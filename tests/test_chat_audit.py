"""OMEGA DRAKON • TESTS
Módulo: tests/test_chat_audit.py
Descrição: Testes do auditor de conversas (core/chat_audit.py, ordem do
           dono 2026-10-22): parser dos logs legados PascAlice (encoding
           corrompido, lado português do "original|traducao"), cascata de
           fonte do sistema (Postgres → SQLite → JSON), juiz plugável
           com reserva POR TURNO (online Groq | local gemma), veredito
           `erro` nunca silencioso, relatório JSON e CLI.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - core/chat_audit.py
  - tests/test_offsite.py (padrão da casa: dublês, env por dict)
  - amostra real: analise/AIML/Nicky Desenvolvimento/conversa/*.log
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.chat_audit import (
    JuizComReserva,
    JuizError,
    JuizLLM,
    Turno,
    Veredito,
    auditar,
    carregar_turnos_cascata,
    carregar_turnos_json,
    carregar_turnos_legados,
    gerar_relatorio,
    main,
    montar_juiz,
    montar_prompt,
    parse_log_legado,
    parse_log_legado_texto,
    salvar_relatorio,
    turnos_de_mensagens,
    _interpretar_resposta,
    _normalizar_veredito,
)


# ---------------------------------------------------------------------------
# Dublês (padrão da casa)
# ---------------------------------------------------------------------------

class _Juiz:
    """Juiz de mentira: devolve vereditos pré-programados por turno."""

    def __init__(self, *vereditos: Veredito | Exception) -> None:
        self._fila = list(vereditos)
        self.chamadas: list[Turno] = []
        self.nome = "juiz-de-mentira"

    def julgar(self, turno: Turno, anterior: Turno | None = None) -> Veredito:
        self.chamadas.append(turno)
        item = self._fila.pop(0) if self._fila else Veredito(
            "ok", "sem programa", self.nome)
        if isinstance(item, Exception):
            raise item
        return item


class _Provider:
    """Provider LLM de mentira (async generate igual ao OpenAICompat)."""

    def __init__(self, respostas: list[str] | Exception,
                 nome: str = "fake") -> None:
        self.name = nome
        self._respostas = respostas
        self.prompts: list[str] = []

    async def generate(self, prompt: str, **options: object) -> str | None:
        self.prompts.append(prompt)
        if isinstance(self._respostas, Exception):
            raise self._respostas
        return self._respostas.pop(0) if self._respostas else None


LOG_LEGADO = """\
23:40:23 -->
ALEX PROJETI: oi|Hi
Nicky: Hello there.|Olá.

23:41:00 -->
ALEX PROJETI: o que tem pra hoje|What's for today
Nicky: Check out CNN.com.|Confira CNN.com.

