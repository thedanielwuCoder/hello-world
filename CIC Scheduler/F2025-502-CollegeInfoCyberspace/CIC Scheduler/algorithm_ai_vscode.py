#!/usr/bin/env python3
"""
CIC Scheduler: Data Load, Basic Greedy Assignment, and KPI Report
- Translated all non-English comments to English
- Removed Google Colab specifics (no drive.mount, no "!pip")
- Added a minimal greedy assignment algorithm so the script runs end-to-end
- Made it runnable in VSCode as a standard Python script (Python 3.9+ recommended)

USAGE
-----
1) Create a virtual environment and install dependencies:
   python -m venv .venv
   source .venv/bin/activate   # on Windows: .venv\Scripts\activate
   pip install -r requirements.txt

2) Run the script:
   python scheduler_analysis.py

ENVIRONMENT VARIABLES (optional)
--------------------------------
- HUGGINGFACE_TOKEN : Used if you want to run the AI report section with a private model.
- DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME : Override DB settings from defaults below.

NOTES
-----
- If MySQL is unavailable, the script will raise an error during DB read. You can comment that section
  and use the "Excel" section instead by pointing XLSX_PATH to the right file.
- The script prints progress and KPI summaries to stdout. It also attempts to generate an AI-written
  summary if the Transformers library is available and a model can be loaded.
"""

from __future__ import annotations

import math
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

try:
    from sqlalchemy import create_engine
    import pymysql
    SQL_AVAILABLE = True
except Exception:
    SQL_AVAILABLE = False

XLSX_PATH = os.environ.get("CIC_XLSX_PATH", "")
OUTPUT_DIR = os.environ.get("CIC_OUTPUT_DIR", "Schedule_Results")
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

MAX_LOAD = int(os.environ.get("CIC_MAX_LOAD", "3"))
FLEXIBLE_MAX_LOAD_CAP = int(os.environ.get("CIC_FLEX_LOAD_CAP", "5"))

SHEET_MAP = {
    "semester_df": "CIC_Semester",
    "course_df": "CIC_Course",
    "offer_df": "CIC_CourseOffering",
    "faculty_df": "CIC_FacultyProfile",
    "preference_df": "CIC_FacultyPreference",
}

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "user": os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_PASSWORD", "change_to_your_MySQL_password"),
    "database": os.environ.get("DB_NAME", "user_management"),
}


def log(msg: str) -> None:
    print(msg, flush=True)


def safe_to_markdown(df: pd.DataFrame, head: int = 5) -> str:
    try:
        return df.head(head).to_markdown(index=False)
    except Exception:
        return str(df.head(head))


def load_from_excel(xlsx_path: str) -> Dict[str, pd.DataFrame]:
    if not xlsx_path:
        raise ValueError("XLSX_PATH is empty. Set CIC_XLSX_PATH or edit the script.")
    log(f"--- Starting to read data from Excel: {xlsx_path} ---")
    dataframes: Dict[str, pd.DataFrame] = {}
    for df_var_name, sheet_name in SHEET_MAP.items():
        try:
            df = pd.read_excel(xlsx_path, sheet_name=sheet_name)
            dataframes[df_var_name] = df
            log(f"✅ Loaded sheet '{sheet_name}' -> {df_var_name} (shape={df.shape})")
        except Exception as e:
            log(f"❌ ERROR loading sheet '{sheet_name}': {e}")
            raise
    return dataframes


def load_from_mysql() -> Dict[str, pd.DataFrame]:
    if not SQL_AVAILABLE:
        raise RuntimeError("SQLAlchemy/PyMySQL not available. Install them or switch to Excel loading.")
    database_url = (
        f"mysql+pymysql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@"
        f"{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
    )
    try:
        engine = create_engine(database_url)
        log("✅ MySQL Engine created successfully.")
    except Exception as e:
        log(f"❌ Failed to create MySQL Engine: {e}")
        raise

    table_map = {
        "semester_df": "CIC_Semester",
        "course_df": "CIC_Course",
        "offer_df": "CIC_CourseOffering",
        "faculty_df": "CIC_FacultyProfile",
        "preference_df": "CIC_FacultyPreference",
    }

    dataframes: Dict[str, pd.DataFrame] = {}
    log("\n--- Loading DataFrames from MySQL ---")
    try:
        for df_var_name, table_name in table_map.items():
            sql_query = f"SELECT * FROM {table_name};"
            df = pd.read_sql_query(sql_query, engine)
            dataframes[df_var_name] = df
            log(f"✅ Loaded table '{table_name}' -> {df_var_name} (shape={df.shape})")
    finally:
        engine.dispose()

    log("🎉 All DataFrames loaded from MySQL and assigned successfully!")
    return dataframes


