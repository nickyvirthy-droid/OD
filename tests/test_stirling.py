"""
OMEGA DRAKON • TESTS
Módulo: tests/test_stirling.py
Descrição: Testes da Stirling PDF (integrations/stirling.py) — 2ª das 3
           interligações de ferramenta aprovadas (Vaultwarden → Stirling →
           Kiwix). Cliente com transporte INJETÁVEL: corpo multipart
           inspecionado byte a byte, respostas roteirizadas (PDF/ZIP/JSON
           de erro/HTML), mapeamento honesto de erro tipado (rede, 4xx,
           5xx, corpo inválido), validação de mágica ANTES de gravar,
           trava de saída existente (nada apagado por acidente), fábrica
           lazy + as 4 actions no catálogo (categoria stirling, só admin).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - integrations/stirling.py (StirlingClient + transporte injetável)
  - contratos ao vivo do s-pdf 2.13.1 (GET /v1/api-docs, apurado 17/10)
  - tools/actions/actions.py (stirling_status/merge/split/compress)
"""

from __future__ import annotations

import hashlib
import io
import pathlib
import socket
import urllib.error
from typing import Any

import pytest

from core.security import SecurityManager
from integrations import stirling as stirling_mod
from integrations.stirling import (
    URL_PADRAO,
    StirlingClient,
    StirlingError,
    _monta_multipart,
    _nome_seguro,
    client_padrao,
    resetar_cliente,
)
from tools.actions import CATALOG, build_registry
from tools.actions.actions import (
    stirling_compress,
    stirling_merge,
    stirling_split,
    stirling_status,
)

# Corpos "verdade" para resposta do serviço
PDF = b"%PDF-1.4\nsaida-da-stirling\n%%EOF\n"
ZIP = b"PK\x03\x04pedacos-do-split"


# ---------------------------------------------------------------------------
# Dublês
# ---------------------------------------------------------------------------

class _TransporteFalso:
    """Respostas roteirizadas (ou exceção) + registro das chamadas.

    A última resposta gruda (reusada em chamadas seguintes), as demais
    são consumidas em ordem.
    """

    def __init__(self, *respostas: Any) -> None:
        self._respostas = list(respostas)
        self.chamadas: list[dict[str, Any]] = []

    def __call__(self, url: str, *, data=None, headers=None, timeout_s=None):
        self.chamadas.append(
            {"url": url, "data": data, "headers": headers, "timeout_s": timeout_s}
        )
        if not self._respostas:
            raise AssertionError("resposta não roteirizada para a chamada")
        item = self._respostas.pop(0) if len(self._respostas) > 1 else self._respostas[0]
        if isinstance(item, BaseException):
            raise item
        return item

    @property
    def corpo(self) -> bytes:
        """Corpo enviado na última chamada (para inspecionar o multipart)."""
        return self.chamadas[-1]["data"] or b""


class _RespHttp:
    """Resposta urlopen falsa (context manager, status, headers, read)."""

    def __init__(self, status: int = 200, headers=None, body: bytes = b"") -> None:
        self.status = status
        self.headers = headers if headers is not None else {"Content-Type": "application/json"}
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_RespHttp":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False


def _cliente(*respostas: Any) -> tuple[StirlingClient, _TransporteFalso]:
    transporte = _TransporteFalso(*respostas)
    return StirlingClient(transporte=transporte), transporte


def _arquivo(caminho: pathlib.Path, conteudo: bytes = b"entrada") -> pathlib.Path:
    caminho.write_bytes(conteudo)
    return caminho


@pytest.fixture(autouse=True)
def _fabrica_limpa():
    """Fábrica cacheada nunca vaza entre testes."""
    resetar_cliente()
    yield
    resetar_cliente()


# ===========================================================================
# Camada baixa — multipart, nomes, erros de rede
# ===========================================================================

