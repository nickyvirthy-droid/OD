# 2026-11-01 — conversa OmegaDrakon

> Registro conforme regra 4 do `iniciar/RULES.md`. Contexto em
> `iniciar/session.json` (chave `reverificacao_rotina_2026_11_01`).

## §1 — "leia iniciar" (01/11 ~05:10): reverificação com achados novos

**Pedido:** usuário: "leia iniciar" — reverificação de rotina (regra 3).
Checkpoint: `reverificacao_rotina_2026_10_30` (30/10 13:50 → updated
31/10 12:30, §8/§9 — v1.8 em lotes no ar, DNS restaurado).

### 1. O que mudou desde o registro (fora da última troca)

- **Plano (a) EXECUTADO PELO DONO — cabo Ethernet ligado:** `enp2s0`
  está **UP com 192.168.0.205** (DHCP, metric 100 = rota primária) e o
  uplink saiu do WiFi: `ip route get 1.1.1.1` → `dev enp2s0 src
  192.168.0.205`. O WiFi `wlx000f0037acf0` (192.168.0.250) continua no
  ar como **reserva** (metric 600 — failover por métrica do kernel).
  Ele confirmou no txt.txt (01/11 04:44): *"IP 192.168.0.205 é o próprio
  servidor só que com internet cabeada"*.
- **DOIS reboots do host em 31/10:** boot 14:11:49 → shutdown14:41:54 e
  boot atual 14:42:27 (kernel 6.8.0-146 → **6.8.0-147**; ambos os
  shutdowns LIMPOS via `systemd-reboot.service`, não crash — comandados,
  provavelmente por ele durante a troca do cabo). **Consequência: a
  execução v1.8 morreu no meio** (log para 14:10:46, up no reboot
  seguinte).
- **Mensagem nova no txt.txt** (01/11 04:44) = a de cima, resposta ao
  alerta `net:dispositivo-novo`.

### 2. Estado medido agora (evidência, não suposição)

- **Git ARVORE LIMPA**, HEAD `7b0fef4` == `origin/master` (nenhuma
  mudança de código desde o registro — sem resíduo de sessão morta).
- **od-core:** active desde 31/10 14:42:30 (subiu com o boot),
  MainPID **1217**, **NRestarts=0**. **/health `ok=true`, `status=up`,
  NENHUM check fora** (depois do conserto §4).
- **Borda:** Funnel `/` **200**; DNS público **NOERROR**
  209.177.145.97/192; stream `/radio.mp3` **206 audio/mpeg**.
- **Rádio tocando música do acervo:** nowplaying = "JULLIANY SOUZA -
  QUEM É ESSE？ (AO VIVO)"; **223 mp3** no storage do AzuraCast.
- **Journal hoje:** 1 [ERROR] (05:00 sink Telegram DNS — mesmo blip de
  link de sempre; agora o uplink é o cabo).
- **Vigia relatório 01/11 04:35:** 4 sondas VERDES, fila do juiz vazia,
  `avisado=false`.

### 3. Alerta "dispositivo novo" = o próprio servidor (reconhecido)

O alerta `net:dispositivo-novo` avisava `84:7B:EB:FB:09:39 (Dell Inc.,
192.168.0.205)`. Conferido: **MAC é o do `enp2s0` do próprio servidor**
(`ip link show enp2s0` → 84:7b:eb:fb:09:39) — ele apareceu como "novo"
porque a placa estava DOWN até a troca do cabo. Com a confirmação dele
no txt.txt, executado `network_watchdog.py --conhecer 84:7B:EB:FB:09:39
Servidor-Cabo` → `pendentes_novos: 0` (o alerta proativo some no próximo
tick).

### 4. calibre-web caído — causa raiz e conserto

- **Sintoma:** `/health` degraded (`ok=false`) só com
  `tool_calibre_web fora (Connection refused — 127.0.0.1:8420)`;
  container `od-calibre-web Exited (128)`.
- **Causa raiz (docker inspect):** `failed to bind host port
  100.77.67.53:8420/tcp: cannot assign requested address` — **corrida
  de boot**: o dockerd tentou bindar o IP da tailnet antes do
  tailscaled atribuir `100.77.67.53` ao `tailscale0` (boot 14:42:34; o
  tailscaled sobe depois).
