// npm install playwright; NODE_PATH=<node_modules> node tests/test_mobile_ui.cjs
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const { once } = require('events');
const path = require('path');

(async () => {
  const backend = spawn(process.env.PYTHON || 'python3',
    [path.join(__dirname, 'serve_ui.py')], {stdio: ['ignore', 'pipe', 'pipe']});
  let browser;
  try {
    const info = await new Promise((resolve, reject) => {
      let buffer = '';
      backend.stdout.on('data', chunk => {
        buffer += chunk;
        const line = buffer.split('\n').find(line => line.startsWith('{"url"'));
        if (line) resolve(JSON.parse(line));
      });
      backend.once('exit', code => reject(new Error('Local test runtime exited: ' + code)));
      backend.stderr.on('data', chunk => process.stderr.write(chunk));
    });
    browser = await chromium.launch({channel: process.env.BROWSER_CHANNEL || 'chrome', headless: true});
    const context = await browser.newContext({viewport: {width: 390, height: 780},
      userAgent: 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130.0.0.0 Mobile Safari/537.36 CSLAAndroid/1'});
    await context.addCookies([{name: 'csla_phone', value: info.cookie.split(';')[0].split('=')[1],
      url: info.url, httpOnly: true, sameSite: 'Strict'}]);
    const page = await context.newPage();
    const errors = [];
    const externalRequests = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => {
      if (/^https?:/.test(request.url()) && new URL(request.url()).origin !== info.url) {
        externalRequests.push(request.url());
      }
    });
    await page.goto(info.url + '/?view=materials');
    await page.locator('#app:not(.hidden)').waitFor();
    await page.locator('.mat-card, .material-card, #material-list > *').first().waitFor();
    if (await page.locator('#gate').isVisible()) throw new Error('API key blocks offline entry');
    await page.locator('#sidebar').evaluate(node => node.classList.add('mobile-open'));
    await page.locator('#btn-settings').click();
    await page.locator('#modal-settings:not(.hidden)').waitFor();
    await page.locator('#set-key').fill('中文输入测试');
    if (await page.locator('#set-key').inputValue() !== '中文输入测试') throw new Error('IME text lost');
    await page.locator('#set-cancel').click();
    await page.locator('.nav-item[data-view="study"]').click();
    await page.locator('#view-study.active').waitFor();
    await page.locator('#sidebar').evaluate(node => node.classList.add('mobile-open'));
    await page.locator('.nav-item[data-view="materials"]').click();
    await page.locator('#view-materials.active').waitFor();
    await page.waitForFunction(() => document.getElementById('sidebar').getBoundingClientRect().right <= 0);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2);
    if (overflow) throw new Error('Page overflows mobile viewport');
    if (errors.length) throw new Error('JavaScript errors: ' + errors.join(' | '));
    if (externalRequests.length) throw new Error('Offline startup made external requests');
    if (process.env.CSLA_SCREENSHOT) await page.screenshot({path: process.env.CSLA_SCREENSHOT});
    console.log('PASS: 390px offline entry, directory, settings, Chinese input, view navigation, no horizontal overflow or JS errors');
  } finally {
    if (browser) await browser.close();
    backend.kill('SIGTERM');
    if (backend.exitCode === null) await once(backend, 'exit');
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
