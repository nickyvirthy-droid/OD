# Conversa 2026-10-21 — OmegaDrakon

## §1 — Retomada de rotina ("leia iniciar", 21/10 ~14:20): sistema verde em v1.44.0+2080

Retomada pela regra 3 — li `iniciar/session.json`, `iniciar/RULES.md` e o
fim da transcrição anterior (`2026-10-20_conversa_omegadrakon.md` §18–§21).
Último ponto registrado: **20/10 ~21:40**, fecho da **v1.44.0+2080 —
Câmera QR no app** (commit `9322352`, v2 da Etapa 4 do Registro Mestre,
fila do TODO zerada).

Verificação feita com a fonte viva (não com o registro):

| Frente | Medição |
|---|---|
| Serviço | `od-core` active desde **20/10 20:39:29** (17h40), MainPID 968535, **NRestarts=0**, journal **2 `[ERROR]`** desde o boot (ambos 21/10 03:01/03:02 — DNS do Telegram durante blip de rede, ver abaixo) |
| Saúde | `/health` (com `X-API-Key`) **ok=true, 25 checks, nenhum fora** |
| Versão | `/app/version` **1.44.0 / 2080**, sha256 `aeb8566b…`, APK publicado 72.028.650 B (subiu de 55 MB — dependência da câmera) |
| Git | árvore **limpa**, HEAD `9322352` == `origin/master` (0 à frente / 0 atrás) |
| Backups | diário `od-2026-10-21_0310.tar.gz` (03:10) · **off-site do diário enviado 03:40** (1 parte, sha `a5c52232…`) · capturas semanal segue `16_1434` (próximo snapshot domingo 04:00) · disco **66%** (76G livres) |
| Canais do dono | `txt.txt` **sem mensagem nova** (nossa entrega da câmera QR, 20/10 ~21:40) · `analise/` **inalterado** (2 capturas do Sistema Órion de 16/10 sem instrução + `fotos-adicionais/` com as 4) |
| Ferramentas | `nomad_tools` **9/9, nenhuma fora** · notifier `ticks=1064, errors=2, problems=24, alerts_emitted=6, alerts_blocked=13` |

Fatos novos transitórios (todos dentro do esperado, sem ação):

- **Blip de rede na madrugada (03:01–03:02):** os 2 `[ERROR]` do boot são
  `Sink falhou | Telegram API indisponível: Temporary failure in name
  resolution` — o mesmo blip de DNS registrado nos boots anteriores.
  Na mesma janela: 1 alerta `router:down` (ping ao 192.168.0.1 falhou),
  1 `health:degraded` (1 check fora = backup, durante o próprio blip) e
  **100 dos WARNs "Transporte indisponível"** do polling do bot de chat
  (bot.py:500 — `TransportError` transitório). Tudo se recuperou sozinho.
- `router:down` adicional em 20/10 21:46, 05:26 e 06:37 — mesmo blip
  intermitente do gateway registrado desde 15/10; o roteador responde
  agora.
- WARNs "Transporte indisponível" fora do pico: ~1/hora entre 10h e 14h
  (mesma ordem de grandeza dos 18 das 20h39→meia-noite de ontem; são
  1.142 em setembro — intermitência antiga de rede/long-polling, não
  regressão). `getMe` dos 3 bots **vivos agora** (@Nicky_Virthy_bot OK).

Estado: **SISTEMA ESTÁVEL E NO AR — v1.44.0+2080**, fila do TODO zerada,
nada em andamento; aguardando ordem do dono (próximas registradas:
exemplo exato do tema §3.8, off-site de capturas segue o ciclo semanal).

## §2 — Reboot do roteador tirado da janela dos backups (21/10 ~14:30–15:50)

