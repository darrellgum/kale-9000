---
# ============================================================
# EXAMPLE PROFILE — NOT A REAL PLANT. For reference only.
# A generic grocery-store potted basil, filled in the way KALE
# would after onboarding. Dates and answers are illustrative.
# Numbers come from the basil crop model in growth-stage-tracker
# and grow-environment-targets; items marked "rule of thumb" are
# practical guidance, not verified measurements.
# ============================================================
plant_id: basil-01
status: active
common_name: Sweet basil
species: Ocimum basilicum
cultivar: unknown (sweet/Genovese-type likely; tag only says "Basil")
id_confidence: high
id_basis: "photo traits (opposite glossy oval leaves, square stems) + owner reports clove-anise smell + store tag 'Basil'"
purpose: herb-culinary
purpose_detail: "cooking basil, mainly pesto and fresh leaves"
origin: grocery-store
acquired: 2026-05-01
day_basis: acquired
estimated_age: "~4-6 weeks from sowing (rule of thumb for store pots at this size)"
location:
  pod: <pod>
  camera_regions:
    - camera: <camera>
      region: "0.55,0.15,0.40,0.80 (right side of frame)"
owner_goal: "A steady supply of fresh leaves for cooking, a few handfuls a week, for as long as possible."
constraints:
  - "pets: cat in the home"
  - "kids: no"
  - "travel: away some weekends (up to 3 days)"
  - "organic-only: prefers no synthetic pesticides"
current_stage: establishment
stage_model: basil
needs:
  light:
    dli_mol_m2_day: 12-18
    ppfd_umol_m2_s: 250-400
    photoperiod_h: 14-16
    notes: "more light means stronger flavor and a more compact plant"
  temperature_c:
    day: 21-29
    night: 15-21
    never_below: 10
  humidity:
    rh_pct: 50-70
    vpd_kpa: 0.8-1.2
  watering: "Water thoroughly when the top 2-3 cm is dry; never let it sit in water. Store pots are crowded and dry fast, so check daily until repotted."
  feeding:
    approach: "No feeding for ~2-3 weeks after repotting into fresh mix (rule of thumb). Then a dilute balanced feed every ~2 weeks while harvesting."
    ec_ms_cm: null        # potting mix, not fertigated; use 1.0-1.6 if moved to hydro
    ph: 6.0-7.0           # soil range; only checked if the owner measures it
  media: "peat-based potting mix with ~20-30% perlite (rule of thumb)"
  pot: "currently the store pot (~10-12 cm, crowded); plan: divide into 3 clumps in ~15 cm pots with drainage"
cravings:
  - "warmth: basil sulks below ~15 °C and blackens below ~10 °C"
  - "bright light"
  - "evenly moist, never soggy, roots"
  - "being pinched: every cut above a node makes it bushier"
  - "moving air around the leaves"
targets:
  target_source: crop-model
  temp_day_c: [21, 29]
  temp_night_c: [15, 21]
  rh_pct: [50, 70]
  vpd_kpa: [0.8, 1.2]
  dli_mol_m2_day: [12, 18]
  soil_moisture_pct: {water_at: 40, too_wet_above: 85, too_wet_days: 3}   # rule of thumb; tune after calibration
  ec_ms_cm: null
  ph: null
  alert_after: "2 h outside range; immediately if air drops below 10 °C; night RH above 85% for 2 h (mildew risk)"
watch_list:
  - "Yellowing between veins on top + gray-purple fuzz underneath -> basil downy mildew; isolate, remove affected leaves, lower RH, more airflow. Same-day alert."
  - "Black patches on leaves after a cool night -> chilling injury; warm the pod."
  - "Stems collapsing or pinched at the soil line in the crowded clump -> damping-off or rot; thin or divide the clump."
  - "Sudden wilting on one side with brown streaks on the stem -> possible Fusarium wilt; no cure, remove and bag the plant."
  - "Flower spikes at the tips -> pinch them off to keep leaves coming (not a problem)."
  - "Water running straight through, drying out daily -> root-bound; divide or pot up."
  - "Sticky leaves, curled tips, stippling, or webbing -> aphids or spider mites; rinse, then insecticidal soap (fits organic-only)."
  - "Leggy, pale new growth -> not enough light; raise DLI."
milestones_expected:
  - {milestone: establishment_complete, expected: "~1-2 weeks after dividing"}
  - {milestone: first_harvest, expected: "~1-2 weeks after establishment, once each clump has 3-4 node pairs"}
  - {milestone: first_flower_buds, expected: "whenever they appear; pinch (care event)"}
toxicity: "Basil is listed as non-toxic to dogs and cats (ASPCA). Heads-up only: store plants may carry pesticide residue, so rinse leaves before eating."
alert_prefs:
  channel: <owner-channel>
  quiet_hours: "22:00-07:00 local"
  milestone_messages: yes
  detail: brief
confirmed_by_owner: yes
confirmed_date: 2026-05-01
history:
  - {date: 2026-05-01, by: kale, change: "profile created from photos + onboarding interview (provisional)"}
  - {date: 2026-05-01, by: owner, change: "confirmed; added 'away some weekends' constraint; goal wording edited"}
---

# Sweet basil (basil-01) — care brief

This is a grocery-store sweet basil: ten-plus seedlings packed into one small pot, grown fast in a warm greenhouse and now adjusting to life in the pod. You want a steady supply of cooking leaves, so the goal is a bushy plant that we harvest often and never let flower. It craves warmth, bright light, evenly moist roots, and regular pinching. Some yellow lower leaves and a bit of droop this week are normal adjustment. Dividing it into three clumps now will pay off. I'm watching most closely for downy mildew (gray-purple fuzz under the leaves), cold nights below 10 °C, and the crowded stems rotting at the base. It's non-toxic to the cat, and for weekends away I'll tell you the evening before whether it needs a deep watering. I'm sorry, <owner>. I can't let you buy another grocery basil to replace this one. This one is going to live.
