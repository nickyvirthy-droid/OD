# Conversa OmegaDrakon — 2026-11-12

## §1 — Retomada ("leia iniciar") e estado encontrado (12/11)

**Pedido do dono:** *"leia iniciar"* — recarregar o checkpoint antes de retomar.

### 1. O que foi lido

`iniciar/README.md`, `iniciar/RULES.md` (21 regras), `iniciar/session.json`
(entrada mais recente: `devaneios_cache_comando_radio_duplicada_e_cota_gemini_2026_11_11`,
de 11/11 15:05), a transcrição `iniciar/2026-11-11_conversa_omegadrakon.md`
inteira (§1–§13, 694 linhas), o `txt.txt` e o `git status`/`git log`.

### 2. Estado do serviço e do repositório

- `od-core` **ativo**, MainPID **2740225**, `NRestarts=0` — é o processo do
  último restart de 11/11 (o mesmo da prova viva do §13). Nada mudou desde
  então.
- `HEAD` = `origin/master` = **`abcd2e1`** (`docs(iniciar): registra a cadeia
  Gemini→Groq→local, a medição e o incidente do deploy`).
- A árvore **não está limpa**: 11 modificados (+622/−37) e 1 novo
  (`tests/test_radio_player.py`) — é exatamente o lote do **§13** (devaneios
  por cache, rádio em duplicata, disjuntor da cota do Gemini), testado mas
  **não commitado**.

### 3. O que está no disco sem commit (§13 de 11/11)

| Arquivo | Mudança |
|---|---|
| `core/orchestrator.py` | `_etapa_cache` não serve comando de action (`detect_action_intent`) |
| `core/intents.py` | `_formata_radio` para `radio_play`/`radio_stop`/`radio_volume`/`radio_status` |
| `tools/actions/actions.py` | `_radio_ffplay_pids()` varre `/proc`; play adota/encerra duplicata; stop encerra todos os PIDs; zumbi conta como morto |
| `core/resilience.py` | `CircuitBreaker.abrir(erro, recuperacao_s)` |
| `core/llm.py` | `_falhar()` abre na hora em 429/quota, `_espera_do_429()` lê o `retryDelay` (teto 6 h), `_erro_http()` preserva o retryDelay |
| testes | `test_radio_player.py` (novo, 13), `TestFormataRadio` (7), `TestCacheNaoServeComando` (2), cota/disjuntor (6+2) |

Gate registrado no checkpoint: **4489 passed / 17 skipped / 0 falha** (rodado
antes do último ajuste do `retryDelay`; os afetados foram re-rodados e
passaram). Ou seja: **o lote está validado mas não publicado** — regra 7.2
(árvore limpa + HEAD em `origin/master`) segue pendente.

### 4. Achados desta leitura

1. **A higiene do §13 é o único trabalho parado.** Nenhum código novo entrou
   depois; o que falta é commit por assunto, push e restart verde com prova.
2. **O `txt.txt` continua com as três queixas de 11/11** (devaneios, rádio em
   duas instâncias, desligar a rádio deve desligar o player). As três foram
   corrigidas no §13 — o arquivo não foi zerado porque ele é canal, não
   registro (regra 20).
3. **Frente aberta declarada no checkpoint:** cota gratuita do Gemini é
   **20 requisições/dia** (prompt não é o gargalo — medido); hoje quem responde
   é o Groq. Falta decidir se as 20 diárias devem ser reservadas para o que
   exige mais qualidade, e o status dos disjuntores não aparece no `/health`.
4. **App segue 1.44.0/2080** — nenhuma mudança de app neste lote.

### 5. Decisão desta troca

Nada alterado no código: só leitura e registro. O deploy/higiene do lote do
§13 fica para a próxima ordem do dono.

**Sem bump:** app segue **1.44.0/2080**.

## §2 — Higiene do lote de 11/11: gate, commits, push e restart verde (12/11 ~09:30)

**Pedido do dono:** fechar a higiene — gate completo, commits por assunto, push
e restart verde com prova viva.

### 1. Gate completo

`.venv/bin/python -m pytest tests/ -q` → **4494 passed / 17 skipped / 0 falha**
(180,40 s). Nenhuma correção foi necessária: o lote de 11/11 já estava verde
(eram 4489 no registro anterior; +5 pelo `test_radio_player.py` que entrou na
contagem desta rodada).

### 2. Commits por assunto (e o que cada um resolve)

| Commit | Arquivos | Assunto |
|---|---|---|
| `5af9012` | `tools/actions/actions.py`, `core/intents.py`, `test_intents.py`, `test_radio_player.py` | **rádio**: player único por SO e stop que cala todas as instâncias |
| `b6d6144` | `core/llm.py`, `core/resilience.py`, `test_llm.py`, `test_resilience.py` | **cota**: 429 abre o disjuntor na hora e a espera vem do `retryDelay` |
| `8e08d7d` | `core/orchestrator.py`, `test_orchestrator.py` | **grafo**: comando de action nunca vem do cache; `prompt_chars` no log |
| `15531f6` | `iniciar/2026-11-11_conversa_omegadrakon.md` | registro do diagnóstico (§13) |

Push: `origin/master` em **`15531f6`**, árvore limpa.

### 3. Deploy e prova viva

