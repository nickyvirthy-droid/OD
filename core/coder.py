"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/coder.py
Descrição: Coder Engine — modificação segura de código com pipeline
           sandbox → testes → backup → promoção. Aplica patches unificados
           ou conteúdo completo em arquivos dentro de um escopo estrito,
           validando (compile + testes opcionais) em sandbox ANTES de tocar
           o arquivo real, com backup atômico e promoção atômica.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime core/coder.py (pipeline sandbox → patch → validação →
    backup → promoção)
  - OMEGADRAKON_SPEC.md §7 (Security Boundaries — execução mediada pelo
    Security Layer, escopo estrito §7.1)
  - OMEGADRAKON_SPEC.md §7.2 (proibição de operações destrutivas sem
    quarentena/aprovação)
  - ROADMAP_ABSORCAO.md Fase 4, item 4.1 (depende de Security + Workflows)

Architecture:
    Uma mudança de código (change) é expressa por um PATCH unificado
    (diff -u / difflib.unified_diff) ou pelo CONTENT completo do arquivo.
    O CoderEngine executa o pipeline em 4 etapas, todas sem efeito no
    arquivo original até a última:

      1. SANDBOX  — o arquivo original é espelhado em um diretório isolado
                    sob o root e o patch é aplicado apenas na cópia
                    (código real intocado);
      2. TESTES   — validação estática (compile syntax check para .py) e,
                    quando configurado, um runner/test_command executado
                    contra o artefato de sandbox;
      3. BACKUP   — o original é copiado para o diretório de backups
                    (versionado por change_id) ANTES de qualquer escrita;
      4. PROMOÇÃO — o conteúdo validado substitui o original via escrita
                    atômica (temp + os.replace).

    O escopo é estrito (spec §7.1): todo caminho deve resolver dentro do
    root do engine; diretórios internos (sandbox/backups) e .git são
    protegidos. O gate do Security Layer (opcional) é consultado na etapa
    de promoção (action "coder.promote") — fail-closed quando o manager
    rejeita em modo strict. Eventos "coder.started"/"coder.completed" são
    publicados no Event Bus (best-effort), e cada execução gera métricas,
    trilha recente e logs NICKY.

Usage:
    from core.coder import CoderEngine

    engine = CoderEngine(root="/home/alex/OmegaDrakon")

    result = await engine.apply_change(
        "core/logger.py",
        patch="@@ -1,2 +1,3 @@\\n\"\"\"\\n+# nova linha\\n\"\"\"\\n",
        message="Adiciona comentário",
    )
    result.status      # "ok" | "invalid" | "test_failed" | "denied" | "error"
    result.backup_path # backup do original criado antes da promoção
