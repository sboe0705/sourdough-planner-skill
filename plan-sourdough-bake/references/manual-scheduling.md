# Scheduling by hand (when the script can't run)

Use this only when there is no code execution. The rules are the same as in `scripts/schedule.py`, so a hand-made plan matches what the script would produce. Work in minutes and write every time down. Don't do the arithmetic in your head.

## 1. Backward pass for a given finish time

1. Write the finish time `F`: the bread comes out of the oven.
2. Go through the steps **from last to first**. A step ends where the next one starts (the last step ends at `F`), and starts at its end minus its duration.
3. The first step's start is when the baker begins. The total is `F` minus that start, which equals the sum of all durations.
4. For a bake step with `preheat: p`, the oven goes on at the bake start minus `p`. This adds no time.

Example: finish Sat 10:00, bake 45 → bake 09:15–10:00. Cold retard 720 → 21:15 Fri – 09:15 Sat. Shape 10 → 21:05–21:15 Fri. Keep going back to step 1.

## 2. Moments that need the baker

- every **attended** step (by default `prep` and `bake`) for its **whole** duration
- the **start** of every other step, unless the step before it was attended
- the **preheat** moment, if there is one
- the **finish**

A moment is a **conflict** if it falls inside a busy window. Windows include their start minute and exclude their end minute: with work 08:00–16:00, 08:00 is busy and 16:00 is free. Default windows: Mon–Fri 08:00–16:00 (work) and every day 22:00–06:00 (sleep). A window like 22:00–06:00 that crosses midnight belongs to the day it starts on.

## 3. No target time: find a good finish

1. **Earliest start** = now + 20 minutes. **Earliest finish** = earliest start + the total of the default durations.
2. Try finish times from there on, in 15-minute steps, over the next 7 days. Don't try every slot by hand. Use the shape of the recipe instead: put long unattended steps (cold retards, overnight levains) across a busy window, and put the hands-on cluster (mixing, shaping, baking) in free time, such as evenings after 16:00, early mornings 06:00–08:00 and weekends.
3. If a hands-on moment falls into a busy window, adjust **flexible** steps, but only inside their own `min`–`max` and in multiples of their `step`. Lengthen the step before a conflict to push it later, or shorten it to pull it earlier. Never change fixed steps or the bake.
4. Prefer, in order: no conflicts, then the soonest day, then the smallest total change from the default durations, then the earliest finish on that day.
5. If no option avoids every conflict, show the one with the fewest and name the conflicting steps.

## 4. Check before presenting

- Every step starts exactly where the previous one ends, and the last ends at the finish.
- Every changed flexible duration is within its range.
- Re-check each hands-on moment against the busy windows, including the day of the week.