**Pedido do dono:** *"o problema do roteador vamos resolver agora. ele está
configurado para reiniciar às 3:00, justamente no horário dos backups. o
sistema pode pegar o controle dele, te passo a senha pelo txt. existe um
aplicativo que faz isso, tether, mas não sei você consegue clonar ou
controlar ele"* — e, quando apontei que o `txt.txt` não tinha linha nova
dele, ele corrigiu: *"a senha já está lá, deveria ter lido de primeira"*
razão: li o arquivo na reverificação e tratei só a nossa entrega como
conteúdo.

**Apuração (antes de tocar no roteador):**

- **Fingerprint:** 192.168.0.1 responde interface **TP-Link** (UI `tpos`,
  firmware `c80_1.14.0`, `/cgi-bin/luci` = 403 — não é OpenWrt); o dono
  informou **Archer C6** (bate com a tela após login).
- **A hipótese dele, provada por um sinal:** no histórico do
  `router_monitor` (751 downs no log + rotação), o down de **21/10 03:00:20
  teve `latency_ms=5`** — falha **instantânea** (host unreachable), a
  **única** de todo o histórico; todos os outros são **timeout de 2009–2012
  ms** (ping perdido). Reboot derruba o gateway na hora; perda de pacote
  espera o timeout. Exatamente o que ele descreveu.
- **Honestidade registrada:** os outros ~10–20 min/dia de "down" espalhados
  (05:25, 05:50, 06:00… o dia inteiro, pico 09h–12h) **não são** o roteador
  caindo — são 1 ping perdido isolado, causa provável o **adaptador WiFi
  USB do servidor** (`wlx000f0037acf0`). Trocar o agendamento elimina o
  incidente das 3:00 (DNS + backup + off-site na mesma janela), **não** esses
  espalhados — diagnóstico separado se ele quiser (cabo resolve).
- **Tether:** não dá pra clonar o app (conta TP-Link do celular dele) e
  **não precisa** — a interface local expõe o mesmo "Reboot Schedule", e é
  por lá que o controle foi feito.

**Leitura do estado atual (SÓ LEITURA, via chromium headless em
`/tmp/opencode/pwvenv` — ferramenta da casa, fora do repo):** login real na
UI (`#reboot` → "Programação de Reinicialização") = **ATIVADA · 03:00 ·
Todos os dias**; Hora Atual do roteador 15:35 = fuso -03 correto (a UI
avisa para conferir o fuso antes de usar a função). Teste do combo "Repetir"
(Todas as semanas → aparece campo de dia) feito **sem salvar** (recarreguei;
o botão GRAVAR é o único que grava).

**Escolha do dono (pergunta objetiva):** **semanal, domingo 05:00**
(recomendado) — frente ao diário 05:00 e ao desligamento total.

**Aplicação (2 tentativas que NÃO gravaram nada + a certa):**

1. `fill()` direto no campo de hora **falhou por construção**: os campos da
   UI são `combobox-text` **readOnly** (spinner); o locator em campo
   readonly travou 20 s e o script foi derrubado por timeout de shell
   (EPIPE no driver) — **estado conferido logo depois: 03:00/diário
   intacto, nada gravado**.
2. JS puro setando `value` não era o caminho (não dispara o widget) e o
   filtro não achou os campos — falhou **antes** do GRAVAR.
3. **Caminho certo = os combos reais:** abrir o combo pelo wrapper do campo
   readonly e clicar na **opção visível** (o mesmo mecanismo que os testes
   de leitura já mostravam): hora `03→05` · Repetir `Todos os dias→Todas
   as semanas` · dia `Segunda-feira→Domingo` · **GRAVAR**.

**PROVA (reabrir do zero e reler):** `{"texts": ["05", "00", "Todas as
semanas", "Domingo"], "ativo": true}` — **PASSOU**, screenshot em
`/tmp/opencode/reboot_prova.png`. Próximo reboot: **domingo 25/10 05:00** —
longe do backup diário (03:00), do off-site (03:40) e das capturas
(domingo 04:00).

