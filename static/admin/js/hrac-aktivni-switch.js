(function () {
  var LABEL_ON = "Aktivní hráč";
  var LABEL_OFF = "Neaktivní hráč";

  function syncAktivniLabel(input) {
    if (!input) return;
    var label =
      document.querySelector('label.vCheckboxLabel[for="' + input.id + '"]') ||
      (input.parentElement && input.parentElement.querySelector("label.vCheckboxLabel"));
    if (!label) return;
    if (input.checked) {
      label.textContent = LABEL_ON;
      label.classList.remove("is-off");
    } else {
      label.textContent = LABEL_OFF;
      label.classList.add("is-off");
    }
  }

  function init() {
    var input = document.getElementById("id_aktivni");
    if (!input) return;
    syncAktivniLabel(input);
    input.addEventListener("change", function () {
      syncAktivniLabel(input);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
