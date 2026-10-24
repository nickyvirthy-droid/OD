/* ==========================================================================
   OMEGA DRAKON • PAINEL
   Arquivo: site/admin.js
   Descrição: JS do painel (/dashboard, /admin, /chat) — saiu das strings
              gigantes do Python em 23/10 (dívida técnica §4, item 6) e
              vive aqui como arquivo REAL: editável, `node --check`
              direto e servido estático por /site/{file}.
              Duas seções, na ordem de execução:
                1. od-tema       — 3 estados (segue o aparelho/claro/
                                   escuro) + sincronia com a conta;
                2. formato-Órion — herói, KPIs, barra lateral e glifos.
              O servidor injeta esta tag ANTES do <script> da página
              (`_com_tema` em integrations/api/server.py): script clássico
              bloqueia, então a ordem é garantida — window.odFormato
              existe quando o script da página roda.
   Interface Viva: Nicky Virthy
   Arquiteto: Alex Projeti
   ======================================================================== */

/* ===== SEÇÃO: od-tema ===== */
(function () {
  'use strict';
  var CHAVE = 'od_theme', VALIDOS = ['system', 'light', 'dark'];
  var ICONES = { system: '🌗', light: '☀️', dark: '🌙' };
  var ROTULOS = { system: 'Tema: segue o aparelho', light: 'Tema: claro', dark: 'Tema: escuro' };
  var CICLO = { system: 'light', light: 'dark', dark: 'system' };

  function ler() {
    try {
      var v = localStorage.getItem(CHAVE);
      return VALIDOS.indexOf(v) >= 0 ? v : 'system';
    } catch (e) { return 'system'; }
  }
  function resolvido(pref) {
    if (pref === 'light' || pref === 'dark') return pref;
    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }
  /* O ciclo percorre os 3 estados SEMPRE (system → claro → escuro → system),
     como o app e como o site (§3.8, alinhado em 23/10). A correção anterior
     de pular o "system" quando resolvia pra mesma cor fazia o dono travar em
     claro↔escuro sem voltar ao automático. O "clique morto" é resolvido com
     FEEDBACK: no "system" a raiz fica sem data-theme e com
     data-tema-modo="auto" (o botão mostra "segue o aparelho"). */
  function proximoTema(pref) {
    return CICLO[pref] || 'system';
  }
  function aplicar(pref) {
    var raiz = document.documentElement;
    if (pref === 'system') {
      raiz.removeAttribute('data-theme');             // volta ao automático
      raiz.setAttribute('data-tema-modo', 'auto');    // feedback
    } else {
      raiz.setAttribute('data-theme', resolvido(pref));
      raiz.setAttribute('data-tema-modo', 'fixo');    // escolha explícita
    }
    raiz.style.colorScheme = resolvido(pref);
    var b = document.getElementById('odTema');
    if (!b) return;
    b.textContent = ICONES[pref] || ICONES.system;
    b.setAttribute('aria-label', ROTULOS[pref] || ROTULOS.system);
    b.title = (ROTULOS[pref] || '') + ' (toque para trocar)';
  }
  function cabecalhos() {
    var h = {};
    try {
      var token = localStorage.getItem('od_session_token');
      var chave = localStorage.getItem('od_api_key');
      if (token) h['Authorization'] = 'Bearer ' + token;
      if (chave) h['X-API-Key'] = chave;
    } catch (e) {}
    return h;
  }
  // Best-effort: sem credencial (ou sem rede) só o local vale.
  function salvar(pref) {
    var h = cabecalhos();
    if (!h['Authorization'] && !h['X-API-Key']) return;
    try {
      h['Content-Type'] = 'application/json';
      fetch('/profile/preferences', {
        method: 'PUT', headers: h, body: JSON.stringify({ theme: pref })
      }).catch(function () {});
    } catch (e) {}
  }
  // O PERFIL é a verdade da conta; o localStorage é o cache (sem pisca).
  function sincronizar() {
    var h = cabecalhos();
    if (!h['Authorization'] && !h['X-API-Key']) return;
    try {
      fetch('/auth/me', { headers: h })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          var doServidor = d && d.preferences && d.preferences.theme;
          if (VALIDOS.indexOf(doServidor) < 0) return;
          if (doServidor === ler()) return;
          try { localStorage.setItem(CHAVE, doServidor); } catch (e) {}
          aplicar(doServidor);
        }).catch(function () {});
    } catch (e) {}
  }
  function montar() {
    if (document.getElementById('odTema')) return;
    var cabecalho = document.querySelector('header');
    if (!cabecalho) return;
    var b = document.createElement('button');
    b.type = 'button';
    b.id = 'odTema';
    cabecalho.appendChild(b);
  }
  function iniciar() {
    aplicar(ler());
    montar();
    var b = document.getElementById('odTema');
    if (b) b.addEventListener('click', function () {
      var proximo = proximoTema(ler());
      try { localStorage.setItem(CHAVE, proximo); } catch (e) {}
      aplicar(proximo);
      salvar(proximo);
    });
    sincronizar();
    try {
      window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', function () {
        if (ler() === 'system') aplicar('system');
      });
    } catch (e) {}
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', iniciar);
  } else { iniciar(); }
})();

