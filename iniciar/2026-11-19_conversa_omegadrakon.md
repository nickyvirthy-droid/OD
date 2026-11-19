# Conversa OmegaDrakon — 19/11/2026

Sessão entre o dono e o assistente. Registro a cada troca (regra 4 de
`iniciar/RULES.md`). Continuação de `2026-11-18_conversa_omegadrakon.md`.

---

## §1 — Retomada "leia iniciar": estado real e o lote do Vigia da Rede (não registrado)

**Pedido (verbatim):** `leia iniciar`

### 1. O que foi lido (regra 3)

- `iniciar/README.md`, `iniciar/RULES.md` (24 regras), `iniciar/session.json`
  (últimas entradas: `espelho_llm_p0_4_2026_11_18`, 18/11 18:55, e as entregas
  de 18/11 — aviso de decisão de 24 h e artista do Raul).
- `iniciar/2026-11-18_conversa_omegadrakon.md` §13–§15 e o topo de
  `iniciar/ATRIBUICOES.md`.
- `txt.txt` (**vazio**, 19/11 04:50 — nenhum pedido novo), `git status`/`log`,
  o brief multi-IA (`tools/brief_multi_ia.py`), o serviço e o `/health`.

### 2. Estado medido (19/11 14:57)

- **Git:** `HEAD == origin/master == 3352c2f`; versão **1.46.0+2083**.
- **Serviço:** `od-core` **active**, MainPID **542567**, NRestarts=0, ativo
  desde **18/11 20:03:41**; `/health` `ok=true`, **30 checks**, nenhuma falha.
- **TODO:** P0 nº 1–4 e P1 nº 5 marcados ENTREGUE (18/11); P1 nº 6 (modo
  colapso declarado) segue aberto.
- **`txt.txt`:** vazio — o dono não deixou pedido novo.

### 3. Achado principal: lote de 19/11 na árvore, não registrado

`git status` mostra **15 arquivos modificados** (+1400/−48), com mtimes de
**hoje 13:39–14:14**, e **nada** em `iniciar/`, `docs/CHANGELOG.md` ou no
TODO. Autor: **origem não identificada** (regra 23) — não foi revertido nem
commitado (regra 7).

O que o diff faz, por inteiro: fecha o **Vigia da Rede** como canal de
resposta, exatamente a lacuna do alerta `net:dispositivo-novo` (o aviso
mandava "responda quando reconhecer" sem dizer se o aparelho ainda está na
rede nem onde responder):

| Arquivo | Mudança |
|---|---|
| `tools/monitor/network_watchdog.py` | `vizinhos_sem_ping()` (leitura ARP barata, sem forçar ping) e `pendentes_ricos()`: cada pendente ganha `nome`, `ultima_vez` e `conectado` (ARP **ou** UI do roteador) na linha `tipo=estado` |
| `integrations/notifier.py` | `formata_dispositivo()` pura: `MAC — nome (fabricante, ip) · conectado agora` / `fora da rede · visto há 2 h 14 min · pendente desde 16/11`; sem o campo novo **não inventa status** |
| `tools/actions/actions.py` | actions **`network_conhecer`** e **`network_bloquear`** (alvo = MAC, IP ou **número** da listagem; vazio = o único pendente; vários = listagem numerada, nunca escolhe sozinho); catálogo 126 → **128** |
| `core/intents.py` | fast path `reconhece o 2` / `bloqueia o 2` → essas actions, com contexto de rede obrigatório ("reconhecer meu erro" segue para o LLM); resposta formatada nunca cai no LLM |
| `core/orchestrator.py` | `network_conhecer`/`network_bloquear` no gate de papel (negação honesta) e `network_bloquear` como escrita sensível (human-in-the-loop) |
| `integrations/api/server.py` | `GET /admin/vigia`, `POST /admin/vigia/conhecer`, `POST /admin/vigia/bloquear` (`_require_admin`) + seção "Vigia da Rede" no `/admin` com status, última vez e botões |
| testes | +7 arquivos de teste ajustados/criados (contagens 128, `test_network_watchdog`, `test_notifier`, `test_intents`, `test_api`) |

