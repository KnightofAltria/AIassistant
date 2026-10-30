/* ============================================================
   计算机课程学习助手 —— 前端逻辑（原生 JS，无框架、无构建）
   ============================================================ */
'use strict';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  view: 'chat',
  conversationId: '',
  subject: null,
  chapter: null,
  folderId: '',
  streaming: false,
};

/* ---------------------------------------------------------------- 工具 */
function toast(msg, isError) {
  const el = $('#toast');
  el.textContent = msg;
  el.className = 'toast' + (isError ? ' err' : '');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add('hidden'), 2600);
}

async function api(path, options) {
  const res = await fetch(path, Object.assign({ headers: { 'Content-Type': 'application/json' } },
    options || {}));
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = { raw: text }; }
  if (!res.ok) {
    const msg = (data && data.error && data.error.message) || `请求失败（${res.status}）`;
    throw new Error(msg);
  }
  return data;
}

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* 轻量 markdown：标题、粗体、行内代码、代码块、列表、引用 */
function md(text) {
  let s = esc(text || '');
  s = s.replace(/```([\s\S]*?)```/g, (m, code) => `<pre class="code">${code.trim()}</pre>`);
  s = s.replace(/^###### (.*)$/gm, '<h6>$1</h6>')
       .replace(/^##### (.*)$/gm, '<h5>$1</h5>')
       .replace(/^#### (.*)$/gm, '<h4>$1</h4>')
       .replace(/^### (.*)$/gm, '<h3>$1</h3>')
       .replace(/^## (.*)$/gm, '<h2>$1</h2>')
       .replace(/^# (.*)$/gm, '<h1>$1</h1>');
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
  s = s.replace(/^\s*[-*] (.*)$/gm, '<li>$1</li>');
  s = s.replace(/(<li>[\s\S]*?<\/li>)/g, '<ul>$1</ul>');
  s = s.replace(/^&gt; (.*)$/gm, '<blockquote>$1</blockquote>');
  return s;
}

/* ---------------------------------------------------------------- SSE 流 */
async function streamSSE(path, payload, handlers) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    let msg = `请求失败（${res.status}）`;
    try { const d = await res.json(); msg = (d.error && d.error.message) || msg; } catch (e) {}
    throw new Error(msg);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buf = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const raw = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = 'message';
      const dataLines = [];
      raw.split('\n').forEach((line) => {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
      });
      if (!dataLines.length) continue;
      let data = {};
      try { data = JSON.parse(dataLines.join('\n')); } catch (e) { continue; }
      if (handlers[event]) handlers[event](data);
    }
  }
}

/* ---------------------------------------------------------------- 启动 */
async function boot() {
  const st = await api('/api/state');
  if (!st.configured) {
    $('#gate').classList.remove('hidden');
    $('#app').classList.add('hidden');
    if (st.mock) { $('#gate-msg').textContent = '当前服务以 --mock 离线演示模式启动，可直接进入。'; $('#gate-msg').classList.add('ok'); }
    return;
  }
  enterApp(st);
}

function enterApp(st) {
  $('#gate').classList.add('hidden');
  $('#app').classList.remove('hidden');
  $('#brand-sub').textContent = st.mock ? '离线演示模式' : (st.model || 'deepseek-chat');
  $('#profile-name').textContent = (st.user && st.user.name) || '本机用户';
  renderStats(st.stats);
  loadProfile();
  switchView('chat');
  loadConversations();
}

function renderStats(stats) {
  if (!stats) return;
  $('#mini-stats').innerHTML =
    `资料 ${stats.materials} 份 · 切片 ${stats.chunks}<br/>对话 ${stats.conversations} · 总结 ${stats.summaries} · 错题 ${stats.mistakes}`;
}

async function loadProfile() {
  const { profile } = await api('/api/profile');
  if (profile) {
    $('#profile-desc').textContent = profile.replace(/[#*`>-]/g, '').split('\n').filter(Boolean)[0] || '已生成画像';
    $('#profile-desc').title = profile;
  }
}

/* ---------------------------------------------------------------- 门禁 */
$('#gate-submit').addEventListener('click', async () => {
  const key = $('#gate-key').value.trim();
  const model = $('#gate-model').value;
  const msg = $('#gate-msg');
  if (!key) { msg.className = 'gate-msg'; msg.textContent = '请填写 API Key（或让服务端以 --mock 启动）'; return; }
  msg.className = 'gate-msg';
  msg.textContent = '正在校验…';
  try {
    await api('/api/config', { method: 'POST', body: JSON.stringify({ api_key: key, model }) });
    msg.className = 'gate-msg ok';
    msg.textContent = '校验通过，正在进入…';
    setTimeout(boot, 300);
  } catch (err) {
    msg.className = 'gate-msg';
    msg.textContent = err.message;
  }
});
$('#gate-key').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('#gate-submit').click(); });

/* ---------------------------------------------------------------- 导航 */
function switchView(view) {
  state.view = view;
  $$('.nav-item').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
  $$('.view').forEach((v) => v.classList.toggle('active', v.id === `view-${view}`));
  if (view === 'summary') loadSummaries();
  if (view === 'study') loadSubjects();
  if (view === 'materials') loadMaterials();
  if (view === 'dashboard' && typeof loadDashboard === 'function') loadDashboard();
}

$$('.nav-item').forEach((btn) => btn.addEventListener('click', () => switchView(btn.dataset.view)));

$('#btn-collapse').addEventListener('click', () => {
  $('#sidebar').classList.add('collapsed');
  $('#btn-expand').classList.remove('hidden');
});
$('#btn-expand').addEventListener('click', () => {
  $('#sidebar').classList.remove('collapsed');
  $('#btn-expand').classList.add('hidden');
});

$('#profile-card').addEventListener('click', async () => {
  const name = prompt('自定义显示名（头像取首字）', $('#profile-name').textContent);
  if (!name) return;
  $('#profile-name').textContent = name;
  $('#avatar').textContent = name.slice(0, 1);
  toast('已更新显示名（仅本次界面生效）');
});

/* ---------------------------------------------------------------- 设置 */
function openModal(sel) { $(sel).classList.remove('hidden'); }
function closeModal(sel) { $(sel).classList.add('hidden'); }

$('#btn-settings').addEventListener('click', async () => {
  const st = await api('/api/state');
  $('#set-mask').textContent = st.masked_key || (st.mock ? '离线演示模式' : '未设置');
  $('#set-model').value = st.model || 'deepseek-chat';
  $('#set-msg').textContent = '';
  openModal('#modal-settings');
});
$('#set-cancel').addEventListener('click', () => closeModal('#modal-settings'));
$('#set-save').addEventListener('click', async () => {
  const key = $('#set-key').value.trim();
  if (!key) { $('#set-msg').textContent = '请填写新的 Key'; return; }
  try {
    await api('/api/config', { method: 'POST', body: JSON.stringify({ api_key: key, model: $('#set-model').value }) });
    $('#set-msg').textContent = '已保存';
    toast('API Key 已更新');
    setTimeout(() => { closeModal('#modal-settings'); boot(); }, 500);
  } catch (err) { $('#set-msg').textContent = err.message; }
});

/* ---------------------------------------------------------------- 聊天 */
async function loadConversations() {
  const { conversations } = await api('/api/conversations');
  const box = $('#conv-list');
  box.innerHTML = '';
  conversations.forEach((c) => {
    const el = document.createElement('div');
    el.className = 'conv-item' + (c.id === state.conversationId ? ' active' : '');
    el.innerHTML = `<span>${esc(c.title)}</span><b class="conv-del" title="删除">×</b>`;
    el.addEventListener('click', (ev) => {
      if (ev.target.classList.contains('conv-del')) { delConversation(c.id); return; }
      openConversation(c.id);
    });
    box.appendChild(el);
  });
}

async function openConversation(id) {
  state.conversationId = id;
  $$('.conv-item').forEach((el) => el.classList.remove('active'));
  const { messages } = await api(`/api/conversations/${id}/messages`);
  const box = $('#messages');
  box.innerHTML = '';
  if (!messages.length) box.innerHTML = '<div class="empty"><p>这个对话还没有消息</p></div>';
  messages.forEach((m) => appendMessage(m.role, m.content, m.citations));
  loadConversations();
}

async function delConversation(id) {
  if (!confirm('删除这个对话？不可恢复。')) return;
  await api(`/api/conversations/${id}`, { method: 'DELETE' });
  if (state.conversationId === id) { state.conversationId = ''; $('#messages').innerHTML = ''; }
  loadConversations();
  toast('已删除对话');
}

$('#btn-new-chat').addEventListener('click', () => {
  state.conversationId = '';
  $('#messages').innerHTML =
    `<div class="empty" id="chat-empty"><div class="empty-icon">💬</div><h3>开始提问吧</h3>
     <p>比如「TCP 为什么需要三次握手」<br/>先在「资料管理」导入课件，回答就会带出处</p></div>`;
  loadConversations();
});

function appendMessage(role, text, citations) {
  const empty = $('#chat-empty');
  if (empty) empty.remove();
  const box = $('#messages');
  const wrap = document.createElement('div');
  wrap.className = `msg ${role}`;
  const avatar = role === 'user' ? '我' : 'AI';
  wrap.innerHTML = `<div class="avatar-s">${avatar}</div>
    <div class="bubble-wrap"><div class="who">${role === 'user' ? '你' : '助手'}</div>
    <div class="bubble"></div></div>`;
  const bubble = wrap.querySelector('.bubble');
  bubble.innerHTML = md(text || '');
  if (citations && citations.length) {
    const row = document.createElement('div');
    row.className = 'cite-row';
    citations.forEach((c) => {
      const chip = document.createElement('span');
      chip.className = 'cite-chip';
      chip.textContent = `${c.citation_id} · ${c.title}`;
      chip.title = (c.snippet || '').slice(0, 200);
      row.appendChild(chip);
    });
    wrap.querySelector('.bubble-wrap').appendChild(row);
  }
  box.appendChild(wrap);
  box.scrollTop = box.scrollHeight;
  return { wrap, bubble };
}

$('#chat-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  if (state.streaming) return;
  const input = $('#chat-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  input.style.height = 'auto';
  appendMessage('user', text);
  const { wrap, bubble } = appendMessage('assistant', '');
  bubble.classList.add('typing');
  const statusLine = document.createElement('div');
  statusLine.className = 'status-line';
  statusLine.textContent = '检索资料中…';
  wrap.querySelector('.bubble-wrap').appendChild(statusLine);

  state.streaming = true;
  let acc = '';
  const styleSel = $('#chat-style');
  try {
    await streamSSE('/api/chat/stream', {
      text, conversation_id: state.conversationId,
      style: (styleSel && styleSel.value) || 'concise',
    }, {
      status(d) {
        if (d.stage === 'retrieving') {
          statusLine.textContent = d.hits ? `找到 ${d.hits} 段相关资料${d.insufficient ? '（可能不足）' : ''}` : '未找到相关资料，将基于通用知识回答';
        } else if (d.stage === 'verifying') statusLine.textContent = '校验引用…';
        if (d.conversation_id) state.conversationId = d.conversation_id;
      },
      retrieval(d) {
        if (typeof renderRetrievalDetail === 'function') renderRetrievalDetail(wrap, d);
      },
      delta(d) {
        acc += d.text || '';
        bubble.innerHTML = md(acc);
        $('#messages').scrollTop = $('#messages').scrollHeight;
      },
      citations(d) {
        statusLine.textContent = d.passed ? '引用校验通过' : `有 ${d.invalid.length} 个无法识别的引用编号`;
        const row = document.createElement('div');
        row.className = 'cite-row';
        (d.items || []).forEach((c) => {
          const chip = document.createElement('span');
          chip.className = 'cite-chip' + (d.passed ? '' : ' bad');
          chip.textContent = `${c.citation_id} · ${c.title}`;
          chip.title = (c.snippet || '').slice(0, 220);
          row.appendChild(chip);
        });
        if (row.children.length) wrap.querySelector('.bubble-wrap').appendChild(row);
      },
      completed() { loadConversations(); },
      failed(d) { throw new Error(d.message || '生成失败'); },
    });
  } catch (err) {
    bubble.classList.remove('typing');
    statusLine.textContent = '请求失败：' + err.message;
    toast(err.message, true);
  } finally {
    bubble.classList.remove('typing');
    state.streaming = false;
    if (!acc) bubble.innerHTML = '<span class="muted">（没有返回内容）</span>';
  }
});

const chatInput = $('#chat-input');
chatInput.addEventListener('input', () => {
  chatInput.style.height = 'auto';
  chatInput.style.height = Math.min(chatInput.scrollHeight, 160) + 'px';
});
chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#chat-form').requestSubmit(); }
});

$('#btn-summarize').addEventListener('click', async () => {
  if (!state.conversationId) { toast('先选择一个有内容的对话', true); return; }
  const btn = $('#btn-summarize');
  btn.disabled = true; btn.textContent = '生成中…';
  try {
    await api('/api/summaries/generate', {
      method: 'POST', body: JSON.stringify({ conversation_id: state.conversationId }),
    });
    toast('已生成近期总结');
    const st = await api('/api/state');
    renderStats(st.stats);
  } catch (err) { toast(err.message, true); }
  finally { btn.disabled = false; btn.textContent = '生成近期总结'; }
});

/* ---------------------------------------------------------------- 近期总结 */
const KIND_LABEL = { recent: '对话总结', chapter: '章节小结', tips: '易错提示本' };

function openSummary(s) {
  $('#sumv-title').textContent = s.title || '总结';
  $('#sumv-meta').textContent = `${KIND_LABEL[s.kind] || s.kind} · ${s.created_at}`;
  // 渲染成易读的排版（标题/列表/表格），不把 markdown 原文甩给用户
  $('#sumv-body').innerHTML = md(s.content || '');
  $('#modal-summary-view').classList.remove('hidden');
  $('#sumv-close').onclick = () => $('#modal-summary-view').classList.add('hidden');
  $('#modal-summary-view').onclick = (e) => {
    if (e.target.id === 'modal-summary-view') $('#modal-summary-view').classList.add('hidden');
  };
}
async function loadSummaries() {
  const { summaries } = await api('/api/summaries');
  const box = $('#summary-list');
  box.innerHTML = '';
  if (!summaries.length) {
    box.innerHTML = '<div class="empty"><div class="empty-icon">📄</div><h3>还没有总结</h3><p>在「AI 聊天」里点「生成近期总结」</p></div>';
    return;
  }
  summaries.forEach((s) => {
    const el = document.createElement('div');
    el.className = 'card summary-card-item';
    const firstLine = (s.content || '').replace(/[#*`>-]/g, '').split('\n').map((x) => x.trim()).filter(Boolean)[0] || '';
    el.innerHTML = `<h4>${esc(s.title)}</h4>
      <div class="meta">${esc(s.created_at)} · ${KIND_LABEL[s.kind] || s.kind}</div>
      <p class="summary-preview">${esc(firstLine.slice(0, 90))}…</p>
      <div class="card-actions">
        <button class="btn" data-act="open">放大查看</button>
        <button class="btn danger" data-act="del">删除</button>
      </div>`;
    el.querySelector('[data-act="open"]').addEventListener('click', () => openSummary(s));
    el.querySelector('h4').addEventListener('click', () => openSummary(s));
    el.querySelector('[data-act="del"]').addEventListener('click', async (ev) => {
      ev.stopPropagation();
      if (!confirm('删除这份总结？')) return;
      await api(`/api/summaries/${s.id}`, { method: 'DELETE' });
      loadSummaries(); toast('已删除');
    });
    box.appendChild(el);
  });
}

/* ---------------------------------------------------------------- 科目学习 */
const SUBJECT_EMOJI = { co: '🖥️', cn: '🌐', os: '⚙️', ds: '🌳' };

async function loadSubjects() {
  const { subjects } = await api('/api/subjects');
  const grid = $('#subject-grid');
  grid.innerHTML = '';
  subjects.forEach((s) => {
    const el = document.createElement('div');
    el.className = 'subject-card';
    const badge = s.is_builtin
      ? '<span class="badge builtin">内置</span>'
      : '<span class="badge custom">自定义</span>';
    el.innerHTML = `<div class="subject-emoji">${SUBJECT_EMOJI[s.slug] || '📘'}</div>
      <h3>${esc(s.name)} ${badge}</h3><p>${s.chapters.length} 个章节</p>
      <div class="card-actions"><button class="btn small" data-act="enter">进入</button>${
        s.is_builtin ? '' : '<button class="btn danger small" data-act="del">删除科目</button>'}</div>`;
    el.querySelector('[data-act="enter"]').addEventListener('click', (ev) => {
      ev.stopPropagation(); openSubject(s);
    });
    const del = el.querySelector('[data-act="del"]');
    if (del) del.addEventListener('click', (ev) => {
      ev.stopPropagation(); deleteSubject(s);
    });
    grid.appendChild(el);
  });
  $('#subject-grid').classList.remove('hidden');
  $('#chapter-list').classList.add('hidden');
  $('#chapter-detail').classList.add('hidden');
  $('#btn-study-back').classList.add('hidden');
  $('.composer.floating').classList.add('hidden');
  $('#study-title').textContent = '科目学习';
  $('#study-sub').textContent = '选择科目与章节，先看讲解再做题';
}

function openSubject(subject) {
  state.subject = subject;
  $('#subject-grid').classList.add('hidden');
  const list = $('#chapter-list');
  list.classList.remove('hidden');
  list.innerHTML = '';
  subject.chapters.forEach((c) => {
    const el = document.createElement('div');
    el.className = 'chapter-item';
    const badge = c.is_builtin ? '<span class="badge builtin">内置</span>' : '';
    el.innerHTML = `<h4>${esc(c.title)} ${badge}</h4>
      <p>${esc((c.outline || '').split('\n')[0].replace(/^-\s*/, '')) || '点击进入'}</p>
      <div class="card-actions">
        <button class="btn small" data-act="open">进入</button>
        <button class="btn small" data-act="edit">编辑</button>
        <button class="btn danger small" data-act="del">删除章节</button>
      </div>`;
    el.querySelector('[data-act="open"]').addEventListener('click', (ev) => {
      ev.stopPropagation(); openChapter(c);
    });
    el.querySelector('[data-act="edit"]').addEventListener('click', (ev) => {
      ev.stopPropagation(); editChapter(subject, c);
    });
    el.querySelector('[data-act="del"]').addEventListener('click', (ev) => {
      ev.stopPropagation(); deleteChapter(subject, c);
    });
    list.appendChild(el);
  });
  $('#btn-study-back').classList.remove('hidden');
  $('#study-title').textContent = subject.name;
  $('#study-sub').textContent = '选择一个章节开始';
}

$('#btn-study-back').addEventListener('click', () => {
  if (state.chapter) { state.chapter = null; openSubject(state.subject); }
  else loadSubjects();
  $('#btn-study-back').classList.add('hidden');
});

async function openChapter(chapter) {
  state.chapter = chapter;
  $('#chapter-list').classList.add('hidden');
  const box = $('#chapter-detail');
  box.classList.remove('hidden');
  box.innerHTML = `
    <div class="outline-box">
      <h4>${esc(chapter.title)} · 大纲</h4>
      <div class="body">${esc(chapter.outline || '（暂无大纲）')}</div>
      <div class="card-actions">
        <button id="btn-tutor" class="btn primary">生成讲解</button>
        <button id="btn-chap-summary" class="btn">本章小结</button>
        <button id="btn-videos" class="btn">推荐学习视频</button>
        <span id="chap-stats" class="muted small"></span>
      </div>
      <div id="tutor-body" class="body" style="margin-top:12px"></div>
      <div id="chapter-summary" class="chapter-summary hidden"></div>
      <div id="chapter-videos" class="chapter-videos hidden"></div>
    </div>
    <div class="qa-box">
      <h4>章节练习</h4>
      <div class="card-actions" style="margin-bottom:10px">
        <button id="btn-gen-q" class="btn">生成 3 道题</button>
        <button id="btn-reload-q" class="btn">刷新</button>
      </div>
      <div id="quiz" class="quiz"></div>
    </div>`;
  $('#btn-study-back').classList.remove('hidden');
  $('#study-sub').textContent = chapter.title;
  if (chapter.outline && chapter.outline.includes('##')) {
    $('#tutor-body').innerHTML = md(chapter.outline);
  }
  $('.composer.floating').classList.remove('hidden');

  $('#btn-tutor').addEventListener('click', () => generateTutor(chapter));
  $('#btn-chap-summary').addEventListener('click', () => generateChapterSummary(chapter.id));
  api(`/api/chapters/${chapter.id}`).then((d) => {
    if (d.stats) {
      $('#chap-stats').textContent = d.stats.visited
        ? `已作答 ${d.stats.attempts} 题，正确率 ${d.stats.rate}%`
        : `本章共 ${d.stats.questions} 道题`;
    }
  }).catch(() => {});
  $('#btn-gen-q').addEventListener('click', () => generateQuestions(chapter));
  $('#btn-reload-q').addEventListener('click', () => loadQuestions(chapter));
  loadQuestions(chapter);
  box.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function generateTutor(chapter) {
  const body = $('#tutor-body');
  const btn = $('#btn-tutor');
  btn.disabled = true; btn.textContent = '生成中…';
  body.textContent = '';
  let acc = '';
  try {
    await streamSSE(`/api/chapters/${chapter.id}/tutor`, {}, {
      delta(d) { acc += d.text || ''; body.innerHTML = md(acc); },
      failed(d) { throw new Error(d.message || '生成失败'); },
    });
    chapter.outline = acc;
  } catch (err) { toast(err.message, true); }
  finally { btn.disabled = false; btn.textContent = '重新生成讲解'; }
}

async function loadQuestions(chapter) {
  const { questions } = await api(`/api/chapters/${chapter.id}`);
  const box = $('#quiz');
  box.innerHTML = '';
  if (!questions.length) {
    box.innerHTML = '<p class="muted small">本章还没有题目，点「生成 3 道题」。</p>';
    return;
  }
  questions.forEach((q, i) => {
    const el = document.createElement('div');
    el.className = 'quiz-item';
    el.innerHTML = `<div class="stem">${i + 1}. ${esc(q.stem)}</div>`;
    q.options.forEach((opt, oi) => {
      const letter = String.fromCharCode(65 + oi);
      const row = document.createElement('div');
      row.className = 'opt';
      row.dataset.letter = letter;
      row.innerHTML = `<b>${letter}</b><span>${esc(String(opt).replace(/^[A-D][.、]\s*/, ''))}</span>`;
      row.addEventListener('click', async () => {
        if (el.dataset.answered) return;
        el.dataset.answered = '1';
        el.querySelectorAll('.opt').forEach((o) => o.classList.remove('sel'));
        row.classList.add('sel');
        try {
          const res = await api('/api/attempts', {
            method: 'POST',
            body: JSON.stringify({ chapter_id: chapter.id, question_id: q.id, answer: letter }),
          });
          el.querySelectorAll('.opt').forEach((o) => {
            if (o.dataset.letter === res.right_answer) o.classList.add('right');
            else if (o.dataset.letter === letter) o.classList.add('wrong');
          });
          const fb = document.createElement('div');
          fb.className = 'quiz-fb';
          fb.innerHTML = (res.correct ? '<b style="color:var(--ok)">回答正确</b>' : '<b style="color:var(--danger)">答错了</b>（已记入易错本）')
            + `<br/>${esc(res.explanation || '')}`;
          el.appendChild(fb);
        } catch (err) { toast(err.message, true); }
      });
      el.appendChild(row);
    });
    box.appendChild(el);
  });
}

async function generateQuestions(chapter) {
  const btn = $('#btn-gen-q');
  btn.disabled = true; btn.textContent = '生成中…';
  try {
    await api(`/api/chapters/${chapter.id}/questions/generate`, {
      method: 'POST', body: JSON.stringify({ n: 3 }),
    });
    await loadQuestions(chapter);
    toast('题目已生成');
  } catch (err) { toast(err.message, true); }
  finally { btn.disabled = false; btn.textContent = '生成 3 道题'; }
}

$('#study-ask-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const input = $('#study-ask-input');
  const text = input.value.trim();
  if (!text || !state.chapter) return;
  input.value = '';
  const body = $('#tutor-body');
  body.innerHTML = `<div class="bubble" style="background:#f7f9fd;border:1px solid var(--line)">${md('**你：** ' + text)}</div>`;
  const answerBox = document.createElement('div');
  answerBox.className = 'body';
  answerBox.style.marginTop = '10px';
  answerBox.innerHTML = '<span class="muted">思考中…</span>';
  body.appendChild(answerBox);
  let acc = '';
  try {
    await streamSSE('/api/chat/stream', {
      text: `【章节：${state.chapter.title}】${text}`,
      ephemeral: true,
    }, {
      delta(d) { acc += d.text || ''; answerBox.innerHTML = md(acc); },
      failed(d) { throw new Error(d.message || '生成失败'); },
    });
  } catch (err) {
    answerBox.innerHTML = `<span style="color:var(--danger)">${esc(err.message)}</span>`;
  }
});

/* ---------------------------------------------------------------- 资料管理 */
let FOLDERS = [];
let CUR_FOLDER = null;
let PICKED_FILE = null;

async function loadMaterials() {
  const q = state.folderId ? `?folder=${encodeURIComponent(state.folderId)}` : '';
  const data = await api('/api/materials' + q);
  const materials = data.materials || [];
  FOLDERS = data.folders || [];
  CUR_FOLDER = FOLDERS.find((f) => f.id === state.folderId) || null;
  renderFolderBar();
  renderSharedWarning();
  if (typeof renderPendingBar === 'function') renderPendingBar(materials);
  renderMaterialList(materials);
}

function renderSharedWarning() {
  const bar = $('#shared-warning');
  if (CUR_FOLDER && CUR_FOLDER.is_shared) {
    bar.className = 'banner warn';
    bar.innerHTML = `🔒 <b>核心资料 core</b>：本机维护的计算机核心知识，会被所有科目的提问检索到。
      不推荐直接修改或删除；确实要改也可以，改动会影响全部科目的回答。`;
  } else {
    bar.className = 'banner hidden';
    bar.innerHTML = '';
  }
}

function renderFolderBar() {
  const bar = $('#folder-bar');
  bar.innerHTML = '';
  const total = FOLDERS.reduce((n, f) => n + (f.count || 0), 0);

  const all = document.createElement('button');
  all.className = 'folder-pill' + (state.folderId ? '' : ' active');
  all.innerHTML = `全部资料 <i class="pill-count">${total}</i>`;
  all.addEventListener('click', () => { state.folderId = ''; loadMaterials(); });
  bar.appendChild(all);

  FOLDERS.forEach((f) => {
    const wrap = document.createElement('div');
    wrap.className = 'folder-pill' + (state.folderId === f.id ? ' active' : '') +
      (f.is_shared ? ' shared' : '');
    wrap.title = f.is_shared ? '共识资料（不推荐修改）' : f.name;
    wrap.innerHTML = `${f.is_shared ? '🔒' : '📁'} <span class="pill-name">${esc(f.name)}</span>
      <i class="pill-count">${f.count || 0}</i>
      <b class="pill-del" title="删除文件夹">✕</b>`;
    wrap.addEventListener('click', (ev) => {
      if (ev.target.classList.contains('pill-del')) {
        ev.stopPropagation();
        openFolderDelete(f);
        return;
      }
      state.folderId = f.id;
      loadMaterials();
    });
    bar.appendChild(wrap);
  });
}

function openFolderDelete(folder) {
  $('#fdel-name').textContent = folder.name;
  $('#fdel-count').textContent = folder.count || 0;
  $('#fdel-shared').innerHTML = folder.is_shared
    ? '注意：这是<b>共识资料</b>文件夹，建议先用「只删文件夹」把资料保留下来。' : '';
  $('#modal-folder-del').dataset.folderId = folder.id;
  openModal('#modal-folder-del');
}

function renderMaterialList(materials) {
  const list = $('#material-list');
  list.innerHTML = '';
  if (!materials.length) {
    list.innerHTML = `<div class="empty"><div class="empty-icon">🗂️</div><h3>这个文件夹还是空的</h3>
      <p>点右上角「导入资料」粘贴课件文本或选择文件</p></div>`;
    return;
  }
  materials.forEach((m) => {
    const el = document.createElement('div');
    el.className = 'card material-card';
    const kb = (m.bytes / 1024).toFixed(1);
    el.innerHTML = `
      <h4 class="mat-title" title="点击打开源文件">${esc(m.title)}</h4>
      <div class="meta">
        ${m.folder_name ? `<span class="tag">${m.folder_shared ? '🔒 ' : '📁 '}${esc(m.folder_name)}</span>` : '<span class="tag">根目录</span>'}
        <span class="tag">${esc(m.subject || '未分类')}</span>
        <span>${kb} KB</span>
        <span>${esc(m.created_at)}</span>
      </div>
      ${m.source_url ? `<div class="meta">来源：${esc(m.source_url)}</div>` : ''}
      <div class="path-line" title="${esc(m.path || '')}">${esc(m.path || '（无源文件路径）')}
        <button class="mini-btn" data-act="copy">复制路径</button></div>
      <div class="card-actions">
        <button class="btn primary small" data-act="open">打开源文件</button>
        <button class="btn small" data-act="preview">查看内容</button>
        <button class="btn danger small" data-act="del">删除</button>
      </div>`;
    el.querySelector('.mat-title').addEventListener('click', () => window.open(`/api/materials/${m.id}/raw`, '_blank'));
    el.querySelector('[data-act="open"]').addEventListener('click', () => window.open(`/api/materials/${m.id}/raw`, '_blank'));
    el.querySelector('[data-act="copy"]').addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(m.path || ''); toast('路径已复制'); }
      catch (e) { toast('复制失败，可手动选中路径', true); }
    });
    el.querySelector('[data-act="preview"]').addEventListener('click', async () => {
      try {
        const d = await api(`/api/materials/${m.id}`);
        const w = window.open('', '_blank');
        w.document.write(`<meta charset="utf-8"><title>${esc(d.material.title)}</title>
          <pre style="white-space:pre-wrap;font:14px/1.7 'Microsoft YaHei',monospace;padding:24px;max-width:900px;margin:auto">${esc(d.content)}</pre>`);
        w.document.close();
      } catch (err) { toast(err.message, true); }
    });
    el.querySelector('[data-act="del"]').addEventListener('click', async () => {
      if (m.folder_shared && !confirm(`「${m.title}」位于共识资料文件夹，删除会影响所有科目。仍要删除吗？`)) return;
      if (!m.folder_shared && !confirm(`删除资料「${m.title}」及其索引？`)) return;
      await api(`/api/materials/${m.id}`, { method: 'DELETE' });
      loadMaterials(); toast('已删除资料');
      const st = await api('/api/state'); renderStats(st.stats);
    });
    list.appendChild(el);
  });
}

