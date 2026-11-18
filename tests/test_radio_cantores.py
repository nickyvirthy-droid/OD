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


def test_lembrete_de_push_duas_horas_antes(registro: Path) -> None:
    """Faltando <= HORAS_LEMBRETE, o dono recebe um push — uma vez só."""
    push = _PushFalso()
    rc.registrar_para_apagar("Annita", "X", "x.mp3", registro=registro,
                             motivo="musica", push=_PushFalso())
    quase = datetime.now(timezone.utc) + timedelta(
        hours=rc.HORAS_DECISAO - rc.HORAS_LEMBRETE + 0.5)
    r = rc.limpar_tocados(registro=registro, push=push, agora=quase,
                          ressincronizar=lambda: True, apagar=lambda _c: True)
    assert r["lembretes"] == 1 and r["apagadas"] == 0
    titulo, corpo, dados = push.envios[0]
    assert f"Faltam {rc.HORAS_LEMBRETE} h" in titulo
    assert "Annita — X" in corpo
    assert dados["origem"] == "radio-lembrete"
    # segunda passada: já lembrado, não repete
    r = rc.limpar_tocados(registro=registro, push=push, agora=quase,
                          ressincronizar=lambda: True, apagar=lambda _c: True)
    assert r["lembretes"] == 0 and len(push.envios) == 1


def test_sem_lembrete_fora_da_janela(registro: Path) -> None:
    push = _PushFalso()
    rc.registrar_para_apagar("Annita", "X", "x.mp3", registro=registro,
                             push=_PushFalso())
    cedo = datetime.now(timezone.utc) + timedelta(hours=1)
    r = rc.limpar_tocados(registro=registro, push=push, agora=cedo,
                          ressincronizar=lambda: True, apagar=lambda _c: True)
    assert r["lembretes"] == 0 and push.envios == []


def test_lembrete_que_falha_nao_marca_e_nao_apaga(registro: Path) -> None:
    class _Quebrado:
        def notify(self, *_a, **_k):
            raise RuntimeError("FCM fora")

    rc.registrar_para_apagar("Annita", "X", "x.mp3", registro=registro,
                             push=_PushFalso())
    quase = datetime.now(timezone.utc) + timedelta(
        hours=rc.HORAS_DECISAO - rc.HORAS_LEMBRETE + 0.5)
    r = rc.limpar_tocados(registro=registro, push=_Quebrado(), agora=quase,
                          ressincronizar=lambda: True, apagar=lambda _c: True)
    assert r["lembretes"] == 0 and r["apagadas"] == 0
    assert "lembrete_em" not in rc.pendentes(registro=registro)[0]


def test_faixa_permitida_nao_recebe_lembrete(registro: Path) -> None:
    push = _PushFalso()
    rc.registrar_para_apagar("Annita", "X", "x.mp3", registro=registro,
                             push=_PushFalso())
    rc.decidir("Annita", "X", permitir=True, registro=registro)
    quase = datetime.now(timezone.utc) + timedelta(hours=23)
    r = rc.limpar_tocados(registro=registro, push=push, agora=quase,
                          ressincronizar=lambda: True, apagar=lambda _c: True)
    assert r["lembretes"] == 0 and push.envios == []


def _item_apagado(artista: str, titulo: str, quando: datetime,
                  motivo_fim: str = "prazo", motivo: str = "cantor") -> dict:
    return {"artista": artista, "titulo": titulo, "status": "apagada",
            "motivo_fim": motivo_fim, "motivo": motivo,
            "apagada_em": quando.isoformat(timespec="seconds")}


