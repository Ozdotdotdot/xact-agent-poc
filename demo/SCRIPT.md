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
To show the photo stage running live too, run `rm out/claim-001/observations.*.json` first (adds ~30 s and about 3¢).

## Slide by slide

The slides carry the numbers. You say the "why" in one or two lines.

| # | Slide | Say |
|---|---|---|
| 1 | What breaks first? | "In my Loom I said missing information breaks first. I built it to find out." |
| 2 | Missing information · 0/12 | "Public damage photos almost never show a measurable water line. Put a tape measure in frame and it reads within half an inch." |
| 3 | Staged water loss | "So I staged one. Tape at heights I measured, so I know the right answer for every room." |
| 4 | Three callers | "Same photos, three callers. Each one hides something the agent should catch." |
| 5 | Models look, code does the math | "No call sees all 40 photos. Models only extract, and every fact needs a quote. Code computes every quantity, writes to Xact and reads it back. Gaps go to a person." |
| 6 | Live run | Switch to the terminal and run the command on the slide. Narrate as it prints: facts → photos → walls per room → write → **read back, repair**. Then open the report: "It caught both lies, 'over a foot' versus 6 inches and an office with no photos. Here's the repair. About 8 cents." |
| 7 | Photos sorted into the right room | "Every version ran 9 times against the truth. Better models got this to 91%, but only 35% on the caller who lies. Tag photos by room at capture and it's 100%." |
| 8 | 27/27 · 27/27 · 9/9 · $0.08 | "With that one change, every flood cut was right in every run." |
| 9 | Wet walls counted | "One thing is still open: the L-shaped den gets over-counted. That's why the next step is capture, not a bigger model." |
| 10 | Own the capture | Walk left to right: "room tag, one step per wall, tape at the line, a LiDAR scan for lengths, and whatever's left becomes the tech's checklist." |
| 11 | What closes each gap | "Capture closes most of it. A tech with a meter closes the rest." |
| 12 | Close | "It's right wherever it has evidence and explicit about the rest. The code and every run are public. I'd love to talk." |

## Numbers to keep straight

- **13** silent write failures repaired is the v5 runs only (slide 8). Across all 45 runs it's **60**.
- Cost is **$0.08** per claim with guided capture. The best version without it cost $0.12.

## If something goes sideways live

- A model call fails: the client retries. If the run dies, open the warm-up run's report. It's the same pipeline.
- No write failures this run (they're random): "no faults this time; the eval repaired 60 across 45 runs."
- Numbers differ a little from the slides: expected. "That's why I ran it 9 times."
