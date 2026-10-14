"""
OMEGA DRAKON • TESTES
Fila de downloads resumable (core/downloads.py + /admin/downloads*) —
Parte D do Project NOMAD (2026-10-14).

Cobre:
- Fila: validação de URL/destino (só dentro da raiz), dedup por
  URL+destino, retomada por Range a partir do `.part`, reinício quando o
  servidor ignora Range, 416, retry com backoff, erro permanente (404 e
  sha256 divergente) sem queimar tentativa, cancelamento preservando o
  parcial, stop() re-enfileirando o que estava em voo, histórico
  recortado, restauração de estado no boot e eventos por assinante.
- API: 401 sem credencial, 201 na criação / 200 no dedup, 400 de
  validação, 404 de job inexistente, 409 de delete em job ativo, 503 sem
  fila, resumo no /dashboard/stats, seção no painel e SSE ao vivo.

Rede NENHUMA: o opener é injetado (respostas falsas); o SSE é lido por
socket cru contra o servidor de teste.
"""

from __future__ import annotations

import hashlib
import io
import json
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.downloads import (  # noqa: E402
    AGUARDANDO,
    BAIXANDO,
    CANCELADO,
    CONCLUIDO,
    ERRO,
    NA_FILA,
    DownloadQueue,
)


# ---------------------------------------------------------------------------#
# Fakes (sem rede)                                                            #
# ---------------------------------------------------------------------------#
class _Resp:
    """Resposta falsa no formato que o _transferir enxerga."""

    def __init__(self, conteudo: bytes = b"", *, status: int = 200,
                 cabecais: dict | None = None, pedacos: list | None = None,
                 ao_ler=None) -> None:
        self.status = status
        self.headers = dict(cabecais or {})
        if pedacos is not None:
            self._pedacos = list(pedacos)
        else:
            self._pedacos = [conteudo] if conteudo else []
            if conteudo and "Content-Length" not in self.headers:
                self.headers["Content-Length"] = str(len(conteudo))
        self._ao_ler = ao_ler
        self.fechado = False

    def read(self, n: int = -1) -> bytes:
        if not self._pedacos:
            return b""
        if self._ao_ler is not None:
            self._ao_ler(len(self._pedacos))
        return self._pedacos.pop(0)

    def getcode(self) -> int:
        return self.status

    def close(self) -> None:
        self.fechado = True


def _erro_http(url: str, codigo: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, codigo, "erro", {}, io.BytesIO(b""))


def _mk(tmp_path: Path, opener, **kw) -> DownloadQueue:
    kw.setdefault("backoff_base_s", 0.01)
    return DownloadQueue(
        base_dir=tmp_path / "dl",
        state_path=tmp_path / "fila.json",
        opener=opener,
        **kw,
    )


def _parte(caminho: Path) -> Path:
    return Path(str(caminho) + ".part")


