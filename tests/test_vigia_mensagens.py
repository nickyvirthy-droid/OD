"""
Guardas do VIGIA DAS MENSAGENS (core/vigia_mensagens.py).

Pedido do dono (26/10): verificar as conversas pelo menos 1× por dia e
CONCERTAR — à minha pergunta de régua ele respondeu "reparo automático
completo", mandando usar os achados da auditoria do dia (10
'respposta_errada' + 5 'inconsistente' em 30 turnos).

A régua destas guardas: o vigia só conserta causas DETERMINÍSTICAS e
comprova cada passo — sonda detecta → CoderEngine aplica → gate →
commit, ou ROLLBACK bit a bit. O que está travado aqui:

  * a sonda de rota acha o defeito do infinitivo ('ligar TV' não
    chegava em ha_device_control) e fica verde quando consertado;
  * a sonda de rede acha bridge do Docker na resposta de network_hosts;
  * a estratégia NUNCA escreve com âncora ausente (fila, não chute);
  * o reparo é idempotente no código de hoje (sem_defeito | aplicado,
    nunca 'ancora_ausente' — vale ANTES e DEPOIS do conserto);
  * gate vermelho → rollback + fila; verde → commit + restart;
  * arquivo sujo (resíduo de sessão alheia) → fila, nunca sobrescrito;
  * --seco não toca git, gate nem Telegram (dry-run de verdade);
  * a janela --ultimas do auditor corta por data (o defeito corrigido
    do próprio auditor: --limite pegava os turnos MAIS ANTIGOS).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

import pytest

from core import vigia_mensagens as vm


def _blocos(trocas: Any, novo: bool = False) -> str:
    """Concatena o lado ANTIGO (0) ou NOVO (1) das trocas ancoradas.

    Cada troca é (rótulo, bloco_antigo, bloco_novo).
    """
    return "\n".join(bloco[2 if novo else 1] for bloco in trocas)


# ---------------------------------------------------------------------------
# Sonda 1 — rota de aparelho no infinitivo (core/intents.py)
# ---------------------------------------------------------------------------


class TestSondaRotaAparelho:
    """'ligar TV' / 'desligar o ar' precisam virar ha_device_control."""

    def test_sonda_detecta_o_defeito_do_infinitivo(self) -> None:
        """Só 'ligar TV' falhando já deixa a sonda vermelha."""
        def detector(frase: str) -> Optional[tuple[str, dict[str, Any]]]:
            if frase == "ligar TV":
                return None  # o defeito de 26/10: infinitivo fora do regex
            return ("ha_device_control", {"entity_id": "", "on": True})

        assert vm.SondaRotaAparelho().vermelha(detector) is True

    def test_sonda_verde_quando_todas_as_frases_rodam(self) -> None:
        espera = {frase: on for frase, on in vm.FRASES_ROTA}

        def detector(frase: str) -> tuple[str, dict[str, Any]]:
            return ("ha_device_control",
                    {"entity_id": "", "on": espera[frase]})

        assert vm.SondaRotaAparelho().vermelha(detector) is False

    def test_sonda_quebrada_conta_como_vermelha(self) -> None:
        """Detector que explode não pode passar batido como 'verde'."""
        def detector(frase: str) -> Any:
            raise RuntimeError("sem HA")

        assert vm.SondaRotaAparelho().vermelha(detector) is True

    def test_reparo_sobre_conteudo_antigo_insere_infinitivos(self) -> None:
        antigo = _blocos(vm._TROCAS_INTENTS)
        rep = vm.SondaRotaAparelho().reparo(conteudo=antigo)

        assert rep["status"] == "aplicado"
        texto = rep["arquivos"]["core/intents.py"]
        assert "ligar|" in texto and "desligar|" in texto
        assert '"apagar"' in texto and '"desconectar"' in texto
        for _rotulo, _velho, bloco_novo in vm._TROCAS_INTENTS:
            assert bloco_novo in texto  # os 3 blocos novos entraram inteiros

    def test_reparo_com_ancora_sumida_vai_para_fila(self) -> None:
        rep = vm.SondaRotaAparelho().reparo(conteudo="# refatorado sem aviso\n")

        assert rep["status"] == "ancora_ausente"
        assert len(rep["faltando"]) == 3  # A1 + A2 + A3, as 3 âncoras

    def test_reparo_no_codigo_de_hoje_e_idempotente(self) -> None:
        """Ou o código está certo, ou a estratégia sabe consertar —
        nunca 'âncora ausente' (que seria fila às 04:30 sem conserto)."""
        sonda = vm.SondaRotaAparelho()
        rep = sonda.reparo()

        assert rep["status"] in ("sem_defeito", "aplicado"), rep
        if sonda.vermelha():
            assert rep["status"] == "aplicado"

    def test_confere_staged_rejeita_o_codigo_antigo(self) -> None:
        sonda = vm.SondaRotaAparelho()

        assert sonda.confere_staged(_blocos(vm._TROCAS_INTENTS)) is False
        assert sonda.confere_staged(_blocos(vm._TROCAS_INTENTS, novo=True)) is True

    def test_runner_do_coder_le_o_arquivo_staged(self, tmp_path) -> None:
        staged = tmp_path / "intents.py"
        runner = vm.SondaRotaAparelho().runner()

        staged.write_text(_blocos(vm._TROCAS_INTENTS, novo=True), encoding="utf-8")
        assert runner(relpath="core/intents.py", staged_file=str(staged),
                      sandbox_dir=str(tmp_path), original_file="") is True

        staged.write_text("x = 1\n", encoding="utf-8")
        assert runner(relpath="core/intents.py", staged_file=str(staged),
                      sandbox_dir=str(tmp_path), original_file="") is False


# ---------------------------------------------------------------------------
# Sonda 2 — network_hosts sem bridges do Docker (tools/actions/actions.py)
# ---------------------------------------------------------------------------


class TestSondaRedeSemBridge:
    """Contêiner do Docker atrás de `br-*` não é aparelho de ninguém."""

    def test_injecao_de_arp_devolve_e_restaura_o_read_proc(self) -> None:
        from tools.actions import actions as ac

        antes = ac._read_proc
        hosts = vm._hosts_com_arp(vm.ARP_SINTETICO)

        assert ac._read_proc is antes  # o finally devolveu o original
        assert "192.168.0.10" in {h["ip"] for h in hosts}

    def test_sonda_espelha_a_regra_da_resposta(self) -> None:
        """Vermelha ⇔ a resposta traz iface virtual — coerente com o que
        a ação devolve hoje (com ou sem o filtro, o teste passa)."""
        sonda = vm.SondaRedeSemBridge()
        hosts = vm._hosts_com_arp(vm.ARP_SINTETICO)
        esperado = any(
            str(h.get("interface") or "").startswith(vm.PREFIXOS_VIRTUAIS)
            for h in hosts)

        assert sonda.vermelha(arp=vm.ARP_SINTETICO) == esperado

    def test_reparo_sobre_conteudo_antigo_insere_o_filtro(self) -> None:
        antigo = _blocos(vm._TROCAS_REDE)
        rep = vm.SondaRedeSemBridge().reparo(conteudo=antigo)

        assert rep["status"] == "aplicado"
        texto = rep["arquivos"]["tools/actions/actions.py"]
        assert "_IFACES_VIRTUAIS = (" in texto
        assert "iface.startswith(_IFACES_VIRTUAIS)" in texto
        for _rotulo, _velho, bloco_novo in vm._TROCAS_REDE:
            assert bloco_novo in texto  # os 2 blocos novos entraram inteiros

    def test_reparo_com_ancora_sumida_vai_para_fila(self) -> None:
        rep = vm.SondaRedeSemBridge().reparo(conteudo="def outra_coisa():\n")

        assert rep["status"] == "ancora_ausente"
        assert len(rep["faltando"]) == 2  # B1 + B2

    def test_reparo_no_codigo_de_hoje_e_idempotente(self) -> None:
        sonda = vm.SondaRedeSemBridge()
        rep = sonda.reparo()

        assert rep["status"] in ("sem_defeito", "aplicado"), rep

    def test_confere_staged_rejeita_o_codigo_antigo(self) -> None:
        sonda = vm.SondaRedeSemBridge()

        assert sonda.confere_staged(_blocos(vm._TROCAS_REDE)) is False
        assert sonda.confere_staged(_blocos(vm._TROCAS_REDE, novo=True)) is True


# ---------------------------------------------------------------------------
# Registro de estratégias (anti-refatoramento silencioso)
# ---------------------------------------------------------------------------


class TestRegistroDeEstrategias:
    def test_sondas_cobrem_os_defeitos_diagnosticados(self) -> None:
        nomes = {s.nome for s in vm.SONDAS}

        assert nomes == {
            "rota_aparelho_infinitivo",
            "rede_sem_bridge",
            "estado_contraditorio",
            "inventario_fora_da_raiz",
        }
        for sonda in vm.SONDAS:
            for arq in sonda.arquivos:
                assert (vm.RAIZ / arq).exists(), (sonda.nome, arq)

    def test_ancoras_estao_no_codigo_ou_o_reparo_sabe_consertar(self) -> None:
        """Se alguém refatorar os blocos ancorados sem o vigia saber,
        este teste falha NO GATE (em vez de o vigia acordar às 04:30 com
        uma sonda vermelha e nenhuma estratégia aplicável)."""
        for sonda in vm.SONDAS:
            if not sonda.vermelha():
                continue
            rep = sonda.reparo()
            assert rep["status"] == "aplicado", (sonda.nome, rep)


# ---------------------------------------------------------------------------
# Sonda 3 — estado contradito vira "✅ executado" (core/intents.py)
# ---------------------------------------------------------------------------


class TestSondaEstadoContraditorio:
    """'ligar' com estado lido 'off' não pode sair como ✅ executado."""

    @staticmethod
    def _format_antigo(action: str, data: dict) -> str:
        """O formato ANTES do conserto (26/10) — a mentira da auditoria
        23/10: deduz o estado da ação e imprime ✅ do mesmo jeito."""
        if not data.get("executed"):
            return ""
        estado = data.get("state_after") or (
            "on" if data.get("action") == "ligar" else "off")
        emoji = "🟢" if estado == "on" else "⚪"
        return (f"✅ {data.get('name')}: {data.get('action')} executado "
                f"({emoji} estado agora: {estado}).")

    @staticmethod
    def _format_com_assertiva_sem_leitura(action: str, data: dict) -> str:
        """Formato que afirma 'estado agora:' mesmo sem state_after."""
        if not data.get("executed"):
            return ""
        return "✅ Luz da Cozinha: ligar executado (🟢 estado agora: on)."

    def test_sonda_pega_o_estado_contrario_do_formato_antigo(self) -> None:
        """O payload contraditório da auditoria ('ligar' + 'off') deixa a
        sonda vermelha quando o formato é o de antes."""
        assert vm.SondaEstadoContraditorio().vermelha(
            self._format_antigo) is True

    def test_sonda_pega_assertiva_feita_sem_leitura(self) -> None:
        """Deduzir 'on' da ação (sem state_after) também é mentira."""
        assert vm.SondaEstadoContraditorio().vermelha(
            self._format_com_assertiva_sem_leitura) is True

    def test_sonda_verde_no_formato_de_hoje(self) -> None:
        assert vm.SondaEstadoContraditorio().vermelha() is False

    def test_format_quebrado_ou_mudo_conta_como_vermelha(self) -> None:
        def _explode(action: str, data: dict) -> str:
            raise RuntimeError("sem intents")

        assert vm.SondaEstadoContraditorio().vermelha(_explode) is True
        assert vm.SondaEstadoContraditorio().vermelha(
            lambda action, data: None) is True  # sem resposta não há resposta

    def test_reparo_sobre_o_bloco_antigo_conserta(self) -> None:
        rep = vm.SondaEstadoContraditorio().reparo(
            conteudo=_blocos(vm._TROCAS_ESTADO))

        assert rep["status"] == "aplicado"
        texto = rep["arquivos"]["core/intents.py"]
        assert "estado_confirmado" in texto and "NÃO confirmou" in texto
        assert 'estado = data.get("state_after") or' not in texto
        assert vm.SondaEstadoContraditorio().confere_staged(texto) is True

    def test_reparo_com_ancora_sumida_vai_para_fila(self) -> None:
        rep = vm.SondaEstadoContraditorio().reparo(
            conteudo="# refatorado sem aviso\n")

        assert rep["status"] == "ancora_ausente"
        assert len(rep["faltando"]) == 1  # só a âncora C1

    def test_reparo_no_codigo_de_hoje_e_idempotente(self) -> None:
        """Hoje o formato já é honesto: sem_defeito (nunca âncora ausente
        — que seria fila às 04:30 sem conserto)."""
        sonda = vm.SondaEstadoContraditorio()

        assert sonda.reparo()["status"] == "sem_defeito"

    def test_confere_staged_rejeita_o_codigo_antigo(self) -> None:
        sonda = vm.SondaEstadoContraditorio()

        assert sonda.confere_staged(_blocos(vm._TROCAS_ESTADO)) is False
        assert sonda.confere_staged(
            _blocos(vm._TROCAS_ESTADO, novo=True)) is True

    def test_bloco_novo_e_o_que_esta_no_arquivo_real(self) -> None:
        """Âncoras conferidas contra o arquivo vivo: o lado novo está lá
        (sonda verde) e o antigo saiu (o conserto já foi aplicado)."""
        alvo = (vm.RAIZ / "core/intents.py").read_text(encoding="utf-8")

        assert _blocos(vm._TROCAS_ESTADO, novo=True) in alvo
        assert _blocos(vm._TROCAS_ESTADO) not in alvo

    def test_runner_do_coder_le_o_arquivo_staged(self, tmp_path) -> None:
        staged = tmp_path / "intents.py"
        runner = vm.SondaEstadoContraditorio().runner()

        staged.write_text(_blocos(vm._TROCAS_ESTADO, novo=True),
                          encoding="utf-8")
        assert runner(relpath="core/intents.py", staged_file=str(staged),
                      sandbox_dir=str(tmp_path), original_file="") is True

        staged.write_text(_blocos(vm._TROCAS_ESTADO), encoding="utf-8")
        assert runner(relpath="core/intents.py", staged_file=str(staged),
                      sandbox_dir=str(tmp_path), original_file="") is False


# ---------------------------------------------------------------------------
# Sonda 4 — inventário do Vigia fora da raiz (tools/actions/actions.py)
# ---------------------------------------------------------------------------


class TestSondaInventarioForaDaRaiz:
    """`network_hosts` só responde com NOME se achar o inventário.

    Defeito achado na prova viva de 26/10: fallback `parents[1]` =
    `tools/logs` (inexistente) e o od-core roda sem `OD_LOG_DIR` →
    inventário vazio em produção, resposta só com IP/MAC.
    """

    def test_sonda_verde_no_codigo_de_hoje(self) -> None:
        assert vm.SondaInventarioForaDaRaiz().vermelha() is False

    def test_sonda_pega_o_fallback_de_tools(self) -> None:
        """Fallback apontando para `tools/logs` = vermelha (o defeito de
        produção, reproduzido sem depender do ambiente)."""
        def dir_errado() -> Path:
            return vm.RAIZ / "tools" / "logs"

        assert vm.SondaInventarioForaDaRaiz().vermelha(dir_errado) is True

    def test_sonda_verde_quando_o_diretorio_e_a_raiz(self) -> None:
        def dir_certo() -> Path:
            return vm.RAIZ / "logs"

        assert vm.SondaInventarioForaDaRaiz().vermelha(dir_certo) is False

    def test_od_log_dir_vence_e_e_restaurado(self, monkeypatch,
                                             tmp_path) -> None:
        """Com `OD_LOG_DIR` no ambiente o probe não pode fingir vermelho —
        e a variável precisa voltar pro lugar depois."""
        monkeypatch.setenv("OD_LOG_DIR", str(tmp_path))

        assert vm.SondaInventarioForaDaRaiz().vermelha() is False
        assert Path(os.environ["OD_LOG_DIR"]) == tmp_path

    def test_probe_quebrado_conta_como_vermelha(self) -> None:
        def _explode() -> Path:
            raise RuntimeError("sem pathlib")

        assert vm.SondaInventarioForaDaRaiz().vermelha(_explode) is True

    def test_reparo_sobre_o_fallback_antigo_conserta(self) -> None:
        rep = vm.SondaInventarioForaDaRaiz().reparo(
            conteudo=_blocos(vm._TROCAS_INV))

        assert rep["status"] == "aplicado"
        texto = rep["arquivos"]["tools/actions/actions.py"]
        assert 'parents[2] / "logs"' in texto
        assert 'parents[1] / "logs"' not in texto
        assert vm.SondaInventarioForaDaRaiz().confere_staged(texto) is True

    def test_reparo_com_ancora_sumida_vai_para_fila(self) -> None:
        rep = vm.SondaInventarioForaDaRaiz().reparo(
            conteudo="# refatorado sem aviso\n")

        assert rep["status"] == "ancora_ausente"
        assert len(rep["faltando"]) == 1  # só a âncora D1

    def test_reparo_no_codigo_de_hoje_e_idempotente(self) -> None:
        """Hoje o fallback já é a raiz: sem_defeito (nunca âncora ausente
        — que seria fila às 04:30 sem conserto)."""
        sonda = vm.SondaInventarioForaDaRaiz()

        assert sonda.reparo()["status"] == "sem_defeito"

    def test_confere_staged_rejeita_o_codigo_antigo(self) -> None:
        sonda = vm.SondaInventarioForaDaRaiz()

        assert sonda.confere_staged(_blocos(vm._TROCAS_INV)) is False
        assert sonda.confere_staged(
            _blocos(vm._TROCAS_INV, novo=True)) is True

    def test_fallback_novo_e_o_que_esta_no_arquivo_real(self) -> None:
        """Âncoras conferidas contra o arquivo vivo: lado novo está lá e o
        antigo saiu (o conserto já está aplicado no disco)."""
        alvo = (vm.RAIZ / "tools/actions/actions.py").read_text(
            encoding="utf-8")

        assert _blocos(vm._TROCAS_INV, novo=True) in alvo
        assert _blocos(vm._TROCAS_INV) not in alvo

    def test_runner_do_coder_le_o_arquivo_staged(self, tmp_path) -> None:
        staged = tmp_path / "actions.py"
        runner = vm.SondaInventarioForaDaRaiz().runner()

        staged.write_text(_blocos(vm._TROCAS_INV, novo=True),
                          encoding="utf-8")
        assert runner(relpath="tools/actions/actions.py",
                      staged_file=str(staged), sandbox_dir=str(tmp_path),
                      original_file="") is True

        staged.write_text(_blocos(vm._TROCAS_INV), encoding="utf-8")
        assert runner(relpath="tools/actions/actions.py",
                      staged_file=str(staged), sandbox_dir=str(tmp_path),
                      original_file="") is False


# ---------------------------------------------------------------------------
# Utilitários: git, gate, aviso, janela
# ---------------------------------------------------------------------------


class TestUtilitarios:
    def test_arquivos_limpos_olha_o_porcelain(self, monkeypatch) -> None:
        monkeypatch.setattr(vm, "_git", lambda *a, **k: (0, ""))
        assert vm._arquivos_limpos(("core/intents.py",)) is True

        monkeypatch.setattr(vm, "_git", lambda *a, **k: (0, " M core/intents.py"))
        assert vm._arquivos_limpos(("core/intents.py",)) is False

    def test_commitar_ordena_add_commit_push(self, monkeypatch) -> None:
        chamadas: list[str] = []
        monkeypatch.setattr(
            vm, "_git",
            lambda *a, **k: (chamadas.append(a[0]), (0, ""))[1])

        assert vm._commitar("vigia: conserto", ["core/intents.py"]) is True
        assert chamadas == ["add", "commit", "push"]

    def test_commitar_aborta_no_primeiro_erro(self, monkeypatch) -> None:
        def fake_git(*args: str, **kwargs: Any) -> tuple[int, str]:
            return (1, "deu ruim") if args[0] == "commit" else (0, "")

        monkeypatch.setattr(vm, "_git", fake_git)
        assert vm._commitar("msg", ["a.py"]) is False

    def test_rollback_e_checkout_dos_arquivos_alvo(self, monkeypatch) -> None:
        registrado: dict[str, Any] = {}

        def fake_git(*args: str, **kwargs: Any) -> tuple[int, str]:
            registrado["args"] = args
            return (0, "")

        monkeypatch.setattr(vm, "_git", fake_git)
        assert vm._rollback(["core/intents.py"]) is True
        assert registrado["args"] == ("checkout", "--", "core/intents.py")

    def test_rodar_gate_interpreta_o_codigo_de_saida(self, monkeypatch) -> None:
        class _Proc:
            def __init__(self, rc: int) -> None:
                self.returncode = rc
                self.stdout = ".....\n3790 passed, 16 skipped in 210s\n"
                self.stderr = ""

        monkeypatch.setattr(vm.subprocess, "run", lambda *a, **k: _Proc(0))
        verde, cauda = vm._rodar_gate(timeout=5)
        assert verde is True and "3790 passed" in cauda

        monkeypatch.setattr(vm.subprocess, "run", lambda *a, **k: _Proc(1))
        verde, _ = vm._rodar_gate(timeout=5)
        assert verde is False

    def test_fila_do_auditor_somente_problemas(self) -> None:
        auditoria = {"resultados": [
            {"veredito": "ok", "quando": "x", "pergunta": "a", "juiz": "g"},
            {"veredito": "resposta_errada", "quando": "y",
             "pergunta": "b", "juiz": "g"},
            {"veredito": "inconsistente", "quando": "z",
             "pergunta": "c", "juiz": "g"},
        ]}
        fila = vm._fila_do_auditor(auditoria)

        assert len(fila) == 2
        assert all(f["origem"] == "auditoria" for f in fila)
        assert "determinístico" in fila[0]["motivo"]
        assert fila[0]["veredito"] == "resposta_errada"

    def test_auditar_janela_sem_turnos_nao_levanta(self, monkeypatch) -> None:
        from core import chat_audit as ca

        monkeypatch.setattr(ca, "carregar_turnos_cascata",
                            lambda **kw: ([], "vazia"))
        relatorio = vm._auditar_janela(24.0)

        assert relatorio["fonte"] == "vazia"
        assert relatorio["turnos"] == 0
        assert relatorio["erro"] == ""

    def test_resumo_telegram_cobre_conserto_fila_e_gate(self) -> None:
        relatorio = {
            "auditoria": {"janela_horas": 24.0, "turnos": 12, "fonte": "postgres",
                          "problematicos": 2, "contagens": {"ok": 10,
                                                            "resposta_errada": 2}},
            "aplicados": [{"sonda": "rota_aparelho_infinitivo",
                           "arquivos": ["core/intents.py"]}],
            "gate": {"executado": True, "verde": True, "saida": ""},
            "commit": {"feito": True},
            "reinicio": {"feito": True},
            "fila": [{"sonda": "x", "motivo": "sem estratégia"}],
        }
        texto = vm._resumo_telegram(relatorio)

        assert "Consertado sozinho: rota_aparelho_infinitivo" in texto
        assert "Gate: verde" in texto
        assert "od-core reiniciado" in texto
        assert "Fila de conserto (1)" in texto


# ---------------------------------------------------------------------------
# Orquestração (com sondas e efeitos falsos — nada de git/Telegram reais)
# ---------------------------------------------------------------------------


class _SondaFalsa(vm.Sonda):
    """Sonda de teste: estado e reparo programáveis."""

    nome = "falsa"
    classe = "teste"
    arquivos = ("arquivo/falso.py",)
    descricao = "sonda falsa de teste"

    def __init__(self, vermelha: bool = True,
                 rep: Optional[dict[str, Any]] = None) -> None:
        self._vermelha = vermelha
        self._rep = rep if rep is not None else {"status": "sem_defeito"}

    def vermelha(self, *args: Any, **kwargs: Any) -> bool:
        return self._vermelha

    def reparo(self, conteudo: Optional[str] = None) -> dict[str, Any]:
        return self._rep

    def confere_staged(self, texto: str) -> bool:
        return True


def _base(monkeypatch, tmp_path, *, sonda: _SondaFalsa,
          problema: int = 0) -> None:
    """Monta o cenário: RAIZ no tmp, auditoria falsa, sonda falsa."""
    monkeypatch.setattr(vm, "RAIZ", tmp_path)
    monkeypatch.setattr(vm, "SONDAS", (sonda,))
    monkeypatch.setattr(vm, "_auditar_janela", lambda horas: {
        "fonte": "postgres", "turnos": 10, "problematicos": problema,
        "janela_horas": horas, "contagens": {"ok": 10 - problema,
                                             "resposta_errada": problema},
        "resultados": [{"veredito": "resposta_errada", "quando": "x",
                        "pergunta": "define dia", "juiz": "g"}] * problema,
        "caminho": "", "erro": "",
    })


class TestOrquestracao:
    def test_seco_nao_toca_git_gate_nem_telegram(self, monkeypatch,
                                                 tmp_path) -> None:
        batidas: list[str] = []
        _base(monkeypatch, tmp_path,
              sonda=_SondaFalsa(vermelha=True,
                                rep={"status": "aplicado",
                                     "arquivos": {"a.py": "x"}}))
        monkeypatch.setattr(vm, "_git", lambda *a, **k: batidas.append("git"))
        monkeypatch.setattr(vm, "_rodar_gate",
                            lambda *a, **k: batidas.append("gate") or (True, ""))
        monkeypatch.setattr(vm, "_avisar", lambda t: batidas.append("aviso"))

        relatorio = asyncio_run(vm.rodar(horas=24.0, dry_run=True))

        assert relatorio["modo"] == "seco"
        assert batidas == []
        assert relatorio["aplicados"] == []
        assert relatorio["avisado"] is False

    @pytest.mark.asyncio
    async def test_reparo_verde_commita_e_reinicia(self, monkeypatch,
                                                    tmp_path) -> None:
        sonda = _SondaFalsa(rep={"status": "aplicado",
                                 "arquivos": {"a.py": "conteudo"}})
        _base(monkeypatch, tmp_path, sonda=sonda)
        monkeypatch.setattr(vm, "_arquivos_limpos", lambda arq: True)

        async def aplicar(s: Any, arquivos: dict[str, str]) -> list[str]:
            return sorted(arquivos)

        monkeypatch.setattr(vm, "_aplicar", aplicar)
        monkeypatch.setattr(vm, "_rodar_gate", lambda timeout=1500.0:
                            (True, "3790 passed"))
        monkeypatch.setattr(vm, "_commitar", lambda msg, arq: True)
        monkeypatch.setattr(vm, "_reiniciar_od_core", lambda espera=60.0: True)
        monkeypatch.setattr(vm, "_avisar", lambda texto: True)

        relatorio = await vm.rodar(horas=24.0)

        assert [a["sonda"] for a in relatorio["aplicados"]] == ["falsa"]
        assert relatorio["gate"]["verde"] is True
        assert relatorio["commit"]["feito"] is True
        assert relatorio["reinicio"]["feito"] is True
        assert relatorio["avisado"] is True

    @pytest.mark.asyncio
    async def test_gate_vermelho_faz_rollback_e_fila(self, monkeypatch,
                                                     tmp_path) -> None:
        sonda = _SondaFalsa(rep={"status": "aplicado",
                                 "arquivos": {"a.py": "conteudo"}})
        _base(monkeypatch, tmp_path, sonda=sonda)
        monkeypatch.setattr(vm, "_arquivos_limpos", lambda arq: True)

        async def aplicar(s: Any, arquivos: dict[str, str]) -> list[str]:
            return sorted(arquivos)

        monkeypatch.setattr(vm, "_aplicar", aplicar)
        monkeypatch.setattr(vm, "_rodar_gate", lambda timeout=1500.0:
                            (False, "2 failed"))
        desfiz: list[Any] = []

        async def falso_to_thread(func, *args):  # captura o rollback
            if func is vm._rollback:
                desfiz.extend(args[0])
                return True
            return func(*args)

        monkeypatch.setattr(vm.asyncio, "to_thread", falso_to_thread)

        relatorio = await vm.rodar(horas=24.0)

        assert relatorio["rollback"] is True
        assert relatorio["aplicados"] == []       # nada foi dado como feito
        assert desfiz == ["a.py"]
        assert any(f["origem"] == "gate" for f in relatorio["fila"])

    @pytest.mark.asyncio
    async def test_arquivo_sujo_vai_para_fila_e_nao_mexe(self, monkeypatch,
                                                         tmp_path) -> None:
        sonda = _SondaFalsa(rep={"status": "aplicado",
                                 "arquivos": {"a.py": "conteudo"}})
        _base(monkeypatch, tmp_path, sonda=sonda)
        monkeypatch.setattr(vm, "_arquivos_limpos", lambda arq: False)

        relatorio = await vm.rodar(horas=24.0)

        assert relatorio["aplicados"] == []
        assert any("sujo" in f["motivo"] for f in relatorio["fila"])

    @pytest.mark.asyncio
    async def test_ancora_ausente_vai_para_fila(self, monkeypatch,
                                                tmp_path) -> None:
        sonda = _SondaFalsa(rep={"status": "ancora_ausente",
                                 "faltando": ["A1"]})
        _base(monkeypatch, tmp_path, sonda=sonda)
        monkeypatch.setattr(vm, "_arquivos_limpos", lambda arq: True)

        relatorio = await vm.rodar(horas=24.0)

        assert relatorio["aplicados"] == []
        assert any("âncora" in f["motivo"] for f in relatorio["fila"])

    @pytest.mark.asyncio
    async def test_sem_reparo_somente_reporta(self, monkeypatch,
                                              tmp_path) -> None:
        _base(monkeypatch, tmp_path, sonda=_SondaFalsa(vermelha=True))
        chamado: list[str] = []

        async def aplicar(s: Any, arquivos: dict[str, str]) -> list[str]:
            chamado.append("aplicar")
            return []

        monkeypatch.setattr(vm, "_aplicar", aplicar)

        relatorio = await vm.rodar(horas=24.0, reparar=False)

        assert chamado == []
        assert any("--sem-reparo" in f["motivo"] for f in relatorio["fila"])

    @pytest.mark.asyncio
    async def test_problemas_do_juiz_entrar_na_fila_mesmo_sem_sonda(
            self, monkeypatch, tmp_path) -> None:
        _base(monkeypatch, tmp_path, sonda=_SondaFalsa(vermelha=False),
              problema=2)

        relatorio = await vm.rodar(horas=24.0, reparar=False)

        assert relatorio["aplicados"] == []
        assert len(relatorio["fila"]) == 2
        assert relatorio["auditoria"]["problematicos"] == 2

    def test_main_repasseia_os_modos(self, monkeypatch, capsys) -> None:
        recebido: dict[str, Any] = {}

        async def rodar_falsa(**kwargs: Any) -> dict[str, Any]:
            recebido.update(kwargs)
            return {"modo": "auditoria", "auditoria": {"turnos": 0,
                                                       "problematicos": 0},
                    "sondas": [], "aplicados": [], "fila": [],
                    "gate": {"verde": False}}

        monkeypatch.setattr(vm, "rodar", rodar_falsa)

        rc = vm.main(["--sem-reparo", "--sem-aviso", "--horas", "48"])

        assert rc == 0
        assert recebido["reparar"] is False
        assert recebido["aviso"] is False
        assert recebido["horas"] == 48.0
        assert "modo=auditoria" in capsys.readouterr().out


def asyncio_run(coro: Any) -> Any:
    """Roda o coro num teste síncrono (pytest-asyncio só marca async)."""
    import asyncio
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Defeitos achados pela PRIMEIRA EXECUÇÃO AO VIVO (26/10 11:23) e corrigidos
# ---------------------------------------------------------------------------


class TestCorrecoesDaExecucaoAoVivo:
    """A prova viva de 26/10 encontrou 2 defeitos do PRÓPRIO relatório
    (não do conserto) e 1 furo de higiene. Guardas para não voltarem:

      1. a re-sonda lia o CACHE de módulo (o processo já tinha importado
         `core/intents` antes do patch) e reportava "continua vermelha"
         — falso alarme; o gate, em subprocesso novo, estava verde;
      2. o JSON era gravado ANTES do aviso, então `avisado: False` era
         o default gravado enquanto o Telegram aceitava a mensagem;
      3. `.od_backups/` (cópias do Coder) entrava no `git status`.
    """

    def test_invalidar_modulos_descarrega_o_cache(self) -> None:
        import importlib
        import sys

        importlib.import_module("core.intents")  # popula o cache
        assert "core.intents" in sys.modules

        vm._invalidar_modulos(("core.intents",))

        assert "core.intents" not in sys.modules
        # volta a existir no próximo import (nada quebra no resto do job)
        assert importlib.import_module("core.intents") is not None

    def test_invalidar_modulos_preserva_o_que_nao_e_alvo(self) -> None:
        import sys

        vm._invalidar_modulos(("core.intents",))

        assert "core.logger" in sys.modules  # alheio ao alvo, intocado

    @pytest.mark.asyncio
    async def test_prova_pos_reparo_invalida_cache_antes(self,
                                                         monkeypatch,
                                                         tmp_path) -> None:
        class _SondaCache(_SondaFalsa):
            modulos = ("core.intents",)

            def __init__(self) -> None:
                super().__init__(vermelha=True)
                self.provas: list[str] = []

            def vermelha(self, *args: Any, **kwargs: Any) -> bool:
                self.provas.append("prova")
                return len(self.provas) == 1  # vermelha antes, verde depois

        sonda = _SondaCache()
        sonda._rep = {"status": "aplicado", "arquivos": {"a.py": "x"}}
        _base(monkeypatch, tmp_path, sonda=sonda)
        invalidados: list[Any] = []
        monkeypatch.setattr(vm, "_invalidar_modulos",
                            lambda prefixos: invalidados.append(prefixos))
        monkeypatch.setattr(vm, "_arquivos_limpos", lambda arq: True)

        async def aplicar(s: Any, arquivos: dict[str, str]) -> list[str]:
            return sorted(arquivos)

        monkeypatch.setattr(vm, "_aplicar", aplicar)
        monkeypatch.setattr(vm, "_rodar_gate", lambda timeout=1500.0:
                            (True, "ok"))

        relatorio = await vm.rodar(horas=24.0)

        assert invalidados == [("core.intents",)]   # antes da re-sonda
        assert sonda.provas == ["prova", "prova"]
        assert relatorio["provas"] == [{"sonda": "falsa", "depois": "verde"}]
        assert relatorio["fila"] == []              # sem falso alarme

    @pytest.mark.asyncio
    async def test_relatorio_gravado_depois_do_aviso(self, monkeypatch,
                                                     tmp_path) -> None:
        """O JSON não pode mentir: `avisado` e o próprio caminho precisam
        estar DENTRO do arquivo gravado (o default False antes era falso)."""
        _base(monkeypatch, tmp_path, sonda=_SondaFalsa(vermelha=False),
              problema=1)
        monkeypatch.setattr(vm, "_avisar", lambda texto: True)

        relatorio = await vm.rodar(horas=24.0)

        gravado = json.loads(Path(relatorio["relatorio"]).read_text(
            encoding="utf-8"))
        assert gravado["avisado"] is True
        assert gravado["relatorio"] == relatorio["relatorio"]
        assert gravado["fila"] and gravado["auditoria"]["problematicos"] == 1

    @pytest.mark.asyncio
    async def test_aviso_falho_nao_derruba_o_ciclo(self, monkeypatch,
                                                   tmp_path) -> None:
        _base(monkeypatch, tmp_path, sonda=_SondaFalsa(vermelha=False),
              problema=1)
        monkeypatch.setattr(vm, "_avisar", lambda texto: False)

        relatorio = await vm.rodar(horas=24.0)

        assert relatorio["avisado"] is False
        assert relatorio["fila"]  # o problema segue registrado no relatório
