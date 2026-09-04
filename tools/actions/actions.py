"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: tools/actions/actions.py
Descrição: Catálogo das 56 Actions operacionais do OmegaDrakon — handlers
           sincronos + metadados (name, category, description, params),
           prontos para registro no Action Registry (tools/registry.py)
           com gate do Security Layer (permission = nome da ação).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime core/actions/ (56 actions operacionais)
  - docs/NV_LEGACY_ANALYSIS.md §3.3 (categorias e nomes)
  - OMEGADRAKON_SPEC.md §7 (execução mediada por Security Layer, escopo
    estrito §7.1)
  - ROADMAP_ABSORCAO.md Fase 4, item 4.4 (depende de Registry 3.3 + Security)

Origem do catálogo:
    54 ações enumeradas na análise legada do NV (sistema, processos,
    docker, serviços, arquivos, git, banco de dados, introspecção) +
    2 ações complementares derivadas, registradas no CHANGELOG:
    process_tree (processos) e action_list (introspecção).

Segurança e robustez:
    - Toda ação declara permission == próprio nome — o Registry consulta o
      Security Layer antes de executar (fail-closed em modo strict).
    - Handlers NUNCA assumem infraestrutura externa: docker/systemd/git/db
      degradam para dados {ok: False, error: ...} quando o binário/recurso
      não está disponível — sem exceção vazando para o Registry.
    - Ações destrutivas por natureza são acionadas apenas por quem o
      Security Layer autorizar (ex: process_kill exige papel com a
      permissão; protege pid < 2).
    - Nenhuma ação usa caminho de repositório padrão: parâmetros de
      arquivo/git são SEMPRE explícitos (sem default para o projeto).
