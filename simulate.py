"""
Rice Precise — Simulation & Visualization

Generates absorption curves and comparison charts for all rice varieties
across crop ages, showing how variety and crop age dominate the soaking
and water ratio decisions.
"""

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from rice_model import (
    VARIETIES, peleg_moisture, peleg_equilibrium,
    time_to_target, _interpolate_m0, get_recommendation,
    CookingMethod,
)


# ─── Color Palette ─────────────────────────────────────────────────────────────
# One color per variety — auto-assign from a perceptually distinct palette

_PALETTE = [
    "#2E86AB", "#A23B72", "#F18F01", "#C73E1D", "#3B1F2B",
    "#44BBA4", "#E94F37", "#393E41", "#8B6914", "#6B8E23",
    "#5BA5C9", "#C4A35A", "#2C2C54", "#D4A373", "#588B8B",
    "#FF6B6B", "#4ECDC4",
]


def _get_color(key: str, idx: int) -> str:
    return _PALETTE[idx % len(_PALETTE)]


# ─── Subset of varieties for readable charts ──────────────────────────────────

# Core varieties to show on absorption curves (too many = unreadable)
CHART_VARIETIES = [
    "hitomebore", "tsuyahime", "niji_no_kirameki", "yumepirika",
    "milky_queen", "genmai", "red_cargo", "thai_black",
]


def plot_absorption_curves(crop_age_months: float = 6.0, max_minutes: int = 480,
                           variety_keys: list | None = None,
                           save_path: str | None = None):
    """Plot moisture absorption curves for selected varieties."""
    keys = variety_keys or CHART_VARIETIES
    fig, ax = plt.subplots(figsize=(12, 7))
    t = np.linspace(0, max_minutes, 500)

    for idx, key in enumerate(keys):
        v = VARIETIES[key]
        m0 = _interpolate_m0(v, crop_age_months)
        moisture = np.array([peleg_moisture(ti, m0, v.k1, v.k2) for ti in t])
        color = _get_color(key, idx)

        ax.plot(t, moisture, color=color, linewidth=2.2, label=v.short_name)

        # Mark target moisture crossing
        t_target = time_to_target(m0, v.k1, v.k2, v.target_moisture)
        if t_target is not None and t_target <= max_minutes:
            ax.plot(t_target, v.target_moisture, 'o', color=color,
                    markersize=7, zorder=5)

    crop_label = "new crop" if crop_age_months < 3 else (
        "old crop" if crop_age_months >= 6 else "transitional")

    ax.set_xlabel("Soaking Time (minutes)", fontsize=12)
    ax.set_ylabel("Moisture Content (% wet basis)", fontsize=12)
    ax.set_title(
        f"Rice Water Absorption Curves — Peleg Model at 20C\n"
        f"Crop age: {crop_age_months:.0f} months ({crop_label})",
        fontsize=13, fontweight='bold')
    ax.legend(loc='lower right', fontsize=10, framealpha=0.9)
    ax.set_xlim(0, max_minutes)
    ax.set_ylim(10, 55)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_locator(ticker.MultipleLocator(60))

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Saved: {save_path}")
    plt.close()


def plot_crop_age_comparison(variety_key: str = "hitomebore",
                             max_minutes: int = 180,
                             save_path: str | None = None):
    """Show how crop age shifts the absorption curve for one variety."""
    v = VARIETIES[variety_key]
    fig, ax = plt.subplots(figsize=(10, 6))
    t = np.linspace(0, max_minutes, 500)

    ages = [0, 1, 3, 6, 12]
    cmap = plt.cm.YlOrBr
    colors = [cmap(0.2 + 0.15 * i) for i in range(len(ages))]

    for age, color in zip(ages, colors):
        m0 = _interpolate_m0(v, age)
        moisture = np.array([peleg_moisture(ti, m0, v.k1, v.k2) for ti in t])
        label = f"{age} months" if age > 0 else "Just harvested"
        ax.plot(t, moisture, color=color, linewidth=2.2, label=label)

        t_target = time_to_target(m0, v.k1, v.k2, v.target_moisture)
        if t_target is not None and t_target <= max_minutes:
            ax.plot(t_target, v.target_moisture, 'o', color=color,
                    markersize=7, zorder=5)

    ax.axhline(y=v.target_moisture, color='gray', linewidth=1, linestyle='--',
               alpha=0.6, label=f"Target ({v.target_moisture}%)")

    ax.set_xlabel("Soaking Time (minutes)", fontsize=12)
    ax.set_ylabel("Moisture Content (% wet basis)", fontsize=12)
    ax.set_title(
        f"Crop Age Effect on Soaking — {v.short_name}\n"
        f"Peleg model at 20C",
        fontsize=13, fontweight='bold')
    ax.legend(loc='lower right', fontsize=10, framealpha=0.9)
    ax.set_xlim(0, max_minutes)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_locator(ticker.MultipleLocator(30))

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Saved: {save_path}")
    plt.close()


