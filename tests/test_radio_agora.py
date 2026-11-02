"""
OMEGA DRAKON • PYTEST
Testes de integrations/radio_agora.py — "Tocando agora" da rádio Nicky
(Item 1 do dono, 01/11/2026): montagem do JSON público, leitura do
acervo.db (Item 4), histórico em tocadas.txt e a rota /api/radio/agora.

Nada de rede: o nowplaying do AzuraCast é substituído por fixtures e os
arquivos caem em tmp_path — o módulo inteiro roda em sandbox.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from integrations import radio_agora as ra


# ---------------------------------------------------------------------------
#  Fixtures / apoio
# ---------------------------------------------------------------------------

def _azura(titulo: str = "Todas as Coisas", artista: str = "Fernandinho",
           proximo: tuple[str, str] | None = ("Maria Marçal", "Cura"),
           historico: list[dict] | None = None) -> dict:
    """Nowplaying de mentira com a MESMA forma do AzuraCast real."""
    return {
        "now_playing": {"song": {"artist": artista, "title": titulo}},
        "playing_next": ({"song": {"artist": proximo[0], "title": proximo[1]}}
                         if proximo else None),
        "listeners": {"total": 7, "unique": 6, "current": 7},
        "live": {"is_live": True},
        "song_history": historico or [],
    }


def _banco_de_exemplo(curiosidade: str, artista: str = "Fernandinho",
                      titulo: str = "Todas as Coisas") -> None:
    conn = sqlite3.connect(str(ra.BANCO_ACERVO))
    conn.execute("""CREATE TABLE musicas (
        caminho TEXT PRIMARY KEY, artista TEXT, titulo TEXT, ano TEXT,
        genero TEXT, curiosidade TEXT, pronuncia_artista TEXT,
        pronuncia_titulo TEXT, duracao_s INTEGER, bytes INTEGER,
        atualizado_em TEXT)""")
    conn.execute("INSERT INTO musicas (caminho, artista, titulo, curiosidade)"
                 " VALUES (?, ?, ?, ?)",
                 ("acervo/Gospel/x.mp3", artista, titulo, curiosidade))
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def _sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Caminhos em tmp + cache zerado: cada teste começa do zero."""
    ra._cache["dados"] = None
    ra._cache["em"] = 0.0
    monkeypatch.setattr(ra, "TOCADAS_ARQ", tmp_path / "tocadas.txt")
    monkeypatch.setattr(ra, "BANCO_ACERVO", tmp_path / "acervo.db")
    yield


# ---------------------------------------------------------------------------
#  montar_agora — contrato da página
# ---------------------------------------------------------------------------

