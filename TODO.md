# TODO — OmegaDrakon (próximas atualizações)

> **Regra:** este arquivo é o **canal do dono** (regra 14) — editável pelo painel `/admin` e pelo app. Não perca nada durante a caminhada.

---

## 1. Stack Nômade Atual (`docker/tools-compose.yaml`) — 8 serviços **no ar** (auditado 17/10)

| # | Serviço | Container | Porta local | Status | Observação |
|---|---|---|---|---|---|
| 1 | **Kiwix** (Wikipedia offline) | `od-kiwix` | 8090 | ✅ | ZIM `wikipedia_en_all_mini` (14,4 GB) **já baixado em 13/10** |
| 2 | **CyberChef** (data tools) | `od-cyberchef` | 8100 | ✅ | ~300 operações (base64, hash, cifra) |
| 3 | **IT Tools** (dev utils) | `od-it-tools` | 8430 | ✅ | UUID, hash, formatadores |
| 4 | **FlatNotes** (caderno MD) | `od-flatnotes` | 8200 | ✅ | auth=none (só Tailscale); API p/ actions "anota"/"o que anotei" |
| 5 | **Stirling PDF** (50+ PDF tools) | `od-stirling-pdf` | 8400 | ✅ | **INTERLIGADA em 17/10 (v1.36.0, 2ª da fila)** — o sistema opera a API v1 (s-pdf 2.13.1, só localhost) pelas actions `stirling_status/stirling_merge/stirling_split/stirling_compress` (categoria `stirling`, só admin); JAVA_TOOL_OPTIONS fix metaspace |
| 6 | **File Browser** (arquivos web) | `od-filebrowser` | 8410 | ✅ | login admin/admin → trocar |
| 7 | **Calibre Web** (e-books) | `od-calibre-web` | 8420 | ✅ | login admin/admin123 → trocar; books em `/home/alex/omegadrakon-tools/books` |
| 8 | **Homebox** (inventário/QR) | `od-homebox` | 8470 | ✅ **NO AR e INTERLIGADO desde 17/10 (v1.38.0)** | **4ª e última da fila, com uso definido pelo dono** (*"cadastrar as ferramentas e peças que possuo... sugerir montagens"*): 6 actions `homebox_*` (categoria `homebox`, só admin) — o sistema CONSULTA e CADASTRA (nenhuma ação apaga). Conta do sistema + API key no `.env` **e no cofre** (14/14). **Já populado com as 2 peças reais do dono: Raspberry Pi 4 + ESP-01S com DHT22** (tipos e tags criados e declarados). Dados: `omegadrakon-tools/homebox` (banco do desligamento preservado) |
| 9 | **Vaultwarden** (cofre senhas) | `od-vaultwarden` | 8480 | ✅ | HTTPS via Tailscale Serve; **conta do dono criada 15/10**; **conta de SERVIÇO do sistema** `od-sistema@omegadrakon.dev` criada 17/10 e **interligada** (actions `vault_*`, v1.35.0 — o sistema lê/escreve no cofre; a conta do dono nunca é usada); **as 12 senhas do `.env` espelhadas no cofre em 17/10** (`vault_env_mirror.py`, cópia idempotente — `.env` segue como bootstrap do boot); `SIGNUPS_ALLOWED=false` |

