# Transcrição da sessão — 2026-10-24

> Registro conforme regra 4 do `iniciar/RULES.md`. Contexto em
> `iniciar/session.json` (chave `reverificacao_e_fecho_divida_4_2026_10_24`).

## §1 — Retomada de rotina ("leia iniciar", 24/10 ~02:30): resíduo de
       sessão morta achado, validado e FECHADO (dívida técnica §4)

**Pedido:** usuário: "leia iniciar" — reverificação de rotina (regra 3).
Checkpoint lido: `session.json` (§11 = tar do legado já transferido pelo
dono) + transcrição `2026-10-23` (§10/§11).

**Achado principal — RESÍDUO NO DISCO:** a árvore estava **suja** com
6 arquivos modificados + 2 novos (`site/admin.js`,
`tests/test_action_registry.py`), última edição **23/10 14:41–15:08**
(11 h parados = sessão morta, não trabalho em curso). Era a **dívida
técnica §4 no meio do caminho**: a sessão de ontem extraiu o JS do
painel para o arquivo real `site/admin.js`, versionou o `ActionRegistry`
e comentou 3 pontos de política — mas morreu **antes do gate e do
commit**. Mesmo padrão das sessões interrompidas de 21–22/10.

**Verde do resto (idem §10):** od-core active desde 13:52:01 de 23/10,
NRestarts=0, journal 0 `[ERROR]`, `/health` ok=True 25 checks,
`/app/version` 1.44.0/2080, disco 64% (80 G), `txt.txt` vazio.

**O que faltava e foi completado antes de fechar:**

1. **2 guards vermelhos** em `tests/test_portal_ferramentas.py` — o
   resíduo deixou a suíte **vermelha** (`test_menu_lateral_tem_as_4_e_mesma_aba`
   e `test_barra_fixa_e_botao_de_topo_nas_telas` ainda liam o JS inline
   no HTML do painel). Migrados para meder o **`/site/admin.js` servido**
   + a tag `<script src>` na página; intenção preservada bit a bit (as 4
   ferramentas do portário, IT Tools fora, mesma aba, montagem do ↑
   depois da guarda `odOla`).
2. **Gate canônico quebrado na coleta:** o depósito do dono
   `analise/Nicky Locutor/` (regra 17, ontem 13:05) tem um
   `test_async.py` que importa `feedparser` — a suíte inteira parava na
   importação **antes de rodar**. Causa raiz corrigida com
   **`pytest.ini` novo**: `norecursedirs` = defaults do pytest +
   `analise/`, `backups/`, `data/`, `logs/` — `analise/` é caixa de
   entrada de arquivos arbitrários dele e nunca mais derruba o gate.

**Validação:** gate oficial **2×** — `3759 passed / 16 skipped /
0 falha · ≥90%` — a segunda **depois** da edição do CHANGELOG (alimenta
o corpus do RAG). pyflakes **0 aviso novo** (os 10 pré-existentes
conferidos contra o HEAD via `git show` + diff). `node --check
site/admin.js` limpo. CHANGELOG 1.44.0 ganhou a subseção "Dívida
técnica §4 fechada" (**sem bump** — backend/limpeza).

**Deploy:** commit **`9f97d54`** pushado (11 arquivos, +754/−458), HEAD
== `origin/master`, árvore limpa. **Restart verde 02:39:09** (regra 7.3,
cenário verde antes): MainPID 1149026, **NRestarts=0**, journal desde o
boot **0 `[ERROR]`**, `/health` ok=True **25 checks nenhum fora**,
`/app/version` **1.44.0/2080** intacta. Prova viva: `/site/admin.js`
HTTP **200, 17123 B**, com as duas seções (od-tema + formato Órion).

**Pauta do dono:** `analise/Nicky Locutor/` segue **não analisada**
(projeto locutor/TTS: `main.py` + feedparser, `docker-compose.yml`,
`Dockerfile`, `locucoes/`, `requirements.txt`) — aguardando ordem dele.
Pautas "não cobrar" inalteradas (cofre pessoal adiado, fotos
adicionais, catálogo 3D). Fila zerada de resto; dívida técnica §4
**fechada**.


## §2 — Dívida técnica §4: fecho dos 2 itens que restavam (24/10 ~03:00)

