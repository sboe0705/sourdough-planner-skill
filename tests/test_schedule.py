"""Unit tests for plan-sourdough-bake/scripts/schedule.py (stdlib unittest).

Run from the repository root:  python3 -m unittest discover tests
"""

import copy
import json
import subprocess
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plan-sourdough-bake" / "scripts" / "schedule.py"
EXAMPLE = ROOT / "plan-sourdough-bake" / "examples" / "country-loaf.json"
sys.path.insert(0, str(SCRIPT.parent))

import schedule as S  # noqa: E402

# Mirrors the fixture Schedoughler's scheduler.test.js uses: a long sourdough.
RECIPE = {
    "name": "Test loaf",
    "steps": [
        {"title": "Levain", "dur": 15, "kind": "prep"},
        {"title": "Levain ripens", "dur": 720, "min": 480, "max": 840, "step": 30, "kind": "rise"},
        {"title": "Mix", "dur": 20, "kind": "prep"},
        {"title": "Bulk", "dur": 240, "min": 180, "max": 300, "step": 15, "kind": "rise"},
        {"title": "Shape", "dur": 10, "kind": "prep"},
        {"title": "Cold retard", "dur": 720, "min": 480, "max": 960, "step": 60, "kind": "cold"},
        {"title": "Bake", "dur": 45, "kind": "bake"},
    ],
}
FINISH = datetime(2026, 11, 14, 18, 0)  # a Saturday


def recipe():
    r = copy.deepcopy(RECIPE)
    S.validate_recipe(r)
    return r


class ComputeScheduleTest(unittest.TestCase):
    """Ported from Schedoughler's computeSchedule tests."""

    def setUp(self):
        self.r = recipe()
        self.steps = S.compute_schedule(self.r, FINISH)

    def test_last_step_ends_at_finish(self):
        self.assertEqual(self.steps[-1]["end"], FINISH)

    def test_steps_are_contiguous(self):
        for a, b in zip(self.steps, self.steps[1:]):
            self.assertEqual(a["end"], b["start"])

    def test_duration_matches_end_minus_start(self):
        for s in self.steps:
            self.assertEqual(s["end"] - s["start"], timedelta(minutes=s["dur"]))

    def test_total_is_sum_of_durations(self):
        total = sum(s["dur"] for s in self.r["steps"])
        self.assertEqual(FINISH - self.steps[0]["start"], timedelta(minutes=total))

    def test_applies_overrides(self):
        steps = S.compute_schedule(self.r, FINISH, {1: 840})
        self.assertEqual(steps[1]["dur"], 840)
        self.assertEqual(steps[0]["start"], self.steps[0]["start"] - timedelta(minutes=120))

    def test_clamps_overrides(self):
        steps = S.compute_schedule(self.r, FINISH, {1: 10_000, 3: 1})
        self.assertEqual(steps[1]["dur"], 840)
        self.assertEqual(steps[3]["dur"], 180)

    def test_override_on_fixed_step_is_ignored(self):
        steps = S.compute_schedule(self.r, FINISH, {6: 5})
        self.assertEqual(steps[6]["dur"], 45)


class EffectiveDurationTest(unittest.TestCase):
    step = {"dur": 60, "min": 30, "max": 90, "step": 15}

    def test_fixed_step(self):
        self.assertEqual(S.effective_duration({"dur": 20}, 99), 20)

    def test_within_range(self):
        self.assertEqual(S.effective_duration(self.step, 75), 75)

    def test_none_override(self):
        self.assertEqual(S.effective_duration(self.step, None), 60)

    def test_clamps(self):
        self.assertEqual(S.effective_duration(self.step, 5), 30)
        self.assertEqual(S.effective_duration(self.step, 500), 90)


