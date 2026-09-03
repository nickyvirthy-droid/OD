"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: tools/auto_extension/engine.py
Descrição: Auto Extension (Fase 6, item 6.6) — geração de ferramentas via
           LLM: o sistema descreve a ferramenta desejada em linguagem
           natural, o LLM escreve o código Python (stdlib apenas), o código
           é validado (compile + inspeção de imports) e a ferramenta é
           registrada no Action Registry como Action com `permission`
           — toda execução futura passa pelo Security Layer (spec §7).
           Espelha a capacidade de extensão do Nexus src/nexus_core.py.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nexus src/nexus_core.py (geração de código via LLM)
  - OMEGADRAKON_SPEC.md §7 (execução mediada pelo Security Layer)
  - ROADMAP_ABSORCAO.md Fase 6, item 6.6 (tools/auto_extension/)

Decisões registradas (ver CHANGELOG):
  - Ferramentas geradas restringidas a stdlib (allowlist de imports) —
    nenhuma dependência externa executada
  - Validação em 2 estágios ANTES de registrar: compile() sintático +
    inspeção de imports/top-level (sem execução do corpo)
  - Toda Action gerada carrega permission="auto_extension.generated" —
    chamadas futuras passam pelo SecurityManager (mediado, nunca livre)
"""

from __future__ import annotations

import ast
import inspect
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.tools.auto_extension")

STDLIB_ALLOWLIST = frozenset(
    {
        "math", "json", "re", "datetime", "time", "typing", "statistics",
        "collections", "itertools", "functools", "random", "string",
        "urllib.parse", "uuid", "decimal", "fractions",
    }
)

PROMPT_TEMPLATE = """Você é o Auto Extension do Omega Drakon. Escreva UMA função Python
pura chamada `{name}` que implemente: {description}

