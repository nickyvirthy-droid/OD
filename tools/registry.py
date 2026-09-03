"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: tools/registry.py
Descrição: Action Registry — registro tipado de ações executáveis com
           schema de parâmetros, execução validada pelo Security Layer
           (spec §7) e integração com o Tool Loader (3.2).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime core/actions/ (registro tipado de ações)
  - OMEGADRAKON_SPEC.md §7 (execução mediada por schemas e Security Layer)
  - ROADMAP_ABSORCAO.md Fase 3, item 3.3 (depende de Security e Loader)

Architecture:
    Uma Action é a unidade atômica executável do catálogo tools/ (spec:
    "ações atômicas, tipadas, validadas por schema e auditadas"). Cada
    Action declara:

      - name        — identificador canônico (ex: "filesystem.read");
      - handler     — callable sync/async que recebe os parâmetros validados
                      como keyword arguments;
      - params      — schema dos parâmetros (formato do tools.loader);
      - permission  — ação verificada no Security Layer ANTES da execução
                      (ex: "filesystem.read"). Vazio = sem gate de segurança;
      - category / description / aliases / version / source.

    O registro centraliza Actions vindas de duas fontes:
      1. registrar ações explícitas (register/register_action);
      2. importar ferramentas de um ToolLoader (import_loader) — cada Tool
         vira uma Action que reutiliza o mesmo schema de parâmetros e o
         `requires` declarado pelo plugin.

    execute() segue o pipeline: resolução (nome/alias) → validação de schema
    → gate de segurança (se permission e SecurityManager presentes) →
    invocação do handler com os parâmetros preenchidos (defaults aplicados).
    O resultado é um ActionResult padronizado (ok | invalid | denied |
    error | not_found), com métricas e trilha recente.

Usage:
    from core.security import SecurityManager
    from tools.registry import Action, ActionRegistry

    registry = ActionRegistry(security=SecurityManager(mode="strict"))
    registry.register_action(
        "filesystem.read",
        handler=lambda path: open(path).read(),
        params={"required": ["path"], "properties": {"path": {"type": "str"}}},
        permission="filesystem.read",
    )

    result = await registry.execute("filesystem.read", params={"path": "/tmp/x"})
    result.status  # "ok" | "invalid" | "denied" | "error" | "not_found"