class ValidationTest(unittest.TestCase):
    def test_rejects_bad_kind(self):
        with self.assertRaises(S.RecipeError):
            S.validate_recipe({"steps": [{"title": "x", "dur": 5, "kind": "oven"}]})

    def test_rejects_partial_range(self):
        with self.assertRaises(S.RecipeError):
            S.validate_recipe({"steps": [{"title": "x", "dur": 5, "kind": "rise", "min": 3}]})

    def test_rejects_dur_outside_range(self):
        with self.assertRaises(S.RecipeError):
            S.validate_recipe({"steps": [{"title": "x", "dur": 50, "kind": "rise",
                                          "min": 10, "max": 40, "step": 5}]})

    def test_rejects_empty(self):
        with self.assertRaises(S.RecipeError):
            S.validate_recipe({"steps": []})

    def test_bake_range_is_dropped_with_warning(self):
        r = {"steps": [{"title": "Bake", "dur": 40, "kind": "bake", "min": 35, "max": 45, "step": 5}]}
        warnings = S.validate_recipe(r)
        self.assertTrue(warnings)
        self.assertNotIn("min", r["steps"][0])


class BusyWindowTest(unittest.TestCase):
    def cal(self, *windows):
        return S.BusyCalendar([S.BusyWindow(w) for w in windows],
                              datetime(2026, 11, 1), datetime(2026, 11, 30))

    def at(self, cal, t):
        return cal.at(cal.m(t))

    def test_weekday_window(self):
        cal = self.cal("Mon-Fri 08:00-16:00")
        self.assertTrue(self.at(cal, datetime(2026, 11, 9, 8, 0)))     # Mon 08:00, inclusive
        self.assertFalse(self.at(cal, datetime(2026, 11, 9, 16, 0)))   # Mon 16:00, exclusive
        self.assertFalse(self.at(cal, datetime(2026, 11, 14, 10, 0)))  # Saturday free

    def test_wrapping_window_belongs_to_start_day(self):
        cal = self.cal("Fri 22:00-06:00")
        self.assertTrue(self.at(cal, datetime(2026, 11, 13, 23, 0)))   # Fri night
        self.assertTrue(self.at(cal, datetime(2026, 11, 14, 5, 59)))   # Sat early morning
        self.assertFalse(self.at(cal, datetime(2026, 11, 13, 3, 0)))   # Fri early morning

    def test_daily_default(self):
        cal = self.cal("22:00-06:00")
        for day in range(9, 16):
            self.assertTrue(self.at(cal, datetime(2026, 11, day, 2, 0)))

    def test_day_lists_and_aliases(self):
        self.assertEqual(S.BusyWindow("Sat,Sun 10:00-12:00").days, {5, 6})
        self.assertEqual(S.BusyWindow("weekends 10:00-12:00").days, {5, 6})
        self.assertEqual(S.BusyWindow("Fri-Mon 10:00-12:00").days, {4, 5, 6, 0})
        self.assertEqual(S.BusyWindow("Montag 10:00-12:00").days, {0})

    def test_default_windows(self):
        self.assertEqual(S.DEFAULT_BUSY, ("Mon-Fri 08:00-16:00", "daily 22:00-05:00"))
        cal = S.BusyCalendar([S.BusyWindow(w) for w in S.DEFAULT_BUSY],
                             datetime(2026, 11, 1), datetime(2026, 11, 30))
        self.assertTrue(cal.at(cal.m(datetime(2026, 11, 10, 4, 59))))   # Tue, still asleep
        self.assertFalse(cal.at(cal.m(datetime(2026, 11, 10, 5, 0))))   # Tue 05:00, up
        self.assertTrue(cal.at(cal.m(datetime(2026, 11, 10, 8, 0))))    # Tue, work starts
        self.assertFalse(cal.at(cal.m(datetime(2026, 11, 10, 16, 0))))  # Tue, work ends

    def test_overlapping_windows(self):
        cal = self.cal("09:00-17:00", "10:00-11:00")
        self.assertTrue(self.at(cal, datetime(2026, 11, 9, 12, 0)))

    def test_overlap_query(self):
        cal = self.cal("Mon-Fri 08:00-16:00")
        a, b = cal.m(datetime(2026, 11, 9, 7, 30)), cal.m(datetime(2026, 11, 9, 8, 0))
        self.assertIsNone(cal.overlap(a, b))       # ends exactly when work starts
        self.assertTrue(cal.overlap(a, b + 1))

    def test_rejects_garbage(self):
        for bad in ("8-16", "Mon 08:00", "Xyz 08:00-09:00", "10:00-10:00", "25:00-26:00"):
            with self.assertRaises(ValueError, msg=bad):
                S.BusyWindow(bad)


