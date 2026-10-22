#!/usr/bin/env python3
"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: tools/monitor/network_watchdog.py
Descrição: VIGIA DA REDE — inventário de dispositivos da LAN + detecção de
           intrusão, a serviço do dono ("o sistema consegue saber todos os
           dispositivos da rede e avisar se alguém tentou invadir? — sim,
           alerta primeiro", 21/10/2026).

           Segue o MESMO contrato do router_monitor.sh: o monitor só
           REGISTRA (JSON-lines em <OD_LOG_DIR>/network_watchdog.log); a
           ponte para o Telegram é a sonda `_check_network` do
           integrations/notifier.py (anti-spam/cooldown por lá).

           Duas camadas:
             1) RÁPIDA (todo ciclo, ~8s, sem dependência nenhuma):
                varredura ARP da LAN (ping + `ip neigh`) → diff contra o
                inventário → MAC novo vira evento `dispositivo_novo` e fica
                PENDENTE até o dono resolver (resumo no Telegram, lembrete
                a cada cooldown de 1h enquanto pendente).
             2) RICA (a cada OD_VIGIA_RICH_A_CADA ciclos, se o venv do
                chromium existir): varre a UI real do roteador — lista de
                clientes (nome/sinal, enriquece o inventário) e o Registo
                de Eventos (login errado/DoS/bloqueio) — e o journal do
                sshd do servidor (Failed password/Invalid user). Eventos de
                segurança também ficam pendentes até `--ack-seguranca`.

           Proteção: o vigia NÃO bloqueia sozinho (escolha do dono:
           "alerta primeiro"). `--bloquear MAC` é modo de OPERADOR — roda
           sob ordem e adiciona o MAC à lista de negação do roteador pela
           UI real (Controlo de Acesso), com releitura como prova.

Uso:
   network_watchdog.py                 # = --once (ciclo do timer)
   network_watchdog.py --seed          # semeia inventário com a rede atual
   network_watchdog.py --conhecer MAC [nome]   # reconhece dispositivo (limpa pendência)
   network_watchdog.py --ack-seguranca # limpa eventos de segurança pendentes
   network_watchdog.py --bloquear MAC  # OPERADOR: adds MAC à lista de negação
   network_watchdog.py --report        # resumo humano do inventário

Saída (JSON-lines, <OD_LOG_DIR>/network_watchdog.log):
   {ts, tipo:"varredura", ativos, novos, rico}                     # ciclo comum
   {ts, tipo:"dispositivo_novo", mac, ip, fabricante, nome?}       # alerta
   {ts, tipo:"seguranca", origem, msg, ts_evento}                  # alerta
   {ts, tipo:"estado", ativos, pendentes_novos[], pendentes_seguranca[], rich}
                                       # ÚLTIMA linha = contrato da sonda

Configuração (env, todas opcionais):
   OD_LOG_DIR            diretório de logs/estado     (padrão <repo>/logs)
   OD_VIGIA_REDE         prefixo IPv4 da LAN          (padrão 192.168.0.)
   OD_VIGIA_ALCANCE      IPs varridos (teste)         (padrão .2..254 da rede)
   OD_VIGIA_RICH_A_CADA  ciclos entre varreduras ricas (padrão 3 = 15 min)
   OD_VIGIA_RICH         0 desliga a camada rica       (padrão 1)
   OD_VIGIA_VENV_PY      python do venv com playwright
                         (padrão /home/alex/od-vigia-venv/bin/python)
   OD_ROUTER_IP          gateway (compartilhado com router_monitor)
   OD_VIGIA_MAX_LOG_BYTES rotação do log (padrão 5 MiB)
   ROUTER_ADMIN_PASSWORD senha da UI do roteador (só a camada rica usa;
                         vem do EnvironmentFile da unit — nunca é logada)

Exit code: `--once`/`--seed` saem 0 sempre que o ciclo rodou — inclusive
com a rede vazia ou a UI do roteador fora (mesma lição do router_monitor:
estado é registro, não exit code). Falha dura só com `--bloquear` (opera-
ção de mutação precisa saber se não aconteceu).

HISTÓRICO — por que existe (21/10/2026):
   Revisão de portas do dia mostrou que o único vetor real de invasão é
   quem entra pela WiFi (CGNAT + nenhuma porta aberta = zero exposição
   externa). O roteador expõe lista completa de clientes e log de
   eventos; este monitor transforma isso em inventário + alarme, e o
   bloqueio fica sob ordem direta do dono.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

