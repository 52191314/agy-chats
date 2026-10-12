#!/usr/bin/env python3
"""
agy-chats: Unified Antigravity Session Suite (TUI, Fuzzy Browser, Turn Forker, Tool Surgery, Workspace Relocation).

Combines agy-chats and agy-fork into a single, cohesive command-line and interactive terminal application.
Cross-platform: Windows, macOS, Linux.
"""

import sys
import os

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import sqlite3
import re
import argparse
import subprocess
from typing import Optional, List, Dict, Any

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markup import escape
from rich import box

from session_engine import (
    SessionReader,
    fork_session,
    move_conversation_workspace,
    list_workspaces,
    format_workspace_path,
    get_workspace_label,
    copy_to_clipboard,
    DEFAULT_SUMMARIES_DB,
    DEFAULT_BRAIN_DIR,
    DEFAULT_CONV_DIR
)
from tui import (
    MainChatsTUI,
    TurnExplorerTUI,
    ToolCutterTUI,
    show_success_screen,
    show_transcript_pager,
    run_conversation_picker
)

console = Console()


# ==============================================================================
# Helper Functions
# ==============================================================================

def resolve_conversation(query: Optional[str]) -> Optional[str]:
    """Resolves a conversation query or partial UUID/title to a full UUID."""
    if not os.path.exists(DEFAULT_SUMMARIES_DB):
        return query

    if not query:
        # Default to latest conversation
        conn = sqlite3.connect(DEFAULT_SUMMARIES_DB)
        cur = conn.cursor()
        cur.execute("SELECT conversation_id FROM conversation_summaries WHERE step_count > 0 ORDER BY last_modified_time DESC LIMIT 1")
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None

    q = query.strip()
    conn = sqlite3.connect(DEFAULT_SUMMARIES_DB)
    cur = conn.cursor()

    # Exact or prefix match on conversation_id
    cur.execute(
        "SELECT conversation_id FROM conversation_summaries WHERE conversation_id = ? OR conversation_id LIKE ? LIMIT 5",
        (q, f"{q}%")
    )
    matches = cur.fetchall()
    if len(matches) == 1:
        conn.close()
        return matches[0][0]

    # Match by title
    cur.execute(
        "SELECT conversation_id FROM conversation_summaries WHERE title = ? OR title LIKE ? LIMIT 5",
        (q, f"{q}%")
    )
    title_matches = cur.fetchall()
    conn.close()

    if len(title_matches) == 1:
        return title_matches[0][0]
    elif len(matches) > 1:
        return matches[0][0]
    elif len(title_matches) > 1:
        return title_matches[0][0]

    # Return raw query if no DB match (could be custom path)
    return q


def resume_conversation(cid: str):
    """Resumes an Antigravity conversation."""
    console.print(f"\n[bold green]Resuming conversation [cyan]{cid}[/cyan]...[/bold green]\n")
    if sys.platform == "win32":
        subprocess.run(f"agy --conversation {cid}", shell=True)
    else:
        os.execvp("agy", ["agy", "--conversation", cid])


def resume_latest():
    """Immediately resumes the most recent conversation."""
    cid = resolve_conversation(None)
    if not cid:
        console.print("[bold red]No conversations found to resume.[/bold red]")
        sys.exit(1)
    resume_conversation(cid)