23:43:19 -->
ALEX PROJETI: sim|sim
"""


def _env(dados: dict[str, str]):
    return lambda nome, padrao: dados.get(nome, padrao)


# ---------------------------------------------------------------------------
# Parser dos logs legados (PascAlice)
# ---------------------------------------------------------------------------

class TestParserLegado:
    def test_extrai_turnos_com_lado_portugues(self) -> None:
        turnos = parse_log_legado_texto(LOG_LEGADO, arquivo="ALEX_20220608.log")
        assert len(turnos) == 3
        assert turnos[0].pergunta == "oi"
        assert turnos[0].resposta == "Olá."
        assert turnos[0].fonte == "legado"
        assert turnos[0].quando == "2022-06-08 23:40"
        assert turnos[1].pergunta == "o que tem pra hoje"
        assert turnos[1].resposta == "Confira CNN.com."
        assert turnos[1].arquivo == "ALEX_20220608.log"

    def test_bloco_sem_resposta_vira_turno_vazio(self) -> None:
        """Lacuna é achado de auditoria — não some do relatório."""
        turnos = parse_log_legado_texto(LOG_LEGADO)
        assert turnos[2].pergunta == "sim"
        assert turnos[2].resposta == ""

    def test_encoding_corrompido_nao_explode(self) -> None:
        """Logs reais têm bytes inválidos — leitura com errors='replace'."""
        corrompido = (b"23:40:23 -->\r\nALEX PROJETI: bom dia\x87\x8a\r\n"
                      b"Nicky: Good morning|Bom dia\x9f\r\n")
        caminho = Path("_legado_tmp.log")
        try:
            caminho.write_bytes(corrompido)
            turnos = parse_log_legado(caminho)
        finally:
            caminho.unlink(missing_ok=True)
        assert len(turnos) == 1
        assert turnos[0].pergunta == "bom dia\ufffd\ufffd" or "bom dia" in \
            turnos[0].pergunta
        assert turnos[0].resposta == "Bom dia\ufffd"

    def test_texto_sem_barra_passa_intacto(self) -> None:
        turnos = parse_log_legado_texto(
            "10:00:00 -->\nAlex: tudo bem\nNicky: tudo bem tambem\n")
        assert turnos[0].pergunta == "tudo bem"
        assert turnos[0].resposta == "tudo bem tambem"

    def test_varredura_recursiva_e_ordem_cronologica(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (tmp_path / "b_20240102.log").write_text(
            "12:00:00 -->\nAlex: dois\nNicky: resposta dois\n", encoding="utf-8")
        (sub / "a_20220101.log").write_text(
            "09:00:00 -->\nAlex: um\nNicky: resposta um\n", encoding="utf-8")
        turnos = carregar_turnos_legados(tmp_path)
        assert [t.pergunta for t in turnos] == ["um", "dois"]
        assert turnos[0].quando == "2022-01-01 09:00"

    def test_pasta_sem_logs_devolve_lista_vazia(self, tmp_path: Path) -> None:
        assert carregar_turnos_legados(tmp_path) == []


# ---------------------------------------------------------------------------
# Fonte sistema (mensagens → turnos, cascata)
# ---------------------------------------------------------------------------

class TestFonteSistema:
    def test_empilha_user_assistant_do_mesmo_balde(self) -> None:
        linhas = [
            {"user_id": "alex", "profile": "nexus", "role": "user",
             "content": "qual a hora", "ts": 1700000000.0, "llm_used": ""},
            {"user_id": "alex", "profile": "nexus", "role": "assistant",
             "content": "sao 10", "ts": 1700000001.0,
             "llm_used": "fastpath:hora"},
        ]
        turnos = turnos_de_mensagens(linhas)
        assert len(turnos) == 1
        assert turnos[0].pergunta == "qual a hora"
        assert turnos[0].resposta == "sao 10"
        assert turnos[0].llm_used == "fastpath:hora"
        assert turnos[0].fonte == "sistema"

    def test_baldes_diferentes_nao_se_misturam(self) -> None:
        linhas = [
            {"user_id": "alex", "profile": "nexus", "role": "user",
             "content": "pergunta A", "ts": 1.0, "llm_used": ""},
            {"user_id": "alex", "profile": "guardian", "role": "user",
             "content": "pergunta B", "ts": 2.0, "llm_used": ""},
            {"user_id": "alex", "profile": "nexus", "role": "assistant",
             "content": "resposta A", "ts": 3.0, "llm_used": "llm"},
            {"user_id": "alex", "profile": "guardian", "role": "assistant",
             "content": "resposta B", "ts": 4.0, "llm_used": "llm"},
        ]
        turnos = turnos_de_mensagens(linhas)
        assert [(t.pergunta, t.resposta) for t in turnos] == [
            ("pergunta A", "resposta A"), ("pergunta B", "resposta B")]

    def test_assistant_orfao_vira_turno_sem_pergunta(self) -> None:
        linhas = [{"user_id": "web", "profile": "-", "role": "assistant",
                   "content": "aviso solto", "ts": 5.0, "llm_used": ""}]
        turnos = turnos_de_mensagens(linhas)
        assert len(turnos) == 1
        assert turnos[0].pergunta == ""
        assert turnos[0].resposta == "aviso solto"

    def test_pergunta_sem_resposta_fica_aberta(self) -> None:
        linhas = [{"user_id": "alex", "profile": "-", "role": "user",
                   "content": "alguem ai?", "ts": 6.0, "llm_used": ""}]
        turnos = turnos_de_mensagens(linhas)
        assert len(turnos) == 1
        assert turnos[0].resposta == ""

    def test_ts_invalido_nao_quebra(self) -> None:
        linhas = [{"user_id": "x", "profile": "-", "role": "user",
                   "content": "oi", "ts": "not-a-ts", "llm_used": ""}]
        assert turnos_de_mensagens(linhas)[0].quando == "not-a-ts"

    def test_json_legado_lista_e_envelope(self, tmp_path: Path) -> None:
        (tmp_path / "a.json").write_text(json.dumps([
            {"user_id": "u", "profile": "-", "role": "user",
             "content": "pergunta", "ts": 1.0, "llm_used": ""},
            {"user_id": "u", "profile": "-", "role": "assistant",
             "content": "resposta", "ts": 2.0, "llm_used": "llm"},
        ]), encoding="utf-8")
        (tmp_path / "b.json").write_text(json.dumps(
            {"messages": [{"user_id": "v", "profile": "-", "role": "user",
                           "content": "outra", "ts": 3.0, "llm_used": ""}]}),
            encoding="utf-8")
        (tmp_path / "quebrado.json").write_text("{sem json", encoding="utf-8")
        turnos = carregar_turnos_json(tmp_path)
        assert [t.pergunta for t in turnos] == ["pergunta", "outra"]

    def test_cascata_usa_postgres_quando_ha_dsn(self, monkeypatch) -> None:
        class _DB:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def query(self, sql: str, params: tuple = (), *, limit=None):
                return [{"user_id": "alex", "profile": "-", "role": "user",
                         "content": "pg vivo", "ts": 1.0, "llm_used": ""},
                        {"user_id": "alex", "profile": "-", "role": "assistant",
                         "content": "resposta pg", "ts": 2.0, "llm_used": "g"}]

        import storage
        monkeypatch.setattr(storage, "Database", _DB)
        turnos, fonte = carregar_turnos_cascata(dsn="postgres://x/y")
        assert fonte == "postgres"
        assert turnos[0].pergunta == "pg vivo"

    def test_cascata_sem_dsn_devolve_vazia(self) -> None:
        turnos, fonte = carregar_turnos_cascata(dsn="")
        assert turnos == []
        assert fonte == "vazia"


# ---------------------------------------------------------------------------
# Juiz (prompt, veredito, reserva por turno)
# ---------------------------------------------------------------------------

class TestJuiz:
    def test_prompt_carrega_pergunta_resposta_e_contexto(self) -> None:
        anterior = Turno("sistema", "", "alex", "ontem chovia?", "sim")
        turno = Turno("sistema", "", "alex", "e hoje?", "esta sol")
        prompt = montar_prompt(turno, anterior)
        assert "e hoje?" in prompt
        assert "esta sol" in prompt
        assert "ontem chovia?" in prompt  # contexto da contradição
        assert "JSON" in prompt

    def test_prompt_sem_anterior_nao_inventa_contexto(self) -> None:
        prompt = montar_prompt(Turno("legado", "", "u", "oi", "ola"), None)
        assert "Turno anterior" not in prompt

    def test_interpretar_resposta_valida_com_cerca(self) -> None:
        texto = ('Aqui está: {"veredito": "devaneio", '
                 '"justificativa": "mudou de assunto"} fim')
        v = _interpretar_resposta(texto, "groq")
        assert v.veredito == "devaneio"
        assert v.justificativa == "mudou de assunto"
        assert v.juiz == "groq"

    def test_interpretar_resposta_sem_json_levanta(self) -> None:
        with pytest.raises(JuizError):
            _interpretar_resposta("achei que ok", "local")

    def test_interpretar_resposta_com_veredito_desconhecido_levanta(self) -> None:
        with pytest.raises(JuizError):
            _interpretar_resposta('{"veredito": "talvez"}', "local")

    def test_normalizar_veredito_aceita_variacoes(self) -> None:
        assert _normalizar_veredito("resposta errada") == "resposta_errada"
        assert _normalizar_veredito("DEVANEIO") == "devaneio"
        assert _normalizar_veredito("inconsistente.") == "inconsistente"
        assert _normalizar_veredito("outra coisa") == ""

    def test_juiz_llm_sucesso(self) -> None:
        provider = _Provider(['{"veredito": "ok", "justificativa": "boa"}'])
        v = JuizLLM(provider, nome="fake").julgar(
            Turno("sistema", "", "alex", "oi", "ola"))
        assert v.veredito == "ok"
        assert "oi" in provider.prompts[0]

    def test_juiz_llm_provider_fora_levanta_juiz_error(self) -> None:
        provider = _Provider(RuntimeError("402"), nome="groq")
        with pytest.raises(JuizError, match="groq"):
            JuizLLM(provider).julgar(Turno("sistema", "", "a", "p", "r"))

    def test_juiz_llm_resposta_vazia_levanta(self) -> None:
        with pytest.raises(JuizError):
            JuizLLM(_Provider([])).julgar(Turno("sistema", "", "a", "p", "r"))

    def test_reserva_assume_no_mesmo_turno(self) -> None:
        """Regra: reserva POR TURNO — o online caiu, o local responde."""
        principal = _Juiz(JuizError("groq fora"))
        reserva = _Juiz(Veredito("devaneio", "classe", "local"))
        v = JuizComReserva(principal, reserva).julgar(
            Turno("legado", "", "u", "bom dia", "What food do you like?"))
        assert v.veredito == "devaneio"
        assert v.juiz == "local"
        assert len(principal.chamadas) == 1
        assert len(reserva.chamadas) == 1

    def test_sem_reserva_o_erro_vira_veredito(self) -> None:
        v = JuizComReserva(_Juiz(JuizError("sem LLM"))).julgar(
            Turno("sistema", "", "u", "p", "r"))
        assert v.veredito == "erro"
        assert "sem LLM" in v.justificativa

    def test_dois_juizes_fora_viram_erro_com_os_dois_motivos(self) -> None:
        juiz = JuizComReserva(_Juiz(JuizError("principal morreu")),
                              _Juiz(JuizError("reserva morreu")))
        v = juiz.julgar(Turno("sistema", "", "u", "p", "r"))
        assert v.veredito == "erro"
        assert "principal morreu" in v.justificativa
        assert "reserva morreu" in v.justificativa

    def test_montar_juiz_local(self) -> None:
        juiz = montar_juiz("local", _env({}))
        assert isinstance(juiz, JuizLLM)
        assert juiz.nome == "gemma-local"

    def test_montar_juiz_online_sem_chave_erro(self) -> None:
        with pytest.raises(ValueError, match="GROQ_API_KEY"):
            montar_juiz("online", _env({}))

    def test_montar_juiz_online_com_chave_tem_reserva_local(self) -> None:
        juiz = montar_juiz("online", _env({"GROQ_API_KEY": "gsk_x"}))
        assert isinstance(juiz, JuizComReserva)
        assert juiz.principal.nome == "groq-online"
        assert juiz.reserva.nome == "gemma-local"

    def test_montar_juiz_auto_offline_first(self) -> None:
        """Sem chave Groq, o auto cai no local — offline-first preservado."""
        assert isinstance(montar_juiz("auto", _env({})), JuizLLM)
        assert isinstance(
            montar_juiz("auto", _env({"GROQ_API_KEY": "gsk_x"})),
            JuizComReserva)
        assert montar_juiz("nenhum", _env({})) is None


# ---------------------------------------------------------------------------
# Auditoria + relatório
# ---------------------------------------------------------------------------

class TestAuditoria:
    def test_auditar_classifica_cada_turno(self) -> None:
        turnos = [
            Turno("legado", "2022-01-01 09:00", "u", "bom dia",
                  "What kind of food do you like?"),
            Turno("legado", "2022-01-01 09:01", "u", "oi", "Olá."),
        ]
        juiz = _Juiz(Veredito("devaneio", "comida?", "local"),
                     Veredito("ok", "pertinente", "local"))
        resultados = auditar(turnos, juiz)
        assert [r["veredito"] for r in resultados] == ["devaneio", "ok"]
        assert resultados[0]["pergunta"] == "bom dia"
        assert len(juiz.chamadas) == 2

    def test_auditar_sem_juiz_marca_erro_nunca_ok(self) -> None:
        resultados = auditar(
            [Turno("sistema", "", "u", "p", "r")], juiz=None)
        assert resultados[0]["veredito"] == "erro"
        assert "sem juiz" in resultados[0]["justificativa"]

    def test_lacuna_e_deterministica_sem_tocar_o_juiz(self) -> None:
        """Resposta vazia = resposta_errada — o juiz alucinou 'ok' nela."""
        juiz = _Juiz(Veredito("ok", "deveria nao ser chamado", "l"))
        resultados = auditar(
            [Turno("legado", "", "u", "pergunta", "")], juiz)
        assert resultados[0]["veredito"] == "resposta_errada"
        assert resultados[0]["juiz"] == "deterministico"
        assert juiz.chamadas == []  # juiz nunca viu a lacuna

    def test_assistant_orfao_e_erro_deterministico(self) -> None:
        juiz = _Juiz()
        resultados = auditar(
            [Turno("sistema", "", "u", "", "aviso solto")], juiz)
        assert resultados[0]["veredito"] == "erro"
        assert "sem pergunta" in resultados[0]["justificativa"]
        assert juiz.chamadas == []

    def test_turno_completo_continua_passando_pelo_juiz(self) -> None:
        juiz = _Juiz(Veredito("devaneio", "mudou", "l"))
        resultados = auditar(
            [Turno("legado", "", "u", "oi", "What is your sign?")], juiz)
        assert resultados[0]["veredito"] == "devaneio"
        assert len(juiz.chamadas) == 1

    def test_juiz_que_explode_nao_para_a_auditoria(self) -> None:
        juiz = _Juiz(RuntimeError("bug"), Veredito("ok", "bom", "l"))
        resultados = auditar(
            [Turno("sistema", "", "u", "p1", "r1"),
             Turno("sistema", "", "u", "p2", "r2")], juiz)
        assert resultados[0]["veredito"] == "erro"
        assert resultados[1]["veredito"] == "ok"

    def test_relatorio_conta_e_lista(self) -> None:
        turnos = [Turno("legado", "", "u", f"p{i}", f"r{i}") for i in range(3)]
        juiz = _Juiz(Veredito("ok", "bom", "l"),
                     Veredito("devaneio", "mudou", "l"),
                     Veredito("resposta_errada", "falso", "l"))
        rel = gerar_relatorio(auditar(turnos, juiz), fonte="legado")
        assert rel["total_turnos"] == 3
        assert rel["contagens"]["ok"] == 1
        assert rel["contagens"]["devaneio"] == 1
        assert rel["contagens"]["resposta_errada"] == 1
        assert rel["problematicos"] == 2
        assert rel["fonte"] == "legado"

    def test_salvar_relatorio_em_analise(self, tmp_path: Path) -> None:
        rel = gerar_relatorio([], fonte="vazia")
        caminho = salvar_relatorio(rel, tmp_path)
        assert caminho.parent == tmp_path
        assert caminho.name.startswith("relatorio_chat_audit_")
        carga = json.loads(caminho.read_text(encoding="utf-8"))
        assert carga["total_turnos"] == 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCLI:
    def test_sem_turnos_devolve_1(self, tmp_path: Path,
                                 monkeypatch) -> None:
        monkeypatch.delenv("OD_DB_URL", raising=False)
        monkeypatch.setattr(
            "core.chat_audit.carregar_turnos_cascata",
            lambda **kw: ([], "vazia"))
        vazio = tmp_path / "vazio"
        vazio.mkdir()
        assert main(["--fonte", "legado", "--pasta", str(vazio)]) == 1

    def test_juiz_online_sem_chave_devolve_2(self, tmp_path: Path,
                                             monkeypatch) -> None:
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        log = tmp_path / "u_20220101.log"
        log.write_text("09:00:00 -->\nAlex: oi\nNicky: Hi|Ola\n",
                       encoding="utf-8")
        assert main(["--fonte", "legado", "--pasta", str(tmp_path),
                     "--juiz", "online"]) == 2

    def test_caminho_feliz_grava_relatorio(self, tmp_path: Path,
                                           monkeypatch) -> None:
        monkeypatch.delenv("OD_DB_URL", raising=False)
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "u_20220101.log").write_text(
            "09:00:00 -->\nAlex: bom dia\nNicky: What food do you like?|"
            "Que comida voce gosta?\n", encoding="utf-8")
        destino = tmp_path / "relatorios"
        saida = main(["--fonte", "legado", "--pasta", str(logs),
                      "--juiz", "nenhum", "--destino", str(destino)])
        assert saida == 0
        gerados = list(destino.glob("relatorio_chat_audit_*.json"))
        assert len(gerados) == 1
        carga = json.loads(gerados[0].read_text(encoding="utf-8"))
        assert carga["total_turnos"] == 1
        assert carga["contagens"]["erro"] == 1  # sem juiz = erro, nunca ok
