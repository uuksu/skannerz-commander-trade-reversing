#!/usr/bin/env python3
"""Find edge/activity regions per channel in the raw capture."""
import numpy as np

SAMPLE_RATE = 200_000

data = np.loadtxt("/home/mikko/skannerz-trade-reversing/trade.csv",
                  delimiter=",", skiprows=1, dtype=np.uint8)
print(f"samples: {data.shape[0]}, duration: {data.shape[0]/SAMPLE_RATE:.2f}s")

np.save("/home/mikko/skannerz-trade-reversing/analysis/capture.npy", data)

for ch in range(4):
    sig = data[:, ch]
    edges = np.flatnonzero(np.diff(sig))
    print(f"\nch{ch}: {len(edges)} edges, idle value at start={sig[0]}, at end={sig[-1]}")
    if len(edges):
        print(f"  first edge at sample {edges[0]} ({edges[0]/SAMPLE_RATE:.3f}s)")
        print(f"  last edge at sample {edges[-1]} ({edges[-1]/SAMPLE_RATE:.3f}s)")
        # activity clusters: gaps > 20ms separate bursts
        gaps = np.diff(edges)
        breaks = np.flatnonzero(gaps > SAMPLE_RATE // 50)
        n_bursts = len(breaks) + 1
        print(f"  bursts (gap>20ms): {n_bursts}")
