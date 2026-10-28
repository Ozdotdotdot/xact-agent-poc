"""Single-file HTML review page: what the agent did, what it wants a human to check, what it cost."""
import base64
import html
import io
from pathlib import Path

from PIL import Image, ImageOps

e = lambda s: html.escape(str(s))


def thumbs(photo_dir: Path) -> dict[str, str]:
    out = {}
    for p in sorted(photo_dir.iterdir()):
        try:
            img = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
        except Exception:
            continue
        img.thumbnail((240, 240))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=70)
        out[p.name] = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    return out


def sources_html(sources: list[str], th: dict[str, str]) -> str:
    parts = []
    for s in sources:
        names = [n for n in th if n in s]
        parts.append(" ".join(f'<img src="{th[n]}" title="{e(n)}">' for n in names) if names
                     else f"<div class=src>{e(s)}</div>")
    return "".join(parts)


def write(r: dict, claim_dir: Path, path: Path):
    th = thumbs(claim_dir / "photos")
    sc, dd, wr, bl = r["scope"], r["dedupe"], r["write"], r["baseline"]
    pipeline_cost = sum(v["usd"] for k, v in r["cost"].items() if k != "baseline")

    items = "".join(
        f"<tr><td>{e(i['room'])}</td><td><code>{e(i['code'])}</code><br><small>{e(i['desc'])}</small></td>"
        f"<td class=n>{i['qty']} {e(i['unit'])}</td><td class=n>${i['total']:,.2f}</td>"
        f"<td><small>{e(i['note'])}</small>{sources_html(i['sources'], th)}</td></tr>"
        for i in sc["line_items"])
    queue = "".join(
        f"<li><b>{e(q['room'])}</b>: {e(q['needs'])}<div class=why>{e(q['why'])}</div>"
        f"{sources_html(q['sources'], th)}</li>" for q in sc["review_queue"])
    surfaces = "".join(
        f"<tr><td>{e(s['key'])}</td><td class=n>{len(s['photos'])}</td>"
        f"<td class=n>{e(s['water_line_in'] if s['water_line_in'] is not None else '-')}</td>"
        f"<td>{''.join(f'<img src={th[p]} title={e(p)}>' for p in s['photos'] if p in th)}</td></tr>"
        for s in dd["surfaces"] if s["surface"] != "note")
    f = sc["facts"]
    fact_rows = []
    for label, key in (("Cause", "cause"), ("Water category", "water_source_category"),
                       ("Reported depth", "reported_water_depth_in"), ("Hours before mitigation", "hours_before_mitigation")):
        v = f.get(key) or {}
        fact_rows.append(f"<tr><td>{label}</td><td>{e(v.get('value', '-'))}</td><td class=src>{e(v.get('quote') or '')}</td></tr>")
    for r in f.get("rooms", []):
        dims = r.get("area_sqft") and f"{r['area_sqft']} SF" or (r.get("length_ft") and f"{r['length_ft']} x {r['width_ft']} ft") \
            or (r.get("affected_wall_lengths_ft") and f"wet wall {r['affected_wall_lengths_ft']} ft") or "unknown"
        fact_rows.append(f"<tr><td>Room: {e(r['room'])}</td><td>{e(dims)}, {e(r.get('flooring') or '?')}</td>"
                         f"<td class=src>{e(r.get('dims_quote') or r.get('wall_lengths_quote') or '')}</td></tr>")
    facts_html = "".join(fact_rows)
    rooms_html = "".join(
        f"<tr><td><b>{e(r)}</b></td><td class=n>{len(v['photos'])}</td><td class=n>{v['wet_walls']}</td>"
        f"<td>{''.join(f'<img src={th[p]} title={e(p)}>' for p in v['photos'] if p in th)}</td></tr>"
        for r, v in dd.get("rooms", {}).items())
    rounds = "".join(
        f"<tr><td>{x['round']}</td><td class=n>{x['written']}</td><td class=n>{x['verified']}</td>"
        f"<td>{e(x['corrupted_removed']) if x['corrupted_removed'] else '-'}</td><td class=n>{x['missing']}</td></tr>"
        for x in wr["rounds"])
    costs = "".join(
        f"<tr><td>{e(k)}</td><td>{e(v['model'])}</td><td class=n>{v['calls']}</td>"
        f"<td class=n>{v['in']:,}</td><td class=n>{v['out']:,}</td><td class=n>${v['usd']:.4f}</td></tr>"
        for k, v in r["cost"].items())
    compare = ""
    if bl:
        compare = f"""<h2>Versus the naive baseline</h2>
<table><tr><th></th><th>Pipeline</th><th>One frontier call</th></tr>
<tr><td>Cost</td><td class=n>${pipeline_cost:.4f}</td><td class=n>${r['cost']['baseline']['usd']:.4f}</td></tr>
<tr><td>Line items</td><td class=n>{len(sc['line_items'])}</td><td class=n>{len(bl['line_items'])}</td></tr>
<tr><td>Duplicate room/code pairs</td><td class=n>0</td><td class=n>{bl['duplicate_room_code_pairs']}</td></tr>
<tr><td>Items flagged for a human</td><td class=n>{len(sc['review_queue'])}</td><td class=n>0 (it never says "I don't know")</td></tr>
<tr><td>Estimate total</td><td class=n>${sc['estimate_total']:,.2f}</td><td class=n>${bl['estimate_total']:,.2f}</td></tr></table>
<details><summary>Baseline line items</summary><table>{''.join(
    f"<tr><td>{e(i['room'])}</td><td><code>{e(i['code'])}</code></td><td class=n>{e(i['qty'])} {e(i.get('unit',''))}</td><td><small>{e(i.get('basis',''))}</small></td></tr>"
    for i in bl['line_items'])}</table></details>"""

    path.write_text(f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Estimate Review</title>
<style>
:root{{--bg:#fafaf9;--fg:#1c1917;--mut:#78716c;--line:#e7e5e4;--card:#fff;--warn:#b45309;--ok:#15803d}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1c1917;--fg:#f5f5f4;--mut:#a8a29e;--line:#44403c;--card:#292524;--warn:#fbbf24;--ok:#4ade80}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;max-width:1100px;margin:0 auto;padding:24px 16px}}
h1{{margin:0 0 4px}} h2{{margin-top:36px;border-bottom:1px solid var(--line);padding-bottom:6px}}
.sub{{color:var(--mut)}} table{{border-collapse:collapse;width:100%;background:var(--card)}}
td,th{{border-bottom:1px solid var(--line);padding:8px;text-align:left;vertical-align:top}}
.n{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
img{{height:56px;border-radius:4px;margin:2px}} img:hover{{height:200px}}
.src{{font-size:12px;color:var(--mut)}} .why{{color:var(--mut);font-size:14px}}
.funnel{{display:flex;gap:8px;flex-wrap:wrap}} .funnel div{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 16px}}
.funnel b{{display:block;font-size:28px}} ul.q li{{margin-bottom:12px;border-left:3px solid var(--warn);padding-left:10px;list-style:none}}
.ok{{color:var(--ok)}} .bad{{color:var(--warn)}} .wrap{{overflow-x:auto}}
</style></head><body>
<h1>Water loss estimate: {e(r['claim'])}</h1>
<div class=sub>Transcript + {len(r['observations'])} photos → mock Xact. Pipeline cost ${pipeline_cost:.4f}.</div>
<h2>Funnel</h2><div class=funnel>
<div><b>{len(r['observations'])}</b>photos</div><div><b>{dd['raw_observations']}</b>damaged-surface observations</div>
<div><b>{dd['unique_surfaces']}</b>unique surfaces after dedupe</div><div><b>{len(sc['line_items'])}</b>line items written</div>
<div><b class=bad>{len(sc['review_queue'])}</b>flagged for a human</div>
<div><b class={'ok' if wr['verified'] else 'bad'}>{'✓' if wr['verified'] else '✗'}</b>Xact read-back</div></div>
<h2>What the call said (every fact quoted)</h2><div class=wrap><table><tr><th>Fact</th><th>Value</th><th>Quote</th></tr>{facts_html}</table></div>
<h2>Photos sorted into rooms</h2><div class=wrap><table><tr><th>Room</th><th class=n>Photos</th><th class=n>Wet walls</th><th>Photos</th></tr>{rooms_html}</table></div>
<h2>Needs a human ({len(sc['review_queue'])})</h2><ul class=q>{queue or '<li>Nothing flagged.</li>'}</ul>
<h2>Line items: ${sc['estimate_total']:,.2f}</h2><div class=wrap><table>
<tr><th>Room</th><th>Code</th><th class=n>Qty</th><th class=n>Total</th><th>Basis and sources</th></tr>{items}</table></div>
<p class=src>Codes are illustrative, modeled on Xactimate's WTR category. Not the real price list.</p>
<h2>Unique surfaces (after dedupe)</h2><div class=wrap><table><tr><th>Surface</th><th class=n>Photos</th><th class=n>Water line (in)</th><th>Seen in</th></tr>{surfaces}</table></div>
<h2>Write + read-back</h2><table><tr><th>Round</th><th class=n>Written</th><th class=n>Verified</th><th>Corrupted (removed)</th><th class=n>Missing</th></tr>{rounds}</table>
{compare}
<h2>Cost</h2><table><tr><th>Stage</th><th>Model</th><th class=n>Calls</th><th class=n>In</th><th class=n>Out</th><th class=n>USD</th></tr>{costs}</table>
</body></html>""")
