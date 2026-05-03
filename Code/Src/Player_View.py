from __future__ import annotations

import numpy as np
import pandas as pd
from app_config import (
    KILL_WINDOW_BASELINE_TICKS_DEFAULT,
    KILL_WINDOW_POST_DEATH_TICKS_DEFAULT,
    KILL_WINDOW_SEARCH_BACK_TICKS_DEFAULT,
)


def build_player_view_lines(player_name: str) -> list[str]:
    """
    Non-UI helper for populating the top-right player view list.

    UI should call this and render the returned lines.
    """
    name = (player_name or "").strip()
    if not name:
        return []
    return [f"Name: {name}"]


def _format_demo_mmss_span(ticks_abs: np.ndarray, tick_rate: float = 128.0) -> str | None:
    """Absolute demo clock from tick count: m:ss … m:ss (same tick rate as gameplay)."""
    if ticks_abs is None or getattr(ticks_abs, "size", 0) == 0:
        return None
    t = np.asarray(ticks_abs, dtype=float)
    s0 = float(np.nanmin(t)) / float(tick_rate)
    s1 = float(np.nanmax(t)) / float(tick_rate)

    def fmt(sec: float) -> str:
        if not np.isfinite(sec):
            return "?"
        w = int(round(max(0.0, sec)))
        m, ss = divmod(w, 60)
        return f"{m}:{ss:02d}"

    return f"{fmt(s0)} … {fmt(s1)}"


def build_kill_view_lines(
    killer_name: str,
    cheat_pct: float | None,
    kill_meta: dict | None = None,
    *,
    ticks_abs: np.ndarray | None = None,
    tick_rate: float = 128.0,
) -> list[str]:
    """
    Non-UI helper for populating the top-right list when a specific kill is selected.

    kill_meta may include: ttd_ms, headshot (bool|None), killing_hit_line (str|None).
    ticks_abs: absolute demo ticks included in the mouse plot (min/max shown as m:ss … m:ss).
    """
    name = (killer_name or "").strip()
    if not name:
        return []
    lines = [f"Name: {name}"]
    if cheat_pct is not None:
        lines.append(f"Cheat Chance: {cheat_pct:.1f}%")
    span = _format_demo_mmss_span(ticks_abs, tick_rate=tick_rate) if ticks_abs is not None else None
    if span:
        lines.append(f"Plot window (demo time): {span}")

    if kill_meta:
        ttd = kill_meta.get("ttd_ms")
        if ttd is not None and isinstance(ttd, (int, float)) and np.isfinite(ttd):
            lines.append(f"TTD (this kill): {float(ttd):.0f} ms")
        else:
            lines.append("TTD (this kill): —")

        hs = kill_meta.get("headshot")
        if hs is True:
            lines.append("Headshot: yes")
        elif hs is False:
            lines.append("Headshot: no")
        else:
            lines.append("Headshot: —")

        kh = kill_meta.get("killing_hit_line")
        if kh:
            lines.append(f"Killing hit: {kh}")
        else:
            lines.append("Killing hit: —")

    return lines


