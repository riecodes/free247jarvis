"""End-to-end check against real Claude Code sessions. Run: .venv\\Scripts\\python check_boss.py

Clips are synthesized with Kokoro, so no microphone is needed. Checks, in order:
  wake      a "Hey Claude" clip wakes the listener (and plain speech does not)
  taglish   a Taglish clip transcribes through Groq
  terminal  "tell terminal 2 to create tmp\\t2.txt" reaches t2 and the file appears
  free      "give this to whoever is free" goes to an idle session (t2 is kept busy meanwhile)
  spawn     "open one more terminal" opens a window named after its grid cell
  gui       "open Notepad and type hello" leaves a Notepad window containing hello
  reply     the boss's spoken reply comes out as a Kokoro wav

It starts the boss if it is not running (and confirms the development-channel warning for it), opens
workers t1 and t2 in this folder if they are missing, and closes every window it opened at the end.
Prints ALL PASS when every check passes.
"""
import ctypes
import ctypes.wintypes as wt
import os
import re
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
TMP = HERE / "tmp"
URL = f"http://127.0.0.1:{os.environ.get('VOICE_PORT', '8790')}/"
PS = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass"]
results: dict[str, bool] = {}


def check(name: str, ok: bool, detail: str = "") -> bool:
    results[name] = bool(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)
    return bool(ok)


def wait(fn, timeout: float, every: float = 2.0):
    """Polls fn until it returns something truthy, or None after timeout seconds."""
    end = time.time() + timeout
    while time.time() < end:
        got = fn()
        if got:
            return got
        time.sleep(every)
    return None


# Windows: Terminal windows by title, focus, keys, close.

user32 = ctypes.WinDLL("user32", use_last_error=True)
EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def windows(cls: str = "CASCADIA_HOSTING_WINDOW_CLASS") -> dict[int, str]:
    found: dict[int, str] = {}

    def each(h, _):
        name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, name, 256)
        if user32.IsWindowVisible(h) and name.value == cls:
            title = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(h, title, 512)
            found[h] = title.value
        return True

    user32.EnumWindows(EnumProc(each), 0)
    return found


def titled(name: str) -> int | None:
    """The Terminal window Claude Code titled with this session name ("<status> t2")."""
    return next((h for h, t in windows().items() if re.search(rf"(^|\s){name}$", t)), None)


def idle(name: str) -> bool:
    h = titled(name)
    return bool(h) and windows().get(h, "").startswith("✳")  # Claude Code shows ✳ while idle


def front(h: int) -> bool:
    fg = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    me = ctypes.windll.kernel32.GetCurrentThreadId()
    user32.keybd_event(0x12, 0, 0, 0), user32.keybd_event(0x12, 0, 2, 0)  # an Alt tap unlocks SetForegroundWindow
    user32.AttachThreadInput(me, fg, True)
    user32.SetForegroundWindow(h)
    user32.AttachThreadInput(me, fg, False)
    time.sleep(0.4)
    return user32.GetForegroundWindow() == h


def press_enter(h: int) -> bool:
    """Enter in window h; never in another window, where it could send someone's half-typed prompt."""
    for _ in range(5):
        if front(h):
            user32.keybd_event(0x0D, 0, 0, 0), user32.keybd_event(0x0D, 0, 2, 0)
            return True
        time.sleep(0.5)
    print(f"      could not bring window {h} to the front (foreground is {user32.GetForegroundWindow()})", flush=True)
    return False


def close(h: int) -> None:
    user32.PostMessageW(h, 0x10, 0, 0)  # WM_CLOSE: Terminal closes the tab and ends Claude Code in it


def ps(script: str) -> str:
    return subprocess.run(PS + ["-Command", script], capture_output=True, text=True, encoding="utf-8").stdout


def workers() -> dict[str, int]:
    """Worker name -> grid cell, from spawn.ps1 -List."""
    out = subprocess.run(PS + ["-File", str(HERE / "spawn.ps1"), "-List"], capture_output=True, text=True).stdout
    return {m[0]: int(m[1]) for m in re.findall(r"(t\d) cell (-?\d+)", out)}


