"""
OMEGA DRAKON • TESTS
Módulo: tests/test_actions_catalog.py
Descrição: Testes do catálogo de 56 Actions (tools/actions/) — Fase 4,
           item 4.4: catalogação completa por categoria, execução funcional
           de sistema/processos/arquivos/git/introspecção, degradação
           graciosa de docker/serviços/db, validação pelo Security Layer
           (roles, escopo estrito, deny), e integração com o Action
           Registry (métricas/trilha).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime core/actions/ (56 actions)
  - docs/NV_LEGACY_ANALYSIS.md §3.3
  - ROADMAP_ABSORCAO.md Fase 4, item 4.4
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

from core.security import ScopeEngine, SecurityManager
from tools.actions import (
    ACTIONS_COUNT,
    CATALOG,
    CATEGORIES,
    build_registry,
    register_all,
)
from tools.registry import ActionRegistry

EXPECTED_CATEGORIES = {
    "system": 14,  # + network_hosts (v0.27.5, complementar OD)
    "process": 4,
    "docker": 4,
    "service": 3,
    "filesystem": 15,
    "git": 10,
    "database": 3,
    "introspection": 4,
}


def strict_admin(tmp_path: Path) -> SecurityManager:
    """SecurityManager strict com escopo no tmp e papel admin (wildcard)."""
    scope = ScopeEngine(allowed_roots=[tmp_path])
    return SecurityManager(mode="strict", scope_engine=scope)


# ===========================================================================
# Catálogo — estrutura
# ===========================================================================

class TestActionsCatalog:
    """56 ações catalogadas por categoria com metadados consistentes."""

    def test_catalog_count_and_categories(self) -> None:
        assert ACTIONS_COUNT == 57
        assert len(CATALOG) == 57
        assert CATEGORIES == EXPECTED_CATEGORIES
        assert sum(CATEGORIES.values()) == 57

    def test_names_unique_and_dotted_clean(self) -> None:
        names = [spec["name"] for spec in CATALOG]
        assert len(names) == len(set(names))
        for spec in CATALOG:
            assert spec["name"]
            assert spec["category"]
            assert callable(spec["handler"])
            assert isinstance(spec["description"], str) and spec["description"]
            assert spec["params"] is not None

    def test_legacy_reference_actions_present(self) -> None:
        """54 ações enumeradas na análise do NV estão todas no catálogo."""
        legacy = [
            # sistema
            "system_info", "datetime", "uptime", "disk_usage", "memory_usage",
            "cpu_info", "ip_address", "system_which", "system_hostname",
            "system_env", "system_ping", "system_user", "system_groups",
            # processos
            "process_list", "process_info", "process_kill",
            # docker
            "docker_list", "docker_status", "docker_logs", "docker_stats",
            # serviços
            "service_list", "service_status", "service_logs",
            # arquivos
            "filesystem_search", "filesystem_read", "filesystem_write",
            "filesystem_delete", "filesystem_exists", "filesystem_info",
            "filesystem_list", "filesystem_mkdir", "filesystem_move",
            "filesystem_copy", "filesystem_touch", "filesystem_tree",
            "filesystem_hash", "filesystem_archive", "filesystem_extract",
            # git
            "git_branch", "git_status", "git_commit", "git_add", "git_log",
            "git_diff", "git_checkout", "git_fetch", "git_pull", "git_push",
            # banco de dados
            "database_tables", "database_schema", "database_query",
            # introspecção
            "action_info", "action_schema", "action_validate",
        ]
        names = {spec["name"] for spec in CATALOG}
        assert names >= set(legacy)
        assert len(legacy) == 54
        # complementares documentadas
        assert {"action_list", "process_tree"} <= names


# ===========================================================================
# Registro no Action Registry
# ===========================================================================

class TestActionsRegistration:
    """Registro via build_registry/register_all."""

    def test_build_registry_registers_56(self) -> None:
        registry = build_registry()
        assert len(registry.list_actions()) == 57
        assert registry.metrics.actions == 57

    def test_every_action_has_permission_and_schema(self) -> None:
        registry = build_registry()
        for spec in CATALOG:
            action = registry.get(spec["name"])
            assert action.permission == spec["name"]  # gate Security Layer
            assert action.category == spec["category"]
            assert action.source == "tools/actions"
            assert action.version == "1.0.0"

    def test_register_all_twice_skips_duplicates(self) -> None:
        registry = ActionRegistry()
        first = register_all(registry)
        second = register_all(registry)
        assert first == 57
        assert second == 0

    def test_find_by_category(self) -> None:
        registry = build_registry()
        for category, expected in EXPECTED_CATEGORIES.items():
            found = registry.find(category)
            assert len(found) == expected, category

    def test_introspection_actions_available_in_registry(self) -> None:
        registry = build_registry()
        assert registry.has("action_list")
        assert registry.has("action_info")


# ===========================================================================
# Execução — Sistema e Introspecção
# ===========================================================================

@pytest.mark.asyncio
class TestSystemActions:
    """Ações de sistema executando (role admin, sem infra externa)."""

    def _registry(self) -> ActionRegistry:
        return build_registry(security=SecurityManager(mode="strict"))

    async def test_system_info_and_datetime(self) -> None:
        registry = self._registry()
        result = await registry.execute("system_info", role="admin")
        assert result.status == "ok"
        assert result.data["system"]
        dt = await registry.execute("datetime", role="admin")
        assert dt.status == "ok"
        assert dt.data["iso"]

    async def test_uptime_memory_cpu_hostname_user(self) -> None:
        registry = self._registry()
        for name in ("uptime", "memory_usage", "cpu_info", "system_hostname", "system_user"):
            result = await registry.execute(name, role="admin")
            assert result.status == "ok", name
            assert result.data.get("ok") is True, name

    async def test_system_which_and_env(self) -> None:
        registry = self._registry()
        result = await registry.execute(
            "system_which", params={"command": "python3"}, role="admin"
        )
        assert result.status == "ok"
        assert result.data["path"]
        env = await registry.execute("system_env", role="admin")
        assert env.status == "ok"
        assert env.data["count"] > 0
        assert "values" not in env.data  # sem keys → só nomes (anti-vazamento)

    async def test_system_ping_tcp(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        try:
            registry = self._registry()
            result = await registry.execute(
                "system_ping",
                params={"host": "127.0.0.1", "port": port, "timeout": 1.0},
                role="admin",
            )
            assert result.status == "ok"
            assert result.data["reachable"] is True
        finally:
            listener.close()

    async def test_action_list_and_info(self) -> None:
        registry = self._registry()
        listed = await registry.execute("action_list", role="admin")
        assert listed.status == "ok"
        assert listed.data["count"] == 57
        info = await registry.execute(
            "action_info", params={"name": "git_status"}, role="admin"
        )
        assert info.status == "ok"
        assert info.data["category"] == "git"
        schema = await registry.execute(
            "action_schema", params={"name": "system_which"}, role="admin"
        )
        assert schema.status == "ok"
        assert "command" in schema.data["params"]["properties"]

    async def test_action_validate(self) -> None:
        registry = self._registry()
        ok_result = await registry.execute(
            "action_validate",
            params={"name": "filesystem_read", "params": {"path": "/x"}},
            role="admin",
        )
        assert ok_result.status == "ok"
        assert ok_result.data["valid"] is True
        bad_result = await registry.execute(
            "action_validate",
            params={"name": "filesystem_read", "params": {}},
            role="admin",
        )
        assert bad_result.status == "ok"
        assert bad_result.data["valid"] is False
        assert bad_result.data["errors"]


# ===========================================================================
# Execução — Arquivos (escopo estrito dentro do tmp)
# ===========================================================================

@pytest.mark.asyncio
class TestFilesystemActions:
    """Ciclo completo de arquivos com security strict + escopo no tmp."""

    async def test_filesystem_workflow(self, tmp_path: Path) -> None:
        registry = build_registry(security=strict_admin(tmp_path))
        base = str(tmp_path)

        # write → read → exists → info
        wrote = await registry.execute(
            "filesystem_write",
            params={"path": f"{base}/docs/a.txt", "content": "olá mundo\n"},
            role="admin",
        )
        assert wrote.status == "ok"
        read = await registry.execute(
            "filesystem_read", params={"path": f"{base}/docs/a.txt"}, role="admin"
        )
        assert read.status == "ok" and read.data == "olá mundo\n"
        exists = await registry.execute(
            "filesystem_exists", params={"path": f"{base}/docs/a.txt"}, role="admin"
        )
        assert exists.status == "ok" and exists.data is True
        info = await registry.execute(
            "filesystem_info", params={"path": f"{base}/docs/a.txt"}, role="admin"
        )
        assert info.status == "ok" and info.data["type"] == "file"

        # list/mkdir/touch/copy/move/tree
        await registry.execute("filesystem_mkdir", params={"path": f"{base}/novo"}, role="admin")
        await registry.execute("filesystem_touch", params={"path": f"{base}/novo/vazio.txt"}, role="admin")
        copied = await registry.execute(
            "filesystem_copy",
            params={"source": f"{base}/docs/a.txt", "destination": f"{base}/novo/b.txt"},
            role="admin",
        )
        assert copied.status == "ok"
        moved = await registry.execute(
            "filesystem_move",
            params={"source": f"{base}/novo/b.txt", "destination": f"{base}/novo/c.txt"},
            role="admin",
        )
        assert moved.status == "ok"
        assert (Path(base) / "novo/c.txt").exists()
        listing = await registry.execute(
            "filesystem_list", params={"path": f"{base}/novo"}, role="admin"
        )
        assert listing.status == "ok" and "c.txt" in listing.data["entries"]
        tree = await registry.execute(
            "filesystem_tree", params={"path": base, "max_depth": 2}, role="admin"
        )
        assert tree.status == "ok" and tree.data["tree"]

        # hash/search/archive/extract/delete
        hashed = await registry.execute(
            "filesystem_hash", params={"path": f"{base}/docs/a.txt"}, role="admin"
        )
        assert hashed.status == "ok" and len(hashed.data["hash"]) == 64
        searched = await registry.execute(
            "filesystem_search",
            params={"path": f"{base}/docs", "pattern": "*.txt"},
            role="admin",
        )
        assert searched.status == "ok" and searched.data["count"] >= 1
        archive = await registry.execute(
            "filesystem_archive",
            params={"path": f"{base}/docs", "archive_path": f"{base}/docs.zip"},
            role="admin",
        )
        assert archive.status == "ok"
        extracted = await registry.execute(
            "filesystem_extract",
            params={"archive_path": f"{base}/docs.zip", "destination": f"{base}/extraido"},
            role="admin",
        )
        assert extracted.status == "ok"
        # o zip preserva a pasta raiz compactada (docs/...)
        assert (Path(base) / "extraido" / "docs" / "a.txt").exists()
        deleted = await registry.execute(
            "filesystem_delete", params={"path": f"{base}/novo/vazio.txt"}, role="admin"
        )
        assert deleted.status == "ok"
        assert not (Path(base) / "novo/vazio.txt").exists()

    async def test_missing_required_param_invalid(self, tmp_path: Path) -> None:
        registry = build_registry(security=strict_admin(tmp_path))
        result = await registry.execute("filesystem_read", params={}, role="admin")
        assert result.status == "invalid"
        assert any("path" in e for e in result.errors)


# ===========================================================================
# Execução — Processos
# ===========================================================================

@pytest.mark.asyncio
class TestProcessActions:
    """process_list/info/kill/tree (kill de processo filho próprio)."""

    def _registry(self) -> ActionRegistry:
        return build_registry(security=SecurityManager(mode="strict"))

    async def test_process_list_and_info(self) -> None:
        registry = self._registry()
        listed = await registry.execute("process_list", role="admin")
        assert listed.status == "ok"
        assert listed.data["count"] >= 1
        info = await registry.execute(
            "process_info", params={"pid": os.getpid()}, role="admin"
        )
        assert info.status == "ok"
        assert info.data["pid"] == os.getpid()

    async def test_process_tree_root(self) -> None:
        registry = self._registry()
        tree = await registry.execute("process_tree", params={"pid": 1}, role="admin")
        assert tree.status == "ok"
        assert tree.data["tree"]["pid"] == 1

    async def test_process_kill_child(self) -> None:
        child = subprocess.Popen(
            ["python3", "-c", "import time; time.sleep(60)"]
        )
        try:
            registry = self._registry()
            result = await registry.execute(
                "process_kill", params={"pid": child.pid, "sig": 15}, role="admin"
            )
            assert result.status == "ok"
            child.wait(timeout=10)
            assert child.returncode is not None
        finally:
            if child.poll() is None:
                child.kill()

    async def test_process_kill_protects_pid_one(self) -> None:
        registry = self._registry()
        result = await registry.execute(
            "process_kill", params={"pid": 1}, role="admin"
        )
        assert result.status == "error"  # ValueError protegendo pid < 2


# ===========================================================================
# Degradação graciosa — docker / serviços / banco
# ===========================================================================

@pytest.mark.asyncio
class TestGracefulDegradation:
    """Ações de infra executam e degradam sem exceção quando fora do alcance."""

    def _registry(self) -> ActionRegistry:
        return build_registry(security=SecurityManager(mode="strict"))

    async def test_database_actions_degrade(self) -> None:
        registry = self._registry()
        for name, params in [
            ("database_tables", {}),
            ("database_schema", {"table": "users"}),
            ("database_query", {"query": "SELECT 1"}),
        ]:
            result = await registry.execute(name, params=params, role="admin")
            assert result.status == "ok", name
            assert result.data["ok"] is False
            assert "Fase 7.5" in result.data["error"]

    async def test_docker_actions_execute_or_degrade(self) -> None:
        registry = self._registry()
        result = await registry.execute("docker_status", role="admin")
        assert result.status == "ok"
        assert "ok" in result.data  # True (daemon) ou False (indisponível)

    async def test_service_actions_execute_or_degrade(self) -> None:
        registry = self._registry()
        result = await registry.execute("service_list", role="admin")
        assert result.status == "ok"
        # sem systemd: {ok:False}; com systemd: lista
        assert isinstance(result.data.get("services", []), list) or result.data["ok"] is False


# ===========================================================================
# Execução — Git (repositório temporário)
# ===========================================================================

@pytest.mark.skipif(shutil.which("git") is None, reason="git não instalado")
class TestGitActions:
    """Ações git sobre um repositório temporário isolado."""

    def _repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "test@od.local"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "OD Test"],
            check=True, capture_output=True,
        )
        (repo / "a.txt").write_text("um\ndois\n", encoding="utf-8")
        return repo

    @pytest.mark.asyncio
    async def test_git_workflow(self, tmp_path: Path) -> None:
        repo = self._repo(tmp_path)
        registry = build_registry(security=strict_admin(tmp_path))
        rp = str(repo)

        status = await registry.execute("git_status", params={"repo": rp}, role="admin")
        assert status.status == "ok" and status.data["ok"] is True

        added = await registry.execute("git_add", params={"repo": rp}, role="admin")
        assert added.status == "ok" and added.data["ok"] is True

        diff = await registry.execute(
            "git_diff", params={"repo": rp, "staged": True}, role="admin"
        )
        assert diff.status == "ok" and diff.data["ok"] is True
        assert "um" in diff.data["output"]

        commit = await registry.execute(
            "git_commit", params={"repo": rp, "message": "primeiro"}, role="admin"
        )
        assert commit.status == "ok" and commit.data["ok"] is True

        log = await registry.execute("git_log", params={"repo": rp, "limit": 5}, role="admin")
        assert log.status == "ok" and "primeiro" in log.data["output"]

        branch = await registry.execute("git_branch", params={"repo": rp}, role="admin")
        assert branch.status == "ok" and "master" in branch.data["output"]

    @pytest.mark.asyncio
    async def test_git_push_without_remote_degrades(self, tmp_path: Path) -> None:
        repo = self._repo(tmp_path)
        registry = build_registry(security=strict_admin(tmp_path))
        result = await registry.execute(
            "git_push", params={"repo": str(repo)}, role="admin"
        )
        assert result.status == "ok"
        # sem remoto configurado → degradação graciosa em vez de exceção
        if result.data.get("ok") is False:
            assert "git" in result.data.get("tool", "")


# ===========================================================================
# Security Layer na execução do catálogo
# ===========================================================================

@pytest.mark.asyncio
class TestActionsSecurity:
    """Gate do Security Layer: roles, escopo e deny patterns."""

    async def test_unknown_role_denied(self, tmp_path: Path) -> None:
        registry = build_registry(security=strict_admin(tmp_path))
        result = await registry.execute(
            "filesystem_read",
            params={"path": str(tmp_path / "x.txt")},
            role="ghost",
        )
        assert result.status == "denied"
        assert result.denied_by == "permission"

    async def test_path_outside_scope_denied(self, tmp_path: Path) -> None:
        # admin tem permissão, mas o caminho foge do escopo estrito
        registry = build_registry(security=strict_admin(tmp_path))
        outside = tmp_path.parent / "fora.txt"
        outside.write_text("x\n")
        result = await registry.execute(
            "filesystem_write",
            params={"path": str(outside), "content": "y"},
            role="admin",
        )
        assert result.status == "denied"
        assert result.denied_by == "scope"

    async def test_admin_allowed_on_all_actions(self, tmp_path: Path) -> None:
        registry = build_registry(security=strict_admin(tmp_path))
        # amostra representativa com caminhos dentro do escopo
        probe = tmp_path / "probe.txt"
        probe.write_text("x\n", encoding="utf-8")
        cases = [
            ("filesystem_read", {"path": str(probe)}),
            ("filesystem_info", {"path": str(probe)}),
            ("system_info", {}),
            ("action_list", {}),
        ]
        for name, params in cases:
            result = await registry.execute(name, params=params, role="admin")
            assert result.status == "ok", name

    async def test_policy_deny_custom_pattern(self, tmp_path: Path) -> None:
        scope = ScopeEngine(allowed_roots=[tmp_path])
        security = SecurityManager(mode="strict", scope_engine=scope)
        security.policy_engine.add_deny("system_info")
        registry = build_registry(security=security)
        result = await registry.execute("system_info", role="admin")
        assert result.status == "denied"
        assert result.denied_by == "policy"

    async def test_no_security_runs_without_gate(self, tmp_path: Path) -> None:
        registry = build_registry()  # sem SecurityManager
        result = await registry.execute(
            "filesystem_write",
            params={"path": str(tmp_path / "ok.txt"), "content": "z"},
            role="ghost",
        )
        assert result.status == "ok"
        assert (tmp_path / "ok.txt").read_text() == "z"

    async def test_metrics_and_history(self, tmp_path: Path) -> None:
        registry = build_registry(security=strict_admin(tmp_path))
        await registry.execute("system_info", role="admin")
        await registry.execute("action_list", role="ghost")  # denied
        snap = registry.metrics.snapshot()
        assert snap["ok"] == 1
        assert snap["denied"] == 1
        assert registry.history[0]["status"] == "denied"
        assert registry.dump()["actions"] == 57
