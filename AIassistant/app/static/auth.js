/* ============================================================
   登录 / 注册 / 退出 / 修改密码 / 离线提示
   依赖 app.js 的全局：$ $$ api toast boot openModal closeModal
   规格见 文档/登录注册方案/登录注册与本地部署流程.md 第 6.4 节
   ============================================================ */
'use strict';

let authMode = 'login';
let appEntered = false;      // 本页面里是否已经进入过主界面（切换账号时要整页刷新清状态）

const USERNAME_RE = /^[A-Za-z0-9_]{3,20}$/;

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
  setTimeout(() => $('#auth-username').focus(), 50);
}

/* 侧栏账号区 + 离线提示条 */
function renderAccount(auth) {
  appEntered = true;
  const bar = $('#account-bar');
  const hasAccount = !!(auth && auth.enabled && auth.user);
  bar.parentElement.classList.toggle('has-account', hasAccount);
  if (!hasAccount) { bar.classList.add('hidden'); return; }
  bar.classList.remove('hidden');
  $('#account-name').textContent = `账号：${auth.user.username}`;
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
