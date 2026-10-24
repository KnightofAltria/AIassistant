/* ============================================================
   AI 工具化模块：资料管理 / 科目学习 的指令输入框
   依赖 app.js 里的全局：$ $$ api toast esc md state
   ============================================================ */
'use strict';

/* ---------------------------------------------------------------- 工具调用步骤展示 */
function agentLog(scope) {
  return scope === 'materials' ? $('#agent-log-materials') : $('#agent-log-study');
}

function appendStep(log, step) {
  const el = document.createElement('div');
  el.className = 'agent-step' + (step.ok ? '' : ' bad') + (step.need_confirm ? ' warn' : '');
  const icon = step.need_confirm ? '⏸' : (step.ok ? '✅' : '⚠️');
  el.innerHTML = `${icon} <b>${esc(step.tool)}</b>
    <span class="step-args">${esc(JSON.stringify(step.args || {}))}</span>
    <div class="step-msg">${esc(step.summary || '')}</div>`;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
}

async function sendAgent(scope, text, btn) {
  if (!text.trim()) return;
  const log = agentLog(scope);
  log.classList.remove('hidden');
  const userLine = document.createElement('div');
  userLine.className = 'agent-user';
  userLine.textContent = '你：' + text;
  log.appendChild(userLine);

  const answer = document.createElement('div');
  answer.className = 'agent-answer';
  answer.innerHTML = '<span class="muted">思考中…</span>';
  log.appendChild(answer);
  log.scrollTop = log.scrollHeight;

  if (btn) { btn.disabled = true; btn.textContent = '执行中'; }
  let acc = '';
  try {
    await streamSSE('/api/agent/stream', { scope, text }, {
      status() { answer.innerHTML = '<span class="muted">思考中…</span>'; },
      step(d) { appendStep(log, d); },
      delta(d) { acc += d.text || ''; answer.innerHTML = md(acc); log.scrollTop = log.scrollHeight; },
      completed() {
        /* 动作可能改动了数据，刷新对应视图 */
        if (scope === 'materials') { loadMaterials(); }
        else { loadSubjects(); }
        api('/api/state').then((st) => renderStats(st.stats)).catch(() => {});
      },
      failed(d) { throw new Error(d.message || '执行失败'); },
    });
  } catch (err) {
    answer.innerHTML = `<span style="color:var(--danger)">${esc(err.message)}</span>`;
    toast(err.message, true);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '执行'; }
  }
}

/* ---------------------------------------------------------------- 两个指令框 */
$('#material-agent-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const input = $('#material-agent-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  sendAgent('materials', text, $('#material-agent-send'));
});

$('#study-agent-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const input = $('#study-agent-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  sendAgent('study', text, $('#study-agent-send'));
});

/* 快捷指令（点一下直接发） */
document.querySelectorAll('[data-agent-preset]').forEach((btn) => {
  btn.addEventListener('click', () => {
    const scope = btn.dataset.scope;
    sendAgent(scope, btn.dataset.agentPreset, null);
  });
});

/* ---------------------------------------------------------------- 科目 / 章节管理 */
function openCreateSubject() {
  $('#subj-name').value = '';
  $('#subj-videos').value = '';
  $('#subj-msg').textContent = '';
  $('#modal-subject').classList.remove('hidden');
  setTimeout(() => $('#subj-name').focus(), 60);
}

