# TODO — OmegaDrakon (próximas atualizações)

> **Regra:** este arquivo é o **canal do dono** (regra 14) — editável pelo painel `/admin` e pelo app. Não perca nada durante a caminhada.

---

## 1. Stack Nômade Atual (`docker/tools-compose.yaml`) — 9 serviços **no ar** (auditado 15/10)

| # | Serviço | Container | Porta local | Status | Observação |
|---|---|---|---|---|---|
| 1 | **Kiwix** (Wikipedia offline) | `od-kiwix` | 8090 | ✅ | ZIM `wikipedia_en_all_mini` (14,4 GB) **já baixado em 13/10** |
| 2 | **CyberChef** (data tools) | `od-cyberchef` | 8100 | ✅ | ~300 operações (base64, hash, cifra) |
| 3 | **IT Tools** (dev utils) | `od-it-tools` | 8430 | ✅ | UUID, hash, formatadores |
| 4 | **FlatNotes** (caderno MD) | `od-flatnotes` | 8200 | ✅ | auth=none (só Tailscale); API p/ actions "anota"/"o que anotei" |
| 5 | **Stirling PDF** (50+ PDF tools) | `od-stirling-pdf` | 8400 | ✅ | OCR, merge, split, assinar; JAVA_TOOL_OPTIONS fix metaspace |
| 6 | **File Browser** (arquivos web) | `od-filebrowser` | 8410 | ✅ | login admin/admin → trocar |
| 7 | **Calibre Web** (e-books) | `od-calibre-web` | 8420 | ✅ | login admin/admin123 → trocar; books em `/home/alex/omegadrakon-tools/books` |
| 8 | **Homebox** (inventário/QR) | `od-homebox` | 8470 | ✅ | API REST p/ actions; pepper fixo no compose |
| 9 | **Vaultwarden** (cofre senhas) | `od-vaultwarden` | 8480 | ✅ | HTTPS via Tailscale Serve; **conta do dono criada 15/10** (verificada com CLI oficial `bw`); **`SIGNUPS_ALLOWED=false`** (registro recusa HTTP 400) |

> **Situação (15/10):** os 9 sobem com `up -d` e estão no ar. **Pendência do §1 concluída:** conta do dono + signups fechados — comprovado por drill E2E (conta de teste criada pela action, logada e decifrada pelo CLI oficial, depois excluída; vault só com o dono).
> **Bugs corrigidos em 15/10:** `DOMAIN` do Vaultwarden (commit `3ed13cc` — API anunciava URL errada); action `nomad_vaultwarden_setup` estava quebrada (rota `/api/accounts/register` = 404 + payload cru + "fechar signups" só imprimia instrução) → corrigida: rota `/identity/accounts/register`, payload `RegisterData` com crypto oficial (PBKDF2 600k + AES-CBC-HMAC + RSA-2048, validada 100% contra o SDK Bitwarden) e fechamento real (edita compose → recria container → confere env).

---

## 1b. DECISÃO FINAL (12/10) — espelho fiel de `docs/ANALISE_PROJECT_NOMAD.md` (corrigido 15/10)

> A versão anterior desta seção listava itens que **não existem** na DECISÃO FINAL
> (Paperless-ngx, Immich, Audiobookshelf, Portainer, exit node…). A tabela abaixo
> reproduz a fonte da verdade (ANALISE § DECISÃO FINAL 12/10).

| Item | Decisão | Status hoje |
|---|---|---|
| **8 ferramentas** (Kiwix, Stirling PDF, CyberChef, IT Tools, Vaultwarden, FlatNotes, File Browser + Calibre Web, Homebox) | ✅ ENTRA como containers | **Concluído** — 9 containers no ar (§1) |
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
| **Vaultwarden** | ✅ | Conta do dono criada + registro aberto fechado em 15/10 (E2E com CLI oficial). Falta só o dono popular o cofre: `https://nicky-server.tail1b1f51.ts.net:8443` |
| **Registro Mestre — Etapa 4** | ☐ | Comprador / QR / loja do lote de brinquedos |
| **Pauta — Item 3** | ☐ | Semana passada |
| **Pauta — Item 5** | ☐ | Semana passada |
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
- [ ] **Métricas Prometheus** — exportar `auto_update_tick_total`, `auto_update_aplicado_total`, `auto_update_falha_total`

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
- [ ] **Alertas no Telegram** — `/health` degraded → msg pro dono; NRestarts > 0 → msg; disco > 85% → msg
- [ ] **Backup automático do `.env` + `data/`** — daily para S3/MinIO/rclone (já tem a fila da Parte D)

