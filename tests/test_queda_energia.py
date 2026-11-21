"""
OMEGA DRAKON • TESTS
Módulo: tests/test_queda_energia.py
Descrição: Testes de core/queda_energia.py — reconhecer o retorno de uma
           queda de energia pelo journal (desligamento sem "Journal
           stopped"), respeitando o limite de boot recente e degradando para
           silêncio quando o journal não pode ser lido.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import json
from typing import Optional

import pytest

from core.queda_energia import (
    LIMITE_ALERTA_S,
    detectar_queda,
    formatar_duracao,
    resumo_queda,
    uptime_s,
)


def _boots(primeiro: int, ultimo: int, segundo_primeiro: int = 0) -> str:
    """Saída de `journalctl --list-boots -o json` com dois boots.

    Os argumentos são segundos de epoch; o journal devolve microssegundos.
    """
    us = 1_000_000
    inicio_atual = (segundo_primeiro or ultimo) * us
    return json.dumps([
        {"index": -1, "boot_id": "aaa", "first_entry": primeiro * us,
         "last_entry": ultimo * us},
        {"index": 0, "boot_id": "bbb", "first_entry": inicio_atual,
         "last_entry": inicio_atual},
    ])


def _executar(ultima_mensagem: str, boots: Optional[str] = None):
    """Fake do journalctl: responde list-boots e a última linha do -1."""
    chamadas: list[list[str]] = []

    def fake(args: list[str]) -> Optional[str]:
        chamadas.append(args)
        if "--list-boots" in args:
            return boots if boots is not None else _boots(1_000_000_000, 1_000_060_000)
        if "-b" in args and "-1" in args:
            return json.dumps({"MESSAGE": ultima_mensagem})
        return None

    fake.chamadas = chamadas  # type: ignore[attr-defined]
    return fake


def test_queda_quando_anterior_nao_registrou_desligamento() -> None:
    # Boot anterior terminou abruptamente há 1 h; atual começou há 5 min.
    fim = 1_700_000_000
    inicio = fim + 3_600
    fake = _executar("systemd: Stopping User Manager...", _boots(1, fim, inicio))
    info = detectar_queda(fake, uptime_fn=lambda: 300.0)

    assert info is not None
    assert info["fora_s"] == 3_600
    assert info["desligado_em"] and info["voltou_em"]


def test_desligamento_limpo_nao_e_queda() -> None:
    fake = _executar("Journal stopped")
    assert detectar_queda(fake, uptime_fn=lambda: 60.0) is None


def test_boot_antigo_nao_e_anunciado_como_queda() -> None:
    # Regressão: `systemctl restart od-core` dias depois do boot lia a mesma
    # queda antiga e anunciava energia cortada a cada deploy.
    fake = _executar("qualquer coisa")
    assert detectar_queda(fake, uptime_fn=lambda: LIMITE_ALERTA_S + 1) is None
    assert fake.chamadas == []  # nem consulta o journal


def test_journal_ilegivel_nao_alerta() -> None:
    assert detectar_queda(lambda args: None, uptime_fn=lambda: 10.0) is None
    assert detectar_queda(lambda args: "não é json", uptime_fn=lambda: 10.0) is None
    assert detectar_queda(_executar("x", "[]"), uptime_fn=lambda: 10.0) is None


def test_relogio_para_tras_nao_gera_duracao_negativa() -> None:
    fim = 1_700_000_000
    fake = _executar("queda", _boots(1, fim, fim - 900))
    info = detectar_queda(fake, uptime_fn=lambda: 10.0)
    assert info is not None and info["fora_s"] == 0.0


@pytest.mark.parametrize(
    ("segundos", "esperado"),
    [
        (0, "0 s"), (59, "59 s"), (60, "1 min"), (3_600, "1 h"),
        (7_800, "2 h 10 min"), (86_400 * 3 + 3_600 * 4, "3 dia(s) 4 h"),
        (86_400 * 2, "2 dia(s)"),
    ],
)
def test_formatar_duracao(segundos: int, esperado: str) -> None:
    assert formatar_duracao(segundos) == esperado


def test_resumo_diz_que_nao_foi_registrado_a_causa() -> None:
    texto = resumo_queda({"fora_s": 3_600})
    assert "voltou após queda de energia" in texto
    assert "ficou fora cerca de 1 h" in texto
    assert "não foi registrado" in texto


def test_uptime_le_proc_uptime(tmp_path) -> None:
    arquivo = tmp_path / "uptime"
    arquivo.write_text("1234.56 9999.00\n", encoding="ascii")
    assert uptime_s(str(arquivo)) == 1234.56
    assert uptime_s(str(tmp_path / "ausente")) == 0.0
