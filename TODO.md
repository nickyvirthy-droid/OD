# TODO — OmegaDrakon (próximas atualizações)

> **Regra:** este arquivo é o **canal do dono** (regra 14) — editável pelo painel `/admin` e pelo app. Não perca nada durante a caminhada.

---

## 1. Stack Nômade Atual (`docker/tools-compose.yaml`) — 9 serviços **já no compose**

| # | Serviço | Container | Porta local | Status | Observação |
|---|---|---|---|---|---|
| 1 | **Kiwix** (Wikipedia offline) | `od-kiwix` | 8090 | ☐ | ZIM precisa ser baixado antes (`wget …/wikipedia_en_all_mini.zim`) |
| 2 | **CyberChef** (data tools) | `od-cyberchef` | 8100 | ☐ | ~300 operações (base64, hash, cifra) |
| 3 | **IT Tools** (dev utils) | `od-it-tools` | 8430 | ☐ | UUID, hash, formatadores |
| 4 | **FlatNotes** (caderno MD) | `od-flatnotes` | 8200 | ☐ | auth=none (só Tailscale); API p/ actions "anota"/"o que anotei" |
| 5 | **Stirling PDF** (50+ PDF tools) | `od-stirling-pdf` | 8400 | ☐ | OCR, merge, split, assinar; JAVA_TOOL_OPTIONS fix metaspace |
| 6 | **File Browser** (arquivos web) | `od-filebrowser` | 8410 | ☐ | login admin/admin → trocar |
| 7 | **Calibre Web** (e-books) | `od-calibre-web` | 8420 | ☐ | login admin/admin123 → trocar; books em `/home/alex/omegadrakon-tools/books` |
| 8 | **Homebox** (inventário/QR) | `od-homebox` | 8470 | ☐ | API REST p/ actions; pepper fixo no compose |
| 9 | **Vaultwarden** (cofre senhas) | `od-vaultwarden` | 8480 | ☐ | HTTPS via Tailscale Serve; `nomad_vaultwarden_setup` cria admin + fecha signups |

> **Ação imediata:** `docker compose -f docker/tools-compose.yaml up -d` sobe os 9.
> **Próximo passo real:** Vaultwarden — criar conta do dono + `SIGNUPS_ALLOWED=false` (já tem action `nomad_vaultwarden_setup`).

---

## 1b. DECISÃO FINAL (12/10) — itens que **NÃO** vão no compose agora

| Item | Decisão | Motivo / Status |
|---|---|---|
| **Paperless-ngx** | ❌ Não agora | OCR + full-text PDF — deixar para quando houver volume real de docs físicos |
| **Immich** | ❌ Não agora | Backup fotos/vídeos — Google Photos ainda atende; rever quando migrar |
| **Audiobookshelf** | ❌ Não agora | Audiobooks/podcasts — não é prioridade |
| **Jellyfin** | ❌ Não agora | Media server — Plex/outro já roda; só se precisar self-host |
| **Home Assistant** | ⚠️ Já roda separado | Automação — integração via actions/API futura, não container no stack |
| **Tailscale exit node** | ⚠️ Já no host | `tailscale` já roda no sistema; não precisa de container |
| **Portainer** | ❌ Não agora | Gestão visual — `docker compose ps` + actions `nomad_tools_*` já cobrem |
| **ProtoMaps** | 🟡 Dev task | Página MapLibre + tiles (não container) — quando quiser mapa próprio |
| **LoRa** | 🧊 Geladeira | Aguarda hardware/necessidade real |

> **Conclusão:** o stack **já tem o que precisa** (9 serviços). O foco agora é **subir o Vaultwarden** (criar conta + fechar signups) e integrar healthchecks no `/health` do OD.

---

## 2. Pendências do dono (não mexidas — são suas)

| Item | Status | Observação |
|---|---|---|
| **Vaultwarden** | ☐ | Criar conta do dono + fechar registro aberto |
| **Registro Mestre — Etapa 4** | ☐ | Comprador / QR / loja do lote de brinquedos |
| **Pauta — Item 3** | ☐ | Semana passada |
| **Pauta — Item 5** | ☐ | Semana passada |
| **Rotação de segredos** | ☐ | Adiada — verificado: sem segredo antigo vivo fora do `.env` |
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
| **DECISÃO FINAL (12/10) — 8 containers + ProtoMaps** | Alto (infra + secrets + saúde) | Vaultwarden primeiro (conta do dono) | Fecha a "virada da análise original" |
| **Registro Mestre — Etapa 4** | Médio | — | Comprador/QR/loja brinquedos |
| **Melhorar RAG (embedding + corpus externo)** | Médio | — | Recall conservador hoje |
| **Observabilidade / Alertas Telegram** | Baixo | — | Ganho operacional imediato |
| **App auto-update + FCM** | Médio | — | UX do dono no celular |

> **Sugestão:** começar pela **DECISÃO FINAL** (já tem a tabela aprovada) — sobe o stack Docker, integra healthchecks, resolve Vaultwarden, e o resto flui. O ProtoMaps é dev (página MapLibre), LoRa fica na geladeira.

---

**Atualizado em:** 2026-10-15 11:15 (após Parte F v1.29.0+2059 no ar, PID 2410050)
**Próxima revisão:** na próxima "leia iniciar" ou nova ordem do dono.