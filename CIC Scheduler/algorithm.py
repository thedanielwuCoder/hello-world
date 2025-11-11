"""
algorithm.py — Greedy course scheduling engine

Exports:
    solve_greedy(course_df, offers, faculty_df, prefs, qual_df, overrides_df,
                 caps=(2,3), weights=(1000,100,1), seed=None) -> pd.DataFrame

Also supports CLI run (Excel in → 4 Excel schedules out) when executed directly.

Data expectations (column names are important):

course_df:
    - CourseId (int/str)
    - CourseName (str)
    - CourseCategory (str, used to infer electives vs core)
    - is_elective (bool)  # optional; if missing, inferred from CourseCategory

offers (one row per course offering, NOT per section):
    - OfferingId (int/str)
    - CourseId (int/str)
    - SemesterId (int/str)
    - SemesterId_str (str)      # optional; will be derived if missing
    - SectionQuantity (int)
    - Year (int)                 # optional; attach if available

faculty_df (faculty only; filter before calling or pass Identity column):
    - UserId (int/str)
    - Identity == "faculty" (optional; if present we filter)
    - UserName/UserEmail optional (not used here)
    - Experience (str, optional; used for qualification keyword matching)

prefs (faculty preferences):
    - UserId (int/str)
    - CourseId (int/str)
    - SemesterId (int/str)
    - SemesterId_str (str)      # optional; will be derived if missing
    - priority_rank (int; 1 = highest)

qual_df (optional; can be empty):
    - UserId, CourseId, qualified, taught_before (values: 1/0, y/n/true/false)

overrides_df (optional; can be empty):
    - UserId, CourseId, OfferingId, SectionLabel, fix_assign, forbid (1/0,y/n/true/false)

Return DataFrame columns:
    - SemesterId, Year, OfferingId, CourseId, CourseName, Section, AssignedFaculty
"""

from __future__ import annotations

import re
import random
from typing import Dict, Tuple, List, Optional, Iterable

import pandas as pd

# ------------------------------
# CONFIGURATION (for CLI mode)
# ------------------------------
INPUT_XLSX = "Mock Data_from_SQL_ready.xlsx"
OUTPUT_PREFIX = "Schedule_Result"
QUAL_MODE = "lenient"  # when no explicit qual/experience, treat everyone as qualified

# Default caps & weights
MAX_PER_SEMESTER_DEFAULT = 2
MAX_NON_ELECTIVE_PER_YEAR_DEFAULT = 3
W_PREF_DEFAULT = 1000
W_EXP_DEFAULT = 100
W_DEM_DEFAULT = 1


# ------------------------------
# TEXT HELPERS
# ------------------------------
def _norm(s: object) -> str:
    """Lowercases and strips non [a-z0-9 + - space] to normalize for keyword matching."""
    return re.sub(r"[^a-z0-9\s\-\+]", " ", str(s or "").lower()).strip()


def _split_keywords(s: object) -> List[str]:
    """Split on common separators and whitespace; keep tokens length >= 3."""
    tokens = re.split(r"[,/;|]\s*|\s+", _norm(s))
    return [t for t in tokens if len(t) >= 3]


def course_keywords(course_name: object, course_category: object = "") -> List[str]:
    """Derive a small, normalized keyword set from course metadata."""
    kws = set(_split_keywords(course_name))
    if pd.notna(course_category) and str(course_category).strip():
        kws |= set(_split_keywords(course_category))

    name_norm = _norm(course_name)
    # add some useful multiword tokens
    if "cyber" in name_norm and "security" in name_norm:
        kws.add("cyber security")
    if "machine" in name_norm and "learning" in name_norm:
        kws.add("machine learning")
    if "artificial" in name_norm and "intelligence" in name_norm:
        kws.add("artificial intelligence")
    return list(kws)


