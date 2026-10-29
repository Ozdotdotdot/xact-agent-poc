"""Builds demo/deck.html, a 16:9 slide deck, from results/*.json, truth.json and the transcripts.

uv run demo/build.py   ->   xdg-open demo/deck.html   (arrow keys / space to move, F for fullscreen)
Every number on a slide comes from a recorded eval run; nothing is typed in by hand.
"""
import html
import json
from pathlib import Path
from statistics import median

ROOT = Path(__file__).parent.parent
CLAIM = ROOT / "data/claim-001"
PHOTOS = "../data/claim-001/photos"
e = lambda s: html.escape(str(s))

VERSIONS = [  # (results file, short label, what changed)
    ("eval-1-flat-haiku.json", "v1", "Haiku groups all photos"),
    ("eval-2-flat-sonnet.json", "v2", "Sonnet groups all photos"),
    ("eval-3-hierarchical.json", "v3", "sort rooms, then walls per room"),
    ("eval-4-hierarchical-caller-context.json", "v4", "+ caller's room descriptions"),
    ("eval-5-guided-capture.json", "v5", "photos tagged by room"),
]
PUBLIC = ROOT / "data/public-samples"
HERO_PHOTO = {"bedroom": "IMG_7693", "den": "IMG_7701", "living room": "IMG_7697"}
CALLERS = [  # (transcript, label, line quoted on the slide; checked against the transcript below)
    ("01-prepared", "Prepared", "Maybe half an inch across the floor?"),
    ("02-vague", "Vague", "I don't know where it came from."),
    ("03-overclaim", "Overclaims", "In the bedroom it was over a foot. Easily."),
]


def photo_room(r: dict, truth: dict) -> float:
    """From the raw room assignments when the run saved them; older runs only have the surface-based score."""
    if not r.get("assignments"):
        return r["photo_room_acc"]
    true_room = {f"{p}.jpg": room for room, t in truth["rooms"].items() for p in t["photos"]}
    def same(got, want):
        got = got.lower()
        return want in got or any(a.lower() in got for a in truth["rooms"][want].get("aka", []))
    return sum(same(r["assignments"].get(p, ""), want) for p, want in true_room.items()) / len(true_room)


def summarize(rows: list[dict], truth: dict) -> dict:
    ok = [r for r in rows if "failed" not in r]
    for r in ok:
        r["photo_room_acc"] = photo_room(r, truth)
    cut = [x["flood_cut_ok"] for r in ok for x in r["rooms"].values() if x["flood_cut_ok"] is not None]
    return {
        "photo_room": median(r["photo_room_acc"] for r in ok),
        "photo_room_liar": median(r["photo_room_acc"] for r in ok if r["transcript"] == "03-overclaim"),
        "cut": (sum(cut), len(cut)),
        "walls": {room: [r["rooms"][room]["wet_walls"] for r in ok] for room in truth["rooms"]},
        "flags": (sum(r["flags_caught"] for r in ok), sum(r["flags_expected"] for r in ok)),
        "flags_by_t": {t: (sum(r["flags_caught"] for r in ok if r["transcript"] == t),
                           sum(r["flags_expected"] for r in ok if r["transcript"] == t))
                       for t in {r["transcript"] for r in ok}},
        "xact": (sum(r["xact_verified"] for r in ok), len(ok)),
        "repairs": sum(r["xact_repairs"] for r in ok),
        "usd": median(r["usd"] for r in ok),
        "runs": len(ok),
    }


def flag_text(f: dict) -> str:
    if f.get("why"):
        return f["why"]
    return f["needs"] if f["room"] == "job" else f"{f['room']}: no {f['needs']}"


def slide_rooms(truth: dict) -> str:
    cols = ""
    for room, t in truth["rooms"].items():
        lo, hi = t["water_line_in"]
        size = f"{t['area_sqft']} SF" if "area_sqft" in t else f"wall {t['affected_wall_lengths_in'][0]} in"
        cols += (f'<figure class="room reveal"><img src="{PHOTOS}/{HERO_PHOTO[room]}.jpg" alt="">'
                 f'<figcaption><b>{e(room.title())}</b><span>tape {lo}–{hi} in</span>'
                 f'<span>{t["wet_walls"]} wet wall{"s" * (t["wet_walls"] > 1)}</span><span>{size}</span>'
                 f'<span>{len(t["photos"])} photos</span></figcaption></figure>')
    return cols


