# Rice Precise

A parametric model for calculating rice soaking time and water ratio, built on peer-reviewed food science.

Given a rice variety, crop age, cooking method, and soak duration, the model predicts how much water to use and how long to soak — calibrated against real cooking data and validated to within 1.5% accuracy on water amounts.

## Why This Exists

Every rice variety behaves differently. Tsuyahime needs 1.08 water ratio; Hitomebore needs 1.20; red cargo rice needs 1.70 dry but drops to 1.34 after a 12-hour soak. These numbers live in experienced cooks' heads, but they're hard to find, inconsistent across sources, and don't account for crop age or how long you soaked.

This project models the physics behind rice hydration to make those numbers predictable — even for varieties you've never cooked before.

## How It Works

### Two-Layer Architecture

**Layer 1: Parametric Baseline** — Peleg's equation (an empirically validated model from food science, R^2 >= 0.99) describes how rice absorbs water over time. The model derives the equation's parameters from two measurable grain properties:

- **Amylose content** (%) — drives total absorption capacity
- **Protein content** (%) — drives initial absorption rate
- **Grain type** (white/brown/pigmented) — bran barrier multiplier

This means you can get a reasonable prediction for any rice variety if you know its composition.

**Layer 2: Cultivar Tuning** — Each cultivar gets a `starch_accessibility` factor that captures starch quality differences not explained by composition alone. Calibrated against real cooking data. For example, Tsuyahime absorbs faster than its amylose/protein numbers predict (factor: 0.75), which is why it needs less water than Hitomebore despite nearly identical composition.

### What It Predicts

- **Water ratio** (water:rice by weight) adjusted for variety, crop age, and cooking method
- **Soak time** to reach target moisture content
- **Soak-adjusted water** — if you soaked for X minutes, how much to reduce the cooking water
- **Cooking simulation** (optional) — models the Zojirushi Micom/IH/Pressure cycle, open pot, pressure cooker, or steamer phase by phase, including gelatinization progress

## Quick Start

```bash
python3 rice_model.py
```

This prints the full variety table and recommendations for 240g rice on a Zojirushi Micom.

### Get a Recommendation

```python
from rice_model import get_recommendation

# Simple: what water ratio for 240g Tsuyahime?
rec = get_recommendation("tsuyahime", rice_grams=240)
print(f"{rec['water_grams']}g water, soak {rec['soak_minutes']} min")
# → 259g water, soak 45 min

# With crop age: new crop Hitomebore
rec = get_recommendation("hitomebore", crop_age_months=1, rice_grams=240)
print(f"{rec['water_grams']}g water (ratio {rec['water_ratio']})")
# → 268g water (ratio 1.12) — less water for shinmai

# With cooking simulation
rec = get_recommendation("hitomebore", rice_grams=240, simulate=True)
print(f"Gelatinization: {rec['sim_gelatinization_pct']}%")
```

### Soak-Adjusted Water

```python
from rice_model import soak_adjusted_water

# Red cargo rice soaked 12 hours — how much water now?
adj = soak_adjusted_water("red_cargo", rice_grams=202, soak_minutes=720)
print(f"Base: {adj['base_water_grams']}g → After 12h soak: {adj['adjusted_water_grams']}g")
# → Base: 343g → After 12h soak: 271g (ratio drops from 1.70 to 1.34)
```

### Add a New Variety

```python
from rice_model import add_custom_variety, GrainType

# If you know amylose and protein, the model derives everything else
add_custom_variety("sasanishiki", "Sasanishiki",
                   amylose_pct=20.0, protein_pct=6.5,
                   grain_type=GrainType.WHITE, origin="Miyagi")
rec = get_recommendation("sasanishiki", rice_grams=240)
```

## Supported Varieties

| Variety | Type | Amylose | Water Ratio | Best For |
|---------|------|---------|-------------|----------|
| Hitomebore | White japonica | 17% | 1.20 | Donburi, curry, onigiri |
| Tsuyahime | White japonica | 17% | 1.08 | Sushi, fish, chirashi |
| Niji no Kirameki | White japonica | 17.5% | 1.17 | Sushi, clean bowls |
| Koshihikari | White japonica | 17% | 1.20 | Sushi, plain rice |
| Yumepirika | White japonica | 14.5% | 1.10 | Plain rice, TKG, bento |
| Nanatsuboshi | White japonica | 18.5% | 1.20 | Everyday, clean flavors |
| Milky Queen | White japonica | 10% | 1.05 | TKG, butter rice |
| Ginga no Shizuku | White japonica | 18% | 1.18 | Everyday, fish |
| Akitakomachi | White japonica | 17% | 1.18 | Sushi, everyday |
| Calrose | White japonica | 22% | 1.25 | General purpose |
| Mochigome | Glutinous | 2% | 1.00 | Mochi, sekihan (steamed) |
| Genmai | Brown japonica | 17% | 1.50 | Health-conscious |
| Haigamai | Partially milled | 17% | 1.30 | Everyday |
| Multigrain | Mixed grains | 20% | 1.40 | Health-conscious |
| Red Cargo | Pigmented (Thai) | 25% | 1.70 | Stir fry, salads |
| Thai Black / Riceberry | Pigmented (Thai) | 25% | 1.75 | Salads, grain bowls |
| Korean Short-Grain | White japonica | 18% | 1.20 | Bibimbap, banchan |

