"""
OMEGA DRAKON • TESTS
Módulo: tests/test_eval_locomo.py
Descrição: R5 — memória de longa duração medida (subset LOCOMO) e o placar
           de benchmarks que roda no CI. Cobre a validação do subset, o
           motor (determinístico, sem rede), os dois modos de ingestão, o
           adversarial (memória que inventa derruba) e o gate (piso +
           baseline).

           Os números não são enfeite: o exame mede o comportamento real do
           `MemoryGraph` e já achou dois furos (ver docs/CHANGELOG.md).
Interface Viva: Nicky Virthy
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals import benchmarks, locomo
from evals.locomo import (
    MODOS,
    PISO_RECALL5,
    LocomoInvalido,
    carregar_subset,
    rodar_locomo,
    verificar,
)


# ===========================================================================
# Subset e validação
# ===========================================================================

class TestSubset:
    def test_subset_real_carrega_e_tem_casos(self) -> None:
        conversas = carregar_subset()
        assert len(conversas) >= 3
        assert sum(len(c.perguntas) for c in conversas) >= 20
        ids = [c.id for c in conversas]
        assert len(ids) == len(set(ids))

    def test_locomo_exige_longevidade(self) -> None:
        """LOCOMO é memória de LONGA duração: várias sessões, muitos turnos."""
        conversas = carregar_subset()
        assert all(len(c.sessoes) >= 2 for c in conversas)
        assert max(c.turnos for c in conversas) >= 30
        assert sum(c.turnos for c in conversas) >= 60

    def test_todos_os_tipos_existem(self) -> None:
        tipos = {p.tipo for c in carregar_subset() for p in c.perguntas}
        assert tipos == set(locomo.TIPOS)

    def test_temporal_so_roda_onde_faz_sentido(self) -> None:
        """Substituição de fato só existe no modo de produção."""
        temporais = [
            p for c in carregar_subset() for p in c.perguntas if p.tipo == "temporal"
        ]
        assert temporais
        assert all(p.modos == ("producao",) for p in temporais)


# Duas sessões válidas: o conteúdo varia por caso, a forma não.
SESSOES_OK = [["oi", "tchau"], ["bom dia", "até mais"]]


class TestValidacao:
    @pytest.mark.parametrize(
        "bruto, trecho",
        [
            ({"id": "x", "usuario": "u", "sessoes": SESSOES_OK,
              "perguntas": [{"id": "q", "tipo": "single_hop",
                             "pergunta": "oi?", "evidencias": ["oi"]}],
              "campo_estranho": 1}, "desconhecido"),
            ({"id": "x", "usuario": "u", "sessoes": [["oi"]],
              "perguntas": [{"id": "q", "tipo": "single_hop",
                             "pergunta": "oi?", "evidencias": ["oi"]}]},
             "duas sessões"),
            ({"id": "x", "usuario": "u", "sessoes": SESSOES_OK,
              "perguntas": [{"id": "q", "tipo": "milagre",
                             "pergunta": "oi?", "evidencias": ["oi"]}]},
             "tipo"),
            ({"id": "x", "usuario": "u", "sessoes": SESSOES_OK,
              "perguntas": [{"id": "q", "tipo": "single_hop",
                             "pergunta": "oi?"}]}, "evidência"),
            ({"id": "x", "usuario": "u", "sessoes": SESSOES_OK,
              "perguntas": [{"id": "q", "tipo": "adversarial",
                             "pergunta": "oi?", "evidencias": ["oi"],
                             "armadilhas": ["nada"]}]},
             "adversarial"),
            ({"id": "x", "usuario": "u", "sessoes": SESSOES_OK,
              "perguntas": [
                  {"id": "q", "tipo": "single_hop", "pergunta": "oi?",
                   "evidencias": ["oi"]},
                  {"id": "q", "tipo": "single_hop", "pergunta": "tchau?",
                   "evidencias": ["tchau"]},
              ]}, "repetido"),
            ({"id": "x", "usuario": "u", "sessoes": SESSOES_OK,
              "perguntas": [{"id": "q", "tipo": "single_hop",
                             "pergunta": "oi?", "evidencias": ["oi"],
                             "modos": ["milagre"]}]}, "modos"),
        ],
    )
    def test_subset_invalido_aborta_a_carga(self, tmp_path, bruto, trecho) -> None:
        caminho = tmp_path / "subset.jsonl"
        caminho.write_text(json.dumps(bruto) + "\n", encoding="utf-8")
        with pytest.raises(LocomoInvalido) as exc:
            carregar_subset(caminho)
        assert trecho in str(exc.value)


# ===========================================================================
# Motor: medição determinística, sem rede
# ===========================================================================

@pytest.fixture(scope="module")
def exame() -> dict:
    return rodar_locomo()


class TestMotor:
    def test_roda_os_dois_modos(self, exame) -> None:
        assert set(exame["modos"]) == set(MODOS)
        for dados in exame["modos"].values():
            assert dados["perguntas"] >= 20
            assert dados["acertos@5"] <= dados["perguntas"]

    def test_deterministico(self, exame) -> None:
        outro = rodar_locomo()
        for modo in MODOS:
            assert outro["modos"][modo]["recall@5"] == exame["modos"][modo]["recall@5"]
            assert outro["modos"][modo]["mrr"] == exame["modos"][modo]["mrr"]

    def test_modo_turnos_nao_usa_extracao(self, exame) -> None:
        """O modo `turnos` grava cru: se ele recupera e `producao` não, o
        problema é o extrator, não a busca."""
        assert exame["modos"]["turnos"]["recall@5"] >= exame["modos"]["producao"]["recall@5"]

    def test_adversarial_nao_inventa_memoria(self, exame) -> None:
        for modo, dados in exame["modos"].items():
            assert dados["falsos_positivos"] == [], modo

    def test_temporal_respeita_a_substituicao(self, exame) -> None:
        """Fato antigo substituído não pode voltar na busca."""
        resultados = {
            f"{r['conversa']}/{r['id']}": r
            for r in exame["modos"]["producao"]["resultados"]
        }
        cidade = resultados["marli/cidade_atual"]
        assert cidade["ok@1"] is True
        assert any("recife" in texto.casefold() for texto in cidade["obtidos"])

    def test_multihop_precisa_das_duas_evidencias(self, exame) -> None:
        resultados = {
            f"{r['conversa']}/{r['id']}": r
            for r in exame["modos"]["producao"]["resultados"]
        }
        multi = resultados["marli/cidade_e_trabalho"]
        assert multi["ok@5"] is True
        texto = " ".join(multi["obtidos"]).casefold()
        assert "recife" in texto and "enfermagem" in texto


# ===========================================================================
# Gate (o que transforma exame em porta de CI)
# ===========================================================================

class TestGate:
    def test_exame_atual_passa_no_gate(self, exame) -> None:
        assert verificar(exame, locomo.carregar_baseline()) == []

    def test_recall_abaixo_do_piso_reprova(self, exame) -> None:
        ruim = json.loads(json.dumps(exame))
        ruim["modos"]["producao"]["recall@5"] = 0.1
        problemas = verificar(ruim, None)
        assert any("abaixo do piso" in p for p in problemas)

    def test_falso_positivo_reprova(self, exame) -> None:
        ruim = json.loads(json.dumps(exame))
        ruim["modos"]["turnos"]["falsos_positivos"] = ["marli/cachorro"]
        assert any("falso positivo" in p for p in verificar(ruim, None))

    def test_regressao_contra_baseline_reprova(self, exame) -> None:
        baseline = {
            "modos": {
                "producao": {
                    "recall@5": 0.5,
                    "ok": {"marli/nome": True},
                }
            }
        }
        ruim = json.loads(json.dumps(exame))
        for resultado in ruim["modos"]["producao"]["resultados"]:
            if resultado["conversa"] == "marli" and resultado["id"] == "nome":
                resultado["ok@5"] = False
        problemas = verificar(ruim, baseline)
        assert any("regrediu marli/nome" in p for p in problemas)

    def test_piso_publicado_e_o_medido(self, exame) -> None:
        for modo, piso in PISO_RECALL5.items():
            assert exame["modos"][modo]["recall@5"] >= piso, modo


# ===========================================================================
# Placar de benchmarks (o passo do CI)
# ===========================================================================

class TestBenchmarks:
    def test_placar_junta_as_duas_suites(self) -> None:
        placar = benchmarks.rodar()
        assert set(placar["suites"]) == set(benchmarks.BENCHMARKS)
        assert placar["suites"]["respostas"]["total"] >= 11
        assert placar["suites"]["memoria"]["conversas"] >= 3

    def test_placar_atual_passa(self) -> None:
        assert benchmarks.verificar(benchmarks.rodar(("memoria",))) == []

    def test_golden_quebrado_reprova_o_placar(self) -> None:
        placar = {
            "suites": {
                "respostas": {
                    "total": 2,
                    "passaram": 1,
                    "nota": 0.5,
                    "quebrados": ["senha_mqtt_user"],
                    "comparacao": {},
                }
            }
        }
        assert any("senha_mqtt_user" in p for p in benchmarks.verificar(placar))

    def test_suite_desconhecida_nao_roda(self) -> None:
        with pytest.raises(SystemExit):
            benchmarks.rodar(("milagre",))


# ===========================================================================
# Escopo: memória de um usuário nunca aparece para outro
# ===========================================================================

def test_memoria_nao_vaza_entre_usuarios(tmp_path: Path) -> None:
    conversas = carregar_subset()
    marli = next(c for c in conversas if c.id == "marli")
    with locomo._ingerir(marli, "producao", tmp_path) as grafo:
        assert grafo.buscar("marli", "onde eu moro?", semantica=False)
        assert grafo.buscar("clara", "onde eu moro?", semantica=False) == []
