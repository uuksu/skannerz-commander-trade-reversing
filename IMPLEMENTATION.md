# Emulating a Skannerz device with an MCU

Companion to `PROTOCOL.md` (read that first). Goal: replace one of the two
toys with any MCU that can bit-bang two GPIOs, and send an arbitrary monster
(one number byte; 1–138 verified, likely covering the whole 126+12
roster) with arbitrary HP (1–99, no confirmed ceiling below that).

## Hardware

- 3 wires to the toy's link port: CLOCK, DATA, GND.
- Both lines idle high. Drive low actively; for high, prefer releasing the
  line with a pull-up (the real devices share the data line and the safest
  assumption is open-drain-style signalling). A 10–47 kΩ pull-up is plenty at
  1.4 kHz.
- **Logic level: 4.5 V** (three AAA cells). Consequences:
  - A classic **5 V Arduino (Uno/Nano) connects directly** and is the
    recommended board. Its input threshold (~3.0 V) reads the toy's 4.5 V
    highs cleanly, and the emulator never drives the lines high (open-drain
    only), so the toy never sees 5 V. Preferred pull-up: 10–47 kΩ from DATA
    to the toy's own 4.5 V rail; the AVR's internal pull-up (to 5 V) is also
    acceptable — 0.5 V above the toy's rail is below a protection diode's
    forward drop, so it injects effectively no current.
  - **3.3 V boards (ESP32, RP2040, 3.3 V Pro Mini) must NOT be connected
    directly**: the toy drives CLOCK and DATA to 4.5 V, above the absolute
    maximum of non-5V-tolerant inputs. Use a divider on CLOCK and a
    bidirectional level shifter (e.g. BSS138) on DATA — or just use a 5 V
    board.
  - Weak batteries lower the toy's highs (~3.3–3.6 V at end of life), which
    approaches a 5 V AVR's input threshold — use fresh-ish batteries if
    reads get flaky.

### Wiring diagram (5 V Arduino, direct — recommended)

```
     Skannerz link port                        Arduino Uno/Nano (5 V)
    ┌────────────────────┐
    │  PIN 1 ── CLOCK ───┼──────────────────────────►  D2  (PIN_CLK)
    │                    │
    │  PIN 2 ── GND ─────┼──────────────────────────   GND
    │                    │
    │  PIN 3 ── DATA ────┼───────────────┬─────────►◄  D3  (PIN_DATA)
    └────────────────────┘               │
                                        ┌┴┐
                                        │ │  10–47 kΩ
                                        │ │  optional external pull-up
                                        └┬┘
                                         │
                                 toy battery "+" terminal
                                 (4.5 V, in the battery compartment)
```

- The pull-up resistor sits **between the DATA wire and the toy's 4.5 V
  rail** — one lead taps DATA anywhere along that wire, the other goes to
  the battery "+" terminal. Fit it and set `USE_INTERNAL_PULLUP 0`
  (cleanest), or leave it out entirely and keep `USE_INTERNAL_PULLUP 1` —
  then the wiring is just the three link-port wires.
- Pin numbering follows PROTOCOL.md §1 (PIN 2 = the middle/GND contact).
- The shared GND wire (PIN 2) is mandatory — without a common ground
  reference nothing will read correctly.
- D2/D3 are just the sketch defaults (`PIN_CLK` / `PIN_DATA`); any two GPIOs
  work.
- CLOCK is input-only on the Arduino side (the toy always drives it); DATA
  is bidirectional but the sketch only ever pulls it low or releases it.

### Wiring (3.3 V board — only if you must)

```
    CLOCK ──┬── 10 kΩ ──┬──────────►  GPIO (CLK)     divider: 4.5 V → ~3.1 V,
            │           │                            still ≥ ~2.5 V with
            │         22 kΩ                          weak batteries
            │           │
            │          GND
    DATA  ──┤ HV ┌─────────────┐ LV ├──  GPIO (DATA)
            └────┤   BSS138    ├────┘
                 │ level shift │      HV ref = toy 4.5 V rail,
                 └─────────────┘      LV ref = 3.3 V
    GND   ──────────────────────────  GND (common to toy, shifter, MCU)
```

A 5 V board avoids all of this.

## Which side to emulate

**Emulate the slave.** The slave never generates the clock, never sends ack
pulses, and never decides timing — everything is a deterministic reaction to
the master's clock and frames. The real toy happily plays master: it beacons
autonomously.

