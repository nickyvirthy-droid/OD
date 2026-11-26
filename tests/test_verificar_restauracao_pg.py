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


# ---------------------------------------------------------------------------
# Guarda de off-site na mesma rodada (item 4 da fila, 26/11)
#
# O runner semanal passa a rodar o `tools/checar_offsite_pg.py` (sha256 do dump
# no canal e nos snapshots das HDs). Só DIVERGÊNCIA alarma: HD desplugada ou
# snapshot pendente são verdade, não defeito.
# ---------------------------------------------------------------------------


def _resumo_checador(canal: str = "ok", hd: str = "ok", *, provado: bool = True,
                     divergente: bool = False) -> str:
    return json.dumps({
        "ok": provado, "divergente": divergente, "dump": "od-2026-11-26_0300.sql.gz",
        "canal": {"status": canal, "tar": "od-2026-11-26_0300.tar.gz",
                  "motivo": "sha256 abc123 idêntico"},
        "hds": [{"alvo": "/home/alex/dados/od_snapshots", "status": hd,
                 "motivo": "sha256 abc123 idêntico"}],
    })


def _rodar_checador(monkeypatch, stdout: str, *, returncode: int = 0,
                    stderr: str = "") -> None:
    import subprocess

    def fake(cmd, **kwargs):
        fake.cmd = list(cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

    monkeypatch.setattr(v.subprocess, "run", fake)


def test_offsite_divergente_no_canal_vira_problema(monkeypatch) -> None:
    _rodar_checador(monkeypatch, _resumo_checador(
        canal="divergente", divergente=True, provado=False
    ))

    r = v.verificar_offsite()

    assert r["ok"] is False and r["divergente"] is True
    assert any(p.startswith("canal:") for p in r["problemas"])


def test_offsite_em_dia_fica_em_silencio(tmp_path: Path) -> None:
    r = v.verificar_offsite() if False else {
        "ok": True, "divergente": False, "provado": True, "problemas": []}
    enviados: list[str] = []
    estado_path = tmp_path / "restore.json"
    codigo = v.rodar(
        estado_path=estado_path,
        verificador=lambda: (0, "RESTORE OK"),
        enviar=enviados.append,
        agora=1000.0,
        offsite=lambda: r,
    )
    assert codigo == 0 and enviados == []          # silêncio no sucesso
    estado = json.loads(estado_path.read_text(encoding="utf-8"))
    assert estado["offsite_ok"] is True
    assert estado["offsite"]["provado"] is True


def test_hd_fora_do_ar_nao_alarma(monkeypatch) -> None:
    """`aguardando`/`ausente` = verdade (HD desplugada), não defeito."""
    _rodar_checador(monkeypatch, _resumo_checador(
        canal="aguardando", hd="ausente", provado=False, divergente=False
    ))

    r = v.verificar_offsite()

    assert r["ok"] is True and r["problemas"] == []
    assert r["provado"] is False          # mas não finge cópia provada


def test_divergencia_avisa_e_registra_mesmo_com_restore_ok(
    monkeypatch, tmp_path: Path
) -> None:
    _rodar_checador(monkeypatch, _resumo_checador(
        canal="divergente", divergente=True, provado=False
    ))
    enviados: list[str] = []
    estado_path = tmp_path / "restore.json"

    codigo = v.rodar(
        estado_path=estado_path,
        verificador=lambda: (0, "RESTORE OK em 0,17 s"),
        enviar=enviados.append,
        agora=2000.0,
        offsite=v.verificar_offsite,   # a guarda de produção, com o fake acima
    )

    assert codigo == 0                     # restore continua ok
    assert len(enviados) == 1
    assert "Off-site DIVERGENTE" in enviados[0]
    assert "sha256" in enviados[0]
    estado = json.loads(estado_path.read_text(encoding="utf-8"))
    assert estado["ok"] is True and estado["offsite_ok"] is False
    assert estado["offsite_aviso_em"] == 2000.0


def test_checador_sem_json_e_divergencia(monkeypatch) -> None:
    _rodar_checador(monkeypatch, "OFFSITE OK", returncode=1, stderr="boom")

    r = v.verificar_offsite()

    assert r["ok"] is False and r["divergente"] is True
    assert "não devolveu JSON" in r["problemas"][0]
    assert "boom" in r["problemas"][0]


def test_checador_que_nem_roda_e_divergencia(monkeypatch) -> None:
    def explode(cmd, **kwargs):
        raise TimeoutError("disco travou")

    monkeypatch.setattr(v.subprocess, "run", explode)

    r = v.verificar_offsite()

    assert r["ok"] is False
    assert "checador não rodou" in r["problemas"][0]


def test_producao_passa_a_guarda_no_main(monkeypatch) -> None:
    """`main()` liga a guarda; sem ela a produção não auditava nada."""
    chamadas: dict = {}

    def fake_rodar(**kwargs):
        chamadas.update(kwargs)
        return 0

    monkeypatch.setattr(v, "rodar", fake_rodar)
    monkeypatch.setattr(v, "montar_enviar", lambda: None)
    v.main(["--dry-run"])

    assert chamadas["offsite"] is v.verificar_offsite