"""

from __future__ import annotations

import datetime
import fnmatch
import hashlib
import os
import pwd
import re
import shutil
import signal
import socket
import stat
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

__signature__ = "OD // CORE"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(argv: list[str], timeout: float = 15.0) -> tuple[int, str, str]:
    """Executa um comando externo capturando saída (sem shell)."""
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", f"comando indisponível: {argv[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout após {timeout}s"


def _unavailable(tool: str, detail: str = "") -> dict[str, Any]:
    """Resultado de degradação graciosa quando recurso externo falta."""
    data: dict[str, Any] = {"ok": False, "tool": tool}
    if detail:
        data["error"] = detail
    return data


def _read_proc(name: str) -> str:
    """Lê um arquivo de /proc ('' se indisponível)."""
    try:
        return Path("/proc", name).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _path(value: str) -> Path:
    return Path(value).expanduser()


# ---------------------------------------------------------------------------
# Sistema
# ---------------------------------------------------------------------------

def system_info() -> dict[str, Any]:
    """Informações gerais do sistema (platform stdlib)."""
    import platform

    uname = os.uname()
    return {
        "system": uname.sysname,
        "node": uname.nodename,
        "release": uname.release,
        "version": uname.version,
        "machine": uname.machine,
        "python": platform.python_version(),
        "cores": os.cpu_count() or 0,
        "ts": time.time(),
    }


def datetime_now() -> dict[str, Any]:
    """Data/hora atual (UTC e local, ISO 8601)."""
    now = datetime.datetime.now()
    return {
        "iso": now.isoformat(timespec="seconds"),
        "date": now.date().isoformat(),
        "time": now.time().isoformat(timespec="seconds"),
        "weekday": now.weekday(),
        "timestamp": time.time(),
    }


def uptime() -> dict[str, Any]:
    """Uptime do sistema (segundos e dias), via /proc/uptime."""
    raw = _read_proc("uptime").split()
    if not raw:
        return _unavailable("uptime", "/proc/uptime indisponível")
    seconds = float(raw[0])
    return {
        "ok": True,
        "seconds": seconds,
        "days": round(seconds / 86400, 2),
        "idle_seconds": float(raw[1]) if len(raw) > 1 else 0.0,
    }


def disk_usage(path: str = "/") -> dict[str, Any]:
    """Uso de disco do caminho (bytes e percentual)."""
    try:
        usage = shutil.disk_usage(_path(path))
    except OSError as exc:
        return _unavailable("disk", f"{type(exc).__name__}: {exc}")
    return {
        "ok": True,
        "path": str(_path(path).resolve()),
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
        "percent": round(100.0 * usage.used / usage.total, 1),
    }


def memory_usage() -> dict[str, Any]:
    """Memória RAM + swap (bytes), via /proc/meminfo."""
    raw = _read_proc("meminfo")
    if not raw:
        return _unavailable("memory", "/proc/meminfo indisponível")
    fields: dict[str, int] = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].endswith(":"):
            try:
                fields[parts[0][:-1]] = int(parts[1]) * 1024
            except ValueError:
                continue
    total = fields.get("MemTotal", 0)
    available = fields.get("MemAvailable", fields.get("MemFree", 0))
    swap_total = fields.get("SwapTotal", 0)
    swap_free = fields.get("SwapFree", 0)
    swap_used = max(0, swap_total - swap_free)
    return {
        "ok": True,
        "total": total,
        "available": available,
        "used": max(0, total - available),
        "percent": round(100.0 * (total - available) / total, 1) if total else 0.0,
        "swap_total": swap_total,
        "swap_used": swap_used,
        "swap_percent": round(100.0 * swap_used / swap_total, 1) if swap_total else 0.0,
    }


def cpu_info() -> dict[str, Any]:
    """Núcleos, modelo e carga da CPU."""
    model = ""
    for line in _read_proc("cpuinfo").splitlines():
        if line.lower().startswith("model name"):
            model = line.split(":", 1)[1].strip()
            break
    load = "0 0 0"
    try:
        load = _read_proc("loadavg").split()[:3]
    except Exception:  # pragma: no cover
        pass
    return {
        "ok": True,
        "cores": os.cpu_count() or 0,
        "model": model or "desconhecido",
        "load1": float(load[0]) if isinstance(load, list) and load else 0.0,
    }


def ip_address() -> dict[str, Any]:
    """Endereços IP do host (best-effort, sem root)."""
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        ips = sorted({info[4][0] for info in infos})
    except OSError:
        ips = []
    # IP de saída padrão (UDP sem enviar pacotes)
    outbound = ""
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        outbound = probe.getsockname()[0]
        probe.close()
    except OSError:
        pass
    return {"ok": True, "addresses": ips, "outbound": outbound}


def system_which(command: str) -> dict[str, Any]:
    """Localiza um executável no PATH."""
    found = shutil.which(command)
    return {"ok": True, "command": command, "path": found}


def system_hostname() -> dict[str, Any]:
    """Nome do host."""
    return {"ok": True, "hostname": socket.gethostname()}


def system_env(keys: list[str] | None = None) -> dict[str, Any]:
    """Variáveis de ambiente: valores apenas para `keys`; sem keys, apenas
    os NOMES (evita vazar segredos em respostas genéricas)."""
    names = sorted(os.environ.keys())
    if keys:
        selected = {key: os.environ.get(key) for key in keys}
        return {"ok": True, "count": len(keys), "values": selected}
    return {"ok": True, "count": len(names), "keys": names}


def system_ping(host: str, port: int = 443, timeout: float = 1.0) -> dict[str, Any]:
    """Sonda de conectividade TCP (sem ICMP — não exige root)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        reachable = True
    except OSError:
        reachable = False
    finally:
        sock.close()
    return {"ok": True, "host": host, "port": port, "reachable": reachable}


def system_user() -> dict[str, Any]:
    """Usuário atual (uid/gid/nome/home)."""
    try:
        info = pwd.getpwuid(os.getuid())
        return {
            "ok": True,
            "name": info.pw_name,
            "uid": info.pw_uid,
            "gid": info.pw_gid,
            "home": info.pw_dir,
            "shell": info.pw_shell,
        }
    except KeyError:
        return {"ok": True, "name": os.environ.get("USER", "?"), "uid": os.getuid()}


def system_groups() -> dict[str, Any]:
    """Grupos do usuário atual."""
    return {"ok": True, "groups": sorted(os.getgroups())}


# ---------------------------------------------------------------------------
# Processos
# ---------------------------------------------------------------------------

