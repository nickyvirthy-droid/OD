"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/security/scope.py
Descrição: Scope Engine — escopo estrito do projeto, caminhos protegidos,
           operações destrutivas e proibição de execução como root.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime Security Layer (camada 3: Scope Engine)
  - OMEGADRAKON_SPEC.md §7.1 (escopo estrito do projeto, proteção a legados)
  - OMEGADRAKON_SPEC.md §7.2 (execução sem root)
"""

from __future__ import annotations

__signature__ = "OD // CORE"

import logging
from pathlib import Path
from typing import Any, Optional

from core.security.models import ActionRequest, CheckResult

logger = logging.getLogger("omega.core.security.scope")

NICKY_PREFIX = "[NICKY][{level}]"


def _audit_nicky(level: str, message: str, **kwargs: Any) -> None:
    prefix = NICKY_PREFIX.format(level=level)
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    full = f"{prefix} {message}" + (f" | {extra}" if extra else "")
    _LEVEL_MAP = {"INFO": logger.info, "WARN": logger.warning, "CRIT": logger.critical}
    _LEVEL_MAP.get(level, logger.info)(full)


# ---------------------------------------------------------------------------
# Heurística de operação (read vs write)
# ---------------------------------------------------------------------------

WRITE_KEYWORDS = (
    "write", "delete", "remove", "move", "rename", "copy", "create", "mkdir",
    "patch", "commit", "push", "touch", "truncate", "save", "update", "format",
    "wipe", "install", "uninstall", "extract", "archive", "edit", "append",
    "promote", "backup", "restore",
)

READ_KEYWORDS = (
    "read", "list", "info", "search", "exists", "get", "show", "inspect",
    "view", "fetch", "hash", "tree", "status", "log", "schema", "tables",
    "health",
)


def classify_operation(request: ActionRequest) -> str:
    """Classifica a operação como "read" ou "write".

    Prioridade: metadata["operation"] explícito > flag destructive >
    heurística de keywords no nome da ação.
    """
    explicit = request.metadata.get("operation")
    if explicit in ("read", "write"):
        return explicit

    if request.destructive:
        return "write"

    action_lower = request.action.lower()
    if any(kw in action_lower for kw in WRITE_KEYWORDS):
        return "write"
    if any(kw in action_lower for kw in READ_KEYWORDS):
        return "read"

    # Default seguro: tratar como write (fail-safe para escopo)
    return "write"


# Chaves de params que podem conter caminhos
_PATH_PARAM_KEYS = (
    "path", "paths", "file", "directory", "dir", "folder", "source", "src",
    "destination", "dest", "target", "target_path", "archive", "backup_path",
    "cwd", "workdir",
)


def extract_paths(request: ActionRequest) -> list[str]:
    """Extrai candidatos a caminhos dos params da requisição."""
    found: list[str] = list(request.paths)
    for key in _PATH_PARAM_KEYS:
        value = request.params.get(key)
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, (list, tuple)):
            found.extend(v for v in value if isinstance(v, str))
    # Remove vazios e deduplica preservando ordem
    seen: set[str] = set()
    result: list[str] = []
    for p in found:
        p = p.strip()
        if p and p not in seen:
            seen.add(p)
            result.append(p)
    return result


# ---------------------------------------------------------------------------
# ScopeEngine
# ---------------------------------------------------------------------------

class ScopeEngine:
    """Camada 3 — Scope Engine: limitações de filesystem e operacionais.

    Regras:
      - Todo caminho acessado deve estar dentro de uma raiz permitida.
      - Caminhos protegidos não podem ser alterados (somente leitura).
      - Operações destrutivas são negadas para agentes autônomos
        (spec §7.2: quarentena ou aprovação humana).
      - Execução como root é proibida (spec §7.2).
    """

    def __init__(
        self,
        *,
        allowed_roots: Optional[list[str | Path]] = None,
        protected_paths: Optional[list[str | Path]] = None,
        allow_root: bool = False,
        allow_destructive: bool = False,
    ) -> None:
        # Raiz padrão: diretório do projeto OmegaDrakon (pai do pacote core/)
        default_root = Path(__file__).resolve().parent.parent.parent
        self._allowed_roots: list[Path] = [
            Path(p).expanduser().resolve()
            for p in (allowed_roots or [default_root])
        ]
        default_protected = [self._allowed_roots[0] / ".git"]
        self._protected_paths: list[Path] = [
            Path(p).expanduser().resolve()
            for p in (protected_paths or default_protected)
        ]
        self._allow_root = allow_root
        self._allow_destructive = allow_destructive

    # -- Regras --------------------------------------------------------------

    def add_root(self, path: str | Path) -> None:
        """Adiciona uma raiz permitida."""
        resolved = Path(path).expanduser().resolve()
        if resolved not in self._allowed_roots:
            self._allowed_roots.append(resolved)

    def remove_root(self, path: str | Path) -> bool:
        """Remove uma raiz permitida. Retorna True se existia."""
        resolved = Path(path).expanduser().resolve()
        if resolved in self._allowed_roots:
            self._allowed_roots.remove(resolved)
            return True
        return False

    def add_protected_path(self, path: str | Path) -> None:
        """Protege um caminho contra alterações (somente leitura)."""
        resolved = Path(path).expanduser().resolve()
        if resolved not in self._protected_paths:
            self._protected_paths.append(resolved)

    def remove_protected_path(self, path: str | Path) -> bool:
        """Remove um caminho protegido. Retorna True se existia."""
        resolved = Path(path).expanduser().resolve()
        if resolved in self._protected_paths:
            self._protected_paths.remove(resolved)
            return True
        return False

    def set_allow_root(self, allow: bool) -> None:
        """Permite/proíbe execução com privilégios de superusuário."""
        self._allow_root = allow

    def set_allow_destructive(self, allow: bool) -> None:
        """Permite/proíbe operações destrutivas (padrão: proibidas)."""
        self._allow_destructive = allow

    def is_within_roots(self, path: Path) -> bool:
        """Verifica se um caminho está dentro de alguma raiz permitida."""
        resolved = path.expanduser().resolve()
        for root in self._allowed_roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def is_protected(self, path: Path) -> bool:
        """Verifica se um caminho é protegido (somente leitura)."""
        resolved = path.expanduser().resolve()
        for protected in self._protected_paths:
            try:
                resolved.relative_to(protected)
                return True
            except ValueError:
                continue
        return False

    # -- Avaliação -----------------------------------------------------------

    def evaluate(self, request: ActionRequest) -> CheckResult:
        """Avalia o escopo da requisição. Retorna CheckResult layer="scope"."""
        # 1. Root execution proibida (spec §7.2)
        if request.requires_root and not self._allow_root:
            _audit_nicky(
                "CRIT",
                "Root execution forbidden",
                action=request.action,
                request_id=request.request_id,
            )
            return CheckResult(
                layer="scope",
                allowed=False,
                reason="Root execution is forbidden by policy",
            )

        # 2. Operações destrutivas proibidas para agentes (spec §7.2)
        if request.destructive and not self._allow_destructive:
            _audit_nicky(
                "CRIT",
                "Destructive operation forbidden",
                action=request.action,
                request_id=request.request_id,
            )
            return CheckResult(
                layer="scope",
                allowed=False,
                reason="Destructive operations require explicit approval",
            )

        # 3. Escopo de filesystem (spec §7.1)
        operation = classify_operation(request)
        paths = extract_paths(request)
        for raw in paths:
            candidate = Path(raw).expanduser()
            # Caminhos relativos são resolvidos contra a primeira raiz
            if not candidate.is_absolute():
                candidate = self._allowed_roots[0] / candidate
            candidate = candidate.resolve()

            if not self.is_within_roots(candidate):
                _audit_nicky(
                    "CRIT",
                    "Path outside allowed roots",
                    action=request.action,
                    path=str(candidate),
                    request_id=request.request_id,
                )
                return CheckResult(
                    layer="scope",
                    allowed=False,
                    reason=f"Path '{candidate}' is outside the allowed project scope",
                )

            if operation == "write" and self.is_protected(candidate):
                _audit_nicky(
                    "CRIT",
                    "Write to protected path",
                    action=request.action,
                    path=str(candidate),
                    request_id=request.request_id,
                )
                return CheckResult(
                    layer="scope",
                    allowed=False,
                    reason=f"Path '{candidate}' is protected (read-only)",
                )

        return CheckResult(layer="scope", allowed=True)

    # -- Inspeção ------------------------------------------------------------

    def dump(self) -> dict[str, Any]:
        return {
            "allowed_roots": [str(p) for p in self._allowed_roots],
            "protected_paths": [str(p) for p in self._protected_paths],
            "allow_root": self._allow_root,
            "allow_destructive": self._allow_destructive,
        }