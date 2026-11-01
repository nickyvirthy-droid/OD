#!/usr/bin/env python3
"""
OMEGA DRAKON • CORE
Módulo: tools/monitor/vigia_rich.py
Descrição: Camada RICA do Vigia da Rede — roda DENTRO do venv com
           playwright/chromium (OD_VIGIA_VENV_PY) e conversa com a UI real
           do Archer C6 por JSON no stdout. Chamado por
           tools/monitor/network_watchdog.py (não use direto).

Modos:
   (padrão)          varre clientes (#networkMap) + Registo de Eventos
                     (#sysLog) e imprime {"clientes": [...], "log_roteador": [...]}
   --bloquear MAC    OPERADOR: adiciona MAC à lista de negação
                     (Controlo de Acesso) e prova por releitura.
   --reservar MAC IP [NOME]
                      OPERADOR: cria Reserva de Endereço (Servidor DHCP,
                      #dhcpServerAdv) fixando IP para o MAC e prova por
                      releitura.

Env: ROUTER_PASS (obrigatória — senha da UI; nunca é logada/impressa).

Contrato de saída (padrão): JSON no stdout; exit 0. Login falhou → exit 2
com diagnóstico no stderr (sem senha). Rede do roteador fora → exit 3.
"""

from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from network_watchdog import parse_linhas_clientes  # noqa: E402  (parser único)

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = "http://192.168.0.1"
SENHA = os.environ.get("ROUTER_PASS", "")
MAC_RE = re.compile(r"([0-9A-Fa-f]{2}(?:[-:][0-9A-Fa-f]{2}){5})")
# Entradas REAIS do Registo seguem "<n> <TIPO> mensagem." — o menu lateral
# também usa tr.grid-content-tr e polui a grade; este filtro separa os dois.
_LOG_ENTRY_RE = re.compile(
    r"^\d+\s+(INFO|WARNING|ERROR|EXCEPTION|NOTICE|CRITICAL|ALERT)\b")


def _login(pg) -> bool:
    pg.goto(BASE, wait_until="domcontentloaded", timeout=20000)
    pg.locator("input[type='password']").first.wait_for(timeout=20000)
    pg.locator("input[type='password']").first.fill(SENHA)
    pg.keyboard.press("Enter")
    for _ in range(24):
        if pg.locator("input[type='password']").count() == 0:
            return True
        pg.wait_for_timeout(500)
    return False


