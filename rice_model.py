"""
Rice Precise — Parametric Soaking & Water Ratio Model

Two-layer architecture:
  1. PARAMETRIC BASELINE — derive Peleg k1/k2 and water ratio from
     measurable grain properties (amylose %, protein %, grain type)
  2. CULTIVAR TUNING — per-cultivar adjustment factor calibrated against
     real cooking data (water ratios, soak times, texture outcomes)

Peleg equation:
    M(t) = M₀ + t / (k₁ + k₂·t)

Parametric derivation (from literature correlations):
    k1_base = f(protein%, grain_type)   — Bao et al. 2021: protein negatively
                                          correlates with absorption rate
    k2_base = f(amylose%, grain_type)   — Bao et al. 2021: amylose negatively
                                          correlates with expansion ratio

Sources:
    - Bao et al. (2021) — Japonica/Indica kinetics, composition correlations
    - Yu et al. (2017) — Brown rice WAR at 30-50°C
    - Allie et al. (2025) — Peleg k1/k2 for rice at 30-70°C
    - Oxford Academic (2024) — Amylose content by cultivar (Koshihikari 16.5-18.5%)
    - AGRIS/FAO — Milky Queen amylose 9-12%
    - Tsuyahime quality standard — protein ≤6.4%
    - User empirical data — water ratios and soak times for 10+ cultivars
"""

from dataclasses import dataclass, field
from enum import Enum


class GrainType(Enum):
    WHITE = "white"           # Fully milled, no bran
    PARTIALLY_MILLED = "partial"  # Germ retained (haigamai)
    BROWN = "brown"           # Bran intact
    PIGMENTED = "pigmented"   # Pigmented bran (red/black)


class CookingMethod(Enum):
    # ── Zojirushi models ───────────────────────────────────────────────
    ZOJIRUSHI_MICOM = "zojirushi_micom"        # Micom fuzzy logic, conventional
                                               # triple heater, no pressure.
                                               # e.g., NS-LLH05, NS-LHC05
    ZOJIRUSHI_IH = "zojirushi_ih"              # Induction heating, no pressure
    ZOJIRUSHI_PRESSURE = "zojirushi_pressure"  # IH + pressure (premium models)
    # ── Other methods ──────────────────────────────────────────────────
    RICE_COOKER_BASIC = "rice_cooker_basic"     # Simple on/off
    OPEN_POT = "open_pot"                      # Stovetop
    PRESSURE_COOKER = "pressure_cooker"        # Instant Pot etc.
    STEAMER = "steamer"                        # Steaming basket


# Cooking method adjustments: (soak_time_multiplier, water_ratio_multiplier)
#
# Micom: built-in soak (~15-20 min) but conventional heaters are less
#   precise than IH. Still reduces pre-soak need, but less aggressively.
#   No pressure → cooks at ~100°C (atmospheric). Slightly more evaporation
#   than IH due to less tight temperature control.
# IH: more precise heating, better soak phase, tighter water management.
# Pressure: adds 103-108°C capability, pressure-assisted hydration.
METHOD_ADJUSTMENTS = {
    CookingMethod.ZOJIRUSHI_MICOM:    (0.65, 1.0),   # Micom soak helps but less than IH
    CookingMethod.ZOJIRUSHI_IH:       (0.55, 1.0),   # Better soak, precise heating
    CookingMethod.ZOJIRUSHI_PRESSURE: (0.5, 1.0),    # Best soak + pressure hydration
    CookingMethod.RICE_COOKER_BASIC:  (1.0, 1.0),
    CookingMethod.OPEN_POT:           (1.0, 1.02),   # Slight evaporation compensation
    CookingMethod.PRESSURE_COOKER:    (0.7, 0.95),   # Pressure assists hydration
    CookingMethod.STEAMER:            (1.0, 0.90),   # Mochigome-style, less water
}


