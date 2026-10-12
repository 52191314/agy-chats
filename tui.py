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
from typing import List, Dict, Optional, Tuple, Any

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
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
    DEFAULT_CONV_DIR,
    DEFAULT_BRAIN_DIR,
    DEFAULT_SUMMARIES_DB
)

console = Console()


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

def build_conversation_preview_lines(cid: str, row_data: Tuple, max_width: int = 65) -> List[Text]:
    """Builds formatted lines for the right-hand scrollable preview pane."""
    lines: List[Text] = []
    cid, title, prev, step_count, last_mod, ws_uris, agent_name, depth, parent_id = row_data

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
    lines.append(Text(""))

    # 3. Turns & Content
    if turns:
        # Initial user request
        lines.append(Text("▶ INITIAL USER REQUEST:", style="bold yellow"))
        init_lines = turns[0]["user_text"].strip().splitlines()
        for l in init_lines:
            t = Text("  │ ", style="dim")
            t.append(l, style="white")
            lines.append(t)
        lines.append(Text(""))

        # Assistant response for Turn 1
        if turns[0].get("assistant_text"):
            lines.append(Text("▶ ASSISTANT RESPONSE:", style="bold green"))
            for l in turns[0]["assistant_text"].strip().splitlines():
                t = Text("  │ ", style="dim")
                t.append(l, style="dim white")
                lines.append(t)
            lines.append(Text(""))

        if turns[0].get("tools"):
            t_tools = Text("  ▶ Tools Executed (", style="bold cyan")
            t_tools.append(f"{len(turns[0]['tools'])} tools): ", style="bold cyan")
            tool_badges = [tl.get("short_label", tl["tool_name"]) for tl in turns[0]["tools"][:3]]
            t_tools.append(", ".join(tool_badges), style="yellow")
            if len(turns[0]["tools"]) > 3:
                t_tools.append(f" +{len(turns[0]['tools']) - 3} more", style="dim")
            lines.append(t_tools)
            lines.append(Text(""))

        # Subsequent turns
        for turn in turns[1:]:
            lines.append(Text(f"▶ USER TURN #{turn['turn_index']}:", style="bold yellow"))
            for l in turn["user_text"].strip().splitlines():
                t = Text("  │ ", style="dim")
                t.append(l, style="white")
                lines.append(t)
            lines.append(Text(""))

            if turn.get("assistant_text"):
                lines.append(Text(f"▶ ASSISTANT (Turn #{turn['turn_index']}):", style="bold green"))
                for l in turn["assistant_text"].strip().splitlines():
                    t = Text("  │ ", style="dim")
                    t.append(l, style="dim white")
                    lines.append(t)
                lines.append(Text(""))

            if turn.get("tools"):
                t_tools = Text("  ▶ Tools (", style="bold cyan")
                t_tools.append(f"{len(turn['tools'])} tools): ", style="bold cyan")
                tool_badges = [tl.get("short_label", tl["tool_name"]) for tl in turn["tools"][:3]]
                t_tools.append(", ".join(tool_badges), style="yellow")
                if len(turn["tools"]) > 3:
                    t_tools.append(f" +{len(turn['tools']) - 3} more", style="dim")
                lines.append(t_tools)
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

    return lines


# ==============================================================================
# MainChatsTUI: Master Conversation Explorer, Forker & Workspace Manager
# ==============================================================================

