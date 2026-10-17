"""
OMEGA DRAKON • TESTS
Módulo: tests/test_homebox.py
Descrição: Testes do Homebox (integrations/homebox.py) — 4ª e última das
           ferramentas interligadas, com uso DEFINIDO pelo dono (17/10:
           cadastrar ferramentas/peças e responder o que ele tem × o que
           falta para uma montagem). Cliente com transporte INJETÁVEL e
           fixtures fiéis ao contrato VIVO de 17/10 (swagger do próprio
           container + chamadas reais): envelope paginado de /entities,
           EntityOut completo do swagger (PUT substitui o objeto —
           GET+merge), PATCH parcial (quantity), auth por API key via
           Bearer (session token NÃO vale como Bearer — apurado ao vivo),
           tipos/tags criados com declaração, erros honestos tipados,
           NENHUMA operação de exclusão, fábrica lazy + as 6 actions.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - integrations/homebox.py (HomeboxClient + transporte injetável)
  - /swagger/doc.json do od-homebox vivo + routes.go v0.26.2 (17/10)
  - tools/actions/actions.py (homebox_status/busca/listar/detalhar/
    criar/atualizar)
"""

from __future__ import annotations

import io
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import pytest

from core.security import SecurityManager
from integrations import homebox as homebox_mod
from integrations.homebox import (
    URL_PADRAO,
    HomeboxClient,
    HomeboxError,
    _detalhe,
    _resumo,
    client_padrao,
    resetar_cliente,
)
from tools.actions import CATALOG, build_registry
from tools.actions.actions import (
    homebox_atualizar,
    homebox_busca,
    homebox_criar,
    homebox_detalhar,
    homebox_listar,
    homebox_status,
)

# ---------------------------------------------------------------------------
# Fixtures fiéis ao contrato VIVO (17/10): swagger + capturas reais
# ---------------------------------------------------------------------------

# GET /api/v1/status (captura real; build v0.26.2)
STATUS_JSON = {
    "health": True,
    "versions": None,
    "title": "Homebox",
    "message": "Track, Manage, and Organize your Things",
    "build": {"version": "v0.26.2", "commit": "e01dd737", "buildTime": ""},
    "demo": False,
    "allowRegistration": True,
    "labelPrinting": False,
    "oidc": {"enabled": False, "buttonText": "Sign in with OIDC", "allowLocal": True},
    "telemetry": {"enabled": False},
}

# GET /api/v1/groups/statistics (captura real)
STATS_JSON = {
    "totalUsers": 1,
    "totalItems": 3,
    "totalLocations": 8,
    "totalTags": 6,
    "totalItemPrice": 960.0,
    "totalWithWarranty": 1,
}

# GET /api/v1/entity-types (captura real do seed + tipo do sistema)
TIPOS_JSON = [
    {"id": "ceb67ea5-39c7-44fb-b054-f150c00dcc5b", "name": "Location",
     "description": "", "isLocation": True, "icon": "",
     "createdAt": "2026-10-17T18:23:56Z", "updatedAt": "2026-10-17T18:23:56Z"},
    {"id": "t1p1aca-0000-4000-8000-000000000001", "name": "Placa de desenvolvimento",
     "description": "", "isLocation": False, "icon": "",
     "createdAt": "2026-10-17T18:30:00Z", "updatedAt": "2026-10-17T18:30:00Z"},
]

# GET /api/v1/tags (formato TagSummary do swagger)
TAGS_JSON = [
    {"id": "g0000001-0000-4000-8000-000000000001", "name": "eletronica",
     "color": "", "description": "", "icon": "", "parentId": "",
     "createdAt": "2026-10-17T18:24:00Z", "updatedAt": "2026-10-17T18:24:00Z"},
    {"id": "g0000002-0000-4000-8000-000000000002", "name": "raspberry",
     "color": "", "description": "", "icon": "", "parentId": "",
     "createdAt": "2026-10-17T18:24:00Z", "updatedAt": "2026-10-17T18:24:00Z"},
]

# EntitySummary (17 campos do swagger) — item do envelope de /entities
RESUMO_BRUTO = {
    "id": "e1a2b3c4-d5e6-7890-abcd-ef1234567890",
    "name": "Raspberry Pi 4",
    "description": "Placa single-board 4 GB",
    "quantity": 1,
    "entityType": {"id": "t1p1aca", "name": "Placa de desenvolvimento", "isLocation": False},
    "parent": None,
    "tags": [{"id": "g1", "name": "eletronica"}, {"id": "g2", "name": "raspberry"}],
    "purchasePrice": 480.0,
    "itemCount": 1,
    "archived": False,
    "insured": False,
    "assetId": "a1", "imageId": "", "thumbnailId": "",
    "createdAt": "2026-10-17T18:30:00Z", "updatedAt": "2026-10-17T18:30:00Z",
}

