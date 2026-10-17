"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/nomad_tools.py
Descrição: Saúde das ferramentas do stack Nômade (DECISÃO FINAL 12/10) —
           as 8 ferramentas ativas do docker/tools-compose.yaml monitoradas
           pelo od-core (eram 9; o Homebox saiu do ar em 2026-10-17 por
           decisão do dono — "nada parado", análise a fundo das ferramentas
           pendentes é item de pauta). Antes desta peça (2026-10-15) nenhuma
           delas era observada: o Stirling PDF ficou 1.917 restarts em crash
           loop e o Kiwix 763 antes de alguém abrir o servidor — o alerta só
           chegou quando a falha já tinha dias.

           - `FERRAMENTAS_NOMAD`: catálogo fixo das 8 (nome, porta local,
             caminho, descrição) — portas conferidas no docker inspect
             (bind 127.0.0.1).
           - `NomadToolsMonitor`: sonda HTTP por ferramenta (stdlib puro,
             http.client) com cache TTL curto — o notifier (tick 60s) e o
             /health podem ler as 8 sem repetir rede dentro da janela.
             Semântica: status < 500 = viva (200/302/401 são vida — auth
             é sinal de serviço no ar); >= 500, timeout ou conexão
             recusada = fora.
           - Contrato do HealthMonitor (check por ferramenta,
             critical=False — nunca derruba o /health) e resumo para o
             /dashboard/stats + sonda do ProactiveNotifier (alerta no
             Telegram quando uma ferramenta cai, com emit_after_s para
             não gritar durante um `compose up` de 20s).
           - `OD_NOMAD_TOOLS=0` desliga (decidido no launcher, onde o
             .env é a fonte).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docker/tools-compose.yaml (as 8 ferramentas ativas)
  - docs/ANALISE_PROJECT_NOMAD.md § DECISÃO FINAL 12/10 ("integrar
    healthchecks dos tools no /health do OD")
  - observability/health.py (contrato de check não-crítico)
  - integrations/notifier.py (padrão das sondas _check_*)

Decisões registradas (ver CHANGELOG):
  - Probe HTTP em vez de `docker inspect` do health status: mede o
    SERVIÇO respondendo (o que importa pro dono), não o container
    "Up" — 4 ferramentas nem têm healthcheck no compose (Up não é
    "funcionando")
  - Status < 500 = viva: Calibre Web responde 302 na raiz (redirect do
    login) e Vaultwarden 401 em rota protegida — recusar esses seria
    alerta falso eterno
  - Cache TTL 10s: notifier e /health compartilham a mesma sondagem na
    janela — 8 probes/min no máximo, nunca 8 por leitura
  - emit_after_s 120 no notifier: um `docker compose up -d` legítimo
    derruba a porta por 10-30s; só persistência vira alerta
"""

from __future__ import annotations

import http.client
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.core.nomad_tools")

# Sondagem: porta fechada / timeout contam como "fora"; qualquer status
# HTTP < 500 é vida (auth-walled e redirect são serviço no ar).
TIMEOUT_PADRAO_S = 2.0
CACHE_TTL_S = 10.0

# Nome do check no /health por ferramenta (ex.: tool_kiwix).
PREFIXO_CHECK = "tool_"


@dataclass(frozen=True, slots=True)
class FerramentaNomad:
    """Uma ferramenta do stack Nômade monitorada.

    Attributes:
        nome:      Identificador estável (ex.: "stirling-pdf").
        porta:     Porta local em 127.0.0.1 (bind do compose).
        caminho:   Caminho da sonda (default "/").
        descricao: Texto curto para o painel.
    """

    nome: str
    porta: int
    caminho: str = "/"
    descricao: str = ""

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.porta}{self.caminho}"

    @property
    def nome_check(self) -> str:
        """Nome canônico no HealthMonitor (hífen vira underscore)."""
        return f"{PREFIXO_CHECK}{self.nome.replace('-', '_')}"


# As 8 ferramentas ativas da DECISÃO FINAL (portas conferidas no docker
# inspect — bind 127.0.0.1; caminhos medidos ao vivo em 15/10). O Homebox
# saiu em 17/10 (compose comentado — reativação em docker/tools-compose.yaml).
FERRAMENTAS_NOMAD: tuple[FerramentaNomad, ...] = (
    FerramentaNomad("kiwix", 8090, "/", "Wikipedia offline (ZIM 14,4 GB)"),
    FerramentaNomad("cyberchef", 8100, "/", "Data tools (~300 operações)"),
    FerramentaNomad("it-tools", 8430, "/", "Utilitários de dev"),
    FerramentaNomad("flatnotes", 8200, "/", "Caderno Markdown"),
    FerramentaNomad("stirling-pdf", 8400, "/", "50+ ferramentas de PDF"),
    FerramentaNomad("filebrowser", 8410, "/", "Arquivos na web"),
    FerramentaNomad("calibre-web", 8420, "/", "Biblioteca de e-books"),
    FerramentaNomad("vaultwarden", 8480, "/alive", "Cofre de senhas"),
)


def _sonda_http(host: str, porta: int, caminho: str, timeout_s: float) -> int:
    """GET na porta local; devolve o status HTTP. Erros de rede sobem."""
    conn = http.client.HTTPConnection(host, porta, timeout=timeout_s)
    try:
        conn.request(
            "GET", caminho, headers={"User-Agent": "OmegaDrakon-Health/1.0"}
        )
        resp = conn.getresponse()
        resp.read()  # consome o corpo — conexão fecha limpo
        return int(resp.status)
    finally:
        conn.close()


class NomadToolsMonitor:
    """Sondagem da saúde das ferramentas do stack Nômade.

    Uso típico:
        monitor = NomadToolsMonitor()
        monitor.registrar_no_health(health)      # /health, não-crítico
        CheckResult(ok=..., ...) = ...           # notifier (via launcher)
        monitor.resumo()                         # /dashboard/stats
    """

    def __init__(
        self,
        *,
        ferramentas: tuple[FerramentaNomad, ...] = FERRAMENTAS_NOMAD,
        host: str = "127.0.0.1",
        timeout_s: float = TIMEOUT_PADRAO_S,
        cache_ttl_s: float = CACHE_TTL_S,
        clock: Optional[Callable[[], float]] = None,
        sonda: Optional[Callable[[str, int, str, float], int]] = None,
    ) -> None:
        self.ferramentas = ferramentas
        self.host = host
        self.timeout_s = timeout_s
        self.cache_ttl_s = cache_ttl_s
        self._clock = clock or time.monotonic
        self._sonda = sonda or _sonda_http
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = threading.RLock()

    # -- Sondagem -------------------------------------------------------------

    def sondar(self, nome: str) -> dict[str, Any]:
        """Resultado da sonda de uma ferramenta (com cache TTL curto).

        Returns:
            dict {nome, ok, status, detail, latency_ms, url} — status é
            "up"/"down"; detail traz o porquê legível.
        """
        ferramenta = self._por_nome(nome)
        agora = self._clock()
        with self._lock:
            entrada = self._cache.get(nome)
        if entrada is not None and (agora - entrada[0]) <= self.cache_ttl_s:
            return entrada[1]
        resultado = self._sondar_sem_cache(ferramenta)
        with self._lock:
            self._cache[nome] = (self._clock(), resultado)
        return resultado

    def estado(self) -> list[dict[str, Any]]:
        """Sonda as 8 (ordem do catálogo), resultado por ferramenta."""
        return [self.sondar(f.nome) for f in self.ferramentas]

    def resumo(self) -> dict[str, Any]:
        """Contagem para /dashboard/stats: total, up e quem está fora."""
        resultados = self.estado()
        fora = [r["nome"] for r in resultados if not r["ok"]]
        return {
            "total": len(resultados),
            "up": len(resultados) - len(fora),
            "fora": fora,
        }

    def limpar_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    # -- Integrações ----------------------------------------------------------

    def check_saude(self, nome: str) -> Callable[[Any], dict[str, Any]]:
        """Check plugável no HealthMonitor (contrato dict ok/status/detail)."""

        def check(_monitor: Any = None) -> dict[str, Any]:
            resultado = self.sondar(nome)
            return {
                "ok": resultado["ok"],
                "status": "up" if resultado["ok"] else "degraded",
                "detail": resultado["detail"],
            }

        return check

    def registrar_no_health(self, health: Any) -> list[str]:
        """Registra as 8 ferramentas no /health (critical=False)."""
        nomes: list[str] = []
        for ferramenta in self.ferramentas:
            health.register(
                ferramenta.nome_check,
                self.check_saude(ferramenta.nome),
                critical=False,
            )
            nomes.append(ferramenta.nome_check)
        return nomes

    # -- Interno --------------------------------------------------------------

    def _por_nome(self, nome: str) -> FerramentaNomad:
        for ferramenta in self.ferramentas:
            if ferramenta.nome == nome:
                return ferramenta
        raise KeyError(f"ferramenta desconhecida: {nome}")

    def _sondar_sem_cache(
        self, ferramenta: FerramentaNomad
    ) -> dict[str, Any]:
        started = self._clock()
        base = {
            "nome": ferramenta.nome,
            "url": ferramenta.url,
        }
        try:
            status = self._sonda(
                self.host, ferramenta.porta, ferramenta.caminho,
                self.timeout_s,
            )
        except Exception as exc:  # porta fechada, timeout, DNS local...
            return {
                **base,
                "ok": False,
                "status": "down",
                "detail": (
                    f"{ferramenta.nome} fora ({type(exc).__name__}: "
                    f"{exc}) — {ferramenta.url}"
                ),
                "latency_ms": (self._clock() - started) * 1000.0,
            }
        vivo = status < 500
        return {
            **base,
            "ok": vivo,
            "status": "up" if vivo else "down",
            "detail": (
                f"{ferramenta.nome} ok (HTTP {status}) — {ferramenta.url}"
                if vivo
                else (
                    f"{ferramenta.nome} respondeu HTTP {status} — "
                    f"{ferramenta.url}"
                )
            ),
            "latency_ms": (self._clock() - started) * 1000.0,
        }


# Instância única do processo (od-core): launcher registra no health e
# injeta no notifier. Testes criam a própria (mesma linha de SUPERVISION).
_MONITOR: Optional[NomadToolsMonitor] = None
_MONITOR_LOCK = threading.Lock()


def monitor_padrao() -> NomadToolsMonitor:
    """Monitor único do processo atual."""
    global _MONITOR
    with _MONITOR_LOCK:
        if _MONITOR is None:
            _MONITOR = NomadToolsMonitor()
        return _MONITOR


def resetar_monitor() -> None:
    """Descarta a instância única — usado nos testes."""
    global _MONITOR
    with _MONITOR_LOCK:
        _MONITOR = None
