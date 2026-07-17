(function () {
  'use strict';

  function readJsonScript(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    var raw = el.textContent || '';
    try {
      return JSON.parse(raw);
    } catch (err) {
      try {
        var ta = document.createElement('textarea');
        ta.innerHTML = raw;
        return JSON.parse(ta.value);
      } catch (err2) {
        console.error('TSTheme: nelze načíst JSON ze #' + id, err2);
        return null;
      }
    }
  }

  function cssVarsFromColors(colors) {
    return {
      '--brand': colors.brand,
      '--brand-600': colors.brand_600,
      '--brand-100': colors.brand_100,
      '--bg': colors.bg,
      '--surface': colors.surface,
      '--text': colors.text,
      '--text-strong': colors.text_strong,
      '--line': colors.line,
      '--amber-100': colors.brand_100,
      '--amber-200': colors.table_head,
      '--table-head': colors.table_head,
      '--table-row-alt': colors.table_row_alt,
      '--table-row-hover': colors.table_row_hover,
      '--muted': colors.muted || '#64748B',
    };
  }

  function ensureThemeStyleEl() {
    var el = document.getElementById('system-theme-vars');
    if (!el) {
      el = document.createElement('style');
      el.id = 'system-theme-vars';
      document.head.appendChild(el);
    }
    return el;
  }

  function setRootAttributes(mode, palette) {
    var root = document.documentElement;
    if (mode) {
      root.dataset.mode = mode;
    }
    if (palette) {
      root.dataset.palette = palette;
    }
  }

  function applyColors(colors, mode, palette) {
    if (!colors) return;
    var root = document.documentElement;
    var vars = cssVarsFromColors(colors);
    Object.keys(vars).forEach(function (k) {
      root.style.setProperty(k, vars[k]);
    });
    var lines = Object.keys(vars).map(function (k) {
      return '  ' + k + ': ' + vars[k] + ';';
    }).join('\n');
    ensureThemeStyleEl().textContent = 'html {\n' + lines + '\n  color-scheme: ' + mode + ';\n}';
    setRootAttributes(mode, palette);
  }

  function applyFromStyleBlock() {
    var el = document.getElementById('system-theme-vars');
    if (!el) return;
    var root = document.documentElement;
    var text = el.textContent || '';
    var re = /(--[\w-]+)\s*:\s*([^;]+);/g;
    var match;
    while ((match = re.exec(text)) !== null) {
      root.style.setProperty(match[1], match[2].trim());
    }
    var schemeMatch = text.match(/color-scheme:\s*(dark|light)/);
    if (schemeMatch) {
      setRootAttributes(schemeMatch[1], root.dataset.palette);
    }
  }

  function initPageTheme() {
    var state = readJsonScript('system-theme-state');
    if (state && state.colors) {
      applyColors(state.colors, state.mode || 'light', state.palette || 'oranzova');
      return;
    }
    applyFromStyleBlock();
  }

  function getCsrfToken() {
    var inp = document.querySelector('[name=csrfmiddlewaretoken]');
    if (inp && inp.value) return inp.value;
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  window.TSTheme = {
    readJsonScript: readJsonScript,
    applyColors: applyColors,
    applyFromStyleBlock: applyFromStyleBlock,
    initPageTheme: initPageTheme,
    getCsrfToken: getCsrfToken,
    cssVarsFromColors: cssVarsFromColors,
  };

  initPageTheme();
})();
