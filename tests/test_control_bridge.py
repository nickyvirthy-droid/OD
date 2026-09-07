"""
OMEGA DRAKON • TESTS
Módulo: tests/test_control_bridge.py
Descrição: Testes do Control Bridge (runtime/control_bridge/bridge.py) —
           v1.0.0, item 1.5. Cobre o enforcement de segurança da ponte de
           execução local: allowlist de comandos, tokens bloqueados, escape
           de caminho (fora do escopo OD e legados isolados spec §7.1),
           auditoria JSONL e execução de comandos permitidos.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docs/CONTROL_BRIDGE.md (ponte de execução local, allowlist)
  - OMEGADRAKON_SPEC.md §7.1 (isolamento dos legados) e §2.2 (bridge)
  - ROADMAP_V1.md item 1.5 (Control Bridge no repo)
"""

from __future__ import annotations

import json

import pytest

from runtime.control_bridge import bridge


# ---------------------------------------------------------------------------
# reject_path_escape — bloqueio de caminhos fora do escopo / legados
# ---------------------------------------------------------------------------

class TestRejectPathEscape:
    """Spec §7.1: a bridge nunca deve alcançar os sistemas legados."""

    def test_texto_seguro_passa(self) -> None:
        # Nenhum caminho proibido — não deve levantar
        bridge.reject_path_escape("ls -la runtime")
        bridge.reject_path_escape("pwd")
        bridge.reject_path_escape("grep -r token core")

    @pytest.mark.parametrize(
        "texto",
        [
            "/home/alex/nicky/config.py",
            "/home/alex/nicky",
            "/home/alex/nexus",
            "/home/alex/NV",
            "/home/alex/Legado",
            "/opt/omegadrakon",
            "/etc/passwd",
            "/root/.bashrc",
            "/boot/grub",
            "/usr/bin/python3",
            "/var/log",
            "cat /home/alex/nicky/settings.py",
        ],
    )
    def test_caminho_proibido_levanta(self, texto: str) -> None:
        with pytest.raises(PermissionError):
            bridge.reject_path_escape(texto)

    def test_legados_bloqueados_na_mensagem(self) -> None:
        with pytest.raises(PermissionError) as exc:
            bridge.reject_path_escape("/home/alex/nicky/x")
        assert "path outside OD scope" in str(exc.value)


# ---------------------------------------------------------------------------
# validate_command — allowlist, tokens bloqueados e escopo de caminho
# ---------------------------------------------------------------------------

