# Conversa OmegaDrakon — 2026-11-13

## §1 — Relatórios do Vigia para fora de `analise/` (13/11 ~00:15, fechado 04:05)

**Pedido do dono:** por que `relatorio_chat_audit_*` e
`relatorio_vigia_mensagens_*` estão em `analise/` — a pasta é dele, para
ele depositar arquivos e pedir análise (regra 17); esses relatórios "não
estão sendo analisados".

### 1. Causa (lida no código, não suposta)

- Quem gera: timer diário **04:30** (`od-vigia-mensagens.timer`) roda
  `core/vigia_mensagens.py`, que chama o `core/chat_audit.py` — cada ciclo
  grava **2 JSONs** (`--horas 24`).
- Por que `analise/`: caminho hardcoded com o motivo registrado em
  `chat_audit.py` — *"relatório sai em `analise/` (gitignorado)"*. Escolha
  pela comodidade do `.gitignore` (linha 189 `/analise/`), feita em 22/10 e
  26/10, **depois** da regra 17 (12/10) — ninguém ligou para o significado
  da pasta.
- Efeito: 2 arquivos/dia acumulando desde 07/11 na caixa do dono.

### 2. Correção

Destino → **`data/relatorios/`** (`data/` já gitignorado inteiro, sem mexer
no `.gitignore`):

| Arquivo | Linhas mudadas |
|---|---|
| `core/chat_audit.py` | default de `--destino` (`raiz/"data"/"relatorios"`) + 2 docstrings |
| `core/vigia_mensagens.py` | `RAIZ / "data" / "relatorios"` (2 usos: relatório do vigia + relatório da auditoria) + 2 docstrings |
| `tests/test_chat_audit.py` | `test_salvar_relatorio_em_analise` → `test_salvar_relatorio_no_destino` (só o nome mentia; o corpo já usava `tmp_path`) |

Os **9 arquivos acumulados** (07/11→12/12) movidos para
`data/relatorios/`; `analise/` ficou só com `NV/` e `Projeti/`, do dono.

Referências que **não** mudaram (são input do dono, não saída do sistema):
`analise/AIML/...` como fonte de logs legados no `chat_audit`.

### 3. Verificação

- 104 passed nos dois suites afetados (`test_chat_audit` +
  `test_vigia_mensagens`).
- **Prova viva:** CLI do chat_audit **sem** `--destino` →
  `Relatório: .../data/relatorios/relatorio_chat_audit_20261113-035633.json`
  (arquivo de prova removido depois).
- Gate completo: **4539 passed / 17 skipped / 0 falha** (186,08 s).
- **Sem deploy:** o vigia é oneshot via timer — a próxima execução (04:30)
  já usa o caminho novo; nenhum serviço residente muda.

**Sem bump:** app segue **1.44.0/2080**.

## §2 — Análise das pastas que ficaram em `analise/`: NV e Projeti (13/11 ~04:30)

**Pedido do dono:** analisar as pastas que restaram em `analise/` — o que tem,
para que serve, se dá para usar no sistema, se já existe, o que melhorar;
pros e contras; incorporações/melhorias/referências viram checkbox no TODO.
E criar a regra se não existisse.

### 1. Regra nova (regra 22 em `iniciar/RULES.md`)

`analise/` é caixa de entrada: **tudo** que ele depositar passa por análise
completa antes de destino — (a) inventário medido, (b) serventia lida no
conteúdo, (c) uso/incorporação no sistema, (d) equivalente já existente
(medido), (e) pros/contras, (f) destino proposto. Incorporação/referência →
checkbox no TODO no mesmo passo; destino que altera o que é dele (apagar/
mover para fora) → só com aprovação (regra 7).

### 2. `analise/NV/` — 1,2 GB, 19.915 arquivos: Nicky Virthy Runtime

**O que é:** o projeto predecessor direto — 11 versões (v0.1.0 → v1.9.X),
cada uma com código, docs e alguns com `.git`/`.venv` próprios. O mapa do
Legado (§2) confirma: NV "gerou o esqueleto do sistema atual: tool runtime,
security layer, workflows".

**Duplicação medida vs. Legado:** `Legado/NV/docs/` (84 KB) tem os docs
**canônicos e mais novos** (SECURITY_LAYER v1.11.0-security-enforcement,
agosto/2026; HOMOLOGACAO_v1.11.0). O `analise/NV` traz os mesmos docs em
versões antigas (v1.7.0) — mas **o código das 11 versões só existe aqui**
(Legado tem só docs). Diffs: docs idênticos em conteúdo só nos casos
comuns; CHANGELOG/FOUNDATION/MILESTONE/PROMPT diferem (camadas geológicas —
não merge, não apagar, conforme o próprio mapa do Legado).

