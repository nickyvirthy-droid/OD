# OMEGA DRAKON — INTEGRAÇÃO GOOGLE (Drive · Agenda · Gmail)

> **Status:** leitura NO AR (provada em 03/10) · escrita em implementação.
> **Escopo atual:** LOTE 1 = SOMENTE LEITURA (dono, 2026-10-02). LOTE 2 =
> **ESCRITA aprovada** (dono, 2026-10-03 — "escopo cheio: atende o txt.txt
> inteiro") com **gate de papel (admin) + confirmação de 2 passos**, mesmo
> padrão do controle do lar. Token novo com os 4 escopos abaixo.
> **Base técnica:** OAuth 2.0 + REST em **stdlib puro** (urllib) — sem
> `google-api-python-client`, sem novas dependências.
> **Assinatura:** `OD // CORE`

---

## 1. O que o dono ganha

Perguntas no chat (REST/WebSocket/Telegram) passam a ser respondidas com
**dados reais**, sem LLM inventando:

| Pergunta no chat | Action | O que devolve |
|---|---|---|
| "meus e-mails" / "ver meus emails" | `google_gmail_list` | últimas mensagens (assunto/remetente) |
| "minha agenda" / "meus compromissos" / "agenda de hoje" | `google_calendar_events` | próximos eventos |
| "meus arquivos no google drive" | `google_drive_list` | arquivos recentes do Drive |

Também via `/executa` (admin) e via API: `google_gmail_read`,
`google_drive_read`, `google_gmail_labels`.

Sem credencial configurada, a resposta é **honesta** ("ainda não está
configurado/autorizado") — o sistema **nunca** inventa e-mail, compromisso ou
arquivo.

## 2. Criar as credenciais (Google Cloud Console)

1. Acesse <https://console.cloud.google.com/> e crie (ou escolha) um projeto.
2. **Ative as APIs** (APIs & Services → Library): **Google Drive API**,
   **Google Calendar API** e **Gmail API**.
3. **Tela de consentimento** (OAuth consent screen): tipo **External** (conta
   pessoal) ou **Internal** (Workspace). Adicione o seu e-mail como *test
   user* se ficar em modo de teste.
4. **Credenciais → Criar credenciais → OAuth client ID → tipo
   "Aplicativo para computador" (Desktop app)**.
5. Baixe o JSON (será algo como `client_secret_....json`).

## 3. Instalar a credencial

Copie o JSON baixado para `config/google_credentials.json` (o arquivo é
**gitignored**):

```bash
cp ~/Downloads/client_secret_XXXX.json config/google_credentials.json
```

Se preferir o formato achatado, use `config/google_credentials.example.json`
como base (o campo `redirect_uris`/`redirect_uri` é opcional; o padrão é
`http://localhost:8766/`).## 4. Autorizar (headless: o servidor não tem navegador)

A autorização acontece no navegador de quem usa, e o código precisa voltar
ao servidor. Três rotas — **A e B não exigem copiar/colar nada**:

### Rota A — helper no PC (recomendada)

```bash
scp alex@192.168.0.250:OmegaDrakon/tools/google_oauth_helper.py .
python3 google_oauth_helper.py
```

O helper sobe `http://localhost:8766/` só na sua máquina, abre o navegador
já na página de consentimento e, quando o Google redirecionar, **captura o
código sozinho** e o envia ao servidor por SSH
(`~/OmegaDrakon/data/google_auth_url.txt`). Sem SSH ele deixa o arquivo
pronto — é só mandar por `scp`. Depois diga no chat que o código chegou.

### Rota B — túnel SSH

```bash
ssh -L 8766:127.0.0.1:8766 alex@192.168.0.250
```

Com a sessão aberta, use o botão de consentimento em
`/site/google_auth.html` (pública): o `localhost:8766` do navegador cai no
servidor pelo túnel e quem captura é o próprio servidor.

### Rota C — colar a URL (reserva)

```bash
.venv/bin/python -m runtime.google_auth
```

1. o script imprime uma URL — abra no navegador e autorize;
2. o Google redireciona para `http://localhost:8766/?code=...` (a página pode
   não abrir — normal);
3. copie a **URL inteira** da barra de endereço e cole de volta no terminal
   (`--code "<url>"` em modo não interativo);
4. em qualquer rota o token é salvo em `data/google_token.json` (`0600`).

Conferir o estado a qualquer momento:

```bash
.venv/bin/python -m runtime.google_auth --check
```

## 5. Ligar no sistema

Reinicie o `od-core` (o launcher injeta o cliente Google nas actions):

```bash
systemctl --user restart od-core
```

Sem credencial, nada quebra: as actions `google_*` apenas degradam.

## 6. Escopos pedidos

| Escopo | Para quê |
|---|---|
| `.../auth/drive` | listar/ler **e criar/editar/apagar** arquivos do Drive (⊃ o antigo `drive.readonly`) |
| `.../auth/calendar.events` | listar/ler **e criar/apagar** eventos da Agenda (⊃ o antigo `calendar.readonly` para eventos) |
| `.../auth/gmail.modify` | listar/ler **e apagar (lixeira)** mensagens do Gmail (⊃ o antigo `gmail.readonly`) |
| `.../auth/gmail.send` | enviar e-mails do Gmail |

> Lote 1 (02/10) usava os três `*.readonly`. Em 03/10 o dono aprovou o
> escopo cheio — a autorização precisa ser FEITA DE NOVO com os escopos
> novos (`include_granted_scopes=true` preserva o já concedido).

Para revogar o acesso a qualquer momento:
<https://myaccount.google.com/permissions>.

## 7. Segurança e papéis

- **Admin (dono):** acesso pleno às actions `google_*`.
- **User:** acesso de **leitura** (decisão explícita do dono, 2026-10-02) —
  veja `core/security/permissions.py`.
- **Token:** gravado em `data/google_token.json` com `0600`; nunca é logado
  nem devolvido em resposta. O token **não** mora no `.env`.
- Segredos continuam vedados no chat (pergunta de senha → negação
  determinística).

## 8. Escrita (2º lote — ainda não implementado)

Criar/editar/apagar arquivos do Drive, criar/apagar eventos e enviar/apagar
e-mails **não existem** ainda. Quando entrarem, usam o mesmo desenho do
controle do lar: gate de papel (admin) + **confirmação de 2 passos**.

## 9. Problemas comuns

| Sintoma | Causa provável | Ação |
|---|---|---|
| `autorização recusada (access_denied)` | conta não autorizada / consentimento negado | refaça o passo 4 e aceite os escopos |
| `invalid_grant` na renovação | token revogado/expirado ou sem refresh | rode o passo 4 de novo (`prompt=consent`) |
| `redirect_uri_mismatch` | o que foi pedido não bate com o que o servidor troca | o valor que vale é o `redirect_uri` de `config/google_credentials.json` (padrão `http://localhost:8766/`) — troque os dois juntos ou nenhum |
| o navegador abre e nada chega | porta 8766 ocupada no seu PC, ou você autorizou de outra máquina | feche quem estiver na porta, ou use a rota B (túnel) |
| Chat responde "ainda não configurado" | credencial/token ausentes ou od-core não reiniciado | passos 3–5 |
| Sem `refresh_token` | consentimento anterior sem `prompt=consent` | o script já força `access_type=offline` + `prompt=consent` |

---**Arquivos:** `integrations/google/` (oauth, client, drive, calendar, gmail) + `runtime/google_auth.py` (autorização) + `tools/google_oauth_helper.py` (captura no PC, sem copiar) + `site/google_auth.html` (botão público) + `config/google_credentials.example.json`.