# ---------------------------------------------------------------------------#
# Enfileiramento e validação                                                  #
# ---------------------------------------------------------------------------#
class TestEnfileirar:
    @pytest.mark.parametrize("url", ["", "ftp://x/a.bin", "sem-esquema/a.bin",
                                     "file:///etc/passwd"])
    def test_url_invalida(self, tmp_path: Path, url: str) -> None:
        fila = _mk(tmp_path, lambda req, timeout=None: _Resp(b"x"))
        with pytest.raises(ValueError, match="url_invalida"):
            fila.enqueue(url)

    @pytest.mark.parametrize("destino", ["../fora.bin", "/etc/passwd",
                                         "sub/../../escape.bin"])
    def test_destino_fora_da_raiz(self, tmp_path: Path, destino: str) -> None:
        fila = _mk(tmp_path, lambda req, timeout=None: _Resp(b"x"))
        with pytest.raises(ValueError, match="destino_invalido"):
            fila.enqueue("https://exemplo.test/a.bin", destino)

    def test_nome_e_caminho_vem_da_url(self, tmp_path: Path) -> None:
        fila = _mk(tmp_path, lambda req, timeout=None: _Resp(b"x"))
        job, criado = fila.enqueue(
            "https://exemplo.test/pesos/modelo-7b.gguf?v=2")
        assert criado is True
        assert job.nome == "modelo-7b.gguf"
        assert job.destino.endswith("modelo-7b.gguf")
        assert str(fila.raiz) in job.destino
        assert job.status == NA_FILA

    def test_destino_com_subpasta(self, tmp_path: Path) -> None:
        fila = _mk(tmp_path, lambda req, timeout=None: _Resp(b"x"))
        job, _ = fila.enqueue("https://exemplo.test/a.bin", "zim/wiki.zim")
        assert job.destino.endswith("zim/wiki.zim")

    def test_dedup_mesma_url_devolve_o_mesmo_job(self, tmp_path: Path) -> None:
        fila = _mk(tmp_path, lambda req, timeout=None: _Resp(b"x"))
        primeiro, criado1 = fila.enqueue("https://exemplo.test/a.bin")
        segundo, criado2 = fila.enqueue("https://exemplo.test/a.bin")
        assert (criado1, criado2) == (True, False)
        assert segundo.id == primeiro.id
        # URL diferente não deduplica
        terceiro, _ = fila.enqueue("https://exemplo.test/b.bin")
        assert terceiro.id != primeiro.id
        assert len(fila.lista()) == 2

    def test_sem_worker_o_job_fica_na_fila(self, tmp_path: Path) -> None:
        fila = _mk(tmp_path, lambda req, timeout=None: pytest.fail("sem worker"))
        fila.enqueue("https://exemplo.test/a.bin")
        resumo = fila.snapshot()
        assert resumo["na_fila"] == 1 and resumo["ativas"] == 1
        assert resumo["total"] == 1


