# Transcrição — 2026-10-23

Sessão iniciada pelo checkpoint (`iniciar/session.json`). Continuação do
arquivo-irmão `2026-10-22_conversa_omegadrakon.md` (§§1–6 do dia 22 já
estão lá: reverificação do círculo ↑/Vigia, o bloco do dono de 4 frentes,
o auditor de conversas com Groq, a pré-história AIML no site, a
blindagem de senhas e a senha vinda do cofre).


## §1 — "leia iniciar" (23/10, ~08:44): o resíduo da frente A (TV) que
       ficou no disco sem commit

**Contexto da retomada.** A sessão de ontem terminou por volta das 22:06
com a fila do dono assim: B (cofre) fechada e publicada (`1665ef9`), A
(TV no HA) **em curso**, C (papel FAMÍLIA) na fila. A reverificação de
rotina de hoje achou a frente A **meio caminho no disco** — o mesmo
padrão da sessão interrompida de ontem à tarde: `core/intents.py` e
`tools/actions/actions.py` alterados às **22:06:51**, ou seja DEPOIS do
boot do od-core (21:56:55) — o serviço estava rodando o código antigo —
e `tests/test_resposta_transparente.py` com **erro de sintaxe**.

**Achado 1 — o rascunho não rodava.** A docstring de
`test_tv_inexistente_resposta_honesta_sem_llm` abria com `''` (duas
aspas) em vez de `"""` → `SyntaxError` na coleta do pytest: o arquivo
inteiro de testes falhava antes de rodar qualquer coisa. Conserto: aspas
corrigidas.

**Achado 2 — o teste novo vazava estado e derrubava teste ANTIGO.** Com
a sintaxe consertada, 3 testes falharam. Causa raiz (código, não
opinião): `_LIGHT_CONFIRMATIONS` é um **global de módulo** em
`tools/actions/actions.py` (o mesmo dict que guarda a confirmação de 2
passos das luzes em produção) e a classe nova `TestControleTV` não o
limpava — a pendência de `'alex'` de um teste vazava para o próximo. O
sintoma era bizaro e valioso: no teste de TV o 1º passo "executava
direto" (pendência velha casava), e nos 2 testes antigos de luzes o
`'sim'` caía na mensagem de **TV inexistente** (a action resolvia a
entidade de TV que não existia no servidor falso daquele teste).
Conserto no padrão da casa: **fixture autouse** na `TestControleTV` que
faz `clear()` no dict antes e depois de cada teste (produção intocada).
Teste do teste: 3 falhas antes → 118/118 depois.


## §2 — Frente A fechada: "desligue a tv" acha a TV Sala no HA

**O que mudou (o caso real da auditoria §5 de ontem: 3× a frase caía no
LLM, que respondia como se fosse um COMPROMISSO):**
- `core/intents.py`: comando de **aparelho do lar** (`tv`, `televisão`,
  `ventilador`, `ar-condicionado`, `cafeteira`, `micro-ondas`,
  `geladeira`, `caixa de som`…) entra na mesma rota de luz/tomada;
  `resolve_light_target` passa a aceitar os domínios **`remote.`** e
  **`media_player.`** (a TV do dono aparece nos dois, com o mesmo
  `friendly_name` "TV Sala") e aceita o alvo curto **`tv`** — antes o
  piso de 3 letras o descartava.
- `tools/actions/actions.py`: `ha_device_control` aceita os **4 domínios
  atuadores** (`switch`, `light`, `remote`, `media_player`).
- **Intocado de propósito:** o gate de papel (usuário comum não desliga),
  a confirmação de 2 passos com TTL de 2 min e a resposta honesta
  ("não existe no Home Assistant") quando a TV não está no HA — tudo sem
  tocar no LLM.

**Guardas:** `tests/test_resposta_transparente.py` **+8**
(`TestControleTV`): pedido pede confirmação com `TV Sala` sem executar;
`'sim'` executa `turn_off` no domínio `remote` (empate determinístico
contra `media_player`, que tem o mesmo nome); "tv da sala" também casa;
usuário comum negado; TV inexistente vira resposta honesta **sem LLM**;
frase sem verbo de comando não sequestra a TV; unidade do resolvedor e
da action aceitando os domínios novos. Mais a fixture autouse acima.

**Validação:** gate oficial **3732 passed / 16 skipped / 0 falha ·
90,81%** (baseline 3724/16 a 90,80%; reexecutado DEPOIS da edição do
CHANGELOG, que alimenta o corpus do RAG). pyflakes sem aviso novo (os
avisos dos arquivos tocados são pré-existentes, conferidos contra o HEAD
com `git stash`).

**Deploy:** commit **`78087ea`** pushado (`HEAD == origin/master`,
árvore limpa, regra 7.1). **Restart verde 08:53:48** (regra 7.3, gate
verde antes): `MainPID 138285`, `NRestarts=0`, journal **0 `[ERROR]`**,
`/health` **ok=True, 25 checks nenhum fora**, `/app/version`
**1.44.0/2080** intacta.

**Prova viva (chat real `POST /message` com a chave do dono = papel
admin, 2 sessões independentes):**
- `"desligue a tv"` → `route=action_intent` · *"💡 Confirmar: desligar
  'TV Sala' (agora: off)? Responda **sim**…"* — 0 LLM.
- `"sim"` → *"✅ TV Sala: desligar executado (⚪ estado agora: off)."*
- **Banco vivo (PostgreSQL):** as 4 linhas da troca (`id` 895–898) com
  `llm_used = fastpath:ha_device_control` — o turno que ANTES vazava no
  LLM e alucinava compromisso agora resolve no fastpath. Journal 0
  `[ERROR]`.


## §3 — Estado e pauta

**Sistema no ar e verde:** v1.44.0/2080, commit `78087ea` publicado,
od-core desde 08:53:48 sem reinício, `/health` 25/25.

**Fila do dono (uma por vez, ordem dele):**
- ~~B — senha vem do cofre~~ **FECHADA** (`1665ef9`, ontem).
- ~~A — TV no HA~~ **FECHADA** (`78087ea`, hoje, §2).
- **C — papel FAMÍLIA** (terceiro papel: pode ligar/desligar aparelhos e
  luzes; o comum continua sem poder) — **próxima frente**.
- Registro final (CHANGELOG/txt/Telegram) ao fechar C.

**Pauta de conteúdo pendente de decisão dele:** as **134 respostas
pt-BR** do `OK/` do AIML (viram RAG ou ficam paradas) e o **exemplo
exato** da falha residual do tema (TODO §3.8).
