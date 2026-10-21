"""
OMEGA DRAKON • TESTES
Módulo: tests/test_flatnotes.py
Descrição: Testes do FlatNotes (integrations/flatnotes.py) — 5ª
           ferramenta interligada (pedido do dono 18/10: "ligar" — 1ª
           da análise de FlatNotes/File Browser/Calibre). Dublê de
           transporte roteirizado com fixtures FIÉIS às capturas VIVAS
           do od-flatnotes (apuradas antes de codificar e
           REVALIDADAS na 5.5.5): POST 200 com Note completo, 409 no
           título repetido, PATCH do sobrescrever, busca com score +
           destaques HTML (`<b class="match term0">`), config
           authType=none, busca `term=*` listando tudo, 404 da nota
           ausente. Cobre: contrato vivo, 409 = flatnotes_ja_existe
           honesto (sobrescrever é flag explícita e vem DECLARADO),
           destaques limpos p/ chat, busca vazia honesta, título com
           "/" recusado, erros tipados de rede/JSON, fábrica lazy com
           OD_FLATNOTES_URL + as 3 actions no catálogo (categoria
           flatnotes, só admin) — e a prova de que NÃO existe action
           de apagar (DELETE fora do catálogo, régua do dono).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - integrations/flatnotes.py (FlatNotesClient + transporte injetável)
  - contratos ao vivo do od-flatnotes (127.0.0.1:8200, apurado 18/10,
    5.5.4 → 5.5.5 revalidado: rotas idênticas)
  - tools/actions/actions.py (flatnotes_status/anota/busca)
"""

from __future__ import annotations

import io
import json
import socket
import urllib.error
from typing import Any

import pytest

from core.security import SecurityManager
from integrations import flatnotes as flatnotes_mod
from integrations.flatnotes import (
    LIMITE_BUSCA_MAXIMO,
    URL_PADRAO,
    FlatNotesClient,
    FlatNotesError,
    _limpar_destaque,
    client_padrao,
    resetar_cliente,
)
from tools.actions import CATALOG, build_registry
from tools.actions.actions import (
    flatnotes_anota,
    flatnotes_busca,
    flatnotes_status,
)

# ---------------------------------------------------------------------------
# Fixtures fiéis às capturas VIVAS do od-flatnotes (18/10, 5.5.4 e 5.5.5)
# ---------------------------------------------------------------------------

# GET /health → string JSON "OK"
SAUDE_OK = b'"OK"'

# GET /api/config → authType none + quick access padrão
CONFIG_JSON = (
    b'{"authType":"none","quickAccessHide":false,'
    b'"quickAccessTitle":"RECENTLY MODIFIED","quickAccessTerm":"*",'
    b'"quickAccessSort":"lastModified","quickAccessLimit":4}'
)

# POST /api/notes → Note completo (unix float em lastModified)
NOTA_CRIADA = (
    b'{"title":"OD contrato v555","content":"revalidando na 5.5.5",'
    b'"lastModified":1792293700.224875}'
)

# POST repetido → 409 com detail do FastAPI
REPETIDA_409 = (
    b'{"detail":"Cannot create note. A note with the same title '
    b'already exists."}'
)

# GET /api/search?term=... → SearchResult com destaques HTML reais
BUSCA_JSON = (
    b'[{"title":"OD teste de integracao","lastModified":1792292931.207031,'
    b'"score":0.3068528194400547,"titleHighlights":null,'
    b'"contentHighlights":"prova de <b class=\\"match term0\\">contrato'
    b'</b> da integracao","tagMatches":null}]'
)

BUSCA_VAZIA = b"[]"

# GET /api/notes/{title} ausente → 404
NAO_ACHADA_404 = b'{"detail":"The specified note cannot be found."}'


# ---------------------------------------------------------------------------
# Dublês
# ---------------------------------------------------------------------------

