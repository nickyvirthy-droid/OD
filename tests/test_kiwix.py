"""
OMEGA DRAKON • TESTS
Módulo: tests/test_kiwix.py
Descrição: Testes do Kiwix (integrations/kiwix.py) — 3ª das 3
           interligações de ferramenta aprovadas (Vaultwarden → Stirling →
           Kiwix, "fase 3 aprovada" pelo dono em 17/10). Cliente com
           transporte INJETÁVEL e fixtures fiéis às capturas VIVAS de
           17/10 (Atom de /catalog/v2/entries, HTML de /search com
           <div class="results">, HTML de /content/<zim>/<path>):
           parsers stdlib, erros honestos tipados, busca vazia como
           resposta (não erro), truncamento declarado, caminho invalidado
           (".."), fábrica lazy + as 3 actions no catálogo (categoria
           kiwix, só admin).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - integrations/kiwix.py (KiwixClient + transporte injetável)
  - contratos ao vivo do kiwix-serve 3.8.1 (127.0.0.1:8090, apurado 17/10)
  - tools/actions/actions.py (kiwix_status/busca/leitura)
"""

from __future__ import annotations

import pathlib
import socket
import urllib.error
from typing import Any

import pytest

from core.security import SecurityManager
from integrations import kiwix as kiwix_mod
from integrations.kiwix import (
    LIMITE_PADRAO_TEXTO,
    URL_PADRAO,
    KiwixClient,
    KiwixError,
    _parse_artigo,
    _parse_busca,
    _parse_catalogo,
    client_padrao,
    resetar_cliente,
)
from tools.actions import CATALOG, build_registry
from tools.actions.actions import (
    kiwix_busca,
    kiwix_leitura,
    kiwix_status,
)

# ---------------------------------------------------------------------------
# Fixtures fiéis às capturas VIVAS do od-kiwix (17/10)
# ---------------------------------------------------------------------------

# /catalog/v2/entries — feed Atom/OPDS (estrutura real, entry enxuto)
CATALOGO_ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:dc="http://purl.org/dc/terms/"
      xmlns:opds="https://specs.opds.io/opds-1.2">
  <id>dc57b2ca-c6fe-0010-0526-cb1f633ce5c6</id>
  <title>All Entries</title>
  <entry>
    <id>urn:uuid:299eb9dc-88e5-6494-1a4b-132d4e897f3d</id>
    <title>Wikipedia</title>
    <updated>2026-09-09T00:00:00Z</updated>
    <summary>The free encyclopedia</summary>
    <language>eng</language>
    <name>wikipedia_en_all_mini</name>
    <articleCount>18095848</articleCount>
    <mediaCount>33992</mediaCount>
  </entry>
</feed>
"""

# /search?pattern=omega — HTML real com 2 hits (título, trecho, palavras)
BUSCA_HTML = b"""<html><head><title>Kiwix Search</title></head><body>
    <div class="results">
      <ul>
          <li>
            <a href="/content/wikipedia_en_all_mini/Omega_function">
              Omega function
            </a>
              <cite><b>Omega</b> function In mathematics, the lower bound
              in Big O notation, f &isin; &Omega;(g).</cite>
              <div class="book-title">from Wikipedia</div>
              <div class="informations">207 words</div>
          </li>
          <li>
            <a href="/content/wikipedia_en_all_mini/Omega_Point_(disambiguation)">
              Omega Point (disambiguation)
            </a>
              <cite>Disambiguation page listing topics.</cite>
              <div class="book-title">from Wikipedia</div>
              <div class="informations">36 words</div>
          </li>
      </ul>
    </div>
</body></html>
"""

# /content/... — HTML real de artigo (título, h2, p, script/style a ignorar)
ARTIGO_HTML = b"""<!DOCTYPE html><html><head>
<meta charset="utf-8"/><title>Omega function</title></head><body>
<div id="content"><h1>Omega function</h1>
<p>In mathematics, the <b>omega</b> function refers to a function using
the Greek letter omega, written &omega; or &Omega;.</p>
<h2>See also</h2>
<p>The lower bound in Big O notation.</p>
<script>var x = "nao deve aparecer";</script>
<style>.p { color: red; }</style>
</div></body></html>
"""

# Busca sem resultados (página vazia — resposta honesta, não erro)
BUSCA_VAZIA_HTML = b"""<html><head><title>Kiwix Search</title></head><body>
    <div class="results"><ul></ul></div>