NOTEPAD = r"""
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$A = [Windows.Automation.AutomationElement]
$doc = [Windows.Automation.PropertyCondition]::new($A::ControlTypeProperty, [Windows.Automation.ControlType]::Document)
foreach ($w in $A::RootElement.FindAll('Children', [Windows.Automation.PropertyCondition]::new($A::ClassNameProperty, 'Notepad'))) {
  $d = $w.FindFirst('Descendants', $doc)
  $t = if ($d) { $d.GetCurrentPattern([Windows.Automation.TextPattern]::Pattern).DocumentRange.GetText(-1) } else { '' }
  "$($w.Current.NativeWindowHandle)`t$($t -replace '\s+', ' ')"
}"""

# Closes the active tab of the Notepad window in front without saving it: Ctrl+W, then "Don't save".
NOTEPAD_DISCARD = r"""
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms
$A = [Windows.Automation.AutomationElement]
$w = $A::FromHandle([IntPtr]HWND)
[System.Windows.Forms.SendKeys]::SendWait('^w'); Start-Sleep -Milliseconds 800
$b = $w.FindFirst('Descendants', [Windows.Automation.PropertyCondition]::new($A::NameProperty, "Don't save"))
if ($b) { $b.GetCurrentPattern([Windows.Automation.InvokePattern]::Pattern).Invoke() }"""


def notepads() -> dict[int, str]:
    return {int(h): t for h, _, t in (line.partition("\t") for line in ps(NOTEPAD).splitlines() if "\t" in line)}


def ask(text: str) -> None:
    """Hands the boss a request, as the listener does after hearing one."""
    urllib.request.urlopen(urllib.request.Request(URL, data=text.encode(), method="POST"), timeout=10).read()
    print(f"      asked: {text}", flush=True)


def boss_up() -> bool:
    try:
        return urllib.request.urlopen(URL, timeout=3).read() == b"ok"
    except OSError:
        return False


# 1 and 2: the listener, fed synthesized clips through the same pipeline the microphone feeds.

sys.path.insert(0, str(HERE))
import listener  # noqa: E402

heard: list[dict] = []
listener.emit = lambda event, **data: heard.append({"event": event, **data})
listener.load_env()
ears = listener.Ears()


def speak(text: str, voice: str = "am_michael", lang: str = "en-us") -> np.ndarray:
    """16 kHz int16 speech from Kokoro (which speaks at 24 kHz)."""
    from scipy.signal import resample_poly

    samples, _ = ears.tts.create(text, voice=voice, speed=1.0, lang=lang)
    return (resample_poly(samples, 2, 3) * 32767).clip(-32768, 32767).astype(np.int16)


def hear(*parts: np.ndarray) -> list[dict]:
    """Feeds the parts plus 7s of quiet (enough for any timeout) and returns the events they caused."""
    heard.clear()
    audio = np.concatenate([np.zeros(listener.RATE, np.int16), *parts, np.zeros(7 * listener.RATE, np.int16)])
    for i in range(0, len(audio) - listener.CHUNK + 1, listener.CHUNK):
        ears.feed(audio[i:i + listener.CHUNK])
    return [e for e in heard if e["event"] != "status"]


def text_of(evs: list[dict]) -> str:
    return " ".join(e["text"] for e in evs if e["event"] == "heard").lower()


assert listener.strip_wake("Hey Claude, what's up?") == "what's up?"
assert listener.strip_wake("Hey, Cloud. Open Notepad") == "Open Notepad"
assert listener.strip_wake("Cloudy skies today") == "Cloudy skies today"

evs = hear(speak("Hey Claude, what time is it in Manila?"))
quiet_evs = hear(speak("The weather is nice today, so we went for a walk by the river."))
check("wake", [e["event"] for e in evs][:2] == ["wake", "heard"] and "time" in text_of(evs) and quiet_evs == [],
      f"{evs} / no wake word: {quiet_evs}")

# Tagalog read with Kokoro's Spanish voice (it has no Tagalog one), the English words with an English voice.
taglish = np.concatenate([speak("Hey Claude,"), speak("pakisabi mo kay", "em_alex", "es"), speak("terminal two"),
                          speak("na i-run niya yung", "em_alex", "es"), speak("tests,"),
                          speak("tapos sabihin mo sa akin. Salamat po.", "em_alex", "es")])
said = text_of(hear(taglish))
tagalog = [w for w in ("paki", "sabi", "kay", "niya", "yung", "tapos", "salamat", "po", "mo") if w in said]
check("taglish", "terminal" in said and "test" in said and len(tagalog) >= 3, f"{said!r} (Tagalog words: {tagalog})")
del ears

# 3 to 7: the boss and its workers, for real.