# EntityOut completo (34 campos do swagger) — resposta de POST/GET/PUT
ENTIDADE_BRUTA = {
    **RESUMO_BRUTO,
    "notes": "Uso no rack da oficina",
    "manufacturer": "Raspberry Pi Foundation",
    "modelNumber": "RPI4-MOD-4GB",
    "serialNumber": "10000000abcdef12",
    "purchaseDate": "2026-09-01T00:00:00Z",
    "purchaseFrom": "Loja X",
    "lifetimeWarranty": False,
    "warrantyDetails": "",
    "soldDate": "", "soldNotes": "", "soldPrice": 0, "soldTo": "",
    "syncChildEntityLocations": False,
    "children": [], "fields": [], "attachments": [],
    "parent": {"id": "loc1", "name": "Oficina"},
}

# Envelope paginado real de GET /entities (captura ao vivo: total 0)
ENVELOPE_CHEIO = {
    "page": -1, "pageSize": -1, "total": 2,
    "items": [RESUMO_BRUTO, {**RESUMO_BRUTO, "id": "outro-id", "name": "ESP-01S"}],
    "totalPrice": 480.0,
}
ENVELOPE_VAZIO = {"page": -1, "pageSize": -1, "total": 0, "items": [], "totalPrice": 0}

ERRO_JSON = b'{"error":"entity not found"}'


def _pct(dados: dict[str, Any]) -> bytes:
    return json.dumps(dados).encode()


# ---------------------------------------------------------------------------
# Dublês
# ---------------------------------------------------------------------------

class _TransporteFalso:
    """Respostas roteirizadas por (MÉTODO, caminho) + registro de chamadas.

    A resposta pode ser (status, headers, corpo) ou exceção (levantada).
    """

    def __init__(self, respostas: dict[tuple[str, str], Any] | None = None) -> None:
        self._rotas = dict(respostas or {})
        self.chamadas: list[dict[str, Any]] = []

    def registrar(self, metodo: str, caminho: str, resposta: Any) -> None:
        self._rotas[(metodo.upper(), caminho)] = resposta

    def __call__(self, url, *, metodo="GET", headers=None, corpo=None, timeout_s=None):
        parsed = urllib.parse.urlparse(url)
        self.chamadas.append({
            "url": url, "metodo": metodo.upper(), "caminho": parsed.path,
            "consulta": parsed.query, "headers": headers or {}, "corpo": corpo,
            "timeout_s": timeout_s,
        })
        chave = (metodo.upper(), parsed.path)
        if chave not in self._rotas:
            raise AssertionError(f"rota não roteirizada: {chave}")
        item = self._rotas[chave]
        if isinstance(item, BaseException):
            raise item
        return item

    @property
    def ultimo_payload(self) -> dict[str, Any]:
        """Payload JSON enviado na última chamada (para inspecionar)."""
        corpo = self.chamadas[-1]["corpo"]
        return json.loads(corpo.decode()) if corpo else {}

    @property
    def ultimo_metodo(self) -> str:
        return self.chamadas[-1]["metodo"]


class _RespHttp:
    """Resposta urlopen falsa (context manager, status, headers, read)."""

    def __init__(self, status: int = 200, headers=None, body: bytes = b"") -> None:
        self.status = status
        self.headers = headers if headers is not None else {"Content-Type": "application/json"}
        self._body = body

    def read(self, *args: Any) -> bytes:
        return self._body

    def __enter__(self) -> "_RespHttp":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False


def _cliente(respostas: dict[tuple[str, str], Any] | None = None,
             **kw: Any) -> tuple[HomeboxClient, _TransporteFalso]:
    transporte = _TransporteFalso(respostas)
    return HomeboxClient(api_key="chave-teste", transporte=transporte, **kw), transporte


def _base_ok() -> dict[tuple[str, str], Any]:
    """Rotas mínimas de um inventário saudável."""
    return {
        ("GET", "/api/v1/status"): (200, {}, _pct(STATUS_JSON)),
        ("GET", "/api/v1/groups/statistics"): (200, {}, _pct(STATS_JSON)),
        ("GET", "/api/v1/entities"): (200, {}, _pct(ENVELOPE_CHEIO)),
        ("GET", "/api/v1/entity-types"): (200, {}, _pct(TIPOS_JSON)),
        ("GET", "/api/v1/tags"): (200, {}, _pct(TAGS_JSON)),
    }


