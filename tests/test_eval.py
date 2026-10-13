"""
OMEGA DRAKON • TESTS
Módulo: tests/test_eval.py
Descrição: Parte A (eval NOMAD) — máquina do exame padrão: carga/validação
           dos goldens, avaliação (funções puras), baseline e CLI.
           O gate de execução (modo oracle ponta a ponta) vive em
           tests/test_eval_oracle.py.
Interface Viva: Nicky Virthy
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals import (
    GoldenInvalido,
    avaliar,
    carregar_baseline,
    carregar_goldens,
    comparar,
    goldens_do_modo,
    gravar_baseline,
)
from evals.avaliacao import resultado_de, usou_llm
from evals.golden import Esperado, Golden
from evals.runner import rodar_modo


def _golden(**campos) -> Golden:
    """Golden de teste com defaults válidos."""
    campos.setdefault("id", "teste")
    campos.setdefault("pergunta", "oi")
    campos.setdefault("esperado", Esperado(contem=("x",)))
    return Golden(**campos)


# ===========================================================================
# Carga e validação dos goldens
# ===========================================================================

class TestCargaDosGoldens:
    def test_arquivo_real_carrega_e_tem_casos(self) -> None:
        goldens = carregar_goldens()
        assert len(goldens) >= 11
        ids = [g.id for g in goldens]
        assert len(ids) == len(set(ids))

    def test_todos_os_modos_tem_casos(self) -> None:
        goldens = carregar_goldens()
        for modo in ("oracle", "e2e", "noretrieval"):
            assert goldens_do_modo(goldens, modo), modo

    def test_casos_oracle_nao_dependem_de_rede(self) -> None:
        """Os goldens do CI (oracle) só podem ser rotas determinísticas —
        nenhum deles aponta para action que exige rede/serviço externo."""
        proibidas = {"clima_venceslau_user", "cotacao_dolar_user"}
        oracle = {g.id for g in goldens_do_modo(carregar_goldens(), "oracle")}
        assert not (oracle & proibidas)

    @pytest.mark.parametrize(
        "bruto, trecho",
        [
            ({"id": "DUP", "pergunta": "oi", "esperado": {"llm": False}}, "id"),
            ({"id": "ok", "pergunta": "oi", "campo Estranho": 1,
              "esperado": {"llm": False}}, "desconhecido"),
            ({"id": "ok", "pergunta": "oi", "modos": ["milagre"],
              "esperado": {"llm": False}}, "modo"),
            ({"id": "ok", "pergunta": "oi", "papel": "rei",
              "esperado": {"llm": False}}, "papel"),
            ({"id": "ok", "pergunta": "oi", "esperado": {}}, "esperado"),
            ({"id": "ok", "pergunta": "oi",
              "esperado": {"regex": ["("]}}, "regex inválida"),
            ({"id": "ok", "pergunta": "oi", "esperado": {"contem": "x",
                                                          "nada_assim": 1}}, "desconhecido"),
        ],
    )
    def test_golden_invalido_aborta_a_carga(self, bruto, trecho) -> None:
        from evals.golden import _parse_golden

        with pytest.raises(GoldenInvalido) as exc:
            _parse_golden(bruto, 1)
        assert trecho in str(exc.value)

    def test_sem_nenhuma_expectativa_e_invalido(self) -> None:
        with pytest.raises(GoldenInvalido, match="expectativa"):
            from evals.golden import _parse_esperado

            _parse_esperado(1, {"rota": None, "llm": None})

    def test_json_invalido_aborta(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "g.jsonl"
        arquivo.write_text("{quebrado", encoding="utf-8")
        with pytest.raises(GoldenInvalido, match="JSON inválido"):
            carregar_goldens(arquivo)

    def test_id_duplicado_aborta(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "g.jsonl"
        linha = json.dumps(
            {"id": "mesmo", "pergunta": "oi", "esperado": {"llm": False}}
        )
        arquivo.write_text(linha + "\n" + linha, encoding="utf-8")
        with pytest.raises(GoldenInvalido, match="duplicado"):
            carregar_goldens(arquivo)

    def test_arquivo_inexistente_aborta(self, tmp_path: Path) -> None:
        with pytest.raises(GoldenInvalido, match="não encontrado"):
            carregar_goldens(tmp_path / "nada.jsonl")

    def test_modo_desconhecido_ao_separar(self) -> None:
        with pytest.raises(GoldenInvalido, match="modo"):
            goldens_do_modo(carregar_goldens(), "turbo")


# ===========================================================================
# Avaliação (funções puras)
# ===========================================================================

class TestAvaliacao:
    def test_tudo_certo_retorna_vazio(self) -> None:
        g = _golden(esperado=Esperado(rota="datetime", llm=False, contem=("hora",)))
        assert avaliar(g, rota="datetime", mensagem="Agora são 10:00. hora",
                       llm_used="") == []

    def test_rota_errada(self) -> None:
        g = _golden(esperado=Esperado(rota="datetime"))
        problemas = avaliar(g, rota="llm", mensagem="", llm_used="gemma")
        assert any("rota esperada" in p for p in problemas)

    def test_llm_falso_quebrou_no_llm(self) -> None:
        g = _golden(esperado=Esperado(llm=False))
        problemas = avaliar(g, rota="llm", mensagem="oi", llm_used="gemma-local")
        assert any("não deveria ir ao LLM" in p for p in problemas)

    def test_llm_falso_passa_em_fastpath(self) -> None:
        """Fastpath tem llm_used preenchido mas NÃO é modelo — é a
        distinção que impede falso negativo em 'fastpath:math'."""
        g = _golden(esperado=Esperado(llm=False, llm_prefix="fastpath:math"))
        assert avaliar(g, rota="action_intent", mensagem="2+2 = 4",
                       llm_used="fastpath:math") == []

    def test_llm_verdadeiro_exige_modelo(self) -> None:
        g = _golden(esperado=Esperado(llm=True))
        problemas = avaliar(g, rota="datetime", mensagem="10:00", llm_used="")
        assert any("esperava resposta do LLM" in p for p in problemas)

    def test_cache_conta_como_llm(self) -> None:
        """Resposta do cache É resposta de modelo — mentir aqui seria
        inflar a métrica."""
        assert usou_llm("cache", "") is True

    def test_contem_case_insensitive(self) -> None:
        g = _golden(esperado=Esperado(contem=("PARIS",)))
        assert avaliar(g, rota="llm", mensagem="é Paris sim",
                       llm_used="gemma") == []
        assert any("não contém" in p for p in
                   avaliar(g, rota="llm", mensagem="Londres", llm_used="gemma"))

    def test_nao_contem_pega_a_alucinacao(self) -> None:
        g = _golden(esperado=Esperado(nao_contem=("OmegaDrakon2026",)))
        problemas = avaliar(g, rota="llm", mensagem="a senha é OmegaDrakon2026",
                            llm_used="gemma")
        assert any("proibido" in p for p in problemas)

    def test_regex(self) -> None:
        g = _golden(esperado=Esperado(regex=(r"^\d{2}:\d{2}$",)))
        assert avaliar(g, rota="datetime", mensagem="14:05", llm_used="") == []
        assert avaliar(g, rota="datetime", mensagem="5h", llm_used="")

    def test_resultado_trunca_resposta(self) -> None:
        g = _golden()
        r = resultado_de(g, rota="llm", mensagem="x" * 5000, llm_used="gemma",
                         latencia_ms=1.0)
        assert len(r.resposta) == 400
        assert r.to_dict()["latencia_ms"] == 1.0


# ===========================================================================
# Baseline — a nota versionada
# ===========================================================================

class TestBaseline:
    def _relatorio(self, modo: str = "oracle") -> dict:
        return {
            "modo": modo,
            "data": "2026-10-13T00:00:00-03:00",
            "total": 3,
            "passaram": 2,
            "nota": 0.6667,
            "resultados": [
                {"id": "a", "ok": True},
                {"id": "b", "ok": False},
                {"id": "c", "ok": True},
            ],
        }

    def test_roundtrip(self, tmp_path: Path) -> None:
        alvo = tmp_path / "baseline-oracle.json"
        gravar_baseline(self._relatorio(), alvo)
        lida = carregar_baseline("oracle", alvo)
        assert lida is not None and lida["nota"] == 0.6667

    def test_sem_arquivo_retorna_none(self, tmp_path: Path) -> None:
        assert carregar_baseline("oracle", tmp_path / "nope.json") is None

    def test_caminho_padrao_por_modo(self) -> None:
        from evals.runner import caminho_baseline

        assert caminho_baseline("e2e").name == "baseline-e2e.json"

    def test_comparar_sem_baseline(self) -> None:
        diff = comparar(self._relatorio(), None)
        assert diff["sem_baseline"] is True
        assert diff["nota_antes"] is None

    def test_comparar_identifica_mudancas(self) -> None:
        antes = self._relatorio()
        depois = {
            **self._relatorio(),
            "resultados": [
                {"id": "a", "ok": True},    # continua
                {"id": "b", "ok": True},    # MELHOROU
                {"id": "c", "ok": False},   # PIOROU
                {"id": "d", "ok": True},    # NOVO
            ],
        }
        diff = comparar(depois, antes)
        assert diff["melhorou"] == ["b"]
        assert diff["piorou"] == ["c"]
        assert diff["novo"] == ["d"]
        assert diff["removido"] == []


# ===========================================================================
# CLI
# ===========================================================================

class TestCLI:
    def _criar_goldens(self, tmp_path: Path) -> Path:
        arquivo = tmp_path / "g.jsonl"
        arquivo.write_text(
            json.dumps({"id": "hora", "pergunta": "que horas são?",
                        "esperado": {"rota": "datetime", "llm": False}})
            + "\n",
            encoding="utf-8",
        )
        return arquivo

    def test_resumo_humano(self) -> None:
        from evals.__main__ import _resumo

        texto = _resumo({
            "modo": "oracle", "data": "x", "total": 2, "passaram": 1,
            "nota": 0.5,
            "resultados": [
                {"id": "bom", "ok": True, "rota": "datetime",
                 "llm_used": "", "problemas": []},
                {"id": "ruim", "ok": False, "rota": "llm",
                 "llm_used": "gemma", "problemas": ["rota esperada 'datetime'"]},
            ],
        })
        assert "1/2" in texto and "✅ bom" in texto and "❌ ruim" in texto
        assert "rota esperada" in texto

    def test_saida_zero_quando_passa(self, tmp_path: Path) -> None:
        from evals.__main__ import main

        arquivo = self._criar_goldens(tmp_path)
        assert main(["--modo", "oracle", "--goldens", str(arquivo)]) == 0

    def test_saida_um_quando_falha(self, tmp_path: Path) -> None:
        from evals.__main__ import main

        arquivo = tmp_path / "g.jsonl"
        arquivo.write_text(
            json.dumps({"id": "impossivel", "pergunta": "que horas são?",
                        "esperado": {"contem": ["ISso NUNCA aparece"]}})
            + "\n",
            encoding="utf-8",
        )
        assert main(["--modo", "oracle", "--goldens", str(arquivo)]) == 1

    def test_saida_grava_json(self, tmp_path: Path) -> None:
        from evals.__main__ import main

        arquivo = self._criar_goldens(tmp_path)
        destino = tmp_path / "relatorio.json"
        main(["--modo", "oracle", "--goldens", str(arquivo),
              "--saida", str(destino)])
        payload = json.loads(destino.read_text(encoding="utf-8"))
        assert payload["nota"] == 1.0

    def test_atualizar_baseline_por_modo(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from evals import runner
        from evals.__main__ import main

        monkeypatch.setattr(
            runner, "PADRAO_BASELINE", str(tmp_path / "baseline-{modo}.json")
        )
        arquivo = self._criar_goldens(tmp_path)
        codigo = main(["--modo", "oracle", "--goldens", str(arquivo),
                       "--atualizar-baseline"])
        assert codigo == 0
        assert (tmp_path / "baseline-oracle.json").exists()


# ===========================================================================
# Relatório (integração leve — sem rede, sem LLM)
# ===========================================================================

class TestRelatorioOracle:
    def test_rodar_modo_oracle_estrutura(self) -> None:
        relatorio = rodar_modo("oracle")
        assert relatorio["modo"] == "oracle"
        assert relatorio["total"] >= 8
        assert relatorio["passaram"] == relatorio["total"]
        assert relatorio["nota"] == 1.0
        for r in relatorio["resultados"]:
            assert r["ok"] is True, r
            assert r["resposta"], r["id"]
