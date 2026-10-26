# Transcrição da sessão — 2026-10-26

> Registro conforme regra 4 do `iniciar/RULES.md`. Contexto em
> `iniciar/session.json` (chave `network_hosts_vigia_fechado_2026_10_26`).

## §1 — Retomada de rotina ("leia iniciar", 26/10 ~09:55): resíduo de
       sessão morta achado e FECHADO — `network_hosts` com o nome do Vigia
       (parking lot §5)

**Pedido:** usuário: "leia iniciar" — reverificação de rotina (regra 3).
Checkpoint lido: `session.json` (chave `reverificacao_rotina_2026_10_24_1048`,
§4 = verde total, sem resíduo) + transcrição `2026-10-24` (§1–§4) +
`RULES.md`.

**Achado principal — RESÍDUO NO DISCO (sessão morta de 24/10):** a árvore
estava **suja com 3 arquivos modificados** (`core/intents.py`,
`tools/actions/actions.py`, `tests/test_intents.py`), última edição
**24/10 10:55–10:59** — 2 dias parados, depois do último commit de
registro (`b656158`, 24/10 10:52). Era o **parking lot §5 na metade**:
a frente "network_hosts + Vigia" estava escrita mas **nunca passou pelo
gate nem pelo commit** — mesmo padrão das interrupções de 21–23/10.

**O que o rascunho fazia (auditado antes de decidir, regra 5):**

1. `tools/actions/actions.py` — `_inventario_vigia()`: lê
   `logs/network_watchdog_estado.json` (**fonte única** do Vigia, o
   arquivo que ele grava a cada ciclo), MAC normalizado nos dois lados
   (ARP do kernel em minúsculo × chave canônica maiúscula do Vigia),
   tolerante a arquivo ausente/ilegível/corrompido (= dicionário vazio),
   `fabricante` só entra se não for o placeholder `desconhecido`.
2. `core/intents.py` — `format_intent_result("network_hosts")`: com
   nome a linha vira `nome · ip`; sem nome o `fabricante` preenche o fim
   do parêntese; sem nenhum dos dois a linha fica **idêntica à
   original**.
3. `tests/test_intents.py` — +7 guards (formato ×2, inventário ×4,
   ponta a ponta no orquestrador com `0` idas ao LLM).

**Verificação antes de mexer:** `tests/test_intents.py` **94/94** já
passava com o rascunho; pyflakes **0 aviso novo** (os 2 de `actions.py`
são pré-existentes — conferidos contra o HEAD com `git show` + pyflakes);
`logs/network_watchdog_estado.json` **vivo com 23 dispositivos** (todos
com nome/fabricante) — a base de dados da entrega existe de verdade.

**Fechamento (regras 4/7.1/13):**

- CHANGELOG 1.44.0 ganhou a subseção **"'Quem está na rede?' responde com
  o NOME de cada aparelho"** (**sem bump** — backend), com a nota
  honesta da origem (sessão de 24/10 interrompida no meio).
- **Gate oficial executado DUAS vezes:** `3790 passed / 16 skipped /
  0 falha · 90,81%` antes do CHANGELOG e **`3790 passed / 16 skipped /
  0 falha · 90,82%` DEPOIS** (a edição alimenta o corpus do RAG). Eram
  3783 na última sessão — os **+7** são exatamente as guards novas.
- Commit **`4135c0e`** pushado (4 arquivos, +247/−5), HEAD ==
  `origin/master` (`ls-remote` confirmou), **árvore limpa**.
- **Restart verde (regra 7.3):** 26/10 **10:09:26**, MainPID **44070**,
  **NRestarts=0**, journal desde o restart **0 `[ERROR]`**, `/health`
  `ok=True` **25 checks nenhum fora**, `/app/version` **1.44.0/2080**
  intacta (sha `aeb8566b…`).

**Prova viva:**

- **REST /message real** (papel admin, `OD_API_KEY`): *"quantas pessoas
  estão conectadas na rede?"* → `route=action_intent`,
  `llm_used=fastpath:network_hosts`, **0 LLM**.
- **Ação direta:** 18 vizinhos, **9 com nome ou fabricante** —
  `Redmi-Note-14 · 192.168.0.108`, `Amazon-Show · 192.168.0.136`,
  `TV Samsung · 192.168.0.192`, e o roteador `192.168.0.1` ganhando
  `TP-Link Systems Inc` no parêntese (sem nome, fabricante preenche).

**Nota honesta (não é desta entrega):** a pergunta *"quem está na
rede?"* **não** dispara o fastpath — o gatilho de `_detect_network`
exige um sujeito da lista (pessoas/dispositivos/aparelhos…), "quem" não
está nela e a frase cai no LLM (pré-existente, intocado). E, no
formato, os **10 primeiros** da listagem são as bridges do Docker
(172.19.x) porque a ordenação é por IP string e o corte é em 10 —
pré-existente também; os dispositivos nomeados aparecem na faixa
`192.168.0.x` (prova acima mostra o payload completo). **Nada disso foi
alterado** — fora do escopo da frente, aguardando ordem.

**Canais do dono:** `txt.txt` = só a entrega do Kiwix de 24/10 05:17,
**nenhuma mensagem nova dele**. `analise/` = apenas `Nicky Locutor/`
(**pendente, aguardando ordem** — regra 17).

**Estado:** SISTEMA VERDE E NO AR — v1.44.0/2080, HEAD `4135c0e`,
árvore limpa. Parking lot §5: **+1 fechado** (network_hosts + Vigia);
restam aguardando ordem: rota WiFi, auditoria de uso de ferramentas, MCP.


