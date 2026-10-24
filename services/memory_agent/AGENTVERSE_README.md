# Earmark Memory: caregiver Q&A for a blind or low-vision person's home

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)
![tag:domain/accessibility](https://img.shields.io/badge/accessibility-4CAF50)

Earmark helps blind and low-vision people find everyday objects by sound.
Spot readers on the counter and Bluetooth fobs record where household objects are and when they are picked up or put down.
Earmark Memory lets a caregiver or family member ask about that record in plain language from ASI:One.
Every answer comes from Earmark's logged events, with times in the household's time zone.

## Example questions

- "Did Mom take her evening pills?"
- "Where did Dad leave his keys?"
- "What hasn't been touched in a week?"
- "When was the salt last used?"
- "Give me today's summary."

## What it can do

- Find an object: its current spot, when it was last confirmed there, or where its Bluetooth fob was last detected.
- Report medication adherence for any day: each scheduled dose marked taken, late, missed, or not yet due, with the time the bottle was picked up.
- List objects that haven't been picked up or put down in a week (or another period you name).
- Give a day's summary: doses, number of pickups, untouched and missing objects.

It plans its own lookups: for "Did Mom take her evening pills?" it checks today's doses, and if tonight's dose isn't due yet it also checks yesterday's.
It uses Claude to choose lookups and phrase answers, and it falls back to a deterministic keyword router if the model is slow or unavailable.

## Interaction

Chat with it directly in ASI:One (Agent Chat Protocol).
Each message is answered on its own; it keeps no conversation history.

## Limitations

- No medical advice, ever: it reports what the records show and never suggests doses or interprets health.
  If you ask what to do, it suggests contacting the person's clinician or pharmacist.
- "Taken" means the pill bottle was picked up during the dose window; Earmark cannot see whether pills were swallowed.
- It only knows what Earmark recorded; when data is missing it says so.
- The household has one primary person: "Mom", "Dad", or a name all refer to them.
- Read-only: it cannot change anything in the home.

Keywords: caregiver, medication adherence, assistive technology, blind and low vision, accessibility, object finder, home monitoring, elder care.