def prepare_sections(semester_df: pd.DataFrame, offer_df: pd.DataFrame, course_df: pd.DataFrame) -> pd.DataFrame:
    try:
        active_semester_id = semester_df[semester_df["semesterIsActive"] == "T"]["semesterId"].iloc[0]
    except IndexError:
        raise RuntimeError("ERROR: Could not find active semester.")

    active_offerings_df = offer_df[offer_df["semesterId"] == active_semester_id].copy()
    list_of_dfs: List[pd.DataFrame] = []
    for _, row in active_offerings_df.iterrows():
        n = int(row["sectionQuantity"])
        if n < 1:
            continue
        temp_df = pd.DataFrame([row] * n)
        temp_df["sectionId"] = [f"S{i}" for i in range(1, n + 1)]
        temp_df["total_sections"] = temp_df["sectionQuantity"]
        list_of_dfs.append(temp_df)

    if not list_of_dfs:
        raise RuntimeError("No sections found to assign (sectionQuantity sums to 0).")

    df_sections_to_assign = pd.concat(list_of_dfs, ignore_index=True)
    df_sections_to_assign = df_sections_to_assign[
        ["offeringId", "courseId", "semesterId", "sectionId", "total_sections"]
    ]

    course_category_map = course_df[["courseId", "courseCategory"]]
    df_sections_to_assign = pd.merge(
        df_sections_to_assign,
        course_category_map,
        on="courseId",
        how="left",
    )

    df_sections_to_assign["assignedFacultyId"] = "NOT_ASSIGNED"
    df_sections_to_assign["category_rank"] = df_sections_to_assign["courseCategory"].apply(
        lambda x: 0 if x == "Core" else 1
    )
    df_sections_to_assign = df_sections_to_assign.sort_values(
        by=["category_rank", "total_sections", "offeringId"],
        ascending=[True, False, True],
        kind="mergesort",
    ).reset_index(drop=True)

    log(f"✅ Final sections DataFrame prepared and sorted: {len(df_sections_to_assign)} sections.")
    log("   Prioritization: Core (large first) -> Elective (large first).")
    return df_sections_to_assign, active_semester_id


def build_faculty_indicators(
    preference_df: pd.DataFrame,
    faculty_df: pd.DataFrame,
    active_semester_id: str | int,
    sections_df: pd.DataFrame,
) -> pd.DataFrame:
    log("--- Indicator Calculation ---")
    courses_to_assign = sections_df["courseId"].unique()
    indicator_df = preference_df[
        (preference_df["semesterId"] == active_semester_id)
        & (preference_df["courseId"].isin(courses_to_assign))
    ].copy()

    faculty_exp_df = faculty_df[["facultyUserId", "facultyExperience"]].copy()
    max_rank = indicator_df["priorityRank"].max() if not indicator_df.empty else 5
    indicator_df["preference_score"] = (max_rank + 1) - indicator_df["priorityRank"]

    indicator_df = pd.merge(indicator_df, faculty_exp_df, on="facultyUserId", how="left")

    def calculate_experience_score(row):
        course_id = str(row["courseId"])
        experience_str = "" if pd.isna(row["facultyExperience"]) else str(row["facultyExperience"])
        if not experience_str or experience_str.upper() == "NULL":
            return 0
        pattern = r"\b" + re.escape(course_id) + r"\b"
        return 5 if re.search(pattern, experience_str) else 0

    indicator_df["experience_score"] = indicator_df.apply(calculate_experience_score, axis=1)
    weight_preference = 0.4
    weight_experience = 0.6
    indicator_df["final_indicator"] = (
        indicator_df["preference_score"] * weight_preference
        + indicator_df["experience_score"] * weight_experience
    )

    all_possible_assignments = pd.DataFrame({"courseId": courses_to_assign}).merge(
        faculty_df[["facultyUserId"]], how="cross"
    )
    df_faculty_indicator = all_possible_assignments.merge(
        indicator_df[["facultyUserId", "courseId", "preference_score", "experience_score", "final_indicator"]],
        on=["facultyUserId", "courseId"],
        how="left",
    ).fillna({"preference_score": 0, "experience_score": 0, "final_indicator": 0})

    df_faculty_indicator = df_faculty_indicator.sort_values(
        by=["final_indicator", "facultyUserId"],
        ascending=[False, True],
    ).reset_index(drop=True)

    log(f"Indicator calculated for {len(df_faculty_indicator)} faculty-course pairs.")
    return df_faculty_indicator


