#!/usr/bin/env python3
"""
OMEGA DRAKON • TESTS
Module: test_logger
Description: Unit tests for core/logger.py — structured NICKY-protocol logger.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from core.logger import (
    DEFAULT_FILE_BACKUP_COUNT,
    LogLevel,
    LogRecord,
    NickyLogger,
    get_logger,
    reset_loggers,
)


# ===========================================================================
# LogLevel
# ===========================================================================

class TestLogLevel:
    """Tests for LogLevel enum."""

    def test_ordering(self) -> None:
        assert LogLevel.DEBUG < LogLevel.INFO < LogLevel.ONLINE < LogLevel.WARN < LogLevel.ERROR < LogLevel.CRIT

    def test_parse_int(self) -> None:
        assert LogLevel.parse(20) == LogLevel.INFO
        assert LogLevel.parse(50) == LogLevel.CRIT

    def test_parse_name(self) -> None:
        assert LogLevel.parse("DEBUG") == LogLevel.DEBUG
        assert LogLevel.parse("info") == LogLevel.INFO
        assert LogLevel.parse("ONLINE") == LogLevel.ONLINE
        assert LogLevel.parse("warn") == LogLevel.WARN
        assert LogLevel.parse("CRIT") == LogLevel.CRIT

    def test_parse_warning_alias(self) -> None:
        assert LogLevel.parse("WARNING") == LogLevel.WARN

    def test_parse_critical_alias(self) -> None:
        assert LogLevel.parse("CRITICAL") == LogLevel.CRIT

    def test_online_between_info_and_warn(self) -> None:
        assert LogLevel.INFO < LogLevel.ONLINE < LogLevel.WARN


# ===========================================================================
# LogRecord
# ===========================================================================

class TestLogRecord:
    """Tests for LogRecord dataclass."""

    def test_to_dict(self) -> None:
        rec = LogRecord(ts=1000.0, level=LogLevel.INFO, level_name="INFO", name="omega", message="hello", context={"k": 1})
        d = rec.to_dict()
        assert d["ts"] == 1000.0
        assert d["level"] == "INFO"
        assert d["logger"] == "omega"
        assert d["message"] == "hello"
        assert d["context"] == {"k": 1}

    def test_to_json(self) -> None:
        rec = LogRecord(ts=1000.0, level=LogLevel.WARN, level_name="WARN", name="omega", message="warn msg", context={"k": "v"})
        data = json.loads(rec.to_json())
        assert data["level"] == "WARN"
        assert data["message"] == "warn msg"
        assert data["context"]["k"] == "v"


# ===========================================================================
# NickyLogger — text output
# ===========================================================================

class TestNickyLoggerText:
    """Tests for text-format output."""

    def test_info_message_has_nicky_prefix(self) -> None:
        stream = io.StringIO()
        log = NickyLogger("omega.test", console=True)
        log.set_stream(stream)
        log.info("System started")
        assert "[NICKY][INFO]" in stream.getvalue()
        assert "System started" in stream.getvalue()

    def test_warn_level_name(self) -> None:
        stream = io.StringIO()
        log = NickyLogger("omega.test", console=True)
        log.set_stream(stream)
        log.warn("Something is off")
        assert "[NICKY][WARN]" in stream.getvalue()

    def test_crit_level_name(self) -> None:
        stream = io.StringIO()
        log = NickyLogger("omega.test", console=True)
        log.set_stream(stream)
        log.crit("Fatal error")
        assert "[NICKY][CRIT]" in stream.getvalue()

    def test_online_level_name(self) -> None:
        stream = io.StringIO()
        log = NickyLogger("omega.test", console=True)
        log.set_stream(stream)
        log.online("Agent online")
        assert "[NICKY][ONLINE]" in stream.getvalue()

    def test_error_level_name(self) -> None:
        stream = io.StringIO()
        log = NickyLogger("omega.test", console=True)
        log.set_stream(stream)
        log.error("Boom")
        assert "[NICKY][ERROR]" in stream.getvalue()

    def test_context_kwargs_in_line(self) -> None:
        stream = io.StringIO()
        log = NickyLogger("omega.test", console=True)
        log.set_stream(stream)
        log.info("Bridge started", port=8765, host="127.0.0.1")
        line = stream.getvalue()
        assert "port=8765" in line
        assert "host=127.0.0.1" in line

    def test_trailing_newline(self) -> None:
        stream = io.StringIO()
        log = NickyLogger("omega.test", console=True)
        log.set_stream(stream)
        log.info("msg")
        assert stream.getvalue().endswith("\n")

    def test_console_disabled(self) -> None:
        stream = io.StringIO()
        log = NickyLogger("omega.test", console=False)
        log.set_stream(stream)
        log.info("silent")
        assert stream.getvalue() == ""


# ===========================================================================
# NickyLogger — level filtering
# ===========================================================================

class TestNickyLoggerLevelFiltering:
    """Tests for minimum level filtering."""

    def test_default_level_is_info(self) -> None:
        log = NickyLogger("omega.test")
        assert log.level == LogLevel.INFO

    def test_debug_below_default_not_emitted(self) -> None:
        stream = io.StringIO()
        log = NickyLogger("omega.test", console=True)
        log.set_stream(stream)
        log.debug("hidden")
        assert stream.getvalue() == ""

    def test_set_level_debug(self) -> None:
        stream = io.StringIO()
        log = NickyLogger("omega.test", console=True)
        log.set_stream(stream)
        log.set_level(LogLevel.DEBUG)
        log.debug("visible now")
        assert "visible now" in stream.getvalue()

    def test_set_level_string(self) -> None:
        log = NickyLogger("omega.test")
        log.set_level("WARN")
        assert log.level == LogLevel.WARN

    def test_filter_warn(self) -> None:
        stream = io.StringIO()
        log = NickyLogger("omega.test", level=LogLevel.WARN, console=True)
        log.set_stream(stream)
        log.info("not shown")
        log.warn("shown")
        out = stream.getvalue()
        assert "not shown" not in out
        assert "shown" in out

    def test_online_filtered_below_warn(self) -> None:
        stream = io.StringIO()
        log = NickyLogger("omega.test", level=LogLevel.WARN, console=True)
        log.set_stream(stream)
        log.online("not shown")
        assert stream.getvalue() == ""


# ===========================================================================
# NickyLogger — JSON output
# ===========================================================================

class TestNickyLoggerJson:
    """Tests for JSON structured output."""

    def test_json_line(self) -> None:
        stream = io.StringIO()
        log = NickyLogger("omega.test", json_output=True, console=True)
        log.set_stream(stream)
        log.info("structured", key="value")
        data = json.loads(stream.getvalue())
        assert data["level"] == "INFO"
        assert data["logger"] == "omega.test"
        assert data["message"] == "structured"
        assert data["context"] == {"key": "value"}

    def test_toggle_json(self) -> None:
        stream = io.StringIO()
        log = NickyLogger("omega.test", console=True)
        log.set_stream(stream)
        log.info("text")
        log.set_json_output(True)
        log.info("json")
        lines = stream.getvalue().splitlines()
        assert lines[0].startswith("[NICKY]")
        json.loads(lines[1])  # segunda linha é JSON válido


# ===========================================================================
# NickyLogger — bind / context
# ===========================================================================

class TestNickyLoggerBind:
    """Tests for bound context via .bind()."""

    def test_bind_adds_context(self) -> None:
        stream = io.StringIO()
        log = NickyLogger("omega.test", console=True)
        log.set_stream(stream)
        child = log.bind(component="bridge")
        child.info("ready")
        assert "component=bridge" in stream.getvalue()

    def test_bind_merges_call_context(self) -> None:
        stream = io.StringIO()
        log = NickyLogger("omega.test", console=True)
        log.set_stream(stream)
        child = log.bind(component="bridge")
        child.info("routed", destination="agent.nicky")
        line = stream.getvalue()
        assert "component=bridge" in line
        assert "destination=agent.nicky" in line

    def test_parent_unaffected_by_child_context(self) -> None:
        stream = io.StringIO()
        log = NickyLogger("omega.test", console=True)
        log.set_stream(stream)
        child = log.bind(component="bridge")
        child.info("child msg")
        log.info("parent msg")
        lines = stream.getvalue().splitlines()
        assert "component=bridge" in lines[0]
        assert "component=bridge" not in lines[1]


# ===========================================================================
# NickyLogger — audit
# ===========================================================================

class TestNickyLoggerAudit:
    """Tests for audit records (spec §7.3)."""

    def test_audit_with_session(self) -> None:
        stream = io.StringIO()
        log = NickyLogger("omega.test", console=True)
        log.set_stream(stream)
        log.audit("tool.call", session_id="sess-123", action="filesystem.read")
        line = stream.getvalue()
        assert "AUDIT tool.call" in line
        assert "session_id=sess-123" in line
        assert "action=filesystem.read" in line

    def test_audit_without_session(self) -> None:
        stream = io.StringIO()
        log = NickyLogger("omega.test", console=True)
        log.set_stream(stream)
        log.audit("event")
        assert "AUDIT event" in stream.getvalue()


# ===========================================================================
# NickyLogger — file sink
# ===========================================================================

class TestNickyLoggerFile:
    """Tests for file output."""

    def test_writes_to_file(self, tmp_path: Path) -> None:
        log_file = tmp_path / "omega.log"
        log = NickyLogger("omega.test", file_path=log_file)
        log.info("written to file", key="value")
        content = log_file.read_text(encoding="utf-8")
        assert "[NICKY][INFO]" in content
        assert "key=value" in content

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        log_file = tmp_path / "nested" / "dir" / "omega.log"
        log = NickyLogger("omega.test", file_path=log_file)
        log.info("deep")
        assert log_file.exists()

    def test_add_file(self, tmp_path: Path) -> None:
        stream = io.StringIO()
        log_file = tmp_path / "added.log"
        log = NickyLogger("omega.test", console=True)
        log.set_stream(stream)
        log.add_file(log_file)
        log.info("both sinks")
        assert log_file.exists()
        assert "[NICKY][INFO]" in log_file.read_text(encoding="utf-8")
        assert "both sinks" in stream.getvalue()

    def test_remove_file(self, tmp_path: Path) -> None:
        log_file = tmp_path / "removed.log"
        log = NickyLogger("omega.test", file_path=log_file)
        log.remove_file()
        log.info("not written")
        assert not log_file.exists()

    def test_rotation(self, tmp_path: Path) -> None:
        log_file = tmp_path / "rot.log"
        log = NickyLogger(
            "omega.test",
            file_path=log_file,
            file_max_bytes=200,
            file_backup_count=DEFAULT_FILE_BACKUP_COUNT,
        )
        for i in range(50):
            log.info(f"line {i} - padding padding padding padding padding")
        log.close()
        assert log_file.exists()
        # Backup deve ter sido criado
        assert Path(f"{log_file}.1").exists()

    def test_close(self, tmp_path: Path) -> None:
        log_file = tmp_path / "closed.log"
        log = NickyLogger("omega.test", file_path=log_file)
        log.info("before close")
        log.close()
        assert log_file.exists()


# ===========================================================================
# NickyLogger — in-memory records
# ===========================================================================

class TestNickyLoggerRecords:
    """Tests for the in-memory ring buffer."""

    def test_records_captured(self) -> None:
        log = NickyLogger("omega.test", console=False)
        log.info("one")
        log.warn("two")
        assert len(log.records) == 2
        assert log.records[0].message == "one"
        assert log.records[1].message == "two"

    def test_records_respect_level_filter(self) -> None:
        log = NickyLogger("omega.test", level=LogLevel.WARN, console=False)
        log.info("hidden")
        log.warn("shown")
        assert [r.message for r in log.records] == ["shown"]

    def test_ring_buffer_capped(self) -> None:
        log = NickyLogger("omega.test", console=False)
        log._max_records = 5
        for i in range(10):
            log.info(f"msg {i}")
        assert len(log.records) == 5
        assert log.records[0].message == "msg 5"

    def test_clear_records(self) -> None:
        log = NickyLogger("omega.test", console=False)
        log.info("one")
        assert log.clear_records() == 1
        assert log.records == []

    def test_record_context(self) -> None:
        log = NickyLogger("omega.test", console=False)
        log.info("ctx", a=1, b="two")
        rec = log.records[0]
        assert rec.context == {"a": 1, "b": "two"}
        assert rec.level_name == "INFO"
        assert rec.name == "omega.test"
        assert isinstance(rec.ts, float)


# ===========================================================================
# Registry
# ===========================================================================

class TestLoggerRegistry:
    """Tests for the global logger registry."""

    def test_get_logger_singleton(self) -> None:
        reset_loggers()
        l1 = get_logger("omega.registry")
        l2 = get_logger("omega.registry")
        assert l1 is l2

    def test_get_logger_distinct_names(self) -> None:
        reset_loggers()
        l1 = get_logger("omega.one")
        l2 = get_logger("omega.two")
        assert l1 is not l2
        assert l1.name == "omega.one"
        assert l2.name == "omega.two"

    def test_reset_loggers(self) -> None:
        reset_loggers()
        l1 = get_logger("omega.reset")
        reset_loggers()
        l2 = get_logger("omega.reset")
        assert l1 is not l2