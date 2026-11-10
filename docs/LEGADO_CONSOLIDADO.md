# Legado Omega Drakon — Consolidação Canônica

> **Fonte única de verdade para identidade, história e autenticidade do ecossistema Omega Drakon.**
> Este documento aponta para as fontes canônicas no diretório `/home/alex/Legado/` (o "Legado").
> **Nada aqui é cópia** — são referências indexadas. O canônico vive no Legado; este arquivo é a bússola.

---

## 1. Núcleo da Marca (VIVO — canônico atual)

**Localização:** `/home/alex/Legado/OMEGA_DRAKON/`

| Área | Arquivo(s) chave | Descrição |
|------|------------------|-----------|
| **Identidade Visual** | `01_NUCLEO_DA_MARCA/Identidade_Visual/MANUAL_IDENTIDADE_VISUAL_v1.md` | Manual oficial: cores, tipografia, logos, símbolos, uso correto/incorreto |
| **Códice da Marca** | `01_NUCLEO_DA_MARCA/01_CODICE_MARCA.md` | Posicionamento, propósito, valores, promessa, personalidade |
| **Símbolos Oficiais** | `01_NUCLEO_DA_MARCA/Simbolos_Oficiais/` | `Logo da Omega Drakon.png`, `simbolo_minimo_OD.png`, `Retrato Futurista.png` |
| **Comunicação Aprovada** | `05_COMUNICACAO/Textos_Aprovados/` | Textos canônicos para site, app, docs, releases |
| **Estratégia de Voz** | `05_COMUNICACAO/ESTRATEGIA_DE_VOZ.md` | Tom de voz, princípios de escrita, exemplos |
| **Protocolo de Autenticidade (MoC/NV)** | `06_REGISTRO_MESTRE/` | Registro Mestre de peças, MoC (Mark of Custody), NV Protocol |
| **Numeração Oficial** | `02_NUMERACAO/` | Versionamento SemVer, versionCode, regras de bump |

**Regra:** Qualquer decisão sobre identidade visual, tom de voz, produtos, autenticidade ou história do ecossistema **deve passar por aqui** antes de ser inventada.

---

## 2. Consolidações Técnicas Canônicas (2026-08 — Google Drive)

Estes 4 documentos no Google Drive (`OmegaDrakon` / `OD`) resumem as 26+23+23 fontes do Legado:

| Documento | Conteúdo | Cópia local equivalente |
|-----------|----------|-------------------------|
| `OMEGADRAKON_SPEC.md` | Especificação técnica completa do sistema | `docs/OMEGADRAKON_SPEC.md` |
| `OMEGA_DRAKON_SOURCE_MAP.md` | Mapa de todas as fontes do Legado (bit a bit) | — |
| `NICKY_VIRTHY_KNOWLEDGE.md` | Conhecimento consolidado da assistente predecessora | `knowledge/` |
| `CONTROL_BRIDGE.md` | Ponte de controle entre sistemas legados e atuais | — |

---

## 3. Projetos Históricos (absorvidos — não são norma vigente)

| Projeto | Período | O que era | Status |
|---------|---------|-----------|--------|
| **Nicky Virthy** | 2025-01 → 2026-02 | Primeira assistente pessoal (v0.1 → v0.3.9) + pacote de marca original | Histórico |
| **Nicky** | 2026-02 → 2026-07 | Continuação: PWA, `/codigo` agêntico, STT/TTS (v0.4 → v0.7) | Histórico |
| **NV (Runtime Cognitivo)** | 2026-07 → 2026-08 | Reescrita arquitetural v1.11: tool runtime, security layer, workflows | Histórico |
| **Nexus** | 2026-07 → 2026-08 | Monitor de casa/servidor (HA, MariaDB); berço da **Plêiade** (7 perfis) | Histórico |

**Linha do tempo:**
1. 2025-01 — Nicky Virthy v0.1 (já com marca Omega Drakon)
2. 2026-02-02 — Manifesto OD selado, Registro Mestre criado, núcleo oficial
3. 2026-04→07 — Nicky v0.3 → v0.7 (servidor próprio, voz, agêntico)
4. 2026-07→08 — Nexus (Plêiade) e NV Runtime v1.11 em paralelo
5. 2026-08 (fim) — Consolidações canônicas no Drive (4 docs)
6. 2026-09 — Absorção total no **OmegaDrakon v1.0** (projeto atual, Git)
7. 2026-10 — v1.21.2 no ar; site institucional do ecossistema publicado

---

## 4. Mapa de Duplicações (medido bit a bit — 09/10/2026)

**Nada foi apagado.** Inventário para limpeza futura segura (só com backup + confirmação do dono — regra 9).

