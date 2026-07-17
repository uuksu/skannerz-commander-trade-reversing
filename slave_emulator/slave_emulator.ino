/*
 * Skannerz trade slave emulator
 *
 * Emulates the slave side of the Radica Skannerz Commander (model 72045)
 * link/trade protocol so a real toy (acting as clock master) can trade
 * monsters with this MCU.
 * Protocol details: see PROTOCOL.md; implementation notes: IMPLEMENTATION.md.
 *
 * Wiring (toy link connector; diagram in IMPLEMENTATION.md):
 *   PIN 1  CLOCK -> PIN_CLK   (input only, toy drives it, 1408 Hz idle-high)
 *   PIN 2  GND   -> GND       (common ground, mandatory)
 *   PIN 3  DATA  -> PIN_DATA  (shared, open-drain style, idle-high)
 *
 * ELECTRICAL: the toy runs at 4.5 V (three AAA cells).
 *  - 5 V Arduino (Uno/Nano): connect directly - recommended. The sketch
 *    never drives DATA high (open-drain: pull low or release), so the toy
 *    never sees 5 V. Internal pull-up is acceptable (5 V through 20-50 k is
 *    only 0.5 V above the toy's rail, below its protection diode drop);
 *    cleaner: USE_INTERNAL_PULLUP 0 + external 10-47 k from DATA to the
 *    toy's 4.5 V rail.
 *  - 3.3 V boards (ESP32, RP2040...): do NOT connect directly - the toy
 *    drives CLK and DATA to 4.5 V, above non-5V-tolerant input maximums.
 *    Divider on CLK + bidirectional level shifter on DATA required.
 */

#define USE_INTERNAL_PULLUP 1

const uint8_t PIN_CLK  = 2;
const uint8_t PIN_DATA = 3;

/* ---- Monster to send (the whole point of the exercise) ----
 * The 4-bit "nibble" field is a CHECKSUM, fully cracked 2026-07-16
 * against a real toy (analysis/nibble_rule.py), over the number byte,
 * the (BCD-encoded) HP byte, and EXP:
 *   digitSum(x) = hi_nibble(x) + lo_nibble(x)
 *   expTerm     = (EXP % 8) - (EXP / 8)
 *   nibble = (-digitSum(byte) - 2*digitSum(hpBcd) + expTerm) mod 8
 * Only the low 3 bits are CHECKED (for acceptance) - a real toy accepted
 * both n and n+8 for the same monster (confirmed at n=0/8 and n=1/9), so
 * the top bit is a don't-care for the checksum and checksumFor() below
 * only ever needs to produce 0..7 to be accepted.
 * Cracked in three passes, each a controlled accept/reject sweep against
 * a real toy: the byte term (9 pairs at HP=63, EXP=9), the HP term (one
 * fixed byte, HP=1/2/3/4/10), the EXP term (one fixed byte+HP, EXP swept
 * 1..9/16 on two different byte+HP baselines to confirm separability).
 * expTerm(9) == 0, which is exactly why every earlier byte/HP experiment
 * "just worked" while EXP sat at this sketch's default of 9 - EXP's
 * contribution was silently cancelling out the whole time.
 * Wrong low-3-bits -> ERROR. The nibble carries no *fixed* monster
 * identity - byte 0x89 (num 138) confirmed valid, so the full roster
 * (126 + 12 secret) is probably addressable. But the FULL 4-bit nibble
 * (not just the checked low 3 bits) carries real meaning: it's also the
 * "Level" the toy displays after a trade - level = (nibble>>2)+1, over
 * all 16 values, giving levels 1..4. Confirmed 2026-07-17 in two rounds:
 * all 8 checksum-valid residues (top bit 0) gave levels 1-2 (8/8); since
 * the top bit doesn't affect acceptance, forcing it set on the same
 * monsters (nibble -> nibble+8, still accepted) gave levels 3-4 (4/4).
 * NUM/HP/EXP fix bit 2 of the nibble via the checksum (not freely
 * choosable), but the top bit is free - so for one monster you can pick
 * between exactly two levels (L and L+2) via MONSTER_NIBBLE = auto value
 * or auto value + 8; reaching the other pair needs different NUM/HP/EXP.
 * NOTE: the toy's displayed monster number is NOT always byte + 1
 * (byte 0x0A displays as "11", but byte 0x04 as "15"); mapping under
 * investigation — use HARVEST_MODE.
 * HP goes on the wire as BCD (0x63 = 63); non-BCD bytes -> ERROR. No
 * confirmed ceiling below 99: BCD 0x99 is accepted with the correct
 * HP-aware checksum (2026-07-16) - the earlier "BCD 99 -> ERROR" finding
 * predates knowing HP feeds the checksum, so that was a checksum
 * mismatch, not a range check (same trap the NUM field's early "range
 * errors" turned out to be). The toy's UI visibly breaks at HP 99 (the
 * in-game balance cap is ~63) but the wire accepts it. 99 is also as
 * high as MONSTER_HP can go through toBcd() without producing an
 * invalid (non-BCD) byte, so it's untested whether the toy enforces any
 * ceiling beyond BCD validity itself.
 * EXP is a raw 7-bit win-counter (round-trips bit-exact: 127 sent came
 * back as 127). The displayed "EXP" stat is EXP/8 (floor, no offset),
 * fully solved 2026-07-17 by a real-toy sweep (9->1, 16->2, 21->2,
 * 64->8, 112->14, 128 (truncates to 0 on the wire)->0, all exact) - a
 * BCD-decode theory (like HP's encoding) was tested and refuted at
 * EXP=16 (would predict display 1, actually shows 2). Level is NOT
 * EXP/30+1 as the manual implies - see the nibble note above. */
