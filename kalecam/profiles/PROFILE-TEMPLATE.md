---
# KALE 9000 plant profile — TEMPLATE
# Copy to /workspace/grow-profiles/<plant-id>.md and fill in.
# Leave unknown values as null. Never invent a number: write null and let the
# daily review say "no target on file". Mark rule-of-thumb values in target_source.
plant_id: <plant-id>                 # lowercase, digits, - or _ ; never reused (e.g. basil-01)
status: active                       # active | retired
common_name: <common name>
species: <scientific name or null>
cultivar: <cultivar or unknown>
id_confidence: <high | medium | low>
id_basis: <tag | owner | photo traits: ...>
purpose: <fruiting-edible | leafy-greens | herb-culinary | herb-medicinal | microgreens-sprouts | flowering-ornamental | foliage-houseplant | succulent-cactus | carnivorous | other>
purpose_detail: <one line, e.g. "pesto basil">
origin: <nursery | grocery-store | cutting | seed | gift | volunteer | unknown>
acquired: <YYYY-MM-DD>               # or sowing date for seed-grown plants
day_basis: <sown | acquired>
estimated_age: <e.g. "~4-6 weeks from sowing" or unknown>
location:
  pod: <pod or zone name>
  camera_regions:                    # which part of each camera frame is this plant
    - camera: <camera>
      region: <e.g. "left third" or x,y,w,h as fractions of the frame: 0.00,0.10,0.35,0.80>
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
owner_goal: <what success looks like, in the owner's words>
constraints:                         # empty list if none
  - <pets: cat | dog | none>
  - <kids: yes | no>
  - <budget / time / travel / space / light / organic-only / taste preferences>
current_stage: <stage name from the stage model>
stage_model: <tomato | pepper | basil | lettuce | annual-fruiting | leafy-herb-annual | microgreens | perennial-foliage | flowering-ornamental | succulent-cactus | bulb | species:<species>>
needs:
  light:
    dli_mol_m2_day: <min-max>
    ppfd_umol_m2_s: <min-max>
    photoperiod_h: <n>
    notes: <e.g. "no more than 18 h">
  temperature_c:
    day: <min-max>
    night: <min-max>
    never_below: <n>
  humidity:
    rh_pct: <min-max>
    vpd_kpa: <min-max>
  watering: <approach in plain words, e.g. "water when top 2-3 cm is dry; never let it sit in water">
  feeding:
    approach: <e.g. "dilute balanced feed every 2 weeks in active growth">
    ec_ms_cm: <min-max or null for soil/organic>
    ph: <min-max>
  media: <e.g. "peat-based potting mix + perlite">
  pot: <size and type, drainage yes/no>
cravings:                            # what this plant especially loves, in plain words
  - <e.g. "warmth">
targets:                             # numeric ranges the daily review checks
  target_source: <species-model | crop-model | generic-model | first-principles | owner>
  temp_day_c: [<min>, <max>]
  temp_night_c: [<min>, <max>]
  rh_pct: [<min>, <max>]
  vpd_kpa: [<min>, <max>]
  dli_mol_m2_day: [<min>, <max>]
  soil_moisture_pct: {water_at: <n>, too_wet_above: <n>, too_wet_days: <n>}
  ec_ms_cm: [<min>, <max>]           # null if not measured
  ph: [<min>, <max>]                 # null if not measured
  alert_after: <e.g. "2 h outside range, or any reading below never_below">
watch_list:                          # early-warning signs KALE looks for with THIS plant
  - <sign> -> <what it means / first response>
milestones_expected:
  - {milestone: <name>, expected: <date or "~n days/weeks from now">}
toxicity: <heads-up for pets and kids, "none well known", or "unknown, check before letting pets or kids at it">
alert_prefs:
  channel: <owner's chosen channel placeholder>
  quiet_hours: <e.g. "22:00-07:00 local" or none>
  milestone_messages: <yes | no>
  detail: <brief | detailed>
confirmed_by_owner: no               # yes | no
confirmed_date: null                 # YYYY-MM-DD once confirmed
history:                             # append only; newest last
  - {date: <YYYY-MM-DD>, by: <kale | owner>, change: "profile created (provisional)"}
---

# <common_name> (<plant-id>) — care brief

<3–6 sentences in KALE's voice: what this plant is, why the owner has it, what success looks like, what it craves, the two or three things KALE is watching most closely, and anything the owner should know (toxicity, constraints). Useful first; one dry line at most.>

<!--
FIELD NOTES (delete in real profiles if you like)
- needs = what the plant wants, in words and ranges. targets = the numbers the daily
  review actually checks, with alert durations. Keep them consistent.
- confirmed_by_owner: no means the profile is PROVISIONAL. The daily review still uses
  it, but says "provisional" when quoting targets, and asks once for confirmation.
- Every edit appends a history line and a profile_updated event in
  /workspace/grow-log/<plant-id>.jsonl.
- A worked example is in /workspace/kalecam/profiles/EXAMPLE-grocery-basil.md.
-->
