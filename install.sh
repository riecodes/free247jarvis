#!/bin/bash
# One-line install of freejarvis on macOS (untested there yet) or Linux, safe to run again (it updates):
#   curl -fsSL webinar.riecodes.com/jarvis.sh | bash
# Installs what is missing (Homebrew, Git, Python, Node, Claude Code), clones or updates freejarvis in
# ~/freejarvis, asks for your free Groq key once, runs setup.sh, installs the window, then starts Jarvis.
# For testing: JARVIS_DIR, JARVIS_BRANCH, JARVIS_GROQ_KEY, JARVIS_NO_WINDOW=1, JARVIS_NO_START=1.
# Everything sits in main(): bash reads this script from the pipe, so a step that reads stdin would eat the rest.
main() {
  local dir="${JARVIS_DIR:-$HOME/freejarvis}" branch="${JARVIS_BRANCH:-main}" bin="$HOME/.local/bin" brew="" key="" missing=""
  say() { printf '\033[36m\xf0\x9f\x92\xa0 %s\033[0m\n' "$1"; }
  warn() { printf '\033[33m\xf0\x9f\x92\xa0 %s\033[0m\n' "$1"; }
  fail() { printf '\033[31m\xf0\x9f\x92\xa0 %s\033[0m\n' "$1"; }
  has_python() { for v in 3.12 3.11 3.13 3.10; do command -v "python$v" >/dev/null && return 0; done; return 1; }
  export PATH="$bin:$PATH"

  echo; say 'Jarvis installer'; say "Folder: $dir"

  # 1. Tools
  if [ "$(uname)" = Darwin ]; then
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && brew="$b" && break; done
    if [ -z "$brew" ]; then
      say "Installing Homebrew. It asks for your Mac password; letters don't show while you type, that's normal."
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" </dev/tty
      for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && brew="$b" && break; done
    fi
    if [ -n "$brew" ]; then
      eval "$("$brew" shellenv)"
      grep -qs 'brew shellenv' "$HOME/.zprofile" || echo "eval \"\$($brew shellenv)\"" >> "$HOME/.zprofile"
      command -v git >/dev/null || { say 'Installing Git...'; "$brew" install git; }
      has_python || { say 'Installing Python 3.12...'; "$brew" install python@3.12; }
      command -v node >/dev/null || { say 'Installing Node.js...'; "$brew" install node; }
    fi
  fi
  command -v git >/dev/null || missing="$missing Git (sudo apt install git),"
  has_python || missing="$missing Python 3.10 to 3.13 (sudo apt install python3.12 python3.12-venv),"
  command -v node >/dev/null || missing="$missing Node.js 20+ (https://nodejs.org),"
  if [ -n "$missing" ]; then fail "Still missing:${missing%,}. Install them, then run this line again."; return 1; fi

  # 2. Claude Code
  if ! command -v claude >/dev/null; then
    say 'Installing Claude Code. About 1 to 3 minutes.'
    curl -fsSL https://claude.ai/install.sh | bash
    if ! command -v claude >/dev/null && [ -n "$brew" ]; then "$brew" install --cask claude-code; fi
    command -v claude >/dev/null || { fail 'Claude Code did not install. Try: curl -fsSL https://claude.ai/install.sh | bash'; return 1; }
    case "${SHELL:-}" in */bash) rc="$HOME/.bash_profile" ;; *) rc="$HOME/.zshrc" ;; esac
    grep -qs '.local/bin' "$rc" || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$rc"
  fi
  say "Claude Code $(claude --version 2>/dev/null | head -1)"

  # 3. Get or update freejarvis
  if [ -d "$dir/.git" ]; then
    say 'Updating freejarvis...'
    git -C "$dir" pull --ff-only --quiet || warn 'Could not update (local changes?). Going on with the copy you have.'
  elif [ -e "$dir" ]; then
    fail "$dir exists but is not a freejarvis clone. Move it away (or set JARVIS_DIR) and run this again."; return 1
  else
    say 'Downloading freejarvis...'
    git clone --quiet --branch "$branch" https://github.com/riecodes/freejarvis.git "$dir" || { fail 'Download failed. Check your internet and run this again.'; return 1; }
  fi
  cd "$dir" || return 1

  # 4. Groq key (free, no card): the only thing you type. stdin is the curl pipe, so read the terminal.
  [ -f .env ] || cp .env.example .env
  if ! grep -Eq '^GROQ_API_KEY=[^[:space:]]' .env; then
    key="${JARVIS_GROQ_KEY:-}"
    if [ -z "$key" ]; then
      say 'Jarvis hears you through Groq, which is free (no card). Opening the Groq keys page: sign in, Create API Key, copy it.'
      (open https://console.groq.com/keys || xdg-open https://console.groq.com/keys) >/dev/null 2>&1
    fi
    until [[ "$key" =~ ^gsk_[^[:space:]]{20,}$ ]]; do
      [ -n "$key" ] && warn 'That does not look like a Groq key (it starts with gsk_). Try again.'
      printf '\xf0\x9f\x92\xa0 Paste your Groq key here and press Enter: '
      read -r key </dev/tty || key=""
      key="${key//[[:space:]]/}"
      [ -n "$key" ] || { fail 'No key given. Run this line again when you have it.'; return 1; }
    done
    if [ "$(curl -s -o /dev/null -w '%{http_code}' -m 15 -H "Authorization: Bearer $key" https://api.groq.com/openai/v1/models)" = 401 ]; then
      fail 'Groq says that key is not valid. Make a new one and run this line again.'; return 1
    fi
    if grep -q '^GROQ_API_KEY=' .env; then
      awk -v k="$key" '/^GROQ_API_KEY=/{print "GROQ_API_KEY=" k; next} {print}' .env > .env.tmp && mv .env.tmp .env
    else printf '\nGROQ_API_KEY=%s\n' "$key" >> .env; fi
    say 'Groq key saved in .env.'
  fi

  # 5. Setup: Python and Node packages, models (a few hundred MB the first time).
  say 'Setting up the voice: packages and models. The first time takes a few minutes.'
  sh setup.sh </dev/null || { fail 'Setup stopped (see above). Fix that and run this line again.'; return 1; }

  # 6. The window: Jarvis shows its words and buttons there.
  if [ "${JARVIS_NO_WINDOW:-}" != 1 ] && [ ! -d window/node_modules/electron/dist ]; then
    say 'Installing the Jarvis window (about 250 MB)...'
    npm install --silent --prefix window </dev/null && node window/node_modules/electron/install.js </dev/null
  fi

  if [ "${JARVIS_NO_START:-}" = 1 ]; then say 'Jarvis is installed. Start it any time with: sh start.sh'; return 0; fi

  # 7. Start Jarvis, then the finish block. It is the last thing printed, and nothing runs after it.
  steps='     1. Pick "Yes, I trust this folder".\n     2. Pick "I am using this for local development".\n     3. If Claude Code asks you to log in, log in with your Claude account.\n     4. Wait for Jarvis to greet you, then say "Hey Jarvis".'
  if [ "$(uname)" = Darwin ]; then
    sh start.sh "" quiet </dev/null >/dev/null 2>&1
    where='in the new Terminal window'; again="sh $dir/start.sh"
    extra='     (Allow Terminal to use the microphone when macOS asks.)'
  else
    where="in a new terminal (Jarvis has no window launcher on Linux yet). Run this there"; again="cd $dir/jarvis && claude --name jarvis --dangerously-skip-permissions --dangerously-load-development-channels server:voice"
    extra=''
  fi
  echo
  printf '\033[32m\xf0\x9f\x92\xa0 Jarvis is installed.\033[0m\n\n'
  say "Next, $where:"
  [ "$(uname)" = Darwin ] || printf '     %s\n' "$again"
  printf "$steps\n"
  [ -n "$extra" ] && echo "$extra"
  echo
  say "Later, just tell Claude: \"start Jarvis from $dir\" or \"uninstall Jarvis from $dir\"."; echo
}
main
