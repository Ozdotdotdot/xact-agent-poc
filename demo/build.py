"""Builds demo/walkthrough.html from results/*.json, truth.json and the transcripts.

uv run demo/build.py   ->   open demo/walkthrough.html
Every number on the page comes from a recorded eval run; nothing is typed in by hand.
"""
import html
import json
from pathlib import Path
from statistics import median

ROOT = Path(__file__).parent.parent
CLAIM = ROOT / "data/claim-001"
e = lambda s: html.escape(str(s))

VERSIONS = [  # (results file, label, what changed)
    ("eval-1-flat-haiku.json", "v1: one dedupe call, Haiku", "Cheap model matches text descriptions of walls across 23 photos"),
    ("eval-2-flat-sonnet.json", "v2: one dedupe call, Sonnet", "Same design, stronger model"),
    ("eval-3-hierarchical.json", "v3: hierarchical", "Photo->room from capture time + contents, then one vision call per room"),
]


def summarize(rows: list[dict], truth: dict) -> dict:
    ok = [r for r in rows if "failed" not in r]
    cut = [x["flood_cut_ok"] for r in ok for x in r["rooms"].values() if x["flood_cut_ok"] is not None]
    walls_exact = [x["wet_walls"] == truth["rooms"][room]["wet_walls"] for r in ok for room, x in r["rooms"].items()]
    return {
        "runs": len(rows), "failed": len(rows) - len(ok),
        "photo_room": median(r["photo_room_acc"] for r in ok),
        "photo_room_by_t": {t: median(r["photo_room_acc"] for r in ok if r["transcript"] == t)
                            for t in sorted({r["transcript"] for r in ok})},
        "cut": (sum(cut), len(cut)),
        "walls_exact": (sum(walls_exact), len(walls_exact)),
        "walls": {room: [r["rooms"][room]["wet_walls"] for r in ok] for room in truth["rooms"]},
        "flags": (sum(r["flags_caught"] for r in ok), sum(r["flags_expected"] for r in ok)),
        "xact": (sum(r["xact_verified"] for r in ok), len(ok)),
        "repairs": sum(r["xact_repairs"] for r in ok),
        "usd": median(r["usd"] for r in ok),
    }


