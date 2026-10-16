# agy-chats & agy-fork 💬 🔱

> Unified Antigravity Session Suite: Interactive Browser, Turn-Level Branching, Surgical Tool/Edit Cutter, and Workspace Manager for **Google Antigravity (`agy`)**.

`agy-chats` combines conversational exploration, session forking (`agy-fork`), surgical tool cutting (`--tool`), and workspace migration into a single fast, native, cross-platform CLI and TUI suite.

---

## ✨ Features

- 🖥️ **fzf Browser with a Shortcut Bar (default):** The claude-chats look — instant fuzzy filtering and a big scrollable preview, running in the top ~75% of your terminal — plus a colored `[key] Action` shortcut bar and a **Resume commands** area in the bottom ~25%. Single-letter shortcuts (`f` fork, `T` tool cut, `m` move, `t` transcript, `y` copy id, `a` all/subagents…); `/` opens the search box. Needs [`fzf`](https://github.com/junegunn/fzf) and a real console; otherwise (or with `--tui`) it uses the built-in Rich split-pane TUI, which also works on **Windows, macOS, and Linux** without external dependencies.
- 🔱 **Turn-Level Session Forking (`agy-fork` / `-f`):** Branch a conversation at any specific turn into a clean, new UUID, cloning database steps and brain artifacts without destructive overwrites.
- ✂️ **Surgical Tool & Edit Cutter (`--tool` / `-T`):** Cut inside a turn right before or after a specific tool invocation (`replace_file_content` edit, `run_command` bash, `view_file` read). Perfect for salvaging work before safety blocks or runtime errors. *(Only active when invoked with `--tool` or selected inside turn cutter)*.
- 📦 **Workspace Relocation & Management (`--move` / `m`):** Move and re-categorize sessions between project workspaces (e.g., from `C:\Users\X` to `E:\JB`) directly from the CLI or with one keypress inside the TUI. Rewrites SQLite tables and wire-format protobuf blobs atomically.
- ⚡ **Interactive Search & Filter:** Real-time search across session titles, UUIDs, initial user prompts, and workspace paths (`/`).
- 🔄 **Resume Command, Browser Stays Open:** Press `Enter` (or `r`) on any conversation and `agy-chats` copies the exact `agy --conversation <id>` command to your clipboard and lists it in the **resume-commands area** at the bottom ~25% of the screen (the browser takes the top ~75%). It does **not** launch `agy` and does **not** exit, so you can keep browsing and grab more commands; older commands stay selectable in that area and are all reprinted when you quit. Pass `--launch` for the old start-`agy`-and-exit behavior.
- 🎛️ **Toggleable Preview:** The right-hand preview always shows your prompts; switch **Tools** (every tool call, one line each) and **Assistant Replies** on/off with `1` / `2`. Tool calls and replies are interleaved in the order they happened, and your choice is remembered between launches (`~/.agy_chats_preview_view`).
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
Launch the interactive explorer (fzf browser; falls back to the Rich TUI without fzf/console, or force it with `--tui`):
```bash
agy-chats          # fzf browser: list + preview on top, shortcut bar + resume commands underneath
agy-chats --tui    # the built-in Rich split-pane TUI instead
```

The browser is **modal**, like the Rich TUI: single letters are shortcuts. Press `/` to open the search box (letters then type into it); `Enter` or `Esc` returns to shortcuts, keeping the filter. The shortcut bar at the bottom shows `[LIST]` or `[SEARCH]` so you always know which mode you are in.

**Keybindings in the fzf browser:**
| Key | Action |
| --- | --- |
| `↑` / `↓` / `j` / `k` | Move through conversations |
| `J` / `K`, `Ctrl-D` / `Ctrl-U`, mouse wheel | Scroll the preview |
| `Enter` / `r` | Copy the resume command (listed in the bottom **Resume commands** area; the browser stays open) |
| `1` / `2` (or `Ctrl-O` / `Ctrl-R`) | Toggle **Tools** / assistant **Replies** in the preview (prompts are always shown) |
| `f` | **Fork** / branch the selected conversation (turn explorer) |
| `T` | **Tool cut** — cut inside a turn at a specific tool call / edit |
| `m` | **Move workspace** for the selected conversation |
| `t` | View the full formatted transcript |
| `y` | Copy the conversation UUID (confirmation shows in the bottom area) |
| `a` | Toggle subagents & empty sessions |
| `g` | **Group by workspace folder** on/off. Each folder gets a `▼ name (N chats)` header row above its chats; the preview on a header shows a folder overview |
| `Enter` / `Space` on a folder row | Fold / unfold that folder (the cursor stays on it) |
| `e` / `c` | Expand all / collapse all folders (grouped mode) |
| `#` | Limit how many chats are listed (newest N; `0` = all) — prompts for a number |
| `/` | Search & filter by title, UUID, workspace (`Enter` keeps the filter, `Esc` stops searching) |
| `Esc` | Clear the filter if there is one, otherwise quit |
| `q` | Quit |

Forking or cutting a chat adds the new chat's resume command to the bottom area too. On quit, every command you collected is reprinted. Start grouped with `agy-chats -g`, or limited with `agy-chats -n 50`. Actions that restart the list (`a`, `g`, `#`, fold/unfold, fork, …) put the cursor back on the row you were on.

**Keybindings in the Rich TUI (`--tui`):**
| Key | Action |
| --- | --- |
| `↑` / `↓` / `k` / `j` | Navigate conversations |
| `PageUp` / `PageDown` | Fast scroll (page through sessions) |
| `Enter` / `r` | Copy the resume command for the selected conversation (listed in the bottom resume-commands area; browser stays open) |
| `1` | Toggle **Tools** in the preview (prompts are always shown) |
| `2` | Toggle assistant **Replies** in the preview |
| `Tab` / `j` `k` / `J` `K` | Focus & scroll the preview pane |
| `g` / `#` | Group by workspace directory / limit how many sessions are shown |
| `f` | Fork / Branch selected conversation |
| `T` | Open the tool cutter (cut at a specific tool call / edit) |
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

* **Get the resume command for the latest session** (one-shot: prints + copies it and exits; add `--launch` to start `agy` directly). `agy-chats <id-prefix>` works the same way:
  ```bash
  agy-chats -c
  # or
  agy-chats --last
  ```

* **Print a preview non-interactively** (what the right-hand pane shows):
  ```bash
  agy-chats --preview 2176aa73                    # uses your saved Tools/Replies switches
  agy-chats --preview 2176aa73 --view=            # prompts only
  agy-chats --preview 2176aa73 --view tools,replies
  ```

* **Diagnostics:** set `CHATS_UI_LOG=<file>` to log every fzf key-binding callback (key, mode, query, returned action) — handy if a shortcut misbehaves in your terminal.

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

## 🗂️ Project Structure

```
agy-chats/
├── agy_chats.py       # CLI entrypoint: argument parsing, fork/cut/move dispatch
├── session_engine.py  # Protobuf parsing, SQLite reading, session cloning/cutting
├── fzf_ui.py          # fzf shell (default UI) - identical copy lives in claude-chats
├── tui.py             # Rich TUI (agy-chats --tui)
├── agy-chats(.bat)    # Launchers (bash / Windows); run the repo files directly
├── agy-fork(.bat)     # Same entrypoint with --fork preset
├── install.sh         # Symlinks launchers into ~/.local/bin
├── pyproject.toml     # Package metadata; py-modules + console scripts
├── LICENSE
└── .agents/           # Local junction to the global skills dir (git-ignored)
```

---

## 📄 License

MIT © [Vaibhav Singh Shekhawat](https://github.com/RAZOR-NINJAS)
