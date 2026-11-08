/* ============================================================
   扩展功能：学习看板 / 复习队列 / 检索详情 / 全文检索 / 报告导出
   —— 依赖 app.js 暴露的 $ / api / esc / md / toast / state
   ============================================================ */
'use strict';

/* ---------------------------------------------------------------- 小工具 */
function readFileBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error('文件读取失败'));
    reader.readAsDataURL(file);
  });
}

function pct(n) { return `${Math.round(Number(n) || 0)}%`; }

function statusClass(status) {
  return { '已掌握': 'ok', '巩固中': 'mid', '薄弱': 'bad', '未练习': 'idle' }[status] || 'idle';
}

function hl(text, query) {
  const safe = esc(text || '');
  const words = String(query || '').split(/\s+/).filter((w) => w.length >= 1).slice(0, 6);
  if (!words.length) return safe;
  const pattern = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
  try {
    return safe.replace(new RegExp(`(${pattern})`, 'g'), '<mark>$1</mark>');
  } catch (e) { return safe; }
}

/* ---------------------------------------------------------------- 学习看板 */
async function loadDashboard() {
  try {
    const d = await api('/api/dashboard');
    renderKpi(d);
    renderRecommend(d.recommend || []);
    renderReviews(d.reviews || [], d.due || 0);
    renderHeatmap(d.activity || {});
    renderForecast(d.forecast || {});
    renderRadar(d);
    renderMastery(d.mastery || { chapters: [], subjects: [], overall: {} });
    renderUsage(d.usage || {});
    loadMistakes();
    loadPending();
    renderGraph();
  } catch (err) {
    toast('看板加载失败：' + err.message, true);
  }
}

/* ---------------------------------------------------------------- 可视化：热力图 */
function renderHeatmap(activity) {
  const box = $('#heatmap-box');
  if (!box) return;
  const counts = {};
  (activity.days || []).forEach((x) => { counts[x.day] = x.count; });
  const max = Math.max(1, activity.max || 1);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const start = new Date(today);
  start.setDate(start.getDate() - 12 * 7 + 1);
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7));   // 对齐到周一

  box.innerHTML = '';
  const wrap = document.createElement('div');
  wrap.className = 'heatmap-wrap';
  const row = document.createElement('div');
  row.className = 'heatmap-row';

  const axis = document.createElement('div');
  axis.className = 'hm-axis';
  axis.innerHTML = ['一', '', '三', '', '五', '', '日'].map((t) => `<span>${t}</span>`).join('');
  row.appendChild(axis);

  const grid = document.createElement('div');
  grid.className = 'hm-grid';
  let total = 0;
  for (let w = 0; w < 14; w += 1) {
    const col = document.createElement('div');
    col.className = 'hm-col';
    for (let day = 0; day < 7; day += 1) {
      const dt = new Date(start);
      dt.setDate(start.getDate() + w * 7 + day);
      const cell = document.createElement('i');
      if (dt > today) { cell.className = 'hm-cell empty'; col.appendChild(cell); continue; }
      const key = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
      const n = counts[key] || 0;
      total += n;
      const level = n === 0 ? 0 : Math.min(4, 1 + Math.floor((n / max) * 3.99));
      cell.className = `hm-cell l${level}`;
      cell.title = `${key}：${n} 次学习活动`;
      col.appendChild(cell);
    }
    grid.appendChild(col);
  }
  row.appendChild(grid);
  wrap.appendChild(row);

  const legend = document.createElement('div');
  legend.className = 'heatmap-legend';
  legend.innerHTML = '少' + [0, 1, 2, 3, 4].map((l) => `<i class="hm-cell l${l}"></i>`).join('') + '多';
  wrap.appendChild(legend);

  box.appendChild(wrap);
  const sub = $('#heatmap-sub');
  if (sub) sub.textContent = `合计 ${total} 次 · 最深 ${max} 次/天`;
}

/* ---------------------------------------------------------------- 可视化：复习预测 */
function renderForecast(forecast) {
  const box = $('#forecast-box');
  if (!box) return;
  const days = forecast.days || [];
  const total = days.reduce((n, d) => n + (d.count || 0), 0);
  if (!total && !forecast.overdue) {
    box.innerHTML = `<div class="forecast-empty"><i><svg class="line-icon" aria-hidden="true"><use href="/icons.svg#calendar"></use></svg></i>
      未来 7 天没有到期复习，做几道题就会自动排期</div>`;
    return;
  }
  const peak = Math.max(1, forecast.peak || 1);
  box.innerHTML = days.map((d) => `
    <div class="fc-col" title="${esc(d.day)}：${d.count} 条到期">
      <div class="fc-bar${d.count ? '' : ' zero'}" style="height:${Math.max(3, (d.count / peak) * 74)}px"></div>
      <div class="fc-count">${d.count}</div>
      <div class="fc-label">${esc(d.label)}</div>
    </div>`).join('');
  if (forecast.overdue) {
    const tip = document.createElement('div');
    tip.className = 'fc-overdue';
    tip.textContent = `另有 ${forecast.overdue} 条已过期，建议先清掉`;
    box.appendChild(tip);
  }
}

