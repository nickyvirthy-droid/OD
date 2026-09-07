# OmegaDrakon — Acesso Externo via Tailscale 🔐

## Status: ✅ Ativo

## Configuração

| Aspecto | Detalhe |
|---|---|
| **IP Tailscale** | `100.77.67.53` |
| **Tailnet** | `nickyvirthy` |
| **Interface** | `tailscale0` |
| **Versão** | 1.102.2 |

## Como acessar

De qualquer dispositivo no mesmo tailnet (celular, outro PC):

```
http://100.77.67.53:8000
```

Todos os endpoints exigem `X-API-Key` (configurada no `.env`).

### Exemplos

```bash
# Health check
curl -H "X-API-Key: SUA_CHAVE" http://100.77.67.53:8000/health

# Enviar mensagem
curl -X POST http://100.77.67.53:8000/message \
  -H "Content-Type: application/json" \
  -H "X-API-Key: SUA_CHAVE" \
  -d '{"message": "Olá OD!"}'
```

## Segurança em camadas

1. **VPN (WireGuard)** — tráfego criptografado peer-to-peer
2. **X-API-Key** — autenticação em todos os endpoints
3. **UFW** — portas 22/8000/8123 apenas (nenhuma porta exposta à internet)
4. **Nada no roteador** — Tailscale faz NAT traversal automático

## Para dispositivos Android

1. Instalar Tailscale da Play Store
2. Entrar no mesmo tailnet (`nickyvirthy@`)
3. Acessar `http://100.77.67.53:8000` pelo app ou browser

## Notas

- O IP Tailscale pode mudar se o servidor for reiniciado (mas geralmente é estável)
- Para verificar o IP atual: `tailscale ip -4`
- Para verificar status: `tailscale status`
- Linger deve estar ativo para o OD rodar sem login: `sudo loginctl enable-linger alex`
