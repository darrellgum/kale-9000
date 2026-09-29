#!/usr/bin/env python3
"""KALE 9000 photo intake and rotation tool.

Layout (see docs/DESIGN.md):
    <root>/<plant-id>/YYYY/MM/DD/HHMMSS-<camera>.jpg     photo (bot-local time), e.g. 143000-phone-1.jpg
    <root>/<plant-id>/YYYY/MM/DD/HHMMSS-<camera>.json    optional sidecar metadata
    <root>/<plant-id>/index.jsonl                        per-plant photo index
    <root>/rotation-log.jsonl                            log of rotation runs

Subcommands:
    rotate  (default) Apply the retention policy. Dry-run unless --apply.
    add     Store an incoming image in the layout and append it to the index.
    flag    Mark a stored photo as a milestone / keep-forever.

Retention policy:
  * Photos from the last N days (--keep-full-days, default 7, counting today)
    are all kept at full size.
  * Older days are thinned to ONE photo per day: the "best" photo, chosen by
    best flag > quality (good > usable > unknown > unusable) > closest to
    the target time (--target-time, default 12:00).
  * Kept daily photos older than --downscale-after-days (default 30; 0 = never)
    are downscaled to --max-edge pixels (needs Pillow; skipped if it is missing).
  * Milestone / keep photos are never deleted or downscaled.

Python 3.8+, stdlib only. Pillow is optional (downscaling only).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image, ImageOps  # type: ignore
    HAVE_PIL = True
except Exception:  # pragma: no cover
    HAVE_PIL = False

PHOTO_RE = re.compile(r"^(\d{6})(?:-([A-Za-z0-9_.]+(?:-[A-Za-z0-9_.]+)*))?\.(jpe?g|png|webp)$", re.I)
PLANT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
QUALITY_RANK = {"good": 0, "usable": 1, None: 2, "unknown": 2, "unusable": 3}
INDEX_NAME = "index.jsonl"
LOG_NAME = "rotation-log.jsonl"
LOCK_NAME = ".rotate.lock"


# ----------------------------------------------------------------- helpers
def _local_tz():
    """Bot-local zone: $TZ, /etc/timezone, /etc/localtime (same order as the capture server)."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:  # Python < 3.9
        return None
    names = [os.environ.get("TZ", "").lstrip(":")]
    try:
        names.append(Path("/etc/timezone").read_text().strip())
    except OSError:
        pass
    try:
        link = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in link:
            names.append(link.split("zoneinfo/", 1)[1])
    except OSError:
        pass
    for n in names:
        if n:
            try:
                return ZoneInfo(n)
            except Exception:
                continue
    return None


_TZ = _local_tz()


def now_local() -> dt.datetime:
    return dt.datetime.now(_TZ) if _TZ else dt.datetime.now().astimezone()


def to_local(t: dt.datetime) -> dt.datetime:
    return t.astimezone(_TZ) if _TZ else t.astimezone()


def iso(t: dt.datetime) -> str:
    return t.isoformat(timespec="seconds")


def _match_mode(tmp: str, target: Path) -> None:
    """mkstemp creates 0600 files; give the replacement the target's mode (or umask default)."""
    try:
        mode = target.stat().st_mode & 0o777
    except FileNotFoundError:
        um = os.umask(0)
        os.umask(um)
        mode = 0o666 & ~um
    os.chmod(tmp, mode)


def read_jsonl(path: Path) -> list[dict]:
    out = []
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    print(f"warning: {path}:{n} is not valid JSON, kept as-is", file=sys.stderr)
                    out.append({"_raw": line})
    return out