@dataclass
class RiceVariety:
    """Parameters for a specific rice variety."""
    name: str
    short_name: str
    grain_type: GrainType
    origin: str              # Prefecture or country of origin

    # ─── Measurable composition ────────────────────────────────────────
    amylose_pct: float       # % amylose content (0-30 range)
    protein_pct: float       # % protein content

    # ─── Parametric Peleg values (derived from composition) ────────────
    # These are computed by derive_peleg_params() and can be overridden
    k1: float = 0.0          # Rate constant (min/%) — lower = faster uptake
    k2: float = 0.0          # Capacity constant (1/%) — lower = more absorption

    # ─── Cultivar tuning factor ────────────────────────────────────────
    # Multiplier on k1 to account for starch quality differences not
    # captured by amylose/protein alone. Calibrated against empirical data.
    # <1.0 = absorbs faster than composition predicts (e.g., Tsuyahime)
    # >1.0 = absorbs slower than composition predicts
    starch_accessibility: float = 1.0

    # ─── Moisture ──────────────────────────────────────────────────────
    m0_new_crop: float = 14.0   # Initial moisture % for shinmai
    m0_old_crop: float = 12.0   # Initial moisture % for komai (6+ months)

    # ─── Target & recommendations ──────────────────────────────────────
    target_moisture: float = 30.0  # Target moisture for "fully soaked"

    # Water ratio by weight — calibrated from user's actual cooking data
    water_ratio_base: float = 1.20   # Standard (old crop)
    water_ratio_new_crop_adj: float = 0.93  # Multiplicative for new crop

    # Soak time range (minutes) — practical recommendation
    min_soak_min: int = 30
    max_soak_min: int = 120

    # Texture profile (1-5 scale, from user's ChatGPT conversation)
    stickiness: float = 3.0    # 1=separate grains, 5=very sticky
    softness: float = 3.0      # 1=firm/chewy, 5=very soft
    grain_definition: float = 3.0  # 1=mushy, 5=distinct grains

    # Best use cases
    best_for: list = field(default_factory=list)
    notes: str = ""


# ─── Parametric Derivation ─────────────────────────────────────────────────────
# Peleg parameters derived from composition + grain type.
#
# From Bao et al. 2021 and Allie et al. 2025:
#   - k1 ∝ protein_pct (higher protein → slower initial absorption)
#   - k2 ∝ 1/amylose_pct (lower amylose → higher capacity constant → less
#     total absorption, which seems counter-intuitive but aligns with the
#     finding that high amylopectin grains swell differently)
#   - Bran barrier multiplies k1 by 1.5-2.5x
#
# Base regression at 20°C (estimated from 30°C literature, +35% for temp):
#   k1_base = 0.65 * protein_pct + 0.8  (at 20°C, white milled rice)
#   k2_base = 0.0005 * amylose_pct + 0.012

GRAIN_TYPE_K1_MULTIPLIER = {
    GrainType.WHITE: 1.0,
    GrainType.PARTIALLY_MILLED: 1.3,
    GrainType.BROWN: 2.0,
    GrainType.PIGMENTED: 2.2,
}

GRAIN_TYPE_K2_OFFSET = {
    GrainType.WHITE: 0.0,
    GrainType.PARTIALLY_MILLED: -0.002,
    GrainType.BROWN: -0.004,
    GrainType.PIGMENTED: -0.006,
}


def derive_peleg_params(v: RiceVariety) -> tuple[float, float]:
    """Derive Peleg k1, k2 from composition and grain type."""
    k1_base = 0.65 * v.protein_pct + 0.8
    k1 = k1_base * GRAIN_TYPE_K1_MULTIPLIER[v.grain_type] * v.starch_accessibility

    k2_base = 0.0005 * v.amylose_pct + 0.012
    k2 = max(0.005, k2_base + GRAIN_TYPE_K2_OFFSET[v.grain_type])

    return round(k1, 2), round(k2, 4)


def _init_variety(v: RiceVariety) -> RiceVariety:
    """Initialize derived Peleg params if not manually set."""
    if v.k1 == 0.0 and v.k2 == 0.0:
        v.k1, v.k2 = derive_peleg_params(v)
    return v


# ─── Cultivar Library ──────────────────────────────────────────────────────────
# Composition from published literature. Water ratios and texture profiles
# calibrated from user's extensive cooking notes (ChatGPT conversation,
# Jan-May 2026).
#
# Amylose sources:
#   - Koshihikari: 16.5-18.5% (Oxford Academic, BBB 2024)
#   - Milky Queen: 9-12% (AGRIS/FAO; The Japanese Food Lab)
#   - Yumepirika: ~14-15% ("low amylose"; The Japanese Food Lab)
#   - Tsuyahime: ~17% (similar to Koshihikari; protein ≤6.4% quality standard)
#   - Hitomebore: ~17% (80% Koshihikari genome)
#   - Calrose: ~22% (MDPI Raman study 2021)

VARIETIES = {}


