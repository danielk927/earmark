# Earmark: path from prototype to production

Earmark is a hackathon prototype built at Cal Hacks 13.0 (October 23-25, 2026).
This document is the plan for turning it into something a blind or low-vision person can rely on at home: what the hardware costs, how it moves to iPhone, where the cloud parts run, how many households it can serve, how data is protected and deleted, and how we would roll it out.
Prices are estimates from public listings read on 2026-10-24 and change often; every one has a link.
Anything marked **estimate** or **proposal** is our planning number, not a measurement.

## 0. Where the prototype stands

| Part | Today (prototype) | Production target |
|---|---|---|
| Detection | Simulator plus `nfc_serial` and `ble_fobs` adapters, tested against fake serial ports and fake Bluetooth; no real reader or fob has run yet | Reader boards installed in the home, fobs on roaming items |
| Hub | Python on the demo Mac: debounce, state engine, local WebSocket bus, durable offline queue to Convex (`services/hub/README.md`) | Same code on a small always-on box in the home (section 2) |
| Voice concierge | Python on the demo Mac: Cartesia speech, Claude tool choice with a keyword fallback, spoken memory of where items were put, Moss retrieval with fuzzy fallback (`services/concierge/README.md`) | Same, on the home box |
| Spatial audio app | macOS app with AirPods head tracking (in progress) | iPhone app (section 3) |
| Walking guidance (UWB) | Four iPhones: three fixed anchors ("UWB Reader/Emitter 1/2/3") and one handheld wearer; the hub's solver and freeze run against a simulator; the iPhone app has not run on a phone yet (`docs/project/UWB-PRD.md`, `docs/project/STATUS.md`) | Small dedicated UWB anchor modules in the room; the user's own iPhone is the wearer (section 3.1) |
| Backend | Convex: tables, HTTP actions with shared secrets, adherence rules with tests, crons, photo labeling (`convex/README.md`) | Convex with user auth, household scoping, and roles (section 5) |
| Caregiver dashboard and memory agent | In progress | Azure Static Web Apps and Azure Container Apps (section 4) |
| Users | None yet; see `docs/project/CUSTOMER.md` | Pilot households through a blindness organization (section 10) |

## 1. Hardware bill of materials per home (estimate)

### 1.1 Parts

| Part | Role | Price seen (2026-10-24) | Source |
|---|---|---|---|
| MFRC522 ("RC522") reader module | Cheapest reader per spot; SPI; read range a few centimeters | US $1.25 (one marketplace listing) | https://www.hotmcu.com/mifare-1356mhz-rc522-rfid-card-reader-module-p-84.html |
| PN532 reader module | Common reader per spot; SPI, I2C, or UART; best library support | $15.00 (Elechouse purple), $23.90 (Elechouse V4), $39.95 (Adafruit breakout) | https://www.elechouse.com/product/pn532-nfc-rfid-module-purple-version/, https://www.elechouse.com/product/pn532-nfc-rfid-module-v4/, https://www.adafruit.com/product/364 |
| NXP PN7150 reader board | Higher-end reader with integrated NFC firmware | $34.95 (MikroE NFC 2 Click at SparkFun) | https://www.sparkfun.com/mikroe-nfc-2-click-wrl-18779.html |
| ESP32-class microcontroller | One per reader board; polls up to about 8 readers on one SPI bus, each with its own chip-select pin | $15.00 (Espressif dev board), $15.95 (ESP32-S3-DevKitC-1), $19.95 (Adafruit HUZZAH32), all at Adafruit | https://www.adafruit.com/product/3269, https://www.adafruit.com/product/5312, https://www.adafruit.com/product/3405 |
| NTAG213 NFC stickers | One per tagged item | $0.24 to $0.77 each depending on quantity (GoToTags); $2.95 single (Adafruit) | https://store.gototags.com/nfc-sticker-ntag213-50-mm-circle-matrix-on/, https://www.adafruit.com/product/4032 |
| BLE key-finder fob ("iTag" style) | One per roaming item (keys, wallet); Immediate Alert service so the hub can make it chirp | US $1.11 to $1.32 (wholesale listing); about €5 retail | https://www.plusbuyer.com/itag-smart-wireless-bluetooth-v40-tracker-finder-key-anti-lost-alarm-locator-tracker-black-itag-anti-lost-alarm-p-43881.html, https://motivs.eu/en/location-trackers-gadgets/bluetooth-atslegu-mekletajs-keyfinder-itag-melns |
| Home hub | Runs the hub and concierge; Raspberry Pi 5 has "Dual-band 802.11ac Wi-Fi" and "Bluetooth 5.0 / Bluetooth Low Energy (BLE)" | $77.50 for Raspberry Pi 5 2GB after the 1 October 2026 memory-driven price increase | https://www.raspberrypi.com/news/price-increases-for-2gb-raspberry-pi-4-and-raspberry-pi-5/, https://www.raspberrypi.com/products/raspberry-pi-5/ |
| Enclosures, spot pads, cables, power supplies | Thin pad per spot, one box per reader board and hub | **Estimate:** $20 to $60 per home (not sourced) | - |

