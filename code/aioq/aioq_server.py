#!/usr/bin/env python3
"""M6: minimal HTTP/3 server on aioquic (same code for every release under test).
Answers every request with 200 and a short body. aioquic's own log (INFO) goes to stdout,
so `docker compose logs` shows each connection close and its error code."""
import asyncio, logging
import aioquic
from aioquic.asyncio import QuicConnectionProtocol, serve
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.h3.events import HeadersReceived
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import ConnectionTerminated, ProtocolNegotiated

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("server")


class H3Server(QuicConnectionProtocol):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.h3 = None

    def quic_event_received(self, event):
        if isinstance(event, ProtocolNegotiated):
            self.h3 = H3Connection(self._quic)
        elif isinstance(event, ConnectionTerminated):
            log.info("terminated code=0x%x frame_type=%s reason=%r",
                     event.error_code, event.frame_type, event.reason_phrase)
        if self.h3 is None:
            return
        for e in self.h3.handle_event(event):
            if isinstance(e, HeadersReceived):
                body = b"ok aioquic " + aioquic.__version__.encode() + b"\n"
                self.h3.send_headers(e.stream_id, [(b":status", b"200"),
                                     (b"content-length", str(len(body)).encode())])
                self.h3.send_data(e.stream_id, body, end_stream=True)
                self.transmit()


async def main():
    cfg = QuicConfiguration(is_client=False, alpn_protocols=H3_ALPN)
    cfg.load_cert_chain("/certs/server.crt", "/certs/server.key")
    await serve("0.0.0.0", 443, configuration=cfg, create_protocol=H3Server)
    log.info("aioquic %s listening on 443", aioquic.__version__)
    await asyncio.Future()

asyncio.run(main())
