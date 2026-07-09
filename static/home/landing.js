// static/home/landing.js
(() => {
  const input = document.getElementById('school-search');
  const grid = document.getElementById('school-grid');
  const empty = document.getElementById('school-empty');
  if (!input || !grid) return;

  const items = Array.from(grid.querySelectorAll('.school-item'));

  input.addEventListener('input', () => {
    const q = input.value.trim().toLowerCase();
    let n = 0;
    items.forEach((el) => {
      const ok = !q || (el.dataset.search || '').includes(q);
      el.classList.toggle('is-hidden', !ok);
      if (ok) n += 1;
    });
    if (empty) empty.hidden = n > 0;
  });
})();
