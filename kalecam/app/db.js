/* kalecam shared IndexedDB helpers (used by the page and the service worker). */
(function (g) {
  'use strict';
  const DB_NAME = 'kalecam', DB_VER = 1;
  let dbp = null;
  function open() {
    if (dbp) return dbp;
    dbp = new Promise((res, rej) => {
      const r = indexedDB.open(DB_NAME, DB_VER);
      r.onupgradeneeded = () => {
        const db = r.result;
        if (!db.objectStoreNames.contains('queue')) db.createObjectStore('queue', { keyPath: 'id' }).createIndex('created', 'created');
        if (!db.objectStoreNames.contains('kv')) db.createObjectStore('kv');
      };
      r.onsuccess = () => res(r.result);
      r.onerror = () => { dbp = null; rej(r.error); };
    });
    return dbp;
  }
  function tx(store, mode, fn) {
    return open().then(db => new Promise((res, rej) => {
      const t = db.transaction(store, mode), s = t.objectStore(store);
      let out;
      Promise.resolve(fn(s)).then(v => { out = v; });
      t.oncomplete = () => res(out && out.result !== undefined && out instanceof IDBRequest ? out.result : out);
      t.onerror = () => rej(t.error);
      t.onabort = () => rej(t.error);
    }));
  }
  const req = r => new Promise((res, rej) => { r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
  const KDB = {
    qAdd: item => tx('queue', 'readwrite', s => { s.put(item); }),
    qDel: id => tx('queue', 'readwrite', s => { s.delete(id); }),
    qPut: item => tx('queue', 'readwrite', s => { s.put(item); }),
    qCount: () => open().then(db => req(db.transaction('queue').objectStore('queue').count())),
    qOldest: (n = 1) => open().then(db => new Promise((res, rej) => {
      const out = [], c = db.transaction('queue').objectStore('queue').index('created').openCursor();
      c.onsuccess = () => { const cur = c.result; if (cur && out.length < n) { out.push(cur.value); cur.continue(); } else res(out); };
      c.onerror = () => rej(c.error);
    })),
    kvGet: k => open().then(db => req(db.transaction('kv').objectStore('kv').get(k))),
    kvSet: (k, v) => tx('kv', 'readwrite', s => { s.put(v, k); }),
    /* Upload one queued photo. Returns {ok, status, json}. Throws on network error/timeout. */
    async upload(item, apiBase, token, version, timeoutMs = 120000) {
      const fd = new FormData();
      fd.append('photo', item.blob, 'photo.jpg');
      for (const [k, v] of Object.entries(item.meta || {})) if (v !== null && v !== undefined) fd.append(k, String(v));
      const queued = (item.attempts || 0) > 0 || (Date.now() - item.created) > 60000;
      fd.append('queued', queued ? '1' : '0');
      const ac = new AbortController(), t = setTimeout(() => ac.abort(), timeoutMs);
      try {
        const r = await fetch(apiBase + '/upload', { method: 'POST', body: fd, signal: ac.signal, cache: 'no-store',
          headers: { 'X-Upload-Key': token, 'X-App-Version': version } });
        let j = null; try { j = await r.json(); } catch (e) { /* non-JSON (e.g. Cloudflare 530 page) */ }
        return { ok: r.ok, status: r.status, json: j };
      } finally { clearTimeout(t); }
    },
  };
  g.KDB = KDB;
})(typeof self !== 'undefined' ? self : window);
