"""
OMEGA DRAKON • TESTS
Módulo: tests/test_os_updater.py
Descrição: Atualizador de SO (core/os_updater.py) — módulo entregue em
           10/11 com 231 stmts e 0% de cobertura. Cobre o ciclo completo
           apt + firmware com saídas fake, detecção de kernel/reboot,
           agendamento semanal/diário, persistência do estado em JSON,
           falhas e timeouts, o método `_reboot`, o `status()` e a CLI
           `main()` (inclusive a execução como script via `__main__`).

SEGURANÇA (regra absoluta desta suíte): NENHUM comando de sistema roda.
  - Fixture autouse `sem_comandos_reais` troca `core.os_updater._executar`
    por um despacho falso que só REGISTRA as chamadas (nunca toca
    subprocess) — apt, fwupdmgr, systemctl e shutdown viram linhas num
    histórico em memória;
  - Fixture autouse `flag_reboot` substitui `_precisa_reboot` (leitura do
    /var/run/reboot-required) por flag controlável; o caminho REAL do
    arquivo é testado com um `Path` falso em `os_updater.Path`;
  - os testes do `_executar` REAL usam `dry_run=True` ou substituem
    `core.os_updater.subprocess` por um namespace falso — o módulo real de
    subprocess nunca é invocado;
  - o teste de script reexecuta o arquivo com `runpy` só depois de trocar
    `subprocess.run` global e de `chdir` para tmp_path;
  - estado (JSON) SEMPRE dentro de tmp_path — o `data/` do repo nunca é
    tocado (inclusive pela CLI, que usa o default `ESTADO_ARQUIVO`).

Estilo e fixtures seguem tests/test_task_queue.py (docstrings pt-BR,
tmp_path, asserts de comportamento).
"""

from __future__ import annotations

import io
import json
import runpy
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import os_updater
from core.os_updater import OSUpdater, OSUpdaterState

# Referências capturadas no import ANTES das fixtures autouse trocarem os
# atributos do módulo — apontam sempre para as funções originais.
_executar_real = os_updater._executar
_precisa_reboot_real = os_updater._precisa_reboot

# Saída esperada do `apt list --upgradable` fake (header + 2 pacotes +
# uma linha sem "/" que o parser tem de ignorar).
PACOTES_ESPERADOS = ["vim", "openssl"]
# Saída esperada do `fwupdmgr get-upgrades` fake: a linha indentada é
# descartada pelo parser, as demais (inclusive o cabeçalho) ficam.
FIRMWARE_ESPERADO = [
    "Informações sobre atualizações de firmware",
    "5678-efgh 1.2.3",
]


# ---------------------------------------------------------------------------
# Dublês
# ---------------------------------------------------------------------------


class _ExecucaoFalsa:
    """Despacho falso para `core.os_updater._executar`.

    Nunca roda comando real: devolve (exit_code, stdout, stderr) por
    chave de comando e registra cada chamada em `chamadas` (com `timeout`
    e `dry_run` recebidos) para os testes verificarem a ordem/argumentos.

    Chaves usadas em `falhas`/`timeouts` = dois primeiros tokens:
    "apt update", "apt list", "apt full-upgrade", "apt autoremove",
    "fwupdmgr refresh", "fwupdmgr get-upgrades", "fwupdmgr update",
    "uname -r", "systemctl reboot", "shutdown -r".
    """

    def __init__(self) -> None:
        self.chamadas: list[dict] = []
        self.kernel = "6.8.0-45-generic"
        # Se definido, o `apt full-upgrade` "instala" um kernel novo —
        # é assim que o teste simula mudança de kernel no meio do ciclo.
        self.kernel_apos_upgrade: str | None = None
        self.pacotes_brutos = [
            "vim/stable 2:9.0-5 amd64 [upgradable from: 2:8.2]",
            "openssl/stable 3.0.11 amd64 [upgradable from: 3.0.10]",
            "Nada para atualizar",  # sem "/" → o parser ignora
        ]
        self.firmware_bruto = (
            "Informações sobre atualizações de firmware\n"
            "  - detalhe indentado (o parser descarta)\n"
            "5678-efgh 1.2.3\n"
        )
        self.falhas: set[str] = set()
        self.timeouts: set[str] = set()

    def __call__(
        self, cmd: list[str], timeout: int = 600, dry_run: bool = False
    ) -> tuple[int, str, str]:
        self.chamadas.append(
            {"cmd": list(cmd), "timeout": timeout, "dry_run": dry_run}
        )
        if dry_run:  # mesmo atalho do _executar real
            return 0, f"[DRY-RUN] {' '.join(cmd)}", ""

        chave = " ".join(cmd[:2])
        if chave in self.timeouts:
            return -1, "", f"Timeout após {timeout}s"
        if chave in self.falhas:
            return self._falha(chave)

        if chave == "uname -r":
            return 0, self.kernel + "\n", ""
        if chave == "apt list":
            saida = "Listing... Done\n" + "\n".join(self.pacotes_brutos) + "\n"
            return 0, saida, ""
        if chave == "apt update":
            return 0, "Todos os pacotes estão atualizados.\n", ""
        if chave == "apt full-upgrade":
            if self.kernel_apos_upgrade:
                self.kernel = self.kernel_apos_upgrade
            return 0, "2 pacotes atualizados\n", ""
        if chave == "apt autoremove":
            return 0, "0 pacotes removidos\n", ""
        if chave == "fwupdmgr refresh":
            return 0, "Downloading succeeded\n", ""
        if chave == "fwupdmgr get-upgrades":
            return 0, self.firmware_bruto, ""
        if chave == "fwupdmgr update":
            return 0, "Nenhuma atualização aplicada\n", ""
        if chave == "systemctl reboot":
            return 0, "", ""
        if chave == "shutdown -r":
            return 0, "Shutdown scheduled\n", ""
        return 0, "", ""

    @staticmethod
    def _falha(chave: str) -> tuple[int, str, str]:
        erros = {
            "uname -r": "uname: falhou",
            "apt list": "apt list: quebrou",
            "apt update": "E: Falha ao buscar repositório",
            "apt full-upgrade": "E: erro ao aplicar upgrade",
            "apt autoremove": "E: autoremove falhou",
            "fwupdmgr refresh": "fwupd: refresh falhou",
            "fwupdmgr get-upgrades": "fwupd: sem daemon",
            "fwupdmgr update": "fwupd: update falhou",
            "systemctl reboot": "Failed to start reboot",
            "shutdown -r": "shutdown recusado",
        }
        return -1, "", erros.get(chave, f"falha em {chave}")


