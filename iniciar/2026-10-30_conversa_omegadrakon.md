# 2026-10-30 — conversa OmegaDrakon

> Registro conforme regra 4 do `iniciar/RULES.md`. Contexto em
> `iniciar/session.json` (chave `reverificacao_rotina_2026_10_30`).

## §1 — "leia iniciar" (30/10 ~13:50): sistema verde e estável

**Pedido:** usuário: "leia iniciar" — reverificação de rotina (regra 3).
Checkpoint: `player_radio_painel_2026_10_29` (29/10 16:10, §7 — player da
rádio entregue no painel, deploy verde, commits pushados).

### 1. Sistema — verde (evidência lida, não presumida)

- **Git ARVORE LIMPA** (`git status --porcelain` vazio), HEAD
  `7d10595` == `origin/master`.
- **od-core active** desde 29/10 16:01:10 (o restart verde da §7),
  MainPID **527739**, **NRestarts=0** (~22 h).
- **/health** autenticado `ok=true`, checks todos up (orchestrator,
  llm gemma-local, …). **/app/version 1.44.0/2080** intacta (sha
  `aeb8566b`).
- **Borda:** Funnel `/` **200**, `/radio.mp3` **200 audio/mpeg**;
  `tailscale serve` com os handlers da 443 (`/`, `/ws`, …) + 1883
  intactos.
- **Rádio viva no ar:** journal mostra ciclo normal (auto-update tick,
  síntese TTS concluída 471432 B).

### 2. Journal desde o restart — achado honesto (rede, não código)

5 entradas **[ERROR]** e 1144 [WARN] desde 29/10 16:01 (o registro da
§7 viu "0 warning/0 erro" logo após o restart — o tempo expôs blips):

- **5× `[ERROR] Sink falhou | Telegram API indisponível`** (4× DNS
  "Temporary failure in name resolution", 1× read timeout) — 16:28,
  23:48, 04:36, 05:36, 08:26.
- **1059× `[WARN] Transporte indisponível — aguardando...`** + 8× clima
  wttr.in (DNS) + 7× notícia G1 (DNS) + 7× `Alerta proativo
  key=router:down` (gateway 192.168.0.1 ping falhou) + 37× RSS do G1
  quebrado.
- **Leitura:** é o MESMO padrão do corte do Funnel de 28/10 — o uplink
  é WiFi (`wlx000f0037acf0`), blips de link derrubam DNS/internet por
  minutos e tudo volta sozinho. **Não é defeito de código**: NRestarts=0,
  health verde, Funnel/rádio de volta. Reforça o item "rota WiFi" do
  parking lot §5 como candidato sério.

### 3. Resíduo — NENHUM

Nada modificado sem commit desde o registro da §7 (árvore limpa; o
padrão das sessões mortas de 21-29/10 NÃO se repetiu).

### 4. Canais do dono

- **txt.txt:** sem mensagem nova dele (mtime 29/10 16:06 = a nossa
  entrega da §7).
- **analise/:** sem pasta nova do dono (Nicky Musicas/ e Nicky Radio/
  intactas desde 28/10); só relatórios do Vigia — inclusive o de
  30/10 04:34.

### 5. Vigia — relatório 30/10 04:34

- **4 sondas VERDES** (rota_aparelho_infinitivo, rede_sem_bridge,
  estado_contraditorio, inventario_fora_da_raiz); **fila do juiz VAZIA**
  (os 2 itens de 28/10 saíram e não foram repostos); gate/commit/restart
  não precisaram rodar; `avisado=false` (04:34).
- **Auditoria 24h:** 0 turnos problemáticos no Postgres.
- **Rede (tick 13:46):** `Pendências: 0 dispositivo(s) novo(s), 0
  evento(s) de segurança`; `pendentes_novos: []`.
- **Renomeações observadas:** os 2 dispositivos que o dono batizou de
  "Smartphone" em 29/10 agora têm nomes novos — `26:14:7A:43:2E:11 ->
  Galaxy-A07` e `7A:25:D5:8C:03:EE -> iPhone` (mais um terceiro
  `7A:A7:13:05:6D:3A -> iPhone`). Alguém (provavelmente o próprio dono,
  via `--conhecer`) renomeou depois do registro de ontem — mudança
  benigna, inventário com 22 aparelhos nomeados, pendências zeradas.

