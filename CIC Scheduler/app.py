# app.py — CIC Course Scheduler (Flask + MySQL + pandas)
# - Uses .env via config.py for secrets and DB
# - Instructor: submit preferences
# - Admin: review submissions, notify, generate schedule, view schedule
# - Accepts {preferences:[...]} (old) and {items:[...]} (new)
# - Supports ALPHANUMERIC course IDs and STRING semesterId
# - Robust scheduler call to avoid pandas "truth value" ambiguity

import os
import re
from collections import Counter
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, session, abort, jsonify

try:
    from google import genai
    GENAI_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    genai = None
    GENAI_AVAILABLE = False

from config import settings, get_db

# ------------------------------------------------------------------------------
# Flask setup
# ------------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = settings.FLASK_SECRET_KEY

ISSUE_LABELS: Dict[str, str] = {
    "unassigned": "No instructor assigned — section still needs coverage.",
    "imbalance": "Workload imbalance — instructor already has significantly more sections.",
    "overload": "Faculty overload — instructor exceeds the safe section limit.",
    "overlap": "Potential overlap — instructor teaches multiple sections of this course.",
}

METHOD_OPTIONS: List[Dict[str, str]] = [
    {"key": "method1", "label": "Method 1 (Strict, Pref > 0)"},
    {"key": "method2", "label": "Method 2 (Strict, No Pref)"},
    {"key": "method3", "label": "Method 3 (Flexible, Core Only)"},
    {"key": "method4", "label": "Method 4 (Flexible, All Sections)"},
]
SUMMARY_METHOD_KEY = "summary"
NAVIGATION_PAGES = METHOD_OPTIONS + [{"key": SUMMARY_METHOD_KEY, "label": "Summary Overview"}]

KPI_ORDER = [
    "Total Assigned Rate",
    "Core Assigned Rate",
    "Elective Assigned Rate",
    "Max Load Achieved",
    "Load Std Dev",
    "Avg Pref Rank",
    "Overall Satisfaction Score",
    "No Preference Rate",
    "Total Sections",
    "Total Assigned",
]

MAX_METHOD_LOAD = 3
FLEXIBLE_MAX_LOAD_CAP = 5

# ------------------------------------------------------------------------------
# DB helpers
# ------------------------------------------------------------------------------
def query_all(sql, params=None):
    cn = get_db()
    try:
        cur = cn.cursor(dictionary=True)
        cur.execute(sql, params or ())
        return cur.fetchall()
    finally:
        try:
            cur.close()
        finally:
            cn.close()

def execute(sql, params=None, many=False):
    cn = get_db()
    try:
        cur = cn.cursor()
        if many and isinstance(params, (list, tuple)):
            cur.executemany(sql, params)
        else:
            cur.execute(sql, params or ())
        cn.commit()
    finally:
        try:
            cur.close()
        finally:
            cn.close()


class SchedulePrepError(Exception):
    """Raised when scheduler inputs are missing or invalid."""
    pass

# ------------------------------------------------------------------------------
# Utilities
# ------------------------------------------------------------------------------
def df(rows):  # list[dict] -> DataFrame
    return pd.DataFrame(rows or [])


def _safe_df(df_like):
    """Return None if df_like is None or an empty DataFrame; else pass-through."""
    if df_like is None:
        return None
    if isinstance(df_like, pd.DataFrame) and df_like.empty:
        return None
    return df_like


def _safe_int(value):
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_percent(value: float) -> str:
    return f"{(value * 100):.1f}%" if value is not None else "0.0%"


def _compute_method_kpi(sem_id: str, method_key: str, label: str) -> Dict[str, str]:
    assignments = query_all("""
        SELECT courseId, courseCategory, priorityRank,
               assignedFacultyUserId
        FROM cic_output_method
        WHERE semesterId=%s AND method=%s
    """, (sem_id, method_key))
    assign_df = pd.DataFrame(assignments)
    total_sections = len(assign_df)
    if total_sections == 0:
        return {
            "Method": label,
            "Total Assigned Rate": "0.0%",
            "Core Assigned Rate": "0.0%",
            "Elective Assigned Rate": "0.0%",
            "Max Load Achieved": "0",
            "Load Std Dev": "0.00",
            "Avg Pref Rank": "0.00",
            "Overall Satisfaction Score": "0.00",
            "No Preference Rate": "0.0%",
            "Total Sections": "0",
            "Total Assigned": "0",
        }

    assign_df["courseCategory"] = assign_df["courseCategory"].fillna("Core").astype(str)
    assign_df["priorityRank"] = pd.to_numeric(assign_df["priorityRank"], errors="coerce")
    assigned_df = assign_df[assign_df["assignedFacultyUserId"].notna()].copy()
    assigned_count = len(assigned_df)

    total_assigned_rate = assigned_count / total_sections if total_sections else 0

    core_df = assign_df[assign_df["courseCategory"].str.lower() == "core"]
    total_core = len(core_df)
    assigned_core = len(core_df[core_df["assignedFacultyUserId"].notna()])
    core_rate = assigned_core / total_core if total_core else 0

    elective_df = assign_df[assign_df["courseCategory"].str.lower() != "core"]
    total_elective = len(elective_df)
    assigned_elective = len(elective_df[elective_df["assignedFacultyUserId"].notna()])
    elective_rate = assigned_elective / total_elective if total_elective else 0

    pref_df = assigned_df[assigned_df["priorityRank"] > 0]
    avg_pref_rank = pref_df["priorityRank"].mean() if not pref_df.empty else 0.0

    priority_series = assign_df["priorityRank"].dropna()
    max_rank = int(priority_series.max()) if not priority_series.empty else 4
    penalty_rank = max_rank + 1

    assigned_df["Satisfaction"] = assigned_df["priorityRank"].fillna(penalty_rank)
    satisfaction_score = assigned_df["Satisfaction"].mean() if not assigned_df.empty else 0.0

    no_pref_rate = (
        assigned_df["priorityRank"].isna().mean() if not assigned_df.empty else 0.0
    )

    load_rows = query_all("""
        SELECT sectionsAssigned
        FROM cic_output_method_load
        WHERE semesterId=%s AND method=%s
    """, (sem_id, method_key))
    load_df = pd.DataFrame(load_rows)
    max_load = int(load_df["sectionsAssigned"].max()) if not load_df.empty else 0
    load_std = float(load_df["sectionsAssigned"].std()) if len(load_df) > 1 else 0.0

    return {
        "Method": label,
        "Total Assigned Rate": _format_percent(total_assigned_rate),
        "Core Assigned Rate": _format_percent(core_rate),
        "Elective Assigned Rate": _format_percent(elective_rate),
        "Max Load Achieved": str(max_load),
        "Load Std Dev": f"{load_std:.2f}",
        "Avg Pref Rank": f"{avg_pref_rank:.2f}",
        "Overall Satisfaction Score": f"{satisfaction_score:.2f}",
        "No Preference Rate": _format_percent(no_pref_rate),
        "Total Sections": str(total_sections),
        "Total Assigned": str(assigned_count),
    }


def compute_kpi_summary(sem_id: str) -> List[Dict[str, str]]:
    summary_rows = []
    for meta in METHOD_OPTIONS:
        summary_rows.append(_compute_method_kpi(sem_id, meta["key"], meta["label"]))
    return summary_rows


def build_kpi_dataframe(summary_rows: List[Dict[str, str]]) -> pd.DataFrame:
    if not summary_rows:
        return pd.DataFrame()
    df = pd.DataFrame(summary_rows)
    if "Method" not in df.columns:
        return pd.DataFrame()
    df = df.set_index("Method").T
    return df