@pytest.fixture(autouse=True)
def _fabrica_limpa():
    """Fábrica cacheada nunca vaza entre testes."""
    resetar_cliente()
    yield
    resetar_cliente()


# ===========================================================================
# Mapeamento (resumo/detalhe)
# ===========================================================================

class TestMapeamento:
    def test_resumo_extrai_o_que_importa(self) -> None:
        r = _resumo(RESUMO_BRUTO)
        assert r["id"] == "e1a2b3c4-d5e6-7890-abcd-ef1234567890"
        assert r["nome"] == "Raspberry Pi 4"
        assert r["quantidade"] == 1
        assert r["tipo"] == "Placa de desenvolvimento"
        assert r["tags"] == ["eletronica", "raspberry"]
        assert r["preco"] == 480.0
        assert r["arquivado"] is False

    def test_detalhe_acrescenta_compra_garantia_notas(self) -> None:
        d = _detalhe(ENTIDADE_BRUTA)
        assert d["notas"] == "Uso no rack da oficina"
        assert d["fabricante"] == "Raspberry Pi Foundation"
        assert d["modelo"] == "RPI4-MOD-4GB"
        assert d["serie"] == "10000000abcdef12"
        assert d["local"] == "Oficina"
        assert d["compra_origem"] == "Loja X"
        assert d["garantia_vitalicia"] is False


# ===========================================================================
# Cliente — status
# ===========================================================================

class TestClienteStatus:
    def test_status_devolve_versao_e_totais(self) -> None:
        cliente, t = _cliente(_base_ok())
        r = cliente.status()
        assert r["versao"] == "v0.26.2"
        assert r["saudavel"] is True
        assert r["total_itens"] == 3
        assert r["total_locais"] == 8
        assert r["total_preco"] == 960.0
        # /status é público (sem Authorization); statistics autenticado
        assert "Authorization" not in t.chamadas[0]["headers"]
        assert t.chamadas[1]["headers"]["Authorization"] == "Bearer chave-teste"

    def test_status_sem_chave_e_nao_autenticado(self) -> None:
        transporte = _TransporteFalso(_base_ok())
        cliente = HomeboxClient(transporte=transporte)  # api_key vazia
        with pytest.raises(HomeboxError) as exc:
            cliente.status()
        assert exc.value.codigo == "homebox_nao_autenticado"
        assert "HBOX_API_KEY" in exc.value.mensagem

    def test_status_401_e_nao_autenticado(self) -> None:
        rotas = _base_ok()
        rotas[("GET", "/api/v1/groups/statistics")] = (401, {}, ERRO_JSON)
        cliente, _ = _cliente(rotas)
        with pytest.raises(HomeboxError) as exc:
            cliente.status()
        assert exc.value.codigo == "homebox_nao_autenticado"
        assert "api-keys" in exc.value.mensagem


# ===========================================================================
# Cliente — busca e listagem
# ===========================================================================

class TestClienteBusca:
    def test_busca_monta_q_e_page_size(self) -> None:
        cliente, t = _cliente(_base_ok())
        r = cliente.buscar("raspberry", quantidade=5)
        assert r["query"] == "raspberry"
        assert r["total"] == 2
        assert [i["nome"] for i in r["itens"]] == ["Raspberry Pi 4", "ESP-01S"]
        consulta = urllib.parse.parse_qs(t.chamadas[0]["consulta"])
        assert consulta["q"] == ["raspberry"]
        assert consulta["pageSize"] == ["5"]

    def test_busca_query_vazia_e_parametro_invalido(self) -> None:
        cliente, _ = _cliente(_base_ok())
        with pytest.raises(HomeboxError) as exc:
            cliente.buscar("   ")
        assert exc.value.codigo == "homebox_parametro_invalido"

    def test_busca_quantidade_tem_teto_de_100(self) -> None:
        cliente, t = _cliente(_base_ok())
        cliente.buscar("peça", quantidade=999)
        assert "pageSize=100" in t.chamadas[0]["url"]

    def test_listar_sem_filtro_devolve_tudo(self) -> None:
        cliente, t = _cliente(_base_ok())
        r = cliente.listar(quantidade=25)
        assert r["total"] == 2
        assert r["tags_criadas"] == []
        assert "tags=" not in t.chamadas[0]["url"]

    def test_listar_por_tags_resolve_nomes_para_ids(self) -> None:
        cliente, t = _cliente(_base_ok())
        r = cliente.listar(tags="eletronica, Raspberry")
        consulta = urllib.parse.parse_qs(t.chamadas[-1]["consulta"])  # [-1] = listagem
        assert consulta["tags"] == ["g0000001-0000-4000-8000-000000000001,"
                                    "g0000002-0000-4000-8000-000000000002"]
        assert r["itens"]

    def test_listar_tag_inexistente_e_parametro_invalido(self) -> None:
        # Filtro de listagem NÃO cria tag — recusa e lista as existentes.
        cliente, _ = _cliente(_base_ok())
        with pytest.raises(HomeboxError) as exc:
            cliente.listar(tags="fantasma")
        assert exc.value.codigo == "homebox_parametro_invalido"


