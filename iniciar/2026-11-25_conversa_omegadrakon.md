# Registro de Conversa — 2026-11-25

## §1 — Retomada "leia iniciar" (25/11 14:22)

### Pedido do Dono

> leia iniciar

### O que foi lido (regra 3)

`iniciar/README.md`, `iniciar/RULES.md` (24 regras), `iniciar/session.json`
(entrada mais recente: `reconhecimento_seguranca_vigia_2026_11_23`),
`iniciar/ATRIBUICOES.md`, transcrição `iniciar/2026-11-23_conversa_omegadrakon.md`
(§1 e §1.1) e o `git` do repositório.

### Estado medido (não presumido)

| Item | Medição de agora |
|------|------------------|
| Árvore de trabalho | **limpa** (`git status --short` vazio) |
| HEAD × origin | `HEAD == origin/master == a909040` (0 commits de diferença) |
| Último commit | `a909040` — 23/11 09:29 (reconhecimento de segurança do Vigia) |
| `od-core` | **active**, `MainPID 3986249`, `NRestarts=0`, no ar desde **21/11 05:38** |
| Código em execução | processo de 21/11 (commit `1db5e6a`) — **o lote de 23/11 NÃO está no ar** |
| `/health` | `ok=true`, **32 checks**, nenhum fora de `up` (com `X-API-Key`) |
| `/app/version` | 1.46.1 / versionCode 2084, `size` 72.488.590, sha `ac60b136…` |
| Journal `od-core` | `-p err` desde 23/11: **0 entradas** |
| `txt.txt` | só o despejo de terminal do login do dono (21/11 05:22) — **sem pedido novo** |

### Achados

1. O lote de 23/11 (reconhecer eventos de segurança pelo chat) está
   **publicado** (`87384c2` + `a909040`) e com **gate verde** registrado
   (`5641 passed / 19 skipped / 0 falha`, 241,82 s), mas **não está vivo**:
   o processo é de 21/11. Falta apenas o restart do `od-core`.
2. `logs/network_watchdog_estado.json` já foi reconhecido em 23/11
   (`pendentes_seguranca=[]`, `pendentes_novos=[]`) — os avisos pararam **de
   fato**; o que falta é o *comando* de chat existir no processo novo.
3. Nenhuma entrega pela metade na árvore: o lote registrado como "pela metade"
   nas atribuições é só o restart.

### Decisão deste turno

Turno de **leitura + registro** (como nas retomadas de 14/11 e 18/11): nenhum
código alterado, nenhum gate rodado de novo, **sem restart** e **sem bump**
(1.46.1+2084). O restart é o único passo pendente e a regra 7.3 o autoriza por
padrão com validação verde — fica aguardando a palavra do dono para não mexer
no processo vivo durante um turno que só pediu leitura.

### Próximo passo exato

`systemctl --user restart od-core` (regra 7.3), registrar MainPID/NRestarts/
`/health`/journal em `iniciar/` e provar ao vivo: "reconhece a segurança" →
`network_conhecer` com `alvo="seguranca"`.

## §2 — Restart executado: o reconhecimento de segurança está vivo (25/11 14:27)

### Ordem do Dono

> Reinicie o od-core para ativar o reconhecimento de segurança pelo chat, com
> registro e prova viva

### Validação antes do restart (regra 7.3 / 10)

Lote afetado, direto no código do HEAD: `pytest -q tests/test_intents.py
tests/test_network_watchdog.py tests/test_notifier.py
tests/test_actions_catalog.py tests/conftest.py` → **444 passed em 11,36 s**,
exit 0. O gate completo do próprio lote era **5641 passed / 19 skipped /
0 falha** (23/11, 241,82 s) e desde então só entraram `.md`/`.json`.

### Antes e depois