/* ---------------------------------------------------------------- 可视化：能力雷达 */
function renderRadar(d) {
  const cv = $('#radar-canvas');
  if (!cv) return;
  const mastery = d.mastery || {};
  const overall = mastery.overall || {};
  const chapters = mastery.chapters || [];
  const practiced = chapters.filter((c) => c.attempts > 0).length;
  const dims = [
    { label: '练习量', value: Math.min(1, (overall.attempts || 0) / 30) },
    { label: '正确率', value: Math.min(1, (overall.rate || 0) / 100) },
    { label: '复习完成', value: Math.max(0, 1 - Math.min(1, (d.due || 0) / 8)) },
    { label: '资料覆盖', value: chapters.length ? practiced / chapters.length : 0 },
  ];
  const ctx = setupCanvas(cv, 300);
  if (!ctx) return;
  const { w, h } = ctx;
  const cx = w / 2;
  const cy = h / 2 + 2;
  const radius = Math.min(w, h) / 2 - 46;
  const n = dims.length;
  const angle = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / n;
  const thin = dims.reduce((s, x) => s + x.value, 0) < 0.12;

  ctx.clearRect(0, 0, w, h);
  for (let ring = 4; ring >= 1; ring -= 1) {
    ctx.beginPath();
    for (let i = 0; i < n; i += 1) {
      const r = (radius * ring) / 4;
      const x = cx + Math.cos(angle(i)) * r;
      const y = cy + Math.sin(angle(i)) * r;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.strokeStyle = ring === 4 ? '#d7e0ee' : '#eef2f8';
    ctx.stroke();
  }
  for (let i = 0; i < n; i += 1) {
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(angle(i)) * radius, cy + Math.sin(angle(i)) * radius);
    ctx.strokeStyle = '#eef2f8';
    ctx.stroke();
  }
  ctx.beginPath();
  dims.forEach((dim, i) => {
    const r = radius * Math.max(0.04, Math.min(1, dim.value));
    const x = cx + Math.cos(angle(i)) * r;
    const y = cy + Math.sin(angle(i)) * r;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.closePath();
  ctx.fillStyle = 'rgba(47,111,237,.18)';
  ctx.fill();
  ctx.strokeStyle = '#2f6fed';
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.lineWidth = 1;

  ctx.font = '12px "Microsoft YaHei", sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  dims.forEach((dim, i) => {
    const x = cx + Math.cos(angle(i)) * (radius + 22);
    const y = cy + Math.sin(angle(i)) * (radius + 18);
    ctx.fillStyle = '#5b6b7f';
    ctx.fillText(dim.label, x, y - 7);
    ctx.fillStyle = '#2f6fed';
    ctx.fillText(`${Math.round(dim.value * 100)}%`, x, y + 8);
  });
  if (thin) {
    ctx.fillStyle = '#93a1b3';
    ctx.font = '12px "Microsoft YaHei", sans-serif';
    ctx.fillText('数据还太少，做几道题雷达才有形状', cx, cy + radius * 0.55);
  }
}

/* ---------------------------------------------------------------- 可视化：知识图谱 */
const GRAPH_COLORS = ['#2f6fed', '#12a45a', '#c9820a', '#8b5cf6', '#d64545', '#0ea5e9', '#ec4899', '#14b8a6'];
let graphData = null;
let graphFullOpen = false;

function setupCanvas(cv, height) {
  if (!cv) return null;
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth || cv.parentElement.clientWidth || 440;
  cv.width = Math.round(w * dpr);
  cv.height = Math.round(height * dpr);
  cv.style.height = `${height}px`;
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return Object.assign(ctx, { w, h: height });
}

function graphSubjects(data) {
  const list = (data && data.subjects) || [];
  return list.map((s) => (typeof s === 'string'
    ? { name: s, chapters: 0, materials: 0 }
    : { name: s.name, chapters: s.chapters || 0, materials: s.materials || 0 }));
}

function graphColor(name, subjects) {
  if (!name || name === '未分类') return '#8a97a8';
  const idx = subjects.findIndex((s) => s.name === name);
  return idx >= 0 ? GRAPH_COLORS[idx % GRAPH_COLORS.length] : '#8a97a8';
}

function hexAlpha(hex, alpha) {
  const h = String(hex || '').replace('#', '');
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
  const n = parseInt(full, 16);
  if (Number.isNaN(n)) return `rgba(120,140,170,${alpha})`;
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}

async function graphFetch(force) {
  if (graphData && !force) return graphData;
  graphData = await api('/api/graph');
  return graphData;
}

function graphLegendHtml(data) {
  const subjects = graphSubjects(data);
  const parts = subjects.map((s) => `<span class="gl-item"><i style="background:${graphColor(s.name, subjects)}"></i>${esc(s.name)}<em>${s.chapters} 章 · ${s.materials} 份资料</em></span>`);
  parts.push('<span class="gl-item gl-note"><i class="gl-pill"></i>胶囊=科目，实心圆=章节，浅色小圆=资料；悬停看名称，点击节点跳转，点空白全屏</span>');
  return parts.join('');
}

function graphSize(cv, full) {
  const rect = cv.getBoundingClientRect();
  const w = Math.max(320, Math.round(rect.width || cv.parentElement.clientWidth || 440));
  const h = Math.max(260, Math.round(full ? (cv.clientHeight || (window.innerHeight - 150)) : 340));
  const dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(w * dpr);
  cv.height = Math.round(h * dpr);
  if (!full) cv.style.height = `${h}px`;
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h };
}

