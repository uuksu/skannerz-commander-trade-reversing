#!/usr/bin/env python3
"""Dump all decoded bytes grouped into messages (idle gap >= 5 bits splits)."""
import numpy as np

SR = 200_000
fall = np.load("/home/mikko/skannerz-trade-reversing/analysis/fall.npy")
bits = np.load("/home/mikko/skannerz-trade-reversing/analysis/bits.npy")

def decode(bits):
    out = []
    i, n = 0, len(bits)
    while i < n:
        if bits[i] == 1:
            i += 1
            continue
        if i + 9 >= n:
            break
        payload = bits[i + 1:i + 9]
        stop = bits[i + 9]
        val = 0
        for b in payload:
            val = (val << 1) | int(b)
        out.append((i, val, bool(stop == 1)))
        i += 10
    return out

res = decode(bits)
msgs = []
cur = []
prev_end = None
for idx, val, ok in res:
    if prev_end is not None and idx - prev_end >= 5:
        msgs.append(cur)
        cur = []
    cur.append((idx, val, ok))
    prev_end = idx + 10
msgs.append(cur)

print(f"{len(res)} bytes in {len(msgs)} messages\n")
for m in msgs:
    t = fall[m[0][0]] / SR
    hexs = " ".join(f"{v:02X}{'' if ok else '!'}" for _, v, ok in m)
    print(f"t={t:8.4f}s  n={len(m):3d}  {hexs}")
