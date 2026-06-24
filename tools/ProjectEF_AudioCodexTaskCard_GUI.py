#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import queue
import re
import subprocess
import threading
import time
import tkinter as tk
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tkinter import messagebox, ttk


APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
DEFAULT_UNITY_ROOT = Path(r"D:\EF New\Client\TargetProject")
REPORT_DIR = ROOT / "Reports" / "CodexTaskCards"

BG = "#0f1722"
PANEL = "#151f2d"
PANEL_2 = "#1b2636"
CARD = "#202c3d"
INK = "#edf4ff"
MUTED = "#9fb0c6"
LINE = "#334258"
ACCENT = "#4db6ff"
GOOD = "#55d68a"
WARN = "#ffcc66"
BAD = "#ff6b6b"

ASSET_EXTENSIONS = {
    ".prefab",
    ".playable",
    ".anim",
    ".asset",
    ".controller",
    ".overridecontroller",
    ".fbx",
    ".mat",
}
IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".webp",
    ".tif",
    ".tiff",
}
TEXT_EXTENSIONS = {
    ".prefab",
    ".playable",
    ".anim",
    ".asset",
    ".controller",
    ".overridecontroller",
    ".meta",
    ".cs",
}
MAX_QUERY_MATCHES = 120
MAX_DIR_ASSETS = 260
MAX_EVIDENCE_LINES = 40
MAX_REFERENCES = 40


PATTERNS: list[tuple[str, str, str]] = [
    ("water_splash_config", "m_splashConfigList", "WaterInteractWithSplash splash config list"),
    ("enter_water_audio", "m_enterWaterAudioName", "Enter-water Wwise Event field"),
    ("leave_water_audio", "m_leaveWaterAudioName", "Leave-water Wwise Event field"),
    ("audio_switch", "m_audioSwichParameters", "Audio switch parameter list"),
    ("fish_size_switch", "Fish_Size", "Fish size Switch"),
    ("wwise_helper", "WwiseAudioHelper", "WwiseAudioHelper component or reference"),
    ("animation_wwise_event", "PlayAnimationWwiseEvent", "AnimationEvent Wwise bridge"),
    ("animation_events", "m_Events:", "AnimationClip event list"),
    ("timeline_director", "PlayableDirector:", "PlayableDirector component"),
    ("playable_asset", "m_PlayableAsset:", "Timeline asset binding"),
    ("timeline_track", "m_Tracks:", "Timeline track list"),
    ("signal", "Simple Signal Emitter", "Timeline simple signal marker"),
    ("ak_event", "AkEvent", "Wwise Timeline/Event object"),
    ("wwise_word", "Wwise", "Wwise text reference"),
    ("audio_name", "AudioName", "Serialized audio-name field"),
    ("sound_event", "SoundEvent", "Serialized sound-event field"),
    ("ui_state_audio", "UIState", "UI state/controller reference"),
    ("button_audio", "PressedAudioName", "UI pressed audio field"),
    ("particle_system", "ParticleSystem:", "Unity ParticleSystem VFX"),
    ("visual_effect", "VisualEffect", "Unity VFX Graph/VisualEffect reference"),
    ("vfx_path", "Pfb_Vfx", "VFX prefab/path reference"),
]


@dataclass
class EvidenceLine:
    line: int
    label: str
    text: str


@dataclass
class ReferenceHit:
    path: str
    line: int
    text: str


@dataclass
class Candidate:
    path: str
    unity_path: str
    kind: str
    score: int
    reasons: list[str] = field(default_factory=list)
    evidence: list[EvidenceLine] = field(default_factory=list)
    references: list[ReferenceHit] = field(default_factory=list)
    guid: str = ""
    size_bytes: int = 0
    recommendation: str = ""


@dataclass
class TaskCard:
    title: str
    intent: str
    unity_root: str
    inputs: list[str]
    events: list[str]
    notes: str
    generated_at: str
    source_grade: str
    candidates: list[Candidate]
    guardrails: list[str]
    next_codex_actions: list[str]
    md_path: str = ""
    json_path: str = ""


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def safe_slug(value: str, fallback: str = "AudioTask") -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("_")
    return (slug or fallback)[:80]