def _register(key: str, v: RiceVariety):
    VARIETIES[key] = _init_variety(v)


# ── Japanese White (Milled Japonica) ───────────────────────────────────────────

_register("hitomebore", RiceVariety(
    name="Hitomebore (ひとめぼれ)",
    short_name="Hitomebore",
    grain_type=GrainType.WHITE,
    origin="Iwate",
    amylose_pct=17.0,
    protein_pct=6.0,
    starch_accessibility=1.0,  # Reference cultivar
    m0_new_crop=14.0,
    m0_old_crop=12.0,
    target_moisture=30.0,
    water_ratio_base=1.20,     # User's standard: 1.2
    water_ratio_new_crop_adj=0.93,
    min_soak_min=45,
    max_soak_min=75,
    stickiness=3.5,
    softness=3.5,
    grain_definition=3.0,
    best_for=["donburi", "curry", "onigiri", "everyday"],
    notes="Balanced comfort rice. Very forgiving. Daily driver. "
          "80-90% of useful hydration in first 40-60 min.",
))

_register("tsuyahime", RiceVariety(
    name="Tsuyahime (つや姫)",
    short_name="Tsuyahime",
    grain_type=GrainType.WHITE,
    origin="Yamagata",
    amylose_pct=17.0,
    protein_pct=6.0,        # Quality standard: ≤6.4%
    starch_accessibility=0.75,  # Absorbs faster than composition predicts
    m0_new_crop=14.0,
    m0_old_crop=12.0,
    target_moisture=28.0,   # Lower target — softer outer starch
    water_ratio_base=1.08,  # User data: 1.05-1.08 (much less than Hitomebore)
    water_ratio_new_crop_adj=0.95,
    min_soak_min=20,
    max_soak_min=45,
    stickiness=3.0,
    softness=3.5,
    grain_definition=4.0,
    best_for=["sushi", "fish", "chirashi", "refined meals"],
    notes="Elegant restaurant rice. Name means 'shiny princess'. "
          "Higher water absorption + softer outer starch → needs less water. "
          "Very tunable in ±5g water steps.",
))

_register("niji_no_kirameki", RiceVariety(
    name="Niji no Kirameki (にじのきらめき)",
    short_name="Niji no Kirameki",
    grain_type=GrainType.WHITE,
    origin="Ibaraki",
    amylose_pct=17.5,
    protein_pct=6.0,
    starch_accessibility=1.05,  # Slightly slower than baseline
    m0_new_crop=14.0,
    m0_old_crop=12.0,
    target_moisture=29.0,
    water_ratio_base=1.17,  # User data: ~2-3% less than Hitomebore
    water_ratio_new_crop_adj=0.94,
    min_soak_min=30,
    max_soak_min=60,
    stickiness=2.8,
    softness=2.5,
    grain_definition=4.5,
    best_for=["sushi", "chirashi", "clean bowls", "grilled fish"],
    notes="Modern heat-tolerant cultivar (2018). Firm, structured, "
          "'restaurant sushi rice'. Slightly firmer than Hitomebore.",
))

_register("koshihikari", RiceVariety(
    name="Koshihikari (コシヒカリ)",
    short_name="Koshihikari",
    grain_type=GrainType.WHITE,
    origin="Niigata",
    amylose_pct=17.0,
    protein_pct=5.7,
    starch_accessibility=0.95,
    m0_new_crop=14.0,
    m0_old_crop=12.0,
    target_moisture=30.0,
    water_ratio_base=1.20,
    water_ratio_new_crop_adj=0.93,
    min_soak_min=30,
    max_soak_min=90,
    stickiness=4.0,
    softness=3.5,
    grain_definition=3.0,
    best_for=["sushi", "plain rice"],
    notes="Gold standard but fragile. Ages poorly in EU storage. "
          "Only buy if confirmed fresh. 80% genome ancestor of "
          "Hitomebore and Akitakomachi.",
))

_register("yumepirika", RiceVariety(
    name="Yumepirika (ゆめぴりか)",
    short_name="Yumepirika",
    grain_type=GrainType.WHITE,
    origin="Hokkaido",
    amylose_pct=14.5,       # Low amylose → very sticky
    protein_pct=5.5,        # Low protein
    starch_accessibility=0.85,
    m0_new_crop=14.0,
    m0_old_crop=12.0,
    target_moisture=31.0,   # Soft target
    water_ratio_base=1.10,  # Needs less water (gets too soft)
    water_ratio_new_crop_adj=0.92,
    min_soak_min=30,
    max_soak_min=75,
    stickiness=4.5,
    softness=4.5,
    grain_definition=2.0,
    best_for=["plain rice", "TKG (egg rice)", "bento", "indulgent meals"],
    notes="Luxury softness. Very high amylopectin. Narrow hydration "
          "window — easy to overcook. Best when rice is the star.",
))

