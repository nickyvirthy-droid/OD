"""
OMEGA DRAKON • TESTES
Tecnologia que respira.
Módulo: tests/test_calibre.py
Descrição: integração Calibre — importação dirigida por LEDGER da inbox
           (espelho do Google Drive do dono) para a biblioteca real via
           `calibredb add -d --automerge new_record` (calibre 9.16 em
           /home/alex/opt; achado em 19/10: o próprio dono instalou em
           08/10). Runner injetável: nenhum calibredb roda de verdade na
           suíte.

Decisão do dono (19/10): Calibre Web "configurar e interligar" — os
livros estavam no Google Drive dele (22 pastas temáticas).

Por que LEDGER (provo ao vivo, 19/10): a primeira importação com
`--automerge ignore` escondeu 156 arquivos cujo título embutido no PDF
colidia com livro já cadastrado ("not added as they already exist").
Ledger (caminho→tamanho) = resync idempotente sem dedup por título;
`-d new_record` = colisão de título vira registro próprio, nada escondido.
"""

from __future__ import annotations

import pathlib
import subprocess
from typing import Any

import pytest

from integrations.calibre import (
    CalibreError,
    carregar_ledger,
    importar_da_inbox,
    salvar_ledger,
    semear_ledger,
)


class FakeProc:
    def __init__(self, rc: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = rc
        self.stdout = stdout
        self.stderr = stderr


def _inbox(tmp_path, nomes=("a.pdf", "b.epub")) -> tuple[str, str]:
    inbox = tmp_path / "inbox" / "Direito"
    inbox.mkdir(parents=True)
    for n in nomes:
        (inbox / n).write_bytes(b"%PDF-1.4 x")
    return str(tmp_path / "inbox"), str(tmp_path / "biblioteca")


def _calibredb_falso(tmp_path) -> str:
    exe = tmp_path / "calibredb"
    exe.write_text("#!/bin/sh\nexit 0\n")
    exe.chmod(0o755)
    return str(exe)


def _semear_tudo(inbox: str) -> None:
    """Ledger cobre todos os arquivos da inbox (estado 'já importado')."""
    import pathlib

    raiz = pathlib.Path(inbox)
    semear_ledger(raiz, [str(p.relative_to(raiz)) for p in raiz.rglob("*") if p.is_file()])


class TestLedger:
    def test_ledger_ausente_recusa_importar_as_cegas(self, tmp_path) -> None:
        inbox, bib = _inbox(tmp_path)
        with pytest.raises(CalibreError) as exc:
            importar_da_inbox(
                inbox=inbox,
                biblioteca=bib,
                calibredb=_calibredb_falso(tmp_path),
            )
        assert exc.value.codigo == "calibre_ledger_ausente"

    def test_ledger_corrompido_vazio_tambem_recusa(self, tmp_path) -> None:
        inbox, bib = _inbox(tmp_path)
        (pathlib.Path(inbox) / ".calibre_ledger.json").write_text("{quebrado")
        with pytest.raises(CalibreError) as exc:
            importar_da_inbox(
                inbox=inbox, biblioteca=bib, calibredb=_calibredb_falso(tmp_path)
            )
        assert exc.value.codigo == "calibre_ledger_ausente"

    def test_semear_e_ler_de_volta(self, tmp_path) -> None:
        inbox, _ = _inbox(tmp_path, nomes=("a.pdf",))
        ledger = semear_ledger(inbox, ["Direito/a.pdf"])
        assert ledger == {"Direito/a.pdf": 10}
        assert carregar_ledger(inbox) == {"Direito/a.pdf": 10}

    def test_semear_nao_duplica_chave_existente(self, tmp_path) -> None:
        inbox, _ = _inbox(tmp_path, nomes=("a.pdf",))
        semear_ledger(inbox, ["Direito/a.pdf"])
        (pathlib.Path(inbox) / "Direito" / "a.pdf").write_bytes(b"mudou!")  # 6 B
        ledger = semear_ledger(inbox, ["Direito/a.pdf"])  # ja existe: intocavel
        assert ledger == {"Direito/a.pdf": 10}

    def test_gravar_e_atomico_sem_sobra(self, tmp_path) -> None:
        inbox, _ = _inbox(tmp_path, nomes=("a.pdf",))
        import pathlib

        salvar_ledger(inbox, {"Direito/a.pdf": 10})
        raiz = pathlib.Path(inbox)
        assert not list(raiz.glob("*.part"))
        assert carregar_ledger(inbox) == {"Direito/a.pdf": 10}


class TestImportarDaInbox:
    def test_binario_ausente_erro_tipado(self, tmp_path) -> None:
        inbox, bib = _inbox(tmp_path)
        with pytest.raises(CalibreError) as exc:
            importar_da_inbox(
                inbox=inbox,
                biblioteca=bib,
                calibredb=str(tmp_path / "nao-existe"),
            )
        assert exc.value.codigo == "calibre_ferramenta_ausente"

    def test_inbox_ausente_erro_tipado(self, tmp_path) -> None:
        with pytest.raises(CalibreError) as exc:
            importar_da_inbox(
                inbox=str(tmp_path / "sumiu"),
                biblioteca=str(tmp_path / "bib"),
                calibredb=_calibredb_falso(tmp_path),
            )
        assert exc.value.codigo == "calibre_inbox_ausente"

    def test_inbox_vazia_resposta_honesta(self, tmp_path) -> None:
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        r = importar_da_inbox(
            inbox=str(inbox),
            biblioteca=str(tmp_path / "bib"),
            calibredb=_calibredb_falso(tmp_path),
        )
        assert r["ok"] and r["novos"] == 0 and "vazia" in r["nota"]

    def test_ledger_em_dia_nem_chama_o_calibre(self, tmp_path) -> None:
        inbox, bib = _inbox(tmp_path)
        _semear_tudo(inbox)
        chamadas: list[list[str]] = []

        def runner(cmd, **kw):
            chamadas.append(cmd)
            return FakeProc(0, stdout="Added book ids: 9\n")

        r = importar_da_inbox(
            inbox=inbox,
            biblioteca=bib,
            calibredb=_calibredb_falso(tmp_path),
            runner=runner,
        )
        assert r["ok"] and r["novos"] == 0 and r["ja_no_ledger"] == 2
        assert chamadas == [], "ledger em dia: calibredb nao pode rodar"

    def test_importa_so_o_novo_com_d_e_new_record(self, tmp_path) -> None:
        inbox, bib = _inbox(tmp_path)
        semear_ledger(inbox, ["Direito/a.pdf"])  # b.epub fica de fora
        captura: dict[str, Any] = {}

        def runner(cmd, **kw):
            captura["cmd"] = cmd
            return FakeProc(0, stdout="Added book ids: 1, 2, 3\n")

        r = importar_da_inbox(
            inbox=inbox,
            biblioteca=bib,
            calibredb=_calibredb_falso(tmp_path),
            runner=runner,
        )
        assert r["ok"] and r["novos"] == 1 and r["ja_no_ledger"] == 1
        assert r["adicionados"] == [1, 2, 3]
        cmd = captura["cmd"]
        assert "--with-library" in cmd and bib in cmd
        assert "-d" in cmd and "new_record" in cmd  # nada escondido por titulo
        assert not any(c.endswith("a.pdf") for c in cmd), "a.pdf ja no ledger"
        assert any(c.endswith("b.epub") for c in cmd)
        # ledger cresceu DEPOIS do rc=0
        assert carregar_ledger(inbox).get("Direito/b.epub") == 10

    def test_rc_diferente_de_zero_erro_e_ledger_nao_cresce(self, tmp_path) -> None:
        inbox, bib = _inbox(tmp_path)
        semear_ledger(inbox, ["Direito/a.pdf"])  # b.epub novo -> runner roda

        def runner(cmd, **kw):
            return FakeProc(1, stdout="", stderr="erro feio\nlinha final\n")

        with pytest.raises(CalibreError) as exc:
            importar_da_inbox(
                inbox=inbox,
                biblioteca=bib,
                calibredb=_calibredb_falso(tmp_path),
                runner=runner,
            )
        assert exc.value.codigo == "calibre_import_falhou"
        assert "linha final" in exc.value.mensagem
        # falha: o novo NAO foi marcado; o que ja estava segue igual
        assert carregar_ledger(inbox) == {"Direito/a.pdf": 10}

    def test_timeout_vira_erro_tipado(self, tmp_path) -> None:
        inbox, bib = _inbox(tmp_path)
        semear_ledger(inbox, ["Direito/a.pdf"])

        def runner(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)

        with pytest.raises(CalibreError) as exc:
            importar_da_inbox(
                inbox=inbox,
                biblioteca=bib,
                calibredb=_calibredb_falso(tmp_path),
                runner=runner,
            )
        assert exc.value.codigo == "calibre_import_timeout"
        assert carregar_ledger(inbox) == {"Direito/a.pdf": 10}

    def test_arquivo_mudou_no_drive_vira_novo(self, tmp_path) -> None:
        inbox, bib = _inbox(tmp_path, nomes=("a.pdf",))
        import pathlib

        semear_ledger(inbox, ["Direito/a.pdf"])  # 10 B
        (pathlib.Path(inbox) / "Direito" / "a.pdf").write_bytes(b"conteudo novo maior")
        captura: dict[str, Any] = {}

        def runner(cmd, **kw):
            captura["cmd"] = cmd
            return FakeProc(0, stdout="Added book ids: 7\n")

        r = importar_da_inbox(
            inbox=inbox,
            biblioteca=bib,
            calibredb=_calibredb_falso(tmp_path),
            runner=runner,
        )
        assert r["novos"] == 1 and any(c.endswith("a.pdf") for c in captura["cmd"])
        assert carregar_ledger(inbox)["Direito/a.pdf"] == len(b"conteudo novo maior")

    def test_ledger_e_part_fora_do_argv(self, tmp_path) -> None:
        inbox, bib = _inbox(tmp_path, nomes=("a.pdf",))
        import pathlib

        raiz = pathlib.Path(inbox)
        (raiz / "Direito" / "a.pdf.part").write_bytes(b"meia")
        semear_ledger(inbox, ["Direito/a.pdf"])
        captura: dict[str, Any] = {}

        def runner(cmd, **kw):
            captura["cmd"] = cmd
            return FakeProc(0, stdout="")

        importar_da_inbox(
            inbox=inbox,
            biblioteca=bib,
            calibredb=_calibredb_falso(tmp_path),
            runner=runner,
        )
        assert captura == {}, "so ledger/part na inbox: nada a chamar"
