#!/usr/bin/env python3
"""
agy-chats: Interactive Terminal User Interface (TUI) to browse, inspect,
and resume previous Google Antigravity (agy) conversations.
"""

import sys
import os
import sqlite3
import json
import re
import shutil
import subprocess
import argparse
from datetime import datetime, timezone

DB_PATH = os.path.expanduser("~/.gemini/antigravity-cli/conversation_summaries.db")
BRAIN_DIR = os.path.expanduser("~/.gemini/antigravity-cli/brain")
STATE_FILE = "/tmp/agy_chats_show_all"

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


def get_db_connection():
    if not os.path.exists(DB_PATH):
        return None
    try:
        return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5.0)
    except Exception:
        try:
            return sqlite3.connect(DB_PATH, timeout=5.0)
        except Exception:
            return None


def parse_time(s):
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


def format_relative(dt):
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


def format_workspace(ws_uris):
    if not ws_uris:
        return "~"
    try:
        uris = json.loads(ws_uris)
        paths = []
        home = os.path.expanduser("~")
        for u in uris:
            p = u.replace("file://", "")
            if p.startswith(home):
                p = "~" + p[len(home):]
            paths.append(p)
        return ", ".join(paths) if paths else "~"
    except Exception:
        return "~"


def clean_user_message(content):
    if not content:
        return ""
    m = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", content, re.DOTALL)
    if m:
        return m.group(1).strip()
    return re.sub(r"<[^>]+>", "", content).strip()


def get_conversation_details(cid):
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


def query_conversations(show_all=False):
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


