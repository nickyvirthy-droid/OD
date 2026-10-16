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
  function temaSincronizar() {
    var token = temaSessao();
    if (!token) return;
    try {
      fetch('/auth/me', { headers: { 'Authorization': 'Bearer ' + token } })
        .then(function (resp) { return resp.ok ? resp.json() : null; })
        .then(function (dados) {
          var doServidor = dados && dados.preferences && dados.preferences.theme;
          if (TEMA_VALIDOS.indexOf(doServidor) < 0) return;
          if (doServidor === temaLido()) return;
          temaGravarLocal(doServidor);
          temaAplicar(doServidor);
        }).catch(function () {});
    } catch (erro) {}
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
        var proximo = TEMA_CICLO[temaLido()] || 'system';
        temaGravarLocal(proximo);
        temaAplicar(proximo);
        temaSalvarNoPerfil(proximo);
      });
    }
    // 3. o perfil manda (quando há sessão) e o sistema avisa quando muda.
    temaSincronizar();
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
})();
