"""
Pure calculation helpers for demo stats. No UI dependencies.
"""

import numpy as np
import pandas as pd
from app_config import (
    FORGET_WINDOW_SECONDS_DEFAULT,
    KILL_SCORE_WINDOW_TICKS_DEFAULT,
)

# Demo tick rate and engagement forget window
TICK_RATE = 128
FORGET_WINDOW_SECONDS = FORGET_WINDOW_SECONDS_DEFAULT
FORGET_WINDOW_TICKS = int(FORGET_WINDOW_SECONDS * TICK_RATE)

# Column name candidates for demoparser2 event tables
KILL_ATTACKER_COLS = ["attacker_steamid", "attackerSteamId", "attacker"]
KILL_VICTIM_COLS = ["user_steamid", "victimSteamId", "victim", "user"]
HURT_DAMAGE_COLS = ["dmg_health", "damage", "hpDamage", "health_damage"]
HURT_HITGROUP_COLS = ["hitgroup", "hitGroup", "hit_group", "hitgroupname"]
HURT_WEAPON_COLS = ["weapon", "weapon_name", "inflictor"]


def _resolve_col(df, candidates):
    if df is None:
        return None
    return next((c for c in candidates if c in df.columns), None)


def _name_for(steamid, steamid_to_name):
    if pd.isna(steamid) or str(steamid) == "nan":
        return "?"
    return steamid_to_name.get(str(steamid), str(steamid))


def get_name_from_steamid(df):
    if df is None or "steamid" not in df.columns or "name" not in df.columns:
        return {}
    return {
        str(r["steamid"]): r["name"] or "?"
        for _, r in df[["steamid", "name"]].drop_duplicates("steamid").iterrows()
        if str(r["steamid"]) and str(r["steamid"]) != "nan"
    }


def _per_kill_cheat_prob(df: pd.DataFrame | None, killer_name: str, kill_tick: int | None) -> float | None:
    # Backward compatible wrapper: return only the probability.
    cheat_prob, _ref_tick = per_kill_cheat_prob_and_ref_tick(
        df,
        killer_name,
        kill_tick,
        score_window_ticks=KILL_SCORE_WINDOW_TICKS_DEFAULT,
        use_last_fire_tick=True,
    )
    return cheat_prob


def _headshot_from_kill_row(row) -> bool | None:
    """Best-effort headshot flag from player_death row."""
    for col in ("headshot", "m_bHeadshot", "is_headshot", "headshot_kill"):
        if col not in row:
            continue
        v = row.get(col)
        if pd.isna(v):
            continue
        if isinstance(v, (bool, np.bool_)):
            return bool(v)
        if isinstance(v, (int, float)) and not pd.isna(v):
            return bool(int(v))
        s = str(v).strip().lower()
        if s in ("true", "1", "yes"):
            return True
        if s in ("false", "0", "no"):
            return False
    return None


def _build_hurt_events_by_pair(hurts_df: pd.DataFrame | None, steamid_to_name: dict) -> dict[tuple[str, str], list[dict]]:
    """
    Group player_hurt rows by (killer_name, victim_name) with tick, damage, hitgroup.
    Each value list is sorted by tick ascending.
    """
    if hurts_df is None or len(hurts_df) == 0:
        return {}

    hurt_att_col = _resolve_col(hurts_df, KILL_ATTACKER_COLS)
    hurt_vic_col = _resolve_col(hurts_df, KILL_VICTIM_COLS)
    hurt_tick_col = "tick" if "tick" in hurts_df.columns else None
    damage_col = _resolve_col(hurts_df, HURT_DAMAGE_COLS)
    hitgroup_col = _resolve_col(hurts_df, HURT_HITGROUP_COLS)
    weapon_col = _resolve_col(hurts_df, HURT_WEAPON_COLS)

    if not hurt_att_col or not hurt_vic_col or not hurt_tick_col or not damage_col:
        return {}

    out: dict[tuple[str, str], list[dict]] = {}
    for _, row in hurts_df.iterrows():
        killer = _name_for(row.get(hurt_att_col), steamid_to_name)
        victim = _name_for(row.get(hurt_vic_col), steamid_to_name)
        if killer == "?" or victim == "?":
            continue
        t = row.get(hurt_tick_col)
        if pd.isna(t):
            continue
        try:
            tick_val = int(float(t))
        except (ValueError, TypeError):
            continue
        dmg = row.get(damage_col)
        try:
            dmg_int = int(float(dmg)) if pd.notna(dmg) else None
        except (ValueError, TypeError):
            dmg_int = None
        hg = None
        if hitgroup_col:
            hg_raw = row.get(hitgroup_col)
            if pd.notna(hg_raw):
                hg = str(hg_raw).strip() or None
        wpn = None
        if weapon_col:
            w_raw = row.get(weapon_col)
            if pd.notna(w_raw):
                wpn = str(w_raw).strip() or None
        key = (killer, victim)
        out.setdefault(key, []).append(
            {"tick": tick_val, "damage": dmg_int, "hitgroup": hg, "weapon": wpn}
        )

    for key in out:
        out[key].sort(key=lambda e: e["tick"])
    return out


