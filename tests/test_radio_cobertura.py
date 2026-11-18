"""
OMEGA DRAKON • PYTEST
Módulo: tests/test_radio_cobertura.py
Descrição: recuperação da dívida de cobertura do cluster de rádio —
           integrations/radio_pro.py, integrations/radio_link.py e
           integrations/radio_cantores.py (linhas perdidas desde 02/11).

           Os testes miram os ramos que a suíte não alcança: erros de
           arquivo/banco, fontes de letra fora do ar, AzuraCast e MariaDB
           dublês, parser do INSERT, worker do link (extração, pipeline,
           trava, CLI) e o registro de cantores indesejados. O que já está
           coberto em tests/test_radio_pro.py, tests/test_radio_link.py e
           tests/test_radio_cantores.py não é repetido aqui.

Segurança (regra da tarefa — NENHUM stream/servidor real e NENHUMA rede):
  - `urlopen`, `subprocess.run` são substituídos por dublês via
    `monkeypatch` — nenhuma requisição sai da máquina;
  - `AZURA_KEY` fica vazia e os tokens do Telegram saem do ambiente por
    teste, então um caminho esquecido não fala com a rádio nem com o bot;
  - temporizadores são valores fixos (`datetime`/`time.time` locais);
  - TODO arquivo é gravado apenas em `tmp_path` (acervo, lista, registro,
    cache, banco de pedidos, logs e diretório isolado do worker).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import fcntl
import json
import sqlite3
import subprocess
import time
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from integrations import radio_cantores as rc
from integrations import radio_link as rl
from integrations import radio_pro as rp


# ---------------------------------------------------------------------------
#  Apoio — nada abaixo toca rede, acervo real ou data/
# ---------------------------------------------------------------------------

CAMINHO = "acervo/Gospel/Fernandinho - Todas as Coisas.mp3"
VIDEO = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
LISTA = "https://www.youtube.com/playlist?list=PL1234567890abcdef"
UID = "abc123abc123abc123abc123"


class _Resposta:
    """Dublê de resposta do `urlopen`: contexto, status e corpo."""

    def __init__(self, corpo: bytes, status: int = 200) -> None:
        self._corpo = corpo
        self.status = status

    def read(self) -> bytes:
        return self._corpo

    def __enter__(self) -> "_Resposta":
        return self

    def __exit__(self, *_exc) -> bool:
        return False


def _urlopen(corpo: bytes = b"{}", status: int = 200,
             falha: BaseException | None = None):
    """Fábrica de `urlopen` dublê: devolve o corpo ou levanta a falha."""

    def _falso(_req, timeout=None):
        if falha is not None:
            raise falha
        return _Resposta(corpo, status)

    return _falso


def _http_erro(codigo: int) -> HTTPError:
    return HTTPError("https://exemplo.test/x", codigo, "erro", {}, None)


def _criar_acervo(banco: Path,
                  musicas: list[tuple[str, str, str, str]] | None = None
                  ) -> Path:
    """acervo.db de mentira com o MESMO esquema do pipeline (musica.py)."""
    conn = sqlite3.connect(str(banco))
    conn.execute("CREATE TABLE musicas (caminho TEXT PRIMARY KEY,"
                 " artista TEXT, titulo TEXT, genero TEXT)")
    for caminho, artista, titulo, genero in (musicas or [
        (CAMINHO, "Fernandinho", "Todas as Coisas", "Gospel"),
    ]):
        conn.execute("INSERT INTO musicas (caminho, artista, titulo,"
                     " genero) VALUES (?, ?, ?, ?)",
                     (caminho, artista, titulo, genero))
    conn.commit()
    conn.close()
    return banco


@pytest.fixture(autouse=True)
def ambiente_isolado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Sandbox do arquivo: banco/cache/lista/acervo/logs só em tmp_path.

    Também desliga por padrão a chave do AzuraCast e os tokens do
    Telegram — mesmo que um teste esqueça o dublê, nada sai da máquina.
    """
    (tmp_path / "musicas").mkdir(exist_ok=True)
    monkeypatch.setattr(rc, "BASE_MUSICAS", tmp_path / "musicas")
    monkeypatch.setattr(rc, "MUSICA_PYTHON", tmp_path / "sem-venv")
    monkeypatch.setattr(rp, "BANCO_PEDIDOS", tmp_path / "pedidos.db")
    monkeypatch.setattr(rp, "BANCO_ACERVO", tmp_path / "acervo.db")
    monkeypatch.setattr(rp, "CACHE_LETRAS", tmp_path / "letras.json")
    monkeypatch.setattr(rp, "AZURA_KEY", "")
    monkeypatch.setattr(rl, "TEMP_BASE", tmp_path / "tmp")
    monkeypatch.setattr(rl, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(rl, "TRAVA", tmp_path / "od_pipeline.lock")
    monkeypatch.setattr(rl, "MUSICA_PYTHON", tmp_path / "sem-venv")
    monkeypatch.setattr(rl, "MUSICA_PY", tmp_path / "sem-musica.py")
    for chave in ("AZURACAST_API_KEY", "OD_TELEGRAM_USUARIOS_TOKEN",
                  "TELEGRAM_BOT_TOKEN", "OD_TELEGRAM_USUARIOS_CHAT",
                  "OD_TELEGRAM_ADMINS"):
        monkeypatch.delenv(chave, raising=False)
    yield


@pytest.fixture()
def bancos(tmp_path: Path) -> dict[str, Path]:
    """Acervo + banco de pedidos do teste (ambos em tmp_path)."""
    return {
        "acervo": _criar_acervo(tmp_path / "acervo.db"),
        "pedidos": tmp_path / "pedidos.db",
        "letras": tmp_path / "letras.json",
    }


def _criar_link(bancos: dict[str, Path], usuario: str = "ana",
                link: str = VIDEO) -> dict:
    return rp.criar_pedido_link(usuario, link, banco=bancos["pedidos"])


def _item_registro(artista: str = "Annita", titulo: str = "X",
                   caminho: str = "", status: str = "aguardando",
                   criado_em: str | None = None,
                   decidir_ate: str | None = None) -> dict:
    item = {"artista": artista, "titulo": titulo, "caminho": caminho,
            "criado_em": criado_em or datetime.now(timezone.utc)
            .isoformat(timespec="seconds"),
            "tocou_em": "", "status": status}
    if decidir_ate is not None:
        item["decidir_ate"] = decidir_ate
    return item


def _vencido() -> str:
    """Prazo de decisão já estourado (a faixa sai na próxima limpeza)."""
    return (datetime.now(timezone.utc) - timedelta(hours=1)) \
        .isoformat(timespec="seconds")


def _registro_de(tmp_path: Path, *itens: dict) -> Path:
    reg = tmp_path / "radio_apagar_depois.json"
    reg.write_text(json.dumps(list(itens), ensure_ascii=False),
                   encoding="utf-8")
    return reg


# ---------------------------------------------------------------------------
#  radio_pro — cache de letras, fontes fora do ar e catálogo
# ---------------------------------------------------------------------------

class TestCacheDeLetras:
    """`_grava_cache` é enfeite, não defeito: nunca derruba a página."""

    def test_cache_estoura_o_teto_e_descarta_o_mais_antigo(
            self, tmp_path: Path) -> None:
        cache = tmp_path / "letras.json"
        dados = {f"m{i}": {"letra": "x", "em": float(i)}
                 for i in range(rp.CACHE_MAX + 5)}
        rp._grava_cache(cache, dados)
        gravado = json.loads(cache.read_text(encoding="utf-8"))
        assert len(gravado) == rp.CACHE_MAX, "teto do cache respeitado"
        assert "m0" not in gravado and "m4" not in gravado
        assert f"m{rp.CACHE_MAX + 4}" in gravado
        assert not list(cache.parent.glob("*.tmp")), "gravação atômica"

    def test_cache_sem_pasta_gravável_só_registra_o_warn(
            self, tmp_path: Path) -> None:
        """Erro de gravação vira log: o cache nunca quebra a tela."""
        arquivo = tmp_path / "nao_e_pasta"
        arquivo.write_text("x", encoding="utf-8")
        rp._grava_cache(arquivo / "letras.json",
                        {"k": {"letra": "x", "em": 1.0}})
        assert not (tmp_path / "letras.json").exists()


class TestBuscaLyricsOvh:
    """Ramos de `_busca_lyrics_ovh` — a reserva da cadeia de letras."""

    def test_letra_encontrada_e_limpa(self, monkeypatch) -> None:
        monkeypatch.setattr(rp, "urlopen",
                            _urlopen(b'{"lyrics": "  Letra boa  "}'))
        assert rp._busca_lyrics_ovh(
            "Fernandinho", "Todas as Coisas") == "Letra boa"

    def test_resposta_sem_letra_devolve_none(self, monkeypatch) -> None:
        monkeypatch.setattr(rp, "urlopen", _urlopen(b'{"lyrics": "   "}'))
        assert rp._busca_lyrics_ovh("A", "B") is None

    def test_404_e_fora_do_catalogo_sem_gritar(self, monkeypatch) -> None:
        monkeypatch.setattr(rp, "urlopen", _urlopen(falha=_http_erro(404)))
        assert rp._busca_lyrics_ovh("A", "B") is None

    def test_erro_do_servico_devolve_none(self, monkeypatch) -> None:
        monkeypatch.setattr(rp, "urlopen", _urlopen(falha=_http_erro(503)))
        assert rp._busca_lyrics_ovh("A", "B") is None

    def test_sem_rede_devolve_none(self, monkeypatch) -> None:
        monkeypatch.setattr(rp, "urlopen",
                            _urlopen(falha=URLError("sem rede")))
        assert rp._busca_lyrics_ovh("A", "B") is None

    def test_corpo_nao_json_devolve_none(self, monkeypatch) -> None:
        monkeypatch.setattr(rp, "urlopen", _urlopen(b"<html>pane</html>"))
        assert rp._busca_lyrics_ovh("A", "B") is None


class TestBuscaLrclibRamos:
    """Ramos do lrclib que a suíte não alcança (404 já está coberto)."""

    def test_erro_diferente_de_404_tambem_e_none(self, monkeypatch) -> None:
        monkeypatch.setattr(rp, "urlopen", _urlopen(falha=_http_erro(503)))
        assert rp._busca_lrclib("A", "B") is None

    def test_corpo_que_nao_e_lista_nem_dict(self, monkeypatch) -> None:
        monkeypatch.setattr(rp, "urlopen", _urlopen(b"42"))
        assert rp._busca_lrclib("A", "B") is None

    def test_dict_sem_letra_nao_vira_resultado(self, monkeypatch) -> None:
        monkeypatch.setattr(rp, "urlopen",
                            _urlopen(b'{"error": "not found"}'))
        assert rp._busca_lrclib("A", "B") is None

    def test_lista_sem_nenhuma_letra(self, monkeypatch) -> None:
        monkeypatch.setattr(rp, "urlopen",
                            _urlopen(b'[{"plainLyrics": ""}]'))
        assert rp._busca_lrclib("A", "B") is None


class TestVariacoesDeArtista:
    """Artista vazio: a fonte não é chamada com nome em branco."""

    def test_artista_vazio_so_tenta_a_vazia(self) -> None:
        assert rp._variacoes_artista("") == [""]
        assert rp._variacoes_artista("   ") == [""]

    def test_titulo_sem_artista_nao_chama_a_fonte(
            self, tmp_path: Path) -> None:
        chamadas: list[str] = []

        def busca(artista: str, _titulo: str) -> str:
            chamadas.append(artista)
            return "letra"

        r = rp.letra_da_musica("", "Ao Vivo", cache_arq=tmp_path / "c.json",
                               buscar=busca)
        assert r == {"ok": False, "motivo": "nao_encontrada"}
        assert chamadas == [], "sem artista não há o que buscar"


class TestCatalogoErros:
    """Entradas inválidas do catálogo devolvem lista vazia, nunca erro."""

    def test_limite_invalido_cai_no_padrao(self, bancos) -> None:
        itens = rp.catalogo_musicas(limite="muitos",
                                    banco=bancos["acervo"])
        assert len(itens) == 1
        assert len(rp.catalogo_musicas(limite=None,
                                       banco=bancos["acervo"])) == 1

    def test_banco_sem_tabela_devolve_vazio(self, tmp_path: Path) -> None:
        vazio = tmp_path / "vazio.db"
        sqlite3.connect(str(vazio)).close()
        assert rp.catalogo_musicas(banco=vazio) == []

    def test_musica_do_acervo_com_banco_inacessivel(
            self, tmp_path: Path) -> None:
        # pasta no lugar do arquivo: conexão falha
        assert rp.musica_do_acervo(CAMINHO, banco=tmp_path) is None
        # arquivo válido mas sem a tabela do pipeline
        vazio = tmp_path / "vazio.db"
        sqlite3.connect(str(vazio)).close()
        assert rp.musica_do_acervo(CAMINHO, banco=vazio) is None


class TestCooldownComRegistroCorrompido:
    """Data inválida no último pedido não trava a fila da conta."""

    def test_criado_em_impossivel_nao_bloqueia(self, bancos) -> None:
        rp._conexao(bancos["pedidos"]).close()
        conn = sqlite3.connect(str(bancos["pedidos"]))
        conn.execute("INSERT INTO pedidos (criado_em, usuario, caminho)"
                     " VALUES (?, ?, ?)",
                     ("data-impossivel", "ana", CAMINHO))
        conn.commit()
        conn.close()
        p = rp.criar_pedido("ana", CAMINHO, banco=bancos["pedidos"],
                            banco_acervo=bancos["acervo"])
        assert p["status"] == "pendente"


class TestLinkYoutubeExtremos:
    """Nada de `ValueError` vazando no handler: devolve "" e pronto."""

    def test_url_malformada_nao_levanta(self) -> None:
        assert rp.link_do_youtube("http://[::1") == ""

    def test_esquema_fora_de_http_e_recusado(self) -> None:
        assert rp.link_do_youtube(
            f"ftp://youtube.com/watch?v=dQw4w9WgXcQ") == ""

    def test_lista_curta_invalida_nao_vira_playlist(self) -> None:
        # `list=abc` não tem o formato de id → vira "" antes do /watch
        assert rp.link_do_youtube(
            "https://www.youtube.com/watch?v=curto&list=abc") == ""

    def test_caminho_desconhecido_do_dominio(self) -> None:
        assert rp.link_do_youtube("https://www.youtube.com/@nicky") == ""


class TestPedidoPorIdErros:
    """Leitura do pedido pelo worker: qualquer problema é None."""

    def test_banco_inexistente_devolve_none(self, tmp_path: Path) -> None:
        assert rp.pedido_por_id(1, banco=tmp_path / "nada.db") is None

    def test_pasta_no_lugar_do_banco_devolve_none(
            self, tmp_path: Path) -> None:
        assert rp.pedido_por_id(1, banco=tmp_path) is None

    def test_id_nao_numerico_devolve_none(self, bancos) -> None:
        rp._conexao(bancos["pedidos"]).close()
        assert rp.pedido_por_id("abc", banco=bancos["pedidos"]) is None


class TestAtualizarPedidoErros:
    """O worker do link atualiza o pedido; erro vira None, nunca exceção."""

    def test_banco_inacessivel_devolve_none(self, tmp_path: Path) -> None:
        assert rp.atualizar_pedido(1, status="tocada",
                                   banco=tmp_path) is None

    def test_erro_na_atualizacao_nao_levanta(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        banco = tmp_path / "pedidos.db"
        banco.write_bytes(b"")                 # existe, mas é lixo
        sem_tabela = tmp_path / "outras.db"
        sqlite3.connect(str(sem_tabela)).close()
        monkeypatch.setattr(rp, "_conexao",
                            lambda _b: sqlite3.connect(str(sem_tabela)))
        assert rp.atualizar_pedido(1, status="tocada", banco=banco) is None


class TestMeusPedidosErros:
    """`meus_pedidos` devolve [] no arquivo/banco problemático."""

    def test_pasta_no_lugar_do_banco(self, tmp_path: Path) -> None:
        assert rp.meus_pedidos("ana", banco=tmp_path) == []

    def test_banco_sem_a_tabela_de_pedidos(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        banco = tmp_path / "pedidos.db"
        banco.write_bytes(b"")
        sem_tabela = tmp_path / "outras.db"
        sqlite3.connect(str(sem_tabela)).close()
        monkeypatch.setattr(rp, "_conexao",
                            lambda _b: sqlite3.connect(str(sem_tabela)))
        assert rp.meus_pedidos("ana", banco=banco) == []


# ---------------------------------------------------------------------------
#  radio_pro — AzuraCast, MariaDB e o INSERT da fila (tudo dublê)
# ---------------------------------------------------------------------------

class TestAzuracast:
    """`_azuracast` nunca levanta: devolve (status, dados)."""

    def test_sem_chave_nem_tenta_conexao(self, monkeypatch) -> None:
        def nao_deve_chamar(*_a, **_k):
            raise AssertionError("rede não pode ser usada sem chave")

        monkeypatch.setattr(rp, "urlopen", nao_deve_chamar)
        assert rp._azuracast("/api/station/nicky/requests",
                             chave="") == (None, None)

    def test_resposta_em_json_com_a_chave_no_header(
            self, monkeypatch) -> None:
        chamadas: list = []

        def fake(req, timeout=None):
            chamadas.append((req, timeout))
            return _Resposta(b'{"ok": true}')

        monkeypatch.setattr(rp, "urlopen", fake)
        status, dados = rp._azuracast("/api/station/nicky/requests",
                                      chave="segredo")
        assert (status, dados) == (200, {"ok": True})
        req, timeout = chamadas[0]
        assert req.full_url.endswith("/api/station/nicky/requests")
        assert req.get_method() == "GET"
        assert "segredo" in str(req.header_items())
        assert timeout == 8.0

    def test_post_manda_o_corpo_vazio(self, monkeypatch) -> None:
        visto: dict = {}

        def fake(req, timeout=None):
            visto["metodo"] = req.get_method()
            visto["data"] = req.data
            return _Resposta(b"{}", 201)

        monkeypatch.setattr(rp, "urlopen", fake)
        assert rp._azuracast("/api/x", metodo="POST", chave="k") == \
            (201, {})
        assert visto == {"metodo": "POST", "data": b"{}"}

    def test_corpo_nao_json_vira_o_texto_cru(self, monkeypatch) -> None:
        monkeypatch.setattr(rp, "urlopen", _urlopen(b"<html>pane</html>"))
        assert rp._azuracast("/api/x", chave="k") == (200, "<html>pane</html>")

    def test_erro_http_devolve_o_codigo(self, monkeypatch) -> None:
        monkeypatch.setattr(rp, "urlopen", _urlopen(falha=_http_erro(503)))
        assert rp._azuracast("/api/x", chave="k") == (503, None)

    def test_sem_rede_devolve_none_none(self, monkeypatch) -> None:
        monkeypatch.setattr(rp, "urlopen",
                            _urlopen(falha=URLError("sem rede")))
        assert rp._azuracast("/api/x", chave="k") == (None, None)


class TestJingleRecente:
    """A régua dos 10 min do jingle lida pelo nosso lado (nunca a rede)."""

    def _com_historico(self, monkeypatch, dados) -> None:
        monkeypatch.setattr(rp, "_azuracast", lambda *a, **k: (200, dados))

    def test_jingle_tocado_agora_trava_o_proximo(self, monkeypatch) -> None:
        self._com_historico(monkeypatch, [
            {"song": {"title": "anuncio musica"}, "played_at": time.time()},
        ])
        assert rp._jingle_tocou_recentemente() is True

    def test_jingle_antigo_nao_trava(self, monkeypatch) -> None:
        self._com_historico(monkeypatch, [
            {"song": {"title": "anuncio musica"},
             "played_at": time.time() - 3600},
        ])
        assert rp._jingle_tocou_recentemente() is False

    def test_outra_faixa_no_historico_nao_conta(self, monkeypatch) -> None:
        self._com_historico(monkeypatch, [
            {"song": {"title": "Fernandinho - Todas as Coisas"},
             "played_at": time.time()},
        ])
        assert rp._jingle_tocou_recentemente() is False

    def test_data_do_historico_invalida_conta_como_antiga(
            self, monkeypatch) -> None:
        self._com_historico(monkeypatch, [
            {"song": {"title": "anuncio musica"}, "played_at": "amanha"},
        ])
        assert rp._jingle_tocou_recentemente() is False

    def test_estacao_fora_nao_trava(self, monkeypatch) -> None:
        monkeypatch.setattr(rp, "_azuracast", lambda *a, **k: (503, []))
        assert rp._jingle_tocou_recentemente() is False

    def test_historico_que_nao_e_lista(self, monkeypatch) -> None:
        self._com_historico(monkeypatch, {"erro": 1})
        assert rp._jingle_tocou_recentemente() is False


class TestMariadb:
    """`_mariadb` roda no container; aqui o subprocesso é dublê."""

    def _falso(self, monkeypatch, retorno) -> dict:
        visto: dict = {}

        def run(cmd, **kwargs):
            visto.update(args=cmd, kwargs=kwargs)
            if isinstance(retorno, BaseException):
                raise retorno
            return SimpleNamespace(**retorno)

        monkeypatch.setattr(rp.subprocess, "run", run)
        return visto

    def test_sucesso_devolve_a_saida_do_container(
            self, monkeypatch) -> None:
        visto = self._falso(monkeypatch,
                            {"returncode": 0, "stdout": "1\t2\t3\n"})
        ok, saida = rp._mariadb("SELECT 1")
        assert ok is True and saida == "1\t2\t3\n"
        assert visto["args"][0] == "docker"
        assert "azuracast" in visto["args"]
        assert visto["kwargs"]["timeout"] == 20

    def test_container_ausente_devolve_false(
            self, monkeypatch) -> None:
        self._falso(monkeypatch, FileNotFoundError("docker sumiu"))
        assert rp._mariadb("SELECT 1") == (False, "")

    def test_timeout_do_mariadb_devolve_false(
            self, monkeypatch) -> None:
        self._falso(monkeypatch, subprocess.TimeoutExpired("docker", 20))
        assert rp._mariadb("SELECT 1") == (False, "")

    def test_codigo_de_erro_nao_e_sucesso(self, monkeypatch) -> None:
        self._falso(monkeypatch, {"returncode": 2, "stdout": "erro\n"})
        assert rp._mariadb("SELECT 1") == (False, "erro\n")


class TestInserirRequestsParser:
    """O parser do SELECT tolera lixo — e SQL recusado não vira INSERT."""

    def test_sql_recusado_nao_insere(self) -> None:
        assert rp._inserir_requests(UID, "b" * 24,
                                    "2026-11-15 10:00:00",
                                    "2026-11-15 10:00:00",
                                    rodar=lambda _sql: (False, "")) is False

    def test_linhas_invalidas_sao_ignoradas(self) -> None:
        uid_j, uid_p = "a" * 24, "b" * 24
        vistas: list[str] = []

        def rodar(sql: str) -> tuple[bool, str]:
            vistas.append(sql)
            if "station_media" in sql:
                return True, "\n".join([
                    "so_duas_colunas",
                    f"mid\t{uid_j}\tnao-e-inteiro",
                    "st\t\ttambem-nao",
                    f"mid\t{uid_j}\t7",
                    f"mid\t{uid_p}\t423",
                    "st\t\t1",
                ])
            return True, ""

        ok = rp._inserir_requests(uid_j, uid_p,
                                  "2026-11-15 10:00:00",
                                  "2026-11-15 10:00:00", rodar=rodar)
        assert ok is True
        assert len(vistas) == 2
        assert "INSERT INTO station_requests" in vistas[1]
        assert f"(1, 7, '2026-11-15 10:00:00', 0, 'od-core')" in vistas[1]


class TestPedirNoArComplementar:
    """Ramos do pedido no ar que os testes da fila não alcançam."""

    def _azuracast_com(self, monkeypatch, itens, status=200) -> None:
        monkeypatch.setattr(rp, "_azuracast",
                            lambda *a, **k: (status, itens))

    def test_fila_fora_do_ar(self, monkeypatch) -> None:
        self._azuracast_com(monkeypatch, None, status=503)
        assert rp.pedir_no_ar("A", "B", chave="k") == \
            {"ok": False, "motivo": "fila_fora"}

    def test_casa_no_texto_artista_traculo_titulo(self, monkeypatch) -> None:
        """Sem artist/title o AzuraCast manda "Artista - Título"."""
        self._azuracast_com(monkeypatch, [
            {"request_url": f"/api/station/1/request/{UID}",
             "song": {"text": "Fernandinho - Todas as Coisas"}}])
        inserido: dict = {}

        def inserir(uj, up, tsj, tsp) -> bool:
            inserido.update(jingle=uj, musica=up)
            return True

        r = rp.pedir_no_ar("Fernandinho", "Todas as Coisas", chave="k",
                           jingle_recente=lambda: False, inserir=inserir)
        assert r == {"ok": True, "fila": "azuracast"}
        assert inserido["musica"] == UID

    def test_padroes_do_modulo_sao_usados_quando_nao_injetados(
            self, monkeypatch) -> None:
        """Sem `jingle_recente`/`inserir` o módulo cai nos seus próprios."""
        self._azuracast_com(monkeypatch, [
            {"request_url": f"/api/station/1/request/{UID}",
             "song": {"artist": "A", "title": "B"}}])
        monkeypatch.setattr(rp, "_jingle_tocou_recentemente", lambda: False)
        visto: dict = {}
        monkeypatch.setattr(
            rp, "_inserir_requests",
            lambda *a: visto.update(args=a) or True)
        r = rp.pedir_no_ar("A", "B", chave="k")
        assert r == {"ok": True, "fila": "azuracast"}
        assert visto["args"][0] == rp.JINGLE_ANUNCIO
        assert visto["args"][1] == UID

    def test_historico_do_jingle_quebrado_nao_trava(
            self, monkeypatch) -> None:
        """Histórico é pista, não portão: a inserção segue normal."""
        self._azuracast_com(monkeypatch, [
            {"request_url": f"/api/station/1/request/{UID}",
             "song": {"artist": "A", "title": "B"}}])

        def quebra():
            raise RuntimeError("history 500")

        ts: dict = {}

        def inserir(_uj, _up, tsj, tsp) -> bool:
            ts.update(jingle=tsj, musica=tsp)
            return True

        r = rp.pedir_no_ar("A", "B", chave="k", jingle_recente=quebra,
                           inserir=inserir)
        assert r == {"ok": True, "fila": "azuracast"}
        assert ts["jingle"] == ts["musica"], "sem travado, os dois juntos"


class TestMarcarStatusErros:
    """Mudança de estado do pedido: erro vira False, nunca exceção."""

    def test_pasta_no_lugar_do_banco(self, tmp_path: Path) -> None:
        assert rp.marcar_status(1, "tocada", banco=tmp_path) is False

    def test_id_suja_nao_atualiza(self, bancos) -> None:
        rp._conexao(bancos["pedidos"]).close()
        assert rp.marcar_status("nao-e-numero", "tocada",
                                banco=bancos["pedidos"]) is False


class TestConfirmarRecadosErros:
    """Confirmação do webhook: erro de arquivo/banco devolve 0."""

    def test_pasta_no_lugar_do_banco(self, tmp_path: Path) -> None:
        assert rp.confirmar_recados_no_ar(banco=tmp_path) == 0

    def test_banco_sem_tabela_de_pedidos(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        banco = tmp_path / "pedidos.db"
        banco.write_bytes(b"")
        sem_tabela = tmp_path / "outras.db"
        sqlite3.connect(str(sem_tabela)).close()
        monkeypatch.setattr(rp, "_conexao",
                            lambda _b: sqlite3.connect(str(sem_tabela)))
        assert rp.confirmar_recados_no_ar(banco=banco) == 0


class TestAnuncioErros:
    """A fala da locutora: qualquer problema devolve "" sem derrubar."""

    def test_pasta_no_lugar_do_banco(self, tmp_path: Path) -> None:
        assert rp.anuncio_de_pedido("", "anuncio musica",
                                    banco=tmp_path) == ""

    def test_artista_divergente_nao_marca_a_faixa(self, bancos) -> None:
        """Outro artista com o mesmo título não pode consumir o recado."""
        p = rp.criar_pedido("ana", CAMINHO, "bom dia",
                            banco=bancos["pedidos"],
                            banco_acervo=bancos["acervo"])
        assert rp.anuncio_de_pedido("Jota Quest", "Todas as Coisas",
                                    banco=bancos["pedidos"]) == ""
        assert rp.pedido_por_id(p["id"], banco=bancos["pedidos"])["status"] \
            == "pendente"

    def test_erro_de_banco_nao_levanta(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        banco = tmp_path / "pedidos.db"
        banco.write_bytes(b"")
        sem_tabela = tmp_path / "outras.db"
        sqlite3.connect(str(sem_tabela)).close()
        monkeypatch.setattr(rp, "_conexao",
                            lambda _b: sqlite3.connect(str(sem_tabela)))
        assert rp.anuncio_de_pedido("", "anuncio musica",
                                    banco=banco) == ""


class TestLancarFilaComListaQuebrada:
    """A lista de cantores é regra, não portão: erro não derruba a fila."""

    def test_erro_na_lista_nao_derruba_a_fila(
            self, bancos, monkeypatch: pytest.MonkeyPatch) -> None:
        def quebra(*_a, **_k):
            raise RuntimeError("lista corrompida")

        monkeypatch.setattr(rc, "indesejado", quebra)
        rp._conexao(bancos["pedidos"]).close()
        pedido = {"id": 1, "status": "pendente", "artista": "Annita",
                  "titulo": "X", "caminho": "acervo/Annita - X.mp3"}
        r = rp.lancar_pedido_na_fila(
            pedido, enviar=lambda _a, _t: {"ok": True},
            banco=bancos["pedidos"])
        assert r["fila"] == "azuracast" and r["status"] == "na_fila"

    def test_musica_bloqueada_marca_e_avisa_o_dono(
            self, bancos, tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch) -> None:
        """Cantor permitido com UMA música bloqueada (ordem de 17/11)."""
        lista = tmp_path / "bloqueadas.txt"
        lista.write_text("Fernandinho | Todas as Coisas\n", encoding="utf-8")
        monkeypatch.setattr(rc, "LISTA_BLOQUEADAS", lista)
        monkeypatch.setattr(rc, "LISTA", tmp_path / "vazia.txt")
        monkeypatch.setattr(rc, "REGISTRO", tmp_path / "apagar.json")
        avisos: list[str] = []
        monkeypatch.setattr(rl, "notificar_dono", avisos.append)
        pedido = rp.criar_pedido("fulano", CAMINHO, "x",
                                 banco=bancos["pedidos"],
                                 banco_acervo=bancos["acervo"])
        assert pedido and pedido["status"] == "pendente"
        r = rp.lancar_pedido_na_fila(
            pedido, enviar=lambda _a, _t: {"ok": True},
            banco=bancos["pedidos"])
        assert r["fila"] == "azuracast" and r["status"] == "na_fila"
        pend = rc.pendentes()
        assert len(pend) == 1 and pend[0]["motivo"] == "musica"
        assert avisos and "Decisão necessária" in avisos[0]


# ---------------------------------------------------------------------------
#  radio_link — extração, pipeline do acervo e trava entre workers
# ---------------------------------------------------------------------------

class TestExtrairEntradas:
    """Extração plana sem baixar: subprocesso dublê, sempre em tmp."""

    def test_python_do_acervo_ausente(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            rl.extrair_entradas(VIDEO, python=tmp_path / "nao-existe")

    def test_processo_de_extração_com_erro(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        py = tmp_path / "python"
        py.write_text("", encoding="utf-8")
        monkeypatch.setattr(
            rl.subprocess, "run",
            lambda *a, **k: SimpleNamespace(returncode=1, stdout="",
                                            stderr="yt-dlp quebrou"))
        with pytest.raises(RuntimeError, match="yt-dlp quebrou"):
            rl.extrair_entradas(VIDEO, python=py)

    def _falso_stdout(self, monkeypatch, stdout: str,
                      codigo: int = 0) -> None:
        monkeypatch.setattr(
            rl.subprocess, "run",
            lambda *a, **k: SimpleNamespace(returncode=codigo,
                                            stdout=stdout, stderr=""))

    def test_stdout_sem_json_devolve_vazio(
            self, tmp_path: Path, monkeypatch) -> None:
        py = tmp_path / "python"
        py.write_text("", encoding="utf-8")
        self._falso_stdout(monkeypatch, "baixando...\nok\n")
        assert rl.extrair_entradas(VIDEO, python=py) == []

    def test_json_pela_metade_devolve_vazio(
            self, tmp_path: Path, monkeypatch) -> None:
        py = tmp_path / "python"
        py.write_text("", encoding="utf-8")
        self._falso_stdout(monkeypatch, '[{"url": "quebrado"\n')
        assert rl.extrair_entradas(VIDEO, python=py) == []

    def test_parseia_lista_com_artistas_de_varios_formatos(
            self, tmp_path: Path, monkeypatch) -> None:
        py = tmp_path / "python"
        py.write_text("", encoding="utf-8")
        corpo = json.dumps([
            {"url": VIDEO, "title": "Faixa 1", "artistas": "Solo"},
            {"title": "sem url nenhuma"},
            "nao-e-dict",
            {"url": "https://youtu.be/bbbbbbbbbbb", "title": "",
             "artistas": ["  Annita  ", "   "]},
        ], ensure_ascii=False)
        self._falso_stdout(monkeypatch, f"aviso\n{corpo}\n")
        entradas = rl.extrair_entradas(LISTA, python=py)
        assert entradas == [
            {"url": VIDEO, "title": "Faixa 1", "artistas": ["Solo"]},
            {"url": "https://youtu.be/bbbbbbbbbbb", "title": "",
             "artistas": ["Annita"]},
        ]


class TestPistasDeArtista:
    """O link já entrega o artista — inclusive como texto único."""

    def test_artista_vindo_como_texto_unico(self) -> None:
        assert rl._pistas_de_artista({"artistas": "Annita",
                                      "title": ""}) == ["Annita"]


class TestRodarPipeline:
    """O pipeline oficial com TEMP_DIR isolado — subprocesso dublê."""

    def _preparar(self, tmp_path: Path) -> tuple[Path, Path]:
        py = tmp_path / "python"
        py.write_text("", encoding="utf-8")
        script = tmp_path / "musica.py"
        script.write_text("", encoding="utf-8")
        return py, script

    def test_python_do_acervo_ausente(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            rl.rodar_pipeline([VIDEO], python=tmp_path / "sem-python",
                              script=tmp_path / "musica.py")

    def test_musica_py_ausente(self, tmp_path: Path) -> None:
        py = tmp_path / "python"
        py.write_text("", encoding="utf-8")
        with pytest.raises(FileNotFoundError):
            rl.rodar_pipeline([VIDEO], python=py,
                              script=tmp_path / "sem-musica.py")

    def test_sucesso_limpa_o_diretorio_isolado(
            self, tmp_path: Path, monkeypatch) -> None:
        py, script = self._preparar(tmp_path)
        monkeypatch.setattr(rl.subprocess, "run",
                            lambda *a, **k: SimpleNamespace(returncode=0))
        assert rl.rodar_pipeline([VIDEO], python=py, script=script,
                                 timeout=10) == 0
        assert list(rl.TEMP_BASE.glob("od_link_*")) == []

    def test_erro_do_pipeline_guarda_o_diretorio_para_inspecao(
            self, tmp_path: Path, monkeypatch) -> None:
        py, script = self._preparar(tmp_path)
        monkeypatch.setattr(rl.subprocess, "run",
                            lambda *a, **k: SimpleNamespace(returncode=3))
        assert rl.rodar_pipeline([VIDEO], python=py, script=script,
                                 timeout=10) == 3
        assert len(list(rl.TEMP_BASE.glob("od_link_*"))) == 1

    def test_timeout_propaga_e_guarda_o_diretorio(
            self, tmp_path: Path, monkeypatch) -> None:
        py, script = self._preparar(tmp_path)

        def estoura(*_a, **_k):
            raise subprocess.TimeoutExpired("musica.py", 1200)

        monkeypatch.setattr(rl.subprocess, "run", estoura)
        with pytest.raises(subprocess.TimeoutExpired):
            rl.rodar_pipeline([VIDEO], python=py, script=script,
                              timeout=1)
        assert len(list(rl.TEMP_BASE.glob("od_link_*"))) == 1


class TestTravaPipeline:
    """Flock entre workers: trava na entrada, libera na saída."""

    def test_trava_segura_e_libera_o_lock(self, tmp_path: Path) -> None:
        alvo = tmp_path / "od.lock"
        with rl.trava_pipeline(alvo):
            assert alvo.exists()
            with alvo.open("w") as testador:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(testador.fileno(),
                                fcntl.LOCK_EX | fcntl.LOCK_NB)
        with alvo.open("w") as testador:
            fcntl.flock(testador.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(testador.fileno(), fcntl.LOCK_UN)


class TestMusicasDoAcervo:
    """Leitura do acervo do worker: arquivo ruim devolve {}."""

    def test_banco_inexistente(self, tmp_path: Path) -> None:
        assert rl._musicas_do_acervo(tmp_path / "nada.db") == {}

    def test_pasta_no_lugar_do_banco(self, tmp_path: Path) -> None:
        assert rl._musicas_do_acervo(tmp_path) == {}

    def test_banco_sem_a_tabela_de_musicas(self, tmp_path: Path) -> None:
        vazio = tmp_path / "vazio.db"
        sqlite3.connect(str(vazio)).close()
        assert rl._musicas_do_acervo(vazio) == {}


class TestPareceRepetida:
    """Pré-checagem barata do título — sem download, sem IA."""

    def test_titulo_vazio_nunca_e_repetida(self) -> None:
        acervo = {"a": {"caminho": "x.mp3", "artista": "Fernandinho",
                        "titulo": "Todas as Coisas"}}
        assert rl._parece_repetida("", acervo) is False
        assert rl._parece_repetida("Fernandinho", acervo) is False
        assert rl._parece_repetida(
            "Fernandinho - Todas as Coisas (Ao Vivo)", acervo) is True

    def test_lista_bare_x_acervo_com_artista_casa(self) -> None:
        """18/11: lista só com "Música" × acervo "Artista - Música".

        Foi o buraco que deixou a Metamorfose Ambulante entrar DUAS
        vezes no acervo (Rock com artista + MPB "Desconhecido" — o
        pipeline renomeou falhando a detecção de artista).
        """
        acervo = {"a": {"caminho": "acervo/Rock/Raul Seixas - Metamorfose"
                                   " Ambulante.mp3",
                        "artista": "Raul Seixas",
                        "titulo": "Metamorfose Ambulante"}}
        assert rl._parece_repetida("Metamorfose Ambulante", acervo) is True
        assert rl._parece_repetida(
            "Metamorfose Ambulante (Clipe Oficial)", acervo) is True
        # Igualdade exata vale até para palavra única
        gita = {"g": {"caminho": "y.mp3", "artista": "Raul Seixas",
                      "titulo": "Gita"}}
        assert rl._parece_repetida("Gita", gita) is True
        # Contido de palavra solta NÃO casa (anti falso positivo:
        # "Love" do acervo não pode matar "Love Fool" da lista)
        love = {"l": {"caminho": "z.mp3", "artista": "X", "titulo": "Love"}}
        assert rl._parece_repetida("Love Fool", love) is False
        # Título totalmente diferente continua liberado
        assert rl._parece_repetida("Alvorada da Terra", acervo) is False


# ---------------------------------------------------------------------------
#  radio_link — aviso ao dono e resultado do pedido
# ---------------------------------------------------------------------------

class TestNotificarDono:
    """Telegram do dono: dublê de `urlopen`, nada sai da máquina."""

    def test_dublê_de_envio_devolve_true(self) -> None:
        assert rl.notificar_dono("oi", enviar=lambda _t: None) is True

    def test_envia_para_cada_chat_do_dono(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OD_TELEGRAM_USUARIOS_TOKEN", "123:abc")
        monkeypatch.setenv("OD_TELEGRAM_USUARIOS_CHAT", "-1001, -1002")
        enviados: list[str] = []

        def fake(req, timeout=None):
            enviados.append(req.full_url)
            return _Resposta(b'{"ok": true}')

        monkeypatch.setattr("urllib.request.urlopen", fake)
        assert rl.notificar_dono("olá dono") is True
        assert len(enviados) == 2
        assert all("sendMessage" in url for url in enviados)

    def test_rede_recusa_o_aviso_e_nao_derruba(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OD_TELEGRAM_USUARIOS_TOKEN", "123:abc")
        monkeypatch.setenv("OD_TELEGRAM_USUARIOS_CHAT", "-1001")
        monkeypatch.setattr("urllib.request.urlopen",
                            _urlopen(falha=URLError("sem rede")))
        assert rl.notificar_dono("oi") is False


class TestAvisarSemDuble:
    """`_avisar(texto, None)` cai no aviso padrão do dono."""

    def test_cai_no_aviso_padrao(self, monkeypatch) -> None:
        visto: list[str] = []
        monkeypatch.setattr(rl, "notificar_dono", visto.append)
        rl._avisar("aviso sem dublê", None)
        assert visto == ["aviso sem dublê"]


class TestAvisarResultado:
    """Texto do desfecho: qualquer status vira aviso (com o link)."""

    def test_status_final_entra_no_texto(self) -> None:
        avisos: list[str] = []
        rl._avisar_resultado({"status": "rejeitada", "usuario": "ana",
                              "artista": "A", "titulo": "B",
                              "link": VIDEO}, avisos.append)
        assert len(avisos) == 1
        assert "(rejeitada)" in avisos[0]
        assert VIDEO in avisos[0]

    def test_pedido_sem_nome_fala_só_o_id_do_aviso(self) -> None:
        avisos: list[str] = []
        rl._avisar_resultado({"status": "baixando", "usuario": "bia"},
                             avisos.append)
        assert "pedido" in avisos[0] and "@bia" in avisos[0]


class TestCantorIndesejadoComErro:
    """Lista do dono corrompida: o download segue, o erro vira log."""

    def test_lista_quebrada_nao_bloqueia_o_resto(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        def quebra(*_a, **_k):
            raise RuntimeError("lista corrompida")

        monkeypatch.setattr(rc, "indesejado", quebra)
        assert rl._do_cantor_indesejado(
            {"title": "Annita - Envolver",
             "artistas": ["Annita"]}) is False


class TestBaixarRestoComplementar:
    """Lote do resto da lista que sai com código de erro."""

    def test_lote_com_codigo_de_erro_conta_como_falha(self) -> None:
        avisos: list[str] = []
        rl._baixar_resto(
            [{"url": "https://youtu.be/aaaaaaaaaaa"}],
            {"id": 7, "usuario": "ana"},
            trava=nullcontext,
            rodar=lambda _urls, **_kw: 3,
            notificar=avisos.append,
        )
        assert any("com falha" in a for a in avisos)
        assert any("radio_link_7.log" in a for a in avisos)

    def test_rodar_quebrado_tambem_conta_como_falha(self) -> None:
        avisos: list[str] = []

        def quebra(_urls, **_kw):
            raise subprocess.TimeoutExpired("musica.py", 1)

        rl._baixar_resto(
            [{"url": "https://youtu.be/aaaaaaaaaaa"},
             {"url": "https://youtu.be/bbbbbbbbbbb"}],
            {"id": 8, "usuario": "bia"},
            trava=nullcontext, rodar=quebra, notificar=avisos.append,
            lote=1,
        )
        assert any("2 lote(s)" in a and "2 com falha" in a for a in avisos)


# ---------------------------------------------------------------------------
#  radio_link — worker: processar_pedido nos ramos de erro
# ---------------------------------------------------------------------------

def _adicionar(banco: Path, caminho: str, artista: str,
               titulo: str) -> None:
    conn = sqlite3.connect(str(banco))
    conn.execute("INSERT INTO musicas (caminho, artista, titulo, genero)"
                 " VALUES (?, ?, ?, '')", (caminho, artista, titulo))
    conn.commit()
    conn.close()


class TestProcessarPedidoComplementar:
    """Ramos do worker que a suíte do link não alcança (erros de ponta)."""

    def test_pedido_inexistente(self, tmp_path: Path) -> None:
        r = rl.processar_pedido(
            999, banco=tmp_path / "nada.db",
            banco_acervo=tmp_path / "acervo.db",
            extrair=lambda _l: [], rodar=lambda _u, **_k: 0,
            lancar=lambda p: p, notificar=lambda _t: None,
            trava=nullcontext)
        assert r == {"ok": False, "motivo": "pedido_inexistente",
                     "pedido_id": 999}

    def test_pedido_sem_link_vira_link_invalido(
            self, tmp_path: Path) -> None:
        banco = tmp_path / "pedidos.db"
        rp._conexao(banco).close()
        conn = sqlite3.connect(str(banco))
        conn.execute("INSERT INTO pedidos (criado_em, usuario, caminho,"
                     " status) VALUES (?, ?, '', 'baixando')",
                     ("2026-11-15T10:00:00", "ana"))
        conn.commit()
        conn.close()
        avisos: list[str] = []
        r = rl.processar_pedido(
            1, banco=banco, banco_acervo=tmp_path / "acervo.db",
            extrair=lambda _l: (_ for _ in ()).throw(
                AssertionError("não deveria extrair")),
            rodar=lambda _u, **_k: 0, lancar=lambda p: p,
            notificar=avisos.append, trava=nullcontext)
        assert r["motivo"] == "link_invalido" and r["ok"] is False
        assert any("link_invalido" in a for a in avisos)

    def test_extracao_quebrada_nao_derruba(
            self, bancos, tmp_path: Path) -> None:
        p = _criar_link(bancos)
        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"],
            banco_acervo=bancos["acervo"],
            extrair=lambda _l: (_ for _ in ()).throw(
                RuntimeError("yt-dlp morreu")),
            rodar=lambda _u, **_k: 0, lancar=lambda p_: p_,
            notificar=lambda _t: None, trava=nullcontext)
        assert r["motivo"] == "link_invalido"
        assert rp.pedido_por_id(p["id"], banco=bancos["pedidos"])["status"] \
            == "rejeitada"

    def test_entradas_suja_sao_filtradas(self, bancos) -> None:
        p = _criar_link(bancos)
        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"],
            banco_acervo=bancos["acervo"],
            extrair=lambda _l: ["lixo", {"title": "sem url"}, None],
            rodar=lambda _u, **_k: 0, lancar=lambda p_: p_,
            notificar=lambda _t: None, trava=nullcontext)
        assert r["motivo"] == "link_invalido"

    def test_lista_do_cantor_quebrada_nao_marca(
            self, bancos, tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch) -> None:
        """A checagem é regra, não portão: erro vira log, pedido segue."""
        def quebra(*_a, **_k):
            raise RuntimeError("lista corrompida")

        monkeypatch.setattr(rc, "indesejado", quebra)
        p = _criar_link(bancos)
        registro = tmp_path / "apagar.json"

        def rodar(_u, **_k) -> int:
            _adicionar(bancos["acervo"], "acervo/Outros/Fulano - Musica.mp3",
                       "Fulano", "Musica")
            return 0

        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"],
            banco_acervo=bancos["acervo"],
            extrair=lambda _l: [{"url": VIDEO, "title": "Fulano - Musica",
                                 "artistas": ["Fulano"]}],
            rodar=rodar,
            lancar=lambda p_: rp.marcar_status(int(p_["id"]), "na_fila",
                                               banco=bancos["pedidos"]),
            notificar=lambda _t: None, trava=nullcontext,
            cantores_lista=tmp_path / "lista.txt",
            cantores_registro=registro)
        assert r["ok"] is True and r["fila"] is True
        assert not registro.exists(), "sem marcar com a lista quebrada"

    def test_repetida_com_lista_baixa_o_resto(self, bancos) -> None:
        """Título já no acervo: não baixa a 1ª, mas o resto da lista segue."""
        p = _criar_link(bancos, link=LISTA)
        urls = [VIDEO, "https://youtu.be/aaaaaaaaaaa"]
        chamadas: list[list[str]] = []

        def rodar(lista, **_kw):
            chamadas.append(list(lista))
            return 0

        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"],
            banco_acervo=bancos["acervo"],
            extrair=lambda _l: [{"url": u, "title": t} for u, t in zip(
                urls, ["Fernandinho - Todas as Coisas (Ao Vivo)",
                       "Outra - Faixa"])],
            rodar=rodar, lancar=lambda p_: p_,
            notificar=lambda _t: None, trava=nullcontext)
        assert r["motivo"] == "musica_repetida"
        assert chamadas == [[urls[1]]], "o resto da lista ainda baixa"

    def test_dedupe_sem_novo_com_lista_baixa_o_resto(
            self, bancos) -> None:
        """Código 0 do pipeline e nada novo: a lista não é abandonada."""
        p = _criar_link(bancos, link=LISTA)
        urls = [VIDEO, "https://youtu.be/aaaaaaaaaaa"]
        chamadas: list[list[str]] = []

        def rodar(lista, **_kw):
            chamadas.append(list(lista))
            return 0

        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"],
            banco_acervo=bancos["acervo"],
            extrair=lambda _l: [{"url": u, "title": f"Faixa {i}"}
                                for i, u in enumerate(urls)],
            rodar=rodar, lancar=lambda p_: p_,
            notificar=lambda _t: None, trava=nullcontext)
        assert r["motivo"] == "musica_repetida"
        # 1ª tentativa do download único (dedupe não achou nada novo) e
        # em seguida o RESTO da lista em lote próprio
        assert chamadas == [[VIDEO], [urls[1]]]

    def test_pipeline_quebrado_vira_falha_download(self, bancos) -> None:
        p = _criar_link(bancos)

        def quebra(_u, **_kw):
            raise RuntimeError("pipeline morreu")

        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"],
            banco_acervo=bancos["acervo"],
            extrair=lambda _l: [{"url": VIDEO, "title": "Faixa"}],
            rodar=quebra, lancar=lambda p_: p_,
            notificar=lambda _t: None, trava=nullcontext)
        assert r["motivo"] == "falha_download"
        assert rp.pedido_por_id(p["id"], banco=bancos["pedidos"])["status"] \
            == "rejeitada"

    def test_erro_ao_registrar_cantor_nao_para_o_pedido(
            self, bancos, tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch) -> None:
        def quebra(*_a, **_k):
            raise RuntimeError("disco cheio")

        monkeypatch.setattr(rc, "registrar_para_apagar", quebra)
        lista = tmp_path / "lista.txt"
        lista.write_text("Annita\n", encoding="utf-8")
        p = _criar_link(bancos)

        def rodar(_u, **_k) -> int:
            _adicionar(bancos["acervo"], "acervo/Outros/Annita - Envolver.mp3",
                       "Annita", "Envolver")
            return 0

        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"],
            banco_acervo=bancos["acervo"],
            extrair=lambda _l: [{"url": VIDEO,
                                 "title": "Annita - Envolver",
                                 "artistas": ["Annita"]}],
            rodar=rodar,
            lancar=lambda p_: rp.marcar_status(int(p_["id"]), "na_fila",
                                               banco=bancos["pedidos"]),
            notificar=lambda _t: None, trava=nullcontext,
            cantores_lista=lista,
            cantores_registro=tmp_path / "apagar.json")
        assert r["ok"] is True and r["fila"] is True

    def test_fila_quebrada_fica_pendente_e_avisa(self, bancos) -> None:
        avisos: list[str] = []
        p = _criar_link(bancos)

        def quebra(_p):
            raise RuntimeError("AzuraCast fora do ar")

        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"],
            banco_acervo=bancos["acervo"],
            extrair=lambda _l: [{"url": VIDEO, "title": "Faixa"}],
            rodar=lambda _u, **_k: _adicionar(
                bancos["acervo"], "acervo/Outros/Faixa.mp3", "A", "Faixa") or 0,
            lancar=quebra, notificar=avisos.append,
            trava=nullcontext)
        assert r["ok"] is True and r["fila"] is False
        assert rp.pedido_por_id(p["id"], banco=bancos["pedidos"])["status"] \
            == "pendente"
        assert any("pendente" in a for a in avisos)


class TestMainDoWorker:
    """`python -m integrations.radio_link --pedido N` — CLI em sandbox."""

    def test_pedido_inexistente_sai_com_erro(
            self, tmp_path: Path, capsys: pytest.CaptureFixture,
            monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(rp, "BANCO_PEDIDOS", tmp_path / "nada.db")
        assert rl.main(["--pedido", "123"]) == 1
        saida = json.loads(capsys.readouterr().out)
        assert saida["motivo"] == "pedido_inexistente"
        assert saida["pedido_id"] == 123

    def test_sucesso_sai_com_zero(
            self, capsys: pytest.CaptureFixture,
            monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            rl, "processar_pedido",
            lambda pid, **_k: {"ok": True, "pedido_id": int(pid)})
        assert rl.main(["--pedido", "7"]) == 0
        assert json.loads(capsys.readouterr().out)["pedido_id"] == 7

    def test_argumento_obrigatorio(self) -> None:
        with pytest.raises(SystemExit):
            rl.main([])


# ---------------------------------------------------------------------------
#  radio_cantores — lista, registro, histórico, sync e limpeza
# ---------------------------------------------------------------------------

class TestListaDoDono:
    """Arquivo simples da lista: comentários preservados, erros em vazio."""

    def test_arquivo_inexistente_e_vazio(self, tmp_path: Path) -> None:
        assert rc._ler(tmp_path / "nao.txt") == []
        assert rc.listar(caminho=tmp_path / "nao.txt") == []

    def test_adicionar_cria_o_arquivo_com_cabecalho(
            self, tmp_path: Path) -> None:
        alvo = tmp_path / "nova" / "cantores.txt"
        assert rc.adicionar("Annita", caminho=alvo) is True
        assert alvo.read_text(encoding="utf-8") == rc.CABECALHO + "Annita\n"
        assert rc.listar(caminho=alvo) == ["Annita"]
        # de novo no MESMO arquivo: idempotente, sem cabeçalho duplicado
        assert rc.adicionar("Annita", caminho=alvo) is False
        assert alvo.read_text(encoding="utf-8").count("# Cantores") == 1

    def test_remover_sem_nome_ou_fora_do_arquivo(
            self, tmp_path: Path) -> None:
        alvo = tmp_path / "cantores.txt"
        alvo.write_text("# comentario\nAnnita\n", encoding="utf-8")
        assert rc.remover("   ", caminho=alvo) is False
        assert rc.remover("Annita", caminho=tmp_path / "nao.txt") is False
        assert rc.remover("Fulano", caminho=alvo) is False
        assert rc.listar(caminho=alvo) == ["Annita"]

    def test_indesejado_sem_nome_e_linha_suja(self, tmp_path: Path) -> None:
        alvo = tmp_path / "cantores.txt"
        alvo.write_text("!!!\nAnnita\n", encoding="utf-8")
        assert rc.indesejado("", caminho=alvo) is False
        assert rc.indesejado("Annita", caminho=alvo) is True

    def test_linhas_do_arquivo(self, tmp_path: Path) -> None:
        assert rc.linhas_do_arquivo(caminho=tmp_path / "nao.txt") == \
            rc.CABECALHO
        alvo = tmp_path / "cantores.txt"
        alvo.write_text("# dono\nAnnita\n", encoding="utf-8")
        assert rc.linhas_do_arquivo(caminho=alvo) == "# dono\nAnnita\n"


class TestRegistroDoDono:
    """`data/radio_apagar_depois.json` corrompido não derruba nada."""

    def test_json_invalido_devolve_lista_vazia(self, tmp_path: Path) -> None:
        reg = tmp_path / "reg.json"
        reg.write_text("{lixo", encoding="utf-8")
        assert rc._ler_registro(reg) == []
        assert rc.pendentes(registro=reg) == []

    def test_itens_que_nao_sao_dict_sao_descartados(
            self, tmp_path: Path) -> None:
        reg = _registro_de(tmp_path)
        reg.write_text(json.dumps([1, "x", _item_registro()]),
                       encoding="utf-8")
        assert len(rc._ler_registro(reg)) == 1

    def test_registrar_sem_nada_nao_grava(self, tmp_path: Path) -> None:
        reg = tmp_path / "reg.json"
        assert rc.registrar_para_apagar("", "", registro=reg) is None
        assert not reg.exists()


class TestHistoricoAzuracast:
    """Últimas faixas da estação — `_azuracast` dublê, sem chamada real."""

    def _falso(self, monkeypatch, retorno) -> None:
        monkeypatch.setattr(rp, "_azuracast",
                            lambda *_a, **_k: retorno)

    def test_parseia_artista_e_titulo(self, monkeypatch) -> None:
        self._falso(monkeypatch, (200, [
            {"song": {"artist": "Fernandinho", "title": "Todas as Coisas"}},
            {"song": {}},
            None,
        ]))
        assert rc.historico_azuracast(3) == [
            {"artista": "Fernandinho", "titulo": "Todas as Coisas"},
            {"artista": "", "titulo": ""},
            {"artista": "", "titulo": ""},
        ]

    def test_estacao_fora_devolve_vazio(self, monkeypatch) -> None:
        self._falso(monkeypatch, (503, None))
        assert rc.historico_azuracast() == []

    def test_resposta_que_nao_e_lista_devolve_vazio(
            self, monkeypatch) -> None:
        self._falso(monkeypatch, (200, {"erro": 1}))
        assert rc.historico_azuracast() == []


class TestRessincronizar:
    """Refaz banco/.m3u/sync no venv do acervo — subprocesso dublê."""

    def _python_falso(self, tmp_path: Path) -> Path:
        py = tmp_path / "python-do-acervo"
        py.write_text("", encoding="utf-8")
        return py

    def test_venv_ausente_nao_roda_nada(
            self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(rc, "MUSICA_PYTHON", tmp_path / "sem-venv")
        assert rc._ressincronizar() is False

    def test_sucesso_no_venv_do_acervo(
            self, tmp_path: Path, monkeypatch) -> None:
        py = self._python_falso(tmp_path)
        monkeypatch.setattr(rc, "MUSICA_PYTHON", py)
        visto: dict = {}

        def run(cmd, **kwargs):
            visto.update(cmd=cmd, cwd=kwargs.get("cwd"))
            return SimpleNamespace(returncode=0, stdout="")

        monkeypatch.setattr(rc.subprocess, "run", run)
        assert rc._ressincronizar() is True
        assert visto["cmd"][0] == str(py)
        assert visto["cwd"] == str(rc.BASE_MUSICAS)
        assert "indexar_acervo" in visto["cmd"][2]

    def test_codigo_de_erro_do_sync(
            self, tmp_path: Path, monkeypatch) -> None:
        py = self._python_falso(tmp_path)
        monkeypatch.setattr(rc, "MUSICA_PYTHON", py)
        monkeypatch.setattr(
            rc.subprocess, "run",
            lambda *a, **k: SimpleNamespace(returncode=2, stdout=""))
        assert rc._ressincronizar() is False

    def test_processo_morto(
            self, tmp_path: Path, monkeypatch) -> None:
        py = self._python_falso(tmp_path)
        monkeypatch.setattr(rc, "MUSICA_PYTHON", py)

        def run(*_a, **_k):
            raise OSError("venv sumiu")

        monkeypatch.setattr(rc.subprocess, "run", run)
        assert rc._ressincronizar() is False

    def test_timeout_do_sync(
            self, tmp_path: Path, monkeypatch) -> None:
        py = self._python_falso(tmp_path)
        monkeypatch.setattr(rc, "MUSICA_PYTHON", py)

        def run(*_a, **_k):
            raise subprocess.TimeoutExpired("python", 300)

        monkeypatch.setattr(rc.subprocess, "run", run)
        assert rc._ressincronizar() is False


class TestApagarArquivo:
    """Só apaga arquivo DENTRO do acervo — e nunca uma pasta."""

    def test_caminho_vazio_nao_apaga(self) -> None:
        assert rc._apagar_arquivo("") is False

    def test_diretorio_nao_e_apagado(self, tmp_path: Path) -> None:
        (rc.BASE_MUSICAS / "pasta").mkdir(parents=True, exist_ok=True)
        assert rc._apagar_arquivo("pasta") is False
        assert (rc.BASE_MUSICAS / "pasta").exists()

    def test_arquivo_do_acervo_e_apagado(self, tmp_path: Path) -> None:
        alvo = rc.BASE_MUSICAS / "ok.mp3"
        alvo.write_bytes(b"mp3")
        assert rc._apagar_arquivo("ok.mp3") is True
        assert not alvo.exists()


class TestLimparTocadosComplementar:
    """A limpeza do webhook NUNCA levanta — os ramos de erro provam isso."""

    def test_registro_vazio_nem_chama_as_fontes(self, tmp_path: Path) -> None:
        reg = _registro_de(tmp_path)
        reg.write_text("[]", encoding="utf-8")

        def nao_deve(*_a, **_k):
            raise AssertionError("não deveria consultar a rádio")

        r = rc.limpar_tocados(registro=reg,
                              ressincronizar=nao_deve, apagar=nao_deve)
        assert r == {"apagadas": 0, "restantes": 0, "sync": False,
                     "lembretes": 0}

    def test_aguardando_nao_e_apagado_antes_das_24h(
            self, tmp_path: Path) -> None:
        reg = _registro_de(tmp_path, _item_registro(
            decidir_ate=(datetime.now(timezone.utc) + timedelta(hours=20))
            .isoformat(timespec="seconds")))
        r = rc.limpar_tocados(registro=reg,
                              ressincronizar=lambda: True, apagar=lambda _c: True)
        assert (r["apagadas"], r["restantes"]) == (0, 1)

    def test_item_ja_apagado_nao_conta_de_novo(self, tmp_path: Path) -> None:
        reg = _registro_de(tmp_path,
                           _item_registro(status="apagada"))

        def nao_deve(*_a, **_k):
            raise AssertionError("nada a sincronizar")

        r = rc.limpar_tocados(registro=reg,
                              ressincronizar=nao_deve,
                              apagar=nao_deve)
        assert r == {"apagadas": 0, "restantes": 0, "sync": False,
                     "lembretes": 0}

    def test_criado_em_invalido_nao_vence_o_prazo(
            self, tmp_path: Path) -> None:
        reg = _registro_de(tmp_path,
                           _item_registro(criado_em="ontem-qualquer"))
        r = rc.limpar_tocados(registro=reg,
                              ressincronizar=lambda: True,
                              apagar=lambda _c: True)
        assert (r["apagadas"], r["restantes"]) == (0, 1)

    def test_erro_ao_apagar_o_arquivo_nao_para_a_fila(
            self, tmp_path: Path) -> None:
        reg = _registro_de(tmp_path, _item_registro(caminho="x.mp3",
                                                   decidir_ate=_vencido()))

        def trava(_caminho):
            raise PermissionError("arquivo travado")

        r = rc.limpar_tocados(
            registro=reg,
            ressincronizar=lambda: True, apagar=trava)
        assert (r["apagadas"], r["restantes"], r["sync"]) == (1, 0, True)
        assert rc.pendentes(registro=reg) == []

    def test_erro_na_sincronizacao_devolve_sync_falso(
            self, tmp_path: Path) -> None:
        reg = _registro_de(tmp_path, _item_registro(decidir_ate=_vencido()))

        def quebra():
            raise RuntimeError("sync do acervo morreu")

        r = rc.limpar_tocados(
            registro=reg,
            ressincronizar=quebra, apagar=lambda _c: True)
        assert r["apagadas"] == 1 and r["sync"] is False

