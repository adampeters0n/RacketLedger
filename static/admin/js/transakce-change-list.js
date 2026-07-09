document.addEventListener('DOMContentLoaded', function () {
  var cfg = document.getElementById('transakce-changelist-config');
  if (!cfg) return;

  var trainingsUrl = cfg.dataset.trainingsUrl || '';
  var trainingsBox = document.getElementById('transakce-day-trainings');
  var trainingsBody = document.getElementById('transakce-day-trainings-body');
  var trainingsTitle = document.getElementById('transakce-day-trainings-title');
  var lastFetchKey = '';

  function renderTrainings(data) {
    if (!trainingsBox || !trainingsBody || !trainingsTitle) return;
    if (!data || !data.ok) {
      trainingsBox.style.display = 'none';
      trainingsBody.innerHTML = '';
      return;
    }
    trainingsTitle.textContent = 'Tréninky – ' + (data.date_label || '');
    if (!data.trainings || !data.trainings.length) {
      trainingsBody.innerHTML = '<p class="transakce-day-trainings-empty">Pro tento den nejsou žádné tréninky.</p>';
      trainingsBox.style.display = 'block';
      return;
    }
    var html = '<table class="transakce-day-trainings-table"><thead><tr>'
      + '<th>Datum</th><th>Čas</th><th>Trenér</th><th>Formát</th><th>Hráči</th><th></th>'
      + '</tr></thead><tbody>';
    data.trainings.forEach(function (t) {
      html += '<tr>'
        + '<td>' + (t.date || '') + '</td>'
        + '<td>' + t.time + '</td>'
        + '<td>' + t.trener + '</td>'
        + '<td>' + t.format + '</td>'
        + '<td>' + t.hraci + '</td>'
        + '<td><a href="' + t.url + '">Otevřít</a></td>'
        + '</tr>';
    });
    html += '</tbody></table>';
    trainingsBody.innerHTML = html;
    trainingsBox.style.display = 'block';
  }

  function loadTrainings(parts) {
    if (!trainingsUrl || !parts) {
      renderTrainings(null);
      return;
    }
    var key = parts.day + '-' + parts.month + '-' + (parts.year || '');
    if (key === lastFetchKey) return;
    lastFetchKey = key;
    var url = trainingsUrl + '?day=' + encodeURIComponent(parts.day) + '&month=' + encodeURIComponent(parts.month);
    if (parts.year) url += '&year=' + encodeURIComponent(parts.year);
    fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.json(); })
      .then(renderTrainings)
      .catch(function () { renderTrainings(null); });
  }

  document.addEventListener('ts:changelist-search', function (e) {
    var parts = e.detail && e.detail.parts;
    if (parts) {
      loadTrainings(parts);
    } else {
      lastFetchKey = '';
      renderTrainings(null);
    }
  });

  var initialQ = cfg.dataset.initialQuery || new URLSearchParams(window.location.search).get('q') || '';
  var parse = window.TsChangelistSearch && window.TsChangelistSearch.parseCzechDateParts;
  if (parse) {
    var initialParts = parse(initialQ);
    if (initialParts) loadTrainings(initialParts);
  }
});
