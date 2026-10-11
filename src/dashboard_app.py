"""Section 7: Raw and Aggregate dashboards (Dash), "GridPulse" theme.
  http://127.0.0.1:8050/raw        -> dashboard "Raw"       (reads energy_readings + meters)
  http://127.0.0.1:8050/aggregate  -> dashboard "Aggregate" (reads continuous aggregates + meters)
Five required panels; the KPI cards and the table are derived from the five panels'
own results (no extra queries). Panel SQL time is measured on the server with
time.perf_counter(); whole-dashboard time is measured in the browser with
performance.now() from the refresh request until all five figures are painted."""
import csv
import os
import socket
import time
from datetime import date, datetime

import plotly.graph_objects as go
from dash import Dash, Input, Output, State, clientside_callback, dcc, html, no_update

from dashboard_queries import PANELS, run_panels

TIMINGS_CSV = "results/dashboard_timings.csv"
TOTAL_RUNS = 11            # 1 warm-up + 10 measured
MACHINE = socket.gethostname()
FONT = "Segoe UI, Arial, sans-serif"
PALETTE = ["#2f7ff2", "#ff5a6e", "#7b61ff", "#22a04b", "#f28c1c",
           "#149b70", "#ff7a45", "#1b3fae", "#d4a000", "#8c5bd6"]
KPIS = [("total", "⚡", "Total Energy", "blue"),
        ("readings", "📶", "Readings Received", "red"),
        ("avgday", "📅", "Average Daily Energy", "purple"),
        ("peakday", "🏆", "Peak Day", "navy"),
        ("peakhour", "⏱", "Peak Network Hour", "green"),
        ("meter", "🏠", "Selected Meter Energy", "orange"),
        ("complete", "✅", "Network Completeness", "teal"),
        ("lowest", "⚠", "Lowest Region Completeness", "coral")]

app = Dash(__name__, title="GridPulse - Smart grid dashboards")


def kpi(key, icon, label, color):
    return html.Div(className=f"kpi kpi-{color}", children=[
        html.Div(icon, className="kpi-icon"),
        html.Div(className="kpi-text", children=[
            html.Div(label, className="kpi-label"),
            html.Div("-", id=f"kpi-{key}-value", className="kpi-value"),
            html.Div("", id=f"kpi-{key}-sub", className="kpi-sub")])])


def card(title, child, anchor=None):
    extra = {"id": anchor} if anchor else {}
    return html.Div(className="card",
                    children=[html.Div(title, className="card-title"), child], **extra)


def graph(key):
    return dcc.Graph(id=f"g-{key}", config={"displayModeBar": False}, style={"height": "340px"})


app.layout = html.Div(className="app", children=[
    dcc.Location(id="url"),
    html.Div(className="sidebar", children=[
        html.Div([html.Span("⚡", className="brand-icon"), html.Span("GridPulse")], className="brand"),
        html.Div("Smart meter analytics", className="brand-sub"),
        html.Div("Dashboards", className="nav-section"),
        html.A("📊  Raw", href="/raw", id="nav-raw", className="nav-link"),
        html.A("🗂  Aggregate", href="/aggregate", id="nav-agg", className="nav-link"),
        html.Div("Panels", className="nav-section"),
        html.A("Hourly regional energy", href="#p-hourly", className="nav-link small"),
        html.A("Daily network energy", href="#p-daily", className="nav-link small"),
        html.A("Seven-day periods", href="#p-weekly", className="nav-link small"),
        html.A("Selected meter", href="#p-meter", className="nav-link small"),
        html.A("Completeness", href="#p-complete", className="nav-link small"),
        html.Div("4,000 meters · 10 regions · CAT (UTC+02:00)", className="sidebar-foot"),
    ]),
    html.Div(className="main", children=[
        html.Div(className="topbar", children=[
            html.Div([html.Div("Smart Grid Energy Dashboard", className="eyebrow"),
                      html.H1(id="dash-title", className="dash-title"),
                      html.Div(id="source-text", className="source-text")]),
            html.Div(className="filters", children=[
                html.Div(className="filter", children=[
                    html.Label("CAT days (inclusive)"),
                    dcc.DatePickerRange(id="days", min_date_allowed=date(2026, 9, 1),
                                        max_date_allowed=date(2026, 9, 28),
                                        start_date=date(2026, 9, 22), end_date=date(2026, 9, 28),
                                        display_format="YYYY-MM-DD")]),
                html.Div(className="filter", children=[
                    html.Label("Meter"),
                    dcc.Input(id="meter", type="number", value=1000000000,
                              min=1000000000, max=1000003999, step=1)]),
                html.Button("⟳ Refresh", id="refresh-btn", n_clicks=0, className="btn"),
                html.Button("▶ Run benchmark (1 + 10)", id="bench-btn", n_clicks=0,
                            className="btn btn-outline"),
            ]),
        ]),
        html.Div(id="range-text", className="range-text"),
        html.Div(className="kpi-grid", children=[kpi(*k) for k in KPIS]),
        card("Hourly regional energy (kWh)", graph("hourly_region"), "p-hourly"),
        html.Div(className="grid-2", children=[
            card("Daily network energy (kWh)", graph("daily_network"), "p-daily"),
            card("Network energy per seven-day period (kWh)", graph("weekly_network"), "p-weekly")]),
        html.Div(className="grid-2", children=[
            card("Daily energy for selected meter (kWh)", graph("meter_daily"), "p-meter"),
            card("Completeness by region (%)", graph("completeness"), "p-complete")]),
        card("Regional completeness table (from the completeness panel)",
             html.Div(id="complete-table"), "p-table"),
        card("Refresh timing (logged for Section 7.4)",
             html.Pre(id="status", className="status"), "p-status"),
        dcc.Store(id="refresh-token"), dcc.Store(id="server-timings"),
        dcc.Store(id="client-timing"), dcc.Store(id="render-dummy"),
        dcc.Store(id="auto-next"), dcc.Store(id="bench-state", data={"active": False}),
    ]),
])


