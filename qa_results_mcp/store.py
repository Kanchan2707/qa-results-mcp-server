"""
store.py

Plain-Python logic for reading evaluation result files (the JSON files written
by claude-eval-framework). It has no MCP code in it, so it can be unit tested
directly. server.py wraps these functions as MCP tools.

Result files are looked up ONLY inside one results directory. A file name that
contains a path separator or ".." is rejected, so a client can't read other
files on the machine through this server.
"""

import json
import os
from pathlib import Path

DEFAULT_RESULTS_DIR = "results"
MAX_TEXT = 400  # characters of prompt/response text returned per failure


class ResultsError(Exception):
    """A problem the caller should see (bad file name, missing file, bad JSON)."""


def results_dir() -> Path:
    return Path(os.environ.get("RESULTS_DIR", DEFAULT_RESULTS_DIR)).expanduser().resolve()


def _truncate(text, limit=MAX_TEXT):
    if text is None:
        return None
    text = str(text)
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def _safe_path(file_name: str) -> Path:
    if not file_name or Path(file_name).name != file_name or ".." in file_name:
        raise ResultsError(
            "Use just a file name from list_runs (no folders or '..'), "
            "for example 'run_live_safety_baseline_2026-10-13_130450.json'."
        )
    if not file_name.endswith(".json"):
        raise ResultsError("Result files end in .json.")
    path = results_dir() / file_name
    if not path.is_file():
        raise ResultsError(f"No result file named '{file_name}'. Call list_runs to see what exists.")
    return path


