#!/usr/bin/env python3
"""Full-session decoder implementing the rules in PROTOCOL.md.

Produces a chronological transcript of every frame in the capture:
  - master frames: bits sampled at falling edges (F stream), 12-cycle units
  - slave frames: bits sampled at rising edges (R stream), 10/11-cycle units
  - 52-cycle payload frames in either stream
  - master ack pulses (2-cycle low in F right after slave frames)
Sender attribution: data-line transition phase within the frame span
(slave < 40 samples after falling edge; master >= 40).
"""
import numpy as np

SR = 200_000
data = np.load("/home/mikko/skannerz-trade-reversing/analysis/capture.npy")
clk = data[:, 1]
dat = data[:, 0]

fall = np.flatnonzero((clk[:-1] == 1) & (clk[1:] == 0)) + 1
rise = np.flatnonzero((clk[:-1] == 0) & (clk[1:] == 1)) + 1
dedge = np.flatnonzero(np.diff(dat)) + 1

ri = np.searchsorted(rise, fall)
ok = ri < len(rise)
fall = fall[ok]
F = dat[fall]                    # master slots
R = dat[rise[ri[ok]] - 2]        # slave slots
n = len(fall)

ci = np.searchsorted(fall, dedge) - 1
v = (ci >= 0) & (ci < n)
phase = dedge[v] - fall[ci[v]]
cyc_of_edge = ci[v]
slave_edges = np.zeros(n, dtype=bool)
master_edges = np.zeros(n, dtype=bool)
slave_edges[cyc_of_edge[phase < 40]] = True
master_edges[cyc_of_edge[phase >= 40]] = True

def parse_payload(bits, c, act):
    if "".join(str(b) for b in bits[c:c + 4]) != "0111":
        return None
    seg = bits[c:c + 52]
    if len(seg) < 52 or seg[51] != 1 or act[c:c + 52].sum() < 8:
        return None
    val = lambda a, b: int("".join(str(x) for x in seg[a:b]), 2)
    return (f"payload ID={val(4,12)+1} lvl={val(12,16)} HP={val(16,24)}"
            f"/{val(24,32)} unk={val(32,44)} EXP={val(44,51)}")

events = []  # (cycle, who, text)
c = 0
while c < n - 10:
    f_start = F[c] == 0 and F[c - 1] == 1 if c else F[c] == 0
    r_start = R[c] == 0 and R[c - 1] == 1 if c else R[c] == 0
    if not (f_start or r_start):
        c += 1
        continue
    m_act = master_edges[max(0, c - 1):c + 10].sum()
    s_act = slave_edges[max(0, c - 1):c + 10].sum()
    # master ack pulse: exactly 2 low cycles in F with master-phase edges
    if (f_start and m_act and not s_act
            and F[c] == 0 and F[c + 1] == 0 and F[c + 2] == 1
            and F[c + 3] == 1):
        events.append((c, "M", "ack pulse"))
        c += 3
        continue
    if f_start and m_act > s_act:            # master frame on F stream
        p = parse_payload(F, c, master_edges)
        if p:
            events.append((c, "M", p))
            c += 52
            continue
        byte = int("".join(str(x) for x in F[c + 1:c + 9]), 2)
        stop, tr = F[c + 9], F[c + 10]
        events.append((c, "M", f"0x{byte:02X}"
                       + ("" if stop == 1 and tr == 0 else " (frame anomaly)")))
        c += 12
    elif r_start and s_act >= 2:             # slave frame on R stream
        p = parse_payload(R, c, slave_edges)
        if p:
            events.append((c, "S", p))
            c += 52
            continue
        byte = int("".join(str(x) for x in R[c + 1:c + 9]), 2)
        stop = R[c + 9]
        kind = "" if stop == 1 else " (event frame, low stop)"
        events.append((c, "S", f"0x{byte:02X}{kind}"))
        c += 10 + (2 if stop == 0 else 0)
    else:
        c += 1

# condense repeats
print(f"{len(events)} events\n")
i = 0
while i < len(events):
    c0, who, txt = events[i]
    j = i
    while (j + 2 < len(events) and events[j + 1][2] == events[i + 1][2]
           and events[j + 2][2] == txt and events[j + 1][1] == events[i + 1][1]
           and i + 1 < len(events)) if i + 1 < len(events) else False:
        j += 2
    # simple approach: count consecutive identical (who,txt)
    k = i
    while k + 1 < len(events) and events[k + 1][1:] == (who, txt):
        k += 1
    reps = k - i + 1
    t = fall[c0] / SR
    print(f"t={t:8.4f}s cyc{c0:6d} {who}: {txt}" + (f"  x{reps}" if reps > 1 else ""))
    i = k + 1
