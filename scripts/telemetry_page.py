#!/usr/bin/env python3
"""telemetry_page.py — Render the public pipeline-status page.

Split out of sync_dashboard.py because the page stopped being a debug dump and
became the one public surface that has to argue, to a stranger, that this
machine is real. Two rules shape it:

1. It inherits the Command Center's palette, not GitHub's. The old page
   hardcoded #0d1117 and looked like a different product from the demo it sits
   next to.
2. It reports the run record, not a row of green lights. `run_history.py`
   separates a full sweep from a run that exited in under two minutes, and the
   page shows that difference, because a status page where everything is always
   green is a status page nobody reads twice.

Server-rendered, no JavaScript, no external requests: it must survive being
opened from a GitHub Pages URL on a recruiter's phone with a bad connection.
"""
import datetime
import html


# The Command Center's own tokens (docs/index.html). Light is the default and
# the dark set is the same design under a different ambient light, not GitHub's
# borrowed palette.
CSS = """
:root{
  --bg:#FAF9F6; --card:#FFFFFF; --text:#0A0A0A; --muted:#5B6270;
  --border:#E7E4DD; --hover:#F3F1EB; --accent:#0F9D74; --accent-soft:#E7F5F0;
  --warn:#C98A16; --warn-soft:#FBF3E2; --stall:#8A8F98; --fail:#A8412A;
  --track:#EDEAE3;
  /* Stage ramp: light to dark by how far a role has travelled. Kept as its own
     scale so the status colours above never get read as stage colours. */
  --s1:#D8D2C6; --s2:#0F9D74; --s3:#C98A16; --s4:#9B9488; --s5:#0A0A0A;
  --shadow:0 1px 2px rgba(16,18,20,.05), 0 8px 24px -12px rgba(16,18,20,.12);
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#141416; --card:#1E1E21; --text:#F2F2EF; --muted:#9AA1AC;
    --border:#2C2C31; --hover:#26262B; --accent:#2CBF93; --accent-soft:#12352B;
    --warn:#E3A83E; --warn-soft:#2E2411; --stall:#71767F; --fail:#E0705A;
    --track:#3C3C44;
    --s1:#3A3A40; --s2:#2CBF93; --s3:#E3A83E; --s4:#6E6A62; --s5:#F2F2EF;
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 24px -12px rgba(0,0,0,.6);
  }
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--bg); color:var(--text);
  font:15px/1.6 -apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  font-variant-numeric:tabular-nums;
  -webkit-font-smoothing:antialiased;
}
::selection{background:var(--accent-soft); color:var(--text)}
:focus-visible{outline:2px solid var(--accent); outline-offset:3px; border-radius:3px}
*{scrollbar-color:var(--border) transparent; scrollbar-width:thin}
::-webkit-scrollbar{height:10px;width:10px}
::-webkit-scrollbar-thumb{background:var(--border); border-radius:99px}
::-webkit-scrollbar-track{background:transparent}
a{color:inherit; text-decoration:none}
a.link{text-decoration:underline; text-decoration-color:var(--border);
  text-underline-offset:3px; transition:text-decoration-color .15s}
a.link:hover{text-decoration-color:var(--accent)}

.wrap{max-width:860px; margin:0 auto; padding:0 24px}

header{border-bottom:1px solid var(--border); background:var(--bg);
  position:sticky; top:0; z-index:5}
.bar{display:flex; align-items:center; gap:20px; height:60px}
.mark{display:flex; align-items:center; gap:10px; font-weight:650;
  letter-spacing:-.01em; margin-right:auto}
.glyph{width:26px; height:26px; border-radius:7px; background:var(--accent);
  display:grid; place-items:center; flex:none}
nav{display:flex; gap:20px; font-size:13.5px; color:var(--muted)}
nav a{padding:4px 0; border-bottom:1.5px solid transparent}
nav a:hover{color:var(--text)}
nav a[aria-current=page]{color:var(--text); border-bottom-color:var(--accent)}

.lede{padding:52px 0 8px}
h1{font-size:clamp(26px,4.2vw,34px); line-height:1.18; letter-spacing:-.024em;
  margin:0 0 14px; max-width:26ch; text-wrap:balance}
.sub{color:var(--muted); font-size:14.5px; margin:0; max-width:66ch}
.sub b{color:var(--text); font-weight:600}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:.92em}

section{padding:36px 0 34px; border-top:1px solid var(--border)}
section:first-of-type{border-top:0; padding-top:22px}
section > :last-child{margin-bottom:0}
h2{font-size:17px; letter-spacing:-.012em; margin:0 0 6px}
.hint{color:var(--muted); font-size:13.5px; margin:0 0 20px; max-width:68ch}

/* ---- run record ------------------------------------------------------- */
.record{background:var(--card); border:1px solid var(--border);
  border-radius:12px; padding:22px 22px 16px; box-shadow:var(--shadow)}
.strip{display:flex; gap:2px; align-items:flex-end; height:64px}
.day{flex:1 1 0; min-width:3px; position:relative; height:100%;
  display:flex; align-items:flex-end}
.day i{display:block; width:100%; border-radius:2px;
  height:var(--h); background:var(--c);
  transform-origin:bottom; animation:grow .5s cubic-bezier(.16,1,.3,1) backwards;
  animation-delay:calc(var(--i) * 7ms)}
/* Absence reads as a floor tick, not a full-height column: a day the machine
   was off should not occupy more ink than a day it worked. */
.day.norun i{height:3px; background:var(--track); animation:none}
@keyframes grow{from{transform:scaleY(0)} to{transform:scaleY(1)}}
@media (prefers-reduced-motion: reduce){.day i{animation:none}}
.axis{display:flex; justify-content:space-between; color:var(--muted);
  font-size:12px; margin-top:10px; padding-top:10px;
  border-top:1px solid var(--border)}
.legend{display:flex; flex-wrap:wrap; gap:6px 18px; margin:14px 0 0;
  padding:0; list-style:none; font-size:13px}
.legend li{display:flex; align-items:center; gap:8px}
.swatch{width:9px; height:9px; border-radius:2px; flex:none;
  box-shadow:inset 0 0 0 1px rgba(0,0,0,.06)}
.legend b{font-weight:600}
.legend span{color:var(--muted)}

.note{display:flex; gap:12px; margin:22px 0 0; padding:14px 16px;
  background:var(--warn-soft); border:1px solid var(--border);
  border-radius:10px; font-size:13.5px; line-height:1.55}
.note svg{flex:none; margin-top:2px; color:var(--warn)}
.note p{margin:0}
.note strong{font-weight:620}

/* ---- stage bar --------------------------------------------------------- */
.stack{display:flex; gap:2px; height:16px; margin:0 0 4px}
.stack span{border-radius:2px; min-width:4px}
.defs{margin:0; padding:0}
.defs div{display:grid; grid-template-columns:150px 3.2em 1fr;
  gap:0 20px; align-items:baseline; padding:11px 0;
  border-bottom:1px solid var(--border)}
.defs div:last-child{border-bottom:0}
.defs dt{display:flex; align-items:center; gap:10px; font-weight:600;
  font-size:14px}
.defs dd{margin:0; color:var(--muted); font-size:13.5px}
.defs .n{font-weight:660; font-size:15px; text-align:right; color:var(--text)}

/* ---- tables ------------------------------------------------------------ */
.tbl{width:100%; border-collapse:collapse}
.tbl th{text-align:left; font-size:11.5px; letter-spacing:.06em;
  text-transform:uppercase; color:var(--muted); font-weight:600;
  padding:0 12px 9px 0; border-bottom:1px solid var(--border)}
.tbl td{padding:11px 12px 11px 0; border-bottom:1px solid var(--border);
  font-size:14px; vertical-align:baseline}
.tbl tr:last-child td{border-bottom:0}
.tbl td.r{text-align:right; color:var(--muted); font-size:13px;
  white-space:nowrap; padding-right:0}
/* The dot alone carries "working". Six rows spelling out the same word is
   noise; the label appears only when the state is worth a word. */
.dot{display:inline-flex; align-items:baseline; gap:9px; font-size:13px;
  color:var(--muted)}
.dot::before{content:''; width:7px; height:7px; border-radius:99px;
  background:var(--accent); flex:none; transform:translateY(-1px)}
.dot.reconnect::before{background:var(--warn)}
.dot.broken::before{background:var(--fail)}

.chips{display:flex; flex-wrap:wrap; gap:7px; margin:0; padding:0;
  list-style:none}
.chips li{border:1px solid var(--border); background:var(--card);
  border-radius:99px; padding:5px 13px; font-size:13px}

.wont{display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
  gap:0 36px; margin:0}
.wont div{padding:13px 0; border-top:1px solid var(--border)}
.wont dt{font-weight:620; font-size:14px; margin:0 0 3px}
.wont dd{margin:0; color:var(--muted); font-size:13.5px; line-height:1.55}
.state{font-style:normal; color:var(--warn); font-weight:600}

footer{border-top:1px solid var(--border); margin-top:40px; padding:24px 0 64px;
  color:var(--muted); font-size:13px}
footer p{margin:0 0 8px; max-width:70ch}

@media (max-width:560px){
  .wrap{padding:0 18px}
  .bar{height:54px; gap:14px}
  .lede{padding:36px 0 4px}
  .record{padding:16px 16px 12px}
  .strip{height:52px}
  /* Three columns squeeze the meaning to four words a line; give it the row. */
  .defs div{grid-template-columns:1fr auto; gap:0 14px}
  .defs dd:last-child{grid-column:1 / -1; margin-top:3px}
}
"""

