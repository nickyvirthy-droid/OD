"""OMEGA DRAKON • TESTS
Módulo: tests/test_auto_update.py
Descrição: Parte E do NOMAD — auto-update de modelos/conteúdo.
           O avaliar() é PURO (relógio/estado/disco injetáveis), então os
           testes cobrem CADA camada do pipeline em tabela (padrão do
           Nômade: todas as ramificações sem rede/disco), mais o executor
           (AutoUpdateService) com fila e relógio falsos, auto-disable,
           religação pelo dono, mover atômico travado na árvore do repo,
           manifesto e integração REAL com a fila da Parte D.
Arquiteto: Omega Drakon
"""

from __future__ import annotations

import json
import queue as queue_mod
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

import pytest

from core.auto_update import (
    APLICAR,
    AGUARDAR,
    ACAO_BAIXAR,
    ACAO_RAG_SYNC,
    POS_MOVER,
    PULAR,
    AlvoUpdate,
    AutoUpdateService,
    ConfigUpdate,
    EstadoAlvo,
    _parse_semver,
    avaliar,
    hash_conteudo,
    na_janela,
    proxima_janela,
)

# --- Fixtures e fakes -------------------------------------------------------


def _as_0300(dia: int = 15) -> float:
    """Timestamp às 03:00 (meio da janela padrão 02:00–06:00, hora local)."""
    return time.mktime((2026, 10, dia, 3, 0, 0, 0, 0, -1))


AGORA = _as_0300()
SEM_REDE = 10 ** 12  # 1 PB livre: preflight de disco nunca atrapalha


def _alvo(**kw: Any) -> AlvoUpdate:
    padrao: dict[str, Any] = dict(
        id="modelo-x", nome="Modelo X", acao=ACAO_BAIXAR,
        url="https://exemplo.test/modelo.bin", sha256="a" * 64,
        destino="modelo.bin", versao_atual="1.0.0", versao_nova="1.0.1",
        bytes_estimados=1024,
    )
    padrao.update(kw)
    return AlvoUpdate(**padrao)


class _JobFake:
    def __init__(self, job_id: str) -> None:
        self.id = job_id


class _FilaFake:
    """Fila no contrato da Parte D: enqueue + subscribe (fila de eventos)."""

    def __init__(self) -> None:
        self.enfileirados: list[dict[str, Any]] = []
        self._subs: list["queue_mod.Queue[dict[str, Any]]"] = []
        self._lock = threading.Lock()

    def enqueue(self, url: str, destino: str = "", sha256: str = ""
                ) -> tuple[_JobFake, bool]:
        with self._lock:
            # dedup como a real: mesma URL+destino ativa devolve o mesmo job
            for reg in self.enfileirados:
                if (reg["url"], reg["destino"]) == (url, destino) \
                        and not reg.get("terminal"):
                    return _JobFake(reg["job"]), False
            job = f"dl-{len(self.enfileirados) + 1:04d}"
            self.enfileirados.append(
                {"job": job, "url": url, "destino": destino,
                 "sha256": sha256, "terminal": False},
            )
        return _JobFake(job), True

    def subscribe(self):
        fila: "queue_mod.Queue[dict[str, Any]]" = queue_mod.Queue()
        self._subs.append(fila)
        return fila, lambda: None

    def emitir(self, pacote: dict[str, Any]) -> None:
        """Empurra um evento para os consumidores (como o worker real)."""
        for reg in self.enfileirados:
            if pacote.get("job", {}).get("id") == reg["job"]:
                reg["terminal"] = pacote["job"].get("status") in (
                    "concluido", "erro", "cancelado")
        for sub in self._subs:
            sub.put(pacote)


def _mk(tmp_path: Path, *, cfg: Optional[ConfigUpdate] = None,
        alvos: Optional[list[AlvoUpdate]] = None,
        rag: Optional[CallableRag] = None,
        fila: Optional[_FilaFake] = None,
        push: Any = None,
        clock_value: Optional[float] = None,
        espaco: int = SEM_REDE) -> AutoUpdateService:
    """Serviço hermético: tudo em tmp_path, relógio e disco falsos."""
    svc = AutoUpdateService(
        cfg=cfg or ConfigUpdate(),
        estado_path=tmp_path / "estado.json",
        manifesto_path=tmp_path / "alvos.json",
        raiz_downloads=tmp_path / "downloads",
        repo_root=tmp_path,
        alvos_fn=(lambda: list(alvos)) if alvos is not None else None,
        rag_sync_fn=(rag.chamar if rag is not None else None),
        fila=fila,
        push=push,
        clock=(lambda: clock_value if clock_value is not None else AGORA),
        espaco_livre_fn=lambda _p: espaco,
    )
    return svc


class CallableRag:
    """rag.sync() falso: conta chamadas e pode falhar."""

    def __init__(self, falhar: bool = False) -> None:
        self.chamadas = 0
        self.falhar = falhar

    def chamar(self) -> dict[str, int]:
        self.chamadas += 1
        if self.falhar:
            raise RuntimeError("store cheio")
        return {"arquivos": 3, "chunks": 9, "novos": 1,
                "atualizados": 0, "iguais": 8, "removidos": 0}


class _PushFake:
    """PushService falso: registra (title, body) e pode levantar."""

    def __init__(self, falhar: bool = False) -> None:
        self.chamadas: list[tuple[str, str]] = []
        self.falhar = falhar

    def notify(self, title: str, body: str,
               data: Optional[dict[str, str]] = None) -> dict[str, Any]:
        if self.falhar:
            raise RuntimeError("sem rede FCM")
        self.chamadas.append((title, body))
        return {"ok": True, "sent": 1, "failed": 0}


# --- 1. Pipeline puro: camada a camada --------------------------------------


