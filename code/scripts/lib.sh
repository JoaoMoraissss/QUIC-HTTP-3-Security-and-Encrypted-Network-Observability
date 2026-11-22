# shared helpers (source from code/)
# set COMPOSE_FILE=docker-compose.m3.yml and LAB_NET=10.20 to use the second lab copy
# interface of the router on the client network / server network (Docker does not fix the order)
rif() { docker compose exec -T router sh -c "ip -o -4 addr show | awk '/ $1\\//{print \$2}'"; }
LAB_NET=${LAB_NET:-10.10}   # 10.20 for docker-compose.m3.yml
RIF_CLIENT=$(rif $LAB_NET.1.254)
RIF_SERVER=$(rif $LAB_NET.2.254)

# netem on both router interfaces: RTT/2 each way, same loss each way, 50 Mbit/s bottleneck (RATE and LIMIT override)
set_netem() {  # $1 = RTT in ms, $2 = loss in %
  local half; half=$(awk "BEGIN{print $1/2}")
  for i in $RIF_CLIENT $RIF_SERVER; do
    docker compose exec -T router tc qdisc replace dev "$i" root netem \
      delay "${half}ms" loss "${2}%" rate ${RATE:-50mbit} limit ${LIMIT:-2000}
  done
}
clear_netem() {
  for i in $RIF_CLIENT $RIF_SERVER; do docker compose exec -T router tc qdisc del dev "$i" root 2>/dev/null || true; done
}
