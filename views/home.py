import streamlit as st

st.title("Electrical Equipment Protection Suite")
st.caption("Protection settings calculation, commissioning-injection assistance, and settings verification for generator, transformer, and motor protection relays.")

st.markdown(
    """
This app helps engineers work through protection relay settings for generator,
transformer, and motor equipment. For each relay it provides:

- **Live simulation** — enter operating currents and see the real-time trip/restraint verdict against the relay's characteristic curve.
- **Commissioning & injection tool** — calculates the exact secondary current to inject at a test set for a target test point.
- **Test point verification** — log actual measured test results and compare them against the calculated characteristic.
- **PDF / CSV export** — for keeping a record of settings and test results.

Every equipment page ships with built-in presets (currently POMI's own relay settings), but you're not
limited to them — each page also lets you add a **custom profile** with your own ratings, CT
specs, and protection settings, so the app works for equipment outside POMI too.

Working across several equipment for the same plant? The **Project** page bundles the settings
you've configured across all of them into one named, saveable file — see the sidebar.

Pick an equipment category from the sidebar to get started.
"""
)

st.markdown("### Quick Start")
st.markdown(
    """
1. **Pick an equipment category from the sidebar** (Generator, Transformer, or Motor) and choose the specific relay.
2. **Load a preset** at the top of the sidebar — a real POMI relay, or *Custom Profile* to enter your own ratings and CT specs. The page fills in immediately with real settings.
3. **Scroll the "Current Settings" section** at the top of the page — every setting currently applied is right there, editable in place. Adjust a value and read the comment beside it:
   - 🟢 green = clears the recommended margin
   - 🟠 orange = below the recommended margin, worth a second look
   - ⚪ neutral = informational only (no automated check exists for that setting yet — engineering judgment required)
4. **Use the tabs below** for deeper work — simulate a fault, calculate a commissioning test injection, view the trip-time curve, or export a report. See the full guide below for what each tab does.

The rest of this page is a full reference guide — expand whichever section is relevant. Nothing below is required reading to get started; it's here for when you want to understand *why* the app does what it does, or you're stuck on something specific.
"""
)

with st.expander("How the two relay families differ — and why the pages don't all look the same", expanded=False):
    st.markdown(
        """
This app models two genuinely different kinds of protection, and the page layout reflects that on purpose rather than forcing one template on both:

**Percentage-bias differential protection** — Generator (87G) and all four Transformer pages (EXCT, GSUT, Overall GSUT-GEN, Auxiliary).
These relays compare current flowing IN to a protected zone against current flowing OUT. In a healthy zone the two should match; a real internal fault makes them diverge. Because two (or three) separate CTs are involved, each with its own ratio and possibly a Delta/Wye connection, some legitimate mismatch always exists from CT/tap-changer error alone — the relay's Bias/Minimum Operate settings exist specifically to ride through that expected mismatch without nuisance-tripping, while still catching a real fault. That's why these pages have a **CT Matching Taps** section and a **Mismatch** metric: the taps are chosen to minimize that mismatch, and the Bias/Min Operate/HOC settings are then sized against whatever mismatch remains.

**Time-overcurrent / thermal protection** — the three Motor pages (Induced Draft Fan, Primary Air Fan, Forced Draft Fan).
These relays watch a single current path (the motor's own supply) and trip based on HOW LONG a given current level persists, not on a mismatch between two currents. A motor draws several times its full-load current for a few seconds every time it starts — that's normal and must not trip the relay — but the exact same current sustained indefinitely (a locked rotor) will cook the winding insulation and must trip well before that happens. That's why these pages have a **Motor Starting & Safe Stall Data** section instead of CT taps: the relay's time-current curve has to thread the needle between "don't trip during a normal start" and "do trip before thermal damage on a stall," using the motor's own documented starting time and safe-stall time as the two boundaries.

Two of the motor pages (Induced Draft Fan, and Primary Air Fan) also have a **second, independent relay** modeled — a discrete electromechanical 50/50/51 unit that exists alongside the microprocessor-based relay as physical backup hardware at POMI. Where that's the case, you'll see an extra tab or section for it, clearly labeled with its own relay model number so it's never confused with the primary relay's settings.
"""
    )

