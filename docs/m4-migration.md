# M4a — NAT rebinding (2026-11-22)

Script: `code/scripts/m4-rebind.sh` (lab copy m3 + override `docker-compose.m4.yml`).
Raw data: `results/m4/rebind-<proto>-<4|base>-<rep>/` (pcap on both router sides, client
TLS keys, qlog), `results/m4/curl-results.txt`, `results/m3/server-logs/{error,debug}.log`.

## Setup

- The router source-NATs the client (10.20.1.10) to 10.20.2.254:40001 on the server side
  (nftables table `lab`, TCP and UDP to port 443).
- Download of `big.bin` (10 MiB), RTT 50 ms, no loss, 8 Mbit/s bottleneck, netem queue of
  100 packets (~150 ms). Without rate limiting the transfer is too short; with
  `curl --limit-rate` the sending is bursty and the rebinding lands in an idle gap; with the
  default queue of 2000 packets the queue holds ~3 s of data and the server's PATH_CHALLENGE
  waits behind it (measured: 2.9 s until PATH_RESPONSE), which measures the lab buffer, not QUIC.
- At t = 4 s the mapping is changed to port 40002 and the conntrack entry is deleted, as a home
  NAT does when a mapping times out. The client does not know it moved.

## Results

| Case | Runs | Completed | Time when completed |
|---|---|---|---|
| HTTP/3, no rebinding | 3 | 3 | 11.36 s |
| HTTP/3, rebinding | 23 | 17 | 11.39–11.47 s (mean 11.42 s, +0.06 s) |
| HTTP/2, no rebinding | 3 | 3 | 11.22 s |
| HTTP/2, rebinding | 3 | 0 | reset at ~4.3 s ("Connection reset by peer") |

**HTTP/2.** The server receives segments from an unknown 4-tuple (port 40002) and answers with
RST; the router, which no longer has the old mapping, also answers the server's segments to
40001 with RST. The TCP connection is lost in every run. (In one earlier run with the large
queue the client kept rejecting the RSTs and the transfer hung until curl's 40 s timeout,
probably because the RST sequence numbers lagged behind the data still queued — RFC 5961
checks. Not repeated with the final settings.)

**HTTP/3, successful runs** (e.g. first exploratory run, error.log:
`quic migrated to path seq:1 addr:10.20.2.254:40002` → `successfully validated`):

1. The first client packet from the new port (an ACK) is enough for nginx to switch paths.
2. nginx sends 2 PATH_CHALLENGE on the new path (55-byte datagrams, not padded to 1200
   because of the anti-amplification limit) and 2 on the old path (padded to 1208 bytes).
3. Before validation nginx sent 174 bytes to the new path after receiving 59 (≈2.95×, inside
   the 3× limit of RFC 9000 §8/§9.3).
4. The client's PATH_RESPONSEs arrive one RTT later (51 ms); the old path's challenges are
   never answered and nginx gives up on it after three tries.
5. Congestion control restarts on the new path (slow start, ~0.8 s to recover the rate).
6. Linkability: the server switches to a new connection ID (issued earlier by the client in
   NEW_CONNECTION_ID) on the new path, but the client keeps the same DCID in both directions of
   the rebinding, because it does not know the address changed. An observer that sees both
   paths links them through the client's DCID. RFC 9000 §9.5 only requires a fresh CID when the
   endpoint itself initiates the migration, so this is expected, but it means NAT rebinding
   offers no unlinkability.

**HTTP/3, failed runs (6/23, ~26%).** The client sees `ERR_DRAINING` ~7 s after the
rebinding; nginx closes with error 0x10 `NO_VIABLE_PATH`. In the debug log of a failed
connection the PATH_CHALLENGE frames for the new path are never built (`tx:0` on the new path
when it becomes active), while those for the old path are sent:

```
quic path seq:0 is now backup ...
quic initiated validation of path seq:1
quic path seq:1 send path_challenge tries:0
quic sendto app packet max:336 min:0        <- no frame, no packet
quic sendto app packet max:336 min:0
quic migrated to path seq:1 addr:10.20.2.254:40002
quic path seq:1 is now active tx:0 rx:112 valid:0
...  (tries:1 at +1 s and tries:2 at +3 s, same)
quic path seq:0 validation failed
quic path seq:1 validation failed
quic close immediate term:1 drain:0 error:16 "no viable path"
```

Cause, from the nginx source (`src/event/quic/ngx_event_quic_output.c`,
`ngx_quic_frame_sendto`, GitHub master):

```c
if (cg->in_flight >= cg->window && !frame->ignore_congestion) {
    ngx_quic_free_frame(c, frame);
    return NGX_AGAIN;
}
```

`ngx_quic_send_path_challenge` only checks for `NGX_ERROR`, so when the congestion window is
full the challenge is dropped silently and is not queued for later. The two padded challenges
for the old path (2 × 1200 bytes) are sent first and use up what is left of the window, so the
new path's challenges are the ones dropped. The same happens on every retry. Until the new
path is validated the server is held at 3× the bytes it receives (≈340 bytes of data per
112-byte ACK), and after three attempts both paths fail validation and the connection is
closed. Whether a run fails depends on how full the window is at the instant of the
rebinding, which explains why it happens in about a quarter of the runs during a bulk
transfer. The nginx master source was read on 2026-11-22; the lab runs nginx 1.31.8.

