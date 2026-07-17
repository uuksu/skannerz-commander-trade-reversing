"""Search for the payload nibble validation rule.

The receiver validates the 4-bit nibble (bits 12-15) jointly with the
number byte (bits 4-11), the (BCD-encoded) HP byte, and EXP:

    (numByte, hpByte, expByte) -> nibble        accepted?

FULLY CRACKED 2026-07-16 in three passes, each a controlled accept/reject
sweep against a real toy:

Pass 1 (byte term, at HP=63, EXP=9): nibble = (14 - digitSum(numByte))
mod 8, where digitSum(x) = hi_nibble(x) + lo_nibble(x). Confirmed by 9
manual accept tests (nums 42/43/44/12/135/136/15/49/123) with zero
mismatches, plus every earlier accept/reject sample at HP=63. Mod 8, not
mod 4 - the earlier "residue 0 wraps to 1" theory was an artifact of a
too-small dataset (0 is a perfectly valid nibble).

Pass 2 (HP term, at EXP=9): a controlled sweep on one fixed byte
(num 138) across HP=1,2,3,4,10 found
    nibble = (-digitSum(numByte) - 2*digitSum(bcd(HP))) mod 8
6/6 exact, and it subsumes pass 1 exactly (at HP=63, this reduces to the
same residues mod 8).

Pass 3 (EXP term): a sweep on the same fixed byte+HP across
EXP=1,2,3,4,5,6,7,8,9,16 found the "+EXP" pattern holds for EXP=1..7 but
breaks at EXP=8 - UNTIL re-testing showed some nibbles have a confirmed
"twin" 8 apart (EXP=3 accepts both 8 and 0; EXP=4 accepts both 9 and 1).
That means the toy only checks the low 3 bits of the nibble field - the
top bit is a don't-care - and the full pattern is
    expTerm = (EXP % 8) - (EXP // 8)
A second sweep on a different byte (num 135, EXP=1..4) confirmed EXP's
contribution is separable (same shift regardless of which monster/HP is
being sent).

FULL FORMULA (fits every sample ever gathered in this project, including
the two original trade.csv captures and four HARVEST_MODE dumps that
motivated passes 2 and 3 in the first place - see full_rule() below):

    digitSum(x) = hi_nibble(x) + lo_nibble(x)
    expTerm     = (EXP % 8) - (EXP // 8)
    nibble = (-digitSum(numByte) - 2*digitSum(bcd(HP)) + expTerm) mod 8

expTerm(9) == 0, which is why every number/HP experiment in this project
"just worked" while EXP sat at the emulator's default of 9 - EXP's
contribution was silently cancelling out the entire time.

BONUS FIND 2026-07-17: the nibble isn't *just* a checksum - the FULL
4-bit wire field is also the "Level" the toy displays after a trade:

    level = (nibble >> 2) + 1        # nibble is the full 4-bit value, 0..15

Proven in two rounds against a real toy, both at fixed NUM=138 (byte
0x89), HP=63. Round 1: every one of the 8 checksum-valid residues (0-7,
top bit 0) was hit by some EXP value (21->0, 4->1, 5->2, 16->3, 7->4,
9/64/128(truncates to 0)->5, 1->6, 112->7); observed level matched
(nibble>>2)+1 in all 8 cases - but since the checksum only checks
`nibble mod 8` (the top bit is a don't-care for acceptance - a real toy
accepts both n and n+8), this round only ever exercised levels 1-2.
Round 2 forced the top bit set on 4 of the same EXP values (nibble ->
nibble+8, still accepted) and got levels 3-4, 4/4 exact - see
LEVEL_TESTS/level_from_nibble() below. Net picture: NUM+HP+EXP fix bit 2
of the nibble via the checksum (not freely choosable), but the top bit
is free, so for one monster you can reach exactly two levels (L, L+2) by
choosing which checksum-valid nibble to send; the other pair needs
different NUM/HP/EXP. All four levels (1-4) are reachable this way. This
still refutes the manual's "one level per 30 EXP" as the literal
mechanism - level isn't a function of EXP alone here.

REAL EXPERIENCE COUNTER, FULLY CRACKED 2026-07-18: the 12 "zeros" bits
are not padding - they're the toy's persistent, real experience counter,
3-digit BCD, displayed as 10x the decoded value. Every capture and test
before this session had them at 0 not because they're unused, but
because BCD 0 reads as 0 regardless. Discovered when a nonzero zeros
value, sent with the old (zeros-less) checksum, immediately ERRORed -
proving the receiver DOES look at these bits. Two real-toy tests then
nailed both the checksum term and the display transform at once:
zeros=BCD"030" (wire 0x030) needed nibble 2 (predicted from a
digitSum3-style checksum term, confirmed) and displayed EXP 300;
zeros=BCD"003" (wire 0x003) needed the same nibble (same digit sum) and
displayed EXP 30 - exactly 10x the decoded value both times. Sending
zeros as plain binary instead of BCD (e.g. 30 as 0b000000011110, hex
nibbles 0/1/14 - 14 isn't a valid decimal digit) doesn't error, it
produces garbage (observed: displayed EXP 1140) - this field isn't
BCD-validated the strict way HP is, only its checksum digit-sum is
checked. Full checksum formula, extending the one above:

    digitSum3(x) = 3 hex-nibble digit sum of a 12-bit value
    nibble = (-digitSum(numByte) - 2*digitSum(bcd(HP)) - digitSum3(zeros)
              + expTerm) mod 8

REFINED 2026-07-19: the real experience counter isn't zeros ALONE - it
SPANS zeros and the 7-bit EXP field, additively:

    displayedEXP = 10 * decodeBcd3(zeros) + (EXP // 8)

`EXP // 8` (0..15) was originally found as the small EXP field's own,
seemingly-separate "capped at 15" display stat (14/14 exact when zeros
was always 0) - it's actually the ONES digit of the real counter, with
zeros providing the tens-and-up. Confirmed additive by zeros=BCD"003"
with EXP=2 (EXP//8=0) still displaying exactly 30, not 32 - and the
single formula above fits all 4 known data points (including the
original zeros=0/EXP=64->8 result) with zero free parameters. Because
EXP//8 ranges 0..15 (not just 0..9), ANY exact integer 0..9999 is
reachable with no rounding: split target = 10*Z + R (Z -> zeros as
3-digit BCD, R -> EXP's top 4 bits, EXP = (R<<3)|low3), and low3 (0..7)
stays fully free for the checksum regardless of R (see
slave_emulator.ino's solveLevelExp()).
"""
from itertools import combinations, product

