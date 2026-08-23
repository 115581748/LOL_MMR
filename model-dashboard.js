(() => {
  const core = window.MODEL_DATA || { rows: [], meta: {} };
  const extras = window.MODEL_EXTRAS || { numericRows: [], profiles: {}, items: {}, spells: {}, runes: {}, runeStyles: {}, meta: {} };
  const manifest = window.MODEL_MANIFEST || { parameters: {} };
  const modelParameters = { ...(core.meta?.model_parameters || {}), ...(extras.meta?.modelParameters || {}), ...(manifest.parameters?.model || {}) };
  const dashboardParameters = { ...(core.meta?.dashboard_parameters || {}), ...(extras.meta?.dashboardParameters || {}), ...(manifest.parameters?.dashboard || {}) };
  const lateStartMinute = Number(manifest.parameters?.conditional_model?.late_phase_start_minute || 25);
  const ui = {
    metricInitialLimit: Number(dashboardParameters.metric_initial_limit || 12),
    metricLoadMore: Number(dashboardParameters.metric_load_more || 24),
    tableInitialLimit: Number(dashboardParameters.table_initial_limit || 80),
    tableLoadMore: Number(dashboardParameters.table_load_more || 80),
    coverageLimit: Number(dashboardParameters.coverage_limit || 20),
    itemSlotLimit: Number(dashboardParameters.item_slot_limit || 4),
    confidenceThresholds: dashboardParameters.confidence_thresholds || [
      { min_samples: 50, label: "较高", css_class: "good", bar_percent: 100 },
      { min_samples: 30, label: "中等", css_class: "medium", bar_percent: 72 },
      { min_samples: 20, label: "初步", css_class: "medium", bar_percent: 52 },
      { min_samples: 0, label: "探索性", css_class: "", bar_percent: 30 },
    ],
  };
  const confidenceNarrativeMin = Number(
    ui.confidenceThresholds.find((entry) => entry.label === "中等")?.min_samples || 30
  );
  const data = [...(core.rows || []), ...(extras.numericRows || [])];
  const $ = (id) => document.getElementById(id);
  const roles = { TOP: "上路", JUNGLE: "打野", MIDDLE: "中路", BOTTOM: "下路", UTILITY: "辅助" };

  const names = {
    early_gold_15: ["15 分钟金币", "Gold @ 15"], level_at_15: ["15 分钟等级", "Champion level @ 15"], early_xp_15: ["15 分钟经验（原始）", "Raw XP @ 15"], early_cs_15: ["15 分钟补刀", "CS @ 15"],
    early_kills: ["前期击杀", "Kills 0–15"], early_deaths: ["前期死亡", "Deaths 0–15"], early_assists: ["前期助攻", "Assists 0–15"],
    mid_gold_gain: ["中期获得金币", `Gold 15–${lateStartMinute}`], mid_cs_gain: ["中期补刀", `CS 15–${lateStartMinute}`], mid_champion_damage: ["中期英雄伤害", `Champion damage 15–${lateStartMinute}`],
    mid_kills: ["中期击杀", `Kills 15–${lateStartMinute}`], mid_deaths: ["中期死亡", `Deaths 15–${lateStartMinute}`], mid_assists: ["中期助攻", `Assists 15–${lateStartMinute}`],
    mid_team_turrets: ["中期团队推塔", `Team turrets 15–${lateStartMinute}`], mid_team_dragons: ["中期团队控龙", `Team dragons 15–${lateStartMinute}`],
    late_champion_damage_per_min: ["后期每分钟英雄伤害", `Champion damage / min after ${lateStartMinute}`], late_damage_taken_per_min: ["后期每分钟承伤", `Damage taken / min after ${lateStartMinute}`],
    late_champion_damage: ["后期累计英雄伤害（原始）", `Raw champion damage ${lateStartMinute}+`], late_damage_taken: ["后期累计承伤（原始）", `Raw damage taken ${lateStartMinute}+`], late_kills: ["后期击杀", `Kills ${lateStartMinute}+`],
    late_deaths: ["后期死亡", `Deaths ${lateStartMinute}+`], late_assists: ["后期助攻", `Assists ${lateStartMinute}+`], late_teamfights: ["后期团战数", "Detected teamfights"],
    late_teamfight_participations: ["后期团战参与", "Teamfight participation"], late_first_target_deaths: ["团战首个阵亡", "First-target deaths"],
    cs_per_min: ["每分钟补刀", "CS / min"], damage_per_min: ["每分钟英雄伤害", "Damage / min"], vision_per_min: ["每分钟视野分", "Vision / min"],
    challenge_killParticipation: ["击杀参与率", "Kill participation"], challenge_goldPerMinute: ["每分钟金币", "Gold / min"],
    challenge_damageTakenOnTeamPercentage: ["团队承伤占比", "Damage taken share"], challenge_teamDamagePercentage: ["团队伤害占比", "Team damage share"],
    challenge_laneMinionsFirst10Minutes: ["10 分钟线上补刀", "Lane CS @ 10"], challenge_maxCsAdvantageOnLaneOpponent: ["最大对位补刀优势", "Max lane CS advantage"],
    dragon_windows: ["全场小龙窗口", "Dragon objective windows"], team_dragons_timeline: ["己方控龙数", "Team dragon secures"], enemy_dragons_timeline: ["对方控龙数", "Enemy dragon secures"],
    dragon_fight_windows: ["发生交战的龙窗口", "Contested dragon windows"], dragon_fight_participations: ["个人龙团参与", "Dragon-fight participations"],
    dragon_fight_kills: ["龙团击杀", "Kills near dragon"], dragon_fight_deaths: ["龙团死亡", "Deaths near dragon"], dragon_fight_assists: ["龙团助攻", "Assists near dragon"],
    dragon_fight_team_kills: ["龙团己方击杀", "Team kills near dragon"], dragon_fight_team_deaths: ["龙团己方死亡", "Team deaths near dragon"],
    dragon_secures_while_participating: ["参团且控下小龙", "Secures while involved"], dragon_losses_while_participating: ["参团但丢龙", "Losses while involved"],
    dragon_secure_rate_when_present: ["龙团到场控龙率", "Secure rate when present"], dragon_fight_kill_participation: ["龙团击杀参与率", "Dragon-fight KP"],
    dragon_fight_survival_rate: ["龙团存活率", "Dragon-fight survival"], dragon_contest_kills_per_window: ["每次龙团总击杀", "Kills per contested window"],
    first_dragon_minute: ["第一条龙时间", "First dragon minute"], teamfights_total: ["全场团战数", "Detected teamfights"],
    teamfight_participations_total: ["全场团战参与", "Teamfight participations"], teamfight_participation_rate: ["全场团战参与率", "Teamfight participation rate"],
    teamfight_kills_total: ["团战击杀", "Teamfight kills"], teamfight_deaths_total: ["团战死亡", "Teamfight deaths"],
    teamfight_assists_total: ["团战助攻", "Teamfight assists"], teamfight_first_target_deaths_total: ["全场团战首个阵亡", "First-target deaths"],
  };

  const phaseMetrics = {
    early: ["early_gold_15", "level_at_15", "early_cs_15", "early_kills", "early_deaths", "early_assists", "challenge_laneMinionsFirst10Minutes", "challenge_maxCsAdvantageOnLaneOpponent"],
    mid: ["mid_gold_gain", "mid_cs_gain", "mid_champion_damage", "mid_kills", "mid_deaths", "mid_assists", "mid_team_turrets", "mid_team_dragons"],
    late: ["late_champion_damage_per_min", "late_damage_taken_per_min", "late_kills", "late_deaths", "late_assists", "late_teamfights", "late_teamfight_participations", "late_first_target_deaths"],
    dragon: ["dragon_windows", "team_dragons_timeline", "enemy_dragons_timeline", "dragon_fight_windows", "dragon_fight_participations", "dragon_secure_rate_when_present", "dragon_fight_kill_participation", "dragon_fight_survival_rate", "dragon_fight_kills", "dragon_fight_deaths", "dragon_fight_assists", "first_dragon_minute"],
    global: ["cs_per_min", "damage_per_min", "vision_per_min", "challenge_killParticipation", "challenge_goldPerMinute", "challenge_damageTakenOnTeamPercentage", "challenge_teamDamagePercentage", "teamfights_total", "teamfight_participation_rate"],
  };
  const phaseCopy = {
    early: ["EARLY GAME", "前 15 分钟行为基准"], mid: ["MID GAME", `15–${lateStartMinute} 分钟行为基准`], late: ["LATE GAME", `${lateStartMinute} 分钟后行为基准`],
    dragon: ["DRAGON FIGHT WINDOWS", "龙团与目标窗口"], global: ["FULL MATCH", "全局效率与贡献"], all: ["ALL NUMERIC FIELDS", "全部可用数值指标"],
  };

  const wordMap = {
    total: "总", damage: "伤害", dealt: "造成", taken: "承受", champion: "英雄", champions: "英雄", kills: "击杀", deaths: "死亡", assists: "助攻",
    gold: "金币", earned: "获得", spent: "花费", vision: "视野", wards: "守卫", ward: "守卫", placed: "放置", killed: "清除", turret: "防御塔", turrets: "防御塔",
    minions: "小兵", jungle: "野区", enemy: "敌方", ally: "己方", team: "团队", time: "时间", first: "首次", per: "每", minute: "分钟", control: "控制",
    heal: "治疗", healing: "治疗", shield: "护盾", objectives: "目标", dragon: "小龙", baron: "男爵", nexus: "水晶", inhibitor: "高地", pings: "信号", score: "评分",
  };
  const categoricalIdPattern = /^end_(item[0-6]|playerAugment\d+|championTransform|roleBoundItem|playerSubteamId)$/;
  const groups = new Map();
  data.forEach((row) => {
    const key = `${row.c}|${row.r}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  });
  const champions = [...new Set(data.map((row) => row.c))].sort();
  let phase = "early";
  let limit = ui.metricInitialLimit;
  let allLimit = ui.tableInitialLimit;

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
  }

  function humanize(metric) {
    const cleaned = metric.replace(/^(end_|challenge_)/, "").replace(/([a-z0-9])([A-Z])/g, "$1 $2").replaceAll("_", " ");
    return cleaned.split(/\s+/).map((token) => wordMap[token.toLowerCase()] || token).join(" ");
  }

  function label(metric) {
    if (names[metric]) return names[metric];
    const source = metric.startsWith("challenge_") ? "Riot Challenges" : metric.startsWith("end_") ? "Match-v5 end field" : metric.startsWith("dragon_") || metric.startsWith("teamfight") ? "Timeline derived" : "Match-v5 metric";
    return [humanize(metric), source];
  }

  function isRate(metric) { return /(percentage|_rate|share)/i.test(metric) || metric === "challenge_killParticipation" || metric === "dragon_fight_kill_participation"; }
  function fmt(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "—";
    const absolute = Math.abs(number);
    if (absolute >= 1e6) return `${(number / 1e6).toFixed(1)}m`;
    if (absolute >= 1e4) return `${(number / 1e3).toFixed(1)}k`;
    if (absolute >= 1e3) return number.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
    return number.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  }
  function fmtMetric(metric, value) {
    const number = Number(value);
    if (metric === "level_at_15" && Number.isFinite(number)) return `Lv.${number.toLocaleString("zh-CN", { maximumFractionDigits: 1 })}`;
    if (isRate(metric) && Number.isFinite(number) && Math.abs(number) <= 1.5) return `${(number * 100).toFixed(1)}%`;
    if (metric === "first_dragon_minute" && Number.isFinite(number)) return `${number.toFixed(1)} 分`;
    return fmt(number);
  }
  function grade(n) {
    const ordered = [...ui.confidenceThresholds].sort((a, b) => Number(b.min_samples) - Number(a.min_samples));
    const match = ordered.find((entry) => n >= Number(entry.min_samples)) || ordered[ordered.length - 1];
    return [match.label, match.css_class, Number(match.bar_percent)];
  }
  function pct(value, min, max) { return Math.max(0, Math.min(100, (value - min) / (max - min || 1) * 100)); }
  function isZero(row) { return [row.p25, row.median, row.mean, row.p75].every((value) => Number(value) === 0); }

  function metricCategory(metric) {
    const lower = metric.toLowerCase();
    if (lower.startsWith("dragon_") || lower.startsWith("teamfight") || lower.includes("dragon") || lower.includes("baron") || lower.includes("rift_herald") || lower.includes("riftHerald".toLowerCase())) return "史诗资源与团战";
    if (/^(early|mid|late)_/.test(metric)) return "阶段表现";
    if (/damage|physical|magic|true|critical|mitigated/.test(lower)) return "输出与承伤";
    if (/kill|death|assist|takedown|kda|spree|multi|ace|bounty/.test(lower)) return "击杀与生存";
    if (/gold|minute|minion|jungle|experience|level|consumable|item|cs/.test(lower)) return "经济与发育";
    if (/vision|ward|ping|unseen|stealth/.test(lower)) return "视野与沟通";
    if (/heal|shield|immobil|control|cc|cleanse|dodge|skillshot/.test(lower)) return "治疗、控制与操作";
    if (/turret|tower|inhibitor|nexus|building|objective|plate/.test(lower)) return "推塔与基地";
    if (metric.startsWith("challenge_")) return "Challenges 其他";
    return "结算与系统";
  }

  function sourceOf(metric) {
    if (metric.startsWith("challenge_")) return "Challenges";
    if (metric.startsWith("end_")) return "Match-v5";
    if (metric.startsWith("dragon_") || metric.startsWith("teamfight")) return "时间线推断";
    return "阶段派生";
  }

  function card(row) {
    const [name, subtitle] = label(row.m);
    const confidence = grade(row.n_clean);
    const min = row.iqr_low;
    const max = row.iqr_high;
    const q1 = pct(row.p25, min, max);
    const q3 = pct(row.p75, min, max);
    const median = pct(row.median, min, max);
    const mean = pct(row.mean, min, max);
    const inputBounds = row.m === "level_at_15" ? 'step="1" min="1" max="18"' : 'step="any"';
    return `<article class="metric-card"><div class="metric-top"><div><h3>${escapeHtml(name)}</h3><p>${escapeHtml(subtitle)}</p></div><span class="sample-grade ${confidence[1]}">${confidence[0]} · n=${row.n_clean}</span></div><div class="numbers"><div><span>P25</span><b>${fmtMetric(row.m, row.p25)}</b></div><div><span>中位数</span><b>${fmtMetric(row.m, row.median)}</b></div><div><span>均值</span><b>${fmtMetric(row.m, row.mean)}</b></div><div><span>P75</span><b>${fmtMetric(row.m, row.p75)}</b></div></div><div class="boxplot"><i class="whisker" style="left:0;width:100%"></i><i class="iqr-box" style="left:${q1}%;width:${Math.max(1, q3 - q1)}%"></i><i class="median-line" style="left:${median}%"></i><i class="mean-dot" style="left:${mean}%"></i></div><div class="compare-row"><label>输入本局值</label><input type="number" ${inputBounds} data-p25="${row.p25}" data-p75="${row.p75}" placeholder="—"><span class="compare-result">与典型区间比较</span></div></article>`;
  }

  function currentKey() { return `${$("championSelect").value}|${$("roleSelect").value}`; }
  function currentRows() { return groups.get(currentKey()) || []; }

  function renderMetrics() {
    let rows = currentRows().filter((row) => !categoricalIdPattern.test(row.m));
    const search = $("metricSearch").value.trim().toLowerCase();
    if (phase !== "all") rows = rows.filter((row) => (phaseMetrics[phase] || []).includes(row.m));
    if (search) rows = rows.filter((row) => `${label(row.m)[0]} ${row.m}`.toLowerCase().includes(search));
    if (phaseMetrics[phase]) rows.sort((a, b) => phaseMetrics[phase].indexOf(a.m) - phaseMetrics[phase].indexOf(b.m));
    else rows.sort((a, b) => metricCategory(a.m).localeCompare(metricCategory(b.m), "zh-CN") || label(a.m)[0].localeCompare(label(b.m)[0], "zh-CN"));
    $("phaseEyebrow").textContent = phaseCopy[phase][0];
    $("phaseTitle").textContent = phaseCopy[phase][1];
    $("visibleMetricCount").textContent = `显示 ${Math.min(rows.length, limit)} / ${rows.length} 项`;
    $("metricGrid").innerHTML = rows.slice(0, limit).map(card).join("");
    $("emptyState").hidden = rows.length > 0;
    $("loadMore").hidden = rows.length <= limit;
    document.querySelectorAll(".compare-row input").forEach((input) => input.addEventListener("input", () => {
      const result = input.nextElementSibling;
      const value = Number(input.value);
      const low = Number(input.dataset.p25);
      const high = Number(input.dataset.p75);
      result.className = "compare-result";
      if (input.value === "") result.textContent = "与典型区间比较";
      else if (value < low) result.textContent = "低于高分段 P25";
      else if (value > high) result.textContent = "高于高分段 P75";
      else { result.textContent = "位于典型区间"; result.classList.add("typical"); }
    }));
  }

  function itemMarkup(itemId) {
    const item = extras.items?.[String(itemId)] || { name: `物品 ${itemId}`, icon: `${itemId}.png` };
    const version = extras.meta?.itemVersion || "16.13.1";
    const icon = `https://ddragon.leagueoflegends.com/cdn/${version}/img/item/${item.icon}`;
    return `<span class="item-card" title="${escapeHtml(item.name)} · ID ${escapeHtml(itemId)}"><img src="${icon}" alt="" loading="lazy"><span>${escapeHtml(item.name)}</span></span>`;
  }

  function sequenceRows(entries, separator = "→") {
    if (!entries?.length) return `<div class="empty-panel">当前英雄位置没有可用的时间线出装样本。</div>`;
    return entries.map((entry) => `<div class="sequence-row"><div class="item-chain">${entry.ids.map((id, index) => `${index ? `<i class="item-arrow">${separator}</i>` : ""}${itemMarkup(id)}`).join("")}</div><span class="frequency"><b>${(entry.share * 100).toFixed(1)}%</b><small>${entry.n} 局</small></span></div>`).join("");
  }

  function choiceRows(entries, formatter = (value) => value) {
    if (!entries?.length) return `<div class="empty-panel">没有足够样本。</div>`;
    return entries.map((entry) => `<div class="choice-row"><span>${escapeHtml(formatter(entry.value))}</span><b>${(entry.share * 100).toFixed(1)}% · ${entry.n}</b></div>`).join("");
  }

  function tupleChoiceRows(entries, formatter) {
    if (!entries?.length) return `<div class="empty-panel">没有足够样本。</div>`;
    return entries.map((entry) => `<div class="choice-row"><span>${escapeHtml(formatter(entry.ids))}</span><b>${(entry.share * 100).toFixed(1)}% · ${entry.n}</b></div>`).join("");
  }

  function renderEnumerables() {
    const profile = extras.profiles?.[currentKey()];
    const maxN = Math.max(0, ...currentRows().map((row) => row.n_raw));
    $("enumerableCount").textContent = profile ? `${maxN} 个玩家单局` : "无时间线样本";
    $("buildOrderPanel").innerHTML = profile ? `<p class="choice-subhead">核心装备（总价 ≥ ${fmt(modelParameters.core_item_min_gold)}）</p>${sequenceRows(profile.coreBuildOrders)}<p class="choice-subhead">完整结算装备顺序（含未合成组件）</p>${sequenceRows(profile.buildOrders)}` : `<div class="empty-panel">没有足够样本。</div>`;
    $("starterPanel").innerHTML = sequenceRows(profile?.starters, "+");
    $("finalBuildPanel").innerHTML = sequenceRows(profile?.finalBuilds, "+");
    $("summonerPanel").innerHTML = profile ? tupleChoiceRows(profile.summoners, (ids) => ids.map((id) => extras.spells?.[id] || `技能 ${id}`).join(" + ")) : `<div class="empty-panel">没有足够样本。</div>`;
    $("runePanel").innerHTML = profile ? tupleChoiceRows(profile.runes, (ids) => `${extras.runes?.[ids[0]] || `基石 ${ids[0]}`} + ${extras.runeStyles?.[ids[1]] || `副系 ${ids[1]}`}`) : `<div class="empty-panel">没有足够样本。</div>`;
    if (!profile) { $("sampleEnumPanel").innerHTML = `<div class="empty-panel">没有足够样本。</div>`; $("itemSlotPanel").innerHTML = `<div class="empty-panel">没有足够样本。</div>`; return; }
    $("sampleEnumPanel").innerHTML = `<p class="choice-subhead">版本</p>${choiceRows(profile.patches)}<p class="choice-subhead">段位</p>${choiceRows(profile.ranks)}<p class="choice-subhead">结果</p>${choiceRows(profile.results)}`;
    $("itemSlotPanel").innerHTML = profile.itemSlots.map((slot, index) => `<div class="slot-column"><h4>${index === 6 ? "饰品栏" : `物品栏 ${index + 1}`}</h4>${slot.slice(0, ui.itemSlotLimit).map((entry) => { const item = extras.items?.[entry.value] || { name: `物品 ${entry.value}`, icon: `${entry.value}.png` }; const icon = `https://ddragon.leagueoflegends.com/cdn/${extras.meta?.itemVersion || "16.13.1"}/img/item/${item.icon}`; return `<div class="slot-item" title="ID ${escapeHtml(entry.value)}"><img src="${icon}" alt=""><span>${escapeHtml(item.name)}</span><b>${(entry.share * 100).toFixed(0)}%</b></div>`; }).join("")}</div>`).join("");
  }

  const dragonTypeNames = { FIRE_DRAGON: "炼狱亚龙", WATER_DRAGON: "海洋亚龙", AIR_DRAGON: "云端亚龙", EARTH_DRAGON: "山脉亚龙", HEXTECH_DRAGON: "海克斯科技亚龙", CHEMTECH_DRAGON: "炼金科技亚龙", ELDER_DRAGON: "远古巨龙", UNKNOWN_DRAGON: "未标注龙种" };
  const dragonOutcomeNames = { secured_contested: "交战后控下", secured_quiet: "无击杀窗口控下", lost_contested: "交战后丢龙", lost_quiet: "无击杀窗口丢龙" };
  function metricByName(metric) { return currentRows().find((row) => row.m === metric); }
  function renderDragon() {
    const metrics = ["dragon_fight_participations", "dragon_secure_rate_when_present", "dragon_fight_kill_participation", "dragon_fight_survival_rate", "team_dragons_timeline", "dragon_fight_windows", "first_dragon_minute", "teamfight_participation_rate"];
    $("dragonStatGrid").innerHTML = metrics.map((metric) => {
      const row = metricByName(metric);
      const [name] = label(metric);
      return `<article class="dragon-stat"><span>${escapeHtml(name)}</span><strong>${row ? fmtMetric(metric, row.median) : "—"}</strong><small>${row ? `P25 ${fmtMetric(metric, row.p25)} · P75 ${fmtMetric(metric, row.p75)} · n=${row.n_clean}` : "样本不足"}</small></article>`;
    }).join("");
    const profile = extras.profiles?.[currentKey()];
    $("dragonTypePanel").innerHTML = profile ? choiceRows(profile.dragonTypes, (value) => dragonTypeNames[value] || value) : `<div class="empty-panel">没有足够样本。</div>`;
    $("dragonOutcomePanel").innerHTML = profile ? choiceRows(profile.dragonOutcomes, (value) => dragonOutcomeNames[value] || value) : `<div class="empty-panel">没有足够样本。</div>`;
  }

  function updateCategoryOptions() {
    const select = $("metricCategory");
    const previous = select.value || "全部类别";
    const counts = new Map();
    currentRows().filter((row) => !categoricalIdPattern.test(row.m)).forEach((row) => counts.set(metricCategory(row.m), (counts.get(metricCategory(row.m)) || 0) + 1));
    select.innerHTML = `<option value="全部类别">全部类别</option>${[...counts].sort((a, b) => a[0].localeCompare(b[0], "zh-CN")).map(([category, count]) => `<option value="${escapeHtml(category)}">${escapeHtml(category)}（${count}）</option>`).join("")}`;
    select.value = [...select.options].some((option) => option.value === previous) ? previous : "全部类别";
  }

  function renderAllData() {
    const category = $("metricCategory").value;
    const search = $("allMetricSearch").value.trim().toLowerCase();
    const showZero = $("showZeroMetrics").checked;
    let rows = currentRows().filter((row) => !categoricalIdPattern.test(row.m));
    if (category !== "全部类别") rows = rows.filter((row) => metricCategory(row.m) === category);
    if (search) rows = rows.filter((row) => `${label(row.m)[0]} ${row.m} ${sourceOf(row.m)}`.toLowerCase().includes(search));
    if (!showZero) rows = rows.filter((row) => !isZero(row));
    rows.sort((a, b) => metricCategory(a.m).localeCompare(metricCategory(b.m), "zh-CN") || label(a.m)[0].localeCompare(label(b.m)[0], "zh-CN"));
    $("allMetricCount").textContent = `显示 ${Math.min(rows.length, allLimit)} / ${rows.length} 字段`;
    $("allMetricRows").innerHTML = rows.slice(0, allLimit).map((row) => `<tr><td class="metric-name-cell"><b>${escapeHtml(label(row.m)[0])}</b><code>${escapeHtml(row.m)}</code></td><td><span class="source-pill">${escapeHtml(sourceOf(row.m))}</span></td><td>${row.n_clean}/${row.n_raw}</td><td>${fmtMetric(row.m, row.p25)}</td><td>${fmtMetric(row.m, row.median)}</td><td>${fmtMetric(row.m, row.mean)}</td><td>${fmtMetric(row.m, row.p75)}</td></tr>`).join("");
    $("allMetricMore").hidden = rows.length <= allLimit;
  }

  function renderProfile() {
    const champion = $("championSelect").value;
    const role = $("roleSelect").value;
    const rows = currentRows();
    const maxN = Math.max(0, ...rows.map((row) => row.n_raw));
    const confidence = grade(maxN);
    $("profileTitle").textContent = `${champion} · ${roles[role] || role}`;
    $("championGlyph").textContent = champion[0];
    $("sampleCount").textContent = maxN;
    $("confidenceLabel").textContent = confidence[0];
    $("confidenceBar").style.width = `${confidence[2]}%`;
    $("confidenceText").textContent = maxN >= confidenceNarrativeMin ? `最多 ${maxN} 个有效样本，适合观察典型区间。` : `最多 ${maxN} 个样本，暂时只适合探索。`;
    renderMetrics();
    renderEnumerables();
    renderDragon();
    updateCategoryOptions();
    renderAllData();
  }

  function updateRoles() {
    const champion = $("championSelect").value;
    const available = [...new Set(data.filter((row) => row.c === champion).map((row) => row.r))].sort();
    $("roleSelect").innerHTML = available.map((role) => `<option value="${role}">${roles[role] || role}</option>`).join("");
    limit = ui.metricInitialLimit;
    allLimit = ui.tableInitialLimit;
    renderProfile();
  }

  function populate() {
    $("championSelect").innerHTML = champions.map((champion) => `<option value="${champion}"${champion === "Kaisa" ? " selected" : ""}>${champion}</option>`).join("");
    updateRoles();
  }

  function coverage() {
    const seen = new Map();
    data.forEach((row) => {
      const key = `${row.c}|${row.r}`;
      seen.set(key, Math.max(seen.get(key) || 0, row.n_raw));
    });
    const top = [...seen].sort((a, b) => b[1] - a[1]).slice(0, ui.coverageLimit);
    const max = top[0]?.[1] || 1;
    $("coverageList").innerHTML = top.map(([key, n]) => {
      const [champion, role] = key.split("|");
      return `<div class="coverage-row"><span>${champion} · ${roles[role] || role}</span><div class="coverage-track"><i style="width:${n / max * 100}%"></i></div><b>${n}</b></div>`;
    }).join("");
  }

  document.querySelector('[data-phase="mid"]').textContent = `15–${lateStartMinute} 分钟`;
  document.querySelector('[data-phase="late"]').textContent = `${lateStartMinute} 分钟后`;

  $("championSelect").addEventListener("change", updateRoles);
  $("roleSelect").addEventListener("change", () => { limit = ui.metricInitialLimit; allLimit = ui.tableInitialLimit; renderProfile(); });
  $("metricSearch").addEventListener("input", () => { limit = ui.metricInitialLimit; renderMetrics(); });
  document.querySelectorAll(".phase-nav button").forEach((button) => button.addEventListener("click", () => {
    document.querySelector(".phase-nav .active").classList.remove("active");
    button.classList.add("active");
    phase = button.dataset.phase;
    limit = ui.metricInitialLimit;
    renderMetrics();
  }));
  $("loadMore").addEventListener("click", () => { limit += ui.metricLoadMore; renderMetrics(); });
  $("metricCategory").addEventListener("change", () => { allLimit = ui.tableInitialLimit; renderAllData(); });
  $("allMetricSearch").addEventListener("input", () => { allLimit = ui.tableInitialLimit; renderAllData(); });
  $("showZeroMetrics").addEventListener("change", () => { allLimit = ui.tableInitialLimit; renderAllData(); });
  $("allMetricMore").addEventListener("click", () => { allLimit += ui.tableLoadMore; renderAllData(); });

  const totalParameters = data.length;
  $("rowCount").textContent = Number(core.meta?.player_match_rows || 0).toLocaleString("zh-CN");
  $("playerCount").textContent = Number(core.meta?.players_sampled || 0).toLocaleString("zh-CN");
  $("parameterCount").textContent = totalParameters.toLocaleString("zh-CN");
  $("enumProfileCount").textContent = Number(extras.meta?.profileCount || 0).toLocaleString("zh-CN");
  const revision = manifest.revision ? ` · 版本 ${manifest.revision.slice(0, 8)}` : "";
  $("datasetState").textContent = `全量模型已载入 · ${totalParameters.toLocaleString("zh-CN")} 数值参数${revision}`;
  $("dragonMethod").textContent = `±${fmt(modelParameters.dragon_window_seconds)} 秒 · 龙坑半径 ${fmt(modelParameters.dragon_radius)}`;
  populate();
  coverage();
})();
