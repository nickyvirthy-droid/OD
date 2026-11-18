# Conversa OmegaDrakon — 18/11/2026

Sessão entre o dono e o assistante. Registro a cada troca (regra 4 de
`iniciar/RULES.md`). Continuação de `2026-11-17_conversa_omegadrakon.md`.

---

## §1 — Retomada "leia iniciar": estado do repositório e lote da madrugada feito por outra ferramenta

**Pedido (verbatim):** `leia iniciar`

### 1. O que foi lido (regra 3)

- `iniciar/README.md`, `iniciar/RULES.md` (23 regras), `iniciar/ATRIBUICOES.md`
  (topo: revisão do TODO de 17/11, curadoria no app 1.46.0, tradução de letra,
  curiosidade, P0 do cache).
- `iniciar/session.json` — última entrada: `cache_conversa_p0_2026_11_17`
  (linha 6163; nenhuma entrada de 18/11 até esta troca).
- Transcrição de 17/11 (§14–§19: curiosidade no `/radio-pro`, letra com
  tradução paralela, curadoria no app, revisão do TODO, P0 do `llm_cache`).
- `txt.txt` (66 linhas) e `git status`/`log` + serviço + `/health`.

### 2. Estado encontrado (18/11 09:33, medido)

- **Serviço:** `od-core` **active**, MainPID **3303767**, NRestarts=0, ativo
  desde **17/11 21:15:18** (restart verde do P0 do cache). `/health` →
  `ok=true`, **30 checks**, `llm: 3 providers (groq, gemini, gemma-local)`,
  `database: 14 tabelas`.
- **Git:** `HEAD == origin/master == 4a5a785`.
- **Versão:** **1.46.0+2083** (release de 17/11).
- **TODO:** **33 abertas / 79 fechadas** (`docs/ANALISE_SISTEMA_TODO.md`);
  priorização P0–P3 na seção "Revisão de 17/11/2026" §2.
- **`txt.txt`:** os 6 pedidos das linhas 1–67 já foram respondidos — lista do
  Raul Seixas (bug `link_do_youtube` corrigido em 17/11), exclusão de músicas,
  exceções de cantores, análise do GSN Offline e dos 2 vídeos, curiosidade e
  tradução de letra (entregues na §14/§15 de 17/11). **Nenhum pedido novo**
  do dono no `txt.txt`.

### 3. Achado principal: OUTRA ferramenta trabalhou hoje de manhã (09:08–09:15)

Sete commits de autor **"Nicky Virthy"** com mensagem `implementa: ideia
default` (18/11 09:08 → 09:15), **já em `origin/master`**. A ferramenta é o
**Cline**: existem refs locais `refs/cline/checkpoints/…` com a última
checkpoint `ed53ab4` às **09:29** (fora de `master` — só checkpoint, não
commit publicado). Nenhuma entrada dela no `iniciar/` (registro completado
neste turno, regra 23).

O que o lote contém (medido via `git show --stat`):

1. **`tools/od.sh` (novo, 497 linhas)** — `~/bin/od` vira menu de CLIs
   (antes `tools/oc.sh`/`oc`): 14/14 CLIs instaladas (OpenCode 2.3.2
   reinstalado com postinstall, Claude Code 2.1.327, Codex, Gemini, Qwen,
   Crush, Cline…), Node 22.23.5 por usuário em `~/.local/opt/node`,
   OpenClaude Portable com NVIDIA_API_KEY, cada CLI em janela tmux própria.
   Doc novo `docs/OD_MENU_CLIS.md` (+134) e entrada no `docs/CHANGELOG.md`
   (script 1.2.0, sem bump).
2. **`orquestrador.py` (raiz, refatorado: ±2290 linhas, hoje com 1258)** —
   orquestrador de fallback de geração de código, modo `--sessao` (lê ideia
   do `txt.txt`, cadeia OpenCode → Kilo, valida sintaxe por AST, commita e
   notifica por Telegram); o modo fila `pedido.txt` segue recusado (removido
   a pedido do dono em 08/10). `teste_orquestrador.py` **novo** (158 linhas).
3. **`core/orchestrator.py`** — **removeu** `_CACHE_BAN_VERIFICACAO_FALSA`
   (a regra que bania "Estado verificado." escrita na noite de 17/11): no
   código ela ainda existia embora a §19 já registrasse a retirada — o lote
   de hoje **alinhou código e registro** (transcrição §19, `session.json` e
   `ATRIBUICOES.md` corrigidos no mesmo commit). Banem-se agora só o conteúdo
   sem fonte e os avisos do turno.
4. **`docs/`** — TODO: checkbox do `_FAKE_ACTION_RES` (falso sucesso de
   ação fora de agenda) e do descarte do "não cachear modelo local"; correções
   de texto do P0. `docs/IAS_DISPONIVEIS.md` +30.
5. **`.gitignore`** — `/pedido.txt` (fila removida).
6. **7 arquivos `gerado_*.py` commitados** (1 linha: `pronto`) e **130
   `gerado_*.py` untracked** na raiz (marcadores de sinalização da
   automação; criados hoje ~09:08–09:29).

