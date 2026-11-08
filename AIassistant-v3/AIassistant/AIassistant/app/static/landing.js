/* ============================================================
   主界面（粒子 / 波浪 / 科技线条）、首页背景、返回导航、
   推荐视频、个人信息页、主界面隐藏侧边栏
   依赖 app.js 的全局：$ $$ api toast esc md state switchView
   ============================================================ */
'use strict';

/* ---------------------------------------------------------------- 粒子 / 波浪场 */
/**
 * 可复用的动态背景：
 *   · 自适应密度的漂浮粒子、距离连线与细点网格
 *   · 鼠标交互与两侧渐隐渐现的金色光纹
 * opts: { areaPerNode, minNodes, maxNodes, linkDist, maxLinks, grid }
 */
function createField(canvas, opts = {}) {
  const ctx = canvas.getContext('2d'), host = canvas.parentElement;
  const pointer = {x:0, y:0, active:false};
  let w=0,h=0,nodes=[],raf=0,last=0,t=0,stopped=false;
  function resize() {
    const dpr=Math.min(devicePixelRatio||1,2);
    w=canvas.clientWidth||800;h=canvas.clientHeight||600;
    canvas.width=w*dpr;canvas.height=h*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);
    const count=Math.min(opts.maxNodes||220,Math.max(opts.minNodes||70,Math.round(w*h/(opts.areaPerNode||6500))));
    const columns=Math.ceil(Math.sqrt(count*w/h)),rows=Math.ceil(count/columns);
    nodes=Array.from({length:count},(_,i)=>({
      x:((i%columns)+Math.random())*w/columns,y:(Math.floor(i/columns)+Math.random())*h/rows,
      phase:Math.random()*Math.PI*2,r:1+Math.random()*1.6}));
  }
  function move(e) {const r=canvas.getBoundingClientRect();pointer.x=e.clientX-r.left;pointer.y=e.clientY-r.top;pointer.active=true;}
  function leave(){pointer.active=false;}
  function gold() {
    if (!window.UIPrefs.get('gold')) return;
    ctx.save();
    ctx.lineCap='round';ctx.lineJoin='round';
    // 两侧丝带以连续曲线铺开；高光沿曲线游走，避免硬折线与方形闪点。
    const band=Math.min(160,w*.18), segments=64;
    for(let side=0;side<2;side++)for(let strand=0;strand<6;strand++){
      const phase=side*2.1+strand*.32;
      const breathe=.65+.35*Math.pow((1+Math.sin(t*.36+phase))/2,2);
      const sheen=.22+.56*(1+Math.sin(t*.22+phase))/2;
      function point(u){
        const wave=Math.sin(u*Math.PI*2.1+t*.12+side*.8);
        const fan=Math.sin(u*Math.PI);
        const inset=band*(.48+.20*wave)+strand*band*.075*fan;
        return {x:side?w-inset:inset,y:-h*.1+u*h*1.2};
      }
      const gradient=ctx.createLinearGradient(0,-h*.1,0,h*1.1);
      gradient.addColorStop(0,'rgba(125,85,30,0)');
      gradient.addColorStop(Math.max(.01,sheen-.2),`rgba(151,103,28,${.72*breathe})`);
      gradient.addColorStop(sheen,`rgba(205,151,43,${breathe})`);
      gradient.addColorStop(Math.min(.99,sheen+.19),`rgba(172,115,25,${.85*breathe})`);
      gradient.addColorStop(1,'rgba(191,149,65,0)');
      const points=Array.from({length:segments+1},(_,i)=>point(i/segments));
      // 薄纱般的金色带面，边缘收尖，中间渐宽。
      ctx.fillStyle=gradient;ctx.globalAlpha=.32;
      ctx.beginPath();
      points.forEach((p,i)=>{const edge=Math.sin(i/segments*Math.PI)*5;
        if(i===0)ctx.moveTo(p.x-edge,p.y);else ctx.lineTo(p.x-edge,p.y);});
      for(let i=segments;i>=0;i--){const p=points[i];ctx.lineTo(p.x+Math.sin(i/segments*Math.PI)*5,p.y);}
      ctx.closePath();ctx.fill();
      ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));
      ctx.strokeStyle=gradient;ctx.globalAlpha=.16;ctx.lineWidth=14;ctx.stroke();
      ctx.globalAlpha=1;ctx.lineWidth=strand%3===0?2.2:1.2;ctx.stroke();
      // 小范围柔光随高光位置滑动，无直角、无硬边闪烁。
      if(strand%2===0){
        const p=point(sheen),r=7;
        const glow=ctx.createRadialGradient(p.x,p.y,0,p.x,p.y,r);
        glow.addColorStop(0,`rgba(255,227,169,${.8*breathe})`);
        glow.addColorStop(.25,`rgba(224,175,85,${.4*breathe})`);
        glow.addColorStop(1,'rgba(224,175,85,0)');
        ctx.fillStyle=glow;ctx.fillRect(p.x-r,p.y-r,r*2,r*2);
      }
    }
    ctx.restore();
  }
  function frame(now) {
    if(stopped||document.hidden)return;
    const dt=Math.min(2,(now-last)/16.667||1);last=now;t+=dt/60;
    ctx.clearRect(0,0,w,h);
    if(opts.grid){
      ctx.fillStyle='rgba(90,132,192,.19)';ctx.beginPath();
      for(let x=21;x<w;x+=42)for(let y=21;y<h;y+=42){ctx.moveTo(x+.85,y);ctx.arc(x,y,.85,0,Math.PI*2);}
      ctx.fill();
    }
    gold();
    for(const n of nodes){
      const a=Math.sin(n.x*.005+t*.2)+Math.cos(n.y*.004-t*.15);
      n.x+=Math.cos(a)*.22*dt;n.y+=Math.sin(a)*.22*dt;
      if(pointer.active&&window.UIPrefs.get('pointer')){
        const dx=n.x-pointer.x,dy=n.y-pointer.y,d=Math.hypot(dx,dy);
        if(d<170&&d>.01){const force=(1-d/170)*1.9*dt;n.x+=dx/d*force;n.y+=dy/d*force;}
      }
      n.x=(n.x+w+12)%(w+12);n.y=(n.y+h+12)%(h+12);
    }
    for(let i=0;i<nodes.length;i++){
      const a=nodes[i];let count=0;
      const linkDist=opts.linkDist||140;
      for(let j=i+1;j<nodes.length&&count<(opts.maxLinks||2);j++){
        const b=nodes[j],d=Math.hypot(a.x-b.x,a.y-b.y);
        if(d>linkDist)continue;count++;
        ctx.strokeStyle=`rgba(86,136,225,${.22*(1-d/linkDist)})`;ctx.lineWidth=.7;
        ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();
      }
      const d=pointer.active&&window.UIPrefs.get('pointer')?Math.hypot(a.x-pointer.x,a.y-pointer.y):999;
      ctx.fillStyle=`rgba(74,124,206,${d<170?.75:.32+.12*Math.sin(t+a.phase)})`;
      ctx.beginPath();ctx.arc(a.x,a.y,a.r,0,Math.PI*2);ctx.fill();
      if(d<140){ctx.strokeStyle=`rgba(92,152,226,${.2*(1-d/140)})`;ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(pointer.x,pointer.y);ctx.stroke();}
    }
    raf=requestAnimationFrame(frame);
  }
  function visibility(){cancelAnimationFrame(raf);if(!document.hidden&&!stopped){last=performance.now();raf=requestAnimationFrame(frame);}}
  resize();raf=requestAnimationFrame(frame);
  host.addEventListener('pointermove',move);host.addEventListener('pointerleave',leave);
  window.addEventListener('resize',resize);document.addEventListener('visibilitychange',visibility);
  return {stop(){stopped=true;cancelAnimationFrame(raf);ctx.clearRect(0,0,w,h);
    host.removeEventListener('pointermove',move);host.removeEventListener('pointerleave',leave);
    window.removeEventListener('resize',resize);document.removeEventListener('visibilitychange',visibility);}};
}