def write_jsonl_atomic(path: Path, rows: list[dict]) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".jsonl")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(r["_raw"] if "_raw" in r else json.dumps(r, ensure_ascii=False))
            f.write("\n")
    _match_mode(tmp, path)
    os.replace(tmp, path)


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_sidecar(photo: Path) -> dict:
    sc = photo.with_suffix(".json")
    if sc.exists():
        try:
            return json.loads(sc.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            print(f"warning: unreadable sidecar {sc}", file=sys.stderr)
    return {}


def write_sidecar(photo: Path, data: dict) -> None:
    sc = photo.with_suffix(".json")
    fd, tmp = tempfile.mkstemp(dir=sc.parent, prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _match_mode(tmp, sc)
    os.replace(tmp, sc)


class Lock:
    """Simple exclusive lock file so two rotations never run at once."""

    def __init__(self, root: Path, stale_after_s: int = 3600):
        self.path = root / LOCK_NAME
        self.stale = stale_after_s

    def __enter__(self):
        try:
            if self.path.exists() and (dt.datetime.now().timestamp() - self.path.stat().st_mtime) > self.stale:
                self.path.unlink()
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
        except FileExistsError:
            sys.exit(f"error: another rotation appears to be running ({self.path}); aborting")
        return self

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


# ----------------------------------------------------------------- scanning
class Photo:
    def __init__(self, plant_dir: Path, path: Path, taken: dt.datetime, camera: str | None):
        self.plant_dir = plant_dir
        self.path = path
        self.rel = path.relative_to(plant_dir).as_posix()
        self.taken = taken  # naive, bot-local
        self.camera = camera
        self.meta: dict = {}

    @property
    def is_keep(self) -> bool:
        return bool(self.meta.get("milestone")) or bool(self.meta.get("keep"))

    @property
    def quality(self):
        q = self.meta.get("quality")
        return q.lower() if isinstance(q, str) else None


def scan_plant(plant_dir: Path, index_rows: list[dict]) -> list[Photo]:
    by_file = {r.get("file"): r for r in index_rows if "file" in r}
    photos = []
    for p in sorted(plant_dir.glob("[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/*")):
        m = PHOTO_RE.match(p.name)
        if not m or not p.is_file():
            continue
        y, mo, d = p.parts[-4:-1]
        try:
            taken = dt.datetime.strptime(f"{y}{mo}{d}{m.group(1)}", "%Y%m%d%H%M%S")
        except ValueError:
            print(f"warning: skipping unparseable path {p}", file=sys.stderr)
            continue
        ph = Photo(plant_dir, p, taken, m.group(2))
        meta = dict(by_file.get(ph.rel, {}))
        meta.update({k: v for k, v in read_sidecar(p).items() if v is not None})
        ph.meta = meta
        photos.append(ph)
    return photos


def pick_best(day_photos: list[Photo], target: dt.time) -> Photo:
    def key(ph: Photo):
        tgt = dt.datetime.combine(ph.taken.date(), target)
        return (
            0 if ph.meta.get("best") else 1,
            QUALITY_RANK.get(ph.quality, 2),
            abs((ph.taken - tgt).total_seconds()),
            ph.taken,
        )
    return sorted(day_photos, key=key)[0]


# ----------------------------------------------------------------- actions
def downscale(path: Path, max_edge: int, quality: int) -> tuple[bool, str]:
    if not HAVE_PIL:
        return False, "Pillow not installed"
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)  # bake in orientation; EXIF (incl. GPS) is dropped on save
        w, h = im.size
        if max(w, h) <= max_edge:
            return False, f"already {w}x{h}"
        im.thumbnail((max_edge, max_edge), Image.LANCZOS)
        fmt = "JPEG" if path.suffix.lower() in (".jpg", ".jpeg") else None
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
        os.close(fd)
        if fmt == "JPEG":
            im.convert("RGB").save(tmp, "JPEG", quality=quality, optimize=True)
        else:
            im.save(tmp)
        _match_mode(tmp, path)
        os.replace(tmp, path)
        return True, f"{w}x{h} -> {im.size[0]}x{im.size[1]}"


def remove_photo(ph: Photo, trash_dir: Path | None) -> None:
    files = [ph.path, ph.path.with_suffix(".json")]
    for f in files:
        if not f.exists():
            continue
        if trash_dir:
            dest = trash_dir / ph.plant_dir.name / f.relative_to(ph.plant_dir)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(dest))
        else:
            f.unlink()
    # prune empty DD/MM/YYYY dirs
    d = ph.path.parent
    for _ in range(3):
        try:
            d.rmdir()
        except OSError:
            break
        d = d.parent