class _FlagReboot:
    """Substitui `core.os_updater._precisa_reboot` (flag controlável)."""

    def __init__(self, pendente: bool = False) -> None:
        self.pendente = pendente

    def __call__(self) -> bool:
        return self.pendente


class _NotificadorFalso:
    """Notificador Telegram dublê: guarda mensagens ou simula indisponível."""

    def __init__(self, falhar: bool = False) -> None:
        self.mensagens: list[str] = []
        self.falhar = falhar

    def __call__(self, mensagem: str) -> None:
        self.mensagens.append(mensagem)
        if self.falhar:
            raise RuntimeError("Telegram indisponível")


# ---------------------------------------------------------------------------
# Fixtures de segurança (autouse: valem para TODO arquivo)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def sem_comandos_reais(monkeypatch) -> _ExecucaoFalsa:
    """Nenhum comando de sistema sai daqui vivo.

    Troca `core.os_updater._executar` pelo despacho falso: apt, fwupdmgr,
    uname, systemctl e shutdown só viram registros em memória.
    """
    falso = _ExecucaoFalsa()
    monkeypatch.setattr(os_updater, "_executar", falso)
    return falso


@pytest.fixture(autouse=True)
def flag_reboot(monkeypatch) -> _FlagReboot:
    """Controla `_precisa_reboot` sem ler o /var/run real do sistema."""
    flag = _FlagReboot()
    monkeypatch.setattr(os_updater, "_precisa_reboot", flag)
    return flag


@pytest.fixture(autouse=True)
def log_do_modulo():
    """Desvia o logger do módulo para StringIO.

    O NickyLogger escreve no stream capturado na criação (mesma armadilha
    documentada em tests/test_api.py) — sem o desvio, os `log.info` do
    ciclo poluiriam o stdout que `main()` usa para imprimiR o JSON e um
    stream velho de teste anterior poderia quebrar a escrita.
    """
    buffer = io.StringIO()
    stream_original = os_updater.log._stream
    os_updater.log.set_stream(buffer)
    yield buffer
    os_updater.log.set_stream(stream_original)


@pytest.fixture()
def estado_path(tmp_path: Path) -> Path:
    """Caminho do estado JSON — SEMPRE dentro de tmp_path, nunca data/."""
    return tmp_path / "os_updater_estado.json"


def _novo_updater(estado: Path, **kwargs) -> OSUpdater:
    """Cria o updater apontando o estado para tmp_path (regra da casa)."""
    kwargs.setdefault("estado_arquivo", estado)
    return OSUpdater(**kwargs)


def _json_no_stdout(saida: str) -> dict:
    """Extrai o JSON impresso por `main()` (o logger pode misturar linhas)."""
    linhas = saida.splitlines()
    inicio = linhas.index("{")
    return json.loads("\n".join(linhas[inicio:]))


def _comandos(execucao: _ExecucaoFalsa) -> list[str]:
    """Histórico de chamadas como strings ("apt update", "uname -r"...)."""
    return [" ".join(c["cmd"]) for c in execucao.chamadas]


# ---------------------------------------------------------------------------
# _executar (função real — dry_run ou subprocess substituído)
# ---------------------------------------------------------------------------


class TestExecutarReal:
    def test_dry_run_nunca_toca_subprocess(self, monkeypatch) -> None:
        """dry_run devolve o atalho sem invocar subprocess algum."""
        monkeypatch.setattr(
            os_updater,
            "subprocess",
            SimpleNamespace(
                run=lambda *a, **k: pytest.fail("subprocess não pode rodar"),
                TimeoutExpired=subprocess.TimeoutExpired,
            ),
        )
        code, out, err = _executar_real(["apt", "update"], dry_run=True)
        assert code == 0
        # O atalho loga a lista de argumentos como repr.
        assert out == "[DRY-RUN] ['apt', 'update']"
        assert err == ""

    def test_sucesso_passa_env_nao_interativo(
        self, monkeypatch
    ) -> None:
        """exit/stdout/stderr viram a tupla; apt roda com DEBIAN_FRONTEND."""
        capturado: dict = {}

        def run_falso(cmd, **kwargs):
            capturado["cmd"] = list(cmd)
            capturado.update(kwargs)
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        monkeypatch.setattr(
            os_updater,
            "subprocess",
            SimpleNamespace(run=run_falso,
                            TimeoutExpired=subprocess.TimeoutExpired),
        )
        code, out, err = _executar_real(["apt", "update"], timeout=30)
        assert (code, out, err) == (0, "ok", "")
        assert capturado["cmd"] == ["apt", "update"]
        assert capturado["timeout"] == 30
        assert capturado["capture_output"] is True
        assert capturado["text"] is True
        assert capturado["env"]["DEBIAN_FRONTEND"] == "noninteractive"

    def test_timeout_vira_menos_um_com_mensagem(self, monkeypatch) -> None:
        """TimeoutExpired → (-1, "", "Timeout após Ns") — sem exceção."""
        def run_falso(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=42)

        monkeypatch.setattr(
            os_updater,
            "subprocess",
            SimpleNamespace(run=run_falso,
                            TimeoutExpired=subprocess.TimeoutExpired),
        )
        code, out, err = _executar_real(["apt", "full-upgrade"], timeout=42)
        assert (code, out) == (-1, "")
        assert err == "Timeout após 42s"

    def test_erro_inesperado_vira_mensagem(self, monkeypatch) -> None:
        """Qualquer exceção vira (-1, "", "Tipo: mensagem")."""
        def run_falso(cmd, **kwargs):
            raise FileNotFoundError("comando nao encontrado")

        monkeypatch.setattr(
            os_updater,
            "subprocess",
            SimpleNamespace(run=run_falso,
                            TimeoutExpired=subprocess.TimeoutExpired),
        )
        code, out, err = _executar_real(["fwupdmgr", "get-upgrades"])
        assert (code, out) == (-1, "")
        assert err == "FileNotFoundError: comando nao encontrado"