| | Antes | Depois |
|---|---|---|
| MainPID | 3986249 | **1768401** |
| Início | 21/11 05:38 | **25/11 14:27:34** |
| Commit em execução | `1db5e6a` | **`229b5ba`** |
| NRestarts | 0 | 0 |
| `/health` | ok, 32 checks | **ok, 32 checks, nenhum fora de `up`** |
| journal `-p err` (10 min) | — | **0 entradas** |

O auto-registro (regra 4, `core/registro_restart.py`) gravou sozinho em
`restarts_od_core`: `{pid: 1768401, commit: 229b5ba, branch: master,
iniciado_em: 2026-11-25T14:27:34-03:00, host: nicky-server, modo: all,
usuario: alex}`.

### Prova viva (chat, processo novo)

```
POST /message  {"text": "reconhece a segurança", "user_id": "app"}
→ route=action_intent | llm_used=fastpath:network_conhecer
  latency_ms=29,062 | fallback_used=false | cached=false
  message="✅ Nenhum evento de segurança pendente — nada a reconhecer."
```

Journal, mesma requisição: `Message processed | route=action_intent |
user=alex | profile=guardian | llm=fastpath:network_conhecer |
latency_ms=29.062`. Ou seja: **29 ms e nenhuma chamada de LLM** — o comando do
chat que faltava agora existe no processo, e sem pendência ele responde isso
em vez de inventar.

### Estado e limites

- Sem bump (1.46.1+2084): mudança de servidor, contrato do app intacto.
- Nada apagado; `logs/network_watchdog_estado.json` segue com
  `pendentes_seguranca=[]` e `pendentes_novos=[]`.
