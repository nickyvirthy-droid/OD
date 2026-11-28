"""Prontidão do sistema para operar sem internet/energia.

Origem (12/11/2026): `txt.txt` do dono — "prepare o Omega Drakon para
resistir... busque todas as alternativas para continuar funcionando e se
comunicando". A resposta é MEDIDA (energia, disco, memória, acervo offline, IA
local, internet, backup, comunicação, dependência de nuvem), nunca opinião.
"""

from __future__ import annotations

import pytest

from core.intents import detect_action_intent, format_intent_result
from tools.actions.actions import readiness_report


class TestReadinessReport:
    def test_energia_conta_quando_o_vigia_esta_autorizado(
        self, tmp_path, monkeypatch
    ) -> None:
        """Sem UPS no SO, o vigia de energia (inferência) substitui o upsc —
        desde que o desligamento esteja autorizado pelo polkit."""
        from core import energia as mod

        monkeypatch.setattr(mod, "estado_atual", lambda: {
            "estado": "normal", "autorizado": {"autorizado": True, "motivo": ""},
        })
        r = readiness_report(
            zim_dir=str(tmp_path), zim_dir_frio=str(tmp_path), backup_dir=str(tmp_path)
        )
        energia = next(i for i in r["itens"] if i["nome"] == "energia")
        assert energia["ok"] is True
        assert "vigia de energia" in energia["detalhe"]

    def test_relatorio_tem_os_nove_checks(self, tmp_path) -> None:
        r = readiness_report(zim_dir=str(tmp_path), zim_dir_frio=str(tmp_path), backup_dir=str(tmp_path))
        nomes = [i["nome"] for i in r["itens"]]
        assert nomes == [
            "energia",
            "disco",
            "memória",
            "conhecimento",
            "ia_local",
            "internet",
            "backup",
            "comunicacao",
            "nuvem",
        ]

    def test_pontuacao_bate_com_os_itens(self, tmp_path) -> None:
        r = readiness_report(zim_dir=str(tmp_path), zim_dir_frio=str(tmp_path), backup_dir=str(tmp_path))
        assert r["pontos"] == sum(1 for i in r["itens"] if i["ok"])
        assert r["total"] == len(r["itens"])
        assert r["percent"] == pytest.approx(100.0 * r["pontos"] / r["total"], abs=0.1)
        assert r["pendentes"] == [i["nome"] for i in r["itens"] if not i["ok"]]

    def test_acervo_offline_pequeno_reprova(self, tmp_path) -> None:
        """Sem ZIM o item de conhecimento não passa — e o detalhe diz o porquê."""
        (tmp_path / "dummy.zim").write_bytes(b"0" * 1024)
        r = readiness_report(zim_dir=str(tmp_path), zim_dir_frio=str(tmp_path), backup_dir=str(tmp_path))
        conhecimento = next(i for i in r["itens"] if i["nome"] == "conhecimento")
        assert conhecimento["ok"] is False
        assert "ZIM" in conhecimento["detalhe"]

    def test_sem_backup_reprova(self, tmp_path) -> None:
        vazio = tmp_path / "sem_backup"
        vazio.mkdir()
        r = readiness_report(zim_dir=str(tmp_path), zim_dir_frio=str(vazio), backup_dir=str(vazio))
        backup = next(i for i in r["itens"] if i["nome"] == "backup")
        assert backup["ok"] is False
        assert "nenhum backup" in backup["detalhe"]

    def test_nao_quebra_com_caminhos_inexistentes(self, tmp_path) -> None:
        r = readiness_report(
            zim_dir=str(tmp_path / "nao_existe"),
            backup_dir=str(tmp_path / "tambem_nao"),
        )
        assert r["ok"] is True
        assert len(r["itens"]) == 9


