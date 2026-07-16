#!/usr/bin/env python3
"""Per-cycle detail table: line value at fall/rise + all data edges with phase."""
import numpy as np

SR = 200_000
data = np.load("/home/mikko/skannerz-trade-reversing/analysis/capture.npy")
clk = data[:, 1]
dat = data[:, 0]

fall = np.flatnonzero((clk[:-1] == 1) & (clk[1:] == 0)) + 1
rise = np.flatnonzero((clk[:-1] == 0) & (clk[1:] == 1)) + 1
dedge = np.flatnonzero(np.diff(dat)) + 1

def table(c0, c1, label):
    print(f"\n=== {label}: cycles {c0}..{c1} ===")
    print("cyc    t(s)      @fall @rise  edges(phase:dir)")
    for c in range(c0, c1):
        f = fall[c]
        r = rise[np.searchsorted(rise, f)]
        nf = fall[c + 1] if c + 1 < len(fall) else f + 142
        vf = dat[f]
        vr = dat[r - 2]
        es = dedge[(dedge >= f) & (dedge < nf)]
        estr = " ".join(f"+{e-f}:{'/' if dat[e] else chr(92)}" for e in es)
        print(f"{c:6d} {f/SR:9.4f}  {vf}     {vr}     {estr}")

table(2374, 2402, "poll: master 0x32 + slave 0x34")
