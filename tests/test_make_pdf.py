"""Unit tests for plan-sourdough-bake/scripts/make_pdf.py (stdlib unittest).

The plan model and the CLI's error handling need no third-party packages.
The rendering tests run only when reportlab is installed.

Run from the repository root:  python3 -m unittest discover tests
"""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "plan-sourdough-bake" / "scripts"
SCRIPT = SCRIPTS / "make_pdf.py"
EXAMPLE = ROOT / "plan-sourdough-bake" / "examples" / "country-loaf.json"
sys.path.insert(0, str(SCRIPTS))

import make_pdf as P  # noqa: E402
import schedule as S  # noqa: E402

# Import it for real: reportlab 5 installs on Python 3.9 but refuses to import there.
try:
    import reportlab  # noqa: F401
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False
FINISH = datetime(2026, 11, 14, 10, 0)  # a Saturday
NOW = datetime(2026, 11, 9, 7, 0)


def example_recipe():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def example_schedule(recipe=None):
    return S.plan(copy.deepcopy(recipe or example_recipe()), now=NOW, finish=FINISH)


class ModelTest(unittest.TestCase):
    def setUp(self):
        self.recipe = example_recipe()
        self.schedule = example_schedule()
        self.model = P.build_model(self.recipe, self.schedule)

    def rows(self, model=None):
        return [r for d in (model or self.model)["days"] for r in d["rows"]]

    def test_relative_day_headings(self):
        self.assertEqual([d["heading"] for d in self.model["days"]], ["Day before", "Bake day"])

    def test_german_labels(self):
        model = P.build_model(self.recipe, self.schedule, lang="de")
        self.assertEqual([d["heading"] for d in model["days"]], ["Vortag", "Backtag"])
        self.assertEqual(model["ingredients_heading"], "Zutaten")
        self.assertEqual(self.rows(model)[-1]["head"], "Fertig")

    def test_dates_instead_of_relative_days(self):
        model = P.build_model(self.recipe, self.schedule, lang="de", use_dates=True)
        self.assertEqual([d["heading"] for d in model["days"]],
                         ["Freitag, 13. November 2026", "Samstag, 14. November 2026"])

    def test_more_than_one_day_before(self):
        self.assertEqual(P.day_heading(datetime(2026, 11, 12).date(), FINISH.date(),
                                       P.labels_for("en"), False), "2 days before")

    def test_rows_cover_every_step_plus_oven_and_done(self):
        rows = self.rows()
        steps = self.schedule["options"][0]["steps"]
        self.assertEqual(len(rows), len(steps) + 2)
        self.assertEqual(rows[0], {"time": steps[0]["start"][11:], "head":
                                   steps[0]["title"] + " · " + steps[0]["duration"],
                                   "desc": steps[0]["desc"]})
        self.assertEqual(rows[-1], {"time": "10:00", "head": "Done", "desc": ""})

    def test_oven_on_row_at_preheat_time(self):
        bake = self.schedule["options"][0]["steps"][-1]
        rows = self.rows()
        oven = rows[-3]
        self.assertEqual(oven["head"], "Oven on")
        self.assertEqual(oven["time"], bake["preheat_at"][11:])
        self.assertEqual(oven["desc"], "Preheat for 45 min.")
        self.assertTrue(rows[-2]["head"].startswith("Bake"))

    def test_ingredients_skip_intermediate_products(self):
        ings = self.model["ingredients"]
        self.assertNotIn("levain", [name for _, name in ings])
        self.assertEqual(ings[0], ("20 g", "active sourdough starter"))
        self.assertIn(("50 g", "water (lukewarm)"), ings)

    def test_decimal_amounts_use_the_locale_separator(self):
        self.assertEqual(P.format_amount(1.5, ","), "1,5")
        self.assertEqual(P.format_amount(2.0, ","), "2")
        self.assertEqual(P.format_amount(450, ","), "450")

    def test_subtitle_and_source_link(self):
        self.recipe["source"] = {"url": "https://www.example.org/rezept/brot", "title": "x"}
        model = P.build_model(self.recipe, self.schedule, subtitle="Plan for 2 loaves")
        self.assertEqual(model["subtitle"], "Plan for 2 loaves")
        self.assertEqual(model["link"], {"url": "https://www.example.org/rezept/brot",
                                         "text": "example.org", "label": "Recipe"})

    def test_subtitle_defaults_to_recipe_subtitle_and_no_link(self):
        self.assertEqual(self.model["subtitle"], self.recipe["subtitle"])
        self.assertIsNone(self.model["link"])

    def test_emoji_are_removed(self):
        self.recipe["name"] = "Loaf 🍞 deluxe"
        self.assertEqual(P.build_model(self.recipe, self.schedule)["title"], "Loaf deluxe")

    def test_label_override(self):
        model = P.build_model(self.recipe, self.schedule, label_overrides={"done": "Klaar"})
        self.assertEqual(self.rows(model)[-1]["head"], "Klaar")
        with self.assertRaises(P.PlanError):
            P.build_model(self.recipe, self.schedule, label_overrides={"nope": "x"})

    def test_bad_option_index(self):
        with self.assertRaises(P.PlanError):
            P.build_model(self.recipe, self.schedule, option=5)
        with self.assertRaises(P.PlanError):
            P.build_model(self.recipe, {"options": []})


class CliTest(unittest.TestCase):
    def run_cli(self, *args, stdin=None):
        return subprocess.run([sys.executable, "-I", str(SCRIPT), *args],
                              input=stdin, capture_output=True, text=True)

    def test_rejects_non_schedule_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.run_cli(str(EXAMPLE), "-", "-o", str(Path(tmp) / "x.pdf"), stdin="{}")
        self.assertEqual(p.returncode, 2)
        self.assertIn("no options", p.stderr)

    @unittest.skipUnless(HAS_REPORTLAB, "reportlab is not installed")
    def test_writes_a_one_page_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "plan.pdf"
            p = self.run_cli(str(EXAMPLE), "-", "-o", str(out), "--lang", "de",
                             stdin=json.dumps(example_schedule()))
            self.assertEqual(p.returncode, 0, p.stderr)
            result = json.loads(p.stdout)
            self.assertEqual(result["pages"], 1)
            self.assertEqual(result["image"], "none")
            self.assertTrue(out.read_bytes().startswith(b"%PDF"))

    @unittest.skipUnless(HAS_REPORTLAB, "reportlab is not installed")
    def test_missing_image_still_builds_the_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "plan.pdf"
            p = self.run_cli(str(EXAMPLE), "-", "-o", str(out),
                             "--image", str(Path(tmp) / "missing.jpg"),
                             stdin=json.dumps(example_schedule()))
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue(json.loads(p.stdout)["image"].startswith("failed"))
            self.assertIn("image not included", p.stderr)
            self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