def experience_keywords(experience: object) -> List[str]:
    """
    Split CV-like text on commas, keep tokens >=3 chars, also retain normalized phrases for substring match.
    """
    phrases = [t.strip() for t in str(experience or "").split(",") if t.strip()]
    tokens = set()
    for p in phrases:
        tokens |= set(_split_keywords(p))
        tokens.add(_norm(p))
    return [t for t in tokens if len(t) >= 3]


# ------------------------------
# LOAD FROM EXCEL (CLI mode)
# ------------------------------
def load_all(xlsx_path: str):
    """Load Excel workbook and apply the same shaping used in the Flask integration."""
    sem_df = pd.read_excel(xlsx_path, sheet_name="Semester")
    course_df = pd.read_excel(xlsx_path, sheet_name="Course")
    offer_df = pd.read_excel(xlsx_path, sheet_name="Course_Offering")
    user_df = pd.read_excel(xlsx_path, sheet_name="User")
    pref_df = pd.read_excel(xlsx_path, sheet_name="Faculty_Preference")

    # optional tabs
    try:
        qual_df = pd.read_excel(xlsx_path, sheet_name="Qualification")
    except Exception:
        qual_df = pd.DataFrame(columns=["UserId", "CourseId", "qualified", "taught_before"])
    try:
        ov_df = pd.read_excel(xlsx_path, sheet_name="Overrides")
    except Exception:
        ov_df = pd.DataFrame(columns=["UserId", "CourseId", "OfferingId", "SectionLabel", "fix_assign", "forbid"])

    # harmonize types/flags
    sem_df["SemesterId_str"] = sem_df["SemesterId"].astype(str)
    offer_df["SemesterId_str"] = offer_df["SemesterId"].astype(str)

    # active semesters (treat 'T', 'True', 'Y', '1' as active)
    active = sem_df[sem_df["IsActive"].astype(str).str.upper().str.startswith(("T", "Y", "1"))]
    active_ids = set(active["SemesterId_str"])

    # keep only offerings in active semesters and with >0 sections
    offers = offer_df[offer_df["SemesterId_str"].isin(active_ids)].copy()
    offers = offers[offers["SectionQuantity"].fillna(0).astype(int) > 0]

    # filter preferences to active semesters too
    pref_df["SemesterId_str"] = pref_df["SemesterId"].astype(str)
    prefs = pref_df[pref_df["SemesterId_str"].isin(active_ids)].copy()

    # derive year on offers
    year_map = sem_df.set_index("SemesterId_str")["Year"].to_dict()
    offers["Year"] = offers["SemesterId_str"].map(year_map)

    # infer elective if not present
    if "is_elective" not in course_df.columns:
        course_df["is_elective"] = ~course_df.get("CourseCategory", "").astype(str)\
            .str.lower().str.contains("core", na=False)

    # faculty only
    faculty_df = user_df[(user_df.get("Identity", "").astype(str).str.lower() == "faculty")].copy()

    return sem_df, course_df, offers, prefs, faculty_df, qual_df, ov_df


# ------------------------------
# BUILD UTILITIES
# ------------------------------
def materialize_sections(offers: pd.DataFrame) -> pd.DataFrame:
    """Expand each offering into one row per section, adding SectionLabel S1..Sn."""
    rows = []
    for _, r in offers.iterrows():
        qty = int(pd.to_numeric(r.get("SectionQuantity", 0), errors="coerce") or 0)
        for s in range(1, qty + 1):
            rows.append({
                "SemesterId": r["SemesterId"],
                "SemesterId_str": r.get("SemesterId_str", str(r["SemesterId"])),
                "Year": r.get("Year"),
                "OfferingId": r["OfferingId"],
                "CourseId": r["CourseId"],
                "SectionLabel": f"S{s}",
            })
    return pd.DataFrame(rows)