class TestAvaliarCamadas:
    def test_auto_disable_primeira_camada(self) -> None:
        est = EstadoAlvo(id="modelo-x", desabilitado=True,
                         motivo_desabilitado="3 falhas seguidas: sha")
        d = avaliar([_alvo()], {"modelo-x": est}, ConfigUpdate(),
                    agora=AGORA, espaco_livre=SEM_REDE)[0]
        assert d.acao == PULAR
        assert d.motivo.startswith("desabilitado: 3 falhas seguidas")

    def test_inativa_no_manifesto(self) -> None:
        d = avaliar([_alvo(ativa=False)], {}, ConfigUpdate(),
                    agora=AGORA, espaco_livre=SEM_REDE)[0]
        assert (d.acao, d.motivo) == (PULAR, "inativa_no_manifesto")

    def test_sem_versao_nova(self) -> None:
        d = avaliar([_alvo(versao_nova="")], {}, ConfigUpdate(),
                    agora=AGORA, espaco_livre=SEM_REDE)[0]
        assert (d.acao, d.motivo) == (PULAR, "sem_atualizacao")

    def test_versao_nova_igual_a_instalada(self) -> None:
        est = EstadoAlvo(id="modelo-x", versao_instalada="1.0.1")
        d = avaliar([_alvo()], {"modelo-x": est}, ConfigUpdate(),
                    agora=AGORA, espaco_livre=SEM_REDE)[0]
        assert (d.acao, d.motivo) == (PULAR, "sem_atualizacao")

    def test_major_nunca_aplica_sozinho(self) -> None:
        d = avaliar([_alvo(versao_nova="2.0.0")], {}, ConfigUpdate(),
                    agora=AGORA, espaco_livre=SEM_REDE)[0]
        assert d.acao == PULAR
        assert d.motivo.startswith("major_requer_dono: 1.0.0 → 2.0.0")

    def test_minor_e_patch_passam(self) -> None:
        cfg = ConfigUpdate(cooloff_s=0.0)  # cool-off testado à parte
        for nova in ("1.0.2", "1.1.0"):
            d = avaliar([_alvo(versao_nova=nova)], {}, cfg,
                        agora=AGORA, espaco_livre=SEM_REDE)[0]
            assert d.acao == APLICAR, nova

    def test_hash_nao_tem_major_passa(self) -> None:
        """Versões por conteúdo (hash) não têm 'major' — passam direto."""
        d = avaliar([_alvo(versao_atual="9f3a2b1c", versao_nova="77aa00dd")],
                    {}, ConfigUpdate(cooloff_s=0.0), agora=AGORA,
                    espaco_livre=SEM_REDE)[0]
        assert d.acao == APLICAR

    def test_fora_da_janela_aguarda_com_proxima(self) -> None:
        tarde = time.mktime((2026, 10, 15, 14, 0, 0, 0, 0, -1))  # 14:00
        d = avaliar([_alvo()], {}, ConfigUpdate(), agora=tarde,
                    espaco_livre=SEM_REDE)[0]
        assert d.acao == AGUARDAR
        assert d.motivo.startswith("fora_da_janela (abre 02:00)")

    def test_cooloff_ancora_no_primeiro_visto(self) -> None:
        """Cool-off de 1 h (o default 6 h cruzaria a janela de 4 h)."""
        estado: dict[str, EstadoAlvo] = {}
        cfg = ConfigUpdate(cooloff_s=3600.0)
        # 1º tick na janela: ancora e aguarda
        d1 = avaliar([_alvo()], estado, cfg, agora=AGORA, espaco_livre=SEM_REDE)[0]
        assert d1.acao == AGUARDAR and d1.motivo.startswith("cooloff (faltam")
        assert estado["modelo-x"].primeiro_visto == AGORA
        # 30 min depois: ainda no cool-off
        d2 = avaliar([_alvo()], estado, cfg, agora=AGORA + 1800,
                     espaco_livre=SEM_REDE)[0]
        assert d2.acao == AGUARDAR
        # 1 h depois (04:00, ainda na janela): aplica
        d3 = avaliar([_alvo()], estado, cfg, agora=AGORA + 3600,
                     espaco_livre=SEM_REDE)[0]
        assert d3.acao == APLICAR

    def test_cooloff_default_faz_soak_na_proxima_janela(self) -> None:
        """Física honesta: 6 h de cool-off numa janela de 4 h = soak noturno.

        Versão vista às 03:00 sai do cool-off às 09:00 (fora da janela) e
        aplica na PRÓXIMA janela — atraso real de até ~1 dia, que é
        exatamente o 'soak' que o cool-off do Nômade quer comprar.
        """
        estado: dict[str, EstadoAlvo] = {}
        cfg = ConfigUpdate()  # cool-off 6 h, janela 02:00–06:00
        avaliar([_alvo()], estado, cfg, agora=AGORA, espaco_livre=SEM_REDE)
        depois_do_cooloff = AGORA + 6 * 3600  # 09:00 — fora da janela
        d = avaliar([_alvo()], estado, cfg, agora=depois_do_cooloff,
                    espaco_livre=SEM_REDE)[0]
        assert d.acao == AGUARDAR and d.motivo.startswith("fora_da_janela")

    def test_versao_vista_muda_recomeca_cooloff(self) -> None:
        """Uma versão NOVA paga o cool-off inteiro (release queimada)."""
        estado: dict[str, EstadoAlvo] = {}
        cfg = ConfigUpdate(cooloff_s=3600.0)
        avaliar([_alvo(versao_nova="1.0.1")], estado, cfg,
                agora=AGORA, espaco_livre=SEM_REDE)
        # 50 min depois surge a 1.0.2: âncora recomeça (03:50, na janela)
        depois = AGORA + 50 * 60
        d = avaliar([_alvo(versao_nova="1.0.2")], estado, cfg,
                    agora=depois, espaco_livre=SEM_REDE)[0]
        assert d.acao == AGUARDAR and d.motivo.startswith("cooloff")
        assert estado["modelo-x"].primeiro_visto == depois

    def test_cooloff_override_zero_conteudo_local(self) -> None:
        """Conteúdo local (índice RAG) aplica no primeiro tick na janela."""
        alvo = _alvo(acao=ACAO_RAG_SYNC, cooloff_s=0.0,
                     versao_atual="", versao_nova="9b86582b")
        d = avaliar([alvo], {}, ConfigUpdate(), agora=AGORA,
                    espaco_livre=SEM_REDE)[0]
        assert d.acao == APLICAR

    def test_backoff_apos_falha(self) -> None:
        # Estado REAL de um alvo que já tentou e falhou: âncora velha já
        # pagou o cool-off; o que trava agora é o backoff pós-falha.
        est = EstadoAlvo(id="modelo-x", falhas=1, ultima_tentativa=AGORA,
                         primeiro_visto=AGORA - 7 * 3600,
                         vista_versao="1.0.1")
        cfg = ConfigUpdate()  # intervalo 30 min → espera 30 min × 1 falha
        d1 = avaliar([_alvo()], {"modelo-x": est}, cfg, agora=AGORA + 60,
                     espaco_livre=SEM_REDE)[0]
        assert d1.acao == AGUARDAR and d1.motivo.startswith("backoff_apos_falha")
        d2 = avaliar([_alvo()], {"modelo-x": est}, cfg, agora=AGORA + 31 * 60,
                     espaco_livre=SEM_REDE)[0]
        assert d2.acao == APLICAR

    def test_cap_de_bytes_estanca_ciclo(self) -> None:
        cfg = ConfigUpdate(cap_bytes=2048, cooloff_s=0.0)  # 2 KiB de orçamento
        a1 = _alvo(id="a", bytes_estimados=1500)
        a2 = _alvo(id="b", url="https://exemplo.test/b.bin", bytes_estimados=1000)
        ds = avaliar([a1, a2], {}, cfg, agora=AGORA, espaco_livre=SEM_REDE)
        assert ds[0].acao == APLICAR
        assert ds[1].acao == PULAR and ds[1].motivo.startswith("cap_de_bytes")

    def test_conteudo_local_nunca_estanca_no_cap(self) -> None:
        cfg = ConfigUpdate(cap_bytes=0)
        alvo = _alvo(acao=ACAO_RAG_SYNC, cooloff_s=0.0, bytes_estimados=0)
        d = avaliar([alvo], {}, cfg, agora=AGORA, espaco_livre=SEM_REDE)[0]
        assert d.acao == APLICAR

    def test_preflight_sem_espaco(self) -> None:
        d = avaliar([_alvo(cooloff_s=0.0)], {}, ConfigUpdate(cooloff_s=0.0),
                    agora=AGORA, espaco_livre=1000)[0]  # precisa 1024 × 1.1
        assert d.acao == PULAR and d.motivo.startswith("sem_espaco")

    def test_preflight_sha_invalido(self) -> None:
        d = avaliar([_alvo(sha256="abc123")], {}, ConfigUpdate(cooloff_s=0.0),
                    agora=AGORA, espaco_livre=SEM_REDE)[0]
        assert d.acao == PULAR and d.motivo.startswith("sha256_invalido")

    def test_preflight_url_invalida(self) -> None:
        cfg = ConfigUpdate(cooloff_s=0.0)
        for url in ("ftp://x/y", "file:///etc/passwd", "sem-esquema"):
            d = avaliar([_alvo(url=url)], {}, cfg,
                        agora=AGORA, espaco_livre=SEM_REDE)[0]
            assert d.acao == PULAR and d.motivo.startswith("url_invalida"), url

    def test_estado_novo_e_inserido_no_dict(self) -> None:
        """Estado ausente vira EstadoAlvo — quem chama persiste se quiser."""
        estado: dict[str, EstadoAlvo] = {}
        avaliar([_alvo(versao_nova="")], estado, ConfigUpdate(),
                agora=AGORA, espaco_livre=SEM_REDE)
        assert "modelo-x" in estado and estado["modelo-x"].falhas == 0

    def test_sem_alvos_devolve_lista_vazia(self) -> None:
        assert avaliar([], {}, ConfigUpdate(), agora=AGORA,
                       espaco_livre=SEM_REDE) == []


