# ATRIBUIÇÕES — quem fez o quê no OmegaDrakon

> **Regra 23 (`iniciar/RULES.md`).** O dono constrói o OD com várias IAs, quase
> sempre em ferramentas gratuitas cujos créditos acabam antes do fim do
> serviço. Este é o **livro-caixa compartilhado**: toda entrega registra
> (a) autor, (b) arquivos criados/modificados e (c) intenção + estado.
> Ordem: mais recente no topo. Nada de adivinhação: origem desconhecida é
> registrada como desconhecida.

---

## 18/11/2026 — P0 nº 4 fechado: `.gguf` 3B + runtime do llama.cpp no espelho

**Autor:** Freebuff (Buffy) — sessão de 18/11 ~18:50, pedido do dono ("Fechar o
P0 nº 4 copiando o .gguf do 3B e o binário do llama.cpp para o espelho com
MANIFEST").

### Criados (fora do repositório, HD USB)

- `/home/alex/dados/od-mirror/models/qwen2.5-coder-3b-instruct-q4_k_m.gguf`
  (2,0 GB; sha256 idêntico ao original).
- `/home/alex/dados/od-mirror/runtimes/llama/` — build 10786, 41 MB, **com as
  `.so`** (o binário sozinho não roda).

### Modificados (fora do repositório)

- `od-mirror/MANIFEST.txt` — 133 entradas (82 antigas + 51 novas).
- `od-mirror/README.md` — tabela + seção "Restaurar o LLM local".

### Modificados (no repositório)

- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (P0 nº 4 e checkbox),
  `iniciar/session.json`, transcrição §11.

### Intenção + estado

- **Intenção:** o "offline" do OD não podia depender de `/home/alex/llama.cpp`
  e `/opt/…/runtimes/llama` sobreviverem.
- **Pronto/validado:** `sha256sum -c` **51/51 OK**; **prova real** — o runtime
  copiado subiu de `/tmp` sem `LD_LIBRARY_PATH`, carregou o `.gguf` do espelho
  e respondeu `/v1/models` (`model loaded` + `listening`), depois encerrado.
- **Descoberta registrada:** o unit `od-llm.service` do repo cita gemma e está
  inactive; o 3B realmente servido foi confirmado no `/v1/models` vivo.
- **Limites:** só o 3B coder; symlinks `.so` fora do MANIFEST; `x86_64`.
- **Sem bump:** 1.46.0+2083; sem restart; nenhum código do serviço alterado.

---

## 18/11/2026 — P0 nº 3 fechado: guarda ZIM ↔ compose do acervo offline

**Autor:** Freebuff (Buffy) — sessão de 18/11 ~18:20, pedido do dono ("Fechar o
P0 nº 3 com um teste ZIM ↔ compose no acervo offline").

### Criados

- `tools/checar_zim_compose.py` — guarda nas duas direções, `--json`, exit 1
  com a correção.
- `tests/test_zim_compose.py` (11 testes).

### Modificados

- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (P0 nº 3 fechado),
  `iniciar/session.json`, transcrição §10.

### Intenção + estado

- **Intenção:** fechar o buraco de um ZIM novo ficar invisível para a busca
  por não estar no `command` do kiwix (e da referência morta no compose).
- **Pronto/validado:** **11 passed** no teste; acervo real **alinhado**
  (12 quentes + 2 frios); `test_zim_compose + test_kiwix + test_enciclopedia`
  **106 passed**; **GATE COMPLETO 5459 passed / 19 skipped / 0 falha**.
- **Limites declarados:** a guarda olha o topo dos diretórios montados (não
  subpastas) e não valida a integridade do ZIM — só presença/paridade.
- **Sem bump:** 1.46.0+2083; sem restart.

---

## 18/11/2026 — Medição: quanto do brief a CLI realmente usa

**Autor:** Freebuff (Buffy) — sessão de 18/11 ~17:50, pedido do dono ("Medir
quanto do brief a CLI realmente usa, comparando o prompt com o diff produzido").

### Criados

- Nenhum arquivo versionado (arquivo de prova `tools/PROVA_BRIEF.md` criado
  pela CLI e **removido** depois da medição).

### Modificados

- `docs/IAS_DISPONIVEIS.md` — linha nova no histórico de medições.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (checkbox fechado),
  `iniciar/session.json`, transcrição §9.

### Intenção + estado

- **Intenção:** provar que o brief injetado no prompt das 13 CLIs é **lido e
  usado**, não só carregado.
- **Medido:** prompt **5083 chars**, brief **2624 (51,6%)**. Só-leitura: **4/4
  campos corretos em 7,8 s**, zero arquivo tocado. Com diff real: **3/3
  corretos em 35,2 s**, **1 arquivo novo**, **0 existente alterado** (git
  status só com o arquivo novo).
- **Limite declarado:** amostra de 1 CLI (OpenClaude) e 2 tarefas curtas; CLIs
  sem saldo (Interpreter/Codex/Aider) e a cascata completa não foram medidas
  nesta rodada.
- **Sem bump:** 1.46.0+2083; nenhum código alterado.

---

## 18/11/2026 — Trava no git, painel “IAs no projeto” e prova real da cascata

**Autor:** Freebuff (Buffy) — sessão de 18/11 ~17:00, três sugestões clicadas
pelo dono (hook de pré-commit, painel do estado das IAs, cascata com CLIs
reais) e a pergunta de como operar o orquestrador.

### Criados

- `tools/trava_reescrita.py` — fonte única da régua de reescrita maciça
  (`--staged` / `--worktree`, escapes configuráveis).
- `tools/instalar_hooks.sh` (+x) — instala o hook `pre-commit`.
- `tests/test_trava_reescrita.py` (13 testes).

### Modificados

- `orquestrador.py` — `_reescritas_em_massa` delega em
  `tools.trava_reescrita.verificar` (uma régua, dois pontos de guarda).
- `integrations/api/server.py` — `GET /admin/estado-ia` (ROUTES 138 → 139) e
  seção “IAs no projeto” no `/admin` (checkpoint, árvore suja, idade do
  registro, P0/P1).
- `tools/brief_multi_ia.py` — `estado_para_painel()`.
- `tests/test_api.py` — contagem de rotas e as duas listas esperadas.
- `docs/PROTOCOLO_MULTI_IA.md` (§6.1 — como o dono opera), `docs/CHANGELOG.md`,
  `docs/ANALISE_SISTEMA_TODO.md` (3 checkboxes fechados),
  `iniciar/session.json`.

### Intenção + estado

- **Intenção:** fechar o buraco da trava fora do orquestrador (hook instalado
  neste repositório), tornar visível o que a próxima IA encontra e provar a
  continuidade com binários de verdade.
- **Pronto/validado:** trava **13 passed** (inclui commit real bloqueado e
  commit normal passando); `test_api.py` **202 passed**; bloco multi-IA **140
  passed**; **prova real** Interpreter falhou em **11,4 s** e OpenClaude
  respondeu `OK` em **9,4 s**, sessão `concluido/implantado` em **20,9 s** sem
  alterar a árvore.
- **Pela metade (declarado):** medir quanto do brief a CLI realmente usa; a
  rota nova do painel só vale após restart do `od-core` (regra 7.3).
- **Sem bump:** 1.46.0+2083.

---

## 18/11/2026 — Convivência multi-IA (brief + trava + cascata até concluir) e corpus de frases reais

**Autor:** Freebuff (Buffy) — sessão de 18/11 ~16:10, ordens do dono: "faça"
(executar a próxima melhoria) e *"garanta que todas [as IAs] prossigam dentro
da mesma linha sem destruir o que existe (...) a próxima deve prosseguir e
assim sucessivamente até concluir"*.

### Criados

- `tools/brief_multi_ia.py` — brief único do estado real (versão, HEAD ×
  origin, árvore suja, checkpoint, atribuições, P0/P1, regras de convivência;
  `--json`).
- `docs/PROTOCOLO_MULTI_IA.md` — contrato entre as IAs.
- `tests/test_corpus_frases_dono.py` (32 testes) e `tests/test_multi_ia.py`
  (11 testes).
- `iniciar/2026-11-18_conversa_omegadrakon.md` §7 (transcrição).

### Modificados

- `orquestrador.py` — brief no prompt de toda CLI; `_reescritas_em_massa()`
  (trava: >70% das linhas de arquivo rastreado → falha sem commitar);
  cascata até concluir no gate vermelho; `_encerrar()` grava `detalhe`.
- `iniciar/RULES.md` — regra 24 (protocolo multi-IA).
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (P0 nº2 fechado),
  `iniciar/session.json`.

### Intenção + estado

- **Intenção:** o dia provou o risco — outra ferramenta regrediu o
  `orquestrador.py` (1654 → 251 linhas) sem registro e a suíte passou a
  quebrar na coleta. A resposta é estado explícito + regras iguais + travas
  automáticas, não confiança na memória de cada IA.
- **Lote órfão revertido** com a ordem do "faça": `orquestrador.py` de volta
  a 1654 linhas, `soma.py` removido, `test_orquestrador.py` **116 passed**.
- **Pronto/validado:** corpus **32 passed**; multi-IA + orquestrador **127
  passed**; **GATE COMPLETO 5435 passed / 19 skipped / 0 falha** (220,46 s).
- **Limite declarado:** as travas valem para sessões do `orquestrador
  --sessao`; IA que trabalha fora dele (esta, por exemplo) segue por
  regra/registro — o brief e o checklist do protocolo são o único cinto.
- **Sem bump:** 1.46.0+2083. Sem restart (o `od-core` não usa o orquestrador
  de CLIs).

---

## 18/11/2026 — Retomada "leia iniciar": restart de 15:01 já no ar, download do Raul no lote 4 e lote órfão do `orquestrador.py`

**Autor:** Freebuff (Buffy) — sessão de 18/11 ~15:50, a pedido do dono
("leia iniciar"). **Origem do lote órfão:** **NÃO IDENTIFICADA** (arquivo
reescrito às 15:19:11, sem registro em `iniciar/` nem no CHANGELOG).

### Criados

- Nenhum arquivo novo (só registro).

### Modificados

- `iniciar/session.json` — checkpoint
  `retomada_leitura_iniciar_2026_11_18_turno2`.
- `iniciar/2026-11-18_conversa_omegadrakon.md` — §6 (estado medido).
- `docs/ANALISE_SISTEMA_TODO.md` — checkboxes do §4 (sugestões não
  escolhidas deste turno).
- `iniciar/ATRIBUICOES.md` — esta entrada.

### Intenção + estado

- **Intenção:** cumprir as regras 3/4/23 (ler antes de assumir contexto,
  salvar a cada troca, atribuir) e responder ao `txt.txt` com medição.
- **Achado 1 — restart não registrado:** o serviço foi reiniciado às
  **15:01:19** (MainPID 220986, NRestarts=0) DEPOIS dos commits de 14:56:55;
  logo a **cascata 13**, o **fix do cgroup** e o **Query Router 101×485**
  já estão no ar — o "restart pendente" do checkpoint anterior está
  vencido. `/health` ok=true 30/30.
- **Achado 2 — lote órfão destruidor:** `orquestrador.py` na árvore foi
  regredido para a versão de **fila de 08/10** (251 linhas), com
  `load_dotenv()` no nível de módulo; `pytest tests/test_orquestrador.py`
  quebra na **coleta** (`ImportError: cannot import name 'CLIS'`). `soma.py`
  (32 B) apareceu na raiz. **Não revertido** (regra 7 exige ordem).
  Próximo passo exato: `git checkout -- orquestrador.py && rm soma.py`
  **com ordem do dono**.
- **Achado 3 — download do Raul:** unidade ativa desde 13:50, lote 3
  fechado (+10; acervo **382**, +28 desde 354), lote 4 de ~19 rodando.
- **Sem bump:** 1.46.0+2083. Nenhum código alterado nesta troca.

---

## 18/11/2026 — Cascata 10 → 13 CLIs: cota nunca é motivo de exclusão

**Autor:** OpenCode (agente, modelo MiMo-V2.6-Flash) — continuação do
serviço (18/11 ~17:00), ordem do dono ("cota nunca é motivo de exclusão… a
cota sempre acaba por isso esse número grande de IAs").

### Criados

- `tools/openclaude_headless.sh` (+x) — wrapper headless do OpenClaude:
  aplica o perfil portátil (`ai_settings.env`, `CLAUDE_CONFIG_DIR` etc.,
  mesmos exports do `start.sh`) e executa a engine `@gitlawb/openclaude`.

### Modificados

- `orquestrador.py` — campo novo `CliSpec.prompt_via_stdin` +
  `executar_cli()` enviando o prompt por `communicate(input=…)`; `CLIS`
  **10 → 13** (Cline posicional one-shot, OpenClaude `-p --yolo`,
  Interpreter `--stdin`); bloco de política reescrito com a régua do
  dono; `CLI_SESSAO_OPCOES` 10 → 13.
- `integrations/api/server.py` — `SESSAO_CLIS` 10 → 13 (contrato do
  painel).
- `tests/test_orquestrador.py` — contrato da cascata atualizado (13
  CLIs; freebuff única de fora e **só por modo**; testes novos de
  `prompt_via_stdin` e do wrapper).
- `docs/IAS_DISPONIVEIS.md` — conclusão 13/14; cota removida dos
  motivos de exclusão; histórico com a 2ª leva.

### Intenção + estado

Reavaliar as 4 exclusões sob a nova régua: cline, openclaude e
interpreter **tinham** one-shot (provado com prompt real — os dois
primeiros falham só por cota/saldo, que volta; openclaude respondeu e
criou arquivo, exit=0); freebuff continua fora por modo medido. Validado:
318 + 336 testes do bloco e **gate completo 5392 passed / 19 skipped /
0 failed**; `executar_cli(OpenClaude)` → `SAIDA: ok`. **Sem bump**
(1.46.0+2083); entra no ar no próximo restart do `od-core` (autorização
do dono pendente — regra 7.1).

---

## 18/11/2026 — Playlist do Raul Seixas: download em unidade própria + fix do cgroup

**Autor:** OpenCode (agente, modelo MiMo-V2.6-Flash) — ordem do dono
("Sim, baixar agora" + "Conserta agora também", 18/11).

### Criados

- `tools/baixar_resto_lista.py` — retoma QUALQUER playlist
  (`OD_LISTA_URL`, `OD_LISTA_NOME`, `OD_LISTA_LOG`; slug default).

### Modificados

- `integrations/radio_link.py` — `_unit_transitoria()` (novo):
  `iniciar_processamento()` passa a rodar o worker em unidade transitória
  `systemd-run --user --unit=od-radio-link-<id>` (irmão do od-core em
  `app.slice`), com fallback para o `Popen` + `start_new_session` antigo
  (`unit=""` desliga); e `_parece_repetida()` endurecido (casa o título
  sozinho — a Metamorfose Ambulante tinha entrado duplicada no acervo).
- `tests/test_radio_link.py` — 3 testes da unidade systemd.
- `tests/test_radio_cobertura.py` — teste novo da pré-checagem no
  sentido contrário (lista bare × acervo com artista).
- `tests/test_tools_diversos_cobertura.py` — expectativas + teste
  `test_nome_da_lista_e_configuravel` (37 passed).

### Intenção + estado

O worker morria com qualquer restart do od-core (mesmo cgroup). Agora o
download roda em unidade própria — `od-radio-lista-raul.service` **ativa**
desde 13:53, lote 1 fechou +10 (354 → 364), lote 2 rodando; 190 faixas ≈
19 lotes ≈ 10–13 h. A duplicata da Metamorfose foi removida (linha 789 →
`revisar/duplicadas/`, acervo 363). **Sem bump** (1.46.0+2083); o fix do
radio_link entra no ar no próximo restart do `od-core` (autorização
pendente) — a unidade do download já protegida desde agora.

---

## 18/11/2026 — Query Router: 101 × 485 features — vetor harmonizado

**Autor:** OpenCode (agente, modelo MiMo-V2.6-Flash) — continuação do
serviço (18/11 ~14:30), escolha do dono ("Voltar ao Query Router").

### Modificados

- `core/query_router.py` — `_harmonizar_dimensao()` (novo) + chamada em
  `classify()`: cauda do embedding completada com a média de treino do
  `StandardScaler` quando o ambiente não tem `sentence-transformers`
  (suíte: 101 → 485); fallback com um único aviso se o vetor for maior.
- `tests/test_query_router.py` — regressão (`use_embeddings=False`).
- `docs/CHANGELOG.md`, `iniciar/session.json`
  (`query_router_101x485_2026_11_18`), transcrição §3, esta entrada.

### Intenção e estado

- **Diagnóstico:** o aviso era só da **suíte** (journal da produção: 0
  ocorrências) — o `.venv` do serviço tem o pacote; o `python3` do
  sistema não. Sem ele, `embed()` falhava e o `predict` quebrava em toda
  chamada (router nunca classificava na suíte).
- **Pronto/validado:** `test_query_router.py` **20 passed**; prova real
  com o modelo de produção → `101 → 485` (1×) e classificações
  `direct`/`tool`/`hybrid`; **gate completo 5385 passed / 19 skipped / 0
  falha**.
- **Sem bump:** 1.46.0+2083. **Restart pendente de autorização** (regra
  7.1) — o fix entra no ar no próximo restart; a produção já se
  comporta igual com o código antigo.

---

## 18/11/2026 — Cascata do orquestrador: 2 → 10 IAs (ordem do dono)

**Autor:** OpenCode (agente, modelo MiMo-V2.6-Flash) — sessão de 18/11
~13:50, pedido do dono no chat ("usar todas as 14 IAs, não só as três
atuais"; confirmou "Sim: expandir a cascata").

### Criados

- `iniciar/2026-11-18_conversa_omegadrakon.md` **§2** (transcrição desta
  entrega).

### Modificados

- `orquestrador.py` — `CLIS` **2 → 10** (Gemini, Qwen, Claude, Crush, Agy,
  OpenClaw, Codex, Aider — cada flag de modo não-interativo medida no
  `--help` de 18/11; medição e as 4 exclusões em comentário no código);
  `OPENCODE_MODELO` trocado (o `nemotron-3-ultra-free` sumiu do catálogo —
  a primeira da cascata morria com model-not-found — → provado
  `opencode/deepseek-v4.1-flash-free`, exit=0); `CLI_SESSAO_OPCOES`
  2 → 10; help do `--cli`.
- `integrations/api/server.py` — `SESSAO_CLIS` 2 → 10 (seletor do painel).
- `tests/test_orquestrador.py` — contrato da cascata atualizado + 2
  testes novos (flags headless de cada CLI nova; exclusão das 4 só-TUI
  freebuff/cline/openclaude/interpreter; seletor do runner × servidor).
- `docs/CHANGELOG.md` — entrada "Cascata do orquestrador: 2 → 10 IAs".
- `docs/IAS_DISPONIVEIS.md` — conclusão das 14 atualizada (10 na cascata,
  4 fora com motivo) + linha no histórico de medições.
- `iniciar/session.json` (checkpoint `cascata_14_ias_2026_11_18`), esta
  entrada.

### Intenção e estado

- **Intenção:** cumprir a ordem do dono de usar as 14 IAs no orquestrador;
  a hipótese dele foi testada primeiro (o refactor da madrugada **não**
  fez isso — media 2 CLIs; os "3 atuais" são providers de LLM do chat,
  camada diferente das CLIs de código).
- **Medição antes de mexer:** `--help` das 14 (sem cota); 10 com one-shot
  entraram, 4 ficaram de fora com motivo documentado; `opencode models`
  para o catálogo de modelos.
- **Pronto/validado:** `test_orquestrador.py` **114 passed**;
  `test_api.py -k sessao` **21 passed**; **gate completo 5384 passed / 19
  skipped / 0 falha**; comando seco das 10 conferido.
- **Sem bump:** 1.46.0+2083. **Restart feito com autorização do dono às
  12:53** (MainPID 83842, NRestarts=0, `journal -p err` = 0, `/health`
  30/30) — `SESSAO_CLIS` novo valendo no painel.

---

## 18/11/2026 — Retomada "leia iniciar": gate vermelho do lote da madrugada diagnosticado e consertado

**Autor:** OpenCode (agente, modelo MiMo-V2.6-Flash) — sessão de 18/11 ~09:33,
a pedido do dono ("leia iniciar").
**Origem do lote trabalhado:** **Cline** (commits de autor "Nicky Virthy",
18/11 09:08–09:15, mensagem `implementa: ideia default`; sessão Cline
visível em `refs/cline/checkpoints/`, última checkpoint 09:29).

### Criados

- `iniciar/2026-11-18_conversa_omegadrakon.md` (§1 — esta retomada).

### Modificados

- `orquestrador.py` — **revertido para `96040ba`** (versão de 17/11). O
  refactor do Cline (2297 linhas) tinha: `load_dotenv()` no nível de módulo
  (linha 53, vazava **56 chaves** do `.env` no `os.environ` na **coleta**
  da suíte via `tests/test_orquestrador.py`) + 10 funções do modo sessão
  removidas (`ler_caixa`, `gravar_caixa`, `_batimento`, `_matar_grupo`…)
  + funções de fila adicionadas que o próprio docstring declara removidas.
  No commit anterior ao revert (antes da reversão) foi feito também o fix
  cirúrgico de `load_dotenv` em `main()` — subsumido pelo revert.
- `iniciar/session.json` (checkpoint de 18/11),
  `iniciar/ATRIBUICOES.md` (esta entrada), transcrição do dia.

### Intenção e estado

- **Intenção:** cumprir as regras 3/4/23 (ler, registrar, atribuir) e fechar
  o ciclo do gate vermelho encontrado (regra 13: causa raiz, correção e
  reexecução até não haver erros).
- **Diagnóstico:** gate completo **80 failed / 5302 passed / 19 skipped**,
  idêntico em 2 rodadas (`diff` = 0). Bissect progressivo (subconjuntos →
  `--ignore-glob` → um arquivo por vez) isolou o gatilho como a **coleta**
  de `tests/test_orquestrador.py`; prova direta do vazamento (56 chaves) e
  confirmação de que cada arquivo falhava só no conjunto.
- **Pronto/validado:** `import orquestrador` → 0 chaves vazadas; os 536
  testes das 8 classes afetadas rodados juntos → **536 passed**; **gate
  completo pós-revert: 5382 passed / 19 skipped / 0 falha** (212,33 s) —
  contra 80 failed / 5302 passed na abertura do turno.
- **Pela metade (declarado, da outra ferramenta):** o refactor do
  `orquestrador.py` ficou incompleto e sem registro (sem CHANGELOG, sem
  `iniciar/`); revertido. As entregas do Cline que **ficam**: `tools/od.sh`
  (menu de 14 CLIs), `docs/OD_MENU_CLIS.md`, entrada no CHANGELOG, remoção
  da regra `_CACHE_BAN_VERIFICACAO_FALSA` em `core/orchestrator.py`
  (edição de 17/11 21:24 commitada pelo lote) e os docs de 18/11.
- **Resíduos LIMPOS com ordem do dono** (~10:50, "encerrou por falta de
  crédito"): 171 `gerado_*.py` + `teste_orquestrador.py` (raiz) removidos;
  árvore com **0 não-rastreados**; gate pós-limpeza **5382 passed / 19
  skipped / 0 falha**; checkbox do TODO §4 marcado `[x]`.
- **Sem bump:** 1.46.0+2083. **Commits:** `2775d3b` (fix) + `4648271`
  (docs) em `origin/master`. **Restart verde (regra 7.3):** 10:37:13,
  MainPID 4133749, NRestarts=0, `journal -p err` = 0, `/health` ok=true
  30/30 up (mqtt transitório reconectou em 8 s). **Telegram:** ok=true
  msg_id=4053.

---

**Autor:** Freebuff (Buffy) — sessão de 17/11, a pedido do dono ("Revisar as
checkboxes abertas do TODO e priorizar as próximas entregas").

### Criados

- Nenhum arquivo novo.

### Modificados

- `docs/ANALISE_SISTEMA_TODO.md` — 5 checkboxes fechadas com evidência,
  duplicata de "Task Queue (Redis/RQ)" removida, item reescopado, texto órfão
  do `web_search` corrigido e a seção nova `📍 Revisão de 17/11/2026` (P0–P3).
- `iniciar/2026-11-17_conversa_omegadrakon.md` (§18), `iniciar/session.json`.

### Intenção e estado

- **Intenção:** o TODO já tinha 38 abertas, das quais várias já estavam
  entregues — revisar sem conferir código é o que gera "parece que nada anda".
- **Pronto/validado:** **32 abertas / 78 fechadas**; `tests/test_rag.py` 93
  passed (calibração lê `docs/`).
- **Prioridades:** P0 (llm_cache, corpus de frases reais, ZIM↔compose, gguf no
  espelho), P1 (I2 com medição, modo colapso, backup com restauração,
  comparador de modelos), P2 (compras/decisões do dono), P3 (infra/demanda).
- **Sem bump:** 1.46.0+2083; nenhum código alterado.

---

## 17/11/2026 — Curadoria do acervo no app Android (1.46.0+2083)

**Autor:** Freebuff (Buffy) — sessão de 17/11, a pedido do dono ("Fechar a
pendência da curadoria do acervo no app Android").

### Criados

- `app/lib/screens/curadoria_screen.dart` — tela de curadoria do acervo.
- `app/test/curadoria_api_test.dart` (10 testes) e
  `app/test/curadoria_screen_test.dart` (10 testes).

### Modificados

- `app/lib/services/od_api.dart` — `OdMusicaAcervo`, `OdParMusica`,
  `OdCuradoria` e 6 métodos REST da curadoria.
- `app/lib/screens/dashboard_screen.dart` — card "Curadoria do acervo" (admin)
  + `_abrirCuradoria()` por `Navigator.push`.
- Bump 1.46.0+2083: `.env` (gitignored), `core/capabilities.py`,
  `app/pubspec.yaml`, `integrations/api/server.py` (`_APP_VERSION_CODE`),
  `site/index.html`, `site/historico.html` (78 lançamentos / Era 9 = 12).
- `tests/conftest.py` — `OD_QUOTA_FILE` da suíte para temporário (isolamento
  da cota real que derrubou 2 testes do gate).
- `docs/CHANGELOG.md` ([1.46.0]), `docs/README_VERSAO.md` ([1.46.0]),
  `docs/ANALISE_SISTEMA_TODO.md` (checkbox fechado),
  `iniciar/2026-11-17_conversa_omegadrakon.md` (§17), `iniciar/session.json`.

### Intenção e estado

- **Intenção:** o dono não precisa mais abrir o navegador no celular para
  excluir/bloquear música e liberar faixas de cantores bloqueados.
- **Pronto/validado:** `flutter analyze` 0 issues, `flutter test` **257
  passed / 2 skipped**, gate Python **5374 passed / 19 skipped / 0 falha**;
  APK **1.46.0+2083** conferido por `aapt2` e publicado em `site/`.
- **Pela metade (deliberado):** sem prova visual no aparelho (máquina sem
  navegador/emulador); a tela é provada pelos 20 testes de widget/API.
- **Bump MINOR:** 1.45.1+2082 → **1.46.0+2083**.

---

## 17/11/2026 — Letra internacional com tradução em lista paralela no `/radio-pro`

**Autor:** Freebuff (Buffy) — sessão de 17/11, a pedido do dono ("Mostrar a
letra internacional com a tradução em lista paralela no /radio-pro").

### Criados

- `integrations/radio_traducao.py` — `montar_traducao()` pela cadeia de LLM do
  OD, cache com hash da letra, marca `JA_PT`.
- `tests/test_radio_traducao.py` — 25 testes.

### Modificados

- `integrations/api/server.py` — rota `GET /api/radio/pro/traducao` (ROUTES,
  `_ROUTE_SPECS`, `AUTH_EXEMPT_PATHS`) e o handler com o gate de sessão.
- `site/radio-pro.html` — card "Letra" em duas colunas + `pedeTraducao()` /
  `desenhaTraducao()`; descarta resposta de faixa que já trocou.
- `tests/test_radio_pro.py` — rota nova nos conjuntos + teste das colunas.
- `tests/test_api.py` — rotas 137 → **138**.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (checkbox fechado),
  `iniciar/2026-11-17_conversa_omegadrakon.md` (§15), `iniciar/session.json`.

### Intenção e estado

- **Intenção:** o dono queria ler a letra internacional com a tradução ao lado;
  sem serviço pago e sem dependência nova — quem traduz é a cadeia do próprio
  OD.
- **Pronto/validado:** gate completo **5374 passed / 19 skipped / 0 falha**
  (218,8 s, exit 0); coleção 5391 contra 5365 do HEAD em worktree (delta exato
  de +26 testes); `node --check` OK; prova viva do Groq traduzindo "The Sound
  of Silence".
- **Limite declarado:** tradução é uma chamada de LLM por faixa (depois só
  cache); sem internet e sem llama-server no ar, a coluna simplesmente não
  aparece.
- **Sem bump:** 1.45.1+2082.

---

## 17/11/2026 — Curiosidade da música de volta no `/radio-pro`

**Autor:** Freebuff (Buffy) — sessão de 17/11, a pedido do dono ("Fazer o
/radio-pro mostrar a curiosidade da música atual").

### Criados

- Nenhum arquivo novo.

### Modificados

- `site/radio-pro.html` — `<div id="agoraCurio">` no card "Tocando agora" e
  `desenhaAgora()` pintando `t.curiosidade` (vazio quando não há).
- `tests/test_radio_pro.py` — `test_pagina_mostra_a_curiosidade_da_musica`.
- `docs/CHANGELOG.md` (entrada datada, sem bump),
  `docs/ANALISE_SISTEMA_TODO.md` (checkbox fechado),
  `iniciar/2026-11-17_conversa_omegadrakon.md` (§14), `iniciar/session.json`.

### Intenção e estado

- **Intenção:** o dado já existia na API (`tocando.curiosidade` de
  `radio_agora.curiosidade_da_musica()`, leitura do `acervo.db`); a página nova
  simplesmente nunca teve onde exibi-lo — 0 ocorrências de "curiosidade" no
  HTML, medido antes da correção.
- **Pronto/validado:** `test_radio_pro.py` 58 passed e rádio completo 216
  passed / 0 falha; sem restart (o HTML é servido do disco a cada requisição).
- **Sem bump:** 1.45.1+2082 (página web; APK e contrato do app intactos).

---

## 17/11/2026 — Retomada "leia iniciar": checkpoint relido e 2 pedidos novos do `txt.txt` registrados

**Autor:** Freebuff (Buffy) — sessão de 17/11, a pedido do dono ("leia
iniciar").

### Criados

- Nenhum arquivo novo.

### Modificados

- `iniciar/session.json` — checkpoint
  `retomada_leitura_iniciar_2026_11_17_turno3`.
- `iniciar/2026-11-17_conversa_omegadrakon.md` — §13 (estado encontrado,
  novidades do `txt.txt`, o que não foi feito).
- `docs/ANALISE_SISTEMA_TODO.md` — 2 checkboxes novos no §4 (curiosidade da
  música no `/radio-pro`; letra com tradução paralela).
- `iniciar/ATRIBUICOES.md` — esta entrada.

### Intenção e estado

- **Intenção:** cumprir a regra 3 (ler o checkpoint antes de retomar) e não
  deixar pedido do dono morar só no `txt.txt` (regra 20).
- **Estado encontrado:** árvore limpa, `HEAD == origin/master == e51b5f2`,
  `od-core` active (MainPID 2433306, NRestarts=0), gate mais recente 5388
  passed, versão 1.45.1+2082.
- **Achado medido:** `site/radio-pro.html` tem **0 ocorrências** de
  "curiosidade", embora `GET /api/radio/agora` já devolva
  `tocando.curiosidade` (de `radio_agora.py::curiosidade_da_musica()`) — falta
  a página exibir, o dado existe.
- **Pela metade (deliberado):** nenhum código alterado, sem gate e sem
  restart; os dois pedidos aguardam ordem do dono. Sem bump (1.45.1+2082).

---

## 17/11/2026 — Bloqueio de música vale no pedido por link do YouTube

**Autor:** Freebuff (Buffy) — sessão de 17/11, a pedido do dono
("Faça o radio_link.py recusar o download de música que está na lista de
bloqueadas").

### Criados

- Nenhum arquivo novo.

### Modificados

- `integrations/radio_link.py` — `_artista_e_titulo_do_link()`,
  `_bloqueada_no_link()`, filtro antes do download em `processar_pedido()`
  (novo parâmetro `musicas_bloqueadas`), filtro das bloqueadas em
  `_baixar_resto()` e conferência pós-download (nome escondido no link →
  `excluir_musica_do_acervo()` + pedido recusado).
- `site/radio-pro.html` — motivo `musica_bloqueada` traduzido.
- `tests/test_radio_link.py` — `TestMusicaBloqueadaNoLink` (7 testes).
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (checkbox fechado),
  `iniciar/2026-11-17_conversa_omegadrakon.md` (§6), `iniciar/session.json`.

### Intenção e estado

- **Intenção:** fazer o bloqueio individual do dono valer para o caminho que
  ele mais usa (pedido por link/playlist), e não só para o painel.
- **Pronto/validado:** gate completo **5355 passed / 16 skipped / 0 falha**
  (202,45 s, exit 0); sandbox provou bloqueada sem download, playlist mista
  baixando só a permitida, título com sufixo casando e lista ausente sem
  barrar nada.
- **Limite declarado:** a checagem pré-download é heurística (depende do que o
  link entrega); a rede de segurança é a conferência no acervo depois do
  download, que apaga a faixa e recusa o pedido.
- **Sem bump:** 1.45.0+2081.

---

## 17/11/2026 — Pedidos 2 e 3 na interface: rotas, painel /admin e página /radio-pro

**Autor:** Freebuff (Buffy) — sessão de 17/11, a pedido do dono
("Implemente as rotas de API, o painel e a página /radio-pro para excluir
música e gerenciar exceções de cantores").

### Criados

- `tests/test_radio_curadoria.py` — 28 testes (listas de pares, exceção
  vencendo o bloqueio, `excluir_musica_do_acervo`, as 6 rotas e as páginas).

### Modificados

- `integrations/api/server.py` — 6 rotas de curadoria (`GET
  /api/radio/musicas`, `POST /api/radio/musicas/excluir`,
  `POST|DELETE /api/radio/musicas/bloqueadas`, `POST|DELETE
  /api/radio/musicas/excecoes`), `_exige_admin_do_acervo`,
  `_par_artista_titulo`, `_listas_de_curadoria`, entradas em
  `AUTH_EXEMPT_PATHS` e no `_ROUTE_SPECS`, seção nova no `_ADMIN_PAGE_HTML`
  (HTML + JS) e `musCarregar` no `carregarTudo`.
- `site/radio-pro.html` — card "Curadoria do acervo" (só o dono vê) com
  buscar, excluir, bloquear/desbloquear e exceções.
- `tests/test_api.py` — contagem de rotas **130 → 136** e as 6 rotas nos
  conjuntos esperados (privado/público).
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`,
  `iniciar/2026-11-17_conversa_omegadrakon.md` (§5) e `iniciar/session.json`.

### Intenção e estado

- **Intenção:** fechar os pedidos 2 e 3 do `txt.txt` até o ponto onde o
  dono opera — até agora só existia a biblioteca.
- **Pronto/validado:** gate completo **5347 passed / 16 skipped / 0 falha**
  (205,23 s, exit 0); sandbox contra o acervo real **em leitura** (200
  faixas, `?q=raul` correto, CRUD em listas de `/tmp`, 404 de faixa
  inexistente); nenhuma música real apagada.
- **Pela metade (declarado):** `radio_link.py` ainda baixa faixa bloqueada
  pedida por link — o bloqueio só vale pelo painel/página. Checkbox criado
  no TODO §4 com o próximo passo exato.
- **Sem bump:** 1.45.0+2081.

---

## 17/11/2026 — Lote órfão validado e publicado: exclusão/bloqueio de músicas, exceções de cantores, reboot, staging e cobertura

**Autor do lote:** **ORIGEM NÃO IDENTIFICADA** (achado na árvore em 17/11,
sem commit, sem transcrição e sem entrada neste livro-caixa — regra 23).
**Validação, registro e publicação:** Freebuff (Buffy), a pedido do dono
("Rode o gate completo e commite o lote órfão").

### Criados

- Confirmados no commit (os 10 arquivos de cobertura já existiam na árvore):
  `tests/test_radio_cobertura.py`, `tests/test_actions_cobertura.py`,
  `tests/test_embed_hybrid_cobertura.py`,
  `tests/test_marketplace_cobertura.py`, `tests/test_os_updater.py`,
  `tests/test_rota_reboot_os_updater.py`,
  `tests/test_server_rotas_novas_cobertura.py`,
  `tests/test_supply_depot_cobertura.py`,
  `tests/test_tools_diversos_cobertura.py`, `tests/test_tools_telemetry.py`
  e `iniciar/2026-11-15_conversa_omegadrakon.md`.

### Modificados

- `integrations/radio_cantores.py` — listas `data/musicas_bloqueadas.txt` e
  `data/cantores_excecoes.txt`, `eh_excecao`/`adicionar_excecao`/
  `remover_excecao`/`linhas_excecoes`, `musica_bloqueada`/
  `adicionar_musica_bloqueada`/`remover_musica_bloqueada`/`linhas_bloqueadas`,
  `excluir_musica_do_acervo` e `indesejado(artista, titulo=)` consultando a
  exceção **antes** do bloqueio.
- `integrations/api/server.py` — `POST /admin/os-updater/reboot` usa
  `updater._reboot()`.
- `tools/supply_depot.py` — código gerado gravado no **staging** (conserta o
  `codigo_ausente_no_staging` do roundtrip).
- `app/lib/screens/tasks_screen.dart`, `app/test/tasks_api_test.dart`,
  `app/test/tasks_screen_test.dart` — payload `{}` válido + 5 testes.
- `tests/test_task_queue.py` — +8 testes de borda (`TestCoberturaDeBorda`).
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/session.json`,
  `iniciar/2026-11-17_conversa_omegadrakon.md` (registro desta rodada).

### Intenção e estado

- **Intenção do lote:** fechar os pedidos 2 e 3 do `txt.txt` (excluir músicas
  que o dono não gosta; manter músicas escolhidas de cantores bloqueados), o
  reboot do OS updater pela API, o staging do `supply_depot`, o payload `{}`
  do app e a dívida de cobertura acumulada desde 02/11.
- **Validado:** gate Python completo **5319 passed / 16 skipped / 0 falha**
  (210,60 s, exit 0); `flutter analyze` sem issues; `flutter test`
  **228 passed / 2 skipped**.
- **Pela metade (declarado):** as **rotas de API, o painel `/admin` e o
  `/radio-pro`** da exclusão/exceções **não existem** — só a biblioteca. O
  dono não consegue operar pela interface ainda; próximo passo exato: criar
  `POST /admin/radio/musica/excluir`, rotas de exceções e os botões nas duas
  páginas.
- **Sem bump:** 1.45.0+2081.

---

## 17/11/2026 — Retomada "leia iniciar": lote órfão verde encontrado na árvore

**Autor:** Freebuff (Buffy) — sessão de 17/11, a pedido do dono ("leia
iniciar").

### Criados

- Nenhum arquivo novo nesta troca.

### Modificados

- `iniciar/2026-11-17_conversa_omegadrakon.md` — §3 (estado encontrado).
- `iniciar/session.json` — chave `retomada_leitura_iniciar_2026_11_17_turno2`.
- `iniciar/ATRIBUICOES.md` — esta entrada.

### Intenção e estado

- **Intenção:** atender à regra 3 (ler o checkpoint antes de retomar) e
  reportar com precisão onde a sessão está.
- **Achado:** a árvore está suja com um lote **posterior ao commit
  `fccb6bc`**, sem registro em `iniciar/`: `integrations/radio_cantores.py`
  (+256: exceções `data/cantores_excecoes.txt` e bloqueio individual
  `data/musicas_bloqueadas.txt`), `integrations/api/server.py` (reboot via
  `updater._reboot()`), `tools/supply_depot.py` (staging do código),
  `app/lib/screens/tasks_screen.dart` (payload `{}` válido) + 2 testes do
  app, `tests/test_task_queue.py` (+263), `docs/ANALISE_SISTEMA_TODO.md` e a
  transcrição de 15/11, mais 10 arquivos de teste de cobertura.
- **Autor do lote: ORIGEM NÃO IDENTIFICADA** (nada no livro-caixa nem na
  transcrição) — registrado como desconhecido, conforme regra 23.
- **Validado agora:** os 12 arquivos de teste do lote → **682 passed em
  8,82 s**. Falta o gate completo e o commit.
- **Pela metade:** os pedidos 2 e 3 do `txt.txt` têm só a camada de
  biblioteca; **não existem ainda** rotas de API, painel nem app para
  excluir música e gerenciar exceções de cantores.
- **Serviço:** `od-core` active, MainPID 2183349, NRestarts=0 (PID mudou em
  relação ao 3322791 de 15/11 — restart não anotado).
- **Nesta troca:** nenhum código alterado, só registro. Aguardando ordem do
  dono para (a) gate completo + commit do lote e (b) fechar as rotas da
  rádio. Sem bump (1.45.0+2081).

---

## 14/11/2026 — Itens 2–4 do backlog: criar tarefa, SSE e filtro por data (registro completado em 15/11)

**Autor:** OpenClaude (outro agente, sessão da noite de 14/11) — os commits
`da19eb3` (criar tarefa pelo painel/app), `eef553e` (SSE na aba Tarefas) e
`ce643a2` (filtro/paginação por data de conclusão) **não entraram no
livro-caixa nem na transcrição**; registro completado aqui por OpenCode em
15/11, a pedido do dono ("voce parou ontem. verifique o que mudou e
continue").

### Criados

- Nenhum arquivo novo.

### Modificados

- `integrations/api/server.py` — formulário de criação no bloco Tarefas
  (select do catálogo `GET /actions` + campo de payload JSON +
  `tqCriar` → `POST /admin/tasks`); rota de ordenação por `finished_ts`.
- `app/lib/services/od_api.dart` — `createTask()` (POST, 201) + SSE de
  `/admin/tasks/events` + `sort_by_finished`.
- `app/lib/screens/tasks_screen.dart` — diálogo "Enfileirar tarefa" (＋),
  stream SSE ao vivo e filtro por data de conclusão.
- `core/task_queue.py` — ordenação/filtro por `finished_ts`.
- `docs/ANALISE_SISTEMA_TODO.md` — itens 2–4 marcados [x].

### Intenção e estado

Intenção: fechar os itens 2, 3 e 4 do backlog §4. Estado verificado em
15/11 por OpenCode: flutter analyze limpo, **223 testes verdes** antes das
correções, lote Python `test_task_queue + test_api` **229 passed**, árvore
pushada e serviço ativo (MainPID 3322791, NRestarts=0). **Duas lacunas
detectadas e cobertas em 15/11:** (a) nenhum teste para
`createTask`/formulário — +5 testes escritos; (b) o diálogo rejeitava
payload vazio `{}` (ação sem parâmetros como `system_info` não passava,
embora a API aceite `payload or {}`) — corrigido.

---

## 14/11/2026 — Inversão da cadeia de IA (Groq → Gemini) e inventário do TODO/Caderno

**Autor:** OpenCode (agente, modelo MiMo-V2.6-Flash) — sessão de 14/11
~17:20, a pedido do dono ("inverta o chamado, coloque o Groq antes do
Gemini").

### Criados

- Nenhum arquivo novo.

### Modificados

- `.env` — `OD_CHAT_PROVIDERS=groq,gemini,local` (novo; é a variável que
  `runtime/launcher.py::build_llm_providers()` realmente lê) +
  `OD_IA_ORDEM` invertido (variável **dormante** — só o `musica.py` de
  `.od_sandbox/` a lia — trocada por consistência).
- `iniciar/2026-11-14_conversa_omegadrakon.md` — §21 (pedido + cadeia +
  inventários + aba Tarefas).
- `iniciar/session.json` — chave `inversao_cadeia_ia_2026_11_14`.
- `docs/CHANGELOG.md` — seção "Cadeia de IA invertida … (sem bump)".

### Intenção e estado

Intenção: honrar a ordem pedida — o Groq na frente porque a cota gratuita do
Gemini zera e abre disjuntor de 6 h. Estado: **verde** — restart 17:25
(MainPID 2967186, NRestarts=0), `/health` ok com 29 checks, journal
`ordem=['groq', 'gemini', 'gemma-local']` e mensagem ao vivo com
`llm_used=groq`. Também entregues nesta sessão (leitura pura): inventário
das **47 checkboxes abertas** do `docs/ANALISE_SISTEMA_TODO.md`, mapa das
**11 notas / 7 listas TODO** do Caderno (só TODO 3 = 17 abertos, TODO 5 = 2
e TODO 6 = 12 têm itens em aberto) e a explicação da aba **Tarefas**
(histórico da Task Queue, não o TODO). Nenhuma nota do Caderno foi
alterada.

---

## 14/11/2026 — Conserto do "menos inteligente": recusa, Query Router e papéis do OD

**Autor:** OpenCode (agente, modelo MiMo-V2.6-Flash) — sessão de 14/11
~16:10, a pedido do dono ("resolva o problema, faça o que for necessário").

### Criados

- Nenhum arquivo novo.

### Modificados

- `core/query_router.py` — `tokenizar_pt()`/`STOPWORDS_PT` de módulo (o
  tokenizer era método vinculado e derrubava o pickle) + `_dump_atomic`
  (tmp + `os.replace`).
- `core/orchestrator.py` — `_refusal_reason` só no início +
  `limpa_etiquetas_resposta()` em 7 pontos (em recusa, crua para o cache
  banir).
- `agents/nicky_virthy/personality.py` — linha do protocolo proíbe a
  etiqueta na resposta ao usuário.
- `tools/actions/actions.py` — action `role_list` (125 → 126);
  `core/intents.py` — detecção (com menção ao OD) e formatter;
  `core/security/permissions.py` — `role_list` para `user`/`familia`.
- Testes: `test_query_router.py` (persistência real — o antigo era cego),
  `test_resposta_transparente.py` (contrato novo + `limpa_etiquetas`),
  `test_intents.py` (`TestPapeisOD`), `test_security.py`,
  `test_actions_catalog.py` (handler) e contagens 125 → 126 em
  `test_actions_catalog/test_capabilities/test_mcp_od/test_orchestrator/
  test_orchestrator_action_registry`.
- Registro: `iniciar/session.json`, transcrição (§20), `docs/CHANGELOG.md`,
  `docs/ANALISE_SISTEMA_TODO.md` (3 checkboxes entregues).

### Intenção e estado

- **Intenção:** fechar os 3 diagnósticos da §18/§19 que faziam o OD parecer
  "menos inteligente": resposta errada sobre os próprios papéis (1 de 6),
  11 refazs/dia pelo detector de etiqueta e Query Router sem persistência.
- **Estado:** **gate completo 4700 passed / 16 skipped / 0 falha** (195 s);
  3 commits publicados (`868a3ad`, `809b7fc`, `3c134fb`); `od-core`
  reiniciado 17:03 (MainPID 2945652) com prova viva — `/health` ok=true
  (29 checks), "quais os tipos de usuários de OD" → `fastpath:role_list` em
  **28,9 ms**, mensagem LLM sem etiqueta e **0 refazs**, `Query Router model
  loaded` sem bootstrap.
- **Achado do gate:** o título da §18 colidiu no RAG com a irrelevante
  de aritmética (a pergunta sintética; nenhum grid recalibrava) — reescrito só o
  título nosso (citação do dono intacta), piso intocado (precedente 20/10).
- **Sem bump:** 1.45.0+2081 — correção de servidor, contrato do app intacto.

---

## 14/11/2026 — Retomada: publicação do lote da §16 e higiene do TODO

**Autor:** OpenCode (agente, modelo MiMo-V2.6-Flash) — sessão de 14/11 ~15:33,
a pedido do dono ("leia iniciar").

### Criados

- Nenhum arquivo novo.

### Modificados

- `docs/ANALISE_SISTEMA_TODO.md` — 2 checkboxes **entregues mas abertos**
  marcados com evidência: fila ligada com 1 worker + custo medido (§13) e
  métricas de retenção no `/health` (§15).
- `iniciar/session.json`, `iniciar/2026-11-14_conversa_omegadrakon.md` (§17),
  `iniciar/ATRIBUICOES.md` — registro desta retomada.
- **Publicou o lote órfão da §16** (autor: Freebuff/Buffy, feito e registrado
  mas nunca commitado): `integrations/api/server.py`,
  `tests/test_task_queue.py`, `docs/CHANGELOG.md`.

### Intenção e estado

- **Intenção:** a sessão anterior terminou antes de publicar a entrega da §16
  (métricas da fila no painel `/admin`) — risco de perda (regra 23). Fechar o
  ciclo: **validar → commitar → publicar** (regras 7.1/7.2).
- **Estado:** **gate completo 4684 passed / 16 skipped / 0 falha** com o lote
  na árvore; 2 commits em `origin/master`; prova viva (`/admin` com
  `#tq-resumo`, `/admin/tasks` e SSE com `queue`).
- **Sem bump / sem restart:** 1.45.0+2081; o `od-core` (15:07:44) já roda
  exatamente o código publicado.

---

## 14/11/2026 — Métricas da fila no painel /admin

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Modificados

- `integrations/api/server.py` — `queue` (snapshot) no `GET /admin/tasks` e
  no `snapshot` do SSE; linha `#tq-resumo` + `tqResumoFila()` na seção
  "Tarefas (Task Queue)".
- `tests/test_task_queue.py` — `test_lista_traz_o_snapshot_da_fila` + painel.
- `docs/CHANGELOG.md`, `iniciar/session.json`,
  `iniciar/2026-11-14_conversa_omegadrakon.md` (§16).

### Intenção e estado

- **Intenção:** os números do `/health` (14/11) também no painel, onde o dono
  já opera a fila.
- **Estado:** resumo no topo da seção (fila, executando, workers, dead letter,
  concluídas/teto, podadas, totais). Fila/execução contadas das tasks da
  tabela (SSE); disco vem do snapshot. Painel testado (27 testes na suíte).
- **Sem bump:** 1.45.0+2081.

---

## 14/11/2026 — Métricas da fila no /health

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Modificados

- `core/task_queue.py` — `snapshot()`, contador `pruned`, `_contar()`.
- `runtime/launcher.py` — `register_task_queue_health()` + chamada no
  `_run_api_forever`.
- `integrations/api/server.py` — bloco `task_queue` no `GET /health`.
- `tests/test_task_queue.py` — 5 testes novos.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/session.json`,
  `iniciar/2026-11-14_conversa_omegadrakon.md` (§15).

### Intenção e estado

- **Intenção:** a fila ligada em produção desde hoje só se enxergava por
  `/admin/tasks`; expor profundidade, workers, dead letter e retenção no
  agregado de saúde.
- **Estado:** bloco `task_queue` no `/health` (fora do cache de 8 s) +
  check não-crítico no HealthMonitor (workers parados/dead letter → degraded).
  `dead_letter` é o que está em disco; o acumulado segue em `metrics`.
- **Sem bump** (só servidor, contrato do app intacto): 1.45.0+2081.

---

## 14/11/2026 — Custo da fila com action de LLM longa

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Criados

- Nenhum arquivo versionado (harness de medição em `/tmp`, descartado).

### Modificados

- `docs/CHANGELOG.md` (subseção de custo com LLM na entrada da fila),
  `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/session.json`,
  `iniciar/2026-11-14_conversa_omegadrakon.md` (§14).

### Intenção e estado

- **Intenção:** completar o quadro de custo com o cenário mais pesado — uma
  action que chama o LLM local pela fila.
- **Método:** o catálogo (125 actions) não tem action de LLM; medido com fila
  em sandbox (1 worker) cuja action faz a mesma chamada HTTP do orchestrator
  (`OpenAICompatProvider._post_chat`) no llama-server local
  (qwen2.5-coder-3b-q4, 4 threads).
- **Resultado:** task de 600 tokens → **105,36 s**, **312% de 1 core no
  llama-server** (333,2 s de CPU), RSS ~1,9 GB; o processo **da fila** gastou
  **0,23% de 1 core** na mesma janela. Custo é do modelo, não da fila.
- **Custo de 1 worker:** task curta atrás de uma LLM de 14,89 s esperou
  **14,49 s**; action longa serializa a fila (avaliar 2 workers/prioridade).
- **Ruído declarado:** repouso do `od-core` de 3,2% → 8,5% no intervalo era o
  TTS da rádio (rajadas de 10–29%/s), não a fila; RSS estável ~262 MB.

---

## 14/11/2026 — Task Queue LIGADA em produção (1 worker), custo medido e pool do RAG

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Criados

- Nenhum arquivo novo versionado (medição em `/tmp`, descartada).

### Modificados

- `runtime/launcher.py` — `build_api_server` repassa `task_queue` ao
  `APIConfig` (fix do 503 permanente, commit `459decb`).
- `tests/test_task_queue.py` — `test_build_api_server_repassa_a_fila`.
- `memory/rag.py` — `TOP_K_CANDIDATOS` 24 → **32** (medição do gate; piso
  0.399/0.036 intocado).
- `tests/test_rag.py` — fixture `rag_real` com `top_k=32` + nota da
  recalibração de 14/11.
- `.env` (gitignored) — `OD_TASK_QUEUE_ENABLED=1`, `OD_TASK_QUEUE_WORKERS=1`.
- `docs/CHANGELOG.md` (§Task Queue, com a medição e o achado do RAG),
  `docs/ANALISE_SISTEMA_TODO.md` (checkbox da fila fechado),
  `iniciar/session.json`, `iniciar/2026-11-14_conversa_omegadrakon.md` (§13).

### Intenção e estado

- **Intenção:** ligar a fila com 1 worker e medir o custo real de CPU/RAM,
  sem bump (servidor não mudou o APK nem o contrato do app).
- **Custo medido** (`/proc`, 1 s): ocioso ligado 3,20% CPU / 231,1 MB (mediana)
  contra 3,65% / 226,0 MB desligado (+5,1 MB); rajada de 50 tasks reais
  14,03% CPU, +0,1 MB, 68 ms/task (execução p50 0,7 ms); retry real com dead
  letter em 6,01 s. Máquina: 4190 MB livres, 4 vCPUs.
- **Achados:** (1) `GET /admin/tasks` respondia 503 com a fila ligada —
  `task_queue` não chegava ao `APIConfig`; (2) o gate do RAG caiu porque o
  chunk-alvo estava na 24ª posição do pool (medição → 32).
- **Estado entregue:** gate **4679 passed / 16 skipped / 0 falha**,
  `test_rag.py` 93/93, `od-core` (unidade de usuário) reiniciado com MainPID
  2752075, `/health` 28/28, `/admin/tasks` 200 com 0 tarefas, journal 0 erros.
- **Limitação:** o custo medido não cobre action de LLM longa (o custo ali é
  do modelo, não da fila).

---

## 14/11/2026 — Release v1.45.0+2081 (APK com a aba Tarefas)

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Criados

- Nenhum arquivo de código novo (bump + build + registro).

### Modificados

- `.env` → `OD_VERSION=1.45.0` (gitignored)
- `core/capabilities.py` — fallback congelado
- `app/pubspec.yaml` — `1.45.0+2081`
- `integrations/api/server.py` — `_APP_VERSION_CODE = 2081`
- `site/index.html` (badge, card, versionCode), `site/historico.html`
  (1.45.0 + contagens 76 releases/10 na era final)
- `docs/CHANGELOG.md` → seção `## [1.45.0]`; `docs/README_VERSAO.md` → §1.45.0
- `site/OmegaDrakon.apk` e `site/OmegaDrakon-arm64.apk` (gitignored) —
  recompilados por `app/build_apk.sh`

### Intenção e estado

- **Intenção:** publicar a aba Tarefas no aparelho do dono, com o bump SemVer
  e o checklist de release completo.
- **Pronto/validado:** APK com versionName **1.45.0** / versionCode **2081**
  (`aapt`), completo 72.143.782 B e arm64 26.906.437 B; `/app/version`
  anuncia o mesmo build **com o sha256 do binário publicado**; gates Python
  **4678/16/0** e Flutter **analyze 0 issues / 223 passed**; `od-core`
  reiniciado (MainPID 2699533, `/health` 28/28, 0 erros).
- **Pendência:** ligar a fila em produção (`OD_TASK_QUEUE_ENABLED=1`) segue
  sendo decisão do dono.

---

## 14/11/2026 — Task Queue no painel `/admin` e no app (histórico com status e resultado)

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Criados

- `app/lib/screens/tasks_screen.dart` (aba "Tarefas")
- `app/test/tasks_api_test.dart` (5 testes)
- `app/test/tasks_screen_test.dart` (5 testes)

### Modificados

- `integrations/api/server.py` — bloco "Tarefas (Task Queue)" no
  `_ADMIN_PAGE_HTML` + JS `tqLoad/tqSse/tqAcao/tqRender` (filtro, retry, apagar,
  aviso de 503) e ligação no `carregarTudo`.
- `app/lib/services/od_api.dart` — `listTasks`, `retryTask`, `deleteTask` e o
  modelo `OdTask`.
- `app/lib/main.dart` — import, `TasksScreen` na posição 6 e a 8ª aba (Config
  foi para 7 no modo avançado).
- `tests/test_task_queue.py` — teste do painel com a seção nova.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/session.json`,
  `iniciar/2026-11-14_conversa_omegadrakon.md` (§11).

### Intenção e estado

- **Intenção:** tornar o histórico da fila visível fora das rotas `/admin`,
  com status e resultado, e permitir retry/apagar sem curl.
- **Pronto/validado:** painel e app implementados; **Python 4678 passed / 16
  skipped**; **`flutter analyze` sem issues**; **`flutter test` 223 passed / 2
  skipped**; JS do painel passou `node --check` (pegou uma aspa errada antes da
  publicação).
- **Pela metade (deliberado):** o **APK não foi recompilado** (deploy do app
  exige bump + ordem); sem prova visual (não há navegador na máquina). Fila
  segue desligada em produção.

---

## 14/11/2026 — Task Queue: histórico de concluídas com poda automática

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Criados

- Nenhum arquivo novo (subdiretório `completed/` é criado em runtime).
- Harness `/tmp/od_tq_historico.py` (fora do repo, descartado após a prova).

### Modificados

- `core/task_queue.py` — `completed_dir`, `keep_completed`
  (`OD_TASK_QUEUE_KEEP_COMPLETED`, 200), `_persist_completed`,
  `_prune_completed` (no `start()` e ao concluir), `get_task`/`list_tasks`
  passam a ler o histórico.
- `integrations/api/server.py` — `DELETE /admin/tasks/{id}` agora apaga também
  o registro de concluída (`tq.completed_dir`).
- `tests/test_task_queue.py` — 18 → 20 testes.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/session.json`,
  `iniciar/2026-11-14_conversa_omegadrakon.md` (§10).

### Intenção e estado

- **Intenção:** fechar o buraco medido no turno anterior — a task concluída
  virava 404 e a listagem nunca mostrava `completed`.
- **Pronto/validado:** sandbox com API + registry + catálogo reais e
  `KEEP_COMPLETED=2`: 3 tasks reais → `GET` da recente 200 `completed` com
  `result=true`, `?status=completed` count=2, mais antiga podada (404). Gate
  **4677 passed / 16 skipped / 0 falha**.
- **Pela metade (deliberado):** a fila continua **desligada em produção**;
  mostrar o histórico no painel/app fica no TODO.

---

## 14/11/2026 — Task Queue provada em sandbox (task real, retry e dead letter)

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Criados

- `/tmp/od_tq_prova.py` (harness da prova — **fora do repo**, descartável)

### Modificados

- `core/task_queue.py` — `registry.execute(..., request_id=)` → `session_id=`.
  O registry real não aceita `request_id`; **toda** task morria com `TypeError`.
- `integrations/api/server.py` — `DELETE /admin/tasks/{id}` passou a apagar em
  `tq.dead_letter_dir` (antes usava o caminho global e deixava o arquivo).
- `tests/test_task_queue.py` — 16 → 18 testes (task real no registry real;
  DELETE do dead letter no `queue_dir` da instância).
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (checkbox novo do achado,
  item da fila atualizado), `iniciar/session.json` e
  `iniciar/2026-11-14_conversa_omegadrakon.md` (§9). Nenhuma regra alterada.

### Intenção e estado

- **Intenção:** ligar a fila num teste controlado, provar task real, medir
  retry e dead letter — e não confiar no gate, que usava um registry falso.
- **Pronto/validado:** gate **4675 passed / 16 skipped / 0 falha**; sandbox
  com API + registry + catálogo reais (completed 1,0 s; retry 1,0 s → 2,7 s →
  dead letter 6,5 s; DELETE remove o arquivo e o `GET` volta 404).
- **Pela metade (deliberado):** a fila **continua desligada em produção**
  (`OD_TASK_QUEUE_ENABLED=0`) — ligar é decisão do dono. Task concluída some
  da API (retenção de histórico a decidir) — checkbox no TODO.

---

## 14/11/2026 — Fechamento do lote de 13/11 (Task Queue, Semantic Cache, OpenAI, web_search, escopo, pg_dump)

**Autor:** Freebuff (Buffy) — sessão de 14/11.
**Origem do lote:** **NÃO IDENTIFICADA** — o código de 13/11 estava na árvore,
fora do git e sem registro. Foi encontrado na retomada de 14/11 e fechado por
Buffy (não presuma que o autor destas linhas seja o mesmo do lote).

### Criados

- `core/task_queue.py` (lote 13/11)
- `tests/test_task_queue.py` (Buffy — 16 testes; cobre também os defeitos
  abaixo)
- `runtime/pg_dump_diario.py`, `systemd/od-pg-dump.service`,
  `systemd/od-pg-dump.timer`, `tests/test_pg_dump_diario.py` (lote 13/11)
- `docs/ARCHITECTURE_v2.md`, `docs/NV_DAG_SCHEDULER_REFERENCE.md`,
  `pyproject.toml` (lote 13/11)
- `iniciar/ATRIBUICOES.md` (Buffy)

### Modificados

- `integrations/api/server.py` (lote 13/11) — Buffy removeu a **duplicata** de
  `_task_queue_or_503`, trocou `_query_param` (inexistente → 500) por
  `parse_qs` e fez o SSE emitir status **uma vez** por mudança.
- `runtime/launcher.py` (lote 13/11) — separado em dois commits por assunto
  (fila / IA) por Buffy.
- `core/llm.py` (lote 13/11) — `OpenAIProvider`; Buffy acrescentou o newline
  final que faltava.
- `core/security/scope.py` + `tests/test_scope_audit.py` (lote 13/11).
- `tools/actions/actions.py` + `tests/test_actions_catalog.py`,
  `tests/test_intents.py`, `tests/test_capabilities.py`, `tests/test_mcp_od.py`,
  `tests/test_orchestrator.py`, `tests/test_orchestrator_action_registry.py`,
  `tests/test_api.py` — contagens 123→125 e rotas 124→130 (Buffy).
- `iniciar/RULES.md` (regra 23), `iniciar/session.json`,
  `iniciar/2026-11-14_conversa_omegadrakon.md`,
  `docs/ANALISE_SISTEMA_TODO.md`, `docs/CHANGELOG.md` (Buffy).

### Intenção e estado

- **Intenção do lote:** fechar R1 (fila com retry/dead letter), ligar I1
  (Semantic Cache), trazer OpenAI para a cadeia, criar actions de pesquisa e de
  Mapa de Força, liberar `/tmp` no escopo e automatizar o dump do Postgres.
- **Estado ao ser encontrado:** `pg_dump` já vivo (timer instalado, 3 dumps);
  o resto **sem commit, sem teste e quebrado** — 14 falhas no gate (contagens
  fixas), fila executando a mesma task 2×, JSON de retry apagado, dead letter
  fora do diretório da instância, `GET /admin/tasks` em 500.
- **Estado entregue por Buffy (14/11):** tudo corrigido, `tests/test_task_queue.py`
  novo, **gate 4656 passed / 16 skipped / 0 falha**, commits por assunto,
  publicado em `origin/master` e `od-core` reiniciado com prova viva.
- **O que continua pendente (deliberadamente):** ligar a `web_search` à intenção
  "pesquise na internet…" (`core/intents.py` intocado); `OD_OPENAI_AUTO` só
  testa a existência da chave, não o crédito; `web_search` não está na lista do
  papel `user`; fila desligada por padrão (`OD_TASK_QUEUE_ENABLED=0`).

---

## Antes de 14/11/2026

O projeto não tinha este livro-caixa. O histórico anterior está em
`iniciar/session.json` e nas transcrições `iniciar/YYYY-MM-DD_conversa_omegadrakon.md`
(que registram pedido, feito, testes e decisões, mas **não** nomeiam o autor de
cada lote).

---

## 14/11/2026 — Cota dos providers de LLM visível/alertada no /health (TODO 681, sem bump)

**Autor:** OpenClaude — sessão de 14/11, a pedido do dono ("comece pelo que achar melhor… verifique sempre").

### Criados

- `tests/test_llm_quota_health.py` — 11 testes do check `llm_quota` e de `_limite_de`/`status_quota`.

### Modificados

- `core/resilience.py` — `status_quota()` nova (com `pct_used`); `_limite_de()` nova (env `OD_QUOTA_<PROVIDER>_LIMIT`); Groq provisório **500** em `_QUOTA_DEFAULTS` (cota real desconhecida — aprende no 429 real, ajustável via `OD_QUOTA_GROQ_LIMIT`); `_QUOTA_LOCK` `Lock` → **`RLock`** (deadlock `record_usage → get_quota` na mesma thread, achado pelos testes).
- `runtime/launcher.py` — check não-crítico `llm_quota` no `/health` (29 → 30 checks): todos os providers com `pct_used`, `degraded` acima de `OD_QUOTA_ALERTA_PCT` (padrão 80%) ou esgotado.
- `docs/ANALISE_SISTEMA_TODO.md` — checkbox 681 marcado [x] com nota de entrega.
- `docs/CHANGELOG.md` — entrada "sem bump" no topo (1.45.0/2081 mantido: só backend, sem app/APK/painel novo; sem toolchain Android na máquina e o app não mudou).
- `iniciar/session.json`, `iniciar/2026-11-14_conversa_omegadrakon.md` (§22).

### Intenção e estado

- **Intenção:** quando a cota de um provider esgota, a resposta caía silenciosamente para o modelo local 3B sem ninguém saber por quê — tornar a cota visível e alertada no `/health` (decisões do dono: todos os providers, alerta 80%, limite Groq provisório 500 aprendido no bloqueio real, só o /health).
- **Pronto/validado:** 66 testes passed (`test_llm_quota_health` + `test_resilience` + `test_health` + `test_launcher_health_external`); `py_compile` OK; od-core reiniciado verde (MainPID 3322791, NRestarts=0); `/health` HTTP 200 com 30 checks e `llm_quota up`: `gemini 0% (0/20); groq 0% (0/500); openai 0% (0/100)`; journal limpo. `data/llm_quota.json` ainda não existe (grava no primeiro uso real).
- **Pela metade (deliberado):** o limite real do Groq (500 é provisório) — será ajustado via `OD_QUOTA_GROQ_LIMIT` quando um 429 bloquear de verdade.

---

## 17/11/2026 — Leitura do iniciar e diagnóstico completo do txt.txt

**Autor:** Antigravity (Gemini 3.8 Flash) — sessão de 17/11, a pedido do dono ("leia inicar e txt").

### Criados

- `iniciar/2026-11-17_conversa_omegadrakon.md` (§1).

### Modificados

- `iniciar/session.json` — atualizado com checkpoint da retomada e diagnóstico dos 6 pontos do `txt.txt`.
- `iniciar/ATRIBUICOES.md` — esta entrada no livro-caixa.

### Intenção e estado

- **Intenção:** atender à ordem do dono de ler `iniciar/` e `txt.txt`, levantando com precisão os fatos sobre as músicas do Raul Seixas no acervo, desenhar a solução para exclusão de músicas indesejadas e exceções de cantores bloqueados, e realizar a análise do site GSN Offline e dos vídeos de resiliência digital (apps off-grid e Meshtastic LoRa).
- **Pronto/validado:** varredura completa do acervo real (`/home/alex/dados/musicas/acervo.db`), logs do pipeline, backups históricos e AzuraCast; análise técnica detalhada do site `gsnoffline.com` e extração de legendas/conteúdo dos dois vídeos do YouTube; transcrição do dia e checkpoint gravados.
- **Pela metade (deliberado):** implementação das rotas e filtros da rádio aguardando confirmação do dono sobre as opções propostas.

---

## 17/11/2026 — Investigação da lista de Raul Seixas (Pedido 11)

**Autor:** Antigravity (Gemini 3.8 Flash) — sessão de 17/11, a pedido do dono.

### Modificados

- `iniciar/2026-11-17_conversa_omegadrakon.md` (§2 adicionada).
- `iniciar/session.json` (checkpoint atualizado).

### Intenção e estado

- **Intenção:** descobrir por que apenas "Metamorfose Ambulante" foi baixada e onde foram parar as outras músicas da lista de Raul Seixas.
- **Achado / Causa Raiz:** comprovado via auditoria do banco `data/radio_pedidos.db` e do log `logs/radio_link_11.log`. O sanitizador `link_do_youtube()` em `integrations/radio_pro.py` possuía um bug: se a URL copiada pelo usuário fosse de reprodução (`/watch?v=...&list=...`), ele descartava o parâmetro `list` e salvava apenas o link do vídeo individual. Por isso o worker recebeu 1 faixa só e nunca chamou `_baixar_resto()`.
- **Pronto:** diagnóstico completo e reprodução do bug documentados.

---

## 17/11/2026 — Correção do link_do_youtube: preservação de playlists em URLs /watch e youtu.be

**Autor:** Antigravity (Gemini 3.8 Flash) — sessão de 17/11, a pedido do dono ("sim, corrija").

### Modificados

- `integrations/radio_pro.py` — `link_do_youtube`: preserva `list=` em URLs `/watch`, `/playlist` e `youtu.be` com `&v=...`.
- `integrations/radio_link.py` — `processar_pedido`: se a URL trouxer `&v=...`, move essa faixa para o topo (`entradas[0]`) para tocar primeiro, chamando `_baixar_resto()` para as demais.
- `tests/test_radio_link.py` — testes atualizados e teste novo `test_playlist_com_video_especifico_toca_ele_primeiro`.
- `docs/CHANGELOG.md` — entrada de 17/11 (sem bump) no topo.
- `iniciar/session.json` — checkpoint atualizado.

### Intenção e estado

- **Intenção:** resolver a causa raiz que impediu o download das outras faixas da lista de Raul Seixas; links com vídeo e lista juntos agora preservam a lista inteira.
- **Pronto/validado:** 170 testes de rádio passando (incluindo `test_radio_link` e `test_radio_cobertura`); 385 testes de rádio e API passando sem nenhuma falha.

---

## 17/11/2026 — Janela de decisão de 24 h (cantor ou música bloqueada) e excluir sem bloquear

**Autor:** Codebuff (Buffy) — sessão de 17/11, a pedido do dono: *"se a musica
for de um cantor bloqueado, vai me avisar e tenho 24 horas para decidir, se não
permitir ela é automaticamente apagada"*, *"o mesmo para certas musicas, as
vezes o cantor é permitido, mas uma musica especifica não"* e *"musicas
apagadas podem voltar a ser baixadas, posso apagar simplesmente por achar uma
versão melhor"*.

### Modificados

- `integrations/radio_cantores.py` — `HORAS_DECISAO` (24 h), prazo no
  registro, `decidir()`, `aviso_de_decisao()`, `pendentes()` com tempo
  restante, `limpar_tocados()` só apaga no vencimento, exclusão sem bloqueio.
- `integrations/radio_link.py` — pedido avulso não é recusado; aviso ao dono
  com prazo e quem pediu.
- `integrations/radio_pro.py` — catálogo também marca música bloqueada.
- `integrations/api/server.py` — `POST /api/radio/musicas/decisao`, `decisoes`
  no GET, exclusão com `bloquear=false`, bloco "Decisões pendentes (24 h)" no
  painel.
- `site/radio-pro.html` — mesmo bloco no card de curadoria; confirm de
  exclusão sem bloqueio.
- Testes: `tests/test_radio_cantores.py`, `tests/test_radio_curadoria.py`,
  `tests/test_radio_cobertura.py`, `tests/test_radio_link.py`,
  `tests/test_api.py` (rotas 136 → 137).
- Registro: `docs/CHANGELOG.md` (topo), `docs/ANALISE_SISTEMA_TODO.md`,
  `iniciar/2026-11-17_conversa_omegadrakon.md` (§6 corrigida + §7),
  `iniciar/session.json`.

### Intenção e estado

- **Intenção:** o ouvinte pode gostar de um cantor que o dono não gosta (e
  vice-versa, o cantor é permitido mas uma música não) — a faixa toca uma vez,
  o dono é avisado e decide em 24 h; sem decisão, sai sozinha. Excluir do
  acervo deixou de bloquear, para poder baixar uma versão melhor depois.
- **Pronto/validado:** gate completo **5370 passed / 16 skipped / 0 falha**
  (203,89 s, exit 0), `node --check` no painel e na página.

---

## 17/11/2026 — Decisões da rádio no app Android (1.45.1+2082)

**Autor:** Codebuff (Buffy) — sessão de 17/11, a pedido do dono: *"Mostrar as
decisões pendentes também no app Android"*.

### Modificados

- `app/lib/services/od_api.dart` — `OdDecisaoRadio`,
  `listRadioDecisoes()`, `decidirRadio()`.
- `app/lib/screens/dashboard_screen.dart` — card "Decisões pendentes (24 h)"
  no Painel (admin), com Permitir / Apagar já.
- `app/test/dashboard_radio_test.dart` — 9 testes novos.
- `app/pubspec.yaml` (1.45.1+2082), `.env` (OD_VERSION), fallback em
  `core/capabilities.py`, `integrations/api/server.py`
  (`_APP_VERSION_CODE`), `site/index.html`, `site/*.apk`.
- Registro: `docs/CHANGELOG.md` [1.45.1], `docs/README_VERSAO.md` [1.45.1],
  `iniciar/2026-11-17_conversa_omegadrakon.md` §8, `iniciar/session.json`.

### Intenção e estado

- **Intenção:** o dono decide a faixa em 24 h pelo celular, sem abrir o site.
- **Pronto/validado:** `flutter analyze` 0 issues · `flutter test` 237 passed
  / 2 skipped · gate Python 5370 passed · APKs 1.45.1+2082 publicados em
  `site/` (antigos em `backups/apk-v1.45.0-2081/`).

---

## 17/11/2026 — Push FCM ao entrar na decisão de 24 h

**Autor:** Codebuff (Buffy) — sessão de 17/11, a pedido do dono: *"Enviar
push FCM quando uma faixa entrar na janela de decisão de 24 h"*.

### Modificados

- `integrations/radio_cantores.py` — push na primeira marcação, com data
  `origem=radio-decisao`, e monta o serviço quando o processo não tem launcher.
- `tests/test_radio_cantores.py` — +5 testes (envio único/payload,
  idempotência, falha do FCM, serviço construído no subprocesso).
- Registro: `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`,
  `iniciar/2026-11-17_conversa_omegadrakon.md` §9, `iniciar/session.json`.

### Intenção e estado

- **Intenção:** o dono saber na hora, no celular, que tem 24 h para decidir.
- **Pronto/validado:** gate **5375 passed / 16 skipped / 0 falha**; push
  `enabled` com 1 aparelho e notificação de teste entregue após o restart.

---

## 17/11/2026 — Lembrete de push 2 h antes do prazo da decisão

**Autor:** Codebuff (Buffy) — sessão de 17/11, a pedido do dono: *"Enviar um
lembrete de push 2 horas antes do prazo vencer"*.

### Modificados

- `integrations/radio_cantores.py` — `HORAS_LEMBRETE`, lembrete dentro de
  `limpar_tocados()` (uma vez por faixa, `lembrete_em`) e a chave `lembretes`
  no retorno.
- `tests/test_radio_cantores.py` (+4) e `tests/test_radio_cobertura.py`
  (retorno com `lembretes`).
- Registro: `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`,
  `iniciar/2026-11-17_conversa_omegadrakon.md` §10, `iniciar/session.json`.

### Intenção e estado

- **Intenção:** avisar no celular quando o prazo está perto, para o dono não
  perder a faixa por esquecimento.
- **Pronto/validado:** gate **5379 passed / 16 skipped / 0 falha**.

---

## 17/11/2026 — Timer próprio da janela de decisão no core

**Autor:** Codebuff (Buffy) — sessão de 17/11, a pedido do dono: *"Mover a
checagem de lembretes e vencimentos para um timer periódico do core"*.

### Modificados

- `runtime/launcher.py` — `_run_radio_decisoes_forever` e o loop
  supervisionado `radio-decisoes` (60 s, `asyncio.to_thread`, erro contido).
- `tests/test_launcher_supervisor.py` — +3 testes do timer.
- Redação dos docs desta sessão: "campo `X`" → "chave `X`" (colisão com a
  calibração do RAG, corrigida na causa).
- Registro: `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`,
  `iniciar/2026-11-17_conversa_omegadrakon.md` §11, `iniciar/session.json`.

### Intenção e estado

- **Intenção:** lembrete e vencimento com relógio próprio, sem depender de a
  rádio trocar de faixa.
- **Pronto/validado:** gate **5382 passed / 16 skipped / 0 falha**; loop no ar
  após o restart.

---

## 17/11/2026 — Resumo diário das faixas apagadas pela janela

**Autor:** Codebuff (Buffy) — sessão de 17/11, a pedido do dono: *"Criar um
resumo diário das faixas apagadas automaticamente pela janela de 24 h"*.

### Modificados

- `integrations/radio_cantores.py` — `motivo_fim`/`apagada_em` no registro,
  `resumo_diario()` e `enviar_resumo_se_devido()` (uma vez por dia, hora
  configurável, estado em `data/`).
- `runtime/launcher.py` — o loop `radio-decisoes` chama o resumo.
- `tests/test_radio_cantores.py` (+6) e `tests/test_launcher_supervisor.py`
  (dublê com `enviar_resumo_se_devido`).
- Registro: `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`,
  `iniciar/2026-11-17_conversa_omegadrakon.md` §12, `iniciar/session.json`.

### Intenção e estado

- **Intenção:** fechar o dia com o que a janela apagou sem decisão do dono,
  em vez de deixar isso só no log.
- **Pronto/validado:** gate **5388 passed / 16 skipped / 0 falha**.

---

## 17/11/2026 — P0: cache de conversa não serve resposta inventada

**Autor:** Codebuff (Buffy) — sessão de 17/11, a pedido do dono: *"Fechar o
P0: impedir que o llm_cache sirva resposta inventada de conversa comum"*.

### Modificados

- `core/orchestrator.py` — `cache_serve_reason()` (guarda de leitura),
  `_resposta_do_cache()` (valida, apaga a entrada inválida e devolve MISS) nos
  dois pontos de leitura (stream e grafo, cache exato e semântico); prefixo
  `"⚠️ não executei nada"` em `_CACHE_BAN_PREFIXES`. **Não** foi banida a frase
  "Estado verificado." (é a assinatura da Guardian no prompt de personalidade)
  nem a resposta de modelo local — as duas regras foram testadas, medidas e
  retiradas (ver transcrição §19).
- `tests/test_orchestrator.py` — `TestCacheDeConversa` (7 testes).
- `tests/test_radio_cantores.py` — assertion do dia do resumo passou a usar a
  data **local** (ficava vermelha entre 21h e meia-noite local).
- Registro: `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (checkbox
  fechada), `iniciar/2026-11-17_conversa_omegadrakon.md` §19, `iniciar/session.json`.

### Intenção e estado

- **Intenção:** o cache era lido antes das guardas do turno; sem revalidar na
  leitura, resposta inventada (e entrada gravada antes de um ban novo) era
  servida para sempre.
- **Pronto/validado:** gate completo **5381 passed / 19 skipped / 0 falha**;
  `tests/test_orchestrator.py` + `tests/test_api.py` 277 passed. Cache vivo:
  4 de 144 entradas recusadas pelas guardas (invenção de agenda + avisos).
- **Sem bump:** correção de servidor, contrato do app intacto (1.46.0+2083).

## 2026-11-18 — Anti-falso-sucesso de rádio/volume no `llm_cache` (sem bump)

**Autor:** Buffy (Codebuff) — continuação do P0 nº 1 de 17/11.

### Arquivos

- `core/orchestrator.py` — `_FAKE_ACTION_RES` ampliado: participíos de
  mídia/casa na construção "… com sucesso" e `volume … para N%`.
- `tests/test_orchestrator.py` — teste novo
  `test_falso_sucesso_de_midia_e_casa_tambem_e_pego` (7 inventadas recusadas,
  7 respostas reais da rota aceitas).
- Registro: `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (P0 nº 1
  riscado como ENTREGUE; checkbox de mídia/casa fechado),
  `iniciar/2026-11-18_conversa_omegadrakon.md` §12, `iniciar/session.json`
  (`falso_sucesso_midia_2026_11_18`).

### Intenção e estado

- **Intenção:** a guarda de leitura do cache (17/11) reusava um
  anti-falso-sucesso que só conhecia agenda; invenções de rádio/volume
  passavam para o dono e para o cache.
- **Base:** a saída real de `intents._formata_radio` nunca usa "com sucesso"
  nem "volume definido para" — logo essas construções denunciam invenção.
- **Pronto/validado:** `tests/test_orchestrator.py` **76 passed**; cache vivo
  (145 entradas) recusa **3 novas**, todas invenções, e **0 legítimas**;
  `od-core` reiniciado (PID 459066), `/health` `ok=true`, journal limpo.
- **Limite:** estado sem "com sucesso" ("Radio ligada.") continua passando —
  pode ser leitura verdadeira.

## 2026-11-18 — I2 (Hybrid Search) fiado no RAG, medido e mantido OFF (sem bump)

**Autor:** Buffy (Codebuff) — P1 nº 5 do backlog.

### Arquivos

- `core/hybrid_search.py` — `tokenizar()` e `fundir_rrf()` em nível de módulo;
  `HybridRetriever` passou a usá-los (comportamento igual).
- `memory/vector.py` — propriedade pública `provider` (o candidato lexical
  precisa do MESMO provider da indexação para o cosseno ser comparável).
- `memory/rag.py` — `hibrido=` / `OD_RAG_HIBRIDO` (padrão `0`); `sync()` monta
  `BM25Index` sobre os mesmos chunks; `_consultar()` une os candidatos
  lexicais por `doc_id` com cosseno real; métrica `lexicais`.
- `tools/medir_rag_hibrido.py` (novo) — medidor reproduzível antes/depois.
- `tests/test_rag.py` — `TestHibrido` (5 testes).
- Registro: `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`,
  `iniciar/2026-11-18_conversa_omegadrakon.md` §13, `iniciar/session.json`
  (`i2_rag_hibrido_2026_11_18`).

### Intenção e estado

- **Intenção:** o HashEmbedding não vê termo raro; o BM25 vê. O item pedia
  fiação **com** medição — e a medição é o que decide o default.
- **Medido (3815 chunks):** relevantes 8/8 → 8/8; paráfrases 6/6 → 6/6;
  **irrelevantes bloqueadas 8/8 → 6/8**. Ganho pontual: o chunk
  `[1.24.2] — EVAL DO ASSISTENTE` passou a entrar no bloco do golden de eval.
- **Causa da regressão:** candidato lexical com `overlap=1.0` só por conter o
  termo raro (ex.: "basquete" num chunk de release); o overlap-IDF foi
  calibrado para candidatos densos.
- **Decisão:** fiação pronta, **OFF por padrão**. Ligar exige recalibrar o
  piso com grid medido — não se afrouxa asserção para a novidade caber.
- **Efeito colateral:** o texto novo no corpus mexeu no IDF e derrubou o gate;
  corrigido reescrevendo o nosso texto ("invenções reais" → "invenções de
  fato"), sem tocar no piso.
- **Validado:** gate completo **5465 passed / 19 skipped / 0 falha**;
  `test_rag` 98 passed; `od-core` reiniciado, `/health` `ok=true`.
