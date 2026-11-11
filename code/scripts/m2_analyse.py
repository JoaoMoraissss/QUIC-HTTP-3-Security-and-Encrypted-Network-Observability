#!/usr/bin/env python3
"""M2 analysis: medians and IQR per condition, HTTP/3 vs HTTP/2 comparison, plots.

Usage: m2_analyse.py results/m2/raw.csv results/m2/
Writes summary.csv, compare.md and one PNG per workload into the output folder.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

raw, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
df = pd.read_csv(raw)
KEYS = ["workload", "rtt_ms", "loss_pct", "proto"]
METRICS = ["t_handshake", "t_ttfb", "t_total", "throughput_mbps", "cpu_client", "cpu_server"]


def q1(s): return s.quantile(0.25)
def q3(s): return s.quantile(0.75)


# failures (timeouts, errors) are counted, not averaged in
fails = df.groupby(KEYS)["ok"].apply(lambda s: int((s == 0).sum())).rename("failed")
ok = df[df.ok == 1]
summary = ok.groupby(KEYS)[METRICS].agg(["median", q1, q3, "count"])
summary.columns = ["_".join(c) for c in summary.columns]
summary = summary.join(fails, how="outer").reset_index()
summary.to_csv(out / "summary.csv", index=False)

# comparison table: median total time, ratio h3/h2, and whether the IQRs overlap
rows = []
for (wl, rtt, loss), g in summary.groupby(["workload", "rtt_ms", "loss_pct"]):
    g = g.set_index("proto")
    if not {"h2", "h3"} <= set(g.index):
        continue
    h2, h3 = g.loc["h2"], g.loc["h3"]
    if pd.isna(h2.t_total_median) or pd.isna(h3.t_total_median):
        verdict, ratio = "timeout", float("nan")
    else:
        ratio = h3.t_total_median / h2.t_total_median
        if h3.t_total_q3 < h2.t_total_q1:
            verdict = "H3 faster"
        elif h2.t_total_q3 < h3.t_total_q1:
            verdict = "H2 faster"
        else:
            verdict = "overlap"
    rows.append({"workload": wl, "rtt_ms": rtt, "loss_pct": loss,
                 "h2_total_s": h2.t_total_median, "h3_total_s": h3.t_total_median,
                 "h3/h2": ratio, "verdict": verdict,
                 "failed h2/h3": f"{int(h2.failed)}/{int(h3.failed)}"})
cmp = pd.DataFrame(rows)
with open(out / "compare.md", "w") as f:
    f.write("Median total time; verdict only when the interquartile ranges do not overlap.\n\n")
    f.write(cmp.to_markdown(index=False, floatfmt=".3f") if hasattr(cmp, "to_markdown")
            else cmp.to_string(index=False))
    f.write("\n")

# plots: total time vs loss, one panel per RTT, median with IQR bars
COLORS = {"h2": "#2b6cb0", "h3": "#dd6b20"}
LABEL = {"h2": "HTTP/2 (TCP+TLS)", "h3": "HTTP/3 (QUIC)"}
for wl, g in summary.groupby("workload"):
    rtts = sorted(g.rtt_ms.unique())
    fig, axes = plt.subplots(1, len(rtts), figsize=(3.2 * len(rtts), 3), sharey=False)
    axes = axes if len(rtts) > 1 else [axes]
    for ax, rtt in zip(axes, rtts):
        for p in ["h2", "h3"]:
            s = g[(g.rtt_ms == rtt) & (g.proto == p)].sort_values("loss_pct")
            if s.empty:
                continue
            err = [s.t_total_median - s.t_total_q1, s.t_total_q3 - s.t_total_median]
            ax.errorbar(s.loss_pct, s.t_total_median, yerr=err, marker="o", ms=4,
                        capsize=3, color=COLORS[p], label=LABEL[p])
        ax.set_title(f"RTT {rtt:g} ms", fontsize=10)
        ax.set_xlabel("loss per direction (%)")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("total time (s)")
    axes[0].legend(fontsize=8)
    fig.suptitle(f"Workload: {wl}", fontsize=11)
    fig.tight_layout()
    fig.savefig(out / f"m2_{wl}.png", dpi=150)
    plt.close(fig)

print(cmp.to_string(index=False))
