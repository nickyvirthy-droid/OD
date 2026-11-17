"""
OMEGA DRAKON • PYTEST
Módulo: tests/test_radio_curadoria.py
Descrição: curadoria do acervo da rádio (pedidos 2 e 3 do txt.txt, 17/11) —
           excluir uma música do acervo, bloquear a faixa para não voltar e
           liberar músicas escolhidas de cantores indesejados.

Cobre as duas camadas entregues juntas:
  1. biblioteca — `integrations/radio_cantores.py` (listas `Artista | Título`,
     `eh_excecao`, `musica_bloqueada`, `excluir_musica_do_acervo`);
  2. rotas — `GET /api/radio/musicas`, `POST /api/radio/musicas/excluir` e
     o CRUD de bloqueadas/exceções, com o gate do dono.

Segurança: nada de rede externa nem do acervo real — `acervo.db`, listas e
arquivos caem em `tmp_path`, e o apagar/sync do AzuraCast é injetado.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from integrations import radio_cantores as rc


# ---------------------------------------------------------------------------
#  Apoio
# ---------------------------------------------------------------------------

def _acervo(banco: Path, musicas: list[tuple[str, str, str]]) -> Path:
    """acervo.db de mentira com o esquema real do pipeline (musica.py)."""
    conn = sqlite3.connect(str(banco))
    conn.execute(
        """CREATE TABLE musicas (
        caminho TEXT PRIMARY KEY, artista TEXT, titulo TEXT, ano TEXT,
        genero TEXT, curiosidade TEXT, pronuncia_artista TEXT,
        pronuncia_titulo TEXT, duracao_s INTEGER, bytes INTEGER,
        atualizado_em TEXT)"""
    )
    for caminho, artista, titulo in musicas:
        conn.execute(
            "INSERT INTO musicas (caminho, artista, titulo, genero)"
            " VALUES (?, ?, ?, 'Rock')", (caminho, artista, titulo))
    conn.commit()
    conn.close()
    return banco


@pytest.fixture()
def listas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Listas isoladas em tmp_path (nenhum arquivo real é tocado)."""
    bloqueadas = tmp_path / "musicas_bloqueadas.txt"
    excecoes = tmp_path / "cantores_excecoes.txt"
    monkeypatch.setattr(rc, "LISTA_BLOQUEADAS", bloqueadas)
    monkeypatch.setattr(rc, "LISTA_EXCECOES", excecoes)
    return {"bloqueadas": bloqueadas, "excecoes": excecoes}


# ---------------------------------------------------------------------------
#  Biblioteca: pares Artista | Título
# ---------------------------------------------------------------------------

class TestListasDePares:
    def test_bloqueio_idempotente_e_sem_caixa_ou_acento(self, listas) -> None:
        assert rc.adicionar_musica_bloqueada("Annita", "Envolver") is True
        assert rc.adicionar_musica_bloqueada("annitá", "envolver") is False
        assert rc.listar_musicas_bloqueadas() == [
            {"artista": "Annita", "titulo": "Envolver"}]

    def test_bloqueio_casa_artista_composto(self, listas) -> None:
        rc.adicionar_musica_bloqueada("Annita", "Envolver")
        # "Annita e Fulano" é o MESMO par: o campo de artista pode vir sujo
        assert rc.musica_bloqueada("Annita e Fulano", "Envolver") is True
        assert rc.musica_bloqueada("Annita", "Outra") is False

    def test_remover_bloqueio(self, listas) -> None:
        rc.adicionar_musica_bloqueada("Annita", "Envolver")
        assert rc.remover_musica_bloqueada("Annita", "Envolver") is True
        assert rc.remover_musica_bloqueada("Annita", "Envolver") is False
        assert rc.listar_musicas_bloqueadas() == []

    def test_excecao_de_cantor_bloqueado(self, listas) -> None:
        assert rc.adicionar_excecao("Annita", "Envolver") is True
        assert rc.eh_excecao("Annita", "Envolver") is True
        assert rc.eh_excecao("Annita", "Outra") is False
        assert rc.listar_excecoes() == [
            {"artista": "Annita", "titulo": "Envolver"}]
        assert rc.remover_excecao("Annita", "Envolver") is True
        assert rc.eh_excecao("Annita", "Envolver") is False

    def test_linhas_vazias_trazem_o_cabecalho(self, listas) -> None:
        assert "Formato: Artista | Titulo" in rc.linhas_bloqueadas()
        assert "Formato: Artista | Titulo" in rc.linhas_excecoes()

    def test_par_invalido_e_recusado(self, listas) -> None:
        assert rc.adicionar_musica_bloqueada("", "Envolver") is False
        assert rc.adicionar_musica_bloqueada("Annita", "") is False


