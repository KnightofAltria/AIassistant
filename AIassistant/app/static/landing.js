/* ============================================================
   主界面（粒子 / 波浪 / 科技线条）、首页背景、返回导航、
   推荐视频、个人信息页、主界面隐藏侧边栏
   依赖 app.js 的全局：$ $$ api toast esc md state switchView
   ============================================================ */
'use strict';

/* ---------------------------------------------------------------- 粒子 / 波浪场 */
/**
 * 可复用的动态背景：
 *   · 漂浮粒子 + 稀疏的距离连线（每点最多连 maxLinks 条）
 *   · 缓慢摆动的长曲线 + 点阵网格（都压得很淡）
 *   · 可选：鼠标移动时出现的水波纹（ripples）
 * 设计文档要求"简洁明快"，所以不做波纹、不做高密度装饰。
 * opts: { count, linkDist, speed, glow, grid, curves }
 */
function createField(canvas, opts) {
  const cfg = Object.assign({
    count: 90, linkDist: 140, speed: 0.32, glow: true, grid: true, curves: 2,
    ripples: false, maxLinks: 2,
  }, opts || {});

  const ctx = canvas.getContext('2d');
  let nodes = [];
  let raf = 0;
  let t = 0;
  let running = true;
  let w = 0, h = 0;
  let ripples = [];
  let lastRipple = { x: -999, y: -999 };

  function addRipple(x, y) {
    if (Math.hypot(x - lastRipple.x, y - lastRipple.y) < 16) return;   // 太密就不加
    lastRipple = { x, y };
    ripples.push({ x, y, r: 3, life: 1 });
    if (ripples.length > 24) ripples.shift();
  }

  function bindRipples() {
    if (!cfg.ripples) return;
    const host = canvas.parentElement || canvas;
    host.addEventListener('pointermove', (e) => {
      const rect = canvas.getBoundingClientRect();
      addRipple(e.clientX - rect.left, e.clientY - rect.top);
    });
    host.addEventListener('pointerdown', (e) => {
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      for (let i = 0; i < 3; i += 1) {   // 点击时来一圈更明显的
        ripples.push({ x, y, r: 3 + i * 14, life: 1 });
      }
    });
  }

  function drawRipples() {
    if (!cfg.ripples || !ripples.length) return;
    ctx.save();
    for (const rp of ripples) {
      rp.r += 2.7;
      rp.life -= 0.013;
      if (rp.life <= 0) continue;
      ctx.beginPath();
      ctx.arc(rp.x, rp.y, rp.r, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(90,150,240,${0.30 * rp.life})`;
      ctx.lineWidth = 1.6;
      ctx.stroke();

      ctx.beginPath();
      ctx.arc(rp.x, rp.y, rp.r * 0.6, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(120,195,225,${0.16 * rp.life})`;
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    ripples = ripples.filter((rp) => rp.life > 0);
    ctx.restore();
  }

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = canvas.clientWidth || canvas.parentElement.clientWidth || 800;
    h = canvas.clientHeight || canvas.parentElement.clientHeight || 600;
    canvas.width = Math.max(1, Math.round(w * dpr));
    canvas.height = Math.max(1, Math.round(h * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const scale = Math.min(1.6, Math.max(0.5, (w * h) / (1280 * 760)));
    const n = Math.round(cfg.count * scale);
    nodes = Array.from({ length: Math.max(26, n) }, () => ({
      x: Math.random() * w,
      y: Math.random() * h,
      vx: (Math.random() - 0.5) * cfg.speed,
      vy: (Math.random() - 0.5) * cfg.speed,
      r: 0.8 + Math.random() * 2.1,
      ph: Math.random() * Math.PI * 2,
      warm: Math.random() < 0.2,
    }));
  }

  function drawGrid() {
    if (!cfg.grid) return;
    const step = 46;
    ctx.save();
    for (let x = 0; x < w; x += step) {
      for (let y = 0; y < h; y += step) {
        const d = Math.hypot(x - w / 2, y - h / 2);
        ctx.globalAlpha = Math.max(0, 0.055 - d / (Math.max(w, h) * 14));
        ctx.fillStyle = '#4a7fd8';
        ctx.fillRect(x, y, 1.4, 1.4);
      }
    }
    ctx.restore();
  }

  function drawCurves() {
    if (!cfg.curves) return;
    ctx.save();
    for (let i = 0; i < cfg.curves; i += 1) {
      // 每条线有自己的生命周期：大部分时间几乎透明，偶尔浮现并轻轻跃动
      const life = 0.5 + 0.5 * Math.sin(t * 0.34 + i * 2.3 + 0.7);
      const alpha = 0.11 * Math.pow(life, 2.2);
      if (alpha < 0.004) continue;
      ctx.globalAlpha = 1;
      const off = (t * (7 + i * 4)) % (h + 240) - 120;
      ctx.beginPath();
      for (let y = -20; y <= h + 20; y += 12) {
        const x = w * (0.22 + i * 0.34)
          + Math.sin(y * 0.006 + t * 0.5 + i) * 46
          + Math.cos(y * 0.0021 - t * 0.3) * 70;
        if (y <= -20) ctx.moveTo(x, y + off); else ctx.lineTo(x, y + off);
      }
      ctx.strokeStyle = `rgba(120,170,235,${alpha.toFixed(4)})`;
      ctx.lineWidth = 1.1;
      ctx.stroke();
    }
    ctx.restore();
  }

  function frame() {
    if (!running) return;
    t += 0.016;
    ctx.clearRect(0, 0, w, h);

    drawGrid();
    drawCurves();
    drawRipples();

    for (const n of nodes) {
      // 流场驱动：每个点的方向由它所在位置的正弦/余弦叠加决定，
      // 于是整片粒子会像水流或波纹一样成束游弋，而不是各走各的直线。
      const ang = Math.sin(n.x * 0.0046 + t * 0.26)
                + Math.cos(n.y * 0.0051 - t * 0.21)
                + Math.sin((n.x + n.y) * 0.0027 + t * 0.17) * 0.6;
      const sp = cfg.speed * 1.15;
      n.x += Math.cos(ang) * sp + Math.sin(t * 0.6 + n.ph) * 0.10;
      n.y += Math.sin(ang) * sp + Math.cos(t * 0.45 + n.ph * 1.2) * 0.14;
      if (n.x < -20) n.x = w + 20;
      if (n.x > w + 20) n.x = -20;
      if (n.y < -20) n.y = h + 20;
      if (n.y > h + 20) n.y = -20;
    }

    // 连线只保留"最近的几条"：每个节点最多连 maxLinks 条，
    // 否则节点一多，两两都在阈值内，画面就糊成一片了。
    const degree = new Array(nodes.length).fill(0);
    const pairs = [];
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const dx = nodes[i].x - nodes[j].x;
        const dy = nodes[i].y - nodes[j].y;
        const d = Math.hypot(dx, dy);
        if (d < cfg.linkDist) pairs.push([d, i, j]);
      }
    }
    pairs.sort((a, b) => a[0] - b[0]);          // 优先连最近的
    for (const [d, i, j] of pairs) {
      if (degree[i] >= cfg.maxLinks || degree[j] >= cfg.maxLinks) continue;
      degree[i] += 1;
      degree[j] += 1;
      ctx.strokeStyle = `rgba(86,136,225,${0.16 * (1 - d / cfg.linkDist)})`;
      ctx.lineWidth = 0.9;
      ctx.beginPath();
      ctx.moveTo(nodes[i].x, nodes[i].y);
      ctx.lineTo(nodes[j].x, nodes[j].y);
      ctx.stroke();
    }

    if (cfg.glow) ctx.shadowBlur = 8;
    for (const n of nodes) {
      const pulse = 0.6 + 0.4 * Math.sin(t * 2 + n.ph);
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r * (0.85 + pulse * 0.35), 0, Math.PI * 2);
      ctx.fillStyle = n.warm
        ? `rgba(80,190,160,${0.42 + pulse * 0.3})`
        : `rgba(70,120,215,${0.42 + pulse * 0.35})`;
      ctx.shadowColor = n.warm ? 'rgba(80,190,160,.7)' : 'rgba(70,120,215,.7)';
      ctx.fill();
    }
    ctx.shadowBlur = 0;

    raf = requestAnimationFrame(frame);
  }

  resize();
  bindRipples();
  frame();
  const onResize = () => resize();
  window.addEventListener('resize', onResize);
  return {
    stop() {
      running = false;
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', onResize);
    },
  };
}

