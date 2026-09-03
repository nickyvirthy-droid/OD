"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Pacote: tools/auto_extension/
Descrição: Auto Extension (Fase 6, item 6.6) — geração de ferramentas via
           LLM com validação (compile + allowlist de imports) e registro no
           Action Registry mediado pelo Security Layer (spec §7).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Módulos:
  - engine.py → AutoExtension (geração → validação → registro)
"""

from tools.auto_extension.engine import (
    PROMPT_TEMPLATE,
    STDLIB_ALLOWLIST,
    AutoExtension,
    ExtensionMetrics,
)

__signature__ = "OD // CORE"
__all__ = [
    "AutoExtension",
    "ExtensionMetrics",
    "STDLIB_ALLOWLIST",
    "PROMPT_TEMPLATE",
]