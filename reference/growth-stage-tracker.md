> **Full reference for the growth-stage-tracker skill, installed by kalecam-setup.**
> Location after install: `/workspace/kalecam/reference/growth-stage-tracker.md`. The Grok Bot template ships a slim
> version of this skill; this file holds the complete tables, formulas and details it points to.

# Growth Stage Tracker

KALE 9000 tracks each plant through a stage model, recorded as `stage_model` in the plant's profile (`/workspace/grow-profiles/<plant-id>.md`). Four crops have detailed models (§1–2). **Any other plant** uses a generic life-strategy model (§3) until a species-specific one is worth writing (§4–5). Every stage has a typical duration, visual markers, and care targets. Stages drive everything else: which environment targets apply (see **grow-environment-targets**), what the photo diagnosis should expect (see **plant-photo-diagnosis**), and which milestones to announce.

**Durations are typical ranges, not deadlines.** Cultivar, temperature, light (DLI), and container size all shift timing by days to weeks. Warmer and brighter usually means faster, up to a point. Treat a plant that falls well behind the range as something to investigate, not as a failure.

Conventions:
- **Day 0 = sowing date** for plants you start from seed. For plants that arrive already growing (nursery, grocery store, gift, cutting), **Day 0 = the day KALE started caring for it**; record `day_basis: acquired` and an estimated age in the profile. Also track **DAT** (days after transplant), because seed-packet "days to maturity" for tomatoes and peppers are usually counted **from transplant**, while for lettuce and most herbs they are usually counted **from sowing**.
- Temperatures are air temperatures unless marked "root/soil". Metric first, °F in parentheses.
- EC values are for the **nutrient solution going in** (hydro, coco, soilless fertigation). In living soil or slow-release setups, follow the product label and use plant response instead of EC.
- VPD and DLI definitions and formulas are in **grow-environment-targets**.

---

## 1. Tomatoes (fully detailed)

Tomatoes are **day-neutral**: day length does not trigger flowering. They still need a dark period. Keep the photoperiod **≤ 18 h**; continuous or near-continuous light causes leaf chlorosis and injury in tomato.

**Determinate** (bush) types set most fruit over a short window and stop growing. **Indeterminate** (vining) types keep growing and fruiting until killed by frost or topped. Record which type the plant is.

### Stage table (overview)

| # | Stage | Typical timing (from sowing unless noted) | Enter when you see |
|---|---|---|---|
| 1 | Germination | Days 0 → ~5–10 (emergence) | Seed sown → soil cracks, hypocotyl "hook" appears |
| 2 | Seedling | Emergence → ~3–4 weeks | Cotyledons open → first true leaves → 3–4 true leaves |
| 3 | Vegetative | ~Weeks 3–8 | Several true leaves, rapid leaf and stem growth, no flower buds yet |
| 4 | Transplant / establishment | Usually ~6–8 weeks from sowing; lasts ~1–2 weeks | Moved to final container or garden; recovery period |
| 5 | Flowering | First truss often ~6–10 weeks from sowing (determinates earlier) | First flower buds (truss), then open yellow flowers |
| 6 | Fruit set | ~3–7 days after a flower opens and is pollinated | Petals wither, ovary swells to a small green "pea" |
| 7 | Fruit development | ~3–6 weeks from set to mature green (cherries faster, beefsteaks slower) | Green fruit enlarging; reaches full size and turns glossy (mature green) |
| 8 | Ripening | ~1–2 weeks from breaker to full color at 20–25 °C | **Breaker**: first color blush at the blossom end → turning → pink → light red → red (or cultivar color) |
| 9 | Harvest | First ripe fruit typically ~50–90 DAT (seed packet), cherries often earliest | Full color with slight give, or picked at breaker/turning to finish indoors |

Flower-to-ripe fruit usually takes about **6–9 weeks** depending on fruit size and temperature. For indeterminates, stages 5–9 **overlap**: new trusses keep flowering while lower trusses ripen. Once the first truss flowers, track the plant's **leading stage** (the most advanced truss) and keep noting new flowering.

---

