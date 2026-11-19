(function () {
  "use strict";

  var boundForm = null;

  function selectedCount(form) {
    if (!form) return 0;
    return form.querySelectorAll('input[name="_selected_action"]:checked').length;
  }

  function selectedIds(form) {
    if (!form) return [];
    return Array.prototype.map.call(
      form.querySelectorAll('input[name="_selected_action"]:checked'),
      function (el) {
        return el.value;
      }
    );
  }

  function wrapField(node, extraClass, labelText) {
    if (!node) return null;
    if (node.parentElement && node.parentElement.classList.contains("cenik-field")) {
      return node.parentElement;
    }
    var wrap = document.createElement("div");
    wrap.className = "cenik-field" + (extraClass ? " " + extraClass : "");
    node.parentNode.insertBefore(wrap, node);
    if (labelText) {
      var lab = document.createElement("p");
      lab.className = "cenik-field__label";
      lab.textContent = labelText;
      wrap.appendChild(lab);
    }
    wrap.appendChild(node);
    return wrap;
  }

  function actionSelect(form) {
    return (
      form.querySelector('.actions select[name="action"]') ||
      form.querySelector('select[name="action"]')
    );
  }

  function actionSubmit(form) {
    return (
      form.querySelector('.actions button[type="submit"]') ||
      form.querySelector('.actions input[type="submit"]') ||
      form.querySelector(".actions .button")
    );
  }

  function shortActionLabel(value, text) {
    var t = (text || "").replace(/\u00a0/g, " ").trim();
    if (value === "delete_selected") return "Smazat";
    if (/odstran|smaz/i.test(t)) return "Smazat";
    return t || value;
  }

  function actionKind(value, text) {
    if (value === "delete_selected" || /odstran|smaz|delete/i.test(text || "")) {
      return "delete";
    }
    return "generic";
  }

  function ensureSelectedBar(container) {
    var bar = container.querySelector(":scope > .cenik-selected");
    if (bar) return bar;
    bar = document.createElement("div");
    bar.className = "cenik-selected";
    bar.setAttribute("hidden", "hidden");
    bar.innerHTML =
      '<span class="cenik-selected__status">' +
      '<span class="cenik-selected__check" aria-hidden="true"></span>' +
      '<span class="cenik-selected__label"></span>' +
      "</span>" +
      '<div class="cenik-selected__actions"></div>';
    container.appendChild(bar);
    return bar;
  }

  function formatSelectedLabel(count) {
    if (count === 1) return "1 vybráno";
    return count + " vybráno";
  }

  function runDjangoAction(form, value) {
    var select = actionSelect(form);
    var submit = actionSubmit(form);
    if (!select || !value) return;
    select.value = value;
    if (typeof select.dispatchEvent === "function") {
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }
    if (submit) {
      if (typeof submit.click === "function") submit.click();
      else if (form.requestSubmit) form.requestSubmit(submit);
      else form.submit();
    }
  }

  function buildActionButtons(form, bar) {
    var actionsWrap = bar.querySelector(".cenik-selected__actions");
    if (!actionsWrap) return;
    actionsWrap.innerHTML = "";

    var selectAllBtn = document.createElement("button");
    selectAllBtn.type = "button";
    selectAllBtn.className = "cenik-act cenik-act--select-all";
    selectAllBtn.textContent = "Vybrat vše";
    selectAllBtn.addEventListener("click", function () {
      var toggle = form.querySelector("#action-toggle");
      var boxes = form.querySelectorAll('input[name="_selected_action"]');
      var allOn = Array.prototype.every.call(boxes, function (b) {
        return b.checked;
      });
      var next = !allOn;
      if (toggle) {
        toggle.checked = next;
        if (typeof toggle.dispatchEvent === "function") {
          toggle.dispatchEvent(new Event("change", { bubbles: true }));
        }
      }
      Array.prototype.forEach.call(boxes, function (b) {
        b.checked = next;
      });
      syncSelection(form, bar.parentElement);
    });
    actionsWrap.appendChild(selectAllBtn);

    var editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "cenik-act cenik-act--edit";
    editBtn.innerHTML =
      '<span class="cenik-act__icon" aria-hidden="true"></span>' +
      "<span>Upravit</span>";
    editBtn.addEventListener("click", function () {
      var ids = selectedIds(form);
      if (ids.length !== 1) return;
      var base = window.location.pathname.replace(/\/?$/, "/");
      window.location.href = base + ids[0] + "/change/";
    });
    actionsWrap.appendChild(editBtn);

    var select = actionSelect(form);
    if (select) {
      Array.prototype.forEach.call(select.options, function (opt) {
        if (!opt.value) return;
        var kind = actionKind(opt.value, opt.textContent);
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "cenik-act cenik-act--" + kind;
        btn.dataset.action = opt.value;
        btn.innerHTML =
          '<span class="cenik-act__icon" aria-hidden="true"></span>' +
          "<span>" +
          shortActionLabel(opt.value, opt.textContent) +
          "</span>";
        btn.addEventListener("click", function () {
          runDjangoAction(form, opt.value);
        });
        actionsWrap.appendChild(btn);
      });
    }
  }

  function syncSelection(form, container) {
    var count = selectedCount(form);
    if (container) container.classList.toggle("cenik-has-selection", count > 0);

    var bar = container && ensureSelectedBar(container);
    if (!bar) return;

    var label = bar.querySelector(".cenik-selected__label");
    var editBtn = bar.querySelector(".cenik-act--edit");

    if (count > 0) {
      if (label) label.textContent = formatSelectedLabel(count);
      if (editBtn) {
        editBtn.disabled = count !== 1;
        editBtn.classList.toggle("is-disabled", count !== 1);
        editBtn.title =
          count === 1 ? "Upravit vybranou položku" : "Upravit lze jen jednu položku";
      }
      var selectAllBtn = bar.querySelector(".cenik-act--select-all");
      if (selectAllBtn) {
        var boxes = form.querySelectorAll('input[name="_selected_action"]');
        var allOn =
          boxes.length > 0 &&
          Array.prototype.every.call(boxes, function (b) {
            return b.checked;
          });
        selectAllBtn.textContent = allOn ? "Zrušit výběr" : "Vybrat vše";
      }
      bar.removeAttribute("hidden");
    } else {
      bar.setAttribute("hidden", "hidden");
    }
  }

  function enhanceActions(form, container) {
    if (!form) return;
    var actions = form.querySelector(".actions");
    if (!actions) return;

    actions.classList.add("cenik-actions");
    actions.setAttribute("aria-hidden", "true");

    var counter = actions.querySelector(".action-counter");
    if (counter) counter.setAttribute("hidden", "hidden");

    var bar = ensureSelectedBar(container);
    buildActionButtons(form, bar);
  }

  function polishAddLabel() {
    /* Finální pill „+ Přidat …“ řeší cenik-change-list.js (stejný look všude). */
    var link =
      document.querySelector(".ts-page-head .object-tools a.addlink") ||
      document.querySelector("#content .object-tools a.addlink");
    if (!link || link.dataset.cenikAddLabel === "1") return;
    var text = (link.textContent || "").replace(/\s+/g, " ").trim();
    if (!text) return;

    var m =
      text.match(/^\+?\s*Přidejte?\s+(.+)$/i) ||
      text.match(/^\+?\s*Přidat\s+(.+)$/i) ||
      text.match(/^\+?\s*Add\s+(.+)$/i) ||
      text.match(/^(.+?)\s*:\s*přidat$/i);
    // Neupravovat vlastní odkazy (Rodiny, Skupiny, Nastavení…)
    if (!m && !/^Přidat\b/i.test(text) && !/^\+\s*Přidat\b/i.test(text)) return;

    var label = m ? "+ Přidat " + m[1] : text.replace(/^\+\s*/, "").trim();
    if (!/^\+/.test(label)) label = "+ " + label;
    // „Přidat“ bez objektu → doplň z nadpisu stránky (Ceník → Přidat ceník)
    if (/^\+?\s*Přidat$/i.test(label)) {
      var titleEl = document.querySelector(".ts-page-head__title");
      var title = titleEl && (titleEl.textContent || "").replace(/\s+/g, " ").trim();
      if (title) {
        label = "+ Přidat " + title.charAt(0).toLowerCase() + title.slice(1);
      }
    }
    var plus = link.querySelector(".ts-btn-plus");
    if (plus) plus.remove();
    link.textContent = label;
    link.dataset.cenikAddLabel = "1";
  }

  function formatItemCount(n) {
    var count = parseInt(n, 10);
    if (!isFinite(count) || count < 0) count = 0;
    if (count === 1) return "1 položka";
    if (count >= 2 && count <= 4) return count + " položky";
    return count + " položek";
  }

  function syncFootCount() {
    var paginator = document.getElementById("changelist-paginator");
    if (!paginator) return;
    var raw = paginator.getAttribute("data-result-count");
    if (raw == null || raw === "") return;
    var label = formatItemCount(raw);
    document
      .querySelectorAll("[data-cenik-foot-count], [data-ts-cl-foot-count]")
      .forEach(function (el) {
        el.textContent = label;
      });
  }

  function enhanceSortHeaders() {
    /* Ikony jsou čisté CSS (a::after) – jen ukliď starý JS markup */
    var table = document.getElementById("result_list");
    if (!table) return;
    Array.prototype.forEach.call(table.querySelectorAll(".ts-sort"), function (el) {
      if (el && el.parentNode) el.parentNode.removeChild(el);
    });
  }

  var sortFetchController = null;
  var sortFetchSeq = 0;
  var sortClickBound = false;

  function applySortedChangelistHtml(html) {
    var doc = new DOMParser().parseFromString(html, "text/html");
    var newForm = doc.getElementById("changelist-form");
    var curForm = document.getElementById("changelist-form");
    if (newForm && curForm) {
      curForm.innerHTML = newForm.innerHTML;
    }
    var newCount = doc.querySelector("#changelist-search .small.quiet");
    var curCount = document.querySelector("#changelist-search .small.quiet");
    if (newCount && curCount) {
      curCount.innerHTML = newCount.innerHTML;
    } else if (newCount && !curCount) {
      var search = document.getElementById("changelist-search");
      if (search) search.appendChild(newCount.cloneNode(true));
    }
  }

  function fetchSortedChangelist(url) {
    var requestId = ++sortFetchSeq;
    if (sortFetchController) sortFetchController.abort();
    sortFetchController = new AbortController();

    var changelist = document.getElementById("changelist");
    if (changelist) changelist.classList.add("ts-search-loading");

    return fetch(url, {
      signal: sortFetchController.signal,
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
    })
      .then(function (r) {
        return r.text();
      })
      .then(function (html) {
        if (requestId !== sortFetchSeq) return;
        applySortedChangelistHtml(html);
        history.replaceState(null, "", url);
        enhance();
        document.dispatchEvent(
          new CustomEvent("ts:changelist-search", { detail: { sort: true } })
        );
      })
      .catch(function (err) {
        if (err && err.name === "AbortError") return;
        window.location.assign(url);
      })
      .finally(function () {
        if (requestId === sortFetchSeq && changelist) {
          changelist.classList.remove("ts-search-loading");
        }
      });
  }

  function bindAjaxSort() {
    if (sortClickBound) return;
    sortClickBound = true;
    document.addEventListener("click", function (event) {
      if (!document.body.classList.contains("change-list")) return;
      var a = event.target && event.target.closest
        ? event.target.closest("#result_list thead th.sortable a, #result_list thead th.sorted a")
        : null;
      if (!a) return;
      var href = a.getAttribute("href");
      if (!href || href === "#") return;
      event.preventDefault();
      event.stopPropagation();
      var url = a.href || href;
      fetchSortedChangelist(url);
    });
  }

  function enhance() {
    if (!document.body.classList.contains("change-list")) return;

    polishAddLabel();

    var changelist = document.getElementById("changelist");
    var form = document.getElementById("changelist-form");
    if (!changelist || !form) return;

    var container =
      changelist.querySelector(".changelist-form-container") || changelist;
    container.classList.add("cenik-layout");

    var toolbar = changelist.querySelector("#toolbar");
    wrapField(toolbar, "cenik-field--search", "Hledat");

    enhanceActions(form, container);
    enhanceSortHeaders();

    var table = document.getElementById("result_list");
    if (table) {
      var oldFoot = table.querySelector("tfoot.cenik-table-foot");
      if (oldFoot) oldFoot.remove();
    }
    var paginator = document.getElementById("changelist-paginator");
    if (paginator) {
      paginator.classList.remove("cenik-paginator--table-foot");
      var info = paginator.querySelector(".paginator-info");
      if (info) info.setAttribute("hidden", "hidden");
    }
    syncFootCount();

    var input =
      document.querySelector("#changelist-search #searchbar") ||
      document.querySelector('#changelist-search input[type="text"]');
    if (input && !input.getAttribute("placeholder")) {
      input.setAttribute("placeholder", "Hledat…");
    }

    syncSelection(form, container);

    if (boundForm !== form) {
      boundForm = form;
      form.addEventListener("change", function (event) {
        var t = event.target;
        if (!t) return;
        if (t.name === "_selected_action" || t.id === "action-toggle") {
          syncSelection(form, container);
        }
      });
      form.addEventListener("click", function (event) {
        var t = event.target;
        if (!t) return;
        if (t.name === "_selected_action" || t.id === "action-toggle") {
          window.setTimeout(function () {
            syncSelection(form, container);
          }, 0);
        }
      });
    }
  }

  function boot() {
    bindAjaxSort();
    enhance();
    polishAddLabel();
    // Layout + FOUC ready řeší cenik-change-list.js (stejný design všude)
    window.requestAnimationFrame(function () {
      polishAddLabel();
    });
    window.setTimeout(function () {
      polishAddLabel();
    }, 50);
    document.addEventListener("ts:changelist-search", function () {
      window.setTimeout(function () {
        enhance();
        polishAddLabel();
      }, 0);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
