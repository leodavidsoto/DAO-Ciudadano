---
name: agent-orchestrator
description: Automates the orchestration of multiple agent instances running in macOS Terminal windows by reading their outputs and sending commands to them.
---

# Agent Orchestrator Skill

This skill allows an overarching Antigravity agent to take control of other agents (like Claude and Codex) running in separate Apple Terminal windows.

## Components Provided

1. `get_terminal.applescript`: Reads the entire output/history of all open Terminal windows and structures them by window name.
2. `send_terminal.applescript`: Focuses a specific Terminal window by name and pastes a command into it via clipboard and keystrokes.

## How to Orchestrate

To work in a continuous loop and reach a complex goal:

1. **Read State**: Use `run_command` with `osascript get_terminal.applescript > terminals.log` to dump the current state of all agents.
2. **Analyze**: Use `grep_search` to find `--- Window:` boundaries and `view_file` to read the ends of each agent's logs. Identify if an agent is waiting for input or running a long task.
3. **Prompt/Unblock**: If an agent is idle (e.g., finished its task and waiting for the next prompt), write your prompt to a `.txt` file and send it using `osascript send_terminal.applescript "window_name" "prompt_file.txt"`.
4. **Schedule**: Use the `schedule` tool to set a timer (e.g., 60s or 120s) to wait for long-running tasks. The timer will wake you up automatically to repeat the loop.

## The Loop Pattern

```markdown
1. Read terminals -> Check Claude -> Check Codex.
2. Are they blocked? -> Resolve dependencies, send next prompts via `send_terminal`.
3. Are they working? -> Call `schedule` for 2 minutes to let them work.
4. When woken up by `schedule`, repeat Step 1.
```

By following this loop, you can asynchronously orchestrate any number of terminal-bound agents until the ultimate project goal is achieved.