# -- Configuração -------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = Path(os.environ.get("OD_LOG_DIR", str(REPO_ROOT / "logs")))
LOG_FILE = LOG_DIR / "network_watchdog.log"
ESTADO_FILE = LOG_DIR / "network_watchdog_estado.json"

REDE = os.environ.get("OD_VIGIA_REDE", "192.168.0.")
GATEWAY = os.environ.get("OD_ROUTER_IP", "192.168.0.1")
RICH_A_CADA = int(os.environ.get("OD_VIGIA_RICH_A_CADA", "3"))
RICH_HABILITADO = os.environ.get("OD_VIGIA_RICH", "1") == "1"
# Consulta de fabricante (OUI) na rede — OD_VIGIA_OUI=0 desliga (testes e
# ambientes sem internet continuam integros: cache/local sem consulta).
OUI_HABILITADO = os.environ.get("OD_VIGIA_OUI", "1") == "1"
VENV_PY = os.environ.get(
    "OD_VIGIA_VENV_PY", "/home/alex/od-vigia-venv/bin/python"
)
SCRIPT_RICH = Path(__file__).resolve().parent / "vigia_rich.py"
MAX_LOG_BYTES = int(os.environ.get("OD_VIGIA_MAX_LOG_BYTES", str(5 * 1024 * 1024)))

Fuso = timezone(timedelta(hours=-3))


def _consulta_oui():
    """Consulta OUI real só quando habilitada (OD_VIGIA_OUI)."""
    return consulta_oui_maclookup if OUI_HABILITADO else None


def agora_iso() -> str:
    return datetime.now(Fuso).isoformat(timespec="seconds")


# -- Funções puras (testadas) -------------------------------------------------


def normaliza_mac(mac: str) -> str:
    """MAC canônico: maiúsculas separadas por ':' (Aceita aa-bb, AABBCC…)."""
    hexa = re.sub(r"[^0-9A-Fa-f]", "", mac).upper()
    if len(hexa) != 12:
        return mac.strip().upper()
    return ":".join(hexa[i:i + 2] for i in range(0, 12, 2))


def prefixo_oui(mac: str) -> str:
    """Primeiros 6 hex do MAC (bloco OUI), sem separadores."""
    return re.sub(r"[^0-9A-Fa-f]", "", mac).upper()[:6]


def vizinhos_lan(texto_ip_neigh: str, rede: str = REDE) -> dict[str, str]:
    """Extrai {mac: ip} dos vizinhos LAN a partir da saída de `ip neigh`.

    Regras: só IPv4 da rede, estado diferente de FAILED, sem docker/IPv6.
   """
    resultado: dict[str, str] = {}
    for linha in texto_ip_neigh.splitlines():
        partes = linha.split()
        if len(partes) < 4 or partes[1] != "dev":
            continue
        ip, estado = partes[0], partes[-1]
        if estado == "FAILED" or not ip.startswith(rede):
            continue
        try:
            lladdr = partes[partes.index("lladdr") + 1]
        except (ValueError, IndexError):
            continue
        resultado[normaliza_mac(lladdr)] = ip
    return resultado


def classificar_novos(
    vizinhos: dict[str, str], dispositivos: dict[str, dict]
) -> tuple[list[dict], list[str]]:
    """Divide a varredura em (novos registros, MACs já conhecidos).

    Novo = MAC ausente do inventário. Conhecidos levam ip/ultima_vez
    atualizados pelo chamador (aqui só devolvemos os MACs).
    """
    novos: list[dict] = []
    vistos: list[str] = []
    for mac, ip in sorted(vizinhos.items()):
        if mac in dispositivos:
            vistos.append(mac)
        else:
            novos.append({"mac": mac, "ip": ip, "primeira_vez": agora_iso()})
    return novos, vistos


# Ruído conhecido do log do roteador que NÃO é evento de segurança
_RUIDO_LOG_ROTEADOR = (
    "dhcpv6", "auto update", "exception", "ntp", "clock", "ipv6",
)


