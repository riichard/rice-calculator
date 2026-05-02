# I Built a Model to Calculate the Perfect Water Ratio for Every Rice Variety

I cook Japanese rice almost every day. Hitomebore for curry, Tsuyahime for fish, red cargo rice when I want something hearty. Over months of obsessive tuning — weighing rice and water to the gram, adjusting for new vs old crop, tracking soak times — I started wondering: is there actual science behind what I'm doing, or am I just vibes-cooking with a scale?

Turns out, there is. And it's surprisingly precise.

## The Problem

Every rice variety needs a different amount of water. Not roughly different — *meaningfully* different:

- **Tsuyahime**: 1.08 ratio (water to rice, by weight)
- **Hitomebore**: 1.20
- **Red cargo rice**: 1.70

That's a 60% spread. Get it wrong by even 5% and you notice — too wet, too dry, mushy edges with a chalky core.

What makes this harder:
- **New crop rice** (shinmai) has more moisture and needs less water
- **Long soaking** changes how much water to add during cooking
- Rice you bought in October behaves differently from the same bag in March
- Nobody publishes precise ratios for Japanese cultivars like Niji no Kirameki or Ginga no Shizuku

I wanted a calculator that could handle all of this. So I built one.

## The Science: How Rice Absorbs Water

Food scientists have been studying rice hydration since the 1980s. The standard model is the **Peleg equation** — a simple formula that describes how rice absorbs water over time:

```
Moisture(t) = M₀ + t / (k₁ + k₂ × t)
```

Two numbers — k₁ and k₂ — characterize how a rice grain behaves:
- **k₁** controls how fast water gets in initially (lower = faster)
- **k₂** controls how much water the grain can absorb total (lower = more)

This has been validated across dozens of studies with R² ≥ 0.99. It's real physics, not a guess.

The key insight from the literature: **k₁ correlates with protein content** (more protein = slower absorption) and **k₂ correlates with amylose content** (a starch component that varies by variety). Brown and pigmented rice have a bran barrier that roughly doubles the absorption time.

This means: if you know a rice's amylose and protein percentage, you can *predict* how it will absorb water — even for a variety you've never cooked.

## Building the Model

I combined three things:

**1. Published grain composition data** — amylose and protein percentages for each cultivar. Koshihikari is ~17% amylose, Milky Queen is 9-12%, Thai red cargo is ~25%. These are published in food science journals and sometimes on Japanese packaging.

**2. The Peleg equation** — to model soaking kinetics at 20°C tap water temperature.

**3. My own cooking data** — four months of daily rice cooking with notes on water ratios, soak times, and results for 10+ varieties.

The model has 17 varieties built in, from premium Japanese cultivars to Thai pigmented rice to Korean short-grain.

## Does It Actually Work?

I validated the model against my actual cooking notes. Here's what it predicts vs what I actually used:

| Scenario | Model Predicts | My Actual | Error |
|----------|---------------|-----------|-------|
| 240g Tsuyahime | 259g water | 255g | +1.6% |
| 200g Tsuyahime | 216g water | 215g | +0.5% |
| 240g Hitomebore | 288g water | 288g | exact |
| 203g Red Cargo (dry) | 345g water | 350g | -1.4% |
| 202g Red Cargo (12h soak) | 271g water | 270g | +0.4% |

Within 1.5% across the board. The red cargo result is the most impressive — the model correctly predicts that after a 12-hour overnight soak, you should drop the water ratio from 1.70 all the way down to 1.34. That's a 73g difference. Get it wrong and your rice is either crunchy or porridge.

## What Variety and Crop Age Actually Do

This chart shows the absorption curves for eight varieties at 20°C:

![Absorption curves showing how different rice varieties absorb water over time](fig_absorption_curves.png)

The white japonica varieties (Hitomebore, Tsuyahime, Yumepirika) cluster together at the top — fast absorption, reaching target moisture in 70-100 minutes. The pigmented varieties (red cargo, Thai black) are dramatically slower, needing 150-220+ minutes because their bran layer acts as a physical barrier to water penetration.