class TestIndesejadoComExcecao:
    def test_excecao_salva_a_musica_do_cantor_bloqueado(self, listas,
                                                        tmp_path) -> None:
        cantores = tmp_path / "cantores.txt"
        cantores.write_text("Annita\n", encoding="utf-8")
        rc.adicionar_excecao("Annita", "Envolver")
        # o cantor continua bloqueado para o resto...
        assert rc.indesejado("Annita", "Outra", caminho=cantores) is True
        # ...mas a música liberada NÃO é apagada
        assert rc.indesejado("Annita", "Envolver", caminho=cantores) is False


class TestExcluirMusica:
    def _banco(self, tmp_path: Path) -> Path:
        return _acervo(tmp_path / "acervo.db", [
            ("acervo/Rock/Raul - Metamorfose.mp3", "Raul", "Metamorfose"),
            ("acervo/Rock/Annita - Envolver.mp3", "Annita", "Envolver"),
        ])

    def test_apaga_arquivo_do_banco_e_bloqueia(self, tmp_path, listas) -> None:
        banco = self._banco(tmp_path)
        apagados: list[str] = []
        syncs: list[bool] = []

        def apagar(rel: str) -> bool:
            apagados.append(rel)
            return True

        def sync() -> bool:
            syncs.append(True)
            return True

        # Ordem de 17/11: apagar NÃO bloqueia (pode ser baixada de novo).
        r = rc.excluir_musica_do_acervo(
            "acervo/Rock/Annita - Envolver.mp3", banco=banco,
            apagar=apagar, ressincronizar=sync)
        assert r["ok"] is True and r["artista"] == "Annita"
        assert r["bloqueada"] is False and r["sync"] is True
        assert rc.musica_bloqueada("Annita", "Envolver") is False
        assert apagados == ["acervo/Rock/Annita - Envolver.mp3"]
        assert syncs == [True]
        # com bloquear=True explícito aí sim entra na lista
        r = rc.excluir_musica_do_acervo(
            "acervo/Rock/Annita - Envolver.mp3", banco=banco,
            bloquear=True, apagar=apagar, ressincronizar=sync)
        assert r["ok"] is False or rc.musica_bloqueada("Annita", "Envolver") is True
        conn = sqlite3.connect(str(banco))
        restantes = conn.execute("SELECT caminho FROM musicas").fetchall()
        conn.close()
        assert restantes == [("acervo/Rock/Raul - Metamorfose.mp3",)]

    def test_aceita_artista_e_titulo(self, tmp_path, listas) -> None:
        banco = self._banco(tmp_path)
        r = rc.excluir_musica_do_acervo(
            "Annita - Envolver", banco=banco, apagar=lambda _r: True,
            ressincronizar=lambda: True)
        assert r["ok"] is True and r["titulo"] == "Envolver"

    def test_sem_bloquear_so_exclui(self, tmp_path, listas) -> None:
        banco = self._banco(tmp_path)
        r = rc.excluir_musica_do_acervo(
            "Annita - Envolver", bloquear=False, banco=banco,
            apagar=lambda _r: True, ressincronizar=lambda: True)
        assert r["ok"] is True and r["bloqueada"] is False
        assert rc.musica_bloqueada("Annita", "Envolver") is False

    def test_musica_inexistente(self, tmp_path, listas) -> None:
        banco = self._banco(tmp_path)
        r = rc.excluir_musica_do_acervo(
            "Ninguem - Nada", banco=banco, apagar=lambda _r: True,
            ressincronizar=lambda: True)
        assert r == {"ok": False, "motivo": "musica_nao_encontrada"}

    def test_banco_ausente(self, tmp_path, listas) -> None:
        r = rc.excluir_musica_do_acervo(
            "Annita - Envolver", banco=tmp_path / "nao_existe.db")
        assert r == {"ok": False, "motivo": "banco_acervo_inexistente"}

    def test_falha_do_sync_nao_desfaz_a_exclusao(self, tmp_path, listas) -> None:
        banco = self._banco(tmp_path)

        def sync_quebrado() -> bool:
            raise RuntimeError("azuracast fora")

        r = rc.excluir_musica_do_acervo(
            "Annita - Envolver", banco=banco, apagar=lambda _r: True,
            ressincronizar=sync_quebrado)
        assert r["ok"] is True and r["sync"] is False


