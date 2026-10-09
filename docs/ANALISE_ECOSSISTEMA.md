# OMEGA DRAKON — ANÁLISE DO ECOSSISTEMA E DO LEGADO

> **Finalidade:** análise profunda, didática e profissional de todo o ecossistema
> Omega Drakon a partir do Legado (`/home/alex/Legado`, 217 arquivos, 93 MB,
> 5 raízes) e das consolidações canônicas do Google Drive — base para o site
> institucional (entregue em 2026-10-09, v1.21.2) e para a discussão de
> implementação das frentes que ainda não existem no sistema atual.
> **Assinatura:** `OD // CORE` · **Data:** 2026-10-09
> **Fontes:** Legado local (5 raízes) · Drive (`OMEGADRAKON_SPEC.md`,
> `OMEGA_DRAKON_SOURCE_MAP.md`, `NICKY_VIRTHY_KNOWLEDGE.md`, `CONTROL_BRIDGE.md`)

---

## 1. Sumário executivo

O Legado responde **o que a Omega Drakon é quando não é só um app**. O sistema
atual em `/home/alex/OmegaDrakon` é a materialização madura de **uma** das
frentes do ecossistema — o software (Omega Drakon · Systems). O ecossistema
completo tem **cinco frentes** (marca-mãe, Systems, FAB, Living Systems e
Nicoly Valentina), um protocolo de autenticidade físico-digital (Mark of
Continuity), uma numeração canônica de itens e uma voz institucional própria.

O novo site institucional (`site/index.html`, v1.21.2) traduz tudo isso.
Este documento guarda a análise que o sustenta e lista as **divergências** a
serem discutidas com o dono antes de implementar as frentes ausentes.

---

## 2. Núcleo da Marca (didática: por que existe uma marca antes do produto)

- **Nome:** OMEGA DRAKON (marca) / OmegaDrakon (produto de software).
- **Tríade canônica (regra de ouro):** *Omega Drakon é o sistema. Nicky Virthy
  é a voz. Alex Projeti é o arquiteto.* Toda criação se valida contra essa
  tríade — sem ela, não é do ecossistema.
- **Propósito:** "Criar sistemas e objetos com identidade, rastreabilidade e
  significado real." Axiomas: *Ordem sobre o caos* · *Soberania técnica*.
- **Assinaturas:** mestra `OD // CORE`; código segue `__signature__ = "OD // CORE"`;
  logs `[NICKY][INFO|WARN|CRIT]`; selo físico `OD` obrigatório em todo item.
- **Símbolos oficiais** (`01_NUCLEO_DA_MARCA/Simbolos_Oficiais/`):
  `Logo da Omega Drakon.png` (cabeça de dragão estilizada em círculo —
  vigilância, autonomia, controle; 1024×1024), `simbolo_minimo_OD.png`
  (monograma ΩD), `Retrato Futurista.png` (avatar canônico de Nicky Virthy).
- **Identidade visual (manual v1):** Preto Profundo `#0A0A0A` · Azul Elêtrico
  `#0088FF` · Grafite `#2C2C2C` · Branco Técnico `#F2F2F2` · Vermelho Alerta
  `#FF0000` (exclusivo `[CRIT]`). Tipografia Montserrat/Orbitron, títulos em
  caixa alta, kerning ampliado. Proibido: cartoon, manuscrito, distorção do selo.
