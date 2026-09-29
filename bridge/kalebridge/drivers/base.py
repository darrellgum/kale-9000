from __future__ import annotations

SECRET_FIELDS = ("password", "token", "pass", "secret")


class DriverError(Exception):
    """A plug could not be read or switched. The message must never contain a password/token."""


def base_url(host: str, default_port: int | None = None) -> str:
    host = str(host or "").strip().rstrip("/")
    if not host:
        raise DriverError("missing 'host'")
    if "://" not in host:
        host = "http://" + host
    return host


def redact(spec: dict) -> dict:
    return {k: ("***" if any(s in k.lower() for s in SECRET_FIELDS) and v else v) for k, v in (spec or {}).items()}


class Driver:
    name = "base"
    timeout = 5.0

    def __init__(self, spec: dict):
        self.spec = dict(spec)
        self.timeout = float(spec.get("timeout_s", self.timeout))

    def get(self) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def set(self, on: bool) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def describe(self) -> str:
        s = redact(self.spec)
        where = s.get("host") or s.get("url") or s.get("state_file") or ""
        ch = s.get("channel")
        ent = s.get("entity_id")
        return f"{self.name}" + (f" {where}" if where else "") + (f" ch{ch}" if ch is not None else "") + (f" {ent}" if ent else "")

    def _wrap(self, fn, what: str):
        """Run fn(); convert any error into a DriverError without leaking secrets."""
        from ..httputil import HTTPStatusError
        try:
            return fn()
        except DriverError:
            raise
        except HTTPStatusError as e:
            raise DriverError(f"{self.name} {what}: HTTP {e.code}" + (" (check user/password)" if e.code == 401 else "")) from None
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            for f in SECRET_FIELDS:
                v = self.spec.get(f)
                if v:
                    msg = msg.replace(str(v), "***")
            raise DriverError(f"{self.name} {what}: {type(e).__name__}: {msg}"[:300]) from None
