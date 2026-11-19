(function () {
  'use strict';

  const i18nEl = document.getElementById('ts-i18n');
  const localeEl = document.getElementById('ts-js-locale');
  const TS_I18N = i18nEl ? JSON.parse(i18nEl.textContent) : {};
  const JS_LOCALE = localeEl ? JSON.parse(localeEl.textContent) : 'cs-CZ';
  function t(key, fallback) {
    return TS_I18N[key] || fallback || key;
  }

  if (typeof Chart !== 'undefined' && typeof ChartDataLabels !== 'undefined') {
    Chart.register(ChartDataLabels);
  }

  /* Pozadí canvasu – sjednocené neprůhledné pro stránku i modal */
  const chartCanvasBgPlugin = {
    id: 'chartCanvasBg',
    beforeDraw(chart) {
      const canvas = chart.canvas;
      if (
        !canvas?.closest('.analytika-app') &&
        !canvas?.closest('.analytika-modal') &&
        canvas?.id !== 'analytikaModalCanvas'
      ) {
        return;
      }
      const { ctx, width, height } = chart;
      ctx.save();
      ctx.globalCompositeOperation = 'destination-over';
      ctx.fillStyle = chartSurfaceColor();
      ctx.fillRect(0, 0, width, height);
      ctx.restore();
    },
  };
  if (typeof Chart !== 'undefined') {
    Chart.register(chartCanvasBgPlugin);
  }

  function parseVal(id) {
    const el = document.getElementById(id);
    if (!el) return 0;
    return parseFloat(el.textContent.replace(/[^\d.-]/g, '').replace(/\s/g, '')) || 0;
  }
  function safeLoadJson(id) {
    const el = document.getElementById(id);
    if (!el || !el.textContent.trim()) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }

  const kcFmt = v => Math.round(v).toLocaleString(JS_LOCALE) + ' ' + t('currency', 'Kč');
  const kcShrt = v => {
    const n = Math.round(Math.abs(v));
    if (n >= 1_000_000) return Math.round(n / 1_000_000) + 'M ' + t('currency', 'Kč');
    if (n >= 1000) return Math.round(n / 1000) + 'k ' + t('currency', 'Kč');
    return n.toLocaleString(JS_LOCALE) + ' ' + t('currency', 'Kč');
  };
  function kpiVal(valueKey, domId) {
    const v = kpiData[valueKey];
    if (typeof v === 'number' && !Number.isNaN(v)) return v;
    if (domId) return parseVal(domId);
    return 0;
  }
  function moneyYMax(values, base = 0) {
    const nums = (Array.isArray(values) ? values : [values]).filter(v => typeof v === 'number' && !Number.isNaN(v));
    const maxVal = Math.max(...nums, base, 0);
    if (maxVal <= 0) return 1000;
    const padded = maxVal * 1.12;
    if (padded < 1000) return Math.ceil(padded / 100) * 100;
    if (padded < 10000) return Math.ceil(padded / 500) * 500;
    return Math.ceil(padded / 1000) * 1000;
  }
  function moneyYScale(values) {
    const nums = (Array.isArray(values) ? values : []).filter(v => typeof v === 'number' && !Number.isNaN(v));
    if (!nums.length) return { suggestedMin: 0, suggestedMax: 1000 };
    const minVal = Math.min(...nums, 0);
    const maxVal = Math.max(...nums, 0);
    const scale = {
      suggestedMax: moneyYMax(nums),
    };
    if (minVal < 0) scale.suggestedMin = -moneyYMax(nums.map(Math.abs));
    return scale;
  }
  function shareOfNauctovano(value, base) {
    if (!base || base <= 0) return '—';
    return Math.round((value / base) * 100) + ' % ' + t('percentOfCharged', 'z naúčtováno');
  }
  const hFmt = v => (typeof v === 'number' ? v : parseFloat(v) || 0).toFixed(1) + ' h';

  function cssVar(name, fallback) {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  }

  function anaCssVar(name, fallback) {
    const app = document.querySelector('.analytika-app');
    const source = app ? getComputedStyle(app) : getComputedStyle(document.documentElement);
    const value = source.getPropertyValue(name).trim();
    return value || fallback;
  }

  function isDarkMode() {
    return document.documentElement.dataset.mode === 'dark';
  }

  function chartSurfaceColor() {
    return anaCssVar('--ana-bg', isDarkMode() ? cssVar('--bg', '#1a252f') : '#f4f5f0');
  }

  function hexToRgb(hex) {
    const raw = (hex || '').trim().replace('#', '');
    if (!raw) return null;
    const h = raw.length === 3 ? raw.split('').map(c => c + c).join('') : raw;
    const n = parseInt(h, 16);
    if (Number.isNaN(n)) return null;
    return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
  }

  function rgbaFromHex(hex, alpha, fallback) {
    const rgb = hexToRgb(hex);
    if (!rgb) return fallback;
    return `rgba(${rgb.r},${rgb.g},${rgb.b},${alpha})`;
  }

  function buildPalette() {
    const dark = isDarkMode();
    const brand = cssVar('--brand', '#E67817');
    const brandFill = rgbaFromHex(brand, dark ? 0.14 : 0.15, dark ? 'rgba(20,131,59,0.14)' : 'rgba(230,120,23,0.15)');
    const brandStroke = rgbaFromHex(brand, dark ? 0.95 : 0.88, brand);

    if (dark) {
      return {
        brand,
        brandLight: brandFill,
        brandBar: brandStroke,
        brandPoint: chartSurfaceColor(),
        slate: '#93c5fd',
        slateLight: 'rgba(147,197,253,0.1)',
        slateBar: 'rgba(147,197,253,0.72)',
        slateBarSoft: 'rgba(147,197,253,0.55)',
        mint: '#6ee7b7',
        mintLight: 'rgba(110,231,183,0.1)',
        mintBar: 'rgba(110,231,183,0.62)',
        dark: '#cbd5e1',
        danger: cssVar('--ana-danger', '#fca5a5'),
        dangerLight: 'rgba(248,113,113,0.18)',
        grid: 'rgba(148,163,184,0.14)',
        text: cssVar('--muted', '#94a3b8'),
        legend: cssVar('--text', '#e2e8f0'),
        label: cssVar('--text-strong', '#f1f5f9'),
        surface: chartSurfaceColor(),
        tooltipBg: '#0f172a',
        charged: 'rgba(147,197,253,0.88)',
        chargedBar: 'rgba(147,197,253,0.55)',
        chargedLine: '#93c5fd',
        paid: 'rgba(110,231,183,0.88)',
        paidBar: 'rgba(110,231,183,0.5)',
        paidLine: '#6ee7b7',
        paidFill: 'rgba(110,231,183,0.08)',
        unpaid: 'rgba(252,165,165,0.88)',
      };
    }

    return {
      brand,
      brandLight: brandFill,
      brandBar: brandStroke,
      brandPoint: '#ffffff',
      slate: '#64748b',
      slateLight: 'rgba(100,116,139,0.12)',
      slateBar: 'rgba(100,116,139,0.85)',
      slateBarSoft: 'rgba(100,116,139,0.7)',
      mint: '#059669',
      mintLight: 'rgba(5,150,105,0.1)',
      mintBar: 'rgba(5,150,105,0.65)',
      dark: '#1a1d16',
      danger: '#c92a2a',
      dangerLight: 'rgba(201,42,42,0.12)',
      grid: '#eef0ea',
      text: '#6b7264',
      legend: '#6b7264',
      label: '#1a1d16',
      surface: chartSurfaceColor(),
      tooltipBg: '#1a1d16',
      charged: 'rgba(100,116,139,0.85)',
      chargedBar: 'rgba(100,116,139,0.85)',
      chargedLine: '#64748b',
      paid: 'rgba(26,29,22,0.75)',
      paidBar: 'rgba(26,29,22,0.7)',
      paidLine: '#1a1d16',
      paidFill: 'rgba(26,29,22,0.06)',
      unpaid: 'rgba(201,42,42,0.8)',
    };
  }

  const PAL = buildPalette();

  const legendBottom = {
    position: 'bottom',
    labels: {
      usePointStyle: true,
      color: PAL.legend,
      font: { size: 11 },
      boxWidth: 10,
    },
  };

  const tooltipBase = {
    backgroundColor: PAL.tooltipBg,
    titleColor: '#f8fafc',
    bodyColor: '#e2e8f0',
    borderColor: isDarkMode() ? 'rgba(148,163,184,0.28)' : 'transparent',
    borderWidth: isDarkMode() ? 1 : 0,
    titleFont: { size: 13, weight: '600' },
    bodyFont: { size: 12 },
    padding: 12,
    cornerRadius: 8,
    displayColors: true,
    boxPadding: 4,
  };

  if (typeof Chart !== 'undefined') {
    Chart.defaults.color = PAL.legend;
    Chart.defaults.borderColor = PAL.grid;
    Chart.defaults.plugins.tooltip.backgroundColor = tooltipBase.backgroundColor;
    Chart.defaults.plugins.tooltip.titleColor = tooltipBase.titleColor;
    Chart.defaults.plugins.tooltip.bodyColor = tooltipBase.bodyColor;
    Chart.defaults.plugins.tooltip.borderColor = tooltipBase.borderColor;
    Chart.defaults.plugins.tooltip.borderWidth = tooltipBase.borderWidth;
    Chart.defaults.plugins.tooltip.cornerRadius = tooltipBase.cornerRadius;
    Chart.defaults.plugins.tooltip.padding = tooltipBase.padding;
    Chart.defaults.plugins.tooltip.displayColors = true;
  }

  const monthlyData = safeLoadJson('monthly-data');
  const yearlyData = safeLoadJson('yearly-data');
  const alltimeData = safeLoadJson('alltime-data');
  const revenueByYearData = safeLoadJson('revenue-by-year-data');
  const debtorsChartData = safeLoadJson('debtors-data');
  const hraciAgeData = safeLoadJson('hraci-age-data');
  const hraciPohlaviData = safeLoadJson('hraci-pohlavi-data');
  const hraciUrovenData = safeLoadJson('hraci-uroven-data');
  const hraciEngageData = safeLoadJson('hraci-engage-data');
  const hraciFreqData = safeLoadJson('hraci-freq-data');
  const trenerChartData = safeLoadJson('trener-data');
  const trenerHoursData = safeLoadJson('trener-hours-data');
  const activityData = safeLoadJson('activity-data');
  const accChartsBundle = safeLoadJson('accounting-charts-data') || {};
  const accData = accChartsBundle.m6 || safeLoadJson('accounting-monthly-data') || [];
  const accYearData = accChartsBundle.y12 || safeLoadJson('accounting-yearly-data') || [];
  const accAlltimeData = accChartsBundle.all || safeLoadJson('accounting-alltime-data') || [];
  const debtorsList = safeLoadJson('debtors-list-data') || [];
  const treneriList = safeLoadJson('treneri-list-data') || [];
  const kpiData = safeLoadJson('kpi-data') || {};
  const rawTrainings = kpiData.trainings_count_current || 0;
  const rawCharges = kpiData.charges_count_current || 0;
  const rawPayments = kpiData.payments_count_current || 0;
  const nakladyChartsBundle = safeLoadJson('naklady-charts-data') || {};
  const nakladyChartData = nakladyChartsBundle.m12 || safeLoadJson('naklady-chart-data') || [];
  const nakladyAlltimeChartData = nakladyChartsBundle.all || [];
  const nakladyDailyChartData = nakladyChartsBundle.daily || [];
  const analytikaSectionUrls = safeLoadJson('analytika-section-urls') || {};
  const nakladySectionUrl = analytikaSectionUrls.naklady || '/admin/analytika/naklady/';

  const chartRegistry = {};
  const chartBuilders = {};
  let modalChart = null;

  /* ── Gradient helper ── */
  function barGradient(chart, colorRgb) {
    const { ctx, chartArea } = chart;
    if (!chartArea) return colorRgb.replace('0.85', '1');
    const g = ctx.createLinearGradient(0, chartArea.bottom, 0, chartArea.top);
    const bottom = isDarkMode() ? 0.22 : 0.35;
    const top = isDarkMode() ? 0.78 : 0.95;
    g.addColorStop(0, colorRgb.replace(/[\d.]+\)$/, `${bottom})`));
    g.addColorStop(1, colorRgb.replace(/[\d.]+\)$/, `${top})`));
    return g;
  }

  const baseScales = {
    x: {
      ticks: { color: PAL.text, font: { size: 11, weight: '500' } },
      grid: { display: false },
      border: { display: false },
    },
    y: {
      ticks: { color: PAL.text, font: { size: 10 } },
      grid: { color: PAL.grid, drawBorder: false },
      border: { display: false },
      beginAtZero: true,
    },
  };

  function hoverCursor(chart) {
    return {
      onHover: (e, els) => {
        e.native.target.style.cursor = els.length ? 'pointer' : 'default';
      },
    };
  }

  function registerChart(id, config, builder) {
    const canvas = document.getElementById(id);
    if (!canvas) return null;
    if (typeof Chart === 'undefined') return null;
    if (chartRegistry[id]) chartRegistry[id].destroy();
    try {
      const chart = new Chart(canvas, config);
      chartRegistry[id] = chart;
      if (builder) chartBuilders[id] = builder;
      requestAnimationFrame(() => {
        try {
          chart.resize();
          chart.update('none');
        } catch (e) { /* noop */ }
      });
      return chart;
    } catch (e) {
      console.error(t('chartRenderError', 'Graf se nepodařilo vykreslit:'), id, e);
      return null;
    }
  }

  function refreshCharts() {
    Object.values(chartRegistry).forEach(ch => {
      try {
        ch.resize();
        ch.update('none');
      } catch (e) { /* noop */ }
    });
  }

  function buildChartConfig(id, forModal) {
    const builder = chartBuilders[id];
    if (!builder) return null;
    const cfg = builder(!!forModal);
    if (forModal && cfg?.options) {
      cfg.options = {
        ...cfg.options,
        animation: false,
        plugins: {
          ...cfg.options.plugins,
          title: { display: false },
        },
      };
    }
    return cfg;
  }

  function bindClick(id, handler) {
    const chart = chartRegistry[id];
    if (!chart) return;
    chart.options.onClick = (e, elements) => {
      if (!elements.length) return;
      const el = elements[0];
      handler(el.index, el.datasetIndex, chart);
    };
    chart.update('none');
  }

  /* ── Drill-down HTML builders ── */
  function drillWrap(variant, content) {
    return `<div class="drill-panel drill-panel--${variant}">${content}</div>`;
  }

  /** Nadpis grafu je v modalu (openDrill); zde jen období (měsíc / rok). */
  function drillHeader(period, _subtitle, _variant) {
    if (!period) return '';
    return `<div class="drill-header drill-header--period">
      <p class="drill-period-label">${period}</p>
    </div>`;
  }

  function metricTitle(focus) {
    const labels = {
      cashflow: 'Cash Flow',
      gross_profit: t('grossProfit', 'Hrubý zisk'),
      net_profit: t('netProfit', 'Čistý zisk'),
      trener_paid: t('coachPayments', 'Výplaty trenérům'),
      other_costs: t('otherCosts', 'Ostatní náklady'),
    };
    return labels[focus] || t('accountingDetail', 'Účetní detail');
  }

  function drillGrid(items, extraClass) {
    const cls = extraClass ? `drill-grid ${extraClass}` : 'drill-grid';
    return `<div class="${cls}">${items.map(it => `
      <div class="drill-stat${it.tone ? ' drill-stat--' + it.tone : ''}${it.hl ? ' drill-stat--highlight' : ''}${it.neg ? ' drill-stat--negative' : ''}">
        <span class="drill-stat-label">${it.label}</span>
        <span class="drill-stat-value">${it.value}</span>
      </div>`).join('')}</div>`;
  }

  function drillBars(rows, variant) {
    const palette = {
      trener: ['#E67817', '#64748b'],
      hrac: ['#c92a2a', '#94a3b8'],
      day: [PAL.brand, PAL.chargedLine, PAL.paidLine],
      person: ['#E67817', '#64748b'],
    };
    const colors = palette[variant] || palette.person;
    const max = Math.max(...rows.map(r => Math.abs(r.value)), 1);
    return `<div class="drill-bars">${rows.map((r, i) => `
      <div class="drill-bar-row">
        <span class="drill-bar-label" title="${r.label}">${r.label}</span>
        <div class="drill-bar-track"><div class="drill-bar-fill" style="width:${(Math.abs(r.value) / max * 100).toFixed(1)}%;background:${r.color || colors[i % colors.length]}"></div></div>
        <span class="drill-bar-value">${r.display || r.value}</span>
      </div>`).join('')}</div>`;
  }

  function drillLink(url, label) {
    return url ? `<a class="drill-link" href="${url}">${label || t('openDetail', 'Otevřít detail')} →</a>` : '';
  }

  function monthDetail(d) {
    if (d && d.split) {
      const schoolUnpaid = Math.max(0, (d.treningy_charged || 0) - (d.school_paid || 0));
      return drillWrap('month', drillHeader(d.label) + drillGrid([
        { label: t('hoursPlayed', 'Odehrané hodiny'), value: hFmt(d.hours), hl: true, tone: 'brand' },
        { label: t('schoolHours', 'Hodiny – škola'), value: hFmt(d.treningy_hours || 0), tone: 'neutral' },
        { label: t('rentalHours', 'Hodiny – pronájmy'), value: hFmt(d.pronajem_hours || 0), tone: 'neutral' },
        { label: t('schoolCharged', 'Tenisová škola'), value: kcFmt(d.treningy_charged || 0), tone: 'slate' },
        { label: t('rentals', 'Pronájmy'), value: kcFmt(d.pronajmy || 0), tone: 'dark' },
        { label: t('charged', 'Tržby celkem'), value: kcFmt(d.charged), tone: 'slate' },
        { label: t('paid', 'Příjmy celkem'), value: kcFmt(d.paid), tone: 'profit' },
        { label: t('unpaidSchool', 'Nezaplaceno (škola)'), value: kcFmt(schoolUnpaid), neg: schoolUnpaid > 0, tone: 'cost' },
      ]));
    }
    const unpaid = Math.max(0, (d.charged || 0) - (d.paid || 0));
    return drillWrap('month', drillHeader(d.label) + drillGrid([
      { label: t('hoursPlayed', 'Odehrané hodiny'), value: hFmt(d.hours), hl: true, tone: 'brand' },
      { label: t('charged', 'Naúčtováno'), value: kcFmt(d.charged), tone: 'slate' },
      { label: t('paid', 'Zaplaceno'), value: kcFmt(d.paid), tone: 'profit' },
      { label: t('unpaid', 'Nezaplaceno'), value: kcFmt(unpaid), neg: unpaid > 0, tone: 'cost' },
      { label: t('payment', 'Úhrada'), value: d.charged > 0 ? Math.round(d.paid / d.charged * 100) + ' %' : '—', tone: 'neutral' },
    ]));
  }

  function accMonthDetail(d, focus) {
    const cf = d.cashflow || 0;
    const gp = d.gross_profit || 0;
    const oc = d.other_costs || 0;
    const tp = d.trener_paid || 0;
    const te = d.trener_earned || 0;
    const np = d.net_profit !== undefined
      ? d.net_profit
      : ((d.paid || 0) - tp - oc);
    return drillWrap('accounting', drillHeader(d.label) + drillGrid([
      { label: 'Cash Flow', value: kcFmt(cf), neg: cf < 0, hl: focus === 'cashflow', tone: cf < 0 ? 'cost' : 'slate' },
      { label: t('grossProfit', 'Hrubý zisk'), value: kcFmt(gp), neg: gp < 0, hl: focus === 'gross_profit', tone: gp < 0 ? 'cost' : 'profit' },
      { label: t('netProfit', 'Čistý zisk'), value: kcFmt(np), neg: np < 0, hl: focus === 'net_profit', tone: np < 0 ? 'cost' : 'profit' },
      { label: t('charged', 'Naúčtováno'), value: kcFmt(d.charged || 0), tone: 'slate' },
      { label: t('received', 'Přijato'), value: kcFmt(d.paid || 0), tone: 'profit' },
      { label: t('coachPayments', 'Výplaty trenérům'), value: kcFmt(tp), hl: focus === 'trener_paid', tone: 'cost' },
      { label: t('otherCosts', 'Ostatní náklady'), value: kcFmt(oc), hl: focus === 'other_costs', tone: 'cost' },
      { label: t('coachCosts', 'Náklady trenérů'), value: kcFmt(te), tone: 'cost' },
    ]));
  }

  function dayDetail(d) {
    return drillWrap('day', drillHeader(d.day_name + ' ' + d.date)
      + drillGrid([
        { label: t('hours', 'Hodiny'), value: hFmt(d.hours), hl: true, tone: 'brand' },
        { label: t('charged', 'Naúčtováno'), value: kcFmt(d.charged), tone: 'slate' },
        { label: t('paid', 'Zaplaceno'), value: kcFmt(d.paid), tone: 'profit' },
      ])
      + `<div class="drill-subsection drill-subsection--bars"><h5 class="drill-subheading">${t('dayDistribution', 'Rozložení dne')}</h5>${drillBars([
        { label: t('hours', 'Hodiny'), value: d.hours, display: hFmt(d.hours) },
        { label: t('charged', 'Naúčtováno'), value: d.charged, display: kcShrt(d.charged) },
        { label: t('paid', 'Zaplaceno'), value: d.paid, display: kcShrt(d.paid) },
      ], 'day')}</div>`);
  }

  function comparisonDetail(label, value, ctx, baseNauctovano) {
    const unpaidLabel = t('unpaid', 'Nezaplaceno');
    const isUnpaid = label === unpaidLabel;
    const base = baseNauctovano ?? (ctx === t('month', 'měsíc')
      ? kpiVal('nauctovano_value', 'data-nauctovano')
      : kpiVal('total_all_charged_value', 'data-total-nauctovano'));
    const podilValue = label === t('charged', 'Naúčtováno')
      ? t('percentBase', '100 % (základ)')
      : shareOfNauctovano(value, base);
    const period = ctx ? (t('financialComparison', 'Finanční srovnání') + ' – ' + ctx) : '';
    return drillWrap('comparison', drillHeader(period) + drillGrid([
      { label: label, value: kcFmt(value), hl: true, neg: isUnpaid, tone: isUnpaid ? 'cost' : 'slate' },
      { label: t('share', 'Podíl'), value: podilValue, tone: 'neutral' },
    ]));
  }

  function personDetail(name, amount, url, extra) {
    const variant = extra?.variant
      || (extra?.subtitle?.includes(t('coach', 'Trenér')) ? 'trener' : '')
      || (extra?.subtitle?.includes(t('playerDebtor', 'Hráč – dlužník')) ? 'hrac' : 'person');
    const debtLabel = t('debt', 'Dluh');
    const isDebt = extra?.amountLabel === debtLabel;
    const heroTone = isDebt ? 'danger' : variant;
    const period = extra?.subtitle || '';

    let html = drillWrap(variant, `
      ${drillHeader(period)}
      <div class="drill-hero drill-hero--${heroTone}">
        <span class="drill-hero-label">${extra?.amountLabel || t('amount', 'Částka')}</span>
        <span class="drill-hero-value">${extra?.amountDisplay || kcFmt(amount)}</span>
      </div>
      ${extra?.stats?.length ? `<div class="drill-subsection"><h5 class="drill-subheading">${t('overview', 'Přehled')}</h5>${drillGrid(extra.stats, 'drill-grid--stats')}</div>` : ''}
      ${extra?.bars?.length ? `<div class="drill-subsection drill-subsection--bars"><h5 class="drill-subheading">${t('comparison', 'Porovnání')}</h5>${drillBars(extra.bars, variant)}</div>` : ''}
      ${drillLink(url, extra?.linkLabel || t('openProfile', 'Otevřít profil'))}
    `);
    return html;
  }

  function drillSection(title, items) {
    return `<div class="kpi-modal-section">
      <h4 class="kpi-modal-heading">${title}</h4>
      ${drillGrid(items)}
    </div>`;
  }

  function buildKpiModalHtml() {
    const k = kpiData;
    if (!k.hours) return '';

    const hoursMonth = parseFloat(String(k.hours).replace(/[^\d.-]/g, '')) || 0;
    const avgHours = k.trainings_count_current > 0
      ? (hoursMonth / k.trainings_count_current).toFixed(2) + ' h'
      : '0 h';
    const avgCharge = k.charges_count_current > 0
      ? Math.round(k.nauctovano_value / k.charges_count_current).toLocaleString(JS_LOCALE) + ' ' + t('currency', 'Kč')
      : '0 ' + t('currency', 'Kč');
    const avgPayment = k.payments_count_current > 0
      ? Math.round(k.platby_value / k.payments_count_current).toLocaleString(JS_LOCALE) + ' ' + t('currency', 'Kč')
      : '0 ' + t('currency', 'Kč');
    const debtVal = parseFloat(String(k.total_debt).replace(/[^\d.-]/g, '')) || 0;
    const balanceVal = parseFloat(String(k.total_balance).replace(/[^\d.-]/g, '')) || 0;

    return `<div class="kpi-modal drill-panel drill-panel--kpi">${
      drillSection(t('activityThisMonth', 'Aktivita – tento měsíc'), [
        { label: t('hoursPlayed', 'Odehrané hodiny'), value: k.hours },
        { label: t('trainingsCount', 'Počet tréninků'), value: String(k.trainings_count_current) },
        { label: t('avgPerTraining', 'Průměr na trénink'), value: avgHours },
      ])
    }${
      drillSection(t('financeThisMonth', 'Finance – tento měsíc'), [
        { label: t('charged', 'Naúčtováno'), value: k.nauctovano },
        { label: t('receivedPayments', 'Přijaté platby'), value: k.platby },
        { label: t('unpaid', 'Nezaplaceno'), value: k.unpaid, neg: k.unpaid_value > 0 },
        { label: t('avgPerInvoice', 'Průměr na fakturu'), value: avgCharge },
        { label: t('avgPerPayment', 'Průměr na platbu'), value: avgPayment },
        { label: t('invoicesCount', 'Počet faktur'), value: String(k.charges_count_current) },
      ])
    }${
      drillSection(t('overallTotals', 'Celkové souhrny'), [
        { label: t('hoursPlayed', 'Odehrané hodiny') + ' ' + t('total', 'celkem'), value: k.total_all_hours },
        { label: t('totalTrainings', 'Tréninků celkem'), value: String(k.total_trainings_count) },
        { label: t('totalCharged', 'Naúčtováno celkem'), value: k.total_all_charged },
        { label: t('paid', 'Zaplaceno') + ' ' + t('total', 'celkem'), value: k.total_all_paid },
        { label: t('toPayCoaches', 'K vyplacení trenérům'), value: k.k_vyplaceni },
        { label: t('debtAmounts', 'Dlužné částky'), value: k.total_debt, neg: debtVal > 0 },
      ])
    }${
      drillSection(t('playerBalance', 'Bilance hráčů'), [
        { label: t('surpluses', 'Přebytky'), value: k.total_surplus },
        { label: t('financialBalance', 'Finanční rovnováha'), value: k.total_balance, neg: balanceVal < 0 },
      ])
    }</div>`;
  }

  /* ── Modal ── */
  function getModal() {
    return document.getElementById('analytikaModal');
  }

  function openModal(title, chartId, extraHtml, wide) {
    const m = getModal();
    if (!m) return;
    if (modalChart) { modalChart.destroy(); modalChart = null; }

    if (m.parentElement !== document.body) {
      document.body.appendChild(m);
    }

    const titleEl = document.getElementById('analytikaModalTitle');
    const extraEl = document.getElementById('analytikaModalExtra');
    const chartWrap = document.getElementById('analytikaModalChartWrap');
    const bodyEl = m.querySelector('.analytika-modal-body');
    const canvas = document.getElementById('analytikaModalCanvas');
    const dialog = m.querySelector('.analytika-modal-dialog');

    if (titleEl) titleEl.textContent = title;
    if (extraEl) extraEl.innerHTML = extraHtml || '';
    m.hidden = false;
    m.removeAttribute('hidden');
    document.body.style.overflow = 'hidden';
    dialog?.classList.toggle('analytika-modal-dialog--wide', !!wide);
    dialog?.classList.toggle('analytika-modal-dialog--chart', !!chartId);
    bodyEl?.classList.toggle('analytika-modal-body--chart', !!chartId && !extraHtml);

    if (chartId && canvas) {
      const cfg = buildChartConfig(chartId, true);
      if (cfg) {
        chartWrap?.classList.remove('is-hidden');
        modalChart = new Chart(canvas, cfg);
      } else {
        chartWrap?.classList.add('is-hidden');
      }
    } else {
      chartWrap?.classList.add('is-hidden');
    }
  }

  function openDrill(title, html, chartId) {
    openModal(title, chartId || null, html, true);
  }

  function closeModal() {
    const m = getModal();
    if (!m) return;
    m.hidden = true;
    document.body.style.overflow = '';
    if (modalChart) { modalChart.destroy(); modalChart = null; }
    document.getElementById('analytikaModalChartWrap')?.classList.remove('is-hidden');
    m.querySelector('.analytika-modal-body')?.classList.remove('analytika-modal-body--chart');
    m.querySelector('.analytika-modal-dialog')?.classList.remove('analytika-modal-dialog--wide', 'analytika-modal-dialog--chart');
  }

  function openKpiPanelExpand(btn) {
    const panel = btn.closest('.panel--expandable');
    if (!panel) return;
    openDrill(panel.dataset.expandTitle || t('basicIndicators', 'Základní ukazatele'), buildKpiModalHtml());
  }

  document.addEventListener('click', e => {
    const expandBtn = e.target.closest('[data-panel-expand]');
    if (expandBtn) {
      e.preventDefault();
      e.stopPropagation();
      openKpiPanelExpand(expandBtn);
      return;
    }
    const chartBtn = e.target.closest('[data-chart-expand]');
    if (chartBtn) {
      e.preventDefault();
      e.stopPropagation();
      openModal(chartBtn.dataset.expandTitle || t('chartDetail', 'Detail grafu'), chartBtn.dataset.chartExpand, null, true);
    }
  });

  document.addEventListener('click', e => {
    if (e.target.closest('[data-modal-close]')) closeModal();
  });
  document.addEventListener('keydown', e => {
    const m = getModal();
    if (e.key === 'Escape' && m && !m.hidden) closeModal();
  });

  /* ── KPI průměry ── */
  try {
    const mH = kpiVal('hours_value', 'data-hours');
    const mT = rawTrainings || 0;
    const el1 = document.getElementById('avg-hours-per-training-month');
    if (el1) el1.textContent = mT > 0 ? (mH / mT).toFixed(2) + ' h' : '0 h';
    const elTile = document.getElementById('avg-hours-tile');
    if (elTile) elTile.textContent = mT > 0 ? (mH / mT).toFixed(2) + ' h' : '0 h';
    const mC = kpiVal('nauctovano_value', 'data-nauctovano');
    const mCn = rawCharges || 0;
    const el2 = document.getElementById('avg-charge-month');
    if (el2) el2.textContent = mCn > 0 ? Math.round(mC / mCn).toLocaleString(JS_LOCALE) + ' ' + t('currency', 'Kč') : '0 ' + t('currency', 'Kč');
    const mP = kpiVal('platby_value', 'data-platby');
    const mPn = rawPayments || 0;
    const el3 = document.getElementById('avg-payment-month');
    if (el3) el3.textContent = mPn > 0 ? Math.round(mP / mPn).toLocaleString(JS_LOCALE) + ' ' + t('currency', 'Kč') : '0 ' + t('currency', 'Kč');
  } catch (e) { /* noop */ }

  function setTrend(id, val) {
    const el = document.getElementById(id);
    if (!el) return;
    if (val > 0) { el.className = 'acc-trend up'; el.textContent = t('positive', 'Kladný'); }
    else if (val < 0) { el.className = 'acc-trend down'; el.textContent = t('negative', 'Záporný'); }
    else { el.className = 'acc-trend neutral'; el.textContent = t('zero', 'Nulový'); }
  }
  setTimeout(() => {
    setTrend('acc-cashflow-month-trend', parseVal('acc-cashflow-month'));
    setTrend('acc-gross-month-trend', parseVal('acc-gross-month'));
  }, 80);

  /* ══════════════════════════════════════
     GRAFY – vylepšený design + drill-down
     ══════════════════════════════════════ */

  const compLabels = [t('charged', 'Naúčtováno'), t('paid', 'Zaplaceno'), t('unpaid', 'Nezaplaceno')];
  const compColors = [PAL.charged, PAL.paid, PAL.unpaid];

  function makeComparisonChart(id, values, ctxLabel, baseNauctovano) {
    const yMax = moneyYMax(values, baseNauctovano);
    const builder = forModal => ({
      type: 'bar',
      data: {
        labels: compLabels,
        datasets: [{
          data: values,
          backgroundColor: forModal
            ? compColors
            : ctx => barGradient(ctx.chart, compColors[ctx.dataIndex]),
          hoverBackgroundColor: compColors,
          borderRadius: { topLeft: 8, topRight: 8 },
          borderSkipped: false,
          maxBarThickness: forModal ? 72 : 64,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: forModal ? false : { duration: 600, easing: 'easeOutQuart' },
        plugins: {
          legend: { display: false },
          datalabels: {
            anchor: 'end', align: 'top',
            formatter: kcFmt,
            font: { weight: '700', size: forModal ? 12 : 11 },
            color: PAL.label,
          },
          tooltip: { ...tooltipBase, callbacks: { label: c => ' ' + kcFmt(c.parsed.y) } },
        },
        scales: {
          x: baseScales.x,
          y: {
            ...baseScales.y,
            suggestedMax: yMax,
            ticks: { ...baseScales.y.ticks, callback: kcShrt, maxTicksLimit: 7 },
          },
        },
        ...(forModal ? {} : hoverCursor()),
      },
    });
    registerChart(id, builder(false), builder);
    bindClick(id, idx => {
      openDrill(compLabels[idx], comparisonDetail(compLabels[idx], values[idx], ctxLabel, baseNauctovano));
    });
  }

  const nauctovanoMonth = kpiVal('nauctovano_value', 'data-nauctovano');
  const platbyMonth = kpiVal('platby_value', 'data-platby');
  const monthComparisonValues = [
    nauctovanoMonth,
    platbyMonth,
    Math.max(0, nauctovanoMonth - platbyMonth),
  ];
  makeComparisonChart('comparisonChart', monthComparisonValues, t('month', 'měsíc'), nauctovanoMonth);

  const totalCharged = kpiVal('total_all_charged_value', 'data-total-nauctovano');
  const totalPaid = kpiVal('total_all_paid_value', 'data-total-platby');
  const totalComparisonValues = [
    totalCharged,
    totalPaid,
    Math.max(0, totalCharged - totalPaid),
  ];
  makeComparisonChart('comparisonChartTotal', totalComparisonValues, 'celkem', totalCharged);

  /* Finance přehled – grouped bars + hours line (6M / 1R / celá doba) */
  function financeOverviewConfig(data, forModal) {
    const barThickness = data.length > 18 ? 12 : data.length > 12 ? 16 : data.length > 6 ? 22 : 28;
    const pointRadius = data.length > 12 ? 4 : 6;
    const modalBar = forModal ? Math.min(barThickness + 8, 36) : barThickness;
    const modalPoint = forModal ? pointRadius + 2 : pointRadius;
    const split = !!(data.length && data[0].split);

    const moneyDatasets = split
      ? [
          {
            label: t('schoolCharged', 'Tenisová škola'),
            data: data.map(d => d.treningy_charged || 0),
            backgroundColor: forModal ? PAL.charged : ctx => barGradient(ctx.chart, PAL.chargedBar),
            borderRadius: 4,
            yAxisID: 'yMoney',
            order: 3,
            maxBarThickness: modalBar,
          },
          {
            label: t('rentals', 'Pronájmy'),
            data: data.map(d => d.pronajmy || 0),
            backgroundColor: forModal ? 'rgba(230,120,23,0.75)' : ctx => barGradient(ctx.chart, 'rgba(230,120,23,0.45)'),
            borderRadius: 4,
            yAxisID: 'yMoney',
            order: 2,
            maxBarThickness: modalBar,
          },
          {
            label: t('incomeTotal', 'Příjmy celkem'),
            data: data.map(d => d.paid),
            backgroundColor: forModal ? PAL.paid : ctx => barGradient(ctx.chart, PAL.paidBar),
            borderRadius: 4,
            yAxisID: 'yMoney',
            order: 4,
            maxBarThickness: modalBar,
          },
        ]
      : [
          {
            label: t('charged', 'Naúčtováno'),
            data: data.map(d => d.charged),
            backgroundColor: forModal
              ? PAL.charged
              : ctx => barGradient(ctx.chart, PAL.chargedBar),
            borderRadius: 4,
            yAxisID: 'yMoney',
            order: 2,
            maxBarThickness: modalBar,
          },
          {
            label: t('paid', 'Zaplaceno'),
            data: data.map(d => d.paid),
            backgroundColor: forModal ? PAL.paid : ctx => barGradient(ctx.chart, PAL.paidBar),
            borderRadius: 4,
            yAxisID: 'yMoney',
            order: 3,
            maxBarThickness: modalBar,
          },
        ];

    return {
      type: 'bar',
      data: {
        labels: data.map(d => d.label),
        datasets: [
          ...moneyDatasets,
          {
            label: t('hours', 'Hodiny'),
            data: data.map(d => d.hours),
            type: 'line',
            borderColor: PAL.brand,
            backgroundColor: forModal ? 'transparent' : PAL.brandLight,
            borderWidth: forModal ? 3 : 2.5,
            pointRadius: modalPoint,
            pointHoverRadius: modalPoint + 3,
            pointBackgroundColor: PAL.brandPoint,
            pointBorderColor: PAL.brand,
            pointBorderWidth: 2,
            fill: !forModal,
            tension: 0.35,
            yAxisID: 'yHours',
            order: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: {
            ...legendBottom,
            labels: { ...legendBottom.labels, pointStyleWidth: 10, padding: 18 },
          },
          datalabels: { display: false },
          tooltip: {
            ...tooltipBase,
            callbacks: {
              label: c => {
                if (c.dataset.yAxisID === 'yHours') return ' ' + hFmt(c.parsed.y);
                return ' ' + kcFmt(c.parsed.y);
              },
            },
          },
        },
        scales: {
          x: {
            ...baseScales.x,
            stacked: false,
            ticks: {
              ...baseScales.x.ticks,
              maxRotation: data.length > 10 ? 45 : 0,
              minRotation: data.length > 10 ? 35 : 0,
              autoSkip: true,
              maxTicksLimit: data.length > 24 ? 24 : data.length > 12 ? 12 : undefined,
            },
          },
          yMoney: {
            ...baseScales.y,
            position: 'left',
            ticks: { ...baseScales.y.ticks, callback: kcShrt },
          },
          yHours: {
            position: 'right',
            beginAtZero: true,
            grid: { drawOnChartArea: false, color: PAL.grid },
            ticks: { color: PAL.brand, font: { size: 11, weight: '600' }, callback: v => v + ' h' },
            border: { display: false },
          },
        },
        ...(forModal ? {} : hoverCursor()),
      },
    };
  }

  function makeFinanceOverviewChart(chartId, data) {
    if (!data?.length) return;
    const builder = forModal => financeOverviewConfig(data, forModal);
    registerChart(chartId, builder(false), builder);
    bindClick(chartId, idx => {
      openDrill(t('monthlyBreakdown', 'Měsíční rozpad'), monthDetail(data[idx]));
    });
  }

  function yearRevenueDetail(y) {
    const months = y.months || [];
    const monthRows = months.map(m => {
      if (m.split) {
        return {
          label: m.label,
          value: kcFmt(m.charged || 0),
          sub: `${t('schoolCharged', 'Škola')} ${kcFmt(m.treningy_charged || 0)} · ${t('rentals', 'Pronájmy')} ${kcFmt(m.pronajmy || 0)} · ${hFmt(m.hours || 0)}`,
        };
      }
      return {
        label: m.label,
        value: kcFmt(m.charged || 0),
        sub: `${t('paid', 'Zaplaceno')} ${kcFmt(m.paid || 0)} · ${hFmt(m.hours || 0)}`,
      };
    });
    const summary = y.split
      ? [
          { label: t('charged', 'Tržby celkem'), value: kcFmt(y.charged), hl: true, tone: 'slate' },
          { label: t('schoolCharged', 'Tenisová škola'), value: kcFmt(y.treningy_charged || 0), tone: 'slate' },
          { label: t('rentals', 'Pronájmy'), value: kcFmt(y.pronajmy || 0), tone: 'dark' },
          { label: t('incomeTotal', 'Příjmy celkem'), value: kcFmt(y.paid), tone: 'profit' },
          { label: t('hours', 'Hodiny'), value: hFmt(y.hours), tone: 'brand' },
        ]
      : [
          { label: t('charged', 'Tržby'), value: kcFmt(y.charged), hl: true, tone: 'slate' },
          { label: t('paid', 'Zaplaceno'), value: kcFmt(y.paid), tone: 'profit' },
          { label: t('hours', 'Hodiny'), value: hFmt(y.hours), tone: 'brand' },
        ];
    const monthsHtml = monthRows.length
      ? `<div class="drill-subsection"><h5 class="drill-subheading">${t('monthsInYear', 'Měsíce v roce')}</h5>
          <div class="drill-year-months">${monthRows.map(r => `
            <div class="drill-year-month">
              <div class="drill-year-month__top"><strong>${r.label}</strong><span>${r.value}</span></div>
              <div class="drill-year-month__sub">${r.sub}</div>
            </div>`).join('')}</div></div>`
      : '';
    return drillWrap('year', drillHeader(y.label) + drillGrid(summary) + monthsHtml);
  }

  function financeByYearConfig(data, forModal) {
    const barThickness = data.length > 10 ? 28 : 40;
    const modalBar = forModal ? Math.min(barThickness + 8, 52) : barThickness;
    const split = !!(data.length && data[0].split);
    const datasets = split
      ? [
          {
            label: t('schoolCharged', 'Tenisová škola'),
            data: data.map(d => d.treningy_charged || 0),
            backgroundColor: forModal ? PAL.charged : ctx => barGradient(ctx.chart, PAL.chargedBar),
            borderRadius: 4,
            maxBarThickness: modalBar,
          },
          {
            label: t('rentals', 'Pronájmy'),
            data: data.map(d => d.pronajmy || 0),
            backgroundColor: forModal ? 'rgba(230,120,23,0.75)' : ctx => barGradient(ctx.chart, 'rgba(230,120,23,0.45)'),
            borderRadius: 4,
            maxBarThickness: modalBar,
          },
          {
            label: t('incomeTotal', 'Příjmy celkem'),
            data: data.map(d => d.paid || 0),
            backgroundColor: forModal ? PAL.paid : ctx => barGradient(ctx.chart, PAL.paidBar),
            borderRadius: 4,
            maxBarThickness: modalBar,
          },
        ]
      : [
          {
            label: t('charged', 'Tržby'),
            data: data.map(d => d.charged || 0),
            backgroundColor: forModal ? PAL.charged : ctx => barGradient(ctx.chart, PAL.chargedBar),
            borderRadius: 4,
            maxBarThickness: modalBar,
          },
          {
            label: t('paid', 'Zaplaceno'),
            data: data.map(d => d.paid || 0),
            backgroundColor: forModal ? PAL.paid : ctx => barGradient(ctx.chart, PAL.paidBar),
            borderRadius: 4,
            maxBarThickness: modalBar,
          },
        ];
    return {
      type: 'bar',
      data: { labels: data.map(d => d.label), datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { ...legendBottom, labels: { ...legendBottom.labels, pointStyleWidth: 10, padding: 18 } },
          datalabels: { display: false },
          tooltip: {
            ...tooltipBase,
            callbacks: { label: c => ' ' + kcFmt(c.parsed.y) },
          },
        },
        scales: {
          x: { ...baseScales.x },
          y: {
            ...baseScales.y,
            ticks: { ...baseScales.y.ticks, callback: kcShrt },
          },
        },
        ...(forModal ? {} : hoverCursor()),
      },
    };
  }

  function makeFinanceByYearChart(chartId, data) {
    if (!data?.length) return;
    const builder = forModal => financeByYearConfig(data, forModal);
    registerChart(chartId, builder(false), builder);
    bindClick(chartId, idx => {
      openDrill(t('yearBreakdown', 'Roční rozpad – škola + pronájmy'), yearRevenueDetail(data[idx]));
    });
  }

  makeFinanceOverviewChart('financeChart', monthlyData);
  makeFinanceOverviewChart('financeYearChart', yearlyData);
  makeFinanceOverviewChart('financeAlltimeChart', alltimeData);
  makeFinanceByYearChart('financeByYearChart', revenueByYearData);

  /* Aktivita 7 dní */
  if (activityData?.length) {
    const activityFillHours = true;
    const activityBuilder = forModal => ({
      type: 'line',
      data: {
        labels: activityData.map(d => d.day_name + '\n' + d.date),
        datasets: [
          {
            label: t('hours', 'Hodiny'), data: activityData.map(d => d.hours),
            borderColor: PAL.brand,
            backgroundColor: forModal ? 'transparent' : PAL.brandLight,
            fill: activityFillHours && !forModal,
            tension: 0.4,
            yAxisID: 'yHours',
            pointRadius: forModal ? 6 : 5,
            pointHoverRadius: 8,
            pointBackgroundColor: PAL.brandPoint,
            pointBorderColor: PAL.brand,
            pointBorderWidth: 2,
            borderWidth: 2.5,
          },
          {
            label: t('charged', 'Naúčtováno'), data: activityData.map(d => d.charged),
            borderColor: PAL.chargedLine,
            backgroundColor: 'transparent',
            fill: false,
            tension: 0.4,
            yAxisID: 'yMoney',
            pointRadius: 4,
            pointBackgroundColor: PAL.brandPoint,
            pointBorderColor: PAL.chargedLine,
            pointBorderWidth: 2,
            borderWidth: 2,
          },
          {
            label: t('paid', 'Zaplaceno'), data: activityData.map(d => d.paid),
            borderColor: PAL.paidLine,
            backgroundColor: 'transparent',
            fill: false,
            tension: 0.4,
            yAxisID: 'yMoney',
            pointRadius: 4,
            pointBackgroundColor: PAL.brandPoint,
            pointBorderColor: PAL.paidLine,
            pointBorderWidth: 2,
            borderWidth: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: legendBottom,
          datalabels: { display: false },
          tooltip: { ...tooltipBase },
        },
        scales: {
          x: baseScales.x,
          yMoney: { ...baseScales.y, position: 'left', ticks: { ...baseScales.y.ticks, callback: kcShrt } },
          yHours: {
            position: 'right',
            beginAtZero: true,
            grid: { drawOnChartArea: false, color: PAL.grid },
            ticks: { color: PAL.brand, callback: v => v + ' h' },
            border: { display: false },
          },
        },
        ...(forModal ? {} : hoverCursor()),
      },
    });
    registerChart('activityChart', activityBuilder(false), activityBuilder);
    bindClick('activityChart', idx => {
      openDrill(t('dailyActivity', 'Denní aktivita'), dayDetail(activityData[idx]));
    });
  }

  /* Účetní grafy */
  function setSumBadge(id, value) {
    const el = document.getElementById(id);
    if (!el) return;
    const fmt = Math.round(value).toLocaleString(JS_LOCALE) + ' ' + t('currency', 'Kč');
    el.textContent = (value >= 0 ? '∑ ' : '∑ −') + (value >= 0 ? fmt : Math.round(Math.abs(value)).toLocaleString(JS_LOCALE) + ' ' + t('currency', 'Kč'));
    el.className = 'acc-sum-badge' + (value < 0 ? ' negative' : '');
  }

  function accBarChart(id, labels, data, focusKey, colorRgb, dense, sourceData) {
    const canvas = document.getElementById(id);
    if (!canvas || !data?.length) return;
    const yScale = moneyYScale(data);
    const barThickness = dense
      ? (data.length > 24 ? 10 : data.length > 12 ? 14 : 20)
      : 48;
    const builder = forModal => ({
      type: 'bar',
      data: {
        labels,
        datasets: [{
          data,
          backgroundColor: forModal
            ? colorRgb.replace(/[\d.]+\)$/, '0.9)')
            : colorRgb,
          hoverBackgroundColor: data.map(v => v < 0 ? PAL.unpaid.replace(/[\d.]+\)$/, '0.85)') : colorRgb.replace(/[\d.]+\)$/, '1)')),
          borderRadius: 6,
          borderSkipped: false,
          maxBarThickness: forModal ? Math.min(barThickness + 8, 56) : barThickness,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: forModal ? false : { duration: 500 },
        plugins: {
          legend: { display: false },
          datalabels: { display: false },
          tooltip: { ...tooltipBase, callbacks: { label: c => ' ' + kcFmt(c.parsed.y) } },
        },
        scales: {
          x: {
            ...baseScales.x,
            ticks: dense ? {
              ...baseScales.x.ticks,
              maxRotation: labels.length > 10 ? 45 : 0,
              minRotation: labels.length > 10 ? 35 : 0,
              autoSkip: true,
              maxTicksLimit: labels.length > 24 ? 24 : labels.length > 12 ? 12 : undefined,
            } : baseScales.x.ticks,
          },
          y: {
            ...baseScales.y,
            ...yScale,
            ticks: { ...baseScales.y.ticks, callback: kcShrt, maxTicksLimit: 7 },
          },
        },
        ...(forModal ? {} : hoverCursor()),
      },
    });
    registerChart(id, builder(false), builder);
    const src = sourceData || accData;
    bindClick(id, idx => {
      if (src?.[idx]) openDrill(metricTitle(focusKey), accMonthDetail(src[idx], focusKey));
    });
  }

  function toCumulative(values) {
    let total = 0;
    return values.map(v => {
      total += v;
      return total;
    });
  }

  function accLineChart(id, labels, data, focusKey, colorRgb, sourceData, opts) {
    const cumulative = opts?.cumulative;
    const canvas = document.getElementById(id);
    if (!canvas || !data?.length) return;
    const yScale = moneyYScale(data);
    const stroke = colorRgb.replace(/[\d.]+\)$/, '1)');
    const fill = colorRgb.replace(/[\d.]+\)$/, '0.12)');
    const pointRadius = data.length > 18 ? 3 : data.length > 12 ? 4 : 5;
    const builder = forModal => ({
      type: 'line',
      data: {
        labels,
        datasets: [{
          data,
          borderColor: stroke,
          backgroundColor: forModal ? 'transparent' : fill,
          pointBackgroundColor: data.map(v => (v < 0 ? '#ffffff' : '#ffffff')),
          pointBorderColor: data.map(v => (v < 0 ? PAL.danger : stroke)),
          pointBorderWidth: 2,
          pointRadius: forModal ? pointRadius + 1 : pointRadius,
          pointHoverRadius: pointRadius + 3,
          borderWidth: forModal ? 3 : 2.5,
          fill: !forModal,
          tension: cumulative ? 0.15 : 0.35,
          spanGaps: false,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: forModal ? false : { duration: 500 },
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          datalabels: { display: false },
          tooltip: {
            ...tooltipBase,
            callbacks: {
              label: c => cumulative
                ? ' ' + t('cumulative', 'Kumulativně:') + ' ' + kcFmt(c.parsed.y)
                : ' ' + kcFmt(c.parsed.y),
            },
          },
        },
        scales: {
          x: {
            ...baseScales.x,
            ticks: {
              ...baseScales.x.ticks,
              maxRotation: labels.length > 10 ? 45 : 0,
              minRotation: labels.length > 10 ? 35 : 0,
              autoSkip: true,
              maxTicksLimit: labels.length > 24 ? 24 : labels.length > 12 ? 12 : undefined,
            },
          },
          y: {
            ...baseScales.y,
            ...yScale,
            ticks: { ...baseScales.y.ticks, callback: kcShrt, maxTicksLimit: 7 },
          },
        },
        ...(forModal ? {} : hoverCursor()),
      },
    });
    registerChart(id, builder(false), builder);
    const src = sourceData || accData;
    bindClick(id, idx => {
      if (src?.[idx]) openDrill(metricTitle(focusKey), accMonthDetail(src[idx], focusKey));
    });
  }

  function setupAccountingCharts(data, chartIds, sumIds, lineKeys, cumulativeLine) {
    if (!data?.length) return;
    const labels = data.map(d => d.label);
    const cfVals = data.map(d => d.cashflow ?? ((d.paid || 0) - (d.trener_paid || 0) - (d.other_costs || 0)));
    const gpVals = data.map(d => d.gross_profit);
    const npVals = data.map(d => d.net_profit !== undefined
      ? d.net_profit
      : ((d.paid || 0) - (d.trener_paid || 0) - (d.other_costs || 0)));
    const tpVals = data.map(d => d.trener_paid || 0);
    const sum = arr => arr.reduce((a, b) => a + b, 0);
    const dense = data.length > 6;
    const lineSet = new Set(lineKeys || []);

    if (sumIds.cashflow) setSumBadge(sumIds.cashflow, sum(cfVals));
    if (sumIds.gross) setSumBadge(sumIds.gross, sum(gpVals));
    if (sumIds.net) setSumBadge(sumIds.net, sum(npVals));
    if (sumIds.trener) setSumBadge(sumIds.trener, sum(tpVals));

    const profitGreen = isDarkMode() ? 'rgba(110,231,183,0.85)' : 'rgba(22,163,74,0.85)';
    const costRed = isDarkMode() ? 'rgba(252,165,165,0.85)' : 'rgba(201,42,42,0.78)';

    if (chartIds.cashflow) accBarChart(chartIds.cashflow, labels, cfVals, 'cashflow', PAL.slateBar, dense, data);
    if (chartIds.gross) accBarChart(chartIds.gross, labels, gpVals, 'gross_profit', profitGreen, dense, data);
    if (chartIds.net) {
      if (lineSet.has('net')) {
        const chartData = cumulativeLine ? toCumulative(npVals) : npVals;
        accLineChart(chartIds.net, labels, chartData, 'net_profit', profitGreen, data, { cumulative: cumulativeLine });
      } else accBarChart(chartIds.net, labels, npVals, 'net_profit', profitGreen, dense, data);
    }
    if (chartIds.trener) {
      if (lineSet.has('trener')) {
        const chartData = cumulativeLine ? toCumulative(tpVals) : tpVals;
        accLineChart(chartIds.trener, labels, chartData, 'trener_paid', costRed, data, { cumulative: cumulativeLine });
      } else accBarChart(chartIds.trener, labels, tpVals, 'trener_paid', costRed, dense, data);
    }
  }

  function initAccountingCharts() {
    setupAccountingCharts(accData, {
      cashflow: 'accCashflowChart',
      gross: 'accGrossChart',
      net: 'accNetProfitChart',
      trener: 'accTrenerPaidChart',
    }, {
      cashflow: 'sum-cashflow',
      gross: 'sum-gross',
      net: 'sum-net',
      trener: 'sum-trener',
    });
    setupAccountingCharts(accYearData, {
      cashflow: 'accYearCashflowChart',
      gross: 'accYearGrossChart',
      net: 'accYearNetProfitChart',
      trener: 'accYearTrenerPaidChart',
    }, {
      cashflow: 'sum-year-cashflow',
      gross: 'sum-year-gross',
      net: 'sum-year-net',
      trener: 'sum-year-trener',
    });
    setupAccountingCharts(accAlltimeData, {
      net: 'accAlltimeNetProfitChart',
      trener: 'accAlltimeTrenerPaidChart',
    }, {
      net: 'sum-alltime-net',
      trener: 'sum-alltime-trener',
    }, ['net', 'trener'], true);
  }

  initAccountingCharts();
  setTimeout(refreshCharts, 120);

  function nakladyDayDetail(d) {
    const items = d.items || [];
    const rows = items.length
      ? items.map(it => ({
          label: it.label,
          value: kcFmt(it.castka),
          tone: 'slate',
        }))
      : [{ label: t('noItems', 'Žádné položky'), value: '—', tone: 'neutral' }];

    const notes = items.filter(it => it.poznamka).map(it =>
      `<div class="drill-note"><span>${it.label}:</span> ${it.poznamka}</div>`
    ).join('');

    const period = [d.label, d.weekday].filter(Boolean).join(' · ');

    return drillWrap('naklady', `
      ${drillHeader(period)}
      <div class="drill-hero drill-hero--danger">
        <span class="drill-hero-label">Celkem za den</span>
        <span class="drill-hero-value">${kcFmt(d.total || 0)}</span>
      </div>
      <div class="drill-subsection">
        <h5 class="drill-subheading">Položky nákladů</h5>
        ${drillGrid(rows.map(r => ({ ...r, tone: 'cost' })), 'drill-grid--stats')}
      </div>
      ${notes ? `<div class="drill-subsection drill-subsection--notes">${notes}</div>` : ''}
      ${d.datum_value ? `<a class="drill-link" href="${nakladySectionUrl}?datum=${d.datum_value}">Upravit náklady za den →</a>` : ''}
    `);
  }

  function nakladyMonthDetail(d) {
    if (d.days?.length) {
      const dayBlocks = d.days.map(day => `
        <div class="drill-subsection">
          <h5 class="drill-subheading">
            <a class="naklady-edit-link" href="${nakladySectionUrl}?datum=${day.datum_value}">${day.label}${day.weekday ? ' (' + day.weekday + ')' : ''}</a>
            · ${kcFmt(day.total)}
          </h5>
          ${drillGrid((day.items || []).map(it => ({
            label: it.label,
            value: kcFmt(it.castka),
            tone: 'cost',
          })), 'drill-grid--stats')}
        </div>
      `).join('');

      return drillWrap('naklady', `
        ${drillHeader(d.label)}
        <div class="drill-hero drill-hero--danger">
          <span class="drill-hero-label">Celkem za měsíc</span>
          <span class="drill-hero-value">${kcFmt(d.total || 0)}</span>
        </div>
        ${dayBlocks}
      `);
    }
    return nakladyDayDetail(d);
  }

  function nakladyBarChart(id, data, colorRgb, onClickDetail) {
    const canvas = document.getElementById(id);
    if (!canvas || !data?.length) return;
    const labels = data.map(d => d.label);
    const vals = data.map(d => d.total);
    const dense = data.length > 6;
    const barThickness = dense
      ? (data.length > 24 ? 10 : data.length > 12 ? 14 : 20)
      : 48;
    const builder = forModal => ({
      type: 'bar',
      data: {
        labels,
        datasets: [{
          data: vals,
          backgroundColor: forModal
            ? colorRgb.replace(/[\d.]+\)$/, '0.9)')
            : colorRgb,
          hoverBackgroundColor: colorRgb.replace(/[\d.]+\)$/, '1)'),
          borderRadius: 6,
          borderSkipped: false,
          maxBarThickness: forModal ? Math.min(barThickness + 8, 56) : barThickness,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: forModal ? false : { duration: 500 },
        plugins: {
          legend: { display: false },
          datalabels: { display: false },
          tooltip: {
            ...tooltipBase,
            callbacks: {
              label: c => ' ' + kcFmt(c.parsed.y),
              afterBody: tooltipItems => {
                const idx = tooltipItems?.[0]?.dataIndex;
                const point = idx !== undefined ? data[idx] : null;
                if (!point) return [];
                if (point.days?.length) {
                  return point.days.map(day => ` ${day.label}: ${kcFmt(day.total)}`);
                }
                if (point.items?.length) {
                  return point.items.map(it => ` ${it.label}: ${kcFmt(it.castka)}`);
                }
                return [];
              },
            },
          },
        },
        scales: {
          x: {
            ...baseScales.x,
            ticks: {
              ...baseScales.x.ticks,
              maxRotation: labels.length > 8 ? 45 : 0,
              minRotation: labels.length > 8 ? 35 : 0,
              autoSkip: true,
              maxTicksLimit: labels.length > 24 ? 24 : labels.length > 12 ? 12 : undefined,
            },
          },
          y: { ...baseScales.y, ticks: { ...baseScales.y.ticks, callback: kcShrt } },
        },
        ...(forModal ? {} : hoverCursor()),
      },
    });
    registerChart(id, builder(false), builder);
    bindClick(id, idx => {
      if (!data[idx]) return;
      const detailFn = onClickDetail || nakladyMonthDetail;
      openDrill(t('otherCosts', 'Ostatní náklady'), detailFn(data[idx]));
    });
  }

  function setupNakladyCharts() {
    if (nakladyChartData?.length) {
      nakladyBarChart('nakladyChart', nakladyChartData, 'rgba(201,42,42,0.75)', nakladyMonthDetail);
    }
    if (nakladyAlltimeChartData?.length) {
      nakladyBarChart('nakladyAlltimeChart', nakladyAlltimeChartData, PAL.slateBar, nakladyMonthDetail);
      const sum = nakladyAlltimeChartData.reduce((a, d) => a + (d.total || 0), 0);
      setSumBadge('sum-naklady-alltime', sum);
    }
  }

  setupNakladyCharts();

  /* ── Kalendář nákladů ── */
  /* Date picker nákladů: sdílený TsDatePicker (ts-date-picker.js) */

  /* Profil hráčů – věk / pohlaví / úroveň */
  function registerProfilDoughnut(canvasId, data, colors, title) {
    if (!data?.labels?.length || !data.values?.some(v => v > 0)) return;
    const labels = [];
    const values = [];
    data.labels.forEach((label, i) => {
      const v = data.values[i] || 0;
      if (v > 0) {
        labels.push(label);
        values.push(v);
      }
    });
    if (!labels.length) return;
    const total = values.reduce((a, b) => a + b, 0) || 1;
    const builder = forModal => ({
      type: 'doughnut',
      data: {
        labels,
        datasets: [{
          data: values,
          backgroundColor: colors.slice(0, labels.length),
          borderWidth: 2,
          borderColor: PAL.surface,
          hoverOffset: forModal ? 12 : 8,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: forModal ? '58%' : '64%',
        plugins: {
          legend: { ...legendBottom, labels: { ...legendBottom.labels, font: { size: 10 } } },
          tooltip: { ...tooltipBase },
          datalabels: {
            color: '#fff',
            font: { weight: 'bold', size: 10 },
            formatter: (v, ctx) => {
              const s = ctx.dataset.data.reduce((a, b) => a + b, 0);
              const r = Math.round((v / s) * 100);
              return r > 7 ? r + '%' : '';
            },
          },
        },
        ...(forModal ? {} : hoverCursor()),
      },
    });
    registerChart(canvasId, builder(false), builder);
    bindClick(canvasId, idx => {
      const label = labels[idx];
      const value = values[idx] || 0;
      openDrill(title, drillWrap('hrac', drillHeader(label) + drillGrid([
        { label: t('playersCount', 'Počet hráčů'), value: String(value), hl: true, tone: 'slate' },
        { label: t('share', 'Podíl'), value: Math.round((value / total) * 100) + ' %', tone: 'neutral' },
      ])));
    });
  }

  const profilPalette = isDarkMode()
    ? [
        'rgba(230,120,23,0.9)', 'rgba(147,197,253,0.85)', 'rgba(110,231,183,0.7)',
        'rgba(251,191,36,0.75)', 'rgba(244,114,182,0.7)', 'rgba(167,139,250,0.75)',
        'rgba(148,163,184,0.55)', 'rgba(100,116,139,0.45)',
      ]
    : [
        'rgba(230,120,23,0.9)', 'rgba(59,130,246,0.75)', 'rgba(16,185,129,0.7)',
        'rgba(245,158,11,0.75)', 'rgba(236,72,153,0.65)', 'rgba(139,92,246,0.7)',
        'rgba(100,116,139,0.55)', 'rgba(148,163,184,0.4)',
      ];

  registerProfilDoughnut('hraciAgeChart', hraciAgeData, profilPalette, t('ageGroups', 'Věkové skupiny'));
  registerProfilDoughnut(
    'hraciPohlaviChart',
    hraciPohlaviData,
    [profilPalette[1], profilPalette[4], profilPalette[6], profilPalette[7]],
    t('gender', 'Pohlaví')
  );
  registerProfilDoughnut(
    'hraciUrovenChart',
    hraciUrovenData,
    [profilPalette[2], profilPalette[0], profilPalette[3], profilPalette[6]],
    t('tennisLevel', 'Úroveň tenisu')
  );
  registerProfilDoughnut(
    'hraciEngageChart',
    hraciEngageData,
    [profilPalette[6], profilPalette[1], profilPalette[2], profilPalette[0], profilPalette[3]],
    t('weeklyIntensity', 'Intenzita (h / týden)')
  );
  registerProfilDoughnut(
    'hraciFreqChart',
    hraciFreqData,
    [profilPalette[1], profilPalette[2], profilPalette[0], profilPalette[5]],
    t('monthFrequency', 'Frekvence (tento měsíc)')
  );

  /* Doughnut – rovnováha */
  const dBal = kpiVal('total_debt_value', 'data-dluhy') || Math.abs(parseVal('data-dluhy'));
  const pBal = kpiVal('total_surplus_value', 'data-prebytky');
  if (dBal > 0 || pBal > 0) {
    const balanceBuilder = forModal => ({
      type: 'doughnut',
      data: {
        labels: [t('debts', 'Dluhy'), t('surpluses', 'Přebytky')],
        datasets: [{
          data: [dBal, pBal],
          backgroundColor: [PAL.unpaid, isDarkMode() ? PAL.mintBar : PAL.slateBarSoft],
          borderWidth: 3,
          borderColor: PAL.surface,
          hoverOffset: forModal ? 12 : 8,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: forModal ? '62%' : '68%',
        plugins: {
          legend: legendBottom,
          tooltip: { ...tooltipBase },
          datalabels: {
            color: '#fff', font: { weight: 'bold', size: 11 },
            formatter: (v, ctx) => {
              const s = ctx.dataset.data.reduce((a, b) => a + b, 0);
              return s > 0 ? Math.round((v / s) * 100) + '%' : '';
            },
          },
        },
        ...(forModal ? {} : hoverCursor()),
      },
    });
    registerChart('balanceChart', balanceBuilder(false), balanceBuilder);
    bindClick('balanceChart', idx => {
      const labels = [t('playerDebts', 'Dluhy hráčů'), t('playerSurpluses', 'Přebytky hráčů')];
      const vals = [dBal, pBal];
      openDrill(t('balanceDistribution', 'Rozložení bilance'), drillWrap('balance', drillHeader(labels[idx]) + drillGrid([
        { label: labels[idx], value: kcFmt(vals[idx]), hl: true, neg: idx === 0, tone: idx === 0 ? 'cost' : 'profit' },
        { label: t('share', 'Podíl'), value: Math.round(vals[idx] / (dBal + pBal) * 100) + ' %', tone: 'neutral' },
      ])));
    });
  }

  /* Dlužníci doughnut */
  if (debtorsChartData?.labels?.length) {
    const paidShades = isDarkMode()
      ? ['rgba(110,231,183,0.55)', 'rgba(110,231,183,0.38)', 'rgba(110,231,183,0.24)', 'rgba(110,231,183,0.16)']
      : ['rgba(26,29,22,0.55)', 'rgba(26,29,22,0.4)', 'rgba(26,29,22,0.3)', 'rgba(26,29,22,0.2)'];
    const slateDoughnut = isDarkMode()
      ? ['rgba(147,197,253,0.82)', 'rgba(147,197,253,0.66)', 'rgba(147,197,253,0.5)']
      : ['rgba(100,116,139,0.8)', 'rgba(100,116,139,0.65)', 'rgba(100,116,139,0.5)'];
    const doughnutColors = [
      'rgba(201,42,42,0.9)', 'rgba(201,42,42,0.75)', 'rgba(201,42,42,0.6)',
      ...slateDoughnut,
      ...paidShades,
    ];
    const debtorsBuilder = forModal => ({
      type: 'doughnut',
      data: {
        labels: debtorsChartData.labels,
        datasets: [{
          data: debtorsChartData.values,
          backgroundColor: doughnutColors,
          borderWidth: 2, borderColor: PAL.surface, hoverOffset: forModal ? 12 : 10,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: forModal ? '54%' : '58%',
        plugins: {
          legend: { ...legendBottom, labels: { ...legendBottom.labels, font: { size: 10 } } },
          tooltip: { ...tooltipBase },
          datalabels: {
            color: '#fff', font: { weight: 'bold', size: 10 },
            formatter: (v, ctx) => {
              const s = ctx.dataset.data.reduce((a, b) => a + b, 0);
              const r = Math.round((v / s) * 100);
              return r > 6 ? r + '%' : '';
            },
          },
        },
        ...(forModal ? {} : hoverCursor()),
      },
    });
    registerChart('debtorsChart', debtorsBuilder(false), debtorsBuilder);
    bindClick('debtorsChart', idx => {
      const name = debtorsChartData.labels[idx];
      const amount = debtorsChartData.values[idx];
      const person = debtorsList.find(d => d.name === name) || {};
      openDrill(name, personDetail(name, amount, person.url, {
        variant: 'hrac',
        amountLabel: 'Dluh',
        amountDisplay: '−' + kcFmt(amount),
        subtitle: t('playerDebtor', 'Hráč – dlužník'),
        linkLabel: t('playerProfile', 'Profil hráče'),
        stats: [{ label: t('shareOfTotalDebts', 'Podíl z celkových dluhů'), value: Math.round(amount / debtorsChartData.values.reduce((a, b) => a + b, 0) * 100) + ' %' }],
      }));
    });
  }

  /* Trenéři k vyplacení */
  if (trenerChartData?.labels?.length) {
    const tPaidShades = isDarkMode()
      ? ['rgba(110,231,183,0.48)', 'rgba(110,231,183,0.32)']
      : ['rgba(26,29,22,0.5)', 'rgba(26,29,22,0.35)'];
    const tSlateDoughnut = isDarkMode()
      ? ['rgba(147,197,253,0.82)', 'rgba(147,197,253,0.66)', 'rgba(147,197,253,0.5)']
      : ['rgba(100,116,139,0.8)', 'rgba(100,116,139,0.65)', 'rgba(100,116,139,0.5)'];
    const tColors = [
      'rgba(230,120,23,0.9)', 'rgba(230,120,23,0.75)', 'rgba(230,120,23,0.6)',
      ...tSlateDoughnut,
      ...tPaidShades,
    ];
    const trenerBuilder = forModal => ({
      type: 'doughnut',
      data: {
        labels: trenerChartData.labels,
        datasets: [{
          data: trenerChartData.values,
          backgroundColor: tColors,
          borderWidth: 2, borderColor: PAL.surface, hoverOffset: forModal ? 12 : 10,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: forModal ? '54%' : '58%',
        plugins: {
          legend: { ...legendBottom, labels: { ...legendBottom.labels, font: { size: 10 } } },
          tooltip: { ...tooltipBase },
          datalabels: {
            color: '#fff', font: { weight: 'bold', size: 10 },
            formatter: (v, ctx) => {
              const s = ctx.dataset.data.reduce((a, b) => a + b, 0);
              const r = Math.round((v / s) * 100);
              return r > 6 ? r + '%' : '';
            },
          },
        },
        ...(forModal ? {} : hoverCursor()),
      },
    });
    registerChart('trenerChart', trenerBuilder(false), trenerBuilder);
    bindClick('trenerChart', idx => {
      const name = trenerChartData.labels[idx];
      const amount = trenerChartData.values[idx];
      const person = treneriList.find(t => t.name === name) || {};
      openDrill(name, personDetail(name, amount, person.url, {
        variant: 'trener',
        amountLabel: t('toPayCoaches', 'K vyplacení'),
        subtitle: t('coach', 'Trenér'),
        linkLabel: t('coachDetail', 'Detail trenéra'),
        stats: [
          { label: t('hoursMonth', 'Hodiny (měsíc)'), value: person.hours_month || '—' },
          { label: t('claimMonth', 'Nárok (měsíc)'), value: person.earned_month || '—' },
        ],
      }));
    });
  }

  /* Hodiny trenérů – horizontální */
  if (trenerHoursData?.labels?.length) {
    const maxH = Math.max(...trenerHoursData.values, 1);
    const trenerHoursBuilder = forModal => ({
      type: 'bar',
      data: {
        labels: trenerHoursData.labels,
        datasets: [{
          data: trenerHoursData.values,
          backgroundColor: trenerHoursData.values.map((v, i) => {
            const intensity = 0.45 + (v / maxH) * 0.55;
            return i === 0
              ? rgbaFromHex(PAL.brand, intensity, `rgba(230,120,23,${intensity})`)
              : (isDarkMode()
                ? `rgba(147,197,253,${intensity * 0.85})`
                : `rgba(100,116,139,${intensity * 0.85})`);
          }),
          borderRadius: 6,
          borderSkipped: false,
          maxBarThickness: forModal ? 28 : 22,
          clip: false,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: 'y',
        animation: forModal ? false : { duration: 500 },
        layout: { padding: { right: forModal ? 56 : 48 } },
        plugins: {
          legend: { display: false },
          datalabels: {
            display: true,
            clip: false,
            anchor: 'end',
            align: 'right',
            offset: 6,
            formatter: v => hFmt(v),
            font: { weight: '600', size: forModal ? 12 : 11 },
            color: PAL.label,
          },
          tooltip: { ...tooltipBase, callbacks: { label: c => ' ' + hFmt(c.parsed.x) } },
        },
        scales: {
          x: {
            ...baseScales.y,
            suggestedMax: maxH * 1.18,
            ticks: { ...baseScales.y.ticks, callback: v => v + ' h' },
          },
          y: { ...baseScales.x, grid: { display: false } },
        },
        ...(forModal ? {} : hoverCursor()),
      },
    });
    registerChart('trenerHoursChart', trenerHoursBuilder(false), trenerHoursBuilder);
    bindClick('trenerHoursChart', idx => {
      const name = trenerHoursData.labels[idx];
      const hours = trenerHoursData.values[idx];
      const person = treneriList.find(t => t.name === name) || {};
      openDrill(name, personDetail(name, hours, person.url, {
        variant: 'trener',
        amountLabel: t('hoursMonth', 'Hodiny (měsíc)'),
        amountDisplay: hFmt(hours),
        subtitle: t('coachActivity', 'Trenér – aktivita'),
        linkLabel: t('coachDetail', 'Detail trenéra'),
        stats: [
          { label: t('hoursPlayed', 'Odehrané hodiny') + ' ' + t('total', 'celkem'), value: person.hours_total || '—' },
          { label: t('trainingsMonth', 'Tréninků (měsíc)'), value: person.trainings_month ?? '—' },
          { label: t('claimMonth', 'Nárok (měsíc)'), value: person.earned_month || '—' },
          { label: t('toPayCoaches', 'K vyplacení'), value: person.balance || '—' },
        ],
        bars: [
          { label: t('thisMonth', 'Tento měsíc'), value: hours, display: hFmt(hours) },
          { label: t('total', 'Celkem'), value: parseFloat((person.hours_total || '0').replace(/[^\d.]/g, '')) || 0, display: person.hours_total || '—' },
        ],
      }));
    });
  }

  /* ── Klikatelné stat karty u finance ── */
  document.querySelectorAll('.comparison-stat--clickable').forEach(el => {
    el.addEventListener('click', () => {
      document.querySelectorAll('.comparison-stat--clickable').forEach(s => s.classList.remove('is-active'));
      el.classList.add('is-active');

      const idx = parseInt(el.dataset.compIdx || '0', 10);
      const label = el.querySelector('.comparison-stat-label')?.textContent || '';
      const valueText = el.querySelector('.comparison-stat-value')?.textContent || '0';
      const value = parseFloat(valueText.replace(/[^\d.-]/g, '').replace(/\s/g, '')) || 0;
      const canvas = el.closest('.panel-grid')?.querySelector('canvas');
      const chartId = canvas?.id;
      const ctx = chartId === 'comparisonChart' ? t('month', 'měsíc') : t('total', 'celkem');
      const base = ctx === t('month', 'měsíc') ? nauctovanoMonth : totalCharged;
      const chartValues = ctx === t('month', 'měsíc') ? monthComparisonValues : totalComparisonValues;
      const drillValue = chartValues[idx] ?? Math.abs(value);

      if (chartId && chartRegistry[chartId] && idx < 3) {
        const chart = chartRegistry[chartId];
        chart.setActiveElements([{ datasetIndex: 0, index: idx }]);
        chart.tooltip?.setActiveElements([{ datasetIndex: 0, index: idx }]);
        chart.update();
      }

      openDrill(label, comparisonDetail(label, drillValue, ctx, base));
    });
  });

  /* ── Navigace sekcí (URL cesty, ne hash) ── */
  const navItems = document.querySelectorAll('.sidebar-nav-item');
  const sidebar = document.getElementById('analytikaSidebar');
  const menuToggle = document.getElementById('analytikaMenuToggle');
  const sidebarClose = document.getElementById('analytikaSidebarClose');
  const analytikaApp = document.getElementById('analytikaApp');

  function syncSidebarLayout() {
    if (!analytikaApp) return;
    const header = document.getElementById('header');
    const top = header ? Math.max(0, header.getBoundingClientRect().bottom) : 72;
    analytikaApp.style.setProperty('--ana-top-offset', `${top}px`);
  }
  syncSidebarLayout();
  window.addEventListener('resize', syncSidebarLayout);
  window.addEventListener('scroll', syncSidebarLayout, { passive: true });

  /* Staré odkazy #sekce → přesměrovat na /admin/analytika/sekce/ */
  const legacyHash = location.hash.replace('#', '');
  if (legacyHash && analytikaSectionUrls[legacyHash]) {
    const target = analytikaSectionUrls[legacyHash] + location.search;
    if (!location.pathname.endsWith('/' + legacyHash + '/')) {
      location.replace(target);
    }
  }

  let overlay = document.querySelector('.analytika-sidebar-overlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.className = 'analytika-sidebar-overlay';
    document.querySelector('.analytika-app')?.appendChild(overlay);
  }
  function closeSidebar() {
    sidebar?.classList.remove('open');
    overlay.classList.remove('visible');
    document.body.classList.remove('analytika-sidebar-open');
  }
  function openSidebar() {
    sidebar?.classList.add('open');
    overlay.classList.add('visible');
    document.body.classList.add('analytika-sidebar-open');
  }
  navItems.forEach(link => link.addEventListener('click', () => closeSidebar()));
  menuToggle?.addEventListener('click', () => {
    sidebar?.classList.contains('open') ? closeSidebar() : openSidebar();
  });
  sidebarClose?.addEventListener('click', closeSidebar);
  overlay.addEventListener('click', closeSidebar);
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeSidebar();
  });

  setTimeout(refreshCharts, 120);

  /* Export přehledu – přepínání URL podle období */
  (function initExportControls() {
    const select = document.getElementById('analytikaExportPeriod');
    const pdfLink = document.getElementById('analytikaExportPdf');
    const xlsxLink = document.getElementById('analytikaExportXlsx');
    const urls = safeLoadJson('analytika-export-urls');
    if (!select || !pdfLink || !xlsxLink || !urls) return;
    function syncLinks() {
      const period = select.value;
      const entry = urls[period];
      if (!entry) return;
      pdfLink.href = entry.pdf;
      xlsxLink.href = entry.xlsx;
    }
    select.addEventListener('change', syncLinks);
    syncLinks();
  })();

  document.querySelectorAll('.data-table-row[data-href]').forEach(row => {
    row.addEventListener('click', e => {
      if (e.target.closest('a')) return;
      window.location.href = row.dataset.href;
    });
  });

})();
