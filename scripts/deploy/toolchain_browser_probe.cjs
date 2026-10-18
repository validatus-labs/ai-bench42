// Trusted host-toolchain canary, run only in the candidate runtime namespace.
// Node -> pinned Playwright -> Brave -> kernel sandbox -> data fixture.
const fs = require('node:fs');
const path = require('node:path');
const {createRequire} = require('node:module');
const load = createRequire('/npm/node_modules/@playwright/mcp/package.json');
let chromium;
try { chromium = load('playwright').chromium; }
catch { chromium = load('playwright-core').chromium; }
(async () => {
  const browser = await chromium.launch({
    executablePath: '/opt/brave.com/brave/brave', headless: true,
    chromiumSandbox: true,
    args: ['--disable-background-networking', '--disable-component-update', '--no-first-run']
  });
  try {
    const context = await browser.newContext({serviceWorkers: 'block', acceptDownloads: false});
    const page = await context.newPage();
    await page.goto('chrome://sandbox/');
    const status = await page.locator('body').innerText();
    if (!/Seccomp-BPF sandbox\s+Yes/i.test(status) || !/(Namespace sandbox|PID namespaces)\s+Yes/i.test(status))
      throw new Error('Browser namespace/seccomp sandbox is not enabled');
    const session = await browser.newBrowserCDPSession();
    const processes = await session.send('SystemInfo.getProcessInfo');
    const renderers = processes.processInfo.filter(x => x.type === 'renderer').map(x => {
      const text = fs.readFileSync(`/proc/${x.id}/status`, 'utf8');
      return {pid:x.id, seccomp:Number(text.match(/^Seccomp:\s+(\d+)/m)?.[1]),
        no_new_privs:Number(text.match(/^NoNewPrivs:\s+(\d+)/m)?.[1])};
    });
    if (!renderers.some(x => x.seccomp === 2 && x.no_new_privs === 1))
      throw new Error('No live sandboxed renderer could be verified');
    const marker = process.argv[2];
    await page.goto('data:text/html,<h1>' + encodeURIComponent(marker) + '</h1>');
    if ((await page.locator('h1').innerText()) !== marker) throw new Error('Browser fixture failed');
    if (context.serviceWorkers().length) throw new Error('Unexpected service worker');
    await context.close();
    console.log(JSON.stringify({status:'PASS', marker, version:browser.version(), renderers,
      namespace_seccomp:true, service_workers:'block', profile:'fresh', downloads:false}));
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode=1; });
