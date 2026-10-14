"""
OMEGA DRAKON • TESTS
Módulo: tests/test_saude.py
Descrição: Parte C NOMAD — referência médica determinística. Cobre o
           carregamento/matching das coleções (tools/saude), as actions
           saude_condicao/saude_interacoes/saude_medicamento, os gatilhos
           (_detect_saude), o formatador com disclaimer OBRIGATÓRIO, a
           permissão do papel user e a execução no pipeline. Toda a rede
           openFDA é falsificada — teste hermético.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - tools/saude/ (coleções curadas + openFDA)
  - tools/actions/actions.py (actions saude_*)
  - core/intents.py (_detect_saude, _formata_saude, SAUDE_AVISO)
  - core/security/permissions.py (allowlist do papel user)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.intents import (
    SAUDE_AVISO,
    detect_action_intent,
    format_intent_result,
)
from core.orchestrator import Orchestrator, StaticProvider
from core.security import SecurityManager
from core.security.permissions import DEFAULT_ROLE_PERMISSIONS
from tools.actions import build_registry
from tools.actions.actions import (
    saude_condicao,
    saude_interacoes,
    saude_medicamento,
)
from tools.saude import dados

COLECOES = Path(__file__).resolve().parents[1] / "tools" / "saude" / "collections"


# ---------------------------------------------------------------------------
# Helpers — labels FDA falsos (rede 100% fake)
# ---------------------------------------------------------------------------


def _label(
    generico: str,
    interacoes: list[str] | None = None,
    avisos: list[str] | None = None,
    indicacoes: list[str] | None = None,
) -> dict:
    corpo: dict = {"openfda": {"generic_name": [generico.upper()]}}
    if interacoes is not None:
        corpo["drug_interactions"] = interacoes
    if avisos is not None:
        corpo["warnings_and_cautions"] = avisos
    if indicacoes is not None:
        corpo["indications_and_usage"] = indicacoes
    return corpo


def _fake_abrir(labels: dict[str, dict]):
    """Corpo de resposta openFDA por genérico; genérico ausente = 404-style."""
    import urllib.parse

    def _abrir(url: str) -> bytes:
        alvo = urllib.parse.unquote(url).casefold()
        for termo, label in labels.items():
            if termo.casefold() in alvo:
                return json.dumps({"results": [label]}).encode("utf-8")
        return json.dumps(
            {"error": {"message": "No matches found!"}}
        ).encode("utf-8")

    return _abrir


# ---------------------------------------------------------------------------
# Coleções versionadas
# ---------------------------------------------------------------------------


class TestColecoes:
    """Curadoria versionada em tools/saude/collections."""

    def test_arquivos_existentes_e_validos(self) -> None:
        for nome, minimo in (
            ("condicoes", 30),
            ("remedios_caseiros", 15),
            ("remedios_naturais", 15),
            ("medicamentos", 40),
        ):
            caminho = COLECOES / f"{nome}.json"
            assert caminho.exists(), caminho
            dados_json = json.loads(caminho.read_text(encoding="utf-8"))
            assert dados_json["versao"]
            assert dados_json["fonte"]

    def test_conclusoes_toda_curadoria_tem_fonte(self) -> None:
        """Todo item carrega atribuição (regra da casa: nunca sem fonte)."""
        for nome in ("remedios_caseiros", "remedios_naturais"):
            itens = dados.carregar_colecao(nome)["remedies"]
            for item in itens:
                assert item["resumo"] and item["detalhe"], item["slug"]
                assert item["fonte"]["nome"], item["slug"]
                assert item["origem_en"]["uses"], item["slug"]

    def test_lexicon_somente_nomes(self) -> None:
        """O lexicon tem nomes/aliases — nunca conteúdo de orientação."""
        meds = dados.carregar_colecao("medicamentos")["medicamentos"]
        for med in meds:
            assert med["nome"] and med["aliases"] and med["genericos_fda"]


# ---------------------------------------------------------------------------
# Matching PT-BR (determinístico, com fronteira de palavra)
# ---------------------------------------------------------------------------


class TestMatching:
    def test_termo_mais_longo_vence(self) -> None:
        assert dados.achar_condicao("dor de cabeça forte")["slug"] == "dor-de-cabeca"
        assert dados.achar_condicao("dor nas costas")["slug"] == "dor-muscular-articular"
        assert dados.achar_condicao("estou com febre")["slug"] == "febre"

    def test_fronteira_de_palavra(self) -> None:
        # 'dor' NÃO casa dentro de 'dormir' (fronteira de palavra).
        assert dados.achar_condicao("vou dormir mal") is None

    def test_condicao_desconhecida(self) -> None:
        # 'remédio para X' roteia, mas X sem termo curado = honestidade.
        assert dados.achar_condicao("remédio para o quadril alienígena") is None
        assert dados.achar_condicao("") is None

    def test_cuidados_da_condicao(self) -> None:
        cuidados = dados.cuidados_da_condicao("cough")
        assert any(c["nome"].startswith("Mel") for c in cuidados)
        assert all(c["fonte"] for c in cuidados)

    def test_extrair_medicamentos_ordem_e_dedupe(self) -> None:
        achados = dados.extrair_medicamentos("tomei dipirona e depois losartana")
        assert [m["nome"] for m in achados] == ["dipirona", "losartana"]
        repete = dados.extrair_medicamentos("dipirona e dipirona")
        assert [m["nome"] for m in repete] == ["dipirona"]
        assert dados.extrair_medicamentos("café com leite") == []

    def test_truncar_honesto(self) -> None:
        longo = "palavra " * 200
        corte = dados.truncar(longo, maximo=50)
        assert len(corte) <= 50 and corte.endswith("…")


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


class TestSaudeCondicao:
    def test_condicao_conhecida(self) -> None:
        r = saude_condicao(texto="o que fazer para dor de cabeça?")
        assert r["ok"] is True
        assert r["condicao"] == "Dor de cabeça"
        assert r["cuidados"] and r["fontes"]

    def test_condicao_desconhecida_eh_honesta_e_nunca_degrada(self) -> None:
        """Resposta honesta (ok=True, condicao=None) — NUNCA cai no LLM."""
        r = saude_condicao(texto="remédio para o quadril alienígena")
        assert r == {
            "ok": True,
            "condicao": None,
            "pedido": "remédio para o quadril alienígena",
        }

    def test_texto_vazio(self) -> None:
        assert saude_condicao(texto="")["condicao"] is None


class TestSaudeInteracoes:
    LABEL_LOSARTAN = _label(
        "losartan potassium",
        interacoes=["7 DRUG INTERACTIONS • NSAIDs: increased risk (7.3)"],
        avisos=["Do not co-administer with potassium-sparing diuretics."],
    )
    LABEL_PARACETAMOL = _label(
        "acetaminophen",
        interacoes=["Drugs that induce CYP2E1 may enhance hepatotoxicity."],
    )
    LABEL_IBUPROFEN = _label(
        "ibuprofen",
        interacoes=["May enhance the nephrotoxicity of cyclosporine."],
    )

    def test_dipirona_com_losartana(self, monkeypatch) -> None:
        """Dipirona não tem label FDA — a ação diz ausência, nunca inventa."""
        monkeypatch.setattr(
            dados, "_abrir",
            _fake_abrir({"LOSARTAN": self.LABEL_LOSARTAN}),
        )
        r = saude_interacoes(texto="posso tomar dipirona com losartana?")
        assert r["ok"] is True and r["incompleto"] is False
        assert r["nomes"] == ["dipirona", "losartana"]
        dipi, losa = r["itens"]
        assert dipi["encontrado"] is False and dipi["motivo"] == "sem_resultado"
        assert losa["encontrado"] is True
        assert "NSAIDs" in losa["interacoes"][0]
        assert losa["rotulo_fda"] == "LOSARTAN POTASSIUM"

    def test_ambos_com_label_e_mencao_cruzada(self, monkeypatch) -> None:
        monkeypatch.setattr(
            dados, "_abrir",
            _fake_abrir({
                "ACETAMINOPHEN": self.LABEL_PARACETAMOL,
                "IBUPROFEN": self.LABEL_IBUPROFEN,
            }),
        )
        r = saude_interacoes(texto="tomei paracetamol e ibuprofeno")
        assert [i["encontrado"] for i in r["itens"]] == [True, True]
        # Nenhum dos dois labels menciona o outro explicitamente.
        assert [i["menciona_outro"] for i in r["itens"]] == [False, False]

    def test_mencao_cruzada_quando_label_fala_do_outro(self, monkeypatch) -> None:
        label = _label(
            "losartan potassium",
            interacoes=["Concomitant use with metamizole may reduce effect."],
        )
        monkeypatch.setattr(dados, "_abrir", _fake_abrir({"LOSARTAN": label}))
        r = saude_interacoes(texto="losartana com dipirona")
        losa = r["itens"][0]
        assert losa["encontrado"] is True and losa["menciona_outro"] is True

    def test_um_medicamento_so_incompleto(self) -> None:
        r = saude_interacoes(texto="posso tomar dipirona?")
        assert r["incompleto"] is True and r["medicamentos"] == ["dipirona"]

    def test_sem_rede_honesto(self, monkeypatch) -> None:
        def _quebra(url: str) -> bytes:
            raise OSError("rede fora")

        monkeypatch.setattr(dados, "_abrir", _quebra)
        r = saude_interacoes(texto="losartana com metformina")
        assert [i["motivo"] for i in r["itens"]] == ["sem_rede", "sem_rede"]
        assert all(i["encontrado"] is False for i in r["itens"])


class TestSaudeMedicamento:
    def test_bula_completa(self, monkeypatch) -> None:
        label = _label(
            "losartan potassium",
            interacoes=["Drug Interactions text."],
            avisos=["Do not use in pregnancy."],
            indicacoes=["LOSARTAN POTASSIUM is indicated for hypertension."],
        )
        monkeypatch.setattr(dados, "_abrir", _fake_abrir({"LOSARTAN": label}))
        r = saude_medicamento(texto="o que diz a bula de losartana?")
        assert r["encontrado"] is True
        assert "hypertension" in r["indicacoes"][0]
        assert "pregnancy" in r["avisos"][0]

    def test_sem_label_honesto(self, monkeypatch) -> None:
        monkeypatch.setattr(dados, "_abrir", _fake_abrir({}))
        r = saude_medicamento(texto="o que diz a bula de dipirona?")
        assert r["encontrado"] is False and r["motivo"] == "sem_resultado"

    def test_sem_medicamento_incompleto(self) -> None:
        assert saude_medicamento(texto="")["incompleto"] is True


# ---------------------------------------------------------------------------
# Gatilhos (intenções)
# ---------------------------------------------------------------------------


class TestGatilhos:
    @pytest.mark.parametrize(
        "texto,action",
        [
            ("o que fazer para dor de cabeça?", "saude_condicao"),
            ("remédio pra gripe", "saude_condicao"),
            ("estou com febre e dor no corpo", "saude_condicao"),
            ("tenho tosse há dias", "saude_condicao"),
            ("posso tomar dipirona com losartana?", "saude_interacoes"),
            ("tomei paracetamol e ibuprofeno", "saude_interacoes"),
            ("interação entre losartana e enalapril", "saude_interacoes"),
            ("o que diz a bula de losartana?", "saude_medicamento"),
            ("quais os efeitos colaterais da metformina?", "saude_medicamento"),
        ],
    )
    def test_saude_detectado(self, texto: str, action: str) -> None:
        r = detect_action_intent(texto)
        assert r is not None and r[0] == action, (texto, r)
        assert r[1] == {"texto": texto}

    @pytest.mark.parametrize(
        "texto",
        [
            "posso tomar café com leite?",        # não é saúde
            "o que fazer para subir o site?",     # gênese genérica sem saúde
            "quanto é 2+2",
            "qual a cotação do dólar?",
            "resumo da casa",
            "desliga a luz da cozinha",
        ],
    )
    def test_nao_rouba_intencoes_alheias(self, texto: str) -> None:
        r = detect_action_intent(texto)
        assert r is None or not r[0].startswith("saude_"), (texto, r)

    def test_intencao_operacional_existente_continua_primeiro(self) -> None:
        """Fastpaths antigos não são afetados (cpu_temp/exchange_rate)."""
        r = detect_action_intent("qual a temperatura do servidor?")
        assert r and r[0] == "cpu_temp"


# ---------------------------------------------------------------------------
# Formatador — disclaimer OBRIGATÓRIO em toda resposta
# ---------------------------------------------------------------------------


class TestFormatador:
    def test_condicao_com_cuidados(self) -> None:
        data = saude_condicao(texto="remédio pra tosse")
        texto = format_intent_result("saude_condicao", data)
        assert texto is not None
        assert "🩺" in texto and "Mel" in texto
        assert SAUDE_AVISO in texto

    def test_condicao_desconhecida_nunca_vira_llm(self) -> None:
        data = saude_condicao(texto="remédio para o quadril alienígena")
        texto = format_intent_result("saude_condicao", data)
        assert texto is not None
        assert "não vou inventar" in texto
        assert SAUDE_AVISO in texto

    def test_interacoes_formatadas(self, monkeypatch) -> None:
        label = _label(
            "losartan potassium",
            interacoes=["NSAIDs: increased risk."],
        )
        monkeypatch.setattr(dados, "_abrir", _fake_abrir({"LOSARTAN": label}))
        data = saude_interacoes(texto="dipirona com losartana")
        texto = format_intent_result("saude_interacoes", data)
        assert texto is not None
        assert "dipirona × losartana" in texto
        assert "não invento" in texto          # ausência dita com honestidade
        assert "NSAIDs" in texto               # verbatim da bula
        assert SAUDE_AVISO in texto

    def test_medicamento_formatado(self, monkeypatch) -> None:
        label = _label(
            "metformin",
            avisos=["Lactic acidosis risk."],
            indicacoes=["METFORMIN is indicated to improve glycemic control."],
        )
        monkeypatch.setattr(dados, "_abrir", _fake_abrir({"METFORMIN": label}))
        data = saude_medicamento(texto="para que serve metformina?")
        texto = format_intent_result("saude_medicamento", data)
        assert texto is not None
        assert "glycemic" in texto and SAUDE_AVISO in texto

    def test_toda_saida_saude_carrega_aviso(self) -> None:
        """Percorre todos os ramos possíveis — o aviso é inegociável."""
        caso_interacoes = {
            "ok": True, "incompleto": False, "nomes": ["a", "b"],
            "itens": [
                {"nome": "a", "encontrado": False, "motivo": "sem_rede",
                 "genericos_fda": ["x"], "interacoes": [], "menciona_outro": False},
                {"nome": "b", "encontrado": True, "rotulo_fda": "B",
                 "genericos_fda": ["y"], "interacoes": [], "menciona_outro": False},
            ],
        }
        caso_medicamento_incompleto = {"ok": True, "incompleto": True}
        for action, data in (
            ("saude_condicao", {"ok": True, "condicao": None}),
            ("saude_condicao", {"ok": True, "condicao": "Febre", "cuidados": [],
                                "fontes": []}),
            ("saude_interacoes", {"ok": True, "incompleto": True}),
            ("saude_interacoes", caso_interacoes),
            ("saude_medicamento", caso_medicamento_incompleto),
            ("saude_medicamento", {"ok": True, "incompleto": False,
                                   "encontrado": False, "nome": "x",
                                   "genericos_fda": ["x"], "motivo": "sem_rede"}),
            ("saude_medicamento", {"ok": True, "incompleto": False,
                                   "encontrado": True, "nome": "x",
                                   "genericos_fda": ["x"], "rotulo_fda": "X",
                                   "indicacoes": ["i"], "avisos": ["a"]}),
        ):
            texto = format_intent_result(action, data)
            assert texto is not None, (action, data)
            assert SAUDE_AVISO in texto, (action, data)

    def test_ok_false_nunca_degrada_para_llm(self) -> None:
        """Nem com ok=False a saúde cai no LLM — regra de segurança."""
        for action in ("saude_condicao", "saude_interacoes", "saude_medicamento"):
            texto = format_intent_result(action, {"ok": False, "error": "x"})
            assert texto is not None and SAUDE_AVISO in texto, action


# ---------------------------------------------------------------------------
# Permissões + pipeline
# ---------------------------------------------------------------------------


class TestPermissoesEPipeline:
    def test_papel_user_pode_ler_saude(self) -> None:
        permitidas = DEFAULT_ROLE_PERMISSIONS["user"]
        for acao in ("saude_condicao", "saude_interacoes", "saude_medicamento"):
            assert acao in permitidas, acao
        # Ações sensíveis continuam vedadas ao user (regressão).
        for vedada in ("system_env", "database_query", "ha_device_control"):
            assert vedada not in permitidas, vedada

    @pytest.mark.asyncio
    async def test_pipeline_user_executa_saude(self) -> None:
        security = SecurityManager(mode="strict")
        registry = build_registry(security=security)
        orch = Orchestrator(
            providers=[StaticProvider("test", "ok")],
            action_registry=registry,
        )
        data = await orch.execute_action(
            "saude_condicao",
            {"texto": "remédio pra dor de cabeça"},
            role="user",
        )
        assert isinstance(data, dict) and data["ok"] is True
        assert data["condicao"] == "Dor de cabeça"

    @pytest.mark.asyncio
    async def test_pipeline_anonimo_nao_executa_saude(self) -> None:
        """Papel desconhecido segue deny-by-default (não há atalho)."""
        security = SecurityManager(mode="strict")
        registry = build_registry(security=security)
        orch = Orchestrator(
            providers=[StaticProvider("test", "ok")],
            action_registry=registry,
        )
        data = await orch.execute_action(
            "saude_condicao", {"texto": "remédio pra tosse"}, role="anonymous"
        )
        assert data is None  # negado — o chat do anônimo segue o fluxo normal
