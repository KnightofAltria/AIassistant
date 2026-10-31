/* ============================================================
   登录 / 注册 / 退出 / 修改密码 / 离线提示
   依赖 app.js 的全局：$ $$ api toast boot openModal closeModal
   规格见 文档/登录注册方案/登录注册与本地部署流程.md 第 6.4 节
   ============================================================ */
'use strict';

let authMode = 'login';
let appEntered = false;      // 本页面里是否已经进入过主界面（切换账号时要整页刷新清状态）

const USERNAME_RE = /^[A-Za-z0-9_]{3,20}$/;
// 只记用户名（不是密码），存在浏览器 localStorage
const REMEMBER_KEY = 'csla.rememberedUsername';
let accountUser = null;      // 当前登录账号，注销确认时要核对用户名

function checkPassword(pw, label) {
  if (pw.length < 8 || pw.length > 64) return `${label}长度需为 8–64 位`;
  if (!/[A-Za-z]/.test(pw) || !/\d/.test(pw)) return `${label}需同时包含字母和数字`;
  return '';
}

function setAuthMode(mode) {
  authMode = mode;
  $$('.auth-tab').forEach((b) => b.classList.toggle('active', b.dataset.mode === mode));
  $$('.auth-reg').forEach((el) => el.classList.toggle('hidden', mode !== 'register'));
  $('#auth-submit').textContent = mode === 'register' ? '注册并进入' : '登录';
  $('#auth-password').autocomplete = mode === 'register' ? 'new-password' : 'current-password';
  $('#auth-msg').className = 'gate-msg';
  $('#auth-msg').textContent = '';
}

/* 显示登录页；任何接口返回 auth_required 时也会调到这里 */
function showAuth(auth) {
  ['#app', '#gate', '#landing'].forEach((sel) => { const el = $(sel); if (el) el.classList.add('hidden'); });
  $$('.modal').forEach((m) => m.classList.add('hidden'));
  $('#auth').classList.remove('hidden');
  $('#auth-offline').classList.add('hidden');
  if (auth && auth.notice) { $('#auth-msg').className = 'gate-msg'; $('#auth-msg').textContent = auth.notice; }
  if (auth && auth.auth_server) $('#auth-hint').textContent = `认证服务：${auth.auth_server} · 忘记密码请联系管理员重置。`;
  const remembered = localStorage.getItem(REMEMBER_KEY) || '';
  $('#auth-remember').checked = !!remembered;
  if (remembered && !$('#auth-username').value) $('#auth-username').value = remembered;
  setTimeout(() => $(remembered ? '#auth-password' : '#auth-username').focus(), 50);
}

/* 侧栏账号区 + 离线提示条 */
function renderAccount(auth) {
  appEntered = true;
  const bar = $('#account-bar');
  const hasAccount = !!(auth && auth.enabled && auth.user);
  bar.parentElement.classList.toggle('has-account', hasAccount);
  // 账号管理入口：登录了且是管理员才显示（--no-auth 单机模式没有账号可管）
  $('#admin-row').classList.toggle('hidden', !(hasAccount && auth.is_admin));
  if (!hasAccount) { bar.classList.add('hidden'); return; }
  accountUser = auth.user;
  bar.classList.remove('hidden');
  const admin = auth.user.role === 'admin';
  $('#account-name').innerHTML = `账号：${esc(auth.user.username)}`
    + (admin ? ' <span class="role-tag admin" title="可修改核心资料、管理账号">管理员</span>' : '');
  $('#account-name').title = `${auth.user.username}（${admin ? '管理员' : '学生'}）`;
  const off = $('#auth-offline');
  off.classList.toggle('hidden', !auth.offline);
  if (auth.offline) off.textContent = `认证服务不可达（${auth.auth_server}），离线使用中；恢复联网后会自动重新校验。`;
}

$$('.auth-tab').forEach((b) => b.addEventListener('click', (e) => { e.preventDefault(); setAuthMode(b.dataset.mode); }));

