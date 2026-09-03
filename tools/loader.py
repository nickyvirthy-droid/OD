"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: tools/loader.py
Descrição: Tool Loader — carregamento dinâmico de ferramentas/plugins
           Python a partir de diretórios, com registro centralizado de
           metadados, hot-reload, validação de parâmetros por schema e
           escopo estrito de diretórios.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nexus src/tool_loader.py (scripts em src/tools/, hot-reload, registro)
  - OMEGADRAKON_SPEC.md — catálogo tools/ com "ações atômicas, tipadas,
    validadas por schema e auditadas"
  - ROADMAP_ABSORCAO.md Fase 3, item 3.2

Architecture:
    Um "plugin" é um módulo Python com uma das seguintes formas de
    declaração (todas opcionais, avaliadas nesta ordem):

      1. PLUGIN  = {"name": ..., "version": ..., "tools": [tool, ...]}
      2. TOOLS   = [tool, ...]
      3. load_tools() -> [tool, ...]   (função chamada na carga)

    Cada `tool` pode ser:
      - dict com nome/descrição/categoria/função/schema de parâmetros;
      - instância de Tool; ou
      - callable puro (nome derivado de __name__/__qualname__).

    Contrato de um dict de ferramenta (chaves aceitas):
      name|tool|id       — nome único (obrigatório)
      fn|function|func|callable — callable executável (obrigatório)
      description|desc|doc — descrição (fallback: docstring da função)
      category           — categoria (ex: "filesystem", "system")
      params|parameters|schema — schema dos parâmetros (ver validate_params)
      requires           — ação exigida no Security Layer em execução (3.3)
      version|tags       — metadados adicionais

    O loader importa cada módulo .py encontrado (executando seu código —
    plugins são código Python confiável do catálogo), extrai as ferramentas,
    valida metadados e registra em um índice central por nome. Falhas de
    import de um módulo não impedem o carregamento dos demais. Hot-reload
    reimporta o módulo do disco e substitui as ferramentas antigas.

    O escopo é estrito: quando o loader recebe diretórios base, arquivos
    fora deles são recusados (ToolScopeError) — alinhado à spec §7.1.

Usage:
    from tools.loader import ToolLoader

    loader = ToolLoader(dirs=["tools/plugins"])
    loader.load_all()

    tool = loader.get("read_file")
    tool.validate({"path": "x.txt"})     # (ok, errors)
    await tool.invoke(path="x.txt")      # execução (3.3 valida via Security)