### 4. Verificação feita neste turno

- `pytest` dos 9 arquivos afetados (`network_watchdog`, `notifier`, `intents`,
  `api`, `actions_catalog`, `capabilities`, `orchestrator`,
  `orchestrator_action_registry`, `mcp_od`): **751 passed**, exit 0 (21,7 s).
- **O lote NÃO está no ar:** o `od-core` subiu em 18/11 20:03, antes das
  edições; `GET /admin/vigia` responde **404** (rota não registrada no
  processo vivo).
- **Pendências do lote (do que falta para fechar):** seção no
  `docs/CHANGELOG.md`, checkbox no `docs/ANALISE_SISTEMA_TODO.md`, registro em
  `iniciar/` (este arquivo) e **gate completo** — só o recorte de 751 passou.

### 5. O que este turno NÃO fez

- Não reverteu, não corrigiu e **não commitou** o lote de origem desconhecida
  (regra 24.3 / regra 7): trabalho de outra IA se registra e se continua, não
  se apaga.
- Não reiniciou o `od-core` (deploy da rota nova exige ordem do dono — regra
  7.1/7.3; o restart liberaria `/admin/vigia` e o boolean `conectado` nos
  alertas).
- Nenhum código alterado neste turno: só leitura, testes e registro.

### 6. Próximo passo exato

Decidir o destino do lote do Vigia da Rede: (a) assumir e fechar (CHANGELOG +
TODO + gate completo + commit + restart verde, o que põe `/admin/vigia` e os
botões no ar), ou (b) deixar como está até a próxima IA que o reivindicar. A
opção (a) é a única que entrega o que o dono pediu no alerta ("diga se o
aparelho ainda está conectado" e "onde responder").

---

## §2 — Ordem do dono: "assuma e feche o lote do Vigia da Rede" (19/11)

**Pedido (verbatim):** *"Assuma e feche o lote do Vigia da Rede: documente, rode
o gate completo, commite e faça o restart verde com prova viva"*.

### 1. Revisão do diff (antes de assumir)

Lido inteiro. O que sustenta a segurança:

- `network_conhecer`/`network_bloquear` **não** estão nas listas de `user`/
  `familia` (`core/security/permissions.py`) — só o admin (`"*"`) executa.
- `network_bloquear` entrou em `ACOES_SENSIVEIS_PADRAO` (human-in-the-loop);
  as duas entraram em `_PAPEL_GATE_ACTIONS` do orquestrador, então a negação
  vira resposta honesta em vez de o LLM inventar "reconhecido".
- Rotas `/admin/vigia*` com `_require_admin` (401 sem credencial, medido).
- Formatadores puros: `formata_dispositivo()` e `_formata_vigia()` só afirmam
  o que a fonte devolveu — sem o campo `conectado`, nada de status.
- `reemite_estado()` faz o aviso sumir na hora (não espera o ciclo de 5 min);
  bloqueio confirmado encerra a pendência com nota, sem marcar "conhecido".
- Fast path exige **contexto de rede**: "quero reconhecer meu erro" → `None`.

### 2. Gate: um vermelho real, corrigido na causa

- **1º run:** `1 failed / 5509 passed / 19 skipped` —
  `tests/test_corpus_frases_dono.py` cobrava a frase *"onde foi parar a lista
  de musicas do raul seixas"* no `txt.txt`, que o dono **zerou hoje** (regra 20:
  canal efêmero). O defeito era o corpus apontar para arquivo apagável.
- **Correção:** origem passou para `iniciar/2026-11-17_conversa_omegadrakon.md`,
  onde a frase está literal (o assert de existência **não** foi afrouxado).
- **2º run (final): 5510 passed / 19 skipped / 0 falha**, exit 0 (228,43 s);
  `test_corpus_frases_dono` 32 passed.

### 3. Deploy verde com prova viva

- `systemctl --user restart od-core` → **MainPID 1677502**, NRestarts=0, ativo
  desde **15:15:05**; journal `-p err` **0 entradas**.
