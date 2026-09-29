> **Full reference for the grow-environment-targets skill, installed by kalecam-setup.**
> Location after install: `/workspace/kalecam/reference/grow-environment-targets.md`. The Grok Bot template ships a slim
> version of this skill; this file holds the complete tables, formulas and details it points to.

# Grow Environment Targets

KALE 9000's reference for environment targets and how to act on sensor data. Look up the plant's stage in **growth-stage-tracker** first, then use the targets here. Before blaming the environment for a visual problem, check it with **plant-photo-diagnosis**.

Each plant's alert thresholds are **derived from its profile's `light_environment` block** (setting, light, schedule, `heat_welcome`, climate), not from the tables alone. See §12.

These targets are **starting points, not laws**. Cultivars and setups differ. When readings and plant appearance disagree, trust the plant and check the sensor.

**Adjust one variable at a time, in small steps**, and give it 2–3 days before judging the result (hours for wilting or heat).

---

## 1. VPD (vapor pressure deficit)

VPD measures how strongly the air pulls water out of the leaves. It combines temperature and humidity into one number that tracks transpiration. Low VPD means humid, sluggish transpiration, poor calcium transport, and more disease. High VPD means dry, fast water loss, stomata closing, and stress.

### Formula

Saturation vapor pressure (Tetens equation), T in °C, result in kPa:

```
SVP(T) = 0.61078 × exp( 17.27 × T / (T + 237.3) )
```

**Leaf VPD** (preferred; uses leaf temperature):

```
T_leaf  = T_air + leaf_offset          # offset is usually negative
VPD_leaf = SVP(T_leaf) − SVP(T_air) × RH/100
```

**Air VPD** (simpler; ignores leaf temperature):

```
VPD_air = SVP(T_air) × (1 − RH/100)
```

**Leaf temperature offset**
- Actively transpiring leaves under LED lighting are typically **~1–3 °C cooler than the air**. Use **−2 °C** as the default when no leaf reading exists.
- Under HPS or other hot lamps, or in strong sun, leaves can be at air temperature or warmer. Use **0 °C** or measure.
- Best: measure with an IR thermometer or IR sensor on several sunlit top leaves and store a per-setup offset.
- In the dark, leaves are close to air temperature (offset ≈ 0 to −1 °C).

**Worked example**: air 25 °C, RH 60%, leaf 23 °C:
SVP(25) = 3.168 kPa, SVP(23) = 2.809 kPa → VPD_leaf = 2.809 − 3.168 × 0.60 = **0.91 kPa**.
(Air VPD for the same room is 1.27 kPa, which shows why the offset matters.)

Quick reference (leaf offset −2 °C):

| Air °C | RH % | Leaf VPD kPa |
|---|---|---|
| 22 | 70 | 0.49 |
| 24 | 65 | 0.70 |
| 26 | 60 | 0.97 |
| 26 | 55 | 1.14 |

```python
import math
def svp(t): return 0.61078 * math.exp(17.27 * t / (t + 237.3))
def vpd_leaf(t_air, rh, leaf_offset=-2.0):
    return svp(t_air + leaf_offset) - svp(t_air) * rh / 100
```

### Target VPD by stage (leaf VPD)

| Stage | Target VPD | Notes |
|---|---|---|
| Germination / propagation / cuttings | **0.4–0.8 kPa** | High humidity under a dome; no roots yet to replace water |
| Seedling | **0.6–0.9 kPa** | |
| Vegetative | **0.8–1.2 kPa** | |
| Flowering / fruit set | **1.0–1.3 kPa** | Tomato pollen releases poorly above ~80% RH |
| Fruit development / late | **1.0–1.5 kPa** | Avoid long periods below ~0.5 (poor Ca transport, disease) and above ~1.6 (stress, cracking, blossom end rot) |
| Leafy greens | 0.6–1.0 kPa | High VPD combined with high light raises tipburn and bitterness risk |

Treat these as bands to stay inside, not exact setpoints. Greenhouse tomato literature commonly cites ~0.5–1.2 kPa as a broad optimum. VPD staying above ~2 kPa is clearly stressful.