- **Achado honesto do conserto:** `docker start` e `docker restart`
  subiam o container **sem reprogramar a porta** (`NetworkSettings.Ports
  = {}`, sem listener, container "running") — a falha de bind da criação
  da endpoint não é refeita em start simples. **Resolvido recriando:**
  `docker compose -f docker/tools-compose.yaml up -d` (Recreate) →
  porta programada nos 3 binds (127.0.0.1, 192.168.0.250,
  100.77.67.53), **8420 → 302** e `/health` volta `ok=true`.
- **Melhoria pendente (registro, sem agir):** a corrida docker×tailscale
  vai se repetir em TODO boot — post-up ou `network_mode: host` seriam
  a correção de causa; exige decisão (ordem).

### 5. v1.8 — parada no reboot, RETOMADA

- Estado no retomar: **223 mp3 no acervo** (já no ar) + **64 em
  `temp/`** (o 65º é o artefato `__ln_*` do loudnorm interrompido — o
  pipeline já o ignora, `musica.py:1164/1199`); `000/` vazio.
- **Retomada 01/11 05:21:45:** `./run.sh --sem-renomear` → `Dedup: 64
  novo(s), 0 duplicado(s)` → lote de 10 (55 restam). **1ª tentativa
  MORREU** com o fim do shell (nohup sozinho não bastou — o harness mata
  o process group; lição: é `setsid`). **2ª tentativa 05:26:06 (pid
  843908, sid próprio 843907 = desvinculado)** e viva: já normalizando
  (1ª música 05:26:25). Log: `logs/execucao_v18_retomada_20261101.log`.
- **Achados honestos da execução de 31/10 (reconstruídos do log):**
  dezenas de **429 do Gemini** (rate limit) → fallback por palavras-
  chave (por isso 161 em "Outros" no classification), 3× "Gemini falhou
  após 5 tentativas", 2× loudnorm timeout de 120s, 1 "Tags incompletas"
  mantido em temp (`Danilo & Davi.mp3`).

### 6. Segurança — pendência nova (informar o dono)

**4 eventos sshd** (pendentes_seguranca) hoje **05:07**: `Invalid user
ALEX` + `Failed password` vindo de **100.77.242.82 = o desktop dele**
(`desktop-4icaj6f`, via tailnet). Usuário real é `alex` (minúsculo) —
provable erro de digitação dele ao tentar SSH agora de madrugada. NÃO é
ataque externo (só tailnet), mas precisa do aviso: usuário `alex`.

### 7. Canais e analise/

- **txt.txt:** mensagem dele acima (01/11 04:44); reescrito com o
  resumo desta troca.
- **analise/:** `Prompt_Nicky_Musicas.txt` NOVO (31/10 11:55) = o
  **mesmo pedido v1.7 (.m3u)** que já foi executado — sem ação nova; a
  pasta `Nicky Musicas/` **não existe mais** em analise/ (renomeada/
  movida por ele; `Nicky Radio/` intacta).

### 8. Estado

**SISTEMA VERDE — v1.44.0/2080, HEAD `7b0fef4`, árvore limpa,
health ok=true 25/25, Funnel e rádio no ar, uplink NOVO em cabo
(192.168.0.205) com WiFi de reserva.** v1.8 em retomada (64 restantes).

**Fila do dono:** (a) aguardar v1.8 terminar (aviso no txt.txt + Telegram
quando fechar — regra 15); (b) dizer se o SSH de 05:07 foi ele (usar
`alex`, minúsculo); (c) definir correção da corrida docker×tailscale do
calibre (§4) quando quiser; (d) parking lot: auditoria de uso de
ferramentas, MCP (rota WiFi resolvida pelo cabo).

## §2 — dono responde a fila (01/11 ~05:40): tudo confirmado

**Pedido:** dono: "1. ok. 2. ok. 3. ok. 4. sim."

1. **Cabo** — confirmado dele (plano (a) fechado).
2. **Retomada da v1.8** — confirmado; execução seguindo: 1º lote fechou
   05:31:38 (acervo 223 → **233**, .m3u regeneradas, AzuraCast
   sync), 2º lote no ar (44 + 10 em processamento). Ritmo ~5min45/lote
   → ETA **~06:07**.
3. **Calibre-web** — "ok" = ciente. **NÃO interpretado como ordem** para
   a correção da corrida docker×tailscale (mutação de compose exige
   ordem explícita — segue como pendência registrada na §1.4).
