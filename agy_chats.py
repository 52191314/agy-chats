#!/usr/bin/env python3
"""
agy-chats: Interactive Terminal User Interface (TUI) and search browser to inspect,
explore, and seamlessly resume previous Google Antigravity (agy) conversations.

Cross-platform: Windows, macOS, Linux.
"""

import sys
import os

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import sqlite3
import json
import re
import shutil
import subprocess
import argparse
import tempfile
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple, Any

# Rich terminal components
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.layout import Layout
from rich import box
from rich.markup import escape

console = Console()

DB_PATH = os.path.expanduser("~/.gemini/antigravity-cli/conversation_summaries.db")
BRAIN_DIR = os.path.expanduser("~/.gemini/antigravity-cli/brain")
CONV_DIR = os.path.expanduser("~/.gemini/antigravity-cli/conversations")
STATE_FILE = os.path.join(tempfile.gettempdir(), "agy_chats_show_all")

# ANSI Colors
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
GRAY = "\033[90m"
WHITE = "\033[97m"
RED = "\033[31m"


# ==============================================================================
# Database & Utility Helpers
# ==============================================================================

def get_db_connection(read_only: bool = True):
    if not os.path.exists(DB_PATH):
        return None
    try:
        if read_only:
            return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5.0)
        else:
            return sqlite3.connect(DB_PATH, timeout=5.0)
    except Exception:
        try:
            return sqlite3.connect(DB_PATH, timeout=5.0)
        except Exception:
            return None


def parse_time(s: Optional[str]) -> Optional[datetime]:
    if not s or s.startswith("0001"):
        return None
    s = s.strip()
    if " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def format_relative(dt: Optional[datetime]) -> str:
    if not dt:
        return "Never"
    now = datetime.now(timezone.utc)
    diff = now - dt
    secs = int(diff.total_seconds())
    if secs < 0:
        secs = 0
    if secs < 60:
        return "Just now"
    elif secs < 3600:
        m = secs // 60
        return f"{m}m ago"
    elif secs < 86400:
        h = secs // 3600
        return f"{h}h ago"
    elif secs < 86400 * 7:
        d = secs // 86400
        return f"{d}d ago"
    else:
        return dt.strftime("%b %d, %Y")


def format_workspace(ws_uris: Optional[str]) -> str:
    if not ws_uris:
        return "~"
    try:
        uris = json.loads(ws_uris)
        paths = []
        home = os.path.expanduser("~").replace("\\", "/")
        for u in uris:
            p = u.replace("file://", "")
            if sys.platform == "win32" and p.startswith("/"):
                # Handle /C:/Users/X -> C:/Users/X
                if len(p) >= 3 and p[2] == ":":
                    p = p[1:]
            if p.startswith(home):
                p = "~" + p[len(home):]
            paths.append(p)
        return ", ".join(paths) if paths else "~"
    except Exception:
        return "~"


def get_workspace_label(ws_uris: Optional[str]) -> str:
    if not ws_uris:
        return "(no workspace)"
    try:
        uris = json.loads(ws_uris)
        if not uris:
            return "(no workspace)"
        first = uris[0].replace("file://", "")
        if sys.platform == "win32" and first.startswith("/"):
            if len(first) >= 3 and first[2] == ":":
                first = first[1:]
        clean = first.rstrip("/\\")
        base = os.path.basename(clean)
        return base or clean
    except Exception:
        return "(no workspace)"


def normalize_workspace_uri(path_str: str) -> str:
    """Normalizes a folder path or URI to standard file:/// URI format."""
    clean = path_str.strip().strip("\"'").replace("\\", "/")
    if clean.startswith("file://"):
        return clean
    if not os.path.isabs(clean):
        clean = os.path.abspath(clean).replace("\\", "/")
    if not clean.startswith("/"):
        clean = "/" + clean
    return f"file://{clean}"


def clean_user_message(content: str) -> str:
    if not content:
        return ""
    m = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", content, re.DOTALL)
    if m:
        return m.group(1).strip()
    return re.sub(r"<[^>]+>", "", content).strip()