# fmt: off
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
    dict(b=0x89, hp=0x63, exp=0x01, n=6),   # manual EXP sweep: num 138, HP=63
    dict(b=0x89, hp=0x63, exp=0x02, n=7),
    dict(b=0x89, hp=0x63, exp=0x03, n=0),   # observed as 8; also confirmed as its twin 0 (8 mod 8)
    dict(b=0x89, hp=0x63, exp=0x04, n=1),   # observed as 9; also confirmed as its twin 1 (9 mod 8)
    dict(b=0x89, hp=0x63, exp=0x05, n=2),
    dict(b=0x89, hp=0x63, exp=0x06, n=3),
    dict(b=0x89, hp=0x63, exp=0x07, n=4),
    dict(b=0x89, hp=0x63, exp=0x08, n=4),
    dict(b=0x89, hp=0x63, exp=0x10, n=3),   # EXP=16
    dict(b=0x86, hp=0x63, exp=0x01, n=1),   # manual EXP sweep, 2nd baseline: num 135
    dict(b=0x86, hp=0x63, exp=0x02, n=2),
    dict(b=0x86, hp=0x63, exp=0x03, n=3),
    dict(b=0x86, hp=0x63, exp=0x04, n=4),
    dict(b=0x01, hp=0x03, exp=0x00, n=1),   # capture: Night Lurk
    dict(b=0x11, hp=0x01, exp=0x06, n=2),   # capture: Diamond Back
    dict(b=0x0A, hp=0x01, exp=0x05, n=1),   # harvest: monster "11"
    dict(b=0x0E, hp=0x01, exp=0x02, n=2),   # harvest: monster "15"
    dict(b=0x12, hp=0x01, exp=0x07, n=2),   # harvest: monster "19"
    dict(b=0x87, hp=0x02, exp=0x06, n=3),   # harvest: monster "136"
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
    dict(b=0x89, hp=0x63, exp=0x01, n=5),   # num 138 EXP=1, byte+HP-only auto (failed)
    dict(b=0x89, hp=0x63, exp=0x02, n=5),   # num 138 EXP=2, byte+HP-only auto (failed)
    dict(b=0x89, hp=0x63, exp=0x05, n=5),   # num 138 EXP=5, byte+HP-only auto (failed)
    dict(b=0x89, hp=0x63, exp=0x06, n=5),   # num 138 EXP=6, byte+HP-only auto (failed)
    dict(b=0x89, hp=0x63, exp=0x07, n=5),   # num 138 EXP=7, byte+HP-only auto (failed)
    dict(b=0x89, hp=0x63, exp=0x08, n=5),   # num 138 EXP=8, byte+HP-only auto (failed)
]
# fmt: on