_register("nanatsuboshi", RiceVariety(
    name="Nanatsuboshi (ななつぼし)",
    short_name="Nanatsuboshi",
    grain_type=GrainType.WHITE,
    origin="Hokkaido",
    amylose_pct=18.5,       # Slightly higher amylose
    protein_pct=6.0,
    starch_accessibility=1.1,
    m0_new_crop=13.5,
    m0_old_crop=12.0,
    target_moisture=29.0,
    water_ratio_base=1.20,
    water_ratio_new_crop_adj=0.94,
    min_soak_min=30,
    max_soak_min=75,
    stickiness=2.5,
    softness=2.5,
    grain_definition=4.0,
    best_for=["everyday", "banchan-style", "clean flavors"],
    notes="Clean, drier finish. Less sticky. Excellent aroma. "
          "More demanding for sushi — needs excellent technique.",
))

_register("milky_queen", RiceVariety(
    name="Milky Queen (ミルキークイーン)",
    short_name="Milky Queen",
    grain_type=GrainType.WHITE,
    origin="Various",
    amylose_pct=10.0,       # Very low: 9-12%
    protein_pct=6.5,
    starch_accessibility=0.80,
    m0_new_crop=14.0,
    m0_old_crop=12.5,
    target_moisture=31.0,
    water_ratio_base=1.05,  # User data: 5-15% less water than standard
    water_ratio_new_crop_adj=0.90,
    min_soak_min=30,
    max_soak_min=60,
    stickiness=5.0,
    softness=5.0,
    grain_definition=1.5,
    best_for=["TKG", "butter rice", "plain rice", "creamy bowls"],
    notes="Koshihikari mutation with near-glutinous stickiness. "
          "Not for sushi, onigiri, or curry. Wrong application for "
          "structured dishes — smears when seasoned.",
))

_register("ginga_no_shizuku", RiceVariety(
    name="Ginga no Shizuku (銀河のしずく)",
    short_name="Ginga no Shizuku",
    grain_type=GrainType.WHITE,
    origin="Iwate",
    amylose_pct=18.0,
    protein_pct=6.0,
    starch_accessibility=1.1,
    m0_new_crop=13.5,
    m0_old_crop=12.0,
    target_moisture=29.0,
    water_ratio_base=1.18,
    water_ratio_new_crop_adj=0.94,
    min_soak_min=30,
    max_soak_min=75,
    stickiness=2.5,
    softness=2.5,
    grain_definition=4.0,
    best_for=["everyday", "fish", "simple meals"],
    notes="Clean, slightly drier rice from Iwate. Less exciting than "
          "Tsuyahime or Hitomebore but dependable.",
))

_register("akitakomachi", RiceVariety(
    name="Akitakomachi (あきたこまち)",
    short_name="Akitakomachi",
    grain_type=GrainType.WHITE,
    origin="Akita",
    amylose_pct=17.0,
    protein_pct=6.0,
    starch_accessibility=1.0,
    m0_new_crop=14.0,
    m0_old_crop=12.0,
    target_moisture=30.0,
    water_ratio_base=1.18,
    water_ratio_new_crop_adj=0.93,
    min_soak_min=30,
    max_soak_min=75,
    stickiness=3.5,
    softness=3.0,
    grain_definition=3.5,
    best_for=["sushi", "everyday", "onigiri"],
    notes="80% Koshihikari genome. Similar to Hitomebore. "
          "Trusted premium cultivar.",
))

_register("calrose", RiceVariety(
    name="Calrose",
    short_name="Calrose",
    grain_type=GrainType.WHITE,
    origin="California",
    amylose_pct=22.0,
    protein_pct=6.0,
    starch_accessibility=1.05,
    m0_new_crop=13.5,
    m0_old_crop=12.0,
    target_moisture=30.0,
    water_ratio_base=1.25,
    water_ratio_new_crop_adj=0.94,
    min_soak_min=30,
    max_soak_min=120,
    stickiness=3.0,
    softness=3.0,
    grain_definition=3.0,
    best_for=["everyday", "general purpose"],
    notes="Medium-grain japonica. Higher amylose than Japanese cultivars. "
          "Different texture class from true short-grain.",
))

