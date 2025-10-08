// static/home/landing.js
(() => {
    const c = document.getElementById('bg');
    if (!c) return;
    const ctx = c.getContext('2d');
  
    let DPR = Math.max(1, window.devicePixelRatio || 1);
    let balls = [];
  
    function resize() {
      DPR = Math.max(1, window.devicePixelRatio || 1);
      c.width  = innerWidth * DPR;
      c.height = innerHeight * DPR;
      // nastav transform, ať se nepřeskaluje násobně
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    }
  
    function rand(a, b) { return a + Math.random() * (b - a); }
  
    function makeBalls(n = 22) {
      balls = Array.from({ length: n }, () => ({
        x: rand(-60, innerWidth + 60),
        y: rand(-60, innerHeight + 60),
        s: rand(26, 64),               // velikost v px
        vx: rand(-0.25, 0.25),         // rychlosti
        vy: rand(-0.18, 0.18),
        a: rand(0.45, 0.9),            // průhlednost (jemné)
        rot: rand(0, Math.PI * 2),     // počáteční natočení
        spin: rand(-0.012, 0.012),     // pomalá rotace
      }));
    }
  
    // vykreslení jednoho míčku
    function drawBall(b) {
      const w = b.s, h = b.s;
      ctx.save();
      ctx.globalAlpha = b.a;
      ctx.translate(b.x, b.y);
      ctx.rotate(b.rot);
  
      // měkký stín pod míčkem
      ctx.shadowColor = 'rgba(0,0,0,.18)';
      ctx.shadowBlur = 14;
      ctx.shadowOffsetY = 3;
  
      ctx.drawImage(ballImg, -w / 2, -h / 2, w, h);
      ctx.restore();
    }
  
    function step() {
      ctx.clearRect(0, 0, innerWidth, innerHeight);
      for (const b of balls) {
        b.x += b.vx; b.y += b.vy; b.rot += b.spin;
  
        // plynulý wrap kolem okrajů
        if (b.x < -70) b.x = innerWidth + 70;
        if (b.x > innerWidth + 70) b.x = -70;
        if (b.y < -70) b.y = innerHeight + 70;
        if (b.y > innerHeight + 70) b.y = -70;
  
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
      makeBalls(22);
      step();
    }
  
    if (ballImg.complete) start();
    else ballImg.onload = start;
  
    addEventListener('resize', () => {
      resize();
      makeBalls(balls.length);
    }, { passive: true });
  
    // první nastavení
    resize();
  })();
  