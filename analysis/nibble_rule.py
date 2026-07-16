"""Search for the payload nibble validation rule.

The receiver validates the 4-bit nibble (bits 12-15) jointly with the
number byte (bits 4-11) and possibly HP/EXP. Accepted/rejected samples
from the capture and from emulator-vs-real-toy tests (2026-07-16):

    (numByte, hpByte, expByte) -> nibble        accepted?

CRACKED 2026-07-16: at HP=63 (the emulator's default), the checksum is
    nibble = (14 - hi_nibble(numByte) - lo_nibble(numByte)) mod 8
i.e. mod 8, not mod 4 - the earlier "residue 0 wraps to 1" theory was an
artifact of a too-small dataset (0 is a perfectly valid nibble; the true
range is 0..7, an unused top bit, never 8..15 in any sample so far).
Confirmed against 9 fresh manual accept tests (nums 42/43/44/12/135/136/
15/49/123) with zero mismatches, plus every prior accept/reject sample
below at HP=63. The two real-toy captures at HP=1..3 (Night Lurk,
Diamond Back) do NOT fit this formula - HP may also feed the checksum;
untested, out of scope while HP stays pinned at 63.
"""
from itertools import combinations, product

# fmt: off
POS = [  # accepted trades: nibble is (assumed) correct for these fields
    dict(b=0x01, hp=0x03, exp=0x00, n=1),   # capture: Night Lurk (HP != 63)
    dict(b=0x11, hp=0x01, exp=0x06, n=2),   # capture: Diamond Back (HP != 63)
    dict(b=0x04, hp=0x63, exp=0x00, n=2),   # emulator (displays as "15")
    dict(b=0x0B, hp=0x63, exp=0x00, n=3),   # emulator/manual num 12
    dict(b=0x29, hp=0x63, exp=0x00, n=3),   # emulator num 42
    dict(b=0x29, hp=0x63, exp=0x7F, n=3),   # emulator num 42, EXP=127
    dict(b=0x2A, hp=0x63, exp=0x00, n=2),   # emulator/manual num 43
    dict(b=0x0A, hp=0x01, exp=0x05, n=1),   # REAL harvest: monster "11" (HP=1)
    dict(b=0x29, hp=0x63, exp=0x7F, n=3),   # REAL harvest: re-injected num 42
    dict(b=0x2B, hp=0x63, exp=0x00, n=1),   # manual: num 44
    dict(b=0x86, hp=0x63, exp=0x00, n=0),   # manual: num 135
    dict(b=0x87, hp=0x63, exp=0x00, n=7),   # manual: num 136
    dict(b=0x0E, hp=0x63, exp=0x00, n=0),   # manual: num 15
    dict(b=0x30, hp=0x63, exp=0x00, n=3),   # manual: num 49
    dict(b=0x7A, hp=0x63, exp=0x00, n=5),   # manual: num 123
]
NEG = [  # rejected: the sent nibble must NOT be what the rule demands
    dict(b=0x04, hp=0x63, exp=0x00, n=1),
    dict(b=0x04, hp=0x63, exp=0x00, n=3),
    dict(b=0x2A, hp=0x63, exp=0x00, n=3),
    dict(b=0x39, hp=0x63, exp=0x00, n=1),   # num 58, old mod-4 auto (failed)
    dict(b=0x39, hp=0x63, exp=0x00, n=4),   # num 58, wrap-guess 4
    dict(b=0x61, hp=0x63, exp=0x00, n=3),   # num 98, old mod-4 auto (failed)
]
# fmt: on


def wrapped_rule(b):
    """Superseded mod-4 model, kept for the search/regression comparison."""
    r = ((b >> 4) - (b & 15) + 2) % 4
    return r if r else 1


def mod8_rule(b):
    """Current model: nibble = (14 - hi - lo) mod 8. Confirmed 2026-07-16."""
    hi, lo = b >> 4, b & 0x0F
    return (14 - hi - lo) & 7


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

    hp63_pos = [s for s in POS if s["hp"] == 0x63]
    hp63_neg = [s for s in NEG if s["hp"] == 0x63]

    ok = all(wrapped_rule(s["b"]) == s["n"] for s in hp63_pos) and all(
        wrapped_rule(s["b"]) != s["n"] for s in hp63_neg)
    print(f"mod-4 rule (r = (hi-lo+2) mod 4; 0->1), HP=63 subset: "
          f"{'fits' if ok else 'REFUTED'}")

    ok8 = all(mod8_rule(s["b"]) == s["n"] for s in hp63_pos) and all(
        mod8_rule(s["b"]) != s["n"] for s in hp63_neg)
    print(f"mod-8 rule (nibble = (14-hi-lo) mod 8), HP=63 subset: "
          f"{'fits all data' if ok8 else 'REFUTED'}")
    print(f"  prediction for byte 0x39 (num 58): {mod8_rule(0x39)}")
    print(f"  prediction for byte 0x61 (num 98): {mod8_rule(0x61)}")


if __name__ == "__main__":
    main()