# ---------------------------------------------------------------------------
# Helpers de sistema (funções reais + _executar falso)
# ---------------------------------------------------------------------------


class TestHelpersDeSistema:
    def test_kernel_atual_retorna_versao(self) -> None:
        assert os_updater._kernel_atual() == "6.8.0-45-generic"

    def test_kernel_atual_com_falha_devolve_vazio(
        self, sem_comandos_reais: _ExecucaoFalsa
    ) -> None:
        sem_comandos_reais.falhas.add("uname -r")
        assert os_updater._kernel_atual() == ""

    def test_lista_upgradable_pula_header_e_ignora_linha_sem_barra(
        self, sem_comandos_reais: _ExecucaoFalsa
    ) -> None:
        pacotes = os_updater._apt_lista_upgradable()
        assert pacotes == PACOTES_ESPERADOS
        # Só os helpers passam SEM dry_run (o flag é do updater).
        assert sem_comandos_reais.chamadas[-1]["cmd"] == [
            "apt", "list", "--upgradable",
        ]

    def test_lista_upgradable_com_falha_devolve_vazio(
        self, sem_comandos_reais: _ExecucaoFalsa
    ) -> None:
        sem_comandos_reais.falhas.add("apt list")
        assert os_updater._apt_lista_upgradable() == []

    def test_fwupdmgr_upgrades_filtra_linhas_indentadas(
        self, sem_comandos_reais: _ExecucaoFalsa
    ) -> None:
        upgrades = os_updater._fwupdmgr_upgrades()
        assert upgrades == FIRMWARE_ESPERADO

    def test_fwupdmgr_upgrades_com_falha_devolve_vazio(
        self, sem_comandos_reais: _ExecucaoFalsa
    ) -> None:
        sem_comandos_reais.falhas.add("fwupdmgr get-upgrades")
        assert os_updater._fwupdmgr_upgrades() == []

    def test_precisa_reboot_real_lê_o_flag_do_sistema(
        self, monkeypatch
    ) -> None:
        """O `_precisa_reboot` de verdade só consulta o /var/run — com um
        `Path` falso (nunca o filesystem real) nos dois estados."""
        path_real = os_updater.Path

        def _path_com_flag(existe: bool):
            def fake(caminho):
                if str(caminho) == "/var/run/reboot-required":
                    return SimpleNamespace(exists=lambda: existe)
                return path_real(caminho)
            return fake

        monkeypatch.setattr(os_updater, "Path", _path_com_flag(True))
        assert _precisa_reboot_real() is True

        monkeypatch.setattr(os_updater, "Path", _path_com_flag(False))
        assert _precisa_reboot_real() is False


# ---------------------------------------------------------------------------
# Estado persistido (JSON em tmp_path)
# ---------------------------------------------------------------------------


