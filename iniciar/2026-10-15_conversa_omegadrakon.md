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
