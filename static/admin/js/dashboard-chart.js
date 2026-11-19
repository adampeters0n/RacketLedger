(function () {
  "use strict";

  function readData() {
    var el = document.getElementById("dash-month-chart-data");
    if (!el) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return null;
    }
  }

  function cssVar(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  function hexToRgb(hex) {
    var raw = String(hex || "").trim().replace("#", "");
    if (!raw) return null;
    if (raw.length === 3) raw = raw.split("").map(function (c) { return c + c; }).join("");
    if (raw.length !== 6) return null;
    var n = parseInt(raw, 16);
    if (Number.isNaN(n)) return null;
    return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
  }

  function rgba(hex, alpha, fallback) {
    var rgb = hexToRgb(hex);
    if (!rgb) return fallback;
    return "rgba(" + rgb.r + "," + rgb.g + "," + rgb.b + "," + alpha + ")";
  }

  function barGradient(chart, topColor, bottomColor) {
    var area = chart.chartArea;
    if (!area) return topColor;
    var ctx = chart.ctx;
    var g = ctx.createLinearGradient(0, area.top, 0, area.bottom);
    g.addColorStop(0, topColor);
    g.addColorStop(1, bottomColor || topColor);
    return g;
  }

  function niceMax(values, pad) {
    var max = 0;
    for (var i = 0; i < values.length; i++) {
      var n = Number(values[i]) || 0;
      if (n > max) max = n;
    }
    if (max <= 0) return pad || 1;
    return max * 1.18;
  }

  function init() {
    if (typeof Chart === "undefined") return;
    var canvas = document.getElementById("dashMonthChart");
    var data = readData();
    if (!canvas || !data || !data.length) return;

    var brand = cssVar("--brand", "#E67817");
    var muted = cssVar("--muted", "#64748B");
    var line = cssVar("--line", "#e2e5ea");
    var text = cssVar("--text-strong", "#111111");
    var dark = document.documentElement.dataset.mode === "dark";

    // Platby – sytá mint jako v analytice (musí být jasně vidět vedle čáry hodin)
    var paidTop = dark ? "rgba(110,231,183,0.92)" : "rgba(5,150,105,0.88)";
    var paidBottom = dark ? "rgba(110,231,183,0.35)" : "rgba(5,150,105,0.28)";
    var paidHover = dark ? "rgba(110,231,183,1)" : "rgba(4,120,87,0.95)";
    var paidLegend = dark ? "#6ee7b7" : "#059669";

    var labels = data.map(function (d) { return d.label; });
    var hours = data.map(function (d) { return Number(d.hours) || 0; });
    var paid = data.map(function (d) { return Number(d.paid) || 0; });

    var moneyMax = niceMax(paid, 1000);
    var hoursMax = niceMax(hours, 1);

    new Chart(canvas.getContext("2d"), {
      type: "bar",
      data: {
        labels: labels,
        datasets: [
          {
            type: "bar",
            label: "Platby",
            data: paid,
            yAxisID: "yMoney",
            backgroundColor: function (ctx) {
              return barGradient(ctx.chart, paidTop, paidBottom);
            },
            hoverBackgroundColor: paidHover,
            borderRadius: 7,
            borderSkipped: false,
            maxBarThickness: 48,
            categoryPercentage: 0.62,
            barPercentage: 0.78,
            order: 2,
          },
          {
            type: "line",
            label: "Hodiny",
            data: hours,
            yAxisID: "yHours",
            borderColor: brand,
            backgroundColor: "transparent",
            fill: false,
            tension: 0.38,
            borderWidth: 2.75,
            pointRadius: 5,
            pointHoverRadius: 7,
            pointBackgroundColor: dark ? cssVar("--bg", "#1a252f") : "#fff",
            pointBorderColor: brand,
            pointBorderWidth: 2.25,
            pointHoverBorderWidth: 2.5,
            order: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: { padding: { top: 6, right: 4, bottom: 0, left: 0 } },
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            position: "bottom",
            align: "center",
            labels: {
              boxWidth: 10,
              boxHeight: 10,
              usePointStyle: true,
              pointStyle: "circle",
              padding: 18,
              color: muted,
              font: { size: 11, weight: "650", family: "inherit" },
              generateLabels: function (chart) {
                var items = Chart.defaults.plugins.legend.labels.generateLabels(chart);
                items.forEach(function (item) {
                  if (item.text === "Platby") {
                    item.fillStyle = paidLegend;
                    item.strokeStyle = paidLegend;
                  }
                });
                return items;
              },
            },
          },
          tooltip: {
            backgroundColor: dark ? "#0f172a" : text,
            titleColor: dark ? "#f8fafc" : "#fff",
            bodyColor: dark ? "#e2e8f0" : "rgba(255,255,255,0.92)",
            borderColor: dark ? "rgba(148,163,184,0.28)" : "transparent",
            borderWidth: dark ? 1 : 0,
            titleFont: { size: 12, weight: "700" },
            bodyFont: { size: 12, weight: "500" },
            padding: 12,
            cornerRadius: 10,
            displayColors: true,
            boxPadding: 6,
            callbacks: {
              label: function (ctx) {
                var v = ctx.parsed.y;
                if (ctx.dataset.yAxisID === "yMoney") {
                  return " Platby  " + Math.round(v).toLocaleString("cs-CZ") + " Kč";
                }
                return (
                  " Hodiny  " +
                  Number(v).toLocaleString("cs-CZ", { maximumFractionDigits: 1 }) +
                  " h"
                );
              },
            },
          },
        },
        scales: {
          x: {
            grid: { display: false, drawBorder: false },
            ticks: {
              color: muted,
              font: { size: 11, weight: "650" },
              padding: 8,
            },
            border: { display: false },
          },
          yMoney: {
            position: "left",
            beginAtZero: true,
            suggestedMax: moneyMax,
            grid: {
              color: dark ? "rgba(148,163,184,0.14)" : "rgba(226,229,234,0.9)",
              drawBorder: false,
              tickLength: 0,
            },
            ticks: {
              color: muted,
              font: { size: 10, weight: "550" },
              padding: 8,
              maxTicksLimit: 5,
              callback: function (v) {
                if (v === 0) return "0";
                if (Math.abs(v) >= 1000) return Math.round(v / 1000) + "k";
                return v;
              },
            },
            border: { display: false },
          },
          yHours: {
            position: "right",
            beginAtZero: true,
            suggestedMax: hoursMax,
            grid: { drawOnChartArea: false, drawBorder: false },
            ticks: {
              color: brand,
              font: { size: 10, weight: "650" },
              padding: 8,
              maxTicksLimit: 5,
              callback: function (v) {
                return v + " h";
              },
            },
            border: { display: false },
          },
        },
      },
    });
  }

  function syncScheduleHeight() {
    var today = document.querySelector(".dash-board--today");
    var month = document.querySelector(".dash-board--month");
    if (!today || !month) return;
    today.style.height = "auto";
    var h = Math.round(month.getBoundingClientRect().height);
    if (h > 0) today.style.height = h + "px";
  }

  function boot() {
    init();
    syncScheduleHeight();
    // Po layoutu Chart.js / fontů ještě jednou
    requestAnimationFrame(syncScheduleHeight);
    window.addEventListener("resize", syncScheduleHeight);
    if (typeof ResizeObserver !== "undefined") {
      var month = document.querySelector(".dash-board--month");
      if (month) {
        var ro = new ResizeObserver(syncScheduleHeight);
        ro.observe(month);
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
