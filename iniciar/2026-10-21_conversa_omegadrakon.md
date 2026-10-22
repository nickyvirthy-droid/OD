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

---

## §9 — ACESSOS: 9 NO LAN (SEM TAILSCALE), CADERNO COM SENHA, MQTT E HA EXTERNOS (noite)

**Pedidos encadeados:** (1) *"quando estou usando a rede interna
192.168.0.250, quero ter acesso a todas as ferramentas sem tailscale"*;
(2) escolha no questionário — **"Todas as 9 + senha no Caderno"**;
(3) *"também quero ter acesso externo ao Homeassistant e ao mosquitto"`;
(4) *"HA e MQTT possuem app próprio, só preciso de uma url externa"*.

**Medição antes de mexer (regra da casa):** Site e HA já abriam no LAN
(0.0.0.0); as 9 ferramentas estavam `127.0.0.1` (+ tailnet em 3);
Mosquitto = serviço do sistema **só em `127.0.0.1:1883`** (nem de casa
alcançava); sudo **indisponível** na conta (a casa opera em `--user`).

**Parte A — casa sem Tailscale:** bind `192.168.0.250` em todas as 9
(comentários atualizados — os antigos diziam "nunca LAN"). Duas
couserros no caminho, ambos provados e consertados: (i) comentário de
bloco perdeu o `#` e derrubou o YAML (`go-yaml load error` — consertado
por sed na linha exata + `docker compose config --quiet` como gate);
(ii) FlatNotes em crash loop — **`FLATNOTES_SECRET_KEY` é obrigatória
com auth** (log provou: "Environment variable FLATNOTES_SECRET_KEY must
be set"). Stirling era só Java devagar (healthy aos 59s). **Prova final
9/9** em `http://192.168.0.250:<porta>` + HA 200.

**Caderno com senha:** `FLATNOTES_AUTH_TYPE=password`, usuário `dono`,
senha + secret key no `.env` (gitignorado). **Contrato de auth apurado
ao vivo via `/openapi.json`** (não chutado): rota = `POST /api/token`
**JSON** → `{"access_token","token_type":"bearer"}` (form-data dá 422);
protegidos = `/api/notes/*` e `/api/search`; `/health` e `/api/config`
públicos. `FlatNotesClient` estendido: `usuario`/`senha` explícitos
(anônimo = contrato byte a byte intacto), `_login()` JSON→bearer,
`Authorization` só quando há token, **401 renova a sessão UMA vez e
repete**, erro `flatnotes_login_falhou` honesto que **nunca ecoa a
senha**; fábrica lazy passa a injetar `FLATNOTES_USERNAME/PASSWORD` do
`.env`. +4 testes fiéis ao contrato vivo = **44 no módulo**. od-core
reiniciado (regra 7.3) → action ao vivo `POST /executa
{"action":"flatnotes_status"}` → **`auth_type: password, notas: 10,
ok`**. Senha espelhada no cofre via `VaultClient.guardar` → item
**"FlatNotes — caderno"** (id 6ae32708; padrão da casa; fora de git,
transcrição e txt.txt).

**Externo:** HA já escutava em `0.0.0.0` → URL pronta
`http://100.77.67.53:8123` (provada 200). Mosquitto: Funnel **não
carrega TCP** (HTTP-only) e sudo não há → **`tailscale serve --bg
--tcp=1883 tcp://127.0.0.1:1883`** (a sintaxe oficial `--tcp=porta`
veio do doc depois de duas tentativas erradas `tcp://:1883`; serve é
user-scope, persiste e sobrevive a reboot — listado no status como
"tailnet only"). **Prova forte: `mosquitto_pub` real com as
credenciais do `.env` publicou pela tailnet** (`od/prova/externa2`).

**Aviso honesto entregue:** LAN = quem tem a senha do WiFi alcança as
ferramentas (4 sem login, mas genéricas e sem dado pessoal; o Caderno
foi justamente o que ganhou senha); Vigia vigia aparelho novo; rotação
da senha de WiFi segue no TODO 5. **"Puxar para dentro do Site"**
explicado com as travas de subcaminho provadas no portal 8443 (5 das 9
quebradas lá) e **fase 1 proposta** — decisão do dono pendente.

**Registrado:** CHANGELOG §1.44.0 (continuação "Acessos") ·
`session.json` (chave `acessos_lan_externos_2026_10_21`) · `txt.txt` ·
Telegram (senha só lá — canal privado).

## 10 — FASE 1 DO PORTÁRIO: 5 FERRAMENTAS DENTRO DO SITE, ATRÁS DO LOGIN

O dono respondeu **"sim fase 1 com as 5"** (Caderno, CyberChef,
IT Tools, Caixa, Cofre) e pediu para **analisar se realmente precisa
das outras 4 na internet** (Livros/Kiwix/Stirling/Homebox). Também
vetou o Kiwix público com uma ideia melhor: *"kiwix é uma enciclopédia,
ela pode ser fornecida dentro do chat"* (ex.: *"define dia"* → o chat
explica que dia é uma duração de 24 horas) — **verificado antes de
afirmar**: `integrations/kiwix.py` já tem busca+artigo e o kiwix-serve
responde busca JSON 200; falta o orquestrador consultá-lo (hoje só a
action admin usa). Ideia gravada na nota **TODO 5** do FlatNotes, com o
exemplo do dono; a enciclopédia não vai para a internet pública.

