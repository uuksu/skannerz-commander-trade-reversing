# Reverse-engineering history

Process log for the Skannerz Commander trade-protocol project. The current,
validated state of knowledge lives in `PROTOCOL.md` (wire protocol) and
`IMPLEMENTATION.md` (MCU guide); the reference implementation is
`slave_emulator/slave_emulator.ino`. This document records how the findings
were reached: the milestones, the theories that turned out to be wrong, and
the raw test log.

Milestone dates follow the git history. Some entries in the raw log
(appendix) carry dates one or two days ahead of the corresponding commits;
the log text is preserved as written.

## Milestones

### 2026-07-16 — capture decoded, emulator built, checksum cracked

**Capture decode.** `trade.csv` — a 200 kHz logic capture of a complete
trade between two real toys (device 1: Night Lurk, wire byte 0x01, HP 3,
acting as master; device 2: Diamond Back, wire byte 0x11, HP 1, slave) —
was decoded with the `analysis/` pipeline. The clock/burst structure, the
shared-data-wire slot scheme, all frame formats, the byte vocabulary, the
session flow and the 52-bit payload layout come from this capture. A
brute-force search for a checksum over the payload *tail*
(`analysis/checksum.py`) found nothing — correctly, as it turned out: the
tail is data (the experience counter), and the real checksum is the 4-bit
nibble next to the number byte.

**Slave emulator.** The Arduino sketch completed real trades against a real
toy the same day, turning the project from passive decoding into controlled
accept/reject experiments — every finding below comes from such
experiments.

**The 4-bit nibble is a checksum, cracked in three passes**
(datasets and verifier: `analysis/nibble_rule.py`):

1. **Number-byte term** (at HP=63, EXP=9): 9 accepted numbers (42, 43, 44,
   12, 135, 136, 15, 49, 123) plus earlier rejections gave
   `nibble = (14 − digitSum(byte)) mod 8`, where
   `digitSum(x) = hi_nibble + lo_nibble`. Mod 8, not mod 4 — an earlier
   mod-4 rule with a "residue 0 wraps to 1" special case had fit a smaller
   dataset by accident.
2. **HP term** (at EXP=9): a controlled sweep on one fixed number (138)
   across HP = 1, 2, 3, 4, 10 gave
   `nibble = (−digitSum(byte) − 2·digitSum(bcd(HP))) mod 8`, 6/6 exact —
   HP=10 decided between the only two linear-in-HP-digit models the earlier
   points had left standing.
3. **EXP term**: a sweep on the same fixed number+HP across EXP = 1..9, 16.
   A naive "+EXP" pattern held for EXP 1–7 and appeared to break at 8 —
   until retesting found some values have a confirmed **twin 8 apart**
   (EXP=3 accepts both nibble 8 and 0; EXP=4 accepts both 9 and 1). That
   revealed the toy checks **only the low 3 bits** of the nibble field, and
   the term is `expTerm = (EXP mod 8) − (EXP div 8)`. A second sweep on a
   different number (135) confirmed the term is separable — the same shift
   regardless of which number/HP is sent.

`expTerm(9) == 0`, which is exactly why every number and HP experiment
"just worked" while EXP sat at the emulator's then-default of 9 — the EXP
contribution was silently cancelling out the whole time. (The zeros term,
found later, has the same silently-zero property; see below.)

**HP encoding.** HP goes on the wire as BCD: 0x63 accepted and displayed
as 63; 0x3E (invalid low nibble) → ERROR; and BCD 0x99 accepted once the
HP-aware checksum was used. An earlier "BCD 99 → ERROR" result predated
knowing HP feeds the checksum — the rejection was a checksum mismatch
misread as a range check.

**Theories killed this day:**

- *The nibble is a fixed per-monster tag* (species/tribe/category) — it is
  derived fresh from NUM/HP/EXP (and later zeros) every time.
- *Checksum is mod 4 with "residue 0 wraps to 1"* — overfit to too little
  data; 0 is a plain valid check value, the rule is mod 8.
