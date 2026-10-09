"""
OMEGA DRAKON • TESTES
Registro Mestre de peças (core/registry.py + GET /registry/{codigo} +
/admin/registry) — item 2 da pauta de divergências (2026-10-09).

Cobre:
- RegistryStore: criação, ID canônico sequencial, busca por public_id e
  engraved_code, update com whitelist e coerência de estados.
- Rota pública /registry/{codigo}: projeção SEM preço/notas, username só
  quando registrada, 404 para código inexistente, público sob auth_all.
- Rotas admin: dono cadastra/edita; usuário comum leva 403; sem banco → 503.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.registry import RegistryStore  # noqa: E402
from storage import Database  # noqa: E402


# ---------------------------------------------------------------------------#
# Fixtures                                                                    #
# ---------------------------------------------------------------------------#
@pytest.fixture()
def store(tmp_path: Path) -> RegistryStore:
    return RegistryStore(Database(tmp_path / "registry.db"))


@pytest.fixture()
def serve():
    """Sobe APIServers sob demanda e derruba todos no fim (espelho de test_api)."""
    from integrations.api import APIServer

    servers = []

    def _start(orch=None, *, config=None) -> APIServer:
        srv = APIServer(orch, config=config)
        srv.serve_background()
        servers.append(srv)
        return srv

    yield _start
    for srv in servers:
        try:
            srv.stop()
        except Exception:
            pass


# ---------------------------------------------------------------------------#
# RegistryStore (banco)                                                       #
# ---------------------------------------------------------------------------#
class TestRegistryStore:
    def test_cria_peca_com_id_canonico(self, store: RegistryStore) -> None:
        item = store.create(name="Anel Abissal", kind="exclusiva", collection="abissal")
        assert item["public_id"].startswith("OD-PROD-")
        assert item["status"] == "estoque"
        assert item["owner_username"] is None

    def test_id_sequencial_no_mesmo_ano(self, store: RegistryStore) -> None:
        a = store.create(name="Peça A", kind="exclusiva")
        b = store.create(name="Peça B", kind="exclusiva")
        assert a["public_id"] != b["public_id"]
        seq_a = int(a["public_id"].rsplit("-", 1)[1])
        seq_b = int(b["public_id"].rsplit("-", 1)[1])
        assert seq_b == seq_a + 1

    def test_busca_por_engraved_code(self, store: RegistryStore) -> None:
        item = store.create(name="Chaveiro", kind="publica", engraved_code="nv-abi-7f3a")
        found = store.get("NV-ABI-7F3A")  # normaliza maiúsculas
        assert found is not None and found["public_id"] == item["public_id"]

    def test_codigo_gravado_duplicado_erro(self, store: RegistryStore) -> None:
        store.create(name="A", kind="exclusiva", engraved_code="X-1")
        with pytest.raises(ValueError, match="codigo_duplicado"):
            store.create(name="B", kind="exclusiva", engraved_code="x-1")

    def test_kind_invalido_erro(self, store: RegistryStore) -> None:
        with pytest.raises(ValueError, match="kind_invalido"):
            store.create(name="A", kind="lenda")

    def test_update_whitelist_e_status(self, store: RegistryStore) -> None:
        item = store.create(name="A", kind="exclusiva", price_brl=100.0)
        store.update(item["public_id"], status="vendida", owner_username="bia")
        got = store.get(item["public_id"])
        assert got["status"] == "vendida"
        # whitelist: id e public_id nunca mudam
        store.update(item["public_id"], id=999, public_id="HACK", name="B")
        got2 = store.get(item["public_id"])
        assert got2["name"] == "B" and got2["public_id"] == item["public_id"]

    def test_registrada_sem_dono_erro(self, store: RegistryStore) -> None:
        item = store.create(name="A", kind="exclusiva")
        with pytest.raises(ValueError, match="registrada_sem_dono"):
            store.update(item["public_id"], status="registrada")

    def test_projecao_publica_esconde_privado(self, store: RegistryStore) -> None:
        item = store.create(
            name="Anel", kind="exclusiva", price_brl=250.0,
            notes="custo 40, margem boa", engraved_code="AB-1",
        )
        pub = store.verify_public(item["public_id"])
        assert pub is not None
        assert "price_brl" not in pub and "notes" not in pub and "id" not in pub
        assert pub["owner_username"] is None and pub["registered"] is False

    def test_projecao_publica_username_so_quando_registrada(self, store: RegistryStore) -> None:
        item = store.create(name="A", kind="exclusiva")
        store.update(item["public_id"], status="registrada", owner_username="bia")
        pub = store.verify_public(item["public_id"])
        assert pub["owner_username"] == "bia" and pub["registered"] is True

    def test_verify_inexistente_none(self, store: RegistryStore) -> None:
        assert store.verify_public("OD-PROD-9999-9999") is None


# ---------------------------------------------------------------------------#
# Rotas (integração HTTP)                                                      #
# ---------------------------------------------------------------------------#
class TestRegistryRotas:
    @pytest.fixture()
    def srv(self, serve, tmp_path: Path):
        from core.registry import RegistryStore as RS
        from storage import Database as DB
        from integrations.api import APIConfig

        db = DB(tmp_path / "api-registry.db")
        reg = RS(db)
        cfg = APIConfig(port=0, rate_limit_max=0, api_key="segredo123",
                        auth_all=True, registry=reg)
        return serve(None, config=cfg), reg

    def test_publica_sob_auth_all_sem_credencial(self, serve, tmp_path: Path) -> None:
        """Produção (auth_all): a consulta pública NÃO pede chave."""
        from core.registry import RegistryStore as RS
        from storage import Database as DB
        from integrations.api import APIConfig

        db = DB(tmp_path / "pub.db")
        reg = RS(db)
        item = reg.create(name="Anel Abissal", kind="exclusiva",
                          collection="abissal", price_brl=500.0)
        cfg = APIConfig(port=0, rate_limit_max=0, api_key="segredo123",
                        auth_all=True, registry=reg)
        srv = serve(None, config=cfg)
        status, body, _ = _request(srv.bound_port, "GET",
                                   f"/registry/{item['public_id']}")
        data = _json_response((status, body, None))
        assert status == 200, body
        assert data["ok"] is True
        peca = data["peca"]
        assert peca["public_id"] == item["public_id"]
        assert "price_brl" not in peca and "notes" not in peca
        assert peca["owner_username"] is None

    def test_404_codigo_inexistente(self, srv) -> None:
        server, _ = srv
        status, body, _ = _request(server.bound_port, "GET",
                                   "/registry/OD-PROD-9999-9999")
        assert status == 404
        data = _json_response((status, body, None))
        assert data["error"] == "nao_encontrada"

    def test_admin_cria_lista_atualiza(self, srv) -> None:
        server, _ = srv
        # cria (dono: api_key do servidor)
        status, body, _ = _request(server.bound_port, "POST", "/admin/registry",
                                   api_key="segredo123",
                                   raw_body='{"name":"Chaveiro OD","kind":"publica"}')
        assert status == 201, body
        item = _json_response((status, body, None))["peca"]
        assert item["kind"] == "publica" and item["status"] == "estoque"
        # lista
        status, body, _ = _request(server.bound_port, "GET", "/admin/registry",
                                   api_key="segredo123")
        data = _json_response((status, body, None))
        assert status == 200 and data["total"] == 1
        # atualiza para registrada com dono
        status, body, _ = _request(
            server.bound_port, "PUT", f"/admin/registry/{item['public_id']}",
            api_key="segredo123",
            raw_body='{"status":"registrada","owner_username":"bia"}')
        assert status == 200
        got = _json_response((status, body, None))["peca"]
        assert got["status"] == "registrada" and got["owner_username"] == "bia"

    def test_comum_403(self, serve, store) -> None:
        from integrations.api import APIConfig, APIServer
        from integrations.api.auth import UserStore

        db = store._db  # mesmo banco
        users = UserStore(db)
        users.register("comum", "comum@x.com", "senha-forte-123")
        cfg = APIConfig(port=0, rate_limit_max=0, api_key="segredo123",
                        auth_all=True, registry=store, user_store=users,
                        owner_username="dono")
        srv = APIServer(None, config=cfg)
        srv.serve_background()
        try:
            # credencial de usuário comum não é admin
            key = users.get_user_by_username("comum").api_key
            status, body, _ = _request(srv.bound_port, "GET", "/admin/registry",
                                       api_key=key)
            assert status == 403
        finally:
            srv.stop()


# helpers locais (espelho de tests/test_api.py) ------------------------------#
def _request(port: int, method: str, path: str, api_key=None, body=None,
             raw_body=None, headers=None):
    import json as _json
    import urllib.request
    import urllib.error

    url = f"http://127.0.0.1:{port}{path}"
    data = raw_body.encode() if raw_body else (
        _json.dumps(body).encode() if body is not None else None)
    hdrs = {"Content-Type": "application/json"} if data else {}
    if api_key:
        hdrs["X-API-Key"] = api_key
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def _json_response(tuple_resp):
    import json as _json
    _, body, _ = tuple_resp
    return _json.loads(body.decode() or "{}")