**Pedido:** dono — "Fechar os 7 itens restantes da dívida técnica §4".
Dos 7, **5 já tinham sido fechados no commit `9f97d54`** da madrugada
(JS do painel → `site/admin.js`, registro versionado, 3 documentações
de política). Restavam **(1) o pin do `bw`** e **(2) o repo GitHub
público**.

### Item 1 — `bw` CLI: reavaliação medida e migração

A dívida pedia "reavaliar ao upgrade da imagem/CLI" — e **ambos
mudaram**: Vaultwarden **1.36 → 1.37.4** e npm latest = **2026.10.0**.
Testes ao vivo, **com item real no cofre** (o drill de 15/10 errara
justamente por exercitar cofre vazio; appdata isolado, snapshot do
`data.json` de produção antes de qualquer coisa):

- **Cifras (bloqueio nº 2): RESOLVIDO.** 2026.10.0 + Node 22 contra a
  1.37.4: unlock (88 ch) + `list items` = **21 itens decifrados**. O
  crash `invalid type: JsValue … expected a string` era da dupla 2026.x
  × Vaultwarden **1.36** e não se reproduz mais.
- **Node 18 continua proibido:** a mesma 2026.10.0 **panica** no unlock
  (`system RNG must not fail: Web Crypto API is unavailable`).
- **`prelogin` (bloqueio nº 1): o comando foi REMOVIDO** do CLI 2026.x.
  Irrelevante para a casa — o `vault.py` nunca usou prelogin (só
  `unlock`/`list`/`get`/`create`/`edit`/`delete`, todos presentes).
- **Honestidade:** o pin 2025.12.1 **também seguia saudável** na 1.37.4
  (a contagem 20 vs 21 era **cache local**, não divergência de CLI —
  provado por diff de títulos + `bw sync`). Migração = escolha do dono,
  não necessidade.

**Migração (escolha do dono via pergunta objetiva):** wrapper
`~/.local/bin/bw` → **2026.10.0 + Node 22** (`~/.local/opt/bw2026`,
`BITWARDENCLI_APPDATA_DIR` próprio mantido). Rollback à mão:
`~/.local/opt/bw2025` + `data.json.bak-2025-pin` (o 2025 rejeita
keyring gravado pela 2026). **E2E pelo `vault.py` de produção** (o
mesmo das actions): `status` locked/alcança=True → `guardar` criou
(21→22) → `obter` senha **confere** → `guardar` de novo **atualiza sem
duplicar** → `apagar` → cofre **de volta a 21**. Senha sempre via
`--passwordenv`; nenhum segredo impresso.

### Item 2 — repo GitHub público: decisão do dono

Confirmado ao vivo via API: `private: False` (**público**). Sem `gh` e
sem token de admin no servidor, a privatização seria dele de qualquer
forma — perguntei e ele decidiu: **segue público** (histórico antes de
`3ed13cc` expôs ADMIN_TOKEN + pepper, ambos **rotacionados em 17/10**
com valor morto; repo sem segredo vivo). Registrado como **decisão**,
não como pendência.

### Fechamento

- `integrations/vault.py`, `core/capabilities.py`, `tests/test_vault.py`:
  textos do pin atualizados (histórico do CHANGELOG intocado).
- CHANGELOG 1.44.0 ganhou a subseção "bw migra para 2026.10.0"
  (**sem bump** — infraestrutura).
- TODO 4 do FlatNotes reescrito com coluna de estado = **7/7 FECHADOS**.
- **Validação:** `tests/test_vault.py` **37/37** · gate oficial
  **3759 passed / 16 skipped / 0 falha** · pyflakes 0 aviso novo.
  **Sem restart** (o wrapper é lido a cada chamada; em runtime só
  comentários mudaram).

**Estado:** dívida técnica §4 **100% fechada (7/7)**; sistema verde
1.44.0/2080. Próxima pauta do dono: `analise/Nicky Locutor/`.

**Nota honesta:** num dos comandos de diagnóstico, 60 caracteres da
chave de sessão (88 ch, efêmera — morta no próximo unlock/lock) de um
unlock meu foram impressos no stdout por engano. Não é senha master
nem segredo de cofre; registro aqui mesmo.