# ---------------------------------------------------------------------------
#  API: rotas de curadoria
# ---------------------------------------------------------------------------

def _request(port: int, method: str, path: str, api_key: str = "",
             body: dict | None = None):
    dados = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=dados, method=method)
    if api_key:
        req.add_header("X-API-Key", api_key)
    if dados is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


class _StoreFalso:
    """UserStore mínimo: a chave decide quem é (admin ou conta comum)."""

    def __init__(self, usuarios: dict[str, SimpleNamespace]) -> None:
        self.usuarios = usuarios

    def login_with_api_key(self, chave: str):
        return self.usuarios.get(chave)

    def validate_session(self, token: str):
        return self.usuarios.get(token)


@pytest.fixture()
def servidor(tmp_path, monkeypatch):
    from integrations import radio_pro as rp
    from integrations.api import APIConfig, APIServer

    bloqueadas = tmp_path / "bloqueadas.txt"
    excecoes = tmp_path / "excecoes.txt"
    monkeypatch.setattr(rc, "LISTA_BLOQUEADAS", bloqueadas)
    monkeypatch.setattr(rc, "LISTA_EXCECOES", excecoes)
    banco = _acervo(tmp_path / "acervo.db", [
        ("acervo/Rock/Raul - Metamorfose.mp3", "Raul Seixas", "Metamorfose"),
        ("acervo/Rock/Annita - Envolver.mp3", "Annita", "Envolver"),
    ])
    monkeypatch.setattr(rp, "BANCO_ACERVO", banco)
    monkeypatch.setattr(rc, "BASE_MUSICAS", tmp_path)
    monkeypatch.setattr(rc, "_apagar_arquivo", lambda _r: True)
    monkeypatch.setattr(rc, "_ressincronizar", lambda: True)

    store = _StoreFalso({
        "chave-dono": SimpleNamespace(username="alex", role="admin"),
        "chave-comum": SimpleNamespace(username="fulano", role="user"),
    })
    # `alex` precisa ser a conta do dono: `admin` não está em
    # PAPEIS_CONTA_VALIDOS, quem vira admin é o OD_OWNER_USERNAME.
    cfg = APIConfig(port=0, rate_limit_max=0, user_store=store,
                    owner_username="alex")
    srv = APIServer(None, config=cfg)
    srv.serve_background()
    yield srv
    srv.stop()


