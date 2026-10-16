"""
tui: Rich Terminal User Interface components for agy-chats & agy-fork.
Includes MainChatsTUI (conversation browser), TurnExplorerTUI (forking),
ToolCutterTUI (tool-level surgery), and full transcript viewer.
"""

import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import json
import sqlite3
import subprocess
import shutil
from typing import List, Dict, Optional, Tuple, Any, Set

from rich.console import Console, Group
from rich.table import Table
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text
from rich import box
from rich.markup import escape

from session_engine import (
    SessionReader,
    fork_session,
    move_conversation_workspace,
    list_workspaces,
    format_workspace_path,
    get_workspace_label,
    parse_time,
    format_relative,
    copy_to_clipboard,
    load_preview_view,
    toggle_preview_view,
    build_resume_cmd,
    DEFAULT_CONV_DIR,
    DEFAULT_BRAIN_DIR,
    DEFAULT_SUMMARIES_DB
)

console = Console()

PREVIEW_REPLY_MAX_LINES = 8


def show_resume_command(cid: str):
    """Prints the resume command for a conversation (plain, so it never gets line-wrapped) and copies it."""
    cmd = build_resume_cmd(cid)
    copied = copy_to_clipboard(cmd)
    os.system("cls" if os.name == "nt" else "clear")
    console.print("[bold green]Resume command[/bold green]" + (" [dim](copied to clipboard)[/dim]" if copied else "") + ":\n")
    sys.stdout.write(cmd + "\n")
    sys.stdout.flush()


# ==============================================================================
# Keyboard Input Helpers
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
            elif ch2 == b'K': return "LEFT"
            elif ch2 == b'M': return "RIGHT"
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
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
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
            elif ch in ('\r', '\n'):
                return "ENTER"
            elif ch in ('\x7f', '\x08'):
                return "BACKSPACE"
            elif ch == '\t':
                return "TAB"
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


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
# Success & Transcript Helpers
# ==============================================================================

def show_success_screen(res: Dict[str, Any]):
    os.system("cls" if os.name == "nt" else "clear")

    new_uuid = res["new_cascade_id"]
    resume_cmd = res["resume_cmd"]
    copied = copy_to_clipboard(resume_cmd)

    success_text = Text()
    success_text.append("Antigravity Session Forked Successfully!\n\n", style="bold green")
    success_text.append("Source Session : ", style="bold")
    success_text.append(f"{res['source_cascade_id']}\n", style="cyan")
    success_text.append("New Session UUID: ", style="bold")
    success_text.append(f"{new_uuid}\n", style="bold yellow")
    cut_desc = res.get('cut_description') or f"Step {res.get('cut_step_idx')}"
    success_text.append(f"{cut_desc}\n", style="white")
    success_text.append("Steps Copied   : ", style="bold")
    success_text.append(f"{res['copied_steps']} steps\n", style="dim")
    success_text.append("Brain Artifacts: ", style="bold")
    success_text.append(f"{'Copied' if res['brain_copied'] else 'Not present'}\n\n", style="dim")

    success_text.append("Resume Command:\n", style="bold white")
    success_text.append(f"  {resume_cmd}\n\n", style="bold green on black")

    if copied:
        success_text.append("[OK] Command automatically copied to clipboard!\n\n", style="bold cyan")
    else:
        success_text.append("Note: Could not copy to clipboard automatically.\n\n", style="dim")

    success_text.append("[R] Run 'agy' now  |  [C] Copy again  |  [Enter / Q] Exit", style="bold yellow")

    console.print(Panel(success_text, title="[bold]Session Fork Completed[/bold]", border_style="green", box=box.ROUNDED))

    while True:
        k = get_key()
        if k in ("r", "R"):
            console.print("\n[bold green]Launching agy session...[/bold green]\n")
            if sys.platform == "win32":
                subprocess.run(f"agy --conversation {new_uuid}", shell=True)
            else:
                os.execvp("agy", ["agy", "--conversation", new_uuid])
            break
        elif k in ("c", "C"):
            copy_to_clipboard(resume_cmd)
            console.print("[cyan]Copied again to clipboard![/cyan]")
        elif k in ("ENTER", "q", "Q", "ESC"):
            break


