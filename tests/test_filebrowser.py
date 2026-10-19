"""
OMEGA DRAKON • TESTES
Módulo: tests/test_filebrowser.py
Descrição: Testes do File Browser (integrations/filebrowser.py) — 6ª
           ferramenta interligada (pedido do dono 18/10: "Liga" — 2ª
           da análise de FlatNotes/File Browser/Calibre). Dublê de
           transporte roteirizado com fixtures FIÉIS às capturas VIVAS
           do od-filebrowser (apuradas antes de codificar via fonte
           oficial da tag 2.63.23 + round-trip real): GET /health
           público `{"status":"OK"}`, janela `window.FileBrowser` do
           HTML com o campo Version, JWT cru no login, uso de disco
           em bytes, raiz vazia honesta, shape real dos itens
           (path/name/size/modified/isDir), arquivo no caminho sem
           `items`, 409 textual do upload sem override. Cobre:
           contrato vivo, 409 = filebrowser_ja_existe honesto
           (substituir é flag explícita e vem DECLARADA), caminho com
           ".." recusado, pasta vazia honesta, credencial ausente e
           recusada (403), erros tipados de rede/JSON, fábrica lazy
           com OD_FILEBROWSER_URL/senha + as 3 actions no catálogo
           (categoria filebrowser, só admin) — e a prova de que NÃO
           existe action de apagar (DELETE fora do catálogo, régua do
           dono).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - integrations/filebrowser.py (FileBrowserClient + transporte injetável)
  - contratos ao vivo do od-filebrowser (127.0.0.1:8410, apurado 18/10,
    fonte http/*.go da tag 2.63.23 + round-trip completo)
  - tools/actions/actions.py (filebrowser_status/lista/envia)
"""

from __future__ import annotations

import base64
import io
import json
import socket
import time
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from core.security import SecurityManager
from integrations import filebrowser as filebrowser_mod
from integrations.filebrowser import (
    URL_PADRAO,
    FileBrowserClient,
    FileBrowserError,
    _exp_do_jwt,
    _normaliza_caminho,
    client_padrao,
    resetar_cliente,
)
from tools.actions import CATALOG, build_registry
from tools.actions.actions import (
    filebrowser_envia,
    filebrowser_lista,
    filebrowser_status,
)

# ---------------------------------------------------------------------------
# Fixtures fiéis às capturas VIVAS do od-filebrowser (18/10, 2.63.23)
# ---------------------------------------------------------------------------

# GET /health → objeto JSON com status (sem auth)
SAUDE_JSON = b'{"status":"OK"}'

# GET / → HTML da própria SPA com a janela FileBrowser (versão real)
PAGINA_HTML = (
    b'<!doctype html><html lang="en"><head><meta charset="utf-8"/>'
    b"<title>\n      File Browser\n    </title></head><body>"
    b"<script>\n      window.FileBrowser = {\"AuthMethod\":\"json\","
    b"\"BaseURL\":\"\",\"EnableExec\":false,\"EnableThumbs\":true,"
    b"\"HideLoginButton\":true,\"LoginPage\":true,\"NoAuth\":false,"
    b"\"ReCaptcha\":false,\"ResizePreview\":true,\"Signup\":false,"
    b'\"Theme":"blue","Version":"2.63.23"};\n    </script></body></html>'
)

# GET / sem a janela (contrato mudou?)
PAGINA_SEM_JANELA = b"<!doctype html><html><body>chegou outra coisa</body></html>"


def _jwt(exp: int = 4102444800) -> bytes:
    """JWT cru no formato do vivo (603 chars no original; começa com ey)."""
    cabeca = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
    carga = base64.urlsafe_b64encode(
        json.dumps({"exp": exp, "sub": "admin"}).encode()
    ).rstrip(b"=").decode()
    return f"{cabeca}.{carga}.assinatura-torta-do-duble".encode()


TOKEN = _jwt()

# POST /api/login → 403 textual (fonte: os.ErrPermission → 403, não 401)
LOGIN_403 = b"403 Forbidden"

# GET /api/usage/ → disco em bytes (valores vivos do container)
USO_JSON = b'{"total":248215199744,"used":148951515136}'