"""

from __future__ import annotations

import asyncio
import difflib
import inspect
import os
import re
import shlex
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Union

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.core.coder")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

DEFAULT_SANDBOX_DIR = ".od_sandbox"
DEFAULT_BACKUP_DIR = ".od_backups"
DEFAULT_HISTORY_SIZE = 200

# Status de uma mudança
STATUS_OK = "ok"
STATUS_INVALID = "invalid"
STATUS_TEST_FAILED = "test_failed"
STATUS_DENIED = "denied"
STATUS_ERROR = "error"
RESULT_STATUSES = (STATUS_OK, STATUS_INVALID, STATUS_TEST_FAILED, STATUS_DENIED, STATUS_ERROR)

# Prefixos relativos protegidos dentro do root (nunca editáveis pelo coder)
PROTECTED_REL_PREFIXES = (".git",)

_HUNK_HEADER_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$"
)


# ---------------------------------------------------------------------------
# Exceções
# ---------------------------------------------------------------------------


class CoderError(Exception):
    """Erro base do Coder Engine."""


class CoderScopeError(CoderError, PermissionError):
    """Caminho fora do escopo estrito do Coder Engine (spec §7.1)."""


class CoderUsageError(CoderError, ValueError):
    """Uso inválido da API (ex: patch e content simultâneos)."""


class CoderPatchError(CoderError, ValueError):
    """Patch unificado inválido ou inaplicável."""


class _ChangeAborted(Exception):
    """Controle interno: aborta a mudança e segue para a finalização comum.

    Attributes:
        status:  Status final da mudança (invalid/test_failed/denied/error).
        errors:  Mensagens de erro a registrar no resultado.
    """

    def __init__(self, status: str, errors: Optional[list[str]] = None) -> None:
        super().__init__(status)
        self.status = status
        self.errors = list(errors or [])


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class TestOutcome:
    """Resultado da etapa de testes/validação de uma mudança.

    Attributes:
        passed:      True se os testes passaram (gate de promoção).
        runner:      Origem do teste ("compile", "callable", "command").
        command:     Comando/callable usado (para diagnóstico).
        output:      Saída capturada do teste (stdout+stderr).
        error:       Mensagem de erro (quando não passou por exceção).
        duration_ms: Duração da execução do teste.
    """

    passed: bool = False
    runner: str = ""
    command: str = ""
    output: str = ""
    error: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "runner": self.runner,
            "command": self.command,
            "output": self.output,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 3),
        }


@dataclass(slots=True)
class CoderResult:
    """Resultado padronizado de uma mudança de código.

    Attributes:
        change_id:    Identificador único da mudança (uuid curto).
        file:         Caminho RELATIVO do arquivo modificado.
        status:       ok | invalid | test_failed | denied | error.
        steps:        Etapas executadas com sucesso (sandbox/test/backup/promote).
        staged_path:  Caminho do artefato de sandbox (área já limpa ao final).
        backup_path:  Caminho do backup do original (quando criado).
        test:         Resultado da etapa de testes (None se não executada).
        summary:      Resumo legível (ex: "+2 -1 · promoção ok").
        errors:       Lista de erros detalhados.
        denied_by:    Camada do Security Layer que negou (quando denied).
        message:      Mensagem/descrição da mudança.
        started_at / finished_at / duration: temporização.
    """

    change_id: str
    file: str
    status: str = STATUS_OK
    steps: dict[str, bool] = field(default_factory=dict)
    staged_path: str = ""
    backup_path: str = ""
    test: Optional[TestOutcome] = None
    summary: str = ""
    errors: list[str] = field(default_factory=list)
    denied_by: str = ""
    message: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    duration: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    def finish(self) -> None:
        """Finaliza a temporização (chamado pelo engine)."""
        self.finished_at = time.time()
        self.duration = self.finished_at - self.started_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "file": self.file,
            "status": self.status,
            "steps": dict(self.steps),
            "staged_path": self.staged_path,
            "backup_path": self.backup_path,
            "test": self.test.to_dict() if self.test else None,
            "summary": self.summary,
            "errors": list(self.errors),
            "denied_by": self.denied_by,
            "message": self.message,
            "duration": round(self.duration, 6),
        }


@dataclass(slots=True)
class CoderMetrics:
    """Métricas agregadas do Coder Engine."""

    changes: int = 0
    ok: int = 0
    invalid: int = 0
    test_failed: int = 0
    denied: int = 0
    errors: int = 0
    backups_created: int = 0
    tests_run: int = 0
    tests_passed: int = 0
    total_duration_ms: float = 0.0

    @property
    def avg_duration_ms(self) -> float:
        if self.changes == 0:
            return 0.0
        return round(self.total_duration_ms / self.changes, 3)

    def snapshot(self) -> dict[str, Any]:
        return {
            "changes": self.changes,
            "ok": self.ok,
            "invalid": self.invalid,
            "test_failed": self.test_failed,
            "denied": self.denied,
            "errors": self.errors,
            "backups_created": self.backups_created,
            "tests_run": self.tests_run,
            "tests_passed": self.tests_passed,
            "avg_duration_ms": self.avg_duration_ms,
        }


# ---------------------------------------------------------------------------
# Unified diff — parse, contagem e aplicação
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class _Hunk:
    """Um hunk @@ -a,b +c,d @@ de um diff unificado."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[tuple[str, str]]  # (op, texto) — op em " ", "-", "+"
    last_add_no_newline: bool = False  # marcador \\ No newline após o último '+'


def parse_unified_diff(diff: str) -> tuple[bool, list[_Hunk], str]:
    """Parseia um diff unificado em hunks aplicáveis.

    Cabeçalhos (---/+++), marcadores "\\ No newline at end of file" e
    textos de seção após @@ são tolerados/ignorados.

    Returns:
        (ok, hunks, erro).
    """
    hunks: list[_Hunk] = []
    current: Optional[_Hunk] = None

    for raw in diff.splitlines(keepends=False):
        line = raw.rstrip("\r")
        if line.startswith("@@ "):
            match = _HUNK_HEADER_RE.match(line)
            if match is None:
                return False, [], f"cabeçalho de hunk inválido: {line!r}"
            old_start = int(match.group(1))
            old_count = int(match.group(2) or "1")
            new_start = int(match.group(3))
            new_count = int(match.group(4) or "1")
            current = _Hunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                lines=[],
            )
            hunks.append(current)
            continue

        if current is None:
            # Fora de hunk (---/+++/linhas soltas): ignora
            continue

        if line.startswith("\\ No newline"):
            # Marcador: a entrada anterior do hunk não termina com quebra.
            # Relevante para a última linha ADICIONADA (define se o arquivo
            # resultante termina sem newline quando criado do zero).
            if current and current.lines and current.lines[-1][0] == "+":
                current.last_add_no_newline = True
            continue

        if line.startswith((" ", "-", "+")):
            current.lines.append((line[0], line[1:]))
            continue

        # Linha inesperada dentro de um hunk — aborta com contexto
        return False, [], (
            f"linha inesperada dentro do hunk {current.old_start}: {line!r}"
        )

    return True, hunks, ""


