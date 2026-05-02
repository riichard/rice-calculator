"""
Rice Precise — Cooking Cycle Simulation (Optional)

Simulates the thermal profile and starch gelatinization during cooking.
Models Zojirushi pressure IH cycle, open pot, pressure cooker, and steamer.

This module is optional — the core model in rice_model.py works without it.
When enabled, it replaces the flat soak_time_multiplier with a physics-based
simulation that accounts for:
  - Warm soaking (Zojirushi pre-heats to 30-40°C during soak)
  - Temperature-dependent Peleg absorption during the cooking ramp
  - Gelatinization kinetics (Arrhenius-based)
  - Pressure effects on boiling point and gelatinization

Zojirushi cycle data from:
  - Japanese manuals and patents (via user's ChatGPT conversation)
  - Phase temperatures and durations from teardown analyses
  - Pressure range: 1.2-1.3 atm → 103-108°C internal temp

Gelatinization kinetics:
  - Rice starch gelatinization onset: 58-72°C (variety-dependent)
  - Rate follows Arrhenius: k_gel = A * exp(-Ea / (R * T))
  - Activation energy Ea ≈ 150-200 kJ/mol for rice starch
  - Reference: Bao et al. 2021, ScienceDirect starch gelatinization studies
"""

from dataclasses import dataclass
from enum import Enum
import math

from rice_model import (
    RiceVariety, CookingMethod, GrainType, VARIETIES,
    peleg_moisture, _interpolate_m0,
)


# ─── Gelatinization Parameters ─────────────────────────────────────────────────

# Gelatinization onset temperature by amylose class
# Higher amylose → higher gelatinization temperature (literature consensus)
def gel_onset_temp(amylose_pct: float) -> float:
    """Estimate gelatinization onset temperature from amylose content."""
    # Range: ~60°C (low amylose) to ~72°C (high amylose)
    return 58.0 + 0.56 * amylose_pct


def gel_peak_temp(amylose_pct: float) -> float:
    """Estimate gelatinization peak temperature."""
    return gel_onset_temp(amylose_pct) + 8.0


# Arrhenius parameters for gelatinization rate
EA_GEL = 170_000.0   # Activation energy (J/mol) — rice starch average
R_GAS = 8.314         # Gas constant (J/(mol·K))
A_GEL = 1e24          # Pre-exponential factor (tuned to give ~15 min at 100°C)


def gel_rate(temp_c: float, amylose_pct: float) -> float:
    """Gelatinization rate constant at given temperature.

    Returns rate in 1/min. Multiply by dt to get fractional conversion.
    Below onset temperature, rate is effectively zero.
    """
    onset = gel_onset_temp(amylose_pct)
    if temp_c < onset - 5:
        return 0.0

    temp_k = temp_c + 273.15
    rate = A_GEL * math.exp(-EA_GEL / (R_GAS * temp_k))

    # Amylose correction: higher amylose → slightly slower gelatinization
    amylose_factor = 1.0 - 0.01 * (amylose_pct - 17.0)
    return rate * max(0.3, amylose_factor)


# ─── Temperature-Dependent Peleg ───────────────────────────────────────────────

def peleg_k1_at_temp(k1_20: float, temp_c: float) -> float:
    """Adjust Peleg k1 for temperature.

    k1 decreases linearly with temperature (faster absorption at higher T).
    From Allie et al. 2025: k1 drops ~50-60% from 30°C to 70°C.
    Regression: k1(T) = k1_20 * (1 - 0.025 * (T - 20))
    """
    factor = max(0.2, 1.0 - 0.025 * (temp_c - 20.0))
    return k1_20 * factor


def peleg_k2_at_temp(k2_20: float, temp_c: float) -> float:
    """Adjust Peleg k2 for temperature.

    k2 also decreases with temperature (more total absorption at higher T).
    Regression: k2(T) = k2_20 * (1 - 0.012 * (T - 20))
    """
    factor = max(0.3, 1.0 - 0.012 * (temp_c - 20.0))
    return k2_20 * factor


# ─── Cooking Cycle Definitions ─────────────────────────────────────────────────

@dataclass
class CyclePhase:
    """A phase in the cooking cycle."""
    name: str
    duration_min: float      # Duration in minutes
    temp_start: float        # Temperature at start (°C)
    temp_end: float          # Temperature at end (°C)
    pressure_atm: float      # Pressure in atm (1.0 = atmospheric)
    is_soak: bool = False    # Whether this phase counts as soaking


