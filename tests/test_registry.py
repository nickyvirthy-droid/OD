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

import json
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


@pytest.fixture()
def srv(serve, tmp_path: Path):
    """Servidor de teste com Registro Mestre + api_key fixa (auth_all)."""
    from integrations.api import APIConfig

    db = Database(tmp_path / "api-registry.db")
    reg = RegistryStore(db)
    cfg = APIConfig(port=0, rate_limit_max=0, api_key="segredo123",
                    auth_all=True, registry=reg)
    return serve(None, config=cfg), reg


# ---------------------------------------------------------------------------#
# RegistryStore (banco)                                                       #
# ---------------------------------------------------------------------------#
class TestRegistryStore:
    def test_cria_peca_com_id_canonico(self, store: RegistryStore) -> None:
        store.criar_colecao("abissal")  # frente NV exige ciclo aberto
        item = store.create(name="Anel Abissal", kind="exclusiva", frente="NV",
                            tipo="SJ", collection="abissal")
        assert item["public_id"].startswith("NV-SJ-")
        assert item["status"] == "estoque"
        assert item["owner_username"] is None

    def test_frente_tipo_padrao_prod_pe(self, store: RegistryStore) -> None:
        item = store.create(name="Trena", kind="publica")
        assert item["public_id"].startswith("PROD-PE-")

    def test_frente_tipo_invalidos(self, store: RegistryStore) -> None:
        with pytest.raises(ValueError, match="frente_invalido"):
            store.create(name="X", kind="publica", frente="A-B")
        with pytest.raises(ValueError, match="frente_invalido"):
            store.create(name="X", kind="publica", frente="LONODEMAIS")
        with pytest.raises(ValueError, match="tipo_invalido"):
            store.create(name="X", kind="publica", tipo="1S")

    def test_sequencia_por_frente_tipo_ano(self, store: RegistryStore) -> None:
        store.criar_colecao("abissal")  # frente NV exige ciclo aberto
        a = store.create(name="Joia A", kind="exclusiva", frente="NV", tipo="SJ",
                         collection="abissal")
        b = store.create(name="Quadro", kind="exclusiva", frente="PROD", tipo="PE")
        c = store.create(name="Joia B", kind="exclusiva", frente="NV", tipo="SJ",
                         collection="abissal")
        # PROD-PE não consome o número do NV-SJ; NV-SJ continua de 1 em 1.
        assert a["public_id"].endswith("-0001")
        assert c["public_id"].endswith("-0002")
        assert b["public_id"].endswith("-0001") and "PROD-PE-" in b["public_id"]

    def test_exclusiva_sem_codigo_ganha_curto_nv(self, store: RegistryStore) -> None:
        store.criar_colecao("abissal")  # frente NV exige ciclo aberto
        item = store.create(name="Anel Abissal", kind="exclusiva", frente="NV",
                            tipo="SJ", collection="abissal")
        curto = item["engraved_code"]
        assert curto is not None and curto.startswith("NV-ABI-")
        assert len(curto) == len("NV-ABI-7F3A")
        # e acha a peça pelo curto
        assert store.get(curto)["public_id"] == item["public_id"]

    def test_publica_sem_codigo_fica_sem_curto(self, store: RegistryStore) -> None:
        item = store.create(name="Trena", kind="publica")
        assert item["engraved_code"] is None

    def test_migracao_id_legado(self, store: RegistryStore) -> None:
        # linha crua no formato v1.22 (OD-PROD-…)
        store._db.execute(
            "INSERT INTO registry_items (public_id, engraved_code, name, "
            "collection, kind, status, created_at) VALUES "
            "('OD-PROD-2026-0004','NV-OD-5E8A','Chaveiro','OD','publica',"
            "'estoque',1.0)"
        )
        store._db.execute(
            "INSERT INTO registry_items (public_id, engraved_code, name, "
            "collection, kind, status, created_at) VALUES "
            "('OD-PROD-2026-0001','NV-ABI-7F3A','Anel','ABISSAL','exclusiva',"
            "'estoque',1.0)"
        )
        mudou = store.migrar_ids_legados()
        assert ("OD-PROD-2026-0004", "PROD-PE-2026-0004") in mudou
        assert ("OD-PROD-2026-0001", "NV-SJ-2026-0001") in mudou
        assert store.get("NV-SJ-2026-0001") is not None
        assert store.get("PROD-PE-2026-0004") is not None
        assert store.get("OD-PROD-2026-0001") is None
        # idempotente: segunda rodada não muda nada
        assert store.migrar_ids_legados() == []

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


# ---------------------------------------------------------------------------#
# Cadastro no painel admin (v1.22.1) + remoção                                #
# ---------------------------------------------------------------------------#
class TestRegistroAdminPainel:
    def test_delete_remove_peca(self, store: RegistryStore) -> None:
        item = store.create(name="A", kind="publica")
        assert store.delete(item["public_id"]) is True
        assert store.get(item["public_id"]) is None
        assert store.delete(item["public_id"]) is False  # já foi

    def test_admin_delete_rota(self, srv) -> None:
        server, _ = srv
        status, body, _ = _request(server.bound_port, "POST", "/admin/registry",
                                   api_key="segredo123",
                                   raw_body='{"name":"Descartável","kind":"publica"}')
        assert status == 201
        item = _json_response((status, body, None))["peca"]
        # público enxerga antes de remover
        status, _, _ = _request(server.bound_port, "GET",
                                "/registry/" + item["public_id"])
        assert status == 200
        # remove (admin)
        status, body, _ = _request(server.bound_port, "DELETE",
                                   "/admin/registry/" + item["public_id"],
                                   api_key="segredo123")
        assert status == 200
        # some da consulta pública
        status, _, _ = _request(server.bound_port, "GET",
                                "/registry/" + item["public_id"])
        assert status == 404
        # remover de novo = 404
        status, _, _ = _request(server.bound_port, "DELETE",
                                "/admin/registry/" + item["public_id"],
                                api_key="segredo123")
        assert status == 404

    def test_admin_page_tem_secao_de_cadastro(self, serve) -> None:
        """O painel /admin traz a seção do Registro Mestre (shell público)."""
        from integrations.api import APIConfig

        cfg = APIConfig(port=0, rate_limit_max=0, api_key="segredo123")
        srv = serve(None, config=cfg)
        status, body, _ = _request(srv.bound_port, "GET", "/admin")
        html = body.decode("utf-8", "replace")
        assert status == 200
        assert "Registro Mestre (peças)" in html
        assert "/admin/registry" in html          # endpoints que a UI usa
        assert 'id="reg-nome"' in html            # campo de cadastro
        assert "regRegistrar" in html             # fluxo de registro por QR
        assert "regFotoEnviar" in html            # upload de foto da peça (1.23.0)
        assert "regChatToggle" in html            # sala de bate-papo (1.23.0)
        assert "reg-chat-del" in html             # moderação da sala (1.23.0)
        assert "🐉" not in html

    def test_transicao_carimba_timestamps(self, store: RegistryStore) -> None:
        """vendida grava sold_at; registrada grava registered_at (sozinhas)."""
        item = store.create(name="A", kind="exclusiva")
        got = store.update(item["public_id"], status="vendida")
        assert got["sold_at"] is not None and got["registered_at"] is None
        got2 = store.update(item["public_id"], status="registrada",
                            owner_username="bia")
        assert got2["registered_at"] is not None
        # repetir a transição não re-carimba (valor já existe)
        s1, r1 = got2["sold_at"], got2["registered_at"]
        got3 = store.update(item["public_id"], status="registrada",
                            owner_username="bia")
        assert (got3["sold_at"], got3["registered_at"]) == (s1, r1)


