#!/usr/bin/env python3
"""Gera as 5 páginas do Ecossistema a partir de um template comum.

Cada frente do ecossistema ganhou página própria a pedido do dono (txt.txt,
10/10: "O Ecossistema vamos evoluir para que cada tópico tenha sua própria
página" e "Produtos vai apontar para as mesmas páginas do Ecossistema").

O template garante que nav (menu ⋮) e rodapé sejam IDÊNTICOS aos das outras
páginas — era exatamente a divergência que cortava o texto do menu.
Rodar: .venv/bin/python tools/gerar_ecossistema.py
"""
from __future__ import annotations

import sys
from pathlib import Path

#: As páginas saem em site/ (o diretório público servido por /site/{file}).
#: O gerador fica em tools/ de propósito: qualquer .py dentro de site/ seria
#: baixado por qualquer visitante via /site/<arquivo>.
SITE = Path(__file__).resolve().parents[1] / "site"

#: O mesmo cabeçalho/rodapé de todas as páginas do site.
NAV = """<nav>
  <div class="wrap">
    <a class="brand" href="/site"><img src="/site/simbolo_minimo.png" alt="OD"> OMEGA DRAKON</a>
    <div class="nav-spacer"></div>
    <button class="nav-toggle" aria-label="Abrir menu" aria-expanded="false" aria-controls="navPanel"><span class="dots">&#8942;</span></button>
  </div>
</nav>
<div class="nav-panel" id="navPanel">
  <div class="wrap">
    <a href="/site#marca">Marca</a>
    <a href="/site#ecossistema">Ecossistema</a>
    <a href="/site#sistemas">Sistemas</a>
    <a href="/site#produtos">Produtos</a>
    <a href="/site#autenticidade">Autenticidade</a>
    <a href="/site/verificacao.html">Verificar peça</a>
    <a href="/site#historico">Histórico</a>
    <a href="/site#pleiade">Plêiade</a>
    <a href="/site#sobre">Sobre</a>
    <a href="/chat">Chat</a>
    <a class="cta" href="/site#download">Baixar APK</a>
  </div>
</div>
"""

RODAPE = """<footer class="site">
  <div class="wrap">
    <div class="f-brand">
      <img src="/site/simbolo_minimo.png" alt="OD">
      <span>OMEGA DRAKON</span>
    </div>
    <p class="f-sig">Interface Viva: Nicky Virthy &nbsp;·&nbsp; Arquiteto: Alex Projeti &nbsp;·&nbsp; Assinatura: OD // CORE</p>
    <div class="f-links">
      <a href="/site#marca">Marca</a>
      <a href="/site#ecossistema">Ecossistema</a>
      <a href="/site/historico.html#historico">Histórico</a>
      <a href="/site/verificacao.html">Verificar peça</a>
      <a href="/chat">Chat</a>
    </div>
    <p class="f-slogan">Tecnologia que respira.</p>
  </div>
</footer>
<button class="to-top" id="toTop" aria-label="Voltar ao topo" title="Voltar ao topo">&#8593;</button>

<script src="/site/od-nav.js"></script>
</body>
</html>
"""

