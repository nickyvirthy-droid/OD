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