const uint8_t MONSTER_NUM    = 138;   // wire byte = NUM-1
const uint8_t MONSTER_HP     = 63;   // 1..99 (BCD-encoded by the sketch; ceiling above 99 untested)

/* Primary interface: say what you want the monster's real stats to be,
 * not the raw wire fields. 1 = derive MONSTER_EXP/MONSTER_NIBBLE below
 * from TARGET_LEVEL/TARGET_EXP via solveLevelExp() (see its comment for
 * how); 0 = fall back to setting MONSTER_EXP/MONSTER_NIBBLE directly,
 * for lower-level experiments (e.g. deliberately sending the level-4
 * glitch value). */
#define USE_LEVEL_EXP_INTERFACE 1

#if USE_LEVEL_EXP_INTERFACE
const uint8_t TARGET_LEVEL = 3;   // 1..3 - the level the toy should show.
                                   // 4 is a real wire value but not a real
                                   // game one (see header comment); refused.
const uint8_t TARGET_EXP   = 0;  // 0..127. CAUTION 2026-07-17: this field's
                                   // receiver-side readout (visible only in
                                   // the toy's monster menu, NOT during a
                                   // trade) has been proven to cap at
                                   // floor(TARGET_EXP/8), max 15 - it may
                                   // NOT be the same persistent experience
                                   // counter the manual describes (that one
                                   // is believed to exceed 15 from normal
                                   // battling and should not be
                                   // trade-transferable). See MONSTER_ZEROS
                                   // below - still probing for the real field.
#endif

uint8_t MONSTER_EXP    = 0;    // raw win-counter 0..127; overwritten by
                               // solveLevelExp() in setup() if
                               // USE_LEVEL_EXP_INTERFACE is 1
uint8_t MONSTER_NIBBLE = 0xFF; // 0xFF = auto (checksum rule); 0..15 forces a
                               // value; overwritten the same way as MONSTER_EXP

/* EXPERIMENTAL 2026-07-17: the 12 "zeros" bits (wire bits 32-43) have been
 * sent as all-zero in every test since the project started, on the
 * assumption they were padding. They're the only unexplored region left
 * in the payload, and a prime suspect for holding the toy's REAL
 * persistent experience counter (wide enough for values > 15, unlike the
 * proven-capped-at-15 EXP field above). Set this to a real-world value
 * you can compare against the monster menu (e.g. 30) and MONSTER_EXP to
 * something distinguishable (e.g. 0) to test whether it's this field,
 * not MONSTER_EXP, that the toy actually displays as experience. */
const uint16_t MONSTER_ZEROS = 0;  // 0..4095, MSB-first; 0 matches every
                                    // capture/test so far

