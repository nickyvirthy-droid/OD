# Conversa OmegaDrakon — 21/11/2026

## §1 — APK instalado, acervo do Raul fechado e leitura de `analise/`

**Pedido do dono (21/11, ~01:45):** *"apk instalado, pode fechar o acervo e leia
a pasta analise"* — três coisas: confirmar o lote do app, encerrar o acervo
deixado em aberto desde 18/11 e ler `analise/`.

---

### 1. APK 1.46.1+2084 instalado

O dono confirmou a instalação do APK publicado em 19/11 (commit `2f88e98`).
Fecha o último passo do lote do Vigia da Rede: card admin-only no painel com
**Reconhecer**/**Bloquear** na tela do alerta e o fix que não republica o aviso
antigo ao tocar na notificação. Nada a fazer do lado do servidor — o app já
consome as rotas `/admin/vigia*` que estão no ar desde 19/11.

### 2. Acervo do Raul Seixas — fechado

**O que estava aberto (TODO de 18/11):** acompanhar os lotes restantes da
playlist, checar duplicatas e fechar o acervo com o dedupe endurecido da §4.

**O que a medição de hoje mostrou:**

| Item | Resultado |
|---|---|
| Unidade `od-radio-lista-raul` | terminou em **18/11 23:38**, `inactive` |
| Lotes | **19/19 com `codigo=0`**, `=== fim: 19 lote(s), 0 com falha, acervo 502 ===` |
| Arquivos × banco | **502 mp3 em `acervo/` = 502 linhas** no `acervo.db`; **0 caminho ausente** |
| Duplicatas exatas | **0** — sha256 das 502 faixas, nenhum par igual |
| Títulos repetidos | 14, **todos de artistas/gravações diferentes** (ex.: "Cicatrizes" Bruna Karla × Isadora Pompeo; "Pais e Filhos" Legião × Banda Rock Beats) |
| `.m3u` | regerados no fecho do pipeline (Eletrônica 9, Gospel 85, Internacional 19, MPB 35, Outros 265, Pop 26, Rock 56, Sertanejo 7, Mix 502) |
| AzuraCast | **504 arquivos = 502 faixas + 2 locuções** (`/api/station/nicky/files`), nowplaying OK |
| Raul Seixas | **1 → 141 faixas** no acervo |

**Quarentena do pipeline (38 arquivos, fora do acervo e fora do banco):** o
pipeline não apaga nem adivinha por desenho. Conferido por hash: **nenhum é
cópia do acervo**. São 25 gravações "(Ao Vivo)" do Raul que o dedupe endurecido
da §4 marcou como *parecidas* com a versão de estúdio, 4 cópias exatas antigas
em `revisar/duplicadas/`, 6 reprovadas (duração < 60 s / bitrate) e 3 nomes
ambíguos. Ficam como decisão do dono — checkbox novo no TODO.

### 3. `analise/` — o que há na pasta

A pasta tem **um único diretório, `No Break/`** (9 imagens, 14 MB); as pastas
`NV/` e `Projeti/` que existiam em 13/11 não estão mais lá. Conteúdo:

- **3 prints de 11/04/2026** (`com.mercadolibre`): anúncio do **Nobreak Intelbras
  Attiv 1200 VA Bivolt**, R$ 792,36 (47% off) / R$ 860,70 em 10×; a ficha diz
  1200 VA / 600 W, entrada 127/220 V, saída 127 V, topologia interativa, onda
  semissenoidal. **Não menciona USB em nenhum ponto.**
- **6 fotos de 28/04/2026** de um **Intelbras Attiv 1500 VA Bivolt aberto**:
  etiqueta traseira `HS: BI.A0008555344 · 1500 VA / 750 W · Entrada 120/220 V ·
  Saída 120 V · 60 Hz · Indústria Brasileira 26/11/25`; por dentro, **2 baterias
  12 V 7 Ah**, transformador com etiqueta `POTÊNCIA: 1500VA/Bivolt` (cód.
  cliente 1110086) e a placa de controle; 8 tomadas NBR 14136, **sem porta
  USB/serial**.

**Leitura técnica:** o equipamento que já existe segura queda e religa sozinho,
mas **não permite shutdown gracioso** — a linha Attiv não tem comunicação, e o
software de gerenciamento da Intelbras (com desligamento programável) só cobre
as linhas **com USB**. O datasheet do Attiv 1500 BI ainda desaconselha fontes
com PFC ativo, que é o caso de servidor. Ou seja: o item "nobreak com USB" do
plano de continuidade **continua em aberto**, e a compra precisa ser de um
modelo com porta USB/HID (para `upsc`/NUT) — o Attiv não vira monitorável com
software.

### 4. Estado e limites

- Nenhum código alterado; só documentação e registros. **Sem bump** (app segue
  **1.46.1+2084**, agora instalado).
- **Limites:** a instalação no celular é declaração do dono (não há como eu
  verificar o aparelho); a leitura do `analise/` é das imagens e das fichas
  públicas da Intelbras, não de um manual impresso da unidade dele.
- **Autor:** Freebuff (Buffy), 21/11. Arquivos: `docs/ANALISE_SISTEMA_TODO.md`,
  `iniciar/session.json`, `iniciar/ATRIBUICOES.md`, esta transcrição.

## §2 — Homebox em uso: o inventário físico real da Nicky

**Pedido do dono (21/11, ~02:05 e ~02:20):** *"existe uma ferramenta de
catálogo... está na hora de colocar para funcionar e você e OD começarem a
saber o que temos para planejar melhor a parte física de OD"* e, depois de
mandar o `txt.txt`, *"o que temos guarde no homebox"*.

### 1. O que era o catálogo

**Homebox v0.26.2**, container `od-homebox` em `127.0.0.1:8470` (também exposto
em `192.168.0.205:8470`). Estava no ar desde 17/10 só com as **2 peças do teste
de ligação** (Raspberry Pi 4 e ESP-01S com DHT22), sem uso real.

### 2. O que faltava no cliente

O modelo do Homebox tem **locais** (entidades de tipo `Location`, hierarquia
por `parentId`), tipos, tags e campos de compra/garantia/série — mas o cliente
só sabia criar nome, quantidade, tipo, tags, descrição, notas e preço.

- `integrations/homebox.py`: `locais()` (usa o filtro `isLocation=true` do
  fork), `_local_id()` (acha por nome sem caixa/acento e **cria** o local
  quando falta), e `criar/atualizar` ganharam `local`, `fabricante`, `modelo`,
  `serie`. Só `name/quantity/description/entityTypeId/parentId/tagIds` existem
  no `EntityCreate`; fabricante/modelo/série vão no **PUT completo** (que
  preserva os demais campos, apurado no swagger vivo).
- `homebox_locais`: action nova, catálogo **128 → 129**.
- 7 testes novos em `tests/test_homebox.py` (local existente/novo, recusa com
  `criar_local=False`, modelo/série por PUT, troca de local, action).

### 3. Inventário cadastrado (9 peças, 2 locais)

Fonte: **`txt.txt`** (resumo do plano solar de 21/11) + **medição da máquina**
(`hostnamectl`, `lscpu`, `free`, `lsblk`, `docker ps`) + fotos de
`analise/No Break/`.

| Local | Peça | Dados guardados |
|---|---|---|
| Nicky — Servidor | Dell OptiPlex 3040 (Nicky) | i5-6500, 7,7 GiB, Ubuntu 24.04.5, BIOS 1.20.1, ~40 W; HA já em Docker |
| Nicky — Servidor | SSD 256 GB SATA | MV256GB, série 2025090600135 |
| Nicky — Servidor | HD Seagate Expansion 1 TB (Arquivos) | série NAC5M7SZ, /mnt/Arquivos |
| Nicky — Servidor | HD Seagate Expansion 1 TB (Dados) | série NA46WE9A, /home/alex/dados |
| Nicky — Servidor | Raspberry Pi 4 | (peça antiga, só mudou de local) |
| Nicky — Servidor | ESP-01S com DHT22 | (peça antiga, só mudou de local) |
| Energia — Fase 1 | Bateria Felicity FLA12100 | 12,8 V 100 Ah, R$ 1.699, entrega 23–24/11, RS485/CAN, **nunca em série** |
| Energia — Fase 1 | Nobreak Intelbras Attiv 1500 VA BI | série BI.A0008555344, 1500 VA/750 W, sem USB |
| Energia — Fase 1 | PWM 30 A 12/24 V | R$ 44, nunca usado; 14,4/13,6/11,2 V e bateria antes do painel |

**Correção registrada:** o `txt.txt` diz "precisa instalar Home Assistant"; o
HA **já roda** aqui (container `homeassistant`), o que muda o próximo passo do
plano (é configurar, não instalar).

### 4. Prova viva e estado

- `homebox_status` → **9 itens, 10 locais, R$ 1.743** de valor cadastrado.
- `homebox_locais` lista os 2 locais novos ao lado dos 8 do seed.
- Gate completo **5530 passed / 19 skipped / 0 falha**; `od-core` reiniciado
  com o catálogo em **129 actions**.
- **Limites:** a bateria ainda não chegou (dados são da compra, não de
  etiqueta); o Pi 4 e o ESP-01S continuam sem modelo/série porque não foram
  medidos; preço do OptiPlex e do no-break não constam em lugar nenhum.
- **Autor:** Freebuff (Buffy), 21/11. Arquivos: `integrations/homebox.py`,
  `tools/actions/actions.py`, `tests/test_homebox.py`,
  `tests/test_actions_catalog.py`, `tests/test_capabilities.py`,
  `tests/test_mcp_od.py`, `tests/test_orchestrator.py`,
  `tests/test_orchestrator_action_registry.py`, `docs/CHANGELOG.md`,
  `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/`.

## §3 — Vigia de energia por inferência: aviso e desligamento gracioso

**Pedido do dono (21/11, ~02:50):** *"Montar o vigia de queda de energia por
inferência, com aviso e shutdown gracioso"* — continuação do pedido anterior
("monitor de no-break sem USB"), agora com o `txt.txt` na mão.

### 1. Por que inferência

O no-break é um **Attiv 1500 VA Bivolt sem porta de dados** (fotos de
`analise/No Break/`): não existe `upsc`, nem `hid`, nem serial. A bateria
Felicity tem RS485/CAN, mas ainda não chegou e exigiria adaptador. O que existe
hoje é a **rede da casa**: com a Nicky no no-break, a queda de energia derruba
os aparelhos da tomada enquanto o servidor continua vivo — o ARP mostra isso.

### 2. Como ficou

- `core/energia.py`: `Detector` (puro, relógio injetável) + `VigiaEnergia`.
  Estados **normal → suspeita → confirmada → desligando**.
  - suspeita: quórum de **60%** das âncoras sumidas por **3 ciclos** (20 s cada);
  - confirmada: **3 min** depois, aviso no Telegram com a carência;
  - desligando: **8 min** de carência → `systemctl poweroff`.
  - âncoras expiram em 30 min (celular que saiu de casa não vira "sumido").
  - se os aparelhos voltam em qualquer fase, volta a `normal` e avisa.
- **Permissão**: antes de desligar, `pkcheck` (o serviço roda como usuário
  comum). Sem a regra, **não desliga** — avisa no Telegram o comando exato.
  `runtime/setup/energia_polkit.sh` instala a regra (sudo, uma vez).
- **Desarmado** com `OD_ENERGIA_DESLIGAR=0`: só monitora e avisa.
- Ações `energia_status` e `energia_cancelar` (catálogo **131**), check
  `energia` no `/health`, aviso "cancelar: /executa energia_cancelar".

### 3. Prova viva

- Leitura real: **15 âncoras, 15 presentes, gateway 192.168.0.1 visto**,
  estado `normal`.
- `desligamento_autorizado()` → `{autorizado: False, motivo: "Authorization
  requires authentication..."}` — ou seja, o vigia **sabe** que não pode
  desligar e degrada o check em vez de falhar silencioso.
- Gate completo **5551 passed / 19 skipped / 0 falha**; 21 testes novos em
  `tests/test_energia.py` (estados, cancelamento por arquivo e por método,
  desligamento executado uma única vez, parsers de ARP/rota, health/actions).

### 4. Limites

- Isto **infere** a queda; não mede carga da bateria. Reinício de roteador
  produz o mesmo sumiço — por isso há 3 ciclos + 3 min de confirmação + 8 min
  de carência e o aviso antes de qualquer desligamento.
- **Desligamento ainda bloqueado pelo polkit** até o dono rodar o instalador
  uma vez com sudo (não tenho senha e não é meu lugar).
- A telemetria real (tensão/carga) virá do BMS da Felicity via RS485/CAN
  quando a bateria chegar e houver adaptador.
- **Autor:** Freebuff (Buffy), 21/11. Arquivos: `core/energia.py`,
  `runtime/launcher.py`, `runtime/setup/energia_polkit.sh`,
  `runtime/setup/od-energia.rules`, `tools/actions/actions.py`,
  `tests/test_energia.py` + contagens de catálogo, `docs/`.

## §4 — Modo colapso declarado (P1 nº 6) + polkit do vigia liberado

**Pedido do dono (21/11):** *"proximo do todo"* — o próximo item aberto de
maior peso era o **P1 nº 6 — modo colapso declarado**, único P1 da revisão de
17/11. No meio do turno o dono corrigiu uma afirmação minha: *"a senha do
servidor está no env e você tem acesso total ao SO"* — o `SUDO_PASSWORD` está
no `.env`; instalei a regra polkit do vigia de energia com ele.

### 1. Modo colapso

- `core/colapso.py` (novo): estado persistido em `data/colapso.json`,
  contador de **falhas seguidas de nuvem** (padrão 3, `OD_COLAPSO_FALHAS`),
  declaração manual que sobrevive à volta da nuvem e sonda TCP (1.1.1.1:443)
  só para revogar o colapso **automático** (2 sondas OK).
- Orquestrador: `_provider_bloqueado()` remove provedores de nuvem da cadeia
  **nos dois caminhos** (normal e streaming), falha/sucesso alimentam a
  contagem e `_finish()` prefixa a resposta com
  *"⚡ modo colapso — respondendo só com a IA local"*.
- Action `colapso` (`status|ligar|desligar`, catálogo **131 → 132**), check
  `colapso` no `/health` (degrada com o motivo) e loop de sondagem
  supervisionado no launcher.

### 2. Polkit do vigia de energia (correção)

- `printf "$SUDO_PASSWORD" | sudo -S bash runtime/setup/energia_polkit.sh` →
  regra instalada em `/etc/polkit-1/rules.d/49-od-energia.rules`.
- `pkcheck --action-id org.freedesktop.login1.power-off --process $$` → **rc=0**
  e `desligamento_autorizado()` → `{autorizado: True}`.
- **Meu erro:** eu tinha afirmado que não havia senha nem acesso root. Havia —
  no `.env`. O desligamento gracioso passa a valer após o restart (o processo
  antigo tinha cacheado `autorizado: false`).

### 3. Prova e estado

- Gate completo **5568 passed / 19 skipped / 0 falha**; 17 testes novos em
  `tests/test_colapso.py` (declaração automática/manual, sucesso não revoga
  manual, monitor revoga em 2 sondas, orquestrador pulando a nuvem e
  prefixando a resposta, action e health).
- **Sem bump** (1.46.1+2084); `od-core` reiniciado com **132 actions**.
- **Limites:** o colapso automático depende de falhas reais dos providers
  (não foi forçado contra a nuvem para não gastar cota); a sonda TCP mede
  internet, não se o provedor está com cota.
- **Autor:** Freebuff (Buffy), 21/11. Arquivos: `core/colapso.py`,
  `core/orchestrator.py`, `runtime/launcher.py`, `tools/actions/actions.py`,
  `tests/test_colapso.py` + contagens, `docs/`.

## §5 — Auto-registro do restart do `od-core` (regra 4)

**Pedido do dono (21/11):** *"Implementar o auto-registro de restart do od-core
no session.json"* — o item aberto no TODO desde 18/11 (o restart das 15:01 com
PID 220986 não entrou em `iniciar/` e o checkpoint seguinte o dava como
pendente).

### 1. Como ficou

- `core/registro_restart.py` (novo): no boot do modo `all`, grava em
  `iniciar/session.json` a chave **`restarts_od_core`** (lista dos últimos
  **30**) com **PID, commit, branch, horário, host, modo, usuário** e `motivo`
  quando `OD_RESTART_MOTIVO` está definido.
- `flock` no próprio arquivo + escrita no lugar (append-only): dois processos
  não se atropelam; JSON ilegível **não** é sobrescrito; qualquer erro vira
  aviso e o boot segue. Dedupe por PID evita linha repetida em reentrada.
- `runtime/launcher.py`: chamada no começo do `main()`, antes de OTel/DB.
- Desligável com `OD_REGISTRAR_RESTART=0`.

### 2. Prova viva

- 7 testes em `tests/test_registro_restart.py` (append, preservação do resto do
  arquivo, dedupe por PID, limite de 30, arquivo ausente, JSON inválido e
  motivo por ambiente).
- O restart deste próprio turno passa a ser a primeira entrada real — sem eu
  digitar nada no `session.json`.

### 3. Limites

- Só o modo `all` (o serviço) registra; execuções pontuais (`capabilities`,
  `--help`) não sujam o histórico.
- O `motivo` depende de quem reinicia exportar `OD_RESTART_MOTIVO`; sem ele, a
  entrada registra o fato (PID/commit/hora) e não a intenção.
- **Autor:** Freebuff (Buffy), 21/11. Arquivos: `core/registro_restart.py`,
  `runtime/launcher.py`, `tests/test_registro_restart.py`, `docs/`.