- *Monster numbers above ~42 are range-rejected* (58, 98 failed) — those
  were checksum mismatches; byte 0x89 (137, inside the presumed
  secret-monster range) was later accepted and used as the fixed baseline
  for all subsequent sweeps.
- *HP is capped below 99* — same checksum-mismatch trap.

### 2026-07-17 — Level and the small EXP field's readout

An EXP display retest with the fixed auto-checksum (NUM=138, HP=63) read
both the "EXP" stat and "Level" from the toy's monster menu after
accepting: EXP 9→1, 16→2, 21→2, 64→8, 112→14, 128→0 (truncates to 0 on
the 7-bit wire field). Displayed EXP = `EXP // 8`, 6/6 exact. At the time
this was taken to be the small field's *own* display stat, capped at 15 —
later revealed to be only half the story (see the next milestone).

Level, however, did not track `EXP/30 + 1` as the toy's manual implies —
it was not even monotonic in EXP. It traced to the checksum nibble
instead: `level = (nibble >> 2) + 1`. Filling in the untested residues
gave full 0–7 coverage, 8/8 exact — and a **wrong first conclusion**:
"level caps at 2." That pass had only exercised the 3 bits the checksum
validates. Since the top bit is a don't-care for *acceptance*, forcing it
set (nibble → nibble+8, still accepted) on 4 of the same baselines gave
levels 3–4, 4/4 exact — 12/12 nibble values total, levels 1–4 on the
wire. Per the user's domain knowledge the real in-game ceiling is level
3, so nibble 12–15 (level 4) was classified as a wire-reachable but
out-of-spec glitch region, and the sketch refuses to build it.

Lesson: "only N bits are checked" (acceptance) ≠ "only N bits matter"
(display) — the checksum ignoring a bit doesn't mean the rest of the
receiver does.

### 2026-07-17 — the "zeros" field is the real experience counter

(Commits dated 07-17; the raw log entries for this work are dated
07-18/19.)

The user pushed back on the "EXP display caps at 15" finding: the real,
persistent experience counter can exceed 15 (e.g. 30), so a 15-ceiling
had to mean the field was misidentified. The sequence that found the
actual counter:

1. `MONSTER_ZEROS=30` (plain binary) with the old zeros-less checksum →
   **ERROR**. Proof that the receiver reads the 12 "zeros" bits — they are
   not padding.
2. Hypothesis: zeros feeds the checksum like NUM does, via
   `−digitSum3(zeros)` (digit sum of its 3 hex nibbles). This fit the
   single ERROR data point and predicted nibble 6 for zeros=30.
3. `MONSTER_ZEROS=30`, forced nibble 6 → **accepted**. Monster menu:
   Level 2, EXP **1140**. Checksum hypothesis confirmed, display value
   inexplicable as any plain-binary transform of 30.
4. Explanation: 30 in binary is `0b000000011110` = hex nibbles 0/1/14, and
   14 is not a decimal digit — the field is BCD like HP, but *not*
   BCD-validated: invalid BCD decodes as garbage instead of erroring.
5. `MONSTER_ZEROS=0x030` (BCD "030"), predicted nibble 2 → accepted,
   EXP **300** = 10 × 30.
6. `MONSTER_ZEROS=0x003` (BCD "003", same digit sum, same predicted
   nibble) → accepted, EXP **30** = 10 × 3.

Conclusion at this point: real experience = 3-digit BCD in the zeros
field, × 10; checksum gains the `−digitSum3(zeros)` term (3/3 predictions
confirmed ahead of testing).

### 2026-07-17 — the counter spans both fields, additively

Second user pushback: the sketch should not need to round the target
experience to a multiple of 10 — the real value should be settable
exactly. Re-examination caught an overlooked detail: the last zeros test
had used smallExp=2 (chosen automatically for the checksum) and *still*
displayed exactly 30, not 32. Checking all 4 known real-toy points against

```
displayedEXP = 10 × decodeBcd3(zeros) + (EXP // 8)
```

