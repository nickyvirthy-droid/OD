#!/usr/bin/env python3
"""
OMEGA DRAKON • TESTS
Module: test_security
Description: Unit tests for core/security/ — the 5-layer Security Layer
             (policy → permission → scope → approval → audit).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.security import (
    ActionRequest,
    ApprovalEngine,
    AuditEngine,
    AuditRecord,
    CheckResult,
    EnforcementMode,
    PermissionEngine,
    PolicyEngine,
    ScopeEngine,
    SecurityDecision,
    SecurityManager,
)
from core.security.scope import classify_operation, extract_paths


# ===========================================================================
# Models
# ===========================================================================

class TestActionRequest:
    """Tests for ActionRequest dataclass."""

    def test_defaults(self) -> None:
        req = ActionRequest(action="system.status")
        assert req.action == "system.status"
        assert req.params == {}
        assert req.role == "agent"
        assert req.paths == []
        assert req.destructive is False
        assert req.requires_root is False
        assert req.approval_token is None
        assert len(req.request_id) == 12
        assert isinstance(req.ts, float)

    def test_custom_fields(self) -> None:
        req = ActionRequest(
            action="filesystem.delete",
            params={"path": "/tmp/x"},
            role="admin",
            source="bridge",
            session_id="s-1",
            paths=["/tmp/x"],
            destructive=True,
        )
        assert req.role == "admin"
        assert req.source == "bridge"
        assert req.session_id == "s-1"
        assert req.destructive is True

    def test_immutable(self) -> None:
        req = ActionRequest(action="a")
        with pytest.raises(AttributeError):
            req.action = "b"  # type: ignore[misc]


class TestEnforcementMode:
    """Tests for EnforcementMode enum."""

    def test_values(self) -> None:
        assert EnforcementMode.COMPATIBILITY.value == "compatibility"
        assert EnforcementMode.SOFT.value == "soft"
        assert EnforcementMode.STRICT.value == "strict"

    def test_parse(self) -> None:
        assert EnforcementMode.parse("strict") == EnforcementMode.STRICT
        assert EnforcementMode.parse(EnforcementMode.SOFT) == EnforcementMode.SOFT


class TestSecurityDecision:
    """Tests for SecurityDecision."""

    def test_to_dict(self) -> None:
        req = ActionRequest(action="a", role="agent")
        decision = SecurityDecision(
            request=req,
            allowed=False,
            mode=EnforcementMode.STRICT,
            denied_by="policy",
            reasons=["denied"],
        )
        d = decision.to_dict()
        assert d["allowed"] is False
        assert d["denied_by"] == "policy"
        assert d["mode"] == "strict"
        assert d["action"] == "a"


class TestAuditRecord:
    """Tests for AuditRecord."""

    def test_from_decision(self) -> None:
        req = ActionRequest(action="a", role="agent", session_id="s")
        decision = SecurityDecision(
            request=req,
            allowed=True,
            mode=EnforcementMode.SOFT,
            reasons=["ok"],
        )
        record = AuditRecord.from_decision(decision)
        assert record.action == "a"
        assert record.allowed is True
        assert record.mode == EnforcementMode.SOFT
        assert record.session_id == "s"
        assert record.reasons == ("ok",)

    def test_to_dict(self) -> None:
        req = ActionRequest(action="a")
        decision = SecurityDecision(
            request=req,
            allowed=False,
            mode=EnforcementMode.STRICT,
            denied_by="scope",
        )
        record = AuditRecord.from_decision(decision)
        d = record.to_dict()
        assert d["denied_by"] == "scope"
        assert d["mode"] == "strict"
        assert "ts" in d
        assert "request_id" in d


# ===========================================================================
# PolicyEngine
# ===========================================================================

class TestPolicyEngine:
    """Tests for Policy Engine (camada 1)."""

    def test_allows_unknown_action_by_default(self) -> None:
        engine = PolicyEngine()
        req = ActionRequest(action="custom.action")
        result = engine.evaluate(req)
        assert isinstance(result, CheckResult)
        assert result.layer == "policy"
        assert result.allowed is True

    def test_denies_default_pattern(self) -> None:
        engine = PolicyEngine()
        req = ActionRequest(action="system.shutdown")
        result = engine.evaluate(req)
        assert result.allowed is False
        assert "denied by policy" in result.reason

    def test_add_deny(self) -> None:
        engine = PolicyEngine()
        engine.add_deny("filesystem.wipe")
        req = ActionRequest(action="filesystem.wipe")
        assert engine.evaluate(req).allowed is False

    def test_remove_deny(self) -> None:
        engine = PolicyEngine()
        engine.add_deny("custom.deny")
        assert engine.remove_deny("custom.deny") is True
        req = ActionRequest(action="custom.deny")
        assert engine.evaluate(req).allowed is True

    def test_allowlist_mode(self) -> None:
        engine = PolicyEngine(allowlist_enabled=True)
        engine.add_allow("system.*")
        assert engine.evaluate(ActionRequest(action="system.status")).allowed is True
        denied = engine.evaluate(ActionRequest(action="filesystem.delete"))
        assert denied.allowed is False
        assert "not in the allowlist" in denied.reason

    def test_destructive_token_detected(self) -> None:
        engine = PolicyEngine()
        req = ActionRequest(
            action="shell.execute",
            params={"command": "rm -rf /important"},
        )
        result = engine.evaluate(req)
        assert result.allowed is False
        assert "Destructive token" in result.reason

    def test_destructive_token_ok_when_absent(self) -> None:
        engine = PolicyEngine()
        req = ActionRequest(action="shell.execute", params={"command": "ls -la"})
        assert engine.evaluate(req).allowed is True

    def test_add_custom_token(self) -> None:
        engine = PolicyEngine()
        engine.add_destructive_token("evil_command")
        req = ActionRequest(action="shell.execute", params={"command": "run evil_command"})
        assert engine.evaluate(req).allowed is False

    def test_remove_custom_token(self) -> None:
        engine = PolicyEngine()
        engine.add_destructive_token("evil_command")
        assert engine.remove_destructive_token("evil_command") is True
        req = ActionRequest(action="shell.execute", params={"command": "evil_command"})
        assert engine.evaluate(req).allowed is True

    def test_clear_resets_to_defaults(self) -> None:
        engine = PolicyEngine()
        engine.add_deny("custom.deny")
        engine.add_allow("custom.allow")
        engine.set_allowlist(True)
        engine.clear()
        assert engine.allowlist_enabled is False
        assert "custom.deny" not in engine.deny_patterns
        assert engine.allow_patterns == []

    def test_dump(self) -> None:
        engine = PolicyEngine()
        d = engine.dump()
        assert "deny_patterns" in d
        assert "destructive_tokens" in d
        assert "system.shutdown" in d["deny_patterns"]


# ===========================================================================
# PermissionEngine
# ===========================================================================

class TestPermissionEngine:
    """Tests for Permission Engine (camada 2)."""

    def test_default_agent_allows_basic_actions(self) -> None:
        engine = PermissionEngine()
        assert engine.is_allowed("agent", "system.status") is True
        assert engine.is_allowed("agent", "filesystem.read") is True

    def test_default_agent_denies_sensitive(self) -> None:
        engine = PermissionEngine()
        assert engine.is_allowed("agent", "system.shutdown") is False
        assert engine.is_allowed("agent", "filesystem.write") is False

    def test_admin_has_wildcard(self) -> None:
        engine = PermissionEngine()
        assert engine.is_allowed("admin", "anything.at.all") is True

    def test_unknown_role_denied_by_default(self) -> None:
        engine = PermissionEngine()
        req = ActionRequest(action="system.status", role="hacker")
        result = engine.evaluate(req)
        assert result.allowed is False
        assert "Unknown role" in result.reason

    def test_grant(self) -> None:
        engine = PermissionEngine()
        engine.grant("agent", "filesystem.write")
        assert engine.is_allowed("agent", "filesystem.write") is True

    def test_grant_wildcard_pattern(self) -> None:
        engine = PermissionEngine()
        engine.grant("agent", "git.*")
        assert engine.is_allowed("agent", "git.commit") is True
        assert engine.is_allowed("agent", "git.push") is True

    def test_revoke(self) -> None:
        engine = PermissionEngine()
        engine.grant("agent", "filesystem.write")
        assert engine.revoke("agent", "filesystem.write") is True
        assert engine.is_allowed("agent", "filesystem.write") is False

    def test_revoke_nonexistent(self) -> None:
        engine = PermissionEngine()
        assert engine.revoke("agent", "nope") is False

    def test_revoke_role(self) -> None:
        engine = PermissionEngine()
        assert engine.revoke_role("agent") is True
        assert engine.list_roles() == ["admin", "router"]

    def test_evaluate_denied_reason(self) -> None:
        engine = PermissionEngine()
        req = ActionRequest(action="system.shutdown", role="agent")
        result = engine.evaluate(req)
        assert result.allowed is False
        assert "no permission" in result.reason

    def test_evaluate_allowed(self) -> None:
        engine = PermissionEngine()
        req = ActionRequest(action="memory.get", role="agent")
        result = engine.evaluate(req)
        assert result.allowed is True

    def test_permissions_for(self) -> None:
        engine = PermissionEngine()
        perms = engine.permissions_for("agent")
        assert "system.status" in perms

    def test_dump(self) -> None:
        engine = PermissionEngine()
        d = engine.dump()
        assert "admin" in d["roles"]
        assert d["roles"]["admin"] == ["*"]


# ===========================================================================
# ScopeEngine
# ===========================================================================

class TestScopeEngine:
    """Tests for Scope Engine (camada 3)."""

    def test_allows_paths_within_root(self) -> None:
        engine = ScopeEngine()
        root = engine.dump()["allowed_roots"][0]
        req = ActionRequest(
            action="filesystem.read",
            paths=[str(Path(root) / "docs" / "README.md")],
            metadata={"operation": "read"},
        )
        assert engine.evaluate(req).allowed is True

    def test_denies_paths_outside_root(self) -> None:
        engine = ScopeEngine()
        req = ActionRequest(
            action="filesystem.read",
            paths=["/etc/passwd"],
            metadata={"operation": "read"},
        )
        result = engine.evaluate(req)
        assert result.allowed is False
        assert "outside the allowed project scope" in result.reason

    def test_relative_path_resolved_against_root(self) -> None:
        engine = ScopeEngine()
        req = ActionRequest(
            action="filesystem.read",
            paths=["docs/CHANGELOG.md"],
            metadata={"operation": "read"},
        )
        assert engine.evaluate(req).allowed is True

    def test_denies_write_to_protected_git(self) -> None:
        engine = ScopeEngine()
        root = engine.dump()["allowed_roots"][0]
        req = ActionRequest(
            action="filesystem.write",
            paths=[str(Path(root) / ".git" / "config")],
            metadata={"operation": "write"},
        )
        result = engine.evaluate(req)
        assert result.allowed is False
        assert "protected" in result.reason

    def test_allows_read_from_protected_path(self) -> None:
        engine = ScopeEngine()
        root = engine.dump()["allowed_roots"][0]
        req = ActionRequest(
            action="filesystem.read",
            paths=[str(Path(root) / ".git" / "config")],
            metadata={"operation": "read"},
        )
        assert engine.evaluate(req).allowed is True

    def test_denies_destructive_operation(self) -> None:
        engine = ScopeEngine()
        req = ActionRequest(action="filesystem.delete", paths=["/x"], destructive=True)
        result = engine.evaluate(req)
        assert result.allowed is False
        assert "Destructive operations" in result.reason

    def test_allow_destructive_flag(self) -> None:
        engine = ScopeEngine(allow_destructive=True)
        root = engine.dump()["allowed_roots"][0]
        req = ActionRequest(
            action="filesystem.delete",
            paths=[str(Path(root) / "tmp" / "x")],
            destructive=True,
        )
        assert engine.evaluate(req).allowed is True

    def test_denies_root_execution(self) -> None:
        engine = ScopeEngine()
        req = ActionRequest(action="system.command", requires_root=True)
        result = engine.evaluate(req)
        assert result.allowed is False
        assert "Root execution" in result.reason

    def test_allow_root_flag(self) -> None:
        engine = ScopeEngine(allow_root=True)
        req = ActionRequest(action="system.command", requires_root=True)
        assert engine.evaluate(req).allowed is True

    def test_denies_root_execution_set_allow(self) -> None:
        engine = ScopeEngine()
        engine.set_allow_root(True)
        req = ActionRequest(action="system.command", requires_root=True)
        assert engine.evaluate(req).allowed is True

    def test_add_root(self) -> None:
        engine = ScopeEngine()
        tmp_root = Path("/tmp/od-test-root")
        engine.add_root(tmp_root)
        assert tmp_root in [Path(p) for p in engine.dump()["allowed_roots"]]

    def test_add_protected_path(self) -> None:
        engine = ScopeEngine()
        target = Path("/tmp/protected-file")
        engine.add_protected_path(target)
        req = ActionRequest(
            action="filesystem.write",
            paths=[str(target)],
            metadata={"operation": "write"},
        )
        assert engine.evaluate(req).allowed is False

    def test_no_paths_allowed(self) -> None:
        engine = ScopeEngine()
        req = ActionRequest(action="system.status")
        assert engine.evaluate(req).allowed is True

    def test_paths_from_params(self) -> None:
        engine = ScopeEngine()
        req = ActionRequest(action="filesystem.read", params={"path": "/etc/passwd"})
        result = engine.evaluate(req)
        assert result.allowed is False  # path extraído dos params

    def test_dump(self) -> None:
        engine = ScopeEngine()
        d = engine.dump()
        assert len(d["allowed_roots"]) >= 1
        assert d["allow_root"] is False
        assert d["allow_destructive"] is False


class TestScopeHelpers:
    """Tests for scope helper functions."""

    def test_classify_operation_explicit(self) -> None:
        req = ActionRequest(action="weird.action", metadata={"operation": "read"})
        assert classify_operation(req) == "read"

    def test_classify_operation_destructive(self) -> None:
        req = ActionRequest(action="anything", destructive=True)
        assert classify_operation(req) == "write"

    def test_classify_operation_write_keyword(self) -> None:
        req = ActionRequest(action="filesystem.delete")
        assert classify_operation(req) == "write"

    def test_classify_operation_read_keyword(self) -> None:
        req = ActionRequest(action="filesystem.read")
        assert classify_operation(req) == "read"

    def test_classify_operation_default_write(self) -> None:
        req = ActionRequest(action="custom.action")
        assert classify_operation(req) == "write"

    def test_extract_paths_from_fields(self) -> None:
        req = ActionRequest(
            action="filesystem.read",
            paths=["/a"],
            params={"path": "/b", "dir": "/c"},
        )
        assert set(extract_paths(req)) == {"/a", "/b", "/c"}

    def test_extract_paths_list_value(self) -> None:
        req = ActionRequest(action="filesystem.read", params={"paths": ["/x", "/y"]})
        assert extract_paths(req) == ["/x", "/y"]

    def test_extract_paths_dedup(self) -> None:
        req = ActionRequest(action="filesystem.read", params={"path": "/x", "source": "/x"})
        assert extract_paths(req) == ["/x"]

    def test_extract_paths_ignores_non_string(self) -> None:
        req = ActionRequest(action="filesystem.read", params={"path": 42, "dir": None})
        assert extract_paths(req) == []


# ===========================================================================
# ApprovalEngine
# ===========================================================================

class TestApprovalEngine:
    """Tests for Approval Engine (camada 4)."""

    def test_disabled_by_default_allows(self) -> None:
        engine = ApprovalEngine()
        req = ActionRequest(action="filesystem.delete", destructive=True)
        result = engine.evaluate(req)
        assert result.allowed is True

    def test_enabled_without_requirement_allows(self) -> None:
        engine = ApprovalEngine(enabled=True)
        req = ActionRequest(action="system.status")
        assert engine.evaluate(req).allowed is True

    def test_requires_approval_pattern(self) -> None:
        engine = ApprovalEngine(enabled=True)
        engine.require_approval("filesystem.*")
        assert engine.requires_approval("filesystem.delete") is True
        assert engine.requires_approval("system.status") is False

    def test_pending_approval_denied(self) -> None:
        engine = ApprovalEngine(enabled=True)
        engine.require_approval("filesystem.delete")
        req = ActionRequest(action="filesystem.delete")
        result = engine.evaluate(req)
        assert result.allowed is False
        assert "requires human approval" in result.reason

    def test_approve_token_flow(self) -> None:
        engine = ApprovalEngine(enabled=True)
        engine.require_approval("filesystem.delete")
        req = ActionRequest(action="filesystem.delete")
        engine.evaluate(req)  # cria pendência

        pending = engine.get_pending(req.request_id)
        assert pending is not None
        assert pending.status == "pending"

        assert engine.approve(pending.token) is True

        approved_req = ActionRequest(
            action="filesystem.delete",
            approval_token=pending.token,
        )
        assert engine.is_approved(approved_req) is True
        assert engine.evaluate(approved_req).allowed is True

    def test_approve_wrong_token(self) -> None:
        engine = ApprovalEngine(enabled=True)
        engine.require_approval("filesystem.delete")
        req = ActionRequest(action="filesystem.delete")
        engine.evaluate(req)
        assert engine.approve("wrong-token") is False

    def test_reject_token(self) -> None:
        engine = ApprovalEngine(enabled=True)
        engine.require_approval("filesystem.delete")
        req = ActionRequest(action="filesystem.delete")
        engine.evaluate(req)
        pending = engine.get_pending(req.request_id)
        assert pending is not None
        assert engine.reject(pending.token) is True
        assert pending.status == "rejected"
        assert engine.is_approved(req) is False

    def test_remove_requirement(self) -> None:
        engine = ApprovalEngine(enabled=True)
        engine.require_approval("filesystem.delete")
        assert engine.remove_approval_requirement("filesystem.delete") is True
        req = ActionRequest(action="filesystem.delete")
        assert engine.evaluate(req).allowed is True

    def test_expired_approval(self) -> None:
        engine = ApprovalEngine(enabled=True, approval_ttl=0.001)
        engine.require_approval("filesystem.delete")
        req = ActionRequest(action="filesystem.delete")
        engine.evaluate(req)
        pending = engine.get_pending(req.request_id)
        assert pending is not None
        import time as _time

        pending.created_ts = _time.time() - 10.0  # envelhece o token
        assert engine.approve(pending.token) is False

    def test_list_pending(self) -> None:
        engine = ApprovalEngine(enabled=True)
        engine.require_approval("filesystem.delete")
        engine.evaluate(ActionRequest(action="filesystem.delete"))
        assert len(engine.list_pending()) == 1


# ===========================================================================
# AuditEngine
# ===========================================================================

class TestAuditEngine:
    """Tests for Audit Engine (camada 5)."""

    def _decision(self, allowed: bool = True) -> SecurityDecision:
        req = ActionRequest(action="a", role="agent", session_id="s1")
        return SecurityDecision(
            request=req,
            allowed=allowed,
            mode=EnforcementMode.STRICT,
            denied_by=None if allowed else "policy",
            reasons=["r"] if not allowed else [],
        )

    def test_record_and_metrics(self) -> None:
        engine = AuditEngine()
        engine.record(self._decision(allowed=True))
        engine.record(self._decision(allowed=False))
        assert engine.metrics.total == 2
        assert engine.metrics.allowed == 1
        assert engine.metrics.denied == 1

    def test_records_contain_details(self) -> None:
        engine = AuditEngine()
        engine.record(self._decision(allowed=False))
        record = engine.records[0]
        assert record.action == "a"
        assert record.session_id == "s1"
        assert record.allowed is False
        assert record.denied_by == "policy"

    def test_sink_receives_record(self) -> None:
        engine = AuditEngine()
        received: list[AuditRecord] = []

        def sink(record: AuditRecord) -> None:
            received.append(record)

        engine.add_sink(sink)
        engine.record(self._decision())
        assert len(received) == 1
        assert received[0].action == "a"

    def test_sink_error_does_not_break(self) -> None:
        engine = AuditEngine()

        def bad_sink(record: AuditRecord) -> None:
            raise RuntimeError("sink failed")

        engine.add_sink(bad_sink)
        engine.record(self._decision())
        assert engine.metrics.total == 1

    def test_ring_buffer_capped(self) -> None:
        engine = AuditEngine(max_records=3)
        for _ in range(5):
            engine.record(self._decision())
        assert len(engine.records) == 3

    def test_clear(self) -> None:
        engine = AuditEngine()
        engine.record(self._decision())
        assert engine.clear() == 1
        assert engine.records == []
        assert engine.metrics.total == 0

    def test_export(self) -> None:
        engine = AuditEngine()
        engine.record(self._decision(allowed=False))
        data = engine.export()
        assert len(data) == 1
        assert data[0]["allowed"] is False

    def test_dump(self) -> None:
        engine = AuditEngine()
        d = engine.dump()
        assert "records" in d
        assert "metrics" in d


# ===========================================================================
# SecurityManager — full pipeline
# ===========================================================================

class TestSecurityManager:
    """Tests for SecurityManager orchestrating the pipeline."""

    def test_strict_blocks_denied_action(self) -> None:
        sm = SecurityManager(mode=EnforcementMode.STRICT)
        sm.start()
        decision = sm.check("system.shutdown", role="agent")
        assert decision.allowed is False
        assert decision.denied_by == "policy"

    def test_compatibility_allows_with_audit(self) -> None:
        sm = SecurityManager(mode=EnforcementMode.COMPATIBILITY)
        decision = sm.check("system.shutdown", role="agent")
        assert decision.allowed is True
        assert decision.denied_by is None
        # Auditoria registrou a decisão
        assert sm.audit_engine.metrics.total == 1

    def test_soft_allows_with_reasons(self) -> None:
        sm = SecurityManager(mode=EnforcementMode.SOFT)
        decision = sm.check("system.shutdown", role="agent")
        assert decision.allowed is True
        assert len(decision.reasons) >= 1

    def test_strict_allows_safe_action(self) -> None:
        sm = SecurityManager(mode=EnforcementMode.STRICT)
        decision = sm.check("system.status", role="agent")
        assert decision.allowed is True

    def test_strict_blocks_out_of_scope_path(self) -> None:
        sm = SecurityManager(mode=EnforcementMode.STRICT)
        decision = sm.check(
            "filesystem.read",
            role="agent",
            paths=["/etc/passwd"],
        )
        assert decision.allowed is False
        assert decision.denied_by == "scope"

    def test_strict_blocks_permission_denial(self) -> None:
        sm = SecurityManager(mode=EnforcementMode.STRICT)
        decision = sm.check("filesystem.write", role="agent", paths=["docs/x"])
        assert decision.allowed is False
        assert decision.denied_by == "permission"

    def test_pipeline_order_respects_first_denial(self) -> None:
        # policy nega antes do scope ser avaliado
        sm = SecurityManager(mode=EnforcementMode.STRICT)
        decision = sm.check("system.shutdown", role="agent", paths=["/etc"])
        assert decision.denied_by == "policy"

    def test_strict_blocks_destructive(self) -> None:
        sm = SecurityManager(mode=EnforcementMode.STRICT)
        decision = sm.check("shell.execute", role="agent", params={"command": "rm -rf /"})
        assert decision.allowed is False
        assert decision.denied_by == "policy"

    def test_strict_approval_flow(self) -> None:
        sm = SecurityManager(mode=EnforcementMode.STRICT)
        sm.approval_engine.set_enabled(True)
        sm.approval_engine.require_approval("filesystem.delete")
        sm.permission_engine.grant("agent", "filesystem.delete")

        decision = sm.check("filesystem.delete", role="agent", paths=["docs/x"])
        assert decision.allowed is False
        assert decision.denied_by == "approval"
        assert decision.approval_required is True
        assert decision.approval_pending is True

        # Aprova e revalida
        pending = sm.approval_engine.get_pending(decision.request.request_id)
        assert pending is not None
        assert sm.approval_engine.approve(pending.token) is True

        decision2 = sm.check(
            "filesystem.delete",
            role="agent",
            paths=["docs/x"],
            approval_token=pending.token,
        )
        assert decision2.allowed is True

    def test_approval_pending_metric(self) -> None:
        sm = SecurityManager(mode=EnforcementMode.SOFT)
        sm.approval_engine.set_enabled(True)
        sm.approval_engine.require_approval("filesystem.delete")
        sm.check("filesystem.delete", role="agent", paths=["docs/x"])
        assert sm.metrics.approvals_pending == 1

    def test_audit_always_recorded(self) -> None:
        sm = SecurityManager(mode=EnforcementMode.STRICT)
        sm.check("system.shutdown", role="agent")
        sm.check("system.status", role="agent")
        assert sm.audit_engine.metrics.total == 2
        assert sm.audit_engine.metrics.denied == 1
        assert sm.audit_engine.metrics.allowed == 1

    def test_metrics(self) -> None:
        sm = SecurityManager(mode=EnforcementMode.STRICT)
        sm.check("system.status", role="agent")
        sm.check("system.shutdown", role="agent")
        assert sm.metrics.validated == 2
        assert sm.metrics.allowed == 1
        assert sm.metrics.denied == 1

    def test_audit_sink_wired(self) -> None:
        received: list[AuditRecord] = []
        sm = SecurityManager(audit_sinks=[received.append])
        sm.check("system.status", role="agent")
        assert len(received) == 1

    def test_custom_engines_injected(self) -> None:
        policy = PolicyEngine()
        policy.add_deny("custom.blocked")
        sm = SecurityManager(mode=EnforcementMode.STRICT, policy_engine=policy)
        assert sm.policy_engine is policy
        decision = sm.check("custom.blocked", role="admin")
        assert decision.allowed is False

    def test_set_mode_runtime(self) -> None:
        sm = SecurityManager(mode=EnforcementMode.COMPATIBILITY)
        decision = sm.check("system.shutdown", role="agent")
        assert decision.allowed is True
        sm.set_mode(EnforcementMode.STRICT)
        decision2 = sm.check("system.shutdown", role="agent")
        assert decision2.allowed is False

    def test_lifecycle(self) -> None:
        sm = SecurityManager()
        assert not sm.running
        sm.start()
        assert sm.running
        sm.start()  # idempotente
        sm.stop()
        assert not sm.running

    def test_dump(self) -> None:
        sm = SecurityManager(mode=EnforcementMode.STRICT)
        d = sm.dump()
        assert d["mode"] == "strict"
        assert d["pipeline"] == ["policy", "permission", "scope", "approval"]
        assert "audit" in d
        assert "policy" in d


# ===========================================================================
# Integration scenarios
# ===========================================================================

class TestSecurityIntegration:
    """End-to-end scenarios simulating OmegaDrakon usage."""

    def test_agent_reads_project_file(self) -> None:
        """Agente lê arquivo do projeto — permitido em modo estrito."""
        sm = SecurityManager(mode=EnforcementMode.STRICT)
        decision = sm.check(
            "filesystem.read",
            role="agent",
            source="agent.nicky",
            session_id="sess-1",
            paths=["docs/CHANGELOG.md"],
            metadata={"operation": "read"},
        )
        assert decision.allowed is True

    def test_agent_cannot_touch_legacy_system(self) -> None:
        """Spec §7.1 — nenhum acesso automático a diretórios legados."""
        sm = SecurityManager(mode=EnforcementMode.STRICT)
        decision = sm.check(
            "filesystem.write",
            role="agent",
            paths=["/home/alex/nicky/config.py"],
            metadata={"operation": "write"},
        )
        assert decision.allowed is False

    def test_destructive_command_requires_approval(self) -> None:
        """Spec §7.2 — comandos destrutivos exigem aprovação humana."""
        sm = SecurityManager(mode=EnforcementMode.STRICT)
        sm.approval_engine.set_enabled(True)
        sm.approval_engine.require_approval("filesystem.delete")

        decision = sm.check(
            "filesystem.delete",
            role="agent",
            paths=["workspace/od-builder/tmp"],
            destructive=True,
        )
        # Negado (destrutivo) OU exigindo aprovação — nunca permitido direto
        assert decision.allowed is False

    def test_full_audit_trail(self) -> None:
        """Todas as chamadas geram trilha de auditoria com sessão."""
        sm = SecurityManager(mode=EnforcementMode.SOFT)
        sm.check("system.status", role="agent", session_id="s1")
        sm.check("system.shutdown", role="agent", session_id="s1")

        records = sm.audit_engine.records
        assert len(records) == 2
        for record in records:
            assert record.session_id == "s1"
            assert record.request_id
        # Soft: nunca bloqueia, mas audita os motivos das negações por camada
        denied = [r for r in records if not r.allowed]
        assert len(denied) == 0
        flagged = [r for r in records if r.reasons]
        assert len(flagged) == 1  # system.shutdown flagado pelo policy/permission