with st.expander("The \"Current Settings\" section, in depth", expanded=False):
    st.markdown(
        """
This is the first thing you see on every equipment page, and it's designed to answer "what is this relay currently set to, and is that reasonable?" without clicking into anything.

**How the comments are generated.** Every comment reuses a check that already exists elsewhere in the app's own engineering logic — nothing is generated freehand by an AI guess at the moment you view the page. For example:
- A transformer's Bias/Minimum Operate comment is driven by the actual computed CT/tap mismatch on that same page (`common/settings_advisor.py`'s `suggest_bias_settings`) — the same formula the old "Settings Calculator" used, just surfaced inline next to the field it applies to instead of hidden in a separate expander.
- A motor's Overload Pickup or Instantaneous Pickup comment checks against the motor's own Full Load Current or Locked Rotor Current, entered in the same Current Settings section just above.
- A motor's Time Dial / Curve Multiplier comment runs the relay's actual trip-time formula against the motor's documented starting time and safe-stall time — the identical calculation shown in full on the TCC Curve tab, just condensed into one pass/fail line here.

**Why some fields only get a neutral, informational note.** Not every setting has an established rule-of-thumb in this app. Where that's the case (Ground Fault pickup, RTD alarm setpoints, frequency thresholds, and similar), the page says so explicitly rather than inventing a plausible-sounding check — a fabricated "looks fine" is worse than no answer at all, since it would create false confidence.

**A real example this caught during development:** on the Overall GSUT-GEN page, an HV tap accidentally restored from an old saved Project at 0.40 (instead of the documented 1.0) drove the computed mismatch up from a normal ~1% to over 140%, and the suggested Bias floor accordingly spiked to an obviously-unreasonable 295%. That's not a bug — it's the exact mechanism working as intended: an extreme, obviously-wrong recommendation is a strong signal that an *input* is wrong, not that the relay genuinely needs a 295% bias setting. If a recommendation ever looks absurd, the fix is almost always to check the inputs feeding it (CT ratios, taps, connection types) rather than the recommendation itself.

**The "Overall status" line** at the end of the section is a single summary: every individual check shown above, ANDed together. It is deliberately conservative — if even one check is borderline, the overall status says review is needed, rather than averaging things out into a false "mostly fine."
"""
    )

with st.expander("Every tab, in depth", expanded=False):
    st.markdown(
        """
**Theory tab**
What the relay protects and why it matters if it fails, a single-line diagram of the protection zone (CTs, polarity, the equipment being protected), and — for motor pages — a live-updating thermal capacity replica showing how much of the motor's thermal budget the current test scenario is using.

**Live Simulation tab**
Enter an actual PRIMARY-side current (and, for differential relays, a phase angle) and see the real-time trip/restraint verdict plotted against the relay's real characteristic curve. This is the fastest way to answer "if this exact current happened right now, would it trip?" — useful for sanity-checking a fault study result, or just building intuition for where the relay's margins sit. Also where you'll find the PDF protection-audit report export and the relay-ready settings sheet.

**Commissioning & Injection Tool tab**
Turns the question around: instead of "what happens at this current," it answers "what do I need to inject at the test set to hit a specific target point on the curve." Pick a target restraint/pickup multiple and the tab calculates the exact SECONDARY current (the small, safe current an actual test set injects, after the CT ratio) to dial in. The Auto-Sweep table below generates a full set of test points across the curve in one click — useful for building a complete commissioning test plan rather than calculating points one at a time.

**TCC Curve tab** (motor pages) / **Test Point Verification & Curve tab** (differential pages)
The relay's full time-current or bias characteristic plotted as a curve, not just a single point. For motors with starting data on record, the motor's own starting profile (locked rotor current vs. acceleration time) and safe-stall limits are overlaid directly on the same chart — the curve should visually pass BELOW the safe-stall markers and ABOVE the starting markers for the setting to be coordinated correctly. On differential pages, this tab also lets you log actual measured test results and draw a "CAL." line straight through them, exactly matching the style of a real commissioning test report — useful for comparing what a test set actually measured against what the relay was supposed to do.

**Settings Summary & Approval tab**
The document-control layer: source document, revision, prepared-by/reviewed-by, and a review status dropdown, plus a consolidated table of every coordination check on the page in one place. Exports both a formal PDF summary report and a JSON settings file you can re-load into this app later (via the Settings File uploader in the sidebar, on pages that support it) or bundle into a Project.

**Historian Data Overlay** (inside the TCC/curve tab on most pages)
Upload a CSV export from a real historian/SCADA system (a `timestamp` column plus one or more numeric current columns) to see what the equipment actually did in service, plotted against the relay's rated and pickup thresholds. This deliberately does NOT try to recompute the relay's own operate/restraint currents from this data — a historian only logs current magnitude, not the phase angle the differential math needs — so it overlays real magnitudes against threshold lines rather than pretending to reproduce the relay's internal trip logic from incomplete data.

**Relay-Ready Settings Sheet** (inside the Live Simulation tab on most pages)
A checklist of every setting, named exactly the way that relay's own instruction manual or settings summary names it (e.g. "T1 (HV Tap)", "51 Tap (A sec.)") — meant for manually typing into the relay's own settings software or front-panel HMI. This is intentionally NOT an importable project file for the relay vendor's software: this app has no access to those proprietary file formats, and guessing at one risks silently wrong settings reaching a relay in service. A checklist you type from is a slower but far safer handoff.
"""
    )

