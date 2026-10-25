# WIRING.md — wiring the five acoustic beacons

This document is for people who have never soldered, crimped, or wired anything.
It identifies every part physically, shows exactly where every wire goes, and ends
with the "if no sound" checklist. Follow it top to bottom. It implements the wiring
section of [LOCATOR_BRIEF.md](../LOCATOR_BRIEF.md) (§3 hardware catalog, §4 pin maps,
§5 wiring) using only parts from the hackathon hardware desk.

Everything here serves one goal: five buzzers around a 3.5 × 3.5 m demo space that
chirp in turn on a 300 ms cycle (§4.4), loud enough for the iPhone's microphone to
hear each one from across the room.

---

## 0. What you are building (one screenful)

One ESP32 dev board drives five small passive buzzers placed around the room.
Each buzzer is switched on and off hundreds of times per chirp by a transistor,
because a phone microphone needs a *frequency-swept* tone (2.0–4.5 kHz, §4.3) —
a fixed-tone "active buzzer" cannot do this and is not on our parts list (§3).
Only one buzzer sounds at a time (§5), which keeps the wiring and power simple.

Each beacon is wired the same way, five times over. Learn one, and you know all five.

**Estimated time:** 1–2 hours for all five beacons once you've done the first.

**Safety:** everything here runs from a 5 V USB charger — no mains voltage anywhere.
The only sharp object is the desk scissors/cable cutter, and an Ethernet cable may be
cut **only if the desk allows it** (Phase A fact 5, §3).

---

## 1. The parts list (and where each one comes from)

All counts include one spare of the small parts. Everything below is in the hardware
desk catalog (§3) — nothing else is needed:

| # | Part | Count | Physically, it looks like… |
|---|------|-------|-----------------------------|
| 1 | ESP32 dev board | 1 | A credit-card-sized PCB with a **silver metal can** in the middle, a USB port on one short edge, two small push buttons (**EN** and **BOOT**), and two rows of header pins. |
| 2 | Bare passive buzzer | 5 (+spares) | A small **black plastic cylinder**, roughly thumb-sized, with a round **sound hole** on the top face. Two legs. One leg is marked **+** (printed on the top, or the longer/marked leg). If it were a flat brass disc it would be a piezo disc — those are *not* on our desk (§3); these are **magnetic** buzzers with a coil inside (confirm with the human: Phase A fact 2). |
| 3 | Small passive buzzer module | (alternative) | A tiny PCB with a buzzer on it and **2 or 3 header pins**. 3-pin versions are labelled something like **S/I/O**, **+ / VCC**, **− / GND** (read the silkscreen). Some have an on-board transistor and are *active-low* — the firmware's `invert` command handles that (§4.5, and step 6 below). Confirm pin count and labels with the human (Phase A fact 3). |
| 4 | NPN transistor **S8050** or **PN2222** | 5 (+spares) | A **half-cylinder** black plastic package (called TO-92) with three legs and the part number printed on the flat face. The desk stocks ~70 S8050 and ~84 PN2222 (§3). |
| 5 | Resistor **1 kΩ** | 5 (+spares) | A small tan/blue cylinder with **brown-black-red** bands (plus a gold/silver tolerance band at one end). |
| 6 | Resistor **100 Ω** | 5 (+spares) | Bands **brown-black-brown**. |
| 7 | Resistor **10 Ω** | 5 (+spares) | Bands **brown-black-black**. |
| 8 | Diode **1N4007** | 5 (+spares) | A black cylinder, fatter than a resistor, with a **white or grey stripe at one end**. The striped end is the **cathode**. |
| 9 | Breadboard | 1 | The white plastic block from the Arduino UNO R3 kit (§3 — the standalone breadboard is unavailable). Rows of holes; a long **+ rail** and **− rail** down each side. The UNO board itself is not used. |
| 10 | Dupont jumpers | a handful | Ribbon-style wires with a rectangular plastic connector at each end (male-to-male and female-to-male both exist on the desk). |
| 11 | Ethernet cable | 1–2 | The blue/grey network cable. May be cut **only if the desk allows** (§5; Phase A fact 5). |
| 12 | USB charger block + USB cable | 1 | The wall-wart USB power supply, plus the cable that plugs into the ESP32. |

