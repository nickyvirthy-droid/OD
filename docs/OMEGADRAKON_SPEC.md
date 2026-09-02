# OMEGADRAKON SPECIFICATION (OMEGADRAKON_SPEC)

**Documento de Especificação Técnica e Arquitetural Oficial**
**Versão:** 1.0.0
**Data:** 2026-08-25
**Status:** Aprovado / Ativo
**Escopo:** `/home/alex/OmegaDrakon`

---

## 1. Finalidade do OmegaDrakon

O **OmegaDrakon** é a plataforma central soberana de inteligência artificial pessoal, automação distribuída e orquestração de agentes autônomos. Ele foi concebido para unificar em uma arquitetura limpa, modular e segura as capacidades cognitivas, sensoriais, operacionais e de memória do ecossistema de computação pessoal e doméstica.

### 1.1 Objetivos Centrais
- **Centralização Soberana:** Prover um ponto único de governança, roteamento de eventos, execução determinística e controle de estado para todas as instâncias e agentes de IA do usuário.
- **Evolução Arquitetural:** Superar as limitações de acoplamento, redundância e dívida técnica observadas em iniciativas anteriores, estabelecendo padrões estritos de modularidade, testes automatizados e segurança por design.
- **Autonomia Segura:** Permitir que agentes inteligentes realizem tarefas complexas (automação residencial, desenvolvimento, manutenção de infraestrutura, gestão de conhecimento) mantendo rígidos limites de privilégio e isolamento de execução.

---

## 2. Responsabilidade e Mapeamento dos Diretórios

A estrutura de diretórios do OmegaDrakon reflete a separação estrita de responsabilidades do sistema. A responsabilidade de cada diretório existente no estado real atual do projeto é definida como segue:

```
/home/alex/OmegaDrakon
├── agents/          # Definições de personas, perfis e configurações de agentes
├── archive/         # Snapshots históricos e estados prévios imutáveis do servidor
├── backups/         # Cópias de segurança, pontos de restauração e dumps de dados
├── configs/         # Arquivos de configuração, variáveis de ambiente e parâmetros
├── core/            # Núcleo da arquitetura, barramento de eventos e ciclo de vida
├── docs/            # Documentação técnica, especificações e manuais operacionais
│   └── inventory/   # Inventários de hardware, serviços, dependências e capacidades
├── imports/         # Zona de estadiamento e quarentena para ingestão de dados/código
├── integrations/    # Conectores externos (Home Assistant, MQTT, Telegram, Docker, APIs)
├── knowledge/       # Bases de conhecimento estruturadas, ontologias e referências
├── logs/            # Registros operacionais, telemetria e trilhas de auditoria
├── memory/          # Camada de persistência de memória (vetorial, relacional, episódica)
├── runtime/         # Ambientes de execução controlada, sandboxes e isolamento
├── tests/           # Bateria de testes automatizados (unitários, integração, segurança)
├── tools/           # Catálogo de ferramentas executáveis e plugins determinísticos
└── workspace/       # Espaços de trabalho dedicados para agentes e subsistemas
    ├── od-builder/  # Workspace isolado do agente construtor/engenheiro
    └── openclaw/    # Workspace principal da interface de orquestração OpenClaw
```

### 2.1 Detalhamento de Responsabilidades