def _greedy_assign(
    sections_df: pd.DataFrame,
    faculty_indicator: pd.DataFrame,
    strict_max_load: int,
    method_id: int,
    flexible_cap: Optional[int] = None,
    core_only_flexible: bool = False,
) -> Dict[str, object]:
    df = sections_df.copy()
    load_counter: Dict[str, int] = {}

    by_course = {}
    for course_id, sub in faculty_indicator.groupby("courseId"):
        if method_id == 1:
            candidates = sub[sub["preference_score"] > 0].sort_values(
                by=["final_indicator", "facultyUserId"], ascending=[False, True]
            )
        else:
            candidates = sub.sort_values(by=["final_indicator", "facultyUserId"], ascending=[False, True])
        by_course[course_id] = candidates

    assigned = 0
    for idx, row in df.iterrows():
        course_id = row["courseId"]
        cat = row.get("courseCategory", None)
        candidates = by_course.get(course_id, pd.DataFrame())

        assigned_faculty = "NOT_ASSIGNED"
        for _, c in candidates.iterrows():
            fid = str(c["facultyUserId"])
            current_load = load_counter.get(fid, 0)
            cap = strict_max_load
            if flexible_cap is not None:
                if method_id == 3 and core_only_flexible:
                    if cat == "Core":
                        cap = flexible_cap
                elif method_id == 4 and not core_only_flexible:
                    cap = flexible_cap

            if current_load < cap:
                assigned_faculty = fid
                load_counter[fid] = current_load + 1
                assigned += 1
                break

        df.at[idx, "assignedFacultyId"] = assigned_faculty

    load_summary = (
        pd.DataFrame(list(load_counter.items()), columns=["facultyUserId", "sections_assigned"])
        if load_counter
        else pd.DataFrame(columns=["facultyUserId", "sections_assigned"])
    )
    method_max = int(load_summary["sections_assigned"].max()) if not load_summary.empty else 0

    return {
        "assignment_df": df,
        "total_assigned": assigned,
        "method_max_load": method_max,
        "load_summary": load_summary,
    }


def run_assignment(
    sections_df: pd.DataFrame,
    faculty_indicator: pd.DataFrame,
    strict_max_load: int,
    method_id: int,
) -> Dict[str, object]:
    return _greedy_assign(
        sections_df=sections_df,
        faculty_indicator=faculty_indicator,
        strict_max_load=strict_max_load,
        method_id=method_id,
        flexible_cap=None,
        core_only_flexible=False,
    )


def run_assignment_flexible_maxload(
    sections_df: pd.DataFrame,
    faculty_indicator: pd.DataFrame,
    strict_max_load: int,
    method_id: int,
    max_load_cap: int,
) -> Dict[str, object]:
    if method_id == 3:
        return _greedy_assign(
            sections_df=sections_df,
            faculty_indicator=faculty_indicator,
            strict_max_load=strict_max_load,
            method_id=method_id,
            flexible_cap=max_load_cap,
            core_only_flexible=True,
        )
    else:
        return _greedy_assign(
            sections_df=sections_df,
            faculty_indicator=faculty_indicator,
            strict_max_load=strict_max_load,
            method_id=method_id,
            flexible_cap=max_load_cap,
            core_only_flexible=False,
        )