def load_run(file_name: str) -> dict:
    path = _safe_path(file_name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ResultsError(f"'{file_name}' is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ResultsError(f"'{file_name}' is not a result file (expected a JSON object).")
    return data


def _norm_suite(name):
    """'safety' and 'safety.yaml' mean the same suite."""
    if name is None:
        return None
    name = str(name)
    return name[:-5] if name.endswith(".yaml") else name


def _mode_warning(mode):
    if mode == "mock":
        return ("MOCK run: canned offline data used to test the framework. "
                "These numbers say nothing about how a real model behaves.")
    return None


def _summary(file_name: str, data: dict) -> dict:
    summary = {
        "file": file_name,
        "mode": data.get("mode"),
        "suite": data.get("suite"),
        "system_prompt_name": data.get("system_prompt_name"),
        "run_timestamp": data.get("run_timestamp"),
        "model": data.get("model"),
        "total_tests": data.get("total_tests"),
        "passed": data.get("passed"),
        "failed": data.get("failed"),
        "pass_rate": data.get("pass_rate"),
    }
    warning = _mode_warning(data.get("mode"))
    if warning:
        summary["warning"] = warning
    return summary


def list_runs(suite=None, mode=None, system_prompt=None, limit=20) -> dict:
    """List result files, newest first, optionally filtered."""
    folder = results_dir()
    if not folder.is_dir():
        raise ResultsError(f"Results folder not found: {folder}. Set RESULTS_DIR to your results folder.")
    runs, skipped = [], []
    for path in folder.glob("run_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except (json.JSONDecodeError, ValueError, OSError):
            skipped.append(path.name)
            continue
        summary = _summary(path.name, data)
        if suite and _norm_suite(summary["suite"]) != _norm_suite(suite):
            continue
        if mode and summary["mode"] != mode:
            continue
        if system_prompt and summary["system_prompt_name"] != system_prompt:
            continue
        runs.append(summary)
    runs.sort(key=lambda r: (r["run_timestamp"] or "", r["file"]), reverse=True)
    result = {"results_dir": str(folder), "count": len(runs), "runs": runs[: max(1, int(limit))]}
    if skipped:
        result["skipped_unreadable_files"] = sorted(skipped)
    return result


def get_run_summary(file_name: str) -> dict:
    """Pass rate, tag metrics (faithfulness, safety...) and per-test pass/fail for one run."""
    data = load_run(file_name)
    summary = _summary(file_name, data)
    summary["by_tag"] = data.get("by_tag", {})
    summary["metrics"] = data.get("metrics", {})
    summary["tests"] = [
        {"id": r.get("id"), "passed": r.get("passed"), "scorer": r.get("scorer")}
        for r in data.get("results", [])
    ]
    return summary


def get_failures(file_name: str) -> dict:
    """Details for every failed test in one run."""
    data = load_run(file_name)
    failures = []
    for r in data.get("results", []):
        if r.get("passed"):
            continue
        item = {
            "id": r.get("id"),
            "scorer": r.get("scorer"),
            "tags": r.get("tags", []),
            "prompt": _truncate(r.get("prompt")),
            "response": _truncate(r.get("response")),
            "detail": r.get("detail"),
        }
        if "judge_score" in r:
            item["judge_score"] = r.get("judge_score")
            item["judge_reason"] = r.get("judge_reason")
        failures.append(item)
    out = {"file": file_name, "mode": data.get("mode"), "suite": data.get("suite"),
           "system_prompt_name": data.get("system_prompt_name"),
           "failure_count": len(failures), "failures": failures}
    warning = _mode_warning(data.get("mode"))
    if warning:
        out["warning"] = warning
    return out


def compare_runs(baseline_file: str, candidate_file: str) -> dict:
    """Per-test regression comparison between two runs of the same suite."""
    base, cand = load_run(baseline_file), load_run(candidate_file)
    if base.get("suite") != cand.get("suite"):
        raise ResultsError(
            f"These runs are from different suites ({base.get('suite')} vs {cand.get('suite')}); "
            "compare runs of the same suite."
        )
    mixed = base.get("mode") != cand.get("mode")
    b = {r.get("id"): r for r in base.get("results", [])}
    c = {r.get("id"): r for r in cand.get("results", [])}
    regressions, fixed, unchanged, new, removed = [], [], [], [], []
    for test_id in sorted(set(b) | set(c), key=str):
        if test_id not in c:
            removed.append(test_id)
        elif test_id not in b:
            new.append(test_id)
        else:
            before, after = bool(b[test_id].get("passed")), bool(c[test_id].get("passed"))
            entry = {"id": test_id, "before_detail": b[test_id].get("detail"),
                     "after_detail": c[test_id].get("detail")}
            if before and not after:
                regressions.append(entry)
            elif after and not before:
                fixed.append(entry)
            else:
                unchanged.append({"id": test_id, "passed": after})
    out = {
        "suite": base.get("suite"),
        "baseline": {"file": baseline_file, "mode": base.get("mode"),
                     "system_prompt_name": base.get("system_prompt_name"), "pass_rate": base.get("pass_rate")},
        "candidate": {"file": candidate_file, "mode": cand.get("mode"),
                      "system_prompt_name": cand.get("system_prompt_name"), "pass_rate": cand.get("pass_rate")},
        "regressions": regressions,
        "fixed": fixed,
        "new_tests": new,
        "removed_tests": removed,
        "unchanged_count": len(unchanged),
        "verdict": "REGRESSIONS FOUND" if regressions else "no regressions",
    }
    warnings = []
    for w in (_mode_warning(base.get("mode")), _mode_warning(cand.get("mode"))):
        if w and w not in warnings:
            warnings.append(w)
    if mixed:
        warnings.append("These runs have different modes (live vs mock); the comparison is not meaningful.")
    if warnings:
        out["warnings"] = warnings
    return out


def get_test_history(test_id: str, suite=None, mode=None) -> dict:
    """How one test (for example 'SF003') performed across all stored runs."""
    history = []
    for path in sorted(results_dir().glob("run_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        if suite and _norm_suite(data.get("suite")) != _norm_suite(suite):
            continue
        if mode and data.get("mode") != mode:
            continue
        for r in data.get("results", []):
            if r.get("id") == test_id:
                history.append({
                    "file": path.name, "mode": data.get("mode"),
                    "system_prompt_name": data.get("system_prompt_name"),
                    "run_timestamp": data.get("run_timestamp"),
                    "passed": r.get("passed"), "detail": r.get("detail"),
                })
    history.sort(key=lambda h: (h["run_timestamp"] or "", h["file"]))
    passed = sum(1 for h in history if h["passed"])
    return {"test_id": test_id, "runs_found": len(history), "passed": passed,
            "failed": len(history) - passed, "history": history}