class ConflictRuleTest(unittest.TestCase):
    def test_walking_away_after_hands_on_step_is_fine(self):
        r = {"steps": [{"title": "Mix", "dur": 10, "kind": "prep"},
                       {"title": "Rise", "dur": 120, "kind": "rise"},
                       {"title": "Bake", "dur": 30, "kind": "bake"}]}
        # Mix 07:50-08:00 on a Monday, rise starts at 08:00 when work begins
        res = S.plan(r, finish=datetime(2026, 11, 9, 10, 30), busy=["Mon-Fri 08:00-10:00"])
        self.assertEqual(res["options"][0]["conflict_count"], 0)

    def test_hands_on_step_must_fit_entirely(self):
        r = {"steps": [{"title": "Bake", "dur": 45, "kind": "bake"}]}
        res = S.plan(r, finish=datetime(2026, 11, 9, 8, 30), busy=["Mon-Fri 08:00-16:00"])
        self.assertEqual(res["options"][0]["steps"][0]["conflict"] is not None, True)

    def test_unattended_start_counts(self):
        r = {"steps": [{"title": "Cold", "dur": 600, "kind": "cold"},
                       {"title": "Bake", "dur": 45, "kind": "bake"}]}
        res = S.plan(r, finish=datetime(2026, 11, 14, 10, 0), busy=["22:00-06:00"])
        opt = res["options"][0]
        self.assertTrue(opt["steps"][0]["conflict"])  # cold step starts 23:15
        self.assertIsNone(opt["steps"][1]["conflict"])

    def test_finish_counts(self):
        r = {"steps": [{"title": "Rise", "dur": 180, "kind": "rise"}]}  # 06:00-09:00
        res = S.plan(r, finish=datetime(2026, 11, 9, 9, 0), busy=["Mon-Fri 08:00-16:00"])
        self.assertIsNone(res["options"][0]["steps"][0]["conflict"])
        self.assertTrue(res["options"][0]["finish_conflict"])

    def test_attended_flag_overrides_kind(self):
        r = {"steps": [{"title": "Bulk with folds", "dur": 120, "kind": "rise", "attended": True},
                       {"title": "Bake", "dur": 30, "kind": "bake"}]}
        res = S.plan(r, finish=datetime(2026, 11, 9, 9, 0), busy=["Mon-Fri 08:00-16:00"])
        self.assertTrue(res["options"][0]["steps"][0]["conflict"])

    def test_preheat_moment_is_checked_but_adds_no_time(self):
        r = {"steps": [{"title": "Cold", "dur": 600, "kind": "cold"},
                       {"title": "Bake", "dur": 45, "kind": "bake", "preheat": 60}]}
        finish = datetime(2026, 11, 14, 7, 30)  # bake 06:45, preheat 05:45 (asleep)
        opt = S.plan(r, finish=finish, busy=["22:00-06:00"])["options"][0]
        self.assertEqual(opt["total_minutes"], 645)
        self.assertEqual(opt["steps"][1]["preheat_at"], "2026-11-14T05:45")
        self.assertTrue(opt["steps"][1]["preheat_conflict"])
        self.assertEqual(opt["conflict_count"], 1)

    def test_rejects_negative_preheat(self):
        with self.assertRaises(S.RecipeError):
            S.validate_recipe({"steps": [{"title": "B", "dur": 5, "kind": "bake", "preheat": -1}]})

    def test_starts_only_matches_schedoughler_rule(self):
        # 07:00-17:00 on a Monday: starts before work, but runs through it and
        # finishes after it. Only the hands-on rule objects.
        r = {"steps": [{"title": "Bake", "dur": 600, "kind": "bake"}]}
        kwargs = dict(finish=datetime(2026, 11, 9, 17, 0), busy=["Mon-Fri 08:00-16:00"])
        self.assertEqual(S.plan(r, starts_only=True, **kwargs)["options"][0]["conflict_count"], 0)
        self.assertEqual(S.plan(r, **kwargs)["options"][0]["conflict_count"], 1)


