# OMEGA DRAKON — INTEGRAÇÃO GOOGLE (Drive · Agenda · Gmail)

> **Status:** código pronto, **dormente até a credencial do dono**.
> **Escopo atual:** SOMENTE LEITURA (decisão do dono em 2026-10-02 — "leitura
> primeiro"; a ESCRITA entra num 2º lote com gate de papel + confirmação).
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
`http://localhost:8766/`).

## 4. Autorizar (headless: colar a URL de retorno)

O servidor não tem navegador. O fluxo é "autorizar no navegador → colar a URL
de volta":

```bash
.venv/bin/python -m runtime.google_auth
```

1. o script imprime uma URL — abra no navegador (do PC ou celular) e autorize;
2. o Google redireciona para `http://localhost:8766/?code=...` (a página pode
   não abrir — normal);
3. copie a **URL inteira** da barra de endereço e cole de volta no terminal;
4. o token é salvo em `data/google_token.json` (permissão `0600`).

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
| `.../auth/drive.readonly` | listar/ler arquivos do Drive |
| `.../auth/calendar.readonly` | listar/ler eventos da Agenda |
| `.../auth/gmail.readonly` | listar/ler mensagens do Gmail |

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
| `redirect_uri_mismatch` | URI de redirecionamento divergente | mantenha `http://localhost:8766/` no Console e no config |
| Chat responde "ainda não configurado" | credencial/token ausentes ou od-core não reiniciado | passos 3–5 |
| Sem `refresh_token` | consentimento anterior sem `prompt=consent` | o script já força `access_type=offline` + `prompt=consent` |

---

**Arquivos:** `integrations/google/` (oauth, client, drive, calendar, gmail) +
`runtime/google_auth.py` (autorização) + `config/google_credentials.example.json`.
