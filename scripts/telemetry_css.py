"""telemetry_css.py — Layout and type for the public status page.

Colours are not defined here. They arrive from brand_tokens.THEME, which is
lifted verbatim from `design/jobhunt-mockup.html`: the accent is salmon
(#FA503D) and status meaning is carried by --ok / --warn / --neutral, so a run
verdict can never be mistaken for a brand colour or the other way round.
"""

CSS = """
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.6 'InterVar',-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  font-variant-numeric:tabular-nums;
  -webkit-font-smoothing:antialiased;
}
h1,h2,.mark,.defs .n,.legend b{font-family:'ManropeVar','InterVar',system-ui,sans-serif}
::selection{background:var(--accent); color:#0A0A0A}
:focus-visible{outline:2px solid var(--accent); outline-offset:3px;
  border-radius:var(--radius-sm)}
*{scrollbar-color:var(--border-strong) transparent; scrollbar-width:thin}
::-webkit-scrollbar{height:10px;width:10px}
::-webkit-scrollbar-thumb{background:var(--border-strong); border-radius:99px}
::-webkit-scrollbar-track{background:transparent}
a{color:inherit; text-decoration:none}
a.link{text-decoration:underline; text-decoration-color:var(--border-strong);
  text-underline-offset:3px; transition:text-decoration-color .15s, color .15s}
a.link:hover{color:var(--accent-ink); text-decoration-color:var(--accent)}

.wrap{max-width:860px; margin:0 auto; padding:0 24px}

header{border-bottom:1px solid var(--border); background:var(--bg);
  position:sticky; top:0; z-index:5}
.bar{display:flex; align-items:center; gap:20px; height:60px}
.mark{display:flex; align-items:center; gap:10px; font-weight:700;
  letter-spacing:-.015em; margin-right:auto}
.glyph{width:26px; height:26px; border-radius:7px;
  background:var(--accent); display:grid; place-items:center; flex:none}
/* The mockup's own current-page treatment: an accent-soft pill with
   accent-ink text, the same grammar as its pressed filters and selected rows. */
nav{display:flex; gap:6px; font-size:13.5px; color:var(--muted)}
nav a{padding:5px 11px; border-radius:99px}
nav a:hover{background:var(--surface-2); color:var(--ink)}
nav a[aria-current=page]{background:var(--accent-soft); color:var(--accent-ink);
  font-weight:600}

.lede{padding:52px 0 8px}
h1{font-size:clamp(26px,4.2vw,34px); line-height:1.18; letter-spacing:-.024em;
  font-weight:700; margin:0 0 14px; max-width:26ch; text-wrap:balance}
.sub{color:var(--muted); font-size:14.5px; margin:0; max-width:66ch}
.sub b{color:var(--ink); font-weight:600}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:.92em}

section{padding:36px 0 34px; border-top:1px solid var(--border)}
section:first-of-type{border-top:0; padding-top:22px}
section > :last-child{margin-bottom:0}
h2{font-size:17px; font-weight:700; letter-spacing:-.015em; margin:0 0 6px}
.hint{color:var(--muted); font-size:13.5px; margin:0 0 20px; max-width:68ch}

/* ---- run record ------------------------------------------------------- */
.record{background:var(--surface); border:1px solid var(--border);
  border-radius:var(--radius); padding:22px 22px 16px; box-shadow:var(--shadow)}
.strip{display:flex; gap:2px; align-items:flex-end; height:64px}
.day{flex:1 1 0; min-width:3px; position:relative; height:100%;
  display:flex; align-items:flex-end}
.day i{display:block; width:100%; border-radius:2px;
  height:var(--h); background:var(--c);
  transform-origin:bottom; animation:grow .5s cubic-bezier(.16,1,.3,1) backwards;
  animation-delay:calc(var(--i) * 7ms)}
/* Absence reads as a floor tick, not a full-height column: a day the machine
   was off should not occupy more ink than a day it worked. */
.day.norun i{height:3px; background:var(--border-strong); animation:none}
@keyframes grow{from{transform:scaleY(0)} to{transform:scaleY(1)}}
@media (prefers-reduced-motion: reduce){.day i{animation:none}}
.axis{display:flex; justify-content:space-between; color:var(--muted);
  font-size:12px; margin-top:10px; padding-top:10px;
  border-top:1px solid var(--border)}
.legend{display:flex; flex-wrap:wrap; gap:6px 18px; margin:14px 0 0;
  padding:0; list-style:none; font-size:13px}
.legend li{display:flex; align-items:center; gap:8px}
.swatch{width:9px; height:9px; border-radius:2px; flex:none;
  box-shadow:inset 0 0 0 1px rgba(0,0,0,.07)}
.legend b{font-weight:650}
.legend span{color:var(--muted)}

.note{display:flex; gap:12px; margin:22px 0 0; padding:14px 16px;
  background:var(--warn-soft); border:1px solid var(--border);
  border-radius:var(--radius-sm); font-size:13.5px; line-height:1.55}
.note svg{flex:none; margin-top:2px; color:var(--warn)}
.note p{margin:0}
.note strong{font-weight:650}

/* ---- stage bar --------------------------------------------------------- */
.stack{display:flex; gap:2px; height:16px; margin:0 0 4px}
.stack span{border-radius:2px; min-width:4px}
.defs{margin:0; padding:0}
.defs div{display:grid; grid-template-columns:150px 3.2em 1fr;
  gap:0 20px; align-items:baseline; padding:11px 0;
  border-bottom:1px solid var(--border)}
.defs div:last-child{border-bottom:0}
/* Interview is the one row the machine exists to produce; the mockup marks its
   selected state with accent-soft, so that is what marks it here. */
.defs div.key{background:var(--accent-soft); border-bottom:0;
  border-radius:var(--radius-sm); padding-left:12px; padding-right:12px;
  margin:2px -12px 0}
.defs div.key dt, .defs div.key .n{color:var(--accent-ink)}
.defs div.key dd{color:var(--accent-ink); opacity:.8}
.defs dt{display:flex; align-items:center; gap:10px; font-weight:600;
  font-size:14px}
.defs dd{margin:0; color:var(--muted); font-size:13.5px}
.defs .n{font-weight:700; font-size:15px; text-align:right; color:var(--ink)}

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
.dot{display:inline-flex; align-items:baseline; gap:9px; font-size:14px}
.dot::before{content:''; width:7px; height:7px; border-radius:99px;
  background:var(--ok); flex:none; transform:translateY(-1px)}
.dot.reconnect::before{background:var(--warn)}
.dot.broken::before{background:var(--crit)}
.state{font-style:normal; color:var(--warn); font-weight:600}

.chips{display:flex; flex-wrap:wrap; gap:7px; margin:0; padding:0;
  list-style:none}
.chips li{border:1px solid var(--border); background:var(--surface);
  border-radius:99px; padding:5px 13px; font-size:13px}

.wont{display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
  gap:0 36px; margin:0}
.wont div{padding:13px 0; border-top:1px solid var(--border)}
.wont dt{font-weight:650; font-size:14px; margin:0 0 3px}
.wont dd{margin:0; color:var(--muted); font-size:13.5px; line-height:1.55}

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