def _count_hunk_changes(hunk: _Hunk) -> tuple[int, int]:
    """Conta linhas adicionadas/removidas de um hunk."""
    added = sum(1 for op, _ in hunk.lines if op == "+")
    removed = sum(1 for op, _ in hunk.lines if op == "-")
    return added, removed


def _hunk_verifies_at(lines: list[str], hunk: _Hunk, cand: int) -> bool:
    """True se todas as linhas de contexto/remoção do hunk casam em `cand`."""
    idx = cand
    for op, text in hunk.lines:
        if op in (" ", "-"):
            if idx >= len(lines) or lines[idx] != text:
                return False
            idx += 1
    return True


def _split_content_lines(content: str) -> tuple[list[str], bool]:
    """Divide conteúdo em linhas de TEXTO PURO + flag de quebra final.

    A aplicação compara texto puro (sem terminadores); a quebra de linha
    do final do arquivo é preservada conforme o original.
    """
    if content == "":
        return [], False
    lines = content.split("\n")
    trailing_nl = content.endswith("\n")
    if trailing_nl:
        lines.pop()  # remove o elemento vazio final
    return lines, trailing_nl


def _terminated_lines(content: str) -> list[str]:
    """Linhas para o difflib — todas terminadas em \\n (sem artefatos de
    merge de diffs gerados quando a última linha não tem quebra)."""
    lines = content.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    return lines


def apply_unified_diff(content: str, diff: str) -> tuple[bool, str, str]:
    """Aplica um diff unificado a um conteúdo textual.

    Estratégia: posição exata declarada no hunk primeiro; se o contexto
    não bater (arquivo derivou), procura a próxima posição compatível a
    partir do ponto de consumo atual (relocation, como `patch --fuzz`).

    Returns:
        (ok, novo_conteúdo, erro).
    """
    ok, hunks, error = parse_unified_diff(diff)
    if not ok:
        return False, "", error
    if not hunks:
        # Diff vazio/cabeçalhos apenas = sem alterações (no-op)
        return True, content, ""

    lines, trailing_nl = _split_content_lines(content)
    out: list[str] = []
    pos = 0

    for hunk in hunks:
        declared = hunk.old_start - 1
        start = declared if declared >= 0 else 0

        # Encaixe: posição declarada ou, se derivou, a próxima compatível
        matched: Optional[int] = None
        if hunk.old_count == 0 or _hunk_verifies_at(lines, hunk, start):
            matched = start
        else:
            for cand in range(max(start, pos) + 1, len(lines)):
                if _hunk_verifies_at(lines, hunk, cand):
                    matched = cand
                    break

        if matched is None:
            expected = hunk.lines[0][1] if hunk.lines else ""
            got = lines[start] if start < len(lines) else "<eof>"
            return False, "", (
                f"hunk @@ -{hunk.old_start} +{hunk.new_start} @@ não "
                f"aplica: esperado {expected!r}, encontrado {got!r} "
                f"(linha {start + 1})"
            )

        if matched < pos:
            return False, "", (
                f"hunk @@ -{hunk.old_start} +{hunk.new_start} @@ sobrepõe "
                "conteúdo já consumido (diff fora de ordem)"
            )

        # Emite o trecho intocado até o hunk, depois processa linha a linha
        out.extend(lines[pos:matched])
        idx = matched
        for op, text in hunk.lines:
            if op in (" ", "-"):
                # Contexto é reemitido; remoções são descartadas
                if op == " ":
                    out.append(lines[idx])
                idx += 1
            else:  # op == "+"
                out.append(text)
        pos = idx

    out.extend(lines[pos:])

    # Reconstrói preservando a quebra final do arquivo original. Arquivo
    # original vazio assume texto terminado em quebra, a menos que o marcador
    # "\\ No newline" indique o contrário para o conteúdo criado.
    if not out:
        return True, "", ""
    if content == "":
        result = "\n".join(out)
        if not hunks[-1].last_add_no_newline:
            result += "\n"
        return True, result, ""
    return True, "\n".join(out) + ("\n" if trailing_nl else ""), ""


def generate_unified_patch(
    old_content: str,
    new_content: str,
    *,
    fromfile: str = "original",
    tofile: str = "patched",
) -> str:
    """Gera um diff unificado entre dois conteúdos (difflib stdlib).

    As linhas alimentam o difflib sempre terminadas em \\n, evitando o
    artefato de merge de entradas quando a última linha do arquivo não
    tem quebra. O diff gerado é compatível com apply_unified_diff.
    """
    old_lines = _terminated_lines(old_content)
    new_lines = _terminated_lines(new_content)
    diff = "".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=fromfile,
            tofile=tofile,
        )
    )
    # Quando o conteúdo novo não termina em quebra de linha e o diff termina
    # numa adição, emite o marcador para que o round-trip seja exato.
    if new_content and not new_content.endswith("\n") and diff:
        last_physical = diff.rstrip("\n").splitlines()[-1]
        if last_physical.startswith("+"):
            diff += "\\ No newline at end of file\n"
    return diff