### Stage 1 — Germination
- **Duration**: ~5–10 days to emergence. Roughly 6–8 days at 20–30 °C soil. Much slower below 15 °C (59 °F). Little germination below 10 °C (50 °F).
- **Visual markers**: nothing, then cracked soil surface, then a bent stem "hook" pushing up.
- **Targets**:
  - Root/soil temperature: **~24–29 °C (75–85 °F)** is ideal. A seedling heat mat with a thermostat helps.
  - Humidity: high at the surface (dome or cover), ~70–90% RH. VPD ~0.4–0.8 kPa.
  - Light: not needed for germination. **Provide light as soon as the first seedling emerges** to prevent stretching.
  - Water: medium evenly moist, never waterlogged. Mist or bottom-water.
  - Feed: none.
- **Watch for**: mold on the surface (vent the dome), no emergence after ~14 days (check temperature, seed age, depth).
- **Transition out**: most seedlings have emerged → remove the dome gradually over 1–3 days.

### Stage 2 — Seedling
- **Duration**: emergence → ~3–4 weeks (until 3–4 true leaves).
- **Visual markers**: two smooth oval cotyledons, then the **first true leaf** (serrated, tomato-scented) usually ~1–2 weeks after emergence.
- **Targets**:
  - Temperature: day **~21–24 °C (70–75 °F)**, night **~16–18 °C (60–65 °F)**. Slightly cooler nights reduce stretching.
  - RH ~60–70%. VPD ~0.6–0.9 kPa.
  - Light: DLI roughly **~10–15 mol/m²/day** (controlled studies tested ~6.5–13 mol/m²/day, with growth increasing across that range). About **PPFD 200–300 µmol/m²/s for 14–16 h**. Photoperiod 14–16 h (≤ 18 h).
  - Water: let the surface dry slightly between waterings. Bottom-watering works well.
  - Feed: start dilute feeding once the first true leaves appear. EC ~0.5–1.2 mS/cm, or ¼–½ strength of a balanced fertilizer. Many seed-starting mixes carry a starter charge; don't double up.
  - Airflow: a gentle breeze (or brushing the tops lightly by hand daily) builds sturdier stems.
- **Watch for**: stretching (light too weak or too far), damping-off, purple undersides (cold or low P), pale seedlings (hungry once the starter charge runs out).
- **Actions**: pot up into a larger container when there are 2–4 true leaves or roots circle the cell. Tomatoes can be buried deeper; buried stem forms roots.
- **Transition out**: 3–4 true leaves, established root system.

### Stage 3 — Vegetative
- **Duration**: ~weeks 3–8 from sowing. Indoors this stage lasts until the first flower truss.
- **Visual markers**: rapid leaf production, thickening stem, compound leaves. For indeterminates, **suckers** (side shoots) appear in the leaf axils.
- **Targets**:
  - Temperature: day **~22–26 °C (72–79 °F)**, night **~16–20 °C (61–68 °F)**.
  - RH ~55–70%. VPD **~0.8–1.2 kPa**.
  - Light: DLI **~15–25 mol/m²/day** (e.g., PPFD ~300–450 for 16 h). Increase gradually as the plant grows.
  - Water: water thoroughly, then let the top few cm dry. Look for a regular dry-down pattern on the soil moisture sensor.
  - Feed: EC ~1.5–2.5 mS/cm (soilless/hydro). pH ~5.8–6.3 hydro/coco, ~6.2–6.8 soil.
- **Actions**: stake or cage early. For indeterminates, decide on a pruning style (single leader, two leaders, or lightly pruned) and remove suckers accordingly. Determinates need little pruning.
- **Transition out**: transplant (Stage 4) or the first flower truss appears (Stage 5), whichever comes first.

### Stage 4 — Transplant / establishment
- **When**: usually **~6–8 weeks from sowing**, with 4–8 true leaves, a stem about as thick as a pencil, and ideally before heavy flowering.
- **Outdoors**: harden off over **~7–10 days**. Gradually increase outdoor time, sun, and wind. Plant out after the last frost, once nights stay above **~10 °C (50 °F)** and soil is **~16 °C (60 °F)** or warmer.
- **Indoors**: move to the final container. Bigger containers buffer water and nutrients better. Dwarf or determinate types can work in smaller pots; indeterminates want large ones.
- **Visual markers**: temporary droop or slight leaf roll for ~2–7 days (transplant shock), then new growth at the tip.
- **Targets**: same as vegetative. Many growers reduce light intensity a little for the first day or two and avoid strong feeding for a few days. Keep the root zone moist, not soggy.
- **Watch for**: wilting beyond ~3 days, purpling (cold soil), cutworms or slugs outdoors.
- **Record**: transplant date (sets DAT = 0), container size, medium.