### 6. Estado

**SISTEMA VERDE E ESTÁVEL — v1.44.0/2080, HEAD `7d10595`, árvore limpa,
health 25/25, Funnel e rádio no ar, Vigia sem pendências.** Nenhuma
mutação nesta troca (regra 7 intocada).

**Fila do dono:** (a) ouvir a rádio/player (site e painel) e dizer se
ficou bom — o teste que só o olho dele fecha; (b) subir músicas pelo
painel 8091 (HD Mídia pronta); (c) parking lot §5: rota WiFi (agora com
prova nova dos blips), auditoria de uso de ferramentas, MCP.

## §2 — dono responde a fila (30/10 ~14:05): rádio aprovada, música de fora, rota WiFi

**Pedido:** dono: "1. ok. 2. não estou em casa, acho que não tem como
subir musicas. me explique o que quer fazer em 3".

### 1. Rádio aprovada
"1. ok" = o teste que só o olho dele fecha está cumprido (site e
painel).

### 2. Música de fora — TEM como (tailnet 8446)
Ele não precisa estar em casa: o painel AzuraCast está publicado na
tailnet desde 28/10 — `https://nicky-server.tail1b1f51.ts.net:8446`
(tailnet only, atrás do proxy que corrige o Host). Com o app Tailscale
no celular/Notebook conectado à tailnet, ele abre o painel de qualquer
lugar e sobe música pelo Upload. Ressalva honesta: se o aparelho dele
NÃO estiver conectado à tailnet, mesmo de fora não há como — o Funnel
443 só expõe `/`, `/ws` e `/radio.mp3` (decisão de segurança da
§2 de 28/10: não publicar o painel na internet). URL escrita no
`txt.txt` (regra 14).

### 3. Rota WiFi — o que eu quero fazer (explicação pedida)
**Problema medido (router_monitor.log, 13 dias, 18655 amostras de 1
min):** o servidor saí para a internet por **WiFi USB**
(`wlx000f0037acf0`), e o link cai com frequência: **300 minutos down**
no total (~1-3%/dia; 29/10: 46 min = 3%; **30/10: 88 min = 11%**, com
janela longa 04:34-06:59). Cada blip = DNS fora (Telegram sink, clima,
notícia G1), Funnel cai da internet e a rádio fica inacessível fora de
casa — o mesmo padrão do "funnel parou" de 28/10.

**O que eu quero fazer (nada disto agora, ele fora = ordem pendente):**
- **(a) Cabo Ethernet** — a placa `enp2s0` já existe e está só
  esperando um cabo até o roteador. Solução definitiva, custo zero em
  código. Precisa dele em casa (físico).
- **(b) Failover com o 2º adapter USB** (`wlx00e2b0101555`, hoje
  parado) — rede reserva que assume quando a principal cai. Arrisca
  derrubar a rede do servidor se errar a configuração => só com ele em
  casa ou ordem explícita.
- **(c) Antena/posição** — medir sinal e reposicionar o adapter.
- **(d) Só monitorar** — já existe (router-monitor 1 min + alertas
  proativos).

**Recomendação:** (a) quando ele voltar para casa — 10 minutos, resolve
a causa raiz.

## §3 — "deu 400 bad request" na 8446 (30/10 ~14:25): causa encontrada

**Pedido:** dono: "deu 400 bad request. certo, chegando em casa troco"
(2 = falha no painel de fora; 3 = aprovou o plano (a) — cabo Ethernet
quando voltar para casa).

### Reprodução e causa (medida, não presumida)
- Serviços saudáveis: `od-azura-proxy` active desde 28/10 12:40,
  MainPID 3086957; backend 8091 -> 302; proxy 8466 -> 302.
- `https://nicky-server.tail1b1f51.ts.net:8446/` -> **302** e
  `/login` -> **200** (funciona).
- **`http://...:8446/` -> 400 com corpo "Client sent an HTTP request
  to an HTTPS server."** = EXATAMENTE o erro que ele viu.
- **Causa:** o navegador foi em `http://` (sem o `https://`). A 8446 do
  tailscale serve só aceita TLS; a requisição em claro é recusada com
  400. Provável origem: digitou a URL no celular sem o esquema e o
  navegador pesquisou/usou http.
