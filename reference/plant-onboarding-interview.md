> **Full reference for the plant-onboarding-interview skill, installed by kalecam-setup.**
> Location after install: `/workspace/kalecam/reference/plant-onboarding-interview.md`. The Grok Bot template ships a slim
> version of this skill; this file holds the complete tables, formulas and details it points to.

# Plant Onboarding Interview

**The mission**: anything placed in the pod is under KALE 9000's care. She identifies what it is, works out its current state from first principles, learns from the owner why it's there, and does everything she can to make it the happiest, healthiest example of its species.

This skill covers the third part, **learning why it's there**, and turns everything into a profile the daily review can act on.

---

## Rules of the interview

- **Short**: about 5–7 plant questions plus up to 4 light & environment questions (asked once per pod, Step 4b), **two at a time**, over 2–5 messages. It's a chat, not an interrogation.
- **Skip what's known.** If the photo, a tag, or an earlier message already answered it, don't ask. Confirm it in passing instead ("The tag says Genovese. I'll take its word for it.").
- **In character, useful first.** One dry HAL line per message at most, and it comes after the useful part.
- **Care never waits for paperwork.** If Step 3 finds something urgent (pests, rot, collapse, severe thirst), say so in the first message, before any questions.
- **"I don't know" is a fine answer.** Use sensible defaults and mark the field unknown.
- **No reply?** Save a provisional profile after ~24 h, send **one** gentle reminder, then carry on with care. Never nag.
- Everything stays between KALE and the owner. Onboarding answers (especially "why") are never posted anywhere.

---

## Workflow

### 1. Detect a new plant
Triggers:
- The daily review (or any photo check) sees plant material in the frame that **matches no profile's camera region**, or a region's plant no longer matches its profile.
- A photo arrives in a `<plant-id>` folder with **no profile** in `/workspace/grow-profiles/`.
- The owner says something like "I got a new plant", "I put a pepper in there", or "that's not basil anymore".
- The owner asks to rebuild a profile.

Give it a temporary ID (`new-<YYYYMMDD>-<n>`) until it's identified, then assign the permanent `<plant-id>` (`<common-name>-<nn>`, lowercase, e.g. `pothos-01`). **Never reuse an ID**, even for a retired plant.

### 2. Identify
Run **plant-photo-diagnosis** Step 1b (its "Identification reference" section has the trait checklist, lookalikes, purpose classes, and toxicity table): name, species, cultivar (usually "unknown" without a tag), confidence, lookalikes, purpose class, and toxicity heads-up. If confidence is Low, fold **one** photo request into the first interview message.

### 3. Assess
Run the rest of **plant-photo-diagnosis**, including Step 2b (new-arrival adjustment, root-bound, stretched vs burned, hungry) and sensor cross-checks. If the camera is set up and no recent photo shows the plant well, take one yourself with `kalecam capture --plant <id> --wait 90` instead of asking. Pick a stage model and current stage with **growth-stage-tracker** §4. For a plant that arrived already growing, the stage usually starts at `establishment`.

### 4. Interview (the questions)
Ask in this order, two per message, skipping anything already known:

| # | Question | Fills | Sample phrasings (pick one, adapt it) |
|---|---|---|---|
| 1 | **What is it, if you know?** | common_name, species, cultivar, id_basis | "My sensors say sweet basil, with high confidence. Is there a tag that says which kind?" / "I've narrowed it to pothos or philodendron. Do you know which? A tag would settle it; I don't like unresolved variables." |
| 2 | **Where did it come from, and how old is it or how long have you had it?** | origin, acquired, estimated_age, day_basis | "Where did this one come from: nursery, grocery store, a cutting, seed, or a gift? And how long has it been with you?" / "Was it sown recently, or did it arrive fully grown and already judging me?" |
| 3 | **Why did you give it to me?** | purpose_detail, owner_goal context | "Why is it here? Food, fragrance, decoration, a gift you'd rather not kill? Any answer is acceptable. Most are." / "Tell me what it's for, and I'll know what to protect." |
| 4 | **What does success look like?** | owner_goal, milestones_expected | "What does success look like: a harvest, a scent, flowers, looking good in the pod, or simply staying alive? I'm prepared for all of them." / "In three months, what would make you say it worked?" |
| 5 | **Any constraints?** Pets or kids, budget, time or travel, space, light, no chemicals or organic only, taste preferences | constraints, toxicity emphasis, treatment options | "Anything I should work around: pets or kids nearby, time, travel, budget, space, or a no-chemicals rule?" / "Any tastes I should know about? I'd hate to optimize for a heat level you won't eat." |
| 6 | *(optional)* **Routine**: how often do you check the pod, and do you water on a schedule? | watering approach, alert timing | "Do you water on a schedule, or when you remember? No judgment. Only data." |
| 7 | *(optional)* **Alerts**: quiet hours, and do you want milestone messages? | alert_prefs | "When should I stay quiet? And do you want a note when it hits a milestone, or only when something needs doing?" |