def per_kill_ttd_and_killing_hit(
    killer_name: str,
    victim_name: str,
    death_tick: int | None,
    hurt_events_by_pair: dict[tuple[str, str], list[dict]],
) -> tuple[float | None, dict | None]:
    """
    TTD (ms): first damage in the 4s forget window before death, to death tick.
    Killing hit: last hurt event from killer to victim at or before death_tick.
    """
    if death_tick is None or not killer_name or not victim_name:
        return None, None
    if killer_name == "?" or victim_name == "?":
        return None, None

    key = (killer_name, victim_name)
    events = [e for e in hurt_events_by_pair.get(key, []) if e["tick"] <= int(death_tick)]
    if not events:
        return None, None

    ticks_only = [e["tick"] for e in events]
    D = int(death_tick)
    engagement_start = D
    for t in reversed(ticks_only):
        if engagement_start - t <= FORGET_WINDOW_TICKS:
            engagement_start = t
        else:
            break
    ttd_ms = (D - engagement_start) / TICK_RATE * 1000.0

    killing = events[-1]
    return float(ttd_ms), killing


def per_kill_cheat_prob_and_ref_tick(
    df: pd.DataFrame | None,
    killer_name: str,
    kill_tick: int | None,
    *,
    score_window_ticks: int = KILL_SCORE_WINDOW_TICKS_DEFAULT,
    use_last_fire_tick: bool = True,
) -> tuple[float | None, int | None]:
    """
    Compute the cheat probability for a single kill event and the "ref tick"
    used to compute it.

    By default, this prefers aligning to the last `FIRE` tick at/before the
    kill tick, since that more closely corresponds to the shot moment for
    weapons like SSG/Scout.
    """
    if df is None or df.empty:
        return None, None
    if not killer_name or killer_name == "?":
        return None, None
    if "name" not in df.columns or "cheat_probability" not in df.columns:
        return None, None
    if "tick" not in df.columns or kill_tick is None:
        return None, None

    # Pull only what we need. FIRE is optional for robustness.
    cols = ["tick", "cheat_probability"]
    fire_col = "FIRE"
    if use_last_fire_tick and fire_col in df.columns:
        cols.append(fire_col)

    sub = df.loc[df["name"] == killer_name, cols].dropna(subset=["tick", "cheat_probability"])
    if sub.empty:
        return None, None

    ticks = sub["tick"].to_numpy()
    probs = sub["cheat_probability"].to_numpy()
    fire_vals = None
    if use_last_fire_tick and fire_col in sub.columns:
        # FIRE may contain None/NaN or other unexpected values; coerce safely.
        fire_vals = pd.to_numeric(sub[fire_col], errors="coerce").fillna(0).to_numpy()

    # Coerce/sort by tick so all aligned arrays use the same ordering.
    try:
        ticks_i = ticks.astype(np.int64, copy=False)
    except Exception:
        ticks_i = ticks.astype(np.int64)

    order = np.argsort(ticks_i, kind="stable")
    ticks_i = ticks_i[order]
    probs = probs[order]
    if fire_vals is not None:
        fire_vals = fire_vals[order]

    t = int(kill_tick)

    # 1) Preferred path: last FIRE tick at/before death.
    if use_last_fire_tick and fire_vals is not None:
        fire_mask = (fire_vals > 0) & (ticks_i <= t)
        fire_idxs = np.where(fire_mask)[0]
        if fire_idxs.size > 0:
            last_fire_idx = int(fire_idxs[-1])
            ref_tick = int(ticks_i[last_fire_idx])
            win_mask = (
                (ticks_i >= ref_tick - int(score_window_ticks))
                & (ticks_i <= ref_tick + int(score_window_ticks))
                & (ticks_i <= t)
            )
            win_probs = probs[win_mask]
            if win_probs.size > 0:
                p = float(np.median(win_probs))
                p = p if np.isfinite(p) else None
                return p, ref_tick

    # 2) Fallback: last tick at/before death.
    idx = int(np.searchsorted(ticks_i, t, side="right") - 1)
    if idx < 0:
        idx = 0
    ref_tick = int(ticks_i[idx])

    win_mask = (ticks_i >= ref_tick - int(score_window_ticks)) & (ticks_i <= ref_tick + int(score_window_ticks))
    win_probs = probs[win_mask]
    if win_probs.size == 0:
        return None, ref_tick

    p = float(np.median(win_probs))
    p = p if np.isfinite(p) else None
    return p, ref_tick