def mode_from(path):
    return "aggregate" if path and path.startswith("/aggregate") else "raw"


@app.callback(Output("dash-title", "children"), Output("source-text", "children"),
              Output("nav-raw", "className"), Output("nav-agg", "className"),
              Input("url", "pathname"))
def set_title(path):
    if mode_from(path) == "aggregate":
        return ("Aggregate", "Source: continuous aggregates cagg_hour_region, cagg_15min_region, "
                "cagg_day_meter (+ meters for labels and registered counts)",
                "nav-link", "nav-link active")
    return ("Raw", "Source: energy_readings joined to meters",
            "nav-link active", "nav-link")


# 1) Browser records the refresh request time, then asks the server for data
clientside_callback(
    """
    function(nClicks, autoNext) {
        window.__refreshStart = performance.now();
        window.__refreshStartIso = new Date().toISOString();
        return {token: Date.now(), start_iso: window.__refreshStartIso};
    }
    """,
    Output("refresh-token", "data"),
    Input("refresh-btn", "n_clicks"), Input("auto-next", "data"),
)


def style(fig, ytitle, xtitle=None, legend=False):
    fig.update_layout(template="plotly_white", font=dict(family=FONT, size=12, color="#3a4466"),
                      margin=dict(l=60, r=15, t=10, b=50), paper_bgcolor="white",
                      plot_bgcolor="white", yaxis_title=ytitle, xaxis_title=xtitle,
                      showlegend=legend, legend=dict(orientation="h", y=-0.22, x=0))
    fig.update_yaxes(gridcolor="#eef1f7", zeroline=False)
    fig.update_xaxes(showgrid=False)
    return fig


def bar(x, y, color, ytitle, xtitle, text=None):
    fig = go.Figure(go.Bar(x=x, y=y, marker_color=color, text=text, textposition="outside",
                           cliponaxis=False))
    try:
        fig.update_traces(marker_cornerradius=6)
    except ValueError:
        pass
    return style(fig, ytitle, xtitle)


def completeness_table(df):
    header = html.Thead(html.Tr([html.Th(h) for h in
                                 ["Region", "Registered meters", "Observed readings",
                                  "Planned readings", "Completeness"]]))
    rows = []
    for _, r in df.iterrows():
        pct = float(r["completeness_pct"])
        rows.append(html.Tr([
            html.Td(r["region"]), html.Td(f"{int(r['registered_meters']):,}"),
            html.Td(f"{int(r['readings']):,}"), html.Td(f"{int(r['planned']):,}"),
            html.Td([html.Span(className="bar-bg",
                               children=html.Div(className="bar-fg", style={"width": f"{pct:.2f}%"})),
                     f"{pct:.4f} %"])]))
    return html.Table(className="data-table", children=[header, html.Tbody(rows)])