def get_conversation_details(cid: str) -> Tuple[List[Any], List[Tuple[str, str]], List[Tuple[str, str]]]:
    tpath = os.path.join(BRAIN_DIR, cid, ".system_generated/logs/transcript.jsonl")
    steps = []
    user_prompts = []
    asst_replies = []
    if os.path.exists(tpath):
        try:
            with open(tpath, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        s = json.loads(line)
                        steps.append(s)
                        if s.get("type") == "USER_INPUT" and s.get("content"):
                            cleaned = clean_user_message(s["content"])
                            if cleaned:
                                user_prompts.append((s.get("created_at", ""), cleaned))
                        elif s.get("type") == "PLANNER_RESPONSE" and s.get("content"):
                            c = s["content"].strip()
                            if c:
                                asst_replies.append((s.get("created_at", ""), c))
                    except Exception:
                        pass
        except Exception:
            pass
    return steps, user_prompts, asst_replies


def query_conversations(show_all: bool = False) -> List[Tuple[Any, ...]]:
    conn = get_db_connection()
    if not conn:
        return []
    cur = conn.cursor()
    if show_all:
        cur.execute("""
            SELECT conversation_id, title, preview, step_count, last_modified_time,
                   workspace_uris, agent_name, nesting_depth, parent_conversation_id
            FROM conversation_summaries
            ORDER BY last_modified_time DESC
        """)
    else:
        cur.execute("""
            SELECT conversation_id, title, preview, step_count, last_modified_time,
                   workspace_uris, agent_name, nesting_depth, parent_conversation_id
            FROM conversation_summaries
            WHERE nesting_depth = 0 AND step_count > 0
            ORDER BY last_modified_time DESC
        """)
    rows = cur.fetchall()
    conn.close()
    return rows


def copy_to_clipboard(text: str) -> bool:
    if sys.platform == "win32":
        try:
            proc = subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True)
            proc.communicate(text.encode("utf-8"))
            return proc.returncode == 0
        except Exception:
            pass
    for tool in ["wl-copy", "pbcopy", "xclip", "xsel"]:
        if shutil.which(tool):
            try:
                cmd = [tool]
                if tool == "xclip":
                    cmd += ["-selection", "clipboard"]
                elif tool == "xsel":
                    cmd += ["--clipboard", "--input"]
                subprocess.run(cmd, input=text.encode("utf-8"), check=False)
                return True
            except Exception:
                pass
    return False


def resume_conversation(cid: str):
    console.print(f"\n[bold green]Resuming conversation [cyan]{cid}[/cyan]...[/bold green]\n")
    if sys.platform == "win32":
        subprocess.run(f"agy --conversation {cid}", shell=True)
    else:
        os.execvp("agy", ["agy", "--conversation", cid])


# ==============================================================================
# Wire-Format Protobuf Parser & Serializer (for Workspace Migration)
# ==============================================================================

def decode_varint(data: bytes, offset: int) -> Tuple[int, int]:
    res = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise IndexError("Unexpected end of data while decoding varint")
        b = data[offset]
        offset += 1
        res |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return res, offset


def encode_varint(val: int) -> bytes:
    res = bytearray()
    while True:
        b = val & 0x7F
        val >>= 7
        if val:
            res.append(b | 0x80)
        else:
            res.append(b)
            break
    return bytes(res)


def parse_proto_fields(data: bytes) -> List[Tuple[int, int, Any]]:
    offset = 0
    fields = []
    while offset < len(data):
        try:
            key, offset = decode_varint(data, offset)
        except IndexError:
            break
        wire_type = key & 0x07
        field_num = key >> 3
        if wire_type == 0:  # Varint
            val, offset = decode_varint(data, offset)
            fields.append((field_num, wire_type, val))
        elif wire_type == 1:  # 64-bit
            val = data[offset:offset+8]
            offset += 8
            fields.append((field_num, wire_type, val))
        elif wire_type == 2:  # Length-delimited
            length, offset = decode_varint(data, offset)
            val = data[offset:offset+length]
            offset += length
            fields.append((field_num, wire_type, val))
        elif wire_type == 5:  # 32-bit
            val = data[offset:offset+4]
            offset += 4
            fields.append((field_num, wire_type, val))
        else:
            break
    return fields


def serialize_proto_fields(fields: List[Tuple[int, int, Any]]) -> bytes:
    res = bytearray()
    for f_num, w_type, val in fields:
        key = (f_num << 3) | w_type
        res.extend(encode_varint(key))
        if w_type == 0:
            res.extend(encode_varint(val))
        elif w_type in (1, 5):
            res.extend(val)
        elif w_type == 2:
            res.extend(encode_varint(len(val)))
            res.extend(val)
    return bytes(res)