### 4. Gate completo VERMELHO — e a causa raiz (diagnóstico com bissect)

O gate completo (`python3 -m pytest -q`) falhou **80 failed / 5302 passed /
19 skipped** — e falhou **idêntico** nas duas rodadas (arquivos de falha
byte a byte iguais, `diff` = 0). Pistas que fecharam o diagnóstico:

1. **Só no gate, nunca isolado:** cada arquivo de teste (e cada subconjunto
   dos que falham) passava sozinho; `tests/test_[a-d]* + test_eval.py` e
   `--ignore-glob='tests/test_[o-z]*'` passavam. Bissect progressivo
   (a-d → o-z → test_o* → um por um) apontou o gatilho: a presença de
   **`tests/test_orquestrador.py`** na coleta.
2. **Mecanismo provado:** o refactor do Cline moveu `load_dotenv()` do
   corpo de `main()` (linha 1447, versão de 17/11) para o **nível de
   módulo (linha 53)** do `orquestrador.py`. `tests/test_orquestrador.py`
   importa o módulo — então a **coleta da suíte** derrava o `.env` inteiro
   no `os.environ` global: **56 chaves** (`OD_CHAT_PROVIDERS`, `GROQ_API_KEY`,
   `OD_DB_URL`…) **antes do primeiro teste rodar**. Prova direta: script
   `import orquestrador` contando chaves novas no ambiente = 56. A própria
   fixture do teste (`_sem_dotenv_real`) documenta o perigo, mas ela só
   protege a chamada de `main()`, não o import.
3. **Efeito:** variáveis de rota mudavam para os testes seguintes —
   `test_eval` (modo oracle 9/13 em vez de 13/13), `test_eval_oracle`,
   `test_intents` (fastpath de matemática caindo em `route=llm`),
   `test_llm`, `test_orchestrator`, `test_resposta_transparente` (40) e
   `test_websocket`. Os WARNs `Query Router prediction failed | X has 101
   features, but StandardScaler expecting 485` acompanhavam o desvio.

### 5. Duas quebras do mesmo refactor — e o conserto

**(a) Vazamento do `.env` (causa das 80):** `load_dotenv()` removido do
nível de módulo e restaurado **dentro de `main()`**, com comentário no
código explicando o porquê (contrato da versão de 17/11). Verificação:
`import orquestrador` → **0 chaves vazadas**; os 536 testes das 8 classes
afetadas, rodados **juntos**, → **536 passed**.

**(b) Refactor do `orquestrador.py` quebrou o contrato (26 testes):**
comparação medida contra `96040ba` (ontem):

- assinaturas mudadas (`aguardar_resposta_dono(ja_ditadas, caminho, …)` →
  `(timeout_s, caixa, …)` = `TypeError: got multiple values`);
- **removidas** 10 funções usadas pelo modo sessão (`ler_caixa`,
  `gravar_caixa`, `_marcar_respondidas`, `_batimento`, `_matar_grupo`,
  `_encerrar`, `_agora_iso`, `_gravar_json`, `gravar_estado`,
  `_arquivos_do_porcelain`);
- **adicionadas** funções do modo fila (`_loop_fila`,
  `read_and_clear_pedido`, `save_generated_code`) que o **próprio docstring
  novo declara removido** — incoerência interna do refactor;
- sem entrada no `docs/CHANGELOG.md` nem no `iniciar/` (não foi entrega
  formal).

**Decisão:** reverter `orquestrador.py` para a versão de `96040ba`
(`git checkout 96040ba -- orquestrador.py`) — a versão de ontem é
autoconsistente, tem o gate verde de 17/11 e o contrato dos 26 testes
íntegro. O refactor do Cline é registrado no livro-caixa como origem
identificada e trabalho pela metade (regra 23), não apagado por conta
própria das entregas dele que ficam (`tools/od.sh`, docs).

### 6. Resíduos do lote, catalogados (nada apagado — regra 7)

- **171 arquivos `gerado_*.py`** na raiz + **`teste_orquestrador.py`
  (raiz)** (158 linhas, 0 `test_*`) — **LIMPOS em 18/11 ~10:50 com ordem
  do dono** ("encerrou por falta de crédito, cota diária acabou"). Medição
  prévia: só marcadores `pronto`/`[AUTORIZACAO]` (47+47+72…), gerados
  09:08–10:30; 7 `gerado_*` commitados (`git rm`) + 164 não-rastreados
  (`rm`). Pós-limpeza: **0 não-rastreados**, gate completo **5382 passed /
  19 skipped / 0 falha**. Checkbox do TODO §4 marcado `[x]`.

### 7. Validação final

- **Gate completo após o conserto: 5382 passed / 19 skipped / 0 falha**
  (212,33 s, `python3 -m pytest -q`) — contra 80 failed / 5302 passed do
  gate da abertura do turno.
- Verificação unitária do conserto: `import orquestrador` → 0 chaves
  vazadas no ambiente; as 8 classes de teste afetadas rodadas juntas →
  536 passed.
