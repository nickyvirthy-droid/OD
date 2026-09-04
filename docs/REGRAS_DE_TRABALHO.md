# OMEGADRAKON — REGRAS DE TRABALHO (Working Agreement)

> **Status:** Documento Normativo — vigente
> **Data:** 2026-09-03
> **Finalidade:** Definir o que significa "concluído" no OmegaDrakon e como
> **qualquer pessoa (humano ou agente)** pode verificar se o trabalho foi
> executado corretamente. Nada é "feito" sem evidência verificável.
> **Assinatura:** `OD // CORE`

---

## 1. Princípio Fundamental

> **"Feito" é o que a evidência comprova — não o que se afirma.**

Todo trabalho entregue no OmegaDrakon deve ser acompanhado de evidências
reproduzíveis: arquivos criados, testes executados (verde), contagem de
testes, e documentação atualizada. Se a evidência não puder ser conferida
com um comando, o trabalho não está concluído.

---

## 2. Definição de Concluído (Definition of Done)

Uma **capacidade** (item do `docs/ROADMAP_ABSORCAO.md`) só é considerada
concluída quando TODOS os itens abaixo forem verdadeiros:

| # | Critério | Como verificar |
|---|----------|----------------|
| 1 | O código existe no caminho previsto no roadmap | `ls <caminho>` |
| 2 | A suíte de testes passa | `.venv/bin/python -m pytest tests/ -q` → `X passed` |
| 3 | Existem testes novos cobrindo a capacidade | Arquivo `tests/test_<modulo>.py` presente e executado |
| 4 | O CHANGELOG foi atualizado com a mudança | `docs/CHANGELOG.md` contém a entrada com data e contagem |
| 5 | O ROADMAP reflete o progresso (checkbox/item/métricas) | `docs/ROADMAP_ABSORCAO.md` atualizado |
| 6 | Zero dependências externas novas sem justificativa | `pip list` comparado antes/depois |
| 7 | Segue as convenções do projeto (§4) | Revisão de código |

Uma **fase** só é concluída quando TODAS as capacidades da fase atendem à
Definition of Done E a seção "Critérios de Aceite por Fase" do roadmap está
integralmente marcada.

### 2.1 Protocolo de reporte

Ao final de cada tarefa, o agente DEVE informar, de forma objetiva:

1. **O que foi feito** — arquivos criados/modificados (caminhos reais).
2. **Evidência** — saída do comando de teste (contagem exata: `X passed`).
3. **O que NÃO foi feito** — itens pendentes, sem rodeios.
4. **Próximo passo** — segundo o roadmap.

É proibido afirmar conclusão de fase/capacidade sem executar o passo 2.
Se uma tentativa falhar (erro de execução, interrupção, loop), o reporte
deve registrar a falha explicitamente — nunca "engolir" o erro.

#### 2.1.1 Persistência obrigatória do relatório

Ao concluir uma **fase**, o relatório §2.1 completo (itens 1–4 acima) DEVE
ser salvo em `docs/README_VERSAO.md`, em uma seção própria da versão
(`## [x.y.z] — Fase N — <nome>`), seguindo o formato das seções já existentes
(O que foi feito / Evidência / O que NÃO foi feito / Próximo passo).
Sem a entrada no README de Versão, a fase NÃO é considerada concluída.

#### 2.1.2 Publicação obrigatória no GitHub

Ao concluir uma **fase** (e somente com a suíte verde), o estado do sistema
DEVE ser publicado no GitHub — commit + push para `origin/master` — para que
nenhum artefato fique apenas em disco local:

```bash
git add <arquivos da fase>
git commit -m "feat: <descrição da fase/versão>"
git push origin master
```

Regras de publicação:
- Nunca publicar com testes vermelhos (ver §8).
- Nunca dar push sem o commit correspondente conter toda a evidência da fase
  (código + testes + CHANGELOG + ROADMAP + README_VERSAO).
- Se o push falhar (ex: divergência com o remoto), NÃO forçar: reportar e
  resolver a divergência primeiro.

---

## 3. Ciclo de Trabalho Recomendado

1. **Consultar o roadmap** — `docs/ROADMAP_ABSORCAO.md`, seção "Próximos
   Passos Imediatos" e tabela "Já Implementado".
2. **Planejar** — lista de tarefas curtas e verificáveis.
3. **Implementar** — seguindo as convenções (§4).
4. **Testar** — escrever/atualizar testes e executar a suíte completa.
5. **Documentar** — atualizar `docs/CHANGELOG.md` e o roadmap.
6. **Registrar o relatório** — salvar o relatório §2.1 em
   `docs/README_VERSAO.md` (obrigatório ao fim de cada fase, §2.1.1).
7. **Publicar** — commit + push para o GitHub (obrigatório ao fim de cada
   fase, §2.1.2).
