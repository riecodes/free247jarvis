# free247jarvis

![License](https://img.shields.io/github/license/riecodes/free247jarvis?style=flat-square&color=green) ![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?style=flat-square&logo=windows&logoColor=white) ![macOS](https://img.shields.io/badge/macOS-untested-999999?style=flat-square&logo=apple&logoColor=white) ![Claude Code](https://img.shields.io/badge/Claude%20Code-voice-D97757?style=flat-square&logo=anthropic&logoColor=white) ![Price](https://img.shields.io/badge/price-free-brightgreen?style=flat-square)

Say **"Hey Jarvis"** and run your Claude Code terminals by voice.

A small, free, open-source voice layer for Windows, and for macOS (untested there yet). A wake word wakes a "boss" Claude Code
session, which hands your spoken request to your other Claude Code terminals, picks the one
that is free, opens new ones, and drives Windows apps for anything outside the terminal. It
answers out loud.

## What you say

- "Hey Jarvis, tell terminal 2 to run the tests."
- "Hey Jarvis, give this to whoever is free: fix the navbar on mobile."
- "Hey Jarvis, open two more terminals in the webinar folder."
- "Hey Jarvis, open Notepad and type hello."

Talk in English, Tagalog, or Taglish. The free voice answers in English (its British voice only
says English words), and so does the pro voice. When a terminal finishes, the boss tells you.

## What's new

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
  records to your pause and goes to the orch, marked as maybe people talking. The last 50 things you said are kept on
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
  `BRUSH_OFF` in listener.py). Nothing goes to the boss, the rest of the reply is dropped, your music resumes, and it
  waits for the wake word again. "I'm good", "that's all", "cancel", "wag na" and "okay na" do the same unless it just
  asked you something; then they're your answer, as are "no", "nothing" and "wala". So is a phrase the line itself used
  ("ship it now or later?" "Later.").
- **Words it says right.** Add `# say:` and the sounds after a word in `words.txt` (`vlog  # say: vlˈɒɡ`) and the
  free voice says it that way.
- **Mix the voices.** `VOICE_TTS=kokoro` hears you with ElevenLabs and answers with the free voice.
- **Settings in the window.** Turn its switches on and off in the optional window; they're saved in `.env`.
- **Spoken progress.** Workers leave a short line (`node progress.mjs`), and "how's it going?" plays it at once with
  its age.
- **One voice across two PCs.** With `VOICE_SHARED=`, only the PC whose mic you turned on listens and speaks.

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

## On macOS (untested)

The same voice runs on a Mac: openWakeWord, Silero VAD, Groq and Kokoro are the same Python packages, and sounddevice
brings its own PortAudio. No one has run it on a Mac yet, so expect to report what breaks. In Terminal:

```sh
xcode-select --install          # git, if it asks
brew install node python@3.12   # Homebrew: https://brew.sh
git clone https://github.com/riecodes/free247jarvis.git ~/dev/free247jarvis
cd ~/dev/free247jarvis
sh setup.sh                     # run it again after putting GROQ_API_KEY in .env
sh start.sh                     # the boss, in a new Terminal window
```

In the boss window pick **Yes, I trust this folder** (the first time) and **I am using this for local development**.
macOS then asks whether Terminal may use the microphone: allow it, or Jarvis hears only silence (System Settings,
Privacy & Security, Microphone, to change it later). Then say "Hey Jarvis". `.venv/bin/python listener.py train` teaches
it your voice, and the window installs the same way as on Windows (`npm install --prefix window`).

What differs from Windows:

- **Calls aren't noticed.** Windows says which app holds the mic and which meeting window is open; macOS has no public
  way to ask. Jarvis still holds its news while people are talking near the mic, but not for a muted call.
- **Only Music and Spotify pause** while it speaks: they are the players macOS lets a script pause. A video in a browser
  plays on under the voice.
- **The orch's window isn't raised** when something was paused: on a Mac that would take the keyboard too.
- **Workers open in plain Terminal windows** (`spawn.sh`), not tiled into the 3x2 grid, and apps go through Claude Code's
  own computer use instead of `gui.ps1`.
