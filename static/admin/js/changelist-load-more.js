/**
 * AJAX „Načíst dalších N“ – připojí další řádky k tabulce bez reloadu stránky.
 */
(function () {
  function qs(sel, root) {
    return (root || document).querySelector(sel);
  }

  function qsa(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function updateShownLabel(paginator, shown, total) {
    var label = qs('.paginator-shown-label', paginator);
    if (!label) return;
    label.textContent = 'Zobrazeno ' + shown + ' z ' + total;
  }

  function rowCount() {
    return qsa('#result_list tbody tr').filter(function (tr) {
      return !tr.classList.contains('row-form-errors');
    }).length;
  }

  function init() {
    var paginator = qs('#changelist-paginator');
    var btn = qs('.paginator-load-more', paginator);
    var tbody = qs('#result_list tbody');
    if (!paginator || !btn || !tbody) return;

    var textEl = btn.querySelector('.paginator-load-more__text');
    var idleLabel = btn.getAttribute('data-idle-label')
      || (textEl ? textEl.textContent : btn.textContent.trim());
    var loadingLabel = btn.getAttribute('data-loading-label') || 'Načítám…';
    var total = parseInt(paginator.getAttribute('data-result-count') || '0', 10) || 0;
    var busy = false;

    function setButtonLabel(label) {
      if (textEl) textEl.textContent = label;
      else btn.textContent = label;
    }

    btn.addEventListener('click', function () {
      if (busy) return;
      var nextUrl = btn.getAttribute('data-next-url');
      if (!nextUrl) return;

      busy = true;
      btn.disabled = true;
      setButtonLabel(loadingLabel);

      fetch(nextUrl, {
        credentials: 'same-origin',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'Accept': 'text/html'
        }
      })
        .then(function (res) {
          if (!res.ok) throw new Error('HTTP ' + res.status);
          return res.text();
        })
        .then(function (html) {
          var doc = new DOMParser().parseFromString(html, 'text/html');
          var newRows = qsa('#result_list tbody tr', doc);
          if (!newRows.length) {
            btn.remove();
            return;
          }
          newRows.forEach(function (tr) {
            tbody.appendChild(document.importNode(tr, true));
          });

          var shown = rowCount();
          updateShownLabel(paginator, shown, total);

          // Sync čísel stránek (1 2 3) z odpovědi
          var newPages = qs('.paginator-pages', doc);
          var curPages = qs('.paginator-pages', paginator);
          if (newPages && curPages) {
            curPages.innerHTML = newPages.innerHTML;
          } else if (newPages && !curPages) {
            paginator.insertBefore(document.importNode(newPages, true), btn);
          } else if (!newPages && curPages) {
            curPages.remove();
          }

          var nextBtn = qs('.paginator-load-more', doc);
          var next = nextBtn && nextBtn.getAttribute('data-next-url');
          if (next) {
            btn.setAttribute('data-next-url', next);
            setButtonLabel(idleLabel);
            btn.disabled = false;
          } else {
            btn.remove();
          }

          document.dispatchEvent(new CustomEvent('ts:changelist-load-more', {
            detail: { shown: shown, total: total }
          }));

          // Django admin: obnovit počítadlo vybraných akcí, pokud existuje
          try {
            if (window.django && django.jQuery) {
              django.jQuery(document).trigger('list-update');
            }
          } catch (e) { /* ignore */ }
        })
        .catch(function () {
          setButtonLabel(idleLabel);
          btn.disabled = false;
          alert('Načtení dalších řádků se nezdařilo. Zkuste to znovu.');
        })
        .finally(function () {
          busy = false;
        });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
