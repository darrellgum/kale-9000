#!/usr/bin/env python3
"""AES-GCM (pure Python vs NIST + cryptography), rendezvous crypto/topics compatibility with the
bot-side publisher, relay reading over fake ntfy/textdb, and replay protection.

Opt-in live check against the real ntfy.sh:  KALEBRIDGE_LIVE_NTFY=1 python3 tests/test_rendezvous.py
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import sys
import tempfile
import unittest
from pathlib import Path

REF = Path(__file__).resolve().parents[1]
CAPTURE = Path(os.environ.get("KALECAM_CODE", REF.parents[1] / "capture"))
sys.path.insert(0, str(REF))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakes import FakeRelay  # noqa: E402
from kalebridge import aesgcm, rendezvous as R  # noqa: E402


def have_bot_code() -> bool:
    try:
        import cryptography  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return (CAPTURE / "bridge_rendezvous.py").exists()


def bot_modules():
    os.environ.setdefault("KALECAM_HOME", tempfile.mkdtemp(prefix="kb-rv-bothome-"))
    sys.path.insert(0, str(CAPTURE))
    import bridge_rendezvous as BRV  # noqa: E402
    import rendezvous as BOTRV  # noqa: E402
    return BRV, BOTRV


def new_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()


class AESGCMTest(unittest.TestCase):
    def test_nist_case_16(self):
        k = bytes.fromhex("feffe9928665731c6d6a8f9467308308feffe9928665731c6d6a8f9467308308")
        iv = bytes.fromhex("cafebabefacedbaddecaf888")
        pt = bytes.fromhex("d9313225f88406e5a55909c5aff5269a86a7a9531534f7da2e4c303d8a318a721c3c0c95956809532fcf0e2449a6b525b16aedf5aa0de657ba637b39")
        aad = bytes.fromhex("feedfacedeadbeeffeedfacedeadbeefabaddad2")
        ct = aesgcm.py_encrypt(k, iv, pt, aad)
        self.assertEqual(ct[-16:].hex(), "76fc6ece0f4e1768cddf8853bb2d551b")
        self.assertEqual(aesgcm.py_decrypt(k, iv, ct, aad), pt)

    def test_nist_case_13_empty(self):
        k = bytes(32)
        ct = aesgcm.py_encrypt(k, bytes(12), b"", b"")
        self.assertEqual(ct.hex(), "530f8afbc74536b9a963b4f1c4cb738b")

    def test_tamper_rejected(self):
        k, iv = os.urandom(32), os.urandom(12)
        ct = bytearray(aesgcm.py_encrypt(k, iv, b"hello world", b"aad"))
        ct[0] ^= 1
        with self.assertRaises(ValueError):
            aesgcm.py_decrypt(k, iv, bytes(ct), b"aad")
        with self.assertRaises(ValueError):
            aesgcm.py_decrypt(k, iv, aesgcm.py_encrypt(k, iv, b"x", b"aad"), b"other-aad")

    def test_matches_cryptography(self):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except Exception:  # noqa: BLE001
            self.skipTest("cryptography not installed")
        for n in range(40):
            k, iv, pt, aad = os.urandom(32), os.urandom(12), os.urandom(n * 11), os.urandom(n % 17)
            self.assertEqual(AESGCM(k).encrypt(iv, pt, aad), aesgcm.py_encrypt(k, iv, pt, aad))


class CompatTest(unittest.TestCase):
    """The bridge must derive the same topics/key and read what the bot publishes."""

    @unittest.skipUnless(have_bot_code(), "bot-side code or cryptography not available")
    def test_bot_encrypt_bridge_decrypt_pure_python(self):
        BRV, _ = bot_modules()
        key = new_key()
        cfg = {"rendezvous": [{"type": "ntfy", "base": "https://ntfy.sh"}, {"type": "textdb", "base": "https://textdb.online"}]}
        self.assertEqual([c["topic"] for c in BRV.channels(key, cfg)],
                         [c["topic"] for c in R.channels(key, BRV.blob_rv(cfg))])
        self.assertEqual(BRV.rv_key(key), R.rv_key(key))
        msg = BRV.encrypt(key, {"v": 1, "url": "https://a-b-c.trycloudflare.com", "issued_at": "x", "seq": 42})
        os.environ["KALEBRIDGE_PURE_AES"] = "1"
        try:
            self.assertEqual(aesgcm.backend(), "pure-python")
            self.assertEqual(R.decrypt(key, msg)["seq"], 42)
            back = R.encrypt(key, {"v": 1, "url": "https://x.example", "seq": 7})
        finally:
            os.environ.pop("KALEBRIDGE_PURE_AES")
        self.assertEqual(BRV.decrypt(key, back)["seq"], 7)
        self.assertIsNone(R.decrypt(new_key(), msg))  # wrong key
        self.assertIsNone(R.decrypt(key, "garbage"))

    @unittest.skipUnless(have_bot_code(), "bot-side code not available")
    def test_phone_messages_do_not_decrypt_with_bridge_key(self):
        """Domain separation: the phone channel's key and the bridge key are unrelated."""
        _, _ = bot_modules()
        import kalecam_lib as K
        pairing = {"secret": new_key()}
        phone_msg = K.rv_encrypt(pairing, {"v": 1, "url": "https://p.example", "seq": 1})
        self.assertIsNone(R.decrypt(pairing["secret"], phone_msg))


