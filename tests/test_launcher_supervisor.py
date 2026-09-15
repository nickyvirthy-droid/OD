"""
OMEGA DRAKON • TESTS
Módulo: tests/test_launcher_supervisor.py
Descrição: Testes do isolamento dos loops do modo `all` (runtime/launcher.py).
           Regressão das quedas de 2026-09-13 a 2026-09-15: o
           `asyncio.gather(*tasks)` propagava a exceção de QUALQUER task, então
           um único loop quebrado (timeout de rede do Telegram) derrubava o
           core inteiro — 89 restarts do od-core no período.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - runtime/launcher.py (_all / _supervise)
  - journal do od-core (2026-09-13 02:53 — 2026-09-15 05:10)
"""

from __future__ import annotations

import asyncio

import pytest

from runtime.launcher import _supervise


@pytest.mark.asyncio
async def test_loop_que_cai_e_reiniciado() -> None:
    """O supervisor mantém o loop de pé depois de uma falha inesperada."""
    execucoes: list[int] = []

    async def loop() -> None:
        execucoes.append(1)
        if len(execucoes) == 1:
            raise TimeoutError("The read operation timed out")
        await asyncio.sleep(3600)

    task = asyncio.create_task(_supervise("teste", loop, delay_s=0.001))
    try:
        for _ in range(200):
            if len(execucoes) >= 2:
                break
            await asyncio.sleep(0.005)
        assert len(execucoes) == 2  # caiu uma vez e voltou
        assert not task.done()  # e o supervisor segue rodando
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_cancelamento_propaga() -> None:
    """CancelledError é shutdown, não falha: não pode virar restart."""
    iniciou = asyncio.Event()

    async def loop() -> None:
        iniciou.set()
        await asyncio.sleep(3600)

    task = asyncio.create_task(_supervise("teste", loop, delay_s=0.001))
    await asyncio.wait_for(iniciou.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_sem_restart_nao_propaga_a_falha() -> None:
    """`restart=False` (API) contém a falha: o gather não recebe exceção."""

    async def loop() -> None:
        raise TimeoutError("The read operation timed out")

    await asyncio.wait_for(
        _supervise("api", loop, restart=False, delay_s=0.001), timeout=2
    )


@pytest.mark.asyncio
async def test_gather_com_supervisao_nao_derruba_o_core() -> None:
    """Espelha o crash real: com a supervisão, o gather não estoura."""

    async def cai() -> None:
        raise TimeoutError("The read operation timed out")

    async def segue() -> None:
        await asyncio.sleep(0.02)
        return None

    await asyncio.wait_for(
        asyncio.gather(
            _supervise("telegram", cai, restart=False, delay_s=0.001),
            _supervise("recovery", segue, restart=False, delay_s=0.001),
        ),
        timeout=2,
    )
