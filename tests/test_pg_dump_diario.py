"""
OMEGA DRAKON • TESTS
Módulo: tests/test_pg_dump_diario.py
Descrição: testes do dump diário do Postgres od (runtime/pg_dump_diario.py)
           — nome/poda cronológicos, gravação atômica .tmp→rename com
           gzip+sha256, `pg_dump` em lista (sem shell) com stderr visível,
           retry de boot, estado, aviso com cooldown de 6 h no Telegram e
           o contracto de que o dump em data/pg_dumps ENTRA no tar diário
           (é ele que viaja no offsite e nas HDs).

Baseado em:
  - runtime/pg_dump_diario.py
  - core/backup.py (EXCLUIDOS_PADRAO, IGNORAR_SUFIXOS, _ignorar — se
    data/pg_dumps um dia entrar nas exclusões, o dump deixa de viajar e
    este teste grita)
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import time
from pathlib import Path

import pytest

import runtime.pg_dump_diario as pg
from core.backup import EXCLUIDOS_PADRAO, IGNORAR_SUFIXOS, _ignorar

SQL = b"CREATE TABLE pessoa (id int);\nCOPY pessoa FROM stdin;\n\\.\n"
AGORA = time.mktime((2026, 11, 14, 2, 50, 0, 0, 0, -1))


def _gerador_ok(payload: bytes = SQL):
    def gerar(dsn: str, saida) -> None:
        saida.write(payload)

    return gerar


def _gerador_falha(mensagem: str, tentativas: list | None = None):
    def gerar(dsn: str, saida) -> None:
        if tentativas is not None:
            tentativas.append(dsn)
        raise pg.FalhaDump(mensagem)

    return gerar


# ------------------------------------------------------------------ nome/poda

def test_nome_de_ordenado_por_tempo() -> None:
    selo = time.strftime("%Y-%m-%d_%H%M", time.localtime(AGORA))
    assert pg.nome_de(AGORA) == f"od-{selo}.sql.gz"
    # minuto seguinte e dia seguinte ordenam depois (formato cronológico)
    assert pg.nome_de(AGORA) < pg.nome_de(AGORA + 60)
    assert pg.nome_de(AGORA) < pg.nome_de(AGORA + 86_400)


def test_podar_mantem_os_mais_novos(tmp_path: Path) -> None:
    for dia in range(1, 18):  # 17 dumps: od-2026-11-01 .. od-2026-11-17
        (tmp_path / f"od-2026-11-{dia:02d}_0250.sql.gz").write_bytes(b"x")
    (tmp_path / "estado.json").write_text("{}")
    (tmp_path / "nao_e_dump.sql.gz").write_bytes(b"x")  # prefixo errado

    podados = pg.podar(tmp_path, 14)

    restantes = [p.name for p in pg.listar_dumps(tmp_path)]
    assert len(restantes) == 14
    assert restantes[0] == "od-2026-11-04_0250.sql.gz"  # 01, 02 e 03 saíram
    assert len(podados) == 3
    assert (tmp_path / "estado.json").exists()
    assert (tmp_path / "nao_e_dump.sql.gz").exists()


def test_podar_nunca_zera_o_diretorio(tmp_path: Path) -> None:
    for dia in range(1, 5):
        (tmp_path / f"od-2026-11-{dia:02d}_0250.sql.gz").write_bytes(b"x")
    podados = pg.podar(tmp_path, 0)
    assert len(pg.listar_dumps(tmp_path)) == 1  # manter<1 vira 1
    assert len(podados) == 3


# ------------------------------------------------------------- executar()

def test_executar_sucesso_atomico(tmp_path: Path) -> None:
    destino = tmp_path / "od-2026-11-14_0250.sql.gz"
    info = pg.executar(dsn="postgres://sintetico/od", destino=destino,
                       gerador=_gerador_ok(SQL))
    assert info["arquivo"] == destino.name
    assert info["bytes"] == destino.stat().st_size > 0
    assert info["sha256"] == hashlib.sha256(destino.read_bytes()).hexdigest()
    assert gzip.decompress(destino.read_bytes()) == SQL
    assert not (tmp_path / (destino.name + ".tmp")).exists()


def test_executar_falha_limpa_o_tmp(tmp_path: Path) -> None:
    destino = tmp_path / "od-2026-11-14_0250.sql.gz"
    with pytest.raises(pg.FalhaDump, match="banco fora"):
        pg.executar(dsn="postgres://sintetico/od", destino=destino,
                    gerador=_gerador_falha("banco fora do ar"))
    assert not destino.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_gerador_padrao_lista_sem_shell_e_stderr_visivel() -> None:
    visto: dict = {}

    def popen(args, stdout=None, stderr=None):
        visto["args"] = args
        stderr.write(b"pg_dump: error: connection refused\n")

        class Proc:
            stdout = io.BytesIO(b"")

            def wait(self):
                return 1

        return Proc()

    gerar = pg._gerador_padrao("/usr/bin/pg_dump", popen=popen)
    with pytest.raises(pg.FalhaDump) as captura:
        gerar("postgres://sintetico/od", io.BytesIO())

    # lista de argumentos, nunca uma string de shell
    assert visto["args"] == ["/usr/bin/pg_dump", "postgres://sintetico/od"]
    assert "pg_dump saiu com 1" in str(captura.value)
    assert "connection refused" in str(captura.value)


def test_gerador_padrao_escreve_o_stdout() -> None:
    def popen(args, stdout=None, stderr=None):
        class Proc:
            stdout = io.BytesIO(SQL)

            def wait(self):
                return 0

        return Proc()

    saida = io.BytesIO()
    pg._gerador_padrao("/usr/bin/pg_dump", popen=popen)(
        "postgres://sintetico/od", saida
    )
    assert saida.getvalue() == SQL


# ------------------------------------------------------------------- rodar()

def test_rodar_sucesso_grava_estado(tmp_path: Path) -> None:
    enviados: list[str] = []
    codigo = pg.rodar({"OD_DB_URL": "postgres://sintetico/od"}, dir=tmp_path,
                      agora=AGORA, gerador=_gerador_ok(),
                      enviar=enviados.append)
    assert codigo == 0
    assert enviados == []  # sucesso não incomoda o dono

    dumps = pg.listar_dumps(tmp_path)
    assert len(dumps) == 1
    estado = json.loads((tmp_path / "estado.json").read_text())
    assert estado["rodadas"] == 1
    assert estado["falhas"] == 0
    assert estado["ultimo_arquivo"] == dumps[0].name
    assert estado["ultimo_bytes"] == dumps[0].stat().st_size
    assert estado["ultimo_sha256"] == hashlib.sha256(dumps[0].read_bytes()).hexdigest()
    assert estado["ultimo_sucesso"] == AGORA
    assert estado["ultimo_erro"] == ""


def test_rodar_falha_avisa_uma_vez_e_retorna_1(tmp_path: Path) -> None:
    tentativas: list = []
    enviados: list[str] = []
    codigo = pg.rodar({"OD_DB_URL": "postgres://sintetico/od"}, dir=tmp_path,
                      agora=AGORA,
                      gerador=_gerador_falha("banco fora do ar", tentativas),
                      enviar=enviados.append, espera=lambda s: None)
    assert codigo == 1
    assert len(tentativas) == 2  # retry de boot antes de desistir
    assert len(enviados) == 1
    assert "PG DUMP FALHOU" in enviados[0]
    assert "banco fora do ar" in enviados[0]

    estado = json.loads((tmp_path / "estado.json").read_text())
    assert estado["falhas"] == 1
    assert estado["rodadas"] == 1
    assert "banco fora do ar" in estado["ultimo_erro"]
    assert estado["ultimo_aviso_em"] == AGORA


def test_aviso_com_cooldown_de_6h() -> None:
    estado = pg.estado_inicial()
    enviados: list[str] = []
    assert pg.avisar(estado, "1", agora=1000.0, enviar=enviados.append) is True
    # 1 h depois: dentro do cooldown, silêncio
    assert pg.avisar(estado, "2", agora=1000.0 + 3600, enviar=enviados.append) is False
    # exatamente 6 h: ainda não (a regra é "1 a cada 6 h")
    assert pg.avisar(estado, "3", agora=1000.0 + 6 * 3600,
                     enviar=enviados.append) is False
    # passou do cooldown: avisa de novo
    assert pg.avisar(estado, "4", agora=1000.0 + 6 * 3600 + 1,
                     enviar=enviados.append) is True
    assert enviados == ["1", "4"]
    assert estado["ultimo_aviso_em"] == 1000.0 + 6 * 3600 + 1


def test_rodar_sem_dsn_erro_honesta(tmp_path: Path) -> None:
    enviados: list[str] = []
    codigo = pg.rodar({}, dir=tmp_path, agora=AGORA, enviar=enviados.append,
                      espera=lambda s: None)
    assert codigo == 1
    assert len(enviados) == 1
    assert "OD_DB_URL" in enviados[0]  # a mensagem diz o que falta

    estado = json.loads((tmp_path / "estado.json").read_text())
    assert estado["falhas"] == 1
    assert "OD_DB_URL" in estado["ultimo_erro"]
    assert pg.listar_dumps(tmp_path) == []  # nunca inventa dump


def test_retry_na_segunda_tentativa(tmp_path: Path) -> None:
    """Corrida de boot: primeira falha, segunda dá conta — sem aviso."""
    chamadas = {"n": 0}

    def gerar(dsn: str, saida) -> None:
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise pg.FalhaDump("corrida de boot")
        saida.write(SQL)

    enviados: list[str] = []
    esperas: list[float] = []
    codigo = pg.rodar({"OD_DB_URL": "postgres://sintetico/od"}, dir=tmp_path,
                      agora=AGORA, gerador=gerar, enviar=enviados.append,
                      espera=esperas.append)
    assert codigo == 0
    assert chamadas["n"] == 2
    assert esperas == [pg.ESPERA_PADRAO_S]
    assert enviados == []  # falhou 1×, recuperou: dono não é incomodado
    estado = json.loads((tmp_path / "estado.json").read_text())
    assert estado["falhas"] == 0
    assert estado["rodadas"] == 1


# ------------------------------------------------- contracto com o backup

def test_nao_excluido_do_tar_do_backup() -> None:
    """O dump precisa ESTAR no tar diário — é ele que viaja no offsite
    (Telegram) e no snapshot das HDs. Se data/pg_dumps entrar nas
    exclusões de core/backup.py, este teste falha antes do silêncio."""
    caminho = "data/pg_dumps/od-2026-11-14_0250.sql.gz"
    assert "data/pg_dumps" not in EXCLUIDOS_PADRAO
    assert not any(caminho.lower().endswith(s) for s in IGNORAR_SUFIXOS)
    assert _ignorar(caminho) is False