def boiling_point(pressure_atm: float, barometric_hpa: float = 1013.25) -> float:
    """Boiling point of water at given pressure.

    Uses Clausius-Clapeyron approximation.
    pressure_atm: gauge pressure in atm above atmospheric (for cookers)
    barometric_hpa: ambient atmospheric pressure
    """
    # Total absolute pressure
    atm_from_barometric = barometric_hpa / 1013.25
    total_atm = atm_from_barometric + (pressure_atm - 1.0)

    # Clausius-Clapeyron: ΔT ≈ T² * R / ΔH_vap * ln(P2/P1)
    # Simplified: bp ≈ 100 + 28.02 * ln(total_atm)
    if total_atm <= 0:
        return 80.0  # Safety floor
    return 100.0 + 28.02 * math.log(total_atm)


# ── Zojirushi Pressure IH Cycle ───────────────────────────────────────────────

def zojirushi_pressure_cycle(mode: str = "white",
                             barometric_hpa: float = 1013.25) -> list[CyclePhase]:
    """Approximate Zojirushi Pressure IH cooking cycle.

    Modes: 'white', 'brown', 'sushi'
    """
    bp = boiling_point(1.0, barometric_hpa)  # Atmospheric boiling point
    bp_pressure = boiling_point(1.25, barometric_hpa)  # Under 1.25 atm

    if mode == "white":
        return [
            CyclePhase("Pre-soak",           20, 20, 38,  1.0, is_soak=True),
            CyclePhase("Gentle ramp",        12, 38, 80,  1.0),
            CyclePhase("Gelatinization",      8, 80, bp,  1.0),
            CyclePhase("Pressure cook",       5, bp, bp_pressure, 1.25),
            CyclePhase("Pressure pulse 1",    2, bp_pressure, bp_pressure, 1.25),
            CyclePhase("Depressurize",        2, bp_pressure, bp, 1.0),
            CyclePhase("Pressure pulse 2",    3, bp, bp_pressure, 1.25),
            CyclePhase("Release",             3, bp_pressure, bp, 1.0),
            CyclePhase("Steam rest",         12, bp, 85,  1.0),
        ]
    elif mode == "brown":
        return [
            CyclePhase("Extended soak",      40, 20, 40,  1.0, is_soak=True),
            CyclePhase("Gentle ramp",        15, 40, 80,  1.0),
            CyclePhase("Gelatinization",     10, 80, bp,  1.0),
            CyclePhase("Pressure cook",       8, bp, bp_pressure, 1.25),
            CyclePhase("Pressure pulse 1",    3, bp_pressure, bp_pressure, 1.25),
            CyclePhase("Depressurize",        2, bp_pressure, bp, 1.0),
            CyclePhase("Pressure pulse 2",    4, bp, bp_pressure, 1.25),
            CyclePhase("Release",             3, bp_pressure, bp, 1.0),
            CyclePhase("Steam rest",         15, bp, 80,  1.0),
        ]
    elif mode == "sushi":
        return [
            CyclePhase("Pre-soak",           15, 20, 35,  1.0, is_soak=True),
            CyclePhase("Gentle ramp",        10, 35, 80,  1.0),
            CyclePhase("Gelatinization",      8, 80, bp,  1.0),
            CyclePhase("Pressure cook",       4, bp, bp_pressure, 1.25),
            CyclePhase("Release",             3, bp_pressure, bp, 1.0),
            CyclePhase("Steam rest",         10, bp, 88,  1.0),
        ]
    else:
        raise ValueError(f"Unknown Zojirushi mode: {mode}")


