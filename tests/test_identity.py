"""
OMEGA DRAKON • TESTS
Módulo: tests/test_identity.py
Descrição: testes do resolvedor de identidade (core/identity.py) — o mapa
           `OD_ACCOUNT_ALIASES` que aponta ids legados de transporte (app,
           Telegram) para a conta do dono.

Baseado em:
  - core/identity.py
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

from core.identity import ALIASES_ENV, parse_aliases, resolve_account


class TestParseAliases:
    def test_mapa_simples(self) -> None:
        assert parse_aliases("app=alex") == {"app": "alex"}

    def test_multiplos_e_espacos(self) -> None:
        assert parse_aliases("app=alex, 660518870 = alex ") == {
            "app": "alex",
            "660518870": "alex",
        }

    def test_vazio_ou_ausente(self) -> None:
        assert parse_aliases("") == {}
        assert parse_aliases(None) == {}

    def test_entradas_malformadas_ignoradas(self) -> None:
        # Sem '=', ou com um dos lados vazio, a entrada cai fora — uma env
        # torta não pode derrubar a identidade.
        assert parse_aliases("app,=,alex,=alex,sem_destino=") == {}

    def test_ultimo_vence_em_chave_repetida(self) -> None:
        assert parse_aliases("app=alex,app=bia") == {"app": "bia"}

    def test_env_var_conhecida(self) -> None:
        # Contrato com o launcher: é essa env que carrega o mapa.
        assert ALIASES_ENV == "OD_ACCOUNT_ALIASES"


class TestResolveAccount:
    ALIASES = {"app": "alex", "660518870": "alex"}

    def test_id_legado_vira_conta(self) -> None:
        assert resolve_account("app", self.ALIASES) == "alex"
        assert resolve_account("660518870", self.ALIASES) == "alex"

    def test_sem_alias_para_o_id(self) -> None:
        assert resolve_account("web", self.ALIASES) == "web"

    def test_mapa_vazio_ou_ausente_preserva_o_id(self) -> None:
        assert resolve_account("app", {}) == "app"
        assert resolve_account("app", None) == "app"

    def test_case_insensitive_na_origem(self) -> None:
        assert resolve_account("APP", self.ALIASES) == "alex"

    def test_strip_e_id_vazio(self) -> None:
        assert resolve_account("  app  ", self.ALIASES) == "alex"
        assert resolve_account("", self.ALIASES) == ""
        assert resolve_account(None, self.ALIASES) == ""