ICON_INFO = ('<svg width="15" height="15" viewBox="0 0 24 24" fill="none" '
             'stroke="currentColor" stroke-width="1.9" stroke-linecap="round" '
             'aria-hidden="true"><circle cx="12" cy="12" r="9"/>'
             '<path d="M12 11v5M12 7.6v.1"/></svg>')

# Verdict -> (css var, label, what it means in plain words)
VERDICT_META = {
    "clean":   ("var(--accent)", "Full sweep",
                "sourced, scored and prepared"),
    "noop":    ("var(--warn)", "Short exit",
                "exited before doing the work"),
    "errors":  ("var(--fail)", "Errored",
                "finished with a non-zero exit code"),
    # Slate, not red: an unfinished log means the outcome is unknown, and
    # painting unknown as failure is its own kind of dishonesty.
    "partial": ("var(--stall)", "Incomplete",
                "started, never logged a finish"),
    "norun":   ("var(--track)", "No run",
                "the machine was off"),
}

STAGE_META = [
    ("not",       "Wishlist",  "Saved and scored. Not applied to."),
    ("applied",   "Applied",   "Submitted, with a confirmation captured."),
    ("captcha",   "CAPTCHA",   "Prepared, then handed to a human to finish."),
    ("closed",    "Closed",    "Rejected, or the posting came down."),
    ("interview", "Interview", "A reply asking to talk."),
]
STAGE_COLOR = {"not": "var(--s1)", "applied": "var(--s2)",
               "captcha": "var(--s3)", "closed": "var(--s4)",
               "interview": "var(--s5)"}