def process_and_print_results(method_name, result, preference_df, initial_max_load):
    df_output = result["assignment_df"].copy()
    columns_to_keep = [
        "offeringId",
        "courseId",
        "semesterId",
        "sectionId",
        "total_sections",
        "courseCategory",
        "assignedFacultyId",
    ]
    if "category_rank" in df_output.columns:
        df_output.drop(columns=["category_rank"], inplace=True, errors="ignore")
    df_output = df_output[columns_to_keep]
    df_output["assignedFacultyId"] = df_output["assignedFacultyId"].astype(str)

    merged_pref = preference_df[["facultyUserId", "courseId", "priorityRank"]].copy()
    merged_pref["facultyUserId"] = merged_pref["facultyUserId"].astype(str)
    df_output = pd.merge(
        df_output,
        merged_pref,
        left_on=["assignedFacultyId", "courseId"],
        right_on=["facultyUserId", "courseId"],
        how="left",
    )
    df_output.drop(columns=["facultyUserId"], inplace=True, errors="ignore")

    max_rank = preference_df["priorityRank"].max()
    penalty_rank = max_rank + 1 if pd.notna(max_rank) else 5

    total_sections = len(df_output)
    total_assigned = result["total_assigned"]

    assigned_df = df_output[df_output["assignedFacultyId"] != "NOT_ASSIGNED"].copy()
    assigned_count = len(assigned_df)

    assigned_core = len(assigned_df[assigned_df["courseCategory"] == "Core"])
    assigned_elective = len(assigned_df[assigned_df["courseCategory"] == "Elective"])

    assigned_with_pref = assigned_df[assigned_df["priorityRank"].notna() & (assigned_df["priorityRank"] > 0)]
    assigned_with_pref_count = len(assigned_with_pref)
    avg_pref_rank = (
        assigned_with_pref["priorityRank"].mean() if assigned_with_pref_count > 0 else 0
    )

    assigned_df["SatisfactionRank"] = assigned_df["priorityRank"].fillna(penalty_rank).astype(int)
    overall_satisfaction_score = assigned_df["SatisfactionRank"].mean() if assigned_count > 0 else 0

    no_pref_assigned_count = assigned_df["priorityRank"].isna().sum()
    no_preference_rate = no_pref_assigned_count / assigned_count if assigned_count > 0 else 0

    total_unassigned = total_sections - total_assigned
    max_load_achieved = result["method_max_load"]
    total_assigned_rate = total_assigned / total_sections if total_sections > 0 else 0

    total_core = len(df_output[df_output["courseCategory"] == "Core"])
    core_assigned_rate = assigned_core / total_core if total_core > 0 else 0

    total_elective = len(df_output[df_output["courseCategory"] == "Elective"])
    elective_assigned_rate = assigned_elective / total_elective if total_elective > 0 else 0

    load_summary = result["load_summary"]
    load_std_dev = load_summary["sections_assigned"].std() if len(load_summary) > 1 else 0

    print(f"\n--- {method_name} Summary ---")
    print(f"* Total Sections: **{total_sections}**")
    print(f"* Assigned: **{total_assigned}** ({total_assigned_rate:.1%})")
    print(f"* Unassigned: **{total_unassigned}**")
    print(f"* Initial Max Load: **{initial_max_load}**")
    print(f"* Actual Max Faculty Load: **{max_load_achieved}**")
    print(f"* Core Assigned Rate: **{core_assigned_rate:.1%}**")
    print(f"* Elective Assigned Rate: **{elective_assigned_rate:.1%}**")
    print(f"* Avg Preference Rank (Pref>0): **{avg_pref_rank:.2f}**")
    print(f"* Overall Satisfaction Score (Penalty={penalty_rank}): **{overall_satisfaction_score:.2f}**")
    print(f"* Load Std Dev: **{load_std_dev:.2f}**\n")

    try:
        print(f"--- {method_name} (first 5 rows) ---")
        print(safe_to_markdown(df_output[["offeringId", "courseId", "courseCategory", "assignedFacultyId", "priorityRank"]], head=5))
    except Exception:
        pass

    if not load_summary.empty:
        print(f"\n--- {method_name} Load Summary ---")
        try:
            print(safe_to_markdown(load_summary.sort_values(by="sections_assigned", ascending=False), head=50))
        except Exception:
            print(load_summary.sort_values(by="sections_assigned", ascending=False))

    unassigned_sections = df_output[df_output["assignedFacultyId"] == "NOT_ASSIGNED"]
    print(f"\nUnassigned Sections count: **{len(unassigned_sections)}**")

    kpi_dict = {
        "Method": method_name,
        "Total Assigned Rate": total_assigned_rate,
        "Core Assigned Rate": core_assigned_rate,
        "Elective Assigned Rate": elective_assigned_rate,
        "Avg Pref Rank": avg_pref_rank,
        "Overall Satisfaction Score": overall_satisfaction_score,
        "No Preference Rate": no_preference_rate,
        "Max Load Achieved": max_load_achieved,
        "Load Std Dev": load_std_dev,
        "Total Sections": total_sections,
        "Total Assigned": total_assigned,
    }
    return df_output, load_summary, unassigned_sections, kpi_dict


