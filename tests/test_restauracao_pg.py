"""Verificador de restauração do Postgres — teste da contagem do dump.

A contagem por bloco COPY é a régua de fidelidade: se ela errar, o
verificador aprova um restore incompleto (ou reprova um bom). Por isso é
testada com um dump pequeno e determinístico, sem precisar de PostgreSQL.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from tools.testar_restauracao_pg import contar_linhas_do_dump


def _dump(tmp_path: Path, corpo: str) -> Path:
    caminho = tmp_path / "od-teste.sql.gz"
    with gzip.open(caminho, "wt", encoding="utf-8") as fh:
        fh.write(corpo)
    return caminho


def test_conta_linhas_de_cada_bloco_copy(tmp_path: Path) -> None:
    dump = _dump(tmp_path, "\n".join([
        "--",
        "-- PostgreSQL database dump",
        "--",
        "COPY public.llm_cache (id, prompt) FROM stdin;",
        "1\tbom dia",
        "2\tboa noite",
        "\\.",
        "COPY public.conversation_messages (id) FROM stdin;",
        "10",
        "\\.",
    ]))
    assert contar_linhas_do_dump(dump) == {
        "llm_cache": 2,
        "conversation_messages": 1,
    }


def test_tabela_vazia_conta_zero_e_nao_some(tmp_path: Path) -> None:
    dump = _dump(tmp_path, "\n".join([
        "COPY public.vazia (id) FROM stdin;",
        "\\.",
        "COPY public.cheia (id) FROM stdin;",
        "1",
        "\\.",
    ]))
    assert contar_linhas_do_dump(dump) == {"vazia": 0, "cheia": 1}


def test_linha_fora_de_bloco_copy_nao_conta(tmp_path: Path) -> None:
    dump = _dump(tmp_path, "\n".join([
        "-- COPY public.comentario (id) FROM stdin;",
        "SELECT 1;",
        "COPY public.real (id) FROM stdin;",
        "7",
        "\\.",
        "ALTER TABLE public.real OWNER TO od;",
    ]))
    assert contar_linhas_do_dump(dump) == {"real": 1}


@pytest.mark.parametrize("nome", ["od-2026-11-19_0250.sql.gz"])
def test_dump_real_conta_todas_as_tabelas(nome: str) -> None:
    """O dump real (se presente) tem as 14 tabelas do banco `od`."""
    caminho = Path("data/pg_dumps") / nome
    if not caminho.is_file():
        pytest.skip("dump real ausente nesta máquina")
    contagem = contar_linhas_do_dump(caminho)
    assert len(contagem) == 14
    assert contagem["llm_cache"] > 0
