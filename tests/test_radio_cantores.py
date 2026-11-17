"""Cantores indesejados (ordem do dono, 05/11/2026).

Regra (05/11, refinada em 17/11): lista em arquivo simples; se um ouvinte
pedir música de artista da lista (ou MÚSICA bloqueada), ela TOCA uma vez e o
dono é avisado — ele tem 24 h para PERMITIR (a faixa fica e vira exceção).
Sem decisão, a faixa é apagada (arquivo + banco + playlists + sync).

Guardas aqui:
- comparação por pessoa (Annita casa "Annita e Fulano" e "Fulano ft. Annita");
- lista é arquivo de texto: adiciona/remove sem perder comentários;
- registro da decisão é idempotente e tem prazo (`decidir_ate`);
- tocar NÃO apaga mais: só a decisão do dono ou o vencimento das 24 h;
- `decidir(permitir=True)` mantém e grava exceção; `False` apaga na hora;
- caminho fora do acervo nunca é apagado;
- a fila marca a faixa quando lança o pedido (sem bloquear o ouvinte).
"""
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


def test_tocar_nao_apaga_espera_decisao(registro: Path, acervo: Path) -> None:
    """Ordem de 17/11: a faixa toca e FICA até o dono decidir (24 h)."""
    alvo = acervo / "acervo" / "Gospel"
    alvo.mkdir(parents=True)
    faixa = alvo / "Annita - X.mp3"
    faixa.write_bytes(b"mp3")
    item = rc.registrar_para_apagar("Annita", "X", "acervo/Gospel/Annita - X.mp3",
                                    registro=registro)
    assert item and item["motivo"] == "cantor" and item["decidir_ate"]
    sincronizou = []
    r = rc.limpar_tocados(registro=registro,
                          ressincronizar=lambda: sincronizou.append(1) or True)
    assert (r["apagadas"], r["restantes"]) == (0, 1)
    assert faixa.exists() and sincronizou == []

    # 23 h depois ainda não venceu
    quase = datetime.now(timezone.utc) + timedelta(hours=23)
    assert rc.limpar_tocados(registro=registro,
                             ressincronizar=lambda: True, agora=quase)["apagadas"] == 0

    # passadas as 24 h, a faixa sai sozinha
    depois = datetime.now(timezone.utc) + timedelta(hours=25)
    r = rc.limpar_tocados(registro=registro,
                          ressincronizar=lambda: sincronizou.append(1) or True,
                          agora=depois)
    assert (r["apagadas"], r["restantes"], r["sync"]) == (1, 0, True)
    assert not faixa.exists()
    assert sincronizou == [1]
    assert rc.pendentes(registro=registro) == []


def test_pendentes_mostram_prazo_e_tempo_restante(registro: Path) -> None:
    rc.registrar_para_apagar("Annita", "X", "x.mp3", registro=registro,
                             motivo="musica", usuario="fulano")
    p = rc.pendentes(registro=registro)
    assert len(p) == 1
    assert p[0]["motivo"] == "musica" and p[0]["usuario"] == "fulano"
    assert rc.HORAS_DECISAO * 3600 - 60 <= p[0]["segundos_restantes"] \
        <= rc.HORAS_DECISAO * 3600


def test_registro_legado_sem_prazo_usa_horas_limite(registro: Path) -> None:
    rc.registrar_para_apagar("Annita", "X", "x.mp3", registro=registro)
    dados = json.loads(registro.read_text(encoding="utf-8"))
    dados[0].pop("decidir_ate")
    dados[0]["criado_em"] = (
        datetime.now(timezone.utc)
        - timedelta(hours=rc.HORAS_LIMITE + 1)).isoformat(timespec="seconds")
    registro.write_text(json.dumps(dados), encoding="utf-8")
    r = rc.limpar_tocados(registro=registro,
                          ressincronizar=lambda: True, apagar=lambda _c: True)
    assert r["apagadas"] == 1


def test_caminho_fora_do_acervo_nunca_apaga(registro: Path, acervo: Path,
                                            tmp_path: Path) -> None:
    fora = tmp_path.parent / "fora_do_acervo.mp3"
    fora.write_bytes(b"mp3")
    rc.registrar_para_apagar("Annita", "X", str(fora), registro=registro)
    depois = datetime.now(timezone.utc) + timedelta(hours=rc.HORAS_DECISAO + 1)
    r = rc.limpar_tocados(registro=registro, ressincronizar=lambda: True,
                          agora=depois)
    assert r["apagadas"] == 1        # o registro sai
    assert fora.exists()             # mas o arquivo de fora fica
    fora.unlink(missing_ok=True)


