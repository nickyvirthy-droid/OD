"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/self_repair.py
Descrição: Self Repair Engine — detecção de falhas em arquivos/componentes
           e geração de correções, sempre mediada pelo Coder Engine
           (sandbox → testes → backup → promoção). Correções automáticas
           só são promovidas se passarem no pipeline seguro; quando uma
           correção promovida reprova na verificação, o estado original é
           restaurado automaticamente a partir de um snapshot pré-reparo.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nexus src/self_repair.py (detecção de falhas + geração de correção)
  - OMEGADRAKON_SPEC.md §7 (Security Boundaries — auto-cura mediada pelo
    Security Layer e por pipeline de validação)
  - docs/NEXUS_LEGACY_ANALYSIS.md §3.7 + alerta: auto-cura legada executava
    scripts gerados por LLM sem sandbox robusto — no OmegaDrakon toda
    correção passa pelo Coder Engine (4.1)
  - ROADMAP_ABSORCAO.md Fase 4, item 4.2 (depende de Coder 4.1 ✅ e, para
    telemetria, de Perception 4.3)

Architecture:
    O Self Repair cobre o ciclo: DETECTAR → GERAR → REPARAR → VERIFICAR →
    (ROLLBACK). A detecção é determinística e segura (syntax check por
    compile + import probe opcional + oracle `check` injetado), e a geração
    de correções usa estratégias determinísticas embutidas (correção de
    header sem ":" etc.) além de estratégias/providers plugáveis — o ponto
    de extensão natural para auto-extensão via LLM no futuro (item 6.6),
    SEM nunca executar código gerado fora do pipeline do Coder Engine.

    O ciclo por candidato de correção:
      1. cada conteúdo candidato é submetido ao CoderEngine.apply_change()
         (compila + runner/test_command opcional + backup + promoção);
      2. promoção só ocorre se o pipeline do Coder aprovar;
      3. após a promoção, uma VERIFICAÇÃO independente é executada
         (oracle `check` e/ou re-detecção do arquivo);
      4. se a verificação reprovar, o snapshot pré-reparo é restaurado
         (rollback automático) e o próximo candidato é tentado.

    O snapshot pré-reparo é feito ANTES de qualquer mudança e permite
    restaurar os bytes exatos do estado anterior — inclusive um estado
    doente — pois o rollback devolve o sistema ao último estado conhecido
    (fail-safe), ao contrário da promoção do Coder, que é gated por saúde.

    Events: self_repair.detected / self_repair.completed (best-effort).
    Métricas, trilha de relatórios recentes e dump() seguem o padrão dos
    demais engines do core.

Usage:
    from core.coder import CoderEngine
    from core.self_repair import SelfRepairEngine

    coder = CoderEngine(root="/home/alex/OmegaDrakon")
    repair = SelfRepairEngine(coder=coder)

    report = await repair.repair("core/exemplo.py")
    report.status   # "healthy" | "repaired" | "no_fix" | "error"
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import inspect
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, Union

from core.coder import CoderEngine, STATUS_ERROR, STATUS_OK
from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.core.self_repair")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

DEFAULT_BACKUP_DIR = ".od_repair_backups"
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_HISTORY_SIZE = 200

# Status de um relatório de reparo
STATUS_HEALTHY = "healthy"
STATUS_REPAIRED = "repaired"
STATUS_NO_FIX = "no_fix"
STATUS_ERROR = "error"
REPORT_STATUSES = (STATUS_HEALTHY, STATUS_REPAIRED, STATUS_NO_FIX, STATUS_ERROR)

# Categorias de falha detectada
CATEGORY_SYNTAX = "syntax"
CATEGORY_IMPORT = "import"
CATEGORY_RUNTIME = "runtime"
CATEGORY_CHECK = "check"

# Cabeçalhos de bloco Python que exigem ":" ao final (para correção de syntax)
_BLOCK_HEADER_RE = (
    r"^\s*(async\s+)?(def|class|if|elif|else|for|while|try|except|finally|with)\b"
)

