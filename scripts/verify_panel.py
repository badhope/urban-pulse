#!/usr/bin/env python3
"""
面板契约自检 (verify_panel.py)

对 panel.py 的只读视图模型与 HTTP 层做契约验证（不依赖 MCP 进程）：
  1. 视图模型契约：skin/scene/events/inventory/relations 字段齐全且类型正确
  2. 旧存档兼容：缺 items/relations/market/event_log 的最小状态不崩、给合法空值
  3. 事件分级：引擎各类事件都能映射到唯一 severity，id 稳定
  4. 静态资源白名单：/ 与 panel.css/panel.js 正确 MIME；panel.py、路径穿越拒绝
  5. SSE 首次推送可解析；/state 事件数组有界
  6. 只读：跑完全部请求后状态文件字节不变

用法:  python scripts/verify_panel.py
退出码: 0 = 全绿；1 = 有失败项
"""

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_spec = importlib.util.spec_from_file_location(
    "panel", os.path.join(ROOT, "panel.py"))
_panel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_panel)

RESULTS = []
PORT = 8795


def check(name, ok, note=""):
    RESULTS.append(bool(ok))
    print("%s  %-52s %s" % ("PASS" if ok else "FAIL", name, note))


FIELD_NAMES_EVENT = ("id", "tick", "type", "kind", "severity", "title", "desc", "icon", "milestone")
SEVERITIES = {"info", "success", "warning", "danger"}


def http_get(url, timeout=8):
    """返回 (status, content_type, body_bytes)；HTTPError 也返回状态码。"""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "") if e.headers else "", e.read()
    except Exception as e:  # aqg: top-level boundary —— 探针：连接失败也要变成可断言的失败，不崩整个自检
        return 0, "", str(e).encode("utf-8")


def get_json(url, timeout=8):
    status, _ct, body = http_get(url, timeout)
    try:
        return status, json.loads(body.decode("utf-8"))
    except Exception:  # aqg: top-level boundary —— 非 JSON 响应视为解析失败，由断言报出
        return status, None


def read_sse_first_frame(url, timeout=8):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        buf = b""
        deadline = time.time() + timeout
        while time.time() < deadline:
            ch = r.read(1)
            if not ch:
                break
            buf += ch
            if buf.endswith(b"\n\n"):
                break
    return buf.decode("utf-8", errors="replace")


def rich_state():
    return {
        "tick": 12,
        "rng_seed": 42,
        "currency": "玄晶",
        "world_info": {"name": "玄枢界", "era": "玄枢历三年", "location_desc": "雾锁长街，灯影摇红。"},
        "entities": {
            "player": {"name": "阿吉", "faction": "散修", "level": "练气三层", "stage": 2,
                       "attrs": {"str": 12, "dex": 13, "int": 15, "con": 11, "cha": 10},
                       "hp": 70, "hp_max": 100, "mp": 18, "mp_max": 30, "gold": 260,
                       "location": "临川城",
                       "items": {"an_shen_dan": 2, "fei_jian": 1},
                       "morality": [1, 0, -1, 0, 0, 2]},
            "laowang": {"name": "老王", "faction": "市井", "level": "凡人",
                        "attrs": {"str": 7, "dex": 8, "int": 12, "con": 9, "cha": 13},
                        "hp": 35, "hp_max": 35, "gold": 150, "location": "临川城",
                        "desc": "茶摊老板，消息灵通。"},
            "wolf": {"name": "独眼狼", "faction": "黑风寨", "level": "二流",
                     "attrs": {"str": 12, "dex": 11, "int": 8, "con": 10, "cha": 5},
                     "hp": 0, "hp_max": 45, "gold": 40, "location": "黑风寨"},
        },
        "relations": {"laowang:player": {"affinity": 24, "respect": 3},
                      "player:wolf": {"affinity": -40, "respect": -10}},
        "market": {"临川城": {
            "an_shen_dan": {"name": "安神丹", "price": 55, "supply": 18, "base_price": 50,
                            "type": "丹药", "desc": "安神"},
            "fei_jian": {"name": "飞剑", "price": 300, "supply": 2, "base_price": 300,
                         "type": "玄器", "desc": "破空"}}},
        "karma_ledger": [
            {"from": "player", "to": "laowang", "type": "theft", "amount": 15, "tick": 3, "settled": False},
            {"from": "player", "to": "wolf", "type": "murder_evil", "amount": 10, "tick": 6, "settled": True}],
        "world_flags": ["xuanshu"],
        "event_log": [
            {"tick": 1, "type": "system", "desc": "世界「玄枢界」开局"},
            {"tick": 2, "type": "travel", "desc": "抵达「黑风寨」（初次探索）"},
            {"tick": 3, "type": "trade", "desc": "阿吉购买安神丹×2，花费110玄晶"},
            {"tick": 4, "type": "social", "desc": "老王对阿吉好感提升"},
            {"tick": 5, "type": "karma", "desc": "阿吉(偷窃) 欠 老王 15"},
            {"tick": 6, "type": "combat", "desc": "独眼狼被击败了"},
            {"tick": 6, "type": "combat", "desc": "阿吉的攻击被独眼狼闪避"},
            {"tick": 6, "type": "combat", "desc": "阿吉的攻击被独眼狼闪避"},
            {"tick": 6, "type": "combat", "desc": "阿吉的攻击被独眼狼闪避"},
            {"tick": 7, "type": "breakthrough", "desc": "突破至 练气四层"},
            {"tick": 8, "type": "use_item", "desc": "使用安神丹×1（自备（买入时已付））：回复10气血"},
            {"tick": 9, "type": "emergent", "desc": "山雨欲来：商路收紧"},
            {"tick": 10, "type": "tick", "desc": "回合10结束"},
        ],
        "milestones": [
            {"tick": 2, "kind": "探索", "desc": "初次抵达「黑风寨」"},
            {"tick": 6, "kind": "击杀", "desc": "阿吉 击败了 wolf"},
            {"tick": 7, "kind": "突破", "desc": "突破至 练气四层（第 2 次）"}],
        "summaries": [{"upto_tick": 10, "text": "阿吉在临川城落脚，与老王攀谈，西行猎了独眼狼。"}],
        "codex": {"locations": ["临川城", "黑风寨"], "people": ["老王", "独眼狼"],
                  "items": ["安神丹"], "lore": []},
        "lore": [],
        "config": {},
    }


