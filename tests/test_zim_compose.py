"""
OMEGA DRAKON • TESTS
Módulo: tests/test_zim_compose.py
Descrição: Guarda do acervo offline (P0 nº 3 da revisão de 17/11) — todo ZIM
           no disco precisa estar no `command` do kiwix em
           `docker/tools-compose.yaml`.

           O kiwix-serve não aceita glob: cada ZIM é um argumento posicional.
           Sem esta guarda, um ZIM novo baixado no diretório montado fica
           INVISÍVEL para a busca até alguém lembrar de editar o compose —
           e o inverso também acontece (compose cita arquivo que sumiu e o
           container sobe com `--skipInvalid`, servindo menos acervo).

Interface Viva: Nicky Virthy
Arquiteto: Alex Projetti
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import checar_zim_compose as checar

COMPOSE = """\
services:
  kiwix:
    image: ghcr.io/kiwix/kiwix-serve:3.8.1
    volumes:
      - {quente}:/data:ro
      - {frio}:/frio:ro
    command:
      - "--skipInvalid"
      - "/data/quente_a.zim"
      - "/data/quente_b.zim"
      - "/frio/frio_a.zim"
  outra:
    image: exemplo
    volumes:
      - {quente}:/data:ro
"""


@pytest.fixture()
def cenario(tmp_path: Path) -> tuple[Path, Path, Path]:
    quente = tmp_path / "zim"
    frio = tmp_path / "frio"
    quente.mkdir()
    frio.mkdir()
    (quente / "quente_a.zim").write_text("a", encoding="utf-8")
    (quente / "quente_b.zim").write_text("b", encoding="utf-8")
    (frio / "frio_a.zim").write_text("c", encoding="utf-8")
    compose = tmp_path / "tools-compose.yaml"
    compose.write_text(
        COMPOSE.format(quente=quente, frio=frio), encoding="utf-8"
    )
    return compose, quente, frio


class TestParse:
    def test_extrai_volumes_e_zims_so_do_kiwix(self, cenario) -> None:
        compose, quente, frio = cenario
        volumes, citados = checar.ler_compose(compose)
        assert volumes == {
            "/data": quente,
            "/frio": frio,
        }
        assert citados == [
            "/data/quente_a.zim",
            "/data/quente_b.zim",
            "/frio/frio_a.zim",
        ]

    def test_bloco_para_no_proximo_servico(self) -> None:
        bloco = checar.bloco_kiwix(COMPOSE.format(quente="/a", frio="/b"))
        assert "kiwix" in bloco and "--skipInvalid" in bloco
        assert "outra" not in bloco and "image: exemplo" not in bloco

    def test_sem_kiwix_devolve_vazio(self) -> None:
        assert checar.bloco_kiwix("services:\n  outro:\n    image: x\n") == ""


class TestDivergencias:
    def test_acervo_alinhado(self, cenario) -> None:
        compose, _, _ = cenario
        assert checar.verificar(compose) == {
            "citados_ausentes_no_disco": [],
            "citados_sem_montagem": [],
            "no_disco_fora_do_compose": [],
        }

    def test_zim_novo_no_disco_aparece_fora_do_compose(self, cenario) -> None:
        compose, quente, _ = cenario
        (quente / "novo_2026.zim").write_text("novo", encoding="utf-8")
        r = checar.verificar(compose)
        assert r["no_disco_fora_do_compose"] == ["/data/novo_2026.zim"]
        assert r["citados_ausentes_no_disco"] == []

    def test_zim_citado_e_ausente_no_disco(self, cenario) -> None:
        compose, _, frio = cenario
        (frio / "frio_a.zim").unlink()
        r = checar.verificar(compose)
        assert r["citados_ausentes_no_disco"] == ["/frio/frio_a.zim"]

    def test_zim_citado_em_diretorio_nao_montado(self, tmp_path: Path) -> None:
        compose = tmp_path / "c.yaml"
        compose.write_text(
            "services:\n  kiwix:\n    command:\n"
            '      - "/mnt/fora/x.zim"\n', encoding="utf-8"
        )
        r = checar.verificar(compose)
        assert r["citados_sem_montagem"] == ["/mnt/fora/x.zim"]

    def test_arquivos_que_nao_sao_zim_sao_ignorados(self, cenario) -> None:
        compose, quente, _ = cenario
        (quente / "MANIFEST").write_text("sha256", encoding="utf-8")
        (quente / "parcial.zim.part").write_text("x", encoding="utf-8")
        assert checar.verificar(compose)["no_disco_fora_do_compose"] == []

    def test_diretorio_de_volume_ausente_nao_quebra(self, tmp_path: Path) -> None:
        compose = tmp_path / "c.yaml"
        compose.write_text(
            "services:\n  kiwix:\n    volumes:\n"
            f"      - {tmp_path / 'sumiu'}:/data:ro\n"
            "    command:\n"
            '      - "/data/a.zim"\n', encoding="utf-8"
        )
        r = checar.verificar(compose)
        assert r["no_disco_fora_do_compose"] == []


class TestAcervoReal:
    """A guarda contra o acervo de verdade (14 ZIMs / 40,3 GB em 12/11).

    Sem o compose ou sem os diretórios montados (CI/outra máquina), o teste
    pula com motivo declarado — nunca finge que verificou.
    """

    def test_compose_real_existe(self) -> None:
        assert checar.COMPOSE_PADRAO.exists(), "docker/tools-compose.yaml sumiu"

    def test_acervo_real_alinhado_com_o_compose(self) -> None:
        volumes, citados = checar.ler_compose(checar.COMPOSE_PADRAO)
        if not citados:
            pytest.skip("compose sem ZIMs citados")
        if not all(Path(host).exists() for host in volumes.values()):
            pytest.skip("diretórios do acervo não montados nesta máquina")
        r = checar.verificar(checar.COMPOSE_PADRAO)
        assert r["citados_ausentes_no_disco"] == []
        assert r["citados_sem_montagem"] == []
        assert r["no_disco_fora_do_compose"] == []