**Portário construído no od-core** (ferramenta nunca é exposta direto
ao Funnel — o portão é sempre a sessão do dono):

- Rotas `GET/POST/PUT/DELETE /f/(caderno|cyberchef|itools|caixa|cofre)/*`
  em `AUTH_EXEMPT` (navegador não manda header) + **gate dentro do
  handler**: cookie `od_sessao` (HttpOnly, SameSite=Lax — o MESMO token
  de `/auth/login`; logout derruba os dois) ou `Bearer`/`X-API-Key`, e
  sempre **papel admin** (`_role()`: conta do dono). Registro aberto não
  vira passagem livre: conta comum logada = **403**; sem credencial =
  **302 → `/auth/login`**.
- **Proxy `http.client`** (não segue redirect sozinho, de propósito):
  strip do prefixo na ida — exceto o **Cofre**, que vive dentro do
  prefixo (`FERRAMENTAS_MANTEN_PREFIXO`) —, `Location` reescrito para o
  portário, hop-by-hop higienizado, corpo em blocos de 64 KB (download
  da Caixa sem estourar RAM), cookie do backend repassado, e **101 =
  relé cru de WebSocket** (notificações do Cofre).
- **Caixa**: `FILEBROWSER_BASEURL=/f/caixa`. Precedência **settings.json
  > db > env** apurada ao vivo — o env sozinho não bastou (um
  `baseURL ""` explícito vencia); solution durável = settings versionado
  (`docker/filebrowser-settings.json`) montado como fonte única.
- **Cofre**: `DOMAIN=https://nicky-server.tail1b1f51.ts.net/f/cofre`
  (web vault nativo no path). **O link direto `:8443` do portal legado
  morreu para o cofre** — o app Bitwarden deve apontar a URL nova, que
  funciona em qualquer rede.

**Provas:** 14/14 testes novos (`tests/test_portal_ferramentas.py` —
portão, proxy, relé WebSocket cru com backend fake, mapa das 5,
`/f/livros` = 404) + gate completo. Vivas: sem credencial **302**
(local e pelo Funnel público), as 5 **200** com chave de operador,
`/f/caderno/api/config` **200** com JSON (API relativa chega inteira),
ativos da Caixa **200** em `/f/caixa/static`, Cofre **200** no path,
raiz do Site **200** intacta.

**Análise das outras 4 (a resposta ao dono):** as quatro **não entram
no portário** — não suportam subcaminho (provado no portal 8443, 5 das
9 quebradas lá) e o Funnel só publica o Site. Recomendação: **casa +
celular (Tailscale) bastam** para Livros, Stirling e Homebox; o Kiwix
fica com o destino novo (o chat). Se algum dia precisar de público de
verdade, o caminho é **hostname próprio** (DDNS + proxy), nunca
subcaminho.

