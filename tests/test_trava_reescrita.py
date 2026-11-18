"""
OMEGA DRAKON • TESTS
Módulo: tests/test_trava_reescrita.py
Descrição: Trava de reescrita maciça fora do orquestrador (hook pre-commit).

           A regra nasceu no orquestrador em 18/11 e só valia para sessões
           `--sessao`. Agora `tools/trava_reescrita.py` é a fonte única:
           o hook `pre-commit` (tools/instalar_hooks.sh) confere o STAGE e o
           orquestrador usa a mesma função no WORKING TREE.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projetti
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tools import trava_reescrita as trava


def _repo_com_arquivo(tmp_path: Path, linhas: int) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    alvo = repo / "grande.py"
    alvo.write_text("\n".join(f"linha {i}" for i in range(linhas)) + "\n",
                    encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"],
        cwd=repo, check=True,
    )
    return repo


class TestNucleoPuro:
    def test_reescrita_maciça_e_suspeita(self) -> None:
        assert trava.avaliar([("x.py", 300, 3)]) == ["x.py: antes=300 depois=3"]

    def test_edicao_normal_passa(self) -> None:
        assert trava.avaliar([("x.py", 300, 290)]) == []

    def test_arquivo_pequeno_nao_e_vigiado(self) -> None:
        assert trava.avaliar([("x.py", 99, 1)]) == []

    def test_limiar_e_minimo_configuraveis(self) -> None:
        assert trava.avaliar([("x.py", 300, 200)], limiar_=0.5, minimo=100) == []
        assert trava.avaliar([("x.py", 300, 50)], limiar_=0.3, minimo=100) != []

    def test_limiar_por_ambiente(self, monkeypatch) -> None:
        monkeypatch.setenv("OD_TRAVA_LIMIAR", "0.9")
        assert trava.limiar() == 0.9
        monkeypatch.setenv("OD_TRAVA_LIMIAR", "abc")
        assert trava.limiar() == trava.LIMIAR_PADRAO


class TestNoGit:
    def test_stage_com_reescrita_maciça_bloqueia(self, tmp_path: Path) -> None:
        repo = _repo_com_arquivo(tmp_path, 300)
        (repo / "grande.py").write_text("pronto\nok\nfim\n", encoding="utf-8")
        subprocess.run(["git", "add", "grande.py"], cwd=repo, check=True)
        suspeitos = trava.verificar(repo, staged=True)
        assert suspeitos and "grande.py" in suspeitos[0]

    def test_worktree_com_reescrita_maciça_bloqueia(self, tmp_path: Path) -> None:
        repo = _repo_com_arquivo(tmp_path, 300)
        (repo / "grande.py").write_text("pronto\n", encoding="utf-8")
        assert trava.verificar(repo, staged=False) != []

    def test_edicao_normal_libera(self, tmp_path: Path) -> None:
        repo = _repo_com_arquivo(tmp_path, 300)
        alvo = repo / "grande.py"
        alvo.write_text(alvo.read_text(encoding="utf-8") + "nova\n", encoding="utf-8")
        subprocess.run(["git", "add", "grande.py"], cwd=repo, check=True)
        assert trava.verificar(repo, staged=True) == []

    def test_main_bloqueia_com_exit_1(self, tmp_path: Path, monkeypatch, capsys) -> None:
        repo = _repo_com_arquivo(tmp_path, 300)
        (repo / "grande.py").write_text("pronto\n", encoding="utf-8")
        subprocess.run(["git", "add", "grande.py"], cwd=repo, check=True)
        monkeypatch.chdir(repo)
        assert trava.main(["--staged"]) == 1
        erro = capsys.readouterr().err
        assert "COMMIT BLOQUEADO" in erro and "OD_TRAVA_OFF=1" in erro

    def test_escape_consciente_libera(self, tmp_path: Path, monkeypatch) -> None:
        repo = _repo_com_arquivo(tmp_path, 300)
        (repo / "grande.py").write_text("pronto\n", encoding="utf-8")
        subprocess.run(["git", "add", "grande.py"], cwd=repo, check=True)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("OD_TRAVA_OFF", "1")
        assert trava.main(["--staged"]) == 0


class TestHookInstalado:
    def test_instalador_cria_hook_que_chama_a_trava(self, tmp_path: Path) -> None:
        repo = _repo_com_arquivo(tmp_path, 5)
        script = Path(__file__).resolve().parents[1] / "tools" / "instalar_hooks.sh"
        r = subprocess.run(["bash", str(script)], cwd=repo, capture_output=True,
                           text=True, check=False)
        assert r.returncode == 0, r.stderr
        hook = repo / ".git" / "hooks" / "pre-commit"
        assert hook.exists()
        conteudo = hook.read_text(encoding="utf-8")
        assert "trava_reescrita.py" in conteudo
        assert "--staged" in conteudo

    def test_commit_real_e_bloqueado_pelo_hook(self, tmp_path: Path) -> None:
        """A prova de ponta: git commit de verdade morre no hook."""
        repo = _repo_com_arquivo(tmp_path, 300)
        script = Path(__file__).resolve().parents[1] / "tools" / "instalar_hooks.sh"
        subprocess.run(["bash", str(script)], cwd=repo, check=True,
                       capture_output=True)
        (repo / "grande.py").write_text("pronto\n", encoding="utf-8")
        subprocess.run(["git", "add", "grande.py"], cwd=repo, check=True)
        r = subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "regressão"],
            cwd=repo, capture_output=True, text=True, check=False,
        )
        assert r.returncode != 0
        assert "COMMIT BLOQUEADO" in (r.stdout + r.stderr)

    def test_commit_normal_passa_pelo_hook(self, tmp_path: Path) -> None:
        repo = _repo_com_arquivo(tmp_path, 300)
        script = Path(__file__).resolve().parents[1] / "tools" / "instalar_hooks.sh"
        subprocess.run(["bash", str(script)], cwd=repo, check=True,
                       capture_output=True)
        alvo = repo / "grande.py"
        alvo.write_text(
            alvo.read_text(encoding="utf-8") + "linha nova\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "grande.py"], cwd=repo, check=True)
        r = subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "ok"],
            cwd=repo, capture_output=True, text=True, check=False,
        )
        assert r.returncode == 0, r.stdout + r.stderr
