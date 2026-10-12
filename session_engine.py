"""
session_engine: Core engine for Antigravity (agy) session inspection,
forking/branching, turn & tool parsing, and workspace management.
"""

import sys
import os
import glob
import sqlite3
import uuid
import shutil
import subprocess
import json
import re
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple, Any

DEFAULT_CONV_DIR = os.path.expanduser("~/.gemini/antigravity-cli/conversations")
DEFAULT_BRAIN_DIR = os.path.expanduser("~/.gemini/antigravity-cli/brain")
DEFAULT_SUMMARIES_DB = os.path.expanduser("~/.gemini/antigravity-cli/conversation_summaries.db")


# ==============================================================================
# Pure-Python Wire-Format Protobuf Parser & Serializer
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


# ==============================================================================
# Tool Calls & Step Inspection
# ==============================================================================

def format_tool_display(tool_name: str, args: Dict[str, Any]) -> Tuple[str, str, str]:
    """Returns (ui_name, short_display, full_display) matching Antigravity CLI's rendering."""
    if tool_name in ("replace_file_content", "write_to_file"):
        ui_name = "Edit"
        path = args.get("TargetFile", "")
        base = os.path.basename(path) if path else ""
        return ui_name, f"Edit({base})", f"Edit({path})"
    elif tool_name == "view_file":
        ui_name = "Read"
        path = args.get("AbsolutePath", "")
        base = os.path.basename(path) if path else ""
        return ui_name, f"Read({base})", f"Read({path})"
    elif tool_name == "run_command":
        ui_name = "Bash"
        cmd = args.get("CommandLine", "")
        cmd_clean = cmd.replace("\r", " ").replace("\n", " ").strip()
        cmd_short = (cmd_clean[:47] + "...") if len(cmd_clean) > 50 else cmd_clean
        return ui_name, f"Bash({cmd_short})", f"Bash({cmd})"
    elif tool_name == "manage_task":
        ui_name = "ManageTask"
        action = args.get("Action", "")
        tid = args.get("TaskId", "")
        tid_short = tid.split("/")[-1] if "/" in tid else tid
        arg_str = f"{action} {tid_short}".strip()
        full_arg = f"{action} {tid}".strip()
        return ui_name, f"ManageTask({arg_str})", f"ManageTask({full_arg})"
    elif tool_name == "send_message":
        ui_name = "SendMessage"
        rec = args.get("Recipient", "")
        return ui_name, f"SendMessage({rec})", f"SendMessage({rec})"
    elif tool_name == "schedule":
        ui_name = "Schedule"
        cron = str(args.get("CronExpression") or args.get("DurationSeconds") or "")
        return ui_name, f"Schedule({cron})", f"Schedule({cron})"
    else:
        ui_name = tool_name
        return ui_name, f"{tool_name}()", f"{tool_name}()"


def extract_tool_info(payload: bytes) -> Optional[Dict[str, Any]]:
    """Extracts tool call details from step_payload (step_type 132)."""
    if not payload:
        return None
    try:
        fields = parse_proto_fields(payload)
        for fn, wt, v in fields:
            if fn == 5 and wt == 2:
                sub = parse_proto_fields(v)
                for sfn, swt, sv in sub:
                    if sfn == 4 and swt == 2:
                        csub = parse_proto_fields(sv)
                        c_id, tool_name, args = None, None, {}
                        for cfn, cwt, cv in csub:
                            if cfn == 1 and cwt == 2:
                                c_id = cv.decode("utf-8", errors="ignore")
                            elif cfn == 2 and cwt == 2:
                                tool_name = cv.decode("utf-8", errors="ignore")
                            elif cfn == 3 and cwt == 2:
                                try:
                                    args = json.loads(cv.decode("utf-8", errors="ignore"))
                                except Exception:
                                    args = {}
                        if tool_name:
                            ui_name, short_disp, full_disp = format_tool_display(tool_name, args)
                            return {
                                "call_id": c_id,
                                "tool_name": tool_name,
                                "ui_name": ui_name,
                                "short_label": short_disp,
                                "full_label": full_disp,
                                "args": args
                            }
    except Exception:
        pass
    return None


