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

/* ---- Monster to send ----
 * Field semantics, checksum rule and receiver validation: PROTOCOL.md
 * §3.5. In short: the 4-bit nibble is a checksum (checksumFor() below)
 * of which the toy checks only the low 3 bits, and the full 4-bit field
 * doubles as the displayed Level = (nibble>>2)+1; the persistent
 * experience counter spans the zeros and EXP fields,
 * displayedEXP = 10*decodeBcd3(zeros) + EXP/8.
 * The displayed monster number is NOT simply wire byte + 1; the mapping
 * is unresolved (PROTOCOL.md §7) - use HARVEST_MODE to gather pairs. */
const uint8_t MONSTER_NUM    = 138;   // wire byte = NUM-1
const uint8_t MONSTER_HP     = 63;   // 1..99, BCD-encoded by the sketch

/* Primary interface: state the stats the toy should show instead of raw
 * wire fields. 1 = derive MONSTER_ZEROS/MONSTER_EXP/MONSTER_NIBBLE below
 * from TARGET_LEVEL/TARGET_EXP via solveLevelExp(); 0 = set the raw
 * fields directly, for lower-level experiments (e.g. the level-4 glitch
 * value, or non-BCD zeros). */
#define USE_LEVEL_EXP_INTERFACE 1

#if USE_LEVEL_EXP_INTERFACE
const uint8_t  TARGET_LEVEL = 3;   // 1..3 (4 is wire-acceptable but not a
                                    // real game value; refused)
const uint16_t TARGET_EXP   = 95;  // 0..9999, the exact experience counter
#endif

uint16_t MONSTER_ZEROS = 0;    // 12-bit, 3-digit BCD = realEXP/10; overwritten
                               // by solveLevelExp() in setup() if
                               // USE_LEVEL_EXP_INTERFACE is 1
uint8_t MONSTER_EXP    = 0;    // raw 0..127; top 4 bits = realEXP's ones
                               // digit, low 3 bits = free checksum knob.
                               // Overwritten the same way as MONSTER_ZEROS
uint8_t MONSTER_NIBBLE = 0xFF; // 0xFF = auto (checksum rule); 0..15 forces
                               // a value; overwritten the same way too

/* Harvest mode: complete the payload exchange (so the toy's monster data
 * gets logged over serial), then keep acking without ever accepting, so
 * the trade cannot commit. CANCEL THE TRADE ON THE TOY after each round —
 * a silent abort makes it re-send the same monster next round, and the
 * cancel's still-unknown reject bytes get logged. */
#define HARVEST_MODE 0

/* Cancel-testing hold (PROTOCOL.md §7). SELECT normally auto-advances
 * (our own simulated selection + ready-to-exchange) within ~200 ms of
 * the master's first fast poll - too fast for a human to react on the
 * real toy. With this set, SELECT just keeps acking 0x34 forever
 * instead. Answered already (no cancel path exists at that stage on a
 * real toy - HISTORY.md), kept for re-use if that ever needs
 * re-checking. */
#define HOLD_AT_SELECT 0

/* ---- Timing (from PROTOCOL.md section 6) ---- */
const uint16_t SLAVE_SETUP_US   = 35;       // drive our bit this long after CLK falling edge
const uint32_t EDGE_TIMEOUT_US  = 500000UL; // clock gaps in handshake are only ~21 ms

/* How many fast polls (~20 ms each) we ack before advancing a stage.
 * The real toy takes human-speed seconds; the master does not enforce a
 * minimum, but a few rounds mimic the captured trace. */
const uint8_t POLLS_BEFORE_EVENT = 5;  // 0x34 acks before the 0x27 "user acted" event
const uint8_t POLLS_BEFORE_READY = 5;  // 0x34 acks after 0x27 before 0x2D "proceed"

/* Consecutive receiveFrame() timeouts (each up to EDGE_TIMEOUT_US) before
 * declaring the clock truly parked and resetting to WAIT_LINK. The
 * largest legitimate mid-session gap is the ~21 ms handshake listen gap
 * - already well inside one EDGE_TIMEOUT_US - so this just needs to
 * absorb a little jitter, not patience for a long real gap. */
const uint8_t LINK_LOST_TIMEOUTS = 3;

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
uint8_t lastLoggedByte = 0xFF;  // de-dupes repeat logging of an unhandled byte

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