- `/health` → `ok=true`, **30 checks**, nenhuma falha.
- `GET /admin/vigia` → **200** com 1 pendente real: `A2:E5:1D:2D:4E:91`,
  `conectado=false`, `ultima_vez=15:14:25`, `desde=16/11` (ciclos 8284); sem
  credencial → **401**.
- Fast path no código vivo: `reconhece o dispositivo` →
  `('network_conhecer', {'alvo': ''})`; `bloqueia o 2` →
  `('network_bloquear', {'alvo': '2'})`; `quero reconhecer meu erro` → `None`.
- Alerta formatado: `A2:E5:1D:2D:4E:91 (desconhecido, 192.168.0.186) · fora da
  rede · visto há 1 min · pendente desde 16/11`.

### 4. Atribuição (regra 23)

- **Implementação:** origem desconhecida (achada pronta na árvore, 13:39–14:14).
- **Fechamento** (revisão, correção do corpus, documentação, gate, commit,
  restart): **Freebuff (Buffy)**, 19/11.
- **Modificados:** os 6 arquivos de código + 10 de teste do lote; no fechamento,
  `tests/test_corpus_frases_dono.py`, `docs/CHANGELOG.md`,
  `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/session.json`,
  `iniciar/ATRIBUICOES.md` e esta transcrição.
- **Sem bump** (1.46.0+2083): servidor/painel, contrato do app intacto.

### 5. Limites

- Nenhum aparelho real foi reconhecido/bloqueado no teste (a ação mexe no
  inventário e, no bloqueio, no roteador): a prova do fast path é de detecção.
- O pendente de 16/11 segue pendente — decisão do dono (reconhecer/bloquear).

---

## §3 — "Decisão de 24 h voltou a aparecer": era o APP republicando a notificação

**Pedido (verbatim):** *"Decisão de 24 h voltou a aparecer, ja estava resolvido,
regrediu porque?"*

### 1. Servidor: limpo (medido, não presumido)

- `data/radio_apagar_depois.json` **vazio** (2 bytes, mtime 17/11 06:36);
  `/api/radio/musicas` com `decisoes: []`.
- Journal do usuário desde 18/11: **nenhum** push com título "Decisão de 24 h"
  (só os pushes horários de status, título "OmegaDrakon").
- A correção de 18/11 (`02a1a31`) está em `HEAD` e o `od-core` reiniciou depois
  dela — o servidor **não** regrediu.

### 2. Causa real: `app/lib/services/push_service.dart`

| Linha | Comportamento | Efeito |
|---|---|---|
| `FirebaseMessaging.onMessageOpenedApp.listen(show)` | ao **tocar** na notificação, chamava `show()` | republicava a mesma notificação local |
| `getInitialMessage()` + `show(initial)` | a cada abertura do app disparada por notificação | republicava de novo |

A notificação tocada já está na bandeja (quem exibiu foi o Android): cada
toque/abertura repostava o aviso antigo — inclusive um de prazo vencido e já
resolvido. Era isso que parecia "regressão".

### 3. Correção

- Só o **foreground** (`onMessage`) exibe notificação local — em
  background/terminado o sistema já mostra.
- `onMessageOpenedApp` e `getInitialMessage()` passam a **consumir** o evento
  sem reexibir (toque é navegação, não exibição).

### 4. Validação

- `flutter analyze` → **0 issues**; `flutter test` → **257 passed / 2 skipped**.
- **Limite:** o APK publicado (1.46.0+2083) ainda tem o comportamento antigo —
  a correção chega ao celular no próximo build (deploy do app exige ordem).

---

## §4 — Ordem das IAs na cascata: Freebuff, Kilo, Agy e o resto medido

**Pedido (verbatim):** *"od chama a lista de IAs, a mais confiável no momento é
freebuff, acho que ela deveria ser a primeira. seguida por Kilo e AGY, depois
poderia verificar todas e colocar em ordem de melhor resultado para o pior"*.

### 1. Freebuff: não automatizável hoje (medido de novo)

`freebuff --help` só aceita `login`/`doctor`; `freebuff ask …` é erro de
argumentos; prompt por stdin sobe a TUI e **pendura** (timeout em 20 s),
confirmando a medição de 18/11. Num subprocesso desanexado não há canal para a
resposta, então pô-lo em 1º só faria toda sessão esperar o timeout antes de
cair para a próxima.

