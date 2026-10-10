"""
OMEGA DRAKON • TESTS
Módulo: tests/test_orquestrador.py
Descrição: testes do orquestrador de CLIs de IA (orquestrador.py) —
           cascata OpenCode → Kilo e o MODO SESSÃO on-demand (ideia do
           dono no txt.txt). A fila pedido.txt foi removida a pedido do
           dono (2026-10-8); o Freebuff saiu da cascata em 2026-10-10
           (0.2.22 interativa apenas).

Baseado em:
  - orquestrador.py
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import orquestrador as orch
from core.dev_canal import (
    carregar_historico,
    ideia_ja_implementada,
    registrar_ideia,
)
from integrations.api.server import APIHandler

#: Seletor do painel — precisa casar com CLI_SESSAO_OPCOES do orquestrador
#: (o 400 `cli_invalida` do servidor é a outra metade do contrato).
CLIS_SESSAO_SERVER = APIHandler.SESSAO_CLIS
from orquestrador import (
    CLIS,
    SESSAO_HEARTBEAT_S,
    SESSAO_MAX_AUTORIZACOES,
    CliSpec,
    _arvore_suja,
    _buscar_no_codigo,
    _extrair_palavras_chave,
    _montar_contexto_repositorio,
    aguardar_resposta_dono,
    commitar_sessao,
    executar_sessao,
    extrair_analise,
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
        """Contratos PROVADOS no ar (10/10, canal de desenvolvimento):

        - OpenCode: 'run --standalone --auto PROMPT' + modelo FREE (default
          'build' → 'credit_balance_exhausted'); binário só em
          ~/.npm-global/bin. O --standalone é OBRIGATÓRIO: sem ele a CLI se
          conecta a um `opencode serve --service` compartilhado de fundo, e
          quando esse serviço morre no meio da sessão a CLI morre junto
          ("InterruptError: All fibers interrupted", exit=1).
        - Kilo: 'run PROMPT --auto --pure' + modelo free. O
          inclusionai/ling-3.0-flash-sante:free foi REMOVIDO do catálogo
          (sobrou só a variante sem ':free', que exige chave) — toda sessão
          morria com "Model not found".
        - Freebuff SAIU (10/10): a 0.2.22 virou interativa apenas.
        """
        nomes = [spec.nome for spec in orch.CLIS]
        assert nomes == ["OpenCode", "Kilo"]  # Freebuff fora
        opencode, kilo = orch.CLIS
        assert opencode.binario == "opencode"
        assert opencode.args_antes[0] == "run"
        assert "--standalone" in opencode.args_antes  # sem ele: exit=1 no meio
        assert "--auto" in opencode.args_antes  # sessão desanexada, sem humano
        assert "free" in orch.OPENCODE_MODELO  # default pago → sem créditos
        assert opencode.caminho_candidato.endswith(".npm-global/bin/opencode")
        assert kilo.binario == "kilo"
        assert kilo.args_antes == ("run", "-m", orch.KILO_MODELO, "--pure")
        assert kilo.args_depois == ("--auto",)
        assert kilo.caminho_candidato.endswith(".npm-global/bin/kilo")

    def test_freebuff_fora_da_cascata_e_do_seletor(self) -> None:
        """Guarda de regressão (10/10): o freebuff 0.2.22 só tem 'login'.

        Toda sessão morria em ~1 s com
        "error: command-argument value ... is invalid for argument 'command'".
        """
        assert all("freebuff" not in (s.binario, s.nome.lower()) for s in orch.CLIS)
        assert "freebuff" not in orch.CLI_SESSAO_OPCOES
        assert "freebuff" not in CLIS_SESSAO_SERVER

    def test_kilo_modelo_gratuito_de_provedor_conhecido(self) -> None:
        """Guarda de regressão (10/10): modelo que EXISTE no catálogo do Kilo.

        O anterior sumiu do catálogo e a cascata inteira caía com
        "Model not found" depois que o OpenCode falhava.
        """
        assert orch.KILO_MODELO.startswith("kilo/")
        assert orch.KILO_MODELO.endswith(":free")  # sem ':free' exige chave

    def test_comando_base_prefere_candidato_real_e_cai_para_path(self, monkeypatch) -> None:
        """O CANDIDATO vence o PATH (mudança de 10/10).

        Motivo: um `freebuff` wrapper v0.2.22 em /usr/local/bin foi
        escolhido pelo `shutil.which` ANTES do binário real de
        ~/.config/manicode — e a cascata inteira morria por causa dele.
        O caminho candidato É a instalação que o orquestrador conhece.
        """
        spec = CliSpec(
            nome="X",
            binario="fantasma",
            args_antes=(),
            caminho_candidato="~/caminho/fantasma",
        )
        # Sem candidato → o binário do PATH (chamado pelo nome; o subprocesso
        # herda o PATH — comportamento original mantido).
        monkeypatch.setattr(orch.Path, "is_file", lambda self: False)
        monkeypatch.setattr(orch.shutil, "which", lambda nome: "/usr/bin/fantasma")
        assert spec.comando_base() == ["fantasma"]

        # Candidato existe e é executável → ele vence (mesmo com PATH).
        monkeypatch.setattr(orch.Path, "is_file", lambda self: True)
        monkeypatch.setattr(orch.os, "access", lambda p, m: True)
        base = spec.comando_base()
        assert len(base) == 1 and base[0].startswith("/")  # expandido absoluto
        assert base[0].endswith("/caminho/fantasma")

        # Nem candidato nem PATH → o binário cru (erro padrão).
        monkeypatch.setattr(orch.Path, "is_file", lambda self: False)
        monkeypatch.setattr(orch.shutil, "which", lambda nome: None)
        assert spec.comando_base() == ["fantasma"]

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

        class FalsoProcesso:
            returncode = 0

            def communicate(self, timeout=None):
                vistos["timeout"] = timeout
                return "x = 1\n", ""

        def falso_popen(comando, **kwargs):
            vistos["comando"] = comando
            vistos["env"] = kwargs.get("env")
            vistos["grupo"] = kwargs.get("start_new_session")
            return FalsoProcesso()

        monkeypatch.setattr(orch.shutil, "which", lambda nome: "/usr/bin/" + nome)
        monkeypatch.setattr(orch.subprocess, "Popen", falso_popen)
        monkeypatch.setenv("GROQ_API_KEY", "chave-groq")

        spec = CliSpec(nome="Falso", binario="falso", args_antes=("run",), args_depois=("--auto",))
        saida = orch.executar_cli(spec, "PROMPT")

        assert saida == "x = 1"
        assert vistos["comando"] == ["falso", "run", "PROMPT", "--auto"]
        assert vistos["env"]["GROQ_API_KEY"] == "chave-groq"  # chave do .env repassada
        assert vistos["grupo"] is True  # grupo próprio: timeout mata os filhos
        assert vistos["timeout"] == orch.CLI_TIMEOUT_S  # teto aplicado ao communicate

    def test_executar_cli_binario_ausente(self, monkeypatch) -> None:
        """Sem PATH e sem candidato: NADA é executado (guarda de indisponível).

        Endurecido após a mutação M2 (guarda removida) sobreviver — o teste
        antigo só conferia None e um subprocess.Popen inexiste não reclamaria
        (binário inexistente → OSError → None do mesmo jeito, por sorte).
        Aqui a chamada ao Popen é FALHA DE TESTE se acontecer.
        """

        def proibido_popen(*args, **kwargs):
            raise AssertionError("subprocess.Popen não deveria ser chamado")

        monkeypatch.setattr(orch.shutil, "which", lambda nome: None)
        monkeypatch.setattr(orch.subprocess, "Popen", proibido_popen)
        spec = CliSpec(nome="Falso", binario="fantasma", args_antes=("run",))
        assert orch.executar_cli(spec, "PROMPT") is None

    def test_executar_cli_timeout_mata_o_grupo(self, monkeypatch) -> None:
        """Timeout: o grupo INTEIRO morre — sem CLI órfã mexendo no repo.

        Regressão de 09/10 (APK 4049): o runtime da CLI sobrevivia ao kill do
        processo direto e completava o trabalho sem validação nenhuma.
        """
        mortos: list[tuple[int, int]] = []

        class ProcessoEstourado:
            pid = 4242
            returncode = None

            def communicate(self, timeout=None):
                raise orch.subprocess.TimeoutExpired(cmd="falso", timeout=timeout or 0)

            def wait(self, timeout=None):
                return 0

        monkeypatch.setattr(orch.shutil, "which", lambda nome: "/usr/bin/" + nome)
        monkeypatch.setattr(orch.subprocess, "Popen", lambda *a, **k: ProcessoEstourado())
        monkeypatch.setattr(orch.os, "getpgid", lambda pid: 777)
        monkeypatch.setattr(
            orch.os, "killpg", lambda pgid, sinal: mortos.append((pgid, sinal))
        )

        spec = CliSpec(nome="Falso", binario="falso", args_antes=("run",))
        saida = orch.executar_cli(spec, "PROMPT", timeout_s=1)

        assert saida is None
        assert mortos and mortos[0] == (777, orch.signal.SIGTERM)  # grupo morto

    def test_cli_timeout_configuravel_pelo_env(self, monkeypatch) -> None:
        """O teto vem do .env (OD_DEV_CLI_TIMEOUT_S) — pedido do dono 10/10.

        'Para você desenvolver um pedido é necessário 1 hora e às vezes mais'
        — o 600 s fixo matava toda sessão real no meio.
        """
        assert orch.CLI_TIMEOUT_S == int(orch.os.environ.get("OD_DEV_CLI_TIMEOUT_S", "7200"))
        assert orch.CLI_TIMEOUT_S >= 3600  # piso de uma hora de trabalho real

    def test_executar_cli_usa_caminho_candidato_sem_path(self, monkeypatch) -> None:
        """Serviço sem ~/.npm-global no PATH: o candidato resolve a CLI."""
        vistos: dict[str, object] = {}

        class FalsoProcesso:
            returncode = 0

            def communicate(self, timeout=None):
                return "x = 2\n", ""

        def falso_popen(comando, **kwargs):
            vistos["comando"] = comando
            return FalsoProcesso()

        monkeypatch.setattr(orch.shutil, "which", lambda nome: None)
        monkeypatch.setattr(orch.subprocess, "Popen", falso_popen)
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


#: Estado fake de uma sessão CONCLUÍDA (alimento do histórico — core/dev_canal).
CONCLUIDA = {"status": "concluido", "motivo": "implantado", "commit": "abc1234"}


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

    def test_contexto_somente_quando_existe(self) -> None:
        """O contexto (árvore suja + duplicatas) entra no prompt só quando
        há algo a avisar — sem contexto, o prompt não muda (10/10)."""
        sem = montar_prompt_sessao("ideia")
        com = montar_prompt_sessao("ideia", contexto="⚠️ já existe X")
        assert "Contexto do repositório" not in sem
        assert "⚠️ já existe X" in com
        assert "⚠️ já existe X" not in sem

    def test_prompt_ensina_anti_duplicata(self) -> None:
        """O prompt obriga a CLI a verificar se a funcionalidade já existe
        em outra forma antes de criar (pedido do dono 10/10: 'temperatura
        em SP' vs 'temperatura no RJ')."""
        prompt = montar_prompt_sessao("qual a temperatura no rio")
        assert "OUTRA FORMA" in prompt
        assert "NÃO crie duplicata" in prompt


class TestContextoRepositorio:
    """Árvore suja + busca por duplicatas — contexto prévio da CLI (10/10)."""

    def test_extrair_palavras_chave_filtra_vazias(self) -> None:
        """Só significativas: 'implementar qual a temperatura no rio de
        janeiro' → ['temperatura', 'janeiro'] (rio é 3 chars, sai pelo
        regex; 'implementar'/'qual' são palavras vazias)."""
        palavras = _extrair_palavras_chave(
            "implementar qual a temperatura no rio de janeiro"
        )
        assert "temperatura" in palavras
        assert "janeiro" in palavras
        assert "implementar" not in palavras
        assert "qual" not in palavras

    def test_extrair_palavras_chave_preserva_dominio(self) -> None:
        """Termos de domínio NÃO são filtrados mesmo sendo verbos —
        'apagar' e 'mensagens' são exatamente o que se busca no código."""
        palavras = _extrair_palavras_chave("apagar minhas mensagens pelo app")
        assert "apagar" in palavras
        assert "mensagens" in palavras

    def test_busca_no_codigo_acha_e_limita(self, tmp_path: Path) -> None:
        """Acha palavras no código e limita a 3 arquivos por palavra."""
        (tmp_path / "core").mkdir()
        for nome in ("a.py", "b.py", "c.py", "d.py"):
            (tmp_path / "core" / nome).write_text(
                "temperatura = 25\n", encoding="utf-8"
            )
        achados = _buscar_no_codigo(["temperatura"], base=tmp_path)
        # 4 arquivos têm 'temperatura', mas o teto é 3.
        assert len(achados) == 3
        assert all("temperatura" in a for a in achados)

    def test_busca_no_codigo_sem_palavras_vazia(self) -> None:
        assert _buscar_no_codigo([]) == []

    def test_arvore_suja_detecta(self, monkeypatch) -> None:
        """git status --porcelain com saída não vazia → lista de sujos."""
        class FalsoResultado:
            stdout = " M orquestrador.py\n?? arquivo_novo.py\n"

        monkeypatch.setattr(
            orch.subprocess, "run",
            lambda *a, **k: FalsoResultado(),
        )
        sujos = _arvore_suja()
        assert len(sujos) == 2
        assert "orquestrador.py" in sujos[0]

    def test_arvore_suja_ignora_backups_e_sandbox(self, monkeypatch) -> None:
        """Guarda de regressão (10/10): resíduo de backup não é trabalho parcial.

        Motivo: `backups/llm-cache-fakes-*.json` poluía o AVISO de árvore
        suja de TODA sessão (o contexto avisava "1 arquivo(s) não
        commitados" sem motivo) e escondia o trabalho real.
        """
        class FalsoResultado:
            stdout = (
                "?? backups/llm-cache-fakes-20261008-055830.json\n"
                "?? .od_sandbox/temp.txt\n"
                " M core/foo.py\n"
                "?? codigo_novo.py\n"
            )

        monkeypatch.setattr(orch.subprocess, "run", lambda *a, **k: FalsoResultado())
        sujos = _arvore_suja()
        assert len(sujos) == 2  # backups/ e .od_sandbox/ fora
        assert any("core/foo.py" in s for s in sujos)
        assert any("codigo_novo.py" in s for s in sujos)

    def test_arvore_suja_limpa(self, monkeypatch) -> None:
        class FalsoResultado:
            stdout = ""

        monkeypatch.setattr(
            orch.subprocess, "run",
            lambda *a, **k: FalsoResultado(),
        )
        assert _arvore_suja() == []

    def test_arvore_suja_git_indisponivel(self, monkeypatch) -> None:
        """Sem git (OSError) → lista vazia, nunca exceção."""
        def falso_run(*a, **k):
            raise OSError("git não encontrado")

        monkeypatch.setattr(orch.subprocess, "run", falso_run)
        assert _arvore_suja() == []

    def test_contexto_com_arvore_suja_e_duplicata(self, monkeypatch) -> None:
        """Os DOIS avisos aparecem: árvore suja + termos já no código."""
        monkeypatch.setattr(orch, "_arvore_suja", lambda: [" M core/foo.py"])
        monkeypatch.setattr(
            orch, "_buscar_no_codigo",
            lambda palavras: ["'temperatura' → core/intents.py"],
        )
        contexto = _montar_contexto_repositorio(
            "implementar a temperatura no rio"
        )
        assert "NÃO commitadas" in contexto
        assert "core/foo.py" in contexto
        assert "OUTRA FORMA" in contexto
        assert "core/intents.py" in contexto

    def test_contexto_vazio_quando_limpo(self, monkeypatch) -> None:
        """Árvore limpa e sem duplicatas → contexto vazio (prompt inalterado)."""
        monkeypatch.setattr(orch, "_arvore_suja", lambda: [])
        monkeypatch.setattr(orch, "_buscar_no_codigo", lambda p: [])
        assert _montar_contexto_repositorio("qualquer ideia") == ""


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


class TestExtrairAnalise:
    """Bloco [ANALISE]…[FIM ANALISE] — viabilidade/prós/contras/alternativas
    que o dono vê na caixa (pedido dele de 2026-10-08)."""

    BLOCO = (
        "[ANALISE]\n"
        "viabilidade: o repo já tem action_registry\n"
        "pros: reaproveita o catálogo\n"
        "contras: precisa de rede\n"
        "alternativas: fastpath (melhor)\n"
        "escolha: fastpath\n"
        "[FIM ANALISE]\n"
        "implementado com testes."
    )

    def test_bloco_completo_e_extraido(self) -> None:
        analise = extrair_analise(self.BLOCO)
        assert analise is not None
        assert "viabilidade: o repo já tem action_registry" in analise
        assert "escolha: fastpath" in analise
        assert "implementado com testes" not in analise  # sobra do fim

    def test_sem_marcador_e_none(self) -> None:
        assert extrair_analise("só o resumo, sem análise.") is None
        assert extrair_analise("") is None

    def test_fim_esquecido_le_o_resto(self) -> None:
        """CLI esqueceu o [FIM ANALISE] → a análise não se perde."""
        analise = extrair_analise(
            "[ANALISE]\nviabilidade: sim\npros: curto"
        )
        assert analise == "viabilidade: sim\npros: curto"

    def test_bloco_vazio_e_none(self) -> None:
        assert extrair_analise("[ANALISE]\n[FIM ANALISE]") is None
        assert extrair_analise("[ANALISE]   ") is None

    def test_pega_a_primeira_ocorrencia(self) -> None:
        """Em rodadas com autorização o bloco pode repetir — vale o 1º."""
        saida = (
            "[ANALISE]\nviabilidade: a\n[FIM ANALISE]\n"
            "[AUTORIZACAO] posso seguir?\n"
            "[ANALISE]\nviabilidade: b\n[FIM ANALISE]"
        )
        assert extrair_analise(saida) == "viabilidade: a"

    def test_prompt_ensina_o_bloco(self) -> None:
        prompt = montar_prompt_sessao("criar cotação do dólar")
        assert "[ANALISE]" in prompt and "[FIM ANALISE]" in prompt
        assert "viabilidade" in prompt and "alternativas" in prompt
        assert "MELHOR opção" in prompt


class TestResolverClis:
    def test_auto_e_a_cascata_oficial(self) -> None:
        assert resolver_clis("auto") == CLIS
        assert resolver_clis("") == CLIS  # default do painel

    def test_nome_especifico_isola_a_cli(self) -> None:
        assert [s.nome for s in resolver_clis("kilo")] == ["Kilo"]
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

    def test_analise_vai_para_a_caixa_e_para_o_estado(self, tmp_path: Path) -> None:
        """Bloco [ANALISE] (viabilidade/prós/contras/alternativas) publicado
        na CAIXA e no estado — é o que o dono vê antes do código (pedido de
        2026-10-08: 'analisa, verifica prós e contras, sugere alternativas')."""
        saida = (
            "[ANALISE]\nviabilidade: o repo já tem action_registry\n"
            "pros: reaproveita o catálogo\ncontras: precisa de rede\n"
            "alternativas: fastpath (melhor)\nescolha: fastpath\n"
            "[FIM ANALISE]\nimplementado com testes."
        )
        estado = _rodar_sessao(
            tmp_path, executar=lambda spec, prompt: saida
        )
        assert estado["status"] == "concluido"
        assert "viabilidade: o repo já tem action_registry" in estado["analise"]
        assert "escolha: fastpath" in estado["analise"]
        assert "implementado com testes" not in estado["analise"]
        caixa = _caixa_de(tmp_path)
        assert caixa[0]["tipo"] == "info"  # "sessão iniciada" continua 1ª
        assert any(
            "Análise da ideia" in m["texto"] and "escolha: fastpath" in m["texto"]
            for m in caixa
        )
        no_disco = json.loads(
            (tmp_path / "estado.json").read_text(encoding="utf-8")
        )
        assert "escolha: fastpath" in no_disco["analise"]

    def test_resposta_sem_analise_nao_publica_nada(self, tmp_path: Path) -> None:
        """Análise ausente NÃO quebra a sessão nem polui a caixa."""
        estado = _rodar_sessao(
            tmp_path, executar=lambda spec, prompt: "pronto, sem marcador"
        )
        assert estado["status"] == "concluido"
        assert not estado.get("analise")
        assert not any(
            "Análise da ideia" in m["texto"] for m in _caixa_de(tmp_path)
        )

    def test_cli_lenta_grava_decorrido_no_disco(self, tmp_path: Path) -> None:
        """Batimento (10/10): CLI demorada re-grava o estado com o tempo.

        O dono reclamou que a sessão parecia TRAVADA em "EXECUTANDO" durante
        uma implementação de 1 h — o estado só era gravado no início e no fim.
        """
        estado_file = tmp_path / "estado.json"
        vistos: list[int] = []

        def cli_lenta(spec, prompt: str) -> str:
            # A thread do batimento tem de gravar ENQUANTO a CLI roda.
            for _ in range(20):
                if estado_file.exists():
                    dados = json.loads(estado_file.read_text(encoding="utf-8"))
                    if dados.get("decorrido_s") is not None:
                        vistos.append(dados["decorrido_s"])
                        break
                time.sleep(0.05)
            return "pronto: implementado"

        # Batimento rápido de propósito — o teste não espera 15 s. A constante
        # é lida no módulo orquestrador (default do argumento), então é lá que
        # se troca.
        antigo = orch.SESSAO_HEARTBEAT_S
        orch.SESSAO_HEARTBEAT_S = 0.02
        try:
            estado = _rodar_sessao(tmp_path, executar=cli_lenta)
        finally:
            orch.SESSAO_HEARTBEAT_S = antigo

        assert estado["status"] == "concluido"
        assert vistos, "o batimento não gravou decorrido_s durante a CLI"
        assert isinstance(vistos[0], int)
        # Limpo no fim: a sessão fechada não deixa lixo de batimento.
        assert "decorrido_s" not in estado

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

    def test_ideia_ja_implementada_retorna_3(self, tmp_path: Path,
                                             monkeypatch) -> None:
        """Passo 2 do canal: ideia IGUAL a uma concluída não roda de novo —
        o painel avisa antes; aqui é o cinturão de quem chama o runner."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "txt.txt").write_text(
            "  Criar botão de tema\r\n  ", encoding="utf-8"
        )
        registrar_ideia("criar botão de tema", CONCLUIDA)
        chamado = {"n": 0}

        def nao_deve_executar(*args, **kwargs):
            chamado["n"] += 1
            return {"status": "concluido"}

        monkeypatch.setattr(orch, "executar_sessao", nao_deve_executar)
        assert main_sessao() == 3
        assert chamado["n"] == 0

    def test_sessao_concluida_registra_a_ideia(self, tmp_path: Path,
                                               monkeypatch) -> None:
        """Sessão concluída vira HISTÓRICO — é ele que alimenta o aviso do
        próximo clique. Só `concluido` entra (falha não é implementação)."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "txt.txt").write_text("criar botão de tema", encoding="utf-8")
        monkeypatch.setattr(
            orch, "executar_sessao",
            lambda ideia, *, cli="auto", clis=None: {
                "status": "concluido", "motivo": "implantado",
                "commit": "abc1234", "cli_usada": "OpenCode",
            },
        )
        assert main_sessao() == 0
        historico = carregar_historico()
        assert len(historico) == 1
        assert historico[0]["ideia"] == "criar botão de tema"
        assert historico[0]["commit"] == "abc1234"
        assert historico[0]["cli"] == "OpenCode"
        assert ideia_ja_implementada("CRIAR  botão de tema") is not None

    def test_sessao_falhada_nao_registra(self, tmp_path: Path,
                                         monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "txt.txt").write_text("ideia que falhou", encoding="utf-8")
        monkeypatch.setattr(
            orch, "executar_sessao",
            lambda ideia, *, cli="auto", clis=None: {
                "status": "falhou", "motivo": "testes_vermelhos",
            },
        )
        assert main_sessao() == 1
        assert carregar_historico() == []


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