# ===========================================================================
# Cliente — detalhe
# ===========================================================================

class TestClienteDetalhar:
    def test_detalhar_devolve_o_completo(self) -> None:
        rotas = _base_ok()
        rotas[("GET", f"/api/v1/entities/{ENTIDADE_BRUTA['id']}")] = (
            200, {}, _pct(ENTIDADE_BRUTA)
        )
        cliente, t = _cliente(rotas)
        r = cliente.detalhar(ENTIDADE_BRUTA["id"])
        assert r["notas"] == "Uso no rack da oficina"
        assert r["local"] == "Oficina"
        assert t.chamadas[0]["headers"]["Authorization"] == "Bearer chave-teste"

    def test_detalhar_404_e_nao_encontrado(self) -> None:
        # UUID bem-formado que NÃO existe → o fork devolve 404 real
        fantasma = "00000000-0000-4000-8000-000000000000"
        rotas = _base_ok()
        rotas[("GET", f"/api/v1/entities/{fantasma}")] = (404, {}, ERRO_JSON)
        cliente, _ = _cliente(rotas)
        with pytest.raises(HomeboxError) as exc:
            cliente.detalhar(fantasma)
        assert exc.value.codigo == "homebox_nao_encontrado"
        assert fantasma in exc.value.mensagem  # mensagem honesta com o id

    def test_detalhar_id_torto_e_parametro_invalido(self) -> None:
        # Apurado ao vivo: id fora de UUID → a API devolve 400 'invalid
        # route key' — validamos ANTES com mensagem acionável.
        cliente, _ = _cliente(_base_ok())
        with pytest.raises(HomeboxError) as exc:
            cliente.detalhar("nao-existe-xyz")
        assert exc.value.codigo == "homebox_parametro_invalido"
        assert "UUID" in exc.value.mensagem

    def test_detalhar_id_vazio_e_parametro_invalido(self) -> None:
        cliente, _ = _cliente(_base_ok())
        with pytest.raises(HomeboxError) as exc:
            cliente.detalhar("")
        assert exc.value.codigo == "homebox_parametro_invalido"


# ===========================================================================
# Cliente — cadastro (o uso central do dono)
# ===========================================================================