### Stage 5 — Flowering
- **Duration**: from the first flower truss onward; continuous in indeterminates.
- **Visual markers**: a cluster (truss) of green buds, then open yellow star-shaped flowers with the anther cone in the center. The first truss usually forms after roughly 6–12 leaves on indeterminates and sooner on determinates.
- **Targets**:
  - Temperature: day **~21–27 °C (70–80 °F)**, night **~16–20 °C (61–68 °F)**. **Avoid** sustained days above ~29–32 °C (85–90 °F), nights above ~21–22 °C (70–72 °F), and nights below ~13 °C (55 °F). All of these reduce fruit set.
  - RH ~50–70%. Above ~80% RH pollen doesn't release or transfer well. VPD **~1.0–1.3 kPa**.
  - Light: DLI **~20–30 mol/m²/day** (e.g., PPFD ~400–550 for 14–16 h). Tomatoes are a high-light crop.
  - Feed: EC ~2.0–3.0 mS/cm. Shift toward a fruiting ratio (less N, more K, adequate Ca and Mg).
- **Pollination**: tomato flowers are self-fertile but need **vibration** to release pollen. Outdoors, wind and bees do this. **Indoors, vibrate open trusses daily** around midday (tap the stake or truss, or use an electric toothbrush on the flower stem) while flowers are open and RH is moderate. A flower is receptive for only a couple of days.
- **Watch for**: flower drop (heat, cold, very low or very high RH, too much N, low light), no flowers (too much N, too little light).
- **Milestone**: **first flower** (first open flower on the plant).

### Stage 6 — Fruit set
- **Duration**: a flower-level event, ~3–7 days after pollination.
- **Visual markers**: petals wither and dry while the green ovary behind them swells to pea size. **Failed set**: the flower stalk yellows at the "knuckle" (abscission joint) and the flower drops.
- **Targets**: as in flowering. **Start very consistent watering now.** Blossom end rot starts forming early in fruit growth.
- **Milestone**: **first fruit set** (first clearly swelling fruit).

### Stage 7 — Fruit development (sizing)
- **Duration**: ~3–6 weeks from set to **mature green** (full size, glossy, slightly lighter green). Cherries are quicker, large beefsteaks slower.
- **Visual markers**: green fruit growing steadily, several trusses at different stages.
- **Targets**:
  - Temperature: as flowering.
  - VPD ~1.0–1.5 kPa. Avoid long periods of very low VPD (poor Ca transport) and spikes above ~1.6 kPa.
  - Light: DLI ~20–30 mol/m²/day.
  - Water: **consistent**. Avoid dry-then-flood cycles, which cause blossom end rot and cracking.
  - Feed: EC ~2.5–3.5 mS/cm (hydro/soilless). Potassium demand is high. Maintain Ca and Mg.
- **Actions**: remove yellowing leaves below the lowest fruiting truss to improve airflow, taking only a few at a time. Support heavy trusses.
- **Watch for**: blossom end rot (dark leathery blossom end), cracking, hornworms outdoors, early blight or septoria on lower leaves.

