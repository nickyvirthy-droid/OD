# Conversa 2026-10-15 — OmegaDrakon

## §1 — Parte F do NOMAD (Supply Depot) ENTREGUE — v1.29.0 (manhã de 15/10)

Dono autorizou **"faça a parte F"** — última parte da ordem acordada
(A → C → B → D → E → **F**). **Ciclo completo do
`docs/ANALISE_PROJECT_NOMAD.md` encerrado** (linha 167: "Registro de
ferramentas/skills estilo Supply Depot — Pre-flight (conflito, versão,
tamanho), rollback, preservar customização — evoluindo o catálogo de
tools do orquestrador. Esforço médio.").

### O que foi feito

| Peça | Detalhe |
|---|---|
| `tools/supply_depot.py` (novo) | `preflight()` PURO (mesmas injeções do `avaliar()` da Parte E) em camadas: nome canônico válido (regra do auto-extension, nunca vira path) → tamanho do código (limite 8000 do `/gerar`) → disco (bytes × 1,1, margem da Parte E) → CONFLITO (`action_alheia`: no registry mas fora do depot) → VERSÃO semver (igual = `sem_acao`, menor = `downgrade_bloqueado`, major = só com `substituir=true`; versão-hash não tem major). Cada decisão com motivo. `SupplyDepot`: catálogo `data/ferramentas_catalogo.json` + códigos `data/ferramentas/` + backups `data/ferramentas_backup/`. |
| Instalação atômica + rollback automático | Fluxo `instalar()`: pré-voo → valida sintaxe/allowlist (gate do auto-extension, import lazy p/ evitar ciclo) → extrai a função → backup da versão atual (arquivo + snapshot na lista `anteriores`, máx. 5) → grava código/catálogo (tmp→`os.replace`) → troca a action no registry (unregister+register — `register()` do `ActionRegistry` respeita `allow_overwrite`). Falha em QUALQUER passo ⇒ `_rollback_memoria()` total (arquivo + catálogo + action de um snapshot em memória), resultado com `rollback=true`. |
| Rollback manual síndico | `depot.rollback()`: restaura arquivo + entrada + action da versão alvo (default = a anterior); a versão ATUAL entra no histórico junto ⇒ rollback **desfazível**; `backup_ausente`/`versao_nao_encontrada`/`sem_historico_de_versoes` com motivo. |
| Customização que sobrevive | `PUT /admin/ferramentas/{id}` → `depot.customizar()` grava sobrescritas (`descricao`/`params`/`permission`) em `custom` — reaplicadas no `_registrar` de CADA versão nova e presentes no snapshot de rollback. `ativa: false/true` = desinstalar/reativação não destrutivas (arquivo preservado no backup como `<id>.removido.v<versao>.py`). |
| `/gerar` com pré-voo + persistência | `AutoExtension.__init__` ganhou `depot` (kwarg) e `extend()` ganhou `substituir`: pré-voo **ANTES** do `generate_code` (conflito/downgrade/major → status honesto `conflict`/`blocked`/`exists` com **zero chamada de LLM** — antes: gerava, `register()` pulava em silêncio e o status era "ok"); no fim `depot.instalar()` persiste. Caminho legado intacto quando `depot=None` (os 17 testes antigos passam sem tocar). `substituir=True` → bump de patch (`proxima_versao()`) com histórico. `commands.py /gerar` renderiza `exists` ("já está instalada — substituir é pelo painel") e `conflict`/`blocked` ("pré-voo bloqueou"). |
| Boot restaura o catálogo | `build_supply_depot(action_registry, health)` no launcher (antes do `build_auto_extension`, caminhos absolutos via `DATA_DIR`): `carregar()` re-registra as ativas; código corrompido/inexistente = warn + `erros` (nunca derruba o boot); JSON ilegível = começa vazio. Health `supply_depot` não-crítico (`health_check(_monitor=None)` — lição da Parte E) detecta dessincronia (`fora_do_registry`). `OD_SUPPLY_DEPOT=0` desliga. |
| Rotas + painel + stats | `ROUTES` 73 → **78**: `GET/POST /admin/ferramentas`, `PUT/DELETE .../{id}`, `POST .../{id}/rollback` — admin; 201 instala / 200 atualiza-sem-acao / **409** pré-voo (o motivo vem no `error`) / 400 código rejeitado / 500 rollback / 404 / 503 `supply_depot_indisponivel`. Bloco `ferramentas` no `/dashboard/stats`. Seção **Ferramentas (Supply Depot)** no `/admin` (formulário nome+versão+descrição+código, tabela origem/tam/custom/histórico, botões ✎/⟲/✕; `frLoad` no `carregarTudo`; `node --check` verde). |
| Manifesto + capability | `data/ferramentas_catalogo.json` atômico com `_comentario`; capability `tool-supply-depot` (runtime, fase v1.29.x) no `/capabilities` (47). **versionCode** 2058 → 2059 (bump completo: `.env`, fallback `core/capabilities.py`, `pubspec 1.29.0+2059`, `_APP_VERSION_CODE`, site ×4; APKs reconstruídos e republicados — universal 55.508.376 B `c23ff4ee…`, arm64 20.043.570 B `837b0d68…`). |

### Verificação

- Suíte: **2863 passed / 16 skipped · gate 90,52%** (+91 testes em
  `tests/test_supply_depot.py`: tabela do pré-voo puro, instalação,
  rollback automático FORÇADO em cada passo (registro e gravação do
  catálogo), rollback manual/desfazível/specífico/backup-ausente,
  customização, remoção, boot com código corrompido + JSON ilegível,
  integração do `/gerar` contando chamadas do LLM fake — conflito com
  **NENHUMA** chamada — e as 5 rotas). `tools/supply_depot.py` a **95%**.
  Bug de teste achado pelo `pyflakes`/execução: `NickyLogger.info()`
  não aceita args posicionais de `%` (f-string corrigida).
- `flutter analyze` **0 issues** · `flutter test` **174/2** · política
  de versão **9/9** · `node --check` do JS do painel verde.

### Prova viva no serviço (3 fases; PIDs 2405509 → 2409472 → 2410050)

| Fase | Resultado |
|---|---|
| Boot (deploy) | `Supply Depot no ar (Parte F NOMAD) \| carregadas=0 \| erros=0 \| catalogo=0`; `/health` **up** com `supply_depot: up` ("supply-depot: 0 no catálogo"); `/capabilities` 47 com `tool-supply-depot`; `/app/version` **1.29.0 / 2059** sha == APK (`c23ff4ee…`) |
| Ciclo de vida (`proof.soma`) | instala **201** `instalar_nova (v1.0.0)` (sha `ec8306c0…`) → repetir **200** `sem_acao (ja_instalada)` → instalar por cima de `system_info` **409** `conflito: … não é do depot` → update `1.0.1` **200** + backup `proof.soma.v1.0.0.py` (116 B) → `PUT` descrição do dono **200** → update `1.0.2` com descrição **ainda** a do dono no `/actions` → major `2.0.0` **409** `major_requer_confirmacao (1.0.2 → 2.0.0)` → rollback **200** `de=1.0.2 para=1.0.1` (descrição do dono **ainda** lá) → `/executa {a:10,b:4}` → **`result: 6`** → `DELETE` **200**, catálogo/stats 0, arquivos preservados no backup |
| Persistência (prova central) | `proof.persist` instalado → restart → journal **`Supply Depot restaurado no boot \| carregadas=1 \| erros=0 \| catalogo=1`** (PID 2409472) → `/actions` ainda com a ferramenta → `/executa` → **"sobrevivi ao restart"** → `/health` "supply-depot: 1 no catálogo" |
| Painel ao vivo | Seção **Ferramentas (Supply Depot)** servida no `/admin` (2 ocorrências no HTML) |
| Restauração | `DELETE` + resíduos apagados (`data/ferramentas*`) → restart limpo (PID 2410050): boot `carregadas=0 \| erros=0 \| catalogo=0`, `/health` up, lista 0, journal **0 erros**, **NRestarts=0** |

### Canais e commits

- Commits `1d6cad4` (Parte F: código+testes+bump+docs) + `5b48460`
  (prova viva nos docs) — == origin/master.
- `txt.txt` reescrito (regra 14 — inclui a "ORDEM DO NOMAD COMPLETA"
  A→F e aponta a DECISÃO FINAL 12/10 como próximo candidato); Telegram
  msg **2742** (regra 15, chat OD_TELEGRAM_ADMINS).

### Estado

**CONCLUÍDO E NO AR — v1.29.0+2059 servindo (PID 2410050).** **Ordem
A → C → B → D → E → F completa** — as 6 partes do NOMAD entregues.
Próximo candidato na análise: a **DECISÃO FINAL (12/10)** — 8 ferramentas
de terceiro em Docker + ProtoMaps + LoRa (tabela da linha 178) — aguarda
ordem do dono. Pendências do dono inalteradas (Vaultwarden, Registro
Mestre etapa 4, pauta 3/5, rotação de segredos, fotos
`analise/fotos-adicionais/`, catálogo `3D/`).

## §2 — Retomada "leia iniciar" (~13:15) — sistema verde; TODO.md roadmap publicado entre sessões

Pedido do dono: **"leia iniciar"**. Verificação feita por evidência
lida no sistema (nada assumido):

### Achados

| Item | Estado |
|---|---|
| `od-core` | **active PID 2523683** desde 15/10 **13:08:55** (reinicio limpo — Stopping/Stopped/Started no mesmo segundo), **NRestarts=0**, journal **0 erros** |
| `/app/version` | **1.29.0 / 2059**, sha256 `c23ff4ee…` == APK publicado (55 508 376 B) |
| `/health` | **up** (orchestrator/llm/audit ok; RAG e Supply Depot no boot) |
| Boot do journal | `RAG … chunks 881` + `Supply Depot no ar (Parte F NOMAD) \| carregadas=0 \| erros=0` |
| Git | **HEAD `e45018e` == origin/master**, árvore **LIMPA** |
| `txt.txt` | **sem mensagem nova do dono** (última escrita nossa 11:09, entrega da Parte F) |
| `analise/` | **sem depósito novo** (`Avatar/` vazio; `fotos-adicionais/` com as mesmas 4 fotos) |

### Achado entre sessões: TODO.md + restart 13:08

- Commit **`e45018e` (13:10)** — `TODO.md` NOVO (163 linhas): roadmap
  organizado em 7 seções — stack Nômade (9 serviços no compose com
  status), DECISÃO FINAL 12/10 itemizado (8 containers ❌/⚠️/🟡 + LoRa
  🧊), pendências do dono, melhoramentos técnicos por parte (A–F),
  dívida técnica, parking lot e o **Definition of Done** copiado de
  `docs/REGRAS_DE_TRABALHO.md`. Fecho honesto: **não foi esta sessão
  quem criou** (o registro da Parte F em `iniciar/` fecha às 11:11);
  o artefato veio de trabalho entre 11:15–13:10 (mtime 13:00), está
  commitado, publicado e coerente com o sistema — **aceito como
  válido, registrado aqui**. O restart 13:08:55 foi verde (mesmo binário
  1.29.0+2059 no ar, NRestarts=0, journal 0 erros — docs não mudam
  runtime).
- Dono com SSH ativo (pts/0 192.168.0.111, desde 13:12) — é ele quem
  está no servidor agora.

### Estado

**SISTEMA ESTÁVEL — v1.29.0+2059 no ar (PID 2523683). Ordem A→F do
NOMAD completa.** Nada em andamento. Aguardando ordem do dono — os
candidatos estão no próprio `TODO.md` §7 (sugestão: DECISÃO FINAL,
começando pelo Vaultwarden). Pendências do dono inalteradas.

---

## §3 — Auditoria do TODO.md + §1 (Stack Nômade) executada: conta do dono no Vaultwarden, signups fechados, action consertada (~15:27→16:35)

Pedido do dono: **"verifique se realmente TODO esta correto e pode
começar pelo inicio, vou seguir a sua ordem sugerida"**. No caminho,
duas instruções novas: usar o **e-mail real do sistema**
(`nickyvirthy@gmail.com`) na conta, e **senhas que o sistema usar vão
no `.env`** (migradas ontem, commit `3ed13cc`).

### 1. Auditoria do TODO.md × sistema real

| Afirmação do TODO | Realidade medida | Veredito |
|---|---|---|
| §1: 9 serviços "☐" | 9 containers `Up` há 2–3 dias (`docker ps`, health) | ERRADO → ✅ |
| §1: Kiwix "ZIM precisa ser baixado" | `wikipedia_en_all_mini.zim` 14 386 799 064 B salvo 13/10 | ERRADO → baixado |
| §1: serve :8443 | 9 rotas respondendo (tailnet) | FUNCIONA |
| §1b: tabela com Paperless-ngx, Immich, Audiobookshelf, Portainer, exit node… | NENHUM desses existe na DECISÃO FINAL (`docs/ANALISE_PROJECT_NOMAD.md` §12/10) | INVENTADA → reescrita fiel |
| §1/§2: Vaultwarden pendente (signups abertos, 0 usuários) | confirmado (`/api/config disableUserRegistration: false`, db 0 users) | CORRETO → executado hoje |

Correções aplicadas no `TODO.md`: §1 9/9 ✅ com observações reais (ZIM
14,4 GB, DOMAIN corrigido, bugs registrados), §1b virou espelho da
DECISÃO FINAL (8 ferramentas ✅ no ar, ProtoMaps dev task, LoRa
geladeira, descartados: Kolibri/Jellyfin/Excalidraw/benchmark), §2
Vaultwarden ✅ + pendência nova do dono (repo público), §4 dívida
(bw ≥2026.9 vs servidor 1.36.0; repo público), §7 atualizado.

### 2. Cofre do dono — conta criada com o SDK oficial

Sem navegador desktop e com o `bw` CLI 2026.10 recusando o prelogin do
servidor 1.36.0 (espera `{kdfSettings, Salt}`; flag `pm-27060` fora do
allowlist `SUPPORTED_FEATURE_FLAGS`), o caminho foi o **SDK oficial
`@bitwarden/sdk-internal`** (mesmo WASM do web vault):

- Payload `RegisterData` completo: `key` (user key 64 B embrulhada com
  AES-256-CBC-HMAC via `encrypt_user_key_with_master_password`), `keys`
  (RSA-2048, PKCS8 embrulhado + SPKI b64), `masterPasswordHash`
  (PBKDF2-SHA256(material, senha, 1 it)), `kdf: 0` 600000.
- `POST /identity/accounts/register` → **HTTP 200 `{"object":"register"}`**
  (a rota antiga `/api/accounts/register` dava 404).
- Entraves de ambiente (ambos resolvidos e documentados): o WASM trava
  em **ESM** no Node 18 (CommonJS obrigatório) e paniqueia sem
  `globalThis.crypto` (que no Node 18 só existe em contexto `-e`;
  polyfill de `crypto.webcrypto` no script).

**Prova com cliente oficial** (`bw` 2026.8.0 — versão contemporânea do
servidor; ≥2026.9 não loga por incompatibilidade de prelogin):
login **OK** → `sync` **OK** → `create folder` + `list folders`
mostrou **"pasta-prova-omegadrakon" decifrada** (roundtrip completo de
criptografia) → remoção → `logout`. Depois do restart por fechar
signups: login do dono **OK** de novo.

### 3. Signups fechados de verdade

`SIGNUPS_ALLOWED=false` no compose → container recriado → env
aplicada conferida (`docker inspect`) → registro de fora → **HTTP 400**
"Registration not allowed or user already exists". Observação honesta:
`/api/config` continua mostrando `disableUserRegistration: False` — não
é bug: o Vaultwarden só esconde o link de cadastro quando
`(mail off + convites off)`; aqui mail está off e convites on
(concessão padrão do servidor). O fechamento real é o 400.

### 4. Action `nomad_vaultwarden_setup` consertada (antes: 3 defeitos + sucesso falso)

- Rota errada (`/api/accounts/register` → 404) e payload cru
  (`{email, masterPassword}`).
- Retorno **inventava um `token`** que o registro nunca devolve.
- `disable_signups=True` só imprimia "edite o compose e rode…" com
  `ok: True` — sucesso falso.

Nova versão: rota `/identity/accounts/register` + payload
`RegisterData` gerado por `_vw_register_payload` (HKDF-Expand RFC 5869,
EncString tipo `2.iv|data|mac` com PKCS7+HMAC, PBKDF2 600k, RSA-2048) e
fechamento **real** (edita compose → `compose up -d` → confere env →
`signups_nao_fecharam` se a env não chegou). Erros honestos
(`registro_recusado` com o HTTP do servidor, `etapa` no erro).

**Oráculo:** o payload Python foi validado contra o SDK oficial —
userKey desembrulhada ✓, pública == extração oficial da privada ✓,
auth hash == cálculo do SDK ✓. O oráculo **pegou um bug real** na 1ª
versão (argumentos do `pbkdf2_hmac` invertidos: senha/material) —
corrigido e reprovado 4/4.

**Drill E2E ao vivo:** reabertura temporária (~40 s, só
localhost+tailnet) → action rodada **sem mock**: criou
`drill@omegadrakon.dev`, editou o compose, recriou o container, conferiu
a env e fechou os signups → `bw` oficial logou na conta **gerada pela
Python** e decifrou pasta (roundtrip) → self-delete via
`/api/accounts/delete` (HTTP 200; exige jwt **antes** do logout — `bw
logout` revoga) → vault final = **só o dono**.

Backups do `db.sqlite3` em `/tmp/opencode/vw/` antes da criação e antes
do drill (contagem 0→1→2→1).

### 5. Verificação final (tudo evidência lida)

- compose `SIGNUPS_ALLOWED=false` · env do container false · container
  **healthy** · registro externo **400** · web vault pública
  `https://nicky-server.tail1b1f51.ts.net:8443` **200** · login do dono
  **OK** (e logout limpo) · db: **só `nickyvirthy@gmail.com`**.
- **Suíte completa: 2870 passed / 16 skipped** (+7 testes da action;
  módulo 48/48). Sem bump (backend/infra — convenção das entregas sem
  versão; CHANGELOG com entrada "sem bump").

### 6. Comunicação e pendências

- `txt.txt` reescrito com credenciais/URLs e **chmod 600** (regra 14).
- **Pendência de decisão do dono** (TODO §2 + txt.txt): repo GitHub
  **público** com histórico contendo segredos do compose (pré-`3ed13cc`)
  — privar? rotacionar? as duas?
- bw CLI ≥2026.9 incompatível com o prelogin do servidor 1.36.0
  (registrado na dívida técnica §4; web vault e app seguem OK).

### 7. Deploy da action corrigida (restart verde, regra 7.3)

Como `actions.py` vive em memória do od-core, o restart fazia parte do
deploy: `systemctl --user restart od-core` → **active PID novo
(16:30:47), NRestarts=0, journal 0 erros**. Provas no ar: `/health`
**up** (11 checks: audit/auto_update/database/homeassistant/llm/loops/
metrics/mqtt/orchestrator/perception/supply_depot), `/supervision`
degraded `[]` restarts 0, `/capabilities` **89 actions (nomad: 8)**
com `nomad_vaultwarden_setup` registrada, `/app/version` 1.29.0/2059
(sem bump — backend/infra), registro externo ainda **400**. Commit
`446246e` publicado (`3ed13cc..446246e`); Telegram msg **2756**.

## §4 — Retomada "leia iniciar" (~20:47) — sistema verde; 2 achados menores registrados

Pedido do dono: **"leia iniciar"**. Verificação por evidência lida
(nada assumido):

### Achados

| Item | Estado |
|---|---|
| `od-core` | **active PID 2707450** desde 15/10 **16:30:47** (deploy da §3), **NRestarts=0**, journal **0 erros** (grep `error\|exception\|traceback` = 0 desde o boot) |
| `/app/version` | **1.29.0 / 2059**, sha256 `c23ff4ee…` == APK publicado (55 508 376 B) |
| `/health` | 401 sem credencial = esperado (auth_all) |
| Git | **HEAD `3d94cbb` == origin/master**, árvore **LIMPA** |
| `txt.txt` | **sem mensagem nova do dono** (última escrita nossa 16:28 — entrega do Vaultwarden) |
| `analise/` | **sem depósito novo** (`Avatar/` vazio; `fotos-adicionais/` as mesmas 4 fotos) |

### Achados menores (registrados, sem ação agora)

- **Alertas `router:down`** (severity=warn) às 16:57, 18:57 e 19:57 —
  mas o ping ao gateway **192.168.0.1 agora responde 2/2** (rtt
  ~0,8 ms): falha intermitente de ping, **não** roteador fora.
  Monitorar; nenhum erro derivado no journal.
- **1 token de push morto**: dos 2 tokens em `data/push_devices.json`,
  o `d8Xhaf…` recebe **NOT_FOUND** do FCM a cada alerta (35 envios ok
  / 46 falhas acumuladas). Registro para poda futura (remover token
  NOT_FOUND do registry) — dívida técnica menor.
- Auto-update tick saudável: `alvos=1 | aplicar=0 |
  resumo=indice-rag=aguardar` (esperado).

### Estado

**SISTEMA ESTÁVEL — v1.29.0+2059 no ar (PID 2707450). Ordem A→F do
NOMAD completa; Vaultwarden fechado com conta do dono (§3).** Nada em
andamento. Aguardando ordem do dono — candidatos no `TODO.md` §7
(sugestão: DECISÃO FINAL / demais itens da stack Nômade). Pendências do
dono inalteradas (decisão sobre repo público, popular cofre, Registro
Mestre etapa 4, pauta 3/5, fotos `analise/fotos-adicionais/`, pasta
`3D/`).
