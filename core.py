#!/usr/bin/env python3
"""Core logic (no GUI): subtitle parsing, label schema, project storage, export. Standard library only."""
import csv
import hashlib
import html
import io
import json
import os
import re
import threading
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
PREFS_FILE = os.path.join(os.path.expanduser("~"), ".screenplay_annotator.json")

DEFAULT_SCHEMA = {
    "name": "screenplay-v0",
    "tasks": [
        {
            "id": "character_sentiment", "short": "CS", "name": "Character Sentiment",
            "description": "Viewer's perception of a character at this moment (temporal).",
            "per_character": True, "speaker_flag": True, "multi": True, "rationale": "required",
            "labels": [
                {"value": "Positive", "hint": "Sympathetic / moral", "color": "#2e9e5b"},
                {"value": "Negative", "hint": "Unsympathetic / compromised", "color": "#d64545"},
                {"value": "Neutral", "hint": "Ambiguous", "color": "#7f8794"},
            ],
        },
        {
            "id": "dialogue_sentiment", "short": "DS", "name": "Dialogue Sentiment",
            "description": "Private state of the speaker, not the calm/loud surface.",
            "per_character": False, "multi": True, "rationale": "required",
            "labels": [
                {"value": "Positive", "hint": "Genuine relief / affection", "color": "#2e9e5b"},
                {"value": "Negative", "hint": "Suppressed fear / resentment", "color": "#d64545"},
                {"value": "Neutral", "hint": "Detached / numb", "color": "#7f8794"},
            ],
        },
        {
            "id": "pragmatic_intent", "short": "PI", "name": "Pragmatic Intent",
            "description": "What the speaker is really doing with the sentence.",
            "per_character": False, "multi": True, "rationale": "required",
            "labels": [
                {"value": "Taarof", "hint": "Politeness masking intent", "color": "#8e5bd6"},
                {"value": "Sarcasm/Irony", "hint": "", "color": "#e08a1e"},
                {"value": "Evasion/Deception", "hint": "", "color": "#b5533c"},
                {"value": "Genuine/Direct", "hint": "", "color": "#1f9aa8"},
            ],
        },
        {
            "id": "offensive_language", "short": "OL", "name": "Offensive Language",
            "description": "Nuanced offensiveness taxonomy.",
            "per_character": False, "multi": True, "rationale": "required",
            "labels": [
                {"value": "Non-Offensive", "hint": "", "color": "#7f8794"},
                {"value": "Mild Insult", "hint": "e.g. \"Shameless\"", "color": "#d9a400"},
                {"value": "Severe Insult/Vulgarity", "hint": "e.g. \"You trash\"", "color": "#d64545"},
                {"value": "Threatening/Intimidating", "hint": "", "color": "#a3263d"},
                {"value": "Gaslighting/Manipulative", "hint": "", "color": "#8e5bd6"},
            ],
        },
    ],
}

LINE_TYPES = ("dialogue", "description")

def load_schema(path=None):
    if not path:
        return json.loads(json.dumps(DEFAULT_SCHEMA))
    with open(path, encoding="utf-8") as f:
        s = json.load(f)
    return normalize_schema(s)

def normalize_schema(s):
    if not isinstance(s, dict) or not isinstance(s.get("tasks"), list) or not s["tasks"]:
        raise ValueError("A task template must contain at least one task.")
    s = json.loads(json.dumps(s))
    s.setdefault("name", "Custom annotation")
    ids = set()
    for t in s["tasks"]:
        if not isinstance(t, dict) or not isinstance(t.get("id"), str) or not t["id"].strip():
            raise ValueError("Each task needs a nonempty id.")
        if t["id"] in ids:
            raise ValueError("duplicate task id: " + t["id"])
        ids.add(t["id"])
        t.setdefault("short", t["id"][:2].upper())
        t.setdefault("name", t["id"])
        t.setdefault("description", "")
        t.setdefault("per_character", False)
        t.setdefault("multi", False)
        t.setdefault("speaker_flag", False)
        t.setdefault("rationale", "required")
        if t["rationale"] not in ("required", "optional"):
            raise ValueError("Rationale must be required or optional: " + t["id"])
        if not isinstance(t.get("labels"), list) or not t["labels"]:
            raise ValueError("Add at least one label to task: " + t["name"])
        values = set()
        for i, lab in enumerate(t["labels"]):
            if isinstance(lab, str):
                lab = t["labels"][i] = {"value": lab}
            if not isinstance(lab, dict) or not isinstance(lab.get("value"), str) or not lab["value"].strip():
                raise ValueError("Labels must have a nonempty name in task: " + t["name"])
            if lab["value"] in values:
                raise ValueError("Duplicate label in %s: %s" % (t["name"], lab["value"]))
            values.add(lab["value"])
            lab.setdefault("hint", "")
            lab.setdefault("color", "#7f8794")
    return s

