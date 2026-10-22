# free247jarvis: Plan

"Hey Claude" voice control for Claude Code on Windows. A wake word wakes a boss Claude Code
session; the boss routes the spoken request to worker sessions, spawns new ones, or uses
computer use, and its reply is spoken aloud.

## Decisions (chosen 2026-10-23)

| Decision | Choice | Why |
|---|---|---|
| Brain | A Claude Code session named `boss`, in its own terminal | Runs on the user's Claude plan. Claude Code's built-in cross-session messaging (`ListAgents`, `SendMessage`, native Windows from v2.1.234) already lists every local session as idle or busy and delivers text to it, so no keystroke injection is needed |
| Voice into the boss | A custom channel MCP server (`claude/channel` capability), loaded with `--dangerously-load-development-channels server:voice` | The documented way to push outside text into a running session. Interactive sessions only; custom channels are not on the research-preview allowlist, so the dev flag stays |
| Where the boss runs | The `boss` folder, whose `.mcp.json` declares `voice` and whose `CLAUDE.md` holds the routing rules | `server:voice` only resolves servers from `.mcp.json` (not `--mcp-config`), and a worker opened in that folder would load the channel too and fight the boss for the microphone |
| Wake word | openWakeWord with [`gdiamos/hey-claude`](https://huggingface.co/gdiamos/hey-claude) (ONNX, about 200 KB, Apache-2.0), plus a verifier trained on the user's voice | Ready-made, runs on the CPU. 90% recall, 3% false accepts; it cannot tell "hey Claude" from "hey Clyde". Try threshold 0.3 if it misses |
| End of speech | Silero VAD | Small, CPU |
| Speech to text | Groq `whisper-large-v3-turbo` | Handles Tagalog and Taglish (Parakeet does not), about $0.04 per audio hour, fast |
| Voice out | Kokoro 82M, local | Free, Apache-2.0, natural, runs on the CPU |
| Computer use | `gui.ps1` (screenshots, app launch, typing, keys, clicks) called by the boss | Claude Code's built-in computer use is macOS-only in the CLI (checked 2026-10-23), so the boss looks and acts through PowerShell instead; same brain for terminal and GUI work |

The listener (wake word, VAD, recording, voice training) is ported from the author's Jarvis app,
where it was built and checked with openWakeWord `hey_jarvis` and Parakeet.

## How a request flows

```
mic -> listener (openWakeWord hey_claude, Silero VAD, Groq STT)
    -> POST 127.0.0.1 -> channel server "voice" -> <channel source="voice"> in the boss session
boss -> ListAgents: who is idle or busy
     -> SendMessage(t2, task)            "tell terminal 2 ..."
     -> SendMessage(<an idle one>, task) "give this to whoever is free ..."
     -> spawn.ps1                        "open two more terminals ..."
     -> gui.ps1                          "open Notepad and type hello"
     -> SendMessage notify_when_idle     tells the boss when a worker finishes
     -> reply tool on the channel -> Kokoro -> speaker (mic muted while speaking)
```

Workers are named after their grid cell (`t1` to `t6`, set with `claude --name`), so
"terminal 2" means session `t2`. Claude Code titles each window with the session name, which is how
`spawn.ps1` sees which numbers are taken; other windows do not count, so a worker can cover them.
The listener runs as a child of the channel server (`voice.mjs`), which also takes typed requests on
`POST 127.0.0.1:8790`.

## v1 scope

1. Talk to terminal N.
2. Auto-pick a free terminal.
3. Spawn terminals by voice.
4. GUI computer use by voice.

## Gotchas

- Workers started with `--dangerously-skip-permissions` hold messages from a session that does not
  bypass permissions until the user approves each one. The boss runs with bypass too, or the user
  sets `crossSessionInbound` to `accept`.
- A cross-session message cannot answer a permission prompt or a menu (AskUserQuestion) inside a
  worker; the user answers those at that terminal.
- Every message a worker receives counts as a prompt against the plan's usage.
- The dev-channel flag shows a confirmation dialog each time the boss starts.
- A Git Bash `PATH` puts an extensionless `notepad` script ahead of `notepad.exe`, so `gui.ps1 open`
  resolves bare names to their `.exe`. Windows 11 Notepad reopens old tabs: press Ctrl+N before
  typing.
- The channel server drops events silently if the session did not load it as a channel; check
  `/mcp` in the boss when nothing arrives.

## Check

`check_boss.py` runs end to end against real sessions and prints `ALL PASS` when: a hey_claude clip
wakes the listener; a Taglish clip transcribes through Groq; "tell terminal 2 to create
tmp\t2.txt" reaches `t2` and the file appears; "give this to whoever is free" goes to an idle
session; "open one more terminal" spawns a window named after its grid cell; "open Notepad and
type hello" leaves a Notepad window containing hello; the boss's reply comes out as a Kokoro wav.
Clips are synthesized, so no microphone is needed.

## Later

Tray icon and start with Windows, a keystroke fallback for answering menus in a worker, and
sessions on other machines through Remote Control.