function buildGraph(data, w, h, full) {
  const subjects = graphSubjects(data);
  const raw = (data.nodes || []).map((n) => ({ ...n, color: graphColor(n.subject || n.group, subjects) }));
  if (!raw.length) return null;
  const anchors = new Map();
  const count = Math.max(1, subjects.length);
  subjects.forEach((s, i) => {
    const angle = -Math.PI / 2 + (i / count) * Math.PI * 2;
    const rx = full ? Math.max(120, w * 0.23) : Math.max(90, w / 2 - 64);
    const ry = full ? Math.max(100, h * 0.23) : Math.max(80, h / 2 - 50);
    anchors.set(s.name, {
      x: w / 2 + Math.cos(angle) * rx,
      y: h / 2 + Math.sin(angle) * ry,
      hw: (String(s.name).length * 12.5 + 26) / 2,
      hh: 15,
    });
  });

  const nodes = raw.map((node, i) => {
    const anchor = anchors.get(node.subject || node.group) || { x: w / 2, y: h / 2 };
    const isSubject = node.type === 'subject';
    const spread = isSubject ? 0 : (full ? 200 : 76);
    const angle = (i / Math.max(1, raw.length)) * Math.PI * 2 + (node.type === 'material' ? 1.1 : 0);
    const radius = spread * (0.3 + ((i * 37) % 100) / 140);
    return { ...node, x: anchor.x + Math.cos(angle) * radius, y: anchor.y + Math.sin(angle) * radius, vx: 0, vy: 0, anchor };
  });
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const links = (data.links || []).map((l) => ({ ...l, s: byId.get(l.source), t: byId.get(l.target) }))
    .filter((l) => l.s && l.t);
  const repulse = full ? 220 : 130;
  for (let iter = 0; iter < 260; iter += 1) {
    const cooling = Math.max(0.25, 1 - iter / 300);
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const a = nodes[i];
        const b = nodes[j];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        const d2 = dx * dx + dy * dy || 0.01;
        if (d2 > repulse * repulse) continue;
        const d = Math.sqrt(d2);
        const f = (repulse * 4) / d2;
        dx = (dx / d) * f;
        dy = (dy / d) * f;
        a.vx -= dx; a.vy -= dy;
        b.vx += dx; b.vy += dy;
      }
    }
    links.forEach((l) => {
      const dx = l.t.x - l.s.x;
      const dy = l.t.y - l.s.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const rest = l.kind === 'subject' ? (full ? 110 : 72) : (full ? 90 : 58);
      const f = (d - rest) * (l.kind === 'subject' ? 0.012 : 0.02);
      l.s.vx += (dx / d) * f; l.s.vy += (dy / d) * f;
      l.t.vx -= (dx / d) * f; l.t.vy -= (dy / d) * f;
    });
    nodes.forEach((n) => {
      if (n.type === 'subject') {
        n.x = n.anchor.x; n.y = n.anchor.y; n.vx = 0; n.vy = 0;
        return;
      }
      n.vx += (n.anchor.x - n.x) * (full ? 0.03 : 0.05);
      n.vy += (n.anchor.y - n.y) * (full ? 0.03 : 0.05);
      const adx = n.x - n.anchor.x;
      const ady = n.y - n.anchor.y;
      const ad = Math.sqrt(adx * adx + ady * ady) || 0.01;
      if (ad < 74) {                       // 把节点推离科目胶囊，给标签留出空间
        n.vx += (adx / ad) * (74 - ad) * 0.05;
        n.vy += (ady / ad) * (74 - ad) * 0.05;
      }
      n.x += Math.max(-10, Math.min(10, n.vx * cooling));
      n.y += Math.max(-10, Math.min(10, n.vy * cooling));
      n.vx *= 0.8; n.vy *= 0.8;
      const pad = n.type === 'material' ? 8 : 14;
      n.x = Math.max(pad, Math.min(w - pad, n.x));
      n.y = Math.max(pad, Math.min(h - pad, n.y));
      // 避免节点压在科目胶囊上：按胶囊矩形做一次硬推离
      const hw = (n.anchor.hw || 40) + 10;
      const hh = (n.anchor.hh || 15) + 12;
      const px = n.x - n.anchor.x;
      const py = n.y - n.anchor.y;
      if (Math.abs(px) < hw && Math.abs(py) < hh) {
        const ox = hw - Math.abs(px);
        const oy = hh - Math.abs(py);
        if (oy <= ox) n.y += (py >= 0 ? 1 : -1) * oy;
        else n.x += (px >= 0 ? 1 : -1) * ox;
      }
    });
  }
  return { nodes, links, subjects, anchors, w, h, full };
}

function graphNodeRadius(n, full) {
  if (n.type === 'subject') return full ? 30 : 24;
  if (n.type === 'chapter') return full ? 8 : 7;
  return (full ? 4 : 3.2) + Math.min(3, n.weight || 1);
}

