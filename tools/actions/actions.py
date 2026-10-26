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

import base64
import datetime
import fnmatch
import hashlib
import hmac
import ipaddress
import json
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


#: Raízes sysfs dos sensores térmicos — constante nomeada (não literal
#: espalhado) para os testes apontarem a um sysfs de fixture em hosts sem
#: sensor legível (o runner do CI não tem /sys/class/thermal com zonas).
#: O comportamento em produção continua idêntico.
THERMAL_DIR = "/sys/class/thermal"
HWMON_DIR = "/sys/class/hwmon"


def cpu_temp() -> dict[str, Any]:
    """Temperatura do servidor (zones térmicos do kernel, via
    THERMAL_DIR e HWMON_DIR — stdlib, sem root).

    Motivação (2026-09-27): o dono perguntou a temperatura do servidor no
    chat e o LLM recusou/alucinou — não existia action para o dado real.
    """
    readings: list[dict[str, Any]] = []
    try:
        for zone in sorted(os.listdir(THERMAL_DIR)):
            if not zone.startswith("thermal_zone"):
                continue
            base = f"{THERMAL_DIR}/{zone}"
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
            for hw in sorted(os.listdir(HWMON_DIR)):
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
# tomadas/dispositivos): chave (user_id, entity_id, on) -> (timestamp da
# intenção, alvo falado pelo user). 2 passos: 'liga a luz/tomada X' cria a
# intenção e responde pedindo confirmação; o SIM do mesmo user executa —
# e o alvo falado permite conferir a coerência do 'sim' (v1.9.1: 'sim'
# seguido de OUTRO dispositivo não executa o anterior).
# Expira em 120s (regra de _device_confirm_check).
_LIGHT_CONFIRMATIONS: dict[tuple[str, str, bool], tuple[float, str]] = {}
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
        log.warn("ha action: falha ao listar entidades", error=str(exc))
        return None


def _ha_state(entity_id: str) -> Optional[Any]:
    client = _ha()
    if client is None:
        return None
    try:
        return client.get_state(entity_id)
    except Exception as exc:
        log.warn("ha action: falha ao ler entidade", entity_id=entity_id,
                 error=str(exc))
        return None


# Códigos WMO (Open-Meteo) → descrição pt-BR (o modelo nunca traduz —
# o formatter entrega o texto pronto).
_WMO_PT: dict[int, str] = {
    0: "céu limpo", 1: "predominantemente limpo", 2: "parcialmente nublado",
    3: "nublado", 45: "neblina", 48: "neblina com geada",
    51: "garoa leve", 53: "garoa", 55: "garoa forte",
    56: "garoa congelante leve", 57: "garoa congelante forte",
    61: "chuva fraca", 63: "chuva", 65: "chuva forte",
    66: "chuva congelante fraca", 67: "chuva congelante forte",
    71: "neve fraca", 73: "neve", 75: "neve forte", 77: "grãos de neve",
    80: "pancadas leves", 81: "pancadas de chuva", 82: "pancadas fortes",
    85: "pancadas de neve fracas", 86: "pancadas de neve fortes",
    95: "tempestade", 96: "tempestade com granizo leve",
    99: "tempestade com granizo forte",
}

def _wmo_condition(raw_code: Any) -> str:
    """Código WMO (Open-Meteo) → descrição pt-BR.

    0 é código VÁLIDO (céu limpo) — a conversão é falsy-safe:
    `is not None`, nunca `or` (o 0 seria engolido)."""
    code = int(raw_code) if raw_code is not None else -1
    return _WMO_PT.get(code, f"código {code}")


def weather_city(city: str) -> dict[str, Any]:
    """Clima REAL de uma cidade informada, via Open-Meteo (sem chave).

    Motivação (2026-09-30, §14): 'qual a temperatura em presidente
    venceslau' recebia o clima DA CASA (weather.* do HA é da região do
    servidor) — resposta honesta sobre a fonte, mas o pedido não era
    atendido. A leitura aqui é de uma API externa gratuita com geocoding
    próprio; sem rede, degrada com mensagem clara (nunca inventa).
    """
    import json as _json
    import urllib.parse
    import urllib.request

    city = (city or "").strip()
    if not city:
        return {"ok": False, "error": "cidade_vazia",
                "message": "Informe a cidade: 'clima em presidente venceslau'."}

    def _get(url: str, timeout: float = 8.0) -> Optional[dict]:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return _json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            log.warn("weather_city: falha na chamada externa", url=url,
                        error=str(exc))
            return None

    geo = _get(
        "https://geocoding-api.open-meteo.com/v1/search?"
        + urllib.parse.urlencode(
            {"name": city, "count": 1, "language": "pt", "format": "json"}
        )
    )
    if not geo or not geo.get("results"):
        return {"ok": False, "error": "cidade_nao_encontrada",
                "message": f"Não encontrei a cidade '{city}' no geocoding."}
    r = geo["results"][0]
    lat, lon = r.get("latitude"), r.get("longitude")
    nome = ", ".join(
        str(r[k]) for k in ("name", "admin1", "country")
        if r.get(k) and str(r[k]).strip()
    )
    forecast = _get(
        "https://api.open-meteo.com/v1/forecast?"
        + urllib.parse.urlencode({
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,"
                       "apparent_temperature,weather_code,wind_speed_10m",
        })
    )
    if not forecast or not forecast.get("current"):
        return {"ok": False, "error": "fonte_indisponivel",
                "message": "Serviço de clima indisponível agora — não invento o dado."}
    cur = forecast["current"]
    raw_code = cur.get("weather_code")
    return {
        "ok": True,
        "city": nome,
        "latitude": lat,
        "longitude": lon,
        "temperature": cur.get("temperature_2m"),
        "temperature_unit": forecast.get("current_units", {}).get(
            "temperature_2m", "°C"),
        "apparent_temperature": cur.get("apparent_temperature"),
        "humidity": cur.get("relative_humidity_2m"),
        "wind_speed": cur.get("wind_speed_10m"),
        "wind_speed_unit": forecast.get("current_units", {}).get(
            "wind_speed_10m", "km/h"),
        "condition": _wmo_condition(raw_code),
        "source": "Open-Meteo",
        "observed_at": cur.get("time"),
    }


# Par de moedas → descrição pt-BR (cotação SEMPRE contra o real — a casa
# fala português; o dono pergunta 'quanto está o dólar', não 'USD/BRL').
_MOEDAS_PT = {
    "USD": "dólar americano",
    "EUR": "euro",
    "GBP": "libra esterlina",
    "ARS": "peso argentino",
    "JPY": "iene japonês",
    "CNY": "yuan chinês",
    "CAD": "dólar canadense",
    "AUD": "dólar australiano",
    "CHF": "franco suíço",
    "BTC": "bitcoin",
}

# Alias da fala do dono → código da moeda ('dólar'/'dolar' → USD).
_MOEDAS_ALIAS = {
    "dolar": "USD", "dólar": "USD", "dolares": "USD", "dólares": "USD",
    "dollar": "USD", "usd": "USD",
    "euro": "EUR", "eur": "EUR", "euros": "EUR",
    "libra": "GBP", "libras": "GBP", "gbp": "GBP",
    "peso": "ARS", "pesos": "ARS", "ars": "ARS",
    "iene": "JPY", "ienes": "JPY", "jpy": "JPY", "yen": "JPY",
    "yuan": "CNY", "cny": "CNY", "renminbi": "CNY",
    "dolar canadense": "CAD", "cad": "CAD",
    "dolar australiano": "AUD", "aud": "AUD",
    "franco suico": "CHF", "franco suíço": "CHF", "chf": "CHF",
    "bitcoin": "BTC", "btc": "BTC",
}


def exchange_rate(moeda: str) -> dict[str, Any]:
    """Cotação REAL de moeda contra o real, via AwesomeAPI (sem chave).

    Motivação (2026-09-30, §12.1): 'quanto está a cotação do dólar hoje?'
    era respondida com valor INVENTADO pelo LLM ('US$ 5.20' — e a mentira
    entrou no cache e renascia). A action intercepta a pergunta ANTES do
    modelo: dado real da fonte ou erro honesto (nunca inventa).
    """
    import json
    import urllib.parse
    import urllib.request

    bruto = (moeda or "").strip().lower()
    if not bruto:
        return {"ok": False, "error": "moeda_vazia",
                "message": "Informe a moeda: 'cotação do dólar', 'euro'."}

    codigo = _MOEDAS_ALIAS.get(bruto)
    if codigo is None:
        # Última chance: sigla de 3 letras direto (ex: 'usd-brl').
        sigla = bruto.replace("-brl", "").replace("brl", "").strip()
        if len(sigla) == 3 and sigla.isalpha():
            codigo = sigla.upper()
    if codigo is None:
        return {"ok": False, "error": "moeda_desconhecida",
                "message": f"Não conheço a moeda '{moeda}'. Tente: "
                           "dólar, euro, libra, peso, iene, yuan, bitcoin."}

    url = (
        "https://economia.awesomeapi.com.br/json/last/"
        + urllib.parse.quote(f"{codigo}-BRL")
    )
    try:
        with urllib.request.urlopen(url, timeout=8.0) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        log.warn("exchange_rate: falha na chamada externa", url=url,
                    error=str(exc))
        return {"ok": False, "error": "fonte_indisponivel",
                "message": "Serviço de câmbio indisponível agora — "
                           "não invento o dado."}

    entrada = payload.get(f"{codigo}BRL")
    if not isinstance(entrada, dict) or not entrada.get("bid"):
        return {"ok": False, "error": "par_indisponivel",
                "message": f"Sem cotação de {codigo} contra o real agora."}
    return {
        "ok": True,
        "codigo": codigo,
        "moeda": _MOEDAS_PT.get(codigo, codigo),
        "bid": float(entrada["bid"]),
        "ask": float(entrada["ask"]) if entrada.get("ask") else None,
        "variacao_pct": float(entrada["pctChange"]) if entrada.get("pctChange") else None,
        "maximo": float(entrada["high"]) if entrada.get("high") else None,
        "minimo": float(entrada["low"]) if entrada.get("low") else None,
        "timestamp": int(entrada["timestamp"]) if entrada.get("timestamp") else None,
        "source": "AwesomeAPI",
    }


# ---------------------------------------------------------------------------
# SAÚDE — referência médica determinística (Parte C NOMAD, v1.25.0)
#
# Espelha o "affirmative gate" do NOMAD: consulta SÓ fonte curada de
# domínio público (CDC/NIH/NCCIH) ou bula oficial FDA (openFDA), com
# disclaimer obrigatório no formatador. Conteúdo médico autoral é vedado;
# quando não há dado, a resposta é "não achei" — NUNCA cai no LLM.
# ---------------------------------------------------------------------------


