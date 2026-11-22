"""timeline.html: the demo view of a workflow-trace run, one self-contained page.

    1. where things run (data site → compute sites)
    2. per workflow: each booked transfer (waiting, then reserved and running; its deadline) and each stage
       of tasks, on one time axis
    3. how full the two transit links are: our bookings per workflow on top of others' registered traffic
    4. what the network agent said: graph B findings, and the SciNet demand forecast against what happened
"""

import html
import re
from datetime import datetime, timedelta
from pathlib import Path

from .cosim import CosimResult, TransferRecord, WorkflowRun

WIDTH, LEFT, RIGHT = 1100, 250, 30                    # svg width, label column, right margin
ROW = 22
WF_COLORS = ["var(--wf1)", "var(--wf2)", "var(--wf3)"]


def label(record: TransferRecord) -> str:
    chrom = re.search(r"chr\d+", record.file)
    chrom = chrom.group(0) if chrom else ""
    if "annotation" in record.file:
        kind = "annotations"
    elif record.file.endswith(".vcf"):
        kind = "genotypes"
    elif record.file.startswith("sifted"):
        kind = "sifted"
    else:
        kind = record.file
    return f"{chrom} {kind} · {record.nbytes / 1e12:.2f} TB → {record.dst.split('-')[0].upper()}"


def path_name(path: tuple[str, ...]) -> str:
    hops = [link.split(":")[0] for link in path]
    return "detour (L4–L5, 40 G)" if "L4" in hops else "main (L2, 100 G)" if "L2" in hops else " ".join(hops)


class Axis:
    def __init__(self, start: datetime, end: datetime):
        self.start, self.end = start, end

    def x(self, moment: datetime) -> float:
        span = (self.end - self.start).total_seconds()
        return LEFT + (WIDTH - LEFT - RIGHT) * (moment - self.start).total_seconds() / span

    def ticks(self, every_minutes: int = 5) -> list[datetime]:
        out, moment = [], self.start
        while moment <= self.end:
            out.append(moment)
            moment += timedelta(minutes=every_minutes)
        return out


def esc(text) -> str:
    return html.escape(str(text))


def axis_svg(axis: Axis, height: float) -> str:
    parts = []
    for tick in axis.ticks():
        x = axis.x(tick)
        parts.append(f'<line x1="{x:.1f}" y1="18" x2="{x:.1f}" y2="{height}" class="grid"/>'
                     f'<text x="{x:.1f}" y="12" class="tick" text-anchor="middle">{tick:%H:%M}</text>')
    return "".join(parts)


