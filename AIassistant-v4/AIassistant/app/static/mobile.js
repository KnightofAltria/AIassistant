'use strict';
window.CSLA_MOBILE = document.documentElement.dataset.platform === 'android'
  || /CSLAAndroid\/1/.test(navigator.userAgent);
if (window.CSLA_MOBILE) {
  document.documentElement.classList.add('csla-mobile');
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.nav-item').forEach(button => button.addEventListener('click',
      () => document.getElementById('sidebar')?.classList.remove('mobile-open')));
    document.addEventListener('click', event => {
      const button = event.target.closest('#btn-tutor');
      if (button) button.textContent = '生成下一节';
    });
    const open = document.getElementById('reader-open-local');
    if (open) open.textContent = '在手机阅读';
    const settings = document.getElementById('modal-settings')?.querySelector('.modal-card');
    if (settings) {
      const note = document.createElement('p');
      note.className = 'muted small';
      note.textContent = '资料、记录和密钥仅存此手机。提问与生成会把问题及所需资料片段发送给 DeepSeek；离线仍可阅读和作答。生成时请保持应用在前台。';
      settings.appendChild(note);
      const clear = document.createElement('button');
      clear.className = 'btn';
      clear.textContent = '清除手机保存的 API Key';
      clear.onclick = async () => {
        if (!confirm('清除密钥？本地资料与学习记录会保留。')) return;
        try {
          await api('/api/mobile/key/clear', {method: 'POST', body: '{}'});
          document.getElementById('set-key').value = '';
          toast('API Key 已清除');
        } catch (error) { toast(error.message, true); }
      };
      settings.appendChild(clear);
    }
  });
}
