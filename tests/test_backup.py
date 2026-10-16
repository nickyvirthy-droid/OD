"""OMEGA DRAKON • TESTS
Módulo: tests/test_backup.py
Descrição: Testes do backup automático (core/backup.py, TODO §3.6 — ordem
           do dono 2026-10-16): configuração por env, nomes/agenda em hora
           LOCAL, plano de conteúdo (com as exclusões de `captures/` e
           `vector_memory/`), retenção 3 diários + 8 semanais, decisão pura
           (antes da hora / já feito hoje / catch-up / disco), executor
           (tar atômico `0600`, determinístico, estado, retenção aplicada),
           falha com aviso no celular (cooldown de 6 h), check não-crítico
           no /health e fiação do launcher (`build_service`).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - core/backup.py
  - tests/test_auto_update.py e tests/test_nomad_tools.py (padrão da casa)
"""

from __future__ import annotations

import os
import stat
import tarfile
from datetime import datetime
from pathlib import Path

import pytest

from core.backup import (
    AGUARDAR,
    ALERTA_FALHA_COOLDOWN_S,
    DIARIOS_PADRAO,
    EXCLUIDOS_PADRAO,
    PULAR,
    RODAR,
    SEMANAIS_PADRAO,
    BackupService,
    ConfigBackup,
    _espaco_livre_padrao,
    agendado_no_dia,
    avaliar,
    build_service,
    calcular_retencao,
    nome_snapshot,
    plano_de_conteudo,
    semana_iso,
    timestamp_do_nome,
)
from observability.health import HealthMonitor


def _epoch(texto: str) -> float:
    """'2026-10-16 03:30' (hora LOCAL) → epoch — determinismo nos testes."""
    return datetime.strptime(texto, "%Y-%m-%d %H:%M").timestamp()


class _Clock:
    """Relógio de parede injetável (a agenda do backup é 03:00 do dono)."""

    def __init__(self, quando: str = "2026-10-16 03:30") -> None:
        self.now = _epoch(quando)

    def __call__(self) -> float:
        return self.now

    def advance(self, segundos: float) -> None:
        self.now += segundos