KPI_OUTPUTS = []
for k, *_ in KPIS:
    KPI_OUTPUTS += [Output(f"kpi-{k}-value", "children"), Output(f"kpi-{k}-sub", "children")]


# 2) Server runs the five panel queries (timed) and builds figures, KPIs and table
@app.callback(
    [Output(f"g-{key}", "figure") for key, _ in PANELS]
    + [Output("server-timings", "data"), Output("range-text", "children")]
    + KPI_OUTPUTS + [Output("complete-table", "children")],
    Input("refresh-token", "data"),
    State("url", "pathname"), State("days", "start_date"), State("days", "end_date"),
    State("meter", "value"),
)
def refresh(token, path, start_date, end_date, meter):
    mode = mode_from(path)
    s = date.fromisoformat(start_date[:10])
    e = date.fromisoformat(end_date[:10])
    meter = int(meter or 1000000000)
    t0 = time.perf_counter()
    res, params = run_panels(mode, s, e, meter)
    server_ms = (time.perf_counter() - t0) * 1000.0

    hourly, _ = res["hourly_region"]
    f1 = go.Figure()
    for i, region in enumerate(hourly["region"].unique()):
        part = hourly[hourly["region"] == region]
        f1.add_trace(go.Scatter(x=part["bucket"], y=part["energy_kwh"], mode="lines", name=region,
                                line=dict(width=1.6, color=PALETTE[i % len(PALETTE)])))
    style(f1, "Energy (kWh)", "CAT hour", legend=True)

    daily, _ = res["daily_network"]
    f2 = bar([b.strftime("%a %d %b") for b in daily["bucket"]], daily["energy_kwh"],
             "#2f7ff2", "Energy (kWh)", "CAT day")

    weekly, _ = res["weekly_network"]
    f3 = bar([f"Period from {b:%d %b}" for b in weekly["bucket"]], weekly["energy_kwh"],
             "#7b61ff", "Energy (kWh)", "Seven-day period (1, 8, 15, 22 Sep)",
             text=[f"{v:,.0f} kWh" for v in weekly["energy_kwh"]])

    mdf, _ = res["meter_daily"]
    f4 = bar([b.strftime("%a %d %b") for b in mdf["bucket"]], mdf["energy_kwh"],
             "#f28c1c", "Energy (kWh)", f"CAT day (meter {meter})",
             text=[f"{v:.2f}" for v in mdf["energy_kwh"]])

    comp, _ = res["completeness"]
    f5 = bar(comp["region"], comp["completeness_pct"], "#149b70", "Completeness (%)", "Region",
             text=[f"{v:.3f}%" for v in comp["completeness_pct"]])
    if len(comp):
        f5.update_yaxes(range=[max(0, comp["completeness_pct"].min() - 0.5), 100])

    # KPI values derived from the five panel results (no extra queries)
    total = daily["energy_kwh"].sum() if len(daily) else 0.0
    readings = int(daily["readings"].sum()) if len(daily) else 0
    ndays = max(len(daily), 1)
    k = {}
    k["total"] = (f"{total:,.0f} kWh", f"{params['days']} CAT day(s), all regions")
    k["readings"] = (f"{readings:,}", "observed meter readings")
    k["avgday"] = (f"{total / ndays:,.0f} kWh", "per CAT day")
    if len(daily):
        pd_row = daily.loc[daily["energy_kwh"].idxmax()]
        k["peakday"] = (f"{pd_row['bucket']:%a %d %b}", f"{pd_row['energy_kwh']:,.0f} kWh")
    else:
        k["peakday"] = ("-", "")
    if len(hourly):
        net = hourly.groupby("bucket")["energy_kwh"].sum()
        k["peakhour"] = (f"{net.idxmax():%d %b %H:%M}", f"{net.max():,.1f} kWh in one hour")
    else:
        k["peakhour"] = ("-", "")
    k["meter"] = (f"{mdf['energy_kwh'].sum():,.2f} kWh", f"meter {meter}")
    if len(comp):
        net_pct = 100.0 * comp["readings"].sum() / comp["planned"].sum()
        low = comp.loc[comp["completeness_pct"].idxmin()]
        k["complete"] = (f"{net_pct:.4f} %",
                         f"{int(comp['readings'].sum()):,} of {int(comp['planned'].sum()):,}")
        k["lowest"] = (f"{low['completeness_pct']:.4f} %", low["region"])
    else:
        k["complete"] = k["lowest"] = ("-", "")
    kpi_values = []
    for key, *_ in KPIS:
        kpi_values += list(k[key])

    timings = {"token": (token or {}).get("token"), "mode": mode,
               "start": params["start"], "end": params["end"], "meter": meter,
               "panel_ms": {key: round(res[key][1], 3) for key, _ in PANELS},
               "server_total_ms": round(server_ms, 3)}
    text = (f"Mode: {mode}  ·  Range: {params['start']} to {params['end']} (exclusive)  ·  "
            f"Meter: {meter}  ·  All regions")
    return [f1, f2, f3, f4, f5, timings, text] + kpi_values + [completeness_table(comp)]


