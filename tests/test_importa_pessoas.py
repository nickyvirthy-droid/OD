"""
OMEGA DRAKON • TESTS
Módulo: tests/test_importa_pessoas.py
Descrição: testes do script de importação do efetivo policial
           (runtime/importa_pessoas.py) — parsers das 4 fontes, merge
           idempotente por matrícula e a CLI. Fixtures sintéticas: nenhum
           dado real de policial no repositório (regra 16).

Baseado em:
  - runtime/importa_pessoas.py
  - storage/database.py (Database em memória)
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import runtime.importa_pessoas as imp
from runtime.importa_pessoas import (
    _opm_do_cabecalho,
    _textos_do_notebook,
    _viatura_da_linha,
    carrega,
    extrai_mapa_csv,
    extrai_pessoas,
    importa,
    main,
)
from storage.database import Database


@pytest.fixture()
def db() -> Database:
    database = Database()
    yield database
    database.close()


# -- extrai_pessoas: efetivo ------------------------------------------------


class TestEfetivo:
    def test_linha_posto_matricula_dv_nome(self) -> None:
        regs = extrai_pessoas("2º SGT PM 100001-7 ALFA", "efetivo.txt")
        assert len(regs) == 1
        assert regs[0]["posto"] == "2º SGT PM"
        assert regs[0]["matricula"] == "100001"
        assert regs[0]["dv"] == "7"
        assert regs[0]["nome"] == "ALFA"

    def test_dv_letra(self) -> None:
        regs = extrai_pessoas("CB PM 100002-A BETA", "efetivo.txt")
        assert regs[0]["dv"] == "A"
        assert regs[0]["nome"] == "BETA"

    def test_cabecalho_nao_vira_pessoa(self) -> None:
        texto = (
            "OPM\n\t42.BPM/I 3.CIA PM\nViatura:\n\tI-90002\n"
            "TERCEIRA CIA PM\nInício de Turno:\n\t13/07/2024 18:30\n"
        )
        assert extrai_pessoas(texto, "efetivo.txt") == []

    def test_efetivo_sem_viatura_propria(self) -> None:
        regs = extrai_pessoas("Sd PM 100003-0 GAMA", "efetivo.txt")
        assert regs[0]["viatura"] == []
        assert regs[0]["unidade"] == ""

    def test_unidade_do_cabecalho(self) -> None:
        regs = extrai_pessoas(
            "OPM\n\t42.BPM/I 3.CIA PM\n\nCB PM 111111-1 ALFA\n",
            "efetivo.txt",
            unidade="42.BPM/I 3.CIA PM",
        )
        assert regs[0]["unidade"] == "42.BPM/I 3.CIA PM"


# -- extrai_pessoas: tokens -------------------------------------------------


class TestTokens:
    def test_token_simples(self) -> None:
        regs = extrai_pessoas("[CB_PM_100004_DELTA]", "MapaForca.txt")
        assert (regs[0]["posto"], regs[0]["matricula"], regs[0]["nome"]) == (
            "CB",
            "100004",
            "DELTA",
        )

    def test_token_posto_com_ponto(self) -> None:
        regs = extrai_pessoas("[2.SGT_PM_100001_ALFA]", "MapaForca.txt")
        assert regs[0]["posto"] == "2.SGT"

    def test_token_com_1c_no_meio(self) -> None:
        regs = extrai_pessoas("[SD_PM_-_1C_100005_ECHO]", "MapaForca.txt")
        assert (regs[0]["posto"], regs[0]["matricula"], regs[0]["nome"]) == (
            "SD",
            "100005",
            "ECHO",
        )

    def test_token_nome_com_espaco(self) -> None:
        regs = extrai_pessoas("[2.SGT_PM_100006_FULANO DE TAL]", "MapaForca.txt")
        assert regs[0]["nome"] == "FULANO DE TAL"

    def test_tpd_e_vtr_nao_sao_pessoas(self) -> None:
        linha = "[I-90001] [TPD:123456789012:TESTTEST0001] [CB_PM_100007_ROCHA]"
        regs = extrai_pessoas(linha, "MapaForca.txt")
        assert len(regs) == 1
        assert regs[0]["nome"] == "ROCHA"

    def test_varios_tokens_na_mesma_linha(self) -> None:
        linha = "[I-90002] [2.SGT_PM_100001_ALFA] [SD_PM_-_1C_100003_GAMA]"
        regs = extrai_pessoas(linha, "MapaForca.txt")
        assert [r["matricula"] for r in regs] == ["100001", "100003"]
        assert all(r["viatura"] == ["I-90002"] for r in regs)


# -- viatura ---------------------------------------------------------------


class TestViatura:
    def test_colchete_na_mesma_linha(self) -> None:
        linha = "88-901\tDISPONÍVEL\t[88-901] [CB_PM_100008_FELIX]"
        regs = extrai_pessoas(linha, "MapaForcaTudo.txt")
        assert regs[0]["viatura"] == ["88-901"]

    def test_col0_tabulada_sem_colchete(self) -> None:
        linha = "SD90001\tDISPONÍVEL\t[CB_PM_100009_MARIA]\t\tRÁDIO PATRULHA"
        regs = extrai_pessoas(linha, "MapaForcaTudo.txt")
        assert regs[0]["viatura"] == ["SD90001"]

    def test_col0_sem_tab_eh_ignorada(self) -> None:
        # Cabeçalho/relógio sem tab não pode virar viatura.
        assert _viatura_da_linha("TERCEIRA CIA PM") == ""
        assert _viatura_da_linha("608420000") == ""

    def test_pendente_da_linha_anterior(self) -> None:
        # Padrão do efetivo: linha de viatura seguida da linha de policiais.
        texto = "[88-901] [TMD:123456789012:TESTTEST0002]\n[SD_PM_-_1C_100005_ECHO]\n"
        regs = extrai_pessoas(texto, "efetivo.txt")
        assert regs[0]["viatura"] == ["88-901"]

    def test_pendente_reseta_apos_uso(self) -> None:
        texto = (
            "[88-901] [TMD:1]\n"
            "[CB_PM_111111_ALFA]\n"
            "[CB_PM_222222_BETA]\n"
        )
        regs = extrai_pessoas(texto, "efetivo.txt")
        assert regs[0]["viatura"] == ["88-901"]
        assert regs[1]["viatura"] == []

    def test_colchete_vence_col0(self) -> None:
        # Linha tabulada cuja col0 é a própria viatura e há colchete repetido.
        assert _viatura_da_linha("90004\tDISPONÍVEL\t[I-90004] [CB_PM_100007_X]") == "I-90004"


# -- extrai_mapa_csv -------------------------------------------------------


class TestMapaCsv:
    _LINHAS = (
        "inicio,final,cmd,municipio,setor,sub,local,vtr,escala,mod,re,func,re2,func2\n"
        '"13/07/2024 18:30,14/07/2024 06:30,CPI-8,42.BPM/I 3.CIA PM,Teodoro Sampaio,'
        'Area do Municipio,Nenhum Subsetor,3ª CIA PM,I-90002,Ordinaria,CGP,'
        '100001,Encarregado,100003,Motorista"\n'
        "13/07/2024 18:30,14/07/2024 06:30,CPI-8,42.BPM/I 3.CIA PM,Teodoro,Area,"
        "Nenhum,ÁREA DO MUNICÍPIO,I-90005,Ordinaria,RP,100011,Encarregado,100012,Motorista\n"
    )

    def test_extrai_re_e_re2_com_aspas(self) -> None:
        regs = extrai_mapa_csv(self._LINHAS, "Mapa.csv")
        assert [(r["matricula"], r["viatura"]) for r in regs] == [
            ("100001", ["I-90002"]),
            ("100003", ["I-90002"]),
            ("100011", ["I-90005"]),
            ("100012", ["I-90005"]),
        ]

    def test_unidade_e_fonte(self) -> None:
        regs = extrai_mapa_csv(self._LINHAS, "Mapa.csv")
        assert regs[0]["unidade"] == "42.BPM/I 3.CIA PM"
        assert regs[0]["fonte"] == ["Mapa.csv"]
        assert regs[0]["nome"] == ""

    def test_cabecalho_e_linha_curta_ignorados(self) -> None:
        assert extrai_mapa_csv(self._LINHAS.split("\n")[0], "Mapa.csv") == []
        assert extrai_mapa_csv("a,b,c\n", "Mapa.csv") == []

    def test_campo_invalido_ignorado(self) -> None:
        linha = (
            "13/07/2024 18:30,14/07/2024 06:30,CPI-8,42.BPM,Teodoro,Area,Sub,"
            "Local,VIATURA ERRADA,Ord,CGP,123456,Enc,654321,Mot"
        )
        assert extrai_mapa_csv(linha, "Mapa.csv") == []


# -- cabeçalho OPM e notebooks ----------------------------------------------


class TestCabecalhoENotebook:
    def test_opm_do_cabecalho(self) -> None:
        texto = "Grande Comando\n\tCPI-8\n\nOPM\n\t42.BPM/I 3.CIA PM\n\nMunicipio\n"
        assert _opm_do_cabecalho(texto) == "42.BPM/I 3.CIA PM"

    def test_opm_ausente(self) -> None:
        assert _opm_do_cabecalho("linha qualquer") == ""

    def _nb(self, tmp_path: Path, outputs: list, source: list[str] | None = None) -> Path:
        caminho = tmp_path / "x.ipynb"
        caminho.write_text(
            json.dumps(
                {
                    "cells": [
                        {
                            "source": source or ["print('nada')\n"],
                            "outputs": outputs,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return caminho

    def test_pega_texto_lista_e_str(self, tmp_path: Path) -> None:
        caminho = self._nb(
            tmp_path,
            [
                {"text": ["[CB_PM_111111_ALFA]\n"]},
                {"data": {"text/plain": "[CB_PM_222222_BETA]"}},
            ],
        )
        texto = _textos_do_notebook(caminho)
        assert "[CB_PM_111111_ALFA]" in texto
        assert "[CB_PM_222222_BETA]" in texto

    def test_source_nao_conta(self, tmp_path: Path) -> None:
        caminho = self._nb(
            tmp_path,
            [{"text": ["[CB_PM_111111_ALFA]\n"]}],
            source=["[CB_PM_999999_FANTASMA]"],
        )
        texto = _textos_do_notebook(caminho)
        assert "FANTASMA" not in texto
        assert "ALFA" in texto

    def test_ipynb_corrompido_devolve_vazio(self, tmp_path: Path) -> None:
        caminho = tmp_path / "q.ipynb"
        caminho.write_text("{quebrado", encoding="utf-8")
        assert _textos_do_notebook(caminho) == ""


# -- carrega ----------------------------------------------------------------


class TestCarrega:
    def test_ordem_efetivo_primeiro_e_notebook(self, tmp_path: Path) -> None:
        (tmp_path / "efetivo.txt").write_text(
            "OPM\n\t42.BPM/I 3.CIA PM\n\nSd PM 222222-0 Alfa\n", encoding="utf-8"
        )
        (tmp_path / "MapaForca.txt").write_text(
            "[CB_PM_222222_ALFA] [CB_PM_333333_BETA]\n", encoding="utf-8"
        )
        (tmp_path / "x.ipynb").write_text(
            json.dumps(
                {
                    "cells": [
                        {
                            "source": ["x"],
                            "outputs": [{"text": ["[CB_PM_444444_GAMA]\n"]}],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "Mapa.txt").write_text(
            "inicio,final,cmd,municipio,setor,sub,local,vtr,escala,mod,re,func,re2,func2\n"
            "13/07/2024 18:30,14/07/2024 06:30,CPI-8,42.BPM,Teodoro,Area,Sub,Local,"
            "I-90002,Ord,CGP,222222,Enc,555555,Mot\n",
            encoding="utf-8",
        )
        regs = carrega(tmp_path)
        mats = [r["matricula"] for r in regs]
        # efetivo primeiro (precedência do merge), depois fontes em ordem estável
        assert mats[0] == "222222"
        assert "333333" in mats and "444444" in mats and "555555" in mats
        assert regs[0]["nome"] == "Alfa"
        assert regs[0]["unidade"] == "42.BPM/I 3.CIA PM"

    def test_diretorio_vazio(self, tmp_path: Path) -> None:
        assert carrega(tmp_path) == []


# -- importa (merge por matrícula) ------------------------------------------


class TestImporta:
    @staticmethod
    def _reg(**kw) -> dict:
        reg = {
            "nome": "",
            "posto": "",
            "matricula": "",
            "dv": "",
            "unidade": "",
            "viatura": [],
            "fonte": [],
        }
        reg.update(kw)
        return reg

    def test_cria_tabela_e_insere(self, db: Database) -> None:
        stats = importa(
            db,
            [
                self._reg(
                    nome="Alfa", posto="CB PM", matricula="111111", dv="1",
                    viatura=["I-90002"], unidade="42.BPM", fonte=["efetivo.txt"],
                )
            ],
        )
        assert stats == {"inseridos": 1, "atualizados": 0, "total": 1}
        linha = db.query("SELECT * FROM pessoas")[0]
        assert linha["nome"] == "Alfa"
        assert linha["viatura"] == "I-90002"
        assert linha["fonte"] == "efetivo.txt"
        assert linha["atualizado_em"] > 0

    def test_idempotente_sem_tocar_timestamp(self, db: Database) -> None:
        registros = [
            self._reg(nome="Alfa", posto="CB PM", matricula="111111", dv="1",
                      viatura=["I-90002"], fonte=["efetivo.txt"])
        ]
        importa(db, registros)
        db.execute("UPDATE pessoas SET atualizado_em = ?", (42.0,))
        stats = importa(db, registros)
        assert stats == {"inseridos": 0, "atualizados": 0, "total": 1}
        assert db.scalar("SELECT atualizado_em FROM pessoas") == 42.0

    def test_merge_preenche_vazio_e_soma_listas(self, db: Database) -> None:
        importa(
            db,
            [self._reg(nome="Alfa", posto="CB PM", matricula="111111",
                       fonte=["efetivo.txt"])],
        )
        stats = importa(
            db,
            [
                self._reg(nome="ALFA", posto="CB", matricula="111111", dv="7",
                          viatura=["I-90002"], fonte=["MapaForcaTudo.txt"]),
                self._reg(matricula="111111", viatura=["I-90002", "88-901"],
                          fonte=["Mapa.txt"]),
            ],
        )
        assert stats["inseridos"] == 0
        assert stats["atualizados"] == 1  # segunda rodada não muda nada
        linha = db.query("SELECT * FROM pessoas")[0]
        # nome/posto vêm da fonte de precedência; caixa alta não sobrescreve
        assert linha["nome"] == "Alfa"
        assert linha["posto"] == "CB PM"
        # campos vazios são preenchidos; viaturas e fontes somam sem repetir
        assert linha["dv"] == "7"
        assert linha["viatura"] == "I-90002, 88-901"
        assert linha["fonte"] == "efetivo.txt, MapaForcaTudo.txt, Mapa.txt"

    def test_nao_duplica_pessoas_com_mesma_matricula(self, db: Database) -> None:
        importa(db, [self._reg(nome="Alfa", matricula="111111")])
        importa(db, [self._reg(nome="ALFA", matricula="111111")])
        importa(db, [self._reg(nome="ALFA", matricula="111111")])
        assert int(db.scalar("SELECT COUNT(*) FROM pessoas")) == 1

    def test_chave_fallback_por_nome(self, db: Database) -> None:
        importa(db, [self._reg(nome="Alfa")])
        stats = importa(db, [self._reg(nome="Alfa")])
        assert stats == {"inseridos": 0, "atualizados": 0, "total": 1}

    def test_registros_vazios_ignorados(self, db: Database) -> None:
        stats = importa(db, [self._reg()])
        assert stats == {"inseridos": 0, "atualizados": 0, "total": 0}

    def test_segunda_rodada_nao_altera_nada(self, db: Database) -> None:
        registros = [
            self._reg(nome="Alfa", posto="CB PM", matricula="111111", dv="1",
                      viatura=["I-90002"], unidade="42.BPM", fonte=["efetivo.txt"]),
            self._reg(nome="Beta", posto="SD PM", matricula="222222", dv="2",
                      fonte=["efetivo.txt"]),
        ]
        importa(db, registros)
        antes = db.query("SELECT * FROM pessoas ORDER BY id")
        importa(db, registros)
        depois = db.query("SELECT * FROM pessoas ORDER BY id")
        assert antes == depois


# -- CLI --------------------------------------------------------------------


class TestMain:
    def _fontes(self, tmp_path: Path) -> Path:
        fontes = tmp_path / "Cod"
        fontes.mkdir()
        (fontes / "efetivo.txt").write_text(
            "OPM\n\t42.BPM/I 3.CIA PM\n\nSd PM 222222-0 Alfa\n", encoding="utf-8"
        )
        (fontes / "MapaForca.txt").write_text(
            "[I-90002] [CB_PM_333333_BETA]\n", encoding="utf-8"
        )
        return fontes

    def test_dir_inexistente(self) -> None:
        assert main(["--dir", "/nao/existe", "--db", ":memory:"]) == 2

    def test_sem_dsn_nem_db(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv("OD_DB_URL", raising=False)
        assert main(["--dir", str(tmp_path)]) == 2

    def test_sucesso_sqlite(self, tmp_path: Path, capsys) -> None:
        fontes = self._fontes(tmp_path)
        banco = tmp_path / "pessoas.db"
        código = main(["--db", str(banco), "--dir", str(fontes)])
        assert código == 0
        saida = capsys.readouterr().out
        assert "pessoa(s)" in saida and "2 nova(s)" in saida

        db = Database(banco)
        try:
            assert int(db.scalar("SELECT COUNT(*) FROM pessoas")) == 2
        finally:
            db.close()

    def test_reexecucao_nao_duplica(self, tmp_path: Path, capsys) -> None:
        fontes = self._fontes(tmp_path)
        banco = tmp_path / "pessoas.db"
        assert main(["--db", str(banco), "--dir", str(fontes)]) == 0
        capsys.readouterr()
        assert main(["--db", str(banco), "--dir", str(fontes)]) == 0
        assert "0 nova(s), 0 atualizada(s)" in capsys.readouterr().out

    def test_diretorio_sem_fontes_avisa(self, tmp_path: Path, capsys) -> None:
        vazio = tmp_path / "vazio"
        vazio.mkdir()
        banco = tmp_path / "p.db"
        assert main(["--db", str(banco), "--dir", str(vazio)]) == 0
        assert "nenhuma fonte reconhecida" in capsys.readouterr().out