# ── Glutinous ──────────────────────────────────────────────────────────────────

_register("mochigome", RiceVariety(
    name="Mochigome (もち米)",
    short_name="Mochigome",
    grain_type=GrainType.WHITE,
    origin="Various",
    amylose_pct=2.0,
    protein_pct=8.8,
    starch_accessibility=0.70,  # Very fast absorption despite high protein
    m0_new_crop=14.0,
    m0_old_crop=12.5,
    target_moisture=33.0,
    water_ratio_base=1.00,
    water_ratio_new_crop_adj=0.92,
    min_soak_min=60,
    max_soak_min=480,
    stickiness=5.0,
    softness=4.0,
    grain_definition=1.0,
    best_for=["mochi", "sekihan", "steamed dishes"],
    notes="Glutinous. Near-zero amylose. Traditionally soaked overnight "
          "and steamed, not boiled.",
))

# ── Brown / Partially Milled ──────────────────────────────────────────────────

_register("genmai", RiceVariety(
    name="Genmai (玄米) — Brown Japonica",
    short_name="Genmai",
    grain_type=GrainType.BROWN,
    origin="Various",
    amylose_pct=17.0,
    protein_pct=7.5,
    starch_accessibility=1.0,
    m0_new_crop=14.5,
    m0_old_crop=12.5,
    target_moisture=28.0,
    water_ratio_base=1.50,
    water_ratio_new_crop_adj=0.95,
    min_soak_min=120,
    max_soak_min=480,
    stickiness=2.0,
    softness=2.0,
    grain_definition=4.0,
    best_for=["health-conscious", "nutty flavor"],
    notes="Bran barrier doubles absorption time. Benefits from 2-8h soak. "
          "Use Zojirushi Brown Rice mode.",
))

_register("haigamai", RiceVariety(
    name="Haigamai (胚芽米) — Partially Milled",
    short_name="Haigamai",
    grain_type=GrainType.PARTIALLY_MILLED,
    origin="Various",
    amylose_pct=17.0,
    protein_pct=6.5,
    starch_accessibility=1.0,
    m0_new_crop=13.8,
    m0_old_crop=12.2,
    target_moisture=29.0,
    water_ratio_base=1.30,
    water_ratio_new_crop_adj=0.94,
    min_soak_min=30,
    max_soak_min=180,
    stickiness=2.8,
    softness=2.8,
    grain_definition=3.5,
    best_for=["everyday", "health-conscious"],
    notes="Germ retained. Absorbs between white and brown rates.",
))

_register("multigrain", RiceVariety(
    name="Zakkokumai (雑穀米) — Multigrain",
    short_name="Multigrain",
    grain_type=GrainType.BROWN,
    origin="Various",
    amylose_pct=20.0,
    protein_pct=8.0,
    starch_accessibility=1.0,
    m0_new_crop=13.0,
    m0_old_crop=11.5,
    target_moisture=28.0,
    water_ratio_base=1.40,
    water_ratio_new_crop_adj=0.95,
    min_soak_min=60,
    max_soak_min=240,
    stickiness=2.0,
    softness=2.0,
    grain_definition=3.5,
    best_for=["health-conscious", "texture variety"],
    notes="Mixed grains. Absorption varies by blend composition.",
))

# ── Pigmented / Thai ───────────────────────────────────────────────────────────

_register("red_cargo", RiceVariety(
    name="Red Cargo Rice",
    short_name="Red Cargo",
    grain_type=GrainType.PIGMENTED,
    origin="Thailand",
    amylose_pct=25.0,
    protein_pct=7.0,
    starch_accessibility=1.0,
    m0_new_crop=13.5,
    m0_old_crop=11.5,
    target_moisture=27.0,
    water_ratio_base=1.70,  # User data: 1.6-1.8 dry, 1.3-1.4 after 12h soak
    water_ratio_new_crop_adj=0.95,
    min_soak_min=120,
    max_soak_min=720,       # Overnight
    stickiness=1.5,
    softness=1.5,
    grain_definition=5.0,
    best_for=["stir fry", "salads", "Thai/SE Asian dishes"],
    notes="Whole grain. Bran barrier + high amylose = very slow absorption. "
          "Min 2h soak, ideally 4-8h or overnight in fridge. "
          "After 12h soak: reduce water to 1.3-1.4. "
          "Use Zojirushi Brown Rice mode. Not comfort rice.",
))

