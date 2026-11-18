#!/usr/bin/env python3
"""Baixa o RESTO de uma playlist do YouTube pelo pipeline oficial.

Ordem do dono (05/11/2026): "faca o resto da lista" (Legiao Urbana, 97
entradas, 8 ja no acervo). Reaproveita as funcoes ja testadas de
integrations/radio_link.py: extrair_entradas, trava_pipeline (flock),
rodar_pipeline, timeout_do_lote e notificar_dono. Lotes de 10, um lote por
execucao do pipeline — o acervo cresce a cada lote e um lote que falha nao
derruba os seguintes.

Lista generica desde 18/11/2026 (o nome nao e mais fixo no codigo — o
primeiro uso foi o Raul Seixas, que parou no restart do od-core de 17/11):

- ``OD_LISTA_URL``   — URL da playlist (padrao: a lista do Legiao Urbana)
- ``OD_LISTA_NOME``  — nome nas notificacoes do Telegram
- ``OD_LISTA_LOG``   — arquivo de log (padrao: logs/radio_link_lista_<slug>.log)

Uso (desanexado): setsid nohup <venv>/bin/python tools/baixar_resto_lista.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

RAIZ = Path("/home/alex/OmegaDrakon")
sys.path.insert(0, str(RAIZ))


def _slug(texto: str) -> str:
    """Legiao Urbana → legiao_urbana (nome de arquivo de log)."""
    return re.sub(r"[^a-z0-9]+", "_", texto.lower()).strip("_")


#: Nome da lista nas notificacoes (ordem do dono: generico, sem fixar artista).
NOME_LISTA = os.environ.get("OD_LISTA_NOME", "Legiao Urbana")
#: Lista do dono (Legiao Urbana). Para outra lista, troque por env.
PLAYLIST = os.environ.get(
    "OD_LISTA_URL",
    "https://www.youtube.com/playlist?list=PLk_SH7F8Y60WEjS87AGhEPBNvyjd3lvxh",
)
LOG = RAIZ / "logs" / os.environ.get(
    "OD_LISTA_LOG", f"radio_link_lista_{_slug(NOME_LISTA)}.log")
LOTE = 10


def carrega_env() -> None:
    """Chaves do .env para o processo (o pipeline le GEMINI_API_KEY do env)."""
    for linha in (RAIZ / ".env").read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


def registra(texto: str) -> None:
    carimbo = time.strftime("%Y-%m-%d %H:%M:%S")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{carimbo} | {texto}\n")


def main() -> int:
    carrega_env()
    from integrations import radio_link as rl

    LOG.parent.mkdir(parents=True, exist_ok=True)
    registra(f"=== inicio: resto da lista do {NOME_LISTA} ===")

    entradas = rl.extrair_entradas(PLAYLIST)
    registra(f"entradas na lista: {len(entradas)}")
    if not entradas:
        rl.notificar_dono(
            f"Lista do {NOME_LISTA}: extracao vazia, nada a fazer.")
        return 1

    acervo = rl._musicas_do_acervo(rl.BASE_MUSICAS / "acervo.db")
    pendentes = [e for e in entradas if not rl._parece_repetida(e["title"], acervo)]
    repetidas = len(entradas) - len(pendentes)
    registra(f"ja no acervo (puladas): {repetidas} | a baixar: {len(pendentes)}")
    rl.notificar_dono(
        f"{NOME_LISTA}: {len(pendentes)} faixa(s) a baixar"
        f" ({repetidas} ja estavam no acervo). Lotes de {min(LOTE, len(pendentes))}."
    )
    if not pendentes:
        registra("nada novo; fim")
        return 0

    falhas = 0
    lotes = 0
    antes = len(acervo)
    for inicio in range(0, len(pendentes), LOTE):
        bloco = pendentes[inicio:inicio + LOTE]
        urls = [str(e["url"]) for e in bloco]
        lotes += 1
        registra(f"lote {lotes}: faixas {inicio + 1}-{inicio + len(bloco)}"
                 f" (timeout {rl.timeout_do_lote(len(urls))}s)")
        try:
            with rl.trava_pipeline():
                codigo = int(rl.rodar_pipeline(
                    urls, timeout=rl.timeout_do_lote(len(urls))) or 0)
        except Exception as exc:
            falhas += 1
            registra(f"lote {lotes} FALHOU: {type(exc).__name__}: {exc}")
            continue
        acervo = rl._musicas_do_acervo(rl.BASE_MUSICAS / "acervo.db")
        registra(f"lote {lotes} codigo={codigo} | acervo agora {len(acervo)}"
                 f" (+{len(acervo) - antes})")
        antes = len(acervo)
        if codigo != 0:
            falhas += 1

    final = rl._musicas_do_acervo(rl.BASE_MUSICAS / "acervo.db")
    registra(f"=== fim: {lotes} lote(s), {falhas} com falha, acervo {len(final)} ===")
    estado = "com falhas" if falhas else "sem falhas"
    rl.notificar_dono(
        f"{NOME_LISTA} (resto da lista) concluido {estado}: {lotes} lote(s),"
        f" acervo agora com {len(final)} faixas. Detalhe: logs/{LOG.name}"
    )
    return 0 if not falhas else 1


if __name__ == "__main__":
    sys.exit(main())
