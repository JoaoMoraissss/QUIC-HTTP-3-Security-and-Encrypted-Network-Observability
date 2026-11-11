#!/usr/bin/env python3
"""Figures and LaTeX tables for report 2 from the M2 CSV files.

Usage: report_figs.py <results/m2> <output dir>
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

src, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({"font.size": 8, "axes.titlesize": 8, "legend.fontsize": 7,
                     "figure.dpi": 150, "savefig.bbox": "tight"})
C = {"h2": "#2b6cb0", "h3": "#dd6b20", "h3_64k": "#9c4221"}
LBL = {"h2": "HTTP/2", "h3": "HTTP/3"}


def load(name):
    d = pd.read_csv(src / name)
    return d


def med_iqr(d, keys, col):
    g = d.groupby(keys)[col]
    return pd.DataFrame({"med": g.median(), "q1": g.quantile(.25), "q3": g.quantile(.75)}).reset_index()


def grid_plot(d, workloads, col, ylabel, fname, scale=1.0):
    rtts = sorted(d.rtt_ms.unique())
    fig, axes = plt.subplots(len(workloads), len(rtts), figsize=(7, 1.9 * len(workloads)), squeeze=False)
    for r, wl in enumerate(workloads):
        s = med_iqr(d[(d.workload == wl) & (d.ok == 1)], ["rtt_ms", "loss_pct", "proto"], col)
        for c, rtt in enumerate(rtts):
            ax = axes[r][c]
            for p in ["h2", "h3"]:
                x = s[(s.rtt_ms == rtt) & (s.proto == p)].sort_values("loss_pct")
                ax.errorbar(x.loss_pct, x.med * scale, yerr=[(x.med - x.q1) * scale, (x.q3 - x.med) * scale],
                            marker="o", ms=3, lw=1, capsize=2, color=C[p], label=LBL[p])
            ax.grid(alpha=.3)
            if r == 0:
                ax.set_title(f"RTT {rtt:g} ms")
            if r == len(workloads) - 1:
                ax.set_xlabel("loss per direction (%)")
            if c == 0:
                ax.set_ylabel(f"{wl}: {ylabel}")
    axes[0][0].legend()
    fig.tight_layout()
    fig.savefig(out / fname)
    plt.close(fig)


# 1. small + multi, total time in ms
sm = load("raw-small-multi.csv")
grid_plot(sm, ["small", "multi"], "t_total", "time (ms)", "fig_small_multi.pdf", scale=1000)

# 2. big object, throughput
big_path = src / "raw-big.csv"
if big_path.exists():
    big = load("raw-big.csv")
    grid_plot(big, ["big"], "throughput_mbps", "Mbit/s", "fig_big.pdf")

# 3. buffer experiment: throughput vs RTT, with the 64 KB/RTT bound
b64, b4m = load("buffer-64k.csv"), load("buffer-4m.csv")
fig, ax = plt.subplots(figsize=(3.4, 2.3))
for d, p, key, lab in [(b4m, "h2", "h2", "HTTP/2"), (b4m, "h3", "h3", "HTTP/3, buffer 4m"),
                       (b64, "h3", "h3_64k", "HTTP/3, buffer 64k (default)")]:
    s = med_iqr(d[(d.ok == 1) & (d.proto == p)], ["rtt_ms"], "throughput_mbps")
    ax.plot(s.rtt_ms, s.med, marker="o", ms=3, lw=1, color=C[key], label=lab)
rtt = pd.Series([10, 25, 50, 100, 200])
ax.plot(rtt, 65536 * 8 / (rtt / 1000) / 1e6, ls="--", lw=.8, color="grey", label="64 KB / RTT")
ax.set_xlabel("RTT (ms)"); ax.set_ylabel("throughput (Mbit/s)")
ax.set_ylim(0, 52); ax.grid(alpha=.3); ax.legend()
fig.savefig(out / "fig_buffer.pdf")
plt.close(fig)

# 4. tables (LaTeX rows) for the text
with open(out / "tables.tex", "w") as f:
    s = sm[sm.ok == 1].groupby(["workload", "rtt_ms", "loss_pct", "proto"]).t_total.median().unstack()
    f.write("% small object: median total time (ms) h2, h3, ratio; loss 0 and 5%\n")
    for (wl, rtt, loss), row in s.iterrows():
        if wl == "small" and loss in (0, 5):
            f.write(f"{rtt:g} & {loss:g} & {row.h2*1000:.0f} & {row.h3*1000:.0f} & {row.h3/row.h2:.2f} \\\\\n")
    cpu = pd.concat([b4m.assign(b="4m"), b64.assign(b="64k")])
    cpu = cpu[cpu.ok == 1].groupby(["b", "proto"])[["cpu_client", "cpu_server"]].median()
    f.write("% 10 MB object without loss, median CPU seconds (client, server)\n")
    for (b, p), row in cpu.iterrows():
        f.write(f"% {b} {p}: client {row.cpu_client:.3f} s, server {row.cpu_server:.3f} s\n")
    if big_path.exists():
        g = big[big.ok == 1].groupby(["rtt_ms", "loss_pct", "proto"]).throughput_mbps.median().unstack()
        f.write("% big object: median throughput (Mbit/s) h2, h3\n")
        for (rtt, loss), row in g.iterrows():
            f.write(f"{rtt:g} & {loss:g} & {row.h2:.1f} & {row.h3:.1f} \\\\\n")
print("figures in", out)