async function submitCreateSubject() {
  const name = $('#subj-name').value.trim();
  const videos = $('#subj-videos').value.split(/\n+/).map((v) => v.trim()).filter(Boolean);
  if (!name) { $('#subj-msg').textContent = '请填写科目名称'; return; }
  const btn = $('#subj-ok');
  btn.disabled = true; btn.textContent = '创建中…';
  $('#subj-msg').textContent = '正在创建科目、整理资料文件夹…';
  try {
    const res = await api('/api/subjects', {
      method: 'POST', body: JSON.stringify({ name, videos }),
    });
    $('#modal-subject').classList.add('hidden');
    toast(`科目「${name}」已创建${res.videos ? `，已收录 ${res.videos} 个视频链接` : ''}，正在生成章节…`);
    // 关掉弹窗后交给 AI 生成章节与例题
    await sendAgent('study',
      `我刚创建了科目「${name}」（资料文件夹也已建好）。请调用 list_subjects 确认，`
      + '然后为它添加 4~5 个章节，每个章节给一段 3~5 条的大纲。只加章节，不要新增别的科目。', null);
    loadSubjects();
    loadMaterials();
  } catch (err) {
    $('#subj-msg').textContent = err.message;
    toast(err.message, true);
  } finally {
    btn.disabled = false; btn.textContent = '创建并生成章节';
  }
}

async function deleteSubject(subject) {
  if (subject.is_builtin) { toast('内置科目不允许删除', true); return; }
  if (!confirm(`删除科目「${subject.name}」及其全部章节与题目？不可恢复。`)) return;
  try {
    await api(`/api/subjects/${subject.id}`, { method: 'DELETE' });
    toast('已删除科目');
    loadSubjects();
  } catch (err) { toast(err.message, true); }
}

async function editChapter(subject, chapter) {
  const newTitle = prompt('章节标题（留空表示不改）', chapter.title);
  if (newTitle === null) return;
  const newOutline = prompt('章节大纲（留空表示不改，可用 - 开头逐条写）', chapter.outline || '');
  if (newOutline === null) return;
  const payload = {};
  if (newTitle && newTitle !== chapter.title) payload.title = newTitle;
  if (newOutline && newOutline !== chapter.outline) payload.outline = newOutline;
  if (!Object.keys(payload).length) { toast('没有改动'); return; }
  try {
    await api(`/api/chapters/${chapter.id}`, { method: 'PATCH', body: JSON.stringify(payload) });
    toast('章节已更新');
    openSubject(subject);
  } catch (err) { toast(err.message, true); }
}

async function deleteChapter(subject, chapter) {
  const warn = chapter.is_builtin ? '（这是初始内置章节）' : '';
  if (!confirm(`删除章节「${chapter.title}」${warn}及其题目？不可恢复。`)) return;
  try {
    await api(`/api/chapters/${chapter.id}`, { method: 'DELETE' });
    toast('章节已删除');
    openSubject(subject);
  } catch (err) { toast(err.message, true); }
}

/* ---------------------------------------------------------------- 章节小结 */
async function generateChapterSummary(chapterId) {
  const box = $('#chapter-summary');
  box.classList.remove('hidden');
  box.innerHTML = '<span class="muted">正在根据作答记录生成小结…</span>';
  try {
    const { summary, stats } = await api(`/api/chapters/${chapterId}/summary`, { method: 'POST' });
    box.innerHTML = `<div class="sum-stats">作答 ${stats.attempts} 题 · 正确 ${stats.correct} · 正确率 ${stats.rate}%</div>`
      + `<div class="body">${md(summary.content)}</div>`;
    toast('小结已生成，可在「近期总结」里查看');
  } catch (err) {
    box.innerHTML = `<span style="color:var(--danger)">${esc(err.message)}</span>`;
  }
}

/* ---------------------------------------------------------------- 启动时询问总结 */
async function askForSummary(pending) {
  if (!pending) return;
  $('#sumask-title').textContent = pending.title || '上一次对话';
  $('#sumask-meta').textContent =
    `共 ${pending.messages} 条消息，最后更新于 ${pending.updated_at}`;
  $('#modal-summary-ask').classList.remove('hidden');
  $('#modal-summary-ask').dataset.conversationId = pending.conversation_id;

  $('#sumask-yes').onclick = async () => {
    $('#modal-summary-ask').classList.add('hidden');
    toast('正在生成近期总结…');
    try {
      await api('/api/summaries/generate', {
        method: 'POST',
        body: JSON.stringify({ conversation_id: pending.conversation_id }),
      });
      toast('近期总结已生成');
      const st = await api('/api/state');
      renderStats(st.stats);
    } catch (err) { toast(err.message, true); }
  };
  $('#sumask-no').onclick = () => $('#modal-summary-ask').classList.add('hidden');
  $('#sumask-later').onclick = () => {
    $('#modal-summary-ask').classList.add('hidden');
    switchView('chat');
  };
}