class TestMontarAgora:
    def test_contrato_completo_para_a_pagina(self, monkeypatch) -> None:
        monkeypatch.setattr(ra, "_nowplaying", lambda: _azura())
        d = ra.montar_agora()
        assert d["ok"] is True
        assert d["tocando"] == {"artista": "Fernandinho",
                                "titulo": "Todas as Coisas",
                                "curiosidade": ""}
        assert d["proxima"] == {"artista": "Maria Marçal", "titulo": "Cura"}
        assert d["ouvintes"] == 7
        assert d["ao_vivo"] is True
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}",
                            d["atualizado_em"])
        assert isinstance(d["ultimas"], list) and len(d["ultimas"]) <= 5

    def test_curiosidade_real_vem_do_banco(self, monkeypatch) -> None:
        _banco_de_exemplo("Fernandinho é referência do louvor brasileiro.")
        # caixa diferente de propósito: a consulta casa em minúsculas
        monkeypatch.setattr(ra, "_nowplaying",
                            lambda: _azura(artista="FERNANDINHO"))
        d = ra.montar_agora()
        assert d["tocando"]["curiosidade"] == \
            "Fernandinho é referência do louvor brasileiro."

    def test_curiosidade_do_placeholder_conta_como_vazia(self, monkeypatch) -> None:
        _banco_de_exemplo("Música nova na rádio Nicky — curiosidade pendente.")
        monkeypatch.setattr(ra, "_nowplaying", lambda: _azura())
        d = ra.montar_agora()
        assert d["tocando"]["curiosidade"] == ""

    def test_sem_banco_curiosidade_nao_derruba_o_json(self, monkeypatch) -> None:
        monkeypatch.setattr(ra, "_nowplaying", lambda: _azura())
        d = ra.montar_agora()               # acervo.db nem existe no tmp
        assert d["ok"] is True
        assert d["tocando"]["curiosidade"] == ""

    def test_locucao_no_ar_nao_vira_musica(self, monkeypatch) -> None:
        monkeypatch.setattr(ra, "_nowplaying",
                            lambda: _azura(titulo="anuncio musica", artista=""))
        d = ra.montar_agora()
        assert d["tocando"]["titulo"] == "Locução da rádio"
        assert d["tocando"]["curiosidade"] == ""

    def test_proxima_locucao_e_declarada_como_locucao(self, monkeypatch) -> None:
        monkeypatch.setattr(ra, "_nowplaying",
                            lambda: _azura(proximo=("", "anuncio musica")))
        d = ra.montar_agora()
        assert d["proxima"]["titulo"] == "Locução da rádio"

    def test_azura_fora_responde_com_o_que_existe(self, monkeypatch) -> None:
        def _caiu() -> dict:
            raise OSError("sem rede")
        monkeypatch.setattr(ra, "_nowplaying", _caiu)
        d = ra.montar_agora()
        assert d["ok"] is True
        assert d["tocando"] is None and d["proxima"] is None
        assert d["ouvintes"] == 0 and d["ao_vivo"] is False
        assert d["ultimas"] == []


# ---------------------------------------------------------------------------
#  Últimas 5 — tocadas.txt e o histórico de cobertura
# ---------------------------------------------------------------------------

class TestUltimasTocadas:
    def test_arquivo_alimenta_as_ultimas_mais_recente_primeiro(
            self, monkeypatch) -> None:
        ra.TOCADAS_ARQ.write_text(
            "14:33 | Damares - O Maior Troféu\n"
            "14:38 | Kell Smith - Era Uma Vez\n"
            "14:43 | Vento Impetuoso - Casa Worship\n"
            "14:47 | Victor & Leo - Boa Sorte Pra Você (Ao Vivo)\n"
            "14:53 | Fernandinho - Todas as Coisas\n"
            "14:58 | Isadora Pompeo - Hey, Pai\n", encoding="utf-8")
        monkeypatch.setattr(ra, "_nowplaying",
                            lambda: _azura(titulo="Hey, Pai",
                                           artista="Isadora Pompeo"))
        d = ra.montar_agora()
        # 6 linhas, uma é a que está no ar (a mais nova) → sobram 5,
        # em ordem de recência a partir da que veio antes dela
        assert len(d["ultimas"]) == 5
        assert d["ultimas"][0]["nome"] == "Fernandinho - Todas as Coisas"
        assert d["ultimas"][-1]["nome"] == "Damares - O Maior Troféu"
        assert all("Hey, Pai" not in u["nome"] for u in d["ultimas"])
        assert all(re.fullmatch(r"\d{2}:\d{2}", u["hora"]) for u in d["ultimas"])

    def test_sem_arquivo_o_historico_do_azura_cobre(self, monkeypatch) -> None:
        hist = [{"played_at": 1793642001, "song": {"artist": "Victor & Leo",
                                                   "title": "Boa Sorte"}},
                {"played_at": 1793641701, "song": {"artist": "Damares",
                                                   "title": "O Maior Troféu"}}]
        monkeypatch.setattr(ra, "_nowplaying", lambda: _azura(historico=hist))
        d = ra.montar_agora()
        assert [u["nome"] for u in d["ultimas"]] == \
            ["Victor & Leo - Boa Sorte", "Damares - O Maior Troféu"]
        assert all(re.fullmatch(r"\d{2}:\d{2}", u["hora"]) for u in d["ultimas"])

    def test_arquivo_so_com_a_do_ar_cai_no_historico(self, monkeypatch) -> None:
        """Arquivo nascente (só a música do ar) → a lista não fica vazia."""
        ra.TOCADAS_ARQ.write_text(
            "16:20 | Isadora Pompeo - Cicatrizes\n", encoding="utf-8")
        hist = [{"played_at": 1793642001,
                 "song": {"artist": "Tiago Iorc", "title": "Amei Te Ver"}}]
        monkeypatch.setattr(ra, "_nowplaying",
                            lambda: _azura(titulo="Cicatrizes",
                                           artista="Isadora Pompeo",
                                           historico=hist))
        d = ra.montar_agora()
        assert [u["nome"] for u in d["ultimas"]] == ["Tiago Iorc - Amei Te Ver"]
        assert d["ultimas"][0]["hora"] != ""

    def test_locucao_nao_entra_no_historico(self, monkeypatch) -> None:
        hist = [{"played_at": 1793642001,
                 "song": {"artist": "", "title": "anuncio musica"}}]
        monkeypatch.setattr(ra, "_nowplaying", lambda: _azura(historico=hist))
        assert ra.montar_agora()["ultimas"] == []