"""

from __future__ import annotations

import importlib.util
import inspect
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Union

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.tools.loader")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

DEFAULT_EXTENSIONS = (".py",)
PRIMITIVE_TYPES = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
    "any": Any,
}


# ---------------------------------------------------------------------------
# Exceções
# ---------------------------------------------------------------------------

class ToolLoaderError(Exception):
    """Erro base do Tool Loader."""


class ToolNotFoundError(ToolLoaderError, KeyError):
    """Ferramenta, módulo ou diretório não encontrado."""


class ToolScopeError(ToolLoaderError, PermissionError):
    """Arquivo fora do escopo permitido de diretórios."""


class ToolValidationError(ToolLoaderError, ValueError):
    """Metadados de ferramenta inválidos."""


# ---------------------------------------------------------------------------
# Validação de schema de parâmetros (compartilhada por Tool e Action)
# ---------------------------------------------------------------------------

def validate_params(
    schema: dict[str, Any],
    params: Optional[dict[str, Any]] = None,
) -> tuple[bool, list[str], dict[str, Any]]:
    """Valida params contra um schema e aplica defaults.

    Suporta o formato simplificado:
        {"required": ["path"], "properties": {"path": {"type": "str"}}}
    ou o formato plano:
        {"path": {"type": "str", "required": True, "default": ""}}

    Returns:
        (ok, erros, preenchido) — `preenchido` é o dict com defaults aplicados.
    """
    schema = schema or {}
    given = dict(params or {})
    errors: list[str] = []

    if "required" in schema or "properties" in schema:
        required = list(schema.get("required", []))
        props: dict[str, Any] = dict(schema.get("properties", {}))
    else:
        # formato plano: valor = spec do campo
        required = [k for k, v in schema.items() if v.get("required")]
        props = dict(schema)

    # Aplica defaults
    for key, spec in props.items():
        if key not in given and spec.get("default") is not None:
            given[key] = spec["default"]

    # Obrigatórios presentes
    for key in required:
        if key not in given:
            errors.append(f"parâmetro obrigatório ausente: {key}")

    # Tipos (quando o valor foi fornecido)
    for key, spec in props.items():
        if key not in given:
            continue
        expected = spec.get("type", "any")
        value = given[key]
        if expected == "any":
            continue
        type_cls = PRIMITIVE_TYPES.get(expected)
        if type_cls is None:
            errors.append(f"tipo desconhecido no schema de {key!r}: {expected!r}")
            continue
        if expected == "bool":
            ok_type = isinstance(value, bool)
        elif expected == "int":
            ok_type = isinstance(value, int) and not isinstance(value, bool)
        else:
            ok_type = isinstance(value, type_cls)
        if not ok_type:
            errors.append(f"tipo inválido para {key!r}: esperado {expected}")

    return (not errors, errors, given)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Tool:
    """Uma ferramenta carregada (metadados + callable).

    Attributes:
        name:        Nome único da ferramenta.
        description: Descrição (fallback: docstring da função).
        category:    Categoria (ex: "filesystem", "system", "network").
        fn:          Callable sync/async que implementa a ferramenta.
        params:      Schema dos parâmetros (ver validate_params).
        requires:    Ação exigida no Security Layer quando executada (3.3).
        version:     Versão da ferramenta.
        tags:        Etiquetas livres.
        source:      Caminho do arquivo de origem ("" se manual).
        module:      Nome do módulo de origem ("" se manual).
        registered_at: Timestamp de registro.
    """

    name: str
    fn: Optional[Callable[..., Any]] = None
    description: str = ""
    category: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    requires: str = ""
    version: str = "1.0.0"
    tags: list[str] = field(default_factory=list)
    source: str = ""
    module: str = ""
    registered_at: float = field(default_factory=time.time)

    # -- Propriedades --------------------------------------------------------

    @property
    def is_async(self) -> bool:
        """True se a função é assíncrona (coroutine function)."""
        return self.fn is not None and inspect.iscoroutinefunction(self.fn)

    @property
    def active(self) -> bool:
        """Uma ferramenta sem callable não é executável."""
        return self.fn is not None

    # -- Invocação -----------------------------------------------------------

    async def invoke(self, *args: Any, **kwargs: Any) -> Any:
        """Invoca a ferramenta (sync ou async) de forma assíncrona."""
        if self.fn is None:
            raise ToolValidationError(f"Ferramenta {self.name!r} sem callable")
        result = self.fn(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    # -- Validação de parâmetros --------------------------------------------

    def validate(self, params: Optional[dict[str, Any]] = None) -> tuple[bool, list[str]]:
        """Valida parâmetros contra o schema da ferramenta.

        Returns:
            (ok, erros) — ok False quando há violações.
        """
        ok, errors, _filled = validate_params(self.params, params)
        return ok, errors

    # -- Conversão -----------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "params": self.params,
            "requires": self.requires,
            "version": self.version,
            "tags": list(self.tags),
            "source": self.source,
            "module": self.module,
            "async": self.is_async,
            "active": self.active,
        }

    # -- Fábrica -------------------------------------------------------------

    @classmethod
    def from_entry(
        cls,
        entry: Any,
        *,
        source: str = "",
        module: str = "",
    ) -> "Tool":
        """Constrói uma Tool a partir de dict, Tool ou callable puro."""
        if isinstance(entry, Tool):
            tool = entry
            if source and not tool.source:
                tool.source = source
            if module and not tool.module:
                tool.module = module
            return tool

        if callable(entry):
            return cls(
                name=getattr(entry, "__name__", entry.__class__.__name__),
                fn=entry,
                description=inspect.getdoc(entry) or "",
                source=source,
                module=module,
            )

        if isinstance(entry, dict):
            name = entry.get("name") or entry.get("tool") or entry.get("id")
            if not name:
                raise ToolValidationError(
                    "ferramenta sem nome (esperado 'name'/'tool'/'id')"
                )
            fn = (
                entry.get("fn")
                or entry.get("function")
                or entry.get("func")
                or entry.get("callable")
            )
            if fn is None:
                raise ToolValidationError(
                    f"ferramenta {name!r} sem callable (esperado 'fn'/'function')"
                )
            description = (
                entry.get("description")
                or entry.get("desc")
                or entry.get("doc")
                or (inspect.getdoc(fn) if callable(fn) else "")
                or ""
            )
            tags = entry.get("tags") or []
            return cls(
                name=str(name),
                fn=fn,
                description=str(description),
                category=str(entry.get("category", "")),
                params=dict(entry.get("params") or entry.get("parameters") or entry.get("schema") or {}),
                requires=str(entry.get("requires", "")),
                version=str(entry.get("version", "1.0.0")),
                tags=list(tags) if isinstance(tags, list) else [str(tags)],
                source=source,
                module=module,
            )

        raise ToolValidationError(
            "entrada de ferramenta inválida: esperado dict, Tool ou callable"
        )


# ---------------------------------------------------------------------------
# ToolLoader
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class LoaderMetrics:
    """Métricas do loader."""

    scans: int = 0
    modules_loaded: int = 0
    modules_failed: int = 0
    modules_skipped: int = 0
    tools_loaded: int = 0
    tools_skipped: int = 0  # duplicados
    tools_unloaded: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "scans": self.scans,
            "modules_loaded": self.modules_loaded,
            "modules_failed": self.modules_failed,
            "modules_skipped": self.modules_skipped,
            "tools_loaded": self.tools_loaded,
            "tools_skipped": self.tools_skipped,
            "tools_unloaded": self.tools_unloaded,
        }


class ToolLoader:
    """Carrega e registra ferramentas a partir de módulos Python.

    Attributes:
        dirs:          Diretórios-base para descoberta (escopo estrito).
        recursive:     Varre subdiretórios.
        allow_overwrite: Se True, re-registrar nome substitui o existente.
        extensions:    Extensões de módulo consideradas.
    """

    def __init__(
        self,
        dirs: Optional[Union[str, Path, list[Union[str, Path]]]] = None,
        *,
        recursive: bool = True,
        allow_overwrite: bool = False,
        extensions: tuple[str, ...] = DEFAULT_EXTENSIONS,
    ) -> None:
        if dirs is None:
            base_dirs: list[Path] = []
        elif isinstance(dirs, (str, Path)):
            base_dirs = [Path(dirs)]
        else:
            base_dirs = [Path(d) for d in dirs]

        self.dirs = base_dirs
        self.recursive = recursive
        self.allow_overwrite = allow_overwrite
        self.extensions = tuple(extensions)

        self._tools: dict[str, Tool] = {}
        self._modules: dict[str, Path] = {}  # módulo importado -> arquivo
        self._errors: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        self._metrics = LoaderMetrics()

    # -- Propriedades --------------------------------------------------------

    @property
    def metrics(self) -> LoaderMetrics:
        return self._metrics

    @property
    def errors(self) -> list[dict[str, Any]]:
        """Erros recentes de carga (módulos que falharam ao importar)."""
        return list(self._errors)

    def list_tools(self) -> list[dict[str, Any]]:
        """Snapshot de todas as ferramentas registradas."""
        return [t.to_dict() for t in self._tools.values()]

    # -- Descoberta ----------------------------------------------------------

    def _discover(self, directory: Path) -> list[Path]:
        """Lista arquivos de módulo dentro do diretório (com escopo)."""
        if not directory.exists() or not directory.is_dir():
            raise ToolNotFoundError(f"Diretório de ferramentas não encontrado: {directory}")
        if self.recursive:
            files = [p for p in directory.rglob("*") if p.is_file()]
        else:
            files = [p for p in directory.glob("*") if p.is_file()]
        result: list[Path] = []
        for path in files:
            if path.suffix not in self.extensions:
                continue
            if path.name.startswith(("_", ".")):
                continue
            result.append(path)
        return sorted(result)

    # -- Carga ---------------------------------------------------------------

    def load_all(self) -> int:
        """Carrega todos os diretórios base configurados.

        Returns:
            Número de ferramentas novas registradas.
        """
        total = 0
        for directory in self.dirs:
            total += self.load_dir(directory)
        self._metrics.scans += 1
        return total

    def load_dir(self, directory: Union[str, Path]) -> int:
        """Carrega todos os módulos de um diretório.

        Raises:
            ToolNotFoundError: diretório inexistente.
            ToolScopeError: diretório fora dos diretórios-base (quando há).
        """
        path = Path(directory)
        self._ensure_in_scope(path)
        loaded = 0
        for module_file in self._discover(path):
            loaded += self._load_module_file(module_file)
        return loaded

    def load_source(self, source: Union[str, Path]) -> int:
        """Carrega um único arquivo de módulo.

        Raises:
            ToolScopeError: arquivo fora do escopo (quando dirs configurados).
            ToolNotFoundError: arquivo inexistente ou sem extensão válida.
        """
        path = Path(source)
        self._ensure_in_scope(path)
        if not path.exists():
            raise ToolNotFoundError(f"Arquivo de ferramenta não encontrado: {path}")
        if path.suffix not in self.extensions or path.name.startswith("_"):
            raise ToolNotFoundError(f"Arquivo não é um módulo carregável: {path}")
        return self._load_module_file(path)

    # -- Interno: carregar módulo -------------------------------------------

    def _load_module_file(self, path: Path) -> int:
        """Importa um módulo e registra suas ferramentas. Retorna nº novo.

        Em falha de import/extração, nenhuma ferramenta antiga do mesmo
        arquivo é removida (reload seguro: versão anterior permanece).
        """
        module_name = f"_od_tool_{uuid.uuid4().hex[:10]}_{path.stem}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise ToolValidationError("spec_from_file_location falhou")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # executa o código do plugin
        except Exception as exc:
            self._metrics.modules_failed += 1
            record = {
                "source": str(path),
                "error": f"{type(exc).__name__}: {exc}",
                "ts": time.time(),
            }
            self._errors.append(record)
            if len(self._errors) > 100:
                self._errors = self._errors[-100:]
            log.crit(
                "Tool module load failed",
                source=str(path),
                error=record["error"],
            )
            return 0

        entries = self._extract_entries(module, path)
        if entries is None:
            self._metrics.modules_skipped += 1
            log.warn(
                "Tool module skipped (sem contrato TOOLS/PLUGIN/load_tools)",
                source=str(path),
            )
            return 0

        # Só agora remove a versão antiga do mesmo arquivo (se houver)
        self._drop_source(str(path))

        self._modules[module_name] = path
        self._metrics.modules_loaded += 1

        count = 0
        for entry in entries:
            try:
                if self.register(entry, source=str(path), module=module_name):
                    count += 1
            except ToolValidationError as exc:
                # Entrada inválida não derruba o resto do módulo
                self._metrics.tools_skipped += 1
                log.warn(
                    "Tool entry invalid",
                    source=str(path),
                    error=str(exc),
                )
        log.info(
            "Tool module loaded",
            source=str(path),
            tools=count,
        )
        return count

    @staticmethod
    def _extract_entries(
        module: Any,
        path: Path,
    ) -> Optional[list[Any]]:
        """Extrai a lista de entradas de ferramenta do módulo carregado."""
        plugin = getattr(module, "PLUGIN", None)
        if isinstance(plugin, dict):
            tools = plugin.get("tools")
            if tools is not None:
                return list(tools)

        tools = getattr(module, "TOOLS", None)
        if tools is not None:
            return list(tools)

        loader_fn = getattr(module, "load_tools", None)
        if callable(loader_fn):
            try:
                result = loader_fn()
            except Exception as exc:
                raise ToolValidationError(
                    f"load_tools() falhou em {path.name}: {type(exc).__name__}: {exc}"
                ) from exc
            if result is not None:
                return list(result)

        return None

    def _drop_source(self, source: str) -> None:
        """Remove ferramentas/módulos previamente carregados de um arquivo."""
        removed = [name for name, t in self._tools.items() if t.source == source]
        for name in removed:
            self._tools.pop(name, None)
        self._modules = {m: p for m, p in self._modules.items() if str(p) != source}
        if removed:
            self._metrics.tools_unloaded += len(removed)

    # -- Registro ------------------------------------------------------------

    def register(
        self,
        entry: Any,
        *,
        source: str = "",
        module: str = "",
    ) -> bool:
        """Registra uma ferramenta (dict, Tool ou callable).

        Returns:
            True se registrada; False se nome duplicado (e overwrite off).
        """
        tool = Tool.from_entry(entry, source=source, module=module)
        with self._lock:
            existing = self._tools.get(tool.name)
            if existing is not None and not self.allow_overwrite:
                self._metrics.tools_skipped += 1
                log.warn(
                    "Tool skipped (nome duplicado)",
                    tool=tool.name,
                    existing_source=existing.source or "manual",
                )
                return False
            self._tools[tool.name] = tool
        self._metrics.tools_loaded += 1
        log.info(
            "Tool registered",
            tool=tool.name,
            category=tool.category or "-",
            async_=tool.is_async,
            source=tool.source or "manual",
        )
        return True

    # -- Consulta ------------------------------------------------------------

    def has(self, name: str) -> bool:
        return name in self._tools

    def get(self, name: str) -> Tool:
        """Retorna a ferramenta registrada (eleva ToolNotFoundError)."""
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFoundError(f"Ferramenta não registrada: {name}")
        return tool

    def find(self, category: Optional[str] = None) -> list[Tool]:
        """Lista ferramentas (opcionalmente filtradas por categoria)."""
        return [
            t for t in self._tools.values()
            if category is None or t.category == category
        ]

    # -- Remoção e reload ----------------------------------------------------

    def unload(self, name: str) -> bool:
        """Remove uma ferramenta registrada. Retorna True se existia."""
        with self._lock:
            tool = self._tools.pop(name, None)
        if tool is None:
            return False
        self._metrics.tools_unloaded += 1
        log.info("Tool unloaded", tool=name)
        return True

    def unload_source(self, source: str) -> int:
        """Remove todas as ferramentas originárias de um arquivo."""
        with self._lock:
            names = [n for n, t in self._tools.items() if t.source == source]
            for name in names:
                self._tools.pop(name, None)
        if names:
            self._metrics.tools_unloaded += len(names)
            log.info("Tools unloaded by source", source=source, count=len(names))
        return len(names)

    def reload(self, name: str) -> bool:
        """Recarrega do disco a ferramenta (via arquivo de origem).

        Retorna True se a ferramenta existia e seu módulo foi recarregado.
        Em falha de reload, a ferramenta antiga permanece registrada.
        """
        tool = self.get(name)
        if not tool.source:
            log.warn("Reload ignorado (ferramenta manual)", tool=name)
            return False
        path = Path(tool.source)
        try:
            # Carrega nova versão; register sobrescreve a antiga via _drop_source
            count = self.load_source(path)
            return count > 0 and self.has(name)
        except Exception as exc:
            log.crit(
                "Tool reload failed",
                tool=name,
                error=f"{type(exc).__name__}: {exc}",
            )
            return False

    def reload_all(self) -> int:
        """Recarrega todos os diretórios-base. Retorna nº de ferramentas."""
        return self.load_all()

    def clear(self) -> int:
        """Remove todas as ferramentas e módulos. Retorna nº removido."""
        with self._lock:
            count = len(self._tools)
            self._tools.clear()
            self._modules.clear()
        self._metrics.tools_unloaded += count
        log.info("ToolLoader cleared", removed=count)
        return count

    # -- Escopo --------------------------------------------------------------

    def _ensure_in_scope(self, path: Path) -> None:
        """Garante que o caminho está dentro dos diretórios-base (se houver)."""
        if not self.dirs:
            return
        resolved = path.resolve()
        for directory in self.dirs:
            base = directory.resolve()
            try:
                resolved.relative_to(base)
                return
            except ValueError:
                continue
        raise ToolScopeError(
            f"Caminho fora do escopo do ToolLoader: {path} "
            f"(permitidos: {[str(d) for d in self.dirs]})"
        )

    # -- Inspeção ------------------------------------------------------------

    def dump(self) -> dict[str, Any]:
        """Snapshot diagnóstico completo do loader."""
        return {
            "dirs": [str(d) for d in self.dirs],
            "recursive": self.recursive,
            "allow_overwrite": self.allow_overwrite,
            "tools": len(self._tools),
            "modules": len(self._modules),
            "errors": len(self._errors),
            "metrics": self._metrics.snapshot(),
            "catalog": self.list_tools(),
        }