class TestJanela:
    def test_janela_simples(self) -> None:
        assert na_janela("02:00-06:00", _as_0300())
        assert not na_janela("02:00-06:00",
                             time.mktime((2026, 10, 15, 13, 0, 0, 0, 0, -1)))
        # limites: 02:00 entra, 06:00 sai
        assert na_janela("02:00-06:00",
                         time.mktime((2026, 10, 15, 2, 0, 0, 0, 0, -1)))
        assert not na_janela("02:00-06:00",
                             time.mktime((2026, 10, 15, 6, 0, 0, 0, 0, -1)))

    def test_janela_atravessa_meia_noite(self) -> None:
        virada = time.mktime((2026, 10, 15, 23, 30, 0, 0, 0, -1))
        madrugada = time.mktime((2026, 10, 16, 1, 30, 0, 0, 0, -1))
        meio_dia = time.mktime((2026, 10, 16, 12, 0, 0, 0, 0, -1))
        assert na_janela("23:00-02:00", virada)
        assert na_janela("23:00-02:00", madrugada)
        assert not na_janela("23:00-02:00", meio_dia)

    def test_proxima_janela_e_futura(self) -> None:
        tarde = time.mktime((2026, 10, 15, 14, 0, 0, 0, 0, -1))
        prox = proxima_janela("02:00-06:00", tarde)
        assert prox > tarde
        assert time.localtime(prox).tm_hour == 2

    def test_parse_semver(self) -> None:
        assert _parse_semver("1.2.3") == (1, 2, 3)
        assert _parse_semver("v1.2") is None
        assert _parse_semver("9b86582b") is None
        assert _parse_semver("1.2.3-rc1") is None  # só canônico


class TestConfigDeEnv:
    def test_defaults(self) -> None:
        cfg = ConfigUpdate.de_env(lambda nome, d: d)
        assert cfg.janela == "02:00-06:00"
        assert cfg.cooloff_s == 6 * 3600.0
        assert cfg.cap_bytes == 2 * 1024 ** 3
        assert cfg.max_falhas == 3 and cfg.intervalo_s == 1800.0
        assert cfg.habilitado is True

    def test_sobrescreve_por_env(self) -> None:
        valores = {"OD_UPDATE_JANELA": "22:00-23:30",
                   "OD_UPDATE_COOLOFF_H": "1.5",
                   "OD_UPDATE_CAP_MB": "512",
                   "OD_UPDATE_MAX_FALHAS": "5",
                   "OD_UPDATE_INTERVALO_MIN": "10",
                   "OD_UPDATE_ENABLED": "0"}
        cfg = ConfigUpdate.de_env(lambda n, d: valores.get(n, d))
        assert cfg.janela == "22:00-23:30"
        assert cfg.cooloff_s == 5400.0
        assert cfg.cap_bytes == 512 * 1024 ** 2
        assert cfg.max_falhas == 5 and cfg.intervalo_s == 600.0
        assert cfg.habilitado is False

    def test_janela_invalida_cai_no_default(self) -> None:
        cfg = ConfigUpdate.de_env(
            lambda n, d: "tarde-cedo" if n == "OD_UPDATE_JANELA" else d)
        assert cfg.janela == "02:00-06:00"

    def test_para_dict(self) -> None:
        d = ConfigUpdate().para_dict()
        assert d["janela"] == "02:00-06:00" and d["cooloff_h"] == 6.0
        assert d["cap_mb"] == 2048 and d["max_falhas"] == 3


# --- 2. Executor (AutoUpdateService) -----------------------------------------


