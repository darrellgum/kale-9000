/* kalecam capture page. No framework, no build step. */
(function () {
  'use strict';
  const VERSION = '1.0.1';
  const LS = {
    pairing: 'kalecam.pairing', blob: 'kalecam.blob', api: 'kalecam.apiBase', seq: 'kalecam.lastSeq',
    slot: 'kalecam.lastSlot', cmds: 'kalecam.doneCmds', dev: 'kalecam.deviceId', prep: 'kalecam.prepDone',
    cfg: 'kalecam.cfg', orient: 'kalecam.orient',
  };
  const DEFAULT_CFG = {
    schedule: { enabled: true, interval_min: 30, start: '06:00', end: '22:00' },
    capture: { facing: 'environment', ideal_width: 4096, ideal_height: 3072, use_image_capture: true,
      jpeg_max_bytes: 3500000, jpeg_quality: 0.92, keep_camera_open: true, warmup_ms: 1500 },
    heartbeat_s: 60, poll_hold_s: 25, migrate: 'sticky', dim_preview: false, orientation: 'any', timezone: null, version: null,
  };
  const $ = id => document.getElementById(id);
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const wakers = new Set();
  function napping(ms) { return new Promise(r => { const w = () => { clearTimeout(t); wakers.delete(w); r(); }; const t = setTimeout(w, ms); wakers.add(w); }); }
  function wakeLoops() { [...wakers].forEach(w => w()); }
  const enc = new TextEncoder(), dec = new TextDecoder();

  const S = {
    pairing: null, blobStr: null, token: null, rvKey: null, cfg: null, apiBase: null,
    connected: false, failures: 0, lastOkAt: 0, stream: null, track: null, imageCapture: null,
    wakeLock: null, wakeState: '-', lastCapture: null, lastUpload: null, queue: 0, errors: [],
    captureChain: Promise.resolve(), draining: false, uploadBackoff: 0, drainTimer: null,
    rvNextAt: 0, rvDelay: 15000, rvLast: null, battery: null, started: Date.now(), lastSeq: 0,
    switching: false, camLabel: null, resolution: null, events: [],
  };

  // ------------------------------------------------------------ utils
  function b64uDec(s) { s = s.replace(/-/g, '+').replace(/_/g, '/'); while (s.length % 4) s += '='; const b = atob(s); const u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return u; }
  function b64uEnc(u8) { let s = ''; u8.forEach(c => { s += String.fromCharCode(c); }); return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); }
  function pad(n) { return String(Math.floor(Math.abs(n))).padStart(2, '0'); }
  function isoLocal(d) {
    const off = -d.getTimezoneOffset(), sign = off >= 0 ? '+' : '-';
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}${sign}${pad(off / 60)}:${pad(off % 60)}`;
  }
  function uuid() { return (crypto.randomUUID ? crypto.randomUUID() : b64uEnc(crypto.getRandomValues(new Uint8Array(16)))); }
  function note(msg) { const e = `${new Date().toTimeString().slice(0, 8)} ${msg}`; S.events.push(e); if (S.events.length > 50) S.events.shift(); console.log('[kalecam]', msg); }
  function err(msg) { S.errors.push(`${isoLocal(new Date())} ${msg}`); if (S.errors.length > 5) S.errors.shift(); note('ERROR ' + msg); }
  function showMsg(t) { const m = $('msg'); if (!t) { m.hidden = true; return; } m.textContent = t; m.hidden = false; }
  function withTimeout(p, ms, what) { return Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error((what || 'operation') + ' timed out')), ms))]); }

  // ------------------------------------------------------------ pairing + keys
  function parseFragment() {
    const h = location.hash.slice(1);
    if (!h) return null;
    const parts = h.split('&'), extra = {};
    for (const p of parts.slice(1)) { const i = p.indexOf('='); if (i > 0) extra[p.slice(0, i)] = decodeURIComponent(p.slice(i + 1)); }
    try {
      const obj = JSON.parse(dec.decode(b64uDec(parts[0])));
      if (obj.v !== 1 || !obj.k || !Array.isArray(obj.r) || !obj.p || !obj.c) throw new Error('bad pairing data');
      return { blobStr: parts[0], pairing: obj, extra };
    } catch (e) { err('could not read pairing link: ' + e.message); return null; }
  }
  async function deriveKeys(secretB64) {
    const ikm = await crypto.subtle.importKey('raw', b64uDec(secretB64), 'HKDF', false, ['deriveBits', 'deriveKey']);
    const salt = enc.encode('kalecam-v1');
    const authBits = await crypto.subtle.deriveBits({ name: 'HKDF', hash: 'SHA-256', salt, info: enc.encode('auth') }, ikm, 256);
    const rvKey = await crypto.subtle.deriveKey({ name: 'HKDF', hash: 'SHA-256', salt, info: enc.encode('rendezvous') }, ikm,
      { name: 'AES-GCM', length: 256 }, false, ['decrypt']);
    return { token: b64uEnc(new Uint8Array(authBits)), rvKey };
  }
  async function decryptRv(text) {
    text = (text || '').trim();
    if (!text.startsWith('kc1.')) return null;
    try {
      const raw = b64uDec(text.slice(4));
      const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: raw.slice(0, 12), additionalData: enc.encode('kalecam-rendezvous-v1') }, S.rvKey, raw.slice(12));
      const o = JSON.parse(dec.decode(pt));
      return (o && typeof o.url === 'string' && Number.isFinite(o.seq)) ? o : null;
    } catch (e) { return null; }   // wrong key / tampered / garbage: GCM tag check fails
  }

  // ------------------------------------------------------------ rendezvous
  async function readChannel([type, base, topic]) {
    const ac = new AbortController(), t = setTimeout(() => ac.abort(), 12000);
    try {
      let texts = [];
      if (type === 'n') {
        const r = await fetch(`${base}/${topic}/json?poll=1&since=all`, { cache: 'no-store', signal: ac.signal, credentials: 'omit' });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        for (const line of (await r.text()).split('\n')) { try { const m = JSON.parse(line); if (m.event === 'message') texts.push(m.message); } catch (e) { /* skip */ } }
      } else if (type === 't') {
        const r = await fetch(`${base}/${topic}`, { cache: 'no-store', signal: ac.signal, credentials: 'omit' });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        texts = [await r.text()];
      } else throw new Error('unknown channel type ' + type);
      const valid = (await Promise.all(texts.map(decryptRv))).filter(Boolean);
      const best = valid.reduce((a, b) => (!a || b.seq > a.seq ? b : a), null);
      return { label: new URL(base).host, ok: !!best, messages: texts.length, valid: valid.length, best };
    } catch (e) { return { label: new URL(base).host, ok: false, error: String(e.message || e) }; }
    finally { clearTimeout(t); }
  }
  async function checkHealth(url) {
    const ac = new AbortController(), t = setTimeout(() => ac.abort(), 10000);
    try { const r = await fetch(url + '/healthz', { cache: 'no-store', signal: ac.signal, credentials: 'omit' }); const j = await r.json(); return r.ok && j.app === 'kalecam'; }
    catch (e) { return false; } finally { clearTimeout(t); }
  }
  async function resolveRendezvous(force) {
    if (!force && Date.now() < S.rvNextAt) return false;
    S.rvNextAt = Date.now() + S.rvDelay;
    S.rvDelay = Math.min(S.rvDelay * 2, 30000);
    const res = await Promise.all(S.pairing.r.map(readChannel));
    const best = res.map(r => r.best).filter(Boolean).reduce((a, b) => (!a || b.seq > a.seq ? b : a), null);
    S.rvLast = { at: isoLocal(new Date()), channels: res.map(r => ({ host: r.label, ok: r.ok, seq: r.best ? r.best.seq : null, error: r.error })) };
    note(`rendezvous: ${res.map(r => `${r.label}=${r.ok ? r.best.seq : 'x'}`).join(' ')}`);
    if (!best) return false;
    if (best.seq <= S.lastSeq) return false;                    // replay / nothing newer
    if (!/^https:\/\/[^/]+$/.test(best.url.replace(/\/$/, ''))) { err('rendezvous URL rejected (not https origin)'); return false; }
    const url = best.url.replace(/\/$/, '');
    if (url === S.apiBase) { S.lastSeq = best.seq; localStorage.setItem(LS.seq, String(best.seq)); return false; }
    if (!(await checkHealth(url))) { note('new address not reachable yet: ' + url); return false; }
    S.lastSeq = best.seq; localStorage.setItem(LS.seq, String(best.seq));
    await switchApi(url);
    return true;
  }
  async function switchApi(url) {
    note('switching server address to ' + url);
    S.apiBase = url; localStorage.setItem(LS.api, url); await KDB.kvSet('apiBase', url);
    S.failures = 0; S.uploadBackoff = 0; S.rvDelay = 15000;
    wakeLoops();   // end any backoff sleep so polling/heartbeats resume right away
    if ((S.cfg.migrate === 'navigate') && new URL(url).origin !== location.origin) return navigateTo(url);
    drain();
  }
  async function navigateTo(url) {
    if (S.switching) return; S.switching = true;
    showMsg('Moving to the new server address...');
    // Upload queued photos first: IndexedDB is per-origin, so they would be stranded here.
    const end = Date.now() + 120000;
    while (Date.now() < end && (await KDB.qCount()) > 0) { await drain(true); if ((await KDB.qCount()) > 0) await sleep(3000); }
    const extra = `&seq=${S.lastSeq}&slot=${encodeURIComponent(localStorage.getItem(LS.slot) || '')}&prep=${localStorage.getItem(LS.prep) ? 1 : 0}&dev=${encodeURIComponent(S.camLabel || '')}`;
    location.replace(`${url}/app#${S.blobStr}${extra}`);
  }

  // ------------------------------------------------------------ server API
  async function api(path, opts = {}) {
    const ac = new AbortController(), t = setTimeout(() => ac.abort(), opts.timeout || 20000);
    try {
      return await fetch(S.apiBase + path, { method: opts.method || 'GET', body: opts.body, cache: 'no-store', credentials: 'omit', signal: ac.signal,
        headers: Object.assign({ 'X-Upload-Key': S.token, 'X-App-Version': VERSION }, opts.headers || {}) });
    } finally { clearTimeout(t); }
  }
  function noteSuccess() {
    const was = S.connected;
    S.connected = true; S.failures = 0; S.lastOkAt = Date.now(); S.rvDelay = 15000; S.rvNextAt = 0;
    if (!was) { note('connected to ' + S.apiBase); showMsg(''); drain(); wakeLoops(); }
  }
  function noteFailure(e) {
    S.connected = false; S.failures++;
    if (S.failures === 1 || S.failures % 10 === 0) err('server unreachable: ' + (e && e.message || e));
    if (S.failures >= 3 || Date.now() - S.lastOkAt > 45000) resolveRendezvous(false).catch(x => err('rendezvous: ' + x));
    render();
  }
  async function loadConfig() {
    const r = await api('/config');
    if (r.status === 401) { showMsg('The server rejected this phone\'s pairing key. Re-scan the QR code from `kalecam pair`.'); throw new Error('401'); }
    if (!r.ok) throw new Error('config HTTP ' + r.status);
    const c = await r.json();
    S.cfg = Object.assign({}, DEFAULT_CFG, c, { capture: Object.assign({}, DEFAULT_CFG.capture, c.capture || {}) });
    localStorage.setItem(LS.cfg, JSON.stringify(S.cfg));
    document.body.classList.toggle('dimmed', !!S.cfg.dim_preview);
    note('config ' + S.cfg.version);
  }
  async function pollLoop() {
    for (;;) {
      if (S.switching) { await sleep(1000); continue; }
      try {
        const hold = S.cfg.poll_hold_s || 25;
        const r = await api(`/poll?camera=${encodeURIComponent(S.pairing.c)}&hold=${hold}`, { timeout: (hold + 20) * 1000 });
        if (r.status === 401) { showMsg('Pairing key rejected by the server. Re-scan the QR code.'); await sleep(60000); continue; }
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const j = await r.json();
        noteSuccess();
        if (j.config_version && j.config_version !== S.cfg.version) await loadConfig().catch(e => err('config: ' + e.message));
        if (j.cmd) handleCommand(j);
      } catch (e) {
        noteFailure(e);
        await napping(Math.min(60000, 1000 * Math.pow(2, Math.min(S.failures, 6))) * (0.75 + Math.random() * 0.5));
      }
      render();
    }
  }
  function handleCommand(j) {
    const done = JSON.parse(localStorage.getItem(LS.cmds) || '[]');
    if (done.includes(j.id)) { note('duplicate command ignored ' + j.id); return; }
    done.push(j.id); localStorage.setItem(LS.cmds, JSON.stringify(done.slice(-50)));
    note('command ' + j.cmd + ' ' + j.id);
    if (j.cmd === 'capture') capture('command', j.id, j.settings || {}, j.plant);
    else if (j.cmd === 'reload') setTimeout(() => location.reload(), 500);
    else if (j.cmd === 'refresh_config') loadConfig().catch(() => {});
  }

  // ------------------------------------------------------------ heartbeat
  async function heartbeat() {
    let battery = null;
    try {
      if (!S.battery && navigator.getBattery) S.battery = await navigator.getBattery();
      if (S.battery) battery = { level: S.battery.level, charging: S.battery.charging,
        charging_time: Number.isFinite(S.battery.chargingTime) ? S.battery.chargingTime : null,
        discharging_time: Number.isFinite(S.battery.dischargingTime) ? S.battery.dischargingTime : null };
    } catch (e) { /* unsupported */ }
    let storage = null;
    try { if (navigator.storage && navigator.storage.estimate) { const e = await navigator.storage.estimate(); storage = { usage: e.usage, quota: e.quota }; } } catch (e) { /* */ }
    S.queue = await KDB.qCount();
    const hb = {
      camera: S.pairing.c, plant_id: S.pairing.p, app_version: VERSION, battery,
      temperature_c: null,   // not exposed to web pages by any browser
      queue: S.queue, last_capture: S.lastCapture, last_upload: S.lastUpload,
      visible: document.visibilityState === 'visible', wake_lock: S.wakeState, camera_label: S.camLabel, resolution: S.resolution,
      api_base: S.apiBase, page_origin: location.origin, migrate: S.cfg.migrate, uptime_s: Math.round((Date.now() - S.started) / 1000),
      failures: S.failures, errors: S.errors.slice(-5), rendezvous: S.rvLast, storage,
      standalone: matchMedia('(display-mode: standalone)').matches || !!navigator.standalone,
      fullscreen: !!document.fullscreenElement, sw: !!(navigator.serviceWorker && navigator.serviceWorker.controller),
      connection: navigator.connection ? navigator.connection.effectiveType : null, ua: navigator.userAgent, next_capture: nextShotText(),
      phone_time: isoLocal(new Date()),
    };
    const r = await api('/heartbeat', { method: 'POST', body: JSON.stringify(hb), headers: { 'Content-Type': 'application/json' } });
    if (!r.ok) throw new Error('heartbeat HTTP ' + r.status);
    noteSuccess();
  }
  async function heartbeatLoop() {
    for (;;) {
      if (!S.switching) { try { await heartbeat(); } catch (e) { noteFailure(e); } }
      await napping(S.connected ? (S.cfg.heartbeat_s || 60) * 1000 : Math.min(30000, (S.cfg.heartbeat_s || 60) * 1000));
    }
  }

  // ------------------------------------------------------------ camera
  async function startCamera(fromGesture) {
    const c = S.cfg.capture;
    const video = { width: { ideal: c.ideal_width }, height: { ideal: c.ideal_height } };
    const dev = localStorage.getItem(LS.dev);
    if (dev) video.deviceId = { exact: dev }; else video.facingMode = { ideal: c.facing || 'environment' };
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ video, audio: false }); }
    catch (e) {
      if (dev && (e.name === 'OverconstrainedError' || e.name === 'NotFoundError')) {   // deviceIds differ per origin
        localStorage.removeItem(LS.dev); return startCamera(fromGesture);
      }
      if (e.name === 'NotAllowedError' || e.name === 'SecurityError') {
        $('camperm').hidden = false;
        $('campermMsg').textContent = fromGesture
          ? 'The camera is blocked for this page. Open the browser\'s site settings (lock icon next to the address) and allow Camera, then tap the button again.'
          : 'This page needs the camera. Tap the button and choose Allow. (A new server address counts as a new site, so the browser may ask again.)';
      }
      throw e;
    }
    stopCamera();
    S.stream = stream; S.track = stream.getVideoTracks()[0];
    const v = $('preview'); v.srcObject = stream; try { await v.play(); } catch (e) { /* autoplay */ }
    S.track.addEventListener('ended', () => { note('camera track ended'); S.stream = null; });
    try { await S.track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] }); } catch (e) { /* unsupported */ }
    S.imageCapture = ('ImageCapture' in window) ? new ImageCapture(S.track) : null;
    const st = S.track.getSettings();
    S.camLabel = S.track.label || 'camera'; S.resolution = `${st.width}x${st.height}`;
    note(`camera ${S.camLabel} ${S.resolution}`);
    $('main').hidden = false; $('camperm').hidden = true;
    fillCameraList();
    return stream;
  }
  function stopCamera() { if (S.stream) S.stream.getTracks().forEach(t => t.stop()); S.stream = null; S.track = null; S.imageCapture = null; }
  function cameraLive() { return S.track && S.track.readyState === 'live'; }
  async function fillCameraList() {
    try {
      const devs = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'videoinput');
      const sel = $('camSelect'); sel.innerHTML = '';
      const auto = new Option('Automatic (rear camera)', ''); sel.add(auto);
      devs.forEach((d, i) => sel.add(new Option(d.label || `Camera ${i + 1}`, d.deviceId)));
      sel.value = localStorage.getItem(LS.dev) || '';
    } catch (e) { /* */ }
  }

  function capture(trigger, cmdId, settings, plant) {
    S.captureChain = S.captureChain.then(() => doCapture(trigger, cmdId, settings || {}, plant)).catch(e => err('capture: ' + (e.message || e)));
    return S.captureChain;
  }
  async function encodeJpeg(src, w, h, maxBytes, q0) {
    const cv = $('canvas'); let scale = 1, q = q0 || 0.92, blob = null;
    const cap = 4096 / Math.max(w, h); if (cap < 1) scale = cap;   // keep canvas size sane
    for (let i = 0; i < 10; i++) {
      cv.width = Math.round(w * scale); cv.height = Math.round(h * scale);
      const ctx = cv.getContext('2d'); ctx.drawImage(src, 0, 0, cv.width, cv.height);
      blob = await new Promise(r => cv.toBlob(r, 'image/jpeg', q));
      if (blob && blob.size <= maxBytes) break;
      if (q > 0.72) q -= 0.08; else scale *= 0.85;
    }
    return { blob, w: cv.width, h: cv.height, q };
  }
  async function doCapture(trigger, cmdId, settings, plant) {
    const c = Object.assign({}, S.cfg.capture, settings);
    const openedHere = !cameraLive();
    if (openedHere) { await startCamera(false); await sleep(c.warmup_ms || 1500); }
    const when = new Date();
    let src = null, w = 0, h = 0;
    if (c.use_image_capture && S.imageCapture && S.imageCapture.takePhoto) {
      try {
        const photo = await withTimeout(S.imageCapture.takePhoto(), 15000, 'takePhoto');
        src = await createImageBitmap(photo); w = src.width; h = src.height;
      } catch (e) { note('takePhoto unavailable (' + e.message + '); using video frame'); src = null; }
    }
    if (!src) {
      const v = $('preview');
      if (!v.videoWidth) await sleep(1000);
      src = v; w = v.videoWidth; h = v.videoHeight;
      if (!w) throw new Error('no video frame available');
    }
    const out = await encodeJpeg(src, w, h, c.jpeg_max_bytes || 3500000, c.jpeg_quality);
    if (src.close) src.close();
    if (!c.keep_camera_open && openedHere) stopCamera();
    const item = { id: uuid(), blob: out.blob, created: Date.now(), attempts: 0,
      meta: { plant_id: plant || S.pairing.p, camera: S.pairing.c, captured_at: isoLocal(when), trigger, cmd_id: cmdId || '', photo_id: '', app_version: VERSION } };
    item.meta.photo_id = item.id;
    await KDB.qAdd(item);
    S.lastCapture = isoLocal(when);
    note(`captured ${out.w}x${out.h} ${(out.blob.size / 1e6).toFixed(2)} MB (${trigger})`);
    const th = $('thumb'); if (th.src) URL.revokeObjectURL(th.src); th.src = URL.createObjectURL(out.blob); th.hidden = false;
    render(); drain();
  }

  // ------------------------------------------------------------ upload queue
  function scheduleDrain(ms) { clearTimeout(S.drainTimer); S.drainTimer = setTimeout(drain, ms); }
  async function drain(force) {
    if (S.draining || (S.switching && !force)) return;
    S.draining = true;
    try {
      for (;;) {
        const [it] = await KDB.qOldest(1);
        if (!it) break;
        let r;
        try { r = await KDB.upload(it, S.apiBase, S.token, VERSION); }
        catch (e) { r = { ok: false, status: 0, error: e.message }; }
        if (r.ok) {
          await KDB.qDel(it.id); S.lastUpload = isoLocal(new Date()); S.uploadBackoff = 0;
          note(`uploaded ${r.json && r.json.file}${r.json && r.json.duplicate ? ' (dup)' : ''}`);
          noteSuccess();
        } else if ([400, 413, 415, 422].includes(r.status)) {
          await KDB.qDel(it.id); err(`photo rejected by server (${r.status} ${r.json && r.json.error}); dropped`);
        } else {
          it.attempts = (it.attempts || 0) + 1; await KDB.qPut(it);
          S.uploadBackoff = Math.min(300000, Math.max(5000, S.uploadBackoff * 2));
          if (r.status === 401) showMsg('Upload rejected: pairing key not accepted. Re-scan the QR code.');
          noteFailure(new Error(r.error || ('upload HTTP ' + r.status)));
          scheduleDrain(S.uploadBackoff);
          try { const reg = await navigator.serviceWorker.ready; if (reg.sync) await reg.sync.register('kalecam-upload'); } catch (e) { /* no bg sync */ }
          break;
        }
      }
    } finally { S.draining = false; S.queue = await KDB.qCount(); render(); }
  }

  // ------------------------------------------------------------ schedule
  function wallClock(tz) {
    let parts;
    try { parts = new Intl.DateTimeFormat('en-CA', { timeZone: tz || undefined, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date()); }
    catch (e) { parts = new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date()); }
    const p = {}; parts.forEach(x => { p[x.type] = x.value; });
    return { y: +p.year, m: +p.month, d: +p.day, hh: (+p.hour) % 24, mm: +p.minute };
  }
  function slotInfo() {
    const s = S.cfg && S.cfg.schedule; if (!s || !s.enabled) return null;
    const toMin = t => { const [h, m] = t.split(':').map(Number); return h * 60 + m; };
    const start = toMin(s.start), end = toMin(s.end), len = ((end - start + 1440) % 1440) || 1440, iv = Math.max(1, s.interval_min | 0);
    const w = wallClock(S.cfg.timezone);
    const since = Math.floor(Date.UTC(w.y, w.m - 1, w.d) / 60000) + w.hh * 60 + w.mm - start;
    const day = Math.floor(since / 1440), inDay = since - day * 1440;
    if (inDay >= len) return { active: false, minsToNext: 1440 - inDay };
    return { active: true, key: `${day}:${Math.floor(inDay / iv)}`, minsToNext: iv - (inDay % iv) };
  }
  function nextShotText() {
    const si = slotInfo(); if (!si) return 'schedule off';
    const t = new Date(Date.now() + si.minsToNext * 60000); t.setSeconds(0);
    return t.toTimeString().slice(0, 5);
  }
  async function scheduleLoop() {
    for (;;) {
      try {
        const si = slotInfo();
        if (si && si.active && localStorage.getItem(LS.slot) !== si.key) {
          localStorage.setItem(LS.slot, si.key);
          await capture('schedule');
        }
      } catch (e) { err('schedule: ' + e.message); }
      render();
      await sleep(10000);
    }
  }

  // ------------------------------------------------------------ screen: wake lock, fullscreen, orientation, dim
  async function requestWake() {
    if (!('wakeLock' in navigator)) { S.wakeState = 'unsupported'; return; }
    if (document.visibilityState !== 'visible') return;
    try {
      S.wakeLock = await navigator.wakeLock.request('screen');
      S.wakeState = 'on';
      S.wakeLock.addEventListener('release', () => { S.wakeState = 'released'; render(); setTimeout(requestWake, 1000); });
    } catch (e) { S.wakeState = 'blocked (' + e.name + ')'; }
    render();
  }
  async function goFullscreen() {
    try { if (!document.fullscreenElement && document.documentElement.requestFullscreen) await document.documentElement.requestFullscreen({ navigationUI: 'hide' }); } catch (e) { note('fullscreen: ' + e.message); }
    await lockOrientation();
  }
  async function lockOrientation() {
    const o = localStorage.getItem(LS.orient) || S.cfg.orientation || 'any';
    if (o === 'any' || !screen.orientation || !screen.orientation.lock) return;
    try { await screen.orientation.lock(o === 'current' ? screen.orientation.type : o); note('orientation locked ' + o); }
    catch (e) { note('orientation lock unavailable: ' + e.message); }
  }
  function setDim(on) { $('dim').hidden = !on; }

  // ------------------------------------------------------------ UI
  function render() {
    if (!S.pairing || $('main').hidden) return;
    const dot = $('dot');
    dot.className = 'dot ' + (S.connected ? 'ok' : S.failures > 3 ? 'bad' : '');
    $('connText').textContent = S.switching ? 'Moving to new address...' : S.connected ? 'Connected' : S.failures ? `Reconnecting (${S.failures})` : 'Connecting...';
    $('lastPhoto').textContent = S.lastCapture ? S.lastCapture.slice(11, 19) : 'none yet';
    $('queue').textContent = String(S.queue);
    const b = S.battery;
    $('battery').textContent = b ? `${Math.round(b.level * 100)}%${b.charging ? ' charging' : ''}` : 'n/a';
    $('nextShot').textContent = nextShotText();
    $('wake').textContent = S.wakeState;
    $('camInfo').textContent = S.resolution || '-';
  }
  function wireUI() {
    $('btnShot').onclick = () => capture('manual');
    $('btnFull').onclick = goFullscreen;
    $('btnDim').onclick = () => setDim(true);
    $('dim').onclick = () => setDim(false);
    $('btnSettings').onclick = () => { fillCameraList(); $('orientSelect').value = localStorage.getItem(LS.orient) || S.cfg.orientation || 'any';
      $('aboutText').textContent = `Plant ${S.pairing.p}, camera ${S.pairing.c}. App ${VERSION}. Server ${S.apiBase}. Page ${location.origin}. Mode ${S.cfg.migrate}.`;
      $('settings').hidden = false; };
    $('btnCloseSettings').onclick = () => { $('settings').hidden = true; };
    $('camSelect').onchange = async e => { if (e.target.value) localStorage.setItem(LS.dev, e.target.value); else localStorage.removeItem(LS.dev); await startCamera(true).catch(() => {}); };
    $('orientSelect').onchange = e => { localStorage.setItem(LS.orient, e.target.value); lockOrientation(); };
    $('btnReconnect').onclick = () => resolveRendezvous(true);
    $('btnForget').onclick = () => { if (confirm('Forget the pairing on this phone?')) { Object.values(LS).forEach(k => localStorage.removeItem(k)); location.replace('/app'); } };
    $('btnPrep').onclick = () => { $('prep').hidden = false; };
    $('btnPrepDone').onclick = () => { localStorage.setItem(LS.prep, '1'); $('prep').hidden = true; };
    $('btnAllowCam').onclick = () => startCamera(true).catch(e => err('camera: ' + e.name));
    const ios = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    $(ios ? 'prepIOS' : 'prepAndroid').open = true;
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') { requestWake(); if (!cameraLive() && S.cfg.capture.keep_camera_open) startCamera(false).catch(() => {}); drain(); }
    });
    window.addEventListener('online', () => { wakeLoops(); drain(); resolveRendezvous(true).catch(() => {}); });
  }

  // ------------------------------------------------------------ boot
  async function boot() {
    if ('serviceWorker' in navigator) navigator.serviceWorker.register('/app/sw.js', { scope: '/app' }).catch(e => note('sw: ' + e.message));
    try { if (navigator.storage && navigator.storage.persist) navigator.storage.persist(); } catch (e) { /* */ }
    wireUI();
    const frag = parseFragment();
    if (frag) {
      localStorage.setItem(LS.pairing, JSON.stringify(frag.pairing));
      localStorage.setItem(LS.blob, frag.blobStr);
      localStorage.setItem(LS.api, location.origin);        // the link was just opened here, so this origin is live
      const seq = parseInt(frag.extra.seq || '0', 10);
      if (seq > parseInt(localStorage.getItem(LS.seq) || '0', 10)) localStorage.setItem(LS.seq, String(seq));
      if (frag.extra.slot) localStorage.setItem(LS.slot, frag.extra.slot);
      if (frag.extra.prep === '1') localStorage.setItem(LS.prep, '1');
      history.replaceState(null, '', location.pathname);  // keep the secret out of the address bar/history
    }
    try { S.pairing = JSON.parse(localStorage.getItem(LS.pairing) || 'null'); } catch (e) { S.pairing = null; }
    if (!S.pairing) { $('unpaired').hidden = false; return; }
    S.blobStr = localStorage.getItem(LS.blob);
    Object.assign(S, await deriveKeys(S.pairing.k));
    S.apiBase = localStorage.getItem(LS.api) || location.origin;
    S.lastSeq = parseInt(localStorage.getItem(LS.seq) || '0', 10);
    await KDB.kvSet('apiBase', S.apiBase); await KDB.kvSet('token', S.token);
    try { S.cfg = Object.assign({}, DEFAULT_CFG, JSON.parse(localStorage.getItem(LS.cfg) || '{}')); } catch (e) { S.cfg = Object.assign({}, DEFAULT_CFG); }
    $('main').hidden = false;
    if (!localStorage.getItem(LS.prep)) $('prep').hidden = false;
    // Opened on an old origin (e.g. home-screen icon) while in navigate mode: hop to the current address.
    if (S.cfg.migrate === 'navigate' && new URL(S.apiBase).origin !== location.origin && await checkHealth(S.apiBase)) return navigateTo(S.apiBase);
    try { await loadConfig(); noteSuccess(); }
    catch (e) { noteFailure(e); if (!(await checkHealth(S.apiBase))) await resolveRendezvous(true).catch(() => {}); await loadConfig().catch(() => {}); }
    S.queue = await KDB.qCount();
    requestWake();
    if (S.cfg.orientation && S.cfg.orientation !== 'any') lockOrientation();
    if (S.cfg.dim_preview) document.body.classList.add('dimmed');
    try { if (S.cfg.capture.keep_camera_open) await startCamera(false); } catch (e) { err('camera: ' + e.name + ' ' + e.message); }
    render();
    pollLoop(); heartbeatLoop(); scheduleLoop(); drain();
    setInterval(render, 5000);
  }

  window.kalecam = { S, decryptRv, resolveRendezvous, capture, drain, slotInfo, version: VERSION };
  boot().catch(e => { err('boot: ' + (e.stack || e)); showMsg('Startup error: ' + e.message); });
})();