/* 两个背景场 */
let landingField = null;
let homeField = null;

function startHomeField() {
  if (homeField || !window.UIPrefs.motion()) return;
  const canvas = $('#home-particles');
  if (!canvas) return;
  homeField = createField(canvas, {
    areaPerNode: 6500, minNodes: 70, maxNodes: 220, linkDist: 130, grid: true,
    maxLinks: 2,
  });
}

function stopHomeField() {
  if (homeField) { homeField.stop(); homeField = null; }
}

/* ---------------------------------------------------------------- 视图导航 */
/* 浏览器历史用于前进/后退与刷新；页内返回按功能层级导航。 */
let historyIdx = (history.state && history.state.idx) || 0;   // 刷新后接着原来的编号
const readerTrail = [];

function rememberReaderOrigin(id) {
  if (state.view === 'reader' && state.readerId === id) return;
  readerTrail.push({view: state.view, readerId: state.readerId, folderId: state.folderId,
                    subject: state.subject, chapter: state.chapter});
}

function go(view) {
  switchView(view);
}

function goHome() {
  go('home');
}

function goBack() {
  if (state.view === 'study') {
    if (state.chapter && state.subject) { openSubject(state.subject); return; }
    if (state.subject) { loadSubjects(); return; }
  }
  if (state.view === 'reader') {
    const previous = readerTrail.pop();
    if (previous) {
      Object.assign(state, previous);
      switchView(previous.view, {restore: true});
    } else switchView('materials', {restore: true});
    return;
  }
  if (state.view === 'materials' && state.folderId) {
    state.folderId = ''; loadMaterials(); return;
  }
  if (state.view === 'chat' && state.conversationId) {
    $('#btn-new-chat').click(); return;
  }
  goHome();
}

