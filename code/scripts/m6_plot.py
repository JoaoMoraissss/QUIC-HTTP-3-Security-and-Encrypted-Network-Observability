#!/usr/bin/env python3
"""Figure for report 2 from the M6 floods: server memory (RSS) over time, one line per
aioquic release, one panel per flood. Same style as report_figs.py.

Usage: m6_plot.py <results/m6> <output dir>
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
SRV = [("aq100", "aioquic 1.0.0", "#c53030", "-"), ("aq120", "aioquic 1.2.0", "#d69e2e", "-"),
       ("aq180", "aioquic 1.8.0", "#2b6cb0", "--")]
FLOODS = [("crypto", "CRYPTO flood"), ("pathchallenge", "PATH_CHALLENGE flood, no ACKs")]

fig, axes = plt.subplots(1, 2, figsize=(7, 2.2), sharey=True)
for ax, (kind, title) in zip(axes, FLOODS):
    for srv, label, colour, style in SRV:
        f = src / f"flood-{kind}-{srv}.csv"
        if not f.exists():
            continue
        d = pd.read_csv(f)
        ax.plot(d.t, d.rss_mb, color=colour, ls=style, lw=1.4, label=label)
    ax.set_title(title)
    if kind == "crypto":
        ax.annotate("1.2.0 and 1.8.0 close the connection\nafter 0.2 s (CRYPTO_BUFFER_EXCEEDED)",
                    xy=(3, 45), xytext=(22, 90), fontsize=7,
                    arrowprops=dict(arrowstyle="->", lw=0.7, color="#555"))
    ax.set_xlabel("time since start of flood (s)")
    ax.grid(alpha=.3)
axes[0].set_ylabel("server RSS (MB)")
axes[1].legend(loc="upper left")
fig.tight_layout()
fig.savefig(out / "fig_m6_memory.pdf")
print("wrote", out / "fig_m6_memory.pdf")
