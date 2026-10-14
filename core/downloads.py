"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/downloads.py
Descrição: Fila de downloads resumable (Parte D do Project NOMAD) —
           retry com backoff exponencial, progresso ao vivo (SSE),
           dedup e cancelamento. Útil para modelos, datasets e
           documentos grandes (ZIM de 14 GB, pesos de modelo...).

Decisões de projeto (14/10 — ordem A → C → B → D do NOMAD):
- RESUMABLE de verdade: cada tentativa abre com `Range: bytes=N-` a
  partir do `.part` já gravado; servidor sem Range (200) reinicia do
  zero sozinho. O estado sobrevive a restart do serviço: um job que
  estava "baixando" volta para a fila no boot e o parcial continua em
  disco — nada de recomeçar 14 GB por causa de um deploy.
- RETRY com backoff: falha transitória (timeout, conexão, 5xx) reagenda
  com `backoff = min(base·2^(tentativa-1), cap)`; erro permanente (404,
  403, sha256 divergente) cai direto para `erro` sem queimar tentativa.
- DEDUP: enfileirar a mesma URL+destino com job ATIVO devolve o job
  existente — nunca dois workers disputando o mesmo arquivo.
- CANCELAMENTO: sinal por job conferido a cada bloco lido; cancelar no
  meio preserva o `.part` (re-enfileirar a mesma URL retoma).
- PROGRESSO AO VIVO: cada assinante leva uma fila própria
  (`subscribe()`), que alimenta o SSE GET /admin/downloads/events —
  um cliente lento nunca trava o worker ( evento que não cabe é
  descartado pelo mais antigo, e o `estado` final sempre sai).
- SEGURANÇA: destino sempre DENTRO de OD_DOWNLOADS_DIR (sem `..`, sem
  caminho absoluto) — a fila não vira um cliente genérico para fora.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import hashlib
import json
import os
import queue as queue_mod
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import unquote, urlsplit

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.core.downloads")

# Estados do job (pt-BR — o painel e o app mostram estes valores).
NA_FILA = "na_fila"
BAIXANDO = "baixando"
AGUARDANDO = "aguardando"   # na janela de backoff entre tentativas
CONCLUIDO = "concluido"
ERRO = "erro"
CANCELADO = "cancelado"
TERMINAIS = frozenset({CONCLUIDO, ERRO, CANCELADO})

# Transferência.
_CHUNK = 64 * 1024            # 64 KiB por leitura
_TIMEOUT_S = 30.0             # sem bloco novo em 30 s = falha transitória
_USER_AGENT = "OmegaDrakon/1.0 (fila-de-downloads)"

# Ritmo do progresso: evento SSE a cada 0,5 s; disco a cada 2 s
# (o `.part` é a fonte da verdade — gravar estado a cada bloco seria
# o mesmo O(n²) de I/O que o RAG pegou no add() unitário).
_PROGRESSO_S = 0.5
_PERSIST_S = 2.0

# Backoff entre tentativas: 2, 4, 8, 16, 32… limitado a 60 s.
_BACKOFF_BASE_S = 2.0
_BACKOFF_CAP_S = 60.0

# Histórico terminal guardado no estado (os arquivos NÃO são apagados).
_HISTORICO_MAX = 50

# 4xx transitórios (vale tentar de novo); demais 4xx = permanente.
_HTTP_RETENTAVEIS = frozenset({408, 425, 429})

# Raiz padrão da fila (sobrepõe por OD_DOWNLOADS_DIR no launcher).
_RAIZ_PADRAO = Path(__file__).resolve().parents[1] / "data" / "downloads"
_ESTADO_PADRAO = Path(__file__).resolve().parents[1] / "data" / "downloads_fila.json"


class _Cancelado(Exception):
    """Cancelamento pedido pelo dono no meio da transferência."""


class _Interrompido(Exception):
    """Stop() do serviço no meio do stream — o job volta para a fila."""


class _Permanente(Exception):
    """Falha que não resolve tentando de novo (404, sha256 divergente...)."""


class _Incompleto(Exception):
    """Stream acabou antes do total anunciado — transitória."""