> **Situação (15/10):** os 9 sobem com `up -d` e estão no ar. **Pendência do §1 concluída:** conta do dono + signups fechados — comprovado por drill E2E (conta de teste criada pela action, logada e decifrada pelo CLI oficial, depois excluída; vault só com o dono).
> **Situação (17/10):** decisão do dono sobre as 9 — **Homebox tirado do ar** (vazio, função única; compose comentado + imagem removida, nada apagado) e **FlatNotes/File Browser/Calibre ficam** para análise a fundo, uma por vez (§5). Stack agora = 8 no ar. Critério do dono: *"ferramenta só interessa se o sistema puder usar"* — as 3 primeiras (Vaultwarden, Stirling PDF, Kiwix) continuam e serão interligadas ao sistema, nessa ordem.
> **Situação (17/10, tarde — v1.36.0):** fila em andamento — **Vaultwarden ✅ (1ª, v1.35.0) e Stirling PDF ✅ (2ª, v1.36.0) INTERLIGADAS**; **Kiwix é a próxima (3ª)**; Homebox volta na sequência com uso definido (decisão do dono). Além disso, **todas as 12 senhas do `.env` estão espelhadas no cofre** (`vault_env_mirror.py` — pedido do dono *"coloque todas as senhas do .env no cofre"*; é cópia, não remoção: `.env` continua o bootstrap).
> **Bugs corrigidos em 15/10:** `DOMAIN` do Vaultwarden (commit `3ed13cc` — API anunciava URL errada); action `nomad_vaultwarden_setup` estava quebrada (rota `/api/accounts/register` = 404 + payload cru + "fechar signups" só imprimia instrução) → corrigida: rota `/identity/accounts/register`, payload `RegisterData` com crypto oficial (PBKDF2 600k + AES-CBC-HMAC + RSA-2048, validada 100% contra o SDK Bitwarden) e fechamento real (edita compose → recria container → confere env).

---

## 1b. DECISÃO FINAL (12/10) — espelho fiel de `docs/ANALISE_PROJECT_NOMAD.md` (corrigido 15/10)

> A versão anterior desta seção listava itens que **não existem** na DECISÃO FINAL
> (Paperless-ngx, Immich, Audiobookshelf, Portainer, exit node…). A tabela abaixo
> reproduz a fonte da verdade (ANALISE § DECISÃO FINAL 12/10).

| Item | Decisão | Status hoje |
|---|---|---|
| **8 ferramentas** (Kiwix, Stirling PDF, CyberChef, IT Tools, Vaultwarden, FlatNotes, File Browser + Calibre Web, Homebox) | ✅ ENTRA como containers | **Concluído** — 8 containers no ar (§1; Homebox fora desde 17/10 por decisão do dono) |
| **ProtoMaps** | 🛠️ DEV TASK (página MapLibre + tiles, não container) | Pendente (quando o dono quiser mapa próprio) |
| **LoRa** | ❄️ GELADEIRA | Aguarda hardware/necessidade real |
| **Kolibri, Jellyfin, Excalidraw, benchmark/leaderboard** | ❌ DESCARTADOS de vez | Confirmado no dono (12/10) |

> **Conclusão:** o stack **já está completo e no ar** (9 serviços) e
> **monitorado pelo od-core** (15/10, ~21:15): as 9 entram no `/health`
> (`tool_kiwix` … `tool_vaultwarden`, não-críticas) e uma ferramenta
> fora por 120s+ vira **alerta no Telegram** — o que faltava do "próximo
> passo" da própria DECISÃO FINAL. Sobra só a página **ProtoMaps**
> (dev task, opcional — quando o dono quiser mapa próprio). LoRa segue
> na geladeira.

---

## 2. Pendências do dono (não mexidas — são suas)

| Item | Status | Observação |
|---|---|---|
| **Vaultwarden** | ✅ | Conta do dono criada + registro aberto fechado em 15/10 (E2E com CLI oficial). O cofre já tem **as 12 senhas do `.env` espelhadas** (17/10, `vault_env_mirror.py` — cópia idempotente, sem tocar no `.env`); falta o dono popular com as **pessoais**: `https://nicky-server.tail1b1f51.ts.net:8443` |
| **Registro Mestre — Etapa 4** | ☐ | Comprador / QR / loja do lote de brinquedos |
| **Pauta §8.5 — Rotação dos segredos vazados no Legado** (09/10) | ☐ | Verificado 09/10: **bot antigo `@Nexus_Nicky_bot` e chave Gemini AINDA ATIVOS**. Decisão do dono: rotacionar só quando os testes em produção finalizarem. Nunca migrar segredo ao site (fonte: §6 linha 15 + §8 item 5 — mesmo assunto da linha "Rotação de segredos" abaixo) |
| **Repo GitHub público + segredos no histórico** | ☐ | **Decisão do dono:** tornar o repo privado e/ou rotacionar segredos que apareceram no histórico antes do commit `3ed13cc` (migração p/ `.env`) — detalhes no `txt.txt` |
| **Rotação de segredos** | ☐ | Adiada — verificado: sem segredo antigo vivo fora do `.env` (exceto histórico git público, pendência acima) |
| **Fotos em `analise/fotos-adicionais/`** | ☐ | "Vou usar depois" (4 fotos com prefixo `zz`/`zzz`) |
| **Catálogo `3D/`** | ☐ | Pasta para catalogar modelos 3D |