/* Harvest mode: complete the payload exchange (so the toy's monster data
 * gets logged over serial), then keep acking without ever accepting, so
 * the trade cannot commit. CANCEL THE TRADE ON THE TOY after each round —
 * it keeps its monster, its trade state resets cleanly (a silent abort
 * makes it re-send the same monster next round), and whatever byte the
 * cancel puts on the wire gets logged (reject codes are still unknown). */
#define HARVEST_MODE 0

/* ---- Timing (from PROTOCOL.md section 6) ---- */
const uint16_t SLAVE_SETUP_US   = 35;       // drive our bit this long after CLK falling edge
const uint32_t EDGE_TIMEOUT_US  = 500000UL; // clock gaps in handshake are only ~21 ms

/* How many fast polls (~20 ms each) we ack before advancing a stage.
 * The real toy takes human-speed seconds; the master does not enforce a
 * minimum, but a few rounds mimic the captured trace. */
const uint8_t POLLS_BEFORE_EVENT = 5;  // 0x34 acks before the 0x27 "user acted" event
const uint8_t POLLS_BEFORE_READY = 5;  // 0x34 acks after 0x27 before 0x2D "proceed"

enum State : uint8_t {
  WAIT_LINK,  // waiting for master beacon 0x32
  LINKED,     // answering polls, waiting for 0x39 session confirm
  CONFIRM,    // one 0x39 seen, second one gets 0x2D -> "Ok!" on the toy
  IDLE,       // 100 ms polling; master user navigates menus
  SELECT,     // master fast-polls 0x2B: announce selection, then 0x2D -> exchange
  PREVIEW,    // toy shows our incoming monster; first 0x32 gets an 0x27 event
  ACCEPT,     // master fast-polls again (its user accepted); we accept too
              // (in HARVEST_MODE we hold here forever - cancel on the toy)
  COMPLETE    // 0x2D sent; waiting for the master to park the clock
};

State state = WAIT_LINK;
uint8_t pollCount = 0;
bool previewEventSent = false;
uint8_t timeoutsInARow = 0;

uint8_t txBits[52];
uint8_t rxBits[52];

/* ---------------- data line, open-drain style ---------------- */

static inline void dataRelease() {
#if USE_INTERNAL_PULLUP
  pinMode(PIN_DATA, INPUT_PULLUP);
#else
  pinMode(PIN_DATA, INPUT);        // external pull-up to the toy's Vcc
#endif
}

static inline void dataLow() {
  // digitalWrite before pinMode: going INPUT_PULLUP -> OUTPUT directly
  // would drive HIGH for an instant (output latch still 1)
  digitalWrite(PIN_DATA, LOW);
  pinMode(PIN_DATA, OUTPUT);
}

static inline void setData(bool b) { b ? dataRelease() : dataLow(); }
static inline bool readData()      { return digitalRead(PIN_DATA); }

/* Wait for a CLK falling edge. False on timeout (clock stopped). */
static bool waitFall(uint32_t timeout_us = EDGE_TIMEOUT_US) {
  uint32_t t0 = micros();
  bool prev = digitalRead(PIN_CLK);
  for (;;) {
    bool cur = digitalRead(PIN_CLK);
    if (prev && !cur) return true;
    prev = cur;
    if ((uint32_t)(micros() - t0) > timeout_us) return false;
  }
}

/* Master bits are valid at the falling edge. */
static inline int readMasterBit() {
  if (!waitFall()) return -1;
  return readData();
}

/* Slave bits go out shortly after the falling edge (our slot);
 * the master samples them at the rising edge. */
static bool writeSlaveBit(bool b) {
  if (!waitFall()) { dataRelease(); return false; }
  delayMicroseconds(SLAVE_SETUP_US);
  setData(b);
  return true;
}

/* After every completed slave frame the master pulls DATA low for ~2
 * cycles (ack pulse, 1..4 cycles after our last one). Consume it so the
 * frame hunter never mistakes it for a start bit. */
static void consumeAck() {
  bool sawLow = false;
  for (uint8_t i = 0; i < 6; i++) {
    int b = readMasterBit();
    if (b < 0) return;
    if (b == 0) sawLow = true;
    else if (sawLow) return;
  }
}

/* ---------------- frames ---------------- */