def df_to_markdown(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return ""
    headers = list(df.columns)
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for _, row in df.iterrows():
        values = []
        for h in headers:
            val = row.get(h)
            if pd.isna(val):
                values.append("")
            else:
                values.append(str(val))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def generate_gemini_report(kpi_df: pd.DataFrame) -> Tuple[Optional[str], Optional[str]]:
    if kpi_df is None or kpi_df.empty:
        return None, "KPI data is not available."
    if not GENAI_AVAILABLE:
        return None, "google-genai is not installed. Please install the dependency."

    api_key = settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None, "Gemini API key is not configured. Set GEMINI_API_KEY in the environment."

    os.environ["GEMINI_API_KEY"] = api_key
    try:
        client = genai.Client()
    except Exception as exc:  # pragma: no cover
        return None, f"Failed to initialize Gemini client: {exc}"

    kpi_text = df_to_markdown(kpi_df)
    system_instruction = (
        "You are an expert academic scheduling analyst. "
        "Your task is to analyze four different faculty assignment methodologies and "
        "generate a concise, professional English report for the Academic Dean, "
        "strictly following the provided analysis requirements and report format."
    )

    prompt_template = f"""
    The following table summarizes the Key Performance Indicators (KPIs) for four different assignment methods (Method 1 to Method 4). Note that lower rank scores (Avg Pref Rank, Overall Satisfaction Score) and lower Load Std Dev are generally better.

    **[DATA INPUT]**
    {kpi_text}

    **[ANALYSIS REQUIREMENTS]**
    1.  **Overall Assignment (Coverage):** Compare the Total, Core, and Elective Assigned Rates. Clearly state which method achieved the highest coverage, and highlight the difference between Method 3 (Core-focused) and Method 4 (All-focused).
    2.  **Quality of Assignment (Preference/Satisfaction):** Analyze 'Avg Pref Rank' (preference-only assignments) and 'Overall Satisfaction Score' (all assignments, including penalty for no-preference). Identify the method that best respects faculty preference. Discuss the trade-off between coverage and quality (e.g., does Method 4's high coverage come at the expense of preference quality?).
    3.  **Faculty Load and Equity:** Analyze 'Max Load Achieved' and 'Load Std Dev'. Recommend the method that provides the best balance of equity (low Std Dev) while maintaining efficiency.
    4.  **Conclusion & Recommendation:** Summarize the findings and provide a final recommendation for the most balanced and effective assignment strategy.

    **[REPORT FORMAT]**
    The report must be professional, use clear section headings (like 1. Coverage Analysis, 2. Quality Analysis, etc.), and be written entirely in English.
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt_template,
            config=genai.types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2,
            ),
        )
        report_text = getattr(response, "text", None)
    except Exception as exc:  # pragma: no cover
        return None, f"Gemini API error: {exc}"

    if not report_text:
        return None, "Gemini response was empty."
    return report_text, None

def get_active_semester():
    """
    Prefer explicit active flag (semesterIsActive truthy),
    else pick the latest by ORDER. Works with string ids like '2025-03'.
    """
    rows = query_all("SELECT * FROM cic_semester ORDER BY semesterId DESC")
    chosen = None
    for r in rows:
        if str(r.get("semesterIsActive", "")).upper().startswith(("T", "Y", "1")):
            chosen = r
            break
    if not chosen and rows:
        chosen = rows[0]
    return chosen

def login_required(role=None):
    def deco(fn):
        def wrapper(*args, **kwargs):
            if "user" not in session:
                return redirect(url_for("login"))
            if role and session["user"].get("userRole") != role:
                abort(403)
            return fn(*args, **kwargs)
        wrapper.__name__ = fn.__name__
        return wrapper
    return deco

# ------------------------------------------------------------------------------
# Column normalization (case/underscore-insensitive)
# ------------------------------------------------------------------------------
def _normkey(s: str) -> str:
    return re.sub(r'[^a-z0-9]', '', str(s).lower())

_CANON_SPEC = {
    # semester
    "SemesterId":      ["semesterId", "SemesterID", "semester_id", "termId", "term_id", "TermID"],
    "Year":            ["Year", "semesterYear", "semester_year", "AY", "academic_year"],
    "IsActive":        ["IsActive", "semesterIsActive", "semester_is_active", "active", "is_active", "ActiveFlag"],
    # offering
    "OfferingId":      ["offeringId", "OfferingID", "offering_id", "sectionOfferingId", "section_offering_id"],
    "CourseId":        ["courseId", "CourseID", "course_id", "cid"],
    "SectionQuantity": ["sectionQuantity", "SectionQuantity", "section_quantity", "sections", "num_sections"],
    # course
    "CourseName":      ["courseTitle", "CourseName", "course_name", "title", "name"],
    "CourseCategory":  ["courseCategory", "CourseCategory", "course_category", "category"],
    # prefs/user
    "UserId":          ["facultyUserId", "userId", "UserID", "user_id", "uid"],
    "priority_rank":   ["priorityRank", "priority_rank", "rank", "preference_rank"],
    "UserName":        ["userName", "UserName", "user_name", "fullName", "full_name"],
    "UserEmail":       ["userEmail", "UserEmail", "user_email", "email"],
    "Identity":        ["Identity", "role", "Role"],
    "Experience":      ["facultyExperience", "Experience", "experience_text", "cv"],
}

def normalize_cols(df_in: pd.DataFrame) -> pd.DataFrame:
    if df_in is None or df_in.empty:
        return df_in
    df2 = df_in.copy()
    src = {_normkey(c): c for c in df2.columns}
    renames = {}
    for canon, variants in _CANON_SPEC.items():
        if canon in df2.columns:
            continue
        for v in variants:
            k = _normkey(v)
            if k in src:
                renames[src[k]] = canon
                break
    return df2.rename(columns=renames)

def require(df_in: pd.DataFrame, cols: list, tag: str):
    missing = [c for c in cols if c not in (df_in.columns if df_in is not None else [])]
    if missing:
        raise KeyError(f"[{tag}] Missing required columns {missing}. Got: {list(df_in.columns) if df_in is not None else []}")


def _load_uploaded_preferences(file_storage):
    """Read uploaded Excel or CSV file into DataFrame."""
    if not file_storage or not getattr(file_storage, "filename", None):
        raise ValueError("No file provided.")

    name = (file_storage.filename or "").lower()
    stream = getattr(file_storage, "stream", file_storage)

    try:
        if name.endswith((".csv", ".txt")):
            df_out = pd.read_csv(stream)
        elif name.endswith((".xlsx", ".xls")):
            df_out = pd.read_excel(stream)
        else:
            raise ValueError("Unsupported file type. Please upload a CSV or Excel file.")
    finally:
        try:
            stream.seek(0)
        except Exception:
            pass

    return df_out


def _schedule_analysis(rows):
    """Compute lightweight pros/cons for the generated schedule."""
    total_sections = len(rows)
    if total_sections == 0:
        return {
            "summary": {
                "total_sections": 0,
                "assigned_sections": 0,
                "coverage_pct": 0.0,
                "instructor_count": 0,
            },
            "pros": [],
            "cons": ["No AI-generated schedules are available yet."],
            "notes": [],
            "unassigned": [],
            "issues_by_row": {},
        }

    assigned_faculty = []
    unassigned_rows = []
    rows_by_faculty: Dict[str, List[dict]] = {}
    combos_by_faculty_course: Dict[Tuple[str, str], List[dict]] = {}
    issue_map: Dict[str, set] = {}

    def add_issue(row: dict, code: str):
        key = f"{row.get('courseId')}|{row.get('section')}"
        issue_map.setdefault(key, set()).add(code)

    for r in rows:
        faculty_label = (r.get("facultyName") or "").strip()
        if not faculty_label and r.get("assignedFacultyUserId"):
            faculty_label = f"Faculty #{r['assignedFacultyUserId']}"
        if faculty_label:
            assigned_faculty.append(faculty_label)
            rows_by_faculty.setdefault(faculty_label, []).append(r)
            combos_by_faculty_course.setdefault((faculty_label, str(r.get("courseId"))), []).append(r)
        else:
            unassigned_rows.append(r)
            add_issue(r, "unassigned")

    assigned_sections = total_sections - len(unassigned_rows)
    coverage_pct = round((assigned_sections / total_sections) * 100, 1) if total_sections else 0.0

    load_counter = Counter(assigned_faculty)
    instructor_count = len(load_counter)

    pros, cons, notes = [], [], []

    if coverage_pct == 100.0:
        pros.append("All sections are assigned to faculty members.")
    else:
        cons.append(f"{len(unassigned_rows)} section(s) still need an instructor.")

    if load_counter:
        max_faculty, max_sections = load_counter.most_common(1)[0]
        min_sections = min(load_counter.values())
        avg_sections = assigned_sections / instructor_count if instructor_count else 0

        if max_sections - min_sections <= 1:
            pros.append("Teaching load is balanced across assigned faculty (range within ±1 section).")
        elif max_sections - min_sections >= 3:
            cons.append(
                f"Workload imbalance detected: {max_faculty} has {max_sections} sections versus {min_sections} at the low end."
            )
            for row in rows_by_faculty.get(max_faculty, []):
                add_issue(row, "imbalance")
        if max_sections >= 4:
            cons.append(f"{max_faculty} is carrying {max_sections} sections; consider redistributing load.")
            for row in rows_by_faculty.get(max_faculty, []):
                add_issue(row, "overload")
        else:
            notes.append(
                f"Average assigned load is {avg_sections:.1f} section(s) across {instructor_count} faculty members."
            )

    overlap_flag = False
    for (faculty, course_id), course_rows in combos_by_faculty_course.items():
        if faculty and len(course_rows) > 1:
            overlap_flag = True
            for row in course_rows:
                add_issue(row, "overlap")
    if overlap_flag:
        cons.append("Potential overlap: some instructors are assigned multiple sections of the same course.")

    if unassigned_rows:
        sample = ", ".join(
            f"{r['courseId']} (Section {r['section']})" for r in unassigned_rows[:3]
        )
        cons.append(f"Unassigned sections include: {sample}.")

    return {
        "summary": {
            "total_sections": total_sections,
            "assigned_sections": assigned_sections,
            "coverage_pct": coverage_pct,
            "instructor_count": instructor_count,
        },
        "pros": pros,
        "cons": cons,
        "notes": notes,
        "unassigned": unassigned_rows,
        "issues_by_row": {k: sorted(v) for k, v in issue_map.items()},
    }


def ensure_method_tables():
    execute("""
        CREATE TABLE IF NOT EXISTS cic_output_method (
            id INT AUTO_INCREMENT PRIMARY KEY,
            semesterId VARCHAR(64) NOT NULL,
            method VARCHAR(32) NOT NULL,
            offeringId VARCHAR(64) NOT NULL,
            courseId VARCHAR(64) NOT NULL,
            courseTitle VARCHAR(255),
            sectionId VARCHAR(16) NOT NULL,
            totalSections INT,
            courseCategory VARCHAR(64),
            assignedFacultyUserId INT NULL,
            facultyName VARCHAR(255),
            priorityRank INT NULL,
            UNIQUE KEY uniq_method_section (semesterId, method, offeringId, sectionId)
        )
    """)
    execute("""
        CREATE TABLE IF NOT EXISTS cic_output_method_load (
            id INT AUTO_INCREMENT PRIMARY KEY,
            semesterId VARCHAR(64) NOT NULL,
            method VARCHAR(32) NOT NULL,
            facultyUserId INT NOT NULL,
            sectionsAssigned INT NOT NULL,
            UNIQUE KEY uniq_method_load (semesterId, method, facultyUserId)
        )
    """)


def clear_method_data(sem_id: str, method_key: str) -> None:
    execute("DELETE FROM cic_output_method WHERE semesterId=%s AND method=%s", (sem_id, method_key))
    execute("DELETE FROM cic_output_method_load WHERE semesterId=%s AND method=%s", (sem_id, method_key))


def _load_scheduler_frames(sem_id: str) -> Dict[str, pd.DataFrame]:
    course_df = df(query_all("SELECT courseId, courseTitle, courseCategory FROM cic_course"))
    offer_df = df(query_all("""
        SELECT offeringId, courseId, semesterId, sectionQuantity
        FROM cic_courseoffering
        WHERE semesterId=%s
    """, (sem_id,)))
    faculty_df = df(query_all("""
        SELECT facultyUserId, COALESCE(facultyExperience, '') AS facultyExperience
        FROM cic_facultyprofile
    """))
    preference_df = df(query_all("""
        SELECT facultyUserId, courseId, semesterId, priorityRank
        FROM cic_facultypreference
        WHERE semesterId=%s
    """, (sem_id,)))

    if offer_df is None or offer_df.empty:
        raise SchedulePrepError("No course offerings found for this semester. Add rows to cic_courseoffering and try again.")

    if course_df is None or course_df.empty:
        raise SchedulePrepError("No courses defined in cic_course.")

    if preference_df is None or preference_df.empty:
        preference_df = pd.DataFrame(columns=["facultyUserId", "courseId", "semesterId", "priorityRank"])
    if faculty_df is None or faculty_df.empty:
        raise SchedulePrepError("No faculty profiles found. Add entries to cic_facultyprofile.")

    sections_df = _build_sections_dataframe(offer_df, course_df)
    indicator_df = _build_indicator_dataframe(preference_df, faculty_df, sections_df["courseId"].unique(), sem_id)

    return {
        "sections": sections_df,
        "indicator": indicator_df,
        "preferences": preference_df,
        "course_titles": {str(r["courseId"]): r.get("courseTitle", "") for _, r in course_df.iterrows()},
    }


def _build_sections_dataframe(offer_df: pd.DataFrame, course_df: pd.DataFrame) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    course_category_map = course_df.set_index("courseId")["courseCategory"].to_dict()
    course_title_map = course_df.set_index("courseId")["courseTitle"].to_dict()

    for _, row in offer_df.iterrows():
        qty = int(pd.to_numeric(row.get("sectionQuantity", 0), errors="coerce") or 0)
        if qty <= 0:
            continue
        for idx in range(1, qty + 1):
            rows.append({
                "offeringId": str(row.get("offeringId")),
                "courseId": str(row.get("courseId")),
                "semesterId": str(row.get("semesterId")),
                "sectionId": f"S{idx}",
                "total_sections": qty,
                "courseCategory": course_category_map.get(row.get("courseId"), "Core"),
                "courseTitle": course_title_map.get(row.get("courseId"), ""),
            })

    sections_df = pd.DataFrame(rows)
    if sections_df.empty:
        raise SchedulePrepError("No sections to assign after expanding course offerings.")

    sections_df["assignedFacultyId"] = "NOT_ASSIGNED"
    sections_df["category_rank"] = sections_df["courseCategory"].astype(str).str.lower().apply(
        lambda x: 0 if x == "core" else 1
    )
    sections_df = sections_df.sort_values(
        by=["category_rank", "total_sections", "offeringId"],
        ascending=[True, False, True],
        kind="mergesort"
    ).reset_index(drop=True)
    return sections_df


def _build_indicator_dataframe(preference_df: pd.DataFrame,
                               faculty_df: pd.DataFrame,
                               courses_to_assign: np.ndarray,
                               sem_id: str) -> pd.DataFrame:
    indicator_df = preference_df[
        (preference_df.get("semesterId").astype(str) == str(sem_id)) &
        (preference_df.get("courseId").isin(courses_to_assign))
    ].copy()

    faculty_exp_df = faculty_df[["facultyUserId", "facultyExperience"]].copy()
    indicator_df["priorityRank"] = pd.to_numeric(indicator_df.get("priorityRank"), errors="coerce").fillna(0).astype(int)
    max_rank = indicator_df["priorityRank"].max() if not indicator_df.empty else 5
    indicator_df["preference_score"] = (max_rank + 1) - indicator_df["priorityRank"]

    indicator_df = indicator_df.merge(faculty_exp_df, on="facultyUserId", how="left")

    def _experience_score(row):
        experience_str = str(row.get("facultyExperience") or "")
        if not experience_str or experience_str.upper() == "NULL":
            return 0
        pattern = r"\b" + re.escape(str(row.get("courseId"))) + r"\b"
        return 5 if re.search(pattern, experience_str) else 0

    indicator_df["experience_score"] = indicator_df.apply(_experience_score, axis=1)

    indicator_df["final_indicator"] = (
        0.4 * indicator_df["preference_score"] + 0.6 * indicator_df["experience_score"]
    )

    courses_df = pd.DataFrame({"courseId": courses_to_assign})
    faculty_ids = faculty_df[["facultyUserId"]].drop_duplicates()
    courses_df["key"] = 1
    faculty_ids["key"] = 1
    all_assignments = courses_df.merge(faculty_ids, on="key").drop(columns=["key"])

    df_faculty_indicator = all_assignments.merge(
        indicator_df[["facultyUserId", "courseId", "preference_score", "experience_score", "final_indicator"]],
        on=["facultyUserId", "courseId"],
        how="left"
    ).fillna({
        "preference_score": 0,
        "experience_score": 0,
        "final_indicator": 0,
    })

    df_faculty_indicator = df_faculty_indicator.sort_values(
        by=["final_indicator", "facultyUserId"],
        ascending=[False, True]
    ).reset_index(drop=True)
    return df_faculty_indicator


def get_best_candidate_df(course_id: str, df_indicator: pd.DataFrame) -> pd.DataFrame:
    candidates_df = df_indicator[df_indicator["courseId"] == course_id].copy()
    if candidates_df.empty:
        return candidates_df
    rng = np.random.default_rng(seed=37)
    candidates_df["random_sort"] = rng.random(len(candidates_df))
    candidates_df = candidates_df.sort_values(
        by=["final_indicator", "random_sort"],
        ascending=[False, False]
    ).reset_index(drop=True)
    return candidates_df


def run_method_strict(df_sections_in: pd.DataFrame,
                      df_indicator_in: pd.DataFrame,
                      initial_max_load: int,
                      require_pref_score: bool) -> Dict[str, pd.DataFrame]:
    df_sections = df_sections_in.copy()
    df_indicator = df_indicator_in.copy()

    df_indicator["facultyUserId"] = df_indicator["facultyUserId"].astype(str)
    unique_faculty = df_indicator["facultyUserId"].unique()
    faculty_load: Dict[str, int] = {uid: 0 for uid in unique_faculty}

    section_indexes = df_sections.index.tolist()

    for idx in section_indexes:
        section = df_sections.loc[idx]
        course_id = section["courseId"]
        candidates_df = get_best_candidate_df(course_id, df_indicator)
        assigned_faculty = "NOT_ASSIGNED"

        for _, candidate in candidates_df.iterrows():
            candidate_id = str(candidate["facultyUserId"])
            pref_score = candidate.get("preference_score", 0)

            if faculty_load[candidate_id] >= initial_max_load:
                continue
            if require_pref_score and pref_score <= 0:
                continue

            assigned_faculty = candidate_id
            break

        if assigned_faculty != "NOT_ASSIGNED":
            df_sections.at[idx, "assignedFacultyId"] = assigned_faculty
            faculty_load[assigned_faculty] += 1

    load_df = pd.Series(faculty_load, name="sections_assigned").reset_index().rename(
        columns={"index": "facultyUserId"}
    )

    return {
        "assignment_df": df_sections,
        "load_summary": load_df,
    }


def run_method_flexible(df_sections_in: pd.DataFrame,
                        df_indicator_in: pd.DataFrame,
                        initial_max_load: int,
                        max_load_cap: int,
                        include_electives: bool) -> Dict[str, pd.DataFrame]:
    df_sections = df_sections_in.copy()
    df_indicator = df_indicator_in.copy()

    df_indicator["facultyUserId"] = df_indicator["facultyUserId"].astype(str)
    df_sections["courseCategory"] = df_sections["courseCategory"].astype(str)

    unique_faculty = df_indicator["facultyUserId"].unique()
    faculty_load: Dict[str, int] = {uid: 0 for uid in unique_faculty}

    current_cap = max(1, int(initial_max_load))

    while current_cap <= max_load_cap:
        remaining = df_sections[df_sections["assignedFacultyId"] == "NOT_ASSIGNED"]
        if remaining.empty:
            break

        if not include_electives:
            remaining_core = remaining[remaining["courseCategory"].str.lower() == "core"]
            if remaining_core.empty:
                break
            targets = remaining_core.index.tolist()
        else:
            targets = remaining.index.tolist()

        if not targets:
            break

        assigned_this_round = 0

        for idx in targets:
            section = df_sections.loc[idx]
            course_id = section["courseId"]
            candidates_df = get_best_candidate_df(course_id, df_indicator)
            assigned_faculty = "NOT_ASSIGNED"

            for _, candidate in candidates_df.iterrows():
                candidate_id = str(candidate["facultyUserId"])
                if faculty_load.get(candidate_id, 0) >= current_cap:
                    continue

                assigned_faculty = candidate_id
                break

            if assigned_faculty != "NOT_ASSIGNED":
                df_sections.at[idx, "assignedFacultyId"] = assigned_faculty
                faculty_load[assigned_faculty] = faculty_load.get(assigned_faculty, 0) + 1
                assigned_this_round += 1

        if df_sections[df_sections["assignedFacultyId"] == "NOT_ASSIGNED"].empty:
            break

        if not include_electives:
            pending_core = df_sections[
                (df_sections["assignedFacultyId"] == "NOT_ASSIGNED") &
                (df_sections["courseCategory"].str.lower() == "core")
            ]
            if pending_core.empty:
                break

        if assigned_this_round == 0 and current_cap >= max_load_cap:
            break

        current_cap += 1

    load_df = pd.Series(faculty_load, name="sections_assigned").reset_index().rename(
        columns={"index": "facultyUserId"}
    )

    return {
        "assignment_df": df_sections,
        "load_summary": load_df,
    }


def process_method_result(result: Dict[str, pd.DataFrame],
                          preference_df: pd.DataFrame,
                          course_title_map: Dict[str, str]) -> Dict[str, pd.DataFrame]:
    assignment_df = result["assignment_df"].copy()
    assignment_df["courseTitle"] = assignment_df["courseId"].map(course_title_map).fillna("")
    assignment_df["assignedFacultyId"] = assignment_df["assignedFacultyId"].astype(str)

    pref_lookup = preference_df[["facultyUserId", "courseId", "priorityRank"]].copy()
    pref_lookup["facultyUserId"] = pref_lookup["facultyUserId"].astype(str)
    assignment_df = assignment_df.merge(
        pref_lookup,
        left_on=["assignedFacultyId", "courseId"],
        right_on=["facultyUserId", "courseId"],
        how="left"
    ).drop(columns=["facultyUserId"])

    assignment_df["priorityRank"] = pd.to_numeric(assignment_df["priorityRank"], errors="coerce")

    load_df = result["load_summary"].copy()
    load_df["facultyUserId"] = load_df["facultyUserId"].astype(str)

    return {"assignments": assignment_df, "load": load_df}


def compute_method_outputs(sem_id: str) -> Dict[str, Optional[Dict[str, pd.DataFrame]]]:
    frames = _load_scheduler_frames(sem_id)
    sections_df = frames["sections"]
    indicator_df = frames["indicator"]
    preference_df = frames["preferences"]
    course_title_map = frames["course_titles"]

    outputs: Dict[str, Optional[Dict[str, pd.DataFrame]]] = {}

    method1_raw = run_method_strict(sections_df, indicator_df, MAX_METHOD_LOAD, require_pref_score=True)
    outputs["method1"] = process_method_result(method1_raw, preference_df, course_title_map)

    method2_raw = run_method_strict(sections_df, indicator_df, MAX_METHOD_LOAD, require_pref_score=False)
    outputs["method2"] = process_method_result(method2_raw, preference_df, course_title_map)

    method3_raw = run_method_flexible(
        sections_df,
        indicator_df,
        MAX_METHOD_LOAD,
        FLEXIBLE_MAX_LOAD_CAP,
        include_electives=False
    )
    outputs["method3"] = process_method_result(method3_raw, preference_df, course_title_map)

    method4_raw = run_method_flexible(
        sections_df,
        indicator_df,
        MAX_METHOD_LOAD,
        FLEXIBLE_MAX_LOAD_CAP,
        include_electives=True
    )
    outputs["method4"] = process_method_result(method4_raw, preference_df, course_title_map)
    return outputs


def save_method_results(sem_id: str,
                        method_key: str,
                        result_data: Dict[str, pd.DataFrame],
                        name_map: Dict[int, str]) -> None:
    clear_method_data(sem_id, method_key)

    assignment_df = result_data["assignments"]
    load_df = result_data["load"]

    rows_out = []
    for _, row in assignment_df.iterrows():
        faculty_id_raw = row.get("assignedFacultyId")
        faculty_int = _safe_int(faculty_id_raw)
        faculty_name = name_map.get(faculty_int) if faculty_int else None
        rows_out.append((
            sem_id,
            method_key,
            str(row.get("offeringId")),
            str(row.get("courseId")),
            str(row.get("courseTitle", "")),
            str(row.get("sectionId")),
            int(pd.to_numeric(row.get("total_sections"), errors="coerce") or 0),
            str(row.get("courseCategory") or ""),
            faculty_int,
            faculty_name,
            _safe_int(row.get("priorityRank")),
        ))

    if rows_out:
        execute("""
            INSERT INTO cic_output_method
              (semesterId, method, offeringId, courseId, courseTitle, sectionId, totalSections,
               courseCategory, assignedFacultyUserId, facultyName, priorityRank)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, rows_out, many=True)

    load_rows = []
    for _, row in load_df.iterrows():
        fid = _safe_int(row.get("facultyUserId"))
        if fid is None:
            continue
        sections_assigned = int(pd.to_numeric(row.get("sections_assigned"), errors="coerce") or 0)
        load_rows.append((sem_id, method_key, fid, sections_assigned))

    if load_rows:
        execute("""
            INSERT INTO cic_output_method_load
              (semesterId, method, facultyUserId, sectionsAssigned)
            VALUES (%s,%s,%s,%s)
        """, load_rows, many=True)


