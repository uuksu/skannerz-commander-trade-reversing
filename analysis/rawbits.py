#!/usr/bin/env python3
"""Print raw bit strings for interesting regions to determine framing."""
import numpy as np

SR = 200_000
fall = np.load("/home/mikko/skannerz-trade-reversing/analysis/fall.npy")
bits = np.load("/home/mikko/skannerz-trade-reversing/analysis/bits.npy")

def show(t_start, nbits, label):
    i0 = np.searchsorted(fall, int(t_start * SR))
    seg = bits[i0:i0 + nbits]
    s = "".join(str(x) for x in seg)
    print(f"\n{label} (from t={fall[i0]/SR:.4f}s, bit {i0}):")
    for k in range(0, len(s), 80):
        print(f"  {i0+k:6d}: {s[k:k+80]}")

# clean poll message
show(3.029, 60, "poll message 32 C6 67")
# dense repeating section start
show(5.385, 260, "dense section start (t=5.386)")
# the 9-byte message at 2.7887
show(2.788, 120, "message at 2.7887")
# 13-byte message at 7.7361 (has 02, 06, 00, 03 = maybe monster data!)
show(7.735, 160, "message at 7.7361")