# ---------------------------------------------------------------------------#
# 1.23.0 — busca sem hífen, foto do produto e sala de bate-papo               #
# ---------------------------------------------------------------------------#
class TestBuscaSemHifen:
    def test_store_acha_sem_separadores(self, store: RegistryStore) -> None:
        item = store.create(name="Anel", kind="exclusiva",
                            engraved_code="NV-ABI-7F3A")
        sem_hifen_id = item["public_id"].replace("-", "").lower()
        assert store.get(sem_hifen_id)["public_id"] == item["public_id"]
        assert store.get("nvabi7f3a")["public_id"] == item["public_id"]
        # com espaços também vale
        assert store.get("nv abi 7f3a")["public_id"] == item["public_id"]

    def test_rota_publica_sem_hifen(self, srv) -> None:
        server, reg = srv
        item = reg.create(name="Anel", kind="exclusiva",
                          engraved_code="NV-ABI-7F3A")
        sem_hifen = item["public_id"].replace("-", "")
        status, body, _ = _request(server.bound_port, "GET",
                                   "/registry/" + sem_hifen)
        data = _json_response((status, body, None))
        assert status == 200 and data["peca"]["public_id"] == item["public_id"]
        status, _, _ = _request(server.bound_port, "GET", "/registry/nvabi7f3a")
        assert status == 200
        # com espaços na URL (percent-encoded: %20) também acha
        status, _, _ = _request(server.bound_port, "GET", "/registry/nv%20abi%207f3a")
        assert status == 200

    def test_inexistente_continua_404(self, srv) -> None:
        server, _ = srv
        status, _, _ = _request(server.bound_port, "GET",
                                "/registry/odprod99999999")
        assert status == 404


class TestFoto:
    JPEGSINO = b"\xff\xd8\xff\xe0OD-TESTE-DE-FOTO\xff\xd9"

    @pytest.fixture()
    def srv_foto(self, serve, tmp_path: Path):
        from integrations.api import APIConfig

        db = Database(tmp_path / "foto.db")
        reg = RegistryStore(db, photo_dir=tmp_path / "fotos")
        cfg = APIConfig(port=0, rate_limit_max=0, api_key="segredo123",
                        auth_all=True, registry=reg)
        return serve(None, config=cfg), reg, tmp_path / "fotos"

    def test_store_salva_e_projeta_url(self, tmp_path: Path) -> None:
        reg = RegistryStore(Database(tmp_path / "f.db"),
                            photo_dir=tmp_path / "fotos")
        item = reg.create(name="Anel", kind="exclusiva")
        # sem foto: payload traz None
        assert reg.verify_public(item["public_id"])["photo"] is None
        reg.save_photo(item["public_id"], self.JPEGSINO, "image/jpeg")
        pub = reg.verify_public(item["public_id"])
        assert pub["photo"] == f"/registry/{item['public_id']}/photo"
        # nunca vaza o nome do arquivo
        assert "JPEGSINO" not in str(pub) and ".jpg" not in str(pub["photo"])
        assert reg.photo_path(item["public_id"]).read_bytes() == self.JPEGSINO

    def test_store_rejeita_formato_e_tamanho(self, tmp_path: Path) -> None:
        from core.registry import PHOTO_MAX_BYTES

        reg = RegistryStore(Database(tmp_path / "f.db"),
                            photo_dir=tmp_path / "fotos")
        item = reg.create(name="A", kind="publica")
        with pytest.raises(ValueError, match="formato_invalido"):
            reg.save_photo(item["public_id"], b"x", "image/gif")
        with pytest.raises(ValueError, match="foto_grande_demais"):
            reg.save_photo(item["public_id"], b"x" * (PHOTO_MAX_BYTES + 1),
                           "image/jpeg")
        with pytest.raises(ValueError, match="peca_inexistente"):
            reg.save_photo("OD-PROD-1999-9999", b"x", "image/jpeg")

    def test_upload_publico_e_servida(self, srv_foto) -> None:
        import base64 as b64

        server, reg, _ = srv_foto
        item = reg.create(name="Anel", kind="exclusiva")
        payload = json.dumps({
            "image_b64": b64.b64encode(self.JPEGSINO).decode(),
            "mime": "image/jpeg",
        })
        status, body, _ = _request(
            server.bound_port, "POST",
            f"/admin/registry/{item['public_id']}/photo",
            api_key="segredo123", raw_body=payload)
        assert status == 200, body
        # pública SEM credencial devolve os bytes com o mime certo
        status, body, headers = _request(
            server.bound_port, "GET", f"/registry/{item['public_id']}/photo")
        assert status == 200 and body == self.JPEGSINO
        assert headers.get("Content-Type") == "image/jpeg"
        # payload público traz a URL
        status, body, _ = _request(server.bound_port, "GET",
                                   "/registry/" + item["public_id"])
        assert _json_response((status, body, None))["peca"]["photo"].endswith(
            "/photo")

    def test_sem_foto_404_e_upload_exige_admin(self, srv_foto) -> None:
        server, reg, _ = srv_foto
        item = reg.create(name="A", kind="publica")
        status, _, _ = _request(server.bound_port, "GET",
                                f"/registry/{item['public_id']}/photo")
        assert status == 404
        # sem credencial (auth_all) = 401, não 403/200
        status, _, _ = _request(
            server.bound_port, "POST",
            f"/admin/registry/{item['public_id']}/photo",
            raw_body=json.dumps({"image_b64": "AA==", "mime": "image/jpeg"}))
        assert status == 401

    def test_delete_peca_remove_foto(self, srv_foto) -> None:
        server, reg, fotos = srv_foto
        import base64 as b64

        item = reg.create(name="A", kind="publica")
        _request(server.bound_port, "POST",
                 f"/admin/registry/{item['public_id']}/photo",
                 api_key="segredo123",
                 raw_body=json.dumps({
                     "image_b64": b64.b64encode(self.JPEGSINO).decode(),
                     "mime": "image/jpeg"}))
        assert (fotos / f"{item['public_id']}.jpg").is_file()
        _request(server.bound_port, "DELETE",
                 "/admin/registry/" + item["public_id"],
                 api_key="segredo123")
        assert not (fotos / f"{item['public_id']}.jpg").exists()