class TestEstadoPersistido:
    def test_estado_padrao_sem_arquivo(self, estado_path: Path) -> None:
        up = _novo_updater(estado_path)
        assert up._estado == OSUpdaterState()
        # Só LE no __init__: nada gravado ainda.
        assert not estado_path.exists()

    def test_estado_corrompido_vira_padrao(self, tmp_path: Path) -> None:
        """JSON inválido não derruba o updater: cai no estado default."""
        arq = tmp_path / "quebrado.json"
        arq.write_text("{isso nao e json", encoding="utf-8")
        up = _novo_updater(arq)
        assert up._estado.ultima_execucao == 0.0
        assert up._estado.secoes == []
        assert up._estado.pendente_reboot is False

    def test_roundtrip_salva_e_recarrega(self, estado_path: Path) -> None:
        up = _novo_updater(estado_path)
        up._estado.sucessos_consecutivos = 4
        up._estado.pendente_reboot = True
        up._estado.ultima_versao_kernel = "6.8.0-45"
        up._registrar_secao("apt_update", True, "ok")

        # Instância nova (como num restart) lê o que ficou no disco.
        nova = _novo_updater(estado_path)
        assert nova._estado.sucessos_consecutivos == 4
        assert nova._estado.pendente_reboot is True
        assert nova._estado.ultima_versao_kernel == "6.8.0-45"
        assert len(nova._estado.secoes) == 1
        assert nova._estado.secoes[0]["acao"] == "apt_update"

        dados = json.loads(estado_path.read_text(encoding="utf-8"))
        assert dados["sucessos_consecutivos"] == 4
        # Gravação atômica: o .tmp não sobra para trás.
        assert not estado_path.with_suffix(".tmp").exists()

    def test_salvar_estado_cria_diretorios_profundos(
        self, tmp_path: Path
    ) -> None:
        arq = tmp_path / "sub" / "profundo" / "estado.json"
        up = _novo_updater(arq)
        up._salvar_estado()
        assert arq.exists()
        assert not arq.with_suffix(".tmp").exists()

    def test_to_dict_mantem_ultimas_50_secoes(self) -> None:
        """Retenção: o histórico em disco nunca passa de 50 seções."""
        estado = OSUpdaterState(secoes=[{"i": i} for i in range(60)])
        dados = estado.to_dict()
        assert len(dados["secoes"]) == 50
        assert dados["secoes"][0]["i"] == 10
        assert dados["secoes"][-1]["i"] == 59
        assert dados["sucessos_consecutivos"] == 0
        assert dados["pendente_reboot"] is False

    def test_from_dict_ignora_chaves_desconhecidas(self) -> None:
        estado = OSUpdaterState.from_dict(
            {"sucessos_consecutivos": 7, "chave_misteriosa": "x"}
        )
        assert estado.sucessos_consecutivos == 7
        assert not hasattr(estado, "chave_misteriosa")

    def test_registrar_secao_trunca_detalhes_em_500(
        self, estado_path: Path
    ) -> None:
        up = _novo_updater(estado_path)
        up._registrar_secao("apt_upgrade", True, "d" * 600)
        secao = up._estado.secoes[-1]
        assert secao["acao"] == "apt_upgrade"
        assert secao["ok"] is True
        assert len(secao["detalhes"]) == 500
        assert "timestamp" in secao

    def test_notificador_recebe_titulo_e_corpo(
        self, estado_path: Path
    ) -> None:
        notif = _NotificadorFalso()
        up = _novo_updater(estado_path, notificador_telegram=notif)
        up._notificar("🔧 OSUpdater", "corpo")
        assert notif.mensagens == ["🔧 OSUpdater\ncorpo"]

    def test_notificador_quebrado_nao_derruba(
        self, tmp_path: Path
    ) -> None:
        """Telegram fora do ar não pode derrubar o ciclo (log.warn)."""
        up = _novo_updater(
            tmp_path / "a.json",
            notificador_telegram=_NotificadorFalso(falhar=True),
        )
        up._notificar("título", "corpo")  # não levanta

        # Sem notificador também é no-op.
        _novo_updater(tmp_path / "b.json")._notificar("título", "corpo")


# ---------------------------------------------------------------------------
# Agendamento (weekly/daily) e portas do executar_ciclo
# ---------------------------------------------------------------------------


