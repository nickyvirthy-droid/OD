"""Cantores indesejados (ordem do dono, 05/11/2026).

Regra: lista em arquivo simples; se um ouvinte pedir música de artista da
lista, ela TOCA uma vez e é apagada (arquivo + banco + playlists + sync).

Guardas aqui:
- comparação por pessoa (Annita casa "Annita e Fulano" e "Fulano ft. Annita");\n- lista é arquivo de texto: adiciona/remove sem perder comentários;\n- registro "toca uma vez e apaga" é idempotente;\n- só apaga depois de TOCAR (histórico do AzuraCast) ou de vencer o prazo;\n- caminho fora do acervo nunca é apagado;\n- a fila marca a faixa quando lança o pedido (sem bloquear o ouvinte).\n"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from integrations import radio_cantores as rc
from integrations import radio_pro as rp


@pytest.fixture()
def lista(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    caminho = tmp_path / "cantores_indesejados.txt"
    caminho.write_text("# comentario\n\n", encoding="utf-8")
    monkeypatch.setattr(rc, "LISTA", caminho)
    return caminho


@pytest.fixture()
def registro(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    caminho = tmp_path / "radio_apagar_depois.json"
    monkeypatch.setattr(rc, "REGISTRO", caminho)
    return caminho


@pytest.fixture()
def acervo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(rc, "BASE_MUSICAS", tmp_path)
    return tmp_path


def test_comparacao_por_pessoa_ignora_caixa_e_acento(lista: Path) -> None:
    assert rc.adicionar("Annita", caminho=lista)
    assert rc.indesejado("Annita", caminho=lista)
    assert rc.indesejado("annitá", caminho=lista)
    assert rc.indesejado("Annita e Fulano", caminho=lista)
    assert rc.indesejado("Fulano ft. Annita", caminho=lista)
    assert not rc.indesejado("Anitta", caminho=lista)      # outra pessoa
    assert not rc.indesejado("Fernandinho", caminho=lista)


def test_lista_arquivo_adiciona_remove_e_preserva_comentario(lista: Path) -> None:
    assert rc.adicionar("Annita", caminho=lista)
    assert not rc.adicionar("annita", caminho=lista)      # idempotente
    assert rc.listar(caminho=lista) == ["Annita"]
    assert "# comentario" in lista.read_text(encoding="utf-8")
    assert rc.remover("Annita", caminho=lista)
    assert rc.listar(caminho=lista) == []
    assert not rc.remover("Annita", caminho=lista)
    assert rc.adicionar("", caminho=lista) is False


def test_registro_idempotente(registro: Path) -> None:
    a = rc.registrar_para_apagar("Annita", "X", "acervo/Gospel/X.mp3",
                                 registro=registro)
    b = rc.registrar_para_apagar("annitá", "x", "", registro=registro)
    assert a and a["status"] == "aguardando"
    assert b == a
    assert len(rc.pendentes(registro=registro)) == 1


def test_limpar_apaga_so_depois_de_tocar(registro: Path, acervo: Path) -> None:
    alvo = acervo / "acervo" / "Gospel"
    alvo.mkdir(parents=True)
    faixa = alvo / "Annita - X.mp3"
    faixa.write_bytes(b"mp3")
    rc.registrar_para_apagar("Annita", "X", "acervo/Gospel/Annita - X.mp3",
                             registro=registro)
    sincronizou = []
    r = rc.limpar_tocados(registro=registro, historico=lambda: [],
                          ressincronizar=lambda: sincronizou.append(1) or True)
    assert (r["apagadas"], r["restantes"]) == (0, 1)
    assert faixa.exists() and sincronizou == []

    r = rc.limpar_tocados(
        registro=registro,
        historico=lambda: [{"artista": "annitá", "titulo": "x"}],
        ressincronizar=lambda: sincronizou.append(1) or True,
    )
    assert (r["apagadas"], r["restantes"], r["sync"]) == (1, 0, True)
    assert not faixa.exists()
    assert sincronizou == [1]
    assert rc.pendentes(registro=registro) == []


def test_limpar_vence_prazo_sem_tocar(registro: Path, acervo: Path) -> None:
    faixa = acervo / "x.mp3"
    faixa.write_bytes(b"mp3")
    rc.registrar_para_apagar("Annita", "X", "x.mp3", registro=registro)
    antigo = datetime.now(timezone.utc) - timedelta(hours=rc.HORAS_LIMITE + 1)
    r = rc.limpar_tocados(registro=registro, historico=lambda: [],
                          ressincronizar=lambda: True, agora=antigo)
    assert r["apagadas"] == 0            # criado_em é agora, não venceu
    dados = json.loads(registro.read_text(encoding="utf-8"))
    dados[0]["criado_em"] = antigo.isoformat(timespec="seconds")
    registro.write_text(json.dumps(dados), encoding="utf-8")
    r = rc.limpar_tocados(registro=registro, historico=lambda: [],
                          ressincronizar=lambda: True)
    assert r["apagadas"] == 1
    assert not faixa.exists()


def test_caminho_fora_do_acervo_nunca_apaga(registro: Path, acervo: Path,
                                            tmp_path: Path) -> None:
    fora = tmp_path.parent / "fora_do_acervo.mp3"
    fora.write_bytes(b"mp3")
    rc.registrar_para_apagar("Annita", "X", str(fora), registro=registro)
    r = rc.limpar_tocados(
        registro=registro,
        historico=lambda: [{"artista": "Annita", "titulo": "X"}],
        ressincronizar=lambda: True,
    )
    assert r["apagadas"] == 1        # o registro sai
    assert fora.exists()             # mas o arquivo de fora fica
    fora.unlink(missing_ok=True)


def test_fila_marca_cantor_indesejado_sem_bloquear(
    lista: Path, registro: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    rc.adicionar("Annita", caminho=lista)
    pedido = {"id": 7, "status": "pendente", "artista": "Annita",
              "titulo": "X", "caminho": "acervo/Gospel/Annita - X.mp3"}
    marcados = []
    monkeypatch.setattr(rp, "marcar_status", lambda *a, **k: True)
    monkeypatch.setattr(rc, "registrar_para_apagar",
                        lambda *a, **k: marcados.append(a) or {"status": "aguardando"})
    resultado = rp.lancar_pedido_na_fila(
        pedido, enviar=lambda artista, titulo: {"ok": True}, banco=Path("/nao/existe.db"))
    assert resultado["fila"] == "azuracast"
    assert resultado["status"] == "na_fila"
    assert marcados and marcados[0][0] == "Annita"


def test_fila_nao_marca_cantor_fora_da_lista(
    lista: Path, registro: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pedido = {"id": 8, "status": "pendente", "artista": "Fernandinho",
              "titulo": "Y", "caminho": "acervo/Gospel/Fernandinho - Y.mp3"}
    marcados = []
    monkeypatch.setattr(rp, "marcar_status", lambda *a, **k: True)
    monkeypatch.setattr(rc, "registrar_para_apagar",
                        lambda *a, **k: marcados.append(a))
    rp.lancar_pedido_na_fila(
        pedido, enviar=lambda artista, titulo: {"ok": True}, banco=Path("/nao/existe.db"))
    assert marcados == []
