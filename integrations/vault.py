"""
OMEGA DRAKON • INTEGRATIONS
Tecnologia que respira.
Módulo: integrations/vault.py
Descrição: Cofre do sistema — leitura e escrita de segredos no Vaultwarden
           self-hosted pelo CLI oficial `bw` (1ª das 3 interligações de
           ferramenta aprovadas pelo dono em 2026-10-17: Vaultwarden →
           Stirling → Kiwix).

           - **Conta de SERVIÇO separada** (`OD_VAULT_EMAIL`, criada em
             17/10 pelo fluxo de registro com crypto oficial): a conta e a
             master do dono NUNCA são usadas aqui. A master da conta de
             serviço mora só no `.env` (`OD_VAULT_MASTER`) — nem argv, nem
             log, nem doc.
           - `VaultClient`: wraps do `bw` (**pinado 2026.10.0 + Node 22**
             desde 24/10 — a migração fechou o item da dívida §4 com
             apuração viva: em 17/10 os 2026.x crashavam decifrando
             cifras do Vaultwarden **1.36** ("invalid type: JsValue …
             expected a string"; o drill de 15/10 só exercitara cofre
             vazio); re-testado ao vivo em 24/10 com Vaultwarden **1.37.4**
             e a 2026.10.0 + Node 22 completa unlock + list (21 itens,
             parse OK) — pin 2025.12.1 também seguia saudável, migração
             escolhida pelo dono. Node 22 continua OBRIGATÓRIO (Node 18
             panica: "Web Crypto API is unavailable"). E2E completo
             provado na migração: guardar → obter → update sem duplicar
             → apagar → cofre de volta a 21. Senha só via
             `--passwordenv` (env), sessão destravada cacheada em MEMÓRIA
             (thread-safe), JSON de item só por **stdin base64** (nunca em
             argv). Erros honestos e tipados (`bw_ausente`,
             `vault_nao_configurado`, `vault_indisponivel`,
             `vault_master_invalida`, `item_nao_encontrado`…).
           - **Lazy por desenho**: o od-core NÃO depende do cofre para
             subir — o cliente nasce na 1ª ação que usar; cofre fora do ar
             degrada a ação, nunca o boot.
           - `client_padrao()`: fábrica cacheada (uma sessão por processo)
             + `resetar_cliente()` para testes.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docker/tools-compose.yaml (container od-vaultwarden, porta 8480,
    HTTPS via Tailscale Serve :8443 — o SDK exige HTTPS, nem localhost
    HTTP passa)
  - tools/actions/actions.py (actions vault_status/list/get/set)
  - drill E2E de 15/10 (registro com RegisterData oficial + CLI bw)
  - ~/.local/share/bitwarden-cli (dispositivo PRÓPRIO do wrapper;
    login persistido, unlock por sessão; snapshot de rollback
    data.json.bak-2025-pin na migração de 24/10 — o 2025 rejeita keyring
    gravado pela 2026)

Decisões registradas (ver CHANGELOG):
  - CLI oficial em vez de crypto própria em Python: decifragem correta
    por construção (SDK Bitwarden), zero código criográfico nosso
  - `bw` via wrapper /home/alex/.local/bin/bw = **2026.10.0 + Node 22 +
    BITWARDENCLI_APPDATA_DIR próprio** (migração 24/10 medida contra
    Vaultwarden 1.37.4; rollback = ~/.local/opt/bw2025 +
    data.json.bak-2025-pin; Node ≥22 segue obrigatório)
  - Lista devolve SÓ id/nome/tipo — segredo só volta em `obter()`
  - Retry único em sessão expirada (unlock novo + repete); criação NUNCA
    é retentada às cegas (evita duplicar segredo)
"""

from __future__ import annotations

import base64
import copy
import json
import os
import pathlib
import subprocess
import threading
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.integrations.vault")

_ENV_PATH = pathlib.Path(__file__).resolve().parent.parent / ".env"