def list_table(show_all: bool = False):
    """Prints a non-interactive tabular summary of conversations."""
    if not os.path.exists(DEFAULT_SUMMARIES_DB):
        console.print("[bold yellow]No conversation summaries database found.[/bold yellow]")
        return

    conn = sqlite3.connect(DEFAULT_SUMMARIES_DB)
    cur = conn.cursor()
    if show_all:
        cur.execute("""
            SELECT conversation_id, title, preview, step_count, last_modified_time, workspace_uris, agent_name
            FROM conversation_summaries ORDER BY last_modified_time DESC
        """)
    else:
        cur.execute("""
            SELECT conversation_id, title, preview, step_count, last_modified_time, workspace_uris, agent_name
            FROM conversation_summaries WHERE nesting_depth = 0 AND step_count > 0
            ORDER BY last_modified_time DESC
        """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        console.print("[yellow]No conversations found.[/yellow]")
        return

    table = Table(title="Antigravity Conversations", expand=True, box=box.ROUNDED)
    table.add_column("ID", style="cyan", width=10)
    table.add_column("Steps", justify="right", width=7)
    table.add_column("Workspace", style="green", width=16)
    table.add_column("Title / Snippet", style="white", ratio=1)

    for row in rows:
        cid, title, prev, step_count, last_mod, ws_uris, agent_name = row
        ws_label = get_workspace_label(ws_uris)
        eff_title = (title or "").strip()
        if not eff_title:
            if agent_name: eff_title = f"[{agent_name}]"
            elif prev: eff_title = prev.strip().splitlines()[0][:50]
            else: eff_title = "(Untitled Session)"
        table.add_row(cid[:8], str(step_count), escape(ws_label[:16]), escape(eff_title))

    console.print(table)


def print_turns_table(reader: SessionReader, filter_q: str = ""):
    """Prints turns in a conversation non-interactively."""
    turns = reader.get_turns()
    table = Table(title=f"Turns in Session: {reader.cascade_id}", expand=True, box=box.ROUNDED)
    table.add_column("Turn #", justify="right", width=8, style="bold")
    table.add_column("Steps", justify="center", width=14)
    table.add_column("Tools", justify="center", width=7)
    table.add_column("User Prompt Snippet", ratio=1)

    matching = 0
    for t in turns:
        if filter_q and filter_q.lower() not in t["user_text"].lower():
            continue
        matching += 1
        prompt = t["user_text"].replace("\n", " ").strip()
        if len(prompt) > 85:
            prompt = prompt[:82] + "..."
        table.add_row(
            f"#{t['turn_index']}",
            f"{t['start_step']}..{t['end_step']}",
            str(t["tool_count"]) if t["tool_count"] > 0 else "-",
            escape(prompt)
        )

    console.print(table)
    console.print(f"[dim]Total matching turns: {matching} (of {len(turns)} total)[/dim]")


def print_tools_table(reader: SessionReader, turn_num: Optional[int] = None):
    """Prints tool calls and edits non-interactively."""
    turns = reader.get_turns()
    table = Table(title=f"Tool Calls & Edits in Session: {reader.cascade_id}", expand=True, box=box.ROUNDED)
    table.add_column("Turn #", justify="right", width=8, style="bold")
    table.add_column("Tool #", justify="right", width=8, style="bold yellow")
    table.add_column("Step", justify="center", width=8)
    table.add_column("Action", justify="center", width=12)
    table.add_column("Tool Invocation / Target / Command", ratio=1)

    total_tools = 0
    for t in turns:
        if turn_num is not None and t["turn_index"] != turn_num:
            continue
        for tl in t.get("tools", []):
            total_tools += 1
            ui_name = tl.get("ui_name", tl["tool_name"])
            if ui_name == "Edit":
                act = "[bold green]Edit[/bold green]"
            elif ui_name == "Bash":
                act = "[bold yellow]Bash[/bold yellow]"
            elif ui_name == "Read":
                act = "[bold cyan]Read[/bold cyan]"
            elif ui_name == "ManageTask":
                act = "[bold magenta]Task[/bold magenta]"
            else:
                act = f"[bold white]{ui_name}[/bold white]"

            table.add_row(
                f"#{t['turn_index']}",
                f"#{tl.get('tool_number', '?')}",
                str(tl["step_idx"]),
                act,
                escape(tl.get("full_label", tl.get("short_label", "")))
            )

    console.print(table)
    console.print(f"[dim]Total tools: {total_tools}[/dim]")


# ==============================================================================
# CLI Entry Point
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        prog="agy-chats",
        description="Unified Antigravity Session Suite: browse, search, resume, branch/fork turns, tool surgery, and move workspaces."
    )
    parser.add_argument(
        "conversation",
        nargs="?",
        default=None,
        help="Optional conversation UUID, search query, or subcommand ('transcript', 'fork', 'move')."
    )
    parser.add_argument(
        "arg2",
        nargs="?",
        default=None,
        help="Secondary argument (e.g. conversation ID for transcript/fork, or target workspace for move)."
    )

    # Core Action Modes
    parser.add_argument(
        "-f", "--fork",
        action="store_true",
        help="Fork/branch session mode. Starts TurnExplorerTUI or picker."
    )
    parser.add_argument(
        "-T", "--tool", "--tools",
        dest="tool",
        nargs="?",
        const=True,
        default=None,
        help="Tool Cutter Mode: inspect and cut at individual edits and tool calls (e.g. '--tool' for TUI, or '--tool 9')."
    )
    parser.add_argument(
        "-m", "--move",
        nargs=2,
        metavar=("CONV", "TARGET_WORKSPACE"),
        help="Move/relocate conversation workspace (e.g. --move JB3 E:\\JB)."
    )
    parser.add_argument(
        "-w", "--workspaces",
        action="store_true",
        help="List all registered workspaces and session counts."
    )
    parser.add_argument(
        "-l", "--list",
        action="store_true",
        help="Print conversation list in tabular format and exit."
    )
    parser.add_argument(
        "-c", "--continue", "--last",
        dest="resume_last",
        action="store_true",
        help="Resume the most recent conversation immediately."
    )
    parser.add_argument(
        "-a", "--all",
        action="store_true",
        help="Show all conversations, including subagents and empty sessions."
    )

    # Surgical / Headless Parameters
    parser.add_argument(
        "--turn", "-t",
        type=int,
        default=None,
        help="Target turn number (1-based index) for headless cutting or tool cutter."
    )
    parser.add_argument(
        "--step",
        type=int,
        default=None,
        help="Exact step index to cut at (idx <= step will be preserved)."
    )
    parser.add_argument(
        "--cut",
        choices=["after", "before", "prompt"],
        default="after",
        help="Turn cut policy: 'after' (keep turn, discard future), 'before' (rewind), 'prompt' (keep prompt only)."
    )
    parser.add_argument(
        "--tool-cut",
        choices=["after", "before"],
        default="after",
        help="Tool cut policy when cutting at a tool: 'after' (keep tool result) or 'before' (rewind before tool call)."
    )
    parser.add_argument(
        "--list-turns",
        action="store_true",
        help="Print all turns non-interactively and exit."
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="Print all tool calls and edits non-interactively and exit."
    )
    parser.add_argument(
        "--search", "-s",
        type=str,
        default=None,
        help="Filter turns matching text."
    )
    parser.add_argument(
        "--run", "-r",
        action="store_true",
        help="Automatically launch agy --conversation <NEW_UUID> immediately after forking."
    )
    parser.add_argument(
        "--no-brain",
        action="store_true",
        help="Do not copy artifacts and system logs from the brain directory when forking."
    )

    args = parser.parse_args()

    # 1. Handle Workspace Move CLI
    if args.move:
        cid_query, target_ws = args.move
        ok, msg = move_conversation_workspace(cid_query, target_ws)
        if ok:
            console.print(f"[bold green]✔[/bold green] {msg}")
        else:
            console.print(f"[bold red]✘[/bold red] {msg}")
            sys.exit(1)
        return

    # Handle Subcommand "move <conv> <target_ws>"
    if args.conversation == "move" and args.arg2:
        # If passed as 'agy-chats move JB3 E:\JB'
        # In this case arg2 is JB3, and sys.argv might contain E:\JB
        target_ws = sys.argv[-1] if len(sys.argv) > 3 else None
        if target_ws and target_ws != args.arg2:
            ok, msg = move_conversation_workspace(args.arg2, target_ws)
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

    # 3. Handle Resume Latest
    if args.resume_last:
        resume_latest()
        return

    # 4. Handle List Table
    if args.list:
        list_table(show_all=args.all)
        return

    # 5. Handle Transcript View
    if args.conversation == "transcript" and args.arg2:
        cid = resolve_conversation(args.arg2)
        if cid:
            show_transcript_pager(cid)
        else:
            console.print(f"[bold red]Conversation not found:[/bold red] {args.arg2}")
        return

    # 6. Check for Subcommand "fork"
    if args.conversation == "fork":
        args.fork = True
        args.conversation = args.arg2

    # 7. Check Tool Mode & Headless Operation
    is_tool_mode = args.tool is not None
    has_tool_number = is_tool_mode and args.tool is not True

    # If tool, turn, step, or list flags are specified, enable fork mode
    if (is_tool_mode or args.list_turns or args.list_tools or
        args.step is not None or args.turn is not None or args.search is not None):
        args.fork = True

    # Check for direct headless forking
    is_headless = (
        args.search is not None or
        (args.turn is not None and not is_tool_mode) or
        args.step is not None or
        has_tool_number or
        args.list_turns or
        args.list_tools
    )

    # 8. Interactive vs Headless Dispatch
    if args.fork:
        # Target conversation ID
        target_cid = None
        if args.conversation:
            target_cid = resolve_conversation(args.conversation)

        # Non-interactive / headless listing
        if is_headless:
            if not target_cid:
                target_cid = resolve_conversation(None)
                if not target_cid:
                    console.print("[bold red]Error:[/bold red] No conversations found.")
                    sys.exit(1)

            reader = SessionReader(target_cid)

            if args.list_tools or (is_tool_mode and args.list_turns):
                print_tools_table(reader, turn_num=args.turn)
                return

            if args.list_turns:
                print_turns_table(reader, filter_q=args.search or "")
                return

            # Headless cut execution
            cut_step_idx = None
            turn_num = None
            desc = ""

            if has_tool_number:
                try:
                    target_tool_num = int(args.tool)
                except ValueError:
                    console.print(f"[bold red]Error:[/bold red] Invalid tool number '{args.tool}'. Expected an integer.")
                    sys.exit(1)

                turns = reader.get_turns()
                target_turn = None
                if args.turn is not None:
                    for t in turns:
                        if t["turn_index"] == args.turn:
                            target_turn = t
                            break
                    if not target_turn:
                        console.print(f"[bold red]Error:[/bold red] Turn #{args.turn} not found.")
                        sys.exit(1)
                else:
                    turns_with_tools = [t for t in turns if t.get("tools")]
                    if not turns_with_tools:
                        console.print("[bold red]Error:[/bold red] No tool calls found in this conversation.")
                        sys.exit(1)
                    target_turn = turns_with_tools[-1]

                tools = target_turn.get("tools", [])
                target_tool = next((tl for tl in tools if tl.get("tool_number") == target_tool_num), None)
                if not target_tool:
                    console.print(f"[bold red]Error:[/bold red] Tool #{target_tool_num} not found in Turn #{target_turn['turn_index']} (available: 1..{len(tools)}).")
                    sys.exit(1)

                turn_num = target_turn["turn_index"]
                if args.tool_cut == "after":
                    cut_step_idx = target_tool["step_idx"]
                    desc = f"Cut AFTER Tool #{target_tool_num} '{target_tool.get('short_label')}' (step {cut_step_idx})"
                else:
                    cut_step_idx = max(0, target_tool["step_idx"] - 1)
                    desc = f"Cut BEFORE Tool #{target_tool_num} '{target_tool.get('short_label')}' (step {cut_step_idx})"

            elif args.step is not None:
                cut_step_idx = args.step
                desc = f"Explicit step {cut_step_idx}"
            else:
                turns = reader.get_turns()
                target_turn = None
                if args.search:
                    matches = reader.search_turns(args.search)
                    if not matches:
                        console.print(f"[bold red]Error:[/bold red] No turn found matching search query: '{args.search}'")
                        sys.exit(1)
                    target_turn = matches[-1][1]
                elif args.turn is not None:
                    for t in turns:
                        if t["turn_index"] == args.turn:
                            target_turn = t
                            break
                    if not target_turn:
                        console.print(f"[bold red]Error:[/bold red] Turn #{args.turn} not found (total: {len(turns)}).")
                        sys.exit(1)
                else:
                    target_turn = turns[-1]

                turn_num = target_turn["turn_index"]
                if args.cut == "after":
                    cut_step_idx = target_turn["end_step"]
                    desc = f"Cut AFTER Turn #{turn_num} (step {cut_step_idx})"
                elif args.cut == "before":
                    cut_step_idx = max(0, target_turn["start_step"] - 1)
                    desc = f"Cut BEFORE Turn #{turn_num} (step {cut_step_idx})"
                elif args.cut == "prompt":
                    cut_step_idx = target_turn["start_step"]
                    desc = f"Cut at Prompt of Turn #{turn_num} (step {cut_step_idx})"

            console.print(f"[cyan]Forking conversation {reader.cascade_id} at {desc}...[/cyan]")
            try:
                res = fork_session(
                    reader.cascade_id,
                    cut_step_idx=cut_step_idx,
                    copy_brain=not args.no_brain
                )
                res["cut_description"] = desc
                res["turn_number"] = turn_num

                new_uuid = res["new_cascade_id"]
                resume_cmd = res["resume_cmd"]
                copy_to_clipboard(resume_cmd)

                console.print(Panel(
                    f"[bold green]Session Forked Successfully![/bold green]\n\n"
                    f"Source Session : [cyan]{reader.cascade_id}[/cyan]\n"
                    f"New Session UUID: [bold yellow]{new_uuid}[/bold yellow]\n"
                    f"Cut Point      : {desc}\n"
                    f"Steps Copied   : {res['copied_steps']} steps\n\n"
                    f"[bold white]Resume Command:[/bold white]\n"
                    f"  [bold green]{resume_cmd}[/bold green]\n\n"
                    f"[cyan][OK] Copied to clipboard![/cyan]",
                    title="Fork Success",
                    border_style="green"
                ))

                if args.run:
                    console.print(f"\n[bold green]Launching agy session...[/bold green]\n")
                    if sys.platform == "win32":
                        subprocess.run(f"agy --conversation {new_uuid}", shell=True)
                    else:
                        os.execvp("agy", ["agy", "--conversation", new_uuid])

            except Exception as e:
                console.print(f"[bold red]Fork failed:[/bold red] {e}")
                sys.exit(1)
            return

        # Interactive TUI Fork / Tool Mode
        if not target_cid:
            # Launch browser picker in fork or tool mode
            default_act = "tool" if is_tool_mode else "fork"
            picker = MainChatsTUI(show_all=args.all, default_action=default_act, target_turn=args.turn)
            picker.run()
            return

        # Target conversation is specified: open explorer or cutter directly
        if is_tool_mode:
            cutter = ToolCutterTUI(target_cid, turn_index=args.turn)
            res = cutter.run()
        else:
            forker = TurnExplorerTUI(target_cid)
            if args.search:
                forker.update_filter(args.search)
            res = forker.run()

        if res:
            show_success_screen(res)
        return

    # 9. Direct Conversation ID Argument without flags
    if args.conversation:
        # Check if argument is a UUID or hex prefix
        if re.match(r"^[0-9a-fA-F\-]{6,}$", args.conversation):
            target_cid = resolve_conversation(args.conversation)
            if target_cid:
                resume_conversation(target_cid)
                return

    # 10. Default Launch: Master Interactive Chats TUI
    initial_q = args.conversation or ""
    app = MainChatsTUI(show_all=args.all, initial_query=initial_q, default_action="resume")
    app.run()


if __name__ == "__main__":
    main()