8. **Reportar** — conforme §2.1, com evidência e o hash do commit publicado.

---

## 4. Convenções de Código

### 4.1 Cabeçalho canônico de módulos

Todo módulo Python do projeto inicia com docstring no formato:

```python
"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: <caminho/do/modulo.py>
Descrição: <o que o módulo faz>
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - <origem legada, se aplicável>
  - <especificação / roadmap relacionado>
"""
```

Arquivos `__init__.py` incluem `__signature__ = "OD // CORE"`.

### 4.2 Regras técnicas

- **Stdlib primeiro:** preferir a biblioteca padrão; dependências externas
  só com justificativa registrada no CHANGELOG (exceções atuais:
  `pytest`, `pytest-asyncio`, `pyyaml` — e `pydantic` quando disponível).
- **Protocolo NICKY:** logs estruturados no formato
  `[NICKY][INFO|WARN|CRIT|ONLINE] <mensagem> | chave=valor`.
- **Tipagem:** type hints em todas as assinaturas; `dataclass` para modelos.
- **Segurança por design:** toda execução/ação passa pelo Security Layer
  (`core/security/`) em modo estrito quando aplicável.
- **Sem hardcode de segredos:** credenciais apenas via env vars / configs.
- **Escopo estrito:** operações de arquivo restritas a `/home/alex/OmegaDrakon`
  (spec §7.1); nada de acesso a diretórios legados sem comando explícito.

### 4.3 Convenções de testes

- Arquivos em `tests/` nomeados `test_<modulo>.py`.
- Testes em classes por área (ex: `TestStateManagerGetSet`), docstrings
  descritivas, uso de fixtures `tmp_path`, `monkeypatch`.
- Testes async usam `@pytest.mark.asyncio`.
- Rodar SEMPRE a suíte completa antes de reportar conclusão:
  `.venv/bin/python -m pytest tests/ -q`

---

## 5. Como Verificar um Trabalho Entregue (Checklist do Revisor)

Execute, nesta ordem:

```bash
# 1. Estado dos arquivos
git status --short

# 2. Suíte completa de testes
.venv/bin/python -m pytest tests/ -q

# 3. Contagem por suíte (opcional)
.venv/bin/python -m pytest tests/test_<modulo>.py -q

# 4. CHANGELOG registra a mudança?
grep -n "0.x.0" docs/CHANGELOG.md

# 5. ROADMAP reflete o progresso?
grep -n "Já Implementado" -A 12 docs/ROADMAP_ABSORCAO.md

# 6. Dependências inalteradas?
.venv/bin/pip list

# 7. Relatório §2.1 persistido no README de Versão?
grep -n "^## \[" docs/README_VERSAO.md

# 8. Fase publicada no GitHub?
git log origin/master..master --oneline   # deve listar o commit da fase
git log -1 --oneline                       # hash do último commit publicado
```

Critério de aceite do revisor: testes verdes + artefatos presentes +
documentação atualizada. Qualquer item ausente = trabalho NÃO concluído.

---

## 6. Estado Atual (Referência — 2026-09-03)

### Fase 1 — Fundação ✅ CONCLUÍDA

| Componente | Arquivo | Testes |
|---|---|---|
| Event Bus | `core/event_bus.py` | 56 ✅ |
| State Manager | `core/state.py` | 68 ✅ |
| Message Router | `core/router.py` | 55 ✅ |
| Config Manager | `configs/manager.py` | 46 ✅ |
| Security Layer | `core/security/` | 95 ✅ |
| Logger | `core/logger.py` | 43 ✅ |
| **Total** | 6 componentes | **363 testes, 0 falhas** |

### Fase 2 — Memória ✅ CONCLUÍDA (2026-09-03)

| Capacidade | Arquivo | Testes |
|---|---|---|
| 2.1 Conversation History | `memory/history.py` | 37 ✅ |
| 2.2 Cache LLM | `memory/cache.py` | 34 ✅ |
| 2.3 Quick Responses | `memory/quick_responses.py` | 28 ✅ |
| 2.4 Vector Memory (RAG) | `memory/vector.py` | 36 ✅ |
| 2.5 Context Manager | `memory/context.py` | 28 ✅ |
| **Total Fase 2** | 5 capacidades | **163 testes** |

> **Nota histórica:** em 2026-09-03 houve uma tentativa anterior de iniciar a
> Fase 2 (item 2.1) que falhou por erros repetidos de execução de ferramenta,
> sem produzir artefatos — registrada para transparência. A Fase 2 foi então
> implementada integralmente no mesmo dia, com evidência: **526 testes, 0
> falhas** (363 da Fase 1 + 163 da Fase 2).
> **Decisão registrada (2.4):** Vector Memory implementado sem ChromaDB
> (indisponível no ambiente), usando provider stdlib (`HashEmbeddingProvider`)
> com interface `EmbeddingProvider` adaptável para ChromaDB futuro — conforme
> mitigação do roadmap ("preferir stdlib; isolar em adapters").