Not included, because the user brings them: an iPhone and head-tracking headphones (section 3).
Not included yet: UWB anchors for walking guidance, which are not priced (section 3.1).
Without supported headphones Earmark falls back to stereo panning and spoken clock directions, then speech only.

### 1.2 A starter home (estimate)

Assumed setup: 8 home spots on two reader boards (a kitchen counter and a medication shelf), 30 tagged items, 2 fobs, 1 hub.

| Line | Low (cheapest parts) | High (higher-end parts) |
|---|---|---|
| 8 readers | 8 x $1.25 = $10 | 8 x $34.95 = $280 |
| 2 microcontrollers | 2 x $15.00 = $30 | 2 x $19.95 = $40 |
| 30 NFC stickers | 30 x $0.24 = $7 | 30 x $2.95 = $89 |
| 2 fobs | 2 x $1.11 = $2 | 2 x about $6 = $12 |
| Hub | $77.50 | $77.50 |
| Enclosures, pads, power (estimate) | $20 | $60 |
| **Total per home (estimate)** | **about $147** | **about $559** |

Hardware is not the expensive part; installation time and support are (section 10 measures both).
At volume, one reader chip switching between several spot antennas would cut reader cost further; that is a design idea we have not tested.

### 1.3 Hardware risks to test in the pilot

- Metal lids and tins detune NFC.
  Put the tag on the bottom of the jar so nothing metal sits between it and the reader under the spot; test on-metal tags for metal tins.
- Read range is short (a few centimeters for RC522-class modules), which is what we want: a jar on the next spot must not be read.
  Pilot test: 1,000 scripted lifts and placements with zero cross-spot reads.
- Firmware for the reader boards is not written yet (`BUILD_BRIEF.md` 5.B); the line protocol (`SPOT <n> TAG <uid>`, `SPOT <n> EMPTY`) is already parsed and tested in the hub.

## 2. The home hub

The hub and concierge are plain Python 3.12 services, so the production plan is to run the same code on a Raspberry Pi-class box.
The Mac-specific parts are small: serial port names, Bluetooth permission prompts, and CoreBluetooth device IDs, which only work on the Mac that scanned them (`docs/sponsors/vendor-notes/bleak.md` 2).
bleak, the Bluetooth library the hub uses, also has a Linux backend.
Changes needed:

| Change | Why |
|---|---|
| Reader boards connect over Wi-Fi as well as USB serial | Readers in two rooms cannot share one USB cable |
| The bus listens on the home network, not only `127.0.0.1`, with TLS and a per-device pairing token | The iPhone app is a separate device |
| Run under a service manager with automatic restart and a watchdog | Unattended operation |
| Heartbeat to Convex; the dashboard shows "hub offline since 9:14 PM" | Caregivers learn about outages without asking the user |
| Signed over-the-air updates with automatic rollback | Fixes without a home visit |

## 3. The iPhone port

The Mac app was built behind two protocols (`HeadTracking` and `SpatialRenderer`, `BUILD_BRIEF.md` 5.E) so the same audio code can move to iPhone.
Every framework it uses exists on iOS:

| Framework | Used for | iOS availability | Source |
|---|---|---|---|
| `CMHeadphoneMotionManager` | AirPods head yaw and pitch | iOS 14.0+ (macOS 14.0+) | https://developer.apple.com/documentation/coremotion/cmheadphonemotionmanager |
| `AVAudioEngine` with `AVAudioEnvironmentNode` | HRTF spatial ping fixed in the room | iOS 8.0+ | https://developer.apple.com/documentation/avfaudio/avaudioenvironmentnode |
| `SFSpeechRecognizer` | Backup speech recognition | iOS 10.0+; `supportsOnDeviceRecognition` iOS 13.0+ | https://developer.apple.com/documentation/speech/sfspeechrecognizer |
| `SpeechAnalyzer` (optional upgrade) | Newer on-device speech API | iOS 26.0+ | https://developer.apple.com/documentation/speech/speechanalyzer |

