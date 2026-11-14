"""Text+image content-generation adapters (no GUI computer use).

All adapters share ``LocalContentHost``: a temporary workspace, shell / write /
read / submit actions, and a ``vision.py`` tool that sends rendered charts or
slides to the local multimodal endpoint.  The agent's actions remain files and
terminal commands; images are only observations/evaluation artifacts.

Real-data adapters
------------------
OfficeEditBench  easy/medium/hard tasks + official ``verify_task.py``.
ChartQA          official test_human split + relaxed exact match.
PutnamBench      Lean 4 sources; grading needs Lean/Mathlib in PATH.
MATH-500 / AIME  local JSON (or two-problem fixture); final-answer match.

Local-fixture adapters (official data not bundled or not public)
---------------------------------------------------------------
ChartMimic       local target chart or a local image set; VLM visual similarity.
PPTEval          local PPTEval-style rubric; WPS render + VLM judge.
Paper2Poster     local poster fixture; VLM visual/textual/holistic judge.
DeckBench        local deck fixture / multi-turn edit; VLM judge.
ECHO             local Plan-Confirm-Execute-style co-edit protocol; no official
                 code or data is public.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from contract.types import (
    Action, BenchmarkAdapter, ExperimentConfig, Grade, Host, Observation,
    TaskSpec,
)

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / ".cache" / "adapters" / "fixtures"
DEFAULT_VLM_URL = "http://127.0.0.1:8080"
DEFAULT_VLM_MODEL = "qwen3.5-9b"

VISION_TOOL = '''\
import base64, json, sys, urllib.request
from pathlib import Path

URL = {url!r}
MODEL = {model!r}

def data_url(path):
    suffix = Path(path).suffix.lower()
    mime = {{".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".png": "image/png", ".webp": "image/webp"}}.get(suffix, "image/png")
    return "data:" + mime + ";base64," + base64.b64encode(Path(path).read_bytes()).decode()

image = sys.argv[1]
question = sys.argv[2] if len(sys.argv) > 2 else "Describe this image in detail."
payload = {{
    "model": MODEL,
    "messages": [{{"role": "user", "content": [
        {{"type": "text", "text": question}},
        {{"type": "image_url", "image_url": {{"url": data_url(image)}}}},
    ]}}],
    "temperature": 0.2,
    "max_tokens": 512,
}}
request = urllib.request.Request(
    URL.rstrip("/") + "/v1/chat/completions",
    data=json.dumps(payload).encode(),
    headers={{"Content-Type": "application/json"}},
)
with urllib.request.urlopen(request, timeout=300) as response:
    data = json.loads(response.read().decode())
print(data["choices"][0]["message"]["content"])
usage = data.get("usage") or {{}}
with open("vision_usage.jsonl", "a", encoding="utf-8") as handle:
    handle.write(json.dumps(usage, ensure_ascii=False) + "\\n")
'''


# --------------------------------------------------------------------- helpers
def _data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp"}.get(suffix, "image/png")
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def _json_from_text(text: str) -> Optional[dict]:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _content_text(message: dict) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
    return str(content)


def _normalize_answer(text: str) -> Any:
    text = text.strip().strip("\"'`“”‘’").strip()
    text = re.sub(r"\s+", " ", text.lower())
    text = text.replace(",", "").replace("$", "").replace("%", "").strip()
    try:
        return float(text)
    except ValueError:
        return text


def _answers_match(predicted: str, expected: str) -> bool:
    p, e = _normalize_answer(predicted), _normalize_answer(expected)
    if isinstance(p, float) and isinstance(e, float):
        if e == 0:
            return abs(p) < 1e-6
        return abs(p - e) / abs(e) <= 0.05
    return str(p) == str(e)


def _first_json(text: str) -> Optional[dict]:
    start = text.find("{")
    if start < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
        return obj
    except json.JSONDecodeError:
        return None


def _proof_has_sorry(text: str) -> bool:
    """Lean accepts ``sorry`` with a warning, so the harness must reject it."""
    return bool(re.search(r"\bsorry\b", text))


_CHEAT_TOKENS = re.compile(r"\b(sorry|admit)\b")
_CHEAT_DECLS = re.compile(
    r"^[ \t]*(?:private[ \t]+|protected[ \t]+|noncomputable[ \t]+)?"
    r"(?:axiom|constant|opaque|unsafe)\b", re.MULTILINE)


def _proof_cheat(text: str) -> str:
    """Return a reason when the source is not a complete proof.

    ``sorry``/``admit`` are accepted by Lean with only a warning.  The other
    tokens let an agent introduce an unproved axiom instead of proving the
    theorem, which would also pass a kernel check.
    """
    tokens = sorted(set(match.group(0) for match in _CHEAT_TOKENS.finditer(text)))
    if tokens:
        return "proof uses " + "/".join(tokens)
    decl = _CHEAT_DECLS.search(text)
    if decl:
        return f"proof declares '{decl.group(0).strip()}'"
    return ""


def _free_commit_gb() -> Optional[float]:
    """Available commit charge in GB (Windows); ``None`` elsewhere.

    Full ``import Mathlib`` maps roughly 3.5 GB of private oleans.  With a
    resident 9B model the commit headroom on this host drops below that and
    Lean fails on a random ``.olean.private`` with a read error, so grading
    reports the number instead of an unexplained kernel failure.
    """
    if os.name != "nt":
        return None
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return status.ullAvailPageFile / (1024 ** 3)
    except Exception:
        return None


def resolve_lean_bin(explicit: str | Path | None = None) -> Optional[Path]:
    """Resolve the pinned Lean toolchain's ``lake`` executable.

    The bundled v4.33.1 is preferred over ``shutil.which``: the latter often
    finds the elan shim in ``~/.elan/bin``, which can block on a toolchain or
    self-update download even when the pinned version is installed.
    """
    name = "lake.exe" if os.name == "nt" else "lake"

    def resolve(value: str | Path) -> Optional[Path]:
        path = Path(value)
        if path.is_file():
            return path
        candidate = path / name
        return candidate if candidate.is_file() else None

    if explicit is not None:
        return resolve(explicit)
    env = os.environ.get("PUTNAM_LEAN_BIN")
    if env:
        found = resolve(env)
        if found is not None:
            return found
    found = shutil.which(name)
    if found and ".elan" not in str(found).lower():
        return Path(found)
    for base in (
        REPO / ".cache" / "tools" / "lean4-4.33.1"
        / "lean-4.33.1-windows" / "bin",
        REPO / ".cache" / "tools" / "lean4-4.33.1"
        / "lean-4.33.1-linux" / "bin",
        REPO / ".cache" / "tools" / "lean4-4.33.1-windows" / "bin",
        REPO / ".cache" / "tools" / "lean4-4.33.1-linux" / "bin",
    ):
        candidate = base / name
        if candidate.is_file():
            return candidate
    return None


def _render_pptx_wps(pptx: Path, outdir: Path, width: int = 1600,
                     height: int = 900) -> List[Path]:
    script = REPO / "experiments" / "adapters" / "render_pptx_wps.ps1"
    outdir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(script), "-Pptx", str(pptx), "-OutDir", str(outdir),
         "-Width", str(width), "-Height", str(height)],
        check=True, capture_output=True, encoding="utf-8", errors="replace",
        timeout=300,
    )
    images = sorted(outdir.glob("*.PNG")) + sorted(outdir.glob("*.png"))
    if not images:
        raise RuntimeError(f"no rendered slides in {outdir}")
    return images


class VLMEvaluator:
    def __init__(self, url: str = DEFAULT_VLM_URL, model: str = DEFAULT_VLM_MODEL,
                 timeout: int = 300):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def ask(self, images: Sequence[Path], prompt: str,
            max_tokens: int = 512) -> str:
        content: List[dict] = [{"type": "text", "text": prompt}]
        for image in images:
            content.append({"type": "image_url",
                            "image_url": {"url": _data_url(Path(image))}})
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }
        request = urllib_request(self.url + "/v1/chat/completions",
                                 json.dumps(payload).encode())
        with urllib_request_open(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode())
        return data["choices"][0]["message"]["content"]

    def json(self, images: Sequence[Path], prompt: str) -> Optional[dict]:
        return _json_from_text(self.ask(images, prompt))


def urllib_request(url: str, data: bytes):
    import urllib.request
    return urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"})


def urllib_request_open(request, timeout: int):
    import urllib.request
    return urllib.request.urlopen(request, timeout=timeout)


# ----------------------------------------------------------------------- host
class LocalContentHost(Host):
    """A local workspace host for text+image content tasks."""

    def __init__(self, task: TaskSpec, config: ExperimentConfig,
                 workspace: Path, vlm_url: str = DEFAULT_VLM_URL,
                 vlm_model: str = DEFAULT_VLM_MODEL,
                 command_timeout: int = 900,
                 submit_callback: Optional[Callable[[Path], Optional[str]]] = None,
                 cleanup_workspace: bool = True,
                 extra_path: Optional[Path] = None,
                 install_tools: bool = True):
        self.task = task
        self.config = config
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.vlm_url = vlm_url
        self.vlm_model = vlm_model
        self.command_timeout = command_timeout
        self.submit_callback = submit_callback
        self.cleanup_workspace = cleanup_workspace
        self.extra_path = Path(extra_path) if extra_path is not None else None
        self.install_tools = install_tools
        self._actions: List[Action] = []
        self._tokens = 0
        self._vision_seen = 0
        self.submitted = False
        self.last_score: Optional[float] = None
        if self.install_tools:
            self._install_tools()

    # ------------------------------------------------------------------ tools
    def _install_tools(self) -> None:
        (self.workspace / "vision.py").write_text(
            VISION_TOOL.format(url=self.vlm_url, model=self.vlm_model),
            encoding="utf-8")
        python = str(Path(sys.executable))
        (self.workspace / "python3.bat").write_text(
            f'@echo off\r\n"{python}" %*\r\n', encoding="utf-8")

    def _vision_tokens(self) -> int:
        path = self.workspace / "vision_usage.jsonl"
        if not path.is_file():
            return 0
        total = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                usage = json.loads(line)
            except json.JSONDecodeError:
                continue
            total += int(usage.get("total_tokens")
                         or (int(usage.get("prompt_tokens") or 0)
                             + int(usage.get("completion_tokens") or 0)))
        return total

    @property
    def vision_tokens(self) -> int:
        return self._vision_tokens()

    def _charge_vision(self) -> None:
        now = self._vision_tokens()
        if now > self._vision_seen:
            self._tokens += now - self._vision_seen
            self._vision_seen = now

    # --------------------------------------------------------------- contract
    @property
    def tokens_used(self) -> int:
        return self._tokens

    @property
    def actions(self) -> List[Action]:
        return list(self._actions)

    def charge_tokens(self, n: int) -> None:
        self._tokens += max(0, int(n))
        if self._tokens > self.config.token_budget:
            raise RuntimeError(f"token budget exceeded: {self._tokens}")

    def _env(self) -> Dict[str, str]:
        env = os.environ.copy()
        parts = [str(Path(sys.executable).parent)]
        if self.extra_path is not None:
            parts.insert(0, str(self.extra_path))
        env["PATH"] = os.pathsep.join(parts + [env.get("PATH", "")])
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    def _run(self, command: str, timeout: Optional[int] = None):
        return subprocess.run(
            command, cwd=str(self.workspace), shell=True, env=self._env(),
            capture_output=True, encoding="utf-8", errors="replace",
            timeout=timeout or self.command_timeout,
        )

    def step(self, action: Action) -> Observation:
        if len(self._actions) >= self.config.max_actions:
            return Observation(error="max actions reached", exit_code=1)
        self._actions.append(action)
        try:
            if action.kind == "write":
                target = self.workspace / str(action.payload.get("path", ""))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(action.payload.get("content", "")),
                                  encoding="utf-8")
                return Observation(output=f"wrote {target.name}")
            if action.kind == "read":
                target = self.workspace / str(action.payload.get("path", ""))
                return Observation(output=target.read_text(encoding="utf-8"))
            if action.kind == "shell":
                proc = self._run(str(action.payload.get("command", "")))
                return Observation(output=(proc.stdout or "")[-8000:],
                                   error=(proc.stderr or "")[-8000:],
                                   exit_code=proc.returncode)
            if action.kind == "submit":
                if self.submit_callback is not None:
                    next_instruction = self.submit_callback(self.workspace)
                    if next_instruction:
                        return Observation(
                            error="Next user instruction: " + next_instruction,
                            exit_code=1)
                self.submitted = True
                return Observation(output="submitted")
            return Observation(error=f"unknown action {action.kind}", exit_code=1)
        except subprocess.TimeoutExpired as exc:
            return Observation(error=f"command timed out: {exc}", exit_code=124)
        except OSError as exc:
            return Observation(error=f"host error: {exc}", exit_code=1)
        finally:
            self._charge_vision()

    def submit(self) -> Observation:
        return self.step(Action("submit"))

    def grade(self) -> Grade:
        return Grade(valid=False, passed=False, checks_passed=0, checks_total=0,
                     detail="content host grade is implemented by the adapter")

    def cleanup(self) -> None:
        if self.cleanup_workspace:
            shutil.rmtree(self.workspace, ignore_errors=True)


# ---------------------------------------------------------------- fixtures
def _fixture_root(name: str) -> Path:
    root = FIXTURES / name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _make_chartmimic_fixture() -> Path:
    root = _fixture_root("chartmimic")
    target = root / "target.png"
    if not target.is_file():
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.bar(["A", "B", "C", "D"], [3, 7, 5, 2], color="#4C78A8")
        ax.set_title("Example Bar Chart")
        ax.set_ylabel("Value")
        fig.tight_layout()
        fig.savefig(target, dpi=120)
        plt.close(fig)
    return target


def _make_deck_fixture(kind: str) -> tuple[Path, Path]:
    from pptx import Presentation
    from pptx.util import Inches, Pt

    root = _fixture_root(kind)
    source = root / ("paper.md" if kind == "paper2poster" else "source.md")
    template = root / "template.pptx"
    if not source.is_file():
        source.write_text(
            "# Quarterly Review\n\nRevenue grew 18% year-over-year. Gross margin "
            "improved 220 bps to 71.4%. Customer acquisition cost rose 12% while "
            "lifetime value stayed flat; retention is the next priority.\n",
            encoding="utf-8")
    if not template.is_file():
        prs = Presentation()
        prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
        title = prs.slides.add_slide(prs.slide_layouts[0])
        title.shapes.title.text = "Quarterly Review"
        title.placeholders[1].text = "Prepared by the Strategy Team"
        body = prs.slides.add_slide(prs.slide_layouts[1])
        body.shapes.title.text = "Key Metrics"
        frame = body.placeholders[1].text_frame
        frame.text = "Revenue +18%"
        for line in ("Gross margin 71.4%", "CAC +12%; retention is the priority"):
            paragraph = frame.add_paragraph()
            paragraph.text = line
            paragraph.font.size = Pt(20)
        last = prs.slides.add_slide(prs.slide_layouts[1])
        last.shapes.title.text = "Next Steps"
        last.placeholders[1].text = "Improve SMB retention and payback period."
        prs.save(template)
    return source, template


def _make_echo_fixture() -> tuple[Path, List[str], dict]:
    from pptx import Presentation
    from pptx.util import Inches

    root = _fixture_root("echo")
    deck = root / "deck.pptx"
    if not deck.is_file():
        prs = Presentation()
        prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        slide.shapes.title.text = "Quarterly Review"
        box = slide.shapes.add_textbox(Inches(0.8), Inches(2.0), Inches(8), Inches(1))
        box.text_frame.text = "Revenue grew 18% year-over-year."
        prs.save(deck)
    instructions = [
        "Make the slide title bold and dark red (RGB C00000).",
        "Add a text line 'Prepared by the team' to the slide.",
    ]
    expected = {"title_bold": True, "title_color": "C00000",
                "subtitle": "Prepared by the team"}
    return deck, instructions, expected


# -------------------------------------------------------------- OfficeEditBench
class OfficeEditBenchAdapter(BenchmarkAdapter):
    name = "office_edit"
    mock_only = False
    real_loader = True
    real_host = True
    real_grader = True

    def __init__(self, root: str | Path, level: str = "easy",
                 limit: int = 20):
        self.root = Path(root)
        self.level = level
        self.limit = limit
        if level not in ("easy", "medium", "hard"):
            raise ValueError("level must be easy/medium/hard")

    def _paths(self) -> List[Path]:
        if self.level == "easy":
            return sorted((self.root / "easy" / "tasks").glob("*/task.json"))
        if self.level == "hard":
            return sorted((self.root / "hard" / "tasks").glob("*/task.json"))
        return sorted((self.root / "medium").rglob("task.json"))

    def load_tasks(self, path: str | None = None) -> List[TaskSpec]:
        tasks = []
        for task_json in self._paths()[: self.limit]:
            data = json.loads(task_json.read_text(encoding="utf-8"))
            task_dir = task_json.parent
            instruction_path = task_dir / "instruction.md"
            instruction = (instruction_path.read_text(encoding="utf-8")
                           if instruction_path.is_file()
                           else data.get("instruction", ""))
            instruction += (
                "\n\nWork in the current directory. The input file is provided "
                f"here. Use Python to edit it and save the deliverable as "
                f"`{data['output_file']}`. Do not use a GUI.")
            tasks.append(TaskSpec(
                task_id=data["id"], benchmark=self.name,
                instruction=instruction,
                metadata={
                    "task_dir": str(task_dir), "input_file": data["input_file"],
                    "output_file": data["output_file"],
                    "category": data.get("category", ""), "level": self.level,
                    "title": data.get("title", ""),
                }))
        return tasks

    def make_host(self, task: TaskSpec, config: ExperimentConfig) -> Host:
        workspace = Path(tempfile.mkdtemp(prefix="oeb-"))
        input_dir = Path(task.metadata["task_dir"]) / "input"
        if input_dir.is_dir():
            for source in input_dir.iterdir():
                if source.is_file():
                    shutil.copy2(source, workspace / source.name)
        return LocalContentHost(task, config, workspace)

    def grade(self, task: TaskSpec, host: Host) -> Grade:
        workspace = Path(getattr(host, "workspace"))
        submission = workspace / "_submission"
        submission.mkdir(exist_ok=True)
        skip = {"_submission", "vision.py", "python3.bat", "vision_usage.jsonl"}
        for source in workspace.iterdir():
            if source.name in skip or not source.is_file():
                continue
            shutil.copy2(source, submission / source.name)
        verifier = self.root / self.level / "verify_task.py"
        try:
            proc = subprocess.run(
                [sys.executable, str(verifier), task.task_id, str(submission)],
                cwd=str(verifier.parent), capture_output=True,
                encoding="utf-8", errors="replace", timeout=300,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return Grade(valid=False, passed=False, checks_passed=0,
                         checks_total=0,
                         detail=f"OfficeEditBench verifier error: {exc}")
        output = (proc.stdout or "") + (proc.stderr or "")
        report = _first_json(output)
        if report is None:
            return Grade(valid=False, passed=False, checks_passed=0,
                         checks_total=0,
                         detail="OfficeEditBench report missing; " + output[-1500:])
        checks = report.get("checks", [])
        passed_checks = sum(1 for check in checks if check.get("passed"))
        score = report.get("score", 0)
        getattr(host, "last_score", None)
        if hasattr(host, "last_score"):
            host.last_score = (score / 100.0) if isinstance(score, (int, float)) else None
        return Grade(
            valid=True, passed=bool(report.get("passed")),
            checks_passed=passed_checks, checks_total=len(checks),
            detail=f"office score={score}\n" + output[-1500:],
        )


# ------------------------------------------------------------------- ChartQA
class ChartQAAdapter(BenchmarkAdapter):
    name = "chartqa"
    mock_only = False
    real_loader = True
    real_host = True
    real_grader = True

    def __init__(self, root: str | Path, split: str = "test",
                 source: str = "test_human", limit: int = 20):
        self.root = Path(root)
        self.split = split
        self.source = source
        self.limit = limit

    def load_tasks(self, path: str | None = None) -> List[TaskSpec]:
        data = json.loads(
            (self.root / self.split / f"{self.source}.json").read_text(
                encoding="utf-8"))
        tasks = []
        for index, item in enumerate(data[: self.limit]):
            image = self.root / self.split / "png" / item["imgname"]
            if not image.is_file():
                continue
            instruction = (
                f"{item['query']}\n\nThe chart is `target.png` in the current "
                "directory. You may inspect it with `python vision.py target.png "
                "\"<question>\"`. Write the final short answer to `answer.txt`.")
            tasks.append(TaskSpec(
                task_id=f"chartqa-{index}", benchmark=self.name,
                instruction=instruction,
                metadata={"image": str(image), "label": item["label"],
                          "query": item["query"]}))
        return tasks

    def make_host(self, task: TaskSpec, config: ExperimentConfig) -> Host:
        workspace = Path(tempfile.mkdtemp(prefix="chartqa-"))
        shutil.copy2(task.metadata["image"], workspace / "target.png")
        return LocalContentHost(task, config, workspace)

    def grade(self, task: TaskSpec, host: Host) -> Grade:
        answer_path = Path(getattr(host, "workspace")) / "answer.txt"
        if not answer_path.is_file():
            return Grade(valid=True, passed=False, checks_passed=0,
                         checks_total=1, detail="answer.txt missing")
        answer = answer_path.read_text(encoding="utf-8").strip()
        expected = task.metadata["label"]
        passed = _answers_match(answer, expected)
        if hasattr(host, "last_score"):
            host.last_score = 1.0 if passed else 0.0
        return Grade(valid=True, passed=passed, checks_passed=1 if passed else 0,
                     checks_total=1,
                     detail=f"answer={answer!r} expected={expected!r}")


# ---------------------------------------------------------------- ChartMimic
class ChartMimicAdapter(BenchmarkAdapter):
    name = "chartmimic"
    mock_only = False
    real_loader = True
    real_host = True
    real_grader = True

    def __init__(self, data_root: str | Path | None = None,
                 limit: int = 1, vlm_url: str = DEFAULT_VLM_URL,
                 vlm_model: str = DEFAULT_VLM_MODEL,
                 judge: Optional[Callable[[Path, Path], Optional[dict]]] = None):
        self.data_root = Path(data_root) if data_root else None
        self.limit = limit
        self.vlm_url = vlm_url
        self.vlm_model = vlm_model
        self.judge = judge

    def load_tasks(self, path: str | None = None) -> List[TaskSpec]:
        tasks = []
        if self.data_root is not None:
            images = self.data_root / "images"
            info = self.data_root / "dimentions_info.jsonl"
            if images.is_dir() and info.is_file():
                for line in info.read_text(encoding="utf-8").splitlines()[: self.limit]:
                    item = json.loads(line)
                    stem = Path(item.get("file", "chart")).stem
                    image = next((p for p in (images / f"{stem}.png",
                                              images / f"{stem}.jpg")
                                  if p.is_file()), None)
                    if image is None:
                        continue
                    tasks.append(TaskSpec(
                        task_id=f"chartmimic-{stem}", benchmark=self.name,
                        instruction=(
                            "Reproduce the target chart in `target.png`. Write "
                            "`solution.py` using matplotlib that saves the chart "
                            "to `output.png`. You may inspect the target with "
                            "`python vision.py target.png \"<question>\"`.\n\n"
                            "Do not use a GUI."),
                        metadata={"image": str(image)}))
                if tasks:
                    return tasks
        target = _make_chartmimic_fixture()
        tasks.append(TaskSpec(
            task_id="bar-fixture", benchmark=self.name,
            instruction=(
                "Reproduce the target chart in `target.png`. Write `solution.py` "
                "using matplotlib that saves the chart to `output.png`. You may "
                "inspect the target with `python vision.py target.png "
                "\"<question>\"`.\n\nDo not use a GUI."),
            metadata={"image": str(target), "fixture": True}))
        return tasks

    def make_host(self, task: TaskSpec, config: ExperimentConfig) -> Host:
        workspace = Path(tempfile.mkdtemp(prefix="chartmimic-"))
        shutil.copy2(task.metadata["image"], workspace / "target.png")
        return LocalContentHost(task, config, workspace, self.vlm_url,
                                self.vlm_model)

    def _judge(self, target: Path, output: Path) -> Optional[dict]:
        if self.judge is not None:
            return self.judge(target, output)
        prompt = (
            "Compare the target chart and the generated chart. Return JSON with "
            "an integer score 1-5 for visual fidelity (chart type, data, axes, "
            "labels, colors, layout) and a short issues list.")
        return VLMEvaluator(self.vlm_url, self.vlm_model).json(
            [target, output], prompt)

    def grade(self, task: TaskSpec, host: Host) -> Grade:
        workspace = Path(getattr(host, "workspace"))
        output = workspace / "output.png"
        exec_ok = output.is_file()
        exec_detail = "output.png present"
        if not exec_ok and (workspace / "solution.py").is_file():
            try:
                proc = subprocess.run(
                    [sys.executable, "solution.py"], cwd=str(workspace),
                    capture_output=True, encoding="utf-8", errors="replace",
                    timeout=180,
                )
                exec_ok = output.is_file() and proc.returncode == 0
                exec_detail = (proc.stdout or "") + (proc.stderr or "")
            except (OSError, subprocess.TimeoutExpired) as exc:
                exec_detail = f"solution failed: {exc}"
        score = 0
        issues: List[str] = []
        if exec_ok:
            judged = self._judge(Path(task.metadata["image"]), output)
            if judged:
                score = int(judged.get("score", 0) or 0)
                issues = judged.get("issues", []) or []
        passed = exec_ok and score >= 3
        if hasattr(host, "last_score"):
            host.last_score = score / 5.0
        return Grade(valid=True, passed=passed,
                     checks_passed=(1 if exec_ok else 0) + (1 if score >= 3 else 0),
                     checks_total=2,
                     detail=f"execution={exec_ok} score={score}/5 issues={issues}\n"
                            + exec_detail[-1000:])


# --------------------------------------------------------- deck/poster/ECHO
class DeckAdapter(BenchmarkAdapter):
    """Local PPTEval / Paper2Poster / DeckBench-style deck adapter."""

    def __init__(self, kind: str = "ppteval", vlm_url: str = DEFAULT_VLM_URL,
                 vlm_model: str = DEFAULT_VLM_MODEL,
                 render: Optional[Callable[[Path, Path], List[Path]]] = None,
                 judge: Optional[Callable[[Sequence[Path], str], Optional[dict]]] = None):
        self.kind = kind
        self.name = kind
        self.vlm_url = vlm_url
        self.vlm_model = vlm_model
        self.render = render or _render_pptx_wps
        self.judge = judge

    def load_tasks(self, path: str | None = None) -> List[TaskSpec]:
        source, template = _make_deck_fixture(self.kind)
        if self.kind == "paper2poster":
            instruction = (
                "Create a one-page poster `poster.pptx` from `paper.md` using "
                "`template.pptx` as the visual template. Keep the content faithful; "
                "use the provided text; do not use a GUI.")
            output = "poster.pptx"
        elif self.kind == "deckbench":
            instruction = (
                "Create `deck.pptx` from `source.md` using `template.pptx`. The deck "
                "must be faithful and visually coherent; do not use a GUI.")
            output = "deck.pptx"
        else:
            instruction = (
                "Create `deck.pptx` from `source.md` using `template.pptx`. Use "
                "Python (python-pptx) to copy the template and fill the slides; "
                "keep content faithful and design coherent. Do not use a GUI.")
            output = "deck.pptx"
        return [TaskSpec(
            task_id=f"{self.kind}-fixture", benchmark=self.name,
            instruction=instruction,
            metadata={"source": str(source), "template": str(template),
                      "output": output, "kind": self.kind})]

    def make_host(self, task: TaskSpec, config: ExperimentConfig) -> Host:
        workspace = Path(tempfile.mkdtemp(prefix=f"{self.kind}-"))
        shutil.copy2(task.metadata["source"], workspace / Path(task.metadata["source"]).name)
        shutil.copy2(task.metadata["template"], workspace / "template.pptx")
        return LocalContentHost(task, config, workspace, self.vlm_url,
                                self.vlm_model)

    def _judge(self, images: Sequence[Path]) -> Optional[dict]:
        if self.kind == "paper2poster":
            prompt = (
                "Evaluate this poster. Return JSON with integer 1-5 scores for "
                "visual, textual, and holistic quality, plus a short issues list.")
        else:
            prompt = (
                "Evaluate this presentation deck. Return JSON with integer 1-5 "
                "scores for content, design, and coherence, plus a short issues list.")
        if self.judge is not None:
            return self.judge(images, prompt)
        return VLMEvaluator(self.vlm_url, self.vlm_model).json(images, prompt)

    def grade(self, task: TaskSpec, host: Host) -> Grade:
        workspace = Path(getattr(host, "workspace"))
        deck = workspace / task.metadata["output"]
        if not deck.is_file():
            return Grade(valid=True, passed=False, checks_passed=0,
                         checks_total=1, detail=f"{deck.name} missing")
        outdir = workspace / "_render"
        try:
            images = self.render(deck, outdir)
        except Exception as exc:
            return Grade(valid=False, passed=False, checks_passed=0,
                         checks_total=1, detail=f"render failed: {exc}")
        judged = self._judge(images) or {}
        if self.kind == "paper2poster":
            keys = ("visual", "textual", "holistic")
        else:
            keys = ("content", "design", "coherence")
        scores = [int(judged.get(key, 0) or 0) for key in keys]
        average = sum(scores) / len(scores) if scores else 0.0
        passed = average >= 3.0
        if hasattr(host, "last_score"):
            host.last_score = average / 5.0
        return Grade(valid=True, passed=passed,
                     checks_passed=sum(1 for score in scores if score >= 3)
                     + (1 if images else 0),
                     checks_total=len(scores) + 1,
                     detail=f"scores={dict(zip(keys, scores))} avg={average:.2f} "
                            f"images={len(images)} issues={judged.get('issues', [])}")


class PPTEvalAdapter(DeckAdapter):
    def __init__(self, **kwargs):
        super().__init__(kind="ppteval", **kwargs)


class Paper2PosterAdapter(DeckAdapter):
    def __init__(self, **kwargs):
        super().__init__(kind="paper2poster", **kwargs)


class DeckBenchAdapter(DeckAdapter):
    def __init__(self, **kwargs):
        super().__init__(kind="deckbench", **kwargs)


class ECHOAdapter(BenchmarkAdapter):
    """Local co-edit protocol; no official ECHO code/data is public."""

    name = "echo"
    mock_only = False
    real_loader = True
    real_host = True
    real_grader = True

    def __init__(self, vlm_url: str = DEFAULT_VLM_URL,
                 vlm_model: str = DEFAULT_VLM_MODEL):
        self.vlm_url = vlm_url
        self.vlm_model = vlm_model

    def load_tasks(self, path: str | None = None) -> List[TaskSpec]:
        deck, instructions, expected = _make_echo_fixture()
        instruction = (
            "Edit the slide deck `deck.pptx` according to the user. First request: "
            f"{instructions[0]}\n\nUse python-pptx; do not use a GUI. The user will "
            "send the next request after you submit.")
        return [TaskSpec(
            task_id="echo-fixture", benchmark=self.name, instruction=instruction,
            metadata={"deck": str(deck), "instructions": instructions,
                      "expected": expected})]

    def make_host(self, task: TaskSpec, config: ExperimentConfig) -> Host:
        workspace = Path(tempfile.mkdtemp(prefix="echo-"))
        shutil.copy2(task.metadata["deck"], workspace / "deck.pptx")
        instructions = list(task.metadata["instructions"])[1:]
        index = {"value": 0}

        def next_instruction(_workspace: Path) -> Optional[str]:
            if index["value"] < len(instructions):
                text = instructions[index["value"]]
                index["value"] += 1
                return text
            return None

        return LocalContentHost(task, config, workspace, self.vlm_url,
                                self.vlm_model,
                                submit_callback=next_instruction)

    def grade(self, task: TaskSpec, host: Host) -> Grade:
        from pptx import Presentation
        from pptx.dml.color import RGBColor

        deck = Path(getattr(host, "workspace")) / "deck.pptx"
        if not deck.is_file():
            return Grade(valid=True, passed=False, checks_passed=0,
                         checks_total=1, detail="deck.pptx missing")
        prs = Presentation(str(deck))
        title_ok = False
        color_ok = False
        subtitle_ok = False
        for slide in prs.slides:
            if slide.shapes.title is not None:
                for paragraph in slide.shapes.title.text_frame.paragraphs:
                    for run in paragraph.runs:
                        if run.font.bold:
                            title_ok = True
                        try:
                            if str(run.font.color.rgb).upper() == "C00000":
                                color_ok = True
                        except Exception:
                            pass
            for shape in slide.shapes:
                if shape.has_text_frame and "Prepared by the team" in shape.text_frame.text:
                    subtitle_ok = True
        expected = task.metadata["expected"]
        checks = [
            ("title_bold", title_ok == expected["title_bold"]),
            ("title_color", color_ok == (expected["title_color"] == "C00000")),
            ("subtitle", subtitle_ok == bool(expected["subtitle"])),
        ]
        passed = all(ok for _, ok in checks)
        if hasattr(host, "last_score"):
            host.last_score = 1.0 if passed else 0.0
        return Grade(valid=True, passed=passed,
                     checks_passed=sum(1 for _, ok in checks if ok),
                     checks_total=len(checks),
                     detail="; ".join(f"{name}={ok}" for name, ok in checks))


# --------------------------------------------------------------- PutnamBench
class PutnamBenchAdapter(BenchmarkAdapter):
    name = "putnam"
    mock_only = False
    real_loader = True
    real_host = True
    real_grader = True

    # Full ``import Mathlib`` needs about 5.5 GB of available commit charge on
    # this host.  Below that Lean aborts on a random olean with a read error.
    MIN_FREE_COMMIT_GB = 5.5

    def __init__(self, root: str | Path, limit: int = 20,
                 lean_bin: str | Path | None = None,
                 min_free_commit_gb: Optional[float] = None):
        self.root = Path(root)
        self.limit = limit
        self.lean_bin = Path(lean_bin) if lean_bin is not None else None
        self.min_free_commit_gb = (
            self.MIN_FREE_COMMIT_GB if min_free_commit_gb is None
            else float(min_free_commit_gb))

    @property
    def project(self) -> Path:
        return self.root / "lean4"

    def _lake(self) -> Optional[Path]:
        return resolve_lean_bin(self.lean_bin)

    def source_path(self, task: TaskSpec) -> Path:
        return self.project / "src" / task.metadata["file"]

    def load_tasks(self, path: str | None = None) -> List[TaskSpec]:
        tasks = []
        for source in sorted((self.project / "src").glob("*.lean"))[: self.limit]:
            parts = source.stem.split("_")
            tasks.append(TaskSpec(
                task_id=source.stem, benchmark=self.name,
                instruction=(
                    "The Lean 4 project is the current directory. Replace "
                    f"`sorry` in `src/{source.name}` with a complete proof. "
                    f"Run `lake env lean src/{source.name}` in the current "
                    "directory to check the kernel; the file must not contain "
                    "`sorry`, `admit`, or a new axiom. Do not use a GUI."),
                metadata={
                    "file": source.name,
                    "project": str(self.project),
                    "year": parts[1] if len(parts) > 1 else "",
                    "problem": parts[2] if len(parts) > 2 else "",
                }))
        return tasks

    def make_host(self, task: TaskSpec, config: ExperimentConfig) -> Host:
        project = self.project
        source = project / "src" / task.metadata["file"]
        if not source.is_file():
            raise FileNotFoundError(f"missing PutnamBench source {source}")
        backup = source.with_suffix(source.suffix + ".bak")
        # The Mathlib cache is large; run in place rather than copying the
        # project per task.  Restore the pristine task file from the backup.
        if backup.is_file():
            shutil.copy2(backup, source)
        else:
            shutil.copy2(source, backup)
        lake = self._lake()
        return LocalContentHost(
            task, config, project, command_timeout=3600,
            cleanup_workspace=False,
            extra_path=lake.parent if lake is not None else None,
            install_tools=False)

    def grade(self, task: TaskSpec, host: Host) -> Grade:
        project = Path(getattr(host, "workspace"))
        source = project / "src" / task.metadata["file"]
        if not source.is_file():
            return Grade(valid=False, passed=False, checks_passed=0,
                         checks_total=1, detail=f"missing {source}")
        text = source.read_text(encoding="utf-8", errors="replace")
        cheat = _proof_cheat(text)
        if cheat:
            return Grade(valid=True, passed=False, checks_passed=0,
                         checks_total=1,
                         detail=f"{cheat}; Lean would accept it with only a "
                                "warning or an extra axiom")
        lake = self._lake()
        if lake is None:
            return Grade(valid=False, passed=False, checks_passed=0,
                         checks_total=1,
                         detail="Lean toolchain missing: set PUTNAM_LEAN_BIN or "
                                "install Lean v4.33.1 + Mathlib")
        free_gb = _free_commit_gb()
        if free_gb is not None and free_gb < self.min_free_commit_gb:
            return Grade(
                valid=False, passed=False, checks_passed=0, checks_total=1,
                detail=(f"Lean grading needs about {self.min_free_commit_gb:.1f} "
                        f"GB of commit headroom, only {free_gb:.1f} GB free; "
                        "stop the local model server before grading "
                        "(repro_math_pilot.py --release-model does this)."))
        env = os.environ.copy()
        env["PATH"] = str(lake.parent) + os.pathsep + env.get("PATH", "")
        started = time.time()
        try:
            proc = subprocess.run(
                [str(lake), "env", "lean", f"src/{task.metadata['file']}"],
                cwd=str(project), env=env, capture_output=True,
                encoding="utf-8", errors="replace", timeout=3600)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return Grade(valid=False, passed=False, checks_passed=0,
                         checks_total=1, detail=f"lake env lean error: {exc}")
        seconds = time.time() - started
        output = (proc.stdout or "") + (proc.stderr or "")
        sorry_warning = "uses `sorry`" in output or "uses 'sorry'" in output
        passed = proc.returncode == 0 and not sorry_warning
        if hasattr(host, "last_score"):
            host.last_score = 1.0 if passed else 0.0
        return Grade(valid=True, passed=passed,
                     checks_passed=1 if passed else 0, checks_total=1,
                     detail=(f"lake env lean exit={proc.returncode} "
                             f"in {seconds:.1f}s"
                             + (f" free_commit_gb={free_gb:.1f}" if free_gb else "")
                             + "\n" + output[-1500:]))


# ----------------------------------------------------------- informal math
_BOXED = re.compile(r"\\boxed\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}")
_FRAC = re.compile(r"\\[dt]?frac\{([^{}]+)\}\{([^{}]+)\}")


def _final_answer(text: str) -> str:
    """Take the last ``\\boxed{...}`` or the last non-empty line."""
    boxed = _BOXED.findall(text)
    if boxed:
        return boxed[-1].strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _normalize_math_text(text: str) -> str:
    text = _final_answer(text)
    text = _FRAC.sub(r"\1/\2", text)
    text = (text.replace("$", "").replace("\\,", "").replace("\\!", "")
                .replace("\\left", "").replace("\\right", "")
                .replace("\\cdot", "*").replace("\\times", "*")
                .replace("\\%", "%"))
    text = re.sub(r"\s+", "", text)
    return text.strip(".;,").lower()


def _as_float(text: str) -> Optional[float]:
    try:
        return float(text)
    except ValueError:
        return None


def _as_fraction(text: str) -> Optional[tuple]:
    match = re.fullmatch(r"(-?\d+)/(\d+)", text)
    if not match or int(match.group(2)) == 0:
        return None
    return int(match.group(1)), int(match.group(2))


def _math_answers_match(predicted: str, expected: str, tol: float = 1e-6) -> bool:
    p = _normalize_math_text(predicted)
    e = _normalize_math_text(expected)
    if p == e:
        return True
    pf, ef = _as_float(p), _as_float(e)
    if pf is not None and ef is not None:
        return abs(pf - ef) <= tol * max(1.0, abs(ef))
    pfrac, efrac = _as_fraction(p), _as_fraction(e)
    if pfrac is not None and efrac is not None:
        return pfrac[0] * efrac[1] == efrac[0] * pfrac[1]
    if pfrac is not None and ef is not None:
        return abs(pfrac[0] / pfrac[1] - ef) <= tol * max(1.0, abs(ef))
    if pf is not None and efrac is not None:
        value = efrac[0] / efrac[1]
        return abs(pf - value) <= tol * max(1.0, abs(value))
    return False


def _load_math_items(path: Path) -> List[dict]:
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in raw.splitlines() if line.strip()]
    data = json.loads(raw)
    if isinstance(data, dict):
        for key in ("problems", "data", "test", "questions", "examples"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    return data


def _make_math_fixture(kind: str) -> Path:
    root = _fixture_root(kind)
    path = root / f"{kind}-fixture.json"
    if not path.is_file():
        if kind == "aime":
            items = [
                {"id": "fixture-1",
                 "problem": "Find the remainder when $2^{100}$ is divided by 7.",
                 "answer": "2"},
                {"id": "fixture-2",
                 "problem": "How many positive divisors does 36 have?",
                 "answer": "9"},
            ]
        else:
            items = [
                {"unique_id": "fixture-1",
                 "problem": "If $x^2 - 5x + 6 = 0$, what is the sum of the "
                            "roots?",
                 "answer": "5"},
                {"unique_id": "fixture-2",
                 "problem": "Compute $\\frac{3}{4} + \\frac{1}{6}$.",
                 "answer": "11/12"},
            ]
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    return path


class MATH500Adapter(BenchmarkAdapter):
    """MATH-500 / AIME informal math with final-answer exact matching.

    The official MATH-500 JSON (``problem``/``answer``) is used when ``path``
    is given.  A local two-problem fixture keeps the adapter testable offline.
    """

    mock_only = False
    real_loader = True
    real_host = True
    real_grader = True

    def __init__(self, path: str | Path | None = None, limit: int = 20,
                 kind: str = "math500", tolerance: float = 1e-6):
        self.path = Path(path) if path is not None else None
        self.limit = limit
        self.kind = kind
        self.name = kind
        self.tolerance = tolerance

    def _items(self) -> List[dict]:
        if self.path is not None:
            if not self.path.is_file():
                raise FileNotFoundError(f"{self.kind} dataset not found: {self.path}")
            return _load_math_items(self.path)
        return json.loads(_make_math_fixture(self.kind).read_text(
            encoding="utf-8"))

    def load_tasks(self, path: str | None = None) -> List[TaskSpec]:
        tasks = []
        for index, item in enumerate(self._items()[: self.limit]):
            problem = (item.get("problem") or item.get("question")
                       or item.get("instruction") or "").strip()
            answer = str(item.get("answer", item.get("final_answer", "")))
            if not problem or not answer:
                continue
            raw_id = str(item.get("unique_id") or item.get("id")
                         or f"{self.kind}-{index}")
            task_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw_id).strip("-")
            instruction = (
                "Solve the following mathematics problem. Work in the current "
                "directory and show your reasoning, then write only the final "
                "answer to `answer.txt` (use `a/b` for fractions, no prose).\n\n"
                f"Problem:\n{problem}")
            tasks.append(TaskSpec(
                task_id=task_id, benchmark=self.name, instruction=instruction,
                metadata={
                    "problem": problem, "answer": answer,
                    "subject": item.get("subject", ""),
                    "level": item.get("level", ""),
                    "kind": self.kind,
                }))
        return tasks

    def make_host(self, task: TaskSpec, config: ExperimentConfig) -> Host:
        workspace = Path(tempfile.mkdtemp(prefix=f"{self.kind}-"))
        return LocalContentHost(task, config, workspace, install_tools=False)

    def grade(self, task: TaskSpec, host: Host) -> Grade:
        path = Path(getattr(host, "workspace")) / "answer.txt"
        if not path.is_file():
            return Grade(valid=True, passed=False, checks_passed=0,
                         checks_total=1, detail="answer.txt missing")
        predicted = path.read_text(encoding="utf-8", errors="replace")
        expected = task.metadata["answer"]
        if self.kind == "aime":
            p = _as_float(_normalize_math_text(predicted))
            e = _as_float(_normalize_math_text(expected))
            passed = (p is not None and e is not None and p == e
                      and 0 <= p <= 999)
        else:
            passed = _math_answers_match(predicted, expected, self.tolerance)
        if hasattr(host, "last_score"):
            host.last_score = 1.0 if passed else 0.0
        return Grade(valid=True, passed=passed,
                     checks_passed=1 if passed else 0, checks_total=1,
                     detail=f"answer={_final_answer(predicted)!r} "
                            f"expected={expected!r}")


class AIMEAdapter(MATH500Adapter):
    def __init__(self, path: str | Path | None = None, limit: int = 20,
                 tolerance: float = 1e-6):
        super().__init__(path=path, limit=limit, kind="aime",
                         tolerance=tolerance)