def show_transcript_pager(cid: str, brain_dir: str = DEFAULT_BRAIN_DIR):
    tpath = os.path.join(brain_dir, cid, ".system_generated/logs/transcript.jsonl")
    if not os.path.exists(tpath):
        console.print(f"[bold red]No transcript logs found at {tpath}[/bold red]")
        prompt_input("Press Enter to continue...")
        return

    buf = []
    buf.append("=" * 70)
    buf.append(f"TRANSCRIPT FOR CONVERSATION {cid}")
    buf.append("=" * 70)
    buf.append("")

    turn_idx = 1
    with open(tpath, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                s = json.loads(line)
                stype = s.get("type", "")
                created_at = s.get("created_at", "")
                content = s.get("content", "")

                if stype == "USER_INPUT":
                    buf.append(f"━━━ [USER TURN #{turn_idx}] ━━━━━━━━━━━━━ {created_at} ━━━")
                    buf.append(content.strip())
                    buf.append("")
                    turn_idx += 1
                elif stype == "PLANNER_RESPONSE":
                    if content:
                        buf.append(f"━━━ [ASSISTANT] ━━━━━━━━━━━━━━━━━━━━━━ {created_at} ━━━")
                        buf.append(content.strip())
                        buf.append("")
                    for tc in s.get("tool_calls", []):
                        tname = tc.get("name", "tool")
                        tsum = tc.get("toolSummary", "")
                        targs = tc.get("args", {})
                        buf.append(f"▶ Tool: {tname} ({tsum})")
                        if "CommandLine" in targs:
                            buf.append(f"  $ {targs['CommandLine']}")
                        elif "TargetFile" in targs:
                            buf.append(f"  File: {targs['TargetFile']}")
            except Exception:
                pass

    transcript_text = "\n".join(buf)
    with console.pager(styles=True):
        console.print(transcript_text)


# ==============================================================================
# ToolCutterTUI: Fine-Grained Tool Call & Edit Surgery (--tool)
# ==============================================================================

class ToolCutterTUI:
    def __init__(self, conv_id_or_path: str, turn_index: Optional[int] = None):
        self.reader = SessionReader(conv_id_or_path)
        self.turns = self.reader.get_turns()
        self.turns_with_tools = [t for t in self.turns if t.get("tools")]

        if not self.turns_with_tools:
            self.current_turn = self.turns[-1] if self.turns else None
            self.tools = []
        else:
            if turn_index is not None:
                match = next((t for t in self.turns if t["turn_index"] == turn_index), None)
                self.current_turn = match or self.turns_with_tools[-1]
            else:
                self.current_turn = self.turns_with_tools[-1]
            self.tools = self.current_turn.get("tools", [])

        self.selected_idx = max(0, len(self.tools) - 1)
        self.filter_query = ""
        self.visible_indices = list(range(len(self.tools)))
        self.page_size = 13

    def switch_turn(self, forward: bool = True):
        if not self.turns_with_tools or len(self.turns_with_tools) <= 1:
            return
        curr_i = self.turns_with_tools.index(self.current_turn)
        next_i = (curr_i + 1) % len(self.turns_with_tools) if forward else (curr_i - 1) % len(self.turns_with_tools)
        self.current_turn = self.turns_with_tools[next_i]
        self.tools = self.current_turn.get("tools", [])
        self.selected_idx = max(0, len(self.tools) - 1)
        self.update_filter("")

    def update_filter(self, query: str):
        self.filter_query = query.strip()
        if not self.filter_query:
            self.visible_indices = list(range(len(self.tools)))
        else:
            q_lower = self.filter_query.lower()
            self.visible_indices = [
                i for i, tl in enumerate(self.tools)
                if q_lower in tl["tool_name"].lower()
                or q_lower in tl.get("ui_name", "").lower()
                or q_lower in tl.get("full_label", "").lower()
                or any(q_lower in str(v).lower() for v in tl.get("args", {}).values())
            ]
        self.selected_idx = self.visible_indices[-1] if self.visible_indices else 0

    def render(self):
        os.system("cls" if os.name == "nt" else "clear")

        header_text = Text()
        header_text.append("Antigravity Tool Cutter  |  ", style="bold green")
        header_text.append(f"Session: {self.reader.cascade_id}\n", style="bold yellow")
        t_num = self.current_turn["turn_index"] if self.current_turn else 0
        prompt_snip = (self.current_turn["user_text"] if self.current_turn else "").replace("\n", " ").strip()
        if len(prompt_snip) > 70:
            prompt_snip = prompt_snip[:67] + "..."
        header_text.append(f"Turn #{t_num} (Prompt: \"{prompt_snip}\")\n", style="cyan")
        header_text.append(f"Tools in Turn: {len(self.tools)}  |  ", style="dim")
        if len(self.turns_with_tools) > 1:
            header_text.append(f"Turns with tools: {len(self.turns_with_tools)} (Tab to switch)  |  ", style="dim")
        if self.filter_query:
            header_text.append(f"Filter: '{self.filter_query}' ({len(self.visible_indices)} matching)", style="bold magenta")
        else:
            header_text.append("Filter: None (press '/' to search)", style="dim")

        console.print(Panel(header_text, border_style="green", box=box.ROUNDED))

        if not self.tools:
            console.print(Panel("[bold red]No tool calls recorded in this turn.[/bold red]\nPress [bold yellow]TAB[/bold yellow] to switch turn or [bold yellow]ESC[/bold yellow] to exit.", border_style="red"))
            self.render_controls()
            return

        if not self.visible_indices:
            console.print(Panel(f"[bold red]No tools match '{escape(self.filter_query)}'.[/bold red]\nPress [bold yellow]'/'[/bold yellow] to change filter or [bold yellow]ESC[/bold yellow] to clear.", border_style="red"))
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
        table.add_column("Tool #", justify="right", style="bold", width=8)
        table.add_column("Step", justify="center", width=8)
        table.add_column("Action", justify="center", width=12)
        table.add_column("Tool Invocation / Target / Command", style="white", ratio=1)

        for pos in range(start_pos, end_pos):
            idx = self.visible_indices[pos]
            tl = self.tools[idx]
            is_selected = (idx == self.selected_idx)

            t_num_str = f"#{tl.get('tool_number', idx + 1)}"
            if is_selected:
                row_style = "bold white on blue"
                t_num_str = f"> {t_num_str}"
            else:
                row_style = "none"

            ui_name = tl.get("ui_name", tl["tool_name"])
            if ui_name == "Edit":
                type_badge = "[bold green]Edit[/bold green]"
            elif ui_name == "Bash":
                type_badge = "[bold yellow]Bash[/bold yellow]"
            elif ui_name == "Read":
                type_badge = "[bold cyan]Read[/bold cyan]"
            elif ui_name == "ManageTask":
                type_badge = "[bold magenta]Task[/bold magenta]"
            else:
                type_badge = f"[bold white]{ui_name}[/bold white]"

            table.add_row(
                t_num_str,
                str(tl["step_idx"]),
                type_badge,
                escape(tl.get("full_label", tl.get("short_label", ""))),
                style=row_style
            )

        console.print(table)

        sel_tl = self.tools[self.selected_idx]
        preview_text = Text()
        preview_text.append(f"Tool #{sel_tl.get('tool_number', self.selected_idx + 1)}  |  Step {sel_tl['step_idx']}  |  ", style="bold yellow")
        preview_text.append(f"{sel_tl.get('ui_name', sel_tl['tool_name'])}\n", style="bold cyan")
        preview_text.append(f"Full Label: {sel_tl.get('full_label', '')}\n", style="white")

        args = sel_tl.get("args", {})
        if "toolSummary" in args:
            preview_text.append(f"Summary   : {args['toolSummary']}\n", style="dim")
        if "toolAction" in args:
            preview_text.append(f"Action    : {args['toolAction']}\n", style="dim")
        if "CommandLine" in args:
            preview_text.append(f"Command   : {args['CommandLine'][:180]}\n", style="dim")
        elif "TargetFile" in args:
            preview_text.append(f"File      : {args['TargetFile']}\n", style="dim")

        console.print(Panel(preview_text, title="[bold]Selected Tool Details[/bold]", border_style="yellow", box=box.ROUNDED))
        self.render_controls()

    def render_controls(self):
        ctrls = Text()
        ctrls.append(" [Up/Down or k/j] Navigate  |  ", style="bold cyan")
        ctrls.append("[Enter or a] Cut AFTER Tool  |  ", style="bold green")
        ctrls.append("[b] Cut BEFORE Tool  |  ", style="bold yellow")
        ctrls.append("[v] Full Args  |  ", style="bold magenta")
        ctrls.append("[/] Search  |  ", style="bold white")
        if len(self.turns_with_tools) > 1:
            ctrls.append("[Tab] Switch Turn  |  ", style="bold yellow")
        ctrls.append("[q/Esc] Quit", style="bold red")
        console.print(ctrls)

    def show_tool_details(self):
        if not self.visible_indices:
            return
        tl = self.tools[self.selected_idx]
        os.system("cls" if os.name == "nt" else "clear")
        details_text = Text()
        details_text.append(f"Tool #{tl.get('tool_number', '?')} (Step {tl['step_idx']})\n\n", style="bold yellow")
        details_text.append(f"Action Type: {tl.get('ui_name', tl['tool_name'])} ({tl['tool_name']})\n", style="bold cyan")
        details_text.append(f"Invocation : {tl.get('full_label')}\n", style="white")
        details_text.append(f"Call ID    : {tl.get('call_id') or 'N/A'}\n\n", style="dim")
        details_text.append("Arguments JSON:\n", style="bold green")
        try:
            details_text.append(json.dumps(tl.get("args", {}), indent=2), style="white")
        except Exception:
            details_text.append(str(tl.get("args", {})), style="white")
        console.print(Panel(details_text, title=f"Full Details - {tl.get('short_label', '')}", border_style="cyan"))
        console.print("\n[bold yellow]Press any key to return...[/bold yellow]")
        get_key()

    def run(self) -> Optional[Dict[str, Any]]:
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
            elif k == "TAB":
                self.switch_turn(forward=True)
            elif k in ("/", "f", "F"):
                q = prompt_input("Search / filter tools (Enter to apply, Esc to clear):")
                self.update_filter(q)
            elif k in ("v", "V"):
                self.show_tool_details()
            elif k in ("ENTER", "a", "A"):
                if self.visible_indices:
                    tl = self.tools[self.selected_idx]
                    cut_idx = tl["step_idx"]
                    desc = f"Cut AFTER Tool #{tl.get('tool_number', self.selected_idx + 1)} '{tl.get('short_label')}' (step {cut_idx})"
                    console.print(f"\n[bold green]Forking session at {desc}...[/bold green]")
                    try:
                        res = fork_session(self.reader.cascade_id, cut_step_idx=cut_idx)
                        res["cut_description"] = desc
                        res["turn_number"] = self.current_turn["turn_index"] if self.current_turn else None
                        return res
                    except Exception as e:
                        console.print(f"[bold red]Fork failed:[/bold red] {e}")
                        get_key()
            elif k in ("b", "B"):
                if self.visible_indices:
                    tl = self.tools[self.selected_idx]
                    cut_idx = max(0, tl["step_idx"] - 1)
                    desc = f"Cut BEFORE Tool #{tl.get('tool_number', self.selected_idx + 1)} '{tl.get('short_label')}' (step {cut_idx})"
                    console.print(f"\n[bold green]Forking session at {desc}...[/bold green]")
                    try:
                        res = fork_session(self.reader.cascade_id, cut_step_idx=cut_idx)
                        res["cut_description"] = desc
                        res["turn_number"] = self.current_turn["turn_index"] if self.current_turn else None
                        return res
                    except Exception as e:
                        console.print(f"[bold red]Fork failed:[/bold red] {e}")
                        get_key()
            elif k == "ESC":
                if self.filter_query:
                    self.update_filter("")
                else:
                    return None
            elif k in ("q", "Q"):
                return None


# ==============================================================================
# TurnExplorerTUI: Conversation Turn Forker & Brancher
# ==============================================================================

class TurnExplorerTUI:
    def __init__(self, conv_id_or_path: str):
        self.reader = SessionReader(conv_id_or_path)
        self.turns = self.reader.get_turns()
        self.selected_idx = max(0, len(self.turns) - 1)
        self.filter_query = ""
        self.visible_indices = list(range(len(self.turns)))
        self.page_size = 12

    def update_filter(self, query: str):
        self.filter_query = query.strip()
        if not self.filter_query:
            self.visible_indices = list(range(len(self.turns)))
        else:
            q_lower = self.filter_query.lower()
            self.visible_indices = [
                i for i, t in enumerate(self.turns)
                if q_lower in t["user_text"].lower() or q_lower in (t["assistant_text"] or "").lower()
            ]
        self.selected_idx = self.visible_indices[0] if self.visible_indices else 0

    def render(self):
        os.system("cls" if os.name == "nt" else "clear")

        header_text = Text()
        header_text.append("Antigravity Session Forker  |  ", style="bold cyan")
        header_text.append(f"Conversation: {self.reader.cascade_id}\n", style="bold yellow")
        header_text.append(f"Total Steps: {self.turns[-1]['end_step'] + 1 if self.turns else 0}  |  ", style="dim")
        header_text.append(f"Total Turns: {len(self.turns)}  |  ", style="dim")
        if self.filter_query:
            header_text.append(f"Filter: '{self.filter_query}' ({len(self.visible_indices)} matching)", style="bold magenta")
        else:
            header_text.append("Filter: None (press '/' to search)", style="dim")

        console.print(Panel(header_text, border_style="cyan", box=box.ROUNDED))

        if not self.visible_indices:
            console.print(Panel("[bold red]No turns matched the query.[/bold red]", border_style="red"))
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
        table.add_column("Turn #", justify="right", style="bold", width=8)
        table.add_column("Steps", justify="center", width=14)
        table.add_column("Tools", justify="center", width=7)
        table.add_column("User Prompt Snippet", style="white", ratio=1)

        for pos in range(start_pos, end_pos):
            idx = self.visible_indices[pos]
            t = self.turns[idx]
            is_selected = (idx == self.selected_idx)

            prompt_snippet = t["user_text"].replace("\n", " ").strip()
            if len(prompt_snippet) > 85:
                prompt_snippet = prompt_snippet[:82] + "..."

            step_span = f"{t['start_step']}..{t['end_step']}"
            tool_badge = f"{t['tool_count']}" if t['tool_count'] > 0 else "-"
            turn_str = f"> #{t['turn_index']}" if is_selected else f"#{t['turn_index']}"
            row_style = "bold white on blue" if is_selected else "none"

            table.add_row(turn_str, step_span, tool_badge, escape(prompt_snippet), style=row_style)

        console.print(table)

        sel_turn = self.turns[self.selected_idx]
        preview_text = Text()
        preview_text.append(f"Turn #{sel_turn['turn_index']}  [Steps {sel_turn['start_step']} to {sel_turn['end_step']}]\n", style="bold yellow")
        preview_text.append("User Prompt:\n", style="bold cyan")
        user_full = sel_turn["user_text"].strip()
        preview_text.append(f"{user_full[:300]}{'...' if len(user_full) > 300 else ''}\n\n", style="white")

        if sel_turn["assistant_text"]:
            preview_text.append("Assistant Preview:\n", style="bold green")
            asst_snippet = sel_turn["assistant_text"].strip()
            preview_text.append(f"{asst_snippet[:250]}{'...' if len(asst_snippet) > 250 else ''}\n", style="dim")

        console.print(Panel(preview_text, title=f"[bold]Turn #{sel_turn['turn_index']} Details[/bold]", border_style="yellow", box=box.ROUNDED))
        self.render_controls()

    def render_controls(self):
        ctrls = Text()
        ctrls.append(" [Up/Down or k/j] Navigate  |  ", style="bold cyan")
        ctrls.append("[Enter or c] Choose Cut  |  ", style="bold green")
        ctrls.append("[t] Tool Cutter  |  ", style="bold yellow")
        ctrls.append("[v] View Text  |  ", style="bold magenta")
        ctrls.append("[/] Filter  |  ", style="bold white")
        ctrls.append("[q/Esc] Quit", style="bold red")
        console.print(ctrls)

    def choose_cut_and_fork(self) -> Optional[Dict[str, Any]]:
        sel_turn = self.turns[self.selected_idx]
        t_num = sel_turn["turn_index"]

        os.system("cls" if os.name == "nt" else "clear")
        cut_menu = Text()
        cut_menu.append(f"Select Cut Point for Turn #{t_num}\n\n", style="bold yellow")
        cut_menu.append(f"Prompt: {sel_turn['user_text'][:120]}...\n\n", style="white")

        cut_menu.append("  [1] Cut AFTER this Turn  (Recommended)\n", style="bold green")
        cut_menu.append(f"      Preserves Turn #{t_num} fully (steps up to {sel_turn['end_step']}). Drops subsequent turns.\n\n", style="dim")

        cut_menu.append("  [2] Cut BEFORE this Turn (Rewind)\n", style="bold cyan")
        cut_menu.append(f"      Rewinds session to state BEFORE this prompt (steps up to {sel_turn['start_step'] - 1}).\n\n", style="dim")

        cut_menu.append("  [3] Cut at Prompt Only\n", style="bold magenta")
        cut_menu.append(f"      Keeps prompt at step {sel_turn['start_step']}, discards execution/response.\n\n", style="dim")

        if sel_turn.get("tools"):
            cut_menu.append(f"  [4] Cut at specific Tool Call / Edit ({len(sel_turn['tools'])} tools)\n", style="bold yellow")
            cut_menu.append(f"      Branch inside Turn #{t_num} right after a specific Edit or Bash command.\n\n", style="dim")

        cut_menu.append("  [Esc / q] Cancel\n", style="bold red")

        console.print(Panel(cut_menu, title="[bold]Fork Branching Menu[/bold]", border_style="yellow", box=box.ROUNDED))
        console.print("[bold]Select an option:[/bold] ", end="")
        sys.stdout.flush()

        while True:
            k = get_key()
            if k in ("1", "a", "A"):
                cut_idx = sel_turn["end_step"]
                desc = f"Cut AFTER Turn #{t_num} (step {cut_idx})"
                break
            elif k in ("2", "b", "B"):
                cut_idx = max(0, sel_turn["start_step"] - 1)
                desc = f"Cut BEFORE Turn #{t_num} (step {cut_idx})"
                break
            elif k in ("3", "p", "P"):
                cut_idx = sel_turn["start_step"]
                desc = f"Cut at Prompt of Turn #{t_num} (step {cut_idx})"
                break
            elif k in ("4", "t", "T") and sel_turn.get("tools"):
                cutter = ToolCutterTUI(self.reader.cascade_id, turn_index=t_num)
                return cutter.run()
            elif k in ("ESC", "q", "Q"):
                return None

        console.print(f"\n[bold green]Forking session up to step {cut_idx}...[/bold green]")
        try:
            res = fork_session(self.reader.cascade_id, cut_step_idx=cut_idx)
            res["cut_description"] = desc
            res["turn_number"] = t_num
            return res
        except Exception as e:
            console.print(f"[bold red]Fork failed:[/bold red] {e}")
            get_key()
            return None

    def run(self) -> Optional[Dict[str, Any]]:
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
                q = prompt_input("Search prompts:")
                self.update_filter(q)
            elif k in ("t", "T"):
                cutter = ToolCutterTUI(self.reader.cascade_id, turn_index=self.turns[self.selected_idx]["turn_index"])
                res = cutter.run()
                if res:
                    return res
            elif k in ("ENTER", "c", "C"):
                if self.visible_indices:
                    res = self.choose_cut_and_fork()
                    if res:
                        return res
            elif k == "ESC":
                if self.filter_query:
                    self.update_filter("")
                else:
                    return None
            elif k in ("q", "Q"):
                return None


# ==============================================================================
# Live Conversation Preview Builder (Split Screen Right Pane)
# ==============================================================================

def _preview_view_chips(view: Dict[str, bool]) -> Text:
    """'View: ☑ Prompts  ☑ Tools  ☐ Replies' status line (prompts are always on)."""
    chips = Text("View:      ", style="bold")
    chips.append("☑ Prompts", style="bold green")
    for key, label in (("tools", "Tools"), ("replies", "Replies")):
        on = view.get(key, False)
        chips.append("  ")
        chips.append(f"{'☑' if on else '☐'} {label}", style="bold green" if on else "dim")
    return chips


def build_conversation_preview_lines(
    cid: str,
    row_data: Tuple,
    max_width: int = 65,
    view: Optional[Dict[str, bool]] = None
) -> List[Text]:
    """Builds formatted lines for the right-hand scrollable preview pane.

    Prompts are always shown; view["tools"] / view["replies"] switch the extras on or off.
    """
    lines: List[Text] = []
    cid, title, prev, step_count, last_mod, ws_uris, agent_name, depth, parent_id = row_data
    if view is None:
        view = load_preview_view()
    show_tools = bool(view.get("tools"))
    show_replies = bool(view.get("replies"))

    dt = parse_time(last_mod)
    rel_time = format_relative(dt)
    exact_time = dt.strftime("%Y-%m-%d %H:%M:%S UTC") if dt else (last_mod or "")[:19]
    ws_str = format_workspace_path(ws_uris)

    try:
        reader = SessionReader(cid)
        turns = reader.get_turns()
    except Exception:
        turns = []

    eff_title = (title or "").strip()
    if not eff_title:
        if turns and turns[0].get("user_text"):
            eff_title = turns[0]["user_text"].splitlines()[0][:50]
        elif agent_name:
            eff_title = f"Subagent: {agent_name}"
        elif prev:
            eff_title = prev.strip().splitlines()[0][:50]
        else:
            eff_title = "(Untitled Session)"

    # 1. Stylized Boxed Title (matching original preview pane)
    box_inner_w = max(10, min(max_width - 4, len(eff_title) + 4))
    title_display = f" {eff_title} "
    if len(title_display) > box_inner_w:
        title_display = title_display[:box_inner_w - 3] + "... "

    t_top = Text("╭" + "─" * box_inner_w + "╮", style="bold cyan")
    t_mid = Text("│", style="bold cyan")
    t_mid.append(f"{title_display:<{box_inner_w}}", style="bold white")
    t_mid.append("│", style="bold cyan")
    t_bot = Text("╰" + "─" * box_inner_w + "╯", style="bold cyan")

    lines.append(t_top)
    lines.append(t_mid)
    lines.append(t_bot)
    lines.append(Text(""))

    # 2. Metadata Block
    t_id = Text("ID:        ", style="bold")
    t_id.append(cid, style="dim cyan")
    lines.append(t_id)

    t_type = Text()
    if agent_name:
        t_type.append("Agent:     ", style="bold")
        t_type.append(f"{agent_name} (depth {depth})", style="bold magenta")
    else:
        t_type.append("Type:      ", style="bold")
        t_type.append("Main User Session", style="bold green")
    lines.append(t_type)

    t_act = Text("Active:    ", style="bold")
    t_act.append(rel_time, style="bold yellow")
    t_act.append(f" ({exact_time})", style="dim")
    lines.append(t_act)

    t_stats = Text("Stats:     ", style="bold")
    t_stats.append(f"{step_count} total steps", style="cyan")
    t_stats.append(f" • {len(turns)} user turns", style="blue")
    lines.append(t_stats)

    t_ws = Text("Workspace: ", style="bold")
    t_ws.append(ws_str, style="green")
    lines.append(t_ws)
    lines.append(_preview_view_chips(view))
    lines.append(Text(""))

    # 3. Turns & Content: prompts always; tool calls / assistant replies per the view switches,
    #    interleaved in the order they happened.
    if turns:
        for turn in turns:
            n = turn["turn_index"]
            head = "▶ INITIAL USER REQUEST:" if n == 1 else f"▶ USER TURN #{n}:"
            lines.append(Text(head, style="bold yellow"))
            for l in turn["user_text"].strip().splitlines():
                t = Text("  │ ", style="dim")
                t.append(l, style="white")
                lines.append(t)
            lines.append(Text(""))

            if not (show_tools or show_replies):
                continue

            wrote_any = False
            prev_kind = None
            for kind, val in turn.get("events", []):
                if kind == "reply" and show_replies:
                    if prev_kind == "tool":
                        lines.append(Text(""))
                    lines.append(Text("▶ ASSISTANT:", style="bold green"))
                    reply_lines = val.strip().splitlines()
                    for l in reply_lines[:PREVIEW_REPLY_MAX_LINES]:
                        t = Text("  │ ", style="dim")
                        t.append(l, style="dim white")
                        lines.append(t)
                    if len(reply_lines) > PREVIEW_REPLY_MAX_LINES:
                        lines.append(Text(f"  │ … [{len(reply_lines) - PREVIEW_REPLY_MAX_LINES} more lines]", style="dim"))
                    lines.append(Text(""))
                    wrote_any = True
                    prev_kind = "reply"
                elif kind == "tool" and show_tools:
                    t = Text("  ▸ ", style="cyan")
                    t.append(f"#{val.get('tool_number', '?')} ", style="dim")
                    t.append(val.get("short_label", val["tool_name"]), style="yellow")
                    lines.append(t)
                    wrote_any = True
                    prev_kind = "tool"
            if wrote_any and prev_kind == "tool":
                lines.append(Text(""))
    elif prev:
        lines.append(Text("▶ PREVIEW SNIPPET:", style="bold yellow"))
        for l in prev.strip().splitlines():
            t = Text("  │ ", style="dim")
            t.append(l, style="white")
            lines.append(t)
        lines.append(Text(""))

    # 4. Resume CLI Command
    lines.append(Text("─" * min(max_width, 60), style="dim"))
    t_cli = Text("Resume CLI: ", style="bold")
    t_cli.append(f"agy --conversation {cid}", style="bold cyan")
    lines.append(t_cli)

    return wrap_text_lines(lines, max_width)


def wrap_text_lines(raw_lines: List[Text], max_w: int) -> List[Text]:
    """Ensures no Text line exceeds max_w so Rich never wraps inside Panel and causes viewport overflow."""
    wrapped: List[Text] = []
    for line in raw_lines:
        if len(line.plain) <= max_w:
            wrapped.append(line)
        else:
            try:
                w_parts = list(line.wrap(console, max_w))
                if w_parts:
                    wrapped.extend(w_parts)
                else:
                    wrapped.append(line)
            except Exception:
                plain = line.plain
                for i in range(0, len(plain), max_w):
                    wrapped.append(line.slice(i, min(len(plain), i + max_w)))
    return wrapped


def normalize_dir(ws_uris: Optional[str]) -> Tuple[str, str]:
    """Normalizes workspace uris to (clean_label, full_path)."""
    if not ws_uris:
        return ("(No Workspace)", "~")
    try:
        import urllib.parse
        uris = json.loads(ws_uris)
        if not uris:
            return ("(No Workspace)", "~")
        raw = uris[0].replace("file://", "")
        raw = urllib.parse.unquote(raw)
        if sys.platform == "win32" and raw.startswith("/"):
            if len(raw) >= 3 and raw[2] == ":":
                raw = raw[1:]
        raw = raw.replace("\\", "/").rstrip("/")
        home = os.path.expanduser("~").replace("\\", "/").rstrip("/")
        if raw.lower() == home.lower():
            return ("~ (Home)", raw)
        base = os.path.basename(raw)
        return (base or raw, raw)
    except Exception:
        return ("(No Workspace)", "~")


def build_directory_preview_lines(dir_name: str, dir_path: str, rows_in_dir: List[Any], max_width: int = 65) -> List[Text]:
    """Builds a rich overview preview for a selected directory in grouped mode."""
    lines: List[Text] = []
    box_w = max(10, min(max_width - 4, len(dir_name) + 6))
    lines.append(Text("╭" + "─" * box_w + "╮", style="bold yellow"))
    lines.append(Text(f"│ 📂 {dir_name:<{box_w - 4}} │", style="bold yellow"))
    lines.append(Text("╰" + "─" * box_w + "╯", style="bold yellow"))
    lines.append(Text(""))

    lines.append(Text("Workspace Path: ", style="bold") + Text(dir_path or "(Default / Unset)", style="cyan"))
    lines.append(Text("Total Sessions: ", style="bold") + Text(str(len(rows_in_dir)), style="bold green"))

    total_steps = sum(r[3] for r in rows_in_dir if len(r) > 3 and r[3])
    lines.append(Text("Total Steps:    ", style="bold") + Text(str(total_steps), style="bold magenta"))

    if rows_in_dir:
        latest = rows_in_dir[0]
        dt = parse_time(latest[4])
        lines.append(Text("Last Active:    ", style="bold") + Text(format_relative(dt), style="yellow"))
    lines.append(Text(""))

    lines.append(Text("─" * min(max_width, 60), style="dim"))
    lines.append(Text(f"Sessions in '{dir_name}':", style="bold white"))
    lines.append(Text(""))

    for idx, r in enumerate(rows_in_dir[:15]):
        cid = r[0]
        title = r[1]
        prev = r[2]
        last_mod = r[4]
        dt = parse_time(last_mod)
        rel = format_relative(dt)
        eff_title = (title or "").strip()
        if not eff_title:
            eff_title = (prev or "").strip().splitlines()[0][:28] if prev else "(Untitled)"
        avail_title = max(10, max_width - 23)
        t_row = Text(f" {idx+1:2d}. ", style="dim")
        t_row.append(f"{cid[:6]} ", style="cyan")
        t_row.append(f"{eff_title[:avail_title]:<{avail_title}} ", style="white")
        t_row.append(f"{rel[:7]}", style="dim")
        lines.append(t_row)

    if len(rows_in_dir) > 15:
        lines.append(Text(f"  ... and {len(rows_in_dir) - 15} more sessions", style="dim italic"))

    lines.append(Text(""))
    lines.append(Text("─" * min(max_width, 60), style="dim"))
    lines.append(Text("Press [Space] or [Enter] to Expand / Collapse this folder.", style="bold cyan"))
    return wrap_text_lines(lines, max_width)


def run_move_flow(cid: str, rows: Optional[List[Any]] = None):
    """Interactive 'relocate conversation workspace' screen (shared by the Rich TUI and the fzf shell)."""
    title = cid[:8]
    curr_ws = "~"
    for r in (rows or []):
        if r[0] == cid:
            title = r[1] or cid[:8]
            curr_ws = format_workspace_path(r[5])
            break

    os.system("cls" if os.name == "nt" else "clear")
    menu = Text()
    menu.append(f"Move Conversation: {title} ({cid[:8]})\n\n", style="bold yellow")
    menu.append(f"Current Workspace: {curr_ws}\n\n", style="cyan")

    known = list_workspaces()
    menu.append("Known Workspaces:\n", style="bold green")
    for i, w in enumerate(known[:5], 1):
        menu.append(f"  [{i}] {w['label']} ({w['path']}) [{w['count']} convs]\n", style="white")

    menu.append("\n  [c] Custom Path\n  [Esc] Cancel\n", style="bold cyan")
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


# ==============================================================================
# MainChatsTUI: Master Conversation Explorer, Forker & Workspace Manager
# ==============================================================================

class MainChatsTUI:
    def __init__(
        self,
        show_all: bool = False,
        initial_query: str = "",
        default_action: str = "resume",
        target_turn: Optional[int] = None,
        limit: int = 0,
        group_by_dir: bool = False,
        launch: bool = False
    ):
        self.launch = launch  # True = actually start `agy` on resume (and exit) instead of just handing back the command
        self.preview_view = load_preview_view()
        self.status_cmd = ""
        self.status_copied = False
        self.resume_log: List[str] = []
        self.show_output_area = True  # bottom ~25% resume-commands area (off for the plain session picker)
        self.show_all = show_all
        self.filter_query = initial_query.strip()
        self.default_action = default_action
        self.target_turn = target_turn
        self.limit_count = max(0, limit)
        self.group_by_dir = group_by_dir
        self.expanded_dirs: Set[str] = set()
        self.tree_items: List[Dict[str, Any]] = []
        self.tree_cursor: int = 0
        self.rows = []
        self.visible_indices = []
        self.selected_idx = 0
        self.page_size = 10
        self.preview_scroll_offset = 0
        self.preview_cache = {}
        self.dir_preview_cache = {}
        self.active_focus: str = "list"  # Default: Up/Down arrow keys move session selection!
        self.refresh_data()

    def refresh_data(self):
        if not os.path.exists(DEFAULT_SUMMARIES_DB):
            self.rows = []
            self.visible_indices = []
            self.tree_items = []
            return
        conn = sqlite3.connect(DEFAULT_SUMMARIES_DB)
        cur = conn.cursor()
        if self.show_all:
            cur.execute("""
                SELECT conversation_id, title, preview, step_count, last_modified_time,
                       workspace_uris, agent_name, nesting_depth, parent_conversation_id
                FROM conversation_summaries ORDER BY last_modified_time DESC
            """)
        else:
            cur.execute("""
                SELECT conversation_id, title, preview, step_count, last_modified_time,
                       workspace_uris, agent_name, nesting_depth, parent_conversation_id
                FROM conversation_summaries WHERE nesting_depth = 0 AND step_count > 0
                ORDER BY last_modified_time DESC
            """)
        all_db_rows = cur.fetchall()
        conn.close()

        if self.limit_count > 0:
            self.rows = all_db_rows[:self.limit_count]
        else:
            self.rows = all_db_rows

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
                ws_str = format_workspace_path(ws_uris)
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

        self.rebuild_tree()

    def rebuild_tree(self):
        """Builds directory hierarchy items when grouped by directory."""
        if not self.group_by_dir:
            self.tree_items = []
            return

        groups: Dict[str, Dict[str, Any]] = {}
        for idx in self.visible_indices:
            r = self.rows[idx]
            dir_label, dir_path = normalize_dir(r[5])
            if dir_label not in groups:
                groups[dir_label] = {
                    "dir_key": dir_label,
                    "dir_path": dir_path,
                    "rows": [],
                    "latest_mod": r[4] or ""
                }
            groups[dir_label]["rows"].append((idx, r))

        sorted_groups = sorted(
            groups.values(),
            key=lambda g: g["latest_mod"],
            reverse=True
        )

        # On initial grouping, expand all directories by default
        if not self.expanded_dirs:
            for g in sorted_groups:
                self.expanded_dirs.add(g["dir_key"])

        self.tree_items = []
        for g in sorted_groups:
            d_key = g["dir_key"]
            is_expanded = (d_key in self.expanded_dirs)
            self.tree_items.append({
                "type": "dir",
                "dir_key": d_key,
                "dir_path": g["dir_path"],
                "count": len(g["rows"]),
                "rows": [r for _, r in g["rows"]],
                "expanded": is_expanded
            })
            if is_expanded:
                for orig_idx, r in g["rows"]:
                    self.tree_items.append({
                        "type": "session",
                        "dir_key": d_key,
                        "row_idx": orig_idx,
                        "row": r
                    })

        if self.tree_items:
            self.tree_cursor = min(self.tree_cursor, len(self.tree_items) - 1)
        else:
            self.tree_cursor = 0

    def set_custom_limit(self):
        console.print()
        curr_str = str(self.limit_count) if self.limit_count > 0 else "All"
        val = prompt_input(f"Enter custom number of sessions to display (0 for all) [Current: {curr_str}]:")
        val = val.strip()
        if not val:
            return
        try:
            num = int(val)
            self.limit_count = max(0, num)
            self.preview_cache.clear()
            self.dir_preview_cache.clear()
            self.preview_scroll_offset = 0
            self.refresh_data()
        except ValueError:
            console.print("[bold red]Invalid number. Limit unchanged.[/bold red]")
            get_key()

    def _get_preview_lines(self, row: Tuple, width: int) -> List[Text]:
        """Cached preview for a conversation, keyed on everything that changes its content."""
        key = (row[0], self.preview_view["tools"], self.preview_view["replies"], width)
        if key not in self.preview_cache:
            self.preview_cache[key] = build_conversation_preview_lines(
                row[0], row, max_width=width, view=self.preview_view
            )
        return self.preview_cache[key]

    def toggle_preview(self, key: str):
        """Flips the 'tools' / 'replies' preview switch, persists it, and re-renders from the top."""
        self.preview_view = toggle_preview_view(key)
        self.preview_scroll_offset = 0

    def _resume(self, cid: str) -> bool:
        """Resume a conversation. Returns True if the browser should exit.

        Default: copy the resume command, show it in the status line, and KEEP RUNNING (so you can
        grab more commands). With --launch: start agy directly, then exit (the old behavior).
        """
        cmd = build_resume_cmd(cid)
        if self.launch:
            console.print(f"\n[bold green]Resuming conversation [cyan]{cid}[/cyan]...[/bold green]\n")
            if sys.platform == "win32":
                subprocess.run(cmd, shell=True)
            else:
                os.execvp("agy", ["agy", "--conversation", cid])
            return True
        self.status_cmd = cmd
        self.status_copied = copy_to_clipboard(cmd)
        if cmd not in self.resume_log:
            self.resume_log.append(cmd)
        return False

    def _layout_budget(self, term_lines: int) -> Tuple[int, int]:
        """(main_h, out_h): rows for the browser (~75%) and for the resume-commands area (~25%).

        One row is always left free below the frame so the cursor never scrolls the screen. The browser
        never gets squeezed below what it needs (header + 5-row list + controls); on very short terminals
        the output area shrinks (below 3 rows it falls back to a one-line status).
        """
        usable = max(8, term_lines - 1)
        if not self.show_output_area:
            return usable, 0
        main_h = max(int(usable * 0.75), min(usable, 18))
        return main_h, usable - main_h

    def _render_status(self):
        """One-line fallback for terminals too short to fit the output area."""
        if not self.status_cmd:
            return
        line = Text("✔ Resume command" + (" (copied)" if self.status_copied else "") + ": ", style="bold green")
        line.append(self.status_cmd, style="bold cyan")
        console.print(line, soft_wrap=True)

    def _render_output_area(self, pad_rows: int, out_h: int):
        """Bottom ~25% of the screen: resume commands handed out so far, newest last.

        Plain unbordered lines on purpose: no box characters to catch in a mouse selection, and each
        command is one unbroken line (soft_wrap) so a drag-select copies it intact.
        """
        if out_h <= 0:
            return
        for _ in range(pad_rows):
            console.print()
        if out_h < 3:
            self._render_status()
            return

        if self.resume_log:
            note = "newest is on your clipboard" if self.status_copied else "clipboard unavailable - select & copy"
        else:
            note = "nothing yet"
        console.print(Rule(Text(f" Resume commands ({note}) ", style="bold green"), style="green"))

        body_rows = out_h - 1
        if not self.resume_log:
            key = "Enter or r" if self.default_action == "resume" else "r"
            console.print(Text(f"Press {key} on a conversation: its resume command is copied and listed here.", style="dim"))
            return

        cmds = self.resume_log
        hidden = 0
        if len(cmds) > body_rows:
            hidden = len(cmds) - (body_rows - 1)
            cmds = cmds[hidden:]
            console.print(Text(f"... {hidden} older (all reprinted when you quit)", style="dim"))
        for i, cmd in enumerate(cmds):
            newest = (i == len(cmds) - 1)
            console.print(Text(cmd, style="bold cyan" if newest else "white"), soft_wrap=True)

    def _print_resume_log(self):
        """On exit, reprint every resume command handed out (the screen is redrawn constantly)."""
        if not self.resume_log:
            return
        console.print("\n[bold green]Resume commands from this session:[/bold green]")
        for cmd in self.resume_log:
            sys.stdout.write(cmd + "\n")
        sys.stdout.flush()

    def _get_selected_cid(self) -> Optional[str]:
        if self.group_by_dir and self.tree_items:
            sel_item = self.tree_items[self.tree_cursor]
            if sel_item["type"] == "session":
                return sel_item["row"][0]
            elif sel_item["rows"]:
                return sel_item["rows"][0][0]
            return None
        if self.visible_indices:
            return self.rows[self.selected_idx][0]
        return None

    def render(self):
        os.system("cls" if os.name == "nt" else "clear")

        term_cols, term_lines = shutil.get_terminal_size((120, 30))

        header_text = Text()
        if self.default_action == "fork":
            header_text.append("Antigravity Session Forker (agy-fork)  |  ", style="bold cyan")
            header_text.append("Select Session to Branch\n", style="bold yellow")
        elif self.default_action == "tool":
            header_text.append("Antigravity Tool Surgery (--tool)  |  ", style="bold green")
            header_text.append("Select Session for Edit/Tool Cut\n", style="bold yellow")
        else:
            header_text.append("Antigravity Unified Session Suite (agy-chats)  |  ", style="bold cyan")
            mode_str = "All (incl. subagents)" if self.show_all else "Main Chats Only"
            header_text.append(f"Mode: {mode_str} ('a' to toggle)\n", style="bold yellow")

        header_text.append(f"Total: {len(self.rows)}  |  ", style="dim")
        header_text.append("Grouped Dirs: ", style="white")
        header_text.append("ON" if self.group_by_dir else "OFF", style="bold green" if self.group_by_dir else "dim")
        header_text.append(" ('g')  |  ", style="white")

        if self.limit_count > 0:
            header_text.append(f"Showing: Top {self.limit_count} ('#' to change)  |  ", style="bold yellow")
        else:
            header_text.append("Showing: All ('#' to limit)  |  ", style="dim")

        if self.filter_query:
            header_text.append(f"Filter: '{self.filter_query}' ({len(self.visible_indices)} matching)", style="bold magenta")
        else:
            header_text.append("Filter: None (press '/' to search)", style="dim")

        border_c = "green" if self.default_action == "tool" else "cyan"
        header_panel = Panel(header_text, border_style=border_c, box=box.ROUNDED)

        main_h, out_h = self._layout_budget(term_lines)

        if not self.visible_indices and not (self.group_by_dir and self.tree_items):
            empty_group = Group(
                header_panel,
                Panel(f"[bold red]No conversations matching '{escape(self.filter_query)}'.[/bold red]", border_style="red"),
                self._controls_text(),
            )
            used = len(console.render_lines(empty_group))
            console.print(empty_group)
            self._render_output_area(max(0, main_h - used), out_h)
            return

        # Height budget: the browser gets ~75% of the rows (main_h); the rest is the resume-commands area.
        # Measure the real header/controls heights (they wrap on narrow terminals), give everything else to the
        # list/preview panels, and derive how many conversations fit on a page from that.
        hdr_h = len(console.render_lines(header_panel))
        ctl_h = len(console.render_lines(self._controls_text()))
        grid_h = main_h - hdr_h - ctl_h
        if term_cols >= 85:
            avail_h = max(9, grid_h - 2)               # one row of panels: 2 border rows
        else:
            avail_h = max(7, (grid_h - 4) // 2)        # list + preview stacked: 2 borders each
        # list table = blank + header + rule + page rows + blank  ->  avail_h = page_size + 4
        self.page_size = max(3, avail_h - 4)
        avail_h = self.page_size + 4

        # -------------------------------------------------------------
        # 1. Left Table: Workspaces Tree vs Flat Conversations List
        # -------------------------------------------------------------
        list_table = Table(box=box.SIMPLE_HEAVY, expand=True, pad_edge=False, padding=(0, 1))

        if self.group_by_dir:
            total_tree = len(self.tree_items)
            total_pages = max(1, (total_tree + self.page_size - 1) // self.page_size) if total_tree else 1
            self.tree_cursor = max(0, min(self.tree_cursor, total_tree - 1)) if total_tree else 0
            curr_page = (self.tree_cursor // self.page_size) + 1 if total_tree else 1
            start_pos = (curr_page - 1) * self.page_size
            end_pos = min(total_tree, start_pos + self.page_size)

            list_table.add_column("", justify="center", width=2, no_wrap=True)
            list_table.add_column("Folder / ID", style="cyan", width=12, no_wrap=True)
            list_table.add_column("Workspace / Session Title", style="white", ratio=1, no_wrap=True, overflow="ellipsis")
            list_table.add_column("Active", justify="center", width=8, no_wrap=True)
            list_table.add_column("Steps", justify="right", width=5, no_wrap=True)

            for pos in range(start_pos, end_pos):
                item = self.tree_items[pos]
                is_selected = (pos == self.tree_cursor)
                row_style = "bold white on blue" if is_selected else "none"

                if item["type"] == "dir":
                    icon = "▼" if item["expanded"] else "▶"
                    fol_badge = f"{icon} 📂 {item['dir_key'][:10]}"
                    title_badge = f"{item['count']} sessions  [dim]({item['dir_path'][:25]})[/dim]"
                    steps_sum = str(sum(r[3] for r in item["rows"] if len(r) > 3 and r[3]))
                    list_table.add_row(
                        icon,
                        fol_badge,
                        title_badge,
                        "",
                        steps_sum,
                        style="bold yellow on blue" if is_selected else "bold yellow"
                    )
                else:
                    r = item["row"]
                    cid = r[0]
                    title = (r[1] or "").strip() or (r[2] or "").strip().splitlines()[0][:30] if r[2] else "(Untitled)"
                    dt = parse_time(r[4])
                    rel_time = format_relative(dt)
                    dot = "[magenta]▲[/magenta]" if r[6] else "[green]●[/green]"
                    id_str = f" >{cid[:6]}" if is_selected else f"  {cid[:6]}"
                    list_table.add_row(
                        dot,
                        id_str,
                        escape(f"  {title}"),
                        rel_time[:8],
                        str(r[3]),
                        style=row_style
                    )

            # Pad empty rows to maintain fixed height
            for _ in range(self.page_size - (end_pos - start_pos)):
                list_table.add_row("", "", "", "", "")

            left_title = f"Workspaces [Page {curr_page}/{total_pages} • {total_tree} items]"
        else:
            if not self.visible_indices:
                total_items = 0
                total_pages = 1
                curr_page = 1
                start_pos = 0
                end_pos = 0
            else:
                total_items = len(self.visible_indices)
                total_pages = max(1, (total_items + self.page_size - 1) // self.page_size)
                if self.selected_idx not in self.visible_indices:
                    self.selected_idx = self.visible_indices[0]
                curr_pos = self.visible_indices.index(self.selected_idx)
                curr_page = (curr_pos // self.page_size) + 1
                start_pos = (curr_page - 1) * self.page_size
                end_pos = min(total_items, start_pos + self.page_size)

            list_table.add_column("", justify="center", width=2, no_wrap=True)
            list_table.add_column("ID", style="cyan", width=8, no_wrap=True)
            list_table.add_column("Title", style="white", ratio=1, no_wrap=True, overflow="ellipsis")
            list_table.add_column("Active", justify="center", width=8, no_wrap=True)
            list_table.add_column("Steps", justify="right", width=5, no_wrap=True)
            list_table.add_column("Dir", style="green", width=8, no_wrap=True, overflow="ellipsis")

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
                    if agent_name: eff_title = f"[{agent_name}]"
                    elif prev: eff_title = prev.strip().splitlines()[0][:35]
                    else: eff_title = "(Untitled Session)"

                dot = "[magenta]▲[/magenta]" if agent_name else "[green]●[/green]"
                id_str = f">{cid[:7]}" if is_selected else f" {cid[:7]}"
                row_style = "bold white on blue" if is_selected else "none"

                list_table.add_row(
                    dot,
                    id_str,
                    escape(eff_title),
                    rel_time[:8],
                    str(step_count),
                    escape(ws_label[:8]),
                    style=row_style
                )

            # Pad empty rows to maintain fixed height
            for _ in range(self.page_size - (end_pos - start_pos)):
                list_table.add_row("", "", "", "", "", "")

            left_title = f"Conversations [Page {curr_page}/{total_pages} • {total_items} total]"

        if self.active_focus == "list":
            left_border = "yellow"
            p_left_title = Text(f"[LIST ACTIVE] {left_title}", style="bold yellow")
            p_left_sub = Text("▲/▼ Select  |  ◀/▶ Page  |  j/k Scroll  |  Tab Focus", style="dim cyan")
        else:
            left_border = "cyan"
            p_left_title = Text(left_title, style="bold cyan")
            p_left_sub = Text("◀/▶ Switch Session  |  Tab Focus List", style="dim")

        left_panel = Panel(list_table, title=p_left_title, subtitle=p_left_sub, border_style=left_border, box=box.ROUNDED)

        # -------------------------------------------------------------
        # 2. Right Pane: Scrollable Live Preview (Pre-wrapped to fit viewport)
        # -------------------------------------------------------------
        preview_w = max(38, (term_cols * 5 // 12) - 4)

        if self.group_by_dir and self.tree_items:
            sel_item = self.tree_items[self.tree_cursor]
            if sel_item["type"] == "dir":
                d_key = sel_item["dir_key"]
                if d_key not in self.dir_preview_cache:
                    self.dir_preview_cache[d_key] = build_directory_preview_lines(
                        d_key, sel_item["dir_path"], sel_item["rows"], max_width=preview_w
                    )
                all_preview_lines = self.dir_preview_cache[d_key]
            else:
                sel_row = sel_item["row"]
                all_preview_lines = self._get_preview_lines(sel_row, preview_w)
        else:
            if self.visible_indices:
                sel_row = self.rows[self.selected_idx]
                all_preview_lines = self._get_preview_lines(sel_row, preview_w)
            else:
                all_preview_lines = [Text("No conversation selected.", style="dim")]

        max_offset = max(0, len(all_preview_lines) - avail_h)
        self.preview_scroll_offset = max(0, min(self.preview_scroll_offset, max_offset))

        visible_preview = all_preview_lines[self.preview_scroll_offset : self.preview_scroll_offset + avail_h]

        preview_content = Text()
        for idx, line in enumerate(visible_preview):
            if idx > 0:
                preview_content.append("\n")
            preview_content.append_text(line)

        # Pad preview_content to avail_h lines if fewer lines exist, maintaining fixed height
        if len(visible_preview) < avail_h:
            pad_needed = avail_h - len(visible_preview)
            for _ in range(pad_needed):
                preview_content.append("\n")

        # Scroll Indicators in Preview Panel
        p_title = Text()
        if self.active_focus == "preview":
            p_title.append("[PREVIEW ACTIVE] ", style="bold green")
        else:
            p_title.append("Preview ", style="bold")

        for key_hint, label, flag in (("1", "Tools", "tools"), ("2", "Replies", "replies")):
            on = self.preview_view.get(flag, False)
            p_title.append(f" [{key_hint}]{label} ", style="bold green" if on else "dim")
            p_title.append("☑" if on else "☐", style="bold green" if on else "dim")

        p_sub = Text()
        remaining_lines = max(0, len(all_preview_lines) - (self.preview_scroll_offset + avail_h))
        if self.preview_scroll_offset > 0:
            p_sub.append(f"▲ {self.preview_scroll_offset} above  ", style="bold yellow")
        if remaining_lines > 0:
            p_sub.append(f"▼ {remaining_lines} below (j/k to scroll)", style="bold yellow")
        else:
            p_sub.append("(End of Preview)", style="dim")

        right_border = "green" if self.active_focus == "preview" else "dim green"
        right_panel = Panel(preview_content, title=p_title, subtitle=p_sub, border_style=right_border, box=box.ROUNDED)

        # Side-by-Side Split Screen Layout
        if term_cols >= 85:
            grid = Table.grid(expand=True)
            grid.add_column("left", ratio=7, min_width=50)
            grid.add_column("right", ratio=5, min_width=38)
            grid.add_row(left_panel, right_panel)
            body = grid
        else:
            body = Group(left_panel, right_panel)

        main_group = Group(header_panel, body, self._controls_text())
        used = len(console.render_lines(main_group))
        console.print(main_group)
        if used > main_h:
            # The browser needs more than its 75% share (short/narrow terminal): give the output area only
            # what's genuinely left, or - if there isn't room for a rule + a line - the one-line status.
            remaining = max(8, term_lines - 1) - used
            out_h = min(out_h, remaining) if remaining >= 3 else 2
        # Anchor the resume-commands area to the bottom ~25%
        self._render_output_area(max(0, main_h - used), out_h)

    def _controls_text(self) -> Text:
        ctrls = Text()
        if self.active_focus == "preview":
            ctrls.append(" [PREVIEW] ", style="bold black on green")
            ctrls.append(" [▲/▼ or j/k] Scroll  |  ", style="bold green")
            ctrls.append("[◀/▶] Switch Session  |  ", style="bold cyan")
            ctrls.append("[Tab] Focus List  |  ", style="yellow")
        else:
            ctrls.append(" [LIST] ", style="bold black on yellow")
            ctrls.append(" [▲/▼] Select  |  ", style="bold yellow")
            ctrls.append("[◀/▶] Page  |  ", style="bold cyan")
            if self.group_by_dir:
                ctrls.append("[Space/Enter] Expand/Collapse  |  ", style="bold cyan")
            ctrls.append("[j/k] Scroll  |  ", style="dim green")
            ctrls.append("[Tab] Focus Preview  |  ", style="green")

        ctrls.append("[1] Tools  [2] Replies  |  ", style="bold green")
        ctrls.append("[g] Group  |  ", style="bold magenta")
        ctrls.append("[#] Limit  |  ", style="bold yellow")
        ctrls.append("[Enter] Copy Resume Cmd  |  ", style="bold green")
        ctrls.append("[f] Fork  |  ", style="cyan")
        ctrls.append("[t] Trans  |  ", style="dim")
        ctrls.append("[/] Search  |  ", style="dim")
        ctrls.append("[q] Quit", style="bold red")
        return ctrls

    def render_controls(self):
        console.print(self._controls_text())

    def interactive_move(self):
        cid = self._get_selected_cid()
        if not cid: return
        run_move_flow(cid, self.rows)
        self.refresh_data()

    def run(self):
        try:
            self._loop()
        finally:
            self._print_resume_log()

    def _loop(self):
        while True:
            self.render()
            k = get_key()

            # Global toggles
            if k == "1":
                self.toggle_preview("tools")
                continue
            elif k == "2":
                self.toggle_preview("replies")
                continue
            elif k in ("g", "G"):
                self.group_by_dir = not self.group_by_dir
                self.rebuild_tree()
                self.preview_scroll_offset = 0
                continue
            elif k in ("#", "N"):
                self.set_custom_limit()
                continue
            elif k in ("TAB",):
                self.active_focus = "list" if self.active_focus == "preview" else "preview"
                continue
            elif k in ("e", "E") and self.group_by_dir:
                for item in self.tree_items:
                    if item["type"] == "dir":
                        self.expanded_dirs.add(item["dir_key"])
                self.rebuild_tree()
                continue
            elif k in ("c", "C") and self.group_by_dir:
                self.expanded_dirs.clear()
                self.rebuild_tree()
                continue

            # Direct preview scrolling with J / K anytime
            if k == "J":
                self.preview_scroll_offset += 4
                continue
            elif k == "K":
                self.preview_scroll_offset = max(0, self.preview_scroll_offset - 4)
                continue

            # -------------------------------------------------------------
            # PREVIEW FOCUS: Arrow keys scroll preview, Left/Right switch item
            # -------------------------------------------------------------
            if self.active_focus == "preview":
                if k in ("UP", "k"):
                    self.preview_scroll_offset = max(0, self.preview_scroll_offset - 2)
                    continue
                elif k in ("DOWN", "j"):
                    self.preview_scroll_offset += 2
                    continue
                elif k == "PAGE_UP":
                    self.preview_scroll_offset = max(0, self.preview_scroll_offset - 8)
                    continue
                elif k == "PAGE_DOWN":
                    self.preview_scroll_offset += 8
                    continue
                elif k == "HOME":
                    self.preview_scroll_offset = 0
                    continue
                elif k == "END":
                    self.preview_scroll_offset = 999999
                    continue
                elif k in ("LEFT", "["):
                    if self.group_by_dir:
                        if self.tree_cursor > 0:
                            self.tree_cursor -= 1
                            self.preview_scroll_offset = 0
                    else:
                        if self.visible_indices:
                            curr_pos = self.visible_indices.index(self.selected_idx) if self.selected_idx in self.visible_indices else 0
                            if curr_pos > 0:
                                self.selected_idx = self.visible_indices[curr_pos - 1]
                                self.preview_scroll_offset = 0
                    continue
                elif k in ("RIGHT", "]"):
                    if self.group_by_dir:
                        if self.tree_cursor < len(self.tree_items) - 1:
                            self.tree_cursor += 1
                            self.preview_scroll_offset = 0
                    else:
                        if self.visible_indices:
                            curr_pos = self.visible_indices.index(self.selected_idx) if self.selected_idx in self.visible_indices else 0
                            if curr_pos < len(self.visible_indices) - 1:
                                self.selected_idx = self.visible_indices[curr_pos + 1]
                                self.preview_scroll_offset = 0
                    continue
                elif k == " ":
                    if self.group_by_dir and self.tree_items:
                        sel_item = self.tree_items[self.tree_cursor]
                        if sel_item["type"] == "dir":
                            d_key = sel_item["dir_key"]
                            if d_key in self.expanded_dirs:
                                self.expanded_dirs.remove(d_key)
                            else:
                                self.expanded_dirs.add(d_key)
                            self.rebuild_tree()
                            self.preview_scroll_offset = 0
                            continue

            # -------------------------------------------------------------
            # LIST FOCUS: Up/Down arrow moves selection, Left/Right pages
            # -------------------------------------------------------------
            if self.active_focus == "list":
                if k == "UP":
                    if self.group_by_dir:
                        if self.tree_cursor > 0:
                            self.tree_cursor -= 1
                            self.preview_scroll_offset = 0
                    else:
                        if self.visible_indices:
                            curr_pos = self.visible_indices.index(self.selected_idx) if self.selected_idx in self.visible_indices else 0
                            if curr_pos > 0:
                                self.selected_idx = self.visible_indices[curr_pos - 1]
                                self.preview_scroll_offset = 0
                    continue
                elif k == "DOWN":
                    if self.group_by_dir:
                        if self.tree_cursor < len(self.tree_items) - 1:
                            self.tree_cursor += 1
                            self.preview_scroll_offset = 0
                    else:
                        if self.visible_indices:
                            curr_pos = self.visible_indices.index(self.selected_idx) if self.selected_idx in self.visible_indices else 0
                            if curr_pos < len(self.visible_indices) - 1:
                                self.selected_idx = self.visible_indices[curr_pos + 1]
                                self.preview_scroll_offset = 0
                    continue
                # Direct preview scrolling in list mode via j / k
                elif k == "j":
                    self.preview_scroll_offset += 2
                    continue
                elif k == "k":
                    self.preview_scroll_offset = max(0, self.preview_scroll_offset - 2)
                    continue
                # Page back
                elif k in ("LEFT", "PAGE_UP", "["):
                    if self.group_by_dir:
                        self.tree_cursor = max(0, self.tree_cursor - self.page_size)
                        self.preview_scroll_offset = 0
                    else:
                        if self.visible_indices:
                            curr_pos = self.visible_indices.index(self.selected_idx) if self.selected_idx in self.visible_indices else 0
                            new_pos = max(0, curr_pos - self.page_size)
                            self.selected_idx = self.visible_indices[new_pos]
                            self.preview_scroll_offset = 0
                    continue
                # Page forward
                elif k in ("RIGHT", "PAGE_DOWN", "]"):
                    if self.group_by_dir:
                        self.tree_cursor = min(max(0, len(self.tree_items) - 1), self.tree_cursor + self.page_size)
                        self.preview_scroll_offset = 0
                    else:
                        if self.visible_indices:
                            curr_pos = self.visible_indices.index(self.selected_idx) if self.selected_idx in self.visible_indices else 0
                            new_pos = min(len(self.visible_indices) - 1, curr_pos + self.page_size)
                            self.selected_idx = self.visible_indices[new_pos]
                            self.preview_scroll_offset = 0
                    continue
                elif k == "HOME":
                    if self.group_by_dir:
                        self.tree_cursor = 0
                    else:
                        if self.visible_indices:
                            self.selected_idx = self.visible_indices[0]
                    self.preview_scroll_offset = 0
                    continue
                elif k == "END":
                    if self.group_by_dir:
                        self.tree_cursor = max(0, len(self.tree_items) - 1)
                    else:
                        if self.visible_indices:
                            self.selected_idx = self.visible_indices[-1]
                    self.preview_scroll_offset = 0
                    continue
                elif k == " ":
                    if self.group_by_dir and self.tree_items:
                        sel_item = self.tree_items[self.tree_cursor]
                        if sel_item["type"] == "dir":
                            d_key = sel_item["dir_key"]
                            if d_key in self.expanded_dirs:
                                self.expanded_dirs.remove(d_key)
                            else:
                                self.expanded_dirs.add(d_key)
                            self.rebuild_tree()
                            self.preview_scroll_offset = 0
                            continue

            # Global actions
            if k in ("/",):
                q = prompt_input("Search (title, UUID, workspace):")
                self.update_filter(q)
                self.preview_scroll_offset = 0
            elif k in ("a", "A"):
                self.show_all = not self.show_all
                self.refresh_data()
                self.preview_scroll_offset = 0
            elif k in ("m", "M"):
                self.interactive_move()
            elif k in ("f", "F"):
                cid = self._get_selected_cid()
                if cid:
                    forker = TurnExplorerTUI(cid)
                    res = forker.run()
                    if res:
                        show_success_screen(res)
                        return
            elif k in ("T",) or (self.default_action == "tool" and k in ("ENTER",)):
                cid = self._get_selected_cid()
                if cid:
                    cutter = ToolCutterTUI(cid, turn_index=self.target_turn)
                    res = cutter.run()
                    if res:
                        show_success_screen(res)
                        return
            elif k in ("t",):
                cid = self._get_selected_cid()
                if cid:
                    show_transcript_pager(cid)
            elif k in ("y", "Y"):
                cid = self._get_selected_cid()
                if cid:
                    copy_to_clipboard(cid)
                    console.print("\n[bold green]Copied UUID to clipboard![/bold green]")
                    get_key()
            elif k in ("r", "R"):
                cid = self._get_selected_cid()
                if cid and self._resume(cid):
                    return
            elif k in ("ENTER",):
                if self.group_by_dir and self.tree_items:
                    sel_item = self.tree_items[self.tree_cursor]
                    if sel_item["type"] == "dir":
                        d_key = sel_item["dir_key"]
                        if d_key in self.expanded_dirs:
                            self.expanded_dirs.remove(d_key)
                        else:
                            self.expanded_dirs.add(d_key)
                        self.rebuild_tree()
                        self.preview_scroll_offset = 0
                        continue

                cid = self._get_selected_cid()
                if cid:
                    if self.default_action == "fork":
                        forker = TurnExplorerTUI(cid)
                        res = forker.run()
                        if res:
                            show_success_screen(res)
                            return
                    elif self.default_action == "tool":
                        cutter = ToolCutterTUI(cid, turn_index=self.target_turn)
                        res = cutter.run()
                        if res:
                            show_success_screen(res)
                            return
                    else:
                        if self._resume(cid):
                            return
            elif k == "ESC":
                if self.filter_query:
                    self.update_filter("")
                    self.preview_scroll_offset = 0
                else:
                    return
            elif k in ("q", "Q"):
                return


def run_conversation_picker(prompt_title: str = "Select Conversation") -> Optional[str]:
    """Helper to pick a conversation ID interactively."""
    tui = MainChatsTUI(show_all=False)
    if not tui.rows:
        tui = MainChatsTUI(show_all=True)
    if not tui.rows:
        return None
    tui.show_output_area = False  # picker returns the chosen id; no resume-commands area needed

    while True:
        tui.render()
        k = get_key()
        if k == "1":
            tui.toggle_preview("tools")
        elif k == "2":
            tui.toggle_preview("replies")
        elif k in ("UP", "k"):
            if tui.visible_indices:
                curr_pos = tui.visible_indices.index(tui.selected_idx)
                if curr_pos > 0:
                    tui.selected_idx = tui.visible_indices[curr_pos - 1]
        elif k in ("DOWN", "j"):
            if tui.visible_indices:
                curr_pos = tui.visible_indices.index(tui.selected_idx)
                if curr_pos < len(tui.visible_indices) - 1:
                    tui.selected_idx = tui.visible_indices[curr_pos + 1]
        elif k in ("/",):
            q = prompt_input("Search:")
            tui.update_filter(q)
        elif k == "ENTER":
            if tui.visible_indices:
                return tui.rows[tui.selected_idx][0]
            return None
        elif k in ("ESC", "q", "Q"):
            return None