def wrapped_rule(b):
    """Superseded mod-4 model, kept for the search/regression comparison."""
    r = ((b >> 4) - (b & 15) + 2) % 4
    return r if r else 1


def digit_sum(x):
    return (x >> 4) + (x & 0x0F)


def mod8_rule(b):
    """Byte-only model (valid at HP=63, EXP=9). Confirmed 2026-07-16."""
    return (14 - digit_sum(b)) & 7


def byte_hp_rule(b, hp_bcd):
    """Byte+HP model (valid at EXP=9). Confirmed 2026-07-16."""
    return (-digit_sum(b) - 2 * digit_sum(hp_bcd)) & 7


def digit_sum3(x):
    """3 hex-nibble digit sum of a 12-bit value (the zeros field)."""
    return ((x >> 8) & 0xF) + ((x >> 4) & 0xF) + (x & 0xF)


def full_rule(b, hp_bcd, exp, zeros=0):
    """Complete model: byte + HP + zeros + EXP. Checksum fully cracked
    2026-07-16 (byte/HP/EXP terms) and 2026-07-18 (zeros term).
    hp_bcd is the wire byte (BCD-encoded); exp is the raw 7-bit EXP
    value; zeros is the 12-bit real-experience BCD field (default 0,
    matching every sample gathered before 2026-07-18 - see module
    docstring). Fits every sample ever gathered in this project."""
    exp_term = (exp % 8) - (exp // 8)
    return (-digit_sum(b) - 2 * digit_sum(hp_bcd) - digit_sum3(zeros) + exp_term) & 7


def real_exp_display(zeros, exp=0):
    """The toy's actual persistent experience readout. Cracked
    2026-07-18 (zeros term) and refined 2026-07-19 (additive exp term):
    zeros is 3-digit BCD (tens-and-up, x10); exp//8 is the ones digit.
    Fits all 4 known real-toy points with zero free parameters, incl.
    the original zeros=0/exp=64->8 result from the pre-zeros era."""
    decoded = ((zeros >> 8) & 0xF) * 100 + ((zeros >> 4) & 0xF) * 10 + (zeros & 0xF)
    return decoded * 10 + exp // 8


def level_from_nibble(nibble):
    """Displayed "Level" after a trade. Cracked 2026-07-17: the full
    4-bit wire nibble (0..15), not just the 3 bits the checksum checks -
    confirmed for all 8 checksum-valid residues (levels 1-2) AND their
    top-bit-set twins (levels 3-4), 12/12 real-toy readings exact."""
    return (nibble >> 2) + 1


def exp_display(exp):
    """Displayed "EXP" stat (separate from Level). Cracked 2026-07-17:
    floor(EXP/8) - confirmed at EXP=9/16/21/64/112/128(truncates to 0)."""
    return exp // 8


# fmt: off
LEVEL_TESTS = [  # fixed b=0x89 (num 138), hp=0x63; real-toy readings, 2026-07-17
    dict(exp=21,  nibble=0, level=1),
    dict(exp=4,   nibble=1, level=1),
    dict(exp=5,   nibble=2, level=1),
    dict(exp=16,  nibble=3, level=1),
    dict(exp=7,   nibble=4, level=2),
    dict(exp=9,   nibble=5, level=2),
    dict(exp=64,  nibble=5, level=2),
    dict(exp=0,   nibble=5, level=2),  # sent 128; truncates to 0 on the 7-bit wire field
    dict(exp=1,   nibble=6, level=2),
    dict(exp=112, nibble=7, level=2),
    # round 2: same EXP baselines, MONSTER_NIBBLE forced to (auto value)+8
    # (top bit set - still accepted, since the checksum ignores it)
    dict(exp=21, nibble=8,  level=3),
    dict(exp=16, nibble=11, level=3),
    dict(exp=7,  nibble=12, level=4),
    dict(exp=1,  nibble=14, level=4),
]
EXP_DISPLAY_TESTS = [  # real-toy readings, 2026-07-17
    dict(exp=9, shown=1), dict(exp=16, shown=2), dict(exp=21, shown=2),
    dict(exp=64, shown=8), dict(exp=112, shown=14), dict(exp=0, shown=0),
]
ZEROS_TESTS = [  # fixed b=0x89 (num 138), hp=0x63; real-toy, 2026-07-18/19
    # plain-binary zeros=30 (invalid BCD, nibbles 0/1/14) with the OLD
    # zeros-less checksum (nibble=5) -> ERROR; not included here since
    # it's a negative/garbage result, not a clean (zeros,nibble) pair.
    dict(zeros=0x030, exp=0, nibble=2, shown=300),  # BCD "030"
    dict(zeros=0x003, exp=0, nibble=2, shown=30),   # BCD "003" - same digit sum as above
    dict(zeros=0x003, exp=2, nibble=4, shown=30),   # exp=2 (exp//8=0) - confirms additive,
                                                     # not "zeros overrides exp" - still 30, not 32
    # 4th confirming point: the ORIGINAL zeros=0/exp=64->8 result (pre-dates
    # zeros discovery, see EXP_DISPLAY_TESTS) also fits the combined formula.
]
# fmt: on


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
    print(f"{len(hits)} linear candidate rules fit all data (naive 1-2 feature search)")
    for m, combo, coefs, k, target in hits[:40]:
        terms = " + ".join(f"{c}*{n}" for n, c in zip(combo, coefs))
        print(f"  {target} == ({terms} + {k}) mod {m}")

    hp63exp9_pos = [s for s in POS if s["hp"] == 0x63 and s["exp"] == 0x09]
    hp63exp9_neg = [s for s in NEG if s["hp"] == 0x63 and s["exp"] == 0x09]
    ok8 = all(mod8_rule(s["b"]) == s["n"] for s in hp63exp9_pos) and all(
        mod8_rule(s["b"]) != s["n"] for s in hp63exp9_neg)
    print(f"\nbyte-only rule, HP=63/EXP=9 subset: {'fits' if ok8 else 'REFUTED'}")

    exp9_pos = [s for s in POS if s["exp"] == 0x09]
    exp9_neg = [s for s in NEG if s["exp"] == 0x09]
    okhp = all(byte_hp_rule(s["b"], s["hp"]) == s["n"] for s in exp9_pos) and all(
        byte_hp_rule(s["b"], s["hp"]) != s["n"] for s in exp9_neg)
    print(f"byte+HP rule, EXP=9 subset: {'fits' if okhp else 'REFUTED'}")

    okf = all(full_rule(s["b"], s["hp"], s["exp"]) == s["n"] for s in POS) and all(
        full_rule(s["b"], s["hp"], s["exp"]) != s["n"] for s in NEG)
    print(f"FULL rule (byte + HP + EXP), ALL {len(POS)} pos + {len(NEG)} neg: "
          f"{'fits all data' if okf else 'REFUTED'}")

    okl = all(level_from_nibble(t["nibble"]) == t["level"] for t in LEVEL_TESTS)
    print(f"LEVEL rule (nibble>>2)+1, all {len(LEVEL_TESTS)} nibble values (0-15): "
          f"{'fits all data' if okl else 'REFUTED'}")

    oke = all(exp_display(t["exp"]) == t["shown"] for t in EXP_DISPLAY_TESTS)
    print(f"EXP display rule EXP//8, all {len(EXP_DISPLAY_TESTS)} samples: "
          f"{'fits all data' if oke else 'REFUTED'}")

    okz_check = all(
        full_rule(0x89, 0x63, t["exp"], zeros=t["zeros"]) == t["nibble"] for t in ZEROS_TESTS)
    okz_disp = all(real_exp_display(t["zeros"], t["exp"]) == t["shown"] for t in ZEROS_TESTS)
    okz_combined = real_exp_display(0, 64) == 8  # the original pre-zeros-era point still fits
    print(f"ZEROS checksum term -digitSum3(zeros), {len(ZEROS_TESTS)} real-toy nibbles: "
          f"{'fits' if okz_check else 'REFUTED'}")
    print(f"Combined display formula also fits the original zeros=0/exp=64 point: "
          f"{'fits' if okz_combined else 'REFUTED'}")
    print(f"Combined display rule 10*BCD3(zeros)+exp//8 (the REAL experience counter), "
          f"{len(ZEROS_TESTS)} samples: {'fits all data' if okz_disp else 'REFUTED'}")


if __name__ == "__main__":
    main()
