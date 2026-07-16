#!/usr/bin/env python3
"""Aligned @fall (master slot) / @rise (slave slot) bit strings for regions."""
import numpy as np

SR = 200_000
data = np.load("/home/mikko/skannerz-trade-reversing/analysis/capture.npy")
clk = data[:, 1]
dat = data[:, 0]

fall = np.flatnonzero((clk[:-1] == 1) & (clk[1:] == 0)) + 1
rise = np.flatnonzero((clk[:-1] == 0) & (clk[1:] == 1)) + 1
ri = np.searchsorted(rise, fall)
ok = ri < len(rise)
fallv = dat[fall[ok]]
risev = dat[rise[ri[ok]] - 2]
fall = fall[ok]

def show(c0, c1, label):
    print(f"\n=== {label}: cycles {c0}-{c1} (t={fall[c0]/SR:.4f}-{fall[c1]/SR:.4f}s) ===")
    for a in range(c0, c1, 100):
        b = min(a + 100, c1)
        f = "".join(str(x) for x in fallv[a:b])
        r = "".join(str(x) for x in risev[a:b])
        print(f"cyc {a:6d} F: {f}")
        print(f"           R: {r}")

# link establishment: first slave responses
show(1330, 1430, "first slave contact")
show(1500, 1620, "second exchange")
show(1680, 1760, "third exchange")
show(1860, 1920, "fourth")
show(2030, 2130, "0x39 exchange at 2.79s")
show(2230, 2280, "after 0x39")
# slave 0x27 at burst starts
show(7160, 7200, "slave 0x27 at 6.4314s")
show(9295, 9340, "0x32 poll + slave 0x27ish at 7.95s")
# second phase start and end
show(15735, 15790, "slave 0x27 at 12.52s")
show(18960, 19040, "session end")
