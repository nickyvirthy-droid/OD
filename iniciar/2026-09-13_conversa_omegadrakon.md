2026-09-13 — retomada da sessão (regra 3: nenhuma sessão começa do zero).

Entrada:
- Usuário: "leia iniciar".
- Agente leu, nesta ordem: iniciar/README.md, iniciar/RULES.md,
  iniciar/session.json, iniciar/2026-09-12_conversa_omegadrakon.md.

Estado conferido no git (evidência, não memória):
- `git log --oneline` → HEAD é 8c58520 ("docs: registra o hash 68cf2e5 no
  checkpoint da sessão"); antes dele 68cf2e5, a5ac3a5, e2f4960, ffeab4f.
- `git status --short` → a entrega de push FCM segue NÃO commitada:
  novos: core/push.py, tests/test_push.py, docs/FIREBASE_SETUP.md
  modificados: .gitignore, app/lib/main.dart, app/lib/services/od_api.dart,
  app/lib/services/push_service.dart, app/pubspec.yaml,
  app/test/od_api_test.dart, core/capabilities.py, core/llm.py,
  core/orchestrator.py, docs/CAPACIDADES.md, docs/CHANGELOG.md,
  docs/README_VERSAO.md, docs/ROADMAP_V1.md, integrations/api/server.py,
  requirements.txt, runtime/install_postgres.sh, runtime/launcher.py,
  site/index.html, tests/test_api.py, iniciar/.

Retomada registrada:
- iniciar/session.json atualizado (updated_at 2026-09-13T14:20:31-03:00,
  last_turn = esta retomada, bloco anterior preservado em previous_turn,
  next.estado_em_2026-09-13 com o estado real do git).

Pontos abertos (do checkpoint anterior, ainda válidos):
1. Publicar a entrega de push FCM (commit + push) — aguarda autorização.
2. Gerar a service account do Firebase e rodar POST /push/test com o aparelho
   registrado (só o usuário pode gerar a credencial).
3. Instalar o APK 1.2.0+5 (1005) no Redmi Note 14.
4. Backlog de servidor que ficou fora do e2f4960.
5. Achados do journal: SelfRepair no_fix em agent.py e o handler
   face.presence com AttributeError.

Rodada 1 (autorizada): publicar a entrega de push FCM

Escolha do usuário: "Publicar o push FCM". Escopo aprovado por pergunta
explícita: **commit único com tudo que está em produção** (opção A).

Revisão do diff antes de commitar (21 modificados + 4 novos):
- Da entrega: core/push.py, tests/test_push.py, docs/FIREBASE_SETUP.md,
  .gitignore (regras de credencial Firebase), core/capabilities.py
  (push-fcm + integrations.push), requirements.txt (google-auth), app/lib/*,
  app/test/od_api_test.dart, app/pubspec.yaml (1.2.0+5).
- Colados nos mesmos arquivos (não separam por hunk): server.py e
  tests/test_api.py trazem também /actions, /executa e /site; launcher.py
  traz também max_tokens 512.
- Em produção junto: core/llm.py (512 tokens), core/orchestrator.py
  (data/hora DEPOIS do system prompt — cache de KV), install_postgres.sh,
  docs/CAPACIDADES.md, site/index.html (landing do APK arm64).
- Fora: 000/, assets/, sandbox_agent/, agent.py, agent.b64, executar.sh,
  gemini_prompt.sh, llama_prompt.sh, od_aider.sh, od_prompt.sh, txt.txt,
  GPT_preview.png (arquivos soltos de trabalho local, não são o sistema).

Verificação:
- `.venv/bin/python -m pytest tests/ -q` → 1647 passed, 16 skipped (15.13s)
- app: `flutter analyze` → No issues found! · `flutter test` → 42 passed
- segredos: varredura do staged por AIza/PRIVATE KEY/api_key sem ocorrências;
  `git check-ignore -v` confirma data/push_devices.json (.gitignore:101) e
  app/android/app/google-services.json (.gitignore:131) fora do repo.

Publicação:
- Commit **3b5599c** — "feat(push): implanta o push FCM de ponta a ponta
  (servidor + app)" (25 arquivos, +2456/-60).
- Push: `origin/master 8c58520..3b5599c`.
- O APK 1.2.0+5 já estava publicado em site/ — este commit não reconstruiu
  nem republicou binário.

Próximo passo: service account do Firebase + teste de ponta a ponta
(POST /push/test com o aparelho registrado) e a instalação do APK 1.2.0+5 no
Redmi Note 14; depois os dois achados do journal.

Rodada 2 (autorizada): preparar o push FCM para o teste de ponta a ponta

Estado verificado no servidor (não presumido):
- od-core ativo desde 08:02:10 de hoje (PID 133800, modo all).
- Journal de todos os restarts de hoje: "Push FCM inicializado | enabled=False
  | motivo=credencial_ausente | credencial=- | dispositivos=0".
- Dependência pronta: google-auth 2.58.0 já instalado na .venv.
- Credencial ausente mesmo: `find` por *service-account*/*firebase-adminsdk*
  não achou nada no repo; `.env` não tem OD_FCM_CREDENTIALS,
  OD_PUSH_ENABLED nem OD_PUSH_PROJECT_ID (valem os defaults do core/push.py).

Verificação ao vivo contra a API (contrato do push, com a chave do .env):
- GET /push/devices → 200 {enabled:false, reason:"credencial_ausente",
  devices:0}
- POST /push/test → HTTP 503 {ok:false, error:"push_desligado:
  credencial_ausente"} (esperado enquanto não há credencial)
- POST /push/test sem chave → HTTP 401
- POST /push/register com token fake → 200 {devices:1, push_enabled:false}
  (registro funciona com o push desligado — o aparelho se adianta à credencial)
- POST /push/unregister → 200 {removed:true, devices:0} — registro limpo
- git check-ignore: config/firebase-service-account.json coberto pelo
  .gitignore:134 (firebase-service-account*.json)

Projeto Firebase confirmado nos dois google-services.json (000/ e
app/android/app/): project_id nicky-e4f99, project_number 582855984584,
pacote com.omegadrakon.nicky.

Bloqueios que dependem do usuário (não são executáveis daqui):
1. Gerar a service account no console do Firebase (projeto nicky-e4f99 →
   Configurações do projeto → Contas de serviço → Gerar nova chave privada) e
   salvar em config/firebase-service-account.json — só a conta dele pode.
2. Instalar/abrir o APK 1.2.0+5 no Redmi Note 14 (redmi-note-14-1,
   100.80.224.73): o aparelho está OFFLINE no tailnet (visto há 1 dia) e o
   registro segue com 0 dispositivos.

Quando a credencial chegar: validar o JSON com google-auth (sem enviar nada),
reiniciar o od-core e conferir journal + GET /push/devices; com o aparelho
registrado, POST /push/test fecha o teste de ponta a ponta.

Rodada 3: validar a service account — ARQUIVO AUSENTE NO SERVIDOR

O usuário disse que a credencial já estava em
config/firebase-service-account.json. Verifiquei antes de reiniciar:

- `ls -la config/firebase-service-account.json` → No such file or directory
- `find ~ -maxdepth 3` por *firebase*/*nicky-e4f99*/*service-account*/
  *firebase-adminsdk* → nenhum resultado
- `find /home /tmp /srv /opt /mnt /media -maxdepth 5` pelos mesmos padrões → nada
- `find config -newermt 2026-09-12` → nada; config/ tem só iot_credentials.json
  e iot_credentials.example.json
- `find ~ -maxdepth 4 -name '*.json' -newermt 2026-09-12` → só arquivos do
  sistema/manicode e do próprio repo (transaction logs do agent, data/*.json)

Conclusão: o JSON baixado no console do Firebase ficou na máquina onde o
navegador roda (desktop Windows ou celular). O nicky-server é headless, então o
arquivo precisa ser transferido. Por isso NÃO reiniciei o od-core: subiria
idêntico (enabled=False, credencial_ausente) e só geraria ruído no journal.

Caminho de transferência (verificado): ssh ativo no servidor (porta 22,
0.0.0.0 e [::]), usuário `alex`, tailnet 100.77.67.53 →
`scp <arquivo baixado> alex@100.77.67.53:/home/alex/OmegaDrakon/config/firebase-service-account.json`
e depois `chmod 600 config/firebase-service-account.json`.

Aguardando a transferência para seguir com validação + restart + teste.

Rodada 4: usuário reporta que o scp terminou — ARQUIVO CONTINUA AUSENTE

Busca exaustiva desta vez:
- `ls -la config/firebase-service-account.json` → No such file or directory;
  config/ só tem iot_credentials.json e iot_credentials.example.json.
- `find / -xdev` por *adminsdk*/*firebase-service-account*/*nicky-e4f99* → nada.
- `find /home/alex/dados /mnt/Arquivos /srv/omegadrakon` pelos mesmos padrões e
  por arquivos novos desde 14:00 → nada.
- `find /home/alex -maxdepth 3 -newermt 14:05 -type f` → só ruído conhecido:
  .od_repair_backups/*.bak, txt.txt, telemetria do Dart, data/, logs/,
  iniciar/. Nenhum JSON novo em ~ até 5 níveis.
- `find ~ -maxdepth 4 -name '*.json' -newermt 2026-09-12` → nada de credencial.

Pistas no journal:
- Nenhuma conexão SSH nova depois de 14:13:13 (última sessão, pts/0, de
  192.168.0.227, ainda aberta).
- Há dois /usr/lib/openssh/sftp-server ociosos, abertos às 14:08:32 e 14:09:02,
  também de 192.168.0.227, que não deixaram arquivo em nenhum caminho legível.

Endereços do servidor para conferência: LAN 192.168.0.250 · tailnet
100.77.67.53 · usuário alex. Não reiniciei o od-core (nada a carregar; seguiria
dormente) e /root não é verificável sem senha de sudo — se o upload usou root
com caminho relativo, o arquivo pode estar em /root/config/.

Pendente: comando + saída do scp (ou o JSON por outro caminho) para seguir com
validação + restart + teste de ponta a ponta.

Rodada 5: pasta 000/ verificada e colocada fora do git

Pedido: verificar 000/ (arquivos de construção e ideias do projeto) e mantê-la
fora do versionamento.

Conteúdo real da pasta (5 arquivos, 1.2 MB):
- 000/app.txt (897 B), 000/freebuff-intencoes.md (4 KB)
- 000/chatGPT.md (53 KB)
- 000/Ferramenta IA local erotikk.pdf (1 MB)
- 000/google-services.json (1 KB) — já estava coberto pelo .gitignore:131

A service account NÃO está na 000/ (nem em nenhum outro lugar do servidor) — o
bloqueio do push FCM continua igual.

Ação: regra `000/` adicionada ao .gitignore (linha 139), com comentário
explicando que é material de trabalho do usuário, não parte do sistema.
Verificação: `git check-ignore -v` confirma a regra valendo para a pasta e para
todos os 5 arquivos (inclusive o PDF com espaços no nome); `git status` deixou
de listar `?? 000/`; `git ls-files 000` está vazio → nada da pasta entrou no
histórico em nenhum momento, não há nada a remover.

Decisão do usuário (segunda pergunta da rodada): ignorar TAMBÉM tudo que está
solto na raiz. Regras adicionadas ancoradas com barra inicial para não pegar
homônimos dentro do código: /agent.py, /agent.b64, /txt.txt, /GPT_preview.png,
/executar.sh, /gemini_prompt.sh, /llama_prompt.sh, /od_aider.sh, /od_prompt.sh,
/sandbox_agent/, /assets/.

Checagem antes de ignorar: `sandbox_agent/` é a sandbox do agent.py da raiz
(agent_config.json + agent.py:17 `SANDBOX_DIR = PROJECT_ROOT / "sandbox_agent"`)
— são um par local, nenhum módulo do OD os importa; `assets/` é saída de build
do Flutter (assets/flutter_assets/kernel_blob.bin) que nenhum código do projeto
referencia; os .sh carregam o .env e chamam API/LLM localmente.
Verificação: `git check-ignore -v` confirma as 12 regras; `git ls-files |
git check-ignore --stdin --no-index` não retorna nada → nenhum arquivo já
versionado passou a ficar invisível; `git status` ficou limpo de untracked.

Publicado em seguida (autorizado): commit apenas do .gitignore + checkpoint.