/* Receive one master frame: start(0) + 8 data MSB-first + stop slot +
 * 2 tail cycles. Stop slot low = event frame (0x39). Returns the byte,
 * or -1 on clock timeout. Leaves the clock position such that the next
 * falling edge is the reply slot (frame start + 12). */
static int receiveFrame(bool &isEvent) {
  bool sawIdle = false;
  for (;;) {                      // hunt: idle high, then a start bit
    int b = readMasterBit();
    if (b < 0) return -1;
    if (b == 1) sawIdle = true;
    else if (sawIdle) break;
  }
  uint8_t v = 0;
  for (uint8_t i = 0; i < 8; i++) {
    int b = readMasterBit();
    if (b < 0) return -1;
    v = (v << 1) | b;
  }
  int stop = readMasterBit();
  if (stop < 0) return -1;
  isEvent = (stop == 0);
  // tail: normal = low,high; event = high,high - consume both either way
  if (readMasterBit() < 0 || readMasterBit() < 0) return -1;
  return v;
}

/* Send a slave frame in the reply slot. afterEvent: replies to a master
 * event frame (0x39) start one cycle later (+13 instead of +12).
 * asEvent: send the 0x27-style frame (stop slot low + one extra low). */
static void sendFrame(uint8_t v, bool asEvent = false, bool afterEvent = false) {
  if (afterEvent && !waitFall()) return;
  if (!writeSlaveBit(0)) return;                 // start
  for (int8_t b = 7; b >= 0; b--)
    if (!writeSlaveBit((v >> b) & 1)) return;
  if (!asEvent) {
    writeSlaveBit(1);                            // stop = release
  } else {
    writeSlaveBit(0);                            // low stop slot
    writeSlaveBit(0);                            // extra low
    writeSlaveBit(1);                            // release
  }
  consumeAck();
}

/* ---------------- payload ---------------- */

static inline uint8_t toBcd(uint8_t v)   { return ((v / 10) << 4) | (v % 10); }
static inline uint8_t fromBcd(uint8_t v) { return (v >> 4) * 10 + (v & 0x0F); }

/* Checksum rule for the payload nibble (see header comment): a BCD
 * digit-sum checksum over the number byte and the (BCD-encoded) HP byte,
 * plus a base-8 digit-difference term over EXP. Only the low 3 bits are
 * checked (the toy accepts either n or n+8 - confirmed by testing both).
 * Bit 2 of the returned value doubles as the displayed "Level" (>>2)+1. */
static uint8_t checksumFor(uint8_t numByte, uint8_t hpBcd, uint8_t exp) {
  int8_t numSum = (numByte >> 4) + (numByte & 0x0F);
  int8_t hpSum  = (hpBcd >> 4) + (hpBcd & 0x0F);
  int8_t expTerm = (exp % 8) - (exp / 8);
  return (uint8_t)(-numSum - 2 * hpSum + expTerm) & 0x07;
}

static uint8_t nibbleFor(uint8_t numByte, uint8_t hpBcd, uint8_t exp) {
  return MONSTER_NIBBLE != 0xFF ? MONSTER_NIBBLE : checksumFor(numByte, hpBcd, exp);
}

/* Given NUM/HP and a desired (Level, EXP) pair, work out the raw wire
 * EXP + nibble that produce them (2026-07-17 finding). Level =
 * (nibble>>2)+1: the nibble's low 3 bits are pinned to checksumFor(...),
 * only the top bit is free (checksumFor()>>2 is the "band" - 0 picks
 * between level 1/3, 1 picks between level 2/4 - and the top bit then
 * picks which of the pair). At the EXACT target EXP the band is fixed,
 * so only 2 of the 3 real levels are reachable there - but EXP's low 3
 * bits (exp = 8*(targetExp/8) + r, r=0..7) cycle through all 8 checksum
 * residues as r varies, so ANY level is reachable within the same "tens"
 * bucket (targetExp/8 unchanged) by nudging only those low bits. This
 * picks the r closest to what was actually requested, so the sent EXP
 * lands as near TARGET_EXP as possible while still hitting TARGET_LEVEL
 * exactly (max deviation across the whole NUM/HP/level/EXP space is 4,
 * verified by exhaustive search offline). Level 4 is a real wire value
 * (see header comment) but not a real game one, so it's refused here. */
