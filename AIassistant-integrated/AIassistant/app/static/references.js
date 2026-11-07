/* 每个资料文件夹的教材、目录与章节。复用资料原文件和审核权限。 */
let REFERENCE_EDIT = null;

async function renderReferencePanel() {
  const box = $('#reference-panel');
  const folderId = state.folderId;
  const refs = MATERIALS.filter((m) => m.is_reference && m.status === 'approved');
  const editable = CUR_FOLDER && canEditFolder(CUR_FOLDER);
  box.innerHTML = `<div class="reference-heading"><div><h3>主要参考文献</h3>
    <p class="muted small">${CUR_FOLDER ? esc(CUR_FOLDER.name) + ' · 优先参照教材目录和原文生成章节、讲义。' : '选择文件夹管理教材。下面是各科目的主要参考文献。'}</p></div>
    ${editable ? '<button id="ref-import" class="btn">上传教材</button>' : ''}</div>
    <div class="reference-list">${refs.length ? refs.map((m) => {
      let bib = {}; try { bib = JSON.parse(m.bibliography || '{}'); } catch (e) {}
      let toc = []; try { toc = JSON.parse(m.reference_toc || '[]'); } catch (e) {}
      return `<article class="reference-book">
        <span class="tag reference-tag">主要参考文献${bib.pages ? ' · ' + Number(bib.pages) + '页PDF' : ''}</span>
        <h4>${esc(m.title)}</h4><p class="muted small">${esc(bib.author || '')} ${esc(bib.institution || '')}</p>
        ${bib.description ? `<p class="small">${esc(bib.description)}</p>` : ''}
        <p class="muted small">${esc(bib.language || '')} · ${toc.length} 个目录条目</p>
        <div class="card-actions">
          <button class="btn small" data-ref-read="${m.id}">阅读教材</button>
          <a class="btn small" href="/api/materials/${m.id}/source" target="_blank" rel="noopener">原版PDF / 源文件</a>
          ${canEditMaterial(m) ? `<button class="btn primary small" data-ref-edit="${m.id}">目录与生成章节</button>
          <button class="btn small" data-ref-remove="${m.id}">移出参考文献</button>` : '<span class="muted small">核心资料 · 只读</span>'}
        </div></article>`;
    }).join('') : '<p class="muted">这个文件夹还没有主要参考文献。上传教材，或从下方官方开放教材中选择。</p>'}</div>
    ${editable ? '<details class="reference-catalog"><summary id="ref-catalog-summary">添加官方教材与专题PDF</summary><p class="muted small">完整教材、官方单章、作者讲义和协议规范分别标注，可配合中文专题资料学习。已下载文件会直接导入。</p><label class="field"><span>筛选科目</span><select id="ref-catalog-subject"><option value="">全部科目</option><option value="co">计算机组成原理</option><option value="cn">计算机网络</option><option value="os">操作系统</option><option value="ds">数据结构</option></select></label><div id="ref-catalog-list"></div><p id="ref-download-msg" class="small"></p></details>' : ''}`;
  box.querySelectorAll('[data-ref-read]').forEach((b) => b.addEventListener('click', () => openMaterial(b.dataset.refRead)));
  box.querySelectorAll('[data-ref-edit]').forEach((b) => b.addEventListener('click', () => editReference(MATERIALS.find((m) => m.id === b.dataset.refEdit))));
  box.querySelectorAll('[data-ref-remove]').forEach((b) => b.addEventListener('click', async () => {
    try {
      await api(`/api/materials/${b.dataset.refRemove}/reference`, { method: 'POST', body: JSON.stringify({ enabled: false }) });
      await loadMaterials(); toast('已移出主要参考文献，教材文件仍保留');
    } catch (err) { toast(err.message, true); }
  }));
  $('#ref-import')?.addEventListener('click', async () => {
    $('#btn-import').click();
    // 导入弹窗异步读取科目和文件夹，使用观察器在打开时勾选。
    const modal = $('#modal-import');
    const observer = new MutationObserver(() => {
      if (!modal.classList.contains('hidden')) { $('#imp-reference').checked = true; observer.disconnect(); }
    });
    observer.observe(modal, { attributes: true, attributeFilter: ['class'] });
  });
  if (!editable) return;
  try {
    const { books } = await api('/api/references/catalog');
    if (state.folderId !== folderId || !$('#ref-catalog-list')) return;
    $('#ref-catalog-summary').textContent = `添加官方教材与专题PDF（${books.length}份已核验）`;
    const select = $('#ref-catalog-subject');
    select.value = ['co', 'cn', 'os', 'ds'].includes(CUR_FOLDER?.slug) ? CUR_FOLDER.slug : '';
    const renderCatalog = () => {
    $('#ref-catalog-list').innerHTML = books.filter((b) => !select.value || b.subject_slug === select.value).map((b) => `<div class="reference-catalog-row"><div>
      <b>${esc(b.title)}</b><p class="muted small">${esc(b.kind || '完整教材')} · ${esc(b.institution)} · ${Number(b.pages)}页 · ${esc(b.license)}</p>
      <a href="${esc(b.homepage)}" target="_blank" rel="noopener">查看官方来源</a></div>
      <button class="btn small" data-ref-download="${b.id}">${b.cached ? '导入已下载PDF' : '下载并导入PDF'}</button></div>`).join('');
    box.querySelectorAll('[data-ref-download]').forEach((btn) => btn.addEventListener('click', async () => {
      btn.disabled = true;
      const msg = $('#ref-download-msg');
      msg.textContent = '正在下载 / 校验并导入PDF，请稍候…';
      try {
        await api('/api/references/download', { method: 'POST',
          body: JSON.stringify({ book_id: btn.dataset.refDownload, folder_id: folderId }) });
        if (state.folderId === folderId) await loadMaterials();
        toast('教材PDF已导入并设为主要参考文献');
      } catch (err) { msg.textContent = err.message; toast(err.message, true); }
      finally { btn.disabled = false; }
    }));
    };
    select.addEventListener('change', renderCatalog);
    renderCatalog();
  } catch (err) { toast(err.message, true); }
}