| Diretório | Responsabilidade Primária | Regras de Acesso e Uso |
| :--- | :--- | :--- |
| `agents/` | Armazenar perfis de identidade (`IDENTITY.md`, `SOUL.md`), papéis, políticas comportamentais e prompts base de cada agente operacional. | Somente leitura durante o runtime; alterações via governança do sistema. |
| `archive/` | Preservar registros imutáveis de estados anteriores do servidor (ex: `INITIAL_SYSTEM_STATE_SERVER_WIDE.txt`), logs históricos e auditorias legadas. | Estritamente somente leitura. Nenhum processo altera arquivos nesta pasta. |
| `backups/` | Conter snapshots consistentes do estado do OmegaDrakon, dumps de bancos de dados, snapshots de memória e pontos de recuperação. | Escrita automatizada pelos rotinas de backup; retenção controlada. |
| `configs/` | Centralizar configurações de portas, hosts, flags de execução e definições de serviços. Segredos reais devem ser geridos via variáveis de ambiente seguras. | Leitura por módulos autorizados; sem hardcode de credenciais. |
| `core/` | Conter a espinha dorsal do sistema: Event Bus, Message Router, State Manager, Orchestration Engine e gerenciadores de ciclo de vida. | Código limpo, testado com alta cobertura, sem acoplamento a ferramentas externas. |
| `docs/` | Hospedar documentação técnica, especificações (`OMEGADRAKON_SPEC.md`), diagramas arquiteturais e histórico de decisões arquiteturais (ADRs). | Documentação viva, sincronizada rigorosamente com a realidade do código. |
| `docs/inventory/`| Manter inventários detalhados e atualizados do hardware, serviços do sistema operacional, portas de rede, containers e modelos LLM disponíveis. | Atualizado periodicamente ou sob demanda de auditoria. |
| `imports/` | Atuar como quarentena para transferência, sanitização e refatoração de código, bases e dados antes de sua integração ao núcleo. | Dados em estadiamento; arquivos brutos sem execução direta. |
| `integrations/` | Prover adaptadores e clientes para sistemas externos (MQTT Broker, Home Assistant, Docker Daemon, bots de mensageria). | Isolamento de dependências de rede e protocolos de comunicação externa. |
| `knowledge/` | Armazenar dados estáticos de referência, manuais, ontologias, esquemas e documentos conceituais consultados pelos agentes. | Leitura frequente por agentes; indexação para busca semântica e factual. |
| `logs/` | Centralizar logs estruturados (JSON/linhas), logs de auditoria de segurança, telemetria de componentes e histórico de execução de tarefas. | Escrita append-only; rotação automática e retenção definida. |
| `memory/` | Prover persistência de longo e curto prazo, armazenamento vetorial (embeddings), histórico de conversas e consolidação diária/episódica. | Acesso controlado pela camada de memória do core; proteção contra vazamento em contextos públicos. |
| `runtime/` | Prover a infraestrutura de execução segura de tarefas, controle de processos filhos, sandbox local e limites de recursos (CPU/RAM). | Execução de comandos determinísticos sob estrito isolamento. |
| `tests/` | Conter suítes de testes unitários, testes de integração, testes de fluxo de workflows, testes de contrato e validação de segurança. | Validação obrigatória antes de qualquer promoção para execução no core. |
| `tools/` | Catálogo de capacidades executáveis (ações de sistema de arquivos, consultas, automações) que os agentes podem invocar sob demanda. | Ações atômicas, tipadas, validadas por schema e auditadas. |
| `workspace/` | Diretório de trabalho para agentes e orquestradores (como `od-builder` e `openclaw`), contendo contextos de sessão, notas diárias e estados de bootstrap. | Espaço mutável de interação diária com os agentes. |

### 2.2 OD Control Bridge

O **OD Control Bridge** é a infraestrutura local de execução controlada do OmegaDrakon.

- Atua exclusivamente como ponte entre solicitações autorizadas e execução local.
- Não é agente, não é orquestrador e não possui autoridade arquitetural.
- Opera localmente em `127.0.0.1:8765`.
- Executa sob o usuário de sistema `odrunner`, sem privilégios de `root`.
- O diretório de trabalho é estritamente `/home/alex/OmegaDrakon`.
- Comandos permitidos são definidos por lista explícita (`allowlist`).
- Comandos destrutivos e de elevação de privilégio são bloqueados por política.
- Caminhos para sistemas legados e diretórios externos protegidos são rejeitados.
- Toda execução é registrada em `logs/control_bridge.jsonl`.
- O tempo de execução possui limites mínimos e máximos definidos pela infraestrutura.
- O Bridge não concede acesso ao legado nem altera a autoridade arquitetural do OmegaDrakon.
- A documentação operacional completa encontra-se em `docs/CONTROL_BRIDGE.md`.
- O estado operacional do componente é **OPERACIONAL**.

---

## 3. Relação entre OmegaDrakon, OpenClaw, Open Interpreter e Antigravity

Para garantir máxima eficiência e ausência de sobreposição ou conflitos de autoridade, o papel de cada tecnologia no ecossistema é estritamente demarcado:

```
┌─────────────────────────────────────────────────────────────────┐
│                      ANTIGRAVITY (Google)                       │
│    Engenharia de Software, Arquitetura, Refatoração e Testes    │
└───────────────────────────────┬─────────────────────────────────┘
                                │ (Implementa, Valida e Mantém)
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                          OMEGADRAKON                            │
│           Plataforma Central Soberana e Núcleo do Sistema       │
│  (EventBus, Core Runtime, State, Memory, Security, Governance)  │
└──────────────────┬──────────────────────────────┬───────────────┘
                   │                              │
                   ▼                              ▼
┌───────────────────────────────────┐ ┌───────────────────────────┐
│             OPENCLAW              │ │     OPEN INTERPRETER      │
│ Orquestração Conversacional,      │ │ Execução Local Determinística │
│ Agentes & Interfaces (Workspaces) │ │ & Sandbox de Comandos Locais  │
└───────────────────────────────────┘ └───────────────────────────┘
```

### 3.1 Definição dos Papéis

1. **OmegaDrakon (O Sistema & Plataforma):**
   - É a plataforma soberana, o repositório central e a autoridade arquitetural.
   - Fornece o barramento de eventos (`core`), a persistência (`memory`), as políticas de segurança (`runtime`), as integrações e o catálogo de ferramentas (`tools`).
   - Não depende de uma única interface de usuário; é agnóstico e extensível.

2. **OpenClaw (Orquestrador de Agentes & Workspaces):**
   - Atua na camada de orquestração conversacional e interface de agentes.
   - Gerencia os workspaces de agentes (`workspace/openclaw`, `workspace/od-builder`), o ciclo de batimentos cardíacos (`HEARTBEAT.md`), os prompts de personalidade (`SOUL.md`, `IDENTITY.md`) e a recepção de mensagens de canais humanos.
   - Delega a execução de baixo nível e o armazenamento de infraestrutura para o OmegaDrakon.

3. **Open Interpreter (Executor Determinístico Local):**
   - Atua como o motor de execução de scripts locais e comandos sob demanda.
   - Opera dentro dos limites do `runtime/` e das ferramentas cadastradas em `tools/`.
   - Executa sob políticas de sandbox, sem autonomia para alterar configurações estruturais do sistema sem autorização expressa.

4. **Antigravity (O Engenheiro & Arquiteto):**
   - Atua como o parceiro sênior de engenharia de software e inteligência técnica.
   - Responsável pelo planejamento arquitetural, geração de código de alta precisão, criação de testes abrangentes, refatoração e auditoria contínua de integridade do OmegaDrakon.
   - Respeita integralmente os limites de escopo e os padrões do projeto.

---

## 4. Conceito de Absorção Progressiva de Sistemas Legados

O OmegaDrakon é o sucessor dos sistemas anteriores existentes no servidor. Para garantir continuidade e estabilidade sem importar erros arquiteturais do passado, adota-se o princípio da **Absorção Progressiva e Limpa**:

### 4.1 Princípios de Absorção

1. **Não-Invasão e Congelamento:**
   - Nenhum diretório de sistema legado fora de `/home/alex/OmegaDrakon` é acessado, executado, alterado ou movido durante a construção regular.
   - Os sistemas legados operam de forma isolada até que suas capacidades equivalentes estejam implementadas, testadas e homologadas no OmegaDrakon.

2. **Quarentena e Sanitização (`imports/`):**
   - Qualquer dado histórico, lógica de negócio, automação ou conhecimento que venha a ser migrado deve obrigatoriamente transitar pelo diretório `imports/`.
   - No `imports/`, o material legado é inspecionado, limpo de dependências obsoletas, refatorado para tipagem estrita e reescrito nos padrões modernos do OmegaDrakon.

3. **Migração Baseada em Capacidades (Feature-by-Feature):**
   - A absorção ocorre por funcionalidade verificável:
     1. Especificação da capacidade no OmegaDrakon.
     2. Implementação limpa em `core/`, `integrations/` ou `tools/`.
     3. Criação de testes unitários e de integração em `tests/`.
     4. Homologação em ambiente de teste antes de entrar em operação.

---

## 5. Protocolo de Congelamento e Backup

A integridade do estado e a recuperabilidade do sistema são requisitos inegociáveis.

### 5.1 Protocolo de Congelamento

- **Imutabilidade de Arquivos Históricos:** O diretório `archive/` guarda os estados imutáveis do servidor e não deve ser alterado por rotinas dinâmicas.
- **Congelamento de Código em Homologação:** Antes de grandes refatorações ou migrações de dados, o estado atual do repositório deve ser versionado via Git e sincronizado.

### 5.2 Estratégia de Backup

