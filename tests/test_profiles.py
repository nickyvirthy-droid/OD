"""
OMEGA DRAKON • TESTS
Módulo: tests/test_profiles.py
Descrição: Testes do Profile Manager (Fase 6, item 6.5): 6 perfis oficiais,
           detecção automática por domínio, resolução (explícito > auto >
           default), perfis customizados e prompt combinado.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

from agents.profiles import DEFAULT_PROFILE, ProfileManager


class TestProfileManager:
    def setup_method(self) -> None:
        self.pm = ProfileManager()

    def test_seis_perfis_oficiais(self) -> None:
        names = self.pm.list_profiles()
        assert names == ["guardian", "regulus", "luma", "vox", "athenae", "nyx"]

    def test_metadados_essenciais(self) -> None:
        for name, profile in self.pm.profiles.items():
            assert profile["name"]
            assert profile["title"]
            assert profile["emoji"]
            assert profile["domains"]
            assert "system_prompt" in profile

    def test_get_profile_fallback_guardian(self) -> None:
        assert self.pm.get_profile("inexistente")["name"] == "Nicky Virthy"
        assert self.pm.get_profile("")["name"] == "Nicky Virthy"

    def test_guardian_e_o_default(self) -> None:
        assert DEFAULT_PROFILE == "guardian"

    def test_deteccao_por_dominio(self) -> None:
        assert self.pm.get_profile_by_domain("monitoramento de servidores") == "guardian"
        assert self.pm.get_profile_by_domain("história do brasil") == "regulus"
        assert self.pm.get_profile_by_domain("educação infantil") == "luma"
        assert self.pm.get_profile_by_domain("storytelling para anúncios") == "vox"
        assert self.pm.get_profile_by_domain("taxonomia de dados") == "athenae"
        assert self.pm.get_profile_by_domain("mitologia grega") == "nyx"

    def test_deteccao_dominio_vazio(self) -> None:
        assert self.pm.get_profile_by_domain("") == DEFAULT_PROFILE
        assert self.pm.get_profile_by_domain(None) == DEFAULT_PROFILE

    def test_deteccao_dominio_desconhecido(self) -> None:
        assert self.pm.get_profile_by_domain("zzz sem match") == DEFAULT_PROFILE

    def test_resolve_explicito(self) -> None:
        assert self.pm.resolve("luma") == "luma"
        assert self.pm.resolve("NYX") == "nyx"
        assert self.pm.resolve("inexistente") == DEFAULT_PROFILE

    def test_resolve_auto_com_contexto(self) -> None:
        assert self.pm.resolve("auto", "história medieval") == "regulus"
        assert self.pm.resolve("", "psicologia do aprendizado") == "luma"

    def test_resolve_auto_sem_contexto(self) -> None:
        assert self.pm.resolve("auto") == DEFAULT_PROFILE
        assert self.pm.resolve(None, None) == DEFAULT_PROFILE

    def test_get_display_name(self) -> None:
        assert "Nicky Virthy" in self.pm.get_display_name("guardian")
        assert "Regulus" in self.pm.get_display_name("regulus")

    def test_get_combined_prompt(self) -> None:
        combined = self.pm.get_combined_prompt(None, "história", base_identity="IDENTIDADE BASE")
        assert "IDENTIDADE BASE" in combined
        assert "Conselheiro" in combined
        combined_default = self.pm.get_combined_prompt(None)
        assert "Guardiã" in combined_default

    def test_add_custom_profile(self) -> None:
        self.pm.add_custom_profile("Echo", {"domains": ["música", "som"]})
        assert "echo" in self.pm.list_profiles()
        profile = self.pm.get_profile("echo")
        assert profile["name"] == "Echo"
        assert "música" in profile["domains"]
        # detecção agora enxerga o perfil novo
        assert self.pm.get_profile_by_domain("música clássica") == "echo"

    def test_add_custom_profile_nome_vazio(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            self.pm.add_custom_profile("   ", {})

    def test_snapshot_e_dump(self) -> None:
        snap = self.pm.snapshot()
        assert snap["count"] == 6
        assert snap["default"] == "guardian"
        dump = self.pm.dump()
        assert set(dump) == {"guardian", "regulus", "luma", "vox", "athenae", "nyx"}