/* 两个背景场 */
let landingField = null;
let homeField = null;

function startHomeField() {
  if (homeField) return;
  const canvas = $('#home-particles');
  if (!canvas) return;
  homeField = createField(canvas, {
    count: 46, linkDist: 130, speed: 0.2, glow: false, grid: true, curves: 1,
    maxLinks: 2,
  });
}

function stopHomeField() {
  if (homeField) { homeField.stop(); homeField = null; }
}

/* ---------------------------------------------------------------- 视图导航栈 */
/* 每次切页都写进浏览器历史（?view=xxx），所以浏览器的前进/后退、刷新都能回到对应页面；
   navStack 只用来判断页面里的「← 返回」还有没有上一页。入栈出栈在 switchView 包装里做。 */
const navStack = [];
let historyIdx = (history.state && history.state.idx) || 0;   // 刷新后接着原来的编号

function go(view) {
  switchView(view);
}

function goHome() {
  navStack.length = 0;
  go('home');
}

function goBack() {
  if (navStack.length) history.back();   // 交给 popstate，和浏览器后退走同一条路
  else go('home');
}

function viewUrl(view) {
  const url = new URL(location.href);
  if (view === 'home') url.searchParams.delete('view');   // 主界面用干净地址，刷新会重播欢迎动画
  else url.searchParams.set('view', view);
  // 阅读页带上资料 ID（?view=reader&id=…），刷新、前进后退都能回到同一份资料
  if (view === 'reader' && state.readerId) url.searchParams.set('id', state.readerId);
  else url.searchParams.delete('id');
  return url.pathname + url.search + url.hash;
}

