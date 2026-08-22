from pathlib import Path
p=Path(__file__).resolve().parents[1]/'webapp/src/prototype.css'
t=p.read_text()
marker='.quota-card {'
if marker not in t:
 t += r'''

.quota-card {
  margin: 10px 0 12px;
  padding: 12px 13px;
  border: 1px solid #c9e5e3;
  border-radius: 12px;
  background: #ffffff;
}
.quota-card > div { display:flex; align-items:baseline; justify-content:space-between; gap:10px; }
.quota-card span, .quota-card p { color:var(--muted); font-size:11px; }
.quota-card strong { color:var(--teal-dark); font-size:15px; }
.quota-card p { margin:5px 0 8px; }
.quota-track { display:block; height:5px; overflow:hidden; border-radius:999px; background:#e6eeee; }
.quota-track i { display:block; height:100%; border-radius:inherit; background:var(--teal); transition:width 180ms ease; }
.live-dot.loading, .live-dot.unknown { background:#a1a8b4; box-shadow:0 0 0 3px rgba(113,121,137,.12); }
.live-dot.stale { background:#d28b16; box-shadow:0 0 0 3px rgba(210,139,22,.12); }
.venue-health strong.unknown { color:#7b8492; }
.term-choices button { min-height:42px; }
.term-choices button.locked { border-style:dashed; background:#f2f4f5; color:#8a919c; }
.term-choices button.locked svg { flex:0 0 auto; }
.term-note { margin:10px 0 0; color:var(--teal-dark); font-size:12px; line-height:1.55; }
'''
p.write_text(t)
print('css patched')