$('#btn-import').addEventListener('click', async () => {
  const { subjects } = await api('/api/subjects');
  $('#imp-subject').innerHTML = '<option value="">不指定（归入共识资料）</option>' +
    subjects.map((s) => `<option value="${esc(s.name)}">${esc(s.name)}</option>`).join('');
  const data = await api('/api/materials');
  FOLDERS = data.folders || [];
  $('#imp-folder').innerHTML = '<option value="">根目录</option>' +
    FOLDERS.map((f) => `<option value="${f.id}"${f.id === state.folderId ? ' selected' : ''}>${f.is_shared ? '🔒 ' : ''}${esc(f.name)}</option>`).join('');
  $('#imp-title').value = ''; $('#imp-text').value = ''; $('#imp-msg').textContent = '';
  PICKED_FILE = null; $('#imp-file').value = ''; $('#imp-review').checked = false;
  openModal('#modal-import');
});
$('#imp-cancel').addEventListener('click', () => closeModal('#modal-import'));
$('#imp-pick').addEventListener('click', () => $('#imp-file').click());
$('#imp-file').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  PICKED_FILE = file;
  if (file.size > 5 * 1024 * 1024) { $('#imp-msg').textContent = '文件超过 5 MB，建议拆分后再导入'; return; }
  if (!$('#imp-title').value) $('#imp-title').value = file.name.replace(/\.[^.]+$/, '');
  if (/\.docx$/i.test(file.name)) {
    $('#imp-text').value = '';
    $('#imp-msg').textContent = '已选择 .docx，导入时会在服务端解析正文（保留段落结构）';
    return;
  }
  if (/\.doc$/i.test(file.name)) {
    $('#imp-msg').textContent = '老式 .doc 无法直接解析，请先另存为 .docx';
    return;
  }
  const text = await file.text();
  $('#imp-text').value = text;
  $('#imp-msg').textContent = '';
});
$('#imp-save').addEventListener('click', async () => {
  const title = $('#imp-title').value.trim();
  const text = $('#imp-text').value;
  const isDocx = PICKED_FILE && /\.docx$/i.test(PICKED_FILE.name);
  if (!isDocx && (!title || !text.trim())) { $('#imp-msg').textContent = '标题和内容都不能为空'; return; }
  $('#imp-msg').textContent = '导入中…';
  const folderId = $('#imp-folder').value;
  try {
    const payload = {
      title, subject: $('#imp-subject').value, folder_id: folderId,
      filename: PICKED_FILE ? PICKED_FILE.name : '',
      review: $('#imp-review').checked,
    };
    if (isDocx) payload.content = await readFileBase64(PICKED_FILE);
    else payload.text = text;
    const res = await api('/api/materials/import', {
      method: 'POST', body: JSON.stringify(payload),
    });
    toast(`已导入，切分为 ${res.chunks} 段${res.status === 'pending' ? '（待审核）' : ''}`);
    closeModal('#modal-import');
    PICKED_FILE = null;
    $('#imp-file').value = '';
    state.folderId = folderId;
    loadMaterials();
    const st = await api('/api/state'); renderStats(st.stats);
  } catch (err) { $('#imp-msg').textContent = err.message; }
});

