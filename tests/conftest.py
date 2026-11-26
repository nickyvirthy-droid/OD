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

import os
import tempfile
from pathlib import Path

import pytest

# Guarda da cota de LLM (17/11/2026): a suíte NÃO pode depender do consumo
# real do dia. `core.resilience` lê `OD_QUOTA_FILE` no import; sem esta
# linha, `data/llm_quota.json` (o arquivo do dono) vira estado de teste —
# com o Gemini esgotado (20/20) o Orchestrator pula o provider e testes de
# fallback/cota quebram sem nenhum código errado (foi o que derrubou o gate
# de 17/11 depois de um dia de uso real). O conftest é importado ANTES dos
# módulos de teste, então o caminho temporário vale para toda a suíte.
# Testes que querem controlar a cota usam `OD_QUOTA_FILE` + tracker próprio
# (ver tests/test_llm_quota_health.py).
os.environ["OD_QUOTA_FILE"] = str(
    Path(tempfile.mkdtemp(prefix="od-quota-testes-")) / "llm_quota.json"
)

# Guarda de configuração de RUNTIME (23/11/2026): a cascata de IAs exporta o
# `.env` real no ambiente do pytest (`OD_ORCHESTRATOR_GRAPH=1`,
# `OD_CHAT_PROVIDERS=groq,gemini,local`, `OD_IA_ORDEM=groq,...`). A suíte
# herdava isso e 52 testes que exercitam a rota DIRETA e a cadeia PADRÃO
# ficavam vermelhos sem nenhum defeito de código (histórico: 53 failed
# repetidos depois de uma rodada verde). Igual à cota acima, o conftest roda
# ANTES dos módulos de teste: quem precisa do grafo ligado ou de outra ordem
# liga por `monkeypatch.setenv` dentro do próprio teste
# (`tests/test_orchestrator_graph_integration.py`, `tests/test_llm.py`).
VARS_RUNTIME = (
    "OD_ORCHESTRATOR_GRAPH",
    "OD_CHAT_PROVIDERS",
    "OD_IA_ORDEM",
)
for _variavel_de_runtime in VARS_RUNTIME:
    os.environ.pop(_variavel_de_runtime, None)

# Janela de boot do /health (26/11/2026): `build_health()` marca `tool_*`/`mqtt`
# falhando como `starting` nos primeiros 5 min depois do boot. A suíte não pode
# depender do uptime da MÁQUINA — rodar o gate logo após um reboot mudaria o
# status de `/health` em todo teste que simula `mqtt`/tool fora do ar. Desligada
# por padrão; o teste da janela liga com `monkeypatch.setenv`.
os.environ["OD_HEALTH_JANELA_BOOT_S"] = "0"


@pytest.fixture(autouse=True)
def _runtime_sempre_limpo():
    """Apaga o trio de runtime no início de CADA teste (26/11/2026).

    O `pop` do import protege só o começo da suíte: um teste que rode uma CLI
    em processo reabria as três variáveis no meio da rodada e todos os
    testes seguintes mudavam de rota. Caso real medido em 26/11:
    `tests/test_verificar_restauracao_pg.py` chama
    `runtime.verificar_restauracao_pg.main()`, que chama `load_dotenv(.env)`
    quando não há `TELEGRAM_*` no ambiente — o python-dotenv escrevia
    `OD_ORCHESTRATOR_GRAPH=1` no `os.environ` e os 2 testes de streaming de
    `tests/test_websocket.py` (que esperam o caminho DIRETO) falhavam por
    ordem, sem nenhum defeito de código.

    Ordem: esta fixture é autouse e do conftest da suíte, então roda ANTES do
    `monkeypatch` do teste — quem precisa do grafo (`setenv`) continua
    funcionando e o `monkeypatch` devolve o ambiente limpo ao terminar.
    """
    for _variavel in VARS_RUNTIME:
        os.environ.pop(_variavel, None)


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


@pytest.fixture(autouse=True)
def _memoria_longao_isolada(tmp_path, monkeypatch):
    """Memória longa (F4): cada teste usa um SQLite próprio (nunca data/).

    O Orchestrator grava fatos no `_post_process` (melhor esforço), então a
    suíte precisa apontar `OD_MEMORY_PATH` para tmp e descartar o singleton
    entre testes — senão o banco real do dono ganharia fatos da suíte.
    """
    from core import memory_layer

    monkeypatch.setenv("OD_MEMORY_PATH", str(tmp_path / "memory.db"))
    # F4 fase 4: a suíte nunca fala com provider de embedding (rede/cota).
    monkeypatch.setenv("OD_MEMORY_EMBEDDING", "off")
    memory_layer.resetar_memoria()
    yield
    memory_layer.resetar_memoria()