class TestAgendamento:
    def test_primeira_execucao_sempre_roda(
        self, estado_path: Path, sem_comandos_reais: _ExecucaoFalsa
    ) -> None:
        """Sem histórico (ultima_execucao == 0) o ciclo roda SEM --forcar."""
        up = _novo_updater(estado_path, schedule="weekly")
        resultado = up.executar_ciclo()
        assert "apt_update" in resultado  # ciclo completo, não "aguardar"
        assert resultado["apt_update"] is True

    def test_deve_executar_semanal(self, estado_path: Path) -> None:
        """weekly: só domingo (day=6) a partir das 03:00, 1x por dia."""
        up = _novo_updater(estado_path, schedule="weekly", day=6, hour=3)

        # Nunca executou → roda.
        up._estado.ultima_execucao = 0.0
        assert up._deve_executar(datetime(2026, 11, 15, 4, 0).timestamp())

        # Já executou neste domingo → espera a semana que vem.
        up._estado.ultima_execucao = datetime(2026, 11, 15, 4, 0).timestamp()
        assert not up._deve_executar(datetime(2026, 11, 15, 10, 0).timestamp())

        # Dia errado (segunda) → não roda.
        up._estado.ultima_execucao = datetime(2026, 11, 9, 4, 0).timestamp()
        assert not up._deve_executar(datetime(2026, 11, 16, 10, 0).timestamp())

        # Domingo, mas antes das 03:00 → ainda não é hora.
        up._estado.ultima_execucao = datetime(2026, 11, 14, 10, 0).timestamp()
        assert not up._deve_executar(datetime(2026, 11, 15, 2, 0).timestamp())

        # Domingo às 04:00 com última execução na semana anterior → roda.
        assert up._deve_executar(datetime(2026, 11, 15, 4, 0).timestamp())

    def test_deve_executar_diario(self, estado_path: Path) -> None:
        """daily: uma vez por data civil, mesmo que a hora já tenha passado."""
        up = _novo_updater(estado_path, schedule="daily", hour=3)
        segunda = datetime(2026, 11, 16, 10, 0).timestamp()

        # Última execução no dia anterior → roda.
        up._estado.ultima_execucao = datetime(2026, 11, 15, 3, 0).timestamp()
        assert up._deve_executar(segunda)

        # Mesmo dia → não repete.
        up._estado.ultima_execucao = datetime(2026, 11, 16, 3, 0).timestamp()
        assert not up._deve_executar(segunda)

        # Última execução "no futuro" (relógio reajustado) → não repete.
        up._estado.ultima_execucao = datetime(2026, 11, 17, 3, 0).timestamp()
        assert not up._deve_executar(segunda)

    def test_proxima_execucao_diaria(self, estado_path: Path) -> None:
        up = _novo_updater(estado_path, schedule="daily", hour=3)

        # Ainda não passou das 03:00 → hoje.
        prox = datetime.fromtimestamp(
            up._proxima_execucao(datetime(2026, 11, 15, 1, 0).timestamp())
        )
        assert (prox.year, prox.month, prox.day, prox.hour) == (2026, 11, 15, 3)

        # Já passou → amanhã.
        prox = datetime.fromtimestamp(
            up._proxima_execucao(datetime(2026, 11, 15, 5, 0).timestamp())
        )
        assert (prox.year, prox.month, prox.day, prox.hour) == (2026, 11, 16, 3)
        assert (prox.minute, prox.second, prox.microsecond) == (0, 0, 0)

    def test_proxima_execucao_semanal(self, estado_path: Path) -> None:
        up = _novo_updater(estado_path, schedule="weekly", day=6, hour=3)

        # Domingo antes das 03:00 → hoje às 03:00.
        prox = datetime.fromtimestamp(
            up._proxima_execucao(datetime(2026, 11, 15, 1, 0).timestamp())
        )
        assert (prox.year, prox.month, prox.day, prox.hour) == (2026, 11, 15, 3)

        # Domingo depois das 03:00 → daqui a 7 dias.
        prox = datetime.fromtimestamp(
            up._proxima_execucao(datetime(2026, 11, 15, 4, 0).timestamp())
        )
        assert (prox.year, prox.month, prox.day, prox.hour) == (2026, 11, 22, 3)

        # Segunda → próximo domingo.
        prox = datetime.fromtimestamp(
            up._proxima_execucao(datetime(2026, 11, 16, 10, 0).timestamp())
        )
        assert (prox.year, prox.month, prox.day, prox.hour) == (2026, 11, 22, 3)

        # day=0 (segunda) saindo de domingo → segunda que vem.
        segunda = _novo_updater(estado_path, schedule="weekly", day=0, hour=3)
        prox = datetime.fromtimestamp(
            segunda._proxima_execucao(datetime(2026, 11, 15, 4, 0).timestamp())
        )
        assert (prox.year, prox.month, prox.day, prox.hour) == (2026, 11, 16, 3)

    def test_ciclo_ag_quando_ja_executou(
        self, estado_path: Path, sem_comandos_reais: _ExecucaoFalsa
    ) -> None:
        """Sem --forcar e fora da janela: aguarda, sem NENHUM comando e
        sem tocar no arquivo de estado."""
        up = _novo_updater(estado_path, schedule="weekly", day=6, hour=3)
        up._estado.ultima_execucao = time.time()

        resultado = up.executar_ciclo()

        assert resultado["ok"] is True
        assert resultado["acao"] == "aguardar"
        assert resultado["proxima_execucao"] > time.time()
        assert sem_comandos_reais.chamadas == []
        assert not estado_path.exists()
        assert up._estado.ultima_tentativa == 0.0

    def test_forcar_ignora_o_agendamento(
        self, estado_path: Path, sem_comandos_reais: _ExecucaoFalsa
    ) -> None:
        up = _novo_updater(estado_path, schedule="weekly", day=6, hour=3)
        up._estado.ultima_execucao = time.time()

        resultado = up.executar_ciclo(forcar=True)

        assert resultado["apt_update"] is True
        assert sem_comandos_reais.chamadas  # ciclo rodou mesmo assim
        assert estado_path.exists()


# ---------------------------------------------------------------------------
# Ciclo completo (executar_ciclo)
# ---------------------------------------------------------------------------