class TestSalaDeBatePapo:
    @pytest.fixture()
    def srv_chat(self, serve, tmp_path: Path):
        from integrations.api import APIConfig
        from integrations.api.auth import UserStore

        db = Database(tmp_path / "chat.db")
        reg = RegistryStore(db, photo_dir=tmp_path / "fotos")
        users = UserStore(db)
        users.register("bia", "bia@x.com", "senha-forte-123")
        cfg = APIConfig(port=0, rate_limit_max=0, api_key="segredo123",
                        auth_all=True, registry=reg, user_store=users,
                        owner_username="dono")
        srv = serve(None, config=cfg)
        chave_bia = users.get_user_by_username("bia").api_key
        return srv, reg, chave_bia

    def test_store_fluxo_completo(self, store: RegistryStore) -> None:
        item = store.create(name="A", kind="exclusiva")
        m1 = store.chat_post(item["public_id"], "bia", "qual a qualidade?")
        m2 = store.chat_post(item["public_id"], "dono", "japonesa, 925.")
        msgs = store.chat_messages(item["public_id"])
        assert [m["text"] for m in msgs] == ["qual a qualidade?", m2["text"]]
        # polling por id
        so_novas = store.chat_messages(item["public_id"], since_id=m1["id"])
        assert len(so_novas) == 1
        assert store.chat_messages("OD-PROD-1999-9999") is None
        assert store.chat_delete(item["public_id"], m1["id"]) is True
        assert len(store.chat_messages(item["public_id"])) == 1

    def test_limites_do_store(self, store: RegistryStore) -> None:
        from core.registry import CHAT_TEXT_MAX

        item = store.create(name="A", kind="exclusiva")
        with pytest.raises(ValueError, match="peca_inexistente"):
            store.chat_post("OD-PROD-1999-9999", "bia", "oi")
        with pytest.raises(ValueError, match="texto_vazio"):
            store.chat_post(item["public_id"], "bia", "   ")
        with pytest.raises(ValueError, match="texto_longo"):
            store.chat_post(item["public_id"], "bia", "x" * (CHAT_TEXT_MAX + 1))

    def test_leitura_publica_escrita_com_conta(self, srv_chat) -> None:
        server, reg, chave_bia = srv_chat
        item = reg.create(name="Anel", kind="exclusiva")
        # leitura pública (auth_all, SEM credencial)
        status, body, _ = _request(server.bound_port, "GET",
                                   f"/registry/{item['public_id']}/chat")
        data = _json_response((status, body, None))
        assert status == 200 and data["mensagens"] == []
        # escrita SEM conta = 401
        status, _, _ = _request(server.bound_port, "POST",
                                f"/registry/{item['public_id']}/chat",
                                raw_body=json.dumps({"text": "oi"}))
        assert status == 401
        # escrita COM conta da bia = 201 e o username assina
        status, body, _ = _request(
            server.bound_port, "POST",
            f"/registry/{item['public_id']}/chat",
            api_key=chave_bia, raw_body=json.dumps({"text": "ainda tem?"}))
        assert status == 201, body
        msg = _json_response((status, body, None))["mensagem"]
        assert msg["username"] == "bia"
        # aparece na leitura pública com polling since
        status, body, _ = _request(
            server.bound_port, "GET",
            f"/registry/{item['public_id']}/chat?since={msg['id'] - 1}")
        data = _json_response((status, body, None))
        assert len(data["mensagens"]) == 1

    def test_peca_inexistente_404(self, srv_chat) -> None:
        server, _, chave_bia = srv_chat
        status, _, _ = _request(server.bound_port, "GET",
                                "/registry/OD-PROD-1999-9999/chat")
        assert status == 404
        status, _, _ = _request(server.bound_port, "POST",
                                "/registry/OD-PROD-1999-9999/chat",
                                api_key=chave_bia,
                                raw_body=json.dumps({"text": "oi"}))
        assert status == 404

    def test_moderacao_admin(self, srv_chat) -> None:
        server, reg, chave_bia = srv_chat
        item = reg.create(name="A", kind="exclusiva")
        status, body, _ = _request(
            server.bound_port, "POST",
            f"/registry/{item['public_id']}/chat",
            api_key=chave_bia, raw_body=json.dumps({"text": "spam?"}))
        mid = _json_response((status, body, None))["mensagem"]["id"]
        # usuário comum NÃO modera (chave de usuário não é admin)
        status, _, _ = _request(
            server.bound_port, "DELETE",
            f"/admin/registry/{item['public_id']}/chat/{mid}",
            api_key=chave_bia)
        assert status == 403
        # dono modera
        status, _, _ = _request(
            server.bound_port, "DELETE",
            f"/admin/registry/{item['public_id']}/chat/{mid}",
            api_key="segredo123")
        assert status == 200
        status, _, _ = _request(
            server.bound_port, "DELETE",
            f"/admin/registry/{item['public_id']}/chat/{mid}",
            api_key="segredo123")
        assert status == 404

    def test_aviso_ao_dono_com_cooldown(self, srv_chat) -> None:
        """chat_notify dispara 1x por peça em 2 min; erro nunca derruba."""
        server, reg, chave_bia = srv_chat
        server.config.chat_notify = lambda texto: None  # plugado
        item = reg.create(name="A", kind="exclusiva")
        chamadas = []
        server.config.chat_notify = lambda t: chamadas.append(t)
        for i in range(3):
            _request(server.bound_port, "POST",
                     f"/registry/{item['public_id']}/chat",
                     api_key=chave_bia,
                     raw_body=json.dumps({"text": f"msg {i}"}))
        assert len(chamadas) == 1  # cooldown de 2 min por peça
        assert item["public_id"] in chamadas[0]
        # peça diferente avisa à parte
        outro = reg.create(name="B", kind="exclusiva")
        _request(server.bound_port, "POST",
                 f"/registry/{outro['public_id']}/chat",
                 api_key=chave_bia, raw_body=json.dumps({"text": "oi"}))
        assert len(chamadas) == 2