# ---------------------------------------------------------------------------
#  registrar_tocada — o hook do webhook
# ---------------------------------------------------------------------------

class TestRegistrarTocada:
    def _payload(self, artista: str = "Isadora Pompeo",
                 titulo: str = "Hey, Pai") -> dict:
        return {"now_playing": {"song": {"artist": artista, "title": titulo}}}

    def test_grava_linha_no_formato_hora_nome(self) -> None:
        ra.registrar_tocada(self._payload())
        linhas = ra.TOCADAS_ARQ.read_text(encoding="utf-8").splitlines()
        assert len(linhas) == 1
        hora, sep, nome = linhas[0].partition(" | ")
        assert sep and re.fullmatch(r"\d{2}:\d{2}", hora)
        assert nome == "Isadora Pompeo - Hey, Pai"

    def test_retry_do_webhook_nao_duplica(self) -> None:
        ra.registrar_tocada(self._payload())
        ra.registrar_tocada(self._payload())
        assert len(ra.TOCADAS_ARQ.read_text(encoding="utf-8").splitlines()) == 1

    def test_locucao_nao_entra_no_arquivo(self) -> None:
        ra.registrar_tocada(self._payload(titulo="anuncio musica", artista=""))
        assert not ra.TOCADAS_ARQ.exists()

    def test_nunca_lanca_mesmo_com_caminho_impossivel(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        bloqueado = tmp_path / "arquivo" / "tocadas.txt"
        bloqueado.parent.write_text("não é diretório", encoding="utf-8")
        monkeypatch.setattr(ra, "TOCADAS_ARQ", bloqueado)
        ra.registrar_tocada(self._payload())        # OSError contido
        ra.registrar_tocada(None)                    # payload vazio também

    def test_arquivo_gira_nos_500(self) -> None:
        for i in range(505):
            ra.registrar_tocada(self._payload(titulo=f"Música {i}"))
        linhas = ra.TOCADAS_ARQ.read_text(encoding="utf-8").splitlines()
        assert len(linhas) == ra.LIMITE_ARQUIVO
        assert linhas[-1].endswith("| Isadora Pompeo - Música 504")


# ---------------------------------------------------------------------------
#  Rota pública — GET /api/radio/agora
# ---------------------------------------------------------------------------

class TestRotaAgora:
    def test_rota_publica_registrada_e_isenta(self) -> None:
        from integrations.api import server
        rotas = [r for r in server.ROUTES
                 if r.path == "/api/radio/agora"]
        assert len(rotas) == 1, "rota /api/radio/agora não registrada"
        rota = rotas[0]
        assert rota.method == "GET" and rota.auth is False, \
            "a página do ouvinte sonda sem credencial"
        assert rota.path in server.AUTH_EXEMPT_PATHS, \
            "auth_all de produção bloquearia a página"
        assert hasattr(server.APIHandler, rota.handler)

    def test_rate_limit_isenta_a_sondagem_da_pagina(self) -> None:
        # a página sonda a cada 15 s; o limiter é p/ quem faz trabalho
        from integrations.api.server import APIHandler
        import inspect
        fonte = inspect.getsource(APIHandler._check_rate_limit)
        assert '"/api/radio/agora"' in fonte
