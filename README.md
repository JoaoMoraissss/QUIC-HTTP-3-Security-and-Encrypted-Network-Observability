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

```sh
cd code
./scripts/setup.sh          # lab CA, server certificate, test content
docker compose up -d --build
./scripts/m1-check.sh       # M1: same URL over HTTP/2 and HTTP/3, checked in the capture
docker compose down         # stop the lab
```

Results (captures, TLS keys, qlog, server logs) go to `results/`, which is not versioned.

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
| M7 Report 2, packaging | to do |