# ---------------------------------------------------------------------------#
# 1.24.0 — desfazer venda (vendida → estoque) + bloqueio de regressão          #
#          de registro (pendente do código secreto da peça)                    #
# ---------------------------------------------------------------------------#
class TestDesfazerVenda:
    def test_store_desfaz_venda_e_apaga_carimbo(self, store: RegistryStore) -> None:
        item = store.create(name="Anel", kind="exclusiva")
        vendida = store.update(item["public_id"], status="vendida")
        assert vendida["status"] == "vendida" and vendida["sold_at"]
        # desfeita: volta ao estoque e o carimbo some
        volta = store.update(item["public_id"], status="estoque")
        assert volta["status"] == "estoque"
        assert volta["sold_at"] is None
        assert volta["registered_at"] is None
        # a projeção pública também volta a dizer "sem dono"
        pub = store.verify_public(item["public_id"])
        assert pub["status"] == "estoque" and not pub["registered"]

    def test_rota_admin_desfaz_venda(self, serve, tmp_path: Path) -> None:
        from integrations.api import APIConfig

        db = Database(tmp_path / "d.db")
        reg = RegistryStore(db, photo_dir=tmp_path / "fotos")
        cfg = APIConfig(port=0, rate_limit_max=0, api_key="segredo123",
                        registry=reg)
        server = serve(None, config=cfg)
        item = reg.create(name="A", kind="exclusiva")
        reg.update(item["public_id"], status="vendida")
        status, body, _ = _request(
            server.bound_port, "PUT",
            "/admin/registry/" + item["public_id"],
            api_key="segredo123",
            raw_body=json.dumps({"status": "estoque"}))
        data = _json_response((status, body, None))
        assert status == 200 and data["peca"]["status"] == "estoque"
        assert data["peca"]["sold_at"] is None

    def test_registrada_nao_regride_sem_codigo_secreto(
        self, store: RegistryStore
    ) -> None:
        """Posse registrada só cai com o código exclusivo da peça (futuro)."""
        item = store.create(name="A", kind="exclusiva")
        store.update(item["public_id"], status="vendida")
        store.update(item["public_id"], status="registrada",
                     owner_username="bia")
        for alvo in ("estoque", "vendida"):
            with pytest.raises(ValueError, match="codigo_secreto"):
                store.update(item["public_id"], status=alvo)
        # e continua registrada, sem dano
        assert store.get(item["public_id"])["status"] == "registrada"

    def test_painel_tem_botao_desfazer(self, serve) -> None:
        from integrations.api import APIConfig

        cfg = APIConfig(port=0, rate_limit_max=0, api_key="segredo123")
        srv = serve(None, config=cfg)
        status, body, _ = _request(srv.bound_port, "GET", "/admin")
        html = body.decode("utf-8", "replace")
        assert status == 200
        assert "reg-desfazer" in html and "regDesfazer" in html