def gantt(runs: list[WorkflowRun], result: CosimResult, axis: Axis) -> str:
    rows = []                                         # (kind, workflow index, payload)
    for i, run in enumerate(runs):
        rows.append(("header", i, run))
        booked = sorted((r for r in result.transfers if r.booked and r.workflow_id == run.workflow_id),
                        key=lambda r: (r.ready_at, r.offer_start))
        rows += [("transfer", i, r) for r in booked]
        stages: dict[str, list] = {}
        for task in result.tasks:
            if task.workflow_id == run.workflow_id and task.started_at:
                stages.setdefault(run.workflow.tasks[task.task_id].program, []).append(task)
        for program, tasks in sorted(stages.items(), key=lambda kv: min(t.started_at for t in kv[1])):
            rows.append(("stage", i, (program, tasks)))
    height = 24 + len(rows) * ROW
    parts = [axis_svg(axis, height)]
    y = 24
    for kind, i, payload in rows:
        color = WF_COLORS[i % len(WF_COLORS)]
        if kind == "header":
            parts.append(f'<text x="4" y="{y + 15}" class="wf" style="fill:{color}">{esc(payload.workflow_id)} · starts '
                         f'{payload.start:%H:%M}</text>')
        elif kind == "transfer":
            r = payload
            x0, x1, x2 = axis.x(r.ready_at), axis.x(r.offer_start), axis.x(r.finished_at or r.offer_end)
            late = r.finished_at and r.finished_at > r.latest_finish
            detour = "L4" in {link.split(":")[0] for link in r.path}
            parts.append(f'<text x="14" y="{y + 15}" class="lbl">{esc(label(r))}</text>')
            if x1 > x0 + 0.5:
                parts.append(f'<line x1="{x0:.1f}" y1="{y + 11}" x2="{x1:.1f}" y2="{y + 11}" class="wait"/>')
            parts.append(f'<rect x="{x1:.1f}" y="{y + 4}" width="{max(x2 - x1, 2):.1f}" height="14" rx="3" '
                         f'class="{"detour" if detour else "main"}" style="fill:{color}">'
                         f'<title>{esc(r.transfer_id)}: requested {r.ready_at:%H:%M:%S}, reserved {r.offer_start:%H:%M:%S}–'
                         f'{r.offer_end:%H:%M:%S} @ {r.gbps:g} Gbps on {esc(path_name(r.path))}, deadline '
                         f'{r.latest_finish:%H:%M:%S}</title></rect>')
            xd = axis.x(r.latest_finish)
            parts.append(f'<line x1="{xd:.1f}" y1="{y + 2}" x2="{xd:.1f}" y2="{y + 20}" class="{"miss" if late else "deadline"}"/>')
            if late:
                parts.append(f'<text x="{max(x2, xd) + 6:.1f}" y="{y + 15}" class="misslbl">late</text>')
        else:
            program, tasks = payload
            start, end = min(t.started_at for t in tasks), max(t.finished_at for t in tasks)
            site = tasks[0].site.split("-")[0].upper()
            parts.append(f'<text x="14" y="{y + 15}" class="lbl stagelbl">{esc(program)} ×{len(tasks)} @ {site}</text>'
                         f'<rect x="{axis.x(start):.1f}" y="{y + 6}" width="{max(axis.x(end) - axis.x(start), 2):.1f}" '
                         f'height="10" rx="2" class="stage"/>')
        y += ROW
    return f'<svg viewBox="0 0 {WIDTH} {height}" role="img" aria-label="workflow timeline">{"".join(parts)}</svg>'


def link_load(config: dict, runs: list[WorkflowRun], result: CosimResult, axis: Axis, link: str, capacity: float,
              title: str) -> str:
    """Stacked step chart: others' registered traffic, then our bookings per workflow."""
    day = axis.start.date()
    layers = []                                       # (name, color, [(start, end, gbps)])
    others = [(datetime.combine(day, datetime.strptime(b["start"], "%H:%M").time(), axis.start.tzinfo),
               datetime.combine(day, datetime.strptime(b["end"], "%H:%M").time(), axis.start.tzinfo), b["gbps"])
              for b in config["background"] if b["link"] == link]
    layers.append(("others (registered)", "var(--others)", others))
    for i, run in enumerate(runs):
        ours = [(r.offer_start, r.offer_end, r.gbps) for r in result.transfers
                if r.booked and r.workflow_id == run.workflow_id and link in r.path]
        layers.append((run.workflow_id, WF_COLORS[i % len(WF_COLORS)], ours))
    height, top, bottom = 150, 22, 130
    scale = (bottom - top) / capacity
    cuts = sorted({axis.start, axis.end} | {m for _, _, spans in layers for a, b, _ in spans for m in (a, b)
                                            if axis.start < m < axis.end})
    parts = [axis_svg(axis, bottom)]
    base = {c: 0.0 for c in cuts[:-1]}
    for name, color, spans in layers:
        for a, b in zip(cuts, cuts[1:]):
            gbps = sum(g for s, e, g in spans if s <= a < e)
            if gbps <= 0:
                continue
            y1 = bottom - (base[a] + gbps) * scale
            parts.append(f'<rect x="{axis.x(a):.1f}" y="{y1:.1f}" width="{axis.x(b) - axis.x(a):.1f}" '
                         f'height="{gbps * scale:.1f}" style="fill:{color}" class="area"><title>{esc(name)}: {gbps:g} Gbps '
                         f'{a:%H:%M:%S}–{b:%H:%M:%S}</title></rect>')
            base[a] += gbps
    parts.append(f'<line x1="{LEFT}" y1="{top}" x2="{WIDTH - RIGHT}" y2="{top}" class="cap"/>'
                 f'<text x="{LEFT - 8}" y="{top + 4}" class="tick" text-anchor="end">{capacity:g} Gbps</text>'
                 f'<text x="{LEFT - 8}" y="{bottom}" class="tick" text-anchor="end">0</text>'
                 f'<text x="4" y="{top + 30}" class="wf">{esc(title)}</text>')
    legend = "".join(f'<span><i style="background:{color}"></i>{esc(name)}</span>' for name, color, _ in layers)
    return f'<svg viewBox="0 0 {WIDTH} {height}" role="img" aria-label="{esc(title)}">{"".join(parts)}</svg>' \
           f'<div class="legend">{legend}</div>'


