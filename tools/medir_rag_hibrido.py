#!/usr/bin/env python3
"""Mede o I2 (Hybrid Search) no RAG — antes/depois no corpus real.

Módulo: tools/medir_rag_hibrido.py
Descrição: compara o RAG com o lado lexical (BM25) DESLIGADO e LIGADO sobre
           o MESMO store/corpus, usando as perguntas já calibradas em
           tests/test_rag.py (8 relevantes, 8 irrelevantes, 6 paráfrases) e
           as 2 paráfrases estruturais declaradas naquele gate.

Por que existe: o item P1 nº 5 pede "ligar o I2 no RAG com medição
antes/depois". O número tem que sair do corpus real, com o piso calibrado
intacto — não de uma amostra inventada.

Uso:
    python3 tools/medir_rag_hibrido.py            # tabela legível
    python3 tools/medir_rag_hibrido.py --json     # relatório completo

Não escreve em produção: store temporário (`tempfile.mkdtemp`).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from memory.rag import (  # noqa: E402
    ProviderSemStopwords,
    RAGPipeline,
    fontes_padrao,
)
from memory.vector import HashEmbeddingProvider, VectorStore  # noqa: E402

# Mesmas listas do gate (tests/test_rag.py). Duplicadas de propósito: o gate
# vive no teste; aqui é medição, e mudar o gate para "caber" na medição seria
# afrouxar a régua.
RELEVANTES = [
    "o que é o projeto nômade e o que a gente absorveu dele",
    "como funciona a política de versionamento do app",
    "quais são as regras de trabalho da casa",
    "o que é o Registro Mestre das peças",
    "quais containers docker fazem parte do ecossistema",
    "quando o CI fica vermelho o que a suíte pega",
    "como é feito o eval do assistente com goldens",
    "qual é a identidade visual da Omega Drakon",
]
IRRELEVANTES = [
    "qual é a previsão do tempo em campo grande",
    "me vende uma receita de bolo de cenoura",
    "qual a distância da terra até marte",
    "quem venceu a copa do mundo de 1994",
    "preciso de um advogado para alugar imóvel",
    "me dá uma piada sobre gato",
    "qual o melhor time de basquete",
    "quanto é 15% de 380 reais",
]
PARAFRASES = [
    "do que trata o material do time nômade que a gente estudou",
    "quais passos sigo pra publicar uma versão nova do aplicativo",
    "como funciona o cadastro das peças artesanais que têm dono",
    "que programas rodam em contêiner aqui no servidor",
    "como vocês testam as respostas antes de liberar",
    "as cores e o estilo gráfico da marca",
]
# As 2 perdidas declaradas como ESTRUTURAIS no piso atual (comb 0.3922 e
# 0.3682 contra irrelevante 0.3929) — candidatas naturais ao resgate lexical.
ESTRUTURAIS = [
    "quando combinamos pra trabalhar juntos no mesmo servidor",
    "como o robô confere o que foi feito antes de responder",
]


def _rodar(rag: RAGPipeline, perguntas: list[str]) -> list[dict[str, Any]]:
    saida = []
    for pergunta in perguntas:
        r = rag.consult(pergunta, papel="admin")
        saida.append({
            "pergunta": pergunta,
            "trechos": len(r.trechos),
            "fontes": sorted({t.titulo or t.source for t in r.trechos}),
            "candidatos": r.candidatos,
            "floor": r.descartados_floor,
            "lexicais": rag.metricas().get("lexicais", 0),
        })
    return saida


def medir() -> dict[str, Any]:
    store = VectorStore(
        store_dir=Path(tempfile.mkdtemp(prefix="od_hybrid_med_")) / "store",
        provider=ProviderSemStopwords(HashEmbeddingProvider()),
        top_k=32,
    )
    desligado = RAGPipeline(store, fontes=fontes_padrao(RAIZ), hibrido=False)
    desligado.sync()
    lexicais_antes = desligado.metricas()["lexicais"]

    ligado = RAGPipeline(store, fontes=fontes_padrao(RAIZ), hibrido=True)
    ligado.sync()

    grupos: dict[str, list[str]] = {
        "relevantes": RELEVANTES,
        "irrelevantes": IRRELEVANTES,
        "parafrases": PARAFRASES,
        "estruturais": ESTRUTURAIS,
    }
    relatorio: dict[str, Any] = {
        "corpus": desligado.dump()["docs"],
        "hibrido": True,
        "grupos": {},
    }
    total_lexicais = 0
    for nome, perguntas in grupos.items():
        antes = _rodar(desligado, perguntas)
        depois = _rodar(ligado, perguntas)
        total_lexicais = ligado.metricas()["lexicais"]
        relatorio["grupos"][nome] = {"antes": antes, "depois": depois}
    relatorio["lexicais_adicionados"] = total_lexicais
    relatorio["lexicais_desligado"] = lexicais_antes
    return relatorio


def _resumo(relatorio: dict[str, Any]) -> str:
    linhas: list[str] = []
    linhas.append(f"corpus: {relatorio['corpus']} chunks")
    linhas.append(
        f"candidatos lexicais adicionados no total: "
        f"{relatorio['lexicais_adicionados']}"
    )
    linhas.append("")
    for nome, grupo in relatorio["grupos"].items():
        antes, depois = grupo["antes"], grupo["depois"]
        n_a = sum(1 for x in antes if x["trechos"])
        n_d = sum(1 for x in depois if x["trechos"])
        linhas.append(f"[{nome}] com trecho: antes {n_a}/{len(antes)} · depois {n_d}/{len(depois)}")
        for a, d in zip(antes, depois):
            marca = "  " if a["trechos"] == d["trechos"] and a["fontes"] == d["fontes"] else "→ "
            linhas.append(
                f"{marca}{a['pergunta'][:58]:58} "
                f"antes {a['trechos']}t floor={a['floor']:<3} "
                f"depois {d['trechos']}t floor={d['floor']:<3}"
            )
            if a["fontes"] != d["fontes"]:
                linhas.append(f"     antes: {a['fontes']}")
                linhas.append(f"     depois: {d['fontes']}")
    return "\n".join(linhas)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="imprime o relatório em JSON")
    args = ap.parse_args()
    relatorio = medir()
    print(json.dumps(relatorio, ensure_ascii=False, indent=2) if args.json else _resumo(relatorio))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