def zojirushi_micom_cycle(mode: str = "white",
                          barometric_hpa: float = 1013.25) -> list[CyclePhase]:
    """Approximate Zojirushi Micom (non-IH, non-pressure) cooking cycle.

    Models: NS-LLH05, NS-LHC05, NS-LGC05 etc.
    Triple heater (bottom, side, lid), 450W, fuzzy logic timing.
    No pressure → max temp is atmospheric boiling point.
    Slower ramp and less precise temp control than IH models.
    """
    bp = boiling_point(1.0, barometric_hpa)

    if mode == "white":
        return [
            CyclePhase("Micom soak",         15, 20, 32,  1.0, is_soak=True),
            CyclePhase("Ramp (triple heat)",  15, 32, 80,  1.0),
            CyclePhase("Gelatinization",      10, 80, bp,  1.0),
            CyclePhase("Full boil",           10, bp, bp,  1.0),
            CyclePhase("Simmer down",          5, bp, 92,  1.0),
            CyclePhase("Steam rest",          12, 92, 82,  1.0),
        ]
    elif mode == "brown":
        return [
            CyclePhase("Extended soak",       30, 20, 35,  1.0, is_soak=True),
            CyclePhase("Ramp (triple heat)",  18, 35, 80,  1.0),
            CyclePhase("Gelatinization",      12, 80, bp,  1.0),
            CyclePhase("Full boil",           15, bp, bp,  1.0),
            CyclePhase("Simmer down",          5, bp, 92,  1.0),
            CyclePhase("Steam rest",          15, 92, 80,  1.0),
        ]
    elif mode == "sushi":
        return [
            CyclePhase("Micom soak",          12, 20, 30,  1.0, is_soak=True),
            CyclePhase("Ramp (triple heat)",  12, 30, 80,  1.0),
            CyclePhase("Gelatinization",       8, 80, bp,  1.0),
            CyclePhase("Full boil",            8, bp, bp,  1.0),
            CyclePhase("Simmer down",          4, bp, 94,  1.0),
            CyclePhase("Steam rest",          10, 94, 85,  1.0),
        ]
    else:
        raise ValueError(f"Unknown Zojirushi mode: {mode}")


def open_pot_cycle(barometric_hpa: float = 1013.25) -> list[CyclePhase]:
    """Simple stovetop open pot cycle."""
    bp = boiling_point(1.0, barometric_hpa)
    return [
        CyclePhase("Heat to boil",       8, 20, bp,  1.0),
        CyclePhase("Boil (lid on)",      12, bp, bp,  1.0),
        CyclePhase("Low simmer",          5, bp, 92,  1.0),
        CyclePhase("Rest (lid on)",      10, 92, 80,  1.0),
    ]


def pressure_cooker_cycle(barometric_hpa: float = 1013.25) -> list[CyclePhase]:
    """Instant Pot / pressure cooker cycle."""
    bp = boiling_point(1.0, barometric_hpa)
    bp_pressure = boiling_point(1.7, barometric_hpa)  # Higher pressure than Zojirushi
    return [
        CyclePhase("Heat to pressure",    8, 20, bp_pressure, 1.7),
        CyclePhase("Pressure cook",        4, bp_pressure, bp_pressure, 1.7),
        CyclePhase("Natural release",     10, bp_pressure, bp, 1.0),
        CyclePhase("Rest",                10, bp, 80, 1.0),
    ]


def steamer_cycle(barometric_hpa: float = 1013.25) -> list[CyclePhase]:
    """Traditional steaming cycle (e.g., for mochigome)."""
    bp = boiling_point(1.0, barometric_hpa)
    return [
        CyclePhase("Steam ramp",          5, 60, bp,  1.0),
        CyclePhase("Full steam",          25, bp, bp,  1.0),
        CyclePhase("Rest",                10, bp, 85,  1.0),
    ]


CYCLE_GENERATORS = {
    CookingMethod.ZOJIRUSHI_MICOM:    lambda hpa: zojirushi_micom_cycle("white", hpa),
    CookingMethod.ZOJIRUSHI_IH:       lambda hpa: zojirushi_pressure_cycle("white", hpa),  # Approx (no pressure pulses)
    CookingMethod.ZOJIRUSHI_PRESSURE: lambda hpa: zojirushi_pressure_cycle("white", hpa),
    CookingMethod.OPEN_POT:           open_pot_cycle,
    CookingMethod.PRESSURE_COOKER:    pressure_cooker_cycle,
    CookingMethod.STEAMER:            steamer_cycle,
}


# ─── Simulation Engine ────────────────────────────────────────────────────────

@dataclass
class SimulationResult:
    """Results from a cooking cycle simulation."""
    total_time_min: float
    final_moisture_pct: float
    gelatinization_pct: float     # 0-100%, how complete
    max_temp_reached: float
    max_pressure_atm: float
    phase_log: list                # Per-phase details
    zojirushi_soak_moisture: float  # Moisture after Zojirushi's built-in soak
    effective_presoak_saved_min: float  # How much pre-soak the cooker replaces

    @property
    def fully_gelatinized(self) -> bool:
        return self.gelatinization_pct >= 95.0