- Nenhum outro código alterado; sem bump (**1.46.0+2083**).

### 8. Decisão

O turno virou fechamento de ciclo (regras 7.1/7.2/13): o lote da outra
ferramenta estava publicado com o gate vermelho — causa raiz provada,
corrigida no menor ponto possível e validada. Registro completo nos três
lugares (`session.json`, esta transcrição, `ATRIBUICOES.md`).

### 9. Publicação e restart verde (regras 7.1 / 7.3)

- **Commits em `origin/master`:** `2775d3b` (fix: `orquestrador.py` de
  volta à versão de 17/11) e `4648271` (docs do `iniciar/` + TODO).
  `git status -sb`: `master...origin/master`, sem divergência.
- **Restart autorizado pelo 7.3** (gate verde 5382/19/0 + HEAD ==
  origin/master + sem resíduos das minhas mudanças) — necessário porque o
  serviço rodava desde 17/11 21:15 e o código publicado hoje traz a
  retirada da regra `_CACHE_BAN_VERIFICACAO_FALSA` do `core/orchestrator.py`
  (ainda não no ar).
- **Prova viva:** `systemctl --user restart od-core` → **MainPID 4133749,
  NRestarts=0**, ativo desde **10:37:13**; `journalctl -p err` desde o
  restart → **0 entradas**; boot limpo (`Orchestrator real montado |
  llm=['groq','gemini','gemma-local']`, `API REST no ar`, `semantic_cache=
  desligado`); `/health` → **ok=true, 30 checks, 0 não-up** (o check `mqtt`
  apareceu não-up nos primeiros segundos pós-restart e reconectou sozinho
  — releitura 8 s depois: 30/30 up).
- **Telegram do dono** enviado (regra 15): resumo da conclusão.
- **Sem bump:** 1.46.0+2083 (ferramenta de dev + correção de servidor;
  contrato do app intacto).

---

## §2 — Cascata do orquestrador: 2 → 10 IAs (ordem do dono)

**Pedido do dono (18/11 ~13:50):** *"acho que a função que estava sendo
implementada no orquestrador é a utilização de todas as 14 IAs e não apenas
as três atuais"* → depois, confirmação: *"Sim: expandir a cascata"*.

### 1. O que a medição mostrou da hipótese

- **Duas camadas distintas:** os "3 atuais" são os **providers de LLM do
  chat** (`OD_CHAT_PROVIDERS=groq,gemini,local`); as "14 IAs" são as
  **CLIs de código** do inventário. O refactor da madrugada (que reverti)
  **não** expandiu nada — a `CLIS` dele media exatamente **2** (OpenCode,
  Kilo); as 14 só existiam no menu `od` + `docs/IAS_DISPONIVEIS.md`.
- **Obstáculo do próprio inventário:** "nenhuma pronta para lote" + cota
  diária de freebuff/kilo esgotada em 18/11 (foi o que matou o Cline).

### 2. Medição das 14 (só `--help`, sem gastar cota de ninguém)

| Entrou (10) | Flag não-interativo medida |
|---|---|
| OpenCode | `run --standalone --auto -m …` (já era da cascata) |
| Kilo | `run … --auto --pure` (já era da cascata) |
| Gemini | `gemini -p PROMPT -y` (`-p` = headless, `-y` = yolo) |
| Qwen | `qwen PROMPT -y` (posicional = one-shot) |
| Claude | `claude -p PROMPT --dangerously-skip-permissions` |
| Crush | `crush run PROMPT -y` ("Run non-interactively") |
| Agy | `agy -p PROMPT --dangerously-skip-permissions` |
| OpenClaw | `openclaw agent -m PROMPT --json` |
| Codex | `codex exec -s workspace-write --approve-for-me PROMPT` |
| Aider | `aider -m PROMPT --yes-always --no-auto-commit` |

**Ficaram de FORA (4), com motivo medido:** **freebuff** (só
`login`/`doctor`), **cline** (só TUI/ACP — cota esgotada 18/11),
**openclaude** (`start.sh` é launcher de menu) e **interpreter** (só
TUI/`--server`/`--stdin` — sem one-shot).

### 3. Achado extra: a primeira da cascata estava morta

`opencode/nemotron-3-ultra-free` (o modelo do `orquestrador.py` desde
sempre) **não existe mais** no catálogo — `opencode models` medido em
18/11 mostra só `nemotron-3.5-*`; o `qwen3-coder:free` do refactor
revertido também sumiu. Trocado por **`opencode/deepseek-v4.1-flash-free`**,
provado com prompt real (respondeu `OK`, exit=0).

### 4. Arquivos alterados

- `orquestrador.py` — `CLIS` 2→10 (com a medição em comentário), modelo do
  OpenCode, `CLI_SESSAO_OPCOES` 2→10, help do `--cli`.
- `integrations/api/server.py` — `SESSAO_CLIS` 2→10 (painel).
- `tests/test_orquestrador.py` — contrato atualizado + 2 testes novos
  (flags headless de cada CLI; exclusão das 4 só-TUI; seletor × servidor).