### Fase 3 — Orquestração ✅ (CONCLUÍDA — 2026-09-03)

| Capacidade | Arquivo | Testes |
|---|---|---|
| 3.1 Workflow Engine | `core/workflows.py` | 70 ✅ |
| 3.2 Tool Loader | `tools/loader.py` | 39 ✅ |
| 3.3 Action Registry | `tools/registry.py` | 33 ✅ |
| 3.4 Orchestrator Pipeline | `core/orchestrator.py` | 38 ✅ |

> **Suíte atual:** **697 testes, 0 falhas** (668 das Fases 1–3.3 + 29 novos
> do Orchestrator). **16/32 capacidades** no roadmap. Publicado no GitHub —
> ver `docs/README_VERSAO.md` §[0.7.0] para o relatório §2.1 completo.
> **Próxima: Fase 4 — Execução** (Coder Engine, Self Repair, Perception,
> 56 Actions).

---

## 7. Regras de Documentação

- `docs/CHANGELOG.md`: entrada por versão (`## [x.y.z] — data`) com seções
  `### Adicionado`, `### Infraestrutura`; sempre registrar a contagem total
  de testes e a Fase correspondente.
- `docs/ROADMAP_ABSORCAO.md`: marcar itens concluídos (`✅`), atualizar
  tabela "Já Implementado", métricas e "Próximos Passos Imediatos" a cada
  entrega.
- `docs/README_VERSAO.md`: relatório §2.1 persistido por versão/fase
  (obrigatório ao concluir cada fase — ver §2.1.1); versão mais recente no
topo.
- **Publicação:** ao concluir cada fase, commit + push para `origin/master`
  (obrigatório — ver §2.1.2); registrar o hash do commit no reporte final.
- Documentos normativos (como este) são referência obrigatória: se uma regra
  conflitar com outra, prevalece a mais recente, e o conflito deve ser
  registrado no CHANGELOG.

---

## 8. Falhas e Recuperação

- Se uma execução falhar (testes vermelhos, erro de ferramenta, loop):
  1. Parar imediatamente e reportar a falha com a saída capturada.
  2. Corrigir a causa raiz, não os sintomas.
  3. Re-executar a suíte completa até verde.
- Nenhuma fase é promovida com testes vermelhos, em nenhuma circunstância.

---

## 9. Idioma da Interação (norma)

> **Decisão do usuário (Alex Projeti, 2026-09-03).** O agente responsável
> pelo desenvolvimento do OmegaDrakon conversa com o Alex **em Português
> do Brasil** — inclusive explicações técnicas, relatórios de entrega e
> respostas de ferramentas. Esta regra vale para TODAS as sessões futuras
> e tem prioridade sobre qualquer padrão de idioma genérico do agente.

- Exceções: código, identificadores, mensagens de erro e trechos citados
  são reproduzidos exatamente como estão (sem tradução).
- Se o agente se esquecer e responder em outro idioma, o usuário pode
  apontar esta seção — a falha deve ser corrigida imediatamente.
- Mensagens geradas para os produtos do sistema (bot Telegram, notificações
  de presença, avisos) também são em PT-BR, como já praticado.

---

## 10. Autorizações Permanentes do Usuário (norma)

> **Decisão do usuário (Alex Projeti, 2026-09-03).** O agente tem as
> autorizações abaixo de forma permanente, sem precisar pedir de novo a cada
> entrega — mas sempre registrando o que fez no CHANGELOG e com evidência.

1. **Instalação de ferramentas:** pode instalar pacotes, binários e
   dependências necessários ao desenvolvimento do OmegaDrakon (ex:
   whisper.cpp, Piper, OpenCV, clientes MQTT) — no ambiente do projeto,
   com registro da justificativa no CHANGELOG.
2. **Interfaces web (shells) sem chave manual:** páginas HTML de interface
   com o usuário (`/chat`, `/dashboard`) carregam SEM pedir chave manual
   no navegador (navegador não envia header custom). A chave é exigida em
   TODA chamada de dados/API (ex: `POST /message`, `/dashboard/stats`) —
   no chat ela é informada uma vez e fica na sessionStorage da aba.
3. **Segurança na LAN:** com o bind exposto (0.0.0.0), nenhum endpoint de
   dados fica aberto sem a chave; shell de página é estático (sem dados).

---

```python
"""
OMEGA DRAKON • SYSTEMS
Tecnologia que respira.
Módulo: docs/REGRAS_DE_TRABALHO.md
Descrição: Regras normativas de trabalho, verificação e reporte.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""
__signature__ = "OD // CORE"
```