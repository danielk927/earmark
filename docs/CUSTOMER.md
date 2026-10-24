# Earmark: customer understanding

Earmark helps blind and low-vision people find, identify, and confirm everyday objects at home by sound, without a camera and without holding a phone.
This document covers who the users are, the jobs Earmark does for them, why the tools they have today fall short, and what we still need to learn from real users.
Every external fact has a source URL; pages were read on 2026-10-24 unless noted.

**We have not interviewed any users yet.**
Nothing in this document is a quote from, or a finding about, a real person.
See [Conversations with users](#conversations-with-users).

## 1. Who the users are

| Role | Who | What they need from Earmark | Status |
|---|---|---|---|
| Primary user | A blind or low-vision adult who lives at home, often older (see 2.3) | Find a specific item now, know which of two look-alike containers is in hand, and do it by voice with hands free | Assumption to validate |
| Caregiver | Adult child, spouse, or home aide, often not in the same house | Evidence that the medication bottle was picked up at dose time, without calling to ask or visiting | Assumption to validate |
| Family labeler | Any relative with a phone or laptop | Name and describe items remotely, for example "the blue tin is Grandma's tea" | Assumption to validate |
| Professional (channel, not user) | Vision rehabilitation therapist, orientation and mobility specialist, blindness organization staff | A setup they can install, teach, and recommend | Assumption to validate |

## 2. How many people this affects

Definitions differ between sources (presenting versus best-corrected acuity, measured versus self-reported), so these numbers should not be added together or compared directly.

### 2.1 Global

| Fact | Source |
|---|---|
| "Globally, at least 2.2 billion people have a near or distance vision impairment." For "at least 1 billion of these people, vision impairment could have been prevented or is yet to be addressed." | WHO fact sheet "Blindness and vision impairment", dated 10 February 2026, https://www.who.int/news-room/fact-sheets/detail/blindness-and-visual-impairment |
| In 2020, an estimated 43.3 million people were blind, 295 million had moderate or severe vision impairment, and 258 million had mild vision impairment. | GBD 2019 Blindness and Vision Impairment Collaborators, "Trends in prevalence of blindness and distance and near vision impairment over 30 years", Lancet Global Health 2021;9(2):e130-e143, https://doi.org/10.1016/S2214-109X(20)30425-3 |
| By 2050 the same study forecasts 61.0 million people blind and 474 million with moderate or severe vision impairment. | Same paper (abstract, Findings) |
| The IAPB Vision Atlas summarizes this as 1.1 billion people living with sight loss, citing the same study. | https://visionatlas.iapb.org/ |

### 2.2 United States

| Fact | Source |
|---|---|
| CDC modeled estimates for 2024: 7.15 million people with best-corrected visual acuity loss (loss that glasses do not fix), of whom about 706,000 are blind (20/200 or worse). | CDC Vision and Eye Health Surveillance System (VEHSS), https://www.cdc.gov/vision-health-data/prevalence-estimates/vision-loss-prevalence.html |
| NEI: in 2015, 1 million Americans were legally blind and 3.2 million had visual impairment (20/40 or worse with best correction); the total is "expected to double to more than 8 million by 2050". | National Eye Institute, 19 May 2016, citing Varma et al., JAMA Ophthalmology 2016, https://www.nei.nih.gov/research-and-training/research-news/visual-impairment-blindness-cases-us-expected-double-2050 |
| AFB, from the 2022 National Health Interview Survey: an estimated 50.18 million adult Americans reported trouble seeing even with glasses or contacts, or being blind. This is a self-reported, much broader measure. | American Foundation for the Blind, https://www.afb.org/research-and-initiatives/statistics |

### 2.3 Age

WHO: "most people with vision impairment and blindness are over the age of 50 years" (fact sheet above).
This matters for design: many users will be new to vision loss, will not read braille, and may also have reduced hearing or dexterity.
Earmark therefore works by voice and sound only, and needs no screen, braille, or fine motor control from the primary user.

## 3. The jobs Earmark does

| # | Job (in the user's words) | What Earmark does | How it knows | Prototype status (2026-10-24) |
|---|---|---|---|---|
| 1 | "Where's the sugar?" | Says a clock direction and distance ("at your one o'clock, about an arm's length away") and plays a head-tracked ping from the jar's spot through AirPods | NFC reader under each home spot reads the jar's tag | Hub and concierge built and tested with the simulator; Mac app spatial audio in progress |
| 2 | "Which of these identical jars is the salt?" | Names the item on each spot; never guesses from appearance | Identity comes from the tag, not from how the jar looks | Built (hub and concierge) |
| 3 | "Did I pick up the right one?" | On lift: "Got it, that's the sugar", or "That's the salt. The sugar is one spot to your right." | Removal from a spot becomes a `pickup` event | Built (hub debounce, concierge correction) |
| 4 | "Where are my keys?" | Says how close the keys are, then makes the fob on them chirp | Bluetooth signal strength of a key-finder fob, and its alert service | Built against mocked Bluetooth; real fob untested |
| 5 | "Something for my eggs" | Asks "Do you mean the salt or the pepper?" instead of picking one | Retrieval over names, aliases, and family notes; ambiguity decided in code | Built (concierge) |
| 6 | Caregiver: "Did Mom take her evening pills?" | Reports whether the pill bottle was lifted inside the dose window (taken, late, missed, pending), with times; never gives medical advice | Pickups of the medication object, rules in deterministic Convex code | Built (Convex adherence with tests); dashboard and remote agent in progress |
| 7 | Family: "Label the new tin for Dad" | Edit names, aliases, and notes from a web dashboard; optional one-time photo suggests a name, then the photo is deleted | Convex is the registry; edits reach the voice loop within seconds | Convex functions built; dashboard in progress |

Important limit on job 6: lifting a bottle is evidence that it was handled, not proof that a pill was swallowed.
Earmark says "picked up at 8:04 PM", never "took her medication".

## 4. Why existing tools fall short

The core argument:
- Camera and scene apps describe what the camera sees right now.
  They do not remember where things are when the phone is in a pocket, and they need the user to hold and aim a phone.
- Appearance-based recognition cannot, by design, tell apart two containers that look identical (the same jar holding salt or sugar, two pharmacy bottles of the same size).
- Labels (audio, braille, tactile, rubber bands) identify an item once it is in your hand, so you have to find it first.
- Item trackers solve roaming items like keys, but a tracker per spice jar or pill bottle is costly and bulky, and they still need a phone in hand.
- None of these gives a caregiver evidence that the medication bottle was handled at dose time.

Earmark's bet is different: know where each item is all the time from cheap tags and fixed home spots, so the answer is ready before the user asks.
That bet has costs (setup, hardware, items must live on spots), which section 6 lists as questions to validate.

### 4.1 Camera and scene apps

| Tool | What it does well | Gap for Earmark's jobs | Source |
|---|---|---|---|
| Be My Eyes and Be My AI | Free live video calls with sighted volunteers (live counter: 11.5 million volunteers, 1.1 million blind and low-vision users) and AI image description | Each answer needs the phone camera aimed at the item and a person or AI to look; nothing is remembered between calls | https://www.bemyeyes.com/ |
| Microsoft Seeing AI | Free; channels for Short Text, Documents, Products (barcode scanning with audio beeps), Scenes, People, Currency, Colors, Handwriting, and Light | Describes what is in front of the camera; does not track where items are when unseen | https://blogs.microsoft.com/accessibility/seeing-ai-app-launches-on-android-including-new-and-updated-features-and-new-languages/ (4 Dec 2023) |
| Seeing AI "Find My Things" | The closest existing tool to Earmark's job 1: the user records four short videos to teach a personal item, then scans the room until the app finds it and guides them "within arm's reach" with audio, visual, and vibration cues | Requires sweeping the room with a phone; recognition is by appearance, so two identical jars are indistinguishable (our inference from how it works); no pickup confirmation or caregiver view | https://www.microsoft.com/en-us/research/story/find-my-things/ (24 Oct 2024); research: ASSETS 2023, https://dl.acm.org/doi/10.1145/3597638.3608395 |
| Envision app and Envision Glasses | Glasses keep hands free; their "Detect Object" feature "Beeps when one of 15 possible objects is in range" (AFB AccessWorld, Nov 2022) | Generic object categories, not the user's own items; glasses cost $1,899 (Read), $2,499 (Home), $3,499 (Professional) | https://afb.org/aw/23/11/18109, https://shop.letsenvision.com/products/glasses-home |
| Google Lookout (Android) | Seven modes; Find mode gives direction and distance on most phones | Find mode searches a fixed list (Seating & Tables, Doors & Windows, Cups, Bottles & Cans, Utensils & Tableware, Vehicles, Bathroom), so it can find "a bottle" but not "the salt" | https://support.google.com/accessibility/android/answer/9031274?hl=en |
| Apple Magnifier Detection Mode | Detects doors, people, and furniture, and reads text around you | Not for personal items; Apple says it "should not be relied on in high-risk or emergency situations ... or for navigation" and it works only on supported iPhone models | https://support.apple.com/guide/iphone/detect-doors-around-you-iph35c335575/ios |

Microsoft's own research is evidence that finding personal items is a real, unsolved need for blind and low-vision people.
Earmark is complementary to Seeing AI: Seeing AI reads and describes the world, and Earmark keeps track of the user's own things at home.

### 4.2 Audio, tactile, and NFC labels

| Tool | What it does well | Gap | Source |
|---|---|---|---|
| RNIB PenFriend 3 | Record a voice label on a sticker; touch the pen to it to hear it; £95.00 | Identifies an item already in hand; the pen is a second object to find and hold | https://shop.rnib.org.uk/products/rnib-penfriend-3-audio-labeller |
| WayAround WayTags | NFC stickers, buttons, and clips read by a free app "optimized to work with VoiceOver and TalkBack" | Same: scan the item you already found, phone in the other hand | https://afb.org/aw/20/2/14975 (Feb 2019), https://www.wayaround.com/ |
| Rubber bands, raised dots, 3-D pen, large print | Free or cheap; VisionAware suggests one, two, or three bands to tell similar bottles apart, and bands to count daily doses | AFB and the ASCP Foundation note that "Rubber bands can and do break and may come off the container" and "may not be appropriate to distinguish among more than three or four medications"; dose counting is manual and invisible to caregivers | https://aphconnectcenter.org/visionaware/new-to-vision-loss/medication-management/, https://afb.org/blindness-and-low-vision/your-rights/rx-label-enable-campaign/guidelines-prescription-labeling |

Earmark uses the same NFC sticker idea as WayAround, but the reader is under the shelf instead of in the user's hand, so the system always knows which tagged item is on which spot.

### 4.3 Item trackers

| Tool | What it does well | Gap | Source |
|---|---|---|---|
| Apple AirTag | $29 each or $99 for four; Precision Finding with VoiceOver gives directions like "AirTag is 9 feet away on your left"; current model has a louder speaker; user-replaceable CR2032 "works for more than a year" | Precision Finding needs iPhone 11 or later (not iPhone SE 2nd and 3rd generation or iPhone 16e); one tag per item is too costly and bulky for jars and pill bottles; phone in hand | https://www.apple.com/shop/buy-airtag/airtag, https://www.apple.com/airtag/, https://www.apple.com/newsroom/2021/04/apple-introduces-airtag/, https://support.apple.com/en-us/111847 |
| Tile (Life360) | Bluetooth trackers; tap Find in the Tile app to make one ring | Same per-item cost and phone dependence | https://support.life360.com/hc/en-us/articles/30583078813719-Ring-My-Tile |
| Generic "iTag" key finders | Very cheap Bluetooth fobs that beep on command | No useful app of their own | Earmark uses these for keys; see `docs/PRODUCTION.md` |

For keys alone, an AirTag is a strong option and Earmark does not try to beat it.
Earmark's addition is one voice interface for every item, hands-free, with the same "where is it" question working for jars, pill bottles, and keys.

### 4.4 Smart speakers

| Tool | What it does well | Gap | Source |
|---|---|---|---|
| Amazon Alexa "Show and Tell" | On an Echo Show, "Alexa, what am I holding" helps "blind and low vision customers identify grocery items"; built with the Vista Center for the Blind and Visually Impaired | Identifies an item already in hand and held up to the camera; a refilled home jar has no packaging to recognize (our inference) | https://www.aboutamazon.com/news/devices/alexa-what-am-i-holding |
| Voice assistants in general | Hands-free reminders and timers | A reminder cannot tell whether the bottle was actually picked up (our inference) | - |

## 5. Medication-taking context

| Fact | Source |
|---|---|
| "A number of rigorous reviews have found that in developed countries, adherence among patients suffering from chronic diseases averages only 50%." | WHO news release on "Adherence to long-term therapies: evidence for action", 1 July 2003, https://www.who.int/news/item/01-07-2003-failure-to-take-prescribed-medicine-for-chronic-diseases-is-a-massive-world-wide-problem |
| In 100 outpatients over 60 with chronic disease, low adherence (MMAS-8) rose from 3.7% with normal vision to 45.0%, 71.4%, and 88.9% with mild, moderate, and severe visual impairment. The authors call the single-center, cross-sectional result hypothesis-generating. | Shen Q, Zeng X, Yu L. Med Sci Monit 2026, https://doi.org/10.12659/msm.954346 |
| A scoping review found 18 publications on assistive technology for medication management with sensory impairment; ten studies tested early-stage prototypes, and the authors found "limited empirical evaluation of their effectiveness". | Cooper L et al. Disability and Health Journal 2023, https://doi.org/10.1016/j.dhjo.2023.101500 |
| VisionAware: "Not being able to read the information on prescription medications is a particularly dangerous problem for individuals who are blind or low vision." | https://aphconnectcenter.org/visionaware/new-to-vision-loss/medication-management/ |

What Earmark adds is evidence, not advice: the bottle left its spot at 8:04 PM, inside the 8:00 PM window.
It does not say whether a dose was correct, and it tells anyone who asks for advice that it cannot give medical advice (see `docs/RESPONSIBLE_DESIGN.md`).

## Conversations with users

**Status on 2026-10-24: no conversations recorded.**
No one on the team has yet recorded a conversation about Earmark with a blind or low-vision person, a caregiver, or an accessibility professional.
The team has been asked to do so this weekend (`docs/STATUS.md`, blockers, item 7).
Until that happens, every user need in this document is an assumption drawn from the public sources above.

We will never invent an interview, a quote, or user feedback.
If a conversation happens, it goes below using this template, only with the person's consent, and only with what they agreed to share.

### Template

```markdown
### Conversation N - YYYY-MM-DD

- Who: role only (for example "blind adult, lives alone", "daughter and caregiver", "vision rehabilitation therapist").
  No name unless they asked to be named.
- How: in person / phone / video; who from the team; about how long.
- Consent: what they agreed to (notes, quotes, being named, recording), asked before the conversation and confirmed at the end.
- Did they try Earmark? yes / no; if yes, which jobs from section 3.

What they said (their words only where they agreed to be quoted; otherwise a paraphrase, marked as such):
- ...

What surprised us:
- ...

What we will change, or test next:
- ...
```

Rules for this section:
- Ask for consent before taking notes, and again before quoting.
- Quote only words that were said; paraphrase everything else and mark it as a paraphrase.
- Record role, not identity; never record health details beyond what the person volunteers for the notes.
- Record disagreement and negative feedback as carefully as praise.

## 6. Open questions to validate with real users

| # | Question | Why it matters | How we would test it |
|---|---|---|---|
| 1 | How often do people lose time searching for specific items at home, and which items? | Sets the size of job 1 and which items to tag first | Interviews; a one-week diary with a few households |
| 2 | Do look-alike containers cause real mix-ups (salt and sugar, pill bottles), and how do people handle them today? | Job 2 is our strongest differentiator; it has to be a real pain | Interviews; ask people to show us their current system |
| 3 | Will people keep items on fixed home spots? | The design depends on it; an item off its spot is located only by its last sighting | Pilot logs: share of pickups returned to a home spot |
| 4 | Is a spatial ping through earbuds welcome at home, or is speech alone enough? | Spatial audio is our core interaction and also the costliest part | Trial mode: time to find with ping versus speech only |
| 5 | Are AirPods (or similar head-tracking earbuds) acceptable to wear at home, and for how long? | Head tracking needs supported headphones | Interviews; pilot wear time |
| 6 | Do caregivers want pickup evidence, and does the user consent to it being shared? | Job 6 must be wanted by both sides; it can feel like surveillance | Paired interviews with user and caregiver, separately |
| 7 | Is "bottle lifted in the window" good enough evidence, or will it mislead? | False reassurance is a real harm | Compare pilot pickup logs with the user's own record |
| 8 | Who installs the readers and tags, and how long does setup take? | Setup cost may decide adoption | Timed installs with a blindness organization's staff |
| 9 | What would people pay, and who pays (user, family, insurer, agency)? | Sets the hardware budget in `docs/PRODUCTION.md` | Interviews with users, caregivers, and agency staff |
| 10 | Does a voice-only interface work for people with hearing loss as well as vision loss? | Many older users have both | Interviews with dual-sensory-loss users; volume and pitch settings |