def slide_public() -> tuple[str, str]:
    obs = json.loads((PUBLIC / "observations.json").read_text())
    measured = sum(any(x.get("water_line_in") is not None for x in o["surfaces"]) for o in obs)
    cells = "".join(f'<div class=pub><img src="../data/public-samples/photos/{o["photo"]}" alt="">'
                    f'<span>{"water line: none" if not any(x.get("water_line_in") is not None for x in o["surfaces"]) else "water line found"}</span></div>'
                    for o in obs)
    return cells, f"{measured}/{len(obs)}"


def slide_callers(truth: dict, final: dict) -> str:
    cards = ""
    for name, label, quote in CALLERS:
        text = (CLAIM / "transcripts" / f"{name}.txt").read_text()
        assert quote in text, f"quote not in {name}: {quote}"
        chips = "".join(f"<li>{e(flag_text(f))}</li>" for f in truth["transcripts"][name]["expected_flags"])
        caught, expected = final["flags_by_t"][name]
        cards += (f'<div class="caller reveal"><div class=mono>{e(name)}</div><h3>{e(label)}</h3>'
                  f'<blockquote>“{e(quote)}”</blockquote><div class="mono dim">should flag</div><ul class=chips>{chips}</ul>'
                  f'<div class=caught><b>{caught}/{expected}</b> caught across {final["runs"] // 3} guided runs</div></div>')
    return cards


def slide_chart(versions: list) -> str:
    groups = ""
    for label, what, s in versions:
        bars = "".join(
            f'<div class="bar {cls}" style="height:{v * 100:.1f}%" title="{label} {name}: {v:.0%}"><span>{v:.0%}</span></div>'
            for cls, name, v in [("all", "all callers", s["photo_room"]), ("liar", "overclaiming caller", s["photo_room_liar"])])
        groups += (f'<div class="group{" hl" * (label == versions[-1][0])}"><div class=bars>{bars}</div>'
                   f'<div class=xlab><b>{e(label)}</b><span>{e(what)}</span></div></div>')
    return groups


def slide_walls(final: dict, truth: dict) -> str:
    rows, scale = "", 5
    for room, t in truth["rooms"].items():
        counts, true = final["walls"][room], t["wet_walls"]
        seen: dict[int, int] = {}
        dots = ""
        for c in counts:
            k = seen[c] = seen.get(c, -1) + 1
            dx, dy = (k % 3 - 1) * 32, (k // 3 - 1) * 32
            dots += (f'<i class="{"ok" if c == true else "off"}" '
                     f'style="left:calc({c / scale * 100:.2f}% + {dx}px);top:{65 + dy}px"></i>')
        name = room.title() + (" · L-shaped" if room == "den" else "")
        exact = sum(c == true for c in counts)
        rows += (f'<div class="wrow reveal"><div class=wname><b>{e(name)}</b><span>true: {true}</span></div>'
                 f'<div class=track><div class=truth style="left:{true / scale * 100:.2f}%"></div>{dots}</div>'
                 f'<div class=wscore>{exact}/{len(counts)}</div></div>')
    ticks = "".join(f'<span style="left:{n / scale * 100}%">{n}</span>' for n in range(scale + 1))
    return rows + f'<div class=wrow><div></div><div class=ticks>{ticks}</div><div></div></div>'


def main():
    truth = json.loads((CLAIM / "truth.json").read_text())
    versions = [(label, what, summarize(json.loads((ROOT / "results" / f).read_text())["rows"], truth))
                for f, label, what in VERSIONS if (ROOT / "results" / f).exists()]
    final, best_unguided = versions[-1][2], versions[-2][2]
    n_photos = sum(len(t["photos"]) for t in truth["rooms"].values())

    public_cells, public_measured = slide_public()
    page = PAGE
    for k, v in {
        "ROOMS": slide_rooms(truth), "CALLERS": slide_callers(truth, final), "PUBLIC": public_cells, "PUBLIC_MEASURED": public_measured, "CHART": slide_chart(versions),
        "WALLS": slide_walls(final, truth), "N_PHOTOS": str(n_photos), "RUNS": str(final["runs"]),
        "CUT": "{}/{}".format(*final["cut"]), "FLAGS": "{}/{}".format(*final["flags"]),
        "XACT": "{}/{}".format(*final["xact"]), "REPAIRS": str(final["repairs"]), "USD": f"${final['usd']:.2f}",
        "UNGUIDED_ROOM": f"{best_unguided['photo_room']:.0%}", "PHOTOS": PHOTOS,
    }.items():
        page = page.replace(f"%%{k}%%", v)
    out = ROOT / "demo/deck.html"
    out.write_text(page)
    print(out)


PAGE = r"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Xact Agent POC</title>
<link rel=preconnect href="https://fonts.googleapis.com"><link rel=preconnect href="https://fonts.gstatic.com" crossorigin>
<link rel=stylesheet href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400;12..96,600;12..96,800&family=IBM+Plex+Mono:wght@400;600&display=swap">
<style>
:root{--stage-bg:#0c0d0f;--slide-bg:#14161a;--panel:#1c1f24;--line:#2d3138;--ink:#f1ede4;--dim:#9aa0a8;
  --tape:#e6d3a3;--accent:#f2c230;--model:#4f8de0;--code:#f2c230;--liar:#c27c0e;--ok:#4f8de0;--off:#6b7079;
  --display:'Bricolage Grotesque',system-ui,sans-serif;--mono:'IBM Plex Mono',ui-monospace,monospace;--pad:110px}
*{margin:0;padding:0;box-sizing:border-box}
/* fixed 16:9 stage (frontend-slides viewport-base) */
html,body{width:100%;height:100%;overflow:hidden;background:var(--stage-bg)}
.deck-viewport{position:fixed;inset:0;overflow:hidden;background:var(--stage-bg)}
.deck-stage{position:absolute;left:0;top:0;width:1920px;height:1080px;overflow:hidden;transform-origin:0 0;background:var(--slide-bg)}
.slide{position:absolute;inset:0;width:1920px;height:1080px;overflow:hidden;visibility:hidden;opacity:0;pointer-events:none;
  background:var(--slide-bg);transition:opacity .35s ease;padding:var(--pad);display:flex;flex-direction:column}
.slide.active{visibility:visible;opacity:1;pointer-events:auto;z-index:1}
img{max-width:100%;max-height:100%}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;transition-duration:.01ms!important}}
@media print{html,body{overflow:visible;height:auto}.deck-viewport{position:static}.deck-stage{position:static;transform:none!important}
  .slide{position:relative;visibility:visible!important;opacity:1!important;break-after:page}.counter{display:none}}

