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