def simulate_cooking(variety_key: str,
                     method: CookingMethod = CookingMethod.ZOJIRUSHI_PRESSURE,
                     pre_soak_min: float = 0.0,
                     pre_soak_temp: float = 20.0,
                     crop_age_months: float = 6.0,
                     barometric_hpa: float = 1013.25,
                     zojirushi_mode: str = "white",
                     dt: float = 0.5) -> SimulationResult:
    """Simulate the full cooking cycle for a rice variety.

    Args:
        variety_key: Key into VARIETIES dict
        method: Cooking method
        pre_soak_min: Manual pre-soak time before cooking starts
        pre_soak_temp: Temperature of pre-soak water (°C)
        crop_age_months: Months since harvest
        barometric_hpa: Atmospheric pressure in hPa
        zojirushi_mode: 'white', 'brown', or 'sushi'
        dt: Time step in minutes

    Returns:
        SimulationResult with detailed cooking metrics
    """
    v = VARIETIES[variety_key]
    m0 = _interpolate_m0(v, crop_age_months)

    # ── Phase 0: Manual pre-soak ───────────────────────────────────────
    moisture = m0
    if pre_soak_min > 0:
        k1_t = peleg_k1_at_temp(v.k1, pre_soak_temp)
        k2_t = peleg_k2_at_temp(v.k2, pre_soak_temp)
        moisture = peleg_moisture(pre_soak_min, m0, k1_t, k2_t)

    moisture_after_presoak = moisture

    # ── Get cooking cycle ──────────────────────────────────────────────
    if method == CookingMethod.ZOJIRUSHI_MICOM:
        cycle = zojirushi_micom_cycle(zojirushi_mode, barometric_hpa)
    elif method == CookingMethod.ZOJIRUSHI_PRESSURE:
        cycle = zojirushi_pressure_cycle(zojirushi_mode, barometric_hpa)
    elif method in CYCLE_GENERATORS:
        cycle = CYCLE_GENERATORS[method](barometric_hpa)
    else:
        # Basic rice cooker — approximate as open pot
        cycle = open_pot_cycle(barometric_hpa)

    # ── Simulate each phase ────────────────────────────────────────────
    gel_progress = 0.0   # 0.0 to 1.0
    max_temp = pre_soak_temp
    max_pressure = 1.0
    total_time = pre_soak_min
    phase_log = []
    soak_moisture_end = moisture

    for phase in cycle:
        phase_start_moisture = moisture
        phase_start_gel = gel_progress
        steps = max(1, int(phase.duration_min / dt))
        actual_dt = phase.duration_min / steps

        for i in range(steps):
            # Interpolate temperature within phase
            frac = (i + 0.5) / steps
            temp = phase.temp_start + frac * (phase.temp_end - phase.temp_start)
            max_temp = max(max_temp, temp)
            max_pressure = max(max_pressure, phase.pressure_atm)

            # Water absorption (continues during cooking, slowing as moisture rises)
            k1_t = peleg_k1_at_temp(v.k1, temp)
            k2_t = peleg_k2_at_temp(v.k2, temp)
            # Incremental absorption based on current moisture deficit
            eq_moisture = moisture + 1.0 / k2_t if k2_t > 0 else 100.0
            if moisture < eq_moisture:
                rate = 1.0 / (k1_t + k2_t * total_time) if total_time > 0 else 1.0 / k1_t
                moisture += rate * actual_dt * 0.3  # Dampen during cooking (less free water)
                moisture = min(moisture, eq_moisture)

            # Gelatinization
            if gel_progress < 1.0:
                g_rate = gel_rate(temp, v.amylose_pct)
                gel_progress += g_rate * actual_dt * (1.0 - gel_progress)
                gel_progress = min(1.0, gel_progress)

            total_time += actual_dt

        if phase.is_soak:
            soak_moisture_end = moisture

        phase_log.append({
            "name": phase.name,
            "duration_min": phase.duration_min,
            "temp_range": f"{phase.temp_start:.0f}→{phase.temp_end:.0f}°C",
            "pressure_atm": phase.pressure_atm,
            "moisture_start": round(phase_start_moisture, 1),
            "moisture_end": round(moisture, 1),
            "gel_start": round(phase_start_gel * 100, 1),
            "gel_end": round(gel_progress * 100, 1),
        })

    # ── Calculate how much pre-soak the cooker replaces ────────────────
    # Compare moisture gained during cooker's soak phase vs manual soak
    cooker_soak_gain = soak_moisture_end - moisture_after_presoak
    # How many minutes of 20°C manual soak would give the same gain?
    effective_saved = 0.0
    if cooker_soak_gain > 0:
        # Invert Peleg at 20°C to find equivalent time
        test_m0 = moisture_after_presoak
        delta = cooker_soak_gain
        denom = 1.0 - v.k2 * delta
        if denom > 0:
            effective_saved = v.k1 * delta / denom

    return SimulationResult(
        total_time_min=round(total_time, 1),
        final_moisture_pct=round(moisture, 1),
        gelatinization_pct=round(gel_progress * 100, 1),
        max_temp_reached=round(max_temp, 1),
        max_pressure_atm=round(max_pressure, 2),
        phase_log=phase_log,
        zojirushi_soak_moisture=round(soak_moisture_end, 1),
        effective_presoak_saved_min=round(effective_saved, 0),
    )