start = time.time()
opened: list[int] = []  # windows this check opened, closed again at the end
before_workers = workers()
try:
    if not boss_up():
        print("      starting the boss...", flush=True)
        old = set(windows())
        subprocess.run(PS + ["-File", str(HERE / "start.ps1")], check=True, capture_output=True)
        boss = wait(lambda: next(iter(set(windows()) - old), None), 30, 0.5)
        assert boss, "the boss window did not open"
        opened.append(boss)
        # "I am using this for local development". Enter again is harmless: the prompt is still empty.
        for _ in range(4):
            time.sleep(4)
            press_enter(boss)
            if wait(boss_up, 20):
                break
        assert boss_up(), "the voice channel did not come up; check tmp\\voice.log"
    assert wait(lambda: idle("boss"), 120), "the boss is not idle"

    for name in ("t1", "t2"):
        if not titled(name):
            old = set(windows())
            out = subprocess.run(PS + ["-File", str(HERE / "spawn.ps1"), "-Dir", str(HERE)],
                                 capture_output=True, text=True).stdout.strip()
            print(f"      {out}", flush=True)
            opened += list(set(windows()) - old)
    assert wait(lambda: idle("t1") and idle("t2"), 120), "workers t1 and t2 are not idle"

    # terminal: a task for terminal 2 by number.
    target = TMP / "t2.txt"
    target.unlink(missing_ok=True)
    ask(r"Tell terminal 2 to create the file tmp\t2.txt with the word hello in it.")
    check("terminal", wait(target.is_file, 240), f"{target} {'exists' if target.is_file() else 'missing'}")

    # free: keep t2 busy, then ask for whoever is free.
    wait(lambda: idle("t2") and idle("boss"), 120)
    ask("Tell terminal 2 to run the shell command: sleep 150. Nothing else.")
    busy = wait(lambda: titled("t2") and not idle("t2"), 120, 1)
    free = TMP / "free.txt"
    free.unlink(missing_ok=True)
    ask(r"Give this to whoever is free: create the file tmp\free.txt containing only your own session name.")
    got = wait(lambda: free.is_file() and free.read_text(encoding="utf-8", errors="replace").strip(), 240)
    check("free", bool(busy) and bool(got) and re.fullmatch(r"t[1-9]", got or "") and got != "t2",
          f"t2 busy: {bool(busy)}, done by: {got!r}")

    # spawn: one more terminal, named after the cell it lands in.
    have = workers()
    old = set(windows())
    ask("Open one more terminal.")
    new = wait(lambda: {n: c for n, c in workers().items() if n not in have}, 120)
    opened += list(set(windows()) - old)
    name, cell = next(iter(new.items())) if new else ("", 0)
    check("spawn", bool(new) and name == f"t{cell}", f"new worker: {new}")

    # gui: Notepad and hello.
    pads = notepads()
    ask("Open Notepad and type hello.")
    hello = wait(lambda: [h for h, t in notepads().items() if "hello" in t.lower() and "hello" not in pads.get(h, "").lower()], 180)
    check("gui", bool(hello), f"Notepad windows: {notepads()}")
    for h in hello or []:
        if front(h):  # keys go to the window in front, so only when Notepad really is
            ps(NOTEPAD_DISCARD.replace("HWND", str(h)))
        if h not in pads:
            close(h)

    # reply: the boss has spoken by now; its last reply is a Kokoro wav (24 kHz).
    reply = TMP / "reply.wav"
    wait(lambda: reply.is_file() and reply.stat().st_mtime > start, 60)
    ok = reply.is_file() and reply.stat().st_mtime > start
    if ok:
        with wave.open(str(reply)) as w:
            rate, seconds = w.getframerate(), w.getnframes() / w.getframerate()
        ok = rate == 24000 and seconds > 0.5
    log = (TMP / "voice.log").read_text(encoding="utf-8", errors="replace") if (TMP / "voice.log").is_file() else ""
    check("reply", ok, f"{reply.name}: {f'{rate} Hz, {seconds:.1f}s' if reply.is_file() else 'missing'}; "
                       f"last reply: {(re.findall(r'reply: (.*)', log) or [''])[-1]!r}")
finally:
    time.sleep(3)  # let the last reply finish speaking
    for h in opened:
        close(h)

names = ["wake", "taglish", "terminal", "free", "spawn", "gui", "reply"]
if all(results.get(n) for n in names):
    print("ALL PASS")
else:
    print("FAILED: " + ", ".join(n for n in names if not results.get(n)))
    sys.exit(1)
