/*
 World Games · theme bootstrap

 Why this file exists
 --------------------
 The panel must never flash the wrong palette. If the theme were applied from
 panel.js (which loads at the end of <body>), the browser would paint the
 default light theme first and repaint dark a moment later.

 So this is the smallest possible synchronous script, loaded in <head>:
 it reads the stored preference and writes one attribute on <html>.
 No rendering, no data access, no state writes.

 Order of preference:
   1. explicit user choice stored in localStorage ("light" / "dark")
   2. the OS preference (prefers-color-scheme)
   3. light — the product default, see panel.css header

 Export surface: window.PanelTheme { get, set, cycle, current }
 The toggle button in the top bar also calls PanelTheme.set().
*/

(function (global) {
  "use strict";

  var KEY = "wg-theme";
  var VALID = { light: true, dark: true };

  function stored() {
    try {
      var v = global.localStorage.getItem(KEY);
      return VALID[v] ? v : "";
    } catch (e) {
      /* private mode / storage disabled: fall through to the OS preference */
      return "";
    }
  }

  function osPreference() {
    try {
      if (global.matchMedia && global.matchMedia("(prefers-color-scheme: dark)").matches) {
        return "dark";
      }
    } catch (e) { /* very old browser */ }
    return "light";
  }

  function current() {
    var attr = document.documentElement.getAttribute("data-theme");
    return VALID[attr] ? attr : "light";
  }

  function apply(theme) {
    var next = VALID[theme] ? theme : "light";
    document.documentElement.setAttribute("data-theme", next);
    var meta = document.querySelector('meta[name="theme-color"]:not([media])');
    if (meta) meta.setAttribute("content", next === "dark" ? "#0d0f13" : "#f6f4ee");
    return next;
  }

  function set(theme, persist) {
    var next = apply(theme);
    if (persist !== false) {
      try { global.localStorage.setItem(KEY, next); } catch (e) { /* ignore */ }
    }
    global.dispatchEvent(new CustomEvent("panelthemechange", { detail: { theme: next } }));
    return next;
  }

  function cycle() {
    return set(current() === "dark" ? "light" : "dark");
  }

  // Apply before first paint: this block runs while the parser is in <head>.
  apply(stored() || osPreference());

  global.PanelTheme = { get: stored, set: set, cycle: cycle, current: current };
})(window);