/* ---------------------------------------------------------------- 档案 / 易错提示本 */
async function loadProfilePanel() {
  const box = $('#profile-panel');
  try {
    const { profile, files } = await api('/api/profile');
    box.innerHTML = '';
    if (!files.length) {
      box.innerHTML = '<p class="muted small">还没有生成过学习者档案。点下面按钮生成。</p>';
    } else {
      const head = document.createElement('div');
      head.className = 'meta';
      head.textContent = `共 ${files.length} 份档案：` + files.map((f) => f.month).join('、');
      box.appendChild(head);
      files.forEach((f) => {
        const row = document.createElement('div');
        row.className = 'profile-row';
        row.innerHTML = `<b>${esc(f.month)}</b>
          <span class="muted small">${(f.size / 1024).toFixed(1)} KB</span>
          <button class="mini-btn" data-m="${esc(f.month)}">删除</button>`;
        row.querySelector('button').addEventListener('click', async () => {
          if (!confirm(`删除 ${f.month} 的档案？`)) return;
          await api(`/api/profile/${f.month}`, { method: 'DELETE' });
          loadProfilePanel();
        });
        box.appendChild(row);
      });
      if (profile) {
        const pre = document.createElement('pre');
        pre.className = 'profile-pre';
        pre.textContent = profile.slice(0, 1200);
        box.appendChild(pre);
      }
    }
  } catch (err) { box.innerHTML = `<span class="muted">${esc(err.message)}</span>`; }
}

async function generateProfile() {
  const btn = $('#btn-gen-profile');
  btn.disabled = true; btn.textContent = '生成中…';
  try {
    await api('/api/profile/generate', { method: 'POST', body: JSON.stringify({}) });
    toast('学习者档案已更新');
    await loadProfilePanel();
    loadProfile();
  } catch (err) { toast(err.message, true); }
  finally { btn.disabled = false; btn.textContent = '生成/更新本月档案'; }
}

async function generateTips() {
  const btn = $('#btn-gen-tips');
  btn.disabled = true; btn.textContent = '生成中…';
  try {
    await api('/api/mistakes/tips', { method: 'POST', body: JSON.stringify({}) });
    toast('易错提示本已生成');
    loadSummaries();
  } catch (err) { toast(err.message, true); }
  finally { btn.disabled = false; btn.textContent = '生成易错提示本'; }
}

/* ---------------------------------------------------------------- 启动 */
(function bootAgent() {
  const wait = setInterval(async () => {
    if (!document.querySelector('#view-summary.active') && !window.__appReady) {
      /* 等 app.js 把主界面挂出来 */
    }
    try {
      const st = await api('/api/state');
      if (!st || st.configured === undefined) return;
      clearInterval(wait);
      window.__appReady = true;
      setTimeout(() => askForSummary(st.pending_summary), 900);
    } catch (e) { /* 服务还没起来，继续等 */ }
  }, 700);

  $('#btn-gen-profile').addEventListener('click', generateProfile);
  $('#btn-gen-tips').addEventListener('click', generateTips);
  $('#btn-add-subject').addEventListener('click', openCreateSubject);
  $('#subj-cancel').addEventListener('click', () => $('#modal-subject').classList.add('hidden'));
  $('#subj-ok').addEventListener('click', submitCreateSubject);

  /* 进入"近期总结"页时刷新档案面板 */
  const navBtn = document.querySelector('.nav-item[data-view="summary"]');
  if (navBtn) navBtn.addEventListener('click', () => setTimeout(loadProfilePanel, 120));
})();