# ---------------------------------------------------------------------------#
# Etapa 4 — Posse por QR/código (2026-10-15): DECISÃO FINAL a–e              #
# ---------------------------------------------------------------------------#
class TestPosseStore:
    """Núcleo: gerar/registrar posse + regressão destravada pelo código."""

    def test_gerar_posse_formato_e_hash(self, store: RegistryStore) -> None:
        item = store.create(name="Anel", kind="exclusiva")
        g = store.gerar_posse(item["public_id"])
        cod = g["codigo_posse"]
        # POSSE-XXXX-XXXX-XXXX-XXXX — 4 grupos de 4 hex (64 bits de secrets)
        partes = cod.split("-")
        assert partes[0] == "POSSE" and len(partes) == 5
        assert all(len(p) == 4 for p in partes[1:])
        assert g["regenerado"] is False
        # o banco guarda SÓ o hash sha256 (64 hex) — nunca o código
        bruto = store.get(item["public_id"])["posse_code_hash"]
        assert bruto and len(bruto) == 64 and cod not in bruto

    def test_regenerar_invalida_o_anterior(self, store: RegistryStore) -> None:
        item = store.create(name="Anel", kind="exclusiva")
        g1 = store.gerar_posse(item["public_id"])
        g2 = store.gerar_posse(item["public_id"])
        assert g2["regenerado"] is True
        assert g2["codigo_posse"] != g1["codigo_posse"]
        # só o NOVO registra (o cartão antigo perde a força na hora)
        pub = store.registrar_posse(g2["codigo_posse"], "bia")
        assert pub["status"] == "registrada"
        assert pub["owner_username"] == "bia"

    def test_registrar_normaliza_e_estoque_ou_vendida(
        self, store: RegistryStore
    ) -> None:
        item = store.create(name="Anel", kind="exclusiva")
        g = store.gerar_posse(item["public_id"])
        # minúsculo e sem hífen = mesma prova (normalização do servidor)
        pub = store.registrar_posse(
            g["codigo_posse"].lower().replace("-", ""), "bia"
        )
        assert pub["status"] == "registrada" and pub["registered"]
        # vendida → registrada também: a peça está na mão do comprador
        item2 = store.create(name="Colar", kind="exclusiva")
        g2 = store.gerar_posse(item2["public_id"])
        store.update(item2["public_id"], status="vendida")
        pub2 = store.registrar_posse(g2["codigo_posse"], "bia")
        assert pub2["status"] == "registrada"

    def test_erros_uniformes_sem_oraculo(self, store: RegistryStore) -> None:
        item = store.create(name="Anel", kind="exclusiva")
        g = store.gerar_posse(item["public_id"])
        # chute e lixo = MESMA resposta (sem oráculo de "quase")
        for erro_certo, codigo in (
            ("posse_invalida", "POSSE-0000-0000-0000-0000"),
            ("posse_invalida", "qualquercoisa"),
            ("posse_invalida", ""),
        ):
            with pytest.raises(ValueError, match=erro_certo):
                store.registrar_posse(codigo, "bia")
        # username vazio morre ANTES (conta é obrigatória)
        with pytest.raises(ValueError, match="username_obrigatorio"):
            store.registrar_posse(g["codigo_posse"], "   ")
        store.registrar_posse(g["codigo_posse"], "bia")
        with pytest.raises(ValueError, match="ja_registrada"):
            store.registrar_posse(g["codigo_posse"], "outro")

    def test_publica_nao_tem_posse(self, store: RegistryStore) -> None:
        pub = store.create(name="Chaveiro", kind="publica")
        with pytest.raises(ValueError, match="publica_sem_posse"):
            store.gerar_posse(pub["public_id"])
        with pytest.raises(ValueError, match="peca_inexistente"):
            store.gerar_posse("OD-PROD-1999-9999")

    def test_hash_fora_da_projecao_publica(self, store: RegistryStore) -> None:
        item = store.create(name="Anel", kind="exclusiva")
        store.gerar_posse(item["public_id"])
        pub = store.verify_public(item["public_id"])
        assert "posse_code_hash" not in pub
        assert "price_brl" not in pub and "notes" not in pub

    def test_regressao_somente_com_o_codigo(self, store: RegistryStore) -> None:
        item = store.create(name="Anel", kind="exclusiva")
        g = store.gerar_posse(item["public_id"])
        store.registrar_posse(g["codigo_posse"], "bia")
        # sem código → o bloco da etapa 1 continua valendo
        with pytest.raises(ValueError, match="registro_pendente_codigo_secreto"):
            store.update(item["public_id"], status="vendida")
        # código errado → idem
        with pytest.raises(ValueError, match="registro_pendente_codigo_secreto"):
            store.update(item["public_id"], status="vendida",
                         posse_code="POSSE-0000-0000-0000-0000")
        # código certo → desfaz e limpa dono/carimbos junto
        volta = store.update(item["public_id"], status="vendida",
                             posse_code=g["codigo_posse"])
        assert volta["status"] == "vendida"
        assert volta["owner_username"] is None
        assert volta["registered_at"] is None
        # público volta a esconder dono
        pub = store.verify_public(item["public_id"])
        assert not pub["registered"]