TIME_RE = re.compile(r"(?:(\d+):)?(\d+):(\d+)[.,](\d{1,3})")

def _secs(m):
    h, mi, s, ms = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0

def _clean(text):
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\{[^}]*\}", "", text)
    text = html.unescape(text)
    lines = [ln.strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)

def read_text(path, encoding=None):
    with open(path, "rb") as f:
        raw = f.read()
    if encoding:
        return raw.decode(encoding)
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "cp1256", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace")

def parse_srt_vtt(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    cues = []
    for block in re.split(r"\n\s*\n", text):
        lines = block.split("\n")
        for k, ln in enumerate(lines):
            if "-->" in ln:
                a, _, b = ln.partition("-->")
                ma, mb = TIME_RE.search(a), TIME_RE.search(b)
                if ma and mb:
                    cues.append((_secs(ma), _secs(mb), _clean("\n".join(lines[k + 1:]))))
                break
    return cues

def parse_ass(text):
    cues, fmt, in_events = [], None, False
    for ln in text.replace("\r", "").split("\n"):
        s = ln.strip()
        if s.startswith("["):
            in_events = s.lower() == "[events]"
            continue
        if not in_events:
            continue
        low = s.lower()
        if low.startswith("format:"):
            fmt = [x.strip().lower() for x in s[7:].split(",")]
        elif low.startswith("dialogue:") and fmt:
            d = dict(zip(fmt, s[9:].lstrip().split(",", len(fmt) - 1)))
            ma, mb = TIME_RE.search(d.get("start", "")), TIME_RE.search(d.get("end", ""))
            if ma and mb:
                body = d.get("text", "").replace("\\N", "\n").replace("\\n", "\n")
                cues.append((_secs(ma), _secs(mb), _clean(body)))
    return cues

def parse_subtitles(path, encoding=None):
    text = read_text(path, encoding)
    ext = os.path.splitext(path)[1].lower()
    if ext in (".ass", ".ssa") or "[Events]" in text[:5000]:
        cues = parse_ass(text)
    else:
        cues = parse_srt_vtt(text)
    cues = [c for c in cues if c[2]]
    cues.sort(key=lambda c: (c[0], c[1]))
    return cues

def align(primary, secondary):
    out = []
    for ps, pe, _ in primary:
        pd = max(pe - ps, 0.05)
        parts = []
        for ss, se, st in secondary:
            if ss > pe + 0.5:
                break
            ov = min(pe, se) - max(ps, ss)
            if ov > 0 and ov / min(pd, max(se - ss, 0.05)) >= 0.4:
                parts.append(st.replace("\n", " "))
        out.append(" ".join(parts))
    return out

def _expand(p):
    p = (p or "").strip().strip('"').strip("'")
    return os.path.abspath(os.path.expanduser(p)) if p else ""

def _safe(name):
    return re.sub(r"[^\w\-.]+", "_", name, flags=re.UNICODE).strip("._") or "annotator"

def _schema_core(schema):
    s = json.loads(json.dumps(schema))
    for t in s.get("tasks", []):
        t.pop("multi", None)
        t.pop("speaker_flag", None)
    return s

class Project:
    def __init__(self, cfg):
        self.lock = threading.RLock()
        self.cfg = {
            "movie": _expand(cfg.get("movie")),
            "subs": _expand(cfg.get("subs")),
            "subs2": _expand(cfg.get("subs2")),
            "lang1": (cfg.get("lang1") or "fa").strip(),
            "lang2": (cfg.get("lang2") or "en").strip(),
            "annotator": (cfg.get("annotator") or "annotator1").strip(),
            "schema": _expand(cfg.get("schema")),
            "outdir": _expand(cfg.get("outdir")),
            "encoding": (cfg.get("encoding") or "").strip(),
        }
        c = self.cfg
        if not c["subs"] or not os.path.isfile(c["subs"]):
            raise ValueError("Subtitle file not found: %r" % c["subs"])
        if c["movie"] and not os.path.isfile(c["movie"]):
            raise ValueError("Movie file not found: %r" % c["movie"])
        if c["subs2"] and not os.path.isfile(c["subs2"]):
            raise ValueError("Second subtitle file not found: %r" % c["subs2"])
        self.schema = load_schema(c["schema"] or None)
        enc = c["encoding"] or None
        cues = parse_subtitles(c["subs"], enc)
        if not cues:
            raise ValueError("No subtitle cues could be parsed from " + c["subs"])
        t2 = align(cues, parse_subtitles(c["subs2"], enc)) if c["subs2"] else [""] * len(cues)
        self.lines = []
        for i, ((s, e, t1), x2) in enumerate(zip(cues, t2), 1):
            uid = hashlib.sha1(("%d|%.3f|%s" % (i, s, t1)).encode("utf-8")).hexdigest()[:10]
            self.lines.append({"id": i, "uid": uid, "start": s, "end": e, "t1": t1, "t2": x2})
        outdir = c["outdir"] or os.path.join(os.path.dirname(c["subs"]), "annotations")
        os.makedirs(outdir, exist_ok=True)
        base = os.path.splitext(os.path.basename(c["movie"] or c["subs"]))[0]
        self.path = os.path.join(outdir, "%s.annotations.json" % _safe(base))
        self.items, self.warnings = {}, []
        self._load()

    def _load(self):
        if not os.path.isfile(self.path):
            return
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("schema") != self.schema["name"] or (data.get("task_schema") is not None and
                                                         _schema_core(data["task_schema"]) != _schema_core(self.schema)):
            raise ValueError("Saved annotations use a different task template. Select the original template, "
                             "or choose a different annotator name or output folder for the new tasks.")
        uids = {l["id"]: l["uid"] for l in self.lines}
        stale = 0
        for k, v in data.get("items", {}).items():
            i = int(k)
            if i not in uids:
                stale += 1
                continue
            if v.get("uid") != uids[i]:
                stale += 1
                
            tasks_data = v.get("tasks", {})
            sentences_data = v.get("sentences", {})
            if tasks_data and not sentences_data:
                sentences_data = {"0": self._upgrade_tasks(tasks_data)}
            else:
                sentences_data = {sk: self._upgrade_tasks(sv) for sk, sv in sentences_data.items()}

            self.items[i] = {
                "uid": uids[i],
                "sentences": sentences_data,
                "line_type": v.get("line_type") if v.get("line_type") in LINE_TYPES else "dialogue",
                "last_edited_by": v.get("last_edited_by", ""),
                "last_edited_at": v.get("last_edited_at", "")
            }
        if stale:
            self.warnings.append("%d saved annotation(s) did not match the current subtitle file "
                                 "(different file or edited text) - please review them." % stale)

    def _upgrade_tasks(self, tasks):
        by_id = {t["id"]: t for t in self.schema["tasks"]}
        out = {}
        for tid, val in (tasks or {}).items():
            t = by_id.get(tid)
            rows = val if isinstance(val, list) else [val]
            rows = [dict(r) for r in rows if isinstance(r, dict)]
            for r in rows:
                if t and t["multi"] and not isinstance(r.get("label"), list):
                    r["label"] = [r["label"]] if r.get("label") else []
                if t and t["per_character"] and t.get("speaker_flag"):
                    r.setdefault("is_speaker", False)
            out[tid] = rows if isinstance(val, list) else (rows[0] if rows else val)
        return out

    def _write(self):
        data = {"version": 1, "annotator": self.cfg["annotator"], "schema": self.schema["name"],
                "task_schema": self.schema,
                "movie": os.path.basename(self.cfg["movie"]), "subs": os.path.basename(self.cfg["subs"]),
                "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "items": {str(i): v for i, v in sorted(self.items.items())}}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def validate(self, tasks):
        out = {}
        by_id = {t["id"]: t for t in self.schema["tasks"]}
        for tid, val in (tasks or {}).items():
            t = by_id.get(tid)
            if t is None:
                raise ValueError("unknown task: %s" % tid)
            allowed = {l["value"] for l in t["labels"]}

            def one(e, need_char):
                lab = e.get("label", [] if t["multi"] else "")
                if t["multi"]:
                    lab = [x for x in (lab if isinstance(lab, list) else [lab]) if x]
                    bad = [x for x in lab if x not in allowed]
                else:
                    lab = lab or ""
                    bad = [lab] if lab and lab not in allowed else []
                if bad:
                    raise ValueError("label %r not in task %s" % (bad[0], tid))
                r = {"label": lab, "rationale": str(e.get("rationale", "")).strip()[:5000]}
                if need_char:
                    r = {"character": str(e.get("character", "")).strip()[:200], **r}
                    if t.get("speaker_flag"):
                        r["is_speaker"] = bool(e.get("is_speaker", False))
                return r

            if t["per_character"]:
                rows = [one(e, True) for e in (val if isinstance(val, list) else [])]
                rows = [r for r in rows if r["character"] or r["label"] or r["rationale"]]
                if rows:
                    out[tid] = rows
            else:
                r = one(val if isinstance(val, dict) else {}, False)
                if r["label"] or r["rationale"]:
                    out[tid] = r
        return out

    def set_annotation(self, line_id, sentence_idx, tasks, line_type="dialogue", edited_by=None, write=True):
        with self.lock:
            if not 1 <= line_id <= len(self.lines):
                raise ValueError("bad line id")

            if line_type not in LINE_TYPES:
                raise ValueError("unknown line type: %s" % line_type)
            clean = self.validate(tasks)
            previous = self.items.get(line_id, {})
            
            old_sentences = previous.get("sentences", {})
            old_tasks = old_sentences.get(str(sentence_idx), {})
            old_type = previous.get("line_type", "dialogue")

            if old_tasks != clean or old_type != line_type:
                last_edited_by = edited_by or self.cfg["annotator"]
                last_edited_at = datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                )
            else:
                last_edited_by = previous.get("last_edited_by", "")
                last_edited_at = previous.get("last_edited_at", "")
                
            new_sentences = dict(old_sentences)
            if clean:
                new_sentences[str(sentence_idx)] = clean
            else:
                new_sentences.pop(str(sentence_idx), None)

            if new_sentences or last_edited_at or line_type != "dialogue":
                self.items[line_id] = {
                    "uid": self.lines[line_id - 1]["uid"],
                    "sentences": new_sentences,
                    "line_type": line_type,
                    "last_edited_by": last_edited_by,
                    "last_edited_at": last_edited_at,
                }
            else:
                self.items.pop(line_id, None)

            if write:
                self._write()

    def import_preannotations(self, records, edited_by="AI pre-annotation", overwrite=False):
        res = {"imported": 0, "skipped_existing": 0, "empty": 0, "unmatched": [], "errors": []}
        with self.lock:
            for rec in records:
                if not isinstance(rec, dict):
                    res["errors"].append("not an object: %r" % (rec,))
                    continue
                rid = rec.get("id")
                start = rec.get("start")
                if isinstance(start, str):
                    m = TIME_RE.search(start)
                    start = _secs(m) if m else None
                elif not isinstance(start, (int, float)) or isinstance(start, bool):
                    start = None
                if start is not None:
                    cands = [l for l in self.lines if abs(l["start"] - start) <= 0.06]
                    if len(cands) > 1 and isinstance(rid, int):
                        cands.sort(key=lambda l: abs(l["id"] - rid))
                    line = cands[0] if cands else None
                elif isinstance(rid, int) and 1 <= rid <= len(self.lines):
                    line = self.lines[rid - 1]
                else:
                    line = None
                if line is None:
                    res["unmatched"].append(rid if rid is not None else rec.get("start"))
                    continue
                lid = line["id"]
                ltype = rec.get("line_type") or "dialogue"
                sentences = {} if ltype == "description" else (rec.get("sentences") or {"0": rec.get("annotations", {})})
                if ltype == "dialogue" and not sentences:
                    res["empty"] += 1
                    continue
                prev = self.items.get(lid)
                if prev and (prev.get("sentences") or prev.get("line_type") == "description") and not overwrite:
                    res["skipped_existing"] += 1
                    continue
                try:
                    for s_idx, tasks in sentences.items():
                        self.set_annotation(lid, int(s_idx), tasks, ltype, edited_by=edited_by, write=False)
                    res["imported"] += 1
                except ValueError as e:
                    res["errors"].append("line %d: %s" % (lid, e))
            if res["imported"]:
                self._write()
        return res

    def records(self, include_all=False):
        c, l1, l2 = self.cfg, self.cfg["lang1"], self.cfg["lang2"]
        for ln in self.lines:
            it = self.items.get(ln["id"])
            if not it and not include_all:
                continue
            rec = {"id": ln["id"], "uid": ln["uid"], "start": round(ln["start"], 3),
                   "end": round(ln["end"], 3), "text_" + l1: ln["t1"]}
            if c["subs2"]:
                rec["text_" + l2] = ln["t2"]
            rec["annotator"] = c["annotator"]
            rec["movie"] = os.path.basename(c["movie"]) if c["movie"] else ""
            rec["line_type"] = it.get("line_type", "dialogue") if it else "dialogue"
            rec["sentences"] = it["sentences"] if it and rec["line_type"] == "dialogue" else {}
            yield rec

    def export(self, fmt, include_all=False):
        recs = list(self.records(include_all))
        if fmt == "jsonl":
            return "\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n", "application/x-ndjson"
        if fmt == "json":
            return json.dumps(recs, ensure_ascii=False, indent=1), "application/json"
        if fmt == "csv":
            buf = io.StringIO()
            base = ["id", "start", "end", "text_" + self.cfg["lang1"]] + \
                   (["text_" + self.cfg["lang2"]] if self.cfg["subs2"] else []) + ["annotator", "line_type", "sentence_idx"]
            cols = base + [x for t in self.schema["tasks"] for x in (t["id"] + "_label", t["id"] + "_rationale")]
            w = csv.DictWriter(buf, cols, extrasaction="ignore")
            w.writeheader()
            for r in recs:
                sentences = r.get("sentences", {"0": {}})
                if not sentences and r["line_type"] == "dialogue":
                    sentences = {"0": {}}
                for sent_idx, tasks in sentences.items():
                    row = {k: r.get(k, "") for k in base}
                    row["sentence_idx"] = sent_idx
                    for t in self.schema["tasks"]:
                        v = tasks.get(t["id"])
                        if v is None:
                            continue
                        if t["per_character"]:
                            def labs(x):
                                return "/".join(x["label"]) if isinstance(x["label"], list) else x["label"]
                            row[t["id"] + "_label"] = "; ".join(
                                "%s%s=%s" % (x["character"], " [speaker]" if x.get("is_speaker") else "", labs(x)) for x in v)
                            row[t["id"] + "_rationale"] = " | ".join(x["rationale"] for x in v)
                        else:
                            lab = v["label"]
                            row[t["id"] + "_label"] = "; ".join(lab) if isinstance(lab, list) else lab
                            row[t["id"] + "_rationale"] = v["rationale"]
                    w.writerow(row)
            return "﻿" + buf.getvalue(), "text/csv"
        raise ValueError("unknown format")


def entry_state(task, e):
    if not e:
        return "empty"
    rows = e if task["per_character"] else [e]
    rows = [r for r in rows if r.get("label") or r.get("rationale", "").strip() or r.get("character", "").strip()]
    if not rows:
        return "empty"
    for r in rows:
        if task["per_character"] and not r.get("character", "").strip():
            return "incomplete"
        if not r.get("label"):
            return "incomplete"
        if task["rationale"] == "required" and not r.get("rationale", "").strip():
            return "incomplete"
    return "ok"

def is_description(project, line_id):
    return (project.items.get(line_id) or {}).get("line_type") == "description"

def line_state(project, line_id):
    if is_description(project, line_id):
        return True, False
    sentences = (project.items.get(line_id) or {}).get("sentences", {})
    any_, inc = False, False
    if not sentences:
        return False, False
    for tasks in sentences.values():
        for t in project.schema["tasks"]:
            s = entry_state(t, tasks.get(t["id"]))
            if s != "empty":
                any_ = True
            if s == "incomplete":
                inc = True
    return any_, inc

def parse_preannotation_text(text):
    text = text.strip().lstrip("\ufeff")
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    try:
        data = json.loads(text)
    except ValueError:
        data = []
        for ln in text.splitlines():
            ln = ln.strip().rstrip(",")
            if ln:
                data.append(json.loads(ln))
    if isinstance(data, dict):
        for k in ("lines", "annotations", "items", "records"):
            if isinstance(data.get(k), list):
                return data[k]
        raise ValueError("Expected a list of line records.")
    if not isinstance(data, list):
        raise ValueError("Expected a list of line records.")
    return data

def load_prefs():
    try:
        with open(PREFS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_prefs(cfg):
    try:
        with open(PREFS_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
    except OSError:
        pass