#: (arquivo, título, kicker, h1, tagline, conteúdo)
PAGINAS: list[tuple[str, str, str, str, str, str]] = [
    (
        "ecossistema-omega-drakon.html",
        "Omega Drakon — A Marca Mãe",
        "Ecossistema · Marca Mãe",
        "Omega Drakon",
        "O sistema que governa o ecossistema",
        """
<section>
  <div class="wrap">
    <div class="sec-head">
      <div class="kicker">Escopo</div>
      <h2>O que a Marca Mãe Governa</h2>
      <p>A OMEGA DRAKON é a raiz de todo o ecossistema. Não é uma empresa nem
      uma linha de produtos: é a autoridade que define identidade, numeração e
      autenticidade de tudo o que é criado — do software às peças físicas.</p>
    </div>
    <div class="grid g3">
      <div class="card">
        <div class="num">01</div>
        <h3>Identidade</h3>
        <p>O núcleo da marca: manifesto, símbolos oficiais, tom de voz e a
        tríade canônica. Nenhuma frente do ecossistema pode redefinir a
        identidade por conta própria.</p>
      </div>
      <div class="card">
        <div class="num">02</div>
        <h3>Numerologia Canônica</h3>
        <p>Todo item recebe um ID no formato OD-[CATEGORIA]-[ANO]-[SEQ]. A
        numeração é a espinha dorsal do Registro Mestre e da verificação
        pública.</p>
      </div>
      <div class="card">
        <div class="num">03</div>
        <h3>Registro Mestre</h3>
        <p>Banco de tudo o que foi produzido: coleção, lote, data e estado.
        Ciclos encerrados nunca são reeditados — a história da marca é
        imutável por desenho.</p>
      </div>
    </div>
    <blockquote>
      "Omega Drakon é o sistema. Nicky Virthy é a voz. Alex Projeti é o
      arquiteto. Qualquer iniciativa que não respeite essa tríade não pertence
      ao ecossistema."
      <footer>A Tríade Canônica — Regra de Ouro do ecossistema</footer>
    </blockquote>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="sec-head">
      <div class="kicker">Estado</div>
      <h2>Onde Está Hoje</h2>
    </div>
    <div class="grid g2">
      <div class="card">
        <h3>Ativo</h3>
        <p>Núcleo documental completo (manifesto, manual de identidade visual,
        codice da marca), Registro Mestre no ar com verificação pública e o
        site institucional do ecossistema inteiro.</p>
        <span class="tag">Em operação</span>
      </div>
      <div class="card">
        <h3>As outras frentes</h3>
        <p>Cada sub-marca tem página própria com o escopo e o estado real —
        sem promessa de prazo, sem ornamento sem função.</p>
        <span class="tag gray">Ver o ecossistema</span>
      </div>
    </div>
  </div>
</section>
""",
    ),
    (
        "ecossistema-systems.html",
        "Omega Drakon · Systems — A Plataforma Soberana",
        "Ecossistema · Systems",
        "Omega Drakon · Systems",
        "Software, servidores, automação e IoT",
        """
<section>
  <div class="wrap">
    <div class="sec-head">
      <div class="kicker">Escopo</div>
      <h2>A Plataforma Soberana</h2>
      <p>O núcleo de software do ecossistema: uma IA pessoal que roda em
      hardware próprio, decide sem depender de nuvem alheia e conversa por
      qualquer superfície — celular, navegador, Telegram ou voz.</p>
    </div>
    <div class="grid g4">
      <div class="card">
        <div class="num">Núcleo</div>
        <h3>Orquestrador</h3>
        <p>Barramento de eventos, roteamento por papel (dono, usuário,
        visitante), cache inteligente com poda de falhas e pipeline de
        segurança com negação determinística de segredos.</p>
      </div>
      <div class="card">
        <div class="num">Mente</div>
        <h3>IA Local</h3>
        <p>LLM servida localmente (llama.cpp) com fallback honesto: dado sem
        fonte é "desconhecido", nunca alucinado. Recusas do modelo nunca
        entram no cache.</p>
      </div>
      <div class="card">
        <div class="num">Memória</div>
        <h3>Histórico &amp; RAG</h3>
        <p>Histórico persistente por conta em PostgreSQL, busca vetorial,
        respostas rápidas determinísticas e contexto contínuo entre sessões e
        superfícies.</p>
      </div>
      <div class="card">
        <div class="num">Ações</div>
        <h3>Catálogo Determinístico</h3>
        <p>Clima real, temperatura do servidor, luzes e casa via Home
        Assistant, Gmail/Agenda/Drive, monitoramento e telemetria — fast-path
        sem LLM.</p>
      </div>
      <div class="card">
        <div class="num">Superfícies</div>
        <h3>App · Chat · Telegram · Voz</h3>
        <p>App Android com streaming, auto-atualização verificada por SHA-256
        e push; chat web autenticado; bot Telegram; STT/TTS para conversa por
        voz.</p>
      </div>
      <div class="card">
        <div class="num">Lar</div>
        <h3>IoT &amp; Automação</h3>
        <p>Home Assistant, MQTT e monitor de roteador integrados: clima da
        casa, luzes acesas, presença e saúde da infraestrutura respondidos
        com dado real.</p>
      </div>
      <div class="card">
        <div class="num">Confiança</div>
        <h3>Auto-Reparo &amp; Supervisão</h3>
        <p>Sondas de saúde, reinício autônomo supervisado, trilhas de
        auditoria JSONL e painéis de observação do organismo inteiro.</p>
      </div>
      <div class="card">
        <div class="num">Execução</div>
        <h3>Control Bridge</h3>
        <p>Ponte de execução local com allowlist, escopo de filesystem,
        usuário dedicado e auditoria — infraestrutura de execução, jamais
        autoridade arquitetural.</p>
      </div>
    </div>
    <div class="pleiade-note">Stack: Python 3.12 · Flutter · PostgreSQL ·
    llama.cpp · Mosquitto MQTT · Home Assistant · Tailscale · systemd ·
    GitHub. Tudo em hardware próprio — nenhum dado de conversa sai da casa.</div>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="sec-head">
      <div class="kicker">Produto</div>
      <h2>Para o Usuário</h2>
    </div>
    <div class="dl-card">
      <img src="/site/logo.png" alt="Ícone do app Omega Drakon">
      <div class="dl-info">
        <h3>App Omega Drakon</h3>
        <p>A Plêiade no bolso. Chat em streaming, vozes por perfil, comandos
        de voz, push e auto-atualização que só instala builds com hash
        conferido.</p>
        <div class="dl-links">
          <a class="btn btn-primary" href="/site#download">Baixar o app</a>
          <a class="btn btn-ghost" href="/site/verificacao.html">Verificar uma peça</a>
        </div>
      </div>
    </div>
  </div>
</section>
""",
    ),
    (
        "ecossistema-fab.html",
        "Omega Drakon · FAB — Manufatura de Precisão",
        "Ecossistema · FAB",
        "Omega Drakon · FAB",
        "Do bit ao átomo, com o mesmo rigor",
        """
<section>
  <div class="wrap">
    <div class="sec-head">
      <div class="kicker">Escopo</div>
      <h2>Manufatura de Precisão</h2>
      <p>A frente física do ecossistema. Todo projeto nasce digital e termina
      gravado — a mesma engenharia de rastreabilidade da plataforma aplicada
      à matéria.</p>
    </div>
    <div class="grid g3">
      <div class="card">
        <div class="num">Processo</div>
        <h3>Impressão 3D em Resina</h3>
        <p>Prototipagem de alta definição para peças que exigem acabamento
        fino — base de todo ciclo de desenvolvimento físico.</p>
      </div>
      <div class="card">
        <div class="num">Processo</div>
        <h3>Gravação a Laser 0,1 mm</h3>
        <p>O selo OD e o ID canônico são gravados na peça com precisão de
        0,1 mm. Nenhum item é liberado sem o selo físico.</p>
      </div>
      <div class="card">
        <div class="num">Processo</div>
        <h3>CNC &amp; Prototipagem</h3>
        <p>Usinagem e produção sob demanda, para peças que a aditiva não
        resolve.</p>
      </div>
    </div>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="sec-head">
      <div class="kicker">Estado</div>
      <h2>Onde Está Hoje</h2>
      <p>A FAB está em estruturação: o dicionário de processos e os padrões de
      assinatura física já estão definidos no núcleo documental, e a produção
      ainda não começou. Nada é anunciado como disponível antes de existir.</p>
    </div>
    <div class="grid g2">
      <div class="card">
        <h3>Definido</h3>
        <p>Dicionário de processos, padrão de assinatura física e o protocolo
        de selo OD — o desenho está pronto e documentado.</p>
        <span class="tag gray">Estrutura pronta</span>
      </div>
      <div class="card">
        <h3>Ainda não há</h3>
        <p>Produção em série, catálogo de peças ou prazo. A frente entra em
        operação quando o primeiro projeto físico estiver maduro o bastante
        para ser liberado com selo.</p>
        <span class="tag gray">Em estruturação</span>
      </div>
    </div>
  </div>
</section>
""",
    ),
    (
        "ecossistema-living-systems.html",
        "Omega Drakon · Living Systems — Sistemas Vivos",
        "Ecossistema · Living Systems",
        "Omega Drakon · Living Systems",
        "A expressão literal de “tecnologia que respira”",
        """
<section>
  <div class="wrap">
    <div class="sec-head">
      <div class="kicker">Escopo</div>
      <h2>Sistemas Vivos do Mundo Físico</h2>
      <p>Paludários, dioramas e ecossistemas fechados monitorados. É onde o
      lema da marca deixa de ser metáfora: um sistema que observa, reage e
      mantém algo vivo.</p>
    </div>
    <div class="grid g3">
      <div class="card">
        <div class="num">Conceito</div>
        <h3>Ecossistemas Fechados</h3>
        <p>Ambientes autossustentados onde água, luz e temperatura são
        observados continuamente e corrigidos pelo sistema.</p>
      </div>
      <div class="card">
        <div class="num">Conceito</div>
        <h3>Monitoramento Contínuo</h3>
        <p>As mesmas sondas de saúde da plataforma aplicadas a um organismo:
        sensores, alertas e registro histórico do estado do vivo.</p>
      </div>
      <div class="card">
        <div class="num">Conceito</div>
        <h3>Dioramas &amp; Paludários</h3>
        <p>Peças construídas como narrativa — a fronteira entre manufatura,
        arte e biologia que só o ecossistema inteiro consegue sustentar.</p>
      </div>
    </div>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="sec-head">
      <div class="kicker">Estado</div>
      <h2>Onde Está Hoje</h2>
      <p>Living Systems é a frente mais jovem do ecossistema: está no plano
      conceitual, como parte da narrativa da marca. Não há protótipo
      construído nem prazo anunciado — e é isso que a distingue das frentes
      já em operação.</p>
    </div>
    <div class="card">
      <h3>Conceitual</h3>
      <p>O desenho existe como direção: sistemas que respiram, monitorados
      pela mesma engenharia que sustenta a plataforma. A construção começa
      quando a FAB estiver operacional — as duas frentes são
      interdependentes por natureza.</p>
      <span class="tag gray">Conceitual · sem protótipo</span>
    </div>
  </div>
</section>
""",
    ),
    (
        "ecossistema-nicoly-valentina.html",
        "Nicoly Valentina — Arte, Design e Semi-Joias Autorais",
        "Ecossistema · Nicoly Valentina",
        "Nicoly Valentina",
        "Ciclos fechados. Encerrados, nunca reeditados.",
        """
<section>
  <div class="wrap">
    <div class="sec-head">
      <div class="kicker">Escopo</div>
      <h2>Arte, Design e Semi-Joias Autorais</h2>
      <p>A frente artística do ecossistema. Cada coleção nasce em ciclo
      fechado: quando termina, termina — nenhuma peça é reeditada. A
      autenticidade é gravada a laser e o registro é privado, por ID.</p>
    </div>
    <div class="grid g3">
      <div class="card">
        <div class="num">Princípio</div>
        <h3>Ciclos Fechados</h3>
        <p>Coleções têm começo, meio e fim. O encerramento é definitivo: a
        raridade não é discurso, é consequência do desenho.</p>
      </div>
      <div class="card">
        <div class="num">Princípio</div>
        <h3>Assinatura a Laser</h3>
        <p>Cada peça recebe a assinatura <b>OD // NV – SIGIL</b> e um ID único
        no formato NV-[COLEÇÃO]-[HASH] — ex.: NV-ABI-7F3A — gravados com
        micro-gravação de 2 a 5 mm.</p>
      </div>
      <div class="card">
        <div class="num">Princípio</div>
        <h3>Registro Privado</h3>
        <p>O cartão de autenticidade vem com QR: quem tem o QR é o dono. O
        registro é privado e a verificação é pública.</p>
      </div>
    </div>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="sec-head">
      <div class="kicker">Coleções</div>
      <h2>Ciclos Previstos</h2>
      <p>As três primeiras coleções têm os sigilos já desenhados e
      selados no núcleo da marca. Nenhuma delas está à venda ainda.</p>
    </div>
    <div class="grid g3">
      <div class="card"><h3>Abissal</h3><p>Primeiro ciclo. Em criação.</p><span class="tag gray">Em criação</span></div>
      <div class="card"><h3>Draconis</h3><p>Segundo ciclo. Sigilo desenhado.</p><span class="tag gray">Prevista</span></div>
      <div class="card"><h3>Lumen Nox</h3><p>Terceiro ciclo. Sigilo desenhado.</p><span class="tag gray">Prevista</span></div>
    </div>
    <div class="pleiade-note">Quando a primeira peça for liberada, ela
    aparece no <a href="/site/verificacao.html">Registro Mestre</a> — e
    qualquer um poderá conferir a autenticidade pelo ID gravado na peça.</div>
  </div>
</section>
""",
    ),
]


def main() -> int:
    for arquivo, titulo, kicker, h1, tagline, corpo in PAGINAS:
        html = f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titulo}</title>
<meta name="description" content="{kicker} — Omega Drakon. {tagline}.">
<link rel="icon" href="/site/favicon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;800&family=Montserrat:wght@300;400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/site/od.css">
</head>
<body>

{NAV}<header class="compacto">
  <div class="wrap">
    <div><span class="badge">{kicker}</span></div>
    <h1>{h1}</h1>
    <div class="tagline">{tagline}</div>
    <p class="migalha"><a href="/site">Início</a> &nbsp;/&nbsp;
       <a href="/site#ecossistema">Ecossistema</a> &nbsp;/&nbsp; {h1}</p>
  </div>
</header>

{corpo}
{RODAPE}"""
        destino = SITE / arquivo
        destino.write_text(html, encoding="utf-8")
        print(f"  {arquivo}  ({len(html)} bytes)")
    print(f"{len(PAGINAS)} páginas geradas em {SITE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
