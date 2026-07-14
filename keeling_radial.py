
import io
import sys
import math
import textwrap
from datetime import datetime, date
from pathlib import Path

import csv
import urllib.request
import ssl

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import matplotlib.patheffects as path_effects
import matplotlib.font_manager as fm

# URLs for monthly Mauna Loa CO2 data
NOAA_URL = "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_mm_mlo.csv"
SCRIPPS_URL = "https://scrippsco2.ucsd.edu/assets/data/atmospheric/stations/in_situ_co2/monthly/monthly_in_situ_co2_mlo.csv"

def fetch_csv(url: str) -> str:
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(url, context=ctx, timeout=30) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        raise RuntimeError(f"Failed to fetch {url}: {e}") from e

def parse_noaa_csv(txt: str):
    """
    Parse NOAA monthly CSV with header lines beginning with '#'
    Expected columns per NOAA docs:
    # year,month,decimal date,average,interpolated,trend,days
    """
    years, months, dec_date, average, interpolated = [], [], [], [], []
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(",")
        if len(parts) < 7:
            continue
        try:
            y = int(parts[0]); m = int(parts[1])
            dd = float(parts[2])
            avg = float(parts[3]) if parts[3] not in ("-99.99","-1") else float("nan")
            itp = float(parts[4]) if parts[4] not in ("-99.99","-1") else float("nan")
            years.append(y); months.append(m); dec_date.append(dd); average.append(avg); interpolated.append(itp)
        except Exception:
            continue
    return np.array(years), np.array(months), np.array(dec_date), np.array(average), np.array(interpolated)

def parse_scripps_csv(txt: str):
    """
    Parse Scripps monthly CSV with textual header, columns may include:
    'date','year','month','value','qcflag', etc.
    We'll try to detect header row and pull year, month, value.
    """
    lines = [ln for ln in txt.splitlines() if ln.strip()]
    # Find the header line by searching for 'year' and 'month'
    hdr_idx = None
    for i, ln in enumerate(lines):
        low = ln.lower()
        if "year" in low and "month" in low:
            hdr_idx = i
            break
    if hdr_idx is None:
        # fallback: scan with csv and try to infer
        start_idx = 0
    else:
        start_idx = hdr_idx

    reader = csv.reader(lines[start_idx:])
    header = next(reader)
    header_lower = [h.strip().lower() for h in header]

    def col_idx(name_options):
        for nm in name_options:
            if nm in header_lower:
                return header_lower.index(nm)
        return None

    idx_year = col_idx(["year"])
    idx_month = col_idx(["month"])
    idx_value = col_idx(["value","co2","co2ppm","mole_fraction","average","interpolated"])

    years=[]; months=[]; dec_date=[]; average=[]; interpolated=[]
    for row in reader:
        try:
            y = int(float(row[idx_year]))
            m = int(float(row[idx_month]))
            val = float(row[idx_value])
        except Exception:
            continue
        years.append(y); months.append(m)
        # approximate decimal date
        dd = y + (m-0.5)/12.0
        dec_date.append(dd)
        average.append(val)
        interpolated.append(val)

    return np.array(years), np.array(months), np.array(dec_date), np.array(average), np.array(interpolated)

def load_monthly_series():
    # Try NOAA first, then Scripps
    try:
        txt = fetch_csv(NOAA_URL)
        y, m, dd, avg, itp = parse_noaa_csv(txt)
    except Exception as e_noaa:
        try:
            txt = fetch_csv(SCRIPPS_URL)
            y, m, dd, avg, itp = parse_scripps_csv(txt)
        except Exception as e_sio:
            raise RuntimeError(f"Could not load NOAA or Scripps monthly data.\nNOAA error: {e_noaa}\nScripps error: {e_sio}")

    # Prefer 'average' where present; fall back to 'interpolated' for gaps
    vals = np.where(~np.isnan(avg), avg, itp)
    # Filter out nans
    mask = ~np.isnan(vals)
    return y[mask], m[mask], dd[mask], vals[mask]

