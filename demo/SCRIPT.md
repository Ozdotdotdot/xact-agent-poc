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

## The story in one breath

Public photos don't carry the measurements an estimate needs, so I staged a loss where I know the answers. I stress-tested it with three callers and iterated five versions. Better models helped, but the step that kept failing was knowing which room a photo is from, and that's a capture problem. So the fix is to own the capture.

## Slide by slide

| # | Slide | Say |
|---|---|---|
| 1 | What breaks first? | "In my Loom I said missing information breaks first. I built it to find out." |
| 2 | 0/12 public photos | "I started with 12 public water-damage photos. Not one had a water line the model could measure, and it said so instead of making up a number. The information just isn't in the photos." |
| 3 | Staged water loss | "So I staged my own. Bedroom, den, living room, tape at three heights I measured, 23 photos with duplicates and different angles. Now I know the right answer for every room." |
| 4 | Three callers | "Then three calls about the same basement: one prepared, one vague, one exaggerating. Each should trigger specific flags, and the guided runs caught every one." |
| 5 | Pipeline | Walk the boxes left to right: "Read the call and pull out every fact with a quote. Describe each photo with a cheap model, one photo per call. Sort photos into rooms. Count the wet walls in each room by looking at that room's photos together. Then code, not a model, computes the estimate, writes it to Xact and reads it back to catch silent failures." |
| 6 | Live run | Switch to the terminal and paste the one-line command from the slide. The steps are numbered 1–6, matching the pipeline slide. Point at: step 3 *skipped* (photos came tagged); step 4 wall counts; step 5 the **line items** (only rooms with measurements get billed: the overclaimer gave only the bedroom size, so den and living room are *held* and show up as `?` lines instead), the `?` lines (no photos of the office, "over a foot" vs ~5 in); step 6 the rounds catching dropped or corrupted writes until it verifies. About 8–9¢. |
| 7 | Bar chart | "I iterated five times, nine runs each, scored against the truth. v1 and v2 hand every photo description to one model to group, and the stronger model does much better. v3 split it per room, which fixed wall counting but made room sorting worse. v4 gave the sorter what the caller said about each room. That helps when the caller is honest and hurts when they're not. v5 is the only change that isn't a model change: the photos arrive tagged with their room. 100%, even with the lying caller." |
| 8 | 27/27 · 27/27 · 9/9 · $0.08 | "With that one change, every flood cut and every flag was right in every run, for 8 cents a claim." |
| 9 | Wall counts | "What's still open: the L-shaped den gets over-counted. It does get flagged for a human, and the capture flow fixes it with one step per wall." |
| 10 | Own the capture | Left to right: "room tag, one step per wall, tape at the line, a LiDAR scan for lengths, and whatever's left becomes the tech's checklist." |
| 11 | What closes each gap | "Capture closes most of it. A tech with a meter closes the rest." |
| 12 | Close | "It's right wherever it has evidence and explicit about the rest. The code and every run are public. I'd love to talk." |

## Keep straight

- v5 tags **rooms only**. Walls are still counted by the model, which is why the den over-counts.
- On the public photos the model **didn't hallucinate**. It returned no measurement. That's the point: the data isn't there.
- **23** photos (not 27). **13** write repairs in the v5 runs; **60** across all 45 runs.

## If something goes sideways live

- A model call fails: the client retries. If the run dies, open the warm-up run's report.
- No write failures this run (they're random): "no faults this time; the eval repaired 60 across 45 runs."
- A room shows an extra wall (den or bedroom): expected run to run, and it's flagged with `? <room>: confirm wet-wall count`.