**Senha:** consumida do `txt.txt` e **apagada do arquivo na hora**
(protocolo dos tokens); gravada como `ROUTER_ADMIN_PASSWORD` no `.env`
(gitignorado, `check-ignore` confirmado) + **allowlist +1** em
`vault_env_mirror.py` com a nota da pauta. **Espelho do cofre: 19/19
gravado+conferiu** (cofre agora com 19 itens). Nenhum valor impresso no
chat nem nos logs (scripts leem por env).

**Validação:** gate oficial **3546 passed / 16 skipped / 0 falha · 90,69%**
(mudança só na allowlist de um script operacional; `test_vault` 33/33) —
**sem restart** (nenhuma peça em runtime lê a chave nova).

**Estado:** **APLICADO E PROVADO.** Canais: CHANGELOG §1.44.0 (subseção
"sem bump") · `session.json` · `txt.txt` · Telegram. Scripts de
reconhecimento/leitura/aplicação em `/tmp/opencode/` (fora do repo — a
ferramenta registrada de manipulação da UI do roteador).

## §3 — Revisão de falhas e portas do roteador (21/10 ~16:00–17:00)

**Pedido do dono:** *"ok, ja que controla o roteador, verifique possives
falhas e revise todas as portas para o sistema funcionar"* — revisão
completa **só leitura** da UI real (chromium headless, senha via env,
nada impresso), cruzada com o lado do servidor (`ip addr`, `ss -tlnp`,
tailscale).

**O que a revisão mostrou (estado medido, não suposto):**

- **WAN = CGNAT** (100.64.175.223, faixa RFC 6598 da operadora): **sem IP
  público**. Consequência direta: **nenhuma regra de port forward alcança
  a internet hoje**. O acesso externo de tudo é o **Tailscale** (funnel
  `/` → 8000, `/ws` → 8001, Vaultwarden 8443 tailnet-only — confirmado no
  `tailscale status`). DDNS TP-Link não configurado (e seria inútil sob
  CGNAT).
- **5 regras de Port Forwarding**, todas para **192.168.0.250 = este
  servidor** (confirmado por `ip addr` + reserva DHCP): SSH 22→22 · HTTP
  80→8000 (API) · HTTPS 443→443 (**órfã**: nada escuta 443 local — o 443
  é do Tailscale) · Controle 8001→8001 (WebSocket) · **Teste 82→443
  (lixo esquecido, nada escuta em 82)**.
- **Achado crítico: Atualização Automática de firmware LIGADA, janela
  03:00–05:00** — a mesma janela do backup diário. O log do roteador
  mostra 3 downloads de firmware (18/08): qualquer noite com update
  novo, o Archer se reinicia sozinho **no meio do backup de novo**. A
  troca do reboot agendado (§2) sozinha não bastava.
- **Verde confirmado com estado:** SPI Firewall ligado · ping WAN
  desligado (não responde externo) · ping LAN ligado (monitor depende) ·
  DMZ desligado · QoS desligado · Controlo Parental desligado ·
  telemetria TP-Link desligada · WPS desligado · rede de convidados
  desligada · rede IoT própria **com isolamento ligado** · DHCP com
  reserva fixa do servidor (.250) · hora/fuso corretos · log só com
  ruído DHCPv6 do provedor.
- **Lado servidor:** só SSH (22), API (8000/8001) e Home Assistant
  (8123) escutam em todas as interfaces; Postgres/MQTT/Calibre/banco em
  localhost (esperado e bom). Sinal do WiFi do servidor: **-51 dBm
  (forte)** — os pings perdidos espalhados não são distância; diagnóstico
  separado segue de pé (energia do adaptador USB/cabo).
- **Limites honestos:** escanear de fora é impossível sob CGNAT (sem
  caminho por definição — a resposta "mortas" é conclusiva); ALG e
  passthroughs todos ligados (default de fábrica, inócuos aqui); EasyMesh
  ligado sem meshes (inócuo); UPnP ligado com 4 entradas do Tailscale
  (portmap — NAT traversal, mantido de propósito).

**Decisão do dono (pergunta objetiva):** opção recomendada — **"Mover
janela + limpar regras mortas"**.

