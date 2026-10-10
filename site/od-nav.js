/* ---------------------------------------------------------------------------
   OMEGA DRAKON — comportamento compartilhado do site (2026-10-10)
   ---------------------------------------------------------------------------
   Dois comportamentos, sem dependência externa:

   1. MENU ⋮ — o mesmo ícone de três pontos do app. A nav antiga era uma
      fileira de 10 links que estourava a altura fixa e CORTAVA o texto
      (pedido do dono: "Divisória NAV está cortando os textos do Menu").
      Agora os links abrem num painel; Esc ou clique fora fecha.

   2. VOLTAR AO TOPO — círculo que aparece só depois de rolar.
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
})();