def rotate_plant(plant_dir: Path, args, now: dt.datetime) -> dict:
    index_path = plant_dir / INDEX_NAME
    rows = read_jsonl(index_path)
    photos = scan_plant(plant_dir, rows)
    today = now.date()
    target = dt.datetime.strptime(args.target_time, "%H:%M").time()

    by_day: dict[dt.date, list[Photo]] = {}
    for ph in photos:
        by_day.setdefault(ph.taken.date(), []).append(ph)

    plan = {"plant": plant_dir.name, "kept_recent": 0, "kept_daily": [], "kept_milestone": [],
            "delete": [], "downscale": [], "downscale_skipped": []}
    to_delete: list[Photo] = []
    to_downscale: list[Photo] = []

    for day, items in sorted(by_day.items()):
        age = (today - day).days
        if age < args.keep_full_days:
            plan["kept_recent"] += len(items)
            continue
        best = pick_best(items, target)
        for ph in items:
            if ph.is_keep:
                plan["kept_milestone"].append(ph.rel)
            elif ph is best:
                plan["kept_daily"].append(ph.rel)
            else:
                to_delete.append(ph)
        if (args.downscale_after_days and age >= args.downscale_after_days
                and not best.is_keep and not best.meta.get("downscaled")):
            to_downscale.append(best)

    plan["delete"] = [p.rel for p in to_delete]
    plan["downscale"] = [p.rel for p in to_downscale]
    plan["bytes_freed_est"] = sum(p.path.stat().st_size for p in to_delete)

    if not args.apply:
        return plan

    stamp = iso(now)
    status: dict[str, dict] = {}
    for ph in to_delete:
        remove_photo(ph, args.trash_dir)
        status[ph.rel] = {"status": "trashed" if args.trash_dir else "pruned", "pruned_at": stamp}
    for ph in to_downscale:
        try:
            done, msg = downscale(ph.path, args.max_edge, args.jpeg_quality)
        except Exception as e:  # corrupt image etc.: keep original, report
            done, msg = False, f"error: {e}"
        if done:
            sc = read_sidecar(ph.path)
            if sc:
                sc.update({"downscaled": True, "downscaled_at": stamp})
                write_sidecar(ph.path, sc)
            status[ph.rel] = {"downscaled": True, "downscaled_at": stamp}
        else:
            plan["downscale_skipped"].append(f"{ph.rel} ({msg})")
            if msg.startswith("already"):
                status[ph.rel] = {"downscaled": True, "downscaled_at": stamp}
    plan["downscale"] = [r for r in plan["downscale"] if r in status]

    if status:
        seen = set()
        for r in rows:
            if r.get("file") in status:
                r.update(status[r["file"]])
                seen.add(r["file"])
        for rel in sorted(set(status) - seen):  # photo had no index entry yet: record it
            rows.append({"file": rel, "plant": plant_dir.name, **status[rel]})
        write_jsonl_atomic(index_path, rows)
    return plan


