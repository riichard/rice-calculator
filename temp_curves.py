"""
Rice Precise — Cultivar-Specific Temperature Curve Profiles

Generates ideal cooking temperature curves per rice variety, based on:
  1. Gelatinization temperature (DSC onset/peak/conclusion) — derived from amylose
  2. Enzyme activation window (40-60°C) — for sweetness/umami development
  3. Starch accessibility — controls ramp rate through critical zones
  4. Target texture — stickiness/softness/definition goals

The Zojirushi applies one generic curve to all "white rice". This module
generates cultivar-specific curves that a custom controller could follow.

Key cooking phases and what they do:
  1. SOAK (20-35°C): Water diffuses into grain. Duration matters, temp less so.
  2. ENZYME (40-60°C): Native amylases convert starch → sugars. Longer dwell
     at 50-55°C = sweeter, more umami. Glucose peaks at 50°C. This is the
     "Zojirushi slow ramp" phase — and where cultivar differences matter most.
  3. RAMP (60-Tgel_onset): Gentle heating toward gelatinization. Too fast =
     uneven core. Too slow = mushy exterior before core gelatinizes.
  4. GELATINIZATION (Tgel_onset-Tgel_end): Starch granules swell and rupture.
     The critical window. Duration here sets texture — longer = softer.
  5. FULL COOK (Tgel_end-100°C): Complete gelatinization, drive out raw flavor.
  6. REST (100→85°C): Moisture equalization, surface retrogradation for
     grain definition. Skipping this = wet, poorly defined grains.

DSC data anchors:
  - Kinmaze (japonica, ~17% amylose): To=61.8°C, Tp=71.3°C, Tc=79.8°C
  - Indica (#1110-290, ~23% amylose): To=66.4°C, Tp=76.0°C, Tc=84.3°C
  - SSIIa mutant (japonica, ~20% amylose): To=56.2°C, Tp=65.7°C, Tc=74.2°C
  - Japonica gelatinization is ~8°C lower than indica (genetic basis: SSIIa)

Enzyme data:
  - Glucose production peaks at 50°C (100% relative)
  - At 40°C: 66.4%, at 60°C: 91.9%, at 70°C: 76.6%
  - Oligosaccharides peak at 50-60°C
  - Enzymes denature above ~65-70°C (irreversible)
"""

from dataclasses import dataclass
from rice_model import VARIETIES, RiceVariety, GrainType


# ─── Gelatinization Temperature Estimation ─────────────────────────────────────

# From DSC literature: japonica with ~17% amylose has onset ~62°C, peak ~71°C.
# Higher amylose → higher gelatinization temp (positive correlation).
# Japonica SSIIa gene reduces gel temp by ~8°C vs indica at same amylose.

def estimate_gel_temps(v: RiceVariety) -> dict:
    """Estimate DSC gelatinization temperatures from cultivar properties.

    Returns dict with onset, peak, conclusion temperatures in °C.
    """
    # Base: japonica Kinmaze at 17% amylose
    # To = 61.8, Tp = 71.3, Tc = 79.8
    # Amylose coefficient: +0.9°C per 1% amylose above 17%
    amylose_shift = 0.9 * (v.amylose_pct - 17.0)

    # Japonica vs indica: indica is ~8°C higher at same amylose
    # Approximate by grain type — japonica varieties are WHITE or BROWN
    # from Japan/Korea/China; indica are long-grain from SE Asia/India
    # This is crude but directionally correct
    indica_shift = 0.0
    if v.origin in ("Thailand", "India/Pakistan", "Vietnam", "Cambodia"):
        indica_shift = 5.0  # Partial indica shift (not pure indica)

    # Near-zero amylose (glutinous): very low gel temp
    if v.amylose_pct < 5.0:
        base_onset = 55.0
        base_peak = 63.0
        base_conclusion = 72.0
    else:
        base_onset = 61.8
        base_peak = 71.3
        base_conclusion = 79.8

    return {
        "onset": round(base_onset + amylose_shift + indica_shift, 1),
        "peak": round(base_peak + amylose_shift + indica_shift, 1),
        "conclusion": round(base_conclusion + amylose_shift + indica_shift, 1),
    }


# ─── Cooking Phase Definition ──────────────────────────────────────────────────