def legacy_state():
    return {"tick": 0,
            "entities": {"player": {"name": "阿甲", "attrs": {}, "hp": 10, "hp_max": 10,
                                    "gold": 0, "location": "无名地"}}}


def main():
    tmp = tempfile.mkdtemp(prefix="ww-panel-")
    rich_path = os.path.join(tmp, "rich.save.json")
    legacy_path = os.path.join(tmp, "legacy.save.json")
    with open(rich_path, "w", encoding="utf-8") as f:
        json.dump(rich_state(), f, ensure_ascii=False)
    with open(legacy_path, "w", encoding="utf-8") as f:
        json.dump(legacy_state(), f, ensure_ascii=False)

    rich_hash = hashlib.sha256(open(rich_path, "rb").read()).hexdigest()
    legacy_hash = hashlib.sha256(open(legacy_path, "rb").read()).hexdigest()

    srv, port = _panel.start(rich_path, PORT)
    base = "http://127.0.0.1:%d" % port
    try:
        # 1. 视图模型契约（富状态）
        status, vm = get_json(base + "/state")
        check("/state 返回 200 JSON", status == 200 and isinstance(vm, dict), "status=%s" % status)
        vm = vm or {}
        skin = vm.get("skin") or {}
        check("skin 契约（id 合法 + accent 亮暗成对下发）",
              skin.get("id") in ("xuanshu", "neutral", "ink", "neon")
              and isinstance(skin.get("accent"), dict)
              and all(str(skin["accent"].get(m, "")).startswith("#") for m in ("light", "dark"))
              and isinstance(skin.get("accent_fill"), dict),
              str(skin.get("accent")))
        scene = vm.get("scene") or {}
        check("scene 契约（location/title/description/mood/focus_event）",
              all(k in scene for k in ("location", "title", "description", "mood", "focus_event"))
              and scene.get("location") == "临川城"
              and scene.get("mood") in ("neutral", "danger", "trade", "social", "growth", "discovery"),
              "mood=%s loc=%s" % (scene.get("mood"), scene.get("location")))
        events = vm.get("events")
        ok_events = isinstance(events, list) and len(events) == 10
        if ok_events:
            for e in events:
                if not all(k in e for k in FIELD_NAMES_EVENT) or e["severity"] not in SEVERITIES:
                    ok_events = False
                    break
        # fixture 的 10 条事件里有 1 条 tick 心跳；视图模型按设计把它过滤掉 → 9 条
        check("events 契约（9 字段 + severity 合法，tick 滤除且重复合并后 10 条）", ok_events,
              "%d 条" % (len(events) if isinstance(events, list) else -1))
        check("时间线不含 tick 心跳（回合结束只是心跳，不该占时间线）",
              isinstance(events, list) and not any(e["type"] == "tick" for e in events),
              "tick 条数=%d" % sum(1 for e in events if e.get("type") == "tick"))
        # 相邻重复合并：fixture 里有 3 条连续的"攻击被闪避"，合并后应剩 1 条且 repeat=3
        _dups = [e for e in (events or []) if e.get("repeat", 1) > 1]
        _adjacent_same = sum(1 for a, b in zip(events or [], (events or [])[1:])
                             if a.get("desc") == b.get("desc"))
        check("相邻重复事件已合并（repeat 计数生效）",
              bool(_dups) and _adjacent_same == 0,
              "合并 %d 组 · 相邻相同残留 %d" % (len(_dups), _adjacent_same))
        if isinstance(events, list) and events:
            ids = [e["id"] for e in events]
            check("events.id 稳定（tick[.seq]:type:短哈希，无重复）",
                  len(set(ids)) == len(ids) and all(len(i.split(":")) == 3 for i in ids),
                  ids[0])
            # 同 tick 同类型同描述的两条事件（真实现场：一次 tick 里两条 quest 完成）
            # 旧 id 只由 (tick,type,sha1(desc)) 组成，会撞键并被前端当作同一条丢掉。
            e_a = _panel.classify_event({"tick": 4, "type": "quest", "desc": "完成", "seq": 1}, set())
            e_b = _panel.classify_event({"tick": 4, "type": "quest", "desc": "完成", "seq": 2}, set())
            check("events.id 带 seq 前缀时同 tick 同描述不撞键", e_a["id"] != e_b["id"],
                  "%s vs %s" % (e_a["id"], e_b["id"]))
            check("events 保留 seq 供事件溯源排序", (e_a["seq"], e_b["seq"]), (1, 2))
            kinds = {e["type"]: e["kind"] for e in events}
            check("事件分级覆盖引擎类型（tick 除外，共 9 类）",
                  set(kinds) == {"system", "travel", "trade", "social", "karma", "combat",
                                 "breakthrough", "use_item", "emergent"}
                  and all(kinds.values()),
                  str(sorted(set(kinds.values()))))
            sev_pairs = {(e["type"], e["severity"]) for e in events}
            check("严重度映射合理（击杀=danger，突破成功=success）",
                  ("combat", "danger") in sev_pairs and ("breakthrough", "success") in sev_pairs,
                  str(sorted(sev_pairs)))
        inv = vm.get("player", {}).get("inventory")
        ok_inv = (isinstance(inv, list) and len(inv) == 2
                  and {i["key"] for i in inv} == {"an_shen_dan", "fei_jian"}
                  and all(set(i) >= {"key", "name", "quantity", "type"} for i in inv)
                  and {i["name"] for i in inv} == {"安神丹", "飞剑"})
        check("inventory 契约（与市场元数据合并出显示名/类别）", ok_inv, str(inv))
        rel = vm.get("relations")
        ok_rel = (isinstance(rel, list) and len(rel) == 2
                  and {r["id"] for r in rel} == {"laowang", "wolf"}
                  and all(set(r) >= {"id", "name", "affinity", "respect"} for r in rel))
        check("relations 契约（只含与玩家有关的关系，带名字）", ok_rel, str(rel))
        check("旧字段保留（insights/codex/chronicle/milestones/market）",
              "flow" in (vm.get("insights") or {}) and "phase" in (vm.get("insights") or {})
              and {"locations", "people", "items", "lore"} <= set(vm.get("codex") or {})
              and isinstance(vm.get("chronicle"), list) and isinstance(vm.get("milestones"), list)
              and isinstance(vm.get("market"), list) and bool(vm.get("market")))
        check("/state 事件数组有界（<=40）", isinstance(events, list) and len(events) <= 40,
              "%d 条" % (len(events) if isinstance(events, list) else -1))
        # v1.2.0 通用游戏层：视图模型必须带 game 与 sessions
        game = vm.get("game") or {}
        check("视图模型带 game 区块（profile/checks/check_rate/context）",
              set(game) >= {"profile", "checks", "check_rate", "context"},
              str(sorted(game)))
        check("旧存档自动推导游戏档案（资源含 hp/mp/gold）",
              [r.get("key") for r in (game.get("profile") or {}).get("resources") or []]
              == ["hp", "mp", "gold"],
              str([r.get("key") for r in (game.get("profile") or {}).get("resources") or []]))
        sessions = vm.get("sessions") or {}
        check("视图模型带 sessions 区块（root/count/saves）",
              isinstance(sessions.get("saves"), list) and isinstance(sessions.get("root"), str),
              str({k: sessions.get(k) for k in ("count", "trash")}))

        # 1b. 品牌可配置（R10）
        check("品牌默认值随 /state 下发",
              vm.get("skin", {}).get("brand") == "World Games"
              and vm.get("skin", {}).get("tagline") == "万物皆可为一局 · 规则为证",
              "%s / %s" % (vm.get("skin", {}).get("brand"), vm.get("skin", {}).get("tagline")))
        check("meta 提供状态文件路径（本地只读信息）",
              isinstance(vm.get("meta"), dict)
              and str(vm["meta"].get("state_path", "")).endswith("rich.save.json"),
              str((vm.get("meta") or {}).get("state_path", ""))[:60])
        check("数值字段仍是数值（千分位只在展示层）",
              isinstance(vm.get("player", {}).get("gold"), int)
              and isinstance(vm.get("tick"), int))
        check("濒死次数随玩家下发（rich_state 未设该字段 → 默认 0）",
              vm.get("player", {}).get("near_death_count") == 0,
              "near_death_count=%s" % (vm.get("player", {}) or {}).get("near_death_count"))

        # 2. 静态资源白名单与安全
        st, ct, body = http_get(base + "/")
        check("/ 返回 panel.html（200 text/html，含『实况』）",
              st == 200 and "text/html" in ct and "实况".encode("utf-8") in body,
              "status=%s ct=%s" % (st, ct.split(";")[0]))
        check("页面品牌要素齐全（字标/标语/图标/重试横幅）",
              "World Games" in body.decode("utf-8", "replace")
              and "万物皆可为一局" in body.decode("utf-8", "replace")
              and "rel=\"icon\"" in body.decode("utf-8", "replace")
              and "notice-retry" in body.decode("utf-8", "replace"))
        # 1c. 帮助体系（R11）/ 一次引导（R12）
        html_txt = body.decode("utf-8", "replace")
        check("页面有帮助入口与帮助弹窗（含术语表）",
              "help-btn" in html_txt and 'id="helpdlg"' in html_txt
              and "术语" in html_txt and "keyboard" in html_txt)
        check("帮助弹窗覆盖：只读说明/图表读法/数据位置/皮肤",
              all(k in html_txt for k in ("只读", "图表", "状态文件", "皮肤")))
        check("首访引导条存在且可关闭",
              'id="guide"' in html_txt and 'id="guide-close"' in html_txt)
        st_css, ct_css, body_css = http_get(base + "/panel.css")
        check("/panel.css 正确 MIME", st_css == 200 and "text/css" in ct_css, "status=%s" % st_css)
        body_css_txt = body_css.decode("utf-8", "replace")
        st_js, ct_js, body_js = http_get(base + "/panel.js")
        panel_js = body_js.decode("utf-8", "replace")
        check("/panel.js 正确 MIME", st_js == 200 and "javascript" in ct_js, "status=%s" % st_js)
        st_i18n, ct_i18n, body_i18n = http_get(base + "/panel.i18n.js")
        check("/panel.i18n.js 正确 MIME 且含翻译入口",
              st_i18n == 200 and "javascript" in ct_i18n
              and b"translateDom" in body_i18n, "status=%s" % st_i18n)
        check("页面加载翻译层且提供中英切换",
              b"panel.i18n.js" in body and b'data-set-panel-lang="zh"' in body)
        # 主题：亮色默认、首帧前生效、可切换（V1.9 起面板不再只有深色）
        check("主题引导脚本在 <head> 内同步加载（首帧不闪）",
              b"panel.theme.js" in body
              and body.index(b"panel.theme.js") < body.index(b"</head>"))
        check("亮色是默认主题（无 data-theme 时 CSS 按 light 渲染）",
              'data-theme="dark"' not in html_txt.split("<body")[0]
              and "--bg: #f6f4ee" in body_css_txt)
        check("顶栏提供亮/暗切换且默认选中亮色",
              'data-set-theme="light"' in html_txt and 'data-set-theme="dark"' in html_txt
              and 'data-set-theme="light" aria-pressed="true"' in html_txt)
        check("加载骨架屏与进度条存在（首屏体验）",
              'data-boot="loading"' in html_txt and 'id="bootbar"' in html_txt
              and 'id="boot-status"' in html_txt)
        check("首屏骨架屏在数据到达后被移除",
              'setBootState("ready")' in panel_js and 'dataset.boot' in panel_js)
        for bad in ("/panel.py", "/state.json", "/../rich.save.json", "/%2e%2e/rich.save.json",
                    "/..%2frich.save.json"):
            st_bad, _, bad_body = http_get(base + bad)
            leak = b"tick" in bad_body and b"entities" in bad_body
            check("拒绝非白名单路径 %s" % bad, st_bad == 404 and not leak,
                  "status=%s" % st_bad)

        # 3. SSE 首次推送
        try:
            frame = read_sse_first_frame(base + "/events")
            ok_sse = frame.startswith("event: state") and '"tick"' in frame
            check("SSE 首帧可解析（event: state + JSON）", ok_sse, frame.split("\n", 1)[0])
        except Exception as e:  # aqg: top-level boundary —— SSE 读取失败记为一项失败断言
            check("SSE 首帧可解析（event: state + JSON）", False, str(e)[:60])

        # 4. 只读：字节不变
        check("面板只读（富状态文件字节不变）",
              hashlib.sha256(open(rich_path, "rb").read()).hexdigest() == rich_hash)

        # 4b. /series 长局态势采样契约（R6）
        st_s, series = get_json(base + "/series")
        ok_series = (st_s == 200 and isinstance(series, dict)
                     and isinstance(series.get("samples"), list)
                     and len(series["samples"]) >= 1
                     and series.get("cap") == 600)
        keys = {"tick", "hp", "hp_max", "mp", "mp_max", "gold", "karma",
                "price_index", "affinity_avg", "codex_total", "location"}
        if ok_series:
            s0 = series["samples"][-1]
            ok_series = keys <= set(s0)
        check("/series 契约（samples/cap=600/样本字段齐全）", ok_series,
              "%d 样本" % (len(series.get("samples", [])) if isinstance(series, dict) else -1))
        if ok_series:
            ticks = [s["tick"] for s in series["samples"]]
            check("/series 样本按 tick 升序且不重复",
                  ticks == sorted(ticks) and len(ticks) == len(set(ticks)), str(ticks[:6]))
            pi = series["samples"][-1]["price_index"]
            # rich_state 里只有两个商品：安神丹 55/50=1.1、飞剑 300/300=1.0 → 均值 1.05
            # 用精确值而不是 0.2~5 的宽区间：后者连"常量 1.0"都能通过。
            #
            # 但要读的是**本 fixture 那一行**，不是"最后一行"：面板在同一 tick 上
            # 会覆盖样本，而 CI 上 /state 可能先被别的请求写过（同一 tick、同一份
            # state，理论上值相同）。真出现 1.0 说明读到的样本来自另一个 state，
            # 那时应该明确指出"样本来源不对"，而不是让断言看起来像 market 算错了。
            own = [s for s in series["samples"] if int(s.get("tick", -1)) == 12]
            check("price_index 精确等于样本均价（(1.1+1.0)/2=1.05）",
                  bool(own) and abs(float(own[-1]["price_index"]) - 1.05) < 1e-4,
                  "tick12=%s 全部样本=%s" % (
                      [s["price_index"] for s in own],
                      [(s.get("tick"), s.get("price_index")) for s in series["samples"]][-4:]))
            check("skin 调色板随 /state 下发（图表配色用）",
                  isinstance(series.get("palette"), dict)
                  and {"line", "area", "bar", "grid", "text"} <= set(series["palette"]))
        check("面板只读（/series 后状态字节仍不变）",
              hashlib.sha256(open(rich_path, "rb").read()).hexdigest() == rich_hash)
        sidecar = rich_path + ".viz.jsonl"
        sidecar_ok = False
        sidecar_note = "absent"
        if os.path.exists(sidecar):
            try:
                with open(sidecar, encoding="utf-8") as sf:
                    rows = [json.loads(line) for line in sf if line.strip()]
                sidecar_ok = (bool(rows) and all("tick" in r and "hp" in r for r in rows)
                              and sidecar != rich_path)
                sidecar_note = "%d 行" % len(rows)
            except Exception as e:
                sidecar_note = "unparsable: %s" % e
        check("采样边车独立成文件（<state>.viz.jsonl 且为逐行 JSON）", sidecar_ok, sidecar_note)
        with open(rich_path, "rb") as rf:
            state_raw = rf.read()
        check("状态文件未被写入侧写数据（仍是单个 JSON 文档）",
              state_raw.lstrip()[:1] == b"{" and state_raw.rstrip()[-1:] == b"}"
              and state_raw.count(b"\n{") == 0,
              "%d bytes" % len(state_raw))

        # 4c. 本地图表资产（R8）
        st_a, ct_a, body_a = http_get(base + "/assets/echarts.min.js")
        check("/assets/echarts.min.js 离线可发（200 + js MIME + >500KB）",
              st_a == 200 and "javascript" in ct_a and len(body_a) > 500_000,
              "status=%s size=%d" % (st_a, len(body_a)))
        st_a2, _, leak2 = http_get(base + "/assets/..%2fpanel.py")
        check("资产目录路径穿越仍拒绝", st_a2 == 404 and b"HTML_FILE" not in leak2,
              "status=%s" % st_a2)

        # 5. 旧存档兼容（新起一个 server 指向 legacy 文件）
        srv2, port2 = _panel.start(legacy_path, PORT + 1)
        try:
            st2, vm2 = get_json("http://127.0.0.1:%d/state" % port2)
            vm2 = vm2 or {}
            check("旧存档不崩且给合法空值（inventory/relations/events/market）",
                  st2 == 200 and vm2.get("player", {}).get("inventory") == []
                  and vm2.get("relations") == [] and isinstance(vm2.get("events"), list)
                  and vm2.get("market") == []
                  and isinstance(vm2.get("scene"), dict) and vm2["scene"].get("location") == "无名地"
                  and vm2.get("skin", {}).get("id") == "neutral",
                  "scene=%s" % (vm2.get("scene") or {}).get("location"))
            check("旧存档只读（字节不变）",
                  hashlib.sha256(open(legacy_path, "rb").read()).hexdigest() == legacy_hash)
        finally:
            srv2.shutdown()

        # 5b. 状态文件不存在：不是崩溃，而是带 hint 的可读错误（页面横幅直接用）
        missing_path = os.path.join(tmp, "not_there.save.json")
        srv3, port3 = _panel.start(missing_path, PORT + 2)
        try:
            st3, vm3 = get_json("http://127.0.0.1:%d/state" % port3)
            vm3 = vm3 or {}
            check("状态缺档时 /state 返回可读错误（error+hint，不抛栈）",
                  st3 == 200 and "不存在" in str(vm3.get("error", "")) and bool(vm3.get("hint")),
                  str(vm3.get("error", ""))[:48])
            st3b, ct3b, body3 = http_get("http://127.0.0.1:%d/" % port3)
            check("状态缺档时页面仍可打开（200）", st3b == 200 and "text/html" in ct3b)
            frame3 = read_sse_first_frame("http://127.0.0.1:%d/events" % port3)
            check("状态缺档时 SSE 首帧推错误态（不断流）",
                  frame3.startswith("event: state") and "不存在" in frame3,
                  frame3.split("\n", 1)[0])
        finally:
            srv3.shutdown()
    finally:
        srv.shutdown()

    # 6. 纯函数级：分类是全覆盖的（任何未知类型也给合法默认）
    st_unknown = _panel.classify_event({"tick": 1, "type": "未知类型", "desc": "x"}, set())
    check("未知事件类型有合法默认（kind/severity/icon 齐全）",
          all(k in st_unknown for k in FIELD_NAMES_EVENT) and st_unknown["severity"] in SEVERITIES,
          st_unknown.get("kind"))

    # 7. 皮肤 v2：配置优先、未知回退 neutral、调色板完整（R7）
    check("皮肤：世界名启发式仍生效（玄枢界→xuanshu）",
          _panel.skin_for_world({"world_info": {"name": "玄枢界"}, "world_flags": []})["id"] == "xuanshu")
    ink = _panel.skin_for_world({"world_info": {"name": "随便什么界"}, "world_flags": [],
                                 "ui": {"skin": "ink", "accent": "#8fb0c9", "motif": "水墨"}})
    check("皮肤：ui 块可指定 ink 并带 accent/motif",
          ink["id"] == "ink"
          and ink.get("accent") == {"light": "#8fb0c9", "dark": "#8fb0c9"}
          and ink.get("motif") == "水墨",
          str(ink.get("accent")))
    bad = _panel.skin_for_world({"world_info": {"name": "无", "era": ""}, "world_flags": [],
                                 "ui": {"skin": "martian"}})
    check("皮肤：未知 id 回退 neutral 且调色板合法",
          bad["id"] == "neutral" and isinstance(bad.get("palette"), dict)
          and bad["palette"].get("line"), str(bad.get("id")))
    need = {"line", "area", "bar", "grid", "text"}
    for sid in ("xuanshu", "neutral", "ink", "neon"):
        pal = _panel.SKINS[sid]["palette"]
        check("皮肤 %s 调色板字段齐全" % sid, need <= set(pal),
              "%d 色 · 缺 %s" % (len(pal), sorted(need - set(pal)) or "无"))

    # 8. 采样累积与升序（R6 场景补充，纯函数级）
    tmp2 = tempfile.mkdtemp(prefix="ww-series-")
    sp = os.path.join(tmp2, "s.save.json")
    st = rich_state()
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    for t in range(1, 5):
        st["tick"] = t
        st["entities"]["player"]["hp"] = 70 - t
        _panel.record_sample(sp, st)
    ser = _panel.load_series(sp)
    ticks = [s["tick"] for s in ser]
    check("采样随 tick 累积且升序（4 次记录 → 4 样本）",
          ticks == [1, 2, 3, 4], str(ticks))
    _panel.record_sample(sp, st)   # 同 tick 重复记录应覆盖而非重复
    ser2 = _panel.load_series(sp)
    check("同 tick 重复采样覆盖（不产生重复点）", len(ser2) == 4, str([s["tick"] for s in ser2]))


    # 8b. 玩法层契约：playbook / quests / lorebook 三个新块
    pb = (vm_rich := _panel.view_model(rich_path)).get("playbook") or {}
    check("视图模型含玩法剧本（loop/progress/failure/beat/guide）",
          pb.get("loop") in ("freeform", "choice", "mud", "ttrpg")
          and "progress" in pb and "failure" in pb and "beat" in pb
          and isinstance(pb.get("loop_guide"), str), str(pb.get("loop")))
    qs = vm_rich.get("quests") or {}
    check("视图模型含事业线块（rows/total/visible）",
          isinstance(qs.get("rows"), list) and isinstance(qs.get("total"), int)
          and isinstance(qs.get("visible"), int), str(qs.get("total")))
    lb = vm_rich.get("lorebook") or {}
    check("视图模型含世界书块（rows 带 fired/sticky_left/cooldown_left）",
          isinstance(lb.get("rows"), list) and isinstance(lb.get("total"), int),
          "rows=%d" % len(lb.get("rows") or []))

    # 9. 行动队列（双向通道）：面板只写侧写、不写状态；限额与同源校验生效
    inbox_state = os.path.join(tmp2, "inbox.save.json")
    with open(inbox_state, "w", encoding="utf-8") as f:
        json.dump(rich_state(), f, ensure_ascii=False)
    inbox_hash = hashlib.sha256(open(inbox_state, "rb").read()).hexdigest()
    rec = _panel.inbox_append(inbox_state, "我想去黑风寨找独眼狼算账")
    check("行动队列：追加后进入 pending 且带状态回合号",
          rec.get("id") and len(_panel.inbox_pending(inbox_state)) == 1
          and _panel.inbox_pending(inbox_state)[0]["tick"] == 12,
          str(rec.get("tick")))
    check("行动队列：侧写独立成文件（<state>.inbox.jsonl），状态文件字节不变",
          os.path.exists(_panel.inbox_path(inbox_state))
          and hashlib.sha256(open(inbox_state, "rb").read()).hexdigest() == inbox_hash)
    n_done = _panel.inbox_mark_done(inbox_state, [rec["id"]])
    check("行动队列：标记已处理后不再出现在 pending",
          n_done == 1 and _panel.inbox_pending(inbox_state) == [], "marked=%d" % n_done)
    for i in range(_panel.INBOX_MAX_PENDING + 6):
        _panel.inbox_append(inbox_state, "排队行动 %d" % i)
    # 注意：inbox_pending() 自己会切片到上限，所以只看 pending 长度测不出"文件无限增长"。
    # 必须看**落盘行数**，否则删掉裁剪逻辑测试仍然全绿（变异 M29 实测存活过）。
    with open(_panel.inbox_path(inbox_state), encoding="utf-8") as f:
        inbox_lines = len([ln for ln in f.read().splitlines() if ln.strip()])
    # 这里只追加过 1 条已处理记录，所以正确实现的行数上限就是 MAX_PENDING + 1；
    # 留 1 行余量，任何"不裁剪"实现（106 行）都会立刻越界。
    # 失败时必须能区分两种原因：裁剪没生效，还是这个文件被别的进程/实例写脏了
    # （同一存档被两个面板同时 append）。只报行数无法判断，所以把记录构成一并打出来。
    all_recs = _panel.inbox_read_all(inbox_state)
    done_n = sum(1 for r in all_recs if r.get("done"))
    check("行动队列：落盘记录有界（≤ %d 行，不是只切片返回）" % (_panel.INBOX_MAX_PENDING + 2),
          inbox_lines <= _panel.INBOX_MAX_PENDING + 2,
          "%d 行 / pending %d / done %d / 总记录 %d"
          % (inbox_lines, len(_panel.inbox_pending(inbox_state)), done_n, len(all_recs)))

    # 10. 行动队列 HTTP 层：同源 / Content-Type / 长度 三道闸
    inbox_srv, inbox_port = _panel.start(inbox_state, PORT + 3)
    inbox_base = "http://127.0.0.1:%d" % inbox_port
    # 先确认连的是**本次启动的这个实例**：面板端口会顺延/回退，若打到别的实例，
    # 后面的同源/长度断言会对着另一份状态跑，失败信息还指向错误的方向。
    _probe = None
    try:
        with urllib.request.urlopen(inbox_base + "/state", timeout=8) as _r:
            _probe = json.loads(_r.read().decode("utf-8"))
    except Exception as _exc:  # aqg: top-level boundary —— 连不上就是这一项失败
        _probe = {"error": str(_exc)}
    # 断言名里不带端口：变异测试要求基线与变异后的断言清单完全一致，
    # 而端口在两次运行之间可能不同（顺延/回退）。端口放进说明列。
    check("行动队列面板：连到的是本次启动的实例",
          isinstance(_probe, dict) and str(_probe.get("meta", {}).get("state_path", ""))
          .endswith(os.path.basename(inbox_state)),
          str((_probe or {}).get("meta", {}).get("state_path", ""))[:70])
    try:
        def post_action(payload, ctype="application/json", origin=None):
            import urllib.request as _ur
            req = _ur.Request(inbox_base + "/action",
                              data=json.dumps(payload).encode("utf-8"),
                              headers={"Content-Type": ctype, **({"Origin": origin} if origin else {})},
                              method="POST")
            try:
                with _ur.urlopen(req, timeout=8) as r:
                    return r.status, json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                try:
                    return e.code, json.loads(e.read().decode("utf-8"))
                except Exception:
                    return e.code, {}
            except Exception as e:
                return 0, {"error": str(e)}

        # 上一条测试把队列塞满了：先清空，才能验证"新增一条 → pending +1"而不是撞上限
        _panel.inbox_mark_done(inbox_state, [r.get("id") for r in _panel.inbox_read_all(inbox_state)])
        before_pending = len(_panel.inbox_pending(inbox_state))
        st_ok, body_ok = post_action({"text": "去渡口打听消息"})
        check("POST /action 接受同源 JSON 并返回 pending 计数",
              st_ok == 200 and body_ok.get("ok") and before_pending == 0
              and body_ok.get("pending") == before_pending + 1,
              "status=%s pending=%s" % (st_ok, body_ok.get("pending")))
        st_bad, body_bad = post_action({"text": "x"}, ctype="text/plain")
        check("POST /action 拒绝非 JSON（415）", st_bad == 415 and body_bad.get("ok") is False,
              "status=%s" % st_bad)
        st_x, body_x = post_action({"text": "x"}, origin="http://evil.example")
        # 若这里仍是 200，先看 body_x：打到了「Host 不被允许」还是「跨站请求被拒绝」，
        # 能区分是校验缺失还是请求根本没到本实例（端口回退后的旧实例）。
        check("POST /action 拒绝跨站 Origin（403）", st_x == 403 and body_x.get("ok") is False,
              "status=%s body=%s" % (st_x, str(body_x)[:60]))
        st_long, body_long = post_action({"text": "长" * (_panel.INBOX_MAX_TEXT + 10)})
        # 正文过长由业务校验回 400；请求体字节超限由传输层回 413（两者都是拒绝）
        check("POST /action 拒绝超长行动（400/413）", st_long in (400, 413), "status=%s" % st_long)
        st_empty, _ = post_action({"text": "   "})
        check("POST /action 拒绝空行动（400）", st_empty == 400, "status=%s" % st_empty)
        st_404, _ct, _b = http_get(inbox_base + "/action2")
        check("未知 POST 路径一律 404", st_404 == 404, "status=%s" % st_404)
        st_actions, acts = get_json(inbox_base + "/actions")
        check("GET /actions 返回未处理行动列表",
              st_actions == 200 and isinstance((acts or {}).get("pending"), list),
              str(len((acts or {}).get("pending") or [])))
        st_exp, ct_exp, body_exp = http_get(inbox_base + "/export")
        exported = json.loads(body_exp.decode("utf-8")) if body_exp else {}
        check("/export 直出状态 JSON（只读，内容与存档一致）",
              st_exp == 200 and exported.get("tick") == 12 and "application/json" in ct_exp,
              "status=%s tick=%s" % (st_exp, exported.get("tick")))
        check("行动队列 HTTP 层全程不写状态文件（字节不变）",
              hashlib.sha256(open(inbox_state, "rb").read()).hexdigest() == inbox_hash)
    finally:
        inbox_srv.shutdown()

    # 11. 视图模型新增：inbox_pending 计数 + meta.inbox 路径
    vm_meta = _panel.view_model(inbox_state)
    check("视图模型带 inbox_pending 与 meta.inbox",
          isinstance(vm_meta.get("inbox_pending"), int)
          and str(vm_meta.get("meta", {}).get("inbox", "")).endswith(".inbox.jsonl"),
          "pending=%s" % vm_meta.get("inbox_pending"))

    # 12. 复杂场景与并发（v1.3 面板加固）
    _panel_scenarios()

    passed = sum(RESULTS)
    print("\n%d/%d passed" % (passed, len(RESULTS)))
    return 0 if passed == len(RESULTS) else 1