class TestMontaMultipart:
    def test_estrutura_boundary_e_fechamento(self) -> None:
        boundary, corpo = _monta_multipart({"pageNumbers": "2,5"}, [])
        assert boundary.encode() in corpo
        assert corpo.startswith(f"--{boundary}\r\n".encode())
        assert corpo.endswith(f"--{boundary}--\r\n".encode())
        assert b'name="pageNumbers"' in corpo
        assert b"\r\n\r\n2,5\r\n" in corpo

    def test_varios_fileinput_ordenados(self) -> None:
        _, corpo = _monta_multipart(
            {},
            [
                ("fileInput", "a.pdf", b"AAA"),
                ("fileInput", "b.pdf", b"BBB"),
            ],
        )
        assert corpo.count(b'name="fileInput"') == 2
        assert corpo.index(b"AAA") < corpo.index(b"BBB")
        assert b'filename="a.pdf"' in corpo and b'filename="b.pdf"' in corpo

    def test_nome_seguro_remove_injecao(self) -> None:
        assert _nome_seguro('/caminho/a"b\r\n.pdf') == "ab.pdf"
        assert _nome_seguro("x/y/doc.pdf") == "doc.pdf"

    def test_bytes_integros_no_corpo(self) -> None:
        binario = b"\x00\xff\x10conteudo\x00"
        _, corpo = _monta_multipart({}, [("fileInput", "a.pdf", binario)])
        assert binario in corpo


class TestTransporteUrllib:
    """Adapter urllib real: resposta/HTTPError/erro de rede tipado."""

    def test_sucesso_retorna_status_headers_corpo(self, monkeypatch) -> None:
        monkeypatch.setattr(
            stirling_mod.urllib.request,
            "urlopen",
            lambda req, timeout=None: _RespHttp(200, {"Content-Type": "application/json"}, b"{}"),
        )
        status, headers, corpo = stirling_mod._transporte(
            "http://x/api", data=None, headers={}, timeout_s=5.0
        )
        assert (status, corpo) == (200, b"{}")
        assert headers["Content-Type"] == "application/json"

    def test_http_error_e_resposta_nao_excecao(self, monkeypatch) -> None:
        def _abre(req, timeout=None):
            raise urllib.error.HTTPError(
                "http://x/api", 400, "Bad Request",
                {"Content-Type": "application/json"},
                io.BytesIO(b'{"error":"recusado"}'),
            )

        monkeypatch.setattr(stirling_mod.urllib.request, "urlopen", _abre)
        status, headers, corpo = stirling_mod._transporte(
            "http://x/api", data=b"x", headers={}, timeout_s=5.0
        )
        assert status == 400
        assert b"recusado" in corpo
        assert headers["Content-Type"] == "application/json"

    def test_conexao_recusada_vira_indisponivel(self, monkeypatch) -> None:
        def _abre(req, timeout=None):
            raise urllib.error.URLError(ConnectionRefusedError("recusada"))

        monkeypatch.setattr(stirling_mod.urllib.request, "urlopen", _abre)
        with pytest.raises(StirlingError) as erro:
            stirling_mod._transporte("http://x/api", data=None, headers={}, timeout_s=5.0)
        assert erro.value.codigo == "stirling_indisponivel"
        assert "inacessível" in erro.value.mensagem

    def test_timeout_vira_stirling_timeout(self, monkeypatch) -> None:
        def _abre(req, timeout=None):
            raise socket.timeout("devagar")

        monkeypatch.setattr(stirling_mod.urllib.request, "urlopen", _abre)
        with pytest.raises(StirlingError) as erro:
            stirling_mod._transporte("http://x/api", data=None, headers={}, timeout_s=9.0)
        assert erro.value.codigo == "stirling_timeout"
        assert "9s" in erro.value.mensagem


# ===========================================================================
# Cliente — status
# ===========================================================================

