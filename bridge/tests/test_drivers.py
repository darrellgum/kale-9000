#!/usr/bin/env python3
"""Driver unit tests against fake plug servers (stdlib unittest)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakes import FakeHA, FakeKasa, FakeShellyGen1, FakeShellyGen2, FakeTasmota, free_port  # noqa: E402
from kalebridge.drivers import DriverError, make  # noqa: E402
from kalebridge import httputil  # noqa: E402


class ShellyGen1Test(unittest.TestCase):
    def test_on_off_state(self):
        f = FakeShellyGen1()
        d = make({"driver": "shelly_gen1", "host": f.host})
        self.assertFalse(d.get())
        self.assertTrue(d.set(True))
        self.assertTrue(f.on[0])
        self.assertFalse(d.set(False))
        self.assertEqual(f.set_calls, 2)
        f.close()

    def test_channel_and_basic_auth(self):
        f = FakeShellyGen1(relays=2, user="admin", password="pw-gen1")
        d = make({"driver": "shelly1", "host": "http://" + f.host, "channel": 1, "password": "pw-gen1"})
        self.assertTrue(d.set(True))
        self.assertEqual(f.on, [False, True])
        bad = make({"driver": "shelly_gen1", "host": f.host, "password": "wrong"})
        with self.assertRaises(DriverError) as cm:
            bad.get()
        self.assertIn("401", str(cm.exception))
        self.assertNotIn("wrong", str(cm.exception))
        f.close()

    def test_missing_relay(self):
        f = FakeShellyGen1()
        with self.assertRaises(DriverError):
            make({"driver": "shelly_gen1", "host": f.host, "channel": 3}).get()
        f.close()


class ShellyGen2Test(unittest.TestCase):
    def test_no_auth(self):
        f = FakeShellyGen2(switches=2)
        d = make({"driver": "shelly_gen2", "host": f.host, "channel": 1})
        self.assertTrue(d.set(True))
        self.assertEqual(f.on, [False, True])
        self.assertTrue(d.get())
        self.assertFalse(d.set(False))
        f.close()

    def test_digest_sha256(self):
        f = FakeShellyGen2(password="s3cret-pw")
        d = make({"driver": "shelly_plus", "host": f.host, "password": "s3cret-pw"})
        self.assertTrue(d.set(True))
        self.assertTrue(f.on[0])
        with self.assertRaises(DriverError) as cm:
            make({"driver": "shelly_gen2", "host": f.host, "password": "nope-nope"}).get()
        self.assertIn("401", str(cm.exception))
        with self.assertRaises(DriverError):
            make({"driver": "shelly_gen2", "host": f.host}).get()  # auth required, none given
        f.close()

    def test_bad_channel(self):
        f = FakeShellyGen2()
        with self.assertRaises(DriverError):
            make({"driver": "shelly_gen2", "host": f.host, "channel": 9}).get()
        f.close()


class TasmotaTest(unittest.TestCase):
    def test_single(self):
        f = FakeTasmota()
        d = make({"driver": "tasmota", "host": f.host})
        self.assertFalse(d.get())
        self.assertTrue(d.set(True))
        self.assertTrue(f.on[0])
        self.assertFalse(d.set(False))
        f.close()

    def test_multi_channel_with_password(self):
        f = FakeTasmota(relays=4, user="admin", password="tas-pw")
        d = make({"driver": "tasmota", "host": f.host, "channel": 3, "password": "tas-pw"})
        self.assertTrue(d.set(True))
        self.assertEqual(f.on, [False, False, True, False])
        with self.assertRaises(DriverError) as cm:
            make({"driver": "tasmota", "host": f.host, "channel": 3, "password": "bad-pw"}).get()
        self.assertNotIn("bad-pw", str(cm.exception))
        f.close()

    def test_unknown_channel(self):
        f = FakeTasmota()
        with self.assertRaises(DriverError):
            make({"driver": "tasmota", "host": f.host, "channel": 5}).get()
        f.close()


class KasaTest(unittest.TestCase):
    def test_cipher_roundtrip(self):
        from kalebridge.drivers import kasa
        msg = b'{"system":{"get_sysinfo":{}}}'
        enc = kasa.encrypt(msg)
        self.assertEqual(kasa.decrypt(enc[4:]), msg)
        # known first bytes of the XOR autokey stream for '{"sy'
        self.assertEqual(enc[4:8].hex(), "d0f281f8")

    def test_plug(self):
        f = FakeKasa()
        d = make({"driver": "kasa", "host": f.host})
        self.assertFalse(d.get())
        self.assertTrue(d.set(True))
        self.assertEqual(f.relay, 1)
        self.assertFalse(d.set(False))
        f.close()

    def test_strip_child(self):
        f = FakeKasa(children=3)
        d = make({"driver": "kasa", "host": f.host, "channel": 2})
        self.assertTrue(d.set(True))
        self.assertEqual([c["state"] for c in f.children], [0, 0, 1])
        with self.assertRaises(DriverError):
            make({"driver": "kasa", "host": f.host}).get()  # strip without channel
        f.close()

    def test_unreachable(self):
        with self.assertRaises(DriverError):
            make({"driver": "kasa", "host": f"127.0.0.1:{free_port()}", "timeout_s": 1}).get()


class HomeAssistantTest(unittest.TestCase):
    def test_on_off(self):
        f = FakeHA(token="ha-long-lived-token")
        d = make({"driver": "homeassistant", "url": f.url, "token": "ha-long-lived-token", "entity_id": "switch.tent_fan"})
        self.assertFalse(d.get())
        self.assertTrue(d.set(True))
        self.assertEqual(f.states["switch.tent_fan"], "on")
        with self.assertRaises(DriverError) as cm:
            make({"driver": "homeassistant", "url": f.url, "token": "wrong-token", "entity_id": "switch.tent_fan"}).get()
        self.assertNotIn("wrong-token", str(cm.exception))
        f.close()

    def test_requires_entity_and_token(self):
        with self.assertRaises(DriverError):
            make({"driver": "homeassistant", "url": "http://x", "token": "t"})
        with self.assertRaises(DriverError):
            make({"driver": "homeassistant", "url": "http://x", "entity_id": "switch.a"})


class DummyAndRegistryTest(unittest.TestCase):
    def test_dummy(self):
        import tempfile
        p = Path(tempfile.mkdtemp()) / "d.json"
        d = make({"driver": "dummy", "state_file": str(p)})
        self.assertTrue(d.set(True))
        self.assertTrue(make({"driver": "dummy", "state_file": str(p)}).get())  # persisted
        with self.assertRaises(DriverError):
            make({"driver": "dummy", "fail": "boom"}).set(True)

    def test_unknown_driver(self):
        with self.assertRaises(DriverError):
            make({"driver": "no-such-driver"})

    def test_unreachable_http(self):
        with self.assertRaises(DriverError):
            make({"driver": "shelly_gen2", "host": f"127.0.0.1:{free_port()}", "timeout_s": 1}).get()

    def test_describe_redacts(self):
        d = make({"driver": "shelly_gen2", "host": "plug.example", "password": "hunter22"})
        self.assertNotIn("hunter22", d.describe())

    def test_digest_md5_rfc2617_example(self):
        # RFC 2617 section 3.5 example
        chal = ('Digest realm="testrealm@host.com", qop="auth,auth-int", '
                'nonce="dcd98b7102dd2f0e8b11d0f600bfb0c093", opaque="5ccc069c403ebaf9f0171e9517f40e41"')
        h = httputil.digest_header(chal, "GET", "http://www.nowhere.org/dir/index.html", "Mufasa", "Circle Of Life",
                                   cnonce="0a4f113b", nc=1)
        self.assertIn('response="6629fae49393a05397450978507c4ef1"', h)


if __name__ == "__main__":
    unittest.main()