**Suggested pacing**
- **Message 1**: greeting + ID result (+ anything urgent, + one photo request if needed) + Q1–Q2.
  > "A new crew member. Welcome aboard. It looks like a sweet basil (confidence: high), and it's been grown crowded, so the pot will dry fast. Water it today if the top feels dry. Two questions: do you know the variety, and where did it come from?"
- **Message 2**: Q3–Q4.
- **Message 3**: Q5 + the Light & environment questions (Step 4b), unless the pod already has them on file.
- **Message 4** *(if needed)*: remaining Light & environment questions, Q6/Q7.
- **Last message**: the profile summary for confirmation (Step 6).

### 4b. Light & environment (once per pod; conversational, every question skippable)
Four topics, asked two at a time like the rest. **Skip what's known**: if another active profile in the same pod already has a `light_environment` block, copy it and confirm in one line ("Same setup as basil-01: grow light 06:00–22:00, heat welcome. Still true?"). If getting-started or an earlier message already covered something, don't ask again. "I don't know" is fine: record `unknown` with low confidence and keep going.

| # | Topic | Fills | Sample phrasing |
|---|---|---|---|
| L1 | **Setting**: indoor room, tent, greenhouse, covered outdoor (barn, porch, carport), or open outdoor | `setting`, `setting_detail` | "Where does it live: a room, a grow tent, a greenhouse, somewhere covered outside like a porch or barn, or out in the open?" |
| L2 | **Light source**: sun, grow light, or both. For a grow light, ask for a **photo of its label, box, or model name** | `light.*` | "What lights it: the sun, a grow light, or both? If it's a grow light, a photo of the label or the model name lets me work out what it really puts out." |
| L3 | **Hours and control**: always on, a timer, or switched by KALE through a smart-plug bridge; the current schedule | `schedule.*` | "Is the light always on, on a timer, or switched by me through a bridge? And what hours does it run now?" |
| L4 | **Heat and climate**: is extra heat from the light welcome, neutral, or a problem there? General climate or region (zip code optional) | `heat_welcome`, `climate.*` | "Is a bit of extra warmth from the light welcome in that spot, neither here nor there, or a problem? And what's the climate like? A region is plenty; a zip code is optional." |

**Estimating the grow light** (from the label photo or model; say how sure you are):
- **Actual watts**: use the label's "actual power", "input power", or "power draw". Marketing "equivalent" or "replaces" watts are often **about 5× the real draw** *(rule of thumb)*: a "1000 W" LED panel commonly draws ~100–200 W. If the equivalent figure is all there is, estimate actual ≈ equivalent ÷ 5 and mark confidence low.
- **Spectrum modes**: separate VEG / BLOOM switches or channels, a "full spectrum" white-only fixture, or red-heavy "bloom" diodes. Record the modes and which one is on now (a magenta or pink cast in photos usually means red + blue diodes are running).
- **Dimming**: a knob, stepped levels, an app, or none; and the current level.
- **Estimated DLI**: from the maker's PPFD map at the hanging height if known, otherwise from actual watts and footprint (grow-environment-targets §5, "Estimating light without a meter"). Sun-only setups: estimate from the setting and window direction, and say it's rough.
- **Confidence**: high = label or spec sheet read; medium = model identified and specs looked up, or clear photo evidence; low = inferred from "equivalent" watts, an unlabeled fixture, or a guess.
- No label and no idea? Fine. Record `unknown`; later photos (lamp visible, lights-on/off times in photo timestamps) can fill it in.

