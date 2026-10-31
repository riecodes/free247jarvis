"""Lists likely mishears from the voice data, for review. Changes nothing: add the right spelling to words.txt yourself.
Run: .venv\\Scripts\\python mishears.py
"""
import difflib
import json
import re
from collections import Counter

import listener

SHAKY = -0.6  # Whisper's avg_logprob below this: worth listening to the clip


def near_terms(rows: list[dict], terms: list[str]) -> Counter:
    """(heard, term) counts: a word close to a term but not it, or two words that join into one ("name cheap")."""
    terms = {t.lower(): t for t in terms}
    found: Counter = Counter()
    for row in rows:
        if not row.get("kept"):  # noise and prompts handed back would only bury the real ones
            continue
        words = re.findall(r"[\w']+", row["transcript"].lower())
        for word in words:
            close = difflib.get_close_matches(word, terms, n=1, cutoff=0.65)
            # A plural of a term is the term, and a piece of one is counted below as two words.
            if close and word not in close[0] and close[0] not in word:
                found[word, terms[close[0]]] += 1
        for a, b in zip(words, words[1:]):
            close = difflib.get_close_matches(a + b, terms, n=1, cutoff=0.8)
            if close and close[0] not in a and close[0] not in b:
                found[f"{a} {b}", terms[close[0]]] += 1
    return found


def shaky(rows: list[dict]) -> list[tuple[float, str, str]]:
    """(avg_logprob, clip, text) of each stretch Whisper was unsure of, worst first. Scribe gives no such score."""
    return sorted((s["avg_logprob"], row["clip"], s["text"].strip()) for row in rows for s in row.get("segments", [])
                  if s.get("avg_logprob") is not None and s["avg_logprob"] < SHAKY)


def main() -> None:
    folder = listener.data_dir()
    path = folder / "requests.jsonl" if folder else None
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path and path.is_file() else []
    print(f"{len(rows)} requests in {folder}")
    print(f"{len(listener.VOCAB)} of {listener.PROMPT_MAX} prompt characters used, {len(listener.TERMS)} terms")
    print("\nClose to a term:")
    for (heard, term), count in near_terms(rows, listener.TERMS).most_common(40):
        print(f"  {count}x  {heard}  ({term}?)")
    print("\nWhisper unsure:")
    for logprob, clip, text in shaky(rows)[:40]:
        print(f"  {logprob:.2f}  {clip}  {text}")


if __name__ == "__main__":
    main()
