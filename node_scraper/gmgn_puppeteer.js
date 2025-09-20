#!/usr/bin/env node
import fs from 'fs';
import path from 'path';
import process from 'process';
import os from 'os';
import { fileURLToPath } from 'url';
import puppeteer from 'puppeteer-core';
import puppeteerExtra from 'puppeteer-extra';
import StealthPlugin from 'puppeteer-extra-plugin-stealth';

puppeteerExtra.use(StealthPlugin());

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i++) {
    const k = argv[i];
    if (k.startsWith('--')) {
      const key = k.slice(2);
      const next = argv[i + 1];
      if (!next || next.startsWith('--')) {
        args[key] = true;
      } else {
        args[key] = next;
        i++;
      }
    }
  }
  return args;
}

function parseProxy(proxyUrl) {
  try {
    const u = new URL(proxyUrl);
    const server = `${u.hostname}:${u.port || (u.protocol === 'https:' ? 443 : 80)}`;
    const creds = u.username ? { username: decodeURIComponent(u.username), password: decodeURIComponent(u.password || '') } : null;
    return { server, creds, protocol: u.protocol.replace(':','') };
  } catch {
    return null;
  }
}

function guessChromePath() {
  const localAppData = process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local');
  const candidates = [
    // Linux first
    '/usr/bin/google-chrome-stable',
    '/usr/bin/google-chrome',
    '/opt/google/chrome/google-chrome',
    '/usr/bin/chromium',
    // Windows fallbacks
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
    path.join(localAppData, 'Google', 'Chrome', 'Application', 'chrome.exe'),
  ];
  for (const p of candidates) {
    try { if (fs.existsSync(p)) return p; } catch {}
  }
  return null;
}

async function delay(ms) { return new Promise(r => setTimeout(r, ms)); }

async function extractAddresses(page, expectedCount) {
  const addrRegex = /\b[1-9A-HJ-NP-Za-km-z]{32,44}\b/g;
  const html = await page.content();
  const set = new Set();
  const found = html.match(addrRegex) || [];
  for (const a of found) {
    set.add(a);
    if (set.size >= expectedCount) break;
  }
  if (set.size >= expectedCount) return Array.from(set).slice(0, expectedCount);

  // Try reading innerText as well
  const inner = await page.evaluate(() => document.body?.innerText || '');
  const more = inner.match(addrRegex) || [];
  for (const a of more) {
    set.add(a);
    if (set.size >= expectedCount) break;
  }
  return Array.from(set).slice(0, expectedCount);
}

async function tryDismissConsent(page) {
  const selectors = [
    "button:has-text('Accept')",
    "button:has-text('Agree')",
    "text=Accept All",
    "#onetrust-accept-btn-handler",
  ];
  for (const s of selectors) {
    try {
      const el = await page.$(s);
      if (el) { await el.click({ delay: 20 }); await delay(200); }
    } catch {}
  }
}

async function waitForAddresses(page, expectedCount, timeoutMs = 60000) {
  const start = Date.now();
  const addrRegex = /\b[1-9A-HJ-NP-Za-km-z]{32,44}\b/;
  while (Date.now() - start < timeoutMs) {
    try {
      await tryDismissConsent(page);
      // Quick text probe
      const txt = await page.evaluate(() => document.body?.innerText || '');
      if (addrRegex.test(txt)) return true;
      // Probe HTML too
      const html = await page.content();
      if (addrRegex.test(html)) return true;
    } catch {}
    await delay(500);
  }
  return false;
}

