"""Off-site pelo canal PRIVADO do Telegram — os backups saem de casa.

Ordem do dono (20/10): as 2 HDs externas já recebem snapshot diário
(03:40), mas ficam na MESMA casa do sistema. Ele apontou o canal
`t.me/omegadrakon` como destino ("praticamente ilimitado"), fechou o
canal para Private quando alertei do risco (convite no txt.txt) e
decidiu: **Mega e Dropbox ficam para o futuro**. Custo: R$0.

O que este serviço faz (v1, deliberadamente mínimo): **não inventa
backup novo** — ele ENVIA para o canal os artefatos que os perfis já
gravam localmente:

  * `backups/auto/od-*.tar.gz` — diário (`.env` + `data/` sem fotos,
    ~190 KB);
  * `backups/auto-capturas/od-capturas-*.tar.gz` — semanal (fotos e
    vídeos, ~316 MB → fatiados em partes de ≤ 48 MB).

Contrato:
  * `tick()` — acha o artefato MAIS NOVO de cada perfil que ainda não
    foi enviado (estado em `data/offsite_state.json`, comparação por
    NOME + sha256 → **idempotente**: o mesmo tar nunca sobe duas vezes);
  * envio por `sendDocument` (multipart stdlib — sem dependência);
  * falha = retry no próximo tick + push no celular (cooldown 6 h,
    igual ao backup local);
  * check não-crítico `offsite` no `/health`: ok se o DIÁRIO foi
    enviado nas últimas `OD_OFFSITE_IDADE_H_OK` horas (default 48).

Desligue com `OD_OFFSITE=0`; sem `OD_OFFSITE_CHAT` (id do canal) o
serviço nem constrói — configuração ausente não grita, só fica fora.

Recuperação (a parte que ninguém lembra até precisar): com o canal
privado, os arquivos ficam nas mensagens do canal — para baixar tudo
depois de um desastre, usa-se a conta do dono (Telethon/API_ID do
my.telegram.org) ou o Telegram Desktop logado na conta dele: nada no
sistema depende disso estar instalado antes.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from core.logger import get_logger

log = get_logger("omega.core.offsite")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendDocument"
TAMANHO_PADRAO_FATIA = 48 * 1024 * 1024  # margem sob o limite do Bot API
COOLDOWN_PUSH_S = 6 * 3600.0  # 1 aviso de falha por 6 h (igual backup)


def sha256_de(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def fatiar(caminho: Path, fatia_max: int) -> Iterator[tuple[str, bytes]]:
    """Divide o arquivo em partes (nome, bytes) — ≤ fatia_max cada.

    GERADOR de propósito: o tar das capturas tem ~316 MB e cada parte
    (≤ 48 MB) é lida e enviada de uma vez — o arquivo nunca fica inteiro
    na RAM. Arquivo menor que a fatia vira UMA parte com o nome
    original (o Telegram recebe o tar.gz intacto; só os grandes são
    particionados).
    """
    tamanho = caminho.stat().st_size
    if tamanho <= fatia_max:
        yield caminho.name, caminho.read_bytes()
        return
    total = (tamanho + fatia_max - 1) // fatia_max
    with caminho.open("rb") as f:
        for i in range(total):
            dados = f.read(fatia_max)
            yield f"{caminho.name}.parte{i + 1:02d}de{total:02d}", dados


def _multipart(campos: dict[str, str], nome_arquivo: str, dados: bytes,
               boundary: str) -> bytes:
    """Corpo multipart/form-data (stdlib — sem requests)."""
    pedacos: list[bytes] = []
    for chave, valor in campos.items():
        pedacos.append(
            (f"--{boundary}\r\n"
             f'Content-Disposition: form-data; name="{chave}"\r\n\r\n'
             f"{valor}\r\n").encode("utf-8")
        )
    pedacos.append(
        (f"--{boundary}\r\n"
         f'Content-Disposition: form-data; name="document"; '
         f'filename="{nome_arquivo}"\r\n'
         "Content-Type: application/gzip\r\n\r\n").encode("utf-8")
    )
    pedacos.append(dados)
    pedacos.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(pedacos)


def enviar_documento(token: str, chat_id: str, caminho: Path, legenda: str,
                     *, fatia_max: int = TAMANHO_PADRAO_FATIA,
                     timeout: float = 300.0) -> int:
    """Sobe o arquivo (ou as partes) no canal e devolve quantas partes."""
    total = (caminho.stat().st_size + fatia_max - 1) // fatia_max
    contagem = 0
    for nome, dados in fatiar(caminho, fatia_max):
        contagem += 1
        boundary = "odoffsite0boundary"
        # Na única parte a legenda fica limpa; nas demais, leva o nome
        # da parte para o dono saber o que é cada mensagem no canal.
        sufixo = "" if total == 1 else f" ({nome})"
        corpo = _multipart(
            {"chat_id": chat_id, "caption": f"{legenda}{sufixo}"},
            nome, dados, boundary,
        )
        req = urllib.request.Request(
            TELEGRAM_API.format(token=token), data=corpo,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            carga = json.loads(resp.read().decode("utf-8"))
        if not carga.get("ok"):
            raise OSError(f"Telegram recusou: {carga.get('description')}")
    return contagem


@dataclass
class OffsiteConfig:
    """Configuração do navio (vinda do .env via build_service)."""

    token: str
    chat_id: str
    dir_diario: Path
    dir_capturas: Path
    estado_path: Path
    fatia_max: int = TAMANHO_PADRAO_FATIA
    intervalo_s: float = 30 * 60.0
    idade_ok_s: float = 48 * 3600.0
    nome: str = "offsite"


@dataclass
class OffsiteService:
    """Envia os artefatos locais para o canal privado (tick idempotente)."""

    cfg: OffsiteConfig
    enviar: Callable[..., int] = enviar_documento
    push: Optional[Any] = None
    _ultimo_push_falha: float = field(default=0.0, repr=False)

    # -- estado ---------------------------------------------------------

    def _carregar_estado(self) -> dict[str, Any]:
        try:
            return json.loads(self.cfg.estado_path.read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    def _gravar_estado(self, estado: dict[str, Any]) -> None:
        self.cfg.estado_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cfg.estado_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, self.cfg.estado_path)

    @staticmethod
    def _mais_novo(diretorio: Path, padrao: str) -> Optional[Path]:
        candidatos = sorted(diretorio.glob(padrao))
        return candidatos[-1] if candidatos else None

    # -- ciclo ----------------------------------------------------------

    def tick(self) -> dict[str, Any]:
        """Envia o que ainda não foi enviado; devolve o resumo do ciclo."""
        estado = self._carregar_estado()
        enviados: list[str] = []
        erros: list[str] = []
        for perfil, diretorio, padrao in (
            ("diario", self.cfg.dir_diario, "od-*.tar.gz"),
            ("capturas", self.cfg.dir_capturas, "od-capturas-*.tar.gz"),
        ):
            artefato = self._mais_novo(diretorio, padrao)
            if artefato is None:
                continue
            digest = sha256_de(artefato)
            anterior = estado.get(perfil) or {}
            if (anterior.get("arquivo") == artefato.name
                    and anterior.get("sha256") == digest):
                continue  # já no canal — idempotente
            legenda = (
                f"📦 Omega Drakon — backup {perfil} · {artefato.name} · "
                f"sha256 {digest[:16]}…"
            )
            try:
                partes = self.enviar(
                    self.cfg.token, self.cfg.chat_id, artefato, legenda,
                    fatia_max=self.cfg.fatia_max,
                )
            except Exception as exc:  # best-effort: retry + push
                erros.append(f"{perfil}: {exc}")
                log.warn("Off-site falhou", perfil=perfil, error=str(exc))
                self._avisar_falha(f"{artefato.name}: {exc}")
                continue
            estado[perfil] = {
                "arquivo": artefato.name,
                "sha256": digest,
                "bytes": artefato.stat().st_size,
                "partes": partes,
                "enviado_em": time.time(),
            }
            enviados.append(f"{artefato.name} ({partes} parte(s))")
            log.info("Off-site enviado", perfil=perfil,
                     arquivo=artefato.name, partes=partes)
        if enviados:
            self._gravar_estado(estado)
        return {"enviados": enviados, "erros": erros}

    def _avisar_falha(self, texto: str) -> None:
        """1 push por 6 h (mesma política do backup local)."""
        agora = time.time()
        if self.push is None or agora - self._ultimo_push_falha < COOLDOWN_PUSH_S:
            return
        self._ultimo_push_falha = agora
        try:
            self.push.notify("Off-site pendente", texto,
                             data={"origem": "offsite"})
        except Exception as exc:  # pragma: no cover — push degrada sozinho
            log.warn("Off-site: aviso de push falhou", error=str(exc))

    # -- health / stats -------------------------------------------------

    def check_saude(self) -> dict[str, Any]:
        """Check não-crítico: o DIÁRIO chegou no canal nas últimas N h?"""
        diario = (self._carregar_estado().get("diario") or {})
        enviado = float(diario.get("enviado_em") or 0.0)
        idade = time.time() - enviado
        if enviado and idade <= self.cfg.idade_ok_s:
            horas = idade / 3600.0
            return {
                "ok": True, "status": "up",
                "detail": (f"Off-site ok ({diario.get('arquivo')}, "
                           f"há {horas:.1f} h)."),
            }
        if not enviado:
            motivo = "nunca enviado"
        else:
            motivo = f"último envio há {idade / 3600.0:.0f} h"
        return {
            "ok": False, "status": "degraded",
            "detail": (f"Off-site PENDENTE ({motivo} — canal privado do "
                       "Telegram)."),
        }

    def registrar_no_health(self, health: Any) -> Optional[str]:
        if health is None:
            return None
        health.register(self.cfg.nome,
                        lambda _monitor: self.check_saude(),
                        critical=False)
        return self.cfg.nome

    def snapshot(self) -> dict[str, Any]:
        """Resumo p/ o /dashboard/stats (mesmo formato do bloco backup)."""
        estado = self._carregar_estado()
        ultimo = (estado.get("diario") or {})
        return {
            "canal": f"telegram:{self.cfg.chat_id}",
            "ultimo_diario": ultimo.get("arquivo"),
            "ultimo_envio": ultimo.get("enviado_em"),
        }


def build_service(env: Callable[[str, str], str],
                  push: Optional[Any] = None) -> Optional[OffsiteService]:
    """Monta o serviço a partir do .env (launcher.env). None = fora.

    Ligação mínima: `OD_OFFSITE=0` desliga; sem `OD_OFFSITE_CHAT` (id do
    canal privado, tipo -100…) o serviço não constrói. O token do envio
    é o do bot de MONITORAMENTO por padrão (é o bot do sistema).
    """
    if env("OD_OFFSITE", "1") == "0":
        log.info("Off-site desligado (OD_OFFSITE=0)")
        return None
    chat = env("OD_OFFSITE_CHAT", "").strip()
    token = env("OD_OFFSITE_TOKEN", "").strip() or env(
        "OD_TELEGRAM_MONITOR_TOKEN", "").strip()
    if not chat or not token:
        log.info("Off-site fora — falta OD_OFFSITE_CHAT (id do canal "
                 "privado) ou token do bot")
        return None
    raiz = Path(env("OD_REPO_ROOT", "") or Path(__file__).resolve().parents[1])
    cfg = OffsiteConfig(
        token=token,
        chat_id=chat,
        dir_diario=Path(env("OD_OFFSITE_DIARIO", "") or raiz / "backups" / "auto"),
        dir_capturas=Path(env("OD_OFFSITE_CAPTURAS", "")
                          or raiz / "backups" / "auto-capturas"),
        estado_path=Path(env("OD_OFFSITE_ESTADO", "")
                         or raiz / "data" / "offsite_state.json"),
        fatia_max=int(env("OD_OFFSITE_FATIA_MB", "48")) * 1024 * 1024,
        intervalo_s=float(env("OD_OFFSITE_INTERVALO_MIN", "30")) * 60.0,
        idade_ok_s=float(env("OD_OFFSITE_IDADE_H_OK", "48")) * 3600.0,
    )
    return OffsiteService(cfg=cfg, push=push)