def test_resumo_diario_conta_so_o_que_a_janela_apagou(registro: Path) -> None:
    agora = datetime.now(timezone.utc)
    dados = [
        _item_apagado("Annita", "Velha", agora - timedelta(hours=2)),
        _item_apagado("Raul", "Negada", agora - timedelta(hours=1),
                      motivo_fim="negada"),
        _item_apagado("Annita", "Antiga", agora - timedelta(hours=30)),
        {"artista": "X", "titulo": "Pendente", "status": "aguardando"},
    ]
    registro.write_text(json.dumps(dados), encoding="utf-8")
    r = rc.resumo_diario(registro=registro, agora=agora)
    assert r["total"] == 1
    assert r["faixas"][0]["titulo"] == "Velha"
    assert "1 faixa apagada" in r["texto"]
    assert "Annita — Velha" in r["texto"]
    assert "Negada" not in r["texto"]


def test_resumo_diario_vazio_nao_monta_texto(registro: Path) -> None:
    registro.write_text("[]", encoding="utf-8")
    assert rc.resumo_diario(registro=registro) == {
        "total": 0, "faixas": [], "texto": ""}


def test_prazo_marcado_como_motivo_fim_prazo(registro: Path) -> None:
    rc.registrar_para_apagar("Annita", "X", "x.mp3", registro=registro,
                             push=_PushFalso())
    depois = datetime.now(timezone.utc) + timedelta(
        hours=rc.HORAS_DECISAO + 1)
    rc.limpar_tocados(registro=registro, agora=depois,
                      ressincronizar=lambda: True, apagar=lambda _c: True,
                      push=_PushFalso())
    dados = json.loads(registro.read_text(encoding="utf-8"))
    assert dados[0]["motivo_fim"] == "prazo"
    assert dados[0]["apagada_em"]
    # a janela do resumo já pega a faixa que acabou de sair
    assert rc.resumo_diario(registro=registro,
                            agora=depois)["total"] == 1


def test_resumo_so_sai_depois_da_hora_e_uma_vez_por_dia(
        registro: Path, tmp_path: Path) -> None:
    estado = tmp_path / "resumo_estado.json"
    # A hora do resumo é LOCAL — monta 12:00 de hoje no fuso da máquina.
    local = datetime.now().astimezone().replace(
        hour=12, minute=0, second=0, microsecond=0)
    agora = local.astimezone(timezone.utc)
    registro.write_text(
        json.dumps([_item_apagado("Annita", "X", agora)]), encoding="utf-8")
    enviados: list[str] = []

    cedo = local.replace(hour=0, minute=30).astimezone(timezone.utc)
    assert rc.enviar_resumo_se_devido(
        registro=registro, estado=estado, agora=cedo, hora=9,
        enviar=enviados.append) is False
    assert enviados == []

    assert rc.enviar_resumo_se_devido(
        registro=registro, estado=estado, agora=agora, hora=9,
        enviar=enviados.append) is True
    assert len(enviados) == 1 and "Annita — X" in enviados[0]
    # segunda passada no mesmo dia não reenvia
    assert rc.enviar_resumo_se_devido(
        registro=registro, estado=estado, agora=agora, hora=9,
        enviar=enviados.append) is False
    assert len(enviados) == 1
    # dia seguinte: volta a sair (a faixa ainda está dentro das 24 h)
    amanha = agora + timedelta(days=1)
    assert rc.enviar_resumo_se_devido(
        registro=registro, estado=estado, agora=amanha, hora=9,
        enviar=enviados.append) is True


def test_resumo_sem_apagadas_marca_o_dia_em_silencio(
        registro: Path, tmp_path: Path) -> None:
    estado = tmp_path / "estado.json"
    registro.write_text("[]", encoding="utf-8")
    agora = datetime.now(timezone.utc)
    enviados: list[str] = []
    assert rc.enviar_resumo_se_devido(
        registro=registro, estado=estado, agora=agora, hora=0,
        enviar=enviados.append) is False
    assert enviados == []
    # O dia do resumo é o LOCAL (hora de Brasília), não o UTC: entre 21h e
    # meia-noite local o UTC já virou o dia e a marca trocava (teste ficou
    # vermelho às 22h de 17/11 sem nada ter mudado no código).
    assert (rc._ler_estado_resumo(estado)["ultimo_dia"]
            == agora.astimezone().date().isoformat())