**Retrabalho (22/10, feedback do dono): o portário parava numa tela de
login SEM campo para digitar.** Causa achada em produção: meu 302
apontava para `/auth/login` — que é **rota de API (só POST)**; o
navegador recebia 405 JSON. O formulário de verdade é o do `/chat` (o
"gate" com `#login-user`/`#login-pass`). Correção: portão →
`/chat?next=/f/<ferramenta>/` + guarda no JS do login (`startsWith
("/f/")`, sem open redirect) — ele digita a senha e cai direto na
ferramenta. **E a ordem nova:** "coloca um link no menu do
administrador" → seção **🛠 Ferramentas** no `/admin` (5 cards, aba
nova, mesma sessão). +2 testes de contrato (formulário/guarda no chat;
menu das 5 no admin) = 16/16 no arquivo do portário; provas vivas do
Location novo, do campo de senha e dos 5 links.

**Rodada 2 (22/10, feedback em sequência — cada item com teste):**
(1) *"...colocou como botão na tela do admin, quero que fique no
menu"* → a seção de cards SAIU do corpo do admin e as 5 entraram no
**menu lateral do Órion** (`lateralFerramentas`, mesmo gate de papel
do item Admin). (2) *"...abrindo nova aba em vez de abrir dentro do
próprio site"* → **mesma aba** (guarda de teste proíbe
`target="_blank"` no bloco). (3) *"...mesmo já estando logado ele
entra na tela de login e depois vai direto para o chat"* → causa: o
token antigo vivia só no localStorage, **sem cookie**; solução: rota
**`POST /auth/session-cookie`** (Bearer válido → grava `od_sessao`;
inválido → 401 sem cookie) chamada pelo JS **em todo boot com sessão**
e **antes** do salto `?next` — logado antigo agora vai direto à
ferramenta. Extras no mesmo fôlego: **barra do topo fixa**
(`position: sticky` nas 3 telas — o nome do dono sempre visível) e
**botão flutuante ↑** no Painel e no Admin (monta depois da guarda do
herói; **o chat não monta**, o dono confirmou que não precisa).
20/20 no arquivo do portário; rotas 91→92 (mirror + público).

**Rodada 3 (22/10 — "vamos parar e analisar"; ordem nova: praticidade):**
O dono relatou: CyberChef abriu; Caderno e IT Tools não (tela branca);
Caixa e Cofre pediam senha. Análise + repro headless (playwright no
chromium do od-vigia-venv contra instância de teste em :8199 com conta
temporária — sem tela no servidor, o navegador renderiza igual): causa
raiz do Caderno = `<base href="/" />` do FlatNotes (assets resolviam
contra a raiz do Site →404); IT Tools = `/assets/` absoluto. Decisões
do dono (por escolha explícita): portário com **Cofre, Caixa, Caderno
e CyberChef**; **IT Tools sai** ("a resposta é tirar" — fica em
casa/tailnet:8430); **"se for ter que digitar senha não vou querer; o
objetivo é ser prático; tudo o que puder ser feito com IA através do
chat eu aprovo"**. Entrega: proxy reescreve o HTML das SPA pro
prefixo; `FLATNOTES_AUTH_TYPE=none` (bot já opera sem login —
`flatnotes_status`/`busca` provados); **Caixa com login automático**
no proxy (FileBrowser v2: JWT no CORPO text/plain — apurado ao vivo;
Set-Cookie `auth` escopado + JWT injetado no localStorage do shell, que
é onde a SPA olha → `/f/caixa/files/` sem digitar nada); **Cofre tira
o portão de sessão** (clientes Bitwarden não falam cookie — senha-mestra
é o portão; web/app passam a funcionar do celular); portão reforçado
(qualquer cookie válido entre duplicados + log com motivo). O chat já
atende os dois desejos dele de interface: `flatnotes_anota`/`flatnotes_busca`
e `vault_list`/`vault_get`/`vault_set`. +5 testes = **25/25**; provas
vivas no od-core reiniciado + repro headless completo.