class TestExecutor:
    def test_rag_sync_aplica_e_grava_estado(self, tmp_path: Path) -> None:
        rag = CallableRag()
        svc = _mk(tmp_path, alvos=[_alvo(acao=ACAO_RAG_SYNC, cooloff_s=0.0,
                                         versao_atual="", versao_nova="abc123")],
                  rag=rag)
        decisoes = svc.tick()
        assert decisoes[0].acao == APLICAR
        assert rag.chamadas == 1
        estado = json.loads((tmp_path / "estado.json").read_text())["alvos"]
        assert estado["modelo-x"]["versao_instalada"] == "abc123"
        assert estado["modelo-x"]["falhas"] == 0

    def test_push_anuncia_aplicado_no_rag_sync(self, tmp_path: Path) -> None:
        """TODO §3.8 (B): 'auto-update aplicado' vira notificação no celular."""
        rag = CallableRag()
        push = _PushFake()
        svc = _mk(tmp_path, alvos=[_alvo(acao=ACAO_RAG_SYNC, cooloff_s=0.0,
                                         versao_atual="", versao_nova="abc123")],
                  rag=rag, push=push)
        assert svc.tick()[0].acao == APLICAR
        assert push.chamadas == [
            ("Auto-update aplicado",
             "Índice RAG re-sincronizado — 9 chunks (modelo-x)"),
        ]

    def test_push_anuncia_quando_o_download_conclui(self, tmp_path: Path) -> None:
        """Evento público da fila: sucesso → aviso com alvo + versão."""
        push = _PushFake()
        svc = _mk(tmp_path, alvos=[_alvo()], push=push)
        svc._pendentes["job1"] = "modelo-x"
        svc.tratar_evento({"job": {"id": "job1", "status": "concluido"}})
        assert push.chamadas == [
            ("Auto-update aplicado", "modelo-x aplicado (1.0.1)"),
        ]

    def test_push_falho_nao_derruba_o_rag_sync(self, tmp_path: Path) -> None:
        """O aviso é best-effort: push que levanta não trava o ciclo."""
        rag = CallableRag()
        push = _PushFake(falhar=True)
        svc = _mk(tmp_path, alvos=[_alvo(acao=ACAO_RAG_SYNC, cooloff_s=0.0,
                                         versao_atual="", versao_nova="abc123")],
                  rag=rag, push=push)
        assert svc.tick()[0].acao == APLICAR
        assert rag.chamadas == 1          # o sync aconteceu apesar do push
        assert push.chamadas == []        # e a falha ficou contida
        estado = json.loads((tmp_path / "estado.json").read_text())["alvos"]
        assert estado["modelo-x"]["versao_instalada"] == "abc123"

    def test_rag_sync_falha_conta_e_auto_disable_ao_limite(
            self, tmp_path: Path) -> None:
        rag = CallableRag(falhar=True)
        cfg = ConfigUpdate(max_falhas=3, cooloff_s=0.0, intervalo_s=0.0)
        alvo = _alvo(acao=ACAO_RAG_SYNC, cooloff_s=0.0,
                     versao_atual="", versao_nova="abc123")
        svc = _mk(tmp_path, cfg=cfg, alvos=[alvo], rag=rag)

        for rodada in (1, 2, 3):
            svc.tick()
            estado = json.loads((tmp_path / "estado.json").read_text())["alvos"]
            assert estado["modelo-x"]["falhas"] == rodada
        assert estado["modelo-x"]["desabilitado"] is True
        assert "3 falhas seguidas" in estado["modelo-x"]["motivo_desabilitado"]

        # 4º tick: a 1ª camada bloqueia SEM nem chamar o rag
        decisoes = svc.tick()
        assert decisoes[0].acao == PULAR
        assert decisoes[0].motivo.startswith("desabilitado:")
        assert rag.chamadas == 3

    def test_religar_pelo_dono(self, tmp_path: Path) -> None:
        rag = CallableRag(falhar=True)
        cfg = ConfigUpdate(max_falhas=1, cooloff_s=0.0, intervalo_s=0.0)
        alvo = _alvo(acao=ACAO_RAG_SYNC, cooloff_s=0.0, versao_nova="abc")
        svc = _mk(tmp_path, cfg=cfg, alvos=[alvo], rag=rag)
        svc.tick()  # 1 falha → desabilitado
        assert svc.resetar_alvo("modelo-x") is True
        rag.falhar = False
        svc.tick()  # religado → aplica
        estado = json.loads((tmp_path / "estado.json").read_text())["alvos"]
        assert estado["modelo-x"]["desabilitado"] is False
        assert estado["modelo-x"]["versao_instalada"] == "abc"

    def test_resetar_alvo_desconhecido(self, tmp_path: Path) -> None:
        svc = _mk(tmp_path, alvos=[])
        assert svc.resetar_alvo("nao-existe") is False

    def test_enfileira_na_fila_com_sha(self, tmp_path: Path) -> None:
        fila = _FilaFake()
        alvo = _alvo(cooloff_s=0.0, versao_atual="", versao_nova="1.0.0")
        svc = _mk(tmp_path, alvos=[alvo], fila=fila)
        svc.start()
        try:
            svc.tick()
            assert fila.enfileirados[0]["url"] == "https://exemplo.test/modelo.bin"
            assert fila.enfileirados[0]["sha256"] == "a" * 64
            assert fila.enfileirados[0]["destino"] == "modelo.bin"

            # evento terminal de sucesso chega pelo consumidor
            fila.emitir({"evento": "estado",
                         "job": {"id": "dl-0001", "status": "concluido"}})
            _esperar(lambda: json.loads(
                (tmp_path / "estado.json").read_text()
            )["alvos"]["modelo-x"]["versao_instalada"] == "1.0.0")
            assert svc._pendentes == {}
        finally:
            svc.stop()

    def test_evento_de_erro_e_falha_dura(self, tmp_path: Path) -> None:
        fila = _FilaFake()
        alvo = _alvo(cooloff_s=0.0, versao_atual="", versao_nova="1.0.0")
        svc = _mk(tmp_path, alvos=[alvo], fila=fila)
        svc.start()
        try:
            svc.tick()
            fila.emitir({"evento": "estado", "job": {
                "id": "dl-0001", "status": "erro",
                "erro": "HTTP 404: não existe"}})
            _esperar(lambda: json.loads(
                (tmp_path / "estado.json").read_text()
            )["alvos"]["modelo-x"]["falhas"] == 1)
            estado = json.loads((tmp_path / "estado.json").read_text())["alvos"]
            assert "404" in estado["modelo-x"]["ultimo_erro"]
        finally:
            svc.stop()

    def test_dedup_nao_conta_como_falha(self, tmp_path: Path) -> None:
        fila = _FilaFake()
        alvo = _alvo(cooloff_s=0.0, versao_atual="", versao_nova="1.0.0")
        svc = _mk(tmp_path, alvos=[alvo], fila=fila)
        svc.start()
        try:
            svc.tick()   # enfileira dl-0001
            svc.tick()   # mesmo URL+destino ainda ativo → dedup
            assert len(fila.enfileirados) == 1  # nunca dois workers
            assert fila.enfileirados[0]["job"] in svc._pendentes
        finally:
            svc.stop()

    def test_mover_apos_download(self, tmp_path: Path) -> None:
        fila = _FilaFake()
        (tmp_path / "downloads").mkdir()
        (tmp_path / "voz").mkdir()
        alvo = _alvo(cooloff_s=0.0, versao_atual="", versao_nova="2.0.0",
                     pos_download=POS_MOVER, mover_para="voz/modelo.bin")
        svc = _mk(tmp_path, alvos=[alvo], fila=fila)
        svc.start()
        try:
            svc.tick()
            # a fila "baixa" escrevendo o arquivo staged
            (tmp_path / "downloads" / "modelo.bin").write_bytes(b"pesos")
            fila.emitir({"evento": "estado",
                         "job": {"id": "dl-0001", "status": "concluido"}})
            _esperar(lambda: (tmp_path / "voz" / "modelo.bin").exists())
            assert (tmp_path / "voz" / "modelo.bin").read_bytes() == b"pesos"
            assert not (tmp_path / "downloads" / "modelo.bin").exists()
            estado = json.loads((tmp_path / "estado.json").read_text())["alvos"]
            assert estado["modelo-x"]["versao_instalada"] == "2.0.0"
        finally:
            svc.stop()

    def test_mover_fora_da_arvore_e_falha_dura(self, tmp_path: Path) -> None:
        fila = _FilaFake()
        (tmp_path / "downloads").mkdir()
        alvo = _alvo(cooloff_s=0.0, versao_atual="", versao_nova="2.0.0",
                     pos_download=POS_MOVER, mover_para="../fora/bin")
        svc = _mk(tmp_path, alvos=[alvo], fila=fila)
        svc.start()
        try:
            svc.tick()
            (tmp_path / "downloads" / "modelo.bin").write_bytes(b"x")
            fila.emitir({"evento": "estado",
                         "job": {"id": "dl-0001", "status": "concluido"}})
            _esperar(lambda: json.loads(
                (tmp_path / "estado.json").read_text()
            )["alvos"]["modelo-x"]["falhas"] == 1)
            estado = json.loads((tmp_path / "estado.json").read_text())["alvos"]
            assert "fora_da_arvore" in estado["modelo-x"]["ultimo_erro"]
            assert not (tmp_path.parent / "fora").exists()
        finally:
            svc.stop()

    def test_dry_run_nao_executa_nem_persiste(self, tmp_path: Path) -> None:
        rag = CallableRag()
        alvo = _alvo(acao=ACAO_RAG_SYNC, cooloff_s=0.0,
                     versao_atual="", versao_nova="abc123")
        svc = _mk(tmp_path, alvos=[alvo], rag=rag)
        decisoes = svc.tick(dry_run=True)
        assert decisoes[0].acao == APLICAR       # mostra o que FARIA
        assert rag.chamadas == 0                  # mas não executa
        assert not (tmp_path / "estado.json").exists()  # nem persiste
        assert svc.ultimas_decisoes[0]["alvo"] == "modelo-x"

    def test_dry_run_nao_ancora_cooloff(self, tmp_path: Path) -> None:
        """Dry-run é observador: não pode mover o âncora do cool-off."""
        svc = _mk(tmp_path, alvos=[_alvo(cooloff_s=0.0, versao_nova="")])
        svc.tick(dry_run=True)
        assert not (tmp_path / "estado.json").exists()

    def test_estado_corrompido_recomeca_do_zero(self, tmp_path: Path) -> None:
        (tmp_path / "estado.json").write_text("{quebrado", encoding="utf-8")
        svc = _mk(tmp_path, alvos=[])
        assert svc.carregar_estado() == {}

    def test_estado_resumo_para_o_painel(self, tmp_path: Path) -> None:
        rag = CallableRag()
        alvo = _alvo(acao=ACAO_RAG_SYNC, cooloff_s=0.0, versao_nova="abc")
        svc = _mk(tmp_path, alvos=[alvo], rag=rag)
        svc.tick()
        resumo = svc.estado_resumo()
        assert resumo["config"]["janela"] == "02:00-06:00"
        assert resumo["alvos"][0]["id"] == "modelo-x"
        assert resumo["estado"][0]["versao_instalada"] == "abc"
        assert resumo["desabilitados"] == [] and resumo["pendentes"] == []
        assert resumo["ultimo_tick"] == AGORA

    def test_health_check(self, tmp_path: Path) -> None:
        svc = _mk(tmp_path, alvos=[])
        assert svc.health_check()["ok"] is True
        estado = { "modelo-x": EstadoAlvo(id="modelo-x", desabilitado=True,
                                          motivo_desabilitado="x") }
        svc.gravar_estado(estado)
        chk = svc.health_check()
        assert chk["ok"] is False and chk["desligados"] == ["modelo-x"]

    def test_health_check_registrado_no_monitor_real(self, tmp_path: Path) -> None:
        """O HealthMonitor chama `check(monitor)` — a assinatura aceita o arg.

        Bug de produção pego na prova viva de 2026-10-14: sem o parâmetro
        o monitor registrava "check quebrado: TypeError" e o /health
        degradava (não-crítico, mas sujava o status geral).
        """
        import asyncio

        from observability.health import HealthMonitor
        svc = _mk(tmp_path, alvos=[])
        mon = HealthMonitor()
        mon.register("auto_update", svc.health_check, critical=False)
        resultado = asyncio.run(mon.check("auto_update"))
        assert resultado is not None
        assert resultado.ok is True


