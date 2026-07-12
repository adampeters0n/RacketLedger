document.addEventListener('DOMContentLoaded', function () {
  function selectedRezim() {
    var checked = document.querySelector('input[name="auto_rezim"]:checked');
    return checked ? checked.value : '';
  }

  function updateRezimFields() {
    var val = selectedRezim();
    var isManual = val === 'MANUAL';

    document.querySelectorAll('[data-rezim-field]').forEach(function (el) {
      var show = el.getAttribute('data-rezim-field') === val;
      el.style.display = show ? '' : 'none';
    });

    document.querySelectorAll('[data-rezim-auto-only]').forEach(function (el) {
      el.style.display = isManual ? 'none' : '';
    });
  }

  document.querySelectorAll('input[name="auto_rezim"]').forEach(function (radio) {
    radio.addEventListener('change', updateRezimFields);
  });

  updateRezimFields();
});