| zeros | EXP | displayed |
|-------|-----|-----------|
| 0 | 64 | 8 (pre-dates the zeros discovery) |
| BCD "030" | 0 | 300 |
| BCD "003" | 0 | 30 |
| BCD "003" | 2 | 30 |

— all fit exactly, zero free parameters. So `EXP // 8`, originally found
as a separate capped-at-15 stat, is the **ones digit** of the real
counter, additive with the zeros field's tens-and-up. Because `EXP // 8`
ranges 0–15, any exact integer 0–9999 is reachable with no rounding, and
EXP's low 3 bits stay free for the checksum. Verified end-to-end:
TARGET_LEVEL=3, TARGET_EXP=95 → accepted, monster menu shows EXP 95
exactly.

**Interface evolution.** The sketch's stat-based interface went through
three wrong designs before landing:

1. `TARGET_EXP_DISPLAY` (0..15) — conflated the raw counter with its
   lossy on-screen readout.
2. `TARGET_EXP` as the raw 7-bit field value (0..127) — the wrong field
   entirely.
3. `TARGET_EXP` as the zeros-only real value, rounded to multiples of
   10 — the additive ones digit sitting in the EXP field was being wasted.

Final: `TARGET_EXP` (0..9999, exact) + `TARGET_LEVEL` (1..3) →
`solveLevelExp()`.

Lesson: when the user says "I should be able to set X to the exact value
I see on the device," don't stop at the first formula that fits the data
— even a clean 14/14 fit may be only the part of the mechanism that got
exercised so far.

## Superseded theories at a glance

| Theory | Fate |
|--------|------|
| Nibble is a fixed per-monster tag (species/tribe/category) | Dead — checksum derived fresh from NUM/HP/zeros/EXP; also encodes Level |
| Checksum is mod 4, "residue 0 wraps to 1" | Dead — mod-8 digit-sum rule; overfit artifact |
| Numbers 43/58/98 rejected by a range check | Dead — checksum mismatches; 0x89 accepted |
| HP capped below 99 ("BCD 99 → ERROR") | Dead — checksum mismatch; 0x99 accepted |
| Payload tail contains a CRC/checksum | Dead — the tail is the experience counter; the checksum is the nibble |
| Small EXP field is its own stat, capped at 15 | Dead — it's the ones digit of the real counter |
| Level caps at 2 | Dead — only the checksum-checked bits had been tested; levels 1–4 on the wire |
| Level = EXP/30 + 1 (per the manual) | Dead — level = (nibble >> 2) + 1 |
| The 12 "zeros" bits are padding | Dead — 3-digit BCD, tens-and-up of the experience counter |

## Recurring traps

- **Silently cancelling terms.** Two checksum terms are zero at the values
  every earlier experiment happened to use (`expTerm(9) == 0`,
  `digitSum3(0) == 0`), so the terms were invisible until those inputs
  were deliberately varied.
- **Checksum mismatch masquerading as a range check.** Both the NUM range
  and the HP ceiling were "discovered" and later retracted this way.
- **Checked bits vs. meaningful bits.** The receiver validating only 3 of
  the nibble's 4 bits does not mean the 4th bit is unused.
- **Stale re-send after an aborted trade.** The toy re-sends the same
  monster in the next session after a silent abort — cancel on the toy (or
  back fully out of its trade menu) between experiments, or results get
  attributed to the wrong payload.

## Appendix: raw test log

Formerly `findings.txt`; preserved as written (dates included, see the
note at the top of this document).