def _esperar(cond: Callable[[], bool], timeout: float = 5.0) -> None:
    """Espera um condicional (consumidor roda em thread própria)."""
    fim = time.time() + timeout
    while time.time() < fim:
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError("condição não alcançada no tempo dado")


# --- 3. Manifesto e provedores -----------------------------------------------


class TestManifesto:
    def test_ausente_devolve_vazio(self, tmp_path: Path) -> None:
        svc = _mk(tmp_path, alvos=None)
        assert svc.carregar_manifesto() == []

    def test_parse_com_defaults_e_dedup(self, tmp_path: Path) -> None:
        (tmp_path / "alvos.json").write_text(json.dumps({"alvos": [
            {"id": "a", "url": "https://x/a.bin", "versao_nova": "1.0.0"},
            {"id": "a", "url": "https://x/a2.bin"},          # duplicado → último
            {"id": "b", "campo_extra_ignorado": "ok"},        # campo extra ignora
            {"sem_id": True},                                # sem id → fora
            {"id": "c", "bytes_estimados": "abc"},           # erro → warn + fora
        ]}), encoding="utf-8")
        svc = _mk(tmp_path, alvos=None)
        alvos = {a.id: a for a in svc.carregar_manifesto()}
        assert set(alvos) == {"a", "b"}     # "c" (bytes quebrado) e "sem_id" fora
        assert alvos["a"].url == "https://x/a2.bin"
        assert alvos["a"].acao == ACAO_BAIXAR
        # campo extra é ignorado, mas o alvo parseia com os defaults
        assert alvos["b"].ativa is True and alvos["b"].bytes_estimados == -1
        assert alvos["b"].url == "" and alvos["b"].sha256 == ""

    def test_cooloff_h_convertido_para_segundos(self, tmp_path: Path) -> None:
        (tmp_path / "alvos.json").write_text(json.dumps(
            {"alvos": [{"id": "a", "url": "https://x/a", "cooloff_h": 2}]}),
            encoding="utf-8")
        svc = _mk(tmp_path, alvos=None)
        assert svc.carregar_manifesto()[0].cooloff_s == 7200.0

    def test_ilegivel_devolve_vazio(self, tmp_path: Path) -> None:
        (tmp_path / "alvos.json").write_text("não é json", encoding="utf-8")
        svc = _mk(tmp_path, alvos=None)
        assert svc.carregar_manifesto() == []

    def test_alvos_do_ciclo_rag_mais_manifesto(self, tmp_path: Path) -> None:
        (tmp_path / "alvos.json").write_text(json.dumps(
            {"alvos": [{"id": "voz", "url": "https://x/v.bin"}]}),
            encoding="utf-8")
        svc = _mk(tmp_path, alvos=None, rag=CallableRag())  # sem alvos_fn
        ids = [a.id for a in svc._alvos()]
        assert ids == ["indice-rag", "voz"]


