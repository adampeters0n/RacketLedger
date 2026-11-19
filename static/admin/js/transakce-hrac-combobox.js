(function () {
  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  function destroySelect2(select) {
    if (!(window.django && django.jQuery)) return;
    var $ = django.jQuery;
    var $sel = $(select);
    if ($sel.data("select2")) {
      try {
        $sel.select2("destroy");
      } catch (e) {}
    }
    // Select2 sometimes leaves a sibling container
    var wrap = select.closest(".related-widget-wrapper") || select.parentElement;
    if (wrap) {
      wrap.querySelectorAll(".select2-container").forEach(function (el) {
        el.remove();
      });
    }
  }

  function initCombobox(select) {
    if (!select || select.dataset.tsCombobox === "1") return;
    select.dataset.tsCombobox = "1";

    destroySelect2(select);

    var wrapper = select.closest(".related-widget-wrapper") || select.parentElement;
    wrapper.classList.add("ts-hrac-combo-wrap");

    select.classList.add("ts-hrac-combo-native");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");
    select.style.display = "none";

    // Kdyby Select2 znovu naběhl později, znovu ho zruš
    var mo = new MutationObserver(function () {
      destroySelect2(select);
      select.style.display = "none";
      wrapper.querySelectorAll(".select2-container").forEach(function (el) {
        el.style.display = "none";
      });
    });
    mo.observe(wrapper, { childList: true, subtree: true });

    var box = document.createElement("div");
    box.className = "ts-hrac-combo";

    var input = document.createElement("input");
    input.type = "text";
    input.className = "ts-hrac-combo__input";
    input.setAttribute("autocomplete", "off");
    input.setAttribute("spellcheck", "false");
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    input.placeholder = "Vyhledat hráče…";
    if (select.required) {
      input.required = true;
      select.required = false;
    }

    var list = document.createElement("ul");
    list.className = "ts-hrac-combo__list";
    list.setAttribute("role", "listbox");
    list.hidden = true;

    box.appendChild(input);
    box.appendChild(list);
    wrapper.insertBefore(box, select);

    var ajaxUrl = select.getAttribute("data-ajax--url") || "/admin/autocomplete/";
    var appLabel = select.getAttribute("data-app-label") || "core";
    var modelName = select.getAttribute("data-model-name") || "transakce";
    var fieldName = select.getAttribute("data-field-name") || "hrac";
    var activeIndex = -1;
    var debounceTimer = null;
    var reqId = 0;

    function selectedLabel() {
      var opt = select.options[select.selectedIndex];
      return opt && opt.value ? (opt.textContent || "").trim() : "";
    }

    function syncFromSelect() {
      input.value = selectedLabel();
    }

    function closeList() {
      list.hidden = true;
      list.innerHTML = "";
      activeIndex = -1;
      input.setAttribute("aria-expanded", "false");
      box.classList.remove("is-open");
    }

    function setActive(idx) {
      var items = list.querySelectorAll(".ts-hrac-combo__option");
      items.forEach(function (el, i) {
        el.classList.toggle("is-active", i === idx);
      });
      activeIndex = idx;
      if (idx >= 0 && items[idx]) items[idx].scrollIntoView({ block: "nearest" });
    }

    function choose(id, label) {
      select.innerHTML = "";
      var opt = document.createElement("option");
      opt.value = String(id);
      opt.textContent = label;
      opt.selected = true;
      select.appendChild(opt);
      input.value = label;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      if (window.django && django.jQuery) django.jQuery(select).trigger("change");
      closeList();
    }

    function renderResults(results) {
      list.innerHTML = "";
      if (!results.length) {
        var empty = document.createElement("li");
        empty.className = "ts-hrac-combo__empty";
        empty.textContent = "Žádný hráč";
        list.appendChild(empty);
      } else {
        results.forEach(function (row, i) {
          var li = document.createElement("li");
          li.className = "ts-hrac-combo__option" + (i === 0 ? " is-active" : "");
          li.setAttribute("role", "option");
          li.setAttribute("data-id", row.id);
          li.textContent = row.text;
          li.addEventListener("mousedown", function (e) {
            e.preventDefault();
            choose(row.id, row.text);
          });
          list.appendChild(li);
        });
        activeIndex = results.length ? 0 : -1;
      }
      list.hidden = false;
      box.classList.add("is-open");
      input.setAttribute("aria-expanded", "true");
    }

    function fetchResults(term) {
      var myReq = ++reqId;
      var url = new URL(ajaxUrl, window.location.origin);
      url.searchParams.set("term", term || "");
      url.searchParams.set("app_label", appLabel);
      url.searchParams.set("model_name", modelName);
      url.searchParams.set("field_name", fieldName);

      fetch(url.toString(), {
        credentials: "same-origin",
        headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
      })
        .then(function (r) {
          return r.json();
        })
        .then(function (data) {
          if (myReq !== reqId) return;
          var results = (data && data.results) || [];
          renderResults(
            results.map(function (r) {
              return { id: r.id, text: r.text };
            })
          );
        })
        .catch(function () {
          if (myReq !== reqId) return;
          renderResults([]);
        });
    }

    function scheduleSearch(term) {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function () {
        fetchResults(term);
      }, 160);
    }

    input.addEventListener("focus", function () {
      scheduleSearch(input.value.trim());
    });

    input.addEventListener("input", function () {
      if (select.value && input.value !== selectedLabel()) {
        select.value = "";
        while (select.options.length) select.remove(0);
        select.dispatchEvent(new Event("change", { bubbles: true }));
      }
      scheduleSearch(input.value.trim());
    });

    input.addEventListener("keydown", function (e) {
      var items = list.querySelectorAll(".ts-hrac-combo__option");
      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (list.hidden) scheduleSearch(input.value.trim());
        else setActive(Math.min(activeIndex + 1, items.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive(Math.max(activeIndex - 1, 0));
      } else if (e.key === "Enter") {
        if (!list.hidden && activeIndex >= 0 && items[activeIndex]) {
          e.preventDefault();
          var el = items[activeIndex];
          choose(el.getAttribute("data-id"), el.textContent);
        }
      } else if (e.key === "Escape") {
        closeList();
        input.blur();
      }
    });

    input.addEventListener("blur", function () {
      setTimeout(function () {
        closeList();
        if (select.value) syncFromSelect();
      }, 140);
    });

    syncFromSelect();
  }

  function boot() {
    document
      .querySelectorAll("body.model-transakce #id_hrac.admin-autocomplete")
      .forEach(initCombobox);
  }

  ready(function () {
    setTimeout(boot, 0);
    setTimeout(boot, 150);
  });
})();