def split_input_lines(value: str) -> list[str]:
    lines: list[str] = []
    for raw in value.replace(";", "\n").splitlines():
        item = raw.strip().strip('"').strip("'")
        if item:
            lines.append(item)
    return lines


def unity_assets_root(unity_root: Path) -> Path:
    return unity_root / "Assets"


def to_unity_path(path: Path, unity_root: Path) -> str:
    try:
        rel = path.resolve().relative_to(unity_root.resolve())
        return rel.as_posix()
    except Exception:
        return str(path)


def read_text(path: Path, max_bytes: int = 8_000_000) -> str:
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return ""
    try:
        size = path.stat().st_size
        if size > max_bytes:
            raw = path.read_bytes()[:max_bytes]
            return raw.decode("utf-8", errors="ignore")
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def read_guid(path: Path) -> str:
    meta = Path(str(path) + ".meta")
    if not meta.exists():
        return ""
    try:
        for line in meta.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("guid:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        return ""
    return ""


def run_rg(args: list[str], cwd: Path, timeout: int = 10, max_lines: int | None = None) -> list[str]:
    try:
        if max_lines is not None:
            process = subprocess.Popen(
                ["rg", *args],
                cwd=str(cwd),
                text=True,
                encoding="utf-8",
                errors="ignore",
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            output: queue.Queue[str] = queue.Queue()

            def read_stdout() -> None:
                if process.stdout is None:
                    return
                for line in process.stdout:
                    output.put(line.rstrip("\r\n"))

            reader = threading.Thread(target=read_stdout, daemon=True)
            reader.start()
            lines: list[str] = []
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    line = output.get(timeout=0.05)
                except queue.Empty:
                    if process.poll() is not None and output.empty():
                        break
                    continue
                lines.append(line)
                if len(lines) >= max_lines:
                    process.kill()
                    break
            if process.poll() is None:
                process.kill()
            return lines

        completed = subprocess.run(
            ["rg", *args],
            cwd=str(cwd),
            text=True,
            encoding="utf-8",
            errors="ignore",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        if completed.returncode not in (0, 1):
            return []
        return completed.stdout.splitlines()
    except Exception:
        return []


def is_asset_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in ASSET_EXTENSIONS


def collect_from_directory(path: Path) -> list[Path]:
    matches: list[Path] = []
    for child in path.rglob("*"):
        if is_asset_file(child):
            matches.append(child)
            if len(matches) >= MAX_DIR_ASSETS:
                break
    return matches


def search_assets_by_query(query: str, unity_root: Path) -> list[Path]:
    assets = unity_assets_root(unity_root)
    if not assets.exists():
        return []
    query_lower = query.lower().replace("\\", "/")
    lines = run_rg(["--files", str(assets)], unity_root, timeout=12)
    matches: list[Path] = []
    for line in lines:
        normalized = line.replace("\\", "/")
        path = Path(line)
        if path.suffix.lower() == ".meta":
            continue
        if path.suffix.lower() not in ASSET_EXTENSIONS:
            continue
        if query_lower in normalized.lower() or query_lower in path.name.lower():
            matches.append(path)
            if len(matches) >= MAX_QUERY_MATCHES:
                break
    return matches


def resolve_input_to_paths(raw: str, unity_root: Path) -> list[Path]:
    candidate = Path(raw)
    if candidate.exists():
        if candidate.is_dir():
            return collect_from_directory(candidate)
        return [candidate]

    normalized = raw.replace("\\", "/").lstrip("/")
    if normalized.lower().startswith("assets/"):
        path = unity_root / normalized
        if path.exists():
            if path.is_dir():
                return collect_from_directory(path)
            return [path]

    return search_assets_by_query(raw, unity_root)


def compact_line(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def evidence_from_text(text: str) -> tuple[list[EvidenceLine], set[str]]:
    evidence: list[EvidenceLine] = []
    matched_labels: set[str] = set()
    lower_patterns = [(key, needle.lower(), label) for key, needle, label in PATTERNS]
    for line_no, line in enumerate(text.splitlines(), 1):
        lowered = line.lower()
        for key, needle, label in lower_patterns:
            if needle in lowered:
                matched_labels.add(key)
                if len(evidence) < MAX_EVIDENCE_LINES:
                    evidence.append(EvidenceLine(line_no, label, compact_line(line)))
                break
    return evidence, matched_labels


def classify(path: Path, text: str, labels: set[str]) -> tuple[str, list[str], int]:
    suffix = path.suffix.lower()
    reasons: list[str] = []
    score = 0

    if "enter_water_audio" in labels or "leave_water_audio" in labels or "water_splash_config" in labels:
        reasons.append("Contains WaterInteractWithSplash serialized splash/audio fields.")
        score += 85
        return "Prefab Component Field / Water Splash", reasons, score

    if suffix == ".playable":
        reasons.append("Timeline playable asset.")
        score += 45
        if "signal" in labels:
            reasons.append("Contains Timeline signal markers.")
            score += 10
        if "ak_event" in labels or "wwise_word" in labels:
            reasons.append("Contains Wwise/Ak Timeline evidence.")
            score += 30
        return "Timeline", reasons, score

    if suffix == ".anim":
        reasons.append("AnimationClip asset.")
        score += 35
        if "animation_wwise_event" in labels:
            reasons.append("Contains PlayAnimationWwiseEvent keys.")
            score += 45
        elif "animation_events" in labels:
            reasons.append("Contains AnimationEvent section.")
            score += 10
        return "AnimationClip", reasons, score

    if suffix == ".prefab":
        if "timeline_director" in labels or "playable_asset" in labels:
            reasons.append("Prefab owns a PlayableDirector / Timeline binding.")
            score += 55
            return "Timeline Prefab", reasons, score
        if "particle_system" in labels or "visual_effect" in labels or "vfx_path" in labels:
            reasons.append("Prefab contains VFX/ParticleSystem evidence.")
            score += 30
            if "wwise_helper" in labels or "ak_event" in labels or "wwise_word" in labels:
                reasons.append("VFX prefab also contains Wwise/audio evidence.")
                score += 35
            return "VFX Prefab", reasons, score
        if "wwise_helper" in labels or "wwise_word" in labels or "ak_event" in labels:
            reasons.append("Prefab contains Wwise/audio component or text evidence.")
            score += 55
            return "Audio Prefab", reasons, score
        if "ui_state_audio" in labels or "button_audio" in labels or "audio_name" in labels:
            reasons.append("Prefab contains UI/audio serialized fields.")
            score += 50
            return "UI Audio Prefab", reasons, score
        reasons.append("Prefab asset; no strong audio field found in first scan.")
        score += 10
        return "Prefab", reasons, score

    if suffix == ".fbx":
        reasons.append("FBX model/animation source asset.")
        score += 8
        return "FBX Source", reasons, score

    if suffix == ".asset":
        if "wwise_word" in labels or "ak_event" in labels or "audio_name" in labels or "sound_event" in labels:
            reasons.append("ScriptableObject/asset contains audio-like evidence.")
            score += 40
            return "Audio ScriptableObject", reasons, score
        reasons.append("ScriptableObject/asset; no strong audio field found.")
        score += 8
        return "Asset", reasons, score

    reasons.append("Unclassified Unity asset.")
    return "Unknown", reasons, score


def recommendation_for(kind: str, labels: set[str]) -> str:
    if kind == "Prefab Component Field / Water Splash":
        return (
            "Configure the serialized component fields on the owning prefab. Preserve existing "
            "Fish_Size Switch rows unless the task explicitly changes the Unity contract."
        )
    if kind == "Timeline":
        return (
            "Inspect the Timeline tracks and markers. If the cue is cinematic timing, configure "
            "the project Wwise Timeline track/signal path instead of AnimationEvent."
        )
    if kind == "Timeline Prefab":
        return (
            "Use this prefab as the preview/root entry. Follow its PlayableDirector to the Timeline "
            "asset and bound runtime objects before writing audio."
        )
    if kind == "AnimationClip":
        return (
            "Use AnimationEvent only when the sound is tied to the motion and should fire whenever "
            "this clip plays. Analyze motion/contact frames before writing keys."
        )
    if kind == "VFX Prefab":
        if "wwise_word" in labels or "ak_event" in labels or "wwise_helper" in labels:
            return "This VFX prefab has audio evidence; inspect component fields before editing."
        return (
            "Treat as visual evidence by default. Trace the spawning Timeline/prefab/component; "
            "do not add audio to the VFX prefab unless the project pattern requires it."
        )
    if kind in {"Audio Prefab", "UI Audio Prefab", "Audio ScriptableObject"}:
        return "Inspect and configure the existing serialized audio fields/components; avoid runtime logic changes."
    return "Use as context; find the real owner that triggers or configures the sound."


def reference_hits_for(path: Path, unity_root: Path, guid: str) -> list[ReferenceHit]:
    assets = unity_assets_root(unity_root)
    if not assets.exists():
        return []
    searches: list[str] = []
    if guid:
        searches.append(guid)
    unity_path = to_unity_path(path, unity_root)
    if unity_path.startswith("Assets/"):
        searches.append(unity_path)

    hits: list[ReferenceHit] = []
    seen: set[tuple[str, int, str]] = set()
    globs = [
        "--glob",
        "*.prefab",
        "--glob",
        "*.playable",
        "--glob",
        "*.anim",
        "--glob",
        "*.asset",
        "--glob",
        "*.controller",
        "--glob",
        "*.overrideController",
    ]
    for needle in searches:
        lines = run_rg(
            ["--fixed-strings", "-n", *globs, needle, str(assets)],
            unity_root,
            timeout=12,
            max_lines=MAX_REFERENCES,
        )
        for raw in lines:
            match = re.match(r"^(.*):(\d+):(.*)$", raw)
            if not match:
                continue
            hit_path, line_text, text = match.groups()
            line_no = int(line_text)
            key = (hit_path, line_no, text)
            if key in seen:
                continue
            seen.add(key)
            hits.append(ReferenceHit(str(Path(hit_path)), line_no, compact_line(text)))
            if len(hits) >= MAX_REFERENCES:
                return hits
    return hits


def scan_candidate(path: Path, unity_root: Path, include_references: bool = True) -> Candidate:
    text = read_text(path)
    evidence, labels = evidence_from_text(text)
    kind, reasons, score = classify(path, text, labels)
    guid = read_guid(path)
    references = reference_hits_for(path, unity_root, guid) if include_references else []
    if references:
        reasons.append(f"Referenced by {len(references)} Unity asset line(s) in the static scan.")
        score += min(20, len(references))
    elif not include_references:
        reasons.append("Reference scan skipped because this request matched many assets; narrow to one asset for owner tracing.")
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return Candidate(
        path=str(path),
        unity_path=to_unity_path(path, unity_root),
        kind=kind,
        score=score,
        reasons=reasons,
        evidence=evidence,
        references=references,
        guid=guid,
        size_bytes=size,
        recommendation=recommendation_for(kind, labels),
    )


def scan_inputs(inputs: list[str], unity_root: Path) -> list[Candidate]:
    resolved: list[Path] = []
    seen: set[str] = set()
    for raw in inputs:
        for path in resolve_input_to_paths(raw, unity_root):
            try:
                key = str(path.resolve()).lower()
            except Exception:
                key = str(path).lower()
            if key not in seen and is_asset_file(path):
                seen.add(key)
                resolved.append(path)

    include_references = len(resolved) <= 35
    candidates = [scan_candidate(path, unity_root, include_references=include_references) for path in resolved]
    candidates.sort(key=lambda item: (-item.score, item.kind, item.unity_path.lower()))
    return candidates


def guardrails() -> list[str]:
    return [
        "Do not modify WwiseAudioHelper, WwiseProvider, AudioManager4Wwise, GameManager, or runtime audio loading logic.",
        "Prefer existing project preview/test flows over replacing audio initialization.",
        "Before writing versioned Unity/Wwise assets, list the exact target files and intended field/key changes.",
        "Treat static scan evidence as planning evidence; runtime playback still needs Unity/Wwise verification.",
        "For VFX prefabs, trace the owner/spawner first; do not add audio to visual prefabs by default.",
    ]


def has_image_inputs(inputs: list[str] | None) -> bool:
    return any(Path(str(item)).suffix.lower() in IMAGE_EXTENSIONS for item in inputs or [])


def next_actions_for(candidates: list[Candidate], inputs: list[str] | None = None) -> list[str]:
    if not candidates:
        actions = [
            "Analyze the user notes and any attached screenshot/image paths first.",
            "Ask for a more exact Unity asset path/name only if the screenshot and notes are insufficient.",
        ]
        if has_image_inputs(inputs):
            actions.append("Use the screenshot as the primary evidence; manually identify visible Unity folder/object names before scanning again.")
        else:
            actions.append("Run a wider static search from any visible name, system, or feature term.")
        return actions
    top = candidates[0]
    actions = [
        "Review the candidate list and choose the real configuration owner, not just the visible asset name.",
        "Cross-check requested Wwise Events against Wwise object design and Switch/State requirements.",
    ]
    if top.kind == "Prefab Component Field / Water Splash":
        actions.append("For WaterInteractWithSplash, compare Small/Medium/Large rows and preserve Fish_Size Switch values.")
        actions.append("If approved, write only the event-name fields on the owning prefab and open the existing preview route.")
    elif top.kind in {"Timeline", "Timeline Prefab"}:
        actions.append("Open/inspect the Timeline and decide whether Wwise Timeline Track, Signal, or existing component fields own the cue.")
        actions.append("If approved, add/modify Timeline cues using existing project Wwise Timeline support.")
    elif top.kind == "AnimationClip":
        actions.append("Analyze motion/contact frames before adding AnimationEvent Wwise keys.")
        actions.append("Preview with the existing Animation Wwise Event tool before applying.")
    elif top.kind == "VFX Prefab":
        actions.append("Trace references to find the spawning prefab/timeline/component that should own the audio trigger.")
    return actions


def source_grade_for(candidates: list[Candidate], inputs: list[str] | None = None) -> str:
    if not candidates:
        if has_image_inputs(inputs):
            return "SourceGrade D - screenshot/request-only card; Codex must inspect image evidence before choosing Unity targets."
        return "SourceGrade C - no matching Unity assets found; useful only as a request stub."
    if candidates[0].score >= 80:
        return "SourceGrade B - strong static Unity evidence, but runtime preview/WAAPI verification is still needed."
    return "SourceGrade C - static candidates found, but true owner/timing needs Codex review."


def build_task_card(title: str, intent: str, unity_root: Path, inputs: list[str], events: list[str], notes: str) -> TaskCard:
    candidates = scan_inputs(inputs, unity_root)
    return TaskCard(
        title=title.strip() or "ProjectEF audio configuration task",
        intent=intent.strip() or "auto",
        unity_root=str(unity_root),
        inputs=inputs,
        events=events,
        notes=notes.strip(),
        generated_at=dt.datetime.now().isoformat(timespec="seconds"),
        source_grade=source_grade_for(candidates, inputs),
        candidates=candidates,
        guardrails=guardrails(),
        next_codex_actions=next_actions_for(candidates, inputs),
    )


def render_markdown(card: TaskCard) -> str:
    lines: list[str] = []
    lines.append(f"# Codex Audio Configuration Task Card - {card.title}")
    lines.append("")
    lines.append("## Paste Into Codex")
    lines.append("")
    lines.append("```text")
    lines.append("Please analyze this ProjectEF audio configuration task card.")
    lines.append("Use the scanned evidence to decide the real Unity configuration owner and the safest write path.")
    lines.append("Do not change runtime/Wwise bottom-layer logic. Before writing assets, state the exact files and fields/keys.")
    lines.append("After configuration, open the appropriate existing preview flow when possible.")
    lines.append("```")
    lines.append("")
    lines.append("## Task")
    lines.append("")
    lines.append(f"- Title: `{card.title}`")
    lines.append(f"- Intent: `{card.intent}`")
    lines.append(f"- Unity root: `{card.unity_root}`")
    lines.append(f"- Generated: `{card.generated_at}`")
    lines.append(f"- Source quality: {card.source_grade}")
    lines.append("")
    lines.append("## Inputs")
    lines.append("")
    for item in card.inputs or ["(none)"]:
        lines.append(f"- `{item}`")
    lines.append("")
    image_inputs = [item for item in card.inputs if Path(str(item)).suffix.lower() in IMAGE_EXTENSIONS]
    if image_inputs:
        lines.append("## Screenshot / Image Evidence")
        lines.append("")
        for item in image_inputs:
            lines.append(f"- `{item}`")
            if Path(item).is_absolute():
                lines.append(f"![screenshot]({item})")
        lines.append("")
    lines.append("## Requested / Candidate Wwise Events")
    lines.append("")
    for event in card.events or ["(not provided)"]:
        lines.append(f"- `{event}`")
    lines.append("")
    if card.notes:
        lines.append("## User Notes")
        lines.append("")
        lines.append(card.notes)
        lines.append("")
    lines.append("## Guardrails")
    lines.append("")
    for item in card.guardrails:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Candidate Unity Assets")
    lines.append("")
    if not card.candidates:
        lines.append("No matching Unity assets were found.")
    for idx, candidate in enumerate(card.candidates, 1):
        lines.append(f"### {idx}. {candidate.unity_path or candidate.path}")
        lines.append("")
        lines.append(f"- Kind: `{candidate.kind}`")
        lines.append(f"- Score: `{candidate.score}`")
        lines.append(f"- Path: `{candidate.path}`")
        if candidate.guid:
            lines.append(f"- GUID: `{candidate.guid}`")
        lines.append(f"- Recommendation: {candidate.recommendation}")
        lines.append("")
        if candidate.reasons:
            lines.append("Reasons:")
            for reason in candidate.reasons:
                lines.append(f"- {reason}")
            lines.append("")
        if candidate.evidence:
            lines.append("Evidence:")
            for ev in candidate.evidence[:12]:
                lines.append(f"- `{ev.line}` {ev.label}: `{ev.text}`")
            if len(candidate.evidence) > 12:
                lines.append(f"- ... {len(candidate.evidence) - 12} more evidence line(s)")
            lines.append("")
        if candidate.references:
            lines.append("References:")
            for ref in candidate.references[:10]:
                lines.append(f"- `{ref.path}:{ref.line}` `{ref.text}`")
            if len(candidate.references) > 10:
                lines.append(f"- ... {len(candidate.references) - 10} more reference line(s)")
            lines.append("")
    lines.append("## Suggested Codex Actions")
    lines.append("")
    for item in card.next_codex_actions:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def save_task_card(card: TaskCard) -> TaskCard:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    slug = safe_slug(card.title)
    stamp = now_stamp()
    md_path = REPORT_DIR / f"ProjectEF_AudioCodexTaskCard_{slug}_{stamp}.md"
    json_path = REPORT_DIR / f"ProjectEF_AudioCodexTaskCard_{slug}_{stamp}.json"
    md_path.write_text(render_markdown(card), encoding="utf-8")
    json_path.write_text(json.dumps(asdict(card), ensure_ascii=False, indent=2), encoding="utf-8")
    card.md_path = str(md_path)
    card.json_path = str(json_path)
    return card


class CodexTaskCardGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ProjectEF Audio Codex Task Card")
        self.geometry("1320x820")
        self.minsize(1120, 700)
        self.configure(bg=BG)

        self.unity_root_var = tk.StringVar(value=str(DEFAULT_UNITY_ROOT))
        self.title_var = tk.StringVar(value="FishSurfaceStrike audio config")
        self.intent_var = tk.StringVar(value="Auto")
        self.status_var = tk.StringVar(value="Ready.")
        self.last_card: TaskCard | None = None
        self.scan_thread: threading.Thread | None = None

        self.configure_style()
        self.build_ui()

    def configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", background="#101720", fieldbackground="#101720", foreground=INK, rowheight=24)
        style.configure("Treeview.Heading", background="#d7d3c8", foreground="#050b12", font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", "#345f85")])

    def build_ui(self) -> None:
        root = tk.Frame(self, bg=BG)
        root.pack(fill=tk.BOTH, expand=True)

        header = tk.Frame(root, bg=BG)
        header.pack(fill=tk.X, padx=16, pady=(14, 8))
        tk.Label(header, text="ProjectEF Audio Codex Task Card", bg=BG, fg=INK, font=("Segoe UI", 22, "bold")).pack(
            side=tk.LEFT
        )
        tk.Button(header, text="Open Reports", command=self.open_reports, bg=CARD, fg=INK, relief=tk.FLAT, padx=14, pady=8).pack(
            side=tk.RIGHT
        )

        top = tk.Frame(root, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        top.pack(fill=tk.X, padx=16, pady=(0, 10))
        self.labeled_entry(top, "Unity Root", self.unity_root_var, 54).pack(side=tk.LEFT, padx=10, pady=10)
        self.labeled_entry(top, "Task Title", self.title_var, 34).pack(side=tk.LEFT, padx=(0, 10), pady=10)
        tk.Label(top, text="Intent", bg=PANEL, fg=MUTED, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        intent = ttk.Combobox(
            top,
            textvariable=self.intent_var,
            values=["Auto", "Animation", "Timeline", "VFX", "Prefab Component", "UI", "Water Splash"],
            width=18,
            state="readonly",
        )
        intent.pack(side=tk.LEFT, padx=(0, 10), pady=10)
        self.scan_button = tk.Button(
            top,
            text="Scan Candidates",
            command=self.scan_async,
            bg=ACCENT,
            fg="#06111d",
            relief=tk.FLAT,
            padx=16,
            pady=8,
            font=("Segoe UI", 9, "bold"),
        )
        self.scan_button.pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(
            top,
            text="Generate Card",
            command=self.generate_card_async,
            bg=GOOD,
            fg="#06111d",
            relief=tk.FLAT,
            padx=16,
            pady=8,
            font=("Segoe UI", 9, "bold"),
        ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(top, text="Copy Card", command=self.copy_card, bg=CARD, fg=INK, relief=tk.FLAT, padx=14, pady=8).pack(
            side=tk.LEFT
        )

        body = tk.Frame(root, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 10))

        left = tk.Frame(body, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=False)
        left.configure(width=500)
        left.pack_propagate(False)

        tk.Label(left, text="Input asset names / paths", bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=12, pady=(12, 4)
        )
        self.asset_text = self.text_box(left, 8)
        self.asset_text.pack(fill=tk.X, padx=12, pady=(0, 10))
        self.asset_text.insert(
            tk.END,
            "Assets/GameProject/RuntimeAssets/Timeline/FishSurfaceStrike/FishSurfaceStrike.prefab\n",
        )

        tk.Label(left, text="Candidate Wwise Events", bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=12, pady=(0, 4)
        )
        self.event_text = self.text_box(left, 5)
        self.event_text.pack(fill=tk.X, padx=12, pady=(0, 10))
        self.event_text.insert(tk.END, "Play_Fish_WaterSplashIn\nPlay_Fish_WaterSplashOut\n")

        tk.Label(left, text="Notes / config intent", bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=12, pady=(0, 4)
        )
        self.notes_text = self.text_box(left, 9)
        self.notes_text.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        self.notes_text.insert(
            tk.END,
            "Keep project audio loading untouched. Identify the real configuration owner first, then preview with existing project flow.\n",
        )

        right = tk.Frame(body, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0))

        tk.Label(right, text="Scan Candidates", bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=12, pady=(12, 4)
        )
        columns = ("kind", "score", "path")
        self.tree = ttk.Treeview(right, columns=columns, show="headings", height=10)
        self.tree.heading("kind", text="Kind")
        self.tree.heading("score", text="Score")
        self.tree.heading("path", text="Unity Path")
        self.tree.column("kind", width=220, stretch=False)
        self.tree.column("score", width=70, anchor=tk.CENTER, stretch=False)
        self.tree.column("path", width=640, stretch=True)
        self.tree.pack(fill=tk.X, padx=12, pady=(0, 10))

        tk.Label(right, text="Card Preview", bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=12, pady=(0, 4)
        )
        self.preview = self.text_box(right, 20, font=("Consolas", 9))
        self.preview.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        footer = tk.Frame(root, bg=BG)
        footer.pack(fill=tk.X, padx=16, pady=(0, 10))
        tk.Label(footer, textvariable=self.status_var, bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side=tk.LEFT)
        tk.Label(footer, text=str(REPORT_DIR), bg=BG, fg="#65748a", font=("Segoe UI", 9)).pack(side=tk.RIGHT)

    def labeled_entry(self, parent: tk.Frame, label: str, variable: tk.StringVar, width: int) -> tk.Frame:
        box = tk.Frame(parent, bg=PANEL)
        tk.Label(box, text=label, bg=PANEL, fg=MUTED, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        tk.Entry(box, textvariable=variable, width=width, bg="#101720", fg=INK, insertbackground=INK, relief=tk.FLAT).pack(
            anchor="w", ipady=5, pady=(2, 0)
        )
        return box

    def text_box(self, parent: tk.Frame, height: int, font: tuple[str, int] = ("Segoe UI", 10)) -> tk.Text:
        return tk.Text(
            parent,
            height=height,
            wrap=tk.WORD,
            bg="#101720",
            fg=INK,
            insertbackground=INK,
            relief=tk.FLAT,
            font=font,
            padx=10,
            pady=8,
        )

    def gather_inputs(self) -> tuple[str, str, Path, list[str], list[str], str]:
        title = self.title_var.get().strip()
        intent = self.intent_var.get().strip()
        unity_root = Path(self.unity_root_var.get().strip().strip('"'))
        inputs = split_input_lines(self.asset_text.get("1.0", tk.END))
        events = split_input_lines(self.event_text.get("1.0", tk.END))
        notes = self.notes_text.get("1.0", tk.END).strip()
        return title, intent, unity_root, inputs, events, notes

    def scan_async(self) -> None:
        self.run_card_job(save=False)

    def generate_card_async(self) -> None:
        self.run_card_job(save=True)

    def run_card_job(self, save: bool) -> None:
        if self.scan_thread and self.scan_thread.is_alive():
            messagebox.showinfo("Busy", "A scan is already running.")
            return
        title, intent, unity_root, inputs, events, notes = self.gather_inputs()
        if not unity_root.exists():
            messagebox.showerror("Unity root missing", str(unity_root))
            return
        if not inputs:
            messagebox.showerror("Missing input", "Add at least one asset name or path.")
            return
        self.scan_button.configure(state=tk.DISABLED)
        self.status_var.set("Scanning Unity assets...")

        def worker() -> None:
            try:
                card = build_task_card(title, intent, unity_root, inputs, events, notes)
                if save:
                    card = save_task_card(card)
                self.after(0, lambda: self.show_card(card, save))
            except Exception as exc:
                self.after(0, lambda: self.show_error(exc))

        self.scan_thread = threading.Thread(target=worker, daemon=True)
        self.scan_thread.start()

    def show_card(self, card: TaskCard, saved: bool) -> None:
        self.last_card = card
        for row in self.tree.get_children():
            self.tree.delete(row)
        for candidate in card.candidates:
            self.tree.insert("", tk.END, values=(candidate.kind, candidate.score, candidate.unity_path or candidate.path))
        self.preview.delete("1.0", tk.END)
        self.preview.insert(tk.END, render_markdown(card))
        if saved:
            self.status_var.set(f"Saved: {card.md_path}")
        else:
            self.status_var.set(f"Scan complete: {len(card.candidates)} candidate(s).")
        self.scan_button.configure(state=tk.NORMAL)

    def show_error(self, exc: Exception) -> None:
        self.scan_button.configure(state=tk.NORMAL)
        self.status_var.set("Scan failed.")
        messagebox.showerror("Task card scan failed", str(exc))

    def copy_card(self) -> None:
        text = self.preview.get("1.0", tk.END).strip()
        if not text:
            messagebox.showinfo("Copy Card", "Generate or scan a card first.")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("Card preview copied to clipboard.")

    def open_reports(self) -> None:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(REPORT_DIR))


def cli_main(args: argparse.Namespace) -> int:
    unity_root = Path(args.unity_root)
    inputs = split_input_lines(args.assets or "")
    events = split_input_lines(args.events or "")
    notes = args.notes or ""
    card = build_task_card(args.title or "ProjectEF audio configuration task", args.intent or "Auto", unity_root, inputs, events, notes)
    card = save_task_card(card)
    print(card.md_path)
    print(card.json_path)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate ProjectEF audio configuration task cards for Codex.")
    parser.add_argument("--no-gui", action="store_true", help="Generate a card without opening the Tk GUI.")
    parser.add_argument("--unity-root", default=str(DEFAULT_UNITY_ROOT))
    parser.add_argument("--title", default="ProjectEF audio configuration task")
    parser.add_argument("--intent", default="Auto")
    parser.add_argument("--assets", default="")
    parser.add_argument("--events", default="")
    parser.add_argument("--notes", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.no_gui:
        return cli_main(args)
    app = CodexTaskCardGui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
