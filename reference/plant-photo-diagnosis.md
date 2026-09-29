> **Full reference for the plant-photo-diagnosis skill, installed by kalecam-setup.**
> Location after install: `/workspace/kalecam/reference/plant-photo-diagnosis.md`. The Grok Bot template ships a slim
> version of this skill; this file holds the complete tables, formulas and details it points to.

# Plant Photo Diagnosis

KALE 9000's standard way to identify and diagnose a plant from a photo. It works for **any plant in the pod**, not only the crops with detailed models (tomato, pepper, basil, lettuce). Go through the steps in order. Most photos show a healthy plant. The usual result is one quiet log line. The owner only hears from you when something needs doing.

The **Identification reference** near the end of this skill has the trait checklist, lookalike traps, cultivar limits, purpose classes, and the toxicity table used in Step 1b.

> Guiding principle: *"I'm sorry, <owner>. I can't let you overwater that."* In practice that means being useful, being dry, being specific, and saying when you're unsure.

---

## Step 0 — Context before the image

Before you look at the image, load:
- **Plant profile** from `/workspace/grow-profiles/<plant-id>.md` (format in **plant-onboarding-interview**): species/cultivar, ID confidence, purpose, owner goal, stage model, needs, targets, watch_list, medium, container, and **`light_environment`** (setting, light and current mode, schedule, `heat_welcome`). The current light mode predicts the photo's color cast; `heat_welcome` decides how warm readings are judged (grow-environment-targets §12). If `confirmed_by_owner: no`, the profile is **provisional**: use it, but hold its numbers loosely.
- **No profile, or a plant in frame that matches no profile** → run Step 1b, then hand off to **plant-onboarding-interview**. Anything urgent (pests, collapse, rot) gets flagged right away; it doesn't wait for onboarding.
- **Current growth stage** and days since sowing/transplant (from the growth-stage log).
- **Recent sensor snapshot** if there is one: air temp, RH, VPD, CO2, soil moisture trend, light (PPFD/DLI or lux), reservoir level. There is usually **no sensor feed** (the photo index `sensors` field is empty unless something fills it). If a thermometer/hygrometer display is visible in the photo, **read it from the image** (say so, and note it as a photo reading); otherwise use the owner's latest reported readings from the grow log, or ask for them only if the call depends on them.
- **Recent actions**: last watering, feeding (EC/pH), pruning, transplant, pest treatment, light height or intensity changes.
- **Previous diagnosis** and any open issues you are tracking.

Many symptoms look alike. Context is usually what tells them apart.

---

## Step 1 — Get a current photo, then check its quality (always first)

**Getting the photo.** If the kalecam phone camera is installed (`/workspace/kalecam/kalecam` exists), don't ask the owner for a new photo. Take one yourself:
- `/workspace/kalecam/kalecam capture --wait 90` (or `capture <camera> --plant <plant-id> --wait 90`) prints `{"status":"done","file":"/workspace/grow-photos/<plant-id>/YYYY/MM/DD/HHMMSS-<camera>.jpg",...}`. Open that file.
- Recent photos: `/workspace/kalecam/kalecam photos --plant <plant-id> -n 5` (newest first, full paths). Photo files are named `HHMMSS-<camera>.jpg`; don't guess names, list them.
- If the capture times out, run `kalecam status`: a stale heartbeat, `visible: false` or low battery means the phone page is closed, the screen is off, or it's unplugged. Tell the owner that in one line (with the fix) and fall back to the latest photo.
- Ask the owner only for what a fixed camera can't give: leaf undersides, close-ups of a symptom, a stem base, a different angle, or a white-light shot when the grow light can't be switched.

Grade the photo **Good / Usable / Unusable** before you diagnose anything.

| Check | What to look for | If it fails |
|---|---|---|
| **Color cast** | Purple/magenta light from red+blue ("blurple") LEDs, orange from HPS, strong yellow from warm-white LEDs. Under these, color judgments (chlorosis, purpling, bleaching, early spots) are **unreliable**. | Do not make color-dependent calls. Ask for a white-light photo: grow light off or dimmed, and a phone flashlight, a neutral room light, or daylight on. A white card or paper in frame helps. |
| **Blur / focus** | Can you see leaf veins and edges? Motion blur from fans? | Mark lesions and pests as "cannot assess". Ask for a still, focused close-up. |
| **Exposure** | Blown-out highlights near the lamp, or a canopy too dark to see. | Only use the parts that are properly exposed. |
| **Framing** | Is the whole plant visible (for vigor and symptom location)? Is there a close-up of the symptom? Top of the leaf *and* underside? | Ask for the missing view: whole plant, affected leaf top, affected leaf underside, stem base or soil surface. |
| **Scale** | Is there anything for size (pot rim, label, hand, ruler)? | Keep size estimates vague. |
| **Consistency** | Same camera position as earlier photos? | If framing changed, don't read apparent size changes as growth or shrinkage. |