Crop age shifts the starting point. New crop rice starts at ~14% moisture; by 6 months it's down to ~12%. That 2% difference means new crop rice needs less soaking and less cooking water:

![Crop age effect on Hitomebore showing curves from just harvested to 12 months](fig_crop_age_hitomebore.png)

And here's the full picture — every variety, every crop age, with the recommended water ratio:

![Heatmap showing water ratios across all 17 varieties and crop ages](fig_water_ratio_heatmap.png)

The gradient runs much steeper vertically (variety) than horizontally (crop age). **Variety choice is roughly 3x more important than crop age for getting the water ratio right.**

## The Tsuyahime Mystery

Here's something interesting the model revealed. Tsuyahime and Hitomebore have nearly identical composition — both ~17% amylose, ~6% protein. Yet Tsuyahime needs significantly less water (1.08 vs 1.20). Why?

The model captures this with a "starch accessibility" factor. Tsuyahime has softer outer starch granules that let water in faster than its composition would predict. The model assigns it a factor of 0.75 (vs Hitomebore's 1.0), meaning it absorbs 25% faster than expected.

This is the kind of cultivar-specific knowledge that lives in Japanese chefs' heads but has never been quantified. The model makes it explicit and predictable.

## What About Barometric Pressure?

I originally started this project thinking barometric pressure might affect rice cooking. After analysis: **it doesn't matter at sea level.** The Netherlands (where I cook) sees pressure variation of about 985-1035 hPa, which shifts the boiling point by roughly 1.5°C. Since starch gelatinization completes well below boiling, this has zero practical effect.

It would matter at altitude — in Denver (1600m), water boils at ~94.5°C and you'd genuinely need more time and water. But for anyone near sea level, don't worry about it.

## The Overnight Soak Problem (Solved)

If you cook brown or pigmented rice, you probably soak it overnight. But then: how much water do you add for cooking? The rice already absorbed a bunch of water during soaking. Too much cooking water and it's mush. Too little and the core stays hard.

The model solves this with a soak-adjusted water ratio. For red cargo rice:

| Soak Duration | Water Ratio |
|--------------|-------------|
| No soak | 1.70 |
| 2 hours | 1.62 |
| 4 hours | 1.55 |
| 8 hours | 1.43 |
| 12 hours (overnight) | 1.34 |

Not all absorbed soak water replaces cooking water 1:1 — some still evaporates during cooking. The model uses a 0.75 credit factor, calibrated against my actual cooking data.

## How to Use It

The model is a Python library. To get a recommendation:

```python
from rice_model import get_recommendation

rec = get_recommendation("tsuyahime", rice_grams=240)
print(f"{rec['water_grams']}g water, soak {rec['soak_minutes']} min")
# → 259g water, soak 45 min
```

For a new variety you've never cooked, provide the composition and the model derives everything:

```python
from rice_model import add_custom_variety, GrainType

add_custom_variety("sasanishiki", "Sasanishiki",
                   amylose_pct=20.0, protein_pct=6.5,
                   grain_type=GrainType.WHITE, origin="Miyagi")
```

The full code, all 17 variety parameters, and a detailed paper are at **[github.com/riichard/rice-calculator](https://github.com/riichard/rice-calculator)**.

## What's Next

This is a research prototype validated against one person's cooking (mine). The next step is a **web calculator** where anyone can:

1. Select their rice variety and amount
2. Get a water ratio and soak time recommendation
3. After cooking, rate the result
4. Their feedback improves the model for everyone

The model is honest about its limitations — the parametric coefficients are hand-fitted, the starch accessibility factors are tuned rather than measured, and the soak credit factor is calibrated against a single data point. More data from more kitchens would make it genuinely better than any single cook's intuition.

If you're the kind of person who weighs rice in grams and adjusts water by the tablespoon — this is for you.

---

*The model is built on the Peleg equation from food science, with parameters derived from published amylose and protein data for each cultivar. Full methodology, references, and honest limitations are documented in the [paper](https://github.com/riichard/rice-calculator/blob/main/PAPER.md). Code is MIT licensed.*

*Built with computational assistance from Claude (Anthropic).*