$('#auth-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const msg = $('#auth-msg');
  const username = $('#auth-username').value.trim();
  const password = $('#auth-password').value;
  msg.className = 'gate-msg';
  if (!username || !password) { msg.textContent = '请填写用户名和密码'; return; }
  if (authMode === 'register') {
    if (!USERNAME_RE.test(username)) { msg.textContent = '用户名需为 3–20 位字母、数字或下划线'; return; }
    const bad = checkPassword(password, '密码');
    if (bad) { msg.textContent = bad; return; }
    if (password !== $('#auth-password2').value) { msg.textContent = '两次输入的密码不一致'; return; }
  }
  const btn = $('#auth-submit');
  btn.disabled = true;
  msg.textContent = authMode === 'register' ? '正在注册…' : '正在登录…';
  try {
    const body = { username, password };
    if (authMode === 'register') body.nickname = $('#auth-nickname').value.trim();
    await api(`/api/auth/${authMode}`, { method: 'POST', body: JSON.stringify(body) });
    if ($('#auth-remember').checked) localStorage.setItem(REMEMBER_KEY, username);
    else localStorage.removeItem(REMEMBER_KEY);
    $('#auth-password').value = '';
    $('#auth-password2').value = '';
    msg.className = 'gate-msg ok';
    msg.textContent = '成功，正在进入…';
    // 之前进过别的账号：整页刷新，避免上一个账号的界面数据残留
    if (appEntered) { location.reload(); return; }
    setTimeout(() => { $('#auth').classList.add('hidden'); boot(); }, 250);
  } catch (err) {
    msg.className = 'gate-msg';
    msg.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
});

$('#btn-logout').addEventListener('click', async () => {
  if (!confirm('退出登录？本机学习数据会保留，下次登录同一账号即可看到。')) return;
  try { await api('/api/auth/logout', { method: 'POST', body: '{}' }); } catch (e) { /* 照样回登录页 */ }
  location.reload();
});

$('#btn-password').addEventListener('click', () => {
  ['#pw-old', '#pw-new', '#pw-new2'].forEach((s) => { $(s).value = ''; });
  $('#pw-msg').textContent = '';
  openModal('#modal-password');
});
$('#pw-cancel').addEventListener('click', () => closeModal('#modal-password'));
$('#pw-save').addEventListener('click', async () => {
  const oldPw = $('#pw-old').value;
  const newPw = $('#pw-new').value;
  const msg = $('#pw-msg');
  if (!oldPw) { msg.textContent = '请填写原密码'; return; }
  const bad = checkPassword(newPw, '新密码');
  if (bad) { msg.textContent = bad; return; }
  if (newPw !== $('#pw-new2').value) { msg.textContent = '两次输入的新密码不一致'; return; }
  if (newPw === oldPw) { msg.textContent = '新密码不能与原密码相同'; return; }
  try {
    await api('/api/auth/password', { method: 'POST', body: JSON.stringify({ old_password: oldPw, new_password: newPw }) });
    closeModal('#modal-password');
    toast('密码已修改，其他设备上的登录已失效');
  } catch (err) { msg.textContent = err.message; }
});

/* ---------------------------------------------------------------- 显示 / 隐藏密码 */
$$('.pw-toggle').forEach((btn) => btn.addEventListener('click', () => {
  const input = document.getElementById(btn.dataset.for);
  const show = input.type === 'password';
  input.type = show ? 'text' : 'password';
  btn.textContent = show ? '隐藏' : '显示';
  btn.title = show ? '隐藏密码' : '显示密码';
  input.focus();
}));

/* ---------------------------------------------------------------- 登录设备 */
async function loadSessions() {
  const list = $('#sessions-list');
  const msg = $('#sessions-msg');
  list.innerHTML = '<span class="muted small">加载中…</span>';
  msg.textContent = '';
  try {
    const { sessions } = await api('/api/auth/sessions');
    list.innerHTML = '';
    sessions.forEach((s) => {
      const row = document.createElement('div');
      row.className = 'session-row' + (s.current ? ' current' : '');
      row.innerHTML = `<div class="session-info">
          <b>${esc(s.device)}${s.current ? '（本机）' : ''}</b>
          <span>登录于 ${esc(s.login_at || '—')} · 最近活动 ${esc(s.last_seen || '—')}${s.ip ? ` · ${esc(s.ip)}` : ''}</span>
        </div>
        ${s.current ? '<span class="tag">当前</span>' : '<button class="btn small" data-act="revoke">下线</button>'}`;
      const btn = row.querySelector('[data-act="revoke"]');
      if (btn) btn.addEventListener('click', () => revokeSessions({ session_id: s.id }, `让「${s.device}」下线？`));
      list.appendChild(row);
    });
    $('#sessions-revoke-others').disabled = sessions.filter((s) => !s.current).length === 0;
  } catch (err) {
    list.innerHTML = '';
    msg.textContent = err.message;
    $('#sessions-revoke-others').disabled = true;
  }
}