def write_timeline(config: dict, runs: list[WorkflowRun], result: CosimResult, metrics: dict, run_dir: Path) -> None:
    start = min(run.start for run in runs)
    finished = [t.finished_at for t in result.tasks if t.finished_at] + \
               [r.finished_at for r in result.transfers if r.finished_at]
    end = max(finished) if finished else start + timedelta(hours=1)
    axis = Axis(start, start + timedelta(minutes=5 * -(-int((end - start).total_seconds() // 60 + 1) // 5)))
    wf = metrics["workflows"]
    booked = [r for r in result.transfers if r.booked]
    late = sum(1 for r in booked if r.finished_at and r.finished_at > r.latest_finish)
    cards = [("Workflows", f"{len(runs)} × 1000genome, {runs[0].data_scale:g}× data"),
             ("Booked transfers", f"{len(booked)} ({sum(r.nbytes for r in booked) / 1e12:.1f} TB), {late} late"),
             ("Best effort", f"{sum(1 for r in result.transfers if not r.booked)} small files"),
             ("Makespan", " / ".join(f"{k} {v['makespan_min']} min" for k, v in wf.items())),
             ("Graph B checks", f"{result.ticks} ticks, {result.deviations} deviations"),
             ("Demand forecast", f"{metrics['demand_forecast']['booked_transfers_predicted_before_request']} transfers "
                                 f"foreseen, {metrics['demand_forecast']['would_not_fit_reports']} would-not-fit warnings")]
    predicted = sorted((r for r in booked if r.first_prediction), key=lambda r: r.ready_at)
    forecast_rows = "".join(
        f"<tr><td>{esc(r.workflow_id)}</td><td>{esc(label(r))}</td><td>{r.first_prediction:%H:%M:%S}</td>"
        f"<td>{r.last_prediction:%H:%M:%S}</td><td>{r.ready_at:%H:%M:%S}</td></tr>" for r in predicted)
    sites = config["program_sites"]
    by_site: dict[str, list[str]] = {}
    for program, site in sites.items():
        by_site.setdefault(site, []).append(program)
    site_line = " → ".join([f"<b>{esc(config['data_site'])}</b> (input data)"] +
                           [f"<b>{esc(site)}</b> ({esc(', '.join(programs))})" for site, programs in by_site.items()])
    order = config["cosim"]["request_order"]
    page = PAGE.format(
        title=esc(f"{config['tag']}"),
        subtitle=esc(f"{len(runs)} × 1000genome (WfCommons trace, 52 tasks), data × {runs[0].data_scale:g}, "
                     f"compute × {runs[0].compute_scale:g}; requests {'earliest deadline first' if order == 'edf' else 'in trace order'}"),
        sites=site_line,
        cards="".join(f'<div class="card"><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div></div>' for k, v in cards),
        gantt=gantt(runs, result, axis),
        main=link_load(config, runs, result, axis, "L2:esnet-atl>esnet-chi", 100, "L2 (main path)"),
        detour=link_load(config, runs, result, axis, "L4:esnet-atl>esnet-nash", 40, "L4 (detour)"),
        findings="".join(f"<li>{esc(f)}</li>" for f in result.runtime_findings) or "<li>none: no deviation</li>",
        forecast_rows=forecast_rows)
    (run_dir / "timeline.html").write_text(page)


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Workflow Trace Demo</title>
<style>
:root {{ --bg:#fafaf9; --card:#fff; --ink:#1d1d1f; --mute:#6b6b70; --line:#e2e2e6; --wf1:#2f6fde; --wf2:#e8590c;
  --wf3:#16a34a; --others:#c4c4cc; --miss:#dc2626; --stage:#8b8b94; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#161618; --card:#1f1f22; --ink:#ececef;
  --mute:#9a9aa2; --line:#34343a; --wf1:#6ea2ff; --wf2:#ff9a5a; --wf3:#4ade80; --others:#4a4a52; --miss:#f87171; --stage:#77777f; }} }}
:root[data-theme="dark"] {{ --bg:#161618; --card:#1f1f22; --ink:#ececef; --mute:#9a9aa2; --line:#34343a; --wf1:#6ea2ff;
  --wf2:#ff9a5a; --wf3:#4ade80; --others:#4a4a52; --miss:#f87171; --stage:#77777f; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.45 -apple-system,"Helvetica Neue","Segoe UI",sans-serif; }}
main {{ max-width:1140px; margin:0 auto; padding:24px 16px 48px; }}
h1 {{ font-size:22px; margin:0 0 4px; }} h2 {{ font-size:16px; margin:28px 0 8px; }}
.sub, .sites {{ color:var(--mute); margin:0 0 6px; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px; margin:16px 0 4px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:10px 12px; }}
.card .k {{ color:var(--mute); font-size:12px; }} .card .v {{ font-weight:600; margin-top:2px; }}
.panel {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px; overflow-x:auto; }}
svg {{ width:100%; min-width:760px; height:auto; display:block; }}
svg text {{ fill:var(--ink); font-size:12px; }} .tick {{ fill:var(--mute); font-size:11px; }}
.grid {{ stroke:var(--line); }} .wf {{ font-weight:700; font-size:13px; }} .lbl {{ font-size:12px; }}
.stagelbl {{ fill:var(--mute); }} .wait {{ stroke:var(--mute); stroke-dasharray:3 3; stroke-width:1.5; }}
.detour {{ opacity:.55; }} .stage {{ fill:var(--stage); opacity:.6; }}
.deadline {{ stroke:var(--mute); stroke-width:2; }} .miss {{ stroke:var(--miss); stroke-width:2.5; }}
.misslbl {{ fill:var(--miss); font-weight:700; font-size:11px; }} .cap {{ stroke:var(--ink); stroke-dasharray:4 3; }}
.area {{ opacity:.85; }}
.legend {{ display:flex; gap:16px; flex-wrap:wrap; color:var(--mute); font-size:12px; margin:4px 0 0 4px; }}
.legend i {{ display:inline-block; width:12px; height:12px; border-radius:2px; margin-right:5px; vertical-align:-2px; }}
.key {{ color:var(--mute); font-size:12px; margin-top:6px; }}
table {{ border-collapse:collapse; width:100%; font-size:13px; }} td, th {{ text-align:left; padding:4px 8px; border-bottom:1px solid var(--line); }}
th {{ color:var(--mute); font-weight:500; }} ul {{ margin:6px 0; padding-left:20px; }}
</style></head>
<body><main>
<h1>Real workflow trace through the network agent</h1>
<p class="sub">{subtitle} · run <code>{title}</code></p>
<p class="sites">{sites}</p>
<div class="cards">{cards}</div>

<h2>Timeline</h2>
<div class="panel">{gantt}
<div class="key">bar = reserved transfer running (solid: main path, faded: detour) · dashed = waiting for capacity ·
tick = deadline (red: missed) · grey = task stage</div></div>

<h2>Transit links</h2>
<div class="panel">{main}{detour}</div>

<h2>Network agent</h2>
<div class="panel">
<b>Graph B (periodic checks, no events injected)</b><ul>{findings}</ul>
<b>SciNet demand forecast</b> (part B: what the scheduling agent expects to request, from the workflow DAG)
<table><tr><th>workflow</th><th>transfer</th><th>first forecast</th><th>last forecast</th><th>requested</th></tr>{forecast_rows}</table>
</div>
</main></body></html>
"""