class TestClienteCriar:
    def test_criar_minimo_envia_name_e_quantity(self) -> None:
        rotas = _base_ok()
        rotas[("POST", "/api/v1/entities")] = (201, {}, _pct(ENTIDADE_BRUTA))
        cliente, t = _cliente(rotas)
        r = cliente.criar("Raspberry Pi 4")
        assert t.ultimo_metodo == "POST"
        assert t.ultimo_payload["name"] == "Raspberry Pi 4"
        assert t.ultimo_payload["quantity"] == 1
        assert "entityTypeId" not in t.ultimo_payload  # sem tipo = sem campo
        assert r["nome"] == "Raspberry Pi 4"
        assert r["tipo_criado"] is False
        assert r["tags_criadas"] == []

    def test_criar_com_tipo_existente_reusa(self) -> None:
        rotas = _base_ok()
        rotas[("POST", "/api/v1/entities")] = (201, {}, _pct(ENTIDADE_BRUTA))
        cliente, t = _cliente(rotas)
        cliente.criar("ESP-01S", tipo="Placa de desenvolvimento")
        assert t.ultimo_payload["entityTypeId"] == "t1p1aca-0000-4000-8000-000000000001"

    def test_criar_tipo_inexistente_e_criado_com_declaracao(self) -> None:
        rotas = _base_ok()
        rotas[("POST", "/api/v1/entity-types")] = (
            201, {}, _pct({"id": "novo-tipo", "name": "Módulo sensor"})
        )
        rotas[("POST", "/api/v1/entities")] = (201, {}, _pct(ENTIDADE_BRUTA))
        cliente, t = _cliente(rotas)
        r = cliente.criar("DHT22", tipo="Módulo sensor")
        # a criação do tipo aconteceu ANTES da entidade, com isLocation falso
        metodos = [(c["metodo"], c["caminho"]) for c in t.chamadas]
        assert ("POST", "/api/v1/entity-types") in metodos
        assert t.chamadas[-2]["metodo"] == "POST"
        assert t.chamadas[-2]["caminho"] == "/api/v1/entity-types"
        assert t.ultimo_payload["name"] == "DHT22"  # última chamada = entidade
        assert t.ultimo_payload["entityTypeId"] == "novo-tipo"
        assert r["tipo_criado"] is True
        assert r["nome"] == "Raspberry Pi 4"  # eco devolvido pelo servidor

    def test_criar_tipo_recusado_quando_criar_tipo_false(self) -> None:
        cliente, _ = _cliente(_base_ok())
        with pytest.raises(HomeboxError) as exc:
            cliente.criar("X", tipo="Fantasma", criar_tipo=False)
        assert exc.value.codigo == "homebox_parametro_invalido"
        assert "Location" in exc.value.mensagem  # lista os existentes

    def test_criar_tags_reusadas_e_novas_com_declaracao(self) -> None:
        rotas = _base_ok()
        rotas[("POST", "/api/v1/tags")] = (
            201, {}, _pct({"id": "tag-nova", "name": "sensor"})
        )
        rotas[("POST", "/api/v1/entities")] = (201, {}, _pct(ENTIDADE_BRUTA))
        cliente, t = _cliente(rotas)
        r = cliente.criar("DHT22", tags="eletronica, sensor")
        assert t.ultimo_payload["tagIds"] == [
            "g0000001-0000-4000-8000-000000000001", "tag-nova"
        ]
        assert r["tags_criadas"] == ["sensor"]

    def test_criar_notas_ou_preco_passam_por_put_completo(self) -> None:
        # EntityCreate NÃO aceita notes/purchasePrice — o PUT (que
        # SUBSTITUI o objeto) vem com todos os campos atuais preservados.
        rotas = _base_ok()
        rotas[("POST", "/api/v1/entities")] = (201, {}, _pct(ENTIDADE_BRUTA))
        rotas[("PUT", f"/api/v1/entities/{ENTIDADE_BRUTA['id']}")] = (
            200, {}, _pct({**ENTIDADE_BRUTA, "notes": "compras de setembro"})
        )
        cliente, t = _cliente(rotas)
        r = cliente.criar("Pi 4", notas="compras de setembro", preco=480.0)
        puts = [c for c in t.chamadas if c["metodo"] == "PUT"]
        assert len(puts) == 1
        payload = json.loads(puts[0]["corpo"].decode())
        assert payload["notes"] == "compras de setembro"
        assert payload["purchasePrice"] == 480.0
        assert payload["name"] == "Raspberry Pi 4"  # name obrigatório do PUT
        assert payload["quantity"] == 1             # campos atuais preservados
        assert r["notas"] == "compras de setembro"

    def test_criar_nome_vazio_e_parametro_invalido(self) -> None:
        cliente, _ = _cliente(_base_ok())
        with pytest.raises(HomeboxError) as exc:
            cliente.criar("  ")
        assert exc.value.codigo == "homebox_parametro_invalido"

    def test_criar_post_nao_201_e_falhou(self) -> None:
        rotas = _base_ok()
        rotas[("POST", "/api/v1/entities")] = (500, {}, ERRO_JSON)
        cliente, _ = _cliente(rotas)
        with pytest.raises(HomeboxError) as exc:
            cliente.criar("X")
        assert exc.value.codigo == "homebox_falhou"


# ===========================================================================
# Cliente — atualização
# ===========================================================================