def load_daily_series_from_file(csv_path: str):
    """
    Load daily CO2 series from a local CSV file, robustly detecting columns.
    Accepts formats with columns like: 'date' (YYYY-MM-DD), or separate
    'year','month','day' plus 'value'/'co2' etc.
    Returns arrays: years, dec_date, values, day_of_year
    """
    p = Path(csv_path)
    if not p.exists():
        raise FileNotFoundError(f"Daily CSV not found: {csv_path}")

    with p.open("r", encoding="utf-8", errors="replace") as f:
        raw_lines = f.read().splitlines()

    years = []
    dec_dates = []
    values = []
    doy_list = []

    for ln in raw_lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("%"):
            # comment/header in NOAA/Scripps daily format
            continue
        if "," not in s:
            continue
        parts = [p.strip() for p in s.split(",")]
        if len(parts) < 4:
            continue
        try:
            y = int(float(parts[0]))
            m = int(float(parts[1]))
            d = int(float(parts[2]))
            val_str = parts[3]
            val = float("nan") if val_str.strip().lower() in ("nan", "-99.99", "-1") else float(val_str)
        except Exception:
            continue

        if math.isnan(val):
            continue

        # Compute day-of-year and decimal date
        try:
            dt2 = date(y, m, d)
        except Exception:
            continue
        doy = dt2.timetuple().tm_yday
        is_leap = (y % 4 == 0 and y % 100 != 0) or (y % 400 == 0)
        diy = 366 if is_leap else 365
        dec = y + (doy - 0.5) / float(diy)

        years.append(y)
        dec_dates.append(dec)
        values.append(val)
        doy_list.append(doy)

    if not values:
        raise RuntimeError("No valid rows parsed from daily CSV")

    y_arr = np.array(years)
    dd_arr = np.array(dec_dates, dtype=float)
    v_arr = np.array(values, dtype=float)
    doy_arr = np.array(doy_list, dtype=int)
    return y_arr, dd_arr, v_arr, doy_arr

def make_radial_plot(dec_date, values, out_png="keeling_radial.png", out_svg="keeling_radial.svg", *, years=None, day_of_year=None):
    """
    Create a radial polar plot with:
      - angle = month-of-year mapped to [0, 2π)
      - radius = CO2 value, optionally scaled
      - line segments colored from white (start) to blue (end)
      - line width grows from thin to thick over time
      - no ticks, labels, or annotations
    """
    # Compute angle by month-of-year (default) or by day-of-year if provided
    if day_of_year is not None and years is not None:
        # Per-sample days-in-year to handle leap years
        days_in_year = np.array([
            366.0 if ((y % 4 == 0 and y % 100 != 0) or (y % 400 == 0)) else 365.0
            for y in years
        ])
        theta = ((day_of_year - 0.5) / days_in_year) * 2.0 * math.pi
    else:
        months = ((dec_date % 1.0) * 12.0) + 0.5  # 0.5 centers mid-month
        theta = (months / 12.0) * 2.0 * math.pi

    r = values.astype(float)
    # Normalize radius to [0, 1] so the spiral reaches the border
    r_min = np.nanmin(r)
    r_max = np.nanmax(r)
    r_span = float(max(1e-9, (r_max - r_min)))
    r_scaled = (r - r_min) / r_span

    # Prepare color gradient from white to blue across time using a high-exponent power curve
    # so that only the very last points get strongly blue.
    n = len(r_scaled)
    progress = np.linspace(0.0, 1.0, n)
    # Larger gamma -> sharper transition right at the end
    power_gamma = 30.0
    mapped = np.power(progress, power_gamma)
    # Colors: start white (1,1,1), end blue (0,0,1)
    colors = np.column_stack([
        1.0 - mapped,  # R
        1.0 - mapped,  # G
        np.ones(n)     # B
    ])

    # Line width grows from thin to very thick using a high-exponent curve
    # to make the thickening happen very near the end
    lw_start = 0.30
    lw_end = 7.0
    width_gamma = 25.0
    mapped_w = np.power(progress, width_gamma)
    widths = lw_start + (lw_end - lw_start) * mapped_w

    # Alpha is constant (fully opaque); the mapping is kept so the endpoints stay tunable
    alpha_start = 1.00
    alpha_end = 1.00
    alpha_gamma = 10.0
    mapped_a = np.power(progress, alpha_gamma)
    alphas = alpha_start + (alpha_end - alpha_start) * mapped_a

    # Create figure with dark background
    fig = plt.figure(figsize=(8, 8), dpi=200)
    ax = plt.subplot(111, projection="polar")
    bg_color = "#0d1117"
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)

    # Remove all spines, ticks, labels
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_frame_on(False)
    # Ensure the outermost radius meets the border
    ax.set_rlim(0.0, 1.0)

    # Draw progressive line segments so width and color can vary
    for i in range(1, n):
        ax.plot(
            [theta[i-1], theta[i]],
            [r_scaled[i-1], r_scaled[i]],
            color=colors[i],
            linewidth=widths[i],
            alpha=alphas[i],
            solid_capstyle="round",
        )

    # Tight layout and save
    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    fig.savefig(out_png, bbox_inches="tight", pad_inches=0, dpi=300, facecolor=fig.get_facecolor())
    fig.savefig(out_svg, bbox_inches="tight", pad_inches=0, facecolor=fig.get_facecolor())
    plt.close(fig)