def update_traj_blob(blob: bytes, old_u: bytes, new_u: bytes) -> bytes:
    fields = parse_proto_fields(blob)
    new_fields = []
    for f_num, w_type, val in fields:
        if f_num == 1 and w_type == 2:
            sub = parse_proto_fields(val)
            new_sub = []
            for s_num, s_type, s_val in sub:
                if s_num == 1 and s_type == 2 and s_val == old_u:
                    new_sub.append((s_num, s_type, new_u))
                else:
                    new_sub.append((s_num, s_type, s_val))
            new_fields.append((f_num, w_type, serialize_proto_fields(new_sub)))
        elif f_num == 7 and w_type == 2 and val == old_u:
            new_fields.append((f_num, w_type, new_u))
        else:
            new_fields.append((f_num, w_type, val))
    return serialize_proto_fields(new_fields)


def update_raw_summary(raw: bytes, old_u: bytes, new_u: bytes) -> bytes:
    fields = parse_proto_fields(raw)
    new_fields = []
    for f_num, w_type, val in fields:
        if f_num == 9 and w_type == 2:
            sub = parse_proto_fields(val)
            new_sub = []
            for s_num, s_type, s_val in sub:
                if s_num == 1 and s_type == 2 and s_val == old_u:
                    new_sub.append((s_num, s_type, new_u))
                else:
                    new_sub.append((s_num, s_type, s_val))
            new_fields.append((f_num, w_type, serialize_proto_fields(new_sub)))
        elif f_num == 17 and w_type == 2:
            updated_traj = update_traj_blob(val, old_u, new_u)
            new_fields.append((f_num, w_type, updated_traj))
        else:
            new_fields.append((f_num, w_type, val))
    return serialize_proto_fields(new_fields)


# ==============================================================================
# Workspace Relocation / Moving Feature
# ==============================================================================

def move_conversation_workspace(cid_or_query: str, target_workspace_path: str) -> Tuple[bool, str]:
    """
    Moves an Antigravity conversation from its current workspace to target_workspace_path.
    Updates conversation_summaries.db and conversations/<cid>.db.
    """
    conn = get_db_connection(read_only=False)
    if not conn:
        return False, f"Could not connect to database at {DB_PATH}"

    cur = conn.cursor()
    # Resolve conversation
    cur.execute(
        "SELECT conversation_id, title, workspace_uris, raw_summary FROM conversation_summaries "
        "WHERE conversation_id = ? OR conversation_id LIKE ? OR title = ? OR title LIKE ?",
        (cid_or_query, f"{cid_or_query}%", cid_or_query, f"{cid_or_query}%")
    )
    matches = cur.fetchall()
    if not matches:
        conn.close()
        return False, f"No conversation found matching '{cid_or_query}'"
    if len(matches) > 1 and matches[0][0] != cid_or_query:
        conn.close()
        return False, f"Ambiguous query '{cid_or_query}'. Matches {len(matches)} conversations. Please specify exact ID."

    cid, title, old_ws_json, raw_summary = matches[0]

    # Resolve old URI
    try:
        old_uris = json.loads(old_ws_json)
        old_uri_str = old_uris[0] if old_uris else "file:///C:/Users/X"
    except Exception:
        old_uri_str = "file:///C:/Users/X"

    new_uri_str = normalize_workspace_uri(target_workspace_path)
    new_ws_json = json.dumps([new_uri_str])

    old_uri_bytes = old_uri_str.encode("utf-8")
    new_uri_bytes = new_uri_str.encode("utf-8")

    # 1. Update conversation_summaries.db
    if raw_summary:
        updated_raw = update_raw_summary(raw_summary, old_uri_bytes, new_uri_bytes)
    else:
        updated_raw = raw_summary

    cur.execute(
        "UPDATE conversation_summaries SET workspace_uris = ?, raw_summary = ? WHERE conversation_id = ?",
        (new_ws_json, updated_raw, cid)
    )
    conn.commit()
    conn.close()

    # 2. Update conversations/<cid>.db
    conv_db = os.path.join(CONV_DIR, f"{cid}.db")
    if os.path.exists(conv_db):
        try:
            cconn = sqlite3.connect(conv_db)
            ccur = cconn.cursor()
            ccur.execute("SELECT id, data FROM trajectory_metadata_blob")
            for b_id, b_data in ccur.fetchall():
                if b_data:
                    new_b_data = update_traj_blob(b_data, old_uri_bytes, new_uri_bytes)
                    ccur.execute("UPDATE trajectory_metadata_blob SET data = ? WHERE id = ?", (new_b_data, b_id))
            cconn.commit()
            cconn.close()
        except Exception as e:
            return True, f"Updated summary for '{title or cid}', but failed updating {cid}.db: {e}"

    old_lbl = get_workspace_label(old_ws_json)
    new_lbl = get_workspace_label(new_ws_json)
    return True, f"Successfully moved '{title or cid}' ({cid[:8]}) from '{old_lbl}' to '{new_lbl}' ({new_uri_str})"


