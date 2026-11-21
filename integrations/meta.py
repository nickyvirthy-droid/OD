"""
OMEGA DRAKON • INTEGRATIONS
Tecnologia que respira.
Módulo: integrations/meta.py
Descrição: Conexão com a Meta — WhatsApp Cloud API (preparada em 21/11/2026,
           pedido do dono no txt.txt: *"preciso preparar sua conexão com o
           Meta AI"*).

           A Meta **não** oferece API pública para "falar com o Meta AI" de
           fora: o caminho real de conversa é o WhatsApp Business Cloud API
           (Graph API). Este módulo entrega o lado do servidor, pronto para
           o app do Meta for Developers:

             · `GET  /webhook/meta` — verificação do webhook:
               `hub.mode=subscribe` + `hub.verify_token` == env e devolve o
               `hub.challenge` em texto puro (a Meta exige corpo cru).
             · `POST /webhook/meta` — mensagens recebidas, autenticadas por
               `X-Hub-Signature-256` (HMAC-SHA256 do corpo com o app secret).
               Texto → orquestrador → resposta enviada de volta pelo Graph
               API.

           **Sem credencial, nada acontece**: `configurado()` é False, a
           verificação responde 503 e o POST 503 — o resto do od-core segue
           igual. As chaves no `.env`:
             OD_META_TOKEN         (Bearer do Graph, system user token)
             OD_META_PHONE_ID      (id do número, não o telefone)
             OD_META_VERIFY_TOKEN  (segredo escolhido por nós, vai no painel)
             OD_META_APP_SECRET    (assinatura do webhook)
             OD_META_GRAPH_VERSION (padrão v21.0)
             OD_META_PROFILE       (perfil do agente; padrão auto)
             OD_META_ROLE          (papel das actions; padrão admin — é o
                                    canal do dono)

           Nada é gravado em arquivo: a conversa usa o histórico do
           orquestrador com `session_id = "meta:<wa_id>"`, igual ao Telegram.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projetti

Baseado em:
  - https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks
  - https://developers.facebook.com/docs/graph-api/webhooks/getting-started
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

from core.logger import get_logger

log = get_logger("omega.integrations.meta")

GRAPH_PADRAO = "v21.0"
LIMITE_TEXTO = 4096  # teto do WhatsApp por mensagem


@dataclass(frozen=True)
class MetaConfig:
    token: str = ""
    phone_id: str = ""
    verify_token: str = ""
    app_secret: str = ""
    graph_version: str = GRAPH_PADRAO
    perfil: str = "auto"
    role: str = "admin"

    def configurado(self) -> bool:
        return bool(self.token and self.phone_id and self.verify_token)


@dataclass(frozen=True)
class MensagemMeta:
    remetente: str
    texto: str
    mid: str = ""
    nome: str = ""
    tipo: str = "text"


def config_do_ambiente(env: Optional[dict[str, str]] = None) -> MetaConfig:
    fonte = os.environ if env is None else env
    return MetaConfig(
        token=fonte.get("OD_META_TOKEN", "").strip(),
        phone_id=fonte.get("OD_META_PHONE_ID", "").strip(),
        verify_token=fonte.get("OD_META_VERIFY_TOKEN", "").strip(),
        app_secret=fonte.get("OD_META_APP_SECRET", "").strip(),
        graph_version=(fonte.get("OD_META_GRAPH_VERSION") or GRAPH_PADRAO).strip(),
        perfil=(fonte.get("OD_META_PROFILE") or "auto").strip(),
        role=(fonte.get("OD_META_ROLE") or "admin").strip(),
    )


def verificar(
    modo: str, token: str, desafio: str, verify_token: str
) -> Optional[str]:
    """Confere a verificação do webhook; devolve o desafio ou None.

    A Meta chama `GET /webhook/meta?hub.mode=subscribe&hub.verify_token=...&
    hub.challenge=...` e exige que o corpo da resposta seja **exatamente** o
    challenge, em texto puro. Token vazio (nosso ou de quem chamou) nunca
    passa: sem segredo configurado a rota não existe.
    """
    if not verify_token or not token:
        return None
    if modo != "subscribe":
        return None
    if not hmac.compare_digest(str(token), str(verify_token)):
        return None
    return str(desafio)


def assinatura_valida(corpo: bytes, cabecalho: Optional[str], app_secret: str) -> bool:
    """True quando `X-Hub-Signature-256: sha256=<hex>` casa com o corpo.

    Fail-closed: sem app secret configurado, nenhuma assinatura vale (o
    webhook não pode ficar aberto só porque falta uma variável).
    """
    if not app_secret or not cabecalho:
        return False
    prefixo, _, recebido = cabecalho.partition("=")
    if prefixo != "sha256" or not recebido:
        return False
    esperado = hmac.new(app_secret.encode("utf-8"), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(recebido.strip().lower(), esperado)


def assinar(corpo: bytes, app_secret: str) -> str:
    """Assinatura no formato da Meta — usada nos testes e em reprocessamento."""
    return "sha256=" + hmac.new(
        app_secret.encode("utf-8"), corpo, hashlib.sha256
    ).hexdigest()


def extrair_mensagens(payload: dict[str, Any]) -> list[MensagemMeta]:
    """Mensagens do payload do webhook (texto ou mídia sem texto).

    O formato é `entry[].changes[].value.messages[]`; `contacts[].profile
    .name` dá o nome de perfil. Eventos de status (entregue/lido) não têm
    `messages` e caem fora naturalmente — a Meta exige 200 neles também.
    """
    if not isinstance(payload, dict):
        return []
    saida: list[MensagemMeta] = []
    for entrada in payload.get("entry") or []:
        if not isinstance(entrada, dict):
            continue
        for mudanca in entrada.get("changes") or []:
            if not isinstance(mudanca, dict):
                continue
            valor = mudanca.get("value") or {}
            if not isinstance(valor, dict):
                continue
            nomes = {
                str(c.get("wa_id") or ""): str((c.get("profile") or {}).get("name") or "")
                for c in (valor.get("contacts") or [])
                if isinstance(c, dict)
            }
            for msg in valor.get("messages") or []:
                if not isinstance(msg, dict):
                    continue
                de = str(msg.get("from") or "").strip()
                if not de:
                    continue
                tipo = str(msg.get("type") or "")
                texto = ""
                if tipo == "text":
                    texto = str((msg.get("text") or {}).get("body") or "").strip()
                elif tipo == "button":
                    texto = str((msg.get("button") or {}).get("text") or "").strip()
                elif tipo == "interactive":
                    interativo = msg.get("interactive") or {}
                    escolha = interativo.get("button_reply") or interativo.get("list_reply") or {}
                    texto = str(escolha.get("title") or "").strip()
                saida.append(
                    MensagemMeta(
                        remetente=de, texto=texto, mid=str(msg.get("id") or ""),
                        nome=nomes.get(de, ""), tipo=tipo,
                    )
                )
    return saida


def _dividir(texto: str, limite: int = LIMITE_TEXTO) -> list[str]:
    """Quebra em pedaços que caibam numa mensagem do WhatsApp."""
    if len(texto) <= limite:
        return [texto]
    partes, atual = [], ""
    for linha in texto.splitlines(keepends=True):
        while len(linha) > limite:  # linha sozinha maior que o teto
            if atual:
                partes.append(atual)
                atual = ""
            partes.append(linha[:limite])
            linha = linha[limite:]
        if len(atual) + len(linha) > limite:
            partes.append(atual)
            atual = linha
        else:
            atual += linha
    if atual:
        partes.append(atual)
    return partes


def enviar_texto(
    para: str, texto: str, cfg: MetaConfig, *, timeout: float = 15.0
) -> int:
    """Envia texto pelo Graph API; devolve quantas mensagens saíram.

    Erro de rede/HTTP levanta `RuntimeError` — quem chama decide (o handler
    loga e responde 200 para a Meta não reentregar o mesmo evento).
    """
    if not cfg.configurado():
        raise RuntimeError("meta_nao_configurada")
    if not para or not texto:
        return 0
    enviadas = 0
    url = f"https://graph.facebook.com/{cfg.graph_version}/{cfg.phone_id}/messages"
    for parte in _dividir(texto):
        corpo = json.dumps(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": para,
                "type": "text",
                "text": {"preview_url": False, "body": parte},
            }
        ).encode("utf-8")
        pedido = urllib.request.Request(
            url, data=corpo, method="POST",
            headers={
                "Authorization": f"Bearer {cfg.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(pedido, timeout=timeout) as resp:
                resp.read()
        except urllib.error.HTTPError as exc:
            detalhe = exc.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"meta_http_{exc.code}: {detalhe}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"meta_rede: {exc.reason}") from exc
        enviadas += 1
    return enviadas


def construir_handler(
    orchestrator: Any,
    cfg: Optional[MetaConfig] = None,
    *,
    enviar: Optional[Callable[..., int]] = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Handler síncrono do POST /webhook/meta (lado do APIServer).

    Cada mensagem de texto passa pelo orquestrador com o histórico daquele
    número (`meta:<wa_id>`) e a resposta volta pelo Graph API. A Meta exige
    200 mesmo quando o processamento falha (senão reentrega o evento); o erro
    fica no log e no retorno.
    """
    cfg = cfg or config_do_ambiente()
    enviar = enviar or enviar_texto

    def handler(payload: dict[str, Any]) -> dict[str, Any]:
        mensagens = extrair_mensagens(payload)
        respondidas, erros = 0, 0
        for msg in mensagens:
            if not msg.texto:
                log.info("Meta: mensagem sem texto ignorada", tipo=msg.tipo)
                continue
            try:
                perfil = cfg.perfil
                if perfil == "auto":
                    from agents.profiles import resolve_auto

                    perfil = resolve_auto(msg.texto)
                resultado = asyncio.run(
                    orchestrator.process(
                        f"meta:{msg.remetente}", perfil, msg.texto,
                        session_id=f"meta:{msg.remetente}", role=cfg.role,
                    )
                )
                resposta = str(getattr(resultado, "text", "") or "").strip()
                if not resposta:
                    resposta = "Não consegui responder agora — tente de novo."
                enviar(msg.remetente, resposta, cfg)
                respondidas += 1
            except Exception as exc:  # um número com problema não derruba o lote
                erros += 1
                log.warn("Meta: falha ao responder", erro=type(exc).__name__)
        return {"ok": True, "recebidas": len(mensagens),
                "respondidas": respondidas, "erros": erros}

    return handler