def make_radial_gif(
    dec_date,
    values,
    out_gif="keeling_radial.gif",
    *,
    years=None,
    day_of_year=None,
    max_frames: int = 1200,
    max_segments: int = 6000,
    dpi: int = 150,
    fps: int = 15,
    blit: bool = False,
    duration_seconds: float | None = None,
    easing_gamma: float = 3.2,
    color_segment_scale: int = 1,
    magenta_tail_groups: int = 0,
    magenta_linewidth_multiplier: float = 1.0,
    # Tail length in datapoints (post-decimation); overrides magenta_tail_groups if provided
    magenta_tail_points: int | None = None,
    # Echo the tail inward across previous years (same angle, smaller radius)
    magenta_inward_years: int = 7,
    # Early visibility boost for magenta thickness
    magenta_early_boost_multiplier: float = 3.0,
    magenta_early_boost_gamma: float = 1.6,
    # Pulse shaping parameters
    pulse_ramp_gamma: float = 3.5,  # >1: very little early, ramps late
    min_pulse_amp: float = 0.001,   # normalized radial units at start
    max_pulse_amp: float = 0.024,   # normalized radial units at end
    min_pulse_speed: float = 0.02,  # cycles/frame start
    max_pulse_speed: float = 0.45,  # cycles/frame end,
    # Intermittent pulse gating (on/off bursts)
    pulse_burst_period_frames: int = 24,  # frames per on+off cycle
    pulse_burst_on_ratio: float = 0.45,   # fraction of cycle the pulse is ON
    # End-intensity controls (boost pulse during last N seconds of the clip)
    intense_window_seconds: float = 2.0,
    intense_amp_multiplier: float = 3.0,
    intense_speed_multiplier: float = 1.8,
    intense_jitter_multiplier: float = 2.0,
    intensity_gamma: float = 2.5,
    # Hold the final frame for extra seconds at the end (duplicates the last frame)
    pause_last_seconds: float = 0.0,
):
    """
    Create an animated GIF that progressively draws the spiral from the start
    to the end of the series, using the same styling, colors, and non-linear
    width/opacity scaling as the static plot.
    """
    # Compute angle by month-of-year (default) or by day-of-year if provided
    if day_of_year is not None and years is not None:
        days_in_year = np.array([
            366.0 if ((y % 4 == 0 and y % 100 != 0) or (y % 400 == 0)) else 365.0
            for y in years
        ])
        theta = ((day_of_year - 0.5) / days_in_year) * 2.0 * math.pi
    else:
        months = ((dec_date % 1.0) * 12.0) + 0.5
        theta = (months / 12.0) * 2.0 * math.pi

    r = values.astype(float)

    # Normalize radius to [0, 1] so the spiral reaches the border
    r_min = np.nanmin(r)
    r_max = np.nanmax(r)
    r_span = float(max(1e-9, (r_max - r_min)))
    r_scaled = (r - r_min) / r_span

    # Precompute style arrays
    n = len(r_scaled)
    # Decimate if too many segments (speeds up GIF creation significantly)
    stride = max(1, int(math.ceil(n / float(max_segments))))
    if stride > 1:
        theta = theta[::stride]
        r_scaled = r_scaled[::stride]
        n = len(r_scaled)
    progress = np.linspace(0.0, 1.0, n)

    # Color mapping (only last points turn deep blue)
    power_gamma_color = 30.0
    mapped_color = np.power(progress, power_gamma_color)
    colors = np.column_stack([
        1.0 - mapped_color,
        1.0 - mapped_color,
        np.ones(n)
    ])

    # Width mapping (very thin early, very thick near the end)
    lw_start = 0.30
    lw_end = 7.0
    width_gamma = 25.0
    mapped_w = np.power(progress, width_gamma)
    widths = lw_start + (lw_end - lw_start) * mapped_w

    # Alpha mapping (constant, fully opaque; endpoints kept tunable)
    alpha_start = 1.00
    alpha_end = 1.00
    alpha_gamma = 10.0
    mapped_a = np.power(progress, alpha_gamma)
    alphas = alpha_start + (alpha_end - alpha_start) * mapped_a

    # Prepare decimated dec_date for time->year mapping in updates
    dec_date_arr = np.asarray(dec_date, dtype=float)
    if stride > 1:
        dec_date_arr = dec_date_arr[::stride]

    # Figure and axes (dark background consistent with static)
    fig = plt.figure(figsize=(8, 8), dpi=200)
    ax = plt.subplot(111, projection="polar")
    bg_color = "#0d1117"
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_frame_on(False)
    # Ensure the outermost radius meets the border
    ax.set_rlim(0.0, 1.0)

    # Load the bundled pixel font (Visitor BRK by Brian Kent, freeware);
    # falls back to matplotlib's default font if missing
    font_path = Path(__file__).resolve().parent / "assets" / "fonts" / "visitor1.ttf"
    visitor_fp = fm.FontProperties(fname=str(font_path)) if font_path.exists() else None

    # Bottom-center subtitle
    subtitle = fig.text(
        0.5, 0.05, "Global CO2 Levels 1958 - 2025",
        ha="center", va="bottom",
        fontsize=14, fontweight="bold",
        color=(1.0, 1.0, 1.0), alpha=0.95,
        fontproperties=visitor_fp,
    )
    subtitle.set_path_effects([
        path_effects.Stroke(linewidth=3.0, foreground=(0.0, 0.0, 0.0, 0.85)),
        path_effects.Normal(),
    ])

    # Precompute per-segment base geometry for quick updates
    seg_theta = np.stack([theta[:-1], theta[1:]], axis=1)  # (n-1, 2)
    seg_r = np.stack([r_scaled[:-1], r_scaled[1:]], axis=1)  # (n-1, 2)

    # Neon palette endpoints for pulsing (cyan <-> magenta)
    neon_cyan = np.array([0.0, 0.82, 1.0])
    neon_magenta = np.array([1.0, 0.17, 0.84])

    # Create each segment line artist
    lines = []
    for i in range(1, n):
        ln, = ax.plot(
            seg_theta[i-1],
            seg_r[i-1],
            color=colors[i],
            linewidth=widths[i],
            alpha=0.0,  # start invisible; will reveal progressively
            solid_capstyle="round",
        )
        lines.append(ln)

    # Decade/year label in upper-right (now left-aligned to keep position steady)
    decade_text = ax.text(
        0.955, 0.975, "",
        transform=ax.transAxes,
        ha="left", va="top",
        fontsize=16, fontweight="heavy",
        color=(1.0, 1.0, 1.0), alpha=0.0,
        fontproperties=visitor_fp,
    )
    # Blocky white letters with bold black stroke
    decade_text.set_path_effects([
        path_effects.Stroke(linewidth=3.8, foreground=(0.0, 0.0, 0.0, 0.95)),
        path_effects.Normal(),
    ])

    # Helper to find the index approximately k years back from index i0
    def find_year_back_index(i0: int, years_back: int) -> int | None:
        target = dec_date_arr[i0] - float(years_back)
        pos = int(np.searchsorted(dec_date_arr, target))
        candidates = []
        if 0 <= pos < len(dec_date_arr):
            candidates.append(pos)
        if 0 <= pos - 1 < len(dec_date_arr):
            candidates.append(pos - 1)
        if not candidates:
            return None
        best = min(candidates, key=lambda j: abs(dec_date_arr[j] - target))
        return best

    def init():
        for ln in lines:
            ln.set_alpha(0.0)
        decade_text.set_text("")
        decade_text.set_alpha(0.0)
        return lines

    # Build a non-linear frame sequence: fast at the beginning, slow near the end
    # Map a uniform time grid through a power curve to concentrate frames at the end
    if duration_seconds is not None and duration_seconds > 0:
        total_frames = max(2, min(n, int(round(fps * duration_seconds))))
    else:
        total_frames = min(n, max_frames)
    t = np.linspace(0.0, 1.0, total_frames)
    # Ease-out curve: concentrates frames near the end to slow down visibly
    eased = 1.0 - np.power(1.0 - t, float(max(1.0, easing_gamma)))
    frame_indices = np.unique(np.clip((eased * (n - 1)).astype(int), 0, n - 1))
    if frame_indices[0] == 0:
        frame_indices[0] = 1  # skip frame 0 as update expects >= 1 to draw first seg

    # Duplicate the final frame to create a pause at the end
    if pause_last_seconds and pause_last_seconds > 0:
        extra = int(round(fps * float(pause_last_seconds)))
        if extra > 0:
            frame_indices = np.concatenate([frame_indices, np.full(extra, (n - 1), dtype=int)])

    # Cache the final frame index for color override logic
    _final_frame_index = int(frame_indices[-1])

    # Map frame index -> normalized time position (0..1) for end-intensity ramp
    _frame_time_pos = {}
    if len(frame_indices) > 1:
        total = len(frame_indices) - 1
        for k, fi in enumerate(frame_indices):
            _frame_time_pos[int(fi)] = k / float(total)
    else:
        _frame_time_pos[int(frame_indices[0])] = 0.0

    def update(frame_idx):
        updated_artists = []
        if frame_idx == 0:
            return updated_artists

        # Reveal the current segment
        ln_curr = lines[frame_idx - 1]
        ln_curr.set_alpha(alphas[frame_idx])
        updated_artists.append(ln_curr)

        # Update decade label
        idx_pt = min(frame_idx, len(dec_date_arr) - 1)
        current_year = int(math.floor(dec_date_arr[idx_pt]))
        # Show the exact year instead of decade
        if current_year >= 1958:
            decade_text.set_text(f"{current_year:04d}")
            decade_text.set_alpha(1.0)
        else:
            decade_text.set_alpha(0.0)
        updated_artists.append(decade_text)

        # Pulsing neon effect on recent window (coloring), but pulse geometry applies to all visible lines
        pulse_window = 80  # number of recent segments to pulse (increase for stronger effect)
        start_color_i = max(1, frame_idx - pulse_window)
        glitch_period = 16  # every N frames, apply a brief glitch
        glitch_now = (frame_idx % glitch_period) in (0, 1, 2)
        jitter_amp = 0.01  # small jitter in normalized radial units

        # Global pulse that increases frequency and magnitude toward the end (non-linear ramp)
        heat = frame_idx / float(max(1, n - 1))
        eased_heat = math.pow(heat, max(1.0, pulse_ramp_gamma))
        base_period = 22
        min_period = 6
        period = int(max(min_period, round(base_period - eased_heat * (base_period - min_period))))
        pulse_speed = min_pulse_speed + (max_pulse_speed - min_pulse_speed) * eased_heat
        pulse_phase = 2.0 * math.pi * (frame_idx * pulse_speed)
        pulse_amp = min_pulse_amp + (max_pulse_amp - min_pulse_amp) * eased_heat

        # Intermittent gating: only allow pulse during the ON portion of a burst cycle
        burst_period = max(2, int(pulse_burst_period_frames))
        gate = 1.0 if ((frame_idx % burst_period) / float(burst_period)) < float(max(0.0, min(1.0, pulse_burst_on_ratio))) else 0.0
        # For the very last frame (and any duplicates for pause), disable pulse entirely
        if frame_idx >= _final_frame_index:
            gate = 0.0

        # Intensify pulse near the end of the clip duration
        if duration_seconds and duration_seconds > 0:
            # Map this frame to normalized time position in the exported clip
            tpos = _frame_time_pos.get(frame_idx, heat)  # fallback to data progress if unknown
            start_t = max(0.0, 1.0 - (float(intense_window_seconds) / float(duration_seconds)))
            if tpos >= start_t:
                s = ((tpos - start_t) / max(1e-9, (1.0 - start_t))) ** max(1.0, float(intensity_gamma))
                pulse_amp *= (1.0 + s * (float(intense_amp_multiplier) - 1.0))
                pulse_speed *= (1.0 + s * (float(intense_speed_multiplier) - 1.0))
                jitter_amp *= (1.0 + s * (float(intense_jitter_multiplier) - 1.0))

        # Color all segments before the pulse window cyan so the trail remains cyan
        if start_color_i > 1:
            for j in range(1, start_color_i):
                ln_old = lines[j - 1]
                ln_old.set_color(neon_cyan)
                ln_old.set_linewidth(widths[j])
                ln_old.set_alpha(min(1.0, max(0.85, alphas[j])))
                updated_artists.append(ln_old)

        # Apply pulse to geometry for all visible lines (entire image so far)
        for i in range(1, frame_idx + 1):
            ln = lines[i - 1]
            # Phase offset per segment to create wave-like pulse
            gi = max(1, i) // max(1, color_segment_scale)
            gf = max(1, frame_idx) // max(1, color_segment_scale)
            phase = 2.0 * math.pi * ((gf - gi) % period) / period
            # Compute base mix for width pulsing regardless of color override, then gate it
            base_mix = 0.5 + 0.5 * math.sin(phase)
            mix = gate * base_mix

            # Determine whether this segment should be magenta by tail groups or points
            is_magenta_segment = False
            if i >= start_color_i:
                if magenta_tail_points is not None:
                    is_magenta_segment = (frame_idx - i) < max(1, int(magenta_tail_points))
                elif magenta_tail_groups:
                    is_magenta_segment = (gf - gi) < max(1, magenta_tail_groups)

            # Color logic (force all-cyan on the last frame)
            if frame_idx >= _final_frame_index:
                ln.set_color(neon_cyan)
            else:
                if i < start_color_i:
                    ln.set_color(neon_cyan)
                else:
                    if is_magenta_segment:
                        ln.set_color(neon_magenta)
                    else:
                        neon = (1.0 - mix) * neon_cyan + mix * neon_magenta
                        ln.set_color(neon)

            # Pulse thickness slightly around base
            pulse_scale = 0.90 + 0.30 * mix
            # Early boost for magenta visibility that fades over time (strong at start)
            early = (1.0 - heat) ** max(1.0, magenta_early_boost_gamma)
            visibility_mult = 1.0 + (float(magenta_early_boost_multiplier) - 1.0) * early
            lw_mult = (magenta_linewidth_multiplier * visibility_mult) if is_magenta_segment else 1.0
            ln.set_linewidth(widths[i] * pulse_scale * lw_mult)

            # Keep lines mostly opaque
            ln.set_alpha(min(1.0, max(0.85, alphas[i])))

            # Compute per-line pulse offset (scalar applied to both endpoints of segment)
            pulse = (pulse_amp * gate) * math.sin(pulse_phase + (i * 0.12))
            base_r = seg_r[i - 1]
            # Optional glitch: jitter a few recent lines' radius briefly
            if glitch_now and (i % 7) == 0 and gate > 0.0:
                jitter = (np.random.rand(2) - 0.5) * 2.0 * jitter_amp
                ln.set_data(seg_theta[i - 1], base_r + jitter + pulse)
            else:
                # Apply smooth pulse only
                ln.set_data(seg_theta[i - 1], base_r + pulse)

            updated_artists.append(ln)

        return updated_artists

    anim = animation.FuncAnimation(
        fig,
        update,
        init_func=init,
        frames=frame_indices,
        interval=22,  # a bit faster base interval
        blit=blit,
        repeat=False,
    )

    writer = animation.PillowWriter(fps=fps)
    anim.save(
        out_gif,
        writer=writer,
        dpi=dpi,
        savefig_kwargs={
            "facecolor": fig.get_facecolor(),
            "pad_inches": 0,
        },
    )
    plt.close(fig)

