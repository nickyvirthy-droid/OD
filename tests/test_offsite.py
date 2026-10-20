"""OMEGA DRAKON • TESTS
Módulo: tests/test_offsite.py
Descrição: Testes do off-site pelo canal PRIVADO do Telegram
           (core/offsite.py, ordem do dono 2026-10-20): fatiamento lazy
           (o tar de 316 MB nunca fica inteiro na RAM), multipart stdlib,
           envio idempotente por nome+sha256, estado atômico, falha com
           retry + push (cooldown 6 h), check não-crítico no /health,
           fiação do launcher (`build_offsite`) e bloco no stats.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - core/offsite.py
  - tests/test_backup.py (padrão da casa: push falso, env por dict)
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from core.offsite import (
    COOLDOWN_PUSH_S,
    TAMANHO_PADRAO_FATIA,
    OffsiteConfig,
    OffsiteService,
    _multipart,
    build_service,
    enviar_documento,
    fatiar,
    sha256_de,
)
from observability.health import HealthMonitor


# ---------------------------------------------------------------------------
# Dublês (padrão da casa)
# ---------------------------------------------------------------------------

class _Push:
    """PushService de mentira: só registra o que teria ido ao celular."""

    def __init__(self, levantar: bool = False) -> None:
        self.envios: list[tuple[str, str]] = []
        self.levantar = levantar

    def notify(self, titulo: str, corpo: str, data: dict | None = None) -> None:
        if self.levantar:
            raise RuntimeError("FCM fora")
        self.envios.append((titulo, corpo))


class _Resposta:
    """Resposta fake do urlopen (o corpo é o JSON do Bot API)."""

    def __init__(self, carga: dict) -> None:
        self._corpo = json.dumps(carga).encode("utf-8")

    def read(self) -> bytes:
        return self._corpo

    def __enter__(self) -> "_Resposta":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _Telegram:
    """Telegram de mentira: registra cada envio e devolve ok."""

    def __init__(self, carga: dict | None = None, falhar_em: int | None = None) -> None:
        self.envios: list[dict] = []
        self.carga = carga or {"ok": True}
        self.falhar_em = falhar_em  # índice da parte que recusa

    def urlopen(self, req: urllib.request.Request, timeout: float = 0.0):
        corpo = req.data
        if self.falhar_em is not None and len(self.envios) == self.falhar_em:
            return _Resposta({"ok": False, "description": "PAYLOAD_TOO_LARGE"})
        self.envios.append({"url": req.full_url, "corpo": corpo,
                            "headers": dict(req.header_items())})
        return _Resposta(self.carga)


def _env(dados: dict[str, str]):
    return lambda nome, padrao: dados.get(nome, padrao)


@pytest.fixture()
def perfis(tmp_path: Path) -> tuple[Path, Path]:
    """Dois diretórios de artefato com um tar em cada."""
    diario = tmp_path / "auto"
    capturas = tmp_path / "auto-capturas"
    diario.mkdir()
    capturas.mkdir()
    (diario / "od-2026-10-20_0309.tar.gz").write_bytes(b"tar diario 190k")
    (capturas / "od-capturas-2026-10-16_1434.tar.gz").write_bytes(b"tar capturas 316 MB")
    return diario, capturas


def _svc(perfis: tuple[Path, Path], tmp_path: Path, push=None,
         fatia_max: int = TAMANHO_PADRAO_FATIA,
         idade_ok_s: float = 48 * 3600.0) -> OffsiteService:
    diario, capturas = perfis
    cfg = OffsiteConfig(
        token="123:abc", chat_id="-1001234567890",
        dir_diario=diario, dir_capturas=capturas,
        estado_path=tmp_path / "offsite_state.json",
        fatia_max=fatia_max, idade_ok_s=idade_ok_s,
    )
    return OffsiteService(cfg=cfg, push=push)


# ---------------------------------------------------------------------------
# Fatiamento lazy (decisão registrada: 316 MB nunca na RAM)
# ---------------------------------------------------------------------------

class TestFatiar:
    def test_arquivo_pequeno_vira_uma_parte_com_o_nome_original(
            self, tmp_path: Path) -> None:
        tar = tmp_path / "od-2026-10-20_0309.tar.gz"
        tar.write_bytes(b"x" * 1000)
        partes = list(fatiar(tar, 4096))
        assert len(partes) == 1
        assert partes[0][0] == tar.name
        assert partes[0][1] == b"x" * 1000

    def test_arquivo_grande_e_fatiado_com_nome_numerado(self, tmp_path: Path) -> None:
        tar = tmp_path / "od-capturas-2026-10-16_1434.tar.gz"
        tar.write_bytes(b"abcdefghij")  # 10 bytes / fatia 4 = 3 partes
        partes = list(fatiar(tar, 4))
        assert [p[0] for p in partes] == [
            f"{tar.name}.parte01de03", f"{tar.name}.parte02de03",
            f"{tar.name}.parte03de03",
        ]
        assert [len(p[1]) for p in partes] == [4, 4, 2]
        assert b"".join(p[1] for p in partes) == b"abcdefghij"

    def test_e_um_gerador_o_arquivo_nao_carrega_inteiro(self, tmp_path: Path) -> None:
        """`fatiar` deve ser lazy: só a PRIMEIRA fatia é lida no primeiro next."""
        tar = tmp_path / "gordo.tar.gz"
        tar.write_bytes(b"A" * 100 + b"B" * 100)
        gen = fatiar(tar, 100)
        assert not isinstance(gen, list)  # gerador, não lista pronta
        primeiro = next(gen)
        assert len(primeiro[1]) == 100 and primeiro[1][:1] == b"A"
        segundo = next(gen)
        assert segundo[1][:1] == b"B"


# ---------------------------------------------------------------------------
# sha256 / multipart
# ---------------------------------------------------------------------------

class TestHashEMultipart:
    def test_sha256_de_bate_com_hashlib(self, tmp_path: Path) -> None:
        import hashlib

        arquivo = tmp_path / "a.tar.gz"
        arquivo.write_bytes(b"conteudo do tar")
        assert sha256_de(arquivo) == hashlib.sha256(b"conteudo do tar").hexdigest()

    def test_multipart_traz_chat_caption_e_document(self) -> None:
        corpo = _multipart({"chat_id": "-1001", "caption": "legenda"},
                           "a.tar.gz", b"gz", "bnd")
        assert corpo.startswith(b"--bnd\r\n")
        assert b'name="chat_id"\r\n\r\n-1001' in corpo
        assert b'name="caption"\r\n\r\nlegenda' in corpo
        assert b'filename="a.tar.gz"' in corpo
        assert b"Content-Type: application/gzip" in corpo
        assert corpo.endswith(b"\r\n--bnd--\r\n")
        assert corpo.split(b"\r\n--bnd--\r\n")[0].count(b"gz") >= 1


# ---------------------------------------------------------------------------
# Envio (urlopen fake — a rede real nunca é tocada)
# ---------------------------------------------------------------------------

class TestEnviarDocumento:
    def test_envio_unico_usa_o_nome_original_e_conta_1(self, monkeypatch,
                                                       tmp_path: Path) -> None:
        tar = tmp_path / "od-2026-10-20_0309.tar.gz"
        tar.write_bytes(b"tar")
        tg = _Telegram()
        monkeypatch.setattr(urllib.request, "urlopen", tg.urlopen)
        n = enviar_documento("TOK", "-1001", tar, "📦 legenda")
        assert n == 1
        assert len(tg.envios) == 1
        assert "/botTOK/sendDocument" in tg.envios[0]["url"]
        assert b'filename="od-2026-10-20_0309.tar.gz"' in tg.envios[0]["corpo"]
        # peça única: legenda limpa, sem sufixo de parte
        assert "parte" not in tg.envios[0]["corpo"].decode("utf-8", "ignore")

    def test_envio_fatiado_sobe_todas_as_partes(self, monkeypatch,
                                                tmp_path: Path) -> None:
        tar = tmp_path / "od-capturas-2026-10-16_1434.tar.gz"
        tar.write_bytes(b"z" * 10)
        tg = _Telegram()
        monkeypatch.setattr(urllib.request, "urlopen", tg.urlopen)
        n = enviar_documento("TOK", "-1001", tar, "legenda", fatia_max=4)
        assert n == 3 and len(tg.envios) == 3
        # cada parte leva o próprio nome na legenda (o dono sabe o que é)
        for envio, indice in zip(tg.envios, (1, 2, 3)):
            assert f"parte0{indice}de03".encode() in envio["corpo"]

    def test_recusa_do_bot_vira_oserror(self, monkeypatch, tmp_path: Path) -> None:
        tar = tmp_path / "od-2026-10-20_0309.tar.gz"
        tar.write_bytes(b"tar")
        tg = _Telegram(carga={"ok": False, "description": "chat not found"})
        monkeypatch.setattr(urllib.request, "urlopen", tg.urlopen)
        with pytest.raises(OSError, match="chat not found"):
            enviar_documento("TOK", "-1001", tar, "legenda")


# ---------------------------------------------------------------------------
# Tick (idempotente por nome+sha256, estado atômico, falha avisa)
# ---------------------------------------------------------------------------

class TestTick:
    def test_primeiro_tick_envia_os_dois_perfis_e_grava_estado(
            self, perfis, tmp_path, monkeypatch) -> None:
        svc = _svc(perfis, tmp_path)
        tg = _Telegram()
        monkeypatch.setattr(urllib.request, "urlopen", tg.urlopen)
        resumo = svc.tick()
        assert len(resumo["enviados"]) == 2 and resumo["erros"] == []
        assert len(tg.envios) == 2
        estado = json.loads((tmp_path / "offsite_state.json").read_text("utf-8"))
        assert set(estado) == {"diario", "capturas"}
        assert estado["diario"]["arquivo"] == "od-2026-10-20_0309.tar.gz"
        assert estado["capturas"]["partes"] == 1

    def test_segundo_tick_nao_reenvia_o_mesmo_tar(self, perfis, tmp_path,
                                                  monkeypatch) -> None:
        svc = _svc(perfis, tmp_path)
        tg = _Telegram()
        monkeypatch.setattr(urllib.request, "urlopen", tg.urlopen)
        svc.tick()
        resumo = svc.tick()  # idempotente: nada novo no disco
        assert resumo["enviados"] == [] and resumo["erros"] == []
        assert len(tg.envios) == 2  # não subiu de novo

    def test_tar_novo_do_dia_seguinte_e_enviado(self, perfis, tmp_path,
                                                monkeypatch) -> None:
        diario, _capturas = perfis
        svc = _svc(perfis, tmp_path)
        tg = _Telegram()
        monkeypatch.setattr(urllib.request, "urlopen", tg.urlopen)
        svc.tick()
        (diario / "od-2026-10-21_0305.tar.gz").write_bytes(b"tar novo")
        resumo = svc.tick()
        assert len(resumo["enviados"]) == 1
        assert "od-2026-10-21_0305" in resumo["enviados"][0]
        assert len(tg.envios) == 3

    def test_mesmo_nome_com_conteudo_diferente_reenvia(self, perfis, tmp_path,
                                                       monkeypatch) -> None:
        """Mesmo nome, sha diferente (corrupção/regrafo) = artefato novo."""
        diario, _capturas = perfis
        svc = _svc(perfis, tmp_path)
        tg = _Telegram()
        monkeypatch.setattr(urllib.request, "urlopen", tg.urlopen)
        svc.tick()
        (diario / "od-2026-10-20_0309.tar.gz").write_bytes(b"OUTRO CONTEUDO")
        resumo = svc.tick()
        assert len(resumo["enviados"]) == 1  # diário reenviado

    def test_falha_no_envio_vai_para_erros_e_nao_grava_como_enviado(
            self, perfis, tmp_path, monkeypatch) -> None:
        svc = _svc(perfis, tmp_path, push=_Push())
        tg = _Telegram(carga={"ok": False, "description": "chat not found"})
        monkeypatch.setattr(urllib.request, "urlopen", tg.urlopen)
        resumo = svc.tick()
        assert resumo["enviados"] == []
        assert len(resumo["erros"]) == 2 and "chat not found" in resumo["erros"][0]
        assert not (tmp_path / "offsite_state.json").exists()
        # a falha grita no celular — 1 push por 6 h (os dois perfis
        # falhando juntos no mesmo tick = 1 aviso só, sem spam)
        assert len(svc.push.envios) == 1
        assert "od-2026-10-20_0309" in svc.push.envios[0][1]

    def test_push_da_pau_mas_o_ciclo_nao_morre(self, perfis, tmp_path,
                                               monkeypatch) -> None:
        svc = _svc(perfis, tmp_path, push=_Push(levantar=True))
        tg = _Telegram(carga={"ok": False, "description": "boom"})
        monkeypatch.setattr(urllib.request, "urlopen", tg.urlopen)
        resumo = svc.tick()  # não levanta
        assert resumo["erros"] and svc.push.envios == []

    def test_cooldown_de_6h_no_aviso_de_falha(self, perfis, tmp_path,
                                              monkeypatch) -> None:
        svc = _svc(perfis, tmp_path, push=_Push())
        tg = _Telegram(carga={"ok": False, "description": "boom"})
        monkeypatch.setattr(urllib.request, "urlopen", tg.urlopen)
        svc.tick()
        enviados_antes = len(svc.push.envios)
        svc._ultimo_push_falha -= COOLDOWN_PUSH_S - 1  # ainda na janela
        svc.tick()
        assert len(svc.push.envios) == enviados_antes  # segue calado
        svc._ultimo_push_falha -= 2  # venceu o cooldown
        svc.tick()
        assert len(svc.push.envios) > enviados_antes  # grita de novo

    def test_sem_artefato_nada_faz_e_nada_grava(self, tmp_path) -> None:
        vazio = tmp_path / "vazio"
        (vazio / "auto").mkdir(parents=True)
        (vazio / "auto-capturas").mkdir()
        cfg = OffsiteConfig(
            token="T", chat_id="-1001",
            dir_diario=vazio / "auto", dir_capturas=vazio / "auto-capturas",
            estado_path=tmp_path / "estado.json",
        )
        svc = OffsiteService(cfg=cfg)
        assert svc.tick() == {"enviados": [], "erros": []}
        assert not (tmp_path / "estado.json").exists()

    def test_estado_corrompido_comeca_do_zero(self, perfis, tmp_path,
                                              monkeypatch) -> None:
        (tmp_path / "offsite_state.json").write_text("{{{", "utf-8")
        svc = _svc(perfis, tmp_path)
        tg = _Telegram()
        monkeypatch.setattr(urllib.request, "urlopen", tg.urlopen)
        resumo = svc.tick()
        assert len(resumo["enviados"]) == 2  # não travou no JSON ruim


# ---------------------------------------------------------------------------
# Saúde (check não-crítico) e snapshot
# ---------------------------------------------------------------------------

class TestSaude:
    def test_nunca_enviado_e_degraded(self, perfis, tmp_path) -> None:
        saude = _svc(perfis, tmp_path).check_saude()
        assert saude["ok"] is False and saude["status"] == "degraded"
        assert "nunca enviado" in saude["detail"]

    def test_envio_recente_e_up_com_idade(self, perfis, tmp_path,
                                          monkeypatch) -> None:
        import time as _time

        svc = _svc(perfis, tmp_path)
        tg = _Telegram()
        monkeypatch.setattr(urllib.request, "urlopen", tg.urlopen)
        svc.tick()
        agora = _time.time()  # congelado ANTES do patch (sem recursão)
        monkeypatch.setattr(_time, "time", lambda: agora + 3600)
        saude = svc.check_saude()
        assert saude["ok"] is True and saude["status"] == "up"
        assert "há 1.0 h" in saude["detail"]

    def test_envio_velho_degrada_com_motivo(self, perfis, tmp_path,
                                            monkeypatch) -> None:
        svc = _svc(perfis, tmp_path, idade_ok_s=48 * 3600.0)
        tg = _Telegram()
        monkeypatch.setattr(urllib.request, "urlopen", tg.urlopen)
        svc.tick()
        estado = json.loads((tmp_path / "offsite_state.json").read_text("utf-8"))
        estado["diario"]["enviado_em"] -= 72 * 3600.0  # 3 dias atrás
        (tmp_path / "offsite_state.json").write_text(
            json.dumps(estado), "utf-8")
        saude = svc.check_saude()
        assert saude["ok"] is False and "72 h" in saude["detail"]

    @pytest.mark.asyncio
    async def test_registrar_no_health_nao_critico(self, perfis, tmp_path) -> None:
        monitor = HealthMonitor()
        svc = _svc(perfis, tmp_path)
        assert svc.registrar_no_health(monitor) == "offsite"
        agregado = await monitor.health()
        assert "offsite" in agregado["checks"]
        assert agregado["checks"]["offsite"]["critical"] is False
        assert agregado["checks"]["offsite"]["ok"] is False  # nunca enviado

    def test_registrar_no_health_sem_monitor_e_none(self, perfis, tmp_path) -> None:
        assert _svc(perfis, tmp_path).registrar_no_health(None) is None

    def test_snapshot_resumo_para_o_stats(self, perfis, tmp_path,
                                          monkeypatch) -> None:
        svc = _svc(perfis, tmp_path)
        tg = _Telegram()
        monkeypatch.setattr(urllib.request, "urlopen", tg.urlopen)
        svc.tick()
        snap = svc.snapshot()
        assert snap["canal"] == "telegram:-1001234567890"
        assert snap["ultimo_diario"] == "od-2026-10-20_0309.tar.gz"
        assert snap["ultimo_envio"] > 0


# ---------------------------------------------------------------------------
# Fiação (build_service / build_offsite do launcher)
# ---------------------------------------------------------------------------

class TestBuildService:
    def test_desligado_por_env(self, perfis, tmp_path) -> None:
        diario, capturas = perfis
        assert build_service(_env({
            "OD_OFFSITE": "0", "OD_OFFSITE_CHAT": "-1001",
            "OD_OFFSITE_DIARIO": str(diario),
            "OD_OFFSITE_CAPTURAS": str(capturas),
        })) is None

    def test_sem_chat_nao_constrói(self, perfis, tmp_path) -> None:
        diario, capturas = perfis
        assert build_service(_env({
            "OD_OFFSITE_DIARIO": str(diario),
            "OD_OFFSITE_CAPTURAS": str(capturas),
        })) is None

    def test_sem_token_nao_constrói(self, perfis, tmp_path) -> None:
        diario, capturas = perfis
        assert build_service(_env({
            "OD_OFFSITE_CHAT": "-1001",
            "OD_TELEGRAM_MONITOR_TOKEN": "",
            "OD_OFFSITE_DIARIO": str(diario),
            "OD_OFFSITE_CAPTURAS": str(capturas),
        })) is None

    def test_montagem_completa_com_knobs(self, perfis, tmp_path) -> None:
        diario, capturas = perfis
        svc = build_service(_env({
            "OD_OFFSITE_CHAT": "-100999",
            "OD_OFFSITE_TOKEN": "999:xyz",
            "OD_OFFSITE_DIARIO": str(diario),
            "OD_OFFSITE_CAPTURAS": str(capturas),
            "OD_OFFSITE_ESTADO": str(tmp_path / "est.json"),
            "OD_OFFSITE_FATIA_MB": "10",
            "OD_OFFSITE_INTERVALO_MIN": "15",
            "OD_OFFSITE_IDADE_H_OK": "24",
        }))
        assert svc is not None
        assert svc.cfg.chat_id == "-100999"
        assert svc.cfg.token == "999:xyz"
        assert svc.cfg.fatia_max == 10 * 1024 * 1024
        assert svc.cfg.intervalo_s == 15 * 60.0
        assert svc.cfg.idade_ok_s == 24 * 3600.0

    def test_token_padrao_e_o_do_monitor(self, perfis, tmp_path) -> None:
        diario, capturas = perfis
        svc = build_service(_env({
            "OD_OFFSITE_CHAT": "-1001",
            "OD_TELEGRAM_MONITOR_TOKEN": "MON",
            "OD_OFFSITE_DIARIO": str(diario),
            "OD_OFFSITE_CAPTURAS": str(capturas),
        }))
        assert svc is not None and svc.cfg.token == "MON"

    def test_caminhos_padrao_da_raiz_do_repo(self, tmp_path, monkeypatch) -> None:
        from core.offsite import build_service as bs

        raiz = tmp_path / "repo"
        svc = bs(_env({
            "OD_OFFSITE_CHAT": "-1001", "OD_OFFSITE_TOKEN": "T",
            "OD_REPO_ROOT": str(raiz),
        }), push=None)
        assert svc is not None
        assert svc.cfg.dir_diario == raiz / "backups" / "auto"
        assert svc.cfg.dir_capturas == raiz / "backups" / "auto-capturas"
        assert svc.cfg.estado_path == raiz / "data" / "offsite_state.json"

    def test_build_offsite_do_launcher(self, perfis, tmp_path,
                                       monkeypatch) -> None:
        """A fiação do launcher: env do módulo → serviço ou None."""
        import runtime.launcher as launcher

        diario, capturas = perfis
        monkeypatch.setattr(launcher, "env", _env({
            "OD_OFFSITE_CHAT": "-1001", "OD_OFFSITE_TOKEN": "T",
            "OD_OFFSITE_DIARIO": str(diario),
            "OD_OFFSITE_CAPTURAS": str(capturas),
            "OD_OFFSITE_ESTADO": str(tmp_path / "est.json"),
        }))
        svc = launcher.build_offsite()
        assert svc is not None and svc.cfg.nome == "offsite"

    def test_build_offsite_fora_quando_sem_chat(self, monkeypatch) -> None:
        import runtime.launcher as launcher

        monkeypatch.setattr(launcher, "env", _env({}))  # sem OD_OFFSITE_CHAT
        assert launcher.build_offsite() is None

    def test_build_offsite_contem_excecao(self, monkeypatch) -> None:
        """Exceção construtiva é contida: warn + None, boot segue."""
        import runtime.launcher as launcher

        def _estourar(nome: str, padrao: str = "") -> str:
            raise ValueError("env quebrado")

        monkeypatch.setattr(launcher, "env", _estourar)
        assert launcher.build_offsite() is None


# ---------------------------------------------------------------------------
# API — bloco offsite no /dashboard/stats e card no /admin
# ---------------------------------------------------------------------------

@pytest.fixture()
def _serve_stats():
    """Sobe APIServer sob demanda (mesmo padrão do test_backup.py)."""
    from integrations.api import APIServer

    servidores = []

    def _start(orch_, *, config=None):
        from integrations.api import APIConfig

        cfg = config or APIConfig(port=0, rate_limit_max=0)
        srv = APIServer(orch_, config=cfg)
        srv.serve_background()
        servidores.append(srv)
        return srv

    yield _start
    for srv in servidores:
        try:
            srv.stop()
        except Exception:  # pragma: no cover — teardown defensivo
            pass


class TestStatsDoOffsite:
    """O dono vê no Status quando o backup saiu de casa — None (fora) =
    bloco e card some sem poluir."""

    def test_sem_offsite_o_bloco_nao_aparece(self, _serve_stats,
                                             tmp_path: Path) -> None:
        from tests.test_api import _json_response, _request, make_orch

        srv = _serve_stats(make_orch(tmp_path))
        resposta = _request(srv.bound_port, "GET", "/dashboard/stats")
        dados = _json_response(resposta)
        assert resposta[0] == 200
        assert "offsite" not in dados

    def test_com_offsite_traz_canal_e_ultimo_artefato(self, perfis, tmp_path,
                                                      monkeypatch,
                                                      _serve_stats) -> None:
        from tests.test_api import _json_response, _request, make_orch
        from integrations.api import APIConfig

        svc = _svc(perfis, tmp_path)
        tg = _Telegram()
        with monkeypatch.context() as m:  # patch SÓ no tick: o request
            m.setattr(urllib.request, "urlopen", tg.urlopen)  # do teste é real
            svc.tick()
        cfg = APIConfig(port=0, rate_limit_max=0, offsite=svc)
        srv = _serve_stats(make_orch(tmp_path), config=cfg)
        resposta = _request(srv.bound_port, "GET", "/dashboard/stats")
        status, body, _headers = resposta
        dados = _json_response(resposta)
        assert status == 200 and b'"offsite"' in body
        assert dados["offsite"]["canal"] == "telegram:-1001234567890"
        assert dados["offsite"]["ultimo_diario"] == "od-2026-10-20_0309.tar.gz"
        # o card do painel referencia o bloco novo
        _status, corpo_admin, _ = _request(srv.bound_port, "GET", "/admin")
        assert b"Off-site" in corpo_admin and b"stats.offsite" in corpo_admin