def build_pref_weights_ranked(prefs: pd.DataFrame) -> Dict[Tuple[str, str, str], int]:
    """
    Convert ranked preferences into scores where rank 1 is highest.
    Score per (UserId, CourseId, SemesterId_str).
    """
    if prefs is None or prefs.empty:
        return {}
    P = prefs.copy()
    if "SemesterId_str" not in P.columns:
        P["SemesterId_str"] = P["SemesterId"].astype(str)
    P["priority_rank"] = pd.to_numeric(P["priority_rank"], errors="coerce").fillna(0).astype(int)
    P["max_rank_term"] = P.groupby(["UserId", "SemesterId_str"])["priority_rank"]\
                          .transform("max").replace(0, 1)
    # higher score for better rank: (max+1 - rank)
    P["pref_score"] = (P["max_rank_term"] + 1 - P["priority_rank"]).clip(lower=0).astype(int)

    K: Dict[Tuple[str, str, str], int] = {}
    for _, r in P.iterrows():
        K[(str(r["UserId"]), str(r["CourseId"]), str(r["SemesterId_str"]))] = int(r["pref_score"])
    return K


def build_qualification_maps(course_df: pd.DataFrame,
                             faculty_df: pd.DataFrame,
                             qual_df: pd.DataFrame) -> Tuple[Dict[Tuple[str, str], int],
                                                             Dict[Tuple[str, str], int]]:
    """
    Returns:
      qualified[(UserId, CourseId)] = 1/0
      taught_before[(UserId, CourseId)] = 1/0
    """
    q_lookup: Dict[Tuple[str, str], Dict[str, int]] = {}
    if qual_df is not None and not qual_df.empty:
        q = qual_df.rename(columns=str.strip).copy()
        for _, r in q.iterrows():
            key = (str(r.get("UserId")), str(r.get("CourseId")))
            qualified_flag = str(r.get("qualified", "")).lower() in ("1", "y", "yes", "true", "t")
            taught_flag = str(r.get("taught_before", "")).lower() in ("1", "y", "yes", "true", "t")
            q_lookup[key] = {"qualified": int(qualified_flag), "taught_before": int(taught_flag)}

    # derive keywords for heuristic qualification if needed
    course_kw = {str(c["CourseId"]): set(course_keywords(c.get("CourseName", ""), c.get("CourseCategory", "")))
                 for _, c in course_df.iterrows()}
    exp_kw = {str(f["UserId"]): set(experience_keywords(f.get("Experience", "")))
              for _, f in faculty_df.iterrows()}

    faculty_ids = [str(x) for x in faculty_df["UserId"].tolist()]
    course_ids = [str(x) for x in course_df["CourseId"].tolist()]

    no_qual_rows = len(q_lookup) == 0
    # Safe check for empty experience values
    experience_values = faculty_df.get("Experience", pd.Series(dtype=object))
    if experience_values.empty:
        all_exp_blank = True
    else:
        all_exp_blank = all(not (str(e or "").strip()) for e in experience_values.tolist())
    use_lenient = (QUAL_MODE == "lenient") and no_qual_rows and all_exp_blank

    qualified: Dict[Tuple[str, str], int] = {}
    taught_before: Dict[Tuple[str, str], int] = {}

    for p in faculty_ids:
        for c in course_ids:
            key = (p, c)
            if key in q_lookup:
                qualified[key] = q_lookup[key]["qualified"]
                taught_before[key] = q_lookup[key]["taught_before"]
            else:
                if use_lenient:
                    qualified[key] = 1
                    taught_before[key] = 0
                else:
                    ek = exp_kw.get(p, set())
                    ck = course_kw.get(c, set())
                    # substring-friendly overlap (simple heuristic)
                    ok = 1 if ek and ck and any((e in t or t in e) for e in ek for t in ck) else 0
                    qualified[key] = ok
                    taught_before[key] = 0

    if use_lenient:
        print("[QUAL] Lenient fallback active — everyone qualified.")
    return qualified, taught_before


