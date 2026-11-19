(function () {
  "use strict";

  function isChangeList() {
    return document.body && document.body.classList.contains("change-list");
  }

  function isCenik() {
    return document.body && document.body.classList.contains("model-cenik");
  }

  function textOf(el) {
    return (el && el.textContent ? el.textContent : "").replace(/\s+/g, " ").trim();
  }

  function isAllChoice(label) {
    return /^(vše|all|qualquer|alle|tout)/i.test(String(label || "").trim());
  }

  function pageTitle() {
    var titleEl = document.querySelector(".ts-page-head__title");
    return titleEl ? textOf(titleEl) : "";
  }

  function polishPageHead() {
    var head = document.querySelector("#content > .ts-page-head");
    if (!head) return;
    head.classList.add("ts-page-head--cenik");
    var eye = head.querySelector(".ts-page-head__eyebrow");
    var rule = head.querySelector(".ts-page-head__rule");
    if (eye) eye.hidden = false;
    if (rule) rule.hidden = false;
  }

  function ensureToolbar(container) {
    var toolbar = container.querySelector(":scope > .ts-cl-toolbar");
    if (toolbar) return toolbar;
    toolbar = document.createElement("div");
    toolbar.className = "ts-cl-toolbar";
    container.insertBefore(toolbar, container.firstChild);
    return toolbar;
  }

  function buildAddLabel(existingText) {
    var text = String(existingText || "").replace(/\s+/g, " ").trim();
    var m =
      text.match(/^\+?\s*Přidejte?\s+(.+)$/i) ||
      text.match(/^\+?\s*Přidat\s+(.+)$/i) ||
      text.match(/^\+?\s*Add\s+(.+)$/i) ||
      text.match(/^(.+?)\s*:\s*přidat$/i);
    if (m) return "+ Přidat " + m[1];
    if (/^\+?\s*Přidat$/i.test(text) || !text) {
      var title = pageTitle();
      if (title) {
        return "+ Přidat " + title.charAt(0).toLowerCase() + title.slice(1);
      }
      return "+ Přidat";
    }
    if (/^Přidat\b/i.test(text) || /^\+\s/.test(text)) {
      return text.replace(/^\+\s*/, "").replace(/^Přidat\b/i, "+ Přidat");
    }
    return null;
  }

  function polishTools(tools) {
    if (!tools) return;
    tools.classList.add("ts-cl-toolbar__actions", "object-tools");
    var add = tools.querySelector("a.addlink");
    if (add) {
      add.classList.add("ts-cl-btn", "ts-cl-btn--primary", "ts-cl-btn--dash");
      add.dataset.cenikAddLabel = "1";
      add.dataset.tsPhPolished = "1";
      var plus = add.querySelector(".ts-btn-plus");
      if (plus) plus.remove();
      var label = buildAddLabel(textOf(add));
      if (label) add.textContent = label;
    }
    tools.querySelectorAll("a:not(.addlink)").forEach(function (a) {
      a.classList.add("ts-cl-btn", "ts-cl-btn--secondary");
    });
  }

  function unwrapTitleRow(text) {
    if (!text) return;
    var oldRow = text.querySelector(":scope > .ts-page-head__title-row");
    if (!oldRow) return;
    var t = oldRow.querySelector(".ts-page-head__title");
    if (t) text.insertBefore(t, oldRow);
    oldRow.remove();
  }

  function placeTools(tools, toolbar) {
    if (!tools) return;
    polishTools(tools);
    var head = document.querySelector("#content > .ts-page-head");
    var text = head && head.querySelector(".ts-page-head__text");
    unwrapTitleRow(text);

    /* Všude: button na úrovni nadpisu (CSS grid) */
    tools.classList.add("ts-cl-head-actions");
    if (head) {
      if (tools.parentNode !== head) head.appendChild(tools);
    } else if (toolbar) {
      toolbar.appendChild(tools);
    }
  }

  function enhanceToolbar(container) {
    var toolbar = ensureToolbar(container);

    var searchField =
      toolbar.querySelector(".cenik-field--search") ||
      container.querySelector(".cenik-field--search") ||
      document.querySelector("#changelist .cenik-field--search");
    if (!searchField) {
      var bare =
        toolbar.querySelector("#toolbar") ||
        container.querySelector(":scope > #toolbar") ||
        document.querySelector("#changelist #toolbar");
      if (bare && bare.parentElement) {
        if (bare.parentElement.classList.contains("cenik-field")) {
          searchField = bare.parentElement;
        } else {
          searchField = document.createElement("div");
          searchField.className = "cenik-field cenik-field--search";
          bare.parentNode.insertBefore(searchField, bare);
          searchField.appendChild(bare);
        }
      }
    }
    if (searchField) {
      var label = searchField.querySelector(".cenik-field__label");
      if (label) label.remove();
      searchField.classList.add("ts-cl-toolbar__search");
      if (toolbar.firstChild !== searchField) {
        toolbar.insertBefore(searchField, toolbar.firstChild);
      }
    }

    var tools =
      document.querySelector("#content > .ts-page-head .object-tools") ||
      toolbar.querySelector(".object-tools") ||
      document.querySelector("#content-main > .object-tools") ||
      document.querySelector("#changelist .object-tools") ||
      document.querySelector(".object-tools");
    placeTools(tools, toolbar);

    var input =
      toolbar.querySelector("#changelist-search #searchbar") ||
      toolbar.querySelector('#changelist-search input[type="text"]');
    if (input) {
      var title = pageTitle();
      var ph = title
        ? "Hledat v " + title.charAt(0).toLowerCase() + title.slice(1) + "…"
        : "Hledat…";
      input.setAttribute("placeholder", ph);
    }
  }

  function closeChipMenus(except) {
    document.querySelectorAll(".ts-cl-chip--menu.is-open").forEach(function (el) {
      if (el !== except) el.classList.remove("is-open");
    });
  }

  function buildFilterBar(changelist, container) {
    var nav = changelist.querySelector("#changelist-filter");
    if (!nav) return;

    var existing = container.querySelector(":scope > .ts-cl-filters");
    if (existing) existing.remove();

    var bar = document.createElement("div");
    bar.className = "ts-cl-filters";
    bar.setAttribute("role", "toolbar");
    bar.setAttribute("aria-label", "Filtry");

    var icon = document.createElement("span");
    icon.className = "ts-cl-filters__icon";
    icon.setAttribute("aria-hidden", "true");
    bar.appendChild(icon);

    var chips = document.createElement("div");
    chips.className = "ts-cl-filters__chips";
    bar.appendChild(chips);

    var detailsList = nav.querySelectorAll("details[data-filter-title]");
    Array.prototype.forEach.call(detailsList, function (details) {
      var title = details.getAttribute("data-filter-title") || "Filtr";
      var selected = details.querySelector("li.selected a");
      var selectedLabel = selected ? textOf(selected) : "";
      var allLink = null;
      var choices = [];
      // Stav: vždy dropdown (Aktivní / Neaktivní / Vše), ne jen chip s ×
      var forceMenu = /^stav$/i.test(String(title).trim());

      Array.prototype.forEach.call(details.querySelectorAll("li a"), function (a) {
        var label = textOf(a);
        var item = {
          href: a.getAttribute("href") || "#",
          label: label,
          selected: a.parentElement.classList.contains("selected"),
        };
        if (!forceMenu && isAllChoice(label)) {
          allLink = item;
        } else {
          choices.push(item);
        }
      });

      var isActive = !!(selected && !isAllChoice(selectedLabel));

      if (isActive && !forceMenu) {
        var active = document.createElement("a");
        active.className = "ts-cl-chip ts-cl-chip--active";
        active.href = (allLink && allLink.href) || "#";
        active.title = "Zrušit filtr: " + title;
        active.innerHTML =
          '<span class="ts-cl-chip__label">' +
          escapeHtml(selectedLabel) +
          '</span><span class="ts-cl-chip__x" aria-hidden="true">×</span>';
        chips.appendChild(active);
        return;
      }

      var menu = document.createElement("div");
      menu.className = "ts-cl-chip ts-cl-chip--menu";
      if (forceMenu && selectedLabel) {
        menu.classList.add("is-selected");
      }
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ts-cl-chip__btn";
      // U Stav ukazuj vybranou hodnotu (Aktivní…); jinak název filtru
      var btnLabel = forceMenu && selectedLabel ? selectedLabel : title;
      btn.innerHTML =
        '<span class="ts-cl-chip__label">' +
        escapeHtml(btnLabel) +
        '</span><span class="ts-cl-chip__chev" aria-hidden="true"></span>';
      btn.setAttribute("aria-expanded", "false");
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        var open = !menu.classList.contains("is-open");
        closeChipMenus(menu);
        menu.classList.toggle("is-open", open);
        btn.setAttribute("aria-expanded", open ? "true" : "false");
      });

      var panel = document.createElement("div");
      panel.className = "ts-cl-chip__panel";
      panel.setAttribute("role", "listbox");

      if (allLink) {
        var allA = document.createElement("a");
        allA.href = allLink.href;
        allA.className = "ts-cl-chip__option" + (allLink.selected ? " is-selected" : "");
        allA.textContent = "Vše";
        panel.appendChild(allA);
      }
      choices.forEach(function (c) {
        var a = document.createElement("a");
        a.href = c.href;
        a.className = "ts-cl-chip__option" + (c.selected ? " is-selected" : "");
        a.textContent = c.label;
        panel.appendChild(a);
      });

      menu.appendChild(btn);
      menu.appendChild(panel);
      chips.appendChild(menu);
    });

    var clear = nav.querySelector("#changelist-filter-extra-actions a");
    if (clear && /clear|zruš|odstran/i.test(textOf(clear))) {
      var clearBtn = document.createElement("a");
      clearBtn.className = "ts-cl-filters__clear";
      clearBtn.href = clear.getAttribute("href") || "#";
      clearBtn.textContent = "Zrušit filtry";
      bar.appendChild(clearBtn);
    }

    nav.hidden = true;
    nav.setAttribute("aria-hidden", "true");

    var searchRow = container.querySelector(":scope > .ts-cl-toolbar");
    if (searchRow && searchRow.nextSibling) {
      container.insertBefore(bar, searchRow.nextSibling);
    } else {
      container.insertBefore(bar, container.firstChild);
    }
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function ensureTableCols() {
    /* Colgroup šířky jsou specifické pro Ceník – jinde nechat auto layout */
    if (!isCenik()) return;

    var table = document.getElementById("result_list");
    if (!table) return;

    var existing = table.querySelector("colgroup.ts-cenik-cols");
    if (existing) existing.remove();

    /* Na úzkém viewportu colgroup + display:none posouvá šířky (Položka → 0). */
    var compact = window.matchMedia("(max-width: 860px)").matches;
    table.classList.toggle("ts-cenik-table--compact", compact);
    if (compact) return;

    var group = document.createElement("colgroup");
    group.className = "ts-cenik-cols";
    var specs = [
      "ts-cenik-col--check",
      "ts-cenik-col--polozka",
      "ts-cenik-col--kategorie",
      "ts-cenik-col--cena",
      "ts-cenik-col--od",
      "ts-cenik-col--do",
    ];
    var headerCells = table.querySelectorAll("thead tr:first-child > th");
    var count = headerCells.length || specs.length;
    for (var i = 0; i < count; i++) {
      var col = document.createElement("col");
      col.className = specs[i] || "ts-cenik-col";
      group.appendChild(col);
    }
    table.insertBefore(group, table.firstChild);
  }

  function countResultRows() {
    return Array.prototype.filter.call(
      document.querySelectorAll("#result_list tbody tr"),
      function (tr) {
        return (
          tr.id !== "changelist-no-results" &&
          !tr.classList.contains("row-form-errors")
        );
      }
    ).length;
  }

  function enhancePaginator() {
    var paginator = document.getElementById("changelist-paginator");
    if (!paginator) return;
    paginator.classList.add("ts-cl-pager");

    var total = parseInt(paginator.getAttribute("data-result-count") || "0", 10) || 0;
    var perPage = parseInt(paginator.getAttribute("data-per-page") || "10", 10) || 10;
    var rows = countResultRows();
    var pageMatch = (window.location.search || "").match(/[?&]p=(\d+)/);
    var page = pageMatch ? parseInt(pageMatch[1], 10) : 1;
    if (!isFinite(page) || page < 1) page = 1;

    var start = total === 0 ? 0 : (page - 1) * perPage + 1;
    var end = total === 0 ? 0 : Math.min(start + rows - 1, total);

    var meta = paginator.querySelector(".ts-cl-pager__meta");
    if (!meta) {
      meta = document.createElement("div");
      meta.className = "ts-cl-pager__meta";
      paginator.insertBefore(meta, paginator.firstChild);
    }
    meta.innerHTML =
      '<span class="ts-cl-pager__range">' +
      (total === 0 ? "0 položek" : start + "–" + end + " z " + total) +
      "</span>";

    var info = paginator.querySelector(".paginator-info");
    if (info) info.setAttribute("hidden", "hidden");
  }

  function bindDocClicks() {
    if (document.documentElement.dataset.tsCenikChipsBound === "1") return;
    document.documentElement.dataset.tsCenikChipsBound = "1";
    document.addEventListener("click", function () {
      closeChipMenus(null);
    });
  }

  function markReady() {
    if (!document.body) return;
    document.body.classList.add("ts-cenik-ready", "ts-cl-ready");
  }

  function isTreneriSummary() {
    return document.body && document.body.classList.contains("model-treneri");
  }

  function enhance() {
    if (!isChangeList()) return;

    polishPageHead();

    var changelist = document.getElementById("changelist");
    var form = document.getElementById("changelist-form");
    if (!changelist || !form) {
      markReady();
      return;
    }

    var container =
      changelist.querySelector(".changelist-form-container") || changelist;
    container.classList.add("cenik-layout", "ts-cl-layout");

    enhanceToolbar(container);

    if (isTreneriSummary()) {
      /* Filtry Od/Do jsou už v HTML (.ts-cl-filters) – nestavět Django chip bar */
      var searchInput =
        container.querySelector("#changelist-search #searchbar") ||
        container.querySelector('#changelist-search input[type="text"]');
      if (searchInput && !searchInput.getAttribute("placeholder")) {
        searchInput.setAttribute("placeholder", "Hledat v trenéři…");
      }
      var tools =
        document.querySelector("#content > .ts-page-head .object-tools") ||
        document.querySelector("#content-main > .object-tools");
      if (tools) placeTools(tools, null);
    } else {
      buildFilterBar(changelist, container);
      ensureTableCols();
      enhancePaginator();
    }
    bindDocClicks();
  }

  function boot() {
    if (!isChangeList()) return;
    enhance();
    window.requestAnimationFrame(function () {
      enhance();
      markReady();
    });
    window.setTimeout(function () {
      enhance();
      markReady();
    }, 80);
    document.addEventListener("ts:changelist-search", function () {
      window.setTimeout(function () {
        enhance();
        markReady();
      }, 0);
    });
    document.addEventListener("ts:changelist-load-more", function () {
      enhancePaginator();
    });
    if (!document.documentElement.dataset.tsCenikMqBound) {
      document.documentElement.dataset.tsCenikMqBound = "1";
      var mq = window.matchMedia("(max-width: 860px)");
      var onMq = function () {
        window.setTimeout(function () {
          enhance();
          markReady();
        }, 0);
      };
      if (mq.addEventListener) mq.addEventListener("change", onMq);
      else if (mq.addListener) mq.addListener(onMq);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
