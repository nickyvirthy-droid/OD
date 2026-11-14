"""Auditoria do gate de escopo sobre TODO o catálogo de actions.

Origem (12/11/2026): `disk_usage` era negada pela camada de escopo
("Path '/' is outside the allowed project scope") e a pergunta de disco caía
no LLM — uma negação silenciosa, que ninguém via porque a resposta parecia
boa. Este arquivo transforma a auditoria manual em rede de regressão.
"""

from __future__ import annotations

import pytest

from core.security import SecurityManager
from core.security.scope import SCOPE_EXEMPT_ACTIONS, _PATH_PARAM_KEYS
from tools.actions.actions import CATALOG
from tools.loader import validate_params


def _nomes_de_parametros(spec: dict) -> set[str]:
    """Nomes de parâmetros, nos dois formatos de schema do catálogo.

    Parte do catálogo usa `{"properties": {...}}` e parte usa o formato plano
    (`{"path": {...}}`) — a auditoria tem que enxergar os dois, senão o próprio
    `disk_usage` (schema plano) passaria batido.
    """
    params = spec.get("params") or {}
    propriedades = set(params.get("properties") or {})
    planos = {
        chave
        for chave in params
        if chave not in ("required", "properties", "type", "additionalProperties")
    }
    return propriedades | planos


class TestAuditoriaDoGateDeEscopo:
    def test_nenhuma_action_e_negada_com_os_defaults(self) -> None:
        """Nenhuma action pode nascer negada pelo gate com seus defaults.

        Caso real (12/11): `disk_usage` tinha `path="/"` como default, o
        schema preenchia antes do gate e a leitura era recusada — a pergunta
        de disco nunca chegava a responder com dado real.
        """
        security = SecurityManager(mode="strict")
        negadas: list[str] = []
        for spec in CATALOG:
            ok, _erros, filled = validate_params(spec.get("params") or {}, {})
            if not ok:
                # Action que exige parâmetro obrigatório: o default não
                # completa, então não há o que auditar aqui.
                continue
            decisao = security.check(
                action=spec["name"],
                params=filled,
                role="admin",
                source="auditoria",
            )
            if not decisao.allowed:
                negadas.append(f"{spec['name']} ({decisao.denied_by})")
        assert negadas == [], (
            "actions negadas pelo gate com os próprios defaults: "
            + ", ".join(negadas)
        )

    def test_parametros_de_caminho_estao_mapeados(self) -> None:
        """Canário: quem adicionar `path`/`source`/`dest` novo revisa esta lista.

        Se uma action nova aparece aqui, é preciso decidir se o parâmetro é
        caminho LOCAL (o escopo vale) ou nome/argumento de serviço (não vale) —
        foi exatamente essa decisão que faltou no `disk_usage`.
        """
        com_caminho = {
            spec["name"]
            for spec in CATALOG
            if _nomes_de_parametros(spec) & set(_PATH_PARAM_KEYS)
        }
        esperado = {
            "disk_usage",
            "nomad_wikipedia_zim_download",
            "filesystem_search",
            "filesystem_read",
            "filesystem_write",
            "filesystem_delete",
            "filesystem_exists",
            "filesystem_info",
            "filesystem_list",
            "filesystem_mkdir",
            "filesystem_move",
            "filesystem_copy",
            "filesystem_touch",
            "filesystem_tree",
            "filesystem_hash",
            "filesystem_archive",
            "filesystem_extract",
            "stt_transcrever",
            "filebrowser_envia",
            "filebrowser_lista",
            "kiwix_leitura",
        }
        assert com_caminho == esperado, (
            "novas actions com parâmetro de caminho: "
            + str(sorted(com_caminho - esperado))
            + " | removidas: "
            + str(sorted(esperado - com_caminho))
        )

    def test_excecao_de_escopo_so_cobre_metrica_do_sistema(self) -> None:
        """A isenção existe para métrica medida por caminho, nada mais."""
        categorias = {spec["name"]: spec.get("category") for spec in CATALOG}
        for nome in SCOPE_EXEMPT_ACTIONS:
            assert nome in categorias, f"isenção aponta para action inexistente: {nome}"
            assert categorias[nome] == "system", (
                f"{nome} está isenta do escopo mas não é métrica de sistema "
                f"(categoria={categorias[nome]!r})"
            )

    @pytest.mark.parametrize(
        "action",
        ["filesystem_read", "filesystem_delete", "filesystem_write", "filesystem_list"],
    )
    def test_negacao_continua_valendo_para_arquivo_fora_da_raiz(
        self, action: str
    ) -> None:
        """A auditoria não pode afrouxar o escopo: arquivo fora da raiz segue negado."""
        security = SecurityManager(mode="strict")
        decisao = security.check(
            action=action,
            params={"path": "/etc/passwd", "content": "x"},
            role="admin",
            source="auditoria",
        )
        assert decisao.allowed is False

    def test_disco_mede_qualquer_montagem(self) -> None:
        """Métrica de disco é `stat` de uma montagem — não lê conteúdo de arquivo."""
        security = SecurityManager(mode="strict")
        decisao = security.check(
            action="disk_usage", params={"path": "/etc/passwd"}, role="admin"
        )
        assert decisao.allowed is True