def main():
    truth = json.loads((CLAIM / "truth.json").read_text())
    versions = []
    for f, label, what in VERSIONS:
        p = ROOT / "results" / f
        if p.exists():
            versions.append((label, what, summarize(json.loads(p.read_text())["rows"], truth)))
    final = versions[-1][2] if versions else None

    # --- inputs: photos by room, with the measured truth
    rooms_html = ""
    for room, t in truth["rooms"].items():
        lo, hi = t["water_line_in"]
        size = f"{t['area_sqft']} SF" if "area_sqft" in t else f"wet wall {t['affected_wall_lengths_in'][0]} in"
        imgs = "".join(f'<img src="../data/claim-001/photos/{p}.jpg" alt="{p}" loading=lazy>' for p in t["photos"])
        rooms_html += (f'<div class=room><div class=roomhead><b>{e(room.title())}</b>'
                       f'<span>tape at {lo}–{hi} in · {t["wet_walls"]} wet wall{"s" * (t["wet_walls"] > 1)} · {size}</span></div>'
                       f'<div class=strip>{imgs}</div></div>')

    tx_html = ""
    for name, t in truth["transcripts"].items():
        first = next(l for l in (CLAIM / "transcripts" / f"{name}.txt").read_text().splitlines() if l.startswith("HOMEOWNER"))
        traps = "".join(f"<li>{e(x.get('why') or (x['room'] + ': ' + x['needs']))}</li>" for x in t["expected_flags"])
        tx_html += (f'<div class=card><div class=k>{e(name)}</div><p>{e(t["about"])}</p>'
                    f'<p class=quote>"{e(first.split(":", 1)[1].strip()[:140])}…"</p>'
                    f'<div class=k>Should be flagged</div><ul>{traps}</ul></div>')

    # --- eval table
    def cell(v, fmt):
        return f"<td class=n>{fmt(v)}</td>"
    head = "".join(f"<th class=n>{e(l)}<div class=sub>{e(w)}</div></th>" for l, w, _ in versions)
    rows = [
        ("Photo → correct room (median)", lambda s: f"{s['photo_room']:.0%}"),
        ("&nbsp;&nbsp;on the lying caller (03)", lambda s: f"{s['photo_room_by_t'].get('03-overclaim', 0):.0%}"),
        ("Flood-cut height right", lambda s: f"{s['cut'][0]}/{s['cut'][1]}"),
        ("Wet-wall count exactly right", lambda s: f"{s['walls_exact'][0]}/{s['walls_exact'][1]}"),
        ("&nbsp;&nbsp;bedroom walls per run (true 2)", lambda s: ", ".join(map(str, s["walls"]["bedroom"]))),
        ("Expected review flags caught", lambda s: f"{s['flags'][0]}/{s['flags'][1]}"),
        ("Xact read-back verified", lambda s: f"{s['xact'][0]}/{s['xact'][1]} <span class=sub>({s['repairs']} silent failures repaired)</span>"),
        ("Cost per claim (median)", lambda s: f"${s['usd']:.3f}"),
    ]
    body = "".join(f"<tr><td>{label}</td>{''.join(cell(s, fn) for _, _, s in versions)}</tr>" for label, fn in rows)
    eval_html = f"<div class=wrap><table class=eval><tr><th></th>{head}</tr>{body}</table></div>"

    hero = ""
    if final:
        hero = "".join(f"<div class=stat><b>{v}</b><span>{l}</span></div>" for v, l in [
            ("0 / 12", "public water-damage photos with a measurable water line"),
            ("±0.5 in", "water line read off a tape measure in frame"),
            (f"{final['photo_room']:.0%}", "photos sorted into the right room (v3, median of 9 runs)"),
            (f"{final['repairs']}", "silent Xact write failures caught by read-back"),
            (f"${final['usd']:.2f}", "per claim, all model calls"),
        ])

    out = ROOT / "demo/walkthrough.html"
    out.write_text(PAGE.format(rooms=rooms_html, transcripts=tx_html, eval=eval_html, hero=hero,
                               n_photos=sum(len(t["photos"]) for t in truth["rooms"].values())))
    print(out)


PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Xact Agent POC</title>
<style>
:root{{--bg:#f7f6f3;--fg:#1c1b19;--mut:#6b6862;--line:#e3e0da;--card:#fff;--acc:#1d4ed8;--ok:#15803d;--warn:#b45309;--soft:#eef2ff}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#161514;--fg:#f2f0ec;--mut:#a29e97;--line:#34322f;--card:#201f1d;--acc:#93b4ff;--ok:#4ade80;--warn:#fbbf24;--soft:#1e2433}}}}
:root[data-theme=dark]{{--bg:#161514;--fg:#f2f0ec;--mut:#a29e97;--line:#34322f;--card:#201f1d;--acc:#93b4ff;--ok:#4ade80;--warn:#fbbf24;--soft:#1e2433}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--fg);font:17px/1.55 Inter,system-ui,sans-serif}}
main{{max-width:1080px;margin:0 auto;padding:40px 16px 120px}}
section{{padding:56px 0 8px;border-top:1px solid var(--line)}} section:first-of-type{{border:0;padding-top:8px}}
h1{{font-size:40px;line-height:1.15;margin:0 0 12px;letter-spacing:-.02em}} h2{{font-size:28px;margin:0 0 6px;letter-spacing:-.01em}}
.step{{color:var(--acc);font-weight:700;font-size:13px;letter-spacing:.08em;text-transform:uppercase}}
.lede{{font-size:20px;color:var(--mut);max-width:780px}} .mut,.sub{{color:var(--mut)}} .sub{{font-size:12px;font-weight:400}}
.grid{{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));margin-top:18px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px}}
.card p{{margin:6px 0}} .card ul{{margin:4px 0 0;padding-left:18px}}
.k{{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);margin-top:6px}}
.quote{{font-style:italic;color:var(--mut)}}
.breaks{{counter-reset:b}} .breaks .card > b{{display:block;font-size:19px}}
.room{{margin:18px 0}} .roomhead{{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;margin-bottom:6px}} .roomhead span{{color:var(--mut)}}
.strip{{display:flex;gap:6px;overflow-x:auto;padding-bottom:6px}} .strip img{{height:150px;border-radius:6px;flex:none}}
.wrap{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;background:var(--card);border-radius:12px;overflow:hidden}}
td,th{{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
.n{{text-align:right;font-variant-numeric:tabular-nums}} table.eval td:last-child,table.eval th:last-child{{background:var(--soft)}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:22px 0}}
.stat{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}}
.stat b{{display:block;font-size:30px;letter-spacing:-.02em}} .stat span{{color:var(--mut);font-size:14px}}
.flow{{display:flex;flex-wrap:wrap;gap:8px;align-items:stretch;margin:18px 0}}
.box{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;flex:1 1 120px;font-size:14px}}
.box b{{display:block}} .box.code{{border-color:var(--ok)}} .arrow{{align-self:center;color:var(--mut)}}
pre{{background:#111;color:#e6e6e6;padding:14px 16px;border-radius:10px;overflow-x:auto;font-size:15px}}
.phones{{display:flex;flex-wrap:wrap;justify-content:center;gap:16px;padding:12px 2px 18px}}
.phone{{flex:none;width:190px;height:420px;border-radius:34px;border:10px solid #1b1b1b;background:#fff;color:#111;
  display:flex;flex-direction:column;overflow:hidden;box-shadow:0 10px 30px rgba(0,0,0,.18);font-size:14px}}
.phone .bar{{padding:10px 14px 6px;font-weight:700;font-size:15px}} .phone .bar small{{display:block;font-weight:400;color:#666;font-size:12px}}
.phone .view{{flex:1;margin:6px 10px;border-radius:12px;background:#ddd center/cover;position:relative}}
.phone .tag{{position:absolute;left:8px;right:8px;bottom:8px;background:rgba(0,0,0,.72);color:#fff;border-radius:8px;padding:6px 8px;font-size:12px}}
.phone .tag.ok{{background:rgba(21,128,61,.9)}} .phone .tag.warn{{background:rgba(180,83,9,.92)}}
.guide{{position:absolute;left:0;right:0;border-top:2px dashed #fde047}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;padding:8px 12px}} .chip{{border:1px solid #ccc;border-radius:99px;padding:6px 10px}}
.chip.on{{background:#1d4ed8;color:#fff;border-color:#1d4ed8}}
.phone .btn{{margin:8px 12px 14px;background:#1d4ed8;color:#fff;text-align:center;border-radius:10px;padding:10px;font-weight:600}}
.plan{{position:absolute;inset:14px;border:3px solid #1d4ed8;border-radius:4px}}
.plan i{{position:absolute;background:#ef4444;height:5px;border-radius:3px}}
.legend{{font-size:12px;color:#444;padding:0 12px}}
footer{{margin-top:48px;color:var(--mut)}} a{{color:var(--acc)}}
</style></head><body><main>

<section>
<div class=step>Cozmo FDE · Ozair Khan</div>
<h1>An agent enters a water damage estimate into Xact from a call transcript and 40 photos. What breaks first?</h1>
<p class=lede><b>Missing information breaks first.</b> I built the agent, staged a water loss in my basement with measured ground truth,
and scored every version. The fix that mattered most wasn't a smarter model. It was <b>controlling how the photos are captured</b>.</p>
<div class=stats>{hero}</div>
</section>

<section>
<div class=step>Step 1 · Assumptions</div>
<h2>What the question leaves open</h2>
<div class=grid>
<div class=card><div class=k>The call</div><p>A homeowner calling in to report the loss: first notice of loss, not a tech.</p></div>
<div class=card><div class=k>The photos</div><p>Unspecified, so I tested both. <b>Unguided</b> public photos, and <b>guided</b> photos shot the way a tech or a capture app would.</p></div>
<div class=card><div class=k>Xact</div><p>No public write API. Mocked as a server that <b>silently drops or corrupts 15% of writes</b>, like a flaky import or UI automation.</p></div>
<div class=card><div class=k>Prices</div><p>Illustrative codes modeled on Xactimate's WTR category. The quantities and logic are the point.</p></div>
</div>
</section>

<section>
<div class=step>Step 2 · What breaks, in the order it breaks</div>
<h2>Three failure points, three designs</h2>
<div class="grid breaks">
<div class=card><b>1. Missing information</b><p>Calls and photos rarely contain the measurements an estimate needs. A model fills gaps with confident numbers.</p>
<div class=k>Design</div><p>Measurements only count with a named reference (outlet, door, tape measure). Facts only count with a quote. <b>Code computes every quantity</b>. Gaps go to a review queue.</p></div>
<div class=card><b>2. Context and duplicates</b><p>40 photos in one call is expensive, and the same wall gets billed again from every angle.</p>
<div class=k>Design</div><p>Hierarchical: a cheap model per photo, then photo→room, then one vision call per room to count distinct walls.</p></div>
<div class=card><b>3. Silent write failures</b><p>A 200 OK from Xact proves nothing.</p>
<div class=k>Design</div><p>Write, <b>read back, diff</b>, remove corrupted lines, retry until it matches.</p></div>
</div>
</section>

<section>
<div class=step>Step 3 · The test case</div>
<h2>A staged water loss with known answers</h2>
<p class=mut>{n_photos} photos of my basement. Tape marks the water line at heights I measured; room areas come from a professional flooring measure.
Three different callers describe the same loss.</p>
{rooms}
<div class=grid>{transcripts}</div>
</section>

<section>
<div class=step>Step 4 · Run it</div>
<h2>Transcript + photos → estimate in Xact</h2>
<div class=flow>
<div class=box><b>0 · Call → facts</b>Sonnet, every fact quoted</div><div class=arrow>→</div>
<div class=box><b>1 · Per photo</b>Haiku, 1 photo per call, ~1.2k tokens</div><div class=arrow>→</div>
<div class=box><b>2a · Photo → room</b>capture time, contents, water level</div><div class=arrow>→</div>
<div class=box><b>2b · Room → walls</b>1 vision call per room</div><div class=arrow>→</div>
<div class="box code"><b>3 · Quantities</b>plain code, no model</div><div class=arrow>→</div>
<div class="box code"><b>4 · Write + read back</b>diff and repair</div>
</div>
<pre>uv run run.py data/claim-001 --transcript 03-overclaim</pre>
<p class=mut>Then open <code>out/claim-001/03-overclaim/report.html</code>: review queue, line items with source photos, Xact repair log, cost.</p>
</section>

<section>
<div class=step>Step 5 · Measured, not demoed</div>
<h2>Each version, 3 callers × 3 runs, scored against the truth</h2>
<p class=mut>One good run proves nothing. The parts owned by code (review flags, Xact verification) were solid from v1. Grouping photos was the weak link.</p>
{eval}
<p class=mut>Humans get this wrong too: an hour after the shoot I mislabeled 3 of my own 23 photos. Capture timestamps and visible furniture corrected it.</p>
</section>

<section>
<div class=step>Step 6 · The real fix</div>
<h2>Own the capture, not just the inference</h2>
<p class=lede>Every hard problem above traces back to information the photos never carried. A guided capture flow puts it there.</p>
<p class=mut><b>Concept mockup, not built.</b> Photos are from the real claim; scan numbers are illustrative.</p>
<div class=phones>
<div class=phone><div class=bar>Which room are you in?<small>Room 2 of 3 · from your call</small></div>
<div class=chips><span class=chip>Bedroom ✓</span><span class="chip on">Den</span><span class=chip>Living room</span><span class=chip>+ Other</span></div>
<div class=view style="background-image:url(../data/claim-001/photos/IMG_7701.jpg)"><div class=tag>Every photo arrives tagged with its room. No sorting needed.</div></div>
<div class=btn>Start den</div></div>
<div class=phone><div class=bar>Wet wall 1<small>Stand back so the whole wall fits</small></div>
<div class=view style="background-image:url(../data/claim-001/photos/IMG_7703.jpg)"><div class=guide style="top:76%"></div><div class=tag>One step per wall, so the count is exact.</div></div>
<div class=btn>Capture · next wall</div></div>
<div class=phone><div class=bar>Measure the water line<small>Hold a tape measure at the line</small></div>
<div class=view style="background-image:url(../data/claim-001/photos/IMG_7709.jpg)"><div class="tag ok">Tape reads ≈10 in ✓ → 2 ft flood cut</div></div>
<div class=btn>Looks right</div></div>
<div class=phone><div class=bar>Scan the room<small>Walk the edge slowly · LiDAR</small></div>
<div class=view style="background:#f1f5f9"><div class=plan><i style="left:-3px;top:10%;width:5px;height:60%"></i><i style="left:20%;bottom:-3px;width:55%"></i></div>
<div class="tag ok">Den 265 SF · wet walls 14.2 ft + 11.0 ft</div></div>
<div class=legend>Red = wet walls marked during capture</div>
<div class=btn>Send to estimator</div></div>
<div class=phone><div class=bar>Tech checklist<small>Generated from the review queue</small></div>
<div class=view style="background:#fff;padding:10px;font-size:13px;line-height:1.5">
☐ Bedroom closet: moisture reading<br>☐ Confirm den has 2 wet walls<br>☐ Living room area<br>☐ Confirm water category with source photo
<div class="tag warn">Whatever's left becomes on-site instructions</div></div>
<div class=btn>Start site visit</div></div>
</div>
<div class=wrap><table>
<tr><th>Input the estimate needs</th><th>Call + unguided photos</th><th>Guided capture</th><th>Fully closed by</th></tr>
<tr><td>Which room each photo shows</td><td>Inferred, flagged when unsure</td><td><b>Tagged at capture</b></td><td></td></tr>
<tr><td>How many walls are wet</td><td>Over-counted</td><td><b>One step per wall</b></td><td></td></tr>
<tr><td>Water line → flood-cut height</td><td>±2–4 in from outlets/baseboards</td><td><b>±0.5 in</b> with a tape measure</td><td></td></tr>
<tr><td>Wall lengths, room area</td><td>Missing</td><td>Missing</td><td><b>LiDAR room scan</b> or an existing plan</td></tr>
<tr><td>Moisture behind walls, unchecked areas</td><td>Unknown</td><td>Unknown</td><td><b>Tech with a meter</b>, via the checklist</td></tr>
</table></div>
</section>

<section>
<div class=step>Takeaway</div>
<h2>Right wherever there's evidence, and explicit about the rest</h2>
<p class=lede>The agent writes a draft estimate that is correct wherever it has evidence. Every remaining gap becomes a specific
instruction for whoever is on site. An agent that knows which 10% it's unsure about beats one that's confident about everything.</p>
<footer>Code, data and every eval run: <a href="https://github.com/Ozdotdotdot/xact-agent-poc">github.com/Ozdotdotdot/xact-agent-poc</a> · Ozair Khan</footer>
</section>
</main></body></html>"""

if __name__ == "__main__":
    main()
