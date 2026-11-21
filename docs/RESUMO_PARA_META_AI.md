# OMEGA DRAKON — resumo para colar no Meta AI

> **Para que serve:** dar ao Meta AI o estado real do projeto antes de pedir
> ideias, para ele não inventar capacidades, arquivos ou pendências.
> **Gerado em:** 21/11/2026, a partir de `docs/ANALISE_SISTEMA_TODO.md`,
> `docs/README_VERSAO.md`, `docs/ARCHITECTURE_v2.md`, `docs/CHANGELOG.md`,
> `docs/META_CONEXAO.md`, `docs/QUEDA_DE_ENERGIA.md` e `iniciar/session.json`.
> **Números conferidos no código/serviço em 21/11/2026** (146 rotas, 132
> actions, 32 checks, 9 itens/10 locais no Homebox). Contagens mudam com o
> tempo: se um número divergir do código, o código vence.
> **Não é fonte primária:** é um índice + resumo. O canônico continua nos
> arquivos apontados no fim.

## 1. O que é o Omega Drakon

Sistema pessoal do Alex Projeti ("dono"), rodando **localmente** num Dell
OptiPlex 3040 (`nicky-server`, Ubuntu, 6.8.0), em `/home/alex/OmegaDrakon`
(branch `master`). Não é SaaS: o processo local é quem responde, e o LLM
padrão da persona é local (`od-llm.service`, llama-server em 127.0.0.1:8081,
qwen2.5-coder-3b). Há providers online com chave (Gemini e Groq válidos;
OpenAI **sem créditos**), usados como fallback — nuvem não é garantia.

- **Versão atual:** 1.46.1 (19/11/2026).
- **Núcleo:** Python (stdlib na maior parte), `core/orchestrator.py`,
  `core/intents.py`, `tools/actions/actions.py` com **132 actions**,
  memória de conversa em SQLite e camada de banco/actions em PostgreSQL
  local (`OD_DB_URL`), orquestração multi-IA.
- **API REST:** `integrations/api/server.py`, porta 8000, **146 rotas**.
  Health agregado em `GET /health` (32 checks, medido em 21/11).
- **Interfaces:** app Flutter (`app/`), site (`site/`), painel (`site_admin/`),
  bots de Telegram (chat, usuários, monitor) e rádio (`/radio.mp3`, porta 8600).
- **Acesso externo:** Tailscale Funnel `https://nicky-server.tail1b1f51.ts.net`
  → 8000; `/ws` → 8001; `/radio.mp3` → 8600. Fora isso, LAN `192.168.0.x`.
- **Integrações vivas:** Homebox (inventário: 9 itens, 10 locais, 15 tags),
  Google (Drive/Agenda/Gmail, leitura), Firebase (push do app), Meta/WhatsApp
  (preparado, **sem credenciais no `.env`**), rádio e acervo musical.
- **Serviço:** unidade de usuário `od-core.service` (`systemctl --user`),
  modo `all`, com auto-registro de cada restart em `iniciar/session.json`.
- **Containers auxiliares:** Homebox, Home Assistant, Kiwix, Stirling PDF,
  FileBrowser, Vaultwarden, AzuraCast etc. rodam em Docker, mas o núcleo do
  OD (API, orquestrador, bots) **não** roda em container.

## 2. Como o trabalho é validado (regras que não podem ser afrouxadas)

- Gate completo `python3 -m pytest -q` **verde antes de commit/push**.
  Em 21/11: **5621 passed, 19 skipped** (~4 min).
- Commit em `master`, push antes de reiniciar o serviço; restart só depois.
- Não se remove/afrouxa teste para "passar": corrige-se a causa.
- Toda entrega atualiza `docs/CHANGELOG.md`, `docs/README_VERSAO.md` (versão),
  `iniciar/session.json`, `iniciar/ATRIBUICOES.md` e a transcrição do dia.
- Versão segue SemVer (`docs/VERSIONAMENTO.md`); a mais recente é 1.46.1.

## 3. O que já funciona (não invente que falta)

- Orquestrador com providers plugáveis, fallback entre LLMs locais/remotos,
  intenções em pt-BR, **132 actions** e registro de ferramentas.
- Memória de conversa (SQLite), identidade/contas, permissões e painel admin.
- Saúde e observabilidade: `/health` (32 checks), telemetria (traces/métricas,
  `core/telemetry.py`), notificador proativo no Telegram (restart, LLM
  offline, disco, rede, crash loops), vigia de rede e auto-update com janela.
- Inventário Homebox (9 itens, 10 locais) e duas rotas públicas novas:
  `GET /api/ping` e `GET /api/public/inventario` (só nome, local, categoria,
  quantidade — sem série/preço).
- Rádio própria com curadoria, quarentena e reprovadas, painel `/radio-pro`.
- App Flutter com push, painel, decisões da rádio e Vigia da Rede
  (`flutter test` 264 passed em 19/11).
- Backup do Postgres com **restauração provada** em 19/11 (14 tabelas,
  589 linhas, 0,17 s); snapshot/off-site por Telegram.

## 4. O que está quebrado ou pendente (estado honesto)