static void solveLevelExp(uint8_t numByte, uint8_t hpBcd, uint8_t level, uint8_t targetExp,
                           uint8_t &outExp, uint8_t &outNibble) {
  if (level < 1 || level > 3) {
    Serial.println(F("TARGET_LEVEL must be 1..3 (4 is an invalid glitch value) - halting"));
    while (true) {}
  }
  if (targetExp > 127) {
    Serial.println(F("TARGET_EXP must be 0..127 - halting"));
    while (true) {}
  }
  uint8_t band       = (level == 2) ? 1 : 0;  // level 1/3 -> band 0, level 2 -> band 1
  uint8_t topBit     = (level == 3) ? 1 : 0;  // level 3 is level 1's "+8 twin"
  uint8_t decadeBase = (targetExp / 8) * 8;
  uint8_t r0         = targetExp - decadeBase;
  int16_t bestDist   = 999;
  for (uint8_t r = 0; r < 8; r++) {
    uint8_t exp = decadeBase + r;
    uint8_t c = checksumFor(numByte, hpBcd, exp);
    if ((c >> 2) == band) {
      int16_t dist = (r > r0) ? (r - r0) : (r0 - r);
      if (dist < bestDist) {
        bestDist  = dist;
        outExp    = exp;
        outNibble = c | (topBit << 3);
      }
    }
  }
  if (bestDist == 999) {  // mathematically unreachable (see comment), but don't ship garbage
    Serial.println(F("solveLevelExp: no candidate found - this should be impossible - halting"));
    while (true) {}
  }
}

static void buildTxPayload() {
  uint8_t hp  = toBcd(MONSTER_HP);
  uint8_t nib = nibbleFor(MONSTER_NUM - 1, hp, MONSTER_EXP);
  uint8_t i = 0;
  txBits[i++] = 0;                                            // start
  txBits[i++] = 1; txBits[i++] = 1; txBits[i++] = 1;          // sync '111'
  for (int8_t b = 7; b >= 0; b--) txBits[i++] = ((MONSTER_NUM - 1) >> b) & 1;
  for (int8_t b = 3; b >= 0; b--) txBits[i++] = (nib >> b) & 1;
  for (int8_t b = 7; b >= 0; b--) txBits[i++] = (hp >> b) & 1;
  for (int8_t b = 7; b >= 0; b--) txBits[i++] = (hp >> b) & 1;
  for (int8_t b = 11; b >= 0; b--) txBits[i++] = (MONSTER_ZEROS >> b) & 1;  // unknown - probing for real EXP
  for (int8_t b = 6; b >= 0; b--) txBits[i++] = (MONSTER_EXP >> b) & 1;
  txBits[i++] = 1;                                            // stop
}

static uint16_t rxField(uint8_t from, uint8_t to) {  // [from,to) bit range
  uint16_t v = 0;
  for (uint8_t i = from; i < to; i++) v = (v << 1) | rxBits[i];
  return v;
}

/* Dump 52 payload bits grouped by field:
 * start sync num nibble hp hp zeros exp stop */
static void printPayloadBits(const uint8_t *bits) {
  for (uint8_t i = 0; i < 52; i++) {
    Serial.write(bits[i] ? '1' : '0');
    if (i == 0 || i == 3 || i == 11 || i == 15 || i == 23 || i == 31
        || i == 43 || i == 50)
      Serial.write(' ');
  }
  Serial.println();
}

static void printRxMonster() {
  Serial.print(F("<< rx payload: "));
  printPayloadBits(rxBits);
  Serial.print(F("<< numByte="));
  Serial.print(rxField(4, 12));
  Serial.print(F(" (num "));
  Serial.print(rxField(4, 12) + 1);
  Serial.print(F(") nibble="));
  Serial.print(rxField(12, 16));
  Serial.print(F(" HP=0x"));
  Serial.print(rxField(16, 24), HEX);
  Serial.print(F("/0x"));
  Serial.print(rxField(24, 32), HEX);
  Serial.print(F(" (BCD "));
  Serial.print(fromBcd(rxField(16, 24)));
  Serial.print(F(") zeros=0x"));
  Serial.print(rxField(32, 44), HEX);
  Serial.print(F(" EXPraw="));
  Serial.println(rxField(44, 51));
  uint8_t want = checksumFor(rxField(4, 12), rxField(16, 24), rxField(44, 51));
  Serial.print(F("<< nibble checksum: rule says "));
  Serial.print(want);
  Serial.println((rxField(12, 16) & 0x07) == want ? F(" - MATCH") : F(" - MISMATCH!"));
  if (rxField(1, 4) != 0b111 || rxBits[51] != 1)
    Serial.println(F("   (warning: bad sync/stop - payload misread?)"));
}