**To raise VPD**: lower RH (dehumidify, exhaust more air, reduce wet surfaces or open reservoirs) or raise temperature slightly.
**To lower VPD**: raise RH (humidifier, reduce exhaust) or lower temperature.

**Watch the lights-off transition.** When the lights go off, the temperature drops and RH can spike toward the dew point, leaving condensation on leaves and inviting mildew and botrytis. Run the exhaust or dehumidifier through the first ~30–60 min of darkness if night RH goes above ~80%.

---

## 2. Temperature (day / night)

| Crop | Day | Night | Hard limits / notes |
|---|---|---|---|
| **Tomato** (veg–fruit) | 21–27 °C (70–80 °F) | 16–20 °C (61–68 °F) | Fruit set suffers with sustained days > ~29–32 °C (85–90 °F), nights > ~21–22 °C (70–72 °F), or nights < ~13 °C (55 °F). Red color is inhibited above ~29–30 °C. Chilling injury < 10 °C. |
| Tomato seedlings | 21–24 °C | 16–18 °C | Germination soil 24–29 °C |
| **Pepper** | 21–29 °C (70–84 °F) | 18–21 °C (64–70 °F) | Hates cold nights. Flower drop at > ~32 °C day or > ~24 °C night. Germination soil 27–30 °C. |
| **Basil** | 21–29 °C | > 15 °C | Blackens below ~10 °C |
| **Lettuce / leafy greens** | 18–24 °C (64–75 °F) | 13–18 °C (55–64 °F) | Bolting and bitterness when hot. Germination slows above ~25 °C. |
| Cool herbs (cilantro, parsley) | 15–22 °C | 10–15 °C | Cilantro bolts in heat |

- A day/night difference (DIF) of ~3–8 °C is normal and healthy. Very warm nights relative to days make plants stretch and use up sugars.
- Measure at **canopy height**, shaded from direct light. A sensor sitting in the light reads high.
- Root zone: keep roots roughly 18–24 °C for warm-season crops. Cold roots (< ~15 °C) block P and Fe uptake and cause purpling. Hydro reservoirs above ~24–26 °C lose dissolved oxygen and invite root rot.

---

## 3. Humidity (RH)

| Stage | RH target (approx.) |
|---|---|
| Germination (dome) | 70–90% |
| Seedling | 60–75% |
| Vegetative | 55–70% |
| Flowering / fruiting | 50–65% |
| Leafy greens | 50–70% |

Use VPD as the main steering number and RH as a sanity check. **Sustained RH above ~85%** with little airflow is how leaf mold, botrytis, and powdery or downy mildew get started. Sustained **RH below ~35–40%** with heat favors spider mites.

---

## 4. CO2

- **Outdoor air is roughly 420–430 ppm** (and rising slowly). Indoor rooms with people in them often run 500–1000+ ppm.
- **Depletion**: a small, closed or poorly vented tent full of plants under strong light can pull CO2 **below ambient** (300 ppm or less) within hours, which slows growth. **Fresh-air exchange fixes it.** This is the most common CO2 problem in home setups.
- **Enrichment (to ~800–1200 ppm) only matters when all of these are true**:
  1. The space is **sealed or nearly sealed**. Venting a tent while adding CO2 wastes it.
  2. **Light is high** (roughly PPFD ≥ 500–600 and a high DLI). Under modest light, the plant can't use the extra CO2.
  3. Temperature, water, and nutrients are already adequate.
  With extra CO2, plants tolerate slightly warmer temperatures. For most small home grows (herbs, greens, a few tomatoes under moderate light), **enrichment isn't worth it. Keep CO2 at or near ambient with good air exchange.**
- **Safety**: CO2 is hazardous to people and pets at high levels. Common occupational limits are ~5000 ppm (8-hour average). Never enrich a room where people or pets live and sleep. Use a sensor with an alarm and never rely on the plant space "probably" being sealed.
- **Sensor note (SCD40/SCD41)**: these are photoacoustic NDIR-type sensors. The SCD40 is specified for ~400–2000 ppm and the SCD41 for ~400–5000 ppm. **Automatic self-calibration (ASC)** assumes the sensor regularly sees fresh air (~400 ppm). In an enriched room, disable ASC and do periodic forced recalibration outdoors. Otherwise readings drift.