- `docs/CHANGELOG.md` — entrada "Cascata do orquestrador: 2 → 10 IAs".
- `docs/IAS_DISPONIVEIS.md` — conclusão das 14 + linha no histórico.

### 5. Validação (regra 13)

- `tests/test_orquestrador.py` → **114 passed**; `test_api.py -k sessao`
  → **21 passed**.
- **Gate completo: 5384 passed / 19 skipped / 0 falha** (213 s).
- Comando seco de todas as 10 impresso e conferido (prompt no lugar certo
  em cada uma).
- **Sem bump:** 1.46.0+2083 (ferramenta de canal de dev; contrato do app
  intacto).
- **Restart do `od-core` pendente de autorização** (regra 7.1): o
  `SESSAO_CLIS` novo só vale para o painel depois do restart — gate verde
  e `HEAD == origin/master` já são a condição 7.3.

---

## §3 — Query Router: 101 × 485 features consertado

**Continuação do serviço (18/11 ~14:30)** — o dono escolheu "Voltar ao
Query Router" depois de autorizar o restart da cascata.

### 1. Diagnóstico (com a medição certa desta vez)

O aviso `X has 101 features, but StandardScaler is expecting 485` **não
aparece no journal da produção** (0 ocorrências hoje): ele era da
**suíte**. A raiz é o **ambiente**:

| Ambiente | `sentence-transformers` | embedding | vetor × modelo |
|---|---|---|---|
| Serviço (`.venv`, 6.3.0) | tem | 384 | **485 = 485** ✓ |
| Suíte (`python3` do sistema) | **não tem** | `None` | **101 ≠ 485** → erro em toda chamada → fallback |

Ou seja: na suíte o router **nunca classificava** (sempre fallback) e
enchia o log de warning; na produção funcionava por sorte do `.venv`.

### 2. Conserto

- `core/query_router.py` — `_harmonizar_dimensao()`: se o vetor é menor
  que o esperado, completa a **cauda do embedding** com a **média de
  treino do `StandardScaler`** (entrada neutra → 0 após o scaler); se é
  maior, fallback com **um único** aviso (`_dim_aviso`). Antes do
  `predict`, em `classify`.
- `tests/test_query_router.py` — regressão: classifica com
  `use_embeddings=False` e prova que o `predict` rodou.

### 3. Validação (regra 13)

- `test_query_router.py` → **20 passed**.
- Prova real no `python3` do sistema com o modelo de produção:
  `recebido=101 | esperado=485 | completado_por=media_de_treino` (uma vez
  só) e classificações **`direct`/`tool`/`hybrid`** (antes: fallback
  sempre).
- **Gate completo: 5385 passed / 19 skipped / 0 falha** (213 s).
- **Sem bump:** 1.46.0+2083. Entrará no ar no próximo restart do
  `od-core` (o de 12:53 antecedeu este fix; a produção já se comporta
  igual com o código antigo — o fix é para ambientes sem o pacote).

## §4 — Playlist do Raul Seixas (txt.txt): download em unidade própria + fix do cgroup

**Pedido do dono (18/11, tarde):** o `txt.txt` traz o link da playlist do
Raul Seixas. Dono autorizou "Sim, baixar agora" e, em seguida, "Conserta
agora também" — o bug que mata download em voo.

### Diagnóstico (reabrindo o pedido 12 de 17/11)

- O worker morreu às 03:36:51 quando o od-core parou: com
  `start_new_session` o processo sai do grupo, mas **não sai do cgroup** —
  o `kill` do systemd levou o `yt-dlp` no meio da espera de 3 min entre
  lotes.
- 6 mp3s já baixados ficaram presos em `/tmp/od_link_x6q62edm/`.
- A playlist tem **190 entradas** (a extração de 17/11 só tinha detectado 10).

### Conserto (cgroup — regra 7.1 respeitada: nada foi reiniciado)

- `integrations/radio_link.py` — `_unit_transitoria()`: o worker roda em
  unidade transitória `systemd-run --user --unit=od-radio-link-<id>`
  (Type=exec, WorkingDirectory, EnvironmentFile=.env, stdout/stderr em
  append, `--collect`). O processo nasce como **irmão** do od-core em
  `app.slice` (prova: probe `od-probe-cgroup.service`) — restart do
  od-core não alcança mais quem está baixando.
- Fallback preservado: sem `systemd-run` ou recusando, cai no `Popen` +
  `start_new_session` antigo; `unit=""` desliga a unidade.
- Download lanchado como `od-radio-lista-raul.service` (unidade própria,
  log `logs/radio_link_lista_raul_seixas.log`) — **não depende do
  od-core**.

### Tool generalizado

- `tools/baixar_resto_lista.py`: `OD_LISTA_URL`, `OD_LISTA_NOME`,
  `OD_LISTA_LOG` (slug default) — mesma tool para QUALQUER playlist.
- `tests/test_tools_diversos_cobertura.py` atualizado + teste novo
  (`test_nome_da_lista_e_configuravel`) → **37 passed**.