- `https://192.168.0.250:8446/` -> 000 (a 8446 NAO existe na LAN — é
  tailnet only, comportamento esperado e desejado).

### Condições para funcionar (as 2, nessa ordem)
1. App **Tailscale ligado e conectado** à tailnet no aparelho.
2. URL com **`https://`** explícito:
   `https://nicky-server.tail1b1f51.ts.net:8446` -> `/login` 200.

### Melhoria proposta (PENDENTE de ordem — mutação na tailnet, regra 7)
Fazer o tailscale serve redirecionar `http://...:8446` -> `https://`
(evitando o 400 para quem esquecer o esquema). Não implementado: é
mutação fora da LAN (tailnet), exige ordem explícita.

### 3. Cabo Ethernet
Dono: "chegando em casa troco" = plano (a) APROVADO, aguardando ele em
casa. Checklist lá na frente: backup de config, troca para enp2s0,
verificação de rota/Funnel/rádio, rollback se falhar.

## §4 — dono corrige o fluxo de música (30/10 ~14:40): não é upload cru

**Pedido:** dono: "subir musica não é bem assim que deve funcionar.
temos que verificar se a musica já existe, qual a qualidade da musica,
precisa normalizar e enrriquecer os dados, colocar na pasta correta e
mais coisas que não lembro agora". Antes dele: "pelo que entendi é pra
subir a musica diretamente dentro do azura, é isso mesmo?" -> **NÃO**
(upload cru nunca foi o caminho; o AzuraCast importa o `acervo/`
sozinho, cron de 1 min).

### Levantamento (regra 16 — Legado como referência, lido antes de opinar)
`/home/alex/dados/musicas/musica.py` **v1.6, 718 linhas** + `doc/README.md`:

| Pedido do dono | Existe na v1.6? | Evidência |
|---|---|---|
| Normalizar | **SIM** | `converter_local()` — ffmpeg `loudnorm` EBU R128 (alvo configurável; ele mesmo discute -16/-14/-18 LUFS) |
| Enriquecer dados | **SIM** | `enriquecer_pendentes_em_lotes()` — Gemini: artista, título, ano, pronúncia, curiosidade; `tags_validas()` trava TPE1+TIT2+TIT3 antes de mover |
| Colocar na pasta correta | **SIM (com defeito)** | `organizar_acervo()` + `classificar_para_azuracast()` — gênero em subpasta; **defeito: `Mpb` (3 arqs) x `MPB` (0) duplicados por caixa** (`.title()`), + `Outros` e `Jawed Karim` (teste) no acervo |
| Verificar se já existe | **NÃO** | só `gerar_nome_unico()` evita colisão de NOME de arquivo — a MESMA música com nome diferente entra 2x |
| Qualidade | **NÃO** | converte tudo p/ `MP3_BITRATE=192k` sem medir a FONTE (fonte 64k vira "192k" de fachada) |

### Descobertas
- **`analise/Nicky Musicas/Prompt.txt`** = pedido do próprio dono da
  **v1.7: exportar .m3u** (uma playlist por gênero do acervo + "Mix
  Radio" balanceada 40/30/20/10, limite de faixas, sem Gemini nessa
  etapa) — já depositado na caixa de entrada (regra 17), não executado.
- **`dados/musicas/000/` = 254 mp3 brutos** (192 kbps, nomes de vídeo
  YouTube) = backlog de entrada nunca processado.
- **acervo/ = 33 mp3** (os que já tocam na estação), 10 subpastas.
- `analise/Nicky Radio/` = 2613 arquivos (nicky-radio v0.1..v0.7, outro
  projeto — não mexer).
- `run.sh` tem a chave Gemini embutida (Legado — nunca publicar).

### 400 da 8446 — estado do diagnóstico
- desktop-4icaj6f (Edge) **ACTIVE na tailnet** (100.77.242.82, direct).
- Reproduzido: `https://...:8446/login` -> **200** com UA do Edge e
  HTTP/2; `http://...:8446` -> 400 **texto puro sem "nginx"** (tailscale).
