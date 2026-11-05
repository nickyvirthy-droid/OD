"""
OMEGA DRAKON • PYTEST
Testes do pedido por LINK do YouTube (ordem do dono, 02/11 — item 1).

Nada de rede, yt-dlp ou AzuraCast: a extração da lista, o pipeline do
acervo, a fila e o aviso ao dono são injetáveis. O que se prova aqui é o
contrato do worker: o que vira pedido, o que é repetido, a lista que
baixa todas mas só toca a primeira e a caderneta do dono (link + conta).
"""

from __future__ import annotations

import contextlib
import sqlite3
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from integrations import radio_link as rl
from integrations import radio_pro as rp


VIDEO = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
VIDEO_ID = "dQw4w9WgXcQ"
LISTA = "https://www.youtube.com/playlist?list=PL1234567890abcdef"


def _acervo(banco: Path) -> Path:
    conn = sqlite3.connect(str(banco))
    conn.execute("""CREATE TABLE musicas (
        caminho TEXT PRIMARY KEY, artista TEXT, titulo TEXT, genero TEXT,
        atualizado_em TEXT)""")
    conn.commit()
    conn.close()
    return banco


def _adicionar(banco: Path, caminho: str, artista: str, titulo: str) -> None:
    conn = sqlite3.connect(str(banco))
    conn.execute("INSERT INTO musicas (caminho, artista, titulo)"
                 " VALUES (?, ?, ?)", (caminho, artista, titulo))
    conn.commit()
    conn.close()


@pytest.fixture()
def bancos(tmp_path: Path) -> dict[str, Path]:
    return {"acervo": _acervo(tmp_path / "acervo.db"),
            "pedidos": tmp_path / "pedidos.db"}


def _criar(bancos, usuario="ana", link=VIDEO, recado="", agora=None):
    return rp.criar_pedido_link(usuario, link, recado,
                                banco=bancos["pedidos"], agora=agora)


def _status(banco: Path, pedido_id: int) -> str:
    conn = sqlite3.connect(str(banco))
    try:
        return conn.execute("SELECT status FROM pedidos WHERE id = ?",
                            (pedido_id,)).fetchone()[0]
    finally:
        conn.close()


class TestLinkYoutube:
    @pytest.mark.parametrize("entrada,esperado", [
        (VIDEO, VIDEO),
        (f"https://youtu.be/{VIDEO_ID}", VIDEO),
        (f"youtu.be/{VIDEO_ID}?si=abc", VIDEO),
        (f"https://www.youtube.com/shorts/{VIDEO_ID}?feature=share", VIDEO),
        (f"https://m.youtube.com/watch?v={VIDEO_ID}&t=30", VIDEO),
        (f"https://music.youtube.com/watch?v={VIDEO_ID}&si=x", VIDEO),
        (f"https://www.youtube.com/embed/{VIDEO_ID}", VIDEO),
        (LISTA, LISTA),
        ("https://www.youtube.com/watch?list=PL1234567890abcdef", LISTA),
    ])
    def test_aceita_e_canoniza(self, entrada, esperado) -> None:
        assert rp.link_do_youtube(entrada) == esperado

    @pytest.mark.parametrize("entrada", [
        "", "   ", "https://vimeo.com/123", "https://example.com/youtube.com",
        "https://www.youtube.com/watch?v=curto", "javascript:alert(1)",
        "https://www.youtube.com/watch",
    ])
    def test_recusa_o_que_nao_e_youtube(self, entrada) -> None:
        assert rp.link_do_youtube(entrada) == ""

    def test_video_dentro_de_lista_continua_video(self) -> None:
        """Compartilhar vídeo com &list não vira "baixa a lista toda"."""
        assert rp.link_do_youtube(
            f"https://www.youtube.com/watch?v={VIDEO_ID}"
            "&list=PL1234567890abcdef&index=2") == VIDEO