function paintGraph(ctx, layout, hovered) {
  const { w, h, nodes, links, subjects, anchors, full } = layout;
  ctx.clearRect(0, 0, w, h);

  // 每个科目一块淡色区域，先把“科目 → 章节 → 资料”的脉络圈出来
  subjects.forEach((s) => {
    const anchor = anchors.get(s.name);
    const members = nodes.filter((n) => (n.subject || n.group) === s.name && n.type !== 'subject');
    if (!anchor || members.length < 2) return;
    let maxR = 34;
    members.forEach((n) => { maxR = Math.max(maxR, Math.hypot(n.x - anchor.x, n.y - anchor.y)); });
    ctx.beginPath();
    ctx.arc(anchor.x, anchor.y, maxR + (full ? 42 : 26), 0, Math.PI * 2);
    ctx.fillStyle = hexAlpha(graphColor(s.name, subjects), 0.055);
    ctx.fill();
    ctx.setLineDash([5, 7]);
    ctx.strokeStyle = hexAlpha(graphColor(s.name, subjects), 0.22);
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.setLineDash([]);
  });

  links.forEach((l) => {
    ctx.beginPath();
    ctx.moveTo(l.s.x, l.s.y);
    ctx.lineTo(l.t.x, l.t.y);
    ctx.strokeStyle = l.kind === 'subject' ? 'rgba(120,145,180,.32)' : 'rgba(120,145,180,.2)';
    ctx.lineWidth = l.kind === 'subject' ? 1 : 0.6 + (l.weight || 1) * 0.35;
    ctx.stroke();
  });

  // 科目节点画成带全称的胶囊，颜色即图例颜色
  nodes.filter((n) => n.type === 'subject').forEach((n) => {
    ctx.font = `${full ? 15 : 12.5}px "Microsoft YaHei", sans-serif`;
    const tw = ctx.measureText(n.label).width;
    const pw = tw + (full ? 34 : 26);
    const ph = full ? 38 : 30;
    const x = n.x - pw / 2;
    const y = n.y - ph / 2;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x, y, pw, ph, ph / 2); else ctx.rect(x, y, pw, ph);
    ctx.fillStyle = n.color;
    ctx.fill();
    ctx.fillStyle = '#fff';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(n.label, n.x, n.y + 1);
    n._box = [x, y, x + pw, y + ph];
  });

  nodes.filter((n) => n.type !== 'subject').forEach((n) => {
    const r = graphNodeRadius(n, full);
    n._r = r;
    ctx.beginPath();
    ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
    ctx.fillStyle = n.type === 'chapter' ? n.color : hexAlpha(n.color, 0.55);
    ctx.fill();
    if (n.type === 'chapter') {
      ctx.strokeStyle = 'rgba(255,255,255,.85)';
      ctx.lineWidth = 1.2;
      ctx.stroke();
    }
    if (n === hovered) {
      ctx.strokeStyle = '#1b2430';
      ctx.lineWidth = 2.2;
      ctx.stroke();
    }
  });

  // 标签：全屏显示所有节点全称；常规视图只标注章节，资料靠悬停
  // 常规卡片只保留科目胶囊与圆点，名称靠悬停；全屏再显示全部节点全称
  const labelBoxes = [];
  const boxes = nodes.filter((n) => n._box).map((n) => [n._box[0] - 6, n._box[1] - 4, n._box[2] + 6, n._box[3] + 4]);
  const labeled = full ? nodes.filter((n) => n.type !== 'subject') : [];
  labeled.sort((a, b) => (a.type === b.type ? a.label.length - b.label.length : (a.type === 'chapter' ? -1 : 1)));
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  labeled.forEach((n) => {
    const text = n.label;
    ctx.font = `${n.type === 'chapter' ? (full ? 12.5 : 10.5) : (full ? 11.5 : 10)}px "Microsoft YaHei", sans-serif`;
    const tw = ctx.measureText(text).width;
    const th = full ? 16 : 13;
    const r = n._r || 5;
    const fits = (x, y) => {
      if (x < 4 || y < 4 || x + tw > w - 4 || y + th > h - 4) return false;
      const box = [x - 4, y - 3, x + tw + 4, y + th + 3];
      return !boxes.some((b) => !(box[2] < b[0] || box[0] > b[2] || box[3] < b[1] || box[1] > b[3]));
    };
    const draw = (x, y) => {
      labelBoxes.push([x - 4, y - 3, x + tw + 4, y + th + 3]);
      boxes.push([x - 4, y - 3, x + tw + 4, y + th + 3]);
      ctx.lineWidth = 3;
      ctx.strokeStyle = 'rgba(255,255,255,.95)';
      ctx.strokeText(text, x, y);
      ctx.fillStyle = n.type === 'chapter' ? '#3c4a5c' : '#6b7a8d';
      ctx.fillText(text, x, y);
    };
    const cx = n.anchor ? n.anchor.x : w / 2;
    const cy = n.anchor ? n.anchor.y : h / 2;
    const baseAngle = Math.atan2(n.y - cy, n.x - cx);
    const candidates = [];
    // 先沿“科目中心 → 节点”方向往外放，再试左右上下与斜角
    for (const dist of [r + 8, r + 26, r + 46]) {
      for (const da of [0, 0.42, -0.42]) {
        const a = baseAngle + da;
        const ux = Math.cos(a);
        const uy = Math.sin(a);
        candidates.push([n.x + ux * dist - (ux < 0 ? tw : 0), n.y + uy * dist - th / 2]);
      }
    }
    candidates.push(
      [n.x + r + 6, n.y - th / 2],
      [n.x - r - 6 - tw, n.y - th / 2],
      [n.x - tw / 2, n.y - r - th - 4],
      [n.x - tw / 2, n.y + r + 4],
    );
    let placed = false;
    for (const [x, y] of candidates) {
      if (!fits(x, y)) continue;
      draw(x, y);
      placed = true;
      break;
    }
    if (!placed) {
      // 兜底：在所有方向里挑“与其他元素重叠面积最小”的位置，尽量不遮挡
      let bestX = n.x + r + 6;
      let bestY = Math.max(4, Math.min(h - th - 4, n.y - th / 2));
      let bestScore = Infinity;
      for (let dist = r + 24; dist <= r + 150; dist += 22) {
        for (let k = 0; k < 16; k += 1) {
          const a = (k / 16) * Math.PI * 2;
          const ux = Math.cos(a);
          const uy = Math.sin(a);
          const x = n.x + ux * dist - (ux < 0 ? tw : 0);
          const y = n.y + uy * dist - th / 2;
          if (x < 4 || y < 4 || x + tw > w - 4 || y + th > h - 4) continue;
          const box = [x - 4, y - 3, x + tw + 4, y + th + 3];
          let score = 0;
          boxes.forEach((b) => {
            const ox = Math.min(box[2], b[2]) - Math.max(box[0], b[0]);
            const oy = Math.min(box[3], b[3]) - Math.max(box[1], b[1]);
            if (ox > 0 && oy > 0) score += ox * oy;
          });
          if (score < bestScore) { bestScore = score; bestX = x; bestY = y; }
          if (score === 0) break;
        }
        if (bestScore === 0) break;
      }
      draw(bestX, bestY);
    }
  });

  if (hovered) {
    const suffix = hovered.type === 'chapter' ? ' · 点击进入章节'
      : hovered.type === 'material' ? ' · 点击阅读资料'
        : hovered.type === 'subject' ? ' · 点击查看科目' : '';
    const text = (hovered.type === 'material' ? `${hovered.label}（资料）` : hovered.label) + suffix;
    ctx.font = '12px "Microsoft YaHei", sans-serif';
    const tw = ctx.measureText(text).width + 18;
    const bx = Math.min(w - tw - 6, Math.max(6, hovered.x - tw / 2));
    const by = hovered.y - 38 < 6 ? hovered.y + 16 : hovered.y - 38;
    ctx.fillStyle = 'rgba(27,36,48,.92)';
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(bx, by, tw, 24, 7); else ctx.rect(bx, by, tw, 24);
    ctx.fill();
    ctx.fillStyle = '#fff';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, bx + tw / 2, by + 12);
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
  }
}

function bindGraphHover(cv, getLayout, repaint, onOpen, idleCursor) {
  let hovered = null;
  const pick = (ev) => {
    const layout = getLayout();
    if (!layout) return null;
    const rect = cv.getBoundingClientRect();
    const mx = ev.clientX - rect.left;
    const my = ev.clientY - rect.top;
    let best = null;
    let bestD = 16;
    layout.nodes.forEach((n) => {
      if (n.type === 'subject' && n._box) {
        const b = n._box;
        if (mx >= b[0] && mx <= b[2] && my >= b[1] && my <= b[3]) { best = n; bestD = 0; return; }
      }
      const d = Math.hypot(n.x - mx, n.y - my);
      if (d < bestD) { best = n; bestD = d; }
    });
    return best;
  };
  cv.onmousemove = (ev) => {
    const best = pick(ev);
    cv.style.cursor = best ? 'pointer' : (idleCursor || 'default');
    if (best !== hovered) {
      hovered = best;
      repaint(hovered);
    }
  };
  cv.onmouseleave = () => {
    if (hovered) { hovered = null; repaint(null); }
    cv.style.cursor = idleCursor || 'default';
  };
  cv.onclick = (ev) => {
    // 触屏/直接点击不一定先触发 mousemove，这里按点击坐标重新命中一次
    const hit = pick(ev) || hovered;
    if (hit) hovered = hit;
    if (typeof onOpen === 'function') onOpen(hit);
  };
}

