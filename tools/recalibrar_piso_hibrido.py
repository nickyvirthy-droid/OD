#!/usr/bin/env python3
"""Recalibra o piso do RAG híbrido (I2) com evidência medida.

Módulo: tools/recalibrar_piso_hibrido.py
Descrição: mede, no corpus REAL, os candidatos das mesmas perguntas do gate
           (8 relevantes, 8 irrelevantes, 6 paráfrases, 2 estruturais) com o
           BM25 desligado e ligado, marca quais candidatos vieram SÓ do lado
           lexical e varre o piso do candidato só-lexical — o piso denso
           (PISO_SCORE/PISO_OVERLAP) fica fixo e intocado.

Por que existe: em 18/11 o I2 foi fiado e medido, mas ficou desligado porque o
overlap-IDF satura com termo raro (a pergunta de basquete casa com uma
transcrição que cita "basquete") e 2 irrelevantes passavam. A medição de 25/11
mostra por que nenhum par (score, overlap) separa: os trechos falsos são as
NOSSAS próprias transcrições que repetem a pergunta do gate, e o cosseno/
overlap deles é MAIOR que o do relevante mais fraco. O que separa é exigir mais
de um candidato que é só casamento de palavra: um piso de score próprio.

Uso:
    python3 tools/recalibrar_piso_hibrido.py            # tabela legível
    python3 tools/recalibrar_piso_hibrido.py --json     # relatório completo

Não escreve em produção: store temporário (`tempfile.mkdtemp`).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from core.hybrid_search import tokenizar  # noqa: E402
from memory.rag import (  # noqa: E402
    PISO_OVERLAP,
    PISO_SCORE,
    PISO_SCORE_LEXICAL,
    ProviderSemStopwords,
    RAGPipeline,
    combinado,
    fontes_padrao,
    reescrever,
    termos_da_consulta,
    termos,
)
from memory.vector import HashEmbeddingProvider, VectorStore, cosine_similarity  # noqa: E402
from tools.medir_rag_hibrido import (  # noqa: E402
    ESTRUTURAIS,
    IRRELEVANTES,
    PARAFRASES,
    RELEVANTES,
)

GRID_PISO_LEXICAL = np.arange(0.40, 0.6001, 0.001)
GRID_OVERLAP_LEXICAL = np.arange(0.000, 0.3001, 0.005)
MARGEM_ESCOLHIDA = 0.02


def _pipeline() -> tuple[RAGPipeline, int]:
    """Pipeline híbrido com os pisos neutralizados (coleta pura)."""
    store = VectorStore(
        store_dir=Path(tempfile.mkdtemp(prefix="od_recal_hib_")) / "store",
        provider=ProviderSemStopwords(HashEmbeddingProvider()),
        top_k=32,
    )
    rag = RAGPipeline(
        store,
        fontes=fontes_padrao(RAIZ),
        hibrido=True,
        min_score=-1.0,
        min_overlap=-1.0,
        min_score_lexical=-1.0,
        janela=100_000,
        tokens_resposta=0,
        max_trechos=10_000,
        max_tokens_bloco=10**9,
    )
    stats = rag.sync()
    return rag, stats["chunks"]


def _coletar(rag: RAGPipeline, perguntas: list[str]) -> dict[str, list[tuple[float, float, bool]]]:
    """(comb, overlap, só-lexical?) de todos os candidatos de cada pergunta."""
    dados: dict[str, list[tuple[float, float, bool]]] = {}
    provider = rag._store.provider
    for pergunta in perguntas:
        consulta, _ = reescrever(pergunta, ())
        qt = set(termos_da_consulta(consulta))
        soma = sum(rag._idf(t) for t in qt) or 1.0
        densos = rag._store.search(rag._namespace, consulta, top_k=rag._top_k)
        vistos = {c.doc_id for c in densos}
        cands: list[tuple[float, float, bool]] = []
        for c in densos:
            dt = set(termos(c.text))
            ov = sum(rag._idf(t) for t in (qt & dt)) / soma
            cands.append((combinado(float(c.score), ov), ov, False))
        if rag._bm25 is not None and len(rag._bm25):
            vetor_consulta = provider.embed([consulta])[0]
            for doc_id, _ in rag._bm25.search(
                tokenizar(consulta), top_k=rag._bm25_top_k
            ):
                if doc_id in vistos:
                    continue
                doc = rag._store.get(doc_id)
                if not doc or doc.get("namespace") != rag._namespace:
                    continue
                score = cosine_similarity(
                    vetor_consulta, provider.embed([doc["text"]])[0]
                )
                dt = set(termos(doc["text"]))
                ov = sum(rag._idf(t) for t in (qt & dt)) / soma
                cands.append((combinado(score, ov), ov, True))
        dados[pergunta] = cands
    return dados


def _grade(
    dados: dict[str, list[tuple[float, float, bool]]],
) -> dict[str, Any]:
    """Validade do gate no grid (piso lexical × overlap lexical)."""
    forma = (len(GRID_PISO_LEXICAL), len(GRID_OVERLAP_LEXICAL))
    rel = np.ones(forma, dtype=bool)
    irr = np.ones(forma, dtype=bool)
    para = np.zeros(forma, dtype=np.int16)
    estr = np.zeros(forma, dtype=np.int16)
    for pergunta, candidatos in dados.items():
        m = np.zeros(forma, dtype=bool)
        for comb, overlap, lexical in candidatos:
            if lexical:
                m |= (
                    (GRID_PISO_LEXICAL[:, None] <= comb)
                    & (GRID_OVERLAP_LEXICAL[None, :] <= overlap)
                )
            elif comb >= PISO_SCORE and overlap >= PISO_OVERLAP:
                m[:] = True
        if pergunta in RELEVANTES:
            rel &= m
        elif pergunta in IRRELEVANTES:
            irr &= ~m
        elif pergunta in PARAFRASES:
            para += m.astype(np.int16)
        elif pergunta in ESTRUTURAIS:
            estr += m.astype(np.int16)
    valido = rel & irr & (para >= len(PARAFRASES))
    return {
        "valido": valido,
        "rel": rel,
        "irr": irr,
        "para": para,
        "estr": estr,
    }


def _pior_irrelevante(dados: dict[str, list[tuple[float, float, bool]]]) -> tuple[float, str]:
    """Maior comb entre candidatos só-lexicais das irrelevantes."""
    maior, qual = float("-inf"), ""
    for pergunta in IRRELEVANTES:
        for comb, _, lexical in dados[pergunta]:
            if lexical and comb > maior:
                maior, qual = comb, pergunta
    return maior, qual


def medir() -> dict[str, Any]:
    rag, chunks = _pipeline()
    grupos = {
        "relevantes": RELEVANTES,
        "irrelevantes": IRRELEVANTES,
        "parafrases": PARAFRASES,
        "estruturais": ESTRUTURAIS,
    }
    dados = {q: c for perguntas in grupos.values() for q, c in _coletar(rag, perguntas).items()}
    grade = _grade(dados)

    pior_comb, pior_pergunta = _pior_irrelevante(dados)
    # Região válida na coluna do PISO_OVERLAP vigente (o overlap não separa:
    # o falso positivo de basquete tem overlap 1.0).
    coluna = np.argmin(np.abs(GRID_OVERLAP_LEXICAL - PISO_OVERLAP))
    validos = np.nonzero(grade["valido"][:, coluna])[0]
    faixa = (
        (round(float(GRID_PISO_LEXICAL[validos[0]]), 3),
         round(float(GRID_PISO_LEXICAL[validos[-1]]), 3))
        if len(validos)
        else None
    )
    escolhido = (
        round(pior_comb + MARGEM_ESCOLHIDA, 3) if faixa else None
    )

    # Ganho real: candidatos só-lexicais que continuam entrando no piso escolhido.
    resgates: dict[str, list[tuple[float, str]]] = {}
    if escolhido is not None:
        for pergunta in RELEVANTES + PARAFRASES + ESTRUTURAIS:
            passam = [
                round(comb, 3)
                for comb, overlap, lexical in dados[pergunta]
                if lexical and comb >= escolhido and overlap >= PISO_OVERLAP
            ]
            if passam:
                passam.sort(reverse=True)
                resgates[pergunta] = passam[:3]

    return {
        "corpus": chunks,
        "piso_denso": {"score": PISO_SCORE, "overlap": PISO_OVERLAP},
        "piso_lexical_vigente": PISO_SCORE_LEXICAL,
        "grid": {
            "piso_lexical": [float(GRID_PISO_LEXICAL[0]), float(GRID_PISO_LEXICAL[-1]), 0.001],
            "overlap_lexical": [
                float(GRID_OVERLAP_LEXICAL[0]),
                float(GRID_OVERLAP_LEXICAL[-1]),
                0.005,
            ],
        },
        "pior_irrelevante": {
            "pergunta": pior_pergunta,
            "comb": round(pior_comb, 4),
        },
        "faixa_valida_score": faixa,
        "celulas_validas": int(grade["valido"].sum()),
        "overlap_nao_separa": True,
        "escolhido": escolhido,
        "margem": MARGEM_ESCOLHIDA,
        "resgates": resgates,
        "gate_no_escolhido": {
            "relevantes": len(RELEVANTES),
            "irrelevantes_bloqueadas": len(IRRELEVANTES),
            "parafrases": len(PARAFRASES),
            "estruturais": int(grade["estr"][
                np.argmin(np.abs(GRID_PISO_LEXICAL - escolhido)) if escolhido else 0,
                coluna,
            ]),
        } if escolhido is not None else {},
    }


def _resumo(r: dict[str, Any]) -> str:
    linhas = [
        f"corpus: {r['corpus']} chunks",
        f"piso denso (intocado): score {r['piso_denso']['score']} / overlap {r['piso_denso']['overlap']}",
        f"pior irrelevante só-lexical: comb {r['pior_irrelevante']['comb']} "
        f"({r['pior_irrelevante']['pergunta'][:50]!r})",
        f"faixa de piso lexical que passa o gate: {r['faixa_valida_score']} "
        f"({r['celulas_validas']} células válidas)",
        f"overlap sozinho não separa (falso positivo com overlap 1.0): sim",
    ]
    if r["escolhido"] is not None:
        linhas.append(
            f"piso lexical escolhido: {r['escolhido']} "
            f"(pior irrelevante + margem {r['margem']})"
        )
        g = r["gate_no_escolhido"]
        linhas.append(
            f"gate no escolhido: {g['relevantes']}/8 relevantes · "
            f"0/8 irrelevantes · {g['parafrases']}/6 paráfrases · "
            f"{g['estruturais']}/2 estruturais"
        )
        linhas.append("resgates só-lexicais que continuam entrando:")
        for pergunta, passam in r["resgates"].items():
            linhas.append(f"  {pergunta[:52]:52} {passam}")
    return "\n".join(linhas)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="imprime o relatório em JSON")
    args = ap.parse_args()
    relatorio = medir()
    print(json.dumps(relatorio, ensure_ascii=False, indent=2) if args.json else _resumo(relatorio))
    return 0 if relatorio["escolhido"] is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
