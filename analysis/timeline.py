#!/usr/bin/env python3
"""Reconstruct per-device TX waveforms from own-phase data edges.

Master updates data in the clock-high half (phase ~+72 after falling edge).
Slave updates in the clock-low half (phase ~+7).
Phase +103..105 edges: unknown group, reported separately.

Output: per-cycle master TX bit and slave TX bit (1 = idle/high),
then raw bit dumps of all activity regions per sender.
"""
import numpy as np
from collections import Counter

SR = 200_000
data = np.load("/home/mikko/skannerz-trade-reversing/analysis/capture.npy")
clk = data[:, 1]
dat = data[:, 0]

fall = np.flatnonzero((clk[:-1] == 1) & (clk[1:] == 0)) + 1
dedge = np.flatnonzero(np.diff(dat)) + 1
polarity = dat[dedge]  # value AFTER the edge

ci = np.searchsorted(fall, dedge) - 1
valid = ci >= 0
dedge, polarity, ci = dedge[valid], polarity[valid], ci[valid]
phase = dedge - fall[ci]

is_slave = phase < 40
is_master = (phase >= 40) & (phase < 95)
is_odd = phase >= 95

print("edge counts: master", is_master.sum(), "slave", is_slave.sum(),
      "odd(+95..)", is_odd.sum())
oc = Counter(zip(phase[is_odd] // 1, polarity[is_odd]))
print("odd edges by (phase,polarity):",
      dict(Counter(polarity[is_odd])))

n = len(fall)
m_tx = np.ones(n, dtype=np.uint8)
s_tx = np.ones(n, dtype=np.uint8)

# master edge in cycle c: master's new value (polarity) holds from cycle c+1's
# falling-edge sample onward. Build by forward fill.
def build(cycles, pol, delay):
    tx = np.ones(n, dtype=np.uint8)
    last = 1
    ptr = 0
    order = np.argsort(cycles)
    cyc = cycles[order]
    pv = pol[order]
    cur = 1
    prev_c = 0
    out = np.ones(n, dtype=np.uint8)
    for c, p in zip(cyc, pv):
        c2 = min(c + delay, n)
        out[prev_c:c2] = cur
        cur = p
        prev_c = c2
    out[prev_c:] = cur
    return out

# master bit for cycle c is sampled at fall[c]; a master edge in cycle c's
# high half changes the value seen from fall[c+1] on -> delay 1.
m_tx = build(ci[is_master], polarity[is_master], 1)
# slave bit for cycle c is sampled at rise (mid-cycle); a slave edge in cycle
# c's low half changes the value seen at cycle c's rising edge -> delay 0.
s_tx = build(ci[is_slave], polarity[is_slave], 0)

np.save("/home/mikko/skannerz-trade-reversing/analysis/m_tx.npy", m_tx)
np.save("/home/mikko/skannerz-trade-reversing/analysis/s_tx.npy", s_tx)

def dump(tx, name):
    print(f"\n########## {name} TX activity ##########")
    zeros = np.flatnonzero(tx == 0)
    if not len(zeros):
        print("none")
        return
    brk = np.flatnonzero(np.diff(zeros) > 60)
    starts = np.concatenate(([0], brk + 1))
    ends = np.concatenate((brk, [len(zeros) - 1]))
    for s, e in zip(starts, ends):
        a, b = zeros[s], zeros[e]
        t = fall[a] / SR
        seg = "".join(str(x) for x in tx[a:b + 2])
        # compress long runs for readability
        print(f"t={t:8.4f}s cyc{a:6d} len{b-a+2:5d}: {seg[:400]}"
              + ("..." if len(seg) > 400 else ""))

dump(m_tx, "MASTER")
dump(s_tx, "SLAVE")