What changes on iPhone:
- **Audio routing gets easier.**
  macOS has no `AVAudioSession`, so the Mac app switches the system default input to the built-in mic to keep AirPods in high-quality stereo (`docs/project/STATUS.md`, finding 7).
  On iOS, use the `playAndRecord` category with `allowBluetoothA2DP` and without the hands-free option, because "when a single device supports both the Hands-Free Profile (HFP) and A2DP, the system gives hands-free ports a higher priority".
  Source: https://developer.apple.com/documentation/avfaudio/avaudiosession/categoryoptions-swift.struct/allowbluetootha2dp
- **Route changes and interruptions** (a phone call, AirPods removed) arrive as `AVAudioSession` notifications instead of the polling the Mac needs.
- **System spatial audio:** iOS 18+ has `AVGameBypassSystemSpatialAudio` to ignore the Control Center spatial-audio toggle, which macOS lacks.
  Source: https://developer.apple.com/documentation/bundleresources/information-property-list/avgamebypasssystemspatialaudio
- **Background:** guidance and listening continue with the screen locked using the `audio` background mode.
  Source: https://developer.apple.com/documentation/bundleresources/information-property-list/uibackgroundmodes
- **Permissions:** `NSMotionUsageDescription` (iOS 7.0+), microphone and speech recognition descriptions, and `NSLocalNetworkUsageDescription` (iOS 14.0+) to reach the home hub.
  Sources: https://developer.apple.com/documentation/bundleresources/information-property-list/nsmotionusagedescription, https://developer.apple.com/documentation/bundleresources/information-property-list/nslocalnetworkusagedescription
- **UI:** the map becomes a VoiceOver-first SwiftUI screen; the primary user still never has to touch it, since every job works by voice.
- **Hardware coverage:** head tracking needs supported headphones; the fallback ladder in `docs/project/ARCHITECTURE.md` covers everyone else.

### 3.1 Walking guidance: anchors and the wearer

Tonight the anchors are iPhones because they were the UWB hardware we had.
That does not work in a home: each anchor phone needs its screen on, the app in front, auto-lock off, and a charger, because Nearby Interaction suspends a session when its app goes to the background (`docs/sponsors/vendor-notes/apple-nearby-interaction.md`).
And nobody should buy three iPhones to find the sugar.

Production plan (**proposal**):
- **Anchors are small dedicated UWB modules**, for example Qorvo's Apple-interoperable modules, mounted on a wall or shelf and powered by USB or mains.
  Apple's guidance to accessory makers: "Implement the Nearby Interaction accessory protocol with a Nearby Interaction-enabled UWB chipset to make accessories that interact with supported Apple products. Contact your UWB chipset vendor to confirm feature support." (https://developer.apple.com/nearby-interaction/)
