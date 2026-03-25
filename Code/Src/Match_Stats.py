"""
Pure calculation helpers for demo stats. No UI dependencies.
"""

import numpy as np
import pandas as pd

# Demo tick rate and engagement forget window
TICK_RATE = 128
FORGET_WINDOW_SECONDS = 4
FORGET_WINDOW_TICKS = int(FORGET_WINDOW_SECONDS * TICK_RATE)

# Column name candidates for demoparser2 event tables
KILL_ATTACKER_COLS = ["attacker_steamid", "attackerSteamId", "attacker"]
KILL_VICTIM_COLS = ["user_steamid", "victimSteamId", "victim", "user"]
HURT_DAMAGE_COLS = ["dmg_health", "damage", "hpDamage", "health_damage"]


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
    """
    Return cheat_probability for killer at/near a kill tick.
    Uses the nearest tick for that player; prefers exact/previous tick when between samples.
    """
    if df is None or df.empty:
        return None
    if not killer_name or killer_name == "?":
        return None
    if "name" not in df.columns or "cheat_probability" not in df.columns:
        return None
    if "tick" not in df.columns or kill_tick is None:
        return None

    sub = df.loc[df["name"] == killer_name, ["tick", "cheat_probability"]].dropna(subset=["tick", "cheat_probability"])
    if sub.empty:
        return None

    ticks = sub["tick"].to_numpy()
    probs = sub["cheat_probability"].to_numpy()
    try:
        ticks_i = ticks.astype(np.int64, copy=False)
    except Exception:
        ticks_i = ticks.astype(np.int64)

    order = np.argsort(ticks_i, kind="stable")
    ticks_i = ticks_i[order]
    probs = probs[order]

    t = int(kill_tick)
    idx = int(np.searchsorted(ticks_i, t, side="right") - 1)
    if idx < 0:
        idx = 0

    # if the next tick is closer, use it
    if idx + 1 < len(ticks_i):
        if abs(int(ticks_i[idx + 1]) - t) < abs(int(ticks_i[idx]) - t):
            idx = idx + 1

    try:
        p = float(probs[idx])
    except Exception:
        return None
    return p if np.isfinite(p) else None


def calc_killfeed(kills_df, df, results, steamid_to_name):
    if kills_df is None or len(kills_df) == 0:
        return ["(No kills in this demo)"]
    att_col = _resolve_col(kills_df, KILL_ATTACKER_COLS)
    vic_col = _resolve_col(kills_df, KILL_VICTIM_COLS)
    weapon_col = "weapon" if "weapon" in kills_df.columns else None
    kill_tick_col = "tick" if "tick" in kills_df.columns else None
    lines = []
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

        cheat_prob = _per_kill_cheat_prob(df, killer, kill_tick)
        cheat_str = f" — {cheat_prob * 100:.1f}% cheat" if cheat_prob is not None else ""
        lines.append(f"[{killer}] -> [{weapon}] -> [{victim}]{cheat_str}")
    return lines


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
