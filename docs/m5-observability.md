# M5 — Endpoint observability (2026-11-22)

Script: `code/scripts/m5-events.sh` (E1, E2, E4, E6); E3 and E5 reuse the M4 captures
(`results/m4/rebind-*`). Raw data: `results/m5/<event>-<proto>/` with the passive capture
(router, client side), the client TLS keys, the client qlog and the new lines of the server's
`access.log` and `error.log`.

Sources compared, as in report 1:

- **capture** — what a passive observer on the path sees, without keys. For QUIC this
  includes the Initial packets, which anyone can decrypt (the keys come from the DCID).
- **qlog** — client side only: curl/ngtcp2 (`QLOGDIR`) or aioquic. nginx 1.31.8 has no qlog
  output at all (no `qlog` string in the binary).
- **server logs** — `access.log` and `error.log` at level `info`, as an operator would run
  them. The debug log is used only to explain results, not as a source.

The decrypted capture (with the client's keys) is used to check what really happened.

## Table

✔ visible · ◐ only by inference (sizes, timing, what is missing) · ✘ not visible · — not applicable

| Event | TCP/TLS capture (H2) | QUIC capture (H3) | qlog (client, H3) | Server logs H2 | Server logs H3 |
|---|---|---|---|---|---|
| E1 failed handshake (untrusted cert) | ◐ | ◐ | ✔ (code only) | ✘ | ✘ |
| E2 Retry | — | ✔ | ✔ | — | ✘ |
| E3 address change (NAT rebinding) | ✔ | ✔ (linkable by DCID) | ✔ (path challenge) | — | ✔ |
| E4 stream reset | ✘ | ✘ | ✔ | ✔ | ◐ |
| E5 connection close with error code | ✔ (TCP) / ✘ (H2 code) | ✘ | ✘ | — | ✘ |
| E6 rejected 0-RTT | — | ◐ | ◐ | — | ✔ |

## Evidence per event

**E1 — failed handshake** (curl without the lab CA).
- H2 capture: the handshake completes. The client sends its Finished, then a FIN without any
  request; the server's session tickets get RSTs. curl checks the certificate only after the
  handshake and sends **no TLS alert**, so for the server and the observer this is just a
  client that connected and left.
- H3 capture: Initial and Handshake packets, then silence. The client's CONNECTION_CLOSE goes
  in a **Handshake** packet (keys unknown to the observer), so it cannot be read, even though
  the Initial packets can.
- Decrypted / qlog: `connection_close`, transport error **INTERNAL_ERROR (1)**, not the TLS
  `bad_certificate` code (0x12a): the real reason does not go on the wire at all.
- Server logs: nothing in either protocol (no access line, no error line at `info`).

**E2 — Retry** (`quic_retry on`).
- QUIC capture: two Retry packets (long header type 3, one per datagram of the client's first
  flight), then the client's Initial with a 78-byte token. Fully visible.
- qlog: `packet_received` of type `retry` with the token.
- Server logs: only the normal access line; the Retry itself is logged only at debug level.

**E3 — address change** (M4a, `rebind-h3-4-102`, `rebind-h2-4-1`).
- H2 capture: the TCP connection dies with RSTs in both directions.
- QUIC capture: a new 4-tuple appears. The PATH_CHALLENGE/PATH_RESPONSE frames are encrypted,
  but the **client keeps the same DCID** before and after the rebinding (it does not know it
  moved), so the observer links the two paths by a field in the packets, not only by timing.
- qlog: the client logs the server's two `path_challenge` and its `path_response`.
- Server error.log: `quic migrated to path seq:1 addr:10.20.2.254:40002` and
  `... successfully validated`. The access log shows only the port at the start of the request.

**E4 — stream reset** (two transfers on one connection, `big.bin` cancelled by curl).
- Captures: nothing distinguishes the reset in either protocol. Both RST_STREAM (H2) and
  STOP_SENDING (H3) travel encrypted, and the connection continues. (In the H2 run the
  connection ends with FIN/RST only because curl exits afterwards.)
- Decrypted / qlog: H3 `stop_sending` on stream 0 with **H3_REQUEST_CANCELLED (0x10c)**; H2
  `RST_STREAM` on stream 1.
- Server logs: H2 error.log `client terminated stream 1 with status 5`. H3: no error line. In
  both the access log records **200** with fewer bytes than the file (5.4 MB of 10 MiB in H3),
  so the reset can only be guessed from the size.

**E5 — connection close with an error code** (M4a failed run, `rebind-h3-4-101`).
- nginx closed with `NO_VIABLE_PATH (0x10)` (debug log only) and **did not send a
  CONNECTION_CLOSE**: the client learnt it from a **Stateless Reset** sent in reply to its next
  packet (`packet_received` of type `stateless_reset` in the qlog, then `ERR_DRAINING`). A
  Stateless Reset is designed to look like any short-header packet, so the observer sees
  nothing. The error code appears in no source available to an operator.
- Normal closes carry a code too (curl sends `connection_close` with NO_ERROR, in the qlog),
  but always inside encrypted short-header packets.
- H2: the TCP-level end (FIN/RST) is visible (E3, E1); the HTTP/2 GOAWAY code is encrypted.

**E6 — rejected 0-RTT** (ticket from a server instance that was recreated, new ticket keys).
- QUIC capture: the client's first datagram carries a **0-RTT packet** (type 1, 89 bytes),
  visible. The rejection is not, but it can be inferred: the server's Handshake packet is
  **1013 bytes** (it contains the certificate, so no resumption), against **265 bytes** and a
  1-RTT response coalesced in the same datagram when 0-RTT is accepted (M4b victim capture);
  and the client sends a request of the same size again after the handshake.
- qlog (aioquic): the `0RTT` packet is sent, later declared lost (`packet_lost`), and the
  stream is sent again in 1-RTT. No explicit "rejected" event.
- Server logs: error.log `quic no early keys, ignoring packet`; access log `reused=. early=-`.

## Against hypothesis H4

H4 expected: H2 events mostly visible through TCP flags and retransmissions; for QUIC the
handshake and Retry visible, the address change linkable only by timing, and stream resets,
error codes and rejected 0-RTT only in qlog and the server logs.

- **Confirmed:** Retry visible on the wire; stream resets and error codes not visible in the
  QUIC capture.
- **Not confirmed — address change:** linkable by the unchanged client DCID, not only by timing
  (because a NAT rebinding is passive; RFC 9000 only asks for a new CID when the endpoint
  itself migrates).
- **Not confirmed — rejected 0-RTT:** partly inferable from the capture through the size of the
  server's Handshake flight.
- **Worse than expected on the endpoint side:** the server logs miss several events at
  `info` level (failed handshake, Retry, H3 stream reset, the error code of a close), and nginx
  has no qlog, so "endpoint telemetry" here means the *client's* qlog. An operator of this
  server gets back less than the hypothesis assumed.
- **H2 only partly as expected:** connection-level events (E3, E5 at TCP level, E1 as an empty
  connection) are visible; stream-level events (E4) and HTTP/2 error codes are encrypted too,
  and curl's failed handshake produces no TLS alert.