`systemctl --user restart od-core` (regra 7.3, validação verde):
**MainPID 3773109**, `NRestarts=0`, `active`, subido 09:26:26.
`/health` **27/27 up**, `ok=true`; `/llms` = `gemini, groq, gemma-local`;
journal `-p err` **0 entradas** desde o restart.

| Cenário | Resultado |
|---|---|
| "liga a radio" (sem player) | `action_intent fastpath:radio_play`, 1,05 s, **1 player** |
| "liga a radio" de novo | `action_intent` (não cache), 74 ms, **1 player** — adotou o que estava no ar |
| duplicata forçada (`OD_RADIO_CHILD=1 ffplay`) → "liga a radio" | **2 → 1 player**, resposta com "1 instância(s) duplicada(s) encerrada(s)" |
| "status da radio" | `radio_status`, 26 ms, "Rádio tocando (player 3773991)" |
| "desliga a radio" | `radio_stop`, 860 ms, **0 players**, "Rádio parada — energia da caixa desligada" (sem "resistiram") |
| conversa aberta (disjuntor) | `route=llm`, **`llm=gemini`**, 3,45 s, `prompt_chars=6565` |

Nota medida: a cota do Gemini **voltou** (é diária, 20/dia) e o Gemini
respondeu a conversa aberta com o prompt real de 6.565 caracteres — reforça a
medição de 11/11 de que o gargalo é requisição/dia, não tamanho de prompt.

### 4. Resíduos

- Player de teste encerrado (`pgrep ffplay` vazio); nenhum script temporário
  criado nesta entrega.
- Versão **sem bump**: 1.44.0/2080 (correções de servidor; sem mudança de app,
  de API ou de contrato — mesma prática registrada nas entregas anteriores).

**Sem bump:** app segue **1.44.0/2080**.

## §3 — Buracos de intenção: disco, memória e CPU (12/11 ~09:57)

**Pedido do dono:** "qual o uso de disco" deveria acionar a action de disco,
como "quanto de espaço livre" já faz.

### 1. O buraco de detecção

Medido com `detect_action_intent` antes de mexer:

| Frase | Antes |
|---|---|
| "qual o uso de disco" / "uso de disco" / "qual o uso de hd" | `None` (ia para o LLM) |
| "quanto de espaço livre no disco" | `disk_usage` |
| "quanto de memória livre" | `None` (só "quanta memória" casava) |
| "qual o uso de cpu" | `None` (só "uso da cpu"/"processador" casavam) |

A causa era o vocabulário do segundo termo: as regras exigiam
`usado|livre|quanto|como está` e não aceitavam `uso`, `ocupa`, `cheio`,
`disponível`, `quantos`.

### 2. Correção e travas

- `core/intents.py`: disco, memória e cpu passaram a aceitar esses termos.
- **Travas que não podiam regredir:** temperatura continua indo para
  `cpu_temp` (o bloco de cpu ignora a frase quando há
  `temperatura|graus|calor|térmic`); e comprar/preço de HD não vira leitura de
  disco (`custa|compr|preço|barat|orçamento|modelo|marca`).
- A intenção de disco deixou de mandar `path` explícito (a action já mede
  `/` por padrão).

### 3. O segundo defeito: a action era NEGADA

Com a detecção corrigida, a prova viva ainda respondeu `route=fallback`
(`llm=gemini`, 8,8 s). O journal mostrou a causa:

```
CRIT Path outside allowed roots | action=disk_usage | path=/
CRIT Action denied by security | action=disk_usage | denied_by=scope
WARN Orchestrator action denied | Path '/' is outside the allowed project scope
```

O schema da action preenche `path="/"` **antes** do gate, então tirar o param
da intenção não resolvia. Ou seja: **toda** pergunta de disco era negada e caía
no LLM — a detecção nunca chegou a produzir resposta.

- `core/security/scope.py`: `SCOPE_EXEMPT_ACTIONS = {"disk_usage"}` — o `path`
  de uma métrica é o ponto de montagem medido, não acesso a arquivo, então o
  escopo de filesystem não se aplica.
- A exceção é só da métrica: escrita e paths de filesystem continuam negados
  (coberto por teste).

### 4. Testes e deploy

Dois gates completos (um por commit): **4515** e **4517 passed / 17 skipped /
0 falha**. Novos testes: 10 de detecção (disco/memória/cpu, temperatura
preservada, compra de HD não confunde) e 2 de escopo (disco isento, escrita
ainda negada).

Restart: **MainPID 3810200**, `NRestarts=0`, `/health` **27/27**, journal 0 erro.

### 5. Prova viva

| Frase | Resultado |
|---|---|
| "qual o uso de disco" | `action_intent`, `fastpath:disk_usage`, **31,8 ms**, "62,7% usado · 75,7 GB livres de 231,2 GB" |
| "quanto de espaço livre no disco" | `action_intent`, `fastpath:disk_usage`, 20,0 ms, mesmo dado real |
| "quanto de memoria livre" | `action_intent`, `fastpath:memory_usage`, 6,2 ms |
| "qual o uso de cpu" | `action_intent`, `fastpath:cpu_info`, 7,2 ms |
| "qual a temperatura da cpu" | `action_intent`, **`fastpath:cpu_temp`** (não regrediu), 7,6 ms |
| "quanto custa um hd de 4tb" | conversa (não aciona disco) |

Commits: `742e054` (detecção), `c863780` (intenção sem path), `5dde610`
(exceção de escopo).

**Sem bump:** app segue **1.44.0/2080**.