static inline uint8_t  toBcd(uint8_t v)     { return ((v / 10) << 4) | (v % 10); }
static inline uint8_t  fromBcd(uint8_t v)   { return (v >> 4) * 10 + (v & 0x0F); }
static inline uint16_t toBcd3(uint16_t v)   {  // v: 0..999 -> 3-digit BCD in 12 bits
  return ((v / 100) << 8) | (((v / 10) % 10) << 4) | (v % 10);
}
static inline uint16_t fromBcd3(uint16_t v12) {  // inverse of toBcd3()
  return ((v12 >> 8) & 0xF) * 100 + ((v12 >> 4) & 0xF) * 10 + (v12 & 0xF);
}
static inline uint8_t digitSum3(uint16_t v12) {
  return ((v12 >> 8) & 0xF) + ((v12 >> 4) & 0xF) + (v12 & 0xF);
}

/* Payload checksum nibble (PROTOCOL.md §3.5): digit sums of the number
 * byte, the BCD HP byte and the BCD zeros field, plus a base-8
 * digit-difference term over the 7-bit EXP field. The toy checks only
 * the low 3 bits (accepts both n and n+8); the full 4-bit wire field
 * doubles as the displayed Level = (nibble>>2)+1. */
static uint8_t checksumFor(uint8_t numByte, uint8_t hpBcd, uint16_t zerosBcd, uint8_t exp) {
  int8_t numSum    = (numByte >> 4) + (numByte & 0x0F);
  int8_t hpSum     = (hpBcd >> 4) + (hpBcd & 0x0F);
  int8_t zerosSum  = digitSum3(zerosBcd);
  int8_t expTerm   = (exp % 8) - (exp / 8);
  return (uint8_t)(-numSum - 2 * hpSum - zerosSum + expTerm) & 0x07;
}

static uint8_t nibbleFor(uint8_t numByte, uint8_t hpBcd, uint16_t zerosBcd, uint8_t exp) {
  return MONSTER_NIBBLE != 0xFF ? MONSTER_NIBBLE : checksumFor(numByte, hpBcd, zerosBcd, exp);
}

/* Given NUM/HP and a desired (Level, EXP) pair, work out the raw wire
 * zeros/EXP/nibble that produce them. The experience counter spans two
 * fields (PROTOCOL.md §3.5): displayedEXP = 10*decodeBcd3(zeros) + EXP/8,
 * so split targetExp = 10*Z + R: Z -> zeros as 3-digit BCD, R -> EXP's
 * top 4 bits. EXP's low 3 bits don't affect EXP/8, only the checksum,
 * and sweeping them walks the checksum through all 8 residues
 * (expTerm = low3 - R is 8 consecutive integers, always a complete
 * residue system mod 8), so any Level is reachable without perturbing
 * the displayed experience. Level = (nibble>>2)+1: the low 3 bits are
 * pinned by checksumFor(), only the top bit is free (level 3 is level
 * 1's "+8 twin"). Level 4 is wire-acceptable but not a real game value,
 * so it's refused here. */
static void solveLevelExp(uint8_t numByte, uint8_t hpBcd, uint8_t level, uint16_t targetExp,
                           uint16_t &outZeros, uint8_t &outExp, uint8_t &outNibble) {
  if (level < 1 || level > 3) {
    Serial.println(F("TARGET_LEVEL must be 1..3 (4 is an invalid glitch value) - halting"));
    while (true) {}
  }
  if (targetExp > 9999) {
    Serial.println(F("TARGET_EXP must be 0..9999 - halting"));
    while (true) {}
  }
  uint16_t Z = targetExp / 10;   // -> zeros, 3-digit BCD
  uint8_t  R = targetExp % 10;   // -> EXP's top 4 bits (EXP>>3)
  outZeros = toBcd3(Z);
  uint8_t band   = (level == 2) ? 1 : 0;  // level 1/3 -> band 0, level 2 -> band 1
  uint8_t topBit = (level == 3) ? 1 : 0;  // level 3 is level 1's "+8 twin"
  for (uint8_t low3 = 0; low3 < 8; low3++) {
    uint8_t exp = (R << 3) | low3;
    uint8_t c = checksumFor(numByte, hpBcd, outZeros, exp);
    if ((c >> 2) == band) {
      outExp    = exp;
      outNibble = c | (topBit << 3);
      return;
    }
  }
  Serial.println(F("solveLevelExp: no candidate found - this should be impossible - halting"));
  while (true) {}
}

