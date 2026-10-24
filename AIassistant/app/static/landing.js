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
const navStack = [];

function go(view, opts) {
  if (state.view !== view) navStack.push(state.view);
  switchView(view);
  if (view === 'profile') loadProfilePage();
  if (view === 'home') { startHomeField(); refreshHomeSub(); }
}

function goHome() {
  navStack.length = 0;
  go('home');
}

function goBack() {
  const prev = navStack.pop();
  go(prev || 'home');
}

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
    const { meta, user } = await api('/api/profile');
    if (meta) {
      $('#meta-age').value = meta.age || '';
      $('#meta-gender').value = meta.gender || '';
      $('#meta-major').value = meta.major || '';
      $('#meta-needs').value = meta.needs || '';
    }
    if (user) {
      $('#profile-name-big').textContent = user;
      $('#avatar-big').textContent = user.slice(0, 1);
    }
  } catch (e) { /* 忽略 */ }
}

async function saveMeta() {
  const btn = $('#btn-save-meta');
  btn.disabled = true; btn.textContent = '保存中…';
  try {
    await api('/api/profile/meta', {
      method: 'POST',
      body: JSON.stringify({
        age: $('#meta-age').value.trim(),
        gender: $('#meta-gender').value.trim(),
        major: $('#meta-major').value.trim(),
        needs: $('#meta-needs').value.trim(),
      }),
    });
    toast('基本信息已保存，之后的讲解会参考它');
  } catch (err) { toast(err.message, true); }
  finally { btn.disabled = false; btn.textContent = '保存'; }
}

function loadProfilePage() {
  loadMeta();
  const name = $('#profile-name').textContent;
  $('#profile-name-big').textContent = name;
  $('#avatar-big').textContent = name.slice(0, 1);
  renderProfileInto($('#profile-panel-2'));
}

async function renderProfileInto(host) {
  const body = host.querySelector('.panel-body') || host;
  body.innerHTML = '<span class="muted small">加载中…</span>';
  try {
    const { profile, files } = await api('/api/profile');
    body.innerHTML = '';
    $('#profile-summary-line').textContent = files.length
      ? `已有 ${files.length} 份档案：${files.map((f) => f.month).join('、')}`
      : '还没有档案，点右上角生成本月档案';
    if (!files.length) {
      body.innerHTML = '<p class="muted small">档案会依据最近的对话总结生成，按月一份，存在本地。</p>';
      return;
    }
    files.forEach((f) => {
      const row = document.createElement('div');
      row.className = 'profile-row';
      row.innerHTML = `<b>${esc(f.month)}</b>
        <span class="muted small">${(f.size / 1024).toFixed(1)} KB</span>
        <span class="spacer"></span>
        <button class="mini-btn" data-m="${esc(f.month)}">删除</button>`;
      row.querySelector('button').addEventListener('click', async () => {
        if (!confirm(`删除 ${f.month} 的学习者档案？`)) return;
        await api(`/api/profile/${f.month}`, { method: 'DELETE' });
        renderProfileInto(host);
        loadProfilePage();
        toast('已删除档案');
      });
      body.appendChild(row);
    });
    if (profile) {
      const pre = document.createElement('pre');
      pre.className = 'profile-pre';
      pre.textContent = profile;
      body.appendChild(pre);
    }
  } catch (err) {
    body.innerHTML = `<span class="muted">${esc(err.message)}</span>`;
  }
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
        <pre>${esc(s.content)}</pre>`;
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
$('#btn-edit-avatar').addEventListener('click', () => $('#profile-card').click());

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

/* 侧边栏点击时记录导航栈 */
document.querySelectorAll('.nav-item').forEach((btn) => {
  btn.addEventListener('click', () => {
    const target = btn.dataset.view;
    if (state.view !== target) go(target);
  });
});

/* ---------------------------------------------------------------- 主界面隐藏侧边栏 */
(function wrapSwitchView() {
  const original = window.switchView;
  if (typeof original !== 'function') return;
  window.switchView = function patchedSwitchView(view) {
    original(view);
    const app = $('#app');
    if (app) app.classList.toggle('hide-sidebar', view === 'home');
    if (view === 'home') startHomeField(); else stopHomeField();
  };
})();

/* ---------------------------------------------------------------- 启动：先放主界面 */
(function startLanding() {
  const landing = $('#landing');
  let started = false;
  let bound = false;

  // 粒子立刻开始跑：欢迎界面在 HTML 里就是可见的，不等接口
  landingField = createField($('#particles'), {
    count: 130, linkDist: 120, speed: 0.30, glow: true, grid: true, curves: 2,
    ripples: true, maxLinks: 1,
  });

  // 底层视图先切成主界面，避免欢迎界面淡出时看到聊天页
  const prewarm = setInterval(() => {
    if (typeof window.switchView !== 'function') return;
    clearInterval(prewarm);
    goHome();
    refreshHomeSub();
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
