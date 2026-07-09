(function () {
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
    }
    return false;
  }

  function rowMatchesDate(tr, parts) {
    var isoEl = tr.querySelector('.tx-datum[data-iso-date]');
    if (isoEl) return rowMatchesIso(isoEl.getAttribute('data-iso-date'), parts);
    return rowMatchesDateText(normText(tr.innerText || ''), parts);
  }

  window.TsChangelistSearch = {
    parseCzechDateParts: parseCzechDateParts,
    normText: normText,
    rowMatchesDate: rowMatchesDate
  };

  document.addEventListener('DOMContentLoaded', function () {
    if (document.getElementById('changelist-search-skip')) return;

    var changelist = document.getElementById('changelist');
    var table = document.getElementById('result_list');
    var searchInput = document.getElementById('searchbar');
    if (!changelist || !table || !searchInput || searchInput.dataset.tsSearchInit) return;
    searchInput.dataset.tsSearchInit = '1';

    var tbody = table.querySelector('tbody');
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll('tr'));

    var cfg = document.getElementById('changelist-search-config');
    var emptyMsg = (cfg && cfg.dataset.emptyMsg) || 'Nebyly nalezeny žádné výsledky.';

    var emptyRow = document.getElementById('changelist-no-results');
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

    function applyFilter(q, parts) {
      var terms = normText(q).split(/\s+/).filter(Boolean);
      var visible = 0;
      rows.forEach(function (tr) {
        if (tr.id === 'changelist-no-results') return;
        var txt = normText(tr.innerText || '');
        var ok = true;
        if (parts) {
          ok = rowMatchesDate(tr, parts);
        } else if (terms.length) {
          ok = terms.every(function (t) { return txt.indexOf(t) !== -1; });
        }
        tr.style.display = ok ? '' : 'none';
        if (ok) visible++;
      });
      if (emptyRow) {
        emptyRow.style.display = (terms.length || parts) && visible === 0 ? '' : 'none';
      }
    }

    function handleSearch(q) {
      var parts = parseCzechDateParts(q);
      applyFilter(q, parts);
      document.dispatchEvent(new CustomEvent('ts:changelist-search', {
        detail: { query: q, parts: parts }
      }));
    }

    var initialQ = (cfg && cfg.dataset.initialQuery)
      || new URLSearchParams(window.location.search).get('q')
      || '';
    handleSearch(initialQ);

    searchInput.setAttribute('placeholder', 'Hledat');
    searchInput.addEventListener('input', function () {
      handleSearch(searchInput.value || '');
    });
  });
})();
