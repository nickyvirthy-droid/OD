"""
OMEGA DRAKON • TESTS
Módulo: tests/test_launcher_supervisor.py
Descrição: Testes do isolamento dos loops do modo `all` (runtime/launcher.py).
           Regressão das quedas de 2026-09-13 a 2026-09-15: o
           `asyncio.gather(*tasks)` propagava a exceção de QUALQUER task, então
           um único loop quebrado (timeout de rede do Telegram) derrubava o
           core inteiro — 89 restarts do od-core no período. Cada queda passa a
           entrar no registro de supervisão (core/supervision.py), que alimenta
           o check "loops" do /health e o alerta do notifier.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - runtime/launcher.py (_all / _supervise)
  - core/supervision.py
  - journal do od-core (2026-09-13 02:53 — 2026-09-15 05:10)
"""

from __future__ import annotations

import asyncio

import pytest

from core.supervision import SupervisionRegistry
from runtime.launcher import _supervise


def _registro() -> SupervisionRegistry:
    """Registro local — os testes não poluem o registro global do processo."""
    return SupervisionRegistry()


@pytest.mark.asyncio
async def test_loop_que_cai_e_reiniciado() -> None:
    """O supervisor mantém o loop de pé depois de uma falha inesperada."""
    execucoes: list[int] = []

    async def loop() -> None:
        execucoes.append(1)
        if len(execucoes) == 1:
            raise TimeoutError("The read operation timed out")
        await asyncio.sleep(3600)

    task = asyncio.create_task(
        _supervise("teste", loop, delay_s=0.001, registry=_registro())
    )
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

    task = asyncio.create_task(
        _supervise("teste", loop, delay_s=0.001, registry=_registro())
    )
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
        _supervise("api", loop, restart=False, delay_s=0.001, registry=_registro()),
        timeout=2,
    )


@pytest.mark.asyncio
async def test_queda_entra_no_registro_de_supervisao() -> None:
    """A queda vira estado visível: /health degradado e alerta do notifier."""
    registro = _registro()
    execucoes: list[int] = []

    async def loop() -> None:
        execucoes.append(1)
        if len(execucoes) == 1:
            raise TimeoutError("The read operation timed out")
        await asyncio.sleep(3600)

    task = asyncio.create_task(
        _supervise("telegram", loop, delay_s=0.001, registry=registro)
    )
    try:
        for _ in range(200):
            estado = registro.get("telegram")
            if estado is not None and estado.restarts >= 1:
                break
            await asyncio.sleep(0.005)
        estado = registro.get("telegram")
        assert estado is not None
        assert estado.failures == 1
        assert estado.restarts == 1
        assert estado.last_kind == "TimeoutError"
        assert estado.last_error == "The read operation timed out"
        saude = registro.health()
        assert saude["ok"] is False
        assert saude["status"] == "degraded"
        assert "telegram" in saude["detail"]
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_loop_que_retorna_tambem_e_registrado() -> None:
    """Loop que retorna sozinho conta como queda (não é queda silenciosa)."""
    registro = _registro()

    async def loop() -> None:
        return None

    await asyncio.wait_for(
        _supervise(
            "recovery", loop, restart=False, delay_s=0.001, registry=registro
        ),
        timeout=2,
    )
    estado = registro.get("recovery")
    assert estado is not None
    assert estado.failures == 1
    assert estado.last_kind == "Returned"


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
            _supervise(
                "telegram", cai, restart=False, delay_s=0.001,
                registry=_registro(),
            ),
            _supervise(
                "recovery", segue, restart=False, delay_s=0.001,
                registry=_registro(),
            ),
        ),
        timeout=2,
    )
