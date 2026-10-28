# Transcrição da sessão — 2026-10-28

## §1 — "leia iniciar" (28/10 ~01:10): reverificação de rotina — sistema
       verde, rádio Nicky no ar, 2 dispositivos novos pendentes no Vigia

**Pedido:** usuário: "leia iniciar" — reverificação de rotina (regra 3).
Checkpoint lido: `session.json` (chave
`nicky_locutor_integrar_implantar_2026_10_27`, updated 27/10 21:10 —
frente ENTREGUE, §5 da transcrição de 27/10) + `RULES.md` +
transcrição de 27/10 §5.

**Estado medido (nada afirmado sem evidência — regra 5):**

- **Git:** árvore **LIMPA** (`status --porcelain` = 0), HEAD `7ccf955`
  == `origin/master` (ls-remote confirmou o mesmo sha).
- **od-core:** active desde 27/10 21:06:45 (pós-entrega Nicky Locutor),
  MainPID 2081285, NRestarts=0. `/health` (X-API-Key) **ok=True, 25
  checks, NENHUM fora**. `/app/version` **1.44.0/2080** intacta (sha
  aeb8566b). Journal das últimas 6h: **0 [ERROR]**.
- **Rádio Nicky viva:** container `azuracast` **Up 5 hours**;
  `GET /listen/nicky/radio.mp3` → **200 audio/mpeg** (255.791 B
  baixados na amostra) — o ciclo automático song_changed → locução
  segue no ar desde a entrega.
- **Resíduo: NENHUM** — nada modificado sem commit desde o registro da
  §5 de 27/10 (diferente das reverificações de 21–26/10).

**Canais do dono:** `txt.txt` = nossa entrega da §5 escrita 27/10
21:10 (mtime 21:11:46) — **NENHUMA mensagem nova dele**. `analise/` =
apenas `Nicky Locutor/` (PENDENTE, aguardando ordem — regra 17) + 6
relatórios do vigia (nossos; últimos 27/10 04:34).

**Vigia da rede (tick recente):** 25 ativos, **2 DISPOSITIVOS PENDENTES
NOVOS** (não mutados — regra 7, aguardando ordem do dono):
- `26:14:7A:43:2E:11` @ 192.168.0.163, desde 27/10 17:14, fabricante
  desconhecido;
- `7A:25:D5:8C:03:EE` @ 192.168.0.233, desde 27/10 20:50, fabricante
  desconhecido.
Os DOIS com MAC localmente-administrado (bit 2 do 1º octeto) = endereço
WiFi privado aleatorizado — mesma classe do iPhone/iPad conhecidos em
26/10: provável aparelho da casa, não intruso. Para conhecê-los:
`OD_LOG_DIR=logs python3 tools/monitor/network_watchdog.py --conhecer
<mac> <nome>` (só inventário local, sem mutação no roteador).

**Timers:** network-watchdog (5 min) e router-monitor (1 min) ativos;
`od-vigia-mensagens` próximo disparo **28/10 04:31** (Persistent).

**Estado:** SISTEMA VERDE E ESTÁVEL — v1.44.0/2080, HEAD `7ccf955`,
árvore limpa, health 25/25, rádio no ar. **Nenhuma mutação nesta
troca** (regra 7). Fila do dono: (a) subir as músicas pelo painel
AzuraCast 8091 (passo a passo no `txt.txt` e em
`/home/alex/azuracast/ACESSO.txt`); (b) destino de
`analise/Nicky Locutor/` (legado intacto); (c) 2 dispositivos pendentes
no Vigia (conhecer ou bloquear); (d) parking lot §5 restante: rota WiFi,
auditoria de uso de ferramentas, MCP.

## §2 — "coloque a radio dentro do funnel" (28/10 ~01:20): o stream da
       rádio Nicky vira caminho público do Funnel + página de áudio no site

**Pedido:** dono (28/10 ~01:20): *"coloque a rádio dentro do funnel"* —
a estação implantada na §5 de 27/10 passa a ser ouvida fora da rede local.

