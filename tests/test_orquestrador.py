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
        nomes = [spec.nome for spec in orch.CLIS]
        assert nomes == ["Freebuff", "OpenCode", "Kilo"]
        freebuff, opencode, kilo = orch.CLIS
        assert freebuff.binario == "freebuff" and freebuff.args_antes == ("ask",)
        assert opencode.binario == "opencode" and opencode.args_antes == ("run",)
        assert kilo.binario == "kilo"
        assert kilo.args_antes == ("run",) and kilo.args_depois == ("--auto",)

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
        monkeypatch.setattr(orch.shutil, "which", lambda nome: None)
        spec = CliSpec(nome="Falso", binario="fantasma", args_antes=("run",))
        assert orch.executar_cli(spec, "PROMPT") is None