# GET /api/resources/ → raiz VAZIA (a caixa nunca foi usada)
RAIZ_VAZIA = (
    b'{"items":[],"numDirs":0,"numFiles":0,"sorting":{"by":"name","asc":false},'
    b'"path":"/","name":"","size":4096,"extension":"","modified":'
    b'"2026-10-18T19:46:28.907522982Z","mode":2147484157,"isDir":true,'
    b'"isSymlink":false,"type":""}'
)

# GET /api/resources/_dir_teste → shape REAL dos itens (capturado ao vivo)
PASTA_COM_ITENS = (
    b'{"items":[{"path":"/_dir_teste/a.txt","name":"a.txt","size":19,'
    b'"extension":".txt","modified":"2026-10-18T19:51:50.46917544Z",'
    b'"mode":416,"isDir":false,"isSymlink":false,"type":"text"},'
    b'{"path":"/_dir_teste/sub","name":"sub","size":4096,"extension":"",'
    b'"modified":"2026-10-18T19:51:50.46917544Z","mode":2147484136,'
    b'"isDir":true,"isSymlink":false,"type":""}],"numDirs":1,"numFiles":1,'
    b'"sorting":{"by":"name","asc":false},"path":"/_dir_teste",'
    b'"name":"_dir_teste","size":4096,"isDir":true}'
)

# Pasta-pai já com o arquivo (prova do substituido=True declarado)
PAI_COM_ARQUIVO = (
    b'{"items":[{"path":"rel/a.txt","name":"a.txt","size":19,'
    b'"extension":".txt","modified":"2026-10-18T19:51:50.46917544Z",'
    b'"mode":416,"isDir":false,"isSymlink":false,"type":"text"}],'
    b'"numDirs":0,"numFiles":1,"path":"rel","name":"rel","isDir":true}'
)

# GET de ARQUIVO → info SEM "items" (contrato apurado: é arquivo, não pasta)
INFO_ARQUIVO = (
    b'{"path":"/_dir_teste/a.txt","name":"a.txt","size":19,'
    b'"extension":".txt","modified":"2026-10-18T19:51:50.46917544Z",'
    b'"mode":416,"isDir":false,"isSymlink":false,"type":"text",'
    b'"content":"conteudo de prova\\n"}'
)

# Upload repetido sem ?override=true → texto puro "409 Conflict"
CONFLITO_409 = b"409 Conflict"


# ---------------------------------------------------------------------------
# Dublês
# ---------------------------------------------------------------------------

