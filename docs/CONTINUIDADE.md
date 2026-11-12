# OMEGA DRAKON — PLANO DE CONTINUIDADE (RESISTIR AO COLAPSO)

> **Status:** Documento de Planejamento — v1
> **Data:** 2026-11-12
> **Origem:** `txt.txt` do dono (12/11): *"vários países pediram kits de 72
> horas... devemos nos preparar... faça o OD utilizar o máximo da internet
> enquanto ela está disponível e prepare-o para quando tudo colapsar... o que
> precisa ser feito? o que precisa ser comprado? o que precisa ser criado ou
> produzido?"*
> **Assinatura:** `OD // CORE`
> **Regra deste documento:** todo número aqui foi **medido** na máquina em
> 12/11 às 10h30 — nada de estimativa apresentada como certeza. Preços são
> faixas de mercado para orientar a compra, não cotações.

---

## 1. Princípio: soberania local com degradação declarada

O OD não precisa "sobreviver à internet acabar" — ele precisa **continuar
útil** quando a internet, a energia ou os dois falharem. Isso exige três coisas:

1. **O que dá para baixar, baixa AGORA.** Conteúdo, modelos, mapas e pacotes
   são bens perecíveis: só existem enquanto há rede.
2. **O que depende de nuvem precisa de substituto local**, e o substituto tem
   que ser **honesto**: se não sabe, diz que não sabe — nunca inventa (foi
   assim que o 3B local virou "criatura mitológica grega").
3. **A prontidão tem que ser medida, não sentida.** `readiness_report` (ação
   nova em 12/11) devolve o estado real: hoje **6/9**.

> **Pergunte no chat:** *"como está a prontidão?"* — a resposta vem do sistema,
> não do modelo.

---

## 2. Inventário medido (12/11/2026)

| Item | Estado real | Depende de internet? |
|---|---|---|
| Hardware | i5-6500, **7,7 GB RAM** (4,4 GB disponíveis), disco **232 GB — 76 GB livres (62,7% usado)** | não |
| Energia | **Nenhum UPS/bateria visível ao SO** (`/sys/class/power_supply` vazio) | — |
| Conhecimento offline | Kiwix com **2 ZIMs = 15,0 GB** (`wikipedia_en_all_mini`, `wikipedia_pt_all_mini_2026-05`) | não |
| IA | local `qwen2.5-coder-3b` (llama.cpp :8081) + Gemini/Groq na nuvem | **parcial** |
| Voz | `whisper ggml-base` local (STT) | não |
| Serviços | **11 containers**: Kiwix, Stirling PDF, FileBrowser, Calibre-Web, FlatNotes, Vaultwarden, Homebox, IT-Tools, CyberChef, AzuraCast, Home Assistant | não |
| Dados | Postgres 16 local; `data/` 517 MB (checkpoints 7,5 MB, memória, rádio) | não |
| Backup | pasta `backups/` com histórico de APK + `auto/` (último arquivo há **7 h**) — **tudo na mesma máquina** | não |
| Comunicação | Telegram (API na nuvem), chat web/API **só na LAN**, Tailscale com **0 nós online além deste** | **sim** |
| Malha privada | Tailscale: 5 nós cadastrados, todos offline (327, 164, 28, 3 dias) | coordenação na nuvem |
| Rádio | `ffplay` + `pactl` local, stream do AzuraCast local | não |
| Casa | Home Assistant local (switches, luzes, clima) | não |
| Nuvem | 3 chaves de IA no `.env` (Gemini, Groq, OpenAI) — só o Gemini com cota livre | **sim** |

**Leitura:** o núcleo de dados já é local (bom). O que **quebra** no colapso é
**energia** (sem UPS), **comunicação** (Telegram é o único canal e vive na
nuvem) e **acervo** (15 GB é uma fração do que dá para ter).

---

## 3. O que fazer AGORA, enquanto a internet existe (0–7 dias)

### 3.1 Baixar acervo offline (cabe nos 76 GB livres)