_register("thai_black", RiceVariety(
    name="Thai Black Rice / Riceberry",
    short_name="Thai Black",
    grain_type=GrainType.PIGMENTED,
    origin="Thailand",
    amylose_pct=25.0,
    protein_pct=7.5,
    starch_accessibility=1.1,
    m0_new_crop=13.5,
    m0_old_crop=11.0,
    target_moisture=26.0,
    water_ratio_base=1.75,
    water_ratio_new_crop_adj=0.96,
    min_soak_min=120,
    max_soak_min=720,
    stickiness=1.5,
    softness=1.5,
    grain_definition=5.0,
    best_for=["salads", "grain bowls", "Thai dishes"],
    notes="Thickest bran (anthocyanin-rich). Slowest absorption of all. "
          "Benefits greatly from overnight soak in fridge.",
))

# ── Korean ─────────────────────────────────────────────────────────────────────

_register("korean", RiceVariety(
    name="Korean Short-Grain",
    short_name="Korean",
    grain_type=GrainType.WHITE,
    origin="Korea",
    amylose_pct=18.0,
    protein_pct=6.2,
    starch_accessibility=1.1,  # Slightly firmer/bouncier
    m0_new_crop=13.5,
    m0_old_crop=12.0,
    target_moisture=29.0,
    water_ratio_base=1.20,
    water_ratio_new_crop_adj=0.94,
    min_soak_min=30,
    max_soak_min=90,
    stickiness=3.0,
    softness=2.5,
    grain_definition=3.5,
    best_for=["bibimbap", "banchan", "Korean meals"],
    notes="Firmer, more elastic chew than Japanese cultivars. "
          "Optimized for daily Korean table rice.",
))


# ─── Core Model Functions ──────────────────────────────────────────────────────

def peleg_moisture(t_min: float, m0: float, k1: float, k2: float) -> float:
    """Peleg model: moisture content at time t (minutes)."""
    if t_min <= 0:
        return m0
    return m0 + t_min / (k1 + k2 * t_min)


def peleg_equilibrium(m0: float, k2: float) -> float:
    """Theoretical equilibrium moisture (t → ∞)."""
    return m0 + 1.0 / k2


def time_to_target(m0: float, k1: float, k2: float, target: float) -> float | None:
    """Time (minutes) to reach target moisture.

    Returns None if target exceeds equilibrium.
    """
    delta = target - m0
    if delta <= 0:
        return 0.0
    denominator = 1.0 - k2 * delta
    if denominator <= 0:
        return None
    return k1 * delta / denominator


