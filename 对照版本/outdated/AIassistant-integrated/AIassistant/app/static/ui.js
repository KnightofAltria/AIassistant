/* 轻量的视觉偏好与首页氛围；不读取或上传用户资料。 */
(() => {
  const key = 'csla.interface.preferences.v1';
  let prefs = { tooltips: true, motion: true };
  try { prefs = Object.assign(prefs, JSON.parse(localStorage.getItem(key) || '{}')); } catch (e) { /* 默认偏好 */ }
  const descriptions = {
    profile: '查看和编辑你的个人信息、头像与学习档案。',
    chat: '围绕课程资料提问，并查看回答的依据。',
    dashboard: '查看学习进度、复习安排和学习记录。',
    summary: '回顾对话总结、章节小结和易错内容。',
    study: '按课程和章节学习，完成练习。',
    materials: '导入、浏览和整理你的学习资料。',
    preferences: '调整界面提示、动态效果和模型设置。',
  };
  const titleChoices = ['今天学点什么？', '让好奇心带路。', '今天，也向前一步。', '从一个问题开始。', '把想法变成理解。'];
  const title = document.querySelector('.home-title');
  if (title) title.textContent = titleChoices[Math.floor(Math.random() * titleChoices.length)];
  const home = document.getElementById('view-home');
  if (home) home.dataset.ambience = String(Math.floor(Math.random() * 3));
  const bubble = document.createElement('div');
  bubble.className = 'ui-tooltip'; bubble.id = 'ui-tooltip'; bubble.setAttribute('role', 'tooltip');
  bubble.hidden = true; document.body.appendChild(bubble);
  let owner = null;
  function hide() { bubble.hidden = true; if (owner) owner.removeAttribute('aria-describedby'); owner = null; }
  function show(el) {
    if (!prefs.tooltips) return;
    const message = el.dataset.tip || descriptions[el.dataset.view || el.dataset.goto];
    if (!message) return;
    hide(); owner = el; bubble.textContent = message; bubble.hidden = false; el.setAttribute('aria-describedby', bubble.id);
    const r = el.getBoundingClientRect(), b = bubble.getBoundingClientRect();
    let left = r.right + 12, top = r.top + (r.height - b.height) / 2;
    if (left + b.width > innerWidth - 12) { left = r.left + (r.width - b.width) / 2; top = r.top - b.height - 10; }
    bubble.style.left = Math.max(12, Math.min(left, innerWidth - b.width - 12)) + 'px';
    bubble.style.top = Math.max(12, Math.min(top, innerHeight - b.height - 12)) + 'px';
  }
  document.querySelectorAll('.nav-item[data-view], .home-card[data-goto], [data-tip]').forEach(el => {
    el.addEventListener('mouseenter', () => show(el)); el.addEventListener('mouseleave', hide);
    el.addEventListener('focus', () => show(el)); el.addEventListener('blur', hide); el.addEventListener('click', hide);
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') hide(); });
  window.addEventListener('resize', hide); window.addEventListener('scroll', hide, true);
  const tips = document.getElementById('pref-tooltips'), motion = document.getElementById('pref-motion');
  function apply() {
    document.documentElement.classList.toggle('reduce-motion', !prefs.motion);
    if (tips) tips.checked = prefs.tooltips; if (motion) motion.checked = prefs.motion;
    if (!prefs.tooltips) hide();
  }
  function save() { try { localStorage.setItem(key, JSON.stringify(prefs)); } catch (e) { /* 浏览器不允许持久化 */ } apply(); }
  tips.addEventListener('change', () => { prefs.tooltips = tips.checked; save(); });
  motion.addEventListener('change', () => { prefs.motion = motion.checked; save(); });
  document.getElementById('pref-api').addEventListener('click', () => document.getElementById('btn-settings').click());
  apply();
})();
