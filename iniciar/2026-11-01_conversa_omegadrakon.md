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