async function graphNavigate(node) {
  if (!node) return;
  if (node.type === 'chapter') {
    const cid = String(node.id || '').replace(/^ch:/, '');
    closeGraphFull();
    switchView('study');
    try {
      const { subjects } = await api('/api/subjects');
      for (const subject of subjects || []) {
        const chapter = (subject.chapters || []).find((c) => c.id === cid);
        if (chapter) {
          openSubject(subject);
          await openChapter(chapter);
          return;
        }
      }
      toast('没有找到对应章节，可能已被删除', true);
    } catch (err) {
      toast(`跳转失败：${err.message}`, true);
    }
    return;
  }
  if (node.type === 'material') {
    const mid = String(node.id || '').replace(/^mat:/, '');
    closeGraphFull();
    openMaterial(mid);
    return;
  }
  if (node.type === 'subject') {
    closeGraphFull();
    switchView('study');
    try {
      const { subjects } = await api('/api/subjects');
      const subject = (subjects || []).find((s) => s.name === node.label);
      if (subject) openSubject(subject);
      else toast('没有找到对应科目', true);
    } catch (err) {
      toast(`跳转失败：${err.message}`, true);
    }
  }
}

async function renderGraph() {
  const cv = $('#graph-canvas');
  if (!cv) return;
  try {
    const data = await graphFetch(true);
    const legend = $('#graph-legend');
    if (legend) legend.innerHTML = graphLegendHtml(data);
    const { ctx, w, h } = graphSize(cv, false);
    const layout = buildGraph(data, w, h, false);
    if (!layout) {
      ctx.fillStyle = '#93a1b3';
      ctx.font = '13px "Microsoft YaHei", sans-serif';
      ctx.fillText('还没有章节或资料', 16, 28);
      return;
    }
    const repaint = (hover) => paintGraph(ctx, layout, hover);
    bindGraphHover(cv, () => layout, repaint, (node) => {
      if (node) graphNavigate(node);
      else openGraphFull();
    }, 'zoom-in');
    cv._graphLayout = layout;
    repaint(null);
  } catch (err) {
    const ctx = cv.getContext('2d');
    ctx.fillStyle = '#d64545';
    ctx.font = '12px "Microsoft YaHei", sans-serif';
    ctx.fillText(`图谱渲染失败：${err && err.message}`, 12, 24);
    console.error(err);
  }
}

let graphFullLayout = null;

async function openGraphFull() {
  const box = $('#graph-full');
  const cv = $('#graph-full-canvas');
  if (!box || !cv) return;
  box.classList.remove('hidden');
  document.body.classList.add('graph-lock');
  graphFullOpen = true;
  try {
    const data = await graphFetch();
    const legend = $('#graph-legend-full');
    if (legend) legend.innerHTML = graphLegendHtml(data);
    requestAnimationFrame(() => {
      const { ctx, w, h } = graphSize(cv, true);
      graphFullLayout = buildGraph(data, w, h, true);
      if (!graphFullLayout) return;
      cv._graphLayout = graphFullLayout;
      const repaint = (hover) => paintGraph(ctx, graphFullLayout, hover);
      bindGraphHover(cv, () => graphFullLayout, repaint, (node) => {
        if (node) graphNavigate(node);
      }, 'default');
      repaint(null);
    });
  } catch (err) {
    toast(`图谱加载失败：${err.message}`, true);
  }
}

function closeGraphFull() {
  const box = $('#graph-full');
  if (!box) return;
  box.classList.add('hidden');
  document.body.classList.remove('graph-lock');
  graphFullOpen = false;
  graphFullLayout = null;
}

window.addEventListener('resize', () => {
  if (!graphFullOpen || !graphFullLayout) return;
  const cv = $('#graph-full-canvas');
  if (!cv) return;
  clearTimeout(closeGraphFull._timer);
  closeGraphFull._timer = setTimeout(() => {
    const { ctx, w, h } = graphSize(cv, true);
    graphFullLayout = buildGraph(graphData, w, h, true);
    if (!graphFullLayout) return;
    bindGraphHover(cv, () => graphFullLayout, (hover) => paintGraph(ctx, graphFullLayout, hover), (node) => {
      if (node) graphNavigate(node);
    }, 'default');
    paintGraph(ctx, graphFullLayout, null);
  }, 160);
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && graphFullOpen) closeGraphFull();
});

const graphFullBtn = $('#btn-graph-full');
if (graphFullBtn) graphFullBtn.addEventListener('click', openGraphFull);
const graphFullClose = $('#graph-full-close');
if (graphFullClose) graphFullClose.addEventListener('click', closeGraphFull);
const graphFullBox = $('#graph-full');
if (graphFullBox) {
  graphFullBox.addEventListener('click', (e) => {
    if (e.target.id === 'graph-full') closeGraphFull();
  });
}

function renderKpi(d) {
  const overall = (d.mastery && d.mastery.overall) || {};
  const usage = d.usage || {};
  const items = [
    { icon: '<svg class="line-icon" aria-hidden="true"><use href="/icons.svg#spark"></use></svg>', label: '连续学习', value: `${(d.streak && d.streak.days) || 0} 天`,
      hint: `累计 ${(d.streak && d.streak.total_days) || 0} 天有记录` },
    { icon: '<svg class="line-icon" aria-hidden="true"><use href="/icons.svg#refresh"></use></svg>', label: '待复习', value: `${d.due || 0} 条`,
      hint: d.due ? '现在就该过一遍' : '队列已清空' },
    { icon: '<svg class="line-icon" aria-hidden="true"><use href="/icons.svg#target"></use></svg>', label: '总体正确率', value: pct(overall.rate),
      hint: `${overall.correct || 0}/${overall.attempts || 0} 题` },
    { icon: '<svg class="line-icon" aria-hidden="true"><use href="/icons.svg#spark"></use></svg>', label: '近 7 天调用', value: `${usage.calls || 0} 次`,
      hint: `均首字 ${usage.avg_first_ms || 0} ms` },
    { icon: '<svg class="line-icon" aria-hidden="true"><use href="/icons.svg#folder"></use></svg>', label: '资料状态', value: `${d.pending || 0} 待审`,
      hint: d.stale ? `${d.stale} 份来源可能过期` : '来源均为最新' },
  ];
  $('#dash-kpi').innerHTML = items.map((it) => `
    <div class="kpi">
      <div class="kpi-top"><span class="kpi-icon">${it.icon}</span>
        <span class="kpi-label">${esc(it.label)}</span></div>
      <div class="kpi-value">${esc(it.value)}</div>
      <div class="kpi-hint">${esc(it.hint)}</div>
    </div>`).join('');
}