- **Snapshots de Dados e Configurações:** Backups regulares de bancos de dados locais (SQLite, ChromaDB/Vetoriais), arquivos de configuração e chaves em `backups/`.
- **Nomenclatura Padrão de Backups:**
  `backups/YYYYMMDD_HHMMSS_<componente>_<tipo>.(tar.gz|bak|sql)`
- **Princípio da Reversibilidade (Rollback Determinístico):** Qualquer procedimento que altere esquemas de banco de dados, arquivos de memória ou fluxos de execução deve possuir um procedimento documentado e testado de reversão imediata.

---

## 6. Separação entre Orquestração e Execução Local

Para evitar execução caótica ou acoplamento perigoso, o OmegaDrakon impõe uma fronteira rígida entre **pensamento (orquestração)** e **ação (execução)**:

```
[ Camada Cognitiva / Orquestração ]
  - Agentes (OpenClaw / Prompts / Subagentes)
  - Planejamento de Metas (DAGs de Ações)
  - Gestão de Contexto e Memória Semântica
                 │
                 ▼ (Emite Intenção Estruturada / Ação com Schema)
┌─────────────────────────────────────────────────────────────┐
│                   BARRAMENTO DE VALIDAÇÃO                   │
│          (Verificação de Políticas, Escopo e Permissões)    │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼ (Ação Aprovada)
[ Camada de Execução Local / Determinística ]
  - `tools/` (Ações Unitárias Tipadas)
  - `runtime/` (Processos Isolados / Open Interpreter / Shell Sandbox)
  - Emissão de Logs Estruturados & Telemetria em `logs/`
```

### 6.1 Regras de Separação

1. **Orquestrador não executa direto no host:** Agentes e modelos de linguagem não emitem comandos crus de shell arbitrários sem a mediação de schemas validados e controle de sandbox.
2. **Ações Atômicas e Tipadas:** Todas as ações do catálogo `tools/` devem receber parâmetros estritamente validados (Pydantic / schemas JSON), validar entradas e retornar saídas padronizadas.
3. **Assincronia e Event-Driven:** O core comunica intenções e resultados via barramento de eventos, garantindo que falhas de execução em ferramentas não travem o orquestrador.

---

## 7. Limites de Segurança do Sistema (Security Boundaries)

A segurança no OmegaDrakon é projetada em camadas de defesa em profundidade:

### 7.1 Limites Operacionais e de Arquivos

- **Escopo Estrito do Projeto:** Todas as operações de leitura, escrita, compilação e execução de scripts de desenvolvimento devem se limitar estritamente ao diretório `/home/alex/OmegaDrakon`.
- **Proteção a Sistemas Concorrentes/Legados:** Nenhuma operação automática deve acessar, modificar ou interferir em diretórios legados ou externos sem comando explícito e homologado do usuário.

### 7.2 Políticas de Menor Privilégio (Least Privilege)

- **Execução Sem Root:** Nenhum serviço ou agente do OmegaDrakon deve rodar com privilégios de superusuário (`root`), a menos que estritamente necessário para controle de hardware específico e sob autorização expressa.
- **Comandos Destrutivos:** Comandos que envolvam remoção irreversível (`rm -rf`, `DROP TABLE`, formatação) são proibidos para agentes autônomos. A política padrão é mover para quarentena/lixeira (`trash`) ou exigir aprovação humana explícita.

### 7.3 Isolamento e Gestão de Segredos

- **Segredos Fora do Código:** Chaves de API, senhas e tokens nunca devem ser escritos em arquivos rastreados pelo controle de versão. Eles residem em variáveis de ambiente protegidas ou no gerenciador de credenciais do sistema.
- **Auditoria Contínua:** Todas as chamadas de ferramentas, execuções no runtime e eventos críticos de segurança são registrados em `logs/` com carimbo de tempo (timestamp) e identificador da sessão.

---

## 8. Diretrizes de Desenvolvimento e Próximos Passos

1. **Fase Atual:** Planejamento, arquitetura e documentação formal.
2. **Proibição de Código Prematuro:** Nenhum código executável deve ser produzido antes da consolidação e validação das especificações arquiteturais fundamentais.
3. **Critérios de Aceite para Futuros Componentes:**
   - Aderência à especificação `OMEGADRAKON_SPEC.md`.
   - Cobertura de testes unitários e de integração em `tests/`.
   - Documentação de API e tipos atualizada em `docs/`.
   - Zero dependência rígida de diretórios externos.

---

_Fim da Especificação Técnica Oficial do OmegaDrakon._
