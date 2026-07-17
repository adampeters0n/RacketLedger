document.addEventListener('DOMContentLoaded', function () {
  var TSTheme = window.TSTheme;
  var i18nEl = document.getElementById('ts-i18n');
  var localeEl = document.getElementById('ts-js-locale');
  var TS_I18N = i18nEl ? JSON.parse(i18nEl.textContent) : {};
  function t(key, fallback) {
    return TS_I18N[key] || fallback || key;
  }

  var form = document.querySelector('.nastaveni-form');
  if (!form) return;

  var config = TSTheme ? TSTheme.readJsonScript('nastaveni-config') || {} : {};
  var presets = TSTheme ? TSTheme.readJsonScript('theme-presets-data') : null;
  var statusEl = document.querySelector('.js-nastaveni-status');
  var tabs = document.querySelectorAll('.nast-sidebar-item');
  var panels = document.querySelectorAll('.nast-panel');

  var autosaveTimer = null;
  var appearanceTimer = null;
  var statusTimer = null;
  var autosaveInFlight = null;

  tabs.forEach(function (tab) {
    tab.addEventListener('click', function () {
      var id = tab.dataset.panel;
      tabs.forEach(function (t) {
        t.classList.toggle('is-active', t === tab);
        t.setAttribute('aria-selected', t === tab ? 'true' : 'false');
      });
      panels.forEach(function (panel) {
        var show = panel.id === 'panel-' + id;
        panel.classList.toggle('is-active', show);
        panel.hidden = !show;
      });
    });
  });

  form.addEventListener('submit', function (event) {
    event.preventDefault();
  });

  function showStatus(text, isError) {
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.classList.add('is-visible');
    statusEl.classList.toggle('is-error', !!isError);
    statusEl.setAttribute('aria-hidden', 'false');
    if (statusTimer) clearTimeout(statusTimer);
    statusTimer = setTimeout(function () {
      statusEl.classList.remove('is-visible');
      statusEl.setAttribute('aria-hidden', 'true');
    }, isError ? 5000 : 2200);
  }

  function firstErrorMessage(errors) {
    if (!errors) return t('saveFailed', 'Uložení se nezdařilo.');
    var keys = Object.keys(errors);
    if (!keys.length) return t('saveFailed', 'Uložení se nezdařilo.');
    var msgs = errors[keys[0]];
    return (msgs && msgs[0]) || t('saveFailed', 'Uložení se nezdařilo.');
  }

  function updateBranding(data) {
    if (data.nazev_klubu) {
      document.querySelectorAll('.brand-title, .ts-drawer-title span').forEach(function (el) {
        el.textContent = data.nazev_klubu;
      });
    }
    if (data.logo_url) {
      document.querySelectorAll('.brand-logo, .ts-drawer-title img').forEach(function (img) {
        img.src = data.logo_url;
      });
    }
  }

  function buildAutosaveBody() {
    var csrf = TSTheme ? TSTheme.getCsrfToken() : '';
    var body = new FormData(form);
    form.querySelectorAll('input[type="checkbox"]').forEach(function (cb) {
      if (!cb.name) return;
      body.delete(cb.name);
      if (cb.checked) {
        body.append(cb.name, cb.value || 'on');
      }
    });
    var checkedPalette = form.querySelector('input[name="barevna_varianta"]:checked');
    var paletteValue = checkedPalette
      ? checkedPalette.value
      : (config.barevnaVarianta || document.documentElement.dataset.palette || 'oranzova');
    body.delete('barevna_varianta');
    body.append('barevna_varianta', paletteValue);
    if (csrf) {
      body.set('csrfmiddlewaretoken', csrf);
    }
    return body;
  }

  function saveSettings() {
    if (!config.saveUrl) return Promise.resolve();

    var csrf = TSTheme ? TSTheme.getCsrfToken() : '';
    if (!csrf) {
      showStatus(t('missingCsrf', 'Chybí CSRF token – obnovte stránku'), true);
      return Promise.resolve();
    }

    var body = buildAutosaveBody();
    autosaveInFlight = fetch(config.saveUrl, {
      method: 'POST',
      headers: { 'X-CSRFToken': csrf },
      body: body,
      credentials: 'same-origin',
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          if (!resp.ok || !data.ok) {
            throw new Error(firstErrorMessage(data.errors) || data.error || t('saveFailed', 'Uložení se nezdařilo.'));
          }
          return data;
        });
      })
      .then(function (data) {
        autosaveInFlight = null;
        updateBranding(data);
        var pageLangEl = document.getElementById('page-lang');
        var pageLang = pageLangEl ? JSON.parse(pageLangEl.textContent) : (document.documentElement.lang || 'cs');
        if (data.vychozi_jazyk && data.vychozi_jazyk !== pageLang) {
          window.location.reload();
          return;
        }
        showStatus(t('settingsSaved', 'Nastavení uloženo'));
      })
      .catch(function (err) {
        autosaveInFlight = null;
        showStatus(err.message || t('saveFailed', 'Uložení se nezdařilo.'), true);
      });

    return autosaveInFlight;
  }

  function scheduleAutosave(delay) {
    if (autosaveTimer) clearTimeout(autosaveTimer);
    autosaveTimer = setTimeout(function () {
      autosaveTimer = null;
      saveSettings();
    }, delay || 500);
  }

  function isAppearanceField(el) {
    if (!el || !el.name) return false;
    if (el.name === 'tmavy_rezim') return true;
    return el.classList && el.classList.contains('js-theme-preset');
  }

  function isAutosaveField(el) {
    if (!el || !el.name || el.disabled) return false;
    if (el.form !== form) return false;
    if (isAppearanceField(el)) return false;
    if (el.type === 'file' && el.closest('.nast-upload-field')) return true;
    if (el.type === 'hidden') return false;
    return el.matches('input, select, textarea');
  }

  form.addEventListener('input', function (event) {
    var t = event.target;
    if (!isAutosaveField(t)) return;
    if (t.type === 'file') return;
    scheduleAutosave(t.tagName === 'TEXTAREA' ? 700 : 500);
  });

  form.addEventListener('change', function (event) {
    var t = event.target;
    if (!isAutosaveField(t)) return;
    if (t.type === 'file') {
      scheduleAutosave(100);
      return;
    }
    if (t.name === 'vychozi_jazyk') {
      saveSettings();
      return;
    }
    scheduleAutosave(200);
  });

  document.querySelectorAll('.nast-switch').forEach(function (el) {
    el.addEventListener('mousedown', function (event) {
      event.preventDefault();
    });
  });

  /* ── Vzhled (paleta + tmavý režim) ── */
  if (presets && TSTheme && config.vzhledUrl) {
    function isDark() {
      var cb = form.querySelector('.nast-switch-input[name="tmavy_rezim"]');
      return !!(cb && cb.checked);
    }

    function selectedPreset() {
      var checked = form.querySelector('input[name="barevna_varianta"]:checked');
      return checked ? checked.value : 'oranzova';
    }

    function syncPresetRowState() {
      form.querySelectorAll('.nast-excel-row').forEach(function (row) {
        row.classList.toggle('is-active', row.querySelector('input:checked') !== null);
      });
    }

    function applyThemeFromPreset() {
      var key = selectedPreset();
      var palette = presets[key] || presets.oranzova;
      var mode = isDark() ? 'dark' : 'light';
      var colors = palette[mode] || palette.light;
      TSTheme.applyColors(colors, mode, key);
      syncPresetRowState();
    }

    function applyThemeFromServer(data) {
      if (data.theme_style) {
        var styleEl = document.getElementById('system-theme-vars');
        if (styleEl) styleEl.textContent = data.theme_style;
      }
      var key = data.palette || data.theme || selectedPreset();
      var mode = data.mode || (isDark() ? 'dark' : 'light');
      if (data.colors) {
        TSTheme.applyColors(data.colors, mode, key);
      } else {
        var palette = presets[key] || presets.oranzova;
        TSTheme.applyColors(palette[mode] || palette.light, mode, key);
      }
      syncPresetRowState();
    }

    function saveAppearance() {
      var csrf = TSTheme.getCsrfToken();
      if (!csrf) return Promise.resolve();

      var body = new FormData();
      body.append('barevna_varianta', selectedPreset());
      body.append('tmavy_rezim', isDark() ? 'true' : 'false');
      body.append('csrfmiddlewaretoken', csrf);

      return fetch(config.vzhledUrl, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrf },
        body: body,
        credentials: 'same-origin',
      })
        .then(function (resp) {
          return resp.json().then(function (data) {
            if (!resp.ok || !data.ok) {
              throw new Error((data && data.error) || t('appearanceSaveFailed', 'Uložení vzhledu se nezdařilo.'));
            }
            return data;
          });
        })
        .then(function (data) {
          applyThemeFromServer(data);
          showStatus(t('appearanceSaved', 'Vzhled uložen'));
        })
        .catch(function (err) {
          showStatus(err.message || t('appearanceSaveFailed', 'Uložení vzhledu se nezdařilo.'), true);
        });
    }

    function scheduleAppearanceSave() {
      if (appearanceTimer) clearTimeout(appearanceTimer);
      appearanceTimer = setTimeout(function () {
        appearanceTimer = null;
        saveAppearance();
      }, 200);
    }

    function onAppearanceChange() {
      applyThemeFromPreset();
      scheduleAppearanceSave();
    }

    document.addEventListener('change', function (event) {
      var t = event.target;
      if (!t) return;
      if (t.classList && t.classList.contains('js-theme-preset')) {
        onAppearanceChange();
      } else if (t.name === 'tmavy_rezim') {
        if (typeof t.blur === 'function') t.blur();
        onAppearanceChange();
      }
    });

    document.addEventListener('click', function (event) {
      var row = event.target.closest('.nast-excel-row');
      if (!row) return;
      var radio = row.querySelector('.js-theme-preset');
      if (!radio || radio.checked) return;
      radio.checked = true;
      onAppearanceChange();
    });

    syncPresetRowState();
  }

  var oznaceniInput = form.querySelector('input[name="email_oznaceni"]');
  var subjectPreview = document.querySelector('.js-email-subject-preview');
  if (oznaceniInput && subjectPreview) {
    oznaceniInput.addEventListener('input', function () {
      var tag = (oznaceniInput.value || '').trim();
      var prefix = tag ? '[' + tag + '] ' : '';
      subjectPreview.textContent = prefix + t('emailSubjectPreview', 'Přehled tréninků – Jméno hráče');
    });
  }

  function initTranslatedFileInputs() {
    document.querySelectorAll('.nast-upload-field input[type="file"], input.nast-file-input[type="file"]').forEach(function (input) {
      if (input.dataset.i18nReady) return;
      input.dataset.i18nReady = '1';
      var wrap = document.createElement('div');
      wrap.className = 'nast-translated-file';
      input.parentNode.insertBefore(wrap, input);
      wrap.appendChild(input);

      var ui = document.createElement('div');
      ui.className = 'nast-file-ui';
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'nast-file-choose-btn';
      btn.textContent = t('chooseFile', 'Vybrat soubor');
      var status = document.createElement('span');
      status.className = 'nast-file-status';
      status.textContent = input.files && input.files[0]
        ? input.files[0].name
        : t('noFileChosen', 'Soubor nevybrán');
      ui.appendChild(btn);
      ui.appendChild(status);
      wrap.insertBefore(ui, input);

      input.classList.add('nast-file-native-hidden');
      btn.addEventListener('click', function () { input.click(); });
      input.addEventListener('change', function () {
        status.textContent = input.files && input.files[0]
          ? input.files[0].name
          : t('noFileChosen', 'Soubor nevybrán');
      });
    });
  }

  initTranslatedFileInputs();

  document.querySelectorAll('.nast-upload-field input[type="file"]').forEach(function (input) {
    input.addEventListener('change', function () {
      var box = input.closest('.nast-upload-box');
      if (!box || !input.files || !input.files[0]) return;
      var preview = box.querySelector('.nast-upload-preview');
      var img = box.querySelector('.js-upload-preview-img');
      if (!preview || !img) return;
      img.src = URL.createObjectURL(input.files[0]);
      img.hidden = false;
      preview.hidden = false;
    });
  });
});
