# Regras da Conversa

Esta pasta rege o modo como a sessão é conduzida. When in doubt, these rules win over generic assistant habits.

1. **Idioma obrigatório:** todas as respostas devem ser em português do Brasil (pt-BR). Código, identificadores, mensagens de erro e citações literais permanecem em seu idioma original.
2. **Foco no projeto:** a conversa gira em torno do OmegaDrakon. Fuja de divagações fora do escopo do sistema atual.3. **Nenhuma sessão começa do zero:** ao entrar, leia primeiro `iniciar/session.json` e os arquivos recentes de `iniciar/` antes de assumir qualquer contexto. Se nada estiver salvo, não avance como se a conversa tivesse começado agora — pergunte onde retomar.
4. **Salvamento obrigatório a cada troca:** toda resposta relevante da sessão deve ser registrada antes de avançar — não apenas no fim. O mínimo é atualizar `iniciar/session.json` a cada troca com updated_at, o que foi dito, o que foi decidido e o que está em andamento. Se a sessão puder ser interrompida a qualquer momento (limite de uso, reinício, falha), o registro deve ser suficiente para retomar de onde parou. Sessões não salvas são sessões perdidas — isso não é opcional. Quando houver mudança de contexto ou conclusão de um ponto, criar ou atualizar um arquivo de transcrição em `iniciar/` nomeado por data (`iniciar/YYYY-MM-DD_conversa_omegadrakon.md`).
5. **Checkpoint como fonte da verdade:** use `session.json` para saber onde a sessão está. Se o contexto mudar de direção, atualize `session.json` (principalmente `topic`, `next` e `notes`).
6. **Decisões ficam registradas:** toda decisão relevante deve ser anotada em `session.json` (ou em um arquivo de transcrição/ADR quando o assunto for arquitetural), com o motivo básico.

5. **Código antes de suposições:** quando houver dúvida sobre um comportamento, leia o código ou os testes antes de inferir. Não altere arquivos sem verificar o que já existe.
6. **Teste antes de afirmar:** mudanças não triviais devem ter verificação (typecheck, testes, ou pelo menos um run local válido) sempre que possível.
7. **Segurança e escopo:** não executar ações destrutivas ou fora do projeto (reset, deploy, mutação de estado externo) sem pedido explícito.
   - **7.1 Commit e push — autorização permanente (2026-09-21):** depois de concluir e validar uma atualização, `git commit` e `git push origin master` estão **autorizados por padrão** — não esperar confirmação a cada passo (uma queda de conexão ou fim de cota no meio da espera já custou trabalho). Vale para o código, para o `docs/CHANGELOG.md` e para o registro em `iniciar/`. **Deploy/restart** de serviço (`systemctl --user restart od-core`) e outras mutações de estado externo **continuam** exigindo autorização explícita.
   - **7.2 Sistema sempre limpo e atualizado:** ao fechar uma etapa, deixar a árvore de trabalho sem resíduos (temporários/patches removidos), o `HEAD` publicado em `origin/master` e o registro da sessão em `iniciar/` atualizado.
   - **7.3 Restart verde autorizado por padrão (2026-10-09):** o dono autorizou de forma permanente: `systemctl --user restart od-core` está **autorizado por padrão quando a validação está verde** (suíte do servidor passando, `flutter analyze`/`flutter test` limpos quando houver mudança no app, HEAD == origin/master, sem resíduos). O restart DEVE continuar sendo registrado em `iniciar/` com prova viva (PID, NRestarts, /health, journal 0 erros) como em qualquer outro deploy. Fora do cenário verde, pedir autorização explícita.
8. **Formato direto:** responder de forma clara e objetiva, mas sem perder o tom da sessão quando necessário.
9. **Legado imóvel até a aprovação:** limpeza de diretórios legados sairá do servidor apenas depois que o zip/backup estiver pronto e o usuário confirmar.
10. **Sandbox antes do sistema real:** toda mudança deve ser validada em sandbox antes de ir para o sistema real. Só implantar no sistema real quando não houver mais erros. Mudanças no sistema real sem validação prévia não são aceitas.

11. **Regras do projeto valem para a sessão:** as regras normativas do projeto (docs/REGRAS_DE_TRABALHO.md) se aplicam aqui: PT-BR obrigatório, evidência antes de afirmar, Definition of Done, registro e publicação conforme o documento.

12. **Versionamento SemVer obrigatório (2026-09-26):** versão em X.Y.Z conforme `docs/VERSIONAMENTO.md` (base: semver.org). Feature nova compatível = MINOR (`x.Y.0`), fix sem feature = PATCH (`x.y.Z+1`), quebra de API = MAJOR. O sufixo `+N` (versionCode do app) é metadado de build e NUNCA substitui o incremento da versão. Bump acontece no deploy da mudança, pelo checklist da política (`.env`, capabilities, pubspec, site, CHANGELOG, README_VERSAO).

13. **Formalização do fluxo de mudança (3 passos):**
- 1) Validar em sandbox antes do sistema real.
- 2) Só implantar no sistema real quando a mudança estiver estável em sandbox.
- 3) Se houver erro em sandbox, parar, reportar com a saída, corrigir causa raiz e reexecutar até não haver mais erros.

14. **Sem copiar/colar com o dono — canal é o `txt.txt` (2026-10-03):** o dono lê o chat pelo terminal (freebuff) e o copiar/colar NÃO funciona no fluxo dele. Nunca pedir para "copiar e colar" nem assumir que ele vai mover texto entre janelas. Para entregar a ele URLs, comandos, chaves ou textos longos: escrever no `txt.txt` (raiz do projeto — canal do dono, editável também pelo painel `/admin` e pelo app) e avisar no chat do que foi colocado lá; de preferência, entregar páginas com botões em `site/` para clicar em vez de digitar URLs. O dono também escreve no `txt.txt` — checá-lo quando houver troca de informação com ele.

15. **Resumo de conclusão também no Telegram (2026-10-08):** ao concluir uma etapa (lote, deploy, entrega), além de responder no chat e registrar em `iniciar/`, enviar também o mesmo resumo no Telegram do dono (bot `TELEGRAM_BOT_TOKEN` do `.env`, chat `OD_TELEGRAM_ADMINS` — 660518870) via API `sendMessage`. O envio faz parte do Definition of Done da conclusão.

16. **O Legado é referência obrigatória (2026-10-09):** a pasta `/home/alex/Legado` (o dono escreve às vezes como `home/alex/Legado` — o caminho real tem `home` minúsculo e `alex` minúsculo) contém o núcleo da marca Omega Drakon e a história dos projetos predecessor (Nicky Virthy, Nicky, NV, Nexus). Toda decisão sobre identidade visual, tom de voz, produtos, autenticidade ou história do ecossistema deve passar por lá (núcleo em `Legado/OMEGA_DRAKON/`) antes de ser inventada. **Bússola: `Legado/00_MAPA_DO_LEGADO.md`** (índice vivo vs histórico + mapa de duplicações medido bit a bit — nada foi apagado). O Google Drive (`OmegaDrakon`, `OD`) traz as consolidações canônicas de 2026-08 (`OMEGADRAKON_SPEC.md`, `OMEGA_DRAKON_SOURCE_MAP.md`, `NICKY_VIRTHY_KNOWLEDGE.md`). NUNCA copiar segredos do Legado (há tokens/senhas em texto puro em documentos antigos) nem publicá-los no site.

Se precisar alterar uma regra, pode pedir. As regras podem ser ajustadas, mas devem ser ajustadas explicitamente.
