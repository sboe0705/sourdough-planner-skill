#!/usr/bin/env python3
"""Sourdough baking scheduler: turn a recipe into a timed plan.

Works backwards from the moment the bread should be finished: each step's
start is the next step's start minus its own duration (a port of
Schedoughler's computeSchedule). With no target time, it searches for a
finish time, and for durations of flexible steps inside their own min/max
range, so that no hands-on moment lands in a busy window (work, sleep).

Standard library only. Run with --help for usage.

Recipe JSON (see references/recipe-format.md):
  {"name": "...", "steps": [{"title": "...", "dur": 60, "kind": "prep|rise|cold|bake",
    "desc": "...", "min": 45, "max": 90, "step": 15, "attended": true,
    "ingredients": [{"amount": 500, "unit": "g", "name": "flour", "note": "..."}]}]}

Times are naive local wall-clock times, written as ISO 8601 (2026-11-14T18:00).
"""

from __future__ import annotations

import argparse
import bisect
import itertools
import json
import re
import sys
from datetime import datetime, timedelta, timezone

KINDS = ("prep", "rise", "cold", "bake")
ATTENDED_KINDS = ("prep", "bake")  # the baker must be present for the whole step
DEFAULT_BUSY = ("Mon-Fri 08:00-16:00", "daily 22:00-05:00")
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
START_BUFFER_MIN = 20  # time to walk into the kitchen and start (as in Schedoughler)
SLOT_MIN = 15  # grid for candidate finish times
MAX_COMBOS = 600  # cap on combinations of flexible durations tried per finish time


class RecipeError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Recipe handling
# ---------------------------------------------------------------------------

def is_flexible(step: dict) -> bool:
    return step.get("min") is not None


def effective_duration(step: dict, override=None) -> int:
    """Clamp an override for a flexible step into its [min, max] range."""
    if not is_flexible(step):
        return step["dur"]
    base = override if override is not None else step["dur"]
    return min(step["max"], max(step["min"], base))


def is_attended(step: dict) -> bool:
    if "attended" in step:
        return bool(step["attended"])
    return step["kind"] in ATTENDED_KINDS


def validate_recipe(recipe: dict) -> list[str]:
    """Raise RecipeError for broken recipes; return warnings for dubious ones."""
    if not isinstance(recipe, dict):
        raise RecipeError("recipe must be a JSON object")
    steps = recipe.get("steps")
    if not isinstance(steps, list) or not steps:
        raise RecipeError("recipe needs a non-empty 'steps' array")
    warnings = []
    for i, s in enumerate(steps):
        where = f"step {i} ({s.get('title', '?')!r})"
        if not isinstance(s, dict):
            raise RecipeError(f"step {i} must be an object")
        if not s.get("title"):
            raise RecipeError(f"{where}: missing 'title'")
        if not isinstance(s.get("dur"), (int, float)) or s["dur"] <= 0:
            raise RecipeError(f"{where}: 'dur' must be a positive number of minutes")
        s["dur"] = int(round(s["dur"]))
        if s.get("kind") not in KINDS:
            raise RecipeError(f"{where}: 'kind' must be one of {', '.join(KINDS)}")
        if s.get("preheat") is not None:
            if not isinstance(s["preheat"], (int, float)) or s["preheat"] < 0:
                raise RecipeError(f"{where}: 'preheat' must be minutes >= 0")
            s["preheat"] = int(round(s["preheat"]))
        flex = [k for k in ("min", "max", "step") if s.get(k) is not None]
        if flex and len(flex) != 3:
            raise RecipeError(f"{where}: give all of min, max and step, or none")
        if flex:
            for k in ("min", "max", "step"):
                s[k] = int(round(s[k]))
            if not (0 < s["min"] <= s["dur"] <= s["max"]):
                raise RecipeError(f"{where}: needs 0 < min <= dur <= max")
            if s["step"] <= 0:
                raise RecipeError(f"{where}: 'step' must be positive")
            if s["kind"] == "bake":
                warnings.append(f"{where}: bake steps should have a fixed duration; "
                                "its min/max range is ignored")
                for k in ("min", "max", "step"):
                    s.pop(k)
    return warnings