def demand_weights(sections: pd.DataFrame) -> Dict[str, int]:
    """Weight per course by number of sections."""
    counts = sections["CourseId"].astype(str).value_counts().to_dict()
    return counts


# ------------------------------
# GREEDY SCHEDULER
# ------------------------------
def solve_greedy(course_df: pd.DataFrame,
                 offers: pd.DataFrame,
                 faculty_df: pd.DataFrame,
                 prefs: pd.DataFrame,
                 qual_df: Optional[pd.DataFrame],
                 overrides_df: Optional[pd.DataFrame],
                 caps: Tuple[int, int] = (MAX_PER_SEMESTER_DEFAULT, MAX_NON_ELECTIVE_PER_YEAR_DEFAULT),
                 weights: Tuple[int, int, int] = (W_PREF_DEFAULT, W_EXP_DEFAULT, W_DEM_DEFAULT),
                 seed: Optional[int] = None) -> pd.DataFrame:
    """
    Core greedy assignment loop. Scores candidates then enforces caps while assigning.

    caps    = (MAX_PER_SEMESTER, MAX_NON_ELECTIVE_PER_YEAR)
    weights = (W_PREF, W_EXP, W_DEM)
    """
    if seed is not None:
        random.seed(seed)

    # Filter just faculty if Identity exists
    if "Identity" in faculty_df.columns and not faculty_df.empty:
        faculty_mask = faculty_df["Identity"].astype(str).str.lower() == "faculty"
        faculty_df = faculty_df[faculty_mask].copy()

    # Ensure elective flag exists
    if "is_elective" not in course_df.columns:
        course_df = course_df.copy()
        course_df["is_elective"] = ~course_df.get("CourseCategory", "").astype(str)\
            .str.lower().str.contains("core", na=False)

    # Normalize ids to strings where we need dict keys
    offers = offers.copy()
    if "SemesterId_str" not in offers.columns:
        offers["SemesterId_str"] = offers["SemesterId"].astype(str)

    sections = materialize_sections(offers)
    sec = sections.merge(
        course_df[["CourseId", "CourseName", "is_elective"]],
        on="CourseId", how="left"
    )

    pref_score = build_pref_weights_ranked(prefs)
    qualified, taught_before = build_qualification_maps(course_df, faculty_df, qual_df or pd.DataFrame())
    dem_w = demand_weights(sec)

    # Parse overrides
    fix_assign: set[Tuple[str, str, str, str]] = set()
    forbid: set[Tuple[str, str, str, str]] = set()
    if overrides_df is not None and not overrides_df.empty:
        for _, r in overrides_df.iterrows():
            p = str(r.get("UserId", ""))
            c = str(r.get("CourseId", ""))
            o = str(r.get("OfferingId", ""))
            s = str(r.get("SectionLabel", ""))
            if str(r.get("fix_assign", "")).lower() in ("1", "y", "yes", "true", "t"):
                fix_assign.add((p, c, o, s))
            if str(r.get("forbid", "")).lower() in ("1", "y", "yes", "true", "t"):
                forbid.add((p, c, o, s))

    faculty_ids = [str(x) for x in faculty_df["UserId"].tolist()]

    MAX_PER_SEMESTER, MAX_NON_ELECTIVE_PER_YEAR = caps
    W_PREF, W_EXP, W_DEM = weights[:3]

    cap_sem: Dict[Tuple[str, str], int] = {(p, sem): 0 for p in faculty_ids for sem in sec["SemesterId_str"].unique()}
    years = [y for y in sec["Year"].dropna().unique().tolist() if pd.notna(y)]  # filter NaN
    cap_year_core: Dict[Tuple[str, int], int] = {(p, int(y)): 0 for p in faculty_ids for y in years}

    assigned: Dict[int, str] = {}

    # Assignment loop
    for i in sec.index:
        c = str(sec.at[i, "CourseId"])
        o = str(sec.at[i, "OfferingId"])
        s = str(sec.at[i, "SectionLabel"])
        sem = str(sec.at[i, "SemesterId_str"])
        yr = sec.at[i, "Year"]
        yr_int = int(yr) if pd.notna(yr) else None
        elec = bool(sec.at[i, "is_elective"]) is True

        # Fixed override?
        forced = [p for (p, cc, oo, ss) in fix_assign if cc == c and oo == o and ss == s]
        if forced:
            chosen = forced[0]
            assigned[i] = chosen
            cap_sem[(chosen, sem)] = cap_sem.get((chosen, sem), 0) + 1
            if not elec and yr_int is not None:
                cap_year_core[(chosen, yr_int)] = cap_year_core.get((chosen, yr_int), 0) + 1
            continue

        candidates: List[Tuple[int, str]] = []

        for p in faculty_ids:
            if (p, c, o, s) in forbid:
                continue
            if qualified.get((p, c), 0) == 0:
                continue
            if cap_sem.get((p, sem), 0) >= MAX_PER_SEMESTER:
                continue
            if (not elec) and (yr_int is not None) and cap_year_core.get((p, yr_int), 0) >= MAX_NON_ELECTIVE_PER_YEAR:
                continue

            score = (
                W_PREF * int(pref_score.get((p, c, sem), 0))
                + W_EXP * int(taught_before.get((p, c), 0))
                + W_DEM * int(dem_w.get(c, 1))
            )
            candidates.append((-score, p))  # negative so that min() picks highest score

        if not candidates:
            # No valid candidates; force-assign to any faculty with available semester cap (soft fail-safe)
            eligible = [p for p in faculty_ids if cap_sem.get((p, sem), 0) < MAX_PER_SEMESTER]
            chosen = random.choice(eligible or faculty_ids)
        else:
            candidates.sort()
            chosen = candidates[0][1]

        assigned[i] = chosen
        cap_sem[(chosen, sem)] = cap_sem.get((chosen, sem), 0) + 1
        if not elec and yr_int is not None:
            cap_year_core[(chosen, yr_int)] = cap_year_core.get((chosen, yr_int), 0) + 1

    # Build output
    out = []
    for i in sec.index:
        out.append({
            "SemesterId": sec.at[i, "SemesterId"],
            "Year": sec.at[i, "Year"],
            "OfferingId": sec.at[i, "OfferingId"],
            "CourseId": sec.at[i, "CourseId"],
            "CourseName": sec.at[i, "CourseName"],
            "Section": sec.at[i, "SectionLabel"],
            "AssignedFaculty": assigned[i],
        })
    return pd.DataFrame(out)


