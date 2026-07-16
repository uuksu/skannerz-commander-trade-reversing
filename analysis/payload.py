#!/usr/bin/env python3
"""Full dump of non-poll activity regions for both senders, no truncation,
with run-length compression of long idle stretches."""
import numpy as np
import re

SR = 200_000
fall = np.load("/home/mikko/skannerz-trade-reversing/analysis/fall2.npy")
m_tx = np.load("/home/mikko/skannerz-trade-reversing/analysis/m_tx.npy")
s_tx = np.load("/home/mikko/skannerz-trade-reversing/analysis/s_tx.npy")

def compress(s):
    return re.sub(r"(1{15,})", lambda m: f"[1x{len(m.group(1))}]", s)

def dump(tx, name, t0, t1):
    print(f"\n### {name} {t0}-{t1}s ###")
    zeros = np.flatnonzero(tx == 0)
    zeros = zeros[(fall[zeros] >= t0 * SR) & (fall[zeros] <= t1 * SR)]
    if not len(zeros):
        print("silent")
        return
    brk = np.flatnonzero(np.diff(zeros) > 60)
    starts = np.concatenate(([0], brk + 1))
    ends = np.concatenate((brk, [len(zeros) - 1]))
    for s, e in zip(starts, ends):
        a, b = zeros[s], zeros[e]
        seg = "".join(str(x) for x in tx[a:b + 2])
        print(f"t={fall[a]/SR:8.4f}s cyc{a:6d}: {compress(seg)}")

# selection phase and first payload
dump(m_tx, "MASTER", 5.38, 8.0)
dump(s_tx, "SLAVE", 5.38, 8.1)
# second payload phase
dump(m_tx, "MASTER", 11.3, 13.75)
dump(s_tx, "SLAVE", 11.3, 13.75)
