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

from integrations import radio_cantores as rc
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

    def test_video_dentro_de_lista_preserva_playlist(self) -> None:
        """Compartilhar vídeo com &list preserva a lista e o vídeo (baixa todas, toca a indicada)."""
        esperado = f"https://www.youtube.com/playlist?list=PL1234567890abcdef&v={VIDEO_ID}"
        assert rp.link_do_youtube(
            f"https://www.youtube.com/watch?v={VIDEO_ID}"
            "&list=PL1234567890abcdef&index=2") == esperado
        # Funciona também pelo encurtador youtu.be
        assert rp.link_do_youtube(
            f"https://youtu.be/{VIDEO_ID}?list=PL1234567890abcdef") == esperado



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

    def test_playlist_com_video_especifico_toca_ele_primeiro(self, bancos) -> None:
        """Quando a playlist veio de watch?v=B&list=..., o vídeo B toca primeiro."""
        url_a = f"https://www.youtube.com/watch?v=aaaaaaaaaaa"
        url_b = f"https://www.youtube.com/watch?v=bbbbbbbbbbb"
        url_c = f"https://www.youtube.com/watch?v=ccccccccccc"
        urls = [url_a, url_b, url_c]
        link = f"{LISTA}&v=bbbbbbbbbbb"
        p = _criar(bancos, link=link)
        chamadas: list[list[str]] = []

        def rodar(lista, **_kw):
            chamadas.append(list(lista))
            _adicionar(bancos["acervo"], "acervo/Rock/B - FaixaB.mp3", "B", "FaixaB")
            return 0

        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"], banco_acervo=bancos["acervo"],
            extrair=self._extrair(*urls, titulo="B - FaixaB"),
            rodar=rodar, lancar=self._na_fila(bancos),
            notificar=lambda _: None, trava=contextlib.nullcontext,
        )
        assert r["fila"] is True
        assert chamadas[0] == [url_b], "o vídeo B foi priorizado para tocar primeiro"
        assert chamadas[1] == [url_a, url_c], "as outras faixas vão para o acervo"

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


