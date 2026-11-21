"""
OMEGA DRAKON • TESTS
Módulo: tests/test_meta.py
Descrição: conexão com a Meta (WhatsApp Cloud API, 21/11) — verificação do
           webhook, assinatura X-Hub-Signature-256, leitura do payload,
           resposta pelo Graph API (sem rede: envio injetado) e as duas
           rotas reais no APIServer.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projetti
"""

from __future__ import annotations

import json

import pytest

from integrations import meta
from integrations.api import APIConfig, APIServer
from integrations.meta import (
    MensagemMeta,
    MetaConfig,
    assinar,
    assinatura_valida,
    config_do_ambiente,
    construir_handler,
    enviar_texto,
    extrair_mensagens,
    verificar,
)
from tests.test_api import _request, make_orch


def _cfg(**kwargs) -> MetaConfig:
    base = dict(
        token="tok", phone_id="123", verify_token="segredo", app_secret="shh"
    )
    base.update(kwargs)
    return MetaConfig(**base)


def _payload(texto: str = "oi", de: str = "5511999999999") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "waba",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "contacts": [{"wa_id": de, "profile": {"name": "Alex"}}],
                    "messages": [{
                        "from": de, "id": "wamid.X", "timestamp": "1",
                        "type": "text", "text": {"body": texto},
                    }],
                },
            }],
        }],
    }


class TestVerificacao:
    def test_challenge_com_token_certo(self) -> None:
        assert verificar("subscribe", "segredo", "abc", "segredo") == "abc"

    def test_token_errado(self) -> None:
        assert verificar("subscribe", "outro", "abc", "segredo") is None

    def test_modo_errado(self) -> None:
        assert verificar("unsubscribe", "segredo", "abc", "segredo") is None

    def test_sem_segredo_configurado_nao_passa(self) -> None:
        assert verificar("subscribe", "segredo", "abc", "") is None

    def test_token_vazio_nao_passa(self) -> None:
        assert verificar("subscribe", "", "abc", "") is None


class TestAssinatura:
    def test_assinatura_valida(self) -> None:
        corpo = b'{"a":1}'
        assert assinatura_valida(corpo, assinar(corpo, "shh"), "shh")

    def test_corpo_adulterado(self) -> None:
        cabecalho = assinar(b'{"a":1}', "shh")
        assert not assinatura_valida(b'{"a":2}', cabecalho, "shh")

    def test_sem_app_secret_fecha(self) -> None:
        corpo = b"{}"
        assert not assinatura_valida(corpo, assinar(corpo, "shh"), "")

    def test_cabecalho_ausente_ou_malformado(self) -> None:
        assert not assinatura_valida(b"{}", None, "shh")
        assert not assinatura_valida(b"{}", "md5=abc", "shh")
        assert not assinatura_valida(b"{}", "sha256=", "shh")


class TestPayload:
    def test_extrai_texto_e_nome(self) -> None:
        msgs = extrair_mensagens(_payload("olá"))
        assert msgs == [MensagemMeta(
            remetente="5511999999999", texto="olá", mid="wamid.X",
            nome="Alex", tipo="text",
        )]

    def test_status_sem_mensagens(self) -> None:
        payload = {"entry": [{"changes": [{"value": {"statuses": [{"id": "x"}]}}]}]}
        assert extrair_mensagens(payload) == []

    def test_payload_lixo_nao_quebra(self) -> None:
        assert extrair_mensagens({}) == []
        assert extrair_mensagens({"entry": "nada"}) == []

    def test_botao_conta_como_texto(self) -> None:
        payload = {"entry": [{"changes": [{"value": {"messages": [{
            "from": "55", "type": "button", "button": {"text": "sim"},
        }]}}]}]}
        assert extrair_mensagens(payload)[0].texto == "sim"


class TestEnvio:
    def test_sem_credencial_levanta(self) -> None:
        with pytest.raises(RuntimeError, match="meta_nao_configurada"):
            enviar_texto("55", "oi", MetaConfig())

    def test_quebra_texto_longo(self) -> None:
        partes = meta._dividir("x" * 9000)
        assert len(partes) == 3
        assert "".join(partes) == "x" * 9000