def get_recommendation(variety_key: str,
                       crop_age_months: float = 6.0,
                       method: CookingMethod = CookingMethod.ZOJIRUSHI_MICOM,
                       rice_grams: float = 200.0,
                       simulate: bool = False,
                       barometric_hpa: float = 1013.25,
                       pre_soak_min: float | None = None,
                       zojirushi_mode: str = "white") -> dict:
    """Get complete cooking recommendation for a variety.

    Args:
        variety_key: Key into VARIETIES dict
        crop_age_months: Months since harvest (0 = just harvested)
        method: Cooking method
        rice_grams: Amount of dry rice in grams
        simulate: If True, run the optional cooking cycle simulation
                  (requires cooking_sim module). Adds gelatinization %,
                  phase breakdown, and pressure/temperature analysis.
        barometric_hpa: Atmospheric pressure (only used when simulate=True)
        pre_soak_min: Manual pre-soak time. If None, uses the model's
                      recommended soak time.
        zojirushi_mode: 'white', 'brown', or 'sushi' (only for Zojirushi methods)

    Returns dict with soak time, water amount in grams, ratios, and notes.
    When simulate=True, also includes cooking simulation results.
    """
    v = VARIETIES[variety_key]
    m0 = _interpolate_m0(v, crop_age_months)
    soak_mult, water_mult = METHOD_ADJUSTMENTS[method]

    # Soak time to target
    t_raw = time_to_target(m0, v.k1, v.k2, v.target_moisture)
    t_adjusted = round(t_raw * soak_mult) if t_raw is not None else None

    # Clamp to practical range
    if t_adjusted is not None:
        t_adjusted = max(v.min_soak_min, min(v.max_soak_min, t_adjusted))

    # Water ratio adjusted for crop age and cooking method
    if crop_age_months < 3:
        ratio = v.water_ratio_base * v.water_ratio_new_crop_adj
        crop_label = "shinmai (new crop)"
    elif crop_age_months < 6:
        blend = (crop_age_months - 3) / 3.0
        adj = v.water_ratio_new_crop_adj + blend * (1.0 - v.water_ratio_new_crop_adj)
        ratio = v.water_ratio_base * adj
        crop_label = "transitional"
    else:
        ratio = v.water_ratio_base
        crop_label = "komai (old crop)"

    ratio *= water_mult
    water_grams = round(rice_grams * ratio)

    result = {
        "variety": v.name,
        "short_name": v.short_name,
        "origin": v.origin,
        "grain_type": v.grain_type.value,
        "crop_label": crop_label,
        "method": method.value,
        "rice_grams": rice_grams,
        "water_grams": water_grams,
        "water_ratio": round(ratio, 2),
        "soak_minutes": t_adjusted,
        "m0_pct": round(m0, 1),
        "target_moisture_pct": v.target_moisture,
        "k1": v.k1,
        "k2": v.k2,
        "amylose_pct": v.amylose_pct,
        "protein_pct": v.protein_pct,
        "stickiness": v.stickiness,
        "softness": v.softness,
        "grain_definition": v.grain_definition,
        "best_for": v.best_for,
        "notes": v.notes,
    }

    # ── Optional cooking simulation ────────────────────────────────────
    if simulate:
        try:
            from cooking_sim import simulate_cooking
            actual_presoak = pre_soak_min if pre_soak_min is not None else (t_adjusted or 0)
            sim = simulate_cooking(
                variety_key, method,
                pre_soak_min=actual_presoak,
                crop_age_months=crop_age_months,
                barometric_hpa=barometric_hpa,
                zojirushi_mode=zojirushi_mode,
            )
            result["sim_total_time_min"] = sim.total_time_min
            result["sim_final_moisture_pct"] = sim.final_moisture_pct
            result["sim_gelatinization_pct"] = sim.gelatinization_pct
            result["sim_fully_gelatinized"] = sim.fully_gelatinized
            result["sim_max_temp"] = sim.max_temp_reached
            result["sim_max_pressure"] = sim.max_pressure_atm
            result["sim_presoak_saved_min"] = sim.effective_presoak_saved_min
            result["sim_phase_log"] = sim.phase_log
        except ImportError:
            result["sim_error"] = "cooking_sim module not available"

    return result


def _interpolate_m0(v: RiceVariety, crop_age_months: float) -> float:
    """Interpolate initial moisture between new and old crop."""
    if crop_age_months <= 0:
        return v.m0_new_crop
    if crop_age_months >= 6:
        return v.m0_old_crop
    frac = crop_age_months / 6.0
    return v.m0_new_crop + frac * (v.m0_old_crop - v.m0_new_crop)