- **Voz:** Formal Técnico (Técnico + Inspirador); terceira pessoa ("o sistema
  está pronto"); sem emojis, gírias ou exclamações — o NICKY PROTOCOL.
- **Manifesto selado:** 02/02/2026, assinatura `OD // CORE`. Página "Sobre"
  aprovada em `05_COMUNICACAO/Textos_Aprovados/sobre.md` (hoje no site).

## 3. As cinco frentes do ecossistema

| Frente | Escopo | Estado real |
|---|---|---|
| **OMEGA DRAKON** (mãe) | Governo da identidade, numeração, Registro Mestre | Ativo (documentos + site) |
| **· SYSTEMS** | Software: plataforma soberana, app, chat, bot, IoT | **Em produção** (v1.21.2 no ar) |
| **· FAB** | Manufatura: 3D/resina, laser 0,1 mm, CNC, protótipos | Estrutura prevista (`DICIONARIO_FAB.md`), sem produção |
| **· LIVING SYSTEMS** | Paludários, dioramas, ecossistemas monitorados | Conceitual (narrativa da marca) |
| **NICOLY VALENTINA** | Semi-joias autorais, ciclos fechados, selo laser | Protocolo pronto (`PROTOCOLO_NV.md`), 1º lote "em criação" |

### 3.1 Autenticidade (a ponte entre o digital e o físico)

- **Mark of Continuity (MoC) v1.0:** UID `OD-[CATEGORIA]-[ANO]-[SEQ]` (seq hex),
  gravação laser 0,1 mm, esteganografia, validação pela Interface.
- **Protocolo NV (semi-joias):** assinatura `OD // NV – SIGIL`, ID `NV-[COL]-[HASH]`
  (ex.: `NV-ABI-7F3A`), micro-gravação 2–5 mm, QR para registro privado.
- **Registro Mestre:** todo item produzido é registrado (data, coleção, lote,
  estado). Ciclos fechados = encerrados, nunca reeditados.
- **Coleções previstas:** ABISSAL, DRAKONIS, LUMEN NOX (sigilos prontos).
- **GAP:** a voz da marca promete `/verificacao` no site — **não existe hoje**.

## 4. Histórico (a linhagem, didaticamente)

1. **2025-01 — Nicky Virthy v0.1:** assistente pessoal (FastAPI + Telegram +
   LLM local) já batizada com a marca Omega Drakon. A marca antecede o software.
2. **2026-02-02 — Selamento:** Manifesto, Registro Mestre (4 itens) e núcleo
   documental oficial.
3. **2026-04 — Servidor próprio:** Dell Ubuntu 24.04 (192.168.0.250) — soberania
   de hardware desde o início.
4. **2026-05 a 07 — Nicky v0.4 → v0.7:** PWA, `/codigo` agêntico, STT/TTS.
5. **2026-07 — Nexus (a Sétima Entidade):** entidade paralela de monitoramento
   (Home Assistant, MariaDB, llama.cpp) e a **Plêiade** completa (Nexus, Nicky
   Virthy/Guardian, Regulus, Luma, Vox, Athenae, Nyx).
6. **2026-08 — NV Runtime:** reescrita arquitetural modular (Foundation →
   Coder → Sandbox → Tool Runtime → Security → Workflows → API), homologado
   v1.11.0 com 48/48 testes.
7. **2026-08 (final) — Consolidação documental:** Source Map, Spec oficial e
   Knowledge de Nicky Virthy canônicos (também no Drive).
8. **2026-09 — OmegaDrakon v1.0:** absorção de tudo em arquitetura limpa
   (`docs/ROADMAP_ABSORCAO.md` — 37/37 capacidades) — o projeto atual.
9. **2026-10 — Hoje:** v1.21.2 no ar, 42 capabilities, 78 actions, app com
   auto-atualização verificada e site institucional do ecossistema inteiro.

## 5. Projetos predecessor — o que é cada um

- **`Nicky Virthy/`** — a raiz dupla: assistente pessoal **e** pacote de marca
  (manual de identidade, templates, prompts v0.3.9/v0.4.0).
- **`Nicky/`** — continuação da mesma linha (v0.6.0/v0.7.0), PWA e voz; repo
  `github.com/nickyvirthy-droid/NV`.
- **`NV/`** — "Nicky Virthy Runtime Cognitivo Modular": a reescrita que gerou o
  esqueleto do sistema atual (tool runtime de 56 actions, security layer,
  workflows).
- **`Nexus/`** — entidade paralela, monitor de casa/servidor, berço da Plêiade.

**Duplicações e cruzas a organizar (pedido do dono):**

| Conteúdo duplicado | Onde aparece |
|---|---|
| `PROCEDIMENTO OFICIAL DE FECHAMENTO.md`, `Regras de Trabalho.md`, `Regra Prompt.md` | `NV/docs` **e** `Nexus/docs` |
| `MILESTONE.md`, `CHANGELOG.md`, `PROMPT_CONTINUIDADE.md`, `FOUNDATION.md` | `Nicky/docs` **e** `NV/docs` |
| `Nicky Virthy.txt/.md` | `NV/docs` ≈ `Nexus/docs` |
| `ativar venv.md` (3 variantes) | `Nicky`, `NV`, `Nexus` |
| `README.md` com sufixos `(1)`, `(2)` | `Nicky/docs/Docs`, `Nicky Virthy` |
| `ESTRATEGIA_DE_VOZ.md` + ` 1.md` | `05_COMUNICACAO` |
| Códice de Marca em 2 nomes | `01_CODICE_MARCA.md` ≡ `1. Posicionamento da Marca.md` |
| Pacote Único / Templates / Manual de Identidade | `.md` em `Nicky Virthy` ≡ `.docx` em `06_HISTORICO/111` |

**Google Drive:** o Legado do Drive é **mais pobre** que o local para as raízes
de projeto (só existem as pastas `OD` e `OmegaDrakon`; `Nicky Virthy`, `Nicky`,
`NV` e `Nexus` não estão lá). O que o Drive agrega são as **consolidações
canônicas de 29/08** (Spec, Source Map, Knowledge, Control Bridge) — já
refletidas neste documento.

## 6. Divergências Legado × sistema atual (pauta de discussão)

| # | Tema | Legado | Sistema atual | Sugestão |
|---|---|---|---|---|
| 1 | Cores | `#0A0A0A` + `#0088FF` | site antigo: navy `#0d1b3e` + âmbar `#f59e0b` | **Resolvido** no site novo (identidade oficial) |
| 2 | Fonte | Montserrat/Orbitron | Inter | **Resolvido** no site novo |
| 3 | Símbolo | Logo oficial (ΩD) | emoji 🐉 | **Resolvido** em todas as superfícies (v1.21.2) |
| 4 | Escopo do site | Ecossistema inteiro | só o app | **Resolvido** no site novo |
| 5 | Nome | "Omega Drakon" | "OmegaDrakon" | Manter "Omega Drakon" na marca e "OmegaDrakon" no produto (decidir com o dono) |
| 6 | Plêiade | Nicky=Guardian **e** Nexus=Sétima Entidade | 7 perfis (Nexus incluso como 7º) | Alinhado; formalizar no `Personagens.md` canônico |
| 7 | Ações | 56 (NV Runtime) | 78 | Atual; números do site agora vêm do sistema real |
| 8 | Banco | MariaDB 10.11 (Legado) | PostgreSQL (em produção) | **Resolvido**; MariaDB é só do Nexus legado |
| 9 | ID de itens | 2 formatos incompatíveis (SKU 5 campos × MoC 4 campos hex) | — | Unificar num único formato antes das semi-joias |
| 10 | Fundação | "2026" (`sobre.md`) × marca integrada em 2025-01 | — | Site usa "Fundação: 2026" (marca) e 2025 (linha do tempo do software) |
| 11 | Ortografia | "NICOLHY/NICOLY/Nicoly Valentina" | — | Fixar **Nicoly Valentina** |
| 12 | Versão do Nexus | v1.3.0 × v1.9.1 × v1.9.2 | — | Histórico apenas; sem ação |
| 13 | `/verificacao` | Prometida pela voz da marca | não existe | **Implementar** (frente de discussão) |
| 14 | FAB / Living Systems / Semi-joias | protocolos prontos | nada no sistema | **Implementar** módulos quando o dono decidir |
| 15 | Segredos no Legado | tokens/senhas em texto puro nos docs | — | **VERIFICADOS 09/10: bot antigo @Nexus_Nicky_bot e chave Gemini AINDA ATIVOS.** Decisão do dono: rotacionar somente após finalizar todos os testes (em produção). Nunca migrar ao site |

## 7. O que já foi entregue nesta rodada (v1.21.2)

1. Site institucional completo do ecossistema (`site/index.html` + `site/assets/`).
2. Fim do 🐉: chat web, painel, admin, `/capabilities`, respostas de identidade
   e app (login, boas-vindas, chip guardian, selo) com o logo oficial.
3. Regra 16: `/home/alex/Legado` como referência obrigatória da sessão.
4. Este documento — base da próxima discussão.

## 8. Próximos passos (discussão com o dono)

1. **Organização do Legado** — proposta: mover as 4 raízes de projeto para
   `Legado/HISTORICO/`, deduplicar os documentos cruzados (tabela §5) e manter
   `OMEGA_DRAKON/` como núcleo vivo. Só após confirmação (regra 9).
2. **`/verificacao`** — página pública de autenticidade (ler ID gravado,
   consultar Registro Mestre). Requer decidir onde vive o registro (Postgres).
3. **Frentes FAB / Living Systems / Nicoly Valentina** — primeiro passo seria
   o Registro Mestre digital no sistema (já que semi-joias sem registro não
   existem pela própria regra da marca).
4. **Unificação do formato de ID** (linha 9 da tabela §6).
5. **Rotação dos segredos vazados no Legado** (linha 15) — **VERIFICADO 09/10:
   bot antigo `@Nexus_Nicky_bot` e chave Gemini seguem ATIVOS** (getMe OK /
   HTTP 200). Decisão do dono (09/10): rotacionar somente quando todos os
   testes estiverem finalizados — registrados como pendência ativa.
