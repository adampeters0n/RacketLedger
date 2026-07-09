document.addEventListener('DOMContentLoaded', function() {
      var filterBtn = document.getElementById('filter-button');
      if (filterBtn) {
        filterBtn.addEventListener('click', function(e) {
          e.preventDefault(); // Zabrání odkazu, aby skočil na #
          
          var fromVal = document.getElementById('id_filter_from').value;
          var toVal = document.getElementById('id_filter_to').value;
          
          // Použije aktuální URL bez starých parametrů
          var baseUrl = window.location.pathname; 
          var params = new URLSearchParams();
          
          if (fromVal) {
            params.append('from', fromVal);
          }
          if (toVal) {
            params.append('to', toVal);
          }
          
          // Sestaví novou URL (např. .../change/?from=...&to=...)
          // a znovu načte stránku s těmito parametry
          window.location.href = baseUrl + '?' + params.toString();
        });
      }
    });
