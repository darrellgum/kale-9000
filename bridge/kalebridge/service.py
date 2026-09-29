"""`kalebridge run`: the long-running loop. Dials out to the bot, long-polls, reports results,
sends heartbeats, follows URL changes through the encrypted rendezvous, and ticks the engine
(timers, holds, fallback, pump interlock) once per second in a second thread."""
from __future__ import annotations

import logging
import random
import signal
import threading
import time

from . import VERSION
from . import config as C
from . import rendezvous as R
from .client import AuthError, BotClient, NetError
from .engine import Engine

log = logging.getLogger("kalebridge")


class RedactFilter(logging.Filter):
    """Replace every known secret (bridge key, device passwords, tokens) with *** in log lines."""

    def __init__(self, secrets_fn):
        super().__init__()
        self.secrets_fn = secrets_fn

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        red = msg
        for s in self.secrets_fn():
            if s and s in red:
                red = red.replace(s, "***")
        if red != msg:
            record.msg, record.args = red, None
        return True


def setup_logging(verbose: bool = False, secrets_fn=lambda: []) -> None:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%S%z"))
    h.addFilter(RedactFilter(secrets_fn))
    root = logging.getLogger("kalebridge")
    root.handlers[:] = [h]
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.propagate = False


class Service:
    def __init__(self, engine: Engine):
        self.e = engine
        c = engine.cfg
        self.s = engine.settings
        url = engine.state.get("current_url") or c["url"]
        self.client = BotClient(url, c["key"], c["bridge_id"], timeout=float(self.s.get("request_timeout_s") or 15))
        self.stop = threading.Event()
        self.failures = 0
        self.last_rv = 0.0
        self.warned_no_rv = False
        self.rv_misses = 0

    # ------------------------------------------------------------ helpers
    def hb_interval(self) -> int:
        return int(self.s.get("heartbeat_s") or (self.e.cache or {}).get("heartbeat_s") or 60)

    def refresh_config(self) -> bool:
        try:
            self.e.set_cache(self.client.config())
            return True
        except AuthError as ex:
            log.error("%s", ex)
        except NetError as ex:
            log.warning("could not fetch /bridge/config: %s", ex)
        return False

    def send_result(self, res: dict) -> bool:
        try:
            self.client.result(res)
            return True
        except NetError as ex:
            if getattr(ex, "code", None) in (400, 404):
                log.warning("bot refused result for %s (%s); dropping it", res.get("id"), ex)
                return True
            log.warning("result for %s not delivered (%s); kept in the outbox", res.get("id"), ex)
        except AuthError as ex:
            log.error("%s", ex)
        self.e.outbox_add(res)
        return False

    def flush_outbox(self) -> None:
        for res in self.e.outbox_items():
            try:
                self.client.result(res)
            except NetError as ex:
                if getattr(ex, "code", None) not in (400, 404):
                    return
            except AuthError:
                return
            self.e.outbox_remove(res["id"])
            log.info("outbox: delivered result for %s", res["id"])

    def heartbeat(self) -> None:
        try:
            r = self.client.heartbeat(self.e.heartbeat_payload())
            self.e.on_contact()
            v = (r or {}).get("config_version")
            if v and v != (self.e.cache or {}).get("version"):
                self.refresh_config()
        except (NetError, AuthError) as ex:
            log.debug("heartbeat failed: %s", ex)

    def try_rendezvous(self) -> bool:
        rv = self.e.cfg.get("rv") or []
        self.last_rv = time.time()
        if not rv:
            if not self.warned_no_rv:
                log.warning("no rendezvous relays in the pairing blob: after a bot URL change, re-pair with a new blob")
                self.warned_no_rv = True
            return False
        d = R.discover(self.e.cfg["key"], rv)
        best = d["best"]
        with self.e.lock:
            self.e.state["rendezvous"] = {"at": self.e.iso(), "channels": d["channels"],
                                          "best_seq": best["seq"] if best else None}
            self.e.save()
        chans = " ".join(f"{c['label']}={c['seq'] if c['ok'] else 'x'}" for c in d["channels"])
        self.rv_misses += 1  # reset below on success
        quiet = log.info if self.rv_misses <= 3 or self.rv_misses % 10 == 0 else log.debug
        if not best:
            quiet("rendezvous: no valid message found (%s)", chans)
            return False
        last = int(self.e.state.get("last_seq") or 0)
        if best["seq"] <= last:
            quiet("rendezvous: nothing newer than seq %s (%s)", last, chans)
            return False
        url = best["url"].rstrip("/")
        if not C.valid_bot_url(url, bool(self.s.get("allow_http_urls"))):
            log.warning("rendezvous: rejected a non-https address (seq %s)", best["seq"])
            return False
        if url == self.client.url:
            with self.e.lock:
                self.e.state["last_seq"] = best["seq"]
                self.e.save()
            log.info("rendezvous: seq %s still names the current address", best["seq"])
            return False
        probe = BotClient(url, self.e.cfg["key"], self.e.cfg["bridge_id"], timeout=self.client.timeout)
        try:
            conf = probe.config()
        except (NetError, AuthError) as ex:
            log.info("rendezvous: new address (seq %s) does not answer yet: %s", best["seq"], ex)
            return False
        self.client.url = url
        with self.e.lock:
            self.e.state["current_url"] = url
            self.e.state["last_seq"] = best["seq"]
            self.e.save()
        self.e.set_cache(conf)
        self.e.on_contact()
        self.rv_misses = 0
        log.info("rendezvous: switched to the bot's new address %s (seq %s)", url, best["seq"])
        return True

    # ------------------------------------------------------------ threads
    def ticker(self) -> None:
        while not self.stop.is_set():
            try:
                self.e.tick()
            except Exception:  # noqa: BLE001
                log.exception("tick error")
            self.stop.wait(1.0)

    def heartbeater(self) -> None:
        while not self.stop.is_set():
            try:
                self.heartbeat()
            except Exception:  # noqa: BLE001
                log.exception("heartbeat error")
            self.stop.wait(self.hb_interval())

    def run(self) -> int:
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, lambda *_: self.stop.set())
            except ValueError:  # not in the main thread (tests)
                pass
        log.info("kalebridge %s starting: bridge %s, bot %s%s, aliases bound: %s", VERSION, self.e.cfg["bridge_id"],
                 self.client.url, " [DRY RUN: nothing will be switched]" if self.e.dry_run else "",
                 ", ".join(self.e.bound()) or "none")
        self.e.save()
        self.refresh_config()
        threading.Thread(target=self.ticker, name="tick", daemon=True).start()
        threading.Thread(target=self.heartbeater, name="heartbeat", daemon=True).start()
        hold = max(1, min(25, int(self.s.get("poll_hold_s") or 25)))
        auth_logged = 0.0
        while not self.stop.is_set():
            try:
                cmds, hdrs = self.client.poll(hold)
                self.e.on_contact()
                if self.failures:
                    log.info("bot reachable again after %d failed attempt(s)", self.failures)
                self.failures = 0
                self.rv_misses = 0
                v = hdrs.get("x-bridge-config-version")
                if self.e.cache is None or (v and v != self.e.cache.get("version")):
                    self.refresh_config()
                for c in cmds:
                    res = self.e.handle(c)
                    if res:
                        self.send_result(res)
                self.flush_outbox()
            except AuthError as ex:
                self.failures += 1
                if time.time() - auth_logged > 600:
                    log.error("%s (retrying every 5 min)", ex)
                    auth_logged = time.time()
                self.stop.wait(300)
            except NetError as ex:
                self.failures += 1
                if self.failures == 1 or self.failures % 10 == 0:
                    log.warning("bot unreachable (%s); attempt %d", ex, self.failures)
                # relay reads: every rendezvous_min_interval_s at first, slowing to every 5 min in a long outage
                rv_gap = min(300, int(self.s.get("rendezvous_min_interval_s") or 60) * (1 + self.rv_misses // 5))
                if (self.failures >= int(self.s.get("rendezvous_after_failures") or 3)
                        and time.time() - self.last_rv >= rv_gap):
                    try:
                        if self.try_rendezvous():
                            self.failures = 0
                            continue
                    except Exception:  # noqa: BLE001
                        log.exception("rendezvous error")
                cap = float(self.s.get("backoff_max_s") or 60)
                delay = min(cap, 2 ** min(self.failures - 1, 10)) * random.uniform(0.8, 1.2)
                self.stop.wait(min(delay, cap))
            except Exception:  # noqa: BLE001
                log.exception("unexpected error in the poll loop")
                self.stop.wait(5)
        log.info("stopping")
        self.e.save()
        return 0
