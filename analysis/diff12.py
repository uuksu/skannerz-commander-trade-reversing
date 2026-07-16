#!/usr/bin/env python3
"""Where do ch1 and ch2 differ? Characterize handshake phase."""
import numpy as np

SR = 200_000
data = np.load("/home/mikko/skannerz-trade-reversing/analysis/capture.npy")
c1, c2 = data[:, 1], data[:, 2]

diff = np.flatnonzero(c1 != c2)
print(f"samples where ch1!=ch2: {len(diff)}")
if len(diff):
    print(f"first: {diff[0]} ({diff[0]/SR:.4f}s), last: {diff[-1]} ({diff[-1]/SR:.4f}s)")
    # cluster the differing samples
    brk = np.flatnonzero(np.diff(diff) > SR // 100)
    starts = np.concatenate(([0], brk + 1))
    ends = np.concatenate((brk, [len(diff) - 1]))
    print(f"{len(starts)} difference clusters (gap>10ms):")
    for s, e in zip(starts[:20], ends[:20]):
        print(f"  {diff[s]/SR:8.4f}s - {diff[e]/SR:8.4f}s  ({diff[e]-diff[s]} samples)")
