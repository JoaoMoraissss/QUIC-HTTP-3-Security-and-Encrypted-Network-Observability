FROM archlinux:base
# nftables + conntrack-tools: M4 puts a NAT on the router to simulate NAT rebinding
RUN pacman -Syu --noconfirm --needed iproute2 tcpdump wireshark-cli nftables conntrack-tools && pacman -Scc --noconfirm
