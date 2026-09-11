document.addEventListener('DOMContentLoaded', function () {
    const path = window.location.pathname.replace(/\/+$/, '');
    /* Aktivní záložka */
    const tests = [
      ['nav-rozvrh',     /^\/admin\/core\/trening\/schedule(\/|$)/],
      ['nav-treneri',    /^\/admin\/core\/(?:treneri(?:\/|$)|trening\/treneri(?:\/|$))/],
      ['nav-treningy',   /^\/admin\/core\/trening(?!\/(?:treneri|schedule))(\/|$)/],
      ['nav-cenik',      /^\/admin\/core\/cenik(\/|$)/],
      ['nav-hraci',      /^\/admin\/core\/hrac(\/|$)/],
      ['nav-platby',     /^\/admin\/core\/transakce(\/|$)/],
      ['nav-vyuctovani', /^\/admin\/core\/vyuctovani(\/|$)/],
      ['nav-nastaveni',  /^\/admin\/(?:nastaveni|auth\/(?:user|group))(\/|$)/],
    ];
    for (const [id, re] of tests) {
      if (re.test(path)) {
        const el = document.getElementById(id);
        if (el){ el.classList.add('is-active'); el.setAttribute('aria-current','page'); }
        break;
      }
    }

    /* Burger / Drawer */
    const burger = document.getElementById('ts-burger');
    const drawer = document.getElementById('ts-drawer');
    const closeBtn = document.getElementById('ts-drawer-close');

    function openDrawer(){
      drawer.classList.add('is-open');
      drawer.removeAttribute('aria-hidden');
      closeBtn && closeBtn.focus();
      document.body.style.overflow = 'hidden';
    }
    function closeDrawer(){
      drawer.classList.remove('is-open');
      drawer.setAttribute('aria-hidden','true');
      burger && burger.focus();
      document.body.style.overflow = '';
    }

    burger && burger.addEventListener('click', openDrawer);
    closeBtn && closeBtn.addEventListener('click', closeDrawer);

    /* Desktop topnav: zmenši font/padding, když delší jazyk přeteče */
    const topnav = document.querySelector('.ts-topnav');
    function fitTopNav() {
      if (!topnav || window.matchMedia('(max-width: 1200px)').matches) {
        if (topnav) topnav.style.removeProperty('--ts-nav-scale');
        return;
      }
      topnav.style.setProperty('--ts-nav-scale', '1');
      const header = document.getElementById('header');
      if (!header) return;
      const brand = document.getElementById('branding');
      const tools = document.getElementById('user-tools');
      const headerW = header.clientWidth;
      const sidePad = 48;
      const brandW = brand ? brand.getBoundingClientRect().width : 0;
      const toolsW = tools ? tools.getBoundingClientRect().width : 0;
      const available = Math.max(180, headerW - Math.max(brandW, toolsW) * 2 - sidePad);
      let scale = 1;
      for (let i = 0; i < 8; i++) {
        topnav.style.setProperty('--ts-nav-scale', String(scale));
        if (topnav.scrollWidth <= available + 1) break;
        scale = Math.max(0.72, scale - 0.04);
      }
      topnav.style.setProperty('--ts-nav-scale', String(scale));
    }
    fitTopNav();
    window.addEventListener('resize', fitTopNav);
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(fitTopNav).catch(function () {});
    }
    drawer && drawer.addEventListener('click', e => { if (e.target === drawer) closeDrawer(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && drawer.classList.contains('is-open')) closeDrawer(); });
    drawer && drawer.querySelectorAll('a').forEach(a => a.addEventListener('click', closeDrawer));

    /* Na stránce Změna hesla přidat formuláři třídu pro CSS bublin */
    if (window.location.pathname.indexOf('password_change') !== -1) {
      var main = document.getElementById('content-main');
      var form = main && main.querySelector('form');
      if (form) form.classList.add('password-change-form');
    }
  });