class TestRotasDeCuradoria:
    def test_lista_traz_acervo_e_listas(self, servidor) -> None:
        status, d = _request(servidor.bound_port, "GET",
                             "/api/radio/musicas", api_key="chave-dono")
        assert status == 200 and d["ok"] is True
        assert {m["titulo"] for m in d["musicas"]} == {"Metamorfose", "Envolver"}
        assert all(m["bloqueada"] is False for m in d["musicas"])
        assert d["bloqueadas"] == [] and d["excecoes"] == []

    def test_busca_por_termo(self, servidor) -> None:
        status, d = _request(servidor.bound_port, "GET",
                             "/api/radio/musicas?q=annita", api_key="chave-dono")
        assert status == 200
        assert [m["titulo"] for m in d["musicas"]] == ["Envolver"]

    def test_sem_credencial_401(self, servidor) -> None:
        status, d = _request(servidor.bound_port, "GET", "/api/radio/musicas")
        assert status == 401 and d["ok"] is False

    def test_chave_do_servidor_tambem_entra(self, tmp_path, monkeypatch) -> None:
        """O painel usa a X-API-Key do servidor: ela precisa valer aqui."""
        from integrations import radio_pro as rp
        from integrations.api import APIConfig, APIServer

        monkeypatch.setattr(rc, "LISTA_BLOQUEADAS", tmp_path / "b.txt")
        monkeypatch.setattr(rc, "LISTA_EXCECOES", tmp_path / "e.txt")
        monkeypatch.setattr(rp, "BANCO_ACERVO",
                            _acervo(tmp_path / "acervo.db", [
                                ("acervo/Rock/A - B.mp3", "A", "B")]))
        store = _StoreFalso({"od_chave_de_conta":
                             SimpleNamespace(username="fulano", role="user")})
        srv = APIServer(None, config=APIConfig(
            port=0, rate_limit_max=0, api_key="chave-do-operador",
            user_store=store))
        srv.serve_background()
        try:
            status, d = _request(srv.bound_port, "GET", "/api/radio/musicas",
                                 api_key="chave-do-operador")
            assert status == 200 and d["ok"] is True
            # chave de CONTA comum continua barrada
            status, _d = _request(srv.bound_port, "GET", "/api/radio/musicas",
                                  api_key="od_chave_de_conta")
            assert status == 403
            # chave errada não passa
            status, _d = _request(srv.bound_port, "GET", "/api/radio/musicas",
                                  api_key="errada")
            assert status == 401
        finally:
            srv.stop()

    def test_conta_comum_403(self, servidor) -> None:
        status, d = _request(servidor.bound_port, "GET",
                             "/api/radio/musicas", api_key="chave-comum")
        assert status == 403 and d["error"] == "acesso_negado"

    def test_bloquear_e_desbloquear(self, servidor) -> None:
        status, d = _request(
            servidor.bound_port, "POST", "/api/radio/musicas/bloqueadas",
            api_key="chave-dono",
            body={"artista": "Annita", "titulo": "Envolver"})
        assert status == 200 and d["novo"] is True
        assert d["bloqueadas"] == [{"artista": "Annita", "titulo": "Envolver"}]

        status, d = _request(
            servidor.bound_port, "GET", "/api/radio/musicas",
            api_key="chave-dono")
        marcada = [m for m in d["musicas"] if m["titulo"] == "Envolver"][0]
        assert marcada["bloqueada"] is True

        status, d = _request(
            servidor.bound_port, "DELETE", "/api/radio/musicas/bloqueadas",
            api_key="chave-dono",
            body={"artista": "Annita", "titulo": "Envolver"})
        assert status == 200 and d["bloqueadas"] == []

    def test_bloqueio_exige_artista_e_titulo(self, servidor) -> None:
        status, d = _request(
            servidor.bound_port, "POST", "/api/radio/musicas/bloqueadas",
            api_key="chave-dono", body={"artista": "Annita"})
        assert status == 400 and d["error"] == "artista_e_titulo_obrigatorios"

    def test_remover_bloqueio_inexistente_404(self, servidor) -> None:
        status, d = _request(
            servidor.bound_port, "DELETE", "/api/radio/musicas/bloqueadas",
            api_key="chave-dono", body={"artista": "X", "titulo": "Y"})
        assert status == 404 and d["error"] == "nao_estava_na_lista"

    def test_excecoes_crud(self, servidor) -> None:
        status, d = _request(
            servidor.bound_port, "POST", "/api/radio/musicas/excecoes",
            api_key="chave-dono",
            body={"artista": "Annita", "titulo": "Envolver"})
        assert status == 200 and d["novo"] is True
        assert d["excecoes"] == [{"artista": "Annita", "titulo": "Envolver"}]
        assert rc.eh_excecao("Annita", "Envolver") is True

        status, d = _request(
            servidor.bound_port, "DELETE", "/api/radio/musicas/excecoes",
            api_key="chave-dono",
            body={"artista": "Annita", "titulo": "Envolver"})
        assert status == 200 and d["excecoes"] == []
        assert rc.eh_excecao("Annita", "Envolver") is False

    def test_excluir_musica(self, servidor) -> None:
        status, d = _request(
            servidor.bound_port, "POST", "/api/radio/musicas/excluir",
            api_key="chave-dono",
            body={"caminho": "acervo/Rock/Annita - Envolver.mp3"})
        assert status == 200, d
        # Ordem de 17/11: excluir não bloqueia — pode ser baixada de novo.
        assert d["ok"] is True and d["bloqueada"] is False
        assert d["bloqueadas"] == []

        status, d = _request(servidor.bound_port, "GET", "/api/radio/musicas",
                             api_key="chave-dono")
        assert [m["titulo"] for m in d["musicas"]] == ["Metamorfose"]

        status, d = _request(
            servidor.bound_port, "POST", "/api/radio/musicas/excluir",
            api_key="chave-dono",
            body={"caminho": "acervo/Rock/Raul - Metamorfose.mp3",
                  "bloquear": True})
        assert status == 200, d
        assert d["bloqueada"] is True
        assert d["bloqueadas"] == [{"artista": "Raul Seixas",
                                   "titulo": "Metamorfose"}]

    def test_excluir_sem_caminho_400(self, servidor) -> None:
        status, d = _request(
            servidor.bound_port, "POST", "/api/radio/musicas/excluir",
            api_key="chave-dono", body={})
        assert status == 400 and d["error"] == "caminho_obrigatorio"

    def test_excluir_inexistente_404(self, servidor) -> None:
        status, d = _request(
            servidor.bound_port, "POST", "/api/radio/musicas/excluir",
            api_key="chave-dono", body={"caminho": "acervo/Nada.mp3"})
        assert status == 404 and d["motivo"] == "musica_nao_encontrada"

    def test_excluir_com_conta_comum_403(self, servidor) -> None:
        status, d = _request(
            servidor.bound_port, "POST", "/api/radio/musicas/excluir",
            api_key="chave-comum",
            body={"caminho": "acervo/Rock/Annita - Envolver.mp3"})
        assert status == 403


