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
    renderMastery(d.mastery || { chapters: [], subjects: [], overall: {} });
    renderUsage(d.usage || {});
    loadMistakes();
    loadPending();
  } catch (err) {
    toast('看板加载失败：' + err.message, true);
  }
}

function renderKpi(d) {
  const overall = (d.mastery && d.mastery.overall) || {};
  const usage = d.usage || {};
  const items = [
    { label: '连续学习', value: `${(d.streak && d.streak.days) || 0} 天`, hint: `累计 ${(d.streak && d.streak.total_days) || 0} 天有记录` },
    { label: '待复习', value: `${d.due || 0} 条`, hint: d.due ? '现在就该过一遍' : '队列已清空' },
    { label: '总体正确率', value: pct(overall.rate), hint: `${overall.correct || 0}/${overall.attempts || 0} 题` },
    { label: '近 7 天调用', value: `${usage.calls || 0} 次`, hint: `均首字 ${usage.avg_first_ms || 0} ms` },
    { label: '待审核资料', value: `${d.pending || 0} 份`, hint: d.stale ? `${d.stale} 份来源可能过期` : '无过期来源' },
  ];
  $('#dash-kpi').innerHTML = items.map((it) => `
    <div class="kpi">
      <div class="kpi-label">${esc(it.label)}</div>
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
    const icon = { review: '🔁', weak: '⚠️', new: '🌱', idle: '☕' }[item.type] || '•';
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
    box.innerHTML = '<p class="muted small">没有到期的复习。做错的题会自动排进来，按 1/3/7/15 天递增。</p>';
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
  const chapters = (mastery.chapters || []).filter((c) => c.attempts > 0 || c.status === '薄弱');
  const shown = chapters.length ? chapters : (mastery.chapters || []).slice(0, 8);
  if (!shown.length) { box.innerHTML = '<p class="muted small">还没有科目数据</p>'; return; }
  box.innerHTML = shown.map((c) => `
    <div class="mastery-row">
      <div class="mastery-label" title="${esc(c.label)}">${esc(c.label)}</div>
      <div class="mastery-track">
        <div class="mastery-bar ${statusClass(c.status)}" style="width:${Math.max(2, Math.min(100, c.rate))}%"></div>
      </div>
      <div class="mastery-rate">${c.attempts ? pct(c.rate) : '—'}</div>
      <div class="badge ${statusClass(c.status)}">${esc(c.status)}</div>
    </div>`).join('');
}

function renderUsage(usage) {
  const box = $('#usage-box');
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
  const rows = hits.map((h) => `
    <div class="retrieval-hit">
      <div class="rh-head"><b>${esc(h.citation_id)}</b>
        <span class="tag">${esc(h.title)}</span>
        <span class="muted small">${esc(h.locator || '')} · 得分 ${esc(h.score)}</span></div>
      <div class="rh-snippet">${esc(h.snippet || '')}</div>
    </div>`).join('') || '<p class="muted small">没有命中任何片段</p>';
  const box = document.createElement('details');
  box.className = 'retrieval-box';
  box.innerHTML = `<summary>检索详情：命中 ${hits.length} 段 · 最高分 ${esc(data.top_score)} · 阈值 ${esc(data.threshold)}
      ${data.insufficient ? '（判定为资料不足）' : ''}${data.subject ? ' · 科目 ' + esc(data.subject) : ''}</summary>
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
        () => window.open(`/api/materials/${h.material_id}/raw`, '_blank'));
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
  bar.innerHTML = '📋 ' + parts.join('　·　');
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
