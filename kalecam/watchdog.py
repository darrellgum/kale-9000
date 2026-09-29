#!/usr/bin/env python3
"""kalecam watchdog: idempotent, safe to run every few minutes (run it via watchdog.sh,
which holds a lock so two runs never overlap).

Each run:
  1. make sure config, secrets and the cloudflared binary exist (re-download if missing)
  2. check the local server (GET /healthz); restart it if down/unhealthy
  3. check cloudflared: process alive + public URL end-to-end (GET https://<url>/healthz must
     return THIS server's instance id); restart it if not (new URL)
  4. publish the encrypted address to every rendezvous channel when the URL changed, when a
     channel failed last time, or every `republish_s` (default 1 h) to keep caches fresh
  5. the same for the device bridge's own rendezvous channels (bridge_rendezvous.py), if a bridge
     key exists; errors there never affect the phone path
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kalecam_lib as K  # noqa: E402
import rendezvous as RV  # noqa: E402

CLOUDFLARED = K.BIN / "cloudflared"
CF_LOG = K.LOGS / "cloudflared.log"
SERVER_LOG = K.LOGS / "server.log"
WD_LOG = K.LOGS / "watchdog.log"
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
PY = sys.executable


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    K.LOGS.mkdir(parents=True, exist_ok=True)
    if WD_LOG.exists() and WD_LOG.stat().st_size > 2 * 1024 * 1024:
        shutil.move(WD_LOG, WD_LOG.with_suffix(".log.1"))
    with WD_LOG.open("a") as f:
        f.write(line + "\n")


def http_json(url: str, timeout: float = 8.0):
    req = urllib.request.Request(url, headers={"User-Agent": "kalecam-watchdog"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def kill_pid(pid: int, name: str) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(20):
        if not K.pid_alive(pid, name):
            return
        time.sleep(0.25)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def spawn(argv: list[str], logfile: Path) -> int:
    logfile.parent.mkdir(parents=True, exist_ok=True)
    out = open(logfile, "ab")
    p = subprocess.Popen(argv, cwd=K.BASE, stdout=out, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    return p.pid


# ------------------------------------------------------------------ cloudflared binary
# Pinned cloudflared release. The download is refused unless its sha256 matches.
# To update: pick a release from https://github.com/cloudflare/cloudflared/releases, copy the
# sha256 values from its release notes, and change these three lines (or override them in
# config.json: "cloudflared": {"version": "...", "sha256": {"amd64": "...", "arm64": "..."}}).
CLOUDFLARED_VERSION = "2026.9.3"
CLOUDFLARED_SHA256 = {
    "amd64": "77e26d8d900e0b8469f416239d14b5f296525fdf79fee6f511ef55609e3fbac2",
    "arm64": "aaeb2d7d0da3614634c7e03ab13487a1522c2e79165ed2929cfe23d5e95b326d",
}
ARCHES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}


def sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cloudflared_pin(cfg: dict | None = None) -> tuple[str, str | None, str | None]:
    """(version, arch, expected sha256) for this machine; arch/sha are None if unsupported."""
    over = ((cfg or {}).get("cloudflared") or {}) if isinstance((cfg or {}).get("cloudflared"), dict) else {}
    version = over.get("version") or CLOUDFLARED_VERSION
    hashes = over.get("sha256") or (CLOUDFLARED_SHA256 if version == CLOUDFLARED_VERSION else {})
    arch = ARCHES.get(platform.machine().lower())
    return version, arch, (hashes.get(arch) if arch else None)


def ensure_cloudflared(cfg: dict | None = None) -> bool:
    def works(path: Path) -> bool:
        try:
            r = subprocess.run([str(path), "--version"], capture_output=True, timeout=20)
            return r.returncode == 0 and b"cloudflared" in r.stdout + r.stderr
        except Exception:
            return False

    if CLOUDFLARED.exists() and os.access(CLOUDFLARED, os.X_OK) and works(CLOUDFLARED):
        return True
    version, arch, want = cloudflared_pin(cfg)
    if not arch or not want:
        log(f"no pinned cloudflared checksum for this machine ({platform.machine()}, version {version}); "
            f"install cloudflared yourself as {CLOUDFLARED} (supported: linux amd64/arm64)")
        return False
    url = f"https://github.com/cloudflare/cloudflared/releases/download/{version}/cloudflared-linux-{arch}"
    log(f"cloudflared binary missing or broken; downloading pinned {version} ({arch}) from {url}")
    tmp = K.BIN / ".cloudflared.download"
    try:
        K.BIN.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "kalecam-watchdog"})
        with urllib.request.urlopen(req, timeout=180) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        got = sha256_file(tmp)
        if got != want:
            log(f"cloudflared download REJECTED: sha256 {got} does not match the pinned {want}")
            tmp.unlink(missing_ok=True)
            return False
        os.chmod(tmp, 0o755)
        if not works(tmp):
            log("downloaded cloudflared does not run; keeping old state")
            tmp.unlink(missing_ok=True)
            return False
        os.replace(tmp, CLOUDFLARED)
        ver = subprocess.run([str(CLOUDFLARED), "--version"], capture_output=True, text=True).stdout.strip()
        log(f"cloudflared installed (sha256 verified): {ver}")
        return True
    except Exception as e:  # noqa: BLE001
        log(f"cloudflared download failed: {e}")
        tmp.unlink(missing_ok=True)
        return False


# ------------------------------------------------------------------ server
def server_health(port: int):
    try:
        j = http_json(f"http://127.0.0.1:{port}/healthz", timeout=5)
        return j if j.get("app") == "kalecam" else None
    except Exception:
        return None


def ensure_server(cfg: dict, st: dict) -> dict | None:
    port = int(cfg["port"])
    h = server_health(port) or (time.sleep(1.5) or server_health(port))
    if h:
        return h
    pid = st.get("server_pid")
    if pid and K.pid_alive(pid, "server.py"):
        log(f"server pid {pid} alive but unhealthy; restarting")
        kill_pid(pid, "server.py")
    else:
        log("server not running; starting")
    st["server_pid"] = spawn([PY, str(K.BASE / "server.py")], SERVER_LOG)
    st["server_started_at"] = K.iso(K.now_local())
    for _ in range(40):
        time.sleep(0.25)
        h = server_health(port)
        if h:
            log(f"server up pid={st['server_pid']} instance={h['instance']}")
            return h
    log(f"server failed to start (see {SERVER_LOG}); is port {port} taken by another program?")
    return None


class Server:
    """The local server as seen by this pass. The tunnel code asks it `up()` before it blames
    (or waits on) the tunnel: a dead server makes the public check fail too, and restarting the
    tunnel then only burns the URL while the real problem stays unfixed."""

    def __init__(self, cfg: dict, st: dict):
        self.cfg, self.st = cfg, st
        self.port = int(cfg["port"])
        self.instance: str | None = None
        self.restarts = 0

    def ensure(self) -> bool:
        h = ensure_server(self.cfg, self.st)
        if h and self.instance and h["instance"] != self.instance:
            self.restarts += 1
        self.instance = h["instance"] if h else None
        return bool(h)

    def up(self) -> bool:
        h = server_health(self.port)
        if h:
            self.instance = h["instance"]
        return bool(h)

    def heal(self, why: str) -> bool:
        """Called when a tunnel check failed: check the server first, restart it if it is down.
        Returns True if the server is (now) healthy."""
        if self.up():
            return True
        log(f"{why}, and the local server is DOWN; restarting the server first (tunnel untouched)")
        return self.ensure()


# ------------------------------------------------------------------ tunnel
def doh_a(host: str) -> list[str]:
    """Resolve A records over DNS-over-HTTPS (avoids local resolvers that negatively cache
    a brand-new trycloudflare hostname if it was looked up a moment too early)."""
    for ep in (f"https://dns.google/resolve?name={host}&type=A",
               f"https://cloudflare-dns.com/dns-query?name={host}&type=A"):
        try:
            req = urllib.request.Request(ep, headers={"Accept": "application/dns-json", "User-Agent": "kalecam-watchdog"})
            with urllib.request.urlopen(req, timeout=6) as r:
                j = json.loads(r.read())
            ips = [a["data"] for a in j.get("Answer", []) if a.get("type") == 1]
            if ips:
                return ips
        except Exception:
            continue
    return []


def healthz_via_ip(url: str, ip: str, timeout: float = 10.0) -> dict:
    import http.client
    import socket
    import ssl
    host = urllib.parse.urlparse(url).hostname
    ctx = ssl.create_default_context()
    sock = socket.create_connection((ip, 443), timeout=timeout)
    tls = ctx.wrap_socket(sock, server_hostname=host)
    conn = http.client.HTTPSConnection(host, 443, timeout=timeout, context=ctx)
    conn.sock = tls
    conn.request("GET", "/healthz", headers={"User-Agent": "kalecam-watchdog", "Host": host})
    r = conn.getresponse()
    body = r.read()
    conn.close()
    if r.status != 200:
        raise RuntimeError(f"HTTP {r.status}")
    return json.loads(body)


def e2e_ok(url: str, instance: str | None, tries: int = 3, gap: float = 4.0, fresh: bool = False,
           srv: "Server | None" = None) -> bool:
    """GET <url>/healthz through the public tunnel and compare the server instance id.
    fresh=True: the hostname is brand new, so don't touch the system resolver until DoH
    confirms the record exists (prevents negative caching on this machine)."""
    host = urllib.parse.urlparse(url).hostname
    for i in range(tries):
        if srv is not None:  # never wait on the tunnel while the local server is down
            if not srv.up():
                return False
            instance = srv.instance
        if not instance:
            return False
        ips = doh_a(host) if fresh else []
        if not fresh or ips:
            try:
                if http_json(url.rstrip("/") + "/healthz", timeout=10).get("instance") == instance:
                    return True
            except Exception:
                pass
            for ip in (ips or doh_a(host))[:2]:
                try:
                    if healthz_via_ip(url, ip).get("instance") == instance:
                        return True
                except Exception:
                    pass
        if i < tries - 1:
            time.sleep(gap)
    return False


def start_tunnel(cfg: dict, st: dict, srv: Server) -> str | None:
    old = st.get("cloudflared_pid")
    if old and K.pid_alive(old, "cloudflared"):
        kill_pid(old, "cloudflared")
    # also stop any stray quick tunnel of ours pointing at the same port
    for p in Path("/proc").glob("[0-9]*"):
        try:
            cmd = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if str(CLOUDFLARED) in cmd and f"127.0.0.1:{cfg['port']}" in cmd:
            kill_pid(int(p.name), "cloudflared")
    if CF_LOG.exists():
        shutil.move(CF_LOG, CF_LOG.with_suffix(".log.1"))
    pid = spawn([str(CLOUDFLARED), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{cfg['port']}"], CF_LOG)
    st["cloudflared_pid"] = pid
    st["cloudflared_started_at"] = K.iso(K.now_local())
    st.setdefault("tunnel_restarts", []).append(time.time())
    st["tunnel_restarts"] = st["tunnel_restarts"][-20:]
    url = None
    for _ in range(90):
        time.sleep(1)
        txt = CF_LOG.read_text(errors="replace") if CF_LOG.exists() else ""
        m = URL_RE.search(txt)
        if m:
            url = m.group(0)
        if url and "Registered tunnel connection" in txt:
            break
        if not K.pid_alive(pid, "cloudflared"):
            if "429" in txt and "quick tunnel" in txt.lower():
                st["tunnel_error"] = f"Cloudflare rate limit (HTTP 429) at {K.iso(K.now_local())}; retrying every watchdog run"
                log("Cloudflare is rate-limiting new quick tunnels from this computer (HTTP 429). Nothing is broken "
                    "locally; the watchdog retries on every run and this usually clears within an hour.")
            else:
                st["tunnel_error"] = f"cloudflared exited during startup at {K.iso(K.now_local())} (see logs/watchdog.log)"
                log("cloudflared exited during startup: " + txt[-400:].replace("\n", " | "))
            return None
    if not url:
        log("cloudflared started but no URL appeared within 90 s")
        return None
    st.pop("tunnel_error", None)
    K.URL_PATH.write_text(url + "\n")
    log(f"tunnel started pid={pid} url={url}; waiting for public reachability")
    time.sleep(3)
    for _ in range(24):  # new hostnames can take a few seconds to appear in DNS
        if not srv.heal("server stopped answering while waiting for the new tunnel"):
            log("server could not be restarted; not waiting on the tunnel (will re-check next run)")
            return url
        if e2e_ok(url, srv.instance, tries=1, fresh=True, srv=srv):
            log(f"tunnel verified end-to-end: {url}")
            return url
        time.sleep(5)
    log(f"tunnel {url} not reachable end-to-end yet; will re-check next run")
    return url


def ensure_tunnel(cfg: dict, st: dict, srv: Server, force: bool = False) -> tuple[str | None, bool]:
    url = K.current_url()
    pid = st.get("cloudflared_pid")
    alive = bool(pid and K.pid_alive(pid, "cloudflared"))
    if alive and url and not force:
        if e2e_ok(url, srv.instance, srv=srv):
            return url, True
        # The public check failed. Local server FIRST: if it is down, restart it and re-check the
        # SAME tunnel before touching cloudflared (a working tunnel keeps its URL).
        before = srv.instance
        if not srv.heal(f"tunnel {url} failed end-to-end check"):
            log("server is down and could not be restarted; leaving the tunnel alone")
            return url, False
        if srv.instance != before:
            if e2e_ok(url, srv.instance, srv=srv):
                log(f"tunnel {url} fine again after the server restart (URL unchanged)")
                return url, True
        log(f"tunnel {url} failed end-to-end check (pid {pid} alive, server healthy); restarting tunnel")
    elif not force:
        log(f"tunnel not running (pid={pid}, url={'set' if url else 'none'}); starting")
    # back off only after consecutive FAILED attempts (quick-tunnel creation can be rate limited)
    streak = st.get("tunnel_fail_streak", 0)
    if streak >= 3:
        wait_s = min(60 * 2 ** (streak - 3), 900)
        if time.time() - st.get("last_tunnel_attempt", 0) < wait_s:
            log(f"{streak} failed tunnel attempts in a row; backing off ({wait_s}s between attempts)")
            return url, False
    if not srv.heal("about to start a tunnel"):
        return url, False
    st["last_tunnel_attempt"] = time.time()
    if not ensure_cloudflared(cfg):
        st["tunnel_fail_streak"] = streak + 1
        return url, False
    new = start_tunnel(cfg, st, srv)
    ok = bool(new and e2e_ok(new, srv.instance, tries=1, srv=srv))
    if new and not ok and not srv.up():
        # the server died, not the tunnel: don't count it against the tunnel
        srv.heal("server died right after the tunnel started")
        ok = bool(e2e_ok(new, srv.instance, tries=2, srv=srv))
    st["tunnel_fail_streak"] = 0 if ok else streak + 1
    return new, ok


# ------------------------------------------------------------------ publish
def maybe_publish(cfg: dict, url: str, force: bool = False) -> None:
    pairing = K.load_pairing()
    if not pairing:
        return
    ps = K.read_json(K.PUBLISH_STATE, {}) or {}
    labels = [RV.channel_label(c) for c in pairing["channels"]]
    chans = ps.get("channels", {})
    stale = time.time() - ps.get("last_full_ts", 0) >= float(cfg.get("republish_s", 3600))
    if force or url != ps.get("url") or stale:
        todo, why = None, ("forced" if force else "url changed" if url != ps.get("url") else "periodic refresh")
    else:
        todo = [lab for lab in labels
                if (chans.get(lab, {}).get("url") != url or chans.get(lab, {}).get("error"))
                and RV.retry_due(chans.get(lab, {}))]
        why = "retry failed channels"
        if not todo:
            return
    if url != ps.get("url") and pairing.get("qr"):
        try:  # keep pairing-qr.png pointing at the live URL (a QR for a dead URL can't be opened)
            K.write_pairing_qr(pairing, url, pairing["qr"]["plant"], pairing["qr"]["camera"])
            log("pairing QR/link refreshed for the new URL")
        except Exception as e:  # noqa: BLE001
            log(f"QR refresh failed: {e}")
    res = RV.publish(url, pairing, ps, only=todo)
    if todo is None:
        ps["last_full_ts"] = time.time()
    ps["url"] = url
    ok = [k for k, v in res["results"].items() if v["ok"]]
    bad = {k: v.get("error") for k, v in res["results"].items() if not v["ok"]}
    vias = {k: v.get("via") for k, v in res["results"].items() if v["ok"] and v.get("via") != "https"}
    K.write_json_atomic(K.PUBLISH_STATE, ps)
    log(f"published seq={res['seq']} ({why}) ok={ok}" + (f" failed={bad}" if bad else "")
        + (f" via={vias}" if vias else ""))


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-publish", action="store_true")
    ap.add_argument("--restart-tunnel", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    K.ensure_dirs()
    cfg = K.load_config()
    pairing, created = K.ensure_pairing(cfg)
    if created:
        log("created new pairing secret + rendezvous topics (run `kalecam pair` to make the QR)")
    st = K.read_json(K.WATCHDOG_STATE, {}) or {}
    t0 = time.time()
    srv = Server(cfg, st)
    h = srv.ensure()
    url, ok = None, False
    if h:
        url, ok = ensure_tunnel(cfg, st, srv, force=a.restart_tunnel)
        h = srv.up() or srv.heal("server down at the end of the pass")
        if url and ok:
            try:
                maybe_publish(cfg, url, force=a.force_publish)
            except Exception as e:  # noqa: BLE001
                log(f"publish error: {e}")
            try:  # device-bridge rendezvous (separate channels keyed from the bridge key)
                import bridge_rendezvous as BRV
                BRV.maybe_publish(cfg, url, force=a.force_publish, log=log)
            except Exception as e:  # noqa: BLE001
                log(f"bridge rendezvous publish error: {type(e).__name__}: {e}")
    st.update({"last_run_at": K.iso(K.now_local()), "last_run_ok": bool(h and ok), "url": url,
               "server_ok": bool(h), "tunnel_ok": ok, "run_s": round(time.time() - t0, 1)})
    K.write_json_atomic(K.WATCHDOG_STATE, st)
    if not a.quiet:
        print(json.dumps({"ok": bool(h and ok), "server": bool(h), "tunnel": ok, "url": url,
                          "run_s": st["run_s"]}))
    return 0 if (h and ok) else 1


if __name__ == "__main__":
    sys.exit(main())
