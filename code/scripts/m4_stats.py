#!/usr/bin/env python3
"""Summary statistics for M4: NAT rebinding outcomes (with a 95% Wilson interval),
0-RTT timings (median and IQR) and replay outcomes per delay.

usage: m4_stats.py <results/m4> [tag]    e.g. m4_stats.py ../results/m4 -v2
"""
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def quartiles(xs):
    q = statistics.quantiles(xs, n=4, method="inclusive")
    return q[0], statistics.median(xs), q[2]


def rebinding(m4):
    runs = defaultdict(list)
    for line in (m4 / "curl-results.txt").read_text().splitlines():
        m = re.match(r"(h[23])-(4|base)-(\d+) result: .*bytes=(\d+) time=([\d.]+)s exit=(\d+)", line)
        if m:
            proto, at, rep, nbytes, t, ex = m.groups()
            runs[(proto, at)].append((int(rep), int(nbytes), float(t), int(ex)))
    print("NAT rebinding (10 MiB, 8 Mbit/s, RTT 50 ms)")
    for key in sorted(runs):
        rs = runs[key]
        ok = [r for r in rs if r[3] == 0 and r[1] == 10485760]
        lo, hi = wilson(len(ok), len(rs))
        line = f"  {key[0]} rebind={key[1]:4}: {len(ok)}/{len(rs)} completed ({100*len(ok)/len(rs):.0f}%, 95% CI {100*lo:.0f}-{100*hi:.0f}%)"
        if ok:
            ts = [r[2] for r in ok]
            line += f", time median {statistics.median(ts):.2f} s (min {min(ts):.2f}, max {max(ts):.2f})"
        fails = [r for r in rs if r not in ok]
        if fails:
            codes = defaultdict(int)
            for r in fails:
                codes[r[3]] += 1
            line += ", failures by curl exit: " + ", ".join(f"{c}x{n}" for c, n in sorted(codes.items()))
        print(line)
        if key == ("h3", "4"):
            fail = 1 - len(ok) / len(rs)
            lo, hi = wilson(len(rs) - len(ok), len(rs))
            print(f"    H3 failure rate {100*fail:.0f}% (95% CI {100*lo:.0f}-{100*hi:.0f}%)")


def zerortt(m4, tag):
    for mode in ("plain", "retry", "tooearly"):
        d = m4 / f"zerortt-{mode}{tag}"
        if not d.exists():
            continue
        print(f"\n0-RTT, server mode {mode} ({d.name})")
        t = defaultdict(list)
        for line in (d / "timings.txt").read_text().splitlines():
            m = re.match(r"(full|resumed|0rtt)\s.*status=(\d+).* t=([\d.]+)s", line)
            if m:
                t[m.group(1)].append((float(m.group(3)) * 1000, m.group(2)))
        for k in ("full", "resumed", "0rtt"):
            if t[k]:
                ms = [x[0] for x in t[k]]
                q1, med, q3 = quartiles(ms) if len(ms) >= 2 else (ms[0], ms[0], ms[0])
                st = sorted({x[1] for x in t[k]})
                print(f"  {k:8} n={len(ms):2}  median {med:5.0f} ms  IQR {q1:.0f}-{q3:.0f}  status {','.join(st)}")
        rep = defaultdict(list)
        for line in (d / "replays.txt").read_text().splitlines():
            m = re.match(r"replay d=([\d.]+) #(\d+) \+([\d.]+)s .*served \(200\) (\d+) time", line)
            if m:
                rep[float(m.group(1))].append((float(m.group(3)), int(m.group(4))))
            st = re.search(r"statuses ([\d,]+)", line)
        for delay in sorted(rep):
            rs = rep[delay]
            executed = sum(1 for r in rs if r[1] >= 2)
            actual = ", ".join(f"{r[0]:.1f}" for r in rs)
            print(f"  replay after {delay:4.1f} s: executed again in {executed}/{len(rs)} (actual delays {actual})")


if __name__ == "__main__":
    m4 = Path(sys.argv[1])
    tag = sys.argv[2] if len(sys.argv) > 2 else "-v2"
    rebinding(m4)
    zerortt(m4, tag)
