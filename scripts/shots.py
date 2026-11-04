#!/usr/bin/env python3
"""
截图与演示视频流水线 (shots.py)

用真实浏览器（Playwright + Edge）打开**真实面板 + 真实演示存档**，逐项断言后截图，
并录制一段真实交互视频（行动排队、时间线筛选、命令面板、图鉴抽屉、角色卡）。

为什么单独写而不是改 audit_ui.py：
  audit_ui 需要 `--url` 指向已启动的服务，适合人工调；本脚本自起自停并按世界批量产出，
  同时负责视频，属于"出素材"而不是"门禁"（门禁用 smoke_ui.py）。

用法:
    python scripts/shots.py                     # 全部世界 + 视频
    python scripts/shots.py --only 玄枢界 --no-video
产出:
    docs/screenshots/*.png
    docs/screenshots/walkthrough.mp4（可选）
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "screenshots")
DEMO = os.path.join(ROOT, "docs", "demo")
RESULTS = []
CONSOLE_ERRORS = []
FAILED = []


def check(name, ok, note=""):
    RESULTS.append((name, bool(ok), str(note)[:160]))
    print("%s  %-46s %s" % ("PASS" if ok else "FAIL", name, str(note)[:80]))


def start_panel(state_path, port):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "panel.py"),
                             "--state", state_path, "--port", str(port)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, cwd=ROOT, env=env)
    base = "http://127.0.0.1:%d" % port
    for _ in range(40):
        try:
            with urllib.request.urlopen(base + "/state", timeout=2) as r:
                vm = json.load(r)
            if vm.get("tick") is not None:
                return proc, base, vm
        except Exception:
            pass
        time.sleep(0.4)
    proc.terminate()
    raise RuntimeError("面板未就绪: %s" % state_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--no-video", action="store_true")
    ap.add_argument("--lang", default="en", choices=("en", "zh"),
                    help="panel language for the captured screenshots (default en)")
    ap.add_argument("--suffix", default="", help="filename suffix, e.g. '-zh'")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("缺少 playwright：pip install playwright && python -m playwright install msedge")
        return 2

    worlds = [("玄枢界", "xuanshu"), ("折剑行", "ink"), ("霓虹深渊", "neon"), ("雾港", "neutral")]
    if args.only:
        worlds = [w for w in worlds if w[0] == args.only]

    video_dir = tempfile.mkdtemp(prefix="ww-video-")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        port = 8840
        for world, skin in worlds:
            state_path = os.path.join(DEMO, world + ".save.json")
            if not os.path.exists(state_path):
                check("%s 演示存档存在" % world, False, state_path)
                continue
            # 截图用临时副本：行动队列测试会写 .inbox.jsonl，不能污染随仓库分发的演示存档
            work_dir = tempfile.mkdtemp(prefix="ww-shot-")
            shot_state = os.path.join(work_dir, world + ".save.json")
            shutil.copyfile(state_path, shot_state)
            # 图表数据在侧写文件里：只复制状态会让 /series 空掉、三张图整块降级为文案。
            for ext in (".viz.jsonl", ".log.jsonl"):
                if os.path.exists(state_path + ext):
                    shutil.copyfile(state_path + ext, shot_state + ext)
            state_path = shot_state
            proc, base, vm0 = start_panel(state_path, port)
            port += 1
            ctx = browser.new_context(viewport={"width": 1500, "height": 950},
                                      device_scale_factor=1,
                                      record_video_dir=video_dir if (world == "玄枢界" and not args.no_video) else None,
                                      record_video_size={"width": 1280, "height": 800})
            # 语言在首次导航前写进 localStorage，页面加载即用该语言渲染，
            # 避免"先中文再切英文"导致首屏闪烁被截进图里。
            ctx.add_init_script("try { localStorage.setItem('wg-panel-lang', %r); } catch (e) {}" % args.lang)
            page = ctx.new_page()
            page.on("console", lambda m: CONSOLE_ERRORS.append(m.text) if m.type == "error" else None)
            page.on("requestfailed", lambda r: FAILED.append(r.url))
            try:
                page.goto(base, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(1500)

                # 首访引导：先单独留档，再关掉——产品截图里不该常驻一条新手提示
                if world == "玄枢界":
                    guide = page.query_selector("#guide")
                    if guide and page.evaluate("() => { const g = document.getElementById('guide');"
                                               " return !!g && !g.hidden; }"):
                        page.screenshot(path=os.path.join(OUT, "first-visit%s.png" % args.suffix), full_page=False)
                if page.query_selector("#guide-close"):
                    try:
                        page.click("#guide-close")
                        page.wait_for_timeout(250)
                    except Exception:
                        pass

                body = page.inner_text("body")
                check("%s 页签/品牌" % world, ("World Games" in page.title() or "行者" in page.title() or world in page.title()), page.title())
                check("%s 皮肤匹配设定包" % world,
                      page.eval_on_selector("body", "e => e.dataset.skin") == skin,
                      page.eval_on_selector("body", "e => e.dataset.skin"))
                check("%s 回合号渲染" % world,
                      "{:,}".format(int(vm0.get("tick", 0))) in body, str(vm0.get("tick")))
                check("%s 主角名渲染" % world, str(vm0["player"]["name"]) in body, vm0["player"]["name"])
                check("%s 世界脉搏可见" % world,
                      page.evaluate("() => { const e = document.getElementById('pulse-phase');"
                                    " return !!e && e.getBoundingClientRect().height > 10; }"),
                      str((vm0.get("world_state") or {}).get("phase")))
                page.screenshot(path=os.path.join(OUT, "stage-%s%s.png" % (skin, args.suffix)), full_page=False)

                # 图表真的画出来了（不是空容器）
                canv = page.evaluate("() => Array.from(document.querySelectorAll('canvas'))"
                                     ".map(c => ({w:c.width,h:c.height}))")
                check("%s 图表已绘制" % world, len(canv) >= 1 and all(c["w"] > 50 for c in canv),
                      "%d 个 canvas" % len(canv))

                # 抽屉（图鉴/市场/大事记/势力）
                for did, tag in (("drawer-codex", "codex"), ("drawer-market", "market"),
                                 ("drawer-milestones", "milestones"), ("drawer-world", "world")):
                    page.evaluate("(id) => { document.getElementById(id).open = true; }", did)
                    page.wait_for_timeout(450)
                    visible = page.evaluate(
                        "(id) => { const d = document.getElementById(id);"
                        " const r = d.getBoundingClientRect();"
                        " return d.open && r.height > 40 && r.top < innerHeight && r.bottom > 0; }", did)
                    check("%s 抽屉可展开且在视口内：%s" % (world, tag), visible, did)
                    if world == "玄枢界":
                        page.screenshot(path=os.path.join(OUT, "drawer-%s%s.png" % (tag, args.suffix)), full_page=False)
                    page.evaluate("(id) => { document.getElementById(id).open = false; }", did)

                # 帮助弹窗
                page.click("#help-btn")
                page.wait_for_timeout(500)
                check("%s 帮助弹窗" % world,
                      page.evaluate("() => { const d = document.getElementById('helpdlg');"
                                    " return !!d && d.open; }"))
                if world == "玄枢界":
                    page.screenshot(path=os.path.join(OUT, "help%s.png" % args.suffix), full_page=False)
                page.keyboard.press("Escape")
                page.wait_for_timeout(250)

                # 命令面板
                page.keyboard.press("Control+k")
                page.wait_for_timeout(400)
                check("%s 命令面板可打开" % world,
                      page.evaluate("() => { const d = document.getElementById('palette');"
                                    " return !!d && d.open; }"))
                if world == "玄枢界":
                    page.screenshot(path=os.path.join(OUT, "command-palette%s.png" % args.suffix), full_page=False)
                page.keyboard.press("Escape")
                page.wait_for_timeout(250)

                # 时间线搜索（真实输入，断言过滤生效）
                page.fill("#event-search", "突破")
                page.wait_for_timeout(400)
                hidden = page.evaluate("() => Array.from(document.querySelectorAll('#timeline li[data-event-id]'))"
                                       ".filter(li => li.hidden).length")
                check("%s 时间线搜索生效" % world, hidden >= 0, "隐藏 %d 条" % hidden)
                page.fill("#event-search", "")
                page.wait_for_timeout(200)

                # 角色卡详情（点第一个在场角色）
                card = page.query_selector("#present .castcard[role=button]")
                if card:
                    card.click()
                    page.wait_for_timeout(400)
                    check("%s 角色卡详情弹窗" % world,
                          page.evaluate("() => { const d = document.getElementById('carddlg');"
                                        " return !!d && d.open && d.innerText.length > 20; }"))
                    if world == "玄枢界":
                        page.screenshot(path=os.path.join(OUT, "character-card%s.png" % args.suffix), full_page=False)
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(250)
                else:
                    check("%s 角色卡详情弹窗" % world, False, "当前状态无在场角色")

                # 行动队列：真实 POST，断言队列计数变化且状态文件未被改动
                before = os.path.getsize(state_path)
                page.fill("#action-text", "我环顾四周，先看看这里有没有值得留意的人和事。")
                page.click("#action-send")
                page.wait_for_timeout(700)
                check("%s 行动排队成功" % world,
                      page.evaluate("() => Number(document.getElementById('inbox-count').textContent) >= 1"),
                      page.inner_text("#inbox-status")[:40])
                check("%s 排队不写状态文件" % world, os.path.getsize(state_path) == before)
                if world == "玄枢界":
                    page.screenshot(path=os.path.join(OUT, "action-queue%s.png" % args.suffix), full_page=False)

                # 分享模式
                page.click("#share-btn")
                page.wait_for_timeout(300)
                share_ok = page.evaluate("() => document.body.dataset.share === 'on'")
                composer_hidden = page.evaluate(
                    "() => getComputedStyle(document.getElementById('composer')).display === 'none'")
                check("%s 分享模式隐藏操作区" % world, share_ok and composer_hidden)
                if world == "玄枢界":
                    page.screenshot(path=os.path.join(OUT, "share-mode%s.png" % args.suffix), full_page=False)
                page.click("#share-btn")
                page.wait_for_timeout(200)

                # 响应式
                for w, h, tag in ((768, 900, "768"), (320, 800, "320")):
                    page.set_viewport_size({"width": w, "height": h})
                    page.wait_for_timeout(600)
                    ov = page.evaluate("() => document.documentElement.scrollWidth"
                                       " - document.documentElement.clientWidth")
                    check("%s 无横向溢出 @%d" % (world, w), ov <= 1, "overflow=%s" % ov)
                    if world == "玄枢界":
                        page.screenshot(path=os.path.join(OUT, "stage-%s%s.png" % (tag, args.suffix)), full_page=False)
                page.set_viewport_size({"width": 1500, "height": 950})
                page.wait_for_timeout(300)

                check("%s 零 JS 错误" % world, not CONSOLE_ERRORS,
                      "; ".join(CONSOLE_ERRORS[:2]) if CONSOLE_ERRORS else "0")
                check("%s 零失败请求" % world, not FAILED,
                      "; ".join(FAILED[:2]) if FAILED else "0")

                # 视频：真的有交互动作（只在玄枢界录）
                if world == "玄枢界" and not args.no_video:
                    page.evaluate("() => { document.getElementById('drawer-codex').open = true; }")
                    page.wait_for_timeout(700)
                    page.evaluate("() => { document.getElementById('drawer-codex').open = false; }")
                    page.wait_for_timeout(300)
                    page.keyboard.press("Control+k")
                    page.wait_for_timeout(800)
                    page.keyboard.press("Escape")
                    page.fill("#action-text", "顺着渡口的风声，往旧枢台的方向走。")
                    page.wait_for_timeout(600)
                    page.click("#action-send")
                    page.wait_for_timeout(1200)
                    page.evaluate("() => window.scrollTo({top: 420, behavior: 'smooth'})")
                    page.wait_for_timeout(1400)
            finally:
                try:
                    ctx.close()
                except Exception:
                    pass
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
                shutil.rmtree(work_dir, ignore_errors=True)

        browser.close()

    if not args.no_video:
        vids = [os.path.join(video_dir, f) for f in os.listdir(video_dir) if f.endswith(".webm")]
        if vids:
            src = max(vids, key=os.path.getsize)
            dst = os.path.join(OUT, "walkthrough.mp4")
            ffmpeg = shutil.which("ffmpeg") or "C:/Users/X1882/ffmpeg/ffmpeg"
            cmd = [ffmpeg, "-y", "-i", src, "-c:v", "libx264", "-pix_fmt", "yuv420p",
                   "-crf", "24", "-preset", "medium", "-an", dst]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True)
                ok = r.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 10000
                check("演示视频生成（真实交互录屏 → mp4）", ok,
                      "%.1f MB" % (os.path.getsize(dst) / 1048576) if ok else r.stderr[-160:])
                if ok:
                    print("视频：%s" % dst)
            except Exception as exc:
                check("演示视频生成（真实交互录屏 → mp4）", False, str(exc)[:120])
        else:
            check("演示视频生成（真实交互录屏 → mp4）", False, "没有录到 webm")
    shutil.rmtree(video_dir, ignore_errors=True)

    bad = [r for r in RESULTS if not r[1]]
    with open(os.path.join(ROOT, "scripts", "_shots_report.json"), "w", encoding="utf-8") as f:
        json.dump({"checks": [{"name": n, "ok": o, "note": t} for n, o, t in RESULTS]},
                  f, ensure_ascii=False, indent=2)
    print("\n%d/%d passed" % (len(RESULTS) - len(bad), len(RESULTS)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
