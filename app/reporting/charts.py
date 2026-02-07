# ============================================================================
# FORD CAD - Matplotlib Chart Generator
# ============================================================================
# Generates chart images as base64-encoded PNG strings for embedding in
# HTML/PDF reports.  All functions return a base64 string ready for use in
#   <img src="data:image/png;base64,{result}">
# ============================================================================

import base64
import io
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("reporting.charts")

try:
    import matplotlib
    matplotlib.use("Agg")  # non-interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
    import numpy as np
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    logger.warning("matplotlib not installed - chart generation disabled")

# ---------------------------------------------------------------------------
# Ford brand colours
# ---------------------------------------------------------------------------

FORD_BLUE = "#003478"
FORD_BLUE_LIGHT = "#1e5cb3"
FORD_BLUE_LIGHTER = "#3b82f6"
FIRE_RED = "#dc2626"
FIRE_RED_LIGHT = "#ef4444"
GREEN = "#16a34a"
GREEN_LIGHT = "#22c55e"
AMBER = "#ca8a04"
AMBER_LIGHT = "#eab308"
GRAY_500 = "#6b7280"
GRAY_200 = "#e5e7eb"
GRAY_100 = "#f3f4f6"
WHITE = "#ffffff"

PALETTE = [
    FORD_BLUE, FIRE_RED, GREEN, AMBER, FORD_BLUE_LIGHT,
    "#7c3aed", "#0891b2", "#c026d3", "#ea580c", "#4f46e5",
]

DONUT_PALETTE = [
    FORD_BLUE, FIRE_RED, GREEN, AMBER, FORD_BLUE_LIGHTER,
    "#7c3aed", "#0891b2", "#c026d3", "#ea580c", "#4f46e5",
    "#059669", "#d97706", "#9333ea", "#e11d48",
]

# Default figure size (inches) and DPI
DEFAULT_SIZE = (7, 4.5)
DEFAULT_DPI = 150  # balance quality vs file size for embedded images


def _setup_style():
    """Apply a clean, professional style to the current plot."""
    try:
        plt.style.use("seaborn-v0_8-whitegrid")
    except Exception:
        try:
            plt.style.use("seaborn-whitegrid")
        except Exception:
            pass  # fall back to default