def evento_seguranca(linha: str, origem: str) -> Optional[dict]:
    """Classifica uma linha de log como evento de segurança (ou None).

    origem='roteador': Registo de Eventos do Sistema (inglês no log, UI
    em PT). origem='sshd': journal do servidor.
    """
    texto = linha.strip()
    if not texto:
        return None
    baixo = texto.lower()
    if any(r in baixo for r in _RUIDO_LOG_ROTEADOR):
        return None
    if origem == "sshd":
        gatilhos = ("failed password", "invalid user", "authentication failure")
    else:
        gatilhos = (
            "login failed", "illegal", "attack", "dos ", "intrusion",
            "blocked", "invalid user", "auth fail", "wrong password",
        )
    if any(g in baixo for g in gatilhos):
        return {"origem": origem, "msg": texto[:240], "ts_evento": agora_iso()}
    return None


_MAC_RE = re.compile(
    r"([0-9A-Fa-f]{2}(?:[-:][0-9A-Fa-f]{2}){5})"
)
# Sem `\b` inicial de propósito: na grade real o IP vem COLADO ao MAC
# ("...AC-F0192.168.0.250") — dígito na frente de dígito não tem fronteira.
_IP_RE = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})\b")


def parse_linhas_clientes(linhas: list[str]) -> list[dict]:
    """Parse das linhas da grade 'Clientes' do mapa de rede do roteador.

    Formato real capturado (21/10): nome na 1ª célula, MAC colado no IP
    ("00-0F-00-37-AC-F0192.168.0.250"). Devolve [{nome, mac, ip}].
    """
    clientes: list[dict] = []
    for linha in linhas:
        m_mac = _MAC_RE.search(linha)
        if not m_mac:
            continue
        mac = normaliza_mac(m_mac.group(1))
        m_ip = _IP_RE.search(linha, m_mac.end())
        ip = m_ip.group(1) if m_ip else ""
        nome = linha.split("|")[0].strip() or linha.split("|")[1].strip()
        if nome in ("?", "Desconhecido"):
            nome = ""
        clientes.append({"nome": nome[:40], "mac": mac, "ip": ip})
    return clientes


def rotaciona_log(caminho: Path, max_bytes: int) -> None:
    """Rotação simples: >max_bytes vira .1 (mesma convenção do router_monitor)."""
    try:
        if caminho.exists() and caminho.stat().st_size > max_bytes:
            velho = caminho.with_suffix(caminho.suffix + ".1")
            if velho.exists():
                velho.unlink()
            caminho.rename(velho)
    except OSError:
        pass


def fabricante_de(
    mac: str, cache: dict[str, str],
    consulta: Optional[Callable[[str], Optional[str]]] = None,
) -> str:
    """Fabricante via OUI (api.maclookup.app), com cache em estado.

    Nunca derruba o ciclo: sem rede/falha → 'desconhecido' (e o cache
    fica para a próxima).
    """
    prefixo = prefixo_oui(mac)
    if not prefixo:
        return "desconhecido"
    if prefixo in cache:
        return cache[prefixo]
    if consulta is None:
        return "desconhecido"
    try:
        nome = consulta(prefixo)
    except Exception:
        nome = None
    cache[prefixo] = nome or "desconhecido"
    return cache[prefixo]


def consulta_oui_maclookup(prefixo: str, timeout: float = 5.0) -> Optional[str]:
    """Consulta real do OUI (injetável nos testes via fabricante_de)."""
    url = f"https://api.maclookup.app/v2/macs/{prefixo}"
    with urllib.request.urlopen(url, timeout=timeout) as resposta:
        dados = json.loads(resposta.read().decode("utf-8"))
    if dados.get("found"):
        return str(dados.get("company") or "").strip() or None
    return None


# -- Funções de I/O -----------------------------------------------------------


