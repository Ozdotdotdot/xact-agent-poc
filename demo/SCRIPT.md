# Recording script (~2.5 min)

## Before you hit record

```bash
git clone https://github.com/Ozdotdotdot/xact-agent-poc && cd xact-agent-poc
curl -LsSf https://astral.sh/uv/install.sh | sh      # if uv isn't installed
uv sync
echo "ZEN_API_KEY=<your OpenCode Zen key>" > .env

# warm-up run: caches the per-photo results so the live run is fast and you've seen it work once
uv run run.py data/claim-001 --transcript 03-overclaim

uv run demo/build.py
xdg-open demo/walkthrough.html
```

Have two windows ready: **browser** (walkthrough page) and **terminal** (in the repo, font size up).
To show the photo stage running live too, delete the cache before recording:
`rm out/claim-001/observations.*.json` (adds ~30s and about 3¢).

## The run, top to bottom

| # | Screen | Say |
|---|---|---|
| 1 | Walkthrough, top | "My Loom said missing information breaks first. I built the agent to test that, and the data agreed. Here's what I found." Point at the stats. |
| 2 | Step 1 · Assumptions | "The question doesn't say who takes the photos, so I tested both. And Xact has no public write API, so I mocked it as a server that silently corrupts 15% of writes." |
| 3 | Step 2 · Three failure points | One sentence each: missing info, so code owns the numbers and gaps go to a human. Duplicates, so hierarchical dedupe. Silent writes, so read back. |
| 4 | Step 3 · Test case | "I staged a water loss in my basement. Tape marks the water line at heights I measured, so I know the right answer. Three callers: prepared, vague, and one who lies." |
| 5 | **Terminal**: `uv run run.py data/claim-001 --transcript 03-overclaim` | Narrate as it prints: facts with quotes, per-photo calls on a cheap model, photos sorted into rooms, walls counted per room, quantities in plain code, write to Xact, **read back, repair**. |
| 6 | **Browser**: `out/claim-001/03-overclaim/report.html` | Review queue: "The caller said over a foot; the photos show six inches. They claimed a home office that's not in any photo, so nothing gets billed there." Then the Xact repair rounds, then the cost. |
| 7 | Step 5 · Eval table | "One good run proves nothing, so every version ran 9 times against the truth. The code-owned parts were solid from day one. Sorting photos into rooms and walls was the weak link: 39% → 87% → v3." Then: "I mislabeled 3 of my own photos an hour after taking them." |
| 8 | Step 6 · Capture mockup | "So the real fix isn't a smarter model, it's owning the capture: room-tagged photos, one step per wall, a tape at the line, a LiDAR scan for lengths. Whatever's left becomes the tech's on-site checklist." |
| 9 | Takeaway | "It's right wherever it has evidence and explicit about the rest. About 10 cents per claim. The code and every eval run are public. I'd love to talk." |

## If something goes sideways live

- A model call fails or times out: the client retries. If the run dies, show the warm-up run's report instead. It's the same pipeline.
- Numbers differ slightly from the eval table: expected. Say "that's why I ran it 9 times."