@dataclass
class CookingPhase:
    """A phase in the ideal cooking temperature curve."""
    name: str
    temp_start: float       # °C
    temp_end: float         # °C
    duration_min: float     # Minutes
    ramp_rate: float        # °C per minute (0 = hold)
    purpose: str            # What this phase achieves


@dataclass
class TemperatureCurve:
    """Complete ideal cooking curve for a cultivar."""
    variety_key: str
    variety_name: str
    phases: list[CookingPhase]
    gel_temps: dict          # DSC onset/peak/conclusion
    total_time_min: float
    notes: str

    def as_setpoints(self, interval_sec: float = 30.0) -> list[tuple[float, float]]:
        """Generate (time_seconds, temp_celsius) setpoints for a controller.

        Returns list of (time, temp) tuples at the given interval.
        """
        setpoints = []
        t = 0.0
        for phase in self.phases:
            steps = max(1, int(phase.duration_min * 60 / interval_sec))
            for i in range(steps):
                frac = i / steps
                temp = phase.temp_start + frac * (phase.temp_end - phase.temp_start)
                setpoints.append((round(t, 1), round(temp, 1)))
                t += interval_sec
        # Final point
        last_phase = self.phases[-1]
        setpoints.append((round(t, 1), round(last_phase.temp_end, 1)))
        return setpoints


# ─── Texture Profiles ──────────────────────────────────────────────────────────
# How texture goals translate to cooking parameters:
#
# HIGH STICKINESS (e.g., Milky Queen, Yumepirika):
#   - Longer enzyme phase → more surface starch breakdown
#   - Slower ramp through gelatinization → more granule rupture
#   - Shorter rest → less surface retrogradation
#
# HIGH GRAIN DEFINITION (e.g., Niji no Kirameki, Basmati):
#   - Shorter enzyme phase → preserve starch structure
#   - Faster ramp through gelatinization → less over-swelling
#   - Longer rest → more surface firming
#
# HIGH SOFTNESS (e.g., Yumepirika):
#   - Longer gelatinization hold → complete granule conversion
#   - Lower ramp rate → even heating
#
# Enzyme phase duration sweet spot: 50°C is optimal for glucose/sweetness
# (100% relative production). Holding at 50-55°C is the "secret" of
# premium rice cookers.