def create_kpi_summary_df(kpi_results_list: List[Dict[str, object]]) -> pd.DataFrame:
    kpi_df = pd.DataFrame(kpi_results_list)
    kpi_df = kpi_df[
        [
            "Method",
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
    ]
    kpi_df["Total Assigned Rate"] = (kpi_df["Total Assigned Rate"] * 100).round(1).astype(str) + "%"
    kpi_df["Core Assigned Rate"] = (kpi_df["Core Assigned Rate"] * 100).round(1).astype(str) + "%"
    kpi_df["Elective Assigned Rate"] = (kpi_df["Elective Assigned Rate"] * 100).round(1).astype(str) + "%"
    kpi_df["Avg Pref Rank"] = pd.to_numeric(kpi_df["Avg Pref Rank"]).round(2)
    kpi_df["Overall Satisfaction Score"] = pd.to_numeric(kpi_df["Overall Satisfaction Score"]).round(2)
    kpi_df["No Preference Rate"] = (pd.to_numeric(kpi_df["No Preference Rate"]) * 100).round(1).astype(str) + "%"
    kpi_df["Load Std Dev"] = pd.to_numeric(kpi_df["Load Std Dev"]).round(2)
    return kpi_df


def try_ai_report(final_kpi_summary: pd.DataFrame) -> None:
    try:
        from transformers import AutoTokenizer, AutoModelForCausalLM
        from huggingface_hub import login
        import torch  # noqa: F401
    except Exception as e:
        log(f"(AI) Skipping AI report (transformers not available): {e}")
        return

    model_id = os.environ.get("HF_MODEL_ID", "meta-llama/Llama-3.2-3B-Instruct")
    hf_token = os.environ.get("HUGGINGFACE_TOKEN", None)
    if hf_token:
        try:
            login(token=hf_token)
            log("✅ Hugging Face login successful.")
        except Exception as e:
            log(f"(AI) Warning: login failed: {e}")

    try:
        tokenizer = AutoTokenizer.from_pretrained(model_id, token=hf_token)
        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            token=hf_token,
            torch_dtype="auto",
            device_map="auto",
        )
    except Exception as e:
        log(f"(AI) Skipping model load: {e}")
        return

    try:
        kpi_table_markdown = final_kpi_summary.to_markdown(index=False)
    except Exception:
        kpi_table_markdown = str(final_kpi_summary)

    llama_prompt_template = f"""
You are an expert academic scheduling analyst. Your task is to analyze four different faculty assignment methodologies and generate a concise, professional English report for the Academic Dean.

[DATA INPUT]
The following table summarizes the Key Performance Indicators (KPIs) for four different assignment methods (Method 1 to Method 4). Note that lower rank scores (Avg Pref Rank, Overall Satisfaction Score) and lower Load Std Dev are generally better.

{kpi_table_markdown}

[ANALYSIS REQUIREMENTS]
1. Overall Assignment (Coverage): Compare the Total, Core, and Elective Assigned Rates. Clearly state which method achieved the highest coverage, and highlight the difference between Method 3 (Core-focused) and Method 4 (All-focused).
2. Quality of Assignment (Preference/Satisfaction): Analyze 'Avg Pref Rank' and 'Overall Satisfaction Score'. Identify the method that best respects faculty preference. Discuss the trade-off between coverage and quality.
3. Faculty Load and Equity: Analyze 'Max Load Achieved' and 'Load Std Dev'. Recommend the method that provides the best balance of equity while maintaining efficiency.
4. Conclusion & Recommendation: Provide the most balanced and effective assignment strategy.

[REPORT FORMAT]
Use clear section headings (1. Coverage, 2. Quality, etc.).
"""

    messages = [
        {"role": "system", "content": "You are an expert academic scheduling analyst. Generate a professional English report based on the provided data."},
        {"role": "user", "content": llama_prompt_template},
    ]

    try:
        try:
            input_text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        except Exception:
            input_text = "System: " + messages[0]["content"] + "\nUser: " + messages[1]["content"] + "\nAssistant:"

        input_ids = tokenizer.encode(input_text, return_tensors="pt").to(model.device)
        output = model.generate(
            input_ids,
            max_new_tokens=800,
            temperature=0.7,
            do_sample=True,
            top_p=0.9,
            eos_token_id=tokenizer.eos_token_id,
        )
        generated_text = tokenizer.decode(output[0], skip_special_tokens=True)
        print("\n" + "=" * 60)
        print("                 AI GENERATED ANALYSIS REPORT")
        print("=" * 60)
        print(generated_text.strip())
        print("=" * 60)
    except Exception as e:
        log(f"(AI) Generation failed: {e}")