def extract_step_details(payload: bytes) -> Dict[str, Any]:
    if not payload:
        return {}
    details = {
        "turn_id": None,
        "user_text": None,
        "agent_text": None,
        "model_id": None,
    }
    try:
        fields = parse_proto_fields(payload)
        for f_num, w_type, val in fields:
            if f_num == 5 and w_type == 2:
                sub = parse_proto_fields(val)
                for sf_num, sw_type, sval in sub:
                    if sf_num == 12 and sw_type == 2:
                        try:
                            details["turn_id"] = sval.decode("utf-8", errors="ignore")
                        except Exception:
                            pass
            elif f_num == 19 and w_type == 2:
                sub = parse_proto_fields(val)
                for sf_num, sw_type, sval in sub:
                    if sf_num == 2 and sw_type == 2:
                        try:
                            details["user_text"] = sval.decode("utf-8", errors="replace")
                        except Exception:
                            pass
            elif f_num == 20 and w_type == 2:
                sub = parse_proto_fields(val)
                for sf_num, sw_type, sval in sub:
                    if sf_num == 3 and sw_type == 2:
                        try:
                            details["agent_text"] = sval.decode("utf-8", errors="replace")
                        except Exception:
                            pass
                    elif sf_num == 6 and sw_type == 2:
                        try:
                            details["model_id"] = sval.decode("utf-8", errors="ignore")
                        except Exception:
                            pass
    except Exception:
        pass
    return details


# ==============================================================================
# SessionReader: Turn & Tool Aggregator
# ==============================================================================

