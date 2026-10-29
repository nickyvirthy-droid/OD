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

  /* O ciclo percorre os 3 estados SEMPRE (system → claro → escuro → system),
     como o app (rádio completo). A correção anterior — pular o "system" quando
     ele resolvia pra mesma cor — fazia o dono travar em claro↔escuro sem
     nunca voltar ao automático (§3.8). O "clique morto" (uma tela igual à
     anterior) é resolvido com FEEDBACK, não com salto: no "system" a raiz
     ganha data-tema-modo="auto" e o botão mostra o ícone de "segue o
     aparelho", então o clique SEMPRE muda o estado visível do controle,
     mesmo quando a cor do tema não muda. */
  function temaProximo(pref) {
    return TEMA_CICLO[pref] || 'system';
  }

  function temaAplicar(pref) {
    var raiz = document.documentElement;
    if (pref === 'system') {
      raiz.removeAttribute('data-theme');
      raiz.setAttribute('data-tema-modo', 'auto');   // feedback do automático
    } else {
      raiz.setAttribute('data-theme', pref);
      raiz.setAttribute('data-tema-modo', 'fixo');   // escolha explícita
    }
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
    '/site/radio.html': '📻',
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

  /* --- 7. PLAYER DA RÁDIO NO MENU LATERAL (29/10, pedido do dono) ------
     "Toda vez que mudo de página a rádio para. O player deveria ficar no
     menu lateral, assim iria permanecer tocando enquanto navego do site."

     O site é MULTIPÁGINA: navegar recarrega o documento e mata o
     <audio> — só mudar o lugar do elemento não faria nada continuar.
     O que atravessa a troca é o ESTADO, no localStorage (`od_radio`):
     quem estava ouvindo tem a PRÓXIMA página religando o stream assim
     que a barra monta, e a pausa também sobrevive. O custo é o próprio
     carregamento da página, e o rótulo NUNCA mente: se o navegador
     bloquear o início automático (origem sem interação prévia), o
     controle vira "retomar" em vez de fingir que está no ar.

     Dois controles do MESMO estado: dentro da barra lateral (tela
     larga) e uma pílula flutuante que só aparece com som — abaixo de
     1024px a barra é `display:none` e sem a pílula não haveria como
     parar o áudio que a página nova religou. Um SÓ <audio> por página,
     filho do body e escondido: recolher a barra não pode encerrar a
     transmissão. Quem toca sozinho é a página da rádio (radio.html),
     que delega para window.odRadio em vez de ter um segundo player.
     -------------------------------------------------------------------- */
  var RADIO_CHAVE = 'od_radio';
  var RADIO_ESTADOS = {
    parado:  { ico: '▶', rot: 'Rádio',    aria: 'Tocar a rádio Nicky' },
    tocando: { ico: '⏸', rot: 'No ar',    aria: 'Pausar a rádio' },
    retomar: { ico: '▶', rot: 'Retomar',  aria: 'Retomar a rádio' },
    erro:    { ico: '⚠', rot: 'Sem sinal', aria: 'Tentar de novo a rádio' }
  };
  var radio = { audio: null, estado: 'parado', controles: [], ouvintes: [] };

  function radioFonte() {
    // Mesmo caminho que o botão da página da rádio usava: por https
    // (Funnel/tailnet) o stream sai da MESMA origem em /radio.mp3; por
    // http (rede local) vai direto no icecast da 8600 — fonte https
    // nunca carrega http (mixed content). Medido em 29/10: o icecast
    // ecoa o Origin em Access-Control-Allow-Origin, então o
    // crossorigin="anonymous" do elemento continua seguro.
    if (location.protocol === 'https:') return location.origin + '/radio.mp3';
    return 'http://' + location.hostname + ':8600/radio.mp3';
  }

  function radioQuerOuvir() {
    try { return localStorage.getItem(RADIO_CHAVE) === 'tocando'; }
    catch (erro) { return false; }
  }

  function radioGuardar(ligado) {
    try { localStorage.setItem(RADIO_CHAVE, ligado ? 'tocando' : 'parado'); }
    catch (erro) {}
  }

  function radioPintar() {
    var texto = RADIO_ESTADOS[radio.estado] || RADIO_ESTADOS.parado;
    for (var i = 0; i < radio.controles.length; i++) {
      var c = radio.controles[i];
      c.ico.textContent = texto.ico;
      c.rot.textContent = texto.rot;
      c.btn.setAttribute('aria-label', texto.aria);
      c.btn.title = texto.aria;
      c.caixa.classList.toggle('ativo', radio.estado !== 'parado');
    }
    for (var j = 0; j < radio.ouvintes.length; j++) {
      try { radio.ouvintes[j](radio.estado); } catch (erro) {}
    }
  }

  function radioEstado(estado) {
    radio.estado = estado;
    radioPintar();
  }

  function radioTocar() {
    if (!radio.audio) return;
    if (!radio.audio.src) radio.audio.src = radioFonte();
    var promessa = null;
    try { promessa = radio.audio.play(); }
    catch (erro) { radioEstado('erro'); return; }
    // O cache NÃO é apagado aqui: 'retomar'/'erro' continuam querendo
    // ouvir, e é isso que a próxima página religa. Só a pausa do
    // ouvinte (radioAlternar) grava 'parado'.
    if (promessa && typeof promessa.catch === 'function') {
      promessa.catch(function () { radioEstado('retomar'); });
    }
  }

  function radioAlternar() {
    if (!radio.audio) return;
    if (radio.estado === 'tocando') {
      radioGuardar(false);          // pausa EXPLícita: atravessa a troca
      radio.audio.pause();
      radioEstado('parado');
    } else {
      radioTocar();
    }
  }

  function radioControle(flutuante) {
    var caixa = document.createElement('div');
    caixa.id = flutuante ? 'odRadioFlut' : 'odRadio';
    caixa.className = flutuante ? 'od-radio od-radio-flut' : 'od-radio';
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'od-radio-btn';
    var ico = document.createElement('span');
    ico.className = 'od-radio-ico';
    ico.setAttribute('aria-hidden', 'true');
    btn.appendChild(ico);
    var rot = document.createElement('span');
    rot.className = 'od-radio-rot';
    caixa.appendChild(btn);
    caixa.appendChild(rot);
    btn.addEventListener('click', function (evento) {
      if (evento && evento.stopPropagation) evento.stopPropagation();
      radioAlternar();
    });
    var controle = { caixa: caixa, btn: btn, ico: ico, rot: rot };
    radio.controles.push(controle);
    return controle;
  }

  function radioMontar() {
    // Só onde existe MENU (as 13 páginas): sem barra não há o que
    // ancorar — e o harness de tema (página sem navPanel) sai sem erro.
    var barra = document.getElementById('odLateral');
    if (!barra || !document.createElement || !document.body) return;

    var audio = document.createElement('audio');
    audio.className = 'od-radio-audio';
    audio.preload = 'none';
    audio.crossOrigin = 'anonymous';
    audio.controls = false;
    // O estado sai dos EVENTOS do elemento (prova real de que tocou),
    // nunca do resultado de uma chamada — e a pausa do ouvinte é quem
    // grava, para o navegador não apagar o pedido ao descarregar.
    audio.addEventListener('play', function () {
      radioGuardar(true);
      radioEstado('tocando');
    });
    audio.addEventListener('pause', function () { radioEstado('parado'); });
    audio.addEventListener('error', function () { radioEstado('erro'); });
    radio.audio = audio;
    document.body.appendChild(audio);

    var controle = radioControle(false);
    var links = barra.querySelector('.od-lateral-links');
    if (links && links.parentNode === barra) barra.insertBefore(controle.caixa, links);
    else barra.appendChild(controle.caixa);
    document.body.appendChild(radioControle(true).caixa);

    // O mais cedo possível: encurta a lacuna da troca de página.
    if (radioQuerOuvir()) radioTocar();
    else radioEstado('parado');
  }

  // Contrato para quem quiser o MESMO player (a página da rádio). O
  // elemento é único por página — dois players brigariam pelo estado.
  window.odRadio = {
    alternar: function () { radioAlternar(); },
    estado: function () { return radio.estado; },
    aoMudar: function (fn) { if (typeof fn === 'function') radio.ouvintes.push(fn); }
  };

  acessoMontar();     // Painel no ⋮ ANTES do clonar (barra herda o item)
  lateralMontar();
  radioMontar();      // depois da barra: o player é filho dela
})();
