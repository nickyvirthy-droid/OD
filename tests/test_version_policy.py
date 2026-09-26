"""
OMEGA DRAKON • TESTS
Módulo: tests/test_version_policy.py
Descrição: Guardas da política de versionamento (docs/VERSIONAMENTO.md,
           regra 12 de iniciar/RULES.md) — a versão X.Y.Z deve ser a MESMA
           em todas as fontes vivas do sistema e o versionCode do app deve
           ser um inteiro monotônico. Cobertura:
             1. Formato SemVer de OD_VERSION (X.Y.Z, sem zeros à esquerda).
             2. Coerência .env ↔ core/capabilities.py (fonte da verdade).
             3. Fallback congelado em disco = versão vigente.
             4. app/pubspec.yaml: versionName = versão do sistema e build
                (+N) é inteiro (versionCode Android monotônico).
             5. site/index.html anuncia a versão vigente (badge + card).
             6. docs/CHANGELOG.md tem seção da versão vigente.
           Qualquer bump parcial (uma fonte esquecida) quebra a suíte.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docs/VERSIONAMENTO.md (política, §3 fonte da verdade, §5 checklist)
  - iniciar/RULES.md (regra 12)
  - https://semver.org/lang/pt-BR/
"""

from __future__ import annotations

import re
from pathlib import Path

from core.capabilities import OD_VERSION

ROOT = Path(__file__).resolve().parent.parent

SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def _env_version() -> str:
    match = re.search(r"^OD_VERSION=(\S+)\s*$", _read(".env"), re.MULTILINE)
    assert match, ".env sem a linha OD_VERSION — política §3 violada"
    return match.group(1)


def _capabilities_fallback() -> str:
    source = _read("core/capabilities.py")
    match = re.search(
        r'OD_VERSION\s*=\s*\(.*?or\s+"(\d+\.\d+\.\d+)"', source, re.DOTALL
    )
    assert match, "fallback congelado de OD_VERSION não encontrado em core/capabilities.py"
    return match.group(1)


def _pubspec_version() -> tuple[str, int]:
    match = re.search(
        r"^version:\s*(\d+)\.(\d+)\.(\d+)\+(\d+)\s*$",
        _read("app/pubspec.yaml"),
        re.MULTILINE,
    )
    assert match, "app/pubspec.yaml sem 'version: X.Y.Z+N' no formato esperado"
    version_name = f"{match.group(1)}.{match.group(2)}.{match.group(3)}"
    return version_name, int(match.group(4))


class TestVersionPolicy:
    """Guardas da coerência de versão (docs/VERSIONAMENTO.md)."""

    def test_od_version_tem_formato_semver(self) -> None:
        """OD_VERSION é X.Y.Z com inteiros sem zeros à esquerda (SemVer §2)."""
        assert SEMVER_RE.match(OD_VERSION), (
            f"OD_VERSION='{OD_VERSION}' não é X.Y.Z SemVer (sem zeros à esquerda)"
        )

    def test_env_e_capabilities_na_mesma_versao(self) -> None:
        """A fonte da verdade (.env) bate com a versão resolvida em runtime."""
        assert _env_version() == OD_VERSION, (
            f".env tem {_env_version()} mas core.capabilities resolveu {OD_VERSION}"
        )

    def test_fallback_congelado_e_a_versao_vigente(self) -> None:
        """O fallback em disco acompanha a versão vigente (política §5.2)."""
        assert _capabilities_fallback() == OD_VERSION, (
            f"fallback congelado {_capabilities_fallback()} != OD_VERSION {OD_VERSION} "
            "— esqueceu o checklist §5.2 do VERSIONAMENTO.md"
        )

    def test_pubspec_versionname_e_build(self) -> None:
        """versionName do app = versão do sistema; build (+N) é inteiro ≥ 1."""
        version_name, build = _pubspec_version()
        assert version_name == OD_VERSION, (
            f"app está em {version_name}+{build} mas o sistema é {OD_VERSION} — "
            "o +N é versionCode, NUNCA substitui a versão (política §2)"
        )
        assert build >= 1, "versionCode deve ser inteiro positivo monotônico"

    def test_site_anuncia_a_versao_vigente(self) -> None:
        """Landing anuncia a versão vigente no badge do hero e no card do APK."""
        html = _read("site/index.html")
        occurrences = html.count(f"v{OD_VERSION}")
        assert occurrences >= 2, (
            f"site/index.html menciona v{OD_VERSION} {occurrences}x (esperado ≥ 2: "
            "badge do hero + card do APK) — site ficou para trás no bump"
        )
        assert "v1.2.8" not in html, "resíduo da versão antiga v1.2.8 no site"

    def test_changelog_tem_secao_da_versao_vigente(self) -> None:
        """CHANGELOG tem a seção ## [X.Y.Z] da versão vigente no topo da série."""
        changelog = _read("docs/CHANGELOG.md")
        assert re.search(
            rf"^## \[{re.escape(OD_VERSION)}\]", changelog, re.MULTILINE
        ), f"docs/CHANGELOG.md sem seção '## [{OD_VERSION}]' — checklist §5.5"