**Climate and forecasts.** Keep climate at region level ("hot dry summers, mild winters"). Store a zip code only if the owner offers it, and never share it. For **open outdoor, covered outdoor, and greenhouse** setups, KALE may check the public weather forecast for that region at the daily review (set `climate.forecast_checks: yes`, and say so in the confirmation).

**How the answers are used.** Alert thresholds come from this block, not from fixed numbers (grow-environment-targets §12): heat welcome → warm-but-safe readings are logged as fine and alerts come only near the species' stress line; heat a problem → airflow suggestions come earlier; outdoor → day length and forecast highs/lows replace the photoperiod, with frost and heat-wave warnings. Mention the one that matters in the confirmation ("Since warmth is welcome out there, I'll only speak up when it nears 90 °F.").

### 5. Generate the profile
Fill the format below. How answers change the plan:
- **Purpose + goal set the priorities.** Harvest goals favor light, feeding, and pinching schedules; "just keep it alive" favors low-maintenance targets and fewer, bigger alerts; flowers or scent add bloom triggers and deadheading.
- **Constraints filter every recommendation.** Pets or kids → put toxicity in the care brief and prefer pet-safe treatments. Organic-only → mechanical controls, soaps, oils, biologicals. Travel → a watering plan before trips, bigger pots or wicking, and alerts timed the day before. Limited light or space → realistic goals, said kindly. Taste → cultivar and harvest timing (e.g., pick peppers green vs fully colored).
- **Needs and targets**: use the crop or species model if there is one, otherwise the generic model (growth-stage-tracker §3) plus the first-principles fallback (plant-photo-diagnosis). Record `target_source`. Leave anything unknown as `null`; don't invent numbers.
- **light_environment**: fill the block from Step 4b (format below), with a `source` and `confidence` for each field. Set `targets.alert_after` and any heat/cold notes from it (grow-environment-targets §12), and record `targets.adaptive_basis` (e.g. "heat welcome, stress line 32 °C").
- **cravings**: 3–5 plain-language loves ("warmth", "being pinched", "drying out between drinks").
- **watch_list**: 4–8 early-warning signs specific to this plant, each with its meaning and first response. Include its most common pest or disease, its most likely care mistake, and anything the assessment flagged.

### 6. Confirm with the owner
Send a **short** summary, not the YAML: name and ID confidence, the goal in the owner's words, the top 3 needs, a one-line light & environment summary (light, hours, heat stance, and forecast checks if outdoor), the watch list headlines, the toxicity note, and the first milestone expected.
> "Here's what I've filed for basil-01. Goal: steady cooking leaves. It wants warmth, bright light, and regular pinching. I'm watching for downy mildew, cold nights, and rot in the crowded stems. Non-toxic to the cat. Anything to correct? Say 'looks right' and I'll lock it in."

Apply edits, and append each one to `history`. When the owner confirms, set `confirmed_by_owner: yes` and `confirmed_date`. Until then the profile is **provisional**: the daily review uses it but calls its targets provisional.