function renderRecommend(list) {
  const box = $('#dash-recommend');
  if (!list.length) { box.innerHTML = '<p class="muted small">暂无建议</p>'; return; }
  box.innerHTML = '';
  list.forEach((item) => {
    const el = document.createElement('div');
    el.className = 'recommend-item';
    const icon = { review: '<svg class="line-icon" aria-hidden="true"><use href="/icons.svg#refresh"></use></svg>', weak: '<svg class="line-icon" aria-hidden="true"><use href="/icons.svg#alert"></use></svg>', new: '<svg class="line-icon" aria-hidden="true"><use href="/icons.svg#leaf"></use></svg>', idle: '<svg class="line-icon" aria-hidden="true"><use href="/icons.svg#leaf"></use></svg>' }[item.type] || '•';
    el.innerHTML = `<div class="rec-icon">${icon}</div>
      <div class="rec-body"><b>${esc(item.title)}</b>
      <span class="muted small">${esc(item.detail || '')}</span></div>`;
    if (item.chapter_id) {
      const btn = document.createElement('button');
      btn.className = 'btn small';
      btn.textContent = '去练习';
      btn.addEventListener('click', () => {
        switchView('study');
        setTimeout(() => {
          api('/api/subjects').then(({ subjects }) => {
            for (const s of subjects) {
              const ch = s.chapters.find((c) => c.id === item.chapter_id);
              if (ch) { openSubject(s); openChapter(ch); return; }
            }
          });
        }, 200);
      });
      el.appendChild(btn);
    }
    box.appendChild(el);
  });
}

function renderReviews(list, due) {
  const badge = $('#review-due');
  if (badge) { badge.textContent = due ? `${due} 条到期` : ''; badge.className = 'badge' + (due ? ' warn' : ''); }
  const box = $('#review-box');
  if (!list.length) {
    box.innerHTML = `<div class="empty-state"><i><svg class="line-icon" aria-hidden="true"><use href="/icons.svg#check"></use></svg></i><b>今天没有到期的复习</b>
      <span>做错的题会自动排进来，间隔按 1 / 3 / 7 / 15 天递增</span></div>`;
    return;
  }
  box.innerHTML = '';
  list.forEach((r) => {
    const el = document.createElement('div');
    el.className = 'review-card';
    el.innerHTML = `<div class="review-stem">${esc(r.stem)}</div>
      <div class="meta small muted">
        ${r.subject ? `<span class="tag">${esc(r.subject)}</span>` : ''}
        ${r.chapter ? `<span class="tag">${esc(r.chapter)}</span>` : ''}
        <span>第 ${(r.stage || 0) + 1} 阶段 · 已复习 ${r.reps || 0} 次</span>
      </div>
      <details class="review-answer"><summary>看答案</summary>
        <div>${esc(r.answer || '（无答案）')}${r.note ? `<p class="muted small">${esc(r.note)}</p>` : ''}</div>
      </details>
      <div class="card-actions">
        <button class="btn small danger" data-q="again">没想起来</button>
        <button class="btn small" data-q="good">想起来了</button>
        <button class="btn small primary" data-q="easy">太简单</button>
      </div>`;
    el.querySelectorAll('[data-q]').forEach((btn) => {
      btn.addEventListener('click', () => gradeReview(r.id, btn.dataset.q, el));
    });
    box.appendChild(el);
  });
}

async function gradeReview(id, quality, el) {
  try {
    const res = await api('/api/review/grade', {
      method: 'POST', body: JSON.stringify({ id, quality }),
    });
    toast(`已记录，下次复习：${res.next}`);
    el.classList.add('done');
    setTimeout(loadDashboard, 300);
  } catch (err) { toast(err.message, true); }
}

function renderMastery(mastery) {
  const box = $('#mastery-box');
  const chapters = (mastery.chapters || []).filter((c) => c.attempts > 0 || c.read > 0 || c.status === '薄弱');
  const shown = chapters.length ? chapters : (mastery.chapters || []).slice(0, 8);
  if (!shown.length) {
    box.innerHTML = `<div class="empty-state"><i><svg class="line-icon" aria-hidden="true"><use href="/icons.svg#book"></use></svg></i><b>还没有练习记录</b>
      <span>去「科目学习」做几道题，这里会按章节显示掌握度</span></div>`;
    return;
  }
  box.innerHTML = shown.map((c) => `
    <div class="mastery-row">
      <div class="mastery-label" title="${esc(c.label)}">${esc(c.label)}</div>
      <div class="mastery-track">
        <div class="mastery-bar ${statusClass(c.status)}" style="width:${Math.max(2, Math.min(100, c.progress || 0))}%"></div>
      </div>
      <div class="mastery-rate">${pct(c.progress || 0)}</div>
      <div class="badge ${statusClass(c.status)}">${esc(c.status)}</div>
    </div>`).join('');
}

function renderUsage(usage) {
  const box = $('#usage-box');
  if (!usage.calls) {
    box.innerHTML = `<div class="empty-state"><i><svg class="line-icon" aria-hidden="true"><use href="/icons.svg#chart"></use></svg></i><b>还没有模型调用</b>
      <span>在「AI 聊天」问一个问题，这里会记录耗时与 token 估算</span></div>`;
    return;
  }
  const kinds = Object.entries(usage.by_kind || {})
    .map(([k, v]) => `<span class="tag">${esc(k)} ${v}</span>`).join('') || '<span class="muted small">还没有调用记录</span>';
  const daily = (usage.daily || []).slice(-7);
  const max = Math.max(1, ...daily.map((d) => d.calls));
  const bars = daily.map((d) => `
    <div class="usage-bar" title="${esc(d.day)}：${d.calls} 次">
      <div style="height:${Math.max(6, (d.calls / max) * 60)}px"></div>
      <span>${esc(d.day.slice(5))}</span>
    </div>`).join('') || '<span class="muted small">暂无</span>';
  box.innerHTML = `
    <div class="usage-grid">
      <div><b>${usage.calls || 0}</b><span>调用次数</span></div>
      <div><b>${usage.tokens_est || 0}</b><span>估算 token</span></div>
      <div><b>${usage.avg_first_ms || 0} ms</b><span>平均首字</span></div>
      <div><b>${usage.avg_total_ms || 0} ms</b><span>平均总耗时</span></div>
      <div><b>${usage.failed || 0}</b><span>失败次数</span></div>
    </div>
    <div class="usage-kinds">${kinds}</div>
    <div class="usage-chart">${bars}</div>`;
}