---

## 3. Melhoramentos técnicos (surgiram nas entregas A→F)

### 3.1 Supply Depot (Parte F) — recém-entregue
- [ ] **Mais ferramentas nativas no depot** — popular `data/ferramentas/` com utilitários úteis (ex.: `filesystem.ls`, `system.uptime`, `network.ping`, `json.query`)
- [ ] **Importação/exportação de catálogo** — `GET/POST /admin/ferramentas/import` para backup/restaurar o catálogo inteiro (JSON)
- [ ] **Versionamento semântico estrito no `/gerar`** — hoje `substituir=True` dá bump de patch; permitir `major/minor/patch` explícito no body
- [ ] **Política de retenção de backups configurável** — hoje fixo em 5; expor via `OD_SUPPLY_DEPOT_MAX_HISTORY`
- [ ] **Diff visual no painel** — ao editar/atualizar, mostrar diff do código anterior vs novo (estilo GitHub)
- [ ] **Assinatura de código** — SHA256 no manifesto já existe; adicionar assinatura Ed25519 do dono para ferramentas "oficiais"

### 3.2 Auto-update (Parte E)
- [ ] **Mais alvos no manifesto** — hoje só `indice-rag`; adicionar modelos/vozes quando o dono pinar no `data/auto_update_alvos.json`
- [ ] **Notificação no Telegram** — quando um alvo for aplicado/auto-desligado, mandar msg pro dono (chat `OD_TELEGRAM_ADMINS`)
- [ ] **Rollback de modelo** — se um modelo novo quebrar, botão "voltar versão anterior" no painel (usa a fila da Parte D para baixar o anterior)
- [x] **Métricas Prometheus** — exportar `auto_update_tick_total`, `auto_update_aplicado_total`, `auto_update_falha_total` — **ENTREGUE 16/10 (sem bump; CHANGELOG §Observabilidade):** `MetricasAutoUpdate` em `core/auto_update.py` contada **onde o fato acontece** (ticks/dry-run, decisões aplicar/aguardar/pular, `aplicados` que CONCLUÍRAM, falhas DURAS, auto-desligado na **transição**, rag_syncs, downloads novos, dedups, erros contidos) e `prometheus_lines()` no text exposition format. Nomes com **prefixo `od_`** (a convenção de TODA métrica do coletor: `od_processed_total`, `od_audit_total`, `od_api_requests_total`) ⇒ `od_auto_update_tick_total` = o `auto_update_tick_total` pedido aqui, idem aplicado/falha. Contadores **desde o boot** (o Prometheus compensa com `rate()`); gauges do estado **persistido** (`alvo`, `alvo_desabilitado`, `download_pendente`) e `ultimo_tick_segundos` — que **não** é inventado como 0 antes do primeiro ciclo. `ligar_metricas_auto_update()` no launcher liga a fonte viva **depois** do `build_metrics` (o health depende do coletor), best-effort. Os MESMOS números aparecem no bloco `auto_update` do `/dashboard/stats`, no `/admin/auto-update` e no card do painel. **Decisão registrada:** sem `skip_total` — nenhum caminho usa `dura=False` hoje, e métrica que nunca sai de zero confunde. +11 testes (**3057/16 · 90,86%**; `core/auto_update.py` 95%, todo o código novo coberto), mutação **6/6** e prova viva no `/metrics` do serviço (PID 3935938: `tick_total 1`, `decisao{decisao="aguardar"} 1` batendo com o tick do journal, zero regressão nas 42 linhas do scrape).

### 3.3 Fila de downloads (Parte D)
- [ ] **Limpeza automática de `.part` órfãos** — job diário que remove parciais > 24h sem dono
- [ ] **Prioridade de jobs** — `priority` no body do POST `/admin/downloads` (baixa/normal/alta)
- [ ] **Webhook de conclusão** — opcional `callback_url` no job para notificar sistemas externos

