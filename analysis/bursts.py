#!/usr/bin/env python3
"""Verify channel pairing and map clock burst structure."""
import numpy as np

SR = 200_000
data = np.load("/home/mikko/skannerz-trade-reversing/analysis/capture.npy")

print("ch0==ch3:", np.array_equal(data[:, 0], data[:, 3]))
print("ch1==ch2:", np.array_equal(data[:, 1], data[:, 2]))

clk = data[:, 1]
dat = data[:, 0]

# falling edges of clock (CPOL=1, CPHA=0 -> sample data on falling edge)
fall = np.flatnonzero((clk[:-1] == 1) & (clk[1:] == 0)) + 1
rise = np.flatnonzero((clk[:-1] == 0) & (clk[1:] == 1)) + 1
print(f"clock falling edges: {len(fall)}, rising: {len(rise)}")

# split falling edges into bursts separated by >20ms of no clock activity
gaps = np.diff(fall)
brk = np.flatnonzero(gaps > SR // 50)
starts = np.concatenate(([0], brk + 1))
ends = np.concatenate((brk, [len(fall) - 1]))
print(f"\n{len(starts)} clock bursts (gap > 20ms):")
for i, (s, e) in enumerate(zip(starts, ends)):
    n = e - s + 1
    t0, t1 = fall[s] / SR, fall[e] / SR
    # median clock period inside burst
    if n > 1:
        per = np.median(np.diff(fall[s:e + 1]))
    else:
        per = 0
    print(f"  burst {i}: {n:6d} falling edges, {t0:8.3f}s - {t1:8.3f}s, "
          f"median period {per:.1f} samples ({SR/per if per else 0:.0f} Hz)")
