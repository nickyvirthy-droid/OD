"""OMEGA DRAKON • EVALS • RUNNER — executa os goldens por modo.

Três modos (Parte A da absorção do NOMAD, mapeado para o nosso pipeline):

- **oracle**: pipeline REAL com provider falso de resposta fixa.
  Só rotas determinísticas passam (datetime, math fastpath, negações).
  Sem rede, sem LLM, sem custo — é o que roda na suíte/CI.
- **e2e**: `runtime.launcher.build_orchestrator()` de produção + o
  ActionRegistry real + LLM local — a prova de fogo.
- **noretrieval**: mesmo e2e SEM ActionRegistry — isola o quanto as
  actions/retrieval contribuem (LLM puro na linha de frente).

Toda rodada usa `persist=False`: o eval NUNCA escreve em produção
(nem histórico, nem cache) e nunca derruba serviço — não importa nada
aqui dentro do od-core.

Interface Viva: Nicky Virthy
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import time
from pathlib import Path
from typing import Any, Iterable

from evals.avaliacao import Resultado, resultado_de
from evals.golden import (
    MODOS_CONHECIDOS,
    Golden,
    GoldenInvalido,
    carregar_goldens,
    goldens_do_modo,
)

_EVALS_DIR = Path(__file__).parent
PADRAO_GOLDENS = _EVALS_DIR / "goldens.jsonl"
# Baseline por modo (cada modo tem seu conjunto de goldens e sua nota):
PADRAO_BASELINE = _EVALS_DIR / "baseline-{modo}.json"

# Resposta do provider falso do modo oracle: se ela aparecer em algum
# resultado, o golden que deveria ser determinístico CAIU no LLM.
RESPOSTA_ORACLE = "«LLM-NÃO-DEVERIA-ACONTECER»"


# Cache do pipeline RAG do modo oracle: ingestão do corpus real uma vez por
# processo (o store vive em diretório temporário — o eval NUNCA escreve em
# produção; a ingestão de docs/ + knowledge/ custa ~1s).
_oracle_rag: Any = None


def montar_orquestrador(modo: str) -> Any:
    """Monta o pipeline do modo pedido (imports pesados adiados)."""
    if modo not in MODOS_CONHECIDOS:
        raise GoldenInvalido(f"modo {modo!r} desconhecido (válidos: {MODOS_CONHECIDOS})")
    if modo == "oracle":
        from core.orchestrator import Orchestrator, RecordingProvider
        from core.security import SecurityManager
        from tools.actions import build_registry

        global _oracle_rag
        if _oracle_rag is None:
            _oracle_rag = _montar_rag_oracle()
        return Orchestrator(
            providers=[RecordingProvider("oracle", reply=RESPOSTA_ORACLE)],
            action_registry=build_registry(security=SecurityManager(mode="strict")),
            rag=_oracle_rag,
        )

    from runtime.launcher import build_orchestrator

    orch = build_orchestrator()
    if modo == "e2e":
        from runtime.launcher import build_action_registry

        orch.set_action_registry(build_action_registry())
    elif modo == "noretrieval":
        # "noretrieval" = LLM puro na linha de frente: o build de produção
        # liga o RAG (Parte B) — aqui ele é DESLIGADO de propósito para o
        # modo continuar medindo a semântica sem bagagem (e um golden com
        # prompt_nao_contem prova que está desligado).
        orch.set_rag(None)
    return orch


def _montar_rag_oracle() -> Any:
    """RAG do modo oracle: corpus real do repo em store temporário.

    Hermético como os goldens: lê só arquivos do repositório, sem rede,
    sem LLM e sem tocar em data/ (regra da casa: eval nunca escreve em
    produção).
    """
    import tempfile

    from memory.rag import RAGPipeline, fontes_padrao
    from memory.vector import HashEmbeddingProvider, VectorStore
    from memory.rag import ProviderSemStopwords

    raiz = Path(__file__).resolve().parent.parent
    store = VectorStore(
        store_dir=Path(tempfile.mkdtemp(prefix="od_eval_rag_")),
        provider=ProviderSemStopwords(HashEmbeddingProvider()),
        top_k=12,
    )
    pipeline = RAGPipeline(store, fontes=fontes_padrao(raiz))
    pipeline.sync()
    return pipeline


async def rodar_golden(modo: str, golden: Golden, orch: Any) -> Resultado:
    """Roda UM golden (persist=False, usuário dedicado p/ rate limit)."""
    started = time.perf_counter()
    result = await orch.process(
        user_id=f"eval-{modo}-{golden.id}",
        profile=golden.profile,
        text=golden.pergunta,
        role=golden.papel,
        persist=False,
    )
    return resultado_de(
        golden,
        rota=result.route,
        mensagem=result.message,
        llm_used=result.llm_used,
        latencia_ms=(time.perf_counter() - started) * 1000,
        prompt=getattr(result, "prompt", "") or "",
    )


async def rodar_modo_async(
    modo: str,
    goldens: Iterable[Golden] | None = None,
    *,
    caminho_goldens: Path | str | None = None,
) -> dict:
    """Roda todos os goldens do modo e devolve o relatório."""
    todos = list(goldens) if goldens is not None else carregar_goldens(caminho_goldens)
    alvo = goldens_do_modo(todos, modo)
    orch = montar_orquestrador(modo)
    resultados: list[Resultado] = []
    for golden in alvo:
        resultados.append(await rodar_golden(modo, golden, orch))
    passaram = sum(1 for r in resultados if r.ok)
    return {
        "modo": modo,
        "data": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "total": len(resultados),
        "passaram": passaram,
        "nota": round(passaram / len(resultados), 4) if resultados else 0.0,
        "resultados": [r.to_dict() for r in resultados],
    }


def rodar_modo(
    modo: str,
    goldens: Iterable[Golden] | None = None,
    *,
    caminho_goldens: Path | str | None = None,
) -> dict:
    """Síncrono de rodar_modo_async (para CLI e testes)."""
    return asyncio.run(
        rodar_modo_async(modo, goldens, caminho_goldens=caminho_goldens)
    )


# ---------------------------------------------------------------------------
# Baseline — a nota versionada no git
# ---------------------------------------------------------------------------

def caminho_baseline(modo: str, caminho: Path | str | None = None) -> Path:
    """Arquivo de baseline do modo (evals/baseline-<modo>.json)."""
    if caminho is not None:
        return Path(caminho)
    return Path(str(PADRAO_BASELINE).format(modo=modo))


def carregar_baseline(
    modo: str, caminho: Path | str | None = None
) -> dict | None:
    """Baseline do modo lida do arquivo (None quando não existe)."""
    caminho = caminho_baseline(modo, caminho)
    if not caminho.exists():
        return None
    return json.loads(caminho.read_text(encoding="utf-8"))


def gravar_baseline(relatorio: dict, caminho: Path | str | None = None) -> Path:
    """Grava o relatório do modo como baseline (retorna o caminho)."""
    caminho = caminho_baseline(relatorio["modo"], caminho)
    caminho.write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return caminho


def comparar(relatorio: dict, baseline: dict | None) -> dict:
    """Antes/depois: quem melhorou, quem piorou, quem entrou/saiu."""
    if not baseline:
        return {
            "sem_baseline": True,
            "nota_antes": None,
            "nota_depois": relatorio["nota"],
            "melhorou": [],
            "piorou": [],
            "novo": [],
            "removido": [],
        }
    antes = {r["id"]: r["ok"] for r in baseline.get("resultados", [])}
    depois = {r["id"]: r["ok"] for r in relatorio.get("resultados", [])}
    # Só quem EXISTIA antes entra em melhorou/piorou — caso novo é
    # categoria própria (senão todo golden novo que passa viraria
    # "melhorou" e a comparação mentiria).
    melhorou = sorted(
        i for i in depois if i in antes and depois[i] and not antes[i]
    )
    piorou = sorted(
        i for i in depois if i in antes and not depois[i] and antes[i]
    )
    return {
        "sem_baseline": False,
        "nota_antes": baseline.get("nota"),
        "nota_depois": relatorio["nota"],
        "melhorou": melhorou,
        "piorou": piorou,
        "novo": sorted(i for i in depois if i not in antes),
        "removido": sorted(i for i in antes if i not in depois),
    }