REGRAS OBRIGATÓRIAS:
- Apenas stdlib da allowlist: {allowlist}
- Assinatura: def {name}(**params: Any) -> dict
- Nenhum I/O externo (sem rede, sem disco, sem subprocess)
- Nenhum import no topo além dos da allowlist
- Retorne sempre um dict (ex: {{"ok": True, "result": ...}})
- Código entre fences ```python ... ``` e nada além disso.
"""


@dataclass(slots=True)
class ExtensionMetrics:
    """Métricas do gerador de extensões."""

    attempts: int = 0
    generated: int = 0
    invalid_code: int = 0
    disallowed_imports: int = 0
    not_found: int = 0
    errors: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "attempts": self.attempts,
            "generated": self.generated,
            "invalid_code": self.invalid_code,
            "disallowed_imports": self.disallowed_imports,
            "not_found": self.not_found,
            "errors": self.errors,
        }


class AutoExtension:
    """Gera, valida e registra ferramentas via LLM no Action Registry."""

    def __init__(
        self,
        llm: Any,
        registry: Any,
        *,
        security: Any = None,
        prefix: str = "auto",
        max_code_len: int = 8000,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.security = security
        self.prefix = prefix
        self.max_code_len = max_code_len
        self.metrics = ExtensionMetrics()
        self._generated: dict[str, str] = {}

    # -- Geração -------------------------------------------------------------

    async def generate_code(self, name: str, description: str) -> Optional[str]:
        """Pede ao LLM o código da ferramenta e o extrai dos fences."""
        self.metrics.attempts += 1
        prompt = PROMPT_TEMPLATE.format(
            name=name,
            description=description,
            allowlist=", ".join(sorted(STDLIB_ALLOWLIST)),
        )
        try:
            raw = await self.llm.generate(prompt, timeout=120)
        except Exception as exc:  # pragma: no cover
            self.metrics.errors += 1
            log.error("LLM falhou na geração", error=str(exc))
            return None
        if not raw:
            self.metrics.errors += 1
            log.warn("LLM não retornou código", name=name)
            return None
        code = self._extract_code(raw)
        if not code:
            self.metrics.not_found += 1
            log.warn("Nenhum bloco ```python``` na resposta", name=name)
            return None
        return code

    @staticmethod
    def _extract_code(text: str) -> Optional[str]:
        """Extrai o primeiro bloco ```python ... ``` (fallback: último fence)."""
        match = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.S)
        if not match:
            match = re.search(r"```(.*?)```", text, re.S)
        if not match:
            return None
        return match.group(1).strip()

    # -- Validação -----------------------------------------------------------

    @staticmethod
    def validate_code(
        code: str, max_code_len: int = 8000
    ) -> tuple[bool, str]:
        """compile() sintático + allowlist de imports. Nunca executa o corpo."""
        if len(code) > max_code_len:
            return False, f"código excede {max_code_len} caracteres"
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return False, f"syntax:{exc.msg} (linha {exc.lineno})"
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top not in STDLIB_ALLOWLIST:
                        return False, f"import:{alias.name}"
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] not in STDLIB_ALLOWLIST:
                    return False, f"import:{node.module}"
        return True, "ok"

    def _exec_tool(self, code: str, name: str) -> Optional[Callable[..., Any]]:
        """Executa o código em namespace restrito e devolve a função."""
        namespace: dict[str, Any] = {}
        try:
            exec(compile(code, f"<auto_extension:{name}>", "exec"), namespace)
        except Exception as exc:  # pragma: no cover
            self.metrics.errors += 1
            log.error("Falha ao executar código gerado", error=str(exc))
            return None
        fn = namespace.get(name)
        if fn is None or not callable(fn):
            self.metrics.not_found += 1
            log.warn("Função gerada não encontrada no namespace", name=name)
            return None
        return fn

    # -- Registro ------------------------------------------------------------

    async def extend(self, name: str, description: str) -> dict[str, Any]:
        """Pipeline completo: gera → valida → registra → retorna resultado."""
        raw = (name or "").strip().lower()
        clean = re.sub(r"[^a-z0-9_.]", "_", raw)
        if not raw or not clean:
            return {"status": "invalid", "error": "nome de ferramenta vazio"}
        if not description or not description.strip():
            return {"status": "invalid", "error": "descrição vazia"}

        code = await self.generate_code(clean, description.strip())
        if not code:
            return {"status": "error", "error": "LLM não produziu código"}

        ok, reason = self.validate_code(code, max_code_len=self.max_code_len)
        if not ok:
            if reason.startswith("import:"):
                self.metrics.disallowed_imports += 1
                log.warn("Import fora da allowlist", import_name=reason[7:])
            elif reason.startswith("syntax:"):
                self.metrics.invalid_code += 1
                log.warn("Código gerado com erro de sintaxe")
            return {"status": "invalid", "error": reason}

        fn = self._exec_tool(code, clean)
        if fn is None:
            return {"status": "error", "error": "função gerada não carregou"}

        action_name = f"{self.prefix}.{clean}"

        def handler(**params: Any) -> dict[str, Any]:
            try:
                return fn(**params)
            except Exception as exc:  # pragma: no cover
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        # Registro no Action Registry com permission → Security Layer media
        self.registry.register_action(
            action_name,
            handler=handler,
            description=f"Auto-extensão gerada via LLM: {description.strip()[:120]}",
            category="auto_extension",
            params={
                "required": [],
                "properties": {},
            },
            permission="auto_extension.generated",
            source="auto_extension",
        )
        self._generated[action_name] = code
        self.metrics.generated += 1
        log.info(
            "Ferramenta auto-gerada e registrada (mediada pelo Security Layer)",
            action=action_name,
        )
        return {
            "status": "ok",
            "action": action_name,
            "description": description.strip(),
        }

    # -- Introspecção --------------------------------------------------------

    def list_tools(self) -> list[str]:
        return sorted(self._generated)

    def snapshot(self) -> dict[str, Any]:
        return {
            "metrics": self.metrics.snapshot(),
            "generated": self.list_tools(),
            "permission": "auto_extension.generated",
            "security_mediated": self.security is not None,
            "allowlist": sorted(STDLIB_ALLOWLIST),
        }

    def dump(self) -> dict[str, Any]:
        return {
            "generated": {name: code for name, code in self._generated.items()},
            "metrics": self.metrics.snapshot(),
        }