def plot_water_ratio_heatmap(save_path: str | None = None):
    """Heatmap of recommended water ratios: variety x crop age."""
    ages = [0, 1, 2, 3, 4, 5, 6, 9, 12]
    variety_keys = list(VARIETIES.keys())
    variety_names = [VARIETIES[k].short_name for k in variety_keys]

    data = np.zeros((len(variety_keys), len(ages)))
    for i, key in enumerate(variety_keys):
        for j, age in enumerate(ages):
            rec = get_recommendation(key, crop_age_months=age, rice_grams=200)
            data[i, j] = rec["water_ratio"]

    fig, ax = plt.subplots(figsize=(12, 7))
    im = ax.imshow(data, cmap='YlOrRd', aspect='auto', vmin=0.9, vmax=1.9)

    ax.set_xticks(range(len(ages)))
    ax.set_xticklabels([f"{a}mo" for a in ages])
    ax.set_yticks(range(len(variety_keys)))
    ax.set_yticklabels(variety_names, fontsize=9)

    for i in range(len(variety_keys)):
        for j in range(len(ages)):
            text_color = "white" if data[i, j] > 1.5 else "black"
            ax.text(j, i, f"{data[i, j]:.2f}", ha="center", va="center",
                    color=text_color, fontsize=8, fontweight='bold')

    ax.set_xlabel("Crop Age (months since harvest)", fontsize=12)
    ax.set_title(
        "Recommended Water Ratio (water:rice by weight)\n"
        "Variety x Crop Age — Zojirushi Micom",
        fontsize=13, fontweight='bold')

    cbar = plt.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label("Water : Rice ratio", fontsize=10)

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Saved: {save_path}")
    plt.close()


def plot_soak_time_comparison(save_path: str | None = None):
    """Bar chart comparing recommended soak times across varieties and crop ages."""
    variety_keys = list(VARIETIES.keys())
    variety_names = [VARIETIES[k].short_name for k in variety_keys]

    fig, ax = plt.subplots(figsize=(14, 6))
    x = np.arange(len(variety_keys))
    width = 0.35

    soak_new = []
    soak_old = []
    for key in variety_keys:
        rec_new = get_recommendation(key, crop_age_months=1, rice_grams=200)
        rec_old = get_recommendation(key, crop_age_months=9, rice_grams=200)
        soak_new.append(rec_new["soak_minutes"] or 480)
        soak_old.append(rec_old["soak_minutes"] or 480)

    bars1 = ax.bar(x - width/2, soak_new, width, label='New crop (1 month)',
                   color='#2E86AB', alpha=0.85)
    bars2 = ax.bar(x + width/2, soak_old, width, label='Old crop (9 months)',
                   color='#C0392B', alpha=0.85)

    for bar in bars1:
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., h + 3,
                f'{h:.0f}', ha='center', va='bottom', fontsize=7)
    for bar in bars2:
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., h + 3,
                f'{h:.0f}', ha='center', va='bottom', fontsize=7)

    ax.set_xlabel("Rice Variety", fontsize=12)
    ax.set_ylabel("Recommended Soak Time (minutes)", fontsize=12)
    ax.set_title(
        "Soak Time to Target Moisture — New vs Old Crop\n"
        "Peleg model at 20C, Zojirushi Micom",
        fontsize=13, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(variety_names, rotation=35, ha='right', fontsize=9)
    ax.legend(fontsize=10)
    ax.grid(True, axis='y', alpha=0.3)

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Saved: {save_path}")
    plt.close()


if __name__ == "__main__":
    plot_absorption_curves(crop_age_months=6, save_path="fig_absorption_curves.png")
    plot_absorption_curves(crop_age_months=1, save_path="fig_absorption_curves_new.png")
    plot_crop_age_comparison("hitomebore", save_path="fig_crop_age_hitomebore.png")
    plot_crop_age_comparison("red_cargo", max_minutes=480,
                            save_path="fig_crop_age_red_cargo.png")
    plot_water_ratio_heatmap(save_path="fig_water_ratio_heatmap.png")
    plot_soak_time_comparison(save_path="fig_soak_time_comparison.png")
    print("All charts generated.")
