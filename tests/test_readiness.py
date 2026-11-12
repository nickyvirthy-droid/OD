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
