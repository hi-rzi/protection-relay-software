"""
Single-line-diagram (SLD) primitives for illustrating each relay's protection
zone: bus - CT - protected equipment - CT - bus, with the differential (or
overcurrent) zone boundary and relay device-number bubble overlaid.

These are deliberately simplified schematic symbols (standard ANSI/IEC style),
not a reproduction of any site as-built drawing — just enough to show WHERE
the CTs sit and WHAT is inside the protected zone for a given relay.
"""

import math
import os

import streamlit as st

BUS_COLOR = "#1F2937"
CT_COLOR = "#2563EB"
ZONE_COLOR = "#DC2626"
LEADER_COLOR = "#6B7280"
TEXT_COLOR = "#111827"

ASSET_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "sld")


def render_zone_diagram(image_filename, fallback_svg_html):
    """
    Show the engineer's real AutoCAD Electrical SLD (assets/sld/<image_filename>)
    if it's been provided; otherwise fall back to the auto-generated schematic so
    the tab never looks broken while the real drawing is still pending.
    """
    image_path = os.path.join(ASSET_DIR, image_filename)
    if os.path.isfile(image_path):
        st.image(image_path, use_container_width=True)
    else:
        st.info(
            "No AutoCAD Electrical SLD provided yet for this equipment — showing an "
            "auto-generated placeholder schematic instead."
        )
        st.markdown(fallback_svg_html, unsafe_allow_html=True)


def sld_path(image_filename):
    return os.path.join(ASSET_DIR, image_filename)


def save_uploaded_sld(image_filename, uploaded_file):
    """Persists an uploaded SLD image to assets/sld/<image_filename>,
    overwriting any existing file there. This is the SAME location
    render_zone_diagram() reads from, so uploading a relay's SLD from the
    FMEA page immediately shows up on that equipment's own Theory tab too,
    not just wherever the upload happened."""
    os.makedirs(ASSET_DIR, exist_ok=True)
    dest_path = sld_path(image_filename)
    with open(dest_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return dest_path


def _header(width, height):
    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;height:auto;font-family:Segoe UI,Arial,sans-serif;background:#ffffff;">'
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>'
    )


def _footer():
    return "</svg>"


def _bus(x1, y1, x2, y2):
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{BUS_COLOR}" stroke-width="4"/>'


def _label(x, y, text, size=13, anchor="middle", weight="normal", color=TEXT_COLOR):
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" '
        f'font-weight="{weight}" fill="{color}">{text}</text>'
    )


def _ct(x, y, label_lines=None, label_side="above"):
    """A CT symbol: a circle straddling the bus, with an optional stacked label."""
    svg = f'<circle cx="{x}" cy="{y}" r="15" fill="#ffffff" stroke="{CT_COLOR}" stroke-width="2.5"/>'
    svg += f'<line x1="{x-9}" y1="{y+6}" x2="{x+9}" y2="{y-6}" stroke="{CT_COLOR}" stroke-width="2"/>'
    if label_lines:
        base_y = y - 26 if label_side == "above" else y + 34
        step = -14 if label_side == "above" else 14
        for i, line in enumerate(label_lines):
            svg += _label(x, base_y + i * step, line, size=12, color=CT_COLOR)
    return svg


def _relay_bubble(x, y, tag, r=26):
    svg = f'<circle cx="{x}" cy="{y}" r="{r}" fill="#EFF6FF" stroke="{TEXT_COLOR}" stroke-width="2"/>'
    svg += _label(x, y + 5, tag, size=13, weight="bold")
    return svg


def _leader(x1, y1, x2, y2):
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{LEADER_COLOR}" '
        f'stroke-width="1.5" stroke-dasharray="4,3"/>'
    )


def _h_arrow(x1, y, x2, color=BUS_COLOR, width=2.5):
    """Horizontal line from x1 to x2 at height y, with an arrowhead at x2 (works either direction)."""
    svg = f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{color}" stroke-width="{width}"/>'
    d = 1 if x2 > x1 else -1
    svg += f'<polygon points="{x2},{y} {x2-10*d},{y-6} {x2-10*d},{y+6}" fill="{color}"/>'
    return svg


def _zone_box(x1, y1, x2, y2, label):
    svg = (
        f'<rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" fill="none" '
        f'stroke="{ZONE_COLOR}" stroke-width="2.5" stroke-dasharray="8,5" rx="10"/>'
    )
    svg += _label((x1 + x2) / 2, y1 - 12, label, size=13, weight="bold", color=ZONE_COLOR)
    return svg