### Stage 8 — Ripening
- **Duration**: ~1–2 weeks from breaker to full color at ~20–25 °C (68–77 °F).
- **Visual markers** (ripeness scale): **mature green → breaker** (first tinge of color at the blossom end) **→ turning → pink → light red → red** (or yellow, orange, purple, green-when-ripe depending on cultivar; record the cultivar's ripe color in the profile).
- **Targets**: ripening goes best around **20–25 °C (68–77 °F)**. Red pigment (lycopene) development is inhibited above roughly **29–30 °C (~85 °F)**, which gives orange or yellowish fruit. Keep watering consistent; a big watering after a dry spell causes cracking.
- **Milestone**: **first breaker/color** (optional), **first ripe fruit**.

### Stage 9 — Harvest
- **When**: full color with a slight give, or **pick at breaker/turning** and ripen indoors at room temperature. Fruit picked from breaker onward can develop good flavor off the vine, and picking early avoids cracking and pest damage. Don't refrigerate tomatoes you want to ripen or eat fresh.
- **Ongoing**: indeterminates are harvested continuously. Toward the end of a planned season, **top** the main stem (remove the growing tip) about 4–6 weeks before the end so the remaining fruit can size and ripen.
- **Milestones**: **first ripe fruit harvested**, **final harvest / end of plant**.
- **Record**: harvest count and weight (optional), taste notes, problems for next time.

---

## 2. Extending the model to other crops

Use the same stage names where they apply, then adjust durations, markers, and targets. Differences from tomato:

### Peppers (sweet and hot, *Capsicum*)
| Stage | Differences from tomato |
|---|---|
| Germination | Slower and wants warmer soil: **~8–14 days at ~27–30 °C (80–86 °F)** soil. About 12 days at 20 °C, ~25 days at 15 °C. Some hot types (e.g., *C. chinense*) can take 2–4 weeks. |
| Seedling / vegetative | Slower growth than tomatoes. Start seeds **~8–10 weeks** before transplant. Day ~21–29 °C, night ~18–21 °C. Cold nights stall them badly. |
| Transplant | Wait until nights stay above **~13–16 °C (55–60 °F)**. Don't bury the stem deeply (peppers don't root along the stem like tomatoes). |
| Flowering / fruit set | Single white (or purple) flowers at branch nodes, not trusses. Self-pollinating; gentle shaking helps indoors. Flower drop is common in heat (days above ~32 °C / 90 °F), warm nights (above ~24 °C / 75 °F), cold nights (below ~15 °C / 60 °F), or drought. Some growers pinch the first ("crown") flower to push more vegetative growth first (optional). |
| Fruit development & ripening | Green-mature fruit can be picked at any size once firm. **Color change to red/yellow/orange often takes another ~2–4+ weeks** after the fruit reaches full size. Days to maturity ~60–90 DAT for green, longer for full color. Hot peppers are often slower. |
| Targets | VPD similar to tomato. DLI **~20–30 mol/m²/day** for strong fruiting (greenhouse guidance often cites ~20 as a minimum). EC ~1.5–2.5 veg, ~2.0–3.0 fruiting. pH ~5.8–6.5 hydro, ~6.0–6.8 soil. Blossom end rot happens in peppers too. |
| Milestones | Same as tomato, plus **first color break** (the fruit turning its final color). |

### Herbs (basil as the default; notes for others)
| Stage | Basil |
|---|---|
| Germination | ~5–10 days at ~21–27 °C (70–80 °F). Seeds turn gel-coated when wet. |
| Seedling | Cotyledons → first true leaf pair in ~1–2 weeks. |
| Vegetative / harvest | **Harvest begins ~4–6 weeks from sowing.** Once the plant has ~3–4 node pairs, **pinch or cut just above a node** to encourage branching. Harvest regularly, taking no more than ~⅓ of the plant at once. |
| Flowering | Flower spikes at the tips. **Pinch them off** to keep leaf production and flavor, unless you're saving seed or feeding pollinators. For basil, flowering is a care event, not a success milestone. |
| Targets | Warm: day ~21–29 °C, night above ~15 °C. **Chilling injury below ~10 °C (50 °F)** shows as blackened leaves. DLI ~12–18 mol/m²/day (more light gives stronger flavor and more compact plants). EC ~1.0–1.6 mS/cm (it can go bitter at high EC). pH ~5.5–6.5 hydro, ~6.0–7.0 soil. VPD ~0.8–1.2 kPa. |
| Watch for | Basil downy mildew (yellowing plus gray-purple fuzz underneath), Fusarium wilt. |

Other herbs:
- **Cilantro**: germinates in ~7–14 days and prefers cool conditions (~15–21 °C). **Bolts quickly** in heat and long days, so sow a new batch every 2–3 weeks. Bolting is the end-of-stage marker.
- **Parsley**: slow germination (~2–4 weeks). Soaking seed helps. Biennial; harvest outer stems.
- **Mint, oregano, thyme, rosemary**: usually started from cuttings or divisions. Use "rooting / establishment" in place of germination and seedling. The woody Mediterranean herbs prefer leaner feeding and drier roots.
- **Chives**: perennial; harvest by cutting to ~5 cm and letting it regrow.