class TestProvedores:
    def test_hash_conteudo_muda_quando_edita(self, tmp_path: Path) -> None:
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "a.md").write_text("olá", encoding="utf-8")
        antes = hash_conteudo(tmp_path)
        assert antes == hash_conteudo(tmp_path)   # determinístico
        (tmp_path / "docs" / "a.md").write_text("olá!", encoding="utf-8")
        assert hash_conteudo(tmp_path) != antes   # conteúdo mudou

    def test_alvo_rag_sem_pipeline_some(self, tmp_path: Path) -> None:
        from core.auto_update import _alvos_rag
        assert _alvos_rag(tmp_path, tem_rag=False) == []

    def test_alvo_rag_com_pipeline(self, tmp_path: Path) -> None:
        from core.auto_update import _alvos_rag
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "a.md").write_text("x", encoding="utf-8")
        alvos = _alvos_rag(tmp_path, tem_rag=True)
        assert len(alvos) == 1
        alvo = alvos[0]
        assert alvo.id == "indice-rag" and alvo.acao == ACAO_RAG_SYNC
        assert alvo.cooloff_s == 0.0
        assert alvo.versao_nova == hash_conteudo(tmp_path)


# --- 4. Integração REAL com a fila da Parte D ---------------------------------


class _Resp:
    """Resposta HTTP falsa no formato que a fila da Parte D lê."""

    def __init__(self, corpo: bytes, status: int = 200,
                 headers: Optional[dict[str, str]] = None) -> None:
        self.status = status
        self.headers = headers or {"Content-Length": str(len(corpo))}
        self._corpo = corpo

    def read(self, n: int = -1) -> bytes:
        if not self._corpo:
            return b""
        if n < 0:
            n = len(self._corpo)
        bloco, self._corpo = self._corpo[:n], self._corpo[n:]
        return bloco

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *args: Any) -> None:
        return None


class TestIntegracaoFilaReal:
    """O motor de download é a fila da Parte D — aqui os dois se encontram."""

    def _fila_real(self, tmp_path: Path, corpo: bytes):
        from core.downloads import DownloadQueue

        def opener(req: Any, timeout: float = 0) -> _Resp:
            return _Resp(corpo)

        return DownloadQueue(base_dir=tmp_path / "downloads",
                             state_path=tmp_path / "fila.json",
                             opener=opener)

    def _esperar_job(self, estado_path: Path, chave: str, valor: Any,
                     timeout: float = 10.0) -> None:
        def _checar() -> bool:
            try:
                dados = json.loads(estado_path.read_text())["alvos"]
                return dados["modelo-x"].get(chave) == valor
            except Exception:
                return False
        _esperar(_checar, timeout=timeout)

    def test_download_real_conclui_e_registra_sucesso(
            self, tmp_path: Path) -> None:
        fila = self._fila_real(tmp_path, b"pesos-de-verdade")
        fila.start()
        alvo = _alvo(cooloff_s=0.0, versao_atual="", versao_nova="3.1.4",
                     sha256="")   # sem sha: validação é da fila
        svc = _mk(tmp_path, alvos=[alvo], fila=fila)
        svc.start()
        try:
            svc.tick()
            self._esperar_job(tmp_path / "estado.json",
                              "versao_instalada", "3.1.4")
            assert (tmp_path / "downloads" / "modelo.bin").read_bytes() \
                == b"pesos-de-verdade"
            assert fila.get("dl-0001").status == "concluido"
        finally:
            svc.stop()
            fila.stop()

    def test_sha_divergente_vira_falha_dura(self, tmp_path: Path) -> None:
        fila = self._fila_real(tmp_path, b"conteudo-errado")
        fila.start()
        alvo = _alvo(cooloff_s=0.0, versao_atual="", versao_nova="1.0.0",
                     sha256="b" * 64)  # não bate com o conteúdo
        svc = _mk(tmp_path, alvos=[alvo], fila=fila)
        svc.start()
        try:
            svc.tick()
            self._esperar_job(tmp_path / "estado.json", "falhas", 1)
            estado = json.loads((tmp_path / "estado.json").read_text())["alvos"]
            assert "sha" in estado["modelo-x"]["ultimo_erro"].lower()
            assert estado["modelo-x"]["versao_instalada"] == ""  # não registrou
        finally:
            svc.stop()
            fila.stop()


# --- 4b. Métricas Prometheus (TODO §3.2) --------------------------------------


