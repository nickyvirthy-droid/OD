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
                (+N) é inteiro (versionCode Android monotônico).           5. site/index.html anuncia a versão vigente (badge + card).
           6. docs/CHANGELOG.md tem seção da versão vigente.
           7. _APP_VERSION_CODE (integrations/api/server.py) == build do
              pubspec — o /app/version anuncia o versionCode do APK
              publicado; errado aqui mata a auto-atualização em silêncio
              (bug provado no ar em 2026-09-28: anunciava 2017 com o
              binário 2018 em site/).
           8. docs/CHANGELOG.md: seções ## [X.Y.Z] em ordem estrita
              descendente (mais recente no topo).
           9. Nenhum código (.py/.dart) rotula uma entrega com versão
              MAIOR que a vigente (achado de 2026-10-01: a voz saiu
              anunciada como 1.17.3, mas 14 comentários diziam uma
              versão futura — 1.18.0).
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
from typing import Optional

import pytest

from core.capabilities import OD_VERSION

ROOT = Path(__file__).resolve().parent.parent

SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def _env_version() -> Optional[str]:
    """OD_VERSION do `.env` da raiz, ou None em checkout limpo (sem .env).

    O `.env` é gitignored — no CI ele não existe e a versão vigente passa a
    ser o fallback congelado de core/capabilities.py (garantido pelo teste
    `test_fallback_congelado_e_a_versao_vigente`). Sem esta guarda o CI
    quebrava com FileNotFoundError em checkout limpo (achado de 2026-09-30).
    """
    env_path = ROOT / ".env"
    if not env_path.exists():
        return None
    match = re.search(
        r"^OD_VERSION=(\S+)\s*$", env_path.read_text(encoding="utf-8"), re.MULTILINE
    )
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


def _app_version_code() -> int:
    match = re.search(
        r"^_APP_VERSION_CODE\s*=\s*(\d+)",
        _read("integrations/api/server.py"),
        re.MULTILINE,
    )
    assert match, (
        "integrations/api/server.py sem '_APP_VERSION_CODE = <int>' — "
        "o GET /app/version perdeu a fonte do versionCode anunciado"
    )
    return int(match.group(1))