_PROTECTED_REL_PREFIXES = (".git",)

# ---------------------------------------------------------------------------
# Exceções
# ---------------------------------------------------------------------------


class SelfRepairError(Exception):
    """Erro base do Self Repair Engine."""


class SelfRepairScopeError(SelfRepairError, PermissionError):
    """Caminho fora do escopo estrito do Self Repair (spec §7.1)."""


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Detection:
    """Uma falha detectada em um arquivo.

    Attributes:
        file:       Caminho relativo do arquivo ao root.
        category:   syntax | import | runtime | check.
        message:    Mensagem descritiva da falha.
        error_type: Classe do erro (ex: SyntaxError, ModuleNotFoundError).
        line:       Linha do erro (quando disponível).
        offset:     Coluna do erro (quando disponível).
        source:     Origem da detecção (compile | import | check).
        ts:         Timestamp da detecção.
    """

    file: str
    category: str
    message: str = ""
    error_type: str = ""
    line: Optional[int] = None
    offset: Optional[int] = None
    source: str = ""
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "category": self.category,
            "message": self.message,
            "error_type": self.error_type,
            "line": self.line,
            "offset": self.offset,
            "source": self.source,
        }


@dataclass(slots=True)
class RepairAttempt:
    """Registro de uma tentativa de correção (um candidato)."""

    strategy: str
    status: str = "rejected"  # rejected | applied | rolled_back
    coder_status: str = ""
    change_id: str = ""
    error: str = ""
    verification: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "status": self.status,
            "coder_status": self.coder_status,
            "change_id": self.change_id,
            "error": self.error,
            "verification": self.verification,
        }


@dataclass(slots=True)
class RepairReport:
    """Resultado de um ciclo de auto-reparo sobre um arquivo.

    Attributes:
        report_id:     Identificador único do ciclo (uuid curto).
        file:          Caminho relativo do arquivo alvo.
        status:        healthy | repaired | no_fix | error.
        failure:       Falha detectada (None quando saudável).
        attempts:      Tentativas de correção executadas.
        snapshot_path: Caminho do snapshot pré-reparo (quando criado).
        rolled_back:   True se o estado original foi restaurado no fim.
        summary:       Resumo legível do ciclo.
        errors:        Erros do próprio ciclo (não da detecção).
        started_at / finished_at / duration: temporização.
    """

    report_id: str
    file: str
    status: str = STATUS_NO_FIX
    failure: Optional[Detection] = None
    attempts: list[RepairAttempt] = field(default_factory=list)
    snapshot_path: str = ""
    rolled_back: bool = False
    summary: str = ""
    errors: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    duration: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == STATUS_REPAIRED

    def finish(self) -> None:
        self.finished_at = time.time()
        self.duration = self.finished_at - self.started_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "file": self.file,
            "status": self.status,
            "failure": self.failure.to_dict() if self.failure else None,
            "attempts": [a.to_dict() for a in self.attempts],
            "snapshot_path": self.snapshot_path,
            "rolled_back": self.rolled_back,
            "summary": self.summary,
            "errors": list(self.errors),
            "duration": round(self.duration, 6),
        }


@dataclass(slots=True)
class RepairMetrics:
    """Métricas agregadas do Self Repair Engine."""

    cycles: int = 0
    healthy: int = 0
    repaired: int = 0
    no_fix: int = 0
    errors: int = 0
    attempts: int = 0
    rolled_back: int = 0
    total_duration_ms: float = 0.0

    @property
    def avg_duration_ms(self) -> float:
        if self.cycles == 0:
            return 0.0
        return round(self.total_duration_ms / self.cycles, 3)

    def snapshot(self) -> dict[str, Any]:
        return {
            "cycles": self.cycles,
            "healthy": self.healthy,
            "repaired": self.repaired,
            "no_fix": self.no_fix,
            "errors": self.errors,
            "attempts": self.attempts,
            "rolled_back": self.rolled_back,
            "avg_duration_ms": self.avg_duration_ms,
        }