def varre_lan(rede: str, alcance: Optional[list[str]] = None) -> dict[str, str]:
    """Sweep ARP: ping curto em todos os hosts + `ip neigh` como espelho.

    O ping (1 pacote, timeout 1s, 32 em paralelo) força a resolução ARP;
    em seguida o `ip neigh` do kernel devolve mac↔ip de tudo que respondeu.
    """
    ips = alcance or [f"{rede}{i}" for i in range(2, 255)]

    def pinga(ip: str) -> None:
        subprocess.run(
            ["ping", "-c", "1", "-W", "1", ip],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    with ThreadPoolExecutor(max_workers=32) as pool:
        list(pool.map(pinga, ips))
    try:
        texto = subprocess.run(
            ["ip", "neigh"], capture_output=True, text=True, timeout=10
        ).stdout
    except Exception:
        texto = ""
    return vizinhos_lan(texto, rede)


def journal_sshd(desde: str) -> str:
    """Eventos de autenticação do sshd desde `desde` (formato journalctl)."""
    try:
        return subprocess.run(
            ["journalctl", "-q", "--no-pager", "-u", "ssh", "-u", "sshd",
             "--since", desde],
            capture_output=True, text=True, timeout=15,
        ).stdout
    except Exception:
        return ""


def rodar_rich(senha: str, timeout: int = 150) -> Optional[dict]:
    """Roda a camada rica (venv com playwright) e devolve o JSON dela."""
    if not senha or not Path(VENV_PY).exists():
        return None
    try:
        proc = subprocess.run(
            [VENV_PY, str(SCRIPT_RICH)],
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "ROUTER_PASS": senha},
        )
        if proc.returncode != 0:
            return {"_erro": (proc.stderr or "falhou")[:200]}
        return json.loads(proc.stdout)
    except Exception as exc:
        return {"_erro": f"{type(exc).__name__}: {exc}"[:200]}


def carregar_estado() -> dict:
    if ESTADO_FILE.exists():
        try:
            return json.loads(ESTADO_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "dispositivos": {}, "pendentes_novos": [], "pendentes_seguranca": [],
        "ciclos": 0, "rich_ultima": None, "vendor_cache": {},
        "sshd_desde": None,
    }


