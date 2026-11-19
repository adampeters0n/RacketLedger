document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("[data-ts-card-help]").forEach(function (btn) {
    var targetId = btn.getAttribute("aria-controls");
    var panel = targetId ? document.getElementById(targetId) : null;
    if (!panel) return;

    btn.addEventListener("click", function () {
      var open = btn.getAttribute("aria-expanded") === "true";
      var next = !open;
      btn.setAttribute("aria-expanded", next ? "true" : "false");
      btn.setAttribute(
        "aria-label",
        next ? "Skrýt nápovědu" : "Zobrazit nápovědu"
      );
      if (next) {
        panel.hidden = false;
        panel.classList.add("is-open");
      } else {
        panel.hidden = true;
        panel.classList.remove("is-open");
      }
    });
  });
});
