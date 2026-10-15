"""
ULTRA GAMING VPN — dynamic decoy site.

Every request to "/" or any unknown path returns a random corporate
landing page so scanners cannot fingerprint the deployment as a proxy.
Four distinct industries / color palettes rotate per-request; even the same
template mutates slightly (year, stats) so two consecutive fetches are not
byte-identical.
"""

from __future__ import annotations

import random
import time

# Each entry is a complete HTML document. Keep them self-contained (inline
# CSS, no external assets) so the decoy works even when the CDN is the
# only thing reaching the client.
_TEMPLATES: list[str] = [
    # 1 — Nebula Cloud Studio (GPU rendering) — indigo/cyan
    r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nebula Cloud Studio — Real-time Rendering Infrastructure</title>
<meta name="description" content="Nebula Cloud Studio delivers GPU-accelerated rendering and real-time asset pipelines for interactive media teams.">
<meta name="robots" content="noindex,nofollow">
<style>*{box-sizing:border-box;margin:0;padding:0}
body{font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#1f2937;background:#fff}
a{color:#2563eb;text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:960px;margin:0 auto;padding:0 24px}
header{border-bottom:1px solid #e5e7eb;padding:18px 0}
header .wrap{display:flex;align-items:center;gap:12px}
.logo{width:28px;height:28px;border-radius:6px;background:linear-gradient(135deg,#6366f1,#0ea5e9)}
.brand{font-weight:700;font-size:17px;letter-spacing:-.2px}
nav{margin-left:auto;display:flex;gap:22px;font-size:14px;color:#4b5563}
.hero{padding:78px 0 62px;border-bottom:1px solid #f3f4f6}
.hero h1{font-size:40px;line-height:1.15;letter-spacing:-1px;max-width:620px;margin-bottom:18px}
.hero p{font-size:18px;color:#4b5563;max-width:560px;margin-bottom:26px}
.btn{display:inline-block;background:#111827;color:#fff;padding:11px 22px;border-radius:7px;font-size:15px;font-weight:500}
.btn:hover{background:#374151;text-decoration:none}
.btn.ghost{background:#fff;color:#111827;border:1px solid #d1d5db;margin-left:10px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:28px;padding:58px 0}
.card h3{font-size:16px;margin-bottom:8px}
.card p{font-size:14.5px;color:#6b7280}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:20px;padding:38px 0;border-top:1px solid #f3f4f6;border-bottom:1px solid #f3f4f6;text-align:center}
.stats b{display:block;font-size:26px;letter-spacing:-.5px}
.stats span{font-size:13px;color:#6b7280}
footer{padding:34px 0;font-size:13.5px;color:#6b7280}
footer .wrap{display:flex;flex-wrap:wrap;gap:18px;align-items:center}
footer nav{margin-left:auto}
@media(max-width:760px){.grid,.stats{grid-template-columns:1fr 1fr}.hero h1{font-size:30px}nav{display:none}}
</style></head><body>
<header><div class="wrap"><div class="logo"></div><div class="brand">Nebula Cloud Studio</div>
<nav><a href="/">Platform</a><a href="/">Pricing</a><a href="/">Docs</a><a href="/">Contact</a></nav></div></header>
<section class="hero"><div class="wrap">
<h1>GPU rendering infrastructure for interactive media teams</h1>
<p>Distributed frame pipelines, asset streaming and shader compilation — provisioned in seconds, billed per second.</p>
<a class="btn" href="/">Start a project</a><a class="btn ghost" href="/">Read the docs</a>
</div></section>
<div class="wrap"><div class="grid">
<div class="card"><h3>Frame pipelines</h3><p>Queue thousands of render jobs with automatic retry, checkpointing and artifact deduplication.</p></div>
<div class="card"><h3>Asset streaming</h3><p>Progressive mesh and texture delivery with regional edge caches close to your artists.</p></div>
<div class="card"><h3>Shader cache</h3><p>Shared compilation cache across build agents cuts cold-start times on large scenes.</p></div>
<div class="card"><h3>Observability</h3><p>Per-job traces, GPU utilisation and cost attribution exported to your existing stack.</p></div>
<div class="card"><h3>Team workspaces</h3><p>Role-based access, review links and immutable revision history for every deliverable.</p></div>
<div class="card"><h3>API first</h3><p>Everything in the console is available through a documented REST and gRPC surface.</p></div>
</div></div>
<div class="wrap"><div class="stats">
<div><b>99.95%</b><span>Monthly uptime</span></div><div><b>__S1__</b><span>Median queue latency</span></div><div><b>14</b><span>Edge regions</span></div><div><b>2.1 PB</b><span>Assets served</span></div>
</div></div>
<footer><div class="wrap"><span>© __YEAR__ Nebula Cloud Studio</span><nav><a href="/">Status</a><a href="/">Privacy</a><a href="/">Terms</a></nav></div></footer>
</body></html>""",

    # 2 — Vertex Data Systems (analytics / observability) — emerald/slate
    r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vertex Data Systems — Unified Observability Platform</title>
<meta name="description" content="Vertex ingests, correlates and alerts on metrics, logs and traces at petabyte scale.">
<meta name="robots" content="noindex,nofollow">
<style>*{box-sizing:border-box;margin:0;padding:0}
body{font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#0f172a;background:#f8fafc}
a{color:#0f766e;text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:960px;margin:0 auto;padding:0 24px}
header{border-bottom:1px solid #e2e8f0;padding:18px 0;background:#fff}
header .wrap{display:flex;align-items:center;gap:12px}
.logo{width:28px;height:28px;border-radius:7px;background:linear-gradient(135deg,#10b981,#06b6d4)}
.brand{font-weight:800;font-size:17px;letter-spacing:-.3px}
nav{margin-left:auto;display:flex;gap:22px;font-size:14px;color:#475569}
.hero{padding:76px 0 60px}
.hero h1{font-size:39px;line-height:1.14;letter-spacing:-.9px;max-width:640px;margin-bottom:16px}
.hero p{font-size:18px;color:#475569;max-width:580px;margin-bottom:28px}
.btn{display:inline-block;background:#0f172a;color:#fff;padding:11px 22px;border-radius:8px;font-size:15px;font-weight:600}
.btn:hover{background:#1e293b;text-decoration:none}
.btn.ghost{background:#fff;color:#0f172a;border:1px solid #cbd5e1;margin-left:10px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:28px;padding:56px 0}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:22px}
.card h3{font-size:15.5px;margin-bottom:7px}
.card p{font-size:14.2px;color:#64748b}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:18px;padding:36px 0;border-top:1px solid #e2e8f0;text-align:center}
.stats b{display:block;font-size:25px;letter-spacing:-.4px}
.stats span{font-size:13px;color:#64748b}
footer{padding:32px 0;font-size:13.5px;color:#64748b;border-top:1px solid #e2e8f0;background:#fff}
footer .wrap{display:flex;flex-wrap:wrap;gap:18px}
footer nav{margin-left:auto}
@media(max-width:760px){.grid,.stats{grid-template-columns:1fr 1fr}.hero h1{font-size:30px}nav{display:none}}
</style></head><body>
<header><div class="wrap"><div class="logo"></div><div class="brand">Vertex Data Systems</div>
<nav><a href="/">Product</a><a href="/">Solutions</a><a href="/">Pricing</a><a href="/">Docs</a></nav></div></header>
<section class="hero"><div class="wrap">
<h1>One pipeline for metrics, logs and traces</h1>
<p>Ingest from any source, correlate in real time, and alert before your users notice. SOC 2 certified.</p>
<a class="btn" href="/">Start free trial</a><a class="btn ghost" href="/">View demo</a>
</div></section>
<div class="wrap"><div class="grid">
<div class="card"><h3>Petabyte ingest</h3><p>Scales horizontally with no hot shards. Backpressure-aware agents keep edge overhead low.</p></div>
<div class="card"><h3>Correlation engine</h3><p>Joins traces to logs and infra metrics automatically — no manual trace IDs.</p></div>
<div class="card"><h3>Alerting</h3><p>Anomaly detection and SLO burn-rate alerts with on-call routing and escalation.</p></div>
<div class="card"><h3>Log analytics</h3><p>Full-text search with columnar storage. Ask questions in SQL or natural language.</p></div>
<div class="card"><h3>Distributed tracing</h3><p>Head-based sampling with tail overrides keeps the interesting traces, drops the noise.</p></div>
<div class="card"><h3>Integrations</h3><p>200+ collectors and exporters. OpenTelemetry native, Prometheus compatible.</p></div>
</div></div>
<div class="wrap"><div class="stats">
<div><b>__S2__M</b><span>Events / second</span></div><div><b>__S1__</b><span>Query latency p95</span></div><div><b>99.99%</b><span>Ingest availability</span></div><div><b>180+</b><span>Integrations</span></div>
</div></div>
<footer><div class="wrap"><span>© __YEAR__ Vertex Data Systems, Inc.</span><nav><a href="/">Security</a><a href="/">Privacy</a><a href="/">Terms</a></nav></div></footer>
</body></html>""",

    # 3 — Aurelia BioLabs (biotech / research) — rose/amber
    r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Aurelia BioLabs — Computational Biology Platform</title>
<meta name="description" content="Aurelia accelerates discovery with collaborative workspaces for genomic pipelines and structured assay data.">
<meta name="robots" content="noindex,nofollow">
<style>*{box-sizing:border-box;margin:0;padding:0}
body{font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#1c1917;background:#fffbeb}
a{color:#be123c;text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:960px;margin:0 auto;padding:0 24px}
header{border-bottom:1px solid #fde68a;padding:18px 0;background:#fff}
header .wrap{display:flex;align-items:center;gap:12px}
.logo{width:28px;height:28px;border-radius:8px;background:linear-gradient(135deg,#f59e0b,#e11d48)}
.brand{font-weight:800;font-size:17px;letter-spacing:-.2px}
nav{margin-left:auto;display:flex;gap:22px;font-size:14px;color:#57534e}
.hero{padding:74px 0 58px}
.hero h1{font-size:38px;line-height:1.14;letter-spacing:-.8px;max-width:620px;margin-bottom:16px}
.hero p{font-size:18px;color:#57534e;max-width:560px;margin-bottom:28px}
.btn{display:inline-block;background:#1c1917;color:#fff;padding:11px 22px;border-radius:8px;font-size:15px;font-weight:600}
.btn:hover{background:#44403c;text-decoration:none}
.btn.ghost{background:#fff;color:#1c1917;border:1px solid #d6d3d1;margin-left:10px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:26px;padding:54px 0}
.card h3{font-size:15.5px;margin-bottom:7px}
.card p{font-size:14.2px;color:#78716c}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:18px;padding:36px 0;border-top:1px solid #fde68a;border-bottom:1px solid #fde68a;text-align:center;background:#fff}
.stats b{display:block;font-size:25px}
.stats span{font-size:13px;color:#78716c}
footer{padding:32px 0;font-size:13.5px;color:#78716c}
footer .wrap{display:flex;flex-wrap:wrap;gap:18px}
footer nav{margin-left:auto}
@media(max-width:760px){.grid,.stats{grid-template-columns:1fr 1fr}.hero h1{font-size:29px}nav{display:none}}
</style></head><body>
<header><div class="wrap"><div class="logo"></div><div class="brand">Aurelia BioLabs</div>
<nav><a href="/">Platform</a><a href="/">Research</a><a href="/">Pricing</a><a href="/">Company</a></nav></div></header>
<section class="hero"><div class="wrap">
<h1>From sequence to insight, faster</h1>
<p>Collaborative workspaces for genomic pipelines, assay management and reproducible analysis — trusted by 300+ labs.</p>
<a class="btn" href="/">Request access</a><a class="btn ghost" href="/">Read case studies</a>
</div></section>
<div class="wrap"><div class="grid">
<div class="card"><h3>Pipeline builder</h3><p>Drag-and-drop workflow designer with versioned steps and automatic provenance tracking.</p></div>
<div class="card"><h3>Assay hub</h3><p>Structured capture for wet-lab assays with barcode scanning and freezer integration.</p></div>
<div class="card"><h3>Genome browser</h3><p>Interactive variant inspection with population frequency overlays and pathogenicity scores.</p></div>
<div class="card"><h3>Collaboration</h3><p>Share workspaces with fine-grained permissions and review threads on every result.</p></div>
<div class="card"><h3>Compliance</h3><p>21 CFR Part 11 ready with audit trails, e-signatures and validated pipelines.</p></div>
<div class="card"><h3>Scale</h3><p>Elastic compute for alignment and variant calling — pay only for the base pairs you process.</p></div>
</div></div>
<div class="wrap"><div class="stats">
<div><b>4.2B</b><span>Reads / day</span></div><div><b>__S1__</b><span>Pipeline p50</span></div><div><b>300+</b><span>Labs onboarded</span></div><div><b>HIPAA</b><span>Compliant</span></div>
</div></div>
<footer><div class="wrap"><span>© __YEAR__ Aurelia BioLabs</span><nav><a href="/">Privacy</a><a href="/">Security</a><a href="/">Contact</a></nav></div></footer>
</body></html>""",

    # 4 — Northwind Logistics (supply chain) — sky/slate
    r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Northwind Logistics — Supply Chain Control Tower</title>
<meta name="description" content="Northwind gives operators real-time visibility across freight, warehouse and last-mile — with predictive ETAs.">
<meta name="robots" content="noindex,nofollow">
<style>*{box-sizing:border-box;margin:0;padding:0}
body{font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#0f172a;background:#fff}
a{color:#0284c7;text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:960px;margin:0 auto;padding:0 24px}
header{border-bottom:1px solid #e0f2fe;padding:18px 0}
header .wrap{display:flex;align-items:center;gap:12px}
.logo{width:28px;height:28px;border-radius:6px;background:linear-gradient(135deg,#0284c7,#0f172a)}
.brand{font-weight:800;font-size:17px;letter-spacing:-.3px}
nav{margin-left:auto;display:flex;gap:22px;font-size:14px;color:#475569}
.hero{padding:76px 0 60px;border-bottom:1px solid #f1f5f9}
.hero h1{font-size:39px;line-height:1.14;letter-spacing:-.9px;max-width:640px;margin-bottom:16px}
.hero p{font-size:18px;color:#475569;max-width:580px;margin-bottom:28px}
.btn{display:inline-block;background:#0f172a;color:#fff;padding:11px 22px;border-radius:8px;font-size:15px;font-weight:600}
.btn:hover{background:#1e293b;text-decoration:none}
.btn.ghost{background:#fff;color:#0f172a;border:1px solid #cbd5e1;margin-left:10px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:28px;padding:56px 0}
.card h3{font-size:15.5px;margin-bottom:7px}
.card p{font-size:14.2px;color:#64748b}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:18px;padding:36px 0;border-top:1px solid #e0f2fe;border-bottom:1px solid #e0f2fe;text-align:center}
.stats b{display:block;font-size:25px;letter-spacing:-.4px}
.stats span{font-size:13px;color:#64748b}
footer{padding:32px 0;font-size:13.5px;color:#64748b}
footer .wrap{display:flex;flex-wrap:wrap;gap:18px}
footer nav{margin-left:auto}
@media(max-width:760px){.grid,.stats{grid-template-columns:1fr 1fr}.hero h1{font-size:30px}nav{display:none}}
</style></head><body>
<header><div class="wrap"><div class="logo"></div><div class="brand">Northwind Logistics</div>
<nav><a href="/">Platform</a><a href="/">Networks</a><a href="/">Pricing</a><a href="/">Company</a></nav></div></header>
<section class="hero"><div class="wrap">
<h1>See every shipment, predict every delay</h1>
<p>Real-time visibility across freight, warehouse and last-mile — with ML-powered ETAs your customers can trust.</p>
<a class="btn" href="/">Book a demo</a><a class="btn ghost" href="/">Explore platform</a>
</div></section>
<div class="wrap"><div class="grid">
<div class="card"><h3>Control tower</h3><p>Single pane for ocean, air and road — with exception management that surfaces only what needs action.</p></div>
<div class="card"><h3>Predictive ETA</h3><p>Models trained on 12M shipments account for weather, congestion and carrier history.</p></div>
<div class="card"><h3>Warehouse ops</h3><p>Slotting and wave planning integrated with WMS — no rip-and-replace required.</p></div>
<div class="card"><h3>Carrier network</h3><p>Pre-vetted carriers with instant booking and automated rate shopping.</p></div>
<div class="card"><h3>Proof of delivery</h3><p>Photo, signature and geofence capture with customer-facing tracking pages.</p></div>
<div class="card"><h3>Analytics</h3><p>Lane cost, OTIF and dwell-time dashboards — shareable with shippers and 3PLs.</p></div>
</div></div>
<div class="wrap"><div class="stats">
<div><b>__S2__k</b><span>Shipments / month</span></div><div><b>__S1__</b><span>ETA accuracy</span></div><div><b>42</b><span>Countries</span></div><div><b>24/7</b><span>Ops centre</span></div>
</div></div>
<footer><div class="wrap"><span>© __YEAR__ Northwind Logistics</span><nav><a href="/">Privacy</a><a href="/">Security</a><a href="/">Careers</a></nav></div></footer>
</body></html>""",
]


def get_html() -> str:
    """Pick one template at random and inject per-request mutations."""
    tpl = random.choice(_TEMPLATES)
    year = str(time.gmtime().tm_year)
    # Slight jitter so two fetches are not byte-identical even when the same
    # template is chosen — defeats trivial hash fingerprinting.
    s1_choices = ["22 ms", "27 ms", "31 ms", "34 ms", "38 ms", "19 ms"]
    s2_choices = ["18.4", "21.7", "24.1", "16.9", "12.3", "28.6"]
    html = tpl.replace("__YEAR__", year)
    html = html.replace("__S1__", random.choice(s1_choices))
    html = html.replace("__S2__", random.choice(s2_choices))
    # Tiny HTML comment with a random nonce — invisible to users, breaks
    # exact-body hash without affecting rendering.
    html = html.replace(
        "</body>",
        f"<!-- {random.getrandbits(32):08x} --></body>",
    )
    return html


def count() -> int:
    return len(_TEMPLATES)