async function revokeSessions(body, question) {
  if (!confirm(question)) return;
  try {
    const { revoked } = await api('/api/auth/sessions/revoke', { method: 'POST', body: JSON.stringify(body) });
    toast(revoked ? `已让 ${revoked} 台设备下线` : '没有需要下线的设备');
    loadSessions();
  } catch (err) { $('#sessions-msg').textContent = err.message; }
}

$('#btn-sessions').addEventListener('click', () => { openModal('#modal-sessions'); loadSessions(); });
$('#sessions-close').addEventListener('click', () => closeModal('#modal-sessions'));
$('#sessions-revoke-others').addEventListener('click', () =>
  revokeSessions({ others: true }, '让除本机以外的所有设备下线？它们需要重新输入密码登录。'));

/* ---------------------------------------------------------------- 注销账号 */
$('#sessions-delete').addEventListener('click', () => {
  if (!accountUser) return;
  closeModal('#modal-sessions');
  $('#del-username').textContent = accountUser.username;
  ['#del-password', '#del-confirm'].forEach((s) => { $(s).value = ''; });
  $('#del-msg').textContent = '';
  openModal('#modal-delete-account');
});
$('#del-cancel').addEventListener('click', () => closeModal('#modal-delete-account'));
$('#del-ok').addEventListener('click', async () => {
  const password = $('#del-password').value;
  const msg = $('#del-msg');
  if (!password) { msg.textContent = '请输入密码'; return; }
  if ($('#del-confirm').value.trim() !== accountUser.username) { msg.textContent = '用户名输入不一致'; return; }
  const btn = $('#del-ok');
  btn.disabled = true; msg.textContent = '正在注销…';
  try {
    await api('/api/auth/delete', { method: 'POST', body: JSON.stringify({ password }) });
    if ((localStorage.getItem(REMEMBER_KEY) || '').toLowerCase() === accountUser.username.toLowerCase()) {
      localStorage.removeItem(REMEMBER_KEY);
    }
    alert('账号已注销，本机数据已删除。');
    location.reload();
  } catch (err) { msg.textContent = err.message; }
  finally { btn.disabled = false; }
});

/* ---------------------------------------------------------------- 清除本人记录（FR-12 / UI-08） */
/* 先列出影响范围（每类现有条数），勾选 + 输入"确认清除"才放行；后端会再校验一次确认语 */
const CLEAR_WORD = '确认清除';

async function openClearRecords() {
  $('#clr-user').textContent = accountUser ? accountUser.username : '本机用户';
  $('#clr-confirm').value = '';
  $('#clr-msg').textContent = '';
  const box = $('#clr-kinds');
  box.innerHTML = '<span class="muted small">加载中…</span>';
  openModal('#modal-clear-records');
  try {
    const { kinds } = await api('/api/records');
    box.innerHTML = kinds.map((k) => `<label class="clr-kind${k.count ? '' : ' zero'}">
        <input type="checkbox" value="${esc(k.key)}"${k.count ? '' : ' disabled'} />
        <span>${esc(k.label)}</span><b>${k.count}</b></label>`).join('');
    box.querySelectorAll('input').forEach((i) => i.addEventListener('change', updateClearButton));
  } catch (err) { box.innerHTML = ''; $('#clr-msg').textContent = err.message; }
  updateClearButton();
}

function updateClearButton() {
  const picked = $$('#clr-kinds input:checked').length;
  $('#clr-ok').disabled = !picked || $('#clr-confirm').value.trim() !== CLEAR_WORD;
  $('#clr-ok').textContent = picked ? `清除选中的 ${picked} 类记录` : '清除选中的记录';
}

$('#btn-clear-records').addEventListener('click', openClearRecords);
$('#clr-confirm').addEventListener('input', updateClearButton);
$('#clr-cancel').addEventListener('click', () => closeModal('#modal-clear-records'));
$('#clr-ok').addEventListener('click', async () => {
  const picked = $$('#clr-kinds input:checked');
  const kinds = picked.map((i) => i.value);
  const names = picked.map((i) => i.parentElement.querySelector('span').textContent);
  if (!kinds.length || $('#clr-confirm').value.trim() !== CLEAR_WORD) return;
  if (!confirm(`最后确认：清除「${names.join('、')}」？清除后无法恢复。`)) return;
  const btn = $('#clr-ok');
  btn.disabled = true;
  try {
    const { cleared } = await api('/api/records/clear', {
      method: 'POST', body: JSON.stringify({ kinds, confirm: CLEAR_WORD }),
    });
    const total = Object.values(cleared || {}).reduce((a, b) => a + b, 0);
    closeModal('#modal-clear-records');
    toast(`已清除 ${total} 条记录`);
    // 对话、总结、档案、统计都可能变了：清掉聊天区（等于点一次「新对话」）再刷新统计和档案
    if (kinds.includes('conversations')) $('#btn-new-chat').click();
    const st = await api('/api/state');
    renderStats(st.stats);
    loadProfile();
  } catch (err) { $('#clr-msg').textContent = err.message; updateClearButton(); }
});

