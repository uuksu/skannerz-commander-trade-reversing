#!/usr/bin/env python3
"""Phase of each data transition within the clock cycle (vs preceding falling edge)."""
import numpy as np
from collections import Counter

SR = 200_000
data = np.load("/home/mikko/skannerz-trade-reversing/analysis/capture.npy")
clk = data[:, 1]
dat = data[:, 0]

fall = np.flatnonzero((clk[:-1] == 1) & (clk[1:] == 0)) + 1
rise = np.flatnonzero((clk[:-1] == 0) & (clk[1:] == 1)) + 1
dedge = np.flatnonzero(np.diff(dat)) + 1
print(f"data edges: {len(dedge)}")

# phase relative to preceding falling clock edge (clock period ~142)
idx = np.searchsorted(fall, dedge) - 1
valid = idx >= 0
ph_fall = dedge[valid] - fall[idx[valid]]

c = Counter(ph_fall)
print("\nphase after preceding FALLING clock edge (samples, period~142):")
for p in sorted(c):
    if c[p] > 5:
        print(f"  +{p:4d}: {c[p]} times")

# split data edges by phase group and see when each group is active
lo = dedge[valid][(ph_fall >= 0) & (ph_fall < 30)]
hi = dedge[valid][(ph_fall >= 60) & (ph_fall < 110)]
print(f"\ngroup A (phase 0-30): {len(lo)} edges, "
      f"{lo[0]/SR:.3f}s - {lo[-1]/SR:.3f}s" if len(lo) else "group A empty")
print(f"group B (phase 60-110): {len(hi)} edges, "
      f"{hi[0]/SR:.3f}s - {hi[-1]/SR:.3f}s" if len(hi) else "group B empty")
