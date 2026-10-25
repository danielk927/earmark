# Setup

## Get ready
1. Put the Mac on the iPhone hotspot.
2. Run `make mac` once (builds the Mac app).
3. Tape 4 marks on the floor. Measure from the middle of the mat. Forward is the way the tape arrow points.

```
                forward
                   ↑
            mark 2 (0, 0.8 m)

          mark 1 = the mat (0, 0)

   mark 4                    mark 3
   (-0.7, -0.5)              (0.7, -0.5)
```

## Place the 3 beacon phones
All at the same height (about 0.75 m, on a table or chair). Speaker (bottom edge) facing the mat. About 1.2 m from the mat.

```
                 [B1]  ahead

   [B3] left      mat      right [B2]
```

On each beacon phone:
1. Open Earmark Phone, choose **Beacon (no Mac)**.
2. Set the number: 1 ahead, 2 right, 3 left. Check it every time.
3. Band 12 to 16 kHz. Volume all the way up. Screen on. Press Start.

The hotspot phone can be a beacon. Beacons do not need the hotspot.

## Start everything
Stop any old Earmark terminals first (Ctrl-C). Then run one command. Everything starts with no items. You add them by voice later:

```
make session
```

It starts the hub, the voice, the room page and the Mac app, then waits for the phones.

## Connect the judge phone
1. Put the judge phone on the hotspot Wi-Fi.
2. Open Earmark Phone, choose **The user's phone**.
3. Type the address the terminal prints (like `ws://172.20.10.9:8766`). Press Start.
4. Wait until the terminal shows `B1 heard`, `B2 heard` and `B3 heard`.

## Walk the marks
Hold the judge phone at chest height, bottom edge facing out. Do this for each mark, 1 then 2 then 3 then 4:
1. Stand on the mark.
2. Press **Enter** in the terminal.
3. Stand still for 10 seconds.
4. Walk to the next mark when it tells you.

Don't move the beacons. When it says `room setup ok`, it is done. You will see `fix x ... y ...` lines. The beacons show on http://localhost:5173/room.

## AirPods
1. Connect the AirPods to the Mac. Turn Spatial Audio **Off** (menu-bar AirPods icon). The app makes its own 3D sound.
2. In the Mac app, accept the motion and microphone prompts.
3. Stand on the mat facing forward. Press **R** to recenter.
4. Walk to where an item will go. Say or type "I'm leaving my keys here".
5. Back on the mat, just say it out loud: "Where are my keys?". The Mac's microphone is always listening and only sends sound when it hears speech. No key to press, nothing to press on the AirPods. Keep the Mac in the room, speak clearly, and keep the room quiet.
   - Mac not hearing you? A teammate at the Mac can hold **Space** and the judge speaks, or type into the Ask box on the room page.
   - The AirPods microphone is not used on purpose: it would make the sound muffled.

You should hear the ping from the item. It gets faster and louder as you get close. At half a meter it stops and says "You're here".
