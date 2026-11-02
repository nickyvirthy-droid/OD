"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/radio_agora.py
Descrição: "Tocando agora" da rádio Nicky (Item 1 do dono, 01/11/2026) —
           monta o JSON da seção da página da rádio unindo três fontes
           baratas: o nowplaying do AzuraCast (o que toca, o que vem,
           ouvintes), o acervo.db (curiosidade da música atual) e o
           tocadas.txt (últimas 5 trocas, alimentado pelo webhook).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Decisões registradas (ver iniciar/2026-10-30_conversa_omegadrakon.md):
  - Só stdlib (urllib + sqlite3): o requirements do od-core não ganha
    dependência nova por causa de uma seção da página
  - acervo.db aberto em modo leitura (file:?mode=ro): quem ESCREVE é só
    o pipeline (musica.py v1.8.1, --indexar ou a cada lote); o WAL do
    escritor convive com o leitor sem trava
  - curiosidade com o texto de placeholder ("curiosidade pendente")
    conta como vazia: ~150 músicas ficaram assim no rate limit do
    Gemini (31/10) e a página não exibe pendência como curiosidade
  - tocadas.txt é a fonte das "últimas 5" (ordem do dono: arquivo de
    texto mesmo); sem arquivo ainda → song_history do AzuraCast cobre
    o histórico inicial — nada se perde entre o texto e o histórico
  - locutor falando não é música: "anuncio musica" E vinhetas ("vinheta
    nicky") ficam de fora das últimas, do arquivo e do "Tocando agora"
    — dono, 02/11: "vinhetas e anúncios são locutor falando, não aparece"
  - montar_agora() NUNCA derruba a página: fonte que falhou vira campo
    vazio; erro geral vira {"ok": false} e o handler responde 503
  - cache de 5 s no nowplaying: a página sonda a cada 15 s e cada
    visitante tem IP próprio; sem cache, pico martelaria o AzuraCast
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.request import Request, urlopen

from core.logger import get_logger

log = get_logger("omega.integrations.radio_agora")

BASE_MUSICAS = Path(os.environ.get("MP3_BASE_DIR", "/home/alex/dados/musicas"))
BANCO_ACERVO = BASE_MUSICAS / "acervo.db"          # Item 4 — só o link, nunca o áudio
TOCADAS_ARQ = BASE_MUSICAS / "tocadas.txt"         # Item 1 — últimas 5, texto puro
AZURA_NOWPLAYING = os.environ.get(
    "OD_AGORA_AZURA", "http://127.0.0.1:8091/api/nowplaying/nicky"
)

CURIO_PENDENTE = "curiosidade pendente"   # placeholder do fallback do Gemini
ANUNCIO = "anuncio musica"                # vinheta/locução do AzuraCast
CACHE_S = 5.0
LIMITE_TOCADAS = 5
LIMITE_ARQUIVO = 500                      # rotação do tocadas.txt

_cache: dict[str, Any] = {"em": 0.0, "dados": None}


def _e_locucao(titulo: str) -> bool:
    """O locutor falando (vinheta/anúncio) não é música — não aparece.

    Dono, 02/11: "vinhetas e anúncios são locutor falando, não aparece"
    — vale para as últimas, o tocadas.txt e o "Tocando agora" (que mostra
    "Locução da rádio" no lugar, como já fazia com o anúncio).
    """
    t = (titulo or "").strip().lower()
    return bool(t) and (t == ANUNCIO or "vinheta" in t or t.startswith("anuncio"))


# ---------------------------------------------------------------------------
#  Fontes
# ---------------------------------------------------------------------------

def _nowplaying() -> dict:
    """Now Playing do AzuraCast, com cache de 5 s (compartilhado)."""
    agora = time.monotonic()
    dados = _cache.get("dados")
    if dados is not None and (agora - float(_cache.get("em") or 0)) < CACHE_S:
        return dados
    req = Request(AZURA_NOWPLAYING, headers={"User-Agent": "od-core/1.0"})
    with urlopen(req, timeout=4) as resp:            # stdlib: sem requests
        dados = json.loads(resp.read().decode("utf-8"))
    _cache["em"] = agora
    _cache["dados"] = dados
    return dados


def curiosidade_da_musica(artista: str, titulo: str) -> str:
    """Curiosidade da música no acervo.db (leitura mode=ro, nunca escreve).

    Item 2 (02/11): a mesma fonte da página e da locução falada — quem
    escreve é só o pipeline; aqui só se lê. Placeholder ("curiosidade
    pendente") conta como vazia.
    """
    if not titulo:
        return ""
    try:
        conn = sqlite3.connect(f"file:{BANCO_ACERVO}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as exc:
        log.warn("acervo.db inacessível", error=str(exc))
        return ""
    try:
        linha = None
        if artista:
            linha = conn.execute(
                "SELECT curiosidade FROM musicas"
                " WHERE lower(artista) = lower(?) AND lower(titulo) = lower(?)",
                (artista, titulo),
            ).fetchone()
        if linha is None:                     # casou só pelo título
            linha = conn.execute(
                "SELECT curiosidade FROM musicas WHERE lower(titulo) = lower(?)",
                (titulo,),
            ).fetchone()
    except sqlite3.Error as exc:
        log.warn("consulta ao acervo.db falhou", error=str(exc))
        return ""
    finally:
        conn.close()
    if not linha or not linha[0]:
        return ""
    texto = linha[0].strip()
    if CURIO_PENDENTE in texto.lower():
        return ""                             # pendência não vira curiosidade
    return texto


def _historico(dados: dict) -> list[dict]:
    """Cobertura do AzuraCast: song_history (mais recente primeiro).

    Usa quando o tocadas.txt ainda não existe, nasceu agora (só tem a
    música do ar) ou está ilegível — a página nunca fica sem lista.
    """
    saida = []
    for item in (dados.get("song_history") or [])[:LIMITE_TOCADAS]:
        cancao = item.get("song") or {}
        titulo = (cancao.get("title") or "").strip()
        if not titulo or _e_locucao(titulo):
            continue
        artista = (cancao.get("artist") or "").strip()
        try:
            hora = datetime.fromtimestamp(
                int(item.get("played_at") or 0)).strftime("%H:%M")
        except (TypeError, ValueError, OSError):
            hora = "--:--"
        saida.append({"hora": hora,
                      "nome": f"{artista} - {titulo}".strip(" -")})
    return saida


def _tocadas(dados: dict) -> list[dict]:
    """Linhas do tocadas.txt (mais recente primeiro); sem ele, o histórico.

    Devolve o arquivo inteiro (a rotação o limita a 500): o corte em 5
    acontece DEPOIS de montar_agora tirar a música que está no ar — senão
    a lista das últimas viraria "as últimas 4" em toda troca.
    """
    try:
        if TOCADAS_ARQ.is_file():
            with TOCADAS_ARQ.open("r", encoding="utf-8") as fh:
                linhas = [l.strip() for l in fh if l.strip()]
            saida = []
            for linha in linhas:
                hora, sep, nome = linha.partition(" | ")
                if not sep or not nome:
                    continue
                # linha antiga de vinheta/anúncio (escrita antes do filtro
                # do dono, 02/11) também some da página
                if _e_locucao(nome.rsplit(" - ", 1)[-1]):
                    continue
                saida.append({"hora": hora, "nome": nome})
            if saida:
                return list(reversed(saida))
    except OSError as exc:
        log.warn("tocadas.txt ilegível", error=str(exc))
    return _historico(dados)


def registrar_tocada(payload: dict) -> None:
    """Anexa a música que ENTROU no ar em tocadas.txt (Item 1).

    Chamado pelo wrapper do webhook (runtime/launcher.py::_radio) a cada
    troca do AzuraCast. Nunca lança: a locução da rádio não pode morrer
    por causa do histórico da página.
    """
    try:
        cancao = ((payload or {}).get("now_playing") or {}).get("song") or {}
        titulo = (cancao.get("title") or "").strip()
        if not titulo or _e_locucao(titulo):
            return                            # locutor falando: fora do arquivo
        artista = (cancao.get("artist") or "").strip()
        nome = f"{artista} - {titulo}".strip(" -")
        linhas: list[str] = []
        if TOCADAS_ARQ.is_file():
            with TOCADAS_ARQ.open("r", encoding="utf-8") as fh:
                linhas = [l.rstrip("\n") for l in fh if l.strip()]
        if linhas and linhas[-1].partition(" | ")[2] == nome:
            return                            # retry do webhook: já registrada
        linhas.append(f"{datetime.now():%H:%M} | {nome}")
        if len(linhas) > LIMITE_ARQUIVO:      # rotação (escrita atômica)
            linhas = linhas[-LIMITE_ARQUIVO:]
            tmp = TOCADAS_ARQ.with_suffix(".txt.tmp")
            tmp.write_text("".join(f"{l}\n" for l in linhas), encoding="utf-8")
            os.replace(tmp, TOCADAS_ARQ)
        else:
            with TOCADAS_ARQ.open("a", encoding="utf-8") as fh:
                fh.write(f"{linhas[-1]}\n")
    except Exception as exc:                  # pragma: no cover — nunca quebra a fala
        log.warn("tocadas.txt não atualizado", error=str(exc))


# ---------------------------------------------------------------------------
#  Payload da página
# ---------------------------------------------------------------------------

def montar_agora() -> dict:
    """JSON da seção "Tocando agora" — GET /api/radio/agora (público).

    Contrato (página site/radio.html, polling de 15 s):
      {"ok": true,
       "tocando": {"artista", "titulo", "curiosidade"} | null,
       "proxima": {"artista", "titulo"} | null,
       "ultimas": [{"hora": "14:42", "nome": "Artista - Título"}]  # ≤ 5,
       "ouvintes": 3, "ao_vivo": false,
       "atualizado_em": "2026-11-02T15:55:00"}
    """
    try:
        dados = _nowplaying()
    except Exception as exc:
        log.warn("nowplaying do AzuraCast indisponível", error=str(exc))
        dados = {}
    if not isinstance(dados, dict):
        dados = {}

    cancao = ((dados.get("now_playing") or {}).get("song")) or {}
    titulo = (cancao.get("title") or "").strip()
    artista = (cancao.get("artist") or "").strip()
    tocando: Optional[dict[str, str]] = None
    if titulo:
        if _e_locucao(titulo):
            # locutor no ar (vinheta/anúncio): página mostra a fala,
            # não uma "música"
            tocando = {"artista": "", "titulo": "Locução da rádio", "curiosidade": ""}
        else:
            tocando = {
                "artista": artista,
                "titulo": titulo,
                "curiosidade": curiosidade_da_musica(artista, titulo),
            }

    prox_song = ((dados.get("playing_next") or {}).get("song")) or {}
    prox_titulo = (prox_song.get("title") or "").strip()
    proxima: Optional[dict[str, str]] = None
    if prox_titulo:
        if _e_locucao(prox_titulo):
            proxima = {"artista": "", "titulo": "Locução da rádio"}
        else:
            proxima = {
                "artista": (prox_song.get("artist") or "").strip(),
                "titulo": prox_titulo,
            }

    ultimas = _tocadas(dados)
    if tocando:
        no_ar = f"{tocando['artista']} - {tocando['titulo']}".strip(" -")
        vivas = [u for u in ultimas if u["nome"] != no_ar]
        if not vivas:
            # o arquivo nasceu agora e só tem a música do ar
            vivas = _historico(dados)
        ultimas = vivas
    ultimas = ultimas[:LIMITE_TOCADAS]

    ouvintes = dados.get("listeners") or {}
    try:
        n_ouvintes = int(ouvintes.get("total") or ouvintes.get("current") or 0)
    except (TypeError, ValueError):
        n_ouvintes = 0
    ao_vivo = bool((dados.get("live") or {}).get("is_live"))

    return {
        "ok": True,
        "tocando": tocando,
        "proxima": proxima,
        "ultimas": ultimas,
        "ouvintes": n_ouvintes,
        "ao_vivo": ao_vivo,
        "atualizado_em": datetime.now().isoformat(timespec="seconds"),
    }
