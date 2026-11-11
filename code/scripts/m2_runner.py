#!/usr/bin/env python3
"""M2 runner, executed inside the client container for one network condition.

For every repetition it runs each workload once over HTTP/2 and once over HTTP/3,
in random order, each time with a new curl process (so a new connection and no
session resumption). It appends one CSV row per transfer set to --out.

Measured per run: handshake, TTFB, total time and throughput (from curl), wall
time, CPU time of curl (client) and CPU time of the nginx worker (server).
"""
import argparse, csv, json, os, random, resource, subprocess, time

BASE = "https://server.lab"
WORKLOADS = {
    "small": [f"{BASE}/small.html"],
    "big":   [f"{BASE}/big.bin"],
    "multi": [f"{BASE}/obj/{i}.txt" for i in range(1, 51)],
}
PROTO_FLAG = {"h2": "--http2", "h3": "--http3-only"}
TICK = os.sysconf("SC_CLK_TCK")
FIELDS = ["rtt_ms", "loss_pct", "workload", "proto", "run", "ok", "exit", "http_version",
          "connects", "bytes", "t_connect", "t_handshake", "t_ttfb", "t_total", "wall",
          "throughput_mbps", "cpu_client", "cpu_server"]


def nginx_worker_pid():
    # after "nginx -s reload" the old worker lingers as "worker process is shutting down",
    # so take the newest worker that is not shutting down
    found = []
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    cmd = f.read()
                if cmd.startswith(b"nginx: worker") and b"shutting down" not in cmd:
                    found.append(int(pid))
            except OSError:
                pass
    if not found:
        raise SystemExit("nginx worker not found (is the client sharing the server PID namespace?)")
    return max(found)


def cpu_seconds(pid):
    with open(f"/proc/{pid}/stat") as f:
        parts = f.read().rsplit(")", 1)[1].split()
    return (int(parts[11]) + int(parts[12])) / TICK  # utime + stime


def run_once(workload, proto, max_time, worker):
    urls = WORKLOADS[workload]
    cmd = ["curl", "-s", "--cacert", "/certs/ca.crt", PROTO_FLAG[proto],
           "--max-time", str(max_time), "-w", "%{json}\n"]
    if len(urls) > 1:
        cmd += ["--parallel", "--parallel-max", "50"]  # one connection, streams multiplexed
    for u in urls:
        cmd += ["-o", "/dev/null", u]

    before_children = resource.getrusage(resource.RUSAGE_CHILDREN)
    srv0 = cpu_seconds(worker)
    t0 = time.perf_counter()
    p = subprocess.run(cmd, capture_output=True, text=True)
    wall = time.perf_counter() - t0
    srv1 = cpu_seconds(worker)
    after_children = resource.getrusage(resource.RUSAGE_CHILDREN)

    rows = [json.loads(l) for l in p.stdout.splitlines() if l.startswith("{")]
    ok = (p.returncode == 0 and len(rows) == len(urls)
          and all(r.get("response_code") == 200 for r in rows))
    nbytes = sum(r.get("size_download", 0) for r in rows)
    first = rows[0] if rows else {}
    t_total = max((r.get("time_total", 0) for r in rows), default=0)
    return {
        "ok": int(ok), "exit": p.returncode,
        "http_version": ",".join(sorted({str(r.get("http_version")) for r in rows})),
        "connects": sum(r.get("num_connects", 0) for r in rows),
        "bytes": nbytes,
        "t_connect": first.get("time_connect", ""),
        "t_handshake": first.get("time_appconnect", ""),
        "t_ttfb": first.get("time_starttransfer", ""),
        "t_total": t_total,
        "wall": round(wall, 6),
        "throughput_mbps": round(nbytes * 8 / t_total / 1e6, 3) if ok and t_total else "",
        "cpu_client": round((after_children.ru_utime + after_children.ru_stime)
                            - (before_children.ru_utime + before_children.ru_stime), 4),
        "cpu_server": round(srv1 - srv0, 4),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rtt", type=float, required=True)
    ap.add_argument("--loss", type=float, required=True)
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--workloads", default="small,big,multi")
    ap.add_argument("--max-time", type=int, default=180)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    worker = nginx_worker_pid()
    new = not os.path.exists(a.out)
    with open(a.out, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for run in range(1, a.runs + 1):
            for wl in a.workloads.split(","):
                protos = ["h2", "h3"]
                random.shuffle(protos)  # avoid always measuring one protocol first
                for proto in protos:
                    r = run_once(wl, proto, a.max_time, worker)
                    w.writerow({"rtt_ms": a.rtt, "loss_pct": a.loss, "workload": wl,
                                "proto": proto, "run": run, **r})
                    f.flush()
                    time.sleep(0.2)


if __name__ == "__main__":
    main()