def _fig_to_base64(fig) -> str:
    """Convert a matplotlib Figure to a base64-encoded PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DEFAULT_DPI, bbox_inches="tight",
                facecolor=WHITE, edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def _no_matplotlib() -> str:
    """Return a placeholder when matplotlib is unavailable."""
    return ""


# ============================================================================
# Chart functions
# ============================================================================

def line_chart(
    labels: List[str],
    datasets: List[Dict[str, Any]],
    title: str = "",
    size: Tuple[int, int] = DEFAULT_SIZE,
) -> str:
    """Multi-series line chart.

    Parameters
    ----------
    labels : list[str]
        X-axis labels (e.g. dates).
    datasets : list[dict]
        Each dict has keys: "label" (str), "data" (list[float]),
        and optionally "color" (str).
    title : str
        Chart title.

    Returns base64-encoded PNG.
    """
    if not HAS_MATPLOTLIB:
        return _no_matplotlib()

    _setup_style()
    fig, ax = plt.subplots(figsize=size)

    x = range(len(labels))
    for i, ds in enumerate(datasets):
        color = ds.get("color", PALETTE[i % len(PALETTE)])
        ax.plot(x, ds["data"], marker="o", markersize=4, linewidth=2,
                color=color, label=ds.get("label", f"Series {i+1}"))

    ax.set_xticks(list(x))
    # Rotate labels if many
    if len(labels) > 10:
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    else:
        ax.set_xticklabels(labels, fontsize=9)

    ax.set_title(title, fontsize=13, fontweight="bold", color=FORD_BLUE, pad=12)
    ax.legend(fontsize=9, framealpha=0.9)
    ax.tick_params(axis="y", labelsize=9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    return _fig_to_base64(fig)


def bar_chart(
    labels: List[str],
    values: List[float],
    title: str = "",
    colors: Optional[List[str]] = None,
    size: Tuple[int, int] = DEFAULT_SIZE,
) -> str:
    """Vertical bar chart.

    Returns base64-encoded PNG.
    """
    if not HAS_MATPLOTLIB:
        return _no_matplotlib()

    _setup_style()
    fig, ax = plt.subplots(figsize=size)

    if colors is None:
        colors = [FORD_BLUE] * len(labels)
    elif len(colors) < len(labels):
        colors = colors + [FORD_BLUE] * (len(labels) - len(colors))

    bars = ax.bar(range(len(labels)), values, color=colors, width=0.65,
                  edgecolor="white", linewidth=0.5)

    ax.set_xticks(range(len(labels)))
    if len(labels) > 8:
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    else:
        ax.set_xticklabels(labels, fontsize=9)

    # Value labels on bars
    for bar_obj, val in zip(bars, values):
        if val > 0:
            ax.text(bar_obj.get_x() + bar_obj.get_width() / 2, bar_obj.get_height() + 0.3,
                    f"{val:g}", ha="center", va="bottom", fontsize=8, color=GRAY_500)

    ax.set_title(title, fontsize=13, fontweight="bold", color=FORD_BLUE, pad=12)
    ax.tick_params(axis="y", labelsize=9)
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    fig.tight_layout()

    return _fig_to_base64(fig)


def horizontal_bar(
    labels: List[str],
    values: List[float],
    title: str = "",
    color: str = FORD_BLUE,
    size: Tuple[int, int] = DEFAULT_SIZE,
) -> str:
    """Horizontal bar chart.

    Returns base64-encoded PNG.
    """
    if not HAS_MATPLOTLIB:
        return _no_matplotlib()

    _setup_style()
    # Adjust height based on number of items
    h = max(3, len(labels) * 0.4 + 1.5)
    fig, ax = plt.subplots(figsize=(size[0], h))

    y_pos = range(len(labels))
    bars = ax.barh(y_pos, values, color=color, height=0.6,
                   edgecolor="white", linewidth=0.5)

    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()  # highest value at top

    # Value labels
    max_val = max(values) if values else 1
    for bar_obj, val in zip(bars, values):
        ax.text(bar_obj.get_width() + max_val * 0.02, bar_obj.get_y() + bar_obj.get_height() / 2,
                f"{val:g}", va="center", fontsize=8, color=GRAY_500)

    ax.set_title(title, fontsize=13, fontweight="bold", color=FORD_BLUE, pad=12)
    ax.tick_params(axis="x", labelsize=9)
    ax.grid(axis="x", alpha=0.3)
    ax.set_axisbelow(True)
    fig.tight_layout()

    return _fig_to_base64(fig)


def stacked_bar(
    labels: List[str],
    dataset_list: List[Dict[str, Any]],
    title: str = "",
    size: Tuple[int, int] = DEFAULT_SIZE,
) -> str:
    """Stacked vertical bar chart.

    Parameters
    ----------
    labels : list[str]
        X-axis category labels.
    dataset_list : list[dict]
        Each dict has "label" (str) and "data" (list[float]).
    """
    if not HAS_MATPLOTLIB:
        return _no_matplotlib()

    _setup_style()
    fig, ax = plt.subplots(figsize=size)

    x = np.arange(len(labels))
    bottoms = np.zeros(len(labels))

    for i, ds in enumerate(dataset_list):
        color = PALETTE[i % len(PALETTE)]
        data = np.array(ds["data"], dtype=float)
        ax.bar(x, data, bottom=bottoms, color=color, width=0.6,
               label=ds.get("label", f"Series {i+1}"), edgecolor="white", linewidth=0.5)
        bottoms += data

    ax.set_xticks(x)
    if len(labels) > 8:
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    else:
        ax.set_xticklabels(labels, fontsize=9)

    ax.set_title(title, fontsize=13, fontweight="bold", color=FORD_BLUE, pad=12)
    ax.legend(fontsize=8, loc="upper right", framealpha=0.9)
    ax.tick_params(axis="y", labelsize=9)
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    fig.tight_layout()

    return _fig_to_base64(fig)


def donut_chart(
    labels: List[str],
    values: List[float],
    title: str = "",
    size: Tuple[int, int] = (5, 5),
) -> str:
    """Donut (ring) chart.

    Returns base64-encoded PNG.
    """
    if not HAS_MATPLOTLIB:
        return _no_matplotlib()

    _setup_style()
    fig, ax = plt.subplots(figsize=size)

    colors = [DONUT_PALETTE[i % len(DONUT_PALETTE)] for i in range(len(labels))]

    wedges, texts, autotexts = ax.pie(
        values, labels=None, autopct="%1.0f%%", startangle=90,
        colors=colors, pctdistance=0.78,
        wedgeprops=dict(width=0.45, edgecolor="white", linewidth=2),
    )

    for t in autotexts:
        t.set_fontsize(9)
        t.set_fontweight("bold")
        t.set_color("white")

    # Legend
    ax.legend(wedges, labels, loc="center left", bbox_to_anchor=(1, 0.5),
              fontsize=9, framealpha=0.9)

    # Center text with total
    total = sum(values)
    ax.text(0, 0, f"{total:g}\nTotal", ha="center", va="center",
            fontsize=14, fontweight="bold", color=FORD_BLUE)

    ax.set_title(title, fontsize=13, fontweight="bold", color=FORD_BLUE, pad=12)
    fig.tight_layout()

    return _fig_to_base64(fig)


def gauge_chart(
    value: float,
    target: float,
    title: str = "",
    unit: str = "",
    size: Tuple[int, int] = (4, 3),
) -> str:
    """Gauge / speedometer chart showing value vs target.

    Returns base64-encoded PNG.
    """
    if not HAS_MATPLOTLIB:
        return _no_matplotlib()

    fig, ax = plt.subplots(figsize=size, subplot_kw={"projection": "polar"})

    # We'll draw a half-circle gauge (180 degrees)
    max_val = max(target * 1.5, value * 1.2, 1)

    # Background arc
    theta_bg = np.linspace(np.pi, 0, 100)
    ax.fill_between(theta_bg, 0, 1, color=GRAY_200, alpha=0.5)

    # Target zone (green area up to target)
    target_frac = min(target / max_val, 1.0)
    theta_target = np.linspace(np.pi, np.pi - np.pi * target_frac, 50)
    ax.fill_between(theta_target, 0.6, 1.0, color=GREEN_LIGHT, alpha=0.3)

    # Value arc
    val_frac = min(value / max_val, 1.0)
    theta_val = np.linspace(np.pi, np.pi - np.pi * val_frac, 50)
    arc_color = GREEN if value <= target else (AMBER if value <= target * 1.2 else FIRE_RED)
    ax.fill_between(theta_val, 0.65, 0.95, color=arc_color, alpha=0.8)

    # Needle
    needle_angle = np.pi - np.pi * val_frac
    ax.plot([needle_angle, needle_angle], [0, 0.85], color=FORD_BLUE,
            linewidth=2.5, solid_capstyle="round")
    ax.plot(needle_angle, 0.85, "o", color=FORD_BLUE, markersize=5)
    ax.plot(needle_angle, 0, "o", color=FORD_BLUE, markersize=8)

    # Value text
    display_val = f"{value:g}{unit}" if unit else f"{value:g}"
    ax.text(np.pi / 2, 0.3, display_val, ha="center", va="center",
            fontsize=18, fontweight="bold", color=FORD_BLUE)
    ax.text(np.pi / 2, 0.08, f"Target: {target:g}{unit}",
            ha="center", va="center", fontsize=9, color=GRAY_500)

    ax.set_ylim(0, 1)
    ax.set_thetamin(0)
    ax.set_thetamax(180)
    ax.set_rticks([])
    ax.set_thetagrids([])
    ax.spines["polar"].set_visible(False)
    ax.grid(False)

    ax.set_title(title, fontsize=12, fontweight="bold", color=FORD_BLUE,
                 pad=10, y=1.05)
    fig.tight_layout()

    return _fig_to_base64(fig)


def heatmap(
    data_2d: List[List[float]],
    x_labels: List[str],
    y_labels: List[str],
    title: str = "",
    size: Tuple[int, int] = (8, 5),
) -> str:
    """Heat map grid (e.g. activity by hour x day-of-week).

    Parameters
    ----------
    data_2d : list[list[float]]
        2D array where data_2d[row][col] = value.
    x_labels : list[str]
        Column labels.
    y_labels : list[str]
        Row labels.
    """
    if not HAS_MATPLOTLIB:
        return _no_matplotlib()

    _setup_style()
    fig, ax = plt.subplots(figsize=size)

    data_arr = np.array(data_2d, dtype=float)

    im = ax.imshow(data_arr, cmap="YlOrRd", aspect="auto", interpolation="nearest")

    ax.set_xticks(range(len(x_labels)))
    ax.set_xticklabels(x_labels, fontsize=8, rotation=45, ha="right")
    ax.set_yticks(range(len(y_labels)))
    ax.set_yticklabels(y_labels, fontsize=9)

    # Annotate cells with values
    for i in range(len(y_labels)):
        for j in range(len(x_labels)):
            val = data_arr[i, j]
            if val > 0:
                text_color = "white" if val > data_arr.max() * 0.6 else GRAY_500
                ax.text(j, i, f"{val:g}", ha="center", va="center",
                        fontsize=7, color=text_color, fontweight="bold")

    ax.set_title(title, fontsize=13, fontweight="bold", color=FORD_BLUE, pad=12)

    # Colorbar
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.ax.tick_params(labelsize=8)

    fig.tight_layout()
    return _fig_to_base64(fig)


def kpi_card_image(
    value: str,
    label: str,
    trend: str = "",
    trend_pct: float = 0.0,
    size: Tuple[int, int] = (2.5, 1.5),
) -> str:
    """Single KPI tile rendered as an image.

    Useful for email where CSS layout is limited.

    Parameters
    ----------
    value : str
        The KPI value to display (e.g. "42", "5.3 min").
    label : str
        Description label (e.g. "Total Incidents").
    trend : str
        "up", "down", or "flat".
    trend_pct : float
        Percentage change (e.g. 12.5 for +12.5%).
    """
    if not HAS_MATPLOTLIB:
        return _no_matplotlib()

    fig, ax = plt.subplots(figsize=size)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Background card
    from matplotlib.patches import FancyBboxPatch
    card = FancyBboxPatch((0.02, 0.02), 0.96, 0.96, boxstyle="round,pad=0.05",
                          facecolor=WHITE, edgecolor=GRAY_200, linewidth=1.5)
    ax.add_patch(card)

    # Value
    ax.text(0.5, 0.62, str(value), ha="center", va="center",
            fontsize=22, fontweight="bold", color=FORD_BLUE)

    # Label
    ax.text(0.5, 0.32, label, ha="center", va="center",
            fontsize=9, color=GRAY_500)

    # Trend indicator
    if trend:
        if trend == "up":
            arrow = "\u25B2"
            color = FIRE_RED if trend_pct > 0 else GREEN
        elif trend == "down":
            arrow = "\u25BC"
            color = GREEN if trend_pct < 0 else FIRE_RED
        else:
            arrow = "\u25AC"
            color = GRAY_500

        trend_text = f"{arrow} {abs(trend_pct):.0f}%"
        ax.text(0.5, 0.12, trend_text, ha="center", va="center",
                fontsize=8, fontweight="bold", color=color)

    fig.tight_layout(pad=0)
    return _fig_to_base64(fig)