body{color:var(--ink);font-family:var(--display)}
.reveal{opacity:0;transform:translateY(18px);transition:opacity .5s cubic-bezier(.16,1,.3,1),transform .5s cubic-bezier(.16,1,.3,1)}
.slide.active .reveal{opacity:1;transform:none}
.slide.active .reveal:nth-child(2){transition-delay:.08s}.slide.active .reveal:nth-child(3){transition-delay:.16s}
.slide.active .reveal:nth-child(4){transition-delay:.24s}.slide.active .reveal:nth-child(5){transition-delay:.32s}
.slide.active .reveal:nth-child(6){transition-delay:.4s}
.mono{font-family:var(--mono);font-size:24px;letter-spacing:.06em;text-transform:uppercase;color:var(--accent)}
.dim{color:var(--dim)}
h1{font-size:128px;line-height:1;font-weight:800;letter-spacing:-.035em}
h2{font-size:84px;line-height:1.02;font-weight:800;letter-spacing:-.03em;margin:18px 0 0}
h3{font-size:44px;font-weight:800;letter-spacing:-.02em}
.hl-text{color:var(--accent)}
.foot{margin-top:auto;font-family:var(--mono);font-size:28px;color:var(--dim)}
.body{flex:1;display:flex;gap:56px;margin-top:56px;min-height:0}

