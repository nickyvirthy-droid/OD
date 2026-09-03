"""
OMEGA DRAKON • TESTS
Módulo: tests/test_coder.py
Descrição: Testes do Coder Engine (core/coder.py) — Fase 4, item 4.1:
           pipeline sandbox → testes → backup → promoção, aplicação de
           patches unificados, escopo estrito, Security Layer, Event Bus,
           métricas e trilha.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime core/coder.py (sandbox → patch → validação → backup → promoção)
  - OMEGADRAKON_SPEC.md §7
  - ROADMAP_ABSORCAO.md Fase 4, item 4.1
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import core.coder as coder_module
from core.coder import (
    CoderEngine,
    CoderResult,
    CoderScopeError,
    apply_unified_diff,
    diff_stats,
    generate_unified_patch,
    parse_unified_diff,
)
from core.event_bus import EventBus
from core.security import ScopeEngine, SecurityManager

_TestOutcome = coder_module.TestOutcome  # alias sublinhado evita coleta


# ===========================================================================
# Unified diff — parse e aplicação
# ===========================================================================

class TestUnifiedDiffParse:
    """Parse de hunks de diffs unificados."""

    def test_parse_valid_multiple_hunks(self) -> None:
        diff = (
            "--- a/orig.py\n"
            "+++ b/patched.py\n"
            "@@ -1,3 +1,3 @@\n"
            " linha1\n"
            "-linha2\n"
            "+linha2 MOD\n"
            " linha3\n"
            "@@ -8,2 +8,3 @@\n"
            " linha8\n"
            "+linha8b\n"
            " linha9\n"
        )
        ok, hunks, error = parse_unified_diff(diff)
        assert ok and error == ""
        assert len(hunks) == 2
        assert hunks[0].old_start == 1 and hunks[0].new_start == 1
        assert hunks[1].old_start == 8 and hunks[1].new_count == 3
        assert hunks[0].lines[1] == ("-", "linha2")

    def test_parse_ignores_headers_and_markers(self) -> None:
        diff = (
            "diff --git a/x.txt b/x.txt\n"
            "--- a/x.txt\n"
            "+++ b/x.txt\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "\\ No newline at end of file\n"
            "+new\n"
            "\\ No newline at end of file\n"
        )
        ok, hunks, error = parse_unified_diff(diff)
        assert ok and error == ""
        assert len(hunks) == 1
        assert hunks[0].lines == [("-", "old"), ("+", "new")]
        assert hunks[0].last_add_no_newline is True

    def test_parse_invalid_hunk_header(self) -> None:
        ok, hunks, error = parse_unified_diff("@@ -abc +def @@\n")
        assert not ok and hunks == [] and "inválido" in error

    def test_parse_unexpected_line_inside_hunk(self) -> None:
        diff = "@@ -1,2 +1,2 @@\n linha1\n=== lixo ===\n"
        ok, _hunks, error = parse_unified_diff(diff)
        assert not ok and "inesperada" in error

    def test_parse_empty_diff_ok_no_hunks(self) -> None:
        ok, hunks, error = parse_unified_diff("")
        assert ok and error == ""
        assert hunks == []


class TestUnifiedDiffApply:
    """Aplicação de patches com round-trip difflib e casos extremos."""

    def test_roundtrip_cases(self) -> None:
        cases = [
            ("linha1\nlinha2\nlinha3\n", "linha1\nlinha2 MOD\nlinha3\nlinha4\n"),
            ("a\nb\nc\nd\ne\nf\ng\n", "a\nB\nc\nd\nE\nf\ng\n"),  # 2 hunks
            ("", "nova\nlinha\n"),                          # arquivo vazio
            ("", "x sem newline"),                          # vazio → sem quebra final
            ("só uma linha sem newline", "só uma linha sem newline editada"),
            ("a\nb sem newline", "a\nB sem newline"),
            ("x\ny\n", "x\n"),                              # remove até o fim
            ("alpha\nbeta\n", "alpha\nbeta\ngama\n"),       # append
            ("topo\nmeio\n", "novo topo\ntopo\nmeio\n"),
            ("com\nlinhas\ndemais\n", "com\nlinhas\n"),
            ("1\n2\n3\n4\n5\n", "1\n2\n3\n4\n5\n"),        # no-op (vazio)
        ]
        for old, new in cases:
            diff = generate_unified_patch(old, new)
            ok, out, error = apply_unified_diff(old, diff)
            assert ok, error
            assert out == new, (repr(old), repr(new), repr(out))

    def test_noop_diff_returns_same_content(self) -> None:
        content = "a\nb\n"
        ok, out, error = apply_unified_diff(content, "--- a/x\n+++ b/x\n")
        assert ok and error == ""
        assert out == content

    def test_apply_rejects_mismatched_hunk(self) -> None:
        diff = "@@ -1,2 +1,2 @@\n contexto ERRADO\n-linha1\n+linhaX\n"
        ok, _out, error = apply_unified_diff("linha1\nlinha2\n", diff)
        assert not ok
        assert "não aplica" in error

    def test_relocation_finds_hunk_after_drift(self) -> None:
        # Patch gerado contra um arquivo antigo; o arquivo atual ganhou
        # linhas antes — o aplicador deve relocalizar o hunk.
        old = "alfa\nbeta\ngama\ndelta\n"
        drifted = "PRE1\nPRE2\nalfa\nbeta\ngama\ndelta\n"
        new = "alfa\nbeta MOD\ngama\ndelta\n"
        diff = generate_unified_patch(old, new)
        ok, out, error = apply_unified_diff(drifted, diff)
        assert ok, error
        assert "beta MOD" in out and "PRE1" in out

    def test_hunks_out_of_order_rejected(self) -> None:
        # Segundo hunk declarado sobre a região já consumida pelo primeiro
        diff = (
            "@@ -2,2 +2,2 @@\n"
            " l2\n"
            "-l3\n"
            "@@ -2,2 +2,3 @@\n"
            " l2\n"
            "-l3\n"
            "+X\n"
        )
        ok, _out, error = apply_unified_diff("l1\nl2\nl3\nl4\nl5\n", diff)
        assert not ok
        assert "sobrepõe" in error

    def test_diff_stats_counts(self) -> None:
        diff = generate_unified_patch("a\nb\nc\n", "a\nb X\nc\nd\ne\n")
        added, removed = diff_stats(diff)
        assert added == 3 and removed == 1
        assert diff_stats("@@ -x @@") == (0, 0)  # inválido → 0/0

    def test_parse_hand_written_git_style_diff(self) -> None:
        diff = (
            "diff --git a/x.txt b/x.txt\n"
            "index 000..111\n"
            "--- a/x.txt\n"
            "+++ b/x.txt\n"
            "@@ -1,2 +1,3 @@\n"
            " um\n"
            "-dois\n"
            "+DOIS\n"
            "+tres\n"
        )
        ok, out, error = apply_unified_diff("um\ndois\n", diff)
        assert ok, error
        assert out == "um\nDOIS\ntres\n"


# ===========================================================================
# CoderEngine — construção e escopo
# ===========================================================================

class TestCoderEngineScope:
    """Root, escopo estrito e proteção de áreas internas."""

    def test_default_root_is_project(self) -> None:
        engine = CoderEngine()
        assert engine.root.is_dir()
        assert (engine.root / "core").is_dir()
        assert engine.sandbox_dir.name == ".od_sandbox"
        assert engine.backup_dir.name == ".od_backups"

    def test_invalid_root_raises(self, tmp_path: Path) -> None:
        with pytest.raises(CoderScopeError):
            CoderEngine(root=tmp_path / "nao_existe")

    def test_custom_dirs_under_root(self, tmp_path: Path) -> None:
        engine = CoderEngine(
            root=tmp_path,
            sandbox_dir="arena",
            backup_dir="cofre",
        )
        assert engine.sandbox_dir == (tmp_path / "arena").resolve()
        assert engine.backup_dir == (tmp_path / "cofre").resolve()

    @pytest.mark.asyncio
    async def test_target_outside_root_rejected(self, tmp_path: Path) -> None:
        engine = CoderEngine(root=tmp_path)
        outside = tmp_path.parent / "fora.txt"
        outside.write_text("x\n")
        result = await engine.apply_change(str(outside), content="y\n")
        assert result.status == "error"
        assert any("escopo" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_git_dir_protected(self, tmp_path: Path) -> None:
        engine = CoderEngine(root=tmp_path)
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("x\n")
        result = await engine.apply_change(".git/config", content="y\n")
        assert result.status == "error"
        assert any("protegido" in e for e in result.errors)
        assert (tmp_path / ".git" / "config").read_text() == "x\n"

    @pytest.mark.asyncio
    async def test_internal_dirs_protected(self, tmp_path: Path) -> None:
        engine = CoderEngine(root=tmp_path)
        result = await engine.apply_change(
            ".od_backups/hello.py.abc.bak", content="hack\n", create=True
        )
        assert result.status == "error"
        assert any("protegido" in e for e in result.errors)

    def test_dump(self, tmp_path: Path) -> None:
        engine = CoderEngine(root=tmp_path)
        dump = engine.dump()
        assert dump["root"] == str(tmp_path.resolve())
        assert dump["metrics"]["changes"] == 0
        assert dump["history"] == []


# ===========================================================================
# CoderEngine — pipeline completo (sandbox → testes → backup → promoção)
# ===========================================================================

@pytest.mark.asyncio
class TestCoderPipeline:
    """Pipeline feliz e seus artefatos."""

    async def _write_py(self, tmp_path: Path, name: str = "mod/hello.py") -> Path:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "def saudacao():\n    return 'oi'\n", encoding="utf-8"
        )
        return target

    async def test_apply_patch_promotes(self, tmp_path: Path) -> None:
        target = await self._write_py(tmp_path)
        engine = CoderEngine(root=tmp_path)
        patch = generate_unified_patch(
            target.read_text(encoding="utf-8"),
            "def saudacao(nome='mundo'):\n    return f'oi {nome}'\n",
        )
        result = await engine.apply_change("mod/hello.py", patch=patch)
        assert result.status == "ok"
        assert result.ok
        assert result.steps == {
            "sandbox": True, "test": True, "backup": True, "promote": True,
        }
        assert result.file == "mod/hello.py"
        assert result.backup_path
        assert "def saudacao(nome=" in target.read_text(encoding="utf-8")
        assert result.summary == "+2 -2 · sandbox→testes→backup→promoção ok"

    async def test_backup_holds_original(self, tmp_path: Path) -> None:
        target = await self._write_py(tmp_path)
        engine = CoderEngine(root=tmp_path)
        result = await engine.apply_change(
            "mod/hello.py", content="def novo():\n    pass\n"
        )
        assert result.status == "ok"
        backup = Path(result.backup_path)
        assert backup.exists()
        assert backup.read_text(encoding="utf-8").startswith("def saudacao")
        # backup versionado com o change_id
        assert result.change_id in backup.name

    async def test_full_content_replacement(self, tmp_path: Path) -> None:
        await self._write_py(tmp_path)
        engine = CoderEngine(root=tmp_path)
        result = await engine.apply_change(
            "mod/hello.py", content="VALOR = 42\n", message="constante"
        )
        assert result.status == "ok"
        assert result.message == "constante"
        assert (tmp_path / "mod/hello.py").read_text(encoding="utf-8") == "VALOR = 42\n"

    async def test_create_new_file(self, tmp_path: Path) -> None:
        engine = CoderEngine(root=tmp_path)
        result = await engine.apply_change(
            "mod/novo.py", content="X = 1\n", create=True
        )
        assert result.status == "ok"
        assert result.steps["backup"] is True  # nada a preservar — passo ok
        assert result.backup_path == ""
        assert (tmp_path / "mod/novo.py").read_text(encoding="utf-8") == "X = 1\n"

    async def test_create_without_create_flag_errors(self, tmp_path: Path) -> None:
        engine = CoderEngine(root=tmp_path)
        result = await engine.apply_change("mod/fantasma.py", content="X = 1\n")
        assert result.status == "error"
        assert any("não encontrado" in e for e in result.errors)

    async def test_sandbox_cleaned_after_success(self, tmp_path: Path) -> None:
        await self._write_py(tmp_path)
        engine = CoderEngine(root=tmp_path)
        result = await engine.apply_change("mod/hello.py", content="a = 1\n")
        assert result.status == "ok"
        staged = Path(result.staged_path)
        assert not staged.exists()  # área transitória removida
        assert result.steps["sandbox"] is True

    async def test_runner_sees_staged_file_only(self, tmp_path: Path) -> None:
        """A etapa de testes roda contra o artefato do sandbox — o original
        ainda NÃO foi alterado nesse ponto do pipeline."""
        target = await self._write_py(tmp_path)
        engine = CoderEngine(root=tmp_path)
        seen: dict[str, str] = {}

        def runner(*, staged_file: Path, original_file: Path, **_: object) -> bool:
            seen["staged"] = staged_file.read_text(encoding="utf-8")
            seen["original"] = original_file.read_text(encoding="utf-8")
            return True

        result = await engine.apply_change(
            "mod/hello.py",
            content="def patched():\n    return 1\n",
            runner=runner,
        )
        assert result.status == "ok"
        assert "patched" in seen["staged"]
        assert "saudacao" in seen["original"]  # original intocado durante testes
        assert target.read_text(encoding="utf-8") == "def patched():\n    return 1\n"

    async def test_generate_patch_method_roundtrip(self, tmp_path: Path) -> None:
        await self._write_py(tmp_path)
        engine = CoderEngine(root=tmp_path)
        patch = await engine.generate_patch(
            "mod/hello.py", "def tchau():\n    pass\n"
        )
        result = await engine.apply_change("mod/hello.py", patch=patch)
        assert result.status == "ok"
        assert (tmp_path / "mod/hello.py").read_text(encoding="utf-8") == (
            "def tchau():\n    pass\n"
        )

    async def test_noop_patch_not_allowed(self, tmp_path: Path) -> None:
        await self._write_py(tmp_path)
        engine = CoderEngine(root=tmp_path)
        result = await engine.apply_change("mod/hello.py", content="x\n")
        # muda o conteúdo — sem alteração textual seria apenas via patch vazio
        assert result.status == "ok"
        assert (tmp_path / "mod/hello.py").read_text() == "x\n"


# ===========================================================================
# CoderEngine — validações e falhas (arquivo original intacto)
# ===========================================================================

@pytest.mark.asyncio
class TestCoderFailures:
    """Toda falha deve deixar o arquivo real intocado."""

    async def _py(self, tmp_path: Path) -> Path:
        target = tmp_path / "mod.py"
        target.write_text("ok = 1\n", encoding="utf-8")
        return target

    async def test_patch_and_content_together_invalid(self, tmp_path: Path) -> None:
        await self._py(tmp_path)
        engine = CoderEngine(root=tmp_path)
        result = await engine.apply_change(
            "mod.py", patch="@@ -1 +1 @@\n-ok\n+novo\n", content="x\n"
        )
        assert result.status == "invalid"
        assert any("ambos" in e for e in result.errors)

    async def test_neither_patch_nor_content_invalid(self, tmp_path: Path) -> None:
        await self._py(tmp_path)
        engine = CoderEngine(root=tmp_path)
        result = await engine.apply_change("mod.py")
        assert result.status == "invalid"
        assert any("patch ou content" in e for e in result.errors)

    async def test_directory_target_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "pasta").mkdir()
        engine = CoderEngine(root=tmp_path)
        result = await engine.apply_change("pasta", content="x\n")
        assert result.status == "error"
        assert any("diretório" in e for e in result.errors)

    async def test_invalid_patch_aborts(self, tmp_path: Path) -> None:
        target = await self._py(tmp_path)
        engine = CoderEngine(root=tmp_path)
        result = await engine.apply_change(
            "mod.py", patch="@@ -1,5 +1,5 @@\n-inexistente\n+novo\n"
        )
        assert result.status == "invalid"
        assert any("não aplica" in e for e in result.errors)
        assert target.read_text(encoding="utf-8") == "ok = 1\n"  # intacto

    async def test_syntax_error_blocks_promotion(self, tmp_path: Path) -> None:
        target = await self._py(tmp_path)
        engine = CoderEngine(root=tmp_path)
        result = await engine.apply_change(
            "mod.py", content="def quebrada(:\n", message="ruim"
        )
        assert result.status == "test_failed"
        assert any("SyntaxError" in e for e in result.errors)
        assert result.test is not None and result.test.runner == "compile"
        assert result.steps["sandbox"] is True
        assert not result.steps.get("backup", False)
        assert not result.steps.get("promote", False)
        assert target.read_text(encoding="utf-8") == "ok = 1\n"  # intacto
        assert result.backup_path == ""  # sem backup antes da promoção

    async def test_non_py_file_skips_compile(self, tmp_path: Path) -> None:
        (tmp_path / "data.json").write_text('{"a": 1}\n', encoding="utf-8")
        engine = CoderEngine(root=tmp_path)
        result = await engine.apply_change(
            "data.json", content='{"a": 2}\n'
        )
        assert result.status == "ok"
        assert result.test.runner == "none"

    async def test_missing_file_error_status(self, tmp_path: Path) -> None:
        engine = CoderEngine(root=tmp_path)
        result = await engine.apply_change("sumido.txt", content="x\n")
        assert result.status == "error"


# ===========================================================================
# CoderEngine — etapa de testes (runner e comandos)
# ===========================================================================

@pytest.mark.asyncio
class TestCoderTestStep:
    """Runner injetado e test_command (subprocess) na etapa de testes."""

    async def _py(self, tmp_path: Path, content: str = "x = 1\n") -> Path:
        target = tmp_path / "alvo.py"
        target.write_text(content, encoding="utf-8")
        return target

    async def test_runner_false_blocks_promotion(self, tmp_path: Path) -> None:
        target = await self._py(tmp_path)
        engine = CoderEngine(root=tmp_path)
        result = await engine.apply_change(
            "alvo.py", content="x = 2\n", runner=lambda **_: False
        )
        assert result.status == "test_failed"
        assert any("reprovou" in e for e in result.errors)
        assert target.read_text(encoding="utf-8") == "x = 1\n"

    async def test_runner_raise_blocks_promotion(self, tmp_path: Path) -> None:
        target = await self._py(tmp_path)

        def boom(**_: object) -> bool:
            raise RuntimeError("teste quebrou")

        engine = CoderEngine(root=tmp_path)
        result = await engine.apply_change("alvo.py", content="x = 2\n", runner=boom)
        assert result.status == "test_failed"
        assert any("RuntimeError: teste quebrou" in e for e in result.errors)
        assert target.read_text(encoding="utf-8") == "x = 1\n"

    async def test_async_runner(self, tmp_path: Path) -> None:
        await self._py(tmp_path)
        engine = CoderEngine(root=tmp_path)

        async def verifica(*, staged_file: Path, **_: object) -> bool:
            return "x = 2" in staged_file.read_text(encoding="utf-8")

        result = await engine.apply_change("alvo.py", content="x = 2\n", runner=verifica)
        assert result.status == "ok"
        assert result.test.passed is True

    async def test_runner_returning_testoutcome(self, tmp_path: Path) -> None:
        await self._py(tmp_path)
        engine = CoderEngine(root=tmp_path)

        def retorna_outcome(**_: object) -> _TestOutcome:
            return _TestOutcome(passed=True, output="ok por outcome")

        result = await engine.apply_change("alvo.py", content="x = 3\n", runner=retorna_outcome)
        assert result.status == "ok"
        assert result.test.output == "ok por outcome"
        assert result.test.runner == "callable"

    async def test_runner_outcome_failed_blocks(self, tmp_path: Path) -> None:
        target = await self._py(tmp_path)
        engine = CoderEngine(root=tmp_path)

        def falha(**_: object) -> _TestOutcome:
            return _TestOutcome(passed=False, error="cobertura abaixo")

        result = await engine.apply_change("alvo.py", content="x = 4\n", runner=falha)
        assert result.status == "test_failed"
        assert any("cobertura abaixo" in e for e in result.errors)
        assert target.read_text(encoding="utf-8") == "x = 1\n"

    async def test_test_command_py_compile_pass(self, tmp_path: Path) -> None:
        await self._py(tmp_path, content="def fn():\n    return 1\n")
        engine = CoderEngine(root=tmp_path)
        result = await engine.apply_change(
            "alvo.py",
            content="def fn():\n    return 2\n",
            test_command=[sys.executable, "-m", "py_compile", "{file}"],
        )
        assert result.status == "ok"
        assert result.test.runner == "command"
        assert result.test.passed is True

    async def test_test_command_failure_blocks(self, tmp_path: Path) -> None:
        target = await self._py(tmp_path)
        engine = CoderEngine(root=tmp_path)
        result = await engine.apply_change(
            "alvo.py",
            content="def fn():\n    return 2\n",
            test_command=[sys.executable, "-c", "import sys; sys.exit(1)"],
        )
        assert result.status == "test_failed"
        assert any("exit 1" in e for e in result.errors)
        assert target.read_text(encoding="utf-8") == "x = 1\n"

    async def test_test_command_literal_string(self, tmp_path: Path) -> None:
        await self._py(tmp_path)
        engine = CoderEngine(root=tmp_path)
        # comando literal (str) sem shell — passa com exit 0
        result = await engine.apply_change(
            "alvo.py",
            content="y = 9\n",
            test_command=f"{sys.executable} -c 'import sys; sys.exit(0)'",
        )
        assert result.status == "ok"
        assert result.test.command.startswith(sys.executable)

    async def test_test_command_tokens_replaced(self, tmp_path: Path) -> None:
        await self._py(tmp_path)
        engine = CoderEngine(root=tmp_path)
        # token {file} aponta para o artefato de sandbox
        result = await engine.apply_change(
            "alvo.py",
            content="y = 9\n",
            test_command=[
                sys.executable, "-c",
                "import sys; assert open(sys.argv[1]).read() == 'y = 9\\n'",
                "{file}",
            ],
        )
        assert result.status == "ok"
        assert "{file}" not in result.test.command
        assert result.test.passed is True

    async def test_test_command_timeout(self, tmp_path: Path) -> None:
        await self._py(tmp_path)
        engine = CoderEngine(root=tmp_path)
        result = await engine.apply_change(
            "alvo.py",
            content="y = 9\n",
            test_command=[
                sys.executable, "-c", "import time; time.sleep(30)",
            ],
            test_timeout=0.3,
        )
        assert result.status == "test_failed"
        assert any("timeout" in e for e in result.errors)

    async def test_metrics_tests_counted(self, tmp_path: Path) -> None:
        await self._py(tmp_path)
        engine = CoderEngine(root=tmp_path)
        await engine.apply_change("alvo.py", content="y = 1\n", runner=lambda **_: True)
        await engine.apply_change("alvo.py", content="y = 2\n", runner=lambda **_: False)
        snap = engine.metrics.snapshot()
        assert snap["tests_run"] == 2
        assert snap["tests_passed"] == 1


# ===========================================================================
# CoderEngine — gate do Security Layer
# ===========================================================================

@pytest.mark.asyncio
class TestCoderSecurity:
    """Promoção validada pelo Security Layer (fail-closed em strict)."""

    def _strict(self, tmp_path: Path) -> SecurityManager:
        scope = ScopeEngine(allowed_roots=[tmp_path])
        return SecurityManager(mode="strict", scope_engine=scope)

    async def test_denied_role_blocks_promotion(self, tmp_path: Path) -> None:
        target = tmp_path / "mod.py"
        target.write_text("a = 1\n", encoding="utf-8")
        engine = CoderEngine(root=tmp_path, security=self._strict(tmp_path))
        result = await engine.apply_change(
            "mod.py", content="a = 2\n", role="ghost"
        )
        assert result.status == "denied"
        assert result.denied_by == "permission"
        # sandbox e testes rodaram; backup/promoção não
        assert result.steps["sandbox"] is True
        assert result.steps["test"] is True
        assert not result.steps.get("backup", False)
        assert not result.steps.get("promote", False)
        assert target.read_text(encoding="utf-8") == "a = 1\n"

    async def test_admin_role_allowed(self, tmp_path: Path) -> None:
        target = tmp_path / "mod.py"
        target.write_text("a = 1\n", encoding="utf-8")
        engine = CoderEngine(root=tmp_path, security=self._strict(tmp_path))
        result = await engine.apply_change("mod.py", content="a = 2\n", role="admin")
        assert result.status == "ok"
        assert target.read_text(encoding="utf-8") == "a = 2\n"

    async def test_compatibility_mode_flags_but_allows(self, tmp_path: Path) -> None:
        target = tmp_path / "mod.py"
        target.write_text("a = 1\n", encoding="utf-8")
        security = SecurityManager(mode="compatibility")
        engine = CoderEngine(root=tmp_path, security=security)
        result = await engine.apply_change(
            "mod.py", content="a = 3\n", role="ghost"
        )
        assert result.status == "ok"
        assert target.read_text(encoding="utf-8") == "a = 3\n"

    async def test_default_role_from_engine(self, tmp_path: Path) -> None:
        target = tmp_path / "mod.py"
        target.write_text("a = 1\n", encoding="utf-8")
        # role padrão "coder" é desconhecida → negada em strict
        engine = CoderEngine(root=tmp_path, security=self._strict(tmp_path))
        result = await engine.apply_change("mod.py", content="a = 4\n")
        assert result.status == "denied"

    async def test_no_security_manager_bypasses_gate(self, tmp_path: Path) -> None:
        target = tmp_path / "mod.py"
        target.write_text("a = 1\n", encoding="utf-8")
        engine = CoderEngine(root=tmp_path)  # sem security
        result = await engine.apply_change("mod.py", content="a = 5\n", role="ghost")
        assert result.status == "ok"


# ===========================================================================
# CoderEngine — Event Bus
# ===========================================================================

@pytest.mark.asyncio
class TestCoderEvents:
    """Eventos coder.started / coder.completed no bus."""

    async def _engine_with_bus(self, tmp_path: Path) -> tuple[CoderEngine, EventBus, list]:
        bus = EventBus()
        await bus.start()
        seen: list[dict[str, object]] = []

        async def handler(event: object) -> None:
            seen.append({"topic": getattr(event, "topic"), "data": getattr(event, "data")})

        bus.subscribe_handler("coder.*", handler)
        engine = CoderEngine(root=tmp_path, event_bus=bus)
        return engine, bus, seen

    async def test_success_publishes_started_and_completed(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        engine, bus, seen = await self._engine_with_bus(tmp_path)
        try:
            await engine.apply_change("a.py", content="x = 2\n")
            assert [e["topic"] for e in seen] == ["coder.started", "coder.completed"]
            completed = seen[-1]["data"]
            assert completed["status"] == "ok"
            assert completed["file"] == "a.py"
        finally:
            await bus.stop()

    async def test_failure_still_publishes_completed(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        engine, bus, seen = await self._engine_with_bus(tmp_path)
        try:
            await engine.apply_change("a.py", content="def quebrada(:\n")
            assert seen[-1]["topic"] == "coder.completed"
            assert seen[-1]["data"]["status"] == "test_failed"
        finally:
            await bus.stop()

    async def test_bus_not_running_is_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        bus = EventBus()  # nunca iniciado
        engine = CoderEngine(root=tmp_path, event_bus=bus)
        result = await engine.apply_change("a.py", content="x = 2\n")
        assert result.status == "ok"  # publicação best-effort não quebra


# ===========================================================================
# CoderEngine — métricas, trilha e dump
# ===========================================================================

@pytest.mark.asyncio
class TestCoderMetricsHistory:
    """Métricas e trilha recente de mudanças."""

    async def test_metrics_after_mixed_runs(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        engine = CoderEngine(root=tmp_path)
        await engine.apply_change("a.py", content="x = 2\n")                       # ok
        await engine.apply_change("a.py", content="def quebrada(:\n")              # test_failed
        await engine.apply_change("a.py", patch="@@ -9 +9 @@\n-inexistente\n+x\n")  # invalid
        await engine.apply_change("sumido.txt", content="x\n")                     # error
        snap = engine.metrics.snapshot()
        assert snap["changes"] == 4
        assert snap["ok"] == 1
        assert snap["test_failed"] == 1
        assert snap["invalid"] == 1
        assert snap["errors"] == 1
        assert snap["backups_created"] == 1
        assert snap["avg_duration_ms"] >= 0

    async def test_history_recent_first_and_trimmed(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        engine = CoderEngine(root=tmp_path, history_size=2)
        await engine.apply_change("a.py", content="x = 2\n")
        await engine.apply_change("a.py", content="x = 3\n")
        await engine.apply_change("a.py", content="x = 4\n")
        history = engine.history
        assert len(history) == 2
        assert history[0]["status"] == "ok"
        assert history[1]["status"] == "ok"

    async def test_history_entry_shape(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        engine = CoderEngine(root=tmp_path)
        result = await engine.apply_change("a.py", content="x = 2\n", message="trocou")
        entry = engine.history[0]
        assert entry["change_id"] == result.change_id
        assert entry["file"] == "a.py"
        assert entry["message"] == "trocou"
        assert entry["steps"]["promote"] is True
        assert "ts" in entry and entry["duration"] >= 0

    async def test_result_to_dict(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        engine = CoderEngine(root=tmp_path)
        result = await engine.apply_change("a.py", content="x = 2\n")
        data = result.to_dict()
        assert data["status"] == "ok"
        assert isinstance(result, CoderResult)
        assert result.duration >= 0
        assert result.finished_at is not None

    async def test_dump_includes_metrics(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        engine = CoderEngine(root=tmp_path)
        await engine.apply_change("a.py", content="x = 2\n")
        dump = engine.dump()
        assert dump["security_enabled"] is False
        assert dump["metrics"]["ok"] == 1
        assert len(dump["history"]) == 1