async function isLoggedIn(page) {
  // Heuristic login detection: look for auth tokens or absence of login buttons
  try {
    return await page.evaluate(() => {
      const hasLoginText = !!document.querySelector('a[href*="login" i], a[href*="signin" i], button, a, div');
      const loginStrings = ['log in', 'login', 'sign in'];
      let hasLogin = false;
      // Scan some clickable elements for login text
      const els = Array.from(document.querySelectorAll('a,button,[role="button"],div,span'));
      for (const el of els.slice(0, 500)) {
        const t = (el.innerText || el.textContent || '').trim().toLowerCase();
        if (!t) continue;
        if (loginStrings.some(s => t.includes(s))) { hasLogin = true; break; }
      }

      // Local/session storage tokens
      const hasToken = (() => {
        try {
          const keys = [
            ...Array.from({length: localStorage.length}, (_, i) => localStorage.key(i)),
            ...Array.from({length: sessionStorage.length}, (_, i) => sessionStorage.key(i)),
          ];
          return keys.some(k => /auth|token|session|jwt/i.test(k || '') && (localStorage.getItem(k) || sessionStorage.getItem(k)));
        } catch { return false; }
      })();

      const hasAvatar = !!document.querySelector('img[alt*="avatar" i], [class*="avatar" i], [data-testid*="avatar" i]');
      const cookieStr = document.cookie || '';
      const hasCookie = /token|auth|session/i.test(cookieStr);

      // Logged in if token/cookie/avatar present; else not. If no explicit login controls found but no tokens either, assume not logged.
      return !!(hasToken || hasAvatar || hasCookie) && !hasLogin;
    });
  } catch {
    return false;
  }
}

function ensureDirSync(dir) {
  try { fs.mkdirSync(dir, { recursive: true }); } catch {}
}

function getDefaultSessionPath() {
  const dir = path.join(process.cwd(), '.sessions');
  ensureDirSync(dir);
  return path.join(dir, 'gmgn_ai_session.json');
}

async function loadCookies(page, cookies = []) {
  if (!cookies || !cookies.length) return;
  const normalized = cookies.map(c => {
    const copy = { ...c };
    if (!copy.domain && !copy.url) copy.url = 'https://gmgn.ai';
    return copy;
  });
  try { await page.setCookie(...normalized); } catch {}
}

async function loadStorage(page, storage = { localStorage: {}, sessionStorage: {} }) {
  try {
    await page.evaluate(({ ls, ss }) => {
      try { Object.entries(ls || {}).forEach(([k, v]) => localStorage.setItem(k, v)); } catch {}
      try { Object.entries(ss || {}).forEach(([k, v]) => sessionStorage.setItem(k, v)); } catch {}
    }, { ls: storage.localStorage || {}, ss: storage.sessionStorage || {} });
  } catch {}
}

async function saveSession(page, sessionFile) {
  try {
    const cookies = await page.cookies('https://gmgn.ai');
    const storage = await page.evaluate(() => ({
      localStorage: (() => { const o = {}; try { for (let i=0;i<localStorage.length;i++){const k=localStorage.key(i); o[k]=localStorage.getItem(k);} } catch{} return o; })(),
      sessionStorage: (() => { const o = {}; try { for (let i=0;i<sessionStorage.length;i++){const k=sessionStorage.key(i); o[k]=sessionStorage.getItem(k);} } catch{} return o; })(),
    }));
    ensureDirSync(path.dirname(sessionFile));
    fs.writeFileSync(sessionFile, JSON.stringify({ cookies, storage }, null, 2));
  } catch {}
}

