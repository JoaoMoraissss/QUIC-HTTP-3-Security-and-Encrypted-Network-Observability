# M6 — Robustness of aioquic (2026-11-22)

Local servers only. Scripts: `code/scripts/m6-run.sh` (campaign), `code/scripts/m6_attack.py`
(attacker and probe), `code/scripts/m6_plot.py` (figure `report_2/figs/fig_m6_memory.pdf`),
`code/scripts/m6_instrumented_server.py` (debugging aid used to explain one result).
Servers: `code/aioq/` (same minimal HTTP/3 server for every release), started with
`COMPOSE_FILE=docker-compose.m3.yml:docker-compose.m6.yml`, each capped at 1 GB of memory.
Raw data: `results/m6/` (`cases-*.txt`, `flood-<kind>-<srv>.{csv,log,probe.txt,server.log}`,
`summary.txt`).

## Releases under test

The lab had pinned aioquic 1.2.0, but the current release is **1.8.0**. Reading the source of
the wheels gave three releases with different defences:

| Release | Out-of-order CRYPTO limit | Queued PATH_CHALLENGEs |
|---|---|---|
| 1.0.0 | none | one slot (`remote_challenge`, each new one replaces the last) |
| 1.2.0 | 512 KB (`MAX_PENDING_CRYPTO`, added in 1.1.0) | unbounded deque — `MAX_REMOTE_CHALLENGES = 5` is defined but never used |
| 1.8.0 | 512 KB | at most 32 (`MAX_REMOTE_CHALLENGES` enforced) |

The 512 KB limit is the value MerCuriuzz proposed.

## Attacker

An ordinary client (aioquic 1.2.0 in the client container) completes a valid handshake and then
writes arbitrary frames into its 1-RTT packets, straight into aioquic's packet builder, with no
checks (hook on `_write_connection_limits`, called for every 1-RTT packet). For the
PATH_CHALLENGE flood it never sends ACKs (`_write_ack_frame` replaced) and ignores the server's
PATH_RESPONSEs, which its own aioquic would otherwise treat as unsolicited and close on. A
second client ("probe") makes a normal HTTP/3 GET every 5 s during each flood. Server memory
(RSS) and CPU are sampled every second from the host's `/proc`.

## Malformed and misplaced frames (12 cases, one connection each)

| Case | RFC 9000 expects | 1.0.0 | 1.2.0 | 1.8.0 |
|---|---|---|---|---|
| unknown frame type (0x40) | FRAME_ENCODING_ERROR | ✔ 0x7 | ✔ 0x7 | ✔ 0x7 |
| HANDSHAKE_DONE from client | PROTOCOL_VIOLATION | ✔ 0xa | ✔ 0xa | ✔ 0xa |
| NEW_TOKEN from client | PROTOCOL_VIOLATION | ✔ 0xa | ✔ 0xa | ✔ 0xa |
| STREAM on server's uni stream | STREAM_STATE_ERROR | ✔ 0x5 | ✔ 0x5 | ✔ 0x5 |
| STOP_SENDING on unopened server stream | STREAM_STATE_ERROR | ✔ 0x5 | ✔ 0x5 | ✔ 0x5 |
| ACK of a packet never sent | PROTOCOL_VIOLATION (SHOULD, §13.1) | ✘ ignored | ✘ ignored | ✘ ignored |
| truncated STREAM frame | FRAME_ENCODING_ERROR | ✔ 0x7 | ✔ 0x7 | ✔ 0x7 |
| STREAM offset + length > 2^62−1 | FRAME_ENCODING_ERROR | ✔ 0x7 | ✔ 0x7 | ✔ 0x7 |
| MAX_STREAMS > 2^60 | FRAME_ENCODING_ERROR | ✔ 0x7 | ✔ 0x7 | ✔ 0x7 |
| NEW_CONNECTION_ID, Retire Prior To > Sequence | FRAME_ENCODING_ERROR (MUST, §19.15) | ✘ 0xa | ✘ 0xa | ✘ 0xa |
| RETIRE_CONNECTION_ID never issued | PROTOCOL_VIOLATION | ✔ 0xa | ✔ 0xa | ✔ 0xa |
| PATH_RESPONSE answering nothing | MAY close (PROTOCOL_VIOLATION) | closes 0xa | closes 0xa | ignores |

