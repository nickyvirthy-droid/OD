# Monitor do Roteador 📡

Monitora a disponibilidade do roteador (ping no gateway) e o estado da
interface de rede, correlacionando com os link changes do Tailscale — é o
insumo para explicar janelas de rede ruim que aparecem no `od-core`
(`Timeouts` do Telegram, `Transporte indisponível`, reconexões do MQTT).

## Como está rodando

Em produção o monitor é um **timer systemd de usuário** (`router-monitor.timer`,
de 1 em 1 minuto) chamando o script com `--once`. As units ficam versionadas em
`runtime/systemd/` (junto das do núcleo) e o instalador é o mesmo:

```bash
bash runtime/systemd/install-user.sh      # instala as 4 units + liga o timer
systemctl --user list-timers router-monitor.timer
systemctl --user status router-monitor.timer
```

O timer já vem habilitado no boot (`OnBootSec=1min`). O service é `oneshot` e
**não falha quando o roteador cai**: o estado é o registro no log (um unit em
falha a cada minuto durante uma queda seria ruído pelo motivo errado).

## Uso manual

```bash
tools/monitor/router_monitor.sh            # execução contínua (60s)
tools/monitor/router_monitor.sh --once     # uma verificação (o que o timer faz)
tools/monitor/router_monitor.sh --report   # resumo do log acumulado
```

## Saída

JSON-lines, uma linha por verificação, em `logs/`:

| Arquivo | Conteúdo |
|---|---|
| `logs/router_monitor.log` | `{ts, local, gateway, status, latency_ms, detail?}` — `status` é `up` ou `down` |
| `logs/interface_monitor.log` | `{ts, local, interface, state, carrier, speed}` |

Os dois rotacionam ao passar de `OD_MONITOR_MAX_BYTES` (padrão 5 MiB), mantendo
uma geração anterior (`<arquivo>.1`).

## Configuração (variáveis de ambiente)

| Variável | Padrão | Para quê |
|---|---|---|
| `OD_ROUTER_IP` | `192.168.0.1` | gateway pingado |
| `OD_NETWORK_INTERFACE` | `wlx000f0037acf0` | interface observada |
| `OD_MONITOR_INTERVAL` | `60` | segundos entre ciclos (modo contínuo) |
| `OD_MONITOR_PING_TIMEOUT` | `2` | timeout do ping, em segundos |
| `OD_MONITOR_MAX_BYTES` | `5242880` | tamanho que dispara a rotação |
| `OD_LOG_DIR` | `<repo>/logs` | diretório dos logs |

## Limites conhecidos

- **Não alerta sozinho**: registra no log; quem avisa é o notificador do núcleo
  (Telegram/push). Um alerta automático de "roteador fora" precisa do monitor
  dentro do processo do core — não é o desenho hoje.
- Correlação com o Tailscale é por contagem de `LinkChange: major` da última
  hora e depende do `journalctl` acessível ao usuário.
- O log é append puro por minuto; com a rotação, o histórico fica em duas
  gerações (atual + `.1`), não em histórico longo.

## Histórico

- **2026-09-17** — criado e ligado no systemd (não versionado na época).
- **2026-09-18** — versionado e **corrigido**: o script usava `set -e` com
  `x=$(ping ...)`, então toda verificação que falhava (roteador fora) matava o
  script **antes** de registrar o `down` — em 17h de operação deu 1086 linhas
  `up` e zero `down`, ou seja, o monitor era cego para o evento que existe para
  medir. O mesmo acontecia com o `cat` de uma interface ausente. Agora o script
  não usa `set -e`, cada comando externo tem fallback, `--once` sai 0 (o estado
  fica no log) e há rotação de log. Testes: `tests/test_router_monitor.py`.

---

# Vigia da Rede 🕵️ (21/10/2026)

Inventário de dispositivos da LAN + detecção de intrusão, a serviço do dono
(*"o sistema consegue saber todos os dispositivos da rede e avisar se alguém
tentou invadir?"* — escolha dele: **alerta primeiro**, bloqueio só sob ordem).

## Como está rodando

`network-watchdog.timer` (5 min, oneshot) chamando
`tools/monitor/network_watchdog.py --once`. Duas camadas:

- **Rápida** (todo ciclo, ~8 s, sem dependência externa): varredura ARP da
  LAN (ping + `ip neigh`) → diff contra o inventário
  (`logs/network_watchdog_estado.json`). MAC fora do inventário vira evento
  `dispositivo_novo` e fica **pendente** até `--conhecer` (lembrete a cada
  cooldown do notifier enquanto pendente).
- **Rica** (a cada 3º ciclo ≈ 15 min): `vigia_rich.py` dentro do venv
  durável `/home/alex/od-vigia-venv` (playwright/chromium — **fora do
  `/tmp`**, que morre no reboot) lê a UI real do Archer: lista de clientes
  (nome/sinal enriquecem o inventário; clientes que não responderam ao ping
  também entram) e o Registo de Eventos (classificado por
  `evento_seguranca`, com filtro de ruído e do menu lateral). Journal do
  sshd (`Failed password`/`Invalid user`) entra na mesma classe de evento.

A ponte para o Telegram é a sonda `_check_network`
(`integrations/notifier.py`): lê a **última linha de estado** do log
JSON-lines (contrato igual ao do `router_monitor`) e alerta
`net:dispositivo-novo` / `net:seguranca` com cooldown padrão. O monitor
**não** envia mensagem direta.

## Uso manual

```bash
python3 tools/monitor/network_watchdog.py --seed          # reconhece a rede atual
python3 tools/monitor/network_watchdog.py --conhecer MAC [NOME]
python3 tools/monitor/network_watchdog.py --ack-seguranca
python3 tools/monitor/network_watchdog.py --report        # resumo humano
ROUTER_ADMIN_PASSWORD=... python3 tools/monitor/network_watchdog.py --bloquear MAC   # OPERADOR, sob ordem
```

## Configuração (variáveis de ambiente)

`OD_LOG_DIR` · `OD_VIGIA_REDE` (padrão `192.168.0.`) · `OD_VIGIA_ALCANCE`
(teste) · `OD_VIGIA_RICH_A_CADA` (3) · `OD_VIGIA_RICH` (0 desliga) ·
`OD_VIGIA_OUI` (0 desliga a consulta de fabricante) · `OD_VIGIA_VENV_PY` ·
`OD_ROUTER_IP` · `OD_VIGIA_MAX_LOG_BYTES` (5 MiB) · `ROUTER_ADMIN_PASSWORD`
(via `EnvironmentFile=.env` na unit; nunca logada).

## Limites conhecidos

- Detecta e alerta; **não bloqueia sozinho** (`--bloquear` é operador e
  depende da UI do roteador não mudar).
- Celular dormindo pode não responder ao ping — a camada rica pega pelo
  `ip neigh`/UI, mas a detecção instantânea de MAC novo assume aparelho
  ativo (quem entra na rede está ativo).
- Sem internet, fabricante fica "desconhecido" (cache local); sem venv do
  chromium, a camada rica é pulada em silêncio e a rápida segue.
- Sob CGNAT nada de fora alcança a LAN: o vetor real é a senha de WiFi —
  vigia cobre quem usa, não quem descobre a senha.

## Histórico

- **2026-10-21** — criado e ligado no timer (`tests/test_network_watchdog.py`,
  77 testes; sonda em `tests/test_notifier.py::TestCheckNetwork`).