class TestClienteAtualizar:
    def test_quantidade_pura_usa_patch_parcial(self) -> None:
        rotas = _base_ok()
        rotas[("PATCH", f"/api/v1/entities/{ENTIDADE_BRUTA['id']}")] = (
            200, {}, _pct({**ENTIDADE_BRUTA, "quantity": 0})
        )
        cliente, t = _cliente(rotas)
        r = cliente.atualizar(ENTIDADE_BRUTA["id"], quantidade=0)
        assert t.ultimo_metodo == "PATCH"
        assert t.ultimo_payload == {"quantity": 0}  # parcial de verdade
        assert r["quantidade"] == 0

    def test_notas_vao_por_put_completo_preservado(self) -> None:
        atual = {**ENTIDADE_BRUTA}
        rotas = _base_ok()
        rotas[("GET", f"/api/v1/entities/{ENTIDADE_BRUTA['id']}")] = (200, {}, _pct(atual))
        rotas[("PUT", f"/api/v1/entities/{ENTIDADE_BRUTA['id']}")] = (
            200, {}, _pct({**atual, "notes": "gastei 2"})
        )
        cliente, t = _cliente(rotas)
        r = cliente.atualizar(ENTIDADE_BRUTA["id"], notas="gastei 2")
        puts = [c for c in t.chamadas if c["metodo"] == "PUT"]
        payload = json.loads(puts[0]["corpo"].decode())
        assert payload["notes"] == "gastei 2"
        assert payload["name"] == "Raspberry Pi 4"   # não zerou nada
        assert payload["quantity"] == 1
        assert r["notas"] == "gastei 2"

    def test_sem_campos_e_parametro_invalido(self) -> None:
        cliente, _ = _cliente(_base_ok())
        with pytest.raises(HomeboxError) as exc:
            cliente.atualizar(ENTIDADE_BRUTA["id"])  # UUID válido, sem campos
        assert exc.value.codigo == "homebox_parametro_invalido"

    def test_id_torto_e_parametro_invalido_antes_da_chamada(self) -> None:
        cliente, t = _cliente(_base_ok())
        with pytest.raises(HomeboxError) as exc:
            cliente.atualizar("abc", quantidade=1)
        assert exc.value.codigo == "homebox_parametro_invalido"
        assert t.chamadas == []  # nem foi na rede

    def test_id_vazio_e_parametro_invalido(self) -> None:
        cliente, _ = _cliente(_base_ok())
        with pytest.raises(HomeboxError) as exc:
            cliente.atualizar("", quantidade=1)
        assert exc.value.codigo == "homebox_parametro_invalido"

    def test_quantidade_negativa_zera_em_vez_de_erlar(self) -> None:
        rotas = _base_ok()
        rotas[("PATCH", f"/api/v1/entities/{ENTIDADE_BRUTA['id']}")] = (
            200, {}, _pct({**ENTIDADE_BRUTA, "quantity": 0})
        )
        cliente, t = _cliente(rotas)
        cliente.atualizar(ENTIDADE_BRUTA["id"], quantidade=-5)
        assert t.ultimo_payload["quantity"] == 0

    def test_put_omite_parent_e_tipo_vazios(self) -> None:
        # Regressão do 500 ao vivo (17/10): parentId="" quebra o fork
        # ('Unknown Error') — opcionais só entram quando PRESENTES.
        sem_parent = {**ENTIDADE_BRUTA, "parent": None, "entityType": None}
        rotas = _base_ok()
        rotas[("GET", f"/api/v1/entities/{ENTIDADE_BRUTA['id']}")] = (200, {}, _pct(sem_parent))
        rotas[("PUT", f"/api/v1/entities/{ENTIDADE_BRUTA['id']}")] = (
            200, {}, _pct({**sem_parent, "notes": "ok"})
        )
        cliente, t = _cliente(rotas)
        cliente.atualizar(ENTIDADE_BRUTA["id"], notas="ok")
        puts = [c for c in t.chamadas if c["metodo"] == "PUT"]
        payload = json.loads(puts[0]["corpo"].decode())
        assert "parentId" not in payload       # vazio NÃO vai (quebrava o fork)
        assert "entityTypeId" not in payload   # idem
        assert payload["notes"] == "ok"
        assert payload["name"] == "Raspberry Pi 4"


# ===========================================================================
# Transporte urllib — rede de verdade
# ===========================================================================