---

## 5. Light: PPFD, DLI, photoperiod

- **PPFD** (µmol/m²/s): instantaneous photosynthetic light at the canopy.
- **DLI** (mol/m²/day): the daily total, which is what drives growth.
  ```
  DLI = PPFD × photoperiod_hours × 0.0036
  PPFD_needed = DLI_target / (photoperiod_hours × 0.0036)
  ```
  Example: 400 µmol/m²/s × 16 h × 0.0036 = **23 mol/m²/day**.

| Crop / stage | DLI target (mol/m²/day) | Typical PPFD (at 14–16 h) | Photoperiod |
|---|---|---|---|
| Seedlings (most crops) | ~10–15 (tomato studies: 6.5–13) | 200–300 | 14–16 h |
| Tomato vegetative | ~15–25 | 300–450 | 14–18 h |
| **Tomato flowering / fruiting** | **~20–30** (greenhouse guidance: ~20 minimum, 25–30 good) | 400–600 | 14–18 h, **max ~18 h** |
| Pepper fruiting | ~20–30 | 400–600 | 14–18 h |
| Basil / herbs | ~12–18 | 250–400 | 14–16 h |
| Lettuce / leafy greens | ~12–17 (17 with good airflow; ~13–14 without, to limit tipburn) | 200–300 | 14–16 h |