/* Exchange payloads. Called right after sendFrame(0x2D) + its ack.
 * The master idles ~2 cycles, then sends its 52-cycle payload; ours must
 * start on the cycle immediately after its last one - so no printing
 * until both directions are done.
 * Returns: 1 = exchanged, 0 = master sent a normal frame instead (stored
 * in fallbackByte, master's user may not be ready yet), -1 = timeout. */
static int8_t exchangePayloads(uint8_t &fallbackByte) {
  bool sawIdle = false;
  for (;;) {
    int b = readMasterBit();
    if (b < 0) return -1;
    if (b == 1) sawIdle = true;
    else if (sawIdle) break;
  }
  rxBits[0] = 0;
  for (uint8_t i = 1; i <= 3; i++) {           // expect sync '111'
    int b = readMasterBit();
    if (b < 0) return -1;
    rxBits[i] = b;
  }
  if (rxField(1, 4) != 0b111) {
    // not a payload: finish reading it as a normal 12-cycle frame
    uint8_t v = (rxBits[1] << 2) | (rxBits[2] << 1) | rxBits[3];
    for (uint8_t i = 0; i < 5; i++) {
      int b = readMasterBit();
      if (b < 0) return -1;
      v = (v << 1) | b;
    }
    if (readMasterBit() < 0) return -1;        // stop slot
    if (readMasterBit() < 0 || readMasterBit() < 0) return -1;  // tail
    fallbackByte = v;
    return 0;
  }
  for (uint8_t i = 4; i < 52; i++) {
    int b = readMasterBit();
    if (b < 0) return -1;
    rxBits[i] = b;
  }
  for (uint8_t i = 0; i < 52; i++)             // our payload, next cycle on
    if (!writeSlaveBit(txBits[i])) return -1;  // last bit is the stop/release
  consumeAck();
  return 1;
}

/* ---------------- state machine ---------------- */

static void toState(State s, const __FlashStringHelper *name) {
  state = s;
  pollCount = 0;
  Serial.print(F("-> "));
  Serial.println(name);
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_CLK, INPUT);
  dataRelease();
#if USE_LEVEL_EXP_INTERFACE
  solveLevelExp(MONSTER_NUM - 1, toBcd(MONSTER_HP), TARGET_LEVEL, TARGET_EXP,
                MONSTER_EXP, MONSTER_NIBBLE);
  Serial.print(F("solved for target level="));
  Serial.print(TARGET_LEVEL);
  Serial.print(F(" EXP="));
  Serial.print(TARGET_EXP);
  Serial.print(F(" -> sent EXP="));
  Serial.print(MONSTER_EXP);
  Serial.print(F(" nibble="));
  Serial.print(MONSTER_NIBBLE);
  Serial.print(F(" (monster-menu \"EXP\" stat is proven to show floor(sentEXP/8) = "));
  Serial.print(MONSTER_EXP / 8);
  Serial.println(F(" for this field - may not be the real experience counter)"));
#endif
  if (MONSTER_ZEROS != 0) {
    Serial.print(F("probing zeros field: sending 0x"));
    Serial.println(MONSTER_ZEROS, HEX);
  }
  buildTxPayload();
  Serial.println(F("Skannerz slave emulator"));
  Serial.print(F("sending monster num="));
  Serial.print(MONSTER_NUM);
  Serial.print(F(" nibble="));
  Serial.print(nibbleFor(MONSTER_NUM - 1, toBcd(MONSTER_HP), MONSTER_EXP));
  Serial.print(F(" HP="));
  Serial.print(MONSTER_HP);
  Serial.print(F(" EXP="));
  Serial.println(MONSTER_EXP);
  Serial.print(F(">> tx payload: "));
  printPayloadBits(txBits);