# ------------------------------
# OUTPUT (CLI mode)
# ------------------------------
def write_output(df: pd.DataFrame, name: str) -> None:
    path = f"{OUTPUT_PREFIX}_{name}.xlsx"
    df.to_excel(path, index=False)
    print(f"✅ Saved {path}")


def run_variant(name: str,
                caps: Tuple[int, int],
                weights: Tuple[int, int, int],
                seed: Optional[int]) -> None:
    sem_df, course_df, offers, prefs, faculty_df, qual_df, ov_df = load_all(INPUT_XLSX)
    result = solve_greedy(course_df, offers, faculty_df, prefs, qual_df, ov_df,
                          caps=caps, weights=weights, seed=seed)
    write_output(result, name)


def main() -> None:
    # Four illustrative variants, matching your earlier design
    run_variant("V1", (2, 3), (1000, 100, 1), 11)
    run_variant("V2", (2, 3), (2000, 100, 1), 22)
    run_variant("V3", (2, 3), (1000, 200, 1), 33)
    run_variant("V4", (2, 3), (1000, 100, 1), 44)


if __name__ == "__main__":
    main()


__all__ = [
    "solve_greedy",
    "load_all",
    "materialize_sections",
    "build_pref_weights_ranked",
    "build_qualification_maps",
    "demand_weights",
]
