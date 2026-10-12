# agy-chats 💬

> Interactive Terminal User Interface (TUI) and search browser to browse, inspect, resume, and manage previous **Google Antigravity (`agy`)** conversations.

`agy-chats` (also aliased as `agy-history`) connects directly to your local Antigravity state (`~/.gemini/antigravity-cli/`) to provide an instant, interactive conversation history browser and workspace manager.

---

## ✨ Features

- 🖥️ **Cross-Platform Native TUI:** Gorgeous split-pane Rich TUI running out-of-the-box on **Windows (PowerShell/CMD/Windows Terminal)**, macOS, and Linux without external terminal dependencies.
- ⚡ **Interactive Search & Filter:** Real-time search across session titles, UUIDs, initial user prompts, and workspace directories.
- 📦 **Workspace Relocation & Management (`--move` / `m`):** Move and re-categorize sessions between project workspaces (e.g., from `C:\Users\X` to `E:\JB`) directly from the CLI or with one keypress inside the TUI.
- 🔄 **Direct Resume:** Select any conversation and resume it immediately with `agy --conversation <id>`.
- 📖 **Full Transcript Pager:** Read formatted full transcripts turn-by-turn with syntax highlights and tool execution details.
- 📋 **Cross-Platform Clipboard:** Instantly copy conversation UUIDs to clipboard (supports Windows `clip.exe`, macOS `pbcopy`, and Linux `wl-copy`/`xclip`).
- 🤖 **Subagent Filter:** Toggle between main user conversations and background subagent sessions (`a` or `-a`).
- 📊 **Tabular CLI Mode:** Quick non-interactive list overview via `agy-chats -l` and workspace breakdown via `agy-chats -w`.
- ⏩ **Quick Resume:** Jump straight back into your latest session with `agy-chats -c`.

---

## 🚀 Installation

### Windows:
The tool is installed at `E:\02_Projects\agy-chats`.
A global launcher `agy-chats.bat` has been added to `E:\03_Devops\scripts\agy-chats.bat`. You can run `agy-chats` directly from any PowerShell or CMD window!

### Linux / macOS:
```bash
git clone https://github.com/RAZOR-NINJAS/agy-chats.git
cd agy-chats
./install.sh
```

Ensure `~/.local/bin` is in your `PATH` (add to `~/.bashrc` or `~/.zshrc` if needed):
```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Python / Pipx:
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

Include subagents and empty sessions:
```bash
agy-chats -a
```

### Workspace Management

* **List all registered workspaces & conversation counts:**
  ```bash
  agy-chats --workspaces
  # or
  agy-chats -w
  ```

* **Relocate / Move a conversation to a new workspace:**
  ```bash
  # By title or conversation UUID
  agy-chats --move JB3 E:\JB
  agy-chats --move dd2fc93a E:\JB
  ```
  *(Updates SQLite metadata and wire-format protobuf trajectories cleanly in both `conversation_summaries.db` and the conversation's `.db` file)*

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

* **View transcript of a specific conversation:**
  ```bash
  agy-chats transcript <conversation-id>
  ```

---

## 🎮 TUI Keybindings

| Key | Action |
| --- | --- |
| `↑` / `↓` / `k` / `j` | Navigate conversation list |
| `PageUp` / `PageDown` | Fast scroll (page through sessions) |
| `Enter` | Resume selected conversation in `agy` |
| `m` | **Move / Relocate Workspace** for the selected conversation |
| `t` | Open full turn-by-turn transcript |
| `y` | Copy conversation UUID to clipboard |
| `a` | Toggle showing subagents / all sessions |
| `/` or `f` | Search & filter by title, UUID, or workspace |
| `q` / `Esc` | Clear filter / Exit |

---

## ⚙️ How It Works

Antigravity stores CLI session metadata and chat trajectory logs locally in:
- `~/.gemini/antigravity-cli/conversation_summaries.db` (SQLite database containing session titles, workspaces, step counts, timestamps)
- `~/.gemini/antigravity-cli/conversations/<id>.db` (SQLite database containing full trajectory steps and metadata protobufs)
- `~/.gemini/antigravity-cli/brain/<conversation-id>/.system_generated/logs/transcript.jsonl` (detailed turn-by-turn prompts, tool executions, and assistant responses)

`agy-chats` reads this local database in read-only mode, parses transcript files to generate live previews, and provides safe, atomic workspace migration by serializing and rewriting protobuf metadata.

---

## 📄 License

MIT © [Vaibhav Singh Shekhawat](https://github.com/RAZOR-NINJAS)