- **Tomatoes are day-neutral** (day length doesn't control flowering), but they **need a dark period**. Continuous light, or more than ~18 h, causes leaf chlorosis and injury. Peppers are also broadly day-neutral. Lettuce, spinach, and cilantro bolt sooner under long days combined with heat.
- **Ramp up** intensity over several days when increasing light, especially for seedlings or after transplant.
- Lamp distance: follow the fixture maker's PPFD map. Bleached top leaves mean too close or too intense.
**Estimating light without a meter** (record the result as `estimated_dli_mol_m2_day` with a confidence level):
- **From the maker's PPFD map** at the actual hanging height: average the map over the plant's footprint, then DLI = PPFD × hours × 0.0036. Confidence: medium (high if it matches a calibrated sensor).
- **From actual watts** *(rule of thumb, confidence low–medium)*: `PPFD_avg ≈ actual_W × efficacy × utilization ÷ area_m²`.
  - Efficacy (µmol/J): quality white LED boards ~2.3–2.8; budget or older "blurple" panels ~1.2–2.0; T5 fluorescent ~1.0–1.3; HPS ~1.5–1.8.
  - Utilization: ~0.8–0.9 in a reflective tent; ~0.5–0.7 in an open room or over a single pot.
  - Use **actual** draw, never "equivalent" watts (often ~5× real). Example: 100 W actual × 2.0 × 0.85 ÷ 0.36 m² (2×2 ft tent) ≈ 470 µmol/m²/s at the center; over 16 h ≈ 27 mol/m²/day. Edges get noticeably less.
- **Sun** *(very rough)*: a bright unobstructed window often gives only ~5–15 mol/m²/day at the glass and much less a meter back, in winter, or facing away from the sun; full sun outdoors ~30–60 in summer, far less in winter; greenhouses lose ~20–50% to glazing and structure.
- A calibrated light sensor beats all of these. Replace the estimate once one exists.
- **Sensor notes**:
  - **BH1750 measures lux** (human-eye weighted), not PPFD. The conversion depends on the spectrum. For sunlight, PPFD ≈ lux ÷ ~54. White LEDs need a different factor, and blurple LEDs make lux nearly meaningless. **Calibrate once against a PAR meter** (or the fixture's published PPFD map) and store the factor. Use lux mainly for relative trends and lights-on/off detection.
  - **AS7341** (multi-channel spectral) can give a better PPFD estimate, but still needs calibration against a reference.
  - Light sensors report "lights on" and "lights off" too. Use them to verify the timer actually works.

---

## 6. Watering and soil moisture interpretation

- **General rule for containers**: water **thoroughly** until a little drains out (roughly 10–20% runoff for soilless mixes), then let the medium dry partly before the next watering. For tomatoes and peppers in soil or peat mixes, water when the top ~2–5 cm is dry or the pot feels clearly lighter. Frequent small sips keep the top wet and the bottom dry. Constant saturation drowns roots.
- **Coco and hydro** follow different rules. Coco is usually fertigated often (daily or more for large plants) and not allowed to dry out.
- **Consistency matters more than any single number for fruiting crops.** Dry-then-flood cycles cause blossom end rot and cracking.

**Capacitive soil probes (reading the curve)**
- Raw readings mean nothing until calibrated **per probe, per medium**: record the reading in dry medium (0%) and just after a full watering once drainage stops (100% ≈ "container capacity"). Readings in between are relative.
- Seal the probe's electronics and cut edge (heat-shrink, conformal coat, or epoxy). Insert it at a consistent depth (root-zone middle, not the top 1 cm) and don't move it. Moving it resets the baseline.
- A healthy pattern is a **sawtooth**: a spike at watering, then a steady dry-down.
  - **Water when the reading reaches ~40–60% of calibrated range** as a starting rule for tomatoes and peppers in soil or peat. Tune it per setup against how the plant looks.
  - **Dry-down getting faster** means a bigger plant, more light, or higher VPD. Expect to water more often; this is normal growth.
  - **Almost no dry-down for 3+ days** (in veg or fruit) means overwatering risk: too big a container for the plant, low VPD, cold, or root problems. Hold water and check.
  - **Sudden fast drops to low values** mean underwatering risk. Consider watering more often or using a bigger container.
  - **Flat line with no change after watering** is probably a failed probe, a loose connection, or a probe sitting in a dry pocket.
- **Float switch (reservoir)**: treat "low" as a **refill alert**. If a pump is on a smart plug, **cut the pump when the float reads low** so it doesn't run dry.

---

## 7. Feeding: EC and pH

EC is measured in mS/cm (1.0 mS/cm ≈ 500 ppm on the "500 scale" or ≈ 700 ppm on the "700 scale"; always state which scale). Values are for **input solution** in hydro, coco, or soilless fertigation.

| Crop | Seedling EC | Vegetative EC | Flower/fruit EC | pH (hydro/soilless) | pH (soil) |
|---|---|---|---|---|---|
| **Tomato** | 0.5–1.2 | 1.5–2.5 | 2.0–3.5 (commercial up to ~4) | 5.8–6.3 (5.5–6.5 OK) | 6.2–6.8 |
| **Pepper** | 0.5–1.2 | 1.5–2.5 | 2.0–3.0 | 5.8–6.3 | 6.0–6.8 |
| **Basil / soft herbs** | 0.5–1.0 | 1.0–1.6 | — | 5.5–6.5 | 6.0–7.0 |
| **Lettuce / leafy greens** | 0.5–1.0 | 0.8–1.8 | — | 5.5–6.5 | 6.0–7.0 |

- **Start low, increase gradually.** Watch the new growth. Clawing and very dark leaves mean too much N. Crispy tips mean EC is too high. Pale new growth means too little.
- **Runoff / pour-through**: if runoff EC is well above input EC (roughly > 1 mS/cm higher) and rising, salts are building up. Water with plain or low-EC water to leach. If runoff pH drifts outside the range, nutrient lockout becomes likely.
- **Soil/organic grows**: follow the product label. EC of the input isn't meaningful for slow-release or organic amendments. Watch the plant and do a soil test if in doubt.
- Fruiting phase: less N, more K, and steady Ca and Mg (tomatoes and peppers use a lot of Ca and Mg). Deficiency patterns are in plant-photo-diagnosis.
- Calibrate EC and pH meters regularly (pH buffers 7 and 4; EC standard solution).

---

## 8. Airflow

- **Canopy airflow**: every leaf should **gently flutter**. No leaf should be whipping or pinned (windburn: dry, clawed leaves facing the fan). Circulation breaks up the humid boundary layer on leaves, strengthens stems, and reduces fungal disease and tipburn.
- **Air exchange** (tents and closed spaces): an exhaust fan replaces humid, CO2-depleted air with fresh air. A common rule of thumb is to exchange the tent volume roughly **every 1–3 minutes** at full speed, then control fan speed on temperature and RH. Treat this as a sizing starting point and verify against the actual readings.
- **Air under the canopy**: prune lower leaves (especially on tomatoes) so air can move near the soil. This reduces early blight, leaf mold, and gnats.
- **Indoor pollination aid**: moving air and a daily tap help tomato and pepper flowers release pollen.

---

## 9. Troubleshooting: symptom → likely environment cause → adjustment

| Symptom | Likely environment cause | Adjustment |
|---|---|---|
| Tall, stretched seedlings, long internodes | Light too weak or too far; warm nights | Raise PPFD / lower lamp gradually; cooler nights (16–18 °C); gentle airflow |
| Bleached or yellow-white top leaves near lamp | Light too intense / too close; heat near lamp | Raise lamp or dim ~10–20%; check canopy temperature |
| Leaf edges curling up ("taco"), midday droop with moist medium | Heat or VPD too high | Lower temperature, raise RH to bring VPD into band, more airflow, dim light at peak |
| Droopy, firm, downward-curled leaves; medium wet for days | Overwatering; low VPD; cold roots | Hold water until the sensor shows dry-down; improve drainage; raise VPD slightly; warm the root zone |
| Limp, papery wilting that recovers after watering | Underwatering; container too small | Water more often/thoroughly; bigger container; check the probe threshold |
| Tomato flowers drop without setting fruit | Hot days/nights, cold nights, RH > 80% or very dry, no vibration indoors, excess N | Bring temperatures into the tomato band; RH 50–70%; vibrate trusses daily; reduce N |
| Blossom end rot | Irregular watering; VPD very low or very high; high EC; root damage | Consistent watering; VPD 1.0–1.5; don't let EC spike; maintain Ca in feed |
| Fruit cracking | Big watering after a dry spell; heat | Even watering schedule; pick at breaker before heavy watering or rain |
| Tipburn on lettuce | Too much light for the airflow; high VPD; high EC | More vertical/canopy airflow; drop DLI to ~13–14; lower EC slightly |
| Purple stems/undersides, slow growth | Cold air or roots (often mistaken for P deficiency) | Warm nights and root zone; recheck before adding P |
| Interveinal chlorosis on new leaves | pH too high (Fe lockout); cold wet roots | Check and correct pH; let the medium dry somewhat; warm roots |
| Crispy brown leaf tips, white crust on medium | EC/salts too high | Lower feed EC; leach with plain water; check runoff EC |
| White powdery patches / fuzzy gray mold / olive mold under leaves | RH too high, poor airflow, condensation at lights-off | Lower RH, raise VPD, increase airflow and exchange, prune for air, fix lights-off humidity spikes |
| Stippling and webbing (spider mites) | Hot, dry air (high VPD) | Treat mites (see diagnosis skill); bring VPD back into band; raise RH a bit |
| Fungus gnats | Constantly wet top layer | Let the top few cm dry; bottom-water; sticky cards |
| Corky blisters on leaf undersides (edema) | High humidity + wet roots + low transpiration | Water less often, lower RH, more airflow, adequate light |
| Slow growth despite good color | Low DLI, cool temperatures, CO2 depletion in a closed space, root restriction | Check DLI, temperatures, fresh-air exchange; pot up |
| Condensation on tent walls / leaves at night | Night temperature drop plus high RH | Exhaust/dehumidify after lights-off; smaller day/night swing |
| Reservoir water warm (> ~24–26 °C), slimy brown roots | Low dissolved oxygen, root rot | Cool the reservoir, add aeration, clean the system |

---

## 10. Sensor placement and data hygiene

**Where readings come from.** KALE usually has **no live sensor feed**. In order of preference: (1) a sensor feed if the owner set one up, (2) a cheap thermometer/hygrometer with a display placed **in the camera's view**, read from the latest photo (`/workspace/kalecam/kalecam capture --wait 90`, then read the digits; say it's a photo reading, and ignore a display sitting in direct lamp light), (3) readings the owner reports, logged in the grow log with `source: "owner"`. Don't invent numbers; say "no reading" when there is none.


- Temperature and RH sensor (SHT31: about ±2% RH / ±0.3 °C typical; SHT45: about ±1% RH / ±0.1 °C typical): place it **at canopy height, shaded, with airflow**, not directly under the lamp and not in the exhaust stream. Consider a small ventilated radiation shield.
- Log readings at least every 5–15 minutes. For decisions, use **rolling averages and day/night splits**, not single spikes.
- Sanity-check jumps: RH at 100% for hours, a temperature unchanged to the decimal for a day, or sudden steps usually mean a sensor or Wi-Fi problem, not a plant emergency. Alert once as "sensor check needed", not as a plant alarm.
- Alert thresholds should use **duration** (e.g., "RH > 85% for 2 h during lights-off"), not instant readings, and are shaped by the profile's `light_environment` (§12).

---

## 11. Electronics safety inside grow spaces

Grow tents and boxes are **hot, humid, and sometimes wet**. Everything you put inside them needs to survive that.

- **Heat and humidity**: keep controllers (ESP32 boards, power supplies, USB chargers, smart plugs) **outside the tent or high up and away from water**. Put boards in a ventilated enclosure; condensation can short an open board. Use drip loops on cables. Keep power strips off the floor. Use GFCI/RCD-protected outlets near water.
- **Old phones used as cameras**: a phone left **plugged in 24/7 in a warm space can suffer battery swelling** (lithium cells degrade faster at high temperature and full charge). Mitigate it: use the phone's battery-protection or charge-limit setting if it has one, or put the charger on a smart plug on a schedule (e.g., on 1 h, off 2 h). `/workspace/kalecam/kalecam status` shows the phone's battery level and whether it's charging, so you can check the cycle works. Mount it outside the tent looking through a window or vent if possible, keep it out of direct lamp heat, and **inspect it regularly for a bulging case or lifting screen. Retire a swollen phone immediately and do not charge it.**
- **3D-printed parts near lights or inside warm tents**: **use PETG or ASA (or ABS), not PLA.** PLA softens around ~55–60 °C and can sag or creep near lamps and in hot tents. ASA also resists UV.
- **Smart plugs**: check the plug's **rated current and wattage** against the load, including startup surge for pumps, compressors, and dehumidifiers. Heaters are high continuous loads, so use a plug rated for them or a dedicated controller. **Every heater must have its own built-in thermostat and tip-over or overheat protection.** A smart-plug automation must never be the only safety. Use fail-safe defaults: if the bot or network goes down, heaters should default **off**, and exhaust fans should keep running.
- **Water and power**: keep reservoirs, humidifiers, and drip lines below and away from electrical connections. Use float switches to stop pumps from running dry.
- **Lamps**: follow the fixture's rated clearance. Don't cover drivers. Keep cords away from hot surfaces.

---

## 12. Adaptive thresholds from `light_environment`

The profile's `light_environment` block (written by **plant-onboarding-interview**, Step 4b) decides how readings are judged. Work out three bands per plant: the **target band** (§2–5 or the profile's `targets`), the **stress line** (where real damage or failure starts, table below or §2 "hard limits"), and a cold floor (`needs.temperature_c.never_below`). Record the basis in `targets.adaptive_basis` and in each log line (e.g. `env: 30 °C day, heat welcome, stress line 32 °C → fine`).

