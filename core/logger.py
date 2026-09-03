#!/usr/bin/env python3
"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/logger.py
Descrição: Logger estruturado com protocolo NICKY — console + arquivo,
           saída texto ou JSON, context binding, níveis com ONLINE.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime observability/logging/
  - Protocolo NICKY de logs: [NICKY][INFO|WARN|CRIT|ONLINE]
  - OMEGADRAKON_SPEC.md §7.3 (auditoria contínua com timestamp e sessão)

Architecture:
    O logger centraliza toda a produção de logs do OmegaDrakon seguindo o
    protocolo NICKY. Cada registro carrega nível, timestamp, módulo de
    origem e contexto estruturado (key=value), podendo ser emitido como
    texto legível ou linha JSON para ingestão por ferramentas de telemetria.

    O logger é thread-safe (lock interno) e suporta sinks de console e
    arquivo simultaneamente. Context binding permite criar loggers filhos
    com contexto fixo (ex: component="bridge").

Usage:
    from core.logger import get_logger

    log = get_logger("omega.core.bridge")
    log.info("Bridge started", port=8765, host="127.0.0.1")
    log.online("Bridge heartbeat", session="abc123")
    log.warn("LLM timeout", timeout_s=120)
    log.crit("Security violation", action="filesystem.delete")

    # Child logger with bound context
    bridge_log = log.bind(component="bridge")
    bridge_log.info("Message routed", destination="agent.nicky")
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Optional, TextIO

__signature__ = "OD // CORE"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NICKY_PREFIX = "[NICKY]"
DEFAULT_FORMAT = "{prefix}[{level}] {message}"
DEFAULT_FILE_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
DEFAULT_FILE_BACKUP_COUNT = 3


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------

class LogLevel(IntEnum):
    """Log levels do OmegaDrakon — valores alinhados com logging stdlib.

    ONLINE é um nível próprio do protocolo NICKY, usado para presença,
    heartbeats e registros de continuidade (acima de INFO, abaixo de WARN).
    """
    DEBUG = 10
    INFO = 20
    ONLINE = 25
    WARN = 30
    ERROR = 40
    CRIT = 50

    @classmethod
    def parse(cls, value: str | int) -> "LogLevel":
        """Converte string ou int para LogLevel (case-insensitive)."""
        if isinstance(value, int):
            return cls(value)
        name = value.upper()
        if name == "WARNING":
            return cls.WARN
        if name == "CRITICAL":
            return cls.CRIT
        if name == "ONLINE":
            return cls.ONLINE
        return cls[name]


# ---------------------------------------------------------------------------
# LogRecord
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class LogRecord:
    """Um registro de log estruturado (imutável)."""
    ts: float
    level: LogLevel
    level_name: str
    name: str          # nome do logger (módulo de origem)
    message: str
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": round(self.ts, 6),
            "level": self.level_name,
            "logger": self.name,
            "message": self.message,
            "context": self.context,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# File Sink (com rotação simples)
# ---------------------------------------------------------------------------

class _FileSink:
    """Sink de arquivo com rotação por tamanho (append-only)."""

    def __init__(
        self,
        path: Path,
        *,
        max_bytes: int = DEFAULT_FILE_MAX_BYTES,
        backup_count: int = DEFAULT_FILE_BACKUP_COUNT,
    ) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self.backup_count = max(1, backup_count)
        self._handle: Optional[TextIO] = None

    def open(self) -> None:
        if self._handle is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = open(self.path, "a", encoding="utf-8")  # noqa: SIM115

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def write(self, line: str) -> None:
        self.open()
        if self._handle is None:
            return
        self._handle.write(line)
        self._handle.flush()
        self._rotate_if_needed()

    def _rotate_if_needed(self) -> None:
        if self._handle is None:
            return
        try:
            if self.path.stat().st_size < self.max_bytes:
                return
        except OSError:
            return
        self.close()
        # Rotaciona backups: nome.log.2 -> nome.log.3, nome.log.1 -> nome.log.2
        for i in range(self.backup_count - 1, 0, -1):
            src = Path(f"{self.path}.{i}")
            dst = Path(f"{self.path}.{i + 1}")
            if src.exists():
                dst.unlink(missing_ok=True)
                src.rename(dst)
        Path(f"{self.path}.1").unlink(missing_ok=True)
        self.path.rename(Path(f"{self.path}.1"))
        self.open()


