(function () {
  function readGlobalI18n() {
    var el = document.getElementById('ts-global-i18n');
    if (!el) return {};
    try {
      return JSON.parse(el.textContent);
    } catch (err) {
      return {};
    }
  }

  var GI18N = readGlobalI18n();

  var MONTHS = {
    leden: 1, ledna: 1, led: 1,
    unor: 2, unora: 2, uno: 2,
    brezen: 3, brezna: 3, bre: 3,
    duben: 4, dubna: 4, dub: 4,
    kveten: 5, kvetna: 5, kve: 5,
    cerven: 6, cervna: 6,
    cervenec: 7, cervence: 7,
    srpen: 8, srpna: 8, srp: 8,
    zari: 9,
    rijen: 10, rijna: 10,
    listopad: 11, listopadu: 11, lis: 11,
    prosinec: 12, prosince: 12, pro: 12
  };

  var MONTH_NAMES = [
    '', 'leden', 'unor', 'brezen', 'duben', 'kveten', 'cerven',
    'cervenec', 'srpen', 'zari', 'rijen', 'listopad', 'prosinec'
  ];
  var MONTH_GENITIVE = [
    '', 'ledna', 'unora', 'brezna', 'dubna', 'kvetna', 'cervna',
    'cervence', 'srpna', 'zari', 'rijna', 'listopadu', 'prosince'
  ];

  function fold(s) {
    return (s || '').toLowerCase().trim().replace(/\.$/, '')
      .normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  }

  function parseCzechDateParts(q) {
    var raw = (q || '').trim();
    if (!raw) return null;

    var iso = /^(\d{4})-(\d{2})-(\d{2})\s*$/.exec(raw);
    if (iso) {
      return {
        day: parseInt(iso[3], 10),
        month: parseInt(iso[2], 10),
        year: parseInt(iso[1], 10)
      };
    }

    var num = /^(\d{1,2})\.\s*(\d{1,2})\.?(?:\s*(\d{4}))?\s*$/.exec(raw);
    if (num) {
      var dayN = parseInt(num[1], 10);
      var monthN = parseInt(num[2], 10);
      var yearN = num[3] ? parseInt(num[3], 10) : null;
      if (monthN < 1 || monthN > 12 || dayN < 1 || dayN > 31) return null;
      return { day: dayN, month: monthN, year: yearN };
    }

    var named = /^(\d{1,2})\.?\s*([A-Za-zÁČĎÉĚÍŇÓŘŠŤÚŮÝŽáčďéěíňóřšťúůýž]+)\.?(?:\s+(\d{4}))?\s*$/.exec(raw);
    if (named) {
      var day = parseInt(named[1], 10);
      var monthKey = fold(named[2]);
      var year = named[3] ? parseInt(named[3], 10) : null;
      var month = MONTHS[monthKey];
      if (!month) {
        Object.keys(MONTHS).some(function (alias) {
          if (alias.indexOf(monthKey) === 0 || monthKey.indexOf(alias) === 0) {
            month = MONTHS[alias];
            return true;
          }
          return false;
        });
      }
      if (month) return { day: day, month: month, year: year };
    }
    return null;
  }

  function isPartialDateTyping(q) {
    var t = (q || '').trim();
    if (!t || !/^\d/.test(t)) return false;
    if (parseCzechDateParts(t)) return false;
    return /^\d{1,2}(\.\d{0,2}(\.\d{0,4})?)?$/.test(t);
  }

  function normText(s) {
    return (s || '').toString().toLowerCase()
      .normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  }

  function rowMatchesIso(rowDate, parts) {
    if (!rowDate || !parts) return false;
    var chunks = rowDate.split('-');
    if (chunks.length !== 3) return false;
    var y = parseInt(chunks[0], 10);
    var m = parseInt(chunks[1], 10);
    var d = parseInt(chunks[2], 10);
    if (parts.year !== null && parts.year !== undefined) {
      return y === parts.year && m === parts.month && d === parts.day;
    }
    return m === parts.month && d === parts.day;
  }

  function rowMatchesDateText(txt, parts) {
    if (!parts) return false;
    var day = parts.day;
    var month = parts.month;
    var d1 = day + '.' + month + '.';
    var d2 = String(day).padStart(2, '0') + '.' + String(month).padStart(2, '0') + '.';
    if (txt.indexOf(d1) !== -1 || txt.indexOf(d2) !== -1) return true;

    var monthName = MONTH_NAMES[month];
    var monthGen = MONTH_GENITIVE[month];
    if (txt.indexOf(day + '. ' + monthName) !== -1) return true;
    if (txt.indexOf(day + '. ' + monthGen) !== -1) return true;
    if (txt.indexOf(day + '.' + monthName) !== -1) return true;
    if (txt.indexOf(day + '.' + monthGen) !== -1) return true;

    if (parts.year !== null && parts.year !== undefined) {
      var y = parts.year;
      if (txt.indexOf(day + '.' + month + '.' + y) !== -1) return true;
      if (txt.indexOf(d2 + y) !== -1) return true;
      if (txt.indexOf(String(day).padStart(2, '0') + '.' + String(month).padStart(2, '0') + '.' + y) !== -1) return true;
    }
    return false;
  }

  function rowMatchesPartialDate(tr, q) {
    var isoEl = tr.querySelector('.tx-datum[data-iso-date]');
    var txt = normText(tr.innerText || '');
    var t = q.trim();

    var dm = /^(\d{1,2})\.(\d{1,2})$/.exec(t);
    if (dm) {
      var day = parseInt(dm[1], 10);
      var month = parseInt(dm[2], 10);
      if (isoEl) {
        return rowMatchesIso(isoEl.getAttribute('data-iso-date'), { day: day, month: month, year: null });
      }
      return rowMatchesDateText(txt, { day: day, month: month, year: null });
    }

    var dOnly = /^(\d{1,2})\.$/.exec(t);
    if (dOnly) {
      var d = parseInt(dOnly[1], 10);
      if (isoEl) {
        var chunks = isoEl.getAttribute('data-iso-date').split('-');
        if (parseInt(chunks[2], 10) === d) return true;
      }
      return txt.indexOf(d + '. ') !== -1 || txt.indexOf(d + '.') === 0;
    }

    var digit = /^(\d{1,2})$/.exec(t);
    if (digit) {
      var n = parseInt(digit[1], 10);
      if (isoEl) {
        var parts = isoEl.getAttribute('data-iso-date').split('-');
        var iy = parseInt(parts[0], 10);
        var im = parseInt(parts[1], 10);
        var id = parseInt(parts[2], 10);
        if (id === n || im === n || String(iy).indexOf(t) === 0) return true;
      }
      return txt.indexOf(t) !== -1;
    }

    return false;
  }

  function rowMatchesDate(tr, parts) {
    var isoEl = tr.querySelector('.tx-datum[data-iso-date]');
    if (isoEl) return rowMatchesIso(isoEl.getAttribute('data-iso-date'), parts);
    return rowMatchesDateText(normText(tr.innerText || ''), parts);
  }

  function rowMatchesQuery(tr, q) {
    var trimmed = (q || '').trim();
    if (!trimmed) return true;

    var parts = parseCzechDateParts(trimmed);
    if (parts) return rowMatchesDate(tr, parts);

    if (isPartialDateTyping(trimmed)) {
      return rowMatchesPartialDate(tr, trimmed);
    }

    var terms = normText(trimmed).split(/\s+/).filter(Boolean);
    var txt = normText(tr.innerText || '');
    return terms.every(function (term) { return txt.indexOf(term) !== -1; });
  }

  function dispatchSearchEvent(query) {
    document.dispatchEvent(new CustomEvent('ts:changelist-search', {
      detail: { query: query, parts: parseCzechDateParts(query) }
    }));
  }

  function buildSearchUrl(query) {
    var params = new URLSearchParams(window.location.search);
    var trimmed = (query || '').trim();
    if (trimmed) {
      params.set('q', trimmed);
    } else {
      params.delete('q');
    }
    params.delete('p');
    var qs = params.toString();
    return window.location.pathname + (qs ? '?' + qs : '');
  }

  function shouldServerSearch(q) {
    var trimmed = (q || '').trim();
    if (!trimmed) return true;
    if (parseCzechDateParts(trimmed)) return true;
    if (isPartialDateTyping(trimmed)) return false;
    return trimmed.length >= 2;
  }

  function urlSearchQuery() {
    return (new URLSearchParams(window.location.search).get('q') || '').trim();
  }

  window.TsChangelistSearch = {
    parseCzechDateParts: parseCzechDateParts,
    normText: normText,
    rowMatchesDate: rowMatchesDate,
    rowMatchesQuery: rowMatchesQuery
  };

  document.addEventListener('DOMContentLoaded', function () {
    if (document.getElementById('changelist-search-skip')) return;

    var changelist = document.getElementById('changelist');
    var searchForm = document.getElementById('changelist-search');
    var searchInput = document.getElementById('searchbar');
    if (!changelist || !searchForm || !searchInput || searchInput.dataset.tsSearchInit) return;
    searchInput.dataset.tsSearchInit = '1';

    var table = document.getElementById('result_list');
    var tbody = table ? table.querySelector('tbody') : null;
    var rows = [];
    var emptyRow = null;
    var debounceTimer = null;
    var debounceMs = 550;
    var fetchController = null;
    var fetchSeq = 0;
    var serverQuery = urlSearchQuery();

    var cfg = document.getElementById('changelist-search-config');
    var emptyMsg = (cfg && cfg.dataset.emptyMsg) || 'Nebyly nalezeny žádné výsledky.';

    function hasResultTable() {
      return !!document.getElementById('result_list');
    }

    function cacheRows() {
      table = document.getElementById('result_list');
      if (!table) {
        rows = [];
        tbody = null;
        return;
      }
      tbody = table.querySelector('tbody');
      if (!tbody) {
        rows = [];
        return;
      }
      rows = Array.from(tbody.querySelectorAll('tr')).filter(function (tr) {
        return tr.id !== 'changelist-no-results';
      });
    }

    function ensureEmptyRow() {
      if (!table || !tbody) return;
      if (emptyRow && emptyRow.parentNode === tbody) return;
      emptyRow = document.getElementById('changelist-no-results');
      if (!emptyRow) {
        emptyRow = document.createElement('tr');
        emptyRow.id = 'changelist-no-results';
        var td = document.createElement('td');
        td.colSpan = table.querySelectorAll('thead th').length || 12;
        td.style.textAlign = 'center';
        td.textContent = emptyMsg;
        emptyRow.appendChild(td);
        emptyRow.style.display = 'none';
        tbody.appendChild(emptyRow);
      }
    }

    function resetClientFilter() {
      cacheRows();
      if (!table) return;
      ensureEmptyRow();
      rows.forEach(function (tr) {
        tr.style.display = '';
      });
      if (emptyRow) emptyRow.style.display = 'none';
    }

    function applyClientFilter(q) {
      cacheRows();
      if (!table) return;
      ensureEmptyRow();
      var trimmed = (q || '').trim();
      var visible = 0;
      rows.forEach(function (tr) {
        var ok = rowMatchesQuery(tr, trimmed);
        tr.style.display = ok ? '' : 'none';
        if (ok) visible++;
      });
      if (emptyRow) {
        emptyRow.style.display = trimmed && visible === 0 ? '' : 'none';
      }
    }

    function applyChangelistHtml(html) {
      var doc = new DOMParser().parseFromString(html, 'text/html');
      var newForm = doc.getElementById('changelist-form');
      var curForm = document.getElementById('changelist-form');
      if (newForm && curForm) {
        curForm.innerHTML = newForm.innerHTML;
      }
      var newCount = doc.querySelector('#changelist-search .small.quiet');
      var curCount = document.querySelector('#changelist-search .small.quiet');
      if (newCount && curCount) {
        curCount.innerHTML = newCount.innerHTML;
      }
      emptyRow = null;
      cacheRows();
      ensureEmptyRow();
    }

    function needsServerReset() {
      return !!serverQuery || !!urlSearchQuery() || !hasResultTable();
    }

    function serverFetch(query) {
      var trimmed = (query || '').trim();
      var url = buildSearchUrl(trimmed);
      var requestId = ++fetchSeq;

      if (fetchController) fetchController.abort();
      fetchController = new AbortController();

      changelist.classList.add('ts-search-loading');

      return fetch(url, {
        signal: fetchController.signal,
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      })
        .then(function (r) { return r.text(); })
        .then(function (html) {
          if (requestId !== fetchSeq) return;
          applyChangelistHtml(html);
          serverQuery = trimmed;
          history.replaceState(null, '', url);
          var current = (searchInput.value || '').trim();
          if (current) {
            applyClientFilter(current);
          } else {
            resetClientFilter();
          }
          dispatchSearchEvent(current);
        })
        .catch(function (err) {
          if (err && err.name === 'AbortError') return;
        })
        .finally(function () {
          if (requestId === fetchSeq) {
            changelist.classList.remove('ts-search-loading');
          }
        });
    }

    function scheduleServerFetch(q) {
      clearTimeout(debounceTimer);
      var trimmed = (q || '').trim();

      if (!trimmed) {
        if (needsServerReset()) {
          serverFetch('');
        } else {
          resetClientFilter();
        }
        return;
      }

      if (!shouldServerSearch(trimmed)) return;

      debounceTimer = setTimeout(function () {
        var current = (searchInput.value || '').trim();
        if (!shouldServerSearch(current)) return;
        if (current === serverQuery) return;
        serverFetch(current);
      }, debounceMs);
    }

    function handleSearch(q) {
      var trimmed = (q || '').trim();
      if (!trimmed) {
        dispatchSearchEvent('');
        scheduleServerFetch('');
        return;
      }
      applyClientFilter(q);
      dispatchSearchEvent(q);
      scheduleServerFetch(q);
    }

    cacheRows();
    ensureEmptyRow();
    searchInput.setAttribute('placeholder', GI18N.search || 'Hledat');

    searchForm.addEventListener('submit', function (e) {
      e.preventDefault();
      clearTimeout(debounceTimer);
      var q = (searchInput.value || '').trim();
      if (!q) {
        if (needsServerReset()) {
          serverFetch('');
        } else {
          resetClientFilter();
          dispatchSearchEvent('');
        }
        return;
      }
      serverFetch(q);
    });

    searchInput.addEventListener('input', function () {
      handleSearch(searchInput.value || '');
    });

    var initialQ = (searchInput.value || '').trim();
    if (initialQ && !hasResultTable()) {
      serverFetch('');
    } else if (initialQ) {
      applyClientFilter(initialQ);
      dispatchSearchEvent(initialQ);
    }
  });
})();