class _TransporteFalso:
    """Respostas roteirizadas (ou exceção) + registro das chamadas.

    A última resposta gruda (reusada em chamadas seguintes), as demais
    são consumidas em ordem — mesma semântica dos dublês da Stirling/
    Kiwix.
    """

    def __init__(self, *respostas: Any) -> None:
        self._respostas = list(respostas)
        self.chamadas: list[dict[str, Any]] = []

    def __call__(
        self,
        url: str,
        *,
        timeout_s: float | None = None,
        metodo: str = "GET",
        corpo: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        self.chamadas.append(
            {"url": url, "timeout_s": timeout_s, "metodo": metodo, "corpo": corpo}
        )
        if not self._respostas:
            raise AssertionError("resposta não roteirizada para a chamada")
        item = self._respostas.pop(0) if len(self._respostas) > 1 else self._respostas[0]
        if isinstance(item, BaseException):
            raise item
        return item

    @property
    def ultima(self) -> dict[str, Any]:
        return self.chamadas[-1]

    @property
    def corpo_json(self) -> Any:
        """JSON enviado na última chamada (None se não houve corpo)."""
        corpo = self.ultima["corpo"]
        return None if corpo is None else json.loads(json.dumps(corpo))


def _cliente(*respostas: Any) -> tuple[FlatNotesClient, _TransporteFalso]:
    transporte = _TransporteFalso(*respostas)
    return FlatNotesClient(URL_PADRAO, transporte=transporte), transporte


def _com_fabrica(cliente: Any, monkeypatch) -> None:
    monkeypatch.setattr(flatnotes_mod, "client_padrao", lambda: cliente)


@pytest.fixture(autouse=True)
def _fabrica_limpa():
    """Fábrica cacheada nunca vaza entre testes."""
    resetar_cliente()
    yield
    resetar_cliente()


# ===========================================================================
# Cliente — status (vida do caderno)
# ===========================================================================

class TestClienteStatus:
    def test_status_ok_com_contagem_e_ultima(self) -> None:
        cliente, t = _cliente(
            (200, {}, SAUDE_OK),
            (200, {}, CONFIG_JSON),
            (200, {}, BUSCA_JSON),
        )
        r = cliente.status()
        assert r["acessivel"] is True
        assert r["auth_type"] == "none"
        assert r["notas"] == 1
        assert r["ultima_modificada"]["titulo"] == "OD teste de integracao"
        assert r["ultima_modificada"]["modificado_em"] == 1792292931.207031
        assert [c["url"] for c in t.chamadas] == [
            f"{URL_PADRAO}/health",
            f"{URL_PADRAO}/api/config",
            f"{URL_PADRAO}/api/search?term=*",
        ]

    def test_status_caderno_vazio_sem_ultima(self) -> None:
        cliente, _ = _cliente(
            (200, {}, SAUDE_OK),
            (200, {}, CONFIG_JSON),
            (200, {}, BUSCA_VAZIA),
        )
        r = cliente.status()
        assert r["notas"] == 0
        assert r["ultima_modificada"] is None

    def test_status_health_fora_200_eh_falhou(self) -> None:
        cliente, _ = _cliente((500, {}, b"boom"))
        with pytest.raises(FlatNotesError) as exc:
            cliente.status()
        assert exc.value.codigo == "flatnotes_falhou"
        assert "HTTP 500" in exc.value.mensagem

    def test_status_config_resposta_invalida(self) -> None:
        cliente, _ = _cliente(
            (200, {}, SAUDE_OK),
            (200, {}, b"nao-e-json"),
        )
        with pytest.raises(FlatNotesError) as exc:
            cliente.status()
        assert exc.value.codigo == "flatnotes_resposta_invalida"

    def test_status_search_nao_lista_eh_resposta_invalida(self) -> None:
        cliente, _ = _cliente(
            (200, {}, SAUDE_OK),
            (200, {}, CONFIG_JSON),
            (200, {}, b'{"chave": "valor"}'),
        )
        with pytest.raises(FlatNotesError) as exc:
            cliente.status()
        assert exc.value.codigo == "flatnotes_resposta_invalida"


# ===========================================================================
# Cliente — anota (criar; 409 honesto; sobrescrever explícito)
# ===========================================================================

class TestClienteAnota:
    def test_cria_nota_e_envia_title_content(self) -> None:
        cliente, t = _cliente((200, {}, NOTA_CRIADA))
        r = cliente.anota("OD contrato v555", conteudo="revalidando na 5.5.5")
        assert r["titulo"] == "OD contrato v555"
        assert r["conteudo"] == "revalidando na 5.5.5"
        assert r["modificado_em"] == 1792293700.224875
        assert r["sobrescrito"] is False
        assert t.ultima["metodo"] == "POST"
        assert t.ultima["url"].endswith("/api/notes")
        assert t.corpo_json == {
            "title": "OD contrato v555",
            "content": "revalidando na 5.5.5",
        }

    def test_titulo_vazio_reprovado_sem_chamada(self) -> None:
        cliente, t = _cliente((200, {}, NOTA_CRIADA))
        with pytest.raises(FlatNotesError) as exc:
            cliente.anota("   ")
        assert exc.value.codigo == "flatnotes_parametro_invalido"
        assert t.chamadas == []

    def test_titulo_com_barra_reprovado(self) -> None:
        cliente, _ = _cliente((200, {}, NOTA_CRIADA))
        with pytest.raises(FlatNotesError) as exc:
            cliente.anota("pasta/nota", conteudo="x")
        assert exc.value.codigo == "flatnotes_parametro_invalido"
        assert "/" in exc.value.mensagem

    def test_409_sem_flag_eh_ja_existe_e_para_na_1a_chamada(self) -> None:
        cliente, t = _cliente((409, {}, REPETIDA_409))
        with pytest.raises(FlatNotesError) as exc:
            cliente.anota("OD contrato v555", conteudo="de novo")
        assert exc.value.codigo == "flatnotes_ja_existe"
        assert "sobrescrever" in exc.value.mensagem
        assert len(t.chamadas) == 1  # não tenta PATCH por conta própria

    def test_409_com_sobrescrever_vai_no_patch_e_declara(self) -> None:
        cliente, t = _cliente(
            (409, {}, REPETIDA_409),
            (200, {}, NOTA_CRIADA),
        )
        r = cliente.anota("OD contrato v555", conteudo="novo", sobrescrever=True)
        assert r["sobrescrito"] is True
        assert len(t.chamadas) == 2
        patch = t.chamadas[-1]
        assert patch["metodo"] == "PATCH"
        assert patch["url"].endswith("/api/notes/OD%20contrato%20v555")
        assert patch["corpo"] == {"newContent": "novo"}

    def test_409_sobrescrever_mas_nota_sumiu_eh_nao_encontrada(self) -> None:
        cliente, _ = _cliente(
            (409, {}, REPETIDA_409),
            (404, {}, NAO_ACHADA_404),
        )
        with pytest.raises(FlatNotesError) as exc:
            cliente.anota("Meia-a-meia", conteudo="x", sobrescrever=True)
        assert exc.value.codigo == "flatnotes_nao_encontrada"

    def test_resposta_200_sem_title_eh_resposta_invalida(self) -> None:
        cliente, _ = _cliente((200, {}, b'{"content":"sem titulo"}'))
        with pytest.raises(FlatNotesError) as exc:
            cliente.anota("qualquer")
        assert exc.value.codigo == "flatnotes_resposta_invalida"

    def test_erro_500_com_detail_honesto(self) -> None:
        cliente, _ = _cliente(
            (500, {}, b'{"detail":"algo quebrou l\xc3\xa1 dentro"}')
        )
        with pytest.raises(FlatNotesError) as exc:
            cliente.anota("qualquer")
        assert exc.value.codigo == "flatnotes_falhou"
        assert "HTTP 500" in exc.value.mensagem
        assert "algo quebrou lá dentro" in exc.value.mensagem


# ===========================================================================
# Cliente — busca (destaques limpos; vazia honesta; limites)
# ===========================================================================

class TestClienteBusca:
    def test_busca_limpa_html_dos_destaques(self) -> None:
        cliente, t = _cliente((200, {}, BUSCA_JSON))
        r = cliente.buscar("contrato")
        assert r["termo"] == "contrato"
        assert r["total"] == 1
        hit = r["resultados"][0]
        assert hit["titulo"] == "OD teste de integracao"
        assert hit["pontuacao"] == pytest.approx(0.3068528194400547)
        # HTML do flatnotes some: texto limpo, sem <b> nem class
        assert hit["trecho"] == "prova de contrato da integracao"
        assert "<" not in hit["trecho"]
        assert hit["trecho_titulo"] == ""
        assert "term=contrato" in t.ultima["url"]
        assert "limit=10" in t.ultima["url"]

    def test_busca_vazia_eh_resposta_honesta(self) -> None:
        cliente, _ = _cliente((200, {}, BUSCA_VAZIA))
        r = cliente.buscar("filamento")
        assert r == {"termo": "filamento", "total": 0, "resultados": []}

    def test_score_nulo_vira_pontuacao_nula(self) -> None:
        corpo = (
            b'[{"title":"x","lastModified":1.0,"score":null,'
            b'"titleHighlights":null,"contentHighlights":null,'
            b'"tagMatches":null}]'
        )
        cliente, _ = _cliente((200, {}, corpo))
        r = cliente.buscar("x")
        assert r["resultados"][0]["pontuacao"] is None
        assert r["resultados"][0]["trecho"] == ""

    def test_termo_vazio_reprovado(self) -> None:
        cliente, _ = _cliente((200, {}, BUSCA_VAZIA))
        with pytest.raises(FlatNotesError) as exc:
            cliente.buscar("  ")
        assert exc.value.codigo == "flatnotes_parametro_invalido"

    def test_limites_recalculados_para_a_faixa(self) -> None:
        cliente, t = _cliente((200, {}, BUSCA_VAZIA))
        cliente.buscar("a", limite=999)
        assert f"limit={LIMITE_BUSCA_MAXIMO}" in t.chamadas[-1]["url"]
        cliente.buscar("a", limite=0)
        assert "limit=1" in t.chamadas[-1]["url"]

    def test_corpo_nao_json_eh_resposta_invalida(self) -> None:
        cliente, _ = _cliente((200, {}, b"lixo"))
        with pytest.raises(FlatNotesError) as exc:
            cliente.buscar("x")
        assert exc.value.codigo == "flatnotes_resposta_invalida"

    def test_corpo_nao_lista_eh_resposta_invalida(self) -> None:
        cliente, _ = _cliente((200, {}, b'{"nota": "sola"}'))
        with pytest.raises(FlatNotesError) as exc:
            cliente.buscar("x")
        assert exc.value.codigo == "flatnotes_resposta_invalida"


# ===========================================================================
# Erros de rede + destaques + fábrica lazy
# ===========================================================================

class TestErrosRede:
    def test_urlerror_vira_indisponivel(self) -> None:
        cliente, _ = _cliente(urllib.error.URLError("caiu"))
        with pytest.raises(FlatNotesError) as exc:
            cliente.status()
        assert exc.value.codigo == "flatnotes_indisponivel"
        assert "inacessível" in exc.value.mensagem

    def test_timeout_vira_flatnotes_timeout(self) -> None:
        cliente, _ = _cliente(socket.timeout("demorou"))
        with pytest.raises(FlatNotesError) as exc:
            cliente.buscar("x")
        assert exc.value.codigo == "flatnotes_timeout"


class TestLimpaDestaque:
    def test_none_e_vazio_vao_para_string_vazia(self) -> None:
        assert _limpar_destaque(None) == ""
        assert _limpar_destaque("") == ""

    def test_tags_some_e_entidades_desescapam(self) -> None:
        bruto = 'antes <b class="match term0">termo</b> depois &amp; fim'
        assert _limpar_destaque(bruto) == "antes termo depois & fim"


class TestFabrica:
    def test_url_padrao_e_cache(self) -> None:
        a, b = client_padrao(), client_padrao()
        assert a is b
        assert a.base_url == URL_PADRAO

    def test_url_do_env(self, monkeypatch) -> None:
        monkeypatch.setenv("OD_FLATNOTES_URL", "http://127.0.0.1:9999")
        assert client_padrao().base_url == "http://127.0.0.1:9999"

    def test_reset_esquece_a_instancia(self) -> None:
        antes = client_padrao()
        resetar_cliente()
        assert client_padrao() is not antes


# ===========================================================================
# Transporte real (urllib) — corpo JSON e HTTPError como resposta
# ===========================================================================

class _RespHttp:
    def __init__(self, status: int = 200, body: bytes = b"") -> None:
        self.status = status
        self.headers = {"Content-Type": "application/json"}
        self._body = body

    def read(self, amt: int = -1) -> bytes:
        return self._body

    def __enter__(self) -> "_RespHttp":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False


class TestTransporteUrllib:
    def test_get_sem_corpo_e_post_com_json(self, monkeypatch) -> None:
        capturas: list[Any] = []

        def _abre(req, timeout=None):
            capturas.append(req)
            return _RespHttp(200, b"{}")

        monkeypatch.setattr(flatnotes_mod.urllib.request, "urlopen", _abre)

        from integrations.flatnotes import _transporte

        _transporte("http://x/health", timeout_s=5.0, metodo="GET")
        assert capturas[-1].data is None
        assert capturas[-1].method == "GET"

        _transporte(
            "http://x/api/notes",
            timeout_s=5.0,
            metodo="POST",
            corpo={"title": "t", "content": "c"},
        )
        assert capturas[-1].method == "POST"
        assert json.loads(_corpo_str(capturas)) == {"title": "t", "content": "c"}
        assert capturas[-1].get_header("Content-type") == "application/json"

    def test_http_error_devolve_status_em_vez_de_explodir(self, monkeypatch) -> None:
        def _abre(req, timeout=None):
            raise urllib.error.HTTPError(
                "http://x", 409, "Conflict", {}, io.BytesIO(REPETIDA_409)
            )

        monkeypatch.setattr(flatnotes_mod.urllib.request, "urlopen", _abre)

        from integrations.flatnotes import _transporte

        status, _h, corpo = _transporte("http://x/api/notes", timeout_s=5.0, metodo="POST", corpo={})
        assert status == 409
        assert b"already exists" in corpo


def _corpo_str(capturas: list[Any]) -> str:
    """Corpo enviado na última chamada (str p/ json.loads)."""
    return capturas[-1].data.decode("utf-8")


# ===========================================================================
# Actions — contrato fino sobre o cliente (LAZY: fora do ar degrada)
# ===========================================================================

class TestActionsFlatNotes:
    def test_status_ok(self, monkeypatch) -> None:
        cliente, _ = _cliente(
            (200, {}, SAUDE_OK),
            (200, {}, CONFIG_JSON),
            (200, {}, BUSCA_JSON),
        )
        _com_fabrica(cliente, monkeypatch)
        r = flatnotes_status()
        assert r["ok"] is True
        assert r["notas"] == 1
        assert r["auth_type"] == "none"

    def test_status_fora_do_ar_degrada_a_action(self, monkeypatch) -> None:
        cliente, _ = _cliente(urllib.error.URLError("caiu"))
        _com_fabrica(cliente, monkeypatch)
        r = flatnotes_status()
        assert r["ok"] is False
        assert r["error"] == "flatnotes_indisponivel"
        assert "inacessível" in r["message"]

    def test_anota_ok(self, monkeypatch) -> None:
        cliente, _ = _cliente((200, {}, NOTA_CRIADA))
        _com_fabrica(cliente, monkeypatch)
        r = flatnotes_anota(titulo="OD contrato v555", conteudo="olá")
        assert r["ok"] is True
        assert r["sobrescrito"] is False

    def test_anota_ja_existe_honesto(self, monkeypatch) -> None:
        cliente, _ = _cliente((409, {}, REPETIDA_409))
        _com_fabrica(cliente, monkeypatch)
        r = flatnotes_anota(titulo="OD contrato v555", conteudo="x")
        assert r["ok"] is False
        assert r["error"] == "flatnotes_ja_existe"

    def test_busca_ok(self, monkeypatch) -> None:
        cliente, _ = _cliente((200, {}, BUSCA_JSON))
        _com_fabrica(cliente, monkeypatch)
        r = flatnotes_busca(termo="contrato")
        assert r["ok"] is True
        assert r["total"] == 1
        assert r["resultados"][0]["trecho"] == "prova de contrato da integracao"

    def test_busca_termo_vazio_reprovado(self, monkeypatch) -> None:
        cliente, _ = _cliente((200, {}, BUSCA_VAZIA))
        _com_fabrica(cliente, monkeypatch)
        r = flatnotes_busca(termo=" ")
        assert r["ok"] is False
        assert r["error"] == "flatnotes_parametro_invalido"


# ===========================================================================
# Catálogo + permissão (só admin; sem action de apagar)
# ===========================================================================

FLATNOTES_ACOES = {"flatnotes_status", "flatnotes_anota", "flatnotes_busca"}


class TestCatalogoFlatNotes:
    def test_tres_actions_na_categoria_flatnotes(self) -> None:
        da_ferramenta = [s for s in CATALOG if s["category"] == "flatnotes"]
        assert {s["name"] for s in da_ferramenta} == FLATNOTES_ACOES
        assert len(da_ferramenta) == 3

    def test_schemas_dos_params(self) -> None:
        por_nome = {s["name"]: s for s in CATALOG}
        assert por_nome["flatnotes_status"]["params"] == {}
        anota = por_nome["flatnotes_anota"]["params"]
        assert anota.get("required") == ["titulo"]
        assert anota["properties"]["sobrescrever"]["default"] is False
        assert anota["properties"]["conteudo"]["default"] == ""
        busca = por_nome["flatnotes_busca"]["params"]
        assert busca.get("required") == ["termo"]
        assert busca["properties"]["limite"]["default"] == 10

    def test_nenhuma_action_de_apagar_no_catalogo(self) -> None:
        """DELETE da API fica fora — nada apagado por acidente."""
        nomes = {s["name"] for s in CATALOG if s["category"] == "flatnotes"}
        proibidos = ("delete", "apaga", "exclui", "remove", "limpa")
        assert not any(
            any(p in nome for p in proibidos) for nome in nomes
        )

    @pytest.mark.asyncio
    async def test_papel_user_negado_por_permissao(self) -> None:
        """Caderno do dono é do admin: papel comum não alcança."""
        registry = build_registry(security=SecurityManager(mode="strict"))
        params = {
            "flatnotes_status": {},
            "flatnotes_anota": {"titulo": "n", "conteudo": "c"},
            "flatnotes_busca": {"termo": "n"},
        }
        for nome in sorted(FLATNOTES_ACOES):
            result = await registry.execute(nome, params=params[nome], role="user")
            assert result.status == "denied", nome
            assert result.denied_by == "permission", nome

    @pytest.mark.asyncio
    async def test_papel_admin_executa(self, monkeypatch) -> None:
        """Admin passa pelo gate e a action roda no cliente fake."""
        cliente, _ = _cliente(
            (200, {}, SAUDE_OK),
            (200, {}, CONFIG_JSON),
            (200, {}, BUSCA_VAZIA),
        )
        _com_fabrica(cliente, monkeypatch)
        registry = build_registry(security=SecurityManager(mode="strict"))
        result = await registry.execute("flatnotes_status", role="admin")
        assert result.status == "ok"
        assert result.data["ok"] is True
        assert result.data["notas"] == 0


__all__ = [
    "TestClienteStatus",
    "TestClienteAnota",
    "TestClienteBusca",
    "TestErrosRede",
    "TestLimpaDestaque",
    "TestFabrica",
    "TestTransporteUrllib",
    "TestActionsFlatNotes",
    "TestCatalogoFlatNotes",
]


# ---------------------------------------------------------------------------
# 21/10 — Caderno com senha (FLATNOTES_AUTH_TYPE=password): o cliente ganhou
# login automático (POST /api/token JSON → bearer) + renovação em 401.
# Dublês FIÉIS ao contrato apurado ao vivo via OpenAPI: form-data dá 422,
# JSON devolve {"access_token": ..., "token_type": "bearer"}.
# ---------------------------------------------------------------------------


def _transporte_com_auth(negacoes_busca: int = 1):
    """Dublê com estado: /api/search nega `negacoes_busca` vezes, /api/token
    devolve o bearer, /health e /api/config são públicos (contrato vivo)."""
    chamadas: list[dict[str, Any]] = []
    tokens: list[int] = []

    def fake(
        url: str,
        *,
        timeout_s: float,
        metodo: str = "GET",
        corpo: dict[str, Any] | None = None,
        cabecalhos: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        chamadas.append(
            {"url": url, "metodo": metodo, "cabecalhos": dict(cabecalhos or {})}
        )
        if url.endswith("/api/token") and metodo == "POST":
            tokens.append(1)
            return (
                200,
                {},
                b'{"access_token":"tok-abc123","token_type":"bearer"}',
            )
        if "/health" in url:
            return 200, {}, b'{"status":"ok"}'
        if "/api/config" in url:
            return 200, {}, b'{"authType":"password"}'
        if "/api/search" in url:
            negadas = len([c for c in chamadas if "/api/search" in c["url"]]) - 1
            if negadas < negacoes_busca:
                return 401, {}, b'{"detail":"Not authenticated"}'
            return 200, {}, b"[]"
        return 404, {}, b"{}"

    return fake, chamadas, tokens


def test_senha__login_automatico_no_401__retry_com_bearer():
    fake, chamadas, tokens = _transporte_com_auth()
    c = FlatNotesClient(transporte=fake, usuario="dono", senha="s3nh4-ferrea")

    r = c.status()

    assert r["acessivel"] is True
    assert r["auth_type"] == "password"
    assert r["notas"] == 0
    # login exato UMA vez, em POST /api/token com JSON (não form-data):
    assert len(tokens) == 1
    login = [c for c in chamadas if c["url"].endswith("/api/token")][0]
    assert login["metodo"] == "POST"
    # e a busca que passou levou o Bearer no cabeçalho:
    com_bearer = [c for c in chamadas if "/api/search" in c["url"] and c["cabecalhos"]]
    assert com_bearer
    assert com_bearer[-1]["cabecalhos"]["Authorization"] == "Bearer tok-abc123"


def test_senha__login_recusado__erro_honesto_sem_ecoar_a_senha():
    def fake(url, *, timeout_s, metodo="GET", corpo=None, cabecalhos=None):
        if url.endswith("/api/token"):
            return 401, {}, b'{"detail":"bad credentials"}'
        if "/api/search" in url:
            return 401, {}, b'{"detail":"Not authenticated"}'
        if "/health" in url:
            return 200, {}, b'{"status":"ok"}'
        return 200, {}, b'{"authType":"password"}'

    segredo = "s3nh4-SECRETA-nunca-na-mensagem"
    c = FlatNotesClient(transporte=fake, usuario="dono", senha=segredo)

    with pytest.raises(FlatNotesError) as exc:
        c.status()

    assert exc.value.codigo == "flatnotes_login_falhou"
    assert "FLATNOTES_PASSWORD" in exc.value.mensagem
    assert segredo not in exc.value.mensagem


def test_sem_credencial__401_vira_erro_e_nunca_tenta_login():
    chamadas: list[str] = []

    def fake(url, *, timeout_s, metodo="GET", corpo=None, cabecalhos=None):
        chamadas.append(url)
        if "/api/search" in url:
            return 401, {}, b'{"detail":"Not authenticated"}'
        if "/health" in url:
            return 200, {}, b'{"status":"ok"}'
        return 200, {}, b'{"authType":"password"}'

    c = FlatNotesClient(transporte=fake)  # anônimo = contrato antigo intacto

    with pytest.raises(FlatNotesError) as exc:
        c.status()

    assert exc.value.codigo == "flatnotes_falhou"
    assert not any(u.endswith("/api/token") for u in chamadas)


def test_token_reusado_entre_chamadas__sem_relogar():
    fake, _chamadas, tokens = _transporte_com_auth()
    c = FlatNotesClient(transporte=fake, usuario="dono", senha="x")

    c.status()   # 401 → login → retry
    r2 = c.status()  # token em mãos: nenhum login extra

    assert r2["acessivel"] is True
    assert len(tokens) == 1
