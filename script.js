const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const layerData = [
  {
    kicker: "官方明确",
    title: "MMR 是估计，不是“系统情绪”",
    text: "把它想成系统持续更新的一张内部成绩单。评分系统研究常用“均值 + 不确定性”描述实力，但 Riot 并未公开英雄联盟 MMR 的完整公式。",
    strength: 96,
    label: "官方机制"
  },
  {
    kicker: "官方明确",
    title: "Rank 是显示层，不是底层变量",
    text: "同段位玩家的 MMR 可以不同；同一玩家的 Rank 也可能暂时高于或低于 MMR。它是一种可读、可追踪的竞技身份。",
    strength: 96,
    label: "官方机制"
  },
  {
    kicker: "官方明确",
    title: "LP 在修正两层之间的错位",
    text: "MMR 高于 Rank，通常赢得更多、输得更少；MMR 低于 Rank，则可能相反。它更像校准器，不是系统好恶的温度计。",
    strength: 94,
    label: "官方机制"
  },
  {
    kicker: "工程解释",
    title: "匹配是多目标优化，不是单变量抽签",
    text: "双方平均实力只是目标之一；位置供给、等待时间、自动补位和在线玩家池都在施加约束。工程折中可能制造体感差异，但不自动等于恶意安排。",
    strength: 82,
    label: "官方原则 + 合理解释"
  }
];

function selectLayer(index) {
  $$(".layer-tab").forEach((tab, i) => {
    tab.classList.toggle("active", i === index);
    tab.setAttribute("aria-selected", String(i === index));
  });
  $$(".stack-card").forEach((card, i) => card.classList.toggle("active", i === index));
  const data = layerData[index];
  $("#layerKicker").textContent = data.kicker;
  $("#layerTitle").textContent = data.title;
  $("#layerText").textContent = data.text;
  $("#certaintyBar").style.width = `${data.strength}%`;
  $("#certaintyLabel").textContent = data.label;
}

$$(".layer-tab").forEach((tab, index) => tab.addEventListener("click", () => selectLayer(index)));
$$(".stack-card").forEach((card, index) => card.addEventListener("click", () => selectLayer(index)));

const gapInput = $("#mmrGap");
function updateSimulator(value) {
  const gap = Number(value);
  const normalized = gap / 300;
  const win = Math.round(24 + normalized * 7);
  const loss = Math.round(24 - normalized * 7);
  const output = $("#gapOutput");
  output.textContent = `${gap > 0 ? "+" : ""}${gap}`;
  output.style.color = gap >= 0 ? "var(--cyan)" : "var(--red)";
  $("#winLp").textContent = `+${win}`;
  $("#lossLp").textContent = `−${loss}`;
  $("#mmrMarker").style.top = `${48 - normalized * 36}%`;
  $("#mmrMarkerText").textContent = gap === 0 ? "基本一致" : `${gap > 0 ? "高" : "低"} ${Math.abs(gap)}`;
  $("#mmrMarker").style.color = gap >= 0 ? "var(--cyan)" : "var(--red)";

  let message = "MMR 与 Rank 基本一致，LP 增减通常更接近对称。";
  if (gap > 50) message = "你的 MMR 高于当前 Rank，LP 正在把可见段位向隐藏估计拉近。";
  if (gap < -50) message = "你的 Rank 暂时高于 MMR，LP 正在向下修正两者之间的差距。";
  $("#simExplanation").textContent = message;
  $(".status-dot").style.background = gap < -50 ? "var(--red)" : gap > 50 ? "var(--cyan)" : "var(--gold)";
}
gapInput.addEventListener("input", (event) => updateSimulator(event.target.value));
$$(".scenario-buttons button").forEach(button => button.addEventListener("click", () => {
  gapInput.value = button.dataset.gap;
  updateSimulator(button.dataset.gap);
}));
updateSimulator(gapInput.value);