def _generator_symbol(cx, cy, label, r=40):
    svg = f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#ffffff" stroke="{BUS_COLOR}" stroke-width="3"/>'
    svg += (
        f'<path d="M {cx-22} {cy} q 11 -18 22 0 q 11 18 22 0" fill="none" '
        f'stroke="{BUS_COLOR}" stroke-width="2"/>'
    )
    svg += _label(cx, cy + r + 20, label, size=13, weight="bold")
    return svg


def _motor_symbol(cx, cy, label, r=36):
    svg = f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#ffffff" stroke="{BUS_COLOR}" stroke-width="3"/>'
    svg += _label(cx, cy + 7, "M", size=22, weight="bold")
    svg += _label(cx, cy + r + 20, label, size=13, weight="bold")
    return svg


def _transformer_symbol(cx, cy, label, vertical=True, r=24):
    """Classic two-overlapping-circles transformer symbol."""
    if vertical:
        c1 = (cx, cy - r * 0.6)
        c2 = (cx, cy + r * 0.6)
    else:
        c1 = (cx - r * 0.6, cy)
        c2 = (cx + r * 0.6, cy)
    svg = f'<circle cx="{c1[0]}" cy="{c1[1]}" r="{r}" fill="#ffffff" stroke="{BUS_COLOR}" stroke-width="3"/>'
    svg += f'<circle cx="{c2[0]}" cy="{c2[1]}" r="{r}" fill="#ffffff" stroke="{BUS_COLOR}" stroke-width="3"/>'
    label_y = cy + r * 1.6 + 22 if vertical else cy + r + 22
    svg += _label(cx, label_y, label, size=13, weight="bold")
    return svg


# ---------------------------------------------------------------------------
# Generator (87G) — Neutral CT — Generator — Terminal CT — to GSUT
# ---------------------------------------------------------------------------
def generator_zone_svg(relay, ct_polarity, tag="87G"):
    W, H = 760, 320
    y = 150
    svg = _header(W, H)

    svg += _bus(40, y, 700, y)
    svg += _label(60, y - 55, "Neutral\nGrounding".split("\n")[0], size=12, color=LEADER_COLOR)
    svg += _label(60, y - 40, "(Neutral end)", size=11, color=LEADER_COLOR)
    svg += _label(680, y - 55, "To GSUT", size=12, color=LEADER_COLOR, anchor="end")
    svg += _label(680, y - 40, "(Terminal end)", size=11, color=LEADER_COLOR, anchor="end")

    ct_n_x, ct_t_x = 190, 550
    svg += _ct(ct_n_x, y, [f"CT {relay.ct_ratio_N:.0f}:{relay.ct_secondary_rating:.0f}", "Neutral"], "above")
    svg += _ct(ct_t_x, y, [f"CT {relay.ct_ratio_T:.0f}:{relay.ct_secondary_rating:.0f}", "Terminal"], "above")

    svg += _generator_symbol((ct_n_x + ct_t_x) / 2, y + 70, "GENERATOR")

    svg += _zone_box(ct_n_x - 40, y - 90, ct_t_x + 40, y + 135, f"{tag} PROTECTION ZONE")

    rx, ry = (ct_n_x + ct_t_x) / 2, y - 130
    svg += _leader(ct_n_x, y - 15, rx - 15, ry + 15)
    svg += _leader(ct_t_x, y - 15, rx + 15, ry + 15)
    svg += _relay_bubble(rx, ry, tag)

    svg += _label(
        (ct_n_x + ct_t_x) / 2, H - 18,
        f"Polarity reference: {ct_polarity} — currents shown are secondary CT amps into the relay",
        size=11, color=LEADER_COLOR,
    )
    svg += _footer()
    return svg