class TestTransporteUrllib:
    def test_urlopen_ok_vira_resposta(self, monkeypatch) -> None:
        monkeypatch.setattr(
            urllib.request, "urlopen",
            lambda req, timeout=None: _RespHttp(200, {}, _pct(STATUS_JSON)),
        )
        cliente = HomeboxClient(api_key="k")
        _s, dados = cliente._chamada("/api/v1/status", autenticado=False)
        assert dados["build"]["version"] == "v0.26.2"

    def test_httperror_401_e_nao_autenticado(self, monkeypatch) -> None:
        def falso(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url, 401, "Unauthorized", {}, io.BytesIO(ERRO_JSON)
            )

        monkeypatch.setattr(urllib.request, "urlopen", falso)
        cliente = HomeboxClient(api_key="k")
        with pytest.raises(HomeboxError) as exc:
            cliente.buscar("x")
        assert exc.value.codigo == "homebox_nao_autenticado"

    def test_httperror_500_e_falhou_com_mensagem_da_api(self, monkeypatch) -> None:
        def falso(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url, 500, "Boom", {}, io.BytesIO(ERRO_JSON)
            )

        monkeypatch.setattr(urllib.request, "urlopen", falso)
        cliente = HomeboxClient(api_key="k")
        with pytest.raises(HomeboxError) as exc:
            cliente.buscar("x")
        assert exc.value.codigo == "homebox_falhou"
        assert "entity not found" in exc.value.mensagem

    def test_urlerror_vira_indisponivel(self, monkeypatch) -> None:
        def falso(req, timeout=None):
            raise urllib.error.URLError("caiu")

        monkeypatch.setattr(urllib.request, "urlopen", falso)
        cliente = HomeboxClient(api_key="k")
        with pytest.raises(HomeboxError) as exc:
            cliente.buscar("x")
        assert exc.value.codigo == "homebox_indisponivel"

    def test_timeout_vira_homebox_timeout(self, monkeypatch) -> None:
        def falso(req, timeout=None):
            raise socket.timeout("demorou")

        monkeypatch.setattr(urllib.request, "urlopen", falso)
        cliente = HomeboxClient(api_key="k")
        with pytest.raises(HomeboxError) as exc:
            cliente.buscar("x")
        assert exc.value.codigo == "homebox_timeout"

    def test_corpo_nao_json_e_resposta_invalida(self, monkeypatch) -> None:
        monkeypatch.setattr(
            urllib.request, "urlopen",
            lambda req, timeout=None: _RespHttp(200, {}, b"<html>spa</html>"),
        )
        cliente = HomeboxClient(api_key="k")
        with pytest.raises(HomeboxError) as exc:
            cliente.buscar("x")
        assert exc.value.codigo == "homebox_resposta_invalida"


# ===========================================================================
# Fábrica lazy — env, cache, reset
# ===========================================================================

class TestFabrica:
    def test_padrao_e_local(self) -> None:
        c = client_padrao()
        assert c.base_url == URL_PADRAO == "http://127.0.0.1:8470"

    def test_url_e_chave_do_env(self, monkeypatch) -> None:
        monkeypatch.setenv("OD_HOMEB_URL", "http://127.0.0.1:9999/")
        monkeypatch.setenv("HBOX_API_KEY", "chave-do-env")
        c = client_padrao()
        assert c.base_url == "http://127.0.0.1:9999"
        assert c.api_key == "chave-do-env"

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
    monkeypatch.setattr(homebox_mod, "client_padrao", lambda: cliente)


class TestActionsHomebox:
    def test_status_ok(self, monkeypatch) -> None:
        cliente, _ = _cliente(_base_ok())
        _com_fabrica(cliente, monkeypatch)
        r = homebox_status()
        assert r["ok"] is True
        assert r["versao"] == "v0.26.2"
        assert r["total_itens"] == 3

    def test_status_fora_do_ar_degrada_a_action(self, monkeypatch) -> None:
        cliente, _ = _cliente({("GET", "/api/v1/status"): urllib.error.URLError("caiu")})
        _com_fabrica(cliente, monkeypatch)
        r = homebox_status()
        assert r["ok"] is False
        assert r["error"] == "homebox_indisponivel"
        assert "inacessível" in r["message"]

    def test_busca_action_ok(self, monkeypatch) -> None:
        cliente, _ = _cliente(_base_ok())
        _com_fabrica(cliente, monkeypatch)
        r = homebox_busca(query="raspberry", quantidade=2)
        assert r["ok"] is True
        assert r["total"] == 2
        assert r["itens"][0]["nome"] == "Raspberry Pi 4"

    def test_listar_action_ok(self, monkeypatch) -> None:
        cliente, _ = _cliente(_base_ok())
        _com_fabrica(cliente, monkeypatch)
        r = homebox_listar(quantidade=25)
        assert r["ok"] is True
        assert len(r["itens"]) == 2

    def test_detalhar_action_ok(self, monkeypatch) -> None:
        rotas = _base_ok()
        rotas[("GET", f"/api/v1/entities/{ENTIDADE_BRUTA['id']}")] = (
            200, {}, _pct(ENTIDADE_BRUTA)
        )
        cliente, _ = _cliente(rotas)
        _com_fabrica(cliente, monkeypatch)
        r = homebox_detalhar(id=ENTIDADE_BRUTA["id"])
        assert r["ok"] is True
        assert r["notas"] == "Uso no rack da oficina"

    def test_criar_action_ok_com_declaracoes(self, monkeypatch) -> None:
        rotas = _base_ok()
        rotas[("POST", "/api/v1/tags")] = (
            201, {}, _pct({"id": "tag-nova", "name": "sensor"})
        )
        rotas[("POST", "/api/v1/entities")] = (201, {}, _pct(ENTIDADE_BRUTA))
        cliente, _ = _cliente(rotas)
        _com_fabrica(cliente, monkeypatch)
        r = homebox_criar(nome="DHT22", quantidade=2, tipo="Placa de desenvolvimento",
                          tags="eletronica, sensor")
        assert r["ok"] is True
        assert r["tags_criadas"] == ["sensor"]
        assert r["tipo_criado"] is False

    def test_atualizar_action_ok(self, monkeypatch) -> None:
        rotas = _base_ok()
        rotas[("PATCH", f"/api/v1/entities/{ENTIDADE_BRUTA['id']}")] = (
            200, {}, _pct({**ENTIDADE_BRUTA, "quantity": 0})
        )
        cliente, _ = _cliente(rotas)
        _com_fabrica(cliente, monkeypatch)
        r = homebox_atualizar(id=ENTIDADE_BRUTA["id"], quantidade=0)
        assert r["ok"] is True
        assert r["quantidade"] == 0

    def test_credencial_recusada_e_honesta(self, monkeypatch) -> None:
        rotas = _base_ok()
        rotas[("GET", "/api/v1/entities")] = (401, {}, ERRO_JSON)
        cliente, _ = _cliente(rotas)
        _com_fabrica(cliente, monkeypatch)
        r = homebox_busca(query="x")
        assert r["ok"] is False
        assert r["error"] == "homebox_nao_autenticado"


