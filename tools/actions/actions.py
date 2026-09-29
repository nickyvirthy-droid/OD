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
import ipaddress
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
from typing import Any, Optional

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.tools.actions")


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


def cpu_temp() -> dict[str, Any]:
    """Temperatura do servidor (zones térmicos do kernel, via
    /sys/class/thermal e /sys/class/hwmon — stdlib, sem root).

    Motivação (2026-09-27): o dono perguntou a temperatura do servidor no
    chat e o LLM recusou/alucinou — não existia action para o dado real.
    """
    readings: list[dict[str, Any]] = []
    try:
        for zone in sorted(os.listdir("/sys/class/thermal")):
            if not zone.startswith("thermal_zone"):
                continue
            base = f"/sys/class/thermal/{zone}"
            try:
                with open(f"{base}/temp", encoding="utf-8") as fh:
                    millideg = int(fh.read().strip())
                with open(f"{base}/type", encoding="utf-8") as fh:
                    ztype = fh.read().strip() or zone
                readings.append(
                    {"zone": zone, "type": ztype, "celsius": round(millideg / 1000, 1)}
                )
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    if not readings:
        # Fallback hwmon (máquinas sem thermal_zone exposto).
        try:
            for hw in sorted(os.listdir("/sys/class/hwmon")):
                base = f"/sys/class/hwmon/{hw}"
                try:
                    with open(f"{base}/name", encoding="utf-8") as fh:
                        name = fh.read().strip() or hw
                    for label_file in sorted(os.listdir(base)):
                        if not label_file.startswith("temp") or not label_file.endswith("_input"):
                            continue
                        with open(f"{base}/{label_file}", encoding="utf-8") as fh:
                            millideg = int(fh.read().strip())
                        readings.append(
                            {"zone": f"{hw}/{label_file}", "type": name,
                             "celsius": round(millideg / 1000, 1)}
                        )
                except (OSError, ValueError):
                    continue
        except OSError:
            pass
    if not readings:
        return _unavailable(
            "cpu_temp",
            "nenhum sensor térmico exposto (/sys/class/thermal e hwmon vazios)",
        )
    hottest = max(readings, key=lambda r: r["celsius"])
    return {
        "ok": True,
        "readings": readings,
        "hottest": hottest,
        "celsius": hottest["celsius"],
    }


# ---------------------------------------------------------------------------
# Home Assistant (v1.8.0) — o sistema tem HA no ar (health "HA alcançável")
# com 40 entidades reais, mas o catálogo do chat não expunha NADA: perguntas
# de clima/luzes caíam no LLM que alucinava ("23°C" inventado p/ cidade).
# As actions abaixo leem o HA via IoTManager/HAClient injetado pelo launcher
# (configure_ha_client); SEM client configurado degradam com ok=False e a
# resposta cai para o LLM — igual às demais actions do catálogo.
# ---------------------------------------------------------------------------

_HA_CLIENT: Optional[Any] = None
# Confirmações pendentes do controle do lar (v1.8.0 luzes; v1.9.0 também
# tomadas/dispositivos): chave (user_id, entity_id, on) -> timestamp da
# intenção. 2 passos: 'liga a luz/tomada X' cria a intenção e responde
# pedindo confirmação; o SIM do mesmo user executa.
# Expira em 120s (regra de _device_confirm_check).
_LIGHT_CONFIRMATIONS: dict[tuple[str, str, bool], float] = {}
_LIGHT_CONFIRM_TTL = 120.0


def configure_ha_client(client: Any) -> None:
    """Injeta o HAClient/IoTManager do launcher (idempotente)."""
    global _HA_CLIENT
    _HA_CLIENT = client


def _ha() -> Any:
    if _HA_CLIENT is None:
        return None
    return _HA_CLIENT


def _ha_states() -> Optional[list[Any]]:
    client = _ha()
    if client is None:
        return None
    try:
        return client.list_states()
    except Exception as exc:  # HAError ou rede — degrada, nunca estoura
        log.warning("ha action: falha ao listar entidades", error=str(exc))
        return None


