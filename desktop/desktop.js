/* Native desktop integration; shared web/mobile files stay reusable. */
(() => {
  window.CSLA_DESKTOP = true;
  document.getElementById('entry-default').addEventListener('click', () => {
    document.getElementById('entry-choice').classList.add('hidden');
  });
  const browse = document.createElement('button');
  browse.id = 'desktop-browse';
  browse.className = 'btn wide';
  browse.textContent = '暂不配置，先阅读资料';
  browse.addEventListener('click', async () => {
    try {
      const status = await api('/api/state');
      renderAccount(status.auth);
      enterApp(status);
    } catch (error) { toast(error.message, true); }
  });
  document.getElementById('gate-submit').after(browse);
  document.querySelector('#gate .gate-hint').textContent =
    'Key 保存在此电脑的当前账号内。AI 对话、讲解和出题需要联网及 DeepSeek API Key；资料阅读和管理可直接使用。';
  const ready = new Promise(resolve => {
    if (window.pywebview?.api) resolve();
    else window.addEventListener('pywebviewready', resolve, {once: true});
  });
  async function save(path) {
    await ready;
    const result = await window.pywebview.api.save_file(path);
    if (result.error) toast(result.error, true);
    else if (result.ok) toast(`已保存 ${result.name}`);
  }
  function route(url) {
    const target = new URL(url, location.href);
    if (target.origin !== location.origin) {
      ready.then(() => window.pywebview.api.open_external(target.href));
      return;
    }
    const match = target.pathname.match(/^\/api\/materials\/([\w-]+)\/source$/);
    if (match && target.searchParams.get('download') !== '1') {
      openSourceLocally(match[1]);
    } else if (/^\/api\/(?:export\/report|profile\/[\w-]+\/download|chapters\/[\w-]+\/lecture)$/.test(target.pathname)
               || (match && target.searchParams.get('download') === '1')) {
      save(target.pathname + target.search);
    } else {
      location.assign(target.pathname + target.search + target.hash);
    }
  }
  const report = document.getElementById('btn-export-report');
  if (report) {
    report.removeEventListener('click', exportReport);
    report.addEventListener('click', () => save('/api/export/report'));
  }
  window.open = url => { route(url); return null; };
  document.addEventListener('click', event => {
    const anchor = event.target.closest('a[href]');
    if (!anchor) return;
    const target = new URL(anchor.href, location.href);
    if (anchor.target === '_blank' || anchor.hasAttribute('download')
        || target.origin !== location.origin || /\/source$/.test(target.pathname)) {
      event.preventDefault();
      route(anchor.href);
    }
  }, true);
})();
