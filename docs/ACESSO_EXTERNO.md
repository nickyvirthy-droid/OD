# OmegaDrakon — acesso externo (internet)

> Diagnóstico de 2026-09-21. Objetivo: o app (e o site) funcionarem **fora** da
> LAN/Tailscale. Hoje só o Tailscale funciona.

## O que está configurado

| Elemento | Valor |
|---|---|
| Servidor | `192.168.0.250` (Wi-Fi), gateway `192.168.0.1` |
| Tailscale | `100.77.67.53` — `nicky-server.tail1b1f51.ts.net` |
| Domínio (Dynu DDNS) | `nicky.theworkpc.com` → **189.124.4.56** |
| API REST | `:8000` (TLS não; exige `X-API-Key` em tudo — `OD_API_AUTH_ALL=1`) |
| WebSocket | `:8001` |
| App Flutter | primária `http://100.77.67.53:8000`, externa `http://nicky.theworkpc.com` |

## Diagnóstico (o que as medições dizem)

Feito em 2026-09-21 com os serviços no ar:

| Teste | Origem | Resultado |
|---|---|---|
| `curl http://nicky.theworkpc.com/health` | **de dentro** da LAN | **401 em 0,31s** (chegou na API — hairpin NAT do roteador) |
| `dig +short nicky.theworkpc.com` | público | `189.124.4.56` = IP público **atual** (DDNS em dia) |
| HTTP do domínio | **de fora** (hackertarget, EUA) | **timeout** |
| HTTP do IP puro `189.124.4.56` (sem DNS) | **de fora** | **timeout** |
| Controle `http://example.com` no mesmo serviço | de fora | 200 + headers (o serviço funciona) |
| Caminho da rota (`tracepath`) | no servidor | `192.168.0.1` → `189.124.0.25` → internet: **não é CGNAT** |

**Conclusão:** o servidor responde, o DNS está certo e o IP é público — mas
**nada chega da internet na porta 80**. O timeout no IP puro elimina DNS e
descarta o próprio servidor. Causas prováveis, em ordem:

1. **bloqueio da porta 80 pela operadora** (comum em plano residencial); ou
2. **a regra de encaminhamento do roteador não está ativa** (ou aponta para
   outro IP interno — a máquina hoje é `.250`).

O `curl` de dentro da rede **não** prova acesso externo: o roteador devolve a
conexão internamente (hairpin NAT). Foi assim que a verificação de 09-19
concluiu "FUNCIONANDO" sem estar.

## Opção A — Tailscale Funnel (recomendada: não depende de roteador/operadora)

Publica a API na internet com **HTTPS** e sem abrir porta nenhuma:

```bash
# 1. habilitar o Funnel no tailnet (clique único, dono da conta):
#    https://login.tailscale.com/f/funnel?node=nutTa2mhy521CNTRL

# 2. publicar a 8000 (o CLI já resolve o TLS):
tailscale funnel --bg 8000

# 3. conferir / desligar:
tailscale funnel status
tailscale funnel --bg off
```

Resultado: **`https://nicky-server.tail1b1f51.ts.net`** → `127.0.0.1:8000`.
No app, esse é o valor do campo **"URL externa (internet)"**.

Por que é a melhor opção aqui: sobrevive à troca de IP da operadora, não
depende da porta 80 (que não está passando), e entrega TLS (a Play Store e as
operadoras tratam HTTPS melhor que HTTP puro na 80).

## Opção B — encaminhamento no roteador (porta alternativa)

Se preferir manter o domínio próprio:

1. No roteador (`192.168.0.1`): encaminhar **8443** (ou 8080) → `192.168.0.250:8000`.
2. Testar **de fora** (não vale testar de dentro!):
   `https://api.hackertarget.com/httpheaders/?q=http://nicky.theworkpc.com:8443/health`
   — a resposta esperada é o JSON de erro `401 unauthorized` da própria API.
3. No app: campo externo = `http://nicky.theworkpc.com:8443`.

Se o teste continuar em timeout, a operadora bloqueia entrada nessa porta
também e a Opção A é o caminho.

## Como testar de fora (referência)

```bash
# dentro (hairpin — NÃO prova nada sobre a internet)
curl -s -o /dev/null -w "%{http_code}\n" http://nicky.theworkpc.com/health
# de fora, via serviço público (controle: example.com responde headers)
# https://api.hackertarget.com/httpheaders/?q=http://<host>/health
```

## Segurança

- `OD_API_AUTH_ALL=1` (padrão): **todo** endpoint exige `X-API-Key`, sessão
  (`Authorization: Bearer`) ou API key de usuário — inclusive `/health`.
  Expor a 8000 na internet é o desenho previsto; o que **não** pode é expor sem
  chave (`OD_API_AUTH_ALL=0` só para uso local).
- O WebSocket (`:8001`) autentica por credencial desde 2026-09-21 (sessão ou
  API key), mas **não tem TLS**: para streaming externo, o Funnel só publica a
  8000. Streaming na internet hoje passa pelo Tailscale (que é cifrado).