class TestMetricasPrometheus:
    """`od_auto_update_*` no /metrics — contadores contados onde acontecem."""

    def test_tick_conta_ciclo_e_decisao(self, tmp_path: Path) -> None:
        rag = CallableRag()
        svc = _mk(tmp_path, alvos=[_alvo(acao=ACAO_RAG_SYNC, cooloff_s=0.0,
                                         versao_atual="", versao_nova="abc123")],
                  rag=rag)
        assert svc.tick()[0].acao == APLICAR
        m = svc.metricas.snapshot()
        assert m["ticks"] == 1 and m["ticks_dry_run"] == 0
        assert m["decisao_aplicar"] == 1
        assert m["aplicados"] == 1 and m["rag_syncs"] == 1
        assert m["falhas"] == 0 and m["auto_desligados"] == 0

    def test_dry_run_conta_separado_e_nao_aplica(self, tmp_path: Path) -> None:
        rag = CallableRag()
        svc = _mk(tmp_path, alvos=[_alvo(acao=ACAO_RAG_SYNC, cooloff_s=0.0,
                                         versao_atual="", versao_nova="abc123")],
                  rag=rag)
        svc.tick(dry_run=True)
        m = svc.metricas.snapshot()
        assert m["ticks"] == 0 and m["ticks_dry_run"] == 1
        assert m["decisao_aplicar"] == 1   # decidiu…
        assert m["aplicados"] == 0         # …mas nada executou
        assert rag.chamadas == 0

    def test_falha_dura_conta_e_auto_disable_uma_vez(
            self, tmp_path: Path) -> None:
        rag = CallableRag(falhar=True)
        cfg = ConfigUpdate(max_falhas=1, cooloff_s=0.0, intervalo_s=0.0)
        svc = _mk(tmp_path, cfg=cfg, rag=rag, alvos=[
            _alvo(acao=ACAO_RAG_SYNC, cooloff_s=0.0, versao_nova="abc")])
        svc.tick()   # falha dura → desliga
        svc.tick()   # desabilitado → pular
        m = svc.metricas.snapshot()
        assert m["falhas"] == 1
        assert m["auto_desligados"] == 1   # a TRANSIÇÃO conta uma vez
        assert m["decisao_pular"] == 1
        assert m["aplicados"] == 0
        assert m["ticks"] == 2             # ciclo ruim ainda é ciclo
        assert "od_auto_update_alvo_desabilitado 1" in svc.prometheus_lines()

    def test_decisao_aguardar_do_cooloff_entra_no_contador(
            self, tmp_path: Path) -> None:
        svc = _mk(tmp_path, alvos=[_alvo(cooloff_s=3600.0, versao_atual="",
                                         versao_nova="1.0.0")])
        assert svc.tick()[0].acao == AGUARDAR
        m = svc.metricas.snapshot()
        assert m["decisao_aguardar"] == 1 and m["decisao_pular"] == 0
        assert 'od_auto_update_decisao_total{decisao="aguardar"} 1' \
            in svc.prometheus_lines()

    def test_download_novo_e_dedup_contam_separado(self, tmp_path: Path) -> None:
        fila = _FilaFake()
        svc = _mk(tmp_path, alvos=[_alvo(cooloff_s=0.0, versao_atual="",
                                         versao_nova="1.0.0")], fila=fila)
        svc.tick()
        svc.tick()   # mesmo alvo: a fila já tem o job ativo → dedup
        m = svc.metricas.snapshot()
        assert m["downloads"] == 1 and m["dedups"] == 1
        assert len(fila.enfileirados) == 1
        assert m["aplicados"] == 0     # enfileirar não é aplicar

    def test_download_concluido_conta_aplicado(self, tmp_path: Path) -> None:
        svc = _mk(tmp_path, alvos=[_alvo()])
        svc._pendentes["job1"] = "modelo-x"
        svc.tratar_evento({"job": {"id": "job1", "status": "concluido"}})
        assert svc.metricas.aplicados == 1
        assert "od_auto_update_aplicado_total 1" in svc.prometheus_lines()

    def test_evento_torto_conta_erro_e_nao_mata_o_consumidor(
            self, tmp_path: Path, monkeypatch: Any) -> None:
        fila = _FilaFake()
        svc = _mk(tmp_path, alvos=[_alvo()], fila=fila)

        def _boom(_pacote: dict[str, Any]) -> None:
            raise RuntimeError("evento torto")

        monkeypatch.setattr(svc, "tratar_evento", _boom)
        svc.start()
        try:
            fila.emitir({"job": {"id": "dl-0001", "status": "concluido"}})
            _esperar(lambda: svc.metricas.erros == 1)
        finally:
            svc.stop()
        assert "od_auto_update_erro_total 1" in svc.prometheus_lines()

    def test_prometheus_lines_formato_e_idade_do_ciclo(
            self, tmp_path: Path) -> None:
        svc = _mk(tmp_path, alvos=[_alvo(acao=ACAO_RAG_SYNC, cooloff_s=0.0,
                                         versao_nova="abc")], rag=CallableRag())
        linhas = svc.prometheus_lines()
        texto = "\n".join(linhas)
        assert "# TYPE od_auto_update_tick_total counter" in linhas
        assert "od_auto_update_tick_total 0" in linhas
        assert 'od_auto_update_decisao_total{decisao="aplicar"} 0' in linhas
        assert "od_auto_update_aplicado_total 0" in linhas
        assert "od_auto_update_falha_total 0" in linhas
        assert "od_auto_update_alvo 1" in linhas
        assert "od_auto_update_download_pendente 0" in linhas
        # nunca rodou: a idade NÃO é inventada como zero
        assert "od_auto_update_ultimo_tick_segundos" not in texto

        svc.tick()
        linhas = svc.prometheus_lines()
        assert "od_auto_update_tick_total 1" in linhas
        assert "od_auto_update_aplicado_total 1" in linhas
        assert "od_auto_update_rag_sync_total 1" in linhas
        assert 'od_auto_update_decisao_total{decisao="aplicar"} 1' in linhas
        assert "od_auto_update_ultimo_tick_segundos 0.0" in linhas

    def test_prometheus_lines_estado_ilegivel_ainda_expoe_contadores(
            self, tmp_path: Path, monkeypatch: Any) -> None:
        svc = _mk(tmp_path, alvos=[])

        def _quebrado() -> dict[str, Any]:
            raise OSError("estado ilegível")

        monkeypatch.setattr(svc, "estado_resumo", _quebrado)
        linhas = svc.prometheus_lines()   # não levanta
        assert "od_auto_update_tick_total 0" in linhas
        assert not any(l.startswith("od_auto_update_alvo") for l in linhas)

    def test_serve_de_fonte_viva_no_metrics_collector(self, tmp_path: Path) -> None:
        """O contrato do /metrics: add_source(serviço.prometheus_lines)."""
        from observability.metrics import MetricsCollector

        svc = _mk(tmp_path, alvos=[_alvo(acao=ACAO_RAG_SYNC, cooloff_s=0.0,
                                         versao_nova="abc")], rag=CallableRag())
        coletor = MetricsCollector()
        coletor.counter("od_api_requests_total", "Requisições.")
        coletor.add_source(svc.prometheus_lines)
        svc.tick()
        texto = coletor.render()
        assert "# TYPE od_auto_update_tick_total counter" in texto
        assert "od_auto_update_tick_total 1" in texto
        assert "od_auto_update_aplicado_total 1" in texto
        assert "# TYPE od_api_requests_total counter" in texto
        assert coletor.health()["errors"] == 0

    def test_ligacao_no_launcher_e_best_effort(self, tmp_path: Path) -> None:
        """A fiação do boot (build_metrics → add_source) é testada aqui."""
        from observability.metrics import MetricsCollector
        from runtime.launcher import ligar_metricas_auto_update

        coletor = MetricsCollector()
        svc = _mk(tmp_path, alvos=[_alvo(acao=ACAO_RAG_SYNC, cooloff_s=0.0,
                                         versao_nova="abc")], rag=CallableRag())
        assert ligar_metricas_auto_update(coletor, svc) is True
        svc.tick()
        assert "od_auto_update_tick_total 1" in coletor.render()
        # desligado (OD_AUTO_UPDATE=0) ou sem coletor: boot segue igual
        assert ligar_metricas_auto_update(coletor, None) is False
        assert ligar_metricas_auto_update(None, svc) is False


# --- 5. Rotas da API (painel + admin) ----------------------------------------


