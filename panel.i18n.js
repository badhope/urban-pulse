/*
 World Games · panel i18n (runtime translator)

 Why a runtime translator instead of 200 `t("key")` call sites:
 the panel renders through 24 pure render functions that write text with
 `textContent`. Threading a translation call through every one of them would
 touch hundreds of lines of logic that has nothing to do with language, and
 every future render addition would silently forget to translate.

 Instead this module translates *after* rendering, at the DOM level:
   - exact dictionary entries handle fixed labels,
   - template entries ("回合 {n}") handle composed strings,
   - anything not in the dictionary is left untouched, so game content
     (world names, character names, authored prose) is never mangled.

 Switching language re-applies from the stored original, so zh <-> en is lossless.

 Constraints (ARCHITECTURE.md §12.1): this file contains no business logic and
 never writes to the state file. It only rewrites text nodes and the
 placeholder / title / aria-label / alt attributes of the panel chrome.
*/

(function (global) {
  "use strict";

  /* ── Fixed labels: Chinese source text → English ─────────────────────── */
  var EN = {
    /* top bar */
    "World Games · 主舞台": "World Games · Stage",
    "万物皆可为一局 · 规则为证": "Any world, one ruleset",
    "回合 —": "Turn —",
    "连接中…": "Connecting…",
    "连接中断，重试中…": "Connection lost, retrying…",
    "连接失败，重试中…": "Connection failed, retrying…",
    "信号不稳，轮询兜底…": "Signal unstable, polling…",
    "帮助": "Help",
    "命令": "Commands",
    "分享模式": "Share mode",
    "剧情": "Story",
    "导出": "Export",
    "动效：开": "Motion: on",
    "动效：关": "Motion: off",
    "重试": "Retry",
    "知道了": "Got it",
    "知道了（Esc）": "Got it (Esc)",
    "关闭": "Close",
    "继续": "Continue",
    "跳到最新": "Jump to latest",
    "刷新": "Refresh",
    "收起": "Collapse",
    "展开全文": "Show all",
    "排队": "Queue",
    "搜索事件": "Search events",

    /* tooltips / aria */
    "帮助与术语（快捷键 ?）": "Help and glossary (press ?)",
    "命令面板（Ctrl/⌘ + K）": "Command palette (Ctrl/⌘ + K)",
    "分享模式：隐藏存档路径与操作提示，适合截图与直播":
      "Share mode: hides save paths and control hints, good for screenshots and streaming",
    "打开剧情回放（快捷键 S）": "Open story replay (press S)",
    "下载当前对局状态 JSON（只读导出）": "Download the current state as JSON (read-only export)",
    "暂停/恢复界面动效": "Pause or resume interface motion",
    "关闭这条提示": "Dismiss this notice",
    "玩家状态": "Player state",
    "叙事主舞台": "Narrative stage",
    "在场角色与关系": "Present characters and relationships",
    "事件时间线": "Event timeline",
    "按类型筛选事件": "Filter events by kind",
    "按类型的事件分布": "Event distribution by kind",
    "人物关系网：中心为玩家，四周为已结缘人物":
      "Relationship graph: you in the centre, everyone you have bonded with around you",
    "地点分布：当前所在地高亮，连线表示已走动过的路线":
      "Place map: the current location is highlighted; lines are routes you have travelled",
    "气血条": "HP bar",
    "内力条": "Power bar",
    "进度条": "Progress bar",
    "失败条": "Failure bar",
    "气血内力钱财随回合变化曲线": "HP, power and coin over turns",
    "未清业债与人情均值随回合变化": "Unsettled karma and mean relation over turns",
    "物价指数偏离基准的走势": "Price index deviation from baseline",
    "你想做什么": "What do you want to do",
    "搜索剧情与归档": "Search story and archive",
    "检索范围": "Search scope",
    "可用命令": "Available commands",
    "命令面板": "Command palette",

    /* left column */
    "行者": "Character",
    "名号": "Name",
    "境界": "Tier",
    "所在": "At",
    "气血": "HP",
    "内力": "Power",
    "气血吃紧": "HP low",
    "游戏档案": "Game profile",
    "本局": "Session",
    "（无资源轨）": "(no resource tracks)",
    "状态 · 引擎推导": "State · engine-derived",
    "心流": "Flow",
    "世界相位": "World phase",
    "未清因果债": "Unsettled karma",
    "心流偏低时适合安排缓冲剧情；相位决定大事件的烈度。":
      "Low flow suits a calmer scene; the phase sets how hard events hit.",
    "玩法": "Playbook",
    "进度": "Progress",
    "失败": "Failure",
    "当前节拍": "Current beat",
    "体系": "Subsystems",
    "这一局还没配置体系——宿主可用 system_define 或 template_start 载入":
      "No subsystems in this game yet — the host can call system_define or template_start.",
    "随身": "Carrying",
    "（空手）": "(empty-handed)",

    /* middle column */
    "未开幕": "Not started",
    "等待状态文件…": "Waiting for a state file…",
    "（尚无场景描写——开局后由状态与摘要填充）":
      "(No scene description yet — filled in from state and summaries once play begins.)",
    "判定记录": "Checks",
    "还没有判定——宿主可以调 roll / combat / social 结算":
      "No checks yet — the host can call roll / combat / social.",
    "事业线": "Questlines",
    "这一局还没有浮现的事业线": "No questlines have surfaced in this game yet.",
    "编年史": "Chronicle",
    "全部": "All",
    "交锋": "Combat",
    "人情": "Social",
    "交易": "Trade",
    "大事": "Milestone",
    "暂无事件": "No events yet",
    "行藏曲线": "Progress curves",
    "气血 / 内力 / 钱财 · 随回合": "HP / power / coin over turns",
    "还没有足够的回合样本——推进几个回合后这里会画出行藏曲线。":
      "Not enough samples yet — advance a few turns and this chart fills in.",
    "业债与心境": "Karma and mood",
    "未清业债 · 人情均值": "Unsettled karma · mean relation",
    "暂无样本。": "No samples yet.",
    "市价偏离": "Price deviation",
    "1.0 = 基准": "1.0 = baseline",
    "世界脉搏": "World pulse",
    "存量": "Stock",
    "连接度": "Connectivity",
    "烈度": "Intensity",
    "事件谱": "Event spectrum",

    /* right column */
    "在场": "Present",
    "此刻无人": "Nobody here",
    "人情关系": "Relationships",
    "（尚未结缘）": "(No bonds yet)",
    "境地": "Territory",
    "修行轨": "Progression",

    /* drawers */
    "剧情回放": "Story replay",
    "每一次": "Every",
    "的完整正文都在这里（不截断）。面板只读，不会改动剧情。":
      " body written by publish_prose lives here in full, never truncated. The panel is read-only and will not alter the story.",
    "还没有正文——宿主用 publish_prose 写入后这里会出现":
      "No prose yet — it appears here once the host calls publish_prose",
    "正文": "Prose",
    "归档": "Archive",
    "探索图鉴": "Codex",
    "已探索地点": "Places explored",
    "已遇见人物": "People met",
    "经手物品": "Items handled",
    "已触发设定": "Entries triggered",
    "市场行情": "Market",
    "▲高于基准 · ▼低于基准": "▲ above baseline · ▼ below baseline",
    "此界无市": "No market in this world",
    "世界标记": "World flags",
    "势力与风向": "Factions and winds",
    "世界还没开始演化": "The world has not started evolving",
    "传闻": "Rumors",
    "暂无传闻": "No rumors yet",
    "风气": "Culture",
    "世界书": "Lorebook",
    "这里显示每条设定的触发次数与冷却剩余——用来解释「为什么这一句被触发」。":
      "Trigger counts and remaining cooldown per entry — this answers “why was that line injected”.",
    "这一局没有世界书条目": "This game has no lorebook entries",
    "大事记": "Milestones",
    "暂无": "None yet",
    "上下文台账": "Context ledger",
    "宿主用 context_remember 记下的线索/承诺/事实。互动对话的\"该记住什么\"在这里可核对。":
      "Clues, promises and facts recorded with context_remember — this is what the AI is supposed to remember.",
    "存档库": "Save library",
    "面板只读：这里列出存档与进度，切换/新建请让宿主调用 session_switch / session_new。":
      "Read-only: this lists saves and progress. Ask the host to call session_switch / session_new.",
    "面板只读：状态文件一变，本页自动刷新，不会改动对局。":
      "Read-only: the page refreshes when the state file changes and never alters the game.",

    /* dialogs */
    "角色": "Character",
    "事件": "Event",

    /* guide */
    "第一次来？这块是": "First time here? This is the",
    "只读主舞台": "read-only stage",
    "——你玩你的，它跟着变：左侧是你的角色/资源与这一局的玩法， 中间是叙事、判定记录与编年史，右侧是在场角色与场景。按":
      " — you play elsewhere and it follows along: your character and resources on the left, narration and checks in the middle, who is present on the right. Press",
    "看术语与读图说明。": " for terms and how to read the charts.",

    /* help */
    "帮助 · 读这块面板": "Help · reading this panel",
    "这是什么": "What this is",
    "一局由规则引擎结算的文字互动游戏，这块面板是它的":
      "A text game resolved by a rule engine. This panel is its",
    "实况主舞台—— 显示的是状态文件里真实的结果。你（玩家）和对局助手在别处行动，面板只跟着变， 不会改对局，也不会替你掷骰子。":
      " live stage — it shows what is actually in the state file. You and the host act elsewhere; the panel only follows along. It never alters the game and never rolls dice for you.",
    "术语表": "Glossary",
    "引擎概念的人话版": "engine concepts in plain words",
    "气血 / 内力": "HP / Power",
    "生命与可消耗的爆发资源。气血低于三成会亮起\"气血吃紧\"。":
      "Health and a consumable burst resource. Below 30% HP the panel shows “HP low”.",
    "钱财": "Coin",
    "本世界的货币（玄晶/灵石/信用点…由设定决定）。买入会增加，卖出会回归。":
      "The world's currency (crystals, spirit stones, credits… set by the bundle). Buying raises it, selling brings it back.",
    "心流（flow）": "Flow",
    "战斗难度的舒适度：赢得太容易会\"无聊\"，输太多会\"焦虑\"，正好在挑战区才叫心流。":
      "How comfortable the difficulty is: winning too easily is boredom, losing too often is anxiety, and only the challenge band is flow.",
    "世界相位（Panarchy）": "World phase (Panarchy)",
    "世界所处的阶段：增长 / 保护 / 崩溃释放 / 重组。大事件的烈度跟着它走。":
      "Which stage the world is in: growth / conservation / release / reorganisation. The severity of big events follows it.",
    "你做过的\"业\"（杀人、偷窃…）累积的债。债越重，突破成功率被压得越低。":
      "Debt accumulated from what you did (killing, stealing…). The heavier the debt, the harder breakthroughs become.",
    "修行阶段（stage）": "Progression stage",
    "本次突破的次数进度。到上限后不再增长——该换更强的对手或更远的世界了。":
      "How many breakthroughs this run has. It stops at the cap — time for tougher opponents or a further world.",
    "物价指数": "Price index",
    "全市场\"当前价 ÷ 基准价\"的均值。1.0 是正常，越低越适合囤货。":
      "Mean of current ÷ base price across the market. 1.0 is normal; lower is a good time to stock up.",
    "心意（亲密 / 敬重）": "Regard (affinity / respect)",
    "人物关系两维：喜欢你和怕你/服你，是两码事。":
      "Relationships have two axes: liking you and fearing or deferring to you are different things.",
    "去过的地方、见过的人、经手的物、触发过的设定——你自己不用记。":
      "Places visited, people met, items handled, entries triggered — you do not have to remember any of it.",
    "各方存量会随回合自行消长；传闻热度越高，越可能引来是非。你不用管它，它也会动。":
      "Faction stock rises and falls on its own each turn; the hotter a rumour, the likelier trouble. You need not touch it — it moves anyway.",
    "这一回合的正文": "This turn's prose",
    "中间那段字是你这一步的叙事正文；它由宿主写进存档，换设备打开也是同一段。":
      "The text in the middle is the narration for your action. The host wrote it into the save, so it reads the same on any device.",
    "图表怎么读": "How to read the charts",
    "：气血/内力按百分比看左轴，钱财看右轴（虚线）。陡降常是打架与突破的代价。":
      ": HP and power read on the left axis as percentages, coin on the right (dashed). Sharp drops are usually fights and breakthroughs.",
    "：柱是未清业债，线是人情均值。杀人偷窃柱会跳，帮人还债会回落。":
      ": bars are unsettled karma, the line is mean relation. Killing and stealing push bars up; helping and repaying bring them down.",
    "：贴着基准线 1.0 走动；明显低于基准＝本地有折价货。":
      ": hugs the 1.0 baseline; clearly below means bargains here.",
    "：最近事件按危急/警示/顺遂/寻常分档，看得出这段是太平还是多事。":
      ": recent events banded as critical / warning / good / ordinary — tells you whether this stretch is calm or eventful.",
    "键盘": "Keyboard",
    "打开/关闭本帮助；": "opens and closes this help;",
    "关闭任何弹窗（焦点会回到你原来待的控件）。":
      "closes any dialog and returns focus to where you were.",
    "命令面板（图鉴 / 市场 / 导出 / 分享模式…），↑↓ 选择、Enter 执行。":
      "opens the command palette (codex / market / export / share mode…); ↑↓ to choose, Enter to run.",
    "在控件间移动；抽屉与按钮都可用": "moves between controls; drawers and buttons open with",
    "展开。": ".",
    "顶栏「动效：开/关」可暂停所有过渡动画（系统级\"减少动态效果\"也会自动生效）。":
      "The “Motion” button in the top bar pauses every transition (the system-level reduced-motion setting also applies).",
    "数据与隐私": "Data and privacy",
    "状态文件：": "State file: ",
    "（对局的唯一权威，一切数值以它为准）":
      " (the single authority for this run — every number comes from it)",
    "趋势侧写：": "Trend sidecar: ",
    "（面板自己的采样账本，删了只丢曲线，不伤对局）":
      " (the panel's own sampling log; deleting it only loses the charts)",
    "行动队列：你在下方输入的行动会写进同目录的收件箱，由对局助手取走结算——":
      "Action queue: what you type below is written to an inbox beside the save and drained by the host —",
    "面板本身从不改对局状态": "the panel itself never alters game state",
    "面板只监听本机": "The panel listens on",
    "，不向任何外部服务发送数据。": " only and sends nothing to any external service.",
    "皮肤与品牌": "Skin and brand",
    "换世界就换样子": "change the world, change the look",
    "当前皮肤：": "Current skin: ",
    "。皮肤由设定包 /": ". Skins come from the setting bundle or",
    "字段决定（": "'s ui field (core:",
    "，可加": ", plus",
    "主色与": "accent and",
    "风格文案）。换世界无需改代码，面板自动适配。":
      "). Swapping worlds needs no code change; the panel adapts.",
    "输入命令：图鉴 / 市场 / 大事 / 帮助 / 导出 / 分享 / 跳到最新 / 主题":
      "Type a command: codex / market / milestones / help / export / share / jump / theme",
    "↑↓ 选择 · Enter 执行 · Esc 关闭": "↑↓ select · Enter run · Esc close",
    "写下这一步想做的事（Enter 排队，Shift+Enter 换行）":
      "Describe what you want to do (Enter queues, Shift+Enter newline)",
    "指挥官在对话里取走": "the host drains it in chat",
    "搜索事件（如：突破 / 柳寒衣）": "Search events (e.g. breakthrough / a name)",
    "搜索剧情 / 归档（如：灯塔 / 沈伯）": "Search story / archive (e.g. lighthouse / a name)",
    "队列": "Queue",
    "目录：": "Directory: ",
    "备注": "Note",
    "状态": "State",
    "关于": "About",
    "事实": "Fact",
    "承诺": "Promise",
    "线索": "Clue",
    "物品": "Item",
    "价": "Price",
    "基准": "Base",
    "库存": "Stock",
    "地点": "Places",
    "人物": "People",
    "规则": "Rules",
    "角色扮演": "Role-play",
    "叙事": "Narration",
    "口吻": "Voice",
    "性情": "Temperament",
    "成功": "Success",
    "部分成功": "Partial success",
    "大成功": "Great success",
    "顺遂": "Smooth",
    "警示": "Warning",
    "危急": "Critical",
    "寻常": "Ordinary",
    "市易": "Trade",
    "精进": "Growth",
    "初探": "Discovery",
    "焦虑": "Anxiety",
    "无聊": "Boredom",
    "我": "Me",
    "记": "M",
    "无属性": "No attributes",
    "无关键词": "No keys",
    "未触发": "Never fired",
    "尚未演化": "Not evolved yet",
    "还没开始演化": "Has not started evolving",
    "推进几个回合后，势力存量会自己动起来":
      "Faction stock starts moving after a few turns",
    "推进回合后世界开始演化": "Advance a turn and the world starts evolving",
    "（无势力）": "(no factions)",
    "（更早的在归档）": "(earlier ones are archived)",
    "（本地）": " (local)",
    "（常驻）": "(always on)",
    "（损坏）": "(corrupt)",
    "（已到上限）": "(at cap)",
    "（尚未开局）": "(not started)",
    "（还没有）": "(none)",
    "还没有正文": "No prose yet",
    "这一类暂时没有事件": "No events of this kind yet",
    "这一局没有配置事业线": "No questlines configured in this game",
    "本局无失败条件": "No failure condition in this game",
    "已到修行上限": "At the progression cap",
    "已完成": "Done",
    "已失败": "Failed",
    "网络错误": "Network error",
    "状态不可读": "State unreadable",
    "本地有折价货": "Bargains here",
    "正在检索归档…": "Searching the archive…",
    "（几乎恒定 ": "(nearly constant ",
    "（恒定 ": "(constant ",
    "气血偏低": "HP low",
    "已解锁 ": "Unlocked ",
    "触发 ": "Fired ",
    "保留 ": "Sticky ",
    "冷却 ": "Cooldown ",
    "声望": "Reputation",
    "成就": "Achievement",
    "成长": "Progression",
    "时间": "Time",
    "掉落": "Loot",
    "制造": "Craft",
    "自定义": "Custom",
    "经营": "Management",
    "生存": "Survival",
    "调查": "Investigation",
    "桌游": "Tabletop",
    "自由推进": "Freeform",
    "选项推进": "Choice",
    "地点与命令": "MUD",
    "声明→判定→后果": "Declare → resolve → consequence",
    "开发/增长": "Growth",
    "保护/守恒": "Conservation",
    "崩溃/释放": "Release",
    "重组/革新": "Reorganisation",
    "守成": "Conserve",
    "求变": "Explore",
    "丹药": "Pill",
    "药品": "Medicine",
    "Panarchy 适应性循环阶段": "Panarchy adaptive-cycle phase",
    "大事记：会被 recap 与回捞记住的事件":
      "Milestone: remembered by recap and recall",
    "点击查看事件详情": "Click to see event details",
    "图表库未加载（离线资产 assets/echarts.min.js 缺失或被拦截）——数据仍在上方时间线与 HUD 中。":
      "Chart library not loaded (offline asset assets/echarts.min.js missing or blocked) — the data is still in the timeline and HUD above.",
    "（还没有值得画的关系——去认识几个人）":
      "(Nothing worth drawing yet — go meet someone)",
    "（还没记录任何地点——用 travel 走动会记进图鉴）":
      "(No places recorded yet — travel around and they enter the codex)",
    "存档库为空——用 session_new 新建一局（存档会集中在这个目录）":
      "No saves yet — call session_new to start one (saves live in one directory)",
    "台账为空——宿主可用 context_remember 记线索与承诺":
      "Ledger is empty — the host can record clues and promises with context_remember",
    "体系动作由宿主执行（system_run）：时间推进、掉落、制造、声望、成就、成长、自定义动作。":
      "Subsystem actions run in the host (system_run): time, loot, craft, reputation, achievement, progression, custom.",
    "守护": "Guard",
    "与风向": "and winds",
    "长局纪律（宿主 AI 的规矩）": "Long-game discipline (rules for the host AI)",
    "事件链编排规则（小事→线索→大事件）": "Event-chain rules (small → clue → major)",
    "三线主线与长期目标（长局方向）": "Three main lines and long-term goals",
    "修炼阶梯（十阶）": "Progression ladder (ten tiers)",
    "丹药与天材地宝": "Pills and rare materials",
    "修行阶": "Tier",
    "主线 / 长期目标 / 三线 / 长局": "main line / long-term / three lines / long game",
    "事件链 / 伏笔 / 铺垫 / 编排 / 节奏": "event chain / foreshadow / setup / pacing",
    "丹药 / 灵药 / 天材地宝 / 采药": "pills / elixirs / rare materials / gathering",
    "试炼 / 大比 / 排名 / 入学": "trial / contest / ranking / enrolment",
    "追杀 / 悬赏 / 赌斗 / 结仇": "hunt / bounty / wager / feud",
    "采集 / 矿脉 / 药田 / 妖兽材料 / 产出 / 赚钱": "gathering / veins / herb fields / beast parts / output / profit",
    "长局 / 摘要 / 压缩 / 回看 / 上下文": "long game / summary / compression / review / context",
    "重伤退场": "Forced withdrawal"
  };

  /* ── Templates: composed strings. {n} = number, {s} = text ──────────── */
  var EN_TEMPLATES = [
    ["回合 {n}", "Turn {n}"],
    ["更新于 {s}", "Updated {s}"],
    ["第 {n} {s}", "{s} {n}"],
    ["第 {n}", "Step {n}"],
    ["气血 {a}/{b}", "HP {a}/{b}"],
    ["气血 {a}/{b} {s}", "HP {a}/{b} {s}"],
    ["亲密 {a} · 敬重 {b}", "Affinity {a} · Respect {b}"],
    ["亲密 {a} · 敬重 {b} {s}", "Affinity {a} · Respect {b} {s}"],
    ["{s} 亲密{a} / 敬重{b}", "{s} — affinity {a} / respect {b}"],
    ["{n} 人", "{n} present"],
    ["{n} 种", "{n} kinds"],
    ["{n} 段关系", "{n} bonds"],
    ["别处 {n} 人：{s}", "Elsewhere ({n}): {s}"],
    ["展开其余 {n} {s}（共 {t}）", "Show the other {n} {s} ({t} total)"],
    ["没有匹配「{s}」的事件", "No events match “{s}”"],
    ["正文里没有匹配「{s}」的段落", "No prose matches “{s}”"],
    ["归档命中 {n} 条（扫描 {m} 条）", "{n} archive hits (scanned {m})"],
    ["大事记 {n} · 归档 {m}", "Milestones {n} · archived {m}"],
    ["摘要 {n} 条 · 归档 {m} 条", "{n} summaries · {m} archived"],
    ["设定词条 {n} 条", "{n} entries"],
    ["{n} 条事业线，还没到浮现的时候", "{n} questlines, none surfaced yet"],
    ["已浮现 {n} / 共 {m}", "{n} of {m} surfaced"],
    ["这一局有 {n} 条事业线", "This game has {n} questlines"],
    ["期限：第 {n} 回合", "Deadline: turn {n}"],
    ["{n} 回合 · {s}", "Turn {n} · {s}"],
    ["{n} 回合", "{n} turns"],
    ["{n} 天", "{n} days"],
    ["{n} 处", "{n} places"],
    ["{n} 张表", "{n} sheets"],
    ["{n} 套体系", "{n} subsystems"],
    ["{n} 个动作", "{n} actions"],
    ["{n} 个配方", "{n} recipes"],
    ["{n} 格", "{n} slots"],
    ["{n} 字", "{n} chars"],
    ["{n} 次", "{n} times"],
    ["{n} 类", "{n} kinds"],
    ["{n} 行，显示 {m}", "{n} rows, showing {m}"],
    ["（还有 {n} 条）", "({n} more)"],
    ["（共 {n} 条）", "({n} total)"],
    ["第 {n} 阶", "Step {n}"],
    ["相位 {s}", "Phase {s}"],
    ["物价 {s}", "Price {s}"],
    ["队列 {n} 条 · {s}", "Queue {n} · {s}"],
    ["已排队（共 {n} 条）", "Queued ({n} total)"],
    ["实况 · {s}", "Live · {s}"],
    ["当前：{s}", "Current: {s}"],
    ["{s}还没开始演化", "{s} has not started evolving"],
    ["{n} 条未结案 · 共 {m}", "{n} open · {m} total"],
    ["{n} 局 · 回收站 {m}", "{n} saves · trash {m}"],
    ["{n}% 回合为 {s}", "{n}% of turns {s}"],
    ["{s} · 心伤 {n}", "{s} · wounds {n}"],
    ["{s} · 濒死 {n}", "{s} · near-death {n}"],
    ["{s} · 当前", "{s} · current"],
    ["{s} · 大事记", "{s} · milestones"],
    ["业债深重 {s}", "Heavy karma {s}"],
    ["业债缠身 {s}", "Burdened by karma {s}"],
    ["崩解 {s}", "Collapsing {s}"],
    ["查看 {s} 详情", "View {s} details"],
    ["{s} 详情", "{s} details"],
    ["{n} / 共 {m} 段", "{n} of {m} passages"],
    ["{n} · 已触发 {m}", "{n} · fired {m}"],
    ["{s} {n} 次 · 物价 {v}", "{s} {n} times · price {v}"],
    ["{s} {n}%", "{s} {n}%"],
    ["{s} · {n}%", "{s} · {n}%"],
    ["{n} 阶", "Tier {n}"],
    ["{s}（本地）", "{s} (local)"],
    ["可以试试", "Try this"],
    ["推进「{s}」", "advance “{s}”"],
    ["找出同样盯着旧枢台的人", "find whoever else is watching the old altar"],
    ["打听到学宫报名的门槛", "learn the academy's entry requirement"],
    ["凑齐报名所需的路费", "gather the travel fare"],
    ["找地方疗伤，或换条安全的路", "heal up, or take a safer route"],
    ["还一笔业债，或做件好事抵掉", "settle some karma, or do a good turn"],
    ["看看本地市价，有 {n} 样低于基准", "check the market: {n} items below baseline"],
    ["换个地方，或推进一个没试过的交互", "go somewhere else, or try an untried interaction"],
    ["描述你想做的事，或先去别处看看", "describe what you want to do, or look around"],
    ["气血只剩 {n}%", "only {n}% HP left"],
    ["未清业债 {s}，会压突破成功率", "unsettled karma {s} lowers breakthrough odds"],
    ["低价买入，离开后可能卖得更高", "buy low, it may sell higher elsewhere"],
    ["同一状态已经重复出现", "the same state keeps recurring"],
    ["自由推进：引擎会结算，结果由规则决定", "freeform: the engine settles it, rules decide"],
    ["心流 ({n})", "Flow ({n})"],
    ["{s}（{n}）", "{s} ({n})"],
    ["元力", "power"],
    ["{n} · 已触发 {m}", "{n} · fired {m}"],
    ["K · 保护/守恒", "K · Conservation"],
    ["势力", "Factions"],
    ["当前焦点：", "Focus: "],
    ["基调 / 文风", "tone / style"],
    ["玄器与枢宝", "arcane gear and relics"],
    ["玄晶与市价", "crystals and prices"],
    ["境 突破受挫", "Breakthrough set back"],
    ["学宫开山之年", "The academy opens"],
    ["报名", "Sign up"],
    ["打听到学宫报名的门槛", "learn the entry bar"],
    ["情 人情", "S Social"],
    ["势", "F"],
    ["交", "T"],
    ["路", "R"],
    ["阶段 {n}", "Stage {n}"],
    ["阶段", "stage"],
    ["境界", "tier"],
    ["阶", "tier"],
    ["所在", "at"],
    ["名号", "name"],
    ["境界 {n}", "Tier {n}"],
    ["阶 {n}", "Tier {n}"],
    ["元力 / 修行 / 修炼", "power / cultivation / training"],
    ["元力总纲", "Power overview"],
    ["事件范式 · 秘境与名额", "Pattern · secret realm and quota"],
    ["事件范式 · 追杀与赌斗", "Pattern · pursuit and wager"],
    ["凑齐报名所需的路费", "gather the travel fare"],
    ["势 事件", "F Event"],
    ["第{n}回合·{s}", "Turn {n} · {s}"],
    ["纪元:第{n}次大崩解", "Era: collapse #{n}"],
    ["谣言:{s}", "Rumour: {s}"],
    ["路 行旅", "R Travel"],
    ["交 交易", "T Trade"],
    ["{n} 条 · 已触发 {m}", "{n} entries · {m} fired"],
    ["{s} 亲密{a} / 敬重{b}", "{s} — affinity {a} / respect {b}"],
    ["亲密 {a} · 敬重 {b}", "Affinity {a} · Respect {b}"],
    ["阶 {n}", "Tier {n}"],
    ["稳定但也僵化，创新受抑", "Stable but rigid; innovation is suppressed"],
    ["秘境 / 名额 / 令牌 / 开山", "secret realm / quota / token / founding"],
    ["突破与渡厄（事件范式：突破怎么写）", "Breakthroughs and tribulation (how to write one)"],
    ["谁在盯着", "Who is watching"],
    ["危急 · {n}%", "Critical · {n}%"],
    ["警示 · {n}%", "Warning · {n}%"],
    ["顺遂 · {n}%", "Smooth · {n}%"],
    ["寻常 · {n}%", "Ordinary · {n}%"],
    ["势力:{s}", "Faction: {s}"],
    ["保护/守恒", "Conservation"],
    ["开发/增长", "Growth"],
    ["崩溃/释放", "Release"],
    ["重组/革新", "Reorganisation"],
    ["魅力 {n}", "Charisma {n}"],
    ["体质 {n}", "Constitution {n}"],
    ["力量 {n}", "Strength {n}"],
    ["敏捷 {n}", "Agility {n}"],
    ["智力 {n}", "Intellect {n}"],
    ["物力", "Resources"],
    ["气力", "Vigour"],
    ["悟性", "Insight"],
    ["根骨", "Aptitude"],
    ["声望 {n}", "Reputation {n}"],
    ["修为", "Cultivation"],
    ["亲密 {a} · 敬重 {b}", "Affinity {a} · Respect {b}"],
    ["别处 {n} 人：{s}", "Elsewhere ({n}): {s}"],
    ["势力关系 / 格局 / 关系网 / 暗线 / 交错", "faction relations / landscape / network / subplot / interplay"],
    ["势力关系网（错综复杂的现状）", "Faction network (the tangled present)"],
    ["势力格局（学宫/世家/宗门/商行/秩序）", "Faction landscape (academy / clan / sect / guild / order)"],
    ["三阶玄器·断水刀", "Tier-3 arcane blade"],
    ["《引元诀》残页", "torn page"],
    ["「天地异象」在街巷间传开", "“Strange omen” spreads through the streets"]
  ];

  var STORAGE_KEY = "wg-panel-lang";
  var current = "en";
  var applied = false;

  /* Build a matcher for each template: literal text with placeholders. */
  function templateToRegex(tpl) {
    var parts = tpl.split(/(\{\w+\})/);
    var names = [];
    var src = parts.map(function (p) {
      var m = p.match(/^\{(\w+)\}$/);
      if (m) { names.push(m[1]); return "(.+?)"; }
      return p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }).join("");
    return { re: new RegExp("^" + src + "$"), names: names };
  }

  var COMPILED = EN_TEMPLATES.map(function (pair) {
    var c = templateToRegex(pair[0]);
    return { re: c.re, names: c.names, out: pair[1] };
  });

  /**
   * Translate one text run.
   *
   * Captured groups are translated recursively before substitution: without that,
   * a template like "{s}还没开始演化" yields "势力 has not started evolving" —
   * half English, half Chinese, which is worse than leaving it alone.
   *
   * `depth` guards the recursion. If the composed result still carries Chinese,
   * the template was the wrong match and we fall through to the next candidate.
   */
  var PLACEHOLDER_SENTINEL = "\u0000";

  /**
   * Translate one text run.
   *
   * Three subtleties this handles:
   *
   * 1. Inline markup splits sentences into several text nodes ("第一次来？这块是"
   *    + <b>只读主舞台</b> + "——你玩你的…"), so each fragment must be a key.
   * 2. Authored text wraps across lines; keys are matched on whitespace-collapsed
   *    text so a hard line break does not defeat the lookup.
   * 3. A captured group may legitimately be game content (a character name).
   *    Rejecting any result that still contains Chinese would then throw away a
   *    perfectly good template. Instead we rebuild the output with captured
   *    values replaced by a sentinel and reject only if *the template's own*
   *    literal text still carries Chinese.
   *
   * `depth` guards recursion.
   */
  function translateText(text, depth) {
    var raw = text;
    if (!raw || !/[\u4e00-\u9fff]/.test(raw)) return null;
    if ((depth || 0) > 3) return null;

    var lead = raw.match(/^\s*/)[0];
    var trail = raw.match(/\s*$/)[0];
    var core = raw.trim();
    if (!core) return null;
    var flat = core.replace(/\s+/g, " ");

    if (Object.prototype.hasOwnProperty.call(EN, core)) {
      return lead + EN[core] + trail;
    }
    if (Object.prototype.hasOwnProperty.call(EN, flat)) {
      return lead + EN[flat] + trail;
    }

    for (var i = 0; i < COMPILED.length; i++) {
      var c = COMPILED[i];
      var m = core.match(c.re) || flat.match(c.re);
      if (!m) continue;

      var out = c.out;
      var skeleton = c.out;
      for (var j = 0; j < c.names.length; j++) {
        var inner = m[j + 1];
        var translated = translateText(inner, (depth || 0) + 1);
        out = out.replace("{" + c.names[j] + "}", translated !== null ? translated : inner);
        skeleton = skeleton.replace("{" + c.names[j] + "}", PLACEHOLDER_SENTINEL);
      }
      // Only the template's own literal text matters here.
      if (/[\u4e00-\u9fff]/.test(skeleton)) continue;
      // Composed results start with a term ("tier 7"); capitalise so it reads
      // as a label rather than mid-sentence text.
      out = out.replace(/^([a-z])/, function (ch) { return ch.toUpperCase(); });
      return lead + out + trail;
    }
    return null;
  }

  var ATTRS = ["placeholder", "title", "aria-label", "alt"];

  /* Remember originals so switching back is lossless. */
  function remember(node, kind, key, original) {
    var store = node.__wgI18n || (node.__wgI18n = {});
    if (!store[kind]) store[kind] = {};
    if (!(key in store[kind])) store[kind][key] = original;
  }

  function applyToNode(node) {
    if (node.nodeType === 3) {
      var parent = node.parentNode;
      if (!parent) return;
      var tag = (parent.nodeName || "").toLowerCase();
      if (tag === "script" || tag === "style" || tag === "code" || tag === "pre") return;
      remember(parent, "text", node.__wgIdx || (node.__wgIdx = String(Math.random())), node.nodeValue);
      var next = translateText(node.nodeValue);
      if (next !== null) node.nodeValue = next;
      return;
    }
    if (node.nodeType !== 1) return;
    ATTRS.forEach(function (attr) {
      if (!node.hasAttribute || !node.hasAttribute(attr)) return;
      var val = node.getAttribute(attr);
      remember(node, "attr", attr, val);
      var next = translateText(val);
      if (next !== null) node.setAttribute(attr, next);
    });
  }

  function walk(root) {
    if (!root) return;
    if (root.nodeType === 3) { applyToNode(root); return; }
    if (root.nodeType !== 1 && root.nodeType !== 9) return;
    applyToNode(root);
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, null);
    var n = walker.nextNode();
    while (n) { applyToNode(n); n = walker.nextNode(); }
  }

  function restore(root) {
    if (!root) return;
    var scope = root.nodeType === 1 ? root : document.body;
    var nodes = [scope].concat(Array.prototype.slice.call(scope.querySelectorAll("*")));
    nodes.forEach(function (el) {
      var store = el.__wgI18n;
      if (!store) return;
      if (store.attr) {
        Object.keys(store.attr).forEach(function (a) { el.setAttribute(a, store.attr[a]); });
      }
      if (store.text) {
        Array.prototype.slice.call(el.childNodes).forEach(function (child) {
          if (child.nodeType === 3 && child.__wgIdx && store.text[child.__wgIdx] !== undefined) {
            child.nodeValue = store.text[child.__wgIdx];
          }
        });
      }
    });
  }

  /** Translate the live DOM. Safe to call after every render. */
  function translateDom(root) {
    if (current !== "en") return;
    walk(root || document.body);
    applied = true;
  }

  function detect() {
    var saved = null;
    try { saved = global.localStorage.getItem(STORAGE_KEY); } catch (e) { /* storage blocked */ }
    if (saved === "zh" || saved === "en") return saved;
    return "en";
  }

  function setLang(next) {
    if (next !== "zh" && next !== "en") return;
    current = next;
    try { global.localStorage.setItem(STORAGE_KEY, next); } catch (e) { /* storage blocked */ }
    document.documentElement.setAttribute("lang", next === "zh" ? "zh-CN" : "en");
    document.documentElement.setAttribute("data-panel-lang", next);
    if (next === "zh") restore(document.body);
    else translateDom(document.body);
    var btns = document.querySelectorAll("[data-set-panel-lang]");
    Array.prototype.forEach.call(btns, function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-set-panel-lang") === next ? "true" : "false");
    });
  }

  function lang() { return current; }
  function has(key) { return Object.prototype.hasOwnProperty.call(EN, key); }
  function keys() { return Object.keys(EN); }

  global.PanelI18n = {
    translateDom: translateDom,
    setLang: setLang,
    lang: lang,
    detect: detect,
    has: has,
    keys: keys,
    translateText: translateText,
    templateCount: function () { return COMPILED.length; }
  };
})(window);
