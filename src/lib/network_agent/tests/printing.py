"""Printing helpers shared by the demos (step 4 quote, step 5a reserve / commit)."""


def hops(topology, path):
    """Directed link id sequence → 'anl-n02 ─L1→ esnet-atl ─L2→ ...'"""
    links = [topology.links[d] for d in path]
    return links[0].src + "".join(f" ─{d.link_id}→ {d.dst}" for d in links)


def print_network(title, net):
    """Title banner, then the simulated network: nodes, links, background traffic, outages."""
    topo = net.topology
    print(f"\n{'=' * 100}\n{title}\n{'=' * 100}")
    print("Nodes:", ", ".join(topo.nodes))
    print("Links (physical; capacity is per direction):")
    printed = set()
    for d in topo.links.values():                           # print each physical link once, in its defined a → b direction
        if d.link_id not in printed:
            printed.add(d.link_id)
            print(f"  {d.link_id}: {d.src} — {d.dst}   {d.capacity_gbps:g} Gbps")
    print("Background traffic:")
    for link, ivs in net._background.items():
        for iv in ivs:
            print(f"  {link}   {iv.start:%H:%M}–{iv.end:%H:%M}   {iv.gbps:g} Gbps")
    print("Outages:", [f"{link} {iv.start:%H:%M}–{iv.end:%H:%M}" for link, ivs in net._outages.items() for iv in ivs] or "none")