(A master emulator is also specified at the end for completeness.)

## Slave emulator

A ready-to-use Arduino implementation of everything in this section is in
`slave_emulator/slave_emulator.ino` (set `MONSTER_NUM` / `MONSTER_HP` at
the top — the checksum nibble is computed automatically; open-drain data
handling included — see the electrical note in its header). Its
`HARVEST_MODE` flag logs a real toy's monster payloads over serial and then
holds without ever accepting, so a whole collection can be dumped without
losing anything — **cancel each trade on the toy** rather than just
unplugging: an abandoned session makes the toy re-send the same monster
next round instead of the newly selected one, and the on-toy cancel both
resets that and may put the still-unknown reject byte codes on the wire
(the sketch logs any unexpected master byte).

### Bit primitives

All reads/writes are keyed to the master's clock:

- `read_master_bit()`: wait for CLOCK falling edge, sample DATA.
- `write_slave_bit(b)`: wait for CLOCK falling edge, then ~35 µs later drive
  DATA to `b`. (Anywhere in the first ~40 % of the low half-period works;
  the master samples at the rising edge.)
- After the last bit of a frame, release DATA (input/high).

### Receiving a master frame

```
loop:
    b = read_master_bit()
    if b == 0:                      # start bit
        byte = 0
        repeat 8: byte = byte<<1 | read_master_bit()
        stop = read_master_bit()    # 1 = normal frame, 0 = event frame (0x39)
        skip 2 cycles               # normal tail: low,high; event tail: high,high
        handle(byte, event = (stop == 0))
```

Frame cycles are contiguous: start bit at cycle N → data N+1..N+8, stop slot
N+9, tail N+10..N+11. **Reply start bit goes in cycle N+12 for normal
frames, N+13 for event frames (0x39).**

### Sending a slave frame

Ack (0x34 / 0x2D), starting at cycle N+12 relative to the master frame:

```
write_slave_bit(0)                  # start
for i in 7..0: write_slave_bit(bit i of byte)
write_slave_bit(1)                  # stop
release DATA
```

Event frame (0x27 only): same but instead of the high stop bit send two low
cycles, then release:

```
write_slave_bit(0); 8 data bits; write_slave_bit(0); write_slave_bit(0); release
```

After every completed slave frame the master pulls DATA low for ~2 cycles
(ack pulse), possibly starting during your stop cycle — ignore line state
for 3 cycles after your frame ends.

### Building the payload (52 bits)

For monster number byte `B` (= displayed identity via an unknown mapping;
1..0x89 verified accepted) and `HP` (1–99, BCD-encoded):

```
def digit_sum(x): return (x >> 4) + (x & 0x0F)

hp_bcd   = (HP // 10) * 16 + HP % 10                     # BCD! binary HP -> ERROR
exp_term = (EXP % 8) - (EXP // 8)
check    = (-digit_sum(B) - 2 * digit_sum(hp_bcd) + exp_term) % 8  # checksum over B, hp_bcd, EXP
bits  = '0'                      # start
      + '111'                    # sync
      + f'{B:08b}'               # monster number byte
      + f'{check:04b}'           # checksum nibble - wrong value -> ERROR (only low 3 bits checked)
      + f'{hp_bcd:08b}'          # HP, BCD
      + f'{hp_bcd:08b}'          # HP again (duplicate)
      + f'{ZEROS:012b}'          # unknown; 0 in every capture so far, but the
                                  # leading suspect for the toy's REAL persistent
                                  # experience counter - see the note below
      + f'{EXP:07b}'             # a win-counter-like field, but its own menu
                                  # readout caps at 15 - may not be real EXP
      + '1'                      # stop
```