# ----------------------------------------------------------------- commands
def cmd_rotate(args) -> int:
    root: Path = args.root
    if not root.is_dir():
        print(f"error: root {root} does not exist", file=sys.stderr)
        return 2
    now = dt.datetime.fromisoformat(args.now) if args.now else now_local()
    if now.tzinfo is not None:
        now = to_local(now)  # compare in bot-local time, like the folder names
    plants = [root / args.plant] if args.plant else sorted(
        p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".") and PLANT_RE.match(p.name))
    if args.downscale_after_days and not HAVE_PIL:
        print("note: Pillow not installed; downscaling will be skipped", file=sys.stderr)

    with Lock(root):
        results = [rotate_plant(p, args, now) for p in plants if p.is_dir()]
    summary = {"ts": iso(now_local()), "mode": "apply" if args.apply else "dry-run",
               "policy": {"keep_full_days": args.keep_full_days, "target_time": args.target_time,
                          "downscale_after_days": args.downscale_after_days, "max_edge": args.max_edge},
               "plants": results}
    if args.apply:
        append_jsonl(root / LOG_NAME, {**summary, "plants": [
            {k: (len(v) if isinstance(v, list) else v) for k, v in r.items()} for r in results]})
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"[{summary['mode']}] rotation at {summary['ts']}")
        for r in results:
            print(f"  {r['plant']}: recent kept {r['kept_recent']}, daily kept {len(r['kept_daily'])}, "
                  f"milestones kept {len(r['kept_milestone'])}, delete {len(r['delete'])} "
                  f"(~{r['bytes_freed_est'] / 1e6:.1f} MB), downscale {len(r['downscale'])}")
            for s in r["downscale_skipped"]:
                print(f"    downscale skipped: {s}")
        if not args.apply:
            print("  (dry run: nothing changed; re-run with --apply)")
    return 0