def diff_stats(diff: str) -> tuple[int, int]:
    """Conta linhas adicionadas/removidas de um diff (+x, -y)."""
    ok, hunks, _ = parse_unified_diff(diff)
    if not ok:
        return 0, 0
    added = sum(_count_hunk_changes(h)[0] for h in hunks)
    removed = sum(_count_hunk_changes(h)[1] for h in hunks)
    return added, removed


# ---------------------------------------------------------------------------
# CoderEngine
# ---------------------------------------------------------------------------

# Assinatura do runner: callable(relpath, staged_file, sandbox_dir,
# original_file) -> bool | TestOutcome | None
RunnerFn = Callable[..., Union[bool, TestOutcome, None, Any]]


class CoderEngine:
    """Engine de modificação segura de código (sandbox → testes → backup → promoção).

    Attributes:
        root:          Raiz estrita do workspace editável (spec §7.1).
        sandbox_dir:   Diretório de sandbox sob o root (transiente).
        backup_dir:    Diretório de backups sob o root (persistente).
        security:      SecurityManager opcional — gate de "coder.promote".
        event_bus:     EventBus opcional — publica coder.started/completed.
        default_role:  Papel usado no gate de segurança quando não passado.
    """

    def __init__(
        self,
        *,
        root: Optional[Union[str, Path]] = None,
        sandbox_dir: Union[str, Path] = DEFAULT_SANDBOX_DIR,
        backup_dir: Union[str, Path] = DEFAULT_BACKUP_DIR,
        security: Optional[Any] = None,
        event_bus: Optional[Any] = None,
        default_role: str = "coder",
        history_size: int = DEFAULT_HISTORY_SIZE,
    ) -> None:
        if root is None:
            # Raiz padrão: diretório do projeto (pai de core/)
            root = Path(__file__).resolve().parent.parent
        resolved_root = Path(root).expanduser().resolve()
        if not resolved_root.is_dir():
            raise CoderScopeError(
                f"Root do Coder Engine não é diretório: {resolved_root}"
            )

        self.root = resolved_root
        self.sandbox_dir = resolved_root / sandbox_dir
        self.backup_dir = resolved_root / backup_dir
        self.security = security
        self.event_bus = event_bus
        self.default_role = default_role
        self._history_size = max(1, history_size)

        self._history: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        self._metrics = CoderMetrics()

    # -- Propriedades --------------------------------------------------------

    @property
    def metrics(self) -> CoderMetrics:
        return self._metrics

    @property
    def history(self) -> list[dict[str, Any]]:
        """Trilha recente de mudanças (mais recentes primeiro)."""
        return list(reversed(self._history))

    # -- API pública ---------------------------------------------------------

    async def apply_change(
        self,
        file: Union[str, Path],
        *,
        patch: Optional[str] = None,
        content: Optional[str] = None,
        message: str = "",
        create: bool = False,
        runner: Optional[RunnerFn] = None,
        test_command: Optional[Union[str, list[str]]] = None,
        test_timeout: float = 60.0,
        role: Optional[str] = None,
        session_id: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> CoderResult:
        """Executa uma mudança de código no pipeline completo.

        Args:
            file:         Caminho do arquivo (absoluto ou relativo ao root).
            patch:        Diff unificado a aplicar no conteúdo atual.
            content:      Conteúdo COMPLETO novo do arquivo (alternativa ao patch).
            message:      Descrição livre da mudança.
            create:       True permite criar o arquivo (exige content=).
            runner:       Callable sync/async executado na etapa de testes:
                          runner(relpath, staged_file, sandbox_dir,
                          original_file) → bool | TestOutcome | None
                          (False/None = reprovou).
            test_command: Comando a executar na etapa de testes (cwd=sandbox).
                          Tokens {file}, {sandbox}, {root}, {relpath} são
                          substituídos; aceita str ou lista de args.
            test_timeout: Timeout em segundos do comando de teste.
            role:         Papel do solicitante no gate de segurança.
            session_id:   Sessão para auditoria/logs.
            metadata:     Metadados extras para o gate de segurança.

        Returns:
            CoderResult — o arquivo real só é alterado se todas as etapas
            passarem (sandbox → testes → backup → promoção).
        """
        started = time.time()
        change_id = uuid.uuid4().hex[:12]
        result = CoderResult(change_id=change_id, file="", message=message)

        try:
            # Resolução com escopo estrito (spec §7.1)
            target, rel = self._resolve_target(file)
            result.file = rel
        except CoderError as exc:
            self._metrics.changes += 1
            return await self._finish(
                result, started, STATUS_ERROR, errors=[str(exc)]
            )

        self._metrics.changes += 1
        await self._publish_event(
            "coder.started",
            change_id=change_id,
            file=rel,
            message=message,
        )

        # ------------------------------------------------------------------
        # Pipeline: sandbox → testes → backup → promoção
        # ------------------------------------------------------------------
        sandbox_root = self.sandbox_dir / change_id
        try:
            if patch is not None and content is not None:
                raise _ChangeAborted(
                    STATUS_INVALID, ["informe patch OU content, não ambos"]
                )
            if patch is None and content is None:
                raise _ChangeAborted(
                    STATUS_INVALID, ["informe patch ou content"]
                )

            exists = target.exists()
            if not exists and not create:
                raise _ChangeAborted(
                    STATUS_ERROR, [f"arquivo não encontrado: {rel}"]
                )
            if exists and target.is_dir():
                raise _ChangeAborted(STATUS_ERROR, [f"alvo é diretório: {rel}"])

            # Conteúdo patcheado — calculado em memória, nada em disco ainda
            original = "" if not exists else self._read_target(target)
            patched = self._compute_patched(original, patch, content)

            result.summary = "sem alterações (no-op)" if patched == original else ""

            # 1. SANDBOX — materializa o artefato em área isolada
            staged = sandbox_root / rel
            if not await self._stage(staged, patched):
                raise _ChangeAborted(STATUS_ERROR, ["falha ao materializar sandbox"])
            result.steps["sandbox"] = True
            result.staged_path = str(staged)

            try:
                # 2. TESTES — compile estático + runner/comando opcional
                outcome = await self._run_tests(
                    rel=rel,
                    staged=staged,
                    sandbox_dir=sandbox_root,
                    original=target,
                    runner=runner,
                    test_command=test_command,
                    test_timeout=test_timeout,
                )
                result.test = outcome
                result.steps["test"] = outcome.passed
                if not outcome.passed:
                    raise _ChangeAborted(
                        STATUS_TEST_FAILED,
                        [outcome.error or f"testes reprovaram ({outcome.runner})"],
                    )

                # Gate de segurança — a ação real é escrever no original
                decision = self._security_check(
                    rel=rel,
                    target=target,
                    role=role,
                    session_id=session_id,
                    metadata=metadata,
                )
                if decision is not None and not decision.allowed:
                    result.denied_by = decision.denied_by or ""
                    raise _ChangeAborted(
                        STATUS_DENIED, list(decision.reasons) or ["negado"]
                    )

                # 3. BACKUP — preserva o original antes de qualquer escrita
                if exists:
                    backup_path = await self._backup(target, change_id)
                    if backup_path is None:
                        raise _ChangeAborted(
                            STATUS_ERROR, ["falha ao criar backup do original"]
                        )
                    result.backup_path = str(backup_path)
                    result.steps["backup"] = True
                    self._metrics.backups_created += 1
                else:
                    # Arquivo novo: nada a preservar
                    result.steps["backup"] = True

                # 4. PROMOÇÃO — escrita atômica no arquivo real
                if not self._promote(target, staged):
                    raise _ChangeAborted(
                        STATUS_ERROR, ["falha na promoção (arquivo intacto)"]
                    )
                result.steps["promote"] = True

                added, removed = diff_stats(patch) if patch else (0, 0)
                result.summary = (
                    f"+{added} -{removed} · sandbox→testes→backup→promoção ok"
                )
                log.audit(
                    "coder.promote",
                    session_id=session_id,
                    change_id=change_id,
                    file=rel,
                    status=STATUS_OK,
                )
                status = STATUS_OK
            finally:
                # Sandbox é área transitória — sempre limpa ao final
                self._cleanup_sandbox(sandbox_root)

            return await self._finish(result, started, status)
        except _ChangeAborted as abort:
            self._cleanup_sandbox(sandbox_root)
            return await self._finish(
                result, started, abort.status, errors=abort.errors
            )
        except Exception as exc:
            self._cleanup_sandbox(sandbox_root)
            log.crit(
                "Coder change failed",
                change_id=change_id,
                file=rel,
                error=f"{type(exc).__name__}: {exc}",
            )
            return await self._finish(
                result,
                started,
                STATUS_ERROR,
                errors=[f"{type(exc).__name__}: {exc}"],
            )

    async def generate_patch(
        self,
        file: Union[str, Path],
        new_content: str,
        *,
        fromfile: Optional[str] = None,
        tofile: Optional[str] = None,
    ) -> str:
        """Gera o diff unificado entre o conteúdo atual de `file` e `new_content`.

        Conveniência para produzir patches seguros (round-trip com apply).
        """
        _target, rel = self._resolve_target(file)
        target = self.root / rel
        original = ""
        if target.exists():
            original = target.read_text(encoding="utf-8")
        return generate_unified_patch(
            original,
            new_content,
            fromfile=fromfile or f"a/{rel}",
            tofile=tofile or f"b/{rel}",
        )

    # -- Etapas internas -----------------------------------------------------

    def _resolve_target(self, file: Union[str, Path]) -> tuple[Path, str]:
        """Resolve o alvo contra o root com escopo estrito.

        Raises:
            CoderScopeError: caminho fora do root ou área protegida.
        """
        raw = Path(file)
        candidate = raw if raw.is_absolute() else self.root / raw
        resolved = candidate.expanduser().resolve()

        try:
            rel = resolved.relative_to(self.root)
        except ValueError:
            raise CoderScopeError(
                f"arquivo fora do escopo do Coder Engine: {file} "
                f"(root: {self.root})"
            ) from None

        rel_parts = rel.parts
        if rel_parts and rel_parts[0] in PROTECTED_REL_PREFIXES:
            raise CoderScopeError(f"caminho protegido, não editável: {file}")

        # Diretórios internos do engine nunca são alvos de edição
        for internal in (self.sandbox_dir, self.backup_dir):
            internal_resolved = internal.expanduser().resolve()
            if internal_resolved == self.root:
                continue
            try:
                internal_rel = internal_resolved.relative_to(self.root)
            except ValueError:
                continue  # fora do root — irrelevante para o escopo
            if rel_parts[: len(internal_rel.parts)] == internal_rel.parts:
                raise CoderScopeError(
                    f"caminho protegido, não editável: {file}"
                )

        return resolved, str(rel)

    def _read_target(self, target: Path) -> str:
        """Lê o arquivo original (utf-8). Erro de leitura aborta a mudança."""
        try:
            return target.read_text(encoding="utf-8")
        except Exception as exc:
            raise _ChangeAborted(
                STATUS_ERROR,
                [f"falha ao ler {target.name}: {type(exc).__name__}: {exc}"],
            ) from exc

    @staticmethod
    def _compute_patched(
        original: str,
        patch: Optional[str],
        content: Optional[str],
    ) -> str:
        """Calcula o conteúdo novo (content completo ou patch aplicado)."""
        if content is not None:
            return content

        ok, patched, error = apply_unified_diff(original, patch or "")
        if not ok:
            added, removed = diff_stats(patch or "")
            raise _ChangeAborted(
                STATUS_INVALID,
                [f"patch inválido: {error}", f"+{added} -{removed} · rejeitado"],
            )
        return patched

    async def _stage(self, staged: Path, patched: str) -> bool:
        """Materializa o conteúdo patcheado no sandbox (isolado do original)."""
        try:
            staged.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(
                staged.write_text, patched, "utf-8"
            )
            log.info(
                "Coder sandbox staged",
                staged=str(staged),
                bytes=len(patched.encode("utf-8")),
            )
            return True
        except Exception as exc:
            log.crit(
                "Coder sandbox stage failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            return False

    async def _run_tests(
        self,
        *,
        rel: str,
        staged: Path,
        sandbox_dir: Path,
        original: Path,
        runner: Optional[RunnerFn],
        test_command: Optional[Union[str, list[str]]],
        test_timeout: float,
    ) -> TestOutcome:
        """Executa a etapa de testes: compile estático + runner/comando."""
        # Validação estática: arquivos .py devem compilar (syntax check)
        if rel.endswith(".py"):
            syntax_error = self._compile_check(staged)
            if syntax_error is not None:
                log.warn(
                    "Coder syntax check failed",
                    file=rel,
                    error=syntax_error,
                )
                return TestOutcome(
                    passed=False,
                    runner="compile",
                    error=f"SyntaxError: {syntax_error}",
                )

        if runner is not None:
            return await self._run_runner(
                rel=rel,
                staged=staged,
                sandbox_dir=sandbox_dir,
                original=original,
                runner=runner,
            )

        if test_command:
            return await self._run_command(
                test_command=test_command,
                sandbox_dir=sandbox_dir,
                staged=staged,
                timeout=test_timeout,
                rel=rel,
            )

        # Sem teste extra configurado — compilou = passou
        self._metrics.tests_run += 1
        self._metrics.tests_passed += 1
        return TestOutcome(
            passed=True,
            runner="compile" if rel.endswith(".py") else "none",
        )

    @staticmethod
    def _compile_check(path: Path) -> Optional[str]:
        """Syntax check de um arquivo .py. Retorna descrição do erro ou None."""
        try:
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
            return None
        except SyntaxError as exc:
            return f"{exc.msg} (linha {exc.lineno})"
        except Exception as exc:  # ex: erro de decode
            return f"{type(exc).__name__}: {exc}"

    async def _run_runner(
        self,
        *,
        rel: str,
        staged: Path,
        sandbox_dir: Path,
        original: Path,
        runner: RunnerFn,
    ) -> TestOutcome:
        """Invoca o runner injetado (sync ou async) contra o artefato staged."""
        started = time.time()
        self._metrics.tests_run += 1
        outcome = TestOutcome(
            runner="callable", command=getattr(runner, "__name__", "runner")
        )
        try:
            value = runner(
                relpath=rel,
                staged_file=staged,
                sandbox_dir=sandbox_dir,
                original_file=original,
            )
            if inspect.isawaitable(value):
                value = await value
        except Exception as exc:
            outcome.error = f"{type(exc).__name__}: {exc}"
            outcome.duration_ms = (time.time() - started) * 1000.0
            log.warn(
                "Coder runner raised",
                file=rel,
                error=outcome.error,
            )
            return outcome

        outcome.duration_ms = (time.time() - started) * 1000.0
        if isinstance(value, TestOutcome):
            outcome = value
            outcome.runner = "callable"
            outcome.command = getattr(runner, "__name__", "runner")
            outcome.duration_ms = (time.time() - started) * 1000.0
        elif value is True:
            outcome.passed = True
            self._metrics.tests_passed += 1
        else:
            # False/None/0 = reprovado (fail-closed)
            outcome.error = "runner reprovou a mudança (retorno falso)"
        log.info(
            "Coder runner finished",
            file=rel,
            passed=outcome.passed,
        )
        return outcome

    async def _run_command(
        self,
        *,
        test_command: Union[str, list[str]],
        sandbox_dir: Path,
        staged: Path,
        timeout: float,
        rel: str,
    ) -> TestOutcome:
        """Executa um comando de teste com cwd no sandbox (subprocess)."""
        started = time.time()
        self._metrics.tests_run += 1
        argv = self._render_command(
            test_command, sandbox_dir=sandbox_dir, staged=staged
        )
        outcome = TestOutcome(runner="command", command=" ".join(argv))
        log.info(
            "Coder test command running",
            file=rel,
            command=outcome.command,
        )
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(sandbox_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            outcome.error = f"timeout após {timeout}s"
            outcome.duration_ms = (time.time() - started) * 1000.0
            log.warn(
                "Coder test command timed out",
                timeout_s=timeout,
            )
            if proc is not None:
                try:
                    proc.kill()
                except ProcessLookupError:  # pragma: no cover
                    pass
                await proc.wait()
            return outcome
        except Exception as exc:
            outcome.error = f"{type(exc).__name__}: {exc}"
            outcome.duration_ms = (time.time() - started) * 1000.0
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:  # pragma: no cover
                    pass
                await proc.wait()
            return outcome

        outcome.duration_ms = (time.time() - started) * 1000.0
        output = (stdout_b or b"").decode("utf-8", errors="replace")
        errout = (stderr_b or b"").decode("utf-8", errors="replace")
        outcome.output = (output + errout).strip()
        if proc.returncode == 0:
            outcome.passed = True
            self._metrics.tests_passed += 1
        else:
            outcome.error = f"comando falhou (exit {proc.returncode})"
        log.info(
            "Coder test command finished",
            file=rel,
            passed=outcome.passed,
            exit_code=proc.returncode,
        )
        return outcome

    def _render_command(
        self,
        command: Union[str, list[str]],
        *,
        sandbox_dir: Path,
        staged: Path,
    ) -> list[str]:
        """Renderiza o comando, substituindo tokens por caminhos reais."""
        tokens = {
            "{file}": str(staged),
            "{sandbox}": str(sandbox_dir),
            "{root}": str(self.root),
            "{relpath}": str(staged.relative_to(sandbox_dir)),
        }
        if isinstance(command, str):
            rendered = command
            for token, value in tokens.items():
                rendered = rendered.replace(token, value)
            return shlex.split(rendered)
        argv = []
        for arg in command:
            for token, value in tokens.items():
                arg = arg.replace(token, value)
            argv.append(arg)
        return argv

    def _security_check(
        self,
        *,
        rel: str,
        target: Path,
        role: Optional[str],
        session_id: str,
        metadata: Optional[dict[str, Any]],
    ) -> Optional[Any]:
        """Gate do Security Layer na promoção (None = sem manager)."""
        if self.security is None:
            return None
        decision = self.security.check(
            action="coder.promote",
            params={"file": rel},
            role=role or self.default_role,
            source="coder_engine",
            session_id=session_id,
            paths=[str(target)],
            metadata=dict(metadata or {}, operation="write"),
        )
        if not decision.allowed:
            log.crit(
                "Coder promote denied by security",
                file=rel,
                role=role or self.default_role,
                denied_by=decision.denied_by or "-",
            )
        return decision

    async def _backup(self, target: Path, change_id: str) -> Optional[Path]:
        """Copia o original para o diretório de backups (versionado)."""
        try:
            backup = self.backup_dir / f"{target.name}.{change_id}.bak"
            backup.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.copy2, target, backup)
            log.info(
                "Coder backup created",
                change_id=change_id,
                file=str(target),
                backup=str(backup),
            )
            return backup
        except Exception as exc:
            log.crit(
                "Coder backup failed",
                change_id=change_id,
                file=str(target),
                error=f"{type(exc).__name__}: {exc}",
            )
            return None

    def _promote(self, target: Path, staged: Path) -> bool:
        """Promove o artefato validado ao arquivo real (escrita atômica).

        Nunca substitui o original sem backup prévio — responsabilidade do
        pipeline chamar _backup antes.
        """
        tmp_path: Optional[Path] = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = target.with_name(
                f".{target.name}.{uuid.uuid4().hex[:8]}.tmp"
            )
            shutil.copy2(staged, tmp_path)
            os.replace(tmp_path, target)
            log.info("Coder promote ok", file=str(target))
            return True
        except Exception as exc:
            log.crit(
                "Coder promote failed",
                file=str(target),
                error=f"{type(exc).__name__}: {exc}",
            )
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:  # pragma: no cover
                    pass
            return False

    @staticmethod
    def _cleanup_sandbox(sandbox_root: Path) -> None:
        """Remove a área transitória do sandbox (best-effort)."""
        try:
            if not sandbox_root.exists():
                return
            for child in sandbox_root.rglob("*"):
                if child.is_file():
                    child.unlink(missing_ok=True)
            for child in sorted(
                (p for p in sandbox_root.rglob("*") if p.is_dir()),
                reverse=True,
            ):
                try:
                    child.rmdir()
                except OSError:  # pragma: no cover — diretório não vazio
                    pass
            sandbox_root.rmdir()
        except Exception as exc:
            log.warn(
                "Coder sandbox cleanup incomplete",
                error=f"{type(exc).__name__}: {exc}",
            )

    # -- Event Bus (best-effort) ---------------------------------------------

    async def _publish_event(self, topic: str, **data: Any) -> None:
        """Publica um evento no bus (nunca quebra a mudança)."""
        if self.event_bus is None or not getattr(
            self.event_bus, "running", False
        ):
            return
        try:
            from core.event_bus import Event

            await self.event_bus.publish(
                Event(topic=topic, data=dict(data), source="coder_engine")
            )
        except Exception as exc:
            log.warn(
                "Coder event publish failed",
                topic=topic,
                error=type(exc).__name__,
            )

    # -- Finalização ---------------------------------------------------------

    async def _finish(
        self,
        result: CoderResult,
        started: float,
        status: str,
        *,
        errors: Optional[list[str]] = None,
    ) -> CoderResult:
        """Fechamento comum: status, métricas, trilha, log e evento final."""
        if errors:
            result.errors.extend(errors)
        result.status = status
        result.finish()

        with self._lock:
            self._metrics.total_duration_ms += result.duration * 1000.0
            counter = {
                STATUS_OK: "ok",
                STATUS_INVALID: "invalid",
                STATUS_TEST_FAILED: "test_failed",
                STATUS_DENIED: "denied",
                STATUS_ERROR: "errors",
            }.get(status, "errors")
            setattr(self._metrics, counter, getattr(self._metrics, counter) + 1)

            entry = result.to_dict()
            entry["ts"] = result.finished_at
            self._history.append(entry)
            if len(self._history) > self._history_size:
                self._history = self._history[-self._history_size:]

        if status == STATUS_OK:
            log.info(
                "Coder change ok",
                change_id=result.change_id,
                file=result.file,
                summary=result.summary,
                duration_ms=round(result.duration * 1000, 3),
            )
        elif status in (STATUS_DENIED, STATUS_ERROR, STATUS_TEST_FAILED):
            log.crit(
                "Coder change failed",
                change_id=result.change_id,
                file=result.file,
                status=status,
                error="; ".join(result.errors) or result.summary,
            )
        else:
            log.warn(
                "Coder change invalid",
                change_id=result.change_id,
                file=result.file,
                errors="; ".join(result.errors),
            )

        await self._publish_event(
            "coder.completed",
            change_id=result.change_id,
            file=result.file,
            status=result.status,
            summary=result.summary,
        )
        return result

    # -- Inspeção ------------------------------------------------------------

    def dump(self) -> dict[str, Any]:
        """Snapshot diagnóstico completo do Coder Engine."""
        return {
            "root": str(self.root),
            "sandbox_dir": str(self.sandbox_dir),
            "backup_dir": str(self.backup_dir),
            "security_enabled": self.security is not None,
            "event_bus_enabled": self.event_bus is not None,
            "history_size": len(self._history),
            "metrics": self._metrics.snapshot(),
            "history": list(self.history),
        }
