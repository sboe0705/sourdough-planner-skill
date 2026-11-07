# plan-sourdough-bake

Repository: `sourdough-planner-skill` · Skill: `plan-sourdough-bake` (in Claude Code: `/plan-sourdough-bake`)

An [Agent Skill](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview) that turns a sourdough recipe into a baking schedule for your target bake time.

Give your AI agent a recipe (pasted text, a URL or a photo) and, optionally, the time you want the bread to be done. It returns a step-by-step plan with a clock time for every step: feeding the levain, mixing, bulk fermentation, shaping, proofing, cold retard, preheating and baking. If you don't give a time, it finds one that keeps every hands-on step out of working hours (Mon–Fri 08:00–16:00) and out of the night (22:00–06:00). Long rises and fridge time run while you work or sleep, and flexible proofs are stretched or shortened within the recipe's safe range to make it fit.

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
- "Put the plan in my calendar." (exports an `.ics` file)

## Install

The skill is the [`plan-sourdough-bake/`](plan-sourdough-bake/) folder.

**Claude Code:** copy or symlink it into your personal skills directory (or a project's `.claude/skills/`):

```bash
git clone https://github.com/sboe0705/sourdough-planner-skill.git
ln -s "$PWD/sourdough-planner-skill/plan-sourdough-bake" ~/.claude/skills/plan-sourdough-bake
```

**Claude.ai / Claude Desktop:** zip the folder and upload it under *Settings → Capabilities → Skills*:

```bash
cd sourdough-planner-skill && zip -r plan-sourdough-bake.zip plan-sourdough-bake
```

**Other agents** that support the Agent Skills format: point them at the folder. The skill needs Python 3.9+ for the scheduler, with no third-party packages. If an agent can't run code, it falls back to the documented manual procedure.

## What's inside

| Path | Purpose |
|---|---|
| `plan-sourdough-bake/SKILL.md` | The workflow the agent follows |
| `plan-sourdough-bake/scripts/schedule.py` | Scheduling engine and CLI (backward pass, busy-window search, Markdown / JSON / iCalendar output) |
| `plan-sourdough-bake/references/recipe-format.md` | Recipe JSON format and rules for converting recipes |
| `plan-sourdough-bake/references/manual-scheduling.md` | The same algorithm by hand, for agents without code execution |
| `plan-sourdough-bake/examples/country-loaf.json` | A complete example recipe |
| `tests/` | Unit tests for the engine |

You can also run the engine on its own:

```bash
python3 plan-sourdough-bake/scripts/schedule.py plan-sourdough-bake/examples/country-loaf.json --format markdown
python3 plan-sourdough-bake/scripts/schedule.py recipe.json --finish 2026-11-14T10:00 --ics bake.ics
python3 plan-sourdough-bake/scripts/schedule.py recipe.json --busy "Mon-Fri 09:00-17:30" --busy "daily 22:00-06:00" --top 3
python3 plan-sourdough-bake/scripts/schedule.py --help
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

## License

[Apache 2.0](LICENSE)