#if HARVEST_MODE
  Serial.println(F("HARVEST MODE: trades will never commit"));
#endif
  Serial.println(F("waiting for master beacon..."));
}

void loop() {
  bool evt = false;
  int f = receiveFrame(evt);

  if (f < 0) {                       // clock stopped
    timeoutsInARow++;
    if (state == COMPLETE && timeoutsInARow >= 2) {
      Serial.println(F("=== trade complete, session closed ==="));
      previewEventSent = false;
      toState(WAIT_LINK, F("WAIT_LINK"));
    } else if (state != WAIT_LINK && timeoutsInARow >= 20) {
      Serial.println(F("link lost, resetting"));
      previewEventSent = false;
      toState(WAIT_LINK, F("WAIT_LINK"));
    }
    return;
  }
  timeoutsInARow = 0;

  // anything outside the known master vocabulary is protocol news
  // (e.g. the still-unknown cancel/reject codes) - log it
  if (f != 0x32 && f != 0x2B && f != 0x39) {
    Serial.print(F("?? master sent 0x"));
    Serial.print((uint8_t)f, HEX);
    Serial.println(evt ? F(" (event frame)") : F(""));
  }

  switch (state) {
    case WAIT_LINK:
      if (f == 0x32) { sendFrame(0x34); toState(LINKED, F("LINKED")); }
      break;

    case LINKED:
      if (f == 0x32) sendFrame(0x34);
      else if (f == 0x39 && evt) { sendFrame(0x34, false, true); toState(CONFIRM, F("CONFIRM")); }
      break;

    case CONFIRM:
      if (f == 0x39 && evt) { sendFrame(0x2D, false, true); toState(IDLE, F("IDLE (Ok!)")); }
      else if (f == 0x32) sendFrame(0x34);
      break;

    case IDLE:
      if (f == 0x32) sendFrame(0x34);
      else if (f == 0x2B) { sendFrame(0x34); toState(SELECT, F("SELECT")); }
      break;

    case SELECT:
      if (f == 0x2B) {
        pollCount++;
        if (pollCount == POLLS_BEFORE_EVENT) {
          sendFrame(0x27, true);               // "my user selected a monster"
        } else if (pollCount >= POLLS_BEFORE_EVENT + POLLS_BEFORE_READY) {
          sendFrame(0x2D);                     // "ready - exchange now"
          uint8_t fb = 0;
          int8_t r = exchangePayloads(fb);
          if (r == 1) {
            printRxMonster();
#if HARVEST_MODE
            Serial.println(F("harvest: payload logged; will never accept - "
                             "cancel the trade on the toy"));
#endif
            toState(PREVIEW, F("PREVIEW"));
          } else {
            // master wasn't ready (untested path): back off, retry later
            Serial.println(F("no payload after 0x2D, retrying"));
            pollCount = POLLS_BEFORE_EVENT;    // keep acking, 0x2D again soon
          }
        } else {
          sendFrame(0x34);
        }
      } else if (f == 0x32) sendFrame(0x34);
      break;

    case PREVIEW:
      if (f == 0x32) {
        if (!previewEventSent) { sendFrame(0x27, true); previewEventSent = true; }
        else sendFrame(0x34);
      } else if (f == 0x2B) { sendFrame(0x34); toState(ACCEPT, F("ACCEPT")); }
      break;

    case ACCEPT:
#if HARVEST_MODE
      if (f == 0x32 || f == 0x2B) sendFrame(0x34);   // hold: never accept
#else
      if (f == 0x2B) {
        pollCount++;
        if (pollCount == POLLS_BEFORE_EVENT) {
          sendFrame(0x27, true);               // "my user accepted"
        } else if (pollCount >= POLLS_BEFORE_EVENT + POLLS_BEFORE_READY) {
          sendFrame(0x2D);                     // "done, close the session"
          toState(COMPLETE, F("COMPLETE"));
        } else {
          sendFrame(0x34);
        }
      } else if (f == 0x32) sendFrame(0x34);
#endif
      break;

    case COMPLETE:
      if (f == 0x32 || f == 0x2B) sendFrame(0x34);   // master still winding down
      break;
  }
}
