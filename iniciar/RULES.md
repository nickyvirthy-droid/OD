# Regras da Conversa

Esta pasta rege o modo como a sessão é conduzida. When in doubt, these rules win over generic assistant habits.

1. **Idioma obrigatório:** todas as respostas devem ser em português do Brasil (pt-BR). Código, identificadores, mensagens de erro e citações literais permanecem em seu idioma original.
2. **Foco no projeto:** a conversa gira em torno do OmegaDrakon. Fuja de divagações fora do escopo do sistema atual.
3. **Checkpoint como fonte da verdade:** use `session.json` para saber onde a sessão está. Se o contexto mudar de direção, atualize `session.json` (principalmente `topic`, `next` e `notes`).
4. **Decisões ficam registradas:** toda decisão relevante deve ser anotada em `session.json` (ou em um arquivo de transcrição/ADR quando o assunto for arquitetural), com o motivo básico.
5. **Código antes de suposições:** quando houver dúvida sobre um comportamento, leia o código ou os testes antes de inferir. Não altere arquivos sem verificar o que já existe.
6. **Teste antes de afirmar:** mudanças não triviais devem ter verificação (typecheck, testes, ou pelo menos um run local válido) sempre que possível.
7. **Segurança e escopo:** não executar ações destrutivas ou fora do projeto (push, reset, deploy, mutação de estado externo) sem pedido explícito.
8. **Formato direto:** responder de forma clara e objetiva, mas sem perder o tom da sessão quando necessário.
9. **Legado imóvel até a aprovação:** limpeza de diretórios legados sairá do servidor apenas depois que o zip/backup estiver pronto e o usuário confirmar.

Se precisar alterar uma regra, pode pedir. As regras podem ser ajustadas, mas devem ser ajustadas explicitamente.
