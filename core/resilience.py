#!/usr/bin/env python3
"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/resilience.py
Descrição: Circuit Breaker para chamadas externas (LLM, HTTP, APIs).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docs/ANALISE_SISTEMA_TODO.md §R2 (Circuit Breaker + Graceful Degradation)
  - Resilience4j / AWS Well-Architected (padrão de disjuntor)

Architecture:
    Quando um serviço externo está fora, insistir nele custa o timeout cheio
    em cada mensagem. O disjuntor conta falhas consecutivas e, ao atingir o
    limite, abre: as chamadas seguintes falham NA HORA (sem rede) durante a
    janela de recuperação. Passada a janela, deixa passar UMA tentativa
    (meia-aberta): se der certo, fecha; se falhar, abre de novo.

    Estados: `fechado` → `aberto` → `meia_aberto` → (`fechado` | `aberto`).
    O relógio é injetável (`relogio=`) para os testes não dormirem.

    O disjuntor é um objeto puro: quem chama decide o que fazer com a
    recusa. No `OpenAICompatProvider` a recusa vira `LLMError`, que o
    Orchestrator já trata caindo para o próximo provider — degradação
    graciosa, não exceção nova na cara do usuário.

Usage:
    from core.resilience import obter_breaker

    breaker = obter_breaker("llm:groq")
    if not breaker.permitir():
        raise RuntimeError("circuito aberto")
    try:
        resultado = chamar()
    except Exception:
        breaker.registrar_falha()
        raise
    breaker.registrar_sucesso()
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable

__signature__ = "OD // CORE"

_LOG = logging.getLogger("omega.core.resilience")

ENV_LIGADO = "OD_CIRCUIT_BREAKER"
ENV_FALHAS = "OD_CIRCUIT_FAILURES"
ENV_RECUPERACAO = "OD_CIRCUIT_RECOVERY_S"

FALHAS_PADRAO = 5
RECUPERACAO_PADRAO_S = 30.0

FECHADO = "fechado"
ABERTO = "aberto"
MEIA_ABERTO = "meia_aberto"


def _bool_env(nome: str, padrao: bool) -> bool:
    valor = os.environ.get(nome)
    if valor is None or valor == "":
        return padrao
    return valor.strip().lower() in ("1", "true", "sim", "yes", "on")


def _int_env(nome: str, padrao: int, minimo: int = 1) -> int:
    valor = os.environ.get(nome)
    if not valor:
        return padrao
    try:
        numero = int(valor)
    except ValueError:
        return padrao
    return max(minimo, numero)


def _float_env(nome: str, padrao: float) -> float:
    valor = os.environ.get(nome)
    if not valor:
        return padrao
    try:
        numero = float(valor)
    except ValueError:
        return padrao
    return max(0.0, numero)