@dataclass(slots=True)
class DownloadJob:
    """Um download enfileirado (ou em andamento, ou terminado)."""

    id: str
    url: str
    destino: str                 # caminho absoluto final (arquivo pronto)
    nome: str                    # nome do arquivo (exibição)
    status: str = NA_FILA
    bytes_feitos: int = 0
    bytes_total: int = -1        # -1 = o servidor não anunciou o tamanho
    tentativas: int = 0
    max_tentativas: int = 5
    erro: str = ""
    sha256: str = ""             # esperado (opcional — confere no fim)
    sha256_real: str = ""
    criado_em: float = 0.0
    atualizado_em: float = 0.0
    fim_em: Optional[float] = None
    proximo_retry: Optional[float] = None
    # Sinal de cancelamento: transiente, NUNCA persiste (no boot um job
    # cancelado já está com status terminal).
    cancelar: bool = False

    @property
    def ativo(self) -> bool:
        return self.status not in TERMINAIS

    @property
    def pct(self) -> Optional[float]:
        if self.bytes_total > 0:
            return round(min(1.0, self.bytes_feitos / self.bytes_total), 4)
        return None

    def para_dict(self) -> dict[str, Any]:
        """Payload JSON (sem o sinal transiente de cancelamento)."""
        return {
            "id": self.id,
            "url": self.url,
            "destino": self.destino,
            "nome": self.nome,
            "status": self.status,
            "bytes_feitos": self.bytes_feitos,
            "bytes_total": self.bytes_total,
            "pct": self.pct,
            "tentativas": self.tentativas,
            "max_tentativas": self.max_tentativas,
            "erro": self.erro,
            "sha256": self.sha256,
            "sha256_real": self.sha256_real,
            "criado_em": self.criado_em,
            "atualizado_em": self.atualizado_em,
            "fim_em": self.fim_em,
            "proximo_retry": self.proximo_retry,
        }


def _agora() -> float:
    return time.time()


def _tamanho(caminho: Path) -> int:
    try:
        return int(caminho.stat().st_size)
    except OSError:
        return 0


def _hash_arquivo(caminho: Path, hasher: Any) -> None:
    """Prefixo de um `.part` retomado entra no mesmo hasher do stream."""
    with open(caminho, "rb") as fh:
        while True:
            bloco = fh.read(_CHUNK)
            if not bloco:
                return
            hasher.update(bloco)


def _total_do_content_range(valor: str) -> int:
    """'bytes 100-999/1000' → 1000 ( '*' = desconhecido → -1 )."""
    try:
        total = valor.split("/", 1)[1].strip()
        return int(total) if total != "*" else -1
    except (IndexError, ValueError):
        return -1