### Acidente de qualidade: Metamorfose Ambulante entrou duplicada

- **Causa:** a playlist veio só com "Metamorfose Ambulante" e o acervo
  tinha "Raul Seixas - Metamorfose Ambulante" — `_parece_repetida` só
  testava o sentido "artista+título do acervo ∈ título da lista"; o
  contrário passava reto. Depois o pipeline renomeou para "Desconhecido -
  …" (detecção de artista falhou) e o dedupe por artista+título não casou
  → 2ª linha no acervo (MPB).
- **Limpeza:** linha 789 removida do `acervo.db`; arquivo movido para
  `revisar/duplicadas/Desconhecido - Metamorfose Ambulante (duplicada
  18-11).mp3` (acervo 364 → 363, uma linha só para a música).
- **Endurecimento:** `_parece_repetida` ganhou o sentido contrário —
  casa o TÍTULO sozinho (igualdade exata, ou contido com 2+ palavras;
  palavra solta só por igualdade, anti-falso-positivo). Teste novo em
  `tests/test_radio_cobertura.py`.

### Validação e progresso

- radio_link + tools + cobertura: **336 passed** (bloco alvo da §5).
- Lote 1 fechou **+10** (354 → 364, log "lote 1 codigo=0"); lote 2
  rodando desde 14:23; unidade `od-radio-lista-raul` **active**.
- 190 faixas ≈ 19 lotes ≈ 10–13 h; disco 760 G livres.

## §5 — Régua do dono: cota NUNCA é motivo de exclusão — cascata 10 → 13

**Pedido do dono (18/11):** "você retirou o cline do orquestrador pelo
motivo de cota e TUI, não sei o que quer dizer com tui, mas cota volta no
outro dia, então cota nunca é motivo de exclusão, a cota sempre acaba por
isso esse número grande de IAs."

- **TUI explicada ao dono:** *Terminal User Interface* — modo interativo
  que precisa de alguém respondendo prompt; a sessão desanexada não
  responde. Não é defeito, é modo de uso: o que importa é existir (ou não)
  modo **não-interativo**.
- **Nova régua aplicada:** só a falta de modo não-interativo exclui.
  Cota esgota e volta (~18 h) — por isso existe o número grande de IAs.

### Re-mediação das 4 excluídas (ajuda + prompt real, 18/11)

| CLI | Prova | Resultado |
|---|---|---|
| cline 3.0.74 | `cline "prompt" --json` (posicional = one-shot, auto-approve default true) | agente inicia e sai com **exit=1** no 429 da cota ("18h 46m") — fail-fast, a cascata segue |
| interpreter 0.4.3 | `--stdin -y -pl` (prompt no stdin) | **exit=1** — OpenAI sem crédito (igual codex/aider) |
| openclaude 0.32.0 | engine `@gitlawb/openclaude` `-p --yolo --provider nvidia-nim` | **exit=0**, "ok" em 3,5 s; depois **criou arquivo real** com `--yolo` (3 turns). Modelo do app (`deepseek-v3.1-terminus`) está **EOL no NIM** (404) → usar `nvidia/nemotron-3-ultra-550b` (200 em 0,9 s) |
| freebuff 0.2.36 | `--help` + stdin pipeado | só `login`/`doctor`; stdin sobe a TUI e sai sem processar → **única que continua FORA, e por MODO** |

### Implementação

- `orquestrador.py`: campo novo `CliSpec.prompt_via_stdin` + `executar_cli`
  manda o prompt por `communicate(input=…)` quando pedido; `CLIS`
  **10 → 13** (Cline, OpenClaude, Interpreter — nesta ordem, depois do
  Aider); bloco de política reescrito com a régua do dono;
  `CLI_SESSAO_OPCOES` 10 → 13.
- `tools/openclaude_headless.sh` (novo, +x): aplica o perfil portátil do
  OpenClaude-Portable (`ai_settings.env`, `CLAUDE_CONFIG_DIR`, exports do
  `start.sh`) e executa a engine — o `start.sh` é menu e não aceita
  prompt.
- `integrations/api/server.py`: `SESSAO_CLIS` 10 → 13 (contrato do
  painel).
- `docs/IAS_DISPONIVEIS.md`: conclusão **13/14**; cota removida como
  motivo de exclusão (freebuff passa a ser a única fora **por modo**);
  histórico com a 2ª leva; linhas das 3 CLIs atualizadas.

### Validação (regra 13)

- `test_orquestrador.py + test_api.py`: **318 passed**.
- Bloco alvo (orquestrador + radio + tools): **336 passed**.
- **Gate completo: 5392 passed / 19 skipped / 0 falha** (223 s).
- Prova viva do caminho completo: `executar_cli(OpenClaude)` →
  `SAIDA: ok`.
- **Sem bump:** 1.46.0+2083. Entra no ar no próximo restart do `od-core`
  (**autorização do dono pendente** — regra 7.1).

---

## §6 — Retomada "leia iniciar" (15:50): o que está no ar, o que está baixando e o lote órfão do `orquestrador.py`

**Pedido (verbatim):** `leia iniciar`