Receiver-validated (real-toy testing, 2026-07-16): the checksum nibble
must match `check` above (mismatch → ERROR + link abort — this, not a
range check, is what rejected numbers 43/58 before the rule was known),
though only its low 3 bits are actually checked — the toy accepts both
`check` and `check + 8` for the same monster (confirmed by testing both
directly), so the top bit is a don't-care and `check` as computed above
(always 0..7) is always a valid choice. Both HP bytes must be valid BCD
(0x3E → ERROR for the invalid low nibble). **No confirmed HP ceiling
below 99**: BCD 0x99 (99) is accepted with the correct checksum — an
earlier "BCD 99 → ERROR" finding predated knowing HP feeds the checksum
and was a checksum mismatch, not a real range check (same trap the NUM
field's early "range errors" turned out to be; see PROTOCOL.md §3.5/§7).
The toy's UI visibly glitches at HP 99 (in-game balance caps around 63)
but the wire accepts it. **Level is not simply derived from EXP** — it's
the **full 4-bit nibble field**: `level = (nibble >> 2) + 1`, giving
levels 1–4. Proven in two rounds against a real toy (2026-07-17): first,
all 8 checksum-valid residues with the top bit 0 gave levels 1–2 (8/8);
then, since the checksum only validates `nibble mod 8` (top bit is a
don't-care for acceptance — see below), forcing the top bit set on the
same monsters (`nibble` → `nibble+8`, still accepted) gave levels 3–4
(4/4). So NUM/HP/EXP fix bit 2 of the nibble via the checksum (not
freely choosable), but the top bit is free — for any one monster you can
pick between exactly two levels (`L`, `L+2`) by choosing which
checksum-valid nibble to send; the other pair needs different NUM/HP/EXP.
**The real in-game ceiling is level 3** — 4 is a wire-reachable value the
checksum doesn't reject (it only validates 3 of the 4 bits) but real
game data never produces; treat nibble 12–15 as out-of-spec, not a 4th
tier.

Rather than hand-deriving raw wire values for a target level, the sketch
exposes `TARGET_LEVEL` (1..3) and `TARGET_EXP` (0..127) directly.
**CAUTION, reopened 2026-07-17**: `TARGET_EXP`'s own menu readout (only
visible in the toy's monster menu, never during a trade) is proven to be
`rawEXP // 8`, capped at 15 no matter what's sent — but the manual
describes real experience as an accumulating, non-transferable,
battle-won stat that visibly exceeds 15 in normal play. That's a direct
contradiction, so `TARGET_EXP` is **not confirmed** to be the same
counter the monster menu shows for locally-raised monsters; it's
possibly a different, deliberately-capped stat. The likelier home for
the real counter is the previously-untouched 12 "zeros" bits — see
`MONSTER_ZEROS` below, an active, not-yet-hardware-tested probe.
`solveLevelExp()` works out the wire EXP + nibble in `setup()`: it sends
`TARGET_EXP` exactly if that already lands on the checksum band
`TARGET_LEVEL` needs, otherwise it nudges only the low 3 bits (searching
within the same `EXP/8` "tens" bucket, which always contains a match —
proven exhaustively) to the closest value that does, so the sent EXP
never drifts more than a few units from what was asked and refuses
`TARGET_LEVEL=4`. Set `USE_LEVEL_EXP_INTERFACE 0` to fall back to setting
`MONSTER_EXP`/`MONSTER_NIBBLE` by hand for lower-level experiments (e.g.
deliberately probing the level-4 glitch).

`MONSTER_ZEROS` (0..4095) sends an explicit value in the 12 previously-
always-zero bits, for testing whether that's where the real experience
counter lives. To test: set `MONSTER_ZEROS` to something recognizable
(e.g. 30) and `MONSTER_EXP`/`TARGET_EXP` to something clearly different
(e.g. 0), trade, then check the monster menu (not the trade screen).
If it reads "30", the zeros field is the real counter and the 7-bit
`EXP` field is something else; if it still reads whatever `TARGET_EXP`'s
`//8` predicts, the zeros field is inert and the real counter is
elsewhere entirely (not yet identified).

The checksum formula above is fully solved, including the EXP term —
`exp_term(9) == 0` is exactly why every earlier NUM/HP experiment
"just worked" while EXP sat at the emulator's default of 9. The EXP
*display* stat (separate from Level, and separate from the checksum) is
also solved: `EXP // 8`, floor division — proven by a real-toy sweep at
EXP = 9/16/21/64/112/128 (truncates to 0 on the wire), all exact; a
BCD-decode theory was tested and refuted (EXP=16 decodes to BCD 10,
predicting display 1, but the toy showed 2). Field width (7 vs 8 bit) is
still open.

Note HP=0 is untested; the display flow suggests HP ≥ 1. HP=99 is the
ceiling `hp_bcd` above can express without producing a non-BCD byte —
whether the toy enforces anything beyond BCD validity itself is untested.

### Session state machine

```
state WAIT_LINK:
    # master beacons 0x32 in bursts; clock stops ~21 ms between bursts.
    on 0x32 -> reply 0x34; state = LINKED

state LINKED:
    on 0x32 -> reply 0x34                    # 100 ms polling
    on 0x39 -> reply 0x34; state = CONFIRM   # session setup, 1st ask

state CONFIRM:
    on 0x39 -> reply 0x2D; state = IDLE      # 2nd ask -> "Ok!" on both

state IDLE:                                   # user picks monster on the toy
    on 0x32 -> reply 0x34
    on 0x2B -> reply 0x34; state = SELECT    # master user selected

state SELECT:
    # when *your* monster is chosen (immediately, for an emulator):
    on 0x2B -> reply 0x27 (event frame) once; then reply 0x34
    # when ready to exchange (e.g. right after the 0x27):
    on 0x2B -> reply 0x2D; state = XFER

state XFER:
    # master acks your 0x2D (2-cycle low pulse), idles 2 cycles,
    # then sends its 52-bit payload in master slots (sample at falling edges).
    receive 52 master-slot bits -> master's monster
    # your payload starts on the NEXT cycle after its last cycle:
    send 52 slave-slot bits (your payload)
    # master acks; back to 100 ms 0x32 polling
    on 0x32 -> reply 0x27 once (preview state), then 0x34; state = PREVIEW

state PREVIEW:                                # toys show incoming monster
    on 0x32 -> reply 0x34
    on 0x2B -> state = ACCEPT                # master user pressed Accept

state ACCEPT:
    on 0x2B -> reply 0x34 a few times,
               then 0x27 (event frame) once,  # "my user accepted"
               then 0x34,
               then 0x2D                      # trade committed, close
    # master acks and stops the clock. Done.
```

Robustness notes observed from the real master:

- Missed/garbled slave replies are tolerated: the master just re-polls
  (~20 ms later in handshake, next poll period otherwise). If you lose bit
  sync, go silent and wait for the next clean poll.
- The real slave sometimes skipped fast polls while busy; you may too.
- Delays between your state transitions are not enforced by the master —
  the real slave took seconds (human speed); an emulator can advance on
  consecutive polls. Untested lower bound: don't answer 0x2B with 0x2D
  before at least one 0x27/0x34 round if you want to mimic the capture.

## Master emulator (if you must)

Generate CLOCK at 1408 Hz (50 % duty; ±few % is likely fine — the slave
tracks edges). Update your DATA bits just after your rising edge; sample
slave bits at your rising edge (they were set ~35 µs after your falling
edge). Frame per PROTOCOL.md §3.1 (stop + 1-cycle low trailer!), ack every
completed slave frame with the 2-cycle low pulse (§3.4).

```
1. Beacon phase: repeat { run clock; 6 × 0x32 every 30 cycles;
   stop clock 21 ms } until a beacon gets a 0x34 reply (reply starts
   12 cycles after your frame's start bit).
2. Poll 0x32 every 141 cycles. After ~5 ok polls send 0x39 (expect 0x34),
   then 0x39 again (expect 0x2D).  -> "Ok!" state.
3. To trade: fast-poll 0x2B every 28 cycles. Expect 0x34s, an 0x27, and
   finally 0x2D.
4. On 0x2D: ack, wait 2 idle cycles, send your 52-bit payload, then read the
   slave payload starting the very next cycle (slave slots). Ack it.
5. Poll 0x32 (expect one 0x27, then 0x34s) while "preview" is on the toy's
   screen; when accepting, fast-poll 0x2B until 0x27 (slave accepted) and
   0x2D (done). Ack, park clock high. Trade complete.
```

## Verifying against the capture

`analysis/` contains the decoding pipeline used to derive all of this:

- `edges.py` — load CSV, find activity (writes `capture.npy`)
- `bursts.py` / `framing.py` — clock structure
- `phase.py` / `duplex.py` / `timeline.py` — split the shared data wire into
  master/slave streams by transition phase
- `payload.py` / `detail.py` / `transcript.py` — frame dumps and per-cycle
  tables
- `checksum.py` — the (failed) checksum search over the payload tail
- `full_decode.py` — end-to-end decoder implementing PROTOCOL.md; regenerates
  `transcript.txt` (the complete decoded session). Both captured payloads
  decode to exactly the known traded monsters, validating the format.

Re-run order: `edges.py` first (needs `trade.csv`), then any of the others.
