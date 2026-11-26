# 💠 freejarvis

![License](https://img.shields.io/github/license/riecodes/freejarvis?style=flat-square&color=green) ![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?style=flat-square&logo=windows&logoColor=white) ![macOS](https://img.shields.io/badge/macOS-untested-999999?style=flat-square&logo=apple&logoColor=white) ![Claude Code](https://img.shields.io/badge/Claude%20Code-voice-D97757?style=flat-square&logo=anthropic&logoColor=white) ![Price](https://img.shields.io/badge/price-free-brightgreen?style=flat-square)

Say **"Hey Jarvis"** and run your Claude Code terminals by voice.

A small, free, open-source voice layer for Windows, and for macOS (untested there yet). A wake word wakes Jarvis, a Claude Code
session, which hands your spoken request to your other Claude Code terminals, picks the one
that is free, opens new ones, and drives Windows apps for anything outside the terminal. It
answers out loud.

## What you say

- "Hey Jarvis, tell terminal 2 to run the tests."
- "Hey Jarvis, give this to whoever is free: fix the navbar on mobile."
- "Hey Jarvis, open two more terminals in the webinar folder."
- "Hey Jarvis, open Notepad and type hello."

Talk in English, Tagalog, or Taglish. The free voice answers in English (its British voice only
says English words), and so does the pro voice. When a terminal finishes, Jarvis tells you.

## What's new

- **It greets you and sets itself up.** On the first start Jarvis introduces itself out loud, then asks a few questions
  one at a time: how to address you (sir, madam, your first name, or nothing), whether talking over it stops it, the
  chimes, the spoken greeting, clap to wake, and voice data. Answer by voice or click the buttons in the window. Each
  answer is saved in `.env` at once (`ONBOARDED=1` when done; delete that line to run it again), and all of them stay
  in the window's Settings.
- **It can send as soon as your words are whole.** With `FAST_END=on` and an Anthropic key, Claude Haiku reads your
  words at each pause, and a whole request goes about 3.6 seconds after your last word instead of waiting out the
  quiet, which pays when `END_WAIT` is long. You can still go on: what you add follows as the rest of the same
  request. Off by default ("Good to know").
- **Only your voice.** With `VOICE_MATCH=on`, a request that is clearly not in your voice is dropped, by a small model
  on this PC and a voiceprint made from your kept requests. Unsure, it goes as before. Off by default ("Voice match").
- **Story mode.** Say "Hey Jarvis, story mode" (or "start story"), or type `/story`, and tell something long: no wake
  word, pauses never end it, and every part is written to `tmp/stories/<date-time>.txt` as it is heard. "End story",
  "I'm done, Jarvis", or a plain "that's it" followed by 5 seconds of quiet sends the whole telling to Jarvis as one
  message. "Hey Jarvis, ..." mid-story ends it the same way, then that request goes on. "Cancel story" sends nothing and
  keeps the file. Ten minutes of silence sends what was told. `POST /story` with `start`, `end` or `cancel` does the same
  from a script.
- **It knows when you're done.** A small local model hears whether a request sounds finished, so a finished one
  goes after 2 seconds of quiet instead of 5, with no Groq request. Unsure, it waits as before.
- **The double clap is off by default.** `CLAP=on` turns it on, and it now hears through a fan's or a PC's hum, which
  used to drown it. Two snaps or tongue clicks wake it too, which is why it is off.
- **macOS, untested.** `setup.sh`, `start.sh` and `spawn.sh` do on a Mac what the `.ps1` scripts do on Windows. The
  voice itself is the same code on both. What only Windows has is in "On macOS" below.
- **"Sir" at the start or the end.** With `VOICE_TITLE=Sir`, a line says it once, either way round ("Sir, it's
  done." or "I'm with you, sir."), and the greetings do too.
- **The window has its buttons.** Minimize, maximize and close at the top right, in the window's own colors. Closing it
  leaves the voice on, and `POST /window` brings it back.
- **Nothing you say is dropped.** A long answer in the listening window used to be thrown away after 90 seconds. Now it
  records to your pause and goes to Jarvis, marked as maybe people talking. The last 50 things you said are kept on
  this PC, so `curl -X POST http://127.0.0.1:8790/resend-last` sends the newest again if it got lost.
- **It speaks sooner.** A reply's first sentence starts while the rest is still being rendered: about 0.2 s to the first
  word instead of 1 to 2 s, and short openers like "Sir, done." are kept from the last time, so they play at once. A
  reply that arrives while you're talking is rendered meanwhile, so it starts the moment you stop.
- **More ways to say hello.** Forty greetings plus the time of day ("Good afternoon, sir", "I'm here, sir"). None of
  the last twenty comes back, so it doesn't sound like a loop.
- **Click to answer.** When it asks you to pick (A, B, C, 1, 2, yes or no), the window shows the choices as buttons, so
  you can click your answer if you missed the question.
- **Clap twice to wake it.** Two sharp claps, about a quarter second apart, wake it like "Hey Jarvis". Typing, one
  clap, three claps and knocks on the desk don't.
- **Its name first wakes it too.** "Jarvis, wake up", "OK Jarvis, status" or "Yo Jarvis" work as well as "Hey Jarvis",
  but only when you're alone with it: not in a call, with people talking, or with a video playing, and never when the
  name comes mid-sentence ("I told him Jarvis...").
- **Talk over it to stop it.** Start talking while it speaks and it stops and listens, no wake word needed. It
  now follows the loudness of its own words at the mic, so a laptop mic right next to the speakers no longer stops
  it. If nobody was talking, it finishes the reply and still listens for your answer.
- **"What?" repeats.** Say "what?", "huh?" or "come again?" and it says its last line again.
- **"Later" ends it.** Brush it off as the whole request, over a reply too: "later", "talk to you later", "not now",
  "never mind", "forget it", "false alarm", "not you", "my bad", "bye", "mamaya na", "hindi ikaw" (the list is
  `BRUSH_OFF` in listener.py). Nothing goes to Jarvis, the rest of the reply is dropped, your music resumes, and it
  waits for the wake word again. "I'm good", "that's all", "cancel", "wag na", "okay na", and closers like "no,
  nothing, thank you", "thanks" or "salamat" do the same unless it just asked you something; then they're your answer,
  as is a bare "no". So is a phrase its question itself used ("ship it now or later?" "Later.").
- **Words it says right.** Add `# say:` and the sounds after a word in `words.txt` (`vlog  # say: vlˈɒɡ`) and the
  free voice says it that way.
- **Settings in the window.** Turn its switches on and off in the optional window; they're saved in `.env`.
- **Spoken progress.** Workers leave a short line (`node progress.mjs`), and "how's it going?" plays it at once with
  its age.
- **One voice across two PCs.** With `VOICE_SHARED=`, only the PC whose mic you turned on listens and speaks.

## Setup (once)

### One line

**Windows** (PowerShell):

```powershell
irm https://webinar.riecodes.com/jarvis.ps1 | iex
```

**macOS or Linux** (Terminal):

```bash
curl -fsSL https://webinar.riecodes.com/jarvis.sh | bash
```

It does everything, with or without Claude Code already on your computer: installs what is missing
(Git, Python, Node.js, Windows Terminal or Homebrew, and Claude Code itself), puts freejarvis in
`~/freejarvis`, opens the Groq keys page and asks you to paste your free key (the only thing you type),
downloads the voice models, installs the window, and starts Jarvis. The first time, pick **Yes, I trust
this folder** and **I am using this for local development** in the new window (and log in to Claude
Code if it is new). Jarvis then greets you and asks the rest out loud: what to call you, and which
switches you want. Run the same line again any time to update. On Linux it installs but does not start
the window yet (it tells you the command).

### Step by step

If you would rather do it by hand:

1. **Get it.** `git clone https://github.com/riecodes/freejarvis.git`, or *Code > Download
   ZIP* on GitHub and unzip it.
2. **Install.** In that folder: `powershell -ExecutionPolicy Bypass -File setup.ps1`. It says
   what is missing, installs the Python and Node packages, and downloads the models (about
   360 MB). With an NVIDIA graphics card it also installs the GPU build of ONNX Runtime, so the
   voice speaks in about half a second instead of two (that needs the CUDA toolkit and cuDNN;
   without them it runs on the processor).
3. **Add your Groq key.** Get a free key at <https://console.groq.com/keys> (no card needed) and
   put it in `.env`: `GROQ_API_KEY=gsk_...`. Run `setup.ps1` again until it says "Voice packages and models are ready".
4. **Start Jarvis.** `powershell -ExecutionPolicy Bypass -File start.ps1`. The very first time,
   the new window asks whether you trust the folder: pick **Yes, I trust this folder** (once; "No,
   exit" closes the window). Then pick **I am using this for local development** (Claude Code asks
   every time, because the voice channel is not on its approved list yet).
5. **Say "Hey Jarvis".** It answers with a few words ("Yes, sir", "I'm here"), then say what you want. Or say it all in one
   breath: "Hey Jarvis, status".

Optional: `.venv\Scripts\python listener.py train` teaches the wake word your voice (five
"Hey Jarvis"es and three sentences), which cuts false wakes from other voices and the TV.

## On macOS (untested)

The same voice runs on a Mac: openWakeWord, Silero VAD, Groq and Kokoro are the same Python packages, and sounddevice
brings its own PortAudio. No one has run it on a Mac yet, so expect to report what breaks. In Terminal:

```sh
xcode-select --install          # git, if it asks
brew install node python@3.12   # Homebrew: https://brew.sh
git clone https://github.com/riecodes/freejarvis.git ~/dev/freejarvis
cd ~/dev/freejarvis
sh setup.sh                     # run it again after putting GROQ_API_KEY in .env
sh start.sh                     # Jarvis, in a new Terminal window
```

In Jarvis window pick **Yes, I trust this folder** (the first time) and **I am using this for local development**.
macOS then asks whether Terminal may use the microphone: allow it, or Jarvis hears only silence (System Settings,
Privacy & Security, Microphone, to change it later). Then say "Hey Jarvis". `.venv/bin/python listener.py train` teaches
it your voice, and the window installs the same way as on Windows (`npm install --prefix window`).

What differs from Windows:

- **Calls aren't noticed.** Windows says which app holds the mic and which meeting window is open; macOS has no public
  way to ask. Jarvis still holds its news while people are talking near the mic, but not for a muted call.
- **Only Music and Spotify pause** while it speaks: they are the players macOS lets a script pause. A video in a browser
  plays on under the voice.
- **Jarvis's window isn't raised** when something was paused: on a Mac that would take the keyboard too.
- **Workers open in plain Terminal windows** (`spawn.sh`), not tiled into the 3x2 grid, and apps go through Claude Code's
  own computer use instead of `gui.ps1`.
- **Notifications** come from Notification Center, under Script Editor's name.
- **Kokoro runs on the CPU.** The GPU build is for NVIDIA cards only.
- Voice data and the last 50 things heard are kept in `~/Library/Application Support/free247jarvis`.
- `check_jarvis.py` is Windows only. `check_voice.py`'s speaker checks stand in for Windows' sound API, so some of them
  may not run on a Mac.

## Pro voice (projarvis, optional, paid)

The pro voice is a separate, paid add-on, projarvis: ElevenLabs hears you and Jarvis answers in your own cloned
voice. freejarvis stays the same and loads it when `JARVIS_PRO=` in `.env` names its folder (`pro()` in
`listener.py`); if it fails, that request falls back to Groq and Kokoro. Without it, nothing changes.

## Faster answers (optional)

Every request waits for a turn of Jarvis, a few seconds or more. With a TypeSafe key in `.env`
(`TYPESAFE_API_KEY=`), its Jev classifier sorts what you say first, in about 0.2 seconds, and these
skip Jarvis:

- **Status** ("status", "who needs me", "what's pending?"): read straight from Claude Code's session files, plus every
  progress line marked `--waiting` on either machine.
- **Small talk** ("how are you", "what time is it"): Claude Haiku answers, with `ANTHROPIC_API_KEY=`. A plain "hello",
  "how are you" or "thanks" gets a set answer at once: Jev picks it in the same call, so Haiku isn't asked.
- **One session or piece of work** with no progress line of its own ("how's the research going?"): Haiku answers from
  the board (this PC's sessions and both PCs' newest progress lines, sent to Anthropic with such a question), or passes
  it to Jarvis when that doesn't settle it.
- **Unclear speech** (cut off, garbled, the TV): it asks "Say that again?" and listens without the
  wake word.

- **Your notes** ("what's my refund policy"), with `KNOWLEDGE_DIR=` set to a folder of short `.md` notes: Claude
  Haiku answers from them, all sent to Anthropic with each such question. `KNOWLEDGE_FACTS=` is an optional URL of
  live values as flat JSON, for `{placeholders}` in the notes. What the notes don't settle goes to Jarvis.

Everything else, and everything when Jev isn't sure, goes to Jarvis as before. The "heard" sound that ends your
request is the only cue until then: nothing is said in between, so Jarvis's reply is the one spoken answer. To try
it without the mic: `curl -d "status" http://127.0.0.1:8790/heard`.

Every request Jarvis gets ends with the board in parentheses (this PC's sessions and the newest progress lines), so
it can answer without a lookup of its own.

## Near real-time (prototype, optional, paid)

`realtime.py` swaps the slowest parts: OpenAI's Realtime API hears when you finished, instead of 5 seconds of quiet, and
reads replies aloud as the sound arrives. The wake word stays as it is (local, then the 1.5 second check for "Jarvis"), and the router stays: Jev sorts, Haiku answers
from your notes, and real work goes to Jarvis. Audio goes to OpenAI from the wake word to the end of each request and
all through the listening window after a line that asks you something, even if nobody speaks. On every line it says, the
text goes too. If it fails, the normal listener takes over for that turn.

Put in `.env`, then restart the voice:

```
VOICE_LISTENER=realtime.py
OPENAI_API_KEY=sk-...
```

`gpt-realtime-2.1-mini` is about $0.01 per minute you speak and $0.024 per minute it speaks, roughly $0.50 for 100
exchanges (OpenAI's price list, November 2026). `OPENAI_REALTIME_MODEL=` and `OPENAI_VOICE=` change the model and the
voice; the pro voice's clone can't be used here. Tagalog isn't on OpenAI's list, so try your Taglish first.
`.venv\Scripts\python realtime.py measure clip.wav` prints the real timings for 16 kHz clip, plays nothing, and costs a
fraction of a cent.

One more, with no OpenAI key: `KNOWLEDGE_DIR=` takes several folders separated by `;`, such as Obsidian vaults: past 8,000 characters only the
notes sharing words with the question go to Anthropic, plus those they `[[link]]` to.

## Gemini Live (trial, optional, free tier)

`gemini.py` puts Google's Gemini Live in front of the router, after the wake word only (the wake word stays local, and
nothing reaches Google before it). Gemini hears when you finished and answers small talk itself (a greeting, thanks,
the time) in its own voice. Anything else it hands over at once, and the request goes on as it does today: your clip to
Groq for the words, then the router and Jarvis, spoken by Kokoro. The listener's own end of speech runs alongside, so
when Gemini fails or stays quiet, the request ends as it always has.

```
VOICE_LISTENER=gemini.py
GEMINI_API_KEY=...
```

Then restart the listener. A free key from aistudio.google.com/apikey, on a project with no billing, stays on the free
tier: no daily cap on Live, 65,000 tokens a minute (about 25 minutes of audio a minute, far more than one voice needs).
**On the free tier Google may use what you send to improve its products**, and people may read it: every request
from the wake word to its end goes there. Leave `VOICE_LISTENER` empty to stop.

Measured on 2026-11-13 with your own kept requests, from the last word (20 of the newest with a pause of 1.5 s or
more, as 81% of them have):

| | Today | With Gemini |
|---|---|---|
| Small talk, first sound | about 6 s (3.5 s of quiet, text, router, Kokoro) | 1.1 to 1.8 s |
| Request reaches the router | about 4.5 s (3.5 s of quiet, then the text) | 2.5 to 3.5 s for about half; the rest as today |
| Cut off mid-request | 6.6% of all requests | none of the 20 |

Gemini alone cut off 5 of the 20 (3 with 2.5 s of quiet, at a second slower). So its hand-over counts only when the
local Smart Turn also hears you finished (`GEMINI_GATE=`, 0.35); the 5 it cut off all scored lower, and a hand-over it
turns down leaves the request to the listener's own 4 s of quiet, as today.

What to know before keeping it:

- Two voices: Gemini's (`GEMINI_VOICE=`, Puck by default) for small talk, Kokoro for everything else.
- Taglish: Gemini's own transcript of it is poor ("Pakisabi mo kay terminal 2, ..." came back as "Terminal 2"), which is
  why hand-offs use Groq's. It may still take a Taglish greeting for work, which only costs the usual path.
- It is told to answer small talk only. Told to answer general questions too, it made up a ferry schedule and said "No
  response needed" aloud, so keep it that way.
- Long pauses: Gemini hands over after 1.5 s of quiet (`GEMINI_SILENCE_MS=`). If it still cuts you off, raise
  `GEMINI_GATE=` (fewer fast hand-overs) or the quiet (slower ones).
- `GEMINI_LIVE_MODEL=` changes the model (gemini-3.8-live by default; it needs one with non-blocking tools).

## Window (optional)

A small window is a chat of what it heard and what it answered, with its state, your words as you speak, and a Settings
panel for its switches, which saves them in `.env`. Electron is about 250 MB on disk and the open window uses about 140 MB of RAM of its own, so it is not
installed by default:

```
npm install --prefix window
node window/node_modules/electron/install.js
```

It opens with the voice from then on, without taking the keyboard, and stays out of screen shares and
recordings (`CAPTION_VISIBLE=1` in `.env` shows it there). Its minimize, maximize and close buttons sit at the right of
its header, which you drag to move it; drag an edge to resize. Closing it closes only the window, and the voice goes on:
`curl -X POST http://127.0.0.1:8790/window` opens it again, or brings it to the front. `VOICE_WINDOW=off` skips it. To check it without
a mic: `node check_window.mjs`.

While the window is open, your words appear as you speak: from Groq every 4 seconds (or from the pro voice's ears
with projarvis). They are for show only. If they fail, your request still goes through.

Missed what it asked? Its choices are buttons. A reply that asks something gets one per lettered choice (A, B, C) or
numbered item, Yes and No for a plain yes-or-no question, or the labels Jarvis passes as `options`. A click
answers as if you said it: your listening window closes and Jarvis gets "B". Saying the answer still works. Only
the newest reply's buttons work, until you answer it (by voice, typing or a click) or a newer reply brings new choices.

## How it works

```
mic -> listener.py (openWakeWord "hey Jarvis", Silero VAD, Groq whisper-large-v3-turbo)
    -> voice.mjs, a Claude Code channel -> Jarvis session
Jarvis -> SendMessage to t2                  "tell terminal 2 ..."
     -> ListAgents, then the idle one      "give this to whoever is free ..."
     -> spawn.ps1                          "open two more terminals ..."
     -> gui.ps1                            "open Notepad and type hello"
     -> reply tool -> Kokoro -> speaker    (the mic counts again a second before it finishes)
```

- **Jarvis** is a Claude Code session named `jarvis` in the `jarvis` folder. Its `CLAUDE.md` says
  how to route, and its `.mcp.json` loads the voice channel, so no other session loads it.
- **Workers** are Claude Code sessions named after their cell in a 3x2 grid of terminals, `t1`
  (top left) to `t6` (bottom right), so "terminal 2" is session `t2`. `spawn.ps1` opens them
  in Windows Terminal with `--dangerously-skip-permissions`, by default in the folder that
  holds freejarvis. Claude Code's own messaging between sessions carries the requests; no
  keystrokes are sent to them.
- **Windows apps:** Claude Code's computer use runs only on macOS in the CLI, so Jarvis uses
  `gui.ps1` instead: screenshots to look, and app launch, typing, keys, and clicks to act.
- **Typed requests** work too: `curl -d "tell terminal 2 to run the tests" http://127.0.0.1:8790/`.
  Everything heard and said is logged to `tmp\voice.log`. A POST is refused (403) unless its Host is
  `127.0.0.1:8790` and it has no Origin header (curl, scripts) or its own, so a web page can't send Jarvis text.

## Good to know

- Workers bypass permission prompts, so Jarvis does too; Claude Code only delivers messages
  between sessions in the same permission class unless you set `crossSessionInbound` to `accept`.
- **What it hears counts as you, and Jarvis acts with permissions off.** Without a trained voice, anything that says
  the wake word works: someone in the room, or a video. Training lowers that, but it isn't a lock.
- **The local port has no password.** Web pages are refused, but any program on this PC can send Jarvis a request and
  read what it heard, and expect other Windows accounts on this PC to reach it too. Don't run it on a PC you share with
  someone you don't trust.
- A message cannot answer a permission prompt or a menu inside a worker. Answer those at that
  terminal.
- Every message a worker gets counts against your plan's usage.
- The free voice is Kokoro's calm British `bm_george`. Set `VOICE=` in `.env` to `bm_daniel`,
  `bm_fable`, `bm_lewis`, or the old American `af_heart`, then restart Jarvis. Join voices with `+` to blend them
  evenly (a name twice weighs double): `am_puck+af_heart` sits between a male and a female voice (about 150 Hz,
  where George is 140 and Heart 192) and rises and falls more than George does.
- No sound after a request, or when it stops listening? A file in `sounds/local` (`listen.wav`, `heard.wav`,
  `close.wav`, `near.wav`) replaces the shipped one, and a silent one mutes that cue. The log says which at start
  ("Silent cue sounds"); delete the file to get the shipped sound back.
- If the wake word misses you, set `WAKE_THRESHOLD=0.25` in `.env`, or train it on your voice. A faint
  high tick means it almost heard you (a score of 0.12 up to the threshold): say it again. Every try's
  score and level are in `tmp\voice.log` as `wake peak:`, to tune the threshold by. "Hey Jarvis" scores
  more steadily than "Jarvis" alone, which works but scores anywhere from 0.03 to 1. A noise gate on the
  mic (Voicemod's noise reduction) can cut the start of it.
- A score alone doesn't wake it: the model fires on sounds like the name, even a bare "hey". So when it fires, the 1.5
  seconds before go to speech to text, and only if they have "Jarvis" does the pop play, usually under a second later.
  If not, nothing happens and the log says `its words had no Jarvis`. If speech to text can't answer in 4 seconds, it
  wakes anyway. If it ignores you too often, `WAKE_NAME=off` goes back to the score alone.
- Its name first ("Jarvis, wake up", "OK Jarvis, status") scores only 0.1 to 0.45, under the threshold. So when a try
  scores 0.1 or more and fails, its 1.5 seconds go to speech to text, at most once every 2 seconds, and it wakes if the
  words open with the name (after "hey", "ok", "yo" or "so" at most). Anything said after the name is the start of the
  request. In a call, with people talking or a video playing, this check is off, so the name in passing can't wake it;
  "Hey Jarvis" and a double clap (`CLAP=on`) still do. The log says `Woke on its name first`. `WAKE_NAME=off` turns it off too.
- `CLAP=on` (also in the window's Settings) wakes it on a double clap: two sharp, bright sounds 0.12 to 0.6 seconds
  apart, each well above the room (and at least `CLAP_LEVEL=`, 250 by default), with no other sharp sound or speech for
  half a second around them. It is measured on the top of the sound, so a fan's or a PC's hum doesn't hide it. It also
  works in a call or over a video; it can't stop a reply, though. It is off by default, because it can't tell two claps
  from two snaps or two tongue clicks. If it misses, lower `CLAP_LEVEL=` (150); if it wakes on its own, raise it. The log
  says `Double clap`.
- Two PCs that sync a folder: set `VOICE_SHARED=` to it on both, and only one has the voice. Turning the mic on claims it
  (a small `<host>\jarvis.json` there), and the other PC's mic closes and its replies stop as soon as the sync brings that.
  A PC that starts later stays closed until you turn its mic on. Before powering a PC off, `node release.mjs` closes its
  mic and marks its claim released: the other PC's mic then opens by itself, within seconds or when it starts.
- It listens again from half a second before the end of what it says, so you can answer over its last words (`LISTEN_LEAD=`
  in `.env`, in seconds; 0 waits for its last word, a negative number waits longer). There is no echo canceller: on a mic
  near your mouth its voice barely registers, and what speech to text does hear of its last words is taken out of the start
  of your request, in order and allowing for spelling ("Be no. Yes" for "B, no." comes out as "Yes"). Words timed after it
  finished speaking are always yours, even if you read its reply aloud. Loud speakers next to the mic can still open a
  listening window by themselves: lower `LISTEN_LEAD=` then.
- A request that sounds finished goes after 2 seconds of quiet instead of 4. At that pause, [Smart Turn](https://github.com/pipecat-ai/smart-turn)
  v3.2 (BSD 2-Clause, 8.7 MB, downloaded by `listener.py fetch`) judges the last 8 seconds of your voice on the
  processor, in about a tenth of a second, from how you said it rather than the words. A sure "done" (0.95) sends at 2
  seconds, a likely one (0.7) at 3, and anything less waits the 4 seconds (`END_WAIT=`, 5 until November 13). Over 319 kept
  requests, that cut 6.6% of them short (4.1% with the old 5 s) and brought the average wait after the last word from
  4.6 to 3.5 seconds. Sooner doesn't work for this voice: at 0.8 seconds even a 0.98 bar cut twice as many short for a
  sixth of a second. Its languages include English but not Tagalog; those numbers are from English and Taglish requests both. `CLOSING_GAP=` sets the pause,
  `CLOSING_CUT=off` leaves it all to the silence. Speech to text starts in the background at 2 seconds of quiet, so the
  text is ready when the wait ends (about a second sooner); if you go on talking, that try is dropped.
- `FAST_END=on` (off by default; "Send when your words are whole" in the window's Settings) lets the words decide,
  not the sound. At 1.5 seconds of quiet, speech to text runs on what you've said so far and Claude Haiku answers one
  word, DONE or MORE, for English, Tagalog or Taglish. On DONE the request goes at once, about 3.6 seconds after your
  last word (the 1.5 of quiet, a second of speech to text, 1.1 for Haiku), and the mic stays open until `END_WAIT` of
  quiet in all: what you say then goes to Jarvis as the rest of the same request, with the first part quoted beside
  it. So it pays when `END_WAIT` is long: at 6 seconds it sends 2.4 sooner, at the default 4 hardly at all. On MORE, no
  answer in 2 seconds, an error or no key, the rules above decide as before. It stays out of calls, people talking,
  story mode, voice training, requests past 30 seconds, and `FOLLOWUP_SECONDS=0`. It needs `ANTHROPIC_API_KEY`, sends
  the words of each request to Anthropic, and costs one small Haiku request and one more speech-to-text request per
  pause of 1.5 seconds or more: about one and a half a request here, since half of 401 kept requests hold such a
  pause. Sound alone can't do this for this voice: at 2 seconds of quiet Smart Turn tells a pause from an ending with
  an AUC of 0.69, so every earlier bar cut more requests short. Measured on November 23 on the words of those 401
  requests (648 Haiku calls, under 2 cents): Haiku says DONE on 80% of the 300 that end within 30 seconds, so 52% of
  all requests go sooner, and with `END_WAIT=6` the average wait after the last word falls from 5.4 to 4.3 seconds. A
  wrong DONE is a pause after words that read whole, with more to come: the words before a pause of 3 seconds or more
  read whole to it 3 to 6 times in 10. Few pauses outlast 3.6 seconds, so about 2 requests in 100 reach Jarvis in
  two parts (7 or 8 of the 401), and it may have started on the first. A sooner send means more of them (the numbers
  are by `FAST_TEXT` in `listener.py`).
- On waking it says a short line, never one of the last twenty, and the time of day when it's been a while. They're rendered once
  per voice, so they play at once with no turn of Jarvis, and you can talk over them. While you're with someone: only the
  chime. `GREETING=off` for the chime always.
- Workers can leave a spoken progress line: `node progress.mjs vlog "The vlog is rendering, five minutes left."` It's
  rendered ahead, so "how's the vlog?" plays it at once with its age ("as of two minutes ago"), with no turn of Jarvis
  (needs `TYPESAFE_API_KEY`, which sorts the question). A line older than 12 hours is ignored, and a question it has no
  line for goes to Jarvis. So does a yes or no ("is the vlog done?", "have you finished it?") and the same topic asked
  again within 10 minutes, since the line didn't answer it. `node progress.mjs --list` prints the newest line per topic, waiting ones first. With
`--waiting`, one such line may follow the request after a greeting (never between the greeting and your words), the same one at most every 30 minutes
  and never in a call (`REMINDERS=off`). Only when the voice answered that request itself, or none came: a request
  Jarvis takes gets no reminder, since it would play the moment the request left, as if it were the answer. Nor does one
  whose answer already read the waiting lines ("what's pending?"), and a yes or no to the status ("is anything running?")
  gets the yes or no first. With `VOICE_SHARED=`, both PCs' lines count.
- Say "what?", "huh?", "ha?", "ano?", "again?" or "come again?" within a minute and a half of a line, and it says that line
  again. Other short follow-ups are read as replies to what it just said, and a plain "hmm" or "okay" after a line that
  asked nothing gets no answer.
- Talk over a reply and it stops and listens, with no wake word. Your voice must beat the reply's echo at the mic
  (`TALK_OVER_RATIO`, 2 by default), for over half a second, after the reply's first second. The echo it expects
  follows the reply's own words, loud and quiet, so a laptop's mic beside its speakers doesn't stop it. Each reply
  logs `loudest speech Nx its echo` in `tmp\voice.log`, to tune the ratio by. If no words come of it, the rest of the
  reply plays, then it listens for your answer if it asked something. In a call, with people talking, or with a video it couldn't pause, only "Hey Jarvis" stops it.
  `TALK_OVER=off` leaves only "Hey Jarvis". Not in the realtime voice.
- If its ears stop, it says so when they're back, with the reason if it knows and the end of the last thing it heard, and
  listens again if you were talking. The same goes for a request lost to Groq's limit or a failed transcription. Held in a
  call, and off with `CUT_OFF=off`. To restart the listener without cutting anyone off: `python listener.py restart [why]`
  waits for a quiet minute (`--now` doesn't, for trying it).
- You can say "Hey Jarvis" again while it works on your last request: it answers, and what you say next
  reaches Jarvis as a new message. Anything it was about to say waits until you finish.
- After everything it says, it keeps listening for 8 seconds (`LISTEN_AFTER=asked`: only after a line that asks you something), never in a call or while people are talking,
  so you can reply ("yes", "A", "tell it to go on") without the wake word. `FOLLOWUP_SECONDS=` in `.env`
  changes that; 0 turns it off.
- It never talks over you. While it records you, while the 8 seconds are open, or for 3 seconds after you
  spoke (30 at most, in case that's a TV), every line waits in a queue and plays when you're done.
- Can't hear it? Say "Hey Jarvis, hello, are you there?", or try the wake word twice in 20 seconds, and a
  silent Windows notification comes up, closed with its X, with what to check. It names what Windows can detect
  (muted, volume at zero, no speaker, a new default output), and otherwise says to check your speaker's power
  and knob. It also says if a line is held for your call or Jarvis is still working on your request.
- Answers and notes (the sound is muted or failed, the voice restarted) go in the window. Besides "are you
  there", a notification comes only for a question nobody just asked for and never in a call, when Jarvis
  closes, or for a note with no window open. **Unlike the window, a notification shows in a shared screen or
  recording.** Windows' Do Not Disturb holds them in the notification center.
- Whatever is playing (a video, Spotify) pauses at the wake word or when it speaks, and resumes when the exchange ends, if it was playing. A false wake resumes it at once, and a request with no reply within a minute too.
- Pausing something also shows Jarvis's terminal (titled "PC Orchestrator" or "LP Orchestrator") without taking the keyboard. It goes back when the exchange ends: minimized if it was, and left up if you clicked into it.
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
- If the mic stops sending anything for 5 seconds (changing its settings in the Sound panel resets it), the listener
  reopens it by itself; after 3 failed tries it exits and the voice starts a fresh one. A listener that stopped saving
  its state for 2 minutes counts as stuck, and `listener.py restart` stops it instead of refusing.
- Wrong mic or speaker? Pick them under Microphone and Output in the window's Settings: it applies at once, with no
  restart, and saves `MIC_DEVICE` and `OUTPUT_DEVICE` in this computer's `.env`. With Output on Windows default, it
  follows Windows when the sound moves (Bluetooth headphones connecting) within a few quiet seconds.
- Not hearing you at all? Windows may be listening to another mic. Set `MIC_DEVICE=` in `.env` to
  part of your mic's name as Windows Sound settings shows it (such as `MIC_DEVICE=WebCamera`, or
  `MIC_DEVICE=Voicemod` to hear you through Voicemod), then restart Jarvis. If that device won't open
  (Voicemod's entry while its app is closed), Jarvis falls back to Windows' default mic and says so in the log.
- It wakes from across the room, then hears nothing or cuts you off? Set `VAD_BOOST=16` in `.env` and restart
  Jarvis. That boosts only what end-of-speech detection hears; lower it if recordings run on after you stop.
- Nothing arrives in Jarvis? Run `/mcp` there and check that `voice` is connected, and read
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

Separately, whatever `VOICE_DATA` says, the last 50 things heard after the wake word or in a listening window are kept
in `%LOCALAPPDATA%\free247jarvis\recent` (audio and transcript, never synced or uploaded), so one that got lost can be
sent again with `POST /resend-last`. Older ones are deleted as new ones come. `RECENT=off` in `.env` keeps none.

**Anyone near the mic while you make a request is in the clip, and with `forever` they stay in it.** Tell them, or
turn it off for that stretch.

Whatever you choose here, `tmp\voice.log` keeps what it heard and said as text on this PC, with no limit, and
`tmp\listener.log` keeps errors. Neither is in git. Delete them to erase them.

`.venv\Scripts\python mishears.py` lists likely mishears and the stretches Whisper was unsure of. Add the
right spelling to `words.txt`, one term per line, and restart. Terms feed Whisper's prompt (Groq refuses
more than 896 characters, so later lines drop first) and the pro voice's keyterms. Keep them to words: on a noisy
clip Whisper can hand them back. A reply made only of these words, such as a bare "cpd" or "yes, cpd",
counts as noise, so say it in a phrase: "cpd na".

The free voice mispronounces a word? Put `# say:` and its sounds after it in `words.txt`, as espeak writes them
(`vlog  # say: vlˈɒɡ`, one syllable where it said "vee-log"). Plurals and "-ing" follow. Print what it says now with
`.venv\Scripts\python -c "from kokoro_onnx.tokenizer import Tokenizer; print(Tokenizer().phonemize('vlog', 'en-gb'))"`.

## Voice match (optional)

Off unless you choose it: `VOICE_MATCH=on` in `.env`, or "Only my voice" in the window's Settings. A request that is
clearly not in your voice is then dropped: nothing goes to Jarvis, the window says so with its score, and
`POST /resend-last` sends it anyway.

It needs a voiceprint, made from your kept requests (so `VOICE_DATA=on` for a while first):

```
.venv\Scripts\python voiceprint.py enroll
```

That reads the kept clips past their greeting, leaves out the ones that aren't the main voice (a video, someone
else), and saves 192 numbers to `%LOCALAPPDATA%\free247jarvis\voiceprint.npz`, next to the voice data: outside git and
any synced folder, so each PC makes its own. Run it again after a new mic or room. Delete the file to erase it.

Each request is compared with it on this PC, on the processor, in about a tenth of a second while speech to text
runs: [3D-Speaker](https://github.com/modelscope/3D-Speaker) CAM++ (Apache-2.0, 28 MB, downloaded once from the
[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) releases and checked against a pinned SHA-256). Only the speech
is compared, never Jarvis's own voice at the start of a clip, and nothing is uploaded.

How sure it is depends on how much was said. Measured 2026-11-23 on 330 kept requests, each half's voiceprint scoring
the other half, against 22 strangers from LibriSpeech:

| Speech | You, dropped | A stranger, dropped |
| --- | --- | --- |
| 0.5 s | 0.9% | 63% |
| 1 s | 0.4% | 89% |
| 2 s | 0.4% | 97% |
| 4 s or more | 0.5% | 99% |

Under half a second of speech nothing is judged, so someone else's bare "yes" can still get through. The strangers
were on other mics: someone in your room, on your mic, may score nearer to you. A clone of your voice passes. Of the
last 50 things heard that morning it dropped 3: Jarvis's own voice twice, and a one-word sound. Unsure in any way (no
voiceprint, too little speech, the model missing or failing, no answer in 5 seconds): the request goes as before.
`VOICE_MATCH_MIN=` moves the bar (0.3; shorter speech gets a share of it), and `tmp\voice.log` shows each request's
score as "Voice match".

## Check

`.venv\Scripts\python check_jarvis.py` runs end to end against real sessions and prints
`ALL PASS`: the wake word, a Taglish transcription through Groq, a task for terminal 2, a task
for whoever is free, opening a terminal, Notepad, and a spoken reply. Clips are synthesized, so
no microphone is needed. It starts Jarvis and two workers if they are missing and closes what
it opened.

## Needs

- Windows 10 or 11 with Windows Terminal and a microphone, or macOS with Terminal (untested)
- [Claude Code](https://code.claude.com) 2.1.234 or later, signed in with a Pro or Max plan
- Python 3.10 to 3.13 and Node 20 or later
- A free Groq key for speech to text: <https://console.groq.com/keys> (about $0.04 per hour of
  audio past the free tier)

## Files

```
freejarvis/
  jarvis/        the Jarvis session's folder: CLAUDE.md (routing) and .mcp.json (voice channel)
  voice.mjs      the voice channel (MCP server); runs listener.py
  listener.py    wake word, end of speech, speech to text, Kokoro voice, voice training
  realtime.py    prototype: listener.py with OpenAI's Realtime API for ears and mouth
  gemini.py      trial: listener.py with Gemini Live hearing the end and answering small talk
  words.txt      words speech to text should spell right
  mishears.py    lists likely mishears from the voice data, for review
  voiceprint.py  voice match: makes your voiceprint, and scores each request against it
  spawn.ps1      opens worker terminals t1 to t6 in their grid cells
  spawn.sh       the same on macOS, without the grid
  gui.ps1        screenshots, typing, keys, and clicks for Windows apps
  start.ps1      starts Jarvis (start.sh on macOS)
  setup.ps1      one-time setup, safe to re-run (setup.sh on macOS)
  window/        optional Electron window; voice.mjs serves its page and events
  check_jarvis.py  end-to-end check
```

## License

MIT