const teamGapInput = $("#teamGap");
function updateWinFormula(value) {
  const gap = Number(value);
  const teamA = 1500 + gap / 2;
  const teamB = 1500 - gap / 2;
  const chanceA = 100 / (1 + Math.pow(10, -gap / 400));
  const chanceB = 100 - chanceA;
  const withinWindow = Math.abs(gap) <= 100;

  $("#teamGapOutput").textContent = `${gap > 0 ? "+" : ""}${gap}`;
  $("#teamAMmr").textContent = Math.round(teamA);
  $("#teamBMmr").textContent = Math.round(teamB);
  $("#teamAChance").textContent = `${chanceA.toFixed(1)}%`;
  $("#teamBChance").textContent = `${chanceB.toFixed(1)}%`;
  $("#gapNeedle").style.left = `${((gap + 200) / 400) * 100}%`;
  $("#gapNeedle").style.borderColor = withinWindow ? "var(--cyan)" : "var(--red)";
  $("#gapNeedle").style.boxShadow = `0 0 16px ${withinWindow ? "var(--cyan)" : "var(--red)"}`;
  $("#balanceVerdict").textContent = withinWindow ? "平均分差在 100 以内" : "平均分差超过 100";
  $("#balanceVerdict").style.color = withinWindow ? "var(--cyan)" : "var(--red)";
  $("#balanceDetail").textContent = `按经典 Elo 示例，蓝方预期胜率约为 ${chanceA.toFixed(1)}%，红方约为 ${chanceB.toFixed(1)}%。`;
}
teamGapInput.addEventListener("input", event => updateWinFormula(event.target.value));
updateWinFormula(teamGapInput.value);

const playerExamples = {
  "blue-top": ["蓝方上路 · TOP", "翡翠 I 62 LP", "1580", "1540", 40, "MMR 高于当前可见 Rank，因此 LP 变化可能更偏向“赢得多、输得少”。"],
  "blue-jungle": ["蓝方打野 · JNG", "翡翠 II 18 LP", "1515", "1500", 15, "MMR 与当前 Rank 比较接近，LP 增减通常会更接近对称。"],
  "blue-mid": ["蓝方中路 · MID", "翡翠 II 45 LP", "1540", "1500", 40, "MMR 略高于当前 Rank，系统可能仍在把可见段位向上校准。"],
  "blue-bottom": ["蓝方下路 · BOT", "翡翠 III 77 LP", "1470", "1460", 10, "可见 Rank 与 MMR 并非同一个变量；同队玩家也不需要拥有完全相同的数值。"],
  "blue-support": ["蓝方辅助 · SUP", "白金 I 84 LP", "1435", "1420", 15, "较低的可见 Rank 玩家仍可能因整体 MMR、位置供给与队列约束进入这场对局。"],
  "red-top": ["红方上路 · TOP", "翡翠 II 71 LP", "1510", "1500", 10, "这名玩家的 Rank 与 MMR 大致处于同一水平带。"],
  "red-jungle": ["红方打野 · JNG", "翡翠 II 34 LP", "1530", "1500", 30, "MMR 略高于可见 Rank；这不表示系统偏爱该账号，只表示两层暂时错位。"],
  "red-mid": ["红方中路 · MID", "翡翠 II 92 LP", "1455", "1500", -45, "可见 Rank 暂时高于 MMR 时，LP 可能出现赢得较少、输得较多。"],
  "red-bottom": ["红方下路 · BOT", "翡翠 II 8 LP", "1505", "1500", 5, "低 LP 不等于低 MMR；LP 只是玩家在当前可见分段中的位置。"],
  "red-support": ["红方辅助 · SUP", "白金 I 96 LP", "1460", "1420", 40, "系统平衡的是队伍整体，不保证每个位置都由相同 Rank 或相同 MMR 一一配对。"]
};