Not usable, so you can leave them alone if you see them: the **active buzzer** (fixed
tone — it cannot chirp, §3) and the **HC-SR04** ultrasonic sensor (40 kHz — above what
the iPhone can record, §3). The DHT11 temperature module is optional (it would refine
the speed of sound, §6.1) and is not wired in this guide.

Tape, labels, and scissors come from the desk or your own kit.

---

## 2. Step 1 — identify your ESP32 (WROOM or WROVER?)

Read the marking on the **silver metal can** in the middle of the board (Phase A fact 1):

- **`ESP32-WROOM-32`** → use the **WROOM pin map** (default):

  | Beacon | Pin | | Beacon | Pin |
  |---|---|---|---|---|
  | B1 | GPIO 16 | | B4 | GPIO 19 |
  | B2 | GPIO 17 | | B5 | GPIO 21 |
  | B3 | GPIO 18 | | | |

- **`ESP32-WROVER`** → GPIO 16 and 17 are **unavailable** (the can's PSRAM uses them,
  §4.2). Use the **WROVER pin map** instead: B1 = 25, B2 = 26, B3 = 27, B4 = 32, B5 = 33.

The pin map can also be switched at runtime with the serial command `pins wrover`
or `pins wroom` (§4.5) — it is saved in NVS. **After flashing, run `status` in the
serial monitor and read the active pin map back before you wire anything.** Wire the
beacons to the pins of the *active* map, and write the map on a piece of tape on the
board so nobody wires to the wrong column later.

The on-board LED sits on **GPIO 2** and blinks once per cycle as a heartbeat (§4.2) —
you will use it as the first "is it alive?" signal in [BRINGUP.md](BRINGUP.md) step B1.

---

## 3. Step 2 — read the transistor's legs

Each transistor has three legs and the leg order **varies by manufacturer** (§5), so
do this once, carefully, for the bag you actually have (Phase A fact 4):

1. **Read the part number** printed on the flat face: `S8050` or `PN2222` (some
   manufacturers add letters, e.g. `PN2222A` or `SS8050` — same part family for our
   purpose).
2. **Hold it flat-face toward you, legs down.** That is the convention used below.
3. **Look up that exact part's datasheet pinout** (footnotes 1 and 2 below). For both
   desk parts, the datasheets we checked show the common order **E-B-C**: pin 1 =
   **E**mitter, pin 2 = **B**ase, pin 3 = **C**ollector, flat face toward you, legs
   down. Treat this as *likely* and verify against your bag's datasheet — that is the
   point of this step.
4. **If there is no sound later, swap the legs** per the "if no sound" checklist
   (§11) — a mis-inserted TO-92 with the legs in the wrong order is the single most
   common beginner fault, and the standard circuit is forgiving of a brief trial.

For the curious, the job of this part: a tiny current into the **base** (fed by the
GPIO through the 1 kΩ resistor) lets a much larger current flow from **collector** to
**emitter**. The GPIO's 3.3 V signal only *switches* the transistor; the buzzer's
actual power comes from the 5 V rail. Both desk parts switch far more current than a
buzzer coil needs (footnotes 1–2).

---

## 4. Step 3 — read the resistors and the diode

Resistor bands are read with the part horizontal, gold/silver band on the right
(the tolerance band never goes first):

| Resistor | Bands | Meaning |
|---|---|---|
| 1 kΩ | brown · black · red | 1-0-×100 = 1000 Ω |
| 100 Ω | brown · black · brown | 1-0-×10 = 100 Ω |
| 10 Ω | brown · black · black | 1-0-×1 = 10 Ω |

