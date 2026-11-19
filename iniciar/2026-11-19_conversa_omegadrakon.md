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