function selectPlayerExample(playerId) {
  const [role, rank, mmr, rankRef, delta, explanation] = playerExamples[playerId];
  const deltaClass = delta > 20 ? "positive" : delta < -20 ? "negative" : "neutral";
  const deltaText = `${delta >= 0 ? "+" : "−"}${Math.abs(delta)}`;
  $$(".player-card").forEach(card => card.classList.toggle("active", card.dataset.player === playerId));
  $$(".map-role").forEach(marker => marker.classList.toggle("active", marker.dataset.mapPlayer === playerId));
  $("#selectedRole").textContent = role;
  $("#selectedComparison").innerHTML = `${rank} <i>≠</i> MMR ${mmr}`;
  $("#selectedRankRef").textContent = rankRef;
  $("#selectedDelta").textContent = `Δ ${deltaText}`;
  $("#selectedDelta").className = deltaClass;
  $("#selectedExplanation").textContent = explanation;
}

$$(".player-card").forEach(card => card.addEventListener("click", () => selectPlayerExample(card.dataset.player)));
selectPlayerExample("blue-top");

const extremeScenarios = {
  horse: {
    kicker: "内部方差很大",
    title: "一个“上等马”与一个“下等马”可以同时出现在同队",
    blue: [
      ["钻石 IV", 1700], ["翡翠 I", 1550], ["翡翠 III", 1450], ["白金 I", 1425], ["白金 II", 1375]
    ],
    red: [
      ["翡翠 I", 1540], ["翡翠 II", 1520], ["翡翠 II", 1500], ["翡翠 III", 1480], ["翡翠 III", 1460]
    ],
    meaning: "两队平均值完全相同，但蓝方从 1700 到 1375，内部跨度达到 325。上路会像“上等马”，辅助则像“下等马”。",
    boundary: "它不能证明系统为了惩罚某个人而故意配置队友；位置供给、排队时间和玩家池也能产生这种不整齐的组合。"
  },
  offset: {
    kicker: "分路差异相互抵消",
    title: "平均值相同，不代表每条路都是五五开",
    blue: [
      ["钻石 IV", 1650], ["翡翠 I", 1540], ["翡翠 II", 1500], ["白金 I", 1430], ["白金 II", 1380]
    ],
    red: [
      ["白金 II", 1380], ["白金 I", 1430], ["翡翠 II", 1500], ["翡翠 I", 1540], ["钻石 IV", 1650]
    ],
    meaning: "双方平均都是 1500，但蓝方上野明显更强，红方下路组合明显更强。比赛可能表现为两边各自从优势路扩大影响。",
    boundary: "赛后某一路被碾压，并不代表整场匹配的平均 MMR 一定失衡；也不能据此反推出系统预先指定了胜负。"
  },
  winstreak: {
    kicker: "MMR 先于 Rank 上升",
    title: "连胜后，对局变难可以来自评分已经上升",
    blue: [
      ["翡翠 I", 1620], ["翡翠 I", 1605], ["翡翠 II", 1660], ["翡翠 I", 1590], ["翡翠 II", 1575]
    ],
    red: [
      ["翡翠 I", 1625], ["翡翠 I", 1610], ["钻石 IV", 1630], ["翡翠 I", 1600], ["翡翠 II", 1585]
    ],
    meaning: "蓝方中路可见 Rank 仍是翡翠 II，但隐藏 MMR 已到 1660。连续获胜把他送进了整体约 1610 的更强对局池。",
    boundary: "更强的对手和更难的对局是评分上升的正常结果；这本身不等于系统在连胜后安排“必输局”。"
  },
  lossstreak: {
    kicker: "Rank 暂时高于 MMR",
    title: "连败后，可见段位可能还没完全跟上隐藏评分",
    blue: [
      ["白金 I", 1430], ["白金 I", 1400], ["翡翠 I", 1380], ["白金 I", 1395], ["白金 II", 1415]
    ],
    red: [
      ["白金 I", 1415], ["白金 I", 1400], ["白金 II", 1390], ["白金 I", 1410], ["白金 I", 1405]
    ],
    meaning: "蓝方中路仍显示翡翠 I，但隐藏 MMR 示例只有 1380，实际进入的是平均约 1404 的对局；此时 LP 往往承担向下校准。",
    boundary: "连败后的低 MMR、负向 LP 和队友体感变差可能同时出现，但时间上的连续性仍不足以证明存在独立的“败者组”。"
  }
};

