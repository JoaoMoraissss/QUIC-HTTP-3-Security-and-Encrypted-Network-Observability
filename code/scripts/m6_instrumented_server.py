#!/usr/bin/env python3
"""M6 debugging aid: aioquic server (whatever version is installed) that prints, every
second, the internal state of each connection: congestion window, bytes in flight,
queued PATH_CHALLENGEs, sent packets awaiting an ACK, PTO count. Used to explain the
PATH_CHALLENGE flood results; not part of the measurements."""
import asyncio, sys
from aioquic.asyncio import QuicConnectionProtocol, serve
from aioquic.h3.connection import H3_ALPN
from aioquic.quic.configuration import QuicConfiguration
from aioquic.tls import Epoch

conns = []
# count PATH_RESPONSE frames by the congestion budget the builder had when writing them
from aioquic.quic.packet_builder import QuicPacketBuilder
from aioquic.quic.packet import QuicFrameType
stats = {"resp_budget_neg": 0, "resp_budget_pos": 0, "resp_budget_none": 0, "min_budget": None}
_orig_sf = QuicPacketBuilder.start_frame
def _sf(self, frame_type, *a, **kw):
    if frame_type == QuicFrameType.PATH_RESPONSE:
        b = self.max_flight_bytes
        k = "resp_budget_none" if b is None else ("resp_budget_neg" if b <= 0 else "resp_budget_pos")
        stats[k] += 1
        if b is not None and (stats["min_budget"] is None or b < stats["min_budget"]):
            stats["min_budget"] = b
    return _orig_sf(self, frame_type, *a, **kw)
QuicPacketBuilder.start_frame = _sf
class P(QuicConnectionProtocol):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw); conns.append(self._quic)

async def report():
    while True:
        await asyncio.sleep(1)
        for q in conns:
            loss = q._loss; sp = q._spaces.get(Epoch.ONE_RTT)
            rc = sum(len(getattr(p, "remote_challenges", ()) or ()) for p in q._network_paths)
            print(f"cwnd={loss.congestion_window} in_flight={loss.bytes_in_flight} "
                  f"queued_challenges={rc} sent_unacked={len(sp.sent_packets) if sp else 0} "
                  f"pto_count={loss._pto_count} paths={len(q._network_paths)} {stats}", flush=True)

async def main():
    cfg = QuicConfiguration(is_client=False, alpn_protocols=H3_ALPN)
    cfg.load_cert_chain(sys.argv[1], sys.argv[2])
    await serve("0.0.0.0", 4433, configuration=cfg, create_protocol=P)
    await report()
asyncio.run(main())