Rules:
- **Unusable** → do not diagnose. Log "photo unusable (reason)". If there is an open issue or the plant is at a critical stage, take a new one with `kalecam capture` (or ask the owner if there's no camera, or the camera itself is the problem: moved, fogged, blocked). Otherwise wait for the next scheduled capture.
- If color matters for the call (possible deficiency, bleaching, disease spots) and the photo was taken under colored grow light, **ask for a white-light photo before you alert with high confidence**. If the issue could be urgent (pests, spreading disease), you can alert with Low/Medium confidence and ask for the photo in the same message.
- Scheduled camera frames are often taken under grow lights. Where the setup allows, schedule one daily frame just before lights-on or with a white-light source. The daily review uses that frame for color checks.

---

## Step 1b — Identify (new plants, or when the ID is doubtful)

Run this for a new or unknown plant, when the profile's `id_confidence` is Low, or when what you see contradicts the profile. An ID is a **best guess with a confidence level**, never a certainty; the reference at the end is a photo field guide, not a botanical key.

1. **List the traits you can actually see** (Identification reference, trait checklist): arrangement, leaf type and margin, venation, texture, stem, habit, flowers or fruit, plus any tag and any smell the owner reports. Write them down so the reasoning can be checked.
2. **Name it** (common name + species) with **confidence High / Medium / Low**:
   - **High**: several diagnostic traits agree, no open lookalike, Good photo, or a tag (or the owner) confirms it (`id_basis: tag | owner`). "This is sweet basil. Confidence: high."
   - **Medium**: family or genus clear, species likely; a lookalike not ruled out, foliage only, or a color cast. "Very likely flat-leaf parsley. Cilantro isn't ruled out; a leaf sniff would settle it." An owner's "I think it's X" is Medium evidence.
   - **Low**: cotyledons only, partial or blurry view, strong grow-light cast, or several candidates. "It's green, it's alive, and it's keeping its secrets."
3. **Check the lookalike traps** (reference table). An unresolved trap caps confidence at Medium; a grow-light cast caps any color-dependent call (purple foliage, variegation, flower color) at Medium.
4. **Cultivar is a separate call** with its own confidence. Foliage almost never confirms one: say "a sweet basil, cultivar unknown (tag?)". Hot vs sweet pepper can't be judged from the plant at all.
5. **Classify the purpose** (reference table). The owner's stated goal overrides the default.
6. **Toxicity heads-up** for pets and kids where it's well known (reference table). It's a heads-up, not a diagnosis.
7. **If confidence is Low, ask for one thing** (two at most), in this order of usefulness: the plant tag or label photo; a leaf close-up filling the frame, top and underside; the stem where a leaf attaches; a flower or fruit; a white-light photo; a smell report ("crush a leaf corner; what does it smell like?", but not for irritant-sap plants such as Euphorbia, and not for unknown seedlings someone might taste).

Log line: `ID: <common name> (<species>), cultivar <name|unknown>; confidence <H/M/L> (<traits>); lookalikes: <none|list>; purpose: <class>; toxicity: <note|none known|unknown>`.
While the ID is Low or no species model exists, care for it with the **first-principles fallback** below.
**Never declare a plant safe to eat from a photo ID alone**; for edible use the owner relies on the seller's label or a confirmed source. A new plant is not an alert. It starts onboarding.

---

## Step 2 — Overall vigor (whole-plant view)

- **Posture**: leaves held out or slightly up (good), drooping, curling up at the edges ("taco"), clawing down.
- **Color overall**: even medium green vs pale, yellow, very dark green, patchy. Check against the cultivar's normal color. Some cultivars have purple stems or leaves naturally.
- **Structure**: stretched internodes (too little light, or too warm at night relative to day), compact and stocky (good), leaning toward the light.
- **Size vs. expected** for its stage and age (see growth-stage-tracker).
- **Canopy density**: overcrowded foliage means poor airflow and higher disease risk.
- **Medium surface**: wet or shiny, dry and cracked, algae, white crust (salt buildup), mold, fungus gnats.

---

## Step 2b — First-principles state checks (any plant)

These don't depend on a crop model. Check each one briefly.

**Just purchased or transplanted (nursery-to-home adjustment, transplant shock).** Store and nursery plants move from bright, humid greenhouses into dimmer, drier homes.
- **Normal in the first ~1–3 weeks** *(rule of thumb)*: a few older leaves yellowing or dropping, mild droop, a pause in new growth, buds dropping on flowering plants. Don't alert for these; log them as `adjusting`.
- **Not normal**: wilting that doesn't recover once the medium is moist, a mushy stem base, spreading spots, pests, or new growth dying.
- **What not to do**: repot and feed at the same time (fresh mix plus fertilizer on stressed roots adds salt stress); feed in the first ~2–4 weeks (nursery mixes usually carry fertilizer, *rule of thumb*); move the plant around repeatedly; drown it out of sympathy.
- **What to do**: pick a spot with suitable light and leave it there, water by checking the medium, and inspect for pests (ideally keep it away from other plants for ~2 weeks). Repot early only if it's badly root-bound, sitting in a waterlogged mix, or rotting.

**Root-bound.** Signs: roots coming out of the drainage holes or circling the surface; water running straight through; the medium drying much faster than it used to (the plant needs water every day or two); growth stalling despite good light and feeding; a top-heavy plant or a bulging pot. Fix: pot up one size (*rule of thumb*: ~2–5 cm / 1–2 in wider), tease out circling roots, preferably during active growth, and hold off on feeding for a couple of weeks. Some plants flower better slightly snug; check the profile before recommending a big jump.

**Light: stretched vs burned.**

| Etiolation (too little light) | Light burn / sunburn (too much, or too sudden) |
|---|---|
| Long gaps between leaves, thin stems, small pale new leaves, leaning toward the light, lower leaves dropping | Bleached, yellow-white, or washed-out patches on the **most exposed** leaves, crispy tan or brown scars, edges cupping up |
| Succulents: rosettes open up and elongate, turn pale green, lean. **Stretch doesn't reverse**: fix the light, and later behead and re-root if needed | Succulents: tan or brown scars (permanent). Red, orange, or purple "stress color" alone is usually harmless and often wanted |
| Variegated plants lose variegation | Often follows a sudden move into brighter light. Acclimate over ~1–2 weeks *(rule of thumb)* |

**Nutrient-hungry (generic).** Overall pale color with older leaves yellowing evenly, small new leaves, slow growth, in a plant that has sat in the same mix for months unfed (peat-based starter charges run out in weeks, *rule of thumb*). Before recommending food, rule out low light, cold, and wet roots. Feed light and lean for succulents, and **never fertilize carnivorous-plant soil**.

**Water, temperature, pests, disease, stage**: Steps 4–9 below. They include notes for houseplants and succulents.

## Step 2c — Cross-check photos with sensors (when available)

Readings come from a sensor feed, a display visible in the photo, or the owner (Step 0). Never invent them.

| Photo shows | Sensor pattern | Most likely |
|---|---|---|
| Droop | Soil moisture high for days, little dry-down | Overwatering, root trouble, or a pot too large for the plant |
| Droop | Soil moisture low, sharp dry-down | Thirsty |
| Midday droop, evening recovery | Moisture fine, temperature or VPD high | Heat or VPD stress; not a watering problem |
| Stretching | Low PPFD/lux or DLI, or light hours short | Etiolation |
| Bleaching at the top | High PPFD/DLI, lamp recently moved or raised in intensity | Light burn |
| Spots, fuzz, or mildew | RH high overnight, lights-off RH spikes | Fungal disease risk |
| Stippling | RH low, temperature high | Spider mites |
| Stalled growth | Dry-down getting much faster week over week | Root-bound |
| Purpling, slow growth | Low air or root temperature at night | Cold, not phosphorus |

When the photo and the sensor disagree, **suspect the sensor first** (placement, calibration, a probe in a dry pocket) and say so.

---

## Step 3 — Leaves: WHERE the symptom is comes first

Symptom location is the most important clue for nutrient problems.

- **Older / lower leaves first** → a **mobile** nutrient the plant is moving to new growth: **N, P, K, Mg** (and rarely Mo). Also normal senescence: one or two bottom leaves yellowing slowly on a large, healthy plant is normal.
- **Newer / upper leaves and growing tips first** → an **immobile** nutrient: **Ca, Fe, S, Mn, Zn, B, Cu**. Or light, heat, or pest damage at the top.
- **Random / patchy / spots** → more likely disease, pests, spray burn, or physical damage than a nutrient problem.
- **One side of the plant or a single branch** → wilt diseases, stem damage, or uneven light or heat.

Then describe the pattern: uniform yellowing, interveinal chlorosis (veins green, tissue between them yellow), marginal scorch, spots (shape, size, halo, rings), stippling, curling, distortion, bleaching, necrosis.

### Nutrient deficiencies and toxicities: distinguishing signs

| Issue | Where | Distinguishing signs | Commonly confused with |
|---|---|---|---|
| **Nitrogen (N) deficiency** | Old leaves first, moving up | Uniform pale green to yellow across the whole leaf, veins included. Slow growth, thin stems. Older leaves may drop. | Normal senescence (only 1–2 leaves), overwatering, cold roots |
| **Phosphorus (P) deficiency** | Old leaves | Dark, dull or bluish-green leaves, purple or reddish undersides and veins, stunted growth | **Cold** (purpling is common below ~13–15 °C / 55–59 °F root or air temps), cultivar pigmentation |
| **Potassium (K) deficiency** | Old / middle leaves | Yellowing then brown scorch on **leaf margins and tips**, sometimes small spots near edges. In tomatoes: blotchy or uneven ripening, weak fruit. | Salt/EC burn (tips), wind or heat scorch |
| **Magnesium (Mg) deficiency** | Old leaves | **Interveinal chlorosis** on lower leaves with green veins, sometimes a "Christmas tree" pattern. Common in tomatoes and peppers fed high K. | Fe (but Fe is on **new** leaves), Mn |
| **Calcium (Ca) deficiency** | New growth, fruit | Distorted, cupped, or hooked new leaves, dying growing tips. **Blossom end rot** on tomato and pepper fruit. **Tipburn** on lettuce inner leaves. Usually caused by poor Ca **transport** (irregular watering, very high or very low humidity, root damage, high EC) rather than too little Ca in the medium. | Boron, light burn at the tips |
| **Iron (Fe) deficiency** | Youngest leaves | Sharp interveinal chlorosis on new leaves; veins stay distinctly green. Severe cases go nearly white. Usually **high pH** (above ~7 in soil, above ~6.5 in hydro), overwatering, or cold roots, not missing Fe. | Mn (similar but with spots), Mg (old leaves) |
| **Sulfur (S) deficiency** | Newer leaves | Uniform pale yellow-green on **young** leaves (looks like N but from the top down) | N deficiency (old leaves) |
| **Manganese (Mn) deficiency** | Young / middle leaves | Interveinal chlorosis with a wider green band along the veins than Fe, and small tan necrotic specks | Fe, Mg |
| **Zinc (Zn) deficiency** | New growth | Small, narrow leaves, short internodes (rosetting), interveinal chlorosis | Viral distortion, herbicide drift |
| **Boron (B) deficiency** | Growing tips | Dead or blackened growing point, brittle thick distorted new leaves, hollow or cracked stems. Tomato fruit may be corky or cracked. | Ca deficiency |
| **Nitrogen excess** | Whole plant | Very dark green, lush, soft growth. Leaf tips clawed or bent down. Lots of foliage, few flowers or fruit. More aphids. | — |
| **Salt / high EC ("nutrient burn")** | Tips then margins, often older leaves | Crispy brown leaf tips, then marginal necrosis. Wilting even though the medium is wet. White crust on the medium or pot. High runoff EC. | K deficiency, underwatering |
| **pH lockout** | Mixed | Several deficiency patterns at once despite adequate feeding | — |

Before blaming a nutrient, check **pH, root health, watering, and temperature** first. Most apparent deficiencies in home grows are caused by uptake problems, not by a shortage in the medium.

---

## Step 4 — Water stress: over vs under

Both make leaves droop, so tell them apart with context:

| Sign | Overwatering / poor drainage | Underwatering |
|---|---|---|
| Leaf feel/look | Droopy but **firm, thick, curled downward**. Lower leaves yellowing. | **Limp, thin, papery**, edges crisping. Whole plant wilts. |
| Medium | Wet, heavy pot, soil sensor high for days, algae, gnats | Dry, pulling away from pot edge, light pot, soil sensor low |
| Timing | Droops even after the lights have been on for hours. Doesn't recover. | Often worst late in the light period. **Recovers within hours of watering.** |
| Roots (if visible) | Brown, mushy, smelly roots mean root rot | Dry, but white and firm |
| Sensor clue | Soil moisture barely drops for 3+ days | Sharp dry-down, then a flat low reading |

Also consider **heat wilt**: midday droop at high temperature or high VPD that recovers in the evening even though the medium is moist. The fix is environmental (temperature, VPD, shade), not more water.

Other plant types:
- **Succulents / cacti**: thirsty = wrinkled, deflated, or soft-but-firm leaves that plump up within a day or two of watering. Overwatered = translucent, yellowing, **mushy** leaves that fall off at a touch, or a black soft stem base (rot; act now).
- **Thin-leaved houseplants** (peace lily, ferns, calathea): thirsty = sudden dramatic droop or crisp edges; recovers fast after a drink. Overwatered = yellowing lower leaves and droop with a wet, heavy pot.
- **Carnivorous plants**: most bog species want the medium constantly moist with pure water. Dry media and mineral-heavy tap water are the usual killers.

---

## Step 5 — Light stress

- **Too much / too little light**: see the stretched-vs-burned table in Step 2b. Burn shows on the **top leaves closest to the lamp** while lower leaves are fine; check lamp distance, dimming, and PPFD/DLI (or the profile's `estimated_dli_mol_m2_day`). Too little also means poor flowering or fruit set.
- **After a light-mode or fixture change** (per `light_environment`): judge color only from a white-light photo, and expect a few days of adjustment before calling burn or stretch.
- **Continuous light injury (tomatoes)**: mottled chlorosis on leaves when the photoperiod is longer than about 18 h. Give a dark period.

## Step 6 — Temperature stress

- **Heat**: leaves curl up or cup, midday wilting, bleached tops near the lamp. In tomatoes, **flower drop / poor fruit set** follows sustained days above ~29–32 °C (85–90 °F) or nights above ~21–22 °C (70–72 °F). Fruit may ripen orange or yellow instead of red above ~29–30 °C (~85 °F).
- **Cold**: purpling of leaves and stems (tomatoes, peppers), slow growth, leaves curling down. Chilling injury below ~10 °C (50 °F) in warm-season crops (tomato, pepper, basil). Basil blackens.
- **Catfacing** (scarred, misshapen tomato fruit) is linked to cool temperatures during flower development.

---

## Step 7 — Pests (look closely at undersides and new growth)

| Pest | Signs | Notes / first response |
|---|---|---|
| **Spider mites** | Fine pale **stippling or speckling** on the leaf surface, fine webbing on undersides or between leaves, tiny moving dots | Favored by hot, dry air. Act fast; populations explode. Raise humidity if VPD is high, rinse undersides, isolate the plant, use miticide or oil appropriate to the crop. |
| **Aphids** | Clusters of soft-bodied insects (green, black, pink) on new shoots and undersides, **sticky honeydew**, sooty mold, curled new leaves, ants | Common on lush, high-N growth. Water spray, insecticidal soap. |
| **Whiteflies** | Tiny white moths that fly up when the plant is disturbed, eggs and nymphs on undersides, honeydew | Yellow sticky cards for monitoring. Soap or oil sprays on undersides. |
| **Thrips** | **Silvery streaks or scarring**, tiny black fecal specks, distorted new growth, slender fast insects | Can transmit tomato spotted wilt virus. Blue or yellow sticky cards. |
| **Fungus gnats** | Small dark flies around the medium surface, larvae in wet topsoil | A sign of overwatering. Let the top dry out, use yellow sticky cards, BTi drench. Larvae can harm seedling roots. |
| **Tomato/tobacco hornworm** (tomatoes, peppers) | Large green caterpillars that are hard to see, **stripped leaves and bare stems**, **large dark frass pellets** on leaves below | Hand-pick. Leave any covered in white cocoons (parasitic wasps). Mostly outdoors. |
| **Other caterpillars** | Chewed holes, frass | Hand-pick, Bt. |
| **Leaf miners** | Winding pale trails inside leaves | Remove affected leaves. |
| **Tomato russet mites** | **Bronzing / greasy look on lower stems and leaves** spreading upward, leaves drying. Mites are invisible without a lens. | Often missed. Ask for a macro photo. |
| **Broad mites** | Twisted, glossy, stunted new growth. Invisible without magnification. | Can look like herbicide or heat damage. |
| **Slugs/snails** (outdoor) | Ragged holes, slime trails | — |
| **Mealybugs / scale** (houseplants) | Cottony masses or brown bumps on stems, honeydew | — |

For houseplants and succulents, the usual suspects are mealybugs, scale, spider mites, thrips, and fungus gnats. Crop-specific pests (hornworms, russet mites) rarely apply. New arrivals are the most common way pests get into the pod.

When you suspect pests, **ask for a close-up of the leaf underside** (a phone macro mode or a cheap clip-on lens helps).

---

## Step 8 — Diseases and disorders

| Condition | Key signs | Distinguish from |
|---|---|---|
| **Early blight** (Alternaria, tomato) | Brown spots with **concentric rings ("target")** and a yellow halo, starting on **older, lower leaves**. Stem lesions possible. | Septoria (small spots, no rings) |
| **Septoria leaf spot** (tomato) | **Many small (≈2–5 mm) round spots** with dark borders and gray/tan centers, sometimes tiny black dots in the center. Lower leaves first, spreading upward. | Early blight (bigger, ringed) |
| **Late blight** (tomato, potato) | Large, **greasy gray-green to brown water-soaked lesions**, white fuzzy growth on undersides in humid conditions, firm brown fruit lesions. Spreads **very fast**. | Treat as urgent. Remove and bag affected plants. Can spread to other gardens. |
| **Leaf mold** (tomato, humid indoor/greenhouse) | Pale yellow patches on upper leaf surface, **olive-green to gray velvety mold on the underside** | Common at high humidity with poor airflow. Lower RH, increase airflow. |
| **Powdery mildew** | White powdery patches that wipe off. On tomato it can show as yellow patches on top with faint white on the underside. | Mineral residue or spray deposits (don't smear) |
| **Downy mildew** (basil, lettuce) | Yellowing between veins on top, **gray-purple fuzzy growth underneath** | Nutrient chlorosis (no fuzz) |
| **Gray mold / Botrytis** | Fuzzy gray mold on dead or damaged tissue, flowers, stem wounds | High humidity, dense canopy |
| **Bacterial spot / speck** | Small dark, greasy spots, sometimes with yellow halos. Raised scabby spots on fruit. | Septoria (has tan centers) |
| **Fusarium / Verticillium wilt** | Yellowing and wilting on **one side** or of lower leaves, V-shaped yellow wedges (Verticillium), brown vascular tissue inside the stem | Water stress (affects whole plant evenly) |
| **Damping-off** (seedlings) | Seedlings collapse at the soil line with a pinched, dark stem | Too wet, cool, poor airflow |
| **Root rot** (Pythium etc.) | Wilting despite wet medium, brown slimy roots, bad smell | Overwatering |
| **Viruses** (ToMV/TMV, TSWV, etc.) | Mosaic mottling, distorted or fern-like leaves, bronzing or ring spots (TSWV) | Nutrient issues, herbicide drift, broad mites. Confirm with a test if in doubt. |
| **Blossom end rot** (tomato, pepper) | Leathery tan to black patch at the **blossom end** of fruit | A **calcium transport problem**: irregular watering, very high or low humidity, high EC, root damage. Fix watering consistency first. |
| **Fruit cracking** | Radial or concentric cracks near the stem end | Irregular watering (dry then flooded), heat |
| **Sunscald** | Pale, papery patch on fruit exposed to intense light after leaf removal | — |
| **Edema (oedema)** | Small corky blisters on leaf undersides | High humidity combined with wet roots and low transpiration. Common indoors. |
| **Physiological leaf roll** (tomato) | Lower/older leaves roll upward lengthwise, remain green and firm | Harmless. Often follows heavy pruning or heat. Don't alert. |
| **Tipburn** (lettuce) | Brown edges on young inner leaves | Ca transport. Light is too high for the airflow available. |
| **Bolting** (lettuce, cilantro, basil flowering) | Sudden upward stem elongation, flower buds | Heat and long days |
| **Stem / crown rot** (succulents, overwatered houseplants) | Black or brown mushy stem base, translucent leaves, collapse | Thirst (firm, wrinkled). Urgent: cut above the rot and re-root, or discard. |
| **Houseplant leaf spot** (fungal or bacterial) | Brown or black spots, often with a yellow halo; water-soaked edges suggest bacteria | Sunburn scars (dry, on the exposed side only), edema |

For plants not in this table, read the pattern: rings or halos → fungal or bacterial spot; fuzz or powder → mold or mildew; water-soaked, spreading lesions → bacterial or rot; mottling or distortion → virus, mites, or chemical damage. Give it Medium confidence at most unless the pattern is classic.

---

## Step 9 — Growth stage identification

Use the plant's `stage_model` from its profile and the visual markers in **growth-stage-tracker**: the crop models (e.g., cotyledons only → true leaves → vegetative → flower buds/open flowers → fruit set → fruit sizing → color break → ripe) or the generic life-strategy models (leafy/herb, microgreens, perennial foliage, flowering ornamental, succulent/cactus, bulb). If the stage has changed since the last log entry, **record a stage transition** and check whether it is a milestone (first true leaves, first flower, first fruit set, first ripe fruit, etc.).

---

## Step 10 — Compare with previous photos (trend)

Pull the same-plant photos from roughly 1, 3, and 7 days ago (same camera and framing if possible) and ask:
- Is the symptom **new, stable, spreading, or improving**?
- Did it spread from old to new leaves, from bottom to top, or to neighboring plants?
- Has growth rate (height, leaf count, canopy width) changed?
- Did a recent action (feeding, repotting, light change) come before the change?

A stable, minor issue on old leaves usually doesn't need an alert. A symptom that is **spreading or reaching new growth** does.

Account for camera artifacts: different time of day, lights on vs off, auto white balance shifts, and plants moving with the fan (tomato leaves also shift position through the day).

---

## Step 11 — Confidence levels

Give every finding a confidence level:
- **High**: a classic pattern, a Good photo (white light when color matters), and consistent with sensor data or history.
- **Medium**: a likely pattern with one missing piece (color cast, no underside view, no sensor data).
- **Low**: several plausible causes, or photo quality limits the call.

For Medium or Low, list the **top 2–3 differentials** and the **single most useful next check** (a white-light photo, a leaf underside close-up, a runoff pH/EC reading, a soil moisture reading, a check for webbing with a lens). Never present a guess as certain.

---

## Step 12 — Decide: alert or log silently

**Rule: alert the owner only when action is needed. Otherwise log silently.**

Send an alert when:
1. Action is needed within ~48 h (watering, environment fix, pest or disease response, support or staking, harvest-ready fruit).
2. Something urgent is suspected even at Medium/Low confidence (spider mites, late blight, a spreading disease, severe wilting, a pest outbreak). Say how confident you are and ask for the confirming photo.
3. A milestone was reached (first true leaves, first flower, first fruit set, first ripe fruit, harvest). These are pleasant alerts, not problems.
4. A photo is needed to resolve an open issue.

**Thresholds follow the profile's `light_environment`** (grow-environment-targets §12): with heat welcome, warm readings under the species' stress line are logged as fine; with heat a problem, suggest airflow earlier; outdoor setups add frost and heat-wave warnings from the forecast.

Also check the profile's **`watch_list`**: a watch-list sign seen for the first time is an alert even when it's mild, because the owner and KALE agreed to catch it early.

Do **not** alert for: a healthy plant, normal lower-leaf senescence, physiological leaf roll, normal new-arrival adjustment in the first ~1–3 weeks, a minor stable issue already reported, photo quality problems with no open issue, or anything the owner can't act on.

A **new or unidentified plant** isn't an alert. It gets one friendly onboarding message (see **plant-onboarding-interview**). If the profile is provisional, say so when you quote its targets ("provisional target, not yet confirmed").

De-duplicate: don't repeat the same alert within 24 h unless it has gotten worse. Refer back to the earlier alert ("Follow-up to yesterday's note about…").

---

## Output format

### Log entry (always written)

```
[<YYYY-MM-DD HH:MM>] <plant-id> | Day <n> | Stage: <stage> | Status: OK | WATCH | ACTION
Photo: <path> (quality: Good/Usable/Unusable; light: white/grow-light)
Profile: confirmed | provisional | none (onboarding triggered)
Findings: <finding> (<confidence>); <finding> (<confidence>)
Trend vs <date>: <new/stable/spreading/improving>
Sensors: T <°C> RH <%> VPD <kPa> soil <%> (if available)
Actions suggested: <none | list>
Alert sent: yes/no (<reason>)
```

### Alert to owner (only when needed)

Keep it short, specific, and actionable. Lead with the action.

```
<plant-id> — <one-line problem>. Confidence: <High/Medium/Low>.
Do: <1–3 concrete steps>.
Why: <one sentence of evidence>.
Next check: <what I'll look at next / what photo I need>.
```

Examples:

> **tomato-01**: Lower leaves show target-ring spots, very likely early blight (confidence: Medium, the grow light makes color hard to judge).
> Do: remove the 3 affected lower leaves, bag them, don't compost; water at the base only; increase airflow.
> Why: brown concentric-ring spots with yellow halos, lowest leaves only, RH averaged 82% overnight.
> Next check: a white-light photo of the underside of the next leaf up, please. I'd like to rule out septoria.

> **pepper-02**: I'm sorry, <owner>. I can't let you water that again today. The medium has been at 85% moisture for four days and the lower leaves are drooping while firm. Hold watering until the sensor drops below ~45%. (Confidence: High.)

> **basil-01**: First flower buds spotted. Pinch the top pair of nodes to keep the leaves coming. This is a milestone, not a malfunction.

Healthy-plant status (logged, **not** sent):
```
[2026-06-14 08:00] tomato-01 | Day 52 | Stage: flowering | Status: OK | Findings: vigorous, 3 open trusses, no symptoms (High). Alert sent: no.
```

---

## Unknown or unmodeled plants: first-principles fallback

When there's no species model (or the ID is Low), infer needs from what the plant is built for. Every inferred number is a **provisional, rule-of-thumb** starting point. Record it in the profile with `target_source: first-principles`, watch the plant's response for ~2 weeks, then tighten.

| Clue | Likely origin | Starting care |
|---|---|---|
| Thick, waxy, or succulent leaves or stems; gray/silver coating; spines; small leaves | Arid or seasonally dry | Bright light, deep but infrequent watering once the mix is dry, gritty fast-draining mix, lean feeding, dry air is fine |
| Large, thin, soft, dark-green leaves | Shaded forest floor | Medium or indirect light, evenly moist (not wet), humidity ~50–70%, protection from direct hot light |
| Aerial roots, climbing or trailing habit | Tropical climbers (aroids) | Chunky airy mix, let the top dry slightly, humidity, something to climb |
| Silvery thick roots, pseudobulbs, found on bark | Epiphytic orchids | Bark mix, water when the roots turn silvery, humidity, never sitting in water |
| Small gray-green aromatic leaves on woody stems | Mediterranean herbs | Full light, lean mix, dry between waterings, good airflow |
| Soft, fast, lush annual growth | Annual crop or weed | Strong light, steady moisture, moderate feeding |
| Variegation | Same as the green form | Somewhat more light than the green form; slower growth |
| Bulb, tuber, or rhizome | Seasonal climates | Expect a dormancy; don't mistake die-back for death |
| Traps, pitchers, or sticky leaves | Nutrient-poor bogs | Pure water, no soil fertilizer, bright light; temperate species need winter dormancy |

Family also helps once known (mint family: aromatic, easy from cuttings; nightshades: warm, hungry, sun-loving; aroids: humidity and airy mix; cacti and crassulas: light and restraint).

Provisional light bands for unknown plants *(rule of thumb)*: **low-light foliage ~2–6 mol/m²/day** (~50–150 µmol/m²/s over 12 h), **medium ~6–12**, **high-light plants (succulents, herbs, fruiting crops) ~12–30**. Temperature: most tropical houseplants are happiest around ~18–27 °C and dislike nights below ~12–15 °C. Once the plant is identified with confidence, replace these with species values and record the source.

---

## Identification reference (used by Step 1b)

### Trait checklist (work top to bottom; traits first, name second)

| Trait | What it often tells you |
|---|---|
| **Tag / pot label** | The strongest evidence, and the only reliable one for cultivar ("hot"/"sweet", variety). Ask early. |
| **Leaf arrangement** | Opposite leaves + **square stem** + aroma → mint family (basil, mint, oregano, sage, thyme, rosemary, lavender, coleus). |
| **Leaf type / margin** | Tomato: compound, lobed. Pepper: simple, smooth-edged. Cilantro and parsley: divided. Basil: smooth or slightly toothed; mint: clearly serrated. |
| **Venation** | Parallel veins → monocot: grasses, alliums (chives, green onion), spider plant, dracaena, snake plant, orchids, lilies. |
| **Texture** | Thick, waxy, or succulent → drought-adapted. Fuzzy → often dry or high-light habitats. Powdery bloom (farina) on succulents rubs off; don't wipe it. |
| **Stem** | Aerial roots → aroids (pothos, philodendron, monstera). Tendrils → peas, cucurbits. **Areoles** (fuzzy cushions bearing spines) → true cacti. |
| **Sap** (owner-reported) | Milky latex → Euphorbia (irritant; keep from eyes) or fig/ficus. |
| **Habit** | Rosette, upright, bushy, trailing, clumping. Runners spreading sideways → mint, strawberry. |
| **Flowers / fruit** | The most diagnostic trait; one flower photo often settles it. |
| **Smell** (owner crushes a leaf) | Clove/anise, menthol, citrus, "tomato vine", soapy, onion: settles basil vs mint, cilantro vs parsley, chives vs grass. |
| **Roots / storage organs** | Bulb, corm, tuber, rhizome, pseudobulb, silvery orchid roots → bulbs, orchids, dormancy-prone plants. |
| **Seedling stage** | Cotyledons look alike across many species. Claim no more than family until the first true leaves. |

### Lookalike traps

| Trap | How to tell them apart | Foliage-only confidence |
|---|---|---|
| **Sweet basil vs other mint-family plants** | Sweet basil: glossy, smooth or slightly toothed, often cupped oval leaves; clove/anise smell; white flower spikes. Mint: serrated, often wrinkled, runners, menthol. Lemon balm: scalloped, heart-shaped, lemony. Holy basil (tulsi): smaller, often hairy, may be purple-tinged, spicy clove. Thai basil: purple stems, narrower leaves, anise. Shiso: large, deeply toothed, often purple or bicolor. Coleus: ornamental patterns, not a culinary herb. Cuban oregano: thick, fuzzy, succulent leaves. | Medium (smell → High) |
| **Cilantro vs flat-leaf parsley** | Cilantro: paler, softer, rounder lobes; upper leaves turn feathery with age; cilantro smell. Parsley: darker, glossier, sharper pointed lobes, sturdier stems, grassy smell. | Medium (smell → High) |
| **Pothos vs heartleaf philodendron** | Pothos (*Epipremnum aureum*): thicker, waxier, often asymmetric leaves; grooved petiole; one thick aerial root per node; new leaf unrolls from the previous one. Philodendron (*P. hederaceum*): thinner, softer, symmetric heart with a drawn-out tip; round petiole; new leaves from a sheath (cataphyll) that dries brown; thinner, often several roots per node. Also: "satin pothos" is *Scindapsus pictus*; *Monstera deliciosa* vs *Rhaphidophora tetrasperma* ("mini monstera"). | Medium |
| **Tomato vs pepper vs eggplant seedlings** | Cotyledons are hard to separate (eggplant's are often broader and more oval, *rule of thumb*). True leaves: tomato toothed or lobed, hairy, smells of tomato vine; pepper simple, smooth, glossy, hairless stem; eggplant broad, oval, felted, often wavy-edged, sometimes purple-tinted or prickly. "Potato-leaf" tomatoes have smooth leaflets and can fool you. | Low at cotyledons; Medium–High from true leaves |
| **Hot vs sweet pepper** | **Cannot be told from foliage.** Ask for the tag, and note the uncertainty in the profile before anyone tastes a fruit. | — (ask) |
| **Succulents** | Hybrids are everywhere and stress color changes looks. Aim for **genus** (Echeveria, Graptopetalum, Sempervivum, Crassula, Haworthia, Gasteria, Aloe, Agave, Sedum, Kalanchoe). Jade: thicker, larger leaves on thick stems; elephant bush (*Portulacaria afra*): small leaves on thinner reddish stems. True cacti have areoles; spiny Euphorbias don't (paired spines, milky sap). Watch for glued-on "flowers" and painted spines on store cacti. | Genus Medium; species Low unless tagged |
| **Chives vs garlic chives vs green onion vs grass** | Chives: thin, hollow, round, onion smell, purple pom-pom flowers. Garlic chives: flat, solid, garlic smell, white flowers. Green onion: thicker hollow leaves, often regrown from a grocery root end. Grass: flat, no smell. | Medium (smell → High) |
| **Microgreen root hairs vs mold** | Root hairs: fine, even white fuzz on the roots near the seed that vanishes when misted. Mold: cobwebby patches on seeds, stems, or the surface, musty smell, doesn't vanish when misted. | Medium (ask for a close-up) |
| **Spider plant vs young dracaena vs grass** | Spider plant: arching, often striped leaves from a central crown, runners with plantlets. Dracaena: leaves on a developing woody stem. | Medium |

**Volunteers.** A seedling that "just came up" may be a weed. **Never confirm edibility of a volunteer**, especially in the carrot family (Apiaceae), which includes deadly lookalikes such as poison hemlock.

### Cultivar limits
- Foliage identifies species, sometimes type (butterhead vs romaine, curly vs flat parsley, determinate vs indeterminate over time), **rarely a cultivar**. Record `cultivar: unknown` unless tagged.
- Tomato cultivars differ mostly by fruit; wait for fruit. Pepper heat can't be judged from the plant.
- Grocery-store potted basil is usually a sweet basil type labeled only "basil" *(rule of thumb)*.
- Purple or variegated foliage narrows the options ("a purple basil cultivar") but doesn't confirm one. A tag or seed packet is High evidence.

### Purpose classes
Record one primary class (optional secondary). **The owner's goal overrides the default**: basil grown for pollinators is an ornamental for care purposes.

| Class (profile value) | Examples | KALE optimizes for |
|---|---|---|
| `fruiting-edible` | Tomato, pepper, strawberry, cucumber, dwarf citrus | Flowering, fruit set, yield, flavor; steady water; indoor pollination help |
| `leafy-greens` | Lettuce, spinach, kale, chard, Asian greens | Tender leaves, steady growth, delayed bolting, regular harvest |
| `herb-culinary` | Basil, mint, parsley, cilantro, chives, oregano, thyme, rosemary | Aroma, bushy shape through pinching; flowers usually pinched |
| `herb-medicinal` | Chamomile, lemon balm, holy basil, aloe | Plant health and harvest timing. **No dosing or medical advice.** |
| `microgreens-sprouts` | Radish, pea shoots, sunflower, broccoli; jar sprouts | Days to harvest, even germination, mold prevention, hygiene (raw sprouts carry a known food-safety risk) |
| `flowering-ornamental` | Jasmine, gardenia, African violet, orchid, geranium, lavender | Bud set, bloom length, scent, deadheading, rebloom |
| `foliage-houseplant` | Pothos, philodendron, monstera, calathea, fern, snake plant | Steady growth, good color and variegation, no pests |
| `succulent-cactus` | Echeveria, jade, haworthia, aloe, cacti | Compact shape, color, no rot, seasonal rest |
| `carnivorous` | Venus flytrap, sundew, pitcher plants, butterwort | Pure water (rain, distilled, RO), nutrient-poor media, bright light, dormancy for temperate species; **no soil fertilizer** |
| `other` | Seedling trees, bonsai, aquatics, air plants, "mystery seed" | Identify further; first-principles fallback |

### Toxicity heads-up (pets and kids)
A **heads-up, not a diagnosis**. If a pet or child may have eaten a plant, the right move is a vet, a poison control center, or a pet poison hotline, not KALE. Entries marked ASPCA follow the ASPCA toxic/non-toxic plant list; recheck others for the specific species.

| Plant(s) | Heads-up |
|---|---|
| **True lilies** (*Lilium*) and **daylilies** (*Hemerocallis*) | **Severe for cats**: small exposures (even pollen or vase water) can cause kidney failure. Top-priority flag with cats. |
| **Sago palm** (*Cycas*) | Highly toxic to pets (liver damage); all parts, seeds worst. |
| **Aroids**: pothos, philodendron, monstera, dieffenbachia, peace lily, ZZ plant, alocasia, caladium, calla | Calcium oxalate: mouth irritation, drooling, vomiting in pets; mouth pain for children. |
| **Aloe vera** (ASPCA) | Toxic to dogs and cats (vomiting, lethargy, diarrhea). |
| **Jade**, **snake plant**, **dracaena** | Listed toxic to dogs and cats; usually GI upset. |
| **Euphorbias** (poinsettia, pencil cactus, crown of thorns) | Milky sap irritates skin and eyes. Poinsettia is usually mild, but flag it. |
| **Alliums**: chives, garlic, onion, leeks (ASPCA) | Toxic to dogs and cats (red blood cell damage); cats especially sensitive. |
| **Tomato** green parts (ASPCA) | Leaves and stems toxic to dogs and cats; **ripe fruit is non-toxic**. |
| **Mint, oregano, lavender, parsley** (ASPCA) | Listed toxic to dogs and cats; usually mild (GI upset in quantity; parsley photosensitivity in quantity). |
| **Coleus / Cuban oregano** (ASPCA) | Toxic to dogs and cats (vomiting, diarrhea). |
| **Spring bulbs**: tulip, daffodil, hyacinth, amaryllis | Toxic to pets; bulbs are the most concentrated part. |
| **Oleander, foxglove, lily of the valley, castor bean** | Dangerous to people and pets. Flag strongly if kids or pets share the space. |
| Generally listed **non-toxic**: basil, rosemary, Venus flytrap (ASPCA); spider plant, Boston fern, calathea/prayer plant, African violet, Christmas cactus, haworthia, echeveria | Still not pet food; pesticide residue on store plants is its own concern. |

Species not listed and not known: write `toxicity: unknown, check before letting pets or kids at it` rather than guessing.