class TestCantorIndesejadoNoLink:
    """A3: o link já entrega o artista — a faixa nasce marcada, sem esperar
    a fila aceitar nem a IA acertar o nome."""

    def _lista(self, tmp_path: Path, *nomes: str) -> Path:
        caminho = tmp_path / "cantores_indesejados.txt"
        caminho.write_text("\n".join(nomes) + "\n", encoding="utf-8")
        return caminho

    @staticmethod
    def _rodar(banco: Path, artista: str, titulo: str):
        def rodar(_urls, **_kw):
            _adicionar(banco, f"acervo/Outros/{artista} - {titulo}.mp3",
                       artista, titulo)
            return 0
        return rodar

    def _processar(self, bancos, tmp_path, *, artistas, titulo, **kwargs):
        lista = self._lista(tmp_path, "Annita")
        registro = tmp_path / "radio_apagar_depois.json"
        p = _criar(bancos)
        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"], banco_acervo=bancos["acervo"],
            extrair=lambda _l: [{"url": VIDEO, "title": titulo,
                                 "artistas": artistas}],
            notificar=lambda _t: None, trava=contextlib.nullcontext,
            cantores_lista=lista, cantores_registro=registro, **kwargs)
        return p, r, registro

    def test_uploader_na_lista_marca_mesmo_com_a_fila_recusando(
            self, bancos, tmp_path) -> None:
        p, r, registro = self._processar(
            bancos, tmp_path, artistas=["Annita - Topic"],
            titulo="Annita - Envolver",
            rodar=self._rodar(bancos["acervo"], "Annita", "Envolver"),
            lancar=lambda pedido: pedido,          # AzuraCast recusou
        )
        assert r["fila"] is False
        assert rp.pedido_por_id(p["id"], banco=bancos["pedidos"])["status"] \
            == "pendente"
        pendentes = rc.pendentes(registro=registro)
        assert len(pendentes) == 1, "marcou antes de tentar a fila"
        assert pendentes[0]["artista"] == "Annita"
        assert pendentes[0]["titulo"] == "Envolver"
        assert pendentes[0]["caminho"].endswith("Annita - Envolver.mp3")

    def test_pista_do_link_vale_quando_a_ia_tagueia_errado(
            self, bancos, tmp_path) -> None:
        _, r, registro = self._processar(
            bancos, tmp_path, artistas=["Annita"],
            titulo="Clipe oficial",
            rodar=self._rodar(bancos["acervo"], "Desconhecido", "Envolver"),
            lancar=lambda p: rp.marcar_status(int(p["id"]), "na_fila",
                                              banco=bancos["pedidos"]),
        )
        assert r["fila"] is True
        pendentes = rc.pendentes(registro=registro)
        assert len(pendentes) == 1
        assert pendentes[0]["artista"] == "Desconhecido", \
            "grava o artista real do acervo, que é o que o histórico casa"
        assert pendentes[0]["titulo"] == "Envolver"

    def test_fora_da_lista_nao_marca(self, bancos, tmp_path) -> None:
        _, r, registro = self._processar(
            bancos, tmp_path, artistas=["Fulano"],
            titulo="Fulano - Musica",
            rodar=self._rodar(bancos["acervo"], "Fulano", "Musica"),
            lancar=lambda p: rp.marcar_status(int(p["id"]), "na_fila",
                                              banco=bancos["pedidos"]),
        )
        assert r["fila"] is True
        assert rc.pendentes(registro=registro) == []

    def test_lista_de_cantor_indesejado_baixa_so_a_primeira(
            self, bancos, tmp_path) -> None:
        lista = self._lista(tmp_path, "Annita")
        registro = tmp_path / "apagar.json"
        p = _criar(bancos, link=LISTA)
        urls = [VIDEO, "https://youtu.be/aaaaaaaaaaa",
                "https://youtu.be/bbbbbbbbbbb"]
        entradas = [{"url": u, "title": f"Annita - Faixa {i}",
                     "artistas": ["Annita"]} for i, u in enumerate(urls)]
        chamadas: list[list[str]] = []

        def rodar(bloco, **_kw):
            chamadas.append(list(bloco))
            if len(chamadas) == 1:
                _adicionar(bancos["acervo"],
                           "acervo/Outros/Annita - Faixa 0.mp3",
                           "Annita", "Faixa 0")
            return 0

        avisos: list[str] = []
        rl.processar_pedido(
            p["id"], banco=bancos["pedidos"], banco_acervo=bancos["acervo"],
            extrair=lambda _l: entradas, rodar=rodar,
            lancar=lambda ped: rp.marcar_status(
                int(ped["id"]), "na_fila", banco=bancos["pedidos"]),
            notificar=avisos.append, trava=contextlib.nullcontext,
            cantores_lista=lista, cantores_registro=registro,
        )
        assert chamadas == [[VIDEO]], "o resto do cantor recusado nem baixa"
        assert any("cantor indesejado" in a and "nenhuma" in a
                   for a in avisos)

    def test_lista_mista_baixa_so_as_faixas_aceitas(
            self, bancos, tmp_path) -> None:
        lista = self._lista(tmp_path, "Annita")
        registro = tmp_path / "apagar.json"
        p = _criar(bancos, link=LISTA)
        recusada = "https://youtu.be/aaaaaaaaaaa"
        aceita = "https://youtu.be/bbbbbbbbbbb"
        entradas = [{"url": VIDEO, "title": "Annita - Faixa 0",
                     "artistas": ["Annita"]},
                    {"url": recusada, "title": "Annita - Faixa 1",
                     "artistas": ["Annita - Topic"]},
                    {"url": aceita, "title": "Fulano - Faixa 2",
                     "artistas": ["Fulano"]}]
        chamadas: list[list[str]] = []

        def rodar(bloco, **_kw):
            chamadas.append(list(bloco))
            if len(chamadas) == 1:
                _adicionar(bancos["acervo"],
                           "acervo/Outros/Annita - Faixa 0.mp3",
                           "Annita", "Faixa 0")
            return 0

        rl.processar_pedido(
            p["id"], banco=bancos["pedidos"], banco_acervo=bancos["acervo"],
            extrair=lambda _l: entradas, rodar=rodar,
            lancar=lambda ped: rp.marcar_status(
                int(ped["id"]), "na_fila", banco=bancos["pedidos"]),
            notificar=lambda _t: None, trava=contextlib.nullcontext,
            cantores_lista=lista, cantores_registro=registro,
        )
        assert chamadas == [[VIDEO], [aceita]]
        assert recusada not in [u for bloco in chamadas for u in bloco]

    def test_pistas_juntam_metadados_e_titulo(self) -> None:
        pistas = rl._pistas_de_artista(
            {"title": "Annita - Envolver (Clipe Oficial)",
             "artistas": ["Annita - Topic", "AnnitaVEVO"]})
        assert pistas == ["Annita"]


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