def _processes() -> list[dict[str, Any]]:
    """Leitura básica de /proc: pid, comm, estado."""
    result: list[dict[str, Any]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        comm = ""
        try:
            comm = (entry / "comm").read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        state = ""
        try:
            stat_fields = (entry / "stat").read_text(
                encoding="utf-8", errors="replace"
            ).split()
            if len(stat_fields) > 2:
                state = stat_fields[2]
        except OSError:
            pass
        result.append({"pid": pid, "comm": comm, "state": state})
    return result


def process_list() -> dict[str, Any]:
    """Lista processos do sistema."""
    procs = sorted(_processes(), key=lambda p: p["pid"])
    return {"ok": True, "count": len(procs), "processes": procs}


def process_info(pid: int) -> dict[str, Any]:
    """Detalhes de um processo (comm, estado, ppid, cmdline)."""
    proc_dir = Path("/proc") / str(pid)
    if not proc_dir.is_dir():
        return _unavailable("process", f"processo {pid} não encontrado")
    info: dict[str, Any] = {"pid": pid}
    try:
        info["comm"] = (proc_dir / "comm").read_text(
            encoding="utf-8", errors="replace"
        ).strip()
    except OSError:
        pass
    try:
        raw = (proc_dir / "stat").read_text(encoding="utf-8", errors="replace")
        # comm entre parênteses pode conter espaços — fatiar por último ')'
        rest = raw.rsplit(")", 1)[-1].split()
        info["state"] = rest[0] if rest else ""
        info["ppid"] = int(rest[1]) if len(rest) > 1 else None
    except (OSError, ValueError, IndexError):
        pass
    try:
        cmd = (proc_dir / "cmdline").read_bytes().replace(b"\x00", b" ").decode(
            "utf-8", errors="replace"
        )
        info["cmdline"] = cmd.strip()
    except OSError:
        pass
    info["ok"] = True
    return info


def process_kill(pid: int, sig: int = 15) -> dict[str, Any]:
    """Envia um sinal a um processo (protege pid < 2)."""
    if pid < 2:
        raise ValueError("pid < 2 é protegido (nunca encerre init)")
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        return _unavailable("process", f"processo {pid} não encontrado")
    except PermissionError as exc:
        return _unavailable("process", f"permissão negada: {exc}")
    return {"ok": True, "pid": pid, "signal": sig}


def process_tree(pid: int = 1) -> dict[str, Any]:
    """Árvore de processos a partir de um pid (ppid via /proc)."""
    procs = _processes()
    by_pid = {p["pid"]: p for p in procs}
    # parentes de cada processo (stat -> ppid)
    children: dict[int, list[int]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "stat").read_text(encoding="utf-8", errors="replace")
            rest = raw.rsplit(")", 1)[-1].split()
            ppid = int(rest[1]) if len(rest) > 1 else 0
            children.setdefault(ppid, []).append(int(entry.name))
        except (OSError, ValueError, IndexError):
            continue

    def build(node: int, depth: int = 0) -> dict[str, Any]:
        leaf: dict[str, Any] = {"pid": node}
        info = by_pid.get(node)
        if info:
            leaf["comm"] = info["comm"]
        kids = sorted(children.get(node, []))
        if kids and depth < 32:
            leaf["children"] = [build(k, depth + 1) for k in kids]
        return leaf

    return {"ok": True, "root": pid, "tree": build(pid)}


# ---------------------------------------------------------------------------
# Docker (via CLI — degrada graciosamente sem binário/daemon)
# ---------------------------------------------------------------------------

def _docker(args: list[str], timeout: float = 15.0) -> dict[str, Any]:
    rc, out, err = _run(["docker", *args], timeout=timeout)
    if rc != 0:
        return _unavailable("docker", (err or out).strip()[:400])
    return {"ok": True, "output": out}


def docker_list() -> dict[str, Any]:
    """Lista contêineres (docker ps -a)."""
    return _docker(["ps", "-a", "--no-trunc"])


def docker_status() -> dict[str, Any]:
    """Status do daemon (docker info resumido)."""
    result = _docker(["info"], timeout=20.0)
    if not result.get("ok"):
        return result
    out = result.get("output", "")
    extract = re.findall(
        r"^(Server Version|Containers|Running|Images):\s*(.+)$",
        out,
        flags=re.MULTILINE,
    )
    result["summary"] = {k.strip(): v.strip() for k, v in extract}
    return result


def docker_logs(container: str, lines: int = 100) -> dict[str, Any]:
    """Últimas linhas de log de um contêiner."""
    if lines <= 0:
        raise ValueError("lines deve ser > 0")
    return _docker(["logs", "--tail", str(lines), container])


def docker_stats() -> dict[str, Any]:
    """Métricas ao vivo (docker stats --no-stream)."""
    return _docker(
        ["stats", "--no-stream", "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"]
    )


# ---------------------------------------------------------------------------
# Serviços (systemd — degrada graciosamente)
# ---------------------------------------------------------------------------

def service_list() -> dict[str, Any]:
    """Lista unidades de serviço (systemctl)."""
    rc, out, err = _run(
        ["systemctl", "list-units", "--type=service", "--all", "--plain", "--no-pager"]
    )
    if rc != 0:
        return _unavailable("systemd", (err or out).strip()[:400])
    services = []
    for line in out.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0].endswith(".service"):
            services.append({"name": fields[0], "state": fields[1]})
    return {"ok": True, "count": len(services), "services": services}