def _saude_label_do_medicamento(
    med: dict[str, Any],
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Busca o label FDA (genérico do lexicon) — 1º que responder."""
    from tools.saude import dados

    label: Optional[dict[str, Any]] = None
    motivo: Optional[str] = None
    for generico in med.get("genericos_fda", []):
        label, motivo = dados.openfda_label(generico)
        if label is not None:
            return label, None
    return None, motivo or "sem_resultado"


def saude_condicao(texto: str) -> dict[str, Any]:
    """Cuidados caseiros/naturais CURADOS para a condição citada.

    Curadoria versionada em tools/saude/collections (CDC, NIH/NCCIH,
    MedlinePlus — domínio público, com atribuição). Condição desconhecida
    devolve ``ok=True`` com ``condicao=None``: a resposta honesta é
    'não consta na minha referência', nunca LLM solto em saúde.
    """
    from tools.saude import dados

    pedido = (texto or "").strip()
    if not pedido:
        return {"ok": True, "condicao": None, "pedido": ""}
    cond = dados.achar_condicao(pedido)
    if cond is None:
        return {"ok": True, "condicao": None, "pedido": pedido[:120]}
    cuidados = dados.cuidados_da_condicao(cond["slug_en"])
    return {
        "ok": True,
        "condicao": cond["rotulo"],
        "slug": cond["slug"],
        "categoria": cond["categoria"],
        "cuidados": cuidados,
        "fontes": sorted({c["fonte"] for c in cuidados}),
        "pedido": pedido[:120],
    }


def saude_interacoes(texto: str) -> dict[str, Any]:
    """Interação entre os dois medicamentos citados — bula FDA (openFDA).

    Devolve o texto VERBATIM do campo ``drug_interactions`` de cada label
    (truncado no formatador) e o fato de cada label mencionar o outro.
    Medicamento sem label na FDA (ex.: dipirona, não comercializada nos
    EUA) é respondido como ausência — nunca com interação inventada.
    """
    from tools.saude import dados

    achados = dados.extrair_medicamentos((texto or "").strip())
    if len(achados) < 2:
        return {
            "ok": True,
            "incompleto": True,
            "medicamentos": [m["nome"] for m in achados],
        }
    a, b = achados[0], achados[1]
    itens: list[dict[str, Any]] = []
    for med, outro in ((a, b), (b, a)):
        termos_outro = [t.casefold() for t in outro["aliases"]] + [
            g.casefold() for g in outro["genericos_fda"]
        ]
        label, motivo = _saude_label_do_medicamento(med)
        if label is None:
            itens.append({
                "nome": med["nome"],
                "genericos_fda": med["genericos_fda"],
                "encontrado": False,
                "motivo": motivo,
                "interacoes": [],
                "menciona_outro": False,
            })
            continue
        brutos = dados.lista_campo(label, "drug_interactions")
        texto_int = " ".join(brutos).casefold()
        itens.append({
            "nome": med["nome"],
            "genericos_fda": med["genericos_fda"],
            "encontrado": True,
            "rotulo_fda": ", ".join(
                label.get("openfda", {}).get("generic_name", [])[:2]
            ),
            "interacoes": [dados.truncar(t) for t in brutos[:3]],
            "menciona_outro": any(t in texto_int for t in termos_outro),
        })
    return {
        "ok": True,
        "incompleto": False,
        "nomes": [a["nome"], b["nome"]],
        "itens": itens,
    }


def saude_medicamento(texto: str) -> dict[str, Any]:
    """Bula FDA (openFDA) do medicamento citado — indicações e avisos."""
    from tools.saude import dados

    achados = dados.extrair_medicamentos((texto or "").strip())
    if not achados:
        return {"ok": True, "incompleto": True, "medicamentos": []}
    med = achados[0]
    label, motivo = _saude_label_do_medicamento(med)
    base = {
        "ok": True,
        "incompleto": False,
        "nome": med["nome"],
        "genericos_fda": med["genericos_fda"],
    }
    if label is None:
        return {**base, "encontrado": False, "motivo": motivo}
    return {
        **base,
        "encontrado": True,
        "rotulo_fda": ", ".join(
            label.get("openfda", {}).get("generic_name", [])[:3]
        ),
        "indicacoes": [
            dados.truncar(t)
            for t in dados.lista_campo(label, "indications_and_usage")[:2]
        ],
        "avisos": [
            dados.truncar(t)
            for t in (
                dados.lista_campo(label, "do_not_use")
                + dados.lista_campo(label, "warnings_and_cautions")
            )[:2]
        ],
    }


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
    *, now: Optional[float] = None, alvo: str = "",
) -> str:
    """Estado da confirmação de 2 passos para a intenção (user, entidade,
    ação) — luz OU tomada/dispositivo (v1.9.0).

    Args:
        alvo: dispositivo que o user nomeou no comando ('corredor');
        guardado para a conferência de coerência do 'sim' (v1.9.1).

    Returns:
        "required" — primeira menção à intenção (ou anterior expirada):
        registra now e pede confirmação.
        "confirmed" — o mesmo user confirmou dentro do TTL.
    """
    stamp = time.time() if now is None else now
    key = (user_id, entity_id, bool(on))
    pending = _LIGHT_CONFIRMATIONS.get(key)
    if pending is not None and (stamp - pending[0]) <= _LIGHT_CONFIRM_TTL:
        return "confirmed"
    _LIGHT_CONFIRMATIONS[key] = (stamp, alvo)
    return "required"


def drop_pending_light_confirmation(user_id: str) -> None:
    """Descarta TODAS as intenções pendentes do user (incoerência v1.9.1):
    confirmação que não bate com o que está pendente invalida a intenção
    velha — o dono precisa pedir de novo.
    """
    for key in [k for k in _LIGHT_CONFIRMATIONS if k[0] == user_id]:
        _LIGHT_CONFIRMATIONS.pop(key, None)


# Palavras de LUGAR usadas para conferir a coerência do 'sim': se o 'sim'
# menciona um lugar que NÃO está no alvo pendente (nem no nome nem no id
# da entidade), a confirmação não bate (v1.9.1).
_PLACE_WORDS = re.compile(
    r"\b(sala|cozinha|quarto|su[íi]te|corredor|varanda|[áa]rea|oficina|"
    r"garagem|escrit[óo]rio|banheiro|lavanderia|quintal|jardim| servidor|"
    r"notebook|escritorio)\b",
    re.IGNORECASE,
)


def confirm_texts_match_pending(
    text: str, alvo: str, entity_id: str,
) -> bool:
    """Coerência do 'sim' (v1.9.1): a confirmação menciona LUGAR que não
    está no pedido pendente? Caso real (29/09): pendente 'liga a luz do
    corredor' → dono disse 'sim' → executa; a resposta da execução ANTERIOR
    vazou como se fosse a deste turno. Guarda: 'sim, da sala' quando a
    pendente é o corredor NÃO executa o corredor — recusa genérica.

    Regras:
    - 'sim' puro (sem lugar mencionado) → coerente (caso normal).
    - lugar mencionado E contido no alvo/entidade pendente → coerente
      ('sim, a do corredor' quando a pendente é a do corredor).
    - lugar mencionado e FORA do alvo pendente → INCOERENTE (não executa).
    """
    lugares = set(_PLACE_WORDS.findall(text or ""))
    if not lugares:
        return True
    haystack = f"{alvo} {entity_id}".lower()
    for lugar in lugares:
        if lugar.lower() not in haystack:
            return False
    return True


def peek_pending_light_confirmation(
    user_id: str,
) -> Optional[tuple[str, bool, str]]:
    """Intenção de controle pendente mais recente do user (dentro do TTL).

    Retorna (entity_id, on, alvo) — alvo é o dispositivo que o user NOMEAR
    no comando original ('luz do corredor' → 'corredor'); '' quando o
    comando original não nomeou nada. O 'sim' do user não gera intenção de
    action — o orchestrator consulta aqui o que está pendente, confere a
    coerência com o texto do 'sim' (v1.9.1) e executa. NÃO consome: o
    consumo acontece dentro de ha_device_control APÓS a execução
    bem-sucedida. Entradas expiradas são descartadas na varredura.
    """
    now = time.time()
    best: Optional[tuple[str, bool, str]] = None
    best_stamp = -1.0
    for (uid, entity_id, on), (stamp, alvo) in list(
        _LIGHT_CONFIRMATIONS.items()
    ):
        if uid != user_id:
            continue
        if (now - stamp) > _LIGHT_CONFIRM_TTL:
            _LIGHT_CONFIRMATIONS.pop((uid, entity_id, on), None)
            continue
        if stamp > best_stamp:
            best_stamp = stamp
            best = (entity_id, bool(on), alvo)
    return best


# 26/10 (Vigia das Mensagens): o HA nem sempre reflete o comando na
# primeira leitura. Relê até N vezes antes de dizer o estado — e, se não
# confirmar, a resposta diz "não confirmou" em vez de mentir.
_ESTADO_TENTATIVAS = 3
_ESTADO_ESPERA_S = 0.2


def _estado_confirma(after: Optional[str], on: bool, domain: str) -> bool:
    """O estado lido CONFIRMA o pedido de liga/desliga?

    Desligar = `off` em qualquer domínio. Ligar = `on` (switch/light/
    remote); no `media_player` qualquer estado que não seja `off` já é
    aparelho ligado (uma TV ligada fica `playing`/`idle`, não `on`).
    `unknown`/`unavailable` nunca confirmam nada.
    """
    if not after or after in ("unknown", "unavailable"):
        return False
    if not on:
        return after == "off"
    if after == "on":
        return True
    return domain == "media_player" and after != "off"


def _estado_pos_comando(
    client: Any, entity_id: str, on: bool, domain: str,
) -> tuple[Optional[str], bool]:
    """Estado pós-comando + se ele confirma o pedido (best-effort).

    Auditoria 23/10 (4 turnos): a resposta saía como
    "✅ ligar executado (estado: off)" — o estado lido era o CONTRÁRIO do
    comando e o texto imprimia tudo como confirmação. Daqui pra frente o
    par (estado, confirmado) é o único insumo da frase.
    """
    after: Optional[str] = None
    for tentativa in range(max(1, _ESTADO_TENTATIVAS)):
        try:
            post = client.get_state(entity_id)
            after = post.state if post else None
        except Exception:
            after = None
        if _estado_confirma(after, on, domain):
            return after, True
        if tentativa < _ESTADO_TENTATIVAS - 1:
            time.sleep(_ESTADO_ESPERA_S)
    return after, False


def ha_device_control(
    entity_id: str = "", on: bool = True, user_id: str = "", termo: str = "",
    alvo: str = "", plural: bool = False,
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
        if plural:
            return {
                "ok": False,
                "error": "alvo_obrigatorio",
                "plural": True,
                "hint": (
                    "não aciono várias luzes de uma vez — diga qual luz ou "
                    "tomada (ex: 'liga a luz da cozinha')"
                ),
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
    # 22/10: a TV do dono (remote./media_player.) é atuadora como luz/tomada —
    # o resolvedor da intenção já só devolve domínios de _ATUADORES_HA.
    if domain not in ("switch", "light", "remote", "media_player"):
        return {
            "ok": False,
            "error": "nao_e_luz",
            "hint": (
                f"'{entity_id}' não é aparelho controlável aqui "
                f"(domínio '{domain}')"
            ),
        }
    states = _ha_states()
    name = _light_name_for(entity_id, states)
    # Confirmação de 2 passos (por user + luz + ação). O alvo falado é
    # guardado para a coerência do 'sim' (v1.9.1).
    stage = _light_confirm_check(
        user_id or "desconhecido", entity_id, on, alvo=alvo,
    )
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
    # Lê o estado pós-comando até bater com o pedido (releitura curta).
    # O resultado é o par honesto que a resposta vai dizer: sem
    # confirmação a frase é "não confirmou", nunca "✅ executado".
    after, confirmado = _estado_pos_comando(client, entity_id, on, domain)
    # Consome a confirmação (um uso).
    _LIGHT_CONFIRMATIONS.pop((user_id or "desconhecido", entity_id, bool(on)), None)
    return {
        "ok": True,
        "executed": True,
        "entity": entity_id,
        "name": name,
        "action": "ligar" if on else "desligar",
        "state_after": after,
        "estado_confirmado": confirmado,
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


# ---------------------------------------------------------------------------
# Google Workspace (Drive/Agenda/Gmail) — SOMENTE LEITURA
# (decisão do dono, 2026-10-02: leitura primeiro; escrita em 2º lote).
# O cliente OAuth é injetado pelo launcher (configure_google_client); sem
# credenciais/token as actions degradam com ok=False e o chat responde que
# o Google não está configurado — NUNCA inventa e-mail/evento/arquivo.
# ---------------------------------------------------------------------------

_GOOGLE_CLIENT: Optional[Any] = None


def configure_google_client(client: Any) -> None:
    """Injeta o GoogleClient do launcher (idempotente)."""
    global _GOOGLE_CLIENT
    _GOOGLE_CLIENT = client


def _google() -> Any:
    return _GOOGLE_CLIENT


def _google_unavailable() -> dict[str, Any]:
    return _unavailable(
        "google", "Google não configurado/autorizado (rode runtime/google_auth.py)"
    )


def _google_error(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "tool": "google", "error": str(exc)}


def google_drive_list(query: str = "", limit: int = 20) -> dict[str, Any]:
    """Lista/busca arquivos do Google Drive (somente leitura)."""
    client = _google()
    if client is None:
        return _google_unavailable()
    try:
        from integrations.google import DriveService

        data = DriveService(client).list_files(query=query, limit=limit)
        return {"ok": True, "tool": "google_drive", **data}
    except Exception as exc:  # noqa: BLE001 — degrada, nunca estoura
        return _google_error(exc)


def google_drive_read(file_id: str, max_bytes: int = 200_000) -> dict[str, Any]:
    """Lê o conteúdo textual de um arquivo do Drive (exporta nativos Google)."""
    client = _google()
    if client is None:
        return _google_unavailable()
    try:
        from integrations.google import DriveService

        data = DriveService(client).read_text(file_id, max_bytes=max_bytes)
        return {"ok": True, "tool": "google_drive", **data}
    except Exception as exc:  # noqa: BLE001
        return _google_error(exc)


def google_calendar_events(
    days: int = 7, limit: int = 10, calendar_id: str = "primary"
) -> dict[str, Any]:
    """Próximos eventos da Google Agenda (somente leitura)."""
    client = _google()
    if client is None:
        return _google_unavailable()
    try:
        from integrations.google import CalendarService

        data = CalendarService(client).list_events(
            calendar_id=calendar_id or "primary", days=days, limit=limit
        )
        return {"ok": True, "tool": "google_calendar", **data}
    except Exception as exc:  # noqa: BLE001
        return _google_error(exc)


def google_gmail_list(query: str = "", limit: int = 10) -> dict[str, Any]:
    """Lista/busca mensagens do Gmail (somente leitura)."""
    client = _google()
    if client is None:
        return _google_unavailable()
    try:
        from integrations.google import GmailService

        data = GmailService(client).list_messages(query=query, limit=limit)
        return {"ok": True, "tool": "google_gmail", **data}
    except Exception as exc:  # noqa: BLE001
        return _google_error(exc)


def google_gmail_read(message_id: str) -> dict[str, Any]:
    """Lê uma mensagem do Gmail (cabeçalhos + corpo textual)."""
    client = _google()
    if client is None:
        return _google_unavailable()
    try:
        from integrations.google import GmailService

        data = GmailService(client).get_message(message_id)
        return {"ok": True, "tool": "google_gmail", **data}
    except Exception as exc:  # noqa: BLE001
        return _google_error(exc)


def google_gmail_labels() -> dict[str, Any]:
    """Lista os rótulos do Gmail (somente leitura)."""
    client = _google()
    if client is None:
        return _google_unavailable()
    try:
        from integrations.google import GmailService

        data = GmailService(client).list_labels()
        return {"ok": True, "tool": "google_gmail", **data}
    except Exception as exc:  # noqa: BLE001
        return _google_error(exc)


# ---------------------------------------------------------------------------
# Google Workspace — ESCRITA (lote 2, 2026-10-03)
#
# Escopo cheio aprovado pelo dono (txt.txt: criar/editar/apagar arquivos,
# criar/apagar compromissos, enviar/apagar e-mail). Mesmas camadas do
# ha_device_control (v1.8.1):
# 1. Permissão: FORA da allowlist do papel user — só admin/dono executa
#    (a negação do Registry vira permissao_negada guiada, sem LLM).
# 2. Alvo específico obrigatório: nada de operação em lote; alvo falado é
#    resolvido (nome → id) ANTES da confirmação, com 0 ou N>1 recusados.
# 3. Confirmação de 2 passos: 1ª menção registra e pede 'sim'; o mesmo
#    user dentro de 120s executa; consumo só após sucesso.
# ---------------------------------------------------------------------------

_WRITE_CONFIRMATIONS: dict[
    tuple[str, str, str], tuple[float, str, dict[str, Any]]
] = {}
_WRITE_CONFIRM_TTL = 120.0


def _write_chave(action: str, params: dict[str, Any]) -> str:
    """Chave estável da intenção: mesmo pedido = mesma chave."""
    import hashlib

    bruto = repr(sorted((k, str(v)) for k, v in params.items()))
    return hashlib.sha1(bruto.encode("utf-8")).hexdigest()[:32]


def _write_confirm_check(
    user_id: str,
    action: str,
    chave: str,
    *,
    alvo: str,
    params: dict[str, Any],
    now: Optional[float] = None,
) -> str:
    """Confirmação de 2 passos da escrita Google (espelho de
    _light_confirm_check): "required" na 1ª menção, "confirmed" quando o
    mesmo user repete dentro do TTL."""
    stamp = time.time() if now is None else now
    key = (user_id, action, chave)
    pending = _WRITE_CONFIRMATIONS.get(key)
    if pending is not None and (stamp - pending[0]) <= _WRITE_CONFIRM_TTL:
        return "confirmed"
    _WRITE_CONFIRMATIONS[key] = (stamp, alvo, dict(params))
    return "required"


def peek_pending_google_write(
    user_id: str,
) -> Optional[tuple[str, dict[str, Any], str]]:
    """Intenção de escrita Google pendente mais recente do user (TTL).

    Retorna (action, params, alvo) — params é EXATAMENTO o que o 'sim'
    reexecuta (resolução do alvo já embutida); alvo é o texto que o user
    nomeou, para a conferência de coerência (v1.9.1).
    """
    now = time.time()
    best: Optional[tuple[str, dict[str, Any], str]] = None
    best_stamp = -1.0
    for (uid, action, chave), (stamp, alvo, params) in list(
        _WRITE_CONFIRMATIONS.items()
    ):
        if uid != user_id:
            continue
        if (now - stamp) > _WRITE_CONFIRM_TTL:
            _WRITE_CONFIRMATIONS.pop((uid, action, chave), None)
            continue
        if stamp > best_stamp:
            best_stamp = stamp
            best = (action, dict(params), alvo)
    return best


def drop_pending_google_write(user_id: str) -> None:
    """Descarta as intenções de escrita pendentes do user (incoerência)."""
    for key in [k for k in _WRITE_CONFIRMATIONS if k[0] == user_id]:
        _WRITE_CONFIRMATIONS.pop(key, None)


# Pendência de 'quando' do google_calendar_create: o hint 'não entendi
# quando' pede 'hoje'/'amanhã às 15h' e essa resposta NÃO gera intenção —
# sem este estado a frase caía no LLM, que alucinava 'Marquei o
# compromisso…' sem chamar a API (prova real de 08/10, chat ID 700:
# 'Testar Agenda' nunca existiu no Google Calendar).
_CALENDAR_WHEN: dict[str, tuple[float, str]] = {}
_CALENDAR_WHEN_TTL = 300.0


def peek_pending_calendar_when(
    user_id: str, text: str, *, now: Optional[float] = None
) -> Optional[dict[str, Any]]:
    """Completa o create que ficou aguardando 'quando' com a frase atual.

    Devolve params prontos (titulo + quando + alvo) SOMENTE se a frase for
    um 'quando' válido (parse_when) — texto que não é quando NÃO consome a
    pendência (o dono pode digitar outra coisa e voltar); TTL limpa
    sozinho. O orquestrador só consulta quando a frase não casou nenhuma
    intenção, então um pedido novo nunca é sequestrado.
    """
    uid = user_id or "desconhecido"
    pend = _CALENDAR_WHEN.get(uid)
    if pend is None:
        return None
    stamp, titulo = pend
    stamp_now = time.time() if now is None else now
    if (stamp_now - stamp) > _CALENDAR_WHEN_TTL:
        _CALENDAR_WHEN.pop(uid, None)
        return None
    from integrations.google.calendar import parse_when

    if parse_when(text) is None:
        return None
    _CALENDAR_WHEN.pop(uid, None)
    return {"titulo": titulo, "quando": text.strip(), "alvo": titulo}


def drop_pending_calendar_when(user_id: str) -> None:
    """Descarta a pendência de 'quando' do user (limpeza/testes)."""
    _CALENDAR_WHEN.pop(user_id or "desconhecido", None)


def _write_denied() -> dict[str, Any]:
    return {"ok": False, "error": "permissao_negada"}


def google_drive_create(
    name: str = "", content: str = "", user_id: str = "", alvo: str = ""
) -> dict[str, Any]:
    """Cria UM arquivo de texto no Drive (admin + confirmação)."""
    client = _google()
    if client is None:
        return _google_unavailable()
    name = (name or "").strip()
    if not name:
        return {
            "ok": False,
            "error": "alvo_obrigatorio",
            "hint": "diga o nome do arquivo (ex: 'crie o arquivo atas no drive')",
        }
    uid = user_id or "desconhecido"
    action = "google_drive_create"
    params: dict[str, Any] = {"name": name, "content": content or ""}
    chave = _write_chave(action, params)
    stage = _write_confirm_check(uid, action, chave, alvo=alvo or name, params=params)
    if stage == "required":
        resumo = f"criar o arquivo '{name}'"
        if params["content"]:
            resumo += f" com {len(str(params['content']))} caractere(s) de conteúdo"
        return {
            "ok": True,
            "needs_confirmation": True,
            "alvo": name,
            "hint": (
                f"Confirmar: {resumo} no Google Drive? Responda 'sim' para "
                "executar (a confirmação vale por 2 minutos)."
            ),
        }
    try:
        from integrations.google import DriveService

        data = DriveService(client).create_file(name, str(params["content"]))
    except Exception as exc:  # noqa: BLE001
        return _google_error(exc)
    _WRITE_CONFIRMATIONS.pop((uid, action, chave), None)
    return {
        "ok": True,
        "executed": True,
        "alvo": name,
        "file_id": data.get("id", ""),
        "link": data.get("web_view_link", ""),
    }


def google_drive_update(
    name: str = "",
    content: str = "",
    file_id: str = "",
    user_id: str = "",
    alvo: str = "",
) -> dict[str, Any]:
    """Substitui o conteúdo de UM arquivo de texto do Drive."""
    client = _google()
    if client is None:
        return _google_unavailable()
    content = content or ""
    if not content.strip():
        return {
            "ok": False,
            "error": "conteudo_obrigatorio",
            "hint": (
                "diga o novo conteúdo (ex: 'edite o arquivo notas com o "
                "texto: ...')"
            ),
        }
    uid = user_id or "desconhecido"
    action = "google_drive_update"
    alvo_txt = alvo or name
    if not file_id:
        name = (name or "").strip()
        if not name:
            return {
                "ok": False,
                "error": "alvo_obrigatorio",
                "hint": "diga qual arquivo editar (ex: 'edite o arquivo notas ...')",
            }
        try:
            from integrations.google import DriveService

            matches = DriveService(client).find_by_name(name)
        except Exception as exc:  # noqa: BLE001
            return _google_error(exc)
        if not matches:
            return {
                "ok": False,
                "error": "nao_encontrado",
                "hint": f"nenhum arquivo chamado '{name}' no Drive",
            }
        if len(matches) > 1:
            return {
                "ok": False,
                "error": "alvo_ambiguo",
                "hint": (
                    f"{len(matches)} arquivos se chamam '{name}' — renomeie "
                    "um deles ou me diga o id"
                ),
            }
        alvo_txt = alvo or name
        file_id = str(matches[0].get("id") or "")
        mime = str(matches[0].get("mime_type") or "")
        if mime.startswith("application/vnd.google-apps."):
            return {
                "ok": False,
                "error": "nativo_google",
                "hint": (
                    f"'{name}' é um arquivo nativo do Google (Docs/Planilha) — "
                    "não edito o conteúdo dele por aqui; posso criar um arquivo "
                    "de texto novo com esse conteúdo (peça: 'crie o arquivo ...')"
                ),
            }
    params = {"file_id": file_id, "content": content}
    chave = _write_chave(action, params)
    stage = _write_confirm_check(uid, action, chave, alvo=alvo_txt, params=params)
    if stage == "required":
        return {
            "ok": True,
            "needs_confirmation": True,
            "alvo": alvo_txt,
            "hint": (
                f"Confirmar: substituir o conteúdo de '{alvo_txt}' no Drive "
                f"({len(content)} caractere(s))? Responda 'sim' para executar "
                "(a confirmação vale por 2 minutos)."
            ),
        }
    try:
        from integrations.google import DriveService

        data = DriveService(client).update_content(file_id, content)
    except Exception as exc:  # noqa: BLE001
        return _google_error(exc)
    _WRITE_CONFIRMATIONS.pop((uid, action, chave), None)
    return {
        "ok": True,
        "executed": True,
        "alvo": alvo_txt,
        "file_id": file_id,
        "bytes": len(content.encode("utf-8")),
    }


def google_drive_delete(
    name: str = "", file_id: str = "", user_id: str = "", alvo: str = ""
) -> dict[str, Any]:
    """Apaga UM arquivo do Drive (alvo resolvido por nome exato)."""
    client = _google()
    if client is None:
        return _google_unavailable()
    uid = user_id or "desconhecido"
    action = "google_drive_delete"
    alvo_txt = alvo or name
    if not file_id:
        name = (name or "").strip()
        if not name:
            return {
                "ok": False,
                "error": "alvo_obrigatorio",
                "hint": "diga qual arquivo apagar (ex: 'apague o arquivo notas do drive')",
            }
        try:
            from integrations.google import DriveService

            matches = DriveService(client).find_by_name(name)
        except Exception as exc:  # noqa: BLE001
            return _google_error(exc)
        if not matches:
            return {
                "ok": False,
                "error": "nao_encontrado",
                "hint": f"nenhum arquivo chamado '{name}' no Drive — nada foi apagado",
            }
        if len(matches) > 1:
            return {
                "ok": False,
                "error": "alvo_ambiguo",
                "hint": (
                    f"{len(matches)} arquivos se chamam '{name}' — não apago "
                    "em lote; renomeie ou me diga o id"
                ),
            }
        alvo_txt = alvo or name
        file_id = str(matches[0].get("id") or "")
    params = {"file_id": file_id}
    chave = _write_chave(action, params)
    stage = _write_confirm_check(uid, action, chave, alvo=alvo_txt, params=params)
    if stage == "required":
        return {
            "ok": True,
            "needs_confirmation": True,
            "alvo": alvo_txt,
            "hint": (
                f"Confirmar: apagar '{alvo_txt}' do Google Drive (definitivo)? "
                "Responda 'sim' para executar (a confirmação vale por 2 minutos)."
            ),
        }
    try:
        from integrations.google import DriveService

        DriveService(client).delete_file(file_id)
    except Exception as exc:  # noqa: BLE001
        return _google_error(exc)
    _WRITE_CONFIRMATIONS.pop((uid, action, chave), None)
    return {"ok": True, "executed": True, "alvo": alvo_txt, "file_id": file_id}


def google_calendar_create(
    titulo: str = "",
    quando: str = "",
    start: str = "",
    end: str = "",
    user_id: str = "",
    alvo: str = "",
) -> dict[str, Any]:
    """Cria UM compromisso na Agenda (dia inteiro ou com hora)."""
    client = _google()
    if client is None:
        return _google_unavailable()
    titulo = (titulo or "").strip()
    if not titulo:
        return {
            "ok": False,
            "error": "alvo_obrigatorio",
            "hint": "diga o título do compromisso (ex: 'crie o compromisso reunião amanhã às 15h')",
        }
    from core.intents import _quando_legivel

    if not start:
        from integrations.google.calendar import parse_when

        parsed = parse_when(quando or titulo)
        if not parsed:
            # Guarda o título: a próxima frase do dono ('hoje', 'amanhã
            # às 15h') completa ESTA intenção no fastpath (sem LLM).
            _CALENDAR_WHEN[user_id or "desconhecido"] = (time.time(), titulo)
            return {
                "ok": False,
                "error": "quando_obrigatorio",
                "hint": (
                    "não entendi quando — diga 'hoje' ou 'amanhã' (com "
                    "'às 15h' se tiver hora)"
                ),
            }
        start, end = parsed["start"], parsed["end"]
    uid = user_id or "desconhecido"
    action = "google_calendar_create"
    alvo_txt = alvo or titulo
    params = {"titulo": titulo, "start": start, "end": end}
    chave = _write_chave(action, params)
    stage = _write_confirm_check(uid, action, chave, alvo=alvo_txt, params=params)
    if stage == "required":
        quando_txt = _quando_legivel(start)
        return {
            "ok": True,
            "needs_confirmation": True,
            "alvo": alvo_txt,
            "hint": (
                f"Confirmar: criar o compromisso '{titulo}' em {quando_txt} "
                "na sua Agenda? Responda 'sim' para executar (a confirmação "
                "vale por 2 minutos)."
            ),
        }
    try:
        from integrations.google import CalendarService

        data = CalendarService(client).create_event(
            summary=titulo, when={"start": start, "end": end}
        )
    except Exception as exc:  # noqa: BLE001
        return _google_error(exc)
    _WRITE_CONFIRMATIONS.pop((uid, action, chave), None)
    return {
        "ok": True,
        "executed": True,
        "alvo": titulo,
        "start": start,
        "event_id": data.get("id", ""),
        "link": data.get("link", ""),
    }


def google_calendar_delete(
    titulo: str = "", event_id: str = "", user_id: str = "", alvo: str = ""
) -> dict[str, Any]:
    """Apaga UM compromisso da Agenda (título exato nos próximos 60 dias)."""
    client = _google()
    if client is None:
        return _google_unavailable()
    uid = user_id or "desconhecido"
    action = "google_calendar_delete"
    alvo_txt = alvo or titulo
    if not event_id:
        titulo = (titulo or "").strip()
        if not titulo:
            return {
                "ok": False,
                "error": "alvo_obrigatorio",
                "hint": "diga qual compromisso apagar (ex: 'apague o compromisso reunião')",
            }
        try:
            from integrations.google import CalendarService

            matches = CalendarService(client).find_events_by_title(titulo)
        except Exception as exc:  # noqa: BLE001
            return _google_error(exc)
        if not matches:
            return {
                "ok": False,
                "error": "nao_encontrado",
                "hint": f"nenhum compromisso com o título '{titulo}' nos próximos 60 dias",
            }
        if len(matches) > 1:
            return {
                "ok": False,
                "error": "alvo_ambiguo",
                "hint": (
                    f"{len(matches)} compromissos com o título '{titulo}' — "
                    "especifique qual (ex: data)"
                ),
            }
        alvo_txt = alvo or titulo
        event_id = str(matches[0].get("id") or "")
    params = {"event_id": event_id}
    chave = _write_chave(action, params)
    stage = _write_confirm_check(uid, action, chave, alvo=alvo_txt, params=params)
    if stage == "required":
        return {
            "ok": True,
            "needs_confirmation": True,
            "alvo": alvo_txt,
            "hint": (
                f"Confirmar: apagar o compromisso '{alvo_txt}' da sua Agenda? "
                "Responda 'sim' para executar (a confirmação vale por 2 minutos)."
            ),
        }
    try:
        from integrations.google import CalendarService

        CalendarService(client).delete_event(event_id)
    except Exception as exc:  # noqa: BLE001
        return _google_error(exc)
    _WRITE_CONFIRMATIONS.pop((uid, action, chave), None)
    return {"ok": True, "executed": True, "alvo": alvo_txt, "event_id": event_id}


def google_gmail_send(
    para: str = "",
    assunto: str = "",
    corpo: str = "",
    user_id: str = "",
    alvo: str = "",
) -> dict[str, Any]:
    """Envia UM e-mail (admin + confirmação)."""
    import re as _re

    client = _google()
    if client is None:
        return _google_unavailable()
    para = (para or "").strip()
    corpo = corpo or ""
    if not para or not _re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", para):
        return {
            "ok": False,
            "error": "destinatario_invalido",
            "hint": (
                "preciso do endereço de e-mail (ex: 'envie um e-mail para "
                "fulano@exemplo.com assunto: oi corpo: tudo bem')"
            ),
        }
    if not corpo.strip():
        return {
            "ok": False,
            "error": "conteudo_obrigatorio",
            "hint": "diga o corpo do e-mail (ex: 'corpo: tudo bem')",
        }
    uid = user_id or "desconhecido"
    action = "google_gmail_send"
    alvo_txt = alvo or para
    params = {"para": para, "assunto": assunto or "", "corpo": corpo}
    chave = _write_chave(action, params)
    stage = _write_confirm_check(uid, action, chave, alvo=alvo_txt, params=params)
    if stage == "required":
        assunto_txt = assunto or "(sem assunto)"
        return {
            "ok": True,
            "needs_confirmation": True,
            "alvo": alvo_txt,
            "hint": (
                f"Confirmar: enviar e-mail para {para} — assunto "
                f"'{assunto_txt}' ({len(corpo)} caractere(s))? Responda 'sim' "
                "para executar (a confirmação vale por 2 minutos)."
            ),
        }
    try:
        from integrations.google import GmailService

        data = GmailService(client).send_message(
            to=para, subject=assunto or "(sem assunto)", body=corpo
        )
    except Exception as exc:  # noqa: BLE001
        return _google_error(exc)
    _WRITE_CONFIRMATIONS.pop((uid, action, chave), None)
    return {
        "ok": True,
        "executed": True,
        "alvo": para,
        "para": para,
        "assunto": assunto or "(sem assunto)",
        "message_id": data.get("id", ""),
    }


def google_gmail_delete(
    termo: str = "", message_id: str = "", user_id: str = "", alvo: str = ""
) -> dict[str, Any]:
    """Move UM e-mail para a lixeira (busca livre → alvo único)."""
    client = _google()
    if client is None:
        return _google_unavailable()
    uid = user_id or "desconhecido"
    action = "google_gmail_delete"
    alvo_txt = alvo or termo
    if not message_id:
        termo = (termo or "").strip()
        if not termo:
            return {
                "ok": False,
                "error": "alvo_obrigatorio",
                "hint": "diga qual e-mail apagar (ex: 'apague o e-mail da ana')",
            }
        try:
            from integrations.google import GmailService

            found = GmailService(client).list_messages(query=termo, limit=5)
        except Exception as exc:  # noqa: BLE001
            return _google_error(exc)
        msgs = found.get("messages") or []
        if not msgs:
            return {
                "ok": False,
                "error": "nao_encontrado",
                "hint": f"nenhum e-mail bate com '{termo}' — nada foi apagado",
            }
        if len(msgs) > 1:
            assuntos = ", ".join(
                f"'{m.get('subject') or '(sem assunto)'}'" for m in msgs[:3]
            )
            return {
                "ok": False,
                "error": "alvo_ambiguo",
                "hint": (
                    f"{len(msgs)} e-mails batem com '{termo}' ({assuntos}) — "
                    "especifique qual apagar"
                ),
            }
        alvo_txt = alvo or termo
        message_id = str(msgs[0].get("id") or "")
    params = {"message_id": message_id}
    chave = _write_chave(action, params)
    stage = _write_confirm_check(uid, action, chave, alvo=alvo_txt, params=params)
    if stage == "required":
        return {
            "ok": True,
            "needs_confirmation": True,
            "alvo": alvo_txt,
            "hint": (
                f"Confirmar: mover o e-mail '{alvo_txt}' para a lixeira do "
                "Gmail? Responda 'sim' para executar (a confirmação vale por "
                "2 minutos)."
            ),
        }
    try:
        from integrations.google import GmailService

        GmailService(client).trash_message(message_id)
    except Exception as exc:  # noqa: BLE001
        return _google_error(exc)
    _WRITE_CONFIRMATIONS.pop((uid, action, chave), None)
    return {"ok": True, "executed": True, "alvo": alvo_txt, "message_id": message_id}


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


def _inventario_vigia() -> dict[str, dict[str, Any]]:
    """Inventário do Vigia (MAC canônico -> entrada) — parking lot §5.

    Fonte única: `logs/network_watchdog_estado.json`, o MESMO arquivo que o
    Vigia (`tools/monitor/network_watchdog.py`) grava a cada ciclo, com nome,
    fabricante e estado de cada dispositivo conhecido da rede. `OD_LOG_DIR`
    respeitado — mesmo contrato do Vigia.

    Leitura tolerante e sem depender do processo do Vigia: arquivo ausente,
    ilegível ou corrompido = dicionário vazio e `network_hosts` responde só
    com o ARP, exatamente como sempre (o Vigia é opcional, nunca quebra a
    ação nem o boot).
    """
    log_dir = Path(
        os.environ.get("OD_LOG_DIR")
        or Path(__file__).resolve().parents[1] / "logs"
    )
    try:
        estado = json.loads(
            (log_dir / "network_watchdog_estado.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, ValueError):
        return {}
    dispositivos = estado.get("dispositivos") if isinstance(estado, dict) else None
    if not isinstance(dispositivos, dict):
        return {}
    # O ARP do kernel vem em minúsculas; as chaves do Vigia são o MAC
    # canônico (maiúsculo, com dois-pontos) — normalizar os dois lados.
    return {
        str(mac).strip().upper(): entrada
        for mac, entrada in dispositivos.items()
        if isinstance(entrada, dict)
    }


# 26/10 (Vigia das Mensagens): bridges virtuais (docker, veth,
# tailscale…) não são aparelhos de ninguém na rede da casa —
# "quantas pessoas estão conectadas" listava 9 contêineres do
# Docker atrás de br-b7119289ffc4.
_IFACES_VIRTUAIS = ("br-", "docker", "veth", "virbr", "tailscale",
                    "zt", "wg", "tun", "tap")


def network_hosts() -> dict[str, Any]:
    """Hosts da rede local via /proc/net/arp (vizinhança real IP+MAC).

    Leitura 100% stdlib e sem rede ativa — responde "quantos dispositivos /
    pessoas estão conectados na rede" com a tabela ARP do kernel (entradas
    válidas = endereço MAC real). Complementar OD (não existia no NV).

    Parking lot §5 (ideia do dono de 21/10): cada vizinho conhecido pelo
    Vigia ganha o `nome` do inventário (e o `fabricante` do cache OUI quando
    não há nome) — "quem está na rede?" responde "TV Samsung", não só um IP.
    Sem entrada no inventário o host fica intocado (formato original).
    """
    raw = _read_proc("net/arp")
    if not raw:
        return _unavailable("network", "/proc/net/arp indisponível")
    inventario = _inventario_vigia()
    hosts: list[dict[str, Any]] = []
    for line in raw.splitlines()[1:]:  # pula o cabeçalho
        parts = line.split()
        if len(parts) < 6:
            continue
        ip, _hw_type, flags, mac, _mask, iface = parts[:6]
        if mac == "00:00:00:00:00:00":
            continue  # entrada sem vizinho resolvido
        if iface.startswith(_IFACES_VIRTUAIS):
            continue  # bridge/container: não é dispositivo da casa
        host: dict[str, Any] = {
            "ip": ip,
            "mac": mac,
            "interface": iface,
            "state": "reachable" if flags == "0x2" else "stale",
        }
        entrada = inventario.get(mac.strip().upper())
        if entrada:
            nome = str(entrada.get("nome") or "").strip()
            if nome:
                host["nome"] = nome
            fabricante = str(entrada.get("fabricante") or "").strip()
            if fabricante and fabricante.lower() != "desconhecido":
                host["fabricante"] = fabricante
        hosts.append(host)
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
# Docker Compose — Ferramentas Nômade (Project NOMAD absorvido)
# ---------------------------------------------------------------------------

NOMAD_COMPOSE_FILE = "/home/alex/OmegaDrakon/docker/tools-compose.yaml"
NOMAD_TOOLS_DIR = "/home/alex/omegadrakon-tools"

_NOMAD_SERVICES = (
    "kiwix",
    "cyberchef",
    "it-tools",
    "flatnotes",
    "stirling-pdf",
    "filebrowser",
    "calibre-web",
    "vaultwarden",
)

_NOMAD_PORTS = {
    "kiwix": 8090,
    "cyberchef": 8100,
    "it-tools": 8430,
    "flatnotes": 8200,
    "stirling-pdf": 8400,
    "filebrowser": 8410,
    "calibre-web": 8420,
    "vaultwarden": 8480,
}


def _compose(args: list[str], timeout: float = 60.0) -> dict[str, Any]:
    """Executa docker compose com o arquivo das ferramentas Nômade."""
    base = ["docker", "compose", "-f", NOMAD_COMPOSE_FILE]
    rc, out, err = _run(base + args, timeout=timeout)
    if rc != 0:
        return _unavailable("docker_compose", (err or out).strip()[:500])
    return {"ok": True, "output": out}


def nomad_tools_up() -> dict[str, Any]:
    """Sobe todos os containers das ferramentas Nômade (docker compose up -d)."""
    return _compose(["up", "-d"], timeout=120.0)


def nomad_tools_down() -> dict[str, Any]:
    """Derruba todos os containers das ferramentas Nômade (docker compose down)."""
    return _compose(["down"], timeout=60.0)


def nomad_tools_status() -> dict[str, Any]:
    """Status dos containers Nômade (docker compose ps)."""
    return _compose(["ps", "--format", "json"])


def nomad_tools_logs(service: str = "", lines: int = 100) -> dict[str, Any]:
    """Logs de um serviço Nômade (docker compose logs)."""
    if lines <= 0:
        raise ValueError("lines deve ser > 0")
    args = ["logs", "--tail", str(lines)]
    if service:
        if service not in _NOMAD_SERVICES:
            return {"ok": False, "error": "servico_invalido", "message": f"Serviço '{service}' não é uma ferramenta Nômade conhecida. Opções: {', '.join(_NOMAD_SERVICES)}"}
        args.append(service)
    return _compose(args, timeout=30.0)


def nomad_tools_restart(service: str) -> dict[str, Any]:
    """Reinicia um serviço Nômade específico."""
    if service not in _NOMAD_SERVICES:
        return {"ok": False, "error": "servico_invalido", "message": f"Serviço '{service}' não é uma ferramenta Nômade conhecida. Opções: {', '.join(_NOMAD_SERVICES)}"}
    return _compose(["restart", service], timeout=60.0)


def nomad_tools_tailscale_serve(service: str = "", action: str = "up") -> dict[str, Any]:
    """Gerencia tailscale serve para ferramentas Nômade.

    action: "up" (publica), "down" (remove), "status" (lista)
    service: nome do serviço (se vazio, aplica a todos quando action=up/down)
    """
    if service and service not in _NOMAD_SERVICES:
        return {"ok": False, "error": "servico_invalido", "message": f"Serviço '{service}' não é uma ferramenta Nômade conhecida."}

    if action == "status":
        rc, out, err = _run(["tailscale", "serve", "status"])
        if rc != 0:
            return _unavailable("tailscale", (err or out).strip()[:400])
        return {"ok": True, "output": out}

    targets = [service] if service else list(_NOMAD_SERVICES)
    results = []
    for svc in targets:
        port = _NOMAD_PORTS[svc]
        if action == "up":
            # tailscale serve --bg http://127.0.0.1:<port>
            rc, out, err = _run(["tailscale", "serve", "--bg", f"http://127.0.0.1:{port}"])
        elif action == "down":
            # tailscale serve --bg off http://127.0.0.1:<port>
            rc, out, err = _run(["tailscale", "serve", "--bg", "off", f"http://127.0.0.1:{port}"])
        else:
            return {"ok": False, "error": "acao_invalida", "message": "action deve ser 'up', 'down' ou 'status'"}
        results.append({"service": svc, "port": port, "ok": rc == 0, "output": out if rc == 0 else err})

    return {"ok": True, "action": action, "results": results}


def nomad_wikipedia_zim_download(url: str = "", dest: str = "") -> dict[str, Any]:
    """Baixa o arquivo ZIM da Wikipédia para o Kiwix.

    url: URL do arquivo .zim (se vazio, tenta URL padrão do Kiwix)
    dest: caminho de destino (se vazio, usa /home/alex/omegadrakon-tools/zim/wikipedia.zim)
    """
    import os

    if not dest:
        dest = os.path.join(NOMAD_TOOLS_DIR, "zim", "wikipedia.zim")
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    if not url:
        # URLs conhecidas do Kiwix (podem mudar — owner deve verificar no mirror)
        url = "https://download.kiwix.org/zim/wikipedia/wikipedia_en_all_mini.zim"

    rc, out, err = _run(["wget", "-c", "-O", dest, url], timeout=3600.0)
    if rc != 0:
        return {"ok": False, "error": "download_falhou", "message": (err or out).strip()[:500]}
    size = os.path.getsize(dest) if os.path.exists(dest) else 0
    return {"ok": True, "dest": dest, "size_bytes": size, "size_gb": round(size / (1024**3), 2)}


def _vw_hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    """HKDF-Expand (RFC 5869 §2.2) com HMAC-SHA256 — mesmo que o jslib `stretchKey`."""
    out = b""
    block = b""
    counter = 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        out += block
        counter += 1
    return out[:length]


def _vw_encstring(plain: bytes, enc_key: bytes, mac_key: bytes) -> str:
    """AES-256-CBC + HMAC-SHA256 no formato EncString tipo `2.iv|data|mac`.

    Preenchimento PKCS7; MAC cobre iv||ct (AesCbc256_HmacSha256_B64 do Bitwarden).
    """
    from cryptography.hazmat.primitives import padding as sym_padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    iv = os.urandom(16)
    padder = sym_padding.PKCS7(128).padder()
    padded = padder.update(plain) + padder.finalize()
    encryptor = Cipher(algorithms.AES(enc_key), modes.CBC(iv)).encryptor()
    ct = encryptor.update(padded) + encryptor.finalize()
    mac = hmac.new(mac_key, iv + ct, hashlib.sha256).digest()
    return "2." + "|".join(
        base64.b64encode(part).decode("ascii") for part in (iv, ct, mac)
    )


def _vw_decstring(encstr: str, enc_key: bytes, mac_key: bytes) -> bytes:
    """Decifra EncString tipo 2 (autentica MAC e remove PKCS7) — usado nos testes."""
    from cryptography.hazmat.primitives import padding as sym_padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    version, body = encstr.split(".", 1)
    if version != "2" or body.count("|") != 2:
        raise ValueError("EncString tipo 2 malformado")
    iv_b64, ct_b64, mac_b64 = body.split("|")
    iv, ct, mac = (base64.b64decode(p) for p in (iv_b64, ct_b64, mac_b64))
    if not hmac.compare_digest(hmac.new(mac_key, iv + ct, hashlib.sha256).digest(), mac):
        raise ValueError("MAC inválido")
    decryptor = Cipher(algorithms.AES(enc_key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ct) + decryptor.finalize()
    unpadder = sym_padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


_VW_KDF_ITER = 600_000  # PBKDF2-SHA256 (KdfType 0) — padrão Bitwarden


def _vw_register_payload(admin_email: str, admin_password: str, name: str = "Admin") -> dict[str, Any]:
    """Gera o payload `RegisterData` oficial para POST /identity/accounts/register.

    Crypto idêntica aos clientes Bitwarden oficiais (jslib/SDK):
      material    = PBKDF2-SHA256(senha, email, 600000, 32B)
      authHash    = PBKDF2-SHA256(material, senha, 1, 32B)  -> masterPasswordHash
      enc/mac     = HKDF-Expand(material, "enc"/"mac", 32B)  -> embrulho da user key
      userKey     = 64B aleatórios (AES-256-CBC + HMAC-SHA256)
      RSA-2048    = PKCS8 embrulhado com a user key; pública SPKI em base64

    Formato e chaves verificados em 2026-10-15 contra o SDK oficial
    (@bitwarden/sdk-internal) e E2E com CLI bw 2026.8.0 + servidor 1.36.0.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    email = admin_email.strip().lower()
    pwd = admin_password.encode("utf-8")
    material = hashlib.pbkdf2_hmac(
        "sha256", pwd, email.encode("utf-8"), _VW_KDF_ITER, dklen=32
    )
    auth_hash = base64.b64encode(
        hashlib.pbkdf2_hmac("sha256", material, pwd, 1, dklen=32)
    ).decode("ascii")
    enc_key = _vw_hkdf_expand(material, b"enc", 32)
    mac_key = _vw_hkdf_expand(material, b"mac", 32)
    user_key = os.urandom(64)
    wrapped_key = _vw_encstring(user_key, enc_key, mac_key)

    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pkcs8 = priv.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    spki = priv.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    wrapped_priv = _vw_encstring(pkcs8, user_key[:32], user_key[32:])

    return {
        "email": email,
        "name": name,
        "kdf": 0,  # UserKdfType::Pbkdf2
        "kdfIterations": _VW_KDF_ITER,
        "key": wrapped_key,
        "keys": {
            "encryptedPrivateKey": wrapped_priv,
            "publicKey": base64.b64encode(spki).decode("ascii"),
        },
        "masterPasswordHash": auth_hash,
    }


