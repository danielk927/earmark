# Setup

## Links (open these on the Mac)
- Room view (3D map, Ask box): http://localhost:5173/room
- Family dashboard (items, medication, timeline): http://localhost:5173/
- Mac app: opens by itself. Press **R** in its window.

## Get ready
1. Put the Mac and the judge phone on the venue Wi-Fi. No hotspots: they are not allowed at the venue.
2. Run `make mac` once (builds the Mac app).
3. Put a mat on the floor where you will stand. Its middle is the centre. Forward is the way you will face.

## Place the 3 beacon phones
Put the 3 phones in a triangle around the mat, so you stand in the middle of it. All at the same height (about 0.75 m, on a table or chair), speaker (bottom edge) facing the mat. Measure everything in meters from the middle of the mat.

```
                    forward
                       ↑
                     [B1]
                       |
                     1.2 m
                       |
                                    ● pills
                    ┌─────┐         (0.7 m right,
                    │ mat │          0.4 m forward)
                    └─────┘
                   /       \
              1.2 m         1.1 m
                 /           \
             [B3]----1.5 m----[B2]
             left            right
```

Measure from the middle of the mat:

| What | Where | Distance from the mat |
|---|---|---|
| B1 | straight ahead | 1.2 m |
| B2 | back and to the right | 1.1 m (0.75 m right, 0.8 m back) |
| B3 | back and to the left | 1.2 m (0.75 m left, 0.94 m back) |
| Pills | at your 2 o'clock | 0.8 m (0.7 m right, 0.4 m forward) |

B2 and B3 are 1.5 m apart (4 ft 11 in). Check it with the tape.

The pills are already in Earmark when `make session` starts, so there is something to find straight away. Put a real bottle at that spot if you like, about 0.75 m high (on a table or chair). From the pills, B1 is 1.1 m away, B2 is 1.2 m and B3 is 2.0 m. To move the pills, change `position` in `config/demo_item.json`.

On each beacon phone:
1. Open Earmark Phone, choose **Beacon (no Mac)**.
2. Set the number: 1 ahead, 2 right, 3 left. Check it every time.
3. Band 12 to 16 kHz. Volume all the way up. Screen on. Press Start.

Beacons need no Wi-Fi at all.

## Start everything
Stop any old Earmark terminals first (Ctrl-C). Then run one command. Everything starts with one item, the pills (see above). You add more by voice:

```
make session TUNNEL=ssh
```

It starts the hub, the voice, the room page and the Mac app, then waits for the phones.

`TUNNEL=1` is because the venue Wi-Fi keeps phones from reaching the Mac directly. The judge phone connects through a Cloudflare tunnel instead: ordinary internet traffic over the venue Wi-Fi, about 1 Mbit/s, no hotspot. The terminal prints a name like `some-words.trycloudflare.com`; it changes every time you run `make session`. On a Wi-Fi that lets phones reach the Mac (at home), plain `make session` works. If Cloudflare says it is refusing new tunnels (too many requests), run `make session TUNNEL=ssh` instead. It uses localhost.run and prints a name ending in `.lhr.life`; type that on the judge phone the same way.

## Connect the judge phone
1. Put the judge phone on the venue Wi-Fi.
2. Open Earmark Phone, choose **The user's phone**.
3. Type the name the terminal prints (like `some-words.trycloudflare.com`). Press Start.
   - A Wi-Fi blip is fine: the phone keeps recording and catches up, so you do not have to recalibrate. If the terminal ever shows `!!! the phone's audio restarted`, stand on the mat and press Enter.
4. Wait until the terminal shows `B1 heard`, `B2 heard` and `B3 heard`.

## Stand on the mat
Hold the judge phone at chest height, bottom edge facing out. Press **Enter** in the terminal and stand still on the mat for 30 seconds. Don't move the beacons. You will then see `fix x ... y ...` lines, and you and the beacons show on the room view.

## AirPods
1. Connect the AirPods to the Mac. Turn Spatial Audio **Off** (menu-bar AirPods icon). The app makes its own 3D sound.
2. In the Mac app, accept the motion and microphone prompts.
3. Stand on the mat facing forward. Press **R** to recenter.
5. Back on the mat, hold **Space** in the Mac app window and say it: "Where are my keys?". Let go when done. Speak clearly and keep the room quiet.
   - Can't reach the Mac? A teammate can hold Space for you, or type into the box under the Hold to talk button, or into the Ask box on the room page.

You should hear the ping from the item. It gets faster and louder as you get close. At half a meter it stops and says "You're here".