**Composição do tamanho:** ~501 MB de `.venv` (4 venvs: 108+108+136+149 MB),
69 MB de `.git` (4 repositórios), ~61 MB de tars, o resto código/docs.

**O que já existe no OD (herdado do NV):** `core/security/` (1.742 linhas —
SecurityManager/Policy/Permission/Scope/Approval/Audit, o fluxo do
SECURITY_LAYER_DOC), `core/workflows.py` (WorkflowEngine sequencial, com
crédito no docstring: "NV Runtime core/workflows/"). Não duplicar.

**O que é único e pode servir:** o `nested-workflows.tar.gz` (v1.9.2) tem
`dag_engine.py` (347 linhas, grafo com paralelismo) + `scheduler_engine.py`
(413 linhas, cron/interval com persistência) + 8 testes — **o OD não tem
isso** (só workflow sequencial). vira checkbox "referência para
Semanas 9-10/R1".

**Pros:** último exemplar do código-fonte das versões; referência de
arquitetura (DAG/scheduler) para quando o OD precisar; docs da security
layer como intenção revisável.
**Contras:** 1,2 GB na caixa de entrada do dono; ~570 MB é venv+git (lixo
estrutural); duplica docs com o Legado (risco de confusão sobre qual é
canônico); nada roda aqui (é projeto de outra era, Python de outra venv).

**Destino proposto (aguarda aprovação):** zipar para `backups/` (ou mover
para `Legado/NV-codigo/`) e tirar de `analise/`; extrair os `.venv`
primeiro (501 MB de lixo). **Não apagar sem ordem** (regra 9).

### 3. `analise/Projeti/` — 235 MB, 953 arquivos: trabalho PM + ferramentas

**O que é:** (1) notebooks `pyautogui` de RPA do site Orion (mapa de força
da 42.BPM/I — 124 chamadas no `mapa.ipynb`, 76 no `inserirmapa.ipynb`);
(2) dados de escala de 2024 (`Mapa.csv`, `MapaForcaTudo.txt` — **com nomes,
matrículas e viaturas de policiais**); (3) `google-services.json` +
`app.txt` (export do Firebase `nicky-e4f99`); (4) `OmegaDrakon.apk` 51 MB;
(5) ferramentas Windows: FileZillaPortable (82 MB), PuTTYPortable,
MQTT-Explorer (74 MB), tailscale-setup 1.92.5.

**Duplicação medida:**
- `google-services.json` **é byte a byte o mesmo** do
  `app/android/app/google-services.json` (sha256 `5e64634c…` nos dois) —
  redundante.
- `OmegaDrakon.apk` **não bate com nenhum backup** (`b845c044…` vs todos os
  `backups/apk-*`): build antigo, mais velho que v1.39.3-2075 (17/10); o
  atual é 1.44.0+2080. Não extraí a versão (Manifesto compactado).
- Tailscale do desktop: instalador é 1.92.5; o **servidor** está em
  **1.104.6** — o instalador é velho (medido agora).

**Pros:** os notebooks são um RPA funcional e completo (referência de
padrão para automação — e candidatos a virar action/workflow no OD, que já
tem action engine + CoderEngine sandbox); dados do Orion podem virar action
de leitura ("qual o turno de amanhã"); FileZilla/PuTTY/MQTT-Explorer úteis
para o desktop Windows dele (que está na tailnet ativo).
**Contras:** dados pessoais de policiais expostos na pasta (não podem ir
para git/site em hipótese nenhuma — regra 16); APK órfão sem versão;
Google-services duplicado; tailscale instalador velho vs. real; pyautogui é
frágil (tabulação cega — se um dia automatizar de verdade, é API/scraping
autorizado).

**Destinos propostos (aguardam aprovação):** instalar as ferramentas no
desktop Windows (copiar `.exe`); APK e google-services → lixo (ou me diga a
origem do APK que eu arquivo); dados do Orion ficam como referência de
parsing mas **fora de qualquer publicação**.

### 4. O que foi para o TODO

6 checkboxes em `docs/ANALISE_SISTEMA_TODO.md` §4 (seção "Análise de
`analise/` — NV e Projeti"): referência DAG/scheduler do NV; destino dos
1,2 GB do NV; SECURITY_LAYER como referência; automatizar mapa de força
(referência RPA); instalar ferramentas no desktop; google-services/APK como
lixo candidato; dados do Orion como referência de leitura.

**Sem bump:** app segue **1.44.0/2080**.