**Aplicado (mutação autorizada, tudo com prova por reabertura):**

1. **Auto-update: 03:00–05:00 → 06:00–08:00** (combo real da tela
   firmware + GRAVAR; o switch de auto-update **continua ligado** —
   updates automáticos preservados, janela agora longe de backup 03:00,
   off-site 03:40, capturas dom 04:00 e reboot dom 05:00).
2. **Regras "Teste" (82→443) e "HTTPS" (443→443) apagadas** pelo botão
   "Apagar" da própria linha (nesta UI a exclusão é direta, sem modal de
   confirmação — verificado com clique seco antes, sem alterar nada).

**Prova final (leitura do zero, três telas):** reboot
`05:00/Todas as semanas/Domingo` ativo · port forward = **exatamente 3
regras** `[SSH 22→22, HTTP 80→8000, Controle 8001→8001]`, todas →
192.168.0.250 · firmware `janela 06:00–08:00, auto-update ligado`.
Screenshots em `/tmp/opencode/` (`verificacao_final.png`,
`pf_final.png`, `fw_prova.png`).

**Registrado:** `session.json` (chave `roteador_revisao_portas_2026_10_21`)
· CHANGELOG §1.44.0 (mesma subseção "sem bump", estendida) · `txt.txt` ·
Telegram. **Gate não refeito** (nenhum arquivo do sistema em runtime
mudou — só registros; a última rodada verde do dia: 3546/0 · 90,69%).

---

## §4 — VIGIA DA REDE: INVENTÁRIO DA LAN + ALARME DE INTRUSÃO (tarde, ordem do dono)

**Pedido:** *"agora que consegue ver o roteador, o sistema consegue saber
todos os dispositivos da rede e tambem avisar se alguem tentou invadir e
me proteger?"*

**Apuração (só leitura):** o Mapa de Rede do Archer expõe por cliente
nome/MAC/IP/sinal/tráfego/tempo — **e já mostrava 2 "Desconhecido"**:
`AC:A7:04:F0:8F:88` (OUI **Espressif** — chip ESP; provavelmente um IoT
do dono não nomeado) e `0A:31:09:50:C4:5A` (MAC aleatorizado de celular,
linha sem tráfego). A lista de negados do roteador tem **1 Tuya Smart
bloqueado** (`C4:82:E1`) — evidência de que a Controlo de Acesso já foi
usada. Resposta honesta ao dono: de fora **não há o que invadir**
(CGNAT + zero portas abertas; acesso remoto = Tailscale); o vetor real é
quem entra pela WiFi — e o elo mais fraco restante é a **senha "omegadrakon"**
(palavra de dicionário; rotação = operação à parte com custo em todos os
aparelhos, incl. re-pareamento dos ESPs).

**Escolha do dono:** *"Sim, alerta primeiro"* — inventário + alerta
imediato de dispositivo novo + vigia de logs, **bloqueio só sob ordem**
(sem bloqueio automático: poderia trancar ele mesmo fora com aparelho novo
ou visitante).

**Entrega (padrão da casa: monitor registra, notifier alerta):**

- `tools/monitor/network_watchdog.py` — duas camadas: **rápida** (varredura
  ARP a cada 5 min via `network-watchdog.timer` novo; diff contra
  inventário; MAC novo = evento `dispositivo_novo` PENDENTE até
  `--conhecer`, lembrete por cooldown) e **rica** (a cada 3º ciclo ≈15 min,
  `vigia_rich.py` no venv durável `/home/alex/od-vigia-venv` — chromium
  headless **fora do `/tmp`**, que morre no reboot — lê a UI real: nomes/
  sinais + Registo de Eventos; journal do sshd na mesma classe). Modos:
  `--seed/--conhecer/--ack-seguranca/--bloquear/--report`.
- `integrations/notifier.py` — sonda `_check_network` (lê a última linha de
  estado do log JSON-lines, contrato do `router_monitor`) → alertas
  `net:dispositivo-novo`/`net:seguranca` com cooldown.
