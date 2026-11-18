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
