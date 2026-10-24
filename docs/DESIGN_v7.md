# Design v7 (supersedes Amendment 01 where they conflict)

The full design text from the human is summarized here; the backend-relevant decisions are:

- No NFC, no Bluetooth tags, no cameras. Item locations are **saved spots**: during setup a teammate holds the iPhone at each item's spot and taps save; the locator sends `save_spot` and the hub stores it.
- Remove NFC pickup detection, the wrong-jar correction, voice labeling of new tags, and BLE fob chirps.
- Items: sugar in the cupboard in front (top shelf, front left), keys in the drawer on the right, a spice jar in the bag on the left, pills in the box behind.
- Arrival (about 0.45-0.5 m): the ping stops, a short "you're here" tone plays, and the voice says the spot detail. The user finds the item by touch. Arrival is the end of a find.
- The ping is a short click; pitch hints height; a distinct sound plays when the item is behind.
- iPhone 17: listens to 5 acoustic beacons (one ESP32), sends `listener_pose` about 3 Hz, records speech during push-to-talk, plays no sound. AirPods Pro 2 connect to the Mac and report head direction. Phone and Mac connect over the phone's hotspot.
- The Mac app shows the audience map: where the user is, which way they face, and where the sound comes from.
- Fallbacks: beacon position unreliable -> the phone uses step counting (`source: steps`); no position -> assume the mat and speak distances; head tracking lost -> room-forward directions plus clock faces.
- The Fetch.ai memory agent, Convex dashboard, and sponsor integrations keep their workflows.
  Medication adherence evidence is now **arrival at the medication's spot** (the user was guided to and found the pills) within the dose window; answers say "found", never "took".
- Trials end on `arrived` for the target; there are no wrong picks to count.