with st.expander("Typical workflows — step by step", expanded=False):
    st.markdown(
        """
**"I just want to check whether a specific setting looks reasonable."**
Open the equipment page → load the relevant preset (or enter your own data under Custom Profile) → read the comment next to that field in Current Settings. If it's green, you're done. If it's orange, read the comment text — it explains what's being compared and why.

**"I'm preparing for a commissioning test."**
Open the equipment page → confirm Current Settings matches what's actually going to be field-set → go to the Commissioning & Injection Tool tab → either calculate individual target points, or use Auto-Sweep to generate a full test table → download the CSV to bring to site.

**"I have real test results and want to check them against the calculated curve."**
Go to the TCC Curve / Test Point Verification tab → enter each measured result under "Add Test Points" → switch the CAL. line source to "Connect my test points" to see them plotted the same way a real commissioning report would show them, or leave it on "Theoretical" to compare your points against the calculated curve directly.

**"I need to check whether this motor's relay will trip during a normal start."**
Make sure the motor's Locked Rotor Current, Acceleration Time, and Safe Stall Time are entered in Current Settings (under Motor Starting & Safe Stall Data) → read the margin comment next to the Time Dial / Curve Multiplier field → for the full picture, open the TCC Curve tab and check that the curve passes below the Safe Stall markers and above the Start markers at both 100% and 80% voltage.

**"I'm managing settings across several pieces of equipment for the same outage."**
Configure each equipment page you need → go to the Project page → give it a name and save it as a JSON file → next session (or for someone else picking up the work), load that file on the Project page, then revisit each equipment page and select "📁 Restored from Project" from its preset list to actually apply the restored values there.

**"A recommendation on this page looks way off — is that a bug?"**
Almost always not a bug in the recommendation logic itself — check the inputs feeding it first (CT ratios, taps, connection types, motor data). An extreme or nonsensical recommendation is usually the app correctly reacting to a wrong input, not a broken formula. See the worked example in the "Current Settings section, in depth" guide above.

**"I found that a setting doesn't match what the source document says."**
Don't assume either the app or the document is right without checking. This has happened for real during development (see the note on data trustworthiness below) — the resolution each time was going back to the original settings calculation document and re-deriving the number, not guessing.
"""
    )

