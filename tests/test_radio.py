"""
OMEGA DRAKON • TESTS
Módulo: tests/test_radio.py
Descrição: Testes das frases da rádio Nicky (integrations/radio.py +
           runtime/setup_frases_radio.py) — integração do legado Nicky
           Locutor (27/10): família de frases, idempotência da carga e
           comportamento honesto do webhook (banco fora = "" sem derrubar
           a vinheta).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - analise/Nicky Locutor/nicky-locutor/setup_db.py (frases originais)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from integrations.radio import (
    ASSINATURAS,
    FRASES_PASSADO,
    FRASES_PROXIMA,
    INTROS_CURIOSIDADE,
    TABELAS,
    frase_aleatoria,
    frase_formatada,
    garantir_frases,
)
from runtime.setup_frases_radio import main as setup_main
from storage import Database


@pytest.fixture()
def db():
    database = Database()
    yield database
    database.close()


class TestGarantirFrases:
    def test_cria_as_quatro_tabelas(self, db: Database) -> None:
        populadas = garantir_frases(db)
        assert set(populadas) == set(TABELAS)
        assert set(db.tables()) >= set(TABELAS)

    def test_contagens_batem_com_o_legado(self, db: Database) -> None:
        populadas = garantir_frases(db)
        assert populadas["frases_passado"] == len(FRASES_PASSADO) == 40
        assert populadas["frases_proxima"] == len(FRASES_PROXIMA) == 10
        assert populadas["intro_curiosidade"] == len(INTROS_CURIOSIDADE) == 8
        assert populadas["assinaturas"] == len(ASSINATURAS) == 6

    def test_idempotente_nao_duplica(self, db: Database) -> None:
        garantir_frases(db)
        segunda = garantir_frases(db)
        assert all(v == len(FRASES_PASSADO) for v in [segunda["frases_passado"]])
        assert segunda["frases_proxima"] == 10
        assert db.scalar("SELECT COUNT(*) FROM frases_passado") == 40

    def test_preserva_frases_existentes(self, db: Database) -> None:
        # frases já no ar (ex.: dono adicionou uma à mão) nunca são
        # apagadas — o DELETE em massa do legado faria exatamente isso
        garantir_frases(db)
        db.execute(
            "INSERT INTO assinaturas (texto) VALUES (?)",
            ("Frase nova do dono.",),
        )
        garantir_frases(db)
        assert db.scalar("SELECT COUNT(*) FROM assinaturas") == 7

    def test_placeholders_das_frases_de_musica(self, db: Database) -> None:
        garantir_frases(db)
        linhas = db.query("SELECT texto FROM frases_passado")
        assert all("{a}" in r["texto"] and "{t}" in r["texto"] for r in linhas)
        linhas = db.query("SELECT texto FROM frases_proxima")
        assert all("{a_n}" in r["texto"] and "{t_n}" in r["texto"] for r in linhas)
        intros = db.query("SELECT texto FROM intro_curiosidade")
        assert not any("{" in r["texto"] for r in intros)


class TestFrasesWebhook:
    def test_frase_aleatoria_devolve_texto(self, db: Database) -> None:
        garantir_frases(db)
        frase = frase_aleatoria(db, "assinaturas")
        assert frase in ASSINATURAS

    def test_frase_tabela_desconhecida(self, db: Database) -> None:
        garantir_frases(db)
        assert frase_aleatoria(db, "tabela_inexistente") == ""

    def test_frase_banco_sem_tabela_nao_explode(self) -> None:
        vazio = Database()
        try:
            assert frase_aleatoria(vazio, "assinaturas") == ""
        finally:
            vazio.close()

    def test_formatada_preenche_placeholders(self, db: Database) -> None:
        garantir_frases(db)
        frase = frase_formatada(
            db, "frases_passado", a="Skank", t="Resposta"
        )
        assert "Skank" in frase and "Resposta" in frase
        assert "{a}" not in frase and "{t}" not in frase

    def test_formatada_placeholder_ausente_vira_vazio(self, db: Database) -> None:
        garantir_frases(db)
        # música sem artista (o legado estourava KeyError aqui)
        frase = frase_formatada(db, "frases_passado", t="Resposta")
        assert "{a}" not in frase and "{t}" not in frase

    def test_formatada_intro_sem_placeholder(self, db: Database) -> None:
        garantir_frases(db)
        assert frase_formatada(db, "intro_curiosidade") in INTROS_CURIOSIDADE


class TestSetupCLI:
    def test_cli_sqlite(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        caminho = str(tmp_path / "od.db")
        assert setup_main(["--db", caminho]) == 0
        saida = capsys.readouterr().out
        assert "frases_passado: 40" in saida
        # re-rodar mantém as 40 (idempotente pela CLI também)
        assert setup_main(["--db", caminho]) == 0
        assert capsys.readouterr().out.count("frases_passado: 40") == 1

    def test_cli_sem_fonte_falla_honesto(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.delenv("OD_DB_URL", raising=False)
        assert setup_main([]) == 2
        assert "OD_DB_URL ausente" in capsys.readouterr().out
