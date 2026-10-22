# OMEGA DRAKON — CHANGELOG

> **Finalidade:** registro das mudanças por versão, conforme item 4 da
> Definition of Done (`docs/REGRAS_DE_TRABALHO.md` §2) — toda capacidade
> entregue entra aqui com data, contagem de testes e fase/versão.
> **Regra:** a versão mais recente fica no topo.
> **Assinatura:** `OD // CORE`

> **Nota histórica (2026-09-12):** este arquivo foi criado em 2026-09-12 na
> auditoria de alinhamento de versão — até então o projeto não tinha
> `docs/CHANGELOG.md` e o histórico da série 0.x está em
> `docs/README_VERSAO.md` (§0.1.0 → §0.28.4). A partir daqui, toda entrega
> passa a registrar entrada neste CHANGELOG **além** do README de Versão.

## [1.44.0] — CÂMERA QR: O COMPRADOR REGISTRA A PEÇA LENDO O CARTÃO 🜂 (2026-10-20)

**Resumo:** a **v2 da Etapa 4 do Registro Mestre** — a única sobra que o TODO registrava ("*sobra só a v2: câmera de QR dentro do app*") e ordem direta do dono (*"faça o camera qr"*, 20/10). Na v1 o comprador lia o QR do cartão com a câmera do celular (abria a página pública), copiava o código `POSSE-…` à mão e colava no app; agora **a aba Verificar do app tem câmera própria**: aponta, lê e o código cai sozinho pronto para confirmar — zero digitação. O contrato do QR não mudou (URL `{base}/site/verificacao.html?posse=…`, servida em qualquer base — LAN/tailnet/funnel/DDNS, e é isto que a leitura respeita: **só o parâmetro, nunca o host**).

| Peça | Entrega |
|---|---|
| **`app/lib/services/od_qr.dart` (NOVO)** | Parser PURO da leitura: `?posse=` → forma canônica do cartão (`POSSE-XXXX-XXXX-XXXX-XXXX`, 16 hex em 4 grupos — espelho de `core/registry.py`), `?codigo=` → consulta pública direta, texto cru `POSSE-…` também serve, **QR alheio → null** (a tela ignora e segue lendo). Puro de propósito: testável em VM sem câmera. |
| **`app/lib/screens/registry_screen.dart`** | Botão **📷** no card "Registrar minha peça" (com conta — registro segue exigindo cadastro, decisão da Etapa 4) → leitor em tela cheia (`mobile_scanner ^7.4.2`, retículo de mira, trava anti-rafale) → QR de posse preenche o formulário (comprador confere e toca em **Registrar** — "quem tem o código é o dono" continua explícito); `?codigo=` dispara a consulta da peça. **Permissão negada / aparelho sem câmera → aviso honesto no leitor, a digitação do código nunca sai do ar.** |
| **`app/android/.../AndroidManifest.xml`** | Permissão `CAMERA` + `uses-feature` com `required=false` — aparelho sem câmera continua **instalando**, só perde o leitor. |
| **Site** | Cartão `?posse=` da verificação pública agora ensina "*aponte a câmera para este QR (ou cole o código)*"; landing (`v1.44.0 · versionCode 2080`) e linha do tempo do histórico atualizados pela régua da política de versão. |
| **Guardas** | `app/test/registry_qr_test.dart` (+8): 6 do parser (URL cheia, sem hífen/caixa baixa → canônico, `?codigo=`, cru, QR alheio, vazio) + 2 da tela (📷 com conta no card certo; **sem conta = sem câmera** + instrução de login). `flutter analyze` **0 issues** · `flutter test` **206 passed / 2 skipped** (era 198). Suíte Python regida pela política: bump nas **7 fontes** (`OD_VERSION` `.env` + fallback congelado, pubspec `1.44.0+2080`, `_APP_VERSION_CODE = 2080`, site ×2, CHANGELOG, ordem das seções). |

**Validação:** gate oficial **3546 passed / 16 skipped / 0 falha · 90,69%** (nada do servidor mudou além do versionCode) · **APK pelo `build_apk.sh` canônico** (completo + split-per-abi, `FORCE_VERSION_CODE` — achado da 1.43.0) publicado em `site/` · restart verde anunciando **1.44.0/2080** com sha256 do binário novo (o contrato da auto-atualização: `test_version_policy.py` amarrando as 7 fontes). **Nota honesta:** a câmera em si (permissão, mira, leitura) foi provada em **analyzer + parser puro + widget** — o teste de mira real é no aparelho do dono: abrir a aba Verificar, tocar 📷 e apontar para o cartão.

**Nota de calibração (achado do próprio gate):** o gate de calibração
do RAG (`TestCalibracaoCorpusReal`) falhou nesta entrega e o diagnóstico
é registro-valioso: a §1.44.0 das notas repetiu um **substantivo de UI
genérico** 10× em três arquivos do corpus (o corpus do RAG é a própria
memória — `docs/ + knowledge/ + iniciar/*.md`) e virou **falso-amigo**
da irrelevante da fronteira (a pergunta sobre **clima** casava com o
texto da câmera: comb **0.4215 > 0.4032** do relevante mais fraco;
grid medido com **0 células válidas**). Stopwordar a palavra de tempo
foi testado e **medido como pior** (0.4530 — sem o termo diluidor o
embedding fica mais parecido com os chunks do jargão novo). Correção:
**rewording do texto novo** ("no <UI>" → "no formulário"/"a
digitação"), memória alheia intocada, **piso intocado — medido, não
afrouxado**: comb de volta a **0.3940**, grid refeito com **900
células válidas**, piso vigente dentro da região. Medição gravada no
comentário de `memory/rag.py` ao lado das constantes · `test_rag.py`
**92/92**. **Lição:** o corpus é a memória da casa — nota de entrega
genérica demais vira falso-amigo do floor, e até a NOTA do incidente
entra no corpus (esta aqui já foi reescrita uma vez por citar os
termos ao vivo).

### Reboot do roteador tirado da janela dos backups (sem bump — 21/10)

Dono (*"o problema do roteador vamos resolver agora… ele está configurado
para reiniciar às 3:00, justamente no horário dos backups"*). Apuração na
fonte viva: no histórico do `router_monitor`, o down de **21/10 03:00:20
latency=5 ms** foi o **único instantâneo** de todo o log (host unreachable
na hora = assinatura de reboot) — os outros 750 downs são timeout de 2 s
(perda de pacote do adaptador WiFi `wlx…` do servidor, espalhada o dia;
isso **não** é o roteador caindo e não some com esta mudança). Leitura da
UI real (chromium headless + senha entregue no `txt.txt`): Archer C6,
**Programação de Reinicialização ligada, 03:00, Todos os dias** — a
colisão confirmada. Aplicado pelo dono (*"semanal, domingo 05:00"*):
**Todas as semanas · Domingo · 05:00** via combos reais da interface +
**GRAVAR**, prova por reabertura da página (antes `03:00/Todos os dias` →
depois `05:00/Todas as semanas/Domingo`, ativo). Senha `ROUTER_ADMIN_PASSWORD`
no `.env` (gitignorado) + cofre — espelho **19/19 gravado+conferiu**
(`vault_env_mirror.py` +1 na allowlist). Próximo reboot: **domingo
25/10 05:00** — longe do backup (03:00), do off-site (03:40) e das
capturas (domingo 04:00). Gate **3546/0 · 90,69%** (só allowlist mudou;
sem restart — nenhuma peça em runtime lê a chave).

**Continuação (mesma tarde): revisão de falhas e portas, ordem do dono
(*"verifique possíveis falhas e revise todas as portas"*).** Leitura
integral da UI real + cruzamento com o servidor. **WAN = CGNAT**
(100.64.175.223, RFC 6598) ⇒ **sem IP público**: as regras de port
forward não alcançam a internet hoje (acesso externo = Tailscale
funnel). **Achado crítico:** Atualização Automática de firmware **ligada
na janela 03:00–05:00** — mesma janela do backup; o log mostra 3
downloads de firmware (18/08), ou seja, o Archer podia se reiniciar
sozinho no meio do backup de novo. **Aplicado com prova (escolha do
dono: "mover janela + limpar regras mortas"):** auto-update →
**06:00–08:00** (switch **continua ligado** — updates preservados,
janela agora longe de backup/off-site/capturas/reboot) · regras mortas
**"Teste" (82→443)** e **"HTTPS" (443→443, órfã — nada escuta 443
local)** **apagadas**; sobraram as 3 vivas `[SSH 22→22, HTTP 80→8000,
Controle 8001→8001]` → 192.168.0.250 (o servidor, confirmado). Prova
final por releitura do zero nas 3 telas (`verificacao_final.png`).
Verde medido: SPI Firewall on · ping WAN off · DMZ off · QoS off ·
Controlo Parental off · telemetria TP-Link off · WPS off · convidados
off · rede IoT própria **com isolamento on** · DHCP com reserva do
servidor · sinal WiFi do servidor **-51 dBm** (pings perdidos espalhados
não são distância — diagnóstico aparte, adaptador USB). Limites
honestos: escanear de fora impossível sob CGNAT; UPnP mantido (Tailscale
precisa para NAT traversal). Sem restart (nada em runtime mudou).

**Continuação (mesma tarde): VIGIA DA REDE — inventário + alarme de
intrusão (sem bump, ordem do dono: "alerta primeiro").** Pergunta do dono:
*"o sistema consegue saber todos os dispositivos da rede e avisar se
alguém tentou invadir e me proteger?"* — resposta medida na fonte: o
Archer expõe a lista completa de clientes (nome/MAC/IP/sinal/tráfego) e o
Registo de Eventos; sob CGNAT o único vetor real é quem entra pela WiFi.
**Entrega** (mesmo contrato do `router_monitor`: monitor só registra
JSON-lines, a ponte para o Telegram é a sonda `_check_network` nova no
notifier, com anti-spam por cooldown): `tools/monitor/network_watchdog.py`
com **duas camadas** — rápida (varredura ARP a cada 5 min via
`network-watchdog.timer`, diff contra inventário, MAC novo vira evento
`dispositivo_novo` e fica **pendente** até o dono resolver, lembrete a
cada cooldown) e rica (a cada 3º ciclo, chromium headless em venv
durável `/home/alex/od-vigia-venv` — **fora do `/tmp`**, que morre no
reboot — lê a UI real do roteador: enriquece nomes/sinais e classifica
eventos de segurança do log, mais `Failed password`/`Invalid user` do
journal do sshd). Modos de operador: `--seed`, `--conhecer MAC [nome]`,
`--ack-seguranca`, `--bloquear MAC` (lista de negação pela UI, sob ordem
direta — **o vigia não bloqueia sozinho**, escolha explícita do dono) e
`--report`. **Provas:** seed com a rede real = **20 dispositivos
catalogados com nome+IP+fabricante** (Echos, lâmpadas Espressif, celulares
(máscara aleatória = sem OUI), câmera Shenzhen Bilian, o próprio
servidor); camada rica ao vivo = **19 clientes + 60 entradas de log**
(filtro do menu lateral, que usa as mesmas `tr.grid-content-tr` da
grade); gate **3592 passed / 16 skipped** (+46 testes novos: parser com
dados reais do dia, ciclo em sandbox hermético com rede injetável, sonda
em tmp); od-core reiniciado com health **25/25**. Achados do dia já
reportados: 2 MACs desconhecidos (Espressif `AC:A7:04…` e aleatório
`0A:31:09…`) e 1 **Tuya Smart bloqueado** na lista de negação do
roteador. Limites honestos: detecta e alerta; bloqueio sob ordem; nada
vindo de fora (CGNAT) — e o elo mais fraco restante é a **senha de WiFi
"omegadrakon"** (palavra de dicionário; rotação é operação à parte com
custo em todos os aparelhos).

**Continuação (mesma noite): TODO MIGRADO PARA O FLATNOTES — o caderno
virou o canal (sem bump, ordem do dono: "faça o b, se existe ferramenta
não tem porque não usar; arquivo solto só suja o sistema").** Contexto:
o dono apontou duas coisas — várias ferramentas subaproveitadas, e que o
`TODO.md` solto deveria viver **dentro do FlatNotes** (o caderno markdown
da casa, v1.40.0 — o sistema já anota/busca por ação). Opção escolhida:
**(b) tudo no FlatNotes**. **Apurado antes de mexer:** nenhum
código/teste/painel lia o `TODO.md` (grep no repo inteiro — só
transcrições históricas citam); o FlatNotes estava **preso em
`127.0.0.1:8200`** (o dono nem conseguia abrir). **Migrado com prova:**
9 notas criadas pelo cliente real (`FlatNotesClient.anota` — §0 regras +
linhas vermelhas, §1 stack, §1b decisão final, §2 pendências, §3
melhoramentos, §4 dívida, §5 parking lot, §6 DoD, §7 fila zerada) →
**10 notas no caderno** (a marca-mãe da 1.40.0 sobrevive), conteúdo
indexado pela busca (`inventario` → 3 notas). **Bind duplo do caderno**
(`127.0.0.1:8200` + `100.77.67.53:8200`, mesmo padrão da Caixa e do
Calibre; `FLATNOTES_AUTH_TYPE=none` só existe **dentro** da tailnet —
aparelhos do dono; nunca no Funnel) com **HTTP 200 nos dois caminhos**
após recreate do container (volume próprio, notas intactas). **`TODO.md`
removido do repo** (histórico git preserva). Regra do dia reforçada no
lugar novo: ideias agora nascem como item na nota **"TODO 5 — Parking
lot"**. Nuance registrado: a busca do FlatNotes é por **palavra simples**
(termo com sublinhado não tokeniza). Item §5 "parking lot dentro do
FlatNotes" **FECHADO** (esta entrega); seguem abertos no caderno:
`network_hosts` com nomes do Vigia, rotação da senha de WiFi,
diagnóstico dos pings e auditoria de ferramentas subaproveitadas.

**Continuação (mesma noite): ACESSOS — 9 FERRAMENTAS NO LAN, CADERNO
COM SENHA, MQTT E HA EXTERNOS (sem bump, ordem do dono: "quero ter
acesso a todas as ferramentas sem tailscale" + "HA e MQTT possuem app
próprio, só preciso de uma url externa").** **Casa sem Tailscale:**
compose ganhou bind `192.168.0.250` em TODAS as 9 ferramentas (bind
triplo nas que já tinham tailnet) — **prova final 9/9** (kiwix 200,
cyberchef 200, it-tools 200, caderno 200, stirling 200, caixa 200,
livros 302=login, homebox 200, cofre 200) + HA 200 (0.0.0.0 já era).
**Caderno com senha** ("Todas as 9 + senha no Caderno"):
`FLATNOTES_AUTH_TYPE=password` + usuário/senha/SECRET_KEY no `.env`
(secret key exigida pelo v5.5.5 com auth — crash loop provado e
resolvido); **`FlatNotesClient` ganhou login automático**: POST
`/api/token` **JSON** → bearer (`Authorization:`; form-data dá 422 —
contrato apurado ao vivo via OpenAPI, não chutado), renovação em 401
com UMA tentativa, mensagem de erro honesta que **nunca ecoa a senha**;
anônimo continua byte a byte o contrato antigo. +4 testes fiéis =
**44 no módulo**; action ao vivo `flatnotes_status` → `auth_type:
password, notas: 10, ok` (o sistema loga sozinho). Senha espelhada no
cofre: item **"FlatNotes — caderno"** (padrão da casa; nunca no git nem
em canal rastreável). **Externo:** HA já escutava em 0.0.0.0 (URL
`http://100.77.67.53:8123` pela tailnet, provada 200 — nada a mudar);
**Mosquitto externo via `tailscale serve --bg --tcp=1883
tcp://127.0.0.1:1883`** (sintaxe oficial `--tcp=porta` — as tentativas
com `tcp://:1883` falharam e o doc resolveu; **sem sudo**, serve
sobrevive a reboot, Funnel NÃO carrega TCP por ser HTTP-only):
**publicação real com credenciais provada pela tailnet**
(`od/prova/externa2`). Aviso honesto registrado: expor LAN = quem tem a
senha do WiFi alcança as ferramentas sem login (Kiwix/CyberChef/IT
Tools/Stirling são genéricas, sem dado pessoal; o Caderno ganhou senha
justamente por isso) — Vigia vigia aparelho novo, rotação da senha de
WiFi segue no TODO 5. Pendente de decisão do dono: **"puxar para dentro
do Site"** (fase 1 proposta: Caderno/CyberChef/IT Tools + Caixa
`--baseurl` + Cofre via domínio; Calibre/Kiwix/Stirling/Homebox não
suportam subcaminho e ficam casa+celular).

**Continuação (mesma noite): PORTÁRIO `/f/<ferramenta>` — 5 FERRAMENTAS
ATRÁS DO LOGIN DO SITE (fase 1 aprovada: "sim fase 1 com as 5"; sem
bump).** O Site virou portaria: `od-core` ganhou rotas
`GET/POST/PUT/DELETE /f/(caderno|cyberchef|itools|caixa|cofre)/*` com
gate PRÓPRIO — a rota é `AUTH_EXEMPT` porque navegador não manda header;
dentro do handler o **cookie `od_sessao` (HttpOnly, SameSite=Lax)** — o
MESMO token de sessão que `/auth/login` já emitia (logout derruba os
dois) — ou `Bearer`/`X-API-Key` abrem só para **papel admin** (`_role()`:
conta do dono; o registro é aberto, então jamais vira passagem livre:
conta comum logada = **403**, sem credencial = **302 →
`/auth/login`**). Proxy em `http.client` de propósito (não segue redirect
sozinho): strip do prefixo na ida — Cofre é a exceção, vive DENTRO do
prefixo via `DOMAIN` com path (`FERRAMENTAS_MANTEN_PREFIXO`) —,
**`Location` do backend reescrito** de volta para o portário, hop-by-hop
higienizado, corpo em blocos de 64 KB (download da Caixa não estoura
RAM), cookie do backend repassado ao navegador, e **`101` vira relé cru
de WebSocket** (canal de notificações do Cofre). Caixa:
`FILEBROWSER_BASEURL=/f/caixa` — precedência **settings.json > db > env**
apurada ao vivo (env sozinho não bastou: um `baseURL ""` explícito no
settings vencia banco e ambiente); settings versionado no repo
(`docker/filebrowser-settings.json`) e montado como fonte única, senão
recriação do container apagava a correção. Cofre: `DOMAIN=
https://nicky-server.tail1b1f51.ts.net/f/cofre` (web vault nativo no
path; **o link direto `:8443` do portal legado morreu para o cofre** —
o app Bitwarden deve apontar a URL nova, que funciona em qualquer rede).
**Provas:** **14/14** testes novos (`tests/test_portal_ferramentas.py`:
portão sem credencial/conta comum/chave; strip+query+corpo; redirect
prefixado; cookie do backend; 502 contido; relé WebSocket cru com
backend fake; mapa das 5; `/f/livros` = 404) + vivas: sem credencial
**302 `/auth/login`** (local e pelo Funnel público), as 5 **200** com
chave de operador, `GET /f/caderno/api/config` **200** com JSON (a API
relativa do FlatNotes chega inteira), ativos da Caixa **200** em
`/f/caixa/static`, Cofre **200** no path, raiz do Site **200**
intacta. **Análise das outras 4 (ordem do dono: "analisar se realmente
preciso"):** Livros/Kiwix/Stirling/Homebox não suportam subcaminho
(provado no portal 8443) e **não vão para o Funnel**; recomendação
entregue: casa+celular (Tailscale) bastam, e o Kiwix ganhou destino
melhor — **dentro do chat** (ideia do dono na nota TODO 5;
`integrations/kiwix.py` + busca JSON provada, falta o orquestrador
consultá-lo). Se um dia algum precisar público, o caminho é **hostname
próprio** (DDNS + proxy na frente), nunca subcaminho.

**Continuação (22/10): CAMPO DE LOGIN CONCERTADO + MENU DAS FERRAMENTAS
NO ADMIN (feedback do dono: "não está pedindo senha, está parando na
tela de login, mas não tem como digitar... coloca um link no menu do
administrador").** Causa: o 302 do portário apontava para
`/auth/login`, que é **rota de API (só POST)** — o navegador parava num
405 sem formulário nenhum. Correção: o portão agora manda para
**`/chat?next=/f/<ferramenta>/`** (a página do chat é quem tem o
formulário de verdade), e o JS do login ganhou a guarda `next`
(`startsWith("/f/")` — só caminho do portário, sem open redirect): ele
digita a senha e cai **direto na ferramenta** que pediu. **Menu do
admin** ganhou a seção **🛠 Ferramentas** (5 links em cards, abrem em
aba nova com a mesma sessão) — ordem do dono. +2 testes de contrato
(formulário + guarda no /chat; menu com as 5 no /admin) = **16/16**;
provas vivas: 302 com Location novo, `id="login-pass"` e a guarda
presentes no /chat, 5/5 links no /admin.


## [1.43.0] — CALIBRE WEB INTERLIGADO: A BIBLIOTECA DE E-BOOKS VAI DO DRIVE AO LEITOR 🜂 (2026-10-19)

**Resumo:** 3ª da série "uma por vez" (FlatNotes ✅ → File Browser ✅ → **Calibre**). Dono decidiu **"Configurar e interligar"** (19/10) e apontou a fonte: *"os livros estão no google drive"* — pasta **"Biblioteca"** do Drive dele (22 pastas temáticas, **732 itens / 729 arquivos / 1,83 GB** medidos recursivamente; a contagem de 1º nível mentia: 363/1,35 GB). A entrega monta a cadeia inteira: **Drive → espelho local → `calibredb` → Calibre Web (web + OPDS) → actions + botão no app**, e o caminho ensinou duas lições registradas em código: **(1)** o dedup por título do calibre (`--automerge ignore`) **escondeu 156 arquivos de conteúdo diferente** (título embutido do PDF colidindo — provado ao vivo com a mensagem crua *"not added as they already exist"*), então o contrato de resync passou a ser um **LEDGER nosso** (`.calibre_ledger.json`: caminho→tamanho) + `-d --automerge new_record` (colisão de título vira registro próprio); **(2)** a análise de conteúdo por tamanho enganou com **cópias idênticas em duas pastas e zips extraídos** — 55 duplicados criados pela migração foram detectados por **sha256 par a par (55/55 idêntico)** e removidos **só** os ids da migração (54 originais intactos). Estado final provado: **693 livros, 729/729 arquivos com conteúdo, 0 pendentes, reimportação devolvendo `novos=0`**.

| Peça | Entrega |
|---|---|
| **`core/biblioteca_drive.py` (novo)** | Espelho Drive→disco incremental: pula arquivo igual por tamanho, download atômico (`.part`→rename), nome do Drive saneado (não escapa do destino), erro contido por arquivo (o resto segue), aviso de página cheia. **729 arquivos / 1,7 GB espelhados, 0 erros.** +7 testes. |
| **LEDGER + `calibredb` (desenho corrigido ao vivo)** | `integrations/calibre.py::importar_da_inbox` reescrita: ledger ausente **recusa** importar às cegas (`calibre_ledger_ausente` — sem saber o que já entrou, 729 arquivos virariam 729 registros); só o que o ledger não viu vai no lote `calibredb add -d --automerge new_record`; ledger só cresce após `rc==0`, gravação atômica; `.part`/próprio ledger fora do argv. Migração: 573 semeados + **156 importados** (ids 593–748); prova de idempotência = reimportação `novos=0`. |
| **Limpeza honesta dos 55 duplicados** | A migração reimportou cópias que o twin-por-tamanho marcou como faltantes (47 arquivos iguais em duas pastas + 8 zips — o calibre **extrai** o zip e os bytes mudam). Detecção: par por (título+formato+tamanho) → **sha256 dos 55 pares = 55/55 idêntico** → `calibredb remove` **só nos ids da migração** → **693 livros / 695 formatos**, 54 originais provados intactos. Nada do dono perdido: os arquivos originais seguem no espelho e no Drive. |
| **Calibre Web configurado ao vivo** | `POST /admin/dbconfig` com `config_calibre_dir=/books` **salvo** (o alerta do `client_secrets.json` é não-bloqueante; ordem obrigatória: import → apontar). Home virou **"Calibre-Web \| Books"** com 65 autores. Upload de escrita só pela UI (CSRF) — fora do catálogo. |
| **Senha trocada (admin123 morta)** | Política do próprio Calibre Web **exigia caractere especial** (`config_password_special=1` — achado na recusa *"Password doesn't comply"*): senha de **32 caracteres** com especial do conjunto seguro (`.env`/basic-auth), montada pelo form **inteiro devolvido como está** (papéis/sidebar/csrf preservados — postar só a senha teria tirado o `admin_role`). Prova por hash no container: `check_password_hash` **nova=True, admin123=False**. Valor nunca impresso; espelhada no cofre (**16/16**). |
| **Bind duplo + tailnet** | compose recriado: `127.0.0.1:8420` + `100.77.67.53:8420` → provas nos dois caminhos e **login pela tailnet** (o caminho exato do botão do app). `OD_CALIBRE_URL` do `.env` aponta para a tailnet para os **links de download serem clicáveis pelo dono no celular**. |
| **Cliente OPDS (sondado ANTES de codificar)** | Sonda viva (19/10): `/opds/` = **15 seções**; `/opds/new` pagina por `?offset=60` (60/página); `/opds/search/<termo>` devolve **todos** os matches numa página (123 p/ "Aula"; `?query=` também serve); download `/opds/download/<id>/<fmt>/` → **200 `application/pdf`**; senha errada = **401 "Unauthorized Access"**. Cliente stdlib LAZY: `opds_status` (sonda + inventário exato do `metadata.db` + pendências vs ledger) e `opds_busca` (resultados com formatos e links absolutos); erros tipados `opds_auth/indisponivel/http/xml_invalido/config_ausente` + `calibre_busca_termo_vazio`. |
| **3 actions (categoria `calibre`, catálogo 112 → 115)** | `calibre_resync` (espelho + importação por ledger) · `calibre_status` (HTTP real do OPDS + livros/formatos/pendentes — **693 livros, 0 pendentes** ao vivo) · `calibre_busca` (links prontos `http://100.77.67.53:8420/opds/download/...`). Nenhuma action apaga; nenhuma escreve. |
| **App + capability** | Botão **"Biblioteca"** (`odCalibreUri` porta 8420) já no card do painel (+3 testes) · capability `calibre-biblioteca` (fase v1.43.0) com o contrato vivo escrito. |
| **Bump 9/9** | `.env` 1.43.0 · capabilities fallback · pubspec **1.43.0+2079** · `_APP_VERSION_CODE` 2079 · site (versão ×3, Actions 115, Testes 3.449) · CHANGELOG · README_VERSAO · ANALISE · APK. |

### Validação (19/10, tarde)

| Pilar | Prova |
|---|---|
| Suíte do servidor (gate oficial `--cov-fail-under=90` + `.coveragerc`) | **3449 passed / 16 skipped / 0 falha · cobertura ≥ 90** (+27 sobre 1.42.0: ledger/OPDS/espelho/contagens) |
| Flutter | `flutter analyze` **0 issues** · `flutter test` **198 passed / 2 skipped** (+3 do botão Biblioteca) |
| Biblioteca (prova da completude) | **729/729 arquivos com conteúdo** (721 com bytes no `/books` + 8 zips extraídos) · **0 sem conteúdo** · **693 livros / 695 formatos** · reimportação `novos=0` (idempotente) |
| Provas ao vivo | Calibre Web **200 em `127.0.0.1:8420` e `100.77.67.53:8420`** · login tailnet com a senha nova · OPDS raiz 15 seções · busca 15 hits · download 200/pdf (2,1 MB) · senha antiga morta (hash) · cofre **16/16** |
| E2E vivo pós-deploy | **29 provas, 0 falhas** (od-core reiniciado): `/app/version` **1.43.0/2079** · `/health` 24/24 · `/actions` 115 · capability presente · APKs nos dois · Calibre Web **200 nos dois binds** · OPDS 15 seções/busca/download 200/401 · `calibre_status` 693/0/729 · `calibre_busca` com links da tailnet · `calibre_resync` **732 itens 0 erros, sync < 60s (era 305s), novos=0** · journal limpo · NRestarts=0 |

### Três bots, um por papel — divisão do Telegram + rotação do token vazado (20/10, sem bump)

**Resumo:** o dono rotacionou o token do **@Nicky_Virthy_bot** (o vazado em `docs/SERVER_ANALYSIS.md` no histórico público — provado morto por **401** após o `/revoke` do BotFather) e dividiu os três bots dele: *"Nicky_Virthy = Chat, Nexus_Nicky = alertas dos usuários pedindo informações e nicky_monitor = monitoramento, alertas do sistema"*.

| Papel | Bot | O que sai por ele |
|---|---|---|
| **`chat`** (`TELEGRAM_BOT_TOKEN`) | @Nicky_Virthy_bot | conversa, comandos do dono (`TelegramBot` polling) |
| **`usuarios`** (`OD_TELEGRAM_USUARIOS_TOKEN`) | @Nexus_Nicky_bot (o legado renasce) | 💬 mensagens da sala de bate-papo das peças + 🔑 registro de posse (`chat_notify`) |
| **`monitor`** (`OD_TELEGRAM_MONITOR_TOKEN`) | @nicky_monitor_bot | notifier inteiro (saúde/restart/disco/stack), presença, face e resumo de sessão do orquestrador |

- **`PAPEIS_BOT`** no `runtime/launcher.py` + `build_telegram_sink(papel)` — cada papel tem token/chat próprios (`OD_TELEGRAM_<PAPEL>_TOKEN`/`_CHAT`) e, quando vazios, **cai no chat** (degradação honesta: um bot fora nunca cala o sistema). O orquestrador (`_notificar_telegram`) usa o token de monitor com o mesmo fallback.
- **Prova viva:** três mensagens de teste, uma por bot, entregues no chat do dono · getUpdates do bot principal com token novo · cofre espelhado **18/18 gravado+conferiu**.
- **Correção de teste:** `test_presenca_confirmada_nao_vai_para_dead_letter` chamava a API real do Telegram (passava só porque o token velho era válido — com o 401 da rotação virou dead letter); agora injeta o sink falso como os vizinhos.
- Testes: **3464 passed / 16 skipped / 0 falha** (+15: 11 dos papéis dos bots + 4 do orquestrador).

### Guarda de segredos no CI — o repo nunca ganha um segredo novo sem alarme (ordem do dono "pode implementar o CI", 20/10, sem bump)

**Resumo:** ordem do dono 20/10 (fechando o risco residual de manter o repo público). `tools/secret_guard.py` (stdlib, zero dependência) varre **todos os arquivos rastreados** (`git ls-files` — o que de fato vai ao GitHub; os 389/391 de hoje) por 8 famílias de padrão: chave privada PEM · GitHub (`ghp_`/`gho_`/`ghs_`/`ghu_`/`ghr_`/`github_pat_`) · OpenAI (`sk-`, com lookbehind que evita `task-sk-` como falso positivo) · Google/Gemini (`AIza…`) · token de bot Telegram (`id:token`) · AWS (`AKIA…`) · Slack (`xox…`) · GitLab (`glpat-`). Achei = **exit 1** com anotação `::error` pública `arquivo:linha` no job do Actions. Escopo deliberado: a árvore ATUAL (o histórico já foi auditado à parte em 20/10 e seus segredos mortos rotacionados) — a guarda é contra o **deslize novo**.

- **Step no `.github/workflows/ci.yml`** logo após o setup do Python (falha em segundos, antes de instalar dependências).
- **+27 testes** (`tests/test_secret_guard.py`): os 13 padrões, limites (token de 35 caracteres ≠ 36), binário pulado, `main()` com exit 0/1/2, saída CI → anotação, e o **teste vivo**: o repo real inteiro precisa varrer limpo — falha primeiro no seu PC do que num commit público.
- **Prova da guarda no próprio dia:** os 3 PEMs literais dos dados de teste casaram na primeira rodada (a guarda pegou o próprio autor) → reconstruídos por concatenação, repo limpo de novo.
- **Deploy verde:** suíte **3491 passed / 16 skipped / 0 falha** · push `0e99afa` · **run do GitHub: `completed/success`** com o step *"Guarda de segredos"* **success** (job "pytest + compileall + cobertura" inteiro verde).

### Off-site pelo canal PRIVADO do Telegram — os backups saem de casa (ordem do dono, 20/10, sem bump)

**Resumo:** fecha o último degrau do backup. O diário nas 2 HDs + o semanal das capturas protegem contra falha de disco, mas as duas HDs estão na **mesma casa** — incêndio/roubo/alagamento leva tudo. O dono apontou o canal `t.me/omegadrakon` como destino (*"praticamente ilimitado"*), **fechou o canal para Private** quando alertei do risco (convite chegou pelo `txt.txt`) e decidiu: canal privado agora, Mega/Dropbox para o futuro. Custo **R$0**.

| Peça | Entrega |
|---|---|
| **`core/offsite.py` (novo)** | Envia os artefatos que os perfis **já criam** (não inventa backup novo): `backups/auto/od-*.tar.gz` (diário, ~190 KB) e `backups/auto-capturas/od-capturas-*.tar.gz` (semanal, ~316 MB → **fatiado em ≤48 MB por GERADOR** — o tar nunca fica inteiro na RAM) via `sendDocument` multipart **stdlib** (sem dependência). **Idempotente** por nome+sha256 (estado em `data/offsite_state.json`, gravação atômica) — o mesmo tar nunca sobe duas vezes; arquivo novo (ou mesmo nome com conteúdo diferente) envia. Falha = retry no próximo tick + **push no celular** (cooldown 6 h, igual ao backup local); push quebrado não derruba o ciclo. Check **não-crítico** `offsite` no `/health`: ok se o diário foi enviado nas últimas 48 h; degrada, não derruba. **Fora por construção** sem `OD_OFFSITE_CHAT` (id do canal, `-100…`); `OD_OFFSITE=0` desliga. Token padrão = o do bot de monitoramento. |
| **Launcher + API** | `build_offsite` (best-effort, warn + None se o env quebrar) + loop supervisionado em `to_thread` (upload de 316 MB não prende o event loop do Telegram/WebSocket) + check no `/health`. API: bloco `offsite` no `/dashboard/stats` + card **"Off-site"** no `/admin` ("nunca" em vermelho até o primeiro envio — pendente honesto). |
| **+34 testes** (`tests/test_offsite.py`) | Fatiamento lazy (gerador provado: só a primeira fatia é lida no primeiro `next`), multipart, envio único/fatiado/recusa do bot, idempotência por nome **e** por sha, estado corrompido, push quebrado, cooldown, saúde up/degraded/idade, fiação `build_service`/`build_offsite`, bloco no stats + card. `core/offsite.py` **100%**; **mutações 3/3 capturadas** (idempotência removida, check virou crítico, cooldown zerado) com reversão bit-exata. |

**Validação:** gate oficial **3525 passed / 16 skipped / 0 falha · cobertura 90,70%** (+34). Restart verde 14:00:14 (regra 7.3, `b7cdd05` pushado antes): NRestarts=0, journal 0 `[ERROR]`, `/health` 24/24, `/app/version` 1.43.0/2079 intacta (backend puro, **sem bump**). Prova do modo seguro: sem `OD_OFFSITE_CHAT` o serviço fica **fora por construção** (journal: *"Off-site fora — falta OD_OFFSITE_CHAT"*), sem check e sem card.

**Ativação + prova viva (mesmo dia, 14:25–14:33):** dono cumpriu o clique (*"feito"* — @nicky_monitor_bot adicionado como **administrador** do canal), id capturado por `getUpdates` (`Omega Drakon` `-1001019416047`, `my_chat_member`=administrator) e gravado em `OD_OFFSITE_CHAT`. **1º tick completo:** diário `od-2026-10-20_0309.tar.gz` em 1 parte (14:25:54, sha `286d20a57c25…` == o do dia) + capturas em **7 partes de 48 MB** (14:27:40, ~2 min) → `/health` **25/25**, check `offsite` up. **Defeito real corrigido no caminho:** o estado só gravava no fim do tick — uma queda no meio do upload longo descartaria o diário já no canal e o próximo tick o reenviaria; agora é **por perfil** a cada envio (+1 teste, módulo 100%). Gate final **3526 passed / 90,70%**; deploy `0446f14` + restart verde 14:33:04; **idempotência pós-restart provada** (tick de boot não reenviou nada; `ultimo_envio` = 14:25:54).

### `historico.html` completado até a v1.43.0 — as 9 eras fechadas (20/10, sem bump)

**Resumo:** pauta de conteúdo do TODO (§3, achada em 17/10): a linha do tempo dos releases do site parou na **v1.25.0** enquanto o projeto chegou à **v1.43.0**. Ordem do dono *"historico"* (20/10 ~15:40) → completada a partir da fonte viva, sem invenção de conteúdo.

| Peça | Entrega |
|---|---|
| **4 eras novas (Era 6 → 9)** | **Era 6 · Ferramentas Nômades** (14→15 out, 4: 1.26.0 RAG · 1.27.0 downloads · 1.28.0 auto-update · 1.29.0 depot) · **Era 7 · Registro e Autonomia** (15→16 out, 5: 1.30.0 QR/posse · 1.31.0 auto-update no app · 1.32.0 tema · 1.33.0 ID único · 1.33.1 loja por seções) · **Era 8 · Stack Nômade no Ar** (16→17 out, 7: 1.34.0 Protocolo_NV · 1.34.1 Homebox fora · 1.35.0 Vaultwarden · 1.36.0 Stirling · 1.36.1 boot do RAG · 1.37.0 Kiwix · 1.38.0 Homebox) · **Era 9 · Formato Órion e a Biblioteca** (17→19 out, 8: 1.39.0→1.39.3 Órion + snapshots · 1.40.0 FlatNotes · 1.41.0 File Browser · 1.42.0 botão da caixa · 1.43.0 Calibre). **+24 releases → 74 no total, 9 eras.** |
| **Contagens que já mentiam, corrigidas** | Era 5 dizia **"8 releases"** e listava **10** (a 1.24.2 e a 1.25.0 entraram sem atualizar a faixa) → `09 → 13 out · 10 releases`. `index.html`: "48 Lançamentos" / "Ver os 48 releases" / "cinco eras" → **74 / 74 / nove eras** (+ nomes das 9). Meta description e comentário do `od.css` idem (linha do comentário também trazia o total velho do CHANGELOG). |
| **Achado documental (registrado, não consertado)** | o CHANGELOG **não tem** a seção da **1.24.2** (ela existe só no `docs/README_VERSAO.md`) e o README de Versão **não tem** a da **1.42.0** (existe só no CHANGELOG) — dois furos de registro anteriores a hoje; a **união** dos dois documentos cobre as **74** versões e é essa união que a guarda usa. |
| **Guarda nova (teste do teste)** | `TestAPISite::test_historico_cobre_todos_os_releases_e_contagem_verdadeira` (+1): união das duas fontes ⊆ lista da página · sem release repetido · ordem crescente · kicker (`Os 74 Lançamentos`) + meta (`74 releases organizados`) + faixa final (`v1.0.0 a v1.43.0`) batem com a lista · **soma dos `· N releases` por era == total e nº de `era-box` == nº de faixas** · index com o MESMO número (o par "48" que sobrava também é proibido). **Mutações 4/4 capturadas** (release apagado · kicker 74→73 · faixa da era 4→5 · 1.42.0 removida) com restauração bit-exata. |
| **Números do index honestos de novo** | `Testes` no topo do index **3.449 → 3.527** (a suíte real do gate de hoje — o número ficou para trás quando as entregas "sem bump" acrescentaram testes); a guarda `test_site_index_chip_vivo_e_numeros_reais` foi ajustada junto, então ele volta a falhar no próximo descasamento. Actions **115** conferidas ao vivo (`/actions`). |

**Validação:** gate oficial **3527 passed / 16 skipped / 0 falha · cobertura 90,68%** (+1) · `html.parser` sem erro. **Sem restart** (site lido do disco por requisição). **Prova viva:** `GET /site/historico.html` → **200, 29.888 B, byte-idêntico ao disco**, **74** `r-ver`, `Era 9 · Formato Órion e a Biblioteca` e `Os 74 Lançamentos` no corpo servido; `/site/index.html` → `Ver os 74 releases`.

### União dos documentos de versão fechada — 4 cabeçalhos ausentes, 0 corpo perdido (20/10, sem bump)

**Resumo:** ordem do dono *"faça a união"* (20/10, tarde) fechando os 2 furos registrados no caminho do `historico.html`. Apuro de classe: **nenhum corpo está faltando — faltavam CABEÇALHOS**, o mesmo defeito do `## [1.31.0]` engolido achado em 16/10. O CHANGELOG trazia o corpo da **1.24.2** solto entre 1.25.0 e 1.24.1; o README_VERSAO trazia o da **1.42.0** solto entre 1.43.0 e 1.41.0. A guarda nova de "seções irmãs" ainda achou **mais dois**: **1.3.0** e **1.6.1** existiam só no CHANGELOG (nem corpo, nem título, no README) → portadas para lá.

| Peça | Entrega |
|---|---|
| **`docs/CHANGELOG.md`** | `## [1.24.2] — EVAL DO ASSISTENTE (PARTE A) + CLIMA/CÂMBIO DO USER CONCERTADOS 🜂 (2026-10-13)` reinserido acima do corpo que já existia (título verbatim do README — o único lugar que o tinha). |
| **`docs/README_VERSAO.md`** | `## [1.42.0] — BOTÃO DA CAIXA NO PAINEL: SEM WEBVIEW, O APP ABRE NO NAVEGADOR (2026-10-19)` reinserido acima do corpo órfão (título verbatim do CHANGELOG) + **2 seções portadas do CHANGELOG** no formato local (`### 1. O que foi feito` / `### 2. Evidência`): `## [1.6.1]` (IP/portas pela action + anti-recusa, PATCH de 26/09) e `## [1.3.0]` (papéis/histórico/painéis + saneamento de versão, 19→26/09, com o mesmo ponteiro para as seções [1.2.0] por ordem cronológica). |
| **Guarda nova (teste do teste)** | `TestAPISite::test_docs_de_versao_completos_e_irmãos` (+1): CHANGELOG e README têm o **MESMO conjunto** de seções `1.x` (74 == 74, a diferença é listada no erro) · o topo dos dois é a **versão corrente** (`OD_VERSION`) · a versão corrente aparece literalmente como `## [x.y.z]` nos dois — mata a classe "corpo órfão de cabeçalho" e o "release que ninguém registrou". **Mutações 2/2 capturadas** (cabeçalho 1.6.1 borrado no README · cabeçalho 1.24.2 borrado no CHANGELOG), restauração bit-exata. |

**Validação:** gate oficial **3528 passed / 16 skipped / 0 falha · cobertura 90,68%** (+1) · as duas fontes conferidas por script: **74 seções cada, conjuntos idênticos, topo 1.43.0 == `OD_VERSION`**. **Sem restart** (documentos lidos do disco; a união também é o que a guarda do `historico.html` consumia — ela continua verde com 74 ⊆ 74).

### Menu lateral no site e no painel — a barra colapsável do formato Órion (20/10, sem bump)

**Resumo:** na troca da união o dono apontou o item pendente do formato Órion (v1.39.0): *"ainda tem uma mudança no site que vinha do orion, menu na lateral"*. A análise de 17/10 listou 5 elementos (herói, KPIs, mini-painéis vivos e **barra lateral colapsável**), mas a entrega **ao site** foi só *chip vivo + números reais* e o menu seguiu o `⋮` no topo das 11 páginas. Perguntei o escopo (só index / site inteiro / site + painel) e ele escolheu **"site + painel juntos"**.

| Peça | Entrega |
|---|---|
| **Site — `site/od-nav.js` (comportamento 5)** | `lateralMontar()` injeta o `<aside id="odLateral">` **clonando os MESMOS links do painel `⋮`** (`cloneNode` da marca e de cada `<a>`, classe `cta` preservada): o HTML do menu continua existindo em **um lugar só** — é exatamente a divergência entre páginas que já aconteceu. Só monta onde há menu; sem elementos sai sem erro (o harness do tema segue limpo). Idempotente pela marca `odLateral`; **recolher (☰)** alterna `od-lateral-recolhido` na raiz e grava `od_lateral` no `localStorage` (reabre do jeito que ficou). |
| **Site — `site/od.css`** | Bloco `.od-lateral` em `@media (min-width: 1024px)`: barra fixa à esquerda (236px → **68px recolhida**, marca sai e os rótulos encolhem — sem inventar iconografia), a nav fixa acompanha via variável `--od-lat-w`, e no desktop o `⋮` dá lugar ao ☰ (no celular <1024px **nada muda**: o `⋮` continua). Tinta só nas variáveis do tema → claro e escuro sem paleta duplicada. |
| **Painel — `_FORMATO_ORION_CSS`/`_JS` (fonte única)** | Barra injetada no `/dashboard` e `/admin` pelo próprio formato (mesma arquitetura do tema, **um único `<script>`** seguido); `/chat` **inócuo** (sem `#odOla` o `iniciar()` sai cedo e ele mantém o próprio cabeçalho). Itens Painel/Chat/Site para todos e **Admin só para papel admin**: o `quemAmI` das duas páginas passa o papel em `odFormato.nome(nome, papel)` e `lateralAdmin()` acrescenta o item — nada de item que leva a uma página que o usuário não alcança. Mesmo `localStorage` do site (`od_lateral`). |
| **Guarda nova (teste do teste)** | `TestMenuLateralOrion` (**+4**): CSS/JS da barra no site (incluindo o recolher e a mídia 1024px) · **as 11 páginas continuam SEM HTML de menu** (a barra é injetada — é isso que trava a duplicação que já aconteceu) · painel com `odLateral`, `papel === "admin"` e `nome(data.user.username, role)` servidos **e um único `<script>`** nas três páginas · `node --check` do `od-nav.js`. **Mutações 4/4 capturadas** (clonagem removida · markup plantado numa página · `lateralAdmin` desligado · papel parado de ser repassado), restauração bit-exata — as duas primeiras rodadas escaparam e a guarda foi endurecida antes de valer. |

**Defeito real da entrega (mesmo dia, 20/10) — achado pelo dono, corrigido no mesmo dia:** ele reportou *"menu ficou errado, está sobre a página"*. Reproduzido com **render de verdade** (chromium headless instalado isolado em `/tmp`, sem sudo e fora do repositório): no **site** os itens da barra viravam uma **faixa de largura total por cima da página**. Causa raiz: o contêiner dos links era um **`<nav>`**, e o `od.css` tem a regra global `nav { position: fixed; top:0; left:0; right:0 }` (a barra do topo) — o contêiner herdava `fixed` de ponta a ponta. **Correção:** contêiner virou `<div class="od-lateral-links">` (no site **e** no painel, mesma construção) e o deslocamento da nav do topo ficou apertado em `html.od-com-lateral body > nav`. **Guardas novas na mesma classe** (a de strings não pegou porque não afirmava a TAG): `createElement('nav')` proibido no `od-nav.js` · `body > nav` obrigatório no `od.css` · `<div class="od-lateral-links">` presente e `<nav class="od-lateral-links">` ausente no painel. **Prova do conserto:** re-render nas DUAS superfícies + página interna + tema escuro + estado recolhido (68px, links dentro da barra, `dentro_da_barra: true`) e celular (barra escondida, ⋮ intacto).

**Validação:** gate oficial **3532 passed / 16 skipped / 0 falha · cobertura 90,69%** (+4) · **harness de node** com DOM de mentira rodando o `od-nav.js` de verdade: barra montada com a marca e os links clonados (cta preservada, `title` com o nome completo), ☰ recolhe e grava `recolhido`, o 2º clique devolve `aberto`, **2ª chamada = 1 barra** (idempotente). **Restart verde 17:27** (NRestarts=0, journal 0 `[ERROR]`, `/health` **25/25**, `/app/version` **1.43.0/2079**). **Provas vivas no ar:** `/dashboard` e `/admin` com `odLateral`, `<div class="od-lateral-links">` (e **zero** `<nav>` da barra) e **um único `<script>`** · `/chat` inócuo · `od-nav.js` servindo `createElement('div')` (e nenhum `createElement('nav')`) · `od.css` com `body > nav` · `site/index.html` sem markup novo (só injeção) · `historico.html` 200.

### Dashboard unificado — a Visão do sistema no /admin (20/10, sem bump)

**Resumo:** ordem do dono no fim do menu lateral (*"O que tem pra agora?"* → ele escolheu **"Dashboard unificado"**, §3.6 do TODO): o `/admin` ganhou a visão **"System Overview"** com **um card por subsistema — 15 no total** — tudo lido das **MESMAS fontes de sempre** (`/health` · `/supervision` · `/dashboard/stats` · `/actions`), **sem busca nova**. Os 4 subsistemas que o `stats` já emitia e a tela não mostrava entraram junto: **RAG** (`vector_store`), **Auto-update** (alvos/desligados/pendentes), **Downloads** (fila) e **Ferramentas** (Supply Depot); bot, API, stack, backups, HDs e off-site já estavam e seguem.

| Peça | Entrega |
|---|---|
| **Seção (markup)** | `<h2>Visão do sistema (System Overview)` com **pill de resumo** (`#sys-resumo`) e a linha dizendo as fontes; a grade `#sys` continua a mesma (o `Atualizar` e os `<details>` brutos ficam embaixo). |
| **`visaoCards(health, sup, stats)`** | Toda a fila de cards saiu de dentro do `loadSystem` para **UMA função pura**: recebe os quatro payloads e só monta strings. É a alavanca da guarda de fonte única — se um `fetch` entrar dentro dela a visão vira fonte paralela e o teste derruba. |
| **Pill de resumo** | Conta os cards com classe `err` e pinta `X em atenção` / `tudo ok` — o número vem dos MESMOS cards, nunca é pintado por fora (servidor bom = `tudo ok`; um único sinal real já vira atenção). |
| **Sem dado = "—"** | Bloco ausente cai em `"—"` com classe **vazia** (nada de verde de mentira); vermelho só com sinal real: `auto_update.desabilitados > 0`, `downloads.erros > 0`, `ferramentas.ultimo_erro`, off-site que nunca saiu de casa e `!health.ok`. |

**Guarda nova (`TestVisaoDoSistema`, +3):** seção servida cobre os **10 rótulos** e os **7 blocos de dados** · o construtor **não busca nada** (corpo de `visaoCards` sem `fetch`/`http`, ≥4 fallbacks `"—"`, declarada e chamada UMA vez) · **harness de node** rodando o script do `/admin` com DOM de mentira em **3 estados**: completo (todos os subsistemas com valor real, `RAG` começa com `42 docs`), vazio (todos `"—"`, **nenhum em verde**) e problemático (auto-disable, erro de download, erro do depot e off-site sem envio viram `err`).

**Validação:** gate oficial **3535 passed / 16 skipped / 0 falha · cobertura 90,70%** (+3) · **restart verde 17:59:52** (NRestarts=0, journal 0 `[ERROR]`, `/health` **25/25**, `/app/version` **1.43.0/2079**) · **prova visual** (chromium headless + servidor legítimo com dono de teste): visão real com **15 cards e "—" honestos** + pill `1 em atenção` (servidor de teste é degraded), e visão com todos os blocos preenchidos (`42 docs · 1 ns` · `3 alvos · 0 desl · 1 pend` · `2 ativas · 7 ok · 0 erro` · `12/12 · 4 c/ histórico`) · `/admin` vivo servindo `visaoCards` ×2, `#sys-resumo` e **um único `<script>`**.

### Acesso pelo menu principal + /chat com a barra (20/10, sem bump)

**Resumo:** duas ordens do dono logo após o dashboard unificado — *"o acesso que poderia ser pelo menu principal, se estiver logado entra"* e *"chat também pode manter o menu lateral"*.

| Peça | Entrega |
|---|---|
| **Site — item Painel no ⋮ (`od-nav.js`)** | `acessoMontar()` insere `<a href="/dashboard">Painel</a>` **ANTES** da clonagem da barra (os dois menus continuam saindo dos MESMOS links — fonte única intacta), junto do Chat. **Sem sessão o menu não faz NENHUMA chamada à API**: o `/dashboard` manda pro `/chat` (login) — é o "se estiver logado entra". |
| **Site — Admin do dono nos DOIS menus** | `acessoAdmin()` bebe da **mesma resposta `/auth/me` que o tema já busca** (`temaSincronizar().then(acessoAdmin)` — uma ida à API, resposta compartilhada; a promise passou a ser devolvida). Com `role === "admin"` o `<a href="/admin">Admin</a>` entra no **⋮ junto do Chat** e na **barra por último** — a MESMA casa do `lateralAdmin()` do FORMATO nas páginas do painel (um item Admin, mesma posição, nas três telas). |
| **Painel — `/chat` mantém a barra (`_FORMATO_ORION_JS`)** | `iniciar()` chama `lateralMontar()` **antes** do cedo: a barra vale nas três páginas; no `/chat` só o herói/KPIs/relogio não rodam (a página mantém o próprio cabeçalho — e ela **não tem nenhum `position: fixed`**, então o deslocamento de 236px é limpo). O papel do dono lá o FORMATO pergunta sozinho (**`papelChat()`** — só com sessão: anônimo não ganha ida à API nem item Admin), porque o chat não tem `quemAmI`. |
| **Guarda nova (`TestAcessoPeloMenuELateralChat`, +4)** | estáticas (ordem `acessoMontar` antes do clonar, guarda `role !== 'admin'`, resposta compartilhada, `/chat` servido com o FORMATO e **um único `<script>`**) + **harness de node** rodando o `od-nav.js` de verdade nos DOIS cenários: **dono** → Painel antes do Chat nos dois menus, Admin nos dois (barra = último) e **1** chamada `/auth/me`; **anônimo** → Painel presente, Admin ausente e **0** chamadas. |

**Validação:** gate oficial **3539 passed / 16 skipped / 0 falha · cobertura 90,69%** (+4) · **restart verde 18:42:06** (NRestarts=0, journal 0 `[ERROR]`, `/health` **25/25**, `/app/version` **1.43.0/2079**) · **prova visual** (chromium headless + servidor legítimo com dono de teste): **site do dono** com Painel e Admin no ⋮ e na barra (Admin por último, 16/15 links), **`/chat` do dono** com PAINEL/CHAT/SITE/**ADMIN** e conteúdo deslocado 236px, **`/chat` anônimo** com a barra **sem** Admin · **no ar**: `/chat` servindo `papelChat` com **1 `<script>`**, `od-nav.js` servindo `acessoMontar` + a corrente do tema, e render anônimo do **serviço real** provando Painel no site (`#sobre, /dashboard, /chat, #download`) e barra no chat.

### Ícones no menu lateral: recolhido sem pedaços de palavra (20/10, sem bump)

**Resumo:** o dono avaliou o lote e apontou: *"não ficou legal o sistema de escrita, quando o menu retrai fica pedaços de palavras, seria melhor ícones"*.

**Réplica ANTES (chromium headless, o método da casa):** captura do estado recolhido mostrou o defeito ao vivo — 68px com rótulo só encolhendo a fonte (`.66rem`), a barra lia `MAR… ECO… SIST… PRO… HIST… VERI… PLÊI… PAIN… BAI… ADM…`.

| Peça | Entrega |
|---|---|
| **Site — `od-nav.js`** | Tabela `ICONES` **por href** na MESMA fonte única dos links + `iconeDe()` (as variações `/site#anc` e `/site/pag.html#anc` são o MESMO item — as 12 páginas têm menus divergentes de propósito) e o helper `lateralItem()`: todo item da barra vira `title` + `<span class="od-ico">` + `<span class="od-rot">`. Fora da tabela: **"•"**, nunca palavra cortada. `lateralItem` é o MESMO caminho do clonar e do Admin — forma única. |
| **Site — `od.css`** | Link em flex (ícone fixo + rótulo com ellipsis); recolhida: `justify-content: center` + `.od-rot { display: none }` — **some o rótulo, sobra o ícone centrado**, sem encolher fonte. Nome continua no `title` (hover) e no DOM (leitor de tela). |
| **Painel — `_FORMATO_ORION_JS` + CSS** | Mesmos glifos nos 4 itens (Painel 🖥️ · Chat 💬 · Site 🌐 · Admin 🛡️), `title` em todos (antes o chat não tinha nenhum), `lateralAdmin` montado na mesma forma; CSS **espelho exato** do site. Família de emoji explícita nos DOIS (`"Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji", …`) — o produto já usa 🛡 Admin do topo e 🤖/⚖️ no select do chat, é o mesmo contrato. |
| **Guardas (`TestIconesDoMenuLateral`, +4)** | estáticas dos DOIS lados (regra do recolhida **sem** `font-size`, presente em ambas as folhas); **cobertura de divergência**: os hrefs da união de TODOS os menus do site (28) avaliados no **`iconeDe()` REAL** no node — nenhum cai no "•"; **paridade** painel = site nos 4 glifos compartilhados; `/chat` servido com spans, CSS e um único `<script>`. Os 2 testes do harness de menu agora também exigem ícone real (nunca "•") + rótulo + `title` em cada item. |

**Validação:** gate oficial **3543 passed / 16 skipped / 0 falha · cobertura 90,69%** (+4) · pyflakes mesmos 3 avisos pré-existentes · **restart verde 19:15:27** (NRestarts=0, journal 0 `[ERROR]`, `/health` **25/25**, `/app/version` **1.43.0/2079**) · **prova visual antes/depois** (4 capturas por fase, servidor legítimo com dono): recolhido = **só ícones** (0 rótulos visíveis, 0 cortados, `title` em todos) nas DUAS superfícies; aberto = ícone + rótulo sem corte · **no ar**: render anônimo do serviço real confirmando `/site/` **15 itens** e `/chat` **3 itens** (anônimo sem Admin), `sem_icone=0`, `cortado=0`.

**Nota de ambiente:** a captura "depois" inicial saiu com quadradinhos — o chromium headless da máquina de teste não tinha fonte de emoji (`fc-list` = 0). A fonte foi instalada **em nível de usuário** (`~/.local/share/fonts`, fora do repositório, sem sudo) só para a prova; nada de dependência nova no produto (o emoji já era contrato: 🛡 do painel, 🤖/⚖️ do chat).

### Respiro do `main` na Verificação e na Loja: texto cortado sob a nav (20/10, sem bump)

**Resumo:** o dono reportou *"página verificação está muito alta, está cortando o texto"* e, ao ser mostrada a causa, confirmou *"loja também"*.

**Causa raiz (regressão silenciosa de 10/10):** o `od.css` tem `.wrap { padding: 0 24px }` (**classe**) e as páginas mandavam `main { padding: 130px 0 70px }` (**elemento**) — **classe vence elemento**, os 130px de respiro perdiam em silêncio e o conteúdo subia embaixo da **nav fixa (63px)**: o kicker "Registro Mestre · Verificação pública" sumia e o `h1` saía cortado ao meio. Linha do tempo: o `main` nasceu em **09/10** (5d45ada, v1.22.0) funcionando; em **10/10** (b3b86d8) o `.wrap` ganhou `padding: 0 24px` e a colisão começou. Varredura confirmou que **só** essas duas páginas têm `<main class="wrap">` com regra de elemento (`teste-tema` usa `style` inline, que vence) — e render de todas as 11 páginas mostrou nenhuma outra cortada.

| Peça | Entrega |
|---|---|
| **`site/verificacao.html` + `site/loja.html`** | `main { padding: 130px 0 70px }` → **`main.wrap { padding: 130px 24px 70px }`** — sub-especificidade que vence o `.wrap`; o 24px horizontal **mantém a calha** do wrap (a regra antiga, se vencesse, mataria a margem lateral no celular). Comentário nas duas explicando a armadilha. |
| **Guarda (`TestRespiroDoMainAbaixoDaNav`, +3)** | **varredura de TODAS as páginas**: `<main class="wrap">` com regra `main { …padding }` de elemento puro = falha (tem que ser `main.wrap`); respiro de topo ≥ 100px (nav = 63px) e calha ≥ 16px preservadas nas páginas com `main.wrap`; e as DUAS reportadas conferidas **servidas** (regra nova presente, antiga ausente). |

**Validação:** gate oficial **3546 passed / 16 skipped / 0 falha · cobertura 90,69%** (+3) · **sem restart** (só arquivos estáticos; servido == disco conferido por `curl`) — serviço seguia verde desde o restart 19:15:27 (NRestarts=0, `/health` 25/25, 1.43.0/2079) · **prova visual**: render das DUAS páginas em desktop e celular com kicker a **130px** (nav termina em 63), `h1` inteiro abaixo (`cima: True`) e `padding` computado `130px 24px 70px` · **varredura das 11 páginas do site**: todas com o primeiro conteúdo acima da nav (`topo ≥ 130`).

## [1.42.0] — BOTÃO DA CAIXA NO PAINEL: SEM WEBVIEW, O APP ABRE NO NAVEGADOR (2026-10-19)

**Resumo:** o dono respondeu à pergunta sobre webview (19/10): *"com o tailscale funcionando não existe finalidade em embutir, seria melhor apenas um botão que abre o navegador"* — **webview descartada**. O app ganha o botão **"Caixa de arquivos (abre no navegador)"** no card "Meu painel" (`launchUrl` no navegador de fora; URI derivada da mesma host do od-core, porta 8410) e, para o endereço valer de fora, a caixa ganhou **bind duplo** no compose — antes o `127.0.0.1` puro era **inalcançável do celular** (as provas da 1.41.0 diziam "pelo celular" sem testar o bind: honestidade corrigida com prova nova da tailnet).

| Peça | Entrega |
|---|---|
| **Botão no Painel (novo `ListTile`)** | Card "Meu painel", mesmo padrão dos vizinhos (`Icons.folder_open_outlined`) → `launchUrl` com `LaunchMode.externalApplication`; se o lançador recusar (Tailscale desligado), **aviso honesto** no SnackBar — a tela nunca trava. |
| **`odFileBrowserUri` (fonte única)** | `Uri.parse(odDefaultLocalUrl).replace(port: 8410)` — a mesma host que o app usa com o od-core; se a IP da tailnet mudar, muda num lugar só. |
| **`url_launcher: ^6.3.1`** | 1ª dependência do app que sai do app (sem `<queries>` no manifesto: só `canLaunchUrl` exigiria). |
| **Bind duplo da caixa (infra, sem bump próprio)** | `docker/tools-compose.yaml`: `127.0.0.1:8410` (actions do sistema) + `100.77.67.53:8410` (tailnet do dono) — só a interface do Tailscale, nunca LAN nem cara pública (o od-core é `0.0.0.0`; aqui o estrito manda). Container recriado com `restarts=0`. |
| **Testes** | app **+3** (`dashboard_caixa_test.dart`: URI certa, botão presente, toque com canal mockado provando a URI exata + aviso honesto) · servidor **+1** (`TestBindDuploCompose`: removem qualquer linha do bind, a suíte quebra). |
| **Bump 9/9** | `.env` 1.42.0 · capabilities fallback · pubspec **1.42.0+2078** · `_APP_VERSION_CODE` 2078 · site (versão ×3, Testes 3.422) · CHANGELOG · README_VERSAO · ANALISE · APK. |

### Validação (19/10)

| Pilar | Prova |
|---|---|
| Suíte do servidor (gate oficial `--cov-fail-under=90` + `.coveragerc`) | **3422 passed / 16 skipped / 0 falha · cobertura 91,11% ≥ 90** (+1 guarda do bind sobre 1.41.0 = 3421) |
| Flutter | `flutter analyze` **0 issues** · `flutter test` **195 passed / 2 skipped** (+3) |
| Provas ao vivo | caixa responde **HTTP 200 em `http://100.77.67.53:8410`** (o caminho exato do botão) · `127.0.0.1:8410` segue 200 · `filebrowser_status` ok · `/health` 24/24 · od-core reiniciado: `/app/version` **1.42.0/2078** · APK `aapt` `versionCode='2078'` + sha256 idêntico ao anunciado |
| E2E vivo | **48 provas, 0 falhas** (nova prova: alcançabilidade da tailnet) |

## [1.41.0] — FILE BROWSER INTERLIGADO: A CAIXA DE ARQUIVOS DO DONO 🜂 (2026-10-19)

> **Bump MINOR aprovado pelo dono em 18/10 ("Liga")** — 2ª ferramenta da
> série de análises (FlatNotes ✅ → **File Browser** → Calibre, "uma por vez"
> §5). Ele mandou **"primeiro me explica"** — análise entregue primeiro (o
> que é; estado real apurado ao vivo; como o sistema usaria; conta honesta;
> recomendação) e depois **"Liga"**. A análise achou duas coisas que viraram
> entrega: **o login admin/admin nunca chegou a funcionar** (dono "nunca
> entrou" — senha redefinida por CLI oficial com o container parado, valor
> nunca impresso, gravada no `.env` + espelhada no cofre) e a imagem era a
> **única tag flutuante da stack** (`:v2` → pinnei **`:2.63.23`**, a versão
> exata que estava no ar). Caixa de correio dos dois lados: o dono sobe e
> baixa arquivos pelo celular (Tailscale); o sistema deixa saídas lá.

| Peça | Entrega |
|---|---|
| **`integrations/filebrowser.py` (novo)** | Cliente `FileBrowserClient` no molde do FlatNotes (transporte injetável, fábrica lazy `OD_FILEBROWSER_URL`/`OD_FILEBROWSER_PASSWORD`, JWT de 2h cacheado com folga de 120s antes do `exp`). **Contrato apurado ao vivo ANTES de codificar** (18/10 — fonte oficial `http/*.go` da tag 2.63.23 + round-trip completo: login → listar → subir → conflito → sobrescrever → baixar → apagar minhas pastas de teste). **9 erros honestos e tipados** (`indisponivel/timeout/falhou/parametro_invalido/ja_existe/nao_encontrado/resposta_invalida/credencial/arquivo_ausente`). |
| **Upload = corpo CRU (achado vivo)** | O multipart (`-F`) guardava o **envelope inteiro** — 272 B contra 67 B do arquivo — apurado na prova e confirmado no fonte (`writeFile(..., r.Body, ...)` lê o corpo direto). O cliente manda `application/octet-stream` com o arquivo em **streaming** (sem carregar tudo na RAM) e o `POST` cria as pastas-pai sozinho. |
| **409 = recusa honesta** | Arquivo repetido sem `?override=true` → **409 Conflict** → `filebrowser_ja_existe` com a saída na mensagem. **`substituir=false` por padrão**: troca só com flag explícita e vem **DECLARADA** (`substituido=true` só quando o arquivo já existia — conferido na pasta-pai antes, só metadados, sem baixar conteúdo). |
| **3 actions (categoria `filebrowser`, só admin)** | `filebrowser_status` (saúde pública `GET /health`, versão no `window.FileBrowser` do HTML, itens, disco em bytes) · `filebrowser_lista` (raiz vazia = `itens=[]` honesto; pasta inexistente = 404; arquivo no caminho = parâmetro inválido; `..` recusado na API) · `filebrowser_envia` (arquivo local → caixa, `substituir=false`). Nascem admin-only por construção (`permission=nome`, lista `user` intocada). **NÃO existe action de apagar**: o `DELETE` da API fica de fora do catálogo — teste fixa a régua. |
| **Segredo + imagem pinada** | `OD_FILEBROWSER_PASSWORD` nova (24 caracteres gerados pelo sistema — o admin/admin nunca funcionou) no `.env` + espelhada no cofre. Compose: `filebrowser/filebrowser:v2` → **`v2.63.23`** (última tag flutuante da stack pinada) e comentário do compose atualizado com o estado verdadeiro. |
| **Capability + contagem** | Bloco `filebrowser-caixa` (fase v1.41.0) no `core/capabilities.py` com o contrato vivo escrito. **109 → 112 actions** em todos os lugares que contam: `EXPECTED_CATEGORIES` ganha `"filebrowser": 3`, asserts de contagem (5 arquivos de teste), docstrings do pacote e o site. |
| **Testes** | `tests/test_filebrowser.py` **+52**: fixtures fiéis às capturas vivas (health, janela HTML com `Version`, JWT, usage, raiz vazia, shape real dos itens, info de arquivo sem `items`, 409 textual), ordem exata do status (health → página → login → usage → raiz), `X-Auth` presente/ausente por chamada, 409 que **para na 2ª chamada** (nunca tenta sobrescrever sozinho), `substituir` declarado nos 3 casos (novo × trocado × pai inexistente), `..`/vazio/barra-final recusados **sem chamada nenhuma**, erros de rede, `_transporte` real (JSON, corpo cru octet-stream, HTTPError como resposta), fábrica lazy + permissão (user negado ×3, admin executa). |
| **Bump 9/9** | `.env` `OD_VERSION=1.41.0` + `OD_FILEBROWSER_URL` (config) · capabilities fallback · `_APP_VERSION_CODE` **2076 → 2077** · pubspec · site (versão ×3, Actions 112, Testes 3.421) · CHANGELOG · README_VERSAO · ANALISE · APKs. |

| Validado | Resultado |
|---|---|
| Suíte oficial do servidor (gate `--cov-fail-under=90` + `.coveragerc`) | **3421 passed / 16 skipped / 0 falha · cobertura 91,11% ≥ 90** (+52 sobre 1.40.0) |
| Guarda de versão | `test_version_policy` verde com a seção no topo + guarda `vMAIOR que a vigente` limpa (prosa de terceiros sem prefixo `v`, tag exata mora no compose) |
| Contrato vivo (antes de codificar) | Round-trip real: login 200 (JWT cru) e 403 = credencial rejeitada (fonte `os.ErrPermission`) → lista raiz `[]` → subir **200** → repetir **409** → `override=true` **200** → baixar por `/api/raw` **idêntico** → `DELETE` **204** (só minhas pastas de teste) → raiz `[]` de novo; disco e `GET /health` públicos conferidos |
| Provas vivas (pós-deploy) | ver `README_VERSAO` §1.41.0 (actions executadas contra a caixa real do dono) |

## [1.40.0] — FLATNOTES INTERLIGADO: O SISTEMA ANOTA E CONSULTA O CADERNO DO DONO 🜂 (2026-10-18)

> **Bump MINOR aprovado pelo dono em 18/10 ("ligar")** — 1ª ferramenta da
> série de análises que ele ordenou (FlatNotes → File Browser → Calibre,
> "uma por vez" §146). Escopo fechado por mim e por ele aprovado:
> **2 actions + check de saúde + patch v5.5.5 + testes**. O check de saúde
> já existia (`tool_flatnotes` no `FERRAMENTAS_NOMAD`, porta 8200 — o
> monitor de 9/9 nunca saiu); o que nasce aqui é a **fiação**: o sistema
> passa a escrever e perguntar no caderno `.md` do dono. Caderno sem
> banco de dados, sem login (só Tailscale), notas numa pasta plana que
> **já viaja nos snapshots das 2 HDs** desde a v1.39.3.

| Peça | Entrega |
|---|---|
| **`integrations/flatnotes.py` (novo)** | Cliente `FlatNotesClient` no molde do Kiwix (transporte injetável, fábrica lazy cacheada, `OD_FLATNOTES_URL` com default local). **Contrato apurado ao vivo ANTES de codificar** (18/10 — `openapi.json` do próprio container + round-trip completo: criar → repetir → buscar → ler → apagar a minha nota de teste) e **revalidado na v5.5.5** (rotas idênticas, 200/409/200 de novo). Erros honestos tipados: `flatnotes_indisponivel`, `flatnotes_timeout`, `flatnotes_falhou`, `flatnotes_parametro_invalido`, `flatnotes_ja_existe`, `flatnotes_nao_encontrada`, `flatnotes_resposta_invalida`. |
| **409 = recusa honesta** | Título repetido devolve **409** do FastAPI ("A note with the same title already exists.") → `flatnotes_ja_existe` com a saída declarada na própria mensagem. **Sobrescrever é flag explícita** (`sobrescrever=false` por padrão) que vai pelo `PATCH /api/notes/{title}` e vem **declarada na resposta** (`sobrescrito=true`) — o conteúdo original só sai com pedido explícito, régua de "nada apagado por acidente". |
| **Destaques HTML → texto limpo** | `GET /api/search` devolve `contentHighlights`/`titleHighlights` com `<b class="match term0">` — marcador do flatnotes **não é** o `<b>` do Telegram e estouraria o parse de lá; limpos com `regex + html.unescape` (zero dependência nova, resposta de chat é texto puro). `term=*` lista tudo (contagem do status); `[]` é **resposta honesta**, não erro (caderno vazio é estado normal). Título com `/` recusado na camada da API (vira caminho de arquivo `.md` lá no container — validar antes é mais honesto que descobrir o 404 depois). |
| **3 actions (categoria `flatnotes`, só admin)** | `flatnotes_status` (auth, nº de notas, última editada) · `flatnotes_anota` (título + conteúdo markdown, `sobrescrever=false`) · `flatnotes_busca` (texto livre, `limite=10`, trecho limpo do que casou). Nascem admin-only **por construção** (`permission=nome da action`; a lista `user` é explícita e não foi tocada). **NÃO existe action de apagar**: o `DELETE` da API fica de fora do catálogo — teste `test_nenhuma_action_de_apagar_no_catalogo` fixa a régua. |
| **Capability + contagem** | Bloco `flatnotes-caderno` (fase v1.40.0) no `core/capabilities.py` com o contrato vivo escrito. **106 → 109 actions** em todos os lugares que contam: `EXPECTED_CATEGORIES` ganha `"flatnotes": 3`, 23 asserts de contagem, docstrings do pacote e o site. |
| **Patch da ferramenta** | `docker/tools-compose.yaml`: `dullage/flatnotes:v5.5.4` → **`v5.5.5`** (refresh de deps do upstream: uv + Python 3.13 — sem mudança de contrato, comprovado revalidando as rotas na imagem nova). Container recriado no ar; pasta `/data` bind que já entra nos snapshots. |
| **Testes** | `tests/test_flatnotes.py` **+40**: fixtures fiéis às capturas vivas (Note, 409 com `detail`, busca com destaques HTML, config `authType=none`, 404), ordem dos métodos/URLs das 3 chamadas do status, 409 que **para na 1ª chamada** (nunca tenta PATCH por conta própria), PATCH com título URL-encoded, limites da busca (0→1, estouro→50), erros de rede/JSON, `_transporte` real (GET sem corpo, POST com JSON, HTTPError como resposta), fábrica lazy + permissão (user negado ×3, admin executa) e a prova de que não há action de apagar. |
| **Bump 9/9** | `.env` `OD_VERSION=1.40.0` · capabilities fallback · `_APP_VERSION_CODE` **2075 → 2076** · pubspec · site (versão ×3, Actions 109, Testes 3.369) · CHANGELOG · README_VERSAO · ANALISE · APKs. |

| Validado | Resultado |
|---|---|
| Suíte do servidor (gate 90%) | **3369 passed / 16 skipped** (+40 sobre 1.39.3), cobertura **95,59%** |
| Guarda de versão | `test_version_policy` verde após a seção existir + guarda `vMAIOR que a vigente` limpa (prosa de terceiros sem prefixo `v`, como a casa faz) |
| Contrato vivo (antes de codificar) | Round-trip real v5.5.4: POST 200 → POST 409 → busca `term=`/`term=*` → GET ler 200/404 → DELETE limpo (minha nota de teste saiu; caderno ficou `[]` de novo) |
| Contrato vivo (imagem nova) | v5.5.5: 200/409/200 (PATCH), config `authType=none`, **rotas idênticas** às da v5.5.4 |
| Provas vivas (pós-deploy) | ver `README_VERSAO` §1.40.0 (actions executadas contra o caderno real do dono, `/health` 24/24, `/actions` 109) |

## [1.39.3] — SNAPSHOT DO SISTEMA NAS DUAS HDs EXTERNAS 🜂 (2026-10-17)

> **Bump PATCH fechando a pendência do dono de 16/10 ("2 snapshots p/ HD
> externo"):** o backup tar local (§3.6) dizia no próprio docstring
> *"pensado para o dono copiar para um HD externo"* — a cópia era MANUAL.
> Agora o sistema grava **sozinho**, todo dia, em **cada uma** das duas
> HDs, via `rsync --link-dest`: a 1ª rodada leva tudo (~5 GB) e as
> seguintes só o que mudou, com inalterados virando **hardlink** (não
> duplica espaço). O **3D do dono é a primeira fonte da lista** (linha
> vermelha do TODO: entra em TODO snapshot). No mesmo dia as duas HDs
> ganharam fstab unificado (UUID + `noatime` + `nofail`) e dono
> `alex` — grava sem administrador, `FSTAB_OK` do dono.

| Peça | Entrega |
|---|---|
| **`core/hd_backup.py` (novo)** | Serviço **POR HD** (`hd_midias` → `/home/alex/dados`, `hd_arquivos` → `/mnt/Arquivos`) interface-par-a-par com `BackupService` (`cfg/tick/snapshot/check_saude/registrar_no_health`) — por isso plugar na lista do `build_backups()` trouxe loops, bloco `backup` do `/dashboard/stats` e checks do `/health` **de graça**, sem ramificação nova. Knobs: `OD_HD_SNAPSHOT=0` (desliga), `OD_HD_HORA` (03:40), `OD_HD_ALVOS` (`Rótulo=/caminho`), `OD_HD_PASTA`, `OD_HD_DIARIOS` (7), `OD_HD_SEMANAIS` (8). |
| **O que entra / não entra** | Fontes: **`/home/alex/3D` PRIMEIRO** (1,2 GB, linha vermelha), repo inteiro (`.env` + git + **capturas**), `omegadrakon-tools`, `/srv/omegadrakon`, `/etc/fstab`. Exclusões justificadas no docstring: `.venv` (recriável), `backups/` (tars têm retenção própria), `data/vector_memory` (RAG reconstruível), **zim 14 GB** (rebaixável pela action `nomad_wikipedia_zim_download`), **heap_dumps 2,8 GB** (artefato da era do OOM — fica no disco, só não viaja), `__pycache__`/`*.pyc`/`.part`. |
| **SQLite no ponto** | `homebox.db` e `db.sqlite3` do Vaultwarden copiados pelo **backup API do sqlite3** (ponto consistente, WAL consolidado) e **excluídos do rsync** — cópia rasgada de banco é restore que não abre. Bug clássico pego pelos testes: `destino / origem` com origem absoluta — o `/` vence no pathlib e o destino vira o **próprio banco** (backup de um banco nele mesmo trava para sempre). |
| **Verdade por alvo** | Camada nova `alvo_ausente` (`os.path.ismount` — o `nofail` do fstab exige conferir montagem, não existência de pasta): HD desplugada ⇒ skip honesto, check **degrada com "HD desconectada — plugue que o catch-up roda sozinho"** e a próxima conexão dispara sem pedir nada; a outra HD segue intacta (janela, estado, falhas e push **por HD**). |
| **Retenção** | Reusa `calcular_retencao` do tar com **sufixo vazio** — adição retrocompatível em `core/backup.py` (`_nome_re`/`timestamp_do_nome`/`calcular_retencao` ganharam `sufixo` com default idêntico; testes do tar verdes). Nome fora do padrão **nunca** entra na lista de remoção (diretório do dono intocável); `.tmp_` órfão de run interrompido limpo aos 6 h. Publicação atômica `.tmp_* → rename`. |
| **Cards no Status** | Linhas genéricas `hd_*` no JS do painel: rótulo do dono · último snapshot · bytes, **"HD fora"** quando `montado=false` — nunca verde de mentira. |
| **Testes** | `tests/test_hd_backup.py` **+33**: 6 camadas de decisão **pura** (prova: caminhos inexistentes decidem), executor **rsync real** (estrutura `-R`, exclusões, ponto SQLite, atômico), **2ª rodada por hardlink** (inalterado = mesmo inode; mudado = novo sem destruir o velho; removido da fonte ausente no novo e intacto no antigo), retenção intocável, as 4 verdades do check, push com cooldown de 6 h, fiação do launcher (HD quebrado não derruba os tars). |
| **Bump 9/9** | `.env` `OD_VERSION=1.39.3` · capabilities fallback · `_APP_VERSION_CODE` **2074 → 2075** · pubspec · site · CHANGELOG · README_VERSAO · ANALISE · APKs. |

| Validado | Resultado |
|---|---|
| Suíte do servidor (gate 90%) | **3329 passed / 16 skipped** (+34 sobre 1.39.2), cobertura **95,57%** |
| Guarda JS | `node --check` dos scripts do painel (bloco `hd_*` novo) verde pela suíte |
| Provas vivas (pós-deploy) | 1ª rodada real **5.268.052.376 bytes nas 2 HDs** (3D 1,2 GB / 345 itens + capturas dentro); **2ª rodada em 4,2 s** com `--link-dest` (mesmo inode em `.stl` inalterado; custo incremental **31 MB** — o `du` conta o inode uma vez); `/health` **24/24** (checks `hd_*` up: "snapshot_od-2026-10-17_2306, 4.91 GB"); `stats.backup` com **4 chaves**; recibo dos **5 ilegíveis** no `info.json`; `/app/version` **1.39.3/2075**; APK `versionCode=2075` (aapt); **E2E vivo: 35 provas, 0 falhas** |

## [1.39.2] — CONCERTO DUPLA: HERÓI SEM CSS (TEXTO COMUM) + RATE_LIMITED NAS PÁGINAS 🜂 (2026-10-17)

> **Bump PATCH (dois defeitos reportados pelo dono em 17/10, ambos meus):**
> (1) *"o herói não aparece mais como banner, está como texto comum"* —
> a injeção do CSS do formato **nunca aconteceu**: o `_com_tema`
> injetava o JS primeiro e o guarda do CSS (`if "od-formato-orion" not
> in html`) via a marca que o próprio JS carregava no comentário e
> pulava o CSS. O markup chegava pelado em `/dashboard` **e** `/admin`
> desde o deploy da v1.39.1. O E2E e o teste checavam a *marca* (presente
> no JS) e não as *regras* `.od-hero {` — olho cego que agora está
> tapado. (2) *"rate_limited quando tento abrir as páginas, tenho que
> atualizar para sumir"* — o limitador (30 req/min por IP, isentando só
> `/admin*`) contava cada request de abertura de página (~10 por
> `/dashboard`: HTML, ícones, auth, dados, chip do herói) e duas
> aberturas rápidas estouravam a janela.

| Peça | Entrega |
|---|---|
| **CSS do formato de volta** | Marcas **separadas por injeção**: `od-formato-orion-css` (comentário do CSS) e `od-formato-orion-js` (comentário do JS), cada guarda vigiando a **própria** marca; CSS injetado **antes** do JS (mesma ordem do tema). Herói voltou a ser banner no `/dashboard` e no `/admin`. |
| **Navegar nunca cai no limiter** | `_check_rate_limit` isenta: GET de shells de página (`/`, `/chat`, `/dashboard`), `/site/*` (assets) e `/app/version` (chips do app/site). **Seguem contados** o que faz trabalho: `/health` (probes ao vivo), `/message`, `/executa`, `/auth/*` (superfície de força-bruta) — o limite de 30/min não foi afrouxado, só parou de contar o pedido do documento. |
| **`/health` com cache curto (8s)** | O agregado roda os **22 checks ao vivo** (9 probes docker) e os chips o chamam em **toda abertura de página** — sem cache, cada F5 do dono disparava 22 probes. Rajadas compartilham a mesma rodada; o agregado nunca tem mais de 8s de idade (o notifier continua no seu próprio ciclo). |
| **`/admin` sem busca dupla** | O herói do `/admin` é alimentado pelo `loadSystem` (bandeira `odFormatoGerenciado`, lida no DOMContentLoaded) — o JS injetado não repete health/stats/actions que a página já buscou (−3 requests por abertura do painel). |
| **Testes** | `test_api.py`: `test_navegar_nunca_cai_no_limiter` (12 aberturas de página com limite=3, `/health` segue dando 429 no 4º) + travas novas no formato (**regras** `.od-hero {`/`.od-kpis {` presentes, marcas css/js separadas, bandeira só no `/admin`); `test_health.py`: `test_health_tem_cache_curto_para_rajadas` (rajada = 1 rodada de probes; cache vencido >8s reexecuta, sem dormir). |
| **Bump 9/9** | `.env` `OD_VERSION=1.39.2` · capabilities fallback · `_APP_VERSION_CODE` **2073 → 2074** · pubspec · `site/index.html` · CHANGELOG · README_VERSAO · ANALISE · APKs. |

| Validado | Resultado |
|---|---|
| Suíte do servidor (gate 90%) | **3295 passed / 16 skipped** (+2 testes sobre 1.39.1) |
| Guarda JS | `node --check` com `_com_tema` injetado (tema + formato): **OK** |
| Provas vivas (pós-deploy) | *preenchidas abaixo na prova do deploy* |

## [1.39.1] — FORMATO ÓRION NO PAINEL DE TODOS + FONTE ÚNICA 🜂 (2026-10-17)

> **Bump PATCH (extensão do formato + refatoração de fonte única):** o
> dono, ao ver o `/admin` no formato Órion, ordenou: *"como esse painel
> não causa qualquer problema ao sistema … coloca ele no topo do
> dashboard para todos os usuários"* — o **MESMO cabeçalho** (saudação
> por período com o nome de quem entrou, pill ONLINE/DEGRADADO, chips,
> relógio GMT-3, mini-card de saúde) e a **MESMA faixa de 4 KPIs** agora
> abrem o `/dashboard` de **todo usuário logado**. No caminho, o formato
> deixou de viver duplicado dentro do `/admin` e virou **fonte única
> injetada pelo `_com_tema`** — mesma arquitetura do tema claro/escuro
> (uma fonte, três páginas).

| Peça | Entrega |
|---|---|
| **`/dashboard` — formato para TODOS** | Herói + KPIs no topo, antes de "Uso da conta": saudação com o **próprio nome** de quem entrou (`/auth.me`), versão real (`/app/version`, rota pública), pill do `/health`, relógio GMT-3 vivo, mini-card de saúde e os 4 KPIs de sistema (actions · stack · checks · uptime). `/dashboard/stats` que devolve **403 para usuário comum vira "—"** (nada de verde de mentira); **as seções administrativas continuam atrás do papel admin** (só o formato viaja). |
| **Fonte única do formato** | `_FORMATO_ORION_CSS` + `_FORMATO_ORION_JS` (IIFE com `window.odFormato`: `nome`/`pintar`/`atualizar`) saem do HTML do `/admin` e passam a ser injetados pelo `_com_tema` com o **princípio idempotente do tema** (marca `od-formato-orion`; marcado também no JS — segunda chamada não duplica). O `/admin` chama `window.odFormato.pintar()` no refresh do `loadSystem`; o `/dashboard` busca sozinho (health + stats + actions com a sessão do localStorage); o `/chat` recebe a injeção **inócua** (sem `#odOla` o JS sai cedo e o markup não existe lá). Tinta só nas variáveis do tema → **claro e escuro** sem paleta duplicada. |
| **Bump 9/9** | `.env` `OD_VERSION=1.39.1` (fonte real; o fallback do capabilities é só padrão) · `capabilities.py` fallback **1.39.0 → 1.39.1** · `_APP_VERSION_CODE` **2072 → 2073** · `app/pubspec.yaml` · `site/index.html` (badge do herói + card do APK) · CHANGELOG · README_VERSAO · ANALISE · APKs rebuildados. |
| **Testes** | `tests/test_api.py`: **+1** `test_dashboard_no_formato_orion_para_todos` (markup+ids do herói/KPIs no `/dashboard`, **marca da fonte única** nas 3 páginas, **um único `<script>`**, `/chat` sem cabeçalho). Os testes do v1.39.0 (herói do admin, fontes honestas, script único, tema idempotente, `node --check` cru e injetado) seguram a refactor sem mudança de palavra. |

| Validado | Resultado |
|---|---|
| Suíte do servidor (gate 90%) | **3293 passed / 16 skipped** (+1 teste sobre 1.39.0) · gate **91,08%** |
| Guarda JS | `node --check` do script com `_com_tema` injetado (tema + formato): **OK** |
| Provas vivas (pós-deploy) | *preenchidas abaixo na prova do deploy* |

## [1.39.0] — PAINEL E SITE NO FORMATO ÓRION + MONITOR 9/9 🜂 (2026-10-17)

> **Bump MINOR (interface do dono + correção de monitor):** o dono
> analisou as **2 capturas do Sistema Órion** (PMESP) depositadas **sem
> instrução** em `analise/` e definiu o uso delas: *"a captura do orion
> é uma ideia de como a tela ficaria, gostei do formato usado por
> eles"* — formato aprovado para **painel + site** (escolha dele, em
> resposta à pergunta do sistema). O `analyse` do formato: herói de
> saudação, faixa de KPIs com selo de ícone gradiente, mini-painéis
> vivos (relógio/clima), barra lateral colapsável — levamos o FORMATO
> com a identidade do Omega Drakon (a identidade policial ficou de
> fora, e o **dragão segue proscrito** pela guarda da v1.21.2 —
> `assert "🐉" not in html` pegou o herói novo na suíte e ele foi para
> o símbolo oficial). Duas mentiras do caminho corrigidas: o monitor
> `nomad_tools` ficou com **8** depois da reativação do Homebox
> (`/health` dizia 8/8 com **9 serviços no ar**) e o site anunciava
> números velhos (**78 actions / +2.300 testes / v1.38.0**).

| Peça | Entrega |
|---|---|
| **Painel `/admin` — formato Órion** | **Herói**: símbolo oficial + versão + pill **ONLINE/DEGRADADO** (do `/health` real), **saudação por período com o nome do dono** (`/auth.me`, `America/Sao_Paulo`), data por extenso, chips build/uptime/stack e dois mini-painéis **vivos**: **relógio GMT-3 com segundos** (tique 1s) e **Saúde** (checks ok/total + status). **Faixa de 4 KPIs** com selo de ícone gradiente (azul/laranja/roxo/verde): **Actions** (`/actions.count`), **Stack Nômade** (`nomad_tools`), **Checks** (`/health.checks`), **Uptime** (`fmtUptime`) — tudo lendo as **MESMAS fontes das seções**, sem fonte paralela; sem resposta o campo fica "—" (**nada de verde de mentira**) e falha do herói nunca derruba o painel (try/catch vazio). Tinta só nas variáveis do tema → funciona **claro e escuro** sem paleta duplicada. JS novo **dentro do script único** (a guarda `node --check` recorta primeiro→último `<script>`; verificado cru **e** com `_com_tema` injetado). |
| **Site — chip vivo + números reais** | Badge do herói com **versão real** (`/app/version`, rota **pública**) e **ponto de estado** verde/vermelho (`/health`) — **acinzentado (estado desconhecido) até a resposta**, via `od-nav.js` **comportamento 4** (idempotente: só escreve se os elementos existem; as outras 10 páginas intactas). Topo do index corrigido para a realidade: **106 actions · 3.290 testes · 9 ferramentas no ar** (os velhos 78 / +2.300 / "42 capacidades" mentiam); frase do Changelog no index deixou de prometer um range que `historico.html` (parado em 1.25.0 — nova pauta no TODO) não entrega. |
| **Monitor `nomad_tools` — bug corrigido** | `FERRAMENTAS_NOMAD` **8 → 9**: **Homebox reencaixado** (porta 8470) — após a reativação no v1.38.0 o monitor continuou com 8, então `/health` e `/dashboard/stats` diziam **8/8 com 9 serviços no ar** (achado enquanto se apurava o formato Órion; a guarda do teste que proibia Homebox no catálogo foi cumprida pela própria decisão do dono). Docstrings e comentários do módulo atualizados (9 ferramentas, 9 probes/min). |
| **`core/capabilities.py`** | Fallback **1.38.0 → 1.39.0** + capability `nomad-tools`: "**9 containers Docker**" com **Homebox na lista** (o texto ainda anunciava *"Homebox fora do ar desde 17/10"*). |
| **Bump 9/9** | `.env` `OD_VERSION=1.39.0` (fonte real; o fallback do capabilities é só padrão) · `capabilities.py` (fallback+phase) · `_APP_VERSION_CODE` **2071 → 2072** · `app/pubspec.yaml` · CHANGELOG · README_VERSAO · ANALISE_PROJECT_NOMAD (linha nova) · TODO (§1: 9 serviços, situação 17/10 noite; tema residual reiterado; `historico.html` registrado) · APKs rebuildados. |
| **Testes** | `tests/test_nomad_tools.py`: **12 ajustes** 8→9 (contagens, nomes de teste, conjunto de checks com `tool_homebox`, resumos do stats) — a guarda "Homebox fora" virou "Homebox dentro **por decisão do dono**". `tests/test_api.py`: **+2 testes** — `test_painel_admin_no_formato_orion` (herói+KPIs presentes, fontes honestas, **um único `<script>`**) e `test_site_index_chip_vivo_e_numeros_reais` (ids do chip vivo + números reais + trava anti-regressão dos velhos 78/+2.300). `tests/test_registry.py` (guarda do dragão) **pega o herói novo e ele obedece** — emoji trocado pelo `simbolo_minimo.png`. |

| Validado | Resultado |
|---|---|
| Suíte do servidor (gate 90%) | **3292 passed / 16 skipped** (+2 testes sobre 1.38.0) · gate **91,09%** |
| Guarda JS | `node --check` do script do `/admin` cru **e** com `_com_tema`: **OK** · `od-nav.js`: **OK** |
| Provas vivas (restart, NRestarts=0, journal 0 erros) | `/app/version` **1.39.0/2072** (sha `89532bd4…`) · `/health` **22 checks** (novo `tool_homebox`) · **`/dashboard/stats` nomad_tools = 9/9, fora=[]** (o bug do 8/8 morto) · `/actions` **106** · `/admin` com herói+KPIs e **um único `<script>`** · as 3 páginas com tema intacto · site com chip vivo e números reais |
| **E2E vivo (`/tmp/opencode/e2e_orion1390.py`, modo só-verifica)** | **32 provas · 0 falhas** — versão, saúde (9 `tool_*` incluindo `tool_homebox`), stats 9/9, catálogo, DOM do herói/KPIs, script único, guarda do dragão, símbolo oficial, tema nas 3 páginas, chip vivo do site, `od-nav.js`/`od.css` |

## [1.38.0] — INVENTÁRIO DO DONO: HOMEBOX INTERLIGADO (4ª, USO DEFINIDO PELO DONO) 🜂 (2026-10-17)

> **Bump MINOR (capability nova + WRITE):** quarta e última da fila de
> ferramentas, com **uso DEFINIDO pelo dono** em 17/10 (*"me ajudar a
> cadastrar as ferramentas e peças que possuo... sabendo disso, sugerir
> montagens dizendo as peças que possuo e as que preciso"* — ex. dele:
> Raspberry Pi 4 + ESP-01S/DHT22 → estação meteorológica). O sistema
> agora **CONSULTA E CADASTRA** no Homebox self-hosted (container
> `od-homebox` **reativado**, sysadminsmedia/homebox 0.26.2, só
> `127.0.0.1:8470`, banco do desligamento de 17/10 **preservado** —
> nada apagado) pelas actions `homebox_status`/`homebox_busca`/
> `homebox_listar`/`homebox_detalhar`/`homebox_criar`/`homebox_atualizar`
> (categoria `homebox`, só admin) — **nenhuma action apaga**: só lê e
> cadastra (régua do dono). Primeira interligação do catálogo com
> escrita de verdade.

| Peça | Entrega |
|---|---|
| **Bootstrap** | Conta do sistema `omega-drakon@omegadrakon.local` (senha de 32 chars gerada, **nunca impressa**) + **API key estática** `omega-drakon` (sem expiração) no `.env` (`HBOX_API_EMAIL`/`HBOX_API_PASSWORD`/`HBOX_API_KEY`/`OD_HOMEB_URL`); conta órfã de um bootstrap interrompido removida do SQLite via `chown` temporário pelo próprio container (sem sudo); **cofre: allowlist +2 e espelho 14/14 conferem**. |
| **`integrations/homebox.py` (novo)** | `HomeboxClient` em **stdlib puro** (`urllib`+`json`; zero dependência nova). Contratos **apurados ao vivo antes de codificar** — swagger do próprio container (`/swagger/doc.json`, 67 rotas, Swagger 2.0) + `routes.go` da tag v0.26.2: **`/v1/entities` é o inventário** (NÃO `/items` — 404 apurado), envelope paginado `{page,pageSize,total,items}`, `POST /v1/entities` (`EntityCreate`: name*, quantity, description, entityTypeId, tagIds), **PATCH parcial de verdade** (só 5 campos; `quantity` é um deles), **PUT que SUBSTITUI o objeto** (`name` obrigatório; notas/descrição/preço passam por **GET+merge+PUT**), `/v1/entity-types`, `/v1/tags`, `/v1/groups/statistics`. **Achados de auth (ambos apurados ao vivo):** session token do login **NÃO** vale como `Authorization: Bearer` (middleware lê o cookie `hb.auth.token`) e a **API key vale EXATAMENTE como Bearer** (e não como cookie) — caminho estático do sistema. **Erros honestos tipados:** `homebox_indisponivel`, `homebox_timeout`, `homebox_falhou`, `homebox_nao_autenticado`, `homebox_nao_encontrado`, `homebox_parametro_invalido`, `homebox_resposta_invalida`. **LAZY**: `client_padrao()` cacheada (`OD_HOMEB_URL`+`HBOX_API_KEY`) — ferramenta fora do ar degrada a ação, nunca o boot do od-core. |
| **Defeitos achados ao vivo (E2E 1ª execução) e corrigidos** | (1) `PUT` com `parentId:""` → **HTTP 500 "Unknown Error"** do fork: opcionais agora só entram quando **presentes**; (2) id fora de UUID → API devolve **400 `invalid route key`**, não 404: validação **antes** da chamada com mensagem acionável (*"use o id de homebox_busca"*) + 404 honesto para UUID inexistente; (3) tags inexistentes são criadas com **declaração** na resposta (`tags_criadas`/`tipo_criado`) — cadastro sem fricção, nunca silencioso. |
| **`tools/actions/actions.py`** | `_homebox_op` + 6 actions: `homebox_status` (versão + totais), `homebox_busca` (`query`, `quantidade` 1–100), `homebox_listar` (filtro por tags nominais — **sem criar**), `homebox_detalhar` (id UUID), `homebox_criar` (nome, quantidade, tipo, descrição, notas, tags, preco, criar_tipo/criar_tag), `homebox_atualizar` (quantidade pura → PATCH; o resto → PUT cheio). |
| **`core/capabilities.py`** | Nova capability **`homebox-inventario`** (integrations, **ATIVA**) + fallback 1.38.0. |
| **Catálogo de actions** | 100 → **106 actions** (categoria `homebox: 6`) — contagens em 4 arquivos de teste + docstring do pacote. |
| **Testes** | **`tests/test_homebox.py` novo — 52 testes** com fixtures fiéis ao swagger/capturas vivas (envelope paginado, EntityOut 34 campos, tipos/seed): mapeamento, cliente (status/busca/listar/detalhar/criar/atualizar + PUT-seguro + UUID + todos os erros), transporte urllib, fábrica lazy, actions (degradação) e catálogo (**nenhuma action apaga** + negação para papel comum). |
| **versionCode** | 2070 → **2071** (política 9/9; APKs rebuildados, aapt2 confere 1.38.0/2071). |

| Validado | Resultado |
|---|---|
| Suíte do servidor (gate 90%) | **3290 passed / 16 skipped** (+4 testes sobre 1.37.0) · gate **91,07%** |
| Prova viva (restart, NRestarts=0) | `/health` 21 checks · `/actions` **106** com as 6 `homebox_*` · `/app/version` **1.38.0/2071** |
| **E2E real pelo `/executa`** (20 provas) | `homebox_status` (v0.26.2) → **cadastro REAL das peças do dono**: Raspberry Pi 4 + ESP-01S com DHT22 (tipos `Placa de desenvolvimento`/`Módulo sensor` e tags **criados e declarados**) → `homebox_busca("raspberry")`/`("dht22")` 1 hit cada → busca vazia `ok=True, []` → `homebox_listar` = as 2 peças → `homebox_detalhar` → `homebox_atualizar` (nota *"candidato a estação meteorológica"* via PUT completo) → 404 honesto (UUID inexistente) → id torto validado antes → totais coerentes (2 itens). **Guarda anti-duplicação** no E2E: reruns verificam sem cadastrar de novo. |

## [1.37.0] — ACERVO OFFLINE: KIWIX INTERLIGADO (3ª DAS 3 — FILA COMPLETA) 🜂 (2026-10-17)

> **Bump MINOR (capability nova):** terceira e última da fila aprovada
> pelo dono em 17/10 (*"aprovado fase 3"*) — **Vaultwarden ✅ → Stirling
> ✅ → Kiwix ✅**. O sistema agora **consulta a Wikipédia offline**
> (container `od-kiwix`, kiwix-serve 3.8.1, `wikipedia_en_all_mini` de
> 12,5 GB / **18,1 M de artigos**, só `127.0.0.1:8090`, ZIM montado
> `:ro`) pelas actions `kiwix_status` / `kiwix_busca` / `kiwix_leitura`
> (categoria `kiwix`, só admin) — responde do acervo mesmo sem
> internet, pelo critério do dono: ferramenta só interessa se o
> **sistema** usa.

| Peça | Entrega |
|---|---|
| **`integrations/kiwix.py` (novo)** | `KiwixClient` em **stdlib puro** (`urllib` + `html.parser` + `xml.etree.ElementTree`; zero dependência nova). Contratos **apurados ao vivo antes de codificar** (a API do kiwix-serve 3.8 é **HTML/XML puro — sem JSON**, apurado: `/suggestions` vazio, `/search` ignorou `Accept: application/json`): `GET /catalog/v2/entries` (Atom/OPDS: id/título/idioma/artigos/mídias por ZIM), `GET /search?pattern=` (HTML com título+caminho+trecho+palavras), `GET /content/<zim>/<path>` (200 = artigo, 404 = inexistente; achado: `/A/<título>` só redireciona para cá). **Só leitura** (ZIM `:ro` — sem tela = sem ação); caminho invalidado contra `..`; texto extraído com parser próprio (script/style ignorados); **truncamento declarado** (`truncado=True` + `…[cortado]`); **busca vazia é resposta honesta** (`resultados=[]`), não erro; erros tipados: `kiwix_indisponivel`, `kiwix_timeout`, `kiwix_falhou`, `kiwix_parametro_invalido`, `kiwix_artigo_nao_encontrado`, `kiwix_resposta_invalida`. **LAZY**: `client_padrao()` cacheada (`OD_KIWIX_URL`, default local). |
| **`tools/actions/actions.py`** | `_kiwix_op` + 3 actions: `kiwix_status` (acervos + total de artigos), `kiwix_busca` (`pattern`, `quantidade` 1–25), `kiwix_leitura` (`caminho`, `max_chars` 200–100k). |
| **`core/capabilities.py`** | Nova capability **`kiwix-offline`** (integrations, **ATIVA**) + fallback 1.37.0. |
| **`.env`** | `OD_VERSION=1.37.0` + `OD_KIWIX_URL=http://127.0.0.1:8090` (config, não é segredo). |
| **Catálogo de actions** | 97 → **100 actions** (categoria `kiwix: 3`) — contagens em 4 arquivos de teste + docstring do pacote. |
| **Testes** | **`tests/test_kiwix.py` novo — 39 testes** com fixtures **fiéis às capturas vivas** de 17/10 (Atom, HTML da busca com entidades, artigo com script/style): parsers, cliente (status/busca/leitura + todos os erros + truncamento + `..`), transporte urllib (HTTPError **é** resposta; rede/timeout tipados), fábrica lazy e catálogo (schemas + **negação para papel comum**). |
| **versionCode** | 2069 → **2070** (política 9/9; APKs rebuildados, aapt2 confere). |

| Validado | Resultado |
|---|---|
| Suíte do servidor (gate 90%) | **3238 passed / 16 skipped** (+40 testes) |
| Prova viva (PID novo, NRestarts=0) | `/health` up · `/actions` **100** com as 3 `kiwix_*` · `/app/version` **1.37.0/2070** · journal 0 erros · boot continuando ~3s (v1.36.1) |
| **E2E real pelo `/executa`** | `kiwix_status` (**18.095.848 artigos**, `wikipedia_en_all_mini`, eng) → `kiwix_busca("omega")` → hits reais com trecho → `kiwix_leitura` de um hit (texto limpo, `truncado=False`) → 404 honesto (`kiwix_artigo_nao_encontrado`) |

## [1.36.1] — BOOT DO RAG EM PARALELO + REMOÇÕES EM LOTE (CORREÇÃO DO BOOT LENTO) 🜂 (2026-10-17)

> **Correção (PATCH) na esteira do pedido do dono** ao ver o boot de 179s:
> *"porque no boot, ele não pode entrar depois e rodar em paralelo"*.
> Apurado o culpado real **antes** de mexer: não era embedding (o provider
> é hash) — era o store reescrevendo o **JSON inteiro a cada remoção**:
> delete unitário × 442 chunks substituídos = **O(n²) de I/O** (~0,4s por
> chunk, aritmética fecha com os boots históricos). Dois consertos, um por
> cima do outro: remoções em **lote** (uma escrita só) e **sync em
> background** — o boot carrega o índice persistido, serve, e a
> re-sincronia completa em paralelo.

| Peça | Entrega |
|---|---|
| **`memory/vector.py`** | `delete_many(doc_ids)` — lote com **uma persistência** no fim (backends JSON e DB), espelhando o `add_many` que já era loteado (o próprio comentário do `rag.py` já denunciava o O(n²) do caminho unitário). |
| **`memory/rag.py`** | `sync()` apaga substituídos + órfãos em **lote** (`delete_many` único antes do `add_many`); estado de sincronização novo (`pendente`/`sincronizando`/`pronto`/`falhou`) + `sync_status()`; `sync_em_background()` (thread **daemon**, duplo-start devolve a thread em curso, falha vira estado `falhou` + warn — nunca derruba o core); `dump()` expõe `sync`. Janela de degradação honesta: consultas antes do fim do sync devolvem `""` (sem `_df` — o mesmo caminho de "sem corpus", já existente). |
| **`runtime/launcher.py`** | `build_rag()` **padrão background**: `store.load()` serve o índice já gravado e o boot segue — log `RAG ligado (Parte B NOMAD) \| sync em background`; `OD_RAG_SYNC_BACKGROUND=0` volta ao comportamento síncrono (fail-safe/testes). |
| **Testes** | **+11**: lote com uma escrita só (spy em `_persist`), nada-existente não persiste, backend DB, transição de estados, duplo start, degradação durante a janela com volta após o sync, falha → `falhou`, dump com sync. |
| **versionCode** | 2068 → **2069** (política 9/9; APKs rebuildados, aapt2 confere). |

| Validado | Resultado |
|---|---|
| Suíte do servidor (gate 90%) | **3198 passed / 16 skipped** (+11 testes) |
| Prova viva do boot (PID 976302, NRestarts=0) | **API no ar em 3,0s** (antes: 179s) — journal: `Database Layer` → `RAG ligado ... sync em background` (despachado em thread daemon, **antes** do boot terminar) → `API REST no ar`; sync de fundo completou em **2,0s** — o lote fez o sync tão barato que fechou antes da API; a ordenação "API antes do sync" só apareceria num sync maior, e a garantia estrutural (thread + `OD_RAG_SYNC_BACKGROUND=0`) é coberta por teste |
| Idempotência/janela | Sync de fundo completou com os números esperados; a janela de degradação (consultas devolvem `""` sem `_df`) e a volta após o sync são cobertas pelos testes novos |

## [1.36.0] — PIPELINE DE DOCUMENTOS: STIRLING PDF INTERLIGADO (2ª DAS 3) + ESPELHO DO COFRE 🜂 (2026-10-17)

> **Bump MINOR (capability nova):** segunda da fila aprovada pelo dono em
> 17/10 (*"começa a implantação da 2ª opção da fila, stirling"*) —
> **Vaultwarden ✅ → Stirling ✅ → Kiwix**. O sistema agora **opera o
> Stirling self-hosted** (s-pdf 2.13.1, escuta só `127.0.0.1:8400`, sem
> login) por 4 actions (`stirling_status` / `stirling_merge` /
> `stirling_split` / `stirling_compress`, categoria `stirling`, só
> admin) — **pipeline de documentos**: juntar, cortar e comprimir PDFs.
> Na mesma entrega, ordem do dono (*"coloque todas as senhas do .env no
> cofre"*): **as 12 credenciais do `.env` espelhadas no cofre** — cópia
> idempotente que **não tira nada do `.env`** (ele segue como bootstrap
> e o boot nunca depende do cofre).

| Peça | Entrega |
|---|---|
| **`integrations/stirling.py` (novo)** | `StirlingClient` em **stdlib puro**: `urllib` + `multipart/form-data` montado à mão no padrão de `HTTPTransport.build_multipart` (**zero dependência nova** — requirements continua puro). Contratos apurados **ao vivo antes de codificar**: OpenAPI 3.0.3 em `GET /v1/api-docs` (255 rotas do s-pdf 2.13.1) + chamadas reais (merge → `application/pdf` síncrono; page-count → `{"pageCount":2}`) — descoberta importante: a spec fica em **`/v1/api-docs`** (não `/v3`), o `/v3/api-docs` devolve o SPA. Campos **obrigatórios sempre enviados por nós** (nada depende de default do servidor); resposta só vira arquivo **depois da validação de mágica** (`%PDF`/`PK`) — 200 com HTML nunca grava; saída existente só com `substituir=True` (**nada apagado por acidente**); erros tipados honestos: `stirling_indisponivel`, `stirling_timeout`, `stirling_pdf_invalido`, `stirling_gigante`, `stirling_proibido`, `stirling_falhou`, `stirling_arquivo_ausente`, `stirling_diretorio_ausente`, `stirling_saida_ocupada`, `stirling_parametro_invalido`, `stirling_resposta_invalida`. **LAZY por desenho**: `client_padrao()` cacheada com `OD_STIRLING_URL` (default local) — ferramenta fora do ar degrada a ação, **nunca o boot**. |
| **`tools/actions/actions.py`** | 4 actions + `_stirling_op` (mapeia `StirlingError` → `{"ok": False, "error": ...}`): `stirling_status` (versão + estado), `stirling_merge` (2+ PDFs, caminhos separados por vírgula), `stirling_split` (pontos de corte `"2"`, `"2,5"`, `"5-9"`, `"all"` → PDF ou ZIP), `stirling_compress` (nível 1–9, alvo `"25KB"`/`"100MB"`, cinza) — todas com saída protegida. |
| **`vault_env_mirror.py` (novo, raiz)** | Espelho `.env` → cofre (pedido do dono): allowlist **explícita das 12 credenciais** (se nascer segredo novo fora dela, **avisa** em vez de deixar passar), `OD_MQTT_PASSWORD` pareado ao `OD_MQTT_USERNAME`, nota por chave (`TELEGRAM_BOT_LEGADO_TOKEN` marcado como **rotação §8.5 pendente**; `OD_VAULT_MASTER` como auto-referência cifrada com nota), verificação por `get`+comparação que **só imprime nome + confere/ERRO** — nenhum valor em log/transcrição. Reexecutável (`--check` só verifica); atualiza pelo mesmo nome, nunca duplica. |
| **`core/capabilities.py`** | Nova capability **`stirling-pdf`** (integrations, **ATIVA** — API v1, multipart stdlib, mágica antes de gravar, LAZY) + fallback de versão 1.36.0. |
| **`.env`** | `OD_VERSION=1.36.0` + `OD_STIRLING_URL=http://127.0.0.1:8400` (config, não é segredo). |
| **Catálogo de actions** | 93 → **97** (categoria `stirling: 4`) — contagens em `test_actions_catalog` (+ `EXPECTED_CATEGORIES`), `test_capabilities`, `test_orchestrator(×2)` e docstring do pacote `tools/actions`. |
| **Testes** | **`tests/test_stirling.py` novo — 49 testes**: multipart byte a byte (boundary, array `fileInput`, nome higienizado), transporte urllib (HTTPError **é** resposta; rede/timeout → erro tipado), cada operação com **todos** os ramos de erro + trava de saída + mágica, fábrica lazy (env → `.env` → default), actions (parse de lista com espaços, erro degradado) e catálogo (schemas + **negação para papel comum**). Cobertura do módulo: **97%**. |
| **versionCode** | 2067 → **2068** (política 9/9 — `.env`, `capabilities`, `pubspec`, `_APP_VERSION_CODE`, site ×4, CHANGELOG, README_VERSAO; APKs rebuildados e conferidos no aapt2). |

| Validado | Resultado |
|---|---|
| Suíte do servidor (gate 90%) | **3187 passed / 16 skipped** (cov 90,96%) — +49 testes novos (`test_stirling.py`) |
| Mutações (teste do teste) | **4/4 capturadas** (mágica de saída removida → 1 falha · trava de saída removida → 1 · timeout virando `indisponivel` → 1 · redução antes/depois invertida → 1), restauração **bit-exata conferida por sha256** — com lição honesta registrada: um `.pyc` temporário com **mtime+size idênticos** ao fonte mascarou a restauração na suíte intermediária (bytecode mutado servido do cache); `.pyc` invalidado e suíte final verde |
| Prova viva (PID 914141, NRestarts=0) | `/health` **up · 21 checks · tools 8/8** · `/actions` **97** com as 4 `stirling_*` · `/app/version` **1.36.0 / 2068** (sha `b4a7247d…` == APK publicado) · journal **0 erros** (só o alerta esperado `key=restart`) |
| **E2E do pipeline real** (pelo `/executa` de produção) | `stirling_status` (**2.13.1, UP**) → `stirling_merge` de 2 PDFs (**1234 B**, sha conferido) → **page-count direto no container = 2** → repetir sem `substituir` → **`stirling_saida_ocupada` + arquivo intacto** → `stirling_split` do merged (**ZIP com `junto_1.pdf` / `junto_2.pdf`**) → `stirling_compress` de 177 KB (**177072 → 5444 B, −96,9%**) com antes/depois honestos |
| **Espelho do cofre** | `vault_env_mirror.py` rodado na entrega: **12/12 conferem**, cofre do sistema com **12 itens**, nenhum valor impresso |

## [1.35.0] — COFRE DO SISTEMA: VAULTWARDEN INTERLIGADO (1ª DAS 3 FERRAMENTAS) 🜂 (2026-10-17)

> **Bump MINOR (capability nova):** primeira da fila aprovada pelo dono em
> 17/10 (*"prossiga com o cofre"*) — **Vaultwarden → Stirling PDF →
> Kiwix**. O sistema agora **lê e escreve segredos no cofre** por 4
> actions (`vault_status` / `vault_list` / `vault_get` / `vault_set`,
> categoria `vault`, só admin). Conta de **SERVIÇO separada**
> (`od-sistema@omegadrakon.dev`, criada pelo fluxo de registro com
> crypto oficial já provado em 15/10 — signups abertos por segundos e
> **fechados e verificados no mesmo ato**); a conta e a master **do dono
> nunca são usadas pelo sistema**.

| Peça | Entrega |
|---|---|
| **`integrations/vault.py` (novo)** | `VaultClient` sobre o CLI oficial `bw` **pinado 2025.12.1 + Node 22** — **apuração viva na entrega**: a prova de escrita com item no cofre derrubou o pin provisório 2026.8. Todos os 2026.x testados (2026.8 e 2026.10, em Node 18 **e** Node 22) **crasham decifrando cifras do Vaultwarden 1.36** com item no cofre (`invalid type: JsValue … expected a string`) — o drill de 15/10 só exercitou cofre **vazio**; ≥2026.9 ainda tem o bug de prelogin já registrado. Combo estáável via wrapper `~/.local/bin/bw` = **node22 + 2025.12.1 + `BITWARDENCLI_APPDATA_DIR` próprio** (`~/.local/share/bitwarden-cli`, nunca poluído pelas 2026.x), tudo instalado em `~/.local/opt` (**zero dependência em /tmp**). Ciclo completo provado: list/create/edit/delete + lista final `[]`. Senha só por `--passwordenv` (**env, nunca argv**), JSON de item só por **stdin base64**, sessão destravada **cacheada em memória** (thread-safe) com renovação **única** em sessão expirada (nunca em loop; criação jamais retentada às cegas). Erros tipados: `bw_ausente`, `vault_nao_configurado`, `vault_indisponivel`, `vault_master_invalida`, `vault_nao_autenticado`, `sessao_expirada`, `item_nao_encontrado`, `item_invalido`, `vault_timeout`, `bw_falhou`. **LAZY por desenho**: cliente nasce na 1ª ação — cofre fora do ar degrada a ação, **nunca o boot do od-core**. |
| **`.env` (configuração do cofre)** | `OD_VAULT_EMAIL` (conta de serviço), `OD_VAULT_SERVER` = **HTTPS** `https://nicky-server.tail1b1f51.ts.net:8443` (o SDK do bw **recusa HTTP** — nem `127.0.0.1` passa: `InsecureUrlNotAllowedError`; o HTTPS que já era o acesso do dono via Tailscale Serve resolve), `OD_VAULT_MASTER` (32 bytes, só no `.env` — nem argv, nem log, nem doc) e `OD_BW_BIN`. |
| **`tools/actions/actions.py`** | 4 actions `vault_*` + `_vault_op` (mapeia `VaultError` → resposta honesta `{"ok": False, "error": ...}`). `vault_list` devolve **só `id/nome/tipo`** — segredo **só** em `vault_get`; `vault_set` cria ou atualiza (mesmo nome = mesmo item, merge **preserva** campos não informados); `vault_status` = estado do bw + alcançabilidade da rede. |
| **`core/capabilities.py`** | Nova capability **`vault-cofre`** (categoria integrations, **ATIVA**): conta de serviço separada, sessão em memória, lista sem vazamento, LAZY. Fallback de versão = 1.35.0. |
| **Catálogo de actions** | 89 → **93** (categoria `vault: 4`) — contagens atualizadas em `test_actions_catalog` (+ `EXPECTED_CATEGORIES`), `test_capabilities`, `test_orchestrator(×2)`, docstrings do pacote. |
| **Testes** | **`tests/test_vault.py` novo — 33 testes**: sessão (cache, retry único, sessão morta, master errada, bw ausente, timeout, rede caída), operações (lista **sem vazamento** — 4 capturas de mutação provam; obter case-insensitive; guardar via stdin; merge preservador; apagar; status com/sem rede), fábrica LAZY (sem config → `None`; env lidera sobre `.env`), actions (shapes + erro mapeado + não-configurado degrada) e catálogo (4 actions, schemas, **negação para papel comum**). |
| **versionCode** | 2066 → **2067** (política 9/9 — `.env`, `capabilities`, `pubspec`, `_APP_VERSION_CODE`, site ×4, CHANGELOG, README_VERSAO; APKs rebuildados e conferidos no aapt2). |

| Validado | Resultado |
|---|---|
| Suíte do servidor (gate 90%) | **3138 passed / 16 skipped** (cov 90,90%) — +33 testes novos (`test_vault.py`) |
| Mutações (teste do teste) | **4/4 capturadas** (sessão sem cache → 1 falha · sem retry de sessão → 2 · lista bruta vazando segredo → 4 · item em argv → 1), restaurações **bit-exatas** |
| Prova viva (PID 840230, NRestarts=0) | `/health` **up · 21 checks · fora=nenhum · tools 8/8** · `/dashboard/stats` `nomad_tools total=8 up=8 fora=[]` · `/app/version` **1.35.0 / 2067** (sha `753c59af…` == APK publicado) · `/actions` **93 actions** com **`vault_status/vault_list/vault_get/vault_set`** · journal **0 erros** (menções "vault" = só o registro das 4 actions no boot) · **8 containers `od-*`** |
| **E2E no cofre real** (pelo wrapper de produção) | `vault_status` (conta de serviço, `locked`, alcança=true) → `vault_set` **criado** → `vault_list` **só id/nome/tipo** → `vault_get` (case-insensitive, senha **confere**) → `vault_set` de novo **atualiza sem duplicar** → `apagar` → cofre **de volta a `[]`**. Ciclo `list/create/edit/delete` provado também direto no CLI (2025.12.1 + Node 22) e a **conta do dono nunca foi tocada** |

## [1.34.1] — STACK NÔMADE: HOMEBOX FORA DO AR (8 FERRAMENTAS) 🜂 (2026-10-17)

> **Bump PATCH (operação de casa — sem capacidade nova):** decisão do dono
> em 17/10, avaliando as 9 ferramentas juntos — *"essas ferramentas só têm
> interesse para mim se o sistema puder usar-las"* + *"não quero nada
> parado"*. Veredito conjunto: **Homebox sai** (inventário vazio — 1,9 MB
> só de banco, nunca usado), **FlatNotes/File Browser/Calibre ficam** para
> análise a fundo uma por vez (pauta nova no §5 do TODO) e as **3
> primeiras (Vaultwarden → Stirling PDF → Kiwix)** continuam e passam a
> ser **interligadas ao sistema** nessa ordem (o dono mandou começar por
> elas). Nada apagado: "sair" é só tirar do ar.

| Peça | Entrega |
|---|---|
| **`docker/tools-compose.yaml`** | Bloco do Homebox **comentado com instrução de reativação** (descomentar + `HBOX_AUTH_API_KEY_PEPPER` no `.env` + `docker compose up -d homebox`). Container `od-homebox` removido e **imagem apagada (−198 MB)**; dados preservados em `/home/alex/omegadrakon-tools/homebox` (banco 1,9 MB intocado). `docker compose config` valida **8 serviços**. |
| **`core/nomad_tools.py`** | `FERRAMENTAS_NOMAD` 9 → **8** (sem `homebox`) — sonda, cache, notifier e `/health` cobrem só as ativas. Doc do módulo registra a decisão (17/10) e a via de reativação. |
| **`tools/actions/actions.py`** | `_NOMAD_SERVICES`/`_NOMAD_PORTS` sem `homebox` — `nomad_tools_up/down/status/logs/restart` e `tailscale_serve` orquestram só as 8. |
| **`core/capabilities.py`** | Capability `nomad-tools` = "8 containers Docker"; descrição cita a saída do Homebox (dados preservados, compose comentado). Fallback de versão congelado = 1.34.1. |
| **`integrations/api/server.py`** | Painel `/admin`: "Stack Nômade — ferramentas ativas" **sem contagem fixa** (label não desatualiza mais); comentários do stats em 8. **`_APP_VERSION_CODE` 2066**. |
| **notifier + launcher** | Docstrings e contagens 9 → 8 (`_check_tools`, `register_nomad_health_checks`, comentários dos stats) — o alerta `tool:homebox` some **por construção** (não foi silenciado: o check não existe mais). |
| **Testes** | `test_nomad_tools.py`: contagens e sets 9 → 8, **2 asserções negativas** (`homebox` não volta ao catálogo nem ao `/health` sem decisão nova) e a sonda de conexão recusada trocou homebox → filebrowser; `test_nomad_tools_actions.py`: constantes 8 + `tailscale up` 8. **Mutações 3/3 capturadas** (homebox re-adicionado ao catálogo → 10 falhas · re-adicionado às actions → 3 falhas · porta duplicada 8410→8090 → 2 falhas), restaurações bit-exatas. |
| **versionCode** | 2065 → **2066** (política 9/9 — `.env`, `capabilities`, `pubspec`, `_APP_VERSION_CODE`, site ×4, CHANGELOG, README_VERSAO; APKs rebuildados e conferidos no aapt2: 2066 nos dois). |

| Validado | Resultado |
|---|---|
| Suíte do servidor (gate 90%) | **3105 passed / 16 skipped** (cov 90,93%) |
| Mutações (teste do teste) | **3/3 capturadas** |
| Prova viva (PID 725852, NRestarts=0) | `/health` **up · 21 checks · tool 8/8 · sem `tool_homebox`** · `/dashboard/stats` `nomad_tools total=8 up=8 fora=[]` · `/app/version` **1.34.1 / 2066** (sha `9aa8409a…` == APK publicado) · journal **0 erros / 0 menções a homebox** · **8 containers `od-*`** no ar · dados do Homebox intactos no disco |

## [1.34.0] — FRENTE NV: COLEÇÕES COM CICLO FECHADO (PROTOCOLO_NV) 🜂 (2026-10-16)

> **Bump MINOR (capacidade nova + APK novo):** frente NV aberta pelo dono
> ("prossiga") — 1º item da ordem das frentes aprovada (1º NV, 2º FAB,
> 3º Living Systems). Regra do `PROTOCOLO_NV.md` do Legado aplicada ao
> Registro Mestre: **"Coleções são ciclos fechados. Uma vez Encerrada,
> nunca é reeditada"** — imutável por desenho (não existe reabrir,
> renomear nem apagar: só criar e encerrar, e encerrar é para sempre).

| Peça | Entrega |
|---|---|
| **`core/registry.py`** | Tabela `registry_collections` (nome único 3–40, criada_em, closed_at NULL=aberta). **`criar_colecao`** (abre ciclo; duplicada = `colecao_ja_existe`), **`encerrar_colecao`** (fecha PARA SEMPRE; segunda vez = `colecao_ja_encerrada`), **`listar_colecoes`** (abertas primeiro + contagem de peças), **`colecao_de_peca`** (status do ciclo: aberta/encerrada/None). **Regra no `create()`**: peça **NV exige coleção existente e ABERTA** (`colecao_obrigatoria_nv`/`colecao_ausente`/`colecao_encerrada`); não-NV mantém coleção livre (texto) — mas ciclo encerrado não recebe peça de linha nenhuma. **`update()`**: NV só troca para ciclo aberto; peça dentro de ciclo encerrado **não sai** (`peca_em_ciclo_encerrado` — a escassez fica registrada na peça); preço/status continuam livres. **`verify_public`** ganha `collection_status`. **`criar_colecoes_de_pecas()`**: migração idempotente — toda coleção citada por peça NV vira entidade ABERTA no boot (peças anteriores a esta frente não ficam órfãs). |
| **`runtime/launcher.py`** | Boot chama a migração de coleções (com log das criadas — prova viva). |
| **`integrations/api/server.py`** | **`GET /registry/collections`** (PÚBLICA — nome, ciclo, contagem, datas; rota fixa ANTES de `/{codigo}` para "collections" não virar código) + **`POST /admin/registry/collections`** (abrir) e **`POST /admin/registry/collections/{nome}/encerrar`** (dono; 404 inexistente, 400 já-encerrada). **Sem DELETE/PUT de coleção — a imutabilidade é por ausência de rota.** Painel `/admin`: bloco "Coleções (ciclo fechado)" com lista (ciclo, peças, datas), botão "⛔ Encerrar (para sempre)" com confirmação e input para abrir ciclo; dica no campo de coleção da peça (NV: obrigatória/aberta). |
| **`site/verificacao.html`** | A verificação pública mostra o ciclo da coleção: "ABISSAL · ciclo aberto" / "· ciclo encerrado" — escassez visível a quem confere a peça. |
| **Testes** | Nova classe `TestColecoesCicloFechado` (11: criar/normalizar, duplicada, nome inválido, encerrar e nunca reabre [+ hasattr garante que não existe reabrir/apagar], NV exige ciclo aberto, PROD livre mas encerrada não recebe, update respeita ciclo, verify mostra ciclo, listar abertas primeiro, migração idempotente) + `TestColecoesRotas` (6: pública sob auth_all, não engolida por `/{codigo}`, admin abre/encerra, sem chave negado, peça NV pela API exige ciclo aberto, painel tem UI). **Mutações 4/4 capturadas** (exigência do create removida · re-encerrar liberado · peça em ciclo encerrado solta · ordem das rotas invertida), reversões bit-exatas. |
| **Calibração RAG (corpus)** | A entrega anterior poluiu o corpus com uma palavra rara dos docs escritos naquele dia — a irrelevante climática do gate subiu a comb 0.4427 (acima da relevante mais fraca, 0.4058): **sem piso que separe**. Correção honesta nos MEUS textos de hoje (troca do termo raro colidido por sinônimo comum em README_VERSAO/CHANGELOG) — **piso 0.399/0.036 intacto, sem afrouxamento**; gates voltaram a 8/8 rel. + 8/8 irr. bloqueadas + 6/6 parafrases. |
| **versionCode** | 2064 → **2065** (bump MINOR — `.env`, `capabilities`, `pubspec`, `_APP_VERSION_CODE`, site, README_VERSAO, esta seção). |

| Validado | Resultado |
|---|---|
| Suíte do servidor (gate 90%) | **3105 passed / 16 skipped** (+17) |
| Mutações (teste do teste) | **4/4 capturadas** |

## [1.33.1] — LOJA DO SITE SEPARADA POR SEÇÕES (LINHAS DA CASA) 🜂 (2026-10-16)

> **Bump PATCH (ajuste de layout da loja):** pedido do dono no mesmo dia do
> ID unificado — "a loja precisa separar por seções". A separação vem do
> PREFIXO do ID canônico (FRENTE-TIPO-ANO-SEQ): cada linha da casa vira sua
> seção, sem cadastro novo e sem coluna extra — o ID já diz a linha.

| Peça | Entrega |
|---|---|
| **`site/loja.html`** | Prateleira única → **uma seção por linha**: cabeçalho com nome da linha + contagem + resumo curto. Ordem fixa das linhas canônicas (**NV** primeiro — Nicoly Valentina, semi-joias; depois **PROD** — produtos do ecossistema) e linhas novas (ex.: `FAB-…`) entram sozinhas, em ordem alfabética, com seção própria. Contagem total no rodapé do catálogo ("N peça(s) · M linha(s)"). |
| **Testes** | Nova classe `TestLojaPorSecoes` (tests/test_api.py): harness de node que **RODA** o JS inline da loja com DOM e fetch de mentira (padrão do TestTemaClaroEscuro) — NV antes de PROD, peça cai na seção da SUA linha, linha desconhecida ganha seção, catálogo vazio avisa, JS compila. **Mutações 3/3 capturadas** (agrupamento removido · ordem invertida · frente lida do collection em vez do ID), reversões bit-exatas. |
| **versionCode** | 2063 → **2064** (política 9/9 — APK acompanha o bump, ainda que o app não mude). |

| Validado | Resultado |
|---|---|
| Suíte do servidor (gate 90%) | **3088 passed / 16 skipped** (+4) |

## [1.33.0] — ID ÚNICO DO REGISTRO MESTRE (FRENTE-TIPO-ANO-SEQ) — Pauta §8.4 FECHADA (2026-10-16)

> **Bump MINOR (capacidade nova + APK novo):** ordem do dono — "crie uma
> ID bem consistente que possa incorporar todas as frentes; OD não
> precisa; mas como joias são pequenas seria bom ter o código curto
> também". A divergência §8.4 da pauta (2 formatos incompatíveis no
> Legado × sistema) vira UM padrão só, sem prefixo OD, cobrindo todas
> as frentes, e o código curto gravável das joias passa a ser obrigatório
> por desenho nas exclusivas.

| Peça | Entrega |
|---|---|
| **`core/registry.py`** | Padrão canônico **`FRENTE-TIPO-AAAA-NNNN`** (ex.: `NV-SJ-2026-0001`) — frente/tipo de 2–4 letras (vocabulário livre com canônicos documentados: frente NV/PROD/SYS/NUC/SUP, tipo SJ/PE/COD/MAN/AUTH/COL/EMB/CART) e **sequência por frente+tipo+ano** (PROD-PE não consome o número do NV-SJ). `create()` ganha `frente`/`tipo` (padrão PROD-PE). **Código curto gravado** (joia pequena) no padrão do Protocolo NV do Legado — `FRENTE-SIGLA-HEX4`, ex. `NV-ABI-7F3A` — **auto-gerado** para toda exclusiva sem código informado (sigla da coleção, 4 hex, colisão ressorteia; UNIQUE do banco é a garantia final); pública continua podendo ficar sem. **`migrar_ids_legados()`**: idempotente, reescreve o formato v1.22–1.32 (`OD-PROD-AAAA-NNNN`) por classificação determinística (exclusiva→NV-SJ, pública→PROD-PE), leva foto (renomeia arquivo) e bate-papo junto, devolve os pares (antes, depois) para o log. |
| **`runtime/launcher.py`** | Migração roda no boot do `build_registry` (com log dos pares migrados — prova viva) — peça cadastrada no formato antigo continua pesquisável **pelo curto** mesmo antes da migração (busca tolerante normaliza tudo). |
| **`integrations/api/server.py`** | `POST /admin/registry` aceita `frente`/`tipo`; painel `/admin` ganha os 2 selects (NV/PROD/SYS/NUC/SUP × SJ/PE/…) ao lado do nome e o placeholder do código gravado vira "auto se vazio". |
| **Site + app** | `verificacao.html`: placeholder/dica no formato novo (`NV-SJ-2026-0001` / `NVSJ20260001`); `index.html`: tag da semi-joia já nasce no padrão novo; `registry_screen.dart`: hint do campo de busca. |
| **Migração real** | As 6 peças de teste do banco (todas "(exemplo)") reescritas no boot — prova viva: `/admin/registry` com os IDs novos, busca pelo curto antigo (`NV-ABI-7F3A`) intacta. |
| **versionCode** | 2062 → **2063** (bump MINOR — `.env`, `capabilities`, `pubspec`, `_APP_VERSION_CODE`, site, README_VERSAO, esta seção). |

### O padrão (decisão do dono, 16/10)

```
ID canônico:  FRENTE-TIPO-AAAA-NNNN     ex.: NV-SJ-2026-0001
Código curto: FRENTE-SIGLA-HEX4         ex.: NV-ABI-7F3A (9 chars sem hífen)
```

- **Sem prefixo OD** (pedido do dono) — a frente já identifica a casa.
- **Todas as frentes** num formato só: NV (joias), PROD (produtos), SYS
  (sistemas), NUC (núcleo), SUP (suportes) — livre para crescer.
- **Joia pequena = curto gravável**: exclusiva sem código ganha um
  auto; a pessoa lê 9 caracteres e digita (busca tolera sem hífen).
- **Busca continua tolerante** a hífens/espaços/maiúsculas — tanto o
  ID canônico quanto o curto acha a peça.

| Validado | Resultado |
|---|---|
| Suíte do servidor (gate 90%) | **3084 passed / 16 skipped** (+6) |
| `tests/test_registry.py` | **57 verdes** (+6: frente/tipo inválidos, sequência por frente+tipo, curto automático, pública sem curto, migração idempotente) |
| Teste do teste (mutação) | **4/4 capturadas** (validação de frente removida · curto automático removido · migração no-op · sequência global) — reversão bit-exata |
| App | `flutter analyze` **0 issues** · `flutter test` **192 passed / 2 skipped** |

## [1.32.0] — TEMA CLARO/ESCURO SINCRONIZADO NO APP, NO SITE E NO PAINEL (TODO §3.8) (2026-10-16)

> **Bump MINOR (capacidade nova + APK novo):** ordem do dono com as três
> decisões já fechadas na conversa — (1) o tema vale no **app + painel +
> site público (11 páginas)**; (2) quem nunca escolheu **segue o
> sistema**; (3) a preferência fica **no perfil do servidor com cópia
> local**. O backend ganha a preferência no perfil e os TRÊS clientes
> passam a ler a MESMA chave `theme` (`system` | `light` | `dark`) —
> trocar no celular muda o site e o painel no mesmo login.

| Peça | Entrega |
|---|---|
| **`integrations/api/auth.py`** | Tabela própria `user_prefs` (`user_id`, `preferences`, `updated_at`) — e não coluna em `users`: o `Database` não tem migração e `create_table` só cria o que falta, então funciona em banco já existente sem `ALTER TABLE`. Allowlist `PREFERENCIAS_VALIDAS` (`theme`: system/light/dark) + `PREFERENCIAS_PADRAO` (`{"theme": "system"}`) + `validar_preferencias()` **puro** (chave ou valor fora do contrato → `AuthError` 400: chave desconhecida é ERRO e não silêncio, o cliente precisa saber que não guardou) + `get_preferences` (nunca levanta: banco fora ou JSON corrompido devolve o PADRÃO — a UI não pode cair por causa de preferência) e `set_preferences` (**merge**, upsert em duas instruções de propósito: SQLite e Postgres divergem no formato do `ON CONFLICT`). |
| **`integrations/api/server.py`** | Rotas autenticadas **`GET`/`PUT /profile/preferences`** (`PUT` faz merge e devolve o estado final) e `GET /auth/me` passa a devolver `preferences` — é por ali que app, site e painel sincronizam. O painel (`/dashboard`, `/admin`, `/chat`, cada uma com CSS inline próprio) ganha paleta clara e botão por **injeção**: `_com_tema()` mete `_TEMA_PAINEL_CSS` antes do `</head>` e o JS **DENTRO do único `<script>`** que a página já tem (bloco novo no meio quebraria a guarda de sintaxe, que recorta do primeiro `<script>` ao último `</script>`) — idempotente pela marca `odTema`. A paleta clara vive em `_TEMA_PAINEL_VARS` e entra nas duas portas (aparelho e escolha explícita), sem duas listas que possam divergir. |
| **`site/od.css` + `site/od-nav.js`** | Paleta clara em variáveis + as duas portas do "segue o aparelho": `@media (prefers-color-scheme: light)` para quem nunca escolheu e `:root[data-theme="light"]` para a escolha explícita. Botão `.nav-tema` **injetado** pelo JS ao lado do ⋮ (as 11 páginas não foram editadas): ciclo segue→claro→escuro, cópia local em `localStorage['od_theme']`, `PUT /profile/preferences` e sincronia por `/auth/me`. |
| **App `1.32.0+2062`** | `services/theme_service.dart` (**novo**): `ValueNotifier<ThemeMode>` com cópia local em `SharedPreferences['od_theme']` — o app abre já no tema escolhido ANTES do primeiro quadro (sem pisca) — envio best-effort ao perfil e a mesma regra de precedência dos outros dois clientes. `main.dart`: `theme`/`darkTheme` + `ValueListenableBuilder` no `themeMode` (trocar em Ajustes repinta o app inteiro sem reiniciar) e sincronia no boot do `OdRoot`. `settings_screen.dart`: card **Tema** com as três opções. `od_api.dart`: `getPreferences`/`setPreferences` + `getMe` expondo `preferences`. |
| **versionCode** | 2061 → **2062** (bump MINOR — o app mudou: `.env`, `capabilities`, `pubspec`, `_APP_VERSION_CODE`, site ×4, README_VERSAO, esta seção). |

### Decisões do dono (as três perguntas antes do código)

| Pergunta | Resposta | Consequência no desenho |
|---|---|---|
| Até onde o tema vale | **App + painel + site público (11 páginas)** | site e painel usam a MESMA preferência do app; nada de tema só no celular |
| Quem nunca escolheu | **Segue o sistema** | site/painel por `prefers-color-scheme`, app por `ThemeMode.system` (era o que o app já fazia) |
| Onde a preferência fica | **Perfil do servidor + cópia local** | trocar no celular muda o site/painel no mesmo login; offline a cópia local garante o tema e semeia o perfil depois |

| Verificação | Resultado |
|---|---|
| Suíte do servidor (gate oficial `--cov-fail-under=90` + `.coveragerc`) | **3074 passed / 16 skipped · cobertura 90,91%** (exit 0; 1 warning pré-existente de `tests/test_orchestrator.py`) — **+17 testes**: 11 em `tests/test_auth.py` (`TestPreferenciasDoPerfil`: padrão de quem nunca escolheu, round-trip entre instâncias, merge que preserva e normaliza, chave desconhecida → 400, valor fora da allowlist → 400, JSON corrompido volta ao padrão, validação pura, rotas `GET`/`PUT` com e sem sessão) e 6 em `tests/test_api.py` (`TestTemaClaroEscuro`: as 3 páginas do painel, bloco único de `<script>`, injeção idempotente, paleta+botão do site, as 11 páginas carregando `od.css`/`od-nav.js`, `node --check` do JS) |
| App | `flutter analyze` **0 issues** · `flutter test` **192 passed / 2 skipped** — **+13**: 12 do `test/theme_test.dart` (novo: cópia local, precedência perfil × local, semeadura, servidor fora, no-op sem api, `getPreferences`/`setPreferences`) e 1 do card Tema em `test/widget_test.dart` (pelo TOQUE na UI: aplica na hora, grava local e manda `theme: light` no PUT) |
| Correção de teste achada ao rodar a suíte | Três testes da seção **Avançado** faziam `scrollUntilVisible` e tocavam sem `pump`: o `ensureVisible` interno termina em `jumpTo` **sem frame**, e com o card Tema empurrando as seções de baixo o toque caía fora do tile. Entrou um `pumpAndSettle` entre a rolagem e o toque — **asserções intactas**, é o passo que faltava no harness |
| Guardas | política de versão **1.32.0/2062** (9/9) · `node --check` do JS do painel e do site verde |
| **Prova viva no serviço** | Abaixo (pós-deploy) |

**Prova viva no serviço (pós-deploy, 16/10 16:32:16, PID 4007853):**

| Passo | Resultado |
|---|---|
| Boot | **NRestarts=0**, **0 erros** no journal desde o boot · RAG idempotente (`chunks=1708 \| novos=8 \| atualizados=674`) |
| Versão | `/app/version` **1.32.0 / 2062** · `sha256 b5b4ed31…` **==** `site/OmegaDrakon.apk` (55.656.288 B) · `aapt2` dos dois APKs = `versionCode 2062` + `versionName 1.32.0` · guarda da política re-executada **9/9** |
| Backup | `backups/apk-v1.31.0-2061/` criado antes da publicação do novo par |
| Saúde | `/health` **up · 22 checks**, nenhum fora |
| Tema vivo | `/dashboard` servido **com a injeção** (marca `odTema` ×6 no HTML) · `od-nav.js` com `.nav-tema` + `localStorage['od_theme']` · `od.css` com as duas portas (`prefers-color-scheme` + `:root[data-theme]`) |
| Alerta `restart` | Um disparo único 16:36:04 (evento do boot 16:32) — um-disparo-por-boot segue valendo |

## [1.31.0] — APP AUTO-UPDATE EM BACKGROUND + PUSH FCM DO AUTO-UPDATE (ITEM B DA FILA) (2026-10-16)

> **Bump MINOR (capacidade nova):** item (B) da fila §7 — ordem do dono
> ("faça o B agora"). O que JÁ existia: FCM de ponta a ponta desde
> 13/09 (`3b5599c` — servidor `core/push.py` + app `push_service.dart`
> com exibição e registro em `/push/register`) e updater v1.7.0 desde
> 27/09 (checagem no boot, download com SHA-256, instalação via
> FileProvider — provado nas trocas 2017→2060 no celular do dono).
> Este fecha as duas lacunas que faltavam do TODO §3.8: (1) o
> auto-update do SERVIDOR nunca avisava no celular e (2) o download do
> APK só começava com toque do dono.

| Peça | Entrega |
|---|---|
| **`core/auto_update.py`** | `_anunciar()` — notificação FCM **"Auto-update aplicado"** nos dois pontos de sucesso do ciclo: re-sync do índice RAG (com stats de chunks) e download concluído/movido (alvo + versão + destino). Best-effort: `PushService.notify` nunca levanta e o `try/except` cobre um push falso em teste — o ciclo de auto-update **não morre por causa de um aviso**; `push=None` (sem launcher) segue silencioso. |
| **`runtime/launcher.py`** | `build_auto_update(..., push=)` — o `PushService` (construído ANTES do auto-update no boot) é injetado no serviço; call site `push=push` com comentário. |
| **App `1.31.0+2061`** | `main.dart`: `_preDownload` — a checagem do boot dispara o download **SOZINHO em background** (banner "Baixando vX… N%"); concluído → banner "baixada — pronta para instalar" + botão **Instalar** (instala direto, sem rede). Falha de rede é silenciosa: o banner cai no botão "Atualizar" (retry pelo toque) e o próximo boot tenta de novo. `od_updater.dart`: `download()` **reusa o cache cujo SHA-256 confere** (2ª chamada = 0 requisições) e ganha `httpClient` injetável (testes — o binding do Flutter responde 400 em cliente HTTP real). |
| **versionCode** | 2060 → **2061** (bump MINOR — o app mudou: `.env`, `capabilities`, `pubspec`, `_APP_VERSION_CODE`, site ×4, README_VERSAO, esta seção). |

| Verificação | Resultado |
|---|---|
| Suíte do servidor (gate oficial `--cov-fail-under=90` + `.coveragerc`) | **2971 passed / 16 skipped · cobertura 90,64%** — +3 testes em `tests/test_auto_update.py` (63 no arquivo: anúncio no re-sync RAG com stats de chunks, anúncio no download concluído via `tratar_evento` público, push que levanta não derruba o ciclo) |
| Guardas | política de versão **1.31.0/2061** (9/9) · pyflakes sem aviso novo no que mexi (o `field` do `auto_update.py` é pré-existente no HEAD) · `node --check` do JS do painel verde |
| App | `flutter analyze` **0 issues** · `flutter test` **179 passed / 2 skipped** (+2 do cache de download: 1ª baixa/2ª reusa `hits==1`, cache sujo rebaixado — transporte `MockClient` injetado, padrão `od_api_test`) |
| **Prova viva no serviço** | Abaixo (pós-deploy) |

**Prova viva no serviço (pós-deploy, 16/10 12:23:30, PID 3766943):**
restart verde (NRestarts=0, **0 erros** — o único `[ERROR]` do dia é o
DNS do Telegram das 03:00, pré-existente; boot lento ~4 min pós-gate,
porta LISTEN desde cedo e API respondendo ao destravar) · `/health`
**up 20/20** · `/app/version` **1.31.0 / 2061** com `sha256 3d3f6ccf…`
**idêntico** ao `site/OmegaDrakon.apk` (aapt2 dos dois APKs:
`versionCode 2061` cruro + `versionName 1.31.0`; **backup do
1.30.0/2060 reconstruído** em `backups/apk-v1.30.0-2060/` via worktree
no commit `e279151`) · `Auto-update tick | alvos=1 | aplicar=0` no
journal = serviço de pé com a injeção `push=push` · **prova de fogo do
caminho novo**: `_anunciar()` real → journal `Push enviado | enviados=1
| falhas=0 | titulo=Auto-update aplicado` + resumo `{'ok': True, 'sent':
1, 'failed': 0}` (aviso marcado **[PROVA DE FOGO B]** entregue no
celular do dono) · `/dashboard/stats` bloco `notifier` intacto
`{ticks: 3, checks_run: 48, problems: 4, alerts_emitted: 0,
alerts_blocked: 3, errors: 0}` · `/admin` `stats.notifier` ×3 ·
**bônus verificado**: o alerta `key=restart` previsto para ~12:18 na §6
da transcrição disparou **uma única vez às 12:17:33** + push — e o
processo novo o segura de novo pelo cooldown (`blocked: 3` = sem
duplicata).

### Observabilidade — Métricas Prometheus do auto-update (`od_auto_update_*` no `/metrics`) (TODO §3.2, ordem do dono, 2026-10-16, sem bump)

> **Bump:** nenhum — backend puro (1.31.0/2061 intacto). Ordem do dono
> depois do backup: escolha do item da fila (os candidatos do §3 eram
> tema escuro/claro, backup off-site e **métricas Prometheus do
> auto-update**). O TODO §3.2 pedia `auto_update_tick_total`,
> `auto_update_aplicado_total` e `auto_update_falha_total`; os nomes
> saem com **prefixo `od_`** porque **toda** métrica do MetricsCollector o
> leva (`od_processed_total`, `od_audit_total`, `od_api_requests_total`) —
> `od_auto_update_tick_total` é o mesmo número que foi pedido, e o teste
> do `/metrics` fixa os dois lados dessa equivalência.

| Peça | Entrega |
|---|---|
| **`core/auto_update.py`** | `MetricasAutoUpdate` (dataclass `slots`, o mesmo padrão do `NotifierMetrics`) contada **onde o fato acontece**: `ticks`/`ticks_dry_run`, as decisões do ciclo (`decisao_aplicar`/`aguardar`/`pular`), `aplicados` (o que **concluiu**: re-sync do RAG ou download verificado/movido), `falhas` (só **DURA** — a severidade do Nômade), `auto_desligados` (contado na **transição**, não a cada falha), `rag_syncs`, `downloads` (novos enfileirados), `dedups` (enqueue que a fila já tinha — **não é falha**) e `erros` (exceção contida no consumidor de eventos). `prometheus_lines()` renderiza o **text exposition format**: contadores **desde o boot** (zerar no restart é o esperado — `rate()`/`increase()` compensam) + gauges do estado **persistido** (`alvo`, `alvo_desabilitado`, `download_pendente`) + `ultimo_tick_segundos`, que **não é inventado como zero** antes do primeiro ciclo. |
| **`core/capabilities.py`** | O registry do `/capabilities` listava as fontes vivas sem o auto-update (`orchestrator/audit/uptime`) — a descrição do módulo `metrics` passa a citar `od_auto_update_*`, para a superfície pública não ficar desatualizada depois desta entrega. |
| **`runtime/launcher.py`** | `ligar_metricas_auto_update(metrics, auto_update)`: o serviço entra como **fonte viva** do coletor. A ligação é **tardia de propósito** — o coletor nasce em `build_metrics` (o `/health` depende dele) e o auto-update só existe depois — e é **best-effort**: sem coletor ou sem serviço (`OD_AUTO_UPDATE=0`) devolve `False` e o boot segue igual. |
| **API (`/dashboard/stats`, `/admin/auto-update`, `/admin`)** | Os **mesmos números** (uma fonte só: `svc.metricas.snapshot()`) no bloco `auto_update` do Status, no GET/dry-run do admin e numa linha do card do painel — o dono vê sem precisar de um Prometheus apontado; um scraper vê no `/metrics`. |
| **Decisão registrada (honestidade da métrica)** | **Não** existe `skip_total`: o contrato `_registrar_falha(dura=False)` (erro transitório que não conta para o auto-disable) **nenhum caminho usa hoje** — publicar um contador que nunca sai de zero só confundiria quem lê o painel. O docstring diz isso em vez de deixar a dúvida. |

| Verificação | Resultado |
|---|---|
| Suíte oficial gate `--cov-fail-under=90` (+ `.coveragerc`) | **3057 passed / 16 skipped · cobertura 90,86%** (exit 0) — **+11** testes (`tests/test_auto_update.py` com **74** verdes). *(A medição logo após a entrega deu 90,87%; a rerodada final, depois do ajuste do registry de `capabilities`, deu os mesmos **3057 passed** com 90,86% — a diferença é o último centésimo.)* |
| `core/auto_update.py` | **95%** — os 25 stmts faltantes são **pré-existentes** (caminhos de erro com guarda, `dura=False`, `start()` sem fila); **todo** o código novo está coberto |
| pyflakes | **sem aviso novo** nos 4 arquivos tocados (os 7 são pré-existentes; o único "novo" é o **deslocamento de linha** do `plugins` não usado do launcher, mesma mensagem do HEAD) |
| **Teste do teste (mutação)** | 6 mutações aplicadas e **todas capturadas**: contador de ciclos removido, `aplicados` do RAG removido, dedup somado como download, auto-desligado não contado, **idade inventada como 0** e troca `aguardar`/`pular`; reversão bit-exata |
| Testes que mais importam | contagem **por caminho** (tick × dry-run × falha × dedup × concluído), auto-disable contado **uma vez**, formato/labels do `/metrics`, estado ilegível **não derruba** o render, o serviço funciona como fonte no `MetricsCollector` e a **fiação do launcher** é exercitada (com os dois lados do best-effort) |

**Prova viva no serviço (pós-deploy, 16/10 15:20, PID 3935938):**
restart verde (`825a033` pushado **antes**, regra 7.3) · boot
`Métricas do auto-update no /metrics (TODO §3.2)` · primeiro tick real
`Auto-update tick | alvos=1 | aplicar=0 | resumo=indice-rag=aguardar` ·
**`curl /metrics` traz a família nova** — `od_auto_update_tick_total 1`,
`od_auto_update_decisao_total{decisao="aguardar"} 1`,
`od_auto_update_alvo 1`, `od_auto_update_alvo_desabilitado 0`,
`od_auto_update_download_pendente 0`,
`od_auto_update_ultimo_tick_segundos 32.915` (o **mesmo** tick do journal,
32,9 s depois) — **sem regressão** no que já existia (42 linhas no total:
`od_audit_total 13006`, `od_uptime_seconds 41`, `od_api_requests_total 26`,
`od_processed_total 0`) · `/dashboard/stats` bloco `auto_update.metricas`
com **os mesmos números** do scrape (`ticks: 1`, `decisao_aguardar: 1`) ·
`/admin` com a linha de contadores (`id="au-metricas"`, `od_auto_update_` ×2)
· `/health` **up, 22 checks**, nenhum fora · `/app/version` **1.31.0/2061**
(sem bump) · NRestarts=0 e **0 erros** no journal.

### Infra — Backup: as CAPTURAS entram (perfil semanal próprio, para o HD externo) (TODO §3.6, ordem do dono, 2026-10-16, sem bump)

> Pedido do dono: *"inclua data/captures no backup (semanal, para o HD
> externo)"* — fechando o escopo que ficou de fora às 14:16. Medido
> **antes** de decidir: `data/captures` = **316 MB** (43 dias de
> fotos/vídeos) e o **gzip não reduz** (316.016.667 bytes de 316.051.501 —
> mídia já comprimida), **10,7 s** para empacotar. Daí o desenho: snapshot
> **próprio e semanal**, separado do diário do estado — 316 MB todo dia
> seria desperdício para um acervo append-only, e **4 semanas (~1,3 GB)**
> cabem folgadas nos **85 GB livres**.
>
> **Correção de um fato errado meu:** os registros de 14:16 (este arquivo,
> o TODO §3.6 e o `iniciar/` §11) diziam *"disco a **85%**"* — é **falso**.
> O `85.0` era o **limite configurado** do notifier
> (`OD_DISK_THRESHOLD_PERCENT` da sonda `_check_disk`), não o uso; o disco
> real está em **62%** (`df`: 137G usados, 85G livres). Corrigido nos três
> lugares — e é o número certo que sustenta a decisão de reter 4 semanas de
> capturas.

| Peça | Entrega |
|---|---|
| **`core/backup.py`** | Tabela **`PERFIS`** (um código, dois trabalhos) + `cadencia_dias` generalizando `proxima_janela` (dia do último sucesso + N dias no HH:MM; 1 = diário, 7 = semanal, **catch-up preservado**) + `prefixo`/`check_nome` por perfil (`build_services()` devolve os serviços dos perfis ligados). A retenção usa o prefixo: **nome de um perfil nunca é apagado pelo outro**. Perfil `estado` **INTACTO** (03:00, `backups/auto/`, prefixo `od`, sem `captures` nem `vector_memory`, 3 diários + 8 semanais, knobs `OD_BACKUP_*`); perfil `capturas` **novo** (04:00, `backups/auto-capturas/`, prefixo `od-capturas`, exclui **só** `vector_memory`, **0 diários + 4 semanais**, estado próprio `data/backup_capturas_estado.json`, knobs `OD_BACKUP_CAPTURAS_*`). Mesmo tar determinístico/atômico e `0600`/`0700`. |
| **`runtime/launcher.py`** | `build_backup()` → **`build_backups()`**: devolve a lista de perfis; cada um ganha o **próprio loop supervisionado** (`_run_backup_forever`, tick de 15 min) e o próprio check no `/health` — `OD_BACKUP=0` e `OD_BACKUP_CAPTURAS=0` desligam cada um (loop/check/bloco somem). O empacotamento (10,7 s nas capturas) roda em `to_thread`: tar é I/O e não pode prender o event loop dos outros loops. O aviso de falha diz **qual perfil** falhou. |
| **`/health` + `/dashboard/stats` + `/admin`** | Bloco **por perfil** no Status (`{estado: {...}, capturas: {...}}`) e **2 cards** no painel — "Backup" e **"Backup fotos"** (JS `fmtBytes`). Check `backup_capturas` **NÃO crítico** (degrada se a semana passar sem snapshot; antes da hora, ou já feito, fica `up`). |
| **`.gitignore`** | `backups/auto/` → **`backups/auto*/`**: o diretório novo (`auto-capturas/`) **não estava ignorado** — o `git status` o listava como untracked e um `git add -A` subiria **316 MB das fotos do dono + o `.env`** para o repo **PÚBLICO**. Fechado antes do commit (confirmado com `git check-ignore` nos dois diretórios **e** no tar dentro deles). |

| Verificação | Resultado |
|---|---|
| `core/backup.py` | **100% de cobertura** (376 stmts, 0 faltando) |
| Suíte oficial gate `--cov-fail-under=90` (+ `.coveragerc`) | **3046 passed / 16 skipped · cobertura 90,83%** (exit 0) — **+12** sobre o backup diário (3034 · 90,80%); `tests/test_backup.py` com **72** verdes |
| pyflakes | **idêntico ao HEAD** nos 4 arquivos tocados (os 6 avisos são pré-existentes, conferidos por `git stash`) |
| **Teste do teste (mutação)** | 4 mutações aplicadas e **todas capturadas**: capturas fora das exclusões, cadência ignorada, prefixo ignorado e check único para os dois perfis |
| Testes que mais importam | cadência semanal (na semana seguinte só depois de +7 dias, **sem repetir** dentro da semana) e catch-up do semanal (servidor desligado no dia); prefixo por perfil (nome **e** retenção: um perfil não apaga o arquivo do outro); perfil das capturas **inclui** `data/captures` e segue **sem** `vector_memory`; `/health` com os **2 checks não-críticos independentes**; API com os dois blocos e os dois cards |

**Prova viva no serviço (pós-deploy, 16/10 14:34, PID 3888045):**
restart verde · boot com **os dois perfis** (`Backup no ar … perfil=estado
… hora=03:00 | raiz=backups/auto` e `perfil=capturas | hora=04:00 |
raiz=backups/auto-capturas | cadencia_dias=7 | semanais=4`) · **primeiro
tick rodou o snapshot semanal das capturas** (catch-up, journal `Backup
concluído | perfil=capturas | arquivo=od-capturas-2026-10-16_1434.tar.gz |
membros=923 | bytes=316276693 | duracao_s=10.7`) · artefato conferido **fora
do código**: `-rw------- backups/auto-capturas/od-capturas-2026-10-16_1434.tar.gz`
(**301,6 MiB**), pasta `drwx------`, **sha256 do arquivo == `ultimo_sha256`
do estado**, `tar -tzf` = **923 membros** (**906** de `data/captures/` +
`.env` + estado/estatísticas, **0** de `vector_memory/`, **0** de
`captures/../.part`/`.pyc`), **uma foto extraída byte-idêntica** ao
original (`cmp` ok) e o **`.env` extraído byte-idêntico** ao real ·
disco **85 → 85 GB livres (62%)** — o semanal não muda nada de escala ·
`/health` **up, 22 checks** (`backup` = *"Backup do estado ok de hoje
(od-2026-10-16_1416.tar.gz, 0.18 MB, há 0.3 h)"* e `backup_capturas` =
*"Backup das capturas ok da semana (od-capturas-2026-10-16_1434.tar.gz,
301.62 MB, há 0.0 h)"*, ambos `critical: false`) · `/dashboard/stats` com
`backup.estado` (cadência 1) e `backup.capturas` (cadência 7, 316.276.693
bytes) · `/admin` cards **"Backup"** e **"Backup fotos"** (`stats.backup.estado`
& `stats.backup.capturas` ×6 cada) · `/app/version` **1.31.0/2061**
(backend puro, **sem bump**) · NRestarts=0, journal sem `[ERROR]`.

### Infra — Alerta de `restart` vira EVENTO: um disparo por boot (ordem "aplique o refinamento do alerta restart", 2026-10-16, sem bump)

> Achado na retomada das 13:38 (`iniciar/` §8), medido **antes** de
> mexer: o alerta `key=restart` saía **uma vez por boot** (o
> `_restart_reported` sempre foi por processo), mas pagava o anti-spam
> de **1 hora** do legado — então o aviso de um boot novo era
> **atrasado** pelo alerta do boot anterior. Journal de 16/10 com os
> PIDs: **11:17:10** (PID 3703628, boot 11:17:09), **12:17:33** (PID
> 3724539, boot 11:38:58) e **13:17:39** (PID 3766943, boot 12:23:30) —
> 3 deploys seguidos ⇒ 3 alertas, com **39 e 54 min de atraso**, padrão
> que parecia um push de hora em hora no celular do dono. A previsão
> registrada em 16/10 (§6/§8) de que o alerta "travaria" depois da
> primeira emissão estava **errada** — corrigida com a medição.

| Peça | Entrega |
|---|---|
| **`integrations/notifier.py`** | `RESTART_ALERT_GUARD_S = 300.0` + `NotifierConfig.restart_alert_guard_s` + `CheckResult.cooldown_s`: o alerta de evento carrega o **próprio** anti-spam e ele **vence** `config.cooldowns["restart"]`/`default_cooldown_s`. `_check_restart` passa a guarda de rajada — dedupe continua **por boot** (`_restart_reported`, in-memory = o processo), então o MESMO boot nunca repete o aviso e um boot novo alerta no **primeiro tick**, mesmo com o boot anterior tendo alertado minutos antes. A guarda curta existe só contra **rajada** (ex.: `Restart=on-failure` + `RestartSec=10` numa queda que não sobe): boot em cima de boot espera a guarda vencer e ainda assim emite **uma vez**. O crash loop tem sonda própria (`systemd:nrestarts`, warn ≥1 / crit ≥3) com o anti-spam de 1/h — o sinal não depende mais do alerta de restart. |
| **`tests/test_notifier.py` +3 e ajuste** | Classe `TestAlertaDeRestartPorBoot`: (1) **um disparo por boot** — emitido uma vez e, passadas 2 horas de ticks, **não repete**; (2) **regressão do atraso** — alerta do boot anterior há 40 min + `cooldowns["restart"]=3600` ⇒ o boot novo **emite no primeiro tick**; (3) **guarda de rajada** — boots a 10 s/70 s ficam bloqueados (`alerts_blocked`) e o alerta sai **uma vez** aos 310 s, sem repetir depois. `test_config_defaults_match_legacy` ganhou a guarda de 300 s. Os 2 testes antigos que fixavam `cooldowns["restart"]` passaram a fixar `restart_alert_guard_s` (a intenção deles é a mesma: cooldown determinístico no cenário). |

| Verificação | Resultado |
|---|---|
| Suíte oficial gate `--cov-fail-under=90` (+ `.coveragerc`) | **2974 passed / 16 skipped · cobertura 90,62%** (+3 testes; 1 warning pré-existente de `tests/test_orchestrator.py`) |
| pyflakes | **limpo** nos 2 arquivos tocados, idêntico ao HEAD |
| **Teste do teste (mutação)** | Remover o `cooldown_s` da sonda (volta o anti-spam de 1 h) faz **2 dos 3** testes novos falharem (`test_boot_novo_nao_espera_o_cooldown_de_1_hora`, `test_rajada_de_boots_espera_a_guarda_e_emite_uma_vez`); revertido bit a bit, 77 verdes em `tests/test_notifier.py` |

**Prova viva no serviço (pós-deploy):** abaixo, no mesmo dia.

### Infra — Backup automático do `.env` + `data/` (TODO §3.6, ordem do dono, 2026-10-16, sem bump)

> Pedido do dono: *"implemente o backup automático do .env + data/"*, com
> **3 decisões dele** tomadas antes de escrever qualquer linha: destino
> **LOCAL** (`backups/auto/` — ele transfere para um HD externo), escopo
> **`.env` + `data/` SEM `captures/` e SEM `vector_memory/`** (só o
> irreconstruível) e **03:00 · 3 diários + 8 semanais**. Números que
> orientaram a conversa: `data/` = **314 MB**, dos quais **304 MB são as
> capturas** (43 dias de fotos/vídeos) e 11 MB o índice do RAG
> (reconstruível pelos documentos) — o escopo escolhido dá **~185 KB por
> rodada** em vez de 314 MB/dia; `rclone`/`minio`
> ausentes (off-site exigiria conta e credenciais novas — ficou para
> quando ele decidir).
>
> ***Correção de 16/10 (14:38):** este parágrafo dizia "disco a **85%**" e
> isso era **falso** — o `85.0` do log é o **limite configurado** do
> notifier (`OD_DISK_THRESHOLD_PERCENT`, sonda `_check_disk`), não o uso. O
> disco real estava em **62%** (85 GB livres). Ver a entrada das capturas,
> logo acima.*

| Peça | Entrega |
|---|---|
| **`core/backup.py` (novo)** | `avaliar()` **PURO** (padrão da casa: relógio, estado, espaço em disco e arquivos entram por parâmetro) nas camadas `desligado` → `antes_da_hora` → `ja_feito_hoje` → `disco_insuficiente` (estimativa × 1,10) → `rodar`, **com catch-up** (servidor desligado às 03:00 ⇒ o primeiro tick depois do horário roda). `BackupService` é o executor: tar.gz **determinístico** (gzip `mtime=0` e `filename=""`, uid/gid 0, membros ordenados ⇒ mesmo conteúdo = mesmo sha256), gravação atômica (`tmp` → `os.replace`), **`0600` no arquivo e `0700` no diretório** (o tar leva o `.env` dentro), estado em JSON atômico, **retenção por semana ISO** (3 diários + 1 representante de cada uma das 8 semanas mais recentes; nome fora do padrão nunca é apagado), limpeza de `.tmp` órfão e falha que **avisa no celular** (best-effort, 1 push a cada 6 h para erro persistente não virar spam). |
| **`/health` + `/dashboard/stats` + `/admin`** | Check `backup` **NÃO crítico** (degrada enquanto o snapshot do dia não existir — antes da hora ou já feito, fica `up`), bloco `backup` no Status (config, último arquivo/sha/tamanho, `pendente_hoje`, lista para copiar no HD) e card **"Backup"** no painel (JS novo `fmtBytes`). |
| **`runtime/launcher.py`** | `build_backup()` + `_run_backup_forever()` — loop supervisionado (`_supervise("backup", ...)`), **tar em thread** (`asyncio.to_thread`: empacotar é I/O e não pode prender o event loop), tick a cada 15 min com decisão barata. Knobs: `OD_BACKUP`, `OD_BACKUP_HORA`, `OD_BACKUP_DIARIOS`, `OD_BACKUP_SEMANAIS`, `OD_BACKUP_INTERVALO_MIN`, `OD_BACKUP_DIR`, `OD_BACKUP_ESTADO`, `OD_BACKUP_EXCLUIR`. |
| **`.gitignore`** | `backups/auto/` ignorado: o repo é **público** e o tar leva o `.env` dentro. |

| Verificação | Resultado |
|---|---|
| `core/backup.py` | **100% de cobertura** (343 stmts, 0 faltando) |
| Suíte oficial gate `--cov-fail-under=90` (+ `.coveragerc`) | **3034 passed / 16 skipped · cobertura 90,80%** (+60 em `tests/test_backup.py`; 1 warning pré-existente de `tests/test_orchestrator.py`) |
| pyflakes | **idêntico ao HEAD** nos 4 arquivos tocados (os 6 avisos são pré-existentes, conferidos com `git stash`) |
| **Teste do teste (mutação)** | 4 mutações aplicadas e **todas capturadas**: guarda de disco (3 falhas), retenção semanal (3), exclusões do dono (3) e aviso de falha (1); reversão bit-exata ⇒ 60 verdes |
| Testes que mais importam | tar contém `.env` + `data/` e **não** `captures/`/`vector_memory/`; `.env` extraído é **byte-idêntico**; conteúdo igual ⇒ **mesmo sha256**; retenção real (10 dias ⇒ 4 arquivos com 3 diários + 2 semanas); falha grava estado honesto e avisa **1×** (cooldown de 6 h); check não-crítico **degrada** o `/health` em vez de derrubar |

**Prova viva no serviço (pós-deploy, 16/10 14:16, PID 3871779):**
restart verde (regra 7.3 — `2fd75ab` pushado ANTES) · boot
`Backup automático no ar (TODO §3.6) | hora=03:00 | raiz=backups/auto |
diarios=3 | semanais=8 | excluidos=data/captures,data/vector_memory` +
`Loop de backup habilitado` · **primeiro tick rodou o snapshot de hoje**
(catch-up, journal `Backup concluído | arquivo=od-2026-10-16_1416.tar.gz |
membros=16 | bytes=189686 | sha256=392f7bd68863 | duracao_s=0.15`) ·
artefato conferido no disco: `-rw------- backups/auto/od-2026-10-16_1416.tar.gz`
(185 KB), `drwx------ backups/auto`, **sha256 do arquivo == `ultimo_sha256`
do estado**, `tar -tzf` = **16 membros** (`.env` + 15 de `data/`, nenhum de
`captures/`/`vector_memory/`) e o **`.env` extraído é byte-idêntico ao real**
(`cmp` ok) · `/health` **up, 21 checks** (`backup` = *"Backup de hoje ok
(od-2026-10-16_1416.tar.gz, 0.18 MB, há 0.0 h)"*, `critical: false`) ·
`/dashboard/stats` com o bloco `backup` completo · `/admin` com o card
(`stats.backup` ×3) · `/app/version` **1.31.0/2061** (backend puro, **sem
bump**) · NRestarts=0, journal sem erros.

## [1.30.0] — REGISTRO DO COMPRADOR POR QR/POSSE + LOJA DO SITE (ETAPA 4 DO REGISTRO MESTRE) 🜂 (2026-10-15)

> **Bump MINOR (capacidade nova):** Etapa 4 do Registro Mestre — decisão
> final a–e do dono (ANALISE §item 2; ordem "prossiga" registrada como
> `ordem_etapa4_2026_10_15` em `iniciar/session.json`). Cada peça
> **exclusiva** ganha um código de posse `POSSE-XXXX-XXXX-XXXX-XXXX`
> (64 bits de `secrets`) impresso em **QR no cartão da compra**; o
> **comprador registra a peça no APP no próprio nome** com conta (quem
> tem o código é o dono); o MESMO código **destrava a regressão
> `registrada → X`** que o bloqueio `registro_pendente_codigo_secreto`
> da etapa 1 vinha esperando desde 09/10; e o site ganha **Loja**
> pública sem preço (negociação na sala da peça — preço é campo privado
> desde a etapa 1). O QR é símbolo de propriedade, não atalho: quem lê
> o QR continua precisando de conta no app para registrar.

| Peça | Entrega |
|---|---|
| **`core/registry.py`** | Coluna `posse_code_hash` (migração `_ensure_column`, mesmo padrão da photo) — o banco guarda **SÓ** `sha256(normalizado)` (banco vazado não vira domínio). `gerar_posse()` emite `POSSE-` + 4 grupos de 4 hex de `secrets.token_hex(8)` (64 bits) e **regenerar invalida o anterior na hora** (cartão perdido → código novo). `registrar_posse()` leva `estoque/vendida → registrada` com o username de quem tem conta — comparação NORMALIZADA (maiúsculas, sem hífen: `posseabcd…` funciona); erros uniformes `posse_invalida` para chute/lixo/vazio (sem oráculo) e `ja_registrada`; `update()` passou a aceitar `posse_code` e só com ele permite `registrada → vendida/estoque`, limpando `owner_username` e `registered_at` junto (sem ele o erro da etapa 1 continua intacto). Peça `publica` não tem posse (`publica_sem_posse`). |
| **Rotas novas (`ROUTES` 78 → 82)** | `GET /registry` (**lista pública da loja** — projeção `verify_public` sem preço/notas/hash; em `AUTH_EXEMPT_PATHS`), `POST /registry/posse` (comprador com conta: 401 sem login, 400 `posse_invalida`, 409 `ja_registrada`; aviso ao dono no Telegram "Peça X registrada por @user" — falha do aviso nunca derruba a resposta), `POST /admin/registry/{id}/posse` (dono gera/regenera: código em claro **uma vez** + URL absoluta `https://…/site/verificacao.html?posse=…` via `APIConfig.public_url`/`OD_PUBLIC_URL`), `GET /admin/registry/{id}/posse/qr?codigo=` (**SVG do QR** — valida o código contra o hash ANTES de renderizar; `Cache-Control: no-store`; lib `qrcode>=8.0` nova no `requirements.txt` com import tardio: sem ela 503 `qr_indisponivel`, nada mais quebra). |
| **Painel `/admin`** | Botão **🧾 QR** por peça exclusiva: POST gera o código e a linha abre com SVG 132 px + código + link copiável + alerta "código ANTERIOR invalidado" na regeneração. Botão **↩ Registro** nas peças `registrada`: desfazer exige **colar o código de posse** (prompt → PUT com `posse_code`; sem ele "Código de posse inválido — registro protegido"). Lista admin entrega `tem_posse` (bool) e **nunca** o hash. |
| **Site** | **`site/loja.html` (NOVA):** prateleira pública via `GET /registry` — foto, coleção, pill de status (Disponível / Vendida / Com dono), `@dono` quando registrada, link "Ver peça →" e a receita **Como comprar** em 3 passos (escolher → negociar na sala da peça → receber o QR). **Sem preço à vista** (decisão das etapas 1–3). `verificacao.html`: `?codigo=` pré-preenche e consulta sozinho; `?posse=` abre o **cartão do QR** com o código em destaque e a instrução de registrar no app. Nav "Loja" no `index.html` (topo + rodapé) e no `verificacao.html`. |
| **App `1.30.0+2060`** | `OdApi.registrarPosse()` (POST `/registry/posse`; erros amigáveis: sem conta → 401, código errado → "confira o cartão/QR", 409 → "já tem dono") + card **"Registrar minha peça"** na aba Verificar: quem tem conta cola o código (`POSSE-…`); sucesso = snackbar + **consulta automática** da peça recém-registrada (selo novo na tela). Sem conta → instrução para entrar em Config. **Honesto:** sem câmera no v1 — o comprador lê o QR com a câmera do celular (abre a URL com o código) e cola no app; leitura de QR dentro do app fica para a próxima etapa. |
| **versionCode** | 2059 → **2060** (bump MINOR — o app mudou: `.env`, `capabilities`, `pubspec`, `_APP_VERSION_CODE`, site ×4, README_VERSAO, esta seção). |

| Verificação | Resultado |
|---|---|
| Suíte do servidor (gate oficial `--cov-fail-under=90` + `.coveragerc`) | **2929 passed / 16 skipped · cobertura 90,58%** — +15 testes da Etapa 4 em `tests/test_registry.py` (51 no arquivo: loja pública sem preço/hash, registro 201/401/400/409, QR SVG 200/400, 403 p/ usuário comum, `publica_sem_posse`, `tem_posse` sem hash, regressão com/sem código, botões do painel) |
| Guardas | `ROUTES` 78 → 82 no espelho de `tests/test_api.py` (1 pública + 3 com auth); JS do painel `node --check` verde; política de versão em todas as fontes = 1.30.0/2060 |
| App | `flutter analyze` **No issues** · `flutter test` **177 passed / 2 skipped** (+3 do registro do comprador — o mock normaliza o código como o servidor faz) |
| QR (roundtrip real) | SVG do `qrcode` 8.2 **decodificado de volta** com OpenCV (`QRCodeDetector`) → texto **IDÊNTICO** à URL do cartão (`…/site/verificacao.html?posse=POSSE-…`) |
| **Prova viva no serviço** | Abaixo (pós-deploy) |

**Prova viva no serviço (pós-deploy, 15/10 23:41, PID 3091063):**
restart verde (NRestarts=0, journal 0 erros — o boot consumiu ~76 s
extras no resync do corpus RAG: 632 chunks atualizados pelos arquivos
desta própria entrega, trabalho esperado, diagnosticado com stack ao
vivo) · `/health` **up** com 9/9 `tool_*` · `/app/version` **1.30.0 /
2060** com `sha256 57ed3845…` == `site/OmegaDrakon.apk` publicado (aapt
dos dois APKs publicados: `versionCode 2060` cruro + `versionName
1.30.0`; backup do 1.29.0/2059 em `backups/apk-v1.29.0-2059/`) · `GET
/site/loja.html` **200** (8.433 B) · `GET /site/verificacao.html` **200**
· `GET /registry` **200** público sem `price_brl`/`notes`/
`posse_code_hash` · **drill E2E** com a peça `DRILL-ETAPA4` (criada e
apagada no mesmo drill): posse `POSSE-3875-6139-CDFB-90A4` emitida
(201 + URL absoluta do cartão) → QR **200 `image/svg+xml`** 13.092 B e
código errado **400** `posse_invalida` → conta 201 → registro do
comprador **201** com entrada normalizada (minúscula sem hífen) →
consulta pública sem credencial: `registrada=True` + `@dono` e **sem
hash** → repetir **409** `ja_registrada` → regressão **400 sem código /
400 código errado / 200 com código** (dono e `registered_at` limpos,
`tem_posse=true`, hash fora do payload) → ping 🔑 ao Telegram do dono
no instante do registro (peça drill) → peça + usuário de teste
apagados, listas pública/admin de volta ao total 6 — **resíduo zero**.

---

### Infra — Métricas do notifier no `/dashboard/stats` + card "Alertas" no `/admin` (ordem "exponha as métricas do notifier", 2026-10-16, sem bump)

> Item (iii) do conserto do notifier, pedido separado do dono (~11:30).
> Backend/painel puro (nenhuma linha do app) → **sem bump**,
> 1.30.0/2060 intacto. Os contadores já existiam
> (`integrations/notifier.NotifierMetrics`) — o que faltava era a
> ponte até o Status: emitidos × bloqueados pelo anti-spam × erros só
> apareciam no journal.

| Peça | Entrega |
|---|---|
| **`integrations/api/server.py`** | `APIConfig.notifier` (padrão `nomad_tools`: None = bloco ausente quando `OD_NOTIFIER_ENABLED=0`) + bloco `payload["notifier"] = notifier.metrics.snapshot()` no `/dashboard/stats` (ticks, checks_run, problems, alerts_emitted, alerts_blocked, errors). |
| **Card "Alertas" no `/admin`** | Linha nova no `cards` do painel: `X env · Y blq` (classe `err` quando `errors > 0`); o dump JSON completo já cai no details "Métricas do orquestrador". |
| **`runtime/launcher.py`** | `notifier=` nos parâmetros de `build_api_server` e `_run_api_forever`; o modo all passa a instância construída (fechamento tardio — construída antes do `gather` invocar a factory). |
| **`tests/test_notifier.py` +2** | `TestStatsDoNotifier`: bloco **ausente** sem notifier (JSON bruto também sem a chave) · bloco **exato** com notifier (`{ticks:3, checks_run:0, problems:0, alerts_emitted:2, alerts_blocked:5, errors:1}`) + `stats.notifier` presente no HTML do `/admin`. |

| Verificação | Resultado |
|---|---|
| Suíte oficial gate `--cov-fail-under=90` | **2968 passed / 16 skipped · cobertura 90,62%** (+2 testes; 1 warning = pré-existente de `tests/test_orchestrator.py`) |
| pyflakes | **nenhum warning novo** — os 6 apontados em server/launcher conferidos contra o HEAD (idênticos, pré-existentes) |
| Guarda `node --check` do painel | verde (`test_painel_pages_js_compiles`) — o JS do card compilado |
| Estado de produção após o gate | `data/notifier_state.json` intocado (mtime 11:17:11 idêntico antes/depois) |

**Prova viva no serviço (pós-deploy, 16/10 11:38:58, PID 3724539):**
restart verde (regra 7.3 — `c63a4d0` pushado ANTES) · **NRestarts=0** ·
journal **0 erros** · boot `ProactiveNotifier habilitado |
health_ponte=True | nrestarts=True` (boot lento de 90 s — cache do
whisper frio após a suíte; prova coletada após a subida completa às
11:40:28) · **`/dashboard/stats` traz o bloco com números reais**:
`notifier = {ticks: 2, checks_run: 32, problems: 4, alerts_emitted: 1,
alerts_blocked: 2, errors: 0}` · card `"Alertas"` no HTML do `/admin`
(3 × `stats.notifier`) · `/health` **ok, 20/20** · `/app/version`
**1.30.0/2060** (sem bump) · árvore limpa, HEAD == `origin/master`.

**Leitura dos números (tudo explicado):**
- `alerts_blocked: 2` = o `restart` segurado pelo cooldown do alerta
  das 11:17 nos 2 primeiros ticks — **o anti-spam agora visível**.
- Previsão pelo código (não observada ainda): enquanto o cooldown não
  vencer (~12:18) o restart segue bloqueado a cada tick e, ao vencer,
  emite **uma única vez** o alerta atrasado "Sistema foi reiniciado"
  (evento verdadeiro do boot 11:38) e trava em `_restart_reported`.
- `router:down` às 11:41:28 = 5º blip do dia (padrão 00:03 / 01:03 /
  03:00 / 04:41): ping falhou de verdade na hora, push entregue;
  roteador no ar na conferência (3/3, 11,5 ms).

---

### Infra — Conserto do notifier: timestamp de boot antigo não silencia mais `restart`/`llm:offline` + suíte para de gravar o estado de produção (ordem "conserte o notifier", 2026-10-16, sem bump)

> Achado na reverificação das 06:40 (`iniciar/` §4): o
> `data/notifier_state.json` guardava `last_alerts` com monotônicos do
> **boot 29/07 → 11/09** (`restart: 3754164.292`, `llm:offline:
> 3682439.017` — batem com os **últimos** alertas reais das chaves no
> journald: 11/09 00:55:40 e 10/09 05:00:15, conversão pelo boot fecha
> em 3 s). O anti-spam `(now - last) < cooldown` via delta **negativo**
> depois dos reboots ⇒ **35 dias sem 1 alerta `restart` ou
> `llm:offline`** (os 3 restarts de 16/10 mudos; `llm:offline` é
> `severity=crit` — LLM fora = dono sem aviso). Ordem do dono
> **"conserte o notifier"** (~11:10).

| Peça | Entrega |
|---|---|
| **`integrations/notifier.py`** | A carga do `last_alerts` agora **descarta timestamp futuro** (`quando <= agora + 0.01`): monotônico de boot anterior nunca é válido; a folga de 10 ms cobre o `round(v, 3)` do save com relógio congelado nos testes. O `_save_state()` do `__init__` regrava o arquivo **limpo** — a limpeza de `data/` acontece sozinha no restart, sem mutação manual. |
| **`tests/test_nomad_tools.py`** | Fixture `_data_dir_isolada` (mesmo padrão do `test_launcher_health_external`) nos 2 `test_build_notifier_*`: `DATA_DIR` → `tmp_path` + cache de env zerado nos knobs do notifier, com asserção de que `state_file` cai no tmp. **A suíte inteira parou de escrever o estado de produção** (a rodada da madrugada tinha gravado o `pid` do pytest às 04:59:25 — poluição medida em iniciar/ §4). |
| **`tests/test_notifier.py` +2** | Regressão do incidente: (1) carga descarta `restart: 3_754_164.292` e regrava o arquivo limpo **preservando** o `router:down` legítimo; (2) comportamento: com o veneno no arquivo, o alerta `restart` **emite** (antes: bloqueado pelo delta negativo). |

| Verificação | Resultado |
|---|---|
| Suíte oficial gate `--cov-fail-under=90` | **2966 passed / 16 skipped · cobertura 90,62%** (+2 testes; 1 warning pré-existente de `tests/test_orchestrator.py`, conferido isolado) |
| pyflakes | limpo nos 3 arquivos tocados |
| Estado de produção após a suíte | `data/notifier_state.json` **intocado** (mtime 04:59:25 idêntico) |
| Resíduo da rodada | rotação de log do serviço criou `logs/interface_monitor.log.1` fora dos padrões do `.gitignore` → padrão `logs/*.log.*` adicionado (commit `d0d0cba`) |

**Prova viva no serviço (pós-deploy, 16/10 11:17:09, PID 3703628):**
restart verde (regra 7.3 — `5fcdd3b` e `d0d0cba` pushados ANTES) ·
**NRestarts=0** · journal **0 erros** · boot `ProactiveNotifier
habilitado | health_ponte=True | nrestarts=True | disco_pct=85.0` ·
**11:17:10 `key=restart` EMITIDO — o primeiro em 35 dias** (prova do
desbloqueio) + push FCM `enviados=1` · `data/notifier_state.json`
**LIMPO** (`llm:offline` e o `restart` velho fora; `router:down`
legítimo preservado; `restart` regravado com o relógio novo) ·
`/health` **ok, 20/20** · `/app/version` **1.30.0/2060** (backend puro,
sem bump) · árvore limpa, HEAD == `origin/master`.

---

### Infra — Observabilidade/Alertas Telegram (TODO §3.6): `/health` degraded + `NRestarts` + disco configurável (ordem `ordem_a_observabilidade_alertas_2026_10_16`, 2026-10-16, sem bump)

> Pedido do dono **"a"** (~04:30) = item **(A)** da fila do TODO §7.
> Backend puro (nenhuma linha de app/site mudou) → **sem bump**,
> 1.30.0/2060 intacto. Apuração no código antes de escrever qualquer
> linha: **(1)** ponte `/health` → Telegram **não existia** — o notifier
> cobria 6 sondas e o HealthMonitor tem 20 checks; audit, metrics,
> database, mqtt, perception e auto_update degradavam **sem ninguém
> receber nada**; **(2)** `NRestarts > 0` **não existia** — só havia
> "PID mudou" (pegava o restart autorizado, não a queda anormal que o
> systemd ressuscita); **(3)** disco > 85% **já existia** (`_check_disk`,
> limite do legado) e faltava prova de fogo.

| Peça | Entrega |
|---|---|
| **`integrations/notifier.py` — ponte do `/health`** | `_check_health` (async, **última** sonda do tick de propósito: as tools já enchem o cache de 10s que o HealthMonitor compartilha) roda o HealthMonitor real por tick e vira alerta. **Dedupe `SAUDE_JA_COBERTA = ("tool_", "orchestrator", "llm", "loops")`**: falha já gritada por sonda dedicada não dispara o agregado (sem mensagem dupla); o detalhe lista **só** o que ninguém cobre, mas o total ("N check(s) fora") é honesto. `degraded` → warn **após 120s** (restart/compose up legítimo não grita), `down` (crítico) → **crit na hora**; `health_monitor=None` → sonda fora. Duas chaves (`health:degraded`/`health:down`) com baixa explícita nas duas — sem entrada zumbi em `active_problems` (o próprio `_check_llm` já tinha esse formato de limpeza). |
| **`integrations/notifier.py` — `NRestarts`** | `nrestarts_do_systemd(unit)`: `systemctl --user show <unit> -p NRestarts --value`, timeout 5 s, **`asyncio.to_thread`** (subprocess não prende o loop). **`None` → ok**: desconhecido (sem binário, sem bus, valor não-numérico) **nunca** vira alerta nem dá baixa — a baixa só vem de leitura `0` de verdade. Sonda `_check_nrestarts`: **warn ≥ 1**, **crit ≥ `CRASH_LOOP_RESTARTS` (3)**; `nrestarts_fn` injetável (testes/fake). |
| **`runtime/launcher.py`** | `build_notifier(..., health=health)` ligado no `_all()`. Kill-switches `OD_NOTIFIER_HEALTH=0` e `OD_NOTIFIER_NRESTARTS=0`; `OD_SERVICE_UNIT` (padrão `od-core.service`); a sonda de NRestarts **só liga dentro de serviço systemd** (`INVOCATION_ID`) ou com unit explícita — suíte/CI nunca dispara `systemctl`. `OD_DISK_THRESHOLD_PERCENT` (padrão **85**, o do legado, agora configurável). Log de boot como prova: `ProactiveNotifier habilitado \| health_ponte=True \| nrestarts=True \| disco_pct=85.0`. |
| **fix embutido (achado pela própria prova de fogo)** | `format_alert` fazia `time.localtime(alert.ts)` em cima do `ts` **monotônico** → a mensagem saía com data tipo **"(31/12 21:16)"** (valia para TODOS os alertas antigos, `router:down` incluso). `Alert` ganhou `wall = time.time()` carimbado **em `_emit`**; `ts` monotônico continua no comando do anti-spam/`emit_after_s` (é para isso que serve). |

| Verificação | Resultado |
|---|---|
| Suíte oficial gate `--cov-fail-under=90` | **2964 passed / 16 skipped · cobertura 90,60%** — **+29 testes** (`tests/test_notifier.py` 70, +22: ponte com delay/recuperação/dedupe/down/sonda quebrada/ordem do tick, NRestarts 0/1/3/recuperação/leitura parseada, exibição `wall`; `tests/test_launcher_health_external.py` 21, +7: wiring + kill-switches + limiar de disco) |
| Prova de fogo (sandbox, sink REAL do Telegram) | `ProactiveNotifier` real com os **dois probes novos** + `build_telegram_sink()` real: **6 mensagens entregues** ao chat do dono, marcadas `[PROVA DE FOGO 3.6 — sandbox]` (3 no 1º run — que **reproduziram o bug de data** — e 3 no re-run pós-fix, já com `(16/10 04:47)`). Prova do caminho inteiro: probe → `format_alert` → sink async → API do Telegram. |
| pyflakes | limpo em `notifier.py`, `launcher.py` e nos 2 testes (os 3 avisos do launcher são pré-existentes — conferidos contra `HEAD` com `git show`) |

**Prova viva no serviço (pós-deploy, 16/10 04:51:49, PID 3367820):**
restart verde (regra 7.3, código em `a67a6f6` pushado ANTES) ·
**NRestarts=0** · journal **0 erros** · **0 alertas proativos** desde o
boot (o 1º tick já correu com a ponte ligada e **não** gritou — nada
degraded, NRestarts 0) · `/health` **up, 20 checks, nenhum fora** ·
`/app/version` **1.30.0 / 2060** (sem bump) · leitor real
`nrestarts_do_systemd("od-core.service")` → **0** no ambiente do
serviço · árvore limpa, HEAD `a67a6f6` == `origin/master`.

**Lição registrada:** medir o gap antes de codar (6 sondas × 20 checks)
e deixar "desconhecido" calar — sonda que não entende o ambiente
responde ok, não grita; e a prova de fogo pagou o próprio custo ao
pegar a data errada das mensagens antes do dono reclamar.

---

### Infra — RAG: memória histórica no corpus (`iniciar/`) + recalibração medida do floor duplo (ordem `ordem_rag_2026_10_16`, 2026-10-16, sem bump)

- **Corpus externo:** `fontes_padrao()` indexa **`iniciar/*.md`** (32
  transcrições + RULES — as formulações naturais das perguntas do dono,
  interna) além de `docs/` + `knowledge/`; o hash do alvo `indice-rag`
  acompanha as 3 pastas (editar transcrição resynca sozinho). Corpus
  **895 → 1.598 chunks**. `TODO.md` ficou DE FORA por decisão medida:
  muda a cada sessão (churn de IDF puro) e nenhuma linha vencedora do
  grid veio dele.
- **Recalibração COM medição (nunca afrouxamento):** grid `ms` 0.380–0.420
  × `mo` 0.000–0.060 (passo 0.001) no corpus real, validado pelo
  `consult()` de verdade: **780 células** mantêm o gate **8/8
  relevantes + 8/8 irrelevantes bloqueadas** e sobem o recall de
  parafrases (pergunta natural sem termo raro em comum) de **1/8 → 6/8**
  (no floor velho com o corpus novo: 1/8; corpus velho: 3/8). Centro
  medido: `PISO_SCORE` **0.36 → 0.399**, `PISO_OVERLAP` **0.22 → 0.036**.
  Floor duplo load-bearing dos dois lados: `ms` prende a consulta de
  clima (comb 0,3929 — colisão REAL: o corpus documenta a action
  `weather_city`), `mo` prende as irrelevantes sem termo raro
  (ov 0,000), teto do `mo` = 0,071 = ov da parafrase "contêiner".
  Fronteira ±0,006: o gate de calibração é o tripwire (procedimento no
  docstring da classe).
- **Embedding semântico: MEDIDO E RECUSADO** — spike `fastembed` (MiniLM
  multilingual int8, ONNX in-process; a 8081 é llama-server e devolve
  **501 em embeddings**; box com ~1,7 GB de RAM livre). Medido: re-embed
  39 s / busca 46 ms / consulta 7 ms — mas **quebra o gate de
  precisão**: a consulta de clima sobe para cosseno **0,546** > relevante
  mínimo **0,394** e **nenhuma chave separa** (fusão linear `sem×ov`
  provada impossível, suporte top-3, mean-center e PCA-3 — `irr.max >
  rel.min` em todas); mpnet descartado na triagem (**3,8 GB RSS**,
  419 s/895 chunks). Provider do hash permanece; pegue de integração
  anotado (`numpy.float32` não serializa no store).
- **+6 testes** (`TestRecallParafrases` — as 6 medidas passam; as 2
  perdidas documentadas como ESTRUTURAIS: Δ0,0007 contra a consulta de
  clima). `tests/test_rag.py` 85, `test_auto_update.py` 60.
- **Suíte: 2935 passed, 16 skipped** · cobertura **90,60%** (gate 90).
- **Prova viva (pós-deploy, 16/10 03:39, PID 3300626):** restart verde
  (NRestarts=0, journal **0 erros**) · boot `RAG corpus sincronizado |
  chunks=1598 | novos=703 | iguais=895` + 2º sync idempotente
  `iguais=1598` · store no disco 1.598 (hash 256-d) · `/health` **up**
  com **tools 9/9**.
- Sem bump: backend/infraestrutura, sem mudança de app ou site.

---

### Infra — As 9 ferramentas do stack Nômade entram no `/health` + alerta no Telegram (DECISÃO FINAL, 2026-10-15, sem bump)

- **`core/nomad_tools.py` (NOVO):** `FERRAMENTAS_NOMAD` (as 9 do
  `docker/tools-compose.yaml` — portas conferidas no `docker inspect`,
  bind 127.0.0.1) + `NomadToolsMonitor`: sonda HTTP por ferramenta
  (stdlib, `http.client`) com **cache TTL 10s** compartilhado entre
  `/health`, notifier e `/dashboard/stats`. Semântica medida: **status
  < 500 = viva** (Calibre Web responde 302 na raiz e ferramentas com
  auth 401/403 — recusar seria alerta falso eterno); 5xx, timeout ou
  conexão recusada = fora. Vaultwarden é sondado em `/alive` (rota de
  health nativa).
- **`/health` +9 checks não-críticos** (`tool_kiwix` …
  `tool_vaultwarden`): uma ferramenta fora **degrada** o `/health` em
  vez de derrubá-lo (lição da Parte E — check quebrado também não
  derruba o monitor, provado por teste).
- **Alerta no Telegram** (`_check_tools` no ProactiveNotifier, chave
  `tool:<nome>`): ferramenta fora por **120s+** vira alerta (um
  `docker compose up -d` legítimo derruba a porta 10-30s e não deve
  gritar), com o anti-spam de 1/hora do notifier; a volta limpa o
  problema. Motivação registrada: Stirling PDF ficou **1.917 restarts**
  em crash loop e o Kiwix **763** (12/10) sem ninguém receber alerta —
  o stack era invisível.
- **`/dashboard/stats` + bloco `nomad_tools`** (total/up/fora) e card
  "Stack Nômade" + `<details>` no painel `/admin`.
- **Gate `OD_NOMAD_TOOLS=0`** decide no launcher (fonte `.env`);
  `OD_NOTIFIER_ENABLED=0` continua desligando tudo junto.
- **+44 testes** (`tests/test_nomad_tools.py` — catálogo, sonda
  hermética, cache, contrato do HealthMonitor, probe com `http.server`
  real em porta efêmera, anti-spam/emit_after_s do notifier, wiring do
  launcher e as 2 rotas do painel). `core/nomad_tools.py` a **100%**.
- **Suíte: 2914 passed, 16 skipped** · cobertura **95,43%** (gate 90) ·
  `node --check` do JS do painel verde. Sem bump: backend/infraestrutura,
  sem mudança de app ou site.

---

### Infra — Vaultwarden fechado (conta do dono + signups) e action `nomad_vaultwarden_setup` consertada (2026-10-15, sem bump)

- **Conta do dono criada** via `POST /identity/accounts/register` com payload
  `RegisterData` completo (KDF PBKDF2-SHA256 600k, user key AES-256-CBC-HMAC
  embrulhada, RSA-2048 com PKCS8 embrulhado) gerado pelo **SDK oficial**
  (`@bitwarden/sdk-internal`). Verificação E2E com **CLI oficial `bw` 2026.8.0**:
  login + sync + roundtrip de pasta (cifrada → servidor → decifrada); conta de
  teste do drill excluída via `/api/accounts/delete` — vault só com o dono.
- **Signups fechados de verdade:** `SIGNUPS_ALLOWED=false` no compose, container
  recriado, env aplicada conferida; registro de fora → HTTP 400; login do dono
  segue funcionando após o restart.
- **Action consertada** (`nomad_vaultwarden_setup`): a rota antiga
  `/api/accounts/register` dava 404, o payload era cru (`{email, masterPassword}`),
  o retorno inventava um `token` inexistente e "desabilitar signups" só imprimia
  uma instrução (sucesso falso). Agora: rota `/identity/accounts/register`,
  payload `RegisterData` com crypto própria (`_vw_hkdf_expand`/`_vw_encstring`/
  `_vw_register_payload` — HKDF-Expand RFC 5869, EncString tipo 2, PBKDF2 600k)
  **validada byte a byte contra o SDK oficial** (oráculo 4/4), fechamento real
  (edita compose → `compose up -d` → confere env do container) e erros honestos
  (`registro_recusado` com o HTTP do servidor, `signups_nao_fecharam`).
  **+7 testes** (formato do payload, roundtrip interno, rota/método/corpo, 400,
  e os 3 do fechamento + registry).
- **Achados do dia registrados:** `DOMAIN` do Vaultwarden corrigido ontem
  (`3ed13cc`); `bw` CLI ≥ 2026.9 incompatível com o prelogin do servidor
  1.36.0 (espera `kdfSettings`/`Salt`; flag `pm-27060` fora do allowlist do
  servidor — TODO §4; web vault empacotada e app seguem OK).
- **Suíte: 2870 passed, 16 skipped** (+7). Sem bump: backend/infraestrutura,
  sem mudança de app ou site.

---

## [1.29.0] — SUPPLY DEPOT: REGISTRO DE FERRAMENTAS/SKILLS (PARTE F DO NOMAD) 🜂 (2026-10-15)

> **Bump MINOR (capacidade nova):** Parte F da ordem do dono
> (A → C → B → D → E → **F**), aprovada com "faça a parte F". O catálogo
> de tools do orquestrador vira registro de verdade no estilo Supply
> Depot do Nômade: **pré-voo** (conflito, versão, tamanho) antes de
> qualquer entrada, **rollback** de toda atualização e **customização
> do dono que sobrevive** à troca. Fecha também o buraco do `/gerar`:
> ferramenta gerada via LLM existia só em memória (reiniciou o core,
> sumia) e devolvia "ok" mesmo quando o registro foi pulado por conflito.
> Nada de dependência nova — stdlib + o próprio `ActionRegistry`, como
> manda a casa.

| Peça | Entrega |
|---|---|
| **`tools/supply_depot.py` (novo)** | `preflight()` PURO (injeções do `avaliar()` da Parte E — testável sem I/O) com as camadas em ordem: ① nome canônico válido (regra do auto-extension, nunca vira path) → ② tamanho do código (limite 8000 chars do `/gerar`) → ③ espaço em disco (bytes × 1,1 — MESMA margem da Parte E) → ④ CONFLITO (no registry mas fora do depot = ferramenta alheia, não substituímos) → ⑤ VERSÃO (semver: igual → `sem_acao`, menor → `downgrade_bloqueado`, major → `major_requer_confirmacao` só com `substituir=true`; versão-hash não tem major). Cada decisão com motivo. |
| **Instalação atômica + rollback automático** | Fluxo `instalar()`: pré-voo → valida sintaxe/allowlist (MESMO gate do auto-extension) → extrai a função → backup da versão atual (`data/ferramentas_backup/<id>.v<versao>.py` + histórico) → grava código e catálogo (tmp→rename) → troca a action no registry. Qualquer falha no meio ⇒ **rollback total**: arquivo + catálogo + action antigos restaurados de um snapshot em memória, resultado com `rollback=true` e o motivo. |
| **Rollback manual síndico** | `POST /admin/ferramentas/{id}/rollback` (ou `versao` no body): restaura arquivo + entrada + action; a versão ATUAL entra no histórico junto — rollback pode ser desfeito (rollback do rollback). Histórico limitado a 5 versões por ferramenta. |
| **Customização que sobrevive** | `PUT /admin/ferramentas/{id}` grava sobrescritas (`descricao`/`params`/`permission`) em `custom` — reaplicadas no registro de CADA versão nova e presentes no snapshot de rollback. Atualizou, reiniciou, rollbackou: a sua descrição continua lá. `ativa: false/true` desinstala/reativa sem destruir (arquivo preservado no backup). |
| **`/gerar` persistente + pré-voa antes do LLM** | O `AutoExtension.extend()` ganhou `depot`: conflito/downgrade/major são decididos ANTES de chamar o LLM (zero token gasto — antes: gerava, pulava o registro em silêncio e dizia "ok"); no fim, `depot.instalar()` persiste em `data/ferramentas/<id>.py` + `data/ferramentas_catalogo.json`. Status honestos no bot: `exists` ("já está instalada") e `conflict`/`blocked` ("pré-voo bloqueou"). `substituir=True` dá bump de patch com histórico. |
| **Restauração no boot** | `build_supply_depot()` no launcher carrega o catálogo antes do auto-extension e registra as ativas (código corrompido = warn + fica de fora, nunca derruba o boot). Ferramenta gerada **sobrevive a restart** — o buraco que motivou a Parte F. Health check `supply_depot` não-crítico detecta dessincronia com o registry. |
| **Rotas + painel + stats** | `ROUTES` 73 → 78: `GET/POST /admin/ferramentas` (lista com estado vivo / instala-atualiza com pré-voo no caminho — 201 instala, 200 atualiza, **409** pré-voo bloqueou, 400 código rejeitado, 500 rollback), `PUT .../{id}` (customização), `POST .../{id}/rollback`, `DELETE .../{id}` (desinstala preservando arquivo no backup); todas admin e 503 `supply_depot_indisponivel` sem depot. `/dashboard/stats` ganha o bloco `ferramentas`; painel `/admin` ganha a seção **Ferramentas (Supply Depot)** com formulário (nome+versão+descrição+código), tabela (origem/tam/custom/histórico), ✎ editar descrição, ⟲ rollback e ✕ desinstalar. |
| **Manifesto de catálogo** | `data/ferramentas_catalogo.json` (atômico, `_comentario` explicando o `custom`): id, função, versão, origem, sha256/bytes do código, `anteriores` (snapshots das versões antigas com ponteiro para o arquivo no backup) e `ativa`. `data/ferramentas/` guarda o código vivo; `data/ferramentas_backup/` o histórico e os removidos. |
| **versionCode** | 2058 → 2059 (regra §5.3 — sem mudança de código no app, mas o par pubspec/OD_VERSION é guardado pela política). |

| Verificação | Resultado |
|---|---|
| Suíte do servidor (gate `--cov-fail-under=90`) | **2863 passed / 16 skipped · cobertura 90,52%** (+91 testes da Parte F; `tools/supply_depot.py` a **95%**) |
| Guardas | `ROUTES` 73 → 78 em `tests/test_api.py` (5 rotas novas todas admin) |
| Teste de JS do painel | `node --check` do JS SERIDO verde |
| **Prova viva no serviço (15/10, PID 2410050)** | 3 fases na API de produção (abaixo) |

**Prova viva no serviço (15/10, PID 2410050 — NRestarts=0, journal 0 erros):**

| Fase | Resultado |
|---|---|
| Boot (deploy) | `Supply Depot no ar (Parte F NOMAD) \| carregadas=0 \| erros=0 \| catalogo=0` (PID 2405509); `/health` **up** com `supply_depot: up` ("supply-depot: 0 no catálogo"); `/capabilities` 47 com `tool-supply-depot`; `/app/version` **1.29.0 / 2059** com sha == APK publicado (`c23ff4ee…`) |
| Ciclo de vida completo | `POST /admin/ferramentas` `proof.soma` → **201** `instalar_nova (v1.0.0)` (sha256 no manifesto); repetido → **200** `sem_acao (ja_instalada)` (idempotente); instalar por cima da action alheia `system_info` → **409** `conflito: …já existe no registry e não é do depot`; update `1.0.0 → 1.0.1` → **200** + backup `data/ferramentas_backup/proof.soma.v1.0.0.py` (116 B); `PUT` descrição do dono → **200**; update `1.0.2` → descrição **ainda** a do dono no `/actions` (custom sobreviveu); major `2.0.0` → **409** `major_requer_confirmacao (1.0.2 → 2.0.0)`; rollback → **200** `de=1.0.2 para=1.0.1` com descrição do dono **ainda** lá; `/executa proof.soma {a:10,b:4}` → **`result: 6`** (ferramenta executa ao vivo); `DELETE` → **200**, catálogo/stats em 0, arquivos preservados no backup (não destrutivo) |
| Persistência no boot (a prova central) | Instalado `proof.persist` → restart → journal **`Supply Depot restaurado no boot \| carregadas=1 \| erros=0 \| catalogo=1`** (PID 2409472) + `/actions` ainda com a ferramenta + `/executa` → **"sobrevivi ao restart"** + `/health` "supply-depot: 1 no catálogo" |
| Painel ao vivo | Seção **Ferramentas (Supply Depot)** servida no `/admin` (formulário, tabela, ✎/⟲/✕) |
| Restauração | Resíduos da prova apagados (`data/ferramentas*`), restart limpo (PID 2410050): boot `carregadas=0 \| erros=0 \| catalogo=0`, `/health` up, lista 0, journal 0 erros, NRestarts=0 |

---

## [1.28.0] — AUTO-UPDATE DE MODELOS/CONTEÚDO (PARTE E DO NOMAD) 🜂 (2026-10-14)

> **Bump MINOR (capacidade nova):** Parte E da ordem do dono
> (A → C → B → D → **E** → F), aprovada com "pode fazer a parte E".
> O servidor se atualiza sozinho, mas com as rédeas do Nômade: janela
> noturna, cool-off ancorado em "primeiro visto", só minor/patch, cap de
> bytes, auto-disable após 3 falhas duras e pre-flight — tudo num
> `avaliar()` PURO que o dry-run do painel executa pelo MESMO caminho do
> ciclo de produção. Nada de dependência nova — stdlib pura, como manda
> a casa.

| Peça | Entrega |
|---|---|
| **`core/auto_update.py` (novo)** | `avaliar()` puro (relógio/estado/disco/alvos injetáveis) com as 8 camadas em ordem, cada decisão com motivo registrado: ① auto-disable → ② inativa no manifesto → ③ sem mudança → ④ major (só minor/patch automático; versões-hash não têm major) → ⑤ janela → ⑥ cool-off → ⑦ backoff pós-falha → ⑧ cap de bytes + pre-flight (disco × 1,1, sha256 com 64 hex, URL http(s)). |
| **Cool-off com física honesta** | Âncora em "primeiro visto" que RECOMEÇA quando a versão vista muda (versão nova sempre paga o cool-off inteiro — a release queimada nunca entra de supetão). Com o default (6 h de cool-off numa janela de 4 h) a aplicação cai na PRÓXIMA janela: soak real de até ~1 dia, que é o que o cool-off quer comprar; conteúdo local (índice RAG) zera o cool-off. |
| **Executor contido** | `AutoUpdateService.tick()` avalia e executa: `rag_sync` idempotente (VectorStore tem RLock — roda em thread sem travar busca) e `baixar` enfileirado na fila da Parte D (retomada/sha256/dedup de graça). Sucesso/falha do download chegam pelo consumidor dos eventos da fila; só falha DURA conta para o auto-disable (`skip` não conta, padrão do Nômade). Estado atômico em `data/auto_update_estado.json`; religar é do dono (reset zera falhas). |
| **Manifesto editável** | `data/auto_update_alvos.json` (lockfile declarativo, criado no boot com exemplo — edição sua nunca é sobrescrita): url + sha256 + versão de destino por alvo de arquivo; `pos_download: mover` faz `os.replace` atômico travado na árvore do repo (fora da raiz = falha permanente). Troca de modelo EM USO é decisão explícita do dono — aqui a peça chega pronta e conferida. |
| **Alvo vivo de hoje** | `indice-rag`: hash do conteúdo de `docs/` + `knowledge/` como "versão" — editou um `.md`, o próximo ciclo na janela ressincroniza o índice SEM reboot (antes o RAG só refreshava no boot). |
| **Rotas + painel + stats** | `GET /admin/auto-update` (config + alvos + estado + decisões), `POST .../dry-run` (avalia sem executar/gravar — o MESMO caminho do ciclo) e `POST .../reset` (religa alvo desligado), todas admin e 503 `auto_update_indisponivel` sem serviço. `/dashboard/stats` ganha o bloco `auto_update`. Painel `/admin` ganha a seção **Auto-update** com config vigente, tabela de alvos com status/falhas, botão 🧪 dry-run (mostra o que o próximo ciclo faria) e ⟳ religar. |
| **Loop supervisionado** | `_run_auto_update_forever` no `_supervise` do launcher (uma queda não derruba o core), tick em `asyncio.to_thread` (o sync do RAG pode embutir chunks — I/O pesado não prende o loop do Telegram/WebSocket), health check `auto_update` não-crítico, `OD_UPDATE_ENABLED=0` desliga. Fila da Parte D agora é compartilhada entre a API e o auto-update (construída uma vez no modo all). |
| **versionCode** | 2057 → 2058 (regra §5.3 — sem mudança de código no app, mas o par pubspec/OD_VERSION é guardado pela política). |

| Verificação | Resultado |
|---|---|
| Suíte do servidor (gate `--cov-fail-under=90`) | **2771 passed / 16 skipped · cobertura 90,41%** (+59 testes da Parte E; `core/auto_update.py` a **94%**) |
| `flutter analyze` | **0 issues** |
| `flutter test` | **174 passed / 2 skipped** |
| Guardas | `ROUTES` 70 → 73 em `tests/test_api.py` (3 rotas novas todas admin) |
| Teste de JS do painel | `node --check` do JS SERIDO verde (o `\n` do dry-run teve que sair do literal Python: `String.fromCharCode(10)`) |

**Prova viva no serviço em produção (14/10, PID 1608225)** — três fases,
sem fake:

| Passo | Resultado |
|---|---|
| Boot (config padrão) | `Auto-update no ar \| janela=02:00-06:00 \| rag=ligado` + loop supervisionado habilitado; tick de boot `alvos=1 \| aplicar=0 \| resumo=indice-rag=aguardar` (janela viva às 19:27) |
| Executor (janela larga temporária) | `Índice RAG re-sincronizado (auto-update) \| arquivos=18 \| chunks=862` + `enfileirou download \| alvo=proof-modelo \| job=dl-0001 \| bytes=10485760` → `download concluído e verificado` em **7 s**, staged com **sha256 == pin do manifesto** (`e5b844cc…`) |
| Idempotência | `GET /admin/auto-update`: `indice-rag` instalada=`50ab0b74d8c8`, `proof-modelo`=`1.0.0`, 0 falhas; dry-run seguinte: ambos **`pular \| sem_atualizacao`** |
| Bug achado e corrigido no ar | `HealthMonitor` chama `check(monitor)` — assinatura sem argumento derrubava o check (TypeError, /health degraded). Fix + teste de regressão + /health **up** revalidado |
| Restauração | `.env`/manifesto de volta ao padrão, resíduos apagados (staged + estado + dl-0001), restart limpo: `indice-rag=aguardar`, journal 0 erros, NRestarts=0 |

---

## [1.27.0] — FILA DE DOWNLOADS RESUMABLE (PARTE D DO NOMAD) 🜁 (2026-10-14)

> **Bump MINOR (capacidade nova):** Parte D da ordem do dono
> (A → C → B → **D** → E → F), aprovada com "pode fazer a parte D". Fila
> de downloads que não perde 14 GB por causa de um restart: retomada por
> `Range`, retry com backoff, dedup, cancelamento preservando o parcial e
> progresso ao vivo por SSE no painel e no app. Nada de dependência nova —
> `urllib` + `threading` da stdlib, como manda a casa.

| Peça | Entrega |
|---|---|
| **`core/downloads.py` (novo)** | `DownloadQueue` com worker próprio (thread daemon + `Condition`): stream por `urllib` com `Range: bytes=N-` a partir do `.part` já gravado (servidor sem Range → 200 reinicia do zero sozinho; 416 → recomeça uma vez). sha256 incremental — o prefixo de um `.part` retomado entra no mesmo hasher — e `os.replace` atômico no fim (arquivo pronto nunca aparece pela metade). |
| **Retry que sabe parar** | Falha transitória (timeout 30 s, conexão, 5xx, 408/425/429) reagenda com `backoff = min(2·2^(tentativa−1), 60 s)` e o job fica `aguardando` COM `proximo_retry` visível; 404/403/sha256 divergente caem direto em `erro` sem queimar tentativa. Stream cortado abaixo do `Content-Length` anunciado é transitório, não sucesso silencioso. |
| **Restart não zera nada** | `stop()` no meio do stream não cancela: o job volta para `na_fila`, o `.part` fica e o boot re-enfileira (`data/downloads_fila.json`, escrita atômica). Teste `test_stop_reenfileira_o_que_estava_em_voo` + restauração `baixando → na_fila` com o parcial medido em disco. |
| **Dedup + destino travado** | Mesma URL+destino com job ATIVO devolve o job existente (200, `duplicado: true`) — nunca dois workers no mesmo arquivo. Destino sempre DENTRO de `OD_DOWNLOADS_DIR` (sem `..`, sem caminho absoluto); histórico terminal recortado em 50 (arquivos nunca são apagados pela fila). |
| **SSE (`GET /admin/downloads/events`)** | Abre com `snapshot` da fila inteira, depois empurra `estado`/`progresso`/`removido`; `: ping` quando 15 s passam sem eventos (keepalive atrás de proxy — enquanto há progresso o próprio fluxo mantém o canal vivo). Cada assinante tem fila própria (overflow descarta o mais antigo) — um cliente lento nunca trava o worker. `APIServer.stop()` ganhou sinal `encerrando`: sem ele, o `server_close()` do `ThreadingHTTPServer` esperaria o handler SSE nos 15 s de ping **em todo restart**. |
| **Rotas + painel + métricas** | `POST/GET /admin/downloads`, `/events`, `/{job_id}`, `/{job_id}/cancel`, `DELETE /{job_id}` (409 `job_ativo` — apagar só registro terminal, arquivo intocado), todas admin e 503 `downloads_indisponivel` sem fila. `/dashboard/stats` ganha o bloco `downloads` (contagens por estado + bytes gravados). Painel `/admin` ganha a seção **Downloads** com enfileirar, barra de progresso, cancelar/apagar e atualização ao vivo por `fetch` + `ReadableStream` (o JS passou no `node --check` da suíte — o `\n` do split tem que ser escapado dentro do literal Python). |
| **App (7ª aba "Downloads")** | `OdApi`: `listDownloads`/`createDownload`/`cancelDownload`/`deleteDownload` + `streamDownloads()` (SSE com `http.Client.send`, timeout só na abertura). A aba mostra fila, selo por status, barra, tentativas e a etiqueta `📡 ao vivo (SSE)`; quando o stream morre (restart/rota) cai para polling de 5 s e reassina em 15 s — mesmo contrato do chat, que cai do WebSocket para o REST. `_initialIndex` do modo avançado foi para 6 (Config é a 7ª aba agora). |
| **versionCode** | 2056 → 2057 (regra §5.3). |

| Verificação | Resultado |
|---|---|
| Suíte do servidor (gate `--cov-fail-under=90`) | **2712 passed / 16 skipped · cobertura 90,28%** (+46 testes da Parte D; `core/downloads.py` a **95%**) |
| `flutter analyze` | **0 issues** |
| `flutter test` | **174 passed / 2 skipped** (+17: REST, SSE e tela) |
| Guardas | `ROUTES` 64 → 70 em `tests/test_api.py` (6 rotas novas todas admin) |

**Prova viva no serviço em produção (14/10, PID 1517294)** — fila real, sem
fake, contra `proof.ovh.net` (100 MB com Range):

| Passo | Resultado |
|---|---|
| Enfileirar pela API pública | `POST /admin/downloads` → `dl-0001` (201), `na_fila` → `baixando` a ~2 MB/s |
| Progresso ao vivo | SSE capturou `snapshot` + **42 eventos `progresso`**; fila ociosa → **1 `: ping`** exatamente aos 15 s |
| Integridade | `sha256_real` do job **== `sha256sum`** do arquivo em disco (`20492a4d…`) |
| Dedup | POST idêntico durante a transferência → **HTTP 200 `duplicado: true`** com o MESMO job (nenhum segundo worker) |
| Cancelamento em 28,5 MB | `dl-0002` → `cancelado`; `.part` preservado com **o mesmo tamanho do contador** (28 573 696 B); o arquivo final já existente ficou intocado |
| Retomada | `dl-0003` na mesma URL: em 4 s já acusava **33,5 MB** (do zero, naquela taxa, seriam ~8 MB) e terminou com o **MESMO sha256** do download integral — cauda de 71 MB byte a byte |
| Higiene | no sucesso o `.part` some do disco (`os.replace` atômico); `data/downloads` final com só o arquivo pronto |

**Fronteira honesta:** a fila ainda não tem consumo automático — enfileirar
é manual (painel/app). A **Parte E** é justamente isso: janela, cap de
bytes, cool-off e auto-disable ligados ao que o assistente precisa baixar
(modelos de voz/LLM, índice RAG), usando esta fila como motor.

## [1.26.0] — PIPELINE RAG DE QUALIDADE (PARTE B DO NOMAD) 🜂 (2026-10-14)

> **Bump MINOR (capacidade nova):** Parte B da absorção do Project NOMAD —
> o maior esforço e o maior ganho de qualidade da análise — aprovada pelo
> dono com "pode fazer parte B". Tudo determinístico: NENHUMA chamada de
> LLM no retrieval; a única IA no caminho é o modelo que recebe o prompt.

| Peça | Entrega |
|---|---|
| **`memory/rag.py` (novo)** | Pipeline completo: reescrita de consulta com histórico (anafóricas/elípticas "e o preço dele?" agregam termos recentes; consultas autossuficientes passam intactas), busca com embeddings SEM stopwords nos dois lados, **floor duplo medido** (score combinado `0.8·cosseno + 0.2·overlap-IDF ≥ 0.36` E `overlap-IDF ≥ 0.22`) e reranker que reordena pelo combinado. |
| **Corpus interno + visibilidade por papel** | `docs/*.md` + `knowledge/*.md` indexados (850 chunks medidos no boot do serviço em 14/10) com ingestão IDEMPOTENTE: `doc_id` determinístico (fonte+índice) + SHA do conteúdo; editou o arquivo → chunk substituído; removeu/renomeou → órfãos apagados. Chunks são `interna`: o papel `user`/anônimo **nunca** recebe bloco no prompt (testado: 12 candidatos descartados no gate de visibilidade). |
| **Orçamento de contexto com métrica do descartado** | O bloco de referência respeita a janela do modelo (`ContextManager`): `janela − system − histórico − resposta − data/hora`. O que não coube vira métrica (`rag_descartados`, `rag_tokens_descartados`), nunca silêncio. Etapa **4.5** no REST **e** no stream (mesmo contexto nos dois transportes); fastpaths (hora, clima, saúde, matemática, segredos) respondem ANTES — nunca pagam o custo do RAG. |
| **Calibração por modelo** | `JANELAS_MODELOS` com o `n_ctx` medido no host (`od-llm` roda `llama-server --ctx-size 8192` para qwen2.5-coder-3b); `OD_LLM_MODEL` escolhe a janela; orçamento do histórico liga só quando há RAG. |
| **Calibração do floor COM MEDIDA** | Score vetorial puro NÃO separava relevante de irrelevante no corpus real (irrelevante 0.496 > relevante 0.444 — stopwords dominavam o cosseno). A regra de duas chaves acima passa **8/8 queries relevantes e bloqueia 8/8 irrelevantes** (16 queries medidas em 2026-10-14). As 16 medições viraram GATE na suíte (`TestCalibracaoCorpusReal`): falhou = recalibrar com evidência, nunca afrouxar no escuro. |
| **Prova de fogo no serviço vivo (2 disse bordas medidas)** | A primeira consulta de acervo em produção expôs: (1) prefixo de instrução ("responda curto: ...") inflava a soma_idf com idf de palavra rara de comando — overlap 0.211 < 0.22 → **0 trechos e o LLM respondeu INVENTANDO as "regras"** em vez de citar o doc; (2) `top_k` 12 deixava o chunk certo do doc na posição 15 da busca, fora do pool. Correções: `termos_da_consulta()` (só o prefixo curto antes de `:` sai do floor — a busca vetorial continua com a frase crua) e `top_k` 12 → **24**. Re-calibração com o código final: 8/8 + 8/8 preservados; 7 testes novos cobrem as duas bordas. |
| **Eval estendido (Parte A serve à Parte B)** | Expectativas `prompt_contem`/`prompt_nao_contem` nos goldens: provam em modo **oracle (sem rede, sem LLM)** que o contexto recuperado — ou a visibilidade por papel — chegou (ou não) ao prompt. 4 goldens novos (2 em oracle+e2e, 1 user sem vazamento, 1 noretrieval sem bloco). O modo `noretrieval` agora desliga o RAG de propósito e um golden prova que está desligado. |
| **`VectorStore` ligado na API** | O mesmo store do prompt alimenta `GET /memory/{uid}/search` (antes respondia 501 — store nunca conectado). `add_many` ganhou `doc_ids` determinísticos e persistência em LOTE: ingestão de 842 chunks caiu de **86s para 0.66s** (o add unitário persistia o JSON inteiro a cada chunk — O(n²) de I/O). |
| **Injeção no prompt preserva o cache KV** | Ordem obrigatória identidade (estática) → data/hora → acervo, com teste: trocar invalida o prefixo de KV cache do llama-server a cada mensagem. |
| **versionCode** | 2055 → 2056 (regra §5.3). |

| Verificação | Resultado |
|---|---|
| Suíte do servidor | **2666 passed / 16 skipped** (era 2576 antes da Parte B: +90 testes) |
| Modo oracle (13 goldens, sem rede) | **13/13 (100%)** — inclui os 3 goldens RAG de CI |
| Modo e2e (19 goldens, LLM local real) | **19/19 (100%)** — acervo no prompt do admin, sem vazamento para `user` |
| Modo noretrieval (9 goldens, LLM puro) | **9/9 (100%)** — golden prova que o modo está mesmo sem RAG |
| Baselines | `evals/baseline-{oracle,e2e,noretrieval}.json` atualizadas |

**Fronteira honesta:** recall do floor é conservador — uma pergunta certa
com vocabulário fora do corpus ("o que absorvemos do projeto nômade" sem
citar termos do doc) retorna vazio em vez de lixo. A reescrita com
história recupera parte disso; reranker real (cross-encoder) fica para
quando houver modelo de embedding melhor.

**Assinatura:** `OD // CORE`

---

## [1.25.0] — REFERÊNCIA MÉDICA DETERMINÍSTICA (PARTE C DO NOMAD) 🜂 (2026-10-13)

> **Bump MINOR (capacidade nova):** Parte C da absorção do Project NOMAD na
> ordem acordada (A → **C** → B → D → E → F). Explicada ao dono em três eixos
> (para que serve / como acessa / como o sistema controla) e aprovada:
> "pode fazer".

| Peça | Entrega |
|---|---|
| **3 actions de saúde (categoria `saude`)** | `saude_condicao` (cuidados caseiros/naturais curados por condição — 36 condições, 20 remédios caseiros CDC/NIH/MedlinePlus, 18 naturais NCCIH), `saude_interacoes` (interação entre dois medicamentos citados — verbatim do campo `drug_interactions` da bula FDA via openFDA, com checagem de menção cruzada) e `saude_medicamento` (indicações + avisos da bula). |
| **Coleções versionadas** | `tools/saude/collections/*.json` com atribuição obrigatória: formato do NOMAD (Apache-2.0), conteúdo de domínio público governamental (CDC, NIH/NCCIH, MedlinePlus, FDA) e texto ORIGINAL em inglês preservado em `origem_en` para auditoria. Lexicon de 46 medicamentos comuns (PT-BR → genérico FDA) — só nomes, nunca orientação. |
| **Curadoria sem conteúdo autoral** | Resumos PT-BR são tradução fiel/compactação das fontes citadas; o formatador só compõe. Conteúdo médico inventado é vedado pela arquitetura. |
| **Disclaimer obrigatório** | `SAUDE_AVISO` em TODA resposta (padrão `SafetyBanner` do NOMAD) — testado para cada ramo do formatador, inclusive com `ok=False`. |
| **Saúde NUNCA cai no LLM** | Condição fora da curadoria = "não consta na minha referência — não vou inventar"; medicamento sem label FDA (ex.: dipirona, não comercializada nos EUA) = ausência dita; falha de rede = "sem rede para consultar". O formatador de `saude_*` é o único que **nunca retorna None** — sem degradação para o modelo. |
| **Rota conservadora** | `_detect_saude` em `core/intents.py`: interação explícita rota sempre; "posso tomar X com Y" só com 2 medicamentos do lexicon (`posso tomar café com leite` não é saúde); "remédio para X" exige termo de saúde (`subir o site` não cai). Fastpaths antigos intactos (cpu_temp, câmbio etc.). |
| **Papel `user`** | As 3 actions entram na allowlist do user (leitura de fonte pública, mesma natureza de `ha_weather`/`weather_city`); regressão garante que segredos/escrita/IP seguem vedados. |
| **Gate + goldens** | `tests/test_saude.py` (45 testes: coleções, matching, actions com openFDA fakeado, gatilhos, formatador, permissões, pipeline) + 4 goldens: 2 oraculares herméticos (dor de cabeça curada; condição desconhecida = honestidade) e 2 e2e com rede real (interação dipirona×losartana; bula losartana). |
| **versionCode** | 2054 → 2055 (regra §5.3). |

| Verificação | Resultado |
|---|---|
| Suíte do servidor (com `--cov-fail-under=90`) | **2576 passed / 16 skipped · cobertura 90,08%** |
| Modo oracle (10 goldens, sem rede) | **10/10 (100%)** — inclui os 2 goldens de saúde |
| Modo e2e (16 goldens, LLM local + HA + APIs + openFDA) | **16/16 (100%)** — `fastpath:saude_condicao/interacoes/medicamento` no ar |
| Baselines | `evals/baseline-{oracle,e2e,noretrieval}.json` atualizadas |

**Assinatura:** `OD // CORE`

---

## [1.24.2] — EVAL DO ASSISTENTE (PARTE A) + CLIMA/CÂMBIO DO USER CONCERTADOS 🜂 (2026-10-13)

> **Bump PATCH (ordem do dono para as partes do Project NOMAD):** "vamos usar sua ordem. antes de implementar me explique para que serve, como acesso e como o sistema controla" → "ok. pode fazer" — Parte A (eval) primeiro.

| Peça | Entrega |
|---|---|
| **Exame padrão do assistente** | Pacote `evals/` (Parte A da absorção do Project NOMAD): goldens JSONL (pergunta real × resposta esperada), 3 modos — `oracle` (pipeline real com provider falso, sem rede/LLM, roda no CI), `e2e` (pipeline + actions + LLM local) e `noretrieval` (LLM puro, sem actions) — baseline versionada por modo (`baseline-<modo>.json`) com comparação antes/depois, CLI `python -m evals [--modo|--comparar|--atualizar-baseline|--saida]` e `evals/README.md`. |
| **Gate na suíte/CI** | `tests/test_eval_oracle.py` roda os goldens oraculares pelo pipeline real e falha se qualquer um quebrar ou piorar vs baseline; `tests/test_eval.py` cobre carga/validação, avaliação (funções puras), baseline e CLI. |
| **Conserto pegado pelo eval na 1ª rodada** | user + "temperatura em \<cidade\>" → PERMISSION DENIED (`weather_city` fora da allowlist do user) → o LLM respondia sem dado; user + "quanto está o dólar" → idem e o LLM **alucinou "USD 5.478 (USD/CLP)"**. `weather_city` e `exchange_rate` entraram na allowlist do papel `user` (APIs públicas de leitura, mesma natureza de `ha_weather` desde a v1.8.0) — com testes de regressão garantindo que IP/portas/segredos/escrita **seguem vedados**. |
| **Suíte hermética** | Os testes de clima que agora executam a action fakeiam a Open-Meteo (nenhuma chamada de rede dentro da suíte) + teste novo do contrato user → fastpath com fonte fakeada. |
| **Gate de cobertura consertado** | O HEAD anterior estava **abaixo** do gate (89,80% — o CI reprovaria); esta entrega fecha em **90,03%**. |

| Verificação | Resultado |
|---|---|
| Suíte do servidor (com `--cov-fail-under=90`) | **2531 passed / 16 skipped · cobertura 90,03%** |
| Modo oracle (8 goldens, sem rede) | **8/8 (100%)** |
| Modo e2e (12 goldens, LLM local + HA + APIs) | **12/12 (100%)** — clima `fastpath:weather_city` e câmbio `fastpath:exchange_rate` do user no ar |
| Modo noretrieval (8 goldens, LLM puro) | **8/8 (100%)** |
| Baselines | `evals/baseline-{oracle,e2e,noretrieval}.json` versionadas |

**Assinatura:** `OD // CORE`

---

## [1.24.1] — APAGAR/LIMPAR MINHAS MENSAGENS NO APP 🜂 (2026-10-10)

> **Bump PATCH (pedido do dono via txt.txt):** "no site consigo apagar, limpar as minhas mensagens. quero fazer o mesmo pelo APP."

| Peça | Entrega |
|---|---|
| **Limpar conversa** | Menu ⋮ do chat → "Limpar conversa": apaga TODA a conversa salva da conta no servidor (`DELETE /history/me`) — a mesma função do botão do site, agora no app, com confirmação e o total removido no aviso. |
| **Apagar UMA mensagem** | Long press na própria bolha → "Apagar esta mensagem?" → apaga no servidor (`DELETE /history/me/messages/{id}`) e tira da tela. |
| **ID resolvido na hora** | Mensagem recém-escrita ainda não tinha id no app (streaming e `POST /message` não devolvem ids): o app pergunta ao histórico no momento do apagar e localiza a mensagem pelo conteúdo (`OdApi.resolveUserMessageId`) — apagar vale também para o que acabou de ser escrito, sem trocar o protocolo. Sem candidata no servidor, só remove da tela (com aviso honesto). |

| Verificação | Resultado |
|---|---|
| `flutter analyze` | 0 issues |
| `flutter test` | **157 passed / 2 skipped** (+5: 4 de `resolveUserMessageId` + widget do long press) |
| Suíte do servidor | **2393 passed / 16 skipped** |

> **Fix de teste incluso:** `tests/test_notifier.py` agora isola `OD_LOG_DIR` (fixture autouse) — `test_restart_alert_emitted_once` lia o `logs/router_monitor.log` da máquina e quebrava com `router:down` a cada blip real de rede.

**Assinatura:** `OD // CORE`

---

## [1.24.0] — REGISTRO MESTRE NO APP (ABA "VERIFICAR") + DESFAZER VENDA 🜂 (2026-10-09)

> **Bump MINOR (dois pedidos do dono):** (a) "porque atualizou o APP se ele não possui a tela de Registro Mestre" — a 1.23.1 só consertou o "Verificar Atualização"; a tela agora existe no app; (b) "se vendo a peça e depois a pessoa desiste antes de concluir, não consigo desfazer e voltar para o estoque".

| Peça | Entrega |
|---|---|
| **Aba Verificar** | 6ª aba do app (`RegistryScreen`): consulta pública pelo ID gravado na peça (busca tolerante a hífens/espaços, como o site), selo de autenticidade, foto, coleção, status e o USERNAME de quem tem a peça — preço/notas/nome real nunca saem do servidor. |
| **Sala da peça** | A mesma sala do site dentro do app: leitura pública, escrita só com conta (401 avisa), polling de 4 s, assinatura pelo username. |
| **Desfazer venda** | Painel: botão "↩ Desfazer" em peça vendida → volta para o estoque (com confirmação) e `sold_at`/`registered_at` são apagados no store. |
| **Registro protegido** | `registrada → estoque/vendida` bloqueado no store (`registro_pendente_codigo_secreto` → 400): desfazer o registro depende do código exclusivo e secreto da peça (QR de posse) — adiado pelo dono; sem bloqueio, um clique acidental apagaria posse sem prova. |
| **versionCode** | 2051 → 2052 (regra §5.3). |
| **Testes** | app +5 `registry_screen_test.dart` (143 pass / 2 skip) · servidor +3 `test_registry.py` (36 pass) · analyze 0. |

Infra visível no repo: `.env 1.24.0` · capabilities fallback `1.24.0` · `pubspec 1.24.0+2052` · `_APP_VERSION_CODE=2052` · site (badge + dl-meta) · APKs rebuildados · `CHANGELOG [1.24.0]` · `README_VERSAO §1.24.0`.

---

## [1.23.1] — APP: "VERIFICAR ATUALIZAÇÃO" AGORA MOSTRA AS DUAS VERSÕES 🜂 (2026-10-09)

> **Bump PATCH (bug do dono):** "APP não mostra a versão atual ao clicar Verificar Atualização". Duas causas somadas: (1) a mensagem do resultado não trazia versão nenhuma — só "Você já está na versão mais recente."; (2) o versionCode estava parado em 2050 desde a 1.22.0 (bumps com "app sem mudança de código"), e a comparação do updater é só por versionCode — o celular do dono (2050) recebia "já atualizado" enquanto o servidor anunciava 1.23.0.

| Peça | Entrega |
|---|---|
| **Mensagem** | `odUpdateStatusMessage()` no `od_updater.dart` — a tela SEMPRE mostra publicada × instalada com os versionCodes: "Nova versão v1.23.1 (código 2051) (55 MB) disponível — você está na v1.23.0 (código 2050)." ou "Você já está na versão mais recente — publicada: v1.23.1 (código 2051) · instalada: v1.23.1 (código 2051)." |
| **Card** | "App instalado: vX.Y.Z (código N)" — versão e versionCode juntos; `_checkUpdate` recarrega os dois na hora do clique (PackageInfo demorado no initState não atrasa mais a mensagem). |
| **versionCode** | 2050 → **2051** — daqui em diante TODO publicação de APK novo leva versionCode novo, mesmo sem mudança de código (checklist §5.3 ajustado): versionCode igual = updater mudo por definição. O celular do dono (2050) vai receber a 1.23.1 de verdade. |
| **Testes** | `od_updater_test.dart` +4 (mensagem sem atualização, com atualização, fallback sem PackageInfo, servidor inacessível) — e a guarda de política de versão pegou de primeira o `v1.24.0` hipotético do meu próprio teste (código rotulado com versão futura): cenário reescrito com versões reais. |

Infra visível no repo: `.env 1.23.1` · capabilities fallback `1.23.1` · `pubspec 1.23.1+2051` · `_APP_VERSION_CODE=2051` · site (badge + dl-meta) · APKs rebuildados · `CHANGELOG [1.23.1]` · `README_VERSAO §1.23.1`.

---

## [1.23.0] — VERIFICAÇÃO EVOLUÍDA: SEM HÍFEN, FOTO E SALA DE BATE-PAPO 🜂 (2026-10-09)

> **Bump MINOR:** o dono validou a verificação ("verifica, funcionando") e pediu três melhorias: busca sem hífen, foto do produto e "uma sala de bate-papo onde uma pessoa interessada na peça pode conversar com o comprador e negociar a compra direta". Tudo entregue no mesmo dia.

| Peça | Entrega |
|---|---|
| **Busca tolerante** | `odprod20260001`, `NVABI7F3A` ou com espaços acha igual — comparação normalizada (maiúsculas, sem separadores) no `RegistryStore.get()`; exato primeiro (índice), varredura normalizada só como fallback. |
| **Foto do produto** | `POST /admin/registry/{public_id}/photo` (base64 JSON; jpeg/png/webp, ≤6 MB) → arquivo em `data/registry_photos/`; `GET /registry/{codigo}/photo` pública com cache; payload público traz a URL (nunca o nome do arquivo). O painel reduz no navegador (canvas, máx. 900 px) antes de enviar; miniatura na tabela; remover peça apaga a foto. |
| **Sala de bate-papo** | Tabela `registry_chat` + `GET /registry/{codigo}/chat` (leitura pública, `?since=` para polling) + `POST /registry/{codigo}/chat` (conta obrigatória; assina com o username — nome real nunca). Quem tem a peça é o interlocutor: estoque → dono do sistema; registrada → @dono. Verificação pública abre a sala embaixo do selo, com polling de 4 s e link de login para anônimos. |
| **Moderação + aviso** | `DELETE /admin/registry/{public_id}/chat/{msg_id}` (só dono) + botão ✕ na sala do painel (💬 abre a sala por peça). Cada mensagem nova avisa o dono no Telegram (1 aviso a cada 2 min por peça — anti-spam; falha do Telegram nunca derruba o envio). |
| **Testes** | Guardas de rotas 57→62 · `tests/test_registry.py` +14 (busca sem hífen store/rota, foto store/rota/upload/404/moderação de arquivo, chat store/limites/leitura pública/escrita com conta/moderação/cooldown do aviso). |

Limites: foto ≤6 MB de binário (o painel manda ~100-200 KB), mensagem ≤2000 caracteres, sala mostra as últimas 200. Leitura pública da sala é decisão do dono (conversa sobre a peça, não privada); moderação fica com ele.

Infra visível no repo: `.env 1.23.0` · capabilities fallback `1.23.0` · `pubspec 1.23.0+2050` · `_APP_VERSION_CODE=2050` · site (badge, verificação com foto/chat) · APKs rebuildados · `CHANGELOG [1.23.0]` · `README_VERSAO §1.23.0`.

---

## [1.22.1] — PAINEL DO REGISTRO MESTRE: CADASTRO DO DONO NO AR 🜂 (2026-10-09)

> **Bump PATCH:** o dono pediu "um backend de cadastro para o adm" e autorizou exemplos de teste. O painel `/admin` ganha a seção **Registro Mestre (peças)**: formulário de cadastro (nome, coleção, tipo, código gravado, preço, notas), lista completa com status e dono, ações **→ Vender**, **🔑 Registrar** (username de quem comprou) e **✕ Remover** (rota `DELETE /admin/registry/{public_id}` nova, com dupla confirmação). Preço e notas continuam só no painel.

| Peça | Entrega |
|---|---|
| **Painel** | Seção "Registro Mestre (peças)" em `/admin` — cadastro, transições de status e remoção; carrega junto com o resto (`carregarTudo`). |
| **API** | `DELETE /admin/registry/{public_id}` (só dono; 404 se não existe) + `RegistryStore.delete()`. |
| **Testes** | Guardas de rotas 56→57 · `tests/test_registry.py` +3 (delete no store, rota DELETE com prova público→removido→404, seção do painel no HTML). |
| **Exemplos** | Peças de teste cadastradas no ar para o dono exercitar a consulta pública. |

Infra visível no repo: `.env 1.22.1` · capabilities fallback `1.22.1` · `pubspec 1.22.1+2050` · `_APP_VERSION_CODE=2050` · site (badge + card) · APKs rebuildados · `CHANGELOG [1.22.1]` · `README_VERSAO §1.22.1`.

---

## [1.22.0] — REGISTRO MESTRE: BANCO DE PEÇAS + VERIFICAÇÃO PÚBLICA NO AR 🜂 (2026-10-09)

> **Bump MINOR:** item 2 da pauta de divergências (decisões do dono a–e, 09/10) — o Registro Mestre nasce como banco real de peças com consulta pública de autenticidade. A pessoa está com a PEÇA na mão (não com o cartão): o ID vem gravado na peça e é pesquisável por qualquer um; a consulta mostra o **username** de quem registrou (nunca o nome real) e o QR segue como símbolo de propriedade.

| Peça | Entrega |
|---|---|
| **Banco** | `core/registry.py` — tabela `registry_items` (ID canônico `OD-PROD-AAAA-NNNN` sequencial + código curto gravado `engraved_code`, tipo exclusiva/pública, status estoque→vendida→registrada, preço/anotações privados, coerência: `registrada` exige dono). |
| **API** | `GET /registry/{codigo}` pública (AUTH_EXEMPT, sob auth_all) — projeção sem preço/notas, username só quando registrada; `POST/GET /admin/registry` + `PUT /admin/registry/{public_id}` (só dono, 403 para os demais, 503 sem banco). |
| **Ligação** | `runtime/launcher.py`: `build_registry(database)` → `APIConfig.registry` (padrão do UserStore; degrada com None). |
| **Site** | `site/verificacao.html` — página pública de consulta (busca por ID gravado, selo autêntica/vendida/registrada, username do dono) + home: card Verificação “em breve” → **no ar**, link na nav. |
| **Testes** | `tests/test_registry.py` (14) + guardas de rotas atualizadas (56) — suíte completa verde. |

Infra visível no repo: `.env 1.22.0` · capabilities fallback `1.22.0` · `pubspec 1.22.0+2050` · `_APP_VERSION_CODE=2050` · site (badge + card) · APKs rebuildados · `CHANGELOG [1.22.0]` · `README_VERSAO §1.22.0`.

---

## [1.21.2] — ECOSSISTEMA NO AR: SITE INSTITUCIONAL + FIM DO DRAGÃO 🜂 (2026-10-09)

> **Bump PATCH:** o site deixa de falar só do app e passa a apresentar o ecossistema Omega Drakon inteiro (base: Legado `~/Legado/OMEGA_DRAKON` + consolidações canônicas do Drive). O emoji 🐉 é removido de todas as superfícies — mensagens, chat web, painéis e app — substituído pelo logotipo oficial.

1. **Site institucional novo (`site/index.html`)** — reconstruído sobre a identidade visual oficial:
   - Paleta do manual: Preto Profundo `#0A0A0A`, Azul Elêtrico `#0088FF`, Grafite `#2C2C2C`, Branco Técnico `#F2F2F2`; fontes Orbitron + Montserrat.
   - Seções novas: Núcleo da Marca (3 pilares + citação do Arquiteto), Ecossistema (5 sub-marcas: Systems, FAB, Living Systems, Nicoly Valentina + Tríade Canônica), Sistemas (plataforma soberana em 8 módulos), Produtos (do bit ao átomo), Autenticidade (Mark of Continuity + /verificacao), Histórico (linha do tempo 2025→hoje), Plêiade (7 perfis), Download e Sobre (texto aprovado `Textos_Aprovados/sobre.md`).
   - Assets oficiais em `site/` (raiz — o route `/site/{file}` é single-segment): `logo.png` (512), `simbolo_minimo.png` (192), `favicon.png` (64) — todos gerados do Legado via ImageMagick.
   - Zero JavaScript, mesma filosofia de página única do site anterior.
2. **Fim do 🐉 nas mensagens** — `server.py` (favicon, avatar do histórico, nav, login, boas-vindas do chat, painel e admin usam o logo), `capabilities.py` (cabeçalho `/capabilities`), `quick_responses.py` (respostas de identidade).
3. **App** — logo oficial como asset (`app/assets/logo.png` + pubspec): tela de login, boas-vindas do chat e chip do perfil guardian exibem o logo; selo da bolha `🐉 OD` → `OD`.
4. **Regra 16 (`iniciar/RULES.md`)** — `/home/alex/Legado` vira referência obrigatória da sessão.

### 2. Bump PATCH

Infra visível no repo: `.env 1.21.2` · capabilities fallback `1.21.2` · `pubspec 1.21.2+2050` · `_APP_VERSION_CODE=2050` · site (conteúdo + badge) · APKs rebuildados · `CHANGELOG [1.21.2]` · `README_VERSAO §1.21.2`.

## [1.21.1] — ÍCONE DO APP: PADRÃO OMEGA DRAKON 🎨 (2026-10-09)

> **Bump PATCH:** troca visual do ícone do app Android pelo logotipo oficial da marca Omega Drakon. Nenhuma funcionalidade alterada.

1. **Ícone Android (5 densidades)** — gerados a partir da fonte oficial `Logo da Omega Drakon.png` (1024×1024, pasta `01_NUCLEO_DA_MARCA/Simbolos_Oficiais/` do Legado) via ImageMagick:
   - mdpi 48×48, hdpi 72×72, xhdpi 96×96, xxhdpi 144×144, xxxhdpi 192×192 (todos RGBA).
   - Substitui o ícone genérico do Flutter pelo símbolo da marca.
2. **Bump PATCH 1.21.0 → 1.21.1** — versionCode 2048 → 2049; APKs rebuildados e publicados em `site/`.

### 2. Bump PATCH

Infra visível no repo: `.env 1.21.1` · capabilities fallback `1.21.1` · `pubspec 1.21.1+2049` · `_APP_VERSION_CODE=2049` · `site 2x` · APKs rebuildados · `CHANGELOG [1.21.1]` · `README_VERSAO §1.21.1`.

## [1.21.0] — CANAL DE DESENVOLMENTO: OS 3 COMPORTAMENTOS DO ▶ ATIVAR 🧠 (2026-10-08)

> **DEPLOY AUTORIZADO PELO DONO (08/10, escolha 'Sim, deploy 1.21.0 completo').**
> Pedido: 'txt.txt são as minhas ideias de melhoria. se estiver vazio e
> clicar em Ativar desenvolvimento não deve fazer nada. se o texto for o
> mesmo de uma sessão concluída avisa que já foi implementado e se desejo
> limpar. se for uma nova conversa ai sim analisa a possibilidade de
> implementação, verifica os pros e contras, sugere alternativas melhores e
> implementa com a melhor opção.' Checklist §5 completo: `.env 1.21.0` ·
> capabilities · `pubspec 1.21.0+2048` · `_APP_VERSION_CODE=2048` · `site 2x` ·
> APKs rebuildados · restart do `od-core` (regra 13).

1. **`txt.txt` vazio → não faz nada** — o ▶ Ativar (site e app) nem abre o
   diálogo nem chama o servidor quando a prévia do `txt.txt` está vazia
   (mensagem 'nada a ativar'); se a chamada chegar por fora, o contrato
   antigo `400 sem_ideia` segue valendo, **sem Popen e sem estado**.
2. **Ideia igual a uma sessão CONCLUÍDA → aviso + limpeza** — novo
   histórico `data/dev_historico.json` no módulo **`core/dev_canal.py`**
   (compartilhado por propósito: quem grava é o runner, quem lê é o
   painel — os dois precisam da MESMA normalização). O orquestrador
   registra a ideia ao fim de toda sessão `concluido` (dedup por hash da
   forma normalizada: espaços, quebras e caixa não mudam o texto) e o
   `_sessao_ativar` responde **`409 ja_implementado` com
   `commit`/`ts`/`motivo` no corpo** (`APIError` ganhou `extra`; o handler
   monta o payload sem deixar o extra mascarar `ok`/`error`). O painel
   pergunta 'Limpar o txt.txt agora?' → `DELETE /admin/ideias`; Cancelar
   mantém o texto (para rodar de novo, é editar a ideia). Só `concluido`
   bloqueia — sessão que falhou pode ser tentada de novo — e o runner
   recusa também (`exit 3`), para quem o chamar direto.
3. **Ideia nova → ANÁLISE antes do código** — o `INSTRUCAO_SESSAO` passa a
   exigir o bloco **`[ANALISE]…[FIM ANALISE]`** (viabilidade · prós ·
   contras · alternativas · escolha); o runner extrai
   (`extrair_analise`), publica na **caixa de desenvolvimento** e grava em
   `estado["analise"]` (exibido no painel do site e do app). Só depois a
   CLI implementa **SÓ a melhor opção**, com suíte verde antes do commit.
   Análise ausente não quebra a sessão (o prompt pede; quem responde é um
   modelo) e `[FIM ANALISE]` esquecido não perde o bloco.
4. **Paridade do app** — `OdApiError` ganhou `details` (corpo do erro do
   servidor); `_ativarSessao` devolve no vazio, oferece a limpeza no
   `ja_implementado` e mostra `análise:`; copy do card igual ao site.
5. **Teste do teste:** 5 mutações detectadas e restauradas bit-exato
   (histórico ignorado no servidor · campos `extra` fora do erro ·
   registrando sessão que falhou · normalização quebrada · análise sem
   corte no `[FIM ANALISE]`).
6. **Resultado:** Suíte **2390 passed, 16 skipped** (+23) · guardas de
   versão 9/9 · cobertura **90,18%** (gate 90) · `node --check` verde ·
   `flutter analyze` 0 issues · `flutter test` **134 passed** (+1).

## [1.20.2] — CANAL LOGO ABAIXO DAS IDEIAS NO SITE + APP EM PARIDADE 📱 (2026-10-08)

> **DEPLOY AUTORIZADO PELO DONO (08/10, escolha 'Deploy 1.20.2 completo').**
> Pedido: 'No site o Canal de Desenvolvimento deve ficar logo abaixo do
> Ideias (txt.txt). O APP não está refletindo essas atualizações, deixe
> igual.' Checklist §5 completo: `.env 1.20.2` · capabilities · `pubspec
> 1.20.2+2047` · `_APP_VERSION_CODE=2047` · `site 2x` · APKs rebuildados ·
> restart do `od-core` (regra 13).

1. **Seções reordenadas no `/admin`** — ordem nova: Sistema → **Ideias
   (txt.txt)** → **Canal de desenvolvimento** → Limitações. Guarda nova na
   suíte (`test_ordem_no_painel_canal_logo_abaixo_das_ideias`) trava a
   ordem e a seção inteira entre as duas (sem nada da fila antiga).
2. **App em paridade total com o painel** — a UI da fila (botões
   `Injetar`/`Esvaziar` em `/admin/dev/pedido`, que já respondia 404)
   virou a **sessão on-demand**: ▶ Ativar/Parar, seletor de CLI
   (automática/cascata, Freebuff, OpenCode, Kilo), pill de estado com pid e
   autorizações pendentes, info (ideia/CLI/rodada/testes/diff/commit/motivo),
   **caixa de desenvolvimento** com campo de resposta + limpar e **log**
   (ExpansionTile). Confirmação do Ativar mostra um trecho do `txt.txt`.
   Ordem dos cards igual ao site (Ideias → Canal → Limitações) e
   auto-refresh de 5 s enquanto a sessão estiver ativa ou houver
   autorização pendente (mesma cadência do site).
3. **`od_api.dart`** — fora `getDevPedidoStatus`/`adminInjectPedido`/
   `adminClearPedido`; entram `getDevSessao`, `adminDevSessao(ativar/parar)`,
   `getDevCaixa`, `adminDevCaixaReply`, `adminDevCaixaClear`, com o código
   do servidor traduzido em português (`sem_ideia`, `sessao_ativa`…).
4. **Teste do teste:** 1 mutação detectada e restaurada bit-exato (seções
   voltando à ordem antiga).
5. **Resultado:** Suíte **2367 passed, 16 skipped** (+1) · guardas de versão
   9/9 · cobertura **90,18%** (gate 90) · `flutter analyze` limpo ·
   `flutter test` **133 passed** (+2).

### 2. bump PATCH

`[1.20.2]` = PATCH (ajuste de ordem de UI + paridade do app): `.env 1.20.2`
· capabilities fallback `1.20.2` · `pubspec 1.20.2+2047` ·
`_APP_VERSION_CODE=2047` · `site 2x` · APKs rebuildados · `CHANGELOG
[1.20.2]` · este README.

## [1.20.1] — CORREÇÃO DA FONTE DA IDEIA (`txt.txt`) + EXCLUSÃO DA FILA `pedido.txt` 🧹 (2026-10-08)

> **DEPLOY AUTORIZADO PELO DONO (08/10, escolha 'Deploy 1.20.1 completo').**
> Duas correções dele no MESMO dia, em cima do 1.20.0 já publicado:
> 'não entendi a lógica do pedido.txt se o sistema já vai ler o txt.txt onde
> coloco as ideias de atualização do sistema' e 'o arquivo pedido.txt e a
> caixa de diálogo ligado a ele não tem mais função e podem ser excluídas'.
> Os CONTROLES continuam na seção **'Canal de desenvolvimento'** do `/admin`
> (escolha dele) — mudou de ONDE a ideia é lida, não de ONDE os botões ficam.
> Checklist §5 completo: `.env 1.20.1` · capabilities · `pubspec
> 1.20.1+2046` · `_APP_VERSION_CODE=2046` · `site 2x` · APKs rebuildados ·
> restart do `od-core` (regra 13).

1. **Fonte da ideia = `txt.txt`** — `_sessao_ativar` lê `IDEIAS_FILE`
   (`txt.txt`) em vez do `pedido.txt`; erro novo `fila_vazia` → **`sem_ideia`**
   (servidor, runner e mensagem do painel); o confirm do ▶ Ativar busca
   `GET /admin/ideias` e mostra um trecho do `txt.txt` (avisa se vazio). O
   `txt.txt` **não** é limpo após a leitura — é o canal permanente do dono.
2. **Fila `pedido.txt` excluída de ponta a ponta** — arquivo da raiz removido;
   **ROUTES 55 → 52** (saíram `POST/GET/DELETE /admin/dev/pedido` e os três
   handlers); painel perdeu o `<details>` 'Fila manual' e o JS
   `devSetMsg/devStatus/devInjetar/devClear`; o status da sessão perdeu
   `monitor_ativo`.
3. **`orquestrador.py` −400 linhas** — fora `PEDIDO_FILE`, `ARQUIVO_SAIDA`,
   `INSTRUCAO_BLINDADA`, `montar_prompt`, `extrair_codigo`, `validar_sintaxe`,
   `processar_pedido`, `ler_e_limpar_pedido`, `ciclo`, `monitorar` e a flag
   `--fila`; sem `--sessao` o processo recusa (exit 2) em vez de rodar no
   escuro. `executar_cli` + cascata ficaram — são o modo sessão.
4. **`deploy/od-orchestrator.service` excluído** (o `ExecStart` não teria mais
   o que rodar), `.gitignore` sem `/pedido.txt` e comentário de
   `core/limitacoes.py` apontando o `txt.txt`.
5. **Testes** — 30 testes da fila fora (`TestMontarPrompt`,
   `TestExtrairCodigo`, `TestValidarSintaxe`, `TestLearLimparPedido`,
   `TestProcessarPedido`, `TestCiclo`, `TestAdminDevPedido`) **+1 novo**: o
   gate 403 que era da fila virou gate do `/admin/dev/sessao` (dono → 200,
   comum → 403). Guarda de rotas 55 → 52 e ids do HTML sem
   `dev-texto`/`dev-injetar`.
6. **Teste do teste:** **3 mutações** detectadas e restauradas bit-exato
   (server voltando a ler `pedido.txt`; código de erro voltando a
   `fila_vazia`; runner voltando a ler `pedido.txt`).
7. **Resultado:** Suíte **2366 passed, 16 skipped** · guardas de versão 9/9 ·
   cobertura **90,18%** (gate 90) · `node --check` no JS do painel verde.

### 2. bump PATCH

`[1.20.1]` = PATCH (correção de fonte + remoção de fila morta, sem capacidade
nova): `.env 1.20.1` · capabilities fallback `1.20.1` · `pubspec 1.20.1+2046`
· `_APP_VERSION_CODE=2046` · `site 2x` · APKs rebuildados · `CHANGELOG
[1.20.1]` · este README.

## [1.20.0] — CANAL DE DESENVOLVIMENTO ON-DEMAND: SESSÃO PELO PAINEL + CAIXA DE AUTORIZAÇÃO 🛠️ (2026-10-08)

> **DEPLOY AUTORIZADO PELO DONO (08/10, 'sim'):** pedido dele no `txt.txt`
> (08:35) — o orquestrador não precisa mais ficar online 24 h numa fila:
> um botão **▶ Ativar desenvolvimento** no `/admin` sobe uma SESSÃO por
> demanda. Checkpoint de decisão no meio do caminho: ele corrigiu a entrada
> ('no admin o canal de desenvolvimento é o pedido.txt — olha o site na
> seção admin') → a ideia entra no **`pedido.txt`** e o `txt.txt` ficou só
> de CONTEXTO (a CLI lê junto de `iniciar/` e `docs/`). Checklist do
> `docs/VERSIONAMENTO.md` §5 completo: `.env` · capabilities · `pubspec
> 1.20.0+2045` · `_APP_VERSION_CODE=2045` · `site 2x` · APKs rebuildados ·
> restart do `od-core` (regra 13).

1. **Orquestrador vira on-demand** — `orquestrador.py --sessao --cli
   auto|freebuff|opencode|kilo` (default `auto` = cascata Freebuff →
   OpenCode → Kilo): lê a ideia no `pedido.txt`, monta prompt de CONTEXTO
   (`iniciar/session.json`+`RULES.md`, `docs/README_VERSAO.md`,
   `REGRAS_DE_TRABALHO.md`, `VERSIONAMENTO.md`, `CHANGELOG.md` e `txt.txt`),
   executa e valida no fim.
2. **Caixa de desenvolvimento** — CLI one-shot que precisa de autorização
   termina a resposta com `[AUTORIZACAO] pergunta` → o runner publica em
   `data/dev_caixa.json`, muda o estado para `aguardando_autorizacao` e
   ESPERA o dono (timeout 30 min, máx. 5 pedidos) → retoma com a mesma CLI
   e o histórico da rodada. Marcador no meio de uma linha não conta.
3. **Nunca** `git push`, `systemctl`, `.env` ou `backups/` (regras 7 e 13);
   validação com a suíte canônica (`--cov-fail-under=90`) antes de commitar
   — commit SEM push é liberado pelo dono (decisão 2 de 08/10).
4. **Rotas novas (ROUTES 50 → 55)** — `POST/GET /admin/dev/sessao`
   (ativar/parar + estado) e `GET/POST/DELETE /admin/dev/caixa`
   (ler/responder/limpar), todas com `_require_admin`.
5. **Spawn desanexado** — `Popen(start_new_session=True)` com cwd na raiz e
   stdout em `logs/dev_sessao.log`: a sessão sobrevive a restart do od-core;
   **Parar** = `SIGTERM` no GRUPO (runner + CLI, `pgid == pid`). GET
   normaliza processo morto (`interrompida`/`processo_ausente`) — o painel
   nunca mente 'executando'. `_monitor_pids()` ignora `--sessao` (a fila
   antiga e a sessão não se confundem).
6. **Painel `/admin`** — seção 'Canal de desenvolvimento' reescrita:
   ▶ Ativar + seletor de CLI + pill de estado + info (ideia/CLI/testes/
   diff/commit) + caixa com campo de resposta (Enter envia) + log; fila
   manual virou `<details>` (modo avançado); auto-refresh de 5 s enquanto
   ativa.
7. **`od-orchestrator.service` desativado** (decisão 3 do dono) — a fila
   24 h não sobe mais; quem manda é o botão.
8. **Teste do teste:** **5 mutações** detectadas e restauradas bit-exato
   (marcador `[AUTORIZACAO]`, `start_new_session`, filtro
   `COMMIT_EXCECOES`, normalização de processo morto, `_marcar_respondidas`)
   + guarda de ids do HTML no painel (bug de 2026-09-26 não repete).
9. **Resultado:** Suíte **2394 passed, 16 skipped** (+55) · guardas de
   versão 9/9 · cobertura **90,16%** (gate 90) · `node --check` no JS do
   painel verde.

### 2. bump MINOR

Infra visível no repo: `.env 1.20.0` · capabilities fallback `1.20.0` · `pubspec 1.20.0+2045` · `_APP_VERSION_CODE=2045` · `site 2x` · APKs rebuildados · `CHANGELOG [1.20.0]` · este README · `systemctl --user disable --now od-orchestrator`.

## [1.19.5] — AGENDA: 'EVENTO', HORA POR EXTENSO E ANTI-FALSO-SUCESSO 🛡️ (2026-10-08)

> **DEPLOY AUTORIZADO PELO DONO (08/10):** 'mais alguns erros de escrita
> ou de entendimento' — ele testou o 1.19.4 na marra (IDs 759–786) e os 3
> grupos foram corrigidos sob a mesma autorização. Checklist do
> `docs/VERSIONAMENTO.md` §5 completo: `.env` · capabilities · `pubspec
> 1.19.5+2044` · `_APP_VERSION_CODE=2044` · `site 2x` · APKs rebuildados ·
> restart do `od-core` (regra 13).

Achados nos testes dele (prova real, IDs 769–786, 05:23–05:28):

1. `'crie um evento para as 7:00'` / `'marque um evento para as 7:30'` →
   intenção **NENHUMA** (faltava o substantivo **'evento'** na rota) → LLM
   (25 s) em vez do fastpath;
2. **falso sucesso:** a gemma ECOU uma confirmação VELHA do histórico
   (`'teste deploy' 07:00`, minha prova de 05:20) como se fosse nova,
   **sem gravar pendência**, e ao `'sim'` dele respondeu *'Compromisso
   criado com sucesso'* — **a agenda seguia vazia**;
3. `'crie um evento para as sete horas'` (HORA POR EXTENSO) não casava —
   só dígitos eram lidos;
4. `'s'` (typo dele) funcionava com pendência e, sem, caía no LLM que
   respondia `'Estado verificado.'` (sem sentido).

- **fix(intents): 'evento' na rota** — `eventos?` no substantivo de
  ESCRITA (`_GOOGLE_W_CAL_RE`) e de LEITURA (`_GOOGLE_CAL_RE`).
- **fix(intents,calendar): hora POR EXTENSO** — `_NUM_POR_EXTENSO`
  (`um`…`vinte e três`) em `_GOOGLE_W_QUANDO_RE` (ramos dia e sem-dia) +
  `_extenso_em_digito` no `parse_when`; número solto sem preposição
  continua fora (`'daqui duas horas'` → None).
- **fix(core): 'sim' sem pendência = honesto** — `'sim'/'s'` sem nada
  pendente responde `fastpath:confirmacao_sem_pendencia` (zero LLM) nos
  DOIS transportes (REST e WS).
- **fix(core): etapa 6.7 anti-falso-sucesso** — `fake_action_reason`
  detecta resposta do LLM que imita ação (`'Confirmar:'`, `'… com
  sucesso'`, 1ª pessoa `'marquei o compromisso'`) e troca por
  `FAKE_ACTION_MESSAGE` ANTES do histórico e do cache — nunca um sucesso
  inventado.
- **Cache/agenda saneados:** 5 respostas falsas podadas (snapshot
  `backups/llm-cache-fakes-20261008-055830.json`) · 1 evento de teste
  apagado da agenda do dono (`'compromisso' 06:00`; antes 1 → depois 0).
- **Teste do teste:** **10 mutações** detectadas e restauradas bit-exato
  (rota 'evento' escrita/leitura; ramos (a) e (b) do quando sem extenso;
  `parse_when` sem extenso; 'sim' sem pendência no REST; guarda
  anti-falso nas 2 rotas; `fake_action_reason` anulado) + 4 testes do
  contrato antigo (`'sim' solto → LLM`) atualizados para o novo.
- **Resultado:** Suíte **2339 passed, 16 skipped** (+8) · guardas de
  versão 9/9 · cobertura **90,11%** (gate 90).

### 2. bump PATCH

Infra visível no repo: `.env 1.19.5` · capabilities fallback `1.19.5` · `pubspec 1.19.5+2044` · `_APP_VERSION_CODE=2044` · `site 2x` · APKs rebuildados (aapt2 `versionCode='2044' versionName='1.19.5'`) · `CHANGELOG [1.19.5]` · este README.

## [1.19.4] — AGENDA: HORA SEM DIA GRAVA NO HORÁRIO ⏰ (2026-10-08)

> **DEPLOY AUTORIZADO PELO DONO (08/10):** checklist do
> `docs/VERSIONAMENTO.md` §5 completo — `.env` · capabilities · `pubspec
> 1.19.4+2043` · `_APP_VERSION_CODE=2043` · `site 2x` · APKs rebuildados ·
> restart do `od-core` (regra 13).

Bugs reais do chat (IDs 747–752, 08/10): o dono escreveu **'criar
compromisso para as 6 horas'** — sem 'hoje' na frase o regex de quando
não casava, a hora virava **título** (`'para as 6 horas'`), o create
pedia 'quando', ele respondeu 'hoje' e o evento nascia **DIA INTEIRO**
no Google ('quase funcionou, ainda não grava no horário').

- **fix(intents): hora SEM dia** — `_GOOGLE_W_QUANDO_RE` ganha o ramo
  'só a hora' (`para as 6 horas` · `às 12 horas` · `14:30`), com
  exigência de preposição `às` (ou HH:MM): número solto (`daqui 2
  horas`, `10.000`) **não** é um quando.
- **fix(intents): título padrão** — quando todo o resto era o quando,
  o SUBSTANTIVO vira o título (`'criar compromisso para as 6 horas'` →
  `'compromisso'`), nunca string vazia (senão `alvo_obrigatorio`).
- **fix(calendar): parse_when** — hora sem dia → **hoje**, e **amanhã**
  quando a hora já passou; dia explícito nunca rola; sem hora nenhuma
  continua date-only (escolha do dono). A dica `'às 15h'` pura agora
  completa a pendência (antes exigia 'hoje' junto).
- **fix(intents/calendar): ponto não é hora** — a prova viva do deploy
  pegou: `'prova hora 1.19.4 …'` casou como `01:19` (HH**.**MM) e o
  create agendou 01:19. O ramo 'só a hora' agora exige preposição
  (`às`/`para as …`) ou `HH:MM` com **dois-pontos** — versão (`1.19.4`)
  e data `dd.mm` (`08.10`) no título nunca viram horário.
- **fix(intents): `crei` removido da regex de criação** — pedido do
  dono em 08/10: era **erro de digitação**, o verbo é `crie` (já
  coberto). Mensagem com a palavra errada volta a cair na **LEITURA**
  (mostra a agenda), nunca cria.
- **Teste do teste:** **9 mutações** detectadas e restauradas bit-exato
  (regex sem o ramo 'só a hora'; `parse_when` recusa hora sem dia; sem
  o rollover hoje→amanhã; título padrão removido; hora solta aceitando
  número sem preposição; `crei` voltando; `crei` saindo junto com
  `crie`; HH:MM aceitando ponto no intents; idem no `parse_when`).
- **Resultado:** Suíte **2331 passed, 16 skipped** (+6 testes sobre as
  2325 da 1.19.3) · guardas de versão 9/9 · cobertura **90,07%**
  (gate 90). Prova de contrato: POST ao Google com `dateTime 06:00`
  quando o dono falou 'para as 6 horas' — nunca `{"date": …}`.

### 2. bump PATCH

Infra visível no repo: `.env 1.19.4` · capabilities fallback `1.19.4` · `pubspec 1.19.4+2043` · `_APP_VERSION_CODE=2043` · `site 2x` · APKs rebuildados (aapt2 `versionCode='2043' versionName='1.19.4'`) · `CHANGELOG [1.19.4]` · este README.

## [1.19.3] — AGENDA: HORA ANTES DO DIA + CRIAÇÃO ENCADEADA SEM LLM ⏰ (2026-10-08)

> **DEPLOY AUTORIZADO PELO DONO (08/10):** checklist do
> `docs/VERSIONAMENTO.md` §5 completo — `.env` · capabilities · `pubspec
> 1.19.3+2042` · `_APP_VERSION_CODE=2042` · `site 2x` · APKs rebuildados ·
> restart do `od-core` (regra 13).

Bugs reais do chat (IDs 723–734, 08/10): o dono pediu 'marque na agenda
um compromisso para as 4:00 de hoje' e o evento nascia **dia inteiro** no
Google; e 'Testar Agenda' nunca chegou a existir (o LLM alucinou o
sucesso).

- **fix(intents): hora ANTES do dia** — `_GOOGLE_W_QUANDO_RE` só via
  'hoje às 16h'; 'para as 4:00 de hoje' deixava a hora no TÍTULO
  ('compromisso para as 4:00 de') e mandava `quando='hoje'` →
  `parse_when` devolvia date-only → `create_event` enviaba `{"date": …}`.
  Agora a hora antes do dia entra no quando e sai do título; fallback de
  título quando todo o resto era o quando ('crei um evento na agenda …'
  → 'evento').
- **fix(calendar): `parse_when` aceita '5 horas' sem 'às'** — dia
  inteiro só quando o dono NÃO deu hora (nunca inventa hora).
- **fix(actions,orchestrator): criação encadeada sem LLM** — o hint
  'não entendi quando' guarda o título (`_CALENDAR_WHEN`, TTL 300 s) e a
  frase seguinte ('hoje'/'amanhã às 16h') completa a MESMA criação no
  fastpath, nos DOIS caminhos (stream e síncrono), com `user_id`. Antes
  a frase caía no LLM, que alucinava 'Marquei o compromisso…' sem chamar
  a API (ID 700: 'Testar Agenda' nunca existiu).
- **fix(intents): leitura e verbo** — `_GOOGLE_ASK_RE` +
  `mostre|montre|mostra[r]` ('me mostre os compromissos' sem 'meus' ecoava
  a alucinação do cache em vez da Agenda real) · `_GOOGLE_W_CRIAR_RE` +
  `crei` ('crei um evento…' caía em leitura).
- **Testes:** +7 (`TestHoraAntesDoDia` × 6 + integração do encadeamento
  no orquestrador). Suíte **2325 passed, 16 skipped** · guardas de versão
  9/9 · cobertura **90,06%** (gate 90) · **6 mutações** detectadas e
  restauradas bit-exato.

OD // CORE

## [1.19.2] — CORREÇÕES DA AUDITORIA DAS CONVERSAS 🔍 (2026-10-08)

> **DEPLOY AUTORIZADO PELO DONO (08/10):** checklist do
> `docs/VERSIONAMENTO.md` §5 completo — `.env` · capabilities · `pubspec
> 1.19.2+2041` · `_APP_VERSION_CODE=2041` · `site 2x` · APKs rebuildados ·
> restart do `od-core` (regra 13).

Achados da auditoria das 230 mensagens / 115 turnos gravados entre
29/09 e 07/10 (§8 de `iniciar/2026-10-07_conversa_omegadrakon.md`):

- **fix(intents): verbos de agenda entram na detecção de escrita** —
  'Marque na agenda um compromisso…', 'agende uma reunião…', 'coloque na
  minha agenda…', 'anote…', 'registre…' casavam NENHUMA intenção de
  escrita ('coloque … compromisso' caía na **leitura** de eventos) e o
  turno entregava a recusa que o LLM gravara no cache 45 min antes.
  `_GOOGLE_W_CRIAR_RE` passou a casar marcar/agendar/colocar/anotar/
  registrar (e 'coloque no drive um arquivo X' → `google_drive_create`).
- **fix(intents): 'reunião' no singular** — `_GOOGLE_W_CAL_RE` casava só
  `reuni[õo]es?` ('reuniões'); 'agende uma reunião' nem via a Agenda.
- **fix(intents): pergunta diária sem dizer 'agenda'** — 'o que tem pra
  hoje' / 'tenho algo hoje' / 'o que vou fazer amanhã' iam para o LLM,
  que respondia 'você não tem tarefas' SEM consultar nada. Agora leem a
  Agenda de verdade (`days=1/2`), com guarda para 'no sistema'/'no drive'
  continuarem fora.
- **fix(intents): título não herda preposição** — 'agende a reunião com o
  pedro' virava título `'com o pedro'` e 'registre a reunião de amanhã'
  `'de'`; o conector 'com o/a' entrou na limpeza e o artigo só é cortado
  quando termina em espaço/fim de frase (sem cortar `'atas'` → `'tas'`).
- **fix(orchestrator): rota verdadeira no 'sim' que executa a luz** — o
  ramo do stream não reatribuía `route_detail` (default do `safe_math`):
  toda execução de luz saía na telemetria como `fastpath:math`. Agora
  `fastpath:ha_device_control`, igual ao caminho síncrono. Mutação:
  reatribuição removida → teste novo vermelho.
- **fix(intents): lista grande avisa o corte** — o título contava tudo e a
  lista cortava (Drive: '20 arquivo(s)' com 15 itens; Gmail: 'N' com 10)
  → '… e mais N não listado(s)'.
- **fix(cache): coluna `profile` = o perfil QUE PERGUNTOU** — `set()`
  gravava `self._profile` (fixo, 'guardian') em vez do `profile=` do
  orquestrador; **71/71 linhas** saíram como 'guardian'. Agora grava o
  perguntador; as **21 linhas** erradas do banco foram reatribuídas
  **pela chave** (make_key reproduz o par instância×perfil — 0 chaves não
  reconhecidas, 0 ambíguas) por `runtime/llm_cache_saneamento.py`, com
  snapshot em `backups/llm-cache-perfil-20261008-*.bak`.
- **poda: 17 respostas devaneio fora do cache** (prova viva de 06-07/10) —
  'CPU 31,7 °C na porta 5000', '10 Mbps. Estado verificado.', fase da lua
  com 'Fonte: Open-Meteo — leitura real de agora', 4 curiosidades da Lua
  com dados inventados, xintoísmo → cristianismo, recusas falsas de
  Agenda, 'LLM gemma', 'sim, tenho acesso ao seu Drive', '/' como raiz do
  Drive, 'sou o dono adm' e a recusa de criar compromisso. Snapshot com
  **todas** as colunas (rollback `INSERT` executável) em
  `backups/llm-cache-poda-20261008-*.bak`; a poda é idempotente.
- **fix(mqtt): ponte para SEM socket aberto** — `stop()` podia acontecer
  entre a checagem de `_closed` do loop e o `connect()`: o socket abria
  DEPOIS da desconexão e ficava vivo (ponte "parada" com conexão viva) —
  era a corrida que deixava
  `test_start_stop_thread` falhando 1 em 3 vezes (também no worktree
  limpo). Agora `connect()` recusa ponte encerrada e `run()` desconecta
  no `finally`; dois testes determinísticos + `start()` reabre.
- **fix(intents): verbo de ACESSO é leitura** — 'olhe/acessa/consulte
  minha agenda', 'acessa meus e-mails', 'abra o google drive' não casavam
  com nenhum detetor (pedido real do dono em 06/10, [665]) e ia para o
  LLM; agora são `google_*_list` (dado real).
- **já estavam corrigidos (sem código novo):** identidade do modelo
  (prompt declara 'Qwen — qwen2.5-coder-3b servido pelo llama-server' e
  proíbe GPT/Claude) e o fuso na mensagem de sucesso do calendário
  (entregues na 1.19.1) — os achados da auditoria eram mensagens antigas.
- **Evidência:** suíte **2318 passed, 16 skipped** (**+19 testes** sobre
  as 2299 da 1.19.1) · guardas de versão 9/9 · gate de cobertura
  **90,10%** · **5 mutações** detectadas e restauradas (`route_detail`
  sem reatribuir, verbos de agenda fora da regex, coluna `profile` de
  volta ao fixo, `finally` do `run()` sem desconectar, `connect()` sem a
  guarda de `_closed`).

---

## [1.19.1] — ESCRITA NO AR + 2 BUGS DA PROVA VIVA CORRIGIDOS ✍️🧪 (2026-10-07)

- **feat(google) NO AR:** o dono re-autorizou (código capturado com os
  **7 escopos** → token trocado, `refresh` presente, backup do token
  readonly em `backups/google-token-readonly-pre-escrita-20261007-133924.json`,
  NÃO commitado) e o restart ligou `autorizado=True` — catálogo **78
  actions** com as 7 de escrita vivas (gate admin + confirmação 2 passos).
- **fix(intents): 'com o título X' vence a sintaxe** — a prova viva pegou
  o extrator: 'crie um compromisso na minha agenda amanhã às 15h com o
  título Prova de Escrita OD' virava o título
  `'na minha agenda   com o título Prova de Escrita OD'`. Agora o
  marcador explícito vence: título = o que vem depois dele, 'quando'
  procurado ANTES; frases naturais intactas (mutação: marcador removido →
  teste novo vermelho).
- **fix(actions,intents): fuso do dono na confirmação E no sucesso** —
  'às 15h' aparecia como 'em 2026-10-08 18:00' (a API da Agenda fala UTC;
  o `parse_when` guarda o instante certo, mas os textos fatiavam o
  string cru). Novo `_quando_legivel()` (canônico em `core/intents.py`,
  camada correta para o formatter) converte para o fuso local e é usado
  pela confirmação (`google_calendar_create`) e pela mensagem de sucesso
  (`format_intent_result`); dia inteiro fica como veio. Mutação:
  conversão desligada → '18:00' volta → teste (TZ fixada por fixture)
  pega.
- **bump PATCH:** `.env 1.19.1` · capabilities `1.19.1` · `pubspec
  1.19.1+2040` · `_APP_VERSION_CODE=2040` · `site 2x` · APKs rebuildados
  (aapt2 `versionCode='2040' versionName='1.19.1'`).
- **Evidência:** suíte **2299 passed, 16 skipped** (+2 testes de
  regressão em TestGoogleWriteIntents) · guardas de versão 9/9.

---

## [1.19.0] — ESCRITA NO GOOGLE: Drive, Agenda e Gmail com gate + confirmação ✍️ (2026-10-03)

- **feat(google): 7 actions de escrita (lote 2)** — criar/editar/apagar
  arquivo no Drive, criar/apagar compromisso na Agenda, enviar/apagar
  e-mail no Gmail. Escopo cheio aprovado pelo dono no `txt.txt` e
  re-autorizado no mesmo dia — o **código de retorno veio com os 7
  escopos** (13:38, log do capturador), mas a **troca pelo token NÃO foi
  concluída**: o token em disco segue com os 3 readonly e as actions de
  escrita degradam honestamente (`ok=False`) até a re-autorização do dono.
- **Gate de papel (só admin):** escrita continua FORA da allowlist do
  papel `user` (`core/security/permissions.py` intocado); a negação do
  Registry virou `permissao_negada` guiada para as 7 actions no
  `core/orchestrator.py` (espelho do `ha_device_control`) — resposta
  honesta, **nunca o LLM**.
- **Confirmação de 2 passos:** 1ª menção registra (TTL 120s, chave por
  usuário+ação+parâmetros) e pede "sim"; o mesmo user executa dentro do
  TTL; **consumo só após sucesso** (erro do Google mantém a intenção).
  Implementado em `tools/actions/actions.py` (`_WRITE_CONFIRMATIONS`,
  `peek/drop_pending_google_write`).
- **Alvo obrigatório e resolvido:** nome → id ANTES da confirmação;
  0 resultados → `nao_encontrado`, N>1 → `alvo_ambiguo` (nada em lote),
  arquivo nativo do Google → `nativo_google` com dica. Sem alvo →
  `alvo_obrigatorio` com exemplo de frase.
- **Intents determinísticas:** `_detect_google_write` roda ANTES da
  leitura ("apague o e-mail da ana" nunca casa como listagem), extrai
  nome/conteúdo/título/quando/destinatário/corpo da frase e fica FORA do
  `FASTPATH_ACTIONS` (allowlist de leitura — teste garante). Formatter
  próprio (`_format_google_write`) para permissão/alvo/pendência/execução.
- **Dois caminhos:** `process` e `process_stream` consultam a pendência
  de escrita antes do detetor, com conferência de coerência do 'sim'
  (mesma regra v1.9.1) e descarte em caso de incoerência.
- **Catálogo 71 → 78 actions** (google 6 → 13) em `tools/actions/actions.py`
  com `user_id`/`alvo` nos params.
- **bump MINOR:** `.env 1.19.0` · capabilities `1.19.0` · `pubspec
  1.19.0+2039` · `_APP_VERSION_CODE=2039` · `site 2x` · APKs rebuildados
  (aapt2 `versionCode='2039' versionName='1.19.0'`).
- **Evidência:** suíte **2297 passed, 16 skipped** · cobertura **90,30%**
  (gate 90) · **5 mutações** detectadas e restauradas bit-exato (gate
  removido, confirmação eliminada, detetor fora da cadeia, consumo antes
  do sucesso, formatter sem ramo de escrita) · `flutter analyze` 0 ·
  `flutter test` 131/2.
- **registro retroativo do CI (feito em 08/10, não anotado na época):**
  o run **37147058947** do commit `ced23cc` (03/10 19:12 UTC, 'site:
  atualiza índice e APKs para v1.19.0+2039') terminou **VERMELHO** no
  step `Suíte completa + gate de cobertura ≥ 90%` (exit 1) e ficou sem
  registro aqui — a cadeia só voltou a verde em `a7c3e1d` (07/10 16:19).
  Achado pela consulta à API de Actions na auditoria das conversas de
  08/10; a nota existe para o histórico não parecer ininterruptamente
  verde.

---

## [1.18.0] — GOOGLE DRIVE/AGENDA/GMAIL EM LEITURA + CI VERDE 🌐 (2026-10-03)

- **feat(google): OAuth do dono concluído e provado no ar** — fluxo SEM
  copiar/colar (regra 14): `tools/google_oauth_helper.py` + página pública
  `/site/google_auth.html` + redirect `localhost:8766` com capturador no
  servidor (Rota B/Túnel). Token em `data/google_token.json` (0600,
  `refresh` presente, 3 escopos readonly); od-core reiniciado com
  `autorizado=True`.
- **Prova viva 3/3 no chat:** "liste meus emails recentes" → 10 mensagens
  com assunto e remetente REAIS; agenda → consulta real (0 compromissos em
  7 dias); Drive → 20 arquivos reais. `/capabilities` 71 actions · journal
  0 erros · `/supervision` restarts 0.
- **fix(google): `metadataHeaders` vira parâmetro repetido (doseq)** — a
  prova pegou os 10 e-mails "sem assunto": `urlencode` sem `doseq`
  codificava a lista como repr de Python na URL e o Gmail respondia sem
  cabeçalhos. Corrigido nos dois métodos do `GoogleClient` + teste que
  fixa o contrato (mutação detectada e revertida).
- **Ativação sem digitar:** `/site/google_apis.html` (3 botões ENABLE →
  Console) + links no `txt.txt` (canal do dono). **Regra 14** do
  `iniciar/RULES.md`: o dono não copia/colava no terminal — troca de
  informação pelo `txt.txt` e páginas clicáveis em `site/`.
- **fix(test,ci): CI VERDE no GitHub** — 177 runs vermelhos desde 15/09
  (último verde `5668b27`): websockets 17.1 trocou a mensagem de log do
  handshake e 5 testes dependiam do HOST (sysfs térmico, whisper-cli,
  piper, `/opt/omegadrakon`). Correções: `_espera_registro` com trechos
  alternativos; `cpu_temp` lendo `THERMAL_DIR`/`HWMON_DIR` (constantes) com
  sysfs de fixture + teste de degradação sem sensor; gates de voz com
  STT/Piper dublê; flag `--espeak_data` com diretório fixture; 2 canários
  reais com `skipif` (cobertura única deles medida: 90,19% sem eles).
  `ci.yml` ganhou anotações `::error::` públicas (diagnóstico sem login).
  Run **`433458e` = success**.
- **bump MINOR:** `.env 1.18.0` · capabilities `1.18.0` · `pubspec
  1.18.0+2038` · `_APP_VERSION_CODE=2038` · `site 2x` · APKs rebuildados
  (aapt2 `versionCode='2038' versionName='1.18.0'`; full `cbe5b390…`,
  arm64 `7618fb6e…`; anteriores em `backups/apk-v1.17.4+2037-20261003/`).
- **Evidência:** suíte **2241 passed, 16 skipped** · cobertura ≥ 90% ·
  `flutter analyze` 0 issues · `flutter test` **131 passed, 2 skipped** ·
  simulação CI-exata (checkout limpo + venv nova + `env -i`):
  **2240 passed, 90,15%**.

### Integração Google Workspace — leitura (2026-10-02)

- **Nova integração `integrations/google/` (stdlib puro):** OAuth 2.0
  (URL de consentimento, troca de código, refresh) + cliente Bearer com
  renovação automática e persistência do token (`data/google_token.json`,
  `0600`); serviços de **leitura** de Drive, Agenda e Gmail. Sem token salvo,
  o cliente degrada com erro legível — nunca estoura no pipeline.
- **6 actions novas (catálogo 65 → 71, categoria `google`):**
  `google_drive_list`, `google_drive_read`, `google_calendar_events`,
  `google_gmail_list`, `google_gmail_read`, `google_gmail_labels`.
  Degradam com `ok=False` sem credencial (padrão do HA).
- **Chat:** intents determinísticas — "meus e-mails", "minha agenda" e "meus
  arquivos no google drive" vão para as actions (dado REAL). Sem autorização,
  a resposta é HONESTA ('ainda não configurado'), nunca um e-mail/compromisso
  inventado. Prompt por perfil atualizado: o Google (leitura) existe quando
  configurado; escrita/lembretes/redes sociais continuam inexistentes.
- **Papéis:** admin pleno; `user` com **leitura** (decisão explícita do dono).
- **Autorização headless:** `runtime/google_auth.py` (abre a URL no navegador
  e recebe a URL de retorno colada) + `config/google_credentials.example.json`
  + guia `docs/GOOGLE.md`.
- **Sem bump:** dormente até a credencial OAuth do dono (o código e a suíte
  estão prontos; a prova viva com dados reais vem no deploy). Suíte:
  **2229 passed, 16 skipped** (+54 testes novos); cobertura 90,24%.

### Infra — CI verde em checkout limpo + gate de cobertura ≥ 90% (2026-10-02, sem bump)

- **CI quebrava em checkout limpo:** `tests/test_version_policy.py` lia o `.env`
  (gitignored) sem guarda de existência — no GitHub o arquivo não existe e a
  suíte morria com `FileNotFoundError` antes de rodar. Correção:
  `_env_version()` devolve `None` quando o `.env` não existe e o teste
  `test_env_e_capabilities_na_mesma_versao` **pula com motivo** (sem `.env`
  não há estado local a validar; a verdade passa a ser o fallback congelado,
  coberto por `test_fallback_congelado_e_a_versao_vigente`).
- **Gate de cobertura ≥ 90% estava vermelho** (89,33%): cobertura focada em
  ramos reais sem teste — `/executa` (action_list, gate por nível, status
  denied/invalid/error, parsing de params), `/entrar`, `/sair`, `/historico`,
  `/cache` e `/gerar`; CLI `migrate_history_owner.main()` (dry-run/apply, com o
  snapshot redirecionado para `tmp_path`); `WhisperSTT._convert_to_wav` +
  transcrição vazia/WAV inválido. Resultado: **90,17%** (12592 stmts, 1238
  perdidas).
- Suíte: **2175 passed, 16 skipped** (+26); `compileall` limpo. Sem bump: é
  infraestrutura de teste/CI, sem mudança de comportamento em produção (mesmo
  precedente do orquestrador de CLIs de 2026-09-30).

## [1.17.4] — APK UNIVERSAL ÍNTEGRO: 3 ABIs com libflutter+libapp de verdade 📦 (2026-10-01)

- **fix(app,build): o APK "completo" publicado não era completo** — os
  artefatos de 19,5 MB publicados em 01/10 (21:31 e 21:59) tinham
  `libflutter.so` APENAS em arm64-v8a; armeabi-v7a e x86_64 ficavam
  com só 2 arquivos de ~0,1 MB por ABI **sem `libflutter.so`** — o app
  não subia nelas (análise dos ZIPs publicados registrada no achado da
  v1.17.3; os artefatos quebrados foram sobrescritos por este rebuild,
  por isso sem bytes exatos aqui). Causa raiz:
  `intermediates/flutter/release/` do build de ontem só continha
  `arm64-v8a/` — estado incremental envenenado; **não** era configuração
  (AGP 9.2/Gradle 9.4 íntegros, `-Ptarget-platform` sem override).
- Correção: `flutter clean` + rebuild pelo `app/build_apk.sh`
  canônico → universal **53.972.629 B (~54,0 MB)** com as 3 ABIs
  completas (libflutter 11,7/8,6/13,0 MB + libapp 5,9/6,6/6,1 MB) e
  split arm64 **19.245.103 B (~19,2 MB)**; ambos
  `versionCode=2037 versionName=1.17.4` (aapt2). Publicados em `site/`.
- **fix(docs): rótulo da entrega de voz alinhado à release real** —
  14 comentários (.py/.dart) diziam `v1.18.0` (versão inexistente); a
  voz saiu mesmo é na **1.17.3** (já anunciada no ar — release no ar
  não se reescreve, regra do registro honesto). `v1.18.0` fica livre
  para a PRÓXIMA feature (regra 12: voz era MINOR, mas a 1.17.3 já
  foi para o ar como PATCH — desvio registrado, não corrigido retroativamente).
- **test(guarda nova): `test_nenhuma_referencia_a_versao_futura_no_codigo`**
  (`tests/test_version_policy.py`, cobertura 9) — nenhum `.py`/`.dart`
  pode citar `vX.Y.Z` maior que `OD_VERSION` vigente; mutação
  `v9.9.9` em `runtime/launcher.py` → vermelho → restaurado bit-exato.
- Registro: `txt.txt` (gitignored) teve "comunicação por voz" removida
  — restam Drive/Agenda/Gmail.
- Evidência: suíte Python **2149 passed, 16 skipped**; `flutter analyze`
  sem problemas; `flutter test` **131 passed, 2 skipped**.
- bump PATCH: `.env 1.17.4` · `capabilities` fallback `1.17.4` ·
  `pubspec 1.17.4+2037` · `_APP_VERSION_CODE=2037` · `site 2x` +
  tamanhos reais (~19 MB / ~54 MB) · `CHANGELOG [1.17.4]` ·
  `README_VERSAO §1.17.4`

## [1.17.3] — TTS ROBUSTO: LD_LIBRARY_PATH forçado no handler + env do subprocesso 🔊 (2026-10-01)

- **fix(runtime,tools): Piper TTS nunca mais falha por libs compartilhadas ausentes** —
  o `build_voice_handlers()` (launcher) agora **FORÇA** o `LD_LIBRARY_PATH` para
  `/opt/omegadrakon/voice/piper` (onde as libs do deploy moram) em vez de só
  setar se ausente; o `PiperTTS.synthesize_to_file()` passa `env` customizado
  com o caminho correto direto no `asyncio.create_subprocess_exec()` —
  imune a poluição de env por testes/outros processos.
- Causa raiz: a suíte completa rodava 2148 testes, mas o teste
  `test_tts_handler_devolve_wav_real` falhava intermitentemente porque
  `test_audio.py` criava instâncias `PiperTTS` com paths falsos e o launcher
  via `LD_LIBRARY_PATH` já setado (ainda que vazio/errado) e não corrigia.
- Evidência: suíte completa **2148 passed, 16 skipped** (era 1 falha flaky).
- bump PATCH: `.env 1.17.3` · `capabilities` fallback `1.17.3` ·
  `pubspec 1.17.3+2036` · `_APP_VERSION_CODE=2036` · `site 2x` ·
  `CHANGELOG [1.17.3]` · `README_VERSAO §1.17.3`

## [1.17.2] — GUARDA DA CASA DE LIMITAÇÕES: pytest não suja mais o registro real 🧪 (2026-10-01)

- **fix(tests): fixture autouse isola `limitacoes.txt` em tmp_path** —
  causa raiz provada dos "eventos recorrentes" (13:47, 14:47, 15:41,
  16:21 — sempre as MESMAS 3 perguntas, incluindo o typo 'temperatuda'):
  os testes de integração simulam ações degradadas com frases literais
  ('quantas pessoas na rede?' com /proc vazio, 'qual a temperatuda em
  presidente venceslau sp' sem fonte) e os hooks do Orchestrator
  gravavam no arquivo REAL da raiz a cada rodada de pytest. Prova:
  teste isolado gerou entrada nova (47→50 linhas, ts 16:46).
- `tests/conftest.py` (NOVO): redireciona LIMITACOES_FILE para tmp_path
  por teste + isola o dedup em memória. Arquivo real limpo (o conteúdo
  era 100% artefato de teste — **o chat do dono NUNCA degradou**;
  network_hosts e weather_city respondem ok pelo fastpath no ar).
- Teste do teste: mutação no-op na fixture → gravação volta (detectada);
  guarda restaurada → 0 gravações na suíte completa (2139 passed).
- bump PATCH: .env 1.17.2 · capabilities · pubspec 1.17.2+2035 ·
  _APP_VERSION_CODE=2035 · site 2x · CHANGELOG [1.17.2] · README §1.17.2

## [1.17.1] — HONESTIDADE DO MOTOR: o prompt declara o QWEN servido, não o gemma que não roda 🏷 (2026-10-01)

- **fix(agents,capabilities): motor declarado == motor servido** — o
  sandbox da 8082 (01/10) provou com o gemma-4-E4B real: carrega nesta
  máquina (4,98 GB em disco), mas não serve o chat — ~5 tok/s em CPU
  (2 threads), o pensamento do modelo estoura os 512 tok do max_tokens
  do OD (resposta vazia) e 2 instâncias simultâneas ameaçam OOM (RAM
  7,7 GB, swap 88–100%). Decisão do dono: manter o **qwen2.5-coder-3b**
  no ar e declarar a verdade — o system prompt dizia 'gemma (gemma-4-E4B)'
  e o unit do systemd se descrevia como gemma com o binário real sendo
  qwen (rastro de troca sem revisão).
- Corrigidos: prompt do motor (personality.py, todos os papéis e
  perfis), capabilities (llm-provider), Description do unit od-llm
  (com a alternativa gemma documentada para hardware maior) e
  Comentários. Provider 'gemma-local' (nome interno do core) permanece
  — não é declaração de modelo.
- Testes endurecidos: test_motor_real fixa 'qwen' presente + 'gemma-4-e4b'
  AUSENTE em todos os papéis e perfis. Suíte 2139 passed, 16 skipped.
- bump PATCH: .env 1.17.1 · capabilities · pubspec 1.17.1+2034 ·
  _APP_VERSION_CODE=2034 · site 2x · CHANGELOG [1.17.1] · README §1.17.1

## [1.17.0] — PERSONALIDADES REALMENTE DISTINTAS: a Plêiade deixa de responder num só jeito 🎭 (2026-10-01)

- **feat(agents): blocos de voz completos por perfil** — queixa real do
  dono: "as personalidades são diferentes, porque todas respondem do
  mesmo jeito". Causa provada: o system prompt carregava ~95% de texto
  idêntico entre perfis (identidade, motor, limites por papel) e a
  ÚNICA linha variável era o resumo `Tom do perfil: ...` — sinal
  minúsculo para o LLM local (gemma). Cada um dos 7 perfis (Guardian,
  Regulus, Luma, Vox, Athenae, Nyx, Nexus) agora carrega um bloco
  `COMO VOCÊ FALA` com identidade no papel, registro/sintaxe, ritmo,
  o que faz, o que NUNCA faz, frase-assinatura e micro-exemplo
  (começo literal de resposta) — injetado com precedência sobre o
  resumo curto, que permanece por compatibilidade.
- +9 testes (TestVoiceBlocks em tests/test_personality.py): bloco
  presente em todos os perfis, estrutura completa, unicidade par a
  par, auto-nomeação, precedência sobre o resumo, micro-exemplos
  distintos e guarda da causa raiz (prompts de perfis diferentes
  divergem >400 chars).
- **Teste do teste — 3/3 mutações bit-exata:** M1 bloco da Nyx clonado
  do da Athenae → 4 falhas; M2 `voice = ""` (bloco ignorado) → 3
  falhas; M3 bloco movido para ANTES do resumo → 1 falha.
- Sem mudança de rotas/contrato: o catálogo de perfis (/profiles), os
  transportes e o cache (que já isola por perfil) ficam intactos.
- bump MINOR: .env 1.17.0 · capabilities · pubspec 1.17.0+2033 ·
  _APP_VERSION_CODE=2033 · site 2x · CHANGELOG [1.17.0] · README §1.17.0

## [1.16.0] — POOL POSTGRES AUTO-CURÁVEL: conexão morta nunca mais vira erro interno no chat 🩹 (2026-10-01)

> **Política:** correção de robustez interna (sem rota/endpoint/action
> nova) com testes novos = MINOR conservador (`docs/VERSIONAMENTO.md` §1).
> **Versões:** servidor `OD_VERSION=1.16.0` · app `1.16.0+2032`
> (versionCode 2032 — auto-atualização do celular).

### Corrigido (bug real de 01/10, §17 da sessão)

O Postgres reiniciou de madrugada (06:31) e o od-core (de pé desde
30/09 21:36) manteve no pool as conexões que o banco encerrou: toda
query de usuário/sessão/cache falhava com `network error` (pg8000 para
socket morto) e o chat devolvia **erro interno** — o pool
(`PostgresConnectionPool.acquire`) servia conexão podre PARA SEMPRE,
pois nunca validava o que entregava.

| Peça | Entrega |
|---|---|
| **Validação no acquire** | conexão ociosa só é entregue após `SELECT 1` (`_conn_viva`); qualquer falha = podre |
| **Auto-cura** | conexão morta é fechada, removida da contagem (`_discard`) e substituída por uma nova — o sistema se recupera sozinho quando o Postgres reinicia (sem restart do od-core) |
| **Contrato intacto** | pool esgotado continua BLOQUEANDO na fila (sem estouro de conexões) — agora fixado por teste |
| **SQLite intacto** | `ConnectionPool` (SQLite) não muda uma linha |

### Evidência

```
servidor: pytest tests/ → 2130 passed, 16 skipped
  (+5 TestPoolPostgresConexaoMorta em test_database.py)
Teste do teste: 3/3 mutações detectadas e revertidas bit-exata —
  M1 validação desligada (if True) → 2 falhas;
  M2 socket morto tratado como vivo (except Exception → RuntimeError)
    → 2 falhas;
  M3 fila bloqueante virou criação fora do lock → 1ª rodada SOBREVIVEU
    por teste fraco (pool não estava esgotado) — teste endurecido com o
    contrato do cabeçalho do módulo (bloqueia, nunca estoura), mutação
    re-detectada (1 falha)
bump MINOR: .env 1.16.0 · capabilities · pubspec 1.16.0+2032 ·
  _APP_VERSION_CODE=2032 · site 2x · CHANGELOG [1.16.0] · README §1.16.0
```

---

## [1.15.0] — GUARDAS DO CACHE ENDURECIDAS: as 3 cegas do cache_failure_reason fechadas 🛡 (2026-09-30)

> **Política:** correção de robustez interna (sem rota/endpoint/action
> nova) com testes novos = MINOR conservador (`docs/VERSIONAMENTO.md` §1).
> **Versões:** servidor `OD_VERSION=1.15.0` · app `1.15.0+2031`
> (versionCode 2031 — auto-atualização do celular).

### Corrigido (2026-09-30, §15 — auditoria das 39 entradas do cache)

| Cega (as 4 podas manuais NÃO deviam ter nascido) | Fix |
|---|---|
| **Etiqueta de log no MEIO** ('…limpeza. [INFO] Limpeza solicitada…' — o ban só-prefixo via `startswith` não via) | `_CACHE_ETIQUETA_EM_QUALQUER_POSICAO`: regex `\[(nicky])?(crit\|warn\|online\|info)\]` em qualquer posição |
| **Frase seca de execução do lar** ('Acesse a luz do corredor!' — o ban da v1.9.1 só pegava '💡 Confirmar:'/'✅ ' com emoji) | `_CACHE_BAN_LAR_SECOS`: imperativo (`acessa/acenda/apague/desligue/ligue`) ancorado no início |
| **Recusa falsa de 'código proprietário'** (llama.cpp é open-source E do próprio dono) | 2 novos padrões em `_CACHE_BAN_REFUSALS`: `c[óo]digo propriet[áa]rio` + `n[aã]o posso compartilhar detalhes espec[íi]ficos` |
| **Placeholder como resposta** ('"Em construção..."') | `_CACHE_BAN_ESTADO_PAGINA` ancorado no início (o 'obra em construção avança' no MEIO continua cacheável) |

### Evidência

```
servidor: pytest tests/ → 2125 passed, 16 skipped
  (+12 TestCacheBansV115 em test_resposta_transparente)
Teste do teste: 4/4 mutações detectadas e revertidas bit-exata —
  M1 etiqueta-em-qualquer-posição desligada → 3 falhas;
  M2 ban do lar seco desligado → 4 falhas;
  M3 recusa 'código proprietário' removida → 1 falha;
  M4 estado de página desligado → 2 falhas
bump MINOR: .env 1.15.0 · capabilities fallback · pubspec 1.15.0+2031 ·
  _APP_VERSION_CODE=2031 · site (2x)
```

---

## [1.14.0] — CÂMBIO REAL: 'cotação do dólar' vem da FONTE, não da alucinação do modelo 💱 (2026-09-30)

> **Política:** action nova no catálogo (64 → 65) = funcionalidade com
> compatibilidade → MINOR (`docs/VERSIONAMENTO.md` §1).
> **Versões:** servidor `OD_VERSION=1.14.0` · app `1.14.0+2030`
> (versionCode 2030 — auto-atualização do celular).

### Adicionado (2026-09-30)

| Peça | Entrega |
|---|---|
| **Pedido do dono** | Prova viva da 1.13.0 (§12.1): 'quanto está a cotação do dólar hoje?' → o gemma INVENTOU 'US$ 5.20' com confiança (e a mentira entrou no cache e renascia). O gap: mentira confiante não é recusa — os hooks da 1.13.0 não pegam. Solução da casa: interceptar ANTES do modelo com dado REAL (mesma receita da weather_city) |
| **Action `exchange_rate`** | catálogo 64 → 65 (system=17): **AwesomeAPI** (economia.awesomeapi.com.br, gratuita, sem chave, urllib stdlib); USD/EUR/GBP/ARS/JPY/CNY/CAD/AUD/CHF/BTC contra o real; bid/ask/variação %/faixa do dia; aliases da fala do dono ('dólar', 'libra', 'iene', 'bitcoin'…) + sigla solta ('usd') |
| **Detecção de intenção** | moeda + sinal de cotação ('cotação', 'quanto está/custa/vale', 'valor', 'preço') → `exchange_rate`; 'história do dólar' e 'quantos dólares cabem numa mala' NÃO pegam (sem sinal de cotação); 'temperatura do servidor' segue cpu_temp |
| **Formatter pt-BR** | `_brl()` com 4 casas sem zeros à direita e SEM notação científica (o `.4g` viraria '3.501e+05' para o BTC); seta 📈/📉 na variação; degradação → None (nunca LLM inventa) |
| **Honestidade** | sem rede → `fonte_indisponivel`; moeda desconhecida → lista de opções; formatter devolve None e o pipeline degrada guiado + Casa de Limitações registra sozinho |

### Corrigido

- **3 bugs LATENTES de `log.warning`:** o NickyLogger não tem `.warning()`
  (só `.warn`) — `ha_states`, `ha_state` e `weather_city` usavam `.warning`
  no tratamento de falha de rede: o AttributeError esconderia o erro real
  exatamente quando a rede caísse. Corrigidos os 3 + o novo código já nasce
  com `.warn`.

### Evidência

```
servidor: pytest tests/ → 2103 passed, 16 skipped
  (+6 test_intents TestExchangeRate · guardas 64 → 65 em 4 arquivos de teste)
Teste do teste: 4/4 mutações detectadas e revertidas bit-exata —
  M1 detecção desligada (`if False and`) → 6 falhas;
  M2 formatter zumbi (return "zumbi" nos 2 None do bloco) → 1 falha;
  M3 validação de entrada morta (`moeda or "usd"`) → 1 falha;
  M4 spec fora do catálogo → 6 falhas
bump MINOR: .env 1.14.0 · capabilities fallback · pubspec 1.14.0+2030 ·
  _APP_VERSION_CODE=2030 · site (2x)
```

---

## [1.13.0] — CASA DE LIMITAÇÕES + CANAL DE IDEIAS: o sistema percebe o que não sabe 🪞💡 (2026-09-30)

> **Política:** canais novos de interação dono↔sistema (painel admin + API
> + app) = funcionalidade com compatibilidade → MINOR (`docs/VERSIONAMENTO.md` §1).
> **Versões:** servidor `OD_VERSION=1.13.0` · app `1.13.0+2029`
> (versionCode 2029 — auto-atualização do celular).

### Adicionado (2026-09-30)

| Peça | Entrega |
|---|---|
| **Pedido do dono** | O dono perguntou valor do dólar e temperatura de outra cidade e o sistema não sabia — mas não PERCEBEU que não sabia (a action só nasceu porque o agente criou na mão). O sistema deve se auto-observar; e o canal do dono (txt.txt) vira canal de IDEIAS |
| **core/limitacoes.py (NOVO)** | Casa de limitações: `registrar_limitacao(motivo, pergunta)` grava em `limitacoes.txt` (teto 128 KB, dedup 6h por (motivo, pergunta), append atômico com separador de bloco `\n\n` e poda por blocos) — NUNCA propaga exceção (defesa total: qualquer falha vira `log.warn` e False); hooks `registrar_fallback_honesto(pergunta)` (fallback honesto esgotado na `_resolve_refusal`) e `registrar_action_degradada(action, pergunta)` (action degradou, `format_intent_result` → None) |
| **Hooks no orchestrator** | 3 pontos: fallback honesto esgotado (~:1334) e os 2 caminhos de action degradada (stream ~:782 e REST ~:1124) — o sistema registra sozinho quando percebe que falhou |
| **Rotas admin (5)** | `GET/PUT/DELETE /admin/ideias` (txt.txt — canal do DONO: ideias de melhoria, 20 KB, escrita atômica tmp+rename) e `GET /admin/limitacoes` + `DELETE /admin/limitacoes` (registro AUTOMÁTICO do sistema) — todas auth=True; `do_PUT` no handler HTTP e PUT no Allow do OPTIONS |
| **Painel /admin** | Seção "Ideias (txt.txt)" (ler/escrever/limpar) e "Limitações (registro automático)" (listar/limpar) — o dono vê e escreve pelo navegador |
| **App (paridade total)** | `od_api.dart` +8 métodos (dev-pedido + ideias + limitações); dashboard com 3 cards novos: Pedido de desenvolvimento (injetar/limpar), Ideias (escrever/ler/limpar) e Limitações (listar/limpar) — o app reflete o site |
| **Snapshot** | txt.txt (dump de roteador TP-Link) arquivado em `backups/txt-pre-canal-ideias-20260930.txt` (sha256 e3c7305c…) e zerado — vira canal puro de ideias |

### Corrigido

- **Bug real no módulo novo:** separador de bloco era 1 `\n` (a leitura
  juntava as entradas e o teto nunca podava) — corrigido para `\n\n`.
- **Escape JS no painel:** `\n` dentro de triple-quoted string Python é
  escape real — JS precisava `\\n`; quebra pega pela guarda
  `test_painel_pages_js_compiles` (node --check).

### Evidência

```
servidor: pytest tests/ → 2097 passed, 16 skipped
  (+14 test_limitacoes · +10 test_api: TestAdminIdeias 5 + TestAdminLimitacoes 3
   + guardas de rotas 45 → 50)
app: flutter analyze 0 issues · flutter test 125 passed, 2 skipped (+11 dart)
Teste do teste: 4/4 mutações detectadas e revertidas bit-exata —
  M1 dedup `if False` → 2 falhas;
  M2 defesa `raise` no lugar do except → 1 falha (1ª rodada SOBREVIVEU —
  TestDefesaDoPipeline criado, mutação re-detectada);
  M3 teto `while False` → 1 falha;
  M4 hook desligado no orchestrator → 1 falha
```

---

## [1.12.0] — CLIMA DE CIDADE REAL: 'temperatura em presidente venceslau' responde a CIDADE pedida 🌤 (2026-09-30)

> **Política:** action nova no catálogo (63 → 64) = funcionalidade com
> compatibilidade → MINOR (`docs/VERSIONAMENTO.md` §1).
> **Versões:** servidor `OD_VERSION=1.12.0` · app `1.12.0+2028`
> (versionCode 2028 — bump de linhagem; o app não muda de conteúdo).

### Adicionado (2026-09-30)

| Peça | Entrega |
|---|---|
| **Pedido do dono** | Ação 3 da análise de coerência §14 (30/09): pendência da 1.11.1 — "action de clima por cidade (hoje o HA responde o clima da casa para qualquer cidade pedida)" |
| **Action `weather_city`** | catálogo 63 → 64 (categoria iot=5): geocoding + forecast atuais da **Open-Meteo** (gratuita, sem chave, urllib stdlib — sem dependência nova); nome resolvido ('Presidente Venceslau, São Paulo, Brasil'), temperatura, sensação, umidade, vento e condição WMO traduzida pt-BR (o formatter entrega o texto pronto — o modelo nunca traduz) |
| **Detecção de intenção** | `detect_action_intent`: cidade EXPLÍCITA na frase de clima → `weather_city`; sem cidade ('clima hoje', 'aqui') → `ha_weather` INTACTO. Extração pela regra das PONTAS: stopwords/gatilhos saem só das extremidades — 'previsão do tempo no rio de janeiro' → 'rio de janeiro' (o 'de' do MEIO pertence à cidade); UF solta ('...sp') é removida; 'temperatura do servidor' segue cpu_temp (nunca clima) |
| **Honestidade** | sem rede/cidade desconhecida → `ok=False` com erro claro ('cidade_nao_encontrada'/'fonte_indisponivel') — o formatter devolve None e o pipeline degrada guiado; NUNCA dado inventado (padrão da casa) |
| **Falsy-safe** | weather_code 0 (céu limpo) é VÁLIDO — conversão via `_wmo_condition` com `is not None`, não `or` |

### Corrigido

- Teste v1.8.0 que fixava cidade → `ha_weather` atualizado ao contrato da
  1.12.0 (cidade explícita → `weather_city`; genérico segue `ha_weather`).

### Evidência

```
servidor: pytest tests/ → 2075 passed, 16 skipped (+20 no TestWeatherCity)
ambiente canônico: .venv SEM OD_TEST_POSTGRES_DSN
Teste do teste: 4/4 mutações detectadas e revertidas bit-exata —
  M1 rota de cidade desligada → 9 falhas;
  M2 extração só com a última palavra → 8 falhas;
  M3 conversão falsy (or engole o 0) → 1 falha;
  M4 degradação respondendo texto quebrado → 1 falha (1ª rodada
  SOBREVIVEU por teste fraco — teste endurecido com os 4 erros + contrato
  sem temperature, mutação re-detectada)
guarda de coerência de versões: 1.12.0 em .env · capabilities ·
  pubspec 1.12.0+2028 · _APP_VERSION_CODE=2028 · site (2x)
```

---

## Ferramenta — Orquestrador de fallback de CLIs (2026-09-30, sem bump)

> **Sem bump:** ferramenta standalone na raiz (`orquestrador.py`), fora do
> od-core e do app — não altera a API pública nem o runtime implantado
> (mesmo precedente de `runtime/migrate_history_owner.py` e do
> reordenamento deste arquivo em 29/09). Política: `docs/VERSIONAMENTO.md`.

| Peça | Entrega |
|---|---|
| **`orquestrador.py`** | monitor de `pedido.txt` (varredura a cada 5s, leitura+limpeza anti-loop); prompt blindado (código puro, sem markdown/cercas); cascata **Freebuff → OpenCode → Kilo** via subprocesso (`shutil.which` + timeout 600s); extração de cerca markdown como defesa; validação `ast.parse` — sintaxe inválida pula para a próxima CLI; resultado gravado em `codigo_gerado.py`; tipado, `CliSpec`/`ResultadoPedido` como dataclasses |
| **Dependências** | `requirements.txt` ganha `python-dotenv>=1.0` (carga do .env: GEMINI_API_KEY, GROQ_API_KEY para o ambiente dos subprocessos) e `requests>=2.31`; instaladas na `.venv` |
| **Higiene** | `pedido.txt` criado em branco; `.gitignore` ganha `/pedido.txt`, `/codigo_gerado.py` e `/instrucoes_projeto.txt` (material local da raiz) |

### Evidência

```
pytest tests/test_orquestrador.py -q → 25 passed
Suíte completa: 2040 passed, 16 skipped (66s, .venv sem OD_TEST_POSTGRES_DSN)
Teste do teste: 4 mutações — M1 validação desligada → 4 falhas;
M2 falha tratada como sucesso → 4; M3 limpeza anti-loop desligada → 2;
M4 chaves não repassadas → 2 (1ª rodada sobreviveu por teste fraco —
dict(os.environ) já continha as chaves; teste endurecido para o contrato
de executar_cli, mutação re-detectada, revertida bit-exata)
CLIs de backup: opencode v2.0.20 · kilo 7.8.1 (~/.npm-global, sem sudo)
```

---

## [1.11.1] — PROMPT HONESTO: o modelo sabe o que é e o que o sistema não tem 🪞 (2026-09-30)

> **Política:** correção de comportamento sem feature nova → PATCH
> (`docs/VERSIONAMENTO.md` §1).
> **Versões:** servidor `OD_VERSION=1.11.1` · app `1.11.1+2027`
> (versionCode 2027).

### Corrigido (2026-09-30)

| Devaneio (§14 de 30/09) | Correção no prompt canônico (personality.py) |
|---|---|
| "qual o LLM que está usando" → "Estou utilizando a OpenAI GPT-4" (FALSO) | Motor real declarado em todos os papéis/perfis: gemma (gemma-4-E4B) via llama-server local; proibido afirmar ser GPT/OpenAI, Claude ou Gemini |
| "como está minha agenda" → depois de negar, o modelo INVENTOU 3 tarefas falsas | Capacidades inexistentes declaradas: agenda/calendário/lembretes/e-mail não existem — "isso não existe no sistema", NUNCA inventar conteúdo |

**Guardas:** `test_motor_real_declarado_em_todos_os_papeis`,
`test_motor_real_em_todos_os_perfis`,
`test_agenda_inexistente_declarada_em_todos_os_papeis` (test_personality.py,
15 no arquivo) — 3 mutações detectadas e revertidas bit-exata. Suíte
2055 passed, 16 skipped.

---

## [1.11.0] — CANAL DE DESENVOLVIMENTO: o painel admin injeta pedidos direto no orquestrador de CLIs 🛠 (2026-09-30)

> **Política:** rota nova no od-core = funcionalidade com compatibilidade →
> MINOR (`docs/VERSIONAMENTO.md` §1).
> **Versões:** servidor `OD_VERSION=1.11.0` · app `1.11.0+2026`
> (versionCode 2026 — bump de linhagem; o app não muda de conteúdo).

### Adicionado (2026-09-30)

| Peça | Entrega |
|---|---|
| **`POST /admin/dev/pedido`** | injeta texto direto no `pedido.txt` (a fila do `orquestrador.py`); `limpar_antes=true` (default) substitui, `false` ACUMULA múltiplos pedidos; escrita ATÔMICA (tmp+rename) — o monitor lê a cada 5s e nunca pega arquivo pela metade; teto de 20.000 chars |
| **`GET /admin/dev/pedido`** | estado da fila para o painel: {monitor_ativo, monitor_pid, tem_conteudo, bytes_fila, preview 400 chars} — detecção do monitor por varredura de `/proc` (argv `orquestrador.py`), stdlib puro |
| **`DELETE /admin/dev/pedido`** | esvazia a fila sem esperar o monitor (idempotente, limpa também o .tmp) |
| **Painel `/admin`** | nova seção "Canal de desenvolvimento": textarea de injeção, checkbox substituir/acumular, estado da fila com pill do monitor (NO AR/PARADO + pid), preview e esvaziar — o dono alimenta o canal sem SSH |
| **Contexto** | o orquestrador de CLIs (Freebuff → OpenCode → Kilo, entrada da sessão de 30/09) deixa de ser standalone: é o canal oficial de desenvolvimento/melhorias do sistema, com fila alimentável pelo painel; resposta a "o sistema não está criando as ações necessárias para responder as perguntas que não estão prontas" |

### Validação

- `tests/test_api.py`: +9 testes (`TestAdminDevPedido` — injeção/criação,
  acumular/substituir, status vazio/com fila, delete, 400 texto vazio/longo,
  gate 403 com usuário comum cujo pedido NÃO toca a fila). Guarda de rotas
  42 → **45**. O teste `test_painel_pages_js_compiles` pegou um bug REAL do
  JS novo na 1ª rodada (newline literal dentro de string) — a guarda
  funcionando como desenhada.
- Teste do teste: 4 mutações detectadas e revertidas bit-exata.

---

## [1.10.1] — CONEXÃO COM 4 CAMINHOS: LAN, tailnet, Funnel e DDNS sondados sozinhos 🔌 (2026-09-29)

> **Política:** correção de conexão sem capacidade nova = PATCH
> (`docs/VERSIONAMENTO.md` §1).
> **Versões:** servidor `OD_VERSION=1.10.1` · app `1.10.1+2025`
> (versionCode 2025).

### Corrigido (2026-09-29)

| Peça | Entrega |
|---|---|
| **4 caminhos sondados** | `pickBestUrl` sonda EM PARALELO a LAN (`http://192.168.0.250:8000`), o tailnet (`http://100.77.67.53:8000`), o Funnel (`https://nicky-server.tail1b1f51.ts.net`) e o DDNS do roteador (`http://nicky.theworkpc.com`) — antes só 2 (tailnet/Funnel); o DDNS http não ficava de fora quando o Tailscale do celular estava deslogado |
| **Ordem de preferência** | rota mais direta primeiro: LAN → tailnet → Funnel → roteador; o segundo vivo fica de fallback |
| **Re-sondagem em pleno uso** | `isAvailable` re-sonda os 4 caminhos quando primária E fallback morrem (rede trocou — Wi-Fi ↔ dados, Tailscale subiu/caiu); o fallback REST do streaming também re-sonda em erro de rede |
| **Rótulo local/internet** | classificação por HOST (192.168.x/100.x = local) — o DDNS http é internet, não "rede local" |

### Validação

- App: flutter analyze 0 issues; flutter test 114 passed, 2 skipped
  (+10: 6 da sonda de 4 caminhos, 2 da re-sondagem, 1 do streaming com
  re-sondagem e 1 de rótulo/contrato).
- Teste do teste: 4 mutações TODAS detectadas e revertidas bit-exata
  (ordem trocada → 2 falhas; re-sondagem do isAvailable → 1; do REST →
  1; fallback guardado → 2).
- Suíte do servidor: 2015 passed, 16 skipped (sem mudança de backend;
  apenas `_APP_VERSION_CODE` 2024 → 2025).

---

## [1.10.0] — PAINÉIS NO APP: dashboard e admin com as mesmas funcionalidades do site 📊 (2026-09-29)

> **Política:** capacidade nova para o usuário final (o app ganha a aba
> Painel com conta e gestão admin) = MINOR (`docs/VERSIONAMENTO.md` §1).
> **Versões:** servidor `OD_VERSION=1.10.0` · app `1.10.0+2024`
> (versionCode 2024).

### Adicionado (2026-09-29)

| Peça | Entrega |
|---|---|
| **OdApi** | 7 métodos novos consumindo os contratos JÁ existentes do servidor: `getMe` (/auth/me com role), `getDashboardStats` (/dashboard/stats), `changePassword` (/account/password — devolve `sessions_closed`), `rotateApiKey` (/account/api-key), `getAdminUsers` (/admin/users), `adminResetPassword` e `adminDeleteUser` |
| **Tela Painel (nova aba)** | `DashboardScreen` como 3ª aba (Chat · Ações · **Painel** · Status · Config): conta logada com papel, mensagens da conta, stats do sistema, troca da própria senha (encerra sessões e volta ao login) e rotação da API key |
| **Seção Admin (gate por papel)** | Visível só com `role=admin` do /auth/me (o gate de verdade segue no servidor com 403): lista de contas com sessões/msgs, reset de senha, remoção de conta (dono não é alvo) e baldes legados — mesmo conteúdo do /admin do site |
| **Modo avançado** | `_onAdvanced` atualizado para o índice 4 (Config) — regressão pega pelo teste de widget antes do deploy |

### Cobertura

- app/test/od_api_test.dart: +9 (role do /auth/me, stats, troca de senha
  ok e com erro do servidor, rotação de key, /admin/users com Bearer e o
  403 propagado para papel user, reset e remoção na rota certa).
- flutter analyze 0 issues · flutter test 105 passed, 2 skipped.

## [1.9.1] — COERÊNCIA DO LAR: o chat nunca mais responde por dispositivo errado 🎯 (2026-09-29)

> **Política:** correção de incoerência nas respostas (sem capacidade nova)
> = PATCH (`docs/VERSIONAMENTO.md` §1).
> **Versões:** servidor `OD_VERSION=1.9.1` · app `1.9.1+2023` (versionCode 2023).

### Diagnóstico (conversas reais do dono, 29/09)

| Caso | O que apareceu | Causa raiz |
|---|---|---|
| 09:36 — 'acenda a luz do corredor' + 'sim' | '✅ Luz da Varanda: desligar executado' | LLM imitou o formato determinístico em turnos errados (journal: route=llm) e executou intenção velha |
| 09:41 — 'luzes acessas' | 'Confirmar: ligar Luzes Acessas (off)?' | 'acessas' (erro de digitação) não era reconhecido como estado → caiu no LLM, que INVENTOU a entidade |
| (sistema) | Confirmações/execuções do lar no cache LLM | 'sim' virava confirmação velha eternamente |

### Corrigido (2026-09-29)

| Peça | Entrega |
|---|---|
| **Vocabulário a prova de digitação** | 'acenda/acessas/acesso' entram nos padrões de comando e estado — 'luzes acessas' → LEITURA real (nunca LLM) |
| **Coerência do 'sim'** | confirmação que menciona OUTRO lugar ('sim, da sala' com pendente do corredor) NÃO executa: recusa genérica honesta, sem LLM, e a intenção velha é descartada |
| **Plural nunca inventa entidade** | 'liga as luzes (da sala)' → resposta genérica ('não aciono várias luzes de uma vez') — nunca 'Confirmar: ligar Luzes Acessas' |
| **Cache coerente** | '💡 Confirmar:…' e '✅ … executado' são estado de conversa: NUNCA mais entram no cache LLM |

### Evidência (2026-09-29)

```
servidor: pytest tests/ → 2013 passed, 16 skipped (+6 testes de coerência;
          mqtt test_start_stop_thread flaky passa isolado — precedente 09-21)
teste do teste: 4/4 mutações detectadas e revertidas (coerência do sim,
          caminhos do plural, cache de confirmação, regex do 'sim')
APK 1.9.1+2023 (versionCode 2023) publicado em site/
```

## [1.9.0] — CONTROLE DO LAR EXPANDIDO: tomadas e dispositivos com o mesmo padrão 🔌 (2026-09-29)

> **Política:** capacidade nova para o usuário final (o dono controla
> tomadas/soquetes pelo chat, não só luzes) = MINOR (`docs/VERSIONAMENTO.md` §1).
> **Versões:** servidor `OD_VERSION=1.9.0` · app `1.9.0+2022` (versionCode 2022).

### Adicionado (2026-09-29)

| Peça | Entrega |
|---|---|
| **Vocabulário de tomada** | 'liga/desliga a tomada do servidor', 'soquete da oficina', 'desconecta', 'plug' — tudo cai no controle com gate + confirmação |
| **Leitura de tomadas** | 'quais tomadas estão ligadas' / 'quantos soquetes conectados' → ha_lights (os switches SONOFF do dono JÁ são o domínio switch) |
| **Resolução de alvo estendida** | stopwords cobrem tomada/soquete/socket/dispositivo — 'desliga a tomada do servidor' casa com switch.note_servidor_socket_1 |
| **Action renomeada** | ha_light_control → ha_device_control (mesmas camadas: gate de papel + alvo específico obrigatório + confirmação de 2 passos TTL 120s) |
| **Mensagens honestas** | 'Qual luz ou tomada?' e 'luzes e tomadas são só o dono' — a fala acompanha o escopo |

### Segurança

- Gate de papel INTACTO: user continua com só leitura (a tomada do
  servidor é infraestrutura crítica — negação determinística sem LLM).
- Sem comando em lote: 'desliga as tomadas' pede alvo específico.
- 4 mutações detectadas e revertidas (peek, ramo de negação, vocabulário,
  TTL).

### Evidência (2026-09-29)

```
servidor: pytest tests/ → 2007 passed, 16 skipped (+4 testes de tomadas;
          mqtt test_start_stop_thread flaky no run completo, passa isolado
          e por classe — precedente 09-21)
APK 1.9.0+2022 (versionCode 2022) publicado em site/
```

## [1.8.1] — CONTROLE DE LUZES PELO CHAT: ligar/desligar com confirmação de 2 passos 💡 (2026-09-29)

> **Política:** correção/completamento da capacidade do lar da 1.8.0
> (controle desenhado na 1.8.0 entra aqui) = PATCH (`docs/VERSIONAMENTO.md` §1).
> **Versões:** servidor `OD_VERSION=1.8.1` · app `1.8.1+2021` (versionCode 2021).

### Adicionado (2026-09-29)

| Peça | Entrega |
|---|---|
| **Action ha_light_control** | Liga/desliga UMA luz específica (catálogo 62 → 63, categoria iot=4) — papel admin; confirmação de 2 passos com TTL 120s (intenção pendente por user+luz+ação, consumo só após execução bem-sucedida) |
| **Resolução de alvo** | Nome falado → entity_id via entidades do HA carregadas no launcher (`configure_ha_entities`); 'liga a luz da cozinha' acha o switch real |
| **Confirmação no fastpath** | O 'sim' do user executa a intenção pendente SEM passar pelo LLM (`detect_confirmation` + `peek_pending_light_confirmation`), nos dois caminhos (process/process_stream) |
| **Gate determinístico** | Negação do Registry para ha_light_control vira resposta guiada `permissao_negada` — nunca cai no LLM (que podia alucinar confirmação) |

### Segurança

- Papel user mantém só LEITURA do lar (ha_weather/ha_lights); controle é do dono.
- A action recusa o apagão total (sempre resta ao menos 1 luz acesa) e o
  desligar de entidade inexistente.

### Evidência (2026-09-29)

```
servidor: pytest tests/ → 2002 passed, 16 skipped
APK 1.8.1+2021 (versionCode 2021) publicado em site/
```

## [1.8.0] — O CHAT FALA COM O LAR: clima, luzes e resumo do Home Assistant como dado real 🏠 (2026-09-28)

> **Política:** capacidade nova para o usuário final (clima REAL da região
> e estado do lar no chat — dados que o LLM alucinava) = MINOR
> (`docs/VERSIONAMENTO.md` §1).
> **Versões:** servidor `OD_VERSION=1.8.0` · app `1.8.0+2020` (versionCode 2020).

### Diagnóstico (leitura das conversas + integração)

- **Clima alucinado**: "temperatura agora em presidente venceslau" → o
  LLM inventou "23°C" e REPETIU a mentira quando o dono disse "mentira"
  — o sistema não tinha fonte de clima.
- **Senha alucinada**: "qual a senha do mqtt" → o LLM respondeu
  "OmegaDrakon2026" (FALSA — conferido contra o cofre) — dado sensível
  não pode vir do modelo.
- **Home Assistant ocioso**: integração no ar (health "HA alcançável",
  40 entidades: weather com 33.3°C reais, 7 luzes, bateria, roteador) e
  ZERO actions no catálogo — o chat não alcançava nenhum dado de lá.

### Adicionado (2026-09-28)

| Peça | Entrega |
|---|---|
| **Actions iot*** | `ha_weather` (weather.* real), `ha_lights` (estado das luzes, leitura), `ha_summary` (clima+luzes+pessoas+bateria+roteador; só admin) — catálogo 59 → 62, categoria nova `iot` (3) |
| **Intenções novas** | "clima/temperatura/umidade em casa/cidade/agora" → ha_weather (dado REAL, sem LLM); "quais luzes acesas" → ha_lights; "como está a casa" → ha_summary; 'tempo em média/demora' NÃO é clima |
| **Trava de credenciais** | "qual a senha do mqtt/wi-fi/postgres/telegram" → 🔐 NEGAÇÃO determinística para TODOS os papéis (inclusive admin), sem LLM — o valor real vive no .env/cofre, não no modelo |
| **Wiring** | `build_action_registry` injeta o HAClient (config/iot_credentials.json) nas actions iot_*; sem credenciais, degradam (ok=False → LLM) |
| **Casa de Conhecimento** | prompt v1.8.0: dado em TEMPO REAL sem fonte de ferramenta é DESCONHECIDO — 'não tenho esse dado agora' em vez de inventar; fatos incertos → admitir incerteza |
| **Permissões** | papel user ganha ha_weather + ha_lights (leitura do lar, sem ha_summary) |

### Cobertura

- tests/test_resposta_transparente.py: +5 (clima de cidade → ha_weather
  para qualquer papel, 'tempo em média' não é clima, luzes, resumo,
  credenciais negadas + negativo sem contexto).
- Suíte completa: **1994 passed, 16 skipped**.

## [1.7.2] — Anti-recusa com 2 retries para assunto externo + fallback honesto 🔁 (2026-09-28)

> **Política:** refinamento de comportamento sem capacidade nova = PATCH
> (`docs/VERSIONAMENTO.md` §1). O app não muda de conteúdo, mas o
> versionCode sobe para 2019 (> 2018) — a guarda de coerência exige
> `_APP_VERSION_CODE` = build do pubspec, e a reversionagem obriga o
> rebuild do APK (nunca anunciar build que não existe em site/).
> **Versões:** servidor `OD_VERSION=1.7.2` · app `1.7.2+2019` (versionCode 2019).

### Corrigido (2026-09-28)

- **fix(core): 2 retries para ASSUNTO EXTERNO (qualquer papel)** — o
  gemma às vezes recusa 2x seguidas (provado no ar: user viu recusa no
  1º turno sobre 'temperatura em presidente venceslau sp'); com assunto
  de mundo externo a recusa é SEMPRE alucinação, então o anti-recusa
  refaz até 2 vezes (3 gerações no total).
- **fix(core): fallback honesto e NÃO cacheável** — esgotados os
  retries, quem pergunta recebe '🤔 O modelo local não conseguiu
  responder agora. Tente perguntar de novo em instantes.' — NUNCA a
  recusa falsa do modelo; o aviso é banido do cache (prefixo em
  `_CACHE_BAN_PREFIXES`) para o próximo turno ir de novo ao modelo.
- **fix(core): admin em dado de sistema mantém 1 retry** — retries
  extras são exclusivos de assunto externo (prova por mutação).
- Helper novo `Orchestrator._resolve_refusal` centraliza retries+
  fallback para REST e WS; typo corrigido no caminho (unpack de None)
  pego pelo próprio teste novo antes do deploy.

### Cobertura

- tests/test_resposta_transparente.py: +5 (retry duplo responde, recusa
  tripla → aviso honesto sem mentira do modelo, aviso não cacheável,
  admin mantém 1 retry com contagem de chamadas, 2ª tentativa responde).
- Teste do teste: 4 mutações, TODAS detectadas e revertidas (attempts=1,
  fallback=None, aviso cacheável, admin com 2 retries).
- Suíte completa: **1989 passed, 16 skipped** (mqtt flaky passa isolado,
  precedente de 09-21).

## [1.7.1] — Temperatura do servidor como dado real + fim do bloqueio indevido de clima 🌡️ (2026-09-27)

> **Política:** correção com capacidade nova de leitura = PATCH com feature
> pontual (`docs/VERSIONAMENTO.md` §1 — precedente [1.6.1]: a intenção nova
> é caminho para dado existente; nenhuma API nova). O app não muda de
> conteúdo, mas o versionCode sobe para 2018 (> 2017) para manter a
> linhagem monotônica da auto-atualização.
> **Versões:** servidor `OD_VERSION=1.7.1` · app `1.7.1+2018` (versionCode 2018).

### Corrigido (2026-09-27)

- **fix(intents): clima/temperatura de CIDADE não é infraestrutura** —
  o dono perguntou "temperatuda em presidente venceslau sp" e recebeu 🔒
  (a vedação de infra capturava a palavra 'temperatura'). Novo
  `detect_external_intent`: assunto de clima/lugar = mundo externo,
  conversa livre para qualquer papel autenticado. 'tempo' só conta como
  clima com sujeito de clima — "quanto tempo de uptime" segue intacto.
- **fix(chat): "temperatura do servidor" responde com DADO REAL** —
  nova action `cpu_temp` (catálogo 58 → 59): `/sys/class/thermal` +
  fallback `/sys/class/hwmon` (stdlib, sem root), leitura do sensor mais
  quente + zonas. Intenção operacional nova em `core/intents.py`.
- **fix(permissions): `cpu_temp` liberada para o papel user** — leitura
  de temperatura não prejudica o sistema (diferente de IP/portas, que
  seguem vedados).
- **fix(core): anti-recusa do dono endurecido** — etiqueta de log
  `[NICKY][...]` detectada em QUALQUER posição (o gemma entregava
  '[NICKY][WARN] Não posso fornecer informações sobre o clima...' e o
  `startswith` deixava passar) + 7 padrões novos de recusa vistos no ar.
- **fix(personality): limites do papel user sem excesso** — o prompt
  agora veda APENAS o que pode PREJUDICAR O SISTEMA (IPs, portas, paths,
  credenciais, segredos); o resto é conversa livre — o modelo não tem
  mais desculpa para inventar restrição de clima/geografia/notícias.

### Cobertura

- tests/test_resposta_transparente.py: +8 (etiqueta embutida, clima do
  dono não é recusa, cpu_temp por typo real, cidade não é infra nem
  action, clima do user sem bloqueio, cpu_temp para user); +1 mutação
  corrigida no comentário (v1.7.2 → v1.7.1).
- Suíte completa: **1974 passed, 16 skipped** (+7 sobre a 1.7.0).

## [1.7.0] — AUTO-ATUALIZAÇÃO DO APP + SITE MAIS RÁPIDO + TRAVA DE INFRA PARA NÃO-DONO 🚀 (2026-09-26)

> **Política:** capacidade nova para o usuário final (o app se atualiza
> sozinho, sem site) = MINOR (`docs/VERSIONAMENTO.md` §1).
> **Versões:** servidor `OD_VERSION=1.7.0` · app `1.7.0+17` (versionCode 17).

### Adicionado (2026-09-26)

| Peça | Entrega |
|---|---|
| **GET /app/version** | Contrato público (sem auth) da auto-atualização: `{version, version_code, apk, size, sha256}` — hash calculado em streaming, sem carregar o binário de ~50 MB na memória |
| **App: OdUpdater** | Checa /app/version, compara o versionCode local (package_info_plus), baixa o APK com progresso, confere o SHA-256 ANTES de instalar (download corrompido nunca vira instalação) e dispara a instalação via FileProvider (canal nativo `com.omegadrakon.nicky/updater`) |
| **App: banner + Config** | Banner fino no topo ("Nova versão X disponível → Atualizar", com % do download) + seção Atualização nas Configurações (Verificar / Baixar e instalar) |
| **Android** | Permissão REQUEST_INSTALL_PACKAGES + FileProvider (cache-path em res/xml/file_paths.xml) + canal `installApk`/`cacheDir` no MainActivity.kt |

### Corrigido (2026-09-26)

| Sintoma | Causa | Correção |
|---|---|---|
| **SEGURANÇA: usuário de teste (papel user, não admin) recebia lista de IPs e portas abertas pelo chat** | Permissão `ip_address` estava na allowlist do papel user e o LLM entregava o dado mesmo com vedação no prompt | `ip_address` removida de `DEFAULT_ROLE_PERMISSIONS["user"]` (listening_ports nunca esteve lá) + guarda determinística Etapa 3.4 nos DOIS caminhos (`process` e `process_stream`): `detect_infra_intent` → resposta 🔒 fixa SEM LLM para user/anonymous; admin continua com dado real |
| **Site demorava para carregar às vezes** | `OmegaDrakon-debug.apk` de 155 MB em site/ + landing HTML sem cache | debug.apk movido para backups/apk-debug-20260926/; `_serve_site_file` agora manda ETag + `Cache-Control: max-age=60` no HTML com revalidação If-None-Match → 304 barato; APK continua no-store (download sempre completo) |

### Evidência (2026-09-26)

```
servidor: pytest tests/ → 1966 passed, 16 skipped (+6 em test_api.py: contrato
          de rotas 42, /app/version 200/sem auth, sha256 == binário de /site/,
          ETag + 304 da landing, no-store do APK)
app: flutter analyze → No issues found! · flutter test → 87 passed (2 skipped)
APK 1.7.0+17 (versionCode 17) publicado em site/OmegaDrakon.apk
```

### Nota

- A resposta transparente do dono (v1.6.0/1.6.1) NÃO mudou: admin segue com
  IP/portas reais pelo chat (ação + anti-recusa). O que entra em v1.7.0 é a
  trava para os DEMAIS papéis, com teste de regressão
  (TestGuardaInfraParaNaoDono em tests/test_resposta_transparente.py).

## [1.6.1] — IP e portas pela ACTION no chat + anti-recusa do dono 🔧 (2026-09-26)

> **Política:** correção com capacidade nova de leitura = PATCH com feature
> pontual (`docs/VERSIONAMENTO.md` §1 — a intenção nova é caminho para dado
> existente; nenhuma API nova).
> **Versões:** servidor `OD_VERSION=1.6.1` · app `1.6.1+16` (versionCode 16).

### Corrigido (2026-09-26)

- **fix(chat): "qual o ip do servidor" responde com DADO REAL** — o fast
  path de intenções não cobria IP/portas e a pergunta caía no LLM, que
  recusava ou alucinava etiqueta. Agora: `ip_address` e `listening_ports`
  na detecção (`core/intents.py`) — o dono pergunta e recebe o dado do
  sistema, sem passagem pelo modelo.
- **fix(actions): nova `listening_ports`** — portas TCP em escuta via
  `/proc/net/tcp{,6}` (IPv4+IPv6 decodificados, processo por inode) —
  catálogo 57 → 58.
- **fix(core): anti-recusa do dono** — `Orchestrator._refusal_reason`
  detecta recusas do modelo ("não posso fornecer", "sem acesso físico",
  etiquetas de log) na resposta ao ADMIN; refaz UMA geração com reforço;
  o papel user mantém a vedação de direito.
- **feat(auto_extension): allowlist para leitura de sistema** — `socket`,
  `os`, `platform`, `subprocess` entram na allowlist (comandos só de
  leitura: ss/df/ls/hostname/uname/uptime/id) — é a base para o chat
  gerar a ferramenta que traz o dado que faltou.

### Cobertura

- tests/test_resposta_transparente.py: +9 (anti-recusa, intenções
  IP/portas, negativos); suíte 1955 passed, 16 skipped.
- Teste do teste: 5 mutações, TODAS detectadas (prompt sem IPs; detector
  de recusa desligado; intent de IP desligada; done sem profile_name;
  listening_ports fora do catálogo).

## [1.6.0] — Resposta transparente: quem respondeu, hora e admin com acesso pleno 🔍 (2026-09-26)

> **Política:** feature nova compatível = MINOR (`docs/VERSIONAMENTO.md` §1).
> **Versões:** servidor `OD_VERSION=1.6.0` · app `1.6.0+15` (versionCode 15).

### Adicionado (2026-09-26)

- **feat(core,agents): system prompt por PAPEL** — `Orchestrator._resolve_system`
  reconstrói a identidade com o perfil pedido E o papel de quem fala: o dono
  (admin, autenticado pela credencial do servidor) tem acesso pleno aos dados
  do SISTEMA (IPs, portas, serviços, paths, logs — não esconde nada do
  operador da própria máquina); o papel user mantém a vedação de
  infraestrutura. Antes o prompt era estático e a vedação genérica travava
  até o dono.
- **feat(agents): `profile_display_name()`** — nome canônico da Plêiade
  ('regulus' → 'Regulus — O Conselheiro'); `/profiles` expõe `display_name`;
  chave desconhecida devolve a própria chave (nunca atribui ao perfil
  padrão).
- **feat(core): `profile_name` na resposta** — `to_dict()` (REST) e TODOS os
  frames `done` do streaming trazem quem respondeu.
- **feat(app): bolha com QUEM respondeu + hora** — cabeçalho da bolha do OD
  com ícone e nome (Nicky Virthy, Regulus, Nyx…, 'cache', 'ação: X') e a
  hora em toda mensagem (usuário e assistente).
- **feat(app): chips de perfil com o nome canônico** — Regulus, Nyx, Luma,
  Vox, Athenae, Nexus (antes mostrava só o cargo: 'Conselheiro', 'Guardiã').

### Cobertura

- Servidor: tests/test_resposta_transparente.py (NOVO, 10 testes); suíte
  1945 passed, 16 skipped.
- App: +4 testes de widget (nome+hora, cache, hora no usuário, selo);
  flutter analyze 0 issues · flutter test 87 passed, 2 skipped.

## [1.5.0] — App sem configuração de URL: conexão por localização + conta do site 📱 (2026-09-26)

> **Política:** feature nova compatível = MINOR (`docs/VERSIONAMENTO.md` §1).
> **Versões:** servidor `OD_VERSION=1.5.0` · app `1.5.0+14` (versionCode 14).

### Adicionado (2026-09-26 — app Flutter)

- **feat(app): conexão automática pela LOCALIZAÇÃO da rede** —
  `OdApi.pickBestUrl()` sonda a rede local (Tailscale, timeout de 4s) e,
  sem rota, usa a externa (Funnel/TLS); a que responder vira primária e a
  escolha é persistida. O usuário nunca digita URL.
- **feat(app): URLs ocultas** — removidas da tela principal; ficam dentro
  de "Avançado", atrás do switch "Mostrar URLs" (padrão do sistema: ocultas).
- **feat(app): seção Conta nas Configurações** — login com o MESMO
  nome/senha do site (POST /auth/login) direto do app; logado, mostra o
  usuário com botão Sair (logout mata a sessão no servidor).

### Cobertura

- flutter analyze 0 issues; flutter test 84 passed, 2 skipped (+3: URLs
  ocultas no Avançado, login da conta na Configurações, logado com Sair).
- Suíte do servidor verda (guardas de versão) após o bump 1.5.0.

## [1.4.0] — Plêiade pelo domínio, cache saneado e poda admin 🧹 (2026-09-26)

> **Política:** feature nova compatível = MINOR (`docs/VERSIONAMENTO.md` §1).
> **Versões:** servidor `OD_VERSION=1.4.0` · app `1.4.0+13` (versionCode 13).

### Adicionado (2026-09-26)

- **feat(api):** `POST /admin/cache/prune` — saneamento do cache LLM pelo
  admin/dono: `dry_run` lista as candidatas sem tocar nos dados; varredura
  remove entradas de FALHA (etiqueta de log `[NICKY][CRIT]`/`[WARN]`/`[INFO]`,
  respostas vazias ou truncadas no meio da frase — as "respostas de cache sem
  nexo" que renasciam a cada repetição); `keys` faz poda cirúrgica por chave.
- **feat(api,history):** `DELETE /history/{user_id}/messages/{message_id}` —
  remoção de UMA mensagem pela PK (`Message.id` exposto; `delete_message` na
  ConversationHistory), com dono conferido pelo mesmo gate do `/history` e
  404 quando a mensagem não é do balde informado.

### Corrigido (2026-09-26)

- **fix(cache):** respostas de FALHA não entram mais no cache
  (`_cacheable`/`cache_failure_reason` no Orchestrator) — etiqueta de log,
  vazia ou truncada não é conhecimento; cacheada, a mesma pergunta devolvia
  a falha para sempre.
- **fix(profiles):** o perfil `auto` é detectado pelo DOMÍNIO do texto em
  TODOS os transportes (`agents/profiles.resolve_auto` compartilhada) — REST
  e WS forçavam `guardian` e uma pergunta de religião/mitologia respondia
  como Guardian em vez de Nyx.
- **fix(agents):** cânone da Plêiade alinhado (Personagens.md) — Nyx é a
  Guardiã do Limiar (religião, mitologia, esoterismo) e Regulus é o
  Conselheiro (história, direito, ética); antes estavam trocados em
  IDENTITY.md, SOUL.md e personality.py.

### Cobertura

- Suíte: 1932 passed, 16 skipped (+13 em tests/test_api.py: auto por domínio,
  sanidade de cache, remoção de mensagem individual, prune do cache).
- Sandbox: auth_sandbox.py 57 OK, 0 FALHA (REST + WS + Telegram reais).

## [1.3.0] — Papéis, histórico vivo e painéis 🎚️ (2026-09-19 a 2026-09-26 · saneamento de versão 2026-09-26)

> **Política (2026-09-26):** o projeto aderiu ao Versionamento Semântico 2.0.0
> — ver `docs/VERSIONAMENTO.md` e a regra 12 de `iniciar/RULES.md`. Feature
> nova compatível sobe o MINOR; fix sobe o PATCH; o sufixo `+N` do app é
> versionCode (metadado de build) e NUNCA substitui a versão.
>
> **Saneamento:** até aqui o servidor rodou `OD_VERSION=1.2.0` (de 09-12)
> enquanto o app empilhava `1.2.8+8…+11` — o `+N` fazia o papel que era do
> X.Y.Z. A release **1.3.0** contempla as entregas de 2026-09-19 a 2026-09-26
> (autenticação de usuários, LoginGuard, dono do histórico, identidade pela
> credencial, papéis, vínculo Telegram, anônimo, histórico visível/paginado
> no app e no chat, painéis /dashboard e /admin, rotas terminais no
> histórico). As entradas detalhadas permanecem na seção [1.2.0] abaixo por
> ordem cronológica de registro; **a partir daqui, entradas novas nascem na
> seção da release vigente.**
>
> **Versões:** servidor `OD_VERSION=1.3.0` · app `1.3.0+12` (versionCode 12).

## [1.2.0] — App Android 📱 (2026-09-08 · correções em 2026-09-12, 2026-09-14, 2026-09-15, 2026-09-18, 2026-09-21, 2026-09-22, 2026-09-23, 2026-09-24, 2026-09-25 e 2026-09-26)

> **Nota (2026-09-26):** as entregas datadas de 2026-09-19 a 2026-09-26
> abaixo pertencem à release **[1.3.0]** (saneamento de versão —
> `docs/VERSIONAMENTO.md` §6); permanecem aqui por ordem cronológica de
> registro.

### Adicionado (2026-09-26) — painéis: dashboard do usuário e backend do admin 🛡️

- **/dashboard (painel do usuário)** — a página antes morta virou painel
  autenticado: uso da própria conta (mensagens, conversas, última atividade
  via `/history/me/stats`), últimas 20 mensagens do histórico e gestão da
  conta — troca de SENHA (exigindo a atual) e ROTAÇÃO da própria API key
  (via `/account/*`, novos endpoints). Sem login, o navegador é mandado
  para /chat. O menu 👤 do chat ganhou o atalho "📊 Meu painel".
- **/admin (painel do dono, papel admin)** — contas (lista com mensagens,
  sessões ativas, criação e marcação de dono), baldes legados sem conta,
  saúde do sistema (/health, /supervision, /dashboard/stats) e AÇÕES:
  reset de senha e remoção de conta (`/admin/users/*`, novos endpoints).
  A conta do DONO não é alvo (`dono_nao_removivel`) — protege a
  OD_API_KEY de operador. Remover conta NÃO apaga o histórico (balde é
  separado; limpar histórico continua sendo ação própria do admin).
- **Backend (integrations/api/)** — `auth.py`: `UserStore.change_password`
  (exige a senha atual), `delete_user` (mata sessões + vínculo do
  Telegram) e `count_sessions` (sessões válidas). `server.py`: 6 rotas
  novas (33 → 39), gate `_require_admin` (403 para não-admin) e as duas
  páginas embutidas.
- **Segurança** — troca de senha encerra TODAS as sessões da conta (token
  roubado não sobrevive); reset pelo admin idem; sem credencial tudo
  devolve 401; usuário comum em rota admin devolve 403 com log de aviso.
- **Provas** — suíte 1913 passed, 16 skipped (+14: 9 admin, 5 conta);
  4 mutações detectadas e revertidas (papel user→admin, troca sem senha
  atual, dono removível, reset sem fechar sessões); prova viva 7/7 no
  sistema real (shells 200, dados 401 sem credencial, 403 para usuário
  comum, reset+login+remoção de conta de prova, dono protegido, 404
  para conta inexistente, 0 erros no journal).
- **Lição (regra de guarda estendida)** — a página /admin pegou no AR um
  bug de escape JS nos `onclick` gerados (o `node --check` do deploy
  provou). Contrato endurecido: as DUAS páginas novas agora têm a mesma
  guarda `node --check` do /chat (`test_painel_pages_js_compiles`), e os
  onclick inline foram trocados por `data-*` + addEventListener.

### Corrigido (2026-09-25) — histórico do chat não atualizava ao trocar de usuário 🔄

- **Sintoma** — no chat web, ao trocar de usuário ou no primeiro acesso,
  as conversas não atualizavam (ou apareciam as de outra conta / nada).
- **Causa** — 3 defeitos no cliente (página /chat): a página era servida
  SEM `Cache-Control: no-store` (navegador podia rodar JS velho do
  cache); o histórico era buscado por `/history/<user_id do navegador>`
  — defasado na troca ou `web` no modo API key — em vez do
  `/history/me`, que o servidor resolve pela credencial; e o filtro de
  perfil do dropdown persistia entre usuários (perfil com 0 mensagens
  fazia o histórico parecer vazio).
- **Correção** — `integrations/api/server.py`: `_html()` manda
  `Cache-Control: no-store`; `loadHistory`/`loadOlder`/Limpar usam
  `/history/me` e o badge do cabeçalho é corrigido com o `user_id` DA
  RESPOSTA; novo `resetProfileFilter()` volta o dropdown para `auto` nos
  3 pontos de entrada (login, auto-login do registro, API key).
- **Verificação** — suíte 1899 passed, 16 skipped; 3 mutações detectadas
  e revertidas; a guarda `node --check` do teste pegou (antes do deploy)
  um novo bug de sintaxe introduzido na edição.

### Corrigido (2026-09-24) — interações de rota terminal sem LLM sumiam do histórico 🧠

- **Sintoma** — o usuário teste conversava no chat web e a conversa não
  aparecia no histórico: as mensagens repetidas ("oi" e afins) caíam na rota
  `cache` do orquestrador, que respondia ANTES da etapa de persistência — o
  turno nunca chegava ao `ConversationHistory`. Mesmo vale para
  `datetime`/`quick_response`/`action_intent`, no REST e no WS.
- **Correção** — `core/orchestrator.py`: novo `_record_terminal()` registra o
  turno nas rotas terminais (_datetime/quick/intent/cache) também no
  `process_stream`; `PERSISTED_ROUTES` passa a incluí-las. `persist=False`
  (anônimo) segue SEM rastro em todas as rotas; rate limit e indisponível
  não registram (não houve resposta).
- **Prova viva** — login do usuário `teste` + 3 mensagens ("oi" → cache,
  nova → llm, "oi" de novo → cache): as 3 interações aparecem no
  `GET /history/me` (6 msgs) e o journal mostra `Interaction recorded` antes
de cada `Message processed | route=cache`. Suíte 1899 passed, 16 skipped;
  4 mutações detectadas.

### Adicionado (2026-09-23) — chat web: menu da conta (Limpar + Sair), paginação e agrupamento do histórico 🖥️

> Polimento do chat do site: gestão de conta no próprio nome do usuário e
> histórico organizado no tempo, carregando as conversas antigas sob demanda.

- **Menu da conta** — o badge **👤 nome** virou botão: clicar abre dropdown com
  **🧹 Limpar conversa** (`DELETE /history/me` com dupla confirmação — apaga
  TODA a conversa da conta no servidor, zera a tela e a paginação) e
  **🚪 Sair** (`POST /auth/logout` mata a sessão no servidor + limpeza local +
  fecha o WS + volta ao gate). Menu fecha com clique fora ou Esc; anônimo não
  tem menu. O botão solto "Sair" do header foi removido.
- **Paginação por cursor** — `GET /history/{user_id}?before=` devolve a página
  anterior: no banco o cursor é a PK `id` (`has_more`/`oldest_id` encadeiam as
  páginas; `before` inválido → 400 `before_invalido`); em memória/JSON (sem id
  estável) o cursor é offset negativo. `history.get_messages_page()` nova em
  `memory/history.py`.
- **Chat web carrega antigas ao rolar o topo** — pill "↑ Carregar conversas
  anteriores" (clique ou scroll ao topo com folga de 60px) faz prepend
  preservando a posição da leitura, re-agrupa os separadores de dia e mostra
  "Início da conversa" quando acaba.
- **Histórico agrupado por dia com hora discreta** — separador `Hoje`/`Ontem`/
  `dd MMM` (pt-BR) quando a data muda e `HH:MM` no canto de cada bolha do
  histórico (respostas do OD incluem o LLM usado no meta); conversa ao vivo
  intocada.
- **Histórico abre no fim** — a lista carregada rola uma única vez até a
  mensagem mais recente (scroll pós-pintura via duplo `requestAnimationFrame`).

### Corrigido (2026-09-23) — chat web 🔧

- **WebSocket negado para quem logava** — o frame `auth` da página `/chat` só
  enviava `api_key`: com sessão Bearer o servidor sempre respondia
  `api_key_invalida` (close 4001) e o streaming caía no REST silenciosamente.
  A página agora envia `token` no frame (o servidor já aceitava desde
  `d8374e2`).
- **Layout fixo** — o `#chat` crescia com o histórico e empurrava header e
  caixa de digitação para fora da tela. Agora ocupa o espaço restante
  (`flex: 1` + `min-height: 0`) e o scroll fica dentro da lista: header e
  composer fixos por estrutura.
- **Nome do usuário visível** — badge **👤 username** no cabeçalho (login,
  registro e auto-login; limpo no Sair).
- **hist-note** — aviso visível quando o histórico não carrega (status HTTP ou
  falha de rede) ou quando a conta não tem mensagens, em vez de falhar calado.

- **Testes (2026-09-23):** suíte 1896 passed, 16 skipped (+9: fluxo do site —
  registra → conversa → histórico → sair com sessão morta; limpar zera o
  balde; paginação encadeando páginas; asserts do HTML da página `/chat`).
- **Deploys provados no ar** — GET /history (PID 235324), Sair+WS (239235),
  layout+badge (241843), agrupamento (243498), scroll no fim (245159),
  paginação (252797) e menu da conta (255429); todos com 0 erros no journal.

### Adicionado (2026-09-22) — histórico visível: GET /history/{user_id} + carregamento no app e chat web (APK 1.2.8+11) 💬

> As mensagens ficavam no PostgreSQL e alimentavam a memória da IA, mas a
> interface iniciava vazia. Agora a conversa aparece de onde parou no app,
> no chat web e (via API) em qualquer cliente da conta.

- **`GET /history/{user_id}`** (`integrations/api/server.py`, `memory/history.py`)
  — lista as mensagens recentes da conta com `?limit=N` (1–200, default 50) e
  `?profile=` (default `auto` = todos). Passa pela checagem de dono
  (`_check_owner`: usuário só lê o próprio; OD_API_KEY é admin) e pelo 404 de
  histórico inexistente. `history.get_messages()` consulta direto do banco
  (ordem cronológica, fallback em memória sem database); suporta `user_id=me`
  (resolve para a própria conta).
- **Chat web** — a página `/chat` carrega o histórico ao entrar (`loadHistory()`,
  best-effort: falha não impede a conversa).
- **App Flutter** — `OdApi.getHistory()` (`od_api.dart`, best-effort com lista
  vazia em erro) e `ChatScreen._loadHistory()` no `initState` (`chat_screen.dart`):
  ao abrir a conversa, as últimas 50 mensagens da conta aparecem na tela.
  Sem credencial não chama a API.
- **Testes:** suíte 1887 passed, 16 skipped (+5 no backend: GET lista, dono,
  `me`); flutter analyze 0 issues; flutter test 81 passed, 2 skipped (+4:
  getHistory com Bearer, sem credencial, best-effort e carregamento no widget).
- **Versão bump para 1.2.8+11** em `app/pubspec.yaml`; APKs 52.410.843 B (full)
  e 18.715.654 B (arm64) publicados em `site/` (versionCode 11 conferido via
  aapt2).

### Adicionado (2026-09-22) — tela de login/registro no app Flutter + APK 1.2.8+10 📱

> Fase 2 da unificação de contas: o app agora suporta autenticação por conta
> (`POST /auth/login` e `/auth/register`), enviando token `Bearer` no REST e no
> frame `auth` do WebSocket. A mesma conta continua a conversa no app, no
> navegador e no Telegram.

- **Tela de entrada (`LoginScreen`)** em `app/lib/screens/login_screen.dart` — login
  e registro com validação de campos, mensagens de erro da API e alternância
  suave. Inclui botão de "Modo avançado (API key)" para quem usa credencial direta.
- **Sessão persistida no `OdApi`** (`app/lib/services/od_api.dart`) — métodos
  `login()`, `register()`, `logout()` e `setToken()`. Com token ativo, o app
  adiciona `Authorization: Bearer <token>` nas requisições HTTP (com precedência
  sobre `X-API-Key`). Credenciais salvas em SharedPreferences (`od_session_token`,
  `od_username`).
- **WebSocket por token de conta** (`app/lib/services/od_ws.dart`) — frame `auth`
  transmite `'token': api.token` quando logado, associando o stream diretamente
  à conta do usuário no core.
- **Bootstrap no `OdApp`** (`app/lib/main.dart`) — `OdRoot` verifica se há
  credencial salva (`hasCredential`): abre a `LoginScreen` caso não haja, ou vai
  direto ao chat principal (`OdHome`).
- **Versão bump para 1.2.8+10** em `app/pubspec.yaml`.
- **Testes:** `app/test/od_api_test.dart` com 5 novos testes de login/registro/sessão
  e `app/test/widget_test.dart` atualizado com smoke test do login. Total: 77 passed,
  2 skipped (`flutter test`), `flutter analyze` 0 issues.
- **Build APK:** `site/OmegaDrakon.apk` (52.394.459 B) e `site/OmegaDrakon-arm64.apk`
  (18.715.654 B), `versionCode='10' versionName='1.2.8'`.

### Adicionado (2026-09-22) — papéis: dono, conta comum e anônimo 🎚️

> Modelo pedido pelo usuário: **cada pessoa com a própria conta, a mesma em
> qualquer plataforma**; o dono confirmado pela `OD_API_KEY` tem privilégio
> máximo (com confirmação); o chat aceita quem só quer conversar, sem conta e
> sem comando. Esta entrada cobre o **núcleo de privilégio**, o **vínculo do
> Telegram** e o **modo anônimo**. A tela de login do app é a fase seguinte.

- **`OD_OWNER_USERNAME` (default `alex`)** — a `OD_API_KEY` é a chave do
  DONO. Com a conta configurada, a chave **assume a conta**: o histórico do
  dono fica contínuo entre app, `curl` e chat (antes a chave não tinha conta e
  caía no `user_id` do corpo), o `/auth/me` responde `via="server"` +
  `role="admin"` e a conta do dono lê/apaga **qualquer** histórico (admin).
  Entrando por sessão ou API key própria, a conta do dono também é admin.
- **`POST /executa` passa a usar o papel de quem chama.** Antes o handler
  mandava `role="admin"` fixo, então **qualquer** credencial válida —
  inclusive a de um usuário comum — rodava ação destrutiva. Agora:
  - nível 1 (admin) e nível 2 (destrutivo) → **só o dono** (403
    `acao_restrita_ao_dono` antes de executar);
  - nível 2 continua exigindo `confirm=true` (422 sem ele);
  - conta comum roda só o que o papel `user` permite.
- **Papel `user` no Permission Engine** (`core/security/permissions.py`) —
  lista **explícita** com os nomes REAIS das actions (leitura de sistema,
  processos, serviços, docker, arquivos e git + introspecção), deixando de
  fora `system_env` (segredos), `filesystem_read` (ler qualquer arquivo),
  `database_*` e `network_hosts`. **Lacuna registrada:** os padrões com ponto
  do papel `agent` ("filesystem.read") não casam com o ActionRegistry real
  ("filesystem_read"), então o `agent` efetivamente nega tudo — pré-existente,
  fora do escopo desta fase.
- **O papel flui até o fast path de intenções** (`Orchestrator.process` e
  `process_stream` ganharam `role`): REST passa o papel da credencial, o
  WebSocket o da sessão/API key e o bot o do chat admin. O papel
  `anonymous` **não aciona action nenhuma**. `process` também aceita
  `persist=False` (não grava cache nem histórico) — base do modo anônimo.
- **Telegram: `/entrar <usuário> <senha>` e `/sair`.** O vínculo vive no
  banco (tabela `telegram_links`, `UserStore.link_telegram` /
  `telegram_username` / `unlink_telegram`, com `verify_credentials` sem abrir
  sessão). Com o chat vinculado, o histórico do Telegram passa a ser o da
  conta — **a conversa continua de onde parou no chat ou no app**; sem vínculo
  (ou após `/sair`), cada chat segue no próprio balde. O vínculo tem
  prioridade sobre o `OD_ACCOUNT_ALIASES`.
- **Conversa anônima no chat web.** Novo `POST /anon/message` (público —
  `AUTH_EXEMPT_PATHS`, responde mesmo com `auth_all`) + botão "Entrar como
  anônimo" na página: o contexto da conversa vem do **navegador**
  (`history` no corpo → `Orchestrator.process(extra_history=...)`), o papel é
  `anonymous` (não aciona action nenhuma) e `persist=False` — **nada é
  gravado**: sem histórico e sem cache no banco. Rate limit por IP continua.
- **Testes:** `tests/test_auth.py` +6 (dono assume a conta, conta comum é
  `"user"`, dono lê qualquer histórico, `/executa` por papel, destrutiva ainda
  pede confirmação); `tests/test_websocket.py` +1 (papel chega ao
  orchestrator); `tests/test_telegram.py` +5 (`/entrar`, senha errada, `/sair`,
  vínculo acima do alias, sem UserStore); `tests/test_api.py` +3 e
  `tests/test_orchestrator.py` +3 (endpoint anônimo, nada gravado, contexto do
  cliente, anônimo não aciona action). **Suíte:** **1887 passed, 16 skipped**.
- **Sandbox (regra 12):** `sandbox_agent/auth_sandbox.py` ganhou o 6º cenário
  (papéis + `/entrar` + anônimo, com socket real) → **57/57 OK** (era 44).

### Adicionado (2026-09-22) — o histórico do app e do Telegram vai para a conta 🔗

- **`core/identity.py` (novo)** — resolvedor do DONO de identificadores
  legados de transporte. `OD_ACCOUNT_ALIASES` (ex.:
  `app=alex,660518870=alex,web=alex`) aponta o `user_id: "app"` fixo do app,
  o id numérico do chat do Telegram e o `web` do chat em modo avançado para a
  conta: a conversa dos três cai no mesmo histórico/cache da conta, **sem
  mudança nenhuma no cliente**. `parse_aliases` ignora entradas malformadas
  (uma env torta não derruba a identidade) e `resolve_account` casa sem
  diferenciar maiúsculas, devolvendo o id original quando não há alias (mapa
  vazio = comportamento antigo).
- **REST, WebSocket e Telegram** — os três resolvem o MESMO mapa
  (`APIConfig.account_aliases`, `WebSocketServer(account_aliases=...)`,
  `TelegramBot(account_aliases=...)`). O alias só vale no caminho SEM usuário
  (`OD_API_KEY`): credencial de usuário (sessão `Bearer` ou API key `od_...`)
  continua mandando na identidade e o alias é ignorado. No bot, `/historico`
  e `/limpar` leem/limpam o mesmo balde da conta.
- **`runtime/launcher.py`** — monta o mapa de `OD_ACCOUNT_ALIASES` em um único
  lugar e injeta no REST, no WS e no bot.
- **Baldes órfãos migrados:** `app` (44) + `660518870` (20, Telegram) +
  `web` (6, chat em modo avançado) → `alex` (**28 → 98** mensagens), via
  `runtime.migrate_history_owner --de app,660518870,web`. O total da tabela
  não mudou (**102** antes e depois) e a API no ar confirma pelo
  `/history/alex/stats`. Snapshot:
  `backups/history-owner-20260922-020027.bak`. Ficaram de fora, de propósito,
  só os baldes `deploy-check*` (4) — mensagens sintéticas de prova de deploy.
- **Testes:** `tests/test_identity.py` (**novo, 12**) e o alias exercitado no
  REST (`tests/test_auth.py`, +2), no WS (`tests/test_websocket.py`, +1) e no
  bot (`tests/test_telegram.py`, +2). **Teste do teste (4 mutações, todas
  revertidas):** `resolve_account` devolvendo sempre o id bruto (6 falhas) e o
  alias removido do REST (1), do WS (1) e do bot (1). **Suíte:** **1870
  passed, 16 skipped**.
- **Sandbox (regra 12):** `sandbox_agent/auth_sandbox.py` ganhou o 5º cenário
  (REST + WebSocket + Telegram com protocolo real, mais os negativos) →
  **44/44 OK** (era 36).

### Adicionado

- **App Flutter** em `app/` — telas de chat, ações (catálogo de 57 actions
  via `GET /actions` + `POST /executa`), status (`/health` + manifesto de
  capacidades) e configuração; auth por `OD_API_KEY` no header `X-API-Key`.
- **Push FCM** — `firebase_core` + `firebase_messaging`, com documentação em
  `docs/FIREBASE_SETUP.md`.
- **Compatibilidade de API para o app** — `POST /message` aceita
  `{"message": ...}` além do payload do bot (`tests/test_api.py`).
- **APK release publicado na landing** — `site/OmegaDrakon.apk`
  (build via `app/build_apk.sh`, Flutter 3.47.2 / JDK 17 / Android SDK 36).

### Infraestrutura

- Fonte de verdade da versão do sistema: `OD_VERSION` no `.env`
  (`core/capabilities.py` agora resolve `os.environ` → `OD_VERSION` do `.env`
  → fallback congelado `1.2.0`, o que faz o valor chegar ao manifesto, à API
  e ao bot mesmo em entrypoints que não usam o carregador do launcher).
- `app/pubspec.yaml` alinhado para `1.2.0+3` (antes `1.0.0+1`, o que fazia o
  APK reportar `versionName 1.0.0` enquanto a landing anunciava v1.2.0).
- `docs/CHANGELOG.md` criado; seções v1.0.0/v1.1.0/v1.2.0 do
  `docs/README_VERSAO.md` reconstruídas retroativamente.

### Testes

- `app/`: **36 testes** Flutter (`flutter test`) + `flutter analyze` limpo
  (2026-09-12; 27 na entrega original).
- `tests/` (servidor): **1610 passed, 16 skipped** (suíte completa, auditoria
  de 2026-09-12); marco da v1.0.0 registrado com **1594 passed**.

### Corrigido (2026-09-12)

- **Tela Status quebrava com o manifesto real** — `status_screen.dart` fazia
  `_capabilities['system'] as Map<String, dynamic>?`, mas o servidor devolve
  `"system": "Omega Drakon"` (string), com `version`, `counts` e `runtime` no
  topo do manifesto. O cast estourava `_TypeError: type 'String' is not a
  subtype of type 'Map<String, dynamic>?'` e derrubava a seção "Sistema" da
  aba Status. A leitura agora usa `is` + fallback `'?'` (sem cast) e o card
  mostra versão, nº de modos de runtime, capacidades e actions.
- Publicação: commit **`e2f4960`** — _feat(app): publica o código do app v1.2.0
  e corrige a aba Status_ — em `origin/master` (`f42e5c5..e2f4960`). O commit
  levou junto o código do app que gerou o APK (push FCM, resiliência de rede,
  telas ligadas a `/actions` e `/executa`, projeto Android e testes), que
  nunca tinha sido commitado.

- **Contrato testado com payload real** —
  `app/test/fixtures/capabilities_manifest.json` (manifesto capturado do
  servidor em produção) + teste de regressão em `app/test/widget_test.dart`.
  O mock anterior usava um `system` aninhado que o servidor nunca devolveu —
  o teste passava enquanto a tela quebrava no celular.

### APK republicado (2026-09-12)

Dois builds no mesmo dia:

| Build | `versionName` / `versionCode` | sha256 (full) |
|---|---|---|
| 1º — alinhamento de versão | `1.2.0` / 1003·2003·4003 | `3b800c87…d978ff` |
| 2º — com a correção da tela Status | `1.2.0` / **1004·2004·4004** | `6d3c73a5…b616ade` |

- Publicados em `site/OmegaDrakon.apk` (51.9 MB) e
  `site/OmegaDrakon-arm64.apk` (18.5 MB), com sha256 conferido origem↔site
  e download servido pela API (`GET /site/OmegaDrakon.apk`) verificado.
- O build number subiu para `+4` de propósito: com o mesmo `versionCode`
  (1003) o Android recusaria instalar por cima do APK anterior.
- APKs antigos preservados: `backups/apk-v1.0.0/` e
  `backups/apk-v1.2.0-1003/`.
- `OD_VERSION=1.2.0` gravado no `.env`.

### Publicação

- Commit **`ffeab4f`** — _fix(version): alinha OD_VERSION, pubspec e docs na
  v1.2.0_ — publicado em `origin/master` (`3768bcb..ffeab4f`).
- Binários fora do repo por decisão desta entrega: `site/*.apk`,
  `backups/apk-*/` e `.od_repair_backups/` no `.gitignore`.

### Adicionado — push FCM de ponta a ponta (2026-09-12)

Fecha a pendência do push da v1.2.0: até aqui o app só **recebia** (console),
agora o **OD também envia** para o aparelho.

- **`core/push.py`** — `DeviceRegistry` (tokens em `data/push_devices.json`,
  upsert por token, escrita atômica, tolerante a arquivo corrompido),
  `FcmSender` (FCM HTTP v1: OAuth2 da service account + `messages:send`) e
  `PushService` (fachada `notify`/`sink`/`status`, tokens mascarados em
  log/API). Tokens que o FCM declara mortos (`UNREGISTERED`, `INVALID_ARGUMENT`,
  `SENDER_ID_MISMATCH`) saem do registro sozinhos.
- **API** — `POST /push/register`, `POST /push/unregister`, `POST /push/test` e
  `GET /push/devices` (todos com `X-API-Key`); tabela de rotas 22 → **26**.
- **Runtime** — `build_push()` no launcher; a API e o `ProactiveNotifier`
  recebem o serviço, então os alertas proativos (LLM offline, disco, restart)
  também saem como notificação no celular.
- **App** — `OdApi.registerPushToken`/`unregisterPushToken`,
  `PushService.attach(api)` (registra o token no boot, ao salvar as
  Configurações e a cada rotação de token) e `main.dart` ligando os dois.
- **Dependência nova:** `google-auth` (OAuth2/JWT RS256 da service account) —
  justificativa no `requirements.txt`; o HTTP continua em urllib do stdlib
  (adaptador `UrllibRequest`), então não entrou cliente HTTP novo.
- **Dormente por padrão:** sem a credencial (`OD_FCM_CREDENTIALS` ou
  `config/firebase-service-account.json`) o serviço sobe desligado e
  `/push/test` responde **503** — o registro de tokens continua funcionando.
  Ver `docs/FIREBASE_SETUP.md` (passos 6 e 7).

### Validado no aparelho (2026-09-12) ✅

Redmi Note 14 (`redmi-note-14-1`, Tailscale `100.80.224.73`) com o APK
`1.2.0+4`: **Chat, Ações e Status funcionando sem erro**. Evidência do journal
do `od-core` (processo novo, pós-restart de 11:14:52):

```
11:25:58  Message processed | route=cache | user=app | profile=guardian
          llm=- | latency_ms=32.325          → chat do app respondido
11:27:58  Security decision | action=cpu_info | allowed=True | session_id=api:app
          Action executed    | action=cpu_info | role=admin | duration_ms=5.608
                                            → action real executada pelo app
sem "[NICKY][WARN] API erro" depois do restart → zero 4xx vindos do app
```

A tela Status e a instalação do APK não deixam rastro no servidor (GETs não são
registrados e `/site` não tem log de acesso) — essas partes se apoiam no relato
do usuário.

### Corrigido (2026-09-14) — achados do journal do `od-core`

Dois achados levantados no journal, cada um com teste de regressão novo:

- **`face.presence` ia para dead letter a cada evento** —
  `runtime/launcher.py::_run_vision_forever` registrava o handler como
  `on_change(data)` e chamava `data.get("confirmed")`, mas o Event Bus entrega
  o **`Event`** (o payload vive em `event.data`, como no resto do projeto) →
  `AttributeError: 'Event' object has no attribute 'get'` em todas as 3
  tentativas, seguido de _dead letter_ (09-14: 09:29:55, 09:31:17, 10:27:10 e
  10:27:39). O handler passou a ler `event.data` com guarda de tipo — o bus
  grava apenas o **nome** da exceção no journal, por isso o motivo só apareceu
  na leitura do código.
  - Regressão: `tests/test_launcher_vision.py` (novo, **4 testes**, bus real +
    detector fake) — com o handler anterior restaurado, os 4 falham
    reproduzindo as linhas exatas do journal.
  - Prova em produção: depois do restart de 13:24:40, o `face.presence` real
    das 13:25:09 (`Event published | topic=face.presence | subscribers=1`)
    **não** gerou nenhum `Handler error` nem `dead letter`.
- **Snapshots do SelfRepair cresciam sem limite** — `core/self_repair.py`
  criava um `.bak` por tentativa mesmo sem mudança no arquivo: um arquivo
  doente no escopo do `RecoveryLoop` (ciclo de 5 min) rendeu **557 snapshots,
  8,8 MB** em ~2 dias. Agora `_take_snapshot` faz **dedup** (bytes idênticos
  reutilizam o snapshot existente) e **retenção** por arquivo
  (`max_snapshots_per_file`, default `5`) via `_prune_snapshots`;
  `_next_snapshot_path` evita a colisão de nome dentro do mesmo segundo (antes
  o snapshot anterior era sobrescrito).
  - Regressão: `TestSnapshotDedupERetencao` em `tests/test_self_repair.py`
    (**4 testes**) — com o comportamento anterior restaurado, os 4 falham.
  - Limpeza retroativa: dos 557 snapshots (3 conteúdos distintos), 552 saíram
    e os 5 mais novos ficaram → `8,8 MB → 116 KB`.
- `od-core` reiniciado às 13:24:40 para subir as correções; `/health` ok (8
  checks) e o `RecoveryLoop` rodando sem detecções.

### Ativado (2026-09-14) — push FCM em produção 🔔

A service account chegou e o envio saiu do modo dormente **sem nenhuma mudança
de código** (o que faltava era só a credencial):

- Credencial instalada em `config/firebase-service-account.json`
  (`chmod 600`), coberta pelo `.gitignore` — nada de credencial no repositório.
- **Validação antes do restart**: o `FcmSender` do próprio `core/push.py`
  (`available=True`, `project_id=nicky-e4f99`) emitiu um **access token OAuth2
  real** — a chave é válida e tem permissão no FCM (nenhuma mensagem enviada
  nessa etapa).
- `od-core` reiniciado às 14:06:53: `Push FCM inicializado | enabled=True |
  motivo= | credencial=config/firebase-service-account.json | dispositivos=1`
  (todos os restarts desde 13/09 registravam `enabled=False |
  credencial_ausente`).
- **Teste de ponta a ponta**: `POST /push/test` → **HTTP 200**
  `{ok:true, sent:1, failed:0, skipped:0, errors:[]}`; journal
  `Push enviado | enviados=1 | falhas=0 | titulo=OmegaDrakon`; e o aparelho
  registrado (Redmi Note 14) foi para `sent=1, failed=0` no
  `GET /push/devices`. O token foi registrado pelo **próprio app**, sem ação
  manual no servidor.
- Nenhuma variável nova no `.env`: sem `OD_PUSH_ENABLED` o default é "ligado
  se houver credencial" (`PushService.enabled` cai em `sender.available`).

> ⚠️ **Achado de segurança desta rodada:** um dos dumps de tela guardados na
> pasta local `000/` (fora do git) contém a **chave legada do servidor FCM**
> (API legada, descontinuada em 2024) e um par de chaves de push da Web. A
> chave legada **não** é usada pelo OD (o envio é HTTP v1 com service account) e
> deve ser excluída no console — *Cloud Messaging → chave do servidor*.

### Corrigido (2026-09-15) — resiliência do core

- **Timeout de rede do Telegram derrubava o core.** O `HTTPTransport` só
  envolvia `HTTPError`/`URLError`; um `TimeoutError` estourando na **leitura da
  resposta** não passa pelo `URLError` e escapava do `bot.run()` (que tolera
  apenas `TransportError`) até o `asyncio.gather` do launcher, matando o
  **processo inteiro**: 89 quedas e 89 restarts do `od-core` entre 2026-09-13 e
  2026-09-15, uma delas num **crash loop de 4h30** (85 quedas a cada 2–3 min).
  As três chamadas de rede do transporte passaram a capturar `OSError` (cobre
  `TimeoutError`, `ConnectionResetError` e `ssl.SSLError`). Commit **`b215d07`**
  (regressão em `tests/test_telegram.py`, 3 testes).
- **Loops do core sem rede de segurança.** Os laços de **MQTT**, **presença** e
  **visão** chamavam `poll_once()`/`tick()` sem proteção, e o `HAClient` deixava
  `TimeoutError` de leitura escapar cru (mesma classe do bug acima). Cada loop
  ganhou o try/except do "ciclo nunca morre" — a disciplina que o
  `RecoveryLoop` já tinha — e o `launcher._all` passou a **supervisionar** cada
  loop (`_supervise`: contém a exceção, registra e reinicia com espera em vez de
  derrubar o processo; a API entra com `restart=False`, porque recriar o
  servidor conflita na porta 8000). Commit **`0c5b9d8`**;
  `tests/test_launcher_supervisor.py` é novo.
- **Traceback de cliente desconectado poluía o journal.** O `handle_error`
  herdado do `socketserver` imprime o traceback inteiro no stderr do processo
  quando um cliente aborta a conexão no meio do request — e isso é rotina (app
  Android perdendo rede, navegador fechando a aba, health check com timeout):
  em 2026-09-15 10:14:41 o journal ganhou dois `ConnectionResetError` de um peer
  do tailnet, ruído que esconde erro de verdade. O `APIServer` passou a
  sobrescrever `handle_error`: **desconexão** vira uma linha de **DEBUG** sem
  stack, e erro que **não** é desconexão continua aparecendo em **WARN**. Nada
  de diagnóstico se perde — os erros dos handlers já são tratados em
  `APIHandler._handle` (`APIError` → status próprio; `Exception` → 500 +
  `log.error`), então o que chega ali é falha de socket. +3 testes em
  `tests/test_api.py` (um deles aborta um socket com RST de verdade).

### Adicionado (2026-09-15) — supervisão dos loops visível 🔍

- **`core/supervision.py`** (novo) — registro thread-safe das quedas e
  reinícios de cada loop do modo `all` (`failures`, `restarts`, `last_kind`,
  `last_error`, `age_s`). "Degradado" = queda dentro da **janela de 300 s**;
  passada a janela o estado volta a ok sozinho, sem intervenção. O objetivo é
  direto: a supervisão da rodada anterior continha a queda, mas ela ficava
  silenciosa — e foi esse silêncio que deixou as 89 quedas passarem até a
  leitura do journal.
- **Check `loops` no `/health`** — não-crítico (`critical=False`): loop
  reiniciado **degrada** o agregado em vez de derrubá-lo, com o nome do loop e
  o erro no detalhe.
- **Alerta pelo notifier** — nova sonda `_check_loops` nas sondas padrão
  (`integrations/notifier.py`): alerta **WARN** por loop reiniciado, escalando
  para **CRIT** com 3+ reinícios (laço de falha) e limpando o problema quando o
  loop estabiliza; o anti-spam continua o do notifier (1 alerta/hora por loop).
  Commit **`fc2abe0`**.
- **`GET /supervision`** (novo endpoint com `X-API-Key`) — expõe o mesmo estado
  para o app: `{ok, status, window_s, degraded[], restarts, loops[], ts}`.
  `ok=false` + `status=degraded` significam "loop caiu dentro da janela" (o core
  segue de pé, HTTP 200); passada a janela volta a ok. A raiz (`GET /`) passou a
  reportar **27 endpoints**.
- **Testes:** **1689 passed, 16 skipped**, com teste do teste nas três rodadas —
  15 de 18 testes-alvo falharam com as mutações da observabilidade, 2 falharam
  com as mutações da rota (flag de auth e sinal de degradação) e 3 falharam com
  as mutações do `handle_error` (delegar ao `socketserver` e renomear o método).

### App republicado (2026-09-15) — supervisão na aba Status 📱

- **Aba Status** ganhou o card **"Supervisão dos loops"**: mostra se há loop
  reiniciado (`degraded`), a janela considerada, o total de reinícios e, por
  loop, o nome, quantos reinícios e o tipo do último erro (`TimeoutError`…).
  Até aqui o app só sabia de um loop caído pelo Telegram/push.
- **`OdApi.getSupervision()`** consome o `GET /supervision`; `ok=false` +
  `status=degraded` são tratados como **resposta válida** (HTTP 200) — o core
  está de pé, e a tela mostra o loop caído em vez de erro de rede.
- **Best-effort:** falha na rota não derruba a aba — o card avisa "Supervisão
  dos loops indisponível" e o resto da tela continua (a lição do bug do
  `system` aninhado no APK 1.2.0).
- **APK 1.2.0+6** (versionCode 1006/2006/4006) publicado em
  `site/OmegaDrakon.apk` (51.935.427 B) e `site/OmegaDrakon-arm64.apk`
  (18.518.770 B), com sha256 origem == site (`b325ad23…` full · `f3f86059…`
  arm64); o build anterior (**1.2.0+5**) foi preservado em
  `backups/apk-v1.2.0-1005/`. O `versionCode` subiu de propósito: com o mesmo
  código o Android recusa instalar por cima do anterior.
- **Testes do app:** `flutter analyze` sem issues · `flutter test` →
  **48 passed** (42 na entrega anterior; +6: 3 do cliente de API e 3 de
  widget). Teste do teste: tratando `degraded` como erro e omitindo a chamada
  na `_refresh()`, **4 testes falham**.
- **Verificação do binário:** a string `supervision` aparece **2x** no APK novo
  e **0x** no anterior, e `Nenhum loop reiniciado` **1x** contra **0x** —
  diferencial que confirma que o código novo está no binário (a string de
  controle `OmegaDrakon Online` aparece 1x nos dois). A API serviu o arquivo
  novo em `GET /site/OmegaDrakon.apk` (HTTP 200, mesmo tamanho e sha256).

### Provado (2026-09-21) — chat ponta a ponta pela URL do Funnel ✅

- **Prova viva do fluxo real do APK 1.2.8+9**
  (`sandbox_agent/app_funnel_sandbox.py`, gitignored — reproduz o protocolo de
  `od_ws.dart` com TLS validado e prompt único por execução, sem cair no
  cache): **REST** `POST /message` com `X-API-Key` → HTTP 200, `route=llm`,
  `llm=gemma-local`, eco `user_id=app`; **WS** `wss://…/ws` → frame `auth`
  aceito (`via=server`), **512 tokens em streaming**, `route=llm`.
- **Journal do od-core:** `WebSocket authenticated … user_id=app | via=server`
  e 2× `Message processed | route=llm | user=app | llm=gemma-local`
  (latência 94,8 s e 112,5 s em CPU — folga contra o timeout de 240 s do
  app), **0 Traceback/ERROR**.
- **Efeito colateral esperado:** balde `app` no histórico cresceu (as trocas
  das provas entram nele, como qualquer conversa do app); `/supervision` pela
  URL pública: `up`, `restarts: 0`.

### Corrigido (2026-09-21) — app: a URL externa padrão passa a ser o Funnel 📱

- **`app/lib/main.dart`** — o `fallbackUrl` padrão era `http://nicky.theworkpc.com`
  (porta 80, que a operadora bloqueia — ver diagnóstico abaixo) e passou a ser
  **`https://nicky-server.tail1b1f51.ts.net`** (Tailscale Funnel, TLS, sem
  depender de porta). A tela Configurações ganhou o novo hint e o texto
  "Como acessar" ensina o novo endereço; o streaming já deriva `wss://host/ws`
  para https sem porta (commit `57c4710`).
- **APK 1.2.8+9 publicado em `site/`** — o anterior (1.2.8+8) foi preservado
  em `backups/apk-v1.2.8+8-20260921/`; `versionCode` 8 → 9 (o Android recusa
  instalar versionCode menor por cima).
- **Provas:** `flutter analyze` sem issues · `flutter test` **71 passed, 2
  skip**; binário: o `libapp.so` do APK novo contém **1× `tail1b1f51`** e
  **0× `theworkpc`** (o antigo: 0 e 2 — strings diferenciais que confirmam o
  código novo no binário); o APK baixado de
  `https://nicky-server.tail1b1f51.ts.net/site/OmegaDrakon.apk` (HTTP 200,
  52.247.003 B) tem **sha256 idêntico** ao local — a API no ar já serve o
  binário novo pela URL pública.

### Documentado (2026-09-21) — acesso externo publicado via Tailscale Funnel 🌐

- **O caminho recomendado saiu do papel:** com o dono habilitando o Funnel no
  tailnet (clique único em `login.tailscale.com/f/funnel?node=…`), foi
  publicado `tailscale funnel --bg --https=443 8000` (REST) +
  `tailscale serve --bg --https=443 --set-path=/ws 8001` (streaming).
  Resultado: **`https://nicky-server.tail1b1f51.ts.net`** na internet, com TLS
  emitido pelo Tailscale (ACME dns-01, journal `got cert` às 10:06:23).
- **DNS público:** não resolveu de imediato — o autoritativo (dnsimple)
  respondeu NODATA por ~4 min; depois propagou para os ingress
  `209.177.145.97` / `209.177.145.192` (TTL 300). Esperar e reconsultar o
  autoritativo antes de diagnosticar mais nada.
- **Prova de fora (check-host):** `/health` sem credencial devolveu **HTTP 401
  `unauthorized` da nossa API** em 4/5 nós externos (Israel, Irã, Itália,
  Eslovênia — 1,1–1,4 s; ingress `209.177.145.97`). Com `OD_API_AUTH_ALL=1`, o
  401 É a prova: a requisição atravessou a internet e chegou no od-core.
- **Prova do streaming:** `GET https://…/ws` → **HTTP 426** com
  `server: Python/3.12 websockets/16.1.1` — o próprio servidor WS do od-core
  responde pelo mesmo host (426 = falta o `Upgrade`, esperado num GET simples).
- **Nota de operação:** `serve` e `funnel` dividem a 443 — o primeiro
  `serve --set-path` derruba o `funnel` da porta; republicar os dois resolve
  (estado final: `/` e `/ws` com `# Funnel on`). Detalhes em
  `docs/ACESSO_EXTERNO.md` (§ Estado).

### Corrigido (2026-09-21) — app: o streaming se adapta à URL externa 📱

- **`app/lib/services/od_ws.dart`** — o endpoint do streaming passou a ser
  derivado **por URL**, em vez de uma porta única para todas: `https://host`
  sem porta (isto é, a 443) vira **`wss://host/ws`** — o formato que proxy
  reverso publica (Tailscale serve/Funnel, que só tem a 443) — enquanto
  qualquer outra mantém o comportamento antigo (`http://host:8000` →
  `ws://host:8001`). Sem isso a primária (Tailscale, porta própria) e a
  externa HTTPS (por caminho) não conviveriam: uma delas cairia sempre no
  fallback REST e o chat perderia o token-a-token. `wsPath` é configurável
  (`/ws` por padrão).
- **Provas:** +4 testes em `app/test/od_ws_test.dart` (19 no arquivo, **71** na
  suíte do app, 2 skip); teste do teste com 2 mutações, ambas detectadas
  (tirar o ramo de caminho → 4 falhas; `wsPath` para `/` → 3 falhas).

### Documentado (2026-09-21) — acesso externo: o bloqueio é da operadora 🌐

- **`docs/ACESSO_EXTERNO.md` (novo)** — o app não acessa pela internet, só pelo
  Tailscale. **Diagnóstico fechado com prova de mão dupla:** o pedido feito
  **ao IP público pela porta 80**, de dentro, chega na nossa API (`401` com
  `Server: OmegaDrakon/1.2.0`) e o `/supervision` é **idêntico** ao local (só o
  campo `ts` difere) — ou seja, **a regra `80 → 192.168.0.250:8000` está ativa
  e apontando certo**. O roteador ainda responde com a própria UI em
  `189.124.4.56:8443`, o que prova que **ele é o dono do IP público** (PPPoE,
  hop 2 já na agregação da operadora: **sem CGNAT**). Mesmo assim, **de fora**
  a `80` e a `8000` dão timeout (sonda com 4–6 nós independentes) e a varredura
  externa mostra **80, 443, 8000, 8443, 22 e 1883 fechadas** — inclusive a
  `8443` do próprio roteador.
- **Conclusão:** não é o app e não é o roteador — o filtro de entrada está
  **acima** do roteador (operadora). Criar mais regras não resolve; `curl` de
  dentro da rede sempre dá falso positivo (hairpin NAT), que foi como a
  verificação de 09-19 concluiu "FUNCIONANDO" sem estar.
- **Caminho recomendado:** `tailscale funnel --bg --https=443 8000` publica
  **`https://nicky-server.tail1b1f51.ts.net`** → `127.0.0.1:8000` com TLS, sem
  tocar no roteador nem depender de porta; o streaming vai no mesmo host por
  `--set-path=/ws` → `8001`. O CLI respondeu que o Funnel **não está habilitado
  no tailnet** e deu o link de um clique (`login.tailscale.com/f/funnel?node=…`).
- **Alternativas registradas:** pedir liberação de portas/IP público à
  operadora, ou IPv6 nativo (esta máquina tem `2804:428:3:6340:…/64`, mas exige
  liberar o firewall IPv6 no roteador e AAAA com prefixo dinâmico).

### Corrigido (2026-09-21) — /history devolve 404 para nome que não é de ninguém 🧭

- **`GET /history/{user_id}/stats` e `DELETE /history/{user_id}`** — nome que
  não é conta e não tem mensagem alguma devolve **404
  `historico_inexistente`**, em vez de 200 com zero (pega erro de digitação).
  Continuam **200 com zero**: conta recém-criada e quem acabou de apagar o
  próprio histórico — a conta existe, e 404 ali quebraria a tela de histórico
  vazio. Balde legado com mensagens (ex.: `app` do celular) segue 200. Sem
  `UserStore` (dev local) o comportamento antigo permanece: sem contas não há
  como afirmar que um nome é de alguém. A checagem de dono (403) continua vindo
  antes, então ninguém descobre nada sobre o balde alheio.
- **Testes:** `tests/test_auth.py` **+4** (conta nova → 200/zero, apagou o
  próprio histórico → 200/zero, nome inexistente → 404 no GET e no DELETE,
  balde legado com mensagens → 200) e **4 mutações** detectadas (nunca 404;
  404 ignorando a conta; 404 no dev sem `UserStore`; 404 sempre).
- **Suíte:** **1854 passed, 16 skipped**.
- **Legado inerte com backup pronto:** `backups/legacy-json-sqlite-20260921.tar.gz`
  (3,2 KB, sha256 `545c29e3…`, gzip verificado) com `data/od.db` (SQLite
  sem tabelas) e `data/conversations/` (subconjunto antigo do que já está no
  PostgreSQL — 20/2/2 mensagens). A remoção do diretório depende da confirmação
  do dono (regra 9).

### Alterado (2026-09-21) — histórico órfão reatribuído à conta 🔁

- **`runtime/migrate_history_owner.py` (novo)** — one-off, **idempotente** e
  **dry-run por padrão**: reatribui baldes antigos para a conta do dono
  (`UPDATE conversation_messages SET user_id = ?`, preservando o perfil de
  cada conversa) e grava um snapshot de rollback em `backups/`. Os baldes
  nasceram de cada transporte antes do login (chat web em `web`, streaming em
  `ws_user`, app em `app`, bot no id do Telegram); com a identidade vindo da
  credencial, eles ficaram órfãos — a conta não enxergava o que foi
  conversado por eles.
- **Migrado no sistema real:** `web` (14) + `web/nyx` (6) + `ws_user` (4) →
  `alex` (2 → **26** mensagens, perfis guardian 20 / nyx 6). O total da tabela
  não mudou (**86** antes e depois) e a API no ar confirma pelo
  `/history/alex/stats`. Snapshot:
  `backups/history-owner-20260921-093127.bak`.
- **O que ficou de fora, de propósito:** `app` (36) — o app manda
  `user_id: "app"` fixo, então o balde nasceria de novo na próxima mensagem
  do celular; e `660518870` (20, Telegram) — o bot identifica a pessoa pelo id
  do Telegram e faria o mesmo. Migrar os dois é um comando
  (`--de app,660518870`) quando o app autenticar por sessão. `deploy-check*`
  (4) são mensagens sintéticas de prova de deploy, não conversa.
- **Testes:** `tests/test_migrate_history_owner.py` (**novo, 8**) — plan sem
  escrever, preservação de conteúdo/perfil/ordem cronológica, total
  inalterado, idempotência, múltiplas origens e rollback pelo snapshot.
- **Suíte:** **1850 passed, 16 skipped**.

### Corrigido (2026-09-21) — streaming: a identidade vem da credencial 🔌

- **`integrations/api/ws_server.py`** — o frame `auth` só aceitava a
  `OD_API_KEY` global e o **próprio cliente dizia quem era** (`user_id`):
  qualquer portador da chave escrevia no histórico de qualquer username pelo
  streaming — a mesma família do furo fechado no REST no item abaixo. Agora o
  `auth` aceita `token` de sessão (`UserStore.validate_session`) e API key de
  usuário (`od_...`), e a identidade sai da **credencial**: o `user_id` do
  frame é ignorado. A `OD_API_KEY` continua sendo o caminho do app/bot — sem
  usuário associado, vale o `user_id` do frame, agora validado.
- **Streaming volta a funcionar no chat web logado:** o chat usava o campo de
  chave do "modo avançado" (vazio quando se entra por login/senha), a auth
  falhava e ele caía no fallback REST. Com o `token` de sessão no frame, o
  token-a-token passa a ser o caminho normal de quem está logado.
- **`valid_user_id` (`integrations/api/server.py`)** — o id escolhido pelo
  cliente vira nome de arquivo no backend JSON
  (`data/conversations/{user_id}`): um `../../` escaparia do diretório. Vale
  para o `/message` no modo `OD_API_KEY` e para o frame de `auth` do WS →
  **400** `user_id_invalido` / close **4002**. Os ids legados casam todos
  (`web`, `app`, `ws_user`, `deploy-check-2`, `660518870`).
- **`runtime/launcher.py`** — `build_user_store(database)` passa a ser único e
  compartilhado por REST e WebSocket: a sessão criada no login vale nos dois
  transportes (antes o WS nem enxergava o UserStore).
- **Bypass fechado no WS:** com `UserStore` ligada e **sem** `OD_API_KEY`, um
  `auth` sem credencial autenticava — o mesmo defeito corrigido no REST em
  09-20, que seguia aberto no streaming.
- **Testes:** `tests/test_websocket.py` **+12** (`TestWebSocketIdentidade`:
  sessão manda na identidade, API key de usuário, `OD_API_KEY` mantendo o
  balde, `user_id` só no `message` não troca nada, token falso → 4001, ids
  inválidos → 4002, UserStore sem `OD_API_KEY` exigindo credencial) e
  `tests/test_auth.py` **+5** (ids inválidos no `/message` legado e o id do
  corpo ignorado quando há credencial de usuário).
- **Teste do teste (4 mutações, todas revertidas):** identidade voltar a vir
  do cliente → **2 falhas**; validação de `user_id` removida → 4; token
  aceito sem validar → 3; `api_keys` vazio + `UserStore` voltando a abrir sem
  credencial → 4.
- **Sandbox (regra 12):** `sandbox_agent/ws_sandbox.py` ganhou o cenário de
  identidade contra o **llama-server real** — sessão → histórico do usuário da
  sessão (balde pedido pelo cliente fica vazio), `OD_API_KEY` mantendo o balde
  do app, `user_id` inválido → 4002, token falso → 4001 → **18/18 OK**.
- **Suíte:** **1842 passed, 16 skipped**.

### Corrigido (2026-09-21) — dono do histórico: cada conta só acessa a sua 🚪

- **`DELETE /history/{user_id}`, `GET /history/{user_id}/stats` e
  `GET /memory/{user_id}/search`** passam a checar o dono do recurso: com
  credencial de USUÁRIO (sessão `Bearer` ou API key `od_...`), o `{user_id}`
  do caminho tem de ser o **username autenticado** — do contrário **403**
  (`acesso_negado`, com log `Acesso a recurso de outro usuário negado`). A
  `OD_API_KEY` do servidor é o passe de admin: não tem usuário associado
  (`_current_user is None`), é a chave do operador e do app/bot, e continua
  lendo/apagando **qualquer** histórico. Sem `UserStore` (dev local) o
  comportamento legado permanece. Em `/memory` a checagem vem **antes** do
  501 — não conta para o histórico de outra pessoa se o `VectorStore` existe.
- **O que estava aberto:** qualquer credencial válida lia — e **apagava** —
  a conversa de qualquer username. Era inofensivo enquanto todo mundo era o
  balde `"web"`; deixou de ser desde que cada pessoa tem conta e senha
  (leitura e exclusão de conversa alheia por quem estivesse logado).
- **Testes:** `tests/test_auth.py` **+11** (`TestHistoryOwnership`): stats e
  DELETE do próprio histórico, 403 na leitura e na exclusão de outro
  username, o histórico do alvo **intacto** após o 403, a mesma regra para
  API key de usuário, `OD_API_KEY` como admin, caixa do username no caminho
  (`/history/Alex`), 403 antes do 501 em `/memory`, isolamento do namespace
  na busca semântica e 401 para quem não tem credencial.
- **Teste do teste (5 mutações, todas revertidas):** `_check_owner` sempre
  libera → **5 falhas**; checar só o `Bearer` (API key de usuário passando)
  → 1; comparação case-sensitive → 1; `history_delete` sem checagem → 1;
  `/memory` checando depois do 501 → 2.
- **Sandbox (antes do sistema real):** `sandbox_agent/auth_sandbox.py` ganhou
  um terceiro cenário (dois usuários + histórico real) → **27/27 OK** (18
  antes).
- **Suíte:** **1825 passed, 16 skipped** (49,52s).

### Corrigido (2026-09-21) — freio contra força bruta no login 🛡️

- **`LoginGuard` (`integrations/api/auth.py`)** — `POST /auth/login` é
  público por definição (o fluxo de autenticação não pode exigir
  autenticação) e, com o login por senha no ar, aceitava tentativas
  ilimitadas. O guard conta falhas em **duas chaves independentes**:
  `(ip, username)` — trava a conta para aquele IP; e `(ip)` — soma falhas de
  **qualquer** username e trava o IP inteiro (pega o *password spraying* que
  troca o username a cada tentativa). Login bem-sucedido zera a chave da
  conta, mas **não** a do IP. Janela de 300s, lockout de 900s, thread-safe,
  `clock` injetável para teste determinístico e GC das chaves antigas
  (memória limitada pelo tráfego recente).
- **`integrations/api/server.py`** — `APIConfig` ganhou `login_guard`,
  `login_max_attempts` (5), `login_window_s` (300) e `login_lockout_s`
  (900); o servidor constrói o guard quando há `UserStore`. O freio roda
  **antes** de tocar no banco: tentativa bloqueada responde **429
  `too_many_attempts`** com `retry_after_s` e não consome PBKDF2 (260k
  iterações seriam trabalho de graça para o atacante).
- **`runtime/launcher.py`** — repassa `OD_LOGIN_MAX_ATTEMPTS`,
  `OD_LOGIN_WINDOW_S` e `OD_LOGIN_LOCKOUT_S` para a config da API.
- **Testes:** `tests/test_auth.py` **+11** — limites por conta e por IP,
  janela deslizante (falhas fora dela não acumulam), expiração do lockout,
  `reset` que não zera o IP, o 429 por HTTP real (inclusive bloqueando a
  **senha correta** durante o lockout) e o spraying que troca o username.
- **Suíte:** **1814 passed, 16 skipped**.
- **Implantado em 2026-09-21 09:05:45** (PID 749398) — subiu junto com a
  checagem de dono do histórico; provado no ar: 6ª tentativa do mesmo
  usuário/IP → `429 too_many_attempts`.
- **Ressalva de processo:** o código foi escrito em 2026-09-20 e ficou sem
  commit e sem registro em `iniciar/` até 09-21, quando entrou no restart
  seguinte. Não passou pelo sandbox da regra 12 **antes** do deploy (só
  pelos testes); a prova viva no ar é o que sustenta o comportamento hoje.
- **Lacuna da regra 12 fechada (2026-09-21):** `sandbox_agent/auth_sandbox.py`
  ganhou o cenário do freio sobre um `APIServer` real — erro isolado não trava,
  login certo zera o contador da conta, falhas **consecutivas** travam até a
  senha correta (**429 `too_many_attempts`** com `retry_after_s`), o mesmo IP
  travado pega o *spraying* de outro username e tentativa bloqueada não estende
  a punição → **36/36 OK** (era 27).

### Adicionado (2026-09-19/20) — autenticação de usuários no chat web 🔐

- **`integrations/api/auth.py` (novo)** — `UserStore` sobre a Database Layer:
  registro (validação de username/email/senha), login e sessões com token
  UUID4 e expiração configurável, API keys de usuário (`od_` + 40 hex),
  rotação de chave e limpeza de sessões expiradas. Hash de senha em
  **PBKDF2-SHA256** (260k iterações) com salt aleatório — stdlib, sem bcrypt.
- **Rotas `/auth/*`** — `POST /auth/register`, `POST /auth/login` (públicas:
  o próprio fluxo de autenticação não pode exigir auth), `POST /auth/logout`
  e `GET /auth/me` (protegidas). O chat web (`GET /chat`) trocou o gate de
  API key por **login/registro**, com o modo `X-API-Key` preservado como
  "avançado"; a sessão é enviada em `Authorization: Bearer` e persistida em
  `localStorage`.
- **`runtime/launcher.py`** — `build_api_server`/`_run_api_forever` recebem a
  `Database` e montam o `UserStore`; `OD_AUTH_ENABLED=0` desliga.
- **Corrigido no caminho — bypass de auth:** com a auth de usuários ligada
  mas **sem** `OD_API_KEY`, um `Bearer` inválido caía no caminho "auth
  desligada" de `_check_api_key` e **passava**. Agora, com `UserStore`
  configurada, credencial válida é obrigatória (o dev local sem `UserStore`
  segue aberto). O mesmo ajuste fez o gate aceitar **API key de usuário**
  (antes só `OD_API_KEY` do `.env`), alinhando o comportamento ao que o
  `GET /auth/me` já documentava.
- **Identidade em `POST /message`:** com credencial de usuário (sessão
  Bearer ou API key `od_...`), o servidor usa o **usuário autenticado** e
  ignora o `user_id` do corpo. Antes, o chat web mandava sempre `"web"` —
  todas as contas dividiam o mesmo balde de histórico/cache e dava para
  postar como qualquer nome. O app/bot por `OD_API_KEY` segue usando o
  `user_id` do corpo (não há usuário associado). O chat web passou a mandar
  o username do login.
- **Testes:** `tests/test_auth.py` (**novo, 48 testes**) — hash/salt e senha
  nunca em claro, validação e unicidade do registro, login/sessão/expiração/
  logout, API keys, e os endpoints `/auth/*` por HTTP real, incluindo o
  caminho do chat (`login → Bearer → POST /message`). A feature havia subido
  em produção (2026-09-19) **sem cobertura dedicada** e com uma rota
  protegida não refletida em `test_api.py` (`test_auth_flags_follow_legacy`
  falhava) — ambos corrigidos.
- **Teste do teste (7 mutações, todas revertidas):** remover o bloqueio do
  bypass → 1 falha; remover o caminho de API key de usuário no gate → 2;
  `_verify_password` sempre aceita → 3; `validate_session` ignorar a
  expiração → 1; `register` sem checar duplicata → 3; servidor voltar a usar
  o `user_id` do corpo → 2; chat web voltar ao `"web"` fixo → 1.
- **Sandbox (antes do sistema real):** `sandbox_agent/auth_sandbox.py` (pasta
  ignorada pelo git) sobre um `APIServer` real com SQLite de arquivo →
  **16/16 OK**: register/login/Bearer, `/auth/me` por sessão e por API key de
  usuário, `POST /message` autenticado pela sessão, casos negativos (token
  inválido, sem credencial, chave errada → 401) e o cenário do bypass.
- **Suíte:** **1804 passed, 16 skipped** (40,21s).

### Adicionado (2026-09-18) — streaming do chat por WebSocket 🌊

- **Novo `integrations/api/ws_server.py`** — servidor WebSocket
  (`websockets.asyncio.server.serve`, porta `OD_WS_PORT` padrão **8001**,
  ligado por `OD_WS_ENABLED`) que fala com o **mesmo `Orchestrator`** da API
  REST. Protocolo: `auth`/`message` do cliente → `authenticated`,
  `processing`, `token`… e `done` (`route`, `llm_used`, `latency_ms`); auth
  pela mesma `OD_API_KEY` (`api_key` inválida → close **4001**).
- **`core/llm.py`** — `OpenAICompatProvider.generate_stream` +
  `_post_chat_stream`: parser de SSE do formato OpenAI (`data: {...}` /
  `data: [DONE]`) com import tardio do `websockets` (sem ele o core sobe
  normal e só o streaming fica indisponível, como o push sem google-auth).
- **`core/orchestrator.py`** — `process_stream`: o mesmo pipeline de etapas
  (rate limit → datetime → quick → intents → cache → LLM com fallback para
  `generate`) emitindo `token`/`done`/`error`; pós-processamento (cache +
  histórico) preservado.
- **`runtime/launcher.py`** — `build_ws_server` + subida no `_run_api_forever`
  com a falha **contida** em `try/except`: WS que não sobe (porta ocupada,
  dependência ausente) é logado e o REST + o resto do núcleo seguem de pé.
- **`requirements.txt`** — `websockets>=14.0` declarado (item 3), com
  justificativa: é o único servidor não-stdlib do projeto.
- **Ruído no journal:** o `websockets` loga `opening handshake failed` com
  `exc_info=True` — um TCP cru que abre e fecha (sonda de porta, health check)
  despejava **traceback inteiro no stderr**, o mesmo defeito que o
  `handle_error` do `http.server` tinha (correção de 2026-09-15). Agora um
  `_LibraryLogger` (LoggerAdapter) leva o log da biblioteca para o log do OD
  em **UMA linha de debug**; cliente que cai no meio do stream também saiu de
  `log.error` para debug.
- **Testes:** `tests/test_websocket.py` **reescrito (14 → 28)**. Os 14
  anteriores só conferiam formato de dict e existência de método — a suíte
  passava enquanto `start()` quebrava com `import websockets.serve`
  (`ModuleNotFoundError`). Agora há ciclo de vida real (sobe e escuta,
  `bound_port`, `stop` libera a porta, porta ocupada → `RuntimeError` sem
  derrubar o primeiro), protocolo com **cliente WebSocket real**, queda no
  meio do stream, sonda TCP crua sem traceback, SSE do provider, `process_stream`
  e fiação do launcher. **Teste do teste (4 mutações, todas revertidas):**
  import quebrado → *5 failed + 6 errors*; checagem de `api_key` removida →
  falha (revelou que o teste **pendurava** — daí o teto de 10s por fluxo);
  `stop()` sem fechar o servidor → 2 falhas; launcher sem o `try/except` →
  falha a contenção; `serve()` sem o `_LibraryLogger` e handler sem o
  tratamento de desconexão → 1 falha cada.
- **Corrigido no caminho (2026-09-18):** o `POST /message` **valida o perfil**
  e resolve `auto` → `guardian` (`DEFAULT_PROFILE`), mas o WebSocket mandava
  `auto` cru — como o app manda `profile: auto` por padrão, a MESMA conversa
  cairia em baldes diferentes de cache/histórico conforme o transporte (e
  perfil inválido era aceito no WS e recusado no REST). O `ws_server` agora
  importa `DEFAULT_PROFILE`/`DEFAULT_PROFILES` de `integrations.api.server`
  (mesma fonte, sem duplicar a lista), resolve `auto` e recusa perfil
  desconhecido com o mesmo texto do REST. **+2 testes** (`perfil auto vira o
  padrão`, `perfil desconhecido é recusado sem processar`); mutações G/H
  (aceitar perfil inválido e não resolver `auto`) → os 2 falham. Prova ao vivo
  após o deploy: `profile: auto` pelo WebSocket registra
  `Interaction recorded | profile=guardian`.
- **Suíte:** **1719 passed, 16 skipped** (17,29s).
- **Sandbox (antes do sistema real):** `sandbox_agent/ws_sandbox.py` (pasta
  ignorada pelo git) contra o **llama-server real** em `127.0.0.1:8081` →
  **11/11 checagens OK e stderr com 0 bytes**: 35 frames de token com
  espalhamento de **2,67s** (1º em 2,04s, último em 4,71s) — streaming
  incremental de verdade, não um bloco no fim; tokens concatenados ==
  `content` do `done` (`route=llm`); reuso da conexão; chave inválida →
  close 4001; desconexão abrupta sem derrubar o servidor; sonda TCP crua sem
  traceback. Foi o sandbox que expôs os dois ruídos acima.
- **Deploy:** `od-core` reiniciado em **2026-09-18 04:35:09** (PID 395579,
  `NRestarts=0`) — `[NICKY][INFO] WebSocket server no ar | host=0.0.0.0 |
  port=8001 | auth=True`, `:8001` escutando e `/health` com os 9 checks `up`.
  **Prova ao vivo:** mensagem real pelo WebSocket em produção → 7 frames de
  token, `tokens == content do done`, `route=llm`; chave errada → close 4001;
  3 sondas TCP cruas → journal com **0** `Traceback`, **0**
  `opening handshake failed`, **0** `WebSocket processing error`.
- **Nota de escopo:** o **app Flutter ainda usa `POST /message`** — não há
  cliente WebSocket no app; esta entrega é o lado servidor. `process_stream`
  também **não publica** `orchestrator.responded` no EventBus (o `process`
  publica); hoje ninguém assina esse tópico em produção.

### App — chat em streaming com fallback (2026-09-18) 📱

- **`app/lib/services/od_ws.dart` (novo)** — `OdStreamingChat`: fala o
  protocolo do `ws_server` (`auth`/`message` → `authenticated`, `processing`,
  `token`… `done`) e entrega a resposta em `OdChatDelta`s. Deriva a porta do
  streaming da URL já configurada (`http://host:8000` → `ws://host:8001`,
  `https` → `wss`; `wsPort` configurável). Usa `dart:io WebSocket` — **nenhum
  pacote novo no pubspec** (mesmo caminho de rede do `OdApi`).
- **Fallback automático para `POST /message`** quando o WebSocket não estiver
  disponível (core antigo, porta fechada, chave recusada, rede trocando de
  rota) — e **cooldown de 2 min** depois de uma falha, senão toda mensagem
  pagaria o timeout de conexão antes de cair para o REST (o chat ficaria mais
  lento que antes da entrega).
- **Interrupção no meio do stream não repete a mensagem**: se já apareceu
  texto, o app NÃO refaz a chamada pelo REST (duplicaria a resposta e faria
  uma segunda inferência no servidor) — mostra o parcial e avisa na mesma
  bolha (`OdStreamingError`).
- **`chat_screen.dart`** — a bolha do assistente nasce no primeiro token e é
  reescrita a cada frame; o "Digitando..." só aparece enquanto nada chegou; e
  há um selo discreto do transporte da última resposta (⚡ **Streaming ativo**
  ou ↔ **Resposta via REST**), que é o que permite conferir no celular se o
  streaming está de pé.
- **Encerramento best-effort do canal**: nem o `cancel()` do iterador nem o
  `close()` do socket podem segurar a resposta — esperar por eles travava a
  tela com o texto já pronto (bug pego por teste de widget e depois pinado em
  teste unitário com um canal que nunca fecha).
- **`OdApi(apiKey:)`** — chave só em memória, para verificações vivas e testes
  que rodam sem o binding do Flutter (o binding troca o `HttpClient` por um
  dublê que responde 400 e não haveria socket real para exercitar).
- **Testes do app:** `flutter analyze` sem issues · `flutter test` →
  **67 passed, 2 skipped** (49 → 67). Novos: `test/od_ws_test.dart` (12:
  derivação da URL, protocolo com canal roteirizado, frames desconhecidos,
  fallback, interrupção sem duplicar, cooldown, 401) e 3 de widget em
  `test/widget_test.dart` (render incremental token-a-token, fallback com
  selo do transporte, corte no meio mantendo o texto). `test/ws_live_test.dart`
  (2, **opt-in por `OD_LIVE_WS=1`**) fala com o core REAL pelo conector de
  produção.
- **Teste do teste (3 mutações, revertidas):** sem a guarda de texto parcial →
  2 falhas (fallback indevido depois do parcial); com o encerramento aguardado
  (`await cancel` + `await close`) → 3 falhas (unitário do canal que não fecha
  e os 2 de widget, que ficam com o spinner preso); sem o cooldown → 1 falha.
- **Validação viva (sandbox, antes de publicar):** no nicky-server, contra o
  `od-core` em produção → **36 deltas pelo WebSocket** (`transport=webSocket`,
  35 frames de token) respondendo "1 a 15" em ~8s; e chave errada → o
  streaming recusa e o app cai para o REST, que devolve **401**
  (`OdAuthError`).
- **APK 1.2.0+7 publicado** — `site/OmegaDrakon.apk` **52.230.399 B** (sha256
  `c69f2ccd…`, `versionCode 7`) e `site/OmegaDrakon-arm64.apk` **18.649.902 B**
  (sha256 `a5015cd7…`, `versionCode 2007`), com `versionName 1.2.0` conferido
  no `aapt dump badging`; origem == `site/` (sha256 idêntico). O `versionCode`
  subiu de propósito (o Android recusa instalar por cima com o mesmo código) e
  o build anterior (**1.2.0+6**, 51.935.427 B em `b325ad23…` e 18.518.770 B
  em `f3f86059…`) ficou em `backups/apk-v1.2.0-1006/`. Servido pela API: `GET /site/OmegaDrakon.apk` →
  HTTP 200 com o mesmo tamanho e sha256.
- **Prova no binário:** `Streaming ativo` **1x** no APK novo contra **0x** no
  anterior e `Resposta via REST` **1x** contra **0x** (controle
  `OmegaDrakon Online` **1x** nos dois).

### Infraestrutura — monitor do roteador versionado e corrigido (2026-09-18) 📡

- **Versionado o que já rodava solto em produção:**
  `tools/monitor/router_monitor.sh` (ping no gateway + estado da interface +
  link changes do Tailscale, em JSON-lines) e as units, que saíram de
  `tools/monitor/` para `runtime/systemd/router-monitor.{service,timer}` —
  junto das units do núcleo. O `install-user.sh` passa a copiar e a ligar o
  timer (`enable --now router-monitor.timer`), e `tools/monitor/README.md`
  documenta uso, variáveis (`OD_ROUTER_IP`, `OD_NETWORK_INTERFACE`,
  `OD_MONITOR_*`, `OD_LOG_DIR`) e limites.
- **Bug corrigido (o monitor era cego para o que existe para medir):** em 17h
  de operação havia **1086 registros `up` e ZERO `down`**. Causa raiz: `set -e`
  combinado com `x=$(comando que falha)` — o ping que falhava (roteador fora)
  derrubava o script **antes** do registro do `down`, e o `cat` de
  `/sys/class/net/<if>/carrier` com a interface ausente abortava antes da linha
  da interface. Correção na raiz: o script **não usa mais `set -e`** (monitor
  precisa sobreviver a falha transitória), todo comando externo tem fallback
  explícito, e `carrier`/`speed` são forçados a numérico (senão o JSON-lines
  sairia inválido). `--once` passa a sair **0 mesmo com o roteador fora** — o
  estado fica no log e um unit em falha a cada minuto durante a queda seria
  ruído pelo motivo errado.
- **Adicionado:** rotação do log (`OD_MONITOR_MAX_BYTES`, padrão 5 MiB,
  mantendo uma geração `<arquivo>.1`) — 1 linha/min ≈ 130 MB/ano sem teto —,
  `journalctl` opcional, e o relatório deixou de prometer "janelas >30s" que
  nunca calculou (agora descreve o que faz: incidentes por dia).
- **Testes:** `tests/test_router_monitor.py` (novo, **15**) roda o script de
  verdade em sandbox (diretório temporário + gateway de teste do RFC 5737) e
  pina os dois casos do bug, o contrato do log, a rotação e o `--report`;
  `tests/test_systemd_units.py` ganhou **10** asserções (units do monitor +
  instalador). **Suíte: 1743 passed, 16 skipped.**
- **Teste do teste:** reintroduzindo a forma original (`set -euo pipefail` +
  `ping_result=$(...)` + chamada sem guarda) → **6 falhas**, incluindo as três
  que pinam "o `down` é registrado"; revertido.
- **Prova no systemd:** o timer dispara de 1 em 1 minuto com
  `SyslogIdentifier=router-monitor` e registra `up` no log; e um `systemd-run`
  com `OD_ROUTER_IP=192.0.2.1` (inalcançável) **conclui com sucesso**
  enquanto grava `{"status":"down","detail":"ping_failed"}` — exatamente o
  que não acontecia antes. `od-core` não foi reiniciado (PID 399298 intacto).

### Corrigido (2026-09-18) — paridade do `orchestrator.responded` entre REST e WebSocket 🔔

- **A mesma conversa era registrada de dois jeitos.** `process` (REST) passa
  **todo** desfecho por `_finish` — métricas, evento e log `Message processed` —,
  enquanto `process_stream` (WebSocket) só contava `processed` no caminho do LLM
  e **nunca publicava** `orchestrator.responded` (havia até um comentário
  `# Publicar evento` órfão onde a publicação deveria estar). Atalhos (datetime,
  quick, cache, intents) e falhas (rate limit, indisponível) simplesmente não
  apareciam em quem observa o núcleo. Agora **toda saída terminal do stream
  passa pelo `_finish`**, com um `OrchestrationResult` montado por
  `_stream_result` — mesmas métricas, mesmo evento, mesmo log.
- **Provider sync voltou a responder no WebSocket.** O fallback não-streaming do
  stream fazia `await provider.generate(...)`; com um provider **sync** (ex.:
  `StaticProvider`) isso levantava `TypeError`, ninguém tratava e o resultado era
  `todos_providers_falharam` — o mesmo provider respondia no REST (que já usava
  `inspect.isawaitable`) e falhava no WebSocket. A chamada foi extraída para
  `_generate_one`, usada pelos dois caminhos.
- **Paridade de textos:** `RATE_LIMITED_MESSAGE` e `DEFAULT_UNAVAILABLE_ERROR`
  viraram constantes, em vez de literais repetidos — o evento/log do stream
  carrega exatamente o que o REST carregaria. O cliente continua recebendo o
  código curto no chunk de erro (`rate_limited`), que é contrato do protocolo.
- **Testes:** +6 em `tests/test_orchestrator.py` (classe `TestOrchestratorEventBus`),
  incluindo a comparação direta `evento do REST == evento do WebSocket` para o
  mesmo texto. **Suíte: 1749 passed, 16 skipped.**
- **Teste do teste:** 4 mutações — tirar o `_finish` do atalho datetime → 1
  falha; exigir provider async outra vez → 1 falha; evento do rate limit com o
  código curto → 1 falha; voltar o caminho do LLM ao estado original (sem
  evento) → 2 falhas. Revertidas.
- **Validação em sandbox** (`sandbox_agent/event_parity_sandbox.py`, contra o
  llama-server real): **7/7 OK**, incluindo `evento do REST == evento do
  WebSocket` e o atalho datetime publicando. `od-core` **não** foi reiniciado —
  a mudança ainda não está em produção (PID 399298 de 04:49).

### Adicionado (2026-09-18) — alerta do roteador pelo notifier 📡

- **Nova sonda `_check_router`** no `ProactiveNotifier`: lê a última linha
  de `logs/router_monitor.log` (escrita pelo `router_monitor.sh` a cada
  minuto) e alerta quando `status=down`. O monitor do roteador já registrava
  quedas no log, mas quem avisa é agora o notifier (Telegram/push) — o mesmo
  canal dos alertas de loop e disco.
- **Integração zero-config:** se o log não existe (monitor não configurado),
  a sonda retorna `ok=True` sem ruído. Anti-spam: cooldown padrão 1h por
  chave `router:down`.
- **Testes:** +6 em `tests/test_notifier.py` (classe `TestCheckRouter`):
  log ausente, router up, router down, múltiplas linhas, log vazio, JSON
  malformado. Suíte: 1755 passed, 16 skipped.
- **Teste do teste:** removendo `_check_router` de `_default_checks`,
  `test_dump_shape` falha (lista de checks não bate).

### Pendente

- ~~Gerar a **service account** no console do Firebase e gravá-la em
  `config/firebase-service-account.json` para o envio sair do modo dormente
  (o app já está registrando o token).~~ **Feito em 2026-09-14** — ver
  *Ativado (2026-09-14)* acima.

---

## [1.1.0] — Acesso Externo Seguro 🔐 (2026-09-07)

### Adicionado

- **Tailscale (VPN mesh WireGuard)** — IP `100.77.67.53`, tailnet
  `nickyvirthy`, interface `tailscale0`, versão 1.102.2; API acessível de fora
  da LAN em `http://100.77.67.53:8000` com `X-API-Key`.
- **Documentação** — `docs/TAILSCALE_SETUP.md`.

### Infraestrutura

- Segurança em camadas: VPN + `X-API-Key` + UFW (22/8000/8123) — **zero portas
  abertas no roteador**.
- Journal sem exposição de segredos (verificado no roadmap).

### Testes

- Sem suíte nova (item de infraestrutura/rede); critérios de aceite validados
  contra o servidor nicky-server — ver `docs/README_VERSAO.md` §[1.1.0].

---

## [1.0.0] — Fundação v1 (release-grade) 🏛️ (2026-09-07)

### Adicionado

- **7º perfil `nexus`** (Conector) em `agents/profiles.py` — a Plêiade fica
  completa (7 entidades), com detecção automática por domínio
  (conexão/integração/plêiade).
- **Health checks externos** — Home Assistant e MQTT/Mosquitto no Health
  Monitor; `/health` passa a expor 7 checks (5 internos + HA + MQTT).
- **Control Bridge no repositório** — `tests/test_control_bridge.py`
  (allowlist, tokens, escape de path, legados §7.1, auditoria, execute) e o
  unit systemd `runtime/systemd/od-control-bridge.service`.

### Infraestrutura

- **CI no GitHub Actions** — `.github/workflows/ci.yml` (Python 3.12, push +
  PR): `compileall` + `pytest -q` com gate de cobertura ≥ 90% (`.coveragerc`,
  `runtime/launcher.py` omitido).
- **Migração JSON → PostgreSQL** — `memory/adapters.py` (schemas +
  `migrate_all()` idempotente); `history.py`, `cache.py`, `quick_responses.py`
  e `vector.py` ganharam `database=None`; fallback JSON mantido.
- **Systemd `od-core`** — `runtime/systemd/od-core.service` (NoNewPrivileges,
  ProtectSystem=strict, ProtectKernel*, MemoryMax=6G, CPUQuota=200%,
  ReadWritePaths) + `install-user.sh` com verificação de linger.
- **SWAP 8 GB** (`/swapfile`) + `vm.swappiness=10` via
  `runtime/setup/setup-server.sh`.
- **UFW ativo** — 22 (SSH), 8000 (OD API), 8123 (HA) permitidos; resto
  bloqueado.
- **Variáveis de ambiente ausentes** — 6 configuradas no `.env`
  (`OD_PRESENCE_ENABLED`, `OD_PRESENCE_POLL_S`, `OD_RECOVERY_INTERVAL_S`,
  `OD_SELF_REPAIR_ENABLED`, `OD_NOTIFIER_ENABLED`).
- **Disco `sdb1` montado** em `/home/alex/dados` (801 GB livres) + automount
  via `/etc/fstab`.

### Testes

- Suíte local: **1594 passed**; cobertura **95%** (gate ≥ 90% no CI).
- Novos: 46 testes da migração JSON→DB; 29 de `tests/test_systemd_units.py`;
  26 de `tests/test_control_bridge.py`.

---

## Série 0.x — congelada em [0.28.1] ❄️ (2026-09-04)

A série 0.x está **congelada**: a v0.28.1 é o marco estável final (PostgreSQL
nativo no ar, loop de auto-recuperação fechado, fast path de intenções,
57 actions, 1453 testes verdes, tag git `v0.28.1` no commit `ba2f7c8`).
O histórico detalhado de cada versão 0.1.0–0.28.4 está em
`docs/README_VERSAO.md` e nas Fases 1–7 de `docs/ROADMAP_ABSORCAO.md`
(37/37 capacidades absorvidas).

```python
"""
OMEGA DRAKON • SYSTEMS
Tecnologia que respira.
Módulo: docs/CHANGELOG.md
Descrição: Registro de mudanças por versão (item 4 da Definition of Done).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""
__signature__ = "OD // CORE"
```