- **Notifications** come from Notification Center, under Script Editor's name.
- **Kokoro runs on the CPU.** The GPU build is for NVIDIA cards only.
- Voice data and the last 50 things heard are kept in `~/Library/Application Support/free247jarvis`.
- `check_boss.py` is Windows only. `check_voice.py`'s speaker checks stand in for Windows' sound API, so some of them
  may not run on a Mac.

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
   Optional: `VOICE_TTS=kokoro` keeps ElevenLabs for hearing and live words, and speaks with the free voice.
4. **Start the boss** as usual (`start.ps1`). `tmp\voice.log` says `Voice: Scribe and ElevenLabs` when it is on.
   `start.ps1 -Engine elevenlabs` or `-Engine free` overrides `.env` for one run.

Cost: only a try at the wake word (1.5 seconds, to check for "Jarvis") and what follows it are sent, so idle hours cost nothing. A spoken reply is about
70 characters and a request a few seconds of audio, both paid from your plan's credits.

## Faster answers (optional)

Every request waits for a turn of the boss, a few seconds or more. With a TypeSafe key in `.env`
(`TYPESAFE_API_KEY=`), its Jev classifier sorts what you say first, in about 0.2 seconds, and these
skip the boss:

- **Status** ("status", "who needs me", "what's pending?"): read straight from Claude Code's session files, plus every
  progress line marked `--waiting` on either machine.
- **Small talk** ("how are you", "what time is it"): Claude Haiku answers, with `ANTHROPIC_API_KEY=`.
- **Unclear speech** (cut off, garbled, the TV): it asks "Say that again?" and listens without the
  wake word.

- **Your notes** ("what's my refund policy"), with `KNOWLEDGE_DIR=` set to a folder of short `.md` notes: Claude
  Haiku answers from them, all sent to Anthropic with each such question. `KNOWLEDGE_FACTS=` is an optional URL of
  live values as flat JSON, for `{placeholders}` in the notes. What the notes don't settle goes to the boss.

Everything else, and everything when Jev isn't sure, goes to the boss as before. The "heard" sound that ends your
request is the only cue until then: nothing is said in between, so the boss's reply is the one spoken answer. To try
it without the mic: `curl -d "status" http://127.0.0.1:8790/heard`.

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

One more, with no OpenAI key: `KNOWLEDGE_DIR=` takes several folders separated by `;`, such as Obsidian vaults: past 8,000 characters only the
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
recordings (`CAPTION_VISIBLE=1` in `.env` shows it there). Its minimize, maximize and close buttons sit at the right of
its header, which you drag to move it; drag an edge to resize. Closing it closes only the window, and the voice goes on:
`curl -X POST http://127.0.0.1:8790/window` opens it again, or brings it to the front. `VOICE_WINDOW=off` skips it. To check it without
a mic: `node check_window.mjs`.

While the window is open, your words appear as you speak: from ElevenLabs Scribe Realtime with the pro voice
(about $0.39 per hour of speech, on top of the batch Scribe that still makes the final text), or from Groq every
4 seconds with the free voice. They are for show only. If they fail, your request still goes through.

Missed what it asked? Its choices are buttons. A reply that asks something gets one per lettered choice (A, B, C) or
numbered item, Yes and No for a plain yes-or-no question, or the labels the boss passes as `options`. A click
answers as if you said it: your listening window closes and the boss gets "B". Saying the answer still works. Only
the newest reply's buttons work, until you answer it (by voice, typing or a click) or a newer reply brings new choices.

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
  `bm_fable`, `bm_lewis`, or the old American `af_heart`, then restart the boss. Join voices with `+` to blend them
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
  A PC that starts later stays closed until you turn its mic on.
- It listens again from half a second before the end of what it says, so you can answer over its last words (`LISTEN_LEAD=`
  in `.env`, in seconds; 0 waits for its last word, a negative number waits longer). There is no echo canceller: on a mic
  near your mouth its voice barely registers, and what speech to text does hear of its last words is taken out of the start
  of your request, in order and allowing for spelling ("Be no. Yes" for "B, no." comes out as "Yes"). Words timed after it
  finished speaking are always yours, even if you read its reply aloud. Loud speakers next to the mic can still open a
  listening window by themselves: lower `LISTEN_LEAD=` then.