- Units em `runtime/systemd/` + `install-user.sh` atualizado; testes
  `tests/test_network_watchdog.py` (77), `TestCheckNetwork` (7) e
  `TestNetworkWatchdogUnits`.

**Bugs achados no caminho (com teste):** `"dev"` no índice errado do
`ip neigh`; IP colado ao MAC na grade (`\b` não casa — `\b` removido);
primeira versão pegava só a 1ª célula (nome sem MAC) → parser único
compartilhado juntando todas as células; menu lateral poluindo o log do
roteador (filtro `^\d+ (INFO|WARNING|…)`); seed não reconhecia o que o
1º ciclo do systemd já havia catalogado.

**Provas:** seed ao vivo = **20 dispositivos com nome+IP+fabricante**
(Echo-Alex/Echo-Sala/Amazon-Show, 5 lâmpadas Espressif, Tomada1, câmera
MV20604159 = Shenzhen Bilian, celulares Redmi/Samsung com MAC aleatório,
PC-Oficina Intel, o próprio servidor); camada rica = 19 clientes + 60
entradas de log reais; timer no ar (1º ciclo systemd: ativos=10,
rico=true, pendentes=20 → seed zerou); gate **3592 passed / 16 skipped**
(+46 testes); od-core reiniciado **health 25/25**.

**Registrado:** `session.json` (chave `vigia_da_rede_2026_10_21`) ·
CHANGELOG §1.44.0 (subseção "sem bump" nova) · `tools/monitor/README.md`
(seção Vigia) · `txt.txt` · Telegram.

---

## §5 — REGRA NOVA DO DONO: Toda IDEIA DE MELHORIA VIRA ITEM NO TODO (fim de tarde)

**Pedido (regra de processo):** *"toda vez que tiver uma ideia de melhoria
como essa do action mostrar os nomes do inventário do vigia, você coloca
no TODO de atualização para podermos discutir se vamos implementar ou não.
Às vezes posso demorar meses até resolver colocar algo em prática e nesse
tempo posso até esquecer. Sua função, a do sistema, é me ajudar."*

**Contexto:** ele perguntou se existiam dois programas fazendo a mesma
coisa (rotina "leia iniciar" — resposta medida: `router_monitor` = "o
roteador está no ar?", `network_hosts` = foto ARP sob demanda, Vigia =
filme com inventário e alarme; nada duplicado, nada apagado). Na resposta
eu citei uma melhoria possível (a action `network_hosts` devolver os
nomes do inventário do Vigia) — e ele transformou o exemplo em regra
durável.

**Aplicado na hora:**
1. `TODO.md` — regra escrita no topo do arquivo (junto da regra 14 do
   canal) + seção §5 (parking lot) recebeu 3 itens: `network_hosts`
   enriquecida com o inventário (a ideia do exemplo), **rotação da senha
   de WiFi** (pendência técnica de hoje — palavra de dicionário; custo
   real de reconfigurar tudo) e **diagnóstico dos pings perdidos**
   (adaptador USB — oferta de hoje, não pedida).
2. `session.json` — chave `regra_todo_ideias_2026_10_21`.

**Compromisso registrado:** daqui em diante, ideia de melhoria nasce
como item no §5 do TODO — ele decide no tempo dele; eu não implemento
sem ordem.

---

## §6 — DUAS IDEIAS DO DONO: TODO NO FLATNOTES + FERRAMENTAS SUBAPROVEITADAS

**Pedido:** *"um exemplo é que temos várias ferramentas e não estou
aproveitando plenamente, como por exemplo acho que esse TODO deveria ser
uma lista de possiveis melhorias dentro do flatnotes que creio ser o
nosso programa de anotações"*

**Base apurada na fonte (antes de registrar):** o FlatNotes **é** o
caderno markdown da casa (container `od-flatnotes`, porta 8200, no ar
desde 18/10 — v1.40.0) e o sistema **já consegue anotar e buscar** nele:
`flatnotes_anota(titulo, conteudo)` (uma nota por título, recusa
repetição salvo `sobrescrever=true`) + `flatnotes_busca(termo)` +
`flatnotes_status`. Caderno coberto pelos snapshots; acesso via
Tailscale.