class TestCicloCompleto:
    def test_ciclo_sucesso_sem_reboot(
        self,
        estado_path: Path,
        sem_comandos_reais: _ExecucaoFalsa,
    ) -> None:
        """Ciclo inteiro: ordem dos comandos, seções, estado e avisos."""
        notif = _NotificadorFalso()
        up = _novo_updater(estado_path, notificador_telegram=notif)

        resultado = up.executar_ciclo(forcar=True)

        # Resultado por passo.
        assert resultado["ok"] is True
        assert resultado["erros"] == []
        for passo in (
            "apt_update", "apt_upgrade", "apt_autoremove",
            "fwupdmgr_refresh", "fwupdmgr_update",
        ):
            assert resultado[passo] is True, passo
        assert resultado["pacotes_atualizados"] == PACOTES_ESPERADOS
        assert resultado["firmware_atualizados"] == FIRMWARE_ESPERADO
        assert resultado["kernel_antes"] == "6.8.0-45-generic"
        assert resultado["kernel_depois"] == "6.8.0-45-generic"
        assert resultado["reboot_necessario"] is False
        assert resultado["reboot_executado"] is False

        # Ordem exata do ciclo: kernel antes → apt → firmware → kernel depois.
        assert _comandos(sem_comandos_reais) == [
            "uname -r",
            "apt update",
            "apt list --upgradable",
            "apt full-upgrade -y",
            "apt autoremove -y",
            "fwupdmgr refresh",
            "fwupdmgr get-upgrades",
            "fwupdmgr update -y",
            "uname -r",
        ]
        assert all(c["dry_run"] is False for c in sem_comandos_reais.chamadas)
        # Timeouts específicos por etapa (o resto usa o default de 600s).
        assert sem_comandos_reais.chamadas[1]["timeout"] == 120   # apt update
        assert sem_comandos_reais.chamadas[3]["timeout"] == 1800  # full-upgrade
        assert sem_comandos_reais.chamadas[4]["timeout"] == 300   # autoremove
        assert sem_comandos_reais.chamadas[7]["timeout"] == 600   # fwupd -y

        # Estado persistido em tmp_path.
        dados = json.loads(estado_path.read_text(encoding="utf-8"))
        assert dados["sucessos_consecutivos"] == 1
        assert dados["falhas_consecutivas"] == 0
        assert dados["ultima_execucao"] > 0
        assert dados["ultima_tentativa"] > 0
        assert [s["acao"] for s in dados["secoes"]] == [
            "apt_update", "apt_upgrade", "apt_autoremove",
            "fwupdmgr_refresh", "fwupdmgr_update",
        ]
        assert all(s["ok"] for s in dados["secoes"])

        # Notificações: abertura + conclusão sem reboot.
        assert len(notif.mensagens) == 2
        assert "Iniciando atualização semanal" in notif.mensagens[0]
        assert "sem necessidade de reboot" in notif.mensagens[1]

    def test_ciclo_com_reboot_agendado_pela_flag(
        self,
        estado_path: Path,
        sem_comandos_reais: _ExecucaoFalsa,
        flag_reboot: _FlagReboot,
    ) -> None:
        """Flag /var/run ativa → agenda `shutdown -r +5` e limpa o pendente."""
        flag_reboot.pendente = True
        notif = _NotificadorFalso()
        up = _novo_updater(estado_path, notificador_telegram=notif)

        resultado = up.executar_ciclo(forcar=True)

        assert resultado["reboot_necessario"] is True
        assert resultado["reboot_executado"] is True
        assert "shutdown -r +5 OSUpdater: atualizações aplicadas" in _comandos(
            sem_comandos_reais
        )

        dados = json.loads(estado_path.read_text(encoding="utf-8"))
        # Reboot agendado: o pendente é resolvido e o momento fica registrado.
        assert dados["pendente_reboot"] is False
        assert dados["ultimo_reboot"] > 0
        assert dados["secoes"][-1]["acao"] == "reboot"
        assert dados["secoes"][-1]["detalhes"] == "agendado +5min"
        assert any("Reboot necessário" in m for m in notif.mensagens)

    def test_ciclo_dry_run_nunca_agenda_shutdown(
        self,
        estado_path: Path,
        sem_comandos_reais: _ExecucaoFalsa,
        flag_reboot: _FlagReboot,
    ) -> None:
        """dry_run: roda o ciclo em simulação, marca o reboot como PENDENTE
        e NUNCA emite shutdown (a regra de ouro da suíte)."""
        flag_reboot.pendente = True
        up = _novo_updater(estado_path, dry_run=True)

        resultado = up.executar_ciclo(forcar=True)

        assert resultado["reboot_necessario"] is True
        assert resultado["reboot_executado"] is False
        assert not any(
            c["cmd"][0] == "shutdown" for c in sem_comandos_reais.chamadas
        )
        # Passos apt/fwupd receberam o flag dry_run=True.
        apt_calls = [
            c for c in sem_comandos_reais.chamadas
            if c["cmd"][0] == "apt" and c["cmd"][1] != "list"
        ]
        assert apt_calls and all(c["dry_run"] for c in apt_calls)
        assert resultado["apt_update"] is True  # dry_run devolve exit 0

        dados = json.loads(estado_path.read_text(encoding="utf-8"))
        assert dados["pendente_reboot"] is True

    def test_mudanca_de_kernel_dispara_reboot(
        self,
        estado_path: Path,
        sem_comandos_reais: _ExecucaoFalsa,
    ) -> None:
        """Kernel novo no meio do ciclo (flag de arquivo ausente) também
        dispara o reboot — detecção por comparação antes/depois."""
        sem_comandos_reais.kernel_apos_upgrade = "6.8.0-49-generic"
        up = _novo_updater(estado_path)

        resultado = up.executar_ciclo(forcar=True)

        assert resultado["kernel_antes"] == "6.8.0-45-generic"
        assert resultado["kernel_depois"] == "6.8.0-49-generic"
        assert resultado["reboot_necessario"] is True
        assert resultado["reboot_executado"] is True
        assert any(c["cmd"][0] == "shutdown" for c in sem_comandos_reais.chamadas)

    def test_falha_no_apt_update_conta_como_falha(
        self,
        estado_path: Path,
        sem_comandos_reais: _ExecucaoFalsa,
    ) -> None:
        """update falho: erro reportado, seção marcada e contador de falhas
        sobe (zerando o de sucessos) — os demais passos seguem."""
        sem_comandos_reais.falhas.add("apt update")
        up = _novo_updater(estado_path)

        resultado = up.executar_ciclo(forcar=True)

        assert resultado["ok"] is False
        assert resultado["apt_update"] is False
        assert resultado["erros"] == [
            "apt update: E: Falha ao buscar repositório"
        ]
        assert resultado["apt_upgrade"] is True  # ciclo continua

        dados = json.loads(estado_path.read_text(encoding="utf-8"))
        assert dados["falhas_consecutivas"] == 1
        assert dados["sucessos_consecutivos"] == 0
        assert dados["secoes"][0]["acao"] == "apt_update"
        assert dados["secoes"][0]["ok"] is False
        assert "E: Falha ao buscar repositório" in dados["secoes"][0]["detalhes"]

    def test_falha_no_full_upgrade_conta_como_falha(
        self,
        estado_path: Path,
        sem_comandos_reais: _ExecucaoFalsa,
    ) -> None:
        sem_comandos_reais.falhas.add("apt full-upgrade")
        up = _novo_updater(estado_path)

        resultado = up.executar_ciclo(forcar=True)

        assert resultado["ok"] is False
        assert resultado["apt_upgrade"] is False
        assert resultado["erros"] == [
            "apt full-upgrade: E: erro ao aplicar upgrade"
        ]
        secoes = json.loads(estado_path.read_text())["secoes"]
        assert secoes[1]["acao"] == "apt_upgrade"
        assert secoes[1]["ok"] is False

    def test_timeout_no_fwupd_nao_quebra_o_ciclo(
        self,
        estado_path: Path,
        sem_comandos_reais: _ExecucaoFalsa,
    ) -> None:
        """Timeout do fwupd update vira seção com ok=False, mas NÃO entra
        em `erros` (comportamento real: só apt define ok do ciclo)."""
        sem_comandos_reais.timeouts.add("fwupdmgr update")
        up = _novo_updater(estado_path)

        resultado = up.executar_ciclo(forcar=True)

        assert resultado["fwupdmgr_update"] is False
        assert resultado["ok"] is True
        assert resultado["erros"] == []
        secoes = json.loads(estado_path.read_text())["secoes"]
        assert secoes[-1]["acao"] == "fwupdmgr_update"
        assert secoes[-1]["ok"] is False
        assert "Timeout após 600s" in secoes[-1]["detalhes"]

    def test_falha_no_autoremove_fica_na_secao_sem_falhar_o_ciclo(
        self,
        estado_path: Path,
        sem_comandos_reais: _ExecucaoFalsa,
    ) -> None:
        sem_comandos_reais.falhas.add("apt autoremove")
        up = _novo_updater(estado_path)

        resultado = up.executar_ciclo(forcar=True)

        assert resultado["apt_autoremove"] is False
        assert resultado["ok"] is True  # autoremove não derruba o ciclo
        secoes = json.loads(estado_path.read_text())["secoes"]
        assert secoes[2] == {
            **secoes[2],
            "acao": "apt_autoremove",
            "ok": False,
            "detalhes": "E: autoremove falhou",
        }

    def test_contadores_acumulam_entre_ciclos(
        self,
        estado_path: Path,
        sem_comandos_reais: _ExecucaoFalsa,
    ) -> None:
        """Falha → sucesso: o contador de sucessos zera o de falhas e
        vice-versa (persistindo entre "restarts" via arquivo)."""
        sem_comandos_reais.falhas.add("apt update")
        up = _novo_updater(estado_path)
        up.executar_ciclo(forcar=True)
        assert up._estado.falhas_consecutivas == 1
        assert up._estado.sucessos_consecutivos == 0

        sem_comandos_reais.falhas.clear()
        up.executar_ciclo(forcar=True)
        assert up._estado.sucessos_consecutivos == 1
        assert up._estado.falhas_consecutivas == 0
        # As seções das duas rodadas ficaram no mesmo arquivo.
        dados = json.loads(estado_path.read_text(encoding="utf-8"))
        assert len(dados["secoes"]) == 10

        # E um restart recupera os contadores do disco.
        assert _novo_updater(estado_path)._estado.sucessos_consecutivos == 1