def test_permitir_mantem_a_faixa_e_cria_excecao(registro: Path,
                                                lista: Path) -> None:
    rc.registrar_para_apagar("Annita", "X", "x.mp3", registro=registro)
    excecoes = lista.with_name("cantores_excecoes.txt")
    r = rc.decidir("annitá", "x", permitir=True, registro=registro,
                   caminho_excecoes=excecoes)
    assert r["ok"] is True and r["permitida"] is True
    assert rc.pendentes(registro=registro) == []
    assert rc.eh_excecao("Annita", "X", caminho=excecoes) is True
    # idempotência: decidir de novo não duplica nada
    assert rc.decidir("Annita", "X", permitir=True,
                      registro=registro)["motivo"] == "ja_decidida"


def test_negar_apaga_na_hora(registro: Path, acervo: Path) -> None:
    faixa = acervo / "x.mp3"
    faixa.write_bytes(b"mp3")
    rc.registrar_para_apagar("Annita", "X", "x.mp3", registro=registro)
    apagados: list[str] = []
    r = rc.decidir("Annita", "X", permitir=False, registro=registro,
                   apagar=lambda c: apagados.append(c) or True,
                   ressincronizar=lambda: True)
    assert r["ok"] is True and r["permitida"] is False and r["sync"] is True
    assert apagados == ["x.mp3"]
    assert rc.pendentes(registro=registro) == []


def test_decidir_faixa_que_nao_esta_pendente(registro: Path) -> None:
    r = rc.decidir("Annita", "X", permitir=True, registro=registro)
    assert r == {"ok": False, "motivo": "nao_encontrado"}


class _PushFalso:
    """Dublê do PushService: registra os envios, não fala com o FCM."""

    def __init__(self) -> None:
        self.envios: list[tuple[str, str, dict]] = []

    def notify(self, titulo: str, corpo: str, data=None) -> dict:
        self.envios.append((titulo, corpo, data or {}))
        return {"ok": True, "sent": 1, "failed": 0}


def test_push_avisa_quando_a_faixa_entra_na_janela(registro: Path) -> None:
    push = _PushFalso()
    rc.registrar_para_apagar("Annita", "X", "x.mp3", registro=registro,
                             motivo="musica", usuario="fulano", push=push)
    assert len(push.envios) == 1
    titulo, corpo, dados = push.envios[0]
    assert "24 h" in titulo and "música bloqueada" in titulo
    assert "Annita — X" in corpo and "apagada sozinha" in corpo
    assert dados == {"origem": "radio-decisao", "artista": "Annita",
                    "titulo": "X"}


def test_push_nao_repete_na_marcacao_idempotente(registro: Path) -> None:
    push = _PushFalso()
    rc.registrar_para_apagar("Annita", "X", "x.mp3", registro=registro,
                             push=push)
    rc.registrar_para_apagar("annitá", "x", "", registro=registro,
                             push=push)
    assert len(push.envios) == 1


def test_push_que_falha_nao_impede_o_registro(registro: Path) -> None:
    class _Quebrado:
        def notify(self, *_a, **_k):
            raise RuntimeError("FCM fora")

    item = rc.registrar_para_apagar("Annita", "X", "x.mp3",
                                    registro=registro, push=_Quebrado())
    assert item and item["status"] == "aguardando"
    assert len(rc.pendentes(registro=registro)) == 1


def test_push_construido_quando_nao_ha_servico_global(
        registro: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """O worker do link roda em subprocesso sem launcher: sem serviço
    configurado, `radio_cantores` monta um e deixa pronto para as próximas."""
    import core.push as cp

    push = _PushFalso()
    configurados: list[object] = []
    monkeypatch.setattr(cp, "current_push", lambda: None)
    monkeypatch.setattr(cp, "build_push_service",
                        lambda *_a, **_k: push)
    monkeypatch.setattr(cp, "configure_push", configurados.append)

    rc.registrar_para_apagar("Annita", "X", "x.mp3", registro=registro)
    assert len(push.envios) == 1
    assert configurados == [push]


def test_sem_servico_de_push_nao_quebra(registro: Path) -> None:
    # push=None + current_push() devolve None no teste (nada configurado).
    item = rc.registrar_para_apagar("Annita", "X", "x.mp3",
                                    registro=registro)
    assert item is not None


def test_aviso_de_decisao_para_cantor_e_musica() -> None:
    cantor = rc.aviso_de_decisao(
        {"artista": "Annita", "titulo": "X", "motivo": "cantor",
         "usuario": "fulano", "decidir_ate": "2026-11-18T00:00:00+00:00"})
    assert "cantor bloqueado" in cantor and "@fulano" in cantor
    assert f"{rc.HORAS_DECISAO} h" in cantor
    musica = rc.aviso_de_decisao(
        {"artista": "Raul", "titulo": "Y", "motivo": "musica"})
    assert "música bloqueada" in musica and "Raul — Y" in musica
    assert rc.aviso_de_decisao(None) == ""


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
