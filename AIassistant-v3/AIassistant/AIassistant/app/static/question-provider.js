'use strict';
(() => {
  const key = 'csla-question-provider';
  const controls = [...document.querySelectorAll('.question-provider')];
  const sync = value => controls.forEach(control => { control.checked = control.value === value; });
  sync(localStorage.getItem(key) === 'local-qwen' ? 'local-qwen' : 'deepseek');
  document.querySelector('#gate-local')?.addEventListener('click', async () => {
    try {
      const st = await api('/api/state');
      localStorage.setItem(key, 'local-qwen');
      sync('local-qwen');
      enterApp(st);
    } catch (e) { toast(e.message, true); }
  });
  controls.forEach(control => control.addEventListener('change', () => {
    localStorage.setItem(key, control.value);
    sync(control.value);
    window.showQuestionTimingAverage?.();
  }));
})();

// 记录本浏览器实际完成的请求；失败和无新增题目不计入平均值。
(() => {
  const key = 'csla-question-timing-v2-nf4';
  const read = () => {
    try { const data = JSON.parse(localStorage.getItem(key) || '{}'); return data && typeof data === 'object' ? data : {}; }
    catch (_) { return {}; }
  };
  const seconds = ms => `${(ms / 1000).toFixed(1)} 秒`;
  const samples = (provider, count) => {
    const values = read()[`${provider}:${count}`];
    return Array.isArray(values) ? values.filter(x => Number.isFinite(x.ms) && x.ms >= 0 && x.actual > 0) : [];
  };
  const average = (provider, count) => {
    const rows = samples(provider, count);
    if (!rows.length) return '暂无成功样本，完成本次后开始统计';
    const total = rows.reduce((sum, row) => sum + row.ms, 0);
    const questions = rows.reduce((sum, row) => sum + row.actual, 0);
    return `同模型、请求 ${count} 道：平均每次 ${seconds(total / rows.length)} · 折合每道 ${seconds(total / questions)}（最近 ${rows.length} 次成功记录）`;
  };
  window.showQuestionTimingAverage = () => {
    const el = document.querySelector('#question-timing');
    if (!el || el.dataset.running) return;
    const provider = localStorage.getItem('csla-question-provider') === 'local-qwen' ? 'local-qwen' : 'deepseek';
    el.textContent = average(provider, Number(document.querySelector('#question-count')?.value) || 3);
  };
  window.beginQuestionTiming = (provider, count) => {
    const el = document.querySelector('#question-timing');
    const started = performance.now();
    const token = String(started);
    const name = provider === 'local-qwen' ? '本地 Qwen' : 'DeepSeek';
    if (el) el.dataset.running = token;
    const draw = () => {
      if (!el?.isConnected || el.dataset.running !== token) return;
      el.textContent = `${name} · 正在生成 ${count} 道 · 已等待 ${seconds(performance.now() - started)}。${average(provider, count)}。计时包含模型加载、生成和校验，不代表进度。`;
    };
    draw();
    const timer = setInterval(draw, 250);
    return (ok, actual) => {
      clearInterval(timer);
      const elapsed = performance.now() - started;
      let saved = true;
      if (ok && actual > 0) {
        try {
          const data = read();
          data[`${provider}:${count}`] = [...samples(provider, count), {ms: elapsed, actual}].slice(-50);
          localStorage.setItem(key, JSON.stringify(data));
        } catch (_) { saved = false; }
      }
      if (!el?.isConnected || el.dataset.running !== token) return;
      delete el.dataset.running;
      el.textContent = `${name} · ${ok ? `完成，新增 ${actual} 道` : '生成失败'} · 本次耗时 ${seconds(elapsed)}。${average(provider, count)}${saved ? '' : '（浏览器未能保存本次统计）'}`;
    };
  };
})();