def nomad_vaultwarden_setup(admin_email: str = "", admin_password: str = "", disable_signups: bool = True) -> dict[str, Any]:
    """Configura o Vaultwarden: cria conta admin e/ou fecha signups de verdade.

    - Criação de conta: POST /identity/accounts/register com payload RegisterData
      completo (rota e crypto corrigidas em 2026-10-15; a rota antiga
      /api/accounts/register devolvia 404).
    - Fechamento de signups: edita SIGNUPS_ALLOWED=false no compose, recria o
      container e confere a env aplicada — sem sucesso falso.
    Requer container de pé (execute nomad_tools_up primeiro).
    """
    import json
    import urllib.error
    import urllib.request

    # 1) container de pé
    status = nomad_tools_status()
    if not status.get("ok"):
        return status
    running = any(
        "vaultwarden" in line and "running" in line.lower()
        for line in status.get("output", "").splitlines()
    )
    if not running:
        return {"ok": False, "error": "container_nao_rodando", "message": "Container vaultwarden não está rodando. Execute nomad_tools_up primeiro."}

    result: dict[str, Any] = {"ok": True}

    # 2) cria conta (se credenciais fornecidas)
    if admin_email and admin_password:
        try:
            payload = _vw_register_payload(admin_email, admin_password)
        except ImportError as exc:
            return {"ok": False, "error": "crypto_indisponivel", "message": f"Dependência 'cryptography' indisponível: {exc}"}
        except Exception as exc:
            return {"ok": False, "error": "gerar_payload_falhou", "message": str(exc)}
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:8480/identity/accounts/register",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                resp_data = json.loads(resp.read().decode("utf-8") or "{}")
            result["conta"] = {
                "email": payload["email"],
                "criada": True,
                "object": resp_data.get("object", "register"),
            }
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            return {
                "ok": False,
                "error": "registro_recusado",
                "http_status": exc.code,
                "message": f"Registro recusado pelo Vaultwarden (HTTP {exc.code}): signups fechados ou conta já existe. {body}",
            }
        except Exception as exc:
            return {"ok": False, "error": "criar_conta_falhou", "message": str(exc)}

    # 3) fecha signups de verdade (compose + recriação + confere env)
    if disable_signups:

        def _falha_signups(error: str, message: str) -> dict[str, Any]:
            out: dict[str, Any] = {"ok": False, "error": error, "message": message, "etapa": "fechar_signups"}
            if result.get("conta"):
                out["conta"] = result["conta"]
            return out

        try:
            texto = Path(NOMAD_COMPOSE_FILE).read_text(encoding="utf-8")
        except OSError as exc:
            return _falha_signups("ler_compose_falhou", str(exc))
        alterado = "- SIGNUPS_ALLOWED=true" in texto
        if alterado:
            try:
                Path(NOMAD_COMPOSE_FILE).write_text(
                    texto.replace("- SIGNUPS_ALLOWED=true", "- SIGNUPS_ALLOWED=false"),
                    encoding="utf-8",
                )
            except OSError as exc:
                return _falha_signups("editar_compose_falhou", str(exc))
        up = _compose(["up", "-d", "vaultwarden"], timeout=90.0)
        if not up.get("ok"):
            return _falha_signups("recriar_container_falhou", str(up.get("error") or up.get("message") or up))
        rc, out, _err = _run(
            ["docker", "inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", "od-vaultwarden"],
            timeout=15.0,
        )
        if not (rc == 0 and "SIGNUPS_ALLOWED=false" in out):
            return _falha_signups("signups_nao_fecharam", "Container não aplicou SIGNUPS_ALLOWED=false (env ausente).")
        result["signups"] = {
            "compose_atualizado": alterado,
            "signups_allowed": False,
            "container_env": True,
        }

    # mensagem final (sem sucesso falso: só afirma o que foi verificado)
    partes: list[str] = []
    if result.get("conta"):
        partes.append(f"Conta {result['conta']['email']} criada em /identity/accounts/register.")
    if result.get("signups"):
        partes.append("Signups fechados (SIGNUPS_ALLOWED=false, container recriado e env verificada).")
    if not partes:
        partes.append("Vaultwarden pronto. Acesse via tailscale serve https://127.0.0.1:8480")
    result["message"] = " ".join(partes)
    return result


