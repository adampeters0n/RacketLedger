(function () {
      function wireDochazka(ctx) {
        var group = ctx.querySelector('#dochazka_set-group') || ctx.querySelector('#dochazky-group') ||
          Array.from(ctx.querySelectorAll('.inline-group')).find(function (g) {
            var h2 = g.querySelector('h2');
            var t = h2 ? (h2.textContent || '').toLowerCase() : '';
            return /doch[aá]zk|hr[aá]č/.test(t);
          });
        if (!group) return;

        var isFirstRun = !group.classList.contains('x-wired');
        if (isFirstRun) {
          group.classList.add('x-wired', 'x-dochazka-inline');
          if (!group.id) group.id = 'dochazka_set-group';
        }

        if (isFirstRun) {
          var thead = group.querySelector('thead');
          if (thead) {
            var headerMap = [
              [/hrac|hráč/i, 'Hráč'],
              [/cena/i, 'Cena'],
              [/castka|na[uú]ct|naúčt/i, 'Naúčtováno'],
              [/nauceno|naúčteno|kdy/i, 'Kdy naúčtováno'],
            ];
            thead.querySelectorAll('th').forEach(function (th) {
              var raw = (th.textContent || '').trim();
              if (!raw || raw.length < 2) return;
              for (var j = 0; j < headerMap.length; j++) {
                if (headerMap[j][0].test(raw)) {
                  th.textContent = headerMap[j][1];
                  break;
                }
              }
            });
          }
          var h2 = group.querySelector('h2');
          if (h2) h2.style.display = 'none';
          group.querySelectorAll('.inline_label, td.original, th.original').forEach(function (n) { n.remove(); });

          var addRow = group.querySelector('.add-row');
          if (addRow) {
            var a = addRow.querySelector('a');
            if (a) a.textContent = 'Přidat docházku';
            addRow.style.display = '';
            addRow.style.visibility = '';
          }
        }

        if (isFirstRun && !group.hasAttribute('data-x-delete-wired')) {
          group.setAttribute('data-x-delete-wired', '1');
          group.addEventListener('click', function (ev) {
            var target = ev.target;
            var lastCell = target && target.closest && target.closest('tbody td:last-child');
            if (!lastCell) return;
            var link = target.closest('.inline-deletelink, .deletelink, .x-clear-hrac');
            if (!link) return;
            ev.preventDefault();
            ev.stopPropagation();
            var tbody = lastCell.closest('tbody');
            var rows = tbody ? tbody.querySelectorAll('tr.form-row') : [];
            if (rows.length <= 1) {
              var sel = lastCell.closest('tr').querySelector('select');
              if (sel) { sel.value = ''; if (window.jQuery && sel.id) window.jQuery(sel).trigger('change'); }
              return;
            }
            var djangoDel = lastCell.querySelector('.inline-deletelink, .deletelink');
            if (djangoDel && window.jQuery) { window.jQuery(djangoDel).trigger('click'); return; }
            var tr = lastCell.closest('tr');
            if (tr && link.classList.contains('x-clear-hrac')) {
              var form = tr.closest('form');
              tr.remove();
              if (form) {
                var totalInput = form.querySelector('input[name*="TOTAL_FORMS"]');
                if (totalInput) { var n = parseInt(totalInput.value, 10) || 0; totalInput.value = Math.max(0, n - 1); }
                form.dispatchEvent(new Event('formset:removed', { bubbles: true }));
              }
            }
          }, true);
        }

        var tbody = group.querySelector('tbody');
        if (tbody) {
          tbody.querySelectorAll('tr.form-row').forEach(function (tr) {
            var lastTd = tr.querySelector('td:last-child');
            if (!lastTd) return;
            var div = lastTd.querySelector('div');
            if (div) {
              [].slice.call(div.children).forEach(function (child) {
                if (child.nodeName === 'LABEL') child.remove();
                else if (child.nodeName === 'INPUT' && child.type === 'checkbox') child.style.cssText = 'display:none!important;position:absolute;left:-9999px;';
                else if (child.nodeName === 'A' && child.classList && !child.classList.contains('inline-deletelink') && !child.classList.contains('x-clear-hrac')) child.remove();
              });
            }
            if (lastTd.querySelector('.inline-deletelink, .deletelink')) return;
            if (lastTd.querySelector('.x-clear-hrac')) return;
            var a = document.createElement('a');
            a.href = '#';
            a.className = 'x-clear-hrac';
            a.textContent = '×';
            a.setAttribute('aria-label', 'Odstranit');
            lastTd.appendChild(a);
          });
        }
      }

      function ensureCasNadBublinou() {
        var row = document.querySelector('.form-row.field-datum');
        if (!row) return;
        var timeInput = row.querySelector('input.vTimeField');
        if (timeInput) {
          var wrap = timeInput.closest('p') || timeInput.closest('div') || timeInput.parentElement;
          if (wrap) {
            wrap.style.display = 'flex';
            wrap.style.flexDirection = 'column';
            wrap.style.gap = '6px';
            wrap.style.margin = '0';
          }
          var label = row.querySelector('label[for="' + (timeInput.id || '') + '"]');
          if (label) {
            label.style.display = 'block';
            label.style.fontWeight = '700';
            label.style.color = '#111827';
            label.style.marginBottom = '4px';
            label.style.order = '-1';
          }
        }
        var shortcuts = row.querySelectorAll('.datetimeshortcuts');
        shortcuts.forEach(function(span) {
          span.style.setProperty('display', 'inline-flex', 'important');
          span.style.setProperty('justify-content', 'flex-start', 'important');
          span.style.setProperty('text-align', 'left', 'important');
          span.style.setProperty('margin-left', '0', 'important');
          span.style.setProperty('margin-right', 'auto', 'important');
          span.style.setProperty('align-self', 'flex-start', 'important');
        });
        var timeInput = row.querySelector('input.vTimeField');
        if (timeInput) {
          var timeWrap = timeInput.closest('p');
          if (timeWrap) {
            timeWrap.style.setProperty('margin-top', '2px', 'important');
            timeWrap.style.setProperty('padding-top', '0', 'important');
          }
        }
        var dateInput = row.querySelector('input.vDateField');
        if (dateInput) {
          var dateP = dateInput.closest('p');
          var container = dateP ? dateP.parentElement : null;
          if (container && container.nodeName === 'DIV') {
            container.style.setProperty('display', 'flex', 'important');
            container.style.setProperty('flex-direction', 'column', 'important');
            container.style.setProperty('gap', '0', 'important');
          }
        }
      }

      function hideEmptyDochazkaRows(ctx) {
        var group = ctx.querySelector('#dochazka_set-group') || ctx.querySelector('#dochazky-group');
        if (!group) return;
        group.querySelectorAll('tbody tr.form-row').forEach(function (tr) {
          if (tr.classList.contains('empty-form')) return;
          var sel = tr.querySelector('select[name$="-hrac"]');
          if (!sel || sel.value) return;
          tr.style.display = 'none';
          tr.setAttribute('data-x-empty-hrac', '1');
        });
      }

      function boot() {
        wireDochazka(document);
        ensureCasNadBublinou();
        hideEmptyDochazkaRows(document);
      }
      document.addEventListener('DOMContentLoaded', boot);
      window.addEventListener('load', boot);
      document.addEventListener('formset:added', function (ev) {
        boot();
        var row = ev.target && ev.target.closest && ev.target.closest('tr.form-row');
        if (row) {
          row.style.display = '';
          row.removeAttribute('data-x-empty-hrac');
        }
      });
      setTimeout(boot, 0);
      setTimeout(boot, 120);
    })();