def compute_kill_mouse_window(
    df: pd.DataFrame | None,
    killer_name: str,
    kill_tick: int | None,
    baseline_ticks: int = KILL_WINDOW_BASELINE_TICKS_DEFAULT,
    post_death_ticks: int = KILL_WINDOW_POST_DEATH_TICKS_DEFAULT,
    search_back_ticks: int = KILL_WINDOW_SEARCH_BACK_TICKS_DEFAULT,
) -> dict | None:
    """
    Pure (non-UI) kill analysis.

    Returns a dict with:
      - ticks_rel: np.ndarray (tick - kill_tick)
      - dx, dy, mag: np.ndarray
      - start_move_tick: int | None
      - fire_mask: np.ndarray bool | None — discrete shots only (shots_fired increments, else FIRE rising edges)
    """
    if df is None or df.empty or kill_tick is None:
        return None
    name = (killer_name or "").strip()
    if not name:
        return None
    if "tick" not in df.columns or "name" not in df.columns:
        return None
    if "usercmd_mouse_dx" not in df.columns or "usercmd_mouse_dy" not in df.columns:
        return None

    kt = int(kill_tick)
    t0 = kt - int(search_back_ticks)
    t1 = kt + int(post_death_ticks)

    base_cols = ["tick", "usercmd_mouse_dx", "usercmd_mouse_dy"]
    extra_cols = [c for c in ("pitch", "yaw", "FIRE", "shots_fired") if c in df.columns]
    sub = df.loc[
        (df["name"] == name) & (df["tick"].between(t0, t1)),
        base_cols + extra_cols,
    ].copy()
    if sub.empty:
        return None

    sub = sub.dropna(subset=["tick"])
    if sub.empty:
        return None

    # sort by tick and coerce to numeric
    sub["tick"] = pd.to_numeric(sub["tick"], errors="coerce")
    sub["usercmd_mouse_dx"] = pd.to_numeric(sub["usercmd_mouse_dx"], errors="coerce").fillna(0.0)
    sub["usercmd_mouse_dy"] = pd.to_numeric(sub["usercmd_mouse_dy"], errors="coerce").fillna(0.0)
    sub = sub.dropna(subset=["tick"]).sort_values("tick")

    ticks = sub["tick"].to_numpy(dtype=np.int64, copy=False)
    dx = sub["usercmd_mouse_dx"].to_numpy(dtype=np.float64, copy=False)
    dy = sub["usercmd_mouse_dy"].to_numpy(dtype=np.float64, copy=False)
    mag = np.sqrt(dx * dx + dy * dy)

    # Find "start moving" as the last transition from ~0 -> >0 before death tick
    before_mask = ticks <= kt
    start_move_tick = None
    if before_mask.any():
        ticks_b = ticks[before_mask]
        mag_b = mag[before_mask]
        if len(mag_b) >= 2:
            moving = mag_b > 0.0
            transitions = np.where(moving[1:] & (~moving[:-1]))[0] + 1
            if len(transitions) > 0:
                start_idx = int(transitions[-1])
                start_move_tick = int(ticks_b[start_idx])

    if start_move_tick is None:
        start_move_tick = kt - int(baseline_ticks)

    window_start = int(start_move_tick - int(baseline_ticks))
    window_end = int(kt + int(post_death_ticks))
    win_mask = (ticks >= window_start) & (ticks <= window_end)
    if not win_mask.any():
        return None

    ticks_w = ticks[win_mask]
    dx_w = dx[win_mask]
    dy_w = dy[win_mask]
    mag_w = mag[win_mask]

    out: dict = {
        "ticks_rel": (ticks_w - kt).astype(np.int64, copy=False),
        "ticks_abs": ticks_w.astype(np.int64, copy=False),
        "kill_tick": kt,
        "dx": dx_w,
        "dy": dy_w,
        "mag": mag_w,
        "start_move_rel": int(start_move_tick - kt),
        "pitch": None,
        "yaw": None,
    }

    if "pitch" in sub.columns and "yaw" in sub.columns:
        sub_w = sub.iloc[np.nonzero(win_mask)[0]].sort_values("tick")
        p = pd.to_numeric(sub_w["pitch"], errors="coerce")
        y = pd.to_numeric(sub_w["yaw"], errors="coerce")
        if p.notna().any() and y.notna().any():
            pitch_arr = p.to_numpy(dtype=np.float64, copy=False)
            yaw_arr = y.to_numpy(dtype=np.float64, copy=False)
            # unwrap yaw (deg) so line connections don't jump across ±180
            yaw_unwrapped = np.degrees(np.unwrap(np.radians(yaw_arr)))
            out["pitch"] = pitch_arr
            out["yaw"] = yaw_unwrapped
            out["fire_mask"] = _discrete_shot_mask(sub, sub_w)

    return out


def _discrete_shot_mask(sub: pd.DataFrame, sub_w: pd.DataFrame) -> np.ndarray | None:
    n = len(sub_w)
    if n == 0:
        return None
    tw = sub_w["tick"].to_numpy()
    first_t = int(tw[0])
    prev_rows = sub.loc[sub["tick"] < first_t]

    if "shots_fired" in sub_w.columns:
        sh = pd.to_numeric(sub_w["shots_fired"], errors="coerce").fillna(0).to_numpy(dtype=float)
        if len(prev_rows):
            prev_sh = float(
                pd.to_numeric(prev_rows["shots_fired"], errors="coerce").fillna(0).iloc[-1]
            )
        else:
            prev_sh = None
        mask = np.zeros(n, dtype=bool)
        if prev_sh is not None:
            mask[0] = sh[0] > prev_sh
        if n > 1:
            mask[1:] = sh[1:] > sh[:-1]
        return mask

    if "FIRE" in sub_w.columns:
        fv = pd.to_numeric(sub_w["FIRE"], errors="coerce").fillna(0).to_numpy(dtype=float)
        firing = fv > 0
        if len(prev_rows):
            prev_fire = (
                float(pd.to_numeric(prev_rows["FIRE"], errors="coerce").fillna(0).iloc[-1]) > 0
            )
        else:
            prev_fire = False
        mask = np.zeros(n, dtype=bool)
        mask[0] = bool(firing[0]) and not prev_fire
        if n > 1:
            mask[1:] = firing[1:] & (~firing[:-1])
        return mask

    return None