1. **AC Recovery do BIOS não configurado.** O servidor não religa sozinho
   após queda de energia. Não é programável por software neste OptiPlex 3040
   (sem WMI-ACPI; `dell-wmi-sysman` recusa o hardware). Precisa de alguém na
   máquina: F2 → Power Management → AC Recovery → Power On. O aviso de boot
   no Telegram já distingue queda de restart comum (`docs/QUEDA_DE_ENERGIA.md`).
2. **Conexão Meta/WhatsApp sem credenciais.** O código está pronto
   (`integrations/meta.py`, `GET/POST /webhook/meta`), mas faltam
   `OD_META_TOKEN`, `OD_META_PHONE_ID`, `OD_META_VERIFY_TOKEN` e
   `OD_META_APP_SECRET` no `.env`; sem isso as rotas respondem 503/403.
3. **Bluetooth:** o celular emparelha, mas a autenticação falha (`PIN 0000`,
   `AuthenticationFailed` no agent D-Bus). Pendente de novo teste com
   `bluetoothctl --agent`.
4. **Backup off-site físico** ainda não existe; o restore do dump foi provado,
   mas só na mesma máquina.
5. **Ideias do dono ainda não implementadas** (`docs/ANALISE_SISTEMA_TODO.md`
   §9): foto da peça no APK → identificar → cadastrar no Homebox; abrir o
   Homebox pelo site; pré-escuta de músicas em quarentena no `/radio-pro`.
6. **Aviso:** a lista pública do inventário está aberta na internet pelo
   Funnel (só os quatro campos públicos). É uma decisão consciente, mas é
   superfície pública.

## 5. O que o Meta AI NÃO deve supor

- Não há Kubernetes, microsserviços, fila externa nem banco gerenciado. Há
  containers Docker auxiliares (Homebox, Home Assistant, Kiwix, Stirling
  PDF etc.), mas o núcleo do OD não roda neles.
- Não presuma que o chat depende de OpenAI: a chave está **sem créditos**.
  O LLM padrão é local (llama-server, qwen2.5-coder-3b); Gemini e Groq são
  fallback com chave válida.
- Não diga que o catálogo tem 56 actions: são **132** (o número 56 é do
  legado NV, citado em `ACTIONS_CORRESPONDENCIA.md`).
- Não há (ainda) WhatsApp/Meta ativo: só o webhook preparado e sem
  `OD_META_*` no `.env`.
- Não há acesso remoto ao BIOS, iDRAC ou console fora do Tailscale.
- Não existe um único arquivo que contenha "tudo": o estado é dividido entre
  código, `iniciar/session.json`, CHANGELOG e README_VERSAO (ver §6).
- Não proponha reescrita big-bang: a regra é entrega incremental com gate.

## 6. Índice dos documentos (o que ler para cada assunto)

| Arquivo | Última atualização | O que contém |
|---|---|---|
| `docs/ANALISE_SISTEMA_TODO.md` | 21/11/2026 | Análise + TODO priorizado; §9 tem as ideias do dono. **Melhor retrato de pendências.** |
| `docs/README_VERSAO.md` | 19/11/2026 | Relatório de cada versão entregue; topo = 1.46.1. |
| `docs/CHANGELOG.md` | 21/11/2026 | Histórico cronológico de todas as mudanças. |
| `docs/ARCHITECTURE_v2.md` | 14/11/2026 | Arquitetura alvo e estado após 10-13/11. |
| `docs/META_CONEXAO.md` | 21/11/2026 | Relatório técnico da conexão Meta (rotas, auth, portas). |
| `docs/QUEDA_DE_ENERGIA.md` | 21/11/2026 | AC Recovery (passo físico) e aviso de boot. |
| `docs/PROTOCOLO_MULTI_IA.md` | 18/11/2026 | Regras para várias IAs no mesmo repositório. |
| `docs/REGRAS_DE_TRABALHO.md` | 04/09/2026 | Definition of Done e working agreement. |
| `docs/CAPACIDADES.md` | 11/09/2026 | Capacidades (fonte: `core/capabilities.py`). |
| `docs/IAS_DISPONIVEIS.md` | 19/11/2026 | Inventário medido das IAs da máquina. |
| `docs/LEGADO_CONSOLIDADO.md` | 09/11/2026 | Bússola para o Legado (história/identidade). |
| `docs/OMEGADRAKON_SPEC.md` | 02/09/2026 | Especificação oficial 1.0.0 (base histórica). |
| `docs/ROADMAP_V1.md` / `docs/ROADMAP_ABSORCAO.md` | 09/2026 | Planos antigos; não são estado atual. |

### Resposta curta: qual colar no Meta AI?

**Este arquivo** (`docs/RESUMO_PARA_META_AI.md`). Se precisar de mais
profundidade, cole junto `docs/ANALISE_SISTEMA_TODO.md` §1, §2 e §9 e o topo
de `docs/README_VERSAO.md` (versão 1.46.1). Não há um "arquivo único da
verdade" anterior a este; `iniciar/session.json` é o estado operacional vivo,
mas não é documentação para leitura externa.