/* ---------------------------------------------------------------- 账号管理（仅管理员） */
let ADMIN_USERS = [];

async function loadAdminUsers() {
  const list = $('#admin-users-list');
  $('#admin-msg').textContent = '';
  list.innerHTML = '<span class="muted small">加载中…</span>';
  try {
    ({ users: ADMIN_USERS } = await api('/api/admin/users'));
    renderAdminUsers();
  } catch (err) { list.innerHTML = ''; $('#admin-msg').textContent = err.message; }
}

function renderAdminUsers() {
  const list = $('#admin-users-list');
  const kw = $('#admin-search').value.trim().toLowerCase();
  const me = accountUser ? accountUser.id : '';
  const rows = ADMIN_USERS.filter((u) => !kw || `${u.username} ${u.nickname}`.toLowerCase().includes(kw));
  list.innerHTML = rows.length ? '' : '<span class="muted small">没有匹配的账号</span>';
  rows.forEach((u) => {
    const self = u.id === me;
    const disabled = u.status !== 'active';
    const row = document.createElement('div');
    row.className = 'session-row admin-row' + (self ? ' current' : '') + (disabled ? ' disabled' : '');
    row.innerHTML = `<div class="session-info">
        <b>${esc(u.username)}${u.nickname ? `（${esc(u.nickname)}）` : ''}${self ? ' · 我' : ''}
          <span class="role-tag ${u.role === 'admin' ? 'admin' : ''}">${u.role === 'admin' ? '管理员' : '学生'}</span>
          ${disabled ? '<span class="role-tag off">已禁用</span>' : ''}</b>
        <span>注册于 ${esc(u.created_at || '—')} · 最近登录 ${esc(u.last_login_at || '从未登录')}</span>
      </div>
      <div class="admin-acts">
        <button class="btn small" data-act="reset">重置密码</button>
        ${self ? '' : `<button class="btn small ${disabled ? '' : 'danger'}" data-act="toggle">${disabled ? '启用' : '禁用'}</button>`}
      </div>`;
    row.querySelector('[data-act="reset"]').addEventListener('click', () => adminResetPassword(u));
    const toggle = row.querySelector('[data-act="toggle"]');
    if (toggle) toggle.addEventListener('click', () => adminToggle(u));
    list.appendChild(row);
  });
}

async function adminAction(body, okText) {
  try {
    const { user } = await api('/api/admin/users', { method: 'POST', body: JSON.stringify(body) });
    ADMIN_USERS = ADMIN_USERS.map((u) => (u.id === user.id ? user : u));
    renderAdminUsers();
    toast(okText);
  } catch (err) { $('#admin-msg').textContent = err.message; }
}

function adminToggle(u) {
  const disable = u.status === 'active';
  if (disable && !confirm(`禁用账号「${u.username}」？它在所有设备上的登录会立即失效，之后无法登录。本机数据会保留。`)) return;
  adminAction({ action: disable ? 'disable' : 'enable', username: u.username },
    disable ? `已禁用 ${u.username}` : `已启用 ${u.username}`);
}

function adminResetPassword(u) {
  const pw = prompt(`为「${u.username}」设置新密码（8–64 位，含字母和数字）。\n重置后该账号所有设备需要用新密码重新登录。`);
  if (pw == null) return;
  const bad = checkPassword(pw, '新密码');
  if (bad) { $('#admin-msg').textContent = bad; return; }
  adminAction({ action: 'reset_password', username: u.username, password: pw },
    `已重置 ${u.username} 的密码，请把新密码当面告诉本人`);
}

$('#btn-admin-users').addEventListener('click', () => {
  $('#admin-search').value = '';
  openModal('#modal-admin-users');
  loadAdminUsers();
});
$('#admin-search').addEventListener('input', renderAdminUsers);
$('#admin-close').addEventListener('click', () => closeModal('#modal-admin-users'));
