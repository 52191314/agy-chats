# agy-chats & agy-fork 💬 🔱

> Unified Antigravity Session Suite: Interactive Browser, Turn-Level Branching, Surgical Tool/Edit Cutter, and Workspace Manager for **Google Antigravity (`agy`)**.

`agy-chats` combines conversational exploration, session forking (`agy-fork`), surgical tool cutting (`--tool`), and workspace migration into a single fast, native, cross-platform CLI and TUI suite.

---

## ✨ Features

- 🖥️ **Cross-Platform Native TUI:** Gorgeous split-pane Rich TUI running out-of-the-box on **Windows (PowerShell/CMD/Windows Terminal)**, macOS, and Linux without external terminal dependencies.
- 🔱 **Turn-Level Session Forking (`agy-fork` / `-f`):** Branch a conversation at any specific turn into a clean, new UUID, cloning database steps and brain artifacts without destructive overwrites.
- ✂️ **Surgical Tool & Edit Cutter (`--tool` / `-T`):** Cut inside a turn right before or after a specific tool invocation (`replace_file_content` edit, `run_command` bash, `view_file` read). Perfect for salvaging work before safety blocks or runtime errors. *(Only active when invoked with `--tool` or selected inside turn cutter)*.
- 📦 **Workspace Relocation & Management (`--move` / `m`):** Move and re-categorize sessions between project workspaces (e.g., from `C:\Users\X` to `E:\JB`) directly from the CLI or with one keypress inside the TUI. Rewrites SQLite tables and wire-format protobuf blobs atomically.
- ⚡ **Interactive Search & Filter:** Real-time search across session titles, UUIDs, initial user prompts, and workspace paths (`/`).
- 🔄 **Direct Resume:** Select any conversation and resume it immediately with `agy --conversation <id>` (`Enter` or `r`).
- 📖 **Full Transcript Pager:** Read formatted full transcripts turn-by-turn with syntax highlights and tool execution details (`t`).
- 📋 **Cross-Platform Clipboard:** Instantly copy conversation UUIDs or resume commands to clipboard (supports Windows `clip.exe`, macOS `pbcopy`, and Linux `wl-copy`/`xclip`).
- 🤖 **Subagent Filter:** Toggle between main user conversations and background subagent sessions (`a` or `-a`).
- 📊 **Tabular CLI Mode:** Quick non-interactive list overview via `agy-chats -l` and workspace breakdown via `agy-chats -w`.

---

## 🚀 Installation & Setup

