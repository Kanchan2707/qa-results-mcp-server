# QA Results MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server that lets an
AI assistant query LLM **evaluation results**: list test runs, read pass rates and
metrics, see why tests failed, and compare two runs to find regressions.

It reads the JSON result files written by
[claude-eval-framework](https://github.com/Kanchan2707/claude-eval-framework), my
QA-style evaluation framework for the Claude API. Instead of opening result files by
hand, you can ask an assistant things like *"which tests failed in the latest safety
run?"* or *"did the friendly prompt break anything compared with baseline?"*

The server is **read-only**. It makes no network calls and no API calls, so running it
costs nothing.

## Tools

| Tool | What it does |
|---|---|
| `list_runs` | List stored runs, newest first. Filter by `suite`, `mode` (`live`/`mock`) or `system_prompt`. |
| `get_run_summary` | Pass rate, tag metrics (faithfulness, safety violations, over-refusal) and per-test pass/fail for one run. |
| `get_failures` | For each failed test: prompt, response, scorer detail, judge score and reason. |
| `compare_runs` | Compare two runs of the same suite: regressions, fixes, new/removed tests. |
| `get_test_history` | How one test (for example `SF003`) did across every stored run. |

## Design decisions

- **Mock vs live is never mixed up.** Runs made with the offline mock carry
  `mode: "mock"`, and every tool response for them includes a warning that the numbers
  say nothing about real model behaviour. Comparing a live run with a mock run is
  flagged as not meaningful.
- **Safe file access.** Tools take a file *name* from `list_runs`, never a path. Names
  containing `/`, `..` or a non-`.json` ending are rejected, so a client cannot read
  other files on the machine through the server.
- **Clear errors.** Expected problems (missing file, different suites, bad name) come
  back as readable tool errors for the model, not stack traces. Unreadable files in the
  results folder are skipped and reported instead of crashing `list_runs`.

## Setup

Requires Python 3.10+.

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Tell the server where your results are (the `results/` folder of claude-eval-framework):

```bash
export RESULTS_DIR=/path/to/claude-eval-framework/results
```

If `RESULTS_DIR` is not set, the server looks for a `results/` folder in the directory
it is started from.

## Try it without any AI app

`scripts/demo_client.py` starts the server and calls the tools the way an AI assistant
would:

```bash
python scripts/demo_client.py
```

To try it on the bundled sample data (mock runs):

```bash
RESULTS_DIR=tests/fixtures python scripts/demo_client.py
```

## Use it from Claude Desktop (optional)

Copy `claude_desktop_config.example.json`, replace the `/FULL/PATH/TO/...` values with
real absolute paths, and merge it into Claude Desktop's config file
(`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS). Restart
Claude Desktop, and the `qa-results` tools appear in the chat.

## Tests

```bash
python -m unittest discover -s tests -t . -v
```

20 tests: unit tests for the results logic, plus end-to-end tests in which a real MCP
client starts the server over stdio and calls the tools (including a path-traversal
attempt, which must be rejected). Test data is in `tests/fixtures/` and comes from
**mock** runs of the evaluation framework, so tests do not depend on an API key.

## Project structure

```
qa-results-mcp-server/
├── qa_results_mcp/
│   ├── store.py      # reads and analyses result files (no MCP code, easy to test)
│   └── server.py     # registers the tools with the MCP server
├── scripts/demo_client.py
├── tests/            # unit + end-to-end tests, fixtures
├── claude_desktop_config.example.json
└── requirements.txt
```

## Limitations

- Reads result files from one local folder; there is no database or remote storage.
- Built for the result format of claude-eval-framework. Other formats are not supported.
- Uses the stdio transport (local use). It has no authentication, so do not expose it
  on a network as it is.