Security reading: a NAT rebinding during a download is a normal event (mapping timeout,
mobile network), so this is a robustness problem rather than an attack; but anyone who can
force a rebinding (e.g. a middlebox flushing NAT state) can kill a busy nginx HTTP/3
connection about a quarter of the time, while the same event always kills HTTP/2.

# M4b — 0-RTT and replay (2026-11-22)

Script: `code/scripts/m4-zerortt.sh`; client `code/scripts/m4_zerortt.py` (aioquic 1.2.0 — the
lab's curl has `--tls-earlydata` but was built without `--ssl-sessions`, so it cannot keep a
ticket between runs); replay sender `code/scripts/m4_replay.py`. Raw data:
`results/m4/zerortt-<mode>/` (timings, one capture and extracted flight per replay delay, TLS
keys), `results/m4/zerortt-summary.txt`. RTT 50 ms, no loss, nginx with `ssl_early_data on`.

Three server modes: **plain** (only `ssl_early_data on`), **retry** (`quic_retry on`: the
server answers every new connection with a Retry and only accepts the Initial that carries
the token), **tooearly** (`if ($ssl_early_data = "1") { return 425; }`, RFC 8470).

## Time to response (small.html, mean of 5, 3 for tooearly)

| Mode | Full handshake | Resumed, 1-RTT | Resumed, 0-RTT |
|---|---|---|---|
| plain | 128 ms | 115 ms | **64 ms** |
| retry | 179 ms | 167 ms | 115 ms |
| tooearly | 134 ms | 116 ms | 63 ms, but **425** |

- 0-RTT saves exactly one RTT (≈50 ms). Resumption alone saves nothing in time: QUIC already
  merges the transport and TLS handshakes; it only skips the certificate.
- The access log confirms what the server did: `reused=.` (full), `reused=r` (resumed),
  `reused=r early=1` (request received in early data).
- Retry costs one extra RTT and takes away the whole 0-RTT gain (0-RTT + Retry = 115 ms, the
  same as a resumed 1-RTT handshake without Retry).
- With the 425 rule the 0-RTT request is refused; a real client must send it again after the
  handshake (RFC 8470), so the gain is lost too, but only for the requests the rule covers.

## Replay of the first flight

For each delay a new victim request (unique URL, fresh ticket) is captured at the router. Its
first flight is extracted from the capture and resent once, from the victim's address and
port, d seconds later. Without Retry the flight is **one 1200-byte datagram** with the Initial
(ClientHello with the PSK) and the 0-RTT packet (the GET) coalesced; with Retry it is the two
datagrams the client sends after the Retry (Initial with the token, then 0-RTT).

| Replay delay | plain | retry | tooearly |
|---|---|---|---|
| +1 s | **executed again** | **executed again** | 425 to both |
| +5 s | **executed again** | blocked | 425 to both |
| +6 / +7 s | **executed again** | — | — |
| +8 s and later (12, 15, 30, 70 s) | blocked | blocked | — |

"Executed again" means a second `200` line in the access log for the victim's URL, with
`early=1`: nginx served the replayed request although nobody completed a handshake.

Why the window closes:

- **plain, ~7–8 s.** From +8 s the debug log shows `quic no early keys, ignoring packet`:
  OpenSSL refuses the early data and only a 1-RTT handshake would follow, which the attacker
  cannot finish. This is the TLS 1.3 freshness check (RFC 8446 §8.3): the server compares
  the ticket age the client declared in the ClientHello with the age it computes itself, and
  the declared age is frozen in the captured packet. Up to +7 s the early data is accepted
  (`quic frame rx early:1 STREAM`). It is not a real anti-replay mechanism: nginx uses
  stateless tickets and keeps no record of used tickets or ClientHellos, so any copy that
  arrives inside the window is served.
- **retry, between 1 and 5 s.** The replayed flight carries the Retry token, which nginx
  accepts only for a few seconds; the token is also tied to the client's address (not
  tested here from a different address). After that the server sends a new Retry (to the
  real client's address) and discards the 0-RTT packet. Retry does not stop a replay within
  the token lifetime from the victim's address (an on-path attacker can do that), but it
  shortens the window considerably.
- **tooearly.** Nothing that arrives in early data is served, so replays have no effect. In
  practice the rule is limited to non-idempotent requests (POST, anything that changes
  state), so GETs keep the 0-RTT gain.

Side observations:

- A replay creates a half-open connection in nginx that lives for the 60 s handshake
  timeout, and nginx keeps retransmitting its handshake to the victim's address meanwhile
  (unsolicited packets, limited by the 3× anti-amplification rule). While it exists, further
  copies with the same connection ID go to it and are dropped as duplicates, so each victim
  flight can be replayed once per server per minute. With several servers behind a load
  balancer, each one could execute it.
- Lab notes: (1) `nginx -s reload` cannot be used between modes: the old worker stays alive
  while it holds those half-open connections, and with `reuseport` it keeps receiving part of
  the new connections (seen as `cannot decrypt token` for Retry tokens issued by the new
  worker, and as stalled handshakes). The script recreates the server, and nginx-m4.conf sets
  `quic_host_key` so all workers share the token key. (2) aioquic 1.2.0 does not resend
  stream data sent in 0-RTT before a Retry; `m4_zerortt.py` sends the request again on a new
  stream when a Retry arrives (`resent_after_retry=True` in the output).
