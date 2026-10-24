"""
OMEGA DRAKON • TESTES
Módulo: tests/test_action_registry.py
Descrição: Núcleo do Action Registry (tools/registry.py) — o contrato de
           VERSÃO no registro, fechado em 23/10 como item 4 da dívida
           técnica §4: `version` nunca era comparado aqui (só no Supply
           Depot). Agora um overwrite com versão diferente é comparado e
           LOGADO (upgrade em info, downgrade em warn) — o registro nunca
           substitui em silêncio. Quem BLOQUEIA downgrade segue sendo o
           Depot (pré-voo com política): a semântica de overwrite não
           muda, só a visibilidade.
"""
from __future__ import annotations

from tools.registry import Action, ActionRegistry, _eh_downgrade, log as reg_log


def _acao(nome: str = "demo.action", version: str = "1.0.0") -> Action:
    return Action(
        name=nome,
        handler=lambda: {"ok": True},
        description="ação de teste",
        category="teste",
        version=version,
        source="teste",
    )


def _registros_de_versao() -> list:
    return [r for r in reg_log.records
            if "re-registrada com versão diferente" in r.message
            or "nome duplicado" in r.message]


class TestVersaoComparadaNoRegistro:
    """O `version` é comparado no register() (upgrade/downgrade visíveis)."""

    def test_overwrite_com_versao_maior_loga_upgrade(self) -> None:
        reg = ActionRegistry(allow_overwrite=True)
        reg.register(_acao(version="1.0.0"))
        reg_log.clear_records()
        assert reg.register(_acao(version="1.1.0")) is True
        # semântica preservada: a nova versão é a registrada
        assert reg._actions["demo.action"].version == "1.1.0"
        registros = _registros_de_versao()
        assert len(registros) == 1
        r = registros[0]
        assert r.level_name == "INFO"              # upgrade não é alerta
        assert r.context["versao_existente"] == "1.0.0"
        assert r.context["versao_nova"] == "1.1.0"

    def test_overwrite_com_versao_menor_loga_downgrade_em_warn(self) -> None:
        reg = ActionRegistry(allow_overwrite=True)
        reg.register(_acao(version="1.1.0"))
        reg_log.clear_records()
        assert reg.register(_acao(version="1.0.0")) is True
        registros = _registros_de_versao()
        assert len(registros) == 1
        r = registros[0]
        assert r.level_name == "WARN"              # downgrade é alerta
        assert r.context["versao_existente"] == "1.1.0"
        assert r.context["versao_nova"] == "1.0.0"

    def test_versao_igual_nao_gera_log_de_versao(self) -> None:
        reg = ActionRegistry(allow_overwrite=True)
        reg.register(_acao(version="2.3.4"))
        reg_log.clear_records()
        reg.register(_acao(version="2.3.4"))
        assert _registros_de_versao() == []

    def test_lado_nao_semver_nao_vira_downgrade(self) -> None:
        """Sem comparação inventada: qualquer lado não-semver não é
        classificado como downgrade (info, nunca warn)."""
        reg = ActionRegistry(allow_overwrite=True)
        reg.register(_acao(version="beta"))
        reg_log.clear_records()
        reg.register(_acao(version="1.0.0"))
        registros = _registros_de_versao()
        assert len(registros) == 1
        assert registros[0].level_name == "INFO"

    def test_duplicado_sem_overwrite_agora_expe_as_duas_versoes(self) -> None:
        """O skip de nome duplicado também declara as duas versões — a
        divergência visível mesmo quando nada é substituído."""
        reg = ActionRegistry()
        reg.register(_acao(version="1.0.0"))
        reg_log.clear_records()
        assert reg.register(_acao(version="9.9.9")) is False
        registros = _registros_de_versao()
        assert len(registros) == 1
        r = registros[0]
        assert r.level_name == "WARN"
        assert r.context["existing_version"] == "1.0.0"
        assert r.context["nova_versao"] == "9.9.9"


class TestEhDowngrade:
    """A comparação em si (reusa o _parse_semver da Parte E)."""

    def test_semver_menor_e_downgrade(self) -> None:
        assert _eh_downgrade("1.2.3", "1.2.2") is True
        assert _eh_downgrade("2.0.0", "1.9.9") is True

    def test_semver_maior_ou_igual_nao_e_downgrade(self) -> None:
        assert _eh_downgrade("1.2.3", "1.2.4") is False
        assert _eh_downgrade("1.2.3", "1.2.3") is False

    def test_nao_semver_e_false(self) -> None:
        assert _eh_downgrade("beta", "1.0.0") is False
        assert _eh_downgrade("1.0.0", "beta") is False
        assert _eh_downgrade("", "1.0.0") is False
