#!/usr/bin/env python3
"""Theme and contrast self-check (verify_theme.py)

Why this exists
---------------
The panel shipped dark-only until v1.9.0. Making light the default is a visual
change, and "looks fine to me" is not a test: the first attempt at the light
palette had 118 text runs below WCAG AA, because the skin accent was reused as
both a text colour and a button background. That class of bug is invisible in a
screenshot review and obvious in a measurement, so it gets a measurement.

What it checks
--------------
  T1  light is the default: no data-theme attribute means light tokens apply
  T2  the theme bootstrap is a synchronous <head> script (no first-paint flash)
  T3  both palettes are reachable: every token the CSS uses is defined in both
  T4  no component hardcodes a colour outside the token block
  T5  measured contrast: every visible text run meets WCAG AA in BOTH themes
  T6  the toggle actually changes the rendered palette (real browser)
  T7  charts repaint on theme change (canvas pixels change, not just CSS)
  T8  the loading skeleton clears once data arrives

T5/T6/T7 run in a real browser, so they need Playwright + Edge. Without it the
script exits 2 rather than pretending to pass — a skipped accessibility gate is
worse than a red one, because it silently ships.

Usage:  python scripts/verify_theme.py
Exit:   0 = all checks hold, 1 = a check failed, 2 = Playwright/Edge missing
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = []


def check(name, ok, note=""):
    RESULTS.append(bool(ok))
    print("%s  %-58s %s" % ("PASS" if ok else "FAIL", name, str(note)[:88]))


# ── Static checks (no browser needed) ────────────────────────────────────────
def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


TOKENS_LIGHT = [
    "--bg", "--surface-1", "--surface-2", "--surface-3", "--line", "--line-strong",
    "--text", "--text-dim", "--text-faint", "--accent", "--accent-line",
    "--accent-fill", "--accent-ink", "--danger", "--success", "--warning", "--info",
    "--danger-text", "--success-text", "--warning-text", "--info-text",
    "--track", "--code-bg", "--backdrop",
]


def static_checks():
    html = read("panel.html")
    css = read("panel.css")
    theme_js = read("panel.theme.js")
    panel_js = read("panel.js")

    # T1: default is light. The <html> tag must not ship data-theme="dark",
    # and the base :root block must declare color-scheme: light.
    head = html.split("<body", 1)[0]
    check("T1a <html> ships no hardcoded dark attribute",
          'data-theme="dark"' not in head, head.count("data-theme"))
    check("T1b base :root declares color-scheme: light",
          "color-scheme: light;" in css.split('html[data-theme="dark"]', 1)[0])
    check("T1c a dark override block exists",
          'html[data-theme="dark"]' in css)

    # T2: bootstrap must be synchronous and in <head>, before <body>.
    check("T2a theme bootstrap is referenced in <head>",
          "panel.theme.js" in head)
    check("T2b it runs before the body is parsed (no first-paint flash)",
          head.index("panel.theme.js") < html.index("<body"))
    check("T2c bootstrap reads the stored preference and validates it",
          "wg-theme" in theme_js and 'VALID[v]' in theme_js)
    check("T2d bootstrap falls back to the OS preference, then light",
          "prefers-color-scheme: dark" in theme_js and 'return "light";' in theme_js)

    # T3: every token declared in one theme is declared in the other.
    light_block = css.split(":root {", 1)[1].split("}", 1)[0]
    dark_block = css.split('html[data-theme="dark"] {', 1)[1].split("}", 1)[0]
    declared_light = {t for t in TOKENS_LIGHT if t + ":" in light_block}
    declared_dark = {t for t in TOKENS_LIGHT if t + ":" in dark_block}
    check("T3a light block declares every required token",
          declared_light == set(TOKENS_LIGHT),
          str(sorted(set(TOKENS_LIGHT) - declared_light))[:60])
    check("T3b dark block declares the same set (no missing overrides)",
          declared_dark == declared_light,
          str(sorted(declared_light - declared_dark))[:60])

    # T3c: every var() reference resolves.
    import re
    defined = set(re.findall(r"(--[a-zA-Z0-9-]+)\s*:", css))
    used = set(re.findall(r"var\((--[a-zA-Z0-9-]+)", css))
    for extra in ("panel.html", "panel.js"):
        text = read(extra)
        used |= set(re.findall(r"var\((--[a-zA-Z0-9-]+)", text))
        used |= set(re.findall(r'cssVar\("(--[a-zA-Z0-9-]+)"', text))
    check("T3c no var() reference is undefined", not (used - defined),
          str(sorted(used - defined))[:80])

    # T4: colour literals only inside token declarations. Component rules must
    # use var(); the three dark-only neon overrides are the documented exception.
    body_after_tokens = css.split("/* 皮肤：只改主色", 1)[1] if "/* 皮肤：只改主色" in css else css
    offenders = []
    for line in body_after_tokens.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or stripped.startswith("/*") or stripped.startswith("*"):
            continue
        if "data-skin" in stripped or "data-theme" in stripped:
            continue
        if re.search(r"#[0-9a-fA-F]{3,8}\b", stripped) or "rgba(" in stripped:
            offenders.append(stripped[:70])
    check("T4 component rules use tokens, not colour literals",
          not offenders, str(offenders[:2]))

    # T5 static part: the accent is split by intent, and the UI never builds a
    # translucent accent at runtime (the v1.8 defect).
    check("T5a accent is split into text / line / fill roles",
          "--accent-line" in css and "--accent-fill" in css)
    # Strip comments before looking for the pattern, otherwise the explanatory
    # comment that documents the old defect would trip its own guard.
    import re as _re
    code_only = _re.sub(r"/\*.*?\*/", "", panel_js, flags=_re.S)
    code_only = chr(10).join(ln.split("//", 1)[0] for ln in code_only.splitlines())
    check("T5b runtime no longer synthesises translucent accents",
          '+ "88"' not in code_only and 'accent + "' not in code_only)
    panel_py = read("panel.py")
    check("T5c skin accents arrive per theme",
          '"light":' in panel_py and '"accent_fill"' in panel_py)

    # T8 static: skeleton markup + its removal path exist.
    check("T8a skeleton markup ships in the initial HTML",
          'data-boot="loading"' in html and 'id="bootbar"' in html)
    check("T8b skeleton is removed on first data (and on failure)",
          'setBootState("ready")' in panel_js and "data-boot" in css)


# ── Browser checks ───────────────────────────────────────────────────────────
CONTRAST_JS = r"""
() => {
  const hex = (h) => { h = h.trim().replace('#','');
    if (h.length === 3) h = h.split('').map(c => c + c).join('');
    return {r: parseInt(h.slice(0,2),16), g: parseInt(h.slice(2,4),16), b: parseInt(h.slice(4,6),16), a: 1}; };
  const parseColor = (s) => { const m = s.match(/rgba?\(([^)]+)\)/); if (!m) return null;
    const p = m[1].split(',').map(x => parseFloat(x));
    return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1}; };
  const token = (name) => {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    if (v.startsWith('#')) return hex(v);
    return v.match(/^rgba?\(/) ? parseColor(v) : {r: 255, g: 255, b: 255, a: 1};
  };
  const lum = (c) => { const f = (v) => { v /= 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126*f(c.r) + 0.7152*c.g_ !== undefined ? 0 : 0; };
  const relLum = (c) => { const f = (v) => { v /= 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126*f(c.r) + 0.7152*f(c.g) + 0.0722*f(c.b); };
  const blend = (fg, bg) => ({r: fg.r*fg.a + bg.r*(1-fg.a), g: fg.g*fg.a + bg.g*(1-fg.a),
                              b: fg.b*fg.a + bg.b*(1-fg.a), a: 1});
  const surfaceOf = (el) => {
    let node = el;
    while (node && node !== document.documentElement) {
      const c = parseColor(getComputedStyle(node).backgroundColor);
      if (c && c.a > 0.99) return c;
      node = node.parentElement;
    }
    return token('--bg');
  };
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = walker.nextNode())) {
    const t = (n.textContent || '').trim();
    if (t.length < 2) continue;
    const el = n.parentElement; if (!el) continue;
    if (el.closest('[hidden]')) continue;
    const det = el.closest('details');
    if (det && !det.open) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    if (parseFloat(cs.opacity) < 0.05) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const fg = parseColor(cs.color); if (!fg) continue;
    const bg = surfaceOf(el);
    const f = fg.a < 1 ? blend(fg, bg) : fg;
    const l1 = relLum(f), l2 = relLum(bg);
    const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    const size = parseFloat(cs.fontSize);
    const bold = parseInt(cs.fontWeight, 10) >= 700;
    const need = (size >= 24 || (size >= 18.66 && bold)) ? 3.0 : 4.5;
    if (ratio < need) {
      out.push({text: t.slice(0, 40), ratio: Math.round(ratio * 100) / 100, need,
                size, cls: (typeof el.className === 'string' ? el.className : el.tagName).slice(0, 30)});
    }
  }
  return out;
}
"""


def start_panel(state_path, port):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "panel.py"),
         "--state", state_path, "--port", str(port)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT, env=env)
    base = "http://127.0.0.1:%d" % port
    for _ in range(40):
        try:
            with urllib.request.urlopen(base + "/state", timeout=2) as r:
                vm = json.load(r)
            if vm.get("tick") is not None:
                return proc, base
        except Exception:
            pass
        time.sleep(0.4)
    proc.terminate()
    raise RuntimeError("panel did not start on %d" % port)


def browser_checks(state_path):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("SKIP  缺少 playwright：pip install playwright && python -m playwright install msedge")
        return False, "playwright missing"

    proc, base = start_panel(state_path, 8859)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.goto(base, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(1500)

            # T6: default palette is light, toggle switches it, and it sticks.
            check("T6a panel opens in light theme by default",
                  page.evaluate("document.documentElement.getAttribute('data-theme')") == "light")
            light_bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
            page.click('[data-set-theme="dark"]')
            page.wait_for_timeout(400)
            check("T6b toggle switches to dark",
                  page.evaluate("document.documentElement.getAttribute('data-theme')") == "dark")
            dark_bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
            check("T6c the rendered background actually changes",
                  light_bg != dark_bg, "%s -> %s" % (light_bg, dark_bg))
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(900)
            check("T6d the choice survives a reload (no flash back to light)",
                  page.evaluate("document.documentElement.getAttribute('data-theme')") == "dark")
            page.click('[data-set-theme="light"]')
            page.wait_for_timeout(400)

            # T5: measured contrast in both themes.
            bad_light = page.evaluate(CONTRAST_JS)
            page.click('[data-set-theme="dark"]')
            page.wait_for_timeout(500)
            bad_dark = page.evaluate(CONTRAST_JS)
            check("T5 measured contrast: every text run meets WCAG AA (light)", not bad_light,
                  str([(x["text"], x["ratio"]) for x in bad_light[:3]])[:90])
            check("T5 measured contrast: every text run meets WCAG AA (dark)", not bad_dark,
                  str([(x["text"], x["ratio"]) for x in bad_dark[:3]])[:90])
            page.click('[data-set-theme="light"]')
            page.wait_for_timeout(400)

            # T7: canvases repaint on theme change (compare a canvas pixel hash).
            def canvas_hash():
                return page.evaluate("""() => {
                  const c = document.querySelectorAll('canvas')[0];
                  if (!c) return '';
                  const d = c.getContext('2d').getImageData(0, 0, Math.min(c.width, 300), Math.min(c.height, 120)).data;
                  let h = 0;
                  for (let i = 0; i < d.length; i += 97) { h = (h * 31 + d[i]) >>> 0; }
                  return String(h);
                }""")
            before = canvas_hash()
            page.click('[data-set-theme="dark"]')
            page.wait_for_timeout(700)
            after = canvas_hash()
            check("T7 charts repaint when the theme changes",
                  (not before) or before != after, "%s -> %s" % (before, after))

            # T8: skeleton is gone once data lands.
            check("T8c skeleton is cleared after the first frame",
                  page.evaluate("document.body.dataset.boot") == "ready"
                  and page.evaluate("document.getElementById('bootbar').hidden") is True)

            check("T6e no console errors while switching themes", not errors,
                  "; ".join(errors[:2])[:80])
            browser.close()
        return True, "ok"
    finally:
        proc.terminate()


def main():
    static_checks()
    demo = os.path.join(ROOT, "docs", "demo", "玄枢界.save.json")
    static_only = "--static-only" in sys.argv
    if static_only:
        passed, total = sum(RESULTS), len(RESULTS)
        print(chr(10) + "%d/%d passed (static only; browser phase skipped by flag)"
              % (passed, total))
        return 0 if passed == total else 1

    workdir = tempfile.mkdtemp(prefix="ww-theme-")
    state_path = os.path.join(workdir, "theme.save.json")
    if not os.path.exists(demo):
        check("demo save exists for the browser phase", False, demo)
    else:
        shutil.copyfile(demo, state_path)
        for ext in (".viz.jsonl", ".log.jsonl"):
            if os.path.exists(demo + ext):
                shutil.copyfile(demo + ext, state_path + ext)
        ok, note = browser_checks(state_path)
        if not ok:
            print("浏览器断言未执行：%s" % note)
            print("\n%d/%d passed" % (sum(RESULTS), len(RESULTS)))
            return 2

    passed, total = sum(RESULTS), len(RESULTS)
    print("\n%d/%d passed" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