def service_status(name: str) -> dict[str, Any]:
    """Status de um serviço (systemctl status)."""
    rc, out, err = _run(["systemctl", "status", name, "--no-pager"])
    active = ""
    match = re.search(r"Active:\s*([^(]+)", out)
    if match:
        active = match.group(1).strip()
    return {
        "ok": True,
        "name": name,
        "loaded": rc == 0,
        "active": active,
        "output": (out if rc == 0 else (err or out)).strip()[:400],
    }


def service_logs(name: str, lines: int = 50) -> dict[str, Any]:
    """Logs de um serviço (journalctl -u)."""
    if lines <= 0:
        raise ValueError("lines deve ser > 0")
    rc, out, err = _run(["journalctl", "-u", name, "-n", str(lines), "--no-pager"])
    if rc != 0:
        return _unavailable("journald", (err or out).strip()[:400])
    return {"ok": True, "name": name, "logs": out}


# ---------------------------------------------------------------------------
# Arquivos (escopo estrito validado pelo Security Layer no Registry)
# ---------------------------------------------------------------------------

def filesystem_search(path: str, pattern: str, recursive: bool = True) -> dict[str, Any]:
    """Busca arquivos por padrão glob dentro de um diretório."""
    base = _path(path)
    if not base.is_dir():
        raise ValueError(f"diretorio nao encontrado: {path}")
    matcher = base.rglob if recursive else base.glob
    matches = [
        str(p.relative_to(base))
        for p in sorted(matcher("*"))
        if p.is_file() and fnmatch.fnmatch(p.name, pattern)
    ]
    return {"ok": True, "path": str(base.resolve()), "count": len(matches), "matches": matches}


def filesystem_read(path: str, encoding: str = "utf-8") -> str:
    """Lê um arquivo de texto."""
    return _path(path).read_text(encoding=encoding, errors="replace")


def filesystem_write(
    path: str, content: str, encoding: str = "utf-8", append: bool = False
) -> dict[str, Any]:
    """Escreve (ou anexa) conteúdo em um arquivo."""
    target = _path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with open(target, mode, encoding=encoding) as handle:
        handle.write(content)
    return {"ok": True, "path": str(target.resolve()), "append": append}


def filesystem_delete(path: str) -> dict[str, Any]:
    """Remove um arquivo (não diretórios)."""
    target = _path(path)
    if target.is_dir():
        raise ValueError("use filesystem.rmdir para diretórios")
    target.unlink(missing_ok=True)
    return {"ok": True, "deleted": str(target)}


def filesystem_exists(path: str) -> bool:
    """True se o caminho existe."""
    return _path(path).exists()


def filesystem_info(path: str) -> dict[str, Any]:
    """Metadados do arquivo (size, mtime, mode, type)."""
    target = _path(path)
    try:
        st = target.stat()
    except OSError as exc:
        return _unavailable("filesystem", f"{type(exc).__name__}: {exc}")
    kind = "dir" if stat.S_ISDIR(st.st_mode) else "file"
    return {
        "ok": True,
        "path": str(target.resolve()),
        "type": kind,
        "size": st.st_size,
        "mtime": st.st_mtime,
        "mode": stat.S_IMODE(st.st_mode),
    }


def filesystem_list(path: str) -> dict[str, Any]:
    """Lista entradas de um diretório."""
    base = _path(path)
    if not base.is_dir():
        raise ValueError(f"diretorio nao encontrado: {path}")
    entries = sorted(p.name for p in base.iterdir())
    return {"ok": True, "path": str(base.resolve()), "count": len(entries), "entries": entries}


def filesystem_mkdir(path: str) -> dict[str, Any]:
    """Cria diretório (com pais)."""
    target = _path(path)
    target.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "path": str(target.resolve())}


def filesystem_move(source: str, destination: str) -> dict[str, Any]:
    """Move/renomeia arquivo ou diretório."""
    shutil.move(str(_path(source)), str(_path(destination)))
    return {"ok": True, "source": source, "destination": destination}