async function main() {
  const args = parseArgs(process.argv);
  const url = args.url || 'https://gmgn.ai/trade/uZy0WmVx?chain=sol';
  const expectedCount = parseInt(args.count || '100', 10);
  const headless = (args.headless || 'false').toString().toLowerCase() === 'true';
  const panelsMode = !!args.panels || /\/sol\/address\//.test(url);
  const force = !!args.force;
  const profilePath = args.profile ? path.resolve(args.profile) : '';
  const proxyStr = args.proxy || '';
  const chromePath = args.chrome || guessChromePath();
  const cdpUrl = args.cdp || '';
  const sessionFile = args.session ? path.resolve(args.session) : getDefaultSessionPath();
  const outDir = args.outdir ? path.resolve(args.outdir) : path.join(process.cwd(), 'output', 'panels');

  const launchArgs = [
    '--disable-dev-shm-usage',
  ];

  let userDataDir = undefined;
  if (profilePath) {
    const base = path.basename(profilePath);
    if (/^Profile\s+\d+$/.test(base) || base === 'Default') {
      userDataDir = path.dirname(profilePath);
      launchArgs.push(`--profile-directory=${base}`);
    } else {
      userDataDir = profilePath;
    }
  }

  let proxy = null;
  if (proxyStr) {
    proxy = parseProxy(proxyStr);
    if (proxy) {
      launchArgs.push(`--proxy-server=${proxy.protocol || 'http'}://${proxy.server}`);
    }
  }

  let browser;
  let attached = false;
  if (cdpUrl) {
    try {
      // Normalize CDP URL (strip trailing slash)
      const normalized = cdpUrl.replace(/\/+$/, '');
  console.error(`[puppeteer] Attaching to Chrome via CDP at ${normalized}...`);
      browser = await puppeteerExtra.connect({ browserURL: normalized });
      attached = true;
    } catch (e) {
      console.error(`CDP attach failed (${e?.message || e}), falling back to launch.`);
    }
  }
  if (!browser) {
    const executablePath = chromePath || undefined;
    const baseLaunchOptions = {
      headless: headless ? 'new' : false,
      devtools: !headless,
      executablePath,
      ignoreDefaultArgs: [
        '--enable-automation',
        '--disable-extensions',
        '--no-first-run',
        '--no-default-browser-check',
      ],
      args: launchArgs,
    };
    try {
  console.error(`[puppeteer] Launching Chrome${userDataDir ? ' with profile' : ''}...`);
      const launchOptions = { ...baseLaunchOptions, ...(userDataDir ? { userDataDir } : {}) };
      browser = await puppeteerExtra.launch(launchOptions);
    } catch (e) {
      // Retry without userDataDir (profile may be locked by running Chrome)
      const errMsg = (e && e.message) || String(e || '');
  console.error('Profile may be locked; launching without profile. Session will be restored from saved cookies if available.');
      try {
        browser = await puppeteerExtra.launch(baseLaunchOptions);
      } catch (e2) {
        console.error(errMsg || e2);
        throw e2;
      }
    }
  }
  // Choose page strategy:
  // - If attached to existing Chrome: open a new tab to avoid hijacking user's current tab
  // - If launched with a profile (userDataDir set): reuse the first about:blank page (Chrome often opens one)
  // - Else: just open a new page
  let page = null;
  try {
    if (attached) {
      page = await browser.newPage();
    } else if (userDataDir) {
      const pages = await browser.pages();
      const blank = (pages || []).find(p => {
        try { return (p.url() === 'about:blank'); } catch { return false; }
      });
      page = blank || (pages && pages[0]) || null;
      if (!page) page = await browser.newPage();
    } else {
      page = await browser.newPage();
    }
  } catch {
    try { page = await browser.newPage(); } catch {}
  }

  // Lightweight headers and UA tweaks
  await page.setExtraHTTPHeaders({ 'Accept-Language': 'en-US,en;q=0.9' });
  try { await page.bringToFront(); } catch {}

  // Optional proxy auth
  if (proxy && proxy.creds) {
    await page.authenticate(proxy.creds);
  }

  // Try to restore session (cookies) before any navigation
  try {
    if (fs.existsSync(sessionFile)) {
      const json = JSON.parse(fs.readFileSync(sessionFile, 'utf-8'));
      await loadCookies(page, json.cookies || []);
    }
  } catch {}

  // Warm-up root and restore storage
  try {
    console.error('[puppeteer] Opening gmgn.ai root...');
    await page.goto('https://gmgn.ai/', { waitUntil: force ? 'domcontentloaded' : 'domcontentloaded', timeout: force ? 20000 : 45000 });
    try {
      if (fs.existsSync(sessionFile)) {
        const json = JSON.parse(fs.readFileSync(sessionFile, 'utf-8'));
        if (json.storage) {
          await loadStorage(page, json.storage);
          // Give the app a moment to pick up restored storage then reload once
          await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 }).catch(()=>{});
        }
      }
    } catch {}
    await delay(500);
    for (let i = 0; i < 2; i++) {
      await page.mouse.wheel({ deltaY: 200 + Math.floor(Math.random()*400) });
      await delay(150 + Math.floor(Math.random()*200));
    }
  } catch {}

  console.error('[puppeteer] Navigating to target...');
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: force ? 30000 : 60000 });
  if (!force) {
    // Let dynamic content settle a bit but do not block indefinitely
    await page.waitForFunction(() => document.readyState === 'complete', { timeout: 20000 }).catch(()=>{});
    await page.waitForNetworkIdle({ idleTime: 1200, timeout: 30000 }).catch(() => {});
  }
  for (let i = 0; i < 3; i++) {
    await page.mouse.wheel({ deltaY: 200 + Math.floor(Math.random()*400) });
    await delay(150 + Math.floor(Math.random()*200));
  }
  try { await page.bringToFront(); } catch {}

  // Inform GUI the page is open
  try { console.error('[STATUS] PAGE_OPENED'); } catch {}

  // Wait until logged in before starting countdown
  const loginStart = Date.now();
  const loginTimeoutMs = 120000;
  while (true) {
    const ok = await isLoggedIn(page);
    if (ok) {
      try { console.error('[STATUS] LOGGED_IN'); } catch {}
      break;
    }
    if (Date.now() - loginStart > loginTimeoutMs) {
      break;
    }
    await delay(500);
  }

  // Prepare outputs
  let addresses = [];
  let savedPaths = null;

  if (panelsMode) {
    try {
      // Normalize outDir and ensure it exists
      let finalOutDir = outDir;
      try {
        const stat = fs.existsSync(finalOutDir) ? fs.statSync(finalOutDir) : null;
        if (stat && !stat.isDirectory()) {
          finalOutDir = path.dirname(finalOutDir);
        }
        if (!stat) {
          if (/\.[a-z0-9]{2,4}$/i.test(path.basename(finalOutDir))) {
            finalOutDir = path.dirname(finalOutDir);
          }
        }
      } catch {}
      await fs.promises.mkdir(finalOutDir, { recursive: true }).catch(()=>{});

      const data = await page.evaluate(() => {
        const getOuterHTML = (el) => (el && el.outerHTML) || '';
        const cardNodes = Array.from(document.querySelectorAll('div.bg-panel-100'));
        const cardHTML = cardNodes.length ? cardNodes.map(n => n.outerHTML) : [];
        let panelsHTML = '';
        if (!cardHTML.length) {
          const panelsSelectors = [
            'section.panels',
            '[data-testid*="panel" i]',
            '.ant-tabs-content-holder',
            'main',
          ];
          for (const sel of panelsSelectors) {
            const el = document.querySelector(sel);
            if (el) { panelsHTML = getOuterHTML(el); break; }
          }
          if (!panelsHTML) {
            const el = document.querySelector('#root') || document.body;
            panelsHTML = getOuterHTML(el);
          }
        }
        const findByHeading = (labels) => {
          const rx = new RegExp(labels.map(l => l.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&')).join('|'), 'i');
          const nodes = Array.from(document.querySelectorAll('section, div, article'));
          for (const node of nodes) {
            const t = (node.innerText || '').slice(0, 500).toLowerCase();
            if (rx.test(t)) return getOuterHTML(node);
          }
          return '';
        };
        // Basic text dump from main panels area
        const panelsContainer = document.querySelector('section.panels, main, #root, body');
        const panelsText = (panelsContainer && panelsContainer.innerText) || (document.body?.innerText || '');
        const recentPnLHTML = findByHeading(['Recent PnL', 'PnL']);
        const deployedTokensHTML = findByHeading(['Deployed Tokens', 'Deployed']);
        return { panelsHTML, cardHTML, recentPnLHTML, deployedTokensHTML, panelsText };
      });

      const panelsPath = path.join(finalOutDir, 'panels.json');
      const recentPath = path.join(finalOutDir, 'recentpnl.json');
      const deployedPath = path.join(finalOutDir, 'deployedtokens.json');
      if (data.cardHTML && data.cardHTML.length) {
        await fs.promises.writeFile(panelsPath, JSON.stringify({ cards: data.cardHTML }, null, 2), 'utf-8');
      } else {
        await fs.promises.writeFile(panelsPath, JSON.stringify({ outerHTML: data.panelsHTML }, null, 2), 'utf-8');
      }
  await fs.promises.writeFile(recentPath, JSON.stringify({ outerHTML: data.recentPnLHTML || '' }, null, 2), 'utf-8');
  await fs.promises.writeFile(deployedPath, JSON.stringify({ outerHTML: data.deployedTokensHTML || '' }, null, 2), 'utf-8');
  // Also save a basic panels text dump for quick parsing
  const panelsDataPath = path.join(finalOutDir, 'panels_data.json');
  await fs.promises.writeFile(panelsDataPath, JSON.stringify({ text: data.panelsText || '' }, null, 2), 'utf-8');
      savedPaths = { outdir: finalOutDir, panels: panelsPath, recentpnl: recentPath, deployedtokens: deployedPath };
      console.error(`[puppeteer] Saved panels to ${finalOutDir}`);
      
      // Extract Recent PnL and Deployed Tokens tables into structured rows
      async function clickTabByLabelsInPage(labels) {
        try {
          await page.evaluate((labels) => {
            const rx = new RegExp(labels.map(l => l.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&')).join('|'), 'i');
            const buttons = Array.from(document.querySelectorAll('button, [role="tab"], .chakra-tabs__tab'));
            for (const btn of buttons) {
              const t = (btn.innerText || btn.textContent || '').trim();
              if (!t) continue;
              if (rx.test(t)) { (btn).click(); return; }
            }
          }, labels);
          await delay(500);
        } catch {}
      }

      async function extractTableByLabels(labels) {
        await clickTabByLabelsInPage(labels);
        return await page.evaluate((labels) => {
          const getText = (el) => (el && (el.innerText || el.textContent) || '').trim();
          const escapeRe = (s) => s.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&');
          const rx = new RegExp(labels.map(escapeRe).join('|'), 'i');
          let container = null;
          const candidates = Array.from(document.querySelectorAll('section, div, article'));
          for (const el of candidates) {
            const t = getText(el).toLowerCase();
            if (rx.test(t)) { container = el; break; }
          }
          if (!container) container = document.body;

          // Try semantic table first
          const table = container.querySelector('table');
          if (table) {
            const headers = Array.from(table.querySelectorAll('thead th, thead td')).map(getText);
            const rows = Array.from(table.querySelectorAll('tbody tr')).map(tr => (
              Array.from(tr.querySelectorAll('td,th')).map(getText)
            ));
            return { headers, rows };
          }

          // Fallback: grid rows
          let rowsEls = Array.from(container.querySelectorAll('[role="row"]'));
          if (!rowsEls.length) {
            // heuristic: lists with many children likely a table
            const groups = candidates
              .map(el => ({ el, children: Array.from(el.children).filter(c => c.tagName !== 'SCRIPT' && c.tagName !== 'STYLE') }))
              .filter(x => x.children.length > 5);
            if (groups.length) rowsEls = groups[0].children;
          }
          const rows = Array.from(rowsEls).map(r => (
            Array.from(r.querySelectorAll('div,span,p,td')).map(getText).filter(Boolean).slice(0, 20)
          )).filter(a => a.length >= 3);
          return { headers: [], rows };
        }, labels);
      }

      const recentTbl = await extractTableByLabels(['Recent PnL', 'Recent']);
      const deployedTbl = await extractTableByLabels(['Deployed Tokens', 'Deployed']);

      function shapeRows(headers, rows) {
        const h = headers.map(x => x.toLowerCase());
        const idx = (name) => h.findIndex(x => x.includes(name));
        const iToken = idx('token');
        const iLast = idx('last');
        const iUnrl = idx('unreal');
        const iReal = idx('realized');
        const iTotal = idx('total');
        const iBal = idx('balance');
        const iUsd = h.findIndex(x => x === 'usd' || x.includes('usd'));
        const iPos = idx('position');
        const iHold = idx('holding');
        const iBuy = h.findIndex(x => x.includes('bought'));
        const iSell = h.findIndex(x => x.includes('sold'));
        const iTx = h.findIndex(x => x === 'txs' || x.includes('tx'));
        return rows.map(cells => ({
          token: iToken >= 0 ? cells[iToken] : (cells[0] || ''),
          last_active: iLast >= 0 ? cells[iLast] : '',
          unrealized: iUnrl >= 0 ? cells[iUnrl] : '',
          realized_profit: iReal >= 0 ? cells[iReal] : '',
          total_profit: iTotal >= 0 ? cells[iTotal] : '',
          balance: iBal >= 0 ? cells[iBal] : '',
          usd: iUsd >= 0 ? cells[iUsd] : '',
          position_pct: iPos >= 0 ? cells[iPos] : '',
          holding_duration: iHold >= 0 ? cells[iHold] : '',
          bought_avg: iBuy >= 0 ? cells[iBuy] : '',
          sold_avg: iSell >= 0 ? cells[iSell] : '',
          txs: iTx >= 0 ? cells[iTx] : ''
        }));
      }

      function writeCSVSync(filePath, rows) {
        if (!rows || !rows.length) { fs.writeFileSync(filePath, ''); return; }
        const headers = Object.keys(rows[0]);
        const esc = (v) => {
          const s = (v == null ? '' : String(v));
          if (/[",\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
          return s;
        };
        const lines = [headers.join(',')].concat(rows.map(r => headers.map(k => esc(r[k])).join(',')));
        fs.writeFileSync(filePath, lines.join('\n'));
      }

      const recentRows = shapeRows(recentTbl.headers, recentTbl.rows);
      const deployedRows = shapeRows(deployedTbl.headers, deployedTbl.rows);
      const recentDataPath = path.join(finalOutDir, 'recentpnl_data.json');
      const recentCsvPath = path.join(finalOutDir, 'recentpnl.csv');
      const deployedDataPath = path.join(finalOutDir, 'deployedtokens_data.json');
      const deployedCsvPath = path.join(finalOutDir, 'deployedtokens.csv');
      await fs.promises.writeFile(recentDataPath, JSON.stringify({ headers: recentTbl.headers, rows: recentRows }, null, 2), 'utf-8');
      await fs.promises.writeFile(deployedDataPath, JSON.stringify({ headers: deployedTbl.headers, rows: deployedRows }, null, 2), 'utf-8');
      writeCSVSync(recentCsvPath, recentRows);
      writeCSVSync(deployedCsvPath, deployedRows);
    } catch (e) {
      console.error('Failed to save panels JSON:', e?.message || String(e));
    }
  } else {
    // Collect addresses in non-panels mode
    try {
      await waitForAddresses(page, expectedCount, 45000).catch(()=>{});
      addresses = await extractAddresses(page, expectedCount);
    } catch (e) {
      addresses = [];
    }
  }

  // Save updated session for next runs
  await saveSession(page, sessionFile);

  if (!panelsMode) {
    console.error(`[puppeteer] Done. Found ${addresses.length} addresses.`);
  } else {
    console.error('[puppeteer] Done. Panels saved.');
  }
  try { await page?.close({ runBeforeUnload: true }); } catch {}
  // Do not close external Chrome when attached via CDP
  if (!attached) {
    try { await browser.close(); } catch {}
  }
  else {
    try { await browser.disconnect(); } catch {}
  }

  // Output JSON to stdout
  if (panelsMode) {
    process.stdout.write(JSON.stringify({ ok: true, ...(savedPaths || { outdir: outDir }) }));
  } else {
    process.stdout.write(JSON.stringify({ addresses }));
  }
}

main().catch(err => {
  try { console.error(err?.stack || String(err)); } catch {}
  process.stdout.write(JSON.stringify({ addresses: [], error: String(err) }));
  process.exit(0);
});
