"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/radio_traducao.py
Descrição: tradução da letra da música do ar para o português do Brasil — a
           "lista paralela" da área do ouvinte (ordem do dono, 17/11/2026:
           "letra de musica internacional poderia ter uma lista paralela com
           a tradução").
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Decisões registradas (ver iniciar/2026-11-17_conversa_omegadrakon.md §15):
  - Nada de serviço de tradução pago nem dependência nova: quem traduz é a
    cadeia de LLM do próprio OD (regra 19 — Gemini, Groq e o llama-server
    local, nessa ordem), reconfigurável em `OD_TRADUCAO_PROVIDERS`.
  - Cache em arquivo (`data/radio_traducao.json`), chaveado por
    artista|título **mais um hash curto da letra**: se a fonte devolver uma
    versão diferente da letra, a tradução velha não é servida. Acerto vale
    30 dias; falha fica 10 min para não martelar a cota a cada sondagem de
    15 s da página.
  - Letra que já está em português não vira "tradução igual ao original": o
    modelo responde `JA_PT`, o motivo fica no cache e a página esconde a
    coluna.
  - NUNCA levanta exceção: devolve `{"ok": False, "motivo": ...}` e a letra
    original continua na tela.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Optional

from core.logger import get_logger

log = get_logger("omega.integrations.radio_traducao")

CACHE = Path(
    os.environ.get("OD_RADIO_TRADUCAO_CACHE", "data/radio_traducao.json")
)
TTL_OK_S = 30 * 24 * 3600          # tradução boa praticamente não vence
TTL_JA_PT_S = 7 * 24 * 3600        # "já está em português" idem
TTL_FALHA_S = 10 * 60              # falha do LLM: nova tentativa em 10 min
CACHE_MAX = 800
LIMITE_LETRA = 12000               # ~3 mil palavras: acima disso nem tenta
MAX_TOKENS = int(os.environ.get("OD_TRADUCAO_MAX_TOKENS", "1500"))

INSTRUCAO = (
    "Você é um tradutor literário de letras de música. Traduza a letra abaixo "
    "para o português do Brasil, preservando as quebras de linha, a pontuação "
    "e o sentido poético (nada de tradução palavra por palavra). Não explique, "
    "não comente, não numere e não repita o original: devolva SOMENTE a "
    "tradução. Se a letra já estiver em português, devolva exatamente: JA_PT"
)

_MARCA_JA_PT = {"ja_pt", "japt", "ja pt", "ja_em_portugues"}


def _normaliza_texto(texto: str) -> str:
    """Minúsculas, sem acento e sem pontuação — só para a marca JA_PT."""
    decomposto = unicodedata.normalize("NFKD", (texto or "").lower())
    sem_acento = "".join(
        c for c in decomposto
        if not unicodedata.combining(c) and (c.isalnum() or c in " _")
    )
    return re.sub(r"\s+", " ", sem_acento).strip()


def _e_ja_portugues(texto: str) -> bool:
    return _normaliza_texto(texto) in _MARCA_JA_PT


def chave_do_cache(artista: str, titulo: str, letra: str) -> str:
    """Chave estável: artista|título + hash curto da letra (versão importa)."""
    base = f"{(artista or '').strip().lower()}|{(titulo or '').strip().lower()}"
    digest = hashlib.sha1((letra or "").encode("utf-8")).hexdigest()[:12]
    return f"{base}|{digest}"


def _le_cache(cache: Path) -> dict[str, Any]:
    try:
        dados = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _grava_cache(cache: Path, dados: dict[str, Any]) -> None:
    """Grava por arquivo temporário — leitor nunca vê JSON pela metade."""
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        if len(dados) > CACHE_MAX:                # descarta as mais antigas
            for chave, _ in sorted(
                dados.items(), key=lambda kv: float(kv[1].get("em") or 0)
            )[: len(dados) - CACHE_MAX]:
                dados.pop(chave, None)
        temporario = cache.with_suffix(cache.suffix + ".tmp")
        temporario.write_text(
            json.dumps(dados, ensure_ascii=False), encoding="utf-8"
        )
        temporario.replace(cache)
    except OSError as exc:                        # cache é enfeite, não defeito
        log.warn("cache de tradução não gravou", error=str(exc))


def _cadeia() -> list[Any]:
    """Providers de LLM na ordem da regra 19 (ou `OD_TRADUCAO_PROVIDERS`)."""
    from core.llm import GeminiProvider, GroqProvider, OpenAICompatProvider

    ordem = [
        parte.strip().lower()
        for parte in os.environ.get(
            "OD_TRADUCAO_PROVIDERS",
            os.environ.get("OD_CHAT_PROVIDERS", "gemini,groq,local"),
        ).split(",")
        if parte.strip()
    ]
    saida: list[Any] = []
    for nome in ordem:
        if nome in ("gemini", "gemini-online", "online"):
            provider = GeminiProvider(
                model=os.environ.get("OD_GEMINI_MODEL", "gemini-3-flash-preview"),
                api_key=os.environ.get("GEMINI_API_KEY", ""),
                timeout=float(os.environ.get("OD_GEMINI_TIMEOUT_S", "30")),
                max_tokens=MAX_TOKENS,
                temperature=0.2,
            )
            if provider.configurado:
                saida.append(provider)
        elif nome == "groq":
            provider = GroqProvider(
                model=os.environ.get("OD_GROQ_MODEL", "openai/gpt-oss-120b"),
                api_key=os.environ.get("GROQ_API_KEY", ""),
                base_url=os.environ.get(
                    "OD_GROQ_URL", "https://api.groq.com/openai/v1"
                ),
                timeout=float(os.environ.get("OD_GROQ_TIMEOUT_S", "45")),
                max_tokens=MAX_TOKENS,
                temperature=0.2,
            )
            if provider.configurado:
                saida.append(provider)
        elif nome in ("local", "llama", "gemma-local"):
            saida.append(
                OpenAICompatProvider(
                    name="gemma-local",
                    base_url=os.environ.get("OD_LLM_URL", "http://127.0.0.1:8081"),
                    timeout=float(os.environ.get("OD_LLM_TIMEOUT_S", "240")),
                    max_tokens=MAX_TOKENS,
                    temperature=0.2,
                )
            )
    return saida


async def _pede(provider: Any, prompt: str) -> Optional[str]:
    """`generate` do provider (async); aceita dublê síncrono nos testes."""
    resultado = provider.generate(prompt)
    if asyncio.iscoroutine(resultado) or isinstance(resultado, asyncio.Future):
        resultado = await resultado
    return resultado


def _prompt(artista: str, titulo: str, letra: str) -> str:
    nome = f"{artista} — {titulo}".strip(" —")
    return f"{INSTRUCAO}\n\nMúsica: {nome}\n\nLetra:\n{letra}"


def montar_traducao(
    artista: str,
    titulo: str,
    letra: str,
    *,
    cache_arq: Optional[Path] = None,
    provedores: Optional[list[Any]] = None,
    agora: Optional[float] = None,
) -> dict[str, Any]:
    """Tradução da letra do ar — contrato da área do ouvinte.

    {"ok": True, "texto": str, "cache": bool}
    {"ok": False, "motivo": "sem_letra"|"letra_longa"|"ja_em_portugues"|
                             "indisponivel"}

    NUNCA levanta exceção: a página mostra a letra original e o resto segue.
    """
    titulo = (titulo or "").strip()
    letra = (letra or "").strip()
    if not titulo or not letra:
        return {"ok": False, "motivo": "sem_letra"}
    if len(letra) > LIMITE_LETRA:
        return {"ok": False, "motivo": "letra_longa"}

    cache_arq = cache_arq or CACHE
    chave = chave_do_cache(artista, titulo, letra)
    relogio = time.time() if agora is None else agora

    cache = _le_cache(cache_arq)
    entrada = cache.get(chave)
    if isinstance(entrada, dict):
        texto = str(entrada.get("texto") or "")
        motivo = str(entrada.get("motivo") or "")
        if motivo == "ja_em_portugues":
            ttl = TTL_JA_PT_S
        elif texto:
            ttl = TTL_OK_S
        else:
            ttl = TTL_FALHA_S
        if relogio - float(entrada.get("em") or 0) < ttl:
            if texto:
                return {"ok": True, "texto": texto, "cache": True}
            return {"ok": False, "motivo": motivo or "indisponivel"}

    provedores = _cadeia() if provedores is None else provedores
    if not provedores:
        return {"ok": False, "motivo": "indisponivel"}

    prompt = _prompt(artista, titulo, letra)
    erro = ""
    for provider in provedores:
        try:
            resposta = asyncio.run(_pede(provider, prompt))
        except Exception as exc:                  # provider fora/cota: próximo
            erro = f"{type(exc).__name__}: {exc}"
            log.warn("tradução falhou no provider",
                     provider=getattr(provider, "name", "?"), error=erro[:200])
            continue
        texto = (resposta or "").strip()
        if not texto:
            erro = "resposta vazia"
            continue
        if _e_ja_portugues(texto):
            cache[chave] = {"motivo": "ja_em_portugues", "em": relogio}
            _grava_cache(cache_arq, cache)
            return {"ok": False, "motivo": "ja_em_portugues"}
        cache[chave] = {
            "texto": texto,
            "em": relogio,
            "provedor": getattr(provider, "name", ""),
        }
        _grava_cache(cache_arq, cache)
        return {"ok": True, "texto": texto, "cache": False}

    cache[chave] = {"motivo": "indisponivel", "em": relogio, "erro": erro[:200]}
    _grava_cache(cache_arq, cache)
    return {"ok": False, "motivo": "indisponivel"}
