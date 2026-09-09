#!/usr/bin/env python3
"""telemetry_page.py — Render the public pipeline-status page.

Split out of sync_dashboard.py because the page stopped being a debug dump and
became the one public surface that has to argue, to a stranger, that this
machine is real. Two rules shape it:

1. It runs on the product's own design system, read from brand_tokens, which is
   lifted from `design/jobhunt-mockup.html`: salmon accent #FA503D, Manrope over
   Inter. The old page hardcoded GitHub's #0d1117 and looked like a different
   product from the demo it sits next to.
2. It reports the run record, not a row of green lights. `run_history.py`
   separates a full sweep from a run that exited in under two minutes, and the
   page shows that difference, because a status page where everything is always
   green is a status page nobody reads twice.

Server-rendered, no JavaScript, no external requests — the fonts are inlined as
woff2 data URIs — so it survives being opened from a GitHub Pages URL on a
recruiter's phone with a bad connection.
"""
import datetime
import html

import brand_tokens
import telemetry_css


# Colours, fonts and the light/dark contract all come from the mockup via
# brand_tokens; layout and type come from telemetry_css. Nothing about the
# look is decided in this file.
CSS = telemetry_css.CSS

ICON_INFO = ('<svg width="15" height="15" viewBox="0 0 24 24" fill="none" '
             'stroke="currentColor" stroke-width="1.9" stroke-linecap="round" '
             'aria-hidden="true"><circle cx="12" cy="12" r="9"/>'
             '<path d="M12 11v5M12 7.6v.1"/></svg>')

# Verdict -> (css var, label, what it means in plain words)
# The accent is the brand, not a status. Run outcomes read from the semantic
# scale only, so salmon never means "good" on one surface and "brand" on another.
VERDICT_META = {
    "clean":   ("var(--ok)", "Full sweep",
                "sourced, scored and prepared"),
    "noop":    ("var(--warn)", "Short exit",
                "exited before doing the work"),
    "errors":  ("var(--crit)", "Errored",
                "finished with a non-zero exit code"),
    # Neutral, not critical: an unfinished log means the outcome is unknown, and
    # painting unknown as failure is its own kind of dishonesty.
    "partial": ("var(--neutral)", "Incomplete",
                "started, never logged a finish"),
    "norun":   ("var(--border-strong)", "No run",
                "the machine was off"),
}

STAGE_META = [
    ("not",       "Wishlist",  "Saved and scored. Not applied to."),
    ("applied",   "Applied",   "Submitted, with a confirmation captured."),
    ("captcha",   "CAPTCHA",   "Prepared, then handed to a human to finish."),
    ("closed",    "Closed",    "Rejected, or the posting came down."),
    ("interview", "Interview", "A reply asking to talk."),
]
# Interview takes the accent: it is the one number the whole machine exists to
# move, and salmon is where the eye lands.
STAGE_COLOR = {"not": "var(--border-strong)", "applied": "var(--ok)",
               "captcha": "var(--warn)", "closed": "var(--neutral)",
               "interview": "var(--accent)"}

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
        cls = ' class="key"' if key == "interview" else ""
        out.append(
            f'<div{cls}><dt><span class="swatch" '
            f'style="background:{STAGE_COLOR[key]}"></span>{label}</dt>'
            f'<dd class="n">{n}</dd><dd>{meaning}</dd></div>')
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
<meta name="description" content="{{META}}">
<style>{{FONTS}}</style>
<style>{{THEME}}</style>
<style>{{CSS}}</style>

<header>
  <div class="wrap bar">
    <a class="mark" href="./">
      <span class="glyph" aria-hidden="true">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#0A0A0A"
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
        "{{FONTS}}": brand_tokens.FONTS,
        "{{THEME}}": brand_tokens.THEME,
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
