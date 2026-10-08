"""
OMEGA DRAKON • TESTS
Módulo: tests/test_llm_cache_saneamento.py
Descrição: testes do saneamento de llm_cache (runtime/llm_cache_saneamento.py)
           — coluna `profile` reatribuída pela CHAVE (quem perguntou) e poda de
           respostas devaneio, com snapshot de rollback e dry-run intacto.

Baseado em:
  - runtime/llm_cache_saneamento.py
  - memory/cache.py (make_key = normalização + perfil da instância + params)
  - memory/adapters.py (LLM_CACHE_SCHEMA)
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import runtime.llm_cache_saneamento as sane
from memory.adapters import LLM_CACHE_SCHEMA
from memory.cache import LLMCache, normalize_prompt
from storage.database import Database

PERFIS = ["guardian", "nyx", "nexus"]


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "cache.db")
    database.create_table("llm_cache", LLM_CACHE_SCHEMA)
    return database


def _inserir(db: Database, prompt: str, resposta: str, *, chave: str,
             perfil_coluna: str) -> None:
    """Grava uma linha com a CHAVE que o sistema real teria gravado."""
    db.execute(
        "INSERT INTO llm_cache (key, prompt, response, profile, created_ts, "
        "last_used_ts) VALUES (?, ?, ?, ?, ?, ?)",
        (chave, normalize_prompt(prompt), resposta, perfil_coluna, 1000.0, 1000.0),
    )


def _chave(prompt: str, perfil_instancia: str, perfil_perguntou: str) -> str:
    return LLMCache(cache_dir="data/llm_cache", profile=perfil_instancia).make_key(
        prompt, profile=perfil_perguntou
    )


# ---------------------------------------------------------------------------
# 1) coluna `profile`
# ---------------------------------------------------------------------------

class TestPerfil:
    def test_plan_descobre_quem_perguntou_pela_chave(self, db: Database) -> None:
        """Coluna 'guardian' (bug) + chave feita pela nyx → correção 'nyx'."""
        chave = _chave("oi", "guardian", "nyx")
        _inserir(db, "oi", "olá", chave=chave, perfil_coluna="guardian")
        plano = sane.plan_perfis(db, PERFIS)
        assert plano["correcoes"] == [
            {"key": chave, "prompt": "oi",
             "profile": "guardian", "profile_correto": "nyx"}
        ]
        assert plano["nao_reconhecidas"] == [] and plano["ambiguas"] == []

    def test_linha_ja_correta_nao_entra_no_plano(self, db: Database) -> None:
        chave = _chave("tudo bem", "guardian", "guardian")
        _inserir(db, "tudo bem", "bem", chave=chave, perfil_coluna="guardian")
        plano = sane.plan_perfis(db, PERFIS)
        assert plano["correcoes"] == [] and plano["ja_corretas"] == 1

    def test_chave_fora_do_modelo_fica_intacta_e_e_reportada(
        self, db: Database
    ) -> None:
        _inserir(db, "?", "…", chave="chave_de_outro_tempo",
                 perfil_coluna="guardian")
        plano = sane.plan_perfis(db, PERFIS)
        assert plano["correcoes"] == []
        assert [r["key"] for r in plano["nao_reconhecidas"]] == ["chave_de_outro_tempo"]
        assert db.query("SELECT profile FROM llm_cache")[0]["profile"] == "guardian"

    def test_apply_corrige_e_grava_snapshot_de_rollback(self, db: Database,
                                                        tmp_path: Path) -> None:
        boa = _chave("oi", "guardian", "nyx")
        _inserir(db, "oi", "olá", chave=boa, perfil_coluna="guardian")
        _inserir(db, "?", "…", chave="fora_do_modelo", perfil_coluna="guardian")
        rel = sane.apply_perfis(db, PERFIS, backup_dir=tmp_path)
        assert rel["corrigidas"] == 1
        linhas = {r["key"]: r["profile"] for r in db.query("SELECT key, profile FROM llm_cache")}
        assert linhas[boa] == "nyx"
        assert linhas["fora_do_modelo"] == "guardian"  # não reconhecida, intocada
        snapshot = Path(rel["snapshot"])
        dados = json.loads(snapshot.read_text(encoding="utf-8"))
        assert dados["correcoes"][0]["profile_correto"] == "nyx"
        rollback = " ".join(dados["rollback"])
        assert rollback.startswith("UPDATE llm_cache SET profile = 'guardian'")
        assert boa in rollback

    def test_apply_sem_correcao_nao_cria_snapshot(self, db: Database,
                                                  tmp_path: Path) -> None:
        chave = _chave("oi", "guardian", "guardian")
        _inserir(db, "oi", "olá", chave=chave, perfil_coluna="guardian")
        rel = sane.apply_perfis(db, PERFIS, backup_dir=tmp_path / "bak")
        assert rel["corrigidas"] == 0 and rel["snapshot"] is None
        assert not (tmp_path / "bak").exists()


# ---------------------------------------------------------------------------
# 2) poda de devaneios
# ---------------------------------------------------------------------------

class TestPoda:
    def test_plan_poda_seleciona_so_os_devaneios(self, db: Database) -> None:
        _inserir(db, "qual a fase da lua", "Fonte: Open-Meteo",
                 chave="k1", perfil_coluna="guardian")
        _inserir(db, "O que tem pra hoje", "CPU 31.7 °C na porta 5000",
                 chave="k2", perfil_coluna="guardian")
        _inserir(db, "qual a capital do Brasil", "Brasília.",
                 chave="k3", perfil_coluna="guardian")
        plano = sane.plan_poda(db)
        assert [r["key"] for r in plano["podar"]] == ["k1", "k2"]
        assert plano["total"] == 3

    def test_apply_poda_remove_grava_snapshot_e_e_idempotente(
        self, db: Database, tmp_path: Path
    ) -> None:
        _inserir(db, "qual a velocidade da internet", "10 Mbps. Estado verificado.",
                 chave="k1", perfil_coluna="guardian")
        _inserir(db, "qual a capital do Brasil", "Brasília.",
                 chave="k2", perfil_coluna="guardian")
        rel = sane.apply_poda(db, backup_dir=tmp_path)
        assert rel["podadas"] == 1
        assert [r["key"] for r in db.query("SELECT key FROM llm_cache")] == ["k2"]
        dados = json.loads(Path(rel["snapshot"]).read_text(encoding="utf-8"))
        linha = dados["linhas"][0]
        # snapshot com TODAS as colunas (last_used_ts é NOT NULL sem default)
        assert {"key", "prompt", "response", "profile", "llm_used",
                "tokens_used", "use_count", "duplicates", "created_ts",
                "last_used_ts", "avg_response_time_ms"} <= set(linha)
        assert dados["rollback"][0].startswith("INSERT INTO llm_cache (")
        assert "10 Mbps" in dados["rollback"][0]
        # segunda rodada: nada a podar, nenhum snapshot novo
        rel2 = sane.apply_poda(db, backup_dir=tmp_path)
        assert rel2["podadas"] == 0 and rel2["snapshot"] is None

    def test_rollback_do_snapshot_devolve_a_linha(self, db: Database,
                                                  tmp_path: Path) -> None:
        _inserir(db, "qual a fase da lua", "…", chave="k1",
                 perfil_coluna="guardian")
        rel = sane.apply_poda(db, backup_dir=tmp_path)
        assert db.query("SELECT key FROM llm_cache") == []
        for sql in json.loads(Path(rel["snapshot"]).read_text(encoding="utf-8"))["rollback"]:
            db.execute(sql)
        linhas = db.query("SELECT key, prompt, response, last_used_ts FROM llm_cache")
        assert linhas == [{"key": "k1", "prompt": "qual a fase da lua",
                           "response": "…", "last_used_ts": 1000.0}]