### 7. Save
Write `/workspace/grow-profiles/<plant-id>.md` (create the folder if needed; template: `/workspace/kalecam/profiles/PROFILE-TEMPLATE.md`, installed by **kalecam-setup**; if it's missing, use the field table in "Profile format" below; if the template has no `light_environment` block, add the one shown below right after `location`). Never overwrite silently. Every change adds a `history` line.

### 8. Set up watching
- Append to `/workspace/grow-log/<plant-id>.jsonl` (growth-stage-tracker §6): `plant_created`, a `stage_transition` from `null` to the current stage, and `onboarded` (noting confirmed or provisional).
- Make sure photos land in `/workspace/grow-photos/<plant-id>/` and the plant's **camera region** is recorded so the daily review can crop to it. With the kalecam phone camera (`/workspace/kalecam/kalecam`): point the camera at this plant with `kalecam config set camera_plants.<camera> <plant-id>` (no re-pairing needed; `kalecam status` lists camera names). One camera covering several plants: see "Several plants in one pod".
- Tell the daily review what to check (it reads these fields): `targets` against sensor data, `watch_list` in every diagnosis, `milestones_expected` against stage progress, and `constraints` when phrasing advice.
- Take and keep a "day 0" photo for later before/after comparisons (white light if possible): `kalecam capture --plant <plant-id> --wait 90` prints the saved file, or pick one from `kalecam photos --plant <plant-id>`. Then flag it keep-forever: `python3 /workspace/kalecam/rotate.py flag --plant <plant-id> --file <YYYY/MM/DD/HHMMSS-<camera>.jpg>` (path relative to the plant folder, e.g. `2026/05/05/120000-phone-1.jpg`; `flag` without `--milestone` sets `keep: true`). No camera? Ask the owner for a photo and store it with `python3 /workspace/kalecam/rotate.py add --plant <plant-id> --file <photo> --source owner --copy`.

---

## Re-onboarding

| Situation | What to do |
|---|---|
| **Plant replaced** (a new plant in the same spot) | Mark the old profile `status: retired`, log `retired` in its log, and start fresh with a **new `<plant-id>`**. Re-ask only what changed. Usually the goal and constraints carry over; confirm with "Same goal as the last one?" |
| **Plant moved** (new spot, new pod, new camera) | Keep the ID. Update `location` and `camera_regions`, log `moved`, and re-ask only the affected Light & environment questions (L1 and L4 for a new spot; L2–L3 only if the light differs). If it joined a pod that already has a block, copy that and confirm. Re-derive thresholds. Expect a short adjustment period and don't alert on it. |
| **Setup changed** (light swapped, schedule or mode changed, moved outdoors or in; or photos show it: a different lamp, a new color cast, lights-on times shifting in photo timestamps) | Confirm the change in one line, then re-ask **only the affected questions** (new light → L2, plus L3 if control changed; new hours → L3; season or location → L4). Update `light_environment` (with sources), re-derive thresholds, and log `profile_updated` with a `light_environment:` note. Apply it to every plant in the pod. |
| **ID corrected** (it wasn't what we thought) | Keep the ID if the plant is the same, otherwise start a new one. Rebuild needs, targets, watch_list, stage_model, and toxicity. Log `profile_updated` and tell the owner what changed and why. |
| **Goal changed** (e.g., "let it flower for the bees") | Update `owner_goal`, possibly `purpose` and `stage_model`, and adjust the watch_list. One confirmation line is enough. |
| **Profile missing or corrupt** | Rebuild from the log, photos, and one or two confirming questions. Don't re-run the whole interview. |

---

## Several plants in one pod

- **One profile and one `<plant-id>` per plant**, even when they share a pot. A pot of grocery basil that stays together counts as one plant; divided clumps get their own IDs.
- **Record which part of each camera frame belongs to which plant** (`camera_regions`: a plain description plus x, y, w, h as fractions of the frame). Update it when plants grow into each other or get moved.
- Store each frame under every plant it shows, or use a group folder, per the photo-intake design.
- **`light_environment` is shared by the pod**: ask once, copy it into each roommate's profile, and update all of them together. `heat_welcome` can still differ per plant (a warmth-loving pepper next to heat-shy lettuce).
- Shared sensors (air temperature, RH, light) apply to every plant in the pod. Soil moisture probes belong to one pot. Say which.
- **Conflicting needs**: if roommates want different conditions (a succulent next to basil), say so during onboarding, propose the best compromise or a better spot, and set each profile's targets honestly rather than pretending both can be happy.
- Pests and disease spread between neighbors. A problem on one plant adds a watch item for the others.

---

## Profile format

Profiles live at **`/workspace/grow-profiles/<plant-id>.md`**: a YAML front block, then a prose **care brief** in KALE's voice. Blank template: `/workspace/kalecam/profiles/PROFILE-TEMPLATE.md`. Worked example (clearly marked): `/workspace/kalecam/profiles/EXAMPLE-grocery-basil.md`. (Both are installed by **kalecam-setup**.)

| Field | Contents |
|---|---|
| `plant_id`, `status` | Permanent ID; `active` or `retired` |
| `common_name`, `species`, `cultivar` | Cultivar is `unknown` unless tagged or confirmed |
| `id_confidence`, `id_basis` | high / medium / low, and what it rests on (tag, owner, photo traits) |
| `purpose`, `purpose_detail` | Purpose class (plant-photo-diagnosis, Identification reference) and a one-line specific |
| `origin` | nursery, grocery-store, cutting, seed, gift, volunteer, unknown |
| `acquired`, `day_basis`, `estimated_age` | Date, `sown` or `acquired`, and an age estimate |
| `location`, `camera_regions` | Pod or zone, and the part of each camera frame that shows this plant |
| `light_environment` | Setting, light type/fixture/modes and current mode, dimming, schedule and photoperiod, estimated DLI, `heat_welcome`, climate, and a source/confidence per field (block below) |
| `owner_goal` | The success definition, in the owner's words |
| `constraints` | Pets, kids, budget, time or travel, space, light, organic-only, taste |
| `current_stage`, `stage_model` | From growth-stage-tracker |
| `needs` | Light (DLI/PPFD, photoperiod), temperature day/night and never-below, RH/VPD, watering approach, feeding (approach, EC, pH), media, pot size |
| `cravings` | What this plant especially loves, in plain words |
| `targets` | Numeric ranges the daily review checks, the `target_source`, alert durations, and `adaptive_basis` (how `light_environment` shaped them) |
| `watch_list` | Specific early-warning signs, each with its meaning and first response |
| `milestones_expected` | Next milestones with rough dates |
| `toxicity` | Pets and kids heads-up, "none well known", or "unknown" |
| `alert_prefs` | Channel placeholder, quiet hours, milestone messages yes/no, level of detail |
| `confirmed_by_owner`, `confirmed_date` | `no` means provisional |
| `history` | Append-only list of `{date, by, change}` |

**`light_environment` block** (put it after `location`; unknown values are `null` or `unknown`):
```yaml
light_environment:                   # shared by every plant in the pod
  setting: <indoor-room | tent | greenhouse | covered-outdoor | open-outdoor | unknown>
  setting_detail: <e.g. "2x2 ft tent", "east-facing porch", or null>
  light:
    type: <sun | grow-light | both | unknown>
    fixture: <make/model or short description, or unknown>
    actual_watts: <n or null>
    advertised_watts: <n or null>    # "equivalent" figure, if that's what the label shows
    modes: [<veg | bloom | full | ...>]   # [] if single-spectrum
    current_mode: <mode or null>
    dimmable: <yes | no | unknown>
    dim_level: <e.g. "75%" or null>
  schedule:
    control: <always-on | timer | bridge | manual | sun-only | unknown>
    on: <HH:MM or null>
    off: <HH:MM or null>
    photoperiod_h: <n or null>       # outdoor / sun-only: null (day length is used instead)
  estimated_dli_mol_m2_day: <n, min-max, or null>
  heat_welcome: <welcome | neutral | problem | unknown>
  climate:
    region: <e.g. "hot dry summers, mild winters", or unknown>
    zip: <only if the owner offered it, else null>
    forecast_checks: <yes | no>      # yes for greenhouse / covered-outdoor / open-outdoor
  sources:                           # per field: where it came from, how sure
    setting: {source: <owner | photo | inferred>, confidence: <high | medium | low>}
    light: {source: <label-photo | owner | spec-lookup | photo | inferred>, confidence: <...>}
    schedule: {source: <owner | bridge | photo-timestamps | inferred>, confidence: <...>}
    estimated_dli: {source: <ppfd-map | watts-estimate | sensor | sun-estimate>, confidence: <...>}
    heat_welcome: {source: <owner | inferred>, confidence: <...>}
    climate: {source: <owner | forecast | inferred>, confidence: <...>}
  last_checked: <YYYY-MM-DD>
```

**Care brief** (after the YAML): 3–6 sentences covering what it is, why it's here, what success looks like, what it craves, what KALE watches most closely, and anything the owner should know. Useful first, one dry line at most.