- A request that sounds finished goes after 2 seconds of quiet instead of 5. At that pause, [Smart Turn](https://github.com/pipecat-ai/smart-turn)
  v3.2 (BSD 2-Clause, 8.7 MB, downloaded by `listener.py fetch`) judges the last 8 seconds of your voice on the
  processor, in about a tenth of a second, from how you said it rather than the words. Only a sure "done" sends early;
  anything less waits the 5 seconds. Over the 231 kept requests of its first tuning, it cut 2% of them short and sent 14%
  sooner. Its languages include English but not Tagalog; those numbers are from English and Taglish requests both. `CLOSING_GAP=` sets the pause,
  `CLOSING_CUT=off` leaves it all to the silence. No speech to text is asked, so it costs nothing on Groq.
- On waking it says a short line, never one of the last twenty, and the time of day when it's been a while. They're rendered once
  per voice, so they play at once with no turn of the boss, and you can talk over them. While you're with someone: only the
  chime. `GREETING=off` for the chime always.
- Workers can leave a spoken progress line: `node progress.mjs vlog "The vlog is rendering, five minutes left."` It's
  rendered ahead, so "how's the vlog?" plays it at once with its age ("as of two minutes ago"), with no turn of the boss
  (needs `TYPESAFE_API_KEY`, which sorts the question). A line older than 12 hours is ignored, and a question it has no
  line for goes to the boss. So does a yes or no ("is the vlog done?", "have you finished it?") and the same topic asked
  again within 10 minutes, since the line didn't answer it. `node progress.mjs --list` prints the newest line per topic, waiting ones first. With
`--waiting`, one such line may follow the request after a greeting (never between the greeting and your words), the same one at most every 30 minutes
  and never in a call (`REMINDERS=off`). Only when the voice answered that request itself, or none came: a request the
  orch takes gets no reminder, since it would play the moment the request left, as if it were the answer. Nor does one
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
- If the mic stops sending anything for 5 seconds (changing its settings in the Sound panel resets it), the listener
  reopens it by itself; after 3 failed tries it exits and the voice starts a fresh one. A listener that stopped saving
  its state for 2 minutes counts as stuck, and `listener.py restart` stops it instead of refusing.
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

Separately, whatever `VOICE_DATA` says, the last 50 things heard after the wake word or in a listening window are kept
in `%LOCALAPPDATA%\free247jarvis\recent` (audio and transcript, never synced or uploaded), so one that got lost can be
sent again with `POST /resend-last`. Older ones are deleted as new ones come. `RECENT=off` in `.env` keeps none.

**Anyone near the mic while you make a request is in the clip, and with `forever` they stay in it.** Tell them, or
turn it off for that stretch.

Whatever you choose here, `tmp\voice.log` keeps what it heard and said as text on this PC, with no limit, and
`tmp\listener.log` keeps errors. Neither is in git. Delete them to erase them.

`.venv\Scripts\python mishears.py` lists likely mishears and the stretches Whisper was unsure of. Add the
right spelling to `words.txt`, one term per line, and restart. Terms feed Whisper's prompt (Groq refuses
more than 896 characters, so later lines drop first) and Scribe's keyterms. Keep them to words: on a noisy
clip Whisper can hand them back. A reply made only of these words, such as a bare "cpd" or "yes, cpd",
counts as noise, so say it in a phrase: "cpd na".

The free voice mispronounces a word? Put `# say:` and its sounds after it in `words.txt`, as espeak writes them
(`vlog  # say: vlˈɒɡ`, one syllable where it said "vee-log"). Plurals and "-ing" follow. Print what it says now with
`.venv\Scripts\python -c "from kokoro_onnx.tokenizer import Tokenizer; print(Tokenizer().phonemize('vlog', 'en-gb'))"`.

## Check

`.venv\Scripts\python check_boss.py` runs end to end against real sessions and prints
`ALL PASS`: the wake word, a Taglish transcription through Groq, a task for terminal 2, a task
for whoever is free, opening a terminal, Notepad, and a spoken reply. Clips are synthesized, so
no microphone is needed. It starts the boss and two workers if they are missing and closes what
it opened.

## Needs

- Windows 10 or 11 with Windows Terminal and a microphone, or macOS with Terminal (untested)
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
  spawn.sh       the same on macOS, without the grid
  gui.ps1        screenshots, typing, keys, and clicks for Windows apps
  start.ps1      starts the boss (start.sh on macOS)
  setup.ps1      one-time setup, safe to re-run (setup.sh on macOS)
  window/        optional Electron window; voice.mjs serves its page and events
  check_boss.py  end-to-end check
```

## License

MIT
