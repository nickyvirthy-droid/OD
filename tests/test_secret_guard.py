"""Guarda de segredos no CI (ordem do dono 20/10 — "pode implementar").

Hermético nos casos sintéticos (textos montados nos testes) e com um
teste VIVO no fim: o repo real inteiro precisa varrer limpo — é ele que
segura o CI verde e falha primeiro aqui, não no GitHub.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools import secret_guard as sg

RAIZ = Path(__file__).resolve().parents[1]


class TestPadroes:
    @pytest.mark.parametrize(
        ("padrao_esperado", "segredo"),
        [
            # PEMs montados por concatenação: o literal completo não pode
            # existir no fonte (a guarda varre o próprio repo — o teste
            # vivo logo abaixo falharia).
            ("chave-privada-PEM", "-----BEGIN " + "RSA " + "PRIVATE KEY-----"),
            ("chave-privada-PEM", "-----BEGIN " + "PRIVATE KEY-----"),
            ("chave-privada-PEM", "-----BEGIN " + "OPENSSH " + "PRIVATE KEY-----"),
            ("github-token", "ghp_" + "A" * 36),
            ("github-token", "gho_" + "B" * 36),
            ("github-token", "ghs_" + "C" * 36),
            ("github-token", "github_pat_" + "d" * 22),
            ("openai-key", "sk-" + "a1B2" * 8),
            ("google-key", "AIza" + "x9Y8" * 8 + "z9W"),  # 35 chars exatos
            ("telegram-bot-token", "123456789:" + "Aa1_" * 8 + "Aa1"),
            ("aws-access-key", "AKIA" + "ABCDEFGH12345678"),
            ("slack-token", "xoxb-" + "a1b2c3d4e5" * 2),
            ("gitlab-pat", "glpat-" + "Xy9-" * 6 + "Xy"),
        ],
    )
    def test_acha_o_padrao_cert(self, padrao_esperado: str, segredo: str) -> None:
        texto = f"const token = '{segredo}';  # usado no teste"
        achados = sg.achar_em_texto(texto, "falso.py")
        assert [a.padrao for a in achados] == [padrao_esperado]
        assert achados[0].linha == 1

    def test_linha_e_reportada(self) -> None:
        texto = "limpa\noutra\nchave = " + "sk-" + "z" * 30 + "\nfim"
        achados = sg.achar_em_texto(texto, "a.txt")
        assert len(achados) == 1
        assert achados[0].linha == 3

    def test_varios_na_mesma_linha_contam(self) -> None:
        texto = "k1=" + "ghp_" + "a" * 36 + " k2=" + "AKIA" + "B" * 16
        assert len(sg.achar_em_texto(texto, "x")) == 2

    def test_texto_limpo_nao_acusa(self) -> None:
        texto = (
            "MEU_TOKEN=valor-do-banco sk-modelo task-sk-12345678901234567890123\n"
            "https://api.telegram.org/bot<TOKEN>/sendMessage\n"
            "AIza é só menção do nome, sem os 35 caracteres depois\n"
        )
        assert sg.achar_em_texto(texto, "ok.py") == []

    def test_limite_do_padrao_nao_vaza(self) -> None:
        """ghp_ com 35 (não 36) caracteres NÃO é token — não acusa."""
        assert sg.achar_em_texto("ghp_" + "a" * 35, "perto.py") == []

    def test_proprio_fonte_do_guard_nao_casa(self) -> None:
        """O arquivo da guarda contém os padrões como literal — e não acusa."""
        fonte = (RAIZ / "tools" / "secret_guard.py").read_text("utf-8")
        assert sg.achar_em_texto(fonte, "secret_guard.py") == []


class TestVarredura:
    def test_varre_só_o_que_mandarem(self, tmp_path: Path) -> None:
        (tmp_path / "sujo").write_text("x = " + "sk-" + "q" * 40, "utf-8")
        (tmp_path / "limpo").write_text("x = 1", "utf-8")
        achados = sg.varrer(tmp_path, ["sujo", "limpo"])
        assert [a.arquivo for a in achados] == ["sujo"]

    def test_binario_pulado(self, tmp_path: Path) -> None:
        (tmp_path / "foto.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\xff" * 64)
        assert sg.varrer(tmp_path, ["foto.png"]) == []

    def test_arquivo_sumido_nao_derruba(self, tmp_path: Path) -> None:
        assert sg.varrer(tmp_path, ["nao-existe.txt"]) == []

    def test_arquivos_rastreados_pega_o_git(self) -> None:
        nomes = sg.arquivos_rastreados(RAIZ)
        assert "tools/secret_guard.py" in nomes
        assert ".env" not in nomes  # gitignorado nunca entra
        assert not any(n.startswith("backups/") for n in nomes)

    def test_fora_de_repo_erro_tipado(self, tmp_path: Path) -> None:
        with pytest.raises(sg.GuardError):
            sg.arquivos_rastreados(tmp_path)


class TestMain:
    def test_exit_0_no_repo_limpo(self, monkeypatch, capsys) -> None:
        """Repo real, sem segredo → 0 e resumo com a contagem."""
        assert sg.main([]) == 0
        assert "0 achados" in capsys.readouterr().out

    def test_exit_1_quando_acha(self, monkeypatch, tmp_path, capsys) -> None:
        raiz = tmp_path / "repo"
        (raiz / "tools").mkdir(parents=True)
        (raiz / "dado.txt").write_text("k = " + "ghp_" + "F" * 36, "utf-8")
        monkeypatch.setattr(
            sg, "__file__", str(raiz / "tools" / "secret_guard.py")
        )
        monkeypatch.setattr(sg, "arquivos_rastreados", lambda _raiz: ["dado.txt"])
        assert sg.main([]) == 1
        out = capsys.readouterr()
        assert "github-token" in out.out
        assert "dado.txt" in out.out

    def test_saida_ci_vira_annotacao(self, monkeypatch, tmp_path, capsys) -> None:
        monkeypatch.setenv("CI", "true")
        monkeypatch.setattr(sg, "arquivos_rastreados", lambda _raiz: ["d.txt"])
        monkeypatch.setattr(sg, "__file__", str(tmp_path / "y" / "tools" / "guard.py"))
        origem = sg.varrer

        def varrer_falso(raiz, arquivos=None):
            return [sg.Achado("d.txt", 7, "openai-key")]

        monkeypatch.setattr(sg, "varrer", varrer_falso)
        assert sg.main([]) == 1
        assert "::error title=Guarda de segredos::" in capsys.readouterr().out


class TestRepoReal:
    def test_repositorio_publico_esta_limpo(self) -> None:
        """TESTE VIVO: nenhum dos 389 arquivos rastreados tem segredo.

        É este teste que segura o CI verde — se um dia um segredo for
        commitado, ele falha AQUI (local), antes de virar commit público.
        """
        achados = sg.varrer(RAIZ)
        assert achados == [], f"segredo commitado: {achados}"
