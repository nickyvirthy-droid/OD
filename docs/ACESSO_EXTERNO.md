# OmegaDrakon — acesso externo (internet)

> Diagnóstico de 2026-09-21 (revisado com prova de mão dupla). Objetivo: o app
> funcionar **fora** da LAN/Tailscale. Hoje só o Tailscale funciona.

## O que está configurado

| Elemento | Valor |
|---|---|
| Servidor | `192.168.0.250` (Wi-Fi, **IP fixo** — rota `proto static`), gateway `192.168.0.1` |
| Roteador | TP-Link, UI `tpos` (firmware `c80_1.14.0_2024-10-08`), MAC `5c:62:8b:b7:0e:5c` |
| Link | PPPoE (MTU 1480) com IP público próprio: **189.124.4.56** (PTR `189-124-4-56.tcvnet.com.br`) |
| Tailscale | `100.77.67.53` — `nicky-server.tail1b1f51.ts.net` |
| Domínio (Dynu DDNS) | `nicky.theworkpc.com` → **189.124.4.56** (em dia) |
| API REST | `:8000` (sem TLS; exige `X-API-Key`/sessão em tudo — `OD_API_AUTH_ALL=1`) |
| WebSocket | `:8001` (sem TLS) |
| IPv6 nativo | `2804:428:3:6340:20f:ff:fe37:acf0/64` (global, dinâmico por RA) |
| App Flutter | primária `http://100.77.67.53:8000`, externa `http://nicky.theworkpc.com` |

## Diagnóstico fechado: a regra existe, quem barra é a operadora

Medições de 2026-09-21, com os serviços no ar:

| Teste | Origem | Resultado |
|---|---|---|
| `GET http://189.124.4.56/health` (porta 80) | **de dentro** | `401` com `Server: OmegaDrakon/1.2.0` — **é a nossa API** |
| `GET /supervision` local × via IP público | de dentro | **idênticos** (só o campo `ts` difere) — **mesmo processo** |
| `GET https://189.124.4.56:8443/` | de dentro | `403` do **próprio roteador** (mesmo perfil do `192.168.0.1`) |
| Sonda externa (check-host, 4–6 nós) | **de fora** | timeout em `80` e `8000` |
| Varredura externa (portchecker.io) | de fora | **fechadas**: 80, 443, 8000, 8443, 22, 1883 |
| `dig +short nicky.theworkpc.com` | público | `189.124.4.56` ✔ |
| `tracepath 8.8.8.8` | no servidor | hop 1 `192.168.0.1`, hop 2 `189.124.0.25` (público) → **NAT único, sem CGNAT** |

Leitura dessas medições:

1. **A regra de encaminhamento do roteador está ativa e certa** (80 → `192.168.0.250:8000`).
   O pedido feito ao IP público, por dentro, chega na nossa API — com o mesmo
   processo (o `/supervision` bate). Se a regra fosse inativa ou apontasse para
   IP antigo, isso não aconteceria.
2. **O roteador é o dono do IP público** (não há CGNAT nem segundo NAT): ele
   respondeu com a própria UI na `189.124.4.56:8443`, e só quem possui o IP
   pode fazer isso. O hop 2 já é a agregação da operadora.
3. **A `8443` do roteador também está fechada de fora.** Ou seja: não é só a
   porta 80. Um serviço que o roteador expõe na WAN e uma porta encaminhada
   ficam ambos inacessíveis a partir da internet → **o filtro de entrada está
   acima do roteador (operadora — Algar/TCV)**.

**Conclusão:** o app não tem defeito e o roteador não tem erro de configuração.
**Criar mais regras no roteador não resolve** — o tráfego de entrada não chega
na WAN. `curl` de dentro da rede **não** prova acesso externo (hairpin NAT);
foi assim que a verificação de 09-19 concluiu "FUNCIONANDO" sem estar.

## Opção A — Tailscale Funnel (recomendada)

Publica a API na internet com **HTTPS**, sem abrir porta e **sem depender da
operadora**:

```bash
# 1. habilitar o Funnel no tailnet (clique único, dono da conta):
#    https://login.tailscale.com/f/funnel?node=nutTa2mhy521CNTRL

# 2. publicar a 8000 (o CLI resolve o TLS sozinho):
tailscale funnel --bg --https=443 8000

# 3. conferir / desligar:
tailscale funnel status
tailscale funnel --bg off
```

Resultado: **`https://nicky-server.tail1b1f51.ts.net`** → `127.0.0.1:8000`.
No app, esse é o valor do campo **"URL externa (internet)"**.