# ─── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Rice Precise — Cooking Cycle Simulation")
    print("=" * 80)

    test_cases = [
        ("hitomebore", CookingMethod.ZOJIRUSHI_MICOM, 60, "white"),
        ("hitomebore", CookingMethod.OPEN_POT, 60, None),
        ("tsuyahime",  CookingMethod.ZOJIRUSHI_MICOM, 25, "white"),
        ("red_cargo",  CookingMethod.ZOJIRUSHI_MICOM, 240, "brown"),
        ("hitomebore", CookingMethod.ZOJIRUSHI_PRESSURE, 60, "white"),  # Comparison
        ("mochigome",  CookingMethod.STEAMER, 480, None),
    ]

    for vkey, method, presoak, mode in test_cases:
        v = VARIETIES[vkey]
        kwargs = {"zojirushi_mode": mode} if mode else {}
        result = simulate_cooking(vkey, method, pre_soak_min=presoak, **kwargs)

        print(f"\n{'─' * 80}")
        print(f"  {v.name} — {method.value}")
        print(f"  Pre-soak: {presoak} min at 20°C")
        print(f"{'─' * 80}")
        print(f"  Total time:       {result.total_time_min} min")
        print(f"  Final moisture:   {result.final_moisture_pct}%")
        print(f"  Gelatinization:   {result.gelatinization_pct}% "
              f"{'(complete)' if result.fully_gelatinized else '(INCOMPLETE)'}")
        print(f"  Max temp:         {result.max_temp_reached}°C")
        print(f"  Max pressure:     {result.max_pressure_atm} atm")
        print(f"  Cooker soak gain: saves ~{result.effective_presoak_saved_min} min of manual soak")
        print()
        print(f"  {'Phase':<22s} {'Dur':>5s} {'Temp':>14s} {'Press':>5s} "
              f"{'Moist%':>10s} {'Gel%':>10s}")
        for p in result.phase_log:
            print(f"  {p['name']:<22s} {p['duration_min']:>4.0f}m "
                  f"{p['temp_range']:>14s} {p['pressure_atm']:>4.1f}x "
                  f"{p['moisture_start']:>4.1f}→{p['moisture_end']:>4.1f} "
                  f"{p['gel_start']:>4.1f}→{p['gel_end']:>4.1f}")

    # ── Barometric pressure comparison ─────────────────────────────────
    print(f"\n{'=' * 80}")
    print("Barometric pressure effect (Hitomebore, Micom NS-LLH05, 60 min pre-soak):")
    print(f"{'Pressure':>10s} {'BP (max)':>9s} {'Gel%':>6s} {'Moisture':>9s}")
    print("-" * 40)
    for hpa in [980, 1000, 1013, 1030, 1040]:
        r = simulate_cooking("hitomebore", CookingMethod.ZOJIRUSHI_MICOM,
                             pre_soak_min=60, barometric_hpa=hpa)
        bp_atm = boiling_point(1.0, hpa)
        print(f"{hpa:>7d} hPa {bp_atm:>8.1f}°C "
              f"{r.gelatinization_pct:>5.1f}% {r.final_moisture_pct:>7.1f}%")