# ---------------------------------------------------------------------------
# Vaultwarden — cofre do SISTEMA (1ª interligação das ferramentas, 17/10)
# ---------------------------------------------------------------------------

def _vault_op(op: Any) -> dict[str, Any]:
    """Roda uma operação no cofre com erro honesto e tipado.

    Cliente LAZY (integrations/vault.py): cofre fora do ar ou não
    configurado degrada ESTA ação — nunca o boot do od-core. A conta é a
    de SERVIÇO (OD_VAULT_EMAIL); a do dono não é usada aqui.
    """
    from integrations.vault import VaultError, client_padrao

    cliente = client_padrao()
    if cliente is None:
        return {
            "ok": False,
            "error": "vault_nao_configurado",
            "message": "Cofre não configurado: defina OD_VAULT_SERVER, "
            "OD_VAULT_EMAIL, OD_VAULT_MASTER (e OD_BW_BIN) no .env.",
        }
    try:
        return {"ok": True, **op(cliente)}
    except VaultError as exc:
        return {"ok": False, "error": exc.codigo, "message": exc.mensagem}


def vault_status() -> dict[str, Any]:
    """Estado do cofre: sessão do bw (unauthenticated/locked/unlocked) + rede."""
    return _vault_op(lambda c: c.status())


def vault_list() -> dict[str, Any]:
    """Títulos dos itens do cofre — NUNCA valores (segredo é só em vault_get)."""
    def _op(c: Any) -> dict[str, Any]:
        itens = c.listar()
        return {"total": len(itens), "itens": itens}

    return _vault_op(_op)


