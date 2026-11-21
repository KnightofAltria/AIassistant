// Real phone UI workflows against an isolated runtime with fake model responses.
const {chromium} = require('playwright');
const {spawn} = require('child_process');
const {once} = require('events');
const path = require('path');
const fs = require('fs');
async function eventually(check) {
  const deadline = Date.now() + 10000;
  while (!await check()) {
    if (Date.now() > deadline) throw new Error('Persisted state did not reach expected value');
    await new Promise(resolve => setTimeout(resolve, 50));
  }
}

(async () => {
  const backend = spawn(process.env.PYTHON || 'python3',
    [path.join(__dirname, 'serve_ui.py'), '--fixtures'], {stdio: ['ignore', 'pipe', 'pipe']});
  let browser;
  const evidence = [];
  try {
    const info = await new Promise((resolve, reject) => {
      let buffer = '';
      backend.stdout.on('data', data => {
        buffer += data;
        const line = buffer.split('\n').find(line => line.startsWith('{"url"'));
        if (line) resolve(JSON.parse(line));
      });
      backend.stderr.on('data', data => process.stderr.write(data));
      backend.on('exit', code => reject(new Error('Runtime exited: ' + code)));
    });
    browser = await chromium.launch({channel: 'chrome', headless: true});
    const context = await browser.newContext({viewport: {width: 390, height: 780}, acceptDownloads: true,
      userAgent: 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130.0.0.0 Mobile Safari/537.36 CSLAAndroid/1'});
    await context.addCookies([{name: 'csla_phone', value: info.cookie.split(';')[0].split('=')[1],
      url: info.url, httpOnly: true, sameSite: 'Strict'}]);
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    const errors = [], external = [], sessionTrace = [];
    page.on('response', async response => {
      if (response.url().endsWith('/api/mobile/session')) {
        sessionTrace.push({method: response.request().method(), body: response.request().postData(),
          response: await response.text().catch(() => '')});
      }
    });
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => {
      if (/^https?:/.test(request.url()) && new URL(request.url()).origin !== info.url) external.push(request.url());
    });
    const nav = async view => {
      if (view === 'home') {
        await page.locator('.view.active .view-nav button').nth(1).click();
        await page.locator('#view-home.active').waitFor();
        return;
      }
      await page.locator('#sidebar').evaluate(node => node.classList.add('mobile-open'));
      await page.locator(`.nav-item[data-view="${view}"]`).click();
      await page.locator(`#view-${view}.active`).waitFor();
      if (view === 'profile') await page.evaluate(() => loadMeta());
    };
    const shot = async name => {
      if (process.env.CSLA_EVIDENCE_DIR) {
        fs.mkdirSync(process.env.CSLA_EVIDENCE_DIR, {recursive: true});
        await page.screenshot({path: path.join(process.env.CSLA_EVIDENCE_DIR, name + '.png'), fullPage: true});
      }
    };
    await page.goto(info.url);
    await page.locator('#app:not(.hidden)').waitFor();
    await page.waitForFunction(() => state.view === 'home');
    await nav('study');
    await page.locator('#btn-add-subject').click();
    await page.locator('#subj-name').fill('手机完整迁移测试');
    if (await page.locator('#subj-refs').isChecked()) throw new Error('Offline creation defaults to network');
    await page.locator('#subj-ok').click();
    await page.waitForFunction(() => state.subject?.name === '手机完整迁移测试');
    await page.locator('#btn-add-chapter').click();
    await page.locator('#mobile-chapter-title').fill('整数表示');
    await page.locator('#mobile-chapter-outline').fill('- 补码\n- 溢出\n- 位宽');
    await page.locator('#mobile-chapter-save').click();
    await page.locator('#chapter-list [data-act="open"]').click();
    await page.waitForFunction(() => state.chapter?.title === '整数表示');
    evidence.push('PASS: no-key subject and manual chapter created through visible UI');
    await page.waitForFunction(() => document.querySelector('#tutor-status')?.textContent.includes('0/3'));
    await eventually(() => page.evaluate(async () => (await api('/api/mobile/session')).chapter_id === state.chapter.id));
    await page.reload();
    await page.waitForFunction(() => state.chapter?.title === '整数表示').catch(async error => {
      console.error(sessionTrace);
      console.error(await page.evaluate(async () => ({view: state.view, chapter: state.chapter,
        subject: state.subject?.name, session: await api('/api/mobile/session'), url: location.href})));
      throw error;
    });
    evidence.push('PASS: chapter hierarchy restored after reload');
    await nav('preferences');
    await page.locator('[data-pref="largeText"]').check();
    await eventually(() => page.evaluate(async () => (await api('/api/mobile/preferences')).largeText === true));
    await page.reload();
    await page.locator('[data-pref="largeText"]').waitFor({state: 'visible'});
    if (!await page.locator('[data-pref="largeText"]').isChecked()) throw new Error('Preferences not restored');
    evidence.push('PASS: preference survives reload');
    await nav('profile');
    await page.locator('#meta-age').fill('21');
    await page.locator('#meta-major').fill('计算机科学');
    await page.locator('#meta-bio').fill('手机本地学习');
    await page.locator('#btn-save-meta').click();
    await eventually(() => page.evaluate(async () => (await api('/api/profile')).meta.bio === '手机本地学习'));
    await page.evaluate(() => {
      const canvas = document.createElement('canvas'); canvas.width = canvas.height = 64;
      canvas.getContext('2d').fillRect(0, 0, 64, 64);
      canvas.toBlob(blob => {
        window.cropFinished = false;
        chooseAvatarCrop(new File([blob], 'fixture.png', {type: 'image/png'}))
          .then(value => {window.cropFinished = value === null;});
      });
    });
    await page.locator('#modal-avatar-crop:not(.hidden)').waitFor();
    await page.evaluate(() => handleAndroidBack());
    await page.waitForFunction(() => window.cropFinished === true);
    const image = await page.evaluate(() => {
      const canvas = document.createElement('canvas'); canvas.width = canvas.height = 64;
      canvas.getContext('2d').fillRect(0, 0, 64, 64);
      return canvas.toDataURL('image/png').split(',')[1];
    });
    await page.locator('#avatar-file').setInputFiles({name: 'avatar-test.png', mimeType: 'image/png',
      buffer: Buffer.from(image, 'base64')});
    await page.locator('#modal-avatar-crop:not(.hidden)').waitFor();
    await page.locator('#crop-save').click();
    await page.waitForFunction(() => !!state.avatar);
    evidence.push('PASS: profile saved; avatar crop uploaded; native back resolves cancelled crop');
    await shot('个人信息');
    await nav('materials');
    await page.locator('#btn-import').click();
    await page.locator('#modal-import:not(.hidden)').waitFor();
    await page.locator('#imp-file').setInputFiles({name: '手机教材.md', mimeType: 'text/markdown',
      buffer: Buffer.from('# 第一章 补码\n\n补码是整数编码。\n# 第二章 溢出\n\n溢出要判断位宽。\n')});
    await page.waitForFunction(() => document.getElementById('imp-text').value.includes('补码'));
    await page.locator('#imp-folder').selectOption({label: '手机完整迁移测试'});
    await page.locator('#imp-reference').check();
    await page.locator('#imp-save').click();
    await page.locator('#modal-import').waitFor({state: 'hidden'}).catch(async error => {
      console.error('Import status:', await page.locator('#imp-msg').textContent(), errors);
      throw error;
    });
    await page.locator('.material-card').filter({hasText: '手机教材'}).waitFor();
    await page.locator('#mat-search').fill('手机教材');
    if (await page.locator('.material-card').count() !== 1) throw new Error('Material filter failed');
    await page.locator('.material-card [data-act="edit"]').click();
    await page.locator('#medit-title').fill('手机教材改名');
    await page.locator('#medit-ok').click();
    await page.locator('.material-card').filter({hasText: '手机教材改名'}).waitFor();
    await page.locator('.material-card [data-act="reference"]').click();
    await page.locator('#ref-toc').fill('第一章 补码 | 0 | 1\n第二章 溢出 | 0 | 1');
    await page.locator('#ref-save').click();
    await page.waitForFunction(() => document.getElementById('ref-msg').textContent === '目录已保存');
    await page.locator('#ref-plan').click();
    await page.locator('#ref-preview .reference-plan-row').first().waitFor();
    await page.locator('#ref-apply').click();
    await page.waitForFunction(() => document.getElementById('ref-msg').textContent.includes('已添加'));
    await page.locator('#ref-close').click();
    await page.locator('.material-card [data-act="open"]').click();
    await page.waitForFunction(() => READER.data?.material.title === '手机教材改名');
    await page.locator('[data-mode="source"]').click();
    if (!(await page.locator('#reader-body').textContent()).includes('补码')) throw new Error('Reader content missing');
    await page.evaluate(() => handleAndroidBack());
    await page.locator('#view-materials.active').waitFor();
    evidence.push('PASS: binary MD import, filter, rename, reference TOC/preview/apply, source reader/back');
    await shot('资料与参考文献');
    await nav('chat');
    if (!await page.locator('#conv-list').isVisible()) throw new Error('Chat history hidden on phone');
    await page.locator('#chat-input').fill('中文输入中');
    await page.locator('#chat-input').evaluate(node => node.dispatchEvent(
      new KeyboardEvent('keydown', {key: 'Enter', keyCode: 229, isComposing: true, bubbles: true, cancelable: true})));
    if (await page.locator('#chat-input').inputValue() !== '中文输入中') throw new Error('IME Enter sent prematurely');
    await eventually(() => page.evaluate(async () => (await api('/api/mobile/session')).chat_draft === '中文输入中'));
    await page.reload();
    await page.waitForFunction(() => document.getElementById('chat-input').value === '中文输入中');
    evidence.push('PASS: chat history visible, composing Enter guarded, draft restored');
    await page.locator('#sidebar').evaluate(node => node.classList.add('mobile-open'));
    await page.locator('#btn-settings').click();
    await page.locator('#sidebar').evaluate(node => node.classList.remove('mobile-open'));
    await page.locator('#set-key').fill('fake-fixture-key');
    await page.locator('#set-save').click();
    await page.locator('#modal-settings').waitFor({state: 'hidden'});
    await eventually(() => page.evaluate(async () => (await api('/api/state')).configured));
    await nav('chat');
    await page.locator('#chat-input').fill('补码是什么');
    await page.locator('#chat-form button').click();
    await page.waitForFunction(() => state.conversationId && !state.streaming);
    await page.locator('#conv-list .conv-rename').first().waitFor();
    page.once('dialog', dialog => dialog.accept('手机历史改名'));
    await page.locator('#conv-list .conv-rename').first().click();
    await page.locator('.conv-item').filter({hasText: '手机历史改名'}).waitFor();
    await page.locator('#btn-summarize').click();
    await page.waitForFunction(() => document.getElementById('btn-summarize').disabled === false);
    evidence.push('PASS: fake-model chat stream, history rename, conversation summary');
    await shot('聊天与历史');
    await nav('study');
    await page.locator('.subject-card').filter({hasText: '手机完整迁移测试'}).locator('[data-act="enter"]').click();
    await page.locator('.chapter-item').filter({hasText: '整数表示'}).locator('[data-act="open"]').click();
    await page.locator('#btn-tutor').click();
    await page.waitForFunction(() => !state.chapter.generating && document.getElementById('tutor-status').textContent.includes('1/3'));
    await page.locator('#btn-tutor-all').click();
    await page.waitForFunction(() => !state.chapter.generating && document.getElementById('tutor-status').textContent.includes('3/3'));
    await page.locator('.section-read').first().check();
    await page.locator('#question-count').selectOption('1');
    await page.locator('#btn-gen-q').click();
    await page.locator('.quiz-item .opt').first().waitFor();
    await page.locator('.quiz-item .opt').nth(1).click();
    await page.locator('.quiz-fb').waitFor();
    evidence.push('PASS: next/all section generation, read progress, grounded question generation and wrong answer grading');
    await shot('章节讲义与练习');
    await nav('summary');
    await page.locator('#summary-list .card').first().waitFor();
    await nav('dashboard');
    await page.locator('#mobile-graph-list').waitFor();
    await page.locator('#mobile-graph-list > summary').click();
    await page.locator('#mobile-graph-list details').nth(1).locator('summary').click();
    if (!await page.locator('.mobile-graph-node').count()) throw new Error('Graph list empty');
    await page.evaluate(() => openGraphFull());
    await page.locator('#graph-full:not(.hidden)').waitFor();
    await page.evaluate(() => handleAndroidBack());
    if (await page.evaluate(() => document.body.classList.contains('graph-lock'))) throw new Error('Graph lock stuck');
    await page.locator('#search-input').fill('补码');
    await page.locator('#search-form button').click();
    await page.locator('#search-results .search-hit').first().waitFor();
    await shot('学习看板');
    const download = page.waitForEvent('download');
    await page.locator('#btn-export-report').click();
    const file = await download;
    if (!file.suggestedFilename().endsWith('.docx')) throw new Error('Report export format mismatch');
    evidence.push('PASS: summary, mistakes/review/dashboard/search, graph list/back, DOCX report download');
    for (const width of [360, 390, 768]) {
      await page.setViewportSize({width, height: 780});
      for (const view of ['home', 'profile', 'preferences', 'chat', 'dashboard', 'summary', 'materials']) {
        await nav(view);
        if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2)) {
          throw new Error(`${width}px ${view} horizontal overflow`);
        }
      }
    }
    if (errors.length) throw new Error('JavaScript errors: ' + errors.join(' | '));
    if (external.length) throw new Error('Unexpected external requests: ' + external.join(' | '));
    evidence.push('PASS: 360/390/768px all main pages, no horizontal overflow, JS errors or external requests');
    console.log(evidence.join('\n'));
  } finally {
    if (browser) await browser.close();
    backend.kill('SIGTERM');
    if (backend.exitCode === null) await once(backend, 'exit');
  }
})().catch(error => {console.error(error.stack); process.exitCode = 1;});