### 1. O que foi lido (regra 3)

`iniciar/README.md`, `RULES.md` (23 regras), `ATRIBUICOES.md` (topo),
`session.json` (última entrada `cascata_13_cota_nunca_exclui_2026_11_18`),
transcrição de 18/11 (§1–§5), `txt.txt`, `git status/log/diff`,
`systemctl --user status od-core`, `/health` e a unidade do download.

### 2. Estado medido (18/11 15:50)

| Item | Medição |
|---|---|
| Git | `HEAD == origin/master == c4943e2` (14:56:55) |
| Versão | **1.46.0+2083** |
| `od-core` | **active**, MainPID **220986**, NRestarts=0, desde **15:01:19** |
| `/health` | `ok=true`, **30/30** checks up |
| TODO | 33 abertas / 79 fechadas |

### 3. O restart "pendente" do checkpoint JÁ ACONTECEU (não registrado)

O checkpoint anterior (15:05) dava o restart como pendente de autorização.
Medição: o serviço foi reiniciado às **15:01:19** — PID **220986**, contra
**83842** do restart registrado das 12:53 — **depois** dos commits
`adadacb`/`8efdbb0`/`c4943e2` (14:56:55) e de `fd5801e` (13:06).

Consequência medida: **cascata de 13 CLIs**, **fix do cgroup do
`radio_link`** e **harmonização 101×485 do Query Router** já estão no ar.
Quem reiniciou não deixou registro — **origem não identificada** (regra 23).

### 4. Lote órfão na árvore: `orquestrador.py` regredido + `soma.py`

**Outra ferramenta** mexeu na árvore depois do checkpoint:

- `orquestrador.py` — **modificado às 15:19:11**: de 1654 → **251 linhas**,
  virou o orquestrador de **fila** (`pedido.txt`, cascata
  Freebuff → OpenCode → Kilo) que o próprio docstring do repo declara
  **removido em 08/10**; com `load_dotenv()` no **nível de módulo** (o
  defeito que o gate desta manhã consertou) e **sem** `CLIS` /
  `CLI_SESSAO_OPCOES`.
- **Dano provado:** `pytest tests/test_orquestrador.py` → **`ImportError:
  cannot import name 'CLIS'` na coleta**. Os 114 testes do contrato, o
  seletor do painel (`SESSAO_CLIS` 13) e a cascata de 13 ficam **sem par**.
- `soma.py` — não rastreado, 32 B (`def soma(a, b)`), criado 15:23:47.
- **Autor: origem não identificada** (nada em `iniciar/`, nada no
  CHANGELOG). **Não revertido** — derrubar trabalho de terceiro é ação
  destrutiva e exige ordem do dono (regra 7).

### 5. Playlist do Raul Seixas: onde está (resposta ao `txt.txt`)

O `txt.txt` desta tarde pergunta *"onde foi parar a lista de músicas do
raul seixas"*. Medido, não presumido:

- Unidade **`od-radio-lista-raul.service`**: **active (running)** desde
  **13:50:11** (transient, MainPID 142554, ~303 MB) — roda **fora** do
  cgroup do `od-core`.
- **Lote 3 fechou 15:25:09**: acervo **382** faixas (+10 no lote; **+28**
  desde as 354 do início).
- **Lote 4 de ~19 em andamento** (faixas 31-40; 9/10 às 15:50, com a espera
  de 3 min entre lotes). Ritmo medido ≈ 30 min/lote → ~7–8 h restantes.
- A unidade **sobreviveu** ao restart do `od-core` das 15:01 — o fix do
  cgroup está provado em produção, não só em teste.

### 6. Nesta troca

Nenhum código alterado: leitura, medição e registro (`session.json`,
esta transcrição, `ATRIBUICOES.md`, checkboxes no TODO §4). **Sem bump**
(1.46.0+2083). O lote órfão continua na árvore aguardando decisão do dono.

---

## §7 — "faça" + convivência multi-IA: lote órfão revertido, corpus real e cascata até concluir

**Pedido 1 (verbatim):** `faça` — executar a próxima melhoria recomendada
(P0 nº 2: corpus de frases reais do dono como teste de intenção).
**Pedido 2 (verbatim, chegou durante o trabalho):** *"agora temos um número
muito grande de IAs trabalhando sobre OD. garanta que todas prossigam dentro
da mesma linha sem destruir o que existe e mantendo a coerência e melhoria do
projeto, mesmo que uma pare no meio do caminho por cota ou outra razão a
próxima deve prosseguir e assim sucessivamente até concluir"*.

### 1. Lote órfão revertido (com a ordem do dono no "faça")

`git checkout -- orquestrador.py` + `rm soma.py` — a árvore voltou a
**1654 linhas** e `tests/test_orquestrador.py` a **116 passed** (antes:
`ImportError: cannot import name 'CLIS'` na coleta). Nada de terceiro foi
perdido: o conteúdo regredido está no histórico do git do próprio dia.

### 2. P0 nº 2 — corpus de frases reais (`tests/test_corpus_frases_dono.py`)