def list_workspaces() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    if not conn:
        return []
    cur = conn.cursor()
    cur.execute("SELECT workspace_uris, count(*) FROM conversation_summaries GROUP BY workspace_uris ORDER BY count(*) DESC")
    rows = cur.fetchall()
    conn.close()
    res = []
    for ws_json, cnt in rows:
        label = get_workspace_label(ws_json)
        path = format_workspace(ws_json)
        res.append({"label": label, "path": path, "count": cnt, "raw_json": ws_json})
    return res


# ==============================================================================
# Terminal Keyboard Input (Cross-Platform)
# ==============================================================================

def get_key() -> str:
    """Reads a single key or key sequence across Windows and POSIX."""
    if sys.platform == "win32":
        import msvcrt
        ch = msvcrt.getch()
        if ch in (b'\x00', b'\xe0'):
            ch2 = msvcrt.getch()
            if ch2 == b'H': return "UP"
            elif ch2 == b'P': return "DOWN"
            elif ch2 == b'I': return "PAGE_UP"
            elif ch2 == b'Q': return "PAGE_DOWN"
            elif ch2 == b'G': return "HOME"
            elif ch2 == b'O': return "END"
            return f"EXT_{ch2}"
        elif ch == b'\r':
            return "ENTER"
        elif ch == b'\x1b':
            return "ESC"
        elif ch in (b'\x08', b'\x7f'):
            return "BACKSPACE"
        elif ch == b'\t':
            return "TAB"
        try:
            return ch.decode("utf-8", errors="ignore")
        except Exception:
            return ""
    else:
        import tty, termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
            if ch == '\x1b':
                ch2 = sys.stdin.read(1)
                if ch2 == '[':
                    ch3 = sys.stdin.read(1)
                    if ch3 == 'A': return "UP"
                    elif ch3 == 'B': return "DOWN"
                    elif ch3 == 'C': return "RIGHT"
                    elif ch3 == 'D': return "LEFT"
                    elif ch3 == '5': sys.stdin.read(1); return "PAGE_UP"
                    elif ch3 == '6': sys.stdin.read(1); return "PAGE_DOWN"
                    elif ch3 == 'H': return "HOME"
                    elif ch3 == 'F': return "END"
                return "ESC"
            elif ch == '\r' or ch == '\n':
                return "ENTER"
            elif ch == '\x7f' or ch == '\x08':
                return "BACKSPACE"
            elif ch == '\t':
                return "TAB"
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def prompt_input(prompt_text: str) -> str:
    console.print(f"[bold cyan]{prompt_text}[/bold cyan] ", end="")
    sys.stdout.flush()
    chars = []
    while True:
        k = get_key()
        if k == "ENTER":
            console.print()
            return "".join(chars)
        elif k == "ESC":
            console.print()
            return ""
        elif k == "BACKSPACE":
            if chars:
                chars.pop()
                sys.stdout.write("\b \b")
                sys.stdout.flush()
        elif len(k) == 1 and ord(k) >= 32:
            chars.append(k)
            sys.stdout.write(k)
            sys.stdout.flush()


# ==============================================================================
# Rich Interactive TUI (Windows & Cross-Platform Native)
# ==============================================================================

