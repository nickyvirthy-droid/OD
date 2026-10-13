"""
OMEGA DRAKON • TESTS
Módulo: tests/test_eval_oracle.py
Descrição: GATE do exame padrão (Parte A — eval NOMAD). Roda os goldens
           do modo oracle pelo pipeline REAL (provider falso, sem rede,
           sem LLM) e falha se qualquer um quebrar — é o que transforma
           o eval em porta de CI. A baseline versionada (nota anterior)
           também é conferida: regressão em relação ao que já foi provado
           derruba a suíte.
Interface Viva: Nicky Virthy
"""

from __future__ import annotations

from evals import carregar_baseline, comparar, rodar_modo


def test_goldens_oracle_todos_passam() -> None:
    relatorio = rodar_modo("oracle")
    quebrados = [
        f"{r['id']}: {r['problemas']}"
        for r in relatorio["resultados"]
        if not r["ok"]
    ]
    assert relatorio["total"] >= 8, "conjunto de goldens oraculares encolheu"
    assert not quebrados, f"goldens quebrados: {quebrados}"
    assert relatorio["nota"] == 1.0


def test_nenhum_golden_oracle_caiu_no_llm() -> None:
    """Prova do modo: nenhuma resposta veio do provider falso
    (que devolve 'LLM-NÃO-DEVERIA-ACONTECER')."""
    relatorio = rodar_modo("oracle")
    for r in relatorio["resultados"]:
        assert "LLM-NÃO-DEVERIA-ACONTECER" not in r["resposta"], r["id"]
        assert not r["llm_used"].startswith(("gemma", "qwen")), r["id"]


def test_nao_piorou_em_relacao_a_baseline() -> None:
    baseline = carregar_baseline("oracle")
    if baseline is None:
        return  # baseline ainda não publicada — gate acima já vale
    diff = comparar(rodar_modo("oracle"), baseline)
    assert not diff["piorou"], f"piorou em relação à baseline: {diff['piorou']}"
