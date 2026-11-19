(function () {
  "use strict";

  function textOf(el) {
    return (el && el.textContent ? el.textContent : "").replace(/\s+/g, " ").trim();
  }

  function activeNavLabel() {
    var active =
      document.querySelector(".ts-topnav a.is-active") ||
      document.querySelector(".ts-topnav a.active") ||
      document.querySelector(".topnav a.is-active") ||
      document.querySelector(".topnav a.active");
    var label = textOf(active);
    return label || "";
  }

  function cleanTitle(raw, isChangeList, isAddForm) {
    var t = String(raw || "").trim();
    if (!t) return t;

    var m =
      t.match(/^Vyberte položku\s+(.+?)\s+ke změně\.?$/i) ||
      t.match(/^Select\s+(.+?)\s+to change\.?$/i) ||
      t.match(/^Wählen Sie\s+(.+?)\s+zum Ändern\.?$/i);
    if (m) {
      if (isChangeList) {
        var nav = activeNavLabel();
        if (nav) return nav;
      }
      return m[1];
    }

    m = t.match(/^Přidejte?\s+(.+)$/i) || t.match(/^Add\s+(.+)$/i);
    if (m) return m[1];

    m = t.match(/^Změnit\s+(.+)$/i) || t.match(/^Change\s+(.+)$/i);
    if (m) return m[1];

    if (isAddForm) {
      var navAdd = activeNavLabel();
      if (navAdd) return navAdd;
    }

    return t;
  }

  function eyebrowFor(isChangeList, isAddForm, isChangeForm) {
    if (isChangeList) return "Seznam";
    if (isAddForm) return "Nový záznam";
    if (isChangeForm) return "Detail";
    return "Přehled";
  }

  function polishAddLink(a) {
    if (!a || a.dataset.tsPhPolished === "1") return;
    var raw = textOf(a);
    var m =
      raw.match(/^(.+?)\s*:\s*přidat$/i) ||
      raw.match(/^Add\s+(.+)$/i) ||
      raw.match(/^Přidejte?\s+(.+)$/i) ||
      raw.match(/^Přidat\s+(.+)$/i);
    if (!m && !/^Přidat$/i.test(raw)) return;
    a.dataset.tsPhPolished = "1";
    // Changelist: pill „+ Přidat …“ (stejně jako Ceník). Formuláře: krátké „Přidat“.
    if (document.body && document.body.classList.contains("change-list")) {
      var label = m ? m[1] : "";
      if (!label) {
        var titleEl = document.querySelector(".ts-page-head__title");
        label = titleEl ? textOf(titleEl) : "";
        if (label) label = label.charAt(0).toLowerCase() + label.slice(1);
      }
      a.textContent = label ? "+ Přidat " + label : "+ Přidat";
      return;
    }
    a.innerHTML = "";
    var plus = document.createElement("span");
    plus.className = "ts-btn-plus";
    plus.setAttribute("aria-hidden", "true");
    // Plus kreslí CSS (geometricky vycentrovaný); textový „+“ bývá opticky mimo střed
    plus.textContent = "";
    a.appendChild(plus);
    a.appendChild(document.createTextNode(" Přidat"));
  }

  function findTools(content) {
    return (
      content.querySelector(":scope > .object-tools") ||
      content.querySelector("#content-main > .object-tools") ||
      content.querySelector(".object-tools")
    );
  }

  function enhance() {
    var content = document.getElementById("content");
    if (!content || content.querySelector(":scope > .ts-page-head")) return;

    var body = document.body;
    var isChangeList = body.classList.contains("change-list");
    var isChangeForm = body.classList.contains("change-form");
    var isAddForm = body.classList.contains("add-form") || body.classList.contains("add");
    if (!isChangeList && !isChangeForm) return;

    var h1 = content.querySelector(":scope > h1");
    if (!h1) return;

    var tools = findTools(content);

    var head = document.createElement("header");
    head.className = "ts-page-head";
    head.setAttribute("data-ts-page-head", "");

    var textWrap = document.createElement("div");
    textWrap.className = "ts-page-head__text";

    var eye = document.createElement("p");
    eye.className = "ts-page-head__eyebrow";
    eye.textContent = eyebrowFor(isChangeList, isAddForm, isChangeForm);

    var titleText = cleanTitle(textOf(h1), isChangeList, isAddForm);
    h1.classList.add("ts-page-head__title");
    h1.textContent = titleText;

    var rule = document.createElement("span");
    rule.className = "ts-page-head__rule";
    rule.setAttribute("aria-hidden", "true");

    textWrap.appendChild(eye);
    textWrap.appendChild(h1);
    textWrap.appendChild(rule);
    head.appendChild(textWrap);

    if (tools) {
      tools.querySelectorAll("a.addlink").forEach(polishAddLink);
      head.appendChild(tools);
    }

    var first = content.firstElementChild;
    content.insertBefore(head, first);
  }

  function boot() {
    // Po sidebar.js (is-active na nav), ať má changelist správný pluralní nadpis
    enhance();
    window.requestAnimationFrame(function () {
      var title = document.querySelector(".ts-page-head__title");
      if (!title || !document.body.classList.contains("change-list")) return;
      var nav = activeNavLabel();
      if (nav && textOf(title) !== nav) title.textContent = nav;
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
