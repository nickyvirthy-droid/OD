"""
OMEGA DRAKON • TESTS
Módulo: tests/test_auto_extension.py
Descrição: Testes do Auto Extension (Fase 6, item 6.6): extração de código
           da resposta do LLM, validação (compile + allowlist de imports),
           pipeline extend() completo com LLM fake e registro no Action
           Registry com permission mediada pelo Security Layer.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import asyncio

import pytest

from tools.auto_extension import AutoExtension
from tools.auto_extension.engine import STDLIB_ALLOWLIST
from tools.registry import ActionRegistry

GOOD_CODE = '''```python
import math

def area_circulo(**params):
    raio = params.get("raio", 0)
    return {"ok": True, "result": round(math.pi * raio ** 2, 2)}
```'''

BAD_IMPORT_CODE = '''```python
import os

def roubo(**params):
    return {"ok": True, "files": os.listdir("/")}
```'''

SYNTAX_ERROR_CODE = '''```python
def quebrada(**params):
    return {  # falta fechar
```'''


class FakeLLM:
    def __init__(self, code: str) -> None:
        self._code = code
        self.prompts: list[str] = []

    async def generate(self, prompt: str, **options) -> str:
        self.prompts.append(prompt)
        return self._code


class FakeLLMSilent:
    async def generate(self, prompt: str, **options) -> None:
        return None


def build(registry: ActionRegistry, llm) -> AutoExtension:
    return AutoExtension(llm, registry)


class TestExtractCode:
    def test_extrai_fence_python(self) -> None:
        assert "def area" in AutoExtension._extract_code(GOOD_CODE)

    def test_sem_fence_retorna_none(self) -> None:
        assert AutoExtension._extract_code("sem código aqui") is None

    def test_extrai_fence_sem_label(self) -> None:
        assert AutoExtension._extract_code("```\ndef x(**p): return {}\n```") is not None


class TestValidateCode:
    def test_codigo_valido(self) -> None:
        # valida o código extraído (sem fences) — pipeline real
        code = AutoExtension._extract_code(GOOD_CODE)
        ok, reason = AutoExtension.validate_code(code)
        assert ok and reason == "ok"

    def test_import_fora_da_allowlist(self) -> None:
        code = AutoExtension._extract_code(BAD_IMPORT_CODE)
        ok, reason = AutoExtension.validate_code(code)
        assert not ok and "os" in reason

    def test_erro_de_sintaxe(self) -> None:
        code = AutoExtension._extract_code(SYNTAX_ERROR_CODE)
        ok, reason = AutoExtension.validate_code(code)
        assert not ok and "syntax" in reason

    def test_tamanho_maximo(self) -> None:
        huge = "def x(**p): return {}\n" * 10000
        ok, _ = AutoExtension.validate_code(huge)
        assert not ok

    def test_allowlist_tem_stdlib_basico(self) -> None:
        assert {"math", "json", "re", "datetime"} <= STDLIB_ALLOWLIST


class TestExtend:
    def test_pipeline_completo_registra_action(self) -> None:
        registry = ActionRegistry()
        ext = build(registry, FakeLLM(GOOD_CODE))

        async def run() -> None:
            result = await ext.extend("area_circulo", "calcula a área de um círculo")
            assert result["status"] == "ok"
            assert result["action"] == "auto.area_circulo"
            assert "auto.area_circulo" in ext.list_tools()
            # a action registrada carrega permission (Security Layer media)
            action = registry.get("auto.area_circulo")
            assert action.permission == "auto_extension.generated"
            assert action.category == "auto_extension"

        asyncio.run(run())

    def test_action_executa_codigo_gerado(self) -> None:
        registry = ActionRegistry()
        ext = build(registry, FakeLLM(GOOD_CODE))

        async def run() -> None:
            await ext.extend("area_circulo", "calcula a área de um círculo")
            out = await registry.execute(
                "auto.area_circulo", params={"raio": 2}, role="agent"
            )
            assert out.status == "ok"
            assert out.data["result"] == pytest.approx(12.57, abs=0.01)

        asyncio.run(run())

    def test_import_proibido_nao_registra(self) -> None:
        registry = ActionRegistry()
        ext = build(registry, FakeLLM(BAD_IMPORT_CODE))

        async def run() -> None:
            result = await ext.extend("roubo", "lista arquivos")
            assert result["status"] == "invalid"
            assert ext.metrics.disallowed_imports == 1
            assert "roubo" not in ext.list_tools()

        asyncio.run(run())

    def test_sintaxe_invalida_nao_registra(self) -> None:
        registry = ActionRegistry()
        ext = build(registry, FakeLLM(SYNTAX_ERROR_CODE))

        async def run() -> None:
            result = await ext.extend("quebrada", "função quebrada")
            assert result["status"] == "invalid"
            assert ext.metrics.invalid_code == 1

        asyncio.run(run())

    def test_llm_silencioso_retorna_error(self) -> None:
        registry = ActionRegistry()
        ext = build(registry, FakeLLMSilent())

        async def run() -> None:
            result = await ext.extend("vazia", "nada")
            assert result["status"] == "error"

        asyncio.run(run())

    def test_nome_vazio_invalido(self) -> None:
        registry = ActionRegistry()
        ext = build(registry, FakeLLM(GOOD_CODE))

        async def run() -> None:
            assert (await ext.extend("   ", "desc"))["status"] == "invalid"
            assert (await ext.extend("ok", "  "))["status"] == "invalid"

        asyncio.run(run())

    def test_metrica_generated(self) -> None:
        registry = ActionRegistry()
        ext = build(registry, FakeLLM(GOOD_CODE))

        async def run() -> None:
            await ext.extend("area_circulo", "calcula área")
            await ext.extend("area_circulo", "calcula área")
            assert ext.metrics.generated == 2
            assert ext.metrics.attempts == 2

        asyncio.run(run())

    def test_snapshot(self) -> None:
        registry = ActionRegistry()
        ext = build(registry, FakeLLM(GOOD_CODE))
        snap = ext.snapshot()
        assert snap["security_mediated"] is False
        assert snap["permission"] == "auto_extension.generated"
        assert "math" in snap["allowlist"]