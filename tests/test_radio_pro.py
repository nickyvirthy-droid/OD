"""
OMEGA DRAKON • PYTEST
Testes de integrations/radio_pro.py — área do ouvinte LOGADO da rádio
(ordem do dono, 04/11/2026): letra da música com cache, catálogo lido do
acervo.db e a fila de pedidos com recado para a locutora.

Nada de rede e nada do acervo real: o serviço de letras é injetado e os
bancos caem em tmp_path — o módulo roda inteiro em sandbox.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from integrations import radio_pro as rp


# ---------------------------------------------------------------------------
#  Apoio
# ---------------------------------------------------------------------------

def _acervo(banco: Path, musicas: list[tuple[str, str, str, str]] | None = None) -> Path:
    """acervo.db de mentira com o MESMO esquema do pipeline (musica.py)."""
    conn = sqlite3.connect(str(banco))
    conn.execute("""CREATE TABLE musicas (
        caminho TEXT PRIMARY KEY, artista TEXT, titulo TEXT, ano TEXT,
        genero TEXT, curiosidade TEXT, pronuncia_artista TEXT,
        pronuncia_titulo TEXT, duracao_s INTEGER, bytes INTEGER,
        atualizado_em TEXT)""")
    for caminho, artista, titulo, genero in (musicas or [
        ("acervo/Gospel/Fernandinho - Todas as Coisas.mp3",
         "Fernandinho", "Todas as Coisas", "Gospel"),
        ("acervo/Gospel/Isadora Pompeo - Dependente de Deus.mp3",
         "Isadora Pompeo", "Dependente de Deus", "Gospel"),
        ("acervo/MPB/Jota Quest - Do Seu Lado.mp3",
         "Jota Quest", "Do Seu Lado", "MPB"),
    ]):
        conn.execute(
            "INSERT INTO musicas (caminho, artista, titulo, genero)"
            " VALUES (?, ?, ?, ?)", (caminho, artista, titulo, genero))
    conn.commit()
    conn.close()
    return banco


@pytest.fixture()
def bancos(tmp_path: Path) -> dict[str, Path]:
    return {
        "acervo": _acervo(tmp_path / "acervo.db"),
        "pedidos": tmp_path / "pedidos.db",
        "cache": tmp_path / "letras.json",
    }


# ---------------------------------------------------------------------------
#  Letra da música
# ---------------------------------------------------------------------------

class TestLetra:
    def test_sem_musica_nao_busca_nada(self, bancos) -> None:
        def busca(*_a):
            raise AssertionError("não deveria buscar")
        assert rp.letra_da_musica("", "", cache_arq=bancos["cache"],
                                  buscar=busca) == {"ok": False,
                                                    "motivo": "sem_musica"}

    def test_locucao_no_ar_nao_tem_letra(self, bancos) -> None:
        r = rp.letra_da_musica("", "Locução da rádio", cache_arq=bancos["cache"],
                               buscar=lambda a, t: "x")
        assert r["ok"] is False and r["motivo"] == "sem_musica"

    def test_letra_encontrada_e_guardada_no_cache(self, bancos) -> None:
        chamadas: list[tuple[str, str]] = []

        def busca(artista: str, titulo: str) -> str:
            chamadas.append((artista, titulo))
            return "LINHA 1\nLINHA 2"

        r1 = rp.letra_da_musica("Fernandinho", "Todas as Coisas",
                                cache_arq=bancos["cache"], buscar=busca)
        assert r1["ok"] is True and r1["cache"] is False
        assert "LINHA 2" in r1["letra"]
        assert chamadas == [("Fernandinho", "Todas as Coisas")]
        # segunda chamada sai do cache: o serviço não é martelado
        r2 = rp.letra_da_musica("Fernandinho", "Todas as Coisas",
                                cache_arq=bancos["cache"],
                                buscar=lambda a, t: chamadas.append((a, t)) or "outra")
        assert r2["ok"] is True and r2["cache"] is True
        assert len(chamadas) == 1
        guardado = json.loads(Path(bancos["cache"]).read_text(encoding="utf-8"))
        assert guardado, "cache não foi gravado em arquivo"

    def test_dupla_cai_para_o_primeiro_cantor(self, bancos) -> None:
        tentativas: list[str] = []

        def busca(artista: str, _titulo: str):
            tentativas.append(artista)
            return "letra" if artista == "Giselli Cristina" else None

        r = rp.letra_da_musica("Giselli Cristina e Moisés Cleyton", "Meu Barquinho",
                               cache_arq=bancos["cache"], buscar=busca)
        assert r["ok"] is True
        assert tentativas == ["Giselli Cristina e Moisés Cleyton", "Giselli Cristina"]

    def test_nao_encontrada_fica_em_cache_negativo(self, bancos) -> None:
        chamadas = []

        def busca(*_a):
            chamadas.append(1)
            return None

        r1 = rp.letra_da_musica("X", "Y", cache_arq=bancos["cache"], buscar=busca)
        r2 = rp.letra_da_musica("X", "Y", cache_arq=bancos["cache"], buscar=busca)
        assert r1 == {"ok": False, "motivo": "nao_encontrada"}
        assert r2 == {"ok": False, "motivo": "nao_encontrada"}
        assert len(chamadas) == 1, "negativa também precisa de cache"

    def test_fonte_fora_do_ar_devolve_indisponivel(self, bancos) -> None:
        def busca(*_a):
            raise OSError("sem rede")

        r = rp.letra_da_musica("X", "Y", cache_arq=bancos["cache"], buscar=busca)
        assert r == {"ok": False, "motivo": "indisponivel"}

    def test_cache_corrompido_nao_derruba(self, bancos) -> None:
        Path(bancos["cache"]).write_text("{nao e json", encoding="utf-8")
        r = rp.letra_da_musica("X", "Y", cache_arq=bancos["cache"],
                               buscar=lambda a, t: "letra")
        assert r["ok"] is True


# ---------------------------------------------------------------------------
#  Catálogo do acervo
# ---------------------------------------------------------------------------

class TestCatalogo:
    def test_lista_ordenada_do_acervo(self, bancos) -> None:
        itens = rp.catalogo_musicas(banco=bancos["acervo"])
        # ordem por artista (Fernandinho, Isadora Pompeo, Jota Quest)
        assert [i["titulo"] for i in itens] == [
            "Todas as Coisas", "Dependente de Deus", "Do Seu Lado"]
        assert itens[2]["caminho"].endswith("Jota Quest - Do Seu Lado.mp3")

    def test_busca_filtra_por_artista_ou_titulo(self, bancos) -> None:
        assert [i["artista"] for i in
                rp.catalogo_musicas("isadora", banco=bancos["acervo"])] == \
            ["Isadora Pompeo"]
        assert [i["titulo"] for i in
                rp.catalogo_musicas("lado", banco=bancos["acervo"])] == \
            ["Do Seu Lado"]

    def test_limite_vale(self, bancos) -> None:
        assert len(rp.catalogo_musicas(limite=2, banco=bancos["acervo"])) == 2
        # fora da faixa não estoura (limite é sempre 1..200)
        assert len(rp.catalogo_musicas(limite=10_000,
                                      banco=bancos["acervo"])) == 3

    def test_banco_ausente_devolve_lista_vazia(self, tmp_path: Path) -> None:
        assert rp.catalogo_musicas(banco=tmp_path / "nao_existe.db") == []

    def test_musica_do_acervo_por_caminho(self, bancos) -> None:
        caminho = "acervo/Gospel/Fernandinho - Todas as Coisas.mp3"
        assert rp.musica_do_acervo(caminho, banco=bancos["acervo"])["artista"] == \
            "Fernandinho"
        assert rp.musica_do_acervo("acervo/nao/existe.mp3",
                                   banco=bancos["acervo"]) is None
        assert rp.musica_do_acervo("", banco=bancos["acervo"]) is None


# ---------------------------------------------------------------------------
#  Fila de pedidos
# ---------------------------------------------------------------------------

CAMINHO = "acervo/Gospel/Fernandinho - Todas as Coisas.mp3"


class TestPedidos:
    def _criar(self, bancos, usuario="ana", caminho=CAMINHO, recado="",
               agora=None):
        return rp.criar_pedido(usuario, caminho, recado,
                               banco=bancos["pedidos"],
                               banco_acervo=bancos["acervo"], agora=agora)

    def test_pedido_valido_entra_pendente(self, bancos) -> None:
        p = self._criar(bancos, recado="  toca   essa   pra   mim  ")
        assert p["status"] == "pendente" and p["id"] > 0
        assert p["recado"] == "toca essa pra mim"
        assert p["titulo"] == "Todas as Coisas"
        assert p["artista"] == "Fernandinho"
        assert rp.meus_pedidos("ana", banco=bancos["pedidos"])[0]["id"] == p["id"]

    def test_sem_login_nao_pede(self, bancos) -> None:
        with pytest.raises(ValueError, match="login_obrigatorio"):
            self._criar(bancos, usuario="   ")

    def test_musica_fora_do_acervo_e_recusada(self, bancos) -> None:
        with pytest.raises(ValueError, match="musica_desconhecida"):
            self._criar(bancos, caminho="../../etc/passwd")
        with pytest.raises(ValueError, match="musica_desconhecida"):
            self._criar(bancos, caminho="acervo/Gospel/nao_existe.mp3")

    def test_recado_longo_e_recusado(self, bancos) -> None:
        with pytest.raises(ValueError, match="recado_longo"):
            self._criar(bancos, recado="a" * (rp.RECADO_MAX + 1))

    def test_cooldown_de_meia_hora_por_conta(self, bancos) -> None:
        """Um pedido por conta a cada 30 min — o relógio é o limite."""
        self._criar(bancos)
        with pytest.raises(ValueError, match="limite_tempo"):
            self._criar(bancos)
        # outra conta não é afetada
        self._criar(bancos, usuario="bia")
        # passada a meia hora da MESMA conta, pode pedir de novo
        depois = datetime.now() + timedelta(minutes=rp.COOLDOWN_MINUTOS + 1)
        assert self._criar(bancos, agora=depois)["status"] == "pendente"

    def test_pedidos_antigos_nao_bloqueiam(self, bancos) -> None:
        """Os status antigos saíram de cena: só o tempo desde o último conta."""
        rp._conexao(bancos["pedidos"]).close()
        conn = sqlite3.connect(str(bancos["pedidos"]))
        ontem = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
        for _ in range(3):                      # eram as3/dia do limite_diario
            conn.execute(
                "INSERT INTO pedidos (criado_em, usuario, artista, titulo,"
                " caminho, recado, status) VALUES (?, ?, '', '', ?, '', 'tocada')",
                (ontem, "ana", CAMINHO))
        conn.commit()
        conn.close()
        assert self._criar(bancos)["status"] == "pendente"

    def test_meus_pedidos_nao_vaza_de_outra_conta(self, bancos) -> None:
        self._criar(bancos, usuario="ana")
        self._criar(bancos, usuario="bia")
        assert len(rp.meus_pedidos("ana", banco=bancos["pedidos"])) == 1
        assert len(rp.meus_pedidos("bia", banco=bancos["pedidos"])) == 1
        assert rp.meus_pedidos("", banco=bancos["pedidos"]) == []

    def test_meus_pedidos_sem_banco_devolve_vazio(self, tmp_path: Path) -> None:
        assert rp.meus_pedidos("ana", banco=tmp_path / "nada.db") == []


# ---------------------------------------------------------------------------
#  Rotas e página (gate de sessão no servidor)
# ---------------------------------------------------------------------------

class TestRotas:
    def test_rotas_registradas(self) -> None:
        from integrations.api import server

        rotas = {r.path: r for r in server.ROUTES
                 if r.path in {"/radio-pro", "/api/radio/pro/dados",
                               "/api/radio/pro/pedido"}}
        assert set(rotas) == {"/radio-pro", "/api/radio/pro/dados",
                              "/api/radio/pro/pedido"}
        # o gate é do handler: nenhuma delas exige chave no dispatch
        assert all(r.auth is False for r in rotas.values())

    def test_rotas_isentas_da_chave_global(self) -> None:
        from integrations.api import server

        for caminho in ("/radio-pro", "/api/radio/pro/dados",
                        "/api/radio/pro/pedido"):
            assert caminho in server.AUTH_EXEMPT_PATHS, caminho

    def test_pagina_existe_e_nao_e_a_publica(self) -> None:
        from integrations.api import server

        pagina = Path(server.__file__).resolve().parents[2] / "site" / "radio-pro.html"
        assert pagina.exists(), "site/radio-pro.html não encontrado"
        html = pagina.read_text(encoding="utf-8")
        assert "/api/radio/pro/dados" in html
        assert "/api/radio/pro/pedido" in html
        assert "radio.html" in html, "a página pública continua acessível"
        # a área do ouvinte não publica áudio próprio: o stream é o mesmo
        assert "radio.mp3" not in html

    def test_handler_da_pagina_redireciona_anonimo(self) -> None:
        fonte = Path(rp.__file__).resolve().parents[1] / "integrations" / "api" / "server.py"
        texto = fonte.read_text(encoding="utf-8")
        trecho = texto.split("def radio_pro_page", 1)[1].split("def ", 1)[0]
        assert "/chat?next=/radio-pro" in trecho
        assert "send_response(302)" in trecho


# ---------------------------------------------------------------------------
#  2ª fonte de letra (lrclib → lyrics.ovh) — ordem do dono 04/11
# ---------------------------------------------------------------------------

class _RespostaFake:
    """urlopen de mentira: context manager que devolve um JSON."""

    def __init__(self, dados):
        self._dados = dados

    def read(self) -> bytes:
        return json.dumps(self._dados).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


class TestLetraDuasFontes:
    def test_lrclib_primeiro_e_lyrics_ovh_na_reserva(
            self, bancos, monkeypatch) -> None:
        chamadas: list[tuple[str, str, str]] = []

        def lrclib(a: str, t: str, timeout: float = 8.0):
            chamadas.append(("lrclib", a, t))
            return None                       # gospel não achou lá

        def ovh(a: str, t: str, timeout: float = 6.0):
            chamadas.append(("ovh", a, t))
            return "Letra que o lyrics.ovh trouxe."

        monkeypatch.setattr(rp, "_busca_lrclib", lrclib)
        monkeypatch.setattr(rp, "_busca_lyrics_ovh", ovh)
        r = rp.letra_da_musica("Fernandinho", "Todas as Coisas",
                               cache_arq=bancos["cache"])
        assert r == {"ok": True, "letra": "Letra que o lyrics.ovh trouxe.",
                     "fonte": "lyrics.ovh", "cache": False}
        assert [c[0] for c in chamadas] == ["lrclib", "ovh"]

    def test_lrclib_vence_quando_tem_letra(self, bancos, monkeypatch) -> None:
        monkeypatch.setattr(rp, "_busca_lrclib",
                            lambda a, t, timeout=8.0: "Letra do lrclib.")
        monkeypatch.setattr(
            rp, "_busca_lyrics_ovh",
            lambda *a, timeout=6.0: (_ for _ in ()).throw(
                AssertionError("não deveria ir para a reserva")))
        r = rp.letra_da_musica("Jota Quest", "Do Seu Lado",
                               cache_arq=bancos["cache"])
        assert r["ok"] and r["fonte"] == "lrclib"

    def test_cache_guarda_a_fonte_e_devolve_nela(
            self, bancos, monkeypatch) -> None:
        monkeypatch.setattr(rp, "_busca_lrclib",
                            lambda a, t, timeout=8.0: "Guardada.")
        rp.letra_da_musica("Jota Quest", "Do Seu Lado",
                           cache_arq=bancos["cache"])
        r = rp.letra_da_musica("Jota Quest", "Do Seu Lado",
                               cache_arq=bancos["cache"],
                               buscar=lambda *a: AssertionError("cache"))
        assert r == {"ok": True, "letra": "Guardada.",
                     "fonte": "lrclib", "cache": True}

    def test_nenhuma_fonte_responde_e_nao_encontrada(
            self, bancos, monkeypatch) -> None:
        monkeypatch.setattr(rp, "_busca_lrclib",
                            lambda a, t, timeout=8.0: None)
        monkeypatch.setattr(rp, "_busca_lyrics_ovh",
                            lambda a, t, timeout=6.0: None)
        r = rp.letra_da_musica("Desconhecido", "Xptz",
                               cache_arq=bancos["cache"])
        assert r == {"ok": False, "motivo": "nao_encontrada"}

    def test_lrclib_parseia_lista_com_letra(self, monkeypatch) -> None:
        monkeypatch.setattr(
            rp, "urlopen",
            lambda req, timeout=0: _RespostaFake(
                [{"plainLyrics": "Primeira\nlinha"}, {"plainLyrics": ""}]))
        assert rp._busca_lrclib("Tim Maia", "Azul") == "Primeira\nlinha"

    def test_lrclib_parseia_dict_e_lista_vazia(self, monkeypatch) -> None:
        monkeypatch.setattr(rp, "urlopen",
                            lambda req, timeout=0: _RespostaFake(
                                {"plainLyrics": "  Só isto.  "}))
        assert rp._busca_lrclib("A", "B") == "Só isto."
        monkeypatch.setattr(rp, "urlopen",
                            lambda req, timeout=0: _RespostaFake([]))
        assert rp._busca_lrclib("A", "B") is None

    def test_lrclib_fora_do_ar_devolve_none_e_nunca_levanta(
            self, monkeypatch) -> None:
        from urllib.error import URLError

        def _quebra(*a, **k):
            raise URLError("sem rede")

        monkeypatch.setattr(rp, "urlopen", _quebra)
        assert rp._busca_lrclib("A", "B") is None


# ---------------------------------------------------------------------------
#  Fila REAL do AzuraCast (ordem do dono 04/11: "com fila")
# ---------------------------------------------------------------------------

class TestFilaAzuraCast:
    def _criar(self, bancos, usuario="ana", recado="toca ai"):
        return rp.criar_pedido(usuario, CAMINHO, recado,
                               banco=bancos["pedidos"],
                               banco_acervo=bancos["acervo"])

    def _status(self, bancos, pedido_id: int) -> str:
        conn = sqlite3.connect(str(bancos["pedidos"]))
        try:
            return conn.execute("SELECT status FROM pedidos WHERE id = ?",
                                (pedido_id,)).fetchone()[0]
        finally:
            conn.close()

    def test_sem_chave_nao_inventa_fila(self) -> None:
        r = rp.pedir_no_ar("Fernandinho", "Todas as Coisas", chave="")
        assert r == {"ok": False, "motivo": "sem_chave"}

    def test_encontra_na_lista_e_enfileira_jingle_e_musica(
            self, monkeypatch) -> None:
        uid = "abc123abc123abc123abc123"
        caminhos: list[tuple[str, str]] = []

        def fake(caminho, *, metodo="GET", api=None, chave=None,
                 timeout=8.0):
            caminhos.append((metodo, caminho))
            return 200, [{
                "request_url": f"/api/station/1/request/{uid}",
                "song": {"artist": "Fernandinho",
                         "title": "Todas as Coisas"}}]

        chamado: dict[str, str] = {}

        def inserir(uj: str, up: str, tsj: str, tsp: str) -> bool:
            chamado.update(jingle=uj, musica=up,
                           ts_jingle=tsj, ts_musica=tsp)
            return True

        monkeypatch.setattr(rp, "_azuracast", fake)
        r = rp.pedir_no_ar("Fernandinho", "Todas as Coisas", chave="k",
                           jingle_recente=lambda: False, inserir=inserir)
        assert r == {"ok": True, "fila": "azuracast"}
        assert caminhos == [("GET", "/api/station/nicky/requests")]
        assert chamado["jingle"] == rp.JINGLE_ANUNCIO
        assert chamado["musica"] == uid
        # os DOIS nascem com31 min já consumidos → ordem J→P fixa na fila
        assert chamado["ts_jingle"] == chamado["ts_musica"]
        nascimento = datetime.strptime(chamado["ts_jingle"],
                                       "%Y-%m-%d %H:%M:%S")
        desde = datetime.now() - nascimento
        assert timedelta(minutes=rp.ATRASO_SEGURO_MIN - 1) <= desde <= \
            timedelta(minutes=rp.ATRASO_SEGURO_MIN + 1)

    def test_jingle_recente_deixa_a_musica_com_atraso_normal(
            self, monkeypatch) -> None:
        """Jingle travado nos10 min → música com timestamp NORMAL.

        A música só fica jogável (15 min) depois de o jingle destravar
        (10 min): a ordem J→P sobrevive mesmo com o bloqueio.
        """
        uid = "abc123abc123abc123abc123"
        monkeypatch.setattr(
            rp, "_azuracast",
            lambda *a, **k: (200, [{"request_url":
                                    f"/api/station/1/request/{uid}",
                                    "song": {"artist": "A", "title": "B"}}]),
        )
        chamado: dict[str, str] = {}

        def inserir(uj: str, up: str, tsj: str, tsp: str) -> bool:
            chamado.update(ts_jingle=tsj, ts_musica=tsp)
            return True

        r = rp.pedir_no_ar("A", "B", chave="k",
                           jingle_recente=lambda: True, inserir=inserir)
        assert r == {"ok": True, "fila": "azuracast"}
        assert chamado["ts_musica"] > chamado["ts_jingle"]

    def test_fora_da_lista_e_nao_pedivel(self, monkeypatch) -> None:
        monkeypatch.setattr(rp, "_azuracast",
                            lambda *a, **k: (200, []))
        r = rp.pedir_no_ar("Alguém", "Que Não Existe", chave="k")
        assert r == {"ok": False, "motivo": "nao_pedivel"}

    def test_url_de_fora_da_api_e_ignorada(self, monkeypatch) -> None:
        monkeypatch.setattr(
            rp, "_azuracast",
            lambda *a, **k: (200, [{"request_url": "http://evil.tld/x",
                                    "song": {"artist": "A", "title": "B"}}]),
        )

        def nao_deve_chamar(*_a):
            raise AssertionError("não deve enfileirar URL de fora")

        r = rp.pedir_no_ar("A", "B", chave="k",
                           jingle_recente=lambda: False,
                           inserir=nao_deve_chamar)
        assert r == {"ok": False, "motivo": "nao_pedivel"}

    def test_id_que_nao_e_unique_id_nao_vai_ao_sql(self, monkeypatch) -> None:
        """Só unique_id de24 hex chega ao mariadb (nada de SQL de fora)."""
        monkeypatch.setattr(
            rp, "_azuracast",
            lambda *a, **k: (200, [{"request_url":
                                    "/api/station/1/request/nao-e-hex",
                                    "song": {"artist": "A", "title": "B"}}]),
        )

        def nao_deve_chamar(*_a):
            raise AssertionError("não deve chamar o inserir")

        r = rp.pedir_no_ar("A", "B", chave="k",
                           jingle_recente=lambda: False,
                           inserir=nao_deve_chamar)
        assert r == {"ok": False, "motivo": "nao_pedivel"}

    def test_insercao_recusada_ou_quebrada_vira_recusado(
            self, monkeypatch) -> None:
        monkeypatch.setattr(
            rp, "_azuracast",
            lambda *a, **k: (200, [{"request_url":
                                    "/api/station/1/request/"
                                    "abc123abc123abc123abc123",
                                    "song": {"artist": "A", "title": "B"}}]),
        )
        r = rp.pedir_no_ar("A", "B", chave="k",
                           jingle_recente=lambda: False,
                           inserir=lambda *_a: False)
        assert r == {"ok": False, "motivo": "recusado"}

        def quebra(*_a):
            raise RuntimeError("docker morreu")

        r = rp.pedir_no_ar("A", "B", chave="k",
                           jingle_recente=lambda: False, inserir=quebra)
        assert r == {"ok": False, "motivo": "recusado"}

    def test_inserir_monta_o_insert_com_os_dois_ids(self) -> None:
        """O INSERT sai com estação, os DOIS tracks e os DOIS timestamps."""
        uid_j, uid_p = "a" * 24, "b" * 24
        vistas: list[str] = []

        def rodar(sql: str) -> tuple[bool, str]:
            vistas.append(sql)
            if "station_media" in sql:
                return True, (f"mid\t{uid_j}\t7\n"
                              f"mid\t{uid_p}\t423\n"
                              "st\t\t1\n")
            return True, ""

        ok = rp._inserir_requests(uid_j, uid_p,
                                  "2026-11-04 17:00:00",
                                  "2026-11-04 17:00:00", rodar=rodar)
        assert ok is True
        insert = vistas[-1]
        assert "INSERT INTO station_requests" in insert
        assert "(1, 7, '2026-11-04 17:00:00', 0, 'od-core')" in insert
        assert "(1, 423, '2026-11-04 17:00:00', 0, 'od-core')" in insert

    def test_inserir_sem_estacao_nao_insere_nada(self) -> None:
        """Linha da estação faltando → nada de INSERT pela metade."""
        uid_j, uid_p = "a" * 24, "b" * 24
        vistas: list[str] = []

        def rodar(sql: str) -> tuple[bool, str]:
            vistas.append(sql)
            if "station_media" in sql:
                return True, f"mid\t{uid_j}\t7\nmid\t{uid_p}\t423\n"
            return True, ""

        ok = rp._inserir_requests(uid_j, uid_p,
                                  "2026-11-04 17:00:00",
                                  "2026-11-04 17:00:00", rodar=rodar)
        assert ok is False
        assert len(vistas) == 1          # só o SELECT: nenhum INSERT

    def test_inserir_uid_fora_do_padrao_nem_chama_o_sql(self) -> None:
        def rodar(*_a):
            raise AssertionError("não deve tocar o banco com uid sujo")

        assert rp._inserir_requests("'; DROP TABLE", "b" * 24,
                                    "2026-11-04 17:00:00",
                                    "2026-11-04 17:00:00",
                                    rodar=rodar) is False

    def test_marcar_status_muda_a_linha(self, bancos) -> None:
        p = self._criar(bancos)
        assert rp.marcar_status(p["id"], "na_fila",
                                banco=bancos["pedidos"]) is True
        assert self._status(bancos, p["id"]) == "na_fila"

    def test_marcar_status_sem_banco_e_false(self, tmp_path: Path) -> None:
        assert rp.marcar_status(1, "na_fila",
                                banco=tmp_path / "nada.db") is False

    def test_aviso_no_jingle_marca_no_ar_e_confirma(self, bancos) -> None:
        """Janela exata: próxima=jingle → recado entra e vira 'no_ar'."""
        p = self._criar(bancos, usuario="alex", recado="boa noite pra dona")
        rp.marcar_status(p["id"], "na_fila", banco=bancos["pedidos"])
        texto = rp.anuncio_de_pedido("", "anuncio musica",
                                     banco=bancos["pedidos"])
        assert texto == "Pedido de alex: boa noite pra dona"
        assert self._status(bancos, p["id"]) == "no_ar"
        # jingle seguinte sem janela nova mantém o recado vivo
        assert rp.anuncio_de_pedido("", "anuncio musica",
                                    banco=bancos["pedidos"]) == texto
        # o webhook confirma no INSTANTE em que o jingle toca
        assert rp.confirmar_recados_no_ar(banco=bancos["pedidos"]) == 1
        assert self._status(bancos, p["id"]) == "tocada"
        assert rp.anuncio_de_pedido("", "anuncio musica",
                                    banco=bancos["pedidos"]) == ""

    def test_aviso_sem_recado_fala_só_o_pedido(self, bancos) -> None:
        p = self._criar(bancos, usuario="bia", recado="")
        rp.marcar_status(p["id"], "na_fila", banco=bancos["pedidos"])
        texto = rp.anuncio_de_pedido("", "anuncio musica",
                                     banco=bancos["pedidos"])
        assert texto == "Pedido do ouvinte bia."
        assert self._status(bancos, p["id"]) == "no_ar"

    def test_musica_do_pedido_cai_sem_aviso_atrasado(self, bancos) -> None:
        """O bug do 04/11: música sem o jingle → drop com WARN, nunca
        fala o recado DEPOIS da música."""
        p = self._criar(bancos, recado="canta pra mim")
        rp.marcar_status(p["id"], "na_fila", banco=bancos["pedidos"])
        assert rp.anuncio_de_pedido("Fernandinho", "Todas as Coisas",
                                    banco=bancos["pedidos"]) == ""
        assert self._status(bancos, p["id"]) == "tocada"

    def test_jingle_sem_pedido_nao_fala_nada(self, bancos) -> None:
        assert rp.anuncio_de_pedido("", "anuncio musica",
                                    banco=bancos["pedidos"]) == ""

    def test_confirmar_sem_nada_retorna_zero(self, bancos) -> None:
        assert rp.confirmar_recados_no_ar(banco=bancos["pedidos"]) == 0

    def test_confirmar_sem_banco_retorna_zero(self, tmp_path: Path) -> None:
        assert rp.confirmar_recados_no_ar(
            banco=tmp_path / "nada.db") == 0

    def test_anuncio_de_outra_musica_nao_marca(self, bancos) -> None:
        p = self._criar(bancos)
        assert rp.anuncio_de_pedido("Jota Quest", "Do Seu Lado",
                                    banco=bancos["pedidos"]) == ""
        assert self._status(bancos, p["id"]) == "pendente"

    def test_lancar_na_fila_atualiza_status(self, bancos) -> None:
        p = self._criar(bancos)
        r = rp.lancar_pedido_na_fila(
            p, enviar=lambda a, t: {"ok": True, "fila": "azuracast"},
            banco=bancos["pedidos"])
        assert r["fila"] == "azuracast" and r["status"] == "na_fila"
        assert self._status(bancos, p["id"]) == "na_fila"

    def test_lancar_sem_chave_fica_pendente_com_motivo(self, bancos) -> None:
        p = self._criar(bancos)
        r = rp.lancar_pedido_na_fila(
            p, enviar=lambda a, t: {"ok": False, "motivo": "sem_chave"})
        assert r["fila"] is None and r["motivo"] == "sem_chave"
        assert r["status"] == "pendente"
        assert self._status(bancos, p["id"]) == "pendente"

    def test_lancar_nao_repete_ja_na_fila(self, bancos) -> None:
        p = self._criar(bancos)
        rp.marcar_status(p["id"], "na_fila", banco=bancos["pedidos"])
        p["status"] = "na_fila"

        def nao_deve_chamar(*a):
            raise AssertionError("já está na fila")

        r = rp.lancar_pedido_na_fila(p, enviar=nao_deve_chamar)
        assert r["status"] == "na_fila" and "fila" not in r

    def test_lancar_com_envio_quebrado_nao_derruba(self, bancos) -> None:
        p = self._criar(bancos)

        def quebra(*a):
            raise RuntimeError("rede caiu")

        r = rp.lancar_pedido_na_fila(p, enviar=quebra)
        assert r["fila"] is None and r["motivo"] == "recusado"
        assert self._status(bancos, p["id"]) == "pendente"

    def test_status_nao_substitui_o_relógio(self, bancos) -> None:
        """Nem 'na_fila' nem 'tocada' liberam antes dos 30 minutos."""
        p = self._criar(bancos)
        rp.marcar_status(p["id"], "tocada", banco=bancos["pedidos"])
        with pytest.raises(ValueError, match="limite_tempo"):
            self._criar(bancos)

    def test_pedido_do_handler_vai_para_a_fila(self) -> None:
        """O handler liga o pedido à fila REAL (ordem do dono 04/11)."""
        from integrations.api import server

        fonte = Path(server.__file__).read_text(encoding="utf-8")
        trecho = fonte.split("def api_radio_pro_pedido", 1)[1].split("def ", 1)[0]
        assert "lancar_pedido_na_fila" in trecho
        assert '"fila"' in trecho, "a resposta informa o desfecho da fila"
        assert "na fila da rádio" in trecho, "o aviso do dono diz se entrou"

    def test_lrclib_404_e_ausencia_nao_e_pane(self, monkeypatch) -> None:
        """404 = música fora do catálogo: devolve None sem gritar no log."""
        from urllib.error import HTTPError

        def _nao_acha(*a, **k):
            raise HTTPError("https://lrclib.net/x", 404, "Not Found",
                            {}, None)

        monkeypatch.setattr(rp, "urlopen", _nao_acha)
        assert rp._busca_lrclib("Ana Castela", "Neon") is None