# ---------------------------------------------------------------------------#
# Transferência, retomada e integridade                                        #
# ---------------------------------------------------------------------------#
class TestTransferencia:
    def test_conclusao_simples_com_sha(self, tmp_path: Path) -> None:
        conteudo = b"conteudo-da-casa" * 100
        fila = _mk(tmp_path, lambda req, timeout=None: _Resp(conteudo))
        job, _ = fila.enqueue(
            "https://exemplo.test/doc.bin",
            sha256=hashlib.sha256(conteudo).hexdigest())
        fila.start()
        fila.aguardar(job.id, timeout=10)
        destino = Path(job.destino)
        assert job.status == CONCLUIDO
        assert destino.read_bytes() == conteudo
        assert not _parte(destino).exists()
        assert job.sha256_real == hashlib.sha256(conteudo).hexdigest()
        assert job.tentativas == 1
        assert job.bytes_feitos == len(conteudo)

    def test_sha256_divergente_e_erro_permanente(self, tmp_path: Path) -> None:
        fila = _mk(tmp_path, lambda req, timeout=None: _Resp(b"conteudo"))
        job, _ = fila.enqueue("https://exemplo.test/doc.bin",
                              sha256="0" * 64)   # sha errado de propósito
        fila.start()
        fila.aguardar(job.id, timeout=10)
        assert job.status == ERRO
        assert job.tentativas == 1          # não queima retry em erro certo
        assert "sha256 divergente" in job.erro
        assert not _parte(Path(job.destino)).exists()

    def test_sha256_formato_invalido(self, tmp_path: Path) -> None:
        fila = _mk(tmp_path, lambda req, timeout=None: _Resp(b"x"))
        with pytest.raises(ValueError, match="sha256_invalido"):
            fila.enqueue("https://exemplo.test/a.bin", sha256="abc123")

    def test_retoma_com_range_pelo_part(self, tmp_path: Path) -> None:
        fila = _mk(tmp_path, lambda req, timeout=None: _Resp(
            b"conteudo!", status=206,
            cabecais={"Content-Range": "bytes 4-12/13"}))
        job, _ = fila.enqueue("https://exemplo.test/modelo.bin")
        _parte(Path(job.destino)).write_bytes(b"OLA ")   # parcial prévio
        fila.start()
        fila.aguardar(job.id, timeout=10)
        assert job.status == CONCLUIDO
        assert Path(job.destino).read_bytes() == b"OLA conteudo!"
        assert job.sha256_real == hashlib.sha256(b"OLA conteudo!").hexdigest()

    def test_range_vai_no_header(self, tmp_path: Path) -> None:
        pedidos: list = []
        def opener(req, timeout=None):
            pedidos.append(req.get_header("Range"))
            return _Resp(b"resto", status=206,
                         cabecais={"Content-Range": "bytes 8-11/12"})
        fila = _mk(tmp_path, opener)
        job, _ = fila.enqueue("https://exemplo.test/m.bin")
        _parte(Path(job.destino)).write_bytes(b"12345678")
        fila.start()
        fila.aguardar(job.id, timeout=10)
        assert pedidos == ["bytes=8-"]

    def test_servidor_sem_range_reinicia_do_zero(self, tmp_path: Path) -> None:
        # Servidor ignorou o Range (200) — o parcial NÃO pode entrar misturado.
        fila = _mk(tmp_path, lambda req, timeout=None: _Resp(b"arquivo novo"))
        job, _ = fila.enqueue("https://exemplo.test/m.bin")
        _parte(Path(job.destino)).write_bytes(b"PARCIAL VELHO ")
        fila.start()
        fila.aguardar(job.id, timeout=10)
        assert job.status == CONCLUIDO
        assert Path(job.destino).read_bytes() == b"arquivo novo"

    def test_416_reinicia_uma_vez(self, tmp_path: Path) -> None:
        chamadas: list = []
        def opener(req, timeout=None):
            chamadas.append(req.get_header("Range"))
            if req.get_header("Range"):
                raise _erro_http(req.full_url, 416)
            return _Resp(b"conteudo novo")
        fila = _mk(tmp_path, opener)
        job, _ = fila.enqueue("https://exemplo.test/m.bin")
        _parte(Path(job.destino)).write_bytes(b"antigo")
        fila.start()
        fila.aguardar(job.id, timeout=10)
        assert chamadas == ["bytes=6-", None]
        assert Path(job.destino).read_bytes() == b"conteudo novo"
        assert job.status == CONCLUIDO

    def test_404_nao_tenta_de_novo(self, tmp_path: Path) -> None:
        def opener(req, timeout=None):
            raise _erro_http(req.full_url, 404)
        fila = _mk(tmp_path, opener, max_tentativas=5)
        job, _ = fila.enqueue("https://exemplo.test/falta.bin")
        fila.start()
        fila.aguardar(job.id, timeout=10)
        assert job.status == ERRO
        assert job.tentativas == 1
        assert job.erro == "http_404"

    def test_retry_transitorio_ate_concluir(self, tmp_path: Path) -> None:
        chamadas = {"n": 0}
        def opener(req, timeout=None):
            chamadas["n"] += 1
            if chamadas["n"] == 1:
                raise OSError("conexao resetada")
            return _Resp(b"ok no retry")
        fila = _mk(tmp_path, opener, max_tentativas=3)
        job, _ = fila.enqueue("https://exemplo.test/flaky.bin")
        fila.start()
        fila.aguardar(job.id, timeout=10)
        assert job.status == CONCLUIDO
        assert job.tentativas == 2
        assert Path(job.destino).read_bytes() == b"ok no retry"

    def test_retry_esgotado_vira_erro(self, tmp_path: Path) -> None:
        def opener(req, timeout=None):
            raise urllib.error.URLError("conexao recusada")
        fila = _mk(tmp_path, opener, max_tentativas=2)
        job, _ = fila.enqueue("https://exemplo.test/morta.bin")
        fila.start()
        fila.aguardar(job.id, timeout=10)
        assert job.status == ERRO
        assert job.tentativas == 2
        assert "conexao recusada" in job.erro
        # já terminou: o próximo enqueue é um job novo (dedup só é ativo)
        outro, criado = fila.enqueue("https://exemplo.test/morta.bin")
        assert criado is True and outro.id != job.id

    def test_status_aguardando_aparece_no_meio(self, tmp_path: Path) -> None:
        """O backoff é visível: entre tentativas o job fica 'aguardando'."""
        chamadas = {"n": 0}
        def opener(req, timeout=None):
            chamadas["n"] += 1
            if chamadas["n"] == 1:
                raise OSError("timeout")
            return _Resp(b"deu")
        fila = _mk(tmp_path, opener, max_tentativas=3, backoff_base_s=0.3)
        job, _ = fila.enqueue("https://exemplo.test/devagar.bin")
        fila.start()
        # espera a 1ª falha → aguardando (com proximo_retry marcado)
        prazo = time.time() + 5
        while job.status != AGUARDANDO and time.time() < prazo:
            time.sleep(0.01)
        assert job.status == AGUARDANDO
        assert job.proximo_retry is not None
        assert job.proximo_retry > time.time() - 1
        fila.aguardar(job.id, timeout=10)
        assert job.status == CONCLUIDO

    def test_stream_cortado_e_transitorio(self, tmp_path: Path) -> None:
        fila = _mk(tmp_path, lambda req, timeout=None: _Resp(
            b"x" * 40, cabecais={"Content-Length": "100"}),
            max_tentativas=1)
        job, _ = fila.enqueue("https://exemplo.test/cortado.bin")
        fila.start()
        fila.aguardar(job.id, timeout=10)
        assert job.status == ERRO
        assert "stream cortado" in job.erro


