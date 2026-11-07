/*
 万界·行者 · 实况主舞台 前端

 三层结构（见 ARCHITECTURE.md ADR-001/003）：
   panelData  —— 取数：fetch('/state') + SSE('/events')，SSE 断了退回轮询
   panelState —— 上次视图模型、已提示过的事件 id、当前弹窗、动效开关
   render*    —— 纯渲染：把视图模型写进 DOM（状态文字一律 textContent）

 规则：事件分类（kind/severity/title/icon）由 panel.py 决定，本文件不做任何关键词判断。
*/

(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const pct = (a, b) => Math.max(0, Math.min(100, b > 0 ? a * 100 / b : 0));
  const SEV_RANK = { info: 0, warning: 1, success: 1, danger: 2 };
  const MOOD_LABEL = {
    neutral: "寻常", danger: "危急", trade: "市易",
    social: "人情", growth: "精进", discovery: "初探",
  };

  /* ── panelState ───────────────────────────────────── */
  const panelState = {
    vm: null,              // 上次视图模型
    shownEvents: new Set(),// 已弹过提示的事件 id（本轮页面生命周期内）
    primed: false,         // 首次渲染前不弹历史事件的提示
    dialogFor: null,       // 弹窗正在展示的事件
    focusReturn: null,     // 关闭弹窗后焦点归还的控件
    motion: true,          // 动效开关
  };

  /* ── 小工具 ───────────────────────────────────────── */
  function setText(el, text) { if (el) el.textContent = text; }

  function chip(el, arr, cls) {
    if (!el) return;
    el.textContent = "";
    const list = Array.isArray(arr) ? arr : [];
    if (!list.length) {
      const s = document.createElement("span");
      s.className = "empty";
      s.textContent = "（还没有）";
      el.appendChild(s);
      return;
    }
    list.forEach((x) => {
      const s = document.createElement("span");
      s.className = "chip" + (cls ? " " + cls : "");
      s.textContent = String(x);
      el.appendChild(s);
    });
  }

  function fmtFlow(f) {
    if (!f || f.state === undefined) return "—";
    const m = { anxiety: "焦虑", flow: "心流", boredom: "无聊", unknown: "—" };
    return (m[f.state] || f.state) +
      (f.adjustment !== undefined ? "（" + (f.adjustment > 0 ? "+" : "") + f.adjustment + "）" : "");
  }

  function fmtPhase(p) {
    if (!p) return "—";
    if (typeof p === "string") return p;
    // panarchy 返回 {phase:"r", desc:"开发/增长", trigger:"…"}：给人看的应是描述，字母只是代号
    const zh = p.desc || p.phase || p.current || p.name;
    if (!zh) return JSON.stringify(p).slice(0, 40);
    return p.phase && p.desc ? String(p.desc) : String(zh);
  }

  function phaseTitle(p) {
    if (!p || typeof p !== "object") return "";
    const bits = [];
    if (p.phase) bits.push("相位 " + p.phase);
    if (p.trigger) bits.push(p.trigger);
    return bits.join(" · ");
  }

  function fmtIdentity(i) {
    if (!i || typeof i !== "object") return "";
    return Object.entries(i)
      .filter(([, v]) => typeof v === "number")
      .sort((a, b) => b[1] - a[1]).slice(0, 2)
      .map(([k, v]) => k + " " + v.toFixed(2)).join(" · ");
  }

  function relChipClass(v) {
    if (v >= 30) return "good";
    if (v <= -30) return "bad";
    return "dim";
  }

  /* 大数可读：千分位只在展示层用，接口与状态里仍是数值（图表解析不受影响） */
  function fmtNum(n) {
    if (typeof n !== "number" || !isFinite(n)) return n == null ? "—" : String(n);
    return n.toLocaleString("zh-CN");
  }

  /* ── 错误/空态横幅：状态读不到时不清屏、不装死，给出原因与重试 ── */
  function showNotice(msg, hint) {
    const box = $("notice");
    if (!box) return;
    setText($("notice-text"), msg + (hint ? "　" + hint : ""));
    box.hidden = false;
  }

  function hideNotice() {
    const box = $("notice");
    if (box) box.hidden = true;
  }

  /* ── render：主舞台 ───────────────────────────────── */
  function renderScene(v) {
    const sc = v.scene || {};
    setText($("scene-title"), sc.title || "未命名之地");
    const desc = $("scene-desc");
    if (sc.description) {
      desc.textContent = sc.description;
      desc.classList.remove("empty");
    } else {
      desc.textContent = "（尚无场景描写——开局后由状态与摘要填充）";
      desc.classList.add("empty");
    }
    const mood = $("scene-mood");
    mood.hidden = !sc.mood;
    mood.dataset.mood = sc.mood || "neutral";
    setText(mood, MOOD_LABEL[sc.mood] || sc.mood || "");
    const focus = $("scene-focus");
    if (sc.focus_event) {
      focus.hidden = false;
      focus.textContent = "";
      const b = document.createElement("b");
      b.textContent = "当前焦点：";
      focus.appendChild(b);
      focus.appendChild(document.createTextNode(sc.focus_event));
    } else {
      focus.hidden = true;
    }
  }

  /* ── 术语：设定包 ui.terms 覆盖默认中文词 ─────────── */
  function applyTerms(terms) {
    if (!terms || typeof terms !== "object") return;
    document.querySelectorAll("[data-term]").forEach((el) => {
      const key = el.getAttribute("data-term");
      if (key && terms[key]) el.textContent = terms[key];
    });
  }

  /* ── render：HUD ──────────────────────────────────── */
  function renderHud(v) {
    const p = v.player || {};
    const worldName = (v.world && v.world.name) || "未命名世界";
    const skin = v.skin || {};
    const brand = skin.brand || "World Games";
    setText($("world"), worldName);
    const mark = document.querySelector(".wordmark");
    if (mark) mark.textContent = brand;
    const seal = document.querySelector(".seal");
    if (seal) seal.textContent = brand.slice(0, 1);
    const tag = document.querySelector(".tagline");
    if (tag) tag.textContent = skin.tagline || "";
    document.title = (worldName === brand || !worldName) ? brand : (worldName + " · " + brand);
    setText($("era"), (v.world && v.world.era) || "");
    setText($("tick"), "回合 " + fmtNum(v.tick));
    setText($("clock"), "更新于 " + (v.updated_at || "—"));

    const terms = v.terms || {};
    setText($("pname"), p.name || "—");
    const stageWord = terms.stage || "阶段";
    setText($("pname-sub"), (p.stage ? "第 " + p.stage + " " + stageWord : "") || "");
    setText($("plevel"), p.level || "—");
    setText($("ploc"), p.location || "—");
    setText($("phpn"), fmtNum(p.hp) + "/" + fmtNum(p.hp_max));
    setText($("pmpn"), fmtNum(p.mp) + "/" + fmtNum(p.mp_max));
    // 货币单位优先用设定包的 currency；terms.gold 只是"钱财"这类泛称，
    // 两者同名时不再重复输出（曾出现「玄晶 19 玄晶」）。
    const goldWord = terms.gold || "钱财";
    const currency = (p.currency || "").trim();
    setText($("pgold"), currency && currency !== goldWord
      ? goldWord + " " + fmtNum(p.gold) + " " + currency
      : goldWord + " " + fmtNum(p.gold));

    const hpBar = $("phpbar");
    const hpLow = p.hp_max > 0 && p.hp / p.hp_max < 0.3;
    hpBar.style.width = pct(p.hp, p.hp_max) + "%";
    hpBar.classList.toggle("low", hpLow);
    $("pmpbar").style.width = pct(p.mp, p.mp_max || 1) + "%";
    const warn = $("hpwarn");
    if (warn) warn.hidden = !hpLow;

    const attrs = $("pattrs");
    attrs.textContent = "";
    Object.entries(p.attrs || {}).forEach(([k, x]) => {
      const s = document.createElement("span");
      s.className = "chip dim";
      s.textContent = k + " " + x;
      attrs.appendChild(s);
    });

    const ins = v.insights || {};
    setText($("flow"), fmtFlow(ins.flow));
    const phaseEl = $("phase");
    setText(phaseEl, fmtPhase(ins.phase));
    phaseEl.title = phaseTitle(ins.phase) || fmtIdentity(ins.identity);

    const karmaEl = $("karma");
    karmaEl.textContent = "";
    const kv = (v.player || {}).karma != null ? v.player.karma : (v.karma || 0);
    if (kv > 0) {
      const b = document.createElement("b");
      b.style.color = "var(--danger)";
      b.textContent = String(kv);
      karmaEl.appendChild(b);
    } else {
      karmaEl.textContent = "0";
    }

    const moral = $("moral");
    moral.textContent = "";
    const moralVals = (((v.moral || {}).derived || []).length
      ? v.moral.derived : ((v.moral || {}).values || []));
    ((v.moral || {}).dims || []).forEach((d, i) => {
      const val = moralVals[i] || 0;
      if (!val) return;   // 零维不占位：六维全 0 时不该糊一屏"关怀 0 公平 0 …"
      const wrap = document.createElement("span");
      wrap.style.marginRight = "8px";
      const b = document.createElement("b");
      b.textContent = d;
      const s = document.createElement("span");
      s.style.color = val > 0 ? "var(--success)" : (val < 0 ? "var(--danger)" : "var(--text-dim)");
      s.textContent = (val > 0 ? "+" : "") + val;
      wrap.appendChild(b);
      wrap.appendChild(document.createTextNode(" "));
      wrap.appendChild(s);
      moral.appendChild(wrap);
    });

    const inv = (p.inventory || []);
    setText($("inv-count"), inv.length ? inv.length + " 种" : "");
    const invEl = $("inventory");
    invEl.textContent = "";
    if (!inv.length) {
      const s = document.createElement("span");
      s.className = "empty";
      s.textContent = "（空手）";
      invEl.appendChild(s);
    } else {
      inv.forEach((it) => {
        const s = document.createElement("span");
        s.className = "chip" + (it.type === "丹药" || it.type === "药品" ? " good" : "");
        s.textContent = it.name + " ×" + it.quantity;
        invEl.appendChild(s);
      });
    }
  }

  /* ── render：在场 / 关系 ──────────────────────────── */
  /* 长局收敛：人会越攒越多（2000 轮实测 96 段关系、20+ 在场），
     首屏只列最相关的若干条，其余折叠——信息不丢，但不再糊成一整面墙。 */
  const PRESENT_TOP = 6;
  const REL_TOP = 8;

  function expander(host, total, shown, onExpand, noun) {
    if (total <= shown) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "tbtn more-btn";
    btn.textContent = "展开其余 " + (total - shown) + " " + noun + "（共 " + total + "）";
    btn.addEventListener("click", () => {
      btn.remove();
      onExpand();
    });
    host.appendChild(btn);
  }

  function renderCast(v) {
    const relMap = {};
    (v.relations || []).forEach((r) => { relMap[r.id] = r; });

    const present = $("present");
    present.textContent = "";
    const list = v.present || [];
    setText($("present-count"), list.length ? list.length + " 人" : "");
    if (!list.length) {
      const s = document.createElement("span");
      s.className = "empty";
      s.textContent = "此刻无人";
      present.appendChild(s);
    } else {
      const drawCast = (c) => {
        const div = document.createElement("div");
        div.className = "castcard";
        if (c.hp != null && c.hp <= 0) div.classList.add("down");
        else if (relMap[c.id] && relMap[c.id].affinity <= -30) div.classList.add("hostile");
        // 角色卡可点开：卡面文字（desc/personality/speech）才是酒馆生态里的人物本体。
        div.tabIndex = 0;
        div.setAttribute("role", "button");
        div.setAttribute("aria-label", "查看 " + (c.name || "角色") + " 详情");
        const openCard = () => openCardDialog(c, relMap[c.id], div);
        div.addEventListener("click", openCard);
        div.addEventListener("keydown", (ev) => {
          if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); openCard(); }
        });
        const b = document.createElement("b");
        b.textContent = c.name;
        div.appendChild(b);
        const meta = document.createElement("span");
        meta.className = "d";
        meta.textContent = " " + (c.level || "") + (c.hp_max ? " · 气血 " + c.hp + "/" + c.hp_max : "");
        div.appendChild(meta);
        if (c.desc) {
          const d = document.createElement("div");
          d.className = "d";
          d.textContent = c.desc;
          div.appendChild(d);
        }
        const rel = relMap[c.id];
        if (rel) {
          const r = document.createElement("div");
          r.className = "rel";
          const chipEl = document.createElement("span");
          chipEl.className = "chip " + relChipClass(rel.affinity);
          chipEl.textContent = "亲密 " + rel.affinity + " · 敬重 " + rel.respect;
          r.appendChild(chipEl);
          div.appendChild(r);
        }
        present.appendChild(div);
      };
      const ranked = list.slice().sort((a, b) => {
        const ra = relMap[a.id] ? Math.abs(relMap[a.id].affinity) : -1;
        const rb = relMap[b.id] ? Math.abs(relMap[b.id].affinity) : -1;
        return rb - ra;
      });
      ranked.slice(0, PRESENT_TOP).forEach(drawCast);
      expander(present, ranked.length, PRESENT_TOP,
               () => ranked.slice(PRESENT_TOP).forEach(drawCast), "人");
    }

    const others = $("others");
    const olist = v.others || [];
    setText(others, olist.length
      ? "别处 " + olist.length + " 人：" + olist.slice(0, 6).map((o) => o.name).join("、")
        + (olist.length > 6 ? "…" : "")
      : "");

    const rels = $("relations");
    rels.textContent = "";
    const rlist = (v.relations || []).slice().sort((a, b) => Math.abs(b.affinity) - Math.abs(a.affinity));
    setText($("rel-count"), rlist.length ? rlist.length + " 人" : "");
    if (!rlist.length) {
      const s = document.createElement("span");
      s.className = "empty";
      s.textContent = "（尚未结缘）";
      rels.appendChild(s);
    } else {
      const drawRel = (r) => {
        const s = document.createElement("span");
        s.className = "chip " + relChipClass(r.affinity);
        s.textContent = r.name + " 亲密" + r.affinity + " / 敬重" + r.respect;
        s.title = r.id;
        rels.appendChild(s);
      };
      rlist.slice(0, REL_TOP).forEach(drawRel);
      expander(rels, rlist.length, REL_TOP,
               () => rlist.slice(REL_TOP).forEach(drawRel), "段关系");
    }
  }

  /* ── render：时间线 ───────────────────────────────── */
  function timelineItem(e) {
    const li = document.createElement("li");
    li.dataset.severity = e.severity;
    li.dataset.eventId = e.id;
    li.dataset.eventType = e.type || "";
    if (e.milestone) {
      li.classList.add("is-milestone");
      li.title = "大事记：会被 recap 与回捞记住的事件";
    }
    const t = document.createElement("span");
    t.className = "t";
    t.textContent = e.tick != null ? e.tick : "";
    const y = document.createElement("span");
    y.className = "y";
    const sev = document.createElement("span");
    sev.className = "sev";
    sev.textContent = e.icon + " " + e.kind;
    y.appendChild(sev);
    if (e.milestone) {
      const tag = document.createElement("span");
      tag.className = "chip accent";
      tag.style.cssText = "margin:2px 0 0;padding:0 7px;font-size:11px";
      tag.textContent = "记";
      y.appendChild(tag);
    }
    const d = document.createElement("span");
    d.className = "d";
    // 合并过的重复事件标出次数，玩家才知道"连打 4 回合都被闪"而不是只发生一次
    d.textContent = e.desc + (e.repeat > 1 ? "（×" + e.repeat + "）" : "");
    li.appendChild(t);
    li.appendChild(y);
    li.appendChild(d);
    // 条目可点开详情：时间线只给一行摘要，玩家常需要看完整事件
    // （时间/类型/是否大事记/重复次数）。复用事件弹窗，不新造一层 UI。
    li.tabIndex = 0;
    li.setAttribute("role", "button");
    li.style.cursor = "pointer";
    li.title = "点击查看事件详情";
    const openIt = (ev) => { ev.preventDefault(); openDialog(e, li); };
    li.addEventListener("click", openIt);
    li.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") openIt(ev);
    });
    return li;
  }

  let timelineFilter = "all";
  let timelineQuery = "";

  function applyTimelineFilter() {
    const ul = $("timeline");
    if (!ul) return;
    const q = timelineQuery.trim().toLowerCase();
    let shown = 0;
    ul.querySelectorAll("li[data-event-id]").forEach((li) => {
      const type = li.dataset.eventType || "";
      const isMs = li.classList.contains("is-milestone");
      const text = (li.textContent || "").toLowerCase();
      let ok = true;
      if (timelineFilter === "milestone") ok = isMs;
      else if (timelineFilter !== "all") ok = type === timelineFilter;
      if (ok && q) ok = text.indexOf(q) >= 0;
      li.hidden = !ok;
      if (ok) shown += 1;
    });
    // 时间线里所有条目都被过滤掉时给一句可读的空态，而不是一片空白
    let hint = ul.querySelector("li.filter-empty");
    if (!shown) {
      if (!hint) {
        hint = document.createElement("li");
        hint.className = "empty filter-empty";
        ul.appendChild(hint);
      }
      hint.textContent = timelineQuery ? "没有匹配「" + timelineQuery + "」的事件" : "这一类暂时没有事件";
    } else if (hint) {
      hint.remove();
    }
  }

  function renderTimeline(v) {
    const ul = $("timeline");
    ul.textContent = "";
    const events = (v.events || []).slice().reverse();
    setText($("timeline-hint"),
      "大事记 " + ((v.milestones || []).length) + " · 归档 " + (v.archived_events || 0));
    if (!events.length) {
      const li = document.createElement("li");
      li.className = "empty";
      li.textContent = "暂无事件";
      ul.appendChild(li);
      return;
    }
    events.forEach((e) => ul.appendChild(timelineItem(e)));
    applyTimelineFilter();
  }

  function renderDrawers(v) {
    const cx = v.codex || {};
    chip($("cx-loc"), cx.locations, "accent");
    chip($("cx-people"), cx.people, "");
    chip($("cx-items"), cx.items, "");
    chip($("cx-lore"), cx.lore, "dim");
    setText($("lorecnt"), "设定词条 " + (v.lore_total || 0) + " 条");

    const market = $("market");
    market.textContent = "";
    const mlist = v.market || [];
    if (!mlist.length) {
      const s = document.createElement("span");
      s.className = "empty";
      s.textContent = "此界无市";
      market.appendChild(s);
    } else {
      const here = (v.player || {}).location;
      mlist.forEach((m) => {
        const head = document.createElement("div");
        head.className = "row";
        const k = document.createElement("span");
        k.className = "k";
        k.textContent = m.location + (m.location === here ? "（本地）" : "");
        head.appendChild(k);
        market.appendChild(head);
        const table = document.createElement("table");
        const thead = document.createElement("tr");
        ["物品", "价", "基准", "库存"].forEach((h) => {
          const th = document.createElement("th");
          th.textContent = h;
          thead.appendChild(th);
        });
        table.appendChild(thead);
        (m.items || []).forEach((it) => {
          const tr = document.createElement("tr");
          const td1 = document.createElement("td");
          td1.textContent = it.name;
          const td2 = document.createElement("td");
          td2.className = it.delta > 0 ? "up" : (it.delta < 0 ? "down" : "flat");
          td2.textContent = it.price + (it.delta > 0 ? " ▲" : (it.delta < 0 ? " ▼" : " ＝"));
          const td3 = document.createElement("td");
          td3.textContent = it.base_price;
          const td4 = document.createElement("td");
          td4.textContent = it.supply;
          [td1, td2, td3, td4].forEach((td) => tr.appendChild(td));
          table.appendChild(tr);
        });
        market.appendChild(table);
      });
    }

    const ms = $("milestones");
    ms.textContent = "";
    const mlist2 = v.milestones || [];
    setText($("memhint"), "摘要 " + (v.summaries || 0) + " 条 · 归档 " + (v.archived_events || 0) + " 条");
    if (!mlist2.length) {
      const li = document.createElement("li");
      li.className = "empty";
      li.textContent = "暂无";
      ms.appendChild(li);
    } else {
      mlist2.forEach((m) => {
        const li = document.createElement("li");
        li.className = "is-milestone";
        const d = document.createElement("span");
        d.className = "d";
        d.textContent = m;
        li.appendChild(d);
        ms.appendChild(li);
      });
    }

    chip($("flags"), v.flags, "dim");
    renderWorldDrawer(v);
  }

  /* ── 世界侧：势力存量 / 传闻热度 / 风气 ──────────── */
  function renderWorldDrawer(v) {
    const ws = v.world_state || {};
    const terms = v.terms || {};
    const facBox = $("world-factions");
    if (facBox) {
      facBox.textContent = "";
      const facs = ws.factions || [];
      if (!facs.length) {
        const s = document.createElement("span");
        s.className = "empty";
        s.textContent = (terms.factions || "势力") + "还没开始演化";
        facBox.appendChild(s);
      } else {
        facs.forEach((f) => {
          const s = document.createElement("span");
          s.className = "chip" + (f.power >= 70 ? " good" : (f.power <= 25 ? " bad" : ""));
          s.textContent = f.name + " " + f.power;
          facBox.appendChild(s);
        });
      }
    }
    const hint = $("world-hint");
    if (hint) {
      const ph = ws.phase ? "相位 " + ws.phase : "";
      const mi = (ws.market_index != null) ? "物价 " + ws.market_index : "";
      hint.textContent = [ph, mi].filter(Boolean).join(" · ");
    }
    const rumBox = $("world-rumors");
    if (rumBox) {
      rumBox.textContent = "";
      const rumors = ws.rumors || [];
      if (!rumors.length) {
        const s = document.createElement("span");
        s.className = "empty";
        s.textContent = "暂无传闻";
        rumBox.appendChild(s);
      } else {
        rumors.forEach((r) => {
          const s = document.createElement("span");
          s.className = "chip" + (r.heat >= 0.3 ? " bad" : " dim");
          s.textContent = r.topic + " " + Math.round((r.heat || 0) * 100) + "%";
          rumBox.appendChild(s);
        });
      }
    }
    const culBox = $("world-culture");
    if (culBox) {
      culBox.textContent = "";
      const cul = ws.culture || {};
      const t = (cul.tradition != null) ? cul.tradition : null;
      const i = (cul.innovation != null) ? cul.innovation : null;
      if (t == null && i == null) {
        const s = document.createElement("span");
        s.className = "empty";
        s.textContent = "—";
        culBox.appendChild(s);
      } else {
        [["守成", t], ["求变", i]].forEach(([name, val]) => {
          if (val == null) return;
          const s = document.createElement("span");
          s.className = "chip dim";
          s.textContent = name + " " + Math.round(val * 100) + "%";
          culBox.appendChild(s);
        });
      }
    }
  }

  /* ── 长局态势：三张离线图表（ECharts 缺失时降级为文案）── */
  const charts = { c1: null, c2: null, c3: null, questmap: null };
  let lastSeriesKey = "";
  let seriesCache = null;

  function chartReady() { return typeof window.echarts !== "undefined"; }

  function cssVar(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name);
    return (v && v.trim()) || fallback;
  }

  /* 图表配色跟随主题：ECharts 画在 canvas 上，不继承 CSS 变量，
     所以切换主题时必须把算出来的颜色重新喂给 setOption（见 refreshChartTheme）。
     皮肤只覆盖"强调色/线色"，底与文字色一律取自当前主题 token。 */
  function chartPalette(vm) {
    const p = (vm && vm.skin && vm.skin.palette) || {};
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    return {
      line: p.line || cssVar("--accent", "#8a5a12"),
      area: p.area || cssVar("--accent-soft", "rgba(138,90,18,.12)"),
      bar: p.bar || cssVar("--accent-line", "#b98a35"),
      hp: p.hp || "#d9534f",
      mp: p.mp || "#4a90d9",
      grid: dark ? (p.grid || "#2b3341") : cssVar("--line", "#ddd5c6"),
      text: dark ? (p.text || "#a3abb9") : cssVar("--text-dim", "#4c5361"),
      surface: cssVar("--surface-1", dark ? "#151920" : "#fffdf8"),
      ink: cssVar("--text", dark ? "#ecebe6" : "#1d2027"),
    };
  }

  function chartBase(pal, rightPad) {
    return {
      animation: panelState.motion,
      backgroundColor: "transparent",
      grid: { left: 46, right: rightPad || 18, top: 30, bottom: 26 },
      textStyle: { color: pal.text, fontSize: 11 },
      tooltip: {
        trigger: "axis",
        backgroundColor: pal.surface,
        borderColor: pal.grid,
        textStyle: { color: pal.ink, fontSize: 12 },
      },
      legend: { top: 0, textStyle: { color: pal.text, fontSize: 11 }, icon: "roundRect" },
      xAxis: {
        type: "category",
        boundaryGap: false,
        axisLine: { lineStyle: { color: pal.grid } },
        axisLabel: { color: pal.text },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: pal.grid, opacity: .5 } },
        axisLabel: { color: pal.text },
      },
    };
  }

  function ensureChart(key, elId, emptyId) {
    const el = $(elId);
    const emptyEl = $(emptyId);
    if (!el) return null;
    if (!chartReady()) {
      if (emptyEl) {
        emptyEl.hidden = false;
        emptyEl.textContent = "图表库未加载（离线资产 assets/echarts.min.js 缺失或被拦截）——数据仍在上方时间线与 HUD 中。";
      }
      el.hidden = true;
      return null;
    }
    if (!charts[key]) charts[key] = window.echarts.init(el, null, { renderer: "canvas" });
    return charts[key];
  }

  function renderCharts(vm, series) {
    const samples = (series && series.samples) || [];
    const ticks = samples.map((s) => s.tick);
    const pal = chartPalette(vm);
    const enough = samples.length >= 2;

    // 图一：行藏曲线（气血% / 内力% / 钱财）
    let c1 = ensureChart("c1", "chart1", "chart1-empty");
    if (c1) {
      $(("chart1-empty")).hidden = enough;
      c1.getDom && (c1.getDom().style.display = enough ? "" : "none");
      if (enough) {
        const hpPct = samples.map((s) => Math.round(s.hp * 100 / Math.max(1, s.hp_max)));
        const mpPct = samples.map((s) => Math.round(s.mp * 100 / Math.max(1, s.mp_max || 1)));
        const gold = samples.map((s) => s.gold);
        // 图鉴累计（地点/人物/物品/词条）：长局里唯一"只增不减"的成长指标，
        // 气血常因突破回满而看不出变化，用它才能看出"这局到底走了多远"。
        const codex = samples.map((s) => s.codex_total || 0);
        const codexGrows = codex.length && (codex[codex.length - 1] - codex[0]) > 0;
        // 自适应纵轴：长局里气血常年在 76–100% 之间，固定 0–100 会把它压成一条
        // 贴着顶边的直线，玩家看不出任何起伏。这里按实际范围外扩一点，
        // 但如果跨度本身就很大（>60），仍回到 0–100 以免夸大小波动。
        const spanOf = (arr) => {
          const lo = Math.min.apply(null, arr), hi = Math.max.apply(null, arr);
          return { lo, hi, span: hi - lo };
        };
        const hpSpan = spanOf(hpPct), mpSpan = spanOf(mpPct);
        // 全程无波动的序列在图上就是一条贴边的直线，读者会以为是渲染故障。
        // 在系列名里标注"恒定 N%"，让"没变化"本身成为可读信息。
        // "看起来是平线"的两种情形：跨度极小（<5 点），或绝大多数点挤在同一值
        // （长局里玩家靠突破回满，600 回合里可能只有 1 次受伤）。
        const dominantShare = (arr) => {
          const c = {}; arr.forEach(v => { c[v] = (c[v] || 0) + 1; });
          const top = Object.keys(c).reduce((a, b) => (c[a] >= c[b] ? a : b));
          return c[top] / Math.max(1, arr.length);
        };
        const flatLabel = (name, sp, arr, unit) => {
          if (sp.span === 0) return name + "（恒定 " + sp.hi + unit + "）";
          if (sp.span < 5) return name + "（几乎恒定 " + sp.hi + unit + "）";
          const share = dominantShare(arr);
          if (share >= 0.9) {
            return name + "（" + Math.round(share * 100) + "% 回合为 " + sp.hi + unit + "）";
          }
          return name;
        };
        const pctAxis = () => {
          const lo = Math.min(hpSpan.lo, mpSpan.lo);
          const hi = Math.max(hpSpan.hi, mpSpan.hi);
          if (hi - lo > 60) return { min: 0, max: 100 };
          const pad = Math.max(4, Math.round((hi - lo) * 0.25));
          return { min: Math.max(0, lo - pad), max: Math.min(100, hi + pad) };
        };
        const opt = Object.assign(chartBase(pal, 58), {
          xAxis: Object.assign(chartBase(pal).xAxis, { data: ticks }),
          yAxis: [
            Object.assign(chartBase(pal).yAxis, Object.assign(
              { name: "%", nameTextStyle: { color: pal.text } }, pctAxis())),
            { type: "value", splitLine: { show: false }, axisLabel: { color: pal.text },
              name: "钱财", nameTextStyle: { color: pal.text, fontSize: 10 } },
          ].concat(codexGrows ? [
            { type: "value", splitLine: { show: false }, show: false, name: "图鉴" },
          ] : []),
          series: [
            { name: flatLabel("气血%", hpSpan, hpPct, "%"), type: "line", smooth: true, showSymbol: false, data: hpPct,
              lineStyle: { color: pal.hp, width: 2 }, itemStyle: { color: pal.hp },
              areaStyle: { color: pal.hp, opacity: .10 } },
            { name: flatLabel("内力%", mpSpan, mpPct, "%"), type: "line", smooth: true, showSymbol: false, data: mpPct,
              lineStyle: { color: pal.mp, width: 2 }, itemStyle: { color: pal.mp } },
            { name: "钱财", type: "line", smooth: true, showSymbol: false, yAxisIndex: 1, data: gold,
              lineStyle: { color: pal.line, width: 2, type: "dashed" }, itemStyle: { color: pal.line } },
          ].concat(codexGrows ? [
            { name: "图鉴累计", type: "line", smooth: true, showSymbol: false, yAxisIndex: 2, data: codex,
              lineStyle: { color: pal.bar, width: 1.8, type: "dotted" }, itemStyle: { color: pal.bar } },
          ] : []),
        });
        c1.setOption(opt, { notMerge: true });
      }
    }

    // 图二：业债与心境
    let c2 = ensureChart("c2", "chart2", "chart2-empty");
    if (c2) {
      $("chart2-empty").hidden = enough;
      c2.getDom && (c2.getDom().style.display = enough ? "" : "none");
      if (enough) {
        const karma = samples.map((s) => s.karma);
        const aff = samples.map((s) => s.affinity_avg);
        const opt = Object.assign(chartBase(pal), {
          xAxis: Object.assign(chartBase(pal).xAxis, { data: ticks }),
          series: [
            { name: "未清业债", type: "bar", data: karma, itemStyle: { color: pal.bar, opacity: .8 },
              barMaxWidth: 10 },
            { name: "人情均值", type: "line", smooth: true, showSymbol: false, data: aff,
              lineStyle: { color: pal.line, width: 2 }, itemStyle: { color: pal.line } },
          ],
        });
        c2.setOption(opt, { notMerge: true });
      }
    }

    // 图三：市价偏离（1.0 基准参考线）
    let c3 = ensureChart("c3", "chart3", "chart3-empty");
    if (c3) {
      $("chart3-empty").hidden = enough;
      c3.getDom && (c3.getDom().style.display = enough ? "" : "none");
      if (enough) {
        const idx = samples.map((s) => s.price_index);
        const opt = Object.assign(chartBase(pal, 34), {
          xAxis: Object.assign(chartBase(pal).xAxis, { data: ticks }),
          series: [
            { name: "物价指数", type: "line", smooth: true, showSymbol: false, data: idx,
              lineStyle: { color: pal.line, width: 2 },
              areaStyle: { color: pal.area },
              markLine: { silent: true, symbol: "none",
                lineStyle: { color: pal.text, type: "dashed", opacity: .7 },
                data: [{ yAxis: 1.0, label: { formatter: "基准 1.0", color: pal.text, fontSize: 10,
                                              position: "insideStartTop" } }] } },
          ],
        });
        c3.setOption(opt, { notMerge: true });
      }
    }
  }

  function refreshSeries(vm) {
    const key = vm.tick + ":" + ((vm.events || []).length) + ":" + (vm.player || {}).gold;
    if (key === lastSeriesKey && seriesCache) { renderCharts(vm, seriesCache); return; }
    fetch("/series")
      .then((r) => r.json())
      .then((s) => { seriesCache = s; lastSeriesKey = key; renderCharts(vm, s); })
      .catch(() => { renderCharts(vm, seriesCache || { samples: [] }); });
  }

  /* ── 事件谱：按严重度与类型计数（维度信号 + 文本标签）── */
  function renderSpectrum(vm) {
    const box = $("spectrum");
    if (!box) return;
    const events = vm.events || [];
    const bySev = { danger: 0, warning: 0, success: 0, info: 0 };
    const byType = {};
    events.forEach((e) => {
      if (bySev[e.severity] !== undefined) bySev[e.severity] += 1;
      byType[e.type] = (byType[e.type] || 0) + 1;
    });
    const total = Math.max(1, events.length);
    setText($("spectrum-hint"), "最近 " + events.length + " 条 · " + Object.keys(byType).length + " 类");
    box.textContent = "";
    const sevLabels = { danger: "危急", warning: "警示", success: "顺遂", info: "寻常" };
    Object.keys(bySev).forEach((sev) => {
      const n = bySev[sev];
      const cell = document.createElement("div");
      cell.className = "spec-cell";
      cell.dataset.sev = sev;
      const num = document.createElement("div");
      num.className = "n";
      num.textContent = String(n);
      const lab = document.createElement("div");
      lab.className = "l";
      lab.textContent = sevLabels[sev] + " · " + (n / total * 100).toFixed(0) + "%";
      const bar = document.createElement("div");
      bar.className = "spec-bar";
      const fill = document.createElement("i");
      fill.style.width = (n / total * 100).toFixed(1) + "%";
      bar.appendChild(fill);
      cell.appendChild(num);
      cell.appendChild(lab);
      cell.appendChild(bar);
      box.appendChild(cell);
    });
  }

  /* ── 人物关系网：纯 SVG，中心玩家 + 结缘者环绕 ── */
  function renderRelNet(vm) {
    const box = $("relnet");
    if (!box) return;
    const rels = (vm.relations || []).filter((r) => r.affinity !== 0 || r.respect !== 0);
    box.textContent = "";
    if (!rels.length) {
      const s = document.createElement("div");
      s.className = "relnet-empty";
      s.textContent = "（还没有值得画的关系——去认识几个人）";
      box.appendChild(s);
      return;
    }
    const W = 300, H = 190, cx = W / 2, cy = H / 2, R = 66;
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    rels.slice(0, 8).forEach((r, i) => {
      const ang = (-90 + i * (360 / Math.min(8, rels.length))) * Math.PI / 180;
      const x = cx + R * Math.cos(ang), y = cy + R * Math.sin(ang) * 0.82;
      const line = document.createElementNS(NS, "line");
      line.setAttribute("x1", cx); line.setAttribute("y1", cy);
      line.setAttribute("x2", x); line.setAttribute("y2", y);
      line.setAttribute("class", "edge");
      const good = r.affinity > 0;
      line.setAttribute("stroke", good ? "var(--success)" : "var(--danger)");
      svg.appendChild(line);
      const g = document.createElementNS(NS, "g");
      g.setAttribute("class", "node");
      const c = document.createElementNS(NS, "circle");
      c.setAttribute("cx", x); c.setAttribute("cy", y);
      c.setAttribute("r", String(8 + Math.min(10, Math.abs(r.affinity) / 10)));
      g.appendChild(c);
      const t = document.createElementNS(NS, "text");
      t.setAttribute("x", x); t.setAttribute("y", y + 20);
      t.setAttribute("text-anchor", "middle");
      t.textContent = r.name + " " + (r.affinity > 0 ? "+" : "") + r.affinity;
      g.appendChild(t);
      svg.appendChild(g);
    });
    const meG = document.createElementNS(NS, "g");
    meG.setAttribute("class", "node me");
    const meC = document.createElementNS(NS, "circle");
    meC.setAttribute("cx", cx); meC.setAttribute("cy", cy); meC.setAttribute("r", "15");
    meG.appendChild(meC);
    const meT = document.createElementNS(NS, "text");
    meT.setAttribute("x", cx); meT.setAttribute("y", cy + 4);
    meT.setAttribute("text-anchor", "middle");
    meT.textContent = (vm.player || {}).name || "我";
    meG.appendChild(meT);
    svg.appendChild(meG);
    box.appendChild(svg);
  }

  /* ── 地点图：已探索地点环布，当前所在地高亮 ── */
  function renderMapNet(vm) {
    const box = $("mapnet");
    if (!box) return;
    const locs = ((vm.codex || {}).locations || []).slice(0, 10);
    const here = (vm.player || {}).location || "";
    box.textContent = "";
    setText($("map-hint"), locs.length ? locs.length + " 处" : "");
    setText($("map-legend"), here ? "当前：" + here : "");
    if (!locs.length) {
      const s = document.createElement("div");
      s.className = "relnet-empty";
      s.textContent = "（还没记录任何地点——用 travel 走动会记进图鉴）";
      box.appendChild(s);
      return;
    }
    const W = 300, H = 170, cx = W / 2, cy = H / 2, R = 60;
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    if (locs.length > 1) {
      const ring = document.createElementNS(NS, "polygon");
      ring.setAttribute("class", "link");
      const pts = locs.map((_, i) => {
        const ang = (-90 + i * (360 / locs.length)) * Math.PI / 180;
        return (cx + R * Math.cos(ang)) + "," + (cy + R * Math.sin(ang) * 0.78);
      }).join(" ");
      ring.setAttribute("points", pts);
      svg.appendChild(ring);
    }
    locs.forEach((name, i) => {
      const ang = (-90 + i * (360 / locs.length)) * Math.PI / 180;
      const x = cx + R * Math.cos(ang), y = cy + R * Math.sin(ang) * 0.78;
      const g = document.createElementNS(NS, "g");
      g.setAttribute("class", "loc" + (name === here ? " here" : ""));
      const c = document.createElementNS(NS, "circle");
      c.setAttribute("cx", x); c.setAttribute("cy", y);
      c.setAttribute("r", name === here ? "9" : "6.5");
      g.appendChild(c);
      const t = document.createElementNS(NS, "text");
      t.setAttribute("x", x); t.setAttribute("y", y + (y < cy ? -12 : 18));
      t.setAttribute("text-anchor", "middle");
      t.textContent = name;
      g.appendChild(t);
      svg.appendChild(g);
    });
    box.appendChild(svg);
  }

  /* ── 修行轨：stage / stage_max 进度 ── */
  function renderStageTrack(vm) {
    const box = $("stage-track");
    if (!box) return;
    const p = vm.player || {};
    // 配置了 level_tiers 的世界用阶梯长度当上限，否则退回 stage_max
    const stage = (p.tier != null) ? p.tier : (p.stage || 0);
    const cap = (p.tier_max != null) ? p.tier_max : (p.stage_max || 20);
    const shown = Math.min(cap, 20) || 1;
    setText($("stage-hint"), stage + " / " + cap + (stage >= cap ? "（已到上限）" : ""));
    box.textContent = "";
    for (let i = 0; i < shown; i++) {
      const d = document.createElement("span");
      d.className = "step" + (i < stage ? " on" : "") + (i === shown - 1 ? " cap" : "");
      d.title = "第 " + (i + 1) + " 阶";
      box.appendChild(d);
    }
    const lbl = document.createElement("span");
    lbl.className = "lbl";
    lbl.textContent = (p.level || "—")
      + (p.mind_scars ? " · 心伤 " + p.mind_scars : "")
      + (p.near_death_count ? " · 濒死 " + p.near_death_count : "");
    box.appendChild(lbl);
  }

  /* ── 危险/机会徽章 ── */
  function renderBadges(vm) {
    const host = $("badges");
    if (!host) return;
    const p = vm.player || {};
    host.textContent = "";
    const add = (cls, text) => {
      const b = document.createElement("span");
      b.className = "badge " + cls;
      b.textContent = text;
      host.appendChild(b);
    };
    const hpRatio = (p.hp_max || 0) > 0 ? p.hp / p.hp_max : 1;
    if (hpRatio < 0.3) add("danger", "气血吃紧");
    else if (hpRatio < 0.55) add("warn", "气血偏低");
    if ((p.karma || 0) >= 150) add("danger", "业债深重 " + p.karma);
    else if ((p.karma || 0) >= 60) add("warn", "业债缠身 " + p.karma);
    const mkt = (vm.market || []).find((m) => m.location === p.location);
    if (mkt && (mkt.items || []).some((it) => it.delta < 0)) add("chance", "本地有折价货");
    if ((vm.player || {}).stage >= ((vm.player || {}).stage_max || 20)) add("warn", "已到修行上限");
  }

  /* 抽屉位于页面底部；展开时把它滚进视口，否则用户点了"图鉴"却看不到内容。
     键盘/读屏用户同理：焦点跟随滚动，不然展开等于没展开。 */
  function wireDrawers() {
    document.querySelectorAll('details.drawer').forEach((d) => {
      d.addEventListener('toggle', () => {
        if (!d.open) return;
        requestAnimationFrame(() => {
          // 抽屉在页面底部：从顶部点开是"长距离跳转"。长跳用瞬时定位，
          // 短跳才用平滑滚动——否则一屏半的平滑动画既慢又容易被误认为没反应。
          const far = d.getBoundingClientRect().top > window.innerHeight * 1.5;
          d.scrollIntoView({ block: 'nearest', behavior: far ? 'auto' : 'smooth' });
        });
      });
    });
  }

  /* 皮肤主色由后端按主题成对下发（{light, dark}）。这里只挑选当前主题那一支，
     绝不自己拼透明度：v1.8 用 accent + "88" 生成的半透明色被当作文字色使用，
     在亮色底上实测只有 1.8:1 —— 对比度不达标。 */
  function applySkinAccent(skin) {
    if (!skin) return;
    const theme = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
    const pick = (v) => (v && typeof v === "object" ? v[theme] : v) || "";
    const accent = pick(skin.accent);
    const fill = pick(skin.accent_fill);
    const root = document.documentElement;
    if (accent) root.style.setProperty("--accent", accent);
    if (fill) root.style.setProperty("--accent-fill", fill);
  }

  function render(v) {
    if (!v || typeof v !== "object") return;
    document.body.dataset.skin = (v.skin && v.skin.id) || "neutral";
    applySkinAccent(v.skin);
    applyTerms(v.terms);
    renderHud(v);
    renderScene(v);
    renderCast(v);
    renderTimeline(v);
    renderDrawers(v);
    renderSpectrum(v);
    renderRelNet(v);
    renderMapNet(v);
    renderStageTrack(v);
    renderBadges(v);
    renderPulse(v);
    renderPlaybook(v);
    renderQuests(v);
    renderQuestMap(v);
    renderNextMoves(v);
    renderLorebook(v);
    renderGame(v);
    renderSystems(v);
    renderStory(v);
    refreshSeries(v);
  }

  /* ── 世界脉搏：相位 / 存量 / 连接度 / 烈度 / 势力 ─────── */
  const PHASE_LABEL = { r: "开发/增长", K: "保护/守恒", "Ω": "崩溃/释放", "α": "重组/革新" };

  function renderPulse(v) {
    const ws = v.world_state || {};
    const badge = $("pulse-phase");
    const phase = ws.phase || "";
    if (badge) {
      badge.dataset.phase = phase;
      badge.textContent = phase ? (phase + " · " + (PHASE_LABEL[phase] || "")) : "尚未演化";
      badge.title = ws.phase ? "Panarchy 适应性循环阶段" : "推进回合后世界开始演化";
    }
    const setMeter = (id, numId, val, max, fmt) => {
      const bar = $(id), num = $(numId);
      if (bar) bar.style.width = Math.max(0, Math.min(100, (val / (max || 1)) * 100)) + "%";
      if (num) num.textContent = (val == null) ? "—" : fmt(val);
    };
    setMeter("meter-capital", "meter-capital-n", ws.capital, 1, (x) => Number(x).toFixed(2));
    setMeter("meter-conn", "meter-conn-n", ws.connectedness, 1, (x) => Number(x).toFixed(2));
    setMeter("meter-int", "meter-int-n", ws.intensity, 2, (x) => "×" + Number(x).toFixed(2));
    setText($("pulse-hint"),
      (ws.collapses ? "崩解 " + ws.collapses + " 次 · " : "") +
      "物价 " + (ws.market_index != null ? ws.market_index : "—"));
    const box = $("pulse-factions");
    if (box) {
      box.textContent = "";
      const facs = (ws.factions || []).slice(0, 6);
      if (!facs.length) {
        const s = document.createElement("span");
        s.className = "empty";
        s.textContent = "推进几个回合后，势力存量会自己动起来";
        box.appendChild(s);
      } else {
        facs.forEach((f) => {
          const s = document.createElement("span");
          s.className = "chip" + (f.power >= 70 ? " good" : (f.power <= 25 ? " bad" : " dim"));
          s.textContent = f.name + " " + f.power;
          box.appendChild(s);
        });
      }
    }
    const trig = $("pulse-trigger");
    if (trig) {
      const ph = (v.insights || {}).phase || {};
      trig.textContent = ph.trigger || "";
    }
  }

  /* ── 反馈层：toast / dialog ───────────────────────── */
  function toast(e) {
    const box = $("toasts");
    if (!box) return;
    const div = document.createElement("div");
    div.className = "toast";
    div.dataset.severity = e.severity;
    div.setAttribute("role", e.severity === "danger" ? "alert" : "status");
    const tt = document.createElement("div");
    tt.className = "tt";
    tt.textContent = "第 " + (e.tick != null ? e.tick : "?") + " 回合 · " + e.icon + " " + e.kind;
    const dd = document.createElement("div");
    dd.textContent = e.desc;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "关闭";
    btn.setAttribute("aria-label", "关闭这条提示");
    const remove = () => div.remove();
    btn.addEventListener("click", remove);
    div.appendChild(tt);
    div.appendChild(dd);
    div.appendChild(btn);
    box.appendChild(div);
    if (e.severity !== "danger") setTimeout(remove, 6200);
  }

  function openDialog(e, trigger) {
    const dlg = $("eventdlg");
    if (!dlg || typeof dlg.showModal !== "function") { toast(e); return; }
    panelState.dialogFor = e;
    panelState.focusReturn = trigger || document.activeElement;
    setText($("dlg-icon"), e.icon || "");
    setText($("dlg-title-text"), e.title || "事件");
    setText($("dlg-meta"), "第 " + (e.tick != null ? e.tick : "?") + " 回合 · " + (e.type || "") + (e.milestone ? " · 大事记" : ""));
    setText($("dlg-desc"), e.desc || "");
    if (dlg.open) return;
    dlg.showModal();
  }

  function closeDialog() {
    const dlg = $("eventdlg");
    if (!dlg || !dlg.open) return;
    dlg.close();
    const back = panelState.focusReturn;
    panelState.focusReturn = null;
    panelState.dialogFor = null;
    if (back && typeof back.focus === "function" && document.contains(back)) {
      back.focus();
    }
  }

  /* 事件 → 反馈等级（severity 由 panel.py 决定，这里只做呈现分派） */
  function dispatchFeedback(newEvents) {
    if (!panelState.primed) return;   // 首屏不弹历史提示
    const highest = newEvents.reduce(
      (acc, e) => (SEV_RANK[e.severity] > SEV_RANK[acc.severity] ? e : acc),
      newEvents[0] || { severity: "info" });
    if (!newEvents.length) return;
    newEvents.forEach((e) => {
      if (e.severity === "info") return;          // info 只进时间线
      if (e.severity === "danger") return;        // danger 合并进弹窗
      toast(e);
    });
    if (SEV_RANK[highest.severity] >= 2) {
      openDialog(highest, null);
    }
    const ul = $("timeline");
    newEvents.forEach((e) => {
      const li = ul && ul.querySelector('[data-event-id="' + CSS.escape(e.id) + '"]');
      if (li) li.classList.add("flash");
    });
  }

  function diffEvents(prev, next) {
    const out = [];
    (next.events || []).forEach((e) => {
      if (!panelState.shownEvents.has(e.id)) out.push(e);
    });
    return out;
  }

  function apply(vm) {
    if (!vm || typeof vm !== "object") return;
    if (vm.error) {                    // 状态不可读：保留上一屏，横幅说明原因
      showNotice(vm.error, vm.hint || "");
      return;
    }
    hideNotice();
    const fresh = diffEvents(panelState.vm, vm);
    panelState.vm = vm;
    render(vm);
    // 渲染完再翻译：i18n 是表现层职责，24 个 render 函数不感知语言。
    if (window.PanelI18n) window.PanelI18n.translateDom(document.getElementById("toasts") || document.body);
    (vm.events || []).forEach((e) => panelState.shownEvents.add(e.id));
    if (panelState.primed) dispatchFeedback(fresh);
    if (window.PanelI18n) window.PanelI18n.translateDom(document.body);
    panelState.primed = true;
  }

  /* ── panelData：取数 + SSE + 轮询降级 ─────────────── */
  function setConn(state, text) {
    const el = $("conn");
    if (!el) return;
    el.dataset.state = state;
    setText($("conn-text"), text);
  }

  let lastData = 0;

  function fetchState() {
    return fetch("/state")
      .then((r) => r.json())
      .then((v) => {
        lastData = Date.now();
        if (v && v.error) {
          setConn("stale", "状态不可读");
        } else {
          setConn("live", "实况 · " + (v.updated_at || ""));
          setBootState("ready");
        }
        apply(v);
      })
      .catch(() => {
        setConn("down", "连接失败，重试中…");
        setBootState("ready");   // 失败也要收掉骨架屏，横幅才是真正的错误提示
      });
  }

  /* ── 玩法剧本：循环 / 进度 / 失败钟 / 节拍 ─────────── */
  const LOOP_LABEL = {
    freeform: "自由推进", choice: "选项推进", mud: "地点与命令", ttrpg: "声明→判定→后果",
  };

  function renderPlaybook(v) {
    const pb = v.playbook || {};
    if (pb.error) { setText($("pb-guide"), "玩法剧本读取失败：" + pb.error); return; }
    setText($("pb-loop"), LOOP_LABEL[pb.loop] || pb.loop || "");
    const pr = pb.progress || {};
    setText($("pb-progress-label"), pr.label || "进度");
    setText($("pb-progress"), pr.max
      ? (pr.value + " / " + pr.max)
      : String(pr.value == null ? "—" : pr.value));
    const bar = $("pb-bar");
    if (bar) bar.style.width = (pr.ratio != null ? Math.round(pr.ratio * 100) : 0) + "%";

    const f = pb.failure || {};
    setText($("pb-fail-label"), f.label || "失败");
    let failText = "—";
    if (f.mode === "clock") failText = f.value + " / " + f.max + " 格";
    else if (f.mode === "deadline") failText = "第 " + f.value + " 回合 / 限 " + f.max;
    else if (f.mode === "sanity") failText = f.value + " / " + f.max;
    else if (f.mode === "hp") failText = f.value + " / " + f.max;
    else if (f.mode === "none") failText = "本局无失败条件";
    setText($("pb-fail"), failText);
    const fbar = $("pb-fail-bar");
    if (fbar) fbar.style.width = (f.ratio != null ? Math.round(f.ratio * 100) : 0) + "%";

    const b = pb.beat || {};
    setText($("pb-beat"), b.name ? (b.name + "（还有 " + b.next_in + " 回合）") : "—");
    setText($("pb-guide"), pb.loop_guide || "");
  }

  /* ── 事业线：只显示已浮现的，最多 3 条（避免变成待办清单） ── */
  function renderQuests(v) {
    const box = $("quest-list");
    if (!box) return;
    const q = v.quests || {};
    const rows = (q.rows || []);
    setText($("quest-hint"), q.total
      ? ("已浮现 " + rows.length + " / 共 " + q.total)
      : "");
    box.textContent = "";
    if (!rows.length) {
      const s = document.createElement("span");
      s.className = "empty";
      s.textContent = q.total
        ? "这一局有 " + q.total + " 条事业线，还没到浮现的时候"
        : "这一局没有配置事业线";
      box.appendChild(s);
      return;
    }
    rows.slice(0, 4).forEach((r) => {
      const div = document.createElement("div");
      div.className = "quest" + (r.status === "done" ? " done" : (r.status === "failed" ? " failed" : ""));
      const b = document.createElement("b");
      b.textContent = r.title || r.id;
      div.appendChild(b);
      if (r.stage_title) {
        const st = document.createElement("span");
        st.className = "stage";
        st.textContent = r.stage_title;
        div.appendChild(st);
      }
      if (r.status === "done") {
        const d = document.createElement("span");
        d.className = "chip good";
        d.style.marginLeft = "6px";
        d.textContent = "已完成";
        div.appendChild(d);
      } else if (r.status === "failed") {
        const d = document.createElement("span");
        d.className = "chip bad";
        d.style.marginLeft = "6px";
        d.textContent = "已失败";
        div.appendChild(d);
      }
      if (r.summary) {
        const t = document.createElement("div");
        t.className = "tagline";
        t.textContent = r.summary;
        div.appendChild(t);
      }
      if ((r.objectives || []).length) {
        const ul = document.createElement("ul");
        r.objectives.forEach((o) => {
          const li = document.createElement("li");
          li.textContent = o;
          ul.appendChild(li);
        });
        div.appendChild(ul);
      }
      if (r.deadline_tick) {
        const t = document.createElement("div");
        t.className = "tagline";
        t.textContent = "期限：第 " + r.deadline_tick + " 回合";
        div.appendChild(t);
      }
      box.appendChild(div);
    });
    expander(box, rows.length, Math.min(4, rows.length), () => {
      rows.slice(4).forEach((r) => {
        const div = document.createElement("div");
        div.className = "quest";
        const b2 = document.createElement("b");
        b2.textContent = r.title || r.id;
        div.appendChild(b2);
        box.appendChild(div);
      });
    }, "条事业线");
  }

  /* ── 世界书：触发次数与冷却（解释"为什么这段被触发"） ── */
  /* ── 下一步提示：把"现在能做什么"写到输入框上方 ────────────────── */
  function renderNextMoves(v) {
    const box = $("next-moves");
    const list = $("next-moves-list");
    if (!box || !list) return;
    const moves = v.next_moves || [];
    if (!moves.length) { box.hidden = true; return; }
    box.hidden = false;
    list.textContent = "";
    moves.forEach((m) => {
      const chip = document.createElement("span");
      chip.className = "nm-chip " + (m.kind || "free");
      const label = document.createElement("span");
      label.textContent = m.text || "";
      chip.appendChild(label);
      if (m.why) {
        const why = document.createElement("span");
        why.className = "why";
        why.textContent = m.why;
        chip.appendChild(why);
      }
      chip.title = "点一下填进输入框";
      chip.addEventListener("click", () => {
        const ta = $("action-text");
        if (ta) { ta.value = m.text || ""; ta.focus(); }
      });
      list.appendChild(chip);
    });
  }

  /* ── 事业线地图：把 stage DAG 画出来（Twine 的 passage 图思路）───── */
  /* 状态色取自主题 token：亮色下用深绿/深红，暗色下用亮色，保证在两种底色上都可读 */
  function questNodeColor() {
    return {
      done: cssVar("--success", "#2f6b34"),
      current: cssVar("--accent", "#8a5a12"),
      open: cssVar("--text-faint", "#6b7382"),
      failed: cssVar("--danger", "#a8342b"),
    };
  }

  function renderQuestMap(v) {
    const card = $("questmap-card");
    const box = $("questmap");
    if (!card || !box) return;
    const graph = (v.quests || {}).graph || {};
    const nodes = graph.nodes || [];
    const edges = graph.edges || [];
    if (!nodes.length || typeof echarts === "undefined") {
      card.hidden = true;
      return;
    }
    card.hidden = false;
    const done = nodes.filter((n) => n.state === "done").length;
    setText($("questmap-hint"), done + " / " + nodes.length + " 幕已走过");

    if (!charts.questmap) charts.questmap = window.echarts.init(box, null, { renderer: "canvas" });

    // Force layout scatters nodes and overlaps their labels. A stage DAG has a
    // natural depth, so we lay it out ourselves: x = hop count from a root,
    // y = spread within the layer. Deterministic, readable, and it shows the
    // shape of the story instead of a hairball.
    const depthOf = {};
    const incoming = {};
    nodes.forEach((n) => { incoming[n.id] = 0; });
    edges.forEach((e) => { if (incoming[e.to] !== undefined) incoming[e.to] += 1; });
    const roots = nodes.filter((n) => !incoming[n.id]).map((n) => n.id);
    const queue = roots.length ? roots.slice() : [nodes[0].id];
    queue.forEach((id) => { depthOf[id] = 0; });
    const adjacency = {};
    edges.forEach((e) => { (adjacency[e.from] = adjacency[e.from] || []).push(e.to); });
    for (let i = 0; i < queue.length && i < 500; i++) {
      const id = queue[i];
      (adjacency[id] || []).forEach((nxt) => {
        const candidate = (depthOf[id] || 0) + 1;
        if (depthOf[nxt] === undefined || candidate > depthOf[nxt]) {
          depthOf[nxt] = candidate;
          queue.push(nxt);
        }
      });
    }
    const layers = {};
    nodes.forEach((n) => {
      const d = depthOf[n.id] === undefined ? 0 : depthOf[n.id];
      (layers[d] = layers[d] || []).push(n);
    });
    const COL_W = 150;
    const ROW_H = 74;
    const nodeColors = questNodeColor();
    const data = [];
    Object.keys(layers).forEach((d) => {
      layers[d].forEach((n, rowIdx) => {
        const yOffset = (rowIdx - (layers[d].length - 1) / 2) * ROW_H;
        data.push({
          id: n.id,
          name: n.title,
          x: Number(d) * COL_W,
          y: yOffset,
          symbolSize: n.state === "current" ? 22 : 14,
          itemStyle: {
            color: nodeColors[n.state] || nodeColors.open,
            borderColor: n.state === "current" ? cssVar("--surface-1", "#fffdf8") : "transparent",
            borderWidth: n.state === "current" ? 2 : 0,
          },
        });
      });
    });

    charts.questmap.setOption({
      backgroundColor: "transparent",
      tooltip: {
        formatter: (p) => {
          if (p.dataType === "edge") return "";
          const n = byId[p.data.id] || {};
          const lines = (n.objectives || []).map((o) => "· " + o).join("<br/>");
          return "<b>" + (n.title || "") + "</b><br/>" + (lines || "");
        },
      },
      series: [{
        type: "graph",
        layout: "none",
        roam: true,
        draggable: true,
        label: {
          show: true, color: cssVar("--text", "#1d2027"), fontSize: 11,
          position: "bottom", distance: 6,
        },
        lineStyle: { color: cssVar("--line-strong", "#bfb4a1"), width: 1.2, curveness: 0.06 },
        edgeSymbol: ["none", "arrow"],
        edgeSymbolSize: 5,
        data: data,
        links: edges.map((e) => ({ source: e.from, target: e.to })),
      }],
      animation: panelState.motion,
    }, true);

    // Fit the drawing into the card so nothing is cut off on first paint.
    try { charts.questmap.resize(); } catch (e) { /* chart not ready yet */ }
  }

  function renderLorebook(v) {
    const box = $("lore-rows");
    if (!box) return;
    const lb = v.lorebook || {};
    const rows = lb.rows || [];
    setText($("lore-hint"), lb.total ? (lb.total + " 条 · 已触发 " + rows.filter((r) => r.fired > 0).length) : "");
    box.textContent = "";
    if (!rows.length) {
      const s = document.createElement("span");
      s.className = "empty";
      s.textContent = "这一局没有世界书条目";
      box.appendChild(s);
      return;
    }
    rows.slice(0, 40).forEach((r) => {
      const div = document.createElement("div");
      div.className = "lore-row";
      const n = document.createElement("div");
      const b = document.createElement("div");
      b.className = "n";
      b.textContent = r.comment + (r.constant ? "（常驻）" : "");
      const k = document.createElement("div");
      k.className = "k";
      k.textContent = (r.keys || []).join(" / ") || "无关键词";
      n.appendChild(b);
      n.appendChild(k);
      const fired = document.createElement("div");
      fired.className = "c";
      fired.textContent = r.fired ? ("触发 " + r.fired + " 次") : "未触发";
      const state = document.createElement("div");
      state.className = "c";
      if (r.sticky_left > 0) state.textContent = "保留 " + r.sticky_left + " 回合";
      else if (r.cooldown_left > 0) state.textContent = "冷却 " + r.cooldown_left + " 回合";
      else state.textContent = "";
      div.appendChild(n);
      div.appendChild(fired);
      div.appendChild(state);
      box.appendChild(div);
    });
  }

  /* ── 通用游戏层：档案 / 判定 / 上下文 / 存档库 ─────────── */

  const KIND_LABEL = {
    rpg: "角色扮演", investigation: "调查", management: "经营",
    survival: "生存", story: "叙事", board: "桌游", custom: "自定义",
  };
  const CHECK_LEVEL_LABEL = {
    critical_success: "大成功", success: "成功", partial: "部分成功", failure: "失败",
  };
  const FACT_KIND_LABEL = {
    fact: "事实", clue: "线索", promise: "承诺", npc: "人物",
    place: "地点", item: "物品", rule: "规则", note: "备注",
  };

  function checkLevelClass(level) {
    if (level === "critical_success" || level === "success") return "lv ok";
    if (level === "partial") return "lv partial";
    return "lv bad";
  }

  function gameResRow(host, item) {
    const row = document.createElement("div");
    row.className = "game-res";
    const k = document.createElement("span");
    k.className = "k";
    k.textContent = item.label || item.key;
    const barwrap = document.createElement("div");
    barwrap.className = "barwrap";
    const bar = document.createElement("div");
    const lo = Number(item.min || 0);
    const hi = Number(item.max || 0);
    bar.className = "bar" + (item.color === "hp" ? " hp" : (item.color === "mp" ? " mp" : ""));
    bar.style.width = pct(Number(item.value || 0) - lo, hi > lo ? hi - lo : 0) + "%";
    barwrap.appendChild(bar);
    const v = document.createElement("span");
    v.className = "val";
    v.textContent = hi > lo
      ? (item.value + " / " + hi)
      : String(item.value == null ? "—" : item.value);
    row.appendChild(k);
    row.appendChild(barwrap);
    row.appendChild(v);
    host.appendChild(row);
  }

  function renderGame(v) {
    const g = v.game || {};
    const prof = g.profile || {};
    setText($("game-kind"), KIND_LABEL[prof.kind] || prof.kind || "");
    setText($("game-title"), prof.title || (v.world || {}).name || "—");

    const resBox = $("game-resources");
    if (resBox) {
      resBox.textContent = "";
      const res = prof.resources || [];
      if (!res.length) {
        const s = document.createElement("span");
        s.className = "empty";
        s.textContent = "（无资源轨）";
        resBox.appendChild(s);
      } else {
        res.forEach((item) => gameResRow(resBox, item));
      }
    }

    const attrBox = $("game-attributes");
    if (attrBox) {
      attrBox.textContent = "";
      (prof.attributes || []).forEach((item) => {
        const s = document.createElement("span");
        s.className = "chip dim";
        s.textContent = (item.label || item.key) + " " + item.value;
        attrBox.appendChild(s);
      });
    }

    const meterBox = $("game-meters");
    if (meterBox) {
      meterBox.textContent = "";
      (prof.meters || []).forEach((item) => gameResRow(meterBox, item));
    }

    const tagBox = $("game-tags");
    if (tagBox) {
      tagBox.textContent = "";
      (prof.tags || []).forEach((tag) => {
        const s = document.createElement("span");
        s.className = "chip accent";
        s.textContent = tag;
        tagBox.appendChild(s);
      });
    }

    const sheet = prof.sheet || {};
    const keys = Object.keys(sheet);
    const hint = $("game-sheet");
    if (hint) {
      hint.textContent = keys.length
        ? keys.slice(0, 8).map((k) => k + "：" + sheet[k]).join(" · ")
        : "";
    }

    renderChecks(g);
    renderContext(g);
    renderSessions(v);
  }

  function renderChecks(g) {
    const box = $("checks");
    if (!box) return;
    const rows = g.checks || [];
    const rate = g.check_rate || {};
    setText($("checks-hint"), rate.total
      ? (rate.success + "/" + rate.total + " 成功 · " + Math.round((rate.rate || 0) * 100) + "%")
      : "");
    box.textContent = "";
    if (!rows.length) {
      const s = document.createElement("span");
      s.className = "empty";
      s.textContent = g.check_error
        ? ("判定记录读取失败：" + g.check_error)
        : "还没有判定——宿主可以调 roll / combat / social 结算";
      box.appendChild(s);
      return;
    }
    rows.slice(0, 10).forEach((r) => {
      const div = document.createElement("div");
      div.className = "check-row";
      const lv = document.createElement("span");
      lv.className = checkLevelClass(r.level);
      lv.textContent = CHECK_LEVEL_LABEL[r.level] || r.level || "—";
      const mid = document.createElement("div");
      const why = document.createElement("div");
      why.className = "why";
      why.textContent = (r.reason || (r.actor + " · " + (r.attribute || "无属性")));
      const num = document.createElement("div");
      num.className = "num";
      num.textContent = r.total + " vs " + r.difficulty;
      mid.appendChild(why);
      mid.appendChild(num);
      const dice = document.createElement("span");
      dice.className = "num";
      dice.textContent = r.dice || "";
      div.appendChild(lv);
      div.appendChild(mid);
      div.appendChild(dice);
      box.appendChild(div);
    });
  }

  function renderContext(g) {
    const ctx = g.context || {};
    const hint = $("ctx-hint");
    if (hint) hint.textContent = (ctx.open || 0) + " 条未结案 · 共 " + (ctx.total || 0);
    const stats = $("ctx-stats");
    if (stats) {
      stats.textContent = "";
      Object.entries(ctx.by_kind || {}).forEach(([k, n]) => {
        if (!n) return;
        const s = document.createElement("span");
        s.className = "chip dim";
        s.textContent = (FACT_KIND_LABEL[k] || k) + " " + n;
        stats.appendChild(s);
      });
    }
    const box = $("ctx-rows");
    if (!box) return;
    box.textContent = "";
    const rows = ctx.recent || [];
    if (!rows.length) {
      const s = document.createElement("span");
      s.className = "empty";
      s.textContent = ctx.error ? ("台账读取失败：" + ctx.error) : "台账为空——宿主可用 context_remember 记线索与承诺";
      box.appendChild(s);
      return;
    }
    rows.forEach((r) => {
      const div = document.createElement("div");
      div.className = "ctx-row";
      const kind = document.createElement("span");
      kind.className = "kind";
      kind.textContent = FACT_KIND_LABEL[r.kind] || r.kind || "事实";
      const right = document.createElement("div");
      const txt = document.createElement("div");
      txt.className = "txt";
      txt.textContent = r.text || "";
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = "第 " + (r.tick || 0) + " 回合" +
        ((r.keys || []).length ? " · " + r.keys.join(" / ") : "");
      right.appendChild(txt);
      right.appendChild(meta);
      div.appendChild(kind);
      div.appendChild(right);
      box.appendChild(div);
    });
  }

  function renderSessions(v) {
    const s = v.sessions || {};
    const hint = $("sess-hint");
    if (hint) hint.textContent = s.count ? (s.count + " 局 · 回收站 " + (s.trash || 0)) : "";
    const box = $("sess-rows");
    if (!box) return;
    box.textContent = "";
    const rows = s.saves || [];
    if (!rows.length) {
      const p = document.createElement("span");
      p.className = "empty";
      p.textContent = s.error
        ? ("存档库读取失败：" + s.error)
        : "存档库为空——用 session_new 新建一局（存档会集中在这个目录）";
      box.appendChild(p);
      if (s.root) {
        const h = document.createElement("div");
        h.className = "meta";
        h.style.marginTop = "6px";
        h.textContent = "目录：" + s.root;
        box.appendChild(h);
      }
      return;
    }
    rows.forEach((r) => {
      const div = document.createElement("div");
      div.className = "sess-row" + (r.active ? " active" : "");
      const left = document.createElement("div");
      const n = document.createElement("div");
      n.className = "n";
      n.textContent = (r.broken ? "（损坏）" : "") + r.name;
      const m = document.createElement("div");
      m.className = "m";
      m.textContent = [r.world || "未命名世界", r.player || "", r.updated || ""]
        .filter(Boolean).join(" · ");
      left.appendChild(n);
      left.appendChild(m);
      const num = document.createElement("span");
      num.className = "num";
      num.textContent = "第 " + (r.tick || 0) + " 回合" + (r.active ? " · 当前" : "");
      div.appendChild(left);
      div.appendChild(num);
      box.appendChild(div);
    });
  }

  /* ── 体系：时间/掉落/制造/声望/成就/成长/自定义 ── */
  const SYS_KIND_LABEL = {
    time: "时间", loot: "掉落", craft: "制造", reputation: "声望",
    achievement: "成就", progression: "成长", custom: "自定义",
  };

  function sysSummary(kind, s) {
    if (!s) return "";
    if (kind === "time") {
      return [s.clock, "第 " + (s.day || 0) + " 天", s.season, s.weather].filter(Boolean).join(" · ");
    }
    if (kind === "reputation") {
      const facs = Object.entries(s.factions || {});
      return facs.length
        ? facs.slice(0, 3).map(([k, v]) => k + " " + v.value + "(" + v.tier + ")").join(" · ")
        : "（无势力）";
    }
    if (kind === "achievement") return "已解锁 " + (s.unlocked || 0) + " / " + (s.total || 0);
    if (kind === "progression") return "Lv." + (s.level || 1) + " · " + (s.xp || 0) + "/" + (s.need || 0) + " XP";
    if (kind === "loot") return (s.tables || []).length + " 张表";
    if (kind === "craft") return (s.recipes || 0) + " 个配方";
    if (kind === "custom") return (s.actions || []).length + " 个动作";
    return "";
  }

  function renderSystems(v) {
    const box = $("system-rows");
    if (!box) return;
    const sys = v.systems || {};
    const rows = sys.rows || [];
    setText($("systems-hint"), rows.length ? (rows.length + " 套体系") : "");
    box.textContent = "";
    if (!rows.length) {
      const s = document.createElement("span");
      s.className = "empty";
      s.textContent = sys.error
        ? ("体系读取失败：" + sys.error)
        : "这一局还没配置体系——宿主可用 system_define 或 template_start 载入";
      box.appendChild(s);
      return;
    }
    rows.forEach((r) => {
      const div = document.createElement("div");
      div.className = "sys-row";
      const left = document.createElement("div");
      const n = document.createElement("span");
      n.className = "n";
      n.textContent = r.label || r.id;
      const k = document.createElement("span");
      k.className = "k";
      k.textContent = SYS_KIND_LABEL[r.kind] || r.kind;
      left.appendChild(n);
      left.appendChild(k);
      const sum = document.createElement("span");
      sum.className = "sum";
      sum.textContent = sysSummary(r.kind, r.summary);
      div.appendChild(left);
      div.appendChild(sum);
      box.appendChild(div);
    });
    const note = $("systems-note");
    if (note) {
      note.textContent = "体系动作由宿主执行（system_run）：时间推进、掉落、制造、声望、成就、成长、自定义动作。";
    }
  }

  /* ── 剧情回放：完整正文（vm.prose） + 归档检索（/history） ── */
  const storyState = { query: "", scope: "all", archive: null, loading: false, error: "" };

  function storyItem(row, current) {
    const div = document.createElement("div");
    div.className = "story-item" + (current ? " current" : "");
    const head = document.createElement("div");
    head.className = "head";
    const tick = document.createElement("b");
    tick.textContent = "第 " + (row.tick != null ? row.tick : "?") + " 回合";
    head.appendChild(tick);
    if (row.location) {
      const loc = document.createElement("span");
      loc.textContent = row.location;
      head.appendChild(loc);
    }
    if (row.type) {
      const t = document.createElement("span");
      t.textContent = row.type;
      head.appendChild(t);
    }
    if (row.chars != null) {
      const c = document.createElement("span");
      c.textContent = row.chars + " 字";
      head.appendChild(c);
    }
    const body = document.createElement("div");
    body.className = "body" + ((row.text || "").length > 320 ? " clamp" : "");
    body.textContent = row.text || "";
    div.appendChild(head);
    div.appendChild(body);
    if ((row.text || "").length > 320) {
      const more = document.createElement("button");
      more.type = "button";
      more.className = "more";
      more.textContent = "展开全文";
      more.addEventListener("click", () => {
        const open = body.classList.toggle("clamp") === false;
        more.textContent = open ? "收起" : "展开全文";
      });
      div.appendChild(more);
    }
    return div;
  }

  function renderStory(v) {
    const box = $("story-rows");
    if (!box) return;
    const pr = (v.prose || {});
    const items = (pr.items || []).slice().reverse();   // 最新在前
    const q = storyState.query.trim().toLowerCase();
    const matches = q ? items.filter((x) => (x.text || "").toLowerCase().indexOf(q) >= 0) : items;
    setText($("story-hint"), pr.total
      ? (pr.shown + " / 共 " + pr.total + " 段" + (pr.truncated ? "（更早的在归档）" : ""))
      : "");
    box.textContent = "";
    if (!matches.length && storyState.scope !== "archive") {
      const s = document.createElement("span");
      s.className = "empty";
      s.textContent = q ? "正文里没有匹配「" + storyState.query + "」的段落" : "还没有正文";
      box.appendChild(s);
    }
    if (storyState.scope !== "archive") {
      matches.slice(0, 60).forEach((row, i) => {
        box.appendChild(storyItem(row, i === 0 && !storyState.archive));
      });
    }
    // 归档检索结果（服务端已按 limit 截断）
    if (storyState.scope !== "prose" && storyState.archive) {
      const arch = storyState.archive.archive || {};
      const rows = arch.items || [];
      const sep = document.createElement("div");
      sep.className = "hint";
      sep.style.marginTop = "12px";
      sep.textContent = "归档命中 " + (arch.matched || 0) + " 条（扫描 " + (arch.scanned || 0)
        + " 行，显示 " + rows.length + " 条）";
      box.appendChild(sep);
      rows.slice().reverse().forEach((row) => box.appendChild(storyItem(row, false)));
    }
    const meta = $("story-meta");
    if (meta) {
      meta.textContent = storyState.loading
        ? "正在检索归档…"
        : (storyState.error ? "归档检索失败：" + storyState.error : "");
    }
  }

  function fetchHistory() {
    if (storyState.loading) return;
    storyState.loading = true;
    storyState.error = "";
    renderStory(panelState.vm || {});
    const params = new URLSearchParams();
    if (storyState.query.trim()) params.set("q", storyState.query.trim());
    params.set("scope", storyState.scope);
    params.set("limit", "80");
    fetch("/history?" + params.toString())
      .then((r) => r.json())
      .then((data) => { storyState.archive = data; })
      .catch(() => { storyState.error = "网络错误"; })
      .finally(() => {
        storyState.loading = false;
        renderStory(panelState.vm || {});
      });
  }

  function wireStory() {
    const search = $("story-search");
    if (search) {
      let t = null;
      search.addEventListener("input", () => {
        storyState.query = search.value || "";
        clearTimeout(t);
        t = setTimeout(() => {
          if (storyState.scope !== "prose") fetchHistory();
          else renderStory(panelState.vm || {});
        }, 220);
      });
      search.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape") {
          search.value = "";
          storyState.query = "";
          renderStory(panelState.vm || {});
        }
      });
    }
    const scopeBox = $("story-scope");
    if (scopeBox) {
      scopeBox.addEventListener("click", (ev) => {
        const btn = ev.target.closest("[data-scope]");
        if (!btn) return;
        storyState.scope = btn.dataset.scope || "all";
        scopeBox.querySelectorAll("[data-scope]").forEach((b) => {
          b.setAttribute("aria-pressed", String(b === btn));
        });
        if (storyState.scope === "prose") renderStory(panelState.vm || {});
        else fetchHistory();
      });
    }
    const btn = $("story-refresh");
    if (btn) btn.addEventListener("click", () => fetchHistory());
    const topBtn = $("story-btn");
    if (topBtn) topBtn.addEventListener("click", () => openDrawer("drawer-story"));
  }

  function openDrawer(id) {
    const d = $(id);
    if (!d) return;
    d.open = true;
    requestAnimationFrame(() => d.scrollIntoView({ block: "nearest", behavior: "smooth" }));
  }

  function openCardDialog(c, rel, trigger) {
    const dlg = $("carddlg");
    if (!dlg || typeof dlg.showModal !== "function") return;
    setText($("card-name"), c.name || "角色");
    const bits = [c.level, c.faction, rel ? ("亲密 " + rel.affinity + " · 敬重 " + rel.respect) : ""]
      .filter(Boolean);
    setText($("card-meta-line"), bits.join(" · "));
    const sec = (title, body) => {
      if (!body) return null;
      const wrap = document.createElement("section");
      wrap.className = "card-sec";
      const h = document.createElement("h4");
      h.textContent = title;
      const p = document.createElement("p");
      p.textContent = body;
      wrap.appendChild(h);
      wrap.appendChild(p);
      return wrap;
    };
    const host = $("card-body");
    host.textContent = "";
    [
      sec("关于", c.desc),
      sec("性情", c.personality),
      sec("口吻", c.speech),
      sec("状态", (c.hp != null ? "气血 " + c.hp + "/" + c.hp_max : "") +
        (c.mind_scars ? " · 心伤 " + c.mind_scars : "")),
    ].forEach((el) => { if (el) host.appendChild(el); });
    panelState.cardReturn = trigger || document.activeElement;
    if (!dlg.open) dlg.showModal();
  }

  /* ── 首屏加载态：骨架屏 + 顶部进度条 ───────────────
     "正在加载"只该出现一次（第一帧数据到达前）。之后 SSE 每回合刷新都是
     局部重绘，不该再让整页回到骨架屏——那会让长局里每次刷新都闪一下。 */
  function setBootState(state) {
    document.body.dataset.boot = state;
    const bar = $("bootbar");
    if (bar) bar.hidden = state === "ready";
    if (state === "ready") {
      const status = $("boot-status");
      if (status) status.textContent = "";
    }
  }

  /* ── 主题：默认亮色，可切暗色；选择记住，刷新不闪 ── */
  function paintThemeButtons() {
    const theme = (window.PanelTheme && window.PanelTheme.current())
      || document.documentElement.getAttribute("data-theme") || "light";
    document.querySelectorAll("[data-set-theme]").forEach((btn) => {
      btn.setAttribute("aria-pressed", String(btn.getAttribute("data-set-theme") === theme));
    });
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "dark" ? "#0d0f13" : "#f6f4ee");
  }

  /* ECharts 画在 canvas 上，不继承 CSS 变量——换主题后必须重画，
     否则会留下"亮底 + 深色图表"这种半截效果。 */
  function refreshChartTheme() {
    const pal = chartPalette(panelState.vm || {});
    Object.keys(charts).forEach((key) => {
      const chart = charts[key];
      if (!chart) return;
      try {
        chart.setOption({
          backgroundColor: "transparent",
          textStyle: { color: pal.text },
          tooltip: { backgroundColor: pal.surface, borderColor: pal.grid,
                     textStyle: { color: pal.ink } },
          legend: { textStyle: { color: pal.text } },
          xAxis: { axisLine: { lineStyle: { color: pal.grid } }, axisLabel: { color: pal.text } },
          yAxis: { splitLine: { lineStyle: { color: pal.grid, opacity: .5 } },
                   axisLabel: { color: pal.text } },
        });
      } catch (e) { /* 图表尚未初始化 */ }
    });
  }

  function wireTheme() {
    if (!window.PanelTheme) return;
    paintThemeButtons();
    document.querySelectorAll("[data-set-theme]").forEach((btn) => {
      btn.addEventListener("click", () => {
        window.PanelTheme.set(btn.getAttribute("data-set-theme"));
        paintThemeButtons();
        refreshChartTheme();
        if (panelState.vm) render(panelState.vm);
      });
    });
    window.addEventListener("panelthemechange", () => {
      paintThemeButtons();
      if (panelState.vm) applySkinAccent(panelState.vm.skin);
      refreshChartTheme();
    });
  }

  function boot() {
    wireTheme();
    wireDrawers();
    wireStory();
    fetchState();
    // 兜底：任何原因导致首帧没到（脚本报错、服务假死），8 秒后也要收掉骨架屏，
    // 让连接横幅成为唯一的信息来源，而不是让用户对着一张永远转的骨架屏。
    setTimeout(() => setBootState("ready"), 8000);

    if (window.EventSource) {
      const es = new EventSource("/events");
      es.addEventListener("state", (ev) => {
        try {
          const v = JSON.parse(ev.data);
          lastData = Date.now();
          if (v && v.error) {
            setConn("stale", "状态不可读");
          } else {
            setConn("live", "实况 · " + (v.updated_at || ""));
            setBootState("ready");
          }
          apply(v);
        } catch (err) { /* 单帧解析失败不打断流 */ }
      });
      es.onerror = () => { setConn("stale", "信号不稳，轮询兜底…"); };
    }

    // 轮询兜底：SSE 静默超过 4 秒就自己拉
    setInterval(() => {
      if (Date.now() - lastData > 4000) fetchState();
    }, 2500);
    setInterval(() => {
      if (Date.now() - lastData > 8000) setConn("down", "连接中断，重试中…");
    }, 4000);

    $("jump-latest").addEventListener("click", () => {
      const ul = $("timeline");
      if (ul) ul.scrollTop = 0;
    });

    $("notice-retry").addEventListener("click", () => fetchState());

    const motionBtn = $("motion");
    motionBtn.addEventListener("click", () => {
      panelState.motion = !panelState.motion;
      document.documentElement.style.setProperty("--speed", panelState.motion ? ".22s" : "0s");
      motionBtn.setAttribute("aria-pressed", String(!panelState.motion));
      setText(motionBtn, panelState.motion ? "动效：开" : "动效：关");
      Object.keys(charts).forEach((k) => {
        if (charts[k]) charts[k].setOption({ animation: panelState.motion });
      });
    });

    // 图表随窗口尺寸重排（rAF 节流）
    let resizeQueued = false;
    window.addEventListener("resize", () => {
      if (resizeQueued) return;
      resizeQueued = true;
      window.requestAnimationFrame(() => {
        resizeQueued = false;
        Object.keys(charts).forEach((k) => { if (charts[k]) charts[k].resize(); });
      });
    });

    /* ── 时间线搜索与筛选 ───────────────── */
    const search = $("event-search");
    if (search) {
      let t = null;
      search.addEventListener("input", () => {
        timelineQuery = search.value || "";
        clearTimeout(t);
        t = setTimeout(applyTimelineFilter, 80);
      });
      search.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape") { search.value = ""; timelineQuery = ""; applyTimelineFilter(); }
      });
    }
    const filterBox = $("event-filter");
    if (filterBox) {
      filterBox.addEventListener("click", (ev) => {
        const btn = ev.target.closest("[data-filter]");
        if (!btn) return;
        timelineFilter = btn.dataset.filter || "all";
        filterBox.querySelectorAll("[data-filter]").forEach((b) => {
          b.setAttribute("aria-pressed", String(b === btn));
        });
        applyTimelineFilter();
      });
    }

    /* ── 分享模式：隐藏路径 / 队列 / 导出入口，专供截图直播 ── */
    const shareBtn = $("share-btn");
    const setShare = (on) => {
      document.body.dataset.share = on ? "on" : "off";
      if (shareBtn) {
        shareBtn.setAttribute("aria-pressed", String(on));
        setText(shareBtn, on ? "分享模式：开" : "分享模式");
      }
      storageSet("ww_share", on ? "1" : "0");
    };
    if (shareBtn) {
      shareBtn.addEventListener("click", () => setShare(document.body.dataset.share !== "on"));
      setShare(storageGet("ww_share") === "1");
    }

    /* ── 导出当前状态（服务端只读直出，不经过前端拼装）── */
    const exportBtn = $("export-btn");
    if (exportBtn) {
      exportBtn.addEventListener("click", () => { window.location.href = "/export"; });
    }

    /* ── 行动队列：浏览器排队 → 宿主用 pending_actions 取走 ── */
    const composer = $("composer");
    if (composer) {
      const ta = $("action-text");
      const send = $("action-send");
      const refreshInbox = () => {
        fetch("/actions").then((r) => r.json()).then((d) => {
          setText($("inbox-count"), String((d.pending || []).length));
        }).catch(() => {});
      };
      const submit = () => {
        const text = (ta.value || "").trim();
        if (!text) return;
        send.disabled = true;
        setText(send, "…");
        fetch("/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: text }),
        }).then((r) => r.json()).then((d) => {
          if (d && d.ok) {
            ta.value = "";
            ta.style.height = "";
            setText($("inbox-status"), "已排队（共 " + d.pending + " 条）");
            setTimeout(() => setText($("inbox-status"), "指挥官在对话里取走"), 3200);
            refreshInbox();
          } else {
            setText($("inbox-status"), (d && d.error) || "排队失败");
          }
        }).catch(() => setText($("inbox-status"), "排队失败：面板未连接"))
          .finally(() => { send.disabled = false; setText(send, "排队"); });
      };
      composer.addEventListener("submit", (ev) => { ev.preventDefault(); submit(); });
      ta.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); submit(); }
      });
      ta.addEventListener("input", () => {
        ta.style.height = "auto";
        ta.style.height = Math.min(132, ta.scrollHeight) + "px";
      });
      refreshInbox();
      setInterval(refreshInbox, 5000);
    }

    const cardDlg = $("carddlg");
    if (cardDlg) {
      cardDlg.addEventListener("close", () => {
        const back = panelState.cardReturn;
        panelState.cardReturn = null;
        if (back && document.contains(back)) back.focus();
      });
      const cc = $("card-close");
      if (cc) cc.addEventListener("click", () => cardDlg.close());
    }

    $("dlg-close").addEventListener("click", closeDialog);
    $("dlg-ok").addEventListener("click", closeDialog);
    $("eventdlg").addEventListener("close", () => {
      // 原生 Esc / cancel 也要归还焦点
      if (panelState.focusReturn && document.contains(panelState.focusReturn)) {
        panelState.focusReturn.focus();
      }
      panelState.focusReturn = null;
      panelState.dialogFor = null;
    });

    /* ── 命令面板：Ctrl/⌘+K，键盘可达（listbox 语义）── */
    const COMMANDS = [
      { k: "图鉴", run: () => openDrawer("drawer-codex") },
      { k: "市场", run: () => openDrawer("drawer-market") },
      { k: "大事记", run: () => openDrawer("drawer-milestones") },
      { k: "势力", run: () => openDrawer("drawer-world") },
      { k: "世界标记", run: () => openDrawer("drawer-flags") },
      { k: "世界书", run: () => openDrawer("drawer-lorebook") },
      { k: "剧情回放", run: () => openDrawer("drawer-story") },
      { k: "上下文台账", run: () => openDrawer("drawer-context") },
      { k: "存档库", run: () => openDrawer("drawer-sessions") },
      { k: "帮助", run: () => openHelp($("help-btn")) },
      { k: "跳到最新", run: () => { const ul = $("timeline"); if (ul) ul.scrollTop = 0; } },
      { k: "导出状态", run: () => { window.location.href = "/export"; } },
      { k: "分享模式", run: () => $("share-btn") && $("share-btn").click() },
      { k: "动效开关", run: () => $("motion") && $("motion").click() },
    ];
    const palette = $("palette");
    const pInput = $("palette-input");
    const pList = $("palette-list");
    let pItems = [];
    let pIndex = 0;

    const paintPalette = () => {
      if (!pList) return;
      pList.textContent = "";
      pItems.forEach((cmd, i) => {
        const li = document.createElement("li");
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", String(i === pIndex));
        const span = document.createElement("span");
        span.textContent = cmd.k;
        li.appendChild(span);
        li.addEventListener("click", () => { runPalette(cmd); });
        pList.appendChild(li);
      });
    };
    const filterPalette = () => {
      const q = (pInput.value || "").trim().toLowerCase();
      pItems = q ? COMMANDS.filter((c) => c.k.toLowerCase().indexOf(q) >= 0) : COMMANDS.slice();
      pIndex = 0;
      paintPalette();
    };
    const runPalette = (cmd) => {
      if (palette && palette.open) palette.close();
      if (cmd) cmd.run();
    };
    const openPalette = () => {
      if (!palette || typeof palette.showModal !== "function") return;
      pInput.value = "";
      filterPalette();
      if (!palette.open) palette.showModal();
      pInput.focus();
    };
    const paletteBtn = $("palette-btn");
    if (paletteBtn) paletteBtn.addEventListener("click", openPalette);
    if (pInput) {
      pInput.addEventListener("input", filterPalette);
      pInput.addEventListener("keydown", (ev) => {
        if (ev.key === "ArrowDown") {
          ev.preventDefault();
          pIndex = Math.min(pItems.length - 1, pIndex + 1);
          paintPalette();
        } else if (ev.key === "ArrowUp") {
          ev.preventDefault();
          pIndex = Math.max(0, pIndex - 1);
          paintPalette();
        } else if (ev.key === "Enter") {
          ev.preventDefault();
          runPalette(pItems[pIndex]);
        }
      });
    }
    document.addEventListener("keydown", (ev) => {
      const mod = ev.ctrlKey || ev.metaKey;
      if (mod && (ev.key === "k" || ev.key === "K")) {
        ev.preventDefault();
        if (palette && palette.open) palette.close(); else openPalette();
      }
    });

    /* ── 帮助：入口按钮 + `?` 快捷键（不打扰正在输入的场景，本页无输入框）── */
    const helpBtn = $("help-btn");
    if (helpBtn) {
      helpBtn.addEventListener("click", () => openHelp(helpBtn));
    }
    const helpClose = $("help-close");
    if (helpClose) helpClose.addEventListener("click", () => closeHelp());
    document.addEventListener("keydown", (ev) => {
      const tagNow = (ev.target && ev.target.tagName) || "";
      if (!ev.ctrlKey && !ev.metaKey && !ev.altKey
          && (ev.key === "s" || ev.key === "S")
          && tagNow !== "INPUT" && tagNow !== "TEXTAREA") {
        ev.preventDefault();
        openDrawer("drawer-story");
        return;
      }
      if (ev.key === "?" || (ev.key === "/" && ev.shiftKey)) {
        const tag = (ev.target && ev.target.tagName) || "";
        if (tag === "INPUT" || tag === "TEXTAREA") return;
        ev.preventDefault();
        const dlg = $("helpdlg");
        if (dlg && dlg.open) closeHelp(); else openHelp(helpBtn);
      }
    });

    /* ── 首访一次引导：localStorage 记忆；隐私模式下降级为本次会话内记忆 ── */
    const seen = storageGet("ww_guide_seen");
    if (!seen) {
      const g = $("guide");
      if (g) g.hidden = false;
    }
    const gc = $("guide-close");
    if (gc) {
      gc.addEventListener("click", () => {
        const g = $("guide");
        if (g) g.hidden = true;
        storageSet("ww_guide_seen", "1");
      });
    }
  }

  /* ── 帮助弹窗 ─────────────────────────────────────── */
  let helpReturn = null;

  function storageGet(k) {
    try { return window.localStorage.getItem(k); } catch (e) { return panelState["_" + k] || null; }
  }

  function storageSet(k, v) {
    try { window.localStorage.setItem(k, v); } catch (e) { panelState["_" + k] = v; }
  }

  function fillHelp() {
    const v = panelState.vm || {};
    const meta = v.meta || {};
    const skin = v.skin || {};
    setText($("help-state-path"), meta.state_path || "（尚未开局）");
    setText($("help-sidecar-path"), meta.sidecar || "—");
    setText($("help-skin"), (skin.id || "—") + (skin.motif ? "（" + skin.motif + "）" : ""));
  }

  function openHelp(trigger) {
    const dlg = $("helpdlg");
    if (!dlg || typeof dlg.showModal !== "function") return;
    fillHelp();
    helpReturn = trigger || document.activeElement;
    if (!dlg.open) dlg.showModal();
  }

  function closeHelp() {
    const dlg = $("helpdlg");
    if (!dlg || !dlg.open) return;
    dlg.close();
    if (helpReturn && document.contains(helpReturn)) helpReturn.focus();
    helpReturn = null;
  }

  /* ── 语言切换：面板主界面与 README 一样支持中英，英文为默认 ── */
  function wireLanguage() {
    const i18n = window.PanelI18n;
    if (!i18n) return;
    i18n.setLang(i18n.detect());
    document.querySelectorAll("[data-set-panel-lang]").forEach((btn) => {
      btn.addEventListener("click", () => {
        i18n.setLang(btn.getAttribute("data-set-panel-lang"));
        // 切换语言后重新渲染一次，让动态文案（回合数、空态、抽屉）也跟上
        if (panelState.vm) render(panelState.vm);
        if (window.PanelI18n) window.PanelI18n.translateDom(document.body);
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => { wireLanguage(); boot(); });
  } else {
    wireLanguage();
    boot();
  }
})();
