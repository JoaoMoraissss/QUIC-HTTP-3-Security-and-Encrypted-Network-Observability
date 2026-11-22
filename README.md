# Network Security — Assignment #2 (TP1, group 10)

Topic 13, QUIC / HTTP/3, sub-topic (a): protocol behaviour, security and robustness of
implementations. This repository follows the roadmap in Section 9 of report 1 (milestones M1–M7).

## Lab

Three Docker containers on one machine, on two separate networks:

```
client 10.10.1.10  ──  10.10.1.254  router  10.10.2.254  ──  server 10.10.2.10
curl (H2/H3, qlog)      tc/netem, tcpdump, tshark            nginx 1.31.8 (H2 + H3)
aioquic                                                        same content, same cert
```

The client and the server only reach each other through the router, so delay/loss (netem) and
the passive capture (tcpdump) are applied at a single point. The client exports its TLS keys
(`SSLKEYLOGFILE`) and qlog (`QLOGDIR`), so each capture can be read both as an observer would
see it (encrypted) and decrypted.

Exact versions are in `code/versions.txt` (`code/scripts/versions.sh` regenerates it).

## Reproducing

Requirements: Linux, Docker with Compose, openssl. No root is needed beyond Docker access.
Every script is run from `code/`.

```sh
cd code
./scripts/setup.sh          # lab CA, server certificate, QUIC token key, test content

# main lab (10.10.x): M1 and M2
docker compose up -d --build
./scripts/m1-check.sh       # M1: same URL over HTTP/2 and HTTP/3, checked in the capture
./scripts/m2-all.sh         # M2: netem grid, 3 workloads (~4 h, resumable; log in results/m2)
docker compose down

# second lab copy (10.20.x) with the M4 nginx configuration (0-RTT, debug log)
export COMPOSE_FILE=docker-compose.m3.yml:docker-compose.m4.yml
docker compose up -d --build
./scripts/m3-capture.sh && ./scripts/m3-annotate.sh   # M3: annotated H2/H3 captures
./scripts/m4-rebind.sh      # M4: NAT rebinding, H3 and H2 (REPS=n, REBIND_AT=none for a baseline)
./scripts/m4-zerortt.sh     # M4: 0-RTT timings and replay (MODES="plain retry tooearly")
./scripts/m5-events.sh      # M5: observability events

# M6: three local aioquic servers (1.0.0, 1.2.0, 1.8.0), 1 GB memory each
export COMPOSE_FILE=docker-compose.m3.yml:docker-compose.m6.yml
docker compose up -d --build aq100 aq120 aq180
./scripts/m6-run.sh         # malformed frames + CRYPTO / PATH_CHALLENGE floods (SECS=60)
docker compose stop aq100 aq120 aq180
```

Figures: `.venv/bin/python code/scripts/report_figs.py results/m2 <dir>` (M2) and
`code/scripts/m6_plot.py results/m6 <dir>` (M6). The analysis of each milestone is in
`docs/` (`m3-wire-image.md`, `m4-migration.md`, `m5-observability.md`, `m6-robustness.md`).

Notes:

- Results (captures, TLS keys, qlog, server logs) go to `results/`. Files written by the
  containers belong to root; remove them through a container, e.g.
  `docker compose exec router rm -rf /results/m4/rebind-h3-4-1`.
- Do not use `nginx -s reload` between M4 runs: the old worker keeps part of the new QUIC
  connections (reuseport). The scripts recreate the server container instead.
- The client and the server share a PID namespace (the M2 runner reads the nginx worker CPU
  time), so recreating the server also needs the client: `docker compose up -d --force-recreate server client`.

## Submission (`TP1_group10.zip`)

Built by `code/scripts/package.sh`: this README, `code/`, `docs/`, the two report PDFs and a
selection of `results/` (M1–M3, M2 CSVs, M4 text files and 0-RTT captures, M5 without the two
10 MB downloads, M6 measurements). The full results (~800 MB, mostly M4 rebinding captures)
are not included; `results/SHA256SUMS` lists every file of the full set with its hash.

## Test content (`code/server/www/`, generated)

| Workload | Files |
|---|---|
| connection setup | `small.html` (≈1.4 kB) |
| throughput | `big.bin` (10 MiB) |
| multiplexing | `obj/1.txt` … `obj/50.txt` (≈2.8 kB each) |

## Status

| Milestone | State |
|---|---|
| M1 Lab setup | done 2026-11-11 — same URL over H2 and H3, confirmed in the capture and the server log |
| M2 Performance (netem, 3 workloads) | done 2026-11-11 — `code/scripts/m2-all.sh`, figures in report 2 |
| M3 Wire image (annotated captures) | done 2026-11-11 — `docs/m3-wire-image.md` |
| M4 Migration / NAT rebinding, 0-RTT | done 2026-11-22 — `docs/m4-migration.md` |
| M5 Observability | done 2026-11-22 — `docs/m5-observability.md` |
| M6 Robustness (aioquic) | done 2026-11-22 — `docs/m6-robustness.md` |
| M7 Report 2, packaging | done 2026-11-22 — report 2 and `code/scripts/package.sh` |
