document.addEventListener('DOMContentLoaded', function () {

  function readI18n() {
    try {
      var el = document.getElementById('ts-global-i18n');
      return el ? JSON.parse(el.textContent) : {};
    } catch (e) {
      return {};
    }
  }
  var I18N = readI18n();

  // === OVLÁDÁNÍ MODÁLNÍCH OKEN PRO AKCE ===
  (function () {
    var changelistForm = document.getElementById('changelist-form');
    var actionSelect = document.querySelector('select[name="action"]');
    if (!changelistForm || !actionSelect) return;

    var modalVyuct = document.getElementById('vyuctovani-modal');
    var btnVyuctConfirm = document.getElementById('modal-confirm-button');
    var btnVyuctCancel = document.getElementById('modal-cancel-button');

    var modalPlatba = document.getElementById('platba-modal');
    var btnPlatbaConfirm = document.getElementById('platba-confirm-button');
    var btnPlatbaCancel = document.getElementById('platba-cancel-button');

    function closeAllModals() {
      if (modalVyuct) modalVyuct.style.display = 'none';
      if (modalPlatba) modalPlatba.style.display = 'none';
    }

    changelistForm.addEventListener('submit', function (e) {
      var action = actionSelect.value;

      if (action === 'akce_vygenerovat_vyuctovani') {
        if (changelistForm.querySelectorAll('input[name="_selected_action"]:checked').length === 0) {
          alert(I18N.selectAtLeastOnePlayer || 'Musíte vybrat alespoň jednoho hráče.');
          e.preventDefault();
          return;
        }
        e.preventDefault();
        modalVyuct.style.display = 'block';
      } else if (action === 'akce_pridat_platbu') {
        if (changelistForm.querySelectorAll('input[name="_selected_action"]:checked').length === 0) {
          alert(I18N.selectAtLeastOnePlayer || 'Musíte vybrat alespoň jednoho hráče.');
          e.preventDefault();
          return;
        }
        e.preventDefault();
        var dateInput = document.getElementById('id_modal_payment_date');
        if (dateInput && !dateInput.value) {
          dateInput.valueAsDate = new Date();
        }
        modalPlatba.style.display = 'block';
      }
    });

    if (btnVyuctCancel) btnVyuctCancel.addEventListener('click', closeAllModals);
    if (btnVyuctConfirm) {
      btnVyuctConfirm.addEventListener('click', function () {
        addHidden(changelistForm, '_bulk_vyuct_from', document.getElementById('id_modal_vyuct_from').value);
        addHidden(changelistForm, '_bulk_vyuct_to', document.getElementById('id_modal_vyuct_to').value);
        addHidden(changelistForm, '_bulk_castka_k_uhrazeni', document.getElementById('id_modal_castka_k_uhrazeni').value);
        addHidden(changelistForm, '_bulk_email_variant', document.getElementById('id_modal_email_variant').value);
        closeAllModals();
        changelistForm.submit();
      });
    }

    if (btnPlatbaCancel) btnPlatbaCancel.addEventListener('click', closeAllModals);
    if (btnPlatbaConfirm) {
      btnPlatbaConfirm.addEventListener('click', function () {
        var amt = document.getElementById('id_modal_payment_amount').value;
        if (!amt) {
          alert(I18N.enterAmount || 'Zadejte částku.');
          return;
        }
        addHidden(changelistForm, '_bulk_payment_amount', amt);
        addHidden(changelistForm, '_bulk_payment_type', document.getElementById('id_modal_payment_type').value);
        addHidden(changelistForm, '_bulk_payment_date', document.getElementById('id_modal_payment_date').value);
        addHidden(changelistForm, '_bulk_payment_note', document.getElementById('id_modal_payment_note').value);
        closeAllModals();
        changelistForm.submit();
      });
    }

    function addHidden(form, name, value) {
      var input = document.createElement('input');
      input.type = 'hidden';
      input.name = name;
      input.value = value;
      form.appendChild(input);
    }
  })();

});