WONT = [
    ("Solve CAPTCHAs",
     "Detected and flagged, never solved. The folder is marked and a human "
     "finishes the application."),
    ("Answer EEO questions",
     "Left blank on purpose. Guessing on someone's behalf about race, gender, "
     "disability or veteran status is not a bot's call."),
    ("Send cold emails",
     "Drafted only. A cold email goes to a named human and cannot be recalled, "
     "so a person reviews and sends it."),
    ("Invent experience",
     "Screening answers draw only on the profile's experience notes. No "
     "relevant fact means the question is flagged, not answered."),
]


def _esc(v):
    return html.escape(str(v), quote=True)


def _plural(n, one, many=None):
    return one if n == 1 else (many or one + "s")


def _headline(hist, auto):
    """The h1 states the record; the sub qualifies it. Both computed.

    The headline is deliberately the number that is easy to be proud of and the
    number that is not, in that order — the page loses all its value the moment
    it starts rounding in its own favour.
    """
    ran, window = hist["ranCount"], hist["windowDays"]
    if not window:
        return "The pipeline has not run yet.", ""
    worked = hist.get("workedCount", 0)
    lead = f"The pipeline fired on {ran} of the last {window} days."

    last = hist["days"][-1]
    if last["verdict"] == "norun" and len(hist["days"]) > 1:
        last = next((d for d in reversed(hist["days"])
                     if d["verdict"] != "norun"), last)
    dur = (f", {last['minutes']:g} min" if last.get("minutes") is not None else "")
    tail = (f"<b>{worked} of those {_plural(worked, 'run', 'runs')} did a full "
            f"sweep.</b> Last run {_esc(last['date'])}{dur} "
            f"({VERDICT_META[last['verdict']][1].lower()}). "
            f"Scheduled {_esc(auto.get('scheduledTime', 'daily'))}.")
    return lead, tail