/* ===== SEÇÃO: od-formato-orion ===== */
(function () {
  'use strict';
  /* od-formato-orion-js — fonte única, injetada pelo _com_tema. Saudação por
     período, relógio de São Paulo, pill de estado e KPIs — tudo lendo as
     MESMAS fontes de sempre (health / version / actions / stats). Sem
     resposta o campo fica "—" (nunca verde de mentira); falha daqui nunca
     derruba a página (try/catch). O /admin repassa os dados do loadSystem
     via pintar(); o /dashboard (todos os usuários) busca sozinho. */
  var nome = "";

  function saudacao() {
    var h = new Date().getHours();
    return h < 5 ? "Boa madrugada" : h < 12 ? "Boa manhã" : h < 18 ? "Boa tarde" : "Boa noite";
  }

  function fmtUptime(s) {
    if (s == null) return "—";
    var d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600),
        m = Math.floor((s % 3600) / 60);
    return (d ? d + "d " : "") + (h ? h + "h " : "") + m + "m";
  }

  function cabecalhos() {
    var h = {};
    try {
      var t = localStorage.getItem("od_session_token");
      var k = localStorage.getItem("od_api_key");
      if (t) h["Authorization"] = "Bearer " + t;
      else if (k) h["X-API-Key"] = k;
    } catch (e) {}
    return h;
  }

  function relogio() {
    var el = document.getElementById("odRelogio");
    if (!el) return;
    el.textContent = new Date().toLocaleTimeString("pt-BR", {
      timeZone: "America/Sao_Paulo", hour12: false
    });
  }

  function pintar(health, stats, acoes) {
    try {
      var ola = document.getElementById("odOla");
      if (!ola) return;  // página sem o cabeçalho (ex.: chat)
      ola.textContent = saudacao() + (nome ? ", " + nome : "");
      document.getElementById("odData").textContent =
        new Date().toLocaleDateString("pt-BR", {
          weekday: "long", day: "2-digit", month: "long", year: "numeric"
        });
      var vivo = !!(health && health.ok);
      var on = document.getElementById("odOn");
      on.className = "pill" + (vivo ? " ok" : " err");
      on.innerHTML = '<span class="od-ponto' + (vivo ? "" : " err") + '"></span>' +
        (vivo ? "ONLINE" : "DEGRADADO");
      var up = (health && health.uptime_s != null) ? health.uptime_s : null;
      if (stats && stats.uptime_s != null) up = stats.uptime_s;
      var upTxt = fmtUptime(up);
      document.getElementById("kpiUptime").textContent = upTxt;
      var chipUp = document.getElementById("odChipUptime");
      if (chipUp) chipUp.textContent = "uptime " + upTxt;
      document.getElementById("kpiAcoes").textContent =
        acoes && acoes.count != null ? acoes.count : "—";
      var nt = stats && stats.nomad_tools;
      document.getElementById("kpiStack").textContent = nt ? nt.up + "/" + nt.total : "—";
      var chipSt = document.getElementById("odChipStack");
      if (chipSt) chipSt.textContent = nt ? "stack " + nt.up + "/" + nt.total : "stack —";
      var ch = (health && health.checks) || {};
      var nomes = Object.keys(ch);
      var bons = nomes.filter(function (n) { return ch[n] && ch[n].ok; }).length;
      document.getElementById("kpiChecks").textContent =
        nomes.length ? bons + "/" + nomes.length : "—";
      var saude = document.getElementById("odSaude");
      if (nomes.length && bons === nomes.length) {
        saude.textContent = "Tudo verde";
      } else if (nomes.length) {
        saude.textContent = bons + " ok · " + (nomes.length - bons) + " alerta";
      }
      document.getElementById("odSaudeDet").textContent =
        nomes.length + " checks · " + ((health && health.status) || "?");
    } catch (e) { /* enfeite vivo: a falha dele não derruba a página */ }
  }

  function buscarJson(url, auth) {
    return fetch(url, auth ? { headers: cabecalhos() } : undefined)
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  function atualizar() {
    if (!document.getElementById("odOla")) return Promise.resolve();
    return Promise.all([
      buscarJson("/health"),                // pública
      buscarJson("/dashboard/stats", true), // dono: uptime/stack (403 vira null)
      buscarJson("/actions", true)          // catálogo (contagem)
    ]).then(function (r) { pintar(r[0], r[1], r[2]); });
  }

  function versao() {
    buscarJson("/app/version").then(function (d) {
      if (!d || !d.version) return;
      var el = document.getElementById("odVer");
      if (el) el.textContent = "v" + d.version;
      var build = document.getElementById("odChipBuild");
      if (build) build.textContent = "build " + (d.version_code || "");
    });
  }

  /* --- Menu lateral (2026-10-20, formato Órion do dono) ------------------
     Barra fixa à esquerda (marca, itens, ☰ de recolher) como na
     referência. Montada AQUI, na fonte única: as TRÊS páginas recebem
     (pedido do dono em 20/10: "chat também pode manter o menu lateral")
     — no /chat só não há herói/KPIs/relogio, porque ele mantém o próprio
     cabeçalho. Itens sempre presentes: Painel, Chat, Site — o Admin só
     entra para papel admin: em /dashboard e /admin o quemAmI da página
     repassa o papel em odFormato.nome; no /chat, quem pergunta é o
     próprio FORMATO (papelChat — a página não tem quemAmI). Estado
     recolhido no localStorage, como no site. */
  function papelChat() {
    var temSessao = false;
    try { temSessao = !!localStorage.getItem("od_session_token"); } catch (e) {}
    if (!temSessao) return;      // anônimo: sem ida à API, sem item Admin
    buscarJson("/auth/me", true).then(function (d) {
      if (d && d.role === "admin") { lateralAdmin(); lateralFerramentas(); }
    });
  }
  function lateralMontar() {
    if (document.getElementById("odLateral")) return;  // idempotente
    var itens = [
      { href: "/dashboard", rot: "Painel", ico: "🖥️" },
      { href: "/chat", rot: "Chat", ico: "💬" },
      { href: "/site", rot: "Site", ico: "🌐" }
    ];
    var aside = document.createElement("aside");
    aside.id = "odLateral";
    aside.className = "od-lateral";
    aside.setAttribute("aria-label", "Menu lateral");
    var marca = '<div class="od-lateral-topo">' +
      '<a class="od-lateral-marca" href="/dashboard">' +
      '<img src="/site/simbolo_minimo.png" alt="OD"></a>' +
      '<button class="od-lateral-btn" aria-label="Recolher menu lateral">' +
      '&#9776;</button></div><div class="od-lateral-links">';
    var html = marca;
    for (var i = 0; i < itens.length; i++) {
      // title primeiro: recolhido, o rótulo some e o hover mostra o nome.
      html += '<a href="' + itens[i].href + '" title="' + itens[i].rot + '">' +
        '<span class="od-ico" aria-hidden="true">' + itens[i].ico + "</span>" +
        '<span class="od-rot">' + itens[i].rot + "</span></a>";
    }
    aside.innerHTML = html + "</div>";
    document.body.appendChild(aside);
    document.documentElement.classList.toggle("od-com-lateral", true);
    var recolhido = false;
    try { recolhido = localStorage.getItem("od_lateral") === "recolhido"; }
    catch (e) {}
    document.documentElement.classList.toggle("od-lateral-recolhido", recolhido);
    var btn = aside.querySelector(".od-lateral-btn");
    if (btn) btn.addEventListener("click", function () {
      var agora = !document.documentElement
        .classList.contains("od-lateral-recolhido");
      document.documentElement.classList.toggle("od-lateral-recolhido", agora);
      try {
        localStorage.setItem("od_lateral", agora ? "recolhido" : "aberto");
      } catch (e) {}
    });
  }

  function lateralAdmin() {
    var l = document.getElementById("odLateral");
    if (!l || l.querySelector('a[href="/admin"]')) return;
    var links = l.querySelector(".od-lateral-links");
    if (!links) return;
    var a = document.createElement("a");
    a.setAttribute("href", "/admin");
    a.setAttribute("title", "Admin");
    a.innerHTML = '<span class="od-ico" aria-hidden="true">🛡️</span>' +
      '<span class="od-rot">Admin</span>';
    links.appendChild(a);
  }

  function lateralFerramentas() {
    var l = document.getElementById("odLateral");
    if (!l || l.querySelector('a[href="/f/caderno/"]')) return;
    var links = l.querySelector(".od-lateral-links");
    if (!links) return;
    // Portário (22/10, pedido do dono): as 5 ferramentas no MENU, abrindo
    // DENTRO do site — mesma aba (ele reclamou da aba nova). Gate é a
    // sessão: sem login o /f/... leva para o formulário do chat.
    // As 4 do portário (a ferramenta de dev saiu em 22/10 — decisão do
    // dono: fica em casa/tailnet). Nenhuma senha extra: o portário é o
    // único gate.
    var fs = [
      { href: "/f/caderno/", rot: "Caderno", ico: "📝" },
      { href: "/f/cyberchef/", rot: "CyberChef", ico: "🧪" },
      { href: "/f/caixa/", rot: "Caixa", ico: "📂" },
      { href: "/f/cofre/", rot: "Cofre", ico: "🔒" }
    ];
    for (var i = 0; i < fs.length; i++) {
      var a = document.createElement("a");
      a.setAttribute("href", fs[i].href);
      a.setAttribute("title", fs[i].rot);
      a.innerHTML = '<span class="od-ico" aria-hidden="true">' + fs[i].ico +
        '</span><span class="od-rot">' + fs[i].rot + "</span>";
      links.appendChild(a);
    }
  }

  function topoBotao() {
    // Botão flutuante "voltar ao topo" (pedido do dono, 22/10 — Painel e
    // Admin; no chat o corpo não rola, mas o mesmo botão é inofensivo).
    if (document.getElementById("odTopo")) return;
    var b = document.createElement("button");
    b.id = "odTopo";
    b.setAttribute("aria-label", "Voltar ao topo");
    b.title = "Voltar ao topo";
    b.textContent = "↑";
    b.style.cssText = "position:fixed;right:18px;bottom:18px;z-index:40;" +
      "width:42px;height:42px;border-radius:50%;border:1px solid var(--border);" +
      "background:var(--bg2);color:var(--text);font-size:1.1rem;cursor:pointer;" +
      "display:none;box-shadow:0 4px 14px rgba(0,0,0,.35)";
    b.addEventListener("click", function () {
      window.scrollTo({top: 0, behavior: "smooth"});
    });
    window.addEventListener("scroll", function () {
      b.style.display = window.scrollY > 320 ? "block" : "none";
    }, {passive: true});
    document.body.appendChild(b);
  }

  // Interface para a página: o /admin chama pintar() no refresh do
  // loadSystem; quem logar entrega o nome (o cabeçalho chama pelo nome) —
  // e o papel, que decide o item Admin do menu lateral.
  window.odFormato = {
    nome: function (n, papel) {
      if (!n) return;
      nome = n;
      var ola = document.getElementById("odOla");
      if (ola) ola.textContent = saudacao() + ", " + nome;
      if (papel === "admin") { lateralAdmin(); lateralFerramentas(); }
    },
    pintar: pintar,
    atualizar: atualizar
  };

  // Início adiado até DOMContentLoaded: assim a PÁGINA consegue declarar
  // a bandeira odFormatoGerenciado antes (o /admin declara — o
  // loadSystem dele já busca health/stats/actions e repassa via
  // pintar(); o herói não repete as mesmas requests). Relógio e versão
  // continuam de graça; a busca dupla não.
  function iniciar() {
    // A barra vale nas TRÊS páginas (pedido 20/10): monta ANTES do cedo.
    // Sem #odOla só não há herói/KPIs/relogio/atualizar — o chat mantém
    // o próprio cabeçalho, e o papel dele o FORMATO pergunta sozinho.
    lateralMontar();
    if (!document.getElementById("odOla")) { papelChat(); return; }
    topoBotao();   // só Painel/Admin montam (o chat não rola o corpo — 22/10)
    relogio();
    setInterval(relogio, 1000);
    versao();
    if (!window.odFormatoGerenciado) atualizar();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", iniciar);
  } else { iniciar(); }
})();