# Marcas de erro do CLI que significam "sessão invalida — destrava e repete"
_MARCAS_SESSAO = (
    "not logged in",
    "session expired",
    "invalid session",
    "session is no longer valid",
    "requires a new session",
)

# Marcas que significam rede/TLS do lado do cofre (não é erro do bw)
_MARCAS_REDE = (
    "unable to fetch",
    "getaddrinfo",
    "econnrefused",
    "etimedout",
    "fetch failed",
    "network",
    "insecure url",
    "insecureurl",
)


class VaultError(Exception):
    """Erro tipado do cofre — `codigo` vira o campo `error` na action."""

    def __init__(self, codigo: str, mensagem: str) -> None:
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem


def _env(name: str, default: str = "") -> str:
    """Valor de configuração: os.environ primeiro, `.env` depois.

    (Padrão do projeto — igual a `runtime/launcher.env`, sem importar o
    launcher para não amarrar este módulo ao boot.)
    """
    valor = os.environ.get(name)
    if valor:
        return valor
    try:
        if _ENV_PATH.exists():
            for linha in _ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
                linha = linha.strip()
                if not linha or linha.startswith("#") or "=" not in linha:
                    continue
                chave, _, valor = linha.partition("=")
                if chave.strip() == name:
                    return valor.strip().strip('"').strip("'")
    except OSError:
        pass
    return default