class SessionReader:
    def __init__(self, conv_id_or_path: str, conv_dir: str = DEFAULT_CONV_DIR, brain_dir: str = DEFAULT_BRAIN_DIR):
        self.conv_dir = conv_dir
        self.brain_dir = brain_dir
        if os.path.isabs(conv_id_or_path) or conv_id_or_path.endswith(".db"):
            self.db_path = conv_id_or_path
            self.cascade_id = os.path.splitext(os.path.basename(conv_id_or_path))[0]
        else:
            self.cascade_id = conv_id_or_path.strip()
            self.db_path = os.path.join(self.conv_dir, f"{self.cascade_id}.db")

        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"Conversation database not found: {self.db_path}")

        self.trajectory_id = None
        self._load_meta()

    def _load_meta(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT trajectory_id, cascade_id FROM trajectory_meta")
        row = cur.fetchone()
        if row:
            self.trajectory_id = row[0]
            self.cascade_id = row[1]
        conn.close()

    def get_turns(self) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT idx, step_type, step_payload FROM steps ORDER BY idx")
        all_steps = cur.fetchall()
        conn.close()

        turns = []
        current_turn = None

        for idx, step_type, payload in all_steps:
            if step_type == 14:  # User prompt
                details = extract_step_details(payload)
                user_text = details.get("user_text") or "(No text or system prompt)"
                turn_id = details.get("turn_id")

                if current_turn:
                    current_turn["end_step"] = idx - 1
                    turns.append(current_turn)

                current_turn = {
                    "turn_index": len(turns) + 1,
                    "turn_id": turn_id,
                    "start_step": idx,
                    "end_step": idx,
                    "prompt_step": idx,
                    "user_text": user_text,
                    "assistant_text": "",
                    "tool_count": 0,
                    "tools": [],
                    "step_types": [step_type]
                }
            else:
                if current_turn is not None:
                    current_turn["end_step"] = idx
                    current_turn["step_types"].append(step_type)
                    if step_type == 132:
                        tinfo = extract_tool_info(payload)
                        if not tinfo:
                            tinfo = {
                                "call_id": None,
                                "tool_name": "tool_call",
                                "ui_name": "Tool",
                                "short_label": f"Tool(step {idx})",
                                "full_label": f"Tool(step {idx})",
                                "args": {}
                            }
                        tinfo["step_idx"] = idx
                        tinfo["tool_number"] = len(current_turn["tools"]) + 1
                        current_turn["tools"].append(tinfo)
                        current_turn["tool_count"] = len(current_turn["tools"])
                    elif step_type == 15 and not current_turn["assistant_text"]:
                        details = extract_step_details(payload)
                        agent_text = details.get("agent_text") or ""
                        if agent_text:
                            current_turn["assistant_text"] = agent_text

        if current_turn:
            turns.append(current_turn)

        return turns

    def search_turns(self, query: str) -> List[Tuple[int, Dict[str, Any]]]:
        turns = self.get_turns()
        query_lower = query.lower()
        matches = []
        for i, t in enumerate(turns):
            if query_lower in t["user_text"].lower():
                matches.append((i, t))
        return matches


# ==============================================================================
# Forking / Branching Engine
# ==============================================================================

def fork_session(
    src_conv_id: str,
    cut_step_idx: int,
    conv_dir: str = DEFAULT_CONV_DIR,
    brain_dir: str = DEFAULT_BRAIN_DIR,
    custom_new_uuid: Optional[str] = None,
    copy_brain: bool = True
) -> Dict[str, Any]:
    """
    Forks an Antigravity conversation database up to cut_step_idx into a fresh UUID.
    Non-destructive: original conversation is completely untouched.
    """
    reader = SessionReader(src_conv_id, conv_dir=conv_dir, brain_dir=brain_dir)
    src_db = reader.db_path
    src_cascade_id = reader.cascade_id
    src_trajectory_id = reader.trajectory_id

    new_cascade_id = custom_new_uuid or str(uuid.uuid4())
    new_trajectory_id = str(uuid.uuid4())
    dst_db = os.path.join(conv_dir, f"{new_cascade_id}.db")

    if os.path.exists(dst_db):
        raise FileExistsError(f"Target conversation database already exists: {dst_db}")

    src_conn = sqlite3.connect(src_db)
    dst_conn = sqlite3.connect(dst_db)
    src_cur = src_conn.cursor()
    dst_cur = dst_conn.cursor()

    # 1. Clone table schemas
    src_cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
    tables = src_cur.fetchall()
    for t_name, sql in tables:
        dst_cur.execute(sql)

    # 2. trajectory_meta
    src_cur.execute("SELECT trajectory_id, cascade_id, trajectory_type, source FROM trajectory_meta")
    row = src_cur.fetchone()
    if row:
        _, _, traj_type, source = row
        dst_cur.execute("INSERT INTO trajectory_meta VALUES (?, ?, ?, ?)",
                        (new_trajectory_id, new_cascade_id, traj_type, source))

    # 3. trajectory_metadata_blob
    src_cur.execute("SELECT id, data FROM trajectory_metadata_blob")
    for b_id, b_data in src_cur.fetchall():
        if b_data:
            b_data = b_data.replace(src_cascade_id.encode("utf-8"), new_cascade_id.encode("utf-8"))
            if src_trajectory_id:
                b_data = b_data.replace(src_trajectory_id.encode("utf-8"), new_trajectory_id.encode("utf-8"))
        dst_cur.execute("INSERT INTO trajectory_metadata_blob VALUES (?, ?)", (b_id, b_data))

    # 4. steps (idx <= cut_step_idx)
    src_cur.execute(f"SELECT * FROM steps WHERE idx <= ? ORDER BY idx", (cut_step_idx,))
    step_rows = src_cur.fetchall()
    new_step_rows = []
    for r in step_rows:
        row_list = list(r)
        if row_list[9]:  # step_payload
            payload = row_list[9]
            payload = payload.replace(src_cascade_id.encode("utf-8"), new_cascade_id.encode("utf-8"))
            if src_trajectory_id:
                payload = payload.replace(src_trajectory_id.encode("utf-8"), new_trajectory_id.encode("utf-8"))
            row_list[9] = payload
        new_step_rows.append(tuple(row_list))

    dst_cur.executemany("INSERT INTO steps VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", new_step_rows)

    # 5. gen_metadata
    src_cur.execute("SELECT count(*) FROM steps WHERE idx <= ? AND step_type = 15", (cut_step_idx,))
    c15 = src_cur.fetchone()[0]
    src_cur.execute("SELECT * FROM gen_metadata WHERE idx < ? ORDER BY idx", (c15,))
    dst_cur.executemany("INSERT INTO gen_metadata VALUES (?, ?, ?)", src_cur.fetchall())

    # 6. executor_metadata
    src_cur.execute("SELECT count(*) FROM steps WHERE idx <= ? AND step_type IN (14, 23)", (cut_step_idx,))
    c_exec = src_cur.fetchone()[0]
    src_cur.execute("SELECT * FROM executor_metadata WHERE idx <= ? ORDER BY idx", (c_exec,))
    dst_cur.executemany("INSERT INTO executor_metadata VALUES (?, ?)", src_cur.fetchall())

    # 7. parent_references
    src_cur.execute("SELECT count(*) FROM steps WHERE idx <= ? AND step_type = 23", (cut_step_idx,))
    c_parent = src_cur.fetchone()[0]
    src_cur.execute("SELECT * FROM parent_references WHERE idx < ? ORDER BY idx", (c_parent,))
    dst_cur.executemany("INSERT INTO parent_references VALUES (?, ?)", src_cur.fetchall())

    dst_conn.commit()
    src_conn.close()

    dst_cur.execute("PRAGMA integrity_check")
    integrity = dst_cur.fetchone()[0]
    dst_conn.close()

    if integrity != "ok":
        raise RuntimeError(f"Database integrity check failed: {integrity}")

    # Copy brain directory artifacts
    src_brain = os.path.join(brain_dir, src_cascade_id)
    dst_brain = os.path.join(brain_dir, new_cascade_id)
    brain_copied = False
    if copy_brain and os.path.exists(src_brain):
        os.makedirs(dst_brain, exist_ok=True)
        for item in os.listdir(src_brain):
            src_item = os.path.join(src_brain, item)
            dst_item = os.path.join(dst_brain, item)
            if item in [".system_generated", "scratch", ".user_uploaded"] or item.endswith(".md"):
                if os.path.isdir(src_item):
                    shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                else:
                    shutil.copy2(src_item, dst_item)
        brain_copied = True

    resume_cmd = f"agy --conversation {new_cascade_id}"

    return {
        "status": "success",
        "source_cascade_id": src_cascade_id,
        "new_cascade_id": new_cascade_id,
        "new_trajectory_id": new_trajectory_id,
        "cut_step_idx": cut_step_idx,
        "copied_steps": len(new_step_rows),
        "db_path": dst_db,
        "brain_copied": brain_copied,
        "resume_cmd": resume_cmd,
    }


# ==============================================================================
# Workspace Management & Migration
# ==============================================================================

def normalize_workspace_uri(path_str: str) -> str:
    clean = path_str.strip().strip("\"'").replace("\\", "/")
    if clean.startswith("file://"):
        return clean
    if not os.path.isabs(clean):
        clean = os.path.abspath(clean).replace("\\", "/")
    if not clean.startswith("/"):
        clean = "/" + clean
    return f"file://{clean}"


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
        return f"{secs}s ago"
    elif secs < 3600:
        return f"{secs // 60}m ago"
    elif secs < 86400:
        return f"{secs // 3600}h ago"
    elif secs < 86400 * 30:
        return f"{secs // 86400}d ago"
    else:
        return dt.strftime("%b %d")


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


def format_workspace_path(ws_uris: Optional[str]) -> str:
    if not ws_uris:
        return "~"
    try:
        uris = json.loads(ws_uris)
        paths = []
        home = os.path.expanduser("~").replace("\\", "/")
        for u in uris:
            p = u.replace("file://", "")
            if sys.platform == "win32" and p.startswith("/"):
                if len(p) >= 3 and p[2] == ":":
                    p = p[1:]
            if p.startswith(home):
                p = "~" + p[len(home):]
            paths.append(p)
        return ", ".join(paths) if paths else "~"
    except Exception:
        return "~"


def move_conversation_workspace(
    cid_or_query: str,
    target_workspace_path: str,
    summaries_db: str = DEFAULT_SUMMARIES_DB,
    conv_dir: str = DEFAULT_CONV_DIR
) -> Tuple[bool, str]:
    if not os.path.exists(summaries_db):
        return False, f"Conversation summaries DB not found at {summaries_db}"

    conn = sqlite3.connect(summaries_db)
    cur = conn.cursor()
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
        return False, f"Ambiguous query '{cid_or_query}'. Matches {len(matches)} conversations."

    cid, title, old_ws_json, raw_summary = matches[0]

    try:
        old_uris = json.loads(old_ws_json)
        old_uri_str = old_uris[0] if old_uris else "file:///C:/Users/X"
    except Exception:
        old_uri_str = "file:///C:/Users/X"

    new_uri_str = normalize_workspace_uri(target_workspace_path)
    new_ws_json = json.dumps([new_uri_str])

    old_uri_bytes = old_uri_str.encode("utf-8")
    new_uri_bytes = new_uri_str.encode("utf-8")

    # Update conversation_summaries.db
    if raw_summary:
        # Protobuf field 9 & 17
        fields = parse_proto_fields(raw_summary)
        new_fields = []
        for f_num, w_type, val in fields:
            if f_num == 9 and w_type == 2:
                sub = parse_proto_fields(val)
                new_sub = [(s_num, s_type, new_uri_bytes if s_num == 1 and s_val == old_uri_bytes else s_val) for s_num, s_type, s_val in sub]
                new_fields.append((f_num, w_type, serialize_proto_fields(new_sub)))
            elif f_num == 17 and w_type == 2:
                # Update trajectory blob
                t_fields = parse_proto_fields(val)
                new_t = []
                for tf_num, tw_type, tval in t_fields:
                    if tf_num == 1 and tw_type == 2:
                        tsub = parse_proto_fields(tval)
                        new_tsub = [(sn, st, new_uri_bytes if sn == 1 and sv == old_uri_bytes else sv) for sn, st, sv in tsub]
                        new_t.append((tf_num, tw_type, serialize_proto_fields(new_tsub)))
                    elif tf_num == 7 and tw_type == 2 and tval == old_uri_bytes:
                        new_t.append((tf_num, tw_type, new_uri_bytes))
                    else:
                        new_t.append((tf_num, tw_type, tval))
                new_fields.append((f_num, w_type, serialize_proto_fields(new_t)))
            else:
                new_fields.append((f_num, w_type, val))
        updated_raw = serialize_proto_fields(new_fields)
    else:
        updated_raw = raw_summary

    cur.execute(
        "UPDATE conversation_summaries SET workspace_uris = ?, raw_summary = ? WHERE conversation_id = ?",
        (new_ws_json, updated_raw, cid)
    )
    conn.commit()
    conn.close()

    # Update conversation's .db file
    conv_db = os.path.join(conv_dir, f"{cid}.db")
    if os.path.exists(conv_db):
        try:
            cconn = sqlite3.connect(conv_db)
            ccur = cconn.cursor()
            ccur.execute("SELECT id, data FROM trajectory_metadata_blob")
            for b_id, b_data in ccur.fetchall():
                if b_data:
                    t_fields = parse_proto_fields(b_data)
                    new_t = []
                    for tf_num, tw_type, tval in t_fields:
                        if tf_num == 1 and tw_type == 2:
                            tsub = parse_proto_fields(tval)
                            new_tsub = [(sn, st, new_uri_bytes if sn == 1 and sv == old_uri_bytes else sv) for sn, st, sv in tsub]
                            new_t.append((tf_num, tw_type, serialize_proto_fields(new_tsub)))
                        elif tf_num == 7 and tw_type == 2 and tval == old_uri_bytes:
                            new_t.append((tf_num, tw_type, new_uri_bytes))
                        else:
                            new_t.append((tf_num, tw_type, tval))
                    new_b_data = serialize_proto_fields(new_t)
                    ccur.execute("UPDATE trajectory_metadata_blob SET data = ? WHERE id = ?", (new_b_data, b_id))
            cconn.commit()
            cconn.close()
        except Exception as e:
            return True, f"Updated summary for '{title or cid}', but warning updating {cid}.db: {e}"

    old_lbl = get_workspace_label(old_ws_json)
    new_lbl = get_workspace_label(new_ws_json)
    return True, f"Successfully moved '{title or cid}' ({cid[:8]}) from '{old_lbl}' to '{new_lbl}' ({new_uri_str})"


def list_workspaces(summaries_db: str = DEFAULT_SUMMARIES_DB) -> List[Dict[str, Any]]:
    if not os.path.exists(summaries_db):
        return []
    conn = sqlite3.connect(summaries_db)
    cur = conn.cursor()
    cur.execute("SELECT workspace_uris, count(*) FROM conversation_summaries GROUP BY workspace_uris ORDER BY count(*) DESC")
    rows = cur.fetchall()
    conn.close()
    res = []
    for ws_json, cnt in rows:
        label = get_workspace_label(ws_json)
        path = format_workspace_path(ws_json)
        res.append({"label": label, "path": path, "count": cnt, "raw_json": ws_json})
    return res


# ==============================================================================
# Clipboard Helper
# ==============================================================================

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
