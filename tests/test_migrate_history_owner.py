"""
OMEGA DRAKON • TESTS
Módulo: tests/test_migrate_history_owner.py
Descrição: testes do script one-off de migração de baldes de histórico
           (runtime/migrate_history_owner.py) — plan/apply, preservação do
           conteúdo e dos perfis, idempotência e o snapshot de rollback.

Baseado em:
  - runtime/migrate_history_owner.py
  - memory/history.py (tabela conversation_messages)
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.migrate_history_owner import apply, plan
from storage.database import Database


def _db(tmp_path: Path) -> Database:
    return Database(tmp_path / "hist.db")


def _semear(
    db: Database, user_id: str, profile: str, textos: list[str], *, base: float = 1000.0
) -> None:
    """Semeia mensagens com ts crescente a partir de `base` (ordem previsível)."""
    for i, texto in enumerate(textos):
        db.execute(
            "INSERT INTO conversation_messages "
            "(user_id, profile, role, content, ts, llm_used) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, profile, "user", texto, base + i, ""),
        )


@pytest.fixture()
def db(tmp_path: Path):
    database = _db(tmp_path)
    database.create_table(
        "conversation_messages",
        {
            "id": "INTEGER PRIMARY KEY",
            "user_id": "TEXT NOT NULL",
            "profile": "TEXT NOT NULL",
            "role": "TEXT NOT NULL",
            "content": "TEXT NOT NULL",
            "ts": "REAL NOT NULL",
            "llm_used": "TEXT DEFAULT ''",
        },
    )
    yield database
    database.close()


class TestPlan:
    def test_plan_lista_baldes_sem_escrever(self, db) -> None:
        _semear(db, "web", "guardian", ["a", "b"])
        _semear(db, "web", "nyx", ["c"])
        _semear(db, "alex", "guardian", ["minha"])
        antes = plan(db, ["web", "ws_user"], "alex")
        assert antes["para"] == "alex"
        assert antes["total_a_mover"] == 3
        assert [(b["user_id"], b["profile"], int(b["mensagens"])) for b in antes["baldes"]] == [
            ("web", "guardian", 2),
            ("web", "nyx", 1),
        ]
        # Nada foi tocado
        assert db.scalar("SELECT COUNT(*) FROM conversation_messages WHERE user_id = 'web'") == 3

    def test_plan_com_origem_vazia(self, db) -> None:
        antes = plan(db, ["web"], "alex")
        assert antes["baldes"] == [] and antes["total_a_mover"] == 0

    def test_origem_igual_ao_destino_e_ignorada(self, db) -> None:
        _semear(db, "alex", "guardian", ["x"])
        antes = plan(db, ["alex", "web"], "alex")
        assert "alex" not in antes["de"]


class TestApply:
    def test_move_preservando_conteudo_perfil_e_ordem(self, db, tmp_path: Path) -> None:
        # Faixas de ts distintas: a conversa final é lida em ordem cronológica
        _semear(db, "web", "guardian", ["antiga-1", "antiga-2"], base=1000.0)
        _semear(db, "web", "nyx", ["nyx-1"], base=2000.0)
        _semear(db, "alex", "guardian", ["atual"], base=3000.0)
        relatorio = apply(db, ["web"], "alex", backup_dir=tmp_path / "bk")

        assert relatorio["movidas"] == 3
        assert relatorio["destino"][0]["user_id"] == "alex"
        assert int(relatorio["destino"][0]["mensagens"]) == 4

        conteudos = [
            r["content"]
            for r in db.query(
                "SELECT content FROM conversation_messages WHERE user_id = 'alex' "
                "ORDER BY ts"
            )
        ]
        assert conteudos == ["antiga-1", "antiga-2", "nyx-1", "atual"]
        # O perfil de cada conversa não foi misturado
        assert db.scalar(
            "SELECT COUNT(*) FROM conversation_messages WHERE user_id = 'alex' AND profile = 'nyx'"
        ) == 1
        assert db.scalar("SELECT COUNT(*) FROM conversation_messages WHERE user_id = 'web'") == 0

    def test_total_de_mensagens_nao_muda(self, db, tmp_path: Path) -> None:
        _semear(db, "web", "guardian", ["a", "b"])
        total_antes = db.scalar("SELECT COUNT(*) FROM conversation_messages")
        apply(db, ["web"], "alex", backup_dir=tmp_path / "bk")
        assert db.scalar("SELECT COUNT(*) FROM conversation_messages") == total_antes

    def test_idempotente(self, db, tmp_path: Path) -> None:
        _semear(db, "web", "guardian", ["a"])
        assert apply(db, ["web"], "alex", backup_dir=tmp_path / "bk")["movidas"] == 1
        segunda = apply(db, ["web"], "alex", backup_dir=tmp_path / "bk")
        assert segunda["movidas"] == 0 and segunda["nada_a_fazer"] is True

    def test_snapshot_permite_rollback(self, db, tmp_path: Path) -> None:
        _semear(db, "web", "guardian", ["a", "b"], base=1000.0)
        relatorio = apply(db, ["web"], "alex", backup_dir=tmp_path / "bk")
        snapshot = Path(relatorio["snapshot"])
        dados = json.loads(snapshot.read_text(encoding="utf-8"))
        assert dados["de"] == ["web"] and dados["para"] == "alex"
        assert dados["baldes"][0]["mensagens"] == 2
        assert "UPDATE conversation_messages SET user_id = 'web'" in dados["rollback"][0]

        # O rollback do snapshot devolve o balde de origem
        for sql in dados["rollback"]:
            db.execute(sql)
        assert db.scalar("SELECT COUNT(*) FROM conversation_messages WHERE user_id = 'web'") == 2

    def test_multiplas_origens(self, db, tmp_path: Path) -> None:
        _semear(db, "web", "guardian", ["w"])
        _semear(db, "ws_user", "guardian", ["s1", "s2"])
        relatorio = apply(db, ["web", "ws_user"], "alex", backup_dir=tmp_path / "bk")
        assert relatorio["movidas"] == 3
        assert db.scalar(
            "SELECT COUNT(*) FROM conversation_messages WHERE user_id IN ('web', 'ws_user')"
        ) == 0