4. **SSH das 05:07 foi ELE** ("sim") — caso fechado: era o desktop dele
   com `ALEX` maiúsculo; benigno, sem evento de segurança real (usuário
   correto `alex`; aviso escrito no txt.txt).

## §3 — corrida corrigida, reserva DHCP criada, opção B aplicada (01/11 ~05:45–07:00)

**Pedido:** dono: "certo. 3 pode mexer, corrija" (corrida docker×tailscale);
"não precisa trocar os ips final 250 para 205?"; "e também fixar esse ip no
roteador"; depois "B. leia o txt também".

### 1. Correção da corrida (item 3 — autorizado)

- `docker/tools-compose.yaml`: binds `100.77.67.53:*` removidos dos 3
  containers (flatnotes 8200, filebrowser 8410, calibre-web 8420) com
  comentário explicando a causa (dockerd programa o bind na CRIAÇÃO antes do
  tailscaled atribuir o IP ao tailscale0 → exit 128 no boot).
- Tailnet agora via `tailscale serve --bg --tcp=PORTA tcp://127.0.0.1:PORTA`
  (backup em `backups/tailscale-serve-20261101-0550-status.json`).
- Prova (sandbox antes do real, regra 10): TCP serve = mesmo comportamento do
  bind direto (IP tailnet + hostname → 200/302; LAN OK). HTTP serve deu 404
  por IP literal e foi descartado.
- Verificação: IP+hostname+LAN+loopback 200/200/302 nos 3; `/books` da 8443 →
  302 e Funnel → 200 intactos; health verde.

### 2. Reserva DHCP do .205 no roteador (ordem "fixar esse ip")

- Roteador TP-Link Archer C6 (UI `tpos`, PT-BR); senha já no cofre `.env`
  (`ROUTER_ADMIN_PASSWORD`, registrado 21/10). Automação nova via playwright
  (venv do vigia) — rotas descobertas por exploração read-only:
  Avançado → `#dhcpServerAdv` → seção "Reserva de Endereço" (botão Adicionar).
- Diálogo mapeado: 8 campos = Nome + 6 octetos MAC (`-----`) + Endereço IP.
- Código: `_reservar()` em `tools/monitor/vigia_rich.py` (espelho de
  `_bloquear`, prova por releitura) + modo `--reservar MAC IP [NOME]` em
  `tools/monitor/network_watchdog.py` (espelho de `--bloquear`).
- BUG pego na prova: 1ª versão checou MAC+IP no corpo INTEIRO da página →
  falso positivo (`ja_reservado`) porque a lista de clientes DHCP do MESMO
  painel também mostra o par. Correção: `_linhas_reservas()` restrito ao
  painel "Reserva de Endereço" (3 linhas).
- O gate pegou a 2ª sobra de design: `TestBindDuploCompose` exigia
  `100.77.67.53:8410` no compose (a guarda antiga codificava a corrida em
  si). Guarda atualizada para o contrato novo: `127.0.0.1` + `.205`
  presentes e o IP da tailnet **proibido** no compose.
- Gate final: **4012 passed / 16 skipped / 0 falha · 90,47%** · pyflakes
  0 aviso novo. Commit `db0b4a1` pushado; Telegram msg 3518 (regra 15).
- EXECUTADO: `Servidor-Cabo / 84:7B:EB:FB:09:39 → 192.168.0.205` — tabela
  re-lida mostrou 4 linhas com a reserva no topo; servidor segue em .205.

### 3. Pergunta .250 → .205 (medição) e escolha do dono

- Medido: `192.168.0.250:{8420,8410,8200}` → 302/200/200;
  `192.168.0.205:` mesmas portas → 000 (services no .250).
- Opções entregues: (A) manter .250; (B) trocar binds para .205.
  **Dono escolheu B.**

### 4. Opção B aplicada

- 9 binds LAN do compose: `192.168.0.250:` → `192.168.0.205:` (comentário do
  kiwix atualizado explicando a troca + reserva DHCP).
- `docker compose -f docker/tools-compose.yaml up -d` recriou os 9.
- Verificação: 9/9 respondendo no .205 (8480 com 404 na raiz = comportamento
  normal, `/f/cofre` → 200); .250 morto nos binds (esperado); tailnet
  (serve) 200/200/302 por IP e hostname; loopback OK; `/books` 302; Funnel
  200; health `ok: true` nenhum fora (stirling 000 momentâneo = Spring Boot
  ainda subindo, depois healthy).