### Windows
Both global batch launchers are in your DevOps scripts directory (`E:\03_Devops\scripts\`):
- `agy-chats` -> Launches the master interactive conversation explorer
- `agy-fork` -> Launches the turn/tool branching interface

Both commands are globally executable from any PowerShell or CMD terminal!

### Linux / macOS
```bash
git clone https://github.com/RAZOR-NINJAS/agy-chats.git
cd agy-chats
./install.sh
```

Ensure `~/.local/bin` is in your `PATH` (add to `~/.bashrc` or `~/.zshrc` if needed):
```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Python Package / Pipx
```bash
pip install .
# or
pipx install .
```

---

## ⌨️ Usage Guide

### 1. Master Conversation Browser (`agy-chats`)
Launch the interactive explorer:
```bash
agy-chats
```

**Keybindings in Browser:**
| Key | Action |
| --- | --- |
| `↑` / `↓` / `k` / `j` | Navigate conversations |
| `PageUp` / `PageDown` | Fast scroll (page through sessions) |
| `Enter` | Resume selected conversation in `agy` |
| `f` | Fork / Branch selected conversation |
| `m` | **Move Workspace** for selected conversation |
| `t` | View full formatted transcript |
| `y` | Copy conversation UUID to clipboard |
| `a` | Toggle subagents & empty sessions |
| `/` | Search & filter by title, UUID, workspace |
| `q` / `Esc` | Clear filter / Exit |

---

### 2. Turn-Level Session Forking (`agy-fork`)
Launch interactive turn forker on recent or selected sessions:
```bash
# Pick conversation interactively to fork
agy-fork

# Or specify conversation UUID or prefix
agy-fork 2176aa73
```

Inside the turn explorer:
- Press `[Enter]` on any turn to choose cut policy:
  - `[1]` **Cut AFTER this Turn** (Keep turn, discard subsequent turns)
  - `[2]` **Cut BEFORE this Turn** (Rewind to before prompt)
  - `[3]` **Cut at Prompt Only** (Keeps user prompt, discards execution)
  - `[4]` **Cut at Specific Tool Call / Edit**

**Headless Turn Branching:**
```bash
# Cut after Turn #2
agy-fork 2176aa73 --turn 2

# Cut before Turn #2 (rewind)
agy-fork 2176aa73 --turn 2 --cut before

# Cut after latest turn and immediately resume agy
agy-fork 2176aa73 --run

# List turns non-interactively
agy-fork 2176aa73 --list-turns
```

---

### 3. Tool-Level Surgery (`--tool`)
*(Active ONLY when invoked with `--tool` flag or chosen in turn menu)*

Inspect and cut right after or before individual edits and bash commands:
```bash
# Launch interactive tool cutter on conversation
agy-fork --tool 2176aa73
# or
agy-chats --tool 2176aa73

# Focus on tools inside Turn #1
agy-fork --tool 2176aa73 --turn 1
```

**Keybindings in Tool Cutter:**
| Key | Action |
| --- | --- |
| `↑` / `↓` | Navigate tool calls / edits |
| `Enter` / `a` | **Cut AFTER tool** (preserves tool result & edits, drops following) |
| `b` | **Cut BEFORE tool** (rewinds before tool executed) |
| `v` | Toggle tool arguments & payload details |
| `Tab` | Switch between turns with tools |
| `/` | Search tools by name or command snippet |
| `q` / `Esc` | Back / Cancel |

**Headless Tool Cutting:**
```bash
# Cut after Tool #14 in Turn #1
agy-fork 2176aa73 --turn 1 --tool 14

# Rewind before Tool #14
agy-fork 2176aa73 --turn 1 --tool 14 --tool-cut before

# List all tools and edits in Turn #1
agy-fork 2176aa73 --turn 1 --list-tools
```

---

### 4. Workspace Migration (`--move` / `-w`)

* **List registered workspaces and conversation counts:**
  ```bash
  agy-chats --workspaces
  # or
  agy-chats -w
  ```

* **Relocate a conversation to a new workspace:**
  ```bash
  # By session title or UUID prefix
  agy-chats --move JB3 E:\JB
  agy-chats --move dd2fc93a E:\JB
  ```
  *(Safely recalculates protobuf varints and updates both SQLite summaries and trajectory databases)*

---

### 5. Quick Commands & Transcripts

* **Instant resume latest session:**
  ```bash
  agy-chats -c
  # or
  agy-chats --last
  ```

* **Non-interactive conversation overview table:**
  ```bash
  agy-chats -l
  # or include subagents
  agy-chats -l -a
  ```

* **View transcript in pager:**
  ```bash
  agy-chats transcript 2176aa73
  ```

---

## ⚙️ Architecture & Data Integrity

Antigravity stores its operational state locally:
- `~/.gemini/antigravity-cli/conversation_summaries.db`: SQLite database containing session titles, workspace URIs, step counts, and raw summary protobufs.
- `~/.gemini/antigravity-cli/conversations/<id>.db`: SQLite database containing trajectory steps (`trajectory_steps` table) and workspace trajectory metadata blob (`trajectory_metadata_blob` table).
- `~/.gemini/antigravity-cli/brain/<conversation-id>/`: Directory storing transcripts, artifacts, and task outputs.

**Non-Destructive Guarantee:**
When forking or cutting, `agy-fork` never alters the source conversation. It generates a fresh UUIDv4, clones exactly the steps up to the cut point, safely duplicates brain artifacts, registers the new session in the index, and checks database integrity with `PRAGMA integrity_check`.

---

## 📄 License

MIT © [Vaibhav Singh Shekhawat](https://github.com/RAZOR-NINJAS)