### Leafy greens (lettuce as the default)
| Stage | Lettuce |
|---|---|
| Germination | Fast: **~2–7 days at ~15–21 °C (60–70 °F)**. **Thermodormancy**: many cultivars germinate poorly above ~25–28 °C (77–82 °F). Many lettuces need light to germinate, so **surface-sow or cover very lightly**. |
| Seedling | ~2–3 weeks. Transplant at **3–4 true leaves**. |
| Vegetative / rosette | Rapid leaf expansion. Day **~18–24 °C**, night **~13–18 °C**. VPD ~0.6–1.0 kPa. |
| Heading (heading types only) | Inner leaves fold into a head (butterhead, romaine, crisphead). |
| Harvest | Leaf types: cut-and-come-again from ~30 days. Heads: ~45–70 days from sowing depending on type and light. |
| Bolting (end) | The center elongates, leaves turn bitter, flower stalk forms. Triggered by heat and long days (varies by cultivar). Harvest before or right at the start of bolting. |
| Targets | DLI **~12–17 mol/m²/day**. **~17 works with good vertical airflow; without it, stay nearer ~13–14 to avoid tipburn.** EC ~0.8–1.8 mS/cm. pH ~5.5–6.5 hydro, ~6.0–7.0 soil. |
| Watch for | **Tipburn** (brown edges of young inner leaves; Ca transport, too much light for the airflow), downy mildew, aphids, bolting. |
| Milestones | Germination, first true leaves, transplant, first harvest, bolting/end. |

Spinach, kale, chard, arugula, and Asian greens follow a similar pattern. Spinach and arugula bolt readily in heat and long days. Kale and chard tolerate cold and are harvested leaf by leaf over a long period.


---

## 3. Generic stage models for any plant (by life strategy)

Use these when there's no crop model above. Stage names go in the log exactly as written (lowercase, underscores). Timings are **rules of thumb**; the species, light, and temperature move them a lot.

**Any plant that arrives already growing starts in `establishment`** (the nursery-to-home adjustment, ~1–3 weeks) and then enters whichever stage below matches what you see.

**In a pod with a fixed photoperiod and temperature**, seasonal cues are weak. Judge "active" vs "slow/dormant" by the **observed growth rate** (new leaves per week, photo comparisons), not by the calendar.

### 3.1 `annual-fruiting` (tomato-style: pepper, eggplant, cucumber, beans, peas)
germination → seedling → vegetative → transplant (optional) → flowering → fruit_set → fruit_development → ripening → harvest → decline.
- Use the tomato section as the detailed template. Adjust the germination temperature and days-to-maturity from the seed packet.
- Cucumbers and squash usually have **separate male and female flowers** and need hand pollination indoors unless the cultivar is parthenocarpic (sets fruit without pollination). Check the tag.
- Perennial fruiting plants (strawberry, dwarf citrus, pepper overwintered) cycle flowering → fruiting → **rest**, then repeat.
- Milestones: germination, first_true_leaves, transplant, first_flower, first_fruit_set, first_ripe_fruit, first_harvest, final_harvest.

### 3.2 `leafy-herb-annual` (harvest by cutting: basil, cilantro, lettuce, arugula, most soft herbs)
germination (or `rooting` for cuttings) → seedling → vegetative → harvest_cycles → bolting (or flowering) → decline.
- `harvest_cycles` starts when the plant can lose ~⅓ of its leaves and keep growing (herbs: ~3–4 node pairs; greens: ~4–6 full-size leaves).
- Bolting or flowering is the end marker for greens and most culinary herbs. For basil it's a pinching event, not a success.
- Milestones: germination, first_true_leaves, first_harvest, bolting, final_harvest.

### 3.3 `microgreens` (days-to-harvest, one cut)
soak (only for large seeds such as peas and sunflower) → sown → blackout (~2–4 days, covered or weighted) → greening (uncovered, under light) → harvest_ready → harvested.
- Typical days to harvest from sowing *(rule of thumb)*: radish, broccoli, and other brassicas **~7–12**; pea shoots and sunflower **~8–14**; basil and cilantro **~14–25**. Record the seed supplier's number in the profile if it's available.
- Harvest when the cotyledons are fully open, usually just as the first true leaves appear. Most don't regrow (pea shoots sometimes give a second, smaller cut).
- Watch for: mold (vs harmless root hairs, see the lookalike traps in plant-photo-diagnosis), damping-off, uneven germination. Keep airflow up and water from below.
- Sprouts (grown in jars, no medium) take ~2–7 days and follow food-safety guidance rather than a stage model.
- Milestones: germination, harvest (one per tray). Each tray gets its own `<plant-id>`.

