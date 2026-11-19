(function () {
  "use strict";

  var script = document.currentScript;
  if (!script) return;

  var quickAddUrl = (script.getAttribute("data-quick-add-url") || "").trim();
  var moveUrl = (script.getAttribute("data-move-url") || "").trim();
  var addUrl = (script.getAttribute("data-add-url") || "").trim();
  var stalySaveUrl = (script.getAttribute("data-staly-save-url") || "").trim();
  var stalyDeleteUrlTpl = (script.getAttribute("data-staly-delete-url") || "").trim();
  var materializeUrl = (script.getAttribute("data-materialize-url") || "").trim();
  var skipUrl = (script.getAttribute("data-skip-url") || "").trim();
  var deleteUrl = (script.getAttribute("data-delete-url") || "").trim();
  var cenaUrl = (script.getAttribute("data-cena-url") || "").trim();
  var rozvrhMode = (script.getAttribute("data-rozvrh") || "aktualni").trim();
  var isStaly = rozvrhMode === "staly";
  var isPredpokladany = rozvrhMode === "predpokladany";
  var isPronajem = (script.getAttribute("data-kind") || "").trim() === "pronajem";
  var trener = (script.getAttribute("data-trener") || "").trim();
  var holdMs = parseInt(script.getAttribute("data-hold-ms") || "450", 10);
  if (!Number.isFinite(holdMs) || holdMs < 150) holdMs = 450;
  if (holdMs > 1200) holdMs = 450;
  // Mobil: hint až po klidu (scroll nestihne blikat), pak nabíjecí efekt
  var TOUCH_HINT_DELAY_MS = 320;
  var TOUCH_CHARGE_MS = 320;
  var TOUCH_SCROLL_CANCEL_PX = 8;

  var MOVE_CANCEL_PX = 14;
  var SCROLL_KEY = "kalendar-sched-scroll";
  var DAY_INDEX_KEY = "kalendar-day-index";
  var STALY_LAST_KEY = "kalendar-staly-last";
  var STALY_CONTINUE_KEY = "kalendar-staly-continue";
  var DOW_LABELS = ["po", "út", "st", "čt", "pá", "so", "ne"];
  var MOBILE_MQ = window.matchMedia(
    "(max-width: 820px), (max-height: 500px) and (max-width: 1024px)"
  );
  var active = null;
  var pendingSlot = null;
  var suppressEventClick = false;
  var mobileDayIndex = 0;
  var edgeDragAt = 0;
  var weekEdgeGesture = null;
  var pagerScrollTimer = null;
  var autoScrollRaf = null;
  var touchDragBound = false;
  var pagerAnimRaf = null;
  var pagerAnimGen = 0;
  var lockedPagerScrollLeft = null;

  var optionsEl = document.getElementById("qa-options");
  var options = { trainers: [], formats: [], sezony: [], kurty: [], delky: [], players: [], defaults: {} };
  try {
    if (optionsEl && optionsEl.textContent) {
      options = JSON.parse(optionsEl.textContent) || options;
    }
  } catch (e) {}

  var overlay = document.getElementById("qa-overlay");
  var form = document.getElementById("qa-form");
  var whenEl = document.getElementById("qa-when");
  var stalyNoteEl = document.getElementById("qa-staly-note");
  var titleEl = document.getElementById("qa-title");
  var errorEl = document.getElementById("qa-error");
  var trenerSel = document.getElementById("qa-trener");
  var formatSel = document.getElementById("qa-format");
  var delkaInput = document.getElementById("qa-delka");
  var delkaChips = document.getElementById("qa-delka-chips");
  var delkaField = document.getElementById("qa-delka-field");
  var kurtSel = document.getElementById("qa-kurt");
  var sezonaSel = document.getElementById("qa-sezona");
  var pronajemSezonaSel = document.getElementById("qa-pronajem-sezona");
  var hraciRows = document.getElementById("qa-hraci-rows");
  var hraciAddBtn = document.getElementById("qa-hraci-add");
  var rezervujiciInput = document.getElementById("qa-rezervujici");
  var cenaInput = document.getElementById("qa-cena");
  var cenaChips = document.getElementById("qa-cena-chips");
  var cenaHint = document.getElementById("qa-cena-hint");
  var pendingPoznamka = "";
  var cenaManual = false;
  var slotIdInput = document.getElementById("qa-slot-id");
  var dowInput = document.getElementById("qa-dow");
  var ghostSlotIdInput = document.getElementById("qa-ghost-slot-id");
  var predpokladanyIdInput = document.getElementById("qa-predpokladany-id");
  var saveBtn = overlay && overlay.querySelector("[data-qa-save]");
  var saveNextBtn = overlay && overlay.querySelector("[data-qa-save-next]");
  var deleteBtn = overlay && overlay.querySelector("[data-qa-delete]");
  var cancelBtns = overlay ? overlay.querySelectorAll("[data-qa-cancel]") : [];
  var materializeBtn = document.getElementById("sched-materialize-btn");

  function getSchedScrollEl() {
    return document.querySelector(".sched-scroll");
  }

  function getDaysPager() {
    return document.getElementById("sched-days-pager");
  }

  function getDayStrip() {
    return document.getElementById("sched-day-strip");
  }

  function isMobileDayPager() {
    var pager = getDaysPager();
    if (!MOBILE_MQ.matches || !pager) return false;
    return getPagerDayEls().length > 0;
  }

  function getPagerDayEls() {
    var pager = getDaysPager();
    if (!pager) return [];
    return Array.prototype.filter.call(pager.children, function (el) {
      return el.classList && el.classList.contains("sched-day");
    });
  }

  function measurePagerPageWidth() {
    var pager = getDaysPager();
    return pager ? Math.max(0, Math.round(pager.clientWidth)) : 0;
  }

  function sizePagerDays() {
    var pager = getDaysPager();
    var days = getPagerDayEls();
    if (!pager || !days.length) return 0;
    if (!MOBILE_MQ.matches) {
      days.forEach(function (day) {
        day.style.flex = "";
        day.style.width = "";
        day.style.minWidth = "";
        day.style.maxWidth = "";
        day.classList.remove("is-day-active", "is-day-peek", "is-day-from-left", "is-day-from-right");
        var body = day.querySelector(".sched-day-body");
        if (body) {
          body.style.transform = "";
          body.style.opacity = "";
        }
      });
      return 0;
    }
    var w = measurePagerPageWidth();
    if (w < 1) return 0;
    days.forEach(function (day) {
      day.style.boxSizing = "border-box";
      day.style.flex = "0 0 " + w + "px";
      day.style.width = w + "px";
      day.style.minWidth = w + "px";
      day.style.maxWidth = w + "px";
      day.style.transform = "";
      day.style.opacity = "";
      day.classList.remove("is-day-peek", "is-day-from-left", "is-day-from-right");
      var body = day.querySelector(".sched-day-body");
      if (body) {
        body.style.transform = "";
        body.style.opacity = "";
      }
    });
    return w;
  }

  function pagerScrollLeftForIndex(index) {
    var days = getPagerDayEls();
    if (!days.length) return 0;
    index = Math.max(0, Math.min(days.length - 1, index | 0));
    var w = measurePagerPageWidth() || 1;
    if (days[0] && days[0].offsetWidth > 0) w = days[0].offsetWidth;
    return Math.round(w * index);
  }

  function dayProgressFromPagerScroll() {
    var pager = getDaysPager();
    var days = getPagerDayEls();
    if (!pager || !days.length) return 0;
    var w = measurePagerPageWidth() || 1;
    if (days[0] && days[0].offsetWidth > 0) w = days[0].offsetWidth;
    return pager.scrollLeft / Math.max(1, w);
  }

  function clearDayPageEffects() {
    getPagerDayEls().forEach(function (day) {
      day.classList.remove("is-day-active", "is-day-peek", "is-day-from-left", "is-day-from-right");
      day.style.transform = "";
      day.style.opacity = "";
      var body = day.querySelector(".sched-day-body");
      if (body) {
        body.style.transform = "";
        body.style.opacity = "";
      }
    });
  }

  function updateDayPageEffects() {
    // Žádné opacity/transform – ty dělaly posun slotů a „stín“ při swipe.
    clearDayPageEffects();
  }

  function setPagerSnapEnabled(on) {
    var pager = getDaysPager();
    if (!pager) return;
    if (on) {
      pager.classList.remove("is-paging");
      pager.style.scrollSnapType = "";
    } else {
      pager.classList.add("is-paging");
      pager.style.scrollSnapType = "none";
    }
  }

  function realignMobileDay(index) {
    if (!isMobileDayPager()) return;
    var days = getPagerDayEls();
    if (!days.length) return;
    if (index == null || !Number.isFinite(index)) index = mobileDayIndex;
    index = Math.max(0, Math.min(days.length - 1, index | 0));
    cancelPagerAnim();
    clearDayPageEffects();
    snapPagerToIndex(index);
    resetAllDragEventStyles();
    ensureGhostHiddenIfIdle();
  }

  function syncDayStrip(index, opts) {
    var strip = getDayStrip();
    if (!strip) return;
    var btns = strip.querySelectorAll(".sched-day-strip__btn");
    btns.forEach(function (btn, i) {
      btn.classList.toggle("is-active", i === index);
    });
    updateStripPill(index, 0);
    if (opts && opts.scrollBtn === false) return;
    var activeBtn = btns[index];
    if (activeBtn && activeBtn.scrollIntoView) {
      try {
        activeBtn.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
      } catch (e) {
        try {
          activeBtn.scrollIntoView(false);
        } catch (e2) {}
      }
    }
  }

  function updateStripPill(index, frac) {
    var strip = getDayStrip();
    if (!strip) return;
    var pill = document.getElementById("sched-day-strip-pill");
    if (!pill) return;
    var btns = strip.querySelectorAll(".sched-day-strip__btn");
    if (!btns.length) return;
    var i0 = Math.max(0, Math.min(btns.length - 1, Math.floor(index)));
    var i1 = Math.max(0, Math.min(btns.length - 1, i0 + 1));
    var t = frac != null ? frac : index - i0;
    if (!Number.isFinite(t)) t = 0;
    t = Math.max(0, Math.min(1, t));
    var b0 = btns[i0];
    var b1 = btns[i1];
    var left0 = b0.offsetLeft;
    var left1 = b1.offsetLeft;
    var w0 = b0.offsetWidth;
    var w1 = b1.offsetWidth;
    var left = left0 + (left1 - left0) * t;
    var width = w0 + (w1 - w0) * t;
    pill.style.width = width + "px";
    pill.style.transform = "translateX(" + left + "px)";
  }

  function syncStripFromPagerScroll() {
    var pager = getDaysPager();
    if (!pager || !MOBILE_MQ.matches) return;
    var progress = dayProgressFromPagerScroll();
    var i0 = Math.floor(progress);
    var frac = progress - i0;
    var nearest = Math.round(progress);
    var days = getPagerDayEls();
    nearest = Math.max(0, Math.min(days.length - 1, nearest));
    updateStripPill(i0, frac);
    var strip = getDayStrip();
    if (strip) {
      var btns = strip.querySelectorAll(".sched-day-strip__btn");
      btns.forEach(function (btn, i) {
        btn.classList.toggle("is-active", i === nearest);
      });
    }
    if (nearest !== mobileDayIndex) {
      mobileDayIndex = nearest;
      try {
        sessionStorage.setItem(DAY_INDEX_KEY, String(nearest));
      } catch (e) {}
    }
  }

  function easeOutCubic(t) {
    return 1 - Math.pow(1 - t, 3);
  }

  function cancelPagerAnim() {
    pagerAnimGen += 1;
    if (pagerAnimRaf) {
      cancelAnimationFrame(pagerAnimRaf);
      pagerAnimRaf = null;
    }
    document.documentElement.classList.remove("qa-paging-day");
    setPagerSnapEnabled(true);
  }

  function animatePagerTo(targetLeft, durationMs, animOpts) {
    var pager = getDaysPager();
    if (!pager) return;
    cancelPagerAnim();
    var gen = pagerAnimGen;
    sizePagerDays();
    targetLeft = Math.round(targetLeft);
    var startLeft = pager.scrollLeft;
    var dist = targetLeft - startLeft;
    var onFrame = animOpts && animOpts.onFrame;
    var onDone = animOpts && animOpts.onDone;
    var duringDrag = !!(animOpts && animOpts.duringDrag);

    function finish() {
      if (gen !== pagerAnimGen) return;
      pagerAnimRaf = null;
      sizePagerDays();
      pager.scrollLeft = targetLeft;
      setPagerSnapEnabled(true);
      document.documentElement.classList.remove("qa-paging-day");
      syncStripFromPagerScroll();
      clearDayPageEffects();
      ensureGhostHiddenIfIdle();
      if (!duringDrag) resetAllDragEventStyles();
      if (typeof onDone === "function") onDone();
    }

    if (Math.abs(dist) < 1) {
      finish();
      return;
    }

    setPagerSnapEnabled(false);
    if (duringDrag) document.documentElement.classList.add("qa-paging-day");

    // Nativní smooth scroll = plynulý flow bez sekání se snapem
    if (!duringDrag && typeof pager.scrollTo === "function") {
      var settled = false;
      var safetyTimer = null;
      function settleOnce() {
        if (settled || gen !== pagerAnimGen) return;
        settled = true;
        if (safetyTimer) clearTimeout(safetyTimer);
        pager.removeEventListener("scrollend", settleOnce);
        finish();
      }
      pager.addEventListener("scrollend", settleOnce, { passive: true });
      safetyTimer = setTimeout(settleOnce, Math.max(420, (durationMs || 380) + 120));
      try {
        pager.scrollTo({ left: targetLeft, behavior: "smooth" });
      } catch (e) {
        pager.scrollLeft = targetLeft;
        settleOnce();
      }
      function watch() {
        if (settled || gen !== pagerAnimGen) return;
        syncStripFromPagerScroll();
        if (typeof onFrame === "function") onFrame(0.5);
        pagerAnimRaf = requestAnimationFrame(watch);
      }
      pagerAnimRaf = requestAnimationFrame(watch);
      return;
    }

    var start = performance.now();
    var dur = durationMs != null ? durationMs : 380;
    function frame(now) {
      if (gen !== pagerAnimGen) return;
      var t = Math.min(1, (now - start) / dur);
      var eased = easeOutCubic(t);
      pager.scrollLeft = startLeft + dist * eased;
      syncStripFromPagerScroll();
      if (typeof onFrame === "function") onFrame(t);
      if (t < 1) {
        pagerAnimRaf = requestAnimationFrame(frame);
      } else {
        finish();
      }
    }
    pagerAnimRaf = requestAnimationFrame(frame);
  }

  function goToDay(index, opts) {
    var pager = getDaysPager();
    var days = getPagerDayEls();
    if (!pager || !days.length) return;
    index = Math.max(0, Math.min(days.length - 1, index | 0));
    mobileDayIndex = index;
    sizePagerDays();
    var left = pagerScrollLeftForIndex(index);
    var instant = opts && opts.instant;
    if (instant) {
      cancelPagerAnim();
      setPagerSnapEnabled(false);
      pager.scrollLeft = left;
      requestAnimationFrame(function () {
        sizePagerDays();
        pager.scrollLeft = pagerScrollLeftForIndex(index);
        setPagerSnapEnabled(true);
        syncStripFromPagerScroll();
        clearDayPageEffects();
        ensureGhostHiddenIfIdle();
      });
      syncDayStrip(index, { scrollBtn: !(opts && opts.skipStripScroll) });
      clearDayPageEffects();
    } else {
      animatePagerTo(left, (opts && opts.duration) || 380, {
        duringDrag: !!(opts && opts.duringDrag),
        onFrame: opts && opts.onFrame,
        onDone: function () {
          clearDayPageEffects();
          if (typeof (opts && opts.onDone) === "function") opts.onDone();
        },
      });
      syncDayStrip(index, { scrollBtn: !(opts && opts.skipStripScroll) });
    }
    try {
      sessionStorage.setItem(DAY_INDEX_KEY, String(index));
    } catch (e) {}
    ensureGhostHiddenIfIdle();
  }

  function dayIndexFromPagerScroll() {
    var days = getPagerDayEls();
    if (!days.length) return 0;
    var progress = dayProgressFromPagerScroll();
    var idx = Math.round(progress);
    return Math.max(0, Math.min(days.length - 1, idx));
  }

  function applyActiveDayBody(nextIndex) {
    var days = getPagerDayEls();
    var day = days[nextIndex];
    var body = day && day.querySelector("[data-longpress-slot]");
    if (!body || !active) return;
    if (body !== active.dayBody) {
      if (active.dayBody) {
        active.dayBody.classList.remove("is-longpressing", "is-dragging");
      }
      active.dayBody = body;
      var dateStr = day.getAttribute("data-date");
      var dowRaw = day.getAttribute("data-dow");
      if (dateStr) active.dateStr = dateStr;
      if (dowRaw != null) active.dow = parseInt(dowRaw, 10);
      body.classList.add("is-longpressing", "is-dragging");
      if (active.mode === "move" && active.eventEl && active.eventEl.parentNode !== body) {
        body.appendChild(active.eventEl);
      }
      try {
        if (active.pointerId != null) body.setPointerCapture(active.pointerId);
      } catch (e) {}
    }
    if (active.mode === "move") {
      positionMovedEvent(active.dayBody, active.slot);
    } else {
      showHint(active.dayBody, active.slot, true, hintDur());
    }
  }

  function maybeEdgeFlipDay(clientX) {
    if (!isMobileDayPager() || !active || !active.armed) return;
    if (active.pagingDay) return;
    var pager = getDaysPager();
    if (!pager) return;
    var now = Date.now();
    if (now - edgeDragAt < 720) return;
    var rect = pager.getBoundingClientRect();
    var edge = 28;
    var days = getPagerDayEls();
    var nextIndex = null;
    if (clientX <= rect.left + edge && mobileDayIndex > 0) {
      nextIndex = mobileDayIndex - 1;
    } else if (clientX >= rect.right - edge && mobileDayIndex < days.length - 1) {
      nextIndex = mobileDayIndex + 1;
    }
    if (nextIndex == null) return;
    edgeDragAt = now;

    mobileDayIndex = nextIndex;
    active.dragChangedDay = true;
    active.pagingDay = true;
    lockedPagerScrollLeft = null;

    applyActiveDayBody(nextIndex);

    goToDay(nextIndex, {
      instant: false,
      duration: 320,
      skipStripScroll: true,
      duringDrag: true,
      onFrame: function () {
        if (!active || !active.armed) return;
        if (active.mode === "move") {
          positionMovedEvent(active.dayBody, active.slot);
        } else {
          showHint(active.dayBody, active.slot, true, hintDur());
        }
      },
      onDone: function () {
        if (!active) return;
        active.pagingDay = false;
        lockedPagerScrollLeft = pagerScrollLeftForIndex(nextIndex);
        snapPagerToIndex(nextIndex);
        clearDayPageEffects();
        applyActiveDayBody(nextIndex);
      },
    });
  }

  function stopAutoScroll() {
    if (autoScrollRaf) {
      cancelAnimationFrame(autoScrollRaf);
      autoScrollRaf = null;
    }
  }

  function maybeAutoScrollStep() {
    autoScrollRaf = null;
    if (!active || !active.armed || active.lastY == null) return;
    var sc = getSchedScrollEl();
    if (!sc) return;
    var rect = sc.getBoundingClientRect();
    var zone = 56;
    var delta = 0;
    if (active.lastY < rect.top + zone) {
      delta = -Math.max(8, Math.round((rect.top + zone - active.lastY) * 0.35));
    } else if (active.lastY > rect.bottom - zone) {
      delta = Math.max(8, Math.round((active.lastY - (rect.bottom - zone)) * 0.35));
    }
    if (!delta) return;
    var prev = sc.scrollTop;
    sc.scrollTop = prev + delta;
    if (sc.scrollTop !== prev) {
      moveActiveTo(active.lastX, active.lastY, true);
      autoScrollRaf = requestAnimationFrame(maybeAutoScrollStep);
    }
  }

  function ensureAutoScroll() {
    if (autoScrollRaf) return;
    autoScrollRaf = requestAnimationFrame(maybeAutoScrollStep);
  }

  function navigateWeek(dir) {
    if (isStaly) return;
    var sel = dir < 0 ? ".sched-nav-prev" : ".sched-nav-next";
    var link = document.querySelector(sel);
    if (link && link.getAttribute("href")) {
      try {
        sessionStorage.setItem(DAY_INDEX_KEY, dir < 0 ? String(getPagerDayEls().length - 1) : "0");
      } catch (e) {}
      window.location.href = link.getAttribute("href");
    }
  }

  function initMobileDayPager() {
    var pager = getDaysPager();
    var strip = getDayStrip();
    if (!pager) return;

    sizePagerDays();

    if (strip) {
      strip.addEventListener("click", function (ev) {
        var btn = ev.target && ev.target.closest && ev.target.closest(".sched-day-strip__btn");
        if (!btn) return;
        ev.preventDefault();
        var idx = parseInt(btn.getAttribute("data-day-index") || "0", 10);
        goToDay(idx, { instant: false, duration: 380 });
      });
    }

    pager.addEventListener(
      "scroll",
      function () {
        if (!MOBILE_MQ.matches) return;
        if (document.documentElement.classList.contains("qa-dragging") && !(active && active.pagingDay)) {
          return;
        }
        syncStripFromPagerScroll();
        ensureGhostHiddenIfIdle();
      },
      { passive: true }
    );

    pager.addEventListener(
      "scrollend",
      function () {
        if (!MOBILE_MQ.matches) return;
        if (document.documentElement.classList.contains("qa-dragging") && !(active && active.pagingDay)) {
          return;
        }
        if (pagerAnimRaf || pager.classList.contains("is-paging")) return;
        var idx = dayIndexFromPagerScroll();
        realignMobileDay(idx);
      },
      { passive: true }
    );

    var resizeTimer = null;
    function onPagerResize() {
      if (!MOBILE_MQ.matches) {
        sizePagerDays();
        return;
      }
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeTimer = setTimeout(function () {
        resizeTimer = null;
        var idx = mobileDayIndex;
        sizePagerDays();
        snapPagerToIndex(idx);
      }, 80);
    }
    if (typeof ResizeObserver === "function") {
      try {
        var ro = new ResizeObserver(onPagerResize);
        ro.observe(pager);
      } catch (e) {
        window.addEventListener("resize", onPagerResize);
      }
    } else {
      window.addEventListener("resize", onPagerResize);
    }

    pager.addEventListener(
      "touchstart",
      function (ev) {
        if (!isMobileDayPager() || isStaly || !ev.touches || !ev.touches.length) return;
        if (document.documentElement.classList.contains("qa-dragging")) return;
        if (active) return;
        weekEdgeGesture = {
          x: ev.touches[0].clientX,
          y: ev.touches[0].clientY,
          index: dayIndexFromPagerScroll(),
        };
      },
      { passive: true }
    );

    pager.addEventListener(
      "touchend",
      function (ev) {
        if (!weekEdgeGesture || isStaly) {
          weekEdgeGesture = null;
          return;
        }
        if (document.documentElement.classList.contains("qa-dragging") || active) {
          weekEdgeGesture = null;
          return;
        }
        var touch = ev.changedTouches && ev.changedTouches[0];
        if (!touch) {
          weekEdgeGesture = null;
          return;
        }
        var dx = touch.clientX - weekEdgeGesture.x;
        var dy = touch.clientY - weekEdgeGesture.y;
        var days = getPagerDayEls();
        var atStart = weekEdgeGesture.index <= 0;
        var atEnd = weekEdgeGesture.index >= days.length - 1;
        weekEdgeGesture = null;
        if (Math.abs(dx) < 70 || Math.abs(dx) < Math.abs(dy) * 1.2) return;
        if (atStart && dx > 70) navigateWeek(-1);
        else if (atEnd && dx < -70) navigateWeek(1);
      },
      { passive: true }
    );

    function applyInitialDay() {
      if (!MOBILE_MQ.matches) {
        sizePagerDays();
        return;
      }
      sizePagerDays();
      var days = getPagerDayEls();
      if (!days.length) return;
      var idx = 0;
      var wrap = document.querySelector(".sched-wrap");
      var focusDate = wrap && wrap.getAttribute("data-focus-date");
      if (focusDate) {
        for (var i = 0; i < days.length; i++) {
          if (days[i].getAttribute("data-date") === focusDate) {
            idx = i;
            break;
          }
        }
      }
      try {
        var saved = sessionStorage.getItem(DAY_INDEX_KEY);
        if (saved != null && saved !== "") {
          var n = parseInt(saved, 10);
          if (Number.isFinite(n)) idx = n;
        }
      } catch (e) {}
      goToDay(idx, { instant: true });
    }

    applyInitialDay();
    window.addEventListener("orientationchange", function () {
      setTimeout(function () {
        if (!MOBILE_MQ.matches) {
          sizePagerDays();
          clearDayPageEffects();
          return;
        }
        sizePagerDays();
        realignMobileDay(mobileDayIndex);
      }, 160);
    });
    if (typeof MOBILE_MQ.addEventListener === "function") {
      MOBILE_MQ.addEventListener("change", function () {
        if (MOBILE_MQ.matches) applyInitialDay();
        else {
          sizePagerDays();
          clearDayPageEffects();
        }
      });
    } else if (typeof MOBILE_MQ.addListener === "function") {
      MOBILE_MQ.addListener(function () {
        if (MOBILE_MQ.matches) applyInitialDay();
        else {
          sizePagerDays();
          clearDayPageEffects();
        }
      });
    }
  }

  function saveSchedScroll(extra) {
    var el = getSchedScrollEl();
    var payload = {
      top: el ? el.scrollTop : 0,
      left: el ? el.scrollLeft : 0,
      winY: window.scrollY || window.pageYOffset || 0,
      winX: window.scrollX || window.pageXOffset || 0,
    };
    if (extra) {
      if (extra.eventId) payload.eventId = String(extra.eventId);
      if (extra.date) payload.date = extra.date;
      if (extra.time) payload.time = extra.time;
      if (extra.dayIndex != null) payload.dayIndex = extra.dayIndex;
    }
    if (payload.dayIndex == null && isMobileDayPager()) {
      payload.dayIndex = mobileDayIndex;
    }
    try {
      sessionStorage.setItem(SCROLL_KEY, JSON.stringify(payload));
    } catch (e) {}
  }

  function reloadKeepingScroll(extra) {
    saveSchedScroll(extra);
    window.location.reload();
  }

  function restoreSchedScroll() {
    var raw;
    try {
      raw = sessionStorage.getItem(SCROLL_KEY);
      if (raw) sessionStorage.removeItem(SCROLL_KEY);
    } catch (e) {
      return;
    }
    if (!raw) return;
    var data;
    try {
      data = JSON.parse(raw);
    } catch (e) {
      return;
    }

    function apply() {
      if (typeof data.winY === "number" || typeof data.winX === "number") {
        window.scrollTo(data.winX || 0, data.winY || 0);
      }
      var el = getSchedScrollEl();
      if (!el) return;
      if (typeof data.top === "number") el.scrollTop = data.top;
      if (typeof data.left === "number" && !isMobileDayPager()) el.scrollLeft = data.left;

      if (isMobileDayPager() && typeof data.dayIndex === "number") {
        goToDay(data.dayIndex, { instant: true });
      }

      var target = null;
      if (data.eventId) {
        target = document.querySelector('.ev[data-id="' + data.eventId + '"]');
      }
      if (!target && data.date && data.time) {
        var day = document.querySelector('.sched-day[data-date="' + data.date + '"]');
        if (day) target = day.querySelector("[data-longpress-slot]") || day;
      }
      if (!target) return;

      var cr = el.getBoundingClientRect();
      var er = target.getBoundingClientRect();
      var pad = 12;
      if (er.top < cr.top + pad) el.scrollTop -= cr.top + pad - er.top;
      else if (er.bottom > cr.bottom - pad) el.scrollTop += er.bottom - (cr.bottom - pad);
      if (!isMobileDayPager()) {
        if (er.left < cr.left + pad) el.scrollLeft -= cr.left + pad - er.left;
        else if (er.right > cr.right - pad) el.scrollLeft += er.right - (cr.right - pad);
      }
    }

    requestAnimationFrame(function () {
      requestAnimationFrame(apply);
    });
  }

  function dayBodyByDate(dateStr) {
    var day = document.querySelector('.sched-day[data-date="' + dateStr + '"]');
    return day ? day.querySelector("[data-longpress-slot]") : null;
  }

  function reflowDayLanes(dayBody) {
    if (!dayBody) return;
    var nodes = Array.prototype.slice.call(dayBody.querySelectorAll("a.ev, button.ev"));
    var evs = nodes.map(function (el) {
      var off = readEventOffsetMin(el);
      var dur = parseInt(el.getAttribute("data-dur") || el.style.getPropertyValue("--dur"), 10);
      if (!Number.isFinite(dur) || dur <= 0) dur = 60;
      return { el: el, offset_min: off, dur_min: dur, end_min: off + dur };
    });
    if (!evs.length) return;
    evs.sort(function (a, b) {
      return a.offset_min - b.offset_min || a.dur_min - b.dur_min;
    });

    var cluster = [];
    var clusterMaxEnd = -1;

    function finalizeCluster(clusterEvents) {
      var lanesEnd = [];
      clusterEvents.forEach(function (e) {
        var placed = false;
        for (var idx = 0; idx < lanesEnd.length; idx++) {
          if (e.offset_min >= lanesEnd[idx]) {
            e.lane = idx;
            lanesEnd[idx] = e.end_min;
            placed = true;
            break;
          }
        }
        if (!placed) {
          lanesEnd.push(e.end_min);
          e.lane = lanesEnd.length - 1;
        }
      });
      var total = lanesEnd.length || 1;
      clusterEvents.forEach(function (e) {
        e.lanes = total;
      });
    }

    evs.forEach(function (e) {
      if (!cluster.length) {
        cluster = [e];
        clusterMaxEnd = e.end_min;
        return;
      }
      if (e.offset_min < clusterMaxEnd) {
        cluster.push(e);
        if (e.end_min > clusterMaxEnd) clusterMaxEnd = e.end_min;
      } else {
        finalizeCluster(cluster);
        cluster = [e];
        clusterMaxEnd = e.end_min;
      }
    });
    if (cluster.length) finalizeCluster(cluster);

    evs.forEach(function (e) {
      e.el.style.setProperty("--lane", String(e.lane || 0));
      e.el.style.setProperty("--lanes", String(e.lanes || 1));
      e.el.className = e.el.className
        .replace(/\bev--nlanes-\d+\b/g, "")
        .replace(/\s+/g, " ")
        .trim();
      e.el.classList.add("ev--nlanes-" + (e.lanes || 1));
    });
  }

  function restoreEventToOrigin(eventEl, origin) {
    if (!eventEl || !origin || !origin.parent) return;
    if (origin.nextSibling && origin.nextSibling.parentNode === origin.parent) {
      origin.parent.insertBefore(eventEl, origin.nextSibling);
    } else {
      origin.parent.appendChild(eventEl);
    }
    eventEl.style.setProperty("--off", String(origin.off));
    eventEl.setAttribute("data-off", String(origin.off));
    clearDragFixedStyles(eventEl);
    if (origin.subText != null) {
      var sub = eventEl.querySelector(".ev-sub");
      if (sub) sub.textContent = origin.subText;
    }
    eventEl.classList.remove("is-lit", "is-dragging-ev", "is-being-moved");
    reflowDayLanes(origin.parent);
  }

  function finalizeMovedEvent(eventEl, data, originParent) {
    if (!eventEl) return;
    clearDragFixedStyles(eventEl);
    eventEl.classList.remove("is-lit", "is-dragging-ev", "is-being-moved");
    if (data && (data.sub || data.time_range || data.cena_label || data.fmt_label)) {
      var kurtLabel = eventEl.querySelector(".ev-kurt");
      if (kurtLabel && data.fmt_label) kurtLabel.textContent = data.fmt_label;
      var timeLabel = eventEl.querySelector(".ev-time");
      var cenaLabel = eventEl.querySelector(".ev-cena");
      if (timeLabel && (data.time_range || data.sub)) {
        timeLabel.textContent = data.time_range || data.sub;
      }
      if (cenaLabel && data.cena_label) cenaLabel.textContent = data.cena_label;
      var sub = eventEl.querySelector(".ev-sub");
      if (sub && !timeLabel) sub.textContent = data.sub || "";
      var titleBits = [];
      if (data.fmt_label || (kurtLabel && kurtLabel.textContent)) {
        titleBits.push(data.fmt_label || kurtLabel.textContent);
      }
      var nameEl = eventEl.querySelector(".ev-name");
      titleBits.push((nameEl && nameEl.textContent) || "—");
      titleBits.push(data.sub || ((timeLabel && timeLabel.textContent) || ""));
      eventEl.setAttribute("title", titleBits.filter(Boolean).join(" · "));
    }
    reflowDayLanes(eventEl.parentNode);
    if (originParent && originParent !== eventEl.parentNode) {
      reflowDayLanes(originParent);
    }
    if (isMobileDayPager()) realignMobileDay(mobileDayIndex);
  }

  function buildEventElement(ev, changeUrl) {
    var names = ev.names && ev.names.length ? ev.names : ["—"];
    var el;
    if (isPronajem) {
      el = document.createElement("button");
      el.type = "button";
      el.className =
        "ev ev--pronajem-slot ev--" +
        (ev.fmt || "rezervace") +
        " ev--" +
        (ev.fmt_code || "kurt-tre") +
        " ev--nlanes-1 ev--players-1";
      el.setAttribute("data-time", ev.time || "");
      el.setAttribute("data-kurt", ev.kurt || "");
      el.setAttribute("data-kurt-misto", ev.kurt_misto || "");
      el.setAttribute("data-cena", ev.cena != null ? String(ev.cena) : "");
      el.setAttribute("data-cena-hodina", ev.cena_hodina != null ? String(ev.cena_hodina) : "");
      el.setAttribute("data-rezervujici", ev.rezervujici || ev.title || "");
      el.setAttribute("data-poznamka", ev.poznamka || "");
    } else {
      el = document.createElement("a");
      el.className =
        "ev ev--" +
        (ev.fmt || "neznamy") +
        " ev--" +
        (ev.fmt_code || "") +
        " ev--nlanes-1 ev--players-" +
        names.length;
      el.href = changeUrl || "#";
      el.setAttribute("data-date", ev.date || "");
      el.setAttribute("data-time", ev.time || "");
      el.setAttribute("data-trener", ev.trener_id != null ? String(ev.trener_id) : "");
      el.setAttribute("data-format", ev.format || "");
      el.setAttribute("data-kurt", ev.kurt || "");
      el.setAttribute("data-poznamka", ev.poznamka || "");
      el.setAttribute(
        "data-hraci",
        Array.isArray(ev.hraci_ids) ? ev.hraci_ids.join(",") : ""
      );
    }
    el.setAttribute("data-id", String(ev.id));
    el.setAttribute("data-dur", String(ev.dur_min || 60));
    el.setAttribute("data-off", String(ev.offset_min || 0));
    el.title =
      (ev.fmt_label ? ev.fmt_label + " · " : "") +
      (ev.title || "—") +
      " · " +
      (ev.sub || "");
    el.style.setProperty("--off", String(ev.offset_min || 0));
    el.style.setProperty("--dur", String(ev.dur_min || 60));
    el.style.setProperty("--lane", "0");
    el.style.setProperty("--lanes", "1");

    if (isPronajem && ev.fmt_label) {
      var kurtEl = document.createElement("div");
      kurtEl.className = "ev-kurt";
      kurtEl.textContent = ev.fmt_label;
      el.appendChild(kurtEl);
    }

    var namesWrap = document.createElement("div");
    namesWrap.className = "ev-names";
    names.forEach(function (name) {
      var span = document.createElement("span");
      span.className = "ev-name";
      span.textContent = name;
      namesWrap.appendChild(span);
    });
    el.appendChild(namesWrap);

    if (isPronajem) {
      var subP = document.createElement("div");
      subP.className = "ev-sub ev-sub--pronajem";
      var timeEl = document.createElement("span");
      timeEl.className = "ev-time";
      timeEl.textContent = ev.time_range || ev.sub || "";
      subP.appendChild(timeEl);
      if (ev.cena_label) {
        var cenaEl = document.createElement("span");
        cenaEl.className = "ev-cena";
        cenaEl.textContent = ev.cena_label;
        subP.appendChild(cenaEl);
      }
      el.appendChild(subP);
    } else if (ev.sub) {
      var sub = document.createElement("div");
      sub.className = "ev-sub";
      sub.textContent = ev.sub;
      el.appendChild(sub);
    }
    return el;
  }

  function setCena(amount) {
    var value = amount != null && amount !== "" ? String(amount) : "";
    if (cenaInput) cenaInput.value = value;
    if (!cenaChips) return;
    var chips = cenaChips.querySelectorAll(".qa-chip");
    chips.forEach(function (chip) {
      chip.classList.toggle("is-active", chip.getAttribute("data-value") === value);
    });
    updatePronajemCenaHint();
  }

  function formatPronajemHours(minutes) {
    var m = parseInt(minutes, 10) || 60;
    var h = m / 60;
    if (Math.abs(h - Math.round(h)) < 0.001) return String(Math.round(h));
    return String(Math.round(h * 100) / 100).replace(".", ",");
  }

  function updatePronajemCenaHint() {
    if (!isPronajem || !cenaHint) return;
    var rate = parseFloat(String((cenaInput && cenaInput.value) || "").replace(",", "."));
    var mins = parseInt((delkaInput && delkaInput.value) || "60", 10) || 60;
    if (!Number.isFinite(rate) || rate <= 0) {
      cenaHint.textContent = "";
      return;
    }
    var hours = mins / 60;
    var total = Math.round(rate * hours * 100) / 100;
    var totalLabel = total === Math.round(total) ? String(Math.round(total)) : String(total);
    cenaHint.textContent =
      "Celkem " + totalLabel + " Kč (" + formatPronajemHours(mins) + " h × " + String(rate).replace(".", ",") + " Kč/h)";
  }

  function cenyForSezona(sezona) {
    var by = options.ceny_by_sezona || {};
    var list = (by[sezona] || options.ceny || []).slice();
    if (list.length) return list;
    if (sezona === "VENEK") {
      return [
        { value: "220", label: "220 Kč" },
        { value: "250", label: "250 Kč" },
      ];
    }
    return [
      { value: "420", label: "420 Kč" },
      { value: "440", label: "440 Kč" },
      { value: "530", label: "530 Kč" },
      { value: "580", label: "580 Kč" },
    ];
  }

  function kurtyForSezona(sezona) {
    var by = options.kurty_by_sezona || {};
    var list = by[sezona] || options.kurty || [];
    return list.slice();
  }

  function renderCenaChips(selected, sezona) {
    if (!cenaChips) return;
    cenaChips.innerHTML = "";
    var list = isPronajem ? cenyForSezona(sezona || (pronajemSezonaSel && pronajemSezonaSel.value) || "HALA") : (options.ceny || []).slice();
    if (!list.length) {
      list = cenyForSezona(sezona || "HALA");
    }
    var preferred =
      selected != null && selected !== ""
        ? String(selected)
        : String((list[0] && list[0].value) || (options.defaults && options.defaults.cena) || "");
    // Pokud aktuální cena není v seznamu (starší rezervace), přidej ji
    var hasPreferred = list.some(function (item) {
      return String(item.value) === preferred;
    });
    if (preferred && !hasPreferred) {
      list = [{ value: preferred, label: preferred + " Kč" }].concat(list);
    }
    list.forEach(function (item) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "qa-chip" + (String(item.value) === preferred ? " is-active" : "");
      btn.textContent = item.label;
      btn.setAttribute("data-value", String(item.value));
      btn.addEventListener("click", function () {
        cenaManual = true;
        setCena(item.value);
        if (cenaHint) cenaHint.textContent = "";
      });
      cenaChips.appendChild(btn);
    });
    setCena(preferred);
  }

  function applyPronajemSezona(sezona, preferredKurt, preferredCena, keepCena) {
    var season = sezona || "HALA";
    var kurty = kurtyForSezona(season);
    var kurtValue = preferredKurt || "";
    var hasKurt = kurty.some(function (item) {
      return String(item.value) === String(kurtValue);
    });
    if (!hasKurt) {
      kurtValue = (kurty[0] && kurty[0].value) || "";
    }
    fillSelect(kurtSel, kurty, "value", "label", kurtValue, "Vyberte kurt…");
    var seasonCeny = cenyForSezona(season);
    var cenaSel =
      keepCena && preferredCena != null && preferredCena !== ""
        ? preferredCena
        : (seasonCeny[0] && seasonCeny[0].value) || "";
    renderCenaChips(cenaSel, season);
  }

  function fetchPronajemCena() {
    // Ceny jsou pevný výběr z nastavení – ceník se už nepoužívá.
  }

  function insertEventFromPayload(data) {
    if (!data || !data.event) return false;
    var ev = data.event;
    var dayBody = dayBodyByDate(ev.date);
    if (!dayBody) return false;
    var el = buildEventElement(ev, data.change_url);
    dayBody.appendChild(el);
    reflowDayLanes(dayBody);
    return true;
  }

  function cssPx(el, name, fallback) {
    var raw = getComputedStyle(el).getPropertyValue(name).trim();
    var n = parseFloat(raw);
    return Number.isFinite(n) ? n : fallback;
  }

  function snapMinutes(totalMin) {
    // Linky v kalendáři = hranice: klik nad 20:00 → 19:30 (floor na 30 min)
    var snapped = Math.floor(totalMin / 30) * 30;
    return Math.max(0, snapped);
  }

  function pad2(n) {
    return (n < 10 ? "0" : "") + n;
  }

  function formatTime(hour, minute) {
    return pad2(hour) + ":" + pad2(minute);
  }

  function formatCzechDate(iso) {
    var parts = (iso || "").split("-");
    if (parts.length !== 3) return iso;
    return parts[2] + "." + parts[1] + "." + parts[0];
  }

  function csrfToken() {
    if (form) {
      var inp = form.querySelector('input[name="csrfmiddlewaretoken"]');
      if (inp && inp.value) return inp.value;
    }
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function loadStalyLast() {
    try {
      var raw = localStorage.getItem(STALY_LAST_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function saveStalyLast(payload) {
    try {
      localStorage.setItem(
        STALY_LAST_KEY,
        JSON.stringify({
          trener: payload.trener || "",
          format: payload.format || "",
          kurt: payload.kurt || "",
          delka_minut: payload.delka_minut || 60,
          hraci: payload.hraci || [],
          rezervujici: payload.rezervujici || "",
          cena: payload.cena || "",
          sezona: payload.sezona || "",
        })
      );
    } catch (e) {}
  }

  function addMinutesToTime(timeStr, minutes) {
    var parts = (timeStr || "00:00").split(":");
    var h = parseInt(parts[0], 10) || 0;
    var m = parseInt(parts[1], 10) || 0;
    var total = h * 60 + m + (parseInt(minutes, 10) || 60);
    total = ((total % (24 * 60)) + 24 * 60) % (24 * 60);
    return formatTime(Math.floor(total / 60), total % 60);
  }

  function fillPlayersFromIds(ids) {
    if (!hraciRows) return;
    hraciRows.innerHTML = "";
    var list = (ids || []).filter(Boolean);
    if (!list.length) {
      hraciRows.appendChild(createPlayerRow());
      return;
    }
    list.forEach(function (id) {
      var found = (options.players || []).find(function (p) {
        return String(p.id) === String(id);
      });
      hraciRows.appendChild(createPlayerRow(found ? { id: found.id, jmeno: found.jmeno } : { id: id }));
    });
  }

  function fillSelect(sel, items, valueKey, labelKey, selected, placeholder) {
    if (!sel) return;
    sel.innerHTML = "";
    var empty = document.createElement("option");
    empty.value = "";
    empty.textContent = placeholder || "Vyberte…";
    sel.appendChild(empty);
    (items || []).forEach(function (item) {
      var opt = document.createElement("option");
      opt.value = String(item[valueKey]);
      opt.textContent = item[labelKey];
      if (selected != null && String(selected) === String(item[valueKey])) {
        opt.selected = true;
      }
      sel.appendChild(opt);
    });
  }

  function delkaLabel(minutes, fallback) {
    var m = parseInt(minutes, 10);
    if (!Number.isFinite(m) || m <= 0) return fallback || "";
    if (m < 60) return m + " min";
    if (m % 60 === 0) return m / 60 + " h (" + m + " min)";
    var hours = Math.floor(m / 60);
    var mins = m % 60;
    return hours + "," + String(Math.round((mins / 60) * 10)) + " h (" + m + " min)";
  }

  function setDelka(minutes) {
    var value = String(minutes || 60);
    if (delkaInput) delkaInput.value = value;
    if (delkaChips) {
      var chips = delkaChips.querySelectorAll(".qa-chip");
      chips.forEach(function (chip) {
        chip.classList.toggle("is-active", chip.getAttribute("data-value") === value);
      });
    }
    updatePronajemCenaHint();
  }

  function formatIsSluzba(format) {
    return String(format || "").indexOf("V_") === 0;
  }

  function kurtHasOption(sel, value) {
    if (!sel) return false;
    return Array.prototype.some.call(sel.options || [], function (o) {
      return o.value === value;
    });
  }

  function restoreSportKurt() {
    if (!kurtSel) return;
    var prev = kurtSel.getAttribute("data-prev-kurt") || "";
    var fallback =
      (options.defaults && options.defaults.kurt) ||
      "HALA";
    var next = prev && prev !== "SLUZBA" ? prev : fallback;
    if (next === "SLUZBA") next = "HALA";
    if (!kurtHasOption(kurtSel, next)) {
      if (kurtHasOption(kurtSel, "HALA")) next = "HALA";
      else if (kurtHasOption(kurtSel, "VENEK")) next = "VENEK";
      else return;
    }
    kurtSel.value = next;
  }

  function syncSluzbaDelkaUi() {
    if (isPronajem) {
      if (delkaField) {
        delkaField.hidden = false;
        delkaField.classList.remove("is-sluzba-hidden");
      }
      return;
    }
    var format = formatSel ? formatSel.value : "";
    var kurt = kurtSel ? kurtSel.value : "";
    var fmtService = formatIsSluzba(format);

    if (fmtService) {
      if (kurtSel && kurt && kurt !== "SLUZBA") {
        kurtSel.setAttribute("data-prev-kurt", kurt);
      }
      if (kurtSel && kurtHasOption(kurtSel, "SLUZBA") && kurtSel.value !== "SLUZBA") {
        kurtSel.value = "SLUZBA";
      }
      if (delkaField) {
        delkaField.hidden = true;
        delkaField.classList.add("is-sluzba-hidden");
      }
      setDelka(60);
      return;
    }

    // Návrat z výpletu/služby na sportovní typ → obnov kurt a délku
    if (kurtSel && kurtSel.value === "SLUZBA") {
      restoreSportKurt();
      kurt = kurtSel.value;
    }

    var service = kurt === "SLUZBA";
    if (delkaField) {
      delkaField.hidden = !!service;
      delkaField.classList.toggle("is-sluzba-hidden", !!service);
    }
    if (service) setDelka(60);
  }

  function renderDelkaChips(selected) {
    if (!delkaChips) return;
    delkaChips.innerHTML = "";
    var list = options.delky || [];
    if (!list.length) {
      list = [
        { value: 30, label: "30 min" },
        { value: 45, label: "45 min" },
        { value: 60, label: "1 h" },
        { value: 90, label: "1,5 h" },
        { value: 120, label: "2 h" },
      ];
    }
    var preferred = selected != null ? String(selected) : "60";
    list.forEach(function (item) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "qa-chip";
      btn.setAttribute("data-value", String(item.value));
      btn.textContent = item.label || delkaLabel(item.value);
      btn.title = delkaLabel(item.value, item.label);
      btn.addEventListener("click", function () {
        setDelka(item.value);
      });
      delkaChips.appendChild(btn);
    });
    setDelka(preferred);
    syncSluzbaDelkaUi();
  }

  function getSelectedPlayerIds(excludeRow) {
    var ids = [];
    if (!hraciRows) return ids;
    hraciRows.querySelectorAll(".qa-hraci-row[data-id]").forEach(function (row) {
      if (row === excludeRow) return;
      ids.push(String(row.getAttribute("data-id")));
    });
    return ids;
  }

  function collectSelectedPlayers() {
    return getSelectedPlayerIds().map(Number).filter(function (id) {
      return Number.isFinite(id) && id > 0;
    });
  }

  function createPlayerRow(prefill) {
    var row = document.createElement("div");
    row.className = "qa-hraci-row";
    if (prefill && prefill.id) {
      row.setAttribute("data-id", String(prefill.id));
      row.setAttribute("data-jmeno", prefill.jmeno || "");
    }

    var wrap = document.createElement("div");
    wrap.className = "qa-hraci-search-wrap";

    var input = document.createElement("input");
    input.type = "text";
    input.className = "qa-hraci-search";
    input.placeholder = "Vyhledat hráče…";
    input.setAttribute("autocomplete", "off");
    input.setAttribute("aria-label", "Vyhledat hráče");
    if (prefill && prefill.jmeno) input.value = prefill.jmeno;

    var dropdown = document.createElement("ul");
    dropdown.className = "qa-hraci-dropdown";
    dropdown.setAttribute("role", "listbox");
    dropdown.setAttribute("aria-hidden", "true");

    wrap.appendChild(input);
    wrap.appendChild(dropdown);

    var removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "qa-hraci-remove";
    removeBtn.setAttribute("aria-label", "Odstranit");
    removeBtn.textContent = "×";

    row.appendChild(wrap);
    row.appendChild(removeBtn);
    wirePlayerRow(row);
    return row;
  }

  function wirePlayerRow(row) {
    var input = row.querySelector(".qa-hraci-search");
    var dropdown = row.querySelector(".qa-hraci-dropdown");
    var removeBtn = row.querySelector(".qa-hraci-remove");
    if (!input || !dropdown) return;

    function hideDropdown() {
      dropdown.classList.remove("is-open");
      dropdown.setAttribute("aria-hidden", "true");
    }

    function showDropdown(filter) {
      var q = (filter || "").trim().toLowerCase();
      var used = getSelectedPlayerIds(row);
      var list = (options.players || [])
        .filter(function (p) {
          return used.indexOf(String(p.id)) === -1;
        })
        .filter(function (p) {
          if (!q) return true;
          return (p.jmeno || "").toLowerCase().indexOf(q) !== -1;
        })
        .slice(0, 50);

      dropdown.innerHTML = "";
      if (!list.length) {
        var empty = document.createElement("li");
        empty.className = "qa-hraci-empty";
        empty.textContent = q ? "Žádný hráč" : "Začněte psát jméno…";
        dropdown.appendChild(empty);
        dropdown.classList.add("is-open");
        dropdown.setAttribute("aria-hidden", "false");
        try {
          dropdown.scrollIntoView({ block: "nearest", behavior: "smooth" });
        } catch (err) {}
        return;
      }

      list.forEach(function (p, idx) {
        var li = document.createElement("li");
        li.setAttribute("data-id", String(p.id));
        li.setAttribute("data-jmeno", p.jmeno || "");
        li.setAttribute("role", "option");
        if (idx === 0) li.classList.add("is-active");
        li.textContent = p.jmeno || "";
        dropdown.appendChild(li);
      });
      dropdown.classList.add("is-open");
      dropdown.setAttribute("aria-hidden", "false");
      try {
        dropdown.scrollIntoView({ block: "nearest", behavior: "smooth" });
      } catch (err) {}
    }

    function setRowPlayer(id, jmeno) {
      row.setAttribute("data-id", String(id));
      row.setAttribute("data-jmeno", jmeno || "");
      input.value = jmeno || "";
      hideDropdown();
    }

    function clearRowPlayer() {
      row.removeAttribute("data-id");
      row.removeAttribute("data-jmeno");
    }

    input.addEventListener("focus", function () {
      showDropdown(input.value);
    });
    input.addEventListener("input", function () {
      clearRowPlayer();
      showDropdown(input.value);
    });
    input.addEventListener("blur", function () {
      setTimeout(function () {
        hideDropdown();
        if (!row.getAttribute("data-id") && input.value.trim()) {
          input.value = "";
        } else if (row.getAttribute("data-id")) {
          input.value = row.getAttribute("data-jmeno") || "";
        }
      }, 160);
    });
    input.addEventListener("keydown", function (e) {
      var items = dropdown.querySelectorAll("li[data-id]");
      var activeLi = dropdown.querySelector("li.is-active");
      if (e.key === "Escape") {
        e.stopPropagation();
        hideDropdown();
        input.blur();
        return;
      }
      if (e.key === "ArrowDown" && items.length) {
        e.preventDefault();
        var next = activeLi ? activeLi.nextElementSibling : items[0];
        while (next && !next.getAttribute("data-id")) next = next.nextElementSibling;
        if (next) {
          if (activeLi) activeLi.classList.remove("is-active");
          next.classList.add("is-active");
          next.scrollIntoView({ block: "nearest" });
        }
        return;
      }
      if (e.key === "ArrowUp" && items.length) {
        e.preventDefault();
        var prev = activeLi ? activeLi.previousElementSibling : items[items.length - 1];
        while (prev && !prev.getAttribute("data-id")) prev = prev.previousElementSibling;
        if (prev) {
          if (activeLi) activeLi.classList.remove("is-active");
          prev.classList.add("is-active");
          prev.scrollIntoView({ block: "nearest" });
        }
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        var pick = activeLi && activeLi.getAttribute("data-id") ? activeLi : items[0];
        if (pick) {
          setRowPlayer(pick.getAttribute("data-id"), pick.getAttribute("data-jmeno"));
        }
      }
    });
    dropdown.addEventListener("mousedown", function (e) {
      e.preventDefault();
    });
    dropdown.addEventListener("click", function (e) {
      var li = e.target.closest("li[data-id]");
      if (!li) return;
      setRowPlayer(li.getAttribute("data-id"), li.getAttribute("data-jmeno"));
    });
    if (removeBtn) {
      removeBtn.addEventListener("click", function (e) {
        e.preventDefault();
        if (!hraciRows) return;
        var rows = hraciRows.querySelectorAll(".qa-hraci-row");
        if (rows.length <= 1) {
          clearRowPlayer();
          input.value = "";
          hideDropdown();
          input.focus();
          return;
        }
        row.remove();
      });
    }
  }

  function resetPlayerRows() {
    if (!hraciRows) return;
    hraciRows.innerHTML = "";
    hraciRows.appendChild(createPlayerRow());
  }

  function isTodayOrFuture(dateStr) {
    if (!dateStr) return false;
    var parts = String(dateStr).split("-");
    if (parts.length !== 3) return false;
    var d = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
    var now = new Date();
    var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    return d.getTime() >= today.getTime();
  }

  function openModal(opts) {
    opts = opts || {};
    var timeStr = opts.time || "";
    var dateStr = opts.date || "";
    var dow = opts.dow != null ? opts.dow : null;
    var editing = !!opts.id && !opts.ghost;
    var isGhost = !!opts.ghost;
    var isProjected =
      isGhost ||
      (!!opts.predpokladanyId) ||
      (isPredpokladany && dateStr && isTodayOrFuture(dateStr));
    var isPastPred =
      isPredpokladany && dateStr && !isTodayOrFuture(dateStr) && !isGhost;

    if (isStaly) {
      if (!overlay || !stalySaveUrl) return;
      pendingSlot = {
        mode: "staly",
        id: opts.id || null,
        dow: dow,
        time: timeStr,
      };
    } else if (isGhost || (isPredpokladany && isProjected)) {
      if (!overlay || !quickAddUrl) return;
      pendingSlot = {
        mode: "projected",
        date: dateStr,
        time: timeStr,
        ghostSlotId: opts.ghostSlotId || null,
        predpokladanyId: opts.predpokladanyId || null,
      };
    } else if (isPronajem) {
      if (!overlay || !quickAddUrl) return;
      pendingSlot = {
        mode: "pronajem",
        id: opts.id || null,
        date: dateStr,
        time: timeStr,
      };
    } else {
      if (!overlay || !quickAddUrl) {
        if (addUrl) {
          var url = new URL(addUrl, window.location.origin);
          url.searchParams.set("date", dateStr);
          url.searchParams.set("time", timeStr);
          if (trener) url.searchParams.set("trener", trener);
          window.location.href = url.pathname + url.search;
        }
        return;
      }
      pendingSlot = {
        mode: "aktualni",
        id: editing ? opts.id : null,
        date: dateStr,
        time: timeStr,
      };
    }

    if (errorEl) {
      errorEl.hidden = true;
      errorEl.textContent = "";
    }
    if (slotIdInput) slotIdInput.value = editing ? String(opts.id) : "";
    if (dowInput) dowInput.value = dow != null ? String(dow) : "";
    if (ghostSlotIdInput) ghostSlotIdInput.value = opts.ghostSlotId ? String(opts.ghostSlotId) : "";
    if (predpokladanyIdInput) {
      predpokladanyIdInput.value = opts.predpokladanyId ? String(opts.predpokladanyId) : "";
    }

    if (titleEl) {
      if (isPronajem) {
        if (isStaly) titleEl.textContent = editing ? "Upravit stálý pronájem" : "Stálý pronájem";
        else if (pendingSlot && pendingSlot.mode === "projected") {
          titleEl.textContent =
            opts.predpokladanyId || isGhost ? "Upravit předpokládaný" : "Předpokládaný pronájem";
        } else titleEl.textContent = editing ? "Upravit pronájem" : "Nový pronájem";
      } else if (isStaly) titleEl.textContent = editing ? "Upravit stálý slot" : "Stálý slot";
      else if (pendingSlot && pendingSlot.mode === "projected") {
        titleEl.textContent = opts.predpokladanyId || isGhost ? "Upravit předpokládaný" : "Předpokládaný trénink";
      } else titleEl.textContent = editing ? "Upravit trénink" : "Nový trénink";
    }
    if (stalyNoteEl) stalyNoteEl.hidden = !isStaly;
    if (whenEl) {
      if (isStaly) whenEl.textContent = (DOW_LABELS[dow] || "") + " · " + timeStr;
      else whenEl.textContent = formatCzechDate(dateStr) + " · " + timeStr;
    }

    var defaults = options.defaults || {};
    var last = isStaly && !editing ? loadStalyLast() : null;
    var preferredTrener =
      opts.trener || trener || (last && last.trener) || defaults.trener || "";
    var preferredFormat = opts.format || (last && last.format) || "";
    var preferredKurt = opts.kurt || (last && last.kurt) || defaults.kurt || "";
    var preferredDelka =
      opts.delka || (last && last.delka_minut) || defaults.delka_minut || 60;
    var preferredHraci = opts.hraci || (last && last.hraci) || [];

    /* Krátký text: label je nad polem; dlouhý + 16px by se v 2 sloupcích ořízl / <16px = auto-zoom */
    fillSelect(trenerSel, options.trainers, "id", "label", preferredTrener, "Vyberte…");
    fillSelect(formatSel, options.formats, "value", "label", preferredFormat, "Vyberte…");
    if (!isPronajem) {
      fillSelect(kurtSel, options.kurty, "value", "label", preferredKurt, "Vyberte kurt…");
    }
    fillSelect(sezonaSel, options.sezony, "value", "label", defaults.sezona || "", "Volitelně");
    renderDelkaChips(preferredDelka);
    syncSluzbaDelkaUi();
    pendingPoznamka = opts.poznamka || "";
    if (isPronajem) {
      if (rezervujiciInput) {
        rezervujiciInput.value =
          opts.rezervujici || (last && last.rezervujici) || "";
      }
      var preferredSezona =
        opts.sezona ||
        (opts.kurt === "VENEK" || opts.kurt === "HALA" ? opts.kurt : "") ||
        (last && last.sezona) ||
        defaults.sezona ||
        "HALA";
      var preferredKurtMisto =
        opts.kurt_misto ||
        (opts.kurt && opts.kurt !== "VENEK" && opts.kurt !== "HALA" ? opts.kurt : "") ||
        (last && last.kurt) ||
        defaults.kurt ||
        "";
      fillSelect(
        pronajemSezonaSel,
        options.sezony || [
          { value: "VENEK", label: "Venku" },
          { value: "HALA", label: "Hala" },
        ],
        "value",
        "label",
        preferredSezona,
        "Vyberte sezónu…"
      );
      cenaManual = true;
      var preferredCena =
        opts.cena_hodina != null && opts.cena_hodina !== ""
          ? opts.cena_hodina
          : opts.cena != null && opts.cena !== ""
            ? opts.cena
            : (last && last.cena) || "";
      applyPronajemSezona(preferredSezona, preferredKurtMisto, preferredCena, !!preferredCena);
      updatePronajemCenaHint();
    }
    if (
      !isPronajem &&
      preferredHraci &&
      preferredHraci.length &&
      (editing ||
        isStaly ||
        isGhost ||
        (pendingSlot && pendingSlot.mode === "projected"))
    ) {
      fillPlayersFromIds(preferredHraci);
    } else if (!isPronajem) {
      resetPlayerRows();
    }

    var canDeleteProjected =
      pendingSlot &&
      pendingSlot.mode === "projected" &&
      (pendingSlot.ghostSlotId || pendingSlot.predpokladanyId);

    if (deleteBtn) {
      deleteBtn.hidden = !(
        (isStaly && editing) ||
        canDeleteProjected ||
        (isPronajem && pendingSlot && pendingSlot.mode === "pronajem" && editing) ||
        (!isPronajem &&
          !isStaly &&
          editing &&
          pendingSlot &&
          pendingSlot.mode === "aktualni")
      );
      deleteBtn.disabled = false;
      deleteBtn.textContent =
        pendingSlot && pendingSlot.mode === "projected" && pendingSlot.ghostSlotId && !pendingSlot.predpokladanyId
          ? "Přeskočit"
          : "Smazat";
    }
    if (saveNextBtn) {
      saveNextBtn.hidden = !(isStaly && !editing);
      saveNextBtn.disabled = false;
    }
    if (saveBtn) {
      saveBtn.disabled = false;
      if (pendingSlot && pendingSlot.mode === "projected") saveBtn.textContent = "Uložit";
      else if (isPastPred) saveBtn.textContent = isPronajem ? "Zapsat pronájem" : "Zapsat trénink";
      else saveBtn.textContent = editing ? "Uložit" : "Přidat";
    }

    overlay.hidden = false;
    document.documentElement.classList.add("qa-open");
    // Na iOS focus() na <select> hned otevře native picker – fokus jen na sheet.
    var sheet = overlay.querySelector(".qa-sheet");
    if (sheet) {
      if (!sheet.hasAttribute("tabindex")) sheet.setAttribute("tabindex", "-1");
      try {
        sheet.focus({ preventScroll: true });
      } catch (e) {
        try {
          sheet.focus();
        } catch (e2) {}
      }
    }
    if (isPronajem && rezervujiciInput) {
      try {
        rezervujiciInput.focus({ preventScroll: true });
      } catch (e3) {}
    }
  }

  function closeModal() {
    if (!overlay) return;
    overlay.hidden = true;
    document.documentElement.classList.remove("qa-open");
    pendingSlot = null;
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = "Přidat";
    }
    if (saveNextBtn) saveNextBtn.disabled = false;
    if (deleteBtn) deleteBtn.disabled = false;
  }

  function showError(msg) {
    if (!errorEl) {
      window.alert(msg);
      return;
    }
    errorEl.textContent = msg || "Nepodařilo se uložit.";
    errorEl.hidden = false;
  }

  function buildCommonPayload() {
    return {
      trener: trenerSel ? trenerSel.value : "",
      format: formatSel ? formatSel.value : "",
      delka_minut: delkaInput ? delkaInput.value : 60,
      kurt: kurtSel ? kurtSel.value : "",
      sezona: sezonaSel ? sezonaSel.value : "",
      poznamka: pendingPoznamka,
      hraci: collectSelectedPlayers(),
    };
  }

  function submitStalyDelete() {
    if (!pendingSlot) return;

    // Ghost / jednorázový předpokládaný → přeskočit nebo smazat
    if (pendingSlot.mode === "projected" || pendingSlot.mode === "ghost") {
      if (!skipUrl) return;
      var isOneOff = !!pendingSlot.predpokladanyId;
      var confirmMsg = isOneOff
        ? "Smazat tento předpokládaný slot? Neuloží se do tréninků."
        : "Přeskočit tento slot? Noční zápis ho ten den nevytvoří.";
      if (!window.confirm(confirmMsg)) return;
      if (deleteBtn) deleteBtn.disabled = true;
      var skipBody = { date: pendingSlot.date };
      if (isOneOff) skipBody.predpokladany_id = pendingSlot.predpokladanyId;
      else skipBody.staly_slot_id = pendingSlot.ghostSlotId;
      if (!isOneOff && !pendingSlot.ghostSlotId) {
        if (deleteBtn) deleteBtn.disabled = false;
        return;
      }
      fetch(skipUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken(),
          Accept: "application/json",
        },
        body: JSON.stringify(skipBody),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          if (result.data && result.data.ok) {
            closeModal();
            reloadKeepingScroll();
            return;
          }
          showError((result.data && result.data.error) || "Nepodařilo se smazat.");
          if (deleteBtn) deleteBtn.disabled = false;
        })
        .catch(function () {
          showError("Chyba spojení. Zkuste to znovu.");
          if (deleteBtn) deleteBtn.disabled = false;
        });
      return;
    }

    if (!pendingSlot.id || !stalyDeleteUrlTpl) return;
    var deletedStalyId = pendingSlot.id;
    var url = stalyDeleteUrlTpl.replace("{id}", String(deletedStalyId));
    if (deleteBtn) deleteBtn.disabled = true;
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "X-CSRFToken": csrfToken(),
        Accept: "application/json",
      },
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (result) {
        if (result.data && result.data.ok) {
          closeModal();
          removeEventElById(deletedStalyId);
          return;
        }
        showError((result.data && result.data.error) || "Nepodařilo se smazat.");
        if (deleteBtn) deleteBtn.disabled = false;
      })
      .catch(function () {
        showError("Chyba spojení. Zkuste to znovu.");
        if (deleteBtn) deleteBtn.disabled = false;
      });
  }

  function submitStalyMove(eventId, dow, timeStr, eventEl, origin) {
    if (!stalySaveUrl || !eventId) {
      if (eventEl && origin) restoreEventToOrigin(eventEl, origin);
      return;
    }
    fetch(stalySaveUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
        Accept: "application/json",
      },
      body: JSON.stringify({
        id: eventId,
        dow: dow,
        time: timeStr,
        move_only: true,
      }),
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (result) {
        if (result.data && result.data.ok) {
          eventEl.setAttribute("data-dow", String(result.data.dow));
          eventEl.setAttribute("data-time", result.data.time);
          var day = document.querySelector('.sched-day[data-dow="' + result.data.dow + '"]');
          var body = day && day.querySelector("[data-longpress-slot]");
          var originParent = origin && origin.parent ? origin.parent : null;
          if (body && eventEl.parentNode !== body) body.appendChild(eventEl);
          finalizeMovedEvent(eventEl, result.data, originParent);
          return;
        }
        window.alert((result.data && result.data.error) || "Nepodařilo se přesunout.");
        if (eventEl && origin) restoreEventToOrigin(eventEl, origin);
      })
      .catch(function () {
        window.alert("Chyba spojení. Zkuste to znovu.");
        if (eventEl && origin) restoreEventToOrigin(eventEl, origin);
      });
  }

  function removeEventElById(eventId) {
    if (!eventId) return;
    var el = document.querySelector('.ev[data-id="' + String(eventId) + '"]');
    if (!el) return;
    var dayBody = el.parentNode;
    el.remove();
    if (dayBody) reflowDayLanes(dayBody);
  }

  function submitPronajemDelete() {
    if (!pendingSlot || !pendingSlot.id || !deleteUrl) return;
    var deletedId = pendingSlot.id;
    if (deleteBtn) deleteBtn.disabled = true;
    fetch(deleteUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
        Accept: "application/json",
      },
      body: JSON.stringify({ id: deletedId }),
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (result) {
        if (result.data && result.data.ok) {
          closeModal();
          // Bez reloadu – zůstaň na stejném datu/čase v rozvrhu
          removeEventElById(deletedId);
          return;
        }
        showError((result.data && result.data.error) || "Nepodařilo se smazat.");
        if (deleteBtn) deleteBtn.disabled = false;
      })
      .catch(function () {
        showError("Chyba spojení. Zkuste to znovu.");
        if (deleteBtn) deleteBtn.disabled = false;
      });
  }

  function submitQuickAdd(keepOpen) {
    if (!pendingSlot) return;

    if (isPronajem) {
      if (!rezervujiciInput || !rezervujiciInput.value.trim()) {
        showError("Zadejte jméno rezervujícího.");
        return;
      }
      if (!pronajemSezonaSel || !pronajemSezonaSel.value) {
        showError("Vyberte sezónu.");
        return;
      }
      if (!kurtSel || !kurtSel.value) {
        showError("Vyberte kurt.");
        return;
      }
      if (!cenaInput || !cenaInput.value) {
        showError("Vyberte cenu.");
        return;
      }

      if (pendingSlot.mode === "staly" || isStaly) {
        if (!stalySaveUrl) return;
        var stalyPronajemPayload = {
          id: pendingSlot.id || null,
          dow: pendingSlot.dow != null ? pendingSlot.dow : parseInt(dowInput && dowInput.value, 10),
          time: pendingSlot.time,
          rezervujici: rezervujiciInput.value.trim(),
          delka_minut: delkaInput ? delkaInput.value : 60,
          sezona: pronajemSezonaSel.value,
          kurt: kurtSel.value,
          kurt_misto: kurtSel.value,
          cena: cenaInput.value,
          poznamka: pendingPoznamka || "",
        };
        if (saveBtn) {
          saveBtn.disabled = true;
          saveBtn.textContent = "…";
        }
        if (saveNextBtn) saveNextBtn.disabled = true;
        if (errorEl) errorEl.hidden = true;
        fetch(stalySaveUrl, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken(),
            Accept: "application/json",
          },
          body: JSON.stringify(stalyPronajemPayload),
        })
          .then(function (res) {
            return res.json().then(function (data) {
              return { ok: res.ok, data: data };
            });
          })
          .then(function (result) {
            if (result.data && result.data.ok) {
              saveStalyLast(stalyPronajemPayload);
              if (keepOpen) {
                var nextTimeP = addMinutesToTime(
                  stalyPronajemPayload.time,
                  stalyPronajemPayload.delka_minut
                );
                try {
                  sessionStorage.setItem(
                    STALY_CONTINUE_KEY,
                    JSON.stringify({
                      dow: stalyPronajemPayload.dow,
                      time: nextTimeP,
                      sezona: stalyPronajemPayload.sezona,
                      kurt: stalyPronajemPayload.kurt,
                      delka: stalyPronajemPayload.delka_minut,
                      rezervujici: stalyPronajemPayload.rezervujici,
                      cena: stalyPronajemPayload.cena,
                    })
                  );
                } catch (e) {}
              }
              closeModal();
              reloadKeepingScroll({
                eventId: result.data.id,
                time: stalyPronajemPayload.time,
              });
              return;
            }
            showError((result.data && result.data.error) || "Nepodařilo se uložit.");
            if (saveBtn) {
              saveBtn.disabled = false;
              saveBtn.textContent = stalyPronajemPayload.id ? "Uložit" : "Přidat";
            }
            if (saveNextBtn) saveNextBtn.disabled = false;
          })
          .catch(function () {
            showError("Chyba spojení. Zkuste to znovu.");
            if (saveBtn) {
              saveBtn.disabled = false;
              saveBtn.textContent = "Přidat";
            }
            if (saveNextBtn) saveNextBtn.disabled = false;
          });
        return;
      }

      if (!quickAddUrl) return;
      var pronajemPayload = {
        id: pendingSlot.id || (slotIdInput && slotIdInput.value) || null,
        date: pendingSlot.date,
        time: pendingSlot.time,
        rezervujici: rezervujiciInput.value.trim(),
        delka_minut: delkaInput ? delkaInput.value : 60,
        sezona: pronajemSezonaSel.value,
        kurt: kurtSel.value,
        kurt_misto: kurtSel.value,
        cena: cenaInput ? cenaInput.value : "",
        poznamka: pendingPoznamka || "",
      };
      if (pendingSlot.mode === "projected" || pendingSlot.mode === "ghost") {
        pronajemPayload.as_projected = true;
        pronajemPayload.mode = "predpokladany";
        if (pendingSlot.ghostSlotId) pronajemPayload.ghost_slot_id = pendingSlot.ghostSlotId;
        if (pendingSlot.predpokladanyId) {
          pronajemPayload.predpokladany_id = pendingSlot.predpokladanyId;
        }
      } else if (isPredpokladany && isTodayOrFuture(pendingSlot.date)) {
        pronajemPayload.as_projected = true;
        pronajemPayload.mode = "predpokladany";
      }
      if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.textContent = "…";
      }
      if (errorEl) errorEl.hidden = true;
      fetch(quickAddUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken(),
          Accept: "application/json",
        },
        body: JSON.stringify(pronajemPayload),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          if (result.data && result.data.ok) {
            closeModal();
            if (result.data.projected || !insertEventFromPayload(result.data)) {
              reloadKeepingScroll({
                eventId: result.data.id,
                date: pronajemPayload.date,
                time: pronajemPayload.time,
              });
            } else if (pronajemPayload.id) {
              var oldEl = document.querySelector('.ev[data-id="' + pronajemPayload.id + '"]');
              if (oldEl) oldEl.remove();
            }
            return;
          }
          showError((result.data && result.data.error) || "Nepodařilo se uložit.");
          if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.textContent = pronajemPayload.id ? "Uložit" : "Přidat";
          }
        })
        .catch(function () {
          showError("Chyba spojení. Zkuste to znovu.");
          if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.textContent = "Přidat";
          }
        });
      return;
    }

    if (!trenerSel || !trenerSel.value) {
      showError("Vyberte trenéra.");
      return;
    }
    if (!formatSel || !formatSel.value) {
      showError("Vyberte typ tréninku.");
      return;
    }
    if (!kurtSel || !kurtSel.value) {
      showError("Vyberte kurt.");
      return;
    }

    var common = buildCommonPayload();

    if (pendingSlot.mode === "staly" || isStaly) {
      if (!stalySaveUrl) return;
      var stalyPayload = {
        id: pendingSlot.id || null,
        dow: pendingSlot.dow != null ? pendingSlot.dow : parseInt(dowInput && dowInput.value, 10),
        time: pendingSlot.time,
        trener: common.trener,
        format: common.format,
        delka_minut: common.delka_minut,
        kurt: common.kurt,
        poznamka: common.poznamka,
        hraci: common.hraci,
      };
      if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.textContent = "…";
      }
      if (saveNextBtn) saveNextBtn.disabled = true;
      if (errorEl) errorEl.hidden = true;

      fetch(stalySaveUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken(),
          Accept: "application/json",
        },
        body: JSON.stringify(stalyPayload),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          if (result.data && result.data.ok) {
            saveStalyLast(stalyPayload);
            if (keepOpen) {
              var nextTime = addMinutesToTime(stalyPayload.time, stalyPayload.delka_minut);
              try {
                sessionStorage.setItem(
                  STALY_CONTINUE_KEY,
                  JSON.stringify({
                    dow: stalyPayload.dow,
                    time: nextTime,
                    trener: stalyPayload.trener,
                    format: stalyPayload.format,
                    kurt: stalyPayload.kurt,
                    delka: stalyPayload.delka_minut,
                  })
                );
              } catch (e) {}
              closeModal();
              reloadKeepingScroll({ eventId: result.data.id, time: stalyPayload.time });
              return;
            }
            closeModal();
            reloadKeepingScroll({ eventId: result.data.id, time: stalyPayload.time });
            return;
          }
          showError((result.data && result.data.error) || "Nepodařilo se uložit.");
          if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.textContent = stalyPayload.id ? "Uložit" : "Přidat";
          }
          if (saveNextBtn) saveNextBtn.disabled = false;
        })
        .catch(function () {
          showError("Chyba spojení. Zkuste to znovu.");
          if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.textContent = "Přidat";
          }
          if (saveNextBtn) saveNextBtn.disabled = false;
        });
      return;
    }

    if (!quickAddUrl) return;
    var payload = {
      id: pendingSlot.id || (slotIdInput && slotIdInput.value) || null,
      date: pendingSlot.date,
      time: pendingSlot.time,
      trener: common.trener,
      format: common.format,
      delka_minut: common.delka_minut,
      kurt: common.kurt,
      sezona: common.sezona,
      poznamka: common.poznamka,
      hraci: common.hraci,
    };
    if (pendingSlot.mode === "projected" || pendingSlot.mode === "ghost") {
      payload.as_projected = true;
      payload.mode = "predpokladany";
      if (pendingSlot.ghostSlotId) payload.ghost_slot_id = pendingSlot.ghostSlotId;
      if (pendingSlot.predpokladanyId) payload.predpokladany_id = pendingSlot.predpokladanyId;
    } else if (isPredpokladany && isTodayOrFuture(pendingSlot.date)) {
      payload.as_projected = true;
      payload.mode = "predpokladany";
    }

    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.textContent = "…";
    }
    if (errorEl) errorEl.hidden = true;

    fetch(quickAddUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
        Accept: "application/json",
      },
      body: JSON.stringify(payload),
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, status: res.status, data: data };
        });
      })
      .then(function (result) {
        if (result.data && result.data.ok) {
          var wasEdit = !!payload.id;
          closeModal();
          if (wasEdit) {
            removeEventElById(payload.id);
          }
          if (result.data.projected || !insertEventFromPayload(result.data)) {
            reloadKeepingScroll({
              eventId: result.data.id,
              date: payload.date,
              time: payload.time,
            });
          }
          return;
        }
        showError((result.data && result.data.error) || "Nepodařilo se uložit.");
        if (saveBtn) {
          saveBtn.disabled = false;
          saveBtn.textContent = payload.id ? "Uložit" : "Přidat";
        }
      })
      .catch(function () {
        showError("Chyba spojení. Zkuste to znovu.");
        if (saveBtn) {
          saveBtn.disabled = false;
          saveBtn.textContent = "Přidat";
        }
      });
  }

  function parseHraciIds(raw) {
    raw = (raw || "").trim();
    if (!raw) return [];
    return raw
      .split(",")
      .map(function (x) {
        return parseInt(x, 10);
      })
      .filter(function (n) {
        return Number.isFinite(n);
      });
  }

  function openTreningEditFromEl(eventEl, fallbackDate) {
    if (!eventEl) return;
    openModal({
      id: eventEl.getAttribute("data-id"),
      date: eventEl.getAttribute("data-date") || fallbackDate || "",
      time: eventEl.getAttribute("data-time") || "",
      delka: parseInt(eventEl.getAttribute("data-dur") || "60", 10),
      trener: eventEl.getAttribute("data-trener") || "",
      format: eventEl.getAttribute("data-format") || "",
      kurt: eventEl.getAttribute("data-kurt") || "",
      poznamka: eventEl.getAttribute("data-poznamka") || "",
      hraci: parseHraciIds(eventEl.getAttribute("data-hraci")),
    });
  }

  function submitTreningDelete() {
    if (!pendingSlot || !pendingSlot.id || !deleteUrl) return;
    if (!window.confirm("Smazat tento trénink?")) return;
    var deletedId = pendingSlot.id;
    if (deleteBtn) deleteBtn.disabled = true;
    fetch(deleteUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
        Accept: "application/json",
      },
      body: JSON.stringify({ id: deletedId }),
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (result) {
        if (result.data && result.data.ok) {
          closeModal();
          removeEventElById(deletedId);
          return;
        }
        showError((result.data && result.data.error) || "Nepodařilo se smazat.");
        if (deleteBtn) deleteBtn.disabled = false;
      })
      .catch(function () {
        showError("Chyba spojení. Zkuste to znovu.");
        if (deleteBtn) deleteBtn.disabled = false;
      });
  }

  function slotFromEvent(dayBody, clientY, grabOffsetY) {
    var wrap = dayBody.closest(".sched-wrap") || dayBody;
    var hourH = cssPx(wrap, "--hour-h", 115);
    var startHour = cssPx(wrap, "--sched-start", 6);
    var hourCount = cssPx(wrap, "--hour-count", 16);
    var layout = getDragLayoutRects(dayBody);
    var y = clientY - layout.dayRect.top - (grabOffsetY || 0);
    var offsetMin = snapMinutes((y / hourH) * 60);
    var maxMin = Math.max(0, (hourCount - 0.5) * 60);
    if (offsetMin > maxMin) offsetMin = maxMin;
    if (offsetMin < 0) offsetMin = 0;
    var absoluteMin = startHour * 60 + offsetMin;
    var hour = Math.floor(absoluteMin / 60);
    var minute = absoluteMin % 60;
    if (hour > 23) {
      hour = 23;
      minute = 30;
    }
    return { offsetMin: offsetMin, hour: hour, minute: minute, hourH: hourH };
  }

  function slotFromOffset(dayBody, offsetMin) {
    var wrap = dayBody.closest(".sched-wrap") || dayBody;
    var hourH = cssPx(wrap, "--hour-h", 115);
    var startHour = cssPx(wrap, "--sched-start", 6);
    var hourCount = cssPx(wrap, "--hour-count", 16);
    var maxMin = Math.max(0, (hourCount - 0.5) * 60);
    offsetMin = snapMinutes(offsetMin);
    if (offsetMin > maxMin) offsetMin = maxMin;
    if (offsetMin < 0) offsetMin = 0;
    var absoluteMin = startHour * 60 + offsetMin;
    var hour = Math.floor(absoluteMin / 60);
    var minute = absoluteMin % 60;
    if (hour > 23) {
      hour = 23;
      minute = 30;
    }
    return { offsetMin: offsetMin, hour: hour, minute: minute, hourH: hourH };
  }

  function defaultDurMin() {
    var d = (options.defaults && options.defaults.delka_minut) || 60;
    d = parseInt(d, 10);
    return Number.isFinite(d) && d > 0 ? d : 60;
  }

  function dayBodyFromPoint(clientX, clientY) {
    var el = document.elementFromPoint(clientX, clientY);
    if (!el || !el.closest) return null;
    return el.closest("[data-longpress-slot]");
  }

  function getOrCreateDragGhost(dayBody) {
    var ghost = document.getElementById("sched-drag-ghost");
    if (!ghost) {
      ghost = document.createElement("div");
      ghost.id = "sched-drag-ghost";
      ghost.className = "sched-drag-ghost";
      ghost.setAttribute("aria-hidden", "true");
    }
    // Absolute uvnitř dne = stejná velikost, scroll pod sticky řádek dnů (ne fixed přes header)
    var host = dayBody || document.body;
    if (ghost.parentNode !== host) {
      host.appendChild(ghost);
    }
    return ghost;
  }

  function hideDragGhost() {
    var ghost = document.getElementById("sched-drag-ghost");
    if (!ghost) return;
    ghost.classList.remove("is-visible");
    ghost.hidden = true;
    ghost.textContent = "";
    ghost.style.top = "";
    ghost.style.left = "";
    ghost.style.width = "";
    ghost.style.height = "";
    ghost.style.transform = "";
    ghost.style.filter = "";
    ghost.style.opacity = "";
    ghost.style.clipPath = "";
    ghost.style.webkitClipPath = "";
  }

  function ensureGhostHiddenIfIdle() {
    if (active && active.armed) return;
    hideDragGhost();
  }

  function getVisiblePagerDayIndex() {
    var days = getPagerDayEls();
    if (!days.length) return mobileDayIndex;
    return dayIndexFromPagerScroll();
  }

  function getDragLayoutRects(dayBody) {
    var dayRect = dayBody
      ? dayBody.getBoundingClientRect()
      : { top: 0, left: 0, width: 0, height: 0 };
    var colRect = dayRect;
    if (isMobileDayPager()) {
      var pager = getDaysPager();
      if (pager && dayBody) {
        var pr = pager.getBoundingClientRect();
        var br = dayBody.getBoundingClientRect();
        // Sloupec slotů = day-body; ořízni na viditelný pager (při swipe/edge-flip)
        var left = Math.max(br.left, pr.left);
        var right = Math.min(br.right, pr.right);
        var width = Math.max(40, right - left);
        colRect = {
          top: br.top,
          left: left,
          width: width,
          height: br.height,
          right: left + width,
          bottom: br.bottom,
        };
        dayRect = br;
      }
    }
    return { dayRect: dayRect, colRect: colRect };
  }

  function clearDragFixedStyles(el) {
    if (!el || !el.style) return;
    el.style.position = "";
    el.style.left = "";
    el.style.top = "";
    el.style.width = "";
    el.style.right = "";
    el.style.zIndex = "";
    el.style.opacity = "";
    el.style.pointerEvents = "";
    el.style.visibility = "";
    el.style.transform = "";
  }

  function resetAllDragEventStyles() {
    document.querySelectorAll(".sched-day-body .ev").forEach(function (el) {
      if (!el.style) return;
      // Jakýkoli zbytek po dragu (fixed/left/opacity/transform) rozhazuje layout
      if (
        el.style.position ||
        el.style.left ||
        el.style.top ||
        el.style.width ||
        el.style.opacity ||
        el.style.right ||
        el.style.zIndex ||
        el.style.transform ||
        el.style.pointerEvents ||
        el.style.visibility
      ) {
        clearDragFixedStyles(el);
      }
      el.classList.remove("is-lit", "is-dragging-ev", "is-being-moved");
    });
    ensureGhostHiddenIfIdle();
  }

  function snapPagerToIndex(index) {
    var pager = getDaysPager();
    var days = getPagerDayEls();
    if (!pager || !days.length) return;
    index = Math.max(0, Math.min(days.length - 1, index | 0));
    sizePagerDays();
    var left = pagerScrollLeftForIndex(index);
    setPagerSnapEnabled(false);
    pager.scrollLeft = left;
    requestAnimationFrame(function () {
      sizePagerDays();
      pager.scrollLeft = pagerScrollLeftForIndex(index);
      requestAnimationFrame(function () {
        setPagerSnapEnabled(true);
        syncDayStrip(index, { scrollBtn: false });
        clearDayPageEffects();
      });
    });
    lockedPagerScrollLeft = left;
    mobileDayIndex = index;
    syncDayStrip(index, { scrollBtn: false });
    clearDayPageEffects();
    ensureGhostHiddenIfIdle();
  }

  function positionDragGhost(dayBody, slot, durMin) {
    if (!dayBody || !slot) {
      hideDragGhost();
      return;
    }
    var ghost = getOrCreateDragGhost(dayBody);
    var dur = durMin != null ? durMin : defaultDurMin();
    dur = parseInt(dur, 10);
    if (!Number.isFinite(dur) || dur <= 0) dur = 60;
    var hourH = slot.hourH || 115;
    var top = slot.offsetMin * (hourH / 60);
    var height = Math.max(dur * (hourH / 60), 32);
    // Souřadnice vůči day-body (absolute) – stejná výška, scroll pod sticky head
    var left = 6;
    var width = Math.max((dayBody.clientWidth || 0) - 12, 40);
    if (isMobileDayPager()) {
      var layout = getDragLayoutRects(dayBody);
      width = Math.max(layout.colRect.width - 12, 40);
      left = Math.max(6, layout.colRect.left - layout.dayRect.left + 6);
    }
    ghost.hidden = false;
    ghost.removeAttribute("hidden");
    ghost.classList.add("is-visible");
    ghost.style.top = top + "px";
    ghost.style.left = left + "px";
    ghost.style.width = width + "px";
    ghost.style.height = height + "px";
    ghost.setAttribute("data-time", formatTime(slot.hour, slot.minute));
    ghost.textContent = formatTime(slot.hour, slot.minute);
  }

  function showHint(dayBody, slot, ready, durMin, chargeMs) {
    if (active && active.mode === "move") return;
    if (!dayBody || !slot) return;
    // Absolute ghost v dni – stejná velikost, při scrollu pod řádek dnů
    if (ready) {
      positionDragGhost(dayBody, slot, durMin);
      // Skryj inline hint, ať nejsou dva
      var inline = dayBody.querySelector(".sched-press-hint");
      if (inline) {
        inline.hidden = true;
        inline.classList.remove("is-holding", "is-ready", "is-charging");
        inline.style.removeProperty("--hold-ms");
      }
      return;
    }
    var hint = dayBody.querySelector(".sched-press-hint");
    if (!hint) return;
    var dur = durMin != null ? durMin : defaultDurMin();
    dur = parseInt(dur, 10);
    if (!Number.isFinite(dur) || dur <= 0) dur = 60;
    var wasHidden = hint.hidden;
    var animMs = chargeMs != null ? chargeMs : holdMs;
    hint.hidden = false;
    hint.style.top = slot.offsetMin * (slot.hourH / 60) + "px";
    hint.style.height = Math.max(dur * (slot.hourH / 60), 28) + "px";
    hint.style.setProperty("--hold-ms", animMs + "ms");
    hint.classList.add("is-holding");
    hint.classList.remove("is-ready");
    // Restart charge animation jen při novém podržení
    if (wasHidden || !hint.classList.contains("is-charging")) {
      hint.classList.remove("is-charging");
      // force reflow – ať se animace spustí znovu
      void hint.offsetWidth;
      hint.classList.add("is-charging");
    }
    hint.setAttribute("data-time", formatTime(slot.hour, slot.minute));
  }

  function touchCreateStill() {
    if (!active) return false;
    var dx = active.lastX - active.startX;
    var dy = active.lastY - active.startY;
    return dx * dx + dy * dy <= TOUCH_SCROLL_CANCEL_PX * TOUCH_SCROLL_CANCEL_PX;
  }

  function useScrollSafeCreateHint(pointerType) {
    return (
      pointerType === "touch" ||
      pointerType === "pen" ||
      isMobileDayPager()
    );
  }

  function hideHint(dayBody) {
    var hint = dayBody && dayBody.querySelector(".sched-press-hint");
    if (hint) {
      hint.hidden = true;
      hint.classList.remove("is-holding", "is-ready", "is-charging", "is-move");
      hint.removeAttribute("data-time");
      hint.style.top = "";
      hint.style.height = "";
      hint.style.removeProperty("--hold-ms");
    }
    hideDragGhost();
  }

  function lockPagerScroll() {
    if (active && active.pagingDay) return;
    var pager = getDaysPager();
    if (!pager || lockedPagerScrollLeft == null) return;
    if (Math.abs(pager.scrollLeft - lockedPagerScrollLeft) > 0.5) {
      pager.scrollLeft = lockedPagerScrollLeft;
    }
  }

  function setDraggingUi(on) {
    document.documentElement.classList.toggle("qa-dragging", !!on);
    if (!on) document.documentElement.classList.remove("qa-paging-day");
    var pager = getDaysPager();
    if (on) {
      if (pager) lockedPagerScrollLeft = pager.scrollLeft;
    } else {
      // Po dragu vždy dorovnej den – jinak zůstanou sloty „ujeté“ doleva
      var idx = mobileDayIndex;
      lockedPagerScrollLeft = null;
      if (active) active.pagingDay = false;
      if (isMobileDayPager()) {
        requestAnimationFrame(function () {
          realignMobileDay(idx);
        });
      } else {
        resetAllDragEventStyles();
        hideDragGhost();
      }
    }
  }

  function updateEventTimeLabel(el, slot, durMin) {
    if (!el) return;
    var startMin = slot.hour * 60 + slot.minute;
    var endMin = startMin + (durMin || 60);
    var endH = Math.floor(endMin / 60) % 24;
    var endM = endMin % 60;
    var range = formatTime(slot.hour, slot.minute) + "–" + formatTime(endH, endM);
    var timeEl = el.querySelector(".ev-time");
    if (timeEl) {
      timeEl.textContent = range;
      return;
    }
    var sub = el.querySelector(".ev-sub");
    if (!sub) return;
    var cenaEl = el.querySelector(".ev-cena");
    if (cenaEl) {
      sub.innerHTML = "";
      var t = document.createElement("span");
      t.className = "ev-time";
      t.textContent = range;
      sub.appendChild(t);
      sub.appendChild(cenaEl);
      sub.classList.add("ev-sub--pronajem");
      return;
    }
    sub.textContent = range;
  }

  function positionMovedEvent(dayBody, slot) {
    if (!active || !active.eventEl) return;
    var el = active.eventEl;
    if (el.parentNode !== dayBody) {
      dayBody.appendChild(el);
    }
    el.style.setProperty("--off", String(slot.offsetMin));
    el.setAttribute("data-off", String(slot.offsetMin));
    el.classList.add("is-lit", "is-dragging-ev");
    updateEventTimeLabel(el, slot, active.durMin || 60);

    // Ne fixed position na .ev (rozbije layout). Originál skryj, ukazuj ghost.
    clearDragFixedStyles(el);
    el.style.opacity = "0";
    el.style.pointerEvents = "none";
    positionDragGhost(dayBody, slot, active.durMin || 60);
  }

  function restoreMovedEvent() {
    if (!active || !active.eventEl || !active.origin) return;
    var el = active.eventEl;
    var origin = active.origin;
    if (origin.nextSibling && origin.nextSibling.parentNode === origin.parent) {
      origin.parent.insertBefore(el, origin.nextSibling);
    } else {
      origin.parent.appendChild(el);
    }
    el.style.setProperty("--off", String(origin.off));
    el.setAttribute("data-off", String(origin.off));
    clearDragFixedStyles(el);
    if (origin.subText != null) {
      var sub = el.querySelector(".ev-sub");
      if (sub) sub.textContent = origin.subText;
    }
    el.classList.remove("is-lit", "is-dragging-ev", "is-being-moved");
  }

  function unbindTouchDrag() {
    if (!touchDragBound) return;
    touchDragBound = false;
    document.removeEventListener("touchmove", onTouchMoveDrag, true);
    document.removeEventListener("touchend", onTouchEndDrag, true);
    document.removeEventListener("touchcancel", onTouchCancelDrag, true);
  }

  function bindTouchDrag() {
    if (touchDragBound) return;
    touchDragBound = true;
    document.addEventListener("touchmove", onTouchMoveDrag, { passive: false, capture: true });
    document.addEventListener("touchend", onTouchEndDrag, { passive: true, capture: true });
    document.addEventListener("touchcancel", onTouchCancelDrag, { passive: true, capture: true });
  }

  function onTouchMoveDrag(ev) {
    if (!active || !active.armed || active.finishing) return;
    if (!ev.touches || !ev.touches.length) return;
    var t = ev.touches[0];
    if (ev.cancelable) ev.preventDefault();
    moveActiveTo(t.clientX, t.clientY);
  }

  function onTouchEndDrag(ev) {
    if (!active || !active.armed || active.finishing) return;
    var t = ev.changedTouches && ev.changedTouches[0];
    finishArmedDrag(t ? t.clientX : active.lastX, t ? t.clientY : active.lastY);
  }

  function onTouchCancelDrag() {
    if (!active || !active.armed || active.finishing) return;
    // Gesture opravdu zrušen systémem – nezapínat formulář, jen zahodit
    clearActive();
    unbindTouchDrag();
  }

  function finishArmedDrag(clientX, clientY) {
    if (!active || !active.armed || active.finishing) return;
    active.finishing = true;
    if (clientX != null && clientY != null) {
      moveActiveTo(clientX, clientY, true);
    }
    var targetDay = mobileDayIndex;
    commitActive();
    unbindTouchDrag();
    if (isMobileDayPager()) {
      realignMobileDay(targetDay);
    }
  }

  function clearActive(opts) {
    if (!active) return;
    if (active.timer) clearTimeout(active.timer);
    if (active.hintTimer) clearTimeout(active.hintTimer);
    active.pagingDay = false;
    stopAutoScroll();
    hideHint(active.dayBody);
    hideDragGhost();
    unbindTouchDrag();
    var keepMoved = opts && opts.keepMoved;
    if (active.mode === "move" && active.eventEl) {
      if (!keepMoved) restoreMovedEvent();
      else {
        clearDragFixedStyles(active.eventEl);
        active.eventEl.classList.remove("is-lit", "is-dragging-ev", "is-being-moved");
      }
    }
    if (active.dayBody) {
      active.dayBody.classList.remove("is-longpressing", "is-dragging");
      try {
        if (active.pointerId != null) active.dayBody.releasePointerCapture(active.pointerId);
      } catch (e) {}
    }
    setDraggingUi(false);
    active = null;
  }

  function hintDur() {
    if (active && active.mode === "move" && active.durMin) return active.durMin;
    return defaultDurMin();
  }

  function armActive() {
    if (!active || active.armed) return;
    active.armed = true;
    active.finishing = false;
    active.dragChangedDay = false;
    if (active.mode === "move") {
      suppressEventClick = true;
      if (active.eventEl) {
        active.eventEl.classList.add("is-lit", "is-dragging-ev");
      }
    } else if (active.mode === "create" && active.slot) {
      // Zachovej přesný čas z místa stisku; grabOffset = pozice prstu ve slotu
      var hourH = active.slot.hourH || 115;
      var slotTop = active.slot.offsetMin * (hourH / 60);
      var layout = getDragLayoutRects(active.dayBody);
      var y = active.lastY != null ? active.lastY : active.startY;
      active.grabOffsetY = Math.max(0, y - layout.dayRect.top - slotTop);
    }
    if (active.dayBody) {
      active.dayBody.classList.add("is-longpressing", "is-dragging");
      try {
        if (active.pointerId != null) active.dayBody.setPointerCapture(active.pointerId);
      } catch (e) {}
    }
    setDraggingUi(true);
    // Touch stream přežije iOS pointercancel – drag běží dál až do puštění
    if (active.pointerType === "touch" || active.pointerType === "pen") {
      bindTouchDrag();
    }
    if (active.mode !== "move") {
      showHint(active.dayBody, active.slot, true, hintDur());
    } else {
      positionMovedEvent(active.dayBody, active.slot);
    }
    if (navigator.vibrate) {
      try {
        navigator.vibrate(14);
      } catch (e) {}
    }
  }

  function moveActiveTo(clientX, clientY, fromAutoScroll) {
    if (!active) return;
    active.lastX = clientX;
    active.lastY = clientY;
    if (active.armed) lockPagerScroll();
    if (!fromAutoScroll) {
      maybeEdgeFlipDay(clientX);
      ensureAutoScroll();
    }

    var nextBody = active.dayBody;
    var hit = dayBodyFromPoint(clientX, clientY);
    if (isMobileDayPager() && active.armed) {
      // Při dragu zůstaň na logickém cílovém dni (pager se nehýbe)
      nextBody = active.dayBody;
    } else if (isMobileDayPager()) {
      var days = getPagerDayEls();
      var visible = days[getVisiblePagerDayIndex()];
      var visibleBody = visible && visible.querySelector("[data-longpress-slot]");
      if (hit && visibleBody && hit === visibleBody) {
        nextBody = hit;
      } else if (visibleBody) {
        nextBody = visibleBody;
      } else if (hit) {
        nextBody = hit;
      }
    } else if (hit) {
      nextBody = hit;
    }
    if (!nextBody) nextBody = active.dayBody;
    if (!nextBody) return;

    var day = nextBody.closest(".sched-day");
    var dateStr = day && day.getAttribute("data-date");
    var dowRaw = day && day.getAttribute("data-dow");
    if (!isStaly && !dateStr && !isMobileDayPager()) return;
    if (isStaly && dowRaw == null && day) {
      // nech pokračovat s active.dow
    }

    if (nextBody !== active.dayBody) {
      hideHint(active.dayBody);
      active.dayBody.classList.remove("is-longpressing", "is-dragging");
      active.dayBody = nextBody;
      if (dateStr) active.dateStr = dateStr;
      if (dowRaw != null) active.dow = parseInt(dowRaw, 10);
      nextBody.classList.add("is-longpressing");
      if (active.armed) nextBody.classList.add("is-dragging");
      if (active.mode === "move" && active.eventEl && active.eventEl.parentNode !== nextBody) {
        nextBody.appendChild(active.eventEl);
      }
      try {
        nextBody.setPointerCapture(active.pointerId);
      } catch (e) {}
    } else {
      if (dateStr) active.dateStr = dateStr;
      if (dowRaw != null) active.dow = parseInt(dowRaw, 10);
    }
    active.slot = slotFromEvent(nextBody, clientY, active.grabOffsetY || 0);
    if (active.mode === "move") positionMovedEvent(nextBody, active.slot);
    else showHint(nextBody, active.slot, active.armed, hintDur());
  }

  function submitMove(eventId, dateStr, timeStr, eventEl, origin) {
    var originParent = origin && origin.parent ? origin.parent : null;
    if (!moveUrl || !eventId) {
      if (eventEl && origin) restoreEventToOrigin(eventEl, origin);
      return;
    }
    fetch(moveUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
        Accept: "application/json",
      },
      body: JSON.stringify({
        id: eventId,
        date: dateStr,
        time: timeStr,
      }),
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (result) {
        if (result.data && result.data.ok) {
          finalizeMovedEvent(eventEl, result.data, originParent);
          return;
        }
        window.alert((result.data && result.data.error) || "Nepodařilo se přesunout.");
        if (eventEl && origin) restoreEventToOrigin(eventEl, origin);
        else if (eventEl) reflowDayLanes(eventEl.parentNode);
      })
      .catch(function () {
        window.alert("Chyba spojení. Zkuste to znovu.");
        if (eventEl && origin) restoreEventToOrigin(eventEl, origin);
        else if (eventEl) reflowDayLanes(eventEl.parentNode);
      });
  }

  function commitActive() {
    if (!active || !active.armed) {
      clearActive();
      return;
    }
    var date = active.dateStr;
    var dow = active.dow;
    var timeStr = formatTime(active.slot.hour, active.slot.minute);
    var mode = active.mode;
    var eventId = active.eventId;
    var eventEl = active.eventEl;
    var origin = active.origin;
    var unchangedMove =
      mode === "move" &&
      origin &&
      origin.off === active.slot.offsetMin &&
      (isStaly ? origin.dow === dow : origin.dateStr === date);

    if (unchangedMove && eventEl) {
      // Long-press bez posunu → otevřít editaci (jako tap)
      if (isStaly) {
        var hraciRaw = (eventEl.getAttribute("data-hraci") || "").trim();
        var hraciIds = hraciRaw
          ? hraciRaw.split(",").map(function (x) {
              return parseInt(x, 10);
            }).filter(function (n) {
              return Number.isFinite(n);
            })
          : [];
        clearActive();
        openModal({
          id: eventEl.getAttribute("data-id"),
          dow: parseInt(eventEl.getAttribute("data-dow") || "0", 10),
          time: eventEl.getAttribute("data-time") || timeStr,
          delka: parseInt(eventEl.getAttribute("data-dur") || "60", 10),
          trener: eventEl.getAttribute("data-trener") || "",
          format: eventEl.getAttribute("data-format") || "",
          kurt: eventEl.getAttribute("data-kurt") || "",
          poznamka: eventEl.getAttribute("data-poznamka") || "",
          hraci: hraciIds,
          cena: eventEl.getAttribute("data-cena") || "",
          cena_hodina: eventEl.getAttribute("data-cena-hodina") || "",
          rezervujici: eventEl.getAttribute("data-rezervujici") || "",
          sezona: eventEl.getAttribute("data-kurt") || "",
          kurt_misto: eventEl.getAttribute("data-kurt-misto") || "",
        });
        return;
      }
      if (isPronajem) {
        clearActive();
        openModal({
          id: eventEl.getAttribute("data-id"),
          date: date,
          time: eventEl.getAttribute("data-time") || timeStr,
          delka: parseInt(eventEl.getAttribute("data-dur") || "60", 10),
          sezona: eventEl.getAttribute("data-kurt") || "",
          kurt: eventEl.getAttribute("data-kurt") || "",
          kurt_misto: eventEl.getAttribute("data-kurt-misto") || "",
          cena: eventEl.getAttribute("data-cena") || "",
          cena_hodina: eventEl.getAttribute("data-cena-hodina") || "",
          rezervujici: eventEl.getAttribute("data-rezervujici") || "",
          poznamka: eventEl.getAttribute("data-poznamka") || "",
        });
        return;
      }
      clearActive();
      openTreningEditFromEl(eventEl, date);
      return;
    }

    clearActive({ keepMoved: mode === "move" });
    if (mode === "move") {
      if (isStaly) submitStalyMove(eventId, dow, timeStr, eventEl, origin);
      else submitMove(eventId, date, timeStr, eventEl, origin);
      return;
    }
    if (isStaly) openModal({ dow: dow, time: timeStr });
    else openModal({ date: date, time: timeStr });
  }

  function readEventOffsetMin(el) {
    if (!el) return 0;
    var raw = el.getAttribute("data-off");
    if (raw == null || raw === "") {
      raw = el.style.getPropertyValue("--off");
    }
    if (raw == null || String(raw).trim() === "") {
      try {
        raw = window.getComputedStyle(el).getPropertyValue("--off");
      } catch (e) {
        raw = "";
      }
    }
    var n = parseFloat(String(raw).trim());
    return Number.isFinite(n) ? n : 0;
  }

  function startInteraction(ev, dayBody, dateStr, extras) {
    clearActive();
    var grabOffsetY = 0;
    var slot;
    var origin = null;
    var day = dayBody.closest(".sched-day");
    var dow = day ? parseInt(day.getAttribute("data-dow") || "0", 10) : 0;
    if (extras && extras.mode === "move" && extras.eventEl) {
      var offMin = readEventOffsetMin(extras.eventEl);
      slot = slotFromOffset(dayBody, offMin);
      var evRect = extras.eventEl.getBoundingClientRect();
      grabOffsetY = ev.clientY - evRect.top;
      if (!Number.isFinite(grabOffsetY) || grabOffsetY < 0) grabOffsetY = 0;
      var maxGrab = Math.max(0, evRect.height - 4);
      if (grabOffsetY > maxGrab) grabOffsetY = maxGrab;
      var subEl = extras.eventEl.querySelector(".ev-sub");
      origin = {
        parent: extras.eventEl.parentNode,
        nextSibling: extras.eventEl.nextSibling,
        off: offMin,
        subText: subEl ? subEl.textContent : null,
        dateStr: dateStr,
        dow: dow,
      };
      if (extras.eventEl.getAttribute("data-dow") != null) {
        dow = parseInt(extras.eventEl.getAttribute("data-dow"), 10);
        origin.dow = dow;
      }
    } else {
      slot = slotFromEvent(dayBody, ev.clientY, 0);
    }
    var pointerType = ev.pointerType || "mouse";
    active = {
      pointerId: ev.pointerId,
      dayBody: dayBody,
      dateStr: dateStr,
      dow: dow,
      startX: ev.clientX,
      startY: ev.clientY,
      lastX: ev.clientX,
      lastY: ev.clientY,
      slot: slot,
      timer: null,
      hintTimer: null,
      armed: false,
      grabOffsetY: grabOffsetY,
      mode: (extras && extras.mode) || "create",
      eventEl: (extras && extras.eventEl) || null,
      eventId: (extras && extras.eventId) || null,
      durMin: (extras && extras.durMin) || null,
      origin: origin,
      pointerType: pointerType,
    };
    // is-longpressing (touch-action:none) až po arm – jinak iOS ruší tap kvůli scroll/swipe
    if (active.mode === "move" && active.eventEl) {
      active.eventEl.classList.add("is-lit");
    }
    // Ghosty v předpokládaném: jen klik, bez drag
    if (active.mode === "ghost") {
      return;
    }

    // create na mobilu: nejdřív klid (scroll), teprve pak nabíjecí efekt → arm
    if (active.mode === "create" && useScrollSafeCreateHint(pointerType)) {
      active.hintTimer = setTimeout(function () {
        if (!active || active.armed || active.mode !== "create") return;
        if (!touchCreateStill()) {
          clearActive();
          return;
        }
        showHint(active.dayBody, active.slot, false, defaultDurMin(), TOUCH_CHARGE_MS);
        active.timer = setTimeout(function () {
          if (!active) return;
          if (!touchCreateStill()) {
            clearActive();
            return;
          }
          armActive();
        }, TOUCH_CHARGE_MS);
      }, TOUCH_HINT_DELAY_MS);
      return;
    }

    // Desktop create: nabíjení hned + arm po holdMs
    if (active.mode === "create") {
      showHint(dayBody, slot, false, defaultDurMin());
    }
    active.timer = setTimeout(function () {
      if (!active) return;
      armActive();
    }, holdMs);
  }

  function onPointerDown(ev) {
    if (ev.pointerType === "mouse" && ev.button !== 0) return;
    if (overlay && !overlay.hidden) return;
    var target = ev.target;
    if (!target || !target.closest) return;
    if (target.closest(".sched-day-strip, .sched-toolbar, .sched-help, button:not(.ev), input, select, a.button, .qa-overlay")) {
      return;
    }

    var stalyEl = target.closest("button.ev--staly-slot:not(.ev--ghost-slot), button.ev--staly, .ev.ev--staly-slot:not(.ev--ghost-slot)");
    if (stalyEl && isStaly) {
      var dayBodySt = stalyEl.closest("[data-longpress-slot]");
      var daySt = dayBodySt && dayBodySt.closest(".sched-day");
      var dateSt = daySt && daySt.getAttribute("data-date");
      if (!dayBodySt) return;
      var durSt = parseInt(stalyEl.getAttribute("data-dur") || "60", 10);
      if (!Number.isFinite(durSt) || durSt <= 0) durSt = 60;
      startInteraction(ev, dayBodySt, dateSt || "", {
        mode: "move",
        eventEl: stalyEl,
        eventId: stalyEl.getAttribute("data-id"),
        durMin: durSt,
      });
      return;
    }

    var ghostEl = target.closest("button.ev--ghost-slot, .ev.ev--ghost-slot");
    if (ghostEl && isPredpokladany) {
      var dayBodyGh = ghostEl.closest("[data-longpress-slot]");
      var dayGh = dayBodyGh && dayBodyGh.closest(".sched-day");
      var dateGh = ghostEl.getAttribute("data-date") || (dayGh && dayGh.getAttribute("data-date"));
      if (!dayBodyGh) return;
      startInteraction(ev, dayBodyGh, dateGh || "", {
        mode: "ghost",
        eventEl: ghostEl,
        eventId: ghostEl.getAttribute("data-ghost-slot-id") || ghostEl.getAttribute("data-predpokladany-id"),
        durMin: parseInt(ghostEl.getAttribute("data-dur") || "60", 10) || 60,
      });
      return;
    }

    var pronajemEl = target.closest("button.ev--pronajem-slot, .ev.ev--pronajem-slot");
    if (pronajemEl && isPronajem && !isStaly) {
      var dayBodyPr = pronajemEl.closest("[data-longpress-slot]");
      var dayPr = dayBodyPr && dayBodyPr.closest(".sched-day");
      var datePr = dayPr && dayPr.getAttribute("data-date");
      if (!dayBodyPr || !datePr) return;
      var durPr = parseInt(pronajemEl.getAttribute("data-dur") || "60", 10);
      if (!Number.isFinite(durPr) || durPr <= 0) durPr = 60;
      startInteraction(ev, dayBodyPr, datePr, {
        mode: "move",
        eventEl: pronajemEl,
        eventId: pronajemEl.getAttribute("data-id"),
        durMin: durPr,
      });
      return;
    }

    var eventEl = target.closest("a.ev");
    if (eventEl) {
      if (!moveUrl || isStaly) return;
      var dayBodyEv = eventEl.closest("[data-longpress-slot]");
      var dayEv = dayBodyEv && dayBodyEv.closest(".sched-day");
      var dateEv = dayEv && dayEv.getAttribute("data-date");
      if (!dayBodyEv || !dateEv) return;
      var dur = parseInt(eventEl.getAttribute("data-dur") || "60", 10);
      if (!Number.isFinite(dur) || dur <= 0) dur = 60;
      startInteraction(ev, dayBodyEv, dateEv, {
        mode: "move",
        eventEl: eventEl,
        eventId: eventEl.getAttribute("data-id"),
        durMin: dur,
      });
      return;
    }

    var dayBody = target.closest("[data-longpress-slot]");
    if (!dayBody) return;
    var day = dayBody.closest(".sched-day");
    var dateStr = day && day.getAttribute("data-date");
    if (!isStaly && !dateStr) return;
    if (isStaly && (!day || day.getAttribute("data-dow") == null)) return;

    startInteraction(ev, dayBody, dateStr || "", { mode: "create" });
  }

  function onPointerMove(ev) {
    if (!active || ev.pointerId !== active.pointerId) return;
    active.lastX = ev.clientX;
    active.lastY = ev.clientY;
    var dx = ev.clientX - active.startX;
    var dy = ev.clientY - active.startY;
    var absDx = Math.abs(dx);
    var absDy = Math.abs(dy);
    var dist2 = dx * dx + dy * dy;
    var armThreshold = active.pointerType === "touch" ? 16 : MOVE_CANCEL_PX;
    var axisThreshold = active.pointerType === "touch" ? 22 : 18;

    if (!active.armed) {
      // Před long-press: swipe dne / scroll → zrušit create (scroll zůstane nativní)
      if (active.mode === "create" || active.mode === "ghost") {
        var scrollCancel =
          active.pointerType === "touch" || active.pointerType === "pen"
            ? TOUCH_SCROLL_CANCEL_PX
            : axisThreshold;
        if (absDx >= scrollCancel && absDx > absDy * 1.05) {
          clearActive();
          return;
        }
        if (absDy >= scrollCancel && absDy > absDx * 1.05) {
          clearActive();
          return;
        }
        if (
          (active.pointerType === "touch" || active.pointerType === "pen") &&
          dist2 > scrollCancel * scrollCancel
        ) {
          clearActive();
          return;
        }
      }
      // Před long-press u existujícího slotu: větší pohyb = scroll/omyl
      if (active.mode === "move") {
        if (active.pointerType === "touch") {
          if (dist2 > 28 * 28) {
            clearActive();
          }
          return;
        }
        // Myš: tažení rovnou spustí přesun
        if (dist2 > armThreshold * armThreshold) {
          if (active.timer) {
            clearTimeout(active.timer);
            active.timer = null;
          }
          if (ev.cancelable) ev.preventDefault();
          armActive();
          moveActiveTo(ev.clientX, ev.clientY);
        }
        return;
      }
      return;
    }

    if (ev.cancelable) ev.preventDefault();
    moveActiveTo(ev.clientX, ev.clientY);
  }

  function onPointerUp(ev) {
    if (!active || ev.pointerId !== active.pointerId) return;
    if (active.armed) {
      // Na touch řeší dokončení touchend (přežije pointercancel)
      if (active.pointerType === "touch" || active.pointerType === "pen") {
        if (touchDragBound) return;
      }
      finishArmedDrag(ev.clientX, ev.clientY);
      return;
    }

    // Krátký klik na zapsaný trénink (<a.ev>) → sheet (stejný jako Nový trénink)
    if (
      active.mode === "move" &&
      active.eventEl &&
      active.eventEl.tagName === "A" &&
      !isStaly &&
      !isPronajem
    ) {
      var editEl = active.eventEl;
      var editDate = active.dateStr;
      clearActive();
      openTreningEditFromEl(editEl, editDate);
      return;
    }

    // Stálý: krátký klik na slot = upravit
    if (isStaly && active.mode === "move" && active.eventEl) {
      var el = active.eventEl;
      var hraciRaw = (el.getAttribute("data-hraci") || "").trim();
      var hraciIds = hraciRaw
        ? hraciRaw.split(",").map(function (x) {
            return parseInt(x, 10);
          }).filter(function (n) {
            return Number.isFinite(n);
          })
        : [];
      clearActive();
      openModal({
        id: el.getAttribute("data-id"),
        dow: parseInt(el.getAttribute("data-dow") || "0", 10),
        time: el.getAttribute("data-time") || "",
        delka: parseInt(el.getAttribute("data-dur") || "60", 10),
        trener: el.getAttribute("data-trener") || "",
        format: el.getAttribute("data-format") || "",
        kurt: el.getAttribute("data-kurt") || "",
        poznamka: el.getAttribute("data-poznamka") || "",
        hraci: hraciIds,
        cena: el.getAttribute("data-cena") || "",
        cena_hodina: el.getAttribute("data-cena-hodina") || "",
        rezervujici: el.getAttribute("data-rezervujici") || "",
        sezona: el.getAttribute("data-kurt") || "",
        kurt_misto: el.getAttribute("data-kurt-misto") || "",
      });
      return;
    }

    // Pronájem (aktuální): krátký klik na slot = upravit
    if (isPronajem && active.mode === "move" && active.eventEl) {
      var pel = active.eventEl;
      var pelDate = active.dateStr;
      clearActive();
      openModal({
        id: pel.getAttribute("data-id"),
        date: pelDate,
        time: pel.getAttribute("data-time") || "",
        delka: parseInt(pel.getAttribute("data-dur") || "60", 10),
        sezona: pel.getAttribute("data-kurt") || "",
        kurt: pel.getAttribute("data-kurt") || "",
        kurt_misto: pel.getAttribute("data-kurt-misto") || "",
        cena: pel.getAttribute("data-cena") || "",
        cena_hodina: pel.getAttribute("data-cena-hodina") || "",
        rezervujici: pel.getAttribute("data-rezervujici") || "",
        poznamka: pel.getAttribute("data-poznamka") || "",
      });
      return;
    }

    if (isPredpokladany && active.mode === "ghost" && active.eventEl) {
      var gel = active.eventEl;
      var gHraci = (gel.getAttribute("data-hraci") || "").trim();
      var gIds = gHraci
        ? gHraci.split(",").map(function (x) {
            return parseInt(x, 10);
          }).filter(function (n) {
            return Number.isFinite(n);
          })
        : [];
      clearActive();
      openModal({
        ghost: true,
        ghostSlotId: gel.getAttribute("data-ghost-slot-id") || "",
        predpokladanyId: gel.getAttribute("data-predpokladany-id") || "",
        date: gel.getAttribute("data-date") || active.dateStr,
        dow: parseInt(gel.getAttribute("data-dow") || "0", 10),
        time: gel.getAttribute("data-time") || "",
        delka: parseInt(gel.getAttribute("data-dur") || "60", 10),
        trener: gel.getAttribute("data-trener") || "",
        format: gel.getAttribute("data-format") || "",
        kurt: gel.getAttribute("data-kurt") || "",
        poznamka: gel.getAttribute("data-poznamka") || "",
        hraci: gIds,
        cena: gel.getAttribute("data-cena") || "",
        cena_hodina: gel.getAttribute("data-cena-hodina") || "",
        rezervujici: gel.getAttribute("data-rezervujici") || "",
        sezona: gel.getAttribute("data-kurt") || "",
        kurt_misto: gel.getAttribute("data-kurt-misto") || "",
      });
      return;
    }
    // Krátký tap na prázdný čas → nic (formulář jen po long-press + puštění)
    clearActive();
  }

  function onPointerCancel(ev) {
    if (!active || ev.pointerId !== active.pointerId) return;
    if (active.armed) {
      // iOS při tažení zruší pointer – drag pokračuje přes touchmove/touchend
      active.pointerLost = true;
      if (!touchDragBound && (active.pointerType === "touch" || active.pointerType === "pen")) {
        bindTouchDrag();
      }
      return;
    }
    clearActive();
  }

  document.addEventListener("pointerdown", onPointerDown, { passive: true });
  document.addEventListener("pointermove", onPointerMove, { passive: false });
  document.addEventListener("pointerup", onPointerUp, { passive: true });
  document.addEventListener("pointercancel", onPointerCancel, { passive: true });
  document.addEventListener(
    "click",
    function (ev) {
      if (!suppressEventClick) return;
      var link = ev.target && ev.target.closest && ev.target.closest("a.ev");
      if (!link) return;
      ev.preventDefault();
      ev.stopPropagation();
      suppressEventClick = false;
    },
    true
  );
  document.addEventListener(
    "contextmenu",
    function (ev) {
      if (ev.target && ev.target.closest && ev.target.closest("[data-longpress-slot].is-longpressing")) {
        ev.preventDefault();
      }
    },
    true
  );

  if (hraciAddBtn) {
    hraciAddBtn.addEventListener("click", function (ev) {
      ev.preventDefault();
      if (!hraciRows) return;
      var row = createPlayerRow();
      hraciRows.appendChild(row);
      var input = row.querySelector(".qa-hraci-search");
      if (input) input.focus();
    });
  }


  cancelBtns.forEach(function (btn) {
    btn.addEventListener("click", function (ev) {
      ev.preventDefault();
      closeModal();
    });
  });

  if (saveBtn) {
    saveBtn.addEventListener("click", function (ev) {
      ev.preventDefault();
      submitQuickAdd(false);
    });
  }

  if (saveNextBtn) {
    saveNextBtn.addEventListener("click", function (ev) {
      ev.preventDefault();
      submitQuickAdd(true);
    });
  }

  if (deleteBtn) {
    deleteBtn.addEventListener("click", function (ev) {
      ev.preventDefault();
      if (
        pendingSlot &&
        (pendingSlot.mode === "staly" ||
          pendingSlot.mode === "projected" ||
          pendingSlot.mode === "ghost")
      ) {
        submitStalyDelete();
      } else if (isPronajem) {
        submitPronajemDelete();
      } else if (pendingSlot && pendingSlot.mode === "aktualni" && pendingSlot.id) {
        submitTreningDelete();
      } else {
        submitStalyDelete();
      }
    });
  }

  // Fallback: klasický click na <a.ev> → sheet, ne change stránka
  document.addEventListener(
    "click",
    function (ev) {
      if (isStaly || isPronajem) return;
      var link = ev.target && ev.target.closest && ev.target.closest("a.ev");
      if (!link || !link.closest(".sched-day-body")) return;
      ev.preventDefault();
      if (active) return;
      // Pointer-up už sheet otevřel – jen zablokuj navigaci
      if (overlay && !overlay.hidden) return;
      var day = link.closest(".sched-day");
      openTreningEditFromEl(link, day ? day.getAttribute("data-date") : "");
    },
    true
  );

  if (form) {
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      submitQuickAdd(false);
    });
  }

  if (overlay) {
    overlay.addEventListener("click", function (ev) {
      if (ev.target === overlay) closeModal();
    });
  }

  if (materializeBtn && materializeUrl) {
    materializeBtn.addEventListener("click", function (ev) {
      ev.preventDefault();
      var matNoun = isPronajem ? "pronájmy" : "tréninky";
      if (!window.confirm("Zapsat ze stálého rozvrhu " + matNoun + " na dnešek?")) return;
      materializeBtn.disabled = true;
      fetch(materializeUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken(),
          Accept: "application/json",
        },
        body: JSON.stringify({ trener: trener || "" }),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          materializeBtn.disabled = false;
          if (result.data && result.data.ok) {
            window.alert(
              "Zapsáno: " +
                result.data.created +
                " " +
                matNoun +
                " na " +
                result.data.date +
                " (už bylo: " +
                result.data.skipped_exist +
                ", přeskočeno: " +
                result.data.skipped_user +
                ")."
            );
            reloadKeepingScroll();
            return;
          }
          window.alert((result.data && result.data.error) || "Nepodařilo se zapsat.");
        })
        .catch(function () {
          materializeBtn.disabled = false;
          window.alert("Chyba spojení. Zkuste to znovu.");
        });
    });
  }

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && overlay && !overlay.hidden) closeModal();
  });

  if (formatSel) formatSel.addEventListener("change", syncSluzbaDelkaUi);
  if (kurtSel) kurtSel.addEventListener("change", syncSluzbaDelkaUi);

  restoreSchedScroll();
  initMobileDayPager();

  // Scroll/swipe přes slot → zruš pending tap/long-press (neotevírej sheet)
  (function bindScrollCancelsSlotTap() {
    function onScroll() {
      if (!active || active.armed) return;
      if (active.pointerType !== "touch" && active.pointerType !== "pen") return;
      suppressEventClick = true;
      clearActive();
    }
    var vertical = getSchedScrollEl();
    if (vertical) vertical.addEventListener("scroll", onScroll, { passive: true });
    var pager = getDaysPager();
    if (pager) pager.addEventListener("scroll", onScroll, { passive: true });
  })();

  if (isStaly) {
    try {
      var contRaw = sessionStorage.getItem(STALY_CONTINUE_KEY);
      if (contRaw) {
        sessionStorage.removeItem(STALY_CONTINUE_KEY);
        var cont = JSON.parse(contRaw);
        setTimeout(function () {
          openModal({
            dow: cont.dow,
            time: cont.time,
            trener: cont.trener,
            format: cont.format,
            kurt: cont.kurt,
            delka: cont.delka,
            hraci: [],
            poznamka: "",
            rezervujici: cont.rezervujici || "",
            cena: cont.cena || "",
            sezona: cont.sezona || "",
            kurt_misto: cont.kurt || "",
          });
        }, 80);
      }
    } catch (e) {}
  }

  if (pronajemSezonaSel && isPronajem) {
    pronajemSezonaSel.addEventListener("change", function () {
      applyPronajemSezona(pronajemSezonaSel.value, "", "", false);
    });
  }
})();