def filesystem_copy(source: str, destination: str) -> dict[str, Any]:
    """Copia arquivo (ou árvore) para o destino."""
    src, dst = _path(source), _path(destination)
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return {"ok": True, "source": source, "destination": destination}


def filesystem_touch(path: str) -> dict[str, Any]:
    """Cria arquivo vazio (ou atualiza mtime)."""
    target = _path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()
    return {"ok": True, "path": str(target.resolve())}


def filesystem_tree(path: str, max_depth: int = 3) -> dict[str, Any]:
    """Árvore de diretórios (profundidade limitada)."""
    base = _path(path)
    if not base.is_dir():
        raise ValueError(f"diretorio nao encontrado: {path}")

    def walk(current: Path, depth: int) -> list[dict[str, Any]]:
        if depth > max_depth:
            return [{"name": "...", "truncated": True}]
        result = []
        for child in sorted(current.iterdir()):
            if child.is_dir():
                entry: dict[str, Any] = {"name": child.name, "type": "dir"}
                entry["children"] = walk(child, depth + 1)
                result.append(entry)
            else:
                result.append({"name": child.name, "type": "file"})
        return result

    return {"ok": True, "path": str(base.resolve()), "tree": walk(base, 0)}


def filesystem_hash(path: str, algorithm: str = "sha256") -> dict[str, Any]:
    """Hash do arquivo (sha256 padrão)."""
    if algorithm not in hashlib.algorithms_available:
        raise ValueError(f"algoritmo desconhecido: {algorithm}")
    digest = hashlib.new(algorithm)
    with open(_path(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return {"ok": True, "path": str(_path(path).resolve()), "algorithm": algorithm, "hash": digest.hexdigest()}


def filesystem_archive(path: str, archive_path: str = "") -> dict[str, Any]:
    """Compacta um diretório/arquivo em ZIP."""
    src = _path(path)
    dst = _path(archive_path) if archive_path else _path(str(src) + ".zip")
    if not src.exists():
        raise ValueError(f"caminho nao encontrado: {path}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
        if src.is_dir():
            for file in src.rglob("*"):
                if file.is_file():
                    zf.write(file, file.relative_to(src.parent))
        else:
            zf.write(src, src.name)
    return {"ok": True, "archive": str(dst.resolve()), "source": path}


def filesystem_extract(archive_path: str, destination: str) -> dict[str, Any]:
    """Extrai um ZIP para o destino."""
    archive = _path(archive_path)
    if not archive.exists():
        raise ValueError(f"arquivo nao encontrado: {archive_path}")
    dest = _path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
    else:
        raise ValueError(f"formato não suportado (apenas zip): {archive_path}")
    return {"ok": True, "destination": str(dest.resolve()), "archive": archive_path}


# ---------------------------------------------------------------------------
# Git (todos exigem `repo` explícito — nunca o projeto por padrão)
# ---------------------------------------------------------------------------

def _git(repo: str, *args: str) -> dict[str, Any]:
    rc, out, err = _run(["git", "-C", repo, *args])
    if rc != 0:
        return _unavailable("git", (err or out).strip()[:400])
    return {"ok": True, "output": out.rstrip()}


def git_branch(repo: str, all: bool = False) -> dict[str, Any]:
    """Lista branches (local ou com -a)."""
    args = ["branch"]
    if all:
        args.append("-a")
    return _git(repo, *args)


def git_status(repo: str, short: bool = False) -> dict[str, Any]:
    """Status do working tree."""
    args = ["status"]
    if short:
        args.append("--short")
    else:
        args.append("--porcelain=v1")
    return _git(repo, *args)


def git_commit(repo: str, message: str) -> dict[str, Any]:
    """Cria um commit (git commit -m)."""
    if not message.strip():
        raise ValueError("message obrigatória")
    return _git(repo, "commit", "-m", message)


def git_add(repo: str, pathspec: str = ".") -> dict[str, Any]:
    """Adiciona arquivos ao índice."""
    return _git(repo, "add", "--", pathspec)


def git_log(repo: str, limit: int = 20) -> dict[str, Any]:
    """Histórico recente (oneline)."""
    if limit <= 0:
        raise ValueError("limit deve ser > 0")
    return _git(repo, "log", f"-{limit}", "--oneline")


def git_diff(repo: str, staged: bool = False) -> dict[str, Any]:
    """Diff do working tree (ou do índice quando staged)."""
    args = ["diff"]
    if staged:
        args.append("--cached")
    return _git(repo, *args)


def git_checkout(repo: str, branch: str) -> dict[str, Any]:
    """Troca de branch (git checkout)."""
    return _git(repo, "checkout", branch)


def git_fetch(repo: str, remote: str = "origin") -> dict[str, Any]:
    """Busca refs do remoto (git fetch)."""
    return _git(repo, "fetch", remote)


def git_pull(repo: str, remote: str = "origin") -> dict[str, Any]:
    """Puxa do remoto (git pull)."""
    return _git(repo, "pull", remote)


def git_push(repo: str, remote: str = "origin", branch: str = "") -> dict[str, Any]:
    """Envia commits ao remoto (git push). Sem remoto configurado, degrada."""
    args = ["push", remote]
    if branch:
        args.append(branch)
    return _git(repo, *args)


# ---------------------------------------------------------------------------
# Banco de dados (camada Fase 7.5 — degrada graciosamente)
# ---------------------------------------------------------------------------

_DB_UNAVAILABLE = "database layer indisponível (Fase 7.5 — storage/database.py)"

# Database Layer real — injetada via configure_database() (Fase 7.5)
_DB: Any = None


def configure_database(db: Any) -> None:
    """Conecta o catálogo de actions de banco à Database Layer real.

    Chamada pelo launcher com a instância de storage/database.py. Sem
    injeção, as actions continuam degradando graciosamente (ok=False).
    """
    global _DB
    _DB = db


def database_tables() -> dict[str, Any]:
    """Lista tabelas do banco (Database Layer da Fase 7.5)."""
    if _DB is None:
        return _unavailable("database", _DB_UNAVAILABLE)
    try:
        return {"ok": True, "tool": "database", "tables": _DB.tables()}
    except Exception as exc:
        return {"ok": False, "tool": "database", "error": str(exc)}


def database_schema(table: str) -> dict[str, Any]:
    """Schema de uma tabela (Database Layer da Fase 7.5)."""
    if _DB is None:
        return _unavailable("database", _DB_UNAVAILABLE)
    try:
        return {"ok": True, "tool": "database", "table": table,
                "columns": _DB.table_info(table)}
    except Exception as exc:
        return {"ok": False, "tool": "database", "error": str(exc)}


def database_query(query: str) -> dict[str, Any]:
    """Consulta SQL (Database Layer da Fase 7.5, até 100 linhas)."""
    if _DB is None:
        return _unavailable("database", _DB_UNAVAILABLE)
    try:
        rows = _DB.query(query, limit=101)
        return {
            "ok": True,
            "tool": "database",
            "rows": rows[:100],
            "count": len(rows[:100]),
            "truncated": len(rows) > 100,
        }
    except Exception as exc:
        return {"ok": False, "tool": "database", "error": str(exc)}


# ---------------------------------------------------------------------------
# Introspecção (catálogo estático)
# ---------------------------------------------------------------------------

def action_list(category: str = "") -> dict[str, Any]:
    """Lista o catálogo (opcionalmente por categoria)."""
    if category:
        actions = [a for a in CATALOG if a["category"] == category]
    else:
        actions = list(CATALOG)
    return {
        "ok": True,
        "count": len(actions),
        "actions": [a["name"] for a in sorted(actions, key=lambda a: a["name"])],
    }


def action_info(name: str) -> dict[str, Any]:
    """Metadados de uma ação do catálogo."""
    spec = next((a for a in CATALOG if a["name"] == name), None)
    if spec is None:
        raise ValueError(f"ação fora do catálogo: {name}")
    return {
        "name": spec["name"],
        "category": spec["category"],
        "description": spec["description"],
        "permission": spec["name"],
        "params": spec["params"],
    }


def action_schema(name: str) -> dict[str, Any]:
    """Schema de parâmetros de uma ação."""
    spec = next((a for a in CATALOG if a["name"] == name), None)
    if spec is None:
        raise ValueError(f"ação fora do catálogo: {name}")
    return {"ok": True, "name": name, "params": spec["params"]}


def action_validate(name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Valida parâmetros contra o schema da ação (sem executar)."""
    from tools.loader import validate_params

    spec = next((a for a in CATALOG if a["name"] == name), None)
    if spec is None:
        raise ValueError(f"ação fora do catálogo: {name}")
    ok, errors, _filled = validate_params(spec["params"], params)
    return {"ok": True, "valid": ok, "name": name, "errors": errors}


# ---------------------------------------------------------------------------
# Catálogo (56 actions)
# ---------------------------------------------------------------------------

def _spec(
    name: str,
    category: str,
    description: str,
    handler: Any,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "category": category,
        "description": description,
        "handler": handler,
        "params": params or {},
    }


S = {"type": "str"}
I = {"type": "int"}
B = {"type": "bool"}
F = {"type": "float"}
L = {"type": "list"}

CATALOG: list[dict[str, Any]] = [
    # --- Sistema (13) ---
    _spec("system_info", "system", "Informações gerais do sistema", system_info),
    _spec("datetime", "system", "Data/hora atual (ISO)", datetime_now),
    _spec("uptime", "system", "Uptime do sistema", uptime),
    _spec("disk_usage", "system", "Uso de disco", disk_usage,
          {"path": {**S, "default": "/"}}),
    _spec("memory_usage", "system", "Uso de memória RAM/swap", memory_usage),
    _spec("cpu_info", "system", "Núcleos/modelo/carga da CPU", cpu_info),
    _spec("ip_address", "system", "Endereços IP do host", ip_address),
    _spec("system_which", "system", "Localiza executável no PATH", system_which,
          {"required": ["command"], "properties": {"command": S}}),
    _spec("system_hostname", "system", "Nome do host", system_hostname),
    _spec("system_env", "system", "Variáveis de ambiente (nomes; valores por chave)", system_env,
          {"keys": {**L, "default": []}}),
    _spec("system_ping", "system", "Sonda de conectividade TCP", system_ping,
          {"required": ["host"], "properties": {"host": S, "port": {**I, "default": 443}, "timeout": {**F, "default": 1.0}}}),
    _spec("system_user", "system", "Usuário atual", system_user),
    _spec("system_groups", "system", "Grupos do usuário atual", system_groups),
    # --- Processos (4) ---
    _spec("process_list", "process", "Lista processos", process_list),
    _spec("process_info", "process", "Detalhes de um processo", process_info,
          {"required": ["pid"], "properties": {"pid": I}}),
    _spec("process_kill", "process", "Envia sinal a um processo", process_kill,
          {"required": ["pid"], "properties": {"pid": I, "sig": {**I, "default": 15}}}),
    _spec("process_tree", "process", "Árvore de processos (complementar)", process_tree,
          {"pid": {**I, "default": 1}}),
    # --- Docker (4) ---
    _spec("docker_list", "docker", "Lista contêineres", docker_list),
    _spec("docker_status", "docker", "Status do daemon Docker", docker_status),
    _spec("docker_logs", "docker", "Logs de um contêiner", docker_logs,
          {"required": ["container"], "properties": {"container": S, "lines": {**I, "default": 100}}}),
    _spec("docker_stats", "docker", "Métricas de contêineres", docker_stats),
    # --- Serviços (3) ---
    _spec("service_list", "service", "Lista serviços systemd", service_list),
    _spec("service_status", "service", "Status de um serviço", service_status,
          {"required": ["name"], "properties": {"name": S}}),
    _spec("service_logs", "service", "Logs de um serviço", service_logs,
          {"required": ["name"], "properties": {"name": S, "lines": {**I, "default": 50}}}),
    # --- Arquivos (15) ---
    _spec("filesystem_search", "filesystem", "Busca arquivos por padrão", filesystem_search,
          {"required": ["path", "pattern"], "properties": {"path": S, "pattern": S, "recursive": {**B, "default": True}}}),
    _spec("filesystem_read", "filesystem", "Lê arquivo de texto", filesystem_read,
          {"required": ["path"], "properties": {"path": S, "encoding": {**S, "default": "utf-8"}}}),
    _spec("filesystem_write", "filesystem", "Escreve/anexa arquivo", filesystem_write,
          {"required": ["path", "content"], "properties": {"path": S, "content": S, "encoding": {**S, "default": "utf-8"}, "append": {**B, "default": False}}}),
    _spec("filesystem_delete", "filesystem", "Remove arquivo", filesystem_delete,
          {"required": ["path"], "properties": {"path": S}}),
    _spec("filesystem_exists", "filesystem", "Verifica existência", filesystem_exists,
          {"required": ["path"], "properties": {"path": S}}),
    _spec("filesystem_info", "filesystem", "Metadados do arquivo", filesystem_info,
          {"required": ["path"], "properties": {"path": S}}),
    _spec("filesystem_list", "filesystem", "Lista diretório", filesystem_list,
          {"required": ["path"], "properties": {"path": S}}),
    _spec("filesystem_mkdir", "filesystem", "Cria diretório", filesystem_mkdir,
          {"required": ["path"], "properties": {"path": S}}),
    _spec("filesystem_move", "filesystem", "Move/renomeia", filesystem_move,
          {"required": ["source", "destination"], "properties": {"source": S, "destination": S}}),
    _spec("filesystem_copy", "filesystem", "Copia arquivo/árvore", filesystem_copy,
          {"required": ["source", "destination"], "properties": {"source": S, "destination": S}}),
    _spec("filesystem_touch", "filesystem", "Cria arquivo vazio", filesystem_touch,
          {"required": ["path"], "properties": {"path": S}}),
    _spec("filesystem_tree", "filesystem", "Árvore de diretórios", filesystem_tree,
          {"required": ["path"], "properties": {"path": S, "max_depth": {**I, "default": 3}}}),
    _spec("filesystem_hash", "filesystem", "Hash de arquivo", filesystem_hash,
          {"required": ["path"], "properties": {"path": S, "algorithm": {**S, "default": "sha256"}}}),
    _spec("filesystem_archive", "filesystem", "Compacta em ZIP", filesystem_archive,
          {"required": ["path"], "properties": {"path": S, "archive_path": {**S, "default": ""}}}),
    _spec("filesystem_extract", "filesystem", "Extrai ZIP", filesystem_extract,
          {"required": ["archive_path", "destination"], "properties": {"archive_path": S, "destination": S}}),
    # --- Git (10) ---
    _spec("git_branch", "git", "Lista branches", git_branch,
          {"required": ["repo"], "properties": {"repo": S, "all": {**B, "default": False}}}),
    _spec("git_status", "git", "Status do working tree", git_status,
          {"required": ["repo"], "properties": {"repo": S, "short": {**B, "default": False}}}),
    _spec("git_commit", "git", "Cria commit", git_commit,
          {"required": ["repo", "message"], "properties": {"repo": S, "message": S}}),
    _spec("git_add", "git", "Adiciona ao índice", git_add,
          {"required": ["repo"], "properties": {"repo": S, "pathspec": {**S, "default": "."}}}),
    _spec("git_log", "git", "Histórico recente", git_log,
          {"required": ["repo"], "properties": {"repo": S, "limit": {**I, "default": 20}}}),
    _spec("git_diff", "git", "Diff do working tree", git_diff,
          {"required": ["repo"], "properties": {"repo": S, "staged": {**B, "default": False}}}),
    _spec("git_checkout", "git", "Troca de branch", git_checkout,
          {"required": ["repo", "branch"], "properties": {"repo": S, "branch": S}}),
    _spec("git_fetch", "git", "Busca do remoto", git_fetch,
          {"required": ["repo"], "properties": {"repo": S, "remote": {**S, "default": "origin"}}}),
    _spec("git_pull", "git", "Puxa do remoto", git_pull,
          {"required": ["repo"], "properties": {"repo": S, "remote": {**S, "default": "origin"}}}),
    _spec("git_push", "git", "Envia ao remoto", git_push,
          {"required": ["repo"], "properties": {"repo": S, "remote": {**S, "default": "origin"}, "branch": {**S, "default": ""}}}),
    # --- Banco de dados (3) ---
    _spec("database_tables", "database", "Lista tabelas (Fase 7.5)", database_tables),
    _spec("database_schema", "database", "Schema de tabela (Fase 7.5)", database_schema,
          {"required": ["table"], "properties": {"table": S}}),
    _spec("database_query", "database", "Consulta SQL (Fase 7.5)", database_query,
          {"required": ["query"], "properties": {"query": S}}),
    # --- Introspecção (4) ---
    _spec("action_list", "introspection", "Lista o catálogo de ações (complementar)", action_list,
          {"category": {**S, "default": ""}}),
    _spec("action_info", "introspection", "Metadados de uma ação", action_info,
          {"required": ["name"], "properties": {"name": S}}),
    _spec("action_schema", "introspection", "Schema de parâmetros de uma ação", action_schema,
          {"required": ["name"], "properties": {"name": S}}),
    _spec("action_validate", "introspection", "Valida params contra schema", action_validate,
          {"required": ["name", "params"], "properties": {"name": S, "params": {"type": "dict"}}}),
]

ACTIONS_COUNT = len(CATALOG)

CATEGORIES: dict[str, int] = {}
for _entry in CATALOG:
    CATEGORIES[_entry["category"]] = CATEGORIES.get(_entry["category"], 0) + 1