- Limitação honesta: a prova foi com a fila **vazia** (resposta "nada a
  reconhecer"). O ack com eventos de verdade foi provado em 23/11 no processo
  antigo e nos testes (`TestNetworkConhecerSeguranca`), não agora — não fabriquei
  evento de segurança falso só para ver a mensagem de sucesso.

## §3 — Offsite do dump do Postgres fechado com prova (25/11 14:50)

### Ordem do Dono

> Feche o offsite físico do backup do Postgres fora da máquina

### O que já existia (medido, não presumido)

O dump diário de `data/pg_dumps/` (timer `od-pg-dump`, 02:50) já saía da
máquina por **dois** caminhos:

1. **HDs externas** — `core/hd_backup.py` faz snapshot diário às ~03:44 das duas
   HDs (`/home/alex/dados` = **`/dev/sdb1`**, disco separado do sistema, e
   `/mnt/Arquivos`) levando o repo inteiro, logo `data/pg_dumps/`;
2. **canal privado do Telegram** — o tar diário das 03:00 leva `data/` e o
   `core/offsite.py` envia o tar ao canal, registrando nome + sha256 em
   `data/offsite_state.json`.

O que **não** existia: prova de que o arquivo que chegou é o que foi gerado,
e guarda contra silêncio (exclusão nova, tar trocado, cópia truncada).

### Medições

| Destino | Cópia | sha256 |
|---|---|---|
| `data/pg_dumps/od-2026-11-25_0250.sql.gz` (origem, 37.806 B) | — | `3bfaff1c…` |
| Mídias — `snapshot_od-2026-11-25_0346` | idêntico | `3bfaff1c…` |
| Arquivos — `snapshot_od-2026-11-25_0347` | idêntico | `3bfaff1c…` |
| Canal — `od-2026-11-25_0301.tar.gz` (sha `a46ee6df…`, o do `offsite_state.json`) | membro do tar idêntico | `3bfaff1c…` |

**Restauração a partir da cópia do HD** (não do original):

```
tools/testar_restauracao_pg.py --dump <snapshot 03:46>/…/od-2026-11-25_0250.sql.gz
→ RESTORE OK em 0,17 s · 14 tabelas · FIDELIDADE OK: 604 linhas
→ INFO: 1 tabela avançou no banco vivo desde o dump (esperado, não é falha)
```

### O que entrou

- `tools/checar_offsite_pg.py` (novo) — guarda nas duas direções: o dump atual
  tem de estar **presente e com o mesmo sha256** no snapshot mais novo de cada
  HD e **dentro do tar** registrado como enviado (e o tar em disco tem de ser o
  do registro). Compara **sha256**, nunca tamanho ou nome. HD desplugada ou
  snapshot anterior ao dump saem como `ausente`/`aguardando`; só divergência
  real derruba (exit 1). `--json` para painel/CI.
- `tests/test_checar_offsite_pg.py` (novo) — **14 testes**, incluindo tar
  trocado, tar que sumiu, dump ausente no snapshot novo, cópia com conteúdo
  diferente e `--json`.

### Prova

```
python3 tools/checar_offsite_pg.py
CANAL ok: od-2026-11-25_0301.tar.gz — sha256 3bfaff1c idêntico
HD ok: /home/alex/dados/od_snapshots — sha256 3bfaff1c idêntico
HD ok: /mnt/Arquivos/od_snapshots — sha256 3bfaff1c idêntico
OFFSITE OK  (exit 0)
```

### Estado e limites

- **Fechado** o offsite do dump do Postgres com prova de conteúdo e de
  restauração da cópia offsite.
- **Limite declarado:** as duas HDs ficam na mesma casa e o canal é nuvem; a
  mídia física que sai do local (pendrive/SSD criptografado com o dump +
  `data/`) continua sendo ação do dono — é o item que sobra na pendência de
  continuidade.
- Sem bump (1.46.1+2084): ferramenta de verificação, serviço e app intactos.

---

## §4 — I2 (RAG híbrido) ligado com piso próprio medido (~15:5x)

**Pedido do dono:** *"Recalibre o piso do RAG híbrido para ligar o I2 com
evidência medida."*

### O que a medição mostrou

1. O medidor de 18/11 reproduzido no corpus de hoje (4104 chunks) ainda
   reprovava o default: com o piso denso aplicado à união, **2 de 8
   irrelevantes** injetavam trecho.
2. A causa ficou explícita: os trechos falsos são **as nossas próprias
   transcrições** que citam as perguntas do gate (auto-referência), com
   `overlap = 1,0` ou 0,68.
3. Grid de 9.333 células (score × overlap, passo 0,001): **nenhum par
   separa**. O comb dos falsos positivos (0,439 e 0,447) é **maior** que o
   do relevante mais fraco (0,410); o overlap chega a 1,0. Não é piso: é
   casamento de palavra contra um corpus que fala das próprias perguntas.

### A régua que separa (medida)

Piso **próprio do candidato só-lexical**: `PISO_SCORE_LEXICAL = 0,47`
(pior irrelevante 0,447 + margem 0,023). O piso denso `0,399/0,036` ficou
**intocado**; candidato vindo do denso não usa o piso novo. A faixa válida
medida é 0,448–0,60; 0,47 é o menor com margem.

```text
python3 tools/recalibrar_piso_hibrido.py
corpus: 4104 chunks
piso denso (intocado): score 0.399 / overlap 0.036
pior irrelevante só-lexical: comb 0.4471
faixa de piso lexical que passa o gate: (0.448, 0.6)
piso lexical escolhido: 0.47 (pior irrelevante + margem 0.02)
gate no escolhido: 8/8 relevantes · 0/8 irrelevantes · 6/6 paráfrases · 2/2 estruturais
```

### Gate nos dois modos

| Grupo | Denso | Híbrido |
|---|---|---|
| 8 relevantes | 8/8 | 8/8 |
| 8 irrelevantes bloqueadas | 8/8 | 8/8 |
| 6 paráfrases | 6/6 | 6/6 |
| 2 estruturais | 2/2 | 2/2 |

Resgates reais preservados (`tools/medir_rag_hibrido.py`): eval do
assistente **comb 0,636** (chunk `[1.24.2]` no bloco), Registro Mestre
0,628, identidade visual 0,565, versionamento 0,552, containers 0,528,
regras 0,514, cadastro 0,512.

### Código

- `memory/rag.py`: `PISO_SCORE_LEXICAL = 0,47`, parâmetro
  `min_score_lexical`, piso aplicado por `doc_id` marcado como só-lexical,
  métrica `descartados_lexicais`, `hibrido` **ON por padrão**
  (`OD_RAG_HIBRIDO` default "1") e `dump()` expondo `hibrido` e
  `min_score_lexical`.
- `runtime/launcher.py`: `top_k` do store 24 → `TOP_K_CANDIDATOS` (32) —
  o comentário dizia "coerente", mas 24 deixava fora o alvo que a medição
  de 14/11 achou em 26º.
- `tools/recalibrar_piso_hibrido.py` (novo): medidor do piso com origem do
  candidato, varredura e resgates; `--json`.
- `tests/test_rag.py`: `TestCalibracaoHibrida` (8+8+6 + resgate do eval),
  default ligado, desligado explícito, env "0", piso só-lexical
  descartando candidato.

### Lição operacional (custou uma rodada)

A primeira gravação **deste registro** repetiu as perguntas do gate e o
gate caiu na hora (comb 0,490 no chunk novo) — o mesmo falso-amigo de
05/11 e 10/11. Reescrito sem as frases literais (o precedente da casa) e o
gate voltou verde. Texto novo em `docs/`/`iniciar/` mexe na calibragem.

**Validação:** `tests/test_rag.py` 125 passed; `test_rag` +
`test_hybrid_search` 138 passed. Sem bump (1.46.1+2084).

---

## §5 — Atualizações do sistema operacional (~16:0x)

**Pedido do dono:** *"leia também o txt. existem atualizações do sistema
operacional, OD possui algum action ou ferramenta para resolver isso, se não
então crie."*

**Medido (`python3 -m core.os_updater --status`, 25/11 15:5x):**

```json
{"ok": true, "kernel_atual": "6.8.0-147-generic", "precisa_reboot": true,
 "upgradable": 56, "firmware_upgrades": 51, "schedule": "weekly",
 "day": 6, "hour": 3, "ultima_execucao": 1794273354, "proxima_execucao": 1795932000}
```

**Existe ferramenta? Sim — e não foi preciso criar:**

- `core/os_updater.py` — ciclo apt update + full-upgrade + autoremove,
  `fwupdmgr refresh/update`, reboot pendente, notificação Telegram, estado
  em `data/os_updater_estado.json`; CLI `--status/--executar/--forcar/
  --dry-run`; **19 testes** em `tests/test_os_updater.py`.
- Rotas `GET /admin/os-updater/status`, `POST /admin/os-updater/executar`,
  `POST /admin/os-updater/reboot`.
- Units `systemd/od-os-updater.service` + `.timer` (domingos 03:00).

**O que falta (medido, não suposto):**

1. `systemctl is-enabled od-os-updater.timer` → **not-found**: as units
   existem no repositório mas **não estão instaladas**; nada dispara o
   ciclo sozinho nesta máquina. A "próxima execução" do status é só a
   conta do agendamento, não um timer ativo.
2. A última execução registrada (09/11 22:15) foi **dry-run** — não
   atualizou nada, apesar de `sucessos_consecutivos: 1` no estado.
3. Há **reboot pendente** (`/var/run/reboot-required`) e 56 pacotes +
   51 firmwares esperando.

**Ação do dono (precisa de sudo e decide sobre reboot):**

```bash
sudo cp systemd/od-os-updater.service systemd/od-os-updater.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now od-os-updater.timer
python3 -m core.os_updater --status
```

Para aplicar agora, sem esperar domingo: `sudo systemctl start
od-os-updater.service` (o ciclo agenda reboot +5 min se necessário).