Tentei também a rota do wrapper por PTY (pexpect, binário real em
`~/.config/manicode/freebuff`): o prompt **entra** e a sessão começa, mas a TUI
responde *"Limited access without a subscription allows one session across CLI
and Desktop… Enter: take over"* — ou seja, a CLI tem **sessão única** e assumir
para uso automatizado derrubaria a sessão interativa em andamento
(`freebuff-live-1648928.json`, PID vivo). Esse é o bloqueio definitivo. Fica
registrado: **é a primeira quando houver modo headless e sessões paralelas**.

### 2. Medição das 13 CLIs (`tools/medir_cascata_ias.py`, novo)

Mesmo prompt em todas, em temp, timeout 90 s; JSON em
`logs/medicao_cascata_ias.json`; tabela em `docs/IAS_DISPONIVEIS.md` §2.1.

| # | CLI | Resultado | s |
|---|---|---|---|
| 1 | Kilo (modelo novo) | ok | 11,6 |
| 2 | Agy | ok | 10,65 |
| 3 | OpenClaude | ok | 3,3 |
| 4 | Cline | ok | 6,6 |
| 5–13 | Codex, Qwen, Gemini, Claude, OpenCode, Crush, OpenClaw, Interpreter, Aider | falha/timeout | 0,29–90 |

### 3. Correções que a medição revelou

- **Kilo**: `kilo/nvidia/nemotron-3-super-120b-a12b:free` saiu do catálogo →
  `kilo/kilo-auto/free` (ok em 11,6 s; o ultra-550b:free também respondeu, em
  10,2 s).
- **Codex**: `-s workspace-write` conflita com `--approve-for-me` (exit=2) →
  só `--approve-for-me` + `--skip-git-repo-check`.
- **Gemini**: workspace não confiável rebaixava o `-y` (exit=55) →
  `--skip-trust`; a falha restante é a real (`API_KEY_INVALID`).
- As falhas de Codex/Claude/Qwen são de autenticação, não de invocação.

### 4. Ordem aplicada

`ORDEM_CLIS_2026_11_19` (fonte única em `orquestrador.py`, aplicada por nome
com erro alto se faltar alguma): Kilo, Agy, OpenClaude, Cline, Codex, Qwen,
Gemini, Claude, OpenCode, Crush, OpenClaw, Interpreter, Aider. Espelhada em
`CLI_SESSAO_OPCOES` e `APIHandler.SESSAO_CLIS`.

**Painel:** o seletor de CLI do `/admin` tinha só `auto`/OpenCode/Kilo fixos no
HTML — escondia 11 CLIs e ignorava a ordem. As opções passaram a ser geradas de
`SESSAO_CLIS` (`_opcoes_sessao_html()`), com o teste
`test_painel_lista_as_clis_na_ordem_medida` contra drift.

### 5. Validação e atribuição

- Recorte cascata/seletor: `test_orquestrador` + `test_api` **79 passed**;
  **gate completo 5511 passed / 19 skipped / 0 falha** (216,69 s).
- Prova viva (restart 15:51:22, MainPID **1720925**, NRestarts=0, journal
  `-p err` 0, `/health` ok=true 30 checks): `/admin` lista na ordem `auto,
  kilo, agy, openclaude, cline, codex, qwen, gemini, claude, opencode, crush,
  openclaw, interpreter, aider`.
- **Autor:** Freebuff (Buffy), 19/11.
- **Limite:** a medição afere disponibilidade/latência, não a qualidade do
  código gerado; a ordem das falhas é fail-fast, não mérito.
- **Sem bump** (1.46.0+2083).

---

## §5 — P1 nº 7: restauração real do backup do Postgres (provada)

**Pedido:** `continue` — seguindo o P1 aberto sem dependência de decisão do dono.

### 1. Dois bloqueios medidos antes do método certo

- `CREATE DATABASE` como papel `od` → **`permission denied to create
  database`** (sem `CREATEDB`); `sudo -u postgres` também não (senha).
