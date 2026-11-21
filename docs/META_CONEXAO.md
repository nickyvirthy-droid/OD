# CONEXÃO COM A META — relatório técnico exato (21/11/2026)

Resposta ao pedido do dono no `txt.txt` (*"preciso preparar sua conexão com o
Meta AI"*), com o que está **no código e na configuração desta máquina** —
nada de suposição. No fim, o que já foi preparado e o que falta.

> **Fato primeiro:** a Meta não tem API pública para "conversar com o Meta AI"
> de fora. O caminho real de conexão é o **WhatsApp Business Cloud API**
> (Graph API). O que foi preparado é o lado do servidor desse webhook.

## 1. LINGUAGEM E FRAMEWORK

**LINGUAGEM:** Python **3.12.3** (venv em `.venv/`; `python3 --version`).

**FRAMEWORK:** **nenhum framework web** — servidor HTTP da biblioteca padrão:
`ThreadingHTTPServer` + `BaseHTTPRequestHandler`, com roteamento declarativo
próprio em `integrations/api/server.py` (`_ROUTE_SPECS` → `ROUTES`, 146 rotas).
Não há FastAPI, Flask nem Express instalados; o que existe é a cadeia de LLM,
memória e actions do OmegaDrakon por baixo.

## 2. PORTAS E ROTAS

**PORTA:** **8000** (`integrations/api/server.py`, `APIConfig.port = 8000`;
`OD_API_PORT` no `.env`). Escuta em `127.0.0.1:8000` e, pelo launcher,
`OD_API_HOST` (padrão `0.0.0.0`) — na LAN o site é `192.168.0.250:8000`.
**8470 é o Homebox**, outra ferramenta (container `od-homebox`), não o OD.

Rotas: **146** no total, todas em `integrations/api/server.py`. Quase todas
respondem **JSON** (`_json`); HTML em `/site`, `/chat`, `/dashboard`, `/admin`,
`/radio-pro`, `/registry*`; texto puro em `/metrics` e `/webhook/meta`.

| Método | Rota | Auth |
|---|---|---|
| `GET` | `/` | pública/portão no handler |
| `POST` | `/account/api-key` | chave |
| `POST` | `/account/password` | chave |
| `GET` | `/actions` | chave |
| `GET` | `/admin` | pública/portão no handler |
| `GET` | `/admin/auto-update` | chave |
| `POST` | `/admin/auto-update/dry-run` | chave |
| `POST` | `/admin/auto-update/reset` | chave |
| `POST` | `/admin/auto-update/rollback` | chave |
| `POST` | `/admin/cache/prune` | chave |
| `DELETE` | `/admin/dev/caixa` | chave |
| `GET` | `/admin/dev/caixa` | chave |
| `POST` | `/admin/dev/caixa` | chave |
| `GET` | `/admin/dev/sessao` | chave |
| `POST` | `/admin/dev/sessao` | chave |
| `GET` | `/admin/downloads` | chave |
| `POST` | `/admin/downloads` | chave |
| `GET` | `/admin/downloads/events` | chave |
| `DELETE` | `/admin/downloads/{job_id}` | chave |
| `GET` | `/admin/downloads/{job_id}` | chave |
| `POST` | `/admin/downloads/{job_id}/cancel` | chave |
| `GET` | `/admin/estado-ia` | chave |
| `GET` | `/admin/ferramentas` | chave |
| `POST` | `/admin/ferramentas` | chave |
| `GET` | `/admin/ferramentas/export` | chave |
| `GET` | `/admin/ferramentas/import` | chave |
| `POST` | `/admin/ferramentas/import` | chave |
| `DELETE` | `/admin/ferramentas/{id}` | chave |
| `PUT` | `/admin/ferramentas/{id}` | chave |
| `POST` | `/admin/ferramentas/{id}/rollback` | chave |
| `GET` | `/admin/google/apis` | pública/portão no handler |
| `GET` | `/admin/google/auth` | pública/portão no handler |
| `DELETE` | `/admin/ideias` | chave |
| `GET` | `/admin/ideias` | chave |
| `PUT` | `/admin/ideias` | chave |
| `DELETE` | `/admin/limitacoes` | chave |
| `GET` | `/admin/limitacoes` | chave |
| `POST` | `/admin/marketplace/atualizar/{id}` | chave |
| `GET` | `/admin/marketplace/catalogo` | chave |
| `GET` | `/admin/marketplace/catalogo/{id}` | chave |
| `GET` | `/admin/marketplace/categorias` | chave |
| `POST` | `/admin/marketplace/desinstalar/{id}` | chave |
| `GET` | `/admin/marketplace/instalados` | chave |
| `POST` | `/admin/marketplace/instalar/{id}` | chave |
| `POST` | `/admin/marketplace/publicar` | chave |
| `DELETE` | `/admin/marketplace/publicar/{id}` | chave |
| `GET` | `/admin/marketplace/reviews/media/{id}` | chave |
| `GET` | `/admin/marketplace/reviews/{id}` | chave |
| `POST` | `/admin/marketplace/reviews/{id}` | chave |
| `GET` | `/admin/marketplace/stats` | chave |
| `GET` | `/admin/marketplace/tags` | chave |
| `POST` | `/admin/os-updater/executar` | chave |
| `POST` | `/admin/os-updater/reboot` | chave |
| `GET` | `/admin/os-updater/status` | chave |
| `GET` | `/admin/registry` | chave |
| `POST` | `/admin/registry` | chave |
| `POST` | `/admin/registry/collections` | chave |
| `POST` | `/admin/registry/collections/{nome}/encerrar` | chave |
| `DELETE` | `/admin/registry/{public_id}` | chave |
| `PUT` | `/admin/registry/{public_id}` | chave |
| `DELETE` | `/admin/registry/{public_id}/chat/{msg_id}` | chave |
| `POST` | `/admin/registry/{public_id}/photo` | chave |
| `POST` | `/admin/registry/{public_id}/posse` | chave |
| `GET` | `/admin/registry/{public_id}/posse/qr` | chave |
| `GET` | `/admin/tasks` | chave |
| `POST` | `/admin/tasks` | chave |
| `GET` | `/admin/tasks/events` | chave |
| `DELETE` | `/admin/tasks/{task_id}` | chave |
| `GET` | `/admin/tasks/{task_id}` | chave |
| `POST` | `/admin/tasks/{task_id}/retry` | chave |
| `GET` | `/admin/users` | chave |
| `DELETE` | `/admin/users/{username}` | chave |
| `POST` | `/admin/users/{username}/password` | chave |
| `PUT` | `/admin/users/{username}/role` | chave |
| `GET` | `/admin/vigia` | chave |
| `POST` | `/admin/vigia/bloquear` | chave |
| `POST` | `/admin/vigia/conhecer` | chave |
| `POST` | `/anon/message` | pública/portão no handler |
| `GET` | `/api/radio/agora` | pública/portão no handler |
| `DELETE` | `/api/radio/cantores` | chave |
| `GET` | `/api/radio/cantores` | chave |
| `POST` | `/api/radio/cantores` | chave |
| `GET` | `/api/radio/musicas` | pública/portão no handler |
| `DELETE` | `/api/radio/musicas/bloqueadas` | pública/portão no handler |
| `POST` | `/api/radio/musicas/bloqueadas` | pública/portão no handler |
| `POST` | `/api/radio/musicas/decisao` | pública/portão no handler |
| `DELETE` | `/api/radio/musicas/excecoes` | pública/portão no handler |
| `POST` | `/api/radio/musicas/excecoes` | pública/portão no handler |
| `POST` | `/api/radio/musicas/excluir` | pública/portão no handler |
| `GET` | `/api/radio/pro/dados` | pública/portão no handler |
| `POST` | `/api/radio/pro/pedido` | pública/portão no handler |
| `GET` | `/api/radio/pro/traducao` | pública/portão no handler |
| `POST` | `/api/v1/chat/decision` | chave |
| `GET` | `/api/v1/chat/stream` | chave |
| `GET` | `/app/version` | pública/portão no handler |
| `POST` | `/auth/login` | pública/portão no handler |
| `POST` | `/auth/logout` | chave |
| `GET` | `/auth/me` | chave |
| `POST` | `/auth/register` | pública/portão no handler |
| `POST` | `/auth/session-cookie` | pública/portão no handler |
| `GET` | `/capabilities` | chave |
| `GET` | `/chat` | pública/portão no handler |
| `GET` | `/dashboard` | pública/portão no handler |
| `GET` | `/dashboard/stats` | chave |
| `POST` | `/executa` | chave |
| `DELETE` | `/f/(?P<nome>caderno|cyberchef|caixa|cofre)(?P<resto>/.*)?` | pública/portão no handler |
| `GET` | `/f/(?P<nome>caderno|cyberchef|caixa|cofre)(?P<resto>/.*)?` | pública/portão no handler |
| `POST` | `/f/(?P<nome>caderno|cyberchef|caixa|cofre)(?P<resto>/.*)?` | pública/portão no handler |
| `PUT` | `/f/(?P<nome>caderno|cyberchef|caixa|cofre)(?P<resto>/.*)?` | pública/portão no handler |
| `GET` | `/health` | pública/portão no handler |
| `DELETE` | `/history/{user_id}` | chave |
| `GET` | `/history/{user_id}` | chave |
| `DELETE` | `/history/{user_id}/messages/{message_id}` | chave |
| `GET` | `/history/{user_id}/stats` | chave |
| `GET` | `/llms` | chave |
| `GET` | `/memory/{user_id}/search` | chave |
| `POST` | `/message` | chave |
| `GET` | `/metrics` | pública/portão no handler |
| `GET` | `/presence/today` | pública/portão no handler |
| `GET` | `/profile/preferences` | chave |
| `PUT` | `/profile/preferences` | chave |
| `GET` | `/profiles` | pública/portão no handler |
| `GET` | `/profiles/{name}` | pública/portão no handler |
| `GET` | `/push/devices` | chave |
| `POST` | `/push/register` | chave |
| `POST` | `/push/test` | chave |
| `POST` | `/push/unregister` | chave |
| `GET` | `/radio-pro` | pública/portão no handler |
| `POST` | `/radio/webhook/{token}` | pública/portão no handler |
| `GET` | `/registry` | pública/portão no handler |
| `GET` | `/registry/collections` | pública/portão no handler |
| `POST` | `/registry/posse` | chave |
| `GET` | `/registry/{codigo}` | pública/portão no handler |
| `GET` | `/registry/{codigo}/chat` | pública/portão no handler |
| `POST` | `/registry/{codigo}/chat` | chave |
| `GET` | `/registry/{codigo}/photo` | pública/portão no handler |
| `GET` | `/site` | pública/portão no handler |
| `GET` | `/site/{file}` | pública/portão no handler |
| `GET` | `/supervision` | chave |
| `POST` | `/transcribe` | chave |
| `POST` | `/tts` | chave |
| `GET` | `/webhook/meta` | pública/portão no handler |
| `POST` | `/webhook/meta` | pública/portão no handler |
| `GET` | `/ws/chat` | chave |

## 3. AUTH

Hoje existem **três formas** de credencial, verificadas no dispatch
(`_check_api_key`) e nos handlers:

1. **`OD_API_KEY` do servidor** — header `X-API-Key` (é a chave do dono,
   ganha papel admin e assume `OD_OWNER_USERNAME`).
2. **Conta de usuário** — `POST /auth/register` + `POST /auth/login` devolvem
   `Authorization: Bearer <token>`; a sessão do navegador vira cookie
   `od_sessao` (httpOnly). API keys de usuário (`od_...`) também valem como
   `X-API-Key`.
3. **Portões por handler** — token no path (`/radio/webhook/{token}`) ou
   cookie de ouvinte (`/radio-pro`, `/f/*`).

`auth_all` está **ligado** em produção (`OD_API_AUTH_ALL=1`): qualquer rota
não listada abaixo exige credencial. **Rotas públicas hoje** (sem login):

`/anon/message`, `/api/radio/agora`, `/api/radio/musicas/bloqueadas`, `/api/radio/musicas/decisao`, `/api/radio/musicas/excecoes`, `/api/radio/musicas/excluir`, `/api/radio/musicas`, `/api/radio/pro/dados`, `/api/radio/pro/pedido`, `/api/radio/pro/traducao`, `/app/version`, `/auth/login`, `/auth/register`, `/auth/session-cookie`, `/f/(?P<nome>caderno|cyberchef|caixa|cofre)(?P<resto>/.*)?`, `/radio-pro`, `/radio/webhook/{token}`, `/registry/collections`, `/registry/{codigo}/chat`, `/registry/{codigo}/photo`, `/registry/{codigo}`, `/registry`, `/webhook/meta`

## 4. FUNNEL

O estado real (`tailscale funnel status`, 21/11):

```
https://nicky-server.tail1b1f51.ts.net (Funnel on)
|-- /          proxy http://127.0.0.1:8000
|-- /ws        proxy http://127.0.0.1:8001
|-- /radio.mp3 proxy http://127.0.0.1:8600/radio.mp3
```

O Funnel aponta para a **porta 8000** (o OD). As portas 8410/8420/8430/8466
etc. aparecem como *tailnet only* — não saem para a internet. O comando exato
usado para montar isso não está registrado no repositório; o que dá para
afirmar é o **estado acima**, que é o que o `tailscaled` serve agora.
**Consequência para a Meta:** o webhook precisa de URL pública HTTPS — hoje a
única pública é o Funnel na raiz; `/webhook/meta` já cai nela.

## 5. HOMEBOX

**Sim, leio o Homebox.** Por **API REST** (`integrations/homebox.py`),
`Authorization: Bearer <HBOX_API_KEY>`, base `OD_HOMEB_URL`
(`http://127.0.0.1:8470`, que é `192.168.0.205:8470` na LAN). A API usada é a
`/api/v1` (entities, entity-types, tags, status) — nada de escrever no banco
por fora.

**Banco:** SQLite do container em `/data/homebox.db`; no host, o diretório de
dados é `/home/alex/omegadrakon-tools/homebox/` → `homebox.db` (+ `-wal`,
`-shm`). O arquivo é root-owned e não é tocado pelo OD: leitura/escrita é
sempre pela API.

## 6. O QUE O SISTEMA CONSEGUE FAZER

**PODE_CRIAR_PING:** **Sim — criada em 21/11** (`GET /api/ping`, pública):
`{"status":"ok","sistema":"Omega Drakon","versao":"1.0"}`. Não toca banco nem
inventário; o agregado caro continua em `GET /health` (32 checks).

**PODE_CRIAR_INVENTARIO:** **Sim — criada em 21/11** como
`GET /api/public/inventario`, pública e **restrita por construção** a
`nome`, `local`, `categoria` e `quantidade` (método
`HomeboxClient.publico()`). Série, preço, notas, fabricante, garantia e ids
**não** saem; entidades de localização são filtradas. Homebox fora do ar →
503 `homebox_indisponivel` (nunca lista inventada).

## 7. O QUE JÁ FOI PREPARADO (21/11)

- **`integrations/meta.py`** — verificação do webhook (`hub.challenge`),
  assinatura `X-Hub-Signature-256` (HMAC-SHA256, fail-closed), leitura do
  payload (`messages[]` de texto/botão/interativo), divisão em 4096 caracteres
  e envio pelo Graph API.
- **Rotas** `GET /webhook/meta` (verificação) e `POST /webhook/meta`
  (mensagens → orquestrador → resposta), públicas por desenho, com portão no
  handler. Sem credencial: GET/POST respondem **503/403** — nada mais do
  sistema muda.
- **Launcher** monta o handler só quando as credenciais existem; a conversa
  usa `session_id = "meta:<wa_id>"` (histórico separado por número) e papel
  `admin` por padrão (`OD_META_ROLE`).
- **25 testes** em `tests/test_meta.py`, incluindo as rotas reais no servidor.

## 8. O QUE FALTA (lado do dono, no painel da Meta)

1. Criar o app em **developers.facebook.com** → produto **WhatsApp**.
2. Anotar **Phone number ID** e gerar um **token permanente** (system user).
3. Definir um **verify token** (qualquer segredo) e o **app secret**.
4. Preencher no `.env`:
   `OD_META_TOKEN`, `OD_META_PHONE_ID`, `OD_META_VERIFY_TOKEN`,
   `OD_META_APP_SECRET` (opcionais: `OD_META_GRAPH_VERSION`, `OD_META_PROFILE`,
   `OD_META_ROLE`).
5. No painel, configurar o webhook
   `https://nicky-server.tail1b1f51.ts.net/webhook/meta` com o mesmo verify
   token e assinar o campo **messages**.
6. Reiniciar o `od-core` e conferir o log `Webhook da Meta (WhatsApp) plugado`.

Sem esses passos o código fica dormente — por desenho.
