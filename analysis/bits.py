#!/usr/bin/env python3
"""Sample data at falling clock edges; inspect bit pattern around data activity."""
import numpy as np

SR = 200_000
data = np.load("/home/mikko/skannerz-trade-reversing/analysis/capture.npy")
clk = data[:, 1]
dat = data[:, 0]

fall = np.flatnonzero((clk[:-1] == 1) & (clk[1:] == 0)) + 1
bits = dat[fall]
np.save("/home/mikko/skannerz-trade-reversing/analysis/fall.npy", fall)
np.save("/home/mikko/skannerz-trade-reversing/analysis/bits.npy", bits)

print(f"{len(bits)} bits, {bits.sum()} ones, {len(bits)-bits.sum()} zeros")

# find runs of activity in bit domain: positions where bit==0
zeros = np.flatnonzero(bits == 0)
print(f"first zero at bit index {zeros[0]}, last at {zeros[-1]}")

# print bitstream around first data activity, 0-runs grouped
brk = np.flatnonzero(np.diff(zeros) > 40)
starts = np.concatenate(([0], brk + 1))
ends = np.concatenate((brk, [len(zeros) - 1]))
print(f"{len(starts)} zero-clusters (separated by >40 idle bits)")
for i, (s, e) in enumerate(zip(starts[:8], ends[:8])):
    a, b = zeros[s], zeros[e]
    seg = bits[max(0, a - 2):b + 3]
    t = fall[a] / SR
    print(f"\ncluster {i}: bits {a}..{b} (t={t:.3f}s), len {b-a+1}:")
    print("  " + "".join(str(x) for x in seg))
