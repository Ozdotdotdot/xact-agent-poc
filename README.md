# xact-agent-poc

**Prompt:** an agent must enter a water damage estimate into Xact from a phone call transcript and 40 photos. What breaks first, and how do you design around it?

This is a working proof of concept of my answer.

## What breaks, and the design around each

**1. The information gap breaks first.** The call and the photos rarely contain the measurements an estimate needs. An agent that fills that gap with plausible numbers is worse than no agent at all.
- Each photo yields observations, and a measurement is only accepted if the model names the reference object it measured from: outlet box ~12–16" AFF, door 80", baseboard 3–5", or a visible tape.
- Transcript facts are only accepted with a verbatim quote.
- **Code owns the numbers.** The models extract cited facts, and plain Python computes quantities: flood-cut height, wall LF, SF, equipment days. Missing or contradictory inputs go to a **human review queue** instead of being guessed. Example: the homeowner says "maybe an inch" while the photos show a 9" wick line.

**2. Context and cost break second.** Forty full-resolution photos in one call is expensive, and the model loses track of what it has already counted, so the same wall gets billed again from another angle.
- Stage 1 runs a cheap vision model on **one photo per call**, downscaled to ~1.2k tokens.
- Stage 2 is a text-only dedupe that groups observations of the same physical surface. Code merges them: median of the estimates, union of the damage, list of supporting photos.

**3. The write to Xact breaks silently.** There's no open write API, so real integrations go through ESX import, a partner API, or driving the UI. A 200 OK proves nothing.
- `xact_mock.py` is a stand-in that silently drops or corrupts 15% of writes.
- Stage 4 writes, **reads back, diffs, removes corrupted lines and retries** until the estimate matches.

## Pipeline

```
transcript ─────────────────────────────┐
                                        ▼
40 photos ─► [1] cheap vision, ─► [2] dedupe ─► [3] cited facts + code-computed ─► [4] write ─► read back ─► diff/repair
             1 photo per call     (text only)       line items                         │
                                                          │                            ▼
                                                          └──► human review queue    report.html
```

A naive baseline (all photos plus the transcript in one frontier-model call) runs alongside for comparison: cost, duplicates, and how often it says "I don't know".

## Run

```bash
echo "ZEN_API_KEY=..." > .env       # OpenCode Zen key
uv run run.py data/claim-001 --baseline
open out/claim-001/report.html
```

Swap models per stage with `--photo-model`, `--dedupe-model`, `--scope-model`.

## Results

_In progress._

## Honest limits

- Line-item codes and prices are **illustrative**, modeled on Xactimate's WTR category. This is not the real price list.
- Xact is mocked. A production version would target ESX import or a partner integration.
- Wall lengths without a sketch are approximated and labeled as such in each line item's basis.