**Diagnóstico antes de agir (regra 5):** Funnel atual = `# Funnel on` na 443
com `/` → 127.0.0.1:8000 e `/ws` → 8001 (mais 8443 tailnet-only com as
ferramentas). O od-core só tem a rota do **webhook** (`POST
/radio/webhook/{token}`) — **nenhum caminho servia o áudio**: o stream vive
no icecast do AzuraCast (`127.0.0.1:8600/radio.mp3`, e também
`8091/listen/nicky/radio.mp3`), ambos só na LAN. Publicar o painel 8091
inteiro no Funnel exporia o admin à internet → **fora de plano**; o pedido
é a rádio, então o alvo é o áudio.

**Sandbox (regra 10) — sem tocar na 443:** `tailscale serve --bg
--https=9443 --set-path=/radio.mp3 http://127.0.0.1:8600/radio.mp3` numa
porta nova, tailnet-only. Medido: `/:9443/radio.mp3` → **200 audio/mpeg**
(stream continua — o `curl --max-time 6` saiu com exit 28 baixando 206 KB) e
`/radio.mp3/radio.mp3` → 404 (o handler casa o caminho exato). Sandbox
removida (`--https=9443 off`) antes do passo real.

**Implantação (estado externo, ordem explícita do dono — regra 7):**
- Snapshot de rollback ANTES: `tailscale serve status --json` →
  `backups/tailscale-serve-20261028-013152-status.json` (1216 B; o
  `get-config` sai `{"version":"0.0.1"}`, o formato útil é o do status).
- `tailscale funnel --bg --yes --https=443 --set-path=/radio.mp3
  http://127.0.0.1:8600/radio.mp3` → status final com **3 handlers** na 443
  (`/`, `/ws`, `/radio.mp3`), 8443 intacto, 9443 fora.
- **`site/radio.html` (NOVO):** página no estilo da casa (nav + od.css +
  footer + od-nav.js), áudio ao vivo com origem decidida no cliente —
  `https://` usa `/radio.mp3` do mesmo host; `http://` (LAN) usa o icecast
  `:8600`, porque fonte https não carrega http (mixed content). 3 cartões:
  estação, locução automática, acesso — **sem credencial de admin no
  público**.
- **`site/od-nav.js`:** `'/site/radio.html': '📻'`.

**Guarda da casa pegou a entrega (1ª rodada do gate):**
`TestIconesDoMenuLateral::test_tabela_cobre_todos_os_menus_do_site` varre os
`nav-panel` de todas as `site/*.html` e exige glifo real para todo href
(avalia o `iconeDe()` de verdade, em node) → **1 failed / 3957 passed**: o
link novo não estava na tabela `ICONES`. Conserto na causa (glifo `📻` na
tabela, `node --check` limpo) — grupo 4/4 verdes.

**Validação (gate 2x, antes e DEPOIS da edição do CHANGELOG — o CHANGELOG é
corpus do RAG):** **3958 passed / 16 skipped / 0 falha · 90,57%** nas duas
rodadas. Nenhum `.py` mudou → pyflakes sem mudança nova e **nenhum restart
necessário** (a página é servida do disco; o Funnel é externo ao od-core).

**Prova viva (medida, não prometida):**
- `GET https://nicky-server.tail1b1f51.ts.net/radio.mp3` → **200
  `audio/mpeg`**, 179–208 KB em 5–6 s, `file` = **MPEG ADTS layer III, 192
  kb/s, 44,1 kHz** — stream vivo saindo de fora do servidor;
- regressões da 443: `/` **200** · `/app/version` **200** · `/site/` **200**
  · `/ws` **426** (upgrade esperado);
- página: local `200 text/html 6104 B` e pelo Funnel **200 6104 B** (mesmos
  bytes), com `btnTocar`/`od-nav.js` no HTML;
- od-core intocado: MainPID 2081285 (o mesmo do boot de 27/10 21:06),
  NRestarts=0, `/health` ok.

**Estado:** **NO AR** — `https://nicky-server.tail1b1f51.ts.net/site/radio.html`
público e o áudio em `/radio.mp3`. Painel AzuraCast segue só na LAN
(8091). Registro: esta seção + `session.json` chave
`radio_no_funnel_2026_10_28`.
