---
name: plan-sourdough-bake
description: Turns a sourdough (or any bread) recipe into a timed baking schedule with a clock time for every step (levain, mixing, bulk, shaping, proof, cold retard, bake), working backwards from a target bake or finish time. When no time is given, picks a finish time so all hands-on steps fall outside working hours and sleep, using evenings, early mornings and weekends, and adjusts flexible proofs within their safe ranges. Use whenever someone shares a bread recipe and asks when to start, wants bread ready at a certain time, asks for a baking plan, timeline or schedule, or wants to fit a bake around work or sleep, e.g. "when do I have to start to have this loaf by Saturday breakfast?" or "Backplan für dieses Rezept". Can export the plan as a printable one-page PDF.
---

# Plan a sourdough bake

Turn a bread recipe and an optional target time into a concrete baking schedule. The schedule is computed **backwards from the moment the bread comes out of the oven**: every step ends where the next one begins. Scheduling problems usually come from rise times landing at the wrong hours. Long unattended steps (levain, cold retard) should run while the baker is at work or asleep, and every hands-on moment should happen while they are free.

All paths below are relative to this skill's directory.

## Workflow

### 1. Collect the inputs

- **The recipe:** pasted text, a URL (fetch it), a photo, or a file. If there is none, ask for it. Don't make one up.
- **The target time, if any:** "ready Saturday 10:00", "for dinner tomorrow", "I want to start tonight at 19:00". It's optional.
- **Now:** the user's current local date, time and weekday. Use the date/time from the conversation context or the system clock (`date`). A sandbox clock may be in UTC; if the user's time zone is clearly different, use their local time. Always pass it explicitly as `--now`.
- **Their availability**, only if they mention it ("I work until 17:00", "night shifts", "I'm home on Wednesdays"). Don't question the user about it. The defaults are below.

Ask a clarifying question only when the recipe itself is missing or unreadable. For everything else, use the defaults and state your assumptions in the answer.

### 2. Convert the recipe to JSON

Read [references/recipe-format.md](references/recipe-format.md) and follow it exactly. In short:

- one step per phase
- durations in minutes
- `kind` is one of `prep`, `rise`, `cold`, `bake`
- flexible `min`/`max`/`step` only on proofs, rests, levain builds and retards, never on bake
- no separate preheat step, but `"preheat": <min>` on the bake step
- an active-starter build as the first step when the recipe needs one
- ingredients on the step that introduces them

Keep the recipe's language for titles and descriptions.

Write the JSON to a temporary file (for example `recipe.json` in a scratch or working directory).

### 3. Choose the mode

| User says | Run |
|---|---|
| a finish time ("ready Sat 10:00", "bake Sunday at 8") | `--finish 2026-11-14T10:00` |
| when they want to **eat/serve** it | `--finish` = that time minus cooling: about 1 h for rolls and flatbreads, 2 h for wheat loaves, 12–24 h for loaves over 50 % rye. Say that you subtracted it. |
| a day but no time ("on Saturday") | search with `--top 7 --days 8`, then pick the option that finishes that day. If none is clean, use `--finish` at a sensible hour that day. |
| a start time ("start now", "tonight at 19:00") | `--start 2026-11-07T19:00` |
| nothing about time | search (no `--finish`/`--start`), with `--top 3` for alternatives |

**Busy windows**, when the baker can't do hands-on work. The default is:

- `Mon-Fri 08:00-16:00`, work
- `daily 22:00-05:00`, sleep

So hands-on steps go in evenings from 16:00, early mornings from 05:00 to 08:00, and anywhere on weekends outside sleep. If the user describes a different routine, pass **all** their windows with repeated `--busy`, because `--busy` replaces the defaults. Keep the sleep window unless they say otherwise. The format is `[days] HH:MM-HH:MM`, with days like `Mon-Fri`, `Sat,Sun`, `weekends` or `daily`. A window that crosses midnight belongs to the day it starts on. Examples:

- "I work 9 to 17:30" → `--busy "Mon-Fri 09:00-17:30" --busy "daily 22:00-05:00"`
- "I sleep in on weekends" → add `--busy "Sat,Sun 05:00-09:00"` next to the defaults
- "ignore my schedule, just compute it" → `--no-busy`

### 4. Run the scheduler

```bash
python3 scripts/schedule.py recipe.json --now 2026-11-07T14:30 [mode options] [--busy …] [--top 3]
```

Other options:

- `--keep-durations` never changes flexible steps (use it when the user wants the recipe's exact times)
- `--overrides '3=300'` pins a step's duration in minutes (0-based step index)
- `--format markdown` gives a quick human view

The JSON output has `options[]`. Each option has `start`, `finish`, `total`, `conflict_count`, `adjusted_steps`, and `steps[]` with `start`, `end`, `duration`, `attended`, `overnight`, `conflict`, `preheat_at`, `desc` and `ingredients`. Treat these times as authoritative. Don't recompute them in your head.

If the script exits with an error, fix the recipe JSON (the message names the step) and run it again. If there is no way to run code at all, follow [references/manual-scheduling.md](references/manual-scheduling.md).

### 5. Present the schedule

Answer in the user's language. Use their locale's weekday names and time format, with a weekday and date on every line. Structure:

1. **One-line summary:** "Start **Fri 18:30**, bread is out of the oven **Sat 09:45** (total 15 h 15 min)."
2. **The schedule as a table:** time · step · duration · what to do. Show ingredients with amounts in the step where they're needed. Include the preheat row ("switch the oven on") and finish with a "bread is done" row. Mark overnight steps (🌙 or "overnight").
3. **What was adjusted:** any `adjusted_steps`, e.g. "Bulk fermentation planned at 4 h 30 min instead of 4 h (the recipe allows 3–5 h) so shaping falls after work." Leave this out if nothing changed.
4. **Conflicts, said plainly:** if `conflict_count > 0`, name each conflicting step and why, then offer a fix: one of the other options, a different finish time, or asking whether they can be home then. Never hide a conflict.
5. **Assumptions, in one or two lines:** room temperature about 22–24 °C ("go by the dough, not the clock: warmer kitchens are faster"), the default busy windows if you used them, any assumed starter build, cooling time if you subtracted it.
6. **Alternatives, if you ran `--top`:** one line each, e.g. "Or: start Sat 07:40 → bread Sun 06:45."

Keep it scannable. Leave out the raw JSON and how the script was run, unless the user asks.

### 6. Offer follow-ups

- **PDF**, when the user asks for one ("as a PDF", "to print"): see [PDF export](#pdf-export) below.
- **Reschedule:** a different finish time, different availability, or a nudged step. Re-run the script; don't edit times by hand.

## PDF export

A one-page A4 handout with only the recipe and the plan: title, subtitle, an optional photo, the ingredients, and one section per day with a clock time for every step, an "Oven on" row at the preheat moment and a final "Done" row. No notes, assumptions, conflicts or adjustments go into the PDF; keep those in your chat answer.

1. Save the scheduler's JSON output (step 4) to a file, for example `plan.json`. Use the same recipe JSON.
2. Run:
   ```bash
   python3 scripts/make_pdf.py recipe.json plan.json -o plan.pdf --lang de --subtitle "Backplan für 10 Semmeln"
   ```
   - `--lang en|de` sets the labels ("Day before" / "Bake day", "Vortag" / "Backtag", "Oven on", "Done" …). For any other language, keep `--lang en` and override every label with `--label KEY=TEXT` (the keys are listed in `--help`).
   - `--subtitle` is a short line such as "Baking plan for 10 rolls", in the user's language. When the recipe JSON has `source.url`, the script appends "· Recipe: <domain>" with the domain linked to the source.
   - Days are headed "Day before" / "Bake day" by default. Add `--dates` only when the user wants actual dates.
   - `--option N` renders another option from a `--top` run (default 0).
   - `--image PATH_OR_URL` puts a recipe photo under the subtitle, but only when the user wants one. If the output says `"image": "failed: …"`, the PDF was built without it: tell the user and ask them to upload the photo, then re-run with the uploaded file.
3. The script prints `{"pages", "font", "image", "pdf"}`. It needs `reportlab` (`pip install reportlab` if the import fails; on Python 3.9 `pip install 'reportlab<5'`). It looks for DejaVu Sans and falls back to reportlab's bundled Vera font.
4. **Check before handing it over:** render the page with `pdftoppm -png -r 80 plan.pdf preview` and look at the image. Times should line up under the headings, nothing should run past the margins, and steps shouldn't break oddly. The script already shrinks the image and the spacing to fit one page; if `pages` is still above 1, offer to leave out the photo or shorten long step descriptions in the recipe JSON.
5. Give the user the PDF file.

Write step texts without emoji; the font has no glyphs for them (the script removes any it finds).

## Rules

- Never change a fixed step or the bake time. Flexible steps move only inside their own `min`–`max`, which the script enforces.
- Don't invent durations the recipe doesn't support. When you have to infer a range or a missing starter build, say so.
- The finish time is when the bread **leaves the oven**, not when it can be sliced.
- If the user's target leaves too little time (the start would be in the past), say so, and give the earliest realistic finish from a search run.