class RichChatsTUI:
    def __init__(self, show_all: bool = False, initial_query: str = ""):
        self.show_all = show_all
        self.filter_query = initial_query.strip()
        self.rows = []
        self.visible_indices = []
        self.selected_idx = 0
        self.page_size = 14
        self.refresh_data()

    def refresh_data(self):
        self.rows = query_conversations(show_all=self.show_all)
        self.update_filter(self.filter_query)

    def update_filter(self, query: str):
        self.filter_query = query.strip()
        if not self.filter_query:
            self.visible_indices = list(range(len(self.rows)))
        else:
            q_lower = self.filter_query.lower()
            self.visible_indices = []
            for i, r in enumerate(self.rows):
                cid, title, prev, step_count, last_mod, ws_uris, agent_name, depth, parent_id = r
                ws_str = format_workspace(ws_uris)
                if (q_lower in cid.lower() or
                    q_lower in (title or "").lower() or
                    q_lower in (prev or "").lower() or
                    q_lower in (agent_name or "").lower() or
                    q_lower in ws_str.lower()):
                    self.visible_indices.append(i)
        if self.visible_indices:
            self.selected_idx = min(self.selected_idx, len(self.visible_indices) - 1)
        else:
            self.selected_idx = 0

    def render(self):
        os.system("cls" if os.name == "nt" else "clear")

        header_text = Text()
        header_text.append("Antigravity Conversation Explorer (agy-chats)  |  ", style="bold cyan")
        mode_str = "All Sessions (incl. subagents)" if self.show_all else "Main Chats Only"
        header_text.append(f"Mode: {mode_str} (press 'a' to toggle)\n", style="bold yellow")
        header_text.append(f"Total Conversations: {len(self.rows)}  |  ", style="dim")
        if self.filter_query:
            header_text.append(f"Filter: '{self.filter_query}' ({len(self.visible_indices)} matching)", style="bold magenta")
        else:
            header_text.append("Filter: None (press '/' to search)", style="dim")

        console.print(Panel(header_text, border_style="cyan", box=box.ROUNDED))

        if not self.visible_indices:
            console.print(Panel(
                f"[bold red]No conversations matching '{self.filter_query}'.[/bold red]\n"
                "Press [bold yellow]'/'[/bold yellow] to change filter or [bold yellow]ESC[/bold yellow] to clear.",
                border_style="red"
            ))
            self.render_controls()
            return

        if self.selected_idx not in self.visible_indices:
            self.selected_idx = self.visible_indices[0]

        curr_pos = self.visible_indices.index(self.selected_idx)
        start_pos = max(0, curr_pos - self.page_size // 2)
        end_pos = min(len(self.visible_indices), start_pos + self.page_size)
        if end_pos - start_pos < self.page_size:
            start_pos = max(0, end_pos - self.page_size)

        table = Table(box=box.SIMPLE_HEAVY, expand=True)
        table.add_column("ID", style="cyan", width=10)
        table.add_column("Active", justify="center", width=12)
        table.add_column("Steps", justify="right", width=7)
        table.add_column("Workspace", style="green", width=14)
        table.add_column("Title / Snippet", style="white", ratio=1)

        for pos in range(start_pos, end_pos):
            idx = self.visible_indices[pos]
            row = self.rows[idx]
            cid, title, prev, step_count, last_mod, ws_uris, agent_name, depth, parent_id = row
            is_selected = (idx == self.selected_idx)

            dt = parse_time(last_mod)
            rel_time = format_relative(dt)
            ws_label = get_workspace_label(ws_uris)

            eff_title = (title or "").strip()
            if not eff_title:
                if agent_name:
                    eff_title = f"[{agent_name}]"
                elif prev:
                    eff_title = prev.strip().splitlines()[0][:50]
                else:
                    eff_title = "(Untitled Session)"

            id_str = cid[:8]
            if is_selected:
                row_style = "bold white on blue"
                id_str = f"> {id_str}"
            else:
                row_style = "none"

            table.add_row(
                id_str,
                rel_time,
                str(step_count),
                escape(ws_label[:14]),
                escape(eff_title),
                style=row_style
            )

        console.print(table)

        # Selected preview pane
        sel_row = self.rows[self.selected_idx]
        cid = sel_row[0]
        title = sel_row[1] or "(Untitled Session)"
        step_count = sel_row[3]
        last_mod = sel_row[4]
        ws_uris = sel_row[5]
        agent_name = sel_row[6]
        ws_str = format_workspace(ws_uris)
        dt = parse_time(last_mod)
        rel_time = format_relative(dt)

        steps, user_prompts, asst_replies = get_conversation_details(cid)

        preview_text = Text()
        preview_text.append(f"{title}\n", style="bold yellow")
        preview_text.append(f"UUID: {cid}  |  Active: {rel_time} ({last_mod[:19]})  |  Steps: {step_count}\n", style="dim")
        preview_text.append(f"Workspace: {ws_str}\n", style="bold green")

        if user_prompts:
            preview_text.append("\nInitial Prompt:\n", style="bold cyan")
            prompt_snip = user_prompts[0][1].strip()
            if len(prompt_snip) > 180:
                prompt_snip = prompt_snip[:177] + "..."
            preview_text.append(f"{prompt_snip}\n", style="white")

        if asst_replies:
            preview_text.append("\nLatest Response:\n", style="bold magenta")
            resp_snip = asst_replies[-1][1].strip()
            if len(resp_snip) > 180:
                resp_snip = resp_snip[:177] + "..."
            preview_text.append(f"{resp_snip}\n", style="dim")

        console.print(Panel(preview_text, title="[bold]Session Details[/bold]", border_style="yellow", box=box.ROUNDED))
        self.render_controls()

    def render_controls(self):
        ctrls = Text()
        ctrls.append(" [Up/Down] Select  |  ", style="bold cyan")
        ctrls.append("[Enter] Resume  |  ", style="bold green")
        ctrls.append("[m] Move Workspace  |  ", style="bold yellow")
        ctrls.append("[t] Transcript  |  ", style="bold magenta")
        ctrls.append("[y] Copy ID  |  ", style="bold white")
        ctrls.append("[a] Toggle All  |  ", style="dim")
        ctrls.append("[/] Search  |  ", style="bold white")
        ctrls.append("[q/Esc] Quit", style="bold red")
        console.print(ctrls)

    def interactive_move_workspace(self):
        if not self.visible_indices:
            return
        sel_row = self.rows[self.selected_idx]
        cid = sel_row[0]
        title = sel_row[1] or sel_row[0][:8]
        curr_ws = format_workspace(sel_row[5])

        os.system("cls" if os.name == "nt" else "clear")
        menu = Text()
        menu.append(f"Move Conversation: {title} ({cid[:8]})\n\n", style="bold yellow")
        menu.append(f"Current Workspace: {curr_ws}\n\n", style="cyan")

        # Show known workspaces
        known = list_workspaces()
        menu.append("Recent Workspaces:\n", style="bold green")
        for i, w in enumerate(known[:5], 1):
            menu.append(f"  [{i}] {w['label']} ({w['path']}) [{w['count']} convs]\n", style="white")

        menu.append("\n  [c] Custom Path (type custom workspace path)\n", style="bold cyan")
        menu.append("  [Esc] Cancel\n", style="bold red")

        console.print(Panel(menu, title="[bold]Relocate Conversation Workspace[/bold]", border_style="yellow"))
        console.print("[bold]Select an option [1-5, c]:[/bold] ", end="")
        sys.stdout.flush()

        while True:
            k = get_key()
            if k in ("1", "2", "3", "4", "5"):
                idx = int(k) - 1
                if idx < len(known[:5]):
                    target_ws = known[idx]["path"]
                    break
            elif k in ("c", "C"):
                console.print()
                target_ws = prompt_input("Enter target workspace path (e.g. E:\\JB):")
                if not target_ws:
                    return
                break
            elif k in ("ESC", "q", "Q"):
                return

        console.print(f"\n[bold green]Moving conversation to '{target_ws}'...[/bold green]")
        ok, msg = move_conversation_workspace(cid, target_ws)
        if ok:
            console.print(f"[bold green]Success:[/bold green] {msg}")
        else:
            console.print(f"[bold red]Failed:[/bold red] {msg}")
        console.print("\nPress any key to continue...")
        get_key()
        self.refresh_data()

    def run(self):
        while True:
            self.render()
            k = get_key()

            if k in ("UP", "k"):
                if self.visible_indices:
                    curr_pos = self.visible_indices.index(self.selected_idx)
                    if curr_pos > 0:
                        self.selected_idx = self.visible_indices[curr_pos - 1]
            elif k in ("DOWN", "j"):
                if self.visible_indices:
                    curr_pos = self.visible_indices.index(self.selected_idx)
                    if curr_pos < len(self.visible_indices) - 1:
                        self.selected_idx = self.visible_indices[curr_pos + 1]
            elif k == "PAGE_UP":
                if self.visible_indices:
                    curr_pos = self.visible_indices.index(self.selected_idx)
                    self.selected_idx = self.visible_indices[max(0, curr_pos - self.page_size)]
            elif k == "PAGE_DOWN":
                if self.visible_indices:
                    curr_pos = self.visible_indices.index(self.selected_idx)
                    self.selected_idx = self.visible_indices[min(len(self.visible_indices) - 1, curr_pos + self.page_size)]
            elif k == "HOME":
                if self.visible_indices:
                    self.selected_idx = self.visible_indices[0]
            elif k == "END":
                if self.visible_indices:
                    self.selected_idx = self.visible_indices[-1]
            elif k in ("/", "f", "F"):
                q = prompt_input("Search (title, UUID, workspace):")
                self.update_filter(q)
            elif k in ("a", "A"):
                self.show_all = not self.show_all
                self.refresh_data()
            elif k in ("m", "M"):
                self.interactive_move_workspace()
            elif k in ("t", "T"):
                if self.visible_indices:
                    cid = self.rows[self.selected_idx][0]
                    show_transcript_pager(cid)
            elif k in ("y", "Y"):
                if self.visible_indices:
                    cid = self.rows[self.selected_idx][0]
                    if copy_to_clipboard(cid):
                        console.print(f"\n[bold green]Copied conversation UUID to clipboard![/bold green]")
                    else:
                        console.print(f"\n[cyan]UUID: {cid}[/cyan]")
                    console.print("Press any key to return...")
                    get_key()
            elif k in ("ENTER",):
                if self.visible_indices:
                    cid = self.rows[self.selected_idx][0]
                    resume_conversation(cid)
                    return
            elif k == "ESC":
                if self.filter_query:
                    self.update_filter("")
                else:
                    return
            elif k in ("q", "Q"):
                return


# ==============================================================================
# Transcript & Table Fallback Routines
# ==============================================================================

def show_transcript_pager(cid: str):
    steps, user_prompts, asst_replies = get_conversation_details(cid)
    if not steps:
        tpath = os.path.join(BRAIN_DIR, cid, ".system_generated/logs/transcript.jsonl")
        console.print(f"[bold red]No transcript steps found at {tpath}[/bold red]")
        prompt_input("Press Enter to continue...")
        return

    buf = []
    buf.append("=" * 70)
    buf.append(f"TRANSCRIPT FOR CONVERSATION {cid}")
    buf.append("=" * 70)
    buf.append("")

    turn_idx = 1
    for s in steps:
        stype = s.get("type", "")
        created_at = s.get("created_at", "")
        content = s.get("content", "")

        if stype == "USER_INPUT":
            cleaned = clean_user_message(content)
            buf.append(f"━━━ [USER TURN #{turn_idx}] ━━━━━━━━━━━━━ {created_at} ━━━")
            buf.append(cleaned)
            buf.append("")
            turn_idx += 1
        elif stype == "PLANNER_RESPONSE":
            if content:
                buf.append(f"━━━ [ASSISTANT] ━━━━━━━━━━━━━━━━━━━━━━ {created_at} ━━━")
                buf.append(content)
                buf.append("")
            tool_calls = s.get("tool_calls", [])
            for tc in tool_calls:
                tname = tc.get("name", "tool")
                tsum = tc.get("toolSummary", "")
                targs = tc.get("args", {})
                buf.append(f"▶ Tool: {tname} ({tsum})")
                if "CommandLine" in targs:
                    buf.append(f"  $ {targs['CommandLine']}")
                elif "TargetFile" in targs:
                    buf.append(f"  File: {targs['TargetFile']}")
            if tool_calls:
                buf.append("")
        elif stype in ("SYSTEM_MESSAGE", "GENERIC"):
            if content and not content.startswith("{"):
                buf.append(f"[System: {content[:100]}]")

    transcript_text = "\n".join(buf)
    pager = os.environ.get("PAGER")
    if pager and shutil.which(pager.split()[0]):
        try:
            proc = subprocess.Popen(pager, shell=True, stdin=subprocess.PIPE, text=True)
            proc.communicate(input=transcript_text)
            return
        except Exception:
            pass

    # Rich pager fallback
    with console.pager(styles=True):
        console.print(transcript_text)


def list_table(show_all: bool = False):
    rows = query_conversations(show_all=show_all)
    if not rows:
        console.print("[yellow]No conversations found in database.[/yellow]")
        return

    table = Table(title="Antigravity Conversation History", expand=True, box=box.ROUNDED)
    table.add_column("ID", style="cyan", width=10)
    table.add_column("Active", justify="center", width=12)
    table.add_column("Steps", justify="right", width=7)
    table.add_column("Workspace", style="green", width=18)
    table.add_column("Title / Snippet", style="white", ratio=1)

    for row in rows:
        cid, title, prev, step_count, last_mod, ws_uris, agent_name, depth, parent_id = row
        dt = parse_time(last_mod)
        rel_time = format_relative(dt)
        ws_label = get_workspace_label(ws_uris)
        eff_title = (title or "").strip()
        if not eff_title:
            if agent_name:
                eff_title = f"[{agent_name}]"
            elif prev:
                eff_title = prev.strip().splitlines()[0][:50]
            else:
                eff_title = "(Untitled Session)"
        table.add_row(cid[:8], rel_time, str(step_count), escape(ws_label[:18]), escape(eff_title))

    console.print(table)


def resume_latest():
    rows = query_conversations(show_all=False)
    if not rows:
        rows = query_conversations(show_all=True)
    if not rows:
        console.print("[bold red]No previous conversations found.[/bold red]")
        sys.exit(1)
    cid = rows[0][0]
    resume_conversation(cid)


# ==============================================================================
# CLI Entry Point
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Interactive TUI to browse, inspect, resume, and manage Google Antigravity (agy) conversations."
    )
    parser.add_argument(
        "query",
        nargs="?",
        default="",
        help="Optional search query or conversation ID / 'transcript <id>'"
    )
    parser.add_argument(
        "arg2",
        nargs="?",
        default="",
        help="Subcommand argument (e.g. target workspace path for --move, or conversation ID for 'transcript')"
    )
    parser.add_argument(
        "-a", "--all",
        action="store_true",
        help="Show all conversations, including subagents and empty sessions"
    )
    parser.add_argument(
        "-l", "--list",
        action="store_true",
        help="Print conversation list in tabular format and exit"
    )
    parser.add_argument(
        "-c", "--continue", "--last",
        dest="resume_last",
        action="store_true",
        help="Resume the most recent conversation immediately"
    )
    parser.add_argument(
        "-m", "--move",
        nargs=2,
        metavar=("CONV", "TARGET_WORKSPACE"),
        help="Move/relocate conversation workspace (e.g. --move JB3 E:\\JB)"
    )
    parser.add_argument(
        "-w", "--workspaces",
        action="store_true",
        help="List all known workspaces and their conversation counts"
    )
    parser.add_argument(
        "--fzf",
        action="store_true",
        help="Force fzf TUI if fzf is installed"
    )

    args = parser.parse_args()

    # 1. Handle Workspace Migration
    if args.move:
        cid_query, target_ws = args.move
        ok, msg = move_conversation_workspace(cid_query, target_ws)
        if ok:
            console.print(f"[bold green]✔[/bold green] {msg}")
        else:
            console.print(f"[bold red]✘[/bold red] {msg}")
            sys.exit(1)
        return

    # 2. Handle Listing Workspaces
    if args.workspaces:
        ws_list = list_workspaces()
        table = Table(title="Antigravity Registered Workspaces", expand=True, box=box.ROUNDED)
        table.add_column("Workspace Label", style="bold yellow", width=22)
        table.add_column("Path / URI", style="cyan", ratio=1)
        table.add_column("Conversations", justify="right", width=14, style="bold green")
        for w in ws_list:
            table.add_row(w["label"], w["path"], str(w["count"]))
        console.print(table)
        return

    # 3. Direct transcript view
    if args.query == "transcript" and args.arg2:
        show_transcript_pager(args.arg2)
        return

    # 4. Direct resume latest
    if args.resume_last:
        resume_latest()
        return

    # 5. Direct list
    if args.list:
        list_table(show_all=args.all)
        return

    # 6. Direct CID check
    if args.query and not args.arg2 and re.match(r"^[0-9a-fA-F\-]{6,}$", args.query):
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT conversation_id FROM conversation_summaries WHERE conversation_id LIKE ? LIMIT 2",
                (f"{args.query}%",)
            )
            matches = cur.fetchall()
            conn.close()
            if len(matches) == 1:
                cid = matches[0][0]
                resume_conversation(cid)
                return

    # 7. Launch Native Interactive TUI
    app = RichChatsTUI(show_all=args.all, initial_query=args.query)
    app.run()


if __name__ == "__main__":
    main()