# 3) Browser: after all five figures are updated and painted, record elapsed time
clientside_callback(
    """
    function(f1, f2, f3, f4, f5, server) {
        if (!server || window.__refreshStart === undefined) {
            return window.dash_clientside.no_update;
        }
        const start = window.__refreshStart;
        const startIso = window.__refreshStartIso;
        requestAnimationFrame(function() { requestAnimationFrame(function() {
            window.dash_clientside.set_props("client-timing", {data: {
                token: server.token, elapsed_ms: performance.now() - start,
                start_iso: startIso, end_iso: new Date().toISOString()}});
        }); });
        return window.dash_clientside.no_update;
    }
    """,
    Output("render-dummy", "data"),
    [Input(f"g-{key}", "figure") for key, _ in PANELS] + [Input("server-timings", "data")],
)


@app.callback(
    Output("bench-state", "data", allow_duplicate=True),
    Output("auto-next", "data", allow_duplicate=True),
    Input("bench-btn", "n_clicks"),
    prevent_initial_call=True,
)
def start_benchmark(n):
    bench_id = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return {"active": True, "done": 0, "bench_id": bench_id}, time.time()


def to_cat(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().isoformat(timespec="milliseconds")


# 4) Server logs every refresh; drives the 1 + 10 benchmark sequence
@app.callback(
    Output("bench-state", "data", allow_duplicate=True),
    Output("auto-next", "data", allow_duplicate=True),
    Output("status", "children"),
    Input("client-timing", "data"),
    State("server-timings", "data"), State("bench-state", "data"),
    prevent_initial_call=True,
)
def log_refresh(client, server, bench):
    if not client or not server or client.get("token") != server.get("token"):
        return no_update, no_update, no_update
    bench = bench or {"active": False}
    if bench.get("active"):
        run_no = bench["done"]
        run_type = "warm-up" if run_no == 0 else "measured"
        bench_id = bench["bench_id"]
    else:
        run_no, run_type, bench_id = "", "manual", ""

    row = {"bench_id": bench_id, "mode": server["mode"], "run_type": run_type, "run_no": run_no,
           "start_cat": to_cat(client["start_iso"]), "end_cat": to_cat(client["end_iso"]),
           **{f"{k}_ms": server["panel_ms"][k] for k, _ in PANELS},
           "server_total_ms": server["server_total_ms"],
           "dashboard_ms": round(client["elapsed_ms"], 3),
           "range_start": server["start"], "range_end": server["end"],
           "meter": server["meter"], "machine": MACHINE}
    new_file = not os.path.exists(TIMINGS_CSV)
    with open(TIMINGS_CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if new_file:
            w.writeheader()
        w.writerow(row)

    panels = "\n".join(f"  {k:<15} {server['panel_ms'][k]:9.1f} ms" for k, _ in PANELS)
    status = (f"Last refresh: mode={server['mode']}  type={run_type} {run_no}\n"
              f"  whole dashboard {client['elapsed_ms']:9.1f} ms (browser, until all 5 panels painted)\n"
              f"  server queries  {server['server_total_ms']:9.1f} ms\n{panels}\n"
              f"Logged to {TIMINGS_CSV} on {MACHINE}")

    if bench.get("active"):
        bench = dict(bench, done=bench["done"] + 1)
        if bench["done"] < TOTAL_RUNS:
            return bench, time.time(), status + f"\nBenchmark {bench_id}: {bench['done']}/{TOTAL_RUNS} done..."
        bench["active"] = False
        return bench, no_update, status + f"\nBenchmark {bench_id} COMPLETE: 1 warm-up + 10 measured."
    return no_update, no_update, status


if __name__ == "__main__":
    print("Raw dashboard:       http://127.0.0.1:8050/raw")
    print("Aggregate dashboard: http://127.0.0.1:8050/aggregate")
    app.run(host="127.0.0.1", port=8050, debug=False)