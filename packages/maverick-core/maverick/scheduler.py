"""Cron-style scheduler helper for the job queue.

Computes the next run time for a 5-field cron expression
(``minute hour day-of-month month day-of-week``) without dragging in
a cron dependency. Supports ``*``, ``*/n`` steps, ``a-b`` ranges,
``a,b,c`` lists, and named months/weekdays.

Pairs with :mod:`maverick.job_queue`: ``schedule_cron`` enqueues a
job at the next matching time; a worker that re-schedules after each
run gives you a recurring task.

This is intentionally minimal — no seconds field, no ``@reboot``, no
timezone math beyond the caller's ``now`` (pass a UTC timestamp for
UTC scheduling). Good enough for "every weekday at 9am" without a
dep.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Optional

log = logging.getLogger(__name__)


_MONTHS = {
    m: i for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun",
         "jul", "aug", "sep", "oct", "nov", "dec"], start=1)
}
_DOW = {
    d: i for i, d in enumerate(
        ["sun", "mon", "tue", "wed", "thu", "fri", "sat"])
}


class CronError(ValueError):
    """Raised on a malformed cron expression."""


def _parse_field(field: str, lo: int, hi: int, names: dict | None = None) -> set[int]:
    out: set[int] = set()
    for part in field.split(","):
        part = part.strip().lower()
        if not part:
            continue
        step = 1
        if "/" in part:
            base, _, step_s = part.partition("/")
            try:
                step = int(step_s)
            except ValueError as e:
                raise CronError(f"bad step in {field!r}") from e
            if step <= 0:
                raise CronError(f"step must be > 0 in {field!r}")
            part = base or "*"
        if part == "*":
            rng = range(lo, hi + 1)
        elif "-" in part:
            a_s, _, b_s = part.partition("-")
            a = _resolve(a_s, names)
            b = _resolve(b_s, names)
            if a > b:
                raise CronError(f"range {part!r} reversed")
            rng = range(a, b + 1)
        else:
            v = _resolve(part, names)
            rng = range(v, v + 1)
        for i, val in enumerate(rng):
            if i % step == 0:
                if not (lo <= val <= hi):
                    raise CronError(f"value {val} out of [{lo},{hi}] in {field!r}")
                out.add(val)
    if not out:
        raise CronError(f"empty field {field!r}")
    return out


def _resolve(token: str, names: dict | None) -> int:
    token = token.strip().lower()
    if names and token in names:
        return names[token]
    try:
        return int(token)
    except ValueError as e:
        raise CronError(f"bad token {token!r}") from e


def parse_cron(expr: str) -> tuple[set[int], set[int], set[int], set[int], set[int]]:
    fields = expr.split()
    if len(fields) != 5:
        raise CronError(
            f"cron needs 5 fields (min hour dom mon dow), got {len(fields)}"
        )
    minute = _parse_field(fields[0], 0, 59)
    hour = _parse_field(fields[1], 0, 23)
    dom = _parse_field(fields[2], 1, 31)
    mon = _parse_field(fields[3], 1, 12, _MONTHS)
    dow = _parse_field(fields[4], 0, 6, _DOW)
    # Normalize Sunday=7 to 0 if a user wrote 7.
    if 7 in dow:
        dow.discard(7)
        dow.add(0)
    return minute, hour, dom, mon, dow


def next_run(expr: str, *, after: Optional[float] = None) -> float:
    """Return the next epoch timestamp matching ``expr`` strictly after
    ``after`` (default: now). Searches up to ~4 years forward.

    Day-of-month and day-of-week follow Vixie cron semantics: if BOTH
    are restricted (not ``*``), a match on EITHER fires.
    """
    minute, hour, dom, mon, dow = parse_cron(expr)
    base = _dt.datetime.fromtimestamp(
        after if after is not None else _dt.datetime.now().timestamp()
    )
    # Round up to the next whole minute.
    t = base.replace(second=0, microsecond=0) + _dt.timedelta(minutes=1)

    dom_restricted = dom != set(range(1, 32))
    dow_restricted = dow != set(range(0, 7))

    # 4 years of minutes is the hard cap (handles Feb-29-only schedules).
    for _ in range(366 * 4 * 24 * 60):
        if (
            t.minute in minute
            and t.hour in hour
            and t.month in mon
        ):
            # cron weekday: Mon=0..Sun=6 in python; we use Sun=0..Sat=6.
            py_dow = (t.weekday() + 1) % 7  # Mon(0)->1 ... Sun(6)->0
            dom_ok = t.day in dom
            dow_ok = py_dow in dow
            if dom_restricted and dow_restricted:
                match = dom_ok or dow_ok
            elif dom_restricted:
                match = dom_ok
            elif dow_restricted:
                match = dow_ok
            else:
                match = True
            if match:
                return t.timestamp()
        t += _dt.timedelta(minutes=1)
    raise CronError(f"no match for {expr!r} within 4 years")


def schedule_cron(queue, expr: str, kind: str, payload: dict | None = None,
                  *, after: Optional[float] = None) -> tuple[int, float]:
    """Enqueue ``kind`` at the next time matching ``expr``.

    Returns ``(job_id, run_at)``. Pair with a worker that calls
    ``schedule_cron`` again after each run to make it recurring.
    """
    run_at = next_run(expr, after=after)
    job_id = queue.enqueue(kind, payload or {}, run_at=run_at)
    return job_id, run_at


__all__ = ["parse_cron", "next_run", "schedule_cron", "CronError"]
