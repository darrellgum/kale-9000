/* kalecam service worker: keeps the app shell available even when this page's origin
   (an old tunnel URL) is dead, and uploads queued photos via Background Sync where supported. */
importScripts('/app/db.js');
const VERSION = '1.0.1';
const CACHE = 'kalecam-shell-' + VERSION;
const SHELL = ['/app', '/app/app.js', '/app/db.js', '/app/style.css', '/app/manifest.webmanifest',
  '/app/icon-192.png', '/app/icon-512.png'];
const ALIASES = { '/app/': '/app', '/app/index.html': '/app' };

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL.map(u => new Request(u, { cache: 'reload' })))).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith('kalecam-shell-') && k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

function timeout(ms) { return new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), ms)); }

async function networkFirst(req, key) {
  const cache = await caches.open(CACHE);
  try {
    const r = await Promise.race([fetch(req, { cache: 'no-store' }), timeout(5000)]);
    if (r && r.ok) { cache.put(key, r.clone()); return r; }
    const hit = await cache.match(key);   // e.g. 530 from Cloudflare once the old tunnel is gone
    return hit || r;
  } catch (err) {
    const hit = await cache.match(key);
    if (hit) return hit;
    throw err;
  }
}

self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== self.location.origin) return;  // never touch API/cross-origin
  const key = ALIASES[u.pathname] || u.pathname;
  if (!SHELL.includes(key)) return;
  e.respondWith(networkFirst(e.request, key));
});

async function drainFromSW() {
  const apiBase = await KDB.kvGet('apiBase'), token = await KDB.kvGet('token');
  if (!apiBase || !token) return;
  for (;;) {
    const [it] = await KDB.qOldest(1);
    if (!it) return;
    const r = await KDB.upload(it, apiBase, token, VERSION + '-sw');
    if (r.ok || [400, 413, 415, 422].includes(r.status)) await KDB.qDel(it.id);
    else throw new Error('upload failed ' + r.status);  // makes the browser retry the sync later
  }
}
self.addEventListener('sync', e => { if (e.tag === 'kalecam-upload') e.waitUntil(drainFromSW()); });
self.addEventListener('message', e => { if (e.data === 'drain') e.waitUntil(drainFromSW().catch(() => {})); });