### 4.1 Pares IDÊNTICOS (sha256 igual — cópias exatas)
| Arquivo A | Arquivo B |
|-----------|-----------|
| `OMEGA_DRAKON/05_COMUNICACAO/ESTRATEGIA_DE_VOZ.md` | `…/ESTRATEGIA_DE_VOZ 1.md` |
| `OMEGA_DRAKON/01_NUCLEO_DA_MARCA/01_CODICE_MARCA.md` | `…/1. Posicionamento da Marca.md` |
| `Nicky Virthy/Servidor Dell.md` | `Nicky Virthy/Servidor Dell(1).md` |
| `Nicky/docs/Docs/ARCHITECTURE.md` | `Nicky/docs/Docs/ARCHITECTURE(1).md` |

> **Candidatos seguros a remoção** (custo de manter = zero). Ainda assim: só mediante confirmação.

### 4.2 Pares/Grupos DIVERGENTES (versões de eras diferentes — NÃO são cópias)
| Documento | Onde aparece | Natureza |
|-----------|--------------|----------|
| `PROCEDIMENTO OFICIAL DE FECHAMENTO.md` | `NV/docs` × `Nexus/docs` | versões diferentes |
| `Regras de Trabalho.md` | `NV/docs` × `Nexus/docs` | versões diferentes |
| `MILESTONE.md`, `CHANGELOG.md`, `FOUNDATION.md`, `PROMPT_CONTINUIDADE.md` | `Nicky/docs` × `NV/docs` | changelogs/estados de eras diferentes |
| `Nicky Virthy.txt` | `NV/docs` × `Nexus/docs` (`.md`) | textos diferentes sobre a mesma entidade |
| `NICKY_v040_PROMPT.md (2)` · `NICKY_v070_PROMPT (2)` | `Nicky Virthy/` · `Nicky/docs/Docs/` | variantes de prompt da mesma versão |
| `regras_nexus.md` × `regras_nexus 1.md` | `Nexus/docs/` | versões diferentes (1786 B vs 934 B) |
| `ativar venv.md` | 3 versões em 3 pastas | cada uma descreve o ambiente da sua era |

**Conclusão:** As "duplicatas" são **camadas geológicas** — o mesmo documento vivendo fases diferentes. Apagar qualquer um seria perder histórico. Se organizar no futuro: índice/merge consciente, nunca remoção.

---

## 5. ⚠️ AVISO DE SEGURANÇA (permanente)

Documentos antigos do Legado (principalmente `Nicky/docs/Docs/POST_TRANSFER_CHECKLIST.md` e afins) contêm **segredos em texto puro**:
- Token de bot Telegram antigo
- Chave Gemini
- Senhas de MariaDB / Home Assistant
- IP e chaves de acesso

**NUNCA** copiar esses valores para o repositório, site ou novos documentos. Credenciais vivas estão no `.env` do projeto atual.
**Recomendação registrada:** rotacionar esses segredos quando o dono decidir.

---

## 6. O que NÃO fazer com o Legado

1. **Não apagar nada** sem backup + confirmação do dono (regra 9 da sessão).
2. **Não tratar documento histórico como norma vigente** — o cânone da marca é `OMEGA_DRAKON/`; o cânone do software é o Git (`/home/alex/OmegaDrakon`).
3. **Não migrar segredos** (§5).
4. Se a pasta for movida/reorganizada, atualizar **este documento** e `docs/ANALISE_ECOSSISTEMA.md` — são as duas bússolas do Legado.

---

## 7. Referências Cruzadas no Projeto Atual

| No projeto atual | Origem no Legado |
|------------------|------------------|
| `docs/REGRAS_DE_TRABALHO.md` | Derivado de `NV/docs/Regras de Trabalho.md` + `Nexus/docs/Regras de Trabalho.md` |
| `docs/VERSIONAMENTO.md` | Derivado de `OMEGA_DRAKON/02_NUMERACAO/` |
| `site/` (identidade visual) | `OMEGA_DRAKON/01_NUCLEO_DA_MARCA/Identidade_Visual/` |
| `agents/profiles.py` (Plêiade) | `Nexus/docs/Personagens.md` (fonte dos 7 perfis) |
| `core/identity.py` (Registro Mestre) | `OMEGA_DRAKON/06_REGISTRO_MESTRE/` |
| `docs/CHANGELOG.md` | Continuidade do `NV/docs/CHANGELOG.md` |

---

## 8. Como usar esta consolidação

- **Para decisões de marca/identidade:** Comece pelo §1 (núcleo vivo).
- **Para entender a história técnica:** Leia §2 (consolidações 2026-08) + §3 (linha do tempo).
- **Para limpeza futura:** Use §4 (mapa de duplicações medido bit a bit).
- **Para auditoria de segurança:** §5 (avisos de segredos no Legado).
- **Para desenvolvimento:** §7 (referências cruzadas — onde o código atual bebe da fonte).

---

**Assinatura:** OD // CORE  
**Criado em:** 2026-11-09  
**Baseado em:** `/home/alex/Legado/00_MAPA_DO_LEGADO.md` (índice vivo vs histórico)  
**Próxima revisão:** Quando houver mudança no núcleo da marca ou reorganização do Legado.