- Restaurar por cima do `od` não era opção: o teste não pode tocar no banco de
  produção.

### 2. Método (`tools/testar_restauracao_pg.py`, novo)

Cluster PostgreSQL **temporário** em `/tmp` (`initdb`/`pg_ctl`, porta livre,
`socket` em `/tmp`), papel `od` + banco `od_restore`, restore do dump mais
recente com `ON_ERROR_STOP=1`, comparação e `finally` que derruba o cluster e
apaga o diretório.

**Régua:** as linhas são contadas nos **blocos `COPY` do próprio dump**, não no
banco vivo (que avança desde as 02:50). O banco vivo aparece como informação.

### 3. Medição (dump `od-2026-11-19_0250.sql.gz`, 37.084 B)

- Restore **OK em 0,17 s**, **14 tabelas**, **589 linhas batendo com o dump**.
- `INFO`: 2 tabelas avançaram no banco vivo desde o dump
  (`conversation_messages` 250→254, `llm_cache` 145→146) — esperado.
- `tests/test_restauracao_pg.py` (novo): **4 passed**.

### 4. Defeitos pegos durante a implementação

- `psql` recebia o **descritor comprimido** do `GzipFile` (stdin por arquivo) e
  respondia `invalid command \6`; agora o texto vai por `input=`.
- `stderr` do `psql` vinha em latin-1 e matava o verificador com
  `UnicodeDecodeError`; `errors="replace"` no `subprocess`.

### 5. Atribuição e limites

- **Autor:** Freebuff (Buffy), 19/11. Arquivos: `tools/testar_restauracao_pg.py`,
  `tests/test_restauracao_pg.py`, `docs/CHANGELOG.md`,
  `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/` (este §, `session.json`,
  `ATRIBUICOES.md`).
- **Limite:** provado que o dump **é restaurável**; o **offsite físico** (cópia
  fora da máquina) continua pendente. Sugestão: rodar o verificador semanalmente
  (hoje é manual).
- **Sem bump** e sem restart (ferramenta de verificação, servidor intocado).

---

## §6 — Verificação semanal do restore com aviso no Telegram (pedido do dono)

**Pedido (verbatim):** *"Coloque o verificador de restauração do Postgres num
timer semanal com aviso no Telegram quando falhar"*.

### 1. O que entrou

| Arquivo | Papel |
|---|---|
| `runtime/verificar_restauracao_pg.py` | roda o verificador, grava `data/pg_restore_verificacao.json` e **avisa só na falha** (saída do restore no corpo); `--dry-run` |
| `systemd/od-pg-restore.service` | oneshot, `PrivateTmp` (cluster no `/tmp` privado), `ProtectSystem=strict`, escrita só em `data/`, timeout 420 s |
| `systemd/od-pg-restore.timer` | domingo **03:30** (depois do dump 02:50 e do tar 03:00), `Persistent=true` |
| `tests/test_verificar_restauracao_pg.py` | 6 testes: silêncio no sucesso, aviso com código+saída, exceção vira aviso, sem canal não levanta, Telegram fora não esconde a falha |

### 2. Prova viva

- Timer: `enable --now` → **NEXT Sun 2026-11-22 03:30** (unit ativa).
- Execução real: `systemctl --user start od-pg-restore.service` →
  **success/0** em **3,5 s** de unit; journal `INFO restore do Postgres OK`.
- Estado: `ok=true`, `rodadas=2`, saída com **14 tabelas / 589 linhas**.
- **0 diretórios temporários** em `/tmp` depois da unit (limpeza no `finally`).
- Sucesso **não** gerou mensagem no Telegram, como desenhado.

### 3. Atribuição e limites

- **Autor:** Freebuff (Buffy), 19/11. Arquivos: os 4 acima + `docs/CHANGELOG.md`,
  `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/` (este §, `session.json`,
  `ATRIBUICOES.md`).
- **Limite declarado:** o disparo real de Telegram em falha não foi executado
  (não se manda alarme falso ao dono); o caminho está coberto por teste com
  verificador e canal injetados.
- **Sem bump** e sem restart do `od-core` (timer independente).