# ---------------------------------------------------------------------------
# _reboot (método)
# ---------------------------------------------------------------------------


class TestReboot:
    def test_reboot_dry_run_nao_executa_nada(
        self,
        estado_path: Path,
        sem_comandos_reais: _ExecucaoFalsa,
    ) -> None:
        up = _novo_updater(estado_path, dry_run=True)
        ok, msg = up._reboot()
        assert ok is True
        assert "[DRY-RUN]" in msg
        assert sem_comandos_reais.chamadas == []  # nem systemctl, nem log.crit

    def test_reboot_real_chama_systemctl_e_notifica(
        self,
        estado_path: Path,
        sem_comandos_reais: _ExecucaoFalsa,
    ) -> None:
        notif = _NotificadorFalso()
        up = _novo_updater(estado_path, notificador_telegram=notif)

        ok, msg = up._reboot()

        assert ok is True
        ultima = sem_comandos_reais.chamadas[-1]
        assert ultima["cmd"] == ["systemctl", "reboot"]
        assert ultima["timeout"] == 30
        assert any("Reboot do sistema iniciado" in m for m in notif.mensagens)

    def test_reboot_real_com_falha_devolve_erro(
        self,
        estado_path: Path,
        sem_comandos_reais: _ExecucaoFalsa,
    ) -> None:
        sem_comandos_reais.falhas.add("systemctl reboot")
        up = _novo_updater(estado_path)

        ok, msg = up._reboot()

        assert ok is False
        assert "Failed to start reboot" in msg


# ---------------------------------------------------------------------------
# status()
# ---------------------------------------------------------------------------


class TestStatus:
    def test_status_expoe_agendamento_e_contadores(
        self,
        estado_path: Path,
        sem_comandos_reais: _ExecucaoFalsa,
        flag_reboot: _FlagReboot,
    ) -> None:
        up = _novo_updater(
            estado_path,
            schedule="daily", day=2, hour=7, window_hours=9, dry_run=True,
        )
        flag_reboot.pendente = True

        status = up.status()

        assert status["ok"] is True
        assert status["schedule"] == "daily"
        assert status["day"] == 2
        assert status["hour"] == 7
        assert status["window_hours"] == 9
        assert status["kernel_atual"] == "6.8.0-45-generic"
        assert status["precisa_reboot"] is True
        assert status["upgradable"] == len(PACOTES_ESPERADOS)
        assert status["firmware_upgrades"] == len(FIRMWARE_ESPERADO)
        assert status["dry_run"] is True
        assert status["ultima_execucao"] == 0.0
        assert status["ultima_tentativa"] == 0.0
        assert status["sucessos_consecutivos"] == 0
        assert status["falhas_consecutivas"] == 0
        assert status["pendente_reboot"] is False
        assert status["ultimo_reboot"] == 0.0
        assert isinstance(status["proxima_execucao"], float)
        assert status["proxima_execucao"] > 0
        # O status consulta o sistema (via _executar falso) sem executar ciclo.
        assert "uname -r" in _comandos(sem_comandos_reais)
        assert "apt list --upgradable" in _comandos(sem_comandos_reais)
        assert "fwupdmgr get-upgrades" in _comandos(sem_comandos_reais)


