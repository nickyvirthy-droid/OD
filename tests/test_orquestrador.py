"""
OMEGA DRAKON • TESTS
Módulo: tests/test_orquestrador.py
Descrição: testes do orquestrador de fallback entre CLIs de IA
           (orquestrador.py) — monitor de pedido.txt, cascata
           Freebuff → OpenCode → Kilo e validação de sintaxe via ast.parse.

Baseado em:
  - orquestrador.py
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

from pathlib import Path

import orquestrador as orch
from orquestrador import (
    CliSpec,
    ciclo,
    extrair_codigo,
    ler_e_limpar_pedido,
    montar_prompt,
    processar_pedido,
    validar_sintaxe,
)


CODIGO_OK = "x = 1\n"
CODIGO_QUEBRADO = "def quebrada(:\n"


def _spec(nome: str) -> CliSpec:
    return CliSpec(nome=nome, binario=nome.lower(), args_antes=("run",))


class TestMontarPrompt:
    def test_prompt_bate_a_instrucao_com_o_pedido(self) -> None:
        prompt = montar_prompt("  crie o previsao_tempo.py  ")
        assert "previsao_tempo.py" in prompt
        assert "crie o previsao_tempo.py" in prompt

    def test_prompt_blindado_proibe_markdown(self) -> None:
        prompt = montar_prompt("qualquer coisa")
        assert "```" in prompt  # proibição explícita de cerca
        assert "código puro" in prompt


class TestExtrairCodigo:
    def test_sem_cerca_volta_sem_bordas(self) -> None:
        assert extrair_codigo(CODIGO_OK) == "x = 1"

    def test_cerca_python_removida(self) -> None:
        resposta = f"```python\n{CODIGO_OK}```"
        assert extrair_codigo(resposta) == "x = 1"

    def test_cerca_sem_linguagem_removida(self) -> None:
        resposta = f"```\n{CODIGO_OK}```"
        assert extrair_codigo(resposta) == "x = 1"

    def test_cerca_aberta_sem_fechamento(self) -> None:
        assert extrair_codigo(f"```python\n{CODIGO_OK}") == "x = 1"


class TestValidarSintaxe:
    def test_codigo_valido(self) -> None:
        assert validar_sintaxe(CODIGO_OK) is True
        assert validar_sintaxe("def f():\n    return 1\n") is True

    def test_codigo_invalido(self) -> None:
        assert validar_sintaxe(CODIGO_QUEBRADO) is False

    def test_vazio_e_invalido(self) -> None:
        assert validar_sintaxe("") is False
        assert validar_sintaxe("   \n") is False


class TestLearLimparPedido:
    def test_le_e_limpa(self, tmp_path: Path) -> None:
        alvo = tmp_path / "pedido.txt"
        alvo.write_text("crie o teste.py\n", encoding="utf-8")
        assert ler_e_limpar_pedido(alvo) == "crie o teste.py"
        assert alvo.read_text(encoding="utf-8") == ""

    def test_arquivo_ausente_e_nada(self, tmp_path: Path) -> None:
        assert ler_e_limpar_pedido(tmp_path / "inexistente.txt") is None

    def test_arquivo_em_branco_nada_faz(self, tmp_path: Path) -> None:
        alvo = tmp_path / "pedido.txt"
        alvo.write_text("   \n", encoding="utf-8")
        assert ler_e_limpar_pedido(alvo) is None


class TestProcessarPedido:
    def test_primeira_cli_valida_vence(self, tmp_path: Path) -> None:
        saida = tmp_path / "out.py"
        registradas: list[str] = []

        def executar(spec: CliSpec, prompt: str) -> str | None:
            registradas.append(spec.nome)
            return CODIGO_OK

        resultado = processar_pedido("pedido", saida, executar, [_spec("A"), _spec("B")])
        assert resultado.ok is True
        assert resultado.cli == "A"
        assert saida.read_text(encoding="utf-8") == CODIGO_OK  # com \n final garantido
        assert registradas == ["A"]  # nunca chamou a B

    def test_falha_da_primeira_cai_para_a_segunda(self, tmp_path: Path) -> None:
        saida = tmp_path / "out.py"

        def executar(spec: CliSpec, prompt: str) -> str | None:
            return None if spec.nome == "A" else CODIGO_OK

        resultado = processar_pedido("pedido", saida, executar, [_spec("A"), _spec("B")])
        assert resultado.ok is True
        assert resultado.cli == "B"

    def test_sintaxe_invalida_pula_para_a_proxima(self, tmp_path: Path) -> None:
        """Regra central: código quebrado NÃO encerra — avança na cascata."""
        saida = tmp_path / "out.py"

        def executar(spec: CliSpec, prompt: str) -> str | None:
            return CODIGO_QUEBRADO if spec.nome == "A" else CODIGO_OK

        resultado = processar_pedido("pedido", saida, executar, [_spec("A"), _spec("B")])
        assert resultado.ok is True
        assert resultado.cli == "B"
        assert saida.read_text(encoding="utf-8") == CODIGO_OK

    def test_todas_falham_nao_grava_nada(self, tmp_path: Path) -> None:
        saida = tmp_path / "out.py"
        resultado = processar_pedido(
            "pedido", saida, lambda spec, prompt: None, [_spec("A"), _spec("B")]
        )
        assert resultado.ok is False
        assert resultado.cli is None
        assert not saida.exists()

    def test_todas_com_sintaxe_invalida_nao_grava_nada(self, tmp_path: Path) -> None:
        saida = tmp_path / "out.py"
        resultado = processar_pedido(
            "pedido",
            saida,
            lambda spec, prompt: CODIGO_QUEBRADO,
            [_spec("A"), _spec("B")],
        )
        assert resultado.ok is False
        assert not saida.exists()


class TestCiclo:
    def test_ciclo_processa_e_reporta_trabalho(self, tmp_path: Path) -> None:
        pedido = tmp_path / "pedido.txt"
        saida = tmp_path / "out.py"
        pedido.write_text("crie o x.py", encoding="utf-8")
        ok = ciclo(pedido, saida, lambda spec, prompt: CODIGO_OK, [_spec("A")])
        assert ok is True
        assert saida.exists()
        assert pedido.read_text(encoding="utf-8") == ""  # limpo (anti-loop)

    def test_ciclo_sem_pedido_nao_trabalha(self, tmp_path: Path) -> None:
        ok = ciclo(tmp_path / "pedido.txt", tmp_path / "out.py", None, [])  # type: ignore[arg-type]
        assert ok is False

    def test_ciclo_com_todas_falhando_reporta_false(self, tmp_path: Path) -> None:
        pedido = tmp_path / "pedido.txt"
        pedido.write_text("pedido", encoding="utf-8")
        ok = ciclo(
            pedido, tmp_path / "out.py", lambda spec, prompt: None, [_spec("A")]
        )
        assert ok is False


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
        assert orch.PEDIDO_INTERVALO_S == 5


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
