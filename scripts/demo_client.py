"""
demo_client.py

Starts the MCP server as a separate process and talks to it the way an AI
assistant would: list the tools, then call them. Use it to see the server
working without any AI app.

  python scripts/demo_client.py                 # uses ./results if it exists
  RESULTS_DIR=/path/to/results python scripts/demo_client.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parent.parent


def show(title, result):
    print(f"\n=== {title} ===")
    if result.is_error:
        print("ERROR:", result.content[0].text)
        return None
    data = result.structured_content
    if data is None:
        data = json.loads(result.content[0].text)
    print(json.dumps(data, indent=2, ensure_ascii=False)[:1800])
    return data


async def main():
    env = dict(os.environ)
    env.setdefault("RESULTS_DIR", str(ROOT / "results"))
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "qa_results_mcp.server"], cwd=str(ROOT), env=env
    )
    async with Client(params) as client:
        tools = await client.list_tools()
        print("Tools exposed by the server:")
        for tool in tools.tools:
            print(f"  - {tool.name}")

        runs = show("list_runs (safety suite)", await client.call_tool("list_runs", {"suite": "safety"}))
        if not runs or not runs["runs"]:
            print("\nNo safety runs found. Set RESULTS_DIR to a folder of result files.")
            return
        first = runs["runs"][0]["file"]
        show(f"get_failures ({first})", await client.call_tool("get_failures", {"file_name": first}))

        by_prompt = {r["system_prompt_name"]: r["file"] for r in runs["runs"]}
        if "baseline" in by_prompt and "friendly" in by_prompt:
            show("compare_runs (baseline vs friendly)", await client.call_tool(
                "compare_runs",
                {"baseline_file": by_prompt["baseline"], "candidate_file": by_prompt["friendly"]},
            ))

        show("bad input is rejected safely", await client.call_tool(
            "get_run_summary", {"file_name": "../../etc/passwd"}))


if __name__ == "__main__":
    asyncio.run(main())