def generate_curve(variety_key: str, target: str = "balanced",
                   total_target_min: float | None = None) -> TemperatureCurve:
    """Generate ideal temperature curve for a variety.

    Args:
        variety_key: Key into VARIETIES dict
        target: Texture target — 'balanced', 'sticky_soft', 'firm_defined',
                'max_sweetness', 'quick'
        total_target_min: Optional total time constraint (adjusts durations)

    Returns TemperatureCurve with phase breakdown.
    """
    v = VARIETIES[variety_key]
    gel = estimate_gel_temps(v)

    # ── Base phase durations scaled by texture goals ───────────────────
    # Enzyme phase: 50-55°C dwell for sweetness
    # Base: 8 min for average japonica
    enzyme_base = 8.0
    gel_hold_base = 10.0
    rest_base = 12.0

    if target == "sticky_soft":
        enzyme_mult = 1.5     # More sweetness
        gel_hold_mult = 1.3   # More granule conversion
        rest_mult = 0.7       # Less surface firming
        ramp_rate = 2.0       # Slower ramp
    elif target == "firm_defined":
        enzyme_mult = 0.6     # Preserve structure
        gel_hold_mult = 0.8   # Less swelling
        rest_mult = 1.3       # More surface firming
        ramp_rate = 4.0       # Faster ramp
    elif target == "max_sweetness":
        enzyme_mult = 2.5     # Maximum enzyme time
        gel_hold_mult = 1.0
        rest_mult = 1.0
        ramp_rate = 2.5
    elif target == "quick":
        enzyme_mult = 0.3
        gel_hold_mult = 0.6
        rest_mult = 0.5
        ramp_rate = 5.0
    else:  # balanced
        enzyme_mult = 1.0
        gel_hold_mult = 1.0
        rest_mult = 1.0
        ramp_rate = 3.0

    # ── Cultivar-specific adjustments ──────────────────────────────────
    # Low amylose (sticky varieties): naturally need less enzyme time
    # because they're already sweet, but benefit from slower gelatinization
    if v.amylose_pct < 12:
        enzyme_mult *= 0.7
        gel_hold_mult *= 1.2

    # High amylose (separate-grain varieties): need more aggressive
    # gelatinization to fully cook through
    if v.amylose_pct > 22:
        gel_hold_mult *= 1.3
        ramp_rate *= 0.8  # Slow down to ensure even cooking

    # Brown/pigmented: bran slows heat transfer → slower ramp needed
    if v.grain_type in (GrainType.BROWN, GrainType.PIGMENTED):
        ramp_rate *= 0.6
        gel_hold_mult *= 1.5
        rest_base *= 1.3

    # Starch accessibility: fast absorbers (Tsuyahime) need care
    if v.starch_accessibility < 0.85:
        ramp_rate *= 0.8  # Gentle with fast-absorbing varieties

    # ── Build phase list ───────────────────────────────────────────────
    enzyme_dur = round(enzyme_base * enzyme_mult, 1)
    gel_hold_dur = round(gel_hold_base * gel_hold_mult, 1)
    rest_dur = round(rest_base * rest_mult, 1)

    # Ramp durations calculated from rate
    soak_to_enzyme_dur = round((50.0 - 30.0) / ramp_rate, 1)
    enzyme_to_gel_dur = round((gel["onset"] - 55.0) / ramp_rate, 1)
    gel_ramp_dur = round((gel["conclusion"] - gel["onset"]) / ramp_rate, 1)
    gel_to_boil_dur = round((100.0 - gel["conclusion"]) / ramp_rate, 1)

    phases = [
        CookingPhase(
            "Soak (warm)", 20, 30, 5.0, 2.0,
            "Initial warm-up. Water penetration begins. "
            "Most hydration already done in pre-soak.",
        ),
        CookingPhase(
            "Ramp to enzyme zone", 30, 50, soak_to_enzyme_dur, ramp_rate,
            "Gentle heating toward enzyme activation temperature.",
        ),
        CookingPhase(
            "Enzyme dwell", 50, 55, enzyme_dur, round(5.0 / max(1, enzyme_dur), 2),
            f"Hold at 50-55C for amylase activity. Glucose peaks at 50C. "
            f"Longer = sweeter rice. This is the 'secret' of premium cookers.",
        ),
        CookingPhase(
            "Ramp to gelatinization", 55, gel["onset"],
            max(1.0, enzyme_to_gel_dur), ramp_rate,
            f"Heating toward starch gelatinization onset ({gel['onset']}C). "
            f"Enzymes denature above ~65C.",
        ),
        CookingPhase(
            "Gelatinization ramp", gel["onset"], gel["conclusion"],
            gel_ramp_dur, ramp_rate,
            f"Starch granules swell and rupture ({gel['onset']}-{gel['conclusion']}C). "
            f"The critical texture-setting phase.",
        ),
        CookingPhase(
            "Gelatinization hold", gel["conclusion"], gel["conclusion"],
            gel_hold_dur, 0.0,
            "Hold at conclusion temp for complete gelatinization. "
            "Longer = softer texture.",
        ),
        CookingPhase(
            "Ramp to full cook", gel["conclusion"], 100, gel_to_boil_dur, ramp_rate,
            "Drive to boiling. Eliminates raw starch flavor.",
        ),
        CookingPhase(
            "Full cook", 100, 100, 5.0, 0.0,
            "Sustained boil for complete cooking.",
        ),
        CookingPhase(
            "Rest / steam equalization", 100, 85, rest_dur, 0.0,
            "Lid sealed. Moisture redistributes internally. "
            "Surface retrogradation firms grain exterior. "
            "Do not skip — critical for texture.",
        ),
    ]

    total_time = sum(p.duration_min for p in phases)

    # ── Time constraint adjustment ─────────────────────────────────────
    if total_target_min and total_time > total_target_min:
        scale = total_target_min / total_time
        for p in phases:
            p.duration_min = round(p.duration_min * scale, 1)
        total_time = sum(p.duration_min for p in phases)

    # ── Notes ──────────────────────────────────────────────────────────
    notes_parts = []
    if v.stickiness >= 4.0:
        notes_parts.append("High stickiness target — longer gel hold, shorter rest")
    if v.grain_definition >= 4.0:
        notes_parts.append("High definition target — faster ramp, longer rest")
    if v.amylose_pct < 5:
        notes_parts.append("Glutinous — low gel temp, traditionally steamed not boiled")
    if v.grain_type in (GrainType.BROWN, GrainType.PIGMENTED):
        notes_parts.append("Bran intact — slower ramp needed for even heat penetration")

    return TemperatureCurve(
        variety_key=variety_key,
        variety_name=v.name,
        phases=phases,
        gel_temps=gel,
        total_time_min=round(total_time, 1),
        notes="; ".join(notes_parts) if notes_parts else "Standard curve",
    )