def _espera_grade(pg, rota: str, timeout_ms: int = 12000) -> list[str]:
    """Navega à rota e espera as linhas da grade (renderizam atrasadas).

    Junta TODAS as células da linha com ' | ' (formato que o parser único
    de `network_watchdog.parse_linhas_clientes` espera): a primeira célula
    sozinha não tem MAC/IP — foi exatamente o bug da primeira versão.
    """
    pg.goto(f"{BASE}/#{rota}", wait_until="domcontentloaded", timeout=15000)
    for _ in range(timeout_ms // 500):
        linhas = pg.evaluate(
            "() => [...document.querySelectorAll('tr.grid-content-tr')]"
            ".map(l => {"
            "  const c = [...l.querySelectorAll('.content, .td-content')];"
            "  return (c.length ? c : [l])"
            "    .map(x => x.textContent.trim()).join(' | ');"
            "}).filter(Boolean)"
        )
        if linhas:
            return linhas
        pg.wait_for_timeout(500)
    return []


def _clientes(pg) -> list[dict]:
    pg.goto(f"{BASE}/#networkMap", wait_until="domcontentloaded", timeout=15000)
    for _ in range(30):
        linhas = pg.evaluate(
            "() => [...document.querySelectorAll('tr.grid-content-tr')]"
            ".map(l => {"
            "  const c = [...l.querySelectorAll('.content, .td-content')];"
            "  return (c.length ? c : [l])"
            "    .map(x => x.textContent.trim()).join(' | ');"
            "}).filter(Boolean)"
        )
        clientes = parse_linhas_clientes(linhas)
        if clientes:
            return clientes
        pg.wait_for_timeout(500)
    return []


def _log_roteador(pg) -> list[str]:
    pg.goto(f"{BASE}/#sysLog", wait_until="domcontentloaded", timeout=15000)
    for _ in range(24):  # a grade do log é lenta; fallback = texto cru
        linhas = pg.evaluate(
            "() => [...document.querySelectorAll('tr.grid-content-tr')]"
            ".map(l => l.textContent.trim().replace(/\\s+/g, ' '))"
            ".filter(Boolean)"
        )
        # só entradas REAIS ("<n> <TIPO> msg") — as linhas acima são o menu
        entradas = [l for l in linhas if _LOG_ENTRY_RE.match(l)]
        if entradas:
            return entradas[:60]
        pg.wait_for_timeout(500)
    try:
        cru = pg.inner_text("body")
        return [l.strip() for l in cru.splitlines()
                if _LOG_ENTRY_RE.match(l.strip())][:60]
    except Exception:
        return []


def _bloquear(pg, mac: str) -> dict:
    """Adiciona MAC à lista de negação (Controlo de Acesso) e prova."""
    pg.goto(f"{BASE}/#accessControl", wait_until="domcontentloaded",
            timeout=15000)
    pg.wait_for_timeout(4000)
    # já bloqueado?
    corpo = pg.inner_text("body")
    if mac.upper() in corpo.upper().replace("-", ":"):
        return {"ok": True, "ja_bloqueado": True}
    r = pg.evaluate("""() => {
      const b = [...document.querySelectorAll('a, button')].find(e =>
        e.offsetParent && /^Adicionar$/i.test((e.textContent||'').trim()));
      if (!b) return 'sem botao Adicionar';
      b.click(); return 'abriu';
    }""")
    if r != "abriu":
        return {"ok": False, "erro": r}
    pg.wait_for_timeout(1500)
    # diálogo: preenche o campo de MAC (formato do roteador: XX-XX-XX-XX-XX-XX)
    preenchido = pg.evaluate("""(mac) => {
      const campos = [...document.querySelectorAll('input[type=text]')]
        .filter(e => e.offsetParent && !e.readOnly);
      if (!campos.length) return 'sem campo';
      const alvo = campos.find(c => /mac/i.test(
        ((c.closest('tr, div')||{}).textContent||''))) || campos[0];
      alvo.value = mac;
      for (const ev of ['input','change','keyup'])
        alvo.dispatchEvent(new Event(ev, {bubbles: true}));
      return 'preencheu';
    }""", mac.upper().replace(":", "-"))
    pg.wait_for_timeout(800)
    # grava no diálogo e confirma eventuais pop-ups
    r = pg.evaluate("""() => {
      const b = [...document.querySelectorAll('a, button')].find(e =>
        e.offsetParent && /^(GRAVAR|Salvar|OK|Guardar)$/i.test(
          (e.textContent||'').trim()));
      if (!b) return 'sem gravar';
      b.click(); return 'clicou ' + b.textContent.trim();
    }""")
    pg.wait_for_timeout(3000)
    for _ in range(3):  # confirmações tipo SIM/OK
        ok = pg.evaluate("""() => {
          const b = [...document.querySelectorAll('a, button')].find(e =>
            e.offsetParent && /^(SIM|OK)$/i.test((e.textContent||'').trim()) &&
            !/PROCURAR|ATUALIZAR/.test((e.textContent||'').trim()));
          if (b) { b.click(); return true; } return false;
        }""")
        if not ok:
            break
        pg.wait_for_timeout(2000)
    # PROVA: releitura da lista de negação
    pg.goto(f"{BASE}/#networkMap", wait_until="domcontentloaded", timeout=15000)
    pg.wait_for_timeout(1500)
    pg.goto(f"{BASE}/#accessControl", wait_until="domcontentloaded", timeout=15000)
    pg.wait_for_timeout(4000)
    prova = mac.upper().replace(":", "-") in pg.inner_text("body").upper()
    return {"ok": prova, "gravacao": r, "mac": mac}


def _linhas_reservas(pg) -> list[str]:
    """Só as linhas da tabela de Reserva de Endereço (#dhcpServerAdv).

    O painel tem VÁRIAS grades na mesma página (reservas, clientes DHCP,
    banda); sem restringir ao painel da reserva, a prova casa por engano
    com a linha de cliente do próprio servidor.
    """
    return pg.evaluate(
        """() => {
        const vis = e => e.offsetParent !== null;
        const titulos = [...document.querySelectorAll('div,span,h2,h3,th')]
          .filter(e => /Reserva de Endere|Address Reservation/i.test(
            (e.textContent||'').trim()) && (e.textContent||'').trim().length < 40);
        for (const t of titulos) {
          let box = t;
          for (let k = 0; k < 6 && box; k++) {
            box = box.parentElement;
            if (box && box.querySelectorAll('tr.grid-content-tr').length) break;
          }
          if (box) {
            return [...box.querySelectorAll('tr.grid-content-tr')].map(l => {
              const c = [...l.querySelectorAll('.content, .td-content')];
              return (c.length ? c : [l])
                .map(x => x.textContent.trim()).join(' | ');
            }).filter(Boolean);
          }
        }
        return [];
      }"""
    )


def _reservar(pg, mac: str, ip: str, nome: str) -> dict:
    """Cria Reserva de Endereço (Servidor DHCP) fixando IP para o MAC e prova."""
    mac_fmt = mac.upper().replace(":", "-")
    pg.goto(f"{BASE}/#dhcpServerAdv", wait_until="domcontentloaded",
            timeout=15000)
    pg.wait_for_timeout(4000)
    # já reservado? (só a tabela de reservas, não a lista de clientes)
    if any(mac_fmt in l and ip in l for l in _linhas_reservas(pg)):
        return {"ok": True, "ja_reservado": True, "mac": mac, "ip": ip}
    r = pg.evaluate("""() => {
      const vis = e => e.offsetParent !== null;
      const b = [...document.querySelectorAll('a, button')]
        .filter(e => vis(e) && /^Adicionar$/i.test((e.textContent||'').trim()));
      if (!b.length) return 'sem botao Adicionar';
      b[0].click(); return 'abriu';
    }""")
    if r != "abriu":
        return {"ok": False, "erro": r}
    pg.wait_for_timeout(2000)
    # diálogo fixo do Archer C6: dentro do container do GRAVAR há 8 campos,
    # na ordem: 0=Nome, 1..6=octetos do MAC ('-----'), 7=Endereço IP.
    preenchido = pg.evaluate("""(dados) => {
      const {mac_fmt, ip, nome} = dados;
      const vis = e => e.offsetParent !== null;
      const gravar = [...document.querySelectorAll('a,button')]
        .find(e => vis(e) && /^GRAVAR$/i.test((e.textContent||'').trim()));
      if (!gravar) return 'sem GRAVAR';
      let box = gravar;
      while (box && box.querySelectorAll('input[type=text]').length < 8
             && box.parentElement) box = box.parentElement;
      const campos = [...box.querySelectorAll('input[type=text]')];
      if (campos.length < 8) return 'campos inesperados: ' + campos.length;
      const set = (el, v) => {
        el.value = v;
        for (const ev of ['input','change','keyup'])
          el.dispatchEvent(new Event(ev, {bubbles:true}));
      };
      if (nome) set(campos[0], nome);
      const oct = mac_fmt.split('-');
      for (let k = 0; k < 6; k++) set(campos[1 + k], oct[k]);
      set(campos[7], ip);
      return 'preencheu';
    }""", {"mac_fmt": mac_fmt, "ip": ip, "nome": nome})
    if preenchido != "preencheu":
        return {"ok": False, "erro": preenchido}
    pg.wait_for_timeout(800)
    r = pg.evaluate("""() => {
      const vis = e => e.offsetParent !== null;
      const b = [...document.querySelectorAll('a, button')].find(e =>
        vis(e) && /^(GRAVAR|Salvar|OK|Guardar)$/i.test((e.textContent||'').trim()));
      if (!b) return 'sem gravar';
      b.click(); return 'clicou ' + b.textContent.trim();
    }""")
    pg.wait_for_timeout(3000)
    for _ in range(3):  # confirmações tipo SIM/OK
        ok = pg.evaluate("""() => {
          const vis = e => e.offsetParent !== null;
          const b = [...document.querySelectorAll('a, button')].find(e =>
            vis(e) && /^(SIM|OK)$/i.test((e.textContent||'').trim()) &&
            !/PROCURAR|ATUALIZAR/.test((e.textContent||'').trim()));
          if (b) { b.click(); return true; } return false;
        }""")
        if not ok:
            break
        pg.wait_for_timeout(2000)
    # PROVA: releitura da tabela de reservas (não o corpo inteiro)
    pg.goto(f"{BASE}/#networkMap", wait_until="domcontentloaded", timeout=15000)
    pg.wait_for_timeout(1500)
    pg.goto(f"{BASE}/#dhcpServerAdv", wait_until="domcontentloaded",
            timeout=15000)
    pg.wait_for_timeout(4000)
    prova = any(mac_fmt in l and ip in l for l in _linhas_reservas(pg))
    return {"ok": prova, "gravacao": r, "mac": mac, "ip": ip, "nome": nome}


def main() -> int:
    if not SENHA:
        print("sem ROUTER_PASS", file=sys.stderr)
        return 2
    bloquear_mac = None
    if "--bloquear" in sys.argv:
        idx = sys.argv.index("--bloquear")
        if idx + 1 >= len(sys.argv):
            print("--bloquear exige MAC", file=sys.stderr)
            return 2
        bloquear_mac = sys.argv[idx + 1].upper().replace("-", ":")
    reservar_mac = reservar_ip = reservar_nome = None
    if "--reservar" in sys.argv:
        idx = sys.argv.index("--reservar")
        resto = sys.argv[idx + 1:]
        if len(resto) < 2:
            print("--reservar exige MAC e IP", file=sys.stderr)
            return 2
        reservar_mac = resto[0].upper().replace("-", ":")
        reservar_ip = resto[1]
        reservar_nome = resto[2] if len(resto) > 2 else ""

    with sync_playwright() as p:
        nav = p.chromium.launch(headless=True)
        pg = nav.new_page()
        pg.set_default_timeout(15000)
        try:
            if not _login(pg):
                print("login falhou", file=sys.stderr)
                return 2
            if bloquear_mac:
                resultado = _bloquear(pg, bloquear_mac)
                print(json.dumps(resultado, ensure_ascii=False))
                return 0 if resultado.get("ok") else 3
            if reservar_mac:
                resultado = _reservar(pg, reservar_mac, reservar_ip,
                                      reservar_nome or "")
                print(json.dumps(resultado, ensure_ascii=False))
                return 0 if resultado.get("ok") else 3
            clientes = _clientes(pg)
            log = _log_roteador(pg)
            print(json.dumps(
                {"clientes": clientes, "log_roteador": log},
                ensure_ascii=False))
            return 0
        except Exception as exc:
            print(f"rich: {type(exc).__name__}: {exc}"[:200], file=sys.stderr)
            return 3
        finally:
            nav.close()


if __name__ == "__main__":
    sys.exit(main())