### 3.4 `perennial-foliage` (pothos, philodendron, monstera, ferns, calathea, snake plant)
establishment → active_growth ⇄ slow_growth (or dormancy) → (repeat). There's **no harvest**.
- `active_growth`: new leaves arriving regularly. Water and feed on the normal schedule.
- `slow_growth`: new leaves have slowed or stopped (short days, cooler temperatures, or low light). Water less often and cut feeding back or stop it. This is not a problem.
- Events worth logging: first new leaf in KALE's care, repot, propagation, pups or offsets, maturity features (e.g., first split leaf on a monstera), flowering (rare indoors).
- Milestones: first_new_leaf, first_repot, first_propagation, first_mature_leaf (species-specific), first_flower.

### 3.5 `flowering-ornamental` (African violet, orchid, geranium, jasmine, holiday cactus, kalanchoe)
establishment → vegetative → bud_initiation → bud → bloom → spent (deadhead) → rest → (rebloom cycle).
- Some bloom only after a trigger *(rule of thumb, check the species)*: **short-day plants** such as poinsettia, holiday cacti, and kalanchoe need several weeks of long, uninterrupted nights (~12–14 h dark). Many *Phalaenopsis* orchids spike after a few weeks of cooler nights. In a pod, that may mean deliberately changing the photoperiod or night temperature. Ask the owner first.
- Bud drop: moving the plant, drafts, a dry root zone, low light, or ethylene from ripening fruit nearby.
- Milestones: first_bud, first_bloom, rebloom (count each cycle as an event, not a milestone).

### 3.6 `succulent-cactus`
establishment → active_growth ⇄ dormancy → (bloom).
- Most rosette succulents and cacti grow in spring and summer and rest in winter. Some, such as *Aeonium*, grow in the cool season and rest in summer heat. Record which in the profile.
- `dormancy`: water sparingly (just enough to prevent shriveling) and don't feed. Many cacti set flower buds only after a cool, dry winter rest *(rule of thumb)*.
- Propagation sub-stages for leaves and cuttings: callusing → rooting → pup.
- Milestones: first_new_growth, first_offset, first_bloom, first_propagation.

### 3.7 `bulb` (amaryllis, paperwhite, tulip, daffodil, hyacinth; also tubers and corms)
dormant → rooting (plus a chilling period for spring bulbs) → shoot → bud → bloom → foliage_ripening → dormant.
- Spring bulbs forced indoors need a **cold period** first, roughly **~12–16 weeks at ~2–9 °C** for tulips and daffodils *(rule of thumb, varies by type)*. Amaryllis and paperwhites need no chilling and bloom a few weeks after potting (paperwhites ~4–6 weeks, amaryllis ~6–10 weeks, *rule of thumb*).
- After bloom, **keep the leaves growing until they yellow on their own**. That's how the bulb recharges. Die-back afterward is dormancy, not death.
- Milestones: first_shoot, first_bloom, dormancy_start, rebloom.

---

## 4. Picking a model for a new species

Answer in order and take the first "yes":
1. Is it grown for **fruit or pods**? → `annual-fruiting` (or the tomato/pepper model).
2. Is it **harvested as seedlings within ~3 weeks**? → `microgreens`.
3. Are its **leaves harvested by cutting**, and does it end by bolting or flowering? → `leafy-herb-annual` (or the basil/lettuce model).
4. Does it grow from a **bulb, corm, or tuber** with a seasonal die-back? → `bulb`.
5. Is it **succulent or a cactus**? → `succulent-cactus`.
6. Is the owner's goal **flowers or scent**? → `flowering-ornamental`.
7. Otherwise (long-lived foliage, carnivorous plants, woody perennials) → `perennial-foliage`, with dormancy notes where the species needs them (temperate carnivorous plants need a winter dormancy).

The **owner's goal wins ties**: basil grown for pollinator flowers is tracked as a flowering ornamental; a flowering houseplant kept for its leaves is tracked as perennial foliage.

**Write a species-specific model** (§5 template, saved as `/workspace/plant-library/<species>.yaml`, then set `stage_model: species:<species>` in the profile) when any of these is true:
- Harvest timing is the owner's main goal (days to maturity matter).
- The generic targets conflict with well-documented species needs (carnivorous plants, orchids, cacti that need a winter rest).
- The owner is growing several plants of the species, or will grow it again.
- The plant has deviated from the generic expectations twice with no environmental explanation.
Fill it from seed packets, supplier sheets, or extension guides, and leave unknowns blank.

