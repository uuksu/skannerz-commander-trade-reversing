#!/usr/bin/env python3
"""Decode byte stream: idle-high data, start bit 0, 8 data bits, stop bit 1.
Try both bit orders. Report each byte with its bit index and timestamp."""
import numpy as np

SR = 200_000
fall = np.load("/home/mikko/skannerz-trade-reversing/analysis/fall.npy")
bits = np.load("/home/mikko/skannerz-trade-reversing/analysis/bits.npy")

def decode(bits, lsb_first):
    out = []  # (bit_index, byte, stop_ok)
    i = 0
    n = len(bits)
    while i < n:
        if bits[i] == 1:
            i += 1
            continue
        # start bit at i
        if i + 9 >= n:
            break
        payload = bits[i + 1:i + 9]
        stop = bits[i + 9]
        if lsb_first:
            val = sum(b << k for k, b in enumerate(payload))
        else:
            val = 0
            for b in payload:
                val = (val << 1) | int(b)
        out.append((i, val, stop == 1))
        i += 10
    return out

for order in (False, True):
    res = decode(bits, order)
    bad = [r for r in res if not r[2]]
    print(f"{'LSB' if order else 'MSB'}-first: {len(res)} bytes, "
          f"{len(bad)} stop-bit violations")

res = decode(bits, False)
print("\nfirst 60 bytes (MSB-first): idx=bit index, t=seconds")
prev_end = 0
for i, (idx, val, ok) in enumerate(res[:60]):
    gap = idx - prev_end
    t = fall[idx] / SR
    print(f"  [{i:3d}] t={t:8.4f}s bit{idx:6d} gap={gap:5d} "
          f"0x{val:02X} ({val:3d}) stop={'ok' if ok else 'BAD'}")
    prev_end = idx + 10