class TestReadinessNoChat:
    @pytest.mark.parametrize(
        "text",
        [
            "como estamos preparados para o colapso",
            "qual a prontidão do sistema",
            "o que falta para resistir",
            "modo colapso",
        ],
    )
    def test_intencao_de_prontidao(self, text: str) -> None:
        assert detect_action_intent(text) == ("readiness_report", {})

    @pytest.mark.parametrize(
        "text",
        ["quanto de disco está livre", "me conta uma história", "liga a rádio"],
    )
    def test_nao_confunde_conversa_com_prontidao(self, text: str) -> None:
        intent = detect_action_intent(text)
        assert intent is None or intent[0] != "readiness_report"

    def test_formatador_resume_itens_e_pendentes(self) -> None:
        dados = {
            "pontos": 1,
            "total": 2,
            "percent": 50.0,
            "itens": [
                {"nome": "disco", "ok": True, "detalhe": "75 GB livres"},
                {"nome": "energia", "ok": False, "detalhe": "sem UPS"},
            ],
            "pendentes": ["energia"],
        }
        texto = format_intent_result("readiness_report", dados)
        assert "1/2" in texto
        assert "✅ disco" in texto
        assert "⚠️ energia" in texto
        assert "Pendente: energia" in texto

    def test_formatador_sem_itens_devolve_none(self) -> None:
        assert format_intent_result("readiness_report", {"ok": True}) is None


class TestUpscDoNoBreak:
    """Pendência do TODO: ler `upsc` no readiness quando houver no-break USB.

    Hoje o Attiv do dono não aparece no SO; o código precisa estar pronto (e
    testado) para o dia em que entrar um que apareça.
    """

    def test_upsc_com_dados_conta_como_energia_ok(self, tmp_path, monkeypatch) -> None:
        from tools.actions import actions as mod

        monkeypatch.setattr(
            mod, "_upsc_status",
            lambda: {
                "nome": "ups",
                "campos": {
                    "ups.status": "OL",
                    "battery.charge": "100",
                    "battery.runtime": "3600",
                },
            },
        )
        r = readiness_report(
            zim_dir=str(tmp_path), zim_dir_frio=str(tmp_path), backup_dir=str(tmp_path)
        )
        energia = next(i for i in r["itens"] if i["nome"] == "energia")
        assert energia["ok"] is True
        assert "upsc" in energia["detalhe"]
        assert "100%" in energia["detalhe"]
        assert "60 min" in energia["detalhe"]

    def test_sem_upsc_o_relatorio_nao_quebra(self, tmp_path, monkeypatch) -> None:
        from tools.actions import actions as mod

        monkeypatch.setattr(mod, "_upsc_status", lambda: None)
        r = readiness_report(
            zim_dir=str(tmp_path), zim_dir_frio=str(tmp_path), backup_dir=str(tmp_path)
        )
        assert [i["nome"] for i in r["itens"]][0] == "energia"

    def test_binario_ausente_devolve_none(self, monkeypatch) -> None:
        from tools.actions import actions as mod

        monkeypatch.setattr(mod.shutil, "which", lambda _nome: None)
        assert mod._upsc_status() is None

    def test_parsing_do_upsc(self, monkeypatch) -> None:
        from tools.actions import actions as mod

        class _Proc:
            def __init__(self, stdout: str) -> None:
                self.stdout = stdout
                self.returncode = 0

        def _run(args, **_kwargs):
            if args[1] == "-l":
                return _Proc("ups\n")
            return _Proc(
                "ups.status: OB\nbattery.charge: 87\n"
                "battery.runtime: 900\ndevice.mfr: APC\n"
            )

        monkeypatch.setattr(mod.shutil, "which", lambda _nome: "/usr/bin/upsc")
        monkeypatch.setattr(mod.subprocess, "run", _run)
        dados = mod._upsc_status()
        assert dados["nome"] == "ups"
        assert dados["campos"]["ups.status"] == "OB"
        assert dados["campos"]["battery.charge"] == "87"

    def test_nut_fora_do_ar_nao_derruba(self, monkeypatch) -> None:
        from tools.actions import actions as mod

        def _explode(*_a, **_k):
            raise OSError("connection refused")

        monkeypatch.setattr(mod.shutil, "which", lambda _nome: "/usr/bin/upsc")
        monkeypatch.setattr(mod.subprocess, "run", _explode)
        assert mod._upsc_status() is None
