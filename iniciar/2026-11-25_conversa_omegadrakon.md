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