### 3.4 RAG / Pipeline de qualidade (Parte B)
- [ ] **Embedding melhor** — hoje `all-MiniLM-L6-v2`; testar `bge-m3` ou `e5-large` para melhor recall
- [ ] **Corpus externo** — hoje só `docs/` + `knowledge/` internos; adicionar fontes externas (GitHub, Notion, Obsidian via sync)
- [ ] **Hybrid search nativo** — hoje floor duplo (cosseno + overlap-IDF); testar BM25 + vetor nativo no VectorStore
- [ ] **Cache de embeddings** — hoje recalcula no boot; persistir embeddings em `data/vector_memory/` (já existe estrutura)

### 3.5 Auto-extension (`/gerar`)
- [ ] **Templates de ferramenta** — no painel, botão "Novo a partir de template" (ex.: CRUD, wrapper HTTP, parser JSON)
- [ ] **Teste unitário gerado junto** — pedir ao LLM para gerar `test_<nome>.py` junto com a ferramenta
- [ ] **Review antes de instalar** — modo "staging": gera, mostra código/diff, dono aprova → instala

### 3.6 Observabilidade / Operação
- [ ] **Dashboard unificado** — hoje `/admin` tem seções separadas; criar visão "System Overview" com saúde de tudo (RAG, auto-update, downloads, depot, bot, API)
- [x] **Alertas no Telegram** — `/health` degraded → msg pro dono; NRestarts > 0 → msg; disco > 85% → msg — **ENTREGUE 16/10 (sem bump; CHANGELOG §Infra 3.6):** ponte `health_monitor` no notifier (degraded warn 120s / down crit; dedupe com sondas dedicadas), sonda `systemd:nrestarts` (warn ≥1, crit ≥3, `systemctl --user show` em thread; desconhecido = ok) e disco com `OD_DISK_THRESHOLD_PERCENT` (padrão 85). +29 testes (2964/16, cov 90,60%), prova de fogo com sink real, restart verde PID 3367820. Bônus: `format_alert` mostrando hora monotônica (data errada no Telegram) consertado com `Alert.wall`. **Refino 16/10 (ordem do dono):** o alerta `restart` virou **EVENTO — um disparo por boot** (`CheckResult.cooldown_s` = guarda de rajada de 300 s), porque o anti-spam de 1 h atrasava o aviso do boot novo em até 1 h e parecia push de hora em hora.
- [x] **Backup automático do `.env` + `data/`** — **ENTREGUE 16/10 (sem bump; CHANGELOG §Infra):** decisão do dono = **local** em `backups/auto/` (ele transfere para o HD externo), escopo `.env` + `data/` **sem** `captures/` (304 MB de fotos) e **sem** `vector_memory/` (reconstruível) ⇒ **~185 KB/rodada**, **03:00** com **catch-up** e retenção **3 diários + 8 semanais** (`core/backup.py`, 100% de cobertura, +60 testes). Um `.tar.gz` por dia com o `.env` dentro (`0600`/`0700`), sha256 no estado, check não-crítico `backup` no `/health`, bloco no `/dashboard/stats` e card no `/admin`. Falha avisa no celular (1 push a cada 6 h). Off-site (S3/MinIO/rclone) fica para quando o dono decidir a conta/provedor.
- [x] **Backup das CAPTURAS (semanal, para o HD externo)** — **ENTREGUE 16/10 (ordem "inclua data/captures no backup", sem bump; CHANGELOG §Infra):** perfil **semanal próprio** em `backups/auto-capturas/` — `core/backup.py` ganhou a tabela `PERFIS` (`estado` diário/03:00 **intocado** e `capturas` semanal/**04:00**, prefixo `od-capturas`, **0 diários + 4 semanas**, check `backup_capturas`, knobs `OD_BACKUP_CAPTURAS_*`), `cadencia_dias` generalizando `proxima_janela` e retenção que **não cruza perfis**. Medido antes de decidir: `data/captures` = **316 MB** que o gzip **não reduz** (316.016.667 de 316.051.501 — mídia já comprimida) e **10,7 s** para empacotar ⇒ semanal (316 MB/dia seria desperdício para acervo append-only) e 4 semanas ≈ **1,3 GB** dos 85 GB livres. `build_backups()` monta os dois loops supervisionados (tar em `to_thread`), **2 checks não-críticos** no `/health`, bloco por perfil no `/dashboard/stats` e cards **"Backup"**/**"Backup fotos"** no `/admin`. **Furo de segurança fechado no mesmo commit:** `backups/auto/` → **`backups/auto*/`** no `.gitignore` — o diretório novo **não estava ignorado** e carregava 316 MB das fotos + o `.env` para um repo **PÚBLICO**. +12 testes (3046/16, cov 90,83%; `core/backup.py` 100%), prova viva com snapshot real de 316.276.693 bytes (923 membros, sha256 conferido). **Correção de fato:** o "disco a 85%" que eu registrei às 14:16 era o **limite** configurado do notifier, não o uso — o disco real está em **62%**.

### 3.7 Identidade / Legado (Regra 16)
- [ ] **Consolidar `Legado/OMEGA_DRAKON/`** — núcleo da marca + história (Nicky Virthy, Nicky, NV, Nexus)
- [ ] **Google Drive → repo** — trazer `OMEGADRAKON_SPEC.md`, `OMEGA_DRAKON_SOURCE_MAP.md`, `NICKY_VIRTHY_KNOWLEDGE.md` para `docs/legado/` (sem segredos!)
- [ ] **Bússola `Legado/00_MAPA_DO_LEGADO.md`** — índice vivo vs histórico + mapa de duplicações (já medido bit a bit)

### 3.8 App Flutter
- [x] **Auto-update no app** — download em background no boot + instalação com um toque — **ENTREGUE 16/10 (v1.31.0+2061, item B da fila):** `_preDownload` no `main.dart` (banner "Baixando… N%" → "baixada — pronta para instalar" → **Instalar**), `download()` reusa cache cujo SHA-256 confere (2ª chamada = 0 requisições). O `PackageInstaller` do texto era especulação pré-v1.7.0: o caminho FileProvider/`ACTION_INSTALL_PACKAGE` (27/09) já funciona no Android 14+ e mostra a mesma tela de confirmação do sistema — sessão `PackageInstaller` não ganharia UX.
- [x] **Push FCM** — "auto-update aplicado" no celular — **ENTREGUE 16/10 (item B):** `core/auto_update.py::_anunciar()` chama `PushService.notify` nos dois sucessos do ciclo (re-sync do índice RAG com stats de chunks; download concluído/movido com alvo+versão), injetado por `build_auto_update(push=)` — best-effort, nunca derruba o ciclo. Saúde/nerve já vinha ligada pelo notifier (15–16/10) e o FCM e2e (registro/exibição no app) desde 13/09 (`3b5599c`).
- [x] **Tema escuro/claro sincronizado** — preferência salva no perfil do usuário (já tem `UserStore`) — **ENTREGUE 16/10 (v1.32.0+2062; CHANGELOG §1.32.0):** a preferência vive no PERFIL (`user_prefs` + `GET/PUT /profile/preferences`, e o `/auth/me` devolve `preferences`) e a MESMA chave `theme` (`system|light|dark`) orienta **app + painel + site (11 páginas)** — trocar no celular muda o site e o painel no mesmo login. As três decisões do dono: tema nos três clientes, **seguir o sistema** para quem nunca escolheu, e preferência **no perfil + cópia local** (`SharedPreferences`/`localStorage`, que abre já no tema certo sem rede). Site e painel recebem a paleta clara e o botão por **injeção única** (`od.css`/`od-nav.js` e `_com_tema()` no painel, dentro do único `<script>` da página) — nenhuma das 11 páginas foi editada. Chave desconhecida é **400** e não silêncio. +17 testes (3074/16 · 90,91%) + 13 do app (`flutter analyze` 0 issues, 192/2).
- [ ] **Tema — falha residual no site (ADIADO pelo dono 16/10 ~19:50)** — dono reportou: "ainda falha mas bem menos, vamos deixar isso para depois". O clique morto do ciclo foi corrigido (conserto das 17:47, commit 5053c54), mas sobrou um caso não reproduzido. Quando o dono retomar: pedir o exemplo exato (qual página, aparelho claro/escuro, de qual estado o botão partia) e instrumentar/replicar antes de mexer. App segue ok nas palavras do dono.

---

## 4. Dívida técnica conhecida (baixa prioridade, mas registrada)

| Área | Item | Impacto |
|---|---|---|
| `bw` CLI oficial ≥ 2026.9 (dívida atualizada 17/10) | **Dois** bloqueios do `bw` 2026.x × Vaultwarden 1.36.0: (a) prelogin de ≥2026.9 (`{kdfSettings, Salt}` vs `{kdf, kdfIterations}` — flag `pm-27060` fora do allowlist `SUPPORTED_FEATURE_FLAGS`); (b) **parse de cifras** de 2026.8→2026.10 (em Node 18 **e** 22): `invalid type: JsValue … expected a string` — **só aparece com item no cofre** (o drill de 15/10 testou vazio e registrou o 2026.8 como "funcionando", agora corrigido). **Resolvido operacionalmente no 17/10**: pin **2025.12.1 + Node 22 + `BITWARDENCLI_APPDATA_DIR` próprio** (ciclo list/create/edit/delete provado na entrega v1.35.0) | Web vault normal; o sistema usa o pin 2025.12.1 via wrapper — reavaliar ao upgrade da imagem/CLI |
| Repo GitHub público | Histórico antes de `3ed13cc` continha segredos do compose (ADMIN_TOKEN etc.) — visibilidade/rotação é decisão do dono (§2) | Segurança |
| `tools/auto_extension/engine.py` | Caminho legado (`depot=None`) mantido para compat — pode ser removido depois que todo mundo migrar | Limpeza |
| `tools/registry.py` | `version` field no `Action` nunca comparado no registro (só no depot) — OK por enquanto | Consistência futura |
| `core/capabilities.py` | Fallback hardcoded `OD_VERSION` — OK porque `.env` sempre vence | Segurança |
| `integrations/api/server.py` | JS do painel inline no Python (string gigante) — extrair para `site/admin.js` servido estático | Manutenibilidade |
| `runtime/launcher.py` | `_ENV_CACHE` global — testes patcham isso, não `os.environ`; documentar melhor | Onboarding |

---

## 5. Ideias de expansão (parking lot)

- **Análise a fundo de FlatNotes, File Browser e Calibre Web — uma por vez** (pedido do dono 17/10): decidir junto manter/ligar ao sistema/tirar; hoje estão vazias (20 KB / 48 KB / 0 livros) e no ar. Enquanto isso, a ordem aprovada (17/10) avança: **Vaultwarden ✅ interligado (v1.35.0)** → **Stirling PDF ✅ interligada (v1.36.0)** → **Kiwix (próxima)**; e o **Homebox volta na sequência com uso definido** (decisão do dono 17/10: inventário/garantias da casa, já integrado com `homebox_*`)

- **MCP Server** — expor actions/ferramentas do OD via Model Context Protocol para Claudes/Cursors externos
- **Plugin marketplace** — o `tools/loader.py` já carrega `.py` de `plugins/`; criar `plugins/` oficial com manifest
- **Multi-tenant** — hoje `OD_ACCOUNT_ALIASES` mapeia `app=alex`; permitir múltiplos donos/equipes
- **Voice/TTS/STT local** — Piper (TTS) + Whisper.cpp (STT) já testados; integrar no bot como actions
- **Agentic loops** — `RecoveryLoop` (Parte 7.4) já existe; expandir para "auto-repair" de ferramentas quebradas no depot

---

## 6. Checklist de Definition of Done (para cada entrega)

> Copiado de `docs/REGRAS_DE_TRABALHO.md` §2 — **não pular nenhum**:

- [ ] Testes passam (suíte + gate `--cov-fail-under=90`)
- [ ] `flutter analyze` 0 issues + `flutter test` verde (se tocar app)
- [ ] Política de versão 9/9 (`.env`, capabilities, pubspec, `_APP_VERSION_CODE`, site ×4, CHANGELOG, README_VERSAO, ANALISE)
- [ ] APKs rebuildados (`versionCode` novo) + publicados em `site/`
- [ ] Deploy verde (`systemctl --user restart od-core` autorizado por regra 7.3)
- [ ] Prova viva no serviço (PID, NRestarts=0, /health up, journal 0 erros)
- [ ] `CHANGELOG.md` + `README_VERSAO.md` + `ANALISE_PROJECT_NOMAD.md` atualizados com tabela de prova
- [ ] `txt.txt` reescrito (regra 14)
- [ ] Telegram msg enviada (regra 15, chat 660518870)
- [ ] `iniciar/YYYY-MM-DD_conversa_omegadrakon.md` + `session.json` atualizados
- [ ] `git commit` + `git push origin master` (regra 7.1 — autorizado por padrão)
- [ ] Árvore limpa (`git status --short` vazio exceto `.env`/ignored)

---

## 7. Próxima ordem do dono — decidir agora

| Candidato | Esforço | Dependência | Observação |
|---|---|---|---|
| **DECISÃO FINAL (12/10) — healthchecks** | ~~Alto~~ ✅ | Concluído 15/10 ~21:15 | As 9 no `/health` + alerta Telegram (sem bump, 2914/16). Sobra ProtoMaps (dev task, opcional) |
| **Registro Mestre — Etapa 4** | ~~Médio~~ ✅ | Concluído 15/10→16/10 | Posse/QR/loja **no ar (v1.30.0+2060)**: comprador registra no app, QR no cartão, regressão com código, loja sem preço (2929/16, gate 90,58%). Sobra v2: câmera de QR dentro do app |
| **Melhorar RAG (embedding + corpus externo)** | ~~Médio~~ ✅ | Concluído 16/10 ~03:40 | **No ar (sem bump):** `iniciar/*.md` no corpus (895 → **1.598 chunks**) + floor recalibrado **0,399/0,036** (grid medido, 780 células válidas) → parafrases **1/8 → 6/8**, gate 8/8+8/8 intacto (2935/16, cov 90,60%). Embedding semântico **medido e recusado**: quebra precisão (irr 0,546 > rel 0,394 em todas as chaves) e box tem só ~1,7 GB RAM |
| **Observabilidade / Alertas Telegram** | ~~Baixo~~ ✅ | Concluído 16/10 ~04:55 | **No ar (sem bump):** `/health` degraded → Telegram (dedupe com sondas dedicadas) + `NRestarts > 0` (queda anormal) + disco `OD_DISK_THRESHOLD_PERCENT` (2964/16, cov 90,60%; prova de fogo com sink real; fix da data nas mensagens) |
| **App auto-update + FCM** | ~~Médio~~ ✅ | Concluído 16/10 | **No ar (v1.31.0+2061):** download em background no boot (banner % → "pronta para instalar" → **Instalar** com SHA conferido) + push **"Auto-update aplicado"** do servidor no celular (FCM e2e já ligada desde 13/09; o que faltava era o hook do Parte E). Guardas: gate servidor + `flutter analyze/test` verdes |
| **Tema claro/escuro sincronizado** | ~~Médio~~ ✅ | Concluído 16/10 | **No ar (v1.32.0+2062):** preferência no perfil (`user_prefs`, `GET/PUT /profile/preferences` + `preferences` no `/auth/me`) lida pelos **três clientes** com a mesma chave, "seguir o sistema" como padrão e cópia local em cada um. Paleta clara e botão injetados (site e painel) sem editar as 11 páginas. +17 testes no servidor (3074/16, cov 90,91%) e +13 no app (192/2, analyze 0) |

> **Sugestão:** a fila §7 está **zerada** e os três candidatos que restavam
> no §3 foram entregues em 16/10 — **Backup automático `.env`+`data/`**
> (§3.6), **Métricas Prometheus do auto-update** (§3.5) e **Tema
> claro/escuro sincronizado** (§3.8, v1.32.0+2062). Sem candidato técnico
> aberto no §3: as pendências vivas são do dono (§2 do todo da conversa —
> Órion com 2 capturas sem instrução, Vaultwarden, repo público/pautas).

---

**Atualizado em:** 2026-10-17 16:10 (**fila FECHADA DE VEZ: Vaultwarden ✅ Stirling ✅ Kiwix ✅ Homebox ✅** — inventário do dono interligado e já populado com as 2 peças reais dele (RPi4 + ESP-01S/DHT22), v1.38.0+2071, 106 actions; rotação §8.5 ainda pendente)
**Próxima revisão:** na próxima "leia iniciar" ou nova ordem do dono.