with st.expander("The Project page, in depth", expanded=False):
    st.markdown(
        """
The Project page is the cross-equipment layer sitting above the individual relay pages — useful once you're working with more than one piece of equipment at a time (e.g. everything for a single unit outage).

**Save/load a Project.** Every equipment page mirrors its current live settings into the Project's memory automatically as you use it — there's no separate "save to project" button on each page. When you're ready, go to the Project page, give it a name and optional commissioning notes, and download it as a JSON file. Loading that file back in (on the Project page, via the file uploader) restores it into the Project's memory — but each individual equipment page still needs to be revisited and set to "📁 Restored from Project" in its own preset selector to actually apply those values there. This two-step design is deliberate: it means loading a Project never silently overwrites a page you're actively editing without your say-so.

**Equipment Status dashboard.** A table summarizing every equipment type: whether it's been configured this session, a one-line summary (MVA rating, or motor FLA), and a rule-of-thumb Health signal (✅ OK / ⚠️ Review / — not yet configured) reusing the exact same margin checks shown inline on that equipment's own Current Settings section. This is a glance-level status board, not a coordination study — revisit the actual equipment page for the full picture behind any ⚠️ flag.

**Protection Zone Coordination Check.** Cross-references the Generator, GSUT, and Overall GSUT-GEN pages against each other, specifically:
- **Shared CT consistency** — the Generator terminal CT and the GSUT HV-side CT each feed BOTH their own primary differential relay AND the Overall backup relay's corresponding input. Per the Overall relay's own settings document, these are the same physical CT, so their recorded ratios should always match across the two pages. If they ever drift apart, that's flagged as a real data error to review — most likely one of the two pages has a stale or mistyped CT ratio.
- **Backup zone coverage** — states plainly which equipment has a documented backup differential zone via the Overall relay and which doesn't. The Overall relay's own settings document defines its zone as covering the Generator, the GSUT, and the Unit Auxiliary Transformer bus — the Excitation Transformer is NOT one of its three restraint inputs, so it has no backup differential zone recorded anywhere in this app. Worth a conversation with your supervisor about whether that's an accepted, deliberate risk or a genuine gap.

This is deliberately scoped to what can be checked from data already entered across pages — it is NOT a full relay-to-relay time-grading/coordination study (e.g. checking a motor relay against its upstream switchgear breaker), since that would need settings data for equipment not yet modeled in this app.
"""
    )

with st.expander("Presets vs. Custom Profile", expanded=False):
    st.markdown(
        """
Every equipment page's preset selector offers at least one real POMI relay preset, sourced from that equipment's actual settings calculation document, plus a "Custom Profile" option.

- **Real presets** are populated with values cross-checked against their source document's own worked numerical examples wherever possible — not just copied from a summary table. Where a value couldn't be independently confirmed, the app says so explicitly (either in a caption on the page or in this guide) rather than presenting an unverified number with the same confidence as a confirmed one.
- **Custom Profile** starts from generic placeholder values and lets you enter your own ratings, CT specs, and protection settings — this app isn't limited to POMI's own equipment. All the same live comments and checks apply to a Custom Profile exactly as they do to a real preset.
- **"📁 Restored from Project"** appears as an extra preset option once you've saved a Project that includes that equipment — selecting it loads whatever was captured in that saved file. Keep in mind this restores EXACTLY what was saved, including anything that was mid-edit or accidental at save time (see the Project section above).
"""
    )

with st.expander("Glossary of terms used throughout the app", expanded=False):
    st.markdown(
        """
| Term | Meaning |
|---|---|
| **CT** | Current Transformer — steps a large primary current down to a small, standard secondary current (typically 5A or 1A) that relays and meters can safely work with. |
| **CT ratio** | The CT's primary-to-secondary ratio, e.g. "600:5" means 600A primary produces 5A secondary at rated current. |
| **Tap / CT-matching tap** | A relay setting that scales an incoming CT current so that, at rated load, differently-rated CTs on either side of a differential zone read as the same normalized value inside the relay. |
| **Mismatch** | The percentage difference between two (or more) windings' tap-corrected currents at rated load — should be small; the relay's Bias/Minimum Operate settings must be set to tolerate it without nuisance-tripping. |
| **Bias (τ)** | The percentage-restraint slope of a differential relay — how much operating (differential) current is tolerated as restraint current increases, to ride through CT error and external-fault effects without misoperating. |
| **Minimum Operate** | The smallest differential current that will trip the relay even at zero restraint current — the pickup floor. |
| **HOC** | High-Set Overcurrent (or "unrestrained instantaneous") — an unrestrained differential element that trips instantly above a very high threshold, for severe internal faults where waiting for the biased characteristic would be too slow. |
| **FLA** | Full Load Current (or Full Load Amps) — the motor's rated running current. |
| **LRC / Locked Rotor Current** | The current a motor draws if its rotor is prevented from turning (or during the first moments of a normal start) — several times FLA, and the basis for setting instantaneous pickups high enough to ride through a normal start. |
| **Safe Stall Time** | How long a motor can sustain locked-rotor current before winding insulation is thermally damaged — the relay's overload element must trip before this time is reached. |
| **51 / 50 / 46 / 87 (device numbers)** | Standard ANSI/IEEE device function numbers used throughout the industry and this app: 51 = AC time-overcurrent, 50 = AC instantaneous overcurrent, 46 = current unbalance, 87 = differential protection. |
| **TCC** | Time-Current Characteristic — the curve of trip time vs. current that defines a relay's overcurrent behavior. |
| **Restraint current (I_rest) / Operating current (I_op)** | The two axes of a differential relay's characteristic curve — I_rest represents the "healthy load" reference level, I_op is the actual differential (fault-indicating) current; a point above the curve trips, below it restrains. |
"""
    )