## §11 — Cofre compartilhado: organização OmegaDrakon (22/10, madrugada)

**Gatilho:** o dono tentou logar o app na conta pessoal e viu tela
vazia. Diagnóstico (painel admin do cofre): **2 contas ativas** —
`nickyvirthy@gmail.com` (pessoal, criada15/10, vazia de propósito) e
`od-sistema@omegadrakon.dev` (serviço, criada17/10, **os20 segredos**);
ambas verificadas, sem2FA (ponto fechado: dono não quer ativar).
Conselho dado (Telegram3198): logar o app na conta de serviço.
Resposta do dono: **"monta a org"**.

**Como entrou (API do cofre com o payload da web vault oficial):**
`POST /api/organizations` devia422 teimoso; o struct do Vaultwarden
exige `billingEmail` + `collectionName` + `key` + `name` +
**`planType`** (este era o faltante — NumberOrString, ignorado depois,
mas obrigatório). A crypto é client-side e o navegador fez a parte
dele: capturei o pedido exato da UI (`/tmp/opencode/od_req_capta.json`)
— `name` **plano**, `key` = chave da org em RSA-OAEP (`4.…`),
`collectionName` em AES-CBC+HMAC (`2.iv|mac|ct`), `keys` = par novo da
org, `planType:0` — e **repliquei byte a byte** com curl → **200**.
Organização **OmegaDrakon** `96c6d166-…`, coleção **Segredos**
`f2589058-…`; conta de serviço = Owner Confirmada.