/* ---------------------------------------------------------------- 错题 → 变式题 */
async function loadMistakes() {
  const box = $('#mistake-box');
  if (!box) return;
  try {
    const { mistakes } = await api('/api/mistakes');
    if (!mistakes.length) {
      box.innerHTML = '<p class="muted small">错题本还是空的。去「科目学习」做题，答错的会自动进来。</p>';
      return;
    }
    box.innerHTML = '';
    mistakes.slice(0, 8).forEach((m) => {
      const el = document.createElement('div');
      el.className = 'mistake-row';
      el.innerHTML = `<div class="mistake-stem">${esc(m.stem)}</div>
        <div class="meta small muted">
          ${m.subject ? `<span class="tag">${esc(m.subject)}</span>` : ''}
          ${m.chapter ? `<span class="tag">${esc(m.chapter)}</span>` : ''}
          <span>你选 ${esc(m.my_answer)} · 正确 ${esc(m.right_answer)}</span>
        </div>
        <div class="card-actions">
          <button class="btn small" data-act="variant">出一道变式题</button>
        </div>`;
      el.querySelector('[data-act="variant"]').addEventListener('click', () => openVariant(m.id));
      box.appendChild(el);
    });
  } catch (err) { box.innerHTML = `<p class="muted small">加载失败：${esc(err.message)}</p>`; }
}

async function openVariant(mistakeId) {
  $('#var-sub').textContent = '正在按同一考点生成新题…';
  $('#var-body').innerHTML = '<p class="muted small">生成中，最多十几秒</p>';
  $('#modal-variant').classList.remove('hidden');
  try {
    const res = await api(`/api/mistakes/${mistakeId}/variant`, { method: 'POST', body: '{}' });
    const q = res.question || {};
    $('#var-sub').textContent = res.changed
      ? `换掉了：${res.changed}${res.saved ? '（已存入对应章节练习）' : ''}`
      : '同一个考点，换一个问法。';
    const box = $('#var-body');
    box.innerHTML = `<div class="quiz-item"><div class="stem">${esc(q.stem || '')}</div></div>`;
    const item = box.querySelector('.quiz-item');
    (q.options || []).forEach((opt, i) => {
      const letter = String.fromCharCode(65 + i);
      const row = document.createElement('div');
      row.className = 'opt';
      row.dataset.letter = letter;
      row.innerHTML = `<b>${letter}</b><span>${esc(String(opt).replace(/^[A-D][.、]\s*/, ''))}</span>`;
      row.addEventListener('click', () => {
        item.querySelectorAll('.opt').forEach((o) => {
          o.classList.remove('sel');
          if (o.dataset.letter === String(q.answer || '').toUpperCase()) o.classList.add('right');
          else if (o === row) o.classList.add('wrong');
        });
        if (!item.querySelector('.quiz-fb')) {
          const fb = document.createElement('div');
          fb.className = 'quiz-fb';
          fb.innerHTML = `正确答案 <b>${esc(q.answer || '')}</b><br/>${esc(q.explanation || '')}`;
          item.appendChild(fb);
        }
      });
      item.appendChild(row);
    });
  } catch (err) {
    $('#var-sub').textContent = '生成失败';
    $('#var-body').innerHTML = `<p class="muted small" style="color:var(--danger)">${esc(err.message)}</p>`;
  }
}

/* ---------------------------------------------------------------- 检索详情 */
function renderRetrievalDetail(wrap, data) {
  const host = wrap.querySelector('.bubble-wrap');
  if (!host) return;
  const old = host.querySelector('.retrieval-box');
  if (old) old.remove();
  const hits = data.hits || [];
  const queries = (data.queries || []).filter((q, i, arr) => arr.indexOf(q) === i);
  const topScore = Math.max(1, ...hits.map((h) => Number(h.score) || 0));
  const rows = hits.map((h) => `
    <div class="retrieval-hit">
      <div class="rh-head"><b>${esc(h.citation_id)}</b>
        <span class="tag">${esc(h.title)}</span>
        <span class="muted small">${esc(h.locator || '')} · 得分 ${esc(h.score)}</span></div>
      <div class="rh-bar"><i style="width:${Math.max(2, ((Number(h.score) || 0) / topScore) * 100)}%"></i></div>
      <div class="rh-snippet">${esc(h.snippet || '')}</div>
    </div>`).join('') || '<p class="muted small">没有命中任何片段</p>';
  const box = document.createElement('details');
  box.className = 'retrieval-box';
  const resolved = data.resolved && data.resolved !== data.query
    ? `<div class="retrieval-queries muted small">已按上文补全为：<code>${esc(data.resolved)}</code></div>` : '';
  box.innerHTML = `<summary>检索详情：命中 ${hits.length} 段 · 最高分 ${esc(data.top_score)} · 阈值 ${esc(data.threshold)}
      ${data.insufficient ? '（判定为资料不足）' : ''}${data.subject ? ' · 科目 ' + esc(data.subject) : ''}
      ${data.cached ? ' · 命中缓存' : ''}</summary>
    ${resolved}
    <div class="retrieval-queries muted small">检索式：${queries.map((q) => `<code>${esc(q)}</code>`).join(' ')}</div>
    ${rows}
    <div class="muted small">编号由服务端生成，模型只能引用这些编号；得分是本地 BM25 分数。</div>`;
  host.insertBefore(box, host.querySelector('.cite-row'));
}

/* ---------------------------------------------------------------- 全文检索 */
async function runSearch(query) {
  const box = $('#search-results');
  const q = (query || '').trim();
  if (!q) { box.innerHTML = ''; return; }
  box.innerHTML = '<p class="muted small">检索中…</p>';
  try {
    const data = await api(`/api/search?q=${encodeURIComponent(q)}&k=8`);
    if (!data.hits.length) {
      box.innerHTML = '<p class="muted small">没有命中。换个更短的关键词试试。</p>';
      return;
    }
    box.innerHTML = '';
    const queries = (data.queries || []).filter((x, i, arr) => arr.indexOf(x) === i);
    if (queries.length > 1) {
      const tip = document.createElement('p');
      tip.className = 'muted small';
      tip.innerHTML = '实际使用的检索式：' + queries.map((x) => `<code>${esc(x)}</code>`).join(' ');
      box.appendChild(tip);
    }
    data.hits.forEach((h) => {
      const el = document.createElement('div');
      el.className = 'search-hit';
      el.innerHTML = `<div class="sh-head"><b>${esc(h.title)}</b>
          <span class="tag">${esc(h.subject || '未分类')}</span>
          <span class="muted small">${esc(h.locator || '')} · ${esc(h.score)}</span></div>
        <p>${hl(h.snippet, q)}</p>
        <div class="card-actions"><button class="btn small" data-act="open">打开资料</button></div>`;
      el.querySelector('[data-act="open"]').addEventListener('click',
        () => openMaterial(h.material_id));
      box.appendChild(el);
    });
  } catch (err) {
    box.innerHTML = `<p class="muted small" style="color:var(--danger)">${esc(err.message)}</p>`;
  }
}