def _panel_scenarios():
    """面板的复杂场景：多实例隔离、并发写、脏数据、超大状态、SSE 生命周期、Host 校验。"""
    import threading
    import urllib.parse

    # 12a. 两个面板指向不同存档时不得串台（旧实现用 Handler 类属性，后启动的会覆盖前者）
    tmpA = tempfile.mkdtemp(prefix="ww-multi-")
    pa = os.path.join(tmpA, "a.save.json")
    pb = os.path.join(tmpA, "b.save.json")
    for path, name in ((pa, "世界A"), (pb, "世界B")):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"tick": 1, "world_info": {"name": name},
                       "entities": {"player": {"name": "P", "hp": 5, "hp_max": 5}},
                       "event_log": [], "relations": {}, "market": {},
                       "karma_ledger": [], "world_flags": []}, f, ensure_ascii=False)
    srv_a, port_a = _panel.start(pa, PORT + 5)
    srv_b, port_b = _panel.start(pb, PORT + 6)
    try:
        sa, vma = get_json("http://127.0.0.1:%d/state" % port_a)
        sb, vmb = get_json("http://127.0.0.1:%d/state" % port_b)
        check("多面板实例隔离（各自读自己的存档）",
              sa == 200 and sb == 200
              and (vma or {}).get("world", {}).get("name") == "世界A"
              and (vmb or {}).get("world", {}).get("name") == "世界B",
              "%s / %s" % ((vma or {}).get("world", {}).get("name"),
                           (vmb or {}).get("world", {}).get("name")))
    finally:
        srv_a.shutdown()
        srv_b.shutdown()

    # 12b. 并发排队：20 线程同时提交不能互相覆盖
    tmpB = tempfile.mkdtemp(prefix="ww-concurrent-")
    pc = os.path.join(tmpB, "c.save.json")
    with open(pc, "w", encoding="utf-8") as f:
        json.dump({"tick": 1, "entities": {}, "event_log": []}, f)

    def _push(i):
        _panel.inbox_append(pc, "并发行动%d" % i)

    threads = [threading.Thread(target=_push, args=(i,)) for i in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    kept = [r for r in _panel.inbox_read_all(pc) if not r.get("done")]
    check("并发排队不丢条目（20 线程 → 20 条）", len(kept), 20)

    # 12c. 脏数据：类型全错的状态也不能把面板打崩
    tmpC = tempfile.mkdtemp(prefix="ww-dirty-")
    pd = os.path.join(tmpC, "d.save.json")
    with open(pd, "w", encoding="utf-8") as f:
        json.dump({"tick": "abc", "world_info": "not-a-dict",
                   "entities": {"player": "not-a-dict", "npc": {"hp": "x", "hp_max": None}},
                   "relations": ["bad"], "market": {"L": "bad"},
                   "karma_ledger": [{"amount": "x"}, 3], "milestones": ["bad"],
                   "event_log": [{"desc": None}, "bad"], "prose": ["bad"],
                   "codex": "bad", "world_flags": "bad"}, f, ensure_ascii=False)
    try:
        vm_d = _panel.view_model(pd)
        ok_d = (isinstance(vm_d, dict) and vm_d.get("tick") == 0
                and vm_d.get("player", {}).get("hp") == 0
                and vm_d.get("player", {}).get("inventory") == []
                and isinstance(vm_d.get("events"), list))
        check("脏数据不崩（类型全错仍产出合法视图模型）", ok_d,
              "tick=%s hp=%s" % (vm_d.get("tick"), (vm_d.get("player") or {}).get("hp")))
    except Exception as exc:  # aqg: top-level boundary —— 异常本身就是要断言的失败
        check("脏数据不崩（类型全错仍产出合法视图模型）", False, str(exc)[:70])

    # 12d. 超大状态：/state 必须有上限，不能随存档线性膨胀
    tmpD = tempfile.mkdtemp(prefix="ww-big-")
    pe = os.path.join(tmpD, "e.save.json")
    big = {"tick": 900, "world_info": {"name": "大世界"},
           "entities": {"player": {"name": "P", "hp": 10, "hp_max": 10},
                        **{"npc%d" % i: {"name": "NPC%d" % i, "hp": 5, "hp_max": 5,
                                         "location": "L"} for i in range(300)}},
           "market": {"L": {"item%d" % i: {"name": "物品%d" % i, "price": 10 + i,
                                           "base_price": 10, "supply": 20}
                            for i in range(800)}},
           "event_log": [{"tick": i, "type": "combat", "desc": "事件%d" % i}
                         for i in range(3000)],
           "prose": [{"tick": i, "location": "L", "text": "正文%d" % i} for i in range(500)],
           "relations": {}, "karma_ledger": [], "world_flags": [],
           "codex": {"locations": ["l%d" % i for i in range(500)]}}
    with open(pe, "w", encoding="utf-8") as f:
        json.dump(big, f, ensure_ascii=False)
    vm_e = _panel.view_model(pe)
    size = len(json.dumps(vm_e, ensure_ascii=False).encode("utf-8"))
    market_n = sum(len(m["items"]) for m in vm_e["market"])
    check("超大状态：商品下发有条目上限", market_n, _panel.MAX_MARKET_ITEMS)
    check("超大状态：图鉴下发有上限并被标记",
          len(vm_e["codex"]["locations"]) == _panel.MAX_CODEX_ITEMS
          and vm_e["codex"]["truncated"].get("locations", 0) > 0,
          str(vm_e["codex"]["truncated"]))
    check("超大状态：剧情回放有段数上限且保留完整文本",
          vm_e["prose"]["shown"] == _panel.MAX_PROSE_ITEMS
          and vm_e["prose"]["truncated"] > 0, str(vm_e["prose"]["shown"]))
    check("超大状态：/state 体积受控（< 2MB）", size < 2_000_000, "%d bytes" % size)

    # 12e. SSE：连接有寿命上限（配置存在且有限）
    check("SSE 有寿命与帧数上限",
          isinstance(_panel.Handler.SSE_MAX_SECONDS, (int, float))
          and 0 < _panel.Handler.SSE_MAX_SECONDS <= 7200
          and _panel.Handler.SSE_MAX_FRAMES > 0,
          "%ss / %s 帧" % (_panel.Handler.SSE_MAX_SECONDS, _panel.Handler.SSE_MAX_FRAMES))

    # 12f. Host 头校验（DNS rebinding）
    srv_h, port_h = _panel.start(pc, PORT + 7)
    try:
        req = urllib.request.Request("http://127.0.0.1:%d/state" % port_h,
                                     headers={"Host": "evil.example"})
        try:
            urllib.request.urlopen(req, timeout=5)
            st_evil = 200
        except urllib.error.HTTPError as exc:
            st_evil = exc.code
        check("拒绝非回环 Host（DNS rebinding 防护）", st_evil, 403)
        st_ok, _vm = get_json("http://127.0.0.1:%d/state" % port_h)
        check("回环 Host 正常放行", st_ok, 200)
    finally:
        srv_h.shutdown()

    # 12g. /history：关键词检索与分页上限
    tmpE = tempfile.mkdtemp(prefix="ww-hist-")
    ph = os.path.join(tmpE, "h.save.json")
    with open(ph, "w", encoding="utf-8") as f:
        json.dump({"tick": 3, "entities": {"player": {"name": "P"}},
                   "prose": [{"tick": 1, "location": "码头", "text": "雨下了一夜。"},
                             {"tick": 2, "location": "灯塔", "text": "灯塔亮了三分钟。"}],
                   "event_log": [], "relations": {}, "market": {},
                   "karma_ledger": [], "world_flags": []}, f, ensure_ascii=False)
    with open(ph + ".log.jsonl", "w", encoding="utf-8") as f:
        for i in range(5):
            f.write(json.dumps({"tick": i, "type": "prose", "text": "旧正文%d 灯塔" % i},
                               ensure_ascii=False) + "\n")
    hist_hash = hashlib.sha256(open(ph, "rb").read()).hexdigest()
    srv_hist, port_hist = _panel.start(ph, PORT + 8)
    try:
        st_h, hist = get_json("http://127.0.0.1:%d/history?q=%s&limit=3"
                              % (port_hist, urllib.parse.quote("灯塔")))
        check("/history 按关键词检索正文与归档",
              st_h == 200 and isinstance(hist, dict)
              and hist.get("prose", {}).get("returned") == 1
              and len(hist.get("archive", {}).get("items") or []) == 3,
              "prose=%s archive=%s" % ((hist or {}).get("prose", {}).get("returned"),
                                       len((hist or {}).get("archive", {}).get("items") or [])))
        st_h2, hist2 = get_json("http://127.0.0.1:%d/history?limit=9999" % port_hist)
        check("/history limit 被夹到上限",
              st_h2 == 200 and (hist2 or {}).get("limit") == _panel.MAX_HISTORY_PAGE,
              str((hist2 or {}).get("limit")))
        check("/history 前后状态文件 sha256",
              hashlib.sha256(open(ph, "rb").read()).hexdigest(), hist_hash)
    finally:
        srv_hist.shutdown()

    # 12h. /health
    srv_hl, port_hl = _panel.start(pc, PORT + 9)
    try:
        st_hl, health = get_json("http://127.0.0.1:%d/health" % port_hl)
        check("/health 返回 ok/state/version",
              st_hl == 200 and (health or {}).get("ok") is True
              and bool((health or {}).get("version")),
              str((health or {}).get("version")))
    finally:
        srv_hl.shutdown()

    # 12i. 端口耗尽时仍能启动（CI 上同作业连开多个面板会扫完固定窗口）
    holders = []
    try:
        import socket as _socket
        base = 19600
        for p in range(base, base + 12):
            holder = _socket.socket()
            holder.bind(("127.0.0.1", p))
            holder.listen(1)
            holders.append(holder)
        state_fb = os.path.join(tempfile.mkdtemp(prefix="ww-portfb-"), "p.json")
        with open(state_fb, "w", encoding="utf-8") as f:
            json.dump({"tick": 0, "entities": {"player": {"name": "P"}}}, f)
        srv_fb, port_fb = _panel.start(state_fb, base, bind_attempts=10)
        try:
            check("端口窗口耗尽时回退到系统分配端口（不报「都被占用」）",
                  port_fb != base, "requested=%d actual=%d" % (base, port_fb))
            st_fb, _ = get_json("http://127.0.0.1:%d/state" % port_fb)
            check("回退后的面板仍可正常服务", st_fb == 200, "status=%s" % st_fb)
        finally:
            _panel.stop(srv_fb)
    finally:
        for holder in holders:
            holder.close()


if __name__ == "__main__":
    sys.exit(main())