class RelayReadTest(unittest.TestCase):
    def setUp(self):
        self.n = FakeRelay("ntfy")
        self.t = FakeRelay("textdb")
        self.key = new_key()
        self.rv = [["n", self.n.url], ["t", self.t.url]]

    def tearDown(self):
        self.n.close()
        self.t.close()

    def publish(self, url, seq, which="both", key=None):
        for kind, relay in (("ntfy", self.n), ("textdb", self.t)):
            if which not in ("both", kind):
                continue
            topic = R.topic_for(self.key, kind, relay.url)
            relay.msgs.setdefault(topic, [])
            m = R.encrypt(key or self.key, {"v": 1, "url": url, "issued_at": "t", "seq": seq})
            if kind == "ntfy":
                relay.msgs[topic].append(m)
            else:
                relay.msgs[topic] = [m]

    def test_newest_seq_wins_across_channels(self):
        self.publish("https://old.example", 5)
        self.publish("https://new.example", 9, which="ntfy")
        self.publish("https://forged.example", 99, which="ntfy", key=new_key())  # wrong key: ignored
        d = R.discover(self.key, self.rv, timeout=5)
        self.assertEqual(d["best"]["seq"], 9)
        self.assertEqual(d["best"]["url"], "https://new.example")
        labels = {c["label"].split(":")[0]: c for c in d["channels"]}
        self.assertEqual(labels["ntfy"]["valid"], 2)
        self.assertEqual(labels["ntfy"]["messages"], 3)
        self.assertEqual(labels["textdb"]["seq"], 5)

    def test_empty_and_unreachable(self):
        d = R.discover(self.key, self.rv + [["n", "http://127.0.0.1:1"]], timeout=3)
        self.assertIsNone(d["best"])
        self.assertEqual(len(d["channels"]), 3)

    def test_service_replay_protection(self):
        """Service.try_rendezvous only accepts seq > last_seq, https (or allowed local), verified URL."""
        from kalebridge import config as C
        from kalebridge.engine import Engine
        from kalebridge.service import Service
        home = Path(tempfile.mkdtemp(prefix="kb-rv-svc-"))
        p = C.paths(home)
        C.save_config({"url": "https://current.example", "key": self.key, "bridge_id": "b1", "rv": self.rv,
                       "settings": {}}, p)
        e = Engine(p)
        e.state["last_seq"] = 50
        s = Service(e)
        self.publish("https://stale.example", 40)
        self.assertFalse(s.try_rendezvous())            # replayed / older seq
        self.assertEqual(s.client.url, "https://current.example")
        self.publish("http://evil.example", 60, which="ntfy")
        self.assertFalse(s.try_rendezvous())            # not https
        self.publish("https://unreachable.invalid", 61, which="ntfy")
        self.assertFalse(s.try_rendezvous())            # does not answer /bridge/config
        self.assertEqual(e.state["last_seq"], 50)       # nothing accepted
        self.assertEqual(s.client.url, "https://current.example")


@unittest.skipUnless(os.environ.get("KALEBRIDGE_LIVE_NTFY") == "1", "set KALEBRIDGE_LIVE_NTFY=1 for the real ntfy.sh check")
class LiveNtfyTest(unittest.TestCase):
    def test_real_ntfy_publish_and_read(self):
        """One real publish to ntfy.sh on a random throwaway topic (throwaway key), then read it back."""
        key = new_key()
        payload = {"v": 1, "url": "https://live-test.example", "issued_at": "t", "seq": 123456}
        if have_bot_code():
            BRV, BOTRV = bot_modules()
            cfg = {"rendezvous": [{"type": "ntfy", "base": "https://ntfy.sh"}]}
            ch = BRV.channels(key, cfg)[0]
            res = BOTRV.publish_one(ch, BRV.encrypt(key, payload))
        else:
            import urllib.request
            topic = R.topic_for(key, "ntfy", "https://ntfy.sh")
            req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=R.encrypt(key, payload).encode(),
                                         headers={"Cache": "yes", "Firebase": "no", "Priority": "min"})
            urllib.request.urlopen(req, timeout=15).read()
            res = {"ok": True, "via": "https"}
        self.assertTrue(res["ok"], res)
        os.environ["KALEBRIDGE_PURE_AES"] = "1"
        try:
            d = R.discover(key, [["n", "https://ntfy.sh"]], timeout=15)
        finally:
            os.environ.pop("KALEBRIDGE_PURE_AES")
        print(f"\n  live ntfy.sh: publish via {res.get('via')}, read {d['channels']}", file=sys.stderr)
        self.assertEqual(d["best"]["seq"], 123456)
        self.assertEqual(d["best"]["url"], "https://live-test.example")


if __name__ == "__main__":
    unittest.main()