def compare_curves(*variety_keys: str, target: str = "balanced") -> None:
    """Print comparison of temperature curves for multiple varieties."""
    curves = [generate_curve(k, target) for k in variety_keys]

    print(f"Temperature Curve Comparison — target: {target}")
    print("=" * 90)

    # Header
    names = [c.variety_name.split("(")[0].strip()[:18] for c in curves]
    print(f"{'Phase':<25s}", end="")
    for name in names:
        print(f" {name:>18s}", end="")
    print()
    print("-" * (25 + 19 * len(curves)))

    # Gel temps
    print(f"{'Gel onset':<25s}", end="")
    for c in curves:
        print(f" {c.gel_temps['onset']:>16.1f}C", end="")
    print()
    print(f"{'Gel peak':<25s}", end="")
    for c in curves:
        print(f" {c.gel_temps['peak']:>16.1f}C", end="")
    print()
    print(f"{'Gel conclusion':<25s}", end="")
    for c in curves:
        print(f" {c.gel_temps['conclusion']:>16.1f}C", end="")
    print()
    print("-" * (25 + 19 * len(curves)))

    # Phase durations
    for i, phase_name in enumerate([p.name for p in curves[0].phases]):
        print(f"{phase_name[:24]:<25s}", end="")
        for c in curves:
            if i < len(c.phases):
                p = c.phases[i]
                print(f" {p.duration_min:>6.1f}m {p.temp_start:>3.0f}-{p.temp_end:>3.0f}C", end="")
            else:
                print(f" {'':>18s}", end="")
        print()

    print("-" * (25 + 19 * len(curves)))
    print(f"{'TOTAL':<25s}", end="")
    for c in curves:
        print(f" {c.total_time_min:>16.1f}m", end="")
    print()
    print()
    for c in curves:
        if c.notes:
            print(f"  {c.variety_name.split('(')[0].strip()}: {c.notes}")


# ─── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Rice Precise — Cultivar-Specific Temperature Curves")
    print()

    # ── Show curves for Richard's main varieties ──────────────────────
    compare_curves("hitomebore", "tsuyahime", "niji_no_kirameki", "yumepirika")
    print()

    # ── Extreme comparison: sticky vs defined ─────────────────────────
    compare_curves("milky_queen", "basmati", "red_cargo")
    print()

    # ── Same variety, different targets ───────────────────────────────
    print("Hitomebore — different texture targets:")
    print("=" * 70)
    for target in ["balanced", "sticky_soft", "firm_defined", "max_sweetness", "quick"]:
        curve = generate_curve("hitomebore", target)
        enzyme = next(p for p in curve.phases if "Enzyme" in p.name)
        gel_hold = next(p for p in curve.phases if "hold" in p.name.lower()
                        and "Gel" in p.name)
        rest = next(p for p in curve.phases if "Rest" in p.name)
        print(f"  {target:<16s}  enzyme: {enzyme.duration_min:>5.1f}m  "
              f"gel hold: {gel_hold.duration_min:>5.1f}m  "
              f"rest: {rest.duration_min:>5.1f}m  "
              f"total: {curve.total_time_min:>5.1f}m")

    # ── Controller setpoints demo ─────────────────────────────────────
    print()
    print("Controller setpoints for Tsuyahime (first 5 minutes, 30s interval):")
    curve = generate_curve("tsuyahime")
    setpoints = curve.as_setpoints(interval_sec=30)
    for t_sec, temp in setpoints[:10]:
        print(f"  t={t_sec:>6.0f}s  →  {temp:>5.1f}°C")
    print(f"  ... ({len(setpoints)} total setpoints over {curve.total_time_min:.0f} min)")