def calc_killfeed(kills_df, df, results, steamid_to_name, hurts_df: pd.DataFrame | None = None):
    if kills_df is None or len(kills_df) == 0:
        return [{"text": "(No kills in this demo)", "meta": {}}]
    att_col = _resolve_col(kills_df, KILL_ATTACKER_COLS)
    vic_col = _resolve_col(kills_df, KILL_VICTIM_COLS)
    weapon_col = "weapon" if "weapon" in kills_df.columns else None
    kill_tick_col = "tick" if "tick" in kills_df.columns else None
    hurt_events_by_pair = _build_hurt_events_by_pair(hurts_df, steamid_to_name)
    items = []
    for _, kill in kills_df.iterrows():
        killer = _name_for(kill.get(att_col), steamid_to_name) if att_col else "?"
        victim = _name_for(kill.get(vic_col), steamid_to_name) if vic_col else "?"
        weapon = (str(kill.get(weapon_col, "")).strip() if weapon_col else "") or "?"

        kill_tick = None
        if kill_tick_col:
            try:
                kill_tick = int(float(kill.get(kill_tick_col)))
            except (ValueError, TypeError):
                kill_tick = None

        cheat_prob, ref_tick = per_kill_cheat_prob_and_ref_tick(df, killer, kill_tick)
        cheat_str = f" — {cheat_prob * 100:.1f}% cheat" if cheat_prob is not None else ""

        hs = _headshot_from_kill_row(kill)
        ttd_ms, killing = per_kill_ttd_and_killing_hit(killer, victim, kill_tick, hurt_events_by_pair)
        killing_line = None
        if killing is not None:
            parts = []
            if killing.get("damage") is not None:
                parts.append(f"{killing['damage']} dmg")
            if killing.get("hitgroup"):
                parts.append(killing["hitgroup"])
            if killing.get("weapon"):
                parts.append(str(killing["weapon"]))
            parts.append(f"tick {killing.get('tick')}")
            killing_line = " · ".join(parts) if parts else None

        items.append(
            {
                "text": f"[{killer}] -> [{weapon}] -> [{victim}]{cheat_str}",
                "meta": {
                    "killer_name": killer,
                    "victim_name": victim,
                    "weapon": weapon,
                    "kill_tick": kill_tick,
                    "score_tick": ref_tick,
                    "cheat_prob": cheat_prob,
                    "ttd_ms": ttd_ms,
                    "headshot": hs,
                    "killing_hit": killing,
                    "killing_hit_line": killing_line,
                },
            }
        )
    return items


