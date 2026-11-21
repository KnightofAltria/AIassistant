'use strict';
window.CSLA_MOBILE = document.documentElement.dataset.platform === 'android'
  || /CSLAAndroid\/1/.test(navigator.userAgent);
if (window.CSLA_MOBILE) {
  let restoring = true;
  let sessionTimer, prefsTimer, activeImport = null;
  function persistSession(immediate = false) {
    if (restoring || typeof state === 'undefined' || document.getElementById('app')?.classList.contains('hidden')) return;
    clearTimeout(sessionTimer);
    const save = () => {
      const body = {view: state.view, subject_id: state.subject?.id || '',
        chapter_id: state.chapter?.id || '', folder_id: state.folderId || '',
        conversation_id: state.conversationId || '', material_id: state.readerId || '',
        chat_draft: document.getElementById('chat-input')?.value || ''};
      fetch('/api/mobile/session', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body), keepalive: true}).catch(() => {});
    };
    if (immediate === true) save();
    else sessionTimer = setTimeout(save, 180);
  }
  window.addEventListener('csla:preferences', event => {
    clearTimeout(prefsTimer);
    const prefs = event.detail;
    prefsTimer = setTimeout(() => {
      fetch('/api/mobile/preferences', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(prefs), keepalive: true}).catch(() => {});
    }, 160);
  });
  window.restoreMobileSession = async explicitView => {
    restoring = true;
    try {
      const saved = await api('/api/mobile/session');
      const input = document.getElementById('chat-input');
      if (input) input.value = saved.chat_draft || '';
      if (saved.conversation_id) {
        const data = await api('/api/conversations');
        if ((data.conversations || []).some(c => c.id === saved.conversation_id)) {
          await openConversation(saved.conversation_id);
        }
      }
      if (explicitView && explicitView !== saved.view) return;
      const view = saved.view || 'home';
      if (!document.getElementById('view-' + view)) return;
      if (view === 'study') {
        const {subjects} = await api('/api/subjects');
        switchView('study', {restore: true, replace: true});
        const subject = subjects.find(s => s.id === saved.subject_id);
        if (subject) {
          openSubject(subject);
          const chapter = subject.chapters.find(c => c.id === saved.chapter_id);
          if (chapter) await openChapter(chapter);
        } else await loadSubjects();
      } else if (view === 'materials' || view === 'reader') {
        const {folders, materials} = await api('/api/materials');
        state.folderId = folders.some(f => f.id === saved.folder_id) ? saved.folder_id : '';
        const id = new URLSearchParams(location.search).get('id') || saved.material_id;
        if (view === 'reader' && materials.some(m => m.id === id)) {
          state.readerId = id;
          switchView('reader', {restore: true, replace: true});
        } else switchView('materials', {restore: true, replace: true});
      } else switchView(view, {replace: true});
    } catch (_) { /* 启动失败时保留可用首页，失效对象不恢复。 */ }
    finally { restoring = false; persistSession(); }
  };
  window.uploadMobileFile = async (file, metadata, progress) => {
    if (activeImport) throw new Error('请先完成当前导入');
    const job = {xhr: null, id: '', cancelled: false, parsing: false};
    activeImport = job;
    try {
      const prepared = await api('/api/mobile/import/prepare', {
        method: 'POST', body: JSON.stringify({...metadata, size: file.size})});
      job.id = prepared.upload_id;
      if (job.cancelled) {
        await api('/api/mobile/import/cancel', {method: 'POST', body: JSON.stringify({upload_id: job.id})});
        throw new Error('已取消导入');
      }
      return await new Promise((resolve, reject) => {
        const xhr = job.xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/mobile/import');
        xhr.setRequestHeader('Content-Type', 'application/octet-stream');
        xhr.setRequestHeader('X-CSLA-Upload', job.id);
        xhr.timeout = 120000;
        xhr.upload.onprogress = event => {
          if (!event.lengthComputable) return;
          const pct = Math.min(100, Math.round(event.loaded / event.total * 100));
          progress(pct < 100 ? `正在传入本地库：${pct}%` : '传输完成，正在本机解析…');
        };
        xhr.upload.onload = () => {
          job.parsing = true;
          document.getElementById('imp-cancel').disabled = true;
        };
        xhr.onload = () => {
          let data;
          try { data = JSON.parse(xhr.responseText); } catch (_) { reject(new Error('导入响应无效')); return; }
          if (xhr.status >= 200 && xhr.status < 300) resolve(data);
          else reject(new Error(data.error?.message || '文件导入失败'));
        };
        xhr.onerror = () => reject(new Error('文件传输失败，请检查存储空间后重试'));
        xhr.ontimeout = () => reject(new Error('导入超时，请先查看资料列表确认结果后再重试'));
        xhr.onabort = () => reject(new Error('已取消导入'));
        xhr.send(file);
      });
    } finally {
      if (job.id) fetch('/api/mobile/import/cancel', {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({upload_id: job.id})}).catch(() => {});
      if (activeImport === job) activeImport = null;
      document.getElementById('imp-cancel').disabled = false;
    }
  };
  window.cancelMobileImport = () => {
    if (!activeImport) return true;
    if (activeImport.parsing) { toast('正在解析原文件，请稍等'); return false; }
    activeImport.cancelled = true;
    activeImport.xhr?.abort();
    return true;
  };
  window.openMobileChapterEditor = subject => {
    const box = document.getElementById('modal-mobile-chapter');
    document.getElementById('mobile-chapter-title').value = '';
    document.getElementById('mobile-chapter-outline').value = '';
    document.getElementById('mobile-chapter-msg').textContent = '';
    box.dataset.subject = subject.id;
    box.classList.remove('hidden');
  };
  window.renderMobileGraphList = data => {
    const canvas = document.getElementById('graph-canvas');
    if (!canvas) return;
    let list = document.getElementById('mobile-graph-list');
    if (!list) {
      list = document.createElement('details');
      list.id = 'mobile-graph-list';
      canvas.insertAdjacentElement('afterend', list);
    }
    list.innerHTML = '<summary>按列表打开图谱节点</summary>';
    for (const type of ['subject', 'chapter', 'material']) {
      const group = document.createElement('details');
      const nodes = (data.nodes || []).filter(n => n.type === type);
      const summary = document.createElement('summary');
      summary.textContent = `${{subject: '科目', chapter: '章节', material: '资料'}[type]}（${nodes.length}）`;
      group.appendChild(summary);
      nodes.forEach(node => {
        const button = document.createElement('button');
        button.className = 'btn small mobile-graph-node';
        button.textContent = node.label;
        button.dataset.node = node.id;
        button.onclick = () => graphNavigate(node);
        group.appendChild(button);
      });
      list.appendChild(group);
    }
  };
  window.handleAndroidBack = () => {
    const sidebar = document.getElementById('sidebar');
    if (sidebar?.classList.contains('mobile-open')) {
      sidebar.classList.remove('mobile-open');
      return true;
    }
    const graph = document.getElementById('graph-full');
    if (graph && !graph.classList.contains('hidden')) { closeGraphFull(); return true; }
    const modal = [...document.querySelectorAll('.modal:not(.hidden)')].at(-1);
    if (modal) {
      if (modal.id === 'modal-avatar-crop') document.getElementById('crop-cancel')?.click();
      else if (modal.id === 'modal-import') {
        if (window.cancelMobileImport()) document.getElementById('imp-cancel').click();
      } else modal.classList.add('hidden');
      return true;
    }
    if (typeof state === 'undefined' || typeof goBack !== 'function') return null;
    if (state.view === 'home') return false;
    goBack();
    return true;
  };
  document.documentElement.classList.add('csla-mobile');
  document.addEventListener('DOMContentLoaded', () => {
    const chapterModal = document.createElement('div');
    chapterModal.id = 'modal-mobile-chapter';
    chapterModal.className = 'modal hidden';
    chapterModal.innerHTML = `<div class="modal-card"><h3>添加本地章节</h3>
      <label>章节标题<input id="mobile-chapter-title" maxlength="120" placeholder="如：进程与线程"></label>
      <label>学习大纲<textarea id="mobile-chapter-outline" rows="6" placeholder="- 基本概念&#10;- 工作原理&#10;- 例题与练习"></textarea></label>
      <p class="muted small">无需 API Key 即可保存。配置密钥后可生成讲义与练习。</p>
      <p id="mobile-chapter-msg" role="status"></p><div class="modal-actions">
      <button id="mobile-chapter-cancel" class="btn">取消</button>
      <button id="mobile-chapter-save" class="btn primary">保存章节</button></div></div>`;
    document.body.appendChild(chapterModal);
    document.getElementById('mobile-chapter-cancel').onclick = () => chapterModal.classList.add('hidden');
    document.getElementById('mobile-chapter-save').onclick = async event => {
      const title = document.getElementById('mobile-chapter-title').value.trim();
      if (!title) { document.getElementById('mobile-chapter-msg').textContent = '请填写章节标题'; return; }
      event.target.disabled = true;
      try {
        await api(`/api/subjects/${chapterModal.dataset.subject}/chapters`, {method: 'POST', body: JSON.stringify({
          title, outline: document.getElementById('mobile-chapter-outline').value.trim()})});
        const {subjects} = await api('/api/subjects');
        const subject = subjects.find(s => s.id === chapterModal.dataset.subject);
        chapterModal.classList.add('hidden');
        if (subject) openSubject(subject);
        toast('章节已保存');
        persistSession();
      } catch (error) { document.getElementById('mobile-chapter-msg').textContent = error.message; }
      finally { event.target.disabled = false; }
    };
    document.getElementById('subj-ok').textContent = '创建科目';
    document.getElementById('subj-refs').checked = false;
    document.querySelector('#modal-subject .banner').textContent =
      '科目与资料文件夹可离线创建，再手动添加章节。已配置密钥时会自动生成章节大纲；自动下载开放教材需要联网。视频链接可按行粘贴保存。';
    document.querySelectorAll('.view').forEach(view => {
      new MutationObserver(persistSession).observe(view, {attributes: true, attributeFilter: ['class']});
    });
    document.addEventListener('input', persistSession);
    document.addEventListener('click', event => {
      persistSession();
      const anchor = event.target.closest('a');
      if (anchor && anchor.target === '_blank' && anchor.href && /^(https?:)$/.test(new URL(anchor.href).protocol)) {
        event.preventDefault();
        location.assign(anchor.href);
      }
    });
    window.addEventListener('pagehide', () => persistSession(true));
    if (window.visualViewport) {
      const resize = () => document.documentElement.style.setProperty('--mobile-viewport-height',
        Math.round(window.visualViewport.height) + 'px');
      window.visualViewport.addEventListener('resize', resize);
      resize();
    }
    document.querySelectorAll('.nav-item').forEach(button => button.addEventListener('click',
      () => document.getElementById('sidebar')?.classList.remove('mobile-open')));
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
