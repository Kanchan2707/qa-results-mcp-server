"""End-to-end: start the server as a subprocess and talk to it with a real MCP client."""

import asyncio
import json
import sys
import unittest
from pathlib import Path

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
EXPECTED_TOOLS = {"list_runs", "get_run_summary", "get_failures", "compare_runs", "get_test_history"}


def run_with_client(coro_fn):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "qa_results_mcp.server"],
        cwd=str(ROOT), env={"RESULTS_DIR": str(FIXTURES)},
    )

    async def runner():
        async with Client(params) as client:
            return await coro_fn(client)

    return asyncio.run(runner())


def payload(result):
    return result.structured_content or json.loads(result.content[0].text)


class ServerOverMcpTests(unittest.TestCase):
    def test_server_lists_all_tools(self):
        async def go(client):
            return {t.name for t in (await client.list_tools()).tools}
        self.assertEqual(run_with_client(go), EXPECTED_TOOLS)

    def test_list_runs_over_mcp(self):
        async def go(client):
            return await client.call_tool("list_runs", {"suite": "safety"})
        result = run_with_client(go)
        self.assertFalse(result.is_error)
        self.assertEqual(payload(result)["count"], 2)

    def test_get_failures_over_mcp(self):
        async def go(client):
            runs = payload(await client.call_tool("list_runs", {"suite": "safety"}))
            return await client.call_tool("get_failures", {"file_name": runs["runs"][0]["file"]})
        result = run_with_client(go)
        self.assertFalse(result.is_error)
        self.assertEqual(payload(result)["failures"][0]["id"], "SF003")

    def test_path_traversal_is_rejected_over_mcp(self):
        async def go(client):
            return await client.call_tool("get_run_summary", {"file_name": "../../etc/passwd"})
        result = run_with_client(go)
        self.assertTrue(result.is_error)
        self.assertIn("no folders", result.content[0].text)


if __name__ == "__main__":
    unittest.main()