# ===========================================================================
# Catálogo — 6 actions, categoria homebox, permissão, SEM exclusão
# ===========================================================================

HOMEBX_ACOES = {
    "homebox_status", "homebox_busca", "homebox_listar",
    "homebox_detalhar", "homebox_criar", "homebox_atualizar",
}


class TestCatalogoHomebox:
    def test_seis_actions_na_categoria_homebox(self) -> None:
        da_ferramenta = [s for s in CATALOG if s["category"] == "homebox"]
        assert {s["name"] for s in da_ferramenta} == HOMEBX_ACOES
        assert len(da_ferramenta) == 6

    def test_schemas_dos_params(self) -> None:
        por_nome = {s["name"]: s for s in CATALOG}
        assert por_nome["homebox_status"]["params"] == {}
        assert por_nome["homebox_busca"]["params"].get("required") == ["query"]
        assert por_nome["homebox_busca"]["params"]["properties"]["quantidade"]["default"] == 10
        assert por_nome["homebox_listar"]["params"]["properties"]["quantidade"]["default"] == 25
        assert por_nome["homebox_detalhar"]["params"].get("required") == ["id"]
        assert por_nome["homebox_criar"]["params"].get("required") == ["nome"]
        assert por_nome["homebox_criar"]["params"]["properties"]["criar_tipo"]["default"] is True
        assert por_nome["homebox_atualizar"]["params"].get("required") == ["id"]

    def test_nenhuma_action_deleta(self) -> None:
        # Régua do dono: nada apagado — o inventário só LÊ e CADASTRA.
        # (As 4 actions `*_delete` legadas — Drive/Calendar/Gmail/filesystem
        # — são de outras integrações e não fazem parte da categoria.)
        proibidos = ("delete", "exclu", "apagar", "remover", "destruir")
        da_ferramenta = [s for s in CATALOG if s["category"] == "homebox"]
        assert len(da_ferramenta) == 6
        for s in da_ferramenta:
            nome = s["name"].lower()
            assert not any(p in nome for p in proibidos), s["name"]
            assert not any(p in s["description"].lower() for p in ("apagar", "excluir")), s["name"]

    @pytest.mark.asyncio
    async def test_papel_user_negado_por_permissao(self) -> None:
        """Inventário do dono é do admin: papel comum não alcança."""
        registry = build_registry(security=SecurityManager(mode="strict"))
        params = {
            "homebox_status": {},
            "homebox_busca": {"query": "peça"},
            "homebox_listar": {},
            "homebox_detalhar": {"id": "abc"},
            "homebox_criar": {"nome": "Peça"},
            "homebox_atualizar": {"id": "abc", "quantidade": 1},
        }
        for nome in sorted(HOMEBX_ACOES):
            result = await registry.execute(nome, params=params[nome], role="user")
            assert result.status == "denied", nome
            assert result.denied_by == "permission", nome


__all__ = [
    "TestMapeamento",
    "TestClienteStatus",
    "TestClienteBusca",
    "TestClienteDetalhar",
    "TestClienteCriar",
    "TestClienteAtualizar",
    "TestTransporteUrllib",
    "TestFabrica",
    "TestActionsHomebox",
    "TestCatalogoHomebox",
]
