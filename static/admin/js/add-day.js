(function() {
  document.documentElement.classList.add('add-day-ready');

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
          var slotName = titleEl ? titleEl.textContent : 'Trénink';
          alert('V ' + slotName + ' je stejný hráč vybrán více než jednou. Každého hráče vyberte pouze jednou.');
          return;
        }
        seen[ids[i]] = true;
      }
    }
    document.querySelectorAll('.add-day-hraci-rows').forEach(syncHraciRowsToMultiselect);
  });

  function formatIsSluzba(format) {
    return String(format || '').indexOf('V_') === 0;
  }

  function kurtHasOption(sel, value) {
    if (!sel) return false;
    return Array.prototype.some.call(sel.options || [], function(o) {
      return o.value === value;
    });
  }

  function restoreSportKurt(kurtSel) {
    if (!kurtSel) return;
    var prev = kurtSel.getAttribute('data-prev-kurt') || '';
    var next = prev && prev !== 'SLUZBA' ? prev : 'HALA';
    if (next === 'SLUZBA') next = 'HALA';
    if (!kurtHasOption(kurtSel, next)) {
      if (kurtHasOption(kurtSel, 'HALA')) next = 'HALA';
      else if (kurtHasOption(kurtSel, 'VENEK')) next = 'VENEK';
      else return;
    }
    kurtSel.value = next;
  }

  function setDelkaSelect(delkaSel, minutes) {
    if (!delkaSel) return;
    var value = String(minutes || 60);
    delkaSel.value = value;
    if (!delkaSel.value) {
      for (var i = 0; i < delkaSel.options.length; i++) {
        if (delkaSel.options[i].value === value) {
          delkaSel.selectedIndex = i;
          break;
        }
      }
    }
  }

  function syncSlotSluzbaUi(card) {
    if (!card) return;
    // add form: slots-0-format; change form: format / delka_minut / kurt
    var formatSel = card.querySelector('select[name$="-format"], select[name="format"]');
    var kurtSel = card.querySelector('select[name$="-kurt"], select[name="kurt"]');
    var delkaRow = card.querySelector('.add-day-row--delka');
    var delkaSel = card.querySelector('select[name$="delka_minut"]');
    var format = formatSel ? formatSel.value : '';
    var kurt = kurtSel ? kurtSel.value : '';
    var fmtService = formatIsSluzba(format);

    if (fmtService) {
      if (kurtSel && kurt && kurt !== 'SLUZBA') {
        kurtSel.setAttribute('data-prev-kurt', kurt);
      }
      if (kurtSel && kurtHasOption(kurtSel, 'SLUZBA') && kurtSel.value !== 'SLUZBA') {
        kurtSel.value = 'SLUZBA';
      }
      if (delkaRow) {
        delkaRow.hidden = true;
        delkaRow.classList.add('is-sluzba-hidden');
      }
      setDelkaSelect(delkaSel, 60);
      return;
    }

    // Návrat ze služby na běžný typ → kurt zpět + délka viditelná
    if (kurtSel && kurtSel.value === 'SLUZBA') {
      restoreSportKurt(kurtSel);
      kurt = kurtSel.value;
    }

    var service = kurt === 'SLUZBA';
    if (delkaRow) {
      delkaRow.hidden = service;
      delkaRow.classList.toggle('is-sluzba-hidden', service);
    }
    if (service) setDelkaSelect(delkaSel, 60);
  }

  function wireSluzbaUi(card) {
    if (!card || card.getAttribute('data-sluzba-wired') === '1') return;
    card.setAttribute('data-sluzba-wired', '1');
    var formatSel = card.querySelector('select[name$="-format"], select[name="format"]');
    var kurtSel = card.querySelector('select[name$="-kurt"], select[name="kurt"]');
    function onChange() { syncSlotSluzbaUi(card); }
    if (formatSel) formatSel.addEventListener('change', onChange);
    if (kurtSel) kurtSel.addEventListener('change', onChange);
    syncSlotSluzbaUi(card);
  }

  var slotCards = document.querySelectorAll('.slot-card');
  slotCards.forEach(wireSluzbaUi);

  var btnAdd = document.getElementById('btn-add-slot');
  if (btnAdd) {
    btnAdd.addEventListener('click', function() {
      for (var i = 0; i < slotCards.length; i++) {
        if (slotCards[i].style.display === 'none') {
          slotCards[i].style.display = 'block';
          var titleText = slotCards[i].querySelector('.add-day-slot-title-text');
          if (titleText) titleText.textContent = 'Trénink ' + (i + 1);
          slotCards[i].scrollIntoView({ behavior: 'smooth', block: 'start' });
          // po odhalení nového slotu zadrátujeme i časové pole uvnitř
          wireTimeInputs();
          wireSluzbaUi(slotCards[i]);
          return;
        }
      }
    });
  }
})();