function renderExtremeScenario(key) {
  const scenario = extremeScenarios[key];
  const blueAverage = Math.round(scenario.blue.reduce((sum, player) => sum + player[1], 0) / 5);
  const redAverage = Math.round(scenario.red.reduce((sum, player) => sum + player[1], 0) / 5);
  $("#extremeKicker").textContent = scenario.kicker;
  $("#extremeTitle").textContent = scenario.title;
  $("#extremeBlueAvg").textContent = blueAverage;
  $("#extremeRedAvg").textContent = redAverage;
  $("#extremeAvgGap").textContent = Math.abs(blueAverage - redAverage);
  $("#extremeMeaning").textContent = scenario.meaning;
  $("#extremeBoundary").textContent = scenario.boundary;
  $$(".extreme-tab").forEach(tab => tab.classList.toggle("active", tab.dataset.extreme === key));

  $$("[data-extreme-row]").forEach((row, index) => {
    const blue = scenario.blue[index];
    const red = scenario.red[index];
    const difference = blue[1] - red[1];
    const differenceClass = difference > 25 ? "blue-advantage" : difference < -25 ? "red-advantage" : "even";
    const [bluePlayer, redPlayer] = $$(".extreme-player", row);
    $(".extreme-rank", bluePlayer).textContent = blue[0];
    $(".extreme-mmr", bluePlayer).textContent = blue[1];
    $(".rating-bar i", bluePlayer).style.width = `${Math.max(8, Math.min(100, (blue[1] - 1300) / 4.5))}%`;
    $(".extreme-rank", redPlayer).textContent = red[0];
    $(".extreme-mmr", redPlayer).textContent = red[1];
    $(".rating-bar i", redPlayer).style.width = `${Math.max(8, Math.min(100, (red[1] - 1300) / 4.5))}%`;
    const laneDiff = $(".lane-diff", row);
    laneDiff.className = `lane-diff ${differenceClass}`;
    $("b", laneDiff).textContent = `${difference >= 0 ? "+" : "−"}${Math.abs(difference)}`;
    $("small", laneDiff).textContent = differenceClass === "blue-advantage" ? "蓝方更高" : differenceClass === "red-advantage" ? "红方更高" : "基本接近";
  });
}

$$(".extreme-tab").forEach(tab => tab.addEventListener("click", () => renderExtremeScenario(tab.dataset.extreme)));
renderExtremeScenario("horse");

let heroValue = 1628;
setInterval(() => {
  if (document.body.classList.contains("motion-paused")) return;
  heroValue += Math.random() > .47 ? 1 : -1;
  $("#heroMmr").textContent = heroValue;
}, 1500);

const motionButton = $("#motionToggle");
motionButton.addEventListener("click", () => {
  const paused = document.body.classList.toggle("motion-paused");
  motionButton.textContent = paused ? "继续动画" : "暂停动画";
  motionButton.setAttribute("aria-pressed", String(paused));
});

window.addEventListener("scroll", () => $(".topbar").classList.toggle("scrolled", scrollY > 30), { passive: true });

$("#quickDemo").addEventListener("click", async () => {
  $("#layers").scrollIntoView({ behavior: "smooth" });
  for (let i = 0; i < 4; i += 1) {
    await new Promise(resolve => setTimeout(resolve, i === 0 ? 800 : 1200));
    selectLayer(i);
  }
  await new Promise(resolve => setTimeout(resolve, 1000));
  $("#simulator").scrollIntoView({ behavior: "smooth" });
  for (const gap of [-220, 0, 220]) {
    await new Promise(resolve => setTimeout(resolve, 1100));
    gapInput.value = gap;
    updateSimulator(gap);
  }
});

const canvas = $("#convergenceChart");
const ctx = canvas.getContext("2d");
let chartProgress = 0;
let chartFrame;
const dpr = Math.min(window.devicePixelRatio || 1, 2);

