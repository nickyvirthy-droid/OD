"""Runner semanal da verificação de restauração do Postgres.

Contrato (ordem do dono, 19/11): sucesso é silêncio; falha avisa no Telegram
com a saída do verificador e não perde o estado.
"""

from __future__ import annotations

import json
from pathlib import Path

from runtime import verificar_restauracao_pg as v


def test_sucesso_nao_avisa_e_registra_estado(tmp_path: Path) -> None:
    enviados: list[str] = []
    estado_path = tmp_path / "estado.json"
    codigo = v.rodar(
        estado_path=estado_path,
        verificador=lambda: (0, "RESTORE OK em 0,17 s · 14 tabelas"),
        enviar=enviados.append,
        agora=1000.0,
    )
    assert codigo == 0
    assert enviados == []                      # silêncio no sucesso
    estado = json.loads(estado_path.read_text(encoding="utf-8"))
    assert estado["ok"] is True
    assert estado["ultimo_codigo"] == 0
    assert estado["ultimo_sucesso_em"] == 1000.0
    assert "falhas" not in estado


def test_falha_avisa_com_a_saida_do_verificador(tmp_path: Path) -> None:
    enviados: list[str] = []
    estado_path = tmp_path / "estado.json"
    codigo = v.rodar(
        estado_path=estado_path,
        verificador=lambda: (1, "FALHA: restore rc=3\nFIDELIDADE llm_cache"),
        enviar=enviados.append,
        agora=2000.0,
    )
    assert codigo == 1
    assert len(enviados) == 1
    aviso = enviados[0]
    assert "NÃO restaura" in aviso
    assert "código 1" in aviso
    assert "FALHA: restore rc=3" in aviso
    estado = json.loads(estado_path.read_text(encoding="utf-8"))
    assert estado["ok"] is False
    assert estado["falhas"] == 1
    assert estado["ultimo_aviso_em"] == 2000.0


def test_excecao_do_verificador_vira_falha_com_aviso(tmp_path: Path) -> None:
    enviados: list[str] = []

    def explode() -> tuple[int, str]:
        raise TimeoutError("initdb travou")

    codigo = v.rodar(
        estado_path=tmp_path / "estado.json",
        verificador=explode,
        enviar=enviados.append,
    )
    assert codigo == 1
    assert len(enviados) == 1
    assert "TimeoutError" in enviados[0]


def test_sem_canal_registra_falha_sem_levantar(tmp_path: Path) -> None:
    estado_path = tmp_path / "estado.json"
    assert v.rodar(
        estado_path=estado_path,
        verificador=lambda: (2, "erro"),
        enviar=None,
    ) == 2
    estado = json.loads(estado_path.read_text(encoding="utf-8"))
    assert estado["ok"] is False


def test_aviso_que_falha_nao_esconde_a_falha_do_restore(tmp_path: Path) -> None:
    def telegram_fora(_texto: str) -> None:
        raise RuntimeError("rede fora")

    estado_path = tmp_path / "estado.json"
    codigo = v.rodar(
        estado_path=estado_path,
        verificador=lambda: (1, "restore quebrado"),
        enviar=telegram_fora,
    )
    assert codigo == 1
    estado = json.loads(estado_path.read_text(encoding="utf-8"))
    assert estado["ok"] is False
    assert "erro_aviso" in estado
    assert "rede fora" in estado["erro_aviso"]


def test_mensagem_falha_mostra_o_codigo_e_o_trecho() -> None:
    texto = v.mensagem_falha(7, "linha final do erro")
    assert "código 7" in texto
    assert "linha final do erro" in texto