class TestCriarPedidoLink:
    def test_nasce_baixando_com_link_e_conta(self, bancos) -> None:
        p = _criar(bancos, recado="  toca   essa  ")
        assert p["status"] == "baixando" and p["id"] > 0
        assert p["link"] == VIDEO
        assert p["caminho"] == "" and p["titulo"] == ""
        assert p["recado"] == "toca essa"
        guardado = rp.pedido_por_id(p["id"], banco=bancos["pedidos"])
        assert guardado["usuario"] == "ana" and guardado["link"] == VIDEO
        assert rp.meus_pedidos("ana", banco=bancos["pedidos"])[0]["link"] == VIDEO

    def test_link_invalido_nao_cria(self, bancos) -> None:
        with pytest.raises(ValueError, match="link_invalido"):
            _criar(bancos, link="https://vimeo.com/1")
        assert rp.meus_pedidos("ana", banco=bancos["pedidos"]) == []

    def test_recado_longo_nao_cria(self, bancos) -> None:
        with pytest.raises(ValueError, match="recado_longo"):
            _criar(bancos, recado="x" * (rp.RECADO_MAX + 1))

    def test_sem_login_nao_cria(self, bancos) -> None:
        with pytest.raises(ValueError, match="login_obrigatorio"):
            _criar(bancos, usuario="  ")

    def test_cooldown_de_30_minutos(self, bancos) -> None:
        agora = datetime(2026, 11, 5, 12, 0, 0)
        _criar(bancos, agora=agora)
        with pytest.raises(ValueError, match="limite_tempo"):
            _criar(bancos, agora=agora + timedelta(minutes=29))
        outro = _criar(bancos, usuario="bia", link=LISTA,
                       agora=agora + timedelta(minutes=31))
        assert outro["status"] == "baixando"

    def test_mesmo_link_de_outra_conta_e_repetido(self, bancos) -> None:
        _criar(bancos)
        with pytest.raises(ValueError, match="musica_repetida"):
            _criar(bancos, usuario="bia")

    def test_link_rejeitado_pode_ser_pedido_de_novo(self, bancos) -> None:
        p = _criar(bancos)
        rp.atualizar_pedido(p["id"], status="rejeitada",
                            motivo="falha_download", banco=bancos["pedidos"])
        novo = _criar(bancos, usuario="bia")
        assert novo["id"] != p["id"]

    def test_banco_antigo_ganha_as_colunas_novas(self, tmp_path: Path) -> None:
        """Migração idempotente: pedidos de antes do link continuam abrindo."""
        banco = tmp_path / "antigo.db"
        conn = sqlite3.connect(str(banco))
        conn.execute("""CREATE TABLE pedidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, criado_em TEXT NOT NULL,
            usuario TEXT NOT NULL, artista TEXT NOT NULL DEFAULT '',
            titulo TEXT NOT NULL DEFAULT '', caminho TEXT NOT NULL,
            recado TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pendente')""")
        conn.execute("INSERT INTO pedidos (criado_em, usuario, caminho)"
                     " VALUES ('2026-11-01T10:00:00', 'ana', 'x.mp3')")
        conn.commit()
        conn.close()
        antigo = rp.meus_pedidos("ana", banco=banco)
        assert antigo[0]["link"] == "" and antigo[0]["motivo"] == ""
        p = _criar({"pedidos": banco}, link=VIDEO)
        assert rp.pedido_por_id(p["id"], banco=banco)["link"] == VIDEO