def _strip(hist):
    longest = max([d["minutes"] or 0 for d in hist["days"]] + [1])
    cells = []
    for i, d in enumerate(hist["days"]):
        v = d["verdict"]
        color = VERDICT_META[v][0]
        if v == "norun":
            cells.append(f'<span class="day norun" title="{d["date"]} — no run">'
                         f'<i></i></span>')
            continue
        mins = d.get("minutes")
        if mins is None:                 # started, never finished
            pct = 42
            detail = "started, no finish logged"
        else:
            # Square-root scale: a 594-minute outlier must not flatten every
            # 20-minute run into the same stub.
            pct = 22 + 78 * (mins / longest) ** 0.5
            detail = f"{mins:g} min"
        cells.append(
            f'<span class="day" style="--i:{i}" '
            f'title="{d["date"]} — {VERDICT_META[v][1].lower()}, {detail}">'
            f'<i style="--h:{pct:.0f}%;--c:{color}"></i></span>')
    return "".join(cells)


def _legend(hist):
    tally = {}
    for d in hist["days"]:
        tally[d["verdict"]] = tally.get(d["verdict"], 0) + 1
    out = []
    for v in ("clean", "noop", "partial", "errors", "norun"):
        n = tally.get(v, 0)
        if not n:
            continue
        color, label, meaning = VERDICT_META[v]
        out.append(f'<li><span class="swatch" style="background:{color}"></span>'
                   f'<b>{n} {label.lower()}</b> <span>· {meaning}</span></li>')
    return "".join(out)


def _stack(stage, total):
    out = []
    for key, label, _ in STAGE_META:
        n = stage.get(key, 0)
        if not n:
            continue
        pct = 100.0 * n / total if total else 0
        out.append(f'<span style="width:{pct:.2f}%;background:{STAGE_COLOR[key]}" '
                   f'title="{label}: {n}"></span>')
    return "".join(out)


def _defs(stage):
    out = []
    for key, label, meaning in STAGE_META:
        n = stage.get(key, 0)
        out.append(
            f'<div><dt><span class="swatch" style="background:{STAGE_COLOR[key]}">'
            f'</span>{label}</dt><dd class="n">{n}</dd>'
            f'<dd>{meaning}</dd></div>')
    return "".join(out)


def render(tel, hist):
    """Return the full status page as a single self-contained HTML string."""
    auto = tel.get("automation", {})
    stage = tel.get("byStage", {})
    total = tel.get("totalTracked", 0)
    lead, tail = _headline(hist, auto)

    rows = ""
    for s in tel.get("sources", []):
        health = s.get("health", "working")
        # "working" is what the dot already says. Spell a state out only when
        # it is not the expected one.
        word = ("" if health == "working"
                else f' <em class="state">{_esc(health)}</em>')
        rows += (f'<tr><td><span class="dot {_esc(health)}">{_esc(s["name"])}'
                 f'{word}</span></td>'
                 f'<td class="r">{_esc(s.get("synced", "-"))}</td></tr>')

    chips = "".join(f'<li>{_esc(b["name"])}</li>'
                    for b in auto.get("bots", []))

    wont = "".join(f'<div><dt>{t}</dt><dd>{d}</dd></div>' for t, d in WONT)

    noop_n = sum(1 for d in hist["days"] if d["verdict"] == "noop")
    thresh = hist.get("noopThresholdMinutes", 2)
    med = hist.get("medianMinutes")
    if noop_n:
        note = (
            f'<p><strong>{noop_n} of these runs exited in under '
            f'{thresh:g} minutes.</strong> They returned exit code 0, so any '
            f'check that only reads the exit code calls them successful. A real '
            f'sweep takes {med:g} minutes at the median, which is why this page '
            f'plots run length instead: the short bars are how the silent '
            f'failure became visible.</p>')
    else:
        note = ('<p><strong>Exit code 0 is not the same as "did the work".</strong> '
                'Bar height is run length, so a run that returns instantly cannot '
                'hide behind a green light.</p>')

    generated = tel.get("generatedAt", "")[:16].replace("T", " ")

    page = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>Pipeline status — Kestrel</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="description" content="{{META}}">
