#!/usr/bin/env python3
"""Brute-force the payload trailing byte formula.

Payload body (after 0111 sync), MSB-first fields:
  M: ID-1=0x01 X=0x1 HP=0x3 HP=0x3 zeros  -> tail byte 0x01
  S: ID-1=0x11 X=0x2 HP=0x1 HP=0x1 zeros  -> tail byte 0x0D
Bytes (pos4..51 in 8-bit groups):
  M: 01 10 30 30 00 | 01
  S: 11 20 10 10 00 | 0D
"""
from itertools import product

M_bytes = [0x01, 0x10, 0x30, 0x30, 0x00]
S_bytes = [0x11, 0x20, 0x10, 0x10, 0x00]
M_cs, S_cs = 0x01, 0x0D

def rev8(b):
    return int(f"{b:08b}"[::-1], 2)

def crc8(data, poly, init, refin, refout, xorout):
    crc = init
    for b in data:
        if refin:
            b = rev8(b)
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    if refout:
        crc = rev8(crc)
    return crc ^ xorout

datasets = {
    "bytes": (M_bytes, S_bytes),
    "sync+bytes": ([0x07] + M_bytes, [0x07] + S_bytes),
    "bytes-lsb": ([rev8(b) for b in M_bytes], [rev8(b) for b in S_bytes]),
    "nibbles": ([n for b in M_bytes for n in (b >> 4, b & 0xF)],
                [n for b in S_bytes for n in (b >> 4, b & 0xF)]),
    "values": ([0x01, 0x1, 0x3, 0x3], [0x11, 0x2, 0x1, 0x1]),
}

hits = []
for name, (md, sd) in datasets.items():
    for poly in range(1, 256):
        for init in (0x00, 0xFF):
            for refin, refout, xorout in product((False, True), (False, True),
                                                 (0x00, 0xFF)):
                if (crc8(md, poly, init, refin, refout, xorout) == M_cs and
                        crc8(sd, poly, init, refin, refout, xorout) == S_cs):
                    hits.append(("crc8", name, poly, init, refin, refout, xorout))

print(f"CRC8 hits: {len(hits)}")
for h in hits[:40]:
    print(" ", h)

# CRC over the raw 48-bit body (pos4..51 minus cs? try pos4..43 = 40 bits)
M_bits = "0000000100010000001100000011000000000000"
S_bits = "0001000100100000000100000001000000000000"

def crc8_bits(bits, poly, init, xorout):
    crc = init
    for c in bits:
        fb = ((crc >> 7) & 1) ^ int(c)
        crc = ((crc << 1) & 0xFF)
        if fb:
            crc ^= poly
    return crc ^ xorout

bit_hits = []
for poly in range(1, 256):
    for init in (0x00, 0xFF):
        for xorout in (0x00, 0xFF):
            if (crc8_bits(M_bits, poly, init, xorout) == M_cs and
                    crc8_bits(S_bits, poly, init, xorout) == S_cs):
                bit_hits.append((poly, init, xorout))
print(f"CRC8-over-bits hits: {len(bit_hits)}")
for h in bit_hits[:20]:
    print(" ", h)

# simple arithmetic candidates
def tries(md, sd):
    out = []
    fs = {
        "sum": lambda d: sum(d) & 0xFF,
        "sum&F": lambda d: sum(d) & 0x0F,
        "-sum": lambda d: (-sum(d)) & 0xFF,
        "-sum&F": lambda d: (-sum(d)) & 0x0F,
        "~sum": lambda d: (~sum(d)) & 0xFF,
        "xor": lambda d: __import__("functools").reduce(lambda a, b: a ^ b, d, 0),
        "sum>>4+sum&F": lambda d: ((sum(d) >> 4) + (sum(d) & 0xF)) & 0xFF,
        "fold16": lambda d: ((sum(d) >> 4) + sum(d)) & 0x0F,
    }
    for n, f in fs.items():
        if f(md) == M_cs and f(sd) == S_cs:
            out.append(n)
    return out

for name, (md, sd) in datasets.items():
    r = tries(md, sd)
    if r:
        print("arith hit:", name, r)