# ---------------------------------------------------------------------------
# 2-winding transformer (EXCT / GSUT) — HV CT — Transformer — LV CT
# ---------------------------------------------------------------------------
def two_winding_transformer_zone_svg(relay, ct_polarity, tag, hv_bus_label="HV Bus", lv_bus_label="LV Bus"):
    W, H = 760, 340
    y = 160
    svg = _header(W, H)

    svg += _bus(40, y, 700, y)
    svg += _label(60, y - 20, hv_bus_label, size=12, color=LEADER_COLOR)
    svg += _label(680, y - 20, lv_bus_label, size=12, color=LEADER_COLOR, anchor="end")

    w_hv, w_lv = relay.windings[0], relay.windings[1]
    ct_hv_x, ct_lv_x = 190, 550
    svg += _ct(ct_hv_x, y, [f"CT {w_hv['ct_ratio']:.0f}:{w_hv['ct_secondary_rating']:.0f}", w_hv["name"]], "above")
    svg += _ct(ct_lv_x, y, [f"CT {w_lv['ct_ratio']:.0f}:{w_lv['ct_secondary_rating']:.0f}", w_lv["name"]], "above")

    svg += _transformer_symbol((ct_hv_x + ct_lv_x) / 2, y + 85, "", vertical=False, r=30)

    svg += _zone_box(ct_hv_x - 40, y - 100, ct_lv_x + 40, y + 145, f"{tag} PROTECTION ZONE")

    rx, ry = (ct_hv_x + ct_lv_x) / 2, y - 140
    svg += _leader(ct_hv_x, y - 15, rx - 15, ry + 15)
    svg += _leader(ct_lv_x, y - 15, rx + 15, ry + 15)
    svg += _relay_bubble(rx, ry, tag)

    svg += _label(
        (ct_hv_x + ct_lv_x) / 2, H - 18,
        f"Taps T1={w_hv['tap']:.2f} / T2={w_lv['tap']:.2f} — polarity reference: {ct_polarity}",
        size=11, color=LEADER_COLOR,
    )
    svg += _footer()
    return svg


# ---------------------------------------------------------------------------
# Overall GSUT-GEN (87O) — 3-restraint zone: Generator / HV / UAT
# ---------------------------------------------------------------------------
def overall_zone_svg(relay, ct_polarity, tag="87OA/87OB"):
    W, H = 820, 420
    y = 190
    svg = _header(W, H)

    w_hv, w_gen, w_uat = relay.windings[0], relay.windings[1], relay.windings[2]

    # Generator on the left, HV bus (to grid) on the right, UAT tapped off the
    # generator-side bus between the generator and the GSUT.
    svg += _bus(60, y, 620, y)
    svg += _label(80, y - 20, "Generator", size=12, color=LEADER_COLOR)
    svg += _label(600, y - 20, "To 525kV Grid", size=12, color=LEADER_COLOR, anchor="end")

    ct_gen_x, ct_hv_x = 190, 540
    svg += _ct(ct_gen_x, y, [f"CT {w_gen['ct_ratio']:.0f}:{w_gen['ct_secondary_rating']:.0f}", w_gen["name"]], "above")
    svg += _generator_symbol(ct_gen_x - 90, y, "GENERATOR")

    svg += _transformer_symbol((ct_gen_x + ct_hv_x) / 2 + 60, y + 90, "GSUT", vertical=False, r=26)
    svg += _ct(ct_hv_x, y, [f"CT {w_hv['ct_ratio']:.0f}:{w_hv['ct_secondary_rating']:.0f}", w_hv["name"]], "above")

    # UAT branch, tapped downward off the mid-bus
    uat_tap_x = 380
    uat_y = y + 190
    svg += f'<line x1="{uat_tap_x}" y1="{y}" x2="{uat_tap_x}" y2="{uat_y-40}" stroke="{BUS_COLOR}" stroke-width="4"/>'
    ct_uat_y = uat_y - 40
    svg += _ct(uat_tap_x, ct_uat_y, None)
    svg += _label(uat_tap_x + 55, ct_uat_y + 4, f"CT {w_uat['ct_ratio']:.0f}:{w_uat['ct_secondary_rating']:.0f} ({w_uat['name']})", size=12, color=CT_COLOR, anchor="start")
    svg += _transformer_symbol(uat_tap_x, uat_y + 20, "Unit Aux. Xfmr", vertical=True, r=22)

    svg += _zone_box(ct_gen_x - 40, y - 90, ct_hv_x + 40, uat_y + 60, f"{tag} — OVERALL ZONE")

    rx, ry = (ct_gen_x + ct_hv_x) / 2, y - 130
    svg += _leader(ct_gen_x, y - 15, rx - 60, ry + 20)
    svg += _leader(ct_hv_x, y - 15, rx + 60, ry + 20)
    svg += _leader(uat_tap_x, ct_uat_y - 15, rx, ry + 20)
    svg += _relay_bubble(rx, ry, tag, r=32)

    svg += _label(
        W / 2, H - 18,
        f"Taps T1={w_hv['tap']:.2f} (HV) / T2={w_gen['tap']:.2f} (Gen) / T3={w_uat['tap']:.2f} (UAT) "
        f"— polarity reference: {ct_polarity}",
        size=11, color=LEADER_COLOR,
    )
    svg += _footer()
    return svg


