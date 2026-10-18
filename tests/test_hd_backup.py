"""OMEGA DRAKON • TESTES
Módulo: tests/test_hd_backup.py
Descrição: Testes do snapshot de HD externo (core/hd_backup.py — pendência
           "2 snapshots p/ HD externo", ordem do dono 2026-10-16, HDs com
           fstab unificado 2026-10-17): parse/rotulagem dos alvos, fiação
           do build (fonte do 3D PRIMEIRO — linha vermelha do TODO),
           decisão pura com a camada nova `alvo_ausente` (nofail: pasta
           montável sem disco), executor rsync REAL (estrutura -R,
           exclusões, SQLite pelo backup API, publicação atômica),
           dedup por hardlink na 2ª rodada (mudou ≠ escreveu por cima;
           removido da fonte ausente no snapshot novo e intacto no
           antigo), retenção que não toca nome fora do padrão, check
           honesto (HD desconectada degrada, nunca verde de mentira),
           falha grita com cooldown de 6 h e fiação do launcher.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - core/hd_backup.py, core/backup.py (padrão espelhado)
  - tests/test_backup.py (padrão da casa)
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import pytest

from core import hd_backup
from core.backup import (
    AGUARDAR,
    PULAR,
    RODAR,
    calcular_retencao,
    timestamp_do_nome,
)
from core.hd_backup import (
    ConfigHD,
    HDBackupService,
    avaliar,
    build_hd_services,
    fontes_do_sistema,
    fontes_excluidas,
    nome_dir,
    parse_alvos,
)
from observability.health import HealthMonitor


def _epoch(texto: str) -> float:
    """'2026-10-16 03:40' (hora LOCAL) → epoch — determinismo nos testes."""
    return datetime.strptime(texto, "%Y-%m-%d %H:%M").timestamp()


class _Clock:
    """Relógio de parede injetável (mesmo desenho do test_backup.py)."""

    def __init__(self, inicial: float) -> None:
        self.t = inicial

    def __call__(self) -> float:
        return self.t

    def avancar(self, segundos: float) -> None:
        self.t += segundos


class _Push:
    """Push falso que só conta chamadas — a falha tem que gritar."""

    def __init__(self) -> None:
        self.chamadas: list[tuple[str, str]] = []

    def notify(self, title: str, body: str,
               data: dict | None = None) -> dict:
        self.chamadas.append((title, body))
        return {"ok": True}


def _env_de(valores: dict[str, str]):
    return lambda nome, padrao: valores.get(nome, padrao)


# ---------------------------------------------------------------------------
# Árvore de teste: fontes, HD falsa e banco SQLite volátil
# ---------------------------------------------------------------------------


class _Arvore:
    """Tudo que o executor precisa, criado em tmp_path.

    `monkeypatch` aponta `DB_FONTES` para o banco de testes — sem isso a
    execução cópia o homebox.db de produção.
    """

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.raiz = tmp_path
        self.fonte_3d = tmp_path / "3D"
        self.fonte_repo = tmp_path / "repo"
        self.alvo = tmp_path / "hd_midiAS"
        self.fstab = tmp_path / "fstab.txt"
        self.db = tmp_path / "homebox.db"
        monkeypatch.setattr(hd_backup, "DB_FONTES", (str(self.db),))

        (self.fonte_3d).mkdir()
        (self.fonte_3d / "dragao.stl").write_text("STL-PAGO", encoding="utf-8")
        for rel, valor in (
            (".env", "OD_VERSION=1.39.3\n"),
            (".venv/lib.py", "v"),
            (Path("backups") / "od-antigo.tar.gz", "t"),
            (Path("data") / "vector_memory" / "idx.bin", "i"),
            (Path("data") / "captures" / "foto.jpg", "JPEG"),
            (Path("__pycache__") / "m.pyc", "p"),
            ("solta.pyc", "p"),
            ("codigo.py", "# v1"),
            # >1000 bytes: payload de verdade p/ pegar separador de
            # milhar do locale no --stats (o "8 bytes" escondeu o bug)
            ("peso.bin", "x" * 5000),
        ):
            caminho = self.fonte_repo / rel
            caminho.parent.mkdir(parents=True, exist_ok=True)
            caminho.write_text(valor, encoding="utf-8")
        self.fstab.write_text(
            "UUID=f2c8 /home/alex/dados ext4 defaults,noatime,nofail 0 2\n",
            encoding="utf-8",
        )
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE itens (nome TEXT)")
        con.commit()
        con.close()
        self.alvo.mkdir()

    @property
    def fontes(self) -> tuple[str, ...]:
        return (str(self.fonte_3d), str(self.fonte_repo), str(self.fstab))

    def cfg(self, **campos) -> ConfigHD:
        base = dict(
            nome="hd_midias",
            rotulo="Snapshot HD Mídias",
            check_nome="hd_midias",
            fontes=self.fontes,
            excluidos=fontes_excluidas(self.fonte_repo),
            raiz=Path("od_snapshots"),
            estado_path=self.raiz / "estado_hd.json",
            alvo=str(self.alvo),
            hora="03:40",
            versao="1.39.3-teste",
        )
        base.update(campos)
        return ConfigHD(**base)

    def svc(self, cfg: ConfigHD | None = None, *, relogio: _Clock | None = None,
            montado: bool = True, espaco: int = 10 ** 15,
            push=None, rsync: str = "rsync") -> HDBackupService:
        return HDBackupService(
            cfg=cfg or self.cfg(),
            clock=relogio or _Clock(_epoch("2026-10-17 04:00")),
            push=push,
            espaco_livre_fn=lambda _p: espaco,
            montado_fn=lambda _p: montado,
            rsync_bin=rsync,
        )

    def snap(self, nome: str) -> Path:
        return self.alvo / "od_snapshots" / nome

    @staticmethod
    def em(snapshot: Path, fonte: Path, *sub: str) -> Path:
        """Caminho DENTRO do snapshot (rsync -R preserva a árvore cheia)."""
        return snapshot / str(fonte).lstrip("/") / Path(*sub) if sub else \
            snapshot / str(fonte).lstrip("/")


# ---------------------------------------------------------------------------
# Alvos, nomes e fiação do build
# ---------------------------------------------------------------------------


class TestAlvosENomes:
    """`Rótulo=/caminho` por vírgula + o nome canônico de diretório."""

    def test_parse_alvos_preserva_ordem_e_ignora_lixo(self) -> None:
        texto = "Mídias=/home/alex/dados, Bananas,Arquivos=/mnt/Arquivos,  ,X="
        assert parse_alvos(texto) == [
            ("Mídias", "/home/alex/dados"),
            ("Arquivos", "/mnt/Arquivos"),
        ]

    def test_build_padrao_sao_as_duas_hd_do_dono(self) -> None:
        servicos = build_hd_services(repo_root=Path("/repo"),
                                     env=_env_de({}))
        assert [s.cfg.nome for s in servicos] == ["hd_midias", "hd_arquivos"]
        assert [s.cfg.check_nome for s in servicos] == [
            "hd_midias", "hd_arquivos",
        ]
        assert servicos[0].cfg.alvo == "/home/alex/dados"
        assert servicos[1].cfg.alvo == "/mnt/Arquivos"
        assert servicos[0].cfg.rotulo == "Snapshot HD Mídias"
        # a lacuna que o deploy de 17/10 expôs: as FONTES têm que viajar
        # do build pro cfg (de_env sem `fontes=` = "nenhuma fonte existe"
        # em produção, com todos os discos no lugar)
        assert servicos[0].cfg.fontes == fontes_do_sistema(Path("/repo"))
        assert servicos[0].cfg.fontes[0] == "/home/alex/3D"

    def test_master_switch_desliga_tudo(self) -> None:
        assert build_hd_services(
            repo_root=Path("/repo"),
            env=_env_de({"OD_HD_SNAPSHOT": "0"}),
        ) == []

    def test_knobs_do_env_e_hora_invalida_cai_no_default(self) -> None:
        servicos = build_hd_services(
            repo_root=Path("/repo"),
            env=_env_de({
                "OD_HD_HORA": "99:99",
                "OD_HD_DIARIOS": "2",
                "OD_HD_INTERVALO_MIN": "7.5",
                "OD_HD_ALVOS": "Banco=/mnt/Banco",
                "OD_HD_EXCLUIR": "pasta_ruim, /outra/",
            }),
        )
        assert len(servicos) == 1
        cfg = servicos[0].cfg
        assert cfg.hora == "03:40"
        assert cfg.diarios == 2
        assert cfg.intervalo_s == 7.5 * 60.0
        assert cfg.nome == "hd_banco"
        assert cfg.excluidos == ("pasta_ruim", "outra")

    def test_fonte_do_3d_e_a_primeira_lista(self) -> None:
        """Linha vermelha do TODO: o 3D do dono entra em TODO snapshot —
        e a primeira da lista é a garantia contratual disso."""
        fontes = fontes_do_sistema(Path("/repo"))
        assert fontes[0] == "/home/alex/3D"
        assert "/home/alex/omegadrakon-tools" in fontes
        assert "/srv/omegadrakon" in fontes and "/etc/fstab" in fontes
        assert str(Path("/repo")) in fontes

    def test_exclusoes_declaradas_com_motivo(self) -> None:
        excluidos = fontes_excluidas(Path("/repo"))
        assert "/repo/.venv" in excluidos
        assert "/repo/backups" in excluidos
        assert "/repo/data/vector_memory" in excluidos
        assert any("zim" in item for item in excluidos)
        assert any("heap_dumps" in item for item in excluidos)
        assert "__pycache__" in excluidos

    def test_nome_de_dir_só_casa_com_sufixo_vazio(self) -> None:
        """O reuso do `timestamp_do_nome` com sufixo vazio é a regra de
        retenção: `.tar.gz` não casa (mundo tar intocado) e o dir casa."""
        quando = _epoch("2026-10-17 03:40")
        nome = nome_dir(quando, "snapshot_od")
        assert nome == "snapshot_od-2026-10-17_0340"
        assert timestamp_do_nome(nome, "snapshot_od") is None
        assert timestamp_do_nome(nome, "snapshot_od", "") == pytest.approx(
            quando, abs=60
        )
        assert timestamp_do_nome("od-2026-10-17_0300.tar.gz", "od") is not None


# ---------------------------------------------------------------------------
# Decisão pura — as 6 camadas, sem tocar em disco nenhum
# ---------------------------------------------------------------------------


class TestDecisaoPura:
    """`avaliar()` recebe montagem e espaço por parâmetro: os caminhos dos
    casos abaixo NÃO EXISTEM e mesmo assim decidem — prova de pureza."""

    def _avaliar(self, tmp_path: Path, *, estado=None, agora: str,
                 montado: bool, espaco: int | None,
                 habilitado: bool = True):
        cfg = ConfigHD(
            alvo=str(tmp_path / "nao" / "existe"),
            estado_path=tmp_path / "estado_hd.json",
            hora="03:40",
            habilitado=habilitado,
        )
        return avaliar(
            cfg,
            estado or {},
            agora_wall=_epoch(agora),
            montado=montado,
            espaco_livre=espaco,
        )

    def test_desligado(self, tmp_path: Path) -> None:
        d = self._avaliar(tmp_path, agora="2026-10-17 10:00",
                          montado=True, espaco=None, habilitado=False)
        assert (d.acao, d.motivo) == (PULAR, "desligado")

    def test_antes_da_hora(self, tmp_path: Path) -> None:
        d = self._avaliar(tmp_path, agora="2026-10-17 02:00",
                          montado=True, espaco=None)
        assert d.acao == AGUARDAR and d.motivo == "antes_da_hora"
        assert d.proximo_em_s == pytest.approx(100 * 60)

    def test_ja_feito_hoje(self, tmp_path: Path) -> None:
        d = self._avaliar(
            tmp_path,
            estado={"ultimo_sucesso": _epoch("2026-10-17 03:41")},
            agora="2026-10-17 10:00", montado=True, espaco=None,
        )
        assert d.acao == AGUARDAR and d.motivo == "ja_feito"

    def test_catch_up_de_quem_estava_desligado(self, tmp_path: Path) -> None:
        """Servidor off no 03:40 ⇒ janela de hoje já passou ⇒ RODAR."""
        d = self._avaliar(tmp_path, agora="2026-10-17 10:00",
                          montado=True, espaco=10 ** 15)
        assert d.acao == RODAR and d.motivo == "agendado"

    def test_alvo_ausente_antes_do_disco(self, tmp_path: Path) -> None:
        """HD desplugada (fstab nofail): pula honesto, sem olhar espaço."""
        d = self._avaliar(tmp_path, agora="2026-10-17 10:00",
                          montado=False, espaco=10)
        assert (d.acao, d.motivo) == (PULAR, "alvo_ausente")
        assert d.espaco_livre == 10

    def test_disco_insuficiente_com_margem(self, tmp_path: Path) -> None:
        cfg = ConfigHD(alvo=str(tmp_path / "nao" / "existe"),
                       hora="03:40", estimativa_bytes=1000)
        d = avaliar(cfg, {}, agora_wall=_epoch("2026-10-17 10:00"),
                    montado=True, espaco_livre=1050)
        assert (d.acao, d.motivo) == (PULAR, "disco_insuficiente")
        d_ok = avaliar(cfg, {}, agora_wall=_epoch("2026-10-17 10:00"),
                       montado=True, espaco_livre=1100)
        assert d_ok.acao == RODAR  # 1000 × 1,10 de margem

    def test_usa_bytes_medido_quando_ja_rodou(self, tmp_path: Path) -> None:
        cfg = ConfigHD(alvo=str(tmp_path / "nao" / "existe"),
                       hora="03:40", estimativa_bytes=1000)
        estado = {"ultimo_bytes": 5000}
        d = avaliar(cfg, estado, agora_wall=_epoch("2026-10-17 10:00"),
                    montado=True, espaco_livre=5000)
        assert d.precisa_bytes == 5000  # medição real manda, não a default


# ---------------------------------------------------------------------------
# Executor — rsync de verdade em árvore de verdade
# ---------------------------------------------------------------------------


class TestExecutor:
    def test_primeira_rodada_copia_tudo_e_exclui_o_declarado(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        arv = _Arvore(tmp_path, monkeypatch)
        svc = arv.svc()
        res = svc.rodar_agora()
        assert res.ok and res.executado
        snap = arv.snap(res.arquivo)
        assert snap.is_dir()
        # -R preserva a árvore absoluta (restore sem adivinhação)
        assert arv.em(snap, arv.fonte_3d, "dragao.stl").read_text() == "STL-PAGO"
        assert arv.em(snap, arv.fonte_repo, ".env").read_text().startswith(
            "OD_VERSION"
        )
        # linha vermelha: o 3D está lá
        assert arv.em(snap, arv.fonte_3d).is_dir()
        # o alvo do HD: as capturas VIAJAM (a semana não depende mais do
        # tar de quarta)
        assert arv.em(snap, arv.fonte_repo, "data", "captures",
                      "foto.jpg").exists()
        # exclusões
        assert not arv.em(snap, arv.fonte_repo, ".venv").exists()
        assert not arv.em(snap, arv.fonte_repo, "backups").exists()
        assert not arv.em(snap, arv.fonte_repo, "data",
                          "vector_memory").exists()
        assert not arv.em(snap, arv.fonte_repo, "__pycache__").exists()
        assert not arv.em(snap, arv.fonte_repo, "solta.pyc").exists()
        # fonte arquivo único (fstab) copiada como arquivo
        assert arv.em(snap, arv.fstab).is_file()
        # info.json: o que é, quando, de onde
        info = json.loads((snap / "info.json").read_text(encoding="utf-8"))
        assert info["bytes"] > 0
        # >= 5000 (peso.bin): regex de locale quebrada = "5" e reprova
        assert info["bytes_transferidos"] >= 5000
        assert info["od_version"] == "1.39.3-teste"
        assert info["alvo"] == str(arv.alvo)
        assert not list((arv.alvo / "od_snapshots").glob(".tmp_*"))
        # estado persistido atômico
        estado = json.loads(arv.cfg().estado_path.read_text(encoding="utf-8"))
        assert estado["rodadas"] == 1 and estado["falhas"] == 0
        assert estado["ultimo_arquivo"] == res.arquivo
        # ultimo_bytes = tamanho do ARTEFATO (guarda de disco + card);
        # "movidos na rodada" é outro número (info bytes_transferidos)
        assert estado["ultimo_bytes"] == info["bytes"]
        assert estado["ultimo_bytes"] >= 5000

    def test_banco_sqlite_copiado_no_ponto_consistente(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Insert SEM commit antes do snapshot ⇒ snapshot sem a linha e
        SEM wal/shm; depois do commit a fonte tem a linha e o snapshot
        continua no ponto antigo (cópia rasgada é restore que não abre)."""
        arv = _Arvore(tmp_path, monkeypatch)
        svc = arv.svc()
        escritor = sqlite3.connect(arv.db)
        escritor.execute("INSERT INTO itens VALUES ('pendente')")
        res = svc.rodar_agora()
        assert res.ok
        db_snap = arv.em(arv.snap(res.arquivo), arv.db)
        assert db_snap.is_file()
        assert not db_snap.with_name(db_snap.name + "-wal").exists()
        assert not db_snap.with_name(db_snap.name + "-shm").exists()
        con = sqlite3.connect(db_snap)
        assert con.execute("SELECT count(*) FROM itens").fetchone()[0] == 0
        con.close()
        escritor.commit()
        escritor.close()
        con = sqlite3.connect(str(arv.db))
        assert con.execute("SELECT count(*) FROM itens").fetchone()[0] == 1
        con.close()

    def test_segunda_rodada_hardlink_dedup_e_fonte_editada(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        arv = _Arvore(tmp_path, monkeypatch)
        relogio = _Clock(_epoch("2026-10-17 04:00"))
        svc = arv.svc(relogio=relogio)
        res1 = svc.rodar_agora()
        snap1 = arv.snap(res1.arquivo)

        (arv.fonte_repo / "codigo.py").write_text(
            "# v2 editado", encoding="utf-8",
        )  # tamanho DIFERENTE de propósito: o quick-check do rsync é
        # size + mtime com janela de 1 s (padrão dele, idêntico ao make) —
        # reescrita de mesmo tamanho no mesmo segundo de uma re-rodada
        # imediata não re-copia, e isso é comportamento querido, não bug.
        (arv.fonte_repo / "data" / "captures" / "foto.jpg").unlink()
        relogio.avancar(24 * 3600)  # dia seguinte ⇒ nome novo
        res2 = svc.rodar_agora()
        snap2 = arv.snap(res2.arquivo)
        assert snap2 != snap1

        # inalterado ⇒ MESMO inode (hardlink: não duplica espaço na HD)
        alvo1 = arv.em(snap1, arv.fonte_3d, "dragao.stl")
        alvo2 = arv.em(snap2, arv.fonte_3d, "dragao.stl")
        assert alvo1.stat().st_ino == alvo2.stat().st_ino
        # mudou ⇒ snapshot novo com valor novo, snapshot VELHO INTACTO
        # (o rsync nunca escreve por cima do hardlink herdado)
        assert arv.em(snap2, arv.fonte_repo,
                      "codigo.py").read_text() == "# v2 editado"
        assert arv.em(snap1, arv.fonte_repo,
                      "codigo.py").read_text() == "# v1"
        # removido da fonte ⇒ ausente no novo, presente no antigo
        assert not arv.em(snap2, arv.fonte_repo, "data", "captures",
                          "foto.jpg").exists()
        assert arv.em(snap1, arv.fonte_repo, "data", "captures",
                      "foto.jpg").exists()

    def test_re_rrodada_no_mesmo_minuto_substitui_sem_sobra(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        arv = _Arvore(tmp_path, monkeypatch)
        relogio = _Clock(_epoch("2026-10-17 04:00"))
        svc = arv.svc(relogio=relogio)
        res1 = svc.rodar_agora()
        res2 = svc.rodar_agora()  # relógio congelado ⇒ MESMO nome
        assert res1.arquivo == res2.arquivo and res2.ok
        raiz = arv.alvo / "od_snapshots"
        assert [d.name for d in raiz.iterdir()] == [res1.arquivo]

    def test_forcar_com_hd_fora_nao_grava_nada(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        arv = _Arvore(tmp_path, monkeypatch)
        svc = arv.svc(montado=False)
        res = svc.rodar_agora()
        assert not res.ok and "desmontado" in res.erro
        assert not (arv.alvo / "od_snapshots").exists()
        estado = json.loads(arv.cfg().estado_path.read_text(encoding="utf-8"))
        assert estado["falhas"] == 1

    def test_arquivo_ilegel_excluido_com_recibo_no_info(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Os root:root 0600 do `.storage` do HA (medido em produção
        17/10: auth, core.config, onboarding, ...): o rsync 3.2.7 não
        tem `--skip-bad-files`, então a varredura prévia exclui por
        caminho e o `info.json` leva o RECIBO — restaurador sabe o que
        ficou de fora; rc=23 não derruba o snapshot inteiro."""
        arv = _Arvore(tmp_path, monkeypatch)
        secreto = arv.fonte_repo / "secreto.txt"
        secreto.write_text("x", encoding="utf-8")
        os.chmod(secreto, 0o000)
        try:
            svc = arv.svc()
            res = svc.rodar_agora()
            assert res.ok, res.erro
            snap = arv.snap(res.arquivo)
            assert not arv.em(snap, arv.fonte_repo, "secreto.txt").exists()
            info = json.loads((snap / "info.json").read_text(encoding="utf-8"))
            assert info["ilegiveis_total"] == 1
            assert info["ilegiveis"] == [str(secreto)]
            estado = json.loads(
                arv.cfg().estado_path.read_text(encoding="utf-8")
            )
            assert estado["ultimo_ilegiveis"] == 1
            assert estado["falhas"] == 0  # recibo, não é falha
        finally:
            os.chmod(secreto, 0o644)

    def test_fonte_sumida_nao_derruba_as_outras(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        arv = _Arvore(tmp_path, monkeypatch)
        svc = arv.svc(cfg=arv.cfg(fontes=(
            str(tmp_path / "nao_existe"), str(arv.fonte_repo),
        )))
        res = svc.rodar_agora()
        assert res.ok  # sobrevive filtrando o que não existe

    def test_nenhuma_fonte_viva_erro_honesto(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        arv = _Arvore(tmp_path, monkeypatch)
        svc = arv.svc(cfg=arv.cfg(fontes=(str(tmp_path / "sumiu"),)))
        res = svc.rodar_agora()
        assert not res.ok and "nenhuma fonte" in res.erro

    def test_sem_banco_de_fonte_so_pula_o_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(hd_backup, "DB_FONTES",
                            (str(tmp_path / "nao_tem.db"),))
        arv = _Arvore(tmp_path, monkeypatch)
        # _Arvore repõe DB_FONTES — re-seta depois dele:
        monkeypatch.setattr(hd_backup, "DB_FONTES",
                            (str(tmp_path / "nao_tem.db"),))
        res = arv.svc().rodar_agora()
        assert res.ok
        snap = arv.snap(res.arquivo)
        assert not (snap / str(tmp_path / "nao_tem.db").lstrip("/")).exists()


# ---------------------------------------------------------------------------
# Retenção e listagem
# ---------------------------------------------------------------------------


class TestRetencao:
    def _montar_raiz(self, arv: _Arvore, svc: HDBackupService) -> Path:
        raiz = arv.alvo / "od_snapshots"
        raiz.mkdir(parents=True, exist_ok=True)
        for dia in range(1, 21):  # 20 snapshots diários no padrão
            (raiz / nome_dir(_epoch(f"2026-10-{dia:02d} 03:40"))).mkdir()
        (raiz / "coisa_do_downer").mkdir()          # nome fora do padrão
        (raiz / "meu_backup_od-2026-10-17_0340").write_text("x")  # arquivo
        return raiz

    def test_retencao_sai_só_o_que_esta_no_padrao(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        arv = _Arvore(tmp_path, monkeypatch)
        cfg = arv.cfg(diarios=3, semanais=0)
        svc = arv.svc(cfg=cfg)
        raiz = self._montar_raiz(arv, svc)
        nomes = sorted(
            d.name for d in raiz.iterdir() if d.is_dir()
            and timestamp_do_nome(d.name, "snapshot_od", "") is not None
        )
        esperado = set(calcular_retencao(
            nomes, diarios=3, semanais=0, prefixo="snapshot_od", sufixo="",
        ).manter)
        removidos = svc._aplicar_retencao()
        sobrando = {d.name for d in raiz.iterdir() if d.is_dir()}
        assert set(removidos) == (set(nomes) - esperado)
        assert sobrando == esperado | {"coisa_do_downer"}
        # arquivo solto com nome no padrão: NUNCA é candidato a rmtree
        assert (raiz / "meu_backup_od-2026-10-17_0340").exists()

    def test_tmp_orfao_de_run_interrompido_e_limpo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        arv = _Arvore(tmp_path, monkeypatch)
        svc = arv.svc()
        raiz = arv.alvo / "od_snapshots"
        raiz.mkdir(parents=True)
        velho = raiz / ".tmp_snapshot_od-2026-10-15_0340"
        velho.mkdir()
        velho_2 = raiz / ".tmp_snapshot_od-2026-10-16_0340"
        velho_2.mkdir()
        ontem = time.time() - 7 * 3600
        os.utime(velho, (ontem, ontem))
        svc._aplicar_retencao()
        assert not velho.exists()
        assert velho_2.exists()  # <6 h: é run em andamento, não toca

    def test_lista_mostra_so_dirs_padrao_com_bytes_do_info(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        arv = _Arvore(tmp_path, monkeypatch)
        svc = arv.svc()
        raiz = arv.alvo / "od_snapshots"
        raiz.mkdir(parents=True)
        bom = raiz / nome_dir(_epoch("2026-10-16 03:40"))
        bom.mkdir()
        (bom / "info.json").write_text(json.dumps({"bytes": 4242}))
        (raiz / "coisa_do_downer").mkdir()
        itens = svc.lista()
        assert list(itens) == [bom.name]
        assert itens[bom.name]["bytes"] == 4242
        assert itens[bom.name]["criado"] == "16/10/2026 03:40"


# ---------------------------------------------------------------------------
# Saúde — nunca verde de mentira
# ---------------------------------------------------------------------------


class TestSaude:
    def test_check_as_quatro_verdades(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        arv = _Arvore(tmp_path, monkeypatch)
        cfg = arv.cfg()

        # 1) janela futura: agendado (up)
        svc = arv.svc(cfg=cfg, relogio=_Clock(_epoch("2026-10-17 02:00")))
        c = svc.check_saude()
        assert c["ok"] and "agendado" in c["detail"]

        # 2) sucesso de hoje: up com tamanho
        estado = {"ultimo_sucesso": _epoch("2026-10-17 03:41"),
                  "ultimo_bytes": 5 * 1024 ** 3,
                  "ultimo_arquivo": "snapshot_od-2026-10-17_0341"}
        cfg.estado_path.write_text(json.dumps(estado), encoding="utf-8")
        svc_de_dia = arv.svc(cfg=cfg,
                             relogio=_Clock(_epoch("2026-10-17 10:00")))
        c = svc_de_dia.check_saude()
        assert c["ok"] and "5,00" in c["detail"].replace(".", ",")
        assert "há 6.3 h" in c["detail"]

        # 3) janela passada + HD desconectada: degrada dizendo o motivo
        cfg.estado_path.unlink()
        svc_sem_disco = arv.svc(cfg=cfg, relogio=_Clock(
            _epoch("2026-10-17 10:00")), montado=False)
        c = svc_sem_disco.check_saude()
        assert c["ok"] is False and c["status"] == "degraded"
        assert "desconectada" in c["detail"]

        # 4) janela passada + disco montado + nada feito: pendente honesto
        cfg.estado_path.write_text(
            json.dumps({"falhas": 3, "ultimo_erro": "rsync rc=23"}),
            encoding="utf-8",
        )
        c = svc_de_dia.check_saude()
        assert c["ok"] is False
        assert "PENDENTE" in c["detail"] and "falhas=3" in c["detail"]
        assert "rsync rc=23" in c["detail"]

    def test_registra_check_nao_critico_no_health(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        arv = _Arvore(tmp_path, monkeypatch)
        svc = arv.svc()
        monitor = HealthMonitor()
        assert svc.registrar_no_health(monitor) == "hd_midias"
        assert monitor.components == ["hd_midias"]
        assert svc.registrar_no_health(None) is None

    def test_snapshot_traz_as_chaves_do_painel(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        arv = _Arvore(tmp_path, monkeypatch)
        svc = arv.svc()
        dados = svc.snapshot()
        assert {
            "nome", "rotulo", "config", "ultimo_sucesso",
            "ultimo_sucesso_em", "ultimo_arquivo", "ultimo_bytes",
            "ultimo_sha256", "rodadas", "falhas", "ultimo_erro",
            "pendente_hoje", "arquivos", "alvo", "montado",
        } <= set(dados)
        assert dados["montado"] is True
        assert dados["config"]["alvo"] == str(arv.alvo)
        assert dados["pendente_hoje"] is True  # janela de hoje passou


# ---------------------------------------------------------------------------
# Falha grita, estado sobrevive a disco corrompido
# ---------------------------------------------------------------------------


class TestFalhaEEstado:
    def test_falha_grita_uma_vez_por_6_horas(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        arv = _Arvore(tmp_path, monkeypatch)
        relogio = _Clock(_epoch("2026-10-17 04:00"))
        push = _Push()
        svc = arv.svc(relogio=relogio, push=push, rsync="/bin/sem_rsync")

        r1 = svc.tick(forcar=True)
        assert not r1.ok and len(push.chamadas) == 1
        relogio.avancar(60 * 30)  # 30 min: cooldown manda calar
        r2 = svc.tick(forcar=True)
        assert not r2.ok and len(push.chamadas) == 1
        relogio.avancar(7 * 3600)  # passou das 6 h: grita de novo
        r3 = svc.tick(forcar=True)
        assert not r3.ok and len(push.chamadas) == 2
        assert "Snapshot" in push.chamadas[0][0]

        estado = json.loads(arv.cfg().estado_path.read_text(encoding="utf-8"))
        assert estado["falhas"] == 3 and estado["ultimo_erro"]

    def test_estado_corrompido_vai_a_zero_e_o_tick_sobrevive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        arv = _Arvore(tmp_path, monkeypatch)
        arv.cfg().estado_path.write_text("{{{não é json", encoding="utf-8")
        svc = arv.svc()
        assert svc.carregar_estado() == {}
        res = svc.rodar_agora()
        assert res.ok
        assert json.loads(
            arv.cfg().estado_path.read_text(encoding="utf-8")
        )["rodadas"] == 1

    def test_tick_fora_da_janela_nao_executa(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        arv = _Arvore(tmp_path, monkeypatch)
        svc = arv.svc(relogio=_Clock(_epoch("2026-10-17 02:00")))
        res = svc.tick()
        assert res.acao == AGUARDAR and not res.executado
        assert not (arv.alvo / "od_snapshots").exists()


# ---------------------------------------------------------------------------
# Fiação do launcher
# ---------------------------------------------------------------------------


class TestFiaçaoDoLauncher:
    def test_build_backups_acrescenta_os_hd_a_lista(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import runtime.launcher as launcher

        monkeypatch.setattr(launcher, "env", _env_de({}))
        monkeypatch.setattr(launcher, "push", None, raising=False)
        servicos = launcher.build_backups(push=None)
        nomes = [s.cfg.nome for s in servicos]
        # tar (estado + capturas) + os 2 HDs, interface intercambiável:
        # mesmo .cfg/.tick/.snapshot() que o loop e o stats usam
        assert nomes[:2] == ["estado", "capturas"]
        assert nomes[2:] == ["hd_midias", "hd_arquivos"]
        for svc in servicos:
            assert callable(svc.tick) and callable(svc.snapshot)
            assert callable(svc.registrar_no_health)

    def test_hd_do_launcher_quebrado_nao_derruba_os_tars(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import runtime.launcher as launcher

        def _explodir(**_kwargs):
            raise RuntimeError("hd fora do ar")

        monkeypatch.setattr(launcher, "env", _env_de({}))
        monkeypatch.setattr(
            "core.hd_backup.build_hd_services", _explodir
        )
        servicos = launcher.build_backups(push=None)
        assert [s.cfg.nome for s in servicos] == ["estado", "capturas"]