def main():
    # If a local daily dataset is present, use it; otherwise fall back to monthly
    daily_path = Path("daily_in_situ_co2_mlo.csv")
    
    # Generate timestamp for filename
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if daily_path.exists():
        y, dd, vals, doy = load_daily_series_from_file(str(daily_path))
        make_radial_plot(dd, vals, years=y, day_of_year=doy)
        # These are the exact settings that produced the published 16s 1920px render
        make_radial_gif(
            dd, vals, 
            years=y, 
            day_of_year=doy,
            out_gif=f'keeling_radial_16s_1920px_{timestamp}.gif',
            max_segments=4000,
            dpi=240,  # 8 inches * 240 DPI = 1920px
            fps=40,
            duration_seconds=14.0,
            pause_last_seconds=2.0,
            easing_gamma=1.0,
            color_segment_scale=5,
            magenta_tail_points=10,
            magenta_linewidth_multiplier=1.8,
            magenta_early_boost_multiplier=3.0,
            magenta_early_boost_gamma=1.8,
            pulse_ramp_gamma=4.5,
            min_pulse_amp=0.0005,
            max_pulse_amp=0.022,
            min_pulse_speed=0.01,
            max_pulse_speed=0.5,
            pulse_burst_period_frames=24,
            pulse_burst_on_ratio=0.45
        )
        print(f"Saved (daily): keeling_radial.png, keeling_radial.svg, and keeling_radial_16s_1920px_{timestamp}.gif")
    else:
        y, m, dd, vals = load_monthly_series()
        make_radial_plot(dd, vals)
        make_radial_gif(dd, vals, out_gif=f'keeling_radial_{timestamp}.gif')
        print(f"Saved (monthly): keeling_radial.png, keeling_radial.svg, and keeling_radial_{timestamp}.gif")

if __name__ == "__main__":
    main()