def calc_scoreboard(df, results, kills_df, hurts_df, num_rounds, steamid_to_name):
    if not results:
        return []
    att_col = _resolve_col(kills_df, KILL_ATTACKER_COLS)
    vic_col = _resolve_col(kills_df, KILL_VICTIM_COLS)
    headshot_col = "headshot" if kills_df is not None and "headshot" in kills_df.columns else None
    damage_col = _resolve_col(hurts_df, HURT_DAMAGE_COLS)
    hurt_att_col = _resolve_col(hurts_df, KILL_ATTACKER_COLS)
    hurt_vic_col = _resolve_col(hurts_df, KILL_VICTIM_COLS)
    hurt_tick_col = "tick" if hurts_df is not None and "tick" in hurts_df.columns else None
    kill_tick_col = "tick" if kills_df is not None and "tick" in kills_df.columns else None
    rounds = num_rounds if num_rounds and num_rounds > 0 else 1

    k_count = {}
    d_count = {}
    hs_count = {}
    damage_dealt = {}
    running_pct = {}
    ttk_ms_list = {}
    for r in results:
        name = r["name"]
        k_count[name] = 0
        d_count[name] = 0
        hs_count[name] = 0
        damage_dealt[name] = 0
        running_pct[name] = None
        ttk_ms_list[name] = []

    if kills_df is not None and att_col and vic_col:
        for _, row in kills_df.iterrows():
            killer = _name_for(row.get(att_col), steamid_to_name)
            victim = _name_for(row.get(vic_col), steamid_to_name)
            if killer != "?" and killer in k_count:
                k_count[killer] += 1
                if headshot_col and row.get(headshot_col):
                    hs_count[killer] += 1
            if victim != "?" and victim in d_count:
                d_count[victim] += 1

    if hurts_df is not None and damage_col and hurt_att_col:
        for _, row in hurts_df.iterrows():
            att = _name_for(row.get(hurt_att_col), steamid_to_name)
            dmg = row.get(damage_col)
            if att != "?" and att in damage_dealt and pd.notna(dmg):
                try:
                    damage_dealt[att] += int(float(dmg))
                except (ValueError, TypeError):
                    pass

    # TTD: first damage in engagement (4s forget window) to kill
    if kills_df is not None and hurts_df is not None and att_col and vic_col and hurt_att_col and hurt_vic_col and kill_tick_col and hurt_tick_col:
        hurt_ticks_by_pair = {}
        for _, row in hurts_df.iterrows():
            att = _name_for(row.get(hurt_att_col), steamid_to_name)
            vic = _name_for(row.get(hurt_vic_col), steamid_to_name)
            t = row.get(hurt_tick_col)
            if att == "?" or vic == "?" or pd.isna(t):
                continue
            try:
                tick_val = int(float(t))
            except (ValueError, TypeError):
                continue
            key = (att, vic)
            hurt_ticks_by_pair.setdefault(key, []).append(tick_val)
        for key in hurt_ticks_by_pair:
            hurt_ticks_by_pair[key] = sorted(hurt_ticks_by_pair[key])
        for _, row in kills_df.iterrows():
            killer = _name_for(row.get(att_col), steamid_to_name)
            victim = _name_for(row.get(vic_col), steamid_to_name)
            if killer == "?" or victim == "?" or killer not in ttk_ms_list:
                continue
            try:
                death_tick = int(float(row.get(kill_tick_col)))
            except (ValueError, TypeError):
                continue
            ticks = [t for t in hurt_ticks_by_pair.get((killer, victim), []) if t <= death_tick]
            engagement_start = death_tick
            for t in reversed(ticks):
                if engagement_start - t <= FORGET_WINDOW_TICKS:
                    engagement_start = t
                else:
                    break
            ttk_ms = (death_tick - engagement_start) / TICK_RATE * 1000
            ttk_ms_list[killer].append(ttk_ms)

    if df is not None and "is_walking" in df.columns and "name" in df.columns:
        for name in running_pct:
            mask = df["name"] == name
            w = df.loc[mask, "is_walking"]
            if len(w) > 0:
                running_pct[name] = (1 - w.fillna(0).mean()) * 100

    rows = []
    for r in results:
        name = r["name"]
        adr_val = damage_dealt[name] / rounds if rounds and damage_dealt[name] else None
        adr_str = f"{adr_val:.0f}" if adr_val is not None and adr_val > 0 else "—"
        hs_val = (hs_count[name] / k_count[name] * 100) if k_count[name] else None
        hs_str = f"{hs_val:.0f}%" if hs_val is not None else "—"
        run_str = f"{running_pct[name]:.0f}%" if running_pct[name] is not None else "—"
        ttks = ttk_ms_list[name]
        ttk_str = f"{sum(ttks) / len(ttks):.0f} ms" if ttks else "—"
        cheat_pct = r["mean_probability"] * 100
        rows.append({
            "name": name,
            "k": k_count[name],
            "d": d_count[name],
            "adr_str": adr_str,
            "hs_str": hs_str,
            "util_str": "—",
            "running_str": run_str,
            "ttk_str": ttk_str,
            "cheat_str": f"{cheat_pct:.1f}%",
        })
    return rows