def _ha_state(entity_id: str) -> Optional[Any]:
    client = _ha()
    if client is None:
        return None
    try:
        return client.get_state(entity_id)
    except Exception as exc:
        log.warning("ha action: falha ao ler entidade", entity_id=entity_id,
                    error=str(exc))
        return None


def ha_weather() -> dict[str, Any]:
    """Clima REAL da região da casa, do Home Assistant (weather.*).

    Motivação (2026-09-28): 'temperatura agora em presidente venceslau'
    era respondida com temperatura INVENTADA pelo LLM ('23°C' e, quando o
    dono disse 'mentira', repetiu a mentira). O HA tem weather.forecast_casa
    com leitura real da região — o dado agora vem da fonte.
    """
    states = _ha_states()
    if states is None:
        return _unavailable(
            "ha_weather",
            "Home Assistant não configurado ou inacessível",
        )
    weather = [s for s in states if s.entity_id.startswith("weather.")]
    if not weather:
        return _unavailable(
            "ha_weather", "nenhuma entidade weather.* no Home Assistant"
        )
    w = weather[0]
    attrs = w.attributes or {}
    temp = attrs.get("temperature")
    return {
        "ok": True,
        "entity": w.entity_id,
        "condition": w.state,
        "temperature": temp,
        "temperature_unit": attrs.get("temperature_unit", "°C"),
        "humidity": attrs.get("humidity"),
        "wind_speed": attrs.get("wind_speed"),
        "wind_speed_unit": attrs.get("wind_speed_unit"),
        "pressure": attrs.get("pressure"),
        "dew_point": attrs.get("dew_point"),
        "uv_index": attrs.get("uv_index"),
        "cloud_coverage": attrs.get("cloud_coverage"),
    }


def ha_lights() -> dict[str, Any]:
    """Estado das luzes/interruptores do HA (switch.*/light.*) — leitura.

    O dono pergunta 'que luzes estão acesas' e recebe o estado REAL das
    entidades (leitura; controle liga/desliga fica para fase futura).
    """
    states = _ha_states()
    if states is None:
        return _unavailable(
            "ha_lights",
            "Home Assistant não configurado ou inacessível",
        )
    lights: list[dict[str, Any]] = []
    for s in states:
        domain = s.entity_id.split(".", 1)[0]
        if domain not in ("switch", "light"):
            continue
        if s.state in ("unavailable", "unknown", None):
            continue
        name = (s.attributes or {}).get("friendly_name") or s.entity_id
        lights.append(
            {"entity": s.entity_id, "name": name, "state": s.state,
             "on": s.state == "on"}
        )
    on_count = sum(1 for l in lights if l["on"])
    return {
        "ok": True,
        "lights": lights,
        "total": len(lights),
        "on": on_count,
        "off": len(lights) - on_count,
    }


def _light_name_for(entity_id: str, states: Optional[list[Any]]) -> str:
    """friendly_name da entidade (ou o próprio id) dentro da lista dada."""
    for s in states or []:
        if s.entity_id == entity_id:
            return (s.attributes or {}).get("friendly_name") or entity_id
    return entity_id


def _light_confirm_check(
    user_id: str, entity_id: str, on: bool,
    *, now: Optional[float] = None,
) -> str:
    """Estado da confirmação de 2 passos para a intenção (user, entidade,
    ação) — luz OU tomada/dispositivo (v1.9.0).

    Returns:
        "required" — primeira menção à intenção (ou anterior expirada):
        registra now e pede confirmação.
        "confirmed" — o mesmo user confirmou dentro do TTL.
    """
    stamp = time.time() if now is None else now
    key = (user_id, entity_id, bool(on))
    pending = _LIGHT_CONFIRMATIONS.get(key)
    if pending is not None and (stamp - pending) <= _LIGHT_CONFIRM_TTL:
        return "confirmed"
    _LIGHT_CONFIRMATIONS[key] = stamp
    return "required"