</body></html>
"""


# ---------------------------------------------------------------------------
# Dublês
# ---------------------------------------------------------------------------

class _TransporteFalso:
    """Respostas roteirizadas (ou exceção) + registro das chamadas.

    A última resposta gruda (reusada em chamadas seguintes), as demais
    são consumidas em ordem. Assinatura espelha o transporte real do
    kiwix: (url, *, timeout_s).
    """

    def __init__(self, *respostas: Any) -> None:
        self._respostas = list(respostas)
        self.chamadas: list[dict[str, Any]] = []

    def __call__(self, url: str, *, timeout_s=None):
        self.chamadas.append({"url": url, "timeout_s": timeout_s})
        if not self._respostas:
            raise AssertionError("resposta não roteirizada para a chamada")
        item = self._respostas.pop(0) if len(self._respostas) > 1 else self._respostas[0]
        if isinstance(item, BaseException):
            raise item
        return item


class _RespHttp:
    """Resposta urlopen falsa (context manager, status, headers, read)."""

    def __init__(self, status: int = 200, headers=None, body: bytes = b"") -> None:
        self.status = status
        self.headers = headers if headers is not None else {"Content-Type": "text/html"}
        self._body = body

    def read(self, *args: Any) -> bytes:
        return self._body

    def __enter__(self) -> "_RespHttp":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False


def _cliente(*respostas: Any) -> tuple[KiwixClient, _TransporteFalso]:
    transporte = _TransporteFalso(*respostas)
    return KiwixClient(transporte=transporte), transporte


@pytest.fixture(autouse=True)
def _fabrica_limpa():
    """Fábrica cacheada nunca vaza entre testes."""
    resetar_cliente()
    yield
    resetar_cliente()


# ===========================================================================
# Parsers stdlib — fiéis ao HTML/XML vivos
# ===========================================================================

class TestParsers:
    def test_parse_catalogo_extrai_o_acervo(self) -> None:
        acervos = _parse_catalogo(CATALOGO_ATOM)
        assert len(acervos) == 1
        a = acervos[0]
        assert a["id"] == "299eb9dc-88e5-6494-1a4b-132d4e897f3d"  # urn:uuid: removido
        assert a["nome"] == "wikipedia_en_all_mini"
        assert a["titulo"] == "Wikipedia"
        assert a["idioma"] == "eng"
        assert a["artigos"] == 18095848
        assert a["midias"] == 33992

    def test_parse_catalogo_xml_invalido_e_tipado(self) -> None:
        with pytest.raises(KiwixError) as exc:
            _parse_catalogo(b"<feed><entry></feed>")
        assert exc.value.codigo == "kiwix_resposta_invalida"

    def test_parse_catalogo_entry_sem_nome_e_ignorada(self) -> None:
        xml = (
            b'<feed xmlns="http://www.w3.org/2005/Atom">'
            b"<entry><title>Sem nome</title></entry></feed>"
        )
        assert _parse_catalogo(xml) == []

    def test_parse_busca_extrai_titulo_caminho_trecho_palavras(self) -> None:
        itens = _parse_busca(BUSCA_HTML)
        assert len(itens) == 2
        primeiro = itens[0]
        assert primeiro["titulo"] == "Omega function"
        assert primeiro["caminho"] == "wikipedia_en_all_mini/Omega_function"
        assert "Omega function In mathematics" in primeiro["trecho"]
        assert "∈" in primeiro["trecho"]  # entidades desescapeadas (∈ e Ω)
        assert primeiro["palavras"] == 207
        assert itens[1]["caminho"].endswith("Omega_Point_(disambiguation)")

    def test_parse_busca_vazia_devolve_lista_vazia(self) -> None:
        assert _parse_busca(BUSCA_VAZIA_HTML) == []

    def test_parse_artigo_extrai_titulo_e_paragrafos(self) -> None:
        titulo, texto = _parse_artigo(ARTIGO_HTML)
        assert titulo == "Omega function"
        assert "In mathematics, the omega function" in texto
        assert "See also" in texto  # h2 entra como bloco
        assert "lower bound in Big O notation" in texto
        assert "nao deve aparecer" not in texto  # script ignorado
        assert "color: red" not in texto  # style ignorado

    def test_parse_artigo_sem_blocos_devolve_texto_vazio(self) -> None:
        titulo, texto = _parse_artigo(b"<html><head><title>X</title></head></html>")
        assert titulo == "X"
        assert texto == ""


# ===========================================================================
# Cliente — status (catálogo)
# ===========================================================================

class TestClienteStatus:
    def test_status_devolve_acervo_e_total(self) -> None:
        cliente, t = _cliente((200, {}, CATALOGO_ATOM))
        r = cliente.status()
        assert r["ok"] if "ok" in r else True  # ok é aplicado pela action
        assert r["acervos"][0]["nome"] == "wikipedia_en_all_mini"
        assert r["total_artigos"] == 18095848
        assert r["acessivel"] is True
        assert t.chamadas[0]["url"].endswith("/catalog/v2/entries")

    def test_status_404_e_falhou_honesto(self) -> None:
        cliente, _ = _cliente((404, {}, b"not found"))
        with pytest.raises(KiwixError) as exc:
            cliente.status()
        assert exc.value.codigo == "kiwix_falhou"
        assert "404" in exc.value.mensagem

    def test_status_500_e_falhou(self) -> None:
        cliente, _ = _cliente((500, {}, b"boom"))
        with pytest.raises(KiwixError) as exc:
            cliente.status()
        assert exc.value.codigo == "kiwix_falhou"


# ===========================================================================
# Cliente — busca
# ===========================================================================

class TestClienteBusca:
    def test_busca_devolve_hits_limitados(self) -> None:
        cliente, t = _cliente((200, {}, BUSCA_HTML))
        r = cliente.buscar("omega", quantidade=1)
        assert r["pattern"] == "omega"
        assert len(r["resultados"]) == 1
        assert r["resultados"][0]["titulo"] == "Omega function"
        assert "pattern=omega" in t.chamadas[0]["url"]

    def test_busca_padrao_com_espaco_e_codificado(self) -> None:
        cliente, t = _cliente((200, {}, BUSCA_HTML))
        cliente.buscar("omega function")
        assert "pattern=omega+function" in t.chamadas[0]["url"]

    def test_busca_quantidade_tem_ceo_de_25(self) -> None:
        cliente, t = _cliente((200, {}, BUSCA_HTML))
        r = cliente.buscar("omega", quantidade=999)
        assert len(r["resultados"]) <= 25

    def test_busca_vazia_e_resposta_nao_erro(self) -> None:
        cliente, _ = _cliente((200, {}, BUSCA_VAZIA_HTML))
        r = cliente.buscar("inexistente no acervo")
        assert r["resultados"] == []

    def test_busca_padrao_vazio_e_parametro_invalido(self) -> None:
        cliente, _ = _cliente((200, {}, BUSCA_HTML))
        with pytest.raises(KiwixError) as exc:
            cliente.buscar("   ")
        assert exc.value.codigo == "kiwix_parametro_invalido"

    def test_busca_500_e_falhou(self) -> None:
        cliente, _ = _cliente((500, {}, b"boom"))
        with pytest.raises(KiwixError) as exc:
            cliente.buscar("omega")
        assert exc.value.codigo == "kiwix_falhou"


# ===========================================================================
# Cliente — leitura de artigo
# ===========================================================================

class TestClienteLeitura:
    def test_leitura_devolve_texto_limpo(self) -> None:
        cliente, t = _cliente((200, {}, ARTIGO_HTML))
        r = cliente.ler("wikipedia_en_all_mini/Omega_function")
        assert r["titulo"] == "Omega function"
        assert "In mathematics" in r["texto"]
        assert r["truncado"] is False
        assert r["bytes"] == len(ARTIGO_HTML)
        assert t.chamadas[0]["url"].endswith(
            "/content/wikipedia_en_all_mini/Omega_function"
        )

    def test_leitura_com_barra_na_frente_e_normalizada(self) -> None:
        cliente, t = _cliente((200, {}, ARTIGO_HTML))
        cliente.ler("/wikipedia_en_all_mini/Omega_function")
        assert "/content//wikipedia" not in t.chamadas[0]["url"]

    def test_leitura_trunca_com_declaracao_honesta(self) -> None:
        paragrafo = "palavra " * 100  # > 200 chars (piso do max_chars)
        html = f"<html><head><title>G</title></head><body><p>{paragrafo}</p></body></html>".encode()
        cliente, _ = _cliente((200, {}, html))
        r = cliente.ler("zim/Grande", max_chars=250)
        assert r["truncado"] is True
        assert r["texto"].endswith("…[cortado]")
        assert len(r["texto"]) < len(paragrafo) + 20

    def test_leitura_404_e_artigo_nao_encontrado(self) -> None:
        cliente, _ = _cliente((404, {}, b"<html>404</html>"))
        with pytest.raises(KiwixError) as exc:
            cliente.ler("wikipedia_en_all_mini/Inexistente")
        assert exc.value.codigo == "kiwix_artigo_nao_encontrado"
        assert "kiwix_busca" in exc.value.mensagem

    def test_leitura_caminho_com_ponto_ponto_e_reprovado(self) -> None:
        cliente, _ = _cliente((200, {}, ARTIGO_HTML))
        for caminho in ("../etc/passwd", "zim/../../../x", "", None):
            with pytest.raises(KiwixError) as exc:
                cliente.ler(caminho)  # type: ignore[arg-type]
            assert exc.value.codigo == "kiwix_parametro_invalido"

    def test_leitura_html_sem_texto_e_resposta_invalida(self) -> None:
        html = b"<html><head><title>Vazio</title></head><body><div/></body></html>"
        cliente, _ = _cliente((200, {}, html))
        with pytest.raises(KiwixError) as exc:
            cliente.ler("zim/Vazio")
        assert exc.value.codigo == "kiwix_resposta_invalida"


# ===========================================================================
# Transporte urllib — rede de verdade
# ===========================================================================

class TestTransporteUrllib:
    def test_urlopen_ok_vira_resposta(self, monkeypatch) -> None:
        monkeypatch.setattr(
            urllib.request, "urlopen",
            lambda req, timeout=None: _RespHttp(200, {}, CATALOGO_ATOM),
        )
        cliente = KiwixClient()
        r = cliente.status()
        assert r["acervos"][0]["nome"] == "wikipedia_en_all_mini"

    def test_httperror_e_resposta_nao_excecao(self, monkeypatch) -> None:
        def falso(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url, 404, "Not Found", {}, _RespHttp(404).read
            )

        monkeypatch.setattr(urllib.request, "urlopen", falso)
        cliente = KiwixClient()
        with pytest.raises(KiwixError) as exc:
            cliente.ler("zim/Qualquer")
        assert exc.value.codigo == "kiwix_artigo_nao_encontrado"

    def test_urlerror_vira_indisponivel(self, monkeypatch) -> None:
        def falso(req, timeout=None):
            raise urllib.error.URLError("caiu")

        monkeypatch.setattr(urllib.request, "urlopen", falso)
        cliente = KiwixClient()
        with pytest.raises(KiwixError) as exc:
            cliente.status()
        assert exc.value.codigo == "kiwix_indisponivel"

    def test_timeout_vira_kiwix_timeout(self, monkeypatch) -> None:
        def falso(req, timeout=None):
            raise socket.timeout("demorou")

        monkeypatch.setattr(urllib.request, "urlopen", falso)
        cliente = KiwixClient()
        with pytest.raises(KiwixError) as exc:
            cliente.status()
        assert exc.value.codigo == "kiwix_timeout"
        assert "não respondeu" in exc.value.mensagem


# ===========================================================================
# Fábrica lazy — env, cache, reset
# ===========================================================================

class TestFabrica:
    def test_padrao_e_local(self) -> None:
        c = client_padrao()
        assert c.base_url == URL_PADRAO == "http://127.0.0.1:8090"

    def test_url_do_env(self, monkeypatch) -> None:
        monkeypatch.setenv("OD_KIWIX_URL", "http://127.0.0.1:9999/")
        c = client_padrao()
        assert c.base_url == "http://127.0.0.1:9999"  # barra final removida

    def test_cache_um_por_processo(self) -> None:
        assert client_padrao() is client_padrao()

    def test_reset_esquece(self) -> None:
        primeiro = client_padrao()
        resetar_cliente()
        assert client_padrao() is not primeiro


# ===========================================================================
# Actions — erro honesto, degradação, fábrica
# ===========================================================================

def _com_fabrica(cliente: Any, monkeypatch) -> None:
    monkeypatch.setattr(kiwix_mod, "client_padrao", lambda: cliente)


class TestActionsKiwix:
    def test_status_ok(self, monkeypatch) -> None:
        cliente, _ = _cliente((200, {}, CATALOGO_ATOM))
        _com_fabrica(cliente, monkeypatch)
        r = kiwix_status()
        assert r["ok"] is True
        assert r["total_artigos"] == 18095848
        assert r["acervos"][0]["nome"] == "wikipedia_en_all_mini"

    def test_status_fora_do_ar_degrada_a_action(self, monkeypatch) -> None:
        cliente, _ = _cliente(urllib.error.URLError("caiu"))
        _com_fabrica(cliente, monkeypatch)
        r = kiwix_status()
        assert r["ok"] is False
        assert r["error"] == "kiwix_indisponivel"
        assert "inacessível" in r["message"]

    def test_busca_action_ok(self, monkeypatch) -> None:
        cliente, _ = _cliente((200, {}, BUSCA_HTML))
        _com_fabrica(cliente, monkeypatch)
        r = kiwix_busca(pattern="omega", quantidade=2)
        assert r["ok"] is True
        assert r["pattern"] == "omega"
        assert len(r["resultados"]) == 2
        assert r["resultados"][0]["caminho"].startswith("wikipedia_en_all_mini/")

    def test_busca_vazia_na_action_e_ok_com_lista_vazia(self, monkeypatch) -> None:
        cliente, _ = _cliente((200, {}, BUSCA_VAZIA_HTML))
        _com_fabrica(cliente, monkeypatch)
        r = kiwix_busca(pattern="inexistente")
        assert r["ok"] is True
        assert r["resultados"] == []

    def test_leitura_action_ok(self, monkeypatch) -> None:
        cliente, _ = _cliente((200, {}, ARTIGO_HTML))
        _com_fabrica(cliente, monkeypatch)
        r = kiwix_leitura(caminho="wikipedia_en_all_mini/Omega_function")
        assert r["ok"] is True
        assert r["titulo"] == "Omega function"
        assert "In mathematics" in r["texto"]

    def test_leitura_404_na_action_e_honesta(self, monkeypatch) -> None:
        cliente, _ = _cliente((404, {}, b"<html>404</html>"))
        _com_fabrica(cliente, monkeypatch)
        r = kiwix_leitura(caminho="zim/Inexistente")
        assert r["ok"] is False
        assert r["error"] == "kiwix_artigo_nao_encontrado"

    def test_leitura_timeout_na_action_e_honesta(self, monkeypatch) -> None:
        cliente, _ = _cliente(socket.timeout("demorou"))
        _com_fabrica(cliente, monkeypatch)
        r = kiwix_leitura(caminho="zim/Artigo")
        assert r["ok"] is False
        assert r["error"] == "kiwix_timeout"


# ===========================================================================
# Catálogo — 3 actions, categoria kiwix, permissão
# ===========================================================================

KIWIX_ACOES = {"kiwix_status", "kiwix_busca", "kiwix_leitura"}


class TestCatalogoKiwix:
    def test_tres_actions_na_categoria_kiwix(self) -> None:
        da_ferramenta = [s for s in CATALOG if s["category"] == "kiwix"]
        assert {s["name"] for s in da_ferramenta} == KIWIX_ACOES
        assert len(da_ferramenta) == 3

    def test_schemas_dos_params(self) -> None:
        por_nome = {s["name"]: s for s in CATALOG}
        assert por_nome["kiwix_status"]["params"] == {}
        assert por_nome["kiwix_busca"]["params"].get("required") == ["pattern"]
        assert por_nome["kiwix_busca"]["params"]["properties"]["quantidade"]["default"] == 5
        assert por_nome["kiwix_leitura"]["params"].get("required") == ["caminho"]
        assert por_nome["kiwix_leitura"]["params"]["properties"]["max_chars"]["default"] == 8000

    @pytest.mark.asyncio
    async def test_papel_user_negado_por_permissao(self) -> None:
        """Acervo offline é do admin: papel comum não alcança."""
        registry = build_registry(security=SecurityManager(mode="strict"))
        params = {
            "kiwix_status": {},
            "kiwix_busca": {"pattern": "omega"},
            "kiwix_leitura": {"caminho": "wikipedia_en_all_mini/Omega_function"},
        }
        for nome in sorted(KIWIX_ACOES):
            result = await registry.execute(nome, params=params[nome], role="user")
            assert result.status == "denied", nome
            assert result.denied_by == "permission", nome


__all__ = [
    "TestParsers",
    "TestClienteStatus",
    "TestClienteBusca",
    "TestClienteLeitura",
    "TestTransporteUrllib",
    "TestFabrica",
    "TestActionsKiwix",
    "TestCatalogoKiwix",
]