# ---------------------------------------------------------------------------
# NickyLogger
# ---------------------------------------------------------------------------

class NickyLogger:
    """Logger estruturado com protocolo NICKY.

    Características:
      - Níveis: DEBUG, INFO, ONLINE, WARN, ERROR, CRIT
      - Saída texto (padrão) ou JSON (json_output=True)
      - Sinks: console e/ou arquivo
      - Context estruturado por chamada (key=value)
      - Context binding via .bind() para loggers filhos
      - Thread-safe (lock interno)
      - Auditoria: .audit() registra eventos de segurança com session_id
    """

    def __init__(
        self,
        name: str = "omega",
        *,
        level: LogLevel | str | int = LogLevel.INFO,
        json_output: bool = False,
        console: bool = True,
        file_path: str | Path | None = None,
        file_max_bytes: int = DEFAULT_FILE_MAX_BYTES,
        file_backup_count: int = DEFAULT_FILE_BACKUP_COUNT,
        format_template: str = DEFAULT_FORMAT,
    ) -> None:
        self._name = name
        self._level = LogLevel.parse(level)
        self._json_output = json_output
        self._console = console
        self._format_template = format_template
        self._bound_context: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._file_sink: Optional[_FileSink] = None
        self._stream: TextIO = sys.stdout
        self._records: list[LogRecord] = []
        self._max_records = 500  # ring buffer em memória

        if file_path is not None:
            self._file_sink = _FileSink(
                Path(file_path),
                max_bytes=file_max_bytes,
                backup_count=file_backup_count,
            )

    # -- Configuração --------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def level(self) -> LogLevel:
        return self._level

    def set_level(self, level: LogLevel | str | int) -> None:
        """Define o nível mínimo de log."""
        self._level = LogLevel.parse(level)

    def set_json_output(self, enabled: bool) -> None:
        """Alterna entre saída texto e JSON."""
        self._json_output = enabled

    def set_stream(self, stream: TextIO) -> None:
        """Redefine o stream de console (útil em testes)."""
        with self._lock:
            self._stream = stream

    def add_file(
        self,
        path: str | Path,
        *,
        max_bytes: int = DEFAULT_FILE_MAX_BYTES,
        backup_count: int = DEFAULT_FILE_BACKUP_COUNT,
    ) -> None:
        """Adiciona sink de arquivo (append-only, com rotação)."""
        with self._lock:
            if self._file_sink is not None:
                self._file_sink.close()
            self._file_sink = _FileSink(
                Path(path),
                max_bytes=max_bytes,
                backup_count=backup_count,
            )

    def remove_file(self) -> None:
        """Remove o sink de arquivo."""
        with self._lock:
            if self._file_sink is not None:
                self._file_sink.close()
                self._file_sink = None

    def set_console(self, enabled: bool) -> None:
        """Liga/desliga a saída de console."""
        self._console = enabled

    # -- Emissão -------------------------------------------------------------

    def debug(self, message: str, **context: Any) -> None:
        self._log(LogLevel.DEBUG, message, context)

    def info(self, message: str, **context: Any) -> None:
        self._log(LogLevel.INFO, message, context)

    def online(self, message: str, **context: Any) -> None:
        """Nível ONLINE — presença, heartbeat, continuidade do agente."""
        self._log(LogLevel.ONLINE, message, context)

    def warn(self, message: str, **context: Any) -> None:
        self._log(LogLevel.WARN, message, context)

    def error(self, message: str, **context: Any) -> None:
        self._log(LogLevel.ERROR, message, context)

    def crit(self, message: str, **context: Any) -> None:
        self._log(LogLevel.CRIT, message, context)

    def audit(self, event: str, *, session_id: str = "", **context: Any) -> None:
        """Registro de auditoria contínua (spec §7.3).

        Sempre registrado com timestamp e identificador de sessão, em nível
        INFO (visível em todos os modos de operação).
        """
        ctx = dict(context)
        if session_id:
            ctx["session_id"] = session_id
        ctx["audit"] = True
        self._log(LogLevel.INFO, f"AUDIT {event}", ctx)

    def bind(self, **context: Any) -> "NickyLogger":
        """Retorna um logger filho com contexto fixo.

        Exemplo:
            log = get_logger("omega").bind(component="bridge")
            log.info("ready")  # inclui component=bridge no contexto
        """
        child = NickyLogger(
            self._name,
            level=self._level,
            json_output=self._json_output,
            console=self._console,
            format_template=self._format_template,
        )
        child._bound_context = {**self._bound_context, **context}
        child._file_sink = self._file_sink
        child._stream = self._stream
        return child

    # -- Interno -------------------------------------------------------------

    def _log(self, level: LogLevel, message: str, context: dict[str, Any]) -> None:
        if level < self._level:
            return

        merged = {**self._bound_context, **context}
        record = LogRecord(
            ts=time.time(),
            level=level,
            level_name=level.name,
            name=self._name,
            message=message,
            context=merged,
        )

        with self._lock:
            line = self._format(record)

            if self._console:
                self._stream.write(line)
                self._stream.flush()

            if self._file_sink is not None:
                self._file_sink.write(line)

            # Ring buffer em memória
            self._records.append(record)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]

    def _format(self, record: LogRecord) -> str:
        if self._json_output:
            return record.to_json() + "\n"
        parts: list[str] = []
        if record.context:
            parts.append(" | ".join(f"{k}={v}" for k, v in record.context.items()))
        core = self._format_template.format(
            prefix=NICKY_PREFIX,
            level=record.level_name,
            message=record.message,
            name=record.name,
            ts=record.ts,
        )
        return (core + (" | " + " | ".join(parts) if parts else "")) + "\n"

    # -- Inspeção ------------------------------------------------------------

    @property
    def records(self) -> list[LogRecord]:
        """Registros recentes em memória (ring buffer)."""
        with self._lock:
            return list(self._records)

    def clear_records(self) -> int:
        """Limpa o ring buffer em memória. Retorna quantidade removida."""
        with self._lock:
            count = len(self._records)
            self._records.clear()
            return count

    def close(self) -> None:
        """Fecha sinks de arquivo e libera recursos."""
        with self._lock:
            if self._file_sink is not None:
                self._file_sink.close()
                self._file_sink = None


# ---------------------------------------------------------------------------
# Registry global
# ---------------------------------------------------------------------------

_loggers: dict[str, NickyLogger] = {}
_registry_lock = threading.Lock()


def get_logger(name: str = "omega", **kwargs: Any) -> NickyLogger:
    """Obtém (ou cria) um NickyLogger registrado globalmente.

    Args:
        name: Nome do logger (convenção: "omega.<componente>.<sub>").
        **kwargs: Passados ao NickyLogger apenas na primeira criação.

    Returns:
        Instância de NickyLogger compartilhada para o mesmo nome.
    """
    global _loggers
    with _registry_lock:
        if name not in _loggers:
            _loggers[name] = NickyLogger(name=name, **kwargs)
        return _loggers[name]


def reset_loggers() -> None:
    """Fecha e remove todos os loggers registrados (para testes)."""
    global _loggers
    with _registry_lock:
        for logger in _loggers.values():
            logger.close()
        _loggers.clear()