## §2 — "O Vigia está vigiando o que exatamente?" (26/10 ~10:25)

**Pedido:** dono: *"continue. o vigia esta vigiando o que exatamente?"* —
resposta apoiada em código + logs lidos antes de afirmar (regra 5).

**O que é (duas camadas, `tools/monitor/network_watchdog.py`, timer
`network-watchdog.timer` de 5 min, ativo desde 21/10 18:57):**

| Camada | Quando | O que faz |
|---|---|---|
| **Rápida** | todo ciclo (~8 s) | Varredura ARP da LAN `192.168.0.2..254` (ping + `ip neigh`) → **diff contra o inventário** (`logs/network_watchdog_estado.json`). MAC desconhecido = evento `dispositivo_novo`, fica **pendente** até `--conhecer`, com lembrete no Telegram a cada cooldown. |
| **Rica** | a cada 3º ciclo (~15 min) | `vigia_rich.py` (playwright/chromium, venv durável) lê a **UI real do Archer C6**: lista de clientes (nome + sinal enriquecem o inventário) e o **Registo de Eventos** do roteador; o **journal do sshd** do servidor (`Failed password` / `Invalid user` / `Authentication failure`) entra na mesma classe de evento. |

**Ponte de alerta:** a sonda `_check_network` do `integrations/notifier.py`
— traduz as pendências em `net:dispositivo-novo` / `net:seguranca`
(cooldown de 1 h). O monitor **não** manda mensagem sozinho. **Não
bloqueia**: `--bloquear` é operador, só sob ordem. O
`router-monitor.timer` (1 min, `router_monitor.sh`) é **outro** monitor —
disponibilidade do gateway, não o Vigia.

**Estado vivo medido agora:** inventário **23** dispositivos · **1335
ciclos** · última camada rica **26/10 10:13** · 11 ativos no tick das
10:23 · log com 2710 linhas = 1335 varredura + 1335 estado + **23
`dispositivo_novo`** (1 por aparelho, na primeira vista) + 17
`rich_erro` + **0 eventos `seguranca` em todo o histórico**.

**Camada sshd (honestidade):** 0 `failed password`/`invalid user` em 7
 dias — ela está **ociosa porque não há ataque**, não porque esteja muda:
 o defeito do `.splitlines()` (o stdout do `journalctl` inteiro era
 iterado como caracteres, e nenhum alarme jamais casaria) foi corrigido
 em 22/10 e tem teste cobrindo.

**Achado com ação pendente — 2 aparelhos desconhecidos há dias:**

| MAC | Nome (UI do roteador) | IP | Desde |
|---|---|---|---|
| `7A:A7:13:05:6D:3A` | iPhone | 192.168.0.232 | 23/10 18:13 |
| `16:05:EA:56:FB:9E` | iPad | 192.168.0.210 | 25/10 20:46 |

Os dois MACs são **localmente administrados** (endereço WiFi privado do
Apple, aleatorizado) — provavelmente aparelhos da casa, **não intruso**;
mas estão disparando o alerta `net:dispositivo-novo` **a cada cooldown**
(último no journal: 26/10 10:24:32). **Sem ação nesta troca** —
`--conhecer`/`--bloquear` é estado externo e depende da ordem dele.

**Menor:** 17 `rich_erro` (todos `Page.goto Timeout 20000ms` na UI do
roteador, espalhados 22/10–25/10) — a camada rica voltou sozinha hoje
(10:13); transitório de rede, sem ação.

**Estado:** verde (v1.44.0/2080, HEAD `3f6002f`, árvore limpa, health
25/25). Pendência única aberta: os 2 aparelhos aguardando ordem.


## §3 — Dono reconhece os 2 aparelhos: Vigia sem pendências (26/10 ~10:32)

**Pedido:** dono, via pergunta objetiva: *"São meus — reconhecer os
dois"* (os pendentes achados no §2).

**Executado:** `--conhecer 7A:A7:13:05:6D:3A` e `--conhecer
16:05:EA:56:FB:9E` (só inventário local — **nenhuma mutação no
roteador**) e, em seguida, `--once` para **reescrever a linha de estado
do log**: a sonda `_check_network` lê a *última* linha, então sem o
ciclo novo o alerta horário continuaria até o próximo tick.

**Prova:**

- `--report`: **`Pendências: 0 dispositivo(s) novo(s), 0 evento(s) de
  segurança`** — os 2 MACs saíram de `[DESCONHECIDO]` para
  `[conhecido]`.
- Última linha do log (26/10 **10:28:07**): `pendentes_novos: []`.
- Chat real: `network_hosts` formatado devolve **`iPad ·
  192.168.0.210`**.
- Alerta `net:dispositivo-novo` (que saía a cada cooldown desde 23/10)
  para de ser emitido a partir do próximo tick.

**Decisão de nome (honestidade):** mantive **`iPhone`** e **`iPad`** —
os nomes da UI do Archer. **Não** apliquei os rótulos
"iPhone-Nicoly/iPad-Nicoly" que eu sugeri na pergunta: atribuir o
aparelho a uma pessoa seria inventar. Renomear quando quiser:
`--conhecer MAC NOME`.

**Estado:** Vigia **sem pendências** (23 inventariados, 23
conhecidos); sistema verde 1.44.0/2080, HEAD `7f8de9c`, árvore limpa.