class SearchTest(unittest.TestCase):
    NOW = datetime(2026, 11, 9, 7, 0)  # Monday morning

    def test_default_plan_avoids_busy_windows(self):
        res = S.plan(recipe(), now=self.NOW)
        opt = res["options"][0]
        self.assertEqual(opt["conflict_count"], 0)
        cal = S.BusyCalendar([S.BusyWindow(w) for w in S.DEFAULT_BUSY],
                             self.NOW, self.NOW + timedelta(days=10))
        for s in opt["steps"]:
            start = datetime.fromisoformat(s["start"])
            end = datetime.fromisoformat(s["end"])
            if s["attended"]:
                self.assertIsNone(cal.overlap(cal.m(start), cal.m(end)), s)

    def test_flexible_steps_stay_within_their_range(self):
        r = recipe()
        for opt in S.plan(r, now=self.NOW, top=5)["options"]:
            for s, orig in zip(opt["steps"], r["steps"]):
                if S.is_flexible(orig):
                    self.assertTrue(orig["min"] <= s["duration_minutes"] <= orig["max"])
                else:
                    self.assertEqual(s["duration_minutes"], orig["dur"])

    def test_start_not_before_now_plus_buffer(self):
        opt = S.plan(recipe(), now=self.NOW)["options"][0]
        self.assertGreaterEqual(datetime.fromisoformat(opt["start"]),
                                self.NOW + timedelta(minutes=S.START_BUFFER_MIN))

    def test_top_gives_one_option_per_day(self):
        days = [o["finish"][:10] for o in S.plan(recipe(), now=self.NOW, top=4)["options"]]
        self.assertEqual(len(days), len(set(days)))

    def test_keep_durations(self):
        opt = S.plan(recipe(), now=self.NOW, keep_durations=True)["options"][0]
        self.assertEqual(opt["adjusted_steps"], [])

    def test_prefers_default_durations_when_they_fit(self):
        res = S.plan(recipe(), finish=FINISH, busy=[])
        self.assertEqual(res["options"][0]["adjusted_steps"], [])

    def test_pinned_override_is_respected(self):
        res = S.plan(recipe(), finish=FINISH, overrides={5: 900})
        self.assertEqual(res["options"][0]["steps"][5]["duration_minutes"], 900)

    def test_start_mode(self):
        start = datetime(2026, 11, 14, 8, 0)
        opt = S.plan(recipe(), start=start, busy=[])["options"][0]
        self.assertEqual(opt["start"], "2026-11-14T08:00")

    def test_finish_in_past_warns(self):
        res = S.plan(recipe(), finish=self.NOW, now=self.NOW)
        self.assertTrue(any("past" in w for w in res["warnings"]))


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-I", str(SCRIPT), str(EXAMPLE), *args],
                              capture_output=True, text=True)

    def test_json_output(self):
        p = self.run_cli("--now", "2026-11-09T07:00")
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(p.stdout)
        self.assertEqual(data["mode"], "search")
        self.assertEqual(data["options"][0]["conflict_count"], 0)

    def test_markdown_output(self):
        p = self.run_cli("--finish", "2026-11-15T10:00", "--format", "markdown")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("| When | Step |", p.stdout)
        self.assertIn("Bread is done", p.stdout)

    def test_error_exit_code(self):
        p = self.run_cli("--busy", "nonsense")
        self.assertEqual(p.returncode, 2)
        self.assertIn("error:", p.stderr)


if __name__ == "__main__":
    unittest.main()