def _request(port: int, method: str, path: str, *, api_key: str = "",
             body: Any = None) -> tuple[int, bytes]:
    """HTTP real contra o servidor de teste (mesmo molde de test_downloads)."""
    import urllib.error
    import urllib.request

    url = f"http://127.0.0.1:{port}{path}"
    dados = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json"} if dados else {}
    if api_key:
        hdrs["X-API-Key"] = api_key
    req = urllib.request.Request(url, data=dados, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _json_body(resposta: bytes) -> dict[str, Any]:
    return json.loads(resposta.decode() or "{}")


@pytest.fixture()
def serve():
    """Sobe APIServers sob demanda e derruba todos no fim."""
    from integrations.api import APIServer

    servers: list[Any] = []

    def _start(orch: Any = None, *, config: Any = None) -> Any:
        srv = APIServer(orch, config=config)
        srv.serve_background()
        servers.append(srv)
        return srv

    yield _start
    for srv in servers:
        try:
            srv.stop()
        except Exception:
            pass


@pytest.fixture()
def srv_auto(serve, tmp_path: Path):
    """Serviço real de auto-update injetado no APIServer (relógio fixo)."""
    from integrations.api import APIConfig

    rag = CallableRag()
    svc = _mk(tmp_path, alvos=[_alvo(acao=ACAO_RAG_SYNC, cooloff_s=0.0,
                                     versao_atual="", versao_nova="abc123")],
              rag=rag)
    cfg = APIConfig(port=0, rate_limit_max=0, api_key="segredo123",
                    auth_all=True, auto_update=svc)
    servidor = serve(None, config=cfg)
    yield servidor, svc, rag
    svc.stop()


class TestAutoUpdateRotas:
    def test_sem_credencial_leva_401(self, srv_auto) -> None:
        servidor, _, _ = srv_auto
        status, _ = _request(servidor.bound_port, "GET", "/admin/auto-update")
        assert status == 401

    def test_sem_servico_503(self, serve) -> None:
        from integrations.api import APIConfig
        servidor = serve(None, config=APIConfig(
            port=0, rate_limit_max=0, api_key="segredo123", auth_all=True))
        for metodo, caminho in (("GET", "/admin/auto-update"),
                                ("POST", "/admin/auto-update/dry-run"),
                                ("POST", "/admin/auto-update/reset")):
            status, corpo = _request(servidor.bound_port, metodo, caminho,
                                     api_key="segredo123")
            assert status == 503, caminho
            assert _json_body(corpo)["error"] == "auto_update_indisponivel"

    def test_get_estado_com_config_e_alvos(self, srv_auto) -> None:
        servidor, _, _ = srv_auto
        status, corpo = _request(servidor.bound_port, "GET",
                                 "/admin/auto-update", api_key="segredo123")
        data = _json_body(corpo)
        assert status == 200 and data["ok"] is True
        assert data["config"]["janela"] == "02:00-06:00"
        assert data["alvos"][0]["id"] == "modelo-x"
        assert data["estado"][0]["versao_instalada"] == ""
        assert data["desabilitados"] == [] and data["pendentes"] == []
        assert data["metricas"]["ticks"] == 0
        assert data["metricas"]["aplicados"] == 0

    def test_dry_run_mostra_aplicar_sem_executar(self, srv_auto) -> None:
        servidor, _, rag = srv_auto
        status, corpo = _request(servidor.bound_port, "POST",
                                 "/admin/auto-update/dry-run",
                                 api_key="segredo123")
        data = _json_body(corpo)
        assert status == 200 and data["dry_run"] is True
        assert data["decisoes"][0]["alvo"] == "modelo-x"
        assert data["decisoes"][0]["acao"] == "aplicar"   # 03:00: na janela
        assert "atualizacao_disponivel" in data["decisoes"][0]["motivo"]
        assert rag.chamadas == 0                    # não executou nada
        assert _estado_ausente(servidor)            # não persistiu estado
        # o dry-run é contado como dry-run (nunca como ciclo real)
        assert data["metricas"]["ticks_dry_run"] == 1
        assert data["metricas"]["ticks"] == 0
        assert data["metricas"]["aplicados"] == 0

    def test_reset_valida_alvo(self, srv_auto) -> None:
        servidor, svc, _ = srv_auto
        # body sem alvo → 400
        status, corpo = _request(servidor.bound_port, "POST",
                                 "/admin/auto-update/reset",
                                 api_key="segredo123", body={})
        assert status == 400
        assert _json_body(corpo)["error"] == "alvo_obrigatorio"
        # alvo desconhecido → 404
        status, corpo = _request(servidor.bound_port, "POST",
                                 "/admin/auto-update/reset",
                                 api_key="segredo123", body={"alvo": "x"})
        assert status == 404
        assert _json_body(corpo)["error"] == "alvo_inexistente"
        # desligado de verdade → 200 e religa
        estado = {"alvos": {"modelo-x": {
            "id": "modelo-x", "desabilitado": True, "falhas": 3,
            "motivo_desabilitado": "3 falhas seguidas: store cheio"}}}
        svc.estado_path.write_text(json.dumps(estado), encoding="utf-8")
        status, corpo = _request(servidor.bound_port, "POST",
                                 "/admin/auto-update/reset",
                                 api_key="segredo123", body={"alvo": "modelo-x"})
        assert status == 200
        assert _json_body(corpo)["religado"] == "modelo-x"
        assert svc.carregar_estado()["modelo-x"].desabilitado is False

    def test_dashboard_stats_traz_auto_update(self, srv_auto) -> None:
        servidor, svc, _ = srv_auto
        svc.tick()   # ciclo real (na janela): grava versão instalada
        status, corpo = _request(servidor.bound_port, "GET",
                                 "/dashboard/stats", api_key="segredo123")
        data = _json_body(corpo)
        assert status == 200
        au = data["auto_update"]
        assert au["alvos"] == 1 and au["desabilitados"] == 0
        assert au["config"]["janela"] == "02:00-06:00"
        assert au["ultimo_tick"] == AGORA
        # os MESMOS números do /metrics (od_auto_update_*) no Status
        assert au["metricas"]["ticks"] == 1
        assert au["metricas"]["aplicados"] == 1
        assert au["metricas"]["rag_syncs"] == 1

    def test_painel_traz_a_secao(self, srv_auto) -> None:
        servidor, _, _ = srv_auto
        status, corpo = _request(servidor.bound_port, "GET", "/admin",
                                 api_key="segredo123")
        html = corpo.decode()
        assert status == 200
        assert "Auto-update (modelos/conteúdo)" in html
        assert "auDry" in html and "/admin/auto-update/dry-run" in html
        assert "data/auto_update_alvos.json" in html
        assert 'id="au-metricas"' in html and "od_auto_update_" in html


def _estado_ausente(servidor: Any) -> bool:
    """Dry-run não persiste: o serviço do teste não tem estado gravado."""
    svc = servidor.config.auto_update
    return not svc.estado_path.exists()