def peek_pending_light_confirmation(user_id: str) -> Optional[tuple[str, bool]]:
    """Intenção de controle pendente mais recente do user (dentro do TTL).

    O 'sim' do user não gera intenção de action — o orchestrator consulta
    aqui o que está pendente e executa. NÃO consome: o consumo acontece
    dentro de ha_device_control APÓS a execução bem-sucedida. Entradas
    expiradas são descartadas na varredura.
    """
    now = time.time()
    best: Optional[tuple[str, bool]] = None
    best_stamp = -1.0
    for (uid, entity_id, on), stamp in list(_LIGHT_CONFIRMATIONS.items()):
        if uid != user_id:
            continue
        if (now - stamp) > _LIGHT_CONFIRM_TTL:
            _LIGHT_CONFIRMATIONS.pop((uid, entity_id, on), None)
            continue
        if stamp > best_stamp:
            best_stamp = stamp
            best = (entity_id, bool(on))
    return best


def ha_device_control(
    entity_id: str = "", on: bool = True, user_id: str = "", termo: str = "",
) -> dict[str, Any]:
    """Liga/desliga UM dispositivo do HA (luz OU tomada), com gate e
    confirmação.

    Camadas (v1.8.0/1.8.1/1.9.0):
    1. Permissão: a action fica FORA da allowlist do papel user — só o
       admin/dono chega aqui (negação do Registry, denied).
    2. Alvo específico obrigatório: entity_id resolvido pela intenção;
       genérico ("as luzes") nunca executa em lote.
    3. Confirmação de 2 passos: 1ª chamada da intenção registra e pede
       confirmação; o SIM do mesmo user dentro de 120s executa.

    v1.9.0: era ha_light_control — mesmas camadas, domínio switch
    explicitamente na fala ('tomada') e na mensagem.
    """
    if not entity_id:
        if termo:
            return {
                "ok": False,
                "error": "entidade_inexistente",
                "hint": f"'{termo}' não existe no Home Assistant",
            }
        return {
            "ok": False,
            "error": "alvo_obrigatorio",
            "hint": "diga qual luz ou tomada (ex: 'liga a luz da cozinha')",
        }
    client = _ha()
    if client is None:
        return _unavailable("ha_device_control", "Home Assistant não configurado")
    # A entidade tem que existir e ser atuador (switch/light — v1.9.0:
    # tomadas e interruptores SONOFF já são o domínio switch do dono).
    entity = None
    try:
        entity = client.get_state(entity_id)
    except Exception as exc:
        return _unavailable("ha_device_control", f"falha ao ler {entity_id}: {exc}")
    if entity is None:
        return {
            "ok": False,
            "error": "entidade_inexistente",
            "hint": f"'{entity_id}' não existe no Home Assistant",
        }
    domain = entity_id.split(".", 1)[0]
    if domain not in ("switch", "light"):
        return {
            "ok": False,
            "error": "nao_e_luz",
            "hint": (
                f"'{entity_id}' não é luz/tomada/interruptor "
                f"(domínio '{domain}' não é controlável aqui)"
            ),
        }
    states = _ha_states()
    name = _light_name_for(entity_id, states)
    # Confirmação de 2 passos (por user + luz + ação).
    stage = _light_confirm_check(user_id or "desconhecido", entity_id, on)
    if stage == "required":
        return {
            "ok": True,
            "needs_confirmation": True,
            "entity": entity_id,
            "name": name,
            "action": "ligar" if on else "desligar",
            "current": entity.state,
            "hint": (
                f"Confirmar: ligar '{name}'? Responda 'sim' para executar "
                "(confirmação vale por 2 minutos)."
            ),
        }
    # Confirmado: executa o serviço no HA.
    service = "turn_on" if on else "turn_off"
    try:
        client.call_service(domain, service, entity_id=entity_id)
    except Exception as exc:
        return _unavailable(
            "ha_device_control", f"falha ao {service} {entity_id}: {exc}"
        )
    # Lê o estado pós-comando (o HA pode levar um instante; o valor lido
    # é best-effort — o comando foi aceito).
    after = None
    try:
        post = client.get_state(entity_id)
        after = post.state if post else None
    except Exception:
        pass
    # Consome a confirmação (um uso).
    _LIGHT_CONFIRMATIONS.pop((user_id or "desconhecido", entity_id, bool(on)), None)
    return {
        "ok": True,
        "executed": True,
        "entity": entity_id,
        "name": name,
        "action": "ligar" if on else "desligar",
        "state_after": after,
    }


