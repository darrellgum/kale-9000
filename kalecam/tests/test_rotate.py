#!/usr/bin/env python3
"""Self-test for rotate.py using generated dummy images.

Run:  python3 test_rotate.py      (downscale checks run only if Pillow is installed)
"""
import datetime as dt
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "rotate.py"
NOW = "2026-09-28T09:00:00"
try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False


def make_image(path: Path, size=(3000, 2000), color=(40, 140, 60)):
    path.parent.mkdir(parents=True, exist_ok=True)
    if HAVE_PIL:
        Image.new("RGB", size, color).save(path, "JPEG", quality=90)
    else:  # minimal fake JPEG bytes; fine for non-downscale logic
        path.write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 2048 + b"\xff\xd9")


def run(*args):
    p = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    if p.returncode != 0:
        raise AssertionError(f"rotate.py {' '.join(args)} failed:\n{p.stdout}\n{p.stderr}")
    return p.stdout


class RotateTest(unittest.TestCase):
    """Photos are named HHMMSS-<camera>.jpg, like the capture server writes them."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "grow-photos"
        self.inbox = Path(self.tmp.name) / "inbox"
        now = dt.datetime.fromisoformat(NOW)
        # 45 days x 4 photos/day for tomato-01, via the `add` subcommand
        for age in range(45):
            day = (now - dt.timedelta(days=age)).date()
            for hh, mm in ((6, 0), (10, 0), (12, 30), (18, 0)):
                t = dt.datetime.combine(day, dt.time(hh, mm))
                if t > now:
                    continue
                src = self.inbox / f"{day}-{hh}{mm}.jpg"
                make_image(src)
                run("add", "--root", str(self.root), "--plant", "tomato-01", "--file", str(src),
                    "--source", "camera-1", "--ts", t.isoformat(),
                    "--sensors", json.dumps({"t_c": 24.1, "rh": 62}))
        # a second plant with a sidecar-only milestone and multi-camera names
        d = self.root / "basil-01" / "2026" / "08" / "01"
        for name in ("070000-cam-a.jpg", "121500-cam-a.jpg", "121500-cam-b.jpg"):
            make_image(d / name)
        (d / "070000-cam-a.json").write_text(json.dumps({"milestone": "first_true_leaves"}))
        (d / "notes.txt").write_text("not a photo")

    def tearDown(self):
        self.tmp.cleanup()

    def plant_files(self, plant):
        return sorted(p.relative_to(self.root / plant).as_posix()
                      for p in (self.root / plant).glob("*/*/*/*.jpg"))

    def test_policy(self):
        tdir = self.root / "tomato-01"
        before = self.plant_files("tomato-01")
        self.assertEqual(len(before), 45 * 4 - 3)  # today: only 06:00 is <= 09:00

        # flag a non-midday photo on an old day as milestone; mark one midday as unusable
        run("flag", "--root", str(self.root), "--plant", "tomato-01",
            "--file", "2026/08/20/060000.jpg", "--milestone", "first_flower")  # bare HHMMSS.jpg resolves to -camera-1
        run("flag", "--root", str(self.root), "--plant", "tomato-01",
            "--file", "2026/09/10/123000-camera-1.jpg", "--quality", "unusable")
        # the flag above also sets keep=True; undo keep for the quality-only test
        rows = [json.loads(l) for l in (tdir / "index.jsonl").read_text().splitlines()]
        for r in rows:
            if r["file"] == "2026/09/10/123000-camera-1.jpg":
                r["keep"] = False
                r["milestone"] = None
        (tdir / "index.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

        # dry run changes nothing
        out = run("rotate", "--root", str(self.root), "--now", NOW, "--json")
        plan = {p["plant"]: p for p in json.loads(out)["plants"]}
        self.assertEqual(self.plant_files("tomato-01"), before)
        self.assertEqual(plan["tomato-01"]["kept_recent"], 7 * 4 - 3)

        run("rotate", "--root", str(self.root), "--now", NOW, "--apply")
        after = self.plant_files("tomato-01")
        now = dt.datetime.fromisoformat(NOW)
        for age in range(45):
            day = (now - dt.timedelta(days=age)).date()
            files = [f for f in after if f.startswith(day.strftime("%Y/%m/%d"))]
            if age < 7:
                self.assertEqual(len(files), 4 if age else 1, (day, files))
            elif day == dt.date(2026, 8, 20):
                self.assertEqual(sorted(files), ["2026/08/20/060000-camera-1.jpg", "2026/08/20/123000-camera-1.jpg"])
            elif day == dt.date(2026, 9, 10):
                self.assertEqual(files, ["2026/09/10/100000-camera-1.jpg"])  # unusable midday skipped
            else:
                self.assertEqual(files, [day.strftime("%Y/%m/%d") + "/123000-camera-1.jpg"], day)

        # index updated: pruned entries marked, milestone kept
        rows = {r["file"]: r for r in map(json.loads, (tdir / "index.jsonl").read_text().splitlines())}
        self.assertEqual(rows["2026/09/01/180000-camera-1.jpg"]["status"], "pruned")
        self.assertEqual(rows["2026/08/20/060000-camera-1.jpg"]["milestone"], "first_flower")

        # basil: milestone (sidecar) kept, one best of the two 12:15 frames kept, sidecar survives
        self.assertEqual(self.plant_files("basil-01"),
                         ["2026/08/01/070000-cam-a.jpg", "2026/08/01/121500-cam-a.jpg"])
        self.assertTrue((self.root / "basil-01/2026/08/01/notes.txt").exists())

        if HAVE_PIL:
            with Image.open(tdir / "2026/08/15/123000-camera-1.jpg") as im:   # age 44 -> downscaled
                self.assertEqual(max(im.size), 1600)
            with Image.open(tdir / "2026/08/20/060000-camera-1.jpg") as im:   # milestone -> untouched
                self.assertEqual(im.size, (3000, 2000))
            with Image.open(tdir / "2026/09/10/100000-camera-1.jpg") as im:   # age 18 -> full size
                self.assertEqual(im.size, (3000, 2000))

        # idempotent: second run deletes nothing
        out = run("rotate", "--root", str(self.root), "--now", NOW, "--apply", "--json")
        for p in json.loads(out)["plants"]:
            self.assertEqual(p["delete"], [])
            self.assertEqual(p["downscale"], [])
        log = (self.root / "rotation-log.jsonl").read_text().splitlines()
        self.assertEqual(len(log), 2)

    def test_trash_dir(self):
        trash = Path(self.tmp.name) / "trash"
        run("rotate", "--root", str(self.root), "--now", NOW, "--apply",
            "--trash-dir", str(trash), "--downscale-after-days", "0")
        self.assertTrue((trash / "tomato-01/2026/09/01/060000-camera-1.jpg").exists())


if __name__ == "__main__":
    print(f"Pillow available: {HAVE_PIL}")
    unittest.main(verbosity=2)
