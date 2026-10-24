/* ============================================================
   主界面（粒子动画）、首页、返回导航、推荐视频、个人信息页
   依赖 app.js 的全局：$ $$ api toast esc md state switchView
   ============================================================ */
'use strict';

/* ---------------------------------------------------------------- 粒子背景 */
function initParticles(canvas) {
  const ctx = canvas.getContext('2d');
  let nodes = [];
  let raf = 0;
  let running = true;

  function resize() {
    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvas.clientWidth * dpr;
    canvas.height = canvas.clientHeight * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const count = Math.min(90, Math.floor(canvas.clientWidth * canvas.clientHeight / 16000));
    nodes = Array.from({ length: Math.max(30, count) }, () => ({
      x: Math.random() * canvas.clientWidth,
      y: Math.random() * canvas.clientHeight,
      vx: (Math.random() - 0.5) * 0.28,
      vy: (Math.random() - 0.5) * 0.28,
      r: 1 + Math.random() * 1.8,
    }));
  }

  function frame() {
    if (!running) return;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    ctx.clearRect(0, 0, w, h);

    for (const n of nodes) {
      n.x += n.vx; n.y += n.vy;
      if (n.x < 0 || n.x > w) n.vx *= -1;
      if (n.y < 0 || n.y > h) n.vy *= -1;
      n.x = Math.max(0, Math.min(w, n.x));
      n.y = Math.max(0, Math.min(h, n.y));
    }
    // 连线
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const dx = nodes[i].x - nodes[j].x;
        const dy = nodes[i].y - nodes[j].y;
        const d = Math.hypot(dx, dy);
        if (d < 130) {
          ctx.strokeStyle = `rgba(90,140,230,${0.16 * (1 - d / 130)})`;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(nodes[i].x, nodes[i].y);
          ctx.lineTo(nodes[j].x, nodes[j].y);
          ctx.stroke();
        }
      }
    }
    // 点
    for (const n of nodes) {
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(70,120,215,0.55)';
      ctx.fill();
    }
    raf = requestAnimationFrame(frame);
  }

  resize();
  frame();
  window.addEventListener('resize', resize);
  return {
    stop() { running = false; cancelAnimationFrame(raf); },
  };
}

/* ---------------------------------------------------------------- 视图导航栈 */
const navStack = [];

function go(view, opts) {
  if (state.view !== view) navStack.push(state.view);
  switchView(view);
  if (view === 'profile') loadProfilePage();
  if (view === 'home') refreshHomeSub();
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

/* ---------------------------------------------------------------- 返回按钮（每个界面） */
function injectBackBars() {
  document.querySelectorAll('.view').forEach((view) => {
    if (view.id === 'view-home') return;          // 主界面本身不需要返回按钮
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
function loadProfilePage() {
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

/* 侧边栏点击时记录导航栈 */
document.querySelectorAll('.nav-item').forEach((btn) => {
  btn.addEventListener('click', () => {
    const target = btn.dataset.view;
    if (state.view !== target) go(target);
  });
});

/* ---------------------------------------------------------------- 启动：先放主界面 */
(function startLanding() {
  let landed = false;
  const check = setInterval(async () => {
    if (landed) return;
    try {
      const st = await api('/api/state');
      if (!st || !st.configured) return;          // 还没配 Key，停在门禁页
      landed = true;
      clearInterval(check);
      showLanding();
    } catch (e) { /* 等服务器 */ }
  }, 500);

  function showLanding() {
    const landing = $('#landing');
    landing.classList.remove('hidden');
    const anim = initParticles($('#particles'));
    injectBackBars();
    setTimeout(() => $('#btn-start').classList.add('show'), 1600);

    $('#btn-start').addEventListener('click', () => {
      $('#btn-start').classList.remove('show');
      landing.classList.add('fade-out');
      anim.stop();
      setTimeout(() => {
        landing.classList.add('hidden');
        landing.classList.remove('fade-out');
        goHome();
        refreshHomeSub();
      }, 420);
    });
  }
})();