with st.expander("Frequently asked questions", expanded=False):
    st.markdown(
        """
**Why does the same kind of setting get a hard pass/fail on one page but only an informational note on another?**
Because the underlying engineering basis genuinely differs. For example, Generator differential Pickup deliberately does NOT get the same 20%-floor check that transformer Minimum Operate gets — a generator's two CTs have no equivalent to a transformer's inherent tap/turns-ratio mismatch, so industry-standard generator pickup is conventionally set low (5-10%), and applying the transformer's floor logic there would flag a correct setting as wrong. Each page's checks are matched to that equipment's actual physics, not copy-pasted from a template.

**Can I trust every number this app shows?**
Every real preset value has been cross-checked against its source document wherever a worked example existed to check it against — several real errors were caught and fixed this way during development (a CT ratio that didn't match its own documented tap, a thermal curve multiplier that had been assumed instead of calculated, an instantaneous pickup set using the wrong convention). Where a value couldn't be independently verified, the app is explicit about that rather than presenting a guess with false confidence. That said, this remains an engineering support tool, not a substitute for review — see the note below.

**Why did a recommendation change drastically after I loaded a saved Project?**
The Project restore mechanism faithfully replays whatever was live on that page at save time — including anything that was accidentally mid-edit when you saved. If a value looks wrong after a restore, fix it in the current session and re-save the Project so future loads pick up the corrected value.

**Does this app connect to or modify real relays?**
No. It's entirely a calculation and cross-checking tool — the Relay-Ready Settings Sheet is a manual-entry checklist by design, specifically because generating an auto-importable file for a relay vendor's proprietary software would risk putting a wrong setting into a live relay silently.
"""
    )

st.markdown(
    """
**A note on what this app is (and isn't):** every page supports settings checks and commissioning
calculations, but does not itself approve relay settings. Recommendations are rule-of-thumb starting
points and consistency checks, not a substitute for a real through-fault/inrush coordination study —
always verify against the approved coordination study, relay manual, and site test procedure before
applying settings in service.
"""
)

st.markdown("### Available Equipment")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("#### Generator")
    st.write(
        "Generator differential protection (87G) covering:\n"
        "- GE G60 numerical dual-breakpoint characteristic\n"
        "- GE CFD22B4A legacy product-restraint characteristic"
    )

with col2:
    st.markdown("#### Transformer")
    st.write(
        "Transformer differential protection covering:\n"
        "- Excitation Transformer (EXCT)\n"
        "- Generator Step-Up Transformer (GSUT)\n"
        "- Overall GSUT-GEN (backup, 3-winding)\n"
        "- Auxiliary Transformer"
    )

with col3:
    st.markdown("#### Motor")
    st.write(
        "Motor protection covering:\n"
        "- Induced Draft (ID) Fan — 50/50/51 time-overcurrent, GE 869 microprocessor MPR\n"
        "- Primary Air (PA) Fan and Forced Draft (FD) Fan — Multilin SR469 static MPR"
    )