No server crashed, every close carried a reason phrase, and a fresh client was served after
every series. Two deviations are the same in all three releases: an ACK for a packet number the
server never sent is silently accepted (the RFC says SHOULD close; accepting such ACKs is what
optimistic-ACK attacks rely on), and the wrong error code for Retire Prior To > Sequence Number
(PROTOCOL_VIOLATION instead of the required FRAME_ENCODING_ERROR). 1.8.0 changed its reaction to
an unsolicited PATH_RESPONSE from closing to ignoring; both are allowed.

## Floods (60 s each, server restarted before each)

| Flood | 1.0.0 | 1.2.0 | 1.8.0 |
|---|---|---|---|
| CRYPTO (out of order, never contiguous) | **+6.8 MB/s**, 454 MB after 60 s, CPU 100 % of a core, not freed while the connection lives | closed after 0.2 s / ~563 KB: `CRYPTO_BUFFER_EXCEEDED (0xd)`, "too much crypto buffering" | same as 1.2.0 |
| PATH_CHALLENGE, attacker never ACKs | +0.53 MB/s, CPU 72 % | **+1.78 MB/s**, 150 MB after 60 s, CPU 89 % | +0.53 MB/s, CPU 81 % |
| Probe GETs during the flood | 13/13 ok (20 → ~45 ms during the CRYPTO flood) | 13/13 ok | 13/13 ok |

Memory is released when the attacking connection ends (PATH_CHALLENGE curves drop at 60 s);
for the CRYPTO flood on 1.0.0 it stays until the idle timeout.

**CRYPTO flood.** Reproduced on 1.0.0: linear growth for as long as the attacker sends (about
400 MB/min at our sending rate of ~9.5 MB/s; MerCuriuzz reports ~1 GB/min with a faster
sender). With the 1 GB cap the container would be killed by the kernel after about 2.5 min.
Fixed in 1.2.0 and 1.8.0 by the 512 KB limit.

**PATH_CHALLENGE flood.** All three releases grow slowly (~0.5 MB/s), most probably from the
sent packets kept while waiting for ACKs that never come; 1.2.0 grows three times faster. With
the instrumented server (aioquic 1.2.0, 3 s flood) we saw why:

- the queue of challenges reached tens of thousands of entries (unbounded deque);
- bytes in flight reached **22 MB with a congestion window of 12.9 KB**. After the first PTO,
  aioquic allows one probe datagram (`_probe_pending`) and clears the flag only when the probe
  PING is written; the PATH_RESPONSEs are written earlier in the packet and fill it, so the PING
  is never written and the flag stays set. 99.9 % of the PATH_RESPONSE frames were written with
  a positive congestion budget for this reason. In effect congestion control is off for this
  connection: the server answers every challenge 1:1 and keeps every packet awaiting an ACK.

This is our reading of the code, backed by the instrumentation; we did not check it with the
aioquic developers. 1.8.0 bounds the queue (32) and grows like 1.0.0. The growth rates are far
below MerCuriuzz's +0.4 GB/min, since our Python attacker sends only ~4 MB/s of challenges.

## Against hypothesis H5

H5: a current aioquic should answer malformed or misplaced frames with CONNECTION_CLOSE and not
crash; if anything fails, it should be under the floods; an older release from before the fixes
should show memory growth, and if our script does not detect it, the problem is in our method.

- **Confirmed:** no crash in any case; 10 of 12 cases closed with the right code, in every
  release; failures appear only under the floods; 1.0.0 shows the CRYPTO memory growth, and
  1.2.0/1.8.0 close the connection with CRYPTO_BUFFER_EXCEEDED.
- **Refined:** two small, persistent deviations (unsent-packet ACK accepted, wrong error code
  for NEW_CONNECTION_ID); and the release we had pinned in the lab (1.2.0), which we would have
  called "current", still had an unbounded PATH_CHALLENGE queue, fixed only later.
- **Method notes:** the first measurement of the PATH_CHALLENGE flood read the memory after
  the flood, when the connection had already been freed, and saw nothing; the campaign samples
  during the attack. The first attacker also closed its own connection on the server's
  PATH_RESPONSEs. Neither server ever stopped serving the probe, so the "silent DoS" class
  (quiche hold-on) did not appear in aioquic.