class TestVersionPolicy:
    """Guardas da coerência de versão (docs/VERSIONAMENTO.md)."""

    def test_od_version_tem_formato_semver(self) -> None:
        """OD_VERSION é X.Y.Z com inteiros sem zeros à esquerda (SemVer §2)."""
        assert SEMVER_RE.match(OD_VERSION), (
            f"OD_VERSION='{OD_VERSION}' não é X.Y.Z SemVer (sem zeros à esquerda)"
        )

    def test_env_e_capabilities_na_mesma_versao(self) -> None:
        """A fonte da verdade (.env) bate com a versão resolvida em runtime.

        Em checkout limpo (CI) o `.env` não existe: não há estado local a
        validar, então o teste é pulado — o fallback congelado continua
        coberto por `test_fallback_congelado_e_a_versao_vigente`.
        """
        env_version = _env_version()
        if env_version is None:
            pytest.skip(".env ausente (checkout limpo/CI) — fallback é a verdade")
        assert env_version == OD_VERSION, (
            f".env tem {env_version} mas core.capabilities resolveu {OD_VERSION}"
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

    def test_app_version_code_bate_com_o_pubspec(self) -> None:
        """O versionCode anunciado em /app/version é o do APK publicado.

        Bug do ar (2026-09-28): o lote v1.7.1 reversionou o pubspec para
        +2018 mas _APP_VERSION_CODE ficou em 2017 — o servidor anunciava
        o versionCode que o celular JÁ TINHA com o sha256 do binário novo;
        a auto-atualização nunca dispararia. Pego só pela prova viva
        pós-deploy; esta guarda fixa o contrato na suíte.
        """
        _, build = _pubspec_version()
        assert _app_version_code() == build, (
            f"_APP_VERSION_CODE={_app_version_code()} mas o pubspec declara "
            f"+{build} — /app/version anunciaria o versionCode errado e a "
            "auto-atualização morreria (checklist §5.4 do VERSIONAMENTO.md)"
        )

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

    def test_changelog_secoes_em_ordem_cronologica(self) -> None:
        """As seções ## [X.Y.Z] do CHANGELOG estão em ordem DESCENDENTE
        (mais recente no topo).

        A [1.7.0] ficou desordenada — gravada ACIMA da [1.8.0] — porque a
        regra 'mais recente no topo' foi aplicada como 'última seção
        gravada no topo' nas sessões de 28/09. Ordem errada engana quem
        lê o histórico e a nota de mapeamento da [1.3.0] perde o sentido.
        Esta guarda fixa a regra do próprio arquivo como contrato.
        """
        changelog = _read("docs/CHANGELOG.md")
        matches = re.findall(
            r"^## \[(\d+)\.(\d+)\.(\d+)\]", changelog, re.MULTILINE
        )
        assert len(matches) >= 10, (
            "poucas seções ## [X.Y.Z] no CHANGELOG — a regex da guarda "
            "deixou de casar com o formato do arquivo?"
        )
        versions = [tuple(int(p) for p in m) for m in matches]
        estrita = all(a > b for a, b in zip(versions, versions[1:]))
        assert estrita, (
            "seções ## [X.Y.Z] fora da ordem cronológica ESTRITA (esperado: "
            "mais recente no topo, sem cabeçalho repetido): "
            + " → ".join(f"{a}.{b}.{c}" for a, b, c in versions)
        )


class TestReferenciasDeVersao:
    """Nenhum código rotula uma entrega com versão FUTURA (cobertura 9)."""

    DIRS_CODIGO = (
        "agents",
        "configs",
        "core",
        "integrations",
        "memory",
        "observability",
        "plugins",
        "runtime",
        "storage",
        "tests",
        "tools",
        "app/lib",
        "app/test",
    )
    ARQUIVOS_RAIZ = ("orquestrador.py",)
    # Prefixo 'v' obrigatório: números avulsos são dependências
    # (ex.: desugar_jdk_libs 2.1.4) e não rótulos de release.
    RELEASE_RE = re.compile(r"\bv(\d+)\.(\d+)\.(\d+)\b")

    def test_nenhuma_referencia_a_versao_futura_no_codigo(self) -> None:
        """Nenhum .py/.dart cita 'vFUTURA' maior que OD_VERSION vigente.

        Achado de 2026-10-01: a voz (STT/TTS na API) foi entregue e
        anunciada como 1.17.3, mas 14 comentários no código rotulavam a
        entrega como 1.18.0 — uma versão que não existia. Quando a
        PRÓXIMA feature subir mesmo para 1.18.0, o rótulo velho passa a
        mentir sobre o histórico: o registro da entrega tem de ser a
        release que saiu (regra 12 de iniciar/RULES.md + registro
        honesto).
        """
        atual = tuple(int(p) for p in OD_VERSION.split("."))
        candidatos: list[Path] = []
        for rel in self.DIRS_CODIGO:
            base = ROOT / rel
            candidatos += list(base.rglob("*.py")) + list(base.rglob("*.dart"))
        candidatos += [ROOT / rel for rel in self.ARQUIVOS_RAIZ]

        futuras: list[str] = []
        for path in candidatos:
            texto = path.read_text(encoding="utf-8")
            for match in self.RELEASE_RE.finditer(texto):
                versao = tuple(int(match.group(i)) for i in (1, 2, 3))
                if versao > atual:
                    futuro = match.group(0)
                    futuras.append(f"{path.relative_to(ROOT)}: {futuro}")

        assert not futuras, (
            f"código rotulado com versão MAIOR que a vigente ({OD_VERSION}) "
            "— comentário mentindo sobre a release que saiu: "
            + " · ".join(sorted(futuras))
        )
