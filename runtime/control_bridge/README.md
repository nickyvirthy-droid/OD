
OD Control Bridge

Ponte local de execução do OmegaDrakon.

Implementação
runtime/control_bridge/bridge.py
Serviço
od-control-bridge.service
Endpoint
http://127.0.0.1:8765
API
GET  /health
POST /execute
Usuário
odrunner
Raiz operacional
/home/alex/OmegaDrakon
Auditoria
/home/alex/OmegaDrakon/logs/control_bridge.jsonl
Segurança

A Bridge utiliza:

allowlist de comandos;
tokens bloqueados;
restrição de filesystem;
bloqueio dos sistemas legados;
timeout;
execução sem root;
isolamento básico via systemd;
auditoria JSONL.
Regra arquitetural

A Control Bridge é infraestrutura de execução do OmegaDrakon.

Ela não é agente, não é orquestrador e não possui autoridade arquitetural.

Para a documentação operacional completa:

docs/CONTROL_BRIDGE.md