function setupCanvas() {
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.width * 0.565 * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function drawChart(progress = 1) {
  const width = canvas.width / dpr;
  const height = canvas.height / dpr;
  const pad = { left: 48, right: 22, top: 30, bottom: 40 };
  const w = width - pad.left - pad.right;
  const h = height - pad.top - pad.bottom;
  ctx.clearRect(0, 0, width, height);

  ctx.font = "10px 'Space Grotesk'";
  ctx.fillStyle = "#59666b";
  ctx.strokeStyle = "rgba(200,222,226,.10)";
  ctx.lineWidth = 1;
  [40, 50, 60, 70].forEach(value => {
    const y = pad.top + h - ((value - 40) / 30) * h;
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
    ctx.fillText(`${value}%`, 10, y + 3);
  });

  const equilibriumY = pad.top + h - (10 / 30) * h;
  ctx.setLineDash([5, 6]); ctx.strokeStyle = "rgba(180,190,194,.35)";
  ctx.beginPath(); ctx.moveTo(pad.left, equilibriumY); ctx.lineTo(width - pad.right, equilibriumY); ctx.stroke();
  ctx.setLineDash([]);

  const total = 70;
  const visible = Math.floor(total * progress);
  const points = Array.from({ length: total }, (_, i) => {
    const t = i / (total - 1);
    return 50 + 16 * Math.exp(-3.4 * t) + Math.sin(i * .55) * (1.8 * (1 - t));
  });
  drawLine(points, visible, "#63e6e2", 40, 70, pad, w, h);

  const mmrPoints = Array.from({ length: total }, (_, i) => 15 + 72 * (1 - Math.exp(-3 * i / (total - 1))));
  drawLine(mmrPoints, visible, "#d8a94d", 0, 100, pad, w, h, .8);

  const x = pad.left + w * progress;
  const yValue = points[Math.min(visible, total - 1)] || points[0];
  const y = pad.top + h - ((yValue - 40) / 30) * h;
  ctx.fillStyle = "#63e6e2"; ctx.shadowColor = "#63e6e2"; ctx.shadowBlur = 14;
  ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fill(); ctx.shadowBlur = 0;

  ctx.fillStyle = "#59666b";
  ctx.fillText("低 MMR 对局", pad.left, height - 12);
  ctx.fillText("接近当前实力", width - pad.right - 75, height - 12);
}

function drawLine(points, visible, color, min, max, pad, w, h, alpha = 1) {
  if (visible < 2) return;
  ctx.beginPath();
  points.slice(0, visible).forEach((value, i) => {
    const x = pad.left + (i / (points.length - 1)) * w;
    const y = pad.top + h - ((value - min) / (max - min)) * h;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.strokeStyle = color;
  ctx.globalAlpha = alpha;
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.globalAlpha = 1;
}

function animateChart() {
  cancelAnimationFrame(chartFrame);
  chartProgress = 0;
  const tick = () => {
    chartProgress = Math.min(1, chartProgress + .012);
    drawChart(chartProgress);
    if (chartProgress < .45) $("#chartStatus").textContent = "实力高于当前环境";
    else if (chartProgress < .82) $("#chartStatus").textContent = "对局强度正在追上";
    else $("#chartStatus").textContent = "接近当前均衡位置";
    if (chartProgress < 1) chartFrame = requestAnimationFrame(tick);
  };
  tick();
}

setupCanvas();
drawChart(0);
window.addEventListener("resize", () => { setupCanvas(); drawChart(chartProgress); });
$("#replayChart").addEventListener("click", animateChart);

const observer = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (!entry.isIntersecting) return;
    if (entry.target === canvas && chartProgress === 0) animateChart();
    observer.unobserve(entry.target);
  });
}, { threshold: .35 });
observer.observe(canvas);

$$("details").forEach(item => item.addEventListener("toggle", () => {
  if (!item.open) return;
  $$("details").forEach(other => { if (other !== item) other.open = false; });
}));