class TestClienteStatus:
    def test_ok_versao_e_estado(self) -> None:
        cliente, t = _cliente((200, {}, b'{"version":"2.13.1","status":"UP"}'))
        r = cliente.status()
        assert r == {"url": URL_PADRAO, "versao": "2.13.1", "estado": "UP"}
        assert t.chamadas[0]["url"].endswith("/api/v1/info/status")

    def test_resposta_nao_json_e_falha(self) -> None:
        cliente, _ = _cliente((200, {}, b"<html>spa</html>"))
        with pytest.raises(StirlingError) as erro:
            cliente.status()
        assert erro.value.codigo == "stirling_falhou"
        assert "não-JSON" in erro.value.mensagem

    def test_json_sem_version_status_e_falha(self) -> None:
        cliente, _ = _cliente((200, {}, b'{"qualquer":1}'))
        with pytest.raises(StirlingError) as erro:
            cliente.status()
        assert erro.value.codigo == "stirling_falhou"

    def test_http_404_mapeado(self) -> None:
        cliente, _ = _cliente((404, {}, b'{"error":"No endpoint"}'))
        with pytest.raises(StirlingError) as erro:
            cliente.status()
        assert erro.value.codigo == "stirling_falhou"
        assert "HTTP 404" in erro.value.mensagem

    def test_rede_causta_pelo_transporte_injetado(self) -> None:
        cliente, _ = _cliente(urllib.error.URLError("sem rede"))
        with pytest.raises(StirlingError) as erro:
            cliente.status()
        assert erro.value.codigo == "stirling_indisponivel"


# ===========================================================================
# Cliente — merge
# ===========================================================================