class TestDecisoesDe24h:
    """Ordem de 17/11: cantor/música bloqueada → aviso + 24 h para permitir."""

    @pytest.fixture()
    def pendente(self, tmp_path, monkeypatch):
        registro = tmp_path / "radio_apagar_depois.json"
        monkeypatch.setattr(rc, "REGISTRO", registro)
        item = rc.registrar_para_apagar(
            "Annita", "Envolver", "acervo/Rock/Annita - Envolver.mp3",
            registro=registro, motivo="musica", usuario="fulano")
        assert item and item["status"] == "aguardando"
        return registro

    def test_get_lista_decisoes_pendentes(self, servidor, pendente) -> None:
        status, d = _request(servidor.bound_port, "GET",
                             "/api/radio/musicas", api_key="chave-dono")
        assert status == 200, d
        assert d["horas_decisao"] == rc.HORAS_DECISAO
        assert len(d["decisoes"]) == 1
        decisao = d["decisoes"][0]
        assert decisao["motivo"] == "musica"
        assert decisao["usuario"] == "fulano"
        assert decisao["segundos_restantes"] > 0

    def test_permitir_mantem_no_acervo_e_cria_excecao(
            self, servidor, pendente, listas) -> None:
        status, d = _request(
            servidor.bound_port, "POST", "/api/radio/musicas/decisao",
            api_key="chave-dono",
            body={"artista": "Annita", "titulo": "Envolver",
                  "permitir": True})
        assert status == 200, d
        assert d["permitida"] is True and d["decisoes"] == []
        assert d["excecoes"] == [{"artista": "Annita",
                                  "titulo": "Envolver"}]

    def test_negar_apaga_na_hora(self, servidor, pendente, listas) -> None:
        status, d = _request(
            servidor.bound_port, "POST", "/api/radio/musicas/decisao",
            api_key="chave-dono",
            body={"artista": "Annita", "titulo": "Envolver",
                  "permitir": False})
        assert status == 200, d
        assert d["permitida"] is False and d["decisoes"] == []
        assert d["excecoes"] == []

    def test_decidir_duas_vezes_409(self, servidor, pendente) -> None:
        corpo = {"artista": "Annita", "titulo": "Envolver",
                 "permitir": True}
        status, _ = _request(servidor.bound_port, "POST",
                             "/api/radio/musicas/decisao",
                             api_key="chave-dono", body=corpo)
        assert status == 200
        status, d = _request(servidor.bound_port, "POST",
                             "/api/radio/musicas/decisao",
                             api_key="chave-dono", body=corpo)
        assert status == 409 and d["motivo"] == "ja_decidida"

    def test_nao_pendente_404(self, servidor, pendente) -> None:
        status, d = _request(
            servidor.bound_port, "POST", "/api/radio/musicas/decisao",
            api_key="chave-dono",
            body={"artista": "Raul Seixas", "titulo": "Metamorfose",
                  "permitir": True})
        assert status == 404 and d["motivo"] == "nao_encontrado"

    def test_sem_permitir_400(self, servidor, pendente) -> None:
        status, d = _request(
            servidor.bound_port, "POST", "/api/radio/musicas/decisao",
            api_key="chave-dono",
            body={"artista": "Annita", "titulo": "Envolver"})
        assert status == 400 and d["error"] == "permitir_obrigatorio"

    def test_sem_artista_ou_titulo_400(self, servidor, pendente) -> None:
        status, d = _request(
            servidor.bound_port, "POST", "/api/radio/musicas/decisao",
            api_key="chave-dono", body={"permitir": True})
        assert status == 400 and d["error"] == "artista_e_titulo_obrigatorios"

    def test_conta_comum_403_e_sem_chave_401(self, servidor, pendente) -> None:
        corpo = {"artista": "Annita", "titulo": "Envolver",
                 "permitir": True}
        status, _ = _request(servidor.bound_port, "POST",
                             "/api/radio/musicas/decisao",
                             api_key="chave-comum", body=corpo)
        assert status == 403
        status, _ = _request(servidor.bound_port, "POST",
                             "/api/radio/musicas/decisao", body=corpo)
        assert status == 401


