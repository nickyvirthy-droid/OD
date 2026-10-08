"""
OMEGA DRAKON • TESTS
Módulo: tests/test_dev_canal.py
Descrição: histórico de ideias do canal de desenvolvimento on-demand
           (core/dev_canal.py) — o botão ▶ Ativar não roda duas vezes a
           MESMA ideia: quem grava é o orquestrador ao fim da sessão
           concluída, quem lê é o painel no clique.

Baseado em:
  - core/dev_canal.py
  - iniciar/RULES.md (regra 7: código antes de suposições)
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import json
from pathlib import Path

from core.dev_canal import (
    carregar_historico,
    hash_ideia,
    ideia_ja_implementada,
    normalizar_ideia,
    registrar_ideia,
)

CONCLUIDA = {"status": "concluido", "motivo": "implantado", "commit": "abc1234"}
FALHOU = {"status": "falhou", "motivo": "testes_vermelhos", "commit": ""}


class TestNormalizacao:
    def test_espacos_e_caixa_nao_mudam_a_ideia(self) -> None:
        """A forma do dono não muda o significado: quebra de linha, espaço
        duplo e caixa alta são a MESMA ideia para o aviso já-implementado."""
        assert normalizar_ideia("Criar   botão\r\n  NOVO") == "criar botão novo"
        assert hash_ideia("Criar   botão\r\n  NOVO") == hash_ideia("criar botão novo")

    def test_ideias_diferentes_tem_hash_diferente(self) -> None:
        assert hash_ideia("criar botão") != hash_ideia("criar botão verde")

    def test_vazio_nao_tem_hash(self) -> None:
        assert hash_ideia("") == ""
        assert hash_ideia(None) == ""
        assert normalizar_ideia(None) == ""


class TestHistorico:
    def test_arquivo_ausente_ou_corrompido_e_lista_vazia(self, tmp_path: Path) -> None:
        """O canal nunca quebra por causa do histórico: ausente ou lixo → []."""
        ausente = tmp_path / "nao_existe.json"
        assert carregar_historico(ausente) == []
        corrompido = tmp_path / "corrompido.json"
        corrompido.write_text("{não é json", encoding="utf-8")
        assert carregar_historico(corrompido) == []
        nao_lista = tmp_path / "objeto.json"
        nao_lista.write_text('{"status": "concluido"}', encoding="utf-8")
        assert carregar_historico(nao_lista) == []

    def test_concluida_bloqueia_e_falha_nao_bloqueia(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "hist.json"
        registrar_ideia("criar botão de tema", CONCLUIDA, arquivo)
        # mesma ideia com formatação diferente → bloqueada
        assert ideia_ja_implementada("  Criar   botão\n de tema ", arquivo) is not None
        # ideia nova → liberada
        assert ideia_ja_implementada("outro recado", arquivo) is None
        # sessão que FALHOU nunca é "implementada"
        registrar_ideia("ideia ruim", FALHOU, arquivo)
        assert ideia_ja_implementada("ideia ruim", arquivo) is None

    def test_entrada_guarda_commit_data_e_texto(self, tmp_path: Path) -> None:
        """O painel precisa de commit/ts/motivo para montar o aviso."""
        arquivo = tmp_path / "hist.json"
        entrada = registrar_ideia("criar botão", CONCLUIDA, arquivo)
        assert entrada is not None
        assert entrada["status"] == "concluido"
        assert entrada["motivo"] == "implantado"
        assert entrada["commit"] == "abc1234"
        assert entrada["ts"].startswith("20")
        assert entrada["ideia"] == "criar botão"
        assert entrada["hash"] == hash_ideia("criar botão")
        no_disco = json.loads(arquivo.read_text(encoding="utf-8"))
        assert no_disco == [entrada]

    def test_registrar_so_quando_concluido(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "hist.json"
        assert registrar_ideia("ideia", {"status": "falhou"}, arquivo) is None
        assert registrar_ideia("   ", CONCLUIDA, arquivo) is None
        assert not arquivo.exists()
        assert carregar_historico(arquivo) == []

    def test_registrar_deduplica_por_hash(self, tmp_path: Path) -> None:
        """Registar a MESMA ideia de novo substitui (vale a conclusão nova)."""
        arquivo = tmp_path / "hist.json"
        registrar_ideia("criar botão", CONCLUIDA, arquivo)
        registrar_ideia(
            "criar botão", dict(CONCLUIDA, commit="def5678"), arquivo
        )
        historico = carregar_historico(arquivo)
        assert len(historico) == 1
        assert historico[0]["commit"] == "def5678"

    def test_registrar_respeita_o_teto(self, tmp_path: Path) -> None:
        from core.dev_canal import HISTORICO_MAX
        arquivo = tmp_path / "hist.json"
        for i in range(HISTORICO_MAX + 5):
            registrar_ideia(f"ideia {i}", CONCLUIDA, arquivo)
        historico = carregar_historico(arquivo)
        assert len(historico) == HISTORICO_MAX
        assert historico[-1]["ideia"] == f"ideia {HISTORICO_MAX + 4}"