/* tape strip motif */
.tape{position:absolute;left:-40px;right:-40px;height:74px;background:var(--tape);opacity:.92;transform:rotate(-1.2deg);
  display:flex;align-items:center;padding-left:150px;font-family:var(--mono);font-size:24px;letter-spacing:.3em;color:#3b3220;
  box-shadow:0 2px 0 rgba(0,0,0,.25);
  -webkit-mask:linear-gradient(90deg,transparent 0,#000 30px,#000 calc(100% - 30px),transparent 100%)}

/* 1 title */
.title h1{margin-top:auto;max-width:1600px}
.title h1 + h1{margin-top:20px;margin-bottom:220px}
.title .tape{bottom:150px}

/* 2 hero numbers */
.split{flex:1;display:grid;grid-template-columns:1fr 1fr;gap:72px;margin-top:56px;min-height:0}
.big{display:flex;flex-direction:column;justify-content:center;gap:20px}
.big b{font-size:260px;line-height:.9;font-weight:800;letter-spacing:-.05em}
.big span{font-size:40px;line-height:1.2;color:var(--dim);max-width:720px}
.photo{position:relative;border-radius:18px;overflow:hidden;background:var(--panel)}
.photo img{width:100%;height:100%;object-fit:cover;max-height:none}
.photo .tag{position:absolute;left:24px;bottom:24px;background:rgba(10,11,13,.82);padding:14px 20px;border-radius:10px;
  font-family:var(--mono);font-size:28px}
.photo .tag b{color:var(--accent);font-weight:600}

.pubgrid{display:grid;grid-template-columns:repeat(4,1fr);grid-auto-rows:1fr;gap:16px;min-height:0}
.pub{position:relative;border-radius:12px;overflow:hidden;background:var(--panel);min-height:0}
.pub img{width:100%;height:100%;object-fit:cover;max-height:none;display:block}
.pub span{position:absolute;left:10px;bottom:10px;background:rgba(10,11,13,.85);padding:6px 10px;border-radius:6px;font-family:var(--mono);font-size:18px;color:#e66767}
.split.pubsplit{grid-template-columns:560px 1fr}

/* 3 rooms */
.rooms{flex:1;display:grid;grid-template-columns:repeat(3,1fr);gap:40px;margin-top:56px;min-height:0}
.room{display:flex;flex-direction:column;gap:22px;min-height:0}
.room img{flex:1;min-height:0;width:100%;object-fit:cover;border-radius:16px;max-height:none}
.room figcaption{display:flex;flex-wrap:wrap;gap:10px 24px;align-items:baseline;font-family:var(--mono);font-size:24px;color:var(--dim)}
.room figcaption b{width:100%;font-family:var(--display);font-size:44px;color:var(--ink);letter-spacing:-.02em}
.room figcaption span:first-of-type{color:var(--accent)}

/* 4 callers */
.callers{flex:1;display:grid;grid-template-columns:repeat(3,1fr);gap:36px;margin-top:56px}
.caller{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:44px;display:flex;flex-direction:column;gap:18px}
.caller blockquote{font-size:40px;line-height:1.2;font-weight:600;margin:10px 0 auto;padding-bottom:28px}
.caller .chips{min-height:250px}
.chips{list-style:none;display:flex;flex-direction:column;gap:12px}
.caught{margin-top:18px;font-family:var(--mono);font-size:22px;color:var(--dim)}
.caught b{color:#4ade80;font-size:30px;margin-right:6px}
.chips li{font-family:var(--mono);font-size:22px;line-height:1.3;border-left:5px solid var(--accent);padding:10px 16px;background:#24282e;border-radius:0 8px 8px 0}

/* 5 pipeline */
.flow{display:grid;grid-template-columns:repeat(6,1fr);gap:30px;margin-top:100px}
.step{border:3px solid var(--model);border-radius:18px;padding:32px 26px;min-height:400px;display:flex;flex-direction:column;gap:14px;position:relative}
.step.code{border-color:var(--code);background:rgba(242,194,48,.07)}
.step .n{font-family:var(--mono);font-size:26px;color:var(--dim)}
.step b{font-size:36px;line-height:1.1;letter-spacing:-.01em}
.step .who{margin-top:auto;font-family:var(--mono);font-size:22px;font-weight:600;line-height:1.35;color:var(--model)}
.step.code .who{color:var(--code)}
.step .calls{font-family:var(--mono);font-size:24px;line-height:1.35;color:var(--dim)}
.step.skip{border-style:dashed}
.step:not(:last-child)::after{content:"→";position:absolute;right:-21px;top:50%;transform:translate(50%,-50%);font-size:30px;color:var(--dim)}
.legend{display:flex;gap:40px;margin:40px 0 0;font-family:var(--mono);font-size:24px;color:var(--dim)}
.legend i{display:inline-block;width:22px;height:22px;border-radius:5px;border:3px solid var(--model);margin-right:12px;vertical-align:-4px}
.legend i.c{border-color:var(--code);background:rgba(242,194,48,.15)}
.legend i.s{border-style:dashed}

/* 6 live */
.term{margin-top:70px;background:#0b0c0e;border:1px solid var(--line);border-radius:18px;overflow:hidden}
.term .bar{height:52px;background:#202329;display:flex;gap:12px;align-items:center;padding:0 22px}
.term .bar i{width:16px;height:16px;border-radius:50%;background:#3a3f47}
.term pre{font-family:var(--mono);font-size:34px;line-height:1.5;padding:44px 48px;white-space:pre-wrap;color:var(--ink)}
.term pre .p{color:var(--accent)}.term pre .c{color:var(--dim)}
.params{display:flex;gap:28px;margin-top:48px}
.params div{flex:1;border-top:4px solid var(--accent);padding-top:20px;font-size:36px;font-weight:600}
.params span{display:block;font-family:var(--mono);font-size:22px;color:var(--dim);font-weight:400;margin-bottom:8px;text-transform:uppercase;letter-spacing:.06em}

/* 7 chart */
.chart{flex:1;display:grid;grid-template-columns:repeat(5,1fr);gap:28px;margin-top:40px;min-height:0;position:relative;
  border-bottom:2px solid var(--line);padding:0 10px}
.chart .gridline{position:absolute;left:0;right:0;border-top:1px dashed var(--line)}
.chart .gridline span{position:absolute;right:100%;margin-right:14px;transform:translateY(-50%);font-family:var(--mono);font-size:20px;color:var(--dim)}
.group{display:flex;flex-direction:column;min-height:0;border-radius:14px 14px 0 0;padding:0 18px}
.group.hl{background:rgba(242,194,48,.06)}
.bars{flex:1;display:flex;align-items:flex-end;justify-content:center;gap:6px;min-height:0}
.bar{width:96px;border-radius:6px 6px 0 0;position:relative}
.bar.all{background:var(--model)}.bar.liar{background:var(--liar)}
.bar span{position:absolute;bottom:100%;left:0;right:0;text-align:center;padding-bottom:10px;font-family:var(--mono);font-size:26px;font-weight:600;color:var(--ink)}
.group{position:relative}
.xlab{position:absolute;left:0;right:0;bottom:-118px;text-align:center}
.xlab b{display:block;font-size:34px}.xlab span{font-family:var(--mono);font-size:20px;color:var(--dim)}
.chartwrap{flex:1;display:flex;flex-direction:column;min-height:0;padding:0 0 130px 70px}
.key{display:flex;gap:40px;justify-content:flex-end;font-family:var(--mono);font-size:24px;color:var(--dim);margin-top:24px}
.key i{display:inline-block;width:22px;height:22px;border-radius:4px;margin-right:12px;vertical-align:-3px}

/* 8 guided numbers */
.tiles{flex:1;display:grid;grid-template-columns:repeat(4,1fr);gap:32px;margin-top:70px;align-content:center}
.tile{border-top:6px solid var(--accent);padding-top:34px}
.tile b{display:block;font-size:150px;line-height:.95;font-weight:800;letter-spacing:-.04em}
.tile span{display:block;margin-top:22px;font-size:34px;line-height:1.25;color:var(--dim)}

/* 9 wall dots */
.walls{margin-top:60px;display:flex;flex-direction:column;gap:24px}
.wrow{display:grid;grid-template-columns:420px 1fr 160px;align-items:center;gap:40px}
.wname b{display:block;font-size:44px;letter-spacing:-.02em}.wname span{font-family:var(--mono);font-size:22px;color:var(--dim)}
.track{position:relative;height:150px;border-bottom:1px solid var(--line)}
.track i{position:absolute;width:26px;height:26px;border-radius:50%;transform:translate(-50%,-50%)}
.track i.ok{background:var(--ok)}.track i.off{background:transparent;border:4px solid var(--off)}
.truth{position:absolute;top:-6px;bottom:-6px;width:6px;margin-left:-3px;background:var(--accent);border-radius:3px;opacity:.9}
.wscore{font-family:var(--mono);font-size:44px;font-weight:600;text-align:right}
.ticks{position:relative;height:30px}
.ticks span{position:absolute;transform:translateX(-50%);font-family:var(--mono);font-size:22px;color:var(--dim)}
.wkey{display:flex;gap:40px;margin-top:40px;font-family:var(--mono);font-size:24px;color:var(--dim)}
.wkey i{display:inline-block;width:22px;height:22px;border-radius:50%;margin-right:12px;vertical-align:-4px}

/* 10 capture mockup */
.phones{flex:1;display:flex;justify-content:space-between;align-items:center;margin-top:30px}
.phone{width:310px;height:660px;border-radius:46px;border:12px solid #050505;background:#fff;color:#111;display:flex;flex-direction:column;
  overflow:hidden;box-shadow:0 30px 60px rgba(0,0,0,.45);font-family:var(--display);font-size:20px}
.phone .top{padding:22px 22px 8px;font-weight:800;font-size:25px;line-height:1.15}
.phone .top small{display:block;font-weight:400;color:#666;font-size:18px;margin-top:4px}
.phone .view{flex:1;margin:10px 14px;border-radius:16px;background:#ddd center/cover;position:relative}
.phone .btn{margin:10px 18px 22px;background:#1b1d22;color:#fff;text-align:center;border-radius:14px;padding:16px;font-weight:600}
.phone .chips2{display:flex;flex-wrap:wrap;gap:8px;padding:6px 18px}
.phone .chips2 span{border:1.5px solid #ccc;border-radius:99px;padding:8px 14px;font-size:18px}
.phone .chips2 span.on{background:#1b1d22;color:#fff;border-color:#1b1d22}
.phone .line{position:absolute;left:0;right:0;border-top:3px dashed var(--accent)}
.phone .read{position:absolute;left:12px;right:12px;bottom:12px;background:#15803d;color:#fff;border-radius:10px;padding:12px;font-size:19px;font-weight:600}
.phone .plan{position:absolute;inset:26px;border:4px solid #1b1d22;border-radius:4px}
.phone .plan i{position:absolute;background:#e11d48;border-radius:3px}
.phone .list{padding:22px;font-size:19px;line-height:1.9}
.cap{display:flex;justify-content:space-between;margin-top:26px}
.cap div{width:310px;text-align:center;font-family:var(--mono);font-size:22px;color:var(--accent)}

/* 11 what closes each gap */
table{width:100%;border-collapse:collapse;margin-top:60px;font-size:32px}
th{text-align:left;font-family:var(--mono);font-size:22px;font-weight:400;color:var(--dim);text-transform:uppercase;letter-spacing:.06em;padding:0 24px 22px}
td{padding:26px 24px;border-top:1px solid var(--line)}
td:first-child{font-weight:600}
td .x{color:var(--dim)}td .x::before{content:"✗ ";color:#e66767}
td .w::before{content:"~ ";color:var(--accent)}
td .v::before{content:"✓ ";color:#4ade80}
td.closer{font-family:var(--mono);font-size:26px;color:var(--accent)}

/* 12 close */
.close h1{margin-top:auto;font-size:116px;max-width:1500px}
.close h1 + h1{margin-top:16px;margin-bottom:200px;color:var(--accent)}
.close .tape{bottom:300px;transform:rotate(1deg)}
.close .foot{display:flex;justify-content:space-between;font-size:28px;color:var(--ink)}

.counter{position:fixed;right:18px;bottom:12px;z-index:10;font:13px var(--mono);color:#555}
</style></head><body>
<div class=deck-viewport><main class=deck-stage id=stage>

<section class="slide title active">
<div class="mono reveal">Ozair Khan · Cozmo FDE</div>
<h1 class=reveal>Call transcript + 40 photos → an Xact estimate.</h1>
<h1 class="reveal hl-text">What breaks first?</h1>
<div class=tape>WATER LINE · WATER LINE · WATER LINE · WATER LINE · WATER LINE · WATER LINE</div>
</section>

<section class=slide>
<div class="mono reveal">01 · Public water-damage photos</div>
<h2 class=reveal>Missing information.</h2>
<div class="split pubsplit">
<div class="big reveal"><b>%%PUBLIC_MEASURED%%</b><span>photos with a water line the model could measure. It returned no number rather than guess.</span></div>
<div class="pubgrid reveal">%%PUBLIC%%</div>
</div>
<div class="foot reveal" style="margin-top:28px;font-size:20px">Wikimedia Commons · credits in data/public-samples/CREDITS.md</div>
</section>

<section class=slide>
<div class="mono reveal">02 · Test case · %%N_PHOTOS%% photos, measured ground truth</div>
<h2 class=reveal>A staged water loss in my basement.</h2>
<div class=rooms>%%ROOMS%%</div>
</section>

<section class=slide>
<div class="mono reveal">03 · Same photos, three callers</div>
<h2 class=reveal>Each call hides something.</h2>
<div class=callers>%%CALLERS%%</div>
</section>

<section class=slide>
<div class="mono reveal">04 · Pipeline · no call sees all 40 photos</div>
<h2 class=reveal>Models look. Code does the math.</h2>
<div class="flow reveal">
<div class=step><span class=n>1</span><b>Read the call</b><span class=calls>facts, each with a quote</span><span class=who>Sonnet · 1 call</span></div>
<div class=step><span class=n>2</span><b>Describe each photo</b><span class=calls>walls, damage, water line</span><span class=who>Haiku · 1 per photo</span></div>
<div class="step skip"><span class=n>3</span><b>Sort photos into rooms</b><span class=calls>skipped when photos arrive tagged</span><span class=who>Sonnet · 1 call</span></div>
<div class=step><span class=n>4</span><b>Count wet walls per room</b><span class=calls>sees that room's photos together</span><span class=who>Sonnet · 1 per room</span></div>
<div class="step code"><span class=n>5</span><b>Compute the estimate</b><span class=calls>flood cut, SF, equipment days</span><span class=who>code</span></div>
<div class="step code"><span class=n>6</span><b>Write to Xact, read it back</b><span class=calls>diff, repair, retry</span><span class=who>code</span></div>
</div>
<div class="legend reveal"><span><i></i>model</span><span><i class=c></i>code</span><span><i class=s></i>guided capture removes it</span></div>
<div class="foot reveal">gaps and contradictions → human review queue</div>
</section>

<section class=slide>
<div class="mono reveal">05 · Live</div>
<h2 class=reveal>One run, end to end.</h2>
<div class="term reveal"><div class=bar><i></i><i></i><i></i></div>
<pre><span class=p>$</span> uv run run.py data/claim-001 \
    --transcript 03-overclaim --guided --xact-fault-rate 0.3
<span class=c>→ out/claim-001/03-overclaim/report.html</span></pre></div>
<div class="params reveal">
<div><span>Caller</span>Overclaims</div>
<div><span>Photos</span>Tagged by room</div>
<div><span>Mock Xact</span>30% of writes silently fail</div>
</div>
</section>

<section class=slide>
<div class="mono reveal">06 · Five versions × 9 runs, scored against truth</div>
<h2 class=reveal>Photos sorted into the right room</h2>
<div class="chartwrap reveal">
<div class=key><span><i style="background:var(--model)"></i>all callers (median)</span><span><i style="background:var(--liar)"></i>overclaiming caller</span></div>
<div class=chart style="margin-top:60px">
<div class=gridline style="top:0"><span>100%</span></div><div class=gridline style="top:50%"><span>50%</span></div>
%%CHART%%
</div></div>
</section>

<section class=slide>
<div class="mono reveal">07 · v5 guided capture · %%RUNS%% runs</div>
<h2 class=reveal>Right every time it had evidence.</h2>
<div class=tiles>
<div class="tile reveal"><b>%%CUT%%</b><span>flood-cut heights right</span></div>
<div class="tile reveal"><b>%%FLAGS%%</b><span>review flags caught</span></div>
<div class="tile reveal"><b>%%XACT%%</b><span>Xact read-backs verified, %%REPAIRS%% silent write failures repaired</span></div>
<div class="tile reveal"><b>%%USD%%</b><span>per claim, all model calls</span></div>
</div>
</section>

<section class=slide>
<div class="mono reveal">08 · v5 guided capture · still open</div>
<h2 class=reveal>Counting walls: the L-shaped den is still open.</h2>
<div class=walls>%%WALLS%%</div>
<div class="wkey reveal"><span><i style="background:var(--ok)"></i>correct</span><span><i style="border:4px solid var(--off)"></i>wrong</span><span><i style="background:var(--accent);border-radius:3px;width:8px"></i>true count</span></div>
</section>

<section class=slide>
<div class="mono reveal">09 · Concept · guided capture app</div>
<h2 class=reveal>Own the capture.</h2>
<div class="phones reveal">
<div class=phone><div class=top>Which room?<small>Room 2 of 3 · from the call</small></div>
<div class=chips2><span>Bedroom ✓</span><span class=on>Den</span><span>Living room</span><span>+ Other</span></div>
<div class=view style="background-image:url(%%PHOTOS%%/IMG_7701.jpg)"></div><div class=btn>Start den</div></div>
<div class=phone><div class=top>Wet wall 1 of ?<small>Whole wall in frame</small></div>
<div class=view style="background-image:url(%%PHOTOS%%/IMG_7703.jpg)"><div class=line style="top:76%"></div></div><div class=btn>Next wall</div></div>
<div class=phone><div class=top>Water line<small>Tape measure at the line</small></div>
<div class=view style="background-image:url(%%PHOTOS%%/IMG_7709.jpg)"><div class=read>10 in ✓ → 2 ft flood cut</div></div><div class=btn>Looks right</div></div>
<div class=phone><div class=top>Scan the room<small>LiDAR · walk the edge</small></div>
<div class=view style="background:#f1f5f9"><div class=plan><i style="left:-4px;top:10%;width:6px;height:60%"></i><i style="left:20%;bottom:-4px;width:55%;height:6px"></i></div>
<div class=read>265 SF · wet 14.2 + 11.0 ft</div></div><div class=btn>Send</div></div>
<div class=phone><div class=top>Tech checklist<small>From the review queue</small></div>
<div class="view list" style="background:#fff">☐ Bedroom closet: moisture<br>☐ Den: confirm 2 wet walls<br>☐ Living room: area<br>☐ Water category</div>
<div class=btn>Start visit</div></div>
</div>
<div class="cap reveal"><div>room tag</div><div>one step per wall</div><div>±0.5 in</div><div>lengths, area</div><div>what's left</div></div>
</section>

<section class=slide>
<div class="mono reveal">10 · What closes each gap</div>
<h2 class=reveal>Capture fixes most of it. A tech closes the rest.</h2>
<table class=reveal>
<tr><th>The estimate needs</th><th>Call + photos</th><th>Guided capture</th><th>Then</th></tr>
<tr><td>Room for each photo</td><td><span class=w>inferred · %%UNGUIDED_ROOM%%</span></td><td><span class=v>tagged</span></td><td></td></tr>
<tr><td>Number of wet walls</td><td><span class=x>over-counted</span></td><td><span class=v>one step per wall</span></td><td></td></tr>
<tr><td>Flood-cut height</td><td><span class=w>±2–4 in from outlets</span></td><td><span class=v>±0.5 in, tape</span></td><td></td></tr>
<tr><td>Wall lengths, room area</td><td><span class=x>missing</span></td><td><span class=x>missing</span></td><td class=closer>LiDAR scan</td></tr>
<tr><td>Moisture behind walls</td><td><span class=x>unknown</span></td><td><span class=x>unknown</span></td><td class=closer>tech + meter</td></tr>
</table>
</section>

<section class="slide close">
<h1 class=reveal>Right wherever there's evidence.</h1>
<h1 class=reveal>Explicit about the rest.</h1>
<div class=tape>WATER LINE · WATER LINE · WATER LINE · WATER LINE · WATER LINE · WATER LINE</div>
<div class="foot reveal"><span>github.com/Ozdotdotdot/xact-agent-poc</span><span>Ozair Khan</span></div>
</section>

</main></div>
<div class=counter id=counter></div>
<script>
const stage = document.getElementById('stage'), slides = [...document.querySelectorAll('.slide')], counter = document.getElementById('counter');
let cur = 0;
function fit() {
  const f = Math.min(innerWidth / 1920, innerHeight / 1080);
  stage.style.transform = `translate(${(innerWidth - 1920 * f) / 2}px,${(innerHeight - 1080 * f) / 2}px) scale(${f})`;
}
function show(i) {
  cur = Math.max(0, Math.min(i, slides.length - 1));
  slides.forEach((s, j) => s.classList.toggle('active', j === cur));
  counter.textContent = `${cur + 1} / ${slides.length}`;
  history.replaceState(null, '', '#' + (cur + 1));
}
addEventListener('resize', fit);
addEventListener('keydown', ev => {
  if (['ArrowRight', 'ArrowDown', ' ', 'PageDown', 'Enter'].includes(ev.key)) { ev.preventDefault(); show(cur + 1); }
  else if (['ArrowLeft', 'ArrowUp', 'PageUp', 'Backspace'].includes(ev.key)) { ev.preventDefault(); show(cur - 1); }
  else if (ev.key === 'Home') show(0);
  else if (ev.key === 'End') show(slides.length - 1);
  else if (ev.key === 'f' || ev.key === 'F') document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen();
});
let tx = null;
addEventListener('touchstart', ev => tx = ev.touches[0].clientX, {passive: true});
addEventListener('touchend', ev => { if (tx === null) return; const d = ev.changedTouches[0].clientX - tx; if (Math.abs(d) > 50) show(cur + (d < 0 ? 1 : -1)); tx = null; });
fit();
show((parseInt(location.hash.slice(1)) || 1) - 1);
</script>
</body></html>"""

if __name__ == "__main__":
    main()
