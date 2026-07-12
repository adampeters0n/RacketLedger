(function () {
  var NEW_VALUE = "__new_typ__";

  function getConfig() {
    return document.getElementById("cenik-typ-config");
  }

  function getCsrfToken() {
    var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : "";
  }

  function ensureNewOption(select) {
    for (var i = 0; i < select.options.length; i++) {
      if (select.options[i].value === NEW_VALUE) return select.options[i];
    }
    var opt = document.createElement("option");
    opt.value = NEW_VALUE;
    opt.textContent = "— Nový typ tréninku —";
    select.appendChild(opt);
    return opt;
  }

  function initTypField() {
    var config = getConfig();
    var row = document.querySelector(".form-row.field-format");
    var select = document.getElementById("id_format");
    if (!row || !select || !config) return;

    var addUrl = config.dataset.formatAddUrl;
    if (!addUrl) return;

    ensureNewOption(select);

    var help = row.querySelector(".help");
    if (help) help.remove();

    var fieldCol = select.closest(".flex-container") || select.parentElement;
    if (!fieldCol || fieldCol.querySelector(".cenik-typ-wrap")) return;

    var wrap = document.createElement("div");
    wrap.className = "cenik-typ-wrap";
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);

    var createBox = document.createElement("div");
    createBox.className = "cenik-typ-create";
    createBox.hidden = true;
    createBox.innerHTML =
      '<label class="cenik-typ-create-label">Název nového typu</label>' +
      '<div class="cenik-typ-create-row">' +
      '  <input type="text" class="vTextField cenik-typ-create-input" maxlength="120" placeholder="např. Solo (1 hráč) - Člen">' +
      '  <button type="button" class="button default cenik-typ-create-save">Přidat</button>' +
      '  <button type="button" class="button secondary cenik-typ-create-cancel">Zrušit</button>' +
      "</div>" +
      '<p class="cenik-typ-create-error" hidden></p>';
    wrap.appendChild(createBox);

    var input = createBox.querySelector(".cenik-typ-create-input");
    var saveBtn = createBox.querySelector(".cenik-typ-create-save");
    var cancelBtn = createBox.querySelector(".cenik-typ-create-cancel");
    var errorEl = createBox.querySelector(".cenik-typ-create-error");
    var previousValue = select.value || "";

    function showError(msg) {
      if (msg) {
        errorEl.textContent = msg;
        errorEl.hidden = false;
      } else {
        errorEl.textContent = "";
        errorEl.hidden = true;
      }
    }

    function openCreate() {
      previousValue = select.value && select.value !== NEW_VALUE ? select.value : "";
      createBox.hidden = false;
      input.value = "";
      showError("");
      input.focus();
    }

    function closeCreate(restorePrevious) {
      createBox.hidden = true;
      showError("");
      input.value = "";
      if (restorePrevious) {
        select.value = previousValue;
      } else if (select.value === NEW_VALUE) {
        select.value = previousValue;
      }
    }

    select.addEventListener("change", function () {
      if (select.value === NEW_VALUE) {
        openCreate();
      } else {
        closeCreate(false);
      }
    });

    cancelBtn.addEventListener("click", function () {
      closeCreate(true);
    });

    function saveNewTyp() {
      var nazev = (input.value || "").trim();
      if (!nazev) {
        showError("Zadejte název.");
        return;
      }
      showError("");
      saveBtn.disabled = true;

      var body = new URLSearchParams();
      body.set("nazev", nazev);

      fetch(addUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "X-CSRFToken": getCsrfToken(),
        },
        body: body.toString(),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            showError(result.data.error || "Nepodařilo se uložit.");
            return;
          }
          var found = false;
          for (var i = 0; i < select.options.length; i++) {
            if (select.options[i].value === result.data.kod) {
              select.options[i].textContent = result.data.nazev;
              found = true;
              break;
            }
          }
          if (!found) {
            var opt = document.createElement("option");
            opt.value = result.data.kod;
            opt.textContent = result.data.nazev;
            var anchor = ensureNewOption(select);
            select.insertBefore(opt, anchor);
          }
          select.value = result.data.kod;
          createBox.hidden = true;
          input.value = "";
        })
        .catch(function () {
          showError("Nepodařilo se uložit.");
        })
        .finally(function () {
          saveBtn.disabled = false;
        });
    }

    saveBtn.addEventListener("click", saveNewTyp);
    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        saveNewTyp();
      } else if (event.key === "Escape") {
        event.preventDefault();
        closeCreate(true);
      }
    });

    var form = select.closest("form");
    if (form) {
      form.addEventListener("submit", function (event) {
        if (select.value === NEW_VALUE) {
          event.preventDefault();
          openCreate();
          showError("Nejdříve zadejte název nového typu.");
        }
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initTypField);
  } else {
    initTypField();
  }
})();
