"""Search for the payload nibble validation rule.

The receiver validates the 4-bit nibble (bits 12-15) jointly with the
number byte (bits 4-11) and possibly HP/EXP. Accepted/rejected samples
from the capture and from emulator-vs-real-toy tests (2026-07-16):

    (numByte, hpByte, expByte) -> nibble        accepted?

CRACKED 2026-07-16 in two passes, both against a real toy at
MONSTER_EXP=9 (the emulator's default):

Pass 1 (byte only, at HP=63): nibble = (14 - digitSum(numByte)) mod 8,
where digitSum(x) = hi_nibble(x) + lo_nibble(x). Confirmed by 9 manual
accept tests (nums 42/43/44/12/135/136/15/49/123) with zero mismatches,
plus every earlier accept/reject sample at HP=63. Mod 8, not mod 4 - the
earlier "residue 0 wraps to 1" theory was an artifact of a too-small
dataset (0 is a perfectly valid nibble; the true range is 0..7, an
unused top bit, never 8..15 in any sample).

Pass 2 (HP term): a controlled sweep on one fixed byte (num 138) across
HP=1,2,3,4,10 found exactly two linear models in HP's BCD digits
consistent with HP=1/2/63; the HP=10 test (predicted nibble 1 vs 5 by
the two models) picked the winner:
    nibble = (-digitSum(numByte) - 2*digitSum(bcd(HP))) mod 8
6/6 exact matches on the controlled sweep, and it subsumes pass 1
exactly (at HP=63, digitSum(bcd(63))=9 and -2*9 == +14 - (-14) mod 8,
i.e. the two formulas are congruent mod 8).

CAVEAT: pass 2 was solved entirely at EXP=9. Two real-toy captures with
this formula's byte+HP terms known (Night Lurk EXP=0, Diamond Back
EXP=6, both from the original trade.csv) plus several HARVEST_MODE
captures at nonzero EXP are listed in EXTRA below - most don't fit,
suggesting EXP may be a third checksum input. Untested; keep EXP=9 for
now (see full_rule() below, and EXTRA's mismatches).
"""
from itertools import combinations, product

# fmt: off
# All POS/NEG entries below are at EXP=9 (or EXP untested-but-irrelevant
# per the byte-only EXP=0-vs-127 check on b=0x29) - the formula is only
# validated at this EXP. See EXTRA for other-EXP real-device samples.
POS = [  # accepted trades: nibble is (assumed) correct for these fields
    dict(b=0x04, hp=0x63, exp=0x00, n=2),   # emulator (displays as "15")
    dict(b=0x0B, hp=0x63, exp=0x00, n=3),   # emulator/manual num 12
    dict(b=0x29, hp=0x63, exp=0x00, n=3),   # emulator num 42
    dict(b=0x29, hp=0x63, exp=0x7F, n=3),   # emulator num 42, EXP=127
    dict(b=0x2A, hp=0x63, exp=0x00, n=2),   # emulator/manual num 43
    dict(b=0x29, hp=0x63, exp=0x7F, n=3),   # REAL harvest: re-injected num 42
    dict(b=0x2B, hp=0x63, exp=0x00, n=1),   # manual: num 44
    dict(b=0x86, hp=0x63, exp=0x00, n=0),   # manual: num 135
    dict(b=0x87, hp=0x63, exp=0x00, n=7),   # manual: num 136
    dict(b=0x0E, hp=0x63, exp=0x00, n=0),   # manual: num 15
    dict(b=0x30, hp=0x63, exp=0x00, n=3),   # manual: num 49
    dict(b=0x7A, hp=0x63, exp=0x00, n=5),   # manual: num 123
    dict(b=0x89, hp=0x63, exp=0x09, n=5),   # manual HP sweep: num 138, HP=63
    dict(b=0x89, hp=0x01, exp=0x09, n=5),   # manual HP sweep: num 138, HP=1
    dict(b=0x89, hp=0x02, exp=0x09, n=3),   # manual HP sweep: num 138, HP=2
    dict(b=0x89, hp=0x03, exp=0x09, n=1),   # manual HP sweep: num 138, HP=3
    dict(b=0x89, hp=0x04, exp=0x09, n=7),   # manual HP sweep: num 138, HP=4
    dict(b=0x89, hp=0x10, exp=0x09, n=5),   # manual HP sweep: num 138, HP=10 (BCD)
]
NEG = [  # rejected: the sent nibble must NOT be what the rule demands
    dict(b=0x04, hp=0x63, exp=0x00, n=1),
    dict(b=0x04, hp=0x63, exp=0x00, n=3),
    dict(b=0x2A, hp=0x63, exp=0x00, n=3),
    dict(b=0x39, hp=0x63, exp=0x00, n=1),   # num 58, old mod-4 auto (failed)
    dict(b=0x39, hp=0x63, exp=0x00, n=4),   # num 58, wrap-guess 4
    dict(b=0x61, hp=0x63, exp=0x00, n=3),   # num 98, old mod-4 auto (failed)
    dict(b=0x89, hp=0x02, exp=0x09, n=5),   # num 138 HP=2, byte-only auto (failed)
    dict(b=0x89, hp=0x03, exp=0x09, n=5),   # num 138 HP=3, byte-only auto (failed)
    dict(b=0x89, hp=0x04, exp=0x09, n=5),   # num 138 HP=4, byte-only auto (failed)
]
# fmt: on