def main() -> None:
    dataframes: Dict[str, pd.DataFrame]
    if SQL_AVAILABLE:
        try:
            dataframes = load_from_mysql()
        except Exception as e:
            log(f"MySQL load failed ({e}). Trying Excel...")
            dataframes = load_from_excel(XLSX_PATH)
    else:
        dataframes = load_from_excel(XLSX_PATH)

    semester_df = dataframes.get("semester_df")
    course_df = dataframes.get("course_df")
    offer_df = dataframes.get("offer_df")
    faculty_df = dataframes.get("faculty_df")
    preference_df = dataframes.get("preference_df")

    sections_df, active_semester_id = prepare_sections(semester_df, offer_df, course_df)
    faculty_indicator = build_faculty_indicators(
        preference_df=preference_df,
        faculty_df=faculty_df,
        active_semester_id=active_semester_id,
        sections_df=sections_df,
    )

    kpi_results: List[Dict[str, object]] = []

    result_m1 = run_assignment(sections_df, faculty_indicator, MAX_LOAD, 1)
    df_output1, load_summary_m1, unassigned_sections_m1, kpi_m1 = process_and_print_results(
        "Method 1 (Strict, Pref > 0)", result_m1, preference_df, MAX_LOAD
    )
    kpi_results.append(kpi_m1)

    result_m2 = run_assignment(sections_df, faculty_indicator, MAX_LOAD, 2)
    df_output2, load_summary_m2, unassigned_sections_m2, kpi_m2 = process_and_print_results(
        "Method 2 (Strict, No Pref)", result_m2, preference_df, MAX_LOAD
    )
    kpi_results.append(kpi_m2)

    result_m3 = run_assignment_flexible_maxload(sections_df, faculty_indicator, MAX_LOAD, 3, max_load_cap=FLEXIBLE_MAX_LOAD_CAP)
    df_output3, load_summary_m3, unassigned_sections_m3, kpi_m3 = process_and_print_results(
        "Method 3 (Flexible, Core Only)", result_m3, preference_df, MAX_LOAD
    )
    kpi_results.append(kpi_m3)

    result_m4 = run_assignment_flexible_maxload(sections_df, faculty_indicator, MAX_LOAD, 4, max_load_cap=FLEXIBLE_MAX_LOAD_CAP)
    df_output4, load_summary_m4, unassigned_sections_m4, kpi_m4 = process_and_print_results(
        "Method 4 (Flexible, All Sections)", result_m4, preference_df, MAX_LOAD
    )
    kpi_results.append(kpi_m4)

    final_kpi_summary = create_kpi_summary_df(kpi_results)
    print("\n🌟 FINAL KPI COMPARISON ACROSS METHODS 🌟")
    try:
        print(final_kpi_summary.to_markdown(index=False))
    except Exception:
        print(final_kpi_summary)

    out_csv = Path(OUTPUT_DIR) / "final_kpi_summary.csv"
    final_kpi_summary.to_csv(out_csv, index=False)
    log(f"\nSaved KPI summary to: {out_csv.as_posix()}")

    try_ai_report(final_kpi_summary)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"FATAL: {e}")
        sys.exit(1)