**32 testes.** 13 frases **verbatim** do dono, cada uma com o arquivo de
`iniciar/` onde está registrada — e o próprio teste confere que a frase
**existe mesmo** naquele arquivo (o corpus não pode virar invenção):

| Frase real | Ação esperada |
|---|---|
| "qual o uso de disco" | `disk_usage` |
| "quais os tipos de usuários de OD" | `role_list` |
| "quais portas estão abertas?" | `listening_ports` |
| "qual o ip do servidor?" | `ip_address` |
| "temperatura do servidor" | `cpu_temp` |
| "quanto esta o dolar hoje" / "quanto está o dólar" | `exchange_rate` (+`moeda`) |
| "clima em campo grande hoje" / "temperatura em são paulo" | `weather_city` (+`city`) |
| "quais tomadas estão ligadas" | `ha_lights` |
| "aumenta o volume" / "abaixa o volume" | `radio_volume` (+`volume`) |
| "para a rádio" | `radio_stop` |

Negativas (o fast path **não** pode sequestrar): "bom dia" e "onde foi parar
a lista de musicas do raul seixas". Mais `datetime` ("que horas são" →
"Agora são …"; "bom dia" → `None`), que mora em outra etapa do pipeline e
não é buraco de intenção.

### 3. P0 nº 3 — convivência multi-IA (o pedido 2)

**Diagnóstico do dia:** o problema não era falta de IA — era falta de
**estado comum e trava**. A mesma árvore recebeu, em 10 h, três lotes de
autores diferentes, um deles regredindo um arquivo de 1654 linhas sem
registro. A cascata de 13 CLIs já existia, mas: (a) nenhuma CLI recebia o
checkpoint nem as regras (só a ideia); (b) gate vermelho **encerrava** a
sessão em vez de passar para a próxima; (c) nada impedia reescrita maciça.

Implementado (tudo com teste):

- **`tools/brief_multi_ia.py`** (novo) — brief único do estado real: versão,
  `HEAD` × `origin/master`, árvore suja, checkpoint vigente (o mais recente
  **com retrato de turno**, não uma nota de recomendação), últimas atribuições,
  P0/P1 abertas e as 8 regras de convivência. `--json` para ferramentas.
  Medido: **2891 chars** (cabe num prompt gratuito).
- **`orquestrador.py`** — o brief entra no prompt de **toda** CLI;
  **trava anti-destruição** (`_reescritas_em_massa`: arquivo rastreado com
  >= 100 linhas que cai para menos de 30% → sessão falha como
  `arquivo_reescrito_em_massa` **sem commitar**, árvore preservada);
  **cascata até concluir** (gate vermelho não encerra: a próxima CLI recebe o
  resumo do vermelho + "preserve o que já existe e conserte a causa" e valida
  de novo, até concluir ou acabarem as CLIs); `_encerrar()` grava `detalhe` no
  estado.
- **`docs/PROTOCOLO_MULTI_IA.md`** (novo) — o contrato: entrar (brief),
  trabalhar (edição cirúrgica, atribuição no mesmo passo, validar antes de
  publicar), **sair mesmo por cota** (trabalho parcial na árvore + próximo
  passo exato) e como a cascata retoma.
- **`iniciar/RULES.md` — regra 24**, apontando para o protocolo.

### 4. Validação

- `tests/test_multi_ia.py` (novo, **11 testes**): brief do estado real,
  checkpoint no prompt, tool quebrada não derruba a sessão, reescrita maciça
  detectada em repo git temporário (300 → 3 linhas), edição normal não dispara,
  sessão falha **sem commitar**, gate vermelho passa para a CLI seguinte, CLI
  sem cota não consome a vez, histórico da falha chega na próxima.
- `test_multi_ia + test_orquestrador`: **127 passed**;
  `test_corpus_frases_dono`: **32 passed**.
- **GATE COMPLETO: 5435 passed / 19 skipped / 0 falha** (220,46 s) — contra
  5392 da abertura do turno (+43 = 32 do corpus + 11 do multi-IA).
- **Sem bump:** 1.46.0+2083 (ferramenta de dev + testes; contrato do app
  intacto). Nada de restart: o `od-core` não usa o orquestrador de CLIs.

---

## §8 — Trava no git, painel “IAs no projeto” e prova real da cascata

**Pedidos (verbatim, três sugestões clicadas):** *"Adicionar hook de pré-commit
com a trava de reescrita maciça, para valer também fora do orquestrador"* ·
*"Mostrar no painel o checkpoint vigente, a árvore suja e há quanto tempo
ninguém registra"* · *"Provar a cascata até concluir com duas CLIs reais em
sequência"*. **Pergunta junto:** *"como devo trabalhar dentro do orquestrador
para manter tudo organizado? é só escrever em txt e clicar em ativar dentro do
painel do app?"*.

### 1. Trava no git (hook pre-commit)