function recordHistory(view) {
  const target = viewUrl(view);
  if (target === location.pathname + location.search + location.hash) {
    history.replaceState({ view, idx: historyIdx }, '', target);
  } else {
    historyIdx += 1;
    history.pushState({ view, idx: historyIdx }, '', target);
  }
}

window.addEventListener('popstate', (e) => {
  const st = e.state || {};
  const view = st.view || new URLSearchParams(location.search).get('view') || 'home';
  if (!document.getElementById(`view-${view}`)) return;
  const idx = typeof st.idx === 'number' ? st.idx : 0;
  if (idx < historyIdx) navStack.pop();
  else if (state.view !== view) navStack.push(state.view);
  historyIdx = idx;
  if (view === 'reader') state.readerId = new URLSearchParams(location.search).get('id') || '';
  switchView(view, { fromHistory: true });
});

async function refreshHomeSub() {
  try {
    const st = await api('/api/state');
    const s = st.stats || {};
    $('#home-sub').textContent =
      `四个科目 · ${s.materials} 份资料 · ${s.conversations} 个对话 · ${s.mistakes} 条错题`;
  } catch (e) { /* 忽略 */ }
}

/* ---------------------------------------------------------------- 返回按钮（主界面除外） */
function injectBackBars() {
  document.querySelectorAll('.view').forEach((view) => {
    if (view.id === 'view-home') return;
    if (view.querySelector('.view-nav')) return;
    const bar = document.createElement('div');
    bar.className = 'view-nav';
    const back = document.createElement('button');
    back.className = 'btn tiny';
    back.textContent = '← 返回';
    back.addEventListener('click', goBack);
    const home = document.createElement('button');
    home.className = 'btn tiny';
    home.textContent = '⌂ 主界面';
    home.addEventListener('click', goHome);
    bar.appendChild(back);
    bar.appendChild(home);
    view.insertBefore(bar, view.firstChild);
  });
}