Ordem de valor para sobrevivência — biblioteca Kiwix (`.zim`), da
[download.kiwix.org/zim](https://download.kiwix.org/zim/):

| Acervo | Por que primeiro | Tamanho aprox. |
|---|---|---|
| `wikipedia_pt_all_nopic` (completa, sem imagens) | 1 M+ artigos em PT, base de tudo | ~25 GB |
| `wikimed` / `wikipedia_pt_medicine` (WikiMed) | primeiros socorros, doenças, medicamentos | 1–3 GB |
| `wikihow_pt` / `wikihow_en` | reparo, plantio, construção, receitas | 1–5 GB |
| `ifixit` / `based.cooking` / `appropedia` | conserto de eletrônicos, comida, tecnologia apropriada | 1–4 GB |
| `gutenberg_pt` / `gutenberg_en` | literatura e manuais clássicos | 5–60 GB (escolher) |
| Mapas: `Organic Maps` (região Sul/BR) ou PMTiles do estado | navegar sem GPS online | 1–8 GB |
| Manuais do próprio OD (docs/, `knowledge/`) | operar o sistema sem assistência | < 1 GB |

**Meta mínima:** 40 GB de acervo baixado e **verificado** (abrir no Kiwix).
Hoje: 15 GB. **Faltam ~25 GB.**

### 3.2 Modelos locais melhores (hoje o local é 3B — o mais fraco da cadeia)

- Testar `Qwen2.5-7B-Instruct` q4_K_M (~4,4 GB) — cabe nos 7,7 GB de RAM com
  `-c 4096`. Ganho real de qualidade sobre o 3B; medir com o mesmo benchmark
  de 11/11 antes de trocar.
- `whisper small` (~500 MB) para transcrição melhor sem rede.
- Guardar os `.gguf` **e** o binário do llama.cpp no mesmo diretório de acervo.

### 3.3 Pacotes e imagens (reinstalar sem internet)

- `pip download -r requirements.txt -d vendor/pip` (~1 GB).
- `docker save` das 11 imagens em uso (~3–5 GB) + os `compose` no repo.
- `apt` não vale o esforço agora (espelho completo é caro); priorizar o que o
  OD usa em Python/Docker.

### 3.4 Credenciais e dados que só existem aqui

- Exportar o cofre do Vaultwarden (JSON criptografado) para **mídia offline**
  (pendrive/SSD guardado fora da máquina).
- Snapshot do Postgres + `data/` **fora da máquina** (hoje o backup é local).
- Imprimir (papel!) a folha de contatos e o runbook da §6 — colapso não pede
  senha, mas pede bateria.

---

## 4. O que comprar (em ordem de risco, não de preço)

> Faixas aproximadas em BRL (11/2026) só para dimensionar a decisão.

### Fase 1 — o que dói primeiro (essencial, ~R$ 2.000–3.500)

| Item | Por que | Faixa |
|---|---|---|
| **Nobreak 1200–1500 VA com USB** (senoidal) | apagão hoje desliga o servidor no meio da escrita; com USB o OD faz shutdown gracioso e volta sozinho | R$ 700–1.200 |
| **1 SSD externo 1 TB** | primeira cópia **fora** da máquina (hoje não existe) | R$ 400–700 |
| **Roteador 4G/5G + chip de dados** | internet alternativa quando o cabo/ISP cair | R$ 400–900 (+ plano) |
| **Pendrive/SSD criptografado pequeno** | cofre de senhas + documentos fora da casa | R$ 80–200 |

### Fase 2 — comunicação que não depende de nuvem (~R$ 600–1.500)

| Item | Por que | Faixa |
|---|---|---|
| **2 rádios LoRa Meshtastic** (com antena) | mensagem de texto por rádio, **sem operadora e sem internet**, 2–15 km conforme terreno | R$ 250–450 cada |
| **Nobreak pequeno para o roteador** | manter a malha viva mesmo com a casa sem luz | R$ 200–400 |

> Alternativa de software antes de comprar: segundo nó (notebook/PC) na LAN
> com `ntfy`/Matrix local + PWA offline. **Custo zero** e resolve casa↔quintal.

### Fase 3 — energia e acervo maiores (R$ 4.000–10.000)

| Item | Por que |
|---|---|
| **Painel solar 400–600 W + controlador MPPT + bateria LiFePO4 100 Ah** | dias de autonomia para o servidor + roteador (consumo medido: ~60–100 W) |
| **HD externo 4 TB** (ou 2×2 TB) | acervo completo (Wikipédia PT com imagens, mapas, Gutenberg) |
| **Segundo SSD de backup rotativo** | ciclo 3-2-1 sem sobrescrever a única cópia |

### Não comprar ainda

- Servidor reserva / mini PC extra: o gargalo hoje **não é CPU**, é energia e
  comunicação. Um segundo servidor sem UPS só multiplica o problema.
- Antena/radioamador (HF/VHF) sem licença e sem operador: LoRa resolve o caso
  de uso do dono com muito menos custo e nenhuma burocracia.

---

## 5. O que criar/produzir em software (ordem sugerida)

| # | Entrega | Estado | Ganho |
|---|---|---|---|
| 1 | **`readiness_report`** — prontidão medida no chat | ✅ **FEITO 12/11** | transforma "estamos preparados?" em número |
| 2 | **Modo colapso declarado** — ao perder a internet (ou por ordem), o OD troca a cadeia para o local, avisa no chat/UI e para de tentar nuvem | a fazer | fim da espera de 429/timeout e do silêncio |
| 3 | **Fila de download de acervo** (resumable, progresso por SSE, dedup — padrão NOMAD) | a fazer | baixar os 25 GB sem perder progresso |
| 4 | **Mapas offline integrados** (PMTiles + página no site/app) | a fazer | navegar sem rede |
| 5 | **RAG de campo** — manuais (PDF/DjVu) em `knowledge/` com citação de página | a fazer | "como tratar queimadura?" respondido da fonte |
| 6 | **Backup verificado + offsite** (restauração testada; cópia em SSD/pendrive) | a fazer | colapso deixa de significar perda |
| 7 | **Espelho de pacotes** (pip/Docker) no host | a fazer | reinstalar o OD sem internet |
| 8 | **Ponte LoRa ↔ OD** (Meshtastic → MQTT local → action de mensagem) | a fazer (depende da Fase 2) | comunicação sem operadora |
| 9 | **Kit 72 h no app** — checklist com validade, água, comida, remédios, documentos | a fazer | o "kit de 72 horas" com inventário e alerta de vencimento |
| 10 | **Monitor de UPS** (`upsc` → `/health` + shutdown gracioso) | a fazer (depende da Fase 1) | apagão não corrompe mais nada |

---

## 6. Runbook — "modo colapso" (o que fazer, em ordem)

**Primeiros 10 minutos**

1. Confirmar o escopo: só internet caiu, só energia caiu, ou os dois?
2. Internet fora: o OD já responde pelo local (`qwen2.5`); conferir
   `readiness_report` para saber o que ficou mudo.
3. Energia fora: desligar containers não essenciais (Stirling, CyberChef,
   Calibre, Azuracast) para esticar a bateria; manter OD + roteador.
4. Avisar a rede: mensagem no canal alternativo (LoRa ou nó LAN).

**Primeira hora**

5. Backup imediato do Postgres + `data/` para o SSD (antes de qualquer
   tentativa de conserto).
6. Se a energia voltou instável, religar só o essencial e monitorar.

**24 horas**

7. Consultar o acervo offline (Kiwix) em vez de tentar internet.
8. Registrar no `iniciar/` o que funcionou e o que faltou — vira backlog.

**72 horas**

9. Racionar energia por prioridade: OD core → roteador → restante.
10. Revisar a prontidão: cada item que reprovou é uma compra ou uma tarefa.

---

## 7. Decisões que dependem do dono

1. **Energia:** comprar o nobreak com USB (Fase 1) — sem ele, todo o resto é
   frágil.
2. **Comunicação:** LoRa (rádio, sem operadora) **ou** 4G/5G (depende de
   operadora, mas alcança longe)? Sugestão: os dois, LoRa primeiro pelo custo.
3. **Acervo:** quais ZIMs entram nos 40 GB (Wikipédia PT completa + WikiMed +
   WikiHow + mapas é o mínimo defensável).
4. **Offsite:** onde guardar a cópia fora da máquina (casa de familiar, cofre,
   trabalho) — o local importa mais que a mídia.
5. **Modo colapso automático:** o OD deve trocar sozinho para local após N
   falhas de nuvem, ou só quando o dono mandar?

---

## 8. Resumo em uma frase

Já somos **locais em dados e serviços** (6/9 na prontidão); faltam **energia
com UPS**, **um canal de comunicação que não passe pela nuvem** e **25 GB de
acervo** — e, enquanto a internet existe, o relógio corre a favor de baixar,
não de decidir.

**Sem bump:** app segue **1.44.0/2080** (ação nova de servidor; nada de app).
