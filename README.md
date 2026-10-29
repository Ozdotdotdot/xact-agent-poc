# xact-agent-poc

**Prompt:** an agent must enter a water damage estimate into Xact from a phone call transcript and 40 photos. What breaks first, and how do you design around it?

**Answer:** missing information breaks first. I built the agent, staged a water loss in my basement with measured ground truth, and scored five versions over 45 runs. The fix that mattered most wasn't a smarter model. It was **controlling how the photos are captured**.

→ **Deck:** `uv run demo/build.py && xdg-open demo/deck.html` (or `open` on macOS; arrow keys to move, F for fullscreen)

## Results

Every version ran 3 callers × 3 runs and was scored against `data/claim-001/truth.json` (tape heights measured with a tape measure, room areas from a professional flooring measure). Raw rows are in `results/`.

| | v1 one dedupe call, Haiku | v2 one dedupe call, Sonnet | v3 hierarchical | v4 + caller's room descriptions | **v5 guided capture (simulated)** |
|---|---|---|---|---|---|
| Photo → correct room (median) | 39% | 87% | 70% | 91% | **100%** |
| Flood-cut height right | 14/25 | 24/27 | 17/24 | 22/27 | **27/27** |
| Wet-wall count exactly right | 4/27 | 3/27 | 12/27 | 14/27 | **17/27** |
| Expected review flags caught | 26/27 | 26/27 | 24/27 | 27/27 | **27/27** |
| Xact read-back verified | 9/9 | 9/9 | 9/9 | 9/9 | **9/9** |
| Cost per claim (median) | $0.025 | $0.085 | $0.113 | $0.116 | **$0.079** |

Across all 45 runs the read-back caught and repaired **60 silent write failures**.

What else came out of it:
- **0 of 12** public water-damage photos had a measurable water line; the model correctly refused to guess. With a tape measure in frame, readings land within **0.5 in**.
- **The code-owned parts were solid from v1:** review flags and Xact verification. Sorting photos into rooms and walls was the weak link.
- **Splitting work per room (v3)** fixed wall counting: the bedroom went from 4–11 walls to exactly 2 in 8 of 9 runs.
- **Look-alike rooms** (two empty carpeted rooms shot 15 s apart) stayed hard until photos arrived tagged (v5). The photographer, me, mislabeled 3 of my own 23 photos an hour later.
- **Still open:** the L-shaped den over-counts walls even with room tags (3–4 vs. 2). v5 simulates room tags only; one capture step per wall would close it.

## What breaks, and the design around each

**1. Missing information.** Calls and photos rarely contain the measurements an estimate needs.
- A photo measurement only counts with a named reference: outlet ~12–16" AFF, door 80", baseboard, or a visible tape. A transcript fact only counts with a verbatim quote.
- **Code owns the numbers.** Models extract cited facts. Plain Python computes flood-cut height, wall LF, SF and equipment days.
- Missing or contradictory inputs go to a **human review queue** instead of being guessed: a caller's "over a foot" vs. a 6" line in the photos, a room with no photos, a wall length nobody gave.

**2. Context and duplicates.** Forty photos in one call is expensive, and the same wall gets billed again from every angle. The pipeline is hierarchical, so no call sees all 40:

| Stage | Model | Sees |
|---|---|---|
| 0 · Call → facts | Sonnet, 1 call | transcript |
| 1 · Per photo | Haiku, 1 call per photo (~1.2k tokens each) | one photo |
| 2a · Photo → room | Sonnet, 1 text call (**skipped with guided capture**) | photo summaries, capture-time gaps, caller's room descriptions |
| 2b · Room → walls | Sonnet, 1 vision call per room | a thumbnail grid of that room only |
| 3 · Quantities | code | |
| 4 · Write + verify | code | |

Physical cross-checks run in code: water settles at one level per room, so a wall whose line disagrees gets flagged; a wet wall implies a wet floor; a caller's flooring type that doesn't match the photos flags photos of the wrong room.

**3. Silent write failures.** Xact has no public write API, so real integrations go through ESX import, partner APIs or UI automation, and a 200 OK proves nothing. `xact_poc/xact_mock.py` silently drops or corrupts writes. Stage 4 writes, **reads back, diffs, removes corrupted lines and retries** until the estimate matches.

## The real fix: own the capture

Every hard problem above traces back to information the photos never carried. A guided capture flow puts it there: photos tagged by room, one step per wet wall, a tape measure at the line, a LiDAR scan for lengths. Whatever is still unknown (moisture behind walls, unchecked closets) becomes the tech's on-site checklist. The deck has a concept mockup.

## Run it

```bash
git clone https://github.com/Ozdotdotdot/xact-agent-poc && cd xact-agent-poc
uv sync                                         # https://docs.astral.sh/uv/
echo "ZEN_API_KEY=..." > .env                   # OpenCode Zen key

uv run run.py data/claim-001 --transcript 03-overclaim --guided
xdg-open out/claim-001/03-overclaim/report.html

uv run eval.py data/claim-001 --runs 3 --guided --tag mine    # ~$0.75, writes results/eval-mine.json
```

Flags: `--transcript 01-prepared|02-vague|03-overclaim`, `--guided` (photos arrive room-tagged), `--xact-fault-rate 0.3`, `--baseline` (all photos in one Opus call, for comparison), `--photo-model / --dedupe-model / --scope-model`.

## Data

- `data/claim-001/photos/`: 23 photos of a staged basement loss. GPS and all other metadata stripped except capture time.
- `data/claim-001/transcripts/`: three callers describing the same loss: prepared (with numbers), vague (no numbers, unknown source), and overclaiming (a room that wasn't wet, exaggerated depth).
- `data/claim-001/truth.json`: measured water lines, wet-wall counts, room areas, and the flags each transcript should trigger.
- `data/public-samples/`: the 12 public Wikimedia Commons photos behind "0 of 12", what the photo model returned for each, and credits.

## Honest limits

- Line-item codes and prices are **illustrative**, modeled on Xactimate's WTR category. This is not the real price list.
- Xact is mocked.
- One staged claim, three rooms. The eval measures consistency on this case, not general accuracy.
- Guided capture is simulated with ground-truth room tags. The capture app is a mockup.
