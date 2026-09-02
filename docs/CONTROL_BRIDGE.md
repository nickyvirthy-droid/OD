# OMEGA DRAKON • CONTROL BRIDGE

## 1. Identificação

**Componente:** OD Control Bridge  
**Serviço:** `od-control-bridge.service`  
**Módulo:** `runtime/control_bridge/bridge.py`  
**Versão da implementação:** `0.1`  
**Interface:** HTTP local  
**Host:** `127.0.0.1`  
**Porta:** `8765`  
**Usuário de execução:** `odrunner`

A OD Control Bridge é a ponte local de execução do OmegaDrakon.

Sua função é receber comandos autorizados e executá-los dentro do escopo do projeto OmegaDrakon.

A Bridge não constitui um agente, orquestrador ou autoridade arquitetural.

---

## 2. Posição arquitetural

A Bridge pertence à camada `runtime` do OmegaDrakon.

Fluxo conceitual:

```text
Agente / Orquestrador
        │
        │ solicitação de execução
        ▼
┌───────────────────────────┐
│      OD Control Bridge    │
│      127.0.0.1:8765       │
└─────────────┬─────────────┘
              │
              │ validação
              ▼
┌───────────────────────────┐
│ allowlist + bloqueios     │
│ + escopo filesystem       │
└─────────────┬─────────────┘
              │
              ▼
┌───────────────────────────┐
│ subprocess local          │
│ cwd = OmegaDrakon         │
└───────────────────────────┘

A Bridge não depende de OpenClaw, MariaDB, Mosquitto, Home Assistant ou llama.cpp para funcionar.

3. Escopo de filesystem

Raiz autorizada:

/home/alex/OmegaDrakon

Comandos contendo caminhos absolutos são aceitos somente quando o caminho resolvido permanece dentro dessa raiz.

Os seguintes locais são explicitamente bloqueados:

/home/alex/nicky
/home/alex/nexus
/home/alex/NV
/home/alex/Legado
/etc
/root
/boot
/usr
/var
/opt

O bloqueio de /home/alex/Legado é deliberado.

O legado permanece fora do fluxo operacional normal do OmegaDrakon.

4. Usuário de execução

A Bridge deve executar exclusivamente como:

odrunner

A implementação recusa execução como root.

O serviço systemd utiliza:

User=odrunner
Group=odrunner
5. Comandos permitidos

A allowlist atual contém:

cat
find
grep
head
tail
ls
pwd
tree
python
python3
pytest
git
file
sed
awk
du
df
stat
readlink

A allowlist controla o programa principal do comando.

---

## 6. Comandos e tokens bloqueados

Estão bloqueados:

```text
sudo
su
doas
rm
rmdir
mkfs
fdisk
parted
shutdown
reboot
poweroff
systemctl
mount
umount
chown
chmod
setfacl
useradd
userdel
passwd
kill
pkill
killall

A verificação também é aplicada aos tokens individuais do comando.

7. Execução

Diretório de trabalho:

/home/alex/OmegaDrakon

Timeout padrão:

120 segundos

Timeout máximo:

900 segundos

Saída máxima por stream:

64 KiB

Ambiente mínimo fornecido ao processo:

PATH=/usr/local/bin:/usr/bin:/bin
HOME=/home/odrunner
LANG=C.UTF-8
LC_ALL=C.UTF-8
8. API
GET /health

Endpoint de verificação de disponibilidade.

Resposta esperada:

{
  "status": "ok",
  "service": "od-control-bridge",
  "root": "/home/alex/OmegaDrakon"
}
POST /execute

Recebe uma requisição JSON contendo o comando e, opcionalmente, o timeout:

{
  "command": "pwd",
  "timeout": 120
}

Uma execução aceita retorna informações incluindo:

{
  "status": "ok",
  "command": "pwd",
  "exit_code": 0,
  "stdout": "...",
  "stderr": "",
  "elapsed_seconds": 0.001
}

Comandos rejeitados retornam:

{
  "status": "denied",
  "error": "...",
  "message": "..."
}

Timeouts retornam:

{
  "status": "timeout",
  "command": "...",
  "timeout": 120
}
9. Auditoria

A Bridge registra eventos em:

/home/alex/OmegaDrakon/logs/control_bridge.jsonl

São registrados, entre outros:

startup
command
timeout
rejected
http

O arquivo utiliza JSON Lines, permitindo processamento posterior sem introduzir banco de dados ou serviço adicional.

10. Serviço systemd

Arquivo:

/etc/systemd/system/od-control-bridge.service

Configuração atualmente instalada:

[Unit]
Description=OmegaDrakon Control Bridge
After=network.target

[Service]
Type=simple
User=odrunner
Group=odrunner
WorkingDirectory=/home/alex/OmegaDrakon
ExecStart=/usr/bin/python3 /home/alex/OmegaDrakon/runtime/control_bridge/bridge.py
Restart=on-failure
RestartSec=5

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=false
ReadWritePaths=/home/alex/OmegaDrakon

[Install]
WantedBy=multi-user.target


---

## 11. Segurança operacional

A Bridge possui atualmente as seguintes barreiras:

1. Bind exclusivamente em loopback.
2. Execução como usuário não privilegiado.
3. Recusa explícita de execução como root.
4. Allowlist de programas.
5. Lista explícita de comandos e tokens bloqueados.
6. Restrição de caminhos absolutos ao diretório do OD.
7. Bloqueio explícito dos sistemas legados.
8. `NoNewPrivileges=true`.
9. `ProtectSystem=strict`.
10. `PrivateTmp=true`.
11. Registro de auditoria em JSONL.
12. Timeout de execução.
13. Limite de saída.

A Bridge não deve ser tratada como mecanismo de autorização arquitetural.

Ela é uma camada de execução restrita.

---

## 12. Estado operacional

Estado atual registrado:

```text
OD Control Bridge       ATIVA
Host                    127.0.0.1
Porta                   8765
Usuário                 odrunner
Raiz                    /home/alex/OmegaDrakon
Serviço                 od-control-bridge.service
OpenClaw                NÃO requerido
llama.cpp               NÃO requerido
MariaDB                 NÃO requerido
Mosquitto               NÃO requerido
Home Assistant          NÃO requerido
Legado                  BLOQUEADO

A Bridge permanece como infraestrutura mínima do OmegaDrakon e pode operar independentemente dos demais componentes históricos.

13. Princípio de evolução

A implementação deve evoluir somente quando houver uma necessidade arquitetural real identificada.

Não adicionar:

comandos por conveniência;
acesso permanente ao legado;
privilégios elevados;
dependências externas desnecessárias;
banco de dados;
filas;
agentes autônomos;
mecanismos de execução paralela sem requisito definido.

Qualquer ampliação do escopo deve ser documentada antes de ser incorporada.

14. Relação com os legados

A Bridge não concede acesso aos sistemas:

/home/alex/nicky
/home/alex/nexus
/home/alex/NV
/home/alex/Legado

A absorção de conhecimento ou capacidades desses sistemas continua obedecendo ao princípio:

Legado
   ↓
análise
   ↓
capacidade / conhecimento
   ↓
OmegaDrakon

e não:

Legado
   ↓
cópia indiscriminada
   ↓
OmegaDrakon

O legado permanece intacto e fora do fluxo operacional normal.

15. Princípio de isolamento

Durante o desenvolvimento normal do OmegaDrakon:

os sistemas históricos permanecem parados;
o acesso ao legado permanece bloqueado;
serviços externos não são iniciados sem necessidade;
a Bridge permanece como infraestrutura local mínima;
novas dependências não são introduzidas sem requisito arquitetural.

A abertura temporária de acesso ao legado somente ocorre durante uma etapa formal de absorção e deve ser restrita ao material necessário.

16. Dependências operacionais

A Control Bridge atualmente utiliza apenas recursos disponíveis no sistema operacional e na biblioteca padrão do Python.

Não requer:

MariaDB
Mosquitto
Home Assistant
OpenClaw
llama.cpp
Ollama
Docker

para sua operação básica.

O objetivo é manter a camada de execução funcional mesmo quando os demais componentes do OmegaDrakon estiverem desligados.


---

## 17. Teste operacional mínimo

Verificação de saúde:

```bash
curl -s http://127.0.0.1:8765/health

Teste de execução:

curl -s \
  -X POST \
  -H 'Content-Type: application/json' \
  -d '{"command":"pwd"}' \
  http://127.0.0.1:8765/execute

Verificação do serviço:

systemctl status od-control-bridge.service --no-pager

Verificação da auditoria:

tail -n 20 /home/alex/OmegaDrakon/logs/control_bridge.jsonl
18. Estado de implementação

A implementação atual da Control Bridge está operacional.

Características confirmadas:

serviço systemd instalado;
execução como odrunner;
bind em 127.0.0.1:8765;
endpoint /health;
endpoint /execute;
allowlist de comandos;
bloqueio de comandos e tokens;
restrição de filesystem;
bloqueio dos legados;
timeout de execução;
limite de saída;
auditoria JSONL;
execução sem privilégios de root.

A implementação existente deve ser considerada a fonte de verdade para o comportamento efetivo da Bridge.

Este documento registra esse comportamento e não substitui o código.

19. Registro arquitetural

A OD Control Bridge é o componente operacional responsável pela ponte entre uma camada autorizada do OmegaDrakon e a execução local restrita.

Sua posição é:

OmegaDrakon
    │
    └── runtime
          │
          └── control_bridge
                │
                └── execução local restrita

A Bridge não possui autonomia arquitetural.

A autoridade arquitetural permanece fora dela.

20. Regra de evolução

Qualquer alteração futura na Control Bridge deve seguir estas regras:

identificar primeiro a necessidade;
verificar se a capacidade já existe;
alterar somente o necessário;
preservar o isolamento do legado;
preservar execução sem privilégios;
preservar o escopo do filesystem;
preservar a auditoria;
documentar alterações de interface ou comportamento;
testar a alteração antes de integrá-la ao restante do OmegaDrakon.

Nenhuma ampliação deve ocorrer apenas por conveniência.

21. Referência

Implementação:

runtime/control_bridge/bridge.py

Documentação operacional:

docs/CONTROL_BRIDGE.md

Documentação local do componente:

runtime/control_bridge/README.md

Serviço:

od-control-bridge.service

Log:

logs/control_bridge.jsonl
22. Registro final

Componente: OD Control Bridge
Estado: OPERACIONAL
Escopo: execução local restrita
Autoridade: nenhuma autoridade arquitetural
Dependências externas: nenhuma para operação básica
Acesso ao legado: bloqueado
Execução privilegiada: proibida