def vault_get(name: str) -> dict[str, Any]:
    """Lê um segredo do cofre pelo nome (case-insensitive)."""
    return _vault_op(lambda c: {"item": c.obter(name)})


def vault_set(
    name: str,
    password: str,
    username: str = "",
    note: str = "",
) -> dict[str, Any]:
    """Cria (ou atualiza, se o nome já existe) um item no cofre."""
    return _vault_op(
        lambda c: c.guardar(name, password, username=username, nota=note)
    )


# ---------------------------------------------------------------------------
# Stirling PDF — pipeline de documentos (2ª interligação, 17/10)
# ---------------------------------------------------------------------------

def _stirling_op(op: Any) -> dict[str, Any]:
    """Roda uma operação no Stirling PDF com erro honesto e tipado.

    Cliente LAZY (integrations/stirling.py): a ferramenta fora do ar
    degrada ESTA ação — nunca o boot do od-core. API local sem login
    (127.0.0.1:8400), operações síncronas; a saída só é gravada depois
    da validação de mágica do arquivo.
    """
    from integrations.stirling import StirlingError, client_padrao

    try:
        cliente = client_padrao()
        return {"ok": True, **op(cliente)}
    except StirlingError as exc:
        return {"ok": False, "error": exc.codigo, "message": exc.mensagem}