"""

from __future__ import annotations

import inspect
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TYPE_CHECKING

from core.logger import get_logger
from tools.loader import validate_params

if TYPE_CHECKING:
    from core.security.manager import SecurityManager
    from tools.loader import ToolLoader

__signature__ = "OD // CORE"

log = get_logger("omega.tools.registry")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

DEFAULT_HISTORY_SIZE = 200
RESULT_STATUSES = ("ok", "invalid", "denied", "error", "not_found")


# ---------------------------------------------------------------------------
# Exceções
# ---------------------------------------------------------------------------

class ActionRegistryError(Exception):
    """Erro base do Action Registry."""


class ActionNotFoundError(ActionRegistryError, KeyError):
    """Ação não registrada."""


class ActionValidationError(ActionRegistryError, ValueError):
    """Registro de ação inválido (nome vazio, handler ausente etc.)."""


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Action:
    """Uma ação tipada registrada no catálogo.

    Attributes:
        name:        Identificador canônico (ex: "filesystem.read").
        handler:     Callable sync/async; recebe os parâmetros validados
                     como keyword arguments.
        description: Descrição da ação.
        category:    Categoria (ex: "filesystem", "system").
        params:      Schema dos parâmetros (ver tools.loader.validate_params).
        permission:  Ação verificada no Security Layer antes de executar.
                     Vazio = sem gate de segurança.
        aliases:     Nomes alternativos aceitos em execute().
        version:     Versão da ação.
        source:      Origem ("manual", caminho do plugin etc.).
        registered_at: Timestamp de registro.
    """

    name: str
    handler: Optional[Callable[..., Any]] = None
    description: str = ""
    category: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    permission: str = ""
    aliases: list[str] = field(default_factory=list)
    version: str = "1.0.0"
    source: str = ""
    registered_at: float = field(default_factory=time.time)

    # -- Propriedades --------------------------------------------------------

    @property
    def is_async(self) -> bool:
        return self.handler is not None and inspect.iscoroutinefunction(self.handler)

    @property
    def active(self) -> bool:
        return self.handler is not None

    # -- Validação de parâmetros --------------------------------------------

    def validate(self, params: Optional[dict[str, Any]] = None) -> tuple[bool, list[str]]:
        """Valida params contra o schema da ação (sem aplicar defaults)."""
        ok, errors, _filled = validate_params(self.params, params)
        return ok, errors

    # -- Conversão -----------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "params": self.params,
            "permission": self.permission,
            "aliases": list(self.aliases),
            "version": self.version,
            "source": self.source,
            "async": self.is_async,
            "active": self.active,
        }


@dataclass(slots=True)
class ActionResult:
    """Resultado padronizado de uma execução de ação.

    Attributes:
        action:     Nome canônico da ação executada.
        status:     ok | invalid | denied | error | not_found.
        data:       Retorno do handler (quando ok).
        error:      Mensagem de erro (quando error/not_found).
        errors:     Lista de violações de schema (quando invalid).
        denied_by:  Camada do Security Layer que negou (quando denied).
        role:       Papel usado no gate de segurança.
        params:     Parâmetros validados (defaults aplicados).
        started_at / finished_at / duration: temporização.
    """

    action: str
    status: str = "ok"
    data: Any = None
    error: str = ""
    errors: list[str] = field(default_factory=list)
    denied_by: str = ""
    role: str = "agent"
    params: dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    duration: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "status": self.status,
            "data": self.data,
            "error": self.error,
            "errors": list(self.errors),
            "denied_by": self.denied_by,
            "role": self.role,
            "params": self.params,
            "duration": round(self.duration, 6),
        }


@dataclass(slots=True)
class RegistryMetrics:
    """Métricas de execução do registry."""

    executed: int = 0
    ok: int = 0
    invalid: int = 0
    denied: int = 0
    errors: int = 0
    not_found: int = 0
    actions: int = 0
    total_duration_ms: float = 0.0

    @property
    def avg_duration_ms(self) -> float:
        if self.executed == 0:
            return 0.0
        return round(self.total_duration_ms / self.executed, 3)

    def snapshot(self) -> dict[str, Any]:
        return {
            "actions": self.actions,
            "executed": self.executed,
            "ok": self.ok,
            "invalid": self.invalid,
            "denied": self.denied,
            "errors": self.errors,
            "not_found": self.not_found,
            "avg_duration_ms": self.avg_duration_ms,
        }


# ---------------------------------------------------------------------------
# ActionRegistry
# ---------------------------------------------------------------------------

class ActionRegistry:
    """Registro tipado de ações com execução validada.

    Attributes:
        security:        SecurityManager opcional — gates de `permission`.
        allow_overwrite: Se True, re-registrar nome substitui o existente.
        history_size:    Tamanho da trilha recente de execuções.
    """

    def __init__(
        self,
        *,
        security: Optional[SecurityManager] = None,
        allow_overwrite: bool = False,
        history_size: int = DEFAULT_HISTORY_SIZE,
    ) -> None:
        self._security = security
        self._allow_overwrite = allow_overwrite
        self._history_size = max(1, history_size)

        self._actions: dict[str, Action] = {}
        self._aliases: dict[str, str] = {}
        self._history: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        self._metrics = RegistryMetrics()

    # -- Propriedades --------------------------------------------------------

    @property
    def security(self) -> Optional[SecurityManager]:
        return self._security

    @property
    def metrics(self) -> RegistryMetrics:
        return self._metrics

    @property
    def history(self) -> list[dict[str, Any]]:
        """Trilha recente de execuções (mais recentes primeiro)."""
        return list(reversed(self._history))

    # -- Registro ------------------------------------------------------------

    def register(self, action: Action) -> bool:
        """Registra (ou substitui) uma ação. Retorna True se registrada."""
        self._validate_action(action)
        with self._lock:
            existing = self._actions.get(action.name)
            if existing is not None and not self._allow_overwrite:
                log.warn(
                    "Action skipped (nome duplicado)",
                    action=action.name,
                    existing_source=existing.source or "manual",
                )
                return False
            self._actions[action.name] = action
            # aliases apontam para o nome canônico
            self._aliases.pop(action.name, None)
            for alias in action.aliases:
                if alias == action.name:
                    continue
                self._aliases[alias] = action.name
        self._metrics.actions = len(self._actions)
        log.info(
            "Action registered",
            action=action.name,
            category=action.category or "-",
            permission=action.permission or "-",
            async_=action.is_async,
            source=action.source or "manual",
        )
        return True

    def register_action(
        self,
        name: str,
        handler: Callable[..., Any],
        *,
        description: str = "",
        category: str = "",
        params: Optional[dict[str, Any]] = None,
        permission: str = "",
        aliases: Optional[list[str]] = None,
        version: str = "1.0.0",
        source: str = "",
    ) -> Action:
        """Conveniência para registrar uma ação sem instanciar Action."""
        action = Action(
            name=name,
            handler=handler,
            description=description,
            category=category,
            params=dict(params or {}),
            permission=permission,
            aliases=list(aliases or []),
            version=version,
            source=source,
        )
        self.register(action)
        return action

    def import_loader(
        self,
        loader: ToolLoader,
        *,
        category_prefix: Optional[str] = None,
    ) -> int:
        """Importa as ferramentas de um ToolLoader como ações.

        Cada Tool vira uma Action: name preservado (ou prefixado por
        categoria quando category_prefix informado), params e `requires`
        do plugin reutilizados como schema/permission.

        Returns:
            Número de ações novas importadas.
        """
        imported = 0
        for tool in loader.find():
            name = (
                f"{category_prefix}.{tool.name}"
                if category_prefix
                else tool.name
            )
            action = Action(
                name=name,
                handler=tool.fn,
                description=tool.description,
                category=tool.category,
                params=dict(tool.params),
                permission=tool.requires,
                version=tool.version,
                source=tool.source or "loader",
            )
            if self.register(action):
                imported += 1
        log.info(
            "Actions imported from loader",
            loader_source=",".join(str(d) for d in loader.dirs) or "manual",
            imported=imported,
        )
        return imported

    def unregister(self, name: str) -> bool:
        """Remove uma ação (e seus aliases). Retorna True se existia."""
        with self._lock:
            action = self._actions.pop(name, None)
            if action is None:
                return False
            self._aliases = {
                a: target for a, target in self._aliases.items() if target != name
            }
        self._metrics.actions = len(self._actions)
        log.info("Action unregistered", action=name)
        return True

    def clear(self) -> int:
        """Remove todas as ações. Retorna o número removido."""
        with self._lock:
            count = len(self._actions)
            self._actions.clear()
            self._aliases.clear()
            self._history.clear()
        self._metrics.actions = 0
        log.info("ActionRegistry cleared", removed=count)
        return count

    # -- Consulta ------------------------------------------------------------

    def has(self, name: str) -> bool:
        """True se o nome (ou alias) está registrado."""
        return name in self._actions or name in self._aliases

    def get(self, name: str) -> Action:
        """Retorna a ação pelo nome canônico ou alias."""
        action = self._actions.get(name)
        if action is None:
            canonical = self._aliases.get(name)
            action = self._actions.get(canonical) if canonical else None
        if action is None:
            raise ActionNotFoundError(f"Ação não registrada: {name}")
        return action

    def find(self, category: Optional[str] = None) -> list[Action]:
        """Lista ações (opcionalmente filtradas por categoria)."""
        return [
            a for a in self._actions.values()
            if category is None or a.category == category
        ]

    def list_actions(self) -> list[dict[str, Any]]:
        """Snapshot de todas as ações registradas."""
        return [a.to_dict() for a in self._actions.values()]

    # -- Execução ------------------------------------------------------------

    async def execute(
        self,
        name: str,
        *,
        params: Optional[dict[str, Any]] = None,
        role: str = "agent",
        session_id: str = "",
    ) -> ActionResult:
        """Executa uma ação com pipeline completo de validação.

        Pipeline: resolução (nome/alias) → validação de schema (defaults
        aplicados) → gate de segurança (quando permission + security) →
        invocação do handler com os parâmetros preenchidos.

        Args:
            name:       Nome canônico ou alias da ação.
            params:     Parâmetros da ação.
            role:       Papel do solicitante (gate de segurança).
            session_id: Identificador de sessão para auditoria.

        Returns:
            ActionResult com status ok | invalid | denied | error | not_found.
        """
        started = time.time()
        result = ActionResult(
            action=name,
            role=role,
            params=dict(params or {}),
        )

        try:
            action = self.get(name)
        except ActionNotFoundError as exc:
            result.error = str(exc)
            self._record("not_found", result, started)
            log.warn("Action not found", action=name)
            return result

        result.action = action.name
        result.params = dict(params or {})

        # 1. Validação de schema
        ok, errors, filled = validate_params(action.params, params)
        if not ok:
            result.status = "invalid"
            result.errors = errors
            self._record("invalid", result, started)
            log.warn(
                "Action params invalid",
                action=action.name,
                errors="; ".join(errors),
            )
            return result
        result.params = filled

        # 2. Gate de segurança (spec §7)
        if action.permission and self._security is not None:
            decision = self._security.check(
                action=action.permission,
                params=filled,
                role=role,
                source="action_registry",
                session_id=session_id,
            )
            if not decision.allowed:
                result.status = "denied"
                result.denied_by = decision.denied_by or ""
                result.error = "; ".join(decision.reasons) or "denied"
                self._record("denied", result, started)
                log.crit(
                    "Action denied by security",
                    action=action.name,
                    denied_by=result.denied_by or "-",
                    role=role,
                )
                return result

        # 3. Invocação do handler
        try:
            if action.handler is None:
                raise ActionValidationError(f"Ação {action.name!r} sem handler")
            call = action.handler(**filled)
            if inspect.isawaitable(call):
                data = await call
            else:
                data = call
        except Exception as exc:
            result.status = "error"
            result.error = f"{type(exc).__name__}: {exc}"
            self._record("error", result, started)
            log.crit(
                "Action execution error",
                action=action.name,
                error=result.error,
            )
            return result

        result.status = "ok"
        result.data = data
        self._record("ok", result, started)
        log.info(
            "Action executed",
            action=action.name,
            role=role,
            duration_ms=round(result.duration * 1000, 3),
        )
        return result

    # -- Trilha e métricas ---------------------------------------------------

    def _record(self, status: str, result: ActionResult, started: float) -> None:
        """Finaliza o resultado, atualiza métricas e grava a trilha."""
        result.finished_at = time.time()
        result.duration = result.finished_at - started
        result.status = status

        self._metrics.executed += 1
        self._metrics.total_duration_ms += result.duration * 1000.0
        # status "error" mapeia para o campo de métrica "errors"
        metric_field = "errors" if status == "error" else status
        setattr(
            self._metrics,
            metric_field,
            getattr(self._metrics, metric_field) + 1,
        )

        entry = result.to_dict()
        entry["ts"] = result.finished_at
        self._history.append(entry)
        if len(self._history) > self._history_size:
            self._history = self._history[-self._history_size:]

    # -- Inspeção ------------------------------------------------------------

    def dump(self) -> dict[str, Any]:
        """Snapshot diagnóstico completo do registry."""
        return {
            "actions": len(self._actions),
            "aliases": len(self._aliases),
            "security_enabled": self._security is not None,
            "history_size": len(self._history),
            "metrics": self._metrics.snapshot(),
            "catalog": self.list_actions(),
        }

    # -- Validação de registro ----------------------------------------------

    @staticmethod
    def _validate_action(action: Action) -> None:
        if not action.name or not action.name.strip():
            raise ActionValidationError("Ação sem nome")
        if action.handler is None:
            raise ActionValidationError(f"Ação {action.name!r} sem handler")
        for alias in action.aliases:
            if not alias or not alias.strip():
                raise ActionValidationError(
                    f"Alias vazio na ação {action.name!r}"
                )