class TestClienteMerge:
    def test_ok_grava_sha_e_campos_obrigatorios(self, tmp_path) -> None:
        a = _arquivo(tmp_path / "a.pdf", b"AAA")
        b = _arquivo(tmp_path / "b.pdf", b"BBB")
        saida = tmp_path / "junto.pdf"
        cliente, t = _cliente((200, {"Content-Type": "application/pdf"}, PDF))

        r = cliente.merge([str(a), str(b)], str(saida))

        assert r["arquivo"] == str(saida)
        assert saida.read_bytes() == PDF
        assert r["bytes"] == len(PDF)
        assert r["sha256"] == hashlib.sha256(PDF).hexdigest()
        assert r["content_type"] == "application/pdf"
        assert r["entradas"] == 2
        corpo = t.corpo
        assert b'name="sortType"\r\n\r\norderProvided' in corpo
        assert b'name="removeCertSign"\r\n\r\ntrue' in corpo
        assert b"AAA" in corpo and b"BBB" in corpo
        assert t.chamadas[0]["url"].endswith("/api/v1/general/merge-pdfs")
        assert t.chamadas[0]["headers"]["Content-Type"].startswith("multipart/form-data")

    def test_menos_de_dois_arquivos_reprovado(self, tmp_path) -> None:
        a = _arquivo(tmp_path / "a.pdf")
        saida = tmp_path / "out.pdf"
        cliente, t = _cliente((200, {}, PDF))
        with pytest.raises(StirlingError) as erro:
            cliente.merge([str(a)], str(saida))
        assert erro.value.codigo == "stirling_parametro_invalido"
        assert t.chamadas == []
        assert not saida.exists()

    def test_entrada_inexistente_reprovada(self, tmp_path) -> None:
        b = _arquivo(tmp_path / "b.pdf")
        cliente, t = _cliente((200, {}, PDF))
        with pytest.raises(StirlingError) as erro:
            cliente.merge([str(tmp_path / "nao.pdf"), str(b)], str(tmp_path / "out.pdf"))
        assert erro.value.codigo == "stirling_arquivo_ausente"
        assert t.chamadas == []

    def test_saida_existente_sem_substituir_nao_apaga(self, tmp_path) -> None:
        a = _arquivo(tmp_path / "a.pdf")
        b = _arquivo(tmp_path / "b.pdf")
        saida = _arquivo(tmp_path / "out.pdf", b"ORIGINAL")
        cliente, t = _cliente((200, {}, PDF))
        with pytest.raises(StirlingError) as erro:
            cliente.merge([str(a), str(b)], str(saida))
        assert erro.value.codigo == "stirling_saida_ocupada"
        assert "substituir" in erro.value.mensagem
        assert t.chamadas == []
        assert saida.read_bytes() == b"ORIGINAL"

    def test_substituir_true_sobrescreve(self, tmp_path) -> None:
        a = _arquivo(tmp_path / "a.pdf")
        b = _arquivo(tmp_path / "b.pdf")
        saida = _arquivo(tmp_path / "out.pdf", b"ORIGINAL")
        cliente, _ = _cliente((200, {}, PDF))
        r = cliente.merge([str(a), str(b)], str(saida), substituir=True)
        assert r["bytes"] == len(PDF)
        assert saida.read_bytes() == PDF

    def test_diretorio_da_saida_inexistente(self, tmp_path) -> None:
        a = _arquivo(tmp_path / "a.pdf")
        b = _arquivo(tmp_path / "b.pdf")
        cliente, t = _cliente((200, {}, PDF))
        with pytest.raises(StirlingError) as erro:
            cliente.merge([str(a), str(b)], str(tmp_path / "sem-dir" / "out.pdf"))
        assert erro.value.codigo == "stirling_diretorio_ausente"
        assert t.chamadas == []

    def test_rejeicao_400_com_mensagem_do_servidor(self, tmp_path) -> None:
        a = _arquivo(tmp_path / "a.pdf")
        b = _arquivo(tmp_path / "b.pdf")
        saida = tmp_path / "out.pdf"
        cliente, _ = _cliente(
            (400, {"Content-Type": "application/json"}, b'{"status":400,"error":"PDF corrompido"}')
        )
        with pytest.raises(StirlingError) as erro:
            cliente.merge([str(a), str(b)], str(saida))
        assert erro.value.codigo == "stirling_pdf_invalido"
        assert "PDF corrompido" in erro.value.mensagem
        assert not saida.exists()

    def test_413_e_gigante_401_e_proibido_500_e_falhou(self, tmp_path) -> None:
        a = _arquivo(tmp_path / "a.pdf")
        b = _arquivo(tmp_path / "b.pdf")
        casos = [
            (413, b"{}", "stirling_gigante"),
            (401, b"{}", "stirling_proibido"),
            (500, b'{"error":"boom"}', "stirling_falhou"),
        ]
        for status, corpo, codigo in casos:
            cliente, _ = _cliente((status, {}, corpo))
            with pytest.raises(StirlingError) as erro:
                cliente.merge([str(a), str(b)], str(tmp_path / f"out{status}.pdf"))
            assert erro.value.codigo == codigo, status

    def test_200_corpo_vazio_nao_vira_arquivo(self, tmp_path) -> None:
        a = _arquivo(tmp_path / "a.pdf")
        b = _arquivo(tmp_path / "b.pdf")
        saida = tmp_path / "out.pdf"
        cliente, _ = _cliente((200, {"Content-Type": "application/pdf"}, b""))
        with pytest.raises(StirlingError) as erro:
            cliente.merge([str(a), str(b)], str(saida))
        assert erro.value.codigo == "stirling_resposta_invalida"
        assert "vazia" in erro.value.mensagem
        assert not saida.exists()

    def test_200_html_nao_vira_arquivo(self, tmp_path) -> None:
        a = _arquivo(tmp_path / "a.pdf")
        b = _arquivo(tmp_path / "b.pdf")
        saida = tmp_path / "out.pdf"
        cliente, _ = _cliente(
            (200, {"Content-Type": "text/html"}, b"<!doctype html><html>...</html>")
        )
        with pytest.raises(StirlingError) as erro:
            cliente.merge([str(a), str(b)], str(saida))
        assert erro.value.codigo == "stirling_resposta_invalida"
        assert not saida.exists()


# ===========================================================================
# Cliente — split
# ===========================================================================