def salvar_estado(estado: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ESTADO_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    tmp.replace(ESTADO_FILE)


def registrar(linhas: list[dict]) -> None:
    """Acrescenta eventos ao log (uma chamada por ciclo) + rotação."""
    if not linhas:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    rotaciona_log(LOG_FILE, MAX_LOG_BYTES)
    with open(LOG_FILE, "a", encoding="utf-8") as fh:
        for registro in linhas:
            fh.write(json.dumps(registro, ensure_ascii=False) + "\n")


# -- Ciclo principal ----------------------------------------------------------


def ciclo(*, seed: bool = False) -> dict:
    """Um ciclo do vigia. `seed` reconhece tudo que está na rede agora."""
    estado = carregar_estado()
    dispositivos: dict[str, dict] = estado["dispositivos"]
    eventos: list[dict] = []

    # 1) Camada rápida — varredura ARP + diff
    alcance = (
        os.environ["OD_VIGIA_ALCANCE"].split(",")
        if os.environ.get("OD_VIGIA_ALCANCE") else None
    )
    vizinhos_injetado = os.environ.get("OD_VIGIA_VIZINHOS_JSON")
    if vizinhos_injetado:
        vizinhos = {normaliza_mac(m): ip for m, ip in
                    json.loads(vizinhos_injetado).items()}
    else:
        vizinhos = varre_lan(REDE, alcance)

    novos, vistos = classificar_novos(vizinhos, dispositivos)
    ts = agora_iso()
    for mac, ip in vizinhos.items():
        if mac in dispositivos:
            dispositivos[mac]["ip"] = ip
            dispositivos[mac]["ultima_vez"] = ts

    for novo in novos:
        mac = novo["mac"]
        fabricante = fabricante_de(
            mac, estado["vendor_cache"], _consulta_oui()
        )
        dispositivos[mac] = {
            "ip": novo["ip"], "nome": "", "conhecido": bool(seed),
            "primeira_vez": ts, "ultima_vez": ts, "fabricante": fabricante,
            "nota": "semeado em " + ts if seed else "",
        }
        if not seed:
            estado["pendentes_novos"].append({
                "mac": mac, "ip": novo["ip"], "fabricante": fabricante,
                "desde": ts,
            })
            eventos.append({
                "ts": ts, "tipo": "dispositivo_novo", "mac": mac,
                "ip": novo["ip"], "fabricante": fabricante,
            })

    # 2) Camada rica — a cada N ciclos (ou no seed), se habilitada e possível
    rico = False
    deve_rich = seed or (estado["ciclos"] % max(1, RICH_A_CADA) == 0)
    if deve_rich and RICH_HABILITADO:
        dados = rodar_rich(os.environ.get("ROUTER_ADMIN_PASSWORD", ""))
        if dados and not dados.get("_erro"):
            rico = True
            estado["rich_ultima"] = ts
            # 2a) clientes do roteador: enriquece nomes + pega novos que
            #     não responderam ao ping (ex.: celular dormindo acorda na UI)
            for cliente in dados.get("clientes", []):
                mac, nome = cliente.get("mac", ""), cliente.get("nome", "")
                if mac in dispositivos:
                    if nome:
                        dispositivos[mac]["nome"] = nome
                elif mac:
                    fabricante = fabricante_de(
                        mac, estado["vendor_cache"], _consulta_oui()
                    )
                    dispositivos[mac] = {
                        "ip": cliente.get("ip", ""), "nome": nome,
                        "conhecido": bool(seed), "primeira_vez": ts,
                        "ultima_vez": ts, "fabricante": fabricante,
                        "nota": "visto só na UI do roteador",
                    }
                    if not seed:
                        estado["pendentes_novos"].append({
                            "mac": mac, "ip": cliente.get("ip", ""),
                            "fabricante": fabricante, "desde": ts,
                        })
                        eventos.append({
                            "ts": ts, "tipo": "dispositivo_novo", "mac": mac,
                            "ip": cliente.get("ip", ""), "fabricante": fabricante,
                            "origem": "ui_roteador",
                        })
            # 2b) log do roteador + journal sshd → eventos de segurança
            pendentes = estado["pendentes_seguranca"]
            chaves = {(p["origem"], p["msg"]) for p in pendentes}
            for linha in dados.get("log_roteador", []):
                ev = evento_seguranca(linha, "roteador")
                if ev and (ev["origem"], ev["msg"]) not in chaves:
                    pendentes.append(ev)
                    chaves.add((ev["origem"], ev["msg"]))
                    eventos.append({"ts": ts, "tipo": "seguranca", **ev})
            desde = estado.get("sshd_desde") or (
                datetime.now(Fuso) - timedelta(minutes=30)
            ).isoformat(timespec="seconds")
            # .splitlines() de propósito: journal_sshd devolve o stdout
            # INTEIRO (string) — iterar a string seria iterar CARACTERES e
            # nenhum "Failed password" jamais casaria (defeito real achado
            # pelo teste em processo de 22/10; a camada sshd ficou muda).
            texto_ssh = journal_sshd(
                desde.replace("T", " ").replace("-03:00", ""))
            for linha in texto_ssh.splitlines():
                ev = evento_seguranca(linha, "sshd")
                if ev and (ev["origem"], ev["msg"]) not in chaves:
                    pendentes.append(ev)
                    chaves.add((ev["origem"], ev["msg"]))
                    eventos.append({"ts": ts, "tipo": "seguranca", **ev})
            estado["sshd_desde"] = ts
        elif dados and dados.get("_erro"):
            eventos.append({
                "ts": ts, "tipo": "rich_erro", "detalhe": dados["_erro"][:160],
            })

    # 3) Estado: pendências + linha de estado (contrato da sonda)
    if seed:
        # Seed reconhece TUDO: o que a varredura achou E o que já estava no
        # inventário como desconhecido (ex.: o primeiro ciclo do systemd
        # antes do seed catalogou a casa inteira como "novo").
        for registro in dispositivos.values():
            registro["conhecido"] = True
        estado["pendentes_novos"] = []
        estado["pendentes_seguranca"] = []
    ativos = len(dispositivos)
    estado["ciclos"] = int(estado["ciclos"]) + 1
    estado["ultima_varredura"] = {
        "ts": ts, "ativos": len(vizinhos), "novos": len(novos), "rico": rico,
    }
    eventos.append({
        "ts": ts, "tipo": "varredura", "ativos": len(vizinhos),
        "novos": len(novos), "rico": rico,
    })
    eventos.append({
        "ts": ts, "tipo": "estado", "ativos": ativos,
        "conhecidos_ativos": sum(
            1 for m in vizinhos if dispositivos.get(m, {}).get("conhecido")
        ),
        "pendentes_novos": estado["pendentes_novos"],
        "pendentes_seguranca": estado["pendentes_seguranca"][-5:],
        "rich": rico,
    })
    registrar(eventos)
    salvar_estado(estado)
    return {"ativos": len(vizinhos), "novos": len(novos), "rico": rico,
            "pendentes_novos": len(estado["pendentes_novos"]),
            "pendentes_seguranca": len(estado["pendentes_seguranca"])}


# -- Modos de operador --------------------------------------------------------


def conhecer(mac: str, nome: str = "") -> None:
    estado = carregar_estado()
    chave = normaliza_mac(mac)
    alvo = estado["dispositivos"].get(chave)
    if alvo is None:
        print(f"MAC {chave} não está no inventário — varra de novo antes.")
        return
    alvo["conhecido"] = True
    if nome:
        alvo["nome"] = nome[:40]
    estado["pendentes_novos"] = [
        p for p in estado["pendentes_novos"] if p["mac"] != chave
    ]
    salvar_estado(estado)
    print(f"{chave} reconhecido" + (f" como {nome}" if nome else "") + ".")


def ack_seguranca() -> None:
    estado = carregar_estado()
    n = len(estado["pendentes_seguranca"])
    estado["pendentes_seguranca"] = []
    salvar_estado(estado)
    print(f"{n} evento(s) de segurança reconhecido(s).")


def bloquear(mac: str) -> int:
    """OPERADOR: adiciona o MAC à lista de negação do roteador (UI real)."""
    senha = os.environ.get("ROUTER_ADMIN_PASSWORD", "")
    if not senha or not Path(VENV_PY).exists():
        print("FALHA: sem senha (ROUTER_ADMIN_PASSWORD) ou venv do chromium.")
        return 2
    proc = subprocess.run(
        [VENV_PY, str(SCRIPT_RICH), "--bloquear", normaliza_mac(mac)],
        capture_output=True, text=True, timeout=150,
        env={**os.environ, "ROUTER_PASS": senha},
    )
    print((proc.stdout or proc.stderr or "sem saída").strip())
    return proc.returncode


def report() -> None:
    estado = carregar_estado()
    dispositivos = estado["dispositivos"]
    print(f"Inventário: {len(dispositivos)} dispositivo(s) — "
          f"ciclos: {estado['ciclos']} — "
          f"rich última: {estado.get('rich_ultima') or 'nunca'}")
    for mac, d in sorted(dispositivos.items(), key=lambda x: x[1].get("nome") or "zz"):
        marca = "conhecido" if d.get("conhecido") else "DESCONHECIDO"
        print(f"  [{marca:12}] {mac}  ip={d.get('ip','?'):15} "
              f"nome={d.get('nome') or '-':20} fab={d.get('fabricante','?')}")
    pend = estado["pendentes_novos"]
    seg = estado["pendentes_seguranca"]
    print(f"Pendências: {len(pend)} dispositivo(s) novo(s), "
          f"{len(seg)} evento(s) de segurança.")
    for p in pend:
        print(f"  NOVO: {p['mac']} ({p.get('fabricante','?')}) ip={p.get('ip','?')} desde {p.get('desde','?')}")
    for s in seg[-10:]:
        print(f"  SEGURANÇA [{s.get('origem')}]: {s.get('msg','')[:120]}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Vigia da Rede — OmegaDrakon")
    parser.add_argument("--once", action="store_true", help="um ciclo (timer)")
    parser.add_argument("--seed", action="store_true",
                        help="reconhece tudo que está na rede agora")
    parser.add_argument("--conhecer", nargs="+", metavar="MAC [NOME]",
                        help="reconhece um dispositivo (limpa pendência)")
    parser.add_argument("--ack-seguranca", action="store_true",
                        help="limpa eventos de segurança pendentes")
    parser.add_argument("--bloquear", metavar="MAC",
                        help="OPERADOR: bloqueia MAC no roteador (UI real)")
    parser.add_argument("--report", action="store_true", help="resumo humano")
    args = parser.parse_args(argv)

    if args.conhecer:
        conhecer(args.conhecer[0], args.conhecer[1] if len(args.conhecer) > 1 else "")
        return 0
    if args.ack_seguranca:
        ack_seguranca()
        return 0
    if args.bloquear:
        return bloquear(args.bloquear)
    if args.report:
        report()
        return 0
    try:
        resultado = ciclo(seed=args.seed)
    except Exception as exc:  # monitor precisa sobreviver — estado no log
        registrar([{"ts": agora_iso(), "tipo": "ciclo_erro",
                    "detalhe": f"{type(exc).__name__}: {exc}"[:200]}])
        return 0
    print(json.dumps(resultado, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
