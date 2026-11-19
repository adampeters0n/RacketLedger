(function (global) {
  "use strict";

  var POPOVER_WIDTH = 220;
  var HOURS = [];
  var MINUTES = [];
  for (var h = 0; h < 24; h++) HOURS.push(h);
  for (var m = 0; m < 60; m++) MINUTES.push(m);

  var PICKER_INNER =
    '<button type="button" class="ts-time-trigger" data-ts-time-trigger aria-haspopup="dialog" aria-expanded="false">' +
    '<svg class="ts-time-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>' +
    '<span class="ts-time-label" data-ts-time-label>—</span>' +
    '<svg class="ts-time-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>' +
    "</button>" +
    '<div class="ts-time-popover" data-ts-time-popover role="dialog" aria-label="Výběr času" hidden>' +
    '<div class="ts-time-cols">' +
    '<div class="ts-time-col">' +
    '<div class="ts-time-col-title">Hodiny</div>' +
    '<div class="ts-time-list" data-ts-time-hours></div>' +
    "</div>" +
    '<div class="ts-time-col">' +
    '<div class="ts-time-col-title">Minuty</div>' +
    '<div class="ts-time-list" data-ts-time-minutes></div>' +
    "</div>" +
    "</div></div>";

  function pad2(n) {
    return String(n).padStart(2, "0");
  }

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

  function parseTime(raw) {
    var s = String(raw || "").trim();
    var m = /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(s);
    if (m) {
      var hh = parseInt(m[1], 10);
      var mm = parseInt(m[2], 10);
      var ss = m[3] != null ? parseInt(m[3], 10) : 0;
      if (hh >= 0 && hh <= 23 && mm >= 0 && mm <= 59 && ss >= 0 && ss <= 59) {
        return { hour: hh, minute: mm, second: ss, withSeconds: m[3] != null };
      }
    }
    m = /^(\d{1,2})$/.exec(s);
    if (m) {
      var h2 = parseInt(m[1], 10);
      if (h2 >= 0 && h2 <= 23) {
        return { hour: h2, minute: 0, second: 0, withSeconds: false };
      }
    }
    return null;
  }

  function formatValue(h, m, withSeconds, s) {
    var base = pad2(h) + ":" + pad2(m);
    if (!withSeconds) return base;
    return base + ":" + pad2(typeof s === "number" ? s : 0);
  }

  function formatLabel(h, m) {
    return pad2(h) + ":" + pad2(m);
  }

  function init(root, opts) {
    if (!root || root.__tsTimePicker) return root.__tsTimePicker || null;
    opts = opts || {};

    var trigger = root.querySelector("[data-ts-time-trigger]");
    var popover = root.querySelector("[data-ts-time-popover]");
    var labelEl = root.querySelector("[data-ts-time-label]");
    var hoursEl = root.querySelector("[data-ts-time-hours]");
    var minutesEl = root.querySelector("[data-ts-time-minutes]");
    var hidden = root.querySelector('input[data-ts-time-value], input.ts-time-value, input[type="hidden"]');
    if (!hidden) {
      hidden = root.querySelector('input[type="time"], input.vTimeField');
    }
    if (!trigger || !popover || !hidden || !hoursEl || !minutesEl) return null;

    var allowEmpty = root.getAttribute("data-allow-empty") === "1";
    var withSeconds = root.getAttribute("data-with-seconds") === "1";
    var selectedHour = 12;
    var selectedMinute = 0;
    var selectedSecond = 0;
    var isEmpty = false;
    var listsBuilt = false;

    function initFromHidden() {
      var p = parseTime(hidden.value || root.getAttribute("data-time") || "");
      if (!p) {
        var now = new Date();
        selectedHour = now.getHours();
        selectedMinute = now.getMinutes();
        selectedSecond = 0;
        isEmpty = allowEmpty;
        return;
      }
      selectedHour = p.hour;
      selectedMinute = p.minute;
      selectedSecond = p.second || 0;
      if (p.withSeconds) withSeconds = true;
      isEmpty = false;
    }

    function updateLabel() {
      if (!labelEl) return;
      if (isEmpty || !hidden.value) {
        labelEl.textContent = "Vyberte čas";
        labelEl.classList.add("is-placeholder");
      } else {
        labelEl.textContent = formatLabel(selectedHour, selectedMinute);
        labelEl.classList.remove("is-placeholder");
      }
    }

    function syncHidden() {
      if (isEmpty) {
        hidden.value = "";
      } else {
        hidden.value = formatValue(selectedHour, selectedMinute, withSeconds, selectedSecond);
      }
      updateLabel();
      try {
        hidden.dispatchEvent(new Event("change", { bubbles: true }));
        hidden.dispatchEvent(new Event("input", { bubbles: true }));
      } catch (err) {}
      root.dispatchEvent(
        new CustomEvent("ts-time-change", {
          detail: { hour: selectedHour, minute: selectedMinute, value: hidden.value },
          bubbles: true,
        })
      );
    }

    function markSelected() {
      var hourBtns = hoursEl.querySelectorAll(".ts-time-opt");
      for (var i = 0; i < hourBtns.length; i++) {
        hourBtns[i].classList.toggle(
          "is-selected",
          parseInt(hourBtns[i].getAttribute("data-value"), 10) === selectedHour
        );
      }
      var minBtns = minutesEl.querySelectorAll(".ts-time-opt");
      for (var j = 0; j < minBtns.length; j++) {
        minBtns[j].classList.toggle(
          "is-selected",
          parseInt(minBtns[j].getAttribute("data-value"), 10) === selectedMinute
        );
      }
    }

    function scrollSelectedIntoView() {
      var hSel = hoursEl.querySelector(".ts-time-opt.is-selected");
      var mSel = minutesEl.querySelector(".ts-time-opt.is-selected");
      if (hSel && hSel.scrollIntoView) {
        hSel.scrollIntoView({ block: "center", inline: "nearest" });
      }
      if (mSel && mSel.scrollIntoView) {
        mSel.scrollIntoView({ block: "center", inline: "nearest" });
      }
    }

    function buildLists() {
      if (listsBuilt) {
        markSelected();
        return;
      }
      hoursEl.innerHTML = "";
      minutesEl.innerHTML = "";
      HOURS.forEach(function (hour) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "ts-time-opt";
        btn.setAttribute("data-value", String(hour));
        btn.textContent = pad2(hour);
        btn.addEventListener("click", function () {
          selectedHour = hour;
          selectedSecond = 0;
          isEmpty = false;
          markSelected();
          syncHidden();
        });
        hoursEl.appendChild(btn);
      });
      MINUTES.forEach(function (minute) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "ts-time-opt";
        btn.setAttribute("data-value", String(minute));
        btn.textContent = pad2(minute);
        btn.addEventListener("click", function () {
          selectedMinute = minute;
          selectedSecond = 0;
          isEmpty = false;
          markSelected();
          syncHidden();
          closePopover();
        });
        minutesEl.appendChild(btn);
      });
      listsBuilt = true;
      markSelected();
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
      popover.style.top = rect.bottom + 8 + "px";
      popover.style.bottom = "auto";
      var popH = popover.offsetHeight || 260;
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
      popover.hidden = false;
      trigger.setAttribute("aria-expanded", "true");
      root.classList.add("is-open");
      buildLists();
      positionPopover();
      scrollSelectedIntoView();
      window.addEventListener("scroll", onViewportChange, true);
      window.addEventListener("resize", onViewportChange);
    }

    trigger.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (popover.hidden) openPopover();
      else closePopover();
    });

    document.addEventListener("click", function (e) {
      if (!root.contains(e.target)) closePopover();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !popover.hidden) closePopover();
    });

    initFromHidden();
    if (!isEmpty) {
      hidden.value = formatValue(selectedHour, selectedMinute, withSeconds, selectedSecond);
    } else {
      hidden.value = "";
    }
    updateLabel();

    var api = {
      close: closePopover,
      getValue: function () {
        return hidden.value;
      },
      setValue: function (raw) {
        var p = parseTime(raw);
        if (!p) {
          if (allowEmpty) {
            isEmpty = true;
            hidden.value = "";
            updateLabel();
          }
          return;
        }
        selectedHour = p.hour;
        selectedMinute = p.minute;
        selectedSecond = p.second || 0;
        if (p.withSeconds) withSeconds = true;
        isEmpty = false;
        hidden.value = formatValue(selectedHour, selectedMinute, withSeconds, selectedSecond);
        updateLabel();
        if (listsBuilt) markSelected();
      },
    };
    root.__tsTimePicker = api;
    hidden.__tsTimePicker = api;
    return api;
  }

  function initAll(selector, opts) {
    var nodes = document.querySelectorAll(selector || "[data-ts-time-picker]");
    var list = [];
    for (var i = 0; i < nodes.length; i++) {
      var api = init(nodes[i], opts);
      if (api) list.push(api);
    }
    return list;
  }

  function shouldEnhance(input) {
    if (!input || input.dataset.tsTimeEnhanced === "1") return false;
    if (input.disabled || input.readOnly) return false;
    if (input.closest("[data-ts-time-picker]")) return false;
    if (input.hasAttribute("data-ts-time-skip")) return false;
    if (input.type === "hidden" && !input.classList.contains("vTimeField")) return false;
    return true;
  }

  function enhanceInput(input) {
    if (!shouldEnhance(input)) return null;

    var parsed = parseTime(input.value);
    var withSeconds =
      parsed && parsed.withSeconds
        ? true
        : /:\d{2}:\d{2}\s*$/.test(String(input.value || ""));

    input.dataset.tsTimeEnhanced = "1";

    var root = document.createElement("div");
    root.className = "ts-time-picker ts-time-picker--enhanced";
    root.setAttribute("data-ts-time-picker", "");
    if (parsed) {
      root.setAttribute(
        "data-time",
        formatValue(parsed.hour, parsed.minute, withSeconds, parsed.second || 0)
      );
    }
    if (!parsed) root.setAttribute("data-allow-empty", "1");
    if (withSeconds) root.setAttribute("data-with-seconds", "1");

    root.innerHTML = PICKER_INNER;

    var wasType = input.type;
    input.type = "hidden";
    input.classList.add("ts-time-value", "vTimeField");
    input.setAttribute("data-ts-time-value", "");
    if (parsed) {
      input.value = formatValue(parsed.hour, parsed.minute, withSeconds, parsed.second || 0);
    } else if (wasType === "time" && !input.value) {
      input.value = "";
    }

    // Hide related datalist if present
    var listId = input.getAttribute("list");
    if (listId) {
      var dl = document.getElementById(listId);
      if (dl) dl.hidden = true;
      input.removeAttribute("list");
    }

    var parent = input.parentNode;
    parent.insertBefore(root, input);
    var popover = root.querySelector("[data-ts-time-popover]");
    root.insertBefore(input, popover);

    return init(root);
  }

  function enhanceInputs(scope) {
    var root = scope || document;
    var list = [];
    var nodes = root.querySelectorAll(
      'input[type="time"]:not([data-ts-time-skip]), input.vTimeField:not([data-ts-time-skip]), input.add-day-time-input:not([data-ts-time-skip])'
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

  global.TsTimePicker = {
    init: init,
    initAll: initAll,
    enhanceInput: enhanceInput,
    enhanceInputs: enhanceInputs,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  document.addEventListener("formset:added", function (ev) {
    var row =
      (ev.target && ev.target.nodeType === 1 ? ev.target : null) ||
      (ev.detail && ev.detail.formsetElement) ||
      null;
    enhanceInputs(row || document);
  });

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
            n.matches &&
            (n.matches('input[type="time"], input.vTimeField, input.add-day-time-input') ||
              n.querySelector('input[type="time"], input.vTimeField, input.add-day-time-input'))
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
