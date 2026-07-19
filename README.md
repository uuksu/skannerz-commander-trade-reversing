# Skannerz Commander trade protocol reverse engineering

AI (Claude Sonnet/Fable) assisted effort for reverse engineering Skannerz Commander trade protocol. 

## Status: solved

- Full wire protocol decoded: handshake, framing, byte vocabulary, session
  flow, and the 52-bit monster payload.
- All payload fields cracked, including the 4-bit checksum (which doubles as
  the displayed **Level**), the BCD experience counter split across two
  fields, and the wire↔displayed monster-number mapping.
- A working **slave emulator** for a 5 V Arduino completes real trades
  against a real toy: any monster number, HP 1–99, level 1–3, exact
  experience 0–9999. It can also harvest a toy's collection over serial
  without committing any trade.

A few loose ends remain (slave-side reject byte, HP = 0, …) — see
[PROTOCOL.md §7](PROTOCOL.md#7-open-questions).

## Repository map

| Path | What it is |
|------|------------|
| [`PROTOCOL.md`](PROTOCOL.md) | The wire-protocol specification — start here |
| [`IMPLEMENTATION.md`](IMPLEMENTATION.md) | MCU emulation guide: wiring, bit-banging, payload construction, state machine |
| [`HISTORY.md`](HISTORY.md) | How the findings were reached, including the theories that turned out wrong |
| [`slave_emulator/slave_emulator.ino`](slave_emulator/slave_emulator.ino) | Reference implementation: Arduino slave emulator |
| [`analysis/`](analysis/) | Python/numpy pipeline that decodes the capture |
| `trade.csv` | The raw 200 kHz, 4-channel logic-analyzer capture of one complete trade |
| [`task.txt`](task.txt) | The original project brief |

## Trading with an Arduino

You need a **5 V** Arduino (Uno/Nano — 3.3 V boards need level shifting, see
[IMPLEMENTATION.md](IMPLEMENTATION.md)) and three wires to the toy's link
port: CLOCK → D2, GND → GND, DATA → D3. The toy runs at 4.5 V; the sketch
treats DATA as open-drain so the toy never sees 5 V.

1. Open `slave_emulator/slave_emulator.ino` and set the monster at the top:
   `MONSTER_NUM`, `MONSTER_HP`, `TARGET_LEVEL`, `TARGET_EXP`. The checksum
   and raw wire fields are derived automatically.
2. Flash, open the serial monitor (115200 baud), and put the toy in trade
   mode. The emulator links, confirms, exchanges payloads, and accepts —
   the toy receives your monster and shows the incoming one it "traded" for.
3. Optional: set `HARVEST_MODE 1` to log every monster a toy offers over
   serial without ever completing the trade (cancel on the toy between
   rounds).

## Reproducing the analysis

Requires Python 3 with numpy. The scripts hardcode this repo's path, so run
them from anywhere:

```sh
python3 analysis/edges.py        # parses trade.csv into capture.npy — run first
python3 analysis/full_decode.py  # decodes the whole session, writes transcript.txt
python3 analysis/nibble_rule.py  # checksum/Level/EXP rules + accept/reject datasets
```

`full_decode.py` is the end-to-end check: it re-derives every frame in the
capture from the rules in PROTOCOL.md, and both payloads decode to exactly
the monsters that were traded (Night Lurk HP 3 ↔ Diamond Back HP 1).

## Highlights for the curious

- One data wire, both directions at once: master and slave each own a phase
  of every clock cycle, so the slave can reply with zero bus turnaround.
- The "checksum" nibble is also the monster's displayed Level — the toy
  validates only 3 of its 4 bits, and the free bit plus a don't-care field
  in the experience counter let you pick any level without changing any
  other stat.
- The experience counter is BCD, split additively across two fields — and
  one of them isn't BCD-validated, so out-of-range digits render as garbage
  experience values on a real toy instead of erroring.

The full story, including every dead end, is in [HISTORY.md](HISTORY.md).