class _Push:
    """PushService de mentira: só registra o que teria ido ao celular."""

    def __init__(self, levantar: bool = False) -> None:
        self.envios: list[tuple[str, str]] = []
        self.levantar = levantar

    def notify(self, titulo: str, corpo: str, data: dict | None = None) -> None:
        if self.levantar:
            raise RuntimeError("FCM fora")
        self.envios.append((titulo, corpo))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Raiz de repo de mentira com o que o snapshot deve (e não deve) levar."""
    raiz = tmp_path / "repo"
    (raiz / "data" / "captures" / "2026-10-16").mkdir(parents=True)
    (raiz / "data" / "vector_memory").mkdir(parents=True)
    (raiz / "data" / "downloads").mkdir(parents=True)
    (raiz / "data" / "__pycache__").mkdir(parents=True)
    (raiz / ".env").write_text("OD_API_KEY=segredo\n", encoding="utf-8")
    (raiz / "data" / "push_devices.json").write_text(
        '{"token": "x"}', encoding="utf-8"
    )
    (raiz / "data" / "telegram_offset.json").write_text("12345",
                                                        encoding="utf-8")
    (raiz / "data" / "captures" / "2026-10-16" / "foto.jpg").write_bytes(b"foto")
    (raiz / "data" / "vector_memory" / "store.json").write_text(
        "{}", encoding="utf-8"
    )
    (raiz / "data" / "downloads" / "parcial.part").write_bytes(b"meio")
    (raiz / "data" / "__pycache__" / "lixo.pyc").write_bytes(b"x")
    return raiz


def _cfg(tmp_path: Path, **over) -> ConfigBackup:
    base = dict(
        raiz=tmp_path / "auto",
        estado_path=tmp_path / "backup_estado.json",
    )
    base.update(over)
    return ConfigBackup(**base)


def _svc(
    repo: Path,
    tmp_path: Path,
    *,
    clock: _Clock | None = None,
    push=None,
    livre: int | None = 10 ** 12,
    **over,
) -> BackupService:
    cfg = over.pop("cfg", None) or _cfg(tmp_path, **over)
    return BackupService(
        cfg=cfg,
        repo_root=repo,
        push=push,
        clock=clock or _Clock(),
        espaco_livre_fn=(lambda _p: livre) if livre is not None else None,
    )


# ===========================================================================
# Configuração (env OD_BACKUP_*)
# ===========================================================================

class TestConfigBackup:
    def test_defaults_do_dono(self, tmp_path: Path) -> None:
        """Os números da ordem de 16/10: 03:00, 3 diários, 8 semanais."""
        cfg = ConfigBackup.de_env(lambda _n, padrao: padrao)
        assert cfg.habilitado is True
        assert cfg.hora == "03:00"
        assert cfg.diarios == DIARIOS_PADRAO == 3
        assert cfg.semanais == SEMANAIS_PADRAO == 8
        assert cfg.excluidos == EXCLUIDOS_PADRAO
        assert "data/captures" in cfg.excluidos
        assert "data/vector_memory" in cfg.excluidos

    def test_env_sobrescreve_tudo(self) -> None:
        valores = {
            "OD_BACKUP_HORA": "4:15",
            "OD_BACKUP_DIARIOS": "5",
            "OD_BACKUP_SEMANAIS": "2",
            "OD_BACKUP_INTERVALO_MIN": "30",
            "OD_BACKUP_DIR": "backups/outro",
            "OD_BACKUP_ESTADO": "data/outro.json",
            "OD_BACKUP_EXCLUIR": "data/captures, data/3d",
        }
        cfg = ConfigBackup.de_env(lambda nome, padrao: valores.get(nome, padrao))
        assert cfg.hora == "4:15"
        assert cfg.diarios == 5 and cfg.semanais == 2
        assert cfg.intervalo_s == 1800.0
        assert cfg.raiz == Path("backups/outro")
        assert cfg.estado_path == Path("data/outro.json")
        assert cfg.excluidos == ("data/captures", "data/3d")

    def test_hora_invalida_cai_no_default(self) -> None:
        cfg = ConfigBackup.de_env(
            lambda nome, padrao: "25:99" if nome == "OD_BACKUP_HORA" else padrao
        )
        assert cfg.hora == "03:00"

    def test_desligado_e_para_dict(self) -> None:
        cfg = ConfigBackup.de_env(
            lambda nome, padrao: "0" if nome == "OD_BACKUP" else padrao
        )
        assert cfg.habilitado is False
        dados = _cfg(Path("/tmp")).para_dict()
        assert dados["hora"] == "03:00" and dados["diarios"] == 3
        assert dados["semanais"] == 8 and dados["raiz"].endswith("auto")
        assert dados["intervalo_min"] == 15.0


# ===========================================================================
# Nomes e agenda (hora LOCAL)
# ===========================================================================

class TestNomesEAgenda:
    def test_nome_e_timestamp_ida_e_volta(self) -> None:
        quando = _epoch("2026-10-16 03:00")
        nome = nome_snapshot(quando)
        assert nome == "od-2026-10-16_0300.tar.gz"
        assert timestamp_do_nome(nome) == quando

    def test_nome_fora_do_padrao(self) -> None:
        assert timestamp_do_nome("manual-do-dono.tar.gz") is None
        assert timestamp_do_nome("od-2026-10-16_0300.tar.gz.tmp") is None
        # data impossível não vira timestamp
        assert timestamp_do_nome("od-2026-13-45_0300.tar.gz") is None

    def test_agendado_no_dia_e_hora_local(self) -> None:
        agora = _epoch("2026-10-16 01:20")
        agendado = agendado_no_dia(agora, "03:00")
        assert datetime.fromtimestamp(agendado).strftime("%d/%m %H:%M") == \
            "16/10 03:00"
        assert agendado > agora
        # o agendado de ANTES do horário é o de hoje; o de depois também
        depois = _epoch("2026-10-16 22:00")
        assert agendado_no_dia(depois, "03:00") == agendado

    def test_semana_iso(self) -> None:
        # 01/10/2026 (quinta) e 04/10 (domingo) = mesma semana ISO;
        # 05/10 (segunda) já é a semana seguinte.
        assert semana_iso(_epoch("2026-10-01 03:00")) == \
            semana_iso(_epoch("2026-10-04 03:00"))
        assert semana_iso(_epoch("2026-10-05 03:00")) != \
            semana_iso(_epoch("2026-10-04 03:00"))


# ===========================================================================
# Plano de conteúdo (o que entra no tar)
# ===========================================================================

class TestPlanoDeConteudo:
    def test_leva_env_e_data_sem_capturas_e_sem_vetor(self, repo: Path) -> None:
        nomes = [nome for _caminho, nome in plano_de_conteudo(repo)]
        assert ".env" in nomes
        assert "data/push_devices.json" in nomes
        assert "data/telegram_offset.json" in nomes
        # exclusões da ordem do dono: capturas (304 MB) e índice do RAG
        assert not [n for n in nomes if n.startswith("data/captures")]
        assert not [n for n in nomes if n.startswith("data/vector_memory")]

    def test_ignora_lixo_de_build_e_transferencia(self, repo: Path) -> None:
        nomes = [nome for _caminho, nome in plano_de_conteudo(repo)]
        assert "data/__pycache__/lixo.pyc" not in nomes
        assert "data/downloads/parcial.part" not in nomes

    def test_ordenado_e_com_fonte_ausente(self, repo: Path) -> None:
        plano = plano_de_conteudo(repo, fontes=(".env", "data", "nao-existe"))
        nomes = [nome for _caminho, nome in plano]
        assert nomes == sorted(nomes)
        assert not [n for n in nomes if n.startswith("nao-existe")]

    def test_fonte_arquivo_solto(self, repo: Path) -> None:
        plano = plano_de_conteudo(repo, fontes=(".env",))
        assert [nome for _caminho, nome in plano] == [".env"]

    def test_exclusao_customizada(self, repo: Path) -> None:
        plano = plano_de_conteudo(repo, excluidos=("data",))
        assert [nome for _caminho, nome in plano] == [".env"]


# ===========================================================================
# Retenção: 3 diários + 1 por semana ISO
# ===========================================================================

class TestRetencao:
    def _nomes(self, dias: list[str]) -> list[str]:
        return [nome_snapshot(_epoch(f"{dia} 03:00")) for dia in dias]

    def test_tres_diarios_mais_semanais_na_pratica(self) -> None:
        """10 dias seguidos, 3 diários + 2 semanais: fica o topo da lista.

        Semana ISO: 01–04/10 numa semana (representante = 04/10, o mais
        novo dela) e 05–10/10 na seguinte (representante = 10/10, que já
        é diário — a semana corrente não gasta slot extra).
        """
        dias = [f"2026-10-{d:02d}" for d in range(1, 11)]
        retencao = calcular_retencao(self._nomes(dias), diarios=3, semanais=2)
        assert set(retencao.manter) == {
            "od-2026-10-10_0300.tar.gz",
            "od-2026-10-09_0300.tar.gz",
            "od-2026-10-08_0300.tar.gz",
            "od-2026-10-04_0300.tar.gz",
        }
        assert set(retencao.remover) == {
            "od-2026-10-07_0300.tar.gz",
            "od-2026-10-06_0300.tar.gz",
            "od-2026-10-05_0300.tar.gz",
            "od-2026-10-03_0300.tar.gz",
            "od-2026-10-02_0300.tar.gz",
            "od-2026-10-01_0300.tar.gz",
        }

    def test_cada_semana_recente_tem_um_snapshot(self) -> None:
        """8 semanas cobertas: o valor da retenção semanal é ter UM de cada
        semana passada — a mais recente de cada uma."""
        nomes: list[str] = []
        for dia in range(1, 70):  # 10 semanas de dias corridos
            data = datetime(2026, 9, 1).timestamp() + dia * 86400
            nomes.append(nome_snapshot(data))
        retencao = calcular_retencao(nomes, diarios=3, semanais=8)
        assert len(retencao.manter) <= 3 + 8
        semanas = [semana_iso(timestamp_do_nome(n)) for n in retencao.manter]
        distintas = sorted(set(semanas), reverse=True)
        assert len(distintas) == 8  # as 8 semanas mais recentes cobertas
        assert distintas == sorted(
            {semana_iso(timestamp_do_nome(n)) for n in nomes}, reverse=True
        )[:8]
        # a única semana que pode repetir é a corrente (os 3 diários)
        assert semanas.count(distintas[0]) <= 3
        assert nomes[0] in retencao.remover  # o mais velho sai

    def test_defaults_da_casa(self) -> None:
        dias = [f"2026-09-{d:02d}" for d in range(1, 31)]
        nomes = self._nomes(dias) + [
            nome_snapshot(_epoch(f"2026-10-{d:02d} 03:00"))
            for d in range(1, 17)
        ]
        retencao = calcular_retencao(nomes)
        assert len(retencao.manter) <= DIARIOS_PADRAO + SEMANAIS_PADRAO
        assert "od-2026-10-16_0300.tar.gz" in retencao.manter
        assert "od-2026-09-01_0300.tar.gz" in retencao.remover

    def test_nome_estranho_nunca_e_removido(self) -> None:
        nomes = ["manual-do-dono.tar.gz", "od-quebrado.tar.gz"] + \
            self._nomes(["2026-10-01", "2026-10-02"])
        retencao = calcular_retencao(nomes, diarios=1, semanais=0)
        assert "manual-do-dono.tar.gz" not in retencao.remover
        assert "od-quebrado.tar.gz" not in retencao.remover
        assert retencao.manter == ["od-2026-10-02_0300.tar.gz"]

    def test_zero_zero_remove_todos_os_validos(self) -> None:
        retencao = calcular_retencao(
            self._nomes(["2026-10-01", "2026-10-02"]),
            diarios=0, semanais=0,
        )
        assert retencao.manter == [] and len(retencao.remover) == 2

    def test_so_semanais(self) -> None:
        retencao = calcular_retencao(
            self._nomes([f"2026-10-{d:02d}" for d in range(1, 11)]),
            diarios=0, semanais=3,
        )
        # semanas: 01–04/10 (representante 04), 05–10/10 (10); só 2 semanas
        # existem no intervalo — a terceira vaga fica vazia.
        assert retencao.manter == [
            "od-2026-10-10_0300.tar.gz", "od-2026-10-04_0300.tar.gz",
        ]

    def test_mesmo_dia_duplicado(self) -> None:
        nomes = ["od-2026-10-16_0300.tar.gz", "od-2026-10-16_0315.tar.gz",
                 "od-2026-10-15_0300.tar.gz"]
        retencao = calcular_retencao(nomes, diarios=2, semanais=1)
        assert retencao.manter == ["od-2026-10-16_0315.tar.gz",
                                   "od-2026-10-16_0300.tar.gz"]
        assert retencao.remover == ["od-2026-10-15_0300.tar.gz"]


# ===========================================================================
# Decisão pura (avaliar)
# ===========================================================================

class TestAvaliar:
    def test_desligado(self, tmp_path: Path) -> None:
        decisao = avaliar(_cfg(tmp_path, habilitado=False), {},
                          agora_wall=_epoch("2026-10-16 04:00"))
        assert decisao.acao == PULAR and decisao.motivo == "desligado"

    def test_antes_da_hora(self, tmp_path: Path) -> None:
        decisao = avaliar(_cfg(tmp_path), {},
                          agora_wall=_epoch("2026-10-16 02:30"))
        assert decisao.acao == AGUARDAR and decisao.motivo == "antes_da_hora"
        assert decisao.proximo_em_s == pytest.approx(30 * 60.0, abs=1)

    def test_ja_feito_hoje(self, tmp_path: Path) -> None:
        estado = {"ultimo_sucesso": _epoch("2026-10-16 03:00")}
        decisao = avaliar(_cfg(tmp_path), estado,
                          agora_wall=_epoch("2026-10-16 12:00"))
        assert decisao.acao == PULAR and decisao.motivo == "ja_feito_hoje"

    def test_catch_up_de_ontem(self, tmp_path: Path) -> None:
        """Servidor desligado às 03:00: o primeiro tick do dia roda."""
        estado = {"ultimo_sucesso": _epoch("2026-10-15 03:00")}
        decisao = avaliar(_cfg(tmp_path), estado,
                          agora_wall=_epoch("2026-10-16 08:00"))
        assert decisao.acao == RODAR and decisao.motivo == "agendado"

    def test_disco_insuficiente(self, tmp_path: Path) -> None:
        estado = {"ultimo_bytes": 10 * 1024 ** 2}
        decisao = avaliar(
            _cfg(tmp_path), estado, agora_wall=_epoch("2026-10-16 04:00"),
            espaco_livre=5 * 1024 ** 2,
        )
        assert decisao.acao == PULAR
        assert decisao.motivo == "disco_insuficiente"
        assert decisao.precisa_bytes == 10 * 1024 ** 2
        assert decisao.espaco_livre == 5 * 1024 ** 2

    def test_estimativa_usada_quando_nao_ha_medida(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path, estimativa_bytes=1024)
        decisao = avaliar(cfg, {}, agora_wall=_epoch("2026-10-16 04:00"),
                          espaco_livre=2000)
        # 1024 × 1,10 = 1126 > 2000? não — cabe, então roda
        assert decisao.acao == RODAR and decisao.precisa_bytes == 1024
        apertado = avaliar(cfg, {}, agora_wall=_epoch("2026-10-16 04:00"),
                           espaco_livre=1000)
        assert apertado.acao == PULAR

    def test_espaco_livre_none_nao_trava(self, tmp_path: Path) -> None:
        decisao = avaliar(_cfg(tmp_path), {},
                          agora_wall=_epoch("2026-10-16 04:00"))
        assert decisao.acao == RODAR and decisao.espaco_livre is None

    def test_para_dict(self, tmp_path: Path) -> None:
        decisao = avaliar(_cfg(tmp_path), {},
                          agora_wall=_epoch("2026-10-16 04:00"))
        dados = decisao.para_dict()
        assert dados["acao"] == RODAR and "motivo" in dados


# ===========================================================================
# Executor (tar, estado, retenção)
# ===========================================================================

class TestExecutor:
    def test_snapshot_leva_o_que_importa_e_nada_mais(
        self, repo: Path, tmp_path: Path
    ) -> None:
        svc = _svc(repo, tmp_path)
        resultado = svc.rodar_agora()
        assert resultado.ok and resultado.executado
        caminho = svc.cfg.raiz / resultado.arquivo
        assert caminho.exists()
        with tarfile.open(caminho, "r:gz") as tar:
            nomes = tar.getnames()
            assert ".env" in nomes
            assert "data/push_devices.json" in nomes
            assert not [n for n in nomes if n.startswith("data/captures")]
            assert not [n for n in nomes if n.startswith("data/vector_memory")]
            assert "data/__pycache__/lixo.pyc" not in nomes
            extraido = tar.extractfile(".env")
            assert extraido is not None
            assert extraido.read() == b"OD_API_KEY=segredo\n"
        assert resultado.membros == len([n for n in nomes])
        assert resultado.bytes == caminho.stat().st_size > 0
        assert resultado.sha256 == BackupService._sha256(caminho)

    def test_arquivo_e_diretorio_protegidos(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """O tar leva o .env: 0600 no arquivo, 0700 no diretório."""
        svc = _svc(repo, tmp_path)
        resultado = svc.rodar_agora()
        modo_dir = stat.S_IMODE(svc.cfg.raiz.stat().st_mode)
        modo_arq = stat.S_IMODE(
            (svc.cfg.raiz / resultado.arquivo).stat().st_mode
        )
        if os.name == "posix":
            assert modo_dir == 0o700
            assert modo_arq == 0o600

    def test_estado_gravado_e_sem_temporario(
        self, repo: Path, tmp_path: Path
    ) -> None:
        svc = _svc(repo, tmp_path)
        resultado = svc.rodar_agora()
        estado = svc.carregar_estado()
        assert estado["ultimo_arquivo"] == resultado.arquivo
        assert estado["ultimo_bytes"] == resultado.bytes
        assert estado["ultimo_sha256"] == resultado.sha256
        assert estado["rodadas"] == 1 and estado["falhas"] == 0
        assert estado["ultimo_erro"] == ""
        assert estado["membros"] == resultado.membros
        assert not list(svc.cfg.raiz.glob("*.tmp"))

    def test_conteudo_igual_gera_mesmo_sha(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """Contêiner determinístico: gzip mtime 0 + membros ordenados."""
        clock = _Clock()
        svc = _svc(repo, tmp_path, clock=clock)
        primeiro = svc.rodar_agora()
        clock.advance(60)
        segundo = svc.rodar_agora()
        assert primeiro.arquivo != segundo.arquivo  # nome carrega a hora
        assert primeiro.sha256 == segundo.sha256

    def test_retencao_aplicada_no_ciclo(
        self, repo: Path, tmp_path: Path
    ) -> None:
        svc = _svc(repo, tmp_path, diarios=2, semanais=0)
        svc.cfg.raiz.mkdir(parents=True, exist_ok=True)
        antigos = [
            nome_snapshot(_epoch(f"2026-10-{d:02d} 03:00"))
            for d in (10, 11, 12)
        ]
        for nome in antigos:
            (svc.cfg.raiz / nome).write_bytes(b"antigo")
        resultado = svc.rodar_agora()
        restantes = sorted(p.name for p in svc.cfg.raiz.iterdir())
        assert resultado.arquivo in restantes
        assert len(restantes) == 2
        assert not (svc.cfg.raiz / antigos[0]).exists()
        assert resultado.removidos

    def test_lista_e_snapshot(self, repo: Path, tmp_path: Path) -> None:
        clock = _Clock()
        svc = _svc(repo, tmp_path, clock=clock)
        assert svc.lista() == []
        antes = svc.snapshot()
        assert antes["pendente_hoje"] is True
        assert antes["arquivos"] == [] and antes["ultimo_arquivo"] == ""
        svc.rodar_agora()
        depois = svc.snapshot()
        assert depois["pendente_hoje"] is False
        assert len(depois["arquivos"]) == 1
        item = depois["arquivos"][0]
        assert item["arquivo"] == depois["ultimo_arquivo"]
        assert item["bytes"] == depois["ultimo_bytes"] > 0
        assert depois["rodadas"] == 1

    def test_lista_ignora_arquivo_estranho(
        self, repo: Path, tmp_path: Path
    ) -> None:
        svc = _svc(repo, tmp_path)
        svc.cfg.raiz.mkdir(parents=True, exist_ok=True)
        (svc.cfg.raiz / "leia-me.txt").write_text("do dono", encoding="utf-8")
        (svc.cfg.raiz / "subdir").mkdir()  # diretório não é snapshot
        assert svc.lista() == []

    def test_lista_sem_diretorio(self, repo: Path, tmp_path: Path) -> None:
        svc = _svc(repo, tmp_path)
        assert not svc.cfg.raiz.exists()
        assert svc.lista() == []

    def test_temporario_orfao_e_limpo(self, repo: Path, tmp_path: Path) -> None:
        """Rodada que morreu no meio deixou `.tmp`: a próxima limpa."""
        svc = _svc(repo, tmp_path)
        svc.cfg.raiz.mkdir(parents=True, exist_ok=True)
        orfao = svc.cfg.raiz / "od-2026-10-01_0300.tar.gz.tmp"
        orfao.write_bytes(b"incompleto")
        resultado = svc.rodar_agora()
        assert resultado.ok and not orfao.exists()
        assert not list(svc.cfg.raiz.glob("*.tmp"))

    def test_estado_nao_gravavel_nao_quebra(
        self, repo: Path, tmp_path: Path, monkeypatch
    ) -> None:
        svc = _svc(repo, tmp_path)

        def _sem_permissao(*_args, **_kwargs):
            raise OSError("read-only file system")

        monkeypatch.setattr(Path, "write_text", _sem_permissao)
        svc.gravar_estado({"rodadas": 1})  # não levanta

    def test_para_dict_dos_dataclasses(self, tmp_path: Path) -> None:
        from core.backup import Retencao, ResultadoBackup

        retencao = Retencao(manter=["a"], remover=["b"])
        assert retencao.para_dict() == {
            "manter": ["a"], "remover": ["b"], "total_apos": 1
        }
        resultado = ResultadoBackup(acao=RODAR, motivo="agendado",
                                    executado=True, arquivo="x.tar.gz")
        dados = resultado.para_dict()
        assert dados["ok"] is True and dados["arquivo"] == "x.tar.gz"
        assert dados["bytes"] == 0 and dados["sha256"] == ""


# ===========================================================================
# Ciclo (tick) e agendamento
# ===========================================================================

class TestCiclo:
    def test_tick_antes_da_hora_nao_executa(
        self, repo: Path, tmp_path: Path
    ) -> None:
        svc = _svc(repo, tmp_path, clock=_Clock("2026-10-16 01:00"))
        resultado = svc.tick()
        assert resultado.executado is False and resultado.acao == AGUARDAR
        assert svc.carregar_estado() == {}

    def test_tick_no_horario_executa_e_nao_repete(
        self, repo: Path, tmp_path: Path
    ) -> None:
        clock = _Clock("2026-10-16 03:30")
        svc = _svc(repo, tmp_path, clock=clock)
        primeiro = svc.tick()
        assert primeiro.executado is True and primeiro.motivo == "agendado"
        clock.advance(3600)
        segundo = svc.tick()
        assert segundo.executado is False
        assert segundo.acao == PULAR and segundo.motivo == "ja_feito_hoje"

    def test_dia_seguinte_roda_de_novo(
        self, repo: Path, tmp_path: Path
    ) -> None:
        clock = _Clock("2026-10-16 03:30")
        svc = _svc(repo, tmp_path, clock=clock)
        primeiro = svc.rodar_agora()
        clock.now = _epoch("2026-10-17 03:05")
        segundo = svc.tick()
        assert segundo.executado and segundo.arquivo != primeiro.arquivo

    def test_rodar_agora_ignora_a_agenda(
        self, repo: Path, tmp_path: Path
    ) -> None:
        svc = _svc(repo, tmp_path, clock=_Clock("2026-10-16 01:00"))
        resultado = svc.rodar_agora()
        assert resultado.executado and resultado.motivo == "manual"

    def test_disco_cheio_nao_executa(
        self, repo: Path, tmp_path: Path
    ) -> None:
        svc = _svc(repo, tmp_path, clock=_Clock("2026-10-16 03:30"), livre=10)
        resultado = svc.tick()
        assert resultado.executado is False
        assert resultado.motivo == "disco_insuficiente"
        assert not svc.cfg.raiz.exists() or not list(svc.cfg.raiz.iterdir())

    def test_no_disco_real_estima_espaco(self, tmp_path: Path) -> None:
        # caminho inexistente sobe até um ancestral real e devolve > 0
        livre = _espaco_livre_padrao(tmp_path / "nao" / "existe" / "auto")
        assert livre is None or livre > 0


# ===========================================================================
# Falha: estado honesto + aviso no celular (com cooldown)
# ===========================================================================

class TestFalhas:
    @staticmethod
    def _quebrar(monkeypatch) -> None:
        def _explode(self, plano, destino_tmp):  # noqa: ANN001, ARG001
            raise OSError("disco cheio")

        monkeypatch.setattr(BackupService, "_empacotar", _explode)

    def test_falha_grava_estado_e_avisa_uma_vez(
        self, repo: Path, tmp_path: Path, monkeypatch
    ) -> None:
        self._quebrar(monkeypatch)
        push = _Push()
        clock = _Clock("2026-10-16 03:30")
        svc = _svc(repo, tmp_path, clock=clock, push=push)
        resultado = svc.tick()
        assert resultado.executado and not resultado.ok
        assert "disco cheio" in resultado.erro
        estado = svc.carregar_estado()
        assert estado["falhas"] == 1
        assert "disco cheio" in estado["ultimo_erro"]
        assert "ultimo_sucesso" not in estado
        assert len(push.envios) == 1
        titulo, corpo = push.envios[0]
        assert titulo == "Backup falhou" and "disco cheio" in corpo
        # segunda falha minutos depois: cooldown de 6 h segura o aviso
        clock.advance(600)
        svc.tick(forcar=True)
        assert len(push.envios) == 1
        assert svc.carregar_estado()["falhas"] == 2
        # passado o cooldown, avisa de novo
        clock.advance(ALERTA_FALHA_COOLDOWN_S)
        svc.tick(forcar=True)
        assert len(push.envios) == 2

    def test_sem_push_nao_quebra(
        self, repo: Path, tmp_path: Path, monkeypatch
    ) -> None:
        self._quebrar(monkeypatch)
        svc = _svc(repo, tmp_path)
        assert svc.tick().erro != ""

    def test_push_que_levanta_nao_derruba_o_ciclo(
        self, repo: Path, tmp_path: Path, monkeypatch
    ) -> None:
        self._quebrar(monkeypatch)
        svc = _svc(repo, tmp_path, push=_Push(levantar=True))
        resultado = svc.tick()
        assert resultado.executado is True  # o ciclo terminou honesto
        assert svc.carregar_estado()["falhas"] == 1

    def test_sucesso_zera_falhas(
        self, repo: Path, tmp_path: Path, monkeypatch
    ) -> None:
        self._quebrar(monkeypatch)
        svc = _svc(repo, tmp_path)
        assert not svc.tick().ok
        monkeypatch.undo()  # sonda volta ao normal
        assert svc.rodar_agora().ok
        estado = svc.carregar_estado()
        assert estado["falhas"] == 0 and estado["ultimo_erro"] == ""
        assert estado["ultimo_sucesso"] > 0

    def test_estado_corrompido_e_ignorado(
        self, repo: Path, tmp_path: Path
    ) -> None:
        svc = _svc(repo, tmp_path)
        svc.cfg.estado_path.parent.mkdir(parents=True, exist_ok=True)
        svc.cfg.estado_path.write_text("{quebrado", encoding="utf-8")
        assert svc.carregar_estado() == {}
        assert svc.snapshot()["falhas"] == 0


# ===========================================================================
# /health (check não-crítico) e /dashboard/stats
# ===========================================================================

class TestSaude:
    def test_antes_da_hora_o_check_esta_ok(
        self, repo: Path, tmp_path: Path
    ) -> None:
        svc = _svc(repo, tmp_path, clock=_Clock("2026-10-16 02:00"))
        check = svc.check_saude()
        assert check["ok"] is True and "03:00" in check["detail"]

    def test_depois_da_hora_sem_snapshot_degrada(
        self, repo: Path, tmp_path: Path
    ) -> None:
        svc = _svc(repo, tmp_path, clock=_Clock("2026-10-16 04:00"))
        check = svc.check_saude()
        assert check["ok"] is False and check["status"] == "degraded"
        assert "PENDENTE" in check["detail"]

    def test_com_snapshot_do_dia_volta_a_ok(
        self, repo: Path, tmp_path: Path
    ) -> None:
        clock = _Clock("2026-10-16 03:30")
        svc = _svc(repo, tmp_path, clock=clock)
        resultado = svc.rodar_agora()
        check = svc.check_saude()
        assert check["ok"] is True and check["status"] == "up"
        assert resultado.arquivo in check["detail"]

    def test_falha_do_dia_aparece_no_detalhe(
        self, repo: Path, tmp_path: Path, monkeypatch
    ) -> None:
        TestFalhas._quebrar(monkeypatch)
        svc = _svc(repo, tmp_path, clock=_Clock("2026-10-16 04:00"))
        svc.tick()
        check = svc.check_saude()
        assert check["ok"] is False and "disco cheio" in check["detail"]
        assert "falhas=1" in check["detail"]

    @pytest.mark.asyncio
    async def test_registro_nao_critico_no_monitor(
        self, repo: Path, tmp_path: Path
    ) -> None:
        svc = _svc(repo, tmp_path, clock=_Clock("2026-10-16 04:00"))
        monitor = HealthMonitor()
        assert svc.registrar_no_health(monitor) == "backup"
        assert monitor.components == ["backup"]
        agregado = await monitor.health()
        # não-crítico: pendência DEGRADA o /health, não derruba (down)
        assert agregado["status"] == "degraded"
        assert agregado["checks"]["backup"]["ok"] is False
        assert agregado["checks"]["backup"]["critical"] is False

    def test_registrar_sem_monitor(self, repo: Path, tmp_path: Path) -> None:
        assert _svc(repo, tmp_path).registrar_no_health(None) is None


# ===========================================================================
# Fiação do launcher
# ===========================================================================

class TestFiacao:
    def test_build_service_respeita_o_env(self, repo: Path, tmp_path: Path) -> None:
        svc = build_service(
            repo_root=repo,
            env=lambda nome, padrao: {
                "OD_BACKUP_DIR": str(tmp_path / "auto"),
                "OD_BACKUP_ESTADO": str(tmp_path / "estado.json"),
                "OD_BACKUP_DIARIOS": "1",
            }.get(nome, padrao),
        )
        assert svc is not None
        assert svc.cfg.diarios == 1 and svc.cfg.hora == "03:00"

    def test_build_service_desligado(self, repo: Path) -> None:
        svc = build_service(
            repo_root=repo,
            env=lambda nome, padrao: "0" if nome == "OD_BACKUP" else padrao,
        )
        assert svc is None


# ---------------------------------------------------------------------------
# API — bloco backup no /dashboard/stats e card no /admin
# ---------------------------------------------------------------------------

@pytest.fixture()
def _serve_stats():
    """Sobe APIServer sob demanda (mesmo padrão do test_notifier.py)."""
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


class TestStatsDoBackup:
    """O dono vê no Status (e no card "Backup" do /admin) quando foi o
    último snapshot, quanto ocupou e se o de HOJE está pendente — sem
    abrir o journal. None (OD_BACKUP=0) = bloco ausente."""

    def test_sem_backup_o_bloco_nao_aparece(self, _serve_stats,
                                            tmp_path: Path) -> None:
        from tests.test_api import _json_response, _request, make_orch

        srv = _serve_stats(make_orch(tmp_path))
        resposta = _request(srv.bound_port, "GET", "/dashboard/stats")
        dados = _json_response(resposta)
        assert resposta[0] == 200
        assert "backup" not in dados
        assert b'"backup"' not in resposta[1]

    def test_com_backup_traz_o_estado_e_o_card(self, _serve_stats,
                                               repo: Path,
                                               tmp_path: Path) -> None:
        from tests.test_api import _json_response, _request, make_orch
        from integrations.api import APIConfig

        svc = _svc(repo, tmp_path, clock=_Clock("2026-10-16 03:30"))
        svc.rodar_agora()
        cfg = APIConfig(port=0, rate_limit_max=0, backup=svc)
        srv = _serve_stats(make_orch(tmp_path), config=cfg)
        resposta = _request(srv.bound_port, "GET", "/dashboard/stats")
        status, body, _headers = resposta
        dados = _json_response(resposta)
        assert status == 200 and b'"backup"' in body
        assert dados["backup"]["ultimo_arquivo"].startswith("od-2026-10-16")
        assert dados["backup"]["config"]["hora"] == "03:00"
        assert dados["backup"]["arquivos"][0]["bytes"] > 0
        assert dados["backup"]["pendente_hoje"] is False
        # card "Backup" do painel — a linha referencia stats.backup
        status, corpo_admin, _ = _request(srv.bound_port, "GET", "/admin")
        assert status == 200
        assert b"stats.backup" in corpo_admin
        assert b"fmtBytes" in corpo_admin