# ---------------------------------------------------------------------------#
# Cancelamento, stop e remoção                                                #
# ---------------------------------------------------------------------------#
class TestControle:
    def test_cancel_antes_de_baixar(self, tmp_path: Path) -> None:
        fila = _mk(tmp_path, lambda req, timeout=None: pytest.fail("baixou"))
        job, _ = fila.enqueue("https://exemplo.test/a.bin")
        cancelado = fila.cancelar(job.id)
        assert cancelado.status == CANCELADO
        assert fila.aguardar(job.id, timeout=1).status == CANCELADO

    def test_cancel_no_meio_preserva_o_part(self, tmp_path: Path) -> None:
        contexto: dict = {}
        def opener(req, timeout=None):
            def ao_ler(restantes: int):
                if restantes == 2:   # 2º bloco: o dono cancela
                    contexto["fila"].cancelar(contexto["id"])
            return _Resp(pedacos=[b"A" * 100, b"B" * 100, b"C" * 100],
                         cabecais={"Content-Length": "300"}, ao_ler=ao_ler)
        fila = _mk(tmp_path, opener)
        job, _ = fila.enqueue("https://exemplo.test/grande.bin")
        contexto.update(fila=fila, id=job.id)
        fila.start()
        fila.aguardar(job.id, timeout=10)
        assert job.status == CANCELADO
        destino = Path(job.destino)
        assert not destino.exists()                  # não terminou
        assert _parte(destino).read_bytes() == b"A" * 100 + b"B" * 100
        # re-enfileirar a mesma URL retoma do parcial (dedup libera no fim)
        job2, criado = fila.enqueue("https://exemplo.test/grande.bin")
        assert criado is True and job2.id != job.id
        assert job2.bytes_feitos == 200              # já enxerga o parcial

    def test_stop_reenfileira_o_que_estava_em_voo(self, tmp_path: Path) -> None:
        fila = _mk(tmp_path, lambda req, timeout=None: _Resp(
            pedacos=[b"x" * 4096] * 100000))
        job, _ = fila.enqueue("https://exemplo.test/baixao.bin")
        fila.start()
        prazo = time.time() + 10
        while job.bytes_feitos == 0 and time.time() < prazo:
            time.sleep(0.01)
        assert job.bytes_feitos > 0
        fila.stop(timeout=10)
        # parcial preservado e o job de volta para a fila (não cancelado)
        assert job.status == NA_FILA
        assert _parte(Path(job.destino)).exists()

    def test_remover_so_aceita_terminal(self, tmp_path: Path) -> None:
        fila = _mk(tmp_path, lambda req, timeout=None: _Resp(b"x"))
        job, _ = fila.enqueue("https://exemplo.test/a.bin")
        with pytest.raises(ValueError, match="job_ativo"):
            fila.remover(job.id)
        fila.cancelar(job.id)
        fila.remover(job.id)
        assert fila.lista() == []
        with pytest.raises(ValueError, match="job_inexistente"):
            fila.remover(job.id)

    def test_cancelar_job_inexistente(self, tmp_path: Path) -> None:
        fila = _mk(tmp_path, lambda req, timeout=None: _Resp(b"x"))
        with pytest.raises(ValueError, match="job_inexistente"):
            fila.cancelar("dl-9999")


