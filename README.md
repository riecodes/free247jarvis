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
.env file as GROQ_API_KEY, and run setup.ps1 again until it says "Setup done". Show me what it
says about optional voice data and do what I answer; don't choose for me. Then run start.ps1, tell me to pick "I am using this for local development" in the new boss window, and
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
   put it in `.env`: `GROQ_API_KEY=gsk_...`. Run `setup.ps1` again: it also asks whether to keep optional
   voice data on this PC ("Voice data and your words"). The answer is off unless you say yes.
4. **Start the boss.** `powershell -ExecutionPolicy Bypass -File start.ps1`. The very first time,
   the new window asks whether you trust the folder: pick **Yes, I trust this folder** (once; "No,
   exit" closes the window). Then pick **I am using this for local development** (Claude Code asks
   every time, because the voice channel is not on its approved list yet).
5. **Say "Hey Jarvis".** It answers with a few words ("Yes, sir", "I'm here"), then say what you want. Or say it all in one
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

Cost: only a try at the wake word (1.5 seconds, to check for "Jarvis") and what follows it are sent, so idle hours cost nothing. A spoken reply is about
70 characters and a request a few seconds of audio, both paid from your plan's credits.

## Faster answers (optional)

Every request waits for a turn of the boss, a few seconds or more. With a TypeSafe key in `.env`
(`TYPESAFE_API_KEY=`), its Jev classifier sorts what you say first, in about 0.2 seconds, and these
skip the boss:

- **Status** ("status", "who needs me"): read straight from Claude Code's session files.
- **Small talk** ("how are you", "what time is it"): Claude Haiku answers, with `ANTHROPIC_API_KEY=`.
- **Unclear speech** (cut off, garbled, the TV): it asks "Say that again?" and listens without the
  wake word.

- **Your notes** ("what's my refund policy"), with `KNOWLEDGE_DIR=` set to a folder of short `.md` notes: Claude
  Haiku answers from them, all sent to Anthropic with each such question. `KNOWLEDGE_FACTS=` is an optional URL of
  live values as flat JSON, for `{placeholders}` in the notes. What the notes don't settle goes to the boss.

Everything else, and everything when Jev isn't sure, goes to the boss as before. To try it without
the mic: `curl -d "status" http://127.0.0.1:8790/heard`.

## Near real-time (prototype, optional, paid)

`realtime.py` swaps the slowest parts: OpenAI's Realtime API hears when you finished, instead of 5 seconds of quiet, and
reads replies aloud as the sound arrives. The wake word stays as it is (local, then the 1.5 second check for "Jarvis"), and the router stays: Jev sorts, Haiku answers
from your notes, and real work goes to the orch. Audio goes to OpenAI from the wake word to the end of each request and
all through the listening window after a line that asks you something, even if nobody speaks. On every line it says, the
text goes too. If it fails, the normal listener takes over for that turn.

Put in `.env`, then restart the voice:

```
VOICE_LISTENER=realtime.py
OPENAI_API_KEY=sk-...
```

