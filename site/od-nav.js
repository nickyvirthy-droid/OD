/* ---------------------------------------------------------------------------
   OMEGA DRAKON — comportamento compartilhado do site (2026-10-10)
   ---------------------------------------------------------------------------
   Três comportamentos, sem dependência externa:

   1. MENU ⋮ — o mesmo ícone de três pontos do app. A nav antiga era uma
      fileira de 10 links que estourava a altura fixa e CORTAVA o texto
      (pedido do dono: "Divisória NAV está cortando os textos do Menu").
      Agora os links abrem num painel; Esc ou clique fora fecha.

   2. VOLTAR AO TOPO — círculo que aparece só depois de rolar.

   3. TEMA claro/escuro (2026-10-16, TODO §3.8) — o botão é INJETADO aqui
      (e não nas 11 páginas) de propósito: o HTML do menu já se duplicou
      uma vez e as páginas divergiram. O ciclo é segue-o-aparelho →
      claro → escuro, a preferência vive no PERFIL (servidor, via
      /auth/me e /profile/preferences) com cópia em localStorage para o
      site abrir certo mesmo sem rede/sem conta.
   --------------------------------------------------------------------------- */
(function () {
  'use strict';

  /* --- 1. Menu ⋮ ------------------------------------------------------- */
  var toggle = document.querySelector('.nav-toggle');
  var painel = document.getElementById('navPanel');

  if (toggle && painel) {
    var abrir = function (sim) {
      painel.classList.toggle('aberto', sim);
      toggle.setAttribute('aria-expanded', sim ? 'true' : 'false');
    };
    var alternar = function () {
      abrir(!painel.classList.contains('aberto'));
    };

    toggle.addEventListener('click', function (evento) {
      evento.stopPropagation();   // não deixa o clique vazar pro document
      alternar();
    });

    // Clicar num link fecha o painel (a navegação segue normalmente).
    painel.addEventListener('click', function (evento) {
      if (evento.target.closest('a')) abrir(false);
    });

    // Clique fora fecha.
    document.addEventListener('click', function (evento) {
      if (!painel.classList.contains('aberto')) return;
      if (painel.contains(evento.target) || toggle.contains(evento.target)) return;
      abrir(false);
    });

    // Esc fecha — acessibilidade.
    document.addEventListener('keydown', function (evento) {
      if (evento.key === 'Escape') abrir(false);
    });
  }

  /* --- 2. Voltar ao topo ------------------------------------------------ */
  var topo = document.getElementById('toTop');
  if (topo) {
    var limite = 400;
    var marcado = false;
    window.addEventListener('scroll', function () {
      if (marcado) return;
      marcado = true;
      window.requestAnimationFrame(function () {
        topo.classList.toggle('visivel', window.scrollY > limite);
        marcado = false;
      });
    }, { passive: true });

    topo.addEventListener('click', function () {
      var suave = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      window.scrollTo({ top: 0, behavior: suave ? 'smooth' : 'auto' });
    });
  }

  /* --- 3. Tema claro/escuro ------------------------------------------- */
  var TEMA_CHAVE = 'od_theme';              // cópia local (cache offline)
  var TEMA_VALIDOS = ['system', 'light', 'dark'];
  var TEMA_ICONES = { system: '🌗', light: '☀️', dark: '🌙' };
  var TEMA_ROTULOS = {
    system: 'Tema: segue o aparelho', light: 'Tema: claro', dark: 'Tema: escuro'
  };
  var TEMA_CICLO = { system: 'light', light: 'dark', dark: 'system' };

  function temaLido() {
    try {
      var valor = localStorage.getItem(TEMA_CHAVE);
      return TEMA_VALIDOS.indexOf(valor) >= 0 ? valor : 'system';
    } catch (erro) { return 'system'; }
  }

  function temaResolvido(pref) {
    if (pref === 'light' || pref === 'dark') return pref;
    return window.matchMedia('(prefers-color-scheme: light)').matches
      ? 'light' : 'dark';
  }

  /* O ciclo tem 3 estados, mas NENHUM clique pode cair numa tela igual à
     anterior: "escuro → segue o aparelho" num aparelho escuro (e "claro →
     segue o aparelho" num claro) não muda nada visualmente — o dono
     relatou "às vezes não funciona" (16/10). Quando o próximo estado
     resolve para a MESMA cor do atual, pula para o seguinte: todo clique
     pinta. Os 3 estados continuam válidos (o app tem o rádio completo e
     "segue o aparelho" segue sendo o padrão de quem nunca escolheu). */
  function temaProximo(pref) {
    var atual = temaResolvido(pref);
    var proximo = TEMA_CICLO[pref] || 'system';
    if (temaResolvido(proximo) === atual) proximo = TEMA_CICLO[proximo] || 'system';
    return proximo;
  }

  function temaAplicar(pref) {
    var raiz = document.documentElement;
    if (pref === 'system') raiz.removeAttribute('data-theme');
    else raiz.setAttribute('data-theme', pref);
    raiz.style.colorScheme = temaResolvido(pref);
    var botao = document.getElementById('odTema');
    if (!botao) return;
    botao.textContent = TEMA_ICONES[pref] || TEMA_ICONES.system;
    botao.setAttribute('aria-label', TEMA_ROTULOS[pref] || TEMA_ROTULOS.system);
    botao.title = (TEMA_ROTULOS[pref] || '') + ' (toque para trocar)';
  }

  function temaSessao() {
    try { return localStorage.getItem('od_session_token') || ''; }
    catch (erro) { return ''; }
  }

  function temaGravarLocal(pref) {
    try { localStorage.setItem(TEMA_CHAVE, pref); } catch (erro) {}
  }

  // Best-effort puro: sem conta (ou sem rede) o local já resolve o tema e
  // o servidor fica sabendo na próxima vez que houver os dois.
  function temaSalvarNoPerfil(pref) {
    var token = temaSessao();
    if (!token) return;
    try {
      fetch('/profile/preferences', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + token
        },
        body: JSON.stringify({ theme: pref })
      }).catch(function () {});
    } catch (erro) {}
  }

  // O servidor é a verdade da CONTA; o localStorage é o cache que evita o
  // "pisca" de tema errado. Se o perfil tem outra escolha (feita no app,
  // por exemplo), ela vence na primeira visita a uma página com a sessão.
  // A promise (e a RESPOSTA) é reaproveitada pelo acesso do menu (seção
  // 6): uma ida à /auth/me alimenta tema + Admin, sem chamada duplicada.
  function temaSincronizar() {
    var token = temaSessao();
    if (!token) return Promise.resolve(null);
    try {
      return fetch('/auth/me', { headers: { 'Authorization': 'Bearer ' + token } })
        .then(function (resp) { return resp.ok ? resp.json() : null; })
        .then(function (dados) {
          var doServidor = dados && dados.preferences && dados.preferences.theme;
          if (TEMA_VALIDOS.indexOf(doServidor) >= 0 && doServidor !== temaLido()) {
            temaGravarLocal(doServidor);
            temaAplicar(doServidor);
          }
          return dados;                 // quem consome é o acesso do menu
        }).catch(function () { return null; });
    } catch (erro) { return Promise.resolve(null); }
  }

  function temaMontarBotao() {
    if (document.getElementById('odTema')) return;
    var botao = document.createElement('button');
    botao.type = 'button';
    botao.id = 'odTema';
    botao.className = 'nav-tema';
    var ancora = document.querySelector('.nav-toggle');
    if (ancora && ancora.parentNode) {
      ancora.parentNode.insertBefore(botao, ancora);
      return;
    }
    if (document.body) {
      botao.style.position = 'fixed';
      botao.style.right = '16px';
      botao.style.bottom = '16px';
      botao.style.zIndex = '200';
      botao.style.background = 'var(--bg2)';
      document.body.appendChild(botao);
    }
  }

  function temaIniciar() {
    temaAplicar(temaLido());          // 1. pinta com o cache (sem pisca)
    temaMontarBotao();                // 2. botão no canto do menu
    var botao = document.getElementById('odTema');
    if (botao) {
      botao.addEventListener('click', function () {
        var proximo = temaProximo(temaLido());
        temaGravarLocal(proximo);
        temaAplicar(proximo);
        temaSalvarNoPerfil(proximo);
      });
    }
    // 3. o perfil manda (quando há sessão) e o sistema avisa quando muda.
    // A MESMA resposta entra no acesso do menu (seção 6): uma ida só.
    temaSincronizar().then(acessoAdmin);
    try {
      window.matchMedia('(prefers-color-scheme: light)')
        .addEventListener('change', function () {
          if (temaLido() === 'system') temaAplicar('system');
        });
    } catch (erro) {}
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', temaIniciar);
  } else {
    temaIniciar();
  }

  /* --- 4. CHIP VIVO DO TOPO (2026-10-17, formato Órion) ---------------
     Versão e estado REAIS na badge do herói, pelas rotas públicas
     /app/version e /health. Sem rede (ou com o núcleo fora) o HTML
     estático continua verdadeiro: o ponto fica cinza (estado
     desconhecido) e o texto do arquivo permanece — nunca pinta verde de
     mentira. Só escreve se os elementos existirem: as outras páginas do
     site seguem intactas. */
  function chipVivo() {
    var ver = document.getElementById('odSiteVer');
    var on = document.getElementById('odSiteOn');
    if (ver) {
      fetch('/app/version')
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (d && d.version) ver.textContent = 'v' + d.version;
        }).catch(function () {});
    }
    if (on) {
      fetch('/health')
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (!d) return;
          on.className = 'od-site-on ' + (d.ok ? 'ok' : 'err');
        }).catch(function () {});
    }
  }
  chipVivo();

  /* --- 5. MENU LATERAL (2026-10-20, formato Órion do dono) -------------
     A referência dele (Sistema Órion, analisada na v1.39.0) traz barra
     fixa à esquerda: marca em cima, itens embaixo, botão de recolher.
     Este bloco MONTA essa barra clonando os MESMOS links do painel ⋮ —
     o HTML do menu continua existindo num lugar só, o que mata a
     divergência que já aconteceu entre as páginas. Só monta onde há
     menu (as 11 páginas); sem elementos, sai sem erro (o harness de
     teste do tema segue limpo). Telas estreitas ficam com o ⋮ de
     sempre; o estado recolhido fica no localStorage.
     ---------------------------------------------------------------------- */
  /* Ícones dos itens (pedido do dono 20/10: "quando o menu retrai fica
     pedaços de palavras, seria melhor ícones"). Tabela POR HREF na MESMA
     fonte única dos links; o resolvedor manda no "#ancora" (as variações
     "/site#anc" e "/site/pag.html#anc" são o MESMO item — as 12 páginas
     têm menus divergentes de propósito). Fora da tabela: "•", nunca
     palavra cortada — e a guarda de cobertura (test_api) obriga a tabela
     a cobrir TODOS os hrefs de TODOS os menus + Painel/Admin. */
  var ICONES = {
    '#marca': '🐉', '#ecossistema': '🌌', '#sistemas': '⚙️',
    '#produtos': '📦', '#autenticidade': '🔐', '#historico': '🕰️',
    '#pleiade': '✨', '#sobre': 'ℹ️', '#download': '📲',
    '/site/loja.html': '🛒', '/site/protomaps.html': '🗺️',
    '/site/verificacao.html': '🔍', '/site/avatares.html': '🎭',
    '/site/historico.html': '🕰️', '/site/index.html': '🐉',
    '/site': '🌐', '/dashboard': '🖥️', '/chat': '💬',
    '/admin': '🛡️'
  };
  function iconeDe(href) {
    var h = String(href || '');
    var anc = h.indexOf('#');
    if (anc >= 0) h = h.slice(anc);
    return ICONES[h] || '•';
  }
  /* Um item da barra = link com title (hover quando recolhido) + ícone
     + rótulo em <span class="od-rot">. O rótulo FICA no DOM (leitor de
     tela) e some só no CSS da recolhida; link com filho (imagem) não é
     reestruturado. Usado pelo clonar E pelo Admin (mesma casa, mesma
     forma). */
  function lateralItem(copia, href, rotulo) {
    if (!copia.title) copia.title = rotulo;
    if (copia.children && copia.children.length) return copia;
    copia.textContent = '';
    var ico = document.createElement('span');
    ico.className = 'od-ico';
    ico.setAttribute('aria-hidden', 'true');
    ico.textContent = iconeDe(href);
    var rot = document.createElement('span');
    rot.className = 'od-rot';
    rot.textContent = rotulo;
    copia.appendChild(ico);
    copia.appendChild(rot);
    return copia;
  }

  function lateralMontar() {
    if (document.getElementById('odLateral')) return;      // idempotente
    var painel = document.getElementById('navPanel');
    var itens = painel && painel.querySelectorAll
      ? painel.querySelectorAll('a') : null;
    if (!itens || !itens.length) return;                   // ex.: sem menu
    if (!document.createElement || !document.body) return;
    var marca = document.querySelector('nav .brand');

    var aside = document.createElement('aside');
    aside.id = 'odLateral';
    aside.className = 'od-lateral';
    aside.setAttribute('aria-label', 'Menu lateral');

    var topo = document.createElement('div');
    topo.className = 'od-lateral-topo';
    if (marca) topo.appendChild(marca.cloneNode(true));
    var botao = document.createElement('button');
    botao.className = 'od-lateral-btn';
    botao.setAttribute('aria-label', 'Recolher menu lateral');
    botao.textContent = '\u2630';                          // ☰
    topo.appendChild(botao);
    aside.appendChild(topo);

    /* O contêiner dos links é um <div> e NUNCA um <nav>: o od.css tem
       `nav { position: fixed; top:0; left:0; right:0 }` global (a barra do
       topo) e um <nav> aqui viraria uma faixa de ponta a ponta por cima
       da página — defeito real achado e corrigido em 20/10 com render. */
    var links = document.createElement('div');
    links.className = 'od-lateral-links';
    for (var i = 0; i < itens.length; i++) {
      var copia = itens[i].cloneNode(true);
      links.appendChild(lateralItem(copia, copia.getAttribute('href') || '',
                                    (copia.textContent || '').trim()));
    }
    aside.appendChild(links);
    document.body.appendChild(aside);
    document.documentElement.classList.toggle('od-com-lateral', true);

    var recolhido = false;
    try { recolhido = localStorage.getItem('od_lateral') === 'recolhido'; }
    catch (erro) {}
    document.documentElement.classList.toggle('od-lateral-recolhido', recolhido);

    botao.addEventListener('click', function () {
      var agora = !document.documentElement
        .classList.contains('od-lateral-recolhido');
      document.documentElement.classList.toggle('od-lateral-recolhido', agora);
      try {
        localStorage.setItem('od_lateral', agora ? 'recolhido' : 'aberto');
      } catch (erro) {}
    });
  }
  /* --- 6. ACESSO PELO MENU PRINCIPAL (2026-10-20, pedido do dono) -----
     "o acesso que poderia ser pelo menu principal, se estiver logado
     entra": o item Painel entra no ⋮ ANTES da clonagem (os dois menus
     saem dos MESMOS links) e leva ao /dashboard — logado, entra direto;
     sem sessão, o /dashboard manda pro /chat (login). Com sessão de
     DONO, o Admin entra nos DOIS (⋮ e barra) na RESPOSTA do /auth/me
     que o tema já busca (uma ida à API, resposta compartilhada — a
     promise vem da seção 3). Falhou a rede ou sem sessão? Só Painel:
     o menu nunca fica esperando rede nem adivinha papel.
     ---------------------------------------------------------------------- */
  function acessoInserir(container, href, rotulo) {
    if (!container || container.querySelector('a[href="' + href + '"]')) return;
    var link = document.createElement('a');
    link.setAttribute('href', href);
    link.textContent = rotulo;
    // Fica junto dos vizinhos de sistema (Chat) — ou no fim, se a
    // página divergiu e não tem os links padrão (a divergência do menu
    // já aconteceu; o item NUNCA some por causa disso).
    var antes = container.querySelector('a[href="/chat"]') ||
      container.querySelector('a[href="#download"]');
    if (antes && antes.parentNode) antes.parentNode.insertBefore(link, antes);
    else container.appendChild(link);
  }

  function acessoMontar() {
    acessoInserir(document.getElementById('navPanel'), '/dashboard', 'Painel');
  }

  function acessoAdmin(dados) {
    if (!dados || dados.role !== 'admin') return;
    acessoInserir(document.getElementById('navPanel'), '/admin', 'Admin');
    var barra = document.getElementById('odLateral');
    var links = barra && barra.querySelector
      ? barra.querySelector('.od-lateral-links') : null;
    if (links && !links.querySelector('a[href="/admin"]')) {
      var a = document.createElement('a');
      a.setAttribute('href', '/admin');
      links.appendChild(lateralItem(a, '/admin', 'Admin'));
    }
  }

  acessoMontar();     // Painel no ⋮ ANTES do clonar (barra herda o item)
  lateralMontar();
})();