class MainChatsTUI:
    def __init__(
        self,
        show_all: bool = False,
        initial_query: str = "",
        default_action: str = "resume",
        target_turn: Optional[int] = None
    ):
        self.show_all = show_all
        self.filter_query = initial_query.strip()
        self.default_action = default_action
        self.target_turn = target_turn
        self.rows = []
        self.visible_indices = []
        self.selected_idx = 0
        self.page_size = 14
        self.preview_scroll_offset = 0
        self.preview_cache = {}
        self.scroll_mode = False
        self.refresh_data()

    def refresh_data(self):
        if not os.path.exists(DEFAULT_SUMMARIES_DB):
            self.rows = []
            self.visible_indices = []
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
        self.rows = cur.fetchall()
        conn.close()
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
            mode_str = "All Sessions (incl. subagents)" if self.show_all else "Main Chats Only"
            header_text.append(f"Mode: {mode_str} ('a' to toggle)\n", style="bold yellow")

        header_text.append(f"Total Sessions: {len(self.rows)}  |  ", style="dim")
        if self.filter_query:
            header_text.append(f"Filter: '{self.filter_query}' ({len(self.visible_indices)} matching)", style="bold magenta")
        else:
            header_text.append("Filter: None (press '/' to search)", style="dim")

        border_c = "green" if self.default_action == "tool" else "cyan"
        console.print(Panel(header_text, border_style=border_c, box=box.ROUNDED))

        if not self.visible_indices:
            console.print(Panel(f"[bold red]No conversations matching '{escape(self.filter_query)}'.[/bold red]", border_style="red"))
            self.render_controls()
            return

        if self.selected_idx not in self.visible_indices:
            self.selected_idx = self.visible_indices[0]

        curr_pos = self.visible_indices.index(self.selected_idx)
        self.page_size = max(6, min(14, term_lines - 12))
        start_pos = max(0, curr_pos - self.page_size // 2)
        end_pos = min(len(self.visible_indices), start_pos + self.page_size)
        if end_pos - start_pos < self.page_size:
            start_pos = max(0, end_pos - self.page_size)

        # 1. Left Table: Conversations List
        list_table = Table(box=box.SIMPLE_HEAVY, expand=True)
        list_table.add_column("", justify="center", width=2)
        list_table.add_column("ID", style="cyan", width=8)
        list_table.add_column("Title", style="white", ratio=1)
        list_table.add_column("Active", justify="center", width=8)
        list_table.add_column("Steps", justify="right", width=6)
        list_table.add_column("Dir", style="green", width=9)

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
            id_str = f">{cid[:7]}" if is_selected else cid[:8]
            row_style = "bold white on blue" if is_selected else "none"

            list_table.add_row(
                dot,
                id_str,
                escape(eff_title[:32]),
                rel_time[:8],
                str(step_count),
                escape(ws_label[:9]),
                style=row_style
            )

        left_panel = Panel(list_table, title=f"Conversations ({len(self.visible_indices)})", border_style="cyan", box=box.ROUNDED)

        # 2. Right Pane: Scrollable Live Preview
        sel_row = self.rows[self.selected_idx]
        sel_cid = sel_row[0]
        preview_w = max(40, (term_cols // 2) - 4)

        if sel_cid not in self.preview_cache:
            self.preview_cache[sel_cid] = build_conversation_preview_lines(sel_cid, sel_row, max_width=preview_w)
        all_preview_lines = self.preview_cache[sel_cid]

        avail_h = max(6, term_lines - 12)
        max_offset = max(0, len(all_preview_lines) - avail_h)
        self.preview_scroll_offset = max(0, min(self.preview_scroll_offset, max_offset))

        visible_preview = all_preview_lines[self.preview_scroll_offset : self.preview_scroll_offset + avail_h]

        preview_content = Text()
        for idx, line in enumerate(visible_preview):
            if idx > 0:
                preview_content.append("\n")
            preview_content.append_text(line)

        # Scroll Indicators in Preview Panel (Use Text objects to avoid Rich markup tag errors)
        p_title = Text()
        p_title.append("Preview", style="bold")
        if self.preview_scroll_offset > 0:
            p_title.append(f" (▲ {self.preview_scroll_offset} lines above - K/[ to scroll)", style="bold yellow")
        else:
            p_title.append(" Details", style="dim")

        p_sub = Text()
        remaining_lines = max(0, len(all_preview_lines) - (self.preview_scroll_offset + avail_h))
        if remaining_lines > 0:
            p_sub.append(f"▼ {remaining_lines} lines below (use J/K or [/] to scroll)", style="bold yellow")
        else:
            p_sub.append("(End of Preview)", style="dim")

        right_panel = Panel(preview_content, title=p_title, subtitle=p_sub, border_style="green", box=box.ROUNDED)

        # Side-by-Side Split Screen Layout
        if term_cols >= 85:
            grid = Table.grid(expand=True)
            grid.add_column("left", ratio=5, min_width=42)
            grid.add_column("right", ratio=5, min_width=42)
            grid.add_row(left_panel, right_panel)
            console.print(grid)
        else:
            console.print(left_panel)
            console.print(right_panel)

        self.render_controls()

    def render_controls(self):
        ctrls = Text()
        if self.scroll_mode:
            ctrls.append(" [SCROLL MODE] ", style="bold black on yellow")
            ctrls.append(" [Up/Down or k/j] Scroll Preview  |  [p] Switch to List  |  [q/Esc] Exit", style="bold cyan")
        else:
            ctrls.append(" [Up/Down] Select  |  ", style="bold cyan")
            ctrls.append("[J/K or [/]] Scroll Preview  |  ", style="bold yellow")
            if self.default_action == "fork":
                ctrls.append("[Enter] Fork Turns  |  ", style="bold green")
                ctrls.append("[T] Tool Cutter  |  ", style="bold yellow")
                ctrls.append("[r] Resume  |  ", style="cyan")
            elif self.default_action == "tool":
                ctrls.append("[Enter] Tool Cutter  |  ", style="bold green")
                ctrls.append("[f] Fork Turns  |  ", style="bold yellow")
                ctrls.append("[r] Resume  |  ", style="cyan")
            else:
                ctrls.append("[Enter] Resume  |  ", style="bold green")
                ctrls.append("[f] Fork  |  ", style="bold yellow")

            ctrls.append("[m] Move  |  ", style="bold magenta")
            ctrls.append("[t] Transcript  |  ", style="bold white")
            ctrls.append("[p] Scroll  |  ", style="dim")
            ctrls.append("[y] Copy  |  ", style="dim")
            ctrls.append("[a] Toggle  |  ", style="dim")
            ctrls.append("[/] Search  |  ", style="dim")
            ctrls.append("[q/Esc] Quit", style="bold red")
        console.print(ctrls)

    def interactive_move(self):
        if not self.visible_indices: return
        sel_row = self.rows[self.selected_idx]
        cid = sel_row[0]
        title = sel_row[1] or cid[:8]
        curr_ws = format_workspace_path(sel_row[5])

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
                if not target_ws: return
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

            # Preview scroll keys
            if k in ("]", "J"):
                self.preview_scroll_offset += 3
                continue
            elif k in ("[", "K"):
                self.preview_scroll_offset = max(0, self.preview_scroll_offset - 3)
                continue
            elif k in ("p", "P"):
                self.scroll_mode = not self.scroll_mode
                continue

            # Navigation in scroll mode vs list mode
            if self.scroll_mode:
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
                elif k in ("ESC", "q"):
                    self.scroll_mode = False
                    continue

            # Standard list navigation
            if k in ("UP", "k"):
                if self.visible_indices:
                    curr_pos = self.visible_indices.index(self.selected_idx)
                    if curr_pos > 0:
                        self.selected_idx = self.visible_indices[curr_pos - 1]
                        self.preview_scroll_offset = 0
            elif k in ("DOWN", "j"):
                if self.visible_indices:
                    curr_pos = self.visible_indices.index(self.selected_idx)
                    if curr_pos < len(self.visible_indices) - 1:
                        self.selected_idx = self.visible_indices[curr_pos + 1]
                        self.preview_scroll_offset = 0
            elif k == "PAGE_UP":
                if self.visible_indices:
                    curr_pos = self.visible_indices.index(self.selected_idx)
                    self.selected_idx = self.visible_indices[max(0, curr_pos - self.page_size)]
                    self.preview_scroll_offset = 0
            elif k == "PAGE_DOWN":
                if self.visible_indices:
                    curr_pos = self.visible_indices.index(self.selected_idx)
                    self.selected_idx = self.visible_indices[min(len(self.visible_indices) - 1, curr_pos + self.page_size)]
                    self.preview_scroll_offset = 0
            elif k == "HOME":
                if self.visible_indices:
                    self.selected_idx = self.visible_indices[0]
                    self.preview_scroll_offset = 0
            elif k == "END":
                if self.visible_indices:
                    self.selected_idx = self.visible_indices[-1]
                    self.preview_scroll_offset = 0
            elif k in ("/",):
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
                if self.visible_indices:
                    cid = self.rows[self.selected_idx][0]
                    forker = TurnExplorerTUI(cid)
                    res = forker.run()
                    if res:
                        show_success_screen(res)
                        return
            elif k in ("T",) or (self.default_action == "tool" and k in ("ENTER",)):
                if self.visible_indices:
                    cid = self.rows[self.selected_idx][0]
                    cutter = ToolCutterTUI(cid, turn_index=self.target_turn)
                    res = cutter.run()
                    if res:
                        show_success_screen(res)
                        return
            elif k in ("t",):
                if self.visible_indices:
                    cid = self.rows[self.selected_idx][0]
                    show_transcript_pager(cid)
            elif k in ("y", "Y"):
                if self.visible_indices:
                    cid = self.rows[self.selected_idx][0]
                    copy_to_clipboard(cid)
                    console.print("\n[bold green]Copied UUID to clipboard![/bold green]")
                    get_key()
            elif k in ("r", "R"):
                if self.visible_indices:
                    cid = self.rows[self.selected_idx][0]
                    console.print(f"\n[bold green]Resuming conversation [cyan]{cid}[/cyan]...[/bold green]\n")
                    if sys.platform == "win32":
                        subprocess.run(f"agy --conversation {cid}", shell=True)
                    else:
                        os.execvp("agy", ["agy", "--conversation", cid])
                    return
            elif k in ("ENTER",):
                if self.visible_indices:
                    cid = self.rows[self.selected_idx][0]
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
                        console.print(f"\n[bold green]Resuming conversation [cyan]{cid}[/cyan]...[/bold green]\n")
                        if sys.platform == "win32":
                            subprocess.run(f"agy --conversation {cid}", shell=True)
                        else:
                            os.execvp("agy", ["agy", "--conversation", cid])
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

    while True:
        tui.render()
        k = get_key()
        if k in ("UP", "k"):
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

