# M3 — Wire image of HTTP/2 and HTTP/3

Captures taken on 2026-11-11 with `code/scripts/m3-capture.sh` on the second lab copy
(`docker-compose.m3.yml`, networks 10.20.x). RTT 50 ms (25 ms each way), no loss.
Each connection carries two requests: `/small.html` (1386 B) and `/obj/1.txt` (2768 B).
The capture point is the router, client side, i.e. an on-path passive observer.

Views (from `code/scripts/m3-annotate.sh`, in `results/m3/`):

- **observer**: the pcap alone. For QUIC this still includes the content of Initial packets,
  because their keys are derived from the client's first Destination Connection ID, which is
  sent in clear (RFC 9001 §5.2). Anyone on the path can decrypt them, Wireshark does it by default.
- **endpoint**: the same pcap decrypted with the client's TLS key log, plus the curl qlog
  and the nginx access log.

Frame numbers below refer to `h2.pcap` and `h3.pcap`.

**Capture artefact.** Some frames are larger than the 1500-byte MTU (H2 frame 4: 1668 B,
H3 frame 1: 2442 B). This is segmentation offload on the veth links (GSO/GRO), so tcpdump sees
two packets merged. On the wire they are two TCP segments / two QUIC datagrams of ≤1252 B.

## 1. Timeline

| Phase | HTTP/2 over TCP+TLS | HTTP/3 over QUIC |
|---|---|---|
| Transport handshake | SYN f1 (0 ms), SYN/ACK f2 (50.1 ms), ACK f3 | — (merged with TLS) |
| TLS handshake | ClientHello f4 (51.6 ms), ServerHello…Finished f6 (103.0 ms), client Finished f8 | Initial ClientHello f1 (0 ms), server Initial ACK f2 + ServerHello f3 (50.8–51.8 ms), Handshake f5, client Finished f6 (53.2 ms) |
| First request leaves the client | f9, 104.5 ms | f8, 53.3 ms |
| First response arrives | f14–16, 155.1 ms | f10–11, 104.3 ms |
| Second request (same connection) | f17, 155.6 ms | f14, 104.8 ms |
| Connection close | client FIN f25, server FIN f27 | client CONNECTION_CLOSE f21 (NO_ERROR, encrypted) |

The first response arrives after 3 RTT with HTTP/2 and 2 RTT with HTTP/3. This is the same
difference measured in M2 for the small object (median ratio 0.68).

## 2. What a passive observer can infer

| Information | HTTP/2 (observer) | HTTP/3 (observer) | Evidence |
|---|---|---|---|
| Server name | yes, SNI in the ClientHello | yes, SNI in the Initial (decryptable by anyone) | H2 f4, H3 f1 |
| Application protocol | yes, ALPN `h2,http/1.1` | yes, ALPN `h3,h3-29` | H2 f4, H3 f1 |
| Transport / version | TCP, port 443 | QUIC version 1 in every long header | H3 f1–f6 |
| Key exchange group | yes, X25519MLKEM768 (0x11EC) in ClientHello | yes, same | H2 f4, H3 f1 |
| Handshake RTT | yes, SYN → SYN/ACK = 50.1 ms | yes, client Initial → server Initial = 50.8 ms | H2 f1–f2, H3 f1–f2 |
| RTT during the transfer | yes, from sequence/ack numbers at any time | **no**: spin bit is 0 in all 18 short-header packets, so it is disabled | H2 f8→f11, H3 f7–f23 |
| Loss and retransmissions | yes, from TCP sequence numbers | **no**: packet numbers are encrypted by header protection | `tcp.seq` present vs no `quic.packet_number` in observer view |
| Flow identifier | 4-tuple | 4-tuple **and** connection IDs: `b71b…` (client→server) and `99c4…` (server→client) in every packet | H3 f1–f23 |
| Request and response sizes | approximately, from TLS record lengths (1417 B segment for the 1386 B page) | approximately, from datagram sizes (f10+f11) | H2 f16, H3 f10–f11 |
| Number of requests | yes, from bursts of client records | yes, from bursts of client packets | H2 f9, f17; H3 f8, f14 |
| Session tickets issued | likely: two 287 B records right after the handshake | no clear pattern (inside 1-RTT packet f9) | H2 f11–f12 |
| Connection end | yes, FIN from both sides | **no**: only a small last packet, then silence | H2 f25, f27; H3 f21 |
| Method, path, status, headers | no | no | endpoint only |
| Stream IDs, multiplexing | no | no | endpoint only (H2 streams 1, 3; H3 streams 0, 4) |
| Close reason / error code | no (FIN or RST only) | no | H3 f21: CONNECTION_CLOSE, error 0, endpoint only |
| Transport parameters (idle timeout, migration allowed) | n/a | no (inside the encrypted handshake) | qlog: `disable_active_migration: false` |

## 3. Points worth discussing in the report

1. **QUIC Initial packets are encrypted but not confidential.** The SNI and ALPN are as visible
   as in TLS over TCP. Only Encrypted Client Hello would hide the server name, and we did not
   configure it in the lab.
2. **The client splits and shuffles its ClientHello.** Frame 1 carries the ClientHello in 22
   CRYPTO frames, out of order (offsets 403, 386, 807, …, 0, …), mixed with PING and PADDING.
   A middlebox that only reads the first CRYPTO frame cannot find the SNI. Wireshark reassembles
   it, so this protects only against simple filters (see Zohaib et al. 2025 on SNI-based QUIC
   censorship).
3. **TCP gives the operator RTT, loss and end of connection for free. QUIC gives none of these
   after the handshake.** The spin bit would give RTT, but neither curl/ngtcp2 nor nginx turned
   it on (RFC 9000 §17.4 makes it optional, and even when used it must be disabled on at least one in
   every 16 paths or connection IDs). This confirms H2 from report 1: the observer gets server name, ALPN, version,
   connection IDs, sizes, timing and a handshake RTT, and nothing about loss or RTT later on.
4. **Connection IDs are a new identifier that TCP does not have.** They allow an observer to
   link packets of one connection even if the 4-tuple changes. This is the reason for the
   rules on CID rotation after migration, which M4 tests.
5. **Post-quantum key exchange is already the default.** X25519MLKEM768 makes the ClientHello
   larger than one packet in both protocols (two TCP segments, two QUIC Initials). For QUIC this
   means the server cannot answer before the second Initial arrives, and both Initials count
   towards the anti-amplification limit (3× the bytes received).