/* ---------------------------------------------------------------- 个人信息页 */
async function loadMeta() {
  try {
    const { meta, user, avatar } = await api('/api/profile');
    if (meta) {
      $('#meta-age').value = meta.age || '';
      $('#meta-gender').value = meta.gender || '';
      $('#meta-major').value = meta.major || '';
      $('#meta-needs').value = meta.needs || '';
    }
    renderIdentity(user || null, avatar || '');
  } catch (e) { /* 忽略 */ }
}

/* 与服务端 clean_meta 保持一致；返回空串表示通过 */
function checkMeta(meta) {
  if (meta.age && !(/^\d+$/.test(meta.age) && +meta.age >= 6 && +meta.age <= 100)) return '年龄需为 6–100 的整数';
  const limits = [['gender', '性别', 30], ['major', '专业', 30], ['needs', '学习需求', 200]];
  for (const [key, label, max] of limits) {
    if (meta[key].length > max) return `${label}最多 ${max} 个字`;
  }
  return '';
}

async function saveMeta() {
  const meta = {
    age: $('#meta-age').value.trim(),
    gender: $('#meta-gender').value.trim(),
    major: $('#meta-major').value.trim(),
    needs: $('#meta-needs').value.trim(),
  };
  // type=number 输入非数字时 value 为空串，靠 validity 区分"没填"和"填错"
  const bad = $('#meta-age').validity.badInput ? '年龄需为 6–100 的整数' : checkMeta(meta);
  $('#meta-msg').textContent = bad;
  if (bad) return;
  const btn = $('#btn-save-meta');
  btn.disabled = true; btn.textContent = '保存中…';
  try {
    await api('/api/profile/meta', { method: 'POST', body: JSON.stringify(meta) });
    toast('基本信息已保存，之后的讲解会参考它');
  } catch (err) { $('#meta-msg').textContent = err.message; toast(err.message, true); }
  finally { btn.disabled = false; btn.textContent = '保存'; }
}

function loadProfilePage() {
  loadMeta();
  renderIdentity(null);
  renderProfileInto($('#profile-panel-2'));
}

/* 档案列表：点月份看全文，可下载为 .md；默认展开最新一份 */
async function renderProfileInto(host, month) {
  const body = host.querySelector('.panel-body') || host;
  body.innerHTML = '<span class="muted small">加载中…</span>';
  try {
    const { files } = await api('/api/profile');
    body.innerHTML = '';
    $('#profile-summary-line').textContent = files.length
      ? `已有 ${files.length} 份档案：${files.map((f) => f.month).join('、')}`
      : '还没有档案，点右上角生成本月档案';
    if (!files.length) {
      body.innerHTML = '<p class="muted small">档案会依据最近的对话总结生成，按月一份，存在本地。</p>';
      return;
    }
    const current = files.some((f) => f.month === month) ? month : files[0].month;
    const pre = document.createElement('div');
    pre.className = 'profile-pre profile-doc';
    files.forEach((f) => {
      const row = document.createElement('div');
      row.className = 'profile-row clickable' + (f.month === current ? ' active' : '');
      row.title = '点击查看这个月的档案';
      row.innerHTML = `<b>${esc(f.month)}</b>
        <span class="muted small">${(f.size / 1024).toFixed(1)} KB</span>
        <span class="row-actions">
          <a class="mini-btn" href="/api/profile/${esc(f.month)}/download" download>下载</a>
          <button class="mini-btn" data-act="del">删除</button>
        </span>`;
      row.addEventListener('click', (ev) => {
        if (ev.target.closest('.row-actions')) return;
        body.querySelectorAll('.profile-row').forEach((r) => r.classList.toggle('active', r === row));
        showProfileMonth(pre, f.month);
      });
      row.querySelector('[data-act="del"]').addEventListener('click', async () => {
        if (!confirm(`删除 ${f.month} 的学习者档案？`)) return;
        try {
          await api(`/api/profile/${f.month}`, { method: 'DELETE' });
          renderProfileInto(host, current === f.month ? '' : current);
          loadProfile();
          toast('已删除档案');
        } catch (err) { toast(err.message, true); }
      });
      body.appendChild(row);
    });
    body.appendChild(pre);
    showProfileMonth(pre, current);
  } catch (err) {
    body.innerHTML = `<span class="muted">${esc(err.message)}</span>`;
  }
}

