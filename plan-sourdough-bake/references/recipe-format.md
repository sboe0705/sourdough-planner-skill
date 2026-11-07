# Recipe format and conversion rules

`scripts/schedule.py` reads a recipe as JSON. This file describes the format and how to turn a recipe written for people (a web page, a book, a handwritten card) into it. The format is the data model of [Schedoughler](https://github.com/sboe0705/schedoughler), with two additions: `attended` and `preheat`.

## Schema

```jsonc
{
  "name": "Country Sourdough Loaf",          // required
  "subtitle": "Overnight wheat loaf",         // optional
  "source": { "url": "https://…", "title": "…" },  // optional, only for a real URL
  "steps": [                                  // required, in order, first to last
    {
      "title": "Bulk fermentation",           // required, short label
      "dur": 240,                             // required, default duration in whole MINUTES
      "kind": "rise",                         // required: prep | rise | cold | bake
      "desc": "Cover and leave until risen by half.",  // one sentence: what the baker does
      "min": 180, "max": 300, "step": 15,     // optional, all three or none: flexible range
      "attended": false,                      // optional, overrides the default for the kind
      "preheat": 45,                          // optional, bake steps: minutes of preheating
      "ingredients": [                        // optional, on the step that introduces them
        { "amount": 500, "unit": "g", "name": "bread flour", "note": "Type 550" },
        { "name": "levain" }                  // no amount → something made in an earlier step
      ]
    }
  ]
}
```

Keep the recipe's language for `name`, `title`, `desc` and the ingredients. A German recipe gets German step titles.

### Kinds

| kind   | meaning                                  | attended by default |
|--------|------------------------------------------|---------------------|
| `prep` | hands-on work: mixing, kneading, shaping | yes                 |
| `rise` | fermentation or proofing at room temperature | no              |
| `cold` | retard in the fridge                     | no                  |
| `bake` | time in the oven                         | yes                 |

**Attended** means the baker has to be present for the whole step. For any other step, only its start needs the baker, and even that is skipped right after an attended step (the baker is already there and walks away). The finish, when the bread comes out, always needs the baker. Set `"attended": true` on a rise that needs regular work (folds every 30 minutes), or `"attended": false` on a long `prep` step that is really just waiting.

## Conversion rules

1. **One step per distinct phase.** Never merge kneading with bulk fermentation, or shaping with the final proof. Short hands-on moments still get their own step (e.g. "Shape", 10 min).
2. **Durations are whole minutes.** "1½ h" is `90`, "overnight" is a range (see below).
3. **Flexible ranges (`min`/`max`/`step`) only where real flexibility exists:** levain or starter builds, bulk fermentation, bench rests, final proofs, cold retards, soakers and autolyse. `step` is the nudge increment, usually `15` for proofs, `30`–`60` for long builds and retards, and `5` for short rests. Mechanical steps (mixing, kneading, shaping, scoring) carry only `dur`.
4. **Never put a range on a `bake` step.** If the source gives a range ("40–45 min"), use one representative value as `dur`. Write temperatures, steam and vessel in the bake step's `desc`.
5. **No separate preheat step.** Preheating runs in parallel with the final proof and must not lengthen the schedule. Mention it in the bake step's `desc` and set `"preheat": <minutes>` on the bake step (typically 30–60, or 45–60 with a Dutch oven or baking stone). The scheduler then shows and checks the moment the oven has to be switched on.
6. **Starter refresh / levain build is step 1** whenever the recipe needs an active starter or levain ("use a starter fed 4–8 hours ago", "build the levain the evening before"). Model it as a short `prep` step (feeding, ~10 min) plus a flexible `rise` (ripening). If the recipe just says "100 g active starter" and gives no build, add the feed anyway with a typical range (4–12 h at room temperature, `step` 30–60) and tell the user you assumed it.
7. **Stretch-and-folds:** if bulk fermentation has folds at fixed intervals, split it into a fixed, attended "Bulk with folds" step (e.g. 4 folds × 30 min = `120`, `"attended": true`) and a flexible, unattended "Bulk, rest" step. If the folds are optional or rare, keep one bulk step and mention them in `desc`.
8. **Ingredients belong to the step where they first appear.** A preferment used later appears there as `{ "name": "levain" }` without an amount. Steps that only transform the dough carry no `ingredients`.
9. **The schedule ends when the bread leaves the oven.** Don't add cooling as a step. Account for cooling when choosing the finish time (see SKILL.md).

## Inferring ranges when the recipe gives a single time

Many recipes give one time, or a cue like "until doubled". Use the recipe's own range when it has one. Otherwise use these conservative defaults, and keep `dur` at the recipe's value:

| step | range around the given time `T` | typical `step` |
|---|---|---|
| levain / starter build | 0.8 T – 1.5 T (if no time given: 4–12 h) | 30 or 60 |
| autolyse / soaker | 0.5 T – 2 T (an autolyse may be 20–60 min) | 5 or 15 |
| bulk fermentation, wheat | 0.75 T – 1.25 T | 15 |
| bench rest | 0.67 T – 1.33 T | 5 |
| final proof at room temperature, wheat | 0.75 T – 1.25 T | 15 |
| any proof, rye or > 50 % rye | 0.85 T – 1.15 T (rye over-proofs quickly) | 5 or 15 |
| cold retard ("overnight" = 8–16 h) | 0.67 T – 1.33 T, at most 24 h unless the recipe allows more | 30 or 60 |
| mixing, kneading, shaping, folding, baking | fixed: no range | — |

Round `min`/`max` to multiples of `step`, and keep `min ≤ dur ≤ max`. The ranges assume about 22–24 °C. When the user says their kitchen is notably warmer or colder, shift the room-temperature steps: roughly half as long per +8 °C, twice as long per −8 °C. Say that you did this.

## Example

[`../examples/country-loaf.json`](../examples/country-loaf.json) is a complete recipe in this format.