class TestClienteSplit:
    def test_ok_pdf_com_cortes_passados_direto(self, tmp_path) -> None:
        entrada = _arquivo(tmp_path / "doc.pdf", b"doc")
        saida = tmp_path / "pedacos.pdf"
        cliente, t = _cliente((200, {"Content-Type": "application/pdf"}, PDF))
        r = cliente.split(str(entrada), "2,5", str(saida))
        assert r["formato"] == "pdf"
        assert r["cortes"] == "2,5"
        assert saida.read_bytes() == PDF
        assert b'name="pageNumbers"\r\n\r\n2,5' in t.corpo

    def test_resposta_zip_declarada_como_zip(self, tmp_path) -> None:
        entrada = _arquivo(tmp_path / "doc.pdf", b"doc")
        saida = tmp_path / "pedacos.zip"
        # header NÃO diz zip — a mágica PK é quem decide
        cliente, _ = _cliente((200, {"Content-Type": "application/octet-stream"}, ZIP))
        r = cliente.split(str(entrada), "all", str(saida))
        assert r["formato"] == "zip"
        assert saida.read_bytes() == ZIP

    def test_cortes_vazio_vira_all(self, tmp_path) -> None:
        entrada = _arquivo(tmp_path / "doc.pdf", b"doc")
        cliente, t = _cliente((200, {}, PDF))
        cliente.split(str(entrada), "", str(tmp_path / "out.pdf"))
        assert b'name="pageNumbers"\r\n\r\nall' in t.corpo

    def test_resposta_nao_pdf_nao_zip_reprovada(self, tmp_path) -> None:
        entrada = _arquivo(tmp_path / "doc.pdf", b"doc")
        saida = tmp_path / "out.pdf"
        cliente, _ = _cliente((200, {}, b"texto solto sem magica"))
        with pytest.raises(StirlingError) as erro:
            cliente.split(str(entrada), "all", str(saida))
        assert erro.value.codigo == "stirling_resposta_invalida"
        assert not saida.exists()


# ===========================================================================
# Cliente — compress
# ===========================================================================

class TestClienteCompress:
    def test_campos_obrigatorios_sempre_enviados(self, tmp_path) -> None:
        entrada = _arquivo(tmp_path / "doc.pdf", b"x" * 1000)
        saida = tmp_path / "menor.pdf"
        cliente, t = _cliente((200, {"Content-Type": "application/pdf"}, PDF))
        r = cliente.compress(
            str(entrada), str(saida), nivel=6, alvo="50KB", cinza=False
        )
        corpo = t.corpo
        assert b'name="optimizeLevel"\r\n\r\n6' in corpo
        assert b'name="expectedOutputSize"\r\n\r\n50KB' in corpo
        assert b'name="linearize"\r\n\r\nfalse' in corpo
        assert b'name="normalize"\r\n\r\nfalse' in corpo
        assert b'name="grayscale"\r\n\r\nfalse' in corpo
        assert r["arquivo"] == str(saida)

    def test_reducao_honesta_antes_depois(self, tmp_path) -> None:
        entrada = _arquivo(tmp_path / "doc.pdf", b"x" * 1000)
        saida = tmp_path / "menor.pdf"
        corpo_menor = b"%PDF-1.4\n" + b"x" * 391  # 400 bytes
        cliente, _ = _cliente((200, {}, corpo_menor))
        r = cliente.compress(str(entrada), str(saida))
        assert r["bytes_entrada"] == 1000
        assert r["bytes"] == 400
        assert r["reducao_pct"] == 60.0
        assert saida.read_bytes() == corpo_menor

    @pytest.mark.parametrize("nivel", [0, 10, -1, "x"])
    def test_nivel_fora_da_faixa_reprovado(self, tmp_path, nivel) -> None:
        entrada = _arquivo(tmp_path / "doc.pdf", b"doc")
        cliente, t = _cliente((200, {}, PDF))
        with pytest.raises(StirlingError) as erro:
            cliente.compress(str(entrada), str(tmp_path / "out.pdf"), nivel=nivel)
        assert erro.value.codigo == "stirling_parametro_invalido"
        assert t.chamadas == []

    def test_alvo_com_formato_ruim_reprovado(self, tmp_path) -> None:
        entrada = _arquivo(tmp_path / "doc.pdf", b"doc")
        cliente, t = _cliente((200, {}, PDF))
        with pytest.raises(StirlingError) as erro:
            cliente.compress(
                str(entrada), str(tmp_path / "out.pdf"), alvo="grande pra caramba"
            )
        assert erro.value.codigo == "stirling_parametro_invalido"
        assert t.chamadas == []

    def test_alvo_vazio_usa_default_25kb(self, tmp_path) -> None:
        entrada = _arquivo(tmp_path / "doc.pdf", b"doc")
        cliente, t = _cliente((200, {}, PDF))
        cliente.compress(str(entrada), str(tmp_path / "out.pdf"), alvo="")
        assert b'name="expectedOutputSize"\r\n\r\n25KB' in t.corpo

    def test_cinza_liga_grayscale(self, tmp_path) -> None:
        entrada = _arquivo(tmp_path / "doc.pdf", b"doc")
        cliente, t = _cliente((200, {}, PDF))
        cliente.compress(str(entrada), str(tmp_path / "out.pdf"), cinza=True)
        assert b'name="grayscale"\r\n\r\ntrue' in t.corpo