class TestProcessarPedido:
    def _extrair(self, *urls: str, titulo: str = ""):
        entradas = [{"url": u, "title": titulo or f"faixa {i}"}
                    for i, u in enumerate(urls)]
        return lambda _link: entradas

    def _rodar(self, bancos, novos=(), codigo=0, chamadas=None):
        def rodar(urls, **_kw):
            if chamadas is not None:
                chamadas.append(list(urls))
            for caminho, artista, titulo in novos:
                _adicionar(bancos["acervo"], caminho, artista, titulo)
            return codigo
        return rodar

    def _na_fila(self, bancos):
        return lambda p: rp.marcar_status(int(p["id"]), "na_fila",
                                          banco=bancos["pedidos"])

    def test_faixa_nova_entra_na_fila(self, bancos) -> None:
        p = _criar(bancos)
        avisos: list[str] = []
        chamadas: list[list[str]] = []
        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"], banco_acervo=bancos["acervo"],
            extrair=self._extrair(VIDEO, titulo="Artista - Título"),
            rodar=self._rodar(
                bancos, [("acervo/Outros/Artista - Título.mp3",
                          "Artista", "Título")], chamadas=chamadas),
            lancar=self._na_fila(bancos),
            notificar=avisos.append,
            trava=contextlib.nullcontext,
        )
        assert r["ok"] is True and r["fila"] is True
        assert chamadas == [[VIDEO]]
        guardado = rp.pedido_por_id(p["id"], banco=bancos["pedidos"])
        assert guardado["status"] == "na_fila"
        assert guardado["artista"] == "Artista"
        assert guardado["titulo"] == "Título"
        assert guardado["caminho"].endswith("Artista - Título.mp3")
        assert any("na fila da rádio" in a for a in avisos)
        assert any(VIDEO in a for a in avisos)

    def test_repetida_pelo_titulo_nem_baixa(self, bancos) -> None:
        _adicionar(bancos["acervo"],
                   "acervo/Gospel/Fernandinho - Todas as Coisas.mp3",
                   "Fernandinho", "Todas as Coisas")
        p = _criar(bancos)
        chamadas: list[list[str]] = []
        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"], banco_acervo=bancos["acervo"],
            extrair=self._extrair(
                VIDEO, titulo="Fernandinho - Todas as Coisas (Ao Vivo)"),
            rodar=self._rodar(bancos, chamadas=chamadas),
            lancar=self._na_fila(bancos),
            notificar=lambda _t: None, trava=contextlib.nullcontext,
        )
        assert r["motivo"] == "musica_repetida"
        assert chamadas == [], "repetida não gasta download"

    def test_repetida_nao_entra_e_avisa(self, bancos) -> None:
        p = _criar(bancos)
        avisos: list[str] = []
        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"], banco_acervo=bancos["acervo"],
            extrair=self._extrair(VIDEO),
            rodar=self._rodar(bancos, codigo=0),       # dedupe: nada novo
            lancar=self._na_fila(bancos),
            notificar=avisos.append,
            trava=contextlib.nullcontext,
        )
        assert r["ok"] is False and r["motivo"] == "musica_repetida"
        guardado = rp.pedido_por_id(p["id"], banco=bancos["pedidos"])
        assert guardado["status"] == "rejeitada"
        assert guardado["motivo"] == "musica_repetida"
        assert any("musica_repetida" in a for a in avisos)

    def test_falha_do_pipeline_marca_falha_download(self, bancos) -> None:
        p = _criar(bancos)
        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"], banco_acervo=bancos["acervo"],
            extrair=self._extrair(VIDEO),
            rodar=self._rodar(bancos, codigo=1),
            lancar=self._na_fila(bancos),
            notificar=lambda _t: None,
            trava=contextlib.nullcontext,
        )
        assert r["motivo"] == "falha_download"
        assert _status(bancos["pedidos"], p["id"]) == "rejeitada"

    def test_link_sem_entradas_e_invalido(self, bancos) -> None:
        p = _criar(bancos)
        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"], banco_acervo=bancos["acervo"],
            extrair=lambda _l: [],
            rodar=lambda _u, **_kw: 0, lancar=self._na_fila(bancos),
            notificar=lambda _t: None, trava=contextlib.nullcontext,
        )
        assert r["motivo"] == "link_invalido"

    def test_playlist_baixa_todas_mas_so_a_primeira_toca(self, bancos) -> None:
        urls = [VIDEO, f"https://youtu.be/{VIDEO_ID}?t=10",
                "https://youtu.be/aaaaaaaaaaa"]
        p = _criar(bancos, link=LISTA)
        chamadas: list[list[str]] = []
        avisos: list[str] = []
        primeira = {"feito": False}

        def rodar(lista, **_kw):
            chamadas.append(list(lista))
            if not primeira["feito"]:
                primeira["feito"] = True
                _adicionar(bancos["acervo"], "acervo/Outros/Um - Dois.mp3",
                           "Um", "Dois")
            return 0

        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"], banco_acervo=bancos["acervo"],
            extrair=self._extrair(*urls, titulo="Um - Dois"),
            rodar=rodar, lancar=self._na_fila(bancos),
            notificar=avisos.append, trava=contextlib.nullcontext,
        )
        assert r["fila"] is True
        assert chamadas[0] == [VIDEO], "só a primeira toca agora"
        assert chamadas[1] == urls[1:], "as outras baixam em segundo plano"
        assert any("restante" in a for a in avisos)

    def test_resto_vai_em_lotes_com_timeout_proporcional(self, bancos) -> None:
        # 25 entradas: a 1ª toca, as 24 restantes vão em lotes de 10/10/4.
        urls = [VIDEO] + [f"https://youtu.be/{i:011d}" for i in range(24)]
        p = _criar(bancos, link=LISTA)
        chamadas: list[list[str]] = []
        tempos: list[int] = []

        def rodar(lista, **kw):
            chamadas.append(list(lista))
            tempos.append(kw.get("timeout"))
            if len(chamadas) == 1:
                _adicionar(bancos["acervo"],
                           "acervo/Outros/Um - Dois.mp3", "Um", "Dois")
            return 0

        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"], banco_acervo=bancos["acervo"],
            extrair=self._extrair(*urls, titulo="Um - Dois"),
            rodar=rodar, lancar=self._na_fila(bancos),
            notificar=lambda _t: None, trava=contextlib.nullcontext,
        )
        assert r["fila"] is True
        assert [len(c) for c in chamadas[1:]] == [10, 10, 4]
        assert tempos[1:] == [rl.timeout_do_lote(n) for n in (10, 10, 4)]
        assert all(t >= rl.TIMEOUT_PRIMEIRA for t in tempos[1:])

    def test_lote_que_falha_nao_derruba_o_resto(self, bancos) -> None:
        # 11 restantes em 2 lotes: o 1º estoura o tempo, o 2º continua.
        urls = [VIDEO] + [f"https://youtu.be/{i:011d}" for i in range(11)]
        p = _criar(bancos, link=LISTA)
        chamadas: list[list[str]] = []
        avisos: list[str] = []

        def rodar(lista, **kw):
            chamadas.append(list(lista))
            if len(chamadas) == 1:
                _adicionar(bancos["acervo"],
                           "acervo/Outros/Um - Dois.mp3", "Um", "Dois")
                return 0
            if len(chamadas) == 2:
                raise subprocess.TimeoutExpired("musica.py", 3000)
            return 0

        rl.processar_pedido(
            p["id"], banco=bancos["pedidos"], banco_acervo=bancos["acervo"],
            extrair=self._extrair(*urls, titulo="Um - Dois"),
            rodar=rodar, lancar=self._na_fila(bancos),
            notificar=avisos.append, trava=contextlib.nullcontext,
        )
        assert len(chamadas) == 3, "o lote que falhou não cancela o seguinte"
        assert any("com falha" in a for a in avisos)

    def test_escolhe_a_faixa_da_primeira_entrada(self, bancos) -> None:
        p = _criar(bancos)
        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"], banco_acervo=bancos["acervo"],
            extrair=self._extrair(VIDEO, titulo="Banda Certa - A Música"),
            rodar=self._rodar(bancos, [
                ("acervo/Outros/Outra - Faixa.mp3", "Outra", "Faixa"),
                ("acervo/Outros/Banda Certa - A Música.mp3",
                 "Banda Certa", "A Música"),
            ]),
            lancar=self._na_fila(bancos),
            notificar=lambda _t: None, trava=contextlib.nullcontext,
        )
        assert r["pedido"]["artista"] == "Banda Certa"

    def test_ja_processado_nao_baixa_de_novo(self, bancos) -> None:
        p = _criar(bancos)
        rp.atualizar_pedido(p["id"], status="na_fila",
                            banco=bancos["pedidos"])
        chamadas: list[list[str]] = []
        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"], banco_acervo=bancos["acervo"],
            extrair=lambda _l: [{"url": VIDEO, "title": ""}],
            rodar=self._rodar(bancos, chamadas=chamadas),
            lancar=self._na_fila(bancos), notificar=lambda _t: None,
            trava=contextlib.nullcontext,
        )
        assert r["motivo"] == "ja_processado" and chamadas == []


