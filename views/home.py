import streamlit as st

st.title("Electrical Equipment Protection Suite")
st.caption("Protection settings calculation, commissioning-injection assistance, and settings verification for generator, transformer, and motor protection relays.")

st.markdown(
    """
This app helps engineers work through protection relay settings for generator, transformer, and
motor equipment — settings checks, commissioning-injection calculations, and trip-curve
verification, all in one place.
"""
)

st.markdown("### How to Use This App")
st.markdown(
    """
1. **Pick an equipment category from the sidebar** (Generator, Transformer, or Motor) and choose the specific relay.
2. **Load a preset** at the top of the sidebar — a real POMI relay, or *Custom Profile* to enter your own ratings and CT specs.
3. **Read the "Current Settings" section** at the top of the page — every setting currently applied, editable in place. Adjust a value and read the comment beside it:
   - 🟢 green = clears the recommended margin
   - 🟠 orange = below the recommended margin, worth a second look
   - ⚪ neutral = informational only (no rule-of-thumb check for that setting yet)
4. **Use the tabs below** for deeper work: **Live Simulation** (test a current against the curve), **Commissioning & Injection Tool** (calculate test-set injection values), **TCC Curve** (the full trip-time curve, plus logging real test results), **Settings Summary & Approval** (document control + PDF export).
5. Working across multiple equipment? Use the **Project** page (sidebar) to save/load settings across all of them at once.

Every recommendation below is a rule-of-thumb starting point, not a substitute for a real coordination study — always confirm against the approved study, relay manual, and site test procedure before applying settings in service.
"""
)

st.markdown("### Recommended Values")
st.markdown(
    """
**Transformer differential relays** (EXCT, GSUT, Overall GSUT-GEN, Auxiliary):
| Setting | Recommended | Why |
|---|---|---|
| Minimum Operate | ≥ 20%, or ≥ 2× the computed CT/tap mismatch | Floors out CT error and tap rounding so a healthy load can't nuisance-trip |
| Bias (τ) | ≥ Minimum Operate; ≥ 20% (2-winding) or ≥ 30% (3-winding, e.g. Overall) | Extra winding = more CT error can stack on a through-fault |
| HOC (unrestrained) | ~5× tap current (2-winding), ~8× (3-winding) | Clears inrush/CT saturation, still trips fast on a severe internal fault |
| CT matching taps | As close as possible to the computed "ideal tap" for each winding, chosen jointly to minimize overall mismatch | Taps aren't independent — see the page's own T_E reference values |

**Generator differential (87G):**
| Setting | Recommended | Why |
|---|---|---|
| Pickup (G60) | Typically 5-10% | No CT-mismatch concern like a transformer has — sensitivity is the priority |
| Target/Seal-in (CFD22B4A legacy) | ≥ 0.1A, ideally ≥ 0.25A | Per GEK-34124E — below 0.1A isn't recommended; the rear contact may need up to 0.25A to close |

**Motor protection (ID Fan, PA Fan, FD Fan):**
| Setting | Recommended | Why |
|---|---|---|
| Overload Pickup | 110-115% FLA | Rides through minor overload/voltage fluctuation, protects per the thermal damage curve |
| Instantaneous Pickup | ~200-300% Locked Rotor Current | Clears normal starting inrush, trips well below a genuine terminal fault |
| 51 Tap | Nearest available tap to FLA + ~15% margin | Matches the thermal element to actual full-load current |
| Time Dial / Curve Multiplier | Whatever keeps trip time BELOW safe-stall time and ABOVE starting time, at both 100% and 80% voltage | The core coordination requirement — check the TCC Curve tab |

If a recommendation on a page looks extreme (e.g. a bias floor in the hundreds of percent), it's almost always telling you an *input* is wrong — a CT ratio, tap, or connection type — not that the setting genuinely needs to be that high. Check the inputs first.
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
