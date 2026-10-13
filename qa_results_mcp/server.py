"""
server.py

An MCP (Model Context Protocol) server that lets an AI assistant query LLM
evaluation results: list runs, read pass rates and metrics, see why tests
failed, and compare two runs to find regressions.

It reads the JSON result files written by claude-eval-framework. It is
read-only and makes no network or API calls.

Run it:   python -m qa_results_mcp.server
Point it at a results folder with the RESULTS_DIR environment variable.
"""

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from qa_results_mcp import store

mcp = MCPServer(
    "qa-results",
    instructions=(
        "Tools for inspecting LLM evaluation results. Start with list_runs to find "
        "result files, then use get_run_summary, get_failures, compare_runs or "
        "get_test_history. Runs with mode 'mock' are canned test data, not real model "
        "behaviour; never present mock numbers as real results."
    ),
)


def _call(fn, *args, **kwargs):
    """Turn expected problems into a readable error message instead of a crash."""
    try:
        return fn(*args, **kwargs)
    except store.ResultsError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def list_runs(suite: str | None = None, mode: str | None = None,
              system_prompt: str | None = None, limit: int = 20) -> dict:
    """List stored evaluation runs, newest first.

    Optional filters: suite (e.g. 'safety'), mode ('live' or 'mock'),
    system_prompt (e.g. 'baseline'). Returns file names to use in other tools.
    """
    return _call(store.list_runs, suite, mode, system_prompt, limit)


@mcp.tool()
def get_run_summary(file_name: str) -> dict:
    """Pass rate, tag metrics (faithfulness, safety violations, over-refusal) and per-test results for one run file."""
    return _call(store.get_run_summary, file_name)


@mcp.tool()
def get_failures(file_name: str) -> dict:
    """Why tests failed in one run: prompt, response, scorer detail and judge score/reason."""
    return _call(store.get_failures, file_name)


@mcp.tool()
def compare_runs(baseline_file: str, candidate_file: str) -> dict:
    """Compare two runs of the same suite and list regressions (passed before, fail now) and fixes."""
    return _call(store.compare_runs, baseline_file, candidate_file)


@mcp.tool()
def get_test_history(test_id: str, suite: str | None = None, mode: str | None = None) -> dict:
    """How one test case (e.g. 'SF003') performed across every stored run."""
    return _call(store.get_test_history, test_id, suite, mode)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