The **1N4007 diode** is direction-sensitive: the **striped end is the cathode**, and
in our circuit the stripe always points at the **+5 V side of the buzzer** (§5). It
gives the buzzer coil's inductive kick a safe path to discharge. Installed backwards
it becomes a near-short from the 5 V rail through the transistor while a chirp plays:
the buzzer goes quiet and the diode and 10 Ω resistor get hot. Symptom of that: a
quiet beep plus warm parts — flip the diode.

---

## 5. Step 4 — build the standard beacon circuit (×5)

This is the circuit from §5 of the brief. It is built on the **breadboard next to
the ESP32**; only the buzzer sits far away (step 8 shows how the wire run reaches it).

```
ESP32 GPIO ──[1 kΩ]──► NPN BASE            (S8050 or PN2222)
                       NPN EMITTER ──► ESP32 GND
ESP32 5V/VIN ──[10 Ω]──► buzzer (+) ── buzzer (−) ──► NPN COLLECTOR
1N4007 across the buzzer: striped end (cathode) to the +5V side
```

For one beacon (B1, GPIO 16 on the WROOM map), on the breadboard:

1. Plug the transistor into three separate breadboard rows, flat face toward the
   aisle so the leg order you established in step 3 stays true.
2. **Base resistor:** one end of a 1 kΩ resistor into the transistor's **base** row;
   the other end goes to a Dupont jumper that reaches the ESP32 pin for this beacon
   (GPIO 16 for B1).
3. **Emitter:** a jumper from the transistor's **emitter** row to the breadboard's
   **− rail**, and the − rail to any ESP32 **GND** pin.
4. **Buzzer supply:** a jumper from ESP32 **5V/VIN** to the + rail; a **10 Ω**
   resistor from the + rail toward the wire run; its far end is the beacon's **5 V
   feed**.
5. **Buzzer return:** the wire coming back from the far buzzer's **(−)** leg lands on
   the transistor's **collector** row.
6. **Diode:** across the buzzer at the far end — stripe (cathode) to the buzzer's
   **(+)** leg, other end to the buzzer's **(−)** leg.