## Cooking Methods

| Method | Max Temp | Notes |
|--------|----------|-------|
| Zojirushi Micom | 100C | Fuzzy logic, triple heater, built-in 15 min warm soak |
| Zojirushi IH | 100C | Induction heating, more precise, better soak phase |
| Zojirushi Pressure IH | 106C | Adds pressure pulsing for texture tuning |
| Open pot | ~100C | Stovetop, barometric pressure affects boiling point |
| Pressure cooker | ~115C | Instant Pot etc., pressure-assisted hydration |
| Steamer | 100C | Traditional for mochigome |

## Crop Age (Shinmai vs Komai)

The model adjusts for rice freshness:

- **Shinmai** (new crop, <3 months): Higher moisture content, needs 5-8% less water
- **Transitional** (3-6 months): Linear interpolation
- **Komai** (old crop, >6 months): Standard ratios apply

Japanese rice harvest is in autumn. Shinmai is available Oct-Dec. By spring, most rice in European stores is komai.

## Scientific Basis

### Peleg Model

```
M(t) = M0 + t / (k1 + k2 * t)
```

Where M(t) is moisture content at time t, M0 is initial moisture, k1 controls initial absorption rate, and k2 controls total absorption capacity. Validated across dozens of food science studies with R^2 >= 0.99.

### Parametric Derivation

From Bao et al. (2021): protein content negatively correlates with absorption rate (k1), and amylose content negatively correlates with expansion ratio (k2). The model uses these correlations to derive Peleg parameters from composition:

```
k1 = (0.65 * protein% + 0.8) * grain_type_multiplier * starch_accessibility
k2 = 0.0005 * amylose% + 0.012 + grain_type_offset
```

### Key References

- Bao et al. (2021) — "Kinetics of water absorption expansion of rice during soaking at different temperatures" — [PubMed](https://pubmed.ncbi.nlm.nih.gov/33387834/)
- Yu et al. (2017) — "Effect of soaking and high pressure treatment on water absorption of brown rice" — [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC5430198/)
- Allie et al. (2025) — "Effect of Temperature on Water Absorption of Three Varieties of Rice" — [SPG](https://www.sciencepublishinggroup.com/article/10.11648/j.wjfst.20250901.12)
- Li et al. (2021) — "Effects of vacuum soaking on japonica rice" — [Oxford Academic](https://academic.oup.com/bbb/article/85/3/634/6137732)
- Oxford Academic (2024) — "Detailed analysis of amylose content of rice grains" — [BBB](https://academic.oup.com/bbb/article/89/7/1006/8113978)

## Limitations and Honest Caveats

- **N=1 validation**: Water ratios are calibrated against one cook's data. The model needs more users to validate across different kitchens, equipment, and preferences.
- **Parametric regression is hand-fitted**: The amylose/protein to Peleg parameter mapping uses estimated coefficients, not a proper statistical fit against a large dataset.
- **The starch_accessibility tuning factor is a fudge factor**: It captures real cultivar differences but the values are tuned to match output, not independently measured.
- **Soak credit factor (0.75) is calibrated against one data point**: The red cargo 12h soak. Needs more validation across varieties and soak durations.
- **Cooking simulation is approximate**: The Zojirushi cycle is reconstructed from manuals and patents, not measured with instrumentation.
- **Barometric pressure effect is negligible in the Netherlands** (sea level, ~1.3C boiling point range). The model includes it for completeness and for users at altitude.

## Future: Web App with Crowdsourced Calibration

The planned next step is a web calculator where users can:

1. Input variety, rice weight, soak duration, and cooking method
2. Get a water ratio and soak time recommendation
3. After cooking, rate the result (texture, moisture level)
4. Feedback data improves the model over time

This would shift the model from N=1 to crowd-calibrated, replacing the hand-fitted parameters with statistically grounded values.

## Project Structure

```
rice_model.py     Core model: varieties, Peleg equation, recommendations
cooking_sim.py    Optional cooking cycle simulation (Zojirushi, open pot, etc.)
simulate.py       Visualization: absorption curves, heatmaps, comparisons
requirements.txt  numpy, matplotlib
```

## License

MIT