def stirling_status() -> dict[str, Any]:
    """Estado do Stirling PDF: versão + status da API local."""
    return _stirling_op(lambda c: c.status())


def stirling_merge(
    arquivos: str,
    saida: str,
    substituir: bool = False,
) -> dict[str, Any]:
    """Junta 2+ PDFs (caminhos separados por vírgula) em um arquivo só."""
    lista = [p.strip() for p in str(arquivos or "").split(",") if p.strip()]
    return _stirling_op(lambda c: c.merge(lista, saida, substituir=substituir))


def stirling_split(
    arquivo: str,
    saida: str,
    cortes: str = "all",
    substituir: bool = False,
) -> dict[str, Any]:
    """Corta um PDF nos pontos de corte (ex.: "2", "2,5", "5-9", "all")."""
    return _stirling_op(
        lambda c: c.split(arquivo, cortes, saida, substituir=substituir)
    )


def stirling_compress(
    arquivo: str,
    saida: str,
    nivel: int = 4,
    alvo: str = "25KB",
    cinza: bool = False,
    substituir: bool = False,
) -> dict[str, Any]:
    """Comprime um PDF (nivel 1–9, alvo tipo "25KB"; cinza converte p/ P&B)."""
    return _stirling_op(
        lambda c: c.compress(
            arquivo, saida, nivel=nivel, alvo=alvo, cinza=cinza,
            substituir=substituir,
        )
    )


def _kiwix_op(op: Any) -> dict[str, Any]:
    """Roda uma operação no Kiwix Serve com erro honesto e tipado.

    Cliente LAZY (integrations/kiwix.py): a ferramenta fora do ar
    degrada ESTA ação — nunca o boot do od-core. Acervo offline em
    127.0.0.1:8090 (Wikipédia en_all_mini, 12,5 GB), somente LEITURA
    (ZIM montado :ro) — busca vazia é resposta honesta, não erro.
    """
    from integrations.kiwix import KiwixError, client_padrao

    try:
        cliente = client_padrao()
        return {"ok": True, **op(cliente)}
    except KiwixError as exc:
        return {"ok": False, "error": exc.codigo, "message": exc.mensagem}


def kiwix_status() -> dict[str, Any]:
    """Acervos carregados no Kiwix (nome, idioma, nº de artigos)."""
    return _kiwix_op(lambda c: c.status())


def kiwix_busca(pattern: str, quantidade: int = 5) -> dict[str, Any]:
    """Busca na Wikipédia OFFLINE (título, caminho, trecho, palavras)."""
    return _kiwix_op(lambda c: c.buscar(pattern, quantidade))


def kiwix_leitura(caminho: str, max_chars: int = 8000) -> dict[str, Any]:
    """Lê um artigo offline pelo caminho (devolve texto limpo + truncado)."""
    return _kiwix_op(lambda c: c.ler(caminho, max_chars=max_chars))