class TestValidateCommand:
    """A ponte só executa comandos allowlisted dentro do escopo OD."""

    def test_comando_allowlisted_retorna_argv(self) -> None:
        assert bridge.validate_command("pwd") == ["pwd"]
        assert bridge.validate_command("ls -la runtime") == ["ls", "-la", "runtime"]
        assert bridge.validate_command("head -n 5 README.md") == [
            "head", "-n", "5", "README.md",
        ]

    def test_comando_vazio_ou_nao_string(self) -> None:
        with pytest.raises(ValueError):
            bridge.validate_command("")
        with pytest.raises(ValueError):
            bridge.validate_command("   ")
        with pytest.raises(ValueError):
            bridge.validate_command(None)  # type: ignore[arg-type]

    def test_programa_fora_da_allowlist(self) -> None:
        with pytest.raises(PermissionError):
            bridge.validate_command("curl http://example.com")
        with pytest.raises(PermissionError):
            bridge.validate_command("bash -c 'pwd'")

    def test_token_bloqueado(self) -> None:
        with pytest.raises(PermissionError):
            bridge.validate_command("rm -rf /tmp/x")
        with pytest.raises(PermissionError):
            bridge.validate_command("python3 -c 'x' && rm -rf .")
        with pytest.raises(PermissionError):
            bridge.validate_command("head -n 5 sudo /etc/hostname")
        with pytest.raises(PermissionError):
            bridge.validate_command("cat /etc/shadow")

    def test_path_fora_do_escopo_od(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(bridge, "OD_ROOT", tmp_path)
        # /tmp real não é relativo ao OD_ROOT (tmp_path) → escape de escopo
        with pytest.raises(PermissionError) as exc:
            bridge.validate_command("cat /tmp/fora_do_od.txt")
        assert "path outside OD scope" in str(exc.value)

    def test_path_dentro_do_escopo_od(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(bridge, "OD_ROOT", tmp_path)
        alvo = tmp_path / "docs" / "arquivo.md"
        argv = bridge.validate_command(f"cat {alvo}")
        assert argv == ["cat", str(alvo)]

    def test_path_legado_bloqueado_no_validate(self, monkeypatch, tmp_path) -> None:
        # Mesmo com OD_ROOT apontando para tmp, os legados continuam proibidos
        monkeypatch.setattr(bridge, "OD_ROOT", tmp_path)
        with pytest.raises(PermissionError):
            bridge.validate_command("ls /home/alex/nexus")


# ---------------------------------------------------------------------------
# audit — trilha JSONL da bridge
# ---------------------------------------------------------------------------

class TestAudit:
    """Toda decisão da bridge é auditada em logs/control_bridge.jsonl."""

    def test_audit_escreve_jsonl(self, monkeypatch, tmp_path) -> None:
        log_dir = tmp_path / "logs"
        log_file = log_dir / "control_bridge.jsonl"
        monkeypatch.setattr(bridge, "LOG_DIR", log_dir)
        monkeypatch.setattr(bridge, "LOG_FILE", log_file)

        bridge.audit({"event": "command", "status": "ok"})
        bridge.audit({"event": "rejected", "status": "denied"})

        assert log_file.is_file()
        linhas = log_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(linhas) == 2
        primeiro = json.loads(linhas[0])
        assert primeiro["event"] == "command"
        assert primeiro["status"] == "ok"
        assert "ts" in primeiro
        segundo = json.loads(linhas[1])
        assert segundo["event"] == "rejected"
        assert segundo["status"] == "denied"

    def test_audit_cria_diretorio(self, monkeypatch, tmp_path) -> None:
        log_dir = tmp_path / "aninhado" / "logs"
        log_file = log_dir / "control_bridge.jsonl"
        monkeypatch.setattr(bridge, "LOG_DIR", log_dir)
        monkeypatch.setattr(bridge, "LOG_FILE", log_file)

        bridge.audit({"event": "startup"})
        assert log_file.is_file()


# ---------------------------------------------------------------------------
# execute — comandos permitidos rodam; negados nunca chegam ao subprocesso
# ---------------------------------------------------------------------------

class TestExecute:
    """Execução mediada: ok só para comandos validados."""

    def test_executa_comando_permitido(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(bridge, "OD_ROOT", tmp_path)
        log_file = tmp_path / "logs" / "control_bridge.jsonl"
        monkeypatch.setattr(bridge, "LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(bridge, "LOG_FILE", log_file)

        resultado = bridge.execute("pwd", timeout=5)
        assert resultado["status"] == "ok"
        assert resultado["exit_code"] == 0
        assert str(tmp_path) in resultado["stdout"]
        # A execução também é auditada
        assert log_file.is_file()
        linhas = log_file.read_text(encoding="utf-8").strip().splitlines()
        assert any(json.loads(l)["event"] == "command" for l in linhas)

    def test_comando_negado_nao_executa(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(bridge, "OD_ROOT", tmp_path)
        log_file = tmp_path / "logs" / "control_bridge.jsonl"
        monkeypatch.setattr(bridge, "LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(bridge, "LOG_FILE", log_file)

        with pytest.raises(PermissionError):
            bridge.execute("rm -rf .", timeout=5)
        with pytest.raises(PermissionError):
            bridge.execute("python3 -c 'x' && rm -rf .", timeout=5)
        # Nada foi executado nem auditado como command
        if log_file.exists():
            linhas = log_file.read_text(encoding="utf-8").strip().splitlines()
            assert not any(json.loads(l)["event"] == "command" for l in linhas)

    def test_path_escape_nao_executa(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(bridge, "OD_ROOT", tmp_path)
        with pytest.raises(PermissionError):
            bridge.execute("ls /home/alex/nicky", timeout=5)