- **`tools/trava_reescrita.py`** (novo) — a régua virou **fonte única**:
  arquivo rastreado com >= 100 linhas que cai para menos de 30%; `--staged`
  (hook) e `--worktree` (orquestrador). `OD_TRAVA_LIMIAR`,
  `OD_TRAVA_MIN_LINHAS`, escape consciente `OD_TRAVA_OFF=1` /
  `git commit --no-verify` registrado na mensagem.
- **`tools/instalar_hooks.sh`** (novo, +x) — instala o hook com o **caminho
  absoluto** da ferramenta (funciona em clone/repo de teste; fallback
  relativo), preserva hook anterior e não quebra commit se faltar python3.
  **Instalado neste repositório.**
- O `orquestrador._reescritas_em_massa` passou a **delegar** na mesma régua -
  uma régua, dois pontos de guarda.
- **Prova:** `tests/test_trava_reescrita.py` (13) inclui **commit real** de
  300 → 1 linha **bloqueado** pelo hook e commit normal **passando**.

### 2. Painel “IAs no projeto”

- Rota **owner-only** `GET /admin/estado-ia` (ROUTES **138 → 139**) montada por
  `tools/brief_multi_ia.estado_para_painel()`.
- Seção nova no `/admin`: versão/`HEAD` × `origin`, **checkpoint vigente**,
  **árvore suja**, **idade do último registro** (acima de 6 h em vermelho —
  registro parado + árvore suja = lote órfão, como o de 15:19) e P0/P1
  abertas. `iaLoad()` entrou no `carregarTudo`.
- `node --check` no script do painel: **OK** (pegou dois `\n` literais antes de
  ir ao ar). `tests/test_api.py` **202 passed**.

### 3. Prova real da cascata (duas CLIs de verdade)

`executar_sessao` com `executar=executar_cli` real e as CLIs
**Interpreter → OpenClaude**:

| CLI | Resultado | Tempo |
|---|---|---|
| Interpreter | falhou (exit=1, sem saldo OpenAI) — fail-fast | **11,4 s** |
| OpenClaude (NIM) | respondeu `OK` | **9,4 s** |

Estado final: **`concluido / implantado`**, `cli_usada=OpenClaude`, **20,9 s**
no total, e a árvore **sem nenhuma alteração** feita pelas CLIs. É a
continuidade real: uma parou, a próxima concluiu.

### 4. Resposta ao dono (também no protocolo, §6.1)

Sim — o caminho normal é: **escrever o pedido no `txt.txt`** e clicar em
**▶ Ativar desenvolvimento** no `/admin`. O orquestrador lê o txt, injeta o
brief, roda as 13 CLIs, pausa na caixa quando precisa de `[AUTORIZACAO]`,
valida a suíte e commita (push do fecho é automático); o resumo chega no
Telegram. Nada de copiar texto, escolher IA ou commitar. O que continua sendo
decisão do dono: aprovar `[AUTORIZACAO]`, escolher prioridade e autorizar
deploy/restart/ação destrutiva. Para conferir sem ativar nada, a seção “IAs no
projeto” mostra o estado.

### 5. Validação

- `test_trava_reescrita.py` **13 passed**; `test_api.py` **202 passed**;
  `multi_ia + orquestrador + trava` **140 passed**.
- **GATE COMPLETO** (registrado no checkpoint com o número final).
- **Sem bump:** 1.46.0+2083. Restart do `od-core` pela regra 7.3 para a rota
  nova valer no painel (com prova viva).

---

## §9 — Medição: quanto do brief a CLI realmente usa

**Pedido (verbatim):** *"Medir quanto do brief a CLI realmente usa, comparando o
prompt com o diff produzido"*.

### Método (medido, não presumido)

Prompt **real** de sessão (`montar_prompt_sessao` + `brief_multi_ia.montar_brief`)
com **OpenClaude** (NVIDIA NIM, free, já provado em §7/§8). Duas rodadas:

1. **Só leitura** — pedi para copiar do brief: versão, HEAD, checkpoint e se
   está sincronizado. Nenhum arquivo podia ser alterado.
2. **Com diff real** — pedi para criar **um** arquivo novo
   (`tools/PROVA_BRIEF.md`) com 3 linhas tiradas do brief, sem tocar em
   arquivo existente. O arquivo foi removido depois da medição.

### Resultado

| Medida | Resultado |
|---|---|
| Prompt de sessão | **5083 chars** |
| Brief dentro dele | **2624 chars — 51,6%** |
| Rodada 1 (só leitura) | **4/4 corretos**, **7,8 s**, **0** arquivo tocado |
| Rodada 2 (diff real) | **3/3 corretos**, **35,2 s**, **1 arquivo novo**, **0 existente alterado** |

Conteúdo do diff conferido: `versao=1.46.0`, `head=181dea1`,
`checkpoint=trava_git_painel_ia_cascata_real_2026_11_18` — os três do brief.
`git status` mostrou **só** o arquivo novo (`??`), nenhum rastreado alterado.

### Leitura

O brief **não é enfeite**: a CLI extrai o estado sem inventar e respeita a
instrução de não mexer no que existe. O custo é ~2,6 k chars (metade do prompt)
e a resposta continua saindo no contrato (`[ANALISE]` incluso).