# ---------------------------------------------------------------------------
# CLI (main)
# ---------------------------------------------------------------------------


@pytest.fixture()
def estado_main(tmp_path: Path, monkeypatch) -> Path:
    """Redireciona o estado da CLI para tmp_path.

    `main()` constrói `OSUpdater(...)` sem `estado_arquivo`, ou seja, com o
    default `ESTADO_ARQUIVO` (relativo: `data/`). Um subclass injeta o
    caminho de tmp_path — o data/ do repo nunca vira alvo.
    """
    original = os_updater.OSUpdater

    class _OSUpdaterEmTmp(original):
        def __init__(self, **kwargs) -> None:
            kwargs.setdefault("estado_arquivo", tmp_path / "estado_main.json")
            super().__init__(**kwargs)

    monkeypatch.setattr(os_updater, "OSUpdater", _OSUpdaterEmTmp)
    return tmp_path / "estado_main.json"


class TestMain:
    def test_sem_argumentos_imprime_ajuda_e_falha(
        self, capsys, monkeypatch, estado_main: Path
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["od-os-updater"])
        assert os_updater.main() == 1
        assert "OSUpdater" in capsys.readouterr().out

    def test_status_via_cli(
        self, capsys, monkeypatch, estado_main: Path
    ) -> None:
        monkeypatch.setattr(
            sys, "argv",
            ["od-os-updater", "--status",
             "--schedule", "daily", "--day", "1", "--hour", "5"],
        )
        assert os_updater.main() == 0
        dados = _json_no_stdout(capsys.readouterr().out)
        assert dados["schedule"] == "daily"
        assert dados["day"] == 1
        assert dados["hour"] == 5
        assert dados["kernel_atual"] == "6.8.0-45-generic"
        assert dados["upgradable"] == len(PACOTES_ESPERADOS)

    def test_executar_dry_run_via_cli(
        self,
        capsys,
        monkeypatch,
        estado_main: Path,
        sem_comandos_reais: _ExecucaoFalsa,
    ) -> None:
        monkeypatch.setattr(
            sys, "argv", ["od-os-updater", "--executar", "--dry-run"]
        )
        assert os_updater.main() == 0
        dados = _json_no_stdout(capsys.readouterr().out)
        assert dados["ok"] is True
        assert dados["apt_update"] is True
        assert dados["pacotes_atualizados"] == PACOTES_ESPERADOS
        # dry_run: nenhum shutdown, e o estado foi para tmp_path.
        assert not any(
            c["cmd"][0] == "shutdown" for c in sem_comandos_reais.chamadas
        )
        assert estado_main.exists()

    def test_executar_com_falha_retorna_1(
        self,
        capsys,
        monkeypatch,
        estado_main: Path,
        sem_comandos_reais: _ExecucaoFalsa,
    ) -> None:
        sem_comandos_reais.falhas.add("apt update")
        monkeypatch.setattr(sys, "argv", ["od-os-updater", "--executar"])
        assert os_updater.main() == 1
        dados = _json_no_stdout(capsys.readouterr().out)
        assert dados["ok"] is False
        assert dados["erros"][0].startswith("apt update:")

    def test_forcar_via_cli(
        self,
        capsys,
        monkeypatch,
        estado_main: Path,
        sem_comandos_reais: _ExecucaoFalsa,
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["od-os-updater", "--forcar"])
        assert os_updater.main() == 0
        dados = _json_no_stdout(capsys.readouterr().out)
        assert dados["ok"] is True
        assert sem_comandos_reais.chamadas  # ciclo de verdade rodou (fake)
        assert estado_main.exists()

    def test_execucao_como_script_via_main_guard(
        self, capsys, monkeypatch, tmp_path: Path
    ) -> None:
        """Cobre o guard `if __name__ == "__main__"` (fim do módulo).

        O `run_path` cria um namespace NOVO — o `_executar` falso das
        fixtures não vale aqui. Por isso o teste troca o `subprocess.run`
        global por um falso E roda com cwd em tmp_path (o estado relativo
        `data/` do script cai dentro do tmp, nunca no repo).
        """
        falso = _ExecucaoFalsa()

        def run_falso(cmd, **kwargs):
            code, out, err = falso(list(cmd), timeout=kwargs.get("timeout", 600))
            return SimpleNamespace(returncode=code, stdout=out, stderr=err)

        monkeypatch.setattr(subprocess, "run", run_falso)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            sys, "argv", ["core.os_updater", "--executar", "--dry-run"]
        )

        with pytest.raises(SystemExit) as exc:
            runpy.run_path(str(Path(os_updater.__file__)), run_name="__main__")

        assert exc.value.code == 0
        dados = _json_no_stdout(capsys.readouterr().out)
        assert dados["ok"] is True
        assert dados["apt_update"] is True
        # Só os passos SEM dry_run chegam ao subprocess falso (uname/apt
        # list/fwupd get-upgrades); os apt/fwupd em simulação nem isso.
        assert any(c["cmd"][:2] == ["uname", "-r"] for c in falso.chamadas)
        assert any(
            c["cmd"][:2] == ["apt", "list"] for c in falso.chamadas
        )
        assert not any(c["cmd"][0] == "shutdown" for c in falso.chamadas)
        # Estado do script relativo → tmp_path/data/ (nunca o repo).
        assert (tmp_path / "data" / "os_updater_estado.json").exists()