/* ---------------------------------------------------------------- 资料审核 / 过期 */
async function loadPending() {
  try {
    const data = await api('/api/materials/pending');
    renderPendingBar(data);
  } catch (e) { /* 看板里静默失败 */ }
}

function renderPendingBar(data) {
  const bar = $('#pending-bar');
  if (!bar) return;
  const materials = (data && data.materials) || [];
  const stale = (data && data.stale) || [];
  if (!materials.length && !stale.length) { bar.className = 'banner hidden'; return; }
  bar.className = 'banner warn';
  const parts = [];
  if (materials.length) parts.push(`<b>${materials.length} 份资料待审核</b>（审核通过前不参与检索）`);
  if (stale.length) parts.push(`<b>${stale.length} 份来源可能过期</b>（超过 30 天未重新抓取）`);
  bar.innerHTML = '<svg class="line-icon" aria-hidden="true"><use href="/icons.svg#document"></use></svg> ' + parts.join('　·　');
  if (materials.length) {
    bar.innerHTML += '<div class="pending-list"></div>';
    const list = bar.querySelector('.pending-list');
    materials.slice(0, 6).forEach((m) => {
      const el = document.createElement('div');
      el.className = 'pending-row';
      el.innerHTML = `<span>${esc(m.title)}</span>
        <button class="btn small primary" data-act="approve">通过</button>
        <button class="btn small danger" data-act="reject">驳回</button>`;
      el.querySelector('[data-act="approve"]').addEventListener('click', () => setStatus(m.id, 'approved'));
      el.querySelector('[data-act="reject"]').addEventListener('click', () => setStatus(m.id, 'rejected'));
      list.appendChild(el);
    });
  }
  if (stale.length) {
    bar.innerHTML += '<div class="pending-list"></div>';
    const list = bar.querySelectorAll('.pending-list')[bar.querySelectorAll('.pending-list').length - 1];
    stale.slice(0, 4).forEach((m) => {
      const el = document.createElement('div');
      el.className = 'pending-row';
      el.innerHTML = `<span>${esc(m.title)}</span>
        <span class="muted small">抓取于 ${esc((m.fetched_at || '').slice(0, 10) || '未知')}</span>
        <button class="btn small" data-act="refresh">重新抓取</button>`;
      el.querySelector('[data-act="refresh"]').addEventListener('click', () => refreshMaterial(m.id, el));
      list.appendChild(el);
    });
  }
}

async function setStatus(id, status) {
  try {
    await api(`/api/materials/${id}/status`, { method: 'POST', body: JSON.stringify({ status }) });
    toast(status === 'approved' ? '已通过审核，进入检索' : '已驳回，不参与检索');
    loadMaterials();
    if (state.view === 'dashboard') loadDashboard();
  } catch (err) { toast(err.message, true); }
}

async function refreshMaterial(id, el) {
  const btn = el.querySelector('[data-act="refresh"]');
  if (btn) { btn.disabled = true; btn.textContent = '抓取中…'; }
  try {
    const res = await api(`/api/materials/${id}/refresh`, { method: 'POST', body: '{}' });
    toast(res.changed ? '内容有变化，索引已更新' : '内容没有变化');
    loadMaterials();
  } catch (err) {
    toast(err.message, true);
    if (btn) { btn.disabled = false; btn.textContent = '重新抓取'; }
  }
}

/* ---------------------------------------------------------------- 费曼练习 */
function openFeynman() {
  const chapter = (typeof state !== 'undefined' && state.chapter) ? state.chapter : null;
  $('#fey-topic').value = chapter ? chapter.title : '';
  $('#fey-text').value = '';
  $('#fey-result').innerHTML = '';
  $('#modal-feynman').classList.remove('hidden');
}

async function submitFeynman() {
  const topic = $('#fey-topic').value.trim();
  const text = $('#fey-text').value.trim();
  if (!text) { $('#fey-result').innerHTML = '<p class="muted small">先写点东西再交。</p>'; return; }
  const btn = $('#fey-submit');
  btn.disabled = true; btn.textContent = '点评中…';
  $('#fey-result').innerHTML = '<p class="muted small">助教正在读你的复述…</p>';
  try {
    const res = await api('/api/feynman', {
      method: 'POST', body: JSON.stringify({ topic, text }),
    });
    let html = md(res.feedback || '');
    if ((res.citations || []).length) {
      html += '<div class="cite-row">' + res.citations.map((c) =>
        `<span class="cite-chip" title="${esc((c.snippet || '').slice(0, 200))}">${esc(c.citation_id)} · ${esc(c.title)}</span>`).join('') + '</div>';
    }
    $('#fey-result').innerHTML = html;
  } catch (err) {
    $('#fey-result').innerHTML = `<p class="muted small" style="color:var(--danger)">${esc(err.message)}</p>`;
  } finally {
    btn.disabled = false; btn.textContent = '交给助教点评';
  }
}

/* ---------------------------------------------------------------- 报告导出 */
function exportReport() { window.open('/api/export/report', '_blank'); }

/* ---------------------------------------------------------------- 事件绑定 */
const btnExport = $('#btn-export-report');
if (btnExport) btnExport.addEventListener('click', exportReport);

const searchForm = $('#search-form');
if (searchForm) {
  searchForm.addEventListener('submit', (e) => {
    e.preventDefault();
    runSearch($('#search-input').value);
  });
}

const btnFeynman = $('#btn-feynman');
if (btnFeynman) btnFeynman.addEventListener('click', openFeynman);
const feyCancel = $('#fey-cancel');
if (feyCancel) feyCancel.addEventListener('click', () => $('#modal-feynman').classList.add('hidden'));
const feySubmit = $('#fey-submit');
if (feySubmit) feySubmit.addEventListener('click', submitFeynman);
const varClose = $('#var-close');
if (varClose) varClose.addEventListener('click', () => $('#modal-variant').classList.add('hidden'));
const modalVariant = $('#modal-variant');
if (modalVariant) {
  modalVariant.addEventListener('click', (e) => {
    if (e.target.id === 'modal-variant') modalVariant.classList.add('hidden');
  });
}
