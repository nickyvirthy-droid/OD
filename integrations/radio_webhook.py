"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/radio_webhook.py
Descrição: webhook do locutor da rádio Nicky (integração do legado Nicky
           Locutor, 27/10) — o AzuraCast dispara quando a música muda e o
           od-core monta a fala (frases do banco + notícia G1 + hora +
           clima) e gera o MP3 da locução para a estação tocar.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - analise/Nicky Locutor/nicky-locutor/main.py (montagem da fala, ordem
    das partes e probabilidades mantidas — a voz da rádio é do legado)

Decisões registradas (ver CHANGELOG):
  - Só stdlib para rede (urllib + xml.etree): o requirements do od-core
    não tem feedparser/requests e não vai ganhar dependência nova por
    causa de uma vinheta — RSS do G1 é XML puro, wttr.in é texto puro
  - Frase de banco vazia não anexa ". " (o legado mandava "· · " no ar
    quando o MySQL CasaOS caía; a rádio fala só o que existe)
  - Clima falhou → assinatura do banco fecha a locução (a rádio nunca
    fala sem se despedir; o legado deixava a fala em aberto)
  - "e em ponto" do legado corrigido: "14 horas em ponto" / "14 horas
    e 23 minutos" (o texto vira voz falada, o erro de português ouvia)
  - MP3 gravado em tmp e trocado com os.replace (atômico): o liquidsoap
    lê o arquivo no minuto em que toca — nunca pode ver meio arquivo
  - processar() nunca lança: erro vira {"status": "erro"} e o AzuraCast
    registra a falha no log dele sem derrubar nada
