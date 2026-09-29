#!/usr/bin/env python3
"""End-to-end test with headless Chrome + fake camera through the REAL public tunnel.

Phases: pair/connect -> CLI capture -> timed captures -> heartbeats -> tamper/replay ->
failover in `navigate` mode (kill cloudflared; the running watchdog loop heals + publishes) ->
failover in `sticky` mode with the cloudflared binary deleted (watchdog re-downloads) + reload on
the dead origin (service worker) -> reboot simulation (kill everything, run the routine command).

ISOLATED by default: copies this code into a throwaway directory, gives it its own port
(KALECAM_E2E_PORT, default 18795), photo root, state, secrets and quick tunnel, runs the test
there, then kills that instance and deletes the directory. A live install (its schedule, config,
pairing and phone) is never touched. Results are copied to test-results/e2e-isolated/.

  venv/bin/pip install -r requirements-test.txt
  venv/bin/python tests/e2e_test.py              # isolated (recommended)
  venv/bin/python tests/e2e_test.py --live       # in place: rewrites this install's schedule,
                                                 # kills its tunnel 3x; re-pair the phone after
Chrome: KALECAM_E2E_CHROME (default /usr/bin/google-chrome).
Never prints the pairing secret."""
import json, os, shutil, signal, subprocess, sys, tempfile, time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
CHROME = os.environ.get("KALECAM_E2E_CHROME", "/usr/bin/google-chrome")


def run_isolated() -> int:
    port = int(os.environ.get("KALECAM_E2E_PORT", "18795"))
    tmp = Path(tempfile.mkdtemp(prefix="kalecam-e2e-"))
    home = tmp / "kalecam"
    ignore = shutil.ignore_patterns("state", "secrets", "logs", "test-results", "venv", "bin", "config.json",
                                    "pairing-qr*.png", "__pycache__")
    shutil.copytree(BASE, home, ignore=ignore)
    (home / "venv").symlink_to(BASE / "venv")          # python + packages only; no state inside
    if (BASE / "bin" / "cloudflared").exists():         # phase 7 deletes it; the watchdog re-downloads the pinned one
        (home / "bin").mkdir()
        shutil.copy2(BASE / "bin" / "cloudflared", home / "bin" / "cloudflared")
    (home / "config.json").write_text(json.dumps({"port": port, "photo_root": str(tmp / "photos")}, indent=1))
    env = {k: v for k, v in os.environ.items() if k != "KALECAM_HOME"}
    env["KALECAM_E2E_CHILD"] = "1"
    print(f"isolated e2e instance: {home} port {port}", flush=True)
    rc = 1
    try:
        r = subprocess.run([str(home / "watchdog.sh"), "--ensure-loop"], cwd=home, env=env, capture_output=True, text=True, timeout=400)
        print("watchdog:", r.stdout.strip().splitlines()[-1:] if r.stdout.strip() else r.stderr[-300:], flush=True)
        subprocess.run([str(home / "kalecam"), "pair", "--plant", "kalecam-test", "--camera", "test-phone"], cwd=home, env=env,
                       capture_output=True, text=True, timeout=120)
        rc = subprocess.run([str(home / "venv" / "bin" / "python"), str(home / "tests" / "e2e_test.py"), "--live"], cwd=home, env=env).returncode
    finally:
        subprocess.run(["pkill", "-9", "-f", str(home / "watchdog.sh")])
        ws = json.loads((home / "state" / "watchdog-state.json").read_text()) if (home / "state" / "watchdog-state.json").exists() else {}
        for pid in (ws.get("server_pid"), ws.get("cloudflared_pid")):
            try:
                os.kill(int(pid), signal.SIGKILL)
            except Exception:
                pass
        subprocess.run(["pkill", "-9", "-f", str(home)])  # anything else started from the temp copy
        out = BASE / "test-results" / "e2e-isolated"
        shutil.rmtree(out, ignore_errors=True)
        if (home / "test-results").exists():
            shutil.copytree(home / "test-results", out)
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"isolated instance torn down; results in {out}", flush=True)
    return rc


if __name__ == "__main__" and "--live" not in sys.argv:
    sys.exit(run_isolated())

from playwright.sync_api import sync_playwright  # noqa: E402
sys.path.insert(0, str(BASE))
import kalecam_lib as K
import rendezvous as RV

OUT = BASE / "test-results"; OUT.mkdir(exist_ok=True)
LOG = open(OUT / "e2e-log.txt", "w")
CAM, PLANT = "test-phone", "kalecam-test"
cfg = K.load_config()
IDX = Path(cfg["photo_root"]) / PLANT / "index.jsonl"
R = {"phases": {}}
T0 = time.time()