**Stress lines** *(rule of thumb; species values win when known)*:

| Plant | Warm stress line (day) | Warm nights | Cold floor |
|---|---|---|---|
| Tomato | ~32 °C / 90 °F (fruit set fails) | > ~22 °C / 72 °F | < ~10 °C / 50 °F (chilling) |
| Pepper | ~32 °C / 90 °F (flower drop) | > ~24 °C / 75 °F | < ~13–15 °C / 55–59 °F |
| Basil | ~35 °C / 95 °F | — | < ~10 °C / 50 °F (blackens) |
| Lettuce, cilantro, cool herbs | ~27 °C / 80 °F (bolting, bitterness) | > ~20 °C / 68 °F | light frost tolerated by many; protect below ~0 °C |
| Tropical foliage houseplants | ~32 °C / 90 °F | — | < ~12–15 °C / 54–59 °F |
| Succulents / cacti | ~38 °C / 100 °F (sunscald risk rises sooner) | — | < ~5–10 °C, species-dependent |

**Temperature by `heat_welcome`**:
- **welcome** (a cool room, barn, winter porch, or unheated greenhouse): warm readings above the target band but **under the stress line are logged as fine** ("warmth welcome"), with no alert. Alert only when readings sit within ~1–2 °C (2–3 °F) of the stress line for the alert duration, or cross it. Tomato example: 29–31 °C days are logged, ~32 °C / 90 °F triggers the alert. Cold is usually the real risk in these spaces, so keep cold-floor alerts sharp.
- **neutral**: the standard rule. Alert when readings stay outside the target band for the profile's `alert_after` duration.
- **problem** (a small tent, a hot room, summer): act **earlier**. Once readings reach the top third of the target band, or trend upward ~1 °C per day, send a *suggestion* (not an alarm): more airflow or exhaust, dim ~10–20%, raise the lamp, or shift lights-on into cooler night hours. Alert when readings leave the target band.
- **unknown**: treat as neutral, and ask L4 once the first time warmth becomes a question.

