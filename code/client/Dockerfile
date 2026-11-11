FROM archlinux:base
# curl here is built with ngtcp2 + nghttp3 (HTTP/3) and writes qlog when QLOGDIR is set
RUN pacman -Syu --noconfirm --needed curl iproute2 python python-pip && pacman -Scc --noconfirm
RUN pip install --break-system-packages --no-cache-dir aioquic==1.2.0