def _ping(servidor: str, timeout_s: float = 6.0) -> bool:
    """O cofre responde? GET /api/config (sem corpo sensível)."""
    try:
        req = urllib.request.Request(
            f"{servidor.rstrip('/')}/api/config",
            headers={"User-Agent": "OmegaDrakon-Vault/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return 200 <= resp.status < 500
    except Exception:
        return False


class VaultClient:
    """Cliente do cofre via `bw` — sessão em memória, segredo nunca em argv."""

    def __init__(
        self,
        *,
        bw_bin: str,
        servidor: str,
        email: str,
        master: str,
        org: str = "",
        colecao: str = "",
        timeout_s: float = 30.0,
        runner: Optional[Callable[..., Any]] = None,
        pinger: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self.bw_bin = bw_bin
        self.servidor = servidor
        self.email = email
        self._master = master
        # Org compartilhada (OD_VAULT_ORG/OD_VAULT_COLECAO): itens novos
        # entram lá e as duas contas enxergam. Vazio = cofre pessoal.
        self.org = org
        self.colecao = colecao
        self.timeout_s = timeout_s
        self._runner = runner or subprocess.run
        self._pinger = pinger or _ping
        self._sessao: Optional[str] = None
        self._tranca = threading.Lock()

    # ------------------------------------------------------------------
    # Camada baixa
    # ------------------------------------------------------------------

    def _run(
        self,
        args: list[str],
        *,
        sessao: Optional[str] = None,
        destravar: bool = False,
        dados: Optional[str] = None,
        timeout_s: Optional[float] = None,
    ) -> tuple[int, str, str]:
        """Roda o bw. Senha só via env (--passwordenv); item só via stdin."""
        env = dict(os.environ)
        env["BW_NOINTERACTION"] = "1"
        if sessao:
            env["BW_SESSION"] = sessao
        if destravar:
            env["OD_VAULT_MASTER"] = self._master
        try:
            proc = self._runner(
                [self.bw_bin, *args],
                input=dados,
                capture_output=True,
                text=True,
                timeout=timeout_s or self.timeout_s,
                env=env,
                check=False,
            )
        except FileNotFoundError:
            raise VaultError(
                "bw_ausente",
                f"CLI bw não encontrado em {self.bw_bin} — instale "                 "@bitwarden/cli@2026.10.0 (Node 22) e confira OD_BW_BIN "
                "no .env.",
            ) from None
        except subprocess.TimeoutExpired:
            raise VaultError(
                "vault_timeout",
                f"bw não respondeu em {timeout_s or self.timeout_s:.0f}s "
                f"({args[0] if args else '?'}).",
            ) from None
        return int(proc.returncode), proc.stdout or "", proc.stderr or ""

    @staticmethod
    def _mapeia_falha(saida: str, acao: str) -> VaultError:
        """Converte stderr do bw em erro tipado honesto."""
        baixo = saida.lower()
        if "invalid master password" in baixo:
            return VaultError(
                "vault_master_invalida",
                "Master da conta de serviço recusada — OD_VAULT_MASTER do "
                ".env não é a master de OD_VAULT_EMAIL.",
            )
        if "not logged in" in baixo:
            return VaultError(
                "vault_nao_autenticado",
                "Conta de serviço não logada neste dispositivo — rode "
                "`bw login <email> --passwordenv OD_VAULT_MASTER --raw` "
                "uma vez.",
            )
        if any(m in baixo for m in _MARCAS_SESSAO):
            return VaultError(
                "sessao_expirada",
                "Sessão do bw recusada mesmo após novo unlock — confira "
                "`bw status` e o estado do cofre (conta de serviço logada?).",
            )
        if any(m in baixo for m in _MARCAS_REDE):
            return VaultError(
                "vault_indisponivel",
                f"Cofre inacessível ({acao}): {saida.strip()[:300]}",
            )
        return VaultError("bw_falhou", f"{acao}: {saida.strip()[:400]}")

    def _destravar(self) -> str:
        rc, out, err = self._run(
            ["unlock", "--passwordenv", "OD_VAULT_MASTER", "--raw"],
            destravar=True,
            timeout_s=45.0,
        )
        sessao = out.strip().splitlines()[-1].strip() if out.strip() else ""
        if rc != 0 or not sessao or len(sessao) < 20:
            raise self._mapeia_falha(err or out, "unlock")
        return sessao

    def _sessao_valida(self) -> str:
        with self._tranca:
            if self._sessao:
                return self._sessao
            # bw config server é barato e autocurativo (fonte: OD_VAULT_SERVER)
            self._run(["config", "server", self.servidor], timeout_s=15.0)
            sessao = self._destravar()
            self._sessao = sessao
            return sessao

    def invalidar_sessao(self) -> None:
        with self._tranca:
            self._sessao = None

    def _call(self, args: list[str], *, dados: Optional[str] = None) -> str:
        """Comanda o bw com sessão; sessão morta → destrava e repete UMA vez."""
        sessao = self._sessao_valida()
        rc, out, err = self._run(args, sessao=sessao, dados=dados)
        if rc == 0:
            return out
        falha = f"{out}\n{err}"
        if any(m in falha.lower() for m in _MARCAS_SESSAO):
            self.invalidar_sessao()
            sessao = self._sessao_valida()
            rc, out, err = self._run(args, sessao=sessao, dados=dados)
            if rc == 0:
                return out
            falha = f"{out}\n{err}"
        raise self._mapeia_falha(falha, " ".join(args[:2]))

    # ------------------------------------------------------------------
    # Operações
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Estado do bw + alcançabilidade do cofre (rede separada)."""
        rc, out, err = self._run(["status"], timeout_s=15.0)
        if rc != 0:
            raise self._mapeia_falha(err or out, "status")
        try:
            bruto = json.loads(out)
        except json.JSONDecodeError:
            raise VaultError("bw_falhou", f"status: saída inesperada {out[:200]}") from None
        return {
            "servidor": bruto.get("serverUrl", ""),
            "estado": bruto.get("status", ""),
            "email": bruto.get("userEmail", ""),
            "alcanca": bool(self._pinger(self.servidor)),
        }

    @staticmethod
    def _json_item(bruto: dict[str, Any]) -> dict[str, Any]:
        """Normaliza item → forma pública. `password` SÓ aparece aqui."""
        login = bruto.get("login") or {}
        uris = [u.get("uri", "") for u in (login.get("uris") or []) if isinstance(u, dict)]
        return {
            "id": bruto.get("id", ""),
            "nome": bruto.get("name", ""),
            "tipo": bruto.get("type"),
            "username": login.get("username") or "",
            "password": login.get("password") or "",
            "nota": bruto.get("notes") or "",
            "uris": uris,
            "atualizado_em": bruto.get("revisionDate", ""),
        }

    def listar(self) -> list[dict[str, Any]]:
        """Títulos do cofre — SEM valores (segredo é só em `obter`)."""
        out = self._call(["list", "items"])
        try:
            bruto = json.loads(out)
        except json.JSONDecodeError:
            raise VaultError("bw_falhou", "list: saída não-JSON") from None
        if not isinstance(bruto, list):
            raise VaultError("bw_falhou", "list: formato inesperado")
        itens = [
            {"id": i.get("id", ""), "nome": i.get("name", ""), "tipo": i.get("type")}
            for i in bruto
            if isinstance(i, dict)
        ]
        return sorted(itens, key=lambda i: (i["nome"] or "").casefold())

    def _bruto_por_nome(self, nome: str) -> Optional[dict[str, Any]]:
        alvo = nome.strip().casefold()
        out = self._call(["list", "items"])
        try:
            bruto = json.loads(out)
        except json.JSONDecodeError:
            raise VaultError("bw_falhou", "list: saída não-JSON") from None
        for item in bruto if isinstance(bruto, list) else []:
            if isinstance(item, dict) and (item.get("name") or "").strip().casefold() == alvo:
                return item
        return None

    def obter(self, nome: str) -> dict[str, Any]:
        """Lê o segredo pelo nome exato (case-insensitive)."""
        achado = self._bruto_por_nome(nome)
        if achado is None or not achado.get("id"):
            raise VaultError("item_nao_encontrado", f"Item '{nome}' não está no cofre.")
        out = self._call(["get", "item", achado["id"]])
        try:
            return self._json_item(json.loads(out))
        except json.JSONDecodeError:
            raise VaultError("bw_falhou", "get: saída não-JSON") from None

    def guardar(
        self,
        nome: str,
        password: str,
        *,
        username: str = "",
        nota: str = "",
        uris: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Cria o item se não existe; atualiza se existe (mesmo nome = mesmo item)."""
        nome = nome.strip()
        if not nome or not password:
            raise VaultError("item_invalido", "nome e password são obrigatórios.")
        existente = self._bruto_por_nome(nome)

        if existente is None:
            payload: dict[str, Any] = {
                "type": 1,
                "name": nome,
                "login": {
                    "username": username or None,
                    "password": password,
                    "uris": [{"uri": u} for u in (uris or [])],
                },
            }
            if nota:
                payload["notes"] = nota
            if self.org:
                payload["organizationId"] = self.org
                if self.colecao:
                    payload["collectionIds"] = [self.colecao]
            dados = self._codifica(payload)
            rc, out, err = self._run(
                ["create", "item"],
                sessao=self._sessao_valida(),
                dados=dados,
            )
            if rc != 0:
                raise self._mapeia_falha(err or out, "create")
            try:
                item = json.loads(out)
            except json.JSONDecodeError:
                raise VaultError("bw_falhou", "create: saída não-JSON") from None
            if self.org and self.colecao:
                # bw create IGNORA collectionIds (contrato é chamada
                # dedicada) — item de org sem coleção é invisível pra
                # membros comuns (escopo por coleção; o dono via
                # access_all enxergava, por isso o bug passou)
                self._liga_colecao(item.get("id", ""))
            return {"id": item.get("id", ""), "nome": nome, "criado": True}

        # Atualização: merge sobre o item completo (nunca apaga campo por omissão)
        out = self._call(["get", "item", existente["id"]])
        try:
            doc = json.loads(out)
        except json.JSONDecodeError:
            raise VaultError("bw_falhou", "edit: get prévio não-JSON") from None
        doc = copy.deepcopy(doc)
        login = doc.setdefault("login", {})
        login["password"] = password
        if username:
            login["username"] = username
        if nota:
            doc["notes"] = nota
        if uris:
            login["uris"] = [{"uri": u} for u in uris]
        rc, out, err = self._run(
            ["edit", "item", existente["id"]],
            sessao=self._sessao_valida(),
            dados=self._codifica(doc),
        )
        if rc != 0:
            raise self._mapeia_falha(err or out, "edit")
        try:
            item = json.loads(out)
        except json.JSONDecodeError:
            raise VaultError("bw_falhou", "edit: saída não-JSON") from None
        if self.org and self.colecao and self.colecao not in (
            doc.get("collectionIds") or []
        ):
            # auto-cura: item de org criado antes desta correção sem
            # coleção ganha a coleção certa no primeiro update
            self._liga_colecao(existente["id"])
        return {"id": item.get("id", ""), "nome": nome, "criado": False}

    def apagar(self, nome: str) -> dict[str, Any]:
        """Remove item pelo nome (uso operacional: segredo aposentado)."""
        achado = self._bruto_por_nome(nome)
        if achado is None or not achado.get("id"):
            raise VaultError("item_nao_encontrado", f"Item '{nome}' não está no cofre.")
        rc, out, err = self._run(
            ["delete", "item", achado["id"]],
            sessao=self._sessao_valida(),
        )
        if rc != 0:
            raise self._mapeia_falha(err or out, "delete")
        return {"nome": nome, "apagado": True}

    @staticmethod
    def _codifica(payload: dict[str, Any]) -> str:
        """JSON → base64 com \n (formato de stdin aceito pelo bw)."""
        bruto = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return base64.b64encode(bruto).decode("ascii") + "\n"

    def _liga_colecao(self, item_id: str) -> None:
        """Anexa o item à coleção da org (bw edit item-collections).

        Create/update do bw IGNORAM ``collectionIds`` no payload: a
        coleção só grava por chamada dedicada, cujo corpo é o **array**
        de ids codificado. Item de org sem coleção é invisível pra
        membros comuns (escopo por coleção) — o dono via access_all
        enxergava tudo, por isso o bug passou despercebido.
        """
        if not self.colecao:
            return
        bruto = json.dumps([self.colecao]).encode("utf-8")
        dados = base64.b64encode(bruto).decode("ascii") + "\n"
        rc, out, err = self._run(
            ["edit", "item-collections", item_id],
            sessao=self._sessao_valida(),
            dados=dados,
        )
        if rc != 0:
            raise self._mapeia_falha(err or out, "edit")


# ---------------------------------------------------------------------------
# Fábrica cacheada (uma sessão por processo — lazy, nunca no boot)
# ---------------------------------------------------------------------------

_CLIENTE: Optional[VaultClient] = None


def client_padrao() -> Optional[VaultClient]:
    """Cliente do cofre ou None se `OD_VAULT_*` não configurado no .env."""
    global _CLIENTE
    if _CLIENTE is None:
        servidor = _env("OD_VAULT_SERVER")
        email = _env("OD_VAULT_EMAIL")
        master = _env("OD_VAULT_MASTER")
        if not (servidor and email and master):
            return None
        _CLIENTE = VaultClient(
            bw_bin=_env("OD_BW_BIN", "bw"),
            servidor=servidor,
            email=email,
            master=master,
            org=_env("OD_VAULT_ORG"),
            colecao=_env("OD_VAULT_COLECAO"),
        )
        log.info(
            "Cofre do sistema configurado",
            servidor=servidor,
            conta=email,
            org=_env("OD_VAULT_ORG") or "pessoal",
        )
    return _CLIENTE


def resetar_cliente() -> None:
    """Esquece a sessão em memória (testes / troca de configuração)."""
    global _CLIENTE
    _CLIENTE = None