def compute_schedule(recipe: dict, finish: datetime, overrides: dict | None = None) -> list[dict]:
    """Start/end for every step, walking backwards from `finish`."""
    overrides = overrides or {}
    steps = [dict(s, index=i, dur=effective_duration(s, overrides.get(i)))
             for i, s in enumerate(recipe["steps"])]
    cursor = finish
    for s in reversed(steps):
        s["end"] = cursor
        cursor = cursor - timedelta(minutes=s["dur"])
        s["start"] = cursor
    return steps


# ---------------------------------------------------------------------------
# Busy windows
# ---------------------------------------------------------------------------

_WINDOW_RE = re.compile(
    r"^\s*(?:(?P<days>[A-Za-z][A-Za-z,\- ]*?)\s+)?(?P<s>\d{1,2}:\d{2})\s*-\s*(?P<e>\d{1,2}:\d{2})\s*$")


def _parse_hhmm(text: str) -> int:
    h, m = (int(x) for x in text.split(":"))
    if not (0 <= h <= 24 and 0 <= m < 60) or (h == 24 and m):
        raise ValueError(f"invalid time {text!r}")
    return h * 60 + m


def _day_index(token: str) -> int:
    t = token.strip()[:3].lower()
    for i, name in enumerate(DAY_NAMES):
        if name.lower() == t:
            return i
    raise ValueError(f"unknown weekday {token!r}")


def _parse_days(spec: str | None) -> frozenset[int]:
    if not spec:
        return frozenset(range(7))
    spec = spec.strip().lower().replace(" ", "")
    aliases = {"daily": range(7), "everyday": range(7), "all": range(7),
               "weekdays": range(5), "workdays": range(5), "weekends": (5, 6), "weekend": (5, 6)}
    if spec in aliases:
        return frozenset(aliases[spec])
    days = set()
    for part in spec.split(","):
        if not part:
            continue
        if "-" in part:
            a, b = (_day_index(x) for x in part.split("-", 1))
            i = a
            while True:
                days.add(i)
                if i == b:
                    break
                i = (i + 1) % 7
        else:
            days.add(_day_index(part))
    return frozenset(days)


class BusyWindow:
    """A weekly recurring window such as 'Mon-Fri 08:00-16:00'.

    A window whose end is not after its start wraps past midnight and belongs
    to the day it starts on: 'Fri 22:00-06:00' runs Friday 22:00 to Saturday 06:00.
    """

    def __init__(self, text: str):
        m = _WINDOW_RE.match(text)
        if not m:
            raise ValueError(f"cannot parse busy window {text!r} "
                             "(expected e.g. 'Mon-Fri 08:00-16:00' or 'daily 22:00-05:00')")
        self.label = text.strip()
        self.days = _parse_days(m.group("days"))
        self.start = _parse_hhmm(m.group("s"))
        self.end = _parse_hhmm(m.group("e"))
        if self.start == self.end:
            raise ValueError(f"busy window {text!r} has zero length (use 00:00-24:00 for a whole day)")

    def intervals(self, first_day: datetime, last_day: datetime):
        day = first_day.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        while day <= last_day:
            if day.weekday() in self.days:
                a = day + timedelta(minutes=self.start)
                b = day + timedelta(minutes=self.end)
                if self.end <= self.start:
                    b += timedelta(days=1)
                yield a, b, self.label
            day += timedelta(days=1)