class _TransporteFalso:
    """Respostas roteirizadas (ou exceção) + registro das chamadas.

    A última resposta gruda (reusada em chamadas seguintes), as demais
    são consumidas em ordem — mesma semântica dos dublês do FlatNotes.
    Corpo cru é LIDO NA HORA (o arquivo real é fechado após a chamada).
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
        corpo_bruto: Any = None,
        cabecalhos: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        registro: dict[str, Any] = {
            "url": url,
            "timeout_s": timeout_s,
            "metodo": metodo,
            "corpo": corpo,
            "cabecalhos": dict(cabecalhos or {}),
        }
        if corpo_bruto is not None:
            registro["corpo_bruto"] = (
                corpo_bruto.read() if hasattr(corpo_bruto, "read") else corpo_bruto
            )
        self.chamadas.append(registro)
        if not self._respostas:
            raise AssertionError("resposta não roteirizada para a chamada")
        item = self._respostas.pop(0) if len(self._respostas) > 1 else self._respostas[0]
        if isinstance(item, BaseException):
            raise item
        return item

    @property
    def ultima(self) -> dict[str, Any]:
        return self.chamadas[-1]


def _cliente(*respostas: Any, senha: str = "senha-robusta-18-10") -> tuple[FileBrowserClient, _TransporteFalso]:
    transporte = _TransporteFalso(*respostas)
    return FileBrowserClient(URL_PADRAO, senha=senha, transporte=transporte), transporte


def _com_fabrica(cliente: Any, monkeypatch) -> None:
    monkeypatch.setattr(filebrowser_mod, "client_padrao", lambda: cliente)


def _arquivo_local(tmp_path: Path, conteudo: bytes = b"conteudo de prova cru\n") -> Path:
    origem = tmp_path / "origem.txt"
    origem.write_bytes(conteudo)
    return origem


@pytest.fixture(autouse=True)
def _fabrica_limpa():
    """Fábrica cacheada nunca vaza entre testes."""
    resetar_cliente()
    yield
    resetar_cliente()


# ===========================================================================
# Cliente — status (vida da caixa)
# ===========================================================================

class TestClienteStatus:
    def test_status_ok_com_versao_disco_e_contagem(self) -> None:
        cliente, t = _cliente(
            (200, {}, SAUDE_JSON),
            (200, {}, PAGINA_HTML),
            (200, {}, TOKEN),
            (200, {}, USO_JSON),
            (200, {}, RAIZ_VAZIA),
        )
        r = cliente.status()
        assert r["acessivel"] is True
        assert r["saude"] == "OK"
        assert r["versao"] == "2.63.23"
        assert r["pastas"] == 0
        assert r["arquivos"] == 0
        assert r["disco"]["total"] == 248215199744
        assert r["disco"]["usado"] == 148951515136
        assert r["disco"]["uso_pct"] == pytest.approx(60.0, abs=0.1)
        assert [c["url"] for c in t.chamadas] == [
            f"{URL_PADRAO}/health",
            f"{URL_PADRAO}/",
            f"{URL_PADRAO}/api/login",
            f"{URL_PADRAO}/api/usage/",
            f"{URL_PADRAO}/api/resources/",
        ]
        # login manda JSON honesto; as chamadas autenticadas levam o JWT
        assert t.chamadas[2]["corpo"] == {
            "username": "admin",
            "password": "senha-robusta-18-10",
        }
        assert t.chamadas[3]["cabecalhos"].get("X-Auth") == TOKEN.decode()
        assert "X-Auth" not in t.chamadas[0]["cabecalhos"]

    def test_health_fora_200_eh_falhou(self) -> None:
        cliente, _ = _cliente((500, {}, b"boom"))
        with pytest.raises(FileBrowserError) as exc:
            cliente.status()
        assert exc.value.codigo == "filebrowser_falhou"
        assert "HTTP 500" in exc.value.mensagem

    def test_pagina_sem_janela_eh_resposta_invalida(self) -> None:
        cliente, _ = _cliente((200, {}, SAUDE_JSON), (200, {}, PAGINA_SEM_JANELA))
        with pytest.raises(FileBrowserError) as exc:
            cliente.status()
        assert exc.value.codigo == "filebrowser_resposta_invalida"
        assert "window.FileBrowser" in exc.value.mensagem

    def test_janela_sem_version_eh_resposta_invalida(self) -> None:
        pagina = b'<script>window.FileBrowser = {"AuthMethod":"json"};</script>'
        cliente, _ = _cliente((200, {}, SAUDE_JSON), (200, {}, pagina))
        with pytest.raises(FileBrowserError) as exc:
            cliente.status()
        assert exc.value.codigo == "filebrowser_resposta_invalida"
        assert "Version" in exc.value.mensagem

    def test_sem_senha_configurada_eh_credencial(self) -> None:
        transporte = _TransporteFalso((200, {}, SAUDE_JSON), (200, {}, PAGINA_HTML))
        cliente = FileBrowserClient(URL_PADRAO, senha="", transporte=transporte)
        with pytest.raises(FileBrowserError) as exc:
            cliente.status()
        assert exc.value.codigo == "filebrowser_credencial"
        assert "OD_FILEBROWSER_PASSWORD" in exc.value.mensagem
        assert len(transporte.chamadas) == 2  # nem tenta login sem senha

    def test_login_403_eh_credencial_rejeitada_honesta(self) -> None:
        cliente, _ = _cliente(
            (200, {}, SAUDE_JSON),
            (200, {}, PAGINA_HTML),
            (403, {}, LOGIN_403),
        )
        with pytest.raises(FileBrowserError) as exc:
            cliente.status()
        assert exc.value.codigo == "filebrowser_credencial"
        assert "403" in exc.value.mensagem
        assert "mudou" in exc.value.mensagem

    def test_usage_lixo_eh_resposta_invalida(self) -> None:
        cliente, _ = _cliente(
            (200, {}, SAUDE_JSON),
            (200, {}, PAGINA_HTML),
            (200, {}, TOKEN),
            (200, {}, b"lixo"),
        )
        with pytest.raises(FileBrowserError) as exc:
            cliente.status()
        assert exc.value.codigo == "filebrowser_resposta_invalida"
        assert "usage" in exc.value.mensagem

    def test_raiz_sem_contagem_eh_resposta_invalida(self) -> None:
        cliente, _ = _cliente(
            (200, {}, SAUDE_JSON),
            (200, {}, PAGINA_HTML),
            (200, {}, TOKEN),
            (200, {}, USO_JSON),
            (200, {}, b'{"items":[]}'),
        )
        with pytest.raises(FileBrowserError) as exc:
            cliente.status()
        assert exc.value.codigo == "filebrowser_resposta_invalida"


# ===========================================================================
# Cliente — lista (raiz honesta; shape real; 404; ".." recusado)
# ===========================================================================

class TestClienteLista:
    def test_raiz_vazia_eh_estado_honesto(self) -> None:
        cliente, t = _cliente((200, {}, TOKEN), (200, {}, RAIZ_VAZIA))
        r = cliente.lista()
        assert r == {"caminho": "/", "pastas": 0, "arquivos": 0, "itens": []}
        assert t.chamadas[0]["url"].endswith("/api/login")
        assert t.chamadas[1]["url"] == f"{URL_PADRAO}/api/resources/"

    def test_subpasta_com_shape_real_dos_itens(self) -> None:
        cliente, t = _cliente((200, {}, TOKEN), (200, {}, PASTA_COM_ITENS))
        r = cliente.lista("_dir_teste")
        assert r["caminho"] == "/_dir_teste"
        assert r["pastas"] == 1
        assert r["arquivos"] == 1
        arquivo, pasta = r["itens"]
        assert arquivo["nome"] == "a.txt"
        assert arquivo["caminho"] == "/_dir_teste/a.txt"
        assert arquivo["e_pasta"] is False
        assert arquivo["tamanho"] == 19
        assert arquivo["modificado"] == "2026-10-18T19:51:50.46917544Z"
        assert pasta["nome"] == "sub"
        assert pasta["e_pasta"] is True
        # subpasta SEM barra final (sem ela o servidor responde 200 direto)
        assert t.chamadas[1]["url"] == f"{URL_PADRAO}/api/resources/_dir_teste"

    def test_barras_e_ponto_normalizados(self) -> None:
        cliente, t = _cliente((200, {}, TOKEN), (200, {}, RAIZ_VAZIA))
        r = cliente.lista("/sub//./")
        assert r["caminho"] == "/sub"
        assert t.chamadas[1]["url"].endswith("/api/resources/sub")

    def test_ponto_ponto_recusado_sem_chamada(self) -> None:
        cliente, t = _cliente((200, {}, TOKEN), (200, {}, RAIZ_VAZIA))
        with pytest.raises(FileBrowserError) as exc:
            cliente.lista("../fora_da_caixa")
        assert exc.value.codigo == "filebrowser_parametro_invalido"
        assert ".." in exc.value.mensagem
        assert t.chamadas == []

    def test_pasta_inexistente_eh_nao_encontrado(self) -> None:
        cliente, _ = _cliente((200, {}, TOKEN), (404, {}, b"404 Not Found"))
        with pytest.raises(FileBrowserError) as exc:
            cliente.lista("fantasma")
        assert exc.value.codigo == "filebrowser_nao_encontrado"
        assert "não existe na caixa" in exc.value.mensagem

    def test_arquivo_no_caminho_eh_parametro_invalido(self) -> None:
        cliente, _ = _cliente((200, {}, TOKEN), (200, {}, INFO_ARQUIVO))
        with pytest.raises(FileBrowserError) as exc:
            cliente.lista("a.txt")
        assert exc.value.codigo == "filebrowser_parametro_invalido"
        assert "não é uma pasta" in exc.value.mensagem

    def test_corpo_nao_json_eh_resposta_invalida(self) -> None:
        cliente, _ = _cliente((200, {}, TOKEN), (200, {}, b"lixo"))
        with pytest.raises(FileBrowserError) as exc:
            cliente.lista()
        assert exc.value.codigo == "filebrowser_resposta_invalida"

    def test_item_fora_do_shape_eh_resposta_invalida(self) -> None:
        corpo = b'{"items":["torto"],"numDirs":0,"numFiles":1}'
        cliente, _ = _cliente((200, {}, TOKEN), (200, {}, corpo))
        with pytest.raises(FileBrowserError) as exc:
            cliente.lista()
        assert exc.value.codigo == "filebrowser_resposta_invalida"


# ===========================================================================
# Cliente — envia (corpo cru; 409 honesto; substituir DECLARADO)
# ===========================================================================

class TestClienteEnvia:
    def test_envia_corpo_cru_com_timeout_de_envio(self, tmp_path: Path) -> None:
        origem = _arquivo_local(tmp_path, b"relatorio do sistema\n")
        cliente, t = _cliente((200, {}, TOKEN), (200, {}, b""))
        r = cliente.envia(origem, "relatorios/od.txt")
        assert r == {"arquivo": "relatorios/od.txt", "tamanho": 21, "substituido": False}
        post = t.chamadas[1]
        assert post["metodo"] == "POST"
        assert post["url"] == f"{URL_PADRAO}/api/resources/relatorios/od.txt"
        assert "override" not in post["url"]
        assert post["corpo_bruto"] == b"relatorio do sistema\n"
        assert post["cabecalhos"]["X-Auth"] == TOKEN.decode()
        assert post["timeout_s"] == 60.0  # subida tem folga própria

    def test_409_sem_flag_eh_ja_existe_honesto(self, tmp_path: Path) -> None:
        origem = _arquivo_local(tmp_path)
        cliente, t = _cliente((200, {}, TOKEN), (409, {}, CONFLITO_409))
        with pytest.raises(FileBrowserError) as exc:
            cliente.envia(origem, "od.txt")
        assert exc.value.codigo == "filebrowser_ja_existe"
        assert "substituir=true" in exc.value.mensagem
        assert len(t.chamadas) == 2  # não tenta sobrescrever por conta própria

    def test_substituir_true_declarando_arquivo_novo(self, tmp_path: Path) -> None:
        origem = _arquivo_local(tmp_path)
        cliente, t = _cliente(
            (200, {}, TOKEN),
            (200, {}, RAIZ_VAZIA),  # pai sem o arquivo
            (200, {}, b""),
        )
        r = cliente.envia(origem, "od.txt", substituir=True)
        assert r["substituido"] is False  # nada antigo foi trocado
        assert t.chamadas[1]["url"] == f"{URL_PADRAO}/api/resources/"
        assert t.chamadas[2]["url"].endswith("/api/resources/od.txt?override=true")

    def test_substituir_true_declarando_troca_real(self, tmp_path: Path) -> None:
        origem = _arquivo_local(tmp_path)
        cliente, t = _cliente(
            (200, {}, TOKEN),
            (200, {}, PAI_COM_ARQUIVO),  # a.txt já estava lá
            (200, {}, b""),
        )
        r = cliente.envia(origem, "rel/a.txt", substituir=True)
        assert r["substituido"] is True
        assert t.chamadas[1]["url"] == f"{URL_PADRAO}/api/resources/rel"
        assert "override=true" in t.chamadas[2]["url"]

    def test_substituir_true_com_pai_inexistente(self, tmp_path: Path) -> None:
        origem = _arquivo_local(tmp_path)
        cliente, _ = _cliente(
            (200, {}, TOKEN),
            (404, {}, b"404 Not Found"),
            (200, {}, b""),
        )
        r = cliente.envia(origem, "nova_pasta/od.txt", substituir=True)
        assert r["substituido"] is False  # pai nem existia: arquivo novo

    def test_origem_ausente_eh_arquivo_ausente(self, tmp_path: Path) -> None:
        cliente, t = _cliente((200, {}, TOKEN), (200, {}, b""))
        with pytest.raises(FileBrowserError) as exc:
            cliente.envia(str(tmp_path / "nao_existe.txt"), "od.txt")
        assert exc.value.codigo == "filebrowser_arquivo_ausente"
        assert "Origem" in exc.value.mensagem
        assert t.chamadas == []

    def test_origem_vazia_eh_parametro_invalido(self, tmp_path: Path) -> None:
        cliente, t = _cliente((200, {}, TOKEN), (200, {}, b""))
        with pytest.raises(FileBrowserError) as exc:
            cliente.envia("   ", "od.txt")
        assert exc.value.codigo == "filebrowser_parametro_invalido"
        assert t.chamadas == []

    def test_destino_vazio_reprovado(self, tmp_path: Path) -> None:
        origem = _arquivo_local(tmp_path)
        cliente, t = _cliente((200, {}, TOKEN), (200, {}, b""))
        with pytest.raises(FileBrowserError) as exc:
            cliente.envia(origem, "   ")
        assert exc.value.codigo == "filebrowser_parametro_invalido"
        assert "destino" in exc.value.mensagem
        assert t.chamadas == []

    def test_destino_com_barra_final_reprovado(self, tmp_path: Path) -> None:
        origem = _arquivo_local(tmp_path)
        cliente, t = _cliente((200, {}, TOKEN), (200, {}, b""))
        with pytest.raises(FileBrowserError) as exc:
            cliente.envia(origem, "pasta/")
        assert exc.value.codigo == "filebrowser_parametro_invalido"
        assert t.chamadas == []

    def test_destino_com_ponto_ponto_reprovado(self, tmp_path: Path) -> None:
        origem = _arquivo_local(tmp_path)
        cliente, t = _cliente((200, {}, TOKEN), (200, {}, b""))
        with pytest.raises(FileBrowserError) as exc:
            cliente.envia(origem, "../de_fora.txt")
        assert exc.value.codigo == "filebrowser_parametro_invalido"
        assert t.chamadas == []

    def test_upload_403_eh_falhou_de_permissao(self, tmp_path: Path) -> None:
        origem = _arquivo_local(tmp_path)
        cliente, _ = _cliente((200, {}, TOKEN), (403, {}, b"403 Forbidden"))
        with pytest.raises(FileBrowserError) as exc:
            cliente.envia(origem, "od.txt")
        assert exc.value.codigo == "filebrowser_falhou"
        assert "permissão" in exc.value.mensagem


# ===========================================================================
# Erros de rede + normalização + JWT + fábrica lazy
# ===========================================================================

class TestErrosRede:
    def test_urlerror_vira_indisponivel(self) -> None:
        cliente, _ = _cliente(urllib.error.URLError("caiu"))
        with pytest.raises(FileBrowserError) as exc:
            cliente.lista()
        assert exc.value.codigo == "filebrowser_indisponivel"
        assert "inacessível" in exc.value.mensagem

    def test_timeout_vira_filebrowser_timeout(self) -> None:
        cliente, _ = _cliente(socket.timeout("demorou"))
        with pytest.raises(FileBrowserError) as exc:
            cliente.status()
        assert exc.value.codigo == "filebrowser_timeout"


class TestNormalizacaoEJwt:
    def test_normaliza_tira_barras_e_pontos(self) -> None:
        assert _normaliza_caminho("/a//./b/", exigir=False, campo="c") == "a/b"
        assert _normaliza_caminho(None, exigir=False, campo="c") == ""

    def test_normaliza_exigindo_rejeita_vazio(self) -> None:
        with pytest.raises(FileBrowserError) as exc:
            _normaliza_caminho("", exigir=True, campo="destino")
        assert exc.value.codigo == "filebrowser_parametro_invalido"

    def test_exp_do_jwt_lê_o_claim(self) -> None:
        assert _exp_do_jwt(TOKEN.decode()) == 4102444800

    def test_exp_torto_cai_na_folha_conservadora(self) -> None:
        token = "eyJhbGciOiJIUzI1NiJ9.eyJleHAiOiJ0b3J0b19zZSJ9.assinatura"
        # claim não numérico → folga absoluta < 2h a partir de agora
        # (renova cedo, nunca vence no meio de uma operação)
        antes = time.time()
        valor = _exp_do_jwt(token)
        assert antes + 6900 < valor <= antes + 7100


class TestFabrica:
    def test_url_e_cache_padrao(self) -> None:
        a, b = client_padrao(), client_padrao()
        assert a is b
        assert a.base_url == URL_PADRAO

    def test_url_e_senha_do_env(self, monkeypatch) -> None:
        monkeypatch.setenv("OD_FILEBROWSER_URL", "http://127.0.0.1:9999")
        monkeypatch.setenv("OD_FILEBROWSER_USUARIO", "dono")
        monkeypatch.setenv("OD_FILEBROWSER_PASSWORD", "outra-senha")
        cliente = client_padrao()
        assert cliente.base_url == "http://127.0.0.1:9999"
        assert cliente.usuario == "dono"
        assert cliente.senha == "outra-senha"

    def test_reset_esquece_a_instancia(self) -> None:
        antes = client_padrao()
        resetar_cliente()
        assert client_padrao() is not antes


# ===========================================================================
# Transporte real (urllib) — JSON, corpo cru e HTTPError como resposta
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
    def test_post_com_json_vai_como_json(self, monkeypatch) -> None:
        capturas: list[Any] = []

        def _abre(req, timeout=None):
            capturas.append(req)
            return _RespHttp(200, TOKEN)

        monkeypatch.setattr(filebrowser_mod.urllib.request, "urlopen", _abre)
        from integrations.filebrowser import _transporte

        _transporte(
            "http://x/api/login",
            timeout_s=5.0,
            metodo="POST",
            corpo={"username": "admin", "password": "s"},
        )
        assert json.loads(capturas[-1].data.decode()) == {
            "username": "admin",
            "password": "s",
        }
        assert capturas[-1].get_header("Content-type") == "application/json"

    def test_corpo_bruto_vai_cru_com_octet_stream(self, monkeypatch) -> None:
        capturas: list[Any] = []

        def _abre(req, timeout=None):
            capturas.append(req)
            return _RespHttp(200, b"")

        monkeypatch.setattr(filebrowser_mod.urllib.request, "urlopen", _abre)
        from integrations.filebrowser import _transporte

        _transporte(
            "http://x/api/resources/od.txt",
            timeout_s=60.0,
            metodo="POST",
            corpo_bruto=io.BytesIO(b"conteudo cru"),
        )
        # file-like chega intacto ao servidor (streaming, sem carregar tudo)
        assert hasattr(capturas[-1].data, "read")
        assert capturas[-1].data.read() == b"conteudo cru"
        assert capturas[-1].get_header("Content-type") == "application/octet-stream"

    def test_http_error_devolve_status_em_vez_de_explodir(self, monkeypatch) -> None:
        def _abre(req, timeout=None):
            raise urllib.error.HTTPError(
                "http://x", 409, "Conflict", {}, io.BytesIO(CONFLITO_409)
            )

        monkeypatch.setattr(filebrowser_mod.urllib.request, "urlopen", _abre)
        from integrations.filebrowser import _transporte

        status, _h, corpo = _transporte(
            "http://x/api/resources/od.txt", timeout_s=5.0, metodo="POST", corpo_bruto=b"x"
        )
        assert status == 409
        assert corpo == CONFLITO_409


# ===========================================================================
# Actions — contrato fino sobre o cliente (LAZY: fora do ar degrada)
# ===========================================================================

class TestActionsFileBrowser:
    def test_status_ok(self, monkeypatch) -> None:
        cliente, _ = _cliente(
            (200, {}, SAUDE_JSON),
            (200, {}, PAGINA_HTML),
            (200, {}, TOKEN),
            (200, {}, USO_JSON),
            (200, {}, RAIZ_VAZIA),
        )
        _com_fabrica(cliente, monkeypatch)
        r = filebrowser_status()
        assert r["ok"] is True
        assert r["versao"] == "2.63.23"
        assert r["saude"] == "OK"

    def test_status_fora_do_ar_degrada_a_action(self, monkeypatch) -> None:
        cliente, _ = _cliente(urllib.error.URLError("caiu"))
        _com_fabrica(cliente, monkeypatch)
        r = filebrowser_status()
        assert r["ok"] is False
        assert r["error"] == "filebrowser_indisponivel"
        assert "inacessível" in r["message"]

    def test_status_credencial_rejeitada_degrada_honestamente(self, monkeypatch) -> None:
        cliente, _ = _cliente(
            (200, {}, SAUDE_JSON),
            (200, {}, PAGINA_HTML),
            (403, {}, LOGIN_403),
        )
        _com_fabrica(cliente, monkeypatch)
        r = filebrowser_status()
        assert r["ok"] is False
        assert r["error"] == "filebrowser_credencial"

    def test_lista_ok(self, monkeypatch) -> None:
        cliente, _ = _cliente((200, {}, TOKEN), (200, {}, PASTA_COM_ITENS))
        _com_fabrica(cliente, monkeypatch)
        r = filebrowser_lista(caminho="_dir_teste")
        assert r["ok"] is True
        assert r["itens"][0]["nome"] == "a.txt"

    def test_lista_pasta_inexistente_honesta(self, monkeypatch) -> None:
        cliente, _ = _cliente((200, {}, TOKEN), (404, {}, b"404 Not Found"))
        _com_fabrica(cliente, monkeypatch)
        r = filebrowser_lista(caminho="fantasma")
        assert r["ok"] is False
        assert r["error"] == "filebrowser_nao_encontrado"

    def test_envia_ok(self, monkeypatch, tmp_path: Path) -> None:
        origem = _arquivo_local(tmp_path)
        cliente, _ = _cliente((200, {}, TOKEN), (200, {}, b""))
        _com_fabrica(cliente, monkeypatch)
        r = filebrowser_envia(origem=str(origem), destino="saida/rel.txt")
        assert r["ok"] is True
        assert r["arquivo"] == "saida/rel.txt"
        assert r["substituido"] is False

    def test_envia_ja_existe_honesto(self, monkeypatch, tmp_path: Path) -> None:
        origem = _arquivo_local(tmp_path)
        cliente, _ = _cliente((200, {}, TOKEN), (409, {}, CONFLITO_409))
        _com_fabrica(cliente, monkeypatch)
        r = filebrowser_envia(origem=str(origem), destino="rel.txt")
        assert r["ok"] is False
        assert r["error"] == "filebrowser_ja_existe"

    def test_envia_origem_ausente_honesta(self, monkeypatch, tmp_path: Path) -> None:
        cliente, _ = _cliente((200, {}, TOKEN), (200, {}, b""))
        _com_fabrica(cliente, monkeypatch)
        r = filebrowser_envia(
            origem=str(tmp_path / "sumiu.txt"), destino="rel.txt"
        )
        assert r["ok"] is False
        assert r["error"] == "filebrowser_arquivo_ausente"


# ===========================================================================
# Catálogo + permissão (só admin; sem action de apagar)
# ===========================================================================

FILEBROWSER_ACOES = {"filebrowser_status", "filebrowser_lista", "filebrowser_envia"}


class TestCatalogoFileBrowser:
    def test_tres_actions_na_categoria_filebrowser(self) -> None:
        da_ferramenta = [s for s in CATALOG if s["category"] == "filebrowser"]
        assert {s["name"] for s in da_ferramenta} == FILEBROWSER_ACOES
        assert len(da_ferramenta) == 3

    def test_schemas_dos_params(self) -> None:
        por_nome = {s["name"]: s for s in CATALOG}
        assert por_nome["filebrowser_status"]["params"] == {}
        lista = por_nome["filebrowser_lista"]["params"]
        assert lista["properties"]["caminho"]["default"] == ""
        envia = por_nome["filebrowser_envia"]["params"]
        assert envia.get("required") == ["origem", "destino"]
        assert envia["properties"]["substituir"]["default"] is False

    def test_nenhuma_action_de_apagar_no_catalogo(self) -> None:
        """DELETE da API fica fora — nada apagado por acidente."""
        nomes = {s["name"] for s in CATALOG if s["category"] == "filebrowser"}
        proibidos = ("delete", "apaga", "exclui", "remove", "limpa")
        assert not any(
            any(p in nome for p in proibidos) for nome in nomes
        )

    @pytest.mark.asyncio
    async def test_papel_user_negado_por_permissao(self) -> None:
        """A caixa é do admin: papel comum não alcança."""
        registry = build_registry(security=SecurityManager(mode="strict"))
        params = {
            "filebrowser_status": {},
            "filebrowser_lista": {"caminho": ""},
            "filebrowser_envia": {"origem": "/tmp/x", "destino": "x"},
        }
        for nome in sorted(FILEBROWSER_ACOES):
            result = await registry.execute(nome, params=params[nome], role="user")
            assert result.status == "denied", nome
            assert result.denied_by == "permission", nome

    @pytest.mark.asyncio
    async def test_papel_admin_executa(self, monkeypatch) -> None:
        """Admin passa pelo gate e a action roda no cliente fake."""
        cliente, _ = _cliente((200, {}, TOKEN), (200, {}, RAIZ_VAZIA))
        _com_fabrica(cliente, monkeypatch)
        registry = build_registry(security=SecurityManager(mode="strict"))
        result = await registry.execute("filebrowser_lista", role="admin")
        assert result.status == "ok"
        assert result.data["ok"] is True
        assert result.data["itens"] == []


__all__ = [
    "TestClienteStatus",
    "TestClienteLista",
    "TestClienteEnvia",
    "TestErrosRede",
    "TestNormalizacaoEJwt",
    "TestFabrica",
    "TestTransporteUrllib",
    "TestActionsFileBrowser",
    "TestCatalogoFileBrowser",
]
