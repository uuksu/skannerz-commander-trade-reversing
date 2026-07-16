#!/usr/bin/env python3
"""Compare data sampled at falling vs rising clock edges in key regions."""
import numpy as np

SR = 200_000
data = np.load("/home/mikko/skannerz-trade-reversing/analysis/capture.npy")
clk = data[:, 1]
dat = data[:, 0]

fall = np.flatnonzero((clk[:-1] == 1) & (clk[1:] == 0)) + 1
rise = np.flatnonzero((clk[:-1] == 0) & (clk[1:] == 1)) + 1

# also sample mid-low and mid-high: between fall and next rise, etc.
def show(t_start, nbits, label):
    i0 = np.searchsorted(fall, int(t_start * SR))
    print(f"\n=== {label} (t={fall[i0]/SR:.4f}s) ===")
    f = dat[fall[i0:i0 + nbits]]
    print("fall:", "".join(str(x) for x in f))
    j0 = np.searchsorted(rise, fall[i0])
    r = dat[rise[j0:j0 + nbits]]
    print("rise:", "".join(str(x) for x in r))
    # sample at middle of low half-period (between fall and following rise)
    mid_lo = (fall[i0:i0 + nbits] + rise[j0:j0 + nbits]) // 2
    m = dat[mid_lo]
    print("midl:", "".join(str(x) for x in m))

show(3.029, 40, "poll 32 C6 67")
show(5.385, 120, "dense section")
show(7.735, 150, "msg at 7.7361")
