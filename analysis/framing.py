#!/usr/bin/env python3
"""Histogram inter-clock gaps to find byte framing, then decode bytes."""
import numpy as np
from collections import Counter

SR = 200_000
data = np.load("/home/mikko/skannerz-trade-reversing/analysis/capture.npy")
clk = data[:, 1]
dat = data[:, 0]

fall = np.flatnonzero((clk[:-1] == 1) & (clk[1:] == 0)) + 1
gaps = np.diff(fall)

c = Counter(gaps)
print("gap histogram (samples between consecutive falling edges):")
for g in sorted(c):
    if c[g] > 2 or g > 200:
        print(f"  {g:7d} samples ({g/SR*1000:9.3f} ms): {c[g]} times")