def cmd_add(args) -> int:
    if not PLANT_RE.match(args.plant):
        print("error: plant id must be lowercase letters, digits, '-' or '_'", file=sys.stderr)
        return 2
    src: Path = args.file
    ext = src.suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        print(f"error: unsupported file type {ext}", file=sys.stderr)
        return 2
    taken = dt.datetime.fromisoformat(args.ts) if args.ts else now_local()
    if taken.tzinfo is not None:
        taken = to_local(taken)
    cam = re.sub(r"[^A-Za-z0-9_.-]", "_", args.source) if args.source else None
    plant_dir = args.root / args.plant
    day_dir = plant_dir / taken.strftime("%Y/%m/%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    base = taken.strftime("%H%M%S") + (f"-{cam}" if cam and not args.no_camera_suffix else "")
    dest = day_dir / f"{base}{'.jpg' if ext == '.jpeg' else ext}"
    suffix = dest.suffix
    n = 1
    while dest.exists():  # same second (and camera): HHMMSS[-cam]-N.jpg
        dest = day_dir / f"{base}-{n}{suffix}"
        n += 1
    shutil.copy2(src, dest) if args.copy else shutil.move(str(src), str(dest))
    rel = dest.relative_to(plant_dir).as_posix()
    entry = {"file": rel, "ts": iso(taken if taken.tzinfo else (taken.replace(tzinfo=_TZ) if _TZ else taken.astimezone())),
             "plant": args.plant, "source": args.source, "bytes": dest.stat().st_size,
             "status": "active", "milestone": args.milestone, "keep": bool(args.milestone),
             "quality": None, "best": False}
    if args.sensors:
        entry["sensors"] = json.loads(args.sensors)
    append_jsonl(plant_dir / INDEX_NAME, entry)
    if args.sidecar:
        write_sidecar(dest, entry)
    print(dest)
    return 0


def resolve_photo(plant_dir: Path, rel: str) -> str:
    """Accept '.../HHMMSS.jpg' for '.../HHMMSS-<camera>.jpg' when it is unambiguous."""
    if (plant_dir / rel).exists():
        return rel
    p = Path(rel)
    m = re.match(r"^(\d{6})$", p.stem)
    if m:
        hits = sorted(q for q in (plant_dir / p.parent).glob(f"{m.group(1)}-*{p.suffix or '.jpg'}")
                      if PHOTO_RE.match(q.name))
        if len(hits) == 1:
            return (p.parent / hits[0].name).as_posix()
    return rel


def cmd_flag(args) -> int:
    plant_dir = args.root / args.plant
    args.file = resolve_photo(plant_dir, args.file)
    index_path = plant_dir / INDEX_NAME
    rows = read_jsonl(index_path)
    hit = False
    for r in rows:
        if r.get("file") == args.file:
            r.update({"milestone": args.milestone or r.get("milestone"), "keep": True})
            if args.best:
                r["best"] = True
            if args.quality:
                r["quality"] = args.quality
            hit = True
    photo = plant_dir / args.file
    if not photo.exists():
        print(f"error: {photo} not found", file=sys.stderr)
        return 2
    if not hit:
        rows.append({"file": args.file, "plant": args.plant, "status": "active",
                     "milestone": args.milestone, "keep": True, "best": bool(args.best),
                     "quality": args.quality})
    write_jsonl_atomic(index_path, rows)
    sc = read_sidecar(photo)
    if sc:
        sc.update({"milestone": args.milestone or sc.get("milestone"), "keep": True})
        write_sidecar(photo, sc)
    print(f"flagged {args.plant}/{args.file} as keep-forever"
          + (f" (milestone: {args.milestone})" if args.milestone else ""))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="KALE 9000 photo intake + rotation")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path,
                        default=Path(os.environ.get("KALE_PHOTO_ROOT", "/workspace/grow-photos")),
                        help="photo root (default: $KALE_PHOTO_ROOT or /workspace/grow-photos)")
    sub = ap.add_subparsers(dest="cmd")

    r = sub.add_parser("rotate", parents=[common], help="apply retention policy (dry-run unless --apply)")
    r.add_argument("--plant", help="only this plant id")
    r.add_argument("--keep-full-days", type=int, default=7)
    r.add_argument("--target-time", default="12:00", help="HH:MM preferred daily photo time (bot-local)")
    r.add_argument("--downscale-after-days", type=int, default=30, help="0 disables downscaling")
    r.add_argument("--max-edge", type=int, default=1600)
    r.add_argument("--jpeg-quality", type=int, default=85)
    r.add_argument("--trash-dir", type=Path, help="move pruned files here instead of deleting")
    r.add_argument("--now", help="override current time (ISO 8601), for testing")
    r.add_argument("--apply", action="store_true", help="actually change files")
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=cmd_rotate)

    a = sub.add_parser("add", parents=[common], help="store an incoming image and index it")
    a.add_argument("--plant", required=True)
    a.add_argument("--file", type=Path, required=True)
    a.add_argument("--source", help="source device label, e.g. <camera>")
    a.add_argument("--ts", help="capture time ISO 8601 (default: now)")
    a.add_argument("--milestone", help="milestone name -> keep forever")
    a.add_argument("--sensors", help="JSON sensor snapshot")
    a.add_argument("--camera-suffix", action="store_true", help=argparse.SUPPRESS)  # default now; kept for old scripts
    a.add_argument("--no-camera-suffix", action="store_true", help="name the file HHMMSS.jpg (default: HHMMSS-<source>.jpg)")
    a.add_argument("--sidecar", action="store_true", help="also write a HHMMSS-<source>.json sidecar")
    a.add_argument("--copy", action="store_true", help="copy instead of move")
    a.set_defaults(func=cmd_add)

    f = sub.add_parser("flag", parents=[common], help="mark a stored photo keep-forever / milestone")
    f.add_argument("--plant", required=True)
    f.add_argument("--file", required=True, help="path relative to the plant dir, e.g. 2026/05/05/080000-phone-1.jpg "
                   "(a bare HHMMSS.jpg is accepted if exactly one photo from that second exists)")
    f.add_argument("--milestone")
    f.add_argument("--best", action="store_true")
    f.add_argument("--quality", choices=["good", "usable", "unusable"])
    f.set_defaults(func=cmd_flag)
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("rotate", "add", "flag", "-h", "--help"):
        argv = ["rotate"] + argv  # default subcommand
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