# ---------------------------------------------------------------------------#
# Estado persistido, histórico e eventos                                      #
# ---------------------------------------------------------------------------#
class TestEstadoEEventos:
    def test_restaura_baixando_como_na_fila(self, tmp_path: Path) -> None:
        base = tmp_path / "dl"
        base.mkdir(parents=True)
        destino = base / "modelo.bin"
        _parte(destino).write_bytes(b"1234567")      # 7 bytes em disco
        estado = {"versao": 1, "jobs": [{
            "id": "dl-0007", "url": "https://exemplo.test/modelo.bin",
            "destino": str(destino), "nome": "modelo.bin",
            "status": BAIXANDO, "bytes_feitos": 0,
            "criado_em": 1.0, "atualizado_em": 2.0,
        }]}
        (tmp_path / "fila.json").write_text(json.dumps(estado),
                                            encoding="utf-8")
        fila = _mk(tmp_path, lambda req, timeout=None: pytest.fail("sem worker"))
        job = fila.get("dl-0007")
        assert job is not None
        assert job.status == NA_FILA                 # boot re-enfileira
        assert job.bytes_feitos == 7                 # parcial vale
        assert job.cancelar is False

    def test_estado_corrompio_nao_quebra_o_boot(self, tmp_path: Path) -> None:
        (tmp_path / "fila.json").write_text("nao e json", encoding="utf-8")
        fila = _mk(tmp_path, lambda req, timeout=None: _Resp(b"x"))
        assert fila.lista() == []

    def test_estado_e_escrito_atomicamente(self, tmp_path: Path) -> None:
        fila = _mk(tmp_path, lambda req, timeout=None: _Resp(b"x"))
        fila.enqueue("https://exemplo.test/a.bin")
        bruto = json.loads((tmp_path / "fila.json").read_text("utf-8"))
        assert bruto["versao"] == 1
        assert bruto["jobs"][0]["status"] == NA_FILA
        assert not (tmp_path / "fila.json.tmp").exists()

    def test_historico_e_recortado(self, tmp_path: Path) -> None:
        fila = _mk(tmp_path, lambda req, timeout=None: _Resp(b"x"),
                   historico_max=2)
        fila.start()
        ids = []
        for n in range(3):
            job, _ = fila.enqueue(f"https://exemplo.test/a{n}.bin")
            ids.append(job.id)
            fila.aguardar(job.id, timeout=10)
        sobraram = [j["id"] for j in fila.lista()]
        assert sobraram == ids[1:]                    # os 2 mais novos

    def test_snapshot_conta_tudo(self, tmp_path: Path) -> None:
        fila = _mk(tmp_path, lambda req, timeout=None: _Resp(b"x"))
        a, _ = fila.enqueue("https://exemplo.test/a.bin")
        fila.enqueue("https://exemplo.test/b.bin")
        fila.cancelar(a.id)
        s = fila.snapshot()
        assert s["total"] == 2
        assert s["na_fila"] == 1
        assert s["cancelados"] == 1
        assert s["ativas"] == 1
        assert s["bytes_baixados"] == 0

    def test_subscribe_recebe_os_eventos(self, tmp_path: Path) -> None:
        fila = _mk(tmp_path, lambda req, timeout=None: _Resp(b"ping"))
        eventos, cancela = fila.subscribe()
        job, _ = fila.enqueue("https://exemplo.test/a.bin")
        fila.start()
        fila.aguardar(job.id, timeout=10)
        vistos = []
        prazo = time.time() + 5
        while time.time() < prazo:
            try:
                pacote = eventos.get(timeout=0.5)
            except Exception:
                break
            vistos.append(pacote)
            if pacote["job"]["status"] == CONCLUIDO:
                break
        assert any(p["evento"] == "estado" for p in vistos)
        assert vistos[-1]["job"]["status"] == CONCLUIDO
        cancela()
        # depois de cancelar, nada mais é publicado para esta assinatura
        fila.enqueue("https://exemplo.test/b.bin")
        assert eventos.empty()

    def test_overflow_nao_trava_o_worker(self, tmp_path: Path) -> None:
        """Assinante lento: o evento mais antigo sai e o final sempre cabe."""
        fila = _mk(tmp_path, lambda req, timeout=None: _Resp(b"x"))
        eventos, cancela = fila.subscribe()
        for n in range(300):                          # > maxsize (256)
            job, _ = fila.enqueue(f"https://exemplo.test/{n}.bin")
        cancela()
        assert eventos.qsize() <= 256
        assert job.status == NA_FILA