**Registrado no TODO §5 (parking lot), sem implementar (regra §5):**
1. **Parking lot dentro do FlatNotes** — modelo "uma ideia = uma nota";
   a decidir: só o §5 vs tudo vs espelho; risco a evitar = duas fontes
   de verdade divergentes (a casa opera com fonte única).
2. **Auditoria de ferramentas subaproveitadas** — 9 serviços + 115
   actions × uso real (journal/métricas) → relatório ferramenta × uso ×
   sugestão concreta, formato possível no `txt.txt`.

`session.json` — chave `ideias_flatnotes_e_ferramentas_2026_10_21`.

---

## §7 — TODO MIGRADO PARA O FLATNOTES: (b) TUDO NO CADERNO, ARQUIVO SOLTO SAIU (noite)

**Pedido:** *"faça o b, se existe ferramenta não tem porque não usar.
arquivo solto só suja o sistema."* — (b) = mover **tudo** o TODO para o
FlatNotes (a opção (a) era só o parking lot; ele escolheu o total).

**Apurado antes de mexer (regra da casa: medir, não presumir):**
- **Nenhum código/teste/painel/site lê o `TODO.md`** — grep no repo
  inteiro: só transcrições históricas (`iniciar/`) e `session.json`
  citam. Remover é seguro; o git guarda o histórico.
- **FlatNotes preso em `127.0.0.1:8200`** — o dono **nem conseguia
  abrir** no celular; para o TODO ser dele, o caderno precisava do
  **bind duplo** (mesmo tratamento da Caixa e do Calibre, v1.41/1.43).
- Cliente real: `FlatNotesClient.anota(titulo, conteudo,
  sobrescrever)` / `.buscar` / `.status` (contract da v1.40.0).

**Migração com prova (9 notas novas → 10 no caderno):**
`TODO — Regras e linhas vermelhas` (as duas citações de regra do
antigo cabeçalho entraram aqui) · `TODO 1 — Stack Nômade` · `TODO 1b —
Decisão final` · `TODO 2 — Pendências do dono` · `TODO 3 — Melhoramentos
técnicos` · `TODO 4 — Dívida técnica` · `TODO 5 — Parking lot` · `TODO 6
— Definition of Done` · `TODO 7 — Fila de ordens (zerada)`. Rodapé de
migração em cada nota; nota-mãe da 1.40.0 preservada; conteúdo indexado
(busca "inventario" → 3 notas).

**Bind duplo + remoção do arquivo:**
compose ganhou `- "100.77.67.53:8200:8080"` (comentar do padrão da casa:
auth=none só dentro da tailnet, nunca no Funnel) → recreate do
`od-flatnotes` → **provas: `127.0.0.1:8200` = 200 e
`100.77.67.53:8200` = 200**, `docker port` mostrando os dois binds, 10
notas intactas (volume próprio). `git rm TODO.md`.

**Nuance registrado (uso real):** a busca do FlatNotes é por **palavra
simples** — "inventario" acha; "network_hosts" (com sublinhado) não
tokeniza. Dica prática no `txt.txt`.

**Regra do dia no lugar novo:** ideias de melhoria agora nascem como
item na nota **"TODO 5 — Parking lot"** (o sistema reescreve a nota
quando algo entra/sai; `sobrescrever=true` é a atualização declarada).
Item §5 "parking lot dentro do FlatNotes" **FECHADO** por esta entrega;
**abertos** no caderno: `network_hosts` com nomes do Vigia · rotação da
senha de WiFi · diagnóstico dos pings · auditoria de ferramentas
subaproveitadas.

**Registrado:** CHANGELOG §1.44.0 (subseção "TODO migrado") ·
`session.json` (chave `todo_migrado_flatnotes_2026_10_21`) · `txt.txt` ·
Telegram.