# ---------------------------------------------------------------------------
# Estratégias de correção (determinísticas)
# ---------------------------------------------------------------------------


class RepairStrategy(Protocol):
    """Contrato de uma estratégia de correção.

    `generate` recebe o arquivo afetado (Path absoluto), a falha detectada
    e o conteúdo atual — e devolve conteúdos CANDIDATOS completos. Cada
    candidato passa pelo Coder Engine antes de qualquer promoção.
    """

    name: str
    categories: tuple[str, ...]

    def generate(
        self,
        target: Path,
        failure: Detection,
        content: str,
    ) -> list[str]: ...


@dataclass(slots=True)
class AddMissingColonStrategy:
    """Corrige headers de bloco Python sem ':' (ex: `def f()\\n`).

    Categoria: syntax. Candidato = mesma linha com ':' acrescentado ao
    final. Apenas sugerido quando o erro é de ':' ausente OU a linha é um
    header de bloco (def/class/if/elif/else/for/while/try/except/finally/
    with) sem ':' — e o candidato compila (gate do Coder revalida).
    """

    name: str = "add_missing_colon"
    categories: tuple[str, ...] = (CATEGORY_SYNTAX,)

    def generate(
        self,
        target: Path,
        failure: Detection,
        content: str,
    ) -> list[str]:
        if failure.line is None or failure.line < 1:
            return []
        lines = content.split("\n")
        if failure.line > len(lines):
            return []
        line_idx = failure.line - 1
        raw = lines[line_idx]
        stripped = raw.rstrip()
        if not stripped or stripped.endswith(":"):
            return []

        is_colon_error = "expected ':'" in (failure.message or "")
        is_block_header = bool(re.match(_BLOCK_HEADER_RE, stripped))
        if not (is_colon_error or is_block_header):
            return []

        fixed = stripped + ":"
        candidate = list(lines)
        candidate[line_idx] = fixed + raw[len(stripped):]  # preserva sufixo
        new_content = "\n".join(candidate)
        if new_content == content:
            return []
        return [new_content]


class FixProvider(Protocol):
    """Provider plugável de correções (ex: auto-extensão via LLM no futuro).

    `propose` devolve conteúdos candidatos para uma falha que as estratégias
    embutidas não cobrem. Nunca executa código — apenas sugere conteúdo que
    passará pelo Coder Engine.
    """

    name: str

    def propose(
        self,
        target: Path,
        failure: Detection,
        content: str,
    ) -> list[str]: ...


# ---------------------------------------------------------------------------
# SelfRepairEngine
# ---------------------------------------------------------------------------

DEFAULT_STRATEGIES: list[Any] = [AddMissingColonStrategy()]

CheckFn = Callable[..., Union[bool, Any]]