class TestPosseRotas:
    """Rotas: lista pública da loja, registro do comprador, QR do dono."""

    @pytest.fixture()
    def srv_posse(self, serve, tmp_path: Path):
        from integrations.api import APIConfig
        from integrations.api.auth import UserStore

        db = Database(tmp_path / "posse.db")
        reg = RegistryStore(db)
        users = UserStore(db)
        users.register("bia", "bia@x.com", "senha-forte-123")
        cfg = APIConfig(port=0, rate_limit_max=0, api_key="segredo123",
                        auth_all=True, registry=reg, user_store=users,
                        owner_username="dono")
        srv = serve(None, config=cfg)
        chave = users.get_user_by_username("bia").api_key
        return srv, reg, chave

    def test_lista_publica_da_loja_sem_preco_nem_hash(self, srv_posse) -> None:
        srv, reg, _chave = srv_posse
        excl = reg.create(name="Anel", kind="exclusiva",
                          collection="ABISSAL", price_brl=120.0)
        publ = reg.create(name="Chaveiro", kind="publica")
        reg.gerar_posse(excl["public_id"])
        # público SEM credencial (auth_all) — /registry isenta de auth
        status, body, _ = _request(srv.bound_port, "GET", "/registry")
        data = _json_response((status, body, None))
        assert status == 200 and data["ok"] and data["total"] == 2
        texto = body.decode()
        assert "price_brl" not in texto and "posse_code_hash" not in texto
        ids = {p["public_id"] for p in data["pecas"]}
        assert {excl["public_id"], publ["public_id"]} == ids

    def test_posse_exige_conta(self, srv_posse) -> None:
        srv, _reg, _chave = srv_posse
        status, _body, _ = _request(
            srv.bound_port, "POST", "/registry/posse",
            raw_body=json.dumps(
                {"codigo_posse": "POSSE-0000-0000-0000-0000"}))
        assert status == 401

    def test_comprador_registra_com_conta(self, srv_posse) -> None:
        srv, reg, chave = srv_posse
        item = reg.create(name="Anel", kind="exclusiva")
        g = reg.gerar_posse(item["public_id"])
        # sucesso: 201 + peça registrada no username de quem tem conta
        status, body, _ = _request(srv.bound_port, "POST", "/registry/posse",
                                   api_key=chave,
                                   body={"codigo_posse": g["codigo_posse"]})
        data = _json_response((status, body, None))
        assert status == 201 and data["ok"]
        assert data["peca"]["status"] == "registrada"
        assert data["peca"]["owner_username"] == "bia"
        assert "price_brl" not in data["peca"]
        # de novo → 409 (sai só pelo código no update do admin)
        status2, _, _ = _request(srv.bound_port, "POST", "/registry/posse",
                                 api_key=chave,
                                 body={"codigo_posse": g["codigo_posse"]})
        assert status2 == 409
        # chute → 400 com a MESMA resposta de lixo
        status3, body3, _ = _request(
            srv.bound_port, "POST", "/registry/posse", api_key=chave,
            body={"codigo_posse": "POSSE-0000-0000-0000-0000"})
        assert status3 == 400
        assert _json_response(
            (status3, body3, None))["error"] == "posse_invalida"

    def test_qr_admin_so_com_codigo_valido(self, srv_posse) -> None:
        srv, reg, _chave = srv_posse
        item = reg.create(name="Anel", kind="exclusiva")
        # ainda sem código → QR não tem o que renderizar (400)
        status, _, _ = _request(
            srv.bound_port, "GET",
            f"/admin/registry/{item['public_id']}/posse/qr",
            api_key="segredo123")
        assert status == 400
        # gera o código (201 com código + URL absoluta do QR)
        status, body, _ = _request(
            srv.bound_port, "POST",
            f"/admin/registry/{item['public_id']}/posse",
            api_key="segredo123")
        data = _json_response((status, body, None))
        assert status == 201 and data["codigo_posse"].startswith("POSSE-")
        assert data["regenerado"] is False
        assert data["url"].endswith("?posse=" + data["codigo_posse"])
        # QR com o código certo → SVG
        status, svg, hdrs = _request(
            srv.bound_port, "GET",
            f"/admin/registry/{item['public_id']}/posse/qr"
            f"?codigo={data['codigo_posse']}",
            api_key="segredo123")
        assert status == 200
        assert hdrs.get("Content-Type", "").startswith("image/svg+xml")
        assert b"<svg" in svg and b"<path" in svg
        # QR com código errado → 400 (não vaza QR de peça alheia)
        status2, _, _ = _request(
            srv.bound_port, "GET",
            f"/admin/registry/{item['public_id']}/posse/qr"
            "?codigo=POSSE-0000-0000-0000-0000",
            api_key="segredo123")
        assert status2 == 400

    def test_posse_admin_negado_e_publica_sem_qr(self, srv_posse) -> None:
        srv, reg, chave = srv_posse
        item = reg.create(name="Anel", kind="exclusiva")
        # usuário comum não emite código de posse (admin only)
        status, _, _ = _request(
            srv.bound_port, "POST",
            f"/admin/registry/{item['public_id']}/posse", api_key=chave)
        assert status == 403
        # peça pública = linha sem dono → 400 publica_sem_posse
        publ = reg.create(name="Chaveiro", kind="publica")
        status, body, _ = _request(
            srv.bound_port, "POST",
            f"/admin/registry/{publ['public_id']}/posse",
            api_key="segredo123")
        assert status == 400
        assert _json_response((status, body, None))["error"] == "publica_sem_posse"

    def test_lista_admin_vira_tem_posse_sem_hash(self, srv_posse) -> None:
        srv, reg, _chave = srv_posse
        item = reg.create(name="Anel", kind="exclusiva")
        status, body, _ = _request(srv.bound_port, "GET", "/admin/registry",
                                   api_key="segredo123")
        data = _json_response((status, body, None))
        assert data["pecas"][0]["tem_posse"] is False
        assert "posse_code_hash" not in body.decode()  # hash é interno
        reg.gerar_posse(item["public_id"])
        status, body, _ = _request(srv.bound_port, "GET", "/admin/registry",
                                   api_key="segredo123")
        data = _json_response((status, body, None))
        assert data["pecas"][0]["tem_posse"] is True
        assert "posse_code_hash" not in body.decode()

    def test_regressao_admin_somente_com_posse_code(self, srv_posse) -> None:
        srv, reg, _chave = srv_posse
        item = reg.create(name="Anel", kind="exclusiva")
        g = reg.gerar_posse(item["public_id"])
        reg.registrar_posse(g["codigo_posse"], "bia")
        # sem prova secreta → 400 com o erro da etapa 1
        status, body, _ = _request(
            srv.bound_port, "PUT", "/admin/registry/" + item["public_id"],
            api_key="segredo123",
            raw_body=json.dumps({"status": "vendida"}))
        assert status == 400
        assert _json_response(
            (status, body, None))["error"] == "registro_pendente_codigo_secreto"
        # com o código → desfaz, dono limpo, hash continua (tem_posse)
        status, body, _ = _request(
            srv.bound_port, "PUT", "/admin/registry/" + item["public_id"],
            api_key="segredo123",
            raw_body=json.dumps({"status": "vendida",
                                 "posse_code": g["codigo_posse"]}))
        data = _json_response((status, body, None))
        assert status == 200 and data["peca"]["status"] == "vendida"
        assert data["peca"]["owner_username"] is None
        assert data["peca"]["tem_posse"] is True
        assert "posse_code_hash" not in data["peca"]

    def test_painel_tem_botoes_de_posse(self, serve) -> None:
        from integrations.api import APIConfig

        cfg = APIConfig(port=0, rate_limit_max=0, api_key="segredo123")
        srv = serve(None, config=cfg)
        status, body, _ = _request(srv.bound_port, "GET", "/admin")
        html = body.decode("utf-8", "replace")
        assert status == 200
        # 🧾 QR gera o código; ↩ Registro desfaz com a prova secreta
        assert "reg-posse" in html and "regPosse" in html
        assert "reg-desreg" in html and "regDesreg" in html