def log(*a):
    line = f"{time.strftime('%H:%M:%S')} +{time.time() - T0:6.1f}s " + " ".join(str(x) for x in a)
    print(line, flush=True); LOG.write(line + "\n"); LOG.flush()


def sh(*args, timeout=200):
    r = subprocess.run([str(BASE / "kalecam"), *args], capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout.strip()


def rows():
    return [json.loads(l) for l in IDX.read_text().splitlines()] if IDX.exists() else []


def wd_state():
    return K.read_json(K.WATCHDOG_STATE, {}) or {}


def wait(cond, timeout, every=2.0, what=""):
    end = time.time() + timeout
    while time.time() < end:
        try:
            v = cond()
            if v:
                return v
        except Exception as e:  # page navigating etc.
            pass
        time.sleep(every)
    log("TIMEOUT waiting for", what)
    return None


def phase(name, ok, **info):
    R["phases"][name] = {"pass": bool(ok), **info}
    log(("PASS " if ok else "FAIL ") + name, json.dumps(info, default=str)[:600])


JS_STATE = """() => { const S = window.kalecam && window.kalecam.S; if (!S) return null;
  return {connected: S.connected, apiBase: S.apiBase, origin: location.origin, queue: S.queue, lastCapture: S.lastCapture,
          lastUpload: S.lastUpload, failures: S.failures, wake: S.wakeState, res: S.resolution, cam: S.camLabel,
          migrate: S.cfg && S.cfg.migrate, cfgv: S.cfg && S.cfg.version, lastSeq: S.lastSeq, sw: !!navigator.serviceWorker.controller,
          hashInUrl: location.href.includes('#'), events: S.events.slice(-6), battery: S.battery ? {level: S.battery.level, charging: S.battery.charging} : null}; }"""


def main():
    link = (BASE / "secrets/pairing-url.txt").read_text().strip()
    # test settings: 1-minute schedule all day, 15 s heartbeats
    sh("schedule", "set", "--interval", "1", "--start", "00:00", "--end", "00:00", "--on")
    sh("config", "set", "heartbeat_s", "15")
    sh("config", "set", "migrate", "navigate")
    prof = tempfile.mkdtemp(prefix="kalecam-e2e-profile-")
    subprocess.run(["rm", "-rf", prof])
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(prof, executable_path=CHROME, headless=True,
            args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"],
            viewport={"width": 412, "height": 915})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        clog = open(OUT / "e2e-console.txt", "w")
        page.on("console", lambda m: clog.write(f"{time.strftime('%H:%M:%S')} {m.text[:300]}\n") or clog.flush())
        page.on("pageerror", lambda e: clog.write(f"{time.strftime('%H:%M:%S')} PAGEERROR {e}\n"))
        st = lambda: page.evaluate(JS_STATE)

        # ---------------------------------------------------------------- 1. pairing + connect
        t = time.time(); page.goto(link)
        s = wait(lambda: (lambda x: x if x and x["connected"] and x["res"] else None)(st()), 60, 1, "connect")
        prep_visible = page.evaluate("() => !document.getElementById('prep').hidden")
        phase("1 pair via link + connect through public tunnel", bool(s), secs=round(time.time() - t, 1), camera=s and s["cam"],
              resolution=s and s["res"], wake_lock=s and s["wake"], sw=s and s["sw"], fragment_stripped=s and not s["hashInUrl"],
              prep_checklist_shown_first_run=prep_visible, battery=s and s["battery"])
        page.click("#btnPrepDone")
        pairing_origin = s["origin"]

        # ---------------------------------------------------------------- 2. CLI capture on command
        t = time.time(); rc, out = sh("capture", CAM, "--wait", "60")
        lines = [json.loads(l) for l in out.splitlines()]
        done = [l for l in lines if l.get("status") == "done"]
        f = done and done[0]["file"]
        phase("2 kalecam capture -> photo stored", rc == 0 and f and Path(f).exists(), secs=round(time.time() - t, 1), file=f,
              bytes=done and done[0]["bytes"])

        # ---------------------------------------------------------------- 3. timed captures
        t = time.time()
        sched = wait(lambda: (lambda r: r if len(r) >= 2 else None)([x for x in rows() if x.get("trigger") == "schedule" and x.get("source") == CAM
                                                                     and x["received_at"] >= time.strftime("%Y-%m-%dT%H:%M", time.localtime(t))]),
                     200, 5, "2 scheduled photos")
        phase("3 scheduled captures (1-min schedule)", bool(sched), secs=round(time.time() - t, 1),
              photos=[(x["file"], x["ts"]) for x in (sched or [])][:3])

        # ---------------------------------------------------------------- 4. heartbeat
        hb = K.read_json(K.HB_DIR / f"{CAM}.json", {})
        age = time.time() - hb.get("received_ts", 0)
        rc, out = sh("status")
        phase("4 heartbeat received + kalecam status", age < 40 and "battery" in hb, age_s=round(age, 1),
              fields=sorted(hb.keys()), battery=hb.get("battery"), wake_lock=hb.get("wake_lock"), visible=hb.get("visible"),
              status_excerpt=[l for l in out.splitlines() if l.startswith("camera")])
        (OUT / "status-during-test.txt").write_text(out + "\n")

        # ---------------------------------------------------------------- 5. tamper + replay
        pairing = K.load_pairing()
        forged = "kc1." + K.b64u(os.urandom(80))
        good = K.rv_encrypt(pairing, {"v": 1, "url": "https://evil.example", "issued_at": "x", "seq": 5})
        flipped = good[:-5] + ("A" if good[-5] != "A" else "B") + good[-4:]
        r_forged = page.evaluate("t => kalecam.decryptRv(t)", forged)
        r_flip = page.evaluate("t => kalecam.decryptRv(t)", flipped)
        r_good = page.evaluate("t => kalecam.decryptRv(t)", good)
        # publish an authentic-but-old (replayed) message to a real channel; page must not switch
        ch = [c for c in pairing["channels"] if "envs" in c["base"]][0]
        RV.publish_one(ch, good)
        before = st()["apiBase"]
        page.evaluate("() => kalecam.resolveRendezvous(true)")
        time.sleep(3)
        after = st()["apiBase"]
        phase("5 forged/tampered payloads rejected, old seq replay ignored", r_forged is None and r_flip is None and r_good and r_good["seq"] == 5
              and before == after, python_to_js_decrypt_ok=bool(r_good), api_unchanged=before == after)

        # ---------------------------------------------------------------- 6. failover, navigate mode
        s = st(); assert s["migrate"] == "navigate", s
        old_url = K.current_url(); old_pid = wd_state().get("cloudflared_pid")
        tk = time.time(); os.kill(old_pid, signal.SIGKILL); log("killed cloudflared", old_pid, "url", old_url)
        time.sleep(1)
        rc, out = sh("capture", CAM)  # bot asks for a photo while the phone can't reach us
        outage_cmd = json.loads(out.splitlines()[0])["queued"]
        page.evaluate("() => kalecam.capture('manual')")  # photo taken during the outage -> must be queued
        q = wait(lambda: (lambda x: x if x and x["queue"] > 0 else None)(st()), 30, 0.5, "photo queued offline")
        log("phone queue during outage:", q and q["queue"], "failures", q and q["failures"])
        new_url = wait(lambda: (lambda u: u if u and u != old_url and wd_state().get("tunnel_ok") else None)(K.current_url()), 400, 3, "watchdog new URL")
        t_new = time.time()
        ps = K.read_json(K.PUBLISH_STATE, {})
        moved = wait(lambda: (lambda x: x if x and x["origin"] == new_url and x["connected"] else None)(st()), 240, 2, "page navigated to new origin")
        t_moved = time.time()
        drained = wait(lambda: (lambda x: x if x and x["queue"] == 0 else None)(st()), 120, 3, "queue drained")
        t_drained = time.time()
        cstat = wait(lambda: (lambda s_: s_ if s_[0] == "done" else None)(K.command_status(outage_cmd)), 120, 2, "outage command done")
        queued_rows = [x for x in rows() if x.get("queued") and x["received_at"] >= time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(tk))]
        rc, out = sh("capture", CAM, "--wait", "60")
        phase("6 failover (navigate mode): kill cloudflared -> watchdog new URL -> page navigates + resumes",
              bool(new_url and moved and drained and cstat and rc == 0 and queued_rows),
              old_url=old_url, new_url=new_url, page_origin=moved and moved["origin"],
              watchdog_heal_s=round(t_new - tk, 1), page_moved_s=round(t_moved - tk, 1), queue_drained_s=round(t_drained - tk, 1),
              photos_queued_offline=q and q["queue"], queued_rows_uploaded=[(x["file"], x["ts"], x["received_at"]) for x in queued_rows],
              outage_command=cstat and cstat[0], capture_after=out.splitlines()[-1] if out else None,
              published_channels={k: v.get("last_ok_at") for k, v in ps.get("channels", {}).items()})

        # ---------------------------------------------------------------- 7. failover, sticky mode + missing binary + reload on dead origin
        sh("config", "set", "migrate", "sticky")
        wait(lambda: (lambda x: x if x and x["migrate"] == "sticky" else None)(st()), 90, 2, "page picks up sticky")
        sticky_origin = st()["origin"]
        old_url = K.current_url(); old_pid = wd_state().get("cloudflared_pid")
        (K.BIN / "cloudflared").unlink()
        log("deleted bin/cloudflared")
        tk = time.time(); os.kill(old_pid, signal.SIGKILL); log("killed cloudflared", old_pid)
        time.sleep(1)
        page.evaluate("() => kalecam.capture('manual')")
        q = wait(lambda: (lambda x: x if x and x["queue"] > 0 else None)(st()), 30, 0.5, "photo queued offline (sticky)")
        new_url = wait(lambda: (lambda u: u if u and u != old_url and wd_state().get("tunnel_ok") else None)(K.current_url()), 400, 3, "watchdog new URL")
        t_new = time.time()
        redl = "cloudflared installed" in (BASE / "logs/watchdog.log").read_text().split("deleted")[-1] if False else \
            any("cloudflared installed" in l for l in (BASE / "logs/watchdog.log").read_text().splitlines()[-15:])
        sw_ = wait(lambda: (lambda x: x if x and x["apiBase"] == new_url and x["connected"] else None)(st()), 240, 2, "page follows API (sticky)")
        t_sw = time.time()
        drained = wait(lambda: (lambda x: x if x and x["queue"] == 0 else None)(st()), 120, 3, "queue drained")
        rc1, out1 = sh("capture", CAM, "--wait", "60")
        # reload the page while its own origin is dead: service worker must serve the shell
        page.reload()
        rl = wait(lambda: (lambda x: x if x and x["connected"] and x["res"] else None)(st()), 90, 2, "reload on dead origin")
        origin_dead = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-m", "10", sticky_origin + "/healthz"], capture_output=True, text=True).stdout
        rc2, out2 = sh("capture", CAM, "--wait", "60")
        phase("7 failover (sticky mode, cloudflared binary deleted): re-download, page follows API, SW reload on dead origin",
              bool(new_url and redl and sw_ and drained and rc1 == 0 and rl and rc2 == 0 and (K.BIN / "cloudflared").exists()),
              old_url=old_url, new_url=new_url, page_origin_stays=sw_ and sw_["origin"], api_base=sw_ and sw_["apiBase"],
              binary_redownloaded=redl, watchdog_heal_s=round(t_new - tk, 1), page_resumed_s=round(t_sw - tk, 1),
              photos_queued_offline=q and q["queue"], old_origin_http=origin_dead, reload_ok=bool(rl), sw_controlled=rl and rl["sw"],
              capture_after=out1.splitlines()[-1] if out1 else None, capture_after_reload=out2.splitlines()[-1] if out2 else None)

        # ---------------------------------------------------------------- 8. reboot simulation
        loop_pid = int((K.STATE / "watchdog-loop.pid").read_text())
        ws = wd_state()
        for pid, name in ((loop_pid, "loop"), (ws.get("server_pid"), "server"), (ws.get("cloudflared_pid"), "cloudflared")):
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL) if name == "loop" else os.kill(pid, signal.SIGKILL)
            except Exception as e:
                log("kill", name, e)
        subprocess.run(["pkill", "-9", "-f", str(BASE / "watchdog.sh")])
        log("killed loop, server, cloudflared (reboot simulation)")
        time.sleep(3)
        tk = time.time()
        r = subprocess.run([str(BASE / "watchdog.sh"), "--ensure-loop"], capture_output=True, text=True, timeout=300)
        t_up = time.time()
        log("routine output:", r.stdout.strip().replace("\n", " | "))
        new_url = K.current_url()
        back = wait(lambda: (lambda x: x if x and x["apiBase"] == new_url and x["connected"] else None)(st()), 240, 2, "page back after reboot")
        t_back = time.time()
        rc, out = sh("capture", CAM, "--wait", "60")
        loop_ok = K.pid_alive(int((K.STATE / "watchdog-loop.pid").read_text()), "watchdog.sh")
        phase("8 reboot simulation: everything killed, routine command restores all", r.returncode == 0 and bool(back) and rc == 0 and loop_ok,
              restore_s=round(t_up - tk, 1), page_back_s=round(t_back - tk, 1), new_url=new_url, loop_running=loop_ok,
              capture_after=out.splitlines()[-1] if out else None)

        page.screenshot(path=str(OUT / "e2e-final.png"))
        R["final_state"] = st()
        ctx.close()
    subprocess.run(["rm", "-rf", prof])
    R["passed"] = sum(1 for v in R["phases"].values() if v["pass"]); R["total"] = len(R["phases"])
    (OUT / "e2e-results.json").write_text(json.dumps(R, indent=1, default=str))
    log(f"RESULT {R['passed']}/{R['total']} phases passed")
    return 0 if R["passed"] == R["total"] else 1


if __name__ == "__main__":
    rc = 1
    try:
        rc = main()
    finally:
        # restore normal settings
        sh("schedule", "set", "--interval", "30", "--start", "06:00", "--end", "22:00")
        sh("config", "set", "heartbeat_s", "60")
        sh("config", "set", "migrate", "sticky")
    sys.exit(rc)