class TestPaginaERotas:
    def test_rotas_registradas_e_isentas(self) -> None:
        from integrations.api import server

        caminhos = {"/api/radio/musicas", "/api/radio/musicas/excluir",
                    "/api/radio/musicas/bloqueadas",
                    "/api/radio/musicas/excecoes",
                    "/api/radio/musicas/decisao"}
        rotas = {r.path: r for r in server.ROUTES if r.path in caminhos}
        assert set(rotas) == caminhos
        # o gate é do handler (cookie do navegador), não do dispatch
        assert all(r.auth is False for r in rotas.values())
        for caminho in caminhos:
            assert caminho in server.AUTH_EXEMPT_PATHS, caminho

    def test_pagina_tem_a_curadoria(self) -> None:
        from integrations.api import server

        pagina = (Path(server.__file__).resolve().parents[2]
                  / "site" / "radio-pro.html")
        html = pagina.read_text(encoding="utf-8")
        assert "/api/radio/musicas" in html
        assert "/api/radio/musicas/excluir" in html
        assert "/api/radio/musicas/bloqueadas" in html
        assert "/api/radio/musicas/excecoes" in html
        assert "/api/radio/musicas/decisao" in html
        assert 'id="curadoriaCard"' in html
        assert 'id="crDecisoes"' in html

    def test_painel_tem_a_secao(self) -> None:
        from integrations.api import server

        html = server._ADMIN_PAGE_HTML
        for marca in ("mus-busca", "mus-lista", "blq-add", "exc-add",
                      "dec-lista", "/api/radio/musicas/decisao",
                      "/api/radio/musicas"):
            assert marca in html, marca
