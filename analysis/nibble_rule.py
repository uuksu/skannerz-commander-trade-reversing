"""Search for the payload nibble validation rule.

The receiver validates the 4-bit nibble (bits 12-15) jointly with the
number byte (bits 4-11) and possibly HP/EXP. Accepted/rejected samples
from the capture and from emulator-vs-real-toy tests (2026-07-16):

    (numByte, hpByte, expByte) -> nibble        accepted?
"""
from itertools import combinations, product

# fmt: off
POS = [  # accepted trades: nibble is (assumed) correct for these fields
    dict(b=0x01, hp=0x03, exp=0x00, n=1),   # capture: Night Lurk
    dict(b=0x11, hp=0x01, exp=0x06, n=2),   # capture: Diamond Back
    dict(b=0x04, hp=0x63, exp=0x00, n=2),   # emulator (displays as "15")
    dict(b=0x0B, hp=0x63, exp=0x00, n=3),   # emulator num 12
    dict(b=0x29, hp=0x63, exp=0x00, n=3),   # emulator num 42
    dict(b=0x29, hp=0x63, exp=0x7F, n=3),   # emulator num 42, EXP=127
    dict(b=0x2A, hp=0x63, exp=0x00, n=2),   # emulator num 43, auto checksum
    dict(b=0x0A, hp=0x01, exp=0x05, n=1),   # REAL harvest: monster "11"
                                            # -> residue-0 byte, nibble 1!
    dict(b=0x29, hp=0x63, exp=0x7F, n=3),   # REAL harvest: ex-injected num 42
]
NEG = [  # rejected: the sent nibble must NOT be what the rule demands
    dict(b=0x04, hp=0x63, exp=0x00, n=1),
    dict(b=0x04, hp=0x63, exp=0x00, n=3),
    dict(b=0x2A, hp=0x63, exp=0x00, n=3),
    dict(b=0x39, hp=0x63, exp=0x00, n=3),   # num 58
    dict(b=0x39, hp=0x63, exp=0x00, n=4),   # num 58, wrap-guess 4
]
# fmt: on


def wrapped_rule(b):
    """Best current model: mod-4 digit checksum, residue 0 wraps to 1."""
    r = ((b >> 4) - (b & 15) + 2) % 4
    return r if r else 1


def features(s):
    b, hp, exp = s["b"], s["hp"], s["exp"]
    return {
        "b": b, "b+1": b + 1, "b_hi": b >> 4, "b_lo": b & 15,
        "hp": hp, "hp_hi": hp >> 4, "hp_lo": hp & 15,
        "hp_bcd": (hp >> 4) * 10 + (hp & 15),
        "exp": exp, "exp_hi": exp >> 4, "exp_lo": exp & 15,
    }


FEAT_NAMES = list(features(POS[0]).keys())


def val(s, combo, coefs, k):
    f = features(s)
    return sum(c * f[name] for name, c in zip(combo, coefs)) + k


def main():
    hits = []
    for m in range(3, 22):
        for r in (1, 2):  # combos of 1 or 2 features
            for combo in combinations(FEAT_NAMES, r):
                for coefs in product(range(1, m), repeat=r):
                    for k in range(m):
                        for target in ("n", "n-1"):
                            ok = True
                            for s in POS:
                                want = s["n"] if target == "n" else s["n"] - 1
                                if val(s, combo, coefs, k) % m != want % m:
                                    ok = False
                                    break
                            if not ok:
                                continue
                            for s in NEG:
                                want = s["n"] if target == "n" else s["n"] - 1
                                if val(s, combo, coefs, k) % m == want % m:
                                    ok = False
                                    break
                            if ok:
                                hits.append((m, combo, coefs, k, target))
    print(f"{len(hits)} linear candidate rules fit all data")
    for m, combo, coefs, k, target in hits[:40]:
        terms = " + ".join(f"{c}*{n}" for n, c in zip(combo, coefs))
        print(f"  {target} == ({terms} + {k}) mod {m}")

    ok = all(wrapped_rule(s["b"]) == s["n"] for s in POS) and all(
        wrapped_rule(s["b"]) != s["n"] for s in NEG)
    print(f"wrapped rule (r = (hi-lo+2) mod 4; 0->1): "
          f"{'fits all data' if ok else 'REFUTED'}")
    print(f"  prediction for byte 0x39 (num 58): {wrapped_rule(0x39)}")


if __name__ == "__main__":
    main()