**Convite sem SMTP:** `POST /api/organizations/{id}/users/invite`
(`emails:[]` + `groups:[]` obrigatório + coleção como objeto
`{id, readOnly, hidePasswords, manage}`) → conta pessoal entrou
`status=1` (Aceita) e o **`bw confirm org-member`** fechou em
`status=2` (Confirmada) — o confirm é server-side, dispensa o email.
Obs.: bw CLI exige `bw sync` antes ("No encryption key for this
organization" = sync local atrasado).

**Migração dos20 itens:** `bw edit item --organizationid` com o JSON
em **base64** (argumento posicional) — o bw re-criptografa com a
chave da org;19+1, **zero falha**, final:20 na org /0 pessoais.

**Achado do bw CLI (registrado):** payload com org em **JSON cru** no
stdin morre com *"Error parsing the encoded request data"* — o
formato é **base64 + `\n`**. O `_codifica` do `vault.py` já fazia
certo (o teste errado foi meu, não o código).

**Bot alinhado (o único código que mudou):** `integrations/vault.py` —
`VaultClient` ganhou `org`/`colecao` (fábrica lê `OD_VAULT_ORG` /
`OD_VAULT_COLECAO` do `.env`) e `guardar()` injeta
`organizationId` + `collectionIds` ao **criar** (update já carregava
a org pelo doc do `bw get`). Prova viva: `vault_set('zz-teste-org-live',
…)` gravou **dentro** da org, `vault_get` leu de volta, item de teste
apagado permanente. +3 testes = **35/35** no `test_vault.py`.

**Cadeia de prova final:** org criada (200, `hasPublicAndPrivateKeys`),
membro pessoal Confirmed,20/20 na org, create/edit/delete de item de
org nos3 formatos testados, `vault_set`/`vault_get` ao vivo. Dono vê
tudo ao abrir o app (sync puxa a org); segredos novos do bot caem na
org — visíveis pra ele também.

## §12 — "Não funcionou": o item da org SEM coleção (22/10, manhã)

**Relato:** *"não funcionou. no site tela vazia, no app Bitwarden nada"*
— logo depois da org pronta e confirmada. Os clientes dele sincronizavam
normal (sync 200, login novo às 11:30 no log do cofre), então não era
sessão velha: o servidor entregava sync e ele via vazio.

**Diagnóstico sem chute (meu token de API tinha expirado — 401):** li o
**banco SQLite do cofre direto** (db.sqlite3, modo ro). Membro `status=2`
(Confirmed), `atype=2`, `akey` de 346 chars, usuário com chave pública E
privada, `users_collections` com a linha dele ligada à Coleção Segredos.
**Servidor perfeito** — e os 20 itens?

**Achado:** `ciphers_collections` com **ZERO linhas**. Os 20 itens estavam
na org mas **sem vínculo com a coleção**: `create`/`update` do bw
**ignoram `collectionIds` no payload** (o fonte confirma —
`update_cipher_from_data(…, None, …)`: os dois caminhos passam `None`;
o bw até ecoa `collectionIds` na resposta, mentindo bonito). Coleção só
grava pelo endpoint dedicado `PUT /ciphers/{id}/collections`, que o
cliente oficial chama em separado depois de salvar — um passo que a
migração por CLI não fez.

**Por que passou despercebido pra mim:** a conta de serviço é Owner com
`access_all=1` → enxerga os itens **mesmo sem coleção**; a conta pessoal
do dono é User com `access_all=0` → enxerga **só o que está em coleção**.
Meu "20/20 na org" media a metade errada. Lição registrada: provar a
visão do USUÁRIO, não a do dono da API.

**Formato do reparo (apurado ao vivo):** `bw edit item-collections <id>
<base64>` com **array cru** `["<colecao>"]` — o objeto `{"id":…,
"collectionIds":[…]}` devolve **422** (o struct `CollectionsAdminData`
só aceita `collectionIds: Vec`); com o array, exit 0. **20/20 reparados →
banco com 20 linhas** (antes: 0).

**Patch no bot (`integrations/vault.py`):** método novo `_liga_colecao()`
— `guardar()` chama `bw edit item-collections` logo após o **create**
(item novo nasce com coleção) e o **update** auto-cura item sem a
coleção (`collectionIds` do `bw get` não contém a dela → anexa). Prova
viva: create limpo → linha `('f2589058-…',)` no banco. Falso negativo
registrado: o primeiro teste deu "None" porque o uuid foi capturado em
command substitution e o **log do cofre sai no stdout** junto — lição:
gravar id em arquivo, nunca em `$()`.

**Guardas:** +2 testes = **37/37** no `test_vault.py` (create anexa o
array cru sem segredo em argv; update já-ligado não gera chamada extra;
o caminho pessoal nunca chama `item-collections`).

**Estado final:** sync do dono agora devolve os 20 itens — app e site
mostram tudo no próximo sync, sem relogar.

---

## §13 — Tela preta no site + app vazio: duas causas de cliente (22/10)

O dono mandou "leia analise e veja o que estou vendo" e deixou duas
capturas na pasta nova `analise/` do repo (09:10 e 09:12): **(a)** o
cofre aberto no **Edge (Windows 11)** em `…/f/cofre/#/vault` com a tela
**totalmente preta** (título da aba "Cofres | Vaultwarden Web"); **(b)**
a Caixa funcionando (um 409 de upload duplicado — benigno).

**Diagnóstico — servidor provado íntegro em quatro frentes:**
1. **Repro headless** (chromium, locale pt-BR, mesma URL pelo proxy):
   login → onboarding → `#/vault` renderizando o vault **inteiro com os
   20 itens da org**. Mesmo caminho, mesmo proxy, tudo pinta.
2. **Sync real dele** executado no banco com a query `find_by_user` do
   fonte 1.36.0: **21 itens** (20 da org + 1 pessoal de 15/10 —
   estruturalmente perfeito, formato "2.").
3. Logins/sync/profile da sessão dele: **todos 200**; journal do
   od-core limpo (sem 5xx/exceções na janela).
4. Rota `GET /users/{id}/public-key` no fonte 1.36.0 devolve a chave do
   usuário pedido — o `akey` dele é válido por construção.

**Causa 1 — tela preta no site = extensão Dark Reader.** Issue upstream
aberta (darkreader#15190, "[Broken Website] Bitwarden vault/dashboard
is completely black", Win 11 + **Edge**, sintoma idêntico: "the entire
page goes completely black" ao logar no vault). O conserto é do lado
do dono: ativar **"Detect Dark Theme"** no Dark Reader (ou pausar a
extensão no site / abrir em aba anônima).

**Causa 2 — app "nada" = servidor velho demais pro cliente novo.**
Issue vaultwarden#7485: clientes Bitwarden **2026.7+** mostram cofre
**vazio** contra servidores < 1.37 — *"You need to update your
Vaultwarden to v1.37.0 else you will keep seeing an empty vault"*.
Nosso cofre estava em **1.36.0**. Atualizado para **1.37.4**:
backup do banco (`db-pre-update-1.37.4-20261022-1043.sqlite3`), tag no
`docker/tools-compose.yaml`, container recriado; health ok, bw sync
devolvendo 20 itens, proxy `/f/cofre/` 200, repro renderizando.

**Achado cosmético:** o nome real da coleção é **"Default collection"**
(o convite criou com o nome default — o bw decryptou). Renomeável
quando o dono quiser.

**Estado final:** do lado do servidor não há nada a fazer — as duas
peças restantes são do lado do dono (Dark Reader no Edge; sync/relogar
no app com o servidor já atualizado).


## §14 — "Existe um erro": a senha dos 19 itens era a descrição (22/10, tarde)

O dono abriu o cofre (agora funcionando — site e app) e reportou, com
exemplo: *"admin_token a senha está escrita: Admin_token do painel do
vaultwarden, e mais outro com chave gemini"*. Os dois exemplos batem
com os itens ativos `ADMIN_TOKEN` (senha = "ADMIN_TOKEN do painel do
Vaultwarden.") e `GEMINI_API_KEY` (senha = "Chave de API do Google
Gemini.") — **o campo senha dos 19 itens espelhados continha a DESCRIÇÃO,
não o segredo.**

**Causa raiz (uma linha, minha, no espelho):** `vault_env_mirror.py`
montava `alvo = {k: v for k, v in CREDENCIAIS.items() …}` — o destino
vinha do dicionário de **descrições** da allowlist, não do `.env`; o
laço gravava `valor = alvo[chave]` (a descrição) como senha. Pior: a
conferência `item == valor` comparava a descrição gravada com a própria
descrição — **sempre passava**. Por isso a rodada da madrugada (01:27)
e minha reexecução de hoje (13:52) reportaram "19/19 conferem" em cima
do dado errado, e por isso o `--check` "confirmou". (Os spot-checks
independentes contra o `.env` — hash lado a lado — é que denunciaram:
cofre com 37 chars de prosa, `.env` com o valor real.)

**Caça ao "segundo culpado" (era eu de novo):** durante a apuração os
itens foram reescritos a cada ~13 s no log do Vaultwarden — 19 PUTs
exatos = a própria rodada do espelho (6 chamadas de `bw` por item ≈
13 s). Não havia daemon nem sessão irmã: o loop suspeito era o meu
comando. Item "criado e lixeirado" em segundos às 08:55–08:59 = 4 itens
curados descartados (geração antiga, na lixeira até hoje — inócuos).

**Conserto:** `alvo = {k: valores[k] for k in CREDENCIAIS if
valores.get(k)}` — o valor passa a vir do `.env`; descrição continua na
nota de cada item (desenho original). Reexecução: 19/19 gravados e
**verificação independente crua** (`bw sync` + `bw get item` direto ×
`ler_env(.env)` para os 19) = **19/19 conferem** com os valores reais.

**Guarda (bug deste porte não pode passar em branco de novo):**
`tests/test_vault_env_mirror.py` **+7** — senha = valor do `.env`
(regressão), descrição vive na nota, `--check` acusa DIVERGENTE quando
o cofre tem descrição, username vem de outra chave do env, aviso de
segredo fora da allowlist, allowlist ausente avisa. Gate completo
**3632 passed / 16 skipped**.

**Estado final:** cofre com os 19 segredos reais (mais o FlatNotes, já
correto); dono só precisa dar um sync no app/site para ver as senhas
certas; registros + commit nesta rodada.
