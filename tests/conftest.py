"""
OMEGA DRAKON • TESTS
Módulo: tests/conftest.py
Descrição: configurações compartilhadas da suíte. Guarda da Casa de
           Limitações (2026-10-01): `pytest` NÃO suja o `limitacoes.txt`
           REAL da raiz — os hooks do Orchestrator
           (`registrar_action_degradada` / `registrar_fallback_honesto`)
           disparam durante testes de integração que simulam ações
           degradadas ('quantas pessoas na rede?' com /proc vazio,
           'qual a temperatuda em presidente venceslau sp' sem fonte) e,
           sem esta guarda, cada rodada da suíte gravava eventos falsos
           no registro do sistema (caso real: 4 rodadas de pytest em
           01/10 geraram blocos idênticos "action_degradada" no arquivo,
           confundindo a auditoria do dono).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Mecânica: fixture autouse redireciona `core.limitacoes.LIMITACOES_FILE`
para um arquivo dentro de `tmp_path` (isolado por teste). Testes que
DEPENDEM do redirecionamento por `monkeypatch.chdir` continuam válidos:
a fixture só muda o DEFAULT; quem fizer chdir sobrepõe.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _limitacoes_isoladas(tmp_path, monkeypatch):
    """Redireciona o limitacoes.txt da suíte para tmp_path (por teste)."""
    from core import limitacoes

    destino = tmp_path / "limitacoes.txt"
    monkeypatch.setattr(limitacoes, "LIMITACOES_FILE", destino)
    # Dedup em memória também é isolado por teste (senão um teste que
    # registra bloqueia o registro do seguinte na mesma chave).
    monkeypatch.setattr(limitacoes, "_ultimo_registro", {})
    yield