async function setMaterialReference(material) {
  if (!material.folder_id) { toast('请先把教材移动到一个文件夹', true); return; }
  try {
    if (!material.is_reference) {
      const d = await api(`/api/materials/${material.id}/reference`, { method: 'POST', body: JSON.stringify({ enabled: true }) });
      material = d.material;
      await loadMaterials();
    }
    await editReference(material);
  } catch (err) { toast(err.message, true); }
}

async function editReference(material) {
  if (!material) return;
  REFERENCE_EDIT = material;
  const { subjects } = await api('/api/subjects');
  const folder = FOLDERS.find((f) => f.id === material.folder_id);
  const targets = subjects.filter((s) => s.name === folder?.name);
  $('#ref-modal-title').textContent = material.title + ' · 目录与章节';
  const toc = JSON.parse(material.reference_toc || '[]');
  $('#ref-toc').value = toc.map((t) => `${t.title} | ${t.page || 0} | ${t.level || 1}`).join('\n');
  $('#ref-granularity').value = 'chapter';
  $('#ref-subject').innerHTML = targets.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join('');
  $('#ref-msg').textContent = targets.length ? '' : '请先创建与文件夹同名的科目，或将教材移入科目文件夹。';
  $('#ref-plan').disabled = !targets.length;
  $('#ref-preview').innerHTML = '';
  $('#ref-apply').disabled = true;
  openModal('#modal-reference');
}

$('#ref-close').addEventListener('click', () => closeModal('#modal-reference'));
$('#ref-toc').addEventListener('input', () => { $('#ref-apply').disabled = true; $('#ref-preview').innerHTML = ''; });
$('#ref-subject').addEventListener('change', () => { $('#ref-apply').disabled = true; $('#ref-preview').innerHTML = ''; });
$('#ref-granularity').addEventListener('change', () => { $('#ref-apply').disabled = true; $('#ref-preview').innerHTML = ''; });

async function saveReferenceToc() {
  const previous = JSON.parse(REFERENCE_EDIT.reference_toc || '[]');
  const toc = $('#ref-toc').value.split('\n').filter((s) => s.trim()).map((line, index) => {
    const parts = line.split('|');
    const title = parts[0].trim();
    const page = parts.length > 1 ? parts[1].trim() : 0;
    const old = (previous[index]?.title === title ? previous[index] : previous.find((t) => t.title === title)) || {};
    const level = parts.length > 2 ? parts[2].trim() : old.level || 1;
    return { ...old, title, page, level };
  });
  const d = await api(`/api/materials/${REFERENCE_EDIT.id}/reference`, {
    method: 'POST', body: JSON.stringify({ enabled: true, toc }) });
  REFERENCE_EDIT = d.material;
}

$('#ref-save').addEventListener('click', async () => {
  try { await saveReferenceToc(); await loadMaterials(); $('#ref-msg').textContent = '目录已保存'; $('#ref-apply').disabled = true; }
  catch (err) { $('#ref-msg').textContent = err.message; }
});
$('#ref-plan').addEventListener('click', async () => {
  const btn = $('#ref-plan'); btn.disabled = true;
  try {
    await saveReferenceToc();
    const d = await api(`/api/materials/${REFERENCE_EDIT.id}/reference/chapters`, {
      method: 'POST', body: JSON.stringify({ subject_id: $('#ref-subject').value, granularity: $('#ref-granularity').value }) });
    $('#ref-preview').innerHTML = '<p class="small">按教材顺序添加，同名章节跳过。大章会以书中小节作为教学单元。</p>' +
      d.chapters.map((c) => `<div class="reference-plan-row"><span>${esc(c.title)}${c.page ? ' · PDF ' + Number(c.page) + '页' : ''} · ${Number(c.unit_count)}个教学单元</span>
        <span class="tag">${c.action === 'skip' ? '已存在 · 跳过' : '新增'}</span></div>`).join('');
    $('#ref-apply').disabled = !d.chapters.some((c) => c.action === 'add');
    $('#ref-msg').textContent = '';
  } catch (err) { $('#ref-msg').textContent = err.message; }
  finally { btn.disabled = false; }
});
$('#ref-apply').addEventListener('click', async () => {
  const btn = $('#ref-apply'); btn.disabled = true;
  try {
    const d = await api(`/api/materials/${REFERENCE_EDIT.id}/reference/chapters`, {
      method: 'POST', body: JSON.stringify({ subject_id: $('#ref-subject').value, granularity: $('#ref-granularity').value, apply: true }) });
    $('#ref-msg').textContent = `已添加 ${d.created.length} 章，跳过 ${d.skipped} 个已有章节。可到「科目学习」查看并生成完整讲义。`;
    await loadMaterials();
  } catch (err) { $('#ref-msg').textContent = err.message; btn.disabled = false; }
});