```text
I tested couple of the monster numbers, some work, some do not.

Working:
42 nibble 3
43, nibble 2
44, nibble 1
12, nibble 3
135, nibble 0
136, nibble 7
15, nibble 0
49, nibble 3
123, nibble 5

Not working:
98, nibble auto
58, nibble auto

When erroring I see bunch of this:

?? master sent 0x2 (event frame)
?? master sent 0xFF
?? master sent 0xE1 (event frame)

Here is sample of monsters I sent to trade:

11 1/1 HP, EXP 0

<< rx payload: 0 111 00001010 0001 00000001 00000001 000000000000 0000101 1
<< numByte=10 (num 11) nibble=1 HP=0x1/0x1 (BCD 1) zeros=0x0 EXPraw=5
<< nibble checksum: rule says 1 - MATCH

18 1/1 HP, EXP 0

<< rx payload: 0 111 00010001 0010 00000001 00000001 000000000000 0000110 1
<< numByte=17 (num 18) nibble=2 HP=0x1/0x1 (BCD 1) zeros=0x0 EXPraw=6
<< nibble checksum: rule says 2 - MATCH

19 1/1 HP, EXP 0

<< rx payload: 0 111 00010010 0010 00000001 00000001 000000000000 0000111 1
<< numByte=18 (num 19) nibble=2 HP=0x1/0x1 (BCD 1) zeros=0x0 EXPraw=7
<< nibble checksum: rule says 1 - MISMATCH!

15 1/1 HP, EXP 0

<< rx payload: 0 111 00001110 0010 00000001 00000001 000000000000 0000010 1
<< numByte=14 (num 15) nibble=2 HP=0x1/0x1 (BCD 1) zeros=0x0 EXPraw=2
<< nibble checksum: rule says 1 - MISMATCH!

136 2/2 HP, EXP 0
<< rx payload: 0 111 10000111 0011 00000010 00000010 000000000000 0000110 1
<< numByte=135 (num 136) nibble=3 HP=0x2/0x2 (BCD 2) zeros=0x0 EXPraw=6
<< nibble checksum: rule says 3 - MATCH

EXP tests:

9 = EXP 1
16 = ERROR
21 = ERROR
64 = EXP 8
112 = ERROR
128 = EXP 0

HP 3, rejected, correct value 1
HP 4, rejected, correct value 7
HP 10, accepted, correct value 5

EXP 1, rejected, correct value 6
EXP 2, rejected, correct value 7
EXP 3, rejected, correct value 8 (tälle kelpasi toinenkin? kelpaako muille?)
EXP 4, rejected, correct value 9
EXP 16, rejected, correct value 3

2026-07-17, EXP display re-test with the fixed auto-checksum (NUM=138,
HP=63 fixed), reading both the "EXP" stat and "Level" after accepting:

9,   Level 2, EXP 1
16,  Level 1, EXP 2
21,  Level 1, EXP 2
64,  Level 2, EXP 8
112, Level 2, EXP 14
128, Level 2, EXP 0     (truncates to raw 0 on the 7-bit wire field)

EXP display = EXP // 8, all 6 exact, no offset. But Level does NOT track
EXP/30+1 like the manual claims - it's not even monotonic in EXP. Traced
it to the checksum nibble instead: level = (nibble>>2)+1. Filled in the
remaining untested nibble residues (1, 2, 4, 6) to get full 0-7 coverage:

4, Level 1, EXP 0   (nibble 1)
5, Level 1, EXP 0   (nibble 2)
7, Level 2, EXP 0   (nibble 4)
1, Level 2, EXP 0   (nibble 6)

8/8 nibble residues (0-7, all with top bit 0) confirmed against
(nibble>>2)+1, zero mismatches. First conclusion: level capped at 1-2.
WRONG - that only tested the 3 bits the checksum validates, never the
"don't care" top bit. Forced MONSTER_NIBBLE to (residue)+8 - top bit
set, low 3 bits unchanged, so still checksum-valid - on 4 of the same
EXP baselines:

21, Level 3, EXP 2   (nibble forced to 8  = 0+8)
16, Level 3, EXP 2   (nibble forced to 11 = 3+8)
7,  Level 4, EXP 0   (nibble forced to 12 = 4+8)
1,  Level 4, EXP 0   (nibble forced to 14 = 6+8)

4/4 exact, all still accepted. So level = (nibble>>2)+1 over the FULL
4-bit field, levels 1-4, not 1-2. 12/12 nibble values now confirmed.
See analysis/nibble_rule.py LEVEL_TESTS/EXP_DISPLAY_TESTS.

2026-07-18: user pushed back hard on the EXP//8 finding above - real
experience should be settable past 15 (e.g. 30) and shouldn't even be
transferable, so a 15-ceiling must mean we misidentified the field.
Right call. Sequence of real-toy tests that found the actual counter:

1. MONSTER_ZEROS=30 (plain binary), old zeros-less checksum (auto
   nibble=5) -> ERROR. Proves the receiver DOES look at the 12 "zeros"
   bits - they're not padding.

2. Hypothesis: zeros feeds the checksum the same way NUM does,
   nibble -= digitSum3(zeros) (digit sum of its 3 hex nibbles). Fit the
   single ERROR data point exactly (predicted nibble 6 for zeros=30).

3. MONSTER_ZEROS=30, MONSTER_NIBBLE=6 (forced, predicted) -> ACCEPTED.
   Monster menu: Level 2, EXP 1140. Checksum hypothesis confirmed, but
   1140 from 30 doesn't fit any plain-binary transform tried.

4. Explanation: 30 as plain binary = 0b000000011110 = hex nibbles
   0,1,14 - 14 isn't a valid decimal digit. The field is BCD like HP,
   and doesn't reject invalid BCD (no ERROR, just garbage output).

5. MONSTER_ZEROS=48 (0x030, BCD "030"), MONSTER_NIBBLE=2 (predicted via
   the same digitSum3 hypothesis, digitSum3(0x030)=3) -> ACCEPTED.
   Monster menu: Level 1, EXP 300. digitSum3 hypothesis now 2/2. And
   300 = 10 * 30 (the BCD-decoded value) - clean multiplier.

6. MONSTER_ZEROS=3 (0x003, BCD "003", same digit sum as 0x030) with the
   SAME predicted nibble=2 -> ACCEPTED. Monster menu: EXP 30 = 10*3.
   Confirms: real experience = 3-digit BCD in the zeros field, x10.

Formula: zeros = BCD(realEXP/10) (hundreds,tens,ones nibbles), checksum
term -digitSum3(zeros). slave_emulator.ino's TARGET_LEVEL/TARGET_EXP
interface was rewritten around this - TARGET_EXP became 0..9990 meaning
the real value, not the old field's raw 0..127. Set MONSTER_NIBBLE/EXP
to 0 by default in this version, so EXP//8 was always 0 in every test
above.

2026-07-19: user pointed out the sketch shouldn't need to round
TARGET_EXP to a multiple of 10 - real experience should be settable
exactly. Right call, and traced to a detail overlooked above: the LAST
zeros test (level=2, EXP=30 via the new auto interface) used smallExp=2
(not 0, chosen automatically to satisfy the checksum) and STILL showed
exactly 30, not 32. Checked all 4 known real-toy points against
displayedEXP = 10*decodeBcd3(zeros) + (EXP//8):

  zeros=0,        exp=64 -> 8    (10*0 + 64//8 = 8)      [pre-dates zeros]
  zeros=BCD"030",  exp=0 -> 300  (10*30 + 0 = 300)
  zeros=BCD"003",  exp=0 -> 30   (10*3 + 0 = 30)
  zeros=BCD"003",  exp=2 -> 30   (10*3 + 2//8 = 30)

All 4 fit exactly, zero free parameters. So EXP//8 (originally found as
the small field's own "separate, capped at 15" stat) is actually the
ONES digit of the real counter, additive with zeros's tens-and-up - not
a separate stat at all, and not just a checksum knob. Since EXP//8
ranges 0..15 (not just 0..9), ANY exact integer 0..9999 is reachable
with no rounding: target = 10*Z + R, Z (0..999) -> zeros as 3-digit
BCD, R (0..9) -> EXP's top 4 bits (EXP = R<<3 | low3), low3 (0..7)
still fully free for the checksum regardless of R. Verified:
TARGET_LEVEL=3, TARGET_EXP=95 -> zeros=0x9, smallExp=41, nibble=8 ->
ACCEPTED, monster menu shows EXP 95 exactly.
See analysis/nibble_rule.py ZEROS_TESTS/real_exp_display() (now takes
an exp param) and slave_emulator.ino's solveLevelExp().
```
