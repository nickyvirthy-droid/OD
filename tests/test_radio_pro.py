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
import time
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
    def _criar(self, bancos, usuario="ana", caminho=CAMINHO, recado=""):
        return rp.criar_pedido(usuario, caminho, recado,
                               banco=bancos["pedidos"],
                               banco_acervo=bancos["acervo"])

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

    def test_um_pendente_por_conta(self, bancos) -> None:
        self._criar(bancos)
        with pytest.raises(ValueError, match="ja_tem_pedido"):
            self._criar(bancos)
        # outra conta não é afetada
        self._criar(bancos, usuario="bia")

    def test_limite_diario(self, bancos) -> None:
        rp._conexao(bancos["pedidos"]).close()
        conn = sqlite3.connect(str(bancos["pedidos"]))
        hoje = time.strftime("%Y-%m-%d")
        for i in range(rp.PEDIDOS_POR_DIA):
            conn.execute(
                "INSERT INTO pedidos (criado_em, usuario, artista, titulo,"
                " caminho, recado, status) VALUES (?, ?, '', '', ?, '', 'tocada')",
                (f"{hoje}T0{i}:00:00", "ana", CAMINHO))
        conn.commit()
        conn.close()
        with pytest.raises(ValueError, match="limite_diario"):
            self._criar(bancos)

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
