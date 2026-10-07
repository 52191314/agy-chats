# agy-chats 💬

> Interactive Terminal User Interface (TUI) to browse, inspect, and resume previous **Google Antigravity (`agy`)** conversations.

`agy-chats` (also aliased as `agy-history`) connects directly to your local Antigravity state (`~/.gemini/antigravity-cli/`) to provide an instant, interactive conversation history browser.

---

## ✨ Features

- ⚡ **Interactive Fuzzy Search:** Search across conversation titles, IDs, and paths powered by `fzf` with live previews.
- 🖥️ **Native Curses Fallback:** Zero-dependency fallback to built-in curses TUI if `fzf` is not installed.
- 🔄 **Direct Resume:** Select any conversation and resume it immediately with `agy --conversation <id>`.
- 📖 **Full Transcript Pager:** Read formatted full transcripts turn-by-turn with syntax highlights in your default pager (`less -R`).
- 📋 **Clipboard Integration:** Instantly copy conversation UUIDs to clipboard (`Ctrl-Y` using `wl-copy`, `xclip`, or `xsel`).
- 🤖 **Subagent Filter:** Toggle between main user conversations and background subagent sessions (`Ctrl-A` or `-a`).
- 📊 **Tabular CLI Mode:** Quick non-interactive list overview via `agy-chats -l`.
- ⏩ **Quick Resume:** Jump straight back into your latest session with `agy-chats -c`.

---

## 🚀 Installation

### Option 1: Quick Install Script (Symlink)

Clone the repository and run the installer:

```bash
git clone https://github.com/RAZOR-NINJAS/agy-chats.git
cd agy-chats
./install.sh
```

This symlinks `agy-chats` and `agy-history` into `~/.local/bin/`.

Ensure `~/.local/bin` is in your `PATH` (add to `~/.bashrc` or `~/.zshrc` if needed):
```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Option 2: Python / Pipx

```bash
pip install .
# or
pipx install .
```

---

## ⌨️ Usage

### Interactive TUI

Launch the interactive browser:
```bash
agy-chats
# or
agy-history
```

Force native curses interface:
```bash
agy-chats --curses
```

Include subagents and empty sessions:
```bash
agy-chats -a
```

### Non-Interactive / Quick Commands

* **List conversations in a table:**
  ```bash
  agy-chats --list
  # or
  agy-chats -l
  ```

* **Resume the most recent conversation immediately:**
  ```bash
  agy-chats -c
  # or
  agy-chats --last
  ```

* **View transcript of a specific conversation in your pager:**
  ```bash
  agy-chats transcript <conversation-id>
  ```

---

## 🎮 Keybindings

### In `fzf` Mode:
| Key | Action |
| --- | --- |
| `Enter` | Resume selected conversation in `agy` |
| `Ctrl-T` | Open full transcript in pager |
| `Ctrl-Y` | Copy conversation ID to clipboard |
| `Ctrl-A` | Toggle showing subagents / all sessions |
| `Esc` / `Ctrl-C` | Exit |

### In Curses Mode:
| Key | Action |
| --- | --- |
| `↑` / `↓` / `k` / `j` | Navigate conversation list |
| `Enter` | Resume selected conversation in `agy` |
| `t` | Open full transcript in pager |
| `a` | Toggle subagents / all sessions |
| `q` / `Esc` | Exit |

---

## ⚙️ How It Works

Antigravity stores CLI session metadata and chat trajectory logs locally in:
- `~/.gemini/antigravity-cli/conversation_summaries.db` (SQLite database containing session titles, workspaces, step counts, timestamps)
- `~/.gemini/antigravity-cli/brain/<conversation-id>/.system_generated/logs/transcript.jsonl` (detailed turn-by-turn prompts, tool executions, and assistant responses)

`agy-chats` reads this local database in read-only mode and parses transcript files to generate previews, formatted pager transcripts, and launch resume sessions.

---

## 📄 License

MIT © [Vaibhav Singh Shekhawat](https://github.com/RAZOR-NINJAS)