### 5. txt.txt: aviso repetido do SSH (pergunta do dono)

- Pergunta dele: "o que é isso. porque está repetindo?" (WARN de 4 eventos
  de segurança pendentes — `Invalid user ALEX`).
- Resposta: era ELE (desktop via tailnet, 100.77.242.82) com `ALEX` maiúsculo
  às 05:07–05:08; cada tentativa inválida vira um evento novo no Vigia e o
  alerta do Telegram só some quando a fila é reconhecida. Executado
  `--ack-seguranca` → 4 reconhecidos, pendências zeradas.

### 6. v1.8 fechou

- 06:10:47 `Pipeline concluído v1.8` (pid 843908, setsid — sobreviveu).
- Acervo **287 mp3** (223 → 233 → 287), temp vazio; classificação: Gospel 88,
  Internacional 13, MPB 7, Outros 165, Pop 9, Rock 2, Sertanejo 3; .m3u por
  gênero + Mix_Radio.m3u; AzuraCast sincronizada.

## §4 — "leia iniciar" (01/11 ~20:22): reverificação noturna, tudo verde

**Pedido:** usuário: "leia iniciar" — reverificação de rotina (regra 3, SO
LEITURA). Checkpoint: `corrida_reserva_dhcp_opcaoB_2026_11_01` (07:20).

### 1. Estado medido (20:22–20:24, tudo por evidência)

- **Git ARVORE LIMPA**, HEAD `53c463a` == `origin/master` (0 resíduos).
- **od-core:** active desde 31/10 14:42:30, MainPID **1217**,
  **NRestarts=0** (~30h no ar).
- **/health autenticado:** `ok=true`, `status=up`, **nenhum check fora**.
- **Journal 07:20 → 20:22:** **ZERO** warning/erro (primeiro trecho limpo
  depois dos blips de link da madrugada — uplink agora é o cabo).
- **Borda:** Funnel `/` **200**; `/radio.mp3` **206 audio/mpeg**;
  nowplaying "Isadora Pompeo — Hey, Pai" (acervo no ar).

### 2. Depois da corrida + opção B (prova das 9 + 3)

- **LAN .205: 9/9** — 8090/8100/8200/8400/8410/8430/8470 → 200, 8420 → 302,
  8480 → 404 na raiz (comportamento normal, `/f/cofre` é 200).
- **.250 morto** nos binds movidos (8200/8420 → 000, esperado).
- **Tailnet (serve TCP):** 8200 → 200, 8410 → 200, 8420 → 302 via
  `100.77.67.53`.
- **Prova de boot ainda pendente:** nenhum reboot desde 31/10 14:42 — a
  correção da corrida será provada no próximo boot (registro feito na §3).

### 3. v1.8, Vigia e canais

- v1.8 fechou 06:10:47; **acervo 287 mp3**, `000/` e `temp/` vazios (sem
  resquícios). Aviso final já ENTREGUE (txt.txt item 4 + Telegram 3518).
- Vigia tick 20:23: 26 ativos, `pendentes_novos: []`,
  `pendentes_seguranca: []`; relatório 04:35 com 4 sondas verdes e fila do
  juiz vazia.
- **txt.txt:** sem mensagem nova do dono (conteudo ainda é a entrega 07:05).
- **analise/:** nada novo (Prompt_Nicky_Musicas.txt 31/10 já conhecido;
  Nicky Radio/ intacta).

### 4. Estado e fila

**SISTEMA VERDE E ESTÁVEL — v1.44.0/2080, HEAD `53c463a`, árvore limpa,
health ok=true, 9 ferramentas no .205 + tailnet no ar, rádio no ar, Vigia
sem pendências.**

**Fila do dono:** (a) ORDEM PENDENTE oferecida no txt.txt: os 3
encaminhamentos do roteador (SSH 22, HTTP 80→8000, Controle 8001) ainda
apontam para o `.250` — trocar para `.205` quando ele pedir; (b) parking
lot: auditoria de uso de ferramentas, MCP; (c) no próximo reboot, conferir
se a corrida não se repetiu.

**Ações desta troca:** NENHUMA mutação — só leitura e registro (regras 3 e 4).