def soak_adjusted_water(variety_key: str,
                        rice_grams: float,
                        soak_minutes: float,
                        soak_temp: float = 20.0,
                        crop_age_months: float = 6.0) -> dict:
    """Calculate adjusted water ratio after a known soak duration.

    When you pre-soak rice, it absorbs water. The cooking water should
    account for this — long soaks need less cooking water to avoid
    ending up too wet.

    This is particularly useful for:
      - Red cargo / brown rice soaked overnight (ratio drops significantly)
      - Deciding if you need to adjust after an unplanned long soak

    Args:
        variety_key: Key into VARIETIES dict
        rice_grams: Dry rice weight before soaking (grams)
        soak_minutes: How long you soaked
        soak_temp: Water temperature during soak (°C)
        crop_age_months: Months since harvest

    Returns dict with original and adjusted water ratios and grams.
    """
    v = VARIETIES[variety_key]
    m0 = _interpolate_m0(v, crop_age_months)

    # Moisture before and after soak
    from cooking_sim import peleg_k1_at_temp, peleg_k2_at_temp
    k1_t = peleg_k1_at_temp(v.k1, soak_temp)
    k2_t = peleg_k2_at_temp(v.k2, soak_temp)
    m_after = peleg_moisture(soak_minutes, m0, k1_t, k2_t)

    # How much water was absorbed (as fraction of dry rice weight)
    # moisture% is wet basis: m = water / (water + dry_matter)
    # Convert to water absorbed in grams per gram of original rice
    dry_matter_frac_before = 1.0 - m0 / 100.0
    dry_matter_frac_after = 1.0 - m_after / 100.0

    # Weight of soaked rice per gram of dry rice
    soaked_weight_ratio = dry_matter_frac_before / dry_matter_frac_after
    water_absorbed_ratio = soaked_weight_ratio - 1.0  # grams water per gram dry rice

    # Reduce cooking water by what's already inside the grain.
    # Not 1:1 — absorbed soak water still contributes to evaporation
    # during cooking, and swollen grains lose more steam. Calibrated
    # against user data: 202g red cargo, 12h soak → ratio 1.34
    # (absorbed 0.48 ratio, effective credit 0.36 → factor ≈ 0.75)
    SOAK_CREDIT_FACTOR = 0.75
    base_ratio = v.water_ratio_base
    adjusted_ratio = max(0.8, base_ratio - water_absorbed_ratio * SOAK_CREDIT_FACTOR)

    base_water = round(rice_grams * base_ratio)
    adjusted_water = round(rice_grams * adjusted_ratio)
    reduction_pct = round((1.0 - adjusted_ratio / base_ratio) * 100, 1)

    return {
        "variety": v.name,
        "short_name": v.short_name,
        "rice_grams": rice_grams,
        "soak_minutes": soak_minutes,
        "soak_temp": soak_temp,
        "moisture_before_pct": round(m0, 1),
        "moisture_after_pct": round(m_after, 1),
        "moisture_gained_pct": round(m_after - m0, 1),
        "water_absorbed_g": round(rice_grams * water_absorbed_ratio, 1),
        "base_water_ratio": base_ratio,
        "base_water_grams": base_water,
        "adjusted_water_ratio": round(adjusted_ratio, 2),
        "adjusted_water_grams": adjusted_water,
        "reduction_pct": reduction_pct,
    }


def add_custom_variety(key: str, name: str, amylose_pct: float,
                       protein_pct: float, grain_type: GrainType,
                       origin: str = "Unknown",
                       water_ratio: float | None = None,
                       **kwargs) -> RiceVariety:
    """Add a new variety using parametric derivation.

    Provide amylose and protein content; Peleg params are derived
    automatically. Optionally override water_ratio if known from
    experience.
    """
    v = RiceVariety(
        name=name,
        short_name=name.split("(")[0].strip(),
        grain_type=grain_type,
        origin=origin,
        amylose_pct=amylose_pct,
        protein_pct=protein_pct,
        **kwargs,
    )
    v = _init_variety(v)

    if water_ratio is not None:
        v.water_ratio_base = water_ratio

    VARIETIES[key] = v
    return v


# ─── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Rice Precise — Parametric Model")
    print("=" * 90)
    print()

    # Show parametric derivation
    print("Parametric Peleg derivation (amylose + protein → k1, k2):")
    print(f"{'Cultivar':<22s} {'Amylose%':>8s} {'Protein%':>8s} {'Type':<10s} "
          f"{'k1':>6s} {'k2':>7s} {'Sticky':>6s} {'Soft':>5s} {'Def':>5s}")
    print("-" * 90)

    for key, v in VARIETIES.items():
        print(f"{v.short_name:<22s} {v.amylose_pct:>7.1f}% {v.protein_pct:>7.1f}% "
              f"{v.grain_type.value:<10s} {v.k1:>6.2f} {v.k2:>7.4f} "
              f"{v.stickiness:>5.1f} {v.softness:>5.1f} {v.grain_definition:>5.1f}")

    # Practical recommendations for 240g rice on Zojirushi Micom
    print("\n")
    print("Practical recommendations (240g rice, Zojirushi Micom NS-LLH05, old crop):")
    print(f"{'Cultivar':<22s} {'Water (g)':>9s} {'Ratio':>6s} {'Soak':>8s} {'Best for'}")
    print("-" * 90)

    for key in VARIETIES:
        rec = get_recommendation(key, crop_age_months=6,
                                 method=CookingMethod.ZOJIRUSHI_MICOM,
                                 rice_grams=240)
        soak_str = f"{rec['soak_minutes']} min" if rec['soak_minutes'] else "n/a"
        uses = ", ".join(rec["best_for"][:3])
        print(f"{rec['short_name']:<22s} {rec['water_grams']:>7d} g {rec['water_ratio']:>5.02f} "
              f"{soak_str:>8s}   {uses}")
