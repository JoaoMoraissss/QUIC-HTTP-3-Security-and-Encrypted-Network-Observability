#!/usr/bin/env python3
"""M4b: HTTP/3 GET with aioquic, optionally resuming a saved session and sending
the request as 0-RTT early data.

  m4_zerortt.py URL --save-ticket T            full handshake, store the ticket
  m4_zerortt.py URL --ticket T [--zero-rtt]    resumed handshake (1-RTT or 0-RTT)

Prints one line: whether the session was resumed, whether early data was
accepted by the server, the status code and the time to the response.
TLS secrets go to --keylog (for Wireshark), so the 0-RTT packets can be decrypted.
"""
import argparse, asyncio, pickle, ssl, time
from urllib.parse import urlparse

from aioquic.asyncio import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.h3.events import DataReceived, HeadersReceived
from aioquic.quic.configuration import QuicConfiguration


class Client(QuicConnectionProtocol):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.h3 = H3Connection(self._quic)
        self.done = asyncio.get_event_loop().create_future()
        self.status, self.body = None, 0
        self.url, self.resent = None, False

    def datagram_received(self, data, addr):
        # aioquic 1.2.0 restarts the handshake after a Retry but does not resend the
        # stream data that went out in 0-RTT before it (the server discarded those
        # packets), so the request would never be answered. Send it again on a new
        # stream; it goes out as 0-RTT again, now in the flight that carries the token.
        retries = self._quic._retry_count
        super().datagram_received(data, addr)
        if self._quic._retry_count > retries and self.url and self.status is None:
            self.resent = True
            self.get(self.url)

    def get(self, url):
        self.url = url
        u = urlparse(url)
        sid = self._quic.get_next_available_stream_id()
        self.h3.send_headers(sid, [
            (b":method", b"GET"), (b":scheme", b"https"),
            (b":authority", u.netloc.encode()),
            (b":path", (u.path + ("?" + u.query if u.query else "")).encode()),
            (b"user-agent", b"m4-zerortt"),
        ], end_stream=True)
        self.transmit()

    def quic_event_received(self, event):
        for e in self.h3.handle_event(event):
            if isinstance(e, HeadersReceived):
                self.status = dict(e.headers).get(b":status", b"?").decode()
            elif isinstance(e, DataReceived):
                self.body += len(e.data)
            if getattr(e, "stream_ended", False) and not self.done.done():
                self.done.set_result(True)


async def main(a):
    u = urlparse(a.url)
    cfg = QuicConfiguration(is_client=True, alpn_protocols=H3_ALPN,
                            server_name=u.hostname, cafile=a.cafile)
    if a.keylog:
        cfg.secrets_log_file = open(a.keylog, "a")
    if a.ticket:
        with open(a.ticket, "rb") as f:
            cfg.session_ticket = pickle.load(f)

    tickets = []
    t0 = time.monotonic()
    async with connect(u.hostname, u.port or 443, configuration=cfg,
                       create_protocol=Client,
                       session_ticket_handler=tickets.append,
                       wait_connected=not a.zero_rtt) as c:
        c.get(a.url)                      # with --zero-rtt this goes out in 0-RTT packets
        await asyncio.wait_for(c.done, 10)
        t = time.monotonic() - t0
        tls = c._quic.tls
        # give the server time to send NewSessionTicket
        await asyncio.sleep(0.3)
        print(f"resumed={tls.session_resumed} early_data_accepted={tls.early_data_accepted} "
              f"zero_rtt_sent={a.zero_rtt} resent_after_retry={c.resent} status={c.status} body={c.body} t={t:.3f}s")
    if a.save_ticket and tickets:
        with open(a.save_ticket, "wb") as f:
            pickle.dump(tickets[-1], f)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("--cafile", default="/certs/ca.crt")
    p.add_argument("--ticket"); p.add_argument("--save-ticket")
    p.add_argument("--zero-rtt", action="store_true")
    p.add_argument("--keylog")
    asyncio.run(main(p.parse_args()))