Para o streaming (WS `:8001`) no mesmo host, o `serve` aceita caminho:

```bash
tailscale serve --bg --https=443 --set-path=/ws 8001
```

(o app passa a montar `wss://<host>/ws` quando a URL for `https://` sem porta).

Motivo da recomendação: sobrevive à troca de IP da operadora, não depende de
porta (nenhuma entrada passa hoje) e entrega TLS — melhor para o app do que
HTTP puro.

## Estado: Funnel publicado (2026-09-21)

A Opção A foi **executada e provada de fora**:

| Item | Valor |
|---|---|
| URL pública | **https://nicky-server.tail1b1f51.ts.net** |
| REST | `/` → `127.0.0.1:8000` (`tailscale funnel --bg --https=443 8000`) |
| Streaming | `/ws` → `127.0.0.1:8001` (`tailscale serve --bg --https=443 --set-path=/ws 8001`) |
| TLS | cert emitido via ACME dns-01 (journal `got cert` 10:06:23) |
| DNS público | `209.177.145.97` / `209.177.145.192` (ingress Tailscale; propagou ~4 min após publicar) |

Provas de fora:

- `/health` sem credencial → **401 `unauthorized` da nossa API** em 4/5 nós
  externos do check-host (Israel, Irã, Itália, Eslovênia; ingress
  `209.177.145.97`) — com `OD_API_AUTH_ALL=1`, o 401 é a prova de que a
  requisição chegou no od-core.
- `GET https://nicky-server.tail1b1f51.ts.net/ws` → **HTTP 426** com
  `server: Python/3.12 websockets/16.1.1` — o servidor WS do od-core responde
  pelo mesmo host (426 = handshake válido recusado sem `Upgrade`).

Notas de operação:

- `tailscale serve status` mostra `# Funnel on`; para desligar:
  `tailscale funnel --bg --https=443 off`.
- `serve` e `funnel` compartilham a 443 — o primeiro `serve --set-path`
  **derruba** o `funnel` da porta; republicar os dois resolve (estado final:
  `/` e `/ws` com `Funnel on`).
- No app, esta é a URL do campo **"URL externa (internet)"**; o streaming
  deriva `wss://host/ws` quando a URL é https sem porta (commit `57c4710`).
- `nicky.theworkpc.com` (porta 80) segue bloqueado pela operadora — dentro da
  LAN a primária continua sendo o Tailscale direto (`100.77.67.53:8000`).

## Opção B — pedir abertura à operadora (Algar/TCV)

Se quiser manter o domínio próprio (`nicky.theworkpc.com`) e o caminho sem
VPN, é com a operadora: planos residenciais brasileiros normalmente filtram a
entrada (80/443/25 e, neste caso, mais portas). Alternativas: pedir liberação
de portas / plano com IP público fixo, ou contratar um VPS e fazer túnel até
ele. Não há ajuste local que resolva.

## Opção C — IPv6 nativo (a testar, exige roteador)

Esta máquina tem **IPv6 global próprio** (`2804:428:3:6340:20f:ff:fe37:acf0`)
e a operadora não faz NAT nele. Se o firewall IPv6 do roteador permitir
entrada, o caminho externo vira AAAA + porta — **precisa de login no
roteador** para liberar e de AAAA no DNS; o prefixo é dinâmico (muda com RA),
o que exigiria atualização automática do registro.

## Como testar de fora (referência)

```bash
# dentro (hairpin — NÃO prova nada sobre a internet)
curl -s -o /dev/null -w "%{http_code}\n" http://nicky.theworkpc.com/health

# de fora: sonda com nós independentes (TCP)
#   https://check-host.net/check-tcp?host=<ip>:<porta>&max_nodes=4
#   -> depois https://check-host.net/check-result/<request_id>
# de fora: varredura de portas
curl -s -X POST https://portchecker.io/api/v1/query \
     -H 'Content-Type: application/json' \
     -d '{"host":"189.124.4.56","ports":[80,443,8000,8443]}'
```

## Segurança

- `OD_API_AUTH_ALL=1` (padrão): **todo** endpoint exige `X-API-Key`, sessão
  (`Authorization: Bearer`) ou API key de usuário — inclusive `/health`.
  Expor a 8000 na internet é o desenho previsto; o que **não** pode é expor sem
  chave (`OD_API_AUTH_ALL=0` só para uso local).
- O WebSocket (`:8001`) autentica por credencial desde 2026-09-21 (sessão ou
  API key) e, no Funnel, deve ir por `wss://` (caminho `/ws`).
