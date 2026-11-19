(function (global) {
  "use strict";

  var MONTHS_LONG = [
    "Leden", "Únor", "Březen", "Duben", "Květen", "Červen",
    "Červenec", "Srpen", "Září", "Říjen", "Listopad", "Prosinec",
  ];

  /** Sdílené s ts-time-picker: najednou smí být otevřený jen jeden picker. */
  var POPOVER_WIDTH = 268;

  function claimOpen(closeFn) {
    if (global.__tsActivePickerClose && global.__tsActivePickerClose !== closeFn) {
      try {
        global.__tsActivePickerClose();
      } catch (err) {}
    }
    global.__tsActivePickerClose = closeFn;
  }

  function releaseOpen(closeFn) {
    if (global.__tsActivePickerClose === closeFn) {
      global.__tsActivePickerClose = null;
    }
  }

  var PICKER_INNER =
    '<button type="button" class="ts-date-trigger" data-ts-date-trigger aria-haspopup="dialog" aria-expanded="false">' +
    '<svg class="ts-date-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>' +
    '<span class="ts-date-label" data-ts-date-label>—</span>' +
    '<svg class="ts-date-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>' +
    "</button>" +
    '<div class="ts-date-popover" data-ts-date-popover role="dialog" aria-label="Výběr data" hidden>' +
    '<div class="ts-date-cal-header">' +
    '<button type="button" class="ts-date-cal-nav" data-cal-prev aria-label="Předchozí měsíc">‹</button>' +
    '<button type="button" class="ts-date-cal-title" data-ts-date-title>—</button>' +
    '<button type="button" class="ts-date-cal-nav" data-cal-next aria-label="Další měsíc">›</button>' +
    "</div>" +
    '<div class="ts-date-cal-weekdays" aria-hidden="true">' +
    "<span>Po</span><span>Út</span><span>St</span><span>Čt</span><span>Pá</span><span>So</span><span>Ne</span>" +
    "</div>" +
    '<div class="ts-date-cal-days" data-ts-date-days></div>' +
    "</div>";

  function pad2(n) {
    return String(n).padStart(2, "0");
  }

  function parseDatum(val) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(val || "");
    if (!m) return null;
    return {
      year: parseInt(m[1], 10),
      month: parseInt(m[2], 10),
      day: parseInt(m[3], 10),
    };
  }

  function datumValue(y, m, d) {
    return y + "-" + pad2(m) + "-" + pad2(d);
  }

  function formatLabel(y, m, d) {
    return d + ". " + MONTHS_LONG[m - 1].toLowerCase() + " " + y;
  }

  function parseManualDate(raw) {
    var s = (raw || "").trim();
    var m = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(s);
    if (m) {
      return {
        day: parseInt(m[1], 10),
        month: parseInt(m[2], 10),
        year: parseInt(m[3], 10),
      };
    }
    m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(s);
    if (m) {
      return {
        year: parseInt(m[1], 10),
        month: parseInt(m[2], 10),
        day: parseInt(m[3], 10),
      };
    }
    return null;
  }

  function toIso(raw) {
    var p = parseDatum(raw) || parseManualDate(raw);
    if (!p) return "";
    var dt = new Date(p.year, p.month - 1, p.day);
    if (dt.getFullYear() !== p.year || dt.getMonth() + 1 !== p.month || dt.getDate() !== p.day) {
      return "";
    }
    return datumValue(p.year, p.month, p.day);
  }

  function init(root, opts) {
    if (!root || root.__tsDatePicker) return root.__tsDatePicker || null;
    opts = opts || {};

    var trigger = root.querySelector("[data-ts-date-trigger]");
    var popover = root.querySelector("[data-ts-date-popover]");
    var labelEl = root.querySelector("[data-ts-date-label]");
    var titleEl = root.querySelector("[data-ts-date-title]");
    var daysEl = root.querySelector("[data-ts-date-days]");
    var weekdaysEl = popover.querySelector(".ts-date-cal-weekdays");
    var prevBtn = popover.querySelector("[data-cal-prev]");
    var nextBtn = popover.querySelector("[data-cal-next]");
    var hidden = root.querySelector('input[data-ts-date-value], input.ts-date-value, input[type="hidden"]');
    if (!hidden) {
      hidden = root.querySelector('input[type="date"], input.vDateField');
    }
    var manualInput = root.querySelector("[data-ts-date-manual]");
    var manualBtn = root.querySelector("[data-ts-date-manual-btn]");
    if (!trigger || !popover || !hidden || !daysEl) return null;

    var today = new Date();
    var yearMin = parseInt(root.getAttribute("data-year-min") || "2020", 10);
    var yearMax = parseInt(
      root.getAttribute("data-year-max") || String(today.getFullYear() + 2),
      10
    );
    var allowFuture = root.getAttribute("data-allow-future") !== "0";
    var allowEmpty = root.getAttribute("data-allow-empty") === "1";
    var submitForm = root.hasAttribute("data-submit-form");
    var navigateBase = root.getAttribute("data-navigate") || opts.navigate || "";

    var viewYear;
    var viewMonth;
    var selectedYear;
    var selectedMonth;
    var selectedDay;
    var yearPickMode = false;
    var isEmpty = false;

    function initFromHidden() {
      var raw = hidden.value || root.getAttribute("data-datum") || "";
      var p = parseDatum(toIso(raw) || raw) || parseManualDate(raw);
      if (!p) {
        selectedYear = today.getFullYear();
        selectedMonth = today.getMonth() + 1;
        selectedDay = today.getDate();
        isEmpty = allowEmpty;
        return;
      }
      selectedYear = p.year;
      selectedMonth = p.month;
      selectedDay = p.day;
      isEmpty = false;
      viewYear = p.year;
      viewMonth = p.month;
    }

    function formatLabelFor(y, m, d) {
      if (root.getAttribute("data-label-format") === "numeric") {
        return pad2(d) + "." + pad2(m) + "." + y;
      }
      return formatLabel(y, m, d);
    }

    function updateLabel() {
      if (!labelEl) return;
      if (isEmpty || !hidden.value) {
        labelEl.textContent = "Vyberte datum";
        labelEl.classList.add("is-placeholder");
      } else {
        labelEl.textContent = formatLabelFor(selectedYear, selectedMonth, selectedDay);
        labelEl.classList.remove("is-placeholder");
      }
    }

    function positionPopover() {
      if (popover.hidden) return;
      var rect = trigger.getBoundingClientRect();
      var width = Math.min(POPOVER_WIDTH, window.innerWidth - 24);
      var left = rect.left;
      if (left + width > window.innerWidth - 12) {
        left = Math.max(12, window.innerWidth - width - 12);
      }
      if (left < 12) left = 12;

      popover.style.position = "fixed";
      popover.style.width = width + "px";
      popover.style.minWidth = width + "px";
      popover.style.maxWidth = width + "px";
      popover.style.left = left + "px";
      popover.style.right = "auto";
      popover.style.zIndex = "10060";

      // Nejdřív pod trigger; když se nevejde, nad něj
      popover.style.top = rect.bottom + 8 + "px";
      popover.style.bottom = "auto";
      var popH = popover.offsetHeight || 360;
      if (rect.bottom + 8 + popH > window.innerHeight - 8 && rect.top - 8 - popH > 8) {
        popover.style.top = Math.max(8, rect.top - 8 - popH) + "px";
      }
    }

    function onViewportChange() {
      positionPopover();
    }

    function closePopover() {
      if (popover.hidden && global.__tsActivePickerClose !== closePopover) return;
      popover.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
      root.classList.remove("is-open");
      yearPickMode = false;
      popover.style.position = "";
      popover.style.top = "";
      popover.style.left = "";
      popover.style.right = "";
      popover.style.bottom = "";
      popover.style.width = "";
      popover.style.minWidth = "";
      popover.style.maxWidth = "";
      popover.style.zIndex = "";
      window.removeEventListener("scroll", onViewportChange, true);
      window.removeEventListener("resize", onViewportChange);
      releaseOpen(closePopover);
    }

    function openPopover() {
      claimOpen(closePopover);
      viewYear = selectedYear;
      viewMonth = selectedMonth;
      yearPickMode = false;
      popover.hidden = false;
      trigger.setAttribute("aria-expanded", "true");
      root.classList.add("is-open");
      render();
      positionPopover();
      window.addEventListener("scroll", onViewportChange, true);
      window.addEventListener("resize", onViewportChange);
    }

    function applySelection(y, m, d) {
      var dt = new Date(y, m - 1, d);
      if (!allowFuture) {
        var now = new Date();
        now.setHours(23, 59, 59, 999);
        if (dt > now) {
          y = today.getFullYear();
          m = today.getMonth() + 1;
          d = today.getDate();
        }
      }
      selectedYear = y;
      selectedMonth = m;
      selectedDay = d;
      isEmpty = false;
      hidden.value = datumValue(y, m, d);
      updateLabel();
      closePopover();

      try {
        hidden.dispatchEvent(new Event("change", { bubbles: true }));
        hidden.dispatchEvent(new Event("input", { bubbles: true }));
      } catch (err) {}

      var detail = { year: y, month: m, day: d, value: hidden.value };
      root.dispatchEvent(new CustomEvent("ts-date-change", { detail: detail, bubbles: true }));

      if (typeof opts.onSelect === "function") {
        opts.onSelect(detail);
        return;
      }
      if (navigateBase) {
        var href;
        if (navigateBase.indexOf("{date}") !== -1) {
          href = navigateBase.split("{date}").join(encodeURIComponent(hidden.value));
        } else if (/=$/.test(navigateBase)) {
          href = navigateBase + encodeURIComponent(hidden.value);
        } else {
          href =
            navigateBase +
            (navigateBase.indexOf("?") >= 0 ? "&" : "?") +
            "datum=" +
            encodeURIComponent(hidden.value);
        }
        window.location.href = href;
        return;
      }
      if (submitForm) {
        var form = root.closest("form");
        if (form) form.submit();
      }
    }

    function setYearModeUi(on) {
      popover.classList.toggle("is-year-mode", !!on);
      daysEl.classList.toggle("is-year-mode", !!on);
      if (weekdaysEl) weekdaysEl.hidden = !!on;
      if (prevBtn) prevBtn.hidden = !!on;
      if (nextBtn) nextBtn.hidden = !!on;
    }

    function renderYearGrid() {
      daysEl.innerHTML = "";
      setYearModeUi(true);
      if (titleEl) titleEl.textContent = "Vyberte rok";
      var grid = document.createElement("div");
      grid.className = "ts-date-cal-year-grid";
      for (var y = yearMax; y >= yearMin; y--) {
        (function (year) {
          var btn = document.createElement("button");
          btn.type = "button";
          btn.className = "ts-date-cal-year-btn" + (year === viewYear ? " is-selected" : "");
          btn.textContent = String(year);
          btn.addEventListener("click", function () {
            viewYear = year;
            yearPickMode = false;
            render();
            positionPopover();
          });
          grid.appendChild(btn);
        })(y);
      }
      daysEl.appendChild(grid);
    }

    function renderDays() {
      daysEl.innerHTML = "";
      setYearModeUi(false);
      if (titleEl) titleEl.textContent = MONTHS_LONG[viewMonth - 1] + " " + viewYear;

      var first = new Date(viewYear, viewMonth - 1, 1);
      var startDow = (first.getDay() + 6) % 7;
      var daysInMonth = new Date(viewYear, viewMonth, 0).getDate();
      var prevDays = new Date(viewYear, viewMonth - 1, 0).getDate();
      // Vždy 6 týdnů (= 42 buněk) → stejná výška kalendáře u všech měsíců
      var totalCells = 42;

      for (var i = 0; i < totalCells; i++) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "ts-date-cal-day";

        var y = viewYear;
        var m = viewMonth;
        var d;

        if (i < startDow) {
          d = prevDays - startDow + i + 1;
          m = viewMonth - 1;
          if (m < 1) {
            m = 12;
            y -= 1;
          }
          btn.classList.add("is-other");
        } else if (i >= startDow + daysInMonth) {
          d = i - startDow - daysInMonth + 1;
          m = viewMonth + 1;
          if (m > 12) {
            m = 1;
            y += 1;
          }
          btn.classList.add("is-other");
        } else {
          d = i - startDow + 1;
        }

        btn.textContent = String(d);

        if (y < yearMin || y > yearMax) btn.disabled = true;

        if (y === today.getFullYear() && m === today.getMonth() + 1 && d === today.getDate()) {
          btn.classList.add("is-today");
        }
        if (!isEmpty && y === selectedYear && m === selectedMonth && d === selectedDay) {
          btn.classList.add("is-selected");
        }

        (function (yy, mm, dd) {
          btn.addEventListener("click", function () {
            if (yy < yearMin || yy > yearMax) return;
            applySelection(yy, mm, dd);
          });
        })(y, m, d);

        daysEl.appendChild(btn);
      }
    }

    function render() {
      if (yearPickMode) renderYearGrid();
      else renderDays();
    }

    function applyManualDate() {
      var p = parseManualDate(manualInput && manualInput.value);
      if (!p || p.month < 1 || p.month > 12 || p.day < 1 || p.day > 31) return;
      if (p.year < yearMin || p.year > yearMax) return;
      var dt = new Date(p.year, p.month - 1, p.day);
      if (dt.getFullYear() !== p.year || dt.getMonth() + 1 !== p.month || dt.getDate() !== p.day) return;
      applySelection(p.year, p.month, p.day);
    }

    trigger.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (popover.hidden) openPopover();
      else closePopover();
    });

    if (titleEl) {
      titleEl.addEventListener("click", function (e) {
        e.preventDefault();
        yearPickMode = !yearPickMode;
        render();
        positionPopover();
      });
    }

    var todayBtn = popover.querySelector("[data-cal-today]");

    if (prevBtn) {
      prevBtn.addEventListener("click", function (e) {
        e.preventDefault();
        if (yearPickMode) return;
        viewMonth -= 1;
        if (viewMonth < 1) {
          viewMonth = 12;
          viewYear -= 1;
        }
        render();
        positionPopover();
      });
    }
    if (nextBtn) {
      nextBtn.addEventListener("click", function (e) {
        e.preventDefault();
        if (yearPickMode) return;
        viewMonth += 1;
        if (viewMonth > 12) {
          viewMonth = 1;
          viewYear += 1;
        }
        render();
        positionPopover();
      });
    }
    if (todayBtn) {
      todayBtn.addEventListener("click", function (e) {
        e.preventDefault();
        applySelection(today.getFullYear(), today.getMonth() + 1, today.getDate());
      });
    }
    if (manualBtn) {
      manualBtn.addEventListener("click", function (e) {
        e.preventDefault();
        applyManualDate();
      });
    }
    if (manualInput) {
      manualInput.addEventListener("keydown", function (e) {
        if (e.key === "Enter") {
          e.preventDefault();
          applyManualDate();
        }
      });
    }

    document.addEventListener("click", function (e) {
      if (!root.contains(e.target)) closePopover();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !popover.hidden) closePopover();
    });

    initFromHidden();
    viewYear = selectedYear;
    viewMonth = selectedMonth;
    if (!isEmpty) {
      hidden.value = datumValue(selectedYear, selectedMonth, selectedDay);
    } else {
      hidden.value = "";
    }
    updateLabel();

    var api = {
      close: closePopover,
      getValue: function () {
        return hidden.value;
      },
      setValue: function (iso) {
        var normalized = toIso(iso);
        if (!normalized) {
          if (allowEmpty) {
            isEmpty = true;
            hidden.value = "";
            updateLabel();
          }
          return;
        }
        var p = parseDatum(normalized);
        if (!p) return;
        selectedYear = p.year;
        selectedMonth = p.month;
        selectedDay = p.day;
        isEmpty = false;
        hidden.value = datumValue(p.year, p.month, p.day);
        updateLabel();
      },
    };
    root.__tsDatePicker = api;
    hidden.__tsDatePicker = api;
    return api;
  }

  function initAll(selector, opts) {
    var nodes = document.querySelectorAll(selector || "[data-ts-date-picker]");
    var list = [];
    for (var i = 0; i < nodes.length; i++) {
      var api = init(nodes[i], opts);
      if (api) list.push(api);
    }
    return list;
  }

  function shouldEnhance(input) {
    if (!input || input.dataset.tsDateEnhanced === "1") return false;
    if (input.disabled || input.readOnly) return false;
    if (input.closest("[data-ts-date-picker]")) return false;
    if (input.hasAttribute("data-ts-date-skip")) return false;
    if (input.type === "hidden" && !input.classList.contains("vDateField")) return false;
    return true;
  }

  function hideAdminDateShortcuts(input) {
    var parent = input.parentElement;
    if (!parent) return;
    var shortcuts = parent.querySelector(".datetimeshortcuts");
    if (shortcuts) shortcuts.hidden = true;
    var siblings = parent.parentElement ? parent.parentElement.querySelectorAll(".datetimeshortcuts") : [];
    for (var i = 0; i < siblings.length; i++) {
      // Only hide shortcuts that belong to this date field row
      if (siblings[i].previousElementSibling === input || siblings[i].parentElement === parent) {
        siblings[i].hidden = true;
      }
    }
  }

  function enhanceInput(input) {
    if (!shouldEnhance(input)) return null;

    var iso = toIso(input.value);
    var onchangeAttr = (input.getAttribute("onchange") || "") + " " + (input.getAttribute("oninput") || "");
    var wantsSubmit = /(?:this\.)?form\.submit\s*\(|\.submit\s*\(/i.test(onchangeAttr);

    input.dataset.tsDateEnhanced = "1";
    hideAdminDateShortcuts(input);

    var root = document.createElement("div");
    root.className = "ts-date-picker ts-date-picker--enhanced";
    root.setAttribute("data-ts-date-picker", "");
    if (iso) root.setAttribute("data-datum", iso);
    root.setAttribute("data-year-min", "2020");
    root.setAttribute("data-year-max", String(new Date().getFullYear() + 10));
    root.setAttribute("data-allow-future", "1");
    if (!iso) root.setAttribute("data-allow-empty", "1");
    if (wantsSubmit) root.setAttribute("data-submit-form", "");

    root.innerHTML = PICKER_INNER;

    // Keep original field as the value carrier (same name/id for Django + JS).
    input.type = "hidden";
    input.classList.add("ts-date-value");
    input.setAttribute("data-ts-date-value", "");
    input.value = iso || "";
    input.removeAttribute("onchange");
    input.removeAttribute("oninput");

    var parent = input.parentNode;
    parent.insertBefore(root, input);
    // Put hidden input after trigger, before popover
    var popover = root.querySelector("[data-ts-date-popover]");
    root.insertBefore(input, popover);

    return init(root);
  }

  function enhanceInputs(scope) {
    var root = scope || document;
    var list = [];
    var nodes = root.querySelectorAll(
      'input[type="date"]:not([data-ts-date-skip]), input.vDateField:not([data-ts-date-skip])'
    );
    for (var i = 0; i < nodes.length; i++) {
      var api = enhanceInput(nodes[i]);
      if (api) list.push(api);
    }
    return list;
  }

  function boot() {
    initAll();
    enhanceInputs(document);
  }

  global.TsDatePicker = {
    init: init,
    initAll: initAll,
    enhanceInput: enhanceInput,
    enhanceInputs: enhanceInputs,
    toIso: toIso,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  document.addEventListener("formset:added", function (ev) {
    var row = (ev.target && ev.target.nodeType === 1 ? ev.target : null) || (ev.detail && ev.detail.formsetElement) || null;
    enhanceInputs(row || document);
  });

  // Dynamicky přidané modal / AJAX formuláře
  if (typeof MutationObserver !== "undefined") {
    var moTimer = null;
    var observer = new MutationObserver(function (mutations) {
      var needs = false;
      for (var i = 0; i < mutations.length; i++) {
        var nodes = mutations[i].addedNodes;
        for (var j = 0; j < nodes.length; j++) {
          var n = nodes[j];
          if (n.nodeType !== 1) continue;
          if (
            (n.matches && (n.matches('input[type="date"], input.vDateField') || n.querySelector('input[type="date"], input.vDateField')))
          ) {
            needs = true;
            break;
          }
        }
        if (needs) break;
      }
      if (!needs) return;
      if (moTimer) clearTimeout(moTimer);
      moTimer = setTimeout(function () {
        enhanceInputs(document);
      }, 40);
    });
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () {
        observer.observe(document.body, { childList: true, subtree: true });
      });
    } else if (document.body) {
      observer.observe(document.body, { childList: true, subtree: true });
    }
  }
})(window);