# ---------------------------------------------------------------------------#
# Frente NV — COLEÇÕES COM CICLO FECHADO (16/10)                              #
# ---------------------------------------------------------------------------#
class TestColecoesCicloFechado:
    """Regra do PROTOCOLO_NV.md (Legado): "Coleções são ciclos fechados.
    Uma vez Encerrada, nunca é reeditada" — imutável por desenho: existe
    criar e encerrar, nunca reabrir/renomear/apagar."""

    def test_criar_normaliza_e_lista(self, store: RegistryStore) -> None:
        col = store.criar_colecao(" abissal ")  # normaliza p/ maiúsculas
        assert col["name"] == "ABISSAL" and col["closed_at"] is None
        assert store.get_colecao("ABISSAL")["name"] == "ABISSAL"
        lista = store.listar_colecoes()
        assert [c["name"] for c in lista] == ["ABISSAL"]
        assert lista[0]["aberta"] is True and lista[0]["pecas"] == 0

    def test_criar_duplicada_erro(self, store: RegistryStore) -> None:
        store.criar_colecao("ABISSAL")
        with pytest.raises(ValueError, match="colecao_ja_existe"):
            store.criar_colecao("abissal")

    def test_nome_invalido_erro(self, store: RegistryStore) -> None:
        for nome in ("", "ab", "x" * 41, "AB@ISSAL", "  ", "AB ISSAL!"):
            with pytest.raises(ValueError, match="colecao_nome_invalido"):
                store.criar_colecao(nome)

    def test_encerrar_e_nunca_reabre(self, store: RegistryStore) -> None:
        store.criar_colecao("ABISSAL")
        col = store.encerrar_colecao("abissal")
        assert col["closed_at"] is not None
        assert store.colecao_de_peca("ABISSAL") == "encerrada"
        # segunda vez = erro (não existe "reeditar" o ciclo)
        with pytest.raises(ValueError, match="colecao_ja_encerrada"):
            store.encerrar_colecao("ABISSAL")
        # e não existe método de reabrir: a imutabilidade é por desenho
        assert not hasattr(store, "reabrir_colecao")
        assert not hasattr(store, "apagar_colecao")

    def test_encerrar_inexistente_erro(self, store: RegistryStore) -> None:
        with pytest.raises(ValueError, match="colecao_inexistente"):
            store.encerrar_colecao("FANTASMA")  # nome válido, ciclo inexistente

    def test_peca_nv_exige_colecao_aberta(self, store: RegistryStore) -> None:
        # sem coleção → erro
        with pytest.raises(ValueError, match="colecao_obrigatoria_nv"):
            store.create(name="Anel", kind="exclusiva", frente="NV", tipo="SJ")
        # coleção inexistente → erro
        with pytest.raises(ValueError, match="colecao_ausente"):
            store.create(name="Anel", kind="exclusiva", frente="NV", tipo="SJ",
                         collection="fantasma")
        # ciclo encerrado → peça NÃO entra
        store.criar_colecao("ABISSAL")
        store.encerrar_colecao("ABISSAL")
        with pytest.raises(ValueError, match="colecao_encerrada"):
            store.create(name="Anel", kind="exclusiva", frente="NV", tipo="SJ",
                         collection="ABISSAL")
        # trocar para ciclo aberto → entra
        store.criar_colecao("DRAKONIS")
        item = store.create(name="Anel", kind="exclusiva", frente="NV", tipo="SJ",
                            collection="drakonis")
        assert item["public_id"].startswith("NV-SJ-")
        # aberta vem primeiro na listagem: DRAKONIS é [0] e conta a peça
        assert store.listar_colecoes()[0]["pecas"] == 1

    def test_peca_prod_colecao_livre(self, store: RegistryStore) -> None:
        # frente não-NV: coleção continua texto livre (sem virar entidade)
        item = store.create(name="Quadro", kind="publica", collection="quadros")
        assert item["collection"] == "QUADROS"
        assert store.get_colecao("QUADROS") is None  # livre ≠ entidade
        # mas ciclo ENCERRADO não recebe peça nova, seja de que linha for
        store.criar_colecao("ABISSAL")
        store.encerrar_colecao("ABISSAL")
        with pytest.raises(ValueError, match="colecao_encerrada"):
            store.create(name="Anel", kind="publica", collection="ABISSAL")

    def test_update_respeita_ciclo(self, store: RegistryStore) -> None:
        store.criar_colecao("ABISSAL")
        store.criar_colecao("DRAKONIS")
        store.criar_colecao("COBRA")   # ciclo aberto "de fuga" p/ o teste final
        item = store.create(name="Anel", kind="exclusiva", frente="NV", tipo="SJ",
                            collection="ABISSAL")
        # trocar para ciclo encerrado → erro
        store.encerrar_colecao("DRAKONIS")
        with pytest.raises(ValueError, match="colecao_encerrada"):
            store.update(item["public_id"], collection="DRAKONIS")
        # trocar para ciclo inexistente → erro (NV exige entidade)
        with pytest.raises(ValueError, match="colecao_ausente"):
            store.update(item["public_id"], collection="FANTASMA")
        # limpar a coleção de peça NV → erro (NV sempre tem ciclo)
        with pytest.raises(ValueError, match="colecao_obrigatoria_nv"):
            store.update(item["public_id"], collection=None)
        # trocar para ciclo aberto → ok, e o valor gravado é o testado
        got = store.update(item["public_id"], collection=" abissal ")
        assert got["collection"] == "ABISSAL"
        # peça DENTRO de ciclo encerrado não sai (histórico intocado) —
        # nem para um ciclo ABERTO: a escassez fica registrada na peça
        store.encerrar_colecao("ABISSAL")
        with pytest.raises(ValueError, match="peca_em_ciclo_encerrado"):
            store.update(item["public_id"], collection="COBRA")
        # preço/status continuam livres dentro de ciclo encerrado
        assert store.update(item["public_id"], price_brl=90.0)["price_brl"] == 90.0

    def test_verify_public_mostra_ciclo(self, store: RegistryStore) -> None:
        store.criar_colecao("ABISSAL")
        item = store.create(name="Anel", kind="exclusiva", frente="NV", tipo="SJ",
                            collection="ABISSAL")
        assert store.verify_public(item["public_id"])["collection_status"] \
            == "aberta"
        store.encerrar_colecao("ABISSAL")
        assert store.verify_public(item["public_id"])["collection_status"] \
            == "encerrada"
        # peça PROD com coleção que nunca virou entidade: None (sem mentira)
        prod = store.create(name="Quadro", kind="publica", collection="quadros")
        assert store.verify_public(prod["public_id"])["collection_status"] is None

    def test_listar_abertas_primeiro_com_contagem(self,
                                                  store: RegistryStore) -> None:
        store.criar_colecao("ZEDONA")   # criada primeiro, depois encerrada
        store.criar_colecao("ATIVA")
        store.encerrar_colecao("ZEDONA")
        item = store.create(name="Anel", kind="exclusiva", frente="NV", tipo="SJ",
                            collection="ATIVA")
        assert item  # só para clareza: a peça existe
        lista = store.listar_colecoes()
        assert [c["name"] for c in lista] == ["ATIVA", "ZEDONA"]  # aberta 1º
        assert lista[0]["pecas"] == 1 and lista[1]["pecas"] == 0

    def test_migracao_colecoes_de_pecas_idempotente(self,
                                                    store: RegistryStore) -> None:
        # linha crua: peça NV legada com coleção que ainda não é entidade
        store._db.execute(
            "INSERT INTO registry_items (public_id, engraved_code, name, "
            "collection, kind, status, created_at) VALUES "
            "('NV-SJ-2026-0009','NV-ABI-1111','Anel','ABISSAL','exclusiva',"
            "'estoque',1.0)"
        )
        criadas = store.criar_colecoes_de_pecas()
        assert criadas == ["ABISSAL"]
        assert store.colecao_de_peca("ABISSAL") == "aberta"
        # idempotente: segunda rodada não cria nada
        assert store.criar_colecoes_de_pecas() == []


