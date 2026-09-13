"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/push.py
Descrição: Push notifications do OmegaDrakon via Firebase Cloud Messaging
           (FCM HTTP v1). Duas metades que o OD precisava para falar com o
           celular sem o app estar aberto:

             1. REGISTRO — os tokens FCM dos dispositivos ficam em
                data/push_devices.json (upsert por token, escrita atômica);
             2. ENVIO — POST em
                https://fcm.googleapis.com/v1/projects/<projeto>/messages:send
                autenticado com a service account do Firebase.

           O serviço é DORMENTE por padrão: sem a credencial
           (OD_FCM_CREDENTIALS ou um dos caminhos candidatos) nada é enviado
           e `enabled` é False — o sistema segue normal, como as outras
           integrações opcionais (visão, MQTT).

           Toda a fachada é best-effort e thread-safe: um push que falha
           nunca derruba alerta, API ou loop de recuperação.

           Dependência: google-auth (troca o JWT da service account por um
           access token OAuth2). O HTTP continua em urllib, do stdlib —
           ver a justificativa no CHANGELOG.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docs/FIREBASE_SETUP.md (projeto Firebase nicky-e4f99, pacote
    com.omegadrakon.nicky)
  - integrations/notifier.py (sink de alertas proativos)
  - docs/ROADMAP_V1.md (§3 v1.2.0 — push FCM para o app Android)
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.core.push")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Escopo OAuth2 exigido pelo FCM HTTP v1.
FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

# Endpoint de envio (o projeto entra no path).
FCM_ENDPOINT = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"

# Caminhos candidatos da credencial de service account, na ordem. O primeiro
# que existir é usado quando OD_FCM_CREDENTIALS não está definido.
CREDENTIAL_CANDIDATES: tuple[str, ...] = (
    "config/firebase-service-account.json",
    "config/fcm-service-account.json",
    "docs/firebase-service-account.json",
)

# Canais Android do app (app/lib/services/push_service.dart).
ANDROID_CHANNEL_ID = "od_alerts"

# Códigos de erro do FCM que significam "este token morreu" — o dispositivo
# sai do registro em vez de ser tentado para sempre.
DEAD_TOKEN_CODES: frozenset[str] = frozenset(
    {"UNREGISTERED", "INVALID_ARGUMENT", "SENDER_ID_MISMATCH"}
)


class PushError(Exception):
    """Falha ao falar com o FCM (credencial, rede ou resposta de erro)."""


# ---------------------------------------------------------------------------
# Transporte HTTP (stdlib) + adaptador do google-auth
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class HttpResponse:
    """Resposta mínima no formato esperado pelo google-auth e pelo sender."""

    status: int
    headers: dict[str, str]
    data: bytes

    def json(self) -> Any:
        """Corpo decodificado como JSON ({} quando vazio/inválido)."""
        try:
            return json.loads(self.data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}


def http_request(
    url: str,
    method: str = "GET",
    body: Optional[bytes] = None,
    headers: Optional[dict[str, str]] = None,
    timeout: float = 10.0,
) -> HttpResponse:
    """Requisição HTTP com urllib (stdlib) — nunca levanta por status 4xx/5xx.

    Erros HTTP viram `HttpResponse` com o status real (é o que o FCM usa para
    dizer que o token morreu); falhas de rede sobem como PushError.
    """
    request = urllib.request.Request(
        url, data=body, headers=dict(headers or {}), method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResponse(
                int(response.status), dict(response.headers), response.read()
            )
    except urllib.error.HTTPError as exc:
        return HttpResponse(
            int(exc.code), dict(exc.headers or {}), exc.read() or b""
        )
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise PushError(f"falha de rede no FCM: {exc}") from exc


class UrllibRequest:
    """Adaptador do protocolo `google.auth.transport.Request` sobre urllib.

    O google-auth precisa de um objeto assim para trocar o JWT da service
    account por um access token. Implementá-lo aqui evita trazer `requests`
    (e mais uma dependência) só por causa do OAuth2.
    """

    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: Optional[bytes] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: float = 10.0,
        **kwargs: Any,
    ) -> HttpResponse:
        return http_request(url, method, body, headers, timeout)


