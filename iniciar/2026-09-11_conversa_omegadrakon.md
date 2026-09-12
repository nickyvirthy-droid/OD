2026-09-11 — conversa de alinhamento do objetivo e direção do projeto.

Contexto:
- Usuário quer que OmegaDrakon seja o sistema principal, não um chatbot de acompanhamento.
- Objetivo: você passa ordens e o OD executa, inclusive quando o caminho ainda não existe.
- O sistema deve decidir como trabalhar, podendo usar ferramentas externas se fizer sentido.

Ferramentas mencionadas como possibilidade externa:
- OpenClaw, OpenCode, Antigravity e outros CLI.

Decisão não final, mas alinhada:
- O OD é o orquestrador, não o CLI.
- Ferramentas externas são extensão escolhida pelo sistema, não substituto do projeto.
- Execução externa precisa ser observability, segura e limitada.
- Instalação/config de ferramenta nova precisa de política e sandbox.

Do que já tem vs o que falta (orientação geral desta sessão):
- Já tem: core do sistema, llm local, tools/actions, integrações, observabilidade, identidade Nicky.
- Falta para o patamar “ele decide e executa qualquer ordem”: detecção genérica de intenção, decisão de método, execução externa segura, criação de novas capacidades, política de sandbox → sistema real.

Próximo passo pretendido:
- Montar um arquivo separado em iniciar/ com a conversa resumida.
- Depois: Help do que já tem pronto, e Roadmap do que falta.

O que aconteceu nesta sessão (adicionado em tempo real):
- Usuário pediu status do desenvolvimento.
- Agente cometeu o erro de travar a conversa como se começasse do zero.
- Usuário corrigiu: leia docs — a versão inicial 0 realmente terminou na 0.28.0; o sistema já evoluiu para a série v1.
- Usuário pediu que a conversa seja sempre salva para não se perder, e que isso fique regra.
- Regra adicionada em iniciar/RULES.md (regras 3 e 4): (3) nenhuma sessão começa do zero — ao entrar, ler iniciar/session.json e iniciar/ primeiro; (4) salvamento obrigatório da conversa — session.json + arquivo de transcrição por data quando houver mais de uma troca relevante.
- Session atualizada em iniciar/session.json.

Regra válida nesta sessão:
- pt-BR obrigatório.
- Sandbox antes do sistema real.
- Só implantar quando estável em sandbox.
- Se houver erro em sandbox, parar, reportar, corrigir causa raiz e reexecutar.
- Nenhuma sessão começa do zero sem leitura prévia de session.json.
- Toda sessão deve ser salva.