class CircuitBreaker:
    """Disjuntor thread-safe com janela de recuperação e meia-abertura.

    Attributes:
        nome: Identificador (aparece nos logs e no status).
        falhas_limite: Falhas consecutivas que abrem o circuito.
        recuperacao_s: Segundos em aberto antes de permitir uma tentativa.
        relogio: Fonte de tempo monotônica (injetável em testes).
    """

    def __init__(
        self,
        nome: str,
        *,
        falhas_limite: int | None = None,
        recuperacao_s: float | None = None,
        relogio: Callable[[], float] = time.monotonic,
        ligado: bool | None = None,
    ) -> None:
        self.nome = nome
        self.falhas_limite = max(
            1,
            falhas_limite
            if falhas_limite is not None
            else _int_env(ENV_FALHAS, FALHAS_PADRAO),
        )
        self.recuperacao_s = (
            recuperacao_s
            if recuperacao_s is not None
            else _float_env(ENV_RECUPERACAO, RECUPERACAO_PADRAO_S)
        )
        self._relogio = relogio
        self._ligado = _bool_env(ENV_LIGADO, True) if ligado is None else ligado
        self._lock = threading.RLock()
        self._estado = FECHADO
        self._falhas = 0
        self._aberto_em = 0.0
        self._sucessos = 0
        self._recusas = 0
        self._ultimo_erro = ""

    # -- Consulta ------------------------------------------------------------

    @property
    def ligado(self) -> bool:
        return self._ligado

    def estado(self) -> str:
        """Estado atual, já considerando a janela de recuperação."""
        with self._lock:
            if self._estado == ABERTO and self._janela_vencida():
                self._estado = MEIA_ABERTO
            return self._estado

    def permitir(self) -> bool:
        """True quando a chamada pode ser tentada agora."""
        if not self._ligado:
            return True
        with self._lock:
            if self._estado == ABERTO and self._janela_vencida():
                self._estado = MEIA_ABERTO
            if self._estado == ABERTO:
                self._recusas += 1
                return False
            return True

    def _janela_vencida(self) -> bool:
        return (self._relogio() - self._aberto_em) >= self.recuperacao_s

    # -- Resultado -----------------------------------------------------------

    def registrar_sucesso(self) -> None:
        """Fecha o circuito e zera a contagem de falhas."""
        with self._lock:
            if self._estado != FECHADO:
                _LOG.info("Circuito fechado de novo | breaker=%s", self.nome)
            self._estado = FECHADO
            self._falhas = 0
            self._sucessos += 1
            self._ultimo_erro = ""

    def registrar_falha(self, erro: str = "") -> None:
        """Conta a falha; ao atingir o limite, abre o circuito."""
        with self._lock:
            if not self._ligado:
                return
            self._falhas += 1
            if erro:
                self._ultimo_erro = erro[:200]
            if self._estado == MEIA_ABERTO or self._falhas >= self.falhas_limite:
                if self._estado != ABERTO:
                    _LOG.warning(
                        "Circuito ABERTO | breaker=%s falhas=%s recuperacao_s=%s erro=%s",
                        self.nome, self._falhas, self.recuperacao_s, self._ultimo_erro,
                    )
                self._estado = ABERTO
                self._aberto_em = self._relogio()

    def executar(self, funcao: Callable[[], Any]) -> Any:
        """Executa `funcao` sob o disjuntor (síncrono). Recusa = RuntimeError."""
        if not self.permitir():
            raise RuntimeError(f"circuito aberto: {self.nome}")
        try:
            resultado = funcao()
        except Exception as exc:
            self.registrar_falha(f"{type(exc).__name__}: {exc}")
            raise
        self.registrar_sucesso()
        return resultado

    def resetar(self) -> None:
        """Volta ao fechado e zera contadores (painel/testes)."""
        with self._lock:
            self._estado = FECHADO
            self._falhas = 0
            self._aberto_em = 0.0
            self._ultimo_erro = ""

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "nome": self.nome,
                "estado": self.estado(),
                "ligado": self._ligado,
                "falhas": self._falhas,
                "falhas_limite": self.falhas_limite,
                "recuperacao_s": self.recuperacao_s,
                "sucessos": self._sucessos,
                "recusas": self._recusas,
                "ultimo_erro": self._ultimo_erro,
            }


# ---------------------------------------------------------------------------
# Registro global (um breaker por nome)
# ---------------------------------------------------------------------------

_breakers: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def obter_breaker(nome: str, **kwargs: Any) -> CircuitBreaker:
    """Devolve (ou cria) o breaker registrado para `nome`."""
    with _registry_lock:
        breaker = _breakers.get(nome)
        if breaker is None:
            breaker = CircuitBreaker(nome, **kwargs)
            _breakers[nome] = breaker
        return breaker


def status_breakers() -> list[dict[str, Any]]:
    """Status de todos os breakers (para /health e /admin)."""
    with _registry_lock:
        return [b.status() for b in _breakers.values()]


def resetar_breakers() -> None:
    """Fecha e remove todos os breakers (testes)."""
    with _registry_lock:
        for breaker in _breakers.values():
            breaker.resetar()
        _breakers.clear()
