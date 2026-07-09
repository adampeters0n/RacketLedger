document.addEventListener('DOMContentLoaded', function () {
    const path = window.location.pathname.replace(/\/+$/, '');
    /* Aktivní záložka */
    const tests = [
      ['nav-treneri',    /^\/admin\/core\/(?:treneri(?:\/|$)|trening\/treneri(?:\/|$))/],
      ['nav-treningy',   /^\/admin\/core\/trening(?!\/treneri)(\/|$)/],
      ['nav-cenik',      /^\/admin\/core\/cenik(\/|$)/],
      ['nav-hraci',      /^\/admin\/core\/hrac(\/|$)/],
      ['nav-platby',     /^\/admin\/core\/transakce(\/|$)/],
      ['nav-vyuctovani', /^\/admin\/core\/vyuctovani(\/|$)/],
      ['nav-uzivatele',  /^\/admin\/auth\/(?:user|group)(\/|$)/],
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