def test_resumo_que_falha_nao_marca_e_tenta_de_novo(
        registro: Path, tmp_path: Path) -> None:
    estado = tmp_path / "estado.json"
    agora = datetime.now(timezone.utc)
    registro.write_text(
        json.dumps([_item_apagado("Annita", "X", agora)]), encoding="utf-8")

    def quebra(_texto):
        raise RuntimeError("Telegram fora")

    assert rc.enviar_resumo_se_devido(
        registro=registro, estado=estado, agora=agora, hora=0,
        enviar=quebra) is False
    assert rc._ler_estado_resumo(estado) == {}

    enviados: list[str] = []
    assert rc.enviar_resumo_se_devido(
        registro=registro, estado=estado, agora=agora, hora=0,
        enviar=enviados.append) is True
    assert len(enviados) == 1


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


# ===========================================================================
# Aviso só na ABERTURA da janela (achado 18/11): faixa que volta ao acervo
# depois do prazo não pode reenviar "Decisão de 24 h" de um prazo vencido.
# ===========================================================================

def test_aviso_so_na_abertura_da_janela(registro: Path) -> None:
    avisos: list[dict] = []
    push = _PushFalso()
    cb = avisos.append

    # 1ª vez: janela nova → avisa (Telegram uma vez + push uma vez).
    rc.registrar_para_apagar("Annita", "X", "x.mp3", registro=registro,
                             push=push, ao_abrir_janela=cb)
    assert len(avisos) == 1 and len(push.envios) == 1

    # Idempotente: já está aguardando → não avisa de novo.
    rc.registrar_para_apagar("annitá", "x", "", registro=registro,
                             push=push, ao_abrir_janela=cb)
    assert len(avisos) == 1 and len(push.envios) == 1


def test_faixa_permitida_nao_volta_a_avisar(registro: Path) -> None:
    avisos: list[dict] = []
    push = _PushFalso()
    rc.registrar_para_apagar("Annita", "X", "x.mp3", registro=registro,
                             push=push, ao_abrir_janela=avisos.append)
    assert rc.decidir("Annita", "X", permitir=True, registro=registro)["ok"]

    rc.registrar_para_apagar("Annita", "X", "x.mp3", registro=registro,
                             push=push, ao_abrir_janela=avisos.append)
    assert len(avisos) == 1 and len(push.envios) == 1
    assert rc.pendentes(registro=registro) == []


def test_faixa_vencida_que_volta_reabre_uma_janela_so(registro: Path) -> None:
    """Prazo vencido + faixa baixada de novo: UMA janela nova, não spam."""
    avisos: list[dict] = []
    push = _PushFalso()
    rc.registrar_para_apagar("Annita", "X", "x.mp3", registro=registro,
                             push=push, ao_abrir_janela=avisos.append)
    antes = rc.pendentes(registro=registro)[0]["decidir_ate"]

    # Vence o prazo: a janela apaga (arquivo stub) e marca a faixa.
    r = rc.limpar_tocados(
        registro=registro, apagar=lambda _c: True,
        agora=datetime.now(timezone.utc) + timedelta(hours=rc.HORAS_DECISAO + 1),
    )
    assert r["apagadas"] == 1
    assert rc.pendentes(registro=registro) == []
    assert len(avisos) == 1

    # A faixa voltou ao acervo (baixada de novo): reabre a janela, uma vez.
    item = rc.registrar_para_apagar("Annita", "X", "x.mp3", registro=registro,
                                    push=push, ao_abrir_janela=avisos.append)
    assert item["status"] == "aguardando"
    assert item["decidir_ate"] > antes
    assert "motivo_fim" not in item and "apagada_em" not in item
    assert len(avisos) == 2 and len(push.envios) == 2

    # Enquanto a janela nova está aberta, repetir não avisa.
    rc.registrar_para_apagar("Annita", "X", "x.mp3", registro=registro,
                             push=push, ao_abrir_janela=avisos.append)
    assert len(avisos) == 2 and len(push.envios) == 2