class BusyCalendar:
    """Concrete busy intervals over a time range, in integer minutes, for fast lookups."""

    def __init__(self, windows: list[BusyWindow], start: datetime, end: datetime):
        self.base = start.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=2)
        raw = sorted((self.m(a), self.m(b), label)
                     for w in windows for a, b, label in w.intervals(start, end))
        self.starts = [r[0] for r in raw]
        self.ends = [r[1] for r in raw]
        self.labels = [r[2] for r in raw]
        # running maximum of ends, so overlapping windows are handled correctly
        self.max_end = list(itertools.accumulate(self.ends, max))

    def m(self, t: datetime) -> int:
        return int((t - self.base).total_seconds() // 60)

    def at(self, m: int) -> str | None:
        """Label of a busy window containing minute m, or None."""
        i = bisect.bisect_right(self.starts, m) - 1
        if i < 0 or self.max_end[i] <= m:
            return None
        while i >= 0:
            if self.ends[i] > m:
                return self.labels[i]
            i -= 1
        return None

    def overlap(self, a: int, b: int) -> str | None:
        """Label of a busy window overlapping [a, b), or None."""
        hit = self.at(a)
        if hit:
            return hit
        i = bisect.bisect_right(self.starts, a)
        if i < len(self.starts) and self.starts[i] < b:
            return self.labels[i]
        return None


# ---------------------------------------------------------------------------
# Evaluation and search
# ---------------------------------------------------------------------------
#
# Which moments need the baker?
#   * every hands-on ("attended") step, for its whole duration — by default
#     prep and bake steps (you cannot leave the oven on while at work);
#   * the start of every other step, unless the step before it was attended
#     (then the baker is already there and simply walks away);
#   * the finish, when the bread comes out of the oven.
# With starts_only=True the rule is Schedoughler's check-critical-times.sh:
# only step starts count.

class Profile:
    """Per-recipe data the hot loop needs, precomputed once."""

    def __init__(self, recipe: dict, starts_only: bool = False):
        steps = recipe["steps"]
        self.n = len(steps)
        self.attended = [False if starts_only else is_attended(s) for s in steps]
        self.check_start = [starts_only or i == 0 or not self.attended[i - 1] or self.attended[i]
                            for i in range(self.n)]
        self.check_finish = not starts_only
        self.preheat = [0 if starts_only else (s.get("preheat") or 0) for s in steps]


def find_conflicts(profile: Profile, cal: BusyCalendar, finish_m: int, durs) -> dict:
    """Map step index (or 'finish') -> reason, for every hands-on moment in a busy window."""
    conflicts = {}
    end = finish_m
    for i in range(profile.n - 1, -1, -1):
        start = end - durs[i]
        if profile.attended[i]:
            hit = cal.overlap(start, end)
            if hit:
                conflicts[i] = f"hands-on step overlaps busy window '{hit}'"
        elif profile.check_start[i]:
            hit = cal.at(start)
            if hit:
                conflicts[i] = f"starts during busy window '{hit}'"
        if profile.preheat[i]:
            hit = cal.at(start - profile.preheat[i])
            if hit:
                conflicts[("preheat", i)] = f"switching the oven on during busy window '{hit}'"
        end = start
    if profile.check_finish and (profile.n - 1) not in conflicts:
        hit = cal.at(finish_m)
        if hit:
            conflicts["finish"] = f"finish (taking the bread out) during busy window '{hit}'"
    return conflicts


class Combo:
    __slots__ = ("overrides", "durs", "total", "dev")

    def __init__(self, recipe: dict, overrides: dict):
        self.overrides = {i: v for i, v in overrides.items() if v != recipe["steps"][i]["dur"]}
        self.durs = [effective_duration(s, overrides.get(i)) for i, s in enumerate(recipe["steps"])]
        self.total = sum(self.durs)
        self.dev = sum(abs(d - s["dur"]) for d, s in zip(self.durs, recipe["steps"]))


def flexible_combos(recipe: dict, keep_durations: bool = False, pinned: dict | None = None,
                    max_combos: int = MAX_COMBOS) -> list[Combo]:
    """Duration choices to try, ordered by total deviation from the default durations.

    Flexible steps vary only inside their own [min, max] on their own `step`
    grid (coarsened when there would be too many combinations); `pinned`
    fixes chosen steps to given durations.
    """
    pinned = pinned or {}
    flex = [(i, s) for i, s in enumerate(recipe["steps"])
            if is_flexible(s) and i not in pinned and not keep_durations]
    incs = {i: s["step"] for i, s in flex}

    def values(i, s):
        vals = set(range(s["min"], s["max"] + 1, incs[i]))
        vals.update((s["dur"], s["max"]))
        return sorted(vals)

    while True:
        options = {i: values(i, s) for i, s in flex}
        total = 1
        for v in options.values():
            total *= len(v)
        if total <= max_combos:
            break
        widest = max(options, key=lambda i: len(options[i]))  # coarsen the densest grid
        incs[widest] *= 2

    combos = [Combo(recipe, {**pinned, **{i: v for (i, _), v in zip(flex, vals)}})
              for vals in itertools.product(*(options[i] for i, _ in flex))]
    combos.sort(key=lambda c: (c.dev, c.durs))
    return combos


def best_for_finish(profile, cal, finish_m, combos, earliest_start_m=None, bound=None):
    """Best duration choice for a fixed finish: fewest conflicts, then least deviation.

    Returns ((conflicts, deviation), combo) or None. With `bound` (a key to
    beat), stops as soon as no remaining combo can beat it.
    """
    best = bound
    found = None
    for c in combos:
        if best is not None and best[0] == 0 and c.dev >= best[1]:
            break  # sorted by deviation: nothing later can beat a conflict-free option
        if earliest_start_m is not None and finish_m - c.total < earliest_start_m:
            continue
        n = len(find_conflicts(profile, cal, finish_m, c.durs))
        key = (n, c.dev)
        if best is None or key < best:
            best, found = key, c
    return (best, found) if found else None


def ceil_to_slot(t: datetime, slot: int = SLOT_MIN) -> datetime:
    if t.second or t.microsecond:
        t = t.replace(second=0, microsecond=0) + timedelta(minutes=1)
    rem = (t.hour * 60 + t.minute) % slot
    return t + timedelta(minutes=(slot - rem) % slot)


def search(profile, cal, combos, now, days, top=1):
    """Scan finish times on a grid; return [(finish, combo)], one option per finish day.

    Within a day the winner has the fewest conflicts, then the least deviation
    from the default durations, then the earliest finish. Days are ranked by
    conflicts, then chronologically.
    """
    earliest_start = now + timedelta(minutes=START_BUFFER_MIN)
    finish = ceil_to_slot(earliest_start + timedelta(minutes=min(c.total for c in combos)))
    last = now + timedelta(days=days)
    m = cal.m
    es = m(earliest_start)
    per_day = {}
    while finish <= last:
        day = finish.date()
        prev = per_day.get(day)
        res = best_for_finish(profile, cal, m(finish), combos, es, prev[0][:2] if prev else None)
        if res is not None:
            key = (res[0][0], res[0][1], finish)
            if prev is None or key < prev[0]:
                per_day[day] = (key, res[1])
        finish += timedelta(minutes=SLOT_MIN)
    # fewest conflicts first, then the soonest day; per day the least deviation already won
    ranked = sorted(per_day.values(), key=lambda r: (r[0][0], r[0][2]))[:top]
    return [(r[0][2], r[1]) for r in ranked]


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def duration_label(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    h, m = divmod(minutes, 60)
    return f"{h} h {m} min" if m else f"{h} h"


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M")


def is_overnight(step: dict) -> bool:
    """A step of 2 h or more that runs through part of 01:00-05:00 (from the actual times)."""
    if step["dur"] < 120:
        return False
    day = step["start"].replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= step["end"]:
        a, b = day + timedelta(hours=1), day + timedelta(hours=5)
        if step["start"] < b and a < step["end"]:
            return True
        day += timedelta(days=1)
    return False


def option_json(recipe, overrides, steps, conflicts):
    out_steps = []
    for s in steps:
        item = {
            "index": s["index"],
            "title": s["title"],
            "kind": s["kind"],
            "start": iso(s["start"]),
            "start_weekday": DAY_NAMES[s["start"].weekday()],
            "end": iso(s["end"]),
            "duration_minutes": s["dur"],
            "duration": duration_label(s["dur"]),
            "attended": is_attended(s),
            "overnight": is_overnight(s),
            "conflict": conflicts.get(s["index"]),
        }
        if s.get("preheat"):
            pre = s["start"] - timedelta(minutes=s["preheat"])
            item["preheat_at"] = iso(pre)
            item["preheat_weekday"] = DAY_NAMES[pre.weekday()]
            item["preheat_conflict"] = conflicts.get(("preheat", s["index"]))
        if is_flexible(s):
            item["range_minutes"] = [s["min"], s["max"]]
        if s.get("desc"):
            item["desc"] = s["desc"]
        if s.get("ingredients"):
            item["ingredients"] = s["ingredients"]
        out_steps.append(item)
    finish = steps[-1]["end"]
    return {
        "start": iso(steps[0]["start"]),
        "start_weekday": DAY_NAMES[steps[0]["start"].weekday()],
        "finish": iso(finish),
        "finish_weekday": DAY_NAMES[finish.weekday()],
        "total_minutes": sum(s["dur"] for s in steps),
        "total": duration_label(sum(s["dur"] for s in steps)),
        "conflict_count": len(conflicts),
        "finish_conflict": conflicts.get("finish"),
        "adjusted_steps": [
            {"index": i, "title": recipe["steps"][i]["title"],
             "default_minutes": recipe["steps"][i]["dur"], "planned_minutes": v}
            for i, v in sorted(overrides.items())
            if v != recipe["steps"][i]["dur"]
        ],
        "steps": out_steps,
    }


def fmt_when(iso_text: str, weekday: str) -> str:
    return f"{weekday} {iso_text[:10]} {iso_text[11:]}"


def to_markdown(result: dict) -> str:
    lines = [f"# {result['recipe']}", ""]
    if result["busy_windows"]:
        lines.append("Busy windows: " + "; ".join(result["busy_windows"]))
        lines.append("")
    for n, opt in enumerate(result["options"], 1):
        head = f"## Option {n}" if len(result["options"]) > 1 else "## Schedule"
        lines += [head, "",
                  f"**Start:** {fmt_when(opt['start'], opt['start_weekday'])} · "
                  f"**Finish:** {fmt_when(opt['finish'], opt['finish_weekday'])} · "
                  f"**Total:** {opt['total']}", ""]
        for a in opt["adjusted_steps"]:
            lines.append(f"- Adjusted *{a['title']}*: {duration_label(a['default_minutes'])} → "
                         f"{duration_label(a['planned_minutes'])}")
        if opt["adjusted_steps"]:
            lines.append("")
        lines += ["| When | Step | Duration | Notes |", "|---|---|---|---|"]
        for s in opt["steps"]:
            if s.get("preheat_at"):
                warn = "⚠ " + s["preheat_conflict"] if s["preheat_conflict"] else ""
                lines.append(f"| {fmt_when(s['preheat_at'], s['preheat_weekday'])} | "
                             f"Preheat the oven (for {s['title']}) | | {warn} |")
            notes = []
            if s["overnight"]:
                notes.append("overnight")
            if s["conflict"]:
                notes.append("⚠ " + s["conflict"])
            lines.append(f"| {fmt_when(s['start'], s['start_weekday'])} | {s['title']} | "
                         f"{s['duration']} | {'; '.join(notes)} |")
        lines.append(f"| {fmt_when(opt['finish'], opt['finish_weekday'])} | **Bread is done** | | "
                     f"{'⚠ ' + opt['finish_conflict'] if opt['finish_conflict'] else ''} |")
        lines.append("")
    for w in result.get("warnings", []):
        lines.append(f"> Warning: {w}")
    return "\n".join(lines).rstrip() + "\n"


def _ics_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _ics_fold(line: str) -> str:
    out, cur = [], b""
    for ch in line:
        enc = ch.encode("utf-8")
        if len(cur) + len(enc) > (75 if not out else 74):
            out.append(cur.decode("utf-8"))
            cur = b""
        cur += enc
    out.append(cur.decode("utf-8"))
    return "\r\n ".join(out)


def to_ics(result: dict, option_index: int = 0) -> str:
    opt = result["options"][option_index]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    uid_base = re.sub(r"[^A-Za-z0-9]+", "-", result["recipe"]).strip("-").lower() or "bake"
    ics_t = lambda s: s.replace("-", "").replace(":", "") + "00"  # floating local time
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//plan-sourdough-bake//EN", "CALSCALE:GREGORIAN"]
    for s in opt["steps"]:
        if s.get("preheat_at"):
            lines += [
                "BEGIN:VEVENT",
                f"UID:{uid_base}-{opt['start'].replace(':', '')}-{s['index']}-preheat@plan-sourdough-bake",
                f"DTSTAMP:{stamp}",
                f"DTSTART:{ics_t(s['preheat_at'])}",
                f"DTEND:{ics_t(s['start'])}",
                f"SUMMARY:{_ics_escape(result['recipe'] + ': preheat the oven')}",
                "BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:PT0M",
                "DESCRIPTION:Preheat the oven", "END:VALARM",
                "END:VEVENT",
            ]
        desc = s.get("desc", "")
        if s.get("ingredients"):
            parts = []
            for ing in s["ingredients"]:
                amount = " ".join(str(x) for x in (ing.get("amount"), ing.get("unit")) if x is not None)
                name = ing.get("name", "")
                note = f" ({ing['note']})" if ing.get("note") else ""
                parts.append(f"- {amount + ' ' if amount else '+ '}{name}{note}")
            desc = (desc + "\n\n" if desc else "") + "\n".join(parts)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid_base}-{opt['start'].replace(':', '')}-{s['index']}@plan-sourdough-bake",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{ics_t(s['start'])}",
            f"DTEND:{ics_t(s['end'])}",
            f"SUMMARY:{_ics_escape(result['recipe'] + ': ' + s['title'])}",
            f"DESCRIPTION:{_ics_escape(desc)}",
            # reminder when the step is due
            "BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:PT0M",
            f"DESCRIPTION:{_ics_escape(s['title'])}", "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_ics_fold(l) for l in lines) + "\r\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_dt(text: str) -> datetime:
    try:
        t = datetime.fromisoformat(text.strip().replace(" ", "T"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date/time {text!r} (use e.g. 2026-11-14T18:00)")
    return t.replace(tzinfo=None, second=0, microsecond=0)


def parse_overrides(text: str, recipe: dict) -> dict:
    """'{"1": 600}' or '1=600,3=90' (0-based step index -> minutes)."""
    text = text.strip()
    pairs = json.loads(text).items() if text.startswith("{") else (p.split("=", 1) for p in text.split(",") if p)
    out = {}
    for k, v in pairs:
        i = int(k)
        if not 0 <= i < len(recipe.get("steps") or []):
            raise RecipeError(f"override for unknown step index {i}")
        out[i] = int(v)
    return out


def build_parser():
    p = argparse.ArgumentParser(
        description="Turn a sourdough recipe (JSON) into a baking schedule.",
        epilog="Without --finish or --start, searches the next --days for the finish time "
               "whose hands-on moments avoid the busy windows.")
    p.add_argument("recipe", help="recipe JSON file, or - for stdin")
    when = p.add_mutually_exclusive_group()
    when.add_argument("--finish", type=parse_dt, help="target finish time, e.g. 2026-11-14T18:00")
    when.add_argument("--start", type=parse_dt, help="start time instead of a finish time")
    p.add_argument("--now", type=parse_dt, help="current local time (default: system clock)")
    p.add_argument("--days", type=float, default=7, help="search horizon in days (default 7)")
    p.add_argument("--top", type=int, default=1, help="number of alternative options, one per day (default 1)")
    p.add_argument("--busy", action="append", metavar="WINDOW",
                   help="busy window, repeatable; replaces the defaults "
                        f"({'; '.join(DEFAULT_BUSY)}). Format: '[days] HH:MM-HH:MM'")
    p.add_argument("--no-busy", action="store_true", help="ignore busy windows entirely")
    p.add_argument("--keep-durations", action="store_true",
                   help="never change flexible step durations")
    p.add_argument("--overrides", help="fixed durations per step index, e.g. '1=600,3=90'")
    p.add_argument("--starts-only", action="store_true",
                   help="only check step starts (Schedoughler's rule), not finish or hands-on overlap")
    p.add_argument("--format", choices=("json", "markdown"), default="json")
    p.add_argument("--ics", metavar="FILE", help="also write the first option as an iCalendar file")
    return p


def plan(recipe: dict, *, finish: datetime | None = None, start: datetime | None = None,
         now: datetime | None = None, busy=DEFAULT_BUSY, days: float = 7, top: int = 1,
         keep_durations: bool = False, overrides: dict | None = None,
         starts_only: bool = False) -> dict:
    """Plan a bake. Exactly one of finish/start, or neither to search for the best finish."""
    if finish and start:
        raise ValueError("give a finish time or a start time, not both")
    warnings = validate_recipe(recipe)
    windows = [BusyWindow(w) for w in (busy or ())]
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    combos = flexible_combos(recipe, keep_durations, overrides)
    profile = Profile(recipe, starts_only)

    max_total = max(c.total for c in combos)
    if finish:
        mode, lo, hi = "finish", finish - timedelta(minutes=max_total), finish
    elif start:
        mode, lo, hi = "start", start, start + timedelta(minutes=max_total)
    else:
        mode, lo, hi = "search", now, now + timedelta(days=days, minutes=max_total)
    cal = BusyCalendar(windows, lo - timedelta(days=1), hi + timedelta(days=1))

    if mode == "finish":
        _, c = best_for_finish(profile, cal, cal.m(finish), combos)
        results = [(finish, c)]
        if finish - timedelta(minutes=c.total) < now:
            warnings.append("this schedule would have to start in the past (before 'now'); "
                            "pick a later finish time")
    elif mode == "start":
        best = None
        for c in combos:
            f = start + timedelta(minutes=c.total)
            key = (len(find_conflicts(profile, cal, cal.m(f), c.durs)), c.dev, f)
            if best is None or key < best[0]:
                best = (key, c)
        results = [(best[0][2], best[1])]
    else:
        results = search(profile, cal, combos, now, days, max(1, top))
        if not results:
            raise RecipeError("no finish time fits inside the search horizon; increase days")

    options = []
    for f, c in results:
        conflicts = find_conflicts(profile, cal, cal.m(f), c.durs)
        options.append(option_json(recipe, c.overrides, compute_schedule(recipe, f, c.overrides),
                                   conflicts))
    if options[0]["conflict_count"]:
        warnings.append(f"best option still has {options[0]['conflict_count']} hands-on "
                        "moment(s) in busy windows")
    return {
        "recipe": recipe.get("name", "Bread"),
        "mode": mode,
        "now": iso(now),
        "busy_windows": [w.label for w in windows],
        "rule": "starts-only" if starts_only else "hands-on",
        "options": options,
        "warnings": warnings,
    }


def run(argv=None) -> tuple[dict, str]:
    args = build_parser().parse_args(argv)
    raw = sys.stdin.read() if args.recipe == "-" else open(args.recipe, encoding="utf-8").read()
    try:
        recipe = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RecipeError(f"recipe is not valid JSON: {e}")
    result = plan(
        recipe, finish=args.finish, start=args.start, now=args.now,
        busy=() if args.no_busy else (args.busy or DEFAULT_BUSY),
        days=args.days, top=args.top, keep_durations=args.keep_durations,
        overrides=parse_overrides(args.overrides, recipe) if args.overrides else None,
        starts_only=args.starts_only)
    if args.ics:
        with open(args.ics, "w", encoding="utf-8", newline="") as f:
            f.write(to_ics(result))
        result["ics_file"] = args.ics
    return result, args.format


def main(argv=None) -> int:
    try:
        result, fmt = run(argv)
    except (RecipeError, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if fmt == "markdown":
        sys.stdout.write(to_markdown(result))
    else:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