# ---------------------------------------------------------------------------
# Registro de dispositivos
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PushDevice:
    """Um dispositivo registrado para receber push."""

    token: str
    platform: str = "android"
    device: str = ""
    registered_at: float = 0.0
    updated_at: float = 0.0
    sent: int = 0
    failed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "platform": self.platform,
            "device": self.device,
            "registered_at": self.registered_at,
            "updated_at": self.updated_at,
            "sent": self.sent,
            "failed": self.failed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PushDevice":
        return cls(
            token=str(data.get("token") or ""),
            platform=str(data.get("platform") or "android"),
            device=str(data.get("device") or ""),
            registered_at=float(data.get("registered_at") or 0.0),
            updated_at=float(data.get("updated_at") or 0.0),
            sent=int(data.get("sent") or 0),
            failed=int(data.get("failed") or 0),
        )

    def masked_token(self) -> str:
        """Token abreviado para log/API — nunca o valor completo."""
        return _mask(self.token)


class DeviceRegistry:
    """Registro persistente de dispositivos (JSON, escrita atômica).

    O token FCM é a chave: registrar o mesmo token de novo é upsert (o app
    reenvia o token a cada boot e a cada refresh — sem isso o arquivo
    cresceria para sempre).

    Uso:
        registry = DeviceRegistry(Path("data/push_devices.json"))
        registry.register("abc123", device="Redmi Note 14")
        registry.tokens()
    """

    def __init__(
        self,
        path: Path | str,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(path)
        self._clock = clock
        self._lock = threading.RLock()

    # -- Leitura/escrita ----------------------------------------------------

    def _load(self) -> dict[str, PushDevice]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            log.warn("Registro de push ilegível — recomeçando vazio",
                     path=str(self.path), error=type(exc).__name__)
            return {}
        devices: dict[str, PushDevice] = {}
        for item in raw.get("devices", []) if isinstance(raw, dict) else []:
            if not isinstance(item, dict):
                continue
            device = PushDevice.from_dict(item)
            if device.token:
                devices[device.token] = device
        return devices

    def _save(self, devices: dict[str, PushDevice]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": self._clock(),
            "count": len(devices),
            "devices": [d.to_dict() for d in devices.values()],
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(self.path)  # atômico: nunca deixa o arquivo pela metade

    # -- API pública --------------------------------------------------------

    def register(
        self, token: str, platform: str = "android", device: str = ""
    ) -> PushDevice:
        """Registra (ou atualiza) um token. Levanta ValueError se vazio."""
        token = (token or "").strip()
        if not token:
            raise ValueError("token_obrigatorio")
        now = self._clock()
        with self._lock:
            devices = self._load()
            existing = devices.get(token)
            if existing is None:
                entry = PushDevice(
                    token=token,
                    platform=platform or "android",
                    device=device or "",
                    registered_at=now,
                    updated_at=now,
                )
                devices[token] = entry
            else:
                existing.platform = platform or existing.platform
                existing.device = device or existing.device
                existing.updated_at = now
                entry = existing
            self._save(devices)
        log.info("Dispositivo registrado para push",
                 token=entry.masked_token(), platform=entry.platform)
        return entry

    def unregister(self, token: str) -> bool:
        """Remove um token. True quando havia algo para remover."""
        token = (token or "").strip()
        with self._lock:
            devices = self._load()
            if token not in devices:
                return False
            removed = devices.pop(token)
            self._save(devices)
        log.info("Dispositivo removido do push",
                 token=removed.masked_token(), motivo="unregister")
        return True

    def tokens(self) -> list[str]:
        with self._lock:
            return list(self._load())

    def devices(self) -> list[PushDevice]:
        with self._lock:
            return list(self._load().values())

    def get(self, token: str) -> Optional[PushDevice]:
        with self._lock:
            return self._load().get((token or "").strip())

    def mark(self, token: str, *, sent: bool) -> None:
        """Contabiliza um envio (sucesso/falha) para o dispositivo."""
        with self._lock:
            devices = self._load()
            device = devices.get((token or "").strip())
            if device is None:
                return
            if sent:
                device.sent += 1
            else:
                device.failed += 1
            device.updated_at = self._clock()
            self._save(devices)

    def count(self) -> int:
        with self._lock:
            return len(self._load())


# ---------------------------------------------------------------------------
# Sender FCM (HTTP v1)
# ---------------------------------------------------------------------------


class FcmSender:
    """Envia uma notificação para um token FCM via HTTP v1.

    A credencial é a service account do Firebase (JSON). `available` é False
    quando não há credencial válida ou o google-auth não está instalado — e
    nesse caso `send` levanta PushError em vez de estourar ImportError.

    O transporte é injetável (testes passam um dublê e nada sai na rede).
    """

    def __init__(
        self,
        credentials_file: Optional[Path | str] = None,
        project_id: str = "",
        transport: Optional[Callable[..., HttpResponse]] = None,
        timeout: float = 10.0,
    ) -> None:
        self.credentials_file = (
            Path(credentials_file) if credentials_file else None
        )
        self.project_id = project_id or ""
        self._transport = transport or http_request
        self.timeout = timeout
        self._credentials: Any = None
        self._credentials_error: Optional[str] = None
        self._load_credentials()

    # -- Credenciais --------------------------------------------------------

    def _load_credentials(self) -> None:
        """Carrega a service account (silencioso: ausência é estado normal)."""
        path = self.credentials_file
        if path is None or not Path(path).exists():
            self._credentials_error = "credencial_ausente"
            return
        try:
            from google.oauth2 import service_account
        except ImportError:  # pragma: no cover — ambiente sem google-auth
            self._credentials_error = "google_auth_ausente"
            log.warn("google-auth não instalado — push desativado",
                     dependencia="google-auth")
            return
        try:
            self._credentials = service_account.Credentials.from_service_account_file(
                str(path), scopes=[FCM_SCOPE]
            )
        except (ValueError, OSError) as exc:
            self._credentials_error = "credencial_invalida"
            log.warn("Credencial de push inválida — push desativado",
                     path=str(path), error=type(exc).__name__)
            return
        if not self.project_id:
            self.project_id = str(
                getattr(self._credentials, "project_id", "") or ""
            )
        if not self.project_id:
            self._credentials_error = "projeto_desconhecido"
            self._credentials = None
            return
        self._credentials_error = None

    @property
    def available(self) -> bool:
        """True quando há credencial e projeto — ou seja, dá para enviar."""
        return self._credentials is not None and bool(self.project_id)

    @property
    def reason(self) -> str:
        """Motivo quando indisponível ('' quando disponível)."""
        return "" if self.available else (self._credentials_error or "indisponivel")

    def _access_token(self) -> str:
        """Access token OAuth2 (renova sozinho quando expira)."""
        if self._credentials is None:
            raise PushError(f"push indisponivel: {self.reason}")
        if not self._credentials.valid:
            self._credentials.refresh(UrllibRequest())
        return str(self._credentials.token or "")

    # -- Envio --------------------------------------------------------------

    def send(
        self,
        token: str,
        title: str,
        body: str,
        data: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Envia uma notificação para um token.

        Retorna o nome da mensagem do FCM ({"name": ...}). Levanta PushError
        quando o FCM recusa (inclui o motivo e o código do erro).
        """
        if not self.available:
            raise PushError(f"push indisponivel: {self.reason}")
        if not (token or "").strip():
            raise PushError("token_obrigatorio")

        message: dict[str, Any] = {
            "token": token,
            "notification": {"title": title, "body": body},
            "android": {
                "priority": "high",
                "notification": {"channel_id": ANDROID_CHANNEL_ID},
            },
        }
        if data:
            message["data"] = {k: str(v) for k, v in data.items()}

        payload = json.dumps({"message": message}).encode("utf-8")
        response = self._transport(
            FCM_ENDPOINT.format(project=self.project_id),
            "POST",
            payload,
            {
                "Authorization": f"Bearer {self._access_token()}",
                "Content-Type": "application/json; charset=utf-8",
            },
            self.timeout,
        )
        parsed = response.json()
        if response.status >= 400:
            error = (parsed.get("error") or {}) if isinstance(parsed, dict) else {}
            raise PushError(
                "FCM recusou "
                f"status={response.status} code={error.get('status', '')} "
                f"{error.get('message', '')}".strip()
            )
        return parsed if isinstance(parsed, dict) else {}


def _error_code(exc: PushError) -> str:
    """Extrai o código do FCM de uma PushError (ex: UNREGISTERED)."""
    text = str(exc)
    if "code=" not in text:
        return ""
    return text.split("code=", 1)[1].split(maxsplit=1)[0].strip()


# ---------------------------------------------------------------------------
# Fachada
# ---------------------------------------------------------------------------


class PushService:
    """Fachada de push: junta registro de dispositivos e sender FCM.

    Uso no launcher:
        push = build_push_service(DATA_DIR)
        await notifier.notify(...)   # o sink já é push.notify(...)

    Nada aqui levanta por falha de envio: `notify` devolve um resumo com os
    erros por dispositivo (é alerta, não transação).
    """

    def __init__(
        self,
        registry: DeviceRegistry,
        sender: FcmSender,
        enabled: Optional[bool] = None,
    ) -> None:
        self.registry = registry
        self.sender = sender
        self._enabled = enabled
        self._lock = threading.Lock()

    # -- Estado -------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Push ligado? Exige intenção (OD_PUSH_ENABLED) E credencial."""
        if self._enabled is False:
            return False
        if self._enabled is True and not self.sender.available:
            return False
        return self.sender.available

    def status(self) -> dict[str, Any]:
        """Resumo para log/health/API — sem expor tokens completos."""
        return {
            "enabled": self.enabled,
            "reason": "" if self.enabled else self.sender.reason,
            "project_id": self.sender.project_id,
            "devices": self.registry.count(),
            "devices_detail": [
                {
                    "token": d.masked_token(),
                    "platform": d.platform,
                    "device": d.device,
                    "sent": d.sent,
                    "failed": d.failed,
                }
                for d in self.registry.devices()
            ],
        }

    # -- Registro -----------------------------------------------------------

    def register(
        self, token: str, platform: str = "android", device: str = ""
    ) -> PushDevice:
        """Registra um dispositivo (mesmo com push desligado — assim, quando a
        credencial chegar, o aparelho já está lá)."""
        return self.registry.register(token, platform=platform, device=device)

    def unregister(self, token: str) -> bool:
        return self.registry.unregister(token)

    # -- Envio --------------------------------------------------------------

    def notify(
        self,
        title: str,
        body: str,
        data: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Envia para todos os dispositivos registrados.

        Retorna {"ok", "sent", "failed", "errors", "skipped"}. Tokens
        declarados mortos pelo FCM saem do registro; falhas transitórias
        ficam para a próxima (anti-spam é do notifier, não daqui).
        """
        tokens = self.registry.tokens()
        summary: dict[str, Any] = {
            "ok": True,
            "sent": 0,
            "failed": 0,
            "skipped": 0,
            "errors": [],
        }
        if not self.enabled:
            summary.update(ok=False, skipped=len(tokens),
                           reason=self.sender.reason or "push_desligado")
            return summary
        if not tokens:
            return summary

        for token in tokens:
            try:
                self.sender.send(token, title, body, data)
            except PushError as exc:
                summary["failed"] += 1
                self.registry.mark(token, sent=False)
                code = _error_code(exc)
                summary["errors"].append(
                    {"token": _mask(token), "code": code, "error": str(exc)}
                )
                if code in DEAD_TOKEN_CODES:
                    self.registry.unregister(token)
                    log.info("Token morto removido do push",
                             token=_mask(token), code=code)
                else:
                    log.warn("Push falhou", token=_mask(token), code=code)
                summary["ok"] = False
            else:
                summary["sent"] += 1
                self.registry.mark(token, sent=True)

        log.info("Push enviado", enviados=summary["sent"],
                 falhas=summary["failed"], titulo=title)
        return summary

    def sink(self) -> Callable[[str], Any]:
        """Sink plugável no ProactiveNotifier (recebe o texto do alerta)."""

        def _sink(text: str) -> Any:
            return self.notify("OmegaDrakon", text)

        return _sink

    def test(self, title: str = "Teste OD", body: str = "Push funcionando 🎉") -> dict[str, Any]:
        """Notificação de teste para todos os dispositivos registrados."""
        return self.notify(title, body, data={"tipo": "teste"})


def _mask(token: str) -> str:
    """Token abreviado para log — nunca o valor completo."""
    if len(token) <= 12:
        return "***"
    return f"{token[:6]}…{token[-4:]}"


# ---------------------------------------------------------------------------
# Factory a partir do ambiente
# ---------------------------------------------------------------------------


def _find_credentials(explicit: str = "") -> Optional[Path]:
    """Caminho da credencial: OD_FCM_CREDENTIALS ou primeiro candidato."""
    if explicit:
        return Path(explicit)
    for candidate in CREDENTIAL_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return path
    return None


def build_push_service(
    data_dir: Path | str,
    *,
    credentials: Optional[str] = None,
    enabled: Optional[str] = None,
    project_id: Optional[str] = None,
    transport: Optional[Callable[..., HttpResponse]] = None,
) -> PushService:
    """Monta o PushService lendo o ambiente (OD_*).

    Variáveis:
        OD_PUSH_ENABLED     "0" desliga (mesmo com credencial);
                            "1"/ausente = ligado se houver credencial.
        OD_FCM_CREDENTIALS  caminho do JSON da service account (padrão:
                            config/firebase-service-account.json).
        OD_PUSH_PROJECT_ID  força o projeto FCM (padrão: o da credencial).
        OD_PUSH_DEVICES     arquivo do registro (padrão:
                            <data_dir>/push_devices.json).
    """
    env_enabled = (
        enabled if enabled is not None else os.environ.get("OD_PUSH_ENABLED", "")
    )
    want_enabled: Optional[bool] = None
    if env_enabled != "":
        want_enabled = env_enabled != "0"

    creds_path = _find_credentials(
        credentials if credentials is not None
        else os.environ.get("OD_FCM_CREDENTIALS", "")
    )
    devices_file = os.environ.get("OD_PUSH_DEVICES", "") or str(
        Path(data_dir) / "push_devices.json"
    )
    registry = DeviceRegistry(devices_file)
    sender = FcmSender(
        credentials_file=creds_path,
        project_id=(
            project_id if project_id is not None
            else os.environ.get("OD_PUSH_PROJECT_ID", "")
        ),
        transport=transport,
    )
    service = PushService(registry, sender, enabled=want_enabled)
    log.info(
        "Push FCM inicializado",
        enabled=service.enabled,
        motivo=service.sender.reason,
        credencial=str(creds_path) if creds_path else "-",
        dispositivos=registry.count(),
    )
    return service


# ---------------------------------------------------------------------------
# Ação de teste no catálogo (usa o ActionRegistry como os outros módulos)
# ---------------------------------------------------------------------------

_PUSH_SERVICE: Optional[PushService] = None


def configure_push(service: Optional[PushService]) -> None:
    """Injeta o PushService real (chamado pelo launcher/API)."""
    global _PUSH_SERVICE
    _PUSH_SERVICE = service


def current_push() -> Optional[PushService]:
    """PushService configurado, se houver (None = push desligado)."""
    return _PUSH_SERVICE