# Real-device samples NOT used to fit full_rule (EXP != 9, and/or not an
# accept/reject test - just what the device happened to send). Listed to
# track the open EXP question, not as ground truth for the fit above.
EXTRA = [
    dict(b=0x01, hp=0x03, exp=0x00, n=1),   # capture: Night Lurk
    dict(b=0x11, hp=0x01, exp=0x06, n=2),   # capture: Diamond Back
    dict(b=0x0A, hp=0x01, exp=0x05, n=1),   # harvest: monster "11"
    dict(b=0x0E, hp=0x01, exp=0x02, n=2),   # harvest: monster "15"
    dict(b=0x12, hp=0x01, exp=0x07, n=2),   # harvest: monster "19"
    dict(b=0x87, hp=0x02, exp=0x06, n=3),   # harvest: monster "136"
]


def wrapped_rule(b):
    """Superseded mod-4 model, kept for the search/regression comparison."""
    r = ((b >> 4) - (b & 15) + 2) % 4
    return r if r else 1


def digit_sum(x):
    return (x >> 4) + (x & 0x0F)


def mod8_rule(b):
    """Byte-only model (valid at HP=63). Confirmed 2026-07-16."""
    return (14 - digit_sum(b)) & 7


def full_rule(b, hp_bcd):
    """Current model: nibble = (-digitSum(b) - 2*digitSum(hpBcd)) mod 8.
    hp_bcd is the wire byte (BCD-encoded), matching this dataset's `hp`
    field and checksumFor()'s second argument in slave_emulator.ino.
    Confirmed 2026-07-16 at EXP=9; see module docstring for the EXP caveat."""
    return (-digit_sum(b) - 2 * digit_sum(hp_bcd)) & 7


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
    print(f"byte-only mod-8 rule, HP=63 subset: "
          f"{'fits' if ok8 else 'REFUTED'}")

    okf = all(full_rule(s["b"], s["hp"]) == s["n"] for s in POS) and all(
        full_rule(s["b"], s["hp"]) != s["n"] for s in NEG)
    print(f"full rule (nibble = (-digitSum(b) - 2*digitSum(hp)) mod 8), "
          f"ALL {len(POS)} pos + {len(NEG)} neg (every HP tested): "
          f"{'fits all data' if okf else 'REFUTED'}")

    print(f"\nEXTRA (EXP != 9, not accept/reject-tested - informational only):")
    for s in EXTRA:
        got = full_rule(s["b"], s["hp"])
        status = "match" if got == s["n"] else f"MISMATCH (got {got})"
        print(f"  b=0x{s['b']:02X} hp=0x{s['hp']:02X} exp={s['exp']} "
              f"n={s['n']}  {status}")


if __name__ == "__main__":
    main()