# ---------------------------------------------------------------------------
# ID Fan motor — 50/50/51 time-overcurrent (not a differential zone: a single
# CT feeding a discrete overcurrent relay ahead of the motor breaker)
# ---------------------------------------------------------------------------
def motor_overcurrent_svg(ct_ratio, ct_secondary_rating, backup_ct_ratio=None, tag="50/50/51", backup_tag="50 (Backup)",
                           bus_label="13.8kV Switchgear Bus", motor_label="ID FAN MOTOR"):
    W, H = 640, 300
    y = 140
    svg = _header(W, H)

    svg += _bus(40, y, 460, y)
    svg += _label(60, y - 20, bus_label, size=12, color=LEADER_COLOR)

    ct_x = 200
    svg += _ct(ct_x, y, [f"CT {ct_ratio:.0f}:{ct_secondary_rating:.0f}"], "above")

    # breaker symbol
    brk_x = 300
    svg += f'<rect x="{brk_x-12}" y="{y-12}" width="24" height="24" fill="#ffffff" stroke="{BUS_COLOR}" stroke-width="3"/>'
    svg += _label(brk_x, y - 26, "52", size=12, weight="bold")

    svg += _bus(brk_x + 12, y, 460, y)
    svg += _motor_symbol(540, y, motor_label)

    rx, ry = ct_x, y - 110
    svg += _leader(ct_x, y - 15, rx, ry + 26)
    svg += _relay_bubble(rx, ry, tag)

    if backup_ct_ratio:
        ct2_x = 240
        ct2_y = y + 70
        svg += f'<line x1="{ct_x}" y1="{y}" x2="{ct_x}" y2="{ct2_y}" stroke="{LEADER_COLOR}" stroke-width="1.5" stroke-dasharray="2,2"/>'
        svg += _ct(ct2_x, ct2_y, [f"CT {backup_ct_ratio:.0f}:{ct_secondary_rating:.0f}"], "below")
        svg += _relay_bubble(ct2_x + 150, ct2_y, backup_tag, r=24)
        svg += _leader(ct2_x, ct2_y, ct2_x + 128, ct2_y)

    svg += _label(
        W / 2, H - 18,
        "Discrete time-overcurrent protection — not a differential (no zone boundary)",
        size=11, color=LEADER_COLOR,
    )
    svg += _footer()
    return svg


# ---------------------------------------------------------------------------
# Operating Principle diagrams — generic/conceptual (same for every relay of a
# given type), unlike the zone diagrams above which are equipment-specific.
# These illustrate HOW the relay logic decides to trip, not WHERE the CTs
# physically sit (that's the Protection Zone diagram).
# ---------------------------------------------------------------------------
def differential_principle_svg():
    W, H = 720, 300
    svg = _header(W, H)
    y = 95

    svg += _label(90, y - 42, "I₁ (into zone)", size=13, color=CT_COLOR)
    svg += _ct(90, y, None)
    svg += _h_arrow(106, y, 278, color=BUS_COLOR)

    svg += _label(630, y - 42, "I₂ (out of zone)", size=13, color=CT_COLOR)
    svg += _ct(630, y, None)
    svg += _h_arrow(614, y, 442, color=BUS_COLOR)

    box_x1, box_y1, box_x2, box_y2 = 280, y - 42, 440, y + 42
    svg += (
        f'<rect x="{box_x1}" y="{box_y1}" width="{box_x2-box_x1}" height="{box_y2-box_y1}" '
        f'fill="#EFF6FF" stroke="{TEXT_COLOR}" stroke-width="2" rx="8"/>'
    )
    svg += _label((box_x1 + box_x2) / 2, y - 6, "Differential", size=13, weight="bold")
    svg += _label((box_x1 + box_x2) / 2, y + 14, "Element", size=13, weight="bold")

    mid_x = (box_x1 + box_x2) / 2
    out_y = y + 95
    svg += f'<line x1="{mid_x}" y1="{box_y2}" x2="{mid_x}" y2="{out_y - 30}" stroke="{BUS_COLOR}" stroke-width="2"/>'
    svg += _label(mid_x, out_y, "I_op = |I₁ − I₂|", size=14, weight="bold", color=ZONE_COLOR)
    svg += _label(mid_x, out_y + 20, "I_rest = avg or sum of |I₁|, |I₂|", size=12, color=LEADER_COLOR)

    decision_y = out_y + 55
    svg += (
        f'<rect x="{mid_x-150}" y="{decision_y-22}" width="300" height="36" fill="#FEF2F2" '
        f'stroke="{ZONE_COLOR}" stroke-width="1.5" rx="6"/>'
    )
    svg += _label(mid_x, decision_y + 2, "TRIP if I_op > Threshold(I_rest)", size=13, weight="bold", color=ZONE_COLOR)

    svg += _label(
        W / 2, H - 18,
        "Healthy: I₁ ≈ I₂, so I_op stays near 0. Internal fault: I₁ ≠ I₂, so I_op grows large.",
        size=11, color=LEADER_COLOR,
    )
    svg += _footer()
    return svg