- A página dele ("400 Bad Request" + rodapé **nginx**) casa com o
  **nginx do AzuraCast** (reproduzido: 8445 com HTTP puro -> 400 "The
  plain HTTP request was sent to HTTPS port" + `<hr>nginx`). Quem
  devolve nginx NA CADEIA 8446 é o backend do azura_proxy — pedido
  específico do Edge chegou lá e o nginx recusou, ou ele tocou outra
  porta. **Pendente: teste ao vivo com eu lendo o log em tempo real**
  (azura_proxy não loga pedidos; access.log do AzuraCast está vazio).

### Decisão
NADA codado nesta troca — o dono está desenhando o fluxo. Próximo
passo: apresentar o mapeamento + plano de pipeline e perguntar as
escolhas de design (aprovação, regra de qualidade, dedup).

## §5 — escolhas de design do fluxo de música (30/10 ~15:00)

**Pedido:** dono respondeu as 3 perguntas (ask_user):
1. **Dedup: "Chave forte + revisão"** — chave = artista+título
   normalizados. Bate exato → descarta e loga. Bate 'parecido' (mesmo
   artista, título com variação) → pasta `revisar/` para ele olhar.
   Nada é apagado sozinho.
2. **Qualidade: "Recusar abaixo de 192k"** — bitrate real <192 kbps ou
   sample rate <44,1 kHz → pasta `reprovadas/` com o motivo no log.
3. **Aprovação: "Publicação automática"** — passou nas regras (dedup +
   qualidade + tags completas) já entra no acervo e toca em ~1 min
   (relatório continua gerado, mas sem bloquear).

**Observação honesta do combo:** dedup exato e qualidade são
bloqueios AUTOMÁTICOS; só o "parecido" vai para revisão — coere com
aprovação automática.

**Sistema na virada do dia (31/10 ~00:00, regra 3):** od-core active,
MainPID 527739, NRestarts=0, /health ok, árvore limpa (HEAD 64c070e),
Vigia 31/10 04:31 4 sondas verdes, fila vazia, txt.txt sem mensagem
nova.

**Próximo passo:** v1.7 do pipeline = dedup (chave forte + revisar) +
portão de qualidade (<192k reprovado) + fix Mpb/MPB + export .m3u do
Prompt.txt. Sandbox antes do real (regra 10).

## §6 — ordem do dono: RESET LIMPO do acervo (31/10 ~09:30)

**Pedido:** dono: "apague as pastas vazias, coloque todas as musicas na
pasta 000 e reinicie a classificação de forma limpa. não tem problema a
rádio sair do ar, o importante é ela começar de forma limpa e certa.
da menos trabalho agora que no futuro". Item 1 (lista de etapas extras)
= "sim, pode listar".

### Execução (com backup, sem perda)
1. **Backup**: `backups/acervo-20261031-antes-reset.tar.gz` (214 MB,
   33 mp3 + estrutura) em `/home/alex/dados/musicas/backups/`.
2. **Colisão checada antes**: `comm` entre nomes de `000/` e do acervo
   = 0 colisões (mv -n ainda assim usado).
3. **Achatamento**: 33 mp3 do acervo → `000/` (agora **287 arquivos**,
   254 brutas + 33 já enriquecidas). Acervo: **0 arquivos, 0 subpastas**
   (`Mpb`, `MPB`, `Gospel`, `Rock`, `Sertanejo`, `Pop`, `Internacional`,
   `Eletrônica`, `Outros` — incl. `Jawed Karim` do teste — todas
   apagadas; pasta raiz `acervo/` mantida = alvo do mount do AzuraCast).
4. **AzuraCast sincronizado** (`azuracast:media:sync nicky`): storage
   com **2 arquivos** (só `locucoes/`: anuncio_musica + vinheta_nicky) =
   playlist `default` vazia, sem lixo de referência.

### Estado da rádio (honesto)
- Stream **200 audio/mpeg** vivo. Tocava ainda "Algo Novo" (fd aberto
  antes do mv — termina e some sozinho); próxima = anuncio música.
- Rádio segue NO AR em modo **só vinhetas/locuções** (estado conhecido
  de antes de 27/10, quando não havia música). Sem música até a v1.7
  reclassificar o `000/`.

### Próximo
v1.7 (dedup chave forte+revisar · qualidade <192k reprovadas · fix
caixa Mpb/MPB · .m3u do Prompt.txt) em sandbox, dry-run contra os 287,
e aí a reclassificação limpa que ele ordenou.

## §7 — escopo fechado da v1.7 (31/10 ~10:00)

**Pedido:** dono respondeu as 3 perguntas da lista de extras:
1. **CLI completo**: `urls` por argumento, `--dry-run` (simula sem
   mover/baixar) e `--clean` (limpa `temp/` e `logs/` antes).
2. **Gênero via Gemini**: ENTRA — enrichment passa a responder também o
   gênero (lista fixa: Gospel, Sertanejo, Rock, Pop, MPB, Internacional,
   Eletrônica, Outros), gravado em TCON; classificação usa TCON quando
   existir, com fallback nas palavras-chave de hoje. Resolve o "Outros"
   documentado no README.
3. **Itens mortos**: remover o stub `sugerir_playlist_inteligente()`
   (README já diz "não mantida"); manter `sugerir_renomear_temp()`.

**Escopo v1.7 fechado (com as escolhas da §5):**
- dedup: chave forte artista+título normalizados; exato → descarta+loga;
  parecido (mesmo artista + título próximo, difflib) → `revisar/`;
  nada apagado sozinho.
- qualidade: ffprobe na FONTE; <192 kbps ou <44,1 kHz → `reprovadas/`
  com motivo no log (limiar via env MP3_BITRATE_MIN p/ ajuste fino).
- fix caixa: pastas do acervo casadas case-insensitive (Mpb/MPB).
- export `.m3u` (Prompt.txt): por gênero + Mix Radio 40/30/20/10,
  limite de faixas (padrão 50, `--max-faixas`), caminhos relativos,
  sem Gemini nessa etapa.
- registro: BASE_DIR configurável via env MP3_BASE_DIR (para sandbox
  apontar pro acervo real sem copiar 287 arquivos).
- dry-run NÃO chama Gemini nem move nada (verifica tags/ffprobe/dedup e
  relata).

**Ressalva honesta p/ dono (a entregar):** fontes do YouTube costumam
ser <192 kbps (m4a ~129k) — o portão de qualidade literal reprovaria a
maioria dos downloads novos; os 287 de 000/ (192k/48k) passam todos.
Limiar configurável; decisão de ajuste fica com ele.

## §8 — v1.7 construída, validada em sandbox e EXECUÇÃO REAL iniciada (31/10 ~10:20)

### Construção (sandbox `.od_sandbox/musica-v17/`, regra 10)
`musica.py` v1.7 (1.146 linhas) escrita a partir da v1.6 lida por inteiro.
Escopo conforme §5+§7: dedup chave forte (exato → `revisar/duplicadas/`,
parecido → `revisar/`, **nada apagado**), portão de qualidade ffprobe na
fonte (<192k ou <44,1kHz → `reprovadas/` + motivo; limiar `MP3_BITRATE_MIN`),
loudnorm medido em TODOS os mp3 (v1.6 não normalizava downloads — achado),
gênero via Gemini em TCON (lista fixa de 8, validado; `validar_genero`),
classificação única por TCON com fallback palavras-chave e pastas
case-insensitive (fix Mpb/MPB), `.m3u` por gênero + Mix Radio 40/30/20/10
(`--max-faixas`, seed fixa, caminhos relativos), CLI completo (urls,
`--dry-run`, `--clean`, `--max-faixas`, `--sem-m3u`), `MP3_BASE_DIR` para
sandbox, entrada `000/` drenada no início (`drenar_entrada()`), removidos:
stub playlist inteligente, `organizar_acervo()`, PROMPT_ORGANIZACAO,
PROMPT_GENERO_AZURACAST (briga de classificação dupla — achado). Extras:
tags substituídas em vez de acumular frames; renomeação em lotes de 10.

### Validação (antes do real)
- 22 testes unitários (`/tmp/opencode/testa_v17.py`): normalização de chave,
  validar_genero, pasta case-insensitive, dedup exato/parecido/novo, extração
  de nomes YouTube ( ` - `, `｜`, `_` sanitizado), ffprobe 192k passa / 64k
  reprova — **todos verdes**.
- **Dry-run contra os 287 reais**: 287 reconhecidos, 0 reprovados (todos
  192k+), 0 duplicatas (chave única confirmada por teste externo: 287 chaves
  únicas; os 18 "parecidos" aparentes eram músicas DIFERENTES do mesmo artista
  com sufixo igual "[Clipe Oficial]" — falso positivo corrigido com o núcleo
  do título), 287 pendentes de Gemini (33 precisam só do gênero). Dry-run
  prova-read-only: md5 do listing 000/+acervo idêntico antes/depois.
- Defeitos achados e corrigidos durante a validação: (1) dry-run não via a
  entrada `000/` (pipeline só olhava temp/); (2) nomes `Artista ｜ Título`
  viravam artista "Desconhecido"; (3) similaridade inflada por sufixos;
  (4) `oficial` faltando no regex de qualificadores; (5) sequência
  sanitização→extração: `｜` virava `_` antes do leitor ver (corrigido
  tratando `_` espaçado). Um kill de processo matou minha própria shell
  (pkill casou na linha de comando) — lição, sem dano.

### Instalação e execução real
- v1.6 salva em `backups/musica-v16-20261031.py`; v1.7 instalada em
  `/home/alex/dados/musicas/musica.py` (md5 confere com o sandbox);
  `doc/README.md` reescrito para a v1.7.
- Execução real lançada 10:20:48 (pid 2973898) com a chave do `run.sh`
  exportada sem exibir. 287 drenados de `000/` → `temp/` (000 vazio por
  design). Etapas: sanitização → renomear (Gemini lotes) → dedup →
  qualidade → tags → loudnorm (~1h) → enrich Gemini (~15 min) → acervo →
  classificação → .m3u. Estimativa total ~1,5–2h. Acompanhar e reportar.

## §9 — dono: bitrate mínimo para 128 + DNS NXDOMAIN (31/10 ~11:30)

**Pedido 1:** dono: "ajuste o bitrate minimo para 128, assim o youtube
funciona". **EXECUTADO**: `MP3_BITRATE_MIN` default 128 em
`/home/alex/dados/musicas/musica.py` = sandbox (md5 idêntico), README
atualizado; teste: limiar ativo 128, 64k continua reprovado. Vale p/
downloads futuros; a execução em curso já passou pelo portão (287/192k).

**Pedido 2 (pendente de resposta):** dono: "não consigo acessar a pagina.
dns_probe_finished_nxdomain". **Evidências coletadas:**
- NXDOMAIN **autoritativo** (zone ts.net via ns1.dnsimple.com, DoH
  Status 3) para `nicky-server.tail1b1f51.ts.net` E para
  `od.sesite.site`; zona `sesite.site` **nem existe** (NS → NXDOMAIN) —
  se foi essa a URL, o domínio não existe em lugar nenhum.
- Borda pública do Funnel (IPs 209.177.145.97/192 de 30/10) **mortos**
  (curl 000/erro TLS) — o caminho público sumiu, não é só DNS.
- Config local do Funnel **íntegra** (`tailscale funnel status`: on,
  /, /ws, /radio.mp3) — o control plane parou de publicar o registro.
- `desktop-4icaj6f` **OFFLINE da tailnet há 20h** (Tailscale dele
  parado) → sem MagicDNS no dele também.
- od-core faz bind em 0.0.0.0:8000 (confirmado) — **IP literal
  `http://100.77.67.53:8000` funciona sem DNS** assim que o Tailscale
  dele voltar (health respondeu pela tailnet IP).
- /health "ok": false visto sem chave = só auth (com X-API-Key segue
  ok: true) — sem problema de sistema.
- logs tailscaled: "major link change" 04:05/04:06 da madrugada
  (rebind) — possível marco da queda do registro público.
- Repo sem nenhuma referência a sesite.site.

**Plano proposto (aguardando aval):** (A) dono liga o Tailscale no
desktop → MagicDNS resolve o nome na hora, mesmo com DNS público morto;
fallback IP literal. (B) reiniciar tailscaled no servidor (~5s, sem
clientes no funnel agora) para o control plane republicar o registro
público do Funnel; se não voltar, é caso de console admin do Tailscale.
