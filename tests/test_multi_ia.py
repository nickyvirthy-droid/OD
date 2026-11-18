"""
OMEGA DRAKON • TESTS
Módulo: tests/test_multi_ia.py
Descrição: Convivência das várias IAs sobre o MESMO repositório (18/11).

           Ordem do dono: "agora temos um número muito grande de IAs
           trabalhando sobre OD. garanta que todas prossigam dentro da mesma
           linha sem destruir o que existe (...) mesmo que uma pare no meio do
           caminho por cota ou outra razão a próxima deve prosseguir".

           Garantias testadas aqui:
             1. O brief multi-IA (tools/brief_multi_ia.py) lê o estado real e
                entra no prompt de TODA CLI da cascata;
             2. Reescrita maciça de arquivo rastreado NÃO é commitada;
             3. Gate vermelho não encerra a sessão: a próxima CLI da cascata
                continua de onde a anterior parou.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import orquestrador as orch
from orquestrador import CliSpec, executar_sessao, montar_prompt_sessao
from tools import brief_multi_ia


def _spec(nome: str) -> CliSpec:
    return CliSpec(nome=nome, binario=nome.lower(), args_antes=("run",))


def _rodar(tmp_path: Path, **kwargs):
    kwargs.setdefault("validar", lambda: {
        "ok": True, "testes": "1 passed", "arquivos": ["x.py"], "diff": "x.py",
    })
    kwargs.setdefault("commitar", lambda titulo: {"ok": True, "commit": "abc1234"})
    kwargs.setdefault("fechar", lambda estado: None)
    kwargs.setdefault("clis", [_spec("A")])
    return executar_sessao(
        "adicione o botão de tema",
        arquivo_estado=tmp_path / "estado.json",
        arquivo_caixa=tmp_path / "caixa.json",
        **kwargs,
    )


class TestBriefMultiIA:
    def test_brief_traz_estado_real_do_repo(self) -> None:
        texto = brief_multi_ia.montar_brief()
        assert "BRIEF MULTI-IA" in texto
        assert "HEAD:" in texto and "origin/master:" in texto
        # As regras de convivência são o contrato entre as IAs.
        assert "NUNCA reescrever um arquivo inteiro" in texto
        assert "NÃO se reverte" in texto

    def test_brief_aponta_checkpoint_vigente(self) -> None:
        texto = brief_multi_ia.montar_brief()
        assert "Checkpoint vigente" in texto
        checkpoint = brief_multi_ia._checkpoint()
        assert checkpoint.get("chave")
        assert checkpoint["chave"] in texto

    def test_brief_entra_no_prompt_da_sessao(self) -> None:
        prompt = montar_prompt_sessao("ideia", brief="BRIEF-UNICO-XYZ")
        assert "BRIEF-UNICO-XYZ" in prompt
        # Sem brief, o prompt continua íntegro (compatível com chamadas antigas).
        assert "BRIEF-UNICO-XYZ" not in montar_prompt_sessao("ideia")

    def test_brief_nunca_derruba_o_orquestrador(self, monkeypatch) -> None:
        """Falha na tool vira prompt sem brief — nunca sessão quebrada."""
        import tools.brief_multi_ia as b

        monkeypatch.setattr(b, "montar_brief", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
        assert orch._brief_para_cli() == ""


class TestTravaAntiDestruicao:
    def test_reescrita_maciça_e_detectada(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        alvo = repo / "grande.py"
        alvo.write_text("\n".join(f"linha {i}" for i in range(300)) + "\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"],
            cwd=repo, check=True,
        )
        # A "IA" reescreve o arquivo por cima com 3 linhas (caso de 18/11).
        alvo.write_text("pronto\nok\nfim\n", encoding="utf-8")

        suspeitos = orch._reescritas_em_massa(repo)
        assert len(suspeitos) == 1
        assert "grande.py" in suspeitos[0] and "antes=300" in suspeitos[0]

    def test_edicao_normal_nao_dispara(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        alvo = repo / "normal.py"
        alvo.write_text("\n".join(f"linha {i}" for i in range(300)) + "\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"],
            cwd=repo, check=True,
        )
        alvo.write_text(alvo.read_text(encoding="utf-8") + "linha nova\n", encoding="utf-8")
        assert orch._reescritas_em_massa(repo) == []

    def test_sessao_falha_sem_commitar(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(orch, "_reescritas_em_massa", lambda repo=None: ["orquestrador.py: antes=1654 depois=251"])
        chamou_commit = []
        estado = _rodar(
            tmp_path,
            executar=lambda spec, prompt: "feito",
            commitar=lambda titulo: chamou_commit.append(titulo) or {"ok": True},
        )
        assert estado["status"] == "falhou"
        assert estado["motivo"] == "arquivo_reescrito_em_massa"
        assert chamou_commit == []          # nada publicado
        assert "depois=251" in estado["detalhe"]


class TestCascataAteConcluir:
    def test_gate_vermelho_passa_para_a_proxima_cli(self, tmp_path: Path) -> None:
        """Cota/erro de uma IA não encerra o serviço: a próxima conclui."""
        executadas: list[str] = []

        def executar(spec, prompt):
            executadas.append(spec.nome)
            return "feito"

        validacoes = iter([
            {"ok": False, "testes": "3 failed", "arquivos": ["x.py"], "diff": "x.py"},
            {"ok": True, "testes": "3 passed", "arquivos": ["x.py"], "diff": "x.py"},
        ])

        estado = _rodar(
            tmp_path,
            clis=[_spec("A"), _spec("B")],
            executar=executar,
            validar=lambda: next(validacoes),
        )
        assert executadas == ["A", "B"]
        assert estado["cli_usada"] == "B"
        assert estado["status"] == "concluido"
        assert estado["motivo"] == "implantado"

    def test_cli_indisponivel_nao_consome_a_vez(self, tmp_path: Path) -> None:
        """CLI sem cota devolve None (fail-fast) e a próxima assume no MESMO turno."""
        executadas: list[str] = []

        def executar(spec, prompt):
            executadas.append(spec.nome)
            return None if spec.nome == "A" else "feito"

        estado = _rodar(tmp_path, clis=[_spec("A"), _spec("B")], executar=executar)
        assert executadas == ["A", "B"]
        assert estado["status"] == "concluido"

    def test_todas_vermelhas_encerra_com_motivo(self, tmp_path: Path) -> None:
        estado = _rodar(
            tmp_path,
            clis=[_spec("A"), _spec("B")],
            executar=lambda spec, prompt: "feito",
            validar=lambda: {"ok": False, "testes": "5 failed", "arquivos": [], "diff": ""},
        )
        assert estado["status"] == "falhou"
        assert estado["motivo"] == "testes_vermelhos"

    def test_historico_da_falha_chega_na_proxima_cli(self, tmp_path: Path) -> None:
        prompts: list[str] = []

        def executar(spec, prompt):
            prompts.append(prompt)
            return "feito"

        validacoes = iter([
            {"ok": False, "testes": "test_x falhou: expect 485", "arquivos": ["x.py"], "diff": "x.py"},
            {"ok": True, "testes": "ok", "arquivos": ["x.py"], "diff": "x.py"},
        ])
        _rodar(
            tmp_path,
            clis=[_spec("A"), _spec("B")],
            executar=executar,
            validar=lambda: next(validacoes),
        )
        assert len(prompts) == 2
        assert "test_x falhou: expect 485" in prompts[1]
        assert "preserve o que já existe" in prompts[1]