<style>{{CSS}}</style>

<header>
  <div class="wrap bar">
    <a class="mark" href="./">
      <span class="glyph" aria-hidden="true">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#fff"
             stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round">
          <path d="M4 14.5 12 4l8 10.5"/><path d="M8.5 20 12 15l3.5 5"/>
        </svg>
      </span>
      Kestrel
    </a>
    <nav>
      <a href="./">Demo</a>
      <a href="./status.html" aria-current="page">Status</a>
      <a href="https://github.com/sanketp9499/kestrel">Source</a>
    </nav>
  </div>
</header>

<main class="wrap">
  <div class="lede">
    <h1>{{LEAD}}</h1>
    <p class="sub">{{TAIL}} Telemetry from the real pipeline, rewritten after
    every run. Generated <span class="mono">{{GENERATED}}</span>.</p>
  </div>

  <section>
    <h2>Run record</h2>
    <p class="hint">One column per day. Height is how long the run took, so a
    run that finished instantly reads as a stub rather than a success.</p>
    <div class="record">
      <div class="strip">{{STRIP}}</div>
      <div class="axis"><span>{{FIRST}}</span><span>today</span></div>
      <ul class="legend">{{LEGEND}}</ul>
      <div class="note">{{ICON}}{{NOTE}}</div>
    </div>
  </section>

  <section>
    <h2>Where the {{TOTAL}} tracked roles sit</h2>
    <p class="hint">Every role the pipeline has ever recorded, by stage. Most of
    them are saved and scored but never applied to, which is the honest shape of
    a filtered search.</p>
    <div class="stack">{{STACK}}</div>
    <dl class="defs">{{DEFS}}</dl>
  </section>

  <section>
    <h2>Sources</h2>
    <p class="hint">Where postings come from. Six survived; the boards that were
    tried and dropped are documented, with their numbers, in the README.</p>
    <table class="tbl">
      <thead><tr><th>Source</th><th class="r">Last sync</th></tr></thead>
      <tbody>{{ROWS}}</tbody>
    </table>
  </section>

  <section>
    <h2>ATS adapters</h2>
    <p class="hint">One Playwright adapter per application system, over a shared
    base that handles resume and cover-letter upload.</p>
    <ul class="chips">{{CHIPS}}</ul>
  </section>

  <section>
    <h2>What it deliberately won't do</h2>
    <p class="hint">Limits chosen on purpose, not gaps left open.</p>
    <dl class="wont">{{WONT}}</dl>
  </section>
</main>

<footer class="wrap">
  <p>{{NOTEPLAIN}}</p>
  <p><a class="link" href="./">Interactive demo</a> ·
     <a class="link" href="https://github.com/sanketp9499/kestrel">Source on GitHub</a> ·
     <a class="link" href="https://sanketp.webflow.io">Sanket Pawar</a></p>
</footer>
</html>
"""
    import re as _re
    subs = {
        "{{CSS}}": CSS,
        "{{META}}": _esc(lead + " " + _re.sub(r"<[^>]+>", "", tail)),
        "{{LEAD}}": _esc(lead),
        "{{TAIL}}": tail,          # already escaped field-by-field in _headline
        "{{GENERATED}}": _esc(generated),
        "{{STRIP}}": _strip(hist),
        "{{FIRST}}": _esc(f"{hist['windowDays']} days ago"),
        "{{LEGEND}}": _legend(hist),
        "{{ICON}}": ICON_INFO,
        "{{NOTE}}": note,
        "{{TOTAL}}": str(total),
        "{{STACK}}": _stack(stage, total),
        "{{DEFS}}": _defs(stage),
        "{{ROWS}}": rows,
        "{{CHIPS}}": chips,
        "{{WONT}}": wont,
        "{{NOTEPLAIN}}": _esc(tel.get("note", "")),
    }
    for k, v in subs.items():
        page = page.replace(k, v)
    return page