class TestColecoesRotas:
    """Rotas: GET público /registry/collections + admin (abrir/encerrar)."""

    def test_publica_sob_auth_all_sem_credencial(self, serve,
                                                 tmp_path: Path) -> None:
        from core.registry import RegistryStore as RS
        from storage import Database as DB
        from integrations.api import APIConfig

        db = DB(tmp_path / "pub.db")
        reg = RS(db)
        reg.criar_colecao("ABISSAL")
        reg.criar_colecao("DRAKONIS")
        reg.encerrar_colecao("DRAKONIS")
        cfg = APIConfig(port=0, rate_limit_max=0, api_key="segredo123",
                        auth_all=True, registry=reg)
        srv = serve(None, config=cfg)
        status, body, _ = _request(srv.bound_port, "GET",
                                   "/registry/collections")
        data = _json_response((status, body, None))
        assert status == 200 and data["ok"] is True
        assert data["total"] == 2
        assert data["colecoes"][0]["name"] == "ABISSAL"
        assert data["colecoes"][0]["ciclo"] == "aberta"
        assert data["colecoes"][1]["ciclo"] == "encerrada"
        # projeção pública: sem campos privados (nada de "notes"/hash)
        assert "notes" not in data["colecoes"][0]

    def test_nao_engolido_por_codigo(self, srv) -> None:
        """A rota fixa vem ANTES de /{codigo} — 'collections' não vira ID."""
        server, _ = srv
        status, body, _ = _request(server.bound_port, "GET",
                                   "/registry/collections")
        assert status == 200  # e não 404 "nao_encontrada"
        data = _json_response((status, body, None))
        assert data["colecoes"] == []

    def test_admin_abre_e_encerra(self, srv) -> None:
        server, _ = srv
        # abre (dono: api_key)
        status, body, _ = _request(server.bound_port, "POST",
                                   "/admin/registry/collections",
                                   api_key="segredo123",
                                   raw_body='{"name":"ABISSAL"}')
        assert status == 201, body
        assert _json_response((status, body, None))["colecao"]["ciclo"] \
            == "aberta"
        # duplicada → 400
        status, body, _ = _request(server.bound_port, "POST",
                                   "/admin/registry/collections",
                                   api_key="segredo123",
                                   raw_body='{"name":"abissal"}')
        assert status == 400
        assert _json_response((status, body, None))["error"] \
            == "colecao_ja_existe"
        # encerra → 200
        status, body, _ = _request(server.bound_port, "POST",
                                   "/admin/registry/collections/ABISSAL/encerrar",
                                   api_key="segredo123")
        assert status == 200
        assert _json_response((status, body, None))["colecao"]["ciclo"] \
            == "encerrada"
        # re-encerrar → 400 (nunca reeditada)
        status, body, _ = _request(server.bound_port, "POST",
                                   "/admin/registry/collections/ABISSAL/encerrar",
                                   api_key="segredo123")
        assert status == 400
        assert _json_response((status, body, None))["error"] \
            == "colecao_ja_encerrada"
        # encerrar inexistente → 404
        status, body, _ = _request(server.bound_port, "POST",
                                   "/admin/registry/collections/FANTASMA/encerrar",
                                   api_key="segredo123")
        assert status == 404

    def test_admin_sem_chave_negado(self, srv) -> None:
        server, _ = srv
        status, body, _ = _request(server.bound_port, "POST",
                                   "/admin/registry/collections",
                                   raw_body='{"name":"X"}')
        assert status in (401, 403)

    def test_peca_nv_pela_api_exige_ciclo_aberto(self, srv) -> None:
        server, _ = srv
        # sem coleção → 400
        status, body, _ = _request(server.bound_port, "POST", "/admin/registry",
                                   api_key="segredo123",
                                   raw_body='{"name":"Anel","kind":"exclusiva",'
                                            '"frente":"NV","tipo":"SJ"}')
        assert status == 400
        assert _json_response((status, body, None))["error"] \
            == "colecao_obrigatoria_nv"
        # abre o ciclo e cadastra → 201
        _request(server.bound_port, "POST", "/admin/registry/collections",
                 api_key="segredo123", raw_body='{"name":"ABISSAL"}')
        status, body, _ = _request(server.bound_port, "POST", "/admin/registry",
                                   api_key="segredo123",
                                   raw_body='{"name":"Anel","kind":"exclusiva",'
                                            '"frente":"NV","tipo":"SJ",'
                                            '"collection":"ABISSAL"}')
        assert status == 201, body
        # encerra o ciclo e tenta outra peça → 400
        _request(server.bound_port, "POST",
                 "/admin/registry/collections/ABISSAL/encerrar",
                 api_key="segredo123")
        status, body, _ = _request(server.bound_port, "POST", "/admin/registry",
                                   api_key="segredo123",
                                   raw_body='{"name":"Irmã","kind":"exclusiva",'
                                            '"frente":"NV","tipo":"SJ",'
                                            '"collection":"ABISSAL"}')
        assert status == 400
        assert _json_response((status, body, None))["error"] \
            == "colecao_encerrada"

    def test_painel_tem_ui_de_colecoes(self, serve) -> None:
        from integrations.api import APIConfig

        cfg = APIConfig(port=0, rate_limit_max=0, api_key="segredo123")
        srv = serve(None, config=cfg)
        status, body, _ = _request(srv.bound_port, "GET", "/admin")
        html = body.decode("utf-8", "replace")
        assert status == 200
        # abrir ciclo, encerrar (para sempre) e a lista
        assert "col-add" in html and "colLoad" in html
        assert "col-encerrar" in html and "colEncerrar" in html
        assert "nunca é reeditada" in html