class TestMusicaBloqueadaNoLink:
    """Música bloqueada em rádio que aceita pedidos (ordem do dono, 17/11).

    Regra: o ÚNICO bloqueio de download é o limite de tamanho/duração do
    pipeline. Pedido AVULSO de faixa bloqueada baixa, é analisado e entra na
    fila — toca UMA vez para quem pediu e sai, igual ao cantor indesejado.
    Em LISTA, a lista é analisada e as bloqueadas nem são baixadas."""

    @staticmethod
    def _sem_cantores_indesejados(tmp_path: Path) -> Path:
        """Lista de cantores VAZIA: o teste é sobre música bloqueada, não
        sobre o arquivo real do dono (que tem Annita)."""
        caminho = tmp_path / "cantores_indesejados.txt"
        caminho.write_text("", encoding="utf-8")
        return caminho

    def _bloqueadas(self, tmp_path: Path, *pares: tuple[str, str]) -> Path:
        caminho = tmp_path / "musicas_bloqueadas.txt"
        caminho.write_text(
            "".join(f"{a} | {t}\n" for a, t in pares), encoding="utf-8")
        return caminho

    @staticmethod
    def _rodar(banco: Path, artista: str, titulo: str, chamadas=None):
        def rodar(urls, **_kw):
            if chamadas is not None:
                chamadas.append(list(urls))
            _adicionar(banco, f"acervo/Outros/{artista} - {titulo}.mp3",
                       artista, titulo)
            return 0
        return rodar

    @staticmethod
    def _na_fila(bancos):
        return lambda ped: rp.marcar_status(
            int(ped["id"]), "na_fila", banco=bancos["pedidos"])

    def _processar_avulso(self, bancos, tmp_path, *, titulo, artistas,
                          artista_acervo="Annita", titulo_acervo="Envolver",
                          bloqueadas=(("Annita", "Envolver"),)):
        lista = self._bloqueadas(tmp_path, *bloqueadas)
        registro = tmp_path / "radio_apagar_depois.json"
        cantores = self._sem_cantores_indesejados(tmp_path)
        p = _criar(bancos)
        chamadas: list[list[str]] = []
        avisos: list[str] = []
        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"], banco_acervo=bancos["acervo"],
            extrair=lambda _l: [{"url": VIDEO, "title": titulo,
                                 "artistas": artistas}],
            rodar=self._rodar(bancos["acervo"], artista_acervo,
                              titulo_acervo, chamadas),
            lancar=self._na_fila(bancos), notificar=avisos.append,
            trava=contextlib.nullcontext, musicas_bloqueadas=lista,
            cantores_registro=registro, cantores_lista=cantores,
        )
        return p, r, chamadas, avisos, registro

    def test_avulsa_bloqueada_baixa_e_toca_uma_vez(self, bancos,
                                                   tmp_path) -> None:
        p, r, chamadas, avisos, registro = self._processar_avulso(
            bancos, tmp_path, titulo="Annita - Envolver",
            artistas=["Annita"])
        assert chamadas == [[VIDEO]], "pedido avulso NÃO é recusado"
        assert r["ok"] is True and r["fila"] is True
        assert rp.pedido_por_id(p["id"], banco=bancos["pedidos"])["status"] \
            == "na_fila"
        pendentes = rc.pendentes(registro=registro)
        assert len(pendentes) == 1, "abre a janela de decisão de 24 h"
        assert pendentes[0]["artista"] == "Annita"
        assert pendentes[0]["titulo"] == "Envolver"
        assert pendentes[0]["motivo"] == "musica"
        assert pendentes[0]["decidir_ate"]
        assert any("Decisão necessária" in a and "música bloqueada" in a
                   for a in avisos), avisos
        assert pendentes[0]["caminho"].endswith("Annita - Envolver.mp3")
        assert any("na fila da rádio" in a for a in avisos)

    def test_avulsa_titulo_com_sufixo_tambem_marca(self, bancos,
                                                   tmp_path) -> None:
        _p, r, chamadas, _avisos, registro = self._processar_avulso(
            bancos, tmp_path,
            titulo="Annita - Envolver (Clipe Oficial)", artistas=["Annita"])
        assert chamadas == [[VIDEO]]
        assert r["fila"] is True
        assert [x["titulo"] for x in rc.pendentes(registro=registro)] == \
            ["Envolver"]

    def test_outra_musica_do_mesmo_artista_nao_marca(self, bancos,
                                                     tmp_path) -> None:
        _p, r, chamadas, _avisos, registro = self._processar_avulso(
            bancos, tmp_path, titulo="Annita - Outra", artistas=["Annita"],
            titulo_acervo="Outra")
        assert chamadas == [[VIDEO]] and r["fila"] is True
        assert rc.pendentes(registro=registro) == []

    def test_lista_pula_a_bloqueada_e_baixa_a_permitida(
            self, bancos, tmp_path) -> None:
        lista = self._bloqueadas(tmp_path, ("Annita", "Faixa 0"))
        registro = tmp_path / "apagar.json"
        cantores = self._sem_cantores_indesejados(tmp_path)
        p = _criar(bancos, link=LISTA)
        bloqueada = "https://youtu.be/aaaaaaaaaaa"
        permitida = "https://youtu.be/bbbbbbbbbbb"
        entradas = [{"url": bloqueada, "title": "Annita - Faixa 0",
                     "artistas": ["Annita"]},
                    {"url": permitida, "title": "Fulano - Faixa 1",
                     "artistas": ["Fulano"]}]
        chamadas: list[list[str]] = []
        avisos: list[str] = []

        def rodar(bloco, **_kw):
            chamadas.append(list(bloco))
            _adicionar(bancos["acervo"], "acervo/Outros/Fulano - Faixa 1.mp3",
                       "Fulano", "Faixa 1")
            return 0

        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"], banco_acervo=bancos["acervo"],
            extrair=lambda _l: entradas, rodar=rodar,
            lancar=self._na_fila(bancos), notificar=avisos.append,
            trava=contextlib.nullcontext, musicas_bloqueadas=lista,
            cantores_registro=registro, cantores_lista=cantores,
        )
        assert chamadas == [[permitida]], "lista: só a faixa permitida baixa"
        assert r["fila"] is True
        assert any("bloqueadas" in a for a in avisos)

    def test_lista_toda_bloqueada_e_recusada(self, bancos, tmp_path) -> None:
        lista = self._bloqueadas(tmp_path, ("Annita", "Envolver"))
        cantores = self._sem_cantores_indesejados(tmp_path)
        p = _criar(bancos, link=LISTA)
        entradas = [
            {"url": VIDEO, "title": "Annita - Envolver", "artistas": ["Annita"]},
            {"url": "https://youtu.be/aaaaaaaaaaa",
             "title": "Annita - Envolver (Ao Vivo)", "artistas": ["Annita"]},
        ]
        chamadas: list[list[str]] = []
        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"], banco_acervo=bancos["acervo"],
            extrair=lambda _l: entradas,
            rodar=self._rodar(bancos["acervo"], "Annita", "Envolver",
                              chamadas),
            lancar=self._na_fila(bancos), notificar=lambda _t: None,
            trava=contextlib.nullcontext, musicas_bloqueadas=lista,
            cantores_lista=cantores,
        )
        assert chamadas == []
        assert r["ok"] is False and r["motivo"] == "musica_bloqueada"
        assert rp.pedido_por_id(p["id"], banco=bancos["pedidos"])["status"] \
            == "rejeitada"

    def test_resto_bloqueado_nao_baixa(self, bancos, tmp_path) -> None:
        lista = self._bloqueadas(tmp_path, ("Annita", "Faixa 2"))
        registro = tmp_path / "apagar.json"
        cantores = self._sem_cantores_indesejados(tmp_path)
        p = _criar(bancos, link=LISTA)
        urls = [VIDEO, "https://youtu.be/aaaaaaaaaaa",
                "https://youtu.be/bbbbbbbbbbb"]
        entradas = [{"url": urls[0], "title": "Fulano - Faixa 0",
                     "artistas": ["Fulano"]},
                    {"url": urls[1], "title": "Fulano - Faixa 1",
                     "artistas": ["Fulano"]},
                    {"url": urls[2], "title": "Annita - Faixa 2",
                     "artistas": ["Annita"]}]
        chamadas: list[list[str]] = []

        def rodar(bloco, **_kw):
            chamadas.append(list(bloco))
            if len(chamadas) == 1:
                _adicionar(bancos["acervo"],
                           "acervo/Outros/Fulano - Faixa 0.mp3",
                           "Fulano", "Faixa 0")
            return 0

        rl.processar_pedido(
            p["id"], banco=bancos["pedidos"], banco_acervo=bancos["acervo"],
            extrair=lambda _l: entradas, rodar=rodar,
            lancar=self._na_fila(bancos), notificar=lambda _t: None,
            trava=contextlib.nullcontext, musicas_bloqueadas=lista,
            cantores_registro=registro, cantores_lista=cantores,
        )
        assert chamadas == [[VIDEO], [urls[1]]]
        assert urls[2] not in [u for bloco in chamadas for u in bloco]

    def test_link_que_esconde_o_nome_marca_pos_download(
            self, bancos, tmp_path) -> None:
        """Título "Clipe oficial": o acervo revela o nome e a faixa nasce
        marcada — baixou (não é recusa), mas toca uma vez e sai."""
        p, r, chamadas, _avisos, registro = self._processar_avulso(
            bancos, tmp_path, titulo="Clipe oficial",
            artistas=["Canal do fã"])
        assert chamadas == [[VIDEO]]
        assert r["ok"] is True and r["fila"] is True
        pendentes = rc.pendentes(registro=registro)
        assert len(pendentes) == 1
        assert pendentes[0]["titulo"] == "Envolver"
        conn = sqlite3.connect(str(bancos["acervo"]))
        restantes = conn.execute("SELECT caminho FROM musicas").fetchall()
        conn.close()
        assert restantes, "a faixa fica no acervo até tocar"

    def test_lista_ausente_nao_barra_nada(self, bancos, tmp_path) -> None:
        lista = tmp_path / "nao_existe.txt"
        registro = tmp_path / "apagar.json"
        cantores = self._sem_cantores_indesejados(tmp_path)
        p = _criar(bancos)
        chamadas: list[list[str]] = []
        r = rl.processar_pedido(
            p["id"], banco=bancos["pedidos"], banco_acervo=bancos["acervo"],
            extrair=lambda _l: [{"url": VIDEO, "title": "Fulano - Musica",
                                 "artistas": ["Fulano"]}],
            rodar=self._rodar(bancos["acervo"], "Fulano", "Musica",
                              chamadas),
            lancar=self._na_fila(bancos), notificar=lambda _t: None,
            trava=contextlib.nullcontext, musicas_bloqueadas=lista,
            cantores_registro=registro, cantores_lista=cantores,
        )
        assert chamadas == [[VIDEO]] and r["fila"] is True
        assert rc.pendentes(registro=registro) == []