def _homebox_op(op: Any) -> dict[str, Any]:
    """Roda uma operação no Homebox com erro honesto e tipado.

    Cliente LAZY (integrations/homebox.py): a ferramenta fora do ar
    degrada ESTA ação — nunca o boot do od-core. Inventário do dono em
    127.0.0.1:8470 (API key estática via Bearer); uso definido pelo dono
    em 17/10: cadastrar ferramentas/peças e responder o que ele tem e o
    que falta para uma montagem. NENHUMA ação apaga — só lê e cadastra.
    """
    from integrations.homebox import HomeboxError, client_padrao

    try:
        cliente = client_padrao()
        return {"ok": True, **op(cliente)}
    except HomeboxError as exc:
        return {"ok": False, "error": exc.codigo, "message": exc.mensagem}


def homebox_status() -> dict[str, Any]:
    """Inventário: versão + totais (itens, locais, tags, preço)."""
    return _homebox_op(lambda c: c.status())


def homebox_busca(query: str, quantidade: int = 10) -> dict[str, Any]:
    """Busca peças no inventário (texto livre: nome, tipo, descrição)."""
    return _homebox_op(lambda c: c.buscar(query, quantidade))


def homebox_listar(quantidade: int = 25, tags: str = "") -> dict[str, Any]:
    """Lista o inventário (opcional: filtro por tags, "a, b")."""
    return _homebox_op(lambda c: c.listar(quantidade, tags))


def homebox_detalhar(id: str) -> dict[str, Any]:
    """Detalha UMA peça (quantidade, notas, compra, garantia, série)."""
    return _homebox_op(lambda c: c.detalhar(id))


def homebox_criar(
    nome: str,
    quantidade: int = 1,
    tipo: str = "",
    descricao: str = "",
    notas: str = "",
    tags: str = "",
    preco: Optional[float] = None,
    criar_tipo: bool = True,
    criar_tag: bool = True,
) -> dict[str, Any]:
    """Cadastra UMA peça (tipo/tags inexistentes são criados e DECLARADOS)."""
    return _homebox_op(
        lambda c: c.criar(
            nome, quantidade=quantidade, tipo=tipo, descricao=descricao,
            notas=notas, tags=tags, preco=preco,
            criar_tipo=criar_tipo, criar_tag=criar_tag,
        )
    )


def homebox_atualizar(
    id: str,
    quantidade: Optional[int] = None,
    notas: Optional[str] = None,
    descricao: Optional[str] = None,
    preco: Optional[float] = None,
) -> dict[str, Any]:
    """Atualiza UMA peça (ex.: gastou resistores → nova quantidade)."""
    return _homebox_op(
        lambda c: c.atualizar(
            id, quantidade=quantidade, notas=notas, descricao=descricao, preco=preco
        )
    )


def _flatnotes_op(op: Any) -> dict[str, Any]:
    """Roda uma operação no FlatNotes com erro honesto e tipado.

    Cliente LAZY (integrations/flatnotes.py): a ferramenta fora do ar
    degrada ESTA ação — nunca o boot do od-core. Caderno do dono em
    127.0.0.1:8200 (auth=none, só Tailscale); notas = arquivos .md
    numa pasta plana já coberta pelos snapshots das 2 HDs. NENHUMA
    ação apaga — 409 (título repetido) vira flatnotes_ja_existe
    honesto, sobrescrever é flag explícita.
    """
    from integrations.flatnotes import FlatNotesError, client_padrao

    try:
        cliente = client_padrao()
        return {"ok": True, **op(cliente)}
    except FlatNotesError as exc:
        return {"ok": False, "error": exc.codigo, "message": exc.mensagem}


def flatnotes_status() -> dict[str, Any]:
    """Vida do caderno: auth, nº de notas e a última editada."""
    return _flatnotes_op(lambda c: c.status())


def flatnotes_anota(
    titulo: str,
    conteudo: str = "",
    sobrescrever: bool = False,
) -> dict[str, Any]:
    """Cria UMA nota markdown (título repetido: recusa, salvo sobrescrever=true)."""
    return _flatnotes_op(
        lambda c: c.anota(titulo, conteudo=conteudo, sobrescrever=sobrescrever)
    )


def flatnotes_busca(termo: str, limite: int = 10) -> dict[str, Any]:
    """Busca nas notas do dono (texto livre; trecho limpo do que casou)."""
    return _flatnotes_op(lambda c: c.buscar(termo, limite=limite))


def _filebrowser_op(op: Any) -> dict[str, Any]:
    """Roda uma operação no File Browser com erro honesto e tipado.

    Cliente LAZY (integrations/filebrowser.py): a ferramenta fora do
    ar degrada ESTA ação — nunca o boot do od-core. Caixa de arquivos
    do dono em 127.0.0.1:8410 (login admin + JWT de 2h via
    OD_FILEBROWSER_PASSWORD, só Tailscale); serve SÓ a pasta
    omegadrakon-tools/filebrowser/files (UID 1000 = dono, coberta
    pelos snapshots das 2 HDs). NENHUMA ação apaga — o DELETE da API
    fica de fora do catálogo (régua do dono); 409 (arquivo repetido)
    vira filebrowser_ja_existe honesto e substituir é flag explícita
    que vem declarada na resposta.
    """
    from integrations.filebrowser import FileBrowserError, client_padrao

    try:
        cliente = client_padrao()
        return {"ok": True, **op(cliente)}
    except FileBrowserError as exc:
        return {"ok": False, "error": exc.codigo, "message": exc.mensagem}


def filebrowser_status() -> dict[str, Any]:
    """Vida da caixa de arquivos: saúde, versão, nº de itens e disco."""
    return _filebrowser_op(lambda c: c.status())


def filebrowser_lista(caminho: str = "") -> dict[str, Any]:
    """Lista o que tem na caixa (raiz por padrão; pasta por extensão)."""
    return _filebrowser_op(lambda c: c.lista(caminho))


def calibre_resync() -> dict[str, Any]:
    """Espelha a biblioteca do dono (Google Drive) e importa na Calibre.

    Dois passos honestos, um depois do outro:
    1) `core.biblioteca_drive.sincronizar` — Drive "Biblioteca" do dono →
       inbox local (incremental: arquivo igual não rebaixa; erro contido
       por arquivo, o resto segue).
    2) `integrations.calibre.importar_da_inbox` — importação dirigida por
       LEDGER (`.calibre_ledger.json`: caminho→tamanho): só o que o
       ledger não viu vai no `calibredb add -d --automerge new_record`,
       então resync NUNCA duplica registro e NENHUM título colidido fica
       escondido (a saída viva de 19/10 provou que o dedup do calibre
       sozinho escondia 156 arquivos — o ledger é nosso, a régua é do
       dono: nada some, nada sobrescreve, nada apaga).
    Sem Google autorizado, sem calibredb ou sem ledger, degrada com erro
    tipado — nunca derruba o chat.
    """
    from core.biblioteca_drive import sincronizar
    from integrations.calibre import (
        CalibreError,
        caminhos_espelho,
        importar_da_inbox,
    )
    from integrations.google import DriveService

    cliente = _google()
    if cliente is None:
        return _google_unavailable()
    caminhos = caminhos_espelho()
    try:
        espelho = sincronizar(
            caminhos["inbox"],
            drive=DriveService(cliente),
            pasta_id=caminhos["pasta_id"] or None,
        )
    except Exception as exc:  # noqa: BLE001 — degrada com erro honesto
        return {"ok": False, "tool": "calibre", "error": f"espelho_falhou: {exc}"}
    if not espelho.get("ok"):
        return {"ok": False, "tool": "calibre", "etapa": "espelho", **espelho}
    try:
        imp = importar_da_inbox()
    except CalibreError as exc:
        return {"ok": False, "tool": "calibre", "etapa": "importacao",
                "error": exc.codigo, "message": exc.mensagem, "espelho": espelho}
    return {"ok": True, "tool": "calibre", "espelho": espelho, "importacao": imp}


def calibre_status() -> dict[str, Any]:
    """Vida da Biblioteca: sonda OPDS ao vivo + inventário exato + pendências.

    Cliente LAZY (integrations/calibre.py): ferramenta fora do ar
    degrada ESTA ação — nunca o boot do od-core. A sonda bate no
    `/opds/` real da tailnet com Basic Auth (a senha vai no header e
    NUNCA aparece no retorno) e devolve o nº de seções do feed; junto
    vai o inventário local (livros/formatos do metadata.db em leitura,
    arquivos no espelho e PENDENTES de importar pelo ledger). Erros
    tipados `opds_*`/`calibre_*` voltam {ok: False, error, message}.
    """
    from integrations.calibre import CalibreError, opds_status

    try:
        return opds_status()
    except CalibreError as exc:
        return {"ok": False, "tool": "calibre", "error": exc.codigo,
                "message": exc.mensagem}


def calibre_busca(termo: str, limite: int = 10) -> dict[str, Any]:
    """Busca livros no Calibre Web pelo OPDS real (título/autor).

    `/opds/search/<termo>` com url-encode e Basic Auth — o MESMO feed
    que um leitor de e-book consome (nada de consulta direta no banco).
    Cada hit volta com id, título, autor, formatos e links de download
    prontos (URL absoluta da tailnet); `encontrados` é o total do feed
    e `mais_disponiveis` avisa se o feed veio paginado. Sem termo ou
    com o serviço fora, degrada com erro tipado — nunca derruba o chat.
    """
    from integrations.calibre import CalibreError, opds_busca

    try:
        return opds_busca(termo, limite=limite)
    except CalibreError as exc:
        return {"ok": False, "tool": "calibre", "error": exc.codigo,
                "message": exc.mensagem}


