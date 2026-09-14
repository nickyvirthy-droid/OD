2026-09-14 — retomada da sessão (regra 3: nenhuma sessão começa do zero).

Entrada:
- Usuário: "leia iniciar".
- Agente leu, nesta ordem: iniciar/README.md, iniciar/RULES.md,
  iniciar/session.json, iniciar/2026-09-13_conversa_omegadrakon.md e
  iniciar/2026-09-12_conversa_omegadrakon.md.

Estado conferido por evidência (não por memória):

Git:
- `git log --oneline -5` → HEAD **8455493** ("chore(git): tira do repositório
  000/ e os arquivos de trabalho local"); antes dele 0dbd04a (checkpoint),
  3b5599c (entrega de push FCM), 8c58520, 68cf2e5.
- `git status --short` → **limpo** (nada pendente, nada untracked).
- Conclusão: o commit do .gitignore (000/ + arquivos soltos da raiz) que a
  rodada 5 de ontem deixou "publicado em seguida" está feito — não há trabalho
  de escrita pendente no repositório.

Credencial do FCM (bloqueio que segue aberto):
- `ls -la config/firebase-service-account.json` → No such file or directory.
- `config/` só tem iot_credentials.json e iot_credentials.example.json.
- A service account continua **ausente no servidor** (mesma situação das
  rodadas 3 e 4 de 2026-09-13). O upload reportado pelo usuário nunca chegou.

Push FCM em execução (ao vivo):
- `systemctl --user is-active od-core` → active; subiu em 2026-09-13 15:56:17
  (PID 191992 — o restart do fim do dia anterior).
- Journal: último "Push FCM inicializado | enabled=False |
  motivo=credencial_ausente | credencial=- | dispositivos=0" às 15:56:17,
  igual a todos os restarts desde 07:19: nada mudou.
- `GET /push/devices` (com a chave do `.env`, 127.0.0.1:8000) →
  `{ok:true, enabled:false, reason:"credencial_ausente", project_id:"",
  devices:0, devices_detail:[]}`.

Tailnet (`tailscale status`):
- nicky-server online (100.77.67.53).
- **redmi-note-14-1 (100.80.224.73) OFFLINE**, visto pela última vez há 7h.
  O aparelho precisa estar online/aberto para registrar o token.

Pontos abertos herdados (todos ainda válidos):
1. Service account do Firebase em config/firebase-service-account.json — só o
   usuário pode gerar no console (projeto nicky-e4f99). Sem ela /push/test
   responde 503 e o envio fica dormente.
2. Instalar/abrir o APK 1.2.0+5 (1005) no Redmi Note 14 para o token ser
   registrado (o aparelho está offline no tailnet).
3. Achados do journal: SelfRepair `no_fix` em agent.py (a cada ~5 min) e o
   handler face.presence com AttributeError → dead letter.

Nada foi alterado no servidor nesta retomada (nenhum restart, nenhuma escrita
fora do registro da sessão). Aguardando a escolha do usuário sobre por onde
seguir.

Rodada 1 (escolha do usuário): "Achados do journal (sem depender de você)"

=== ACHADO 1 — face.presence / AttributeError · BUG REAL · CORRIGIDO ===

Sintoma no journal (ativo hoje, não só em 09-12):
- 09:29:55, 09:31:17, 10:27:10 e 10:27:39 → em cada `face.presence`:
  "Handler error (attempt 1/3, 2/3, 3/3) |
  handler=_run_vision_forever.<locals>.on_change | error=AttributeError" e
  "Handler failed — dead letter".

CAUSA RAIZ (confirmada no código e reproduzida em teste):
- `core/event_bus.py:387` entrega o **Event** ao handler
  (`result = sub.handler(event)`); o payload fica em `event.data`. Convenção
  usada por todo o projeto (bridge MQTT `handler(event)`, testes com
  `lambda e: e.data`).
- `runtime/launcher.py` registrava `on_change(data)` e chamava
  `data.get("confirmed")` — `.get()` no próprio Event →
  `AttributeError: 'Event' object has no attribute 'get'`. O journal só mostra
  o NOME da exceção (o bus loga `error=type(exc).__name__`), por isso o motivo
  exigiu leitura do código.

CORREÇÃO (runtime/launcher.py, `_run_vision_forever`):
- handler passa a receber `event` e a ler `data = getattr(event, "data",
  None) or {}`, com guarda de tipo antes do `.get("confirmed")`; docstring
  ganhou a nota da correção v1.2.1.

TESTE DO TESTE (reprodução da assinatura exata do journal):
- `tests/test_launcher_vision.py` (novo, 4 testes): bus real + detector fake.
- Com o handler ANTIGO restaurado, os 4 testes FALHAM e imprimem exatamente as
  linhas do journal (Handler error 1/3, 2/3, 3/3 com AttributeError + dead
  letter). Com a correção: 4 passed.
- Suíte completa: **1651 passed, 16 skipped** (1647 + 4 novos).

=== ACHADO 2 — SelfRepair no_fix em agent.py · JÁ CESSOU · AMPLIFICAÇÃO SEGUE ===

O sintoma NÃO está acontecendo agora (evidência, não dedução):
- Último `SelfRepair no_fix` / snapshot: **2026-09-13 15:42:16**.
- O loop está VIVO: o audit registra `perception.snapshot` a cada ~5min, os
  três últimos às **13:06:11, 13:11:12 e 13:16:16 de HOJE (09-14)**;
  `/health` → check "perception" ok=true, "0 erros de sonda".
- `agent.py` (raiz) **foi substituído hoje às 02:17:47** por uma versão
  válida: `ast.parse` → OK. O `.bak` de 15:42 (13.217 B) ainda tinha o erro de
  sintaxe na linha 325 (`system_prompt = f"""`); o arquivo atual (12.809 B) é
  outra versão ("OmegaDrakon Agent - Versão estável") — 408 linhas de diff.
  Ou seja: o no_fix parou porque a origem (arquivo quebrado) deixou de existir.

CAUSA RAIZ do ruído (1.578 linhas de journal em ~2 dias):
- `core/recovery.py::iter_py_files` varre TODO .py do root fora dos diretórios
  excluídos — arquivos soltos na raiz entram no escopo. `agent.py` é o
  primeiro em ordem alfabética e é o par local do `sandbox_agent/` (declarado
  pelo usuário como "não é o sistema" e agora ignorado no git).
- Cada tick: `detect` acha o erro de sintaxe → `repair` (max_repairs_per_tick
  = 3) → `_take_snapshot` escreve um .bak novo com carimbo de tempo →
  nenhuma estratégia determinística resolve → `no_fix`.

AMPLIFICAÇÃO QUE PERMANECE (defeito latente):
- `.od_repair_backups/`: **557 arquivos, 8,8 MB, TODOS do mesmo digest
  (c3aa9f218ecd)** — um snapshot por tick, sem retenção/dedup. Enquanto o
  arquivo estava quebrado, cresceu ~13 KB a cada 5 min, indefinidamente.
- O laço continua gastando as 3 vagas de reparo do tick em arquivos alheios ao
  sistema quando algum deles volta a quebrar.

Nada foi alterado por causa do achado 2 — decisão pendente do usuário sobre
como tratar a amplificação (dedup/retenção de snapshots x escopo da varredura).

Rodada 2 (decisões do usuário): dedup + retenção de snapshots, e restart do od-core

Autorizado: (1) tratar a amplificação com dedup + retenção de snapshots
(sem mexer no escopo da varredura); (2) reiniciar o od-core para o fix do
face.presence entrar no ar.

=== CORREÇÃO NO SELF REPAIR (core/self_repair.py) — v1.2.1 ===

- Novo parâmetro `max_snapshots_per_file` (default
  `DEFAULT_MAX_SNAPSHOTS_PER_FILE = 5`).
- `_take_snapshot`: DELEGOU o nome ao novo `_next_snapshot_path` e agora
  (a) DEDUP — se já existe snapshot com os MESMOS bytes, ele é reutilizado
  (nenhum arquivo novo), via `_find_identical_snapshot`; (b) RETENÇÃO — após
  criar, `_prune_snapshots` mantém no máximo N por arquivo (por digest),
  nunca removendo o snapshot atual.
- Bug colateral corrigido no caminho: o nome usava `int(time.time())`, então
dois ciclos do MESMO arquivo no mesmo segundo gravavam o mesmo nome e o
snapshot anterior era SOBRESCRITO. `_next_snapshot_path` agora avança o
carimbo até o nome estar livre (o formato dos arquivos não mudou).
- `dump()` passou a expor `max_snapshots_per_file`.

Testes (tests/test_self_repair.py, classe `TestSnapshotDedupERetencao`, 4 novos):
- 5 ciclos com conteúdo inalterado reutilizam UM snapshot;
- conteúdo novo ainda gera snapshot novo (dedup só vale para bytes idênticos);
- retenção com cap=2 corta o excedente e o snapshot mais recente é o estado
  atual do arquivo;
- cap=0 é normalizado para 1.
TESTE DO TESTE: com o comportamento anterior restaurado (sem dedup, sem
retenção, sem bump de colisão), os 4 testes FALHAM; com a correção, os 4
passam. Suíte completa: **1655 passed, 16 skipped** (1647 + 8 novos).

LIMPEZA RETROATIVA (autorizada pelo item "mata o crescimento de 8,8 MB"):
os 557 snapshots foram conferidos antes — 3 conteúdos distintos (9.929,
13.217 e 13.228 B). Aplicado o próprio `_prune_snapshots` do engine
(digest c3aa9f218ecd, keep = o mais novo): **removidos 552, mantidos os 5 mais
novos** → `.od_repair_backups/` de **8,8 MB → 116 KB**. O mais novo (15:42 de
13/09) preserva a possibilidade de restaurar o estado anterior ao arquivo ser
trocado.

=== DEPLOY DO FIX DO FACE.PRESENCE + VERIFICAÇÃO AO VIVO ===

- `systemctl --user restart od-core` → **active desde 2026-09-14 13:24:40**
  (PID 264390); journal: Push FCM (enabled=False), RecoveryLoop,
  ProactiveNotifier, Presence Monitor e Face Detector todos habilitados.
- `/health` → ok=true, 8 checks.
- **PROVA AO VIVO**: às **13:25:09** o detector publicou um `face.presence`
  real ("Event published | topic=face.presence | subscribers=1") e, depois
dele, **NÃO há nenhuma linha de "Handler error" nem "dead letter"** — antes
da correção, TODO face.presence gerava 3 WARN + 1 CRIT. O handler corrigido
rodou limpo no processo em produção.
- RecoveryLoop pós-restart: "iniciando ciclo periódico | interval_s=300.0",
  nenhum snapshot/self-repair (nenhuma detecção — agent.py saudável).

Rodada 3 (autorizada): commit + push das duas correções

- Revisão antes de commitar: `git diff` dos quatro arquivos de código/teste +
  `git log` para seguir o estilo do repo.
- Ajuste de consistência de versão: as notas de código/teste diziam
  "v1.2.1", mas `OD_VERSION` segue **1.2.0** — troquei por **(2026-09-14)**
  (launcher, self_repair, os dois arquivos de teste) e registrei no
  `docs/CHANGELOG.md` como **"### Corrigido (2026-09-14)"** dentro da seção
  [1.2.0], em vez de inventar uma versão sem o bump correspondente.
- `docs/CHANGELOG.md`: nova subseção com o diagnóstico, a correção, a
  evidência de produção e a limpeza retroativa dos snapshots; cabeçalho da
  [1.2.0] atualizado para "correções em 2026-09-12 e 2026-09-14".
- Verificação: suíte completa **1655 passed, 16 skipped**; varredura do staged
  por `AIza`/`PRIVATE KEY`/`api_key`/`password`/`secret` sem ocorrências.
- **Commit `40d2bb0`** — _fix(core): corrige o handler de face.presence e
  limita snapshots do SelfRepair_ (7 arquivos, +603/-19).
- **Push**: `origin/master 8455493..40d2bb0`.

Estado final da sessão: as duas correções estão no ar E publicadas; o
checkpoint desta sessão foi atualizado com o hash (commit de docs separado,
como nas entregas anteriores).