# ===========================================================================
# Fábrica lazy
# ===========================================================================

class TestFabrica:
    def test_cacheada_e_resetavel(self) -> None:
        primeiro = client_padrao()
        assert client_padrao() is primeiro
        resetar_cliente()
        assert client_padrao() is not primeiro

    def test_url_do_env(self, monkeypatch) -> None:
        monkeypatch.setenv("OD_STIRLING_URL", "http://127.0.0.1:9999")
        resetar_cliente()
        assert client_padrao().base_url == "http://127.0.0.1:9999"

    def test_url_lida_do_arquivo_env(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("OD_STIRLING_URL", raising=False)
        env = tmp_path / ".env"
        env.write_text("OD_STIRLING_URL=http://127.0.0.1:8888\n", encoding="utf-8")
        monkeypatch.setattr(stirling_mod, "_ENV_PATH", env)
        resetar_cliente()
        assert client_padrao().base_url == "http://127.0.0.1:8888"

    def test_default_local_quando_sem_config(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("OD_STIRLING_URL", raising=False)
        monkeypatch.setattr(stirling_mod, "_ENV_PATH", tmp_path / ".env")  # não existe
        resetar_cliente()
        assert client_padrao().base_url == URL_PADRAO


# ===========================================================================
# Actions — erro honesto, parse de lista, fábrica
# ===========================================================================

def _com_fabrica(cliente: Any, monkeypatch) -> None:
    monkeypatch.setattr(stirling_mod, "client_padrao", lambda: cliente)


class TestActionsStirling:
    def test_status_ok(self, monkeypatch) -> None:
        cliente, _ = _cliente((200, {}, b'{"version":"2.13.1","status":"UP"}'))
        _com_fabrica(cliente, monkeypatch)
        r = stirling_status()
        assert r["ok"] is True
        assert r["versao"] == "2.13.1" and r["estado"] == "UP"

    def test_status_fora_do_ar_degrada_a_action(self, monkeypatch) -> None:
        cliente, _ = _cliente(urllib.error.URLError("caiu"))
        _com_fabrica(cliente, monkeypatch)
        r = stirling_status()
        assert r["ok"] is False
        assert r["error"] == "stirling_indisponivel"
        assert "127.0.0.1" in r["message"] or "inacessível" in r["message"]

    def test_merge_action_faz_parse_da_lista_com_espacos(
        self, tmp_path, monkeypatch
    ) -> None:
        a = _arquivo(tmp_path / "a.pdf", b"AAA")
        b = _arquivo(tmp_path / "b.pdf", b"BBB")
        saida = tmp_path / "junto.pdf"
        cliente, t = _cliente((200, {}, PDF))
        _com_fabrica(cliente, monkeypatch)
        r = stirling_merge(arquivos=f"{a} , {b}", saida=str(saida))
        assert r["ok"] is True and r["entradas"] == 2
        assert saida.read_bytes() == PDF
        assert len(t.chamadas) == 1

    def test_merge_action_um_so_arquivo_reprovado(
        self, tmp_path, monkeypatch
    ) -> None:
        a = _arquivo(tmp_path / "a.pdf")
        cliente, _ = _cliente((200, {}, PDF))
        _com_fabrica(cliente, monkeypatch)
        r = stirling_merge(arquivos=str(a), saida=str(tmp_path / "out.pdf"))
        assert r["ok"] is False
        assert r["error"] == "stirling_parametro_invalido"

    def test_split_e_compress_actions_ok(self, tmp_path, monkeypatch) -> None:
        entrada = _arquivo(tmp_path / "doc.pdf", b"x" * 500)
        cliente, _ = _cliente((200, {}, PDF))
        _com_fabrica(cliente, monkeypatch)
        rs = stirling_split(
            arquivo=str(entrada), saida=str(tmp_path / "p.pdf"), cortes="1"
        )
        rc = stirling_compress(
            arquivo=str(entrada), saida=str(tmp_path / "c.pdf"), nivel=3
        )
        assert rs["ok"] is True and rs["formato"] == "pdf"
        assert rc["ok"] is True and rc["bytes_entrada"] == 500

    def test_saida_ocupada_na_action_e_honesta(self, tmp_path, monkeypatch) -> None:
        a = _arquivo(tmp_path / "a.pdf")
        b = _arquivo(tmp_path / "b.pdf")
        saida = _arquivo(tmp_path / "out.pdf", b"DO DONO")
        cliente, _ = _cliente((200, {}, PDF))
        _com_fabrica(cliente, monkeypatch)
        r = stirling_merge(arquivos=f"{a},{b}", saida=str(saida))
        assert r["ok"] is False
        assert r["error"] == "stirling_saida_ocupada"
        assert saida.read_bytes() == b"DO DONO"


# ===========================================================================
# Catálogo — 4 actions, categoria stirling, permissão
# ===========================================================================

STIRLING_ACOES = {"stirling_status", "stirling_merge", "stirling_split", "stirling_compress"}


class TestCatalogoStirling:
    def test_quatro_actions_na_categoria_stirling(self) -> None:
        da_ferramenta = [s for s in CATALOG if s["category"] == "stirling"]
        assert {s["name"] for s in da_ferramenta} == STIRLING_ACOES
        assert len(da_ferramenta) == 4

    def test_schemas_dos_params(self) -> None:
        por_nome = {s["name"]: s for s in CATALOG}
        assert por_nome["stirling_status"]["params"] == {}
        assert por_nome["stirling_merge"]["params"].get("required") == ["arquivos", "saida"]
        assert por_nome["stirling_merge"]["params"]["properties"]["substituir"]["default"] is False
        assert por_nome["stirling_split"]["params"]["properties"]["cortes"]["default"] == "all"
        assert por_nome["stirling_compress"]["params"]["properties"]["nivel"]["default"] == 4
        assert por_nome["stirling_compress"]["params"]["properties"]["alvo"]["default"] == "25KB"

    @pytest.mark.asyncio
    async def test_papel_user_negado_por_permissao(self) -> None:
        """Pipeline de documentos é do admin: papel comum não alcança."""
        registry = build_registry(security=SecurityManager(mode="strict"))
        params = {
            "stirling_status": {},
            "stirling_merge": {"arquivos": "a.pdf,b.pdf", "saida": "out.pdf"},
            "stirling_split": {"arquivo": "a.pdf", "saida": "out.pdf"},
            "stirling_compress": {"arquivo": "a.pdf", "saida": "out.pdf"},
        }
        for nome in sorted(STIRLING_ACOES):
            result = await registry.execute(nome, params=params[nome], role="user")
            assert result.status == "denied", nome
            assert result.denied_by == "permission", nome


__all__ = [
    "TestMontaMultipart",
    "TestTransporteUrllib",
    "TestClienteStatus",
    "TestClienteMerge",
    "TestClienteSplit",
    "TestClienteCompress",
    "TestFabrica",
    "TestActionsStirling",
    "TestCatalogoStirling",
]
