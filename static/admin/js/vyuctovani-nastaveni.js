document.addEventListener("DOMContentLoaded", function () {
  function selectedRezim() {
    var checked = document.querySelector('input[name="auto_rezim"]:checked');
    return checked ? checked.value : "";
  }

  function syncActiveRows() {
    document.querySelectorAll(".vyuct-rezim-list .nast-excel-row").forEach(function (row) {
      var input = row.querySelector('input[type="radio"]');
      row.classList.toggle("is-active", !!(input && input.checked));
    });
  }

  function updateRezimFields() {
    var val = selectedRezim();
    var isManual = val === "MANUAL";
    var anyParamVisible = false;

    document.querySelectorAll("[data-rezim-field]").forEach(function (el) {
      var show = el.getAttribute("data-rezim-field") === val;
      el.style.display = show ? "" : "none";
      if (show) anyParamVisible = true;
    });

    document.querySelectorAll(".vyuct-rezim-params").forEach(function (el) {
      el.style.display = anyParamVisible ? "" : "none";
    });

    document.querySelectorAll("[data-rezim-auto-only]").forEach(function (el) {
      el.style.display = isManual ? "none" : "";
    });

    syncActiveRows();
  }

  document.querySelectorAll('input[name="auto_rezim"]').forEach(function (radio) {
    radio.addEventListener("change", updateRezimFields);
  });

  updateRezimFields();
});