class DownloadQueue:
    """Fila de downloads com worker próprio (thread daemon).

    O worker é o ÚNICO que escreve em `.part`; a API só consulta e
    sinaliza (enqueue/cancelar/remover), sempre sob o mesmo lock.
    """

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        state_path: Optional[Path] = None,
        *,
        max_tentativas: int = 5,
        backoff_base_s: float = _BACKOFF_BASE_S,
        backoff_cap_s: float = _BACKOFF_CAP_S,
        opener: Optional[Callable[..., Any]] = None,
        historico_max: int = _HISTORICO_MAX,
        timeout_s: float = _TIMEOUT_S,
    ) -> None:
        raiz = base_dir or Path(
            os.environ.get("OD_DOWNLOADS_DIR", "") or _RAIZ_PADRAO
        )
        self._base = Path(raiz).expanduser().resolve()
        self._estado = Path(state_path) if state_path else _ESTADO_PADRAO
        self._max_tentativas = max(1, int(max_tentativas))
        self._backoff_base = float(backoff_base_s)
        self._backoff_cap = float(backoff_cap_s)
        self._historico_max = int(historico_max)
        self._timeout = float(timeout_s)
        # injetável para testes herméticos (sem rede)
        self._abrir = opener or urllib.request.urlopen

        self._jobs: dict[str, DownloadJob] = {}
        self._ordem: list[str] = []          # FIFO por criado_em
        self._subs: set[queue_mod.Queue] = set()
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._parar = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ultima_gravacao = 0.0

        self._carregar()

    # ------------------------------------------------------------------#
    # Ciclo de vida                                                      #
    # ------------------------------------------------------------------#
    def start(self) -> None:
        """Sobe o worker (idempotente — daemon, morre com o processo)."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._parar.clear()
            self._thread = threading.Thread(
                target=self._loop, name="od-downloads", daemon=True
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Encerra o worker (o estado fica gravado; o boot re-enfileira)."""
        self._parar.set()
        with self._cond:
            self._cond.notify_all()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    @property
    def raiz(self) -> Path:
        """Diretório-raiz da fila — todo destino válido está dentro dele."""
        return self._base

    @property
    def max_tentativas(self) -> int:
        return self._max_tentativas

    # ------------------------------------------------------------------#
    # Operações da API                                                   #
    # ------------------------------------------------------------------#
    def enqueue(self, url: str, destino: str = "",
                sha256: str = "") -> tuple[DownloadJob, bool]:
        """Enfileira. Devolve (job, True) quando criou; (existente, False)
        no dedup — mesma URL+destino já ativa na fila."""
        url = str(url or "").strip()
        partes = urlsplit(url)
        if partes.scheme not in ("http", "https") or not partes.netloc:
            raise ValueError("url_invalida")
        sha256 = str(sha256 or "").strip().lower()
        if sha256 and (len(sha256) != 64
                       or any(c not in "0123456789abcdef" for c in sha256)):
            raise ValueError("sha256_invalido")
        caminho = self._resolver_destino(url, destino)
        if caminho.is_dir():
            raise ValueError("destino_e_diretorio")
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            for job_id in self._ordem:
                antigo = self._jobs[job_id]
                if antigo.url == url and antigo.destino == str(caminho) \
                        and antigo.ativo:
                    return antigo, False
            job = DownloadJob(
                id=self._proximo_id(),
                url=url,
                destino=str(caminho),
                nome=caminho.name,
                bytes_feitos=_tamanho(Path(str(caminho) + ".part")),
                max_tentativas=self._max_tentativas,
                sha256=sha256,
                criado_em=_agora(),
                atualizado_em=_agora(),
            )
            self._jobs[job.id] = job
            self._ordem.append(job.id)
            self._persistir(forcar=True)
            self._publicar("estado", job)
            self._cond.notify_all()
            log.info("Download enfileirado", id=job.id, nome=job.nome)
            return job, True

    def lista(self) -> list[dict[str, Any]]:
        """Jobs em ordem de fila (FIFO), prontos para o painel/app."""
        with self._lock:
            return [self._jobs[job_id].para_dict() for job_id in self._ordem]

    def get(self, job_id: str) -> Optional[DownloadJob]:
        with self._lock:
            return self._jobs.get(str(job_id))

    def cancelar(self, job_id: str) -> DownloadJob:
        """Cancela. No meio da transferência preserva o `.part`."""
        with self._lock:
            job = self._jobs.get(str(job_id))
            if job is None:
                raise ValueError("job_inexistente")
            job.cancelar = True
            if job.status == BAIXANDO:
                # o worker finalize no próximo bloco lido
                self._cond.notify_all()
                return job
            if job.status not in TERMINAIS:
                self._finalizar(job, CANCELADO)
            return job

    def remover(self, job_id: str) -> None:
        """Apaga o REGISTRO (arquivo/.part ficam). Só job terminal."""
        with self._lock:
            job = self._jobs.get(str(job_id))
            if job is None:
                raise ValueError("job_inexistente")
            if job.ativo:
                raise ValueError("job_ativo")
            del self._jobs[job.id]
            self._ordem.remove(job.id)
            self._persistir(forcar=True)
            self._publicar("removido", job)
            self._cond.notify_all()

    def snapshot(self) -> dict[str, Any]:
        """Resumo para /dashboard/stats e para o cabeçalho do painel."""
        with self._lock:
            contagem = {s: 0 for s in (NA_FILA, BAIXANDO, AGUARDANDO,
                                       CONCLUIDO, ERRO, CANCELADO)}
            bytes_baixados = 0
            for job in self._jobs.values():
                contagem[job.status] = contagem.get(job.status, 0) + 1
                bytes_baixados += max(0, job.bytes_feitos)
            ativas = contagem[NA_FILA] + contagem[BAIXANDO] + contagem[AGUARDANDO]
            return {
                "total": len(self._jobs),
                "ativas": ativas,
                "na_fila": contagem[NA_FILA],
                "baixando": contagem[BAIXANDO],
                "aguardando": contagem[AGUARDANDO],
                "concluidos": contagem[CONCLUIDO],
                "erros": contagem[ERRO],
                "cancelados": contagem[CANCELADO],
                "bytes_baixados": bytes_baixados,
            }

    def subscribe(self) -> tuple[queue_mod.Queue, Callable[[], None]]:
        """Assinatura de eventos (SSE). Devolve (fila, cancela)."""
        fila: queue_mod.Queue = queue_mod.Queue(maxsize=256)
        with self._lock:
            self._subs.add(fila)

        def cancela() -> None:
            with self._lock:
                self._subs.discard(fila)

        return fila, cancela

    def aguardar(self, job_id: str, timeout: float = 10.0) -> DownloadJob:
        """Espera o job chegar a estado terminal (prova viva / testes)."""
        prazo = _agora() + timeout
        with self._cond:
            while True:
                job = self._jobs.get(str(job_id))
                if job is None:
                    raise ValueError("job_inexistente")
                if job.status in TERMINAIS:
                    return job
                restante = prazo - _agora()
                if restante <= 0:
                    return job
                self._cond.wait(timeout=restante)

    # ------------------------------------------------------------------#
    # Worker                                                             #
    # ------------------------------------------------------------------#
    def _loop(self) -> None:
        while not self._parar.is_set():
            job: Optional[DownloadJob] = None
            with self._cond:
                while not self._parar.is_set():
                    agora = _agora()
                    job = self._proximo(agora)
                    if job is not None:
                        break
                    espera = self._espera(agora)
                    if espera is None:
                        self._cond.wait()
                    else:
                        self._cond.wait(timeout=max(0.01, espera))
                if job is None:
                    return  # stop() no meio da espera
            try:
                self._baixar(job)
            except Exception as exc:  # pragma: no cover — defeito inesperado
                log.error("Worker de download falhou", id=job.id,
                          error=f"{type(exc).__name__}: {exc}")
                with self._lock:
                    if job.status not in TERMINAIS:
                        job.erro = f"{type(exc).__name__}: {exc}"[:300]
                        self._finalizar(job, ERRO)

    def _proximo(self, agora: float) -> Optional[DownloadJob]:
        """Pronto para baixar: na_fila (FIFO) ou aguardando vencido."""
        for job_id in self._ordem:
            job = self._jobs[job_id]
            if job.status == NA_FILA:
                return job
            if job.status == AGUARDANDO and (job.proximo_retry or 0) <= agora:
                return job
        return None

    def _espera(self, agora: float) -> Optional[float]:
        """Segundos até o próximo retry (None = nada agendado)."""
        menor: Optional[float] = None
        for job in self._jobs.values():
            if job.status == AGUARDANDO and job.proximo_retry:
                resta = job.proximo_retry - agora
                menor = resta if menor is None else min(menor, resta)
        return menor

    def _backoff(self, tentativas: int) -> float:
        return min(self._backoff_base * (2 ** max(0, tentativas - 1)),
                   self._backoff_cap)

    def _baixar(self, job: DownloadJob) -> None:
        destino = Path(job.destino)
        part = Path(job.destino + ".part")
        try:
            with self._lock:
                if job.status in TERMINAIS:
                    return  # cancelado antes de começar
                if job.cancelar:
                    self._finalizar(job, CANCELADO)
                    return
                job.status = BAIXANDO
                job.tentativas += 1
                job.erro = ""
                job.proximo_retry = None
                job.atualizado_em = _agora()
                self._persistir(forcar=True)
                self._publicar("estado", job)
            destino.parent.mkdir(parents=True, exist_ok=True)
            self._transferir(job, part)
        except _Cancelado:
            with self._lock:
                job.bytes_feitos = _tamanho(part)
                self._finalizar(job, CANCELADO)   # `.part` fica para retomar
            log.info("Download cancelado", id=job.id, nome=job.nome)
            return
        except _Interrompido:
            # Servidor descendo: preserva o parcial e re-enfileira — o
            # próximo boot retoma com Range em vez de recomeçar do zero.
            with self._lock:
                job.status = NA_FILA
                job.bytes_feitos = _tamanho(part)
                job.atualizado_em = _agora()
                self._persistir(forcar=True)
                self._publicar("estado", job)
                self._cond.notify_all()
            return
        except Exception as exc:
            self._falhou(job, part, exc)
            return

        with self._lock:
            job.bytes_feitos = _tamanho(destino)
            job.bytes_total = job.bytes_feitos
            self._finalizar(job, CONCLUIDO)
        log.info("Download concluído", id=job.id, nome=job.nome,
                 bytes=job.bytes_feitos, tentativas=job.tentativas)

    def _transferir(self, job: DownloadJob, part: Path) -> None:
        """Stream com Range (retomada) + sha256 incremental."""
        offset = _tamanho(part)
        hasher = hashlib.sha256()
        if offset:
            _hash_arquivo(part, hasher)   # prefixo já gravado entra no hash

        resp: Any = None
        tentar_range = offset > 0
        try:
            while True:
                cabecos = {"User-Agent": _USER_AGENT}
                if tentar_range:
                    cabecos["Range"] = f"bytes={offset}-"
                try:
                    resp = self._abrir(
                        urllib.request.Request(job.url, headers=cabecos),
                        timeout=self._timeout,
                    )
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code == 416 and offset > 0:
                        # Range insatisfável (arquivo mudou no servidor):
                        # recomeça do zero — uma vez só.
                        part.unlink(missing_ok=True)
                        offset = 0
                        tentar_range = False
                        hasher = hashlib.sha256()
                        continue
                    raise

            status = int(getattr(resp, "status", 0) or resp.getcode())
            cabecais = getattr(resp, "headers", {}) or {}
            feitos = offset
            if status == 206:
                total = _total_do_content_range(
                    str(cabecais.get("Content-Range") or "")
                )
                if total < 0:
                    cl = cabecais.get("Content-Length")
                    total = offset + int(cl) if cl else -1
            else:
                # 200: o servidor ignorou o Range — recomeça de verdade.
                offset = 0
                feitos = 0
                if tentar_range:
                    hasher = hashlib.sha256()
                cl = cabecais.get("Content-Length")
                total = int(cl) if cl else -1

            job.bytes_total = total
            modo = "ab" if (status == 206 and feitos) else "wb"
            proxima_publicacao = 0.0
            with open(part, modo) as fh:
                while True:
                    if job.cancelar:
                        raise _Cancelado()
                    if self._parar.is_set():
                        raise _Interrompido()
                    bloco = resp.read(_CHUNK)
                    if not bloco:
                        break
                    fh.write(bloco)
                    hasher.update(bloco)
                    feitos += len(bloco)
                    job.bytes_feitos = feitos
                    agora = _agora()
                    if agora >= proxima_publicacao:
                        proxima_publicacao = agora + _PROGRESSO_S
                        with self._lock:
                            job.atualizado_em = agora
                            self._publicar("progresso", job)
                            self._persistir()   # throttled
                fh.flush()
                os.fsync(fh.fileno())

            if total >= 0 and feitos < total:
                raise _Incompleto(f"stream cortado: {feitos}/{total} bytes")

            job.sha256_real = hasher.hexdigest()
            if job.sha256 and job.sha256.lower() != job.sha256_real:
                part.unlink(missing_ok=True)
                raise _Permanente(
                    f"sha256 divergente: esperado {job.sha256[:12]}…, "
                    f"veio {job.sha256_real[:12]}…"
                )
            os.replace(part, Path(job.destino))
        finally:
            if resp is not None:
                fecha = getattr(resp, "close", None)
                if fecha:
                    try:
                        fecha()
                    except Exception:  # pragma: no cover
                        pass

    def _falhou(self, job: DownloadJob, part: Path, exc: Exception) -> None:
        """Retry com backoff OU erro terminal — sempre com estado visível."""
        with self._lock:
            job.bytes_feitos = _tamanho(part)   # verdade em disco
            job.atualizado_em = _agora()
            if job.cancelar:
                self._finalizar(job, CANCELADO)
                return
            permanente = isinstance(exc, _Permanente)
            codigo = exc.code if isinstance(exc, urllib.error.HTTPError) else None
            if codigo is not None and codigo not in _HTTP_RETENTAVEIS:
                permanente = True
            if permanente or job.tentativas >= job.max_tentativas:
                job.erro = self._mensagem(exc)
                self._finalizar(job, ERRO)
                log.warn("Download falhou", id=job.id, nome=job.nome,
                         tentativas=job.tentativas, erro=job.erro)
                return
            job.status = AGUARDANDO
            job.erro = self._mensagem(exc)
            job.proximo_retry = _agora() + self._backoff(job.tentativas)
            self._persistir(forcar=True)
            self._publicar("estado", job)
            self._cond.notify_all()
            log.warn("Download reagendado", id=job.id,
                     tentativa=job.tentativas,
                     proximo_retry_em=round(job.proximo_retry - _agora(), 1),
                     erro=job.erro)

    @staticmethod
    def _mensagem(exc: Exception) -> str:
        if isinstance(exc, urllib.error.HTTPError):
            return f"http_{exc.code}"
        texto = str(exc) or type(exc).__name__
        return texto[:300]

    # ------------------------------------------------------------------#
    # Estado (JSON atômico)                                              #
    # ------------------------------------------------------------------#
    def _finalizar(self, job: DownloadJob, status: str) -> None:
        """Transição terminal — chamado sempre com o lock segurado."""
        job.status = status
        job.cancelar = False
        job.proximo_retry = None
        job.fim_em = _agora()
        job.atualizado_em = job.fim_em
        self._recortar_historico()
        self._persistir(forcar=True)
        self._publicar("estado", job)
        self._cond.notify_all()

    def _recortar_historico(self) -> None:
        terminais = [jid for jid in self._ordem
                     if self._jobs[jid].status in TERMINAIS]
        excedente = len(terminais) - self._historico_max
        for jid in terminais[:max(0, excedente)]:
            del self._jobs[jid]
            self._ordem.remove(jid)

    def _proximo_id(self) -> str:
        seq = 0
        for job_id in self._ordem:
            try:
                seq = max(seq, int(job_id.split("-", 1)[1]))
            except (IndexError, ValueError):
                continue
        return f"dl-{seq + 1:04d}"

    def _persistir(self, forcar: bool = False) -> None:
        """Escrita atômica; progresso entra no máximo a cada 2 s."""
        agora = _agora()
        if not forcar and (agora - self._ultima_gravacao) < _PERSIST_S:
            return
        self._ultima_gravacao = agora
        payload = {
            "versao": 1,
            "atualizado_em": agora,
            "jobs": [self._jobs[job_id].para_dict() for job_id in self._ordem],
        }
        try:
            self._estado.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._estado.with_suffix(self._estado.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self._estado)
        except OSError as exc:  # pragma: no cover — disco cheio/sem permissão
            log.warn("Estado da fila não gravado", error=str(exc))

    def _carregar(self) -> None:
        try:
            bruto = json.loads(self._estado.read_text(encoding="utf-8"))
            linhas = bruto.get("jobs") or []
        except (OSError, ValueError):
            return
        conhecidos = {f.name for f in fields(DownloadJob)} - {"cancelar"}
        for linha in linhas:
            try:
                job = DownloadJob(**{k: v for k, v in linha.items()
                                     if k in conhecidos})
            except TypeError:
                continue
            if job.status in (BAIXANDO, AGUARDANDO):
                # Boot: o que estava em voo volta para a fila — o `.part`
                # em disco continua valendo (retomada automática).
                job.status = NA_FILA
                job.proximo_retry = None
            job.cancelar = False
            part = Path(job.destino + ".part")
            if job.status != CONCLUIDO and not Path(job.destino).exists():
                job.bytes_feitos = _tamanho(part)
            self._jobs[job.id] = job
            self._ordem.append(job.id)
        if self._jobs:
            log.info("Fila de downloads restaurada",
                     jobs=len(self._jobs),
                     reenfileirados=sum(1 for j in self._jobs.values()
                                        if j.status == NA_FILA))

    # ------------------------------------------------------------------#
    # Eventos (SSE)                                                      #
    # ------------------------------------------------------------------#
    def _publicar(self, evento: str, job: DownloadJob) -> None:
        """Transmite SEM segurar o worker: fila por assinante, overflow
        descarta o mais antigo (o `estado` final é re-publicado depois)."""
        if not self._subs:
            return
        pacote = {"evento": evento, "job": job.para_dict()}
        for fila in tuple(self._subs):
            try:
                fila.put_nowait(pacote)
            except queue_mod.Full:
                try:
                    fila.get_nowait()
                    fila.put_nowait(pacote)
                except (queue_mod.Empty, queue_mod.Full):  # pragma: no cover
                    pass

    # ------------------------------------------------------------------#
    # Destino                                                            #
    # ------------------------------------------------------------------#
    def _resolver_destino(self, url: str, destino: str) -> Path:
        """Caminho absoluto SEMPRE dentro da raiz da fila."""
        nome = str(destino or "").strip() or _nome_da_url(url)
        if not nome:
            nome = "download"
        bruto = Path(nome)
        if bruto.is_absolute() or any(p in ("..", "") for p in bruto.parts):
            raise ValueError("destino_invalido")
        alvo = (self._base / bruto).resolve()
        if not alvo.is_relative_to(self._base):
            raise ValueError("destino_invalido")
        return alvo


def _nome_da_url(url: str) -> str:
    """Nome do arquivo pela URL ('.../peso-7b.gguf?v=2' → 'peso-7b.gguf')."""
    caminho = unquote(urlsplit(url).path)
    nome = Path(caminho).name.strip()
    if not nome or nome in (".", "..") or "/" in nome:
        return "download"
    return nome
