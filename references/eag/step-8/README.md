# Step 8 reference provenance

The Step 8 correction used the following directory only as a read-only design reference:

`/home/sagar/Downloads/Agent_codefile/Agent_codefile/session-10/S10Share`

Files inspected:

- `agent/agentSession.py`, `agent/agent_loop.py`, and `agent/agent_loop2.py`
- `perception/perception.py` and `prompts/perception_prompt.txt`
- `decision/decision.py` and `prompts/decision_prompt.txt`
- `action/executor.py`
- `mcp_servers/multiMCP.py` and `mcp_servers/mcp_server_1.py`
- `heuristics/heuristics.py`, `memory/session_log.py`, and `EXECUTION_FLOW.md`

Adopted ideas were a request-local agent session, separate Perception and Decision stages,
step-result perception, versioned plans, structured model output, an MCP registry boundary, and a
visible execution timeline. These were adapted into strict bounded Pydantic contracts,
manifest-derived authorized tool descriptors, immutable host-owned completed history, deterministic
plan progression, database-backed authorization, content-free failure observations, and a sanitized
response-only trace.

Unsafe ideas were rejected: `run_user_code`, generated-code execution, `compile`/`exec`, arbitrary
Python, shell, SQL, URL, path, browser, or computer tools; positional argument reconstruction;
unbounded loops; implicit forced completion; global vector memory; raw session files; duplicate tool
overwrites; and printing raw queries, prompts, evidence, results, errors, or secrets. In particular,
`run_user_code` and every generated-code execution path are unsafe and are not supported.

Production code must never import, execute, or otherwise depend on this reference directory. The
reference was not copied into the application, and it remains outside the repository.