class TestHandler:
    def test_responde_pelo_orquestrador(self, tmp_path) -> None:
        enviados: list[tuple[str, str]] = []
        orch = make_orch(tmp_path)
        handler = construir_handler(
            orch, _cfg(perfil="guardian"),
            enviar=lambda para, texto, cfg: enviados.append((para, texto)) or 1,
        )
        resultado = handler(_payload("qual a capital?"))
        assert resultado["respondidas"] == 1
        assert enviados and enviados[0][0] == "5511999999999"
        assert enviados[0][1].strip()  # resposta não vazia

    def test_falha_de_envio_nao_derruba_lote(self, tmp_path) -> None:
        def _explode(*_a, **_k):
            raise RuntimeError("meta_http_500")

        handler = construir_handler(
            make_orch(tmp_path), _cfg(perfil="guardian"), enviar=_explode
        )
        resultado = handler(_payload("oi"))
        assert resultado["erros"] == 1 and resultado["respondidas"] == 0

    def test_mensagem_vazia_e_ignorada(self, tmp_path) -> None:
        handler = construir_handler(
            make_orch(tmp_path), _cfg(), enviar=lambda *a, **k: 1
        )
        assert handler(_payload(""))["respondidas"] == 0


class TestEnv:
    def test_config_do_ambiente(self) -> None:
        cfg = config_do_ambiente({
            "OD_META_TOKEN": "t", "OD_META_PHONE_ID": "9",
            "OD_META_VERIFY_TOKEN": "v", "OD_META_APP_SECRET": "s",
            "OD_META_ROLE": "user",
        })
        assert cfg.configurado() and cfg.role == "user"
        assert cfg.graph_version == "v21.0"

    def test_sem_credenciais_nao_esta_configurada(self) -> None:
        assert not config_do_ambiente({}).configurado()


@pytest.fixture()
def meta_server():
    servers: list[APIServer] = []
    cfg = APIConfig(
        port=0, rate_limit_max=0, auth_all=True,
        meta_verify_token="segredo", meta_app_secret="shh",
        meta=construir_handler(
            make_orch(__import__("pathlib").Path("/tmp")),
            _cfg(perfil="guardian"), enviar=lambda *a, **k: 1,
        ),
    )
    srv = APIServer(None, config=cfg)
    srv.serve_background()
    servers.append(srv)
    yield srv
    for s in servers:
        s.stop()


class TestRotas:
    def test_verificacao_publica_devolve_challenge(self, meta_server) -> None:
        porteiro = meta_server.bound_port
        status, corpo, _ = _request(
            porteiro, "GET",
            "/webhook/meta?hub.mode=subscribe&hub.verify_token=segredo&hub.challenge=42",
        )
        assert status == 200 and corpo.decode() == "42"

    def test_verificacao_com_token_errado_403(self, meta_server) -> None:
        status, _, _ = _request(
            meta_server.bound_port, "GET",
            "/webhook/meta?hub.mode=subscribe&hub.verify_token=x&hub.challenge=42",
        )
        assert status == 403

    def test_post_sem_assinatura_403(self, meta_server) -> None:
        status, _, _ = _request(
            meta_server.bound_port, "POST", "/webhook/meta", body={"entry": []},
            headers={"X-Hub-Signature-256": "sha256=00"},
        )
        assert status == 403

    def test_post_assinado_processa(self, meta_server) -> None:
        corpo = json.dumps(_payload("oi")).encode()
        status, resposta, _ = _request(
            meta_server.bound_port, "POST", "/webhook/meta", raw_body=corpo,
            headers={"X-Hub-Signature-256": assinar(corpo, "shh")},
        )
        assert status == 200
        assert json.loads(resposta)["respondidas"] == 1

    def test_post_sem_handler_503(self) -> None:
        srv = APIServer(None, config=APIConfig(port=0, rate_limit_max=0))
        srv.serve_background()
        try:
            status, _, _ = _request(srv.bound_port, "POST", "/webhook/meta", body={})
            assert status == 503
        finally:
            srv.stop()
