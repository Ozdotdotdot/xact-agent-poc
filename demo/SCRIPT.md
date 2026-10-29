# Recording script (~2.5 min)

## Before you hit record

```bash
git clone https://github.com/Ozdotdotdot/xact-agent-poc && cd xact-agent-poc
curl -LsSf https://astral.sh/uv/install.sh | sh      # if uv isn't installed
uv sync
echo "ZEN_API_KEY=<your OpenCode Zen key>" > .env

# warm-up run: caches the per-photo results so the live run is fast and you've seen it work once
uv run run.py data/claim-001 --transcript 03-overclaim --guided --xact-fault-rate 0.3

uv run demo/build.py
xdg-open demo/deck.html        # F = fullscreen, arrow keys / space to move
```

Two windows: the **deck** (fullscreen) and a **terminal** in the repo with the font size turned up.

The warm-up caches photo descriptions, so the live run takes ~20s. To show step 2 running live instead, `rm out/claim-001/observations.*.json` first (~70s, ~10¢; talk over the wait).

## The story in one breath

You asked what breaks first; I said missing information, then built it to check. Public photos don't carry the measurements, so I staged a loss where I know the answers. Models look, code does the math. Better models got room sorting to 91%; the only thing that got it to 100% wasn't a model change: the photos arrived tagged. So the fix is to own the capture.

Say the thesis once at the start, prove it once on the chart, land it once at the close. Don't explain guided capture before the pipeline slide.

## Slide by slide

| # | Slide | Say |
|---|---|---|
| 1 | What breaks first? | "You asked what breaks first when an agent turns a call and 40 photos into an Xact estimate. In my Loom I said missing information. I built it to check, and I was right. The fix isn't a smarter model, it's owning the capture." |
| 2 | 0/12 public photos | "I started with 12 public water-damage photos. Not one had a water line the model could measure, and it said so instead of making up a number. The information just isn't in the photos." |
| 3 | Staged water loss | "So I staged my own. Bedroom, den, living room, tape at three heights I measured, 23 photos with duplicates and different angles. Now I know the right answer for every room." |
| 4 | Three callers | "Then three calls about the same basement: one prepared, one vague, one exaggerating. Each should trigger specific flags." |
| 5 | Pipeline | "Models look, code does the math. A model reads the call and pulls out every fact with a quote. A cheap model describes each photo: walls, damage, where the water line is. Steps 3 and 4 are where it struggles: which room a photo is from, and how many walls got wet. Those aren't really vision problems; the person taking the photos already knows the answers, so a guided capture app should record them. In this run room tags come from capture, so step 3 is skipped. Wall counting is still on the model, and you'll see it miss. Then code computes the estimate, writes it to Xact, and reads it back to make sure every line actually landed. Anything missing or contradictory goes to a human instead of being guessed." |
| 6 | Live run | Paste the command from the slide. Point at three things, nothing else: **step 4**: "Den says 3, truth is 2. That's the miss I mentioned, and it's flagged for a human." **The `?` lines**: "The caller said over a foot, the photos show six inches, so a human confirms. They claimed a home office with no photos of it, so nothing is billed there." **Step 6**: if a write failed, "Xact silently dropped a write; the read-back caught it and fixed it." If none failed, "no failures this run; across 45 eval runs it caught and repaired 60." |
| 7 | Bar chart | "I ran five versions, nine runs each, scored against the truth. Better models and better prompts got room sorting from 39% to 91%. The only thing that got it to 100% wasn't a model change: the photos arrived tagged." |
| 8 | 27/27 · 27/27 · 9/9 · $0.08 | "With that one change, every flood cut and every flag was right in every run, for 8 cents a claim." |
| 9 | Own the capture | "So that's the fix: own the capture. Room tag, one step per wall, a tape at the line, LiDAR for lengths, and whatever's left becomes the tech's checklist." |
| 10 | Close | Read the two lines on screen: "Right wherever there's evidence. Explicit about the rest." Then: "The code's on GitHub. I'd love to talk." Don't skip it. |

## Say it plainly

You measured all of this, so drop the hedges: not "I was kind of right" / "I guess" / "I believe" / "I can imagine it messes up." Xact has no public write API, and a 200 OK doesn't prove a write landed; that's why it reads back. Skip asides about what's off screen or "fake numbers" (the line-item prices are illustrative; only say so if asked).

## Keep straight

- v5 tags **rooms only**. Walls are still counted by the model, which is why the den over-counts.
- On the public photos the model **didn't hallucinate**. It returned no measurement. That's the point: the data isn't there.
- **23** photos (not 27). **13** write repairs in the v5 runs; **60** across all 45 runs.

## If something goes sideways live

- A model call fails: the client retries. If the run dies, open the warm-up run's report.
- No write failures this run (they're random): "no faults this time; the eval repaired 60 across 45 runs."
- The den shows an extra wall: expected, and it's flagged with `? den: confirm wet-wall count`.
- The **bedroom** shows 3 walls (about 1 run in 5): it is *not* flagged and bills $967 instead of $816. Re-run before recording; check step 4 first.