- **The wearer is the user's own iPhone**, running the iPhone app from section 3, held or carried as they walk. It ranges to each anchor and sends the distances to the home hub, exactly like tonight's wearer app.
- **Background use.** Apple: "In iOS 16, third-party UWB accessories paired to the device through Bluetooth can interact with your app while it's in the background." The app pairs to each anchor over Bluetooth and starts the session with `NINearbyAccessoryConfiguration(accessoryData:bluetoothPeerIdentifier:)` (iOS 16+). The plain `NINearbyAccessoryConfiguration(data:)` is iOS 15+. (https://developer.apple.com/documentation/nearbyinteraction/ninearbyaccessoryconfiguration)
- **Setup.** The installer measures each anchor from the origin mark with a tape measure, the same way we do tonight (Mac app Calibrate screen or `scripts/calibrate.py`), and runs the five-mark position check.

What changes in the code:
- The iPhone app swaps phone-to-phone sessions (`NINearbyPeerConfiguration`) for accessory sessions. The accessory sends its configuration data over the Bluetooth link, so the hub's token relay is no longer needed for the anchors.
- Nothing else changes. The hub's solver, freeze, and NFC re-anchor, the Mac/iPhone audio, the concierge, and the dashboard all consume `uwb_range` and `listener_pose`, never the anchor hardware.

Not verified yet (vendor sites were unreachable from our build environment on 2026-10-25):
- Which Qorvo module or development kit to use, its price, size, and power draw, and whether it supports Apple's current interoperability specification. Anchors are therefore not in the bill of materials in section 1.
- Whether a shipping anchor needs Apple's MFi program. Apple's Nearby Interaction page links MFi but does not say.

Risks to test in the pilot:
- How many accessory sessions one iPhone sustains at once. Apple only says the limit "varies across device type and platform" (`NIError.activeSessionsLimitExceeded`). Tonight's round-robin fallback carries over.
- Battery drain on the user's iPhone while walking guidance runs.
- A phone in a pocket or bag: tonight the phone is held at the chest (`docs/project/UWB-PRD.md` section 2), and a pocket is untested.
- Anchor placement in real kitchens: metal appliances and the user's own body block the signal; the hub flags and drops a blocked anchor, but rooms need at least three anchors with a clear view of the walking area.

## 4. Cloud hosting on Azure

Convex stays the database.
Azure hosts the two cloud services; commands and constraints are in `docs/sponsors/vendor-notes/azure.md`.

| Part | Hosting | Pilot setting | Production setting | Cost (estimate) |
|---|---|---|---|---|
| Caregiver dashboard (static React build) | Azure Static Web Apps | Free plan: 100 GB bandwidth per month, no SLA | Standard plan, which adds an SLA, custom auth providers, and private endpoints | $0 on Free |
| Memory agent (Fetch.ai uAgent) | Azure Container Apps, Consumption plan, no ingress | 0.25 vCPU / 0.5 GiB, `--min-replicas 1 --max-replicas 1` | One replica per agent identity; more households scale out with KEDA rules | About $4 to $14 per month per always-on replica after the free grant (East US list prices) |
| Secrets | Container Apps secrets referenced with `secretref:` | As in `azure.md` 5.4 | Key Vault references with a managed identity, as Microsoft recommends | - |
| Database, files, crons | Convex | Cloud deployment | Same; Convex states data is "encrypted at rest using industry-standard 256-bit AES", it is "SOC 2 Type 2 compliant", and it signs a HIPAA Business Associate Agreement | Convex plan pricing not reviewed |

Sources: https://learn.microsoft.com/en-us/azure/static-web-apps/plans, https://learn.microsoft.com/en-us/azure/static-web-apps/quotas, https://azure.microsoft.com/en-us/pricing/details/container-apps/, https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets, https://learn.microsoft.com/en-us/azure/container-apps/scale-app, https://www.convex.dev/security

Deployment status: not deployed yet at the time of writing.
Live URLs go here once they exist:
- Dashboard: not deployed yet.
- Memory agent: not deployed yet.

## 5. Multi-household support

The prototype is one household.
Production adds a `households` table and a `householdId` on every row, with every index led by `householdId`, so one query can never read another home's data.

### 5.1 Authentication

- **Today:** Convex client functions (the dashboard's queries and mutations) have no authentication; anyone with the deployment URL can call them (`convex/README.md`, "Not done / open").
  HTTP actions use two shared secrets (`EARMARK_HUB_SECRET`, `EARMARK_READ_SECRET`), compared in constant time.
  This is acceptable only for a demo household with synthetic data.
- **Production:** Convex auth with an OpenID Connect provider such as Clerk (Convex also documents Auth0, WorkOS AuthKit, Convex Auth, and custom OIDC; https://docs.convex.dev/auth).
  Every public function starts by resolving the signed-in user, their household membership, and their role, and rejects anything outside it.
- **Hub:** each hub gets its own credential bound to one household, issued at pairing, stored only as a hash in Convex, and revocable from the dashboard.
- **Memory agent:** answers only senders linked to a caregiver account in that household, and reads with a token scoped to that household.
  The prototype agent serves only the demo household's seed data.

### 5.2 Roles (proposal)

| Action | Primary user | Caregiver | Family labeler | Installer (time-limited) |
|---|---|---|---|---|
| Use voice guidance | Yes | - | - | For testing |
| See live map and timeline | Yes (by voice) | Yes, if the user consents | No | During setup |
| See medication evidence | Yes (by voice) | Yes, if the user consents | No | No |
| Edit item names, aliases, notes | Yes (by voice) | Yes | Yes | Yes |
| Change medication schedules | Yes | Yes | No | No |
| Invite or remove people | Yes | Only if granted | No | No |
| Export or delete household data | Yes | Only if granted | No | No |

The primary user is the owner of the household's data.
Caregiver access needs the user's consent and can be withdrawn by the user at any time.

## 6. Security and data retention

### 6.1 What is stored, and for how long

| Data | Where | Prototype | Production retention (proposal) |
|---|---|---|---|
| Item registry: names, aliases, notes, descriptions, tag IDs, home spots | Convex; cached on the hub | Kept | While the household is active |
| Events: placements, removals, pickups, labels, chirps | Convex, append-only | Kept indefinitely | 90 days raw, then only daily summaries |
| Dose results and daily summaries | Convex | Kept | 12 months, or shorter if the user chooses |
| Trial results (pseudonymous tester names) | Convex | Kept; never edited or deleted by `reset` | Until the study ends; deleted on a tester's request |
| Labeling photos | Convex file storage | Deleted in a `finally` block right after the model's suggestion, on success and on every failure; a cron deletes any file older than 10 minutes | Same |
| Microphone audio | Not stored | Streamed to Cartesia only while push-to-talk is held or the voice detector fires; the socket closes after 5 s without audio | Same |
| Transcripts | Not sent to Convex; written with timings to `logs/latency.jsonl` on the hub machine | Kept locally | Timings only, no text; local logs rotated after 7 days |
| Unsent events | `var/hub/queue.jsonl` on the hub | Until Convex accepts them | Same, encrypted at rest on the hub |

Data that leaves the home, and to whom:
- Convex: the registry, events, doses, trials, and briefly a labeling photo.
- Cartesia: microphone audio during a request, and the text of each spoken reply.
- Anthropic (Claude): the transcript plus item names, aliases, notes, and saved place names for tool choice, and the labeling photo.
- Moss: the concierge uses an in-process session index, so item names are embedded and searched on the hub (`docs/sponsors/vendor-notes/moss.md` 3).

We have not yet reviewed Cartesia's or Anthropic's data retention terms.
Signing data processing agreements with every vendor, or replacing a vendor, is a gate before the first home pilot.

### 6.2 Deletion

- **Item:** `objects:remove` already deletes the item's state, schedule, and doses; production also removes its events.
- **Household:** a single "delete household" action deletes every row and stored file for that household and revokes the hub credential and all sessions.
  How long Convex keeps backups after deletion is something we still need to confirm with Convex.
- **Tester:** trial rows are found by pseudonym and deleted on request.

### 6.3 Secrets and keys

- Today: secrets live in a gitignored `.env` and in Convex environment variables, are sent only as headers, and are never logged (`services/concierge/README.md`, `services/hub/README.md`).
- Production: no shared secrets.
  Each hub, each agent, and each signed-in person has its own credential scoped to one household.
  Azure secrets move to Key Vault with managed identities.
  Hub credentials rotate automatically; a lost or replaced hub is revoked from the dashboard.

## 7. Fob battery life (estimate)

| Fact | Value | Source |
|---|---|---|
| CR2032 typical capacity | 235 mAh (to 2.0 V) | Energizer CR2032 datasheet, https://data.energizer.com/pdfs/cr2032.pdf |
| AirTag (same cell type) | "works for more than a year" | https://www.apple.com/airtag/ |
| Generic iTag-style fobs | Sellers claim up to about 6 months; no independent measurement found | https://motivs.eu/en/location-trackers-gadgets/bluetooth-atslegu-mekletajs-keyfinder-itag-melns |
| BLE advertising draw, generic example | "By increasing the advertising interval to 1000 ms, the average current is reduced to 21.5 µA" (Silicon Labs reference design, not an iTag) | https://docs.silabs.com/bluetooth/latest/bluetooth-fundamentals-system-performance/current-consumption |

**Estimate:** 235 mAh at 21.5 µA would last about 15 months of advertising alone.
Real fobs will last less: their advertising interval is unknown, every chirp holds a connection and drives a buzzer, and coin cells lose capacity in the cold.
Plan: measure current on the pilot fobs, read each fob's Battery Level characteristic (0x2A19, present on common iTag units per `docs/sponsors/vendor-notes/bleak.md` 4) once a day, and tell the caregiver at 20%.
Battery swap is a caregiver task, budgeted at twice a year until we have measurements.

## 8. Reliability and safe failure

Every fallback in `docs/project/ARCHITECTURE.md` ("Failure handling") applies; `docs/project/RESPONSIBLE_DESIGN.md` covers what the user hears in each case.
Production adds:

| Risk | Mitigation | Pilot metric |
|---|---|---|
| Hub crashes or loses power | Service manager restarts it; the registry cache and durable queue survive restarts; heartbeat alerts the caregiver | Hub uptime at least 99% per week |
| A reader cable is loose | Silence never counts as a removal, so a glitch cannot create a false pickup (`services/hub/README.md`); reader errors raise a status the dashboard shows | Zero false pickups in the soak test |
| Internet down | The local loop keeps working; speech falls back to cached phrases and the system voice; events queue and replay in order, idempotent by `event_id` | No lost events after a 24-hour offline test |
| Wrong item named | Identity comes only from tags; when retrieval is ambiguous Earmark asks instead of guessing | Zero wrong-identity confirmations; every reported error reviewed |
| Slow answers | Per-stage latency log and `scripts/latency_report.py` | Final transcript to first audio: target 1.2 s, maximum 2.0 s at p95 (`BUILD_BRIEF.md` 5.D) |
| Fob battery dies | Daily battery read and caregiver alert | No fob found dead without a prior warning |

## 9. Regulatory note

Earmark reports events; it does not diagnose, dose, or advise.
The FDA's 2022 guidance "Policy for Device Software Functions and Mobile Medical Applications" lists, among functions for which FDA "intends to exercise enforcement discretion", "Software functions that keep track of medications and provide user-configured reminders for improved medication adherence".
Source: https://www.fda.gov/media/80958/download (issued September 28, 2022), Appendix B, item 11.
This is our reading of public guidance, not legal advice; we would confirm with regulatory counsel before making any health claim.
If Earmark is ever offered through a healthcare provider, HIPAA applies, and Convex offers a Business Associate Agreement (https://www.convex.dev/security).

## 10. Rollout plan

Each phase has a go or no-go checkpoint; we do not move on until it passes.
Target numbers are proposals to be agreed with the partner organization.

| Phase | What happens | Checkpoint to move on |
|---|---|---|
| 0. Prototype (this weekend) | Simulator, one demo counter, blindfolded-teammate trials, which are a pilot and not user evidence | Definition of done in `BUILD_BRIEF.md` section 8; trial results shown with raw counts |
| 1. Bench hardening (about 4 weeks) | Real readers and fobs, reader firmware, home hub on a Pi-class box, user auth and household scoping, delete flow, vendor data agreements | 7-day soak with 1,000 scripted lifts: zero missed or false pickups, zero cross-spot reads, zero wrong-identity answers; latency target met |
| 2. Usability sessions (about 4 weeks) | 5 to 8 blind and low-vision participants, recruited with consent through a blindness organization, for example LightHouse for the Blind and Visually Impaired in San Francisco (https://lighthouse-sf.org/) or The Chicago Lighthouse (https://chicagolighthouse.org/); neither has been contacted yet; ethics review if run through a university | At least 80% of find tasks completed in under 30 seconds; no participant misled about which container they hold; findings recorded in `docs/project/CUSTOMER.md` with consent |
| 3. Home pilot (8 weeks) | 3 to 5 households, installed together with the organization's staff, iPhone app, caregiver dashboard | Setup under 60 minutes; hub uptime at least 99%; zero wrong-identity confirmations; Earmark used in at least 5 of 7 days; caregiver and user both still opted in at the end |
| 4. Expanded pilot (3 months) | 20 to 30 households across 2 or 3 organizations; support process; measured fob battery life; cost per household including installation | At least 70% of households still using Earmark weekly at week 8; support contacts under 1 per household per month; cost per household known |
| 5. Scale | Installer training kit for partner organizations, Azure Standard plan, on-call rotation, incident response and rollback plans (Microsoft's "Operate" stage, `docs/sponsors/sponsor-packs/microsoft.md` 4.3) | Ongoing: the same reliability and safety metrics, reported monthly |

Feedback channels from phase 2 on: a spoken "That was wrong" logged against the guidance event, a feedback button on the dashboard, and a phone number at the partner organization.