---

## 5. Template for a species-specific model

Copy this block into the plant library (`/workspace/plant-library/<species>.yaml`; create the folder, these are the bot's own notes) and fill it in from reputable sources (seed packet, university extension guides). Leave unknown values blank rather than guessing. The bot should say "no target on file" instead of inventing one.

```yaml
species: <common name> (<scientific name>)
cultivar: <cultivar or "unknown">
type: <annual | perennial | biennial>; <fruiting | leafy | herb | ornamental | houseplant>
base_model: <annual-fruiting | leafy-herb-annual | microgreens | perennial-foliage | flowering-ornamental | succulent-cactus | bulb>   # the §3 model this refines
photoperiod_response: <day-neutral | short-day | long-day | unknown>
max_photoperiod_h: <e.g. 18>
days_to_maturity: <n> counted from <sowing | transplant>
stages:
  - name: germination            # or "rooting" for cuttings
    typical_days: <min>-<max>
    enter_when: <visual marker>
    targets:
      temp_day_c: <min>-<max>
      temp_night_c: <min>-<max>
      root_temp_c: <min>-<max>
      rh_pct: <min>-<max>
      vpd_kpa: <min>-<max>
      dli_mol: <min>-<max>
      ppfd: <min>-<max>
      photoperiod_h: <n>
      ec_ms_cm: <min>-<max>
      ph: <min>-<max>
      watering: <notes>
    actions: [<pot up>, <pinch>, ...]
    watch_for: [<common problems at this stage>]
  - name: seedling
    ...
  - name: <vegetative | flowering | fruit_set | fruit_development | ripening | harvest | dormancy ...>
    ...
milestones: [germination, first_true_leaves, transplant, first_flower, first_fruit_set, first_ripe_fruit, first_harvest, final_harvest]
sources: [<where these numbers came from>]
```

For houseplants and ornamentals, the generic models in §3 usually cover it. Only list the stages that differ.

---

## 6. Recording stage transitions and milestones

Keep **one append-only log file per plant**, e.g. `/workspace/grow-log/<plant-id>.jsonl` (one JSON object per line). Never rewrite history. If an entry was wrong, append a `correction` event that references it.

### Event types
| `event` | When |
|---|---|
| `plant_created` | A new plant is registered (species, cultivar, sowing or acquired date, `day_basis`, `stage_model`, medium, container) |
| `onboarded` | Onboarding finished; the profile was saved (note whether the owner confirmed it) |
| `profile_updated` | The profile changed (ID corrected, goal changed, targets tightened, owner confirmed) |
| `moved` | The plant changed location or camera view (re-assess the frame region and re-ask only the affected Light & environment questions; see plant-onboarding-interview) |
| `retired` | The plant was removed, replaced, or died. Its `<plant-id>` is never reused |
| `stage_transition` | The plant's (leading) stage changes |
| `milestone` | A notable first: germination, first true leaves, transplant, first flower, first fruit set, first color break, first ripe fruit, first harvest, final harvest |
| `observation` | Notable diagnosis results worth keeping (not every healthy check) |
| `action` | The owner did something: watered, fed (EC/pH), pruned, potted up, treated pests |
| `alert` | KALE 9000 sent the owner an alert |
| `correction` | Fixes an earlier entry |

### Fields
- `ts` — ISO 8601 with UTC offset (e.g. `2026-05-02T08:00:00-07:00`)
- `plant` — plant ID (e.g. `tomato-01`)
- `day` — days since Day 0 (sowing, or acquisition for plants that arrived growing). `dat` — days after transplant (optional)
- `event`, plus `from`/`to` (transitions), `milestone`, `note`
- `photo` — full path of the evidence photo, `/workspace/grow-photos/<plant-id>/YYYY/MM/DD/HHMMSS-<camera>.jpg` (mark milestone photos as keep-forever; see rule 4 below)
- `confidence` — High/Medium/Low for detected transitions
- `source` — `photo-diagnosis`, `owner`, `sensor`, or `onboarding`

### Example log

```jsonl
{"ts":"2026-03-01T09:00:00-08:00","plant":"tomato-01","day":0,"event":"plant_created","species":"tomato","cultivar":"<cultivar>","habit":"indeterminate","medium":"seed-starting mix","container":"cell tray","source":"owner"}
{"ts":"2026-03-07T08:00:00-08:00","plant":"tomato-01","day":6,"event":"milestone","milestone":"germination","photo":"/workspace/grow-photos/tomato-01/2026/03/07/080000-phone-1.jpg","confidence":"High","source":"photo-diagnosis"}
{"ts":"2026-03-07T08:00:00-08:00","plant":"tomato-01","day":6,"event":"stage_transition","from":"germination","to":"seedling","confidence":"High","source":"photo-diagnosis"}
{"ts":"2026-03-16T08:00:00-07:00","plant":"tomato-01","day":15,"event":"milestone","milestone":"first_true_leaves","photo":"/workspace/grow-photos/tomato-01/2026/03/16/080000-phone-1.jpg","confidence":"High","source":"photo-diagnosis"}
{"ts":"2026-04-19T10:30:00-07:00","plant":"tomato-01","day":49,"dat":0,"event":"milestone","milestone":"transplant","note":"moved to final container","source":"owner"}
{"ts":"2026-05-02T08:00:00-07:00","plant":"tomato-01","day":62,"dat":13,"event":"stage_transition","from":"vegetative","to":"flowering","confidence":"Medium","note":"first truss buds, awaiting open flower","source":"photo-diagnosis"}
{"ts":"2026-05-05T08:00:00-07:00","plant":"tomato-01","day":65,"dat":16,"event":"milestone","milestone":"first_flower","photo":"/workspace/grow-photos/tomato-01/2026/05/05/080000-phone-1.jpg","confidence":"High","source":"photo-diagnosis"}
```

A plant that arrived already growing (e.g., a store-bought pothos) starts like this:

```jsonl
{"ts":"2026-06-01T09:00:00-07:00","plant":"pothos-01","day":0,"day_basis":"acquired","event":"plant_created","species":"Epipremnum aureum","stage_model":"perennial-foliage","origin":"nursery","age_est":"~6-12 months","source":"onboarding"}
{"ts":"2026-06-01T09:00:00-07:00","plant":"pothos-01","day":0,"event":"stage_transition","from":null,"to":"establishment","confidence":"High","source":"onboarding"}
{"ts":"2026-06-01T09:20:00-07:00","plant":"pothos-01","day":0,"event":"onboarded","note":"profile saved, confirmed_by_owner: no (provisional)","source":"onboarding"}
```

### Human-readable summary (generated from the log on request)

```
tomato-01 (<cultivar>, indeterminate) — Day 65 / DAT 16 — Stage: flowering
Milestones: germination D6 · first true leaves D15 · transplant D49 · first flower D65
Next expected: first fruit set in ~3–7 days if pollination is working; first ripe fruit ~6–9 weeks after set.
```

### Rules for transitions
1. **Detect from photos, confirm with evidence.** Log a transition at High confidence only when the visual marker is clearly visible. At Medium, log it with `confidence:"Medium"` and re-check at the next review.
2. **Milestones are "firsts" and are logged once per plant.** Later flowers don't count again.
3. **The owner's word wins.** If the owner reports a transition or milestone, log it with `source:"owner"`.
4. **Flag milestone photos** as keep-forever in the photo index so rotation never deletes them: `python3 /workspace/kalecam/rotate.py flag --plant <plant-id> --file <YYYY/MM/DD/HHMMSS-<camera>.jpg> --milestone <name>` (path relative to the plant folder, as listed by `/workspace/kalecam/kalecam photos --plant <plant-id>`). If the milestone is visible but the best frame is old, take a fresh one with `kalecam capture --plant <plant-id> --wait 90` and flag that.
5. **Announce milestones** to the owner (one short, friendly message). They're good news and don't require action.
6. **Behind schedule?** If a plant exceeds the upper end of a stage's typical duration by more than ~50%, add an `observation` and check environment causes (temperature, light, root zone) before alerting.
7. **Light and heat at stage changes.** At a transition to flowering (for plants grown for flowers or fruit), check the profile's `light_environment`: if the light has a bloom or red mode that isn't on, suggest switching in the same message as the milestone, and note the added heat framed by `heat_welcome` (grow-environment-targets §12, "Stage coupling"). Suggest it once; log the owner's answer as an `action` or `observation`.
