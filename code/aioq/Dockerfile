# M6: aioquic HTTP/3 server, one image per aioquic release (build arg)
FROM python:3.11-slim
ARG AIOQUIC_VERSION
RUN apt-get update && apt-get install -y --no-install-recommends iproute2 procps \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir "aioquic==${AIOQUIC_VERSION}"
COPY aioq_server.py /aioq_server.py
CMD ["sh", "-c", "ip route add 10.20.1.0/24 via 10.20.2.254 && exec python -u /aioq_server.py"]
