# free247jarvis

![License](https://img.shields.io/github/license/riecodes/free247jarvis?style=flat-square&color=green) ![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?style=flat-square&logo=windows&logoColor=white) ![Claude Code](https://img.shields.io/badge/Claude%20Code-voice-D97757?style=flat-square&logo=anthropic&logoColor=white) ![Price](https://img.shields.io/badge/price-free-brightgreen?style=flat-square)

Say **"Hey Jarvis"** and run your Claude Code terminals by voice.

A small, free, open-source voice layer for Windows. A wake word wakes a "boss" Claude Code
session, which hands your spoken request to your other Claude Code terminals, picks the one
that is free, opens new ones, and drives Windows apps for anything outside the terminal. It
answers out loud.

## What you say

- "Hey Jarvis, tell terminal 2 to run the tests."
- "Hey Jarvis, give this to whoever is free: fix the navbar on mobile."
- "Hey Jarvis, open two more terminals in the webinar folder."
- "Hey Jarvis, open Notepad and type hello."

Talk in English, Tagalog, or Taglish. The free voice answers in English (its British voice only
says English words); the pro voice answers in Taglish. When a terminal finishes, the boss tells you.

## Setup (once)

### One prompt

Open Claude Code in any folder (`claude` in a terminal) and paste:

```text
Set up free247jarvis for me. Clone https://github.com/riecodes/free247jarvis.git into my
Documents folder (install Git first if it is missing, after asking me). In that folder, run
powershell -ExecutionPolicy Bypass -File setup.ps1 and install anything it reports missing
after asking me. Get me a free Groq key from https://console.groq.com/keys (get it for me if
you have browser tools such as Claude in Chrome, otherwise walk me through it), put it in the
.env file as GROQ_API_KEY, and run setup.ps1 again until it says "Setup done". Then run
start.ps1, tell me to pick "I am using this for local development" in the new boss window, and
to say "Hey Jarvis, open one more terminal".
```

### Step by step

1. **Get it.** `git clone https://github.com/riecodes/free247jarvis.git`, or *Code > Download
   ZIP* on GitHub and unzip it.
2. **Install.** In that folder: `powershell -ExecutionPolicy Bypass -File setup.ps1`. It says
   what is missing, installs the Python and Node packages, and downloads the models (about
   360 MB). With an NVIDIA graphics card it also installs the GPU build of ONNX Runtime, so the
   voice speaks in about half a second instead of two (that needs the CUDA toolkit and cuDNN;
   without them it runs on the processor).
3. **Add your Groq key.** Get a free key at <https://console.groq.com/keys> (no card needed) and
   put it in `.env`: `GROQ_API_KEY=gsk_...`.
4. **Start the boss.** `powershell -ExecutionPolicy Bypass -File start.ps1`. The very first time,
   the new window asks whether you trust the folder: pick **Yes, I trust this folder** (once; "No,
   exit" closes the window). Then pick **I am using this for local development** (Claude Code asks
   every time, because the voice channel is not on its approved list yet).
5. **Say "Hey Jarvis".** It answers "Jarvis here", then say what you want. Or say it all in one
   breath: "Hey Jarvis, status".

Optional: `.venv\Scripts\python listener.py train` teaches the wake word your voice (five
"Hey Jarvis"es and three sentences), which cuts false wakes from other voices and the TV.

## Pro voice (ElevenLabs, optional)

Swap the free ears and voice for ElevenLabs: Scribe v2 hears you, and the boss answers in your own
cloned voice or any ElevenLabs voice. The wake word and the boss stay the same and still run on your PC.
If ElevenLabs fails (no credits, no internet), that request falls back to Groq and Kokoro.

1. **Get a key.** Sign up at <https://elevenlabs.io>. Any plan works, the free one too while its credits
   last; an Instant Voice Clone needs Starter or higher, a Professional Voice Clone Creator or higher. Under *Developers > API keys*,
   create a key with access to Text to Speech and Speech to Text.
2. **Pick a voice.** Either:
   - **Stock:** leave the ID empty for the calm British stock voice George. Or open *Voices*, pick one
     from the Voice Library (the butler-style Rupert is `89gcX1AeMGgcsN8ypHLu`), and copy its voice ID
     (the `...` menu, *Copy voice ID*).
   - **Your own:** *Voices > Create a voice*. Instant needs about a minute of clean audio and is ready
     right away. Professional needs 30 minutes or more, a short verification read, and a few hours of
     training, and sounds much closer to you. Copy its voice ID when it is ready.
3. **Paste them into `.env`:**
   ```
   VOICE_ENGINE=elevenlabs
   ELEVENLABS_API_KEY=sk_...
   ELEVENLABS_VOICE_ID=your voice ID
   ```
   Optional: `ELEVENLABS_MODEL=eleven_v4_turbo` sounds more natural; the default `eleven_flash_v2_5`
   is the fastest and cheapest.
4. **Start the boss** as usual (`start.ps1`). `tmp\voice.log` says `Voice: ElevenLabs` when it is on.
   `start.ps1 -Engine elevenlabs` or `-Engine free` overrides `.env` for one run.

Cost: only what follows the wake word is sent, so idle hours cost nothing. A spoken reply is about
70 characters and a request a few seconds of audio, both paid from your plan's credits.

## Faster answers (optional)

Every request waits for a turn of the boss, a few seconds or more. With a TypeSafe key in `.env`
(`TYPESAFE_API_KEY=`), its Jev classifier sorts what you say first, in about 0.2 seconds, and these
skip the boss:

- **Status** ("status", "who needs me"): read straight from Claude Code's session files.
- **Small talk** ("how are you", "what time is it"): Claude Haiku answers, with `ANTHROPIC_API_KEY=`.
- **Unclear speech** (cut off, garbled, the TV): it asks "Say that again?" and listens without the
  wake word.

Everything else, and everything when Jev isn't sure, goes to the boss as before. To try it without
the mic: `curl -d "status" http://127.0.0.1:8790/heard`.

## How it works

```
mic -> listener.py (openWakeWord "hey Jarvis", Silero VAD, Groq whisper-large-v3-turbo)
    -> voice.mjs, a Claude Code channel -> the boss session
boss -> SendMessage to t2                  "tell terminal 2 ..."
     -> ListAgents, then the idle one      "give this to whoever is free ..."
     -> spawn.ps1                          "open two more terminals ..."
     -> gui.ps1                            "open Notepad and type hello"
     -> reply tool -> Kokoro -> speaker    (the mic is muted while it speaks)
```

- **The boss** is a Claude Code session named `boss` in the `boss` folder. Its `CLAUDE.md` says
  how to route, and its `.mcp.json` loads the voice channel, so no other session loads it.
- **Workers** are Claude Code sessions named after their cell in a 3x2 grid of terminals, `t1`
  (top left) to `t6` (bottom right), so "terminal 2" is session `t2`. `spawn.ps1` opens them
  in Windows Terminal with `--dangerously-skip-permissions`, by default in the folder that
  holds free247jarvis. Claude Code's own messaging between sessions carries the requests; no
  keystrokes are sent to them.
- **Windows apps:** Claude Code's computer use runs only on macOS in the CLI, so the boss uses
  `gui.ps1` instead: screenshots to look, and app launch, typing, keys, and clicks to act.
- **Typed requests** work too: `curl -d "tell terminal 2 to run the tests" http://127.0.0.1:8790/`.
  Everything heard and said is logged to `tmp\voice.log`.

## Good to know

- Workers bypass permission prompts, so the boss does too; Claude Code only delivers messages
  between sessions in the same permission class unless you set `crossSessionInbound` to `accept`.
- A message cannot answer a permission prompt or a menu inside a worker. Answer those at that
  terminal.
- Every message a worker gets counts against your plan's usage.
- The free voice is Kokoro's calm British `bm_george`. Set `VOICE=` in `.env` to `bm_daniel`,
  `bm_fable`, `bm_lewis`, or the old American `af_heart`, then restart the boss.
- Rather say "Hey Claude"? Set `WAKE_WORDS=hey_claude` in `.env` (it answers "Claude here"), or
  `WAKE_WORDS=hey_jarvis,hey_claude` for both. "Hey Claude" can't tell "hey Clyde" apart.
- If the wake word misses you, set `WAKE_THRESHOLD=0.3` in `.env`, or train it on your voice.
- After it hears a request, it waits for the answer before the wake word works again, so saying
  "Hey Jarvis" twice doesn't start over.
- After each spoken answer it keeps listening for 8 seconds, so you can reply ("yes", "A", "tell it
  to go on") without the wake word. `FOLLOWUP_SECONDS=` in `.env` changes that; 0 turns it off.
- If the mic sends nothing but silence for 30 seconds (a virtual mic such as Voicemod whose app is
  closed), it says so once.
- Not hearing you at all? Windows may be listening to another mic. Set `MIC_DEVICE=` in `.env` to
  part of your mic's name as Windows Sound settings shows it (such as `MIC_DEVICE=WebCamera`, or
  `MIC_DEVICE=Voicemod` to hear you through Voicemod), then restart the boss.
- Nothing arrives in the boss? Run `/mcp` there and check that `voice` is connected, and read
  `tmp\voice.log`.

## Check

`.venv\Scripts\python check_boss.py` runs end to end against real sessions and prints
`ALL PASS`: the wake word, a Taglish transcription through Groq, a task for terminal 2, a task
for whoever is free, opening a terminal, Notepad, and a spoken reply. Clips are synthesized, so
no microphone is needed. It starts the boss and two workers if they are missing and closes what
it opened.

## Needs

- Windows 10 or 11 with Windows Terminal and a microphone
- [Claude Code](https://code.claude.com) 2.1.234 or later, signed in with a Pro or Max plan
- Python 3.10 to 3.13 and Node 20 or later
- A free Groq key for speech to text: <https://console.groq.com/keys> (about $0.04 per hour of
  audio past the free tier), or an ElevenLabs key for the pro voice

## Files

```
free247jarvis/
  boss/          the boss session's folder: CLAUDE.md (routing) and .mcp.json (voice channel)
  voice.mjs      the voice channel (MCP server); runs listener.py
  listener.py    wake word, end of speech, speech to text, Kokoro voice, voice training
  spawn.ps1      opens worker terminals t1 to t6 in their grid cells
  gui.ps1        screenshots, typing, keys, and clicks for Windows apps
  start.ps1      starts the boss
  setup.ps1      one-time setup (safe to re-run)
  check_boss.py  end-to-end check
```

## License

MIT
