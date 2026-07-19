# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Reverse engineering of the trade protocol of the Radica Skannerz Commander (2003 electronic toy), from a 200 kHz logic-analyzer capture (`trade.csv`) of one real trade plus controlled hardware experiments against a real toy. The original brief is `task.txt`. The deliverables are the protocol documentation and an MCU emulator that can stand in for one toy — not an app; there is no build system, test suite, or linter.

## Documentation architecture (the core convention)

Findings are split across three living documents, updated **as findings emerge**, not as a final phase (explicit task requirement):

- `PROTOCOL.md` — the validated wire-protocol spec. Source of truth for all protocol facts; §7 tracks open questions. Don't restate its contents elsewhere — link/point to it.
- `IMPLEMENTATION.md` — companion MCU bit-bang guide (wiring, bit primitives, payload construction, session state machine).
- `HISTORY.md` — process log: milestones, the raw test log, and **superseded/wrong theories**. Disproven theories are moved here with the reason they fell, never silently deleted.
- `README.md` — human-facing overview/entry point; summarizes the above without adding facts. Keep its status claims and instructions consistent when the docs change.

When a finding changes: update `PROTOCOL.md` (and `IMPLEMENTATION.md` if it affects the emulator), record how it was reached in `HISTORY.md`, and keep the sketch's comments consistent with both.

Every protocol claim carries an evidence tier — derived from the capture, verified by hardware test against the real toy, or untested (goes in PROTOCOL.md §7). Preserve that distinction when editing; don't upgrade a claim's certainty without a new test.

## Code layout

- `slave_emulator/slave_emulator.ino` — **the reference implementation** of the whole protocol (Arduino slave emulator). Configuration lives in constants/flags at the top: `MONSTER_NUM`/`MONSTER_HP`/`TARGET_LEVEL`/`TARGET_EXP`, `USE_LEVEL_EXP_INTERFACE` (stat-based vs raw wire fields), `HARVEST_MODE` (dump a toy's collection without committing trades), `HOLD_AT_SELECT` (cancel-path experiments). Experiments are run by editing these flags.
- `analysis/` — Python/numpy decoding pipeline over the capture. Scripts hardcode absolute paths under `/home/mikko/skannerz-trade-reversing/`, so they run from anywhere.
- `trade.csv` — 26 MB raw capture, 4 channels. **Never read it directly**; go through `analysis/capture.npy` and the scripts.

## Running the analysis pipeline

```
python3 analysis/edges.py        # first: parses trade.csv, writes capture.npy
python3 analysis/full_decode.py  # end-to-end decoder; regenerates transcript.txt
python3 analysis/nibble_rule.py  # checksum/Level/EXP rules + the real-toy accept/reject datasets and verifiers
```

`edges.py` must run before anything else (everything loads `capture.npy`). `full_decode.py` implements PROTOCOL.md and is the regression check: both captured payloads must decode to exactly the known traded monsters. The other scripts (`framing.py`, `phase.py`, `duplex.py`, `timeline.py`, `payload.py`, `detail.py`, `transcript.py`, …) are the intermediate exploration steps; run order and roles are listed at the end of `IMPLEMENTATION.md`.

## Verifying changes

There is no Arduino toolchain on this machine (`arduino-cli` not installed) — the `.ino` cannot be compiled or tested here. Hardware verification means the user flashes the sketch and runs a trade against the real toy; when a change needs that, say so and hand it off rather than claiming it verified. Capture-level claims *can* be verified locally via `full_decode.py` and `nibble_rule.py` (both contain assertions/verifiers over recorded data).

## Domain quick facts

The toy under test is the master (drives the 1408 Hz clock); the emulator always plays slave. One shared data wire carries both directions, split by clock phase. The checksum, Level, real-EXP counter, and wire↔displayed number mapping are fully solved — see PROTOCOL.md §3.5 before touching payload code. Known open items (slave-side reject byte, master frame trailer purpose, HP=0, EXP field width) are in PROTOCOL.md §7.