def overcurrent_principle_svg():
    """
    Conceptual (illustrative only) inverse-time trip curve: shaded 'no trip'
    region below the curve, shaded 'trip' region above it. The curve shape
    itself uses the standard IEEE Moderately Inverse constants (IEEE
    C37.112: A=0.0515, p=0.02, B=0.1140) purely to draw a realistic inverse-
    time shape for this generic diagram - it is NOT the actual relay curve
    used elsewhere in this app (each equipment's real TCC Curve tab computes
    its own manufacturer-specific formula from its own real settings).
    """
    W, H = 640, 340
    svg = _header(W, H)

    ox, oy = 90, 280
    ax_top, ax_right = 40, 590

    svg += _h_arrow(ox, oy, ax_right, color=BUS_COLOR)
    svg += f'<line x1="{ox}" y1="{oy}" x2="{ox}" y2="{ax_top}" stroke="{BUS_COLOR}" stroke-width="2.5"/>'
    svg += f'<polygon points="{ox},{ax_top} {ox-6},{ax_top+10} {ox+6},{ax_top+10}" fill="{BUS_COLOR}"/>'

    svg += _label(ax_right - 10, oy + 24, "Current", size=13, anchor="end")
    svg += _label(ox - 12, ax_top + 2, "Time", size=13, anchor="end")

    # IEEE Moderately Inverse shape (illustrative curve only, see docstring above)
    A, p, B = 0.0515, 0.02, 0.1140
    m_start, m_end, max_time = 1.01, 10.0, 16.0
    plot_left, plot_right = ox + 15, ax_right - 15
    n_points = 120
    pts = []
    for i in range(n_points + 1):
        m = m_start + (m_end - m_start) * i / n_points
        t = min(A / (m ** p - 1) + B, max_time)
        x = plot_left + (plot_right - plot_left) * (m - m_start) / (m_end - m_start)
        y = oy - (oy - ax_top) * (t / max_time)
        pts.append((round(x, 1), round(y, 1)))

    pts_str = " ".join(f"{x},{y}" for x, y in pts)
    below_region = f"{pts_str} {plot_right},{oy} {plot_left},{oy}"
    above_region = f"{pts_str} {plot_right},{ax_top} {plot_left},{ax_top}"
    curve_path = "M " + " L ".join(f"{x} {y}" for x, y in pts)

    # Shade regions BEFORE the curve line so the curve stays visually on top.
    svg += f'<polygon points="{below_region}" fill="#D9F2D9" opacity="0.7"/>'
    svg += f'<polygon points="{above_region}" fill="#FADBD8" opacity="0.7"/>'
    svg += f'<path d="{curve_path}" fill="none" stroke="{CT_COLOR}" stroke-width="3"/>'

    svg += _label((ox + ax_right) / 2, ax_top - 12, "51 Inverse-Time Trip Curve", size=13, color=CT_COLOR, weight="bold")
    svg += _label(
        plot_left + (plot_right - plot_left) * 0.35, oy - 30,
        "NORMAL START", size=13, color="#006600", weight="bold"
    )
    svg += _label(
        plot_left + (plot_right - plot_left) * 0.35, oy - 12,
        "(No Trip Region)", size=11, color="#006600"
    )
    svg += _label(
        plot_left + (plot_right - plot_left) * 0.65, ax_top + 60,
        "LOCKED ROTOR / FAULT", size=13, color="#B30000", weight="bold"
    )
    svg += _label(
        plot_left + (plot_right - plot_left) * 0.65, ax_top + 78,
        "(Trip Region)", size=11, color="#B30000"
    )

    svg += _label(
        W / 2, H - 18,
        "Higher current → shorter trip time, so severe faults clear fast while normal starting current is tolerated.",
        size=11, color=LEADER_COLOR, weight="normal"
    )
    svg += _footer()
    return svg