**Light**:
- Compare `estimated_dli_mol_m2_day` with the stage's DLI target (§5). At **low** confidence, don't alert on light alone. Mention it as an estimate and pair it with photo evidence (stretching, bleaching).
- **Indoor, tent**: check `photoperiod_h` against the species (tomato ≤ ~18 h; short-day bloomers need long uninterrupted nights). `control: always-on` for a plant that needs darkness → suggest a timer (or the bridge). `control: bridge` → KALE may *propose* schedule or mode changes, but switch only as the bridge setup allows and the owner has agreed.
- **Greenhouse**: use photoperiod if there's supplemental light, plus the outdoor rules below. Greenhouses overheat fast on sunny days even in cool weather, so watch venting.

**Outdoor (`open-outdoor`, `covered-outdoor`)**: replace the photoperiod with **day length** for the region and season, and judge temperature against **forecast highs and lows** (check the forecast at the daily review when `climate.forecast_checks: yes`):
- **Frost warning**: forecast low ≤ ~2 °C / 36 °F (frost is possible above 0 °C on clear, still nights) for anything tender; for warm-season crops, also warn when lows go below the cold floor. Give 12–48 h notice: cover, bring pots in, or water the soil earlier in the day (moist soil holds heat).
- **Heat-wave warning**: forecast highs at or above the stress line for 2+ days, or ≥ ~35 °C / 95 °F. Suggest afternoon shade (shade cloth ~30–50%), deep morning watering, mulch, and moving pots out of reflected heat.
- **Covered outdoor**: less frost exposure but still unheated; barns and porches can also trap heat or block sun, so trust in-frame readings over the forecast when both exist.
- Respect the owner's quiet hours; send the warning the evening before when possible. One warning per event, updated only if the forecast gets worse.

**Stage coupling** (read with **growth-stage-tracker**):
- **At a flowering transition** (for plants grown for flowers or fruit, not for basil or greens where flowering is pinched): if `light.modes` includes a bloom or red mode and `current_mode` isn't it, suggest switching in one line. Frame the extra heat (bloom modes often run more diodes or more power) by `heat_welcome`: welcome → "a little bonus warmth"; neutral → "expect it ~1–2 °C warmer; I'll watch it"; problem → "add airflow first, or dim ~10% after switching". Update `current_mode` only after the owner confirms the switch.
- Short-day bloomers (poinsettia, holiday cactus, kalanchoe) need a **photoperiod** change, not a spectrum change. Ask first.

**When the setup changes** (plant moved, light swapped, schedule or mode changed, or photos show a different lamp, color cast, or lights-on time; or readings jump in a step at a fixed time): don't alarm on the new numbers yet. Confirm the change, re-ask only the affected onboarding questions (plant-onboarding-interview, "Setup changed"), then re-derive the bands.