function viewUrl(view) {
  const url = new URL(location.href);
  if (view === 'home') url.searchParams.delete('view');   // 主界面用干净地址，重新打开先选择账号
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
      $('#meta-bio').value = meta.bio || '';
      $('#profile-desc').textContent = meta.bio || '写一句话介绍自己';
    }
    renderIdentity(user || null, avatar || '');
  } catch (e) { /* 忽略 */ }
}

/* 与服务端 clean_meta 保持一致；返回空串表示通过 */
function checkMeta(meta) {
  if (meta.age && !(/^\d+$/.test(meta.age) && +meta.age >= 6 && +meta.age <= 100)) return '年龄需为 6–100 的整数';
  const limits = [['gender', '性别', 30], ['major', '专业', 30], ['needs', '学习需求', 200], ['bio', '个人简介', 200]];
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
    bio: $('#meta-bio').value.trim(),
  };
  // type=number 输入非数字时 value 为空串，靠 validity 区分"没填"和"填错"
  const bad = $('#meta-age').validity.badInput ? '年龄需为 6–100 的整数' : checkMeta(meta);
  $('#meta-msg').textContent = bad;
  if (bad) return;
  const btn = $('#btn-save-meta');
  btn.disabled = true; btn.textContent = '保存中…';
  try {
    await api('/api/profile/meta', { method: 'POST', body: JSON.stringify(meta) });
    $('#profile-desc').textContent = meta.bio || '写一句话介绍自己';
    toast('个人信息已保存');
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
    let blob = await window.chooseAvatarCrop(file);
    if (!blob) return;
    if (blob.size > AVATAR_MAX) blob = await compressAvatar(blob);
    const dataUrl = await readFileBase64(blob);
    const res = await api('/api/profile/avatar', {
      method: 'POST', body: JSON.stringify({ content: dataUrl.split(',')[1] || '' }),
    });
    renderIdentity(null, res.avatar);
    toast('选中的头像区域已保存');
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
      box.innerHTML = '<div class="empty"><div class="empty-icon"><svg class="line-icon" aria-hidden="true"><use href="/icons.svg#document"></use></svg></div>'
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

const avatarDrop = $('#avatar-big');
avatarDrop.addEventListener('click', () => $('#avatar-file').click());
avatarDrop.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $('#avatar-file').click(); } });
['dragenter', 'dragover'].forEach((event) => avatarDrop.addEventListener(event, (e) => { e.preventDefault(); avatarDrop.classList.add('dragging'); }));
['dragleave', 'drop'].forEach((event) => avatarDrop.addEventListener(event, (e) => { e.preventDefault(); avatarDrop.classList.remove('dragging'); }));
avatarDrop.addEventListener('drop', (e) => uploadAvatar(e.dataTransfer.files[0]));

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
/* 所有切页（侧边栏、主界面卡片、各模块里的跳转）最终都走 switchView，在这里统一写历史 */
(function wrapSwitchView() {
  const original = window.switchView;
  if (typeof original !== 'function') return;
  window.switchView = function patchedSwitchView(view, opts) {
    const o = opts || {};
    if (view !== 'reader' && !o.restore) readerTrail.length = 0;
    if (view === 'materials' && !o.restore && !o.fromHistory) state.folderId = '';
    original(view, o);
    if (o.replace) {                       // 启动时的切页：不产生历史记录，也不算"上一页"
      history.replaceState({ view, idx: historyIdx }, '', viewUrl(view));
    } else if (!o.fromHistory) {
      recordHistory(view);
    }
    const app = $('#app');
    if (app) app.classList.toggle('hide-sidebar', view === 'home');
    if (view === 'home') { window.refreshHomeTitle(); startHomeField(); refreshHomeSub(); } else stopHomeField();
    if (view === 'profile') loadProfilePage();
  };
})();

/* 启动入口统一由 boot 与账号选择页控制，欢迎动画不自动显示。 */

function syncHomeMotion() { stopHomeField(); if (state.view === 'home' && !$('#app').classList.contains('hidden')) startHomeField(); }
window.addEventListener('csla:preferences', syncHomeMotion);
matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', syncHomeMotion);