class SelfRepairEngine:
    """Engine de auto-reparo: detecta falhas e corrige via Coder Engine.

    Attributes:
        coder:        CoderEngine usado para TODA mudança (obrigatório).
        root:         Raiz estrita (padrão: root do coder).
        backup_dir:   Diretório de snapshots pré-reparo sob o root.
        strategies:   Estratégias determinísticas de correção.
        providers:    Providers plugáveis (ex: LLM/auto-extensão).
        event_bus:    EventBus opcional (self_repair.detected/completed).
        default_role: Papel usado no gate de segurança do Coder.
    """

    def __init__(
        self,
        *,
        coder: Optional[CoderEngine] = None,
        root: Optional[Union[str, Path]] = None,
        backup_dir: Union[str, Path] = DEFAULT_BACKUP_DIR,
        strategies: Optional[list[Any]] = None,
        providers: Optional[list[Any]] = None,
        event_bus: Optional[Any] = None,
        default_role: str = "coder",
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        history_size: int = DEFAULT_HISTORY_SIZE,
    ) -> None:
        if coder is None:
            coder = CoderEngine(root=root or Path(__file__).resolve().parent.parent)
        self.coder = coder

        resolved_root = (Path(root) if root else coder.root).expanduser().resolve()
        if coder.root != resolved_root:
            raise SelfRepairError(
                f"root divergente: coder.root={coder.root} vs root={resolved_root}"
            )
        self.root = resolved_root
        self.backup_dir = self.root / backup_dir
        self.strategies = list(strategies) if strategies else list(DEFAULT_STRATEGIES)
        self.providers = list(providers or [])
        self.event_bus = event_bus
        self.default_role = default_role
        self.max_attempts = max(1, max_attempts)
        self._history_size = max(1, history_size)

        self._snapshots: dict[str, Path] = {}  # rel -> snapshot
        self._history: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        self._metrics = RepairMetrics()

    # -- Propriedades --------------------------------------------------------

    @property
    def metrics(self) -> RepairMetrics:
        return self._metrics

    @property
    def history(self) -> list[dict[str, Any]]:
        """Relatórios recentes (mais recentes primeiro)."""
        return list(reversed(self._history))

    # -- API pública ---------------------------------------------------------

    def detect(
        self,
        file: Union[str, Path],
        *,
        import_probe: bool = False,
    ) -> Optional[Detection]:
        """Detecta falhas em um arquivo (determinística, sem efeitos).

        - Arquivos .py passam por syntax check (compile);
        - `import_probe=True` executa o módulo isolado para capturar falhas
          de import/runtime (opcional — executa o código do arquivo);
        - Arquivos saudáveis retornam None.

        Returns:
            Detection da primeira falha encontrada, ou None se saudável.
        """
        target, rel = self._resolve_target(file)
        if not target.exists() or target.is_dir():
            raise SelfRepairScopeError(f"arquivo inválido: {rel}")

        content = target.read_text(encoding="utf-8", errors="replace")
        if rel.endswith(".py"):
            syntax = self._compile_failure(rel, content)
            if syntax is not None:
                return syntax
            if import_probe:
                probe = self._import_failure(target, rel)
                if probe is not None:
                    return probe
        return None

    async def repair(
        self,
        file: Union[str, Path],
        *,
        check: Optional[CheckFn] = None,
        import_probe: bool = False,
        runner: Optional[Callable[..., Any]] = None,
        test_command: Optional[Union[str, list[str]]] = None,
        test_timeout: float = 60.0,
        max_attempts: Optional[int] = None,
        role: Optional[str] = None,
        session_id: str = "",
    ) -> RepairReport:
        """Ciclo completo de auto-reparo sobre um arquivo.

        Args:
            file:          Arquivo a inspecionar/reparar (relativo ao root).
            check:         Oracle de verificação (sync/async): retorna True
                           quando o componente está saudável; exceção/False =
                           falha. Executado APÓS cada promoção.
            import_probe:  Usa import probe na detecção (executa o módulo).
            runner:        Repassado ao Coder Engine (gate da etapa de testes).
            test_command:  Repassado ao Coder Engine (subprocess de testes).
            test_timeout:  Timeout do comando de testes do Coder.
            max_attempts:  Limite de candidatos tentados neste ciclo.
            role:          Papel no gate de segurança do Coder.
            session_id:    Sessão para auditoria.

        Returns:
            RepairReport — qualquer correção passou pelo Coder Engine
            (sandbox → testes → backup → promoção) e pela verificação.
        """
        started = time.time()
        report_id = uuid.uuid4().hex[:12]
        report = RepairReport(report_id=report_id, file="")
        max_attempts = max_attempts or self.max_attempts

        try:
            target, rel = self._resolve_target(file)
            report.file = rel
        except SelfRepairError as exc:
            report.errors.append(str(exc))
            self._metrics.cycles += 1
            return await self._finish(report, started, STATUS_ERROR)

        self._metrics.cycles += 1

        # 1. DETECTAR (nível código + oracle `check` do componente)
        try:
            failure = await self._detect_with_check(
                rel, check=check, import_probe=import_probe
            )
        except SelfRepairError as exc:
            return await self._finish(
                report, started, STATUS_ERROR, errors=[str(exc)]
            )

        if failure is None:
            report.status = STATUS_HEALTHY
            report.summary = "componente saudável — nada a reparar"
            return await self._finish(report, started, STATUS_HEALTHY)

        report.failure = failure
        await self._publish_event(
            "self_repair.detected",
            report_id=report_id,
            file=rel,
            category=failure.category,
            message=failure.message,
        )

        # 2. Snapshot pré-reparo (bytes exatos do estado atual)
        snapshot = self._take_snapshot(target, rel)
        if snapshot is None:
            return await self._finish(
                report,
                started,
                STATUS_ERROR,
                errors=["falha ao criar snapshot pré-reparo"],
            )
        report.snapshot_path = str(snapshot)
        self._snapshots[rel] = snapshot

        # 3. GERAR candidatos (estratégias embutidas + providers)
        original_content = target.read_text(encoding="utf-8", errors="replace")
        candidates: list[tuple[str, str]] = []
        seen: set[str] = set()

        for strategy in self.strategies:
            if failure.category not in getattr(strategy, "categories", (failure.category,)):
                continue
            try:
                for candidate in strategy.generate(target, failure, original_content):
                    if candidate not in seen and candidate != original_content:
                        seen.add(candidate)
                        candidates.append((strategy.name, candidate))
            except Exception as exc:
                log.warn(
                    "SelfRepair strategy error",
                    strategy=getattr(strategy, "name", "?"),
                    error=f"{type(exc).__name__}: {exc}",
                )

        for provider in self.providers:
            try:
                for candidate in provider.propose(target, failure, original_content):
                    if candidate not in seen and candidate != original_content:
                        seen.add(candidate)
                        candidates.append((getattr(provider, "name", "provider"), candidate))
            except Exception as exc:
                log.warn(
                    "SelfRepair provider error",
                    provider=getattr(provider, "name", "?"),
                    error=f"{type(exc).__name__}: {exc}",
                )

        if not candidates:
            report.summary = (
                f"nenhuma estratégia gerou correção para falha "
                f"[{failure.category}] {failure.message}"
            )
            return await self._finish(report, started, STATUS_NO_FIX)

        # 4. REPARAR (candidato a candidato, via Coder Engine)
        attempt_count = 0
        for strategy_name, candidate in candidates:
            if attempt_count >= max_attempts:
                break
            attempt_count += 1
            self._metrics.attempts += 1

            attempt = RepairAttempt(strategy=strategy_name)
            report.attempts.append(attempt)

            coder_result = await self.coder.apply_change(
                rel,
                content=candidate,
                message=f"self-repair[{strategy_name}] {failure.category}",
                runner=runner,
                test_command=test_command,
                test_timeout=test_timeout,
                role=role or self.default_role,
                session_id=session_id,
            )
            attempt.coder_status = coder_result.status
            attempt.change_id = coder_result.change_id
            if coder_result.status != STATUS_OK:
                attempt.status = "rejected"
                attempt.error = "; ".join(coder_result.errors) or coder_result.summary
                log.warn(
                    "SelfRepair candidate rejected",
                    report_id=report_id,
                    file=rel,
                    strategy=strategy_name,
                    coder_status=coder_result.status,
                    error=attempt.error,
                )
                continue

            # 5. VERIFICAR (pós-promoção)
            ok_verify, verify_msg = await self._verify(
                target=target,
                rel=rel,
                failure=failure,
                check=check,
                import_probe=import_probe,
            )
            attempt.verification = verify_msg
            if ok_verify:
                attempt.status = "applied"
                report.status = STATUS_REPAIRED
                report.rolled_back = False
                report.summary = (
                    f"corrigido via [{strategy_name}] "
                    f"(coder {coder_result.change_id})"
                )
                log.audit(
                    "self_repair.repaired",
                    session_id=session_id,
                    report_id=report_id,
                    file=rel,
                    strategy=strategy_name,
                    change_id=coder_result.change_id,
                )
                return await self._finish(report, started, STATUS_REPAIRED)

            # 6. ROLLBACK automático (estado original restaurado)
            attempt.status = "rolled_back"
            restored = self._restore(target, snapshot)
            report.rolled_back = restored
            if not restored:
                report.errors.append(
                    f"verificação reprovou e rollback falhou após "
                    f"[{strategy_name}] ({verify_msg})"
                )
                return await self._finish(
                    report, started, STATUS_ERROR, errors=report.errors
                )
            self._metrics.rolled_back += 1
            log.warn(
                "SelfRepair rolled back",
                report_id=report_id,
                file=rel,
                strategy=strategy_name,
                verification=verify_msg,
            )

        # Esgotou candidatos sem sucesso
        report.summary = (
            f"{len(report.attempts)} tentativa(s) sem sucesso — "
            f"estado original preservado"
        )
        return await self._finish(report, started, STATUS_NO_FIX)

    def restore(self, file: Union[str, Path]) -> bool:
        """Restaura o snapshot pré-reparo mais recente de um arquivo.

        Retorna True se havia snapshot e a restauração foi feita. Útil para
        reverter manualmente um reparo indesejado.
        """
        _target, rel = self._resolve_target(file)
        snapshot = self._snapshots.get(rel)
        if snapshot is None or not snapshot.exists():
            log.warn("SelfRepair restore sem snapshot", file=rel)
            return False
        target = self.root / rel
        restored = self._restore(target, snapshot)
        if restored:
            log.audit("self_repair.restore", file=rel, snapshot=str(snapshot))
        return restored

    # -- Detecção interna ----------------------------------------------------

    def _compile_failure(self, rel: str, content: str) -> Optional[Detection]:
        """Syntax check de um .py. Retorna Detection ou None."""
        try:
            compile(content, rel, "exec")
            return None
        except SyntaxError as exc:
            return Detection(
                file=rel,
                category=CATEGORY_SYNTAX,
                message=exc.msg or "invalid syntax",
                error_type=type(exc).__name__,
                line=exc.lineno,
                offset=exc.offset,
                source="compile",
            )
        except Exception as exc:  # ex: decode
            return Detection(
                file=rel,
                category=CATEGORY_RUNTIME,
                message=f"{type(exc).__name__}: {exc}",
                error_type=type(exc).__name__,
                source="compile",
            )

    def _import_failure(self, target: Path, rel: str) -> Optional[Detection]:
        """Executa o módulo isolado para capturar falhas de import/runtime."""
        module_name = f"_od_repair_{uuid.uuid4().hex[:10]}_{Path(rel).stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, target)
            if spec is None or spec.loader is None:
                return Detection(
                    file=rel,
                    category=CATEGORY_RUNTIME,
                    message="spec_from_file_location falhou",
                    error_type="ImportError",
                    source="import",
                )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return None
        except ModuleNotFoundError as exc:
            return Detection(
                file=rel,
                category=CATEGORY_IMPORT,
                message=str(exc),
                error_type=type(exc).__name__,
                source="import",
            )
        except ImportError as exc:
            return Detection(
                file=rel,
                category=CATEGORY_IMPORT,
                message=str(exc),
                error_type=type(exc).__name__,
                source="import",
            )
        except Exception as exc:
            return Detection(
                file=rel,
                category=CATEGORY_RUNTIME,
                message=f"{type(exc).__name__}: {exc}",
                error_type=type(exc).__name__,
                source="import",
            )

    # -- Verificação ---------------------------------------------------------

    async def _detect_with_check(
        self,
        rel: str,
        *,
        check: Optional[CheckFn],
        import_probe: bool,
    ) -> Optional[Detection]:
        """Detecção combinada: nível de código + oracle `check` do componente.

        Retorna a primeira falha de código (compile/import) ou, se o código
        está íntegro, a falha reportada pelo oracle — None se tudo saudável.
        """
        code_failure = self.detect(rel, import_probe=import_probe)
        if code_failure is not None:
            return code_failure
        if check is None:
            return None
        try:
            value = check()
            if inspect.isawaitable(value):
                value = await value
        except Exception as exc:
            return Detection(
                file=rel,
                category=CATEGORY_CHECK,
                message=f"{type(exc).__name__}: {exc}",
                error_type=type(exc).__name__,
                source="check",
            )
        if value is True:
            return None
        return Detection(
            file=rel,
            category=CATEGORY_CHECK,
            message="oracle de verificação reprovou (retorno não-True)",
            source="check",
        )

    async def _verify(
        self,
        *,
        target: Path,
        rel: str,
        failure: Detection,
        check: Optional[CheckFn],
        import_probe: bool,
    ) -> tuple[bool, str]:
        """Verifica se a falha foi resolvida após a promoção.

        Prioridade: oracle `check` > re-detecção (compile/import).
        """
        if check is not None:
            try:
                value = check()
                if inspect.isawaitable(value):
                    value = await value
                if value is True:
                    return True, "check ok"
                return False, "check reprovou (retorno não-True)"
            except Exception as exc:
                return False, f"check falhou: {type(exc).__name__}: {exc}"

        # Re-detecção padrão: se a categoria original não reaparece, está bom
        redetect = self.detect(rel, import_probe=import_probe and failure.category
                               in (CATEGORY_IMPORT, CATEGORY_RUNTIME))
        if redetect is None:
            return True, "re-detecção: sem falhas"
        return False, (
            f"falha persiste [{redetect.category}]: {redetect.message}"
        )

    # -- Snapshot e restauração ---------------------------------------------

    def _take_snapshot(self, target: Path, rel: str) -> Optional[Path]:
        """Copia os bytes exatos do estado atual para o diretório de backups."""
        try:
            digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:12]
            snapshot = self.backup_dir / f"{digest}.{int(time.time())}.bak"
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            # Escrita atômica do snapshot
            tmp = snapshot.with_suffix(".tmp")
            tmp.write_bytes(target.read_bytes())
            os.replace(tmp, snapshot)
            log.info("SelfRepair snapshot created", file=rel, backup=str(snapshot))
            return snapshot
        except Exception as exc:
            log.crit(
                "SelfRepair snapshot failed",
                file=rel,
                error=f"{type(exc).__name__}: {exc}",
            )
            return None

    def _restore(self, target: Path, snapshot: Path) -> bool:
        """Restaura bytes exatos do snapshot sobre o alvo (escrita atômica).

        Rollback devolve o ÚLTIMO ESTADO CONHECIDO — mesmo que doente — por
        isso não passa pelo gate de saúde do Coder; é a saída de emergência
        do auto-reparo, restrita a snapshots criados pelo próprio engine.
        """
        try:
            if not snapshot.exists():
                return False
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}.tmp")
            tmp.write_bytes(snapshot.read_bytes())
            os.replace(tmp, target)
            log.info("SelfRepair restore ok", file=str(target), backup=str(snapshot))
            return True
        except Exception as exc:
            log.crit(
                "SelfRepair restore failed",
                file=str(target),
                error=f"{type(exc).__name__}: {exc}",
            )
            return False

    # -- Escopo --------------------------------------------------------------

    def _resolve_target(self, file: Union[str, Path]) -> tuple[Path, str]:
        """Resolve o alvo contra o root com escopo estrito.

        Raises:
            SelfRepairScopeError: caminho fora do root ou área protegida.
        """
        raw = Path(file)
        candidate = raw if raw.is_absolute() else self.root / raw
        resolved = candidate.expanduser().resolve()

        try:
            rel = resolved.relative_to(self.root)
        except ValueError:
            raise SelfRepairScopeError(
                f"arquivo fora do escopo do Self Repair: {file} "
                f"(root: {self.root})"
            ) from None

        rel_parts = rel.parts
        if rel_parts and rel_parts[0] in _PROTECTED_REL_PREFIXES:
            raise SelfRepairScopeError(
                f"caminho protegido, não editável: {file}"
            )

        for internal in (self.coder.sandbox_dir, self.coder.backup_dir, self.backup_dir):
            internal_resolved = internal.expanduser().resolve()
            if internal_resolved == self.root:
                continue
            try:
                internal_rel = internal_resolved.relative_to(self.root)
            except ValueError:
                continue
            if rel_parts[: len(internal_rel.parts)] == internal_rel.parts:
                raise SelfRepairScopeError(
                    f"caminho protegido, não editável: {file}"
                )
        return resolved, str(rel)

    # -- Event Bus (best-effort) ---------------------------------------------

    async def _publish_event(self, topic: str, **data: Any) -> None:
        """Publica um evento no bus (nunca quebra o ciclo)."""
        if self.event_bus is None or not getattr(
            self.event_bus, "running", False
        ):
            return
        try:
            from core.event_bus import Event

            await self.event_bus.publish(
                Event(topic=topic, data=dict(data), source="self_repair")
            )
        except Exception as exc:
            log.warn(
                "SelfRepair event publish failed",
                topic=topic,
                error=type(exc).__name__,
            )

    # -- Finalização ---------------------------------------------------------

    async def _finish(
        self,
        report: RepairReport,
        started: float,
        status: str,
        *,
        errors: Optional[list[str]] = None,
    ) -> RepairReport:
        """Fechamento comum: status, métricas, trilha, log e evento final."""
        if errors:
            report.errors.extend(errors)
        report.status = status
        report.finish()

        with self._lock:
            self._metrics.total_duration_ms += report.duration * 1000.0
            counter = {
                STATUS_HEALTHY: "healthy",
                STATUS_REPAIRED: "repaired",
                STATUS_NO_FIX: "no_fix",
                STATUS_ERROR: "errors",
            }.get(status, "errors")
            setattr(self._metrics, counter, getattr(self._metrics, counter) + 1)

            entry = report.to_dict()
            entry["ts"] = report.finished_at
            self._history.append(entry)
            if len(self._history) > self._history_size:
                self._history = self._history[-self._history_size:]

        if status == STATUS_REPAIRED:
            log.info(
                "SelfRepair repaired",
                report_id=report.report_id,
                file=report.file,
                summary=report.summary,
                duration_ms=round(report.duration * 1000, 3),
            )
        elif status == STATUS_HEALTHY:
            log.info(
                "SelfRepair healthy",
                file=report.file,
                duration_ms=round(report.duration * 1000, 3),
            )
        elif status == STATUS_ERROR:
            log.crit(
                "SelfRepair error",
                report_id=report.report_id,
                file=report.file,
                errors="; ".join(report.errors),
            )
        else:
            log.warn(
                "SelfRepair no_fix",
                report_id=report.report_id,
                file=report.file,
                failure=report.failure.message if report.failure else "",
                summary=report.summary,
            )

        await self._publish_event(
            "self_repair.completed",
            report_id=report.report_id,
            file=report.file,
            status=report.status,
            summary=report.summary,
        )
        return report

    # -- Inspeção ------------------------------------------------------------

    def dump(self) -> dict[str, Any]:
        """Snapshot diagnóstico completo do Self Repair Engine."""
        return {
            "root": str(self.root),
            "backup_dir": str(self.backup_dir),
            "coder_root": str(self.coder.root),
            "strategies": [getattr(s, "name", type(s).__name__) for s in self.strategies],
            "providers": [getattr(p, "name", type(p).__name__) for p in self.providers],
            "snapshots_kept": len(self._snapshots),
            "history_size": len(self._history),
            "metrics": self._metrics.snapshot(),
            "history": list(self.history),
        }