The current path when the firmware chirps: **5 V → 10 Ω → buzzer coil → return wire
→ collector → emitter → GND**, switched on/off by the GPIO through the 1 kΩ base
resistor. At idle (`stop`, or between chirps) every beacon pin sits **LOW**
(HIGH only when that beacon's `invert` flag is set, §4.2) so no buzzer is ever fed
a steady DC level — that is deliberate (§5: "never leave a buzzer driven with DC").

Repeat this block five times for B1–B5, each on its own GPIO per the pin map in
step 2. Five circuits take about half a breadboard.

---

## 6. Variants

### 6a. Direct-drive test circuit (build this one FIRST)

Before committing to five transistor circuits, wire **one** beacon the simple way —
no transistor, no diode, no 10 Ω (§5):

```
ESP32 GPIO 16 ──[100 Ω]──► buzzer (+)
buzzer (−) ──► ESP32 GND
```

The GPIO drives the buzzer directly through 100 Ω. It is quieter than the transistor
circuit, but if the phone detects it at 4 m in the hall (Phase B step B4), **the team
may skip the transistors entirely** (§5) — a real simplification. Run the B3/B4 checks
with this circuit before building the other four.

### 6b. The 3-pin buzzer module

If the desk's "small passive buzzer module" has three pins (Phase A fact 3), it wires
directly to the ESP32 — **no transistor, no resistors, no diode** (§5):

| Module pin | Goes to |
|---|---|
| **S** / **I** / **O** (signal) | the beacon's GPIO |
| **+** / **VCC** | ESP32 **3.3V** (not 5 V) |
| **−** / **GND** | ESP32 **GND** |

Some of these modules contain an on-board transistor and are **active-low**: they
sound *inverted* — silent while the pin is driven, or clicking at idle. The firmware
has a per-beacon fix: run `invert <n> 1` (and `save`), which also flips the pin's
idle level (§4.2, §4.5). If it behaves like a normal 2-terminal buzzer, wire it like
the bare buzzer instead (through the standard circuit).

### 6c. Why there is no PNP or MOSFET option here

The brief's drive circuit is an **NPN low-side switch** (§5), and the desk stocks NPN
parts only — S8050 and PN2222 (§3). There are **no PNP transistors and no MOSFETs in
the hardware catalog**, so neither variant is buildable from the desk this weekend;
Appendix A of the brief fixes the parts list. If a logic-level N-channel MOSFET
ever does become available, it substitutes directly (gate ← 1 kΩ ← GPIO, source →
GND, buzzer + 10 Ω from 5 V to drain, same 1N4007 across the buzzer) — but do not
hunt for one; the NPN circuit meets the demo's needs.

---

## 7. Step 5 — power

- Power the ESP32 from a **USB charger block** (preferred — the board then moves
  freely) or the **Mac's USB port** (§5). The board's 5 V/VIN pin feeds the buzzer
  rail through the five 10 Ω resistors.
- Load is small by design: only **one** buzzer sounds at a time (§5), so the peak
  draw is the ESP32 board plus one buzzer coil — any USB charger covers it. There is
  no scenario in this demo where five buzzers sound together.
- Never feed the buzzer rail from the ESP32's **3.3V** pin in the standard circuit —
  the beep would be much quieter. (The 3-pin *module* in §6b is the exception; it
  asks for 3.3 V on its own VCC pin.)
- The firmware auto-starts 2 s after power-up (§4.5), so a plain USB charger block
  runs the whole show with no computer attached — that is how it runs at the demo.

---

## 8. Step 6 — the wire runs (2–3 m to each beacon)

The buzzers sit at the room's edges; the ESP32 sits at the mat's edge. That is a
2–3 m run per beacon, and the brief prefers **one cut Ethernet cable** for all of
them (§5): a network cable is really eight neatly-twisted wires in one jacket.

**Ask the desk before cutting** (Phase A fact 5). If the desk says no, fall back to
chained Dupont jumpers with **every joint taped** (§5).

Inside the jacket: four colour-coded twisted pairs — **blue/blue-white**,
**orange/orange-white**, **green/green-white**, **brown/brown-white**.

- **One twisted pair per beacon; four beacons per cable** (§5):

  | Pair | Beacon | Wire A (to buzzer +) | Wire B (buzzer − return) |
  |---|---|---|---|
  | blue | B1 | 5 V feed (after the 10 Ω) | to collector |
  | orange | B2 | 5 V feed (after the 10 Ω) | to collector |
  | green | B3 | 5 V feed (after the 10 Ω) | to collector |
  | brown | B4 | 5 V feed (after the 10 Ω) | to collector |

- With this split, **all electronics stay at the ESP32 end** (the 1 kΩ, 10 Ω and
  transistor live on the breadboard) and the far end is just the buzzer plus its
  diode: wire A to (+), wire B to (−), diode across the two legs with the stripe on
  the wire-A side. That is the simplest possible thing to tape to a wall.
- **B5 is the fifth beacon** — run it on a second cable (any pair) or a chained-Dupont
  run with taped joints (§5).
- **Label both ends of every wire: B1…B5** (§5). Masking tape + marker. "Which wire is
  B3 again?" is how a 20-minute fault becomes a two-hour fault.
- Keep the twisted pairs twisted right up to the connection points — the twist is
  what keeps the chirp from bleeding into the neighbouring beacon's pair.
- **Wires never cross the walking area** — the user is blindfolded (§1, §5). Route
  along table edges and walls.

---

## 9. Step 7 — mounting

Placeholder geometry (§2.2 — real values come from tape-measuring in Phase C, step C2):

| Beacon | Position [x, y, z] m | Where that is | Height |
|---|---|---|---|
| B1 | [-1.5, 1.5, 1.8] | front-left | high (1.8 m) |
| B2 | [1.5, 1.5, 0.3] | front-right | low (0.3 m) |
| B3 | [1.5, -1.5, 1.8] | back-right | high (1.8 m) |
| B4 | [-1.5, -1.5, 0.3] | back-left | low (0.3 m) |
| B5 | [-1.8, 0.0, 1.0] | left side | mid (1.0 m) |

- The **buzzer's sound opening faces the room's center** (§5) — the round hole on the
  black cylinder points at the mat.
- The mixed heights (two high, two low, one mid) are deliberate: they make the 3D
  solve possible (§2.2). The app warns if all beacon heights land within 0.5 m of
  each other (§8.3) — if it does, remount before measuring.
- **Tape firmly so nothing shifts after measuring** (§5). A beacon that moves 5 cm
  after C2 poisons every later measurement.
- Wires run along table edges and walls, never across the walking area (§1, §5).

---

## 10. Step 8 — label and record

1. Label both ends of every wire run (B1…B5), and label each buzzer itself.
2. After measuring in Phase C, write the measured position on the tape next to each
   beacon — the paper trail makes re-mounting after a fall possible without re-measuring
   the whole room.

---

## 11. "If no sound" checklist

Work down the list in order — each step is a 30-second check (§5):

1. **Is the ESP32 running?** Serial monitor shows the banner and `RUNNING`, and the
   on-board LED blinks once per cycle (§4.5, §4.2). If not: [BRINGUP.md](BRINGUP.md) B1.
2. **Does `test` print?** Run `test` — it prints `>> B1 chirp` before each chirp
   (§4.5). If nothing prints, you have a firmware/serial problem, not a wiring problem.
3. **Is there 5 V?** The wire feeding the buzzer's (+) leg must come from the
   5V/VIN rail — check it is not accidentally on the 3.3V pin, and that the charger
   block is actually powered.
4. **Are the transistor legs right?** Flat face toward you, legs down; datasheet
   order (E-B-C for both desk parts, footnotes below). If in doubt, swap the
   transistor end-for-end and retry — a mis-ordered TO-92 is the most common fault.
5. **Is the diode oriented correctly?** Stripe (cathode) to the **+5 V side** of the
   buzzer (§5).
6. **Is the invert flag right?** For 3-pin modules that sound inverted: run
   `invert <n> 1` then `save` (§4.5). Symptoms: silent while beeping, or clicking
   at idle.
7. **Try direct drive.** Rewire that one beacon per §6a (GPIO → 100 Ω → buzzer +,
   buzzer − → GND) and run `beep <n>`. If the bare buzzer is silent even here, the
   buzzer itself is dead or it is a fixed-tone active buzzer — swap in a spare and
   check the part (§3).
8. Still nothing? Unmarked buzzer polarity: in the direct-drive circuit, flip the
   buzzer's two legs — magnetic buzzers are usually louder one way and silent-or-quiet
   the other.

When the sound exists but the phone can't hear it at distance, that is not a wiring
fault — go to [BRINGUP.md](BRINGUP.md) B4 and the fallback ladder (brief §11):
transistor circuit → remove the 10 Ω resistors → aim the buzzers at the center →
`len 20` → lower the band.

---

## Footnotes

1. S8050 datasheet (MCC, TO-92): pin order 1=E, 2=B, 3=C, 500 mA max collector
   current — <https://www.mccsemi.com/pdf/products/S8050(TO-92)-V1.pdf>
2. PN2222A datasheet (ON Semiconductor/Fairchild, TO-92): "EBC" lead order, 500 mA-class
   switching part — <https://www.onsemi.com/pub/Collateral/PN2222A-D.PDF>
   (Both verified 2026-10-24; the brief still requires checking the bag you actually
   have, because manufacturers differ — §5.)
