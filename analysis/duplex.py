#!/usr/bin/env python3
"""Split the shared data line into master/slave sub-streams.

Clock cycle n: falling edge f_n, rising edge r_n (f_n < r_n < f_{n+1}).
- Slave drives during clock-LOW half (updates ~7 samples after f_n).
  Sample slave slot late in the low half: r_n - 5.
- Master drives during clock-HIGH half (updates ~1 sample after r_n).
  Sample master slot late in the high half: f_{n+1} - 5.
Also record whether any data edge occurred in each half (who actively drove).
"""
import numpy as np

SR = 200_000
data = np.load("/home/mikko/skannerz-trade-reversing/analysis/capture.npy")
clk = data[:, 1]
dat = data[:, 0]

fall = np.flatnonzero((clk[:-1] == 1) & (clk[1:] == 0)) + 1
rise = np.flatnonzero((clk[:-1] == 0) & (clk[1:] == 1)) + 1
dedge = np.flatnonzero(np.diff(dat)) + 1

# pair each fall with the next rise
ri = np.searchsorted(rise, fall)
ok = ri < len(rise)
fall = fall[ok]
ri = ri[ok]
r_of_f = rise[ri]

# slave slot value: just before the rising edge
slave_bits = dat[r_of_f - 3]
# master slot value: just before the NEXT falling edge
nxt = np.empty(len(fall), dtype=np.int64)
nxt[:-1] = fall[1:]
nxt[-1] = min(r_of_f[-1] + 71, len(dat) - 1)
master_bits = dat[nxt - 3]

# edge activity per half-cycle
lo_edge = np.zeros(len(fall), dtype=bool)   # edge between f_n and r_n
hi_edge = np.zeros(len(fall), dtype=bool)   # edge between r_n and f_{n+1}
li = np.searchsorted(dedge, fall)
for k in range(len(fall)):
    j = li[k]
    while j < len(dedge) and dedge[j] < nxt[k]:
        if dedge[j] < r_of_f[k]:
            lo_edge[k] = True
        else:
            hi_edge[k] = True
        j += 1

np.save("/home/mikko/skannerz-trade-reversing/analysis/master_bits.npy", master_bits)
np.save("/home/mikko/skannerz-trade-reversing/analysis/slave_bits.npy", slave_bits)
np.save("/home/mikko/skannerz-trade-reversing/analysis/fall2.npy", fall)

def show(t0, n, label):
    i0 = np.searchsorted(fall, int(t0 * SR))
    m = "".join(str(x) for x in master_bits[i0:i0 + n])
    s = "".join(str(x) for x in slave_bits[i0:i0 + n])
    me = "".join("M" if x else "." for x in hi_edge[i0:i0 + n])
    se = "".join("S" if x else "." for x in lo_edge[i0:i0 + n])
    print(f"\n=== {label} (t={fall[i0]/SR:.4f}s, cycle {i0}) ===")
    print("master:", m)
    print("m-edge:", me)
    print("slave :", s)
    print("s-edge:", se)

show(1.301, 60, "handshake burst 0")
show(3.029, 40, "poll 32 C6 67")
show(5.385, 130, "dense section")
show(7.735, 150, "msg at 7.7361")
