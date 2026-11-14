/* 轻量的视觉偏好与首页氛围；不读取或上传用户资料。 */
(() => {
  const key = 'csla.interface.preferences.v1';
  const defaults = {tooltips:true,motion:true,pointer:true,mascot:true,math:true,
    largeText:false,wrapCode:true,outlineExpanded:false,confirmDelete:true};
  let prefs = {...defaults};
  try { const saved = JSON.parse(localStorage.getItem(key) || '{}');
    for (const k of Object.keys(defaults)) if (typeof saved[k] === 'boolean') prefs[k] = saved[k];
  } catch (e) { /* 默认偏好 */ }
  const descriptions = {
    profile: '查看和编辑你的个人信息、头像与学习档案。',
    chat: '围绕课程资料提问，并查看回答的依据。',
    dashboard: '查看学习进度、复习安排和学习记录。',
    summary: '回顾对话总结、章节小结和易错内容。',
    study: '按课程和章节学习，完成练习。',
    materials: '导入、浏览和整理你的学习资料。',
    preferences: '调整界面提示、动态效果和模型设置。',
  };
  const titleChoices = ['今天学点什么？', '让好奇心带路。', '今天，也向前一步。', '从一个问题开始。', '把想法变成理解。',
    '每次弄懂一点，就更近一步。', '为新的发现，留一点时间。', '把问号，慢慢变成答案。', '知识有边界，好奇没有。',
    '今天的思考，明天的底气。', '给灵感一个落脚点。', '拆开难题，看见原理。', '让每一次练习都有回响。',
    '沿着问题，走向理解。', '慢一点，也能想得更深。', '从已知出发，遇见未知。'];
  let lastTitle = '';
  let titleBag = [];
  window.refreshHomeTitle = () => {
    if (!titleBag.length) {
      titleBag = [...titleChoices];
      for (let i=titleBag.length-1;i>0;i--) { const j=Math.floor(Math.random()*(i+1)); [titleBag[i],titleBag[j]]=[titleBag[j],titleBag[i]]; }
      if (titleBag.at(-1) === lastTitle) [titleBag[0],titleBag[titleBag.length-1]] = [titleBag.at(-1),titleBag[0]];
    }
    lastTitle = titleBag.pop();
    const title = document.querySelector('.home-title');
    title.textContent = ''; title.setAttribute('aria-label', lastTitle);
    const reveal = document.createElement('span');
    reveal.className = 'title-reveal'; reveal.setAttribute('aria-hidden', 'true');
    reveal.style.setProperty('--title-duration', `${550 + [...lastTitle].length * 48}ms`);
    const text = document.createElement('span');
    text.className = 'title-text'; text.textContent = lastTitle;
    reveal.appendChild(text); title.appendChild(reveal);
  };
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
  function apply() {
    document.documentElement.classList.toggle('reduce-motion', !prefs.motion);
    document.documentElement.classList.toggle('large-reading', prefs.largeText);
    document.documentElement.classList.toggle('wrap-code', prefs.wrapCode);
    document.documentElement.classList.toggle('hide-mascot', !prefs.mascot);
    for (const k of Object.keys(defaults)) {
      const input = document.querySelector(`[data-pref="${k}"]`);
      if (input) input.checked = prefs[k];
    }
    if (!prefs.tooltips) hide();
    window.dispatchEvent(new CustomEvent('csla:preferences',{detail:{...prefs}}));
  }
  function save() { try { localStorage.setItem(key, JSON.stringify(prefs)); } catch (e) { /* 浏览器不允许持久化 */ } apply(); }
  document.querySelectorAll('[data-pref]').forEach(input => input.addEventListener('change', () => {
    prefs[input.dataset.pref] = input.checked; save();
  }));
  window.UIPrefs = {get:name=>prefs[name], motion:()=>prefs.motion && !matchMedia('(prefers-reduced-motion: reduce)').matches};
  document.getElementById('pref-reset').addEventListener('click', () => {prefs={...defaults}; save();});
  document.getElementById('pref-api').addEventListener('click', () => document.getElementById('btn-settings').click());
  apply();
})();
