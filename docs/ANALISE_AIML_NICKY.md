# Análise — `analise/AIML/` (o Nicky antigo em AIML)

**Data:** 22/10/2026 · **Pedido do dono:** analisar a pasta depositada em
`analise/AIML/` — "um dos primeiros Nicky que escrevi, acho que 2019 ou
antes, ele usava AIML e foi feito em Delphi" — para colocar no histórico
do site e ver o que pode ser incluído no sistema atual.

## 1. Inventário medido

**1406 arquivos · 338 MB**, distribuídos assim:

| Pasta | Conteúdo |
|---|---|
| `Original/` | 39 arquivos `.aiml` com **24.546 categorias** — os sets clássicos do ALICE em inglês (a base de todo AIML do mundo) |
| `OK/` | 15 arquivos já em português: `sistema.aiml` (30 cats), `basic.aiml` (24), lotes `nicky_nucleo_operacional_3..8` (10 cada). `nicky_core_operacional.aiml` está **vazio** com typo `encoding="TUF-8"` |
| `Traduz/` | Pipeline de lotes (dividir → normalizar → traduzir → unir) + `prompt.txt` com as instruções de tradução AIML→pt-BR (padrões MAIÚSCULOS sem acento, respostas em pt correto, sem categoria repetida, UTF-8) |
| `knowledge_en/` | 34 arquivos de conhecimento em inglês |
| `Nicky Desenvolvimento/` | 1190 arquivos — o coração do sistema antigo (ver §2) |

## 2. O Nicky antigo (PascAlice)

`Nicky Desenvolvimento/` guarda o que existia antes do Omega Drakon:

- **`PascAlice.exe`** — motor AIML compilado em Delphi (Pascal). **Sem
  fontes `.pas`/`.dpr` no material depositado** — o executável é a prova,
  o código-fonte não veio na pasta.
- **168 arquivos `.aiml`** e **19 `.py`** (ferramentas auxiliares).
- **66 logs de conversa** (`conversa/`, de 2022-05-30 a 2024-06-12) —
  o registro real de como o Nicky antigo respondia.
- Fotos do Nicky (a Interface na versão pré-Omega).

### A patologia medida nos logs

Formato do log: linha `HH:MM:SS -->`, fala do usuário `NOME: pergunta|en`,
fala do bot `Nicky: en|pt` (encoding corrompido — leitura com
`errors="replace"`). A amostra mostra o defeito clássico do ALICE
genérico: **"Bom dia" → "What kind of food do you like?"**,
**"oi" → "What's your sign?"** — devaneios em inglês porque o motor casava
categoria genérica do ALICE.

Esses 66 logs são hoje o **maior corpus de conversas reais** que existe
do projeto — e já são auditáveis: o auditor `core/chat_audit.py`
(extraído na mesma data, frente 1 deste bloco) extraiu **1065 turnos**
dos 66 arquivos e classificou os devaneios com justificativa
(`python -m core.chat_audit --fonte legado`).

## 3. O que pode alimentar o sistema atual

O que tem valor HOJE dentro do material:

1. **As respostas em português já traduzidas** (`OK/`, 134 categorias
   prontas + lotes do núcleo operacional) — são conhecimento do Nicky
   (identidade, operação), não do ALICE genérico. Podem virar
   conhecimento do RAG/Quick Responses, mas precisam de revisão: o
   próprio `nicky_core_operacional.aiml` está vazio (nunca foi gerado).
2. **O prompt de tradução** (`Traduz/prompt.txt`) — já resolve o
   gargalo de traduzir os 24.546 categorias do ALICE; se algum dia
   quiser o corpus inteiro em pt-BR, o pipeline está pronto.
3. **Os 66 logs** — viraram a base de medição do auditor de conversas
   (§2). São a memória de como o Nicky antigo respondia antes do
   Omega Drakon.
4. **A narrativa** — a pré-história do ecossistema, agora no site
   (`site/historico.html`, seção "Fase 0 · Pré-História").

O que NÃO entra no sistema: o `PascAlice.exe` (binário legado sem
fontes, inerte — guardado como artefato histórico), o ALICE genérico em
inglês (o sistema atual tem identidade própria; embedir 24 mil
categorias genéricas rebaixaria o Nicky de volta ao patológico visto
nos logs) e as fotos (ficam no material do Legado, regra 16).

## 4. Decisão

**Catalogar, não migrar.** O material fica íntegro em `analise/AIML/`
(regra 17), a narrativa foi para o histórico do site, e as 134
categorias pt-BR do `OK/` ficam disponíveis como candidatas a
conhecimento do RAG quando o dono quiser — decisão de conteúdo dele,
não minha.