static void buildTxPayload() {
  uint8_t hp  = toBcd(MONSTER_HP);
  uint8_t nib = nibbleFor(MONSTER_NUM - 1, hp, MONSTER_ZEROS, MONSTER_EXP);
  uint8_t i = 0;
  txBits[i++] = 0;                                            // start
  txBits[i++] = 1; txBits[i++] = 1; txBits[i++] = 1;          // sync '111'
  for (int8_t b = 7; b >= 0; b--) txBits[i++] = ((MONSTER_NUM - 1) >> b) & 1;
  for (int8_t b = 3; b >= 0; b--) txBits[i++] = (nib >> b) & 1;
  for (int8_t b = 7; b >= 0; b--) txBits[i++] = (hp >> b) & 1;
  for (int8_t b = 7; b >= 0; b--) txBits[i++] = (hp >> b) & 1;
  for (int8_t b = 11; b >= 0; b--) txBits[i++] = (MONSTER_ZEROS >> b) & 1;  // real EXP, 3-digit BCD, x10
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
  uint8_t want = checksumFor(rxField(4, 12), rxField(16, 24), rxField(32, 44), rxField(44, 51));
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
                MONSTER_ZEROS, MONSTER_EXP, MONSTER_NIBBLE);
  Serial.print(F("solved for target level="));
  Serial.print(TARGET_LEVEL);
  Serial.print(F(" EXP="));
  Serial.print(TARGET_EXP);
  Serial.print(F(" -> zeros=0x"));
  Serial.print(MONSTER_ZEROS, HEX);
  Serial.print(F(" smallExp="));
  Serial.print(MONSTER_EXP);
  Serial.print(F(" (monster menu should show EXP "));
  Serial.print(fromBcd3(MONSTER_ZEROS) * 10 + MONSTER_EXP / 8);
  Serial.print(F(") nibble="));
  Serial.println(MONSTER_NIBBLE);
#endif
  buildTxPayload();
  Serial.println(F("Skannerz slave emulator"));
  Serial.print(F("sending monster num="));
  Serial.print(MONSTER_NUM);
  Serial.print(F(" nibble="));
  Serial.print(nibbleFor(MONSTER_NUM - 1, toBcd(MONSTER_HP), MONSTER_ZEROS, MONSTER_EXP));
  Serial.print(F(" HP="));
  Serial.print(MONSTER_HP);
  Serial.print(F(" zeros(realEXP/10 BCD)=0x"));
  Serial.print(MONSTER_ZEROS, HEX);
  Serial.print(F(" smallExp="));
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
    if (state == COMPLETE && timeoutsInARow >= LINK_LOST_TIMEOUTS) {
      Serial.println(F("=== trade complete, session closed ==="));
      previewEventSent = false;
      toState(WAIT_LINK, F("WAIT_LINK"));
    } else if (state != WAIT_LINK && timeoutsInARow >= LINK_LOST_TIMEOUTS) {
      Serial.println(F("link lost, resetting"));
      previewEventSent = false;
      toState(WAIT_LINK, F("WAIT_LINK"));
    }
    return;
  }
  timeoutsInARow = 0;

  // 0x3B = master cancel/session-abort (PROTOCOL.md §4/§7). Confirmed by
  // testing: replying to it (even a plain 0x34 ack) makes the master loop
  // resending it instead of resolving on its own - so, like any other
  // byte outside the known vocabulary, send NOTHING back and just let it
  // self-resolve (it already does, via its own retry/timeout). Only the
  // logging differs: log each distinct byte once, not on every repeat -
  // the master resends these at poll cadence, and re-printing an
  // unchanged value adds no information.
  if (f != 0x32 && f != 0x2B && f != 0x39) {
    if ((uint8_t)f != lastLoggedByte) {
      if (f == 0x3B) {
        Serial.println(F("<< master cancel (0x3B)"));
      } else {
        Serial.print(F("?? master sent 0x"));
        Serial.print((uint8_t)f, HEX);
        Serial.println(evt ? F(" (event frame)") : F(""));
      }
      lastLoggedByte = f;
    }
  } else {
    lastLoggedByte = 0xFF;  // back to normal polling - a later repeat is a new event
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
#if HOLD_AT_SELECT
        sendFrame(0x34);                         // never advance - hold the window open
        break;
#endif
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