def build_preview(cid):
    conn = get_db_connection()
    if not conn:
        return f"{RED}Could not open database at {DB_PATH}{RESET}"
    cur = conn.cursor()
    cur.execute("""
        SELECT conversation_id, title, preview, step_count, last_modified_time,
               workspace_uris, agent_name, nesting_depth, parent_conversation_id
        FROM conversation_summaries WHERE conversation_id = ?
    """, (cid,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return f"{RED}Conversation {cid} not found.{RESET}"

    cid, title, prev, step_count, last_mod, ws_uris, agent_name, depth, parent_id = row
    steps, user_prompts, asst_replies = get_conversation_details(cid)

    parsed_time = parse_time(last_mod)
    rel_time = format_relative(parsed_time)
    exact_time = parsed_time.strftime("%Y-%m-%d %H:%M:%S UTC") if parsed_time else last_mod
    workspace_str = format_workspace(ws_uris)

    # Title fallback
    effective_title = title.strip()
    if not effective_title:
        if user_prompts:
            effective_title = user_prompts[0][1].splitlines()[0][:60]
        elif agent_name:
            effective_title = f"Subagent: {agent_name}"
        else:
            effective_title = "Untitled Session"

    out = []
    out.append(f"{BOLD}{CYAN}╭───────────────────────────────────────────────────────────────────╮{RESET}")
    title_line = f" {effective_title}"
    if len(title_line) > 65:
        title_line = title_line[:62] + "..."
    out.append(f"{BOLD}{CYAN}│{RESET} {BOLD}{WHITE}{title_line:<65}{RESET} {BOLD}{CYAN}│{RESET}")
    out.append(f"{BOLD}{CYAN}╰───────────────────────────────────────────────────────────────────╯{RESET}")
    out.append("")

    out.append(f"{BOLD}ID:{RESET}         {GRAY}{cid}{RESET}")
    if agent_name:
        out.append(f"{BOLD}Agent:{RESET}      {MAGENTA}{agent_name}{RESET} (subagent depth {depth})")
    else:
        out.append(f"{BOLD}Type:{RESET}       {GREEN}Main User Session{RESET}")
    out.append(f"{BOLD}Active:{RESET}     {YELLOW}{rel_time}{RESET} {DIM}({exact_time}){RESET}")
    out.append(f"{BOLD}Stats:{RESET}      {BLUE}{step_count} total steps{RESET} • {CYAN}{len(user_prompts)} user turns{RESET}")
    out.append(f"{BOLD}Workspace:{RESET}  {GREEN}{workspace_str}{RESET}")
    out.append("")

    if user_prompts:
        out.append(f"{BOLD}{YELLOW}▶ INITIAL USER REQUEST:{RESET}")
        first_time, first_prompt = user_prompts[0]
        lines = first_prompt.strip().splitlines()
        show_lines = lines[:7]
        for l in show_lines:
            out.append(f"  {GRAY}│{RESET} {l}")
        if len(lines) > 7:
            out.append(f"  {GRAY}│ ... [{len(lines) - 7} more lines]{RESET}")
        out.append("")

    if asst_replies:
        out.append(f"{BOLD}{GREEN}▶ LATEST ASSISTANT RESPONSE:{RESET}")
        last_time, last_reply = asst_replies[-1]
        lines = last_reply.strip().splitlines()
        show_lines = lines[:9]
        for l in show_lines:
            out.append(f"  {GRAY}│{RESET} {l}")
        if len(lines) > 9:
            out.append(f"  {GRAY}│ ... [{len(lines) - 9} more lines]{RESET}")
        out.append("")

    out.append(f"{GRAY}─────────────────────────────────────────────────────────────────────{RESET}")
    out.append(f"{BOLD}Resume CLI:{RESET}  {CYAN}agy --conversation {cid}{RESET}")
    return "\n".join(out)


def show_transcript_pager(cid):
    steps, user_prompts, asst_replies = get_conversation_details(cid)
    if not steps:
        tpath = os.path.join(BRAIN_DIR, cid, ".system_generated/logs/transcript.jsonl")
        print(f"{RED}No transcript steps found at {tpath}{RESET}")
        input("Press Enter to continue...")
        return

    buf = []
    buf.append("=" * 70)
    buf.append(f"TRANSCRIPT FOR CONVERSATION {cid}")
    buf.append("=" * 70)
    buf.append("")

    turn_idx = 1
    for s in steps:
        stype = s.get("type", "")
        source = s.get("source", "")
        created_at = s.get("created_at", "")
        content = s.get("content", "")

        if stype == "USER_INPUT":
            cleaned = clean_user_message(content)
            buf.append(f"{BOLD}{YELLOW}━━━ [USER TURN #{turn_idx}] ━━━━━━━━━━━━━ {created_at} ━━━{RESET}")
            buf.append(cleaned)
            buf.append("")
            turn_idx += 1
        elif stype == "PLANNER_RESPONSE":
            if content:
                buf.append(f"{BOLD}{GREEN}━━━ [ASSISTANT] ━━━━━━━━━━━━━━━━━━━━━━ {created_at} ━━━{RESET}")
                buf.append(content)
                buf.append("")
            tool_calls = s.get("tool_calls", [])
            for tc in tool_calls:
                tname = tc.get("name", "tool")
                tsum = tc.get("toolSummary", "")
                targs = tc.get("args", {})
                buf.append(f"{DIM}{BLUE}▶ Tool: {tname} ({tsum}){RESET}")
                if "CommandLine" in targs:
                    buf.append(f"  {DIM}$ {targs['CommandLine']}{RESET}")
                elif "TargetFile" in targs:
                    buf.append(f"  {DIM}File: {targs['TargetFile']}{RESET}")
            if tool_calls:
                buf.append("")
        elif stype in ("SYSTEM_MESSAGE", "GENERIC"):
            if content and not content.startswith("{"):
                buf.append(f"{GRAY}[System: {content[:100]}]{RESET}")

    transcript_text = "\n".join(buf)
    pager = os.environ.get("PAGER", "less -R")
    try:
        proc = subprocess.Popen(pager, shell=True, stdin=subprocess.PIPE, text=True)
        proc.communicate(input=transcript_text)
    except Exception:
        print(transcript_text)
        input("Press Enter to continue...")


def dump_list(show_all=False):
    rows = query_conversations(show_all=show_all)
    for row in rows:
        cid, title, prev, step_count, last_mod, ws_uris, agent_name, depth, parent_id = row
        dt = parse_time(last_mod)
        rel_time = format_relative(dt)
        workspace = format_workspace(ws_uris)

        effective_title = title.strip()
        if not effective_title:
            if agent_name:
                effective_title = f"[{agent_name}]"
            elif prev:
                effective_title = prev.strip().splitlines()[0][:50]
            else:
                effective_title = "(Untitled Session)"

        short_id = cid[:8]
        if agent_name:
            tag = f"{MAGENTA}[{agent_name[:12]}]{RESET}"
        else:
            tag = f"{GREEN}●{RESET}"

        display_col = (
            f"{tag} {CYAN}{short_id}{RESET}  "
            f"{BOLD}{WHITE}{effective_title:<38}{RESET}  "
            f"{YELLOW}{rel_time:<10}{RESET}  "
            f"{BLUE}{step_count:>3} steps{RESET}  "
            f"{DIM}{workspace}{RESET}"
        )
        print(f"{cid}\t{display_col}")


def copy_to_clipboard(text):
    if shutil.which("wl-copy"):
        subprocess.run(["wl-copy"], input=text.encode("utf-8"), check=False)
        return True
    elif shutil.which("xclip"):
        subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode("utf-8"), check=False)
        return True
    elif shutil.which("xsel"):
        subprocess.run(["xsel", "--clipboard", "--input"], input=text.encode("utf-8"), check=False)
        return True
    return False


def run_fzf_tui(initial_query="", show_all=False):
    script_path = os.path.abspath(__file__)
    if show_all:
        open(STATE_FILE, "w").close()
    elif os.path.exists(STATE_FILE):
        try:
            os.remove(STATE_FILE)
        except Exception:
            pass

    while True:
        # Generate current candidate list
        current_show_all = os.path.exists(STATE_FILE)
        rows = query_conversations(show_all=current_show_all)
        if not rows and not current_show_all:
            # Fall back to showing all if no top-level chats
            current_show_all = True
            rows = query_conversations(show_all=True)

        lines = []
        for row in rows:
            cid, title, prev, step_count, last_mod, ws_uris, agent_name, depth, parent_id = row
            dt = parse_time(last_mod)
            rel_time = format_relative(dt)
            workspace = format_workspace(ws_uris)
            effective_title = title.strip()
            if not effective_title:
                if agent_name:
                    effective_title = f"[{agent_name}]"
                elif prev:
                    effective_title = prev.strip().splitlines()[0][:50]
                else:
                    effective_title = "(Untitled Session)"

            short_id = cid[:8]
            if agent_name:
                tag = f"\033[35m[{agent_name[:12]}]\033[0m"
            else:
                tag = f"\033[32m●\033[0m"

            display_col = (
                f"{tag} \033[36m{short_id}\033[0m  "
                f"\033[1;37m{effective_title:<38}\033[0m  "
                f"\033[33m{rel_time:<10}\033[0m  "
                f"\033[34m{step_count:>3} steps\033[0m  "
                f"\033[2m{workspace}\033[0m"
            )
            lines.append(f"{cid}\t{display_col}")

        input_data = "\n".join(lines)

        mode_str = "All Sessions (incl. subagents)" if current_show_all else "Main Chats Only"
        header = (
            f"Mode: {mode_str}\n"
            "ENTER: Continue Chat | CTRL-T: Full Transcript | CTRL-Y: Copy ID | CTRL-A: Toggle All | ESC: Quit"
        )

        fzf_cmd = [
            "fzf",
            "--ansi",
            "--delimiter=\t",
            "--with-nth=2..",
            f"--preview={script_path} --preview {{1}}",
            "--preview-window=right:52%:wrap",
            f"--header={header}",
            "--prompt=Resume Chat > ",
            "--expect=ctrl-t,ctrl-y,ctrl-o,ctrl-a,enter",
            "--height=90%",
            "--border=rounded",
            "--info=inline",
        ]
        if initial_query:
            fzf_cmd.append(f"--query={initial_query}")
            initial_query = ""  # Only use on first loop

        try:
            proc = subprocess.Popen(
                fzf_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True
            )
            stdout, _ = proc.communicate(input=input_data)
        except FileNotFoundError:
            print(f"{YELLOW}fzf not found; falling back to curses TUI...{RESET}")
            run_curses_tui(show_all=show_all)
            return

        if proc.returncode != 0 and not stdout:
            # User canceled (Esc or Ctrl-C)
            return

        out_lines = stdout.splitlines()
        if not out_lines:
            return

        key = out_lines[0].strip() if len(out_lines) >= 2 else ""
        selected_line = out_lines[1] if len(out_lines) >= 2 else out_lines[0]
        cid = selected_line.split("\t")[0].strip()

        if key == "ctrl-a":
            # Toggle show_all and loop
            if os.path.exists(STATE_FILE):
                os.remove(STATE_FILE)
            else:
                open(STATE_FILE, "w").close()
            continue
        elif key == "ctrl-t":
            show_transcript_pager(cid)
            continue
        elif key == "ctrl-y":
            if copy_to_clipboard(cid):
                print(f"{GREEN}✔ Copied conversation ID {cid} to clipboard.{RESET}")
            else:
                print(f"Conversation ID: {cid}")
            return
        elif key == "ctrl-o":
            print(cid)
            return
        else:
            # Enter: execute agy --conversation <cid>
            print(f"{BOLD}{GREEN}Resuming conversation {CYAN}{cid}{GREEN}...{RESET}\n")
            os.execvp("agy", ["agy", "--conversation", cid])


def run_curses_tui(show_all=False):
    import curses

    def curses_main(stdscr):
        curses.curs_set(0)
        curses.use_default_colors()
        selected_idx = 0
        scroll_offset = 0
        current_show_all = show_all

        while True:
            stdscr.clear()
            h, w = stdscr.getmaxyx()
            rows = query_conversations(show_all=current_show_all)

            if not rows:
                stdscr.addstr(2, 2, "No conversations found. Press 'a' to toggle all, 'q' to quit.")
                key = stdscr.getch()
                if key in (ord('q'), 27):
                    break
                elif key == ord('a'):
                    current_show_all = not current_show_all
                continue

            if selected_idx >= len(rows):
                selected_idx = len(rows) - 1
            if selected_idx < 0:
                selected_idx = 0

            split_col = max(30, int(w * 0.45))
            list_height = h - 4

            # Draw Header
            title_hdr = f" AGY Previous Chats ({'All Sessions' if current_show_all else 'Main Chats'}) "
            stdscr.addstr(0, 2, title_hdr, curses.A_BOLD | curses.A_REVERSE)
            help_str = " [↑/↓] Select | [Enter] Resume | [t] Transcript | [a] Toggle All | [q] Quit "
            if w > len(help_str) + 4:
                stdscr.addstr(h - 1, 2, help_str, curses.A_DIM)

            # Draw List Pane
            if selected_idx < scroll_offset:
                scroll_offset = selected_idx
            elif selected_idx >= scroll_offset + list_height:
                scroll_offset = selected_idx - list_height + 1

            for i in range(list_height):
                item_idx = scroll_offset + i
                if item_idx >= len(rows):
                    break
                row = rows[item_idx]
                cid, title, prev, step_count, last_mod, ws_uris, agent_name, depth, parent_id = row
                dt = parse_time(last_mod)
                rel_time = format_relative(dt)
                eff_title = title.strip() or (f"[{agent_name}]" if agent_name else "(Untitled)")
                line_str = f" {eff_title[:split_col - 16]:<{split_col - 16}} {rel_time:>10} "

                y = 2 + i
                if item_idx == selected_idx:
                    stdscr.addstr(y, 1, line_str[:split_col - 1], curses.A_STANDOUT | curses.A_BOLD)
                else:
                    stdscr.addstr(y, 1, line_str[:split_col - 1])

            # Vertical separator
            for y in range(1, h - 2):
                stdscr.addstr(y, split_col, "│", curses.A_DIM)

            # Draw Preview Pane
            sel_row = rows[selected_idx]
            cid = sel_row[0]
            title = sel_row[1] or "(Untitled Session)"
            step_count = sel_row[3]
            last_mod = sel_row[4]
            ws_uris = sel_row[5]
            agent_name = sel_row[6]
            ws_str = format_workspace(ws_uris)
            dt = parse_time(last_mod)
            rel_time = format_relative(dt)

            px = split_col + 2
            pw = w - px - 2
            if pw > 10:
                stdscr.addstr(2, px, f"Title: {title[:pw]}", curses.A_BOLD)
                stdscr.addstr(3, px, f"ID:    {cid[:pw]}", curses.A_DIM)
                stdscr.addstr(4, px, f"Time:  {rel_time} ({last_mod[:19]})")
                stdscr.addstr(5, px, f"Steps: {step_count} total steps")
                stdscr.addstr(6, px, f"Dir:   {ws_str[:pw]}")
                stdscr.addstr(7, px, "─" * min(pw, 50), curses.A_DIM)

                # Show preview snippet
                steps, user_prompts, asst_replies = get_conversation_details(cid)
                cur_y = 9
                if user_prompts and cur_y < h - 5:
                    stdscr.addstr(cur_y, px, "Initial User Prompt:", curses.A_UNDERLINE)
                    cur_y += 1
                    for pline in user_prompts[0][1].splitlines()[:4]:
                        if cur_y >= h - 5:
                            break
                        stdscr.addstr(cur_y, px + 2, pline[:pw - 2])
                        cur_y += 1

                if asst_replies and cur_y < h - 4:
                    cur_y += 1
                    stdscr.addstr(cur_y, px, "Latest Assistant Response:", curses.A_UNDERLINE)
                    cur_y += 1
                    for aline in asst_replies[-1][1].splitlines()[:5]:
                        if cur_y >= h - 2:
                            break
                        stdscr.addstr(cur_y, px + 2, aline[:pw - 2])
                        cur_y += 1

            stdscr.refresh()
            ch = stdscr.getch()

            if ch in (ord('q'), 27):
                return None
            elif ch in (curses.KEY_UP, ord('k')):
                selected_idx -= 1
            elif ch in (curses.KEY_DOWN, ord('j')):
                selected_idx += 1
            elif ch == curses.KEY_PPAGE:
                selected_idx -= list_height
            elif ch == curses.KEY_NPAGE:
                selected_idx += list_height
            elif ch == ord('a'):
                current_show_all = not current_show_all
            elif ch == ord('t'):
                curses.endwin()
                show_transcript_pager(cid)
                stdscr.clear()
            elif ch in (ord('\n'), curses.KEY_ENTER):
                return cid

    selected_cid = curses.wrapper(curses_main)
    if selected_cid:
        print(f"{BOLD}{GREEN}Resuming conversation {CYAN}{selected_cid}{GREEN}...{RESET}\n")
        os.execvp("agy", ["agy", "--conversation", selected_cid])


def list_table(show_all=False):
    rows = query_conversations(show_all=show_all)
    if not rows:
        print(f"{YELLOW}No conversations found in database.{RESET}")
        return

    print(f"\n{BOLD}{CYAN}{'ID':<10} {'ACTIVE':<12} {'STEPS':<8} {'TITLE':<40} {'WORKSPACE'}{RESET}")
    print(f"{GRAY}{'─'*10} {'─'*12} {'─'*8} {'─'*40} {'─'*25}{RESET}")
    for row in rows:
        cid, title, prev, step_count, last_mod, ws_uris, agent_name, depth, parent_id = row
        dt = parse_time(last_mod)
        rel_time = format_relative(dt)
        workspace = format_workspace(ws_uris)
        eff_title = title.strip()
        if not eff_title:
            if agent_name:
                eff_title = f"[{agent_name}]"
            elif prev:
                eff_title = prev.strip().splitlines()[0][:38]
            else:
                eff_title = "(Untitled Session)"

        short_id = cid[:8]
        if agent_name:
            tag = f"{MAGENTA}{short_id}{RESET}"
        else:
            tag = f"{CYAN}{short_id}{RESET}"

        print(f"{tag:<19} {YELLOW}{rel_time:<12}{RESET} {BLUE}{step_count:<8}{RESET} {BOLD}{eff_title[:38]:<40}{RESET} {DIM}{workspace}{RESET}")
    print()


def resume_latest():
    rows = query_conversations(show_all=False)
    if not rows:
        rows = query_conversations(show_all=True)
    if not rows:
        print(f"{RED}No previous conversations found.{RESET}")
        sys.exit(1)
    cid = rows[0][0]
    print(f"{BOLD}{GREEN}Resuming latest conversation {CYAN}{cid}{GREEN}...{RESET}\n")
    os.execvp("agy", ["agy", "--conversation", cid])


def main():
    parser = argparse.ArgumentParser(
        description="Interactive TUI to browse and resume previous agy conversations."
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
        help="Subcommand argument (e.g. conversation ID for 'transcript' or 'preview')"
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
        "--curses",
        action="store_true",
        help="Force native curses TUI instead of fzf"
    )
    parser.add_argument(
        "--preview",
        metavar="CID",
        help=argparse.SUPPRESS  # Internal flag for fzf preview
    )
    parser.add_argument(
        "--dump-list",
        action="store_true",
        help=argparse.SUPPRESS  # Internal flag for fzf reload
    )

    args = parser.parse_args()

    # Handle internal helper flags first
    if args.preview:
        print(build_preview(args.preview))
        return
    if args.query == "preview" and args.arg2:
        print(build_preview(args.arg2))
        return
    if args.dump_list:
        dump_list(show_all=args.all or os.path.exists(STATE_FILE))
        return
    if args.query == "transcript" and args.arg2:
        show_transcript_pager(args.arg2)
        return

    # Direct resume latest
    if args.resume_last:
        resume_latest()
        return

    # Direct list
    if args.list:
        list_table(show_all=args.all)
        return

    # Direct CID check: if user passed an exact or prefix UUID match
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
                print(f"{BOLD}{GREEN}Resuming conversation {CYAN}{cid}{GREEN}...{RESET}\n")
                os.execvp("agy", ["agy", "--conversation", cid])

    # Run TUI
    if args.curses or not shutil.which("fzf"):
        run_curses_tui(show_all=args.all)
    else:
        run_fzf_tui(initial_query=args.query, show_all=args.all)


if __name__ == "__main__":
    main()
