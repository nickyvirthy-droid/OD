#!/usr/bin/env python3
"""
OMEGA DRAKON • RUNTIME
Module: control_bridge
Description: Local command execution bridge for OmegaDrakon.
Interface Viva: Nicky Virthy
Architect: Alex Projeti
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8765

OD_ROOT = Path("/home/alex/OmegaDrakon").resolve()
LOG_DIR = OD_ROOT / "logs"
LOG_FILE = LOG_DIR / "control_bridge.jsonl"

MAX_OUTPUT = 64 * 1024
DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 900

ALLOWED_COMMANDS = {
    "cat",
    "find",
    "grep",
    "head",
    "tail",
    "ls",
    "pwd",
    "tree",
    "python",
    "python3",
    "pytest",
    "git",
    "file",
    "sed",
    "awk",
    "du",
    "df",
    "stat",
    "readlink",
}

BLOCKED_TOKENS = {
    "sudo",
    "su",
    "doas",
    "rm",
    "rmdir",
    "mkfs",
    "fdisk",
    "parted",
    "shutdown",
    "reboot",
    "poweroff",
    "systemctl",
    "mount",
    "umount",
    "chown",
    "chmod",
    "setfacl",
    "useradd",
    "userdel",
    "passwd",
    "kill",
    "pkill",
    "killall",
}

def ensure_runtime() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def audit(event: dict) -> None:
    ensure_runtime()
    event = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        **event,
    }

    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def reject_path_escape(text: str) -> None:
    forbidden = (
        "/home/alex/nicky",
        "/home/alex/nexus",
        "/home/alex/NV",
        "/home/alex/Legado",
        "/etc",
        "/root",
        "/boot",
        "/usr",
        "/var",
        "/opt",
    )

    for item in forbidden:
        if item in text:
            raise PermissionError(f"path outside OD scope: {item}")


def validate_command(command: str) -> list[str]:
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must be a non-empty string")

    reject_path_escape(command)

    argv = shlex.split(command)

    if not argv:
        raise ValueError("empty command")

    program = Path(argv[0]).name

    if program in BLOCKED_TOKENS:
        raise PermissionError(f"blocked command: {program}")

    if program not in ALLOWED_COMMANDS:
        raise PermissionError(f"command not allowlisted: {program}")

    for token in argv:
        lowered = token.lower()

        if lowered in BLOCKED_TOKENS:
            raise PermissionError(f"blocked token: {token}")

        if token.startswith("/"):
            resolved = Path(token).resolve()
            if not resolved.is_relative_to(OD_ROOT):
                raise PermissionError(
                    f"path outside OD scope: {token}"
                )

    return argv


def execute(command: str, timeout: int) -> dict:
    argv = validate_command(command)

    timeout = max(1, min(timeout, MAX_TIMEOUT))

    started = time.monotonic()

    proc = subprocess.run(
        argv,
        cwd=OD_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/home/odrunner",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        },
    )

    elapsed = round(time.monotonic() - started, 3)

    stdout = proc.stdout[-MAX_OUTPUT:]
    stderr = proc.stderr[-MAX_OUTPUT:]

    result = {
        "status": "ok" if proc.returncode == 0 else "error",
        "command": command,
        "exit_code": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "elapsed_seconds": elapsed,
    }

    audit({
        "event": "command",
        **result,
    })

    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "OD-Control-Bridge/0.1"

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(
                200,
                {
                    "status": "ok",
                    "service": "od-control-bridge",
                    "root": str(OD_ROOT),
                },
            )
            return

        self._send(404, {"status": "error", "message": "not found"})

    def do_POST(self) -> None:
        if self.path != "/execute":
            self._send(404, {"status": "error", "message": "not found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 1024 * 1024:
                raise ValueError("invalid request size")

            raw = self.rfile.read(content_length)
            payload = json.loads(raw)

            command = payload.get("command")
            timeout = int(payload.get("timeout", DEFAULT_TIMEOUT))

            result = execute(command, timeout)
            self._send(200, result)

        except subprocess.TimeoutExpired as exc:
            result = {
                "status": "timeout",
                "command": str(exc.cmd),
                "timeout": exc.timeout,
            }
            audit({
                "event": "timeout",
                **result,
            })
            self._send(408, result)

        except Exception as exc:
            result = {
                "status": "denied",
                "error": type(exc).__name__,
                "message": str(exc),
            }
            audit({
                "event": "rejected",
                **result,
            })
            self._send(403, result)

    def log_message(self, fmt: str, *args) -> None:
        audit({
            "event": "http",
            "message": fmt % args,
        })


def main() -> None:
    ensure_runtime()

    if os.geteuid() == 0:
        raise RuntimeError("od-control-bridge must never run as root")

    server = ThreadingHTTPServer((HOST, PORT), Handler)

    audit({
        "event": "startup",
        "host": HOST,
        "port": PORT,
        "root": str(OD_ROOT),
        "uid": os.getuid(),
    })

    print(f"OD Control Bridge listening on http://{HOST}:{PORT}")

    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
