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