def ha_summary() -> dict[str, Any]:
    """Raio-X do lar no HA: clima, luzes, pessoas, bateria do celular e
    rede (roteador). Somente leitura — a visão geral que o dono pede."""
    states = _ha_states()
    if states is None:
        return _unavailable(
            "ha_summary",
            "Home Assistant não configurado ou inacessível",
        )
    weather = next(
        (s for s in states if s.entity_id.startswith("weather.")), None
    )
    people = [
        {"entity": s.entity_id, "state": s.state}
        for s in states if s.entity_id.startswith("person.")
    ]
    batteries = []
    for s in states:
        if s.entity_id.endswith("_battery_level") and s.state not in (
            "unknown", "unavailable"
        ):
            name = (s.attributes or {}).get("friendly_name") or s.entity_id
            batteries.append({"name": name, "level": s.state})
    router: dict[str, Any] = {}
    for s in states:
        if "router" in s.entity_id and "external_ip" in s.entity_id:
            router["external_ip"] = s.state
        if "router" in s.entity_id and "download_speed" in s.entity_id:
            router["download_kib_s"] = s.state
        if "router" in s.entity_id and "upload_speed" in s.entity_id:
            router["upload_kib_s"] = s.state
    lights_out = ha_lights()
    lights_data = lights_out if lights_out.get("ok") else {"total": 0, "on": 0}
    w_attrs = (weather.attributes or {}) if weather else {}
    return {
        "ok": True,
        "total_entities": len(states),
        "weather": {
            "condition": weather.state if weather else None,
            "temperature": w_attrs.get("temperature"),
            "temperature_unit": w_attrs.get("temperature_unit", "°C"),
            "humidity": w_attrs.get("humidity"),
        } if weather else None,
        "lights": {
            "total": lights_data.get("total", 0),
            "on": lights_data.get("on", 0),
        },
        "people": people,
        "batteries": batteries,
        "router": router,
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


def listening_ports() -> dict[str, Any]:
    """Portas TCP em escuta (via /proc/net/tcp — stdlib, sem root para as
    do próprio usuário; portas de outros usuários aparecem sem processo)."""
    # Mapeia inode → processo (via /proc/<pid>/fd, best-effort).
    inode_process: dict[str, str] = {}
    try:
        for pid_dir in os.listdir("/proc"):
            if not pid_dir.isdigit():
                continue
            try:
                with open(f"/proc/{pid_dir}/comm", encoding="utf-8") as fh:
                    comm = fh.read().strip()
                fd_dir = f"/proc/{pid_dir}/fd"
                for fd in os.listdir(fd_dir):
                    try:
                        link = os.readlink(os.path.join(fd_dir, fd))
                        if link.startswith("socket:["):
                            inode = link[8:-1]
                            inode_process.setdefault(inode, comm)
                    except OSError:
                        continue
            except (OSError, PermissionError):
                continue
    except OSError:
        pass

    def _parse(path: str) -> list[dict[str, Any]]:
        ports: list[dict[str, Any]] = []
        try:
            with open(path, encoding="utf-8") as fh:
                fh.readline()  # cabeçalho
                for line in fh:
                    cols = line.split()
                    if len(cols) < 4 or cols[3] != "0A":  # 0A = LISTEN
                        continue
                    local = cols[1]
                    port = int(local.split(":")[1], 16)
                    address_hex = local.split(":")[0]
                    if len(address_hex) == 8:  # IPv4
                        raw = bytes.fromhex(address_hex)
                        addr = ".".join(str(b) for b in raw[::-1])
                    else:  # IPv6: 4 DWORDs little-endian (formato do kernel)
                        raw = bytes.fromhex(address_hex)
                        dwords = [
                            int.from_bytes(raw[i:i + 4], "little")
                            for i in range(0, 16, 4)
                        ]
                        groups: list[int] = []
                        for dword in dwords:
                            groups.append((dword >> 16) & 0xFFFF)
                            groups.append(dword & 0xFFFF)
                        value = sum(
                            g << (16 * (7 - i)) for i, g in enumerate(groups)
                        )
                        addr = str(ipaddress.IPv6Address(value))
                    inode = cols[9] if len(cols) > 9 else ""
                    ports.append({
                        "port": port,
                        "addr": addr,
                        "process": inode_process.get(inode, ""),
                    })
        except OSError:
            pass
        return ports

    seen: dict[int, dict[str, Any]] = {}
    for entry in _parse("/proc/net/tcp") + _parse("/proc/net/tcp6"):
        seen[entry["port"]] = entry
    ports = sorted(seen.values(), key=lambda e: e["port"])
    return {"ok": True, "count": len(ports), "ports": ports}


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


def network_hosts() -> dict[str, Any]:
    """Hosts da rede local via /proc/net/arp (vizinhança real IP+MAC).

    Leitura 100% stdlib e sem rede ativa — responde "quantos dispositivos /
    pessoas estão conectados na rede" com a tabela ARP do kernel (entradas
    válidas = endereço MAC real). Complementar OD (não existia no NV).
    """
    raw = _read_proc("net/arp")
    if not raw:
        return _unavailable("network", "/proc/net/arp indisponível")
    hosts: list[dict[str, Any]] = []
    for line in raw.splitlines()[1:]:  # pula o cabeçalho
        parts = line.split()
        if len(parts) < 6:
            continue
        ip, _hw_type, flags, mac, _mask, iface = parts[:6]
        if mac == "00:00:00:00:00:00":
            continue  # entrada sem vizinho resolvido
        hosts.append({
            "ip": ip,
            "mac": mac,
            "interface": iface,
            "state": "reachable" if flags == "0x2" else "stale",
        })
    hosts.sort(key=lambda h: h["ip"])
    return {"ok": True, "count": len(hosts), "hosts": hosts}


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
    _spec("cpu_temp", "system", "Temperatura do servidor (zones térmicos)", cpu_temp),
    _spec("ha_weather", "iot", "Clima real da região da casa (Home Assistant)", ha_weather),
    _spec("ha_lights", "iot", "Estado das luzes e interruptores (Home Assistant)", ha_lights),
    _spec("ha_summary", "iot", "Raio-X do lar: clima, luzes, pessoas, bateria, rede", ha_summary),
    _spec("ha_device_control", "iot", "Liga/desliga UMA luz ou tomada específica (dono, com confirmação)", ha_device_control,
          {"required": ["entity_id"], "properties": {
              "entity_id": S,
              "on": {**B, "default": True},
              "user_id": {**S, "default": ""},
              "termo": {**S, "default": ""},
          }}),
    _spec("ip_address", "system", "Endereços IP do host", ip_address),
    _spec("listening_ports", "system", "Portas TCP em escuta", listening_ports),
    
    _spec("system_which", "system", "Localiza executável no PATH", system_which,
          {"required": ["command"], "properties": {"command": S}}),
    _spec("system_hostname", "system", "Nome do host", system_hostname),
    _spec("system_env", "system", "Variáveis de ambiente (nomes; valores por chave)", system_env,
          {"keys": {**L, "default": []}}),
    _spec("system_ping", "system", "Sonda de conectividade TCP", system_ping,
          {"required": ["host"], "properties": {"host": S, "port": {**I, "default": 443}, "timeout": {**F, "default": 1.0}}}),
    _spec("system_user", "system", "Usuário atual", system_user),
    _spec("system_groups", "system", "Grupos do usuário atual", system_groups),
    # --- Rede (1, complementar OD) ---
    _spec("network_hosts", "system", "Dispositivos na rede local (ARP)", network_hosts),
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