### 3.7 Identidade / Legado (Regra 16)
- [ ] **Consolidar `Legado/OMEGA_DRAKON/`** — núcleo da marca + história (Nicky Virthy, Nicky, NV, Nexus)
- [ ] **Google Drive → repo** — trazer `OMEGADRAKON_SPEC.md`, `OMEGA_DRAKON_SOURCE_MAP.md`, `NICKY_VIRTHY_KNOWLEDGE.md` para `docs/legado/` (sem segredos!)
- [ ] **Bússola `Legado/00_MAPA_DO_LEGADO.md`** — índice vivo vs histórico + mapa de duplicações (já medido bit a bit)

### 3.8 App Flutter
- [ ] **Auto-update no app** — hoje o app checa `/app/version`; adicionar download em background + install `PackageInstaller` (Android 14+)
- [ ] **Push FCM** — já tem `google-services.json`; conectar notificações do servidor (auto-update aplicado, saúde, etc.)
- [ ] **Tema escuro/claro sincronizado** — preferência salva no perfil do usuário (já tem `UserStore`)

---

## 4. Dívida técnica conhecida (baixa prioridade, mas registrada)

| Área | Item | Impacto |
|---|---|---|
| `bw` CLI oficial ≥ 2026.9 | Incompatível com Vaultwarden 1.36.0 no **prelogin** (CLI espera `{kdfSettings, Salt}`; servidor 1.36.0 devolve `{kdf, kdfIterations}` — flag `pm-27060` não está no allowlist `SUPPORTED_FEATURE_FLAGS` do servidor). Funciona com CLI 2026.8.0 (verificado). Resolver com upgrade da imagem quando sair Vaultwarden compatível | Login via CLI oficial de versões novas falha; **web vault empacotada funciona normalmente** |
| Repo GitHub público | Histórico antes de `3ed13cc` continha segredos do compose (ADMIN_TOKEN etc.) — visibilidade/rotação é decisão do dono (§2) | Segurança |
| `tools/auto_extension/engine.py` | Caminho legado (`depot=None`) mantido para compat — pode ser removido depois que todo mundo migrar | Limpeza |
| `tools/registry.py` | `version` field no `Action` nunca comparado no registro (só no depot) — OK por enquanto | Consistência futura |
| `core/capabilities.py` | Fallback hardcoded `OD_VERSION` — OK porque `.env` sempre vence | Segurança |
| `integrations/api/server.py` | JS do painel inline no Python (string gigante) — extrair para `site/admin.js` servido estático | Manutenibilidade |
| `runtime/launcher.py` | `_ENV_CACHE` global — testes patcham isso, não `os.environ`; documentar melhor | Onboarding |

---

## 5. Ideias de expansão (parking lot)

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
| **Melhorar RAG (embedding + corpus externo)** | Médio | — | Recall conservador hoje |
| **Observabilidade / Alertas Telegram** | Baixo | — | Ganho operacional imediato |
| **App auto-update + FCM** | Médio | — | UX do dono no celular |

> **Sugestão:** healthchecks e **Registro Mestre Etapa 4 estão
> concluídos** (15/10 e madrugada de 16/10). Próximo da fila:
> **melhorar o RAG** (embedding + corpus externo — recall conservador
> hoje) ou **Observabilidade/Alertas** — ordem do dono.

---

**Atualizado em:** 2026-10-16 00:20 (Etapa 4 do Registro Mestre entregue: posse/QR/loja + app 1.30.0+2060 — §7; drill E2E com resíduo zero; suíte 2929 passed)
**Próxima revisão:** na próxima "leia iniciar" ou nova ordem do dono.