class TestTimeoutDoLote:
    def test_cresce_com_o_tamanho_e_respeita_o_teto(self) -> None:
        assert rl.timeout_do_lote(1) == rl.TIMEOUT_PRIMEIRA
        assert rl.timeout_do_lote(10) == rl.SEGUNDOS_POR_FAIXA * 10
        assert rl.timeout_do_lote(10**6) == rl.TIMEOUT_RESTO


class TestAvisoEDisparo:
    def test_aviso_quebrado_nao_derruba(self) -> None:
        def quebra(_texto):
            raise RuntimeError("telegram fora")
        assert rl.notificar_dono("oi", enviar=quebra) is False

    def test_sem_token_nao_tenta_rede(self, monkeypatch) -> None:
        for chave in ("OD_TELEGRAM_USUARIOS_TOKEN", "TELEGRAM_BOT_TOKEN",
                      "OD_TELEGRAM_USUARIOS_CHAT", "OD_TELEGRAM_ADMINS"):
            monkeypatch.delenv(chave, raising=False)
        assert rl.notificar_dono("oi") is False

    def test_disparo_usa_processo_desanexado(self, tmp_path: Path,
                                             monkeypatch) -> None:
        monkeypatch.setattr(rl, "LOG_DIR", tmp_path / "logs")
        visto: dict = {}

        class FakeProc:
            pass

        def fake_popen(args, **kwargs):
            visto["args"] = args
            visto.update(kwargs)
            return FakeProc()

        assert rl.iniciar_processamento(7, popen=fake_popen)
        assert visto["args"][-2:] == ["--pedido", "7"]
        assert "integrations.radio_link" in visto["args"]
        assert visto["start_new_session"] is True
        assert (tmp_path / "logs" / "radio_link_7.log").exists()


class TestHandlerEPagina:
    def test_handler_avisa_na_criacao_e_dispara_o_worker(self) -> None:
        from integrations.api import server

        fonte = Path(server.__file__).read_text(encoding="utf-8")
        trecho = fonte.split("def api_radio_pro_pedido", 1)[1].split("def ", 1)[0]
        assert "criar_pedido_link" in trecho
        assert "iniciar_processamento" in trecho
        assert "Pedido por LINK" in trecho
        assert '"link_invalido": 400' in trecho
        assert "falha_agendamento" in trecho
        # o pedido do catálogo continua na fila real (guarda de 04/11)
        assert "lancar_pedido_na_fila" in trecho
        assert "na fila da rádio" in trecho

    def test_pagina_tem_campo_de_link_e_rotulos(self) -> None:
        from integrations.api import server

        pagina = (Path(server.__file__).resolve().parents[2]
                  / "site" / "radio-pro.html").read_text(encoding="utf-8")
        assert 'id="link"' in pagina
        assert "corpo.link" in pagina
        assert "baixando" in pagina and "rejeitada" in pagina
        assert "musica_repetida" in pagina