async function showProfileMonth(pre, month) {
  pre.textContent = '加载中…';
  try {
    const { content } = await api(`/api/profile/${month}`);
    pre.innerHTML = md(content);            // 档案是 markdown，按排版显示；原文可点「下载」
  } catch (err) { pre.textContent = err.message; }
}

/* ---------------------------------------------------------------- 头像上传 */
const AVATAR_MAX = 1024 * 1024;     // 与 store.AVATAR_MAX 一致
const AVATAR_SIDE = 512;            // 头像只显示几十像素，压到 512 边长足够

function loadImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('图片无法读取，可能已损坏')); };
    img.src = url;
  });
}

/* 超过 1 MB 的图片在本地缩小重编码：先按 512 边长缩放，PNG 仍超限就转 JPEG 逐步降质量 */
async function compressAvatar(file) {
  const img = await loadImage(file);
  const scale = Math.min(1, AVATAR_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
  canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
  const ctx = canvas.getContext('2d');
  const toBlob = (type, q) => new Promise((r) => canvas.toBlob(r, type, q));
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  if (file.type === 'image/png') {
    const png = await toBlob('image/png');
    if (png && png.size <= AVATAR_MAX) return png;
  }
  // JPEG 没有透明通道，先铺白底，免得透明处变黑
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  for (const q of [0.9, 0.8, 0.7, 0.6, 0.5]) {
    const jpg = await toBlob('image/jpeg', q);
    if (jpg && jpg.size <= AVATAR_MAX) return jpg;
  }
  throw new Error('图片压缩后仍超过 1 MB，请换一张');
}

async function uploadAvatar(file) {
  if (!file) return;
  if (!/^image\/(png|jpeg)$/.test(file.type)) { toast('头像只支持 PNG 或 JPG 图片', true); return; }
  if (file.size > 20 * 1024 * 1024) { toast('图片超过 20 MB，请换一张小一点的', true); return; }
  try {
    let blob = file;
    if (file.size > AVATAR_MAX) {
      toast('图片较大，正在压缩…');
      blob = await compressAvatar(file);
    }
    const dataUrl = await readFileBase64(blob);
    const res = await api('/api/profile/avatar', {
      method: 'POST', body: JSON.stringify({ content: dataUrl.split(',')[1] || '' }),
    });
    renderIdentity(null, res.avatar);
    toast(blob === file ? '头像已更新' : `头像已压缩到 ${(blob.size / 1024).toFixed(0)} KB 并更新`);
  } catch (err) { toast(err.message, true); }
}

async function resetAvatar() {
  if (!confirm('删除自定义头像，恢复为名字首字？')) return;
  try {
    await api('/api/profile/avatar', { method: 'DELETE' });
    renderIdentity(null, '');
    toast('已恢复默认头像');
  } catch (err) { toast(err.message, true); }
}

/* ---------------------------------------------------------------- 聊天：查看本对话总结 */
async function viewConversationSummary() {
  if (!state.conversationId) { toast('先选一个对话', true); return; }
  try {
    const { summaries } = await api(`/api/summaries?conversation=${state.conversationId}`);
    go('summary');
    await new Promise((r) => setTimeout(r, 150));
    const box = $('#summary-list');
    if (!summaries.length) {
      box.innerHTML = '<div class="empty"><div class="empty-icon">📄</div>'
        + '<h3>这个对话还没有总结</h3><p>点聊天页右上角「生成近期总结」</p></div>';
      return;
    }
    box.innerHTML = `<div class="banner">本对话的总结（${summaries.length} 份）</div>`;
    summaries.forEach((s) => {
      const el = document.createElement('div');
      el.className = 'card highlight';
      el.innerHTML = `<h4>${esc(s.title)}</h4><div class="meta">${esc(s.created_at)}</div>
        <div class="summary-body">${md(s.content)}</div>`;
      box.appendChild(el);
    });
    loadSummaries();
  } catch (err) { toast(err.message, true); }
}

/* ---------------------------------------------------------------- 推荐学习视频 */
async function loadChapterVideos() {
  const chapter = state.chapter;
  if (!chapter) return;
  const box = $('#chapter-videos');
  box.classList.remove('hidden');
  box.innerHTML = '<span class="muted small">正在推荐…（只给搜索关键词，不会编造视频链接）</span>';
  try {
    const { videos } = await api(`/api/chapters/${chapter.id}/videos`, { method: 'POST', body: '{}' });
    if (!videos.length) { box.innerHTML = '<span class="muted">没有拿到推荐结果，稍后再试</span>'; return; }
    box.innerHTML = '<h4>推荐学习视频</h4>';
    const list = document.createElement('div');
    list.className = 'video-list';
    videos.forEach((v) => {
      const item = document.createElement('div');
      item.className = 'video-item';
      item.innerHTML = `<a href="${esc(v.url)}" target="_blank" rel="noreferrer">▶ ${esc(v.title)}</a>
        <div class="meta"><span class="tag">${esc(v.kind)}</span>
        <span>搜索词：${esc(v.keyword)}</span></div>
        ${v.reason ? `<div class="small muted">${esc(v.reason)}</div>` : ''}`;
      list.appendChild(item);
    });
    box.appendChild(list);
    const save = document.createElement('button');
    save.className = 'btn small';
    save.textContent = '把这份清单存进本科资料';
    save.addEventListener('click', async () => {
      const text = `# ${chapter.title} 推荐视频\n\n`
        + videos.map((v) => `- [${v.kind}] ${v.title}（搜索词：${v.keyword}）\n  ${v.url}\n  推荐理由：${v.reason || '—'}`).join('\n');
      try {
        await api('/api/materials', {
          method: 'POST',
          body: JSON.stringify({
            title: `推荐视频 · ${chapter.title}`,
            text, subject: chapter.subject_name || '',
          }),
        });
        toast('已存入资料（可在资料管理里找到并打开）');
      } catch (err) { toast(err.message, true); }
    });
    box.appendChild(save);
  } catch (err) {
    box.innerHTML = `<span style="color:var(--danger)">${esc(err.message)}</span>`;
  }
}

/* ---------------------------------------------------------------- 事件绑定 */
document.addEventListener('click', (e) => {
  const goto = e.target.closest('[data-goto]');
  if (goto) { go(goto.dataset.goto); return; }
  if (e.target.id === 'btn-videos') loadChapterVideos();
});

$('#btn-view-summary').addEventListener('click', viewConversationSummary);
injectBackBars();          // 9509ae8 改启动流程时把这句漏掉了，返回按钮一直没出现
$('#btn-edit-avatar').addEventListener('click', () => $('#avatar-file').click());
$('#avatar-file').addEventListener('change', (e) => {
  uploadAvatar(e.target.files[0]);
  e.target.value = '';                 // 允许再次选同一张图
});
$('#btn-reset-avatar').addEventListener('click', resetAvatar);
$('#btn-edit-name').addEventListener('click', editDisplayName);

window.genProfileFromPage = async function genProfileFromPage() {
  const btn = $('#btn-gen-profile-2');
  if (!btn) return;
  btn.disabled = true; btn.textContent = '生成中…';
  try {
    await api('/api/profile/generate', { method: 'POST', body: '{}' });
    toast('学习者档案已更新');
    renderProfileInto($('#profile-panel-2'));
    loadProfile();
  } catch (err) { toast(err.message, true); }
  finally { btn.disabled = false; btn.textContent = '生成本月档案'; }
};
$('#btn-gen-profile-2').addEventListener('click', () => window.genProfileFromPage());
$('#btn-save-meta').addEventListener('click', saveMeta);

/* ---------------------------------------------------------------- 主界面隐藏侧边栏 + 记录浏览器历史 */
/* 所有切页（侧边栏、主界面卡片、各模块里的跳转）最终都走 switchView，在这里统一入栈、写历史 */
(function wrapSwitchView() {
  const original = window.switchView;
  if (typeof original !== 'function') return;
  window.switchView = function patchedSwitchView(view, opts) {
    const from = state.view;
    const o = opts || {};
    original(view);
    if (o.replace) {                       // 启动时的切页：不产生历史记录，也不算"上一页"
      navStack.length = 0;
      history.replaceState({ view, idx: historyIdx }, '', viewUrl(view));
    } else if (!o.fromHistory) {
      if (from && from !== view) navStack.push(from);
      if (view === 'home') navStack.length = 0;
      recordHistory(view);
    }
    const app = $('#app');
    if (app) app.classList.toggle('hide-sidebar', view === 'home');
    if (view === 'home') { startHomeField(); refreshHomeSub(); } else stopHomeField();
    if (view === 'profile') loadProfilePage();
  };
})();

/* ---------------------------------------------------------------- 启动：先放主界面 */
(function startLanding() {
  const landing = $('#landing');
  let started = false;
  let bound = false;

  // 深链接（?view=dashboard 等）：直接进目标页，不播欢迎动画，也不抢回首页
  const wantView = new URLSearchParams(location.search).get('view');
  if (wantView && document.getElementById(`view-${wantView}`)) {
    landing.classList.add('hidden');
    return;
  }

  // 粒子立刻开始跑：欢迎界面在 HTML 里就是可见的，不等接口
  landingField = createField($('#particles'), {
    count: 130, linkDist: 120, speed: 0.30, glow: true, grid: true, curves: 2,
    ripples: true, maxLinks: 1,
  });

  // 底层视图先切成主界面，避免欢迎界面淡出时看到聊天页
  const prewarm = setInterval(() => {
    if (typeof window.switchView !== 'function') return;
    clearInterval(prewarm);
    switchView('home', { replace: true });
  }, 120);

  // 再看接口：没配 Key 就把欢迎界面藏起来，让门禁页露出来
  const check = setInterval(async () => {
    try {
      const st = await api('/api/state');
      if (!st) return;
      clearInterval(check);
      if (!st.configured) {
        landing.classList.add('hidden');
        if (landingField) { landingField.stop(); landingField = null; }
        return;
      }
      showStart();
    } catch (e) { /* 等服务器 */ }
  }, 300);

  function showStart() {
    if (started) return;
    started = true;
    setTimeout(() => $('#btn-start').classList.add('show'), 1600);
    if (bound) return;
    bound = true;

    $('#btn-start').addEventListener('click', () => {
      $('#btn-start').classList.remove('show');
      landing.classList.add('fade-out');
      if (landingField) { landingField.stop(); landingField = null; }
      setTimeout(() => {
        landing.classList.add('hidden');
        landing.classList.remove('fade-out');
      }, 420);
    });
  }
})();
