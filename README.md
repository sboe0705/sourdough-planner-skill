# plan-sourdough-bake

Repository: `sourdough-planner-skill` · Skill: `plan-sourdough-bake` (in Claude Code: `/plan-sourdough-bake`)

An [Agent Skill](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview) that turns a sourdough recipe into a baking schedule for your target bake time.

Give your AI agent a recipe (pasted text, a URL or a photo) and, optionally, the time you want the bread to be done. It returns a step-by-step plan with a clock time for every step: feeding the levain, mixing, bulk fermentation, shaping, proofing, cold retard, preheating and baking. If you don't give a time, it finds one that keeps every hands-on step out of working hours (Mon–Fri 08:00–16:00) and out of the night (22:00–05:00). Long rises and fridge time run while you work or sleep, and flexible proofs are stretched or shortened within the recipe's safe range to make it fit.

The scheduling model comes from [Schedoughler](https://github.com/sboe0705/schedoughler), a bread-baking scheduler app. The bundled engine is a stdlib-only Python port of its backward scheduling, checked against the original on all 28 of its recipes.

## Example

> **You:** Here's my recipe: [recipe] — when do I have to start?
>
> **Agent:** Start **Mon 07:50**, bread is out of the oven **Tue 07:45** (total 23 h 55 min).
>
> | When | Step | Duration |
> |---|---|---|
> | Mon 07:50 | Build the levain: 20 g starter, 50 g flour, 50 g water | 10 min |
> | Mon 08:00 | Let the levain ripen | 8 h |
> | Mon 16:00 | Mix the dough: levain, 450 g bread flour, … | 20 min |
> | Mon 16:20 | Bulk fermentation (4 folds in the first 2 h) | 4 h |
> | … | … | … |
> | Mon 21:00 | Cold retard 🌙 | 10 h |
> | Tue 06:15 | Switch the oven on (250 °C, Dutch oven inside) | |
> | Tue 07:00 | Bake | 45 min |
>
> Levain planned at 8 h instead of 5 h (the recipe allows 4–8 h) so mixing falls after work …

Other things you can ask:

- "I want this bread for Saturday breakfast."
- "Plan it around my shifts: I work 14:00–22:00 on weekdays."
- "Start tonight at 19:00. When will it be done?"
- "Give me the plan as a PDF to print." (a one-page A4 handout: ingredients, then each day's steps with clock times, headed "Day before" / "Bake day")

## Install

The skill is the [`plan-sourdough-bake/`](plan-sourdough-bake/) folder.

**Claude Code:** clone the repository and run `install.sh`. It symlinks the skill into your personal skills directory, so a later `git pull` updates the installed skill too:

```bash
git clone https://github.com/sboe0705/sourdough-planner-skill.git
cd sourdough-planner-skill
./install.sh                        # ~/.claude/skills/plan-sourdough-bake -> this repo
```

| Option | Effect |
|---|---|
| `--project DIR` | install into `DIR/.claude/skills` (one project only) |
| `--target DIR` | install into any skills directory, for other agents |
| `--copy` | copy the files instead of symlinking (e.g. when the repo will be moved or deleted) |
| `--force` | replace an existing `plan-sourdough-bake` entry |
| `--uninstall` | remove the installed skill (only a link or copy of this skill, nothing else) |

**Claude.ai / Claude Desktop:** download `plan-sourdough-bake.zip` from the [latest release](https://github.com/sboe0705/sourdough-planner-skill/releases/latest) and upload it under *Settings → Capabilities → Skills* (code execution must be turned on). Or build the zip yourself:

```bash
cd sourdough-planner-skill && ./build.sh    # → dist/plan-sourdough-bake.zip
```

`build.sh` checks the `SKILL.md` frontmatter (name and description limits), runs the unit tests, and writes a reproducible zip with the skill folder at its root and without caches. Options: `--output FILE` for another destination, `--skip-tests` to package without testing.

**Other agents** that support the Agent Skills format: point them at the folder. The skill needs Python 3.9+ for the scheduler, with no third-party packages. Only the optional PDF export needs [reportlab](https://pypi.org/project/reportlab/) (`pip install reportlab`, on Python 3.9 `pip install 'reportlab<5'`, plus Pillow for PNG photos); it uses DejaVu Sans when installed and reportlab's bundled Vera font otherwise. If an agent can't run code, it falls back to the documented manual procedure.

## What's inside

| Path | Purpose |
|---|---|
| `plan-sourdough-bake/SKILL.md` | The workflow the agent follows |
| `plan-sourdough-bake/scripts/schedule.py` | Scheduling engine and CLI (backward pass, busy-window search, Markdown / JSON output) |
| `plan-sourdough-bake/scripts/make_pdf.py` | Renders a schedule (the scheduler's JSON plus the recipe JSON) as a one-page A4 PDF (needs reportlab) |
| `plan-sourdough-bake/references/recipe-format.md` | Recipe JSON format and rules for converting recipes |
| `plan-sourdough-bake/references/manual-scheduling.md` | The same algorithm by hand, for agents without code execution |
| `plan-sourdough-bake/examples/country-loaf.json` | A complete example recipe |
| `install.sh` | Symlinks (or copies) the skill into a skills directory |
| `release.sh` | Tags and pushes a new release version: shows the latest release, suggests the next version |
| `build.sh` | Packages the skill as `dist/plan-sourdough-bake.zip` for upload to Claude.ai and other agents |
| `.github/workflows/build.yml` | CI: tests on Python 3.9 and current 3.x, then uploads the zip as a workflow artifact, unwrapped (no zip-in-zip), so it can be uploaded to an agent as downloaded |
| `.github/workflows/release.yml` | Publishes a GitHub release with the zip when a `v*` tag is pushed |
| `CLAUDE.md` | Development guide for AI agents (and humans) working on this repo |
| `tests/` | Unit tests for the engine and the PDF export |

You can also run the engine on its own:

```bash
python3 plan-sourdough-bake/scripts/schedule.py plan-sourdough-bake/examples/country-loaf.json --format markdown
python3 plan-sourdough-bake/scripts/schedule.py recipe.json --finish 2026-11-14T10:00
python3 plan-sourdough-bake/scripts/schedule.py recipe.json --busy "Mon-Fri 09:00-17:30" --busy "daily 22:00-05:00" --top 3
python3 plan-sourdough-bake/scripts/schedule.py --help

# PDF export (needs reportlab)
python3 plan-sourdough-bake/scripts/schedule.py recipe.json --finish 2026-11-14T10:00 > plan.json
python3 plan-sourdough-bake/scripts/make_pdf.py recipe.json plan.json -o plan.pdf --lang de --subtitle "Backplan für 10 Semmeln"
python3 plan-sourdough-bake/scripts/make_pdf.py recipe.json plan.json -o plan.pdf --dates --image photo.jpg
```

## How the schedule is chosen

- **Backwards from the finish:** the last step ends at the finish time, and every earlier step ends where the next one starts.
- **Moments that need you:**
  - every hands-on step (`prep`, `bake`) for its whole duration
  - the start of every other step, unless you're already there from the step before
  - switching the oven on
  - taking the bread out
- **Search:** finish times on a 15-minute grid over the next 7 days. Flexible steps vary only within their own `min`/`max`. The ranking is fewest conflicts, then the soonest day, then the smallest change from the recipe's default durations.

## Development

```bash
python3 -m unittest discover tests
```

The PDF rendering tests are skipped when reportlab isn't installed.

[`CLAUDE.md`](CLAUDE.md) holds the development guide: architecture of the engine, the scheduling rules and where they are documented, conventions (stdlib only, Python 3.9+), the cross-check against Schedoughler, and the Git workflow (all work on `main`). Keep `README.md` and `CLAUDE.md` up to date with every change.

## License

[Apache 2.0](LICENSE)