"""

from __future__ import annotations

import asyncio
import os
import random
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional, Union
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from core.logger import get_logger
from integrations.radio import frase_aleatoria, frase_formatada

__signature__ = "OD // CORE"

log = get_logger("omega.integrations.radio_webhook")

TIMEZONE = ZoneInfo("America/Sao_Paulo")
#: Cidade do dono no wttr.in (legado: CIDADE = "Presidente+Venceslau").
CIDADE = "Presidente+Venceslau"
#: Nome da cidade na fala (o legado escrevia por extenso no áudio).
CIDADE_FALA = "Presidente Venceslau"
#: RSS do G1 que o legado puxava (tecnologia e música).
FEEDS_NOTICIA: tuple[str, ...] = (
    "https://g1.globo.com/rss/g1/tecnologia/",
    "https://g1.globo.com/rss/g1/musica/",
)
#: Timeout das buscas externas: o AzuraCast espera o webhook (timeout
#: configurado lá em cima); 3 s por busca + ~2,4 s de síntese cabem.
TIMEOUT_FONTE_S = 3.0


def limpar_pronuncia(texto: Optional[str]) -> str:
    """Marca/título falam como gente: "ft." vira "com participação de" etc.

    Porte literal do legado (main.py limpar_pronuncia) — a rádio nunca
    soletra "feat" no ar.
    """
    if not texto:
        return ""
    texto = texto.lower()
    texto = texto.replace("ft.", " com participação de ")
    texto = texto.replace("feat.", " com participação de ")
    texto = texto.replace("feat", " com participação de ")
    texto = texto.replace("&", " e ")
    texto = texto.replace(" x ", " e ")
    return texto.strip().capitalize()


def _primeira_noticia(xml_bytes: bytes) -> str:
    """Título da primeira notícia de um RSS ("" se o XML não tiver item).

    O legado fazia `feed.entries[0].title.split(':')[-1].strip()` — o G1
    prefixa o título com a editoria ("Tecnologia: Apple anuncia...") e a
    rádio fala só a manchete.
    """
    try:
        raiz = ET.fromstring(xml_bytes)
        item = raiz.find(".//item/title")
        if item is not None and item.text:
            return item.text.split(":")[-1].strip()
    except ET.ParseError as exc:
        log.warn("RSS do G1 veio quebrado", error=str(exc))
    return ""


def noticia_g1(*, timeout_s: float = TIMEOUT_FONTE_S) -> str:
    """Uma manchete do G1 (tecnologia/música); "" se a fonte falhar.

    Rede com timeout curto e tudo em try/except: notícia é enfeite da
    locução, nunca motivo para o webhook estourar.
    """
    try:
        req = Request(
            random.choice(FEEDS_NOTICIA),
            headers={"User-Agent": "OmegaDrakon/1.0 (+radio)"},
        )
        with urlopen(req, timeout=timeout_s) as resp:
            return _primeira_noticia(resp.read(65_536))
    except Exception as exc:  # noqa: BLE001 — rede é terra de surpresa
        log.warn("Notícia G1 indisponível", error=str(exc))
        return ""


def _texto_clima(bruto: str) -> str:
    """wttr.in `format=%t` ("+28°C") → fala da rádio ("28°").

    Porte literal do legado: `replace("+","").replace("C","").strip()`.
    """
    return bruto.replace("+", "").replace("C", "").strip()


def clima_wttr(*, timeout_s: float = TIMEOUT_FONTE_S) -> str:
    """Temperatura agora em wttr.in; "" se a fonte falhar."""
    try:
        req = Request(
            f"https://wttr.in/{CIDADE}?format=%t",
            headers={"User-Agent": "curl/8.0"},
        )
        with urlopen(req, timeout=timeout_s) as resp:
            temp = _texto_clima(resp.read(64).decode("utf-8", "replace"))
        if temp:
            return f"Faz agora {temp} em {CIDADE_FALA}."
    except Exception as exc:  # noqa: BLE001 — rede é terra de surpresa
        log.warn("Clima wttr.in indisponível", error=str(exc))
    return ""


def montar_locucao(
    payload: dict[str, Any],
    db: Any,
    *,
    rng: Any = random,
    agora: Optional[datetime] = None,
    noticia_fn: Optional[Callable[[], str]] = None,
    clima_fn: Optional[Callable[[], str]] = None,
) -> str:
    """Monta o texto da locução a partir do Now Playing do AzuraCast.

    Ordem e probabilidades do legado (main.py radio_webhook):
      1. notícia (15%) — "Giro de notícias Nicky..."
      2. frase da música passada (sempre)
      3. curiosidade do custom_field (70%, só sem notícia)
      4. hora certa projetada no fim da música (50%, só sem notícia)
      5. próxima música (50%, só se houver)
      6. clima (20%) senão assinatura — fecha a fala SEMPRE

    `rng`, `agora`, `noticia_fn` e `clima_fn` são injetáveis: os testes
    rodam determinísticos e sem rede.
    """
    agora = agora or datetime.now(TIMEZONE)
    noticia_fn = noticia_fn or noticia_g1
    clima_fn = clima_fn or clima_wttr

    np = payload.get("now_playing") or {}
    duration = int(np.get("duration") or 0)
    song = np.get("song") or {}
    custom = song.get("custom_fields") or {}

    # Lógica de pronúncia (custom_field do AzuraCast > limpeza automática)
    artista_fala = custom.get("pronuncia_artista") or limpar_pronuncia(
        song.get("artist", "Nicky")
    )
    titulo_fala = custom.get("pronuncia_titulo") or limpar_pronuncia(
        song.get("title", "Sucesso")
    )
    curiosidade = custom.get("curiosidade")

    next_p = payload.get("playing_next") or {}
    next_song = next_p.get("song") or {}
    next_custom = next_song.get("custom_fields") or {}
    next_artista = next_custom.get("pronuncia_artista") or limpar_pronuncia(
        next_song.get("artist", "")
    )
    next_titulo = next_custom.get("pronuncia_titulo") or limpar_pronuncia(
        next_song.get("title", "")
    )

    texto = ""
    deu_noticia = False

    # 1. Notícia (15% chance)
    if rng.random() < 0.15:
        n = noticia_fn()
        if n:
            texto += f"Giro de notícias Nicky. {n}. "
            deu_noticia = True

    # 2. Música passado
    frase_p = frase_formatada(db, "frases_passado", a=artista_fala, t=titulo_fala)
    if frase_p:
        texto += frase_p + ". "

    # 3. Curiosidade (se não deu notícia)
    if not deu_noticia and curiosidade and rng.random() < 0.70:
        texto += frase_aleatoria(db, "intro_curiosidade") + curiosidade + ". "

    # 4. Hora certa (se não deu notícia) — soma a duração da música + 10 s
    #    de processamento (legado). Correção do "e em ponto" do legado.
    if not deu_noticia and rng.random() < 0.50:
        previsao = agora + timedelta(seconds=duration + 10)
        if previsao.minute > 0:
            texto += (
                f"Agora, {previsao.hour} horas e {previsao.minute} minutos. "
            )
        else:
            texto += f"Agora, {previsao.hour} horas em ponto. "

    # 5. Próxima música
    if next_artista and rng.random() < 0.50:
        frase_nx = frase_formatada(
            db, "frases_proxima", a_n=next_artista, t_n=next_titulo
        )
        if frase_nx:
            texto += frase_nx + ". "

    # 6. Finalização: 20% clima; se a fonte falhou (ou o sorteio não deu),
    #    a assinatura do banco fecha a fala — a rádio nunca fala sem se
    #    despedir (decisão registrada; o legado deixava em aberto).
    fechou = False
    if rng.random() < 0.20:
        clima = clima_fn()
        if clima:
            texto += clima + " "
            fechou = True
    if not fechou:
        assinatura = frase_aleatoria(db, "assinaturas")
        if assinatura:
            texto += assinatura
    return texto


def _apagar(caminho: Path) -> None:
    """Remove o tmp se existir — a limpeza nunca pode virar novo erro."""
    try:
        caminho.unlink(missing_ok=True)
    except OSError:  # pragma: no cover — defensivo
        pass


def processar(
    payload: dict[str, Any],
    *,
    tts: Any,
    db: Any,
    destino: Union[str, Path],
    voz: Optional[str] = None,
    rng: Any = random,
    agora: Optional[datetime] = None,
    noticia_fn: Optional[Callable[[], str]] = None,
    clima_fn: Optional[Callable[[], str]] = None,
) -> dict[str, Any]:
    """Webhook completo: monta a fala, gera o MP3 e o entrega ao AzuraCast.

    O `tts` é um PiperTTS (tools/audio/tts.py) com a pele de locução de
    rádio; o MP3 é gravado em tmp e trocado no destino com os.replace
    (atômico) — o liquidsoap lê o arquivo no minuto em que toca.

    Devolve {"status": "ok", "frase": texto, ...} do legado; nunca lança.
    """
    try:
        texto = montar_locucao(
            payload, db, rng=rng, agora=agora,
            noticia_fn=noticia_fn, clima_fn=clima_fn,
        )
    except Exception as exc:  # noqa: BLE001 — montagem nunca derruba nada
        log.warn("Montagem da locução falhou", error=str(exc))
        return {"status": "erro", "message": str(exc)}
    if not texto.strip():
        return {"status": "erro", "message": "locucao_vazia"}

    alvo = Path(destino)
    tmp = alvo.with_name(alvo.stem + ".tmp" + alvo.suffix)
    try:
        alvo.parent.mkdir(parents=True, exist_ok=True)
        ok = asyncio.run(
            tts.synthesize_locucao_to_file(texto, tmp, profile=voz)
        )
        if not ok:
            _apagar(tmp)
            return {"status": "erro", "message": "sintese_falhou"}
        os.replace(tmp, alvo)
    except Exception as exc:  # noqa: BLE001 — webhook nunca derruba nada
        log.warn("Locução da rádio falhou", error=str(exc))
        _apagar(tmp)
        return {"status": "erro", "message": str(exc)}
    log.info("Locução da rádio gerada", arquivo=str(alvo), chars=len(texto))
    return {"status": "ok", "frase": texto, "arquivo": str(alvo)}
