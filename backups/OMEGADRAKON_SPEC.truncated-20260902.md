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

---