def filebrowser_envia(
    origem: str,
    destino: str,
    substituir: bool = False,
) -> dict[str, Any]:
    """Deixa um arquivo do sistema na caixa (o dono baixa no celular)."""
    return _filebrowser_op(
        lambda c: c.envia(origem, destino, substituir=substituir)
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
# Catálogo (78 actions)
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
    _spec("weather_city", "iot", "Clima real de uma cidade informada (Open-Meteo, sem chave)", weather_city,
          {"required": ["city"], "properties": {"city": S}}),
    _spec("exchange_rate", "system", "Cotação real de moeda contra o real (AwesomeAPI, sem chave)", exchange_rate,
          {"required": ["moeda"], "properties": {"moeda": S}}),
    _spec("ha_lights", "iot", "Estado das luzes e interruptores (Home Assistant)", ha_lights),
    _spec("ha_summary", "iot", "Raio-X do lar: clima, luzes, pessoas, bateria, rede", ha_summary),
    _spec("ha_device_control", "iot", "Liga/desliga UMA luz ou tomada específica (dono, com confirmação)", ha_device_control,
          {"required": ["entity_id"], "properties": {
              "entity_id": S,
              "on": {**B, "default": True},
              "user_id": {**S, "default": ""},
              "termo": {**S, "default": ""},
              "alvo": {**S, "default": ""},
              "plural": {**B, "default": False},
          }}),
    # --- Google Workspace (leitura) ---
    _spec("google_drive_list", "google", "Lista/busca arquivos do Google Drive", google_drive_list,
          {"query": {**S, "default": ""}, "limit": {**I, "default": 20}}),
    _spec("google_drive_read", "google", "Lê o conteúdo textual de um arquivo do Drive", google_drive_read,
          {"required": ["file_id"], "properties": {"file_id": S, "max_bytes": {**I, "default": 200000}}}),
    _spec("google_calendar_events", "google", "Próximos eventos da Google Agenda", google_calendar_events,
          {"days": {**I, "default": 7}, "limit": {**I, "default": 10}, "calendar_id": {**S, "default": "primary"}}),
    _spec("google_gmail_list", "google", "Lista/busca mensagens do Gmail", google_gmail_list,
          {"query": {**S, "default": ""}, "limit": {**I, "default": 10}}),
    _spec("google_gmail_read", "google", "Lê uma mensagem do Gmail", google_gmail_read,
          {"required": ["message_id"], "properties": {"message_id": S}}),
    _spec("google_gmail_labels", "google", "Lista os rótulos do Gmail", google_gmail_labels),
    # --- Google Workspace (escrita — admin + confirmação de 2 passos) ---
    _spec("google_drive_create", "google", "Cria UM arquivo de texto no Drive (dono, com confirmação)", google_drive_create,
          {"required": ["name"], "properties": {
              "name": S,
              "content": {**S, "default": ""},
              "user_id": {**S, "default": ""},
              "alvo": {**S, "default": ""},
          }}),
    _spec("google_drive_update", "google", "Substitui o conteúdo de UM arquivo do Drive (dono, com confirmação)", google_drive_update,
          {"required": ["content"], "properties": {
              "name": {**S, "default": ""},
              "content": S,
              "file_id": {**S, "default": ""},
              "user_id": {**S, "default": ""},
              "alvo": {**S, "default": ""},
          }}),
    _spec("google_drive_delete", "google", "Apaga UM arquivo do Drive (dono, com confirmação)", google_drive_delete,
          {"properties": {
              "name": {**S, "default": ""},
              "file_id": {**S, "default": ""},
              "user_id": {**S, "default": ""},
              "alvo": {**S, "default": ""},
          }}),
    _spec("google_calendar_create", "google", "Cria UM compromisso na Agenda (dono, com confirmação)", google_calendar_create,
          {"required": ["titulo"], "properties": {
              "titulo": S,
              "quando": {**S, "default": ""},
              "start": {**S, "default": ""},
              "end": {**S, "default": ""},
              "user_id": {**S, "default": ""},
              "alvo": {**S, "default": ""},
          }}),
    _spec("google_calendar_delete", "google", "Apaga UM compromisso da Agenda (dono, com confirmação)", google_calendar_delete,
          {"properties": {
              "titulo": {**S, "default": ""},
              "event_id": {**S, "default": ""},
              "user_id": {**S, "default": ""},
              "alvo": {**S, "default": ""},
          }}),
    _spec("google_gmail_send", "google", "Envia UM e-mail (dono, com confirmação)", google_gmail_send,
          {"required": ["para"], "properties": {
              "para": S,
              "assunto": {**S, "default": ""},
              "corpo": {**S, "default": ""},
              "user_id": {**S, "default": ""},
              "alvo": {**S, "default": ""},
          }}),
    _spec("google_gmail_delete", "google", "Move UM e-mail para a lixeira (dono, com confirmação)", google_gmail_delete,
          {"properties": {
              "termo": {**S, "default": ""},
              "message_id": {**S, "default": ""},
              "user_id": {**S, "default": ""},
              "alvo": {**S, "default": ""},
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
    # --- Ferramentas Nômade (Project NOMAD absorvido — 8 containers ativos;
    #     Homebox fora do ar desde 17/10/2026) ---
    _spec("nomad_tools_up", "nomad", "Sobe todos os containers das ferramentas Nômade (docker compose up -d)", nomad_tools_up),
    _spec("nomad_tools_down", "nomad", "Derruba todos os containers das ferramentas Nômade (docker compose down)", nomad_tools_down),
    _spec("nomad_tools_status", "nomad", "Status dos containers Nômade (docker compose ps)", nomad_tools_status),
    _spec("nomad_tools_logs", "nomad", "Logs de um serviço Nômade", nomad_tools_logs,
          {"properties": {"service": {**S, "default": ""}, "lines": {**I, "default": 100}}}),
    _spec("nomad_tools_restart", "nomad", "Reinicia um serviço Nômade específico", nomad_tools_restart,
          {"required": ["service"], "properties": {"service": S}}),
    _spec("nomad_tools_tailscale_serve", "nomad", "Gerencia tailscale serve para ferramentas Nômade", nomad_tools_tailscale_serve,
          {"properties": {"service": {**S, "default": ""}, "action": {**S, "default": "up"}}}),
    _spec("nomad_wikipedia_zim_download", "nomad", "Baixa o arquivo ZIM da Wikipédia para o Kiwix", nomad_wikipedia_zim_download,
          {"properties": {"url": {**S, "default": ""}, "dest": {**S, "default": ""}}}),
    _spec("nomad_vaultwarden_setup", "nomad", "Configura Vaultwarden: cria conta admin e desabilita signups", nomad_vaultwarden_setup,
          {"properties": {"admin_email": {**S, "default": ""}, "admin_password": {**S, "default": ""}, "disable_signups": {**B, "default": True}}}),
    # --- Vaultwarden: cofre do sistema (1ª interligação das ferramentas, 17/10) ---
    _spec("vault_status", "vault", "Estado do cofre do sistema (bw + alcançabilidade)", vault_status),
    _spec("vault_list", "vault", "Lista os itens do cofre (títulos, sem valores)", vault_list),
    _spec("vault_get", "vault", "Lê um segredo do cofre pelo nome", vault_get,
          {"required": ["name"], "properties": {"name": S}}),
    _spec("vault_set", "vault", "Cria/atualiza um segredo no cofre", vault_set,
          {"required": ["name", "password"], "properties": {"name": S, "password": S, "username": {**S, "default": ""}, "note": {**S, "default": ""}}}),
    # --- Stirling PDF: pipeline de documentos (2ª interligação das ferramentas, 17/10) ---
    _spec("stirling_status", "stirling", "Estado do Stirling PDF (versão + status da API)", stirling_status),
    _spec("stirling_merge", "stirling", "Junta 2+ PDFs (caminhos separados por vírgula) em um arquivo", stirling_merge,
          {"required": ["arquivos", "saida"], "properties": {"arquivos": S, "saida": S, "substituir": {**B, "default": False}}}),
    _spec("stirling_split", "stirling", "Corta um PDF nos pontos de corte (ex.: \"2\", \"2,5\", \"5-9\", \"all\")", stirling_split,
          {"required": ["arquivo", "saida"], "properties": {"arquivo": S, "saida": S, "cortes": {**S, "default": "all"}, "substituir": {**B, "default": False}}}),
    _spec("stirling_compress", "stirling", "Comprime um PDF (nivel 1-9, alvo tipo \"25KB\", cinza opcional)", stirling_compress,
          {"required": ["arquivo", "saida"], "properties": {"arquivo": S, "saida": S, "nivel": {**I, "default": 4}, "alvo": {**S, "default": "25KB"}, "cinza": {**B, "default": False}, "substituir": {**B, "default": False}}}),
    # --- Kiwix: acervo offline (3ª interligação das ferramentas, 17/10) ---
    _spec("kiwix_status", "kiwix", "Acervos carregados no Kiwix (Wikipédia offline)", kiwix_status),
    _spec("kiwix_busca", "kiwix", "Busca na Wikipédia OFFLINE (título, caminho, trecho)", kiwix_busca,
          {"required": ["pattern"], "properties": {"pattern": S, "quantidade": {**I, "default": 5}}}),
    _spec("kiwix_leitura", "kiwix", "Lê um artigo offline pelo caminho (texto limpo, com corte declarado)", kiwix_leitura,
          {"required": ["caminho"], "properties": {"caminho": S, "max_chars": {**I, "default": 8000}}}),
    # --- Homebox: inventário do dono (4ª ferramenta, uso definido 17/10) ---
    _spec("homebox_status", "homebox", "Inventário: versão + totais (itens, locais, tags)", homebox_status),
    _spec("homebox_busca", "homebox", "Busca peças no inventário (o dono tem X? o que sobrou de Y?)", homebox_busca,
          {"required": ["query"], "properties": {"query": S, "quantidade": {**I, "default": 10}}}),
    _spec("homebox_listar", "homebox", "Lista o inventário (opcional por tags: \"a, b\")", homebox_listar,
          {"properties": {"quantidade": {**I, "default": 25}, "tags": {**S, "default": ""}}}),
    _spec("homebox_detalhar", "homebox", "Detalha UMA peça (notas, compra, garantia, série)", homebox_detalhar,
          {"required": ["id"], "properties": {"id": S}}),
    _spec("homebox_criar", "homebox", "Cadastra UMA peça (tipo/tags inexistentes são criados e declarados)", homebox_criar,
          {"required": ["nome"], "properties": {
              "nome": S, "quantidade": {**I, "default": 1}, "tipo": {**S, "default": ""},
              "descricao": {**S, "default": ""}, "notas": {**S, "default": ""}, "tags": {**S, "default": ""},
              "preco": {"type": "float"}, "criar_tipo": {**B, "default": True}, "criar_tag": {**B, "default": True},
          }}),
    _spec("homebox_atualizar", "homebox", "Atualiza UMA peça (ex.: gastou resistores → nova quantidade)", homebox_atualizar,
          {"required": ["id"], "properties": {
              "id": S, "quantidade": {"type": "int"}, "notas": S, "descricao": S, "preco": {"type": "float"},
          }}),
    # --- FlatNotes: caderno de notas do dono (5ª interligação, 18/10) ---
    _spec("flatnotes_status", "flatnotes", "Estado do caderno (auth, nº de notas, última editada)", flatnotes_status),
    _spec("flatnotes_anota", "flatnotes", "Cria uma nota no caderno do dono (título + conteúdo markdown)", flatnotes_anota,
          {"required": ["titulo"], "properties": {
              "titulo": S, "conteudo": {**S, "default": ""}, "sobrescrever": {**B, "default": False},
          }}),
    _spec("flatnotes_busca", "flatnotes", "Busca nas notas do dono (texto livre, trecho do que casou)", flatnotes_busca,
          {"required": ["termo"], "properties": {"termo": S, "limite": {**I, "default": 10}}}),
    # --- File Browser: caixa de arquivos do dono (2ª interligação, 18/10) ---
    _spec("filebrowser_status", "filebrowser", "Estado da caixa de arquivos (saúde, versão, nº de itens, disco)", filebrowser_status),
    _spec("filebrowser_lista", "filebrowser", "Lista o que tem na caixa do dono (raiz por padrão, pasta por extensão)", filebrowser_lista,
          {"properties": {"caminho": {**S, "default": ""}}}),
    _spec("filebrowser_envia", "filebrowser", "Deixa um arquivo do sistema na caixa (o dono baixa pelo celular)", filebrowser_envia,
          {"required": ["origem", "destino"], "properties": {
              "origem": S, "destino": S, "substituir": {**B, "default": False},
          }}),
    # --- Calibre: biblioteca de e-books do dono (3ª análise "uma por vez", 19/10) ---
    _spec("calibre_resync", "calibre", "Espelha a biblioteca do dono (Google Drive) e importa na Calibre (calibredb; nada é sobrescrito/apagado)", calibre_resync),
    _spec("calibre_status", "calibre", "Saúde da Biblioteca: sonda OPDS ao vivo (tailnet), nº de livros/formatos e pendências de importar", calibre_status),
    _spec("calibre_busca", "calibre", "Busca livros no Calibre Web via OPDS (título/autor; formatos e links de download prontos)", calibre_busca,
          {"required": ["termo"], "properties": {
              "termo": S, "limite": {**I, "default": 10},
          }}),
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
    # --- Saúde — referência médica determinística (3, Parte C NOMAD) ---
    # Somente fonte curada de domínio público + bula FDA; disclaimer
    # obrigatório no formatador; NUNCA cai no LLM (ver core/intents.py).
    _spec("saude_condicao", "saude", "Cuidados caseiros/naturais curados por condição (CDC/NIH/NCCIH)",
          saude_condicao,
          {"required": ["texto"], "properties": {"texto": S}}),
    _spec("saude_interacoes", "saude", "Interação entre medicamentos citados (bula FDA via openFDA)",
          saude_interacoes,
          {"required": ["texto"], "properties": {"texto": S}}),
    _spec("saude_medicamento", "saude", "Bula FDA (indicações/avisos) do medicamento citado",
          saude_medicamento,
          {"required": ["texto"], "properties": {"texto": S}}),
]

ACTIONS_COUNT = len(CATALOG)

CATEGORIES: dict[str, int] = {}
for _entry in CATALOG:
    CATEGORIES[_entry["category"]] = CATEGORIES.get(_entry["category"], 0) + 1
