# sourdough-planner-skill — Claude Context

## Project Overview

This repository publishes **`plan-sourdough-bake`**, an Agent Skill that turns a bread recipe and an optional target time into a baking schedule with a clock time for every step. The schedule is computed **backwards from the moment the bread leaves the oven**. With no target time, the skill searches for a finish time whose hands-on moments fall outside busy windows, by default Mon–Fri 08:00–16:00 (work) and daily 22:00–05:00 (sleep).

The skill is meant for public use, in Claude Code, Claude.ai/Desktop and other agents that support the Agent Skills format.

**Origin:** the scheduling model and the recipe data model come from the Schedoughler app (`/home/sboe0705/Projekte/schedoughler`, https://github.com/sboe0705/schedoughler). Its `src/scheduler.js` (`computeSchedule`, `effectiveDuration`), `check-critical-times.sh` and the `add-recipe` / `tune-ideal-finish` skills are the reference. `schedule.py` is a port of that logic with extensions (see **Scheduling rules**).

**Tech stack:** Python 3 **standard library only** for the scheduler (Python 3.9+ syntax), Markdown for the skill docs, Bash for `install.sh` and `build.sh`. The one exception is the optional PDF export `make_pdf.py`, which needs **reportlab** (Pillow for non-JPEG images). The only "build" is zipping the skill folder.

## Commands

```bash
python3 -m unittest discover tests        # run the unit tests (from the repo root)

# run the engine directly
python3 plan-sourdough-bake/scripts/schedule.py plan-sourdough-bake/examples/country-loaf.json --format markdown
python3 plan-sourdough-bake/scripts/schedule.py recipe.json --now 2026-11-09T07:00 --top 3
python3 plan-sourdough-bake/scripts/schedule.py recipe.json --finish 2026-11-14T10:00 --ics bake.ics
python3 plan-sourdough-bake/scripts/schedule.py --help

# PDF export (needs reportlab; locally e.g. in a venv: python3 -m venv .venv && .venv/bin/pip install reportlab pillow)
python3 plan-sourdough-bake/scripts/schedule.py recipe.json --finish 2026-11-14T10:00 > plan.json
python3 plan-sourdough-bake/scripts/make_pdf.py recipe.json plan.json -o plan.pdf --lang de --subtitle "Backplan für 10 Semmeln"
pdftoppm -png -r 80 plan.pdf preview     # look at the page before shipping layout changes

./install.sh                 # symlink the skill into ~/.claude/skills (--project, --target, --copy, --force, --uninstall)
./build.sh                   # check frontmatter, run tests, write dist/plan-sourdough-bake.zip (--output, --skip-tests)
```

The skill is installed on this machine via `install.sh`: `~/.claude/skills/plan-sourdough-bake` is a symlink to this repo's `plan-sourdough-bake/` folder, so edits take effect in the next Claude Code session.

## Project Structure

```
plan-sourdough-bake/              # ← the skill itself; everything the agent sees lives here
├── SKILL.md                      # frontmatter (name, description) + the agent's workflow
├── scripts/schedule.py           # scheduling engine + CLI (JSON / Markdown / iCalendar output)
├── scripts/make_pdf.py           # one-page A4 PDF from schedule.py's JSON + the recipe JSON (reportlab)
├── references/recipe-format.md   # recipe JSON schema, conversion rules, range-inference table
├── references/manual-scheduling.md  # the same algorithm by hand, for agents without code execution
└── examples/country-loaf.json    # self-written example recipe
tests/test_schedule.py            # unittest suite for schedule.py (incl. CLI via subprocess)
tests/test_make_pdf.py            # unittest suite for make_pdf.py (rendering tests skip without reportlab)
install.sh                        # symlinks/copies the skill into a skills directory
build.sh                          # packages the skill as a reproducible zip in dist/ (git-ignored)
.github/workflows/build.yml       # CI on push/PR to main: tests (Python 3.9 + 3.x, with reportlab installed), then build.sh → zip artifact (upload-artifact `archive: false`, so the download is the skill zip itself, not a zip-in-zip)
.github/workflows/release.yml     # on a v* tag: build.sh (with tests) → GitHub release with the zip attached
README.md                         # public documentation (what it does, install, usage, how it decides)
CLAUDE.md                         # this file
LICENSE                           # Apache-2.0
```

## Architecture of `schedule.py`

The pipeline is `main` → `run` (CLI parsing, file I/O, `--ics`) → **`plan()`**, the public, testable entry point that returns the result dict.

- **Recipe:**
  - `validate_recipe` normalises durations to ints, rejects broken recipes with `RecipeError`, and returns warnings. A range on a `bake` step is dropped with a warning.
  - `effective_duration` clamps an override into `[min, max]`.
  - `compute_schedule` does the backward pass on `datetime`s and is used for output.
- **Busy windows:**
  - `BusyWindow` parses `'[days] HH:MM-HH:MM'` (days: `Mon-Fri`, `Sat,Sun`, `weekends`, `daily`, wrapping ranges such as `Fri-Mon`). A window ending at or before its start wraps past midnight and belongs to its start day. Start is inclusive, end exclusive.
  - `BusyCalendar` expands the windows into concrete intervals in **integer minutes** relative to a base date, with bisect lookups (`at`, `overlap`).
- **Hot loop:**
  - `Profile` precomputes per-step flags.
  - `Combo` holds one choice of flexible durations (`durs`, `total`, `dev` = total deviation from the defaults).
  - `find_conflicts` works on ints only. Keep it allocation-light, because the search calls it hundreds of thousands of times.
- **Search:**
  - `flexible_combos` lists duration choices on each step's own `step` grid, coarsened until there are at most `MAX_COMBOS`, and sorted by deviation.
  - `best_for_finish` picks the best combo for a fixed finish. It stops early once a conflict-free combo is found, because nothing later can beat it.
  - `search` scans finish times on a `SLOT_MIN` grid and keeps one option per finish day.
- **Output:** `option_json` is the JSON contract the skill relies on. `to_markdown` and `to_ics` render from that JSON, not from internal objects.

Constants at the top: `KINDS`, `ATTENDED_KINDS`, `DEFAULT_BUSY`, `START_BUFFER_MIN` (20), `SLOT_MIN` (15), `MAX_COMBOS` (600).

## Architecture of `make_pdf.py`

- **`build_model`** turns the recipe JSON and one option of `schedule.py`'s JSON into a plain dict (title, subtitle, source link, ingredients, days → rows of time / "Step · Duration" / instruction). No reportlab here, so it is tested everywhere. Days are grouped by calendar date and headed relative to the finish day ("Day before", "Bake day", "{n} days before") unless `--dates`. It adds an "Oven on" row at `preheat_at` and a "Done" row at the finish. Ingredients without an amount (intermediate products like levain) are left out. Emoji are stripped.
- **Labels** come from the `LABELS` presets (`en`, `de`) plus `--label KEY=TEXT` overrides; this is how the PDF is localised, since the agent can't edit it afterwards.
- **`render_pdf`** loads the image (path or URL; any failure → build without it and report `"image": "failed: …"`), then calls `_build` until the PDF fits one page: shrink the image from 85 mm down to `IMAGE_MIN_HEIGHT_MM`, then a compact spacing pass.
- **Layout** (keep it): A4, margins 20 mm left/right and 18 mm top/bottom, table width = text width − 12 pt frame padding (so times sit flush under the headings, zero cell padding on the left), title 22 pt bold, subtitle 10 pt `#666666`, headings 13 pt bold in accent `#8a5a2b` (also the link colour), ingredients in two columns (amount bold in a narrow column + name), steps as time (18 mm, bold) + "Step · Duration" bold over the instruction at 9.5 pt `#333333`, about 9 pt between steps, no borders, lines or backgrounds. One `Table` per step, so a step never splits across pages; each day heading is kept with its first step.
- **Fonts:** DejaVu Sans / Sans-Bold from the usual system font directories (or `--font-dir`, or matplotlib's copy), else reportlab's bundled Vera, else Helvetica.

## Scheduling rules (keep code, docs and tests consistent)

- **Moments that need the baker** (`find_conflicts`):
  - attended steps (`prep`, `bake`, or `"attended": true`) for their whole duration
  - the start of every other step, unless the previous step was attended
  - the preheat moment (bake start minus `preheat`)
  - the finish
- `--starts-only` reproduces Schedoughler's `check-critical-times.sh` rule: only step starts count. Keep it working, because it is the compatibility check against the original.
- Flexible steps move **only within their own `min`/`max`**. Fixed steps and `bake` never change.
- **Ranking:**
  - within a finish day: fewest conflicts, then least deviation, then earliest finish
  - across days: fewest conflicts, then the soonest day
- The earliest allowed start is `now + START_BUFFER_MIN`.
- `overnight` is derived from the actual times: a step of 2 h or more that touches 01:00–05:00. The recipe's `sleep` flag is ignored.

These rules are described in four places: `schedule.py`, `references/manual-scheduling.md`, `SKILL.md` and the README's "How the schedule is chosen". A change to one needs the others updated.

## Conventions

- **Standard library only** in `schedule.py`, and stay compatible with Python 3.9. Check with `python3 -c "import ast; ast.parse(open('plan-sourdough-bake/scripts/schedule.py').read(), feature_version=(3,9))"` (same for `make_pdf.py`). Use `X | None` only in annotations (both files have `from __future__ import annotations`).
- **`make_pdf.py` imports reportlab lazily**, only inside the rendering functions, so `build_model`, `--help` and the error paths work without it. Don't add other third-party packages.
- **Skill text is English.** The agent answers in the user's language, and recipe content stays in the recipe's language. Script output (labels, weekday abbreviations) is English, and the agent localises it.
- **`SKILL.md` frontmatter:**
  - `name` must stay `plan-sourdough-bake`: lowercase and hyphens, ≤ 64 characters, matching the folder name.
  - `description` is the trigger text, ≤ 1024 characters.
  - Keep the body of `SKILL.md` lean and put detail in `references/`.
- **Changing the JSON output** (field names in `option_json`) changes the skill's contract. Update `SKILL.md` step 4/5, and add fields rather than renaming them. `make_pdf.py` reads `finish`, and per step `title`, `start`, `duration`, `desc`, `ingredients` and `preheat_at`.
- **The PDF holds only the recipe and the plan.** No notes, assumptions, conflicts or adjustments, and no emoji (the fonts have no glyphs). After layout changes, render it with `pdftoppm` and look at it.
- **Changing the recipe format** means updating `references/recipe-format.md`, `examples/country-loaf.json` and `validate_recipe` together.
- **No third-party recipe texts** in the repo (copyright, since the repo is public). Examples must be self-written.
- **Tests:**
  - every behaviour change in `schedule.py` comes with a test in `tests/test_schedule.py`
  - use fixed `now`/`finish` datetimes, never the real clock
  - the suite must pass before every commit
- **Cross-check against Schedoughler** after changes to the backward pass or the conflict logic. In a scratch directory:
  1. With a small Node script, import `RECIPES` and `computeSchedule` from the schedoughler repo's `src/scheduler.js` and dump each recipe as JSON, together with its step start times for a fixed finish (its `idealFinish` on a reference day) and the number of starts in the windows 22:00–05:00 and 09:00–16:00.
  2. Compare against `compute_schedule` and against `plan(..., keep_durations=True, starts_only=True, busy=['daily 22:00-05:00', 'daily 09:00-16:00'])`.
  3. All 28 recipes matched exactly at the time of writing.

## Keeping docs up to date

**On every change, update `README.md` and `CLAUDE.md` in the same commit** wherever the change affects them:

- `README.md` covers features, example usage, install options, the file table, "How the schedule is chosen" and CLI examples.
- `CLAUDE.md` covers structure, commands, architecture, rules and conventions.

Also keep `SKILL.md` and the `references/` files in sync with the script's behaviour. Docs that contradict the code are a bug.

## Releases

- CI (`build.yml`) runs on every push to `main` and every pull request. Keep it green.
- To release, tag a commit on `main` with a semantic version and push the tag:
  ```bash
  git tag v1.0.0 && git push origin v1.0.0
  ```
  `release.yml` runs `build.sh` (tests included) and creates a GitHub release named after the tag, with generated notes and `plan-sourdough-bake.zip` attached. The asset name stays the same across versions, so `releases/latest/download/plan-sourdough-bake.zip` always points at the newest build.

## Git Workflow

- Always work directly on the `main` branch.
- Never create Git branches (no feature branches, no `git checkout -b`, no `git switch -c`, no worktrees on other branches).
- If a session environment or tool instruction asks for a separate branch, say so to the user and stay on `main` unless the user explicitly says otherwise in the conversation.