def recompute_method_loads(sem_id: str, method_key: str) -> None:
    execute("DELETE FROM cic_output_method_load WHERE semesterId=%s AND method=%s", (sem_id, method_key))
    faculty_ids = [r["userId"] for r in query_all("SELECT userId FROM systemuser WHERE userRole='Customer'")]
    counts = {fid: 0 for fid in faculty_ids}

    assigned_counts = query_all("""
        SELECT assignedFacultyUserId AS facultyUserId, COUNT(*) AS cnt
        FROM cic_output_method
        WHERE semesterId=%s AND method=%s AND assignedFacultyUserId IS NOT NULL
        GROUP BY assignedFacultyUserId
    """, (sem_id, method_key))

    for row in assigned_counts:
        fid = row.get("facultyUserId")
        if fid in counts:
            counts[fid] = row.get("cnt", 0)

    rows = [(sem_id, method_key, fid, counts[fid]) for fid in counts]
    if rows:
        execute("""
            INSERT INTO cic_output_method_load
              (semesterId, method, facultyUserId, sectionsAssigned)
            VALUES (%s,%s,%s,%s)
        """, rows, many=True)

# ------------------------------------------------------------------------------
# Routes: auth
# ------------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def root():
    if "user" in session:
        return redirect(url_for("admin_dashboard" if session["user"]["userRole"] == "Admin" else "instructor_preferences"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        user = query_all("SELECT * FROM systemuser WHERE userEmail=%s AND userPassword=%s", (email, pw))
        if user:
            session["user"] = user[0]
            return redirect(url_for("root"))
        error = "Invalid email or password."
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ------------------------------------------------------------------------------
# Routes: instructor
# ------------------------------------------------------------------------------
@app.route("/instructor/preferences", methods=["GET"])
@login_required(role="Customer")
def instructor_preferences():
    u = session["user"]
    sem = get_active_semester()
    courses = query_all("SELECT courseId, courseTitle FROM cic_course ORDER BY courseId")
    existing = query_all("""
        SELECT COUNT(*) AS n
        FROM cic_facultypreference
        WHERE facultyUserId=%s AND semesterId=%s
    """, (u["userId"], str(sem["semesterId"])))
    submitted = existing[0]["n"] > 0 if existing else False
    return render_template("instructor_preferences.html", user=u, courses=courses, submitted=submitted)

# --- Alphanumeric course IDs + tolerant payloads; semesterId is STRING ----------
def _clean_course_id(val):
    """Accept alphanumeric IDs like 'CIC6173' or ints; return clean string or None."""
    if val is None:
        return None
    s = str(val).strip()
    return s or None

def _first_int_from(val):
    """Extract first integer for numeric fields like preference (1–5)."""
    if val is None:
        return None
    if isinstance(val, int):
        return val
    s = str(val).strip()
    m = re.search(r'\d+', s)
    return int(m.group()) if m else None

@app.route("/instructor/preferences", methods=["POST"])
@login_required(role="Customer")
def instructor_submit_preferences():
    data = request.get_json(silent=True) or {}
    user = session["user"]
    sem = get_active_semester()
    if not sem:
        return jsonify({"ok": False, "error": "No active semester configured."}), 400
    sem_id = str(sem["semesterId"])  # string

    # Accept old or new payloads
    raw = None
    if isinstance(data.get("preferences"), list) and data["preferences"]:
        raw = data["preferences"]     # old: [{courseId, courseText, priority}]
    elif isinstance(data.get("items"), list) and data["items"]:
        raw = data["items"]           # new: [{courseId, preference}]
    else:
        return jsonify({"ok": False, "error": "No preferences provided."}), 400

    cleaned, seen, skipped = [], set(), []
    for idx, obj in enumerate(raw, 1):  # 1-based for human-readable indices
        course_val = (obj.get("courseId") or obj.get("course_id") or
                      obj.get("id")       or obj.get("value"))
        pref_val   = (obj.get("preference") or obj.get("priority") or obj.get("pref"))

        cid  = _clean_course_id(course_val)  # string
        pref = _first_int_from(pref_val)     # int 1..5

        if cid is None or pref is None or not (1 <= pref <= 5):
            skipped.append(idx)
            continue

        if cid in seen:
            # keep best (lowest) preference if duplicate appears
            for r in cleaned:
                if r[3] == cid:
                    r[2] = min(r[2], pref)
                    break
            continue
        seen.add(cid)
        cleaned.append([int(user["userId"]), sem_id, pref, cid])

    if not cleaned:
        msg = "No valid preferences found."
        if skipped:
            msg += f" Skipped rows at indices: {skipped}."
        return jsonify({"ok": False, "error": msg}), 400

    # replace prior entries for this instructor & semester
    execute("DELETE FROM cic_facultypreference WHERE facultyUserId=%s AND semesterId=%s",
            (user["userId"], sem_id))
    execute("""
        INSERT INTO cic_facultypreference (facultyUserId, semesterId, priorityRank, courseId)
        VALUES (%s, %s, %s, %s)
    """, cleaned, many=True)

    if skipped:
        return jsonify({"ok": True, "skipped": skipped})
    return jsonify({"ok": True})

# ------------------------------------------------------------------------------
# Routes: admin dashboard + notify
# ------------------------------------------------------------------------------
@app.route("/admin", methods=["GET"])
@login_required(role="Admin")
def admin_dashboard():
    u = session["user"]
    sem = get_active_semester()
    sem_id = str(sem["semesterId"])
    message = request.args.get("message")
    error = request.args.get("error")
    edit_key = request.args.get("edit_key") or ""
    instructors = query_all("""
        SELECT su.userId, su.userName, su.userEmail
        FROM systemuser su
        WHERE su.userRole='Customer'
        ORDER BY su.userName
    """)
    prefs = query_all("""
        SELECT fp.facultyUserId, fp.courseId, fp.priorityRank, c.courseTitle
        FROM cic_facultypreference fp
        JOIN cic_course c ON c.courseId = fp.courseId
        WHERE fp.semesterId = %s
    """, (sem_id,))
    pref_by_user = {}
    for p in prefs:
        pref_by_user.setdefault(p["facultyUserId"], []).append(p)

    table_rows, missing = [], 0
    for ins in instructors:
        items = sorted(pref_by_user.get(ins["userId"], []), key=lambda r: r["priorityRank"])
        if not items:
            missing += 1
            table_rows.append({
                "instructorName": ins["userName"],
                "instructorId": ins["userId"],
                "courseId": "",
                "courseTitle": "",
                "preference": "",
                "hasSubmitted": "No",
            })
            continue

        for pref in items:
            table_rows.append({
                "instructorName": ins["userName"],
                "instructorId": ins["userId"],
                "courseId": pref.get("courseId", ""),
                "courseTitle": pref.get("courseTitle", ""),
                "preference": pref.get("priorityRank", ""),
                "hasSubmitted": "Yes",
                "facultyUserId": pref.get("facultyUserId"),
                "rowKey": f"{ins['userId']}|{pref.get('courseId', '')}"
            })

    return render_template(
        "admin_dashboard.html",
        user=u,
        active_semester=sem,
        table_rows=table_rows,
        missing_count=missing,
        instructor_count=len(instructors),
        preference_count=len(table_rows),
        message=message,
        error=error,
        edit_key=edit_key,
    )


@app.route("/admin/preferences/edit", methods=["POST"])
@login_required(role="Admin")
def admin_edit_preferences():
    sem = get_active_semester()
    if not sem:
        return redirect(url_for("admin_dashboard", error="No active semester configured."))
    sem_id = str(sem["semesterId"])

    action = request.form.get("action") or ""

    def redirect_with(msg=None, err=None):
        params = {}
        if msg:
            params["message"] = msg
        if err:
            params["error"] = err
        return redirect(url_for("admin_dashboard", **params))

    try:
        if action == "delete":
            faculty_user_id = (request.form.get("faculty_user_id") or "").strip()
            course_id = (request.form.get("course_id") or "").strip()
            if not faculty_user_id or not faculty_user_id.isdigit():
                raise ValueError("A numeric faculty user ID is required to remove a preference.")
            if not course_id:
                raise ValueError("Course ID is required to remove a preference.")
            execute(
                "DELETE FROM cic_facultypreference WHERE facultyUserId=%s AND semesterId=%s AND courseId=%s",
                (int(faculty_user_id), sem_id, course_id),
            )
            return redirect_with(msg="Preference removed.")

        if action == "update":
            original_user_id = (request.form.get("original_user_id") or "").strip()
            original_course_id = (request.form.get("original_course_id") or "").strip()
            faculty_user_id = (request.form.get("faculty_user_id") or "").strip()
            course_id = (request.form.get("course_id") or "").strip()
            course_name = (request.form.get("course_name") or "").strip()
            pref_val = request.form.get("preference")

            if not original_user_id.isdigit():
                raise ValueError("Original instructor identifier is missing.")
            if not faculty_user_id or not faculty_user_id.isdigit():
                raise ValueError("Select an instructor to assign the preference.")
            if not original_course_id:
                raise ValueError("Original course identifier is missing.")
            if not course_id:
                raise ValueError("Course ID is required.")

            pref_clean = _first_int_from(pref_val) or 1

            existing = query_all(
                """
                SELECT 1 FROM cic_facultypreference
                 WHERE facultyUserId=%s AND semesterId=%s AND courseId=%s
                """,
                (int(faculty_user_id), sem_id, course_id),
            )
            if existing and (int(faculty_user_id) != int(original_user_id) or course_id != original_course_id):
                raise ValueError("A preference for that instructor and course already exists.")

            execute(
                """
                UPDATE cic_facultypreference
                   SET facultyUserId=%s,
                       courseId=%s,
                       priorityRank=%s
                 WHERE facultyUserId=%s AND semesterId=%s AND courseId=%s
                """,
                (int(faculty_user_id), course_id, pref_clean, int(original_user_id), sem_id, original_course_id),
            )

            if course_name:
                existing_course = query_all("SELECT courseId FROM cic_course WHERE courseId=%s", (course_id,))
                if existing_course:
                    execute("UPDATE cic_course SET courseTitle=%s WHERE courseId=%s", (course_name, course_id))
                else:
                    execute("INSERT INTO cic_course (courseId, courseTitle) VALUES (%s, %s)", (course_id, course_name))

            return redirect_with(msg="Preference updated.")

        if action == "add":
            faculty_user_id = (request.form.get("new_faculty_user_id") or "").strip()
            course_id = (request.form.get("new_course_id") or "").strip()
            course_name = (request.form.get("new_course_name") or "").strip()
            pref_val = request.form.get("new_preference")

            if not faculty_user_id or not faculty_user_id.isdigit():
                raise ValueError("Select an instructor when adding a preference.")
            if not course_id:
                raise ValueError("Course ID is required to add a preference.")

            pref_clean = _first_int_from(pref_val) or 1

            existing = query_all(
                """
                SELECT 1 FROM cic_facultypreference
                 WHERE facultyUserId=%s AND semesterId=%s AND courseId=%s
                """,
                (int(faculty_user_id), sem_id, course_id),
            )
            if existing:
                raise ValueError("Preference already exists for that instructor and course.")

            execute(
                """
                INSERT INTO cic_facultypreference (facultyUserId, semesterId, priorityRank, courseId)
                VALUES (%s, %s, %s, %s)
                """,
                (int(faculty_user_id), sem_id, pref_clean, course_id),
            )

            if course_name:
                existing_course = query_all("SELECT courseId FROM cic_course WHERE courseId=%s", (course_id,))
                if existing_course:
                    execute("UPDATE cic_course SET courseTitle=%s WHERE courseId=%s", (course_name, course_id))
                else:
                    execute("INSERT INTO cic_course (courseId, courseTitle) VALUES (%s, %s)", (course_id, course_name))

            return redirect_with(msg="Preference added.")

        raise ValueError("Unsupported action.")

    except Exception as exc:
        return redirect_with(err=str(exc))


@app.route("/admin/preferences/edit", methods=["GET"])
@login_required(role="Admin")
def admin_edit_preferences_view():
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/upload", methods=["GET", "POST"])
@login_required(role="Admin")
def admin_upload():
    user = session["user"]
    sem = get_active_semester()
    sem_id = str(sem["semesterId"]) if sem else None

    error = None
    result = None

    if request.method == "POST":
        file = request.files.get("preferences_file")
        if not sem_id:
            error = "No active semester is configured."
        elif not file or not file.filename:
            error = "Please choose a CSV or Excel file to upload."
        else:
            try:
                df_in = _load_uploaded_preferences(file)
                df_in = normalize_cols(df_in)
                require(df_in, ["UserEmail", "CourseId", "priority_rank"], "Upload")
            except KeyError as exc:
                error = exc.args[0] if exc.args else str(exc)
            except Exception as exc:
                error = str(exc)
            else:
                df_in["UserEmail"] = df_in["UserEmail"].astype(str).str.strip().str.lower()
                df_in["CourseId"] = df_in["CourseId"].astype(str).str.strip()
                df_in["priority_rank"] = df_in["priority_rank"].apply(_first_int_from)
                df_in = df_in.dropna(subset=["UserEmail", "CourseId"])

                total_rows = len(df_in)
                if total_rows == 0:
                    error = "The uploaded file does not contain any usable rows."
                else:
                    emails = sorted(set(df_in["UserEmail"].dropna()))
                    email_map = {}
                    missing_emails = []
                    if emails:
                        placeholders = ",".join(["%s"] * len(emails))
                        try:
                            rows = query_all(
                                f"SELECT userId, LOWER(userEmail) AS email FROM systemuser WHERE LOWER(userEmail) IN ({placeholders})",
                                tuple(emails),
                            )
                        except Exception as exc:
                            error = f"Failed to look up users: {exc}"
                            rows = []
                        else:
                            email_map = {r["email"]: r["userId"] for r in rows}
                            missing_emails = sorted(set(emails) - set(email_map.keys()))

                    stats = {
                        "total_rows": total_rows,
                        "imported_rows": 0,
                        "skipped_invalid": 0,
                        "skipped_missing_user": 0,
                        "deduped": 0,
                        "missing_emails": missing_emails,
                    }
                    cleaned = {}

                    for _, row in df_in.iterrows():
                        email = row.get("UserEmail")
                        course_id = row.get("CourseId")
                        pref = row.get("priority_rank")
                        uid = email_map.get(email)

                        if not uid:
                            stats["skipped_missing_user"] += 1
                            continue
                        if pref is None or not (1 <= int(pref) <= 5):
                            stats["skipped_invalid"] += 1
                            continue
                        if not course_id:
                            stats["skipped_invalid"] += 1
                            continue

                        pref = int(pref)
                        key = (uid, course_id)
                        prev = cleaned.get(key)
                        if prev is None or pref < prev[2]:
                            cleaned[key] = (uid, sem_id, pref, course_id)
                            if prev is not None:
                                stats["deduped"] += 1
                        else:
                            stats["deduped"] += 1

                    entries = list(cleaned.values())
                    stats["imported_rows"] = len(entries)

                    if entries:
                        try:
                            affected = {e[0] for e in entries}
                            for uid in affected:
                                execute(
                                    "DELETE FROM cic_facultypreference WHERE facultyUserId=%s AND semesterId=%s",
                                    (uid, sem_id),
                                )
                            execute(
                                """
                                    INSERT INTO cic_facultypreference (facultyUserId, semesterId, priorityRank, courseId)
                                    VALUES (%s, %s, %s, %s)
                                """,
                                entries,
                                many=True,
                            )
                        except Exception as exc:
                            error = f"Failed to store preferences: {exc}"
                        else:
                            result = stats
                    else:
                        error = "No valid preference rows were detected in the file."

    return render_template(
        "admin_upload.html",
        user=user,
        active_semester=sem,
        upload_error=error,
        upload_result=result,
    )

@app.route("/admin/notify", methods=["POST"])
@login_required(role="Admin")
def admin_notify():
    sem = get_active_semester()
    sem_id = str(sem["semesterId"])
    instructors = query_all("SELECT su.userId, su.userName, su.userEmail FROM systemuser su WHERE su.userRole='Customer'")
    submitted = query_all("SELECT DISTINCT facultyUserId FROM cic_facultypreference WHERE semesterId = %s", (sem_id,))
    submitted_ids = {r["facultyUserId"] for r in submitted}
    _missing = [i for i in instructors if i["userId"] not in submitted_ids]
    # TODO: send reminder emails to _missing if desired
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/reset/preferences", methods=["POST"])
@login_required(role="Admin")
def admin_reset_preferences():
    sem = get_active_semester()
    if not sem:
        return redirect(url_for("admin_dashboard", message="No active semester configured for reset."))
    sem_id = str(sem["semesterId"])
    execute("DELETE FROM cic_facultypreference WHERE semesterId=%s", (sem_id,))
    return redirect(url_for("admin_dashboard", message="Instructor preferences reset for the active semester."))

# ------------------------------------------------------------------------------
# Routes: generate schedule + view schedule
# ------------------------------------------------------------------------------
@app.route("/admin/generate", methods=["POST"])
@login_required(role="Admin")
def admin_generate():
    sem = get_active_semester()
    if not sem:
        return redirect(url_for("admin_dashboard", message="No active semester available for schedule generation."))
    sem_id = str(sem["semesterId"])

    ensure_method_tables()

    try:
        method_outputs = compute_method_outputs(sem_id)
    except SchedulePrepError as exc:
        for meta in METHOD_OPTIONS:
            clear_method_data(sem_id, meta["key"])
        faculty_options = query_all("""
            SELECT userId, COALESCE(userName, CONCAT('Faculty #', userId)) AS userName, userEmail
            FROM systemuser
            WHERE userRole='Customer'
            ORDER BY userName
        """)
        return render_template(
            "schedule.html",
            rows=[],
            load_summary=[],
            semester=sem,
            message=str(exc),
            current_method="method1",
            current_method_label=METHOD_OPTIONS[0]["label"],
            method_options=METHOD_OPTIONS,
            prev_method=None,
            next_method=METHOD_OPTIONS[1]["key"],
            faculty_options=faculty_options,
            issue_map={},
            issue_labels=ISSUE_LABELS,
        )

    name_map = {r["userId"]: r.get("userName", f"Faculty #{r['userId']}") for r in query_all("SELECT userId, userName FROM systemuser")}

    for meta in METHOD_OPTIONS:
        key = meta["key"]
        result_data = method_outputs.get(key)
        if result_data:
            save_method_results(sem_id, key, result_data, name_map)
        else:
            clear_method_data(sem_id, key)

    return redirect(url_for("admin_schedule", method="method1"))
@app.route("/admin/schedule", methods=["GET"])
@login_required(role="Admin")
def admin_schedule():
    sem = get_active_semester()
    sem_id = str(sem["semesterId"])
    ensure_method_tables()
    nav_pages = NAVIGATION_PAGES
    method_keys = [m["key"] for m in nav_pages]
    method = request.args.get("method", nav_pages[0]["key"])
# fix indentation
    if method not in method_keys:
        method = nav_pages[0]["key"]

    rows = []
    load_rows = []
    issue_map = {}
    kpi_summary = None

    if method != SUMMARY_METHOD_KEY:
        rows = query_all("""
            SELECT offeringId, courseId, semesterId, courseTitle, sectionId, totalSections,
                   courseCategory, assignedFacultyUserId, COALESCE(facultyName, '') AS facultyName,
                   priorityRank
            FROM cic_output_method
            WHERE semesterId=%s AND method=%s
            ORDER BY courseCategory, totalSections DESC, courseId, sectionId
        """, (sem_id, method))

        load_rows = query_all("""
            SELECT facultyUserId, sectionsAssigned
            FROM cic_output_method_load
            WHERE semesterId=%s AND method=%s
            ORDER BY sectionsAssigned DESC, facultyUserId
        """, (sem_id, method))

        analysis_rows = []
        for r in rows:
            analysis_rows.append({
                "courseId": r["courseId"],
                "section": r["sectionId"],
                "courseCategory": r.get("courseCategory"),
                "assignedFacultyUserId": r.get("assignedFacultyUserId"),
                "facultyName": r.get("facultyName", ""),
            })
        if analysis_rows:
            issue_analysis = _schedule_analysis(analysis_rows)
            issue_map = issue_analysis.get("issues_by_row", {})
    else:
        kpi_summary = compute_kpi_summary(sem_id)

    method_index = method_keys.index(method)
    prev_method = method_keys[method_index - 1] if method_index > 0 else None
    next_method = method_keys[method_index + 1] if method_index < len(method_keys) - 1 else None
    current_method_index = method_index + 1
    current_method_label = nav_pages[method_index]["label"]

    faculty_options = query_all("""
        SELECT userId, COALESCE(userName, CONCAT('Faculty #', userId)) AS userName, userEmail
        FROM systemuser
        WHERE userRole='Customer'
        ORDER BY userName
    """)
    message = request.args.get("message")
    return render_template(
        "schedule.html",
        rows=rows,
        load_summary=load_rows,
        kpi_summary=kpi_summary,
        semester=sem,
        message=message,
        current_method=method,
        current_method_label=current_method_label,
        current_method_index=current_method_index,
        nav_pages=nav_pages,
        summary_method_key=SUMMARY_METHOD_KEY,
        kpi_metrics=KPI_ORDER,
        prev_method=prev_method,
        next_method=next_method,
        faculty_options=faculty_options,
        issue_map=issue_map,
        issue_labels=ISSUE_LABELS,
    )


@app.route("/admin/analysis", methods=["GET", "POST"])
@login_required(role="Admin")
def admin_analysis():
    sem = get_active_semester()
    sem_id = str(sem["semesterId"]) if sem else None
    ensure_method_tables()
    method = request.args.get("method", METHOD_OPTIONS[0]["key"])
    method_label = next((m["label"] for m in METHOD_OPTIONS if m["key"] == method), method)

    rows: List[dict] = []
    analysis = None
    ai_report = None
    ai_error = None
    kpi_table_headers: List[str] = []
    kpi_table_rows: List[Dict[str, str]] = []
    kpi_markdown = None

    if sem_id:
        rows = query_all("""
            SELECT courseId, courseTitle, sectionId AS section,
                   assignedFacultyUserId, COALESCE(facultyName, '') AS facultyName
            FROM cic_output_method
            WHERE semesterId=%s AND method=%s
            ORDER BY courseId, section
        """, (sem_id, method))
        analysis = _schedule_analysis(rows)

        summary_rows = compute_kpi_summary(sem_id)
        kpi_df = build_kpi_dataframe(summary_rows)
        if not kpi_df.empty:
            kpi_markdown = df_to_markdown(kpi_df)
            kpi_table_headers = kpi_df.columns.tolist()
            for metric, series in kpi_df.iterrows():
                kpi_table_rows.append({
                    "metric": metric,
                    "values": [series[col] for col in kpi_table_headers],
                })

        if request.method == "POST" and request.form.get("action") == "generate_report":
            ai_report, ai_error = generate_gemini_report(kpi_df)

    return render_template(
        "admin_analysis.html",
        user=session.get("user"),
        semester=sem,
        run_id=method,
        method_label=method_label,
        method_options=METHOD_OPTIONS,
        rows=rows,
        analysis=analysis,
        kpi_table_headers=kpi_table_headers,
        kpi_table_rows=kpi_table_rows,
        kpi_markdown=kpi_markdown,
        ai_report=ai_report,
        ai_error=ai_error,
    )


@app.route("/admin/reset/schedule", methods=["POST"])
@login_required(role="Admin")
def admin_reset_schedule():
    sem = get_active_semester()
    if not sem:
        return redirect(url_for("admin_schedule", message="No active semester configured for reset."))
    sem_id = str(sem["semesterId"])
    ensure_method_tables()
    for meta in METHOD_OPTIONS:
        clear_method_data(sem_id, meta["key"])
    execute("DELETE FROM cic_output WHERE semesterId=%s", (sem_id,))
    return redirect(url_for("admin_schedule", message="Generated schedules cleared."))


@app.route("/admin/schedule/edit", methods=["GET", "POST"])
@login_required(role="Admin")
def admin_edit_schedule():
    if request.method != "POST":
        return redirect(url_for("admin_schedule"))

    data = request.get_json(silent=True) or {}
    sem = get_active_semester()
    if not sem:
        return jsonify({"ok": False, "error": "No active semester available."}), 400
    sem_id = str(sem["semesterId"])

    required = ["methodKey", "offeringId", "originalSection", "courseId", "courseTitle", "section"]
    missing = [k for k in required if not str(data.get(k, "")).strip()]
    if missing:
        return jsonify({"ok": False, "error": f"Missing required field(s): {', '.join(missing)}"}), 400

    method_key = data["methodKey"]
    valid_methods = {m["key"] for m in METHOD_OPTIONS}
    if method_key not in valid_methods:
        return jsonify({"ok": False, "error": "Unknown method key."}), 400
    offering_id = str(data["offeringId"]).strip()
    original_section = str(data["originalSection"]).strip()
    new_section = str(data["section"]).strip()
    course_id = str(data["courseId"]).strip()
    course_title = str(data["courseTitle"]).strip()

    assigned_id_raw = data.get("assignedFacultyUserId")
    assigned_faculty_id = None
    if assigned_id_raw not in (None, "", "null"):
        try:
            assigned_faculty_id = int(assigned_id_raw)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Assigned faculty id must be numeric."}), 400

    faculty_name = str(data.get("facultyName", "") or "").strip()
    if assigned_faculty_id and not faculty_name:
        rec = query_all("SELECT COALESCE(userName, CONCAT('Faculty #', userId)) AS userName FROM systemuser WHERE userId=%s",
                        (assigned_faculty_id,))
        if rec:
            faculty_name = rec[0]["userName"]

    existing = query_all("""
        SELECT offeringId FROM cic_output_method
        WHERE semesterId=%s AND method=%s AND offeringId=%s AND sectionId=%s
    """, (sem_id, method_key, offering_id, original_section))
    if not existing:
        return jsonify({"ok": False, "error": "Schedule row was not found (it may have been deleted)."}), 404

    if assigned_faculty_id:
        pref_lookup = query_all("""
            SELECT priorityRank FROM cic_facultypreference
            WHERE facultyUserId=%s AND semesterId=%s AND courseId=%s
            LIMIT 1
        """, (assigned_faculty_id, sem_id, course_id))
        priority_rank = pref_lookup[0]["priorityRank"] if pref_lookup else None
    else:
        priority_rank = None

    user_row = None
    if assigned_faculty_id:
        rows = query_all("SELECT COALESCE(userName, CONCAT('Faculty #', userId)) AS userName FROM systemuser WHERE userId=%s",
                        (assigned_faculty_id,))
        user_row = rows[0]["userName"] if rows else None

    execute("""
        UPDATE cic_output_method
        SET courseId=%s,
            courseTitle=%s,
            sectionId=%s,
            assignedFacultyUserId=%s,
            facultyName=%s,
            priorityRank=%s
        WHERE semesterId=%s AND method=%s AND offeringId=%s AND sectionId=%s
    """, (
        course_id,
        course_title,
        new_section,
        assigned_faculty_id,
        user_row or faculty_name or None,
        priority_rank,
        sem_id,
        method_key,
        offering_id,
        original_section,
    ))

    recompute_method_loads(sem_id, method_key)

    updated = query_all("""
        SELECT offeringId, courseId, courseTitle, sectionId,
               totalSections, courseCategory,
               assignedFacultyUserId, COALESCE(facultyName, '') AS facultyName,
               priorityRank
        FROM cic_output_method
        WHERE semesterId=%s AND method=%s AND offeringId=%s AND sectionId=%s
        LIMIT 1
    """, (sem_id, method_key, offering_id, new_section))

    if not updated:
        return jsonify({"ok": True, "row": {
            "method": method_key,
            "offeringId": offering_id,
            "courseId": course_id,
            "courseTitle": course_title,
            "sectionId": new_section,
            "totalSections": data.get("totalSections"),
            "courseCategory": data.get("courseCategory"),
            "assignedFacultyUserId": assigned_faculty_id,
            "facultyName": user_row or faculty_name,
            "priorityRank": priority_rank,
        }})

    updated_row = updated[0]
    updated_row["method"] = method_key
    return jsonify({"ok": True, "row": updated_row})



# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
