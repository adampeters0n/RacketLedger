// static/home/landing.js
(() => {
  const c = document.getElementById('bg');
  if (!c) return;
  const ctx = c.getContext('2d');

  let DPR = Math.max(1, window.devicePixelRatio || 1);
  let balls = [];
  
  // ✅ PATCH: Timer pro "debounce" (zpomalení) resize události
  let resizeTimer;

  function resize() {
    DPR = Math.max(1, window.devicePixelRatio || 1);
    c.width  = innerWidth * DPR;
    c.height = innerHeight * DPR;
    // nastav transform, ať se nepřeskaluje násobně
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }

  function rand(a, b) { return a + Math.random() * (b - a); }

  // Tato funkce se teď zavolá POUZE JEDNOU při načtení stránky
  function makeBalls() {
    const isMobile = innerWidth < 768;
    const n = isMobile ? 12 : 22; // Méně míčků na mobilu
    const minSize = isMobile ? 20 : 26;
    const maxSize = isMobile ? 48 : 64; // Menší míčky na mobilu
    
    balls = Array.from({ length: n }, () => ({
      x: rand(-60, innerWidth + 60),
      y: rand(-60, innerHeight + 60),
      s: rand(minSize, maxSize),
      vx: rand(-0.25, 0.25),
      vy: rand(-0.18, 0.18),
      a: rand(0.45, 0.9),
      rot: rand(0, Math.PI * 2),
      spin: rand(-0.012, 0.012),
    }));
  }

  // vykreslení jednoho míčku
  function drawBall(b) {
    const w = b.s, h = b.s;
    ctx.save();
    ctx.globalAlpha = b.a;
    ctx.translate(b.x, b.y);
    ctx.rotate(b.rot);

    ctx.shadowColor = 'rgba(0,0,0,.18)';
    ctx.shadowBlur = 14;
    ctx.shadowOffsetY = 3;

    ctx.drawImage(ballImg, -w / 2, -h / 2, w, h);
    ctx.restore();
  }

  // Hlavní smyčka animace
  function step() {
    // 1. Vždy vyčistí plochu (už v nové velikosti)
    ctx.clearRect(0, 0, innerWidth, innerHeight);
    
    for (const b of balls) {
      // 2. Posune míčky
      b.x += b.vx; b.y += b.vy; b.rot += b.spin;

      // 3. Plynule je "přebalí" na druhou stranu, pokud vyletí z nové velikosti okna
      if (b.x < -70) b.x = innerWidth + 70;
      if (b.x > innerWidth + 70) b.x = -70;
      if (b.y < -70) b.y = innerHeight + 70;
      if (b.y > innerHeight + 70) b.y = -70;

      // 4. Vykreslí míček na jeho nové pozici
      drawBall(b);
    }
    requestAnimationFrame(step);
  }

  // PNG míček
  const src = c.dataset.ballSrc || '/static/home/tennisball.png';
  const ballImg = new Image();
  ballImg.src = src;

  function start() {
    resize();
    makeBalls(); // Vygenerujeme míčky jen JEDNOU ZDE
    step();      // A spustíme animaci
  }

  if (ballImg.complete) start();
  else ballImg.onload = start;

  // ✅ PATCH: Změna chování při změně velikosti okna
  addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    
    // Počkáme 100ms po POSLEDNÍ změně velikosti
    resizeTimer = setTimeout(() => {
      // A pak POUZE změníme velikost canvasu
      resize();
      
      // !!! UŽ NEVOLÁME makeBalls() !!!
      // Animace ve smyčce step() plynule pokračuje dál.
    }, 100); // 100ms je dostatečně rychlá reakce
  }, { passive: true });

  // první nastavení
  resize();
})();