`gpt-realtime-2.1-mini` is about $0.01 per minute you speak and $0.024 per minute it speaks, roughly $0.50 for 100
exchanges (OpenAI's price list, November 2026). `OPENAI_REALTIME_MODEL=` and `OPENAI_VOICE=` change the model and the
voice; a cloned ElevenLabs voice can't be used here. Tagalog isn't on OpenAI's list, so try your Taglish first.
`.venv\Scripts\python realtime.py measure clip.wav` prints the real timings for 16 kHz clip, plays nothing, and costs a
fraction of a cent.

Two more, with no OpenAI key: `VOICE_ACK=on` says "On it" as soon as real work goes to the orch, then its answer
later. `KNOWLEDGE_DIR=` takes several folders separated by `;`, such as Obsidian vaults: past 8,000 characters only the
notes sharing words with the question go to Anthropic, plus those they `[[link]]` to.

## Window (optional)

A small window is a chat of what it heard and what it answered, with its state, your words as you speak, and a Settings
panel for its switches, which saves them in `.env`. Electron is about 250 MB on disk and the open window uses about 140 MB of RAM of its own, so it is not
installed by default:

```
npm install --prefix window
node window/node_modules/electron/install.js
```

It opens with the voice from then on, without taking the keyboard, and stays out of screen shares and
recordings (`CAPTION_VISIBLE=1` in `.env` shows it there). `VOICE_WINDOW=off` skips it. To check it without
a mic: `node check_window.mjs`.

While the window is open, your words appear as you speak: from ElevenLabs Scribe Realtime with the pro voice
(about $0.39 per hour of speech, on top of the batch Scribe that still makes the final text), or from Groq every
4 seconds with the free voice. They are for show only. If they fail, your request still goes through.

## How it works

```
mic -> listener.py (openWakeWord "hey Jarvis", Silero VAD, Groq whisper-large-v3-turbo)
    -> voice.mjs, a Claude Code channel -> the boss session
boss -> SendMessage to t2                  "tell terminal 2 ..."
     -> ListAgents, then the idle one      "give this to whoever is free ..."
     -> spawn.ps1                          "open two more terminals ..."
     -> gui.ps1                            "open Notepad and type hello"
     -> reply tool -> Kokoro -> speaker    (the mic counts again a second before it finishes)
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
  Everything heard and said is logged to `tmp\voice.log`. A POST is refused (403) unless its Host is
  `127.0.0.1:8790` and it has no Origin header (curl, scripts) or its own, so a web page can't send the boss text.

## Good to know

- Workers bypass permission prompts, so the boss does too; Claude Code only delivers messages
  between sessions in the same permission class unless you set `crossSessionInbound` to `accept`.
- **What it hears counts as you, and the boss acts with permissions off.** Without a trained voice, anything that says
  the wake word works: someone in the room, or a video. Training lowers that, but it isn't a lock.
- **The local port has no password.** Web pages are refused, but any program on this PC can send the boss a request and
  read what it heard, and expect other Windows accounts on this PC to reach it too. Don't run it on a PC you share with
  someone you don't trust.
- A message cannot answer a permission prompt or a menu inside a worker. Answer those at that
  terminal.
- Every message a worker gets counts against your plan's usage.
- The free voice is Kokoro's calm British `bm_george`. Set `VOICE=` in `.env` to `bm_daniel`,
  `bm_fable`, `bm_lewis`, or the old American `af_heart`, then restart the boss.
- If the wake word misses you, set `WAKE_THRESHOLD=0.25` in `.env`, or train it on your voice. A faint
  high tick means it almost heard you (a score of 0.12 up to the threshold): say it again. Every try's
  score and level are in `tmp\voice.log` as `wake peak:`, to tune the threshold by. "Hey Jarvis" scores
  more steadily than "Jarvis" alone, which works but scores anywhere from 0.03 to 1. A noise gate on the
  mic (Voicemod's noise reduction) can cut the start of it.
- A score alone doesn't wake it: the model fires on sounds like the name, even a bare "hey". So when it fires, the 1.5
  seconds before go to speech to text, and only if they have "Jarvis" does the pop play, usually under a second later.
  If not, nothing happens and the log says `its words had no Jarvis`. If speech to text can't answer in 4 seconds, it
  wakes anyway. If it ignores you too often, `WAKE_NAME=off` goes back to the score alone.
- Two PCs that sync a folder: set `VOICE_SHARED=` to it on both, and only one has the voice. Turning the mic on claims it
  (a small `<host>\jarvis.json` there), and the other PC's mic closes and its replies stop as soon as the sync brings that.
  A PC that starts later stays closed until you turn its mic on.
- It listens again from a second before the end of what it says, so you can answer over its last words (`LISTEN_LEAD=` in
  `.env`, in seconds; 0 waits for its last word, a negative number waits longer). There is no echo canceller: on a mic
  near your mouth its voice barely registers, and what speech to text does hear of its last words is taken out of your
  request. Loud speakers next to the mic can still open a listening window by themselves: lower `LISTEN_LEAD=` then.
- End a request with "do it", "go", "go ahead", "send it", "let's go", "that's it" or "thank you" and it goes after 0.8
  seconds of quiet instead of 5 (`CLOSING_GAP=`, or `CLOSING_CUT=off`). At each pause the last 6 seconds go to speech to
  text, at most once every 4 seconds, and the phrase must stand on its own: "how do I do it" and "do it again" don't count.
- On waking it says a short line, different each time, and the time of day when it's been a while. They're rendered once
  per voice, so they play at once with no turn of the boss, and you can talk over them. While you're with someone: only the
  chime. `GREETING=off` for the chime always.
- Workers can leave a spoken progress line: `node progress.mjs vlog "The vlog is rendering, five minutes left."` It's
  rendered ahead, so "how's the vlog?" plays it at once with its age ("as of two minutes ago"), with no turn of the boss
  (needs `TYPESAFE_API_KEY`, which sorts the question). A line older than 12 hours is ignored, and a question it has no
  line for goes to the boss. With `--waiting`, one such line may follow a greeting, the same one at most every 30 minutes
  and never in a call (`REMINDERS=off`). With `VOICE_SHARED=`, both PCs' lines count.
- If its ears stop, it says so when they're back, with the reason if it knows and the end of the last thing it heard, and
  listens again if you were talking. The same goes for a request lost to Groq's limit or a failed transcription. Held in a
  call, and off with `CUT_OFF=off`. To restart the listener without cutting anyone off: `python listener.py restart [why]`
  waits for a quiet minute (`--now` doesn't, for trying it).
- You can say "Hey Jarvis" again while it works on your last request: it answers, and what you say next
  reaches the boss as a new message. Anything it was about to say waits until you finish.
- After everything it says, it keeps listening for 8 seconds (`LISTEN_AFTER=asked`: only after a line that asks you something), never in a call or while people are talking,
  so you can reply ("yes", "A", "tell it to go on") without the wake word. `FOLLOWUP_SECONDS=` in `.env`
  changes that; 0 turns it off.
- It never talks over you. While it records you, while the 8 seconds are open, or for 3 seconds after you
  spoke (30 at most, in case that's a TV), every line waits in a queue and plays when you're done.
- Can't hear it? Say "Hey Jarvis, hello, are you there?", or try the wake word twice in 20 seconds, and a
  silent Windows notification comes up, closed with its X, with what to check. It names what Windows can detect
  (muted, volume at zero, no speaker, a new default output), and otherwise says to check your speaker's power
  and knob. It also says if a line is held for your call or the orch is still working on your request.
- Answers and notes (the sound is muted or failed, the voice restarted) go in the window. Besides "are you
  there", a notification comes only for a question nobody just asked for and never in a call, when the orch
  closes, or for a note with no window open. **Unlike the window, a notification shows in a shared screen or
  recording.** Windows' Do Not Disturb holds them in the notification center.
- Whatever is playing (a video, Spotify) pauses at the wake word or when it speaks, and resumes when the exchange ends, if it was playing. A false wake resumes it at once, and a request with no reply within a minute too.
- Pausing something also shows the orch's terminal (titled "PC Orchestrator" or "LP Orchestrator") without taking the keyboard. It goes back when the exchange ends: minimized if it was, and left up if you clicked into it.
- It stays quiet by itself while you're with someone, and the window shows why: another app on the mic (a Meet in
  Chrome, Zoom), a meeting's window title, or, with neither, speech in 40% of the last 30 seconds (`TALK_SHARE=`). Then
  lines nobody just asked for wait unsaid, with no notification and no listening window. The wake word needs a score
  of 0.7 (`WAKE_STRICT=`). A request runs 90 seconds at most, no audio from it is kept, and one that passes is logged as
  text like any other. Say "Hey Jarvis, what's the update?" for the lines. A listening window that runs
  past 90 seconds is thrown away unsent. **It can't see** a call on your phone or one in another room, nor a
  conversation too quiet for the mic, and a video's voices count as talking. Chrome on the mic for anything else counts
  as a call. Apps that hold the mic
  all day, such as Voicemod, go in `CALL_IGNORE=` in `.env`. A meeting that lets go of a muted mic, in a tab you aren't on, looks
  like no call.
- If the mic sends nothing but silence for 30 seconds (a virtual mic such as Voicemod whose app is
  closed), it says so once. With `MIC_FALLBACK=` in `.env` (part of a second mic's name, such as
  `MIC_FALLBACK=Realtek`) it moves to that mic instead and says so.
- Not hearing you at all? Windows may be listening to another mic. Set `MIC_DEVICE=` in `.env` to
  part of your mic's name as Windows Sound settings shows it (such as `MIC_DEVICE=WebCamera`, or
  `MIC_DEVICE=Voicemod` to hear you through Voicemod), then restart the boss. If that device won't open
  (Voicemod's entry while its app is closed), the boss falls back to Windows' default mic and says so in the log.
- It wakes from across the room, then hears nothing or cuts you off? Set `VAD_BOOST=16` in `.env` and restart
  the boss. That boosts only what end-of-speech detection hears; lower it if recordings run on after you stop.
- Nothing arrives in the boss? Run `/mcp` there and check that `voice` is connected, and read
  `tmp\voice.log`.

## Voice data and your words

Optional, and off unless you choose it: `setup.ps1` asks once, or set `VOICE_DATA` in `.env` and restart.
It helps you tune how Jarvis hears you, your accent and your tone.

| `VOICE_DATA` | What it keeps |
| --- | --- |
| empty or `off` | Nothing |
| `on` | Requests for 30 days, or less past 2 GB, oldest first |
| `forever` | Requests with no age or size limit, until you delete them |

A kept request is what passed the wake word: the audio and one line (time, transcript, language, confidence,
wake score) in `%LOCALAPPDATA%\free247jarvis\voicedata`, outside any synced folder and outside git. So is each
1.5 second try that fired the wake word but had no "Jarvis" in its words, to see what it ignored. It keeps
nothing while the mic is off, nothing from a follow-up window, nothing in a call, and never continuous audio.
**Nothing here is uploaded by keeping it**, though the request itself still goes to your speech-to-text service to
be heard. Delete that folder to erase it all. With `off` or `on`, clips already there age out under the `on`
limits, including ones kept under `forever`.

**Anyone near the mic while you make a request is in the clip, and with `forever` they stay in it.** Tell them, or
turn it off for that stretch.

Whatever you choose here, `tmp\voice.log` keeps what it heard and said as text on this PC, with no limit, and
`tmp\listener.log` keeps errors. Neither is in git. Delete them to erase them.

`.venv\Scripts\python mishears.py` lists likely mishears and the stretches Whisper was unsure of. Add the
right spelling to `words.txt`, one term per line, and restart. Terms feed Whisper's prompt (Groq refuses
more than 896 characters, so later lines drop first) and Scribe's keyterms. Keep them to words: on a noisy
clip Whisper can hand them back. A reply made only of these words, such as a bare "cpd" or "yes, cpd",
counts as noise, so say it in a phrase: "cpd na".

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
  realtime.py    prototype: listener.py with OpenAI's Realtime API for ears and mouth
  words.txt      words speech to text should spell right
  mishears.py    lists likely mishears from the voice data, for review
  spawn.ps1      opens worker terminals t1 to t6 in their grid cells
  gui.ps1        screenshots, typing, keys, and clicks for Windows apps
  start.ps1      starts the boss
  setup.ps1      one-time setup (safe to re-run)
  window/        optional Electron window; voice.mjs serves its page and events
  check_boss.py  end-to-end check
```

## License

MIT
