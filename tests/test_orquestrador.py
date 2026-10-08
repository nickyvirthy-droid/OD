"""
OMEGA DRAKON • TESTS
Módulo: tests/test_orquestrador.py
Descrição: testes do orquestrador de CLIs de IA (orquestrador.py) —
           cascata Freebuff → OpenCode → Kilo e o MODO SESSÃO
           on-demand (ideia do dono no txt.txt). A fila pedido.txt
           foi removida a pedido do dono (2026-10-8).

Baseado em:
  - orquestrador.py
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import json
from pathlib import Path

import orquestrador as orch
from orquestrador import (
    CLIS,
    SESSAO_MAX_AUTORIZACOES,
    CliSpec,
    aguardar_resposta_dono,
    commitar_sessao,
    executar_sessao,
    extrair_autorizacao,
    main_sessao,
    montar_prompt_sessao,
    resolver_clis,
    validar_sessao,
)


def _spec(nome: str) -> CliSpec:
    return CliSpec(nome=nome, binario=nome.lower(), args_antes=("run",))


class TestCascataOficial:
    def test_ordem_e_contrato_das_clis(self) -> None:
        """Contratos PROVADOS no ar (30/09, prova do serviço):

        - Freebuff: o wrapper público (0.2.1) só tem 'login'; o binário real
          (~/.config/manicode/freebuff) aceita PROMPT posicional. 'ask'
          dava 'too many arguments' → cascade inteira caía.
        - OpenCode: 'run PROMPT' + modelo FREE (default 'build' →
          'credit_balance_exhausted'); binário só em ~/.npm-global/bin.
        - Kilo: 'run PROMPT --auto --pure' + modelo free (gemini → quota;
          groq → TPM 8000 estourado pelo prompt de sistema).
        """
        nomes = [spec.nome for spec in orch.CLIS]
        assert nomes == ["Freebuff", "OpenCode", "Kilo"]
        freebuff, opencode, kilo = orch.CLIS
        assert freebuff.binario == "freebuff"
        assert freebuff.args_antes == ()  # prompt posicional direto
        assert freebuff.caminho_candidato.endswith(".config/manicode/freebuff")
        assert opencode.binario == "opencode"
        assert opencode.args_antes[:2] == ("run", "-m")
        assert "free" in orch.OPENCODE_MODELO  # default pago → sem créditos
        assert opencode.caminho_candidato.endswith(".npm-global/bin/opencode")
        assert kilo.binario == "kilo"
        assert kilo.args_antes == ("run", "-m", orch.KILO_MODELO, "--pure")
        assert kilo.args_depois == ("--auto",)
        assert kilo.caminho_candidato.endswith(".npm-global/bin/kilo")

    def test_comando_base_prefere_path_e_cai_para_candidato(self, monkeypatch) -> None:
        """PATH primeiro; sem PATH, o candidato expandido e executável vence."""
        spec = CliSpec(
            nome="X",
            binario="fantasma",
            args_antes=(),
            caminho_candidato="~/caminho/fantasma",
        )
        monkeypatch.setattr(orch.shutil, "which", lambda nome: None)
        monkeypatch.setattr(orch.Path, "is_file", lambda self: False)
        assert spec.comando_base() == ["fantasma"]  # nada resolve → binário

        monkeypatch.setattr(orch.Path, "is_file", lambda self: True)
        monkeypatch.setattr(orch.os, "access", lambda p, m: True)
        base = spec.comando_base()
        assert len(base) == 1 and base[0].startswith("/")  # expandido absoluto

    def test_env_keys_contrato(self) -> None:
        # As chaves do .env exigidas pelo instrucoes_projeto.txt.
        assert orch.ENV_KEYS == ("GEMINI_API_KEY", "GROQ_API_KEY")
        # A ideia do dono vem do txt.txt (canal dele) — fila removida.
        assert orch.IDEIA_FILE == Path("txt.txt")


class TestAmbienteComChaves:
    def test_ambiente_herdado_e_repassado(self, monkeypatch) -> None:
        """O subprocesso recebe o ambiente inteiro (PATH, HOME e as chaves do .env)."""
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("GEMINI_API_KEY", "chave-teste")
        env = orch._ambiente_com_chaves()
        assert env["PATH"] == "/usr/bin"
        assert env["GEMINI_API_KEY"] == "chave-teste"

    def test_executar_cli_monta_comando_e_ambiente(self, monkeypatch) -> None:
        """Contrato da execução: [binario, *args_antes, prompt, *args_depois]."""
        vistos: dict[str, object] = {}

        class FalsoCompleted:
            returncode = 0
            stdout = "x = 1\n"
            stderr = ""

        def falso_run(comando, **kwargs):
            vistos["comando"] = comando
            vistos["env"] = kwargs.get("env")
            return FalsoCompleted()

        monkeypatch.setattr(orch.shutil, "which", lambda nome: "/usr/bin/" + nome)
        monkeypatch.setattr(orch.subprocess, "run", falso_run)
        monkeypatch.setenv("GROQ_API_KEY", "chave-groq")

        spec = CliSpec(nome="Falso", binario="falso", args_antes=("run",), args_depois=("--auto",))
        saida = orch.executar_cli(spec, "PROMPT")

        assert saida == "x = 1"
        assert vistos["comando"] == ["falso", "run", "PROMPT", "--auto"]
        assert vistos["env"]["GROQ_API_KEY"] == "chave-groq"  # chave do .env repassada

    def test_executar_cli_binario_ausente(self, monkeypatch) -> None:
        """Sem PATH e sem candidato: NADA é executado (guarda de indisponível).

        Endurecido após a mutação M2 (guarda removida) sobreviver — o teste
        antigo só conferia None e um subprocess.run inexiste não reclamaria
        (binário inexistente → OSError → None do mesmo jeito, por sorte).
        Aqui a chamada ao subprocess.run é FALHA DE TESTE se acontecer.
        """

        def proibido_run(*args, **kwargs):
            raise AssertionError("subprocess.run não deveria ser chamado")

        monkeypatch.setattr(orch.shutil, "which", lambda nome: None)
        monkeypatch.setattr(orch.subprocess, "run", proibido_run)
        spec = CliSpec(nome="Falso", binario="fantasma", args_antes=("run",))
        assert orch.executar_cli(spec, "PROMPT") is None

    def test_executar_cli_usa_caminho_candidato_sem_path(self, monkeypatch) -> None:
        """Serviço sem ~/.npm-global no PATH: o candidato resolve a CLI."""
        vistos: dict[str, object] = {}

        class FalsoCompleted:
            returncode = 0
            stdout = "x = 2\n"
            stderr = ""

        def falso_run(comando, **kwargs):
            vistos["comando"] = comando
            return FalsoCompleted()

        monkeypatch.setattr(orch.shutil, "which", lambda nome: None)
        monkeypatch.setattr(orch.subprocess, "run", falso_run)
        monkeypatch.setattr(
            orch.Path, "is_file", lambda self: ".npm-global" in str(self)
        )
        monkeypatch.setattr(orch.os, "access", lambda p, m: True)

        spec = CliSpec(
            nome="Opencode",
            binario="opencode",
            args_antes=("run",),
            caminho_candidato="~/.npm-global/bin/opencode",
        )
        saida = orch.executar_cli(spec, "PROMPT")

        assert saida == "x = 2"
        assert vistos["comando"][0].endswith("/.npm-global/bin/opencode")


# ===========================================================================
# Modo SESSÃO — canal de desenvolvimento on-demand (2026-10-08)
# ===========================================================================

VALIDACAO_OK = {
    "ok": True,
    "testes": "12 passed in 0.40s",
    "arquivos": ["orquestrador.py"],
    "diff": "orquestrador.py",
}


def _rodar_sessao(tmp_path: Path, **kwargs):
    """executar_sessao com estado/caixa em tmp_path e validação/commit fake.

    Sem os fakes, os defaults chamariam a suíte canônica e o git de verdade —
    aqui o que importa é a COREOGRAFIA da sessão, não o git.
    """
    kwargs.setdefault("validar", lambda: dict(VALIDACAO_OK))
    kwargs.setdefault("commitar", lambda titulo: {"ok": True, "commit": "abc1234"})
    kwargs.setdefault("clis", [_spec("A")])
    return executar_sessao(
        "crie o botão de tema no painel",
        arquivo_estado=tmp_path / "estado.json",
        arquivo_caixa=tmp_path / "caixa.json",
        **kwargs,
    )


def _caixa_de(tmp_path: Path) -> list[dict]:
    return json.loads((tmp_path / "caixa.json").read_text(encoding="utf-8"))


class TestMontarPromptSessao:
    def test_instrucao_e_ideia_no_prompt(self) -> None:
        prompt = montar_prompt_sessao("  adicione o tema claro  ")
        assert "adicione o tema claro" in prompt
        assert "iniciar/" in prompt and "docs/" in prompt and "txt.txt" in prompt
        assert "[AUTORIZACAO]" in prompt  # a CLI aprende o marcador
        assert "NÃO rode git commit nem git push" in prompt

    def test_historico_somente_quando_existe(self) -> None:
        sem = montar_prompt_sessao("ideia")
        com = montar_prompt_sessao("ideia", "[Resposta do dono] pode")
        assert "Histórico" not in sem
        assert "[Resposta do dono] pode" in com
        assert "[Resposta do dono] pode" not in sem


class TestExtrairAutorizacao:
    def test_marcador_em_linha_propria(self) -> None:
        saida = "implementado.\n[AUTORIZACAO] posso subir o APK?"
        assert extrair_autorizacao(saida) == "posso subir o APK?"

    def test_marcador_com_recuo(self) -> None:
        assert extrair_autorizacao("   [AUTORIZACAO] reinicio?") == "reinicio?"

    def test_marcador_no_meio_da_linha_nao_conta(self) -> None:
        """O contrato é linha INTEIRA começando com o marcador — texto solto
        dentro de uma frase não pode travar a sessão num falso positivo."""
        assert extrair_autorizacao("o [AUTORIZACAO] aqui dentro") is None

    def test_sem_marcador_e_none(self) -> None:
        assert extrair_autorizacao("tudo pronto, nada a perguntar.") is None

    def test_marcador_vazio_e_none(self) -> None:
        assert extrair_autorizacao("[AUTORIZACAO]   \noutra linha") is None
        assert extrair_autorizacao("") is None


class TestResolverClis:
    def test_auto_e_a_cascata_oficial(self) -> None:
        assert resolver_clis("auto") == CLIS
        assert resolver_clis("") == CLIS  # default do painel

    def test_nome_especifico_isola_a_cli(self) -> None:
        assert [s.nome for s in resolver_clis("freebuff")] == ["Freebuff"]
        assert [s.nome for s in resolver_clis("Kilo")] == ["Kilo"]
        assert [s.nome for s in resolver_clis("opencode")] == ["OpenCode"]

    def test_cli_desconhecida_raises(self) -> None:
        try:
            resolver_clis("gpt-99")
        except ValueError as erro:
            assert "gpt-99" in str(erro)
        else:  # pragma: no cover — só roda se a guarda sumir (mutação)
            raise AssertionError("CLI desconhecida deveria levantar ValueError")


class TestAguardarRespostaDono:
    def test_resposta_nova_retoma(self, tmp_path: Path) -> None:
        caixa = tmp_path / "caixa.json"

        def dormir(_s: float) -> None:
            orch.publicar_na_caixa("dono", "pode seguir", "resposta", caixa)

        resposta = aguardar_resposta_dono(
            0, caixa, timeout_s=6, intervalo_s=2, dormir=dormir
        )
        assert resposta == "pode seguir"

    def test_timeout_devolve_none(self, tmp_path: Path) -> None:
        caixa = tmp_path / "caixa.json"
        resposta = aguardar_resposta_dono(
            0, caixa, timeout_s=4, intervalo_s=2, dormir=lambda _s: None
        )
        assert resposta is None

    def test_resposta_antiga_nao_reabre_o_pedido(self, tmp_path: Path) -> None:
        """A história do dono NÃO vale como resposta da rodada atual."""
        caixa = tmp_path / "caixa.json"
        orch.publicar_na_caixa("dono", "sim", "resposta", caixa)
        resposta = aguardar_resposta_dono(
            1, caixa, timeout_s=2, intervalo_s=1, dormir=lambda _s: None
        )
        assert resposta is None


class TestValidarSessao:
    def test_sucessa_com_diff(self, tmp_path: Path) -> None:
        def rodar(cmd, cwd):
            if cmd[0] == "git":
                return 0, " M orquestrador.py\n?? tests/test_novo.py\n\n"
            return 0, "12 passed in 0.40s\n"

        resultado = validar_sessao(rodar=rodar, repo=tmp_path)
        assert resultado["ok"] is True
        assert "12 passed" in resultado["testes"]
        assert resultado["arquivos"] == ["orquestrador.py", "tests/test_novo.py"]

    def test_gate_de_cobertura_vermelho(self, tmp_path: Path) -> None:
        def rodar(cmd, cwd):
            if cmd[0] == "git":
                return 0, " M x.py\n"
            return 1, "ERROR: Required test coverage of 90.0% not reached\n"

        resultado = validar_sessao(rodar=rodar, repo=tmp_path)
        assert resultado["ok"] is False  # o gate DERRUBA como no CI

    def test_porcelain_de_rename_e_aspas(self, tmp_path: Path) -> None:
        def rodar(cmd, cwd):
            if cmd[0] == "git":
                return 0, 'R  "old file.py" -> "new file.py"\n'
            return 0, "1 passed\n"

        resultado = validar_sessao(rodar=rodar, repo=tmp_path)
        assert resultado["arquivos"] == ["new file.py"]


class TestCommitarSessao:
    def test_commita_so_o_codigo_fora_de_dados(self, tmp_path: Path) -> None:
        chamadas: list[list[str]] = []

        def rodar(cmd, cwd):
            chamadas.append(cmd)
            if cmd[:3] == ["git", "status", "--porcelain"]:
                return 0, (
                    " M orquestrador.py\n"
                    "?? data/dev_sessao.json\n"
                    "?? backups/snapshot.json\n"
                    "?? logs/dev_sessao.log\n"
                )
            if cmd[1] == "commit":
                return 0, "[master abc1234] ok\n"
            if cmd[1] == "rev-parse":
                return 0, "abc1234\n"
            return 0, ""

        info = commitar_sessao("adicionei o tema claro", rodar=rodar, repo=tmp_path)
        assert info == {"ok": True, "commit": "abc1234", "arquivos": 1}
        add = next(c for c in chamadas if c[1] == "add")
        assert add == ["git", "add", "--", "orquestrador.py"]
        commit = next(c for c in chamadas if c[1] == "commit")
        assert "feat(dev): adicionei o tema claro" in commit

    def test_sem_diff_retorna_none(self, tmp_path: Path) -> None:
        chamadas: list[list[str]] = []

        def rodar(cmd, cwd):
            chamadas.append(cmd)
            return 0, "" if cmd[1] == "status" else ""

        assert commitar_sessao("qualquer", rodar=rodar, repo=tmp_path) is None
        assert all(c[1] != "add" for c in chamadas)  # nada a stagear

    def test_falha_no_add_nao_commita(self, tmp_path: Path) -> None:
        def rodar(cmd, cwd):
            if cmd[1] == "status":
                return 0, " M x.py\n"
            if cmd[1] == "add":
                return 128, "fatal: pathspec não existe"
            raise AssertionError("commit não deveria ser chamado")

        info = commitar_sessao("x", rodar=rodar, repo=tmp_path)
        assert info["ok"] is False
        assert "pathspec" in info["erro"]

    def test_falha_no_commit_devolve_erro(self, tmp_path: Path) -> None:
        def rodar(cmd, cwd):
            if cmd[1] == "status":
                return 0, " M x.py\n"
            if cmd[1] == "add":
                return 0, ""
            if cmd[1] == "commit":
                return 1, "nothing to commit (mesmo assim)"
            return 0, ""

        info = commitar_sessao("x", rodar=rodar, repo=tmp_path)
        assert info["ok"] is False
        assert "nothing to commit" in info["erro"]


class TestExecutarSessao:
    def test_caminho_feliz_commita_e_fecha(self, tmp_path: Path) -> None:
        estado = _rodar_sessao(
            tmp_path,
            executar=lambda spec, prompt: "pronto: tema claro no painel",
        )
        assert estado["status"] == "concluido"
        assert estado["motivo"] == "implantado"
        assert estado["commit"] == "abc1234"
        assert estado["cli_usada"] == "A"
        assert estado["ativo"] is False
        assert estado["testes"] == VALIDACAO_OK["testes"]
        no_disco = json.loads(
            (tmp_path / "estado.json").read_text(encoding="utf-8")
        )
        assert no_disco["status"] == "concluido"
        assert no_disco["updated_at"]
        caixa = _caixa_de(tmp_path)
        assert caixa[0]["tipo"] == "info" and "iniciada" in caixa[0]["texto"]
        assert "concluido" in caixa[-1]["texto"]

    def test_todas_as_clis_falham(self, tmp_path: Path) -> None:
        estado = _rodar_sessao(
            tmp_path,
            clis=[_spec("A"), _spec("B")],
            executar=lambda spec, prompt: None,
        )
        assert estado["status"] == "falhou"
        assert estado["motivo"] == "todas_as_clis_falharam"
        assert estado["cli_usada"] == ""

    def test_cascata_pula_para_a_proxima(self, tmp_path: Path) -> None:
        def executar(spec, prompt):
            return None if spec.nome == "A" else "pronto pela B"

        estado = _rodar_sessao(
            tmp_path, clis=[_spec("A"), _spec("B")], executar=executar
        )
        assert estado["status"] == "concluido"
        assert estado["cli_usada"] == "B"

    def test_autorizacao_pausa_e_retoma_com_a_resposta(
        self, tmp_path: Path
    ) -> None:
        prompts: list[str] = []
        respostas = iter([
            "feito.\n[AUTORIZACAO] posso reiniciar o od-core?",
            "feito sem marcador, tudo certo",
        ])

        def executar(spec, prompt):
            prompts.append(prompt)
            return next(respostas)

        estado = _rodar_sessao(
            tmp_path,
            executar=executar,
            esperar_resposta=lambda ja_ditadas: "pode sim",
        )
        assert estado["status"] == "concluido"
        assert estado["autorizacoes"] == 1
        assert estado["rodada"] == 2
        assert len(prompts) == 2
        # a CLI nova recebe o histórico da rodada anterior (one-shot sem memória)
        assert "[Resposta do dono] pode sim" in prompts[1]
        assert "[Autorização pedida] posso reiniciar o od-core?" in prompts[1]
        caixa = _caixa_de(tmp_path)
        assert [m["tipo"] for m in caixa] == ["info", "pedir_autorizacao", "info"]
        assert caixa[1]["respondida"] is True  # _marcar_respondidas
        assert caixa[1]["texto"] == "posso reiniciar o od-core?"

    def test_sem_resposta_do_dono_a_sessao_falha(self, tmp_path: Path) -> None:
        def executar(spec, prompt):
            return "[AUTORIZACAO] subo o APK?"

        estado = _rodar_sessao(
            tmp_path, executar=executar, esperar_resposta=lambda n: None
        )
        assert estado["status"] == "falhou"
        assert estado["motivo"] == "autorizacao_nao_respondida"
        caixa = _caixa_de(tmp_path)
        assert caixa[1]["respondida"] is False  # continua no mural do painel

    def test_testes_vermelhos_nao_commita(self, tmp_path: Path) -> None:
        chamado = {"commit": False}

        def commitar(titulo):
            chamado["commit"] = True
            return {"ok": True, "commit": "nao"}

        estado = _rodar_sessao(
            tmp_path,
            executar=lambda spec, prompt: "pronto",
            validar=lambda: {"ok": False, "testes": "2 failed",
                             "arquivos": ["x.py"], "diff": "x.py"},
            commitar=commitar,
        )
        assert estado["status"] == "falhou"
        assert estado["motivo"] == "testes_vermelhos"
        assert chamado["commit"] is False

    def test_sem_diff_nao_commita(self, tmp_path: Path) -> None:
        chamado = {"commit": False}

        def commitar(titulo):
            chamado["commit"] = True
            return {"ok": True, "commit": "nao"}

        estado = _rodar_sessao(
            tmp_path,
            executar=lambda spec, prompt: "já estava pronto",
            validar=lambda: {"ok": True, "testes": "1 passed",
                             "arquivos": [], "diff": ""},
            commitar=commitar,
        )
        assert estado["status"] == "concluido"
        assert estado["motivo"] == "nada_mudou"
        assert chamado["commit"] is False

    def test_commit_recusado_continua_concluido(self, tmp_path: Path) -> None:
        estado = _rodar_sessao(
            tmp_path,
            executar=lambda spec, prompt: "pronto",
            commitar=lambda titulo: {"ok": False, "erro": "git ocupado"},
        )
        assert estado["status"] == "concluido"
        assert estado["motivo"] == "commit_nao_realizado"
        assert estado["commit"] == ""

    def test_commit_sem_alvos_e_nada_mudou(self, tmp_path: Path) -> None:
        """commitar devolve None quando o diff é só de dados (gitignored):
        não é falha de git — é sessão que não mexeu em código."""
        estado = _rodar_sessao(
            tmp_path,
            executar=lambda spec, prompt: "já estava tudo certo",
            commitar=lambda titulo: None,
        )
        assert estado["status"] == "concluido"
        assert estado["motivo"] == "nada_mudou"
        assert estado["commit"] == ""

    def test_limite_de_autorizacoes_estanca(self, tmp_path: Path) -> None:
        """N pedidos e o runner trava a sessão — sem loop infinito eterno."""
        estado = _rodar_sessao(
            tmp_path,
            executar=lambda spec, prompt: "…\n[AUTORIZACAO] e agora?",
            esperar_resposta=lambda n: "segue",
        )
        assert estado["status"] == "falhou"
        assert estado["motivo"] == "limite_de_autorizacoes_excedido"
        caixa = _caixa_de(tmp_path)
        perguntas = [m for m in caixa if m["tipo"] == "pedir_autorizacao"]
        assert len(perguntas) == SESSAO_MAX_AUTORIZACOES

    def test_sem_injecao_usa_os_defaults_da_casa(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """`validar`/`commitar` sem injeção caem nos REAIS (suíte canônica +
        git) — aqui trocados por fakes para o teste não rodar pytest dentro
        de pytest, mas o ramo dos defaults é exercitado de verdade."""
        monkeypatch.setattr(orch, "validar_sessao", lambda: dict(VALIDACAO_OK))
        monkeypatch.setattr(
            orch, "commitar_sessao", lambda titulo: {"ok": True, "commit": "def123"}
        )
        estado = executar_sessao(
            "ideia default",
            clis=[_spec("A")],
            executar=lambda spec, prompt: "pronto",
            arquivo_estado=tmp_path / "estado.json",
            arquivo_caixa=tmp_path / "caixa.json",
        )
        assert estado["status"] == "concluido"
        assert estado["commit"] == "def123"


class TestMainSessao:
    def test_sem_ideia_retorna_2(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        assert main_sessao() == 2

    def test_cli_invalida_retorna_2(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "txt.txt").write_text("ideia boa", encoding="utf-8")
        assert main_sessao("gpt-99") == 2

    def test_executa_a_sessao_com_a_cascata(self, tmp_path: Path,
                                            monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "txt.txt").write_text("crie o botão de tema", encoding="utf-8")
        capturado: dict = {}

        def falso_executar(ideia, *, cli="auto", clis=None):
            capturado.update(ideia=ideia, cli=cli, clis=clis)
            return {"status": "concluido", "motivo": "implantado"}

        monkeypatch.setattr(orch, "executar_sessao", falso_executar)
        assert main_sessao() == 0
        assert capturado["ideia"] == "crie o botão de tema"
        assert capturado["cli"] == "auto"
        assert capturado["clis"] == CLIS  # auto → Freebuff → OpenCode → Kilo

    def test_sessao_falhada_retorna_1(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "txt.txt").write_text("ideia", encoding="utf-8")
        monkeypatch.setattr(
            orch, "executar_sessao",
            lambda ideia, *, cli="auto", clis=None: {
                "status": "falhou", "motivo": "testes_vermelhos",
            },
        )
        assert main_sessao("kilo") == 1


class TestRodarPorContaPropria:
    """`_rodar` é o default de validar_sessao/commitar_sessao — o runner de
    verdade depende dele, então ele tem teste próprio (não só o fake)."""

    def test_comando_existente_devolve_codigo_e_saida(self, tmp_path: Path) -> None:
        codigo, saida = orch._rodar(
            [orch.sys.executable, "-c", "print('oi')"], tmp_path
        )
        assert codigo == 0
        assert "oi" in saida

    def test_comando_inexistente_nunca_levanta(self, tmp_path: Path) -> None:
        codigo, saida = orch._rodar(["binario-que-nao-existe-xyz"], tmp_path)
        assert codigo == 1
        assert saida  # o erro vira string, não exceção


class TestMain:
    """`main` só tem o modo sessão — sem flag ele recusa (fila removida)."""

    def test_flag_sessao_executa_o_modo_sessao(self, tmp_path: Path,
                                               monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "txt.txt").write_text("ideia via flag", encoding="utf-8")
        capturado: dict = {}

        def falso_executar(ideia, *, cli="auto", clis=None):
            capturado.update(ideia=ideia, cli=cli)
            return {"status": "concluido", "motivo": "implantado"}

        monkeypatch.setattr(orch, "executar_sessao", falso_executar)
        assert orch.main(["--sessao", "--cli", "opencode"]) == 0
        assert capturado == {"ideia": "ideia via flag", "cli": "opencode"}

    def test_flag_sessao_sem_ideia_retorna_2(self, tmp_path: Path,
                                             monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        assert orch.main(["--sessao"]) == 2

    def test_sem_flag_recusa_o_processo(self) -> None:
        """Sem --sessao não há mais fila: exit 2 em vez de rodar no escuro."""
        assert orch.main([]) == 2

