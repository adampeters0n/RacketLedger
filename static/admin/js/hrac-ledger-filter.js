document.addEventListener("DOMContentLoaded", function () {
  var root = document.getElementById("hrac-ledger-filter") || document.querySelector(".ledger-filter");
  if (!root) return;

  var requestSeq = 0;

  function fieldValue(name) {
    var el =
      root.querySelector('input[name="' + name + '"]') ||
      root.querySelector('.ts-date-value[name="' + name + '"]');
    return el && el.value ? String(el.value).trim() : "";
  }

  function buildUrl() {
    var fromVal = fieldValue("from");
    var toVal = fieldValue("to");
    var params = new URLSearchParams();
    if (fromVal) params.append("from", fromVal);
    if (toVal) params.append("to", toVal);
    var qs = params.toString();
    return window.location.pathname + (qs ? "?" + qs : "");
  }

  function currentUrl() {
    return window.location.pathname + (window.location.search || "");
  }

  function replaceNode(oldNode, newNode) {
    if (!oldNode || !newNode) return null;
    var clone = newNode.cloneNode(true);
    oldNode.replaceWith(clone);
    return clone;
  }

  function updateLedgerFromDoc(doc) {
    var table = document.getElementById("hrac-ledger-table") || document.querySelector(".ledger-card table.ledger");
    var newTable = doc.getElementById("hrac-ledger-table") || doc.querySelector(".ledger-card table.ledger");
    if (table && newTable) {
      var oldTbody = table.querySelector("tbody");
      var newTbody = newTable.querySelector("tbody");
      if (oldTbody && newTbody) replaceNode(oldTbody, newTbody);

      var oldTfoot = table.querySelector("tfoot");
      var newTfoot = newTable.querySelector("tfoot");
      if (oldTfoot && newTfoot) {
        replaceNode(oldTfoot, newTfoot);
      } else if (oldTfoot && !newTfoot) {
        oldTfoot.remove();
      } else if (!oldTfoot && newTfoot) {
        table.appendChild(newTfoot.cloneNode(true));
      }
    }

    var summary = document.getElementById("hrac-player-summary") || document.querySelector(".player-summary");
    var newSummary = doc.getElementById("hrac-player-summary") || doc.querySelector(".player-summary");
    if (summary && newSummary) {
      replaceNode(summary, newSummary);
    } else if (!summary && newSummary) {
      var card = document.querySelector(".ledger-card");
      if (card) card.after(newSummary.cloneNode(true));
    } else if (summary && !newSummary) {
      summary.remove();
    }
  }

  function setLoading(isLoading) {
    var table = document.getElementById("hrac-ledger-table") || document.querySelector(".ledger-card table.ledger");
    if (!table) return;
    table.classList.toggle("is-filtering", !!isLoading);
    table.setAttribute("aria-busy", isLoading ? "true" : "false");
  }

  function applyFilter() {
    var next = buildUrl();
    if (next === currentUrl()) return;

    var seq = ++requestSeq;
    var scrollY = window.scrollY;
    setLoading(true);

    fetch(next, {
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        Accept: "text/html",
      },
      credentials: "same-origin",
    })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.text();
      })
      .then(function (html) {
        if (seq !== requestSeq) return;
        var doc = new DOMParser().parseFromString(html, "text/html");
        updateLedgerFromDoc(doc);
        history.pushState({ hracLedgerFilter: true }, "", next);
        window.scrollTo(0, scrollY);
      })
      .catch(function () {
        if (seq !== requestSeq) return;
        window.location.href = next;
      })
      .finally(function () {
        if (seq === requestSeq) setLoading(false);
      });
  }

  var timer = null;
  function scheduleApply() {
    clearTimeout(timer);
    timer = setTimeout(applyFilter, 120);
  }

  function setPickerValue(picker, iso) {
    if (!picker) return;
    var api = picker.__tsDatePicker;
    var hidden = picker.querySelector(".ts-date-value, input[data-ts-date-value]");
    var label = picker.querySelector("[data-ts-date-label]");
    var value = iso ? String(iso).trim() : "";
    if (api && typeof api.setValue === "function") {
      api.setValue(value);
    }
    if (hidden) hidden.value = value;
    picker.setAttribute("data-datum", value);
    if (!value && label) {
      label.textContent = "Vyberte datum";
      label.classList.add("is-placeholder");
    }
  }

  function todayIso() {
    var resetBtn = document.getElementById("hrac-ledger-reset") || root.querySelector(".ledger-filter__reset");
    if (resetBtn && resetBtn.getAttribute("data-today")) {
      return resetBtn.getAttribute("data-today");
    }
    var d = new Date();
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return d.getFullYear() + "-" + m + "-" + day;
  }

  var resetBtn = document.getElementById("hrac-ledger-reset") || root.querySelector(".ledger-filter__reset");

  function syncResetVisibility() {
    if (!resetBtn) return;
    var hasFrom = !!fieldValue("from");
    resetBtn.hidden = !hasFrom;
    resetBtn.setAttribute("aria-hidden", hasFrom ? "false" : "true");
    resetBtn.classList.toggle("is-visible", hasFrom);
  }

  function resetPeriod() {
    var pickers = root.querySelectorAll("[data-ts-date-picker]");
    var fromPicker = root.querySelector('[data-ts-date-picker] .ts-date-value[name="from"]');
    var toPicker = root.querySelector('[data-ts-date-picker] .ts-date-value[name="to"]');
    setPickerValue(fromPicker && fromPicker.closest("[data-ts-date-picker]"), "");
    setPickerValue(toPicker && toPicker.closest("[data-ts-date-picker]"), todayIso());
    // pokud nejsou name match, fallback: 1. prázdný, 2. dnes
    if (!fromPicker && !toPicker && pickers.length >= 2) {
      setPickerValue(pickers[0], "");
      setPickerValue(pickers[1], todayIso());
    }
    syncResetVisibility();
    scheduleApply();
  }

  if (resetBtn) {
    resetBtn.addEventListener("click", function (e) {
      e.preventDefault();
      resetPeriod();
    });
  }

  root.querySelectorAll("[data-ts-date-picker]").forEach(function (picker) {
    picker.addEventListener("ts-date-change", function () {
      syncResetVisibility();
      scheduleApply();
    });
  });

  root.addEventListener("change", function (e) {
    if (!e.target) return;
    if (
      e.target.matches(".ts-date-value") ||
      e.target.matches('input[name="from"]') ||
      e.target.matches('input[name="to"]')
    ) {
      syncResetVisibility();
      scheduleApply();
    }
  });

  syncResetVisibility();

  window.addEventListener("popstate", function () {
    // Back/forward: soft refresh of ledger only
    var seq = ++requestSeq;
    var scrollY = window.scrollY;
    setLoading(true);
    fetch(currentUrl(), {
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        Accept: "text/html",
      },
      credentials: "same-origin",
    })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.text();
      })
      .then(function (html) {
        if (seq !== requestSeq) return;
        var doc = new DOMParser().parseFromString(html, "text/html");
        updateLedgerFromDoc(doc);
        // sync date picker hidden inputs from URL if present
        var params = new URLSearchParams(window.location.search);
        ["from", "to"].forEach(function (name) {
          var input = root.querySelector('.ts-date-value[name="' + name + '"]');
          if (!input) return;
          var val = params.get(name) || "";
          if (name === "to" && !val) val = todayIso();
          if (input.value !== val) {
            var picker = input.closest("[data-ts-date-picker]");
            setPickerValue(picker, val);
          }
        });
        syncResetVisibility();
        window.scrollTo(0, scrollY);
      })
      .catch(function () {
        window.location.reload();
      })
      .finally(function () {
        if (seq === requestSeq) setLoading(false);
      });
  });
});