$('#btn-new-folder').addEventListener('click', async () => {
  const name = prompt('文件夹名称');
  if (!name) return;
  try {
    await api('/api/folders', { method: 'POST', body: JSON.stringify({ name }) });
    loadMaterials(); toast('已创建文件夹');
  } catch (err) { toast(err.message, true); }
});

// 删除文件夹：两种模式
$('#fdel-cancel').addEventListener('click', () => closeModal('#modal-folder-del'));
$('#fdel-move').addEventListener('click', () => doDeleteFolder('move'));
$('#fdel-purge').addEventListener('click', () => doDeleteFolder('purge'));

async function doDeleteFolder(mode) {
  const folderId = $('#modal-folder-del').dataset.folderId;
  if (!folderId) return;
  try {
    const res = await api(`/api/folders/${folderId}?mode=${mode}`, { method: 'DELETE' });
    closeModal('#modal-folder-del');
    if (mode === 'purge') toast('文件夹及其资料已删除');
    else toast(res.moved ? `文件夹已删除，${res.moved} 份资料移到根目录` : '文件夹已删除');
    if (state.folderId === folderId) state.folderId = '';
    loadMaterials();
    const st = await api('/api/state'); renderStats(st.stats);
  } catch (err) { toast(err.message, true); }
}

/* ---------------------------------------------------------------- 启动 */
boot().catch((err) => {
  console.error(err);
  $('#gate').classList.remove('hidden');
  $('#gate-msg').textContent = '无法连接本地服务：' + err.message;
});