# ---------------------------------------------------------------------------#
# API REST + SSE                                                              #
# ---------------------------------------------------------------------------#
def _request(port: int, method: str, path: str, api_key=None, body=None):
    url = f"http://127.0.0.1:{port}{path}"
    dados = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json"} if dados else {}
    if api_key:
        hdrs["X-API-Key"] = api_key
    req = urllib.request.Request(url, data=dados, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _json_body(resposta) -> dict:
    """Corpo (bytes) de _request → dict."""
    return json.loads(resposta.decode() or "{}")


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
def srv_downloads(serve, tmp_path: Path):
    from integrations.api import APIConfig

    fila = DownloadQueue(base_dir=tmp_path / "dl",
                         state_path=tmp_path / "fila.json",
                         opener=lambda req, timeout=None: _Resp(b"ok"))
    cfg = APIConfig(port=0, rate_limit_max=0, api_key="segredo123",
                    auth_all=True, downloads=fila)
    servidor = serve(None, config=cfg)
    yield servidor, fila
    fila.stop()


class TestDownloadAPI:
    def test_sem_credencial_leva_401(self, srv_downloads) -> None:
        servidor, _ = srv_downloads
        status, _ = _request(servidor.bound_port, "GET", "/admin/downloads")
        assert status == 401
        status, _ = _request(servidor.bound_port, "POST", "/admin/downloads",
                             body={"url": "https://exemplo.test/a.bin"})
        assert status == 401

    def test_cria_201_e_dedup_200(self, srv_downloads) -> None:
        servidor, _ = srv_downloads
        status, corpo = _request(
            servidor.bound_port, "POST", "/admin/downloads",
            api_key="segredo123", body={"url": "https://exemplo.test/a.bin"})
        assert status == 201, corpo
        data = _json_body(corpo)
        assert data["job"]["id"] == "dl-0001"
        assert data["duplicado"] is False

        status, corpo = _request(
            servidor.bound_port, "POST", "/admin/downloads",
            api_key="segredo123", body={"url": "https://exemplo.test/a.bin"})
        assert status == 200
        data = _json_body(corpo)
        assert data["duplicado"] is True
        assert data["job"]["id"] == "dl-0001"

    def test_url_invalida_400(self, srv_downloads) -> None:
        servidor, _ = srv_downloads
        status, corpo = _request(servidor.bound_port, "POST",
                                 "/admin/downloads", api_key="segredo123",
                                 body={"url": "nao-e-url"})
        assert status == 400
        assert _json_body(corpo)["error"] == "url_invalida"

    def test_lista_detalhe_e_404(self, srv_downloads) -> None:
        servidor, _ = srv_downloads
        _request(servidor.bound_port, "POST", "/admin/downloads",
                 api_key="segredo123", body={"url": "https://exemplo.test/a"})
        status, corpo = _request(servidor.bound_port, "GET",
                                 "/admin/downloads", api_key="segredo123")
        data = _json_body(corpo)
        assert status == 200 and data["resumo"]["na_fila"] == 1

        status, corpo = _request(servidor.bound_port, "GET",
                                 "/admin/downloads/dl-0001",
                                 api_key="segredo123")
        assert status == 200
        assert _json_body(corpo)["job"]["status"] == NA_FILA

        status, _ = _request(servidor.bound_port, "GET",
                             "/admin/downloads/dl-9999",
                             api_key="segredo123")
        assert status == 404

    def test_cancela_e_depois_remove(self, srv_downloads) -> None:
        servidor, _ = srv_downloads
        _request(servidor.bound_port, "POST", "/admin/downloads",
                 api_key="segredo123", body={"url": "https://exemplo.test/a"})
        status, corpo = _request(servidor.bound_port, "POST",
                                 "/admin/downloads/dl-0001/cancel",
                                 api_key="segredo123")
        assert status == 200
        assert _json_body(corpo)["job"]["status"] == CANCELADO

        status, corpo = _request(servidor.bound_port, "DELETE",
                                 "/admin/downloads/dl-0001",
                                 api_key="segredo123")
        assert status == 200
        status, _ = _request(servidor.bound_port, "DELETE",
                             "/admin/downloads/dl-0001",
                             api_key="segredo123")
        assert status == 404

    def test_delete_de_job_ativo_409(self, srv_downloads) -> None:
        servidor, _ = srv_downloads
        _request(servidor.bound_port, "POST", "/admin/downloads",
                 api_key="segredo123", body={"url": "https://exemplo.test/a"})
        status, corpo = _request(servidor.bound_port, "DELETE",
                                 "/admin/downloads/dl-0001",
                                 api_key="segredo123")
        assert status == 409
        assert _json_body(corpo)["error"] == "job_ativo"

    def test_sem_fila_503(self, serve) -> None:
        from integrations.api import APIConfig
        servidor = serve(None, config=APIConfig(
            port=0, rate_limit_max=0, api_key="segredo123", auth_all=True))
        status, corpo = _request(servidor.bound_port, "GET",
                                 "/admin/downloads", api_key="segredo123")
        assert status == 503
        assert _json_body(corpo)["error"] == "downloads_indisponivel"

    def test_dashboard_stats_traz_o_resumo(self, srv_downloads) -> None:
        servidor, fila = srv_downloads
        fila.enqueue("https://exemplo.test/a.bin")
        status, corpo = _request(servidor.bound_port, "GET",
                                 "/dashboard/stats", api_key="segredo123")
        data = _json_body(corpo)
        assert status == 200
        assert data["downloads"]["na_fila"] == 1
        assert data["downloads"]["ativas"] == 1

    def test_painel_traz_a_secao_de_downloads(self, srv_downloads) -> None:
        servidor, _ = srv_downloads
        status, corpo = _request(servidor.bound_port, "GET", "/admin",
                                 api_key="segredo123")
        html = corpo.decode()
        assert status == 200
        assert "Downloads (fila resumable)" in html
        assert "/admin/downloads/events" in html
        assert "dlLoad" in html


class TestDownloadSSE:
    def test_snapshot_e_evento_ao_vivo(self, srv_downloads) -> None:
        """Conexão SSE entrega a fila inteira e depois empurra transições."""
        servidor, fila = srv_downloads
        primeiro, _ = fila.enqueue("https://exemplo.test/a.bin")
        with socket.create_connection(("127.0.0.1", servidor.bound_port),
                                      timeout=5) as conexao:
            conexao.settimeout(5)
            conexao.sendall(
                ("GET /admin/downloads/events HTTP/1.1\r\n"
                 "Host: 127.0.0.1\r\n"
                 "X-API-Key: segredo123\r\n"
                 "Connection: close\r\n\r\n").encode())
            buffer = b""
            while b"data:" not in buffer:
                bloco = conexao.recv(4096)
                if not bloco:
                    break
                buffer += bloco
            assert b"text/event-stream" in buffer
            linhas = [l for l in buffer.split(b"\n") if l.startswith(b"data: ")]
            pacote = json.loads(linhas[0][6:])
            assert pacote["evento"] == "snapshot"
            assert pacote["jobs"][0]["id"] == primeiro.id
            assert pacote["resumo"]["na_fila"] == 1

            # enfileira DEPOIS de conectado → o estado chega ao vivo
            segundo, _ = fila.enqueue("https://exemplo.test/b.bin")
            while buffer.count(b"data:") < 2:
                bloco = conexao.recv(4096)
                if not bloco:
                    break
                buffer += bloco
            linhas = [l for l in buffer.split(b"\n") if l.startswith(b"data: ")]
            pacote = json.loads(linhas[1][6:])
            assert pacote["evento"] == "estado"
            assert pacote["job"]["id"] == segundo.id

    def test_sem_credencial_o_stream_nao_abre(self, srv_downloads) -> None:
        servidor, _ = srv_downloads
        with socket.create_connection(("127.0.0.1", servidor.bound_port),
                                      timeout=5) as conexao:
            conexao.settimeout(5)
            conexao.sendall(
                ("GET /admin/downloads/events HTTP/1.1\r\n"
                 "Host: 127.0.0.1\r\n"
                 "Connection: close\r\n\r\n").encode())
            buffer = b""
            while b"data:" not in buffer and b"\r\n\r\n" not in buffer:
                bloco = conexao.recv(4096)
                if not bloco:
                    break
                buffer += bloco
            assert b"data:" not in buffer
            assert b"401" in buffer.split(b"\r\n")[0]
