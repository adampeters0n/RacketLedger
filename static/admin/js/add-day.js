(function() {
  document.documentElement.classList.add('add-day-ready');

  function readI18n() {
    try {
      var el = document.getElementById('ts-global-i18n');
      return el ? JSON.parse(el.textContent) : {};
    } catch (e) {
      return {};
    }
  }
  var I18N = readI18n();

  var today = new Date();
  var todayStr = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');
  var dnesLink = document.getElementById('add-day-dnes');
  var datumInput = document.getElementById('id_day-datum');
  if (dnesLink && datumInput) {
    dnesLink.addEventListener('click', function(e) {
      e.preventDefault();
      datumInput.value = todayStr;
    });
  }
  var minulyTydenLink = document.getElementById('add-day-minuly-tyden');
  if (minulyTydenLink && datumInput) {
    minulyTydenLink.addEventListener('click', function(e) {
      e.preventDefault();
      var parts = (datumInput.value || todayStr).split('-');
      var d = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
      d.setDate(d.getDate() - 7);
      datumInput.value = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    });
  }
  function openDatePicker() {
    if (!datumInput) return;
    datumInput.focus();
    if (typeof datumInput.showPicker === 'function') datumInput.showPicker();
  }
  var calendarBtn = document.getElementById('add-day-calendar');
  if (calendarBtn) calendarBtn.addEventListener('click', function(e) { e.preventDefault(); openDatePicker(); });

  function bindCopyDatePicker(input) {
    if (!input || input.type !== 'date') return;
    function openPicker() {
      input.focus();
      if (typeof input.showPicker === 'function') {
        try { input.showPicker(); } catch (err) { /* prohlížeč může odmítnout mimo uživatelský gesture */ }
      }
    }
    input.addEventListener('click', openPicker);
    input.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openPicker();
      }
    });
  }
  document.querySelectorAll('.add-day-copy-card input[type="date"]').forEach(bindCopyDatePicker);

  function getPlayersForSlot(slotIndex) {
    var script = document.querySelector('.add-day-players-json[data-slot="' + slotIndex + '"]');
    if (!script || !script.textContent) return [];
    try { return JSON.parse(script.textContent); } catch (err) { return []; }
  }
  function getSelectedIds(container, excludeRow) {
    var ids = [];
    container.querySelectorAll('.add-day-hraci-row[data-id]').forEach(function(r) {
      if (r !== excludeRow) ids.push(r.getAttribute('data-id'));
    });
    return ids;
  }
  function syncHraciRowsToMultiselect(container) {
    var multiselectId = container.getAttribute('data-multiselect-id');
    var multiselect = document.getElementById(multiselectId);
    if (!multiselect) return;
    var selected = [];
    container.querySelectorAll('.add-day-hraci-row[data-id]').forEach(function(row) {
      selected.push({ id: row.getAttribute('data-id'), jmeno: row.getAttribute('data-jmeno') || '' });
    });
    multiselect.innerHTML = '';
    selected.forEach(function(p) {
      var opt = document.createElement('option');
      opt.value = p.id;
      opt.textContent = p.jmeno;
      opt.selected = true;
      multiselect.appendChild(opt);
    });
  }
  function wirePlayerRow(row, card) {
    var container = row.closest('.add-day-hraci-rows');
    var slot = container && container.getAttribute('data-slot');
    var multiselectId = container && container.getAttribute('data-multiselect-id');
    var multiselect = multiselectId ? document.getElementById(multiselectId) : null;
    var players = slot !== null ? getPlayersForSlot(slot) : [];
    var searchInput = row.querySelector('.add-day-hraci-search');
    var dropdown = row.querySelector('.add-day-hraci-dropdown');
    if (!searchInput || !dropdown || !container || !multiselect) return;

    function showDropdown(filter) {
      var q = (filter || '').trim().toLowerCase();
      var used = getSelectedIds(container, row);
      var list = (q ? players.filter(function(p) { return (p.jmeno || '').toLowerCase().indexOf(q) !== -1; }) : players)
        .filter(function(p) { return used.indexOf(String(p.id)) === -1; });
      dropdown.innerHTML = '';
      list.slice(0, 50).forEach(function(p) {
        var li = document.createElement('li');
        li.setAttribute('data-id', p.id);
        li.setAttribute('data-jmeno', p.jmeno || '');
        li.setAttribute('role', 'option');
        li.textContent = p.jmeno || '';
        dropdown.appendChild(li);
      });
      dropdown.classList.toggle('is-open', list.length > 0);
    }
    function hideDropdown() { dropdown.classList.remove('is-open'); }
    function setRowPlayer(id, jmeno) {
      row.setAttribute('data-id', id);
      searchInput.value = jmeno || '';
      syncHraciRowsToMultiselect(container);
    }

    searchInput.value = row.getAttribute('data-id') ? (row.getAttribute('data-jmeno') || '') : '';
    searchInput.addEventListener('focus', function() { showDropdown(searchInput.value); });
    searchInput.addEventListener('input', function() { showDropdown(searchInput.value); });
    searchInput.addEventListener('blur', function() { setTimeout(hideDropdown, 180); });
    searchInput.addEventListener('keydown', function(e) {
      if (e.key === 'Escape') { hideDropdown(); searchInput.blur(); return; }
      var items = dropdown.querySelectorAll('li');
      if (e.key === 'Enter' && items.length) {
        e.preventDefault();
        var first = items[0];
        setRowPlayer(first.getAttribute('data-id'), first.getAttribute('data-jmeno'));
        hideDropdown();
      }
    });
    dropdown.addEventListener('click', function(e) {
      var li = e.target.closest('li[data-id]');
      if (!li) return;
      setRowPlayer(li.getAttribute('data-id'), li.getAttribute('data-jmeno'));
      hideDropdown();
    });
    var btnRemove = row.querySelector('.btn-remove');
    if (btnRemove) {
      btnRemove.onclick = function(ev) {
        ev.preventDefault();
        row.remove();
        syncHraciRowsToMultiselect(container);
        if (container.children.length === 0) {
          var empty = createEmptyPlayerRow(card);
          if (empty) { container.appendChild(empty); wirePlayerRow(empty, card); }
        }
      };
    }
  }
  function createEmptyPlayerRow(card) {
    var container = card.querySelector('.add-day-hraci-rows');
    var first = container && container.querySelector('.add-day-hraci-row');
    if (!first) return null;
    var clone = first.cloneNode(true);
    clone.removeAttribute('data-id');
    clone.removeAttribute('data-jmeno');
    var inp = clone.querySelector('.add-day-hraci-search');
    var ul = clone.querySelector('.add-day-hraci-dropdown');
    if (inp) inp.value = '';
    if (ul) ul.innerHTML = '';
    return clone;
  }

  function hydrateInitialHraciForSlot(slotIndex, players) {
    var card = document.querySelector('.slot-card[data-slot-index="' + slotIndex + '"]');
    if (!card) return;
    var container = card.querySelector('.add-day-hraci-rows');
    if (!container) return;

    var templateRow = container.querySelector('.add-day-hraci-row');
    if (!templateRow) return;
    var rowTemplate = templateRow.cloneNode(true);
    rowTemplate.removeAttribute('data-id');
    rowTemplate.removeAttribute('data-jmeno');
    var tplInp = rowTemplate.querySelector('.add-day-hraci-search');
    var tplUl = rowTemplate.querySelector('.add-day-hraci-dropdown');
    if (tplInp) tplInp.value = '';
    if (tplUl) tplUl.innerHTML = '';

    container.innerHTML = '';

    if (!players || !players.length) {
      container.appendChild(rowTemplate);
      wirePlayerRow(rowTemplate, card);
      syncHraciRowsToMultiselect(container);
      return;
    }

    players.forEach(function(p) {
      var row = rowTemplate.cloneNode(true);
      row.setAttribute('data-id', String(p.id));
      row.setAttribute('data-jmeno', p.jmeno || '');
      container.appendChild(row);
      wirePlayerRow(row, card);
      var inp = row.querySelector('.add-day-hraci-search');
      if (inp) inp.value = p.jmeno || '';
    });
    syncHraciRowsToMultiselect(container);
  }

  document.querySelectorAll('.slot-card').forEach(function(card) {
    var slotIndex = card.getAttribute('data-slot-index');
    var container = card.querySelector('.add-day-hraci-rows');
    if (!container) return;

    var preloadedRows = container.querySelectorAll('.add-day-hraci-row[data-id]');
    if (preloadedRows.length) {
      preloadedRows.forEach(function(row) {
        wirePlayerRow(row, card);
      });
      syncHraciRowsToMultiselect(container);
      return;
    }

    var script = card.querySelector('.add-day-initial-hraci[data-slot="' + slotIndex + '"]');
    if (script) {
      try {
        var players = JSON.parse(script.textContent || '[]');
        hydrateInitialHraciForSlot(slotIndex, players);
      } catch (err) { /* ignore */ }
      return;
    }

    container.querySelectorAll('.add-day-hraci-row').forEach(function(row) {
      wirePlayerRow(row, card);
    });
  });

  document.getElementById('add-day-form').addEventListener('click', function(e) {
    var closeBtn = e.target.closest('.add-day-slot-close');
    if (!closeBtn) return;
    e.preventDefault();
    var card = closeBtn.closest('.slot-card');
    if (!card) return;
    card.querySelectorAll('input, select, textarea').forEach(function(el) {
      var type = (el.type || '').toLowerCase();
      if (type === 'checkbox' || type === 'radio') { el.checked = false; }
      else if (el.tagName === 'SELECT') { el.selectedIndex = 0; }
      else if (el.name && el.name.indexOf('TOTAL_FORMS') === -1 && el.name.indexOf('INITIAL_FORMS') === -1) { el.value = ''; }
    });
    var hraciContainer = card.querySelector('.add-day-hraci-rows');
    if (hraciContainer) {
      var emptyRow = createEmptyPlayerRow(card);
      hraciContainer.innerHTML = '';
      if (emptyRow) { hraciContainer.appendChild(emptyRow); wirePlayerRow(emptyRow, card); }
      syncHraciRowsToMultiselect(hraciContainer);
    }
    card.style.display = 'none';
  });

  document.getElementById('add-day-form').addEventListener('click', function(e) {
    var btn = e.target.closest('.add-day-btn-pridat-hrace');
    if (!btn) return;
    e.preventDefault();
    var card = btn.closest('.slot-card');
    var container = card && card.querySelector('.add-day-hraci-rows');
    if (!container) return;
    var newRow = createEmptyPlayerRow(card);
    if (newRow) {
      container.appendChild(newRow);
      wirePlayerRow(newRow, card);
      var inp = newRow.querySelector('.add-day-hraci-search');
      if (inp) inp.focus();
    }
  });

  function normalizeTimeValue(raw) {
    if (!raw) return '';
    var v = String(raw).trim();
    if (!v) return '';
    // nahradit čárku/tečku dvojtečkou
    v = v.replace(/[.,]/g, ':');
    // čisté HH → HH:00
    if (/^\d{1,2}$/.test(v)) {
      var h = parseInt(v, 10);
      if (isNaN(h) || h < 0 || h > 23) return raw;
      return String(h).padStart(2, '0') + ':00';
    }
    // HH:MM nebo HH:MM:SS
    var m = /^(\d{1,2}):(\d{1,2})(?::\d{1,2})?$/.exec(v);
    if (m) {
      var hh = parseInt(m[1], 10);
      var mm = parseInt(m[2], 10);
      if (isNaN(hh) || isNaN(mm) || hh < 0 || hh > 23 || mm < 0 || mm > 59) return raw;
      return String(hh).padStart(2, '0') + ':' + String(mm).padStart(2, '0');
    }
    return raw;
  }

  function wireTimeInputs() {
    var inputs = document.querySelectorAll('input.add-day-time-input');
    inputs.forEach(function(inp) {
      if (inp.dataset.xTimeWired === '1') return;
      inp.dataset.xTimeWired = '1';
      inp.addEventListener('blur', function() {
        inp.value = normalizeTimeValue(inp.value);
      });
    });
  }

  wireTimeInputs();

  document.querySelectorAll('.add-day-fields input[name$="-cas"]').forEach(function(inp) {
    if (inp.value) inp.value = normalizeTimeValue(inp.value);
  });

  document.getElementById('add-day-form').addEventListener('submit', function(ev) {
    // nejdřív znormalizujeme všechny časové inputy
    document.querySelectorAll('input.add-day-time-input').forEach(function(inp) {
      inp.value = normalizeTimeValue(inp.value);
    });
    /* Kontrola: v každém viditelném tréninku (slot) nesmí být stejný hráč dvakrát */
    var slotCards = document.querySelectorAll('.slot-card');
    for (var s = 0; s < slotCards.length; s++) {
      var card = slotCards[s];
      if (card.style.display === 'none') continue;
      var container = card && card.querySelector('.add-day-hraci-rows');
      if (!container) continue;
      var ids = [];
      container.querySelectorAll('.add-day-hraci-row[data-id]').forEach(function(row) {
        ids.push(row.getAttribute('data-id'));
      });
      var seen = {};
      for (var i = 0; i < ids.length; i++) {
        if (seen[ids[i]]) {
          ev.preventDefault();
          var titleEl = card.querySelector('.add-day-slot-title-text');
          var slotName = titleEl ? titleEl.textContent : (I18N.training || 'Trénink');
          var tpl = I18N.duplicatePlayerInSlot || 'V %(slot)s je stejný hráč vybrán více než jednou. Každého hráče vyberte pouze jednou.';
          alert(tpl.replace('%(slot)s', slotName));
          return;
        }
        seen[ids[i]] = true;
      }
    }
    document.querySelectorAll('.add-day-hraci-rows').forEach(syncHraciRowsToMultiselect);
  });

  var slotCards = document.querySelectorAll('.slot-card');
  var btnAdd = document.getElementById('btn-add-slot');
  if (btnAdd) {
    btnAdd.addEventListener('click', function() {
      for (var i = 0; i < slotCards.length; i++) {
        if (slotCards[i].style.display === 'none') {
          slotCards[i].style.display = 'block';
          var titleText = slotCards[i].querySelector('.add-day-slot-title-text');
          if (titleText) titleText.textContent = (I18N.training || 'Trénink') + ' ' + (i + 1);
          slotCards[i].scrollIntoView({ behavior: 'smooth', block: 'start' });
          // po odhalení nového slotu zadrátujeme i časové pole uvnitř
          wireTimeInputs();
          return;
        }
      }
    });
  }
})();
