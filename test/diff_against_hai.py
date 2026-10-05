#!/usr/bin/env python3
"""
当前代码、Python 参考实现、test/Hai code、test/Dan code 的对拍测试引擎。

本脚本不会修改任意一份源码。它会把各份代码复制到临时目录，在临时目录中
分别通过 Makefile 编译 animate_server 和 animate_client，然后通过作业要求的
SIGUSR1/SIGUSR2 + FIFO 协议直接和 server 通信。由于不同实现的资源 handle
分配方式不同，对拍时会分别记录每份实现返回的 handle，并在比较输出时做归一化。
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import errno
import os
import random
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


ROOT = Path(__file__).resolve().parents[1]
HAI_ROOT = ROOT / "test" / "Hai code"
DAN_ROOT = ROOT / "test" / "Dan code"
PYTHON_ROOT = ROOT / "test" / "Python"
IMPLEMENTATION_NAMES = ("student", "python", "hai", "dan")
REFERENCE_ROOTS = {
    "hai": HAI_ROOT,
    "dan": DAN_ROOT,
}
ARTIFACT_RUN_ID = os.environ.get(
    "P2_DIFF_RUN_ID",
    datetime.now().strftime("%Y%m%d_%H%M%S_%d"),
)
TEST_ROOT = ROOT / "test"
VIDEO_RUN_DIR = TEST_ROOT / "data" / ARTIFACT_RUN_ID
DATA_RUN_DIR = TEST_ROOT / "data" / ARTIFACT_RUN_ID

# 随机/压力测试默认参数。放在文件顶部，方便直接修改测试规模。
DEFAULT_IMPLEMENTATIONS = "student,python"  # 默认参与测试的实现；限制：逗号分隔，可选 student/python/hai/dan/all。
DEFAULT_THREADS = 40  # 服务器工作线程数；限制：必须 >= 1。
DEFAULT_TIMEOUT = 5.0  # 单次连接/响应等待秒数；限制：必须 > 0；压力测试响应慢时优先调大。
DEFAULT_BUILD_TIMEOUT = 10.0  # 单次 make 等待秒数；限制：必须 > 0。
DEFAULT_MEMCHECK = True  # 是否默认启用 sanitizer 内存检查；限制：布尔值，True=每个测试扫描 student 的 ASan/LSan 日志。
DEFAULT_RANDOM_SEED = 4894196  # 随机种子；限制：整数，相同值生成相同测试。
DEFAULT_USERS_SEED = 81569  # users.txt 随机生成种子；限制：整数，改动会改变 userN 的登录返回值。
DEFAULT_RANDOM_BMP_SEED = 9217  # bmp/ 随机图片生成种子；限制：整数，改动会改变 create_sprite 测试图片内容。
DEFAULT_RANDOM_BMP_COUNT = 40  # 每份临时代码目录生成的 BMP 数量；限制：必须 >= 1。
DEFAULT_RANDOM_CASES = 1  # 小随机用例数量；限制：必须 >= 0。
DEFAULT_RANDOM_CLIENTS = 3  # 小随机客户端数；限制：必须 >= 2。
DEFAULT_COMMANDS_PER_CLIENT = 6  # 小随机每客户端命令数；限制：必须 >= 1。
DEFAULT_STRESS_CLIENTS = 50  # 压力测试客户端数；限制：必须 >= 2。
DEFAULT_STRESS_ROUNDS = 200  # 独立压力每客户端轮数；限制：必须 >= 1。
DEFAULT_RANDOM_PRESSURE_CASES = 5  # 随机压力用例数量；限制：必须 >= 0。
DEFAULT_RANDOM_PRESSURE_CLIENTS = 50  # 随机压力客户端数；限制：必须 >= 2。
DEFAULT_RANDOM_PRESSURE_COMMANDS_PER_CLIENT = 200  # 随机压力每客户端命令数；限制：必须 >= 1。
DEFAULT_RANDOM_CREATE_WEIGHT = 180  # create_canvas/create_sprite/create_rectangle/create_circle 合并权重；限制：必须 >= 0。
DEFAULT_RANDOM_PLACE_SPRITE_WEIGHT = 200  # place_sprite 动作权重；限制：必须 >= 0。
DEFAULT_RANDOM_PLACEMENT_WEIGHT = 60  # placement_up/down/top/bottom 合并权重；限制：必须 >= 0。
DEFAULT_RANDOM_SET_ANIMATION_WEIGHT = 200  # set_animation_params 动作权重；限制：必须 >= 0。
DEFAULT_RANDOM_DESTROY_CANVAS_WEIGHT = 30  # destroy_canvas 动作权重；限制：必须 >= 0。
DEFAULT_RANDOM_DESTROY_SPRITE_WEIGHT = 40  # destroy_sprite 动作权重；限制：必须 >= 0。
DEFAULT_RANDOM_DESTROY_PLACEMENT_WEIGHT = 60  # destroy_placement 动作权重；限制：必须 >= 0。
DEFAULT_RANDOM_BARRIER_WEIGHT = 100  # barrier 动作相对权重；限制：必须 >= 0，0 表示禁用；概率约为本值/所有动作权重总和。
DEFAULT_RANDOM_GENERATE_WEIGHT = 5  # generate 动作相对权重；限制：必须 >= 0，0 表示禁用；调高会增加视频导出场景和运行时间。
DEFAULT_RANDOM_GENERATE_DURATION_SECONDS = 10.0  # 随机测试 generate 视频时长秒数；限制：必须 > 0。
DEFAULT_RANDOM_SHARE_WEIGHT = 7  # share_canvas 动作相对权重；限制：必须 >= 0，0 表示禁用；调高会增加共享/请求共享场景。
DEFAULT_RANDOM_INVALID_WEIGHT = 8  # 非法参数/越权动作相对权重；限制：必须 >= 0，0 表示禁用；调高会增加失败返回码场景。
DEFAULT_RANDOM_DISCONNECT_WEIGHT = 5  # Disconnect/重连动作相对权重；限制：必须 >= 0，0 表示禁用；调高会增加资源释放压力。
DEFAULT_RANDOM_MIN_SPRITES_PER_CLIENT = 10  # 随机多客户端测试中每个客户端预置 sprite 下限；限制：必须 >= 0。
DEFAULT_RANDOM_MIN_PLACEMENTS_PER_CLIENT = 20  # 随机多客户端测试中每个客户端预置 placement 下限；限制：必须 >= 0。
DEFAULT_RANDOM_MIN_CANVASES_PER_CLIENT = 30  # 随机多客户端测试中每个客户端可访问 canvas 下限；限制：必须 >= 0。
DEFAULT_COLLAB_MIN_SPRITES_PER_CLIENT = 10  # 协作动画测试中每个客户端预置 sprite 下限；限制：必须 >= 1。
DEFAULT_COLLAB_MIN_PLACEMENTS_PER_CLIENT = 20  # 协作动画测试中每个客户端预置 placement 下限；限制：必须 >= 1。
DEFAULT_COLLAB_ANIMATION_ROUNDS = 30  # 协作动画压力默认轮数；限制：必须 >= 1，默认值用于保证 5 分钟内完成。
DEFAULT_COLLAB_ANIMATION_FRAME_RATE = 60  # 协作动画帧率；限制：必须 >= 1，帧数/帧率决定视频时长。
DEFAULT_COLLAB_ANIMATION_DURATION_SECONDS = 30.0  # 协作动画 generate 视频时长秒数；限制：必须 > 0。
DEFAULT_COLLAB_ANIMATION_FRAMES = max(2, round(DEFAULT_COLLAB_ANIMATION_DURATION_SECONDS * DEFAULT_COLLAB_ANIMATION_FRAME_RATE))  # 协作动画 generate 帧数；限制：必须 >= 2。
DEFAULT_HUGE_ANIMATION_CLIENTS = 100  # 超大长跑协作动画客户端数；限制：必须 >= 2。
DEFAULT_HUGE_ANIMATION_ROUNDS = 400  # 超大长跑协作动画操作轮数；限制：必须 >= 1。
DEFAULT_HUGE_ANIMATION_MIN_RUNTIME_SECONDS = 600.0  # 超大长跑单个实现最短运行秒数；限制：必须 >= 0，600 约等于 10 分钟。
DEFAULT_HUGE_ANIMATION_CANVAS_WIDTH = 320  # 超大长跑共享画布宽度；限制：必须 >= 32。
DEFAULT_HUGE_ANIMATION_CANVAS_HEIGHT = 240  # 超大长跑共享画布高度；限制：必须 >= 32。
DEFAULT_HUGE_ANIMATION_FRAME_RATE = 50  # 超大长跑最终 generate 帧率；限制：必须 >= 1。
DEFAULT_HUGE_ANIMATION_DURATION_SECONDS = 50.0  # 超大长跑每个 generate 视频时长秒数；限制：必须 >= 20。
DEFAULT_HUGE_ANIMATION_FRAMES = max(2, round(DEFAULT_HUGE_ANIMATION_DURATION_SECONDS * DEFAULT_HUGE_ANIMATION_FRAME_RATE))  # 超大长跑 generate 帧数；限制：必须 >= 2。
DEFAULT_HUGE_ANIMATION_GENERATE_COUNT = 2  # 超大长跑 generate 次数；限制：必须在 1 到 5 之间。
DEFAULT_HUGE_MIN_SPRITES_PER_CLIENT = 20  # 超大长跑每客户端初始 sprite 下限；限制：必须 >= 1。
DEFAULT_HUGE_MIN_PLACEMENTS_PER_CLIENT = 60  # 超大长跑每客户端初始 placement 下限；限制：必须 >= 1。
DEFAULT_HUGE_TIMEOUT = 300.0  # 超大长跑单次响应等待秒数；限制：必须 > 0，generate 大视频时需要较大。
DEFAULT_HUGE_BUILD_TIMEOUT = 30.0  # 超大长跑编译等待秒数；限制：必须 > 0。

STUDENT_FILES = [
    "Makefile",
    "animate_client.c",
    "animate_server.c",
    "queue.c",
    "queue.h",
    "rpc.c",
    "rpc.h",
    "rpc_cleanup.c",
    "rpc_cleanup.h",
    "rpc_tool.c",
    "rpc_tool.h",
    "thread_pool.c",
    "thread_pool.h",
    "timer.c",
    "timer.h",
    "tool.c",
    "tool.h",
    "users.txt",
    "vector.c",
    "vector.h",
]

HANDLE_COMMANDS = {
    "create_canvas",
    "create_sprite",
    "create_rectangle",
    "create_circle",
    "place_sprite",
}


@dataclasses.dataclass
class Event:
    label: str
    response: str


@dataclasses.dataclass
class Step:
    op: str
    client: Optional[str] = None
    command: Optional[str] = None
    store: Optional[str] = None
    expect: Optional[str] = None
    label: Optional[str] = None


@dataclasses.dataclass
class Scenario:
    name: str
    steps: List[Step]
    description: str = ""


@dataclasses.dataclass
class RandomClientState:
    label: str
    username: str
    balance: int
    live: bool = True


@dataclasses.dataclass
class RandomCanvasState:
    name: str
    participants: Set[str]
    alive: bool = True


@dataclasses.dataclass
class RandomSpriteState:
    name: str
    owner: str
    alive: bool = True


@dataclasses.dataclass
class RandomPlacementState:
    name: str
    owner: str
    canvas: str
    sprite: str
    alive: bool = True


class DiffFailure(Exception):
    pass


class BuildFailure(Exception):
    pass


ImplementationDirs = Dict[str, Path]
TimingByImplementation = Dict[str, float]


def parse_implementation_names(raw: str) -> Tuple[str, ...]:
    names = [name.strip().lower() for name in re.split(r"[,\s]+", raw) if name.strip()]
    if names == ["all"]:
        return IMPLEMENTATION_NAMES
    if not names:
        raise ValueError("至少需要选择一个实现")

    selected: List[str] = []
    for name in names:
        if name not in IMPLEMENTATION_NAMES:
            allowed = ", ".join(IMPLEMENTATION_NAMES)
            raise ValueError(f"未知实现 {name!r}；允许值: {allowed} 或 all")
        if name not in selected:
            selected.append(name)
    return tuple(selected)


def copy_implementation_tree(name: str, destination: Path,
                             generated_clients: int) -> None:
    if name == "student":
        copy_student_tree(destination, generated_clients)
    elif name == "python":
        copy_python_tree(destination, generated_clients)
    elif name in REFERENCE_ROOTS:
        copy_reference_tree(name, destination, generated_clients)
    else:
        raise ValueError(f"unknown implementation {name!r}")


def safe_artifact_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip())
    cleaned = cleaned.strip("._")
    return cleaned or "case"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def runtime_output_files(directory: Path) -> List[Path]:
    suffixes = {".mp4", ".dat", ".log"}
    files: List[Path] = []
    for path in directory.rglob("*"):
        if path.is_file() and path.suffix.lower() in suffixes:
            files.append(path)
    return files


def clear_runtime_outputs(implementation_dirs: ImplementationDirs) -> None:
    for directory in implementation_dirs.values():
        for path in runtime_output_files(directory):
            try:
                path.unlink()
            except OSError:
                pass


def copy_file_if_present(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_tree_if_present(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def client_stdout_from_events(events: List[Event]) -> str:
    lines = [
        event.response
        for event in events
        if event.response != "<sent>"
    ]
    return "\n".join(lines) + ("\n" if lines else "")


def client_event_trace(events: List[Event]) -> str:
    lines = [f"{event.label}: {event.response}" for event in events]
    return "\n".join(lines) + ("\n" if lines else "")


def timing_json_value(
    timing_by_implementation: Optional[TimingByImplementation],
) -> Dict[str, float]:
    if not timing_by_implementation:
        return {}
    return {
        implementation: round(seconds, 6)
        for implementation, seconds in timing_by_implementation.items()
    }


def save_case_artifacts(
    case_name: str,
    implementation_dirs: ImplementationDirs,
    metadata: Dict[str, Any],
    events_by_implementation: Optional[Dict[str, List[Event]]] = None,
    problems: Optional[List[str]] = None,
    stdout_by_implementation: Optional[Dict[str, str]] = None,
    stderr_by_implementation: Optional[Dict[str, str]] = None,
    timing_by_implementation: Optional[TimingByImplementation] = None,
) -> None:
    safe_case = safe_artifact_name(case_name)
    case_data_dir = DATA_RUN_DIR / safe_case
    case_video_dir = VIDEO_RUN_DIR / safe_case
    events_by_implementation = events_by_implementation or {}
    problems = problems or []
    stdout_by_implementation = stdout_by_implementation or {}
    stderr_by_implementation = stderr_by_implementation or {}

    write_json(
        case_data_dir / "case.json",
        {
            "run_id": ARTIFACT_RUN_ID,
            "case_name": case_name,
            "metadata": metadata,
            "implementations": list(implementation_dirs),
            "timing_seconds": timing_json_value(timing_by_implementation),
        },
    )
    write_json(
        case_data_dir / "timing.json",
        timing_json_value(timing_by_implementation),
    )
    write_json(
        case_data_dir / "events.json",
        {
            implementation: [
                dataclasses.asdict(event) for event in events
            ]
            for implementation, events in events_by_implementation.items()
        },
    )
    (case_data_dir / "problems.txt").write_text(
        "\n".join(problems) + ("\n" if problems else ""),
        encoding="utf-8",
    )

    for implementation, directory in implementation_dirs.items():
        implementation_data_dir = case_data_dir / implementation
        implementation_data_dir.mkdir(parents=True, exist_ok=True)
        copy_file_if_present(directory / "users.txt",
                             implementation_data_dir / "users.txt")
        copy_tree_if_present(directory / "bmp",
                             implementation_data_dir / "bmp")

        if implementation in stdout_by_implementation:
            (implementation_data_dir / "server_stdout.txt").write_text(
                stdout_by_implementation[implementation],
                encoding="utf-8",
            )
        if implementation in stderr_by_implementation:
            (implementation_data_dir / "server_stderr.txt").write_text(
                stderr_by_implementation[implementation],
                encoding="utf-8",
            )
        if implementation in events_by_implementation:
            (implementation_data_dir / "client_stdout.txt").write_text(
                client_stdout_from_events(events_by_implementation[implementation]),
                encoding="utf-8",
            )
            (implementation_data_dir / "client_events.txt").write_text(
                client_event_trace(events_by_implementation[implementation]),
                encoding="utf-8",
            )
            (implementation_data_dir / "client_stderr.txt").write_text(
                "",
                encoding="utf-8",
            )

        for output in runtime_output_files(directory):
            relative_name = safe_artifact_name(str(output.relative_to(directory)))
            if output.suffix.lower() == ".mp4":
                copy_file_if_present(
                    output,
                    case_video_dir / implementation / relative_name,
                )
            else:
                copy_file_if_present(
                    output,
                    implementation_data_dir / "generated" / relative_name,
                )


def print_artifact_locations() -> None:
    if VIDEO_RUN_DIR.exists():
        print(f"视频产物目录: {VIDEO_RUN_DIR}")
    if DATA_RUN_DIR.exists():
        print(f"复现数据目录: {DATA_RUN_DIR}")


def generated_user_balance(index: int) -> int:
    rng = random.Random(DEFAULT_USERS_SEED + index * 7919)
    return rng.randint(1, 1000)


def random_extra_username(index: int, rng: random.Random) -> str:
    suffix = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(8))
    return f"randuser{index}_{suffix}"


def write_test_users(destination: Path, generated_clients: int) -> None:
    base_users = [
        "ExcitableFabricator 1",
        "UnwillingDeveloper 10",
        "lc 0",
        "JollyPainter -10",
        "lhc 65",
    ]
    stress_users = [
        f"user{i} {generated_user_balance(i)}" for i in range(generated_clients)
    ]
    rng = random.Random(DEFAULT_USERS_SEED + generated_clients)
    random_extra_count = max(4, generated_clients // 4)
    random_extra_users = [
        f"{random_extra_username(i, rng)} {rng.randint(1, 1000)}"
        for i in range(random_extra_count)
    ]
    (destination / "users.txt").write_text(
        "\n".join(base_users + stress_users + random_extra_users) + "\n",
        encoding="utf-8",
    )


def bmp_filename(index: int) -> str:
    return f"bmp/random_{index % DEFAULT_RANDOM_BMP_COUNT:02d}.bmp"


def write_argb32_bmp(path: Path, width: int, height: int,
                     rng: random.Random) -> None:
    row_size = width * 4
    pixel_data_size = row_size * height
    file_header_size = 14
    info_header_size = 124
    pixel_offset = file_header_size + info_header_size
    file_size = pixel_offset + pixel_data_size

    with path.open("wb") as bmp:
        bmp.write(
            struct.pack(
                "<2sIHHI",
                b"BM",
                file_size,
                0,
                0,
                pixel_offset,
            )
        )
        bmp.write(
            struct.pack(
                "<IIIHHIIIIII",
                info_header_size,
                width,
                height,
                1,
                32,
                0,
                pixel_data_size,
                0,
                0,
                0,
                0,
            )
        )
        bmp.write(
            struct.pack(
                "<IIII",
                0x00FF0000,
                0x0000FF00,
                0x000000FF,
                0xFF000000,
            )
        )
        bmp.write(b"\x00" * (info_header_size - 40 - 16))

        for _y in range(height):
            for _x in range(width):
                red = rng.randrange(256)
                green = rng.randrange(256)
                blue = rng.randrange(256)
                alpha = rng.choice([128, 192, 255])
                bmp.write(bytes((blue, green, red, alpha)))


def write_test_bmps(destination: Path) -> None:
    bmp_dir = destination / "bmp"
    bmp_dir.mkdir(exist_ok=True)
    rng = random.Random(DEFAULT_RANDOM_BMP_SEED)
    for index in range(DEFAULT_RANDOM_BMP_COUNT):
        width = rng.choice([1, 2, 3, 4, 8])
        height = rng.choice([1, 2, 3, 5, 8])
        write_argb32_bmp(bmp_dir / f"random_{index:02d}.bmp", width, height,
                         rng)


def copy_student_tree(destination: Path, generated_clients: int) -> None:
    destination.mkdir(parents=True)
    for relative in STUDENT_FILES:
        shutil.copy2(ROOT / relative, destination / relative)
    shutil.copytree(ROOT / "libanimate", destination / "libanimate")
    write_test_users(destination, generated_clients)
    write_test_bmps(destination)


def copy_python_tree(destination: Path, generated_clients: int) -> None:
    ignore = shutil.ignore_patterns(
        "__pycache__",
        "animate_server",
        "animate_client",
        "libanimate_bridge.so",
        "FIFO_*",
        "*.dat",
        "*.mp4",
        "*.log",
        "libanimate",
    )
    shutil.copytree(PYTHON_ROOT, destination, ignore=ignore)
    shutil.copytree(ROOT / "libanimate", destination / "libanimate")
    write_test_users(destination, generated_clients)
    write_test_bmps(destination)


def copy_hai_tree(destination: Path, generated_clients: int) -> None:
    copy_reference_tree("hai", destination, generated_clients)


def copy_dan_tree(destination: Path, generated_clients: int) -> None:
    copy_reference_tree("dan", destination, generated_clients)


def copy_reference_tree(name: str, destination: Path,
                        generated_clients: int) -> None:
    ignore = shutil.ignore_patterns(
        "animate_server", "animate_client", "*.o", "FIFO_*", "server", "client",
        "libanimate"
    )
    shutil.copytree(REFERENCE_ROOTS[name], destination, ignore=ignore)
    shutil.copytree(ROOT / "libanimate", destination / "libanimate")
    write_test_users(destination, generated_clients)
    write_test_bmps(destination)


def run_command(args: List[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


SANITIZER_FLAGS = (
    "-g -O1 -Wall -Wextra -fsanitize=address "
    "-fno-omit-frame-pointer"
)


def build_tree(name: str, cwd: Path, timeout: float,
               sanitize: bool = False) -> None:
    clean = run_command(["make", "clean"], cwd, timeout)
    if clean.returncode != 0:
        raise BuildFailure(
            f"{name}: make clean failed\nSTDOUT:\n{clean.stdout}\nSTDERR:\n{clean.stderr}"
        )
    if sanitize:
        build = run_command(
            [
                "make",
                "animate_server",
                "animate_client",
                f"CFLAGS={SANITIZER_FLAGS}",
                f"FLAGS={SANITIZER_FLAGS}",
            ],
            cwd,
            timeout,
        )
    else:
        build = run_command(["make", "animate_server", "animate_client"], cwd,
                            timeout)
    if build.returncode != 0:
        raise BuildFailure(
            f"{name}: make failed\nSTDOUT:\n{build.stdout}\nSTDERR:\n{build.stderr}"
        )
    for executable in ("animate_server", "animate_client"):
        executable_path = cwd / executable
        if not executable_path.exists() or not os.access(executable_path, os.X_OK):
            raise BuildFailure(
                f"{name}: make did not produce executable {executable}"
            )


def describe_runner_error(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return f"{exc}；超时视为可能死锁/阻塞"
    return str(exc)


def memory_report_problems(name: str, stderr: str) -> List[str]:
    markers = [
        "ERROR: AddressSanitizer",
        "ERROR: LeakSanitizer",
        "LeakSanitizer: detected memory leaks",
        "AddressSanitizer: heap-use-after-free",
        "AddressSanitizer: heap-buffer-overflow",
        "AddressSanitizer: stack-buffer-overflow",
        "AddressSanitizer:DEADLYSIGNAL",
        "AddressSanitizer: SEGV",
    ]
    if not any(marker in stderr for marker in markers):
        return []
    excerpt = "\n".join(stderr.strip().splitlines()[:30])
    return [f"{name}: sanitizer 检测到内存错误/泄漏:\n{excerpt}"]


def read_fd_line(fd: int, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    data = bytearray()
    poller = select.poll()
    poller.register(fd, select.POLLIN | select.POLLHUP | select.POLLERR)
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        events = poller.poll(max(0, int(remaining * 1000)))
        if not events:
            continue
        chunk = os.read(fd, 1)
        if not chunk:
            break
        data.extend(chunk)
        if chunk == b"\n":
            return data.decode(errors="replace").rstrip("\n")
    raise TimeoutError(f"timed out waiting for line; partial={data!r}")


SIGNAL_PROXY_CODE = r"""
import os
import signal
import sys
import time

server_pid = int(sys.argv[1])
received = False

def on_sigusr2(_signum, _frame):
    global received
    received = True

signal.signal(signal.SIGUSR2, on_sigusr2)
print(os.getpid(), flush=True)
os.kill(server_pid, signal.SIGUSR1)
deadline = time.monotonic() + 5.0
while not received and time.monotonic() < deadline:
    signal.pause()
while True:
    time.sleep(3600)
"""


def start_signal_proxy(server_pid: int) -> subprocess.Popen:
    proxy = subprocess.Popen(
        [sys.executable, "-c", SIGNAL_PROXY_CODE, str(server_pid)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    assert proxy.stdout is not None
    line = proxy.stdout.readline().strip()
    if not line or int(line) != proxy.pid:
        proxy.terminate()
        proxy.stdout.close()
        raise RuntimeError(f"failed to start signal proxy for server {server_pid}")
    proxy.stdout.close()
    return proxy


class RawClient:
    def __init__(self, server: "ServerRun", timeout: float):
        self.server = server
        self.timeout = timeout
        self.proxy_proc = start_signal_proxy(server.pid)
        self.proxy_pid = self.proxy_proc.pid
        self.read_buffer = bytearray()
        self.c2s_fd = -1
        self.s2c_fd = -1
        self._open_fifos()

    def _open_fifos(self) -> None:
        c2s = self.server.cwd / f"FIFO_C2S_{self.proxy_pid}"
        s2c = self.server.cwd / f"FIFO_S2C_{self.proxy_pid}"
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if c2s.exists() and s2c.exists():
                break
            time.sleep(0.01)
        else:
            raise TimeoutError(f"server did not create FIFOs for pid {self.proxy_pid}")

        self.s2c_fd = os.open(s2c, os.O_RDONLY | os.O_NONBLOCK)
        while time.monotonic() < deadline:
            try:
                self.c2s_fd = os.open(c2s, os.O_WRONLY | os.O_NONBLOCK)
                return
            except OSError as exc:
                if exc.errno != errno.ENXIO:
                    raise
                time.sleep(0.01)
        raise TimeoutError(f"server did not open C2S FIFO for pid {self.proxy_pid}")

    def send(self, command: str) -> None:
        payload = command.encode() + b"\n"
        written = 0
        while written < len(payload):
            try:
                written += os.write(self.c2s_fd, payload[written:])
            except BlockingIOError:
                time.sleep(0.01)

    def read_line(self) -> str:
        deadline = time.monotonic() + self.timeout
        poller = select.poll()
        poller.register(
            self.s2c_fd, select.POLLIN | select.POLLHUP | select.POLLERR
        )
        while time.monotonic() < deadline:
            if b"\n" in self.read_buffer:
                line, _, rest = self.read_buffer.partition(b"\n")
                self.read_buffer = bytearray(rest)
                return line.decode(errors="replace")
            remaining = deadline - time.monotonic()
            events = poller.poll(max(0, int(remaining * 1000)))
            if not events:
                continue
            try:
                chunk = os.read(self.s2c_fd, 4096)
            except BlockingIOError:
                continue
            if not chunk:
                time.sleep(0.01)
                continue
            self.read_buffer.extend(chunk)
        raise TimeoutError(
            f"timed out waiting for server response; partial={bytes(self.read_buffer)!r}"
        )

    def request(self, command: str) -> str:
        self.send(command)
        return self.read_line()

    def close(self) -> None:
        for fd in (self.c2s_fd, self.s2c_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self.c2s_fd = -1
        self.s2c_fd = -1
        if self.proxy_pid > 0:
            if self.proxy_proc.poll() is None:
                self.proxy_proc.terminate()
                try:
                    self.proxy_proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.proxy_proc.kill()
                    self.proxy_proc.wait(timeout=1)
            if (
                self.proxy_proc.stdout is not None
                and not self.proxy_proc.stdout.closed
            ):
                self.proxy_proc.stdout.close()
            self.proxy_pid = -1


class ServerRun:
    def __init__(
        self,
        name: str,
        cwd: Path,
        threads: int,
        timeout: float,
        memory_check: bool = False,
    ):
        self.name = name
        self.cwd = cwd
        self.timeout = timeout
        self.memory_check = memory_check
        env = os.environ.copy()
        if memory_check:
            env["ASAN_OPTIONS"] = (
                "detect_leaks=1:halt_on_error=0:abort_on_error=0:"
                "allocator_may_return_null=1:strict_string_checks=1"
            )
            env["LSAN_OPTIONS"] = "suppressions=/dev/null"
        self.proc = subprocess.Popen(
            [str(cwd / "animate_server"), str(threads)],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
        assert self.proc.stdout is not None
        line = read_fd_line(self.proc.stdout.fileno(), timeout)
        match = re.search(r"Server PID:\s*(\d+)", line)
        if not match:
            self.stop()
            raise RuntimeError(f"{name}: unexpected server startup line: {line!r}")
        self.pid = int(match.group(1))
        self.clients: List[RawClient] = []

    def connect(self) -> RawClient:
        client = RawClient(self, self.timeout)
        self.clients.append(client)
        return client

    def stop(self) -> Tuple[str, str]:
        for client in list(self.clients):
            client.close()
        self.clients.clear()
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.proc.wait(timeout=2)

        stdout = b""
        stderr = b""
        if self.proc.stdout is not None:
            stdout = self.proc.stdout.read() or b""
            self.proc.stdout.close()
        if self.proc.stderr is not None:
            stderr = self.proc.stderr.read() or b""
            self.proc.stderr.close()
        return stdout.decode(errors="replace"), stderr.decode(errors="replace")


def command_name(command_template: str) -> str:
    return command_template.split()[0] if command_template.split() else ""


def normalize_response(command_template: str, response: str, store: Optional[str]) -> str:
    if store is not None:
        parts = response.split()
        if len(parts) == 2 and parts[0] == "0" and parts[1].isdigit():
            return f"0 <{store}>"
        return response

    if command_name(command_template) in HANDLE_COMMANDS:
        parts = response.split()
        if len(parts) == 2 and parts[0] == "0" and parts[1].isdigit():
            return "0 <handle>"
    return response


def substitute(template: str, variables: Dict[str, str]) -> str:
    try:
        return template.format(**variables)
    except KeyError as exc:
        missing = exc.args[0]
        raise DiffFailure(f"missing handle variable {{{missing}}} for {template!r}")


def run_scenario_on_server(
    server: ServerRun, scenario: Scenario, verbose: bool
) -> List[Event]:
    clients: Dict[str, RawClient] = {}
    variables: Dict[str, str] = {}
    events: List[Event] = []

    def get_client(name: str) -> RawClient:
        if name not in clients:
            raise DiffFailure(f"client {name!r} has not been connected")
        return clients[name]

    try:
        for step in scenario.steps:
            if step.op == "connect":
                assert step.client is not None
                clients[step.client] = server.connect()
                continue

            if step.op == "send":
                assert step.client is not None and step.command is not None
                command = substitute(step.command, variables)
                if verbose:
                    print(f"[{server.name}] {step.client} -> {command}")
                get_client(step.client).send(command)
                continue

            if step.op == "request":
                assert step.client is not None and step.command is not None
                command = substitute(step.command, variables)
                if verbose:
                    print(f"[{server.name}] {step.client} -> {command}")
                try:
                    response = get_client(step.client).request(command)
                except Exception as exc:
                    raise type(exc)(
                        f"{scenario.name}: {server.name}: while waiting for "
                        f"{command!r}: {exc}"
                    ) from exc
                if verbose:
                    print(f"[{server.name}] {step.client} <- {response}")
                if step.expect is not None and response != step.expect:
                    raise DiffFailure(
                        f"{scenario.name}: {server.name}: expected {step.expect!r} "
                        f"from {step.command!r}, got {response!r}"
                    )
                if step.store is not None:
                    parts = response.split()
                    if len(parts) != 2 or parts[0] != "0":
                        raise DiffFailure(
                            f"{scenario.name}: {server.name}: could not store handle "
                            f"{step.store!r} from response {response!r}"
                        )
                    variables[step.store] = parts[1]
                events.append(
                    Event(
                        step.label or f"{step.client}: {step.command}",
                        normalize_response(step.command, response, step.store),
                    )
                )
                continue

            if step.op == "read":
                assert step.client is not None
                try:
                    response = get_client(step.client).read_line()
                except Exception as exc:
                    raise type(exc)(
                        f"{scenario.name}: {server.name}: while waiting for "
                        f"async response on {step.client}: {exc}"
                    ) from exc
                if verbose:
                    print(f"[{server.name}] {step.client} <- {response}")
                if step.expect is not None and response != step.expect:
                    raise DiffFailure(
                        f"{scenario.name}: {server.name}: expected async "
                        f"{step.expect!r}, got {response!r}"
                    )
                events.append(Event(step.label or f"{step.client}: <read>", response))
                continue

            if step.op == "disconnect":
                assert step.client is not None
                client = get_client(step.client)
                try:
                    client.send("Disconnect")
                finally:
                    time.sleep(0.05)
                    client.close()
                events.append(Event(f"{step.client}: Disconnect", "<sent>"))
                continue

            raise DiffFailure(f"unknown step op {step.op!r}")
    finally:
        for client in clients.values():
            client.close()

    return events


def scripted_scenarios() -> List[Scenario]:
    return [
        Scenario(
            "single_client_core",
            [
                Step("connect", "a"),
                Step("request", "a", "Login lhc", expect="65"),
                Step("request", "a", "create_canvas 12 16 0", store="canvas"),
                Step("request", "a", "create_sprite bmp/random_00.bmp",
                     store="bitmap"),
                Step(
                    "request",
                    "a",
                    "create_rectangle 3 4 12345 1",
                    store="rect",
                ),
                Step("request", "a", "create_circle 2 54321 1", store="circle"),
                Step(
                    "request",
                    "a",
                    "place_sprite {canvas} {rect} 1 2",
                    store="placement",
                ),
                Step("request", "a", "placement_up {placement}", expect="0"),
                Step("request", "a", "placement_down {placement}", expect="0"),
                Step("request", "a", "placement_top {placement}", expect="0"),
                Step("request", "a", "placement_bottom {placement}", expect="0"),
                Step(
                    "request",
                    "a",
                    "set_animation_params {placement} 1 2 3 4",
                    expect="0",
                ),
                Step("request", "a", "generate {canvas} fixed_single 0 0 1",
                     expect="0 0 0"),
                Step("request", "a", "destroy_placement {placement}", expect="0"),
                Step("request", "a", "destroy_sprite {bitmap}", expect="0 0"),
                Step("request", "a", "destroy_sprite {rect}", expect="0 0"),
                Step("request", "a", "destroy_sprite {circle}", expect="0 0"),
                Step("request", "a", "destroy_canvas {canvas}", expect="0"),
                Step("disconnect", "a"),
            ],
            "固定场景：单客户端完整生命周期，覆盖登录、create 四类、放置、placement 四类、动画参数、generate 和销毁。",
        ),
        Scenario(
            "invalid_arguments",
            [
                Step("connect", "a"),
                Step("request", "a", "Login lhc", expect="65"),
                Step("request", "a", "create_canvas 1 2", expect="-1"),
                Step("request", "a", "create_rectangle 3 4 12345 2", expect="-2"),
                Step("request", "a", "place_sprite 999 999 0 0", expect="-2"),
                Step("request", "a", "destroy_canvas 999", expect="-2"),
                Step("disconnect", "a"),
            ],
            "固定场景：参数数量错误、非法布尔值、无效句柄等基础失败返回码。",
        ),
        Scenario(
            "creator_share_and_barrier",
            [
                Step("connect", "a"),
                Step("connect", "b"),
                Step("request", "a", "Login lhc", expect="65"),
                Step("request", "b", "Login UnwillingDeveloper", expect="10"),
                Step("request", "a", "create_canvas 8 8 0", store="canvas"),
                Step("request", "a", "share_canvas {canvas} UnwillingDeveloper", expect="0"),
                Step("send", "b", "barrier {canvas}"),
                Step("send", "a", "barrier {canvas}"),
                Step("read", "a", expect="0", label="a: barrier released"),
                Step("read", "b", expect="0", label="b: barrier released"),
                Step("disconnect", "b"),
                Step("disconnect", "a"),
            ],
            "固定场景：创建者共享画布给另一个在线用户，然后两个客户端同时进入 barrier 并释放。",
        ),
        Scenario(
            "barrier_waiter_disconnect_release",
            [
                Step("connect", "a"),
                Step("connect", "b"),
                Step("request", "a", "Login lhc", expect="65"),
                Step("request", "b", "Login UnwillingDeveloper", expect="10"),
                Step("request", "a", "create_canvas 8 8 0", store="canvas"),
                Step("request", "a", "share_canvas {canvas} UnwillingDeveloper",
                     expect="0"),
                Step("send", "b", "barrier {canvas}"),
                Step("disconnect", "b"),
                Step("request", "a", "barrier {canvas}", expect="0",
                     label="a: barrier released after b disconnect"),
                Step("disconnect", "a"),
            ],
            "极端固定场景：一个 barrier 等待者断连后，剩余在线参与者应立即释放 barrier。",
        ),
    ]


def random_scenario(seed: int, operations: int) -> Scenario:
    rng = random.Random(seed)
    steps: List[Step] = [
        Step("connect", "a"),
        Step("request", "a", "Login lhc", expect="65"),
        Step("request", "a", "create_canvas 20 20 0", store="canvas0"),
    ]
    sprites: List[str] = []
    placements: List[str] = []
    sprite_index = 0
    placement_index = 0

    for index in range(operations):
        choice_pool = ["bmp_sprite", "rect", "circle"]
        if sprites:
            choice_pool.extend(["place", "destroy_sprite"])
        if placements:
            choice_pool.extend(["move", "params", "destroy_placement"])

        choice = rng.choice(choice_pool)
        if choice == "bmp_sprite":
            name = f"bmp_sprite{sprite_index}"
            sprite_index += 1
            steps.append(
                Step(
                    "request",
                    "a",
                    f"create_sprite {bmp_filename(rng.randrange(DEFAULT_RANDOM_BMP_COUNT))}",
                    store=name,
                )
            )
            sprites.append(name)
        elif choice == "rect":
            name = f"rect{sprite_index}"
            sprite_index += 1
            steps.append(
                Step(
                    "request",
                    "a",
                    f"create_rectangle {rng.randint(1, 4)} {rng.randint(1, 4)} "
                    f"{rng.randint(0, 0xFFFFFF)} 0",
                    store=name,
                )
            )
            sprites.append(name)
        elif choice == "circle":
            name = f"circle{sprite_index}"
            sprite_index += 1
            steps.append(
                Step(
                    "request",
                    "a",
                    f"create_circle {rng.randint(1, 4)} {rng.randint(0, 0xFFFFFF)} 1",
                    store=name,
                )
            )
            sprites.append(name)
        elif choice == "place":
            sprite = rng.choice(sprites)
            name = f"placement{placement_index}"
            placement_index += 1
            steps.append(
                Step(
                    "request",
                    "a",
                    f"place_sprite {{canvas0}} {{{sprite}}} "
                    f"{rng.randint(-3, 3)} {rng.randint(-3, 3)}",
                    store=name,
                )
            )
            placements.append(name)
        elif choice == "move":
            placement = rng.choice(placements)
            move = rng.choice(
                ["placement_up", "placement_down", "placement_top", "placement_bottom"]
            )
            steps.append(Step("request", "a", f"{move} {{{placement}}}", expect="0"))
        elif choice == "params":
            placement = rng.choice(placements)
            steps.append(
                Step(
                    "request",
                    "a",
                    f"set_animation_params {{{placement}}} "
                    f"{rng.randint(-2, 2)} {rng.randint(-2, 2)} "
                    f"{rng.randint(-2, 2)} {rng.randint(-2, 2)}",
                    expect="0",
                )
            )
        elif choice == "destroy_placement":
            placement = rng.choice(placements)
            steps.append(
                Step("request", "a", f"destroy_placement {{{placement}}}", expect="0")
            )
            placements.remove(placement)
        elif choice == "destroy_sprite":
            sprite = rng.choice(sprites)
            # 只销毁没有被已知存活 placement 引用的 sprite。
            # 这样可以避免随机测试被不同实现的“使用中 sprite 清理策略”干扰。
            if placements:
                continue
            steps.append(Step("request", "a", f"destroy_sprite {{{sprite}}}", expect="0 0"))
            sprites.remove(sprite)

    for placement in list(placements):
        steps.append(Step("request", "a", f"destroy_placement {{{placement}}}", expect="0"))
    for sprite in list(sprites):
        steps.append(Step("request", "a", f"destroy_sprite {{{sprite}}}", expect="0 0"))
    steps.extend(
        [
            Step("request", "a", "destroy_canvas {canvas0}", expect="0"),
            Step("disconnect", "a"),
        ]
    )
    return Scenario(
        f"random_seed_{seed}",
        steps,
        f"随机场景：单客户端确定性随机资源操作，seed={seed}，操作数={operations}。",
    )


def random_multiclient_scenario(
    seed: int,
    client_count: int,
    commands_per_client: int,
    create_weight: int = DEFAULT_RANDOM_CREATE_WEIGHT,
    place_sprite_weight: int = DEFAULT_RANDOM_PLACE_SPRITE_WEIGHT,
    placement_weight: int = DEFAULT_RANDOM_PLACEMENT_WEIGHT,
    set_animation_weight: int = DEFAULT_RANDOM_SET_ANIMATION_WEIGHT,
    destroy_canvas_weight: int = DEFAULT_RANDOM_DESTROY_CANVAS_WEIGHT,
    destroy_sprite_weight: int = DEFAULT_RANDOM_DESTROY_SPRITE_WEIGHT,
    destroy_placement_weight: int = DEFAULT_RANDOM_DESTROY_PLACEMENT_WEIGHT,
    barrier_weight: int = DEFAULT_RANDOM_BARRIER_WEIGHT,
    generate_weight: int = DEFAULT_RANDOM_GENERATE_WEIGHT,
    share_weight: int = DEFAULT_RANDOM_SHARE_WEIGHT,
    invalid_weight: int = DEFAULT_RANDOM_INVALID_WEIGHT,
    disconnect_weight: int = DEFAULT_RANDOM_DISCONNECT_WEIGHT,
    generate_duration_seconds: float = DEFAULT_RANDOM_GENERATE_DURATION_SECONDS,
    min_sprites_per_client: int = DEFAULT_RANDOM_MIN_SPRITES_PER_CLIENT,
    min_placements_per_client: int = DEFAULT_RANDOM_MIN_PLACEMENTS_PER_CLIENT,
    min_canvases_per_client: int = DEFAULT_RANDOM_MIN_CANVASES_PER_CLIENT,
) -> Scenario:
    if client_count < 2:
        raise ValueError("多客户端随机测试至少需要 2 个客户端")
    if commands_per_client < 1:
        raise ValueError("commands_per_client 必须 >= 1")
    if generate_duration_seconds <= 0:
        raise ValueError("generate_duration_seconds 必须 > 0")
    if min_sprites_per_client < 0:
        raise ValueError("min_sprites_per_client 必须 >= 0")
    if min_placements_per_client < 0:
        raise ValueError("min_placements_per_client 必须 >= 0")
    if min_canvases_per_client < 0:
        raise ValueError("min_canvases_per_client 必须 >= 0")

    rng = random.Random(seed)
    steps: List[Step] = []
    clients: Dict[str, RandomClientState] = {
        f"c{i}": RandomClientState(
            f"c{i}", f"user{i}", generated_user_balance(i)
        )
        for i in range(client_count)
    }
    command_counts: Dict[str, int] = {label: 0 for label in clients}
    canvases: Dict[str, RandomCanvasState] = {}
    sprites: Dict[str, RandomSpriteState] = {}
    placements: Dict[str, RandomPlacementState] = {}
    canvas_index = 0
    sprite_index = 0
    placement_index = 0
    generate_index = 0

    def count_command(label: str) -> None:
        command_counts[label] += 1

    def add_request(
        label: str,
        command: str,
        store: Optional[str] = None,
        expect: Optional[str] = None,
        event_label: Optional[str] = None,
    ) -> None:
        steps.append(Step("request", label, command, store=store, expect=expect,
                          label=event_label))
        count_command(label)

    def add_disconnect(label: str) -> None:
        if not clients[label].live:
            return
        steps.append(Step("disconnect", label))
        count_command(label)
        clients[label].live = False
        for canvas_state in canvases.values():
            if not canvas_state.alive:
                continue
            canvas_state.participants.discard(label)
            if not canvas_state.participants:
                retire_canvas(canvas_state.name)
        for sprite_state in sprites.values():
            if sprite_state.owner == label:
                sprite_state.alive = False
        for placement_state in placements.values():
            if placement_state.owner == label:
                placement_state.alive = False

    def reconnect(label: str) -> None:
        if clients[label].live:
            return
        steps.append(Step("connect", label))
        clients[label].live = True
        add_request(label, f"Login {clients[label].username}",
                    expect=str(clients[label].balance),
                    event_label=f"{label}: relogin")

    def live_labels() -> List[str]:
        return [label for label, state in clients.items() if state.live]

    def choose_live_label() -> str:
        live = live_labels()
        if not live:
            reconnect(rng.choice(list(clients)))
            live = live_labels()
        return rng.choice(live)

    def live_canvases() -> List[RandomCanvasState]:
        return [state for state in canvases.values() if state.alive]

    def retire_canvas(canvas_name: str) -> None:
        if canvas_name in canvases:
            canvases[canvas_name].alive = False
        for placement_state in placements.values():
            if placement_state.canvas == canvas_name:
                placement_state.alive = False

    def accessible_canvases(label: str) -> List[RandomCanvasState]:
        return [
            state
            for state in live_canvases()
            if label in state.participants and clients[label].live
        ]

    def owned_live_sprites(label: str) -> List[RandomSpriteState]:
        return [
            state
            for state in sprites.values()
            if state.alive and state.owner == label and clients[label].live
        ]

    def owned_live_placements(label: str) -> List[RandomPlacementState]:
        return [
            state
            for state in placements.values()
            if state.alive and state.owner == label and clients[label].live
        ]

    def create_canvas(label: str) -> RandomCanvasState:
        nonlocal canvas_index
        name = f"mc_canvas_{canvas_index}"
        canvas_index += 1
        height = rng.choice([50, 20])
        width = rng.choice([10, 20])
        color = rng.randint(0, 0xFFFFFF)
        add_request(label, f"create_canvas {height} {width} {color}", store=name,
                    event_label=f"{label}: create_canvas {name}")
        state = RandomCanvasState(name, {label})
        canvases[name] = state
        return state

    def create_sprite(label: str,
                      kind: Optional[str] = None) -> RandomSpriteState:
        nonlocal sprite_index
        name = f"mc_sprite_{sprite_index}"
        sprite_index += 1
        color = rng.randint(0, 0xFFFFFF)
        filled = rng.randint(0, 1)
        kind = kind or rng.choice(["bmp", "rectangle", "circle"])
        if kind == "bmp":
            command = (
                f"create_sprite "
                f"{bmp_filename(rng.randrange(DEFAULT_RANDOM_BMP_COUNT))}"
            )
        elif kind == "rectangle":
            width = rng.choice([1, 2, 3, 4, 8])
            height = rng.choice([1, 2, 3, 5, 8])
            command = f"create_rectangle {width} {height} {color} {filled}"
        else:
            radius = rng.choice([1, 2, 3, 4, 6])
            command = f"create_circle {radius} {color} {filled}"
        add_request(label, command, store=name,
                    event_label=f"{label}: create_sprite {name}")
        state = RandomSpriteState(name, label)
        sprites[name] = state
        return state

    def create_any_resource(label: str) -> None:
        kind = rng.choice(["canvas", "bmp", "rectangle", "circle"])
        if kind == "canvas":
            create_canvas(label)
        else:
            create_sprite(label, kind)

    def ensure_canvas(label: str) -> RandomCanvasState:
        choices = accessible_canvases(label)
        if choices:
            return rng.choice(choices)
        return create_canvas(label)

    def ensure_sprite(label: str) -> RandomSpriteState:
        choices = owned_live_sprites(label)
        if choices:
            return rng.choice(choices)
        return create_sprite(label)

    def place_sprite(label: str) -> Optional[RandomPlacementState]:
        nonlocal placement_index
        canvas_state = ensure_canvas(label)
        sprite_state = ensure_sprite(label)
        name = f"mc_placement_{placement_index}"
        placement_index += 1
        x = rng.randint(-5, 8)
        y = rng.randint(-5, 8)
        add_request(
            label,
            f"place_sprite {{{canvas_state.name}}} {{{sprite_state.name}}} {x} {y}",
            store=name,
            event_label=f"{label}: place_sprite {name}",
        )
        state = RandomPlacementState(name, label, canvas_state.name, sprite_state.name)
        placements[name] = state
        return state

    def share_canvas() -> None:
        live = live_labels()
        if len(live) < 2:
            reconnect(rng.choice(list(clients)))
            live = live_labels()
        canvas_choices = [
            canvas_state
            for canvas_state in live_canvases()
            if any(label in canvas_state.participants for label in live)
        ]
        if not canvas_choices:
            create_canvas(rng.choice(live))
            canvas_choices = live_canvases()
        canvas_state = rng.choice(canvas_choices)
        participants = [
            label
            for label in live
            if label in canvas_state.participants
        ]
        outsiders = [
            label
            for label in live
            if label not in canvas_state.participants
        ]

        if participants and outsiders and rng.choice([True, False]):
            caller = rng.choice(participants)
            target = rng.choice(outsiders)
            add_request(
                caller,
                f"share_canvas {{{canvas_state.name}}} {clients[target].username}",
                event_label=f"{caller}: share_canvas grant",
            )
            canvas_state.participants.add(target)
        elif participants and outsiders:
            caller = rng.choice(outsiders)
            peer = rng.choice(participants)
            add_request(
                caller,
                f"share_canvas {{{canvas_state.name}}} {clients[peer].username}",
                event_label=f"{caller}: share_canvas request_probe",
            )
            canvas_state.participants.add(caller)
        else:
            caller = rng.choice(live)
            add_request(
                caller,
                f"share_canvas {{{canvas_state.name}}} MissingUser{seed}",
                event_label=f"{caller}: share_canvas invalid_user",
            )

    def barrier_group() -> None:
        canvas_choices = [
            canvas_state
            for canvas_state in live_canvases()
            if any(label in canvas_state.participants and clients[label].live
                   for label in canvas_state.participants)
        ]
        if not canvas_choices:
            canvas_state = create_canvas(choose_live_label())
        else:
            canvas_state = rng.choice(canvas_choices)

        participants = sorted(
            label
            for label in canvas_state.participants
            if clients[label].live
        )
        if not participants:
            return
        for label in participants:
            steps.append(Step("send", label, f"barrier {{{canvas_state.name}}}",
                              label=f"{label}: barrier send"))
            count_command(label)
        for label in participants:
            steps.append(Step("read", label,
                              label=f"{label}: barrier {canvas_state.name}"))

    def generate(label: str) -> None:
        nonlocal generate_index
        canvas_state = ensure_canvas(label)
        filename = f"rand_{seed}_{generate_index}_{label}"
        generate_index += 1
        if rng.random() < 0.75:
            start = rng.randint(0, 2)
            frame_rate = rng.choice([1, 2, 5])
            frame_count = max(1, round(generate_duration_seconds * frame_rate))
            end = start + frame_count - 1
            command = (
                f"generate {{{canvas_state.name}}} {filename} "
                f"{start} {end} {frame_rate}"
            )
        else:
            command = rng.choice(
                [
                    f"generate {{{canvas_state.name}}} {filename} 3 1 1",
                    f"generate {{{canvas_state.name}}} {filename} 0 1 0",
                    f"generate {{{canvas_state.name}}} {filename} -1 1 1",
                ]
            )
        add_request(label, command, event_label=f"{label}: generate")

    def unauthorized_or_invalid(label: str) -> None:
        invalid_templates = [
            "create_canvas 1 2",
            "create_canvas -1 2 0",
            "create_canvas 06959 1 0",
            "create_canvas 999999999999999999999999 1 0",
            "create_sprite",
            "create_sprite bmp/missing_random.bmp extra",
            "create_sprite bmp/missing_random.bmp",
            "create_rectangle 1 2 12345 2",
            "create_rectangle 0 2 12345 1",
            "create_circle 0 12345 1",
            "create_circle 2 999999999999999999999 1",
            "place_sprite 999999 888888 1 1",
            "placement_top 999999",
            "set_animation_params 999999 1 2 3 4",
            "destroy_canvas 999999",
            "destroy_sprite 999999",
            "destroy_placement 999999",
            "share_canvas 999999 user0",
            "barrier 999999",
            "generate 999999 bad_output 0 1 1",
            "unknown_rpc 1 2 3",
        ]
        commands: List[Tuple[str, str]] = [
            (command, f"{label}: invalid") for command in invalid_templates
        ]

        foreign_sprites = [
            sprite_state
            for sprite_state in sprites.values()
            if sprite_state.alive and sprite_state.owner != label
        ]
        if foreign_sprites:
            sprite_state = rng.choice(foreign_sprites)
            commands.append((f"destroy_sprite {{{sprite_state.name}}}",
                             f"{label}: unauthorized destroy_sprite"))

        foreign_placements = [
            placement_state
            for placement_state in placements.values()
            if placement_state.alive and placement_state.owner != label
        ]
        if foreign_placements:
            placement_state = rng.choice(foreign_placements)
            commands.append((f"placement_top {{{placement_state.name}}}",
                             f"{label}: unauthorized placement_top"))
            commands.append((f"destroy_placement {{{placement_state.name}}}",
                             f"{label}: unauthorized destroy_placement"))

        inaccessible_canvases = [
            canvas_state
            for canvas_state in live_canvases()
            if label not in canvas_state.participants
        ]
        if inaccessible_canvases:
            canvas_state = rng.choice(inaccessible_canvases)
            commands.append((f"barrier {{{canvas_state.name}}}",
                             f"{label}: unauthorized barrier"))
            commands.append((f"generate {{{canvas_state.name}}} bad_access 0 1 1",
                             f"{label}: unauthorized generate"))

        command, event_label = rng.choice(commands)
        add_request(label, command, event_label=event_label)

    def seed_minimum_resource_pool() -> None:
        labels = list(clients)
        for canvas_number in range(min_canvases_per_client):
            owner = labels[canvas_number % len(labels)]
            canvas_state = create_canvas(owner)
            for target in labels:
                if target == owner:
                    continue
                add_request(
                    owner,
                    f"share_canvas {{{canvas_state.name}}} "
                    f"{clients[target].username}",
                    expect="0",
                    event_label=(
                        f"{owner}: seed share_canvas {canvas_state.name} "
                        f"to {target}"
                    ),
                )
                canvas_state.participants.add(target)

        for label in labels:
            while len(owned_live_sprites(label)) < min_sprites_per_client:
                create_sprite(label)

        for label in labels:
            while len(owned_live_placements(label)) < min_placements_per_client:
                place_sprite(label)

    for label, state in clients.items():
        steps.append(Step("connect", label))
        add_request(label, f"Login {state.username}", expect=str(state.balance),
                    event_label=f"{label}: login")

    seed_minimum_resource_pool()

    action_pool = (
        ["create"] * max(0, create_weight)
        + ["place_sprite"] * max(0, place_sprite_weight)
        + ["placement"] * max(0, placement_weight)
        + ["set_animation_params"] * max(0, set_animation_weight)
        + ["destroy_canvas"] * max(0, destroy_canvas_weight)
        + ["destroy_sprite"] * max(0, destroy_sprite_weight)
        + ["destroy_placement"] * max(0, destroy_placement_weight)
        + ["share"] * max(0, share_weight)
        + ["barrier"] * max(0, barrier_weight)
        + ["generate"] * max(0, generate_weight)
        + ["invalid"] * max(0, invalid_weight)
        + ["disconnect"] * max(0, disconnect_weight)
    )
    if not action_pool:
        raise ValueError("随机动作权重总和必须 > 0")
    target_commands = sum(command_counts.values()) + client_count * commands_per_client
    while sum(command_counts.values()) < target_commands:
        action = rng.choice(action_pool)
        label = choose_live_label()

        if action == "create":
            create_any_resource(label)
        elif action == "place_sprite":
            place_sprite(label)
        elif action == "placement":
            placement_choices = owned_live_placements(label)
            if not placement_choices:
                place_sprite(label)
            else:
                placement_state = rng.choice(placement_choices)
                operation = rng.choice(
                    [
                        "placement_up",
                        "placement_down",
                        "placement_top",
                        "placement_bottom",
                    ]
                )
                add_request(label, f"{operation} {{{placement_state.name}}}",
                            event_label=f"{label}: {operation}")
        elif action == "set_animation_params":
            placement_choices = owned_live_placements(label)
            if not placement_choices:
                place_sprite(label)
            else:
                placement_state = rng.choice(placement_choices)
                add_request(
                    label,
                    f"set_animation_params {{{placement_state.name}}} "
                    f"{rng.randint(-3, 3)} {rng.randint(-3, 3)} "
                    f"{rng.randint(-3, 3)} {rng.randint(-3, 3)}",
                    event_label=f"{label}: set_animation_params",
                )
        elif action == "destroy_canvas":
            own_canvases = accessible_canvases(label)
            if own_canvases:
                canvas_state = rng.choice(own_canvases)
                add_request(label, f"destroy_canvas {{{canvas_state.name}}}",
                            event_label=f"{label}: destroy_canvas")
                retire_canvas(canvas_state.name)
            else:
                create_canvas(label)
        elif action == "destroy_sprite":
            unused_sprites = [
                sprite_state
                for sprite_state in owned_live_sprites(label)
                if not any(
                    placement_state.alive
                    and placement_state.sprite == sprite_state.name
                    for placement_state in placements.values()
                )
            ]
            if unused_sprites:
                sprite_state = rng.choice(unused_sprites)
                add_request(label, f"destroy_sprite {{{sprite_state.name}}}",
                            event_label=f"{label}: destroy_sprite")
                sprite_state.alive = False
            else:
                create_sprite(label)
        elif action == "destroy_placement":
            owned_placements = owned_live_placements(label)
            if owned_placements:
                placement_state = rng.choice(owned_placements)
                add_request(label, f"destroy_placement {{{placement_state.name}}}",
                            event_label=f"{label}: destroy_placement")
                placement_state.alive = False
            else:
                place_sprite(label)
        elif action == "share":
            share_canvas()
        elif action == "barrier":
            barrier_group()
        elif action == "generate":
            generate(label)
        elif action == "invalid":
            unauthorized_or_invalid(label)
        elif action == "disconnect":
            live = live_labels()
            if len(live) > 1:
                add_disconnect(label)
                if rng.random() < 0.65:
                    reconnect(label)
            else:
                reconnect(label)

    for label in list(clients):
        if clients[label].live:
            add_disconnect(label)

    return Scenario(
        f"random_multi_seed_{seed}",
        steps,
        "随机场景：多客户端确定性随机 RPC，覆盖创建、放置、移动、销毁、"
        f"越界、越权、share、barrier、generate、断连重连；seed={seed}，"
        f"客户端={client_count}，预置每客户端 sprite>={min_sprites_per_client}、"
        f"placement>={min_placements_per_client}、"
        f"canvas>={min_canvases_per_client}，随机 generate 时长约 "
        f"{generate_duration_seconds:g}s，预置后每客户端约 "
        f"{commands_per_client} 条随机命令。",
    )


def compare_events(name: str, baseline_name: str, baseline: List[Event],
                   other_name: str, other: List[Event]) -> List[str]:
    problems: List[str] = []
    max_len = max(len(baseline), len(other))
    for index in range(max_len):
        if index >= len(baseline):
            problems.append(
                f"{name}: extra {other_name} event {index}: {other[index]}"
            )
            continue
        if index >= len(other):
            problems.append(
                f"{name}: extra {baseline_name} event {index}: "
                f"{baseline[index]}"
            )
            continue
        if baseline[index].label != other[index].label:
            problems.append(
                f"{name}: event label mismatch at {index}: "
                f"{baseline_name}={baseline[index].label!r}, "
                f"{other_name}={other[index].label!r}"
            )
            continue
        if baseline[index].response != other[index].response:
            problems.append(
                f"{name}: response mismatch at {baseline[index].label!r}: "
                f"{baseline_name}={baseline[index].response!r}, "
                f"{other_name}={other[index].response!r}"
            )
    return problems


def compare_event_sets(name: str,
                       events_by_implementation: Dict[str, List[Event]]) -> List[str]:
    if not events_by_implementation:
        return [f"{name}: no implementation produced events"]

    baseline_name = (
        "python" if "python" in events_by_implementation
        else "student" if "student" in events_by_implementation
        else next(iter(events_by_implementation))
    )
    baseline = events_by_implementation[baseline_name]
    problems: List[str] = []
    for other_name, other_events in events_by_implementation.items():
        if other_name == baseline_name:
            continue
        problems.extend(
            compare_events(name, baseline_name, baseline, other_name, other_events)
        )
    return problems


def runtime_output_map(directory: Path) -> Dict[str, Path]:
    return {
        str(path.relative_to(directory)): path
        for path in runtime_output_files(directory)
    }


def comparable_runtime_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix.lower() != ".log":
        return data

    text = data.decode(errors="replace")
    replacements = [
        (r"0x[0-9A-Fa-f]+", "0xADDR"),
        (r"speed=\s*[^ \r\n]+", "speed=<runtime>"),
        (r"bitrate=\s*[^ \r\n]+", "bitrate=<runtime>"),
        (r"fps=\s*[^ \r\n]+", "fps=<runtime>"),
        (r"time=\s*[^ \r\n]+", "time=<runtime>"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text.encode()


def compare_python_runtime_outputs(
    case_name: str,
    implementation_dirs: ImplementationDirs,
    stdout_by_implementation: Dict[str, str],
    successful_implementations: Iterable[str],
) -> List[str]:
    successful = set(successful_implementations)
    if "python" not in successful:
        return []

    python_dir = implementation_dirs.get("python")
    if python_dir is None:
        return []

    problems: List[str] = []
    python_stdout = stdout_by_implementation.get("python", "")
    python_outputs = runtime_output_map(python_dir)

    for implementation_name in sorted(successful):
        if implementation_name == "python":
            continue
        directory = implementation_dirs[implementation_name]
        stdout = stdout_by_implementation.get(implementation_name, "")
        if stdout != python_stdout:
            problems.append(
                f"{case_name}: {implementation_name} stdout differs from python"
            )

        outputs = runtime_output_map(directory)
        missing = sorted(set(python_outputs) - set(outputs))
        extra = sorted(set(outputs) - set(python_outputs))
        if missing:
            problems.append(
                f"{case_name}: {implementation_name} missing runtime outputs "
                f"compared with python: {missing}"
            )
        if extra:
            problems.append(
                f"{case_name}: {implementation_name} extra runtime outputs "
                f"compared with python: {extra}"
            )

        for relative in sorted(set(python_outputs) & set(outputs)):
            python_bytes = comparable_runtime_bytes(python_outputs[relative])
            other_bytes = comparable_runtime_bytes(outputs[relative])
            if python_bytes != other_bytes:
                problems.append(
                    f"{case_name}: {implementation_name} output {relative!r} "
                    f"differs from python "
                    f"(python size={python_outputs[relative].stat().st_size}, "
                    f"{implementation_name} size={outputs[relative].stat().st_size})"
                )
    return problems


def print_timing_report(
    implementation_dirs: ImplementationDirs,
    timing_by_implementation: TimingByImplementation,
) -> None:
    parts = []
    for implementation_name in implementation_dirs:
        seconds = timing_by_implementation.get(implementation_name)
        if seconds is not None:
            parts.append(f"{implementation_name}={seconds:.3f}s")
    if parts:
        print("耗时: " + ", ".join(parts))


def add_pass_messages_when_needed(
    case_name: str,
    problems: List[str],
    passed_implementations: Iterable[str],
) -> List[str]:
    passed = list(passed_implementations)
    if not problems or not passed:
        return problems
    pass_messages = [
        f"{case_name}: {implementation_name} PASS"
        for implementation_name in passed
    ]
    return pass_messages + problems


def record_response(
    events: List[Event],
    label: str,
    command_template: str,
    response: str,
    store: Optional[str] = None,
) -> None:
    events.append(Event(label, normalize_response(command_template, response, store)))


def run_independent_pressure_on_server(
    server: ServerRun,
    client_count: int,
    rounds: int,
    timeout: float,
    verbose: bool,
) -> List[Event]:
    clients = [server.connect() for _ in range(client_count)]
    events_by_client: List[List[Event]] = [[] for _ in range(client_count)]
    errors: List[str] = []
    errors_lock = threading.Lock()
    start = threading.Barrier(client_count)

    def add_error(message: str) -> None:
        with errors_lock:
            errors.append(message)

    def worker(index: int) -> None:
        variables: Dict[str, str] = {}
        client = clients[index]

        def request(command_template: str, store: Optional[str] = None) -> str:
            command = substitute(command_template, variables)
            if verbose:
                print(f"[{server.name}] stress c{index} -> {command}")
            try:
                response = client.request(command)
            except Exception as exc:
                raise type(exc)(
                    f"while waiting for {command!r}: {exc}"
                ) from exc
            if verbose:
                print(f"[{server.name}] stress c{index} <- {response}")
            if store is not None:
                parts = response.split()
                if len(parts) != 2 or parts[0] != "0":
                    raise DiffFailure(
                        f"{server.name}: c{index}: cannot store {store} from {response!r}"
                    )
                variables[store] = parts[1]
            record_response(
                events_by_client[index],
                f"c{index}: {command_template}",
                command_template,
                response,
                store,
            )
            return response

        try:
            request(f"Login user{index}")
            start.wait(timeout=timeout)
            for round_index in range(rounds):
                canvas = f"canvas{round_index}"
                sprite = f"sprite{round_index}"
                placement = f"placement{round_index}"
                color = 1000 + index * 100 + round_index
                request(f"create_canvas 16 16 {color}", canvas)
                request(f"create_rectangle 2 3 {color} 1", sprite)
                request(f"place_sprite {{{canvas}}} {{{sprite}}} 1 1", placement)
                request(f"set_animation_params {{{placement}}} 1 0 0 1")
                request(f"placement_top {{{placement}}}")
                request(f"destroy_placement {{{placement}}}")
                request(f"destroy_sprite {{{sprite}}}")
                request(f"destroy_canvas {{{canvas}}}")
            client.send("Disconnect")
            record_response(
                events_by_client[index], f"c{index}: Disconnect", "Disconnect", "<sent>"
            )
        except Exception as exc:
            add_error(f"c{index}: {describe_runner_error(exc)}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(client_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=max(timeout * rounds, timeout * 2))

    for index, thread in enumerate(threads):
        if thread.is_alive():
            add_error(f"c{index}: worker thread timed out")

    for client in clients:
        client.close()

    if errors:
        raise DiffFailure("; ".join(errors))

    events: List[Event] = []
    for client_events in events_by_client:
        events.extend(client_events)
    return events


def run_barrier_pressure_on_server(
    server: ServerRun,
    client_count: int,
    timeout: float,
    verbose: bool,
) -> List[Event]:
    clients = [server.connect() for _ in range(client_count)]
    variables: Dict[str, str] = {}
    events: List[Event] = []

    try:
        for index, client in enumerate(clients):
            command = f"Login user{index}"
            try:
                response = client.request(command)
            except Exception as exc:
                raise type(exc)(
                    f"while waiting for {command!r}: {exc}"
                ) from exc
            record_response(events, f"c{index}: Login", f"Login user{index}", response)

        command = "create_canvas 24 24 0"
        try:
            response = clients[0].request(command)
        except Exception as exc:
            raise type(exc)(
                f"while waiting for {command!r}: {exc}"
            ) from exc
        parts = response.split()
        if len(parts) != 2 or parts[0] != "0":
            raise DiffFailure(f"cannot create shared canvas: {response!r}")
        variables["canvas"] = parts[1]
        record_response(events, "c0: create_canvas", "create_canvas 24 24 0", response)

        for index in range(1, client_count):
            command = f"share_canvas {{canvas}} user{index}"
            concrete_command = substitute(command, variables)
            try:
                response = clients[0].request(concrete_command)
            except Exception as exc:
                raise type(exc)(
                    f"while waiting for {concrete_command!r}: {exc}"
                ) from exc
            record_response(events, f"c0: share user{index}", command, response)

        send_barrier = threading.Barrier(client_count)
        responses: List[Optional[str]] = [None] * client_count
        errors: List[str] = []
        errors_lock = threading.Lock()

        def add_error(message: str) -> None:
            with errors_lock:
                errors.append(message)

        def barrier_worker(index: int) -> None:
            command = substitute("barrier {canvas}", variables)
            try:
                send_barrier.wait(timeout=timeout)
                if verbose:
                    print(f"[{server.name}] barrier c{index} -> {command}")
                clients[index].send(command)
                try:
                    responses[index] = clients[index].read_line()
                except Exception as exc:
                    raise type(exc)(
                        f"while waiting for {command!r}: {exc}"
                    ) from exc
                if verbose:
                    print(f"[{server.name}] barrier c{index} <- {responses[index]}")
            except Exception as exc:
                add_error(f"c{index}: {describe_runner_error(exc)}")

        threads = [
            threading.Thread(target=barrier_worker, args=(index,))
            for index in range(client_count)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=timeout + 1.0)

        for index, thread in enumerate(threads):
            if thread.is_alive():
                add_error(f"c{index}: barrier 超时；超时视为可能死锁/阻塞")

        if errors:
            raise DiffFailure("; ".join(errors))

        for index, response in enumerate(responses):
            assert response is not None
            record_response(events, f"c{index}: barrier", "barrier {canvas}", response)

        for client in clients:
            client.send("Disconnect")
        for index in range(client_count):
            record_response(events, f"c{index}: Disconnect", "Disconnect", "<sent>")
        return events
    finally:
        for client in clients:
            client.close()


def run_barrier_disconnect_pressure_on_server(
    server: ServerRun,
    client_count: int,
    timeout: float,
    verbose: bool,
) -> List[Event]:
    pair_count = max(1, client_count // 2)
    events_by_pair: List[List[Event]] = [[] for _ in range(pair_count)]
    errors: List[str] = []
    errors_lock = threading.Lock()
    connection_lock = threading.Lock()
    start = threading.Barrier(pair_count)

    def add_error(message: str) -> None:
        with errors_lock:
            errors.append(message)

    def worker(pair_index: int) -> None:
        creator = None
        waiter = None
        variables: Dict[str, str] = {}
        creator_index = pair_index * 2
        waiter_index = pair_index * 2 + 1

        def request(client: RawClient, label: str, command_template: str,
                    store: Optional[str] = None,
                    expect: Optional[str] = None) -> str:
            command = substitute(command_template, variables)
            if verbose:
                print(f"[{server.name}] barrier-disconnect {label} -> {command}")
            try:
                response = client.request(command)
            except Exception as exc:
                raise type(exc)(
                    f"while waiting for {command!r}: {exc}"
                ) from exc
            if verbose:
                print(f"[{server.name}] barrier-disconnect {label} <- {response}")
            if expect is not None and response != expect:
                raise DiffFailure(
                    f"{server.name}: {label}: expected {expect!r} from "
                    f"{command!r}, got {response!r}"
                )
            if store is not None:
                parts = response.split()
                if len(parts) != 2 or parts[0] != "0":
                    raise DiffFailure(
                        f"{server.name}: {label}: cannot store {store} from "
                        f"{response!r}"
                    )
                variables[store] = parts[1]
            record_response(
                events_by_pair[pair_index],
                f"pair{pair_index} {label}: {command_template}",
                command_template,
                response,
                store,
            )
            return response

        try:
            # 连接使用 SIGUSR1 普通信号；这里串行化连接阶段，避免信号合并
            # 掩盖本场景真正要压的 barrier + Disconnect 逻辑。
            with connection_lock:
                creator = server.connect()
                waiter = server.connect()
            request(
                creator,
                "creator",
                f"Login user{creator_index}",
                expect=str(generated_user_balance(creator_index)),
            )
            request(
                waiter,
                "waiter",
                f"Login user{waiter_index}",
                expect=str(generated_user_balance(waiter_index)),
            )
            request(creator, "creator", "create_canvas 8 8 0", store="canvas")
            request(
                creator,
                "creator",
                f"share_canvas {{canvas}} user{waiter_index}",
                expect="0",
            )
            start.wait(timeout=timeout)
            waiter.send(substitute("barrier {canvas}", variables))
            time.sleep(0.02)
            waiter.send("Disconnect")
            waiter.close()
            record_response(
                events_by_pair[pair_index],
                f"pair{pair_index} waiter: Disconnect while barrier pending",
                "Disconnect",
                "<sent>",
            )
            request(
                creator,
                "creator",
                "barrier {canvas}",
                expect="0",
            )
            creator.send("Disconnect")
            record_response(
                events_by_pair[pair_index],
                f"pair{pair_index} creator: Disconnect",
                "Disconnect",
                "<sent>",
            )
        except Exception as exc:
            add_error(f"pair{pair_index}: {describe_runner_error(exc)}")
        finally:
            if waiter is not None:
                waiter.close()
            if creator is not None:
                creator.close()

    threads = [
        threading.Thread(target=worker, args=(pair_index,))
        for pair_index in range(pair_count)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=max(timeout * 2, 2.0))

    for pair_index, thread in enumerate(threads):
        if thread.is_alive():
            add_error(f"pair{pair_index}: worker thread timed out")

    if errors:
        raise DiffFailure("; ".join(errors))

    events: List[Event] = []
    for pair_events in events_by_pair:
        events.extend(pair_events)
    return events


def run_share_disconnect_pressure_on_server(
    server: ServerRun,
    client_count: int,
    timeout: float,
    verbose: bool,
) -> List[Event]:
    owner_count = max(1, client_count - 1)
    target = server.connect()
    owners = [server.connect() for _ in range(owner_count)]
    variables_by_owner: List[Dict[str, str]] = [{} for _ in range(owner_count)]
    events_by_owner: List[List[Event]] = [[] for _ in range(owner_count)]
    events: List[Event] = []
    errors: List[str] = []
    errors_lock = threading.Lock()
    start = threading.Barrier(owner_count + 1)

    def add_error(message: str) -> None:
        with errors_lock:
            errors.append(message)

    def request(client: RawClient, event_list: List[Event], label: str,
                command_template: str, variables: Dict[str, str],
                store: Optional[str] = None,
                expect: Optional[str] = None) -> str:
        command = substitute(command_template, variables)
        if verbose:
            print(f"[{server.name}] share-disconnect {label} -> {command}")
        try:
            response = client.request(command)
        except Exception as exc:
            raise type(exc)(
                f"while waiting for {command!r}: {exc}"
            ) from exc
        if verbose:
            print(f"[{server.name}] share-disconnect {label} <- {response}")
        if expect is not None and response != expect:
            raise DiffFailure(
                f"{server.name}: {label}: expected {expect!r} from "
                f"{command!r}, got {response!r}"
            )
        if store is not None:
            parts = response.split()
            if len(parts) != 2 or parts[0] != "0":
                raise DiffFailure(
                    f"{server.name}: {label}: cannot store {store} from "
                    f"{response!r}"
                )
            variables[store] = parts[1]
        record_response(event_list, label, command_template, response, store)
        return response

    try:
        target_login = target.request("Login user0")
        if target_login != str(generated_user_balance(0)):
            raise DiffFailure(
                f"{server.name}: target login expected "
                f"{generated_user_balance(0)!r}, got {target_login!r}"
            )
        record_response(events, "target: Login user0", "Login user0", target_login)

        for index, owner in enumerate(owners):
            username_index = index + 1
            request(
                owner,
                events_by_owner[index],
                f"owner{index}: Login user{username_index}",
                f"Login user{username_index}",
                variables_by_owner[index],
                expect=str(generated_user_balance(username_index)),
            )
            request(
                owner,
                events_by_owner[index],
                f"owner{index}: create initial canvas",
                "create_canvas 6 6 0",
                variables_by_owner[index],
                store="initial_canvas",
            )
            request(
                owner,
                events_by_owner[index],
                f"owner{index}: initial share",
                "share_canvas {initial_canvas} user0",
                variables_by_owner[index],
                expect="0",
            )
            request(
                owner,
                events_by_owner[index],
                f"owner{index}: create race canvas",
                "create_canvas 7 7 1",
                variables_by_owner[index],
                store="race_canvas",
            )

        def owner_worker(index: int) -> None:
            owner = owners[index]
            variables = variables_by_owner[index]
            event_list = events_by_owner[index]
            try:
                start.wait(timeout=timeout)
                for attempt in range(4):
                    response = request(
                        owner,
                        event_list,
                        f"owner{index}: race share {attempt}",
                        "share_canvas {race_canvas} user0",
                        variables,
                    )
                    if response not in {"0", "-2"}:
                        raise DiffFailure(
                            f"{server.name}: owner{index}: unexpected race share "
                            f"response {response!r}"
                        )
                    event_list[-1].response = "<0-or--2>"
                    time.sleep(0.005)
                owner.send("Disconnect")
                record_response(
                    event_list,
                    f"owner{index}: Disconnect",
                    "Disconnect",
                    "<sent>",
                )
            except Exception as exc:
                add_error(f"owner{index}: {describe_runner_error(exc)}")

        def target_worker() -> None:
            try:
                start.wait(timeout=timeout)
                time.sleep(0.005)
                target.send("Disconnect")
                record_response(
                    events,
                    "target: Disconnect during concurrent shares",
                    "Disconnect",
                    "<sent>",
                )
            except Exception as exc:
                add_error(f"target: {describe_runner_error(exc)}")
            finally:
                target.close()

        threads = [
            threading.Thread(target=owner_worker, args=(index,))
            for index in range(owner_count)
        ]
        threads.append(threading.Thread(target=target_worker))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=max(timeout * 2, 2.0))

        for index, thread in enumerate(threads):
            if thread.is_alive():
                add_error(f"share-disconnect thread{index}: timed out")
    finally:
        target.close()
        for owner in owners:
            owner.close()

    if errors:
        raise DiffFailure("; ".join(errors))

    for owner_events in events_by_owner:
        events.extend(owner_events)
    return events


def run_collaborative_animation_pressure_on_server(
    server: ServerRun,
    client_count: int,
    rounds: int,
    timeout: float,
    verbose: bool,
    frame_count: int = DEFAULT_COLLAB_ANIMATION_FRAMES,
    frame_rate: int = DEFAULT_COLLAB_ANIMATION_FRAME_RATE,
    min_sprites_per_client: int = DEFAULT_COLLAB_MIN_SPRITES_PER_CLIENT,
    min_placements_per_client: int = DEFAULT_COLLAB_MIN_PLACEMENTS_PER_CLIENT,
) -> List[Event]:
    if client_count < 2:
        raise ValueError("协作动画测试至少需要 2 个客户端")
    if rounds < 1:
        raise ValueError("协作动画轮数必须 >= 1")
    if frame_count < 2:
        raise ValueError("协作动画帧数必须 >= 2")
    if frame_rate < 1:
        raise ValueError("协作动画帧率必须 >= 1")
    if min_sprites_per_client < 1:
        raise ValueError("协作动画每客户端 sprite 下限必须 >= 1")
    if min_placements_per_client < 1:
        raise ValueError("协作动画每客户端 placement 下限必须 >= 1")

    clients = [server.connect() for _ in range(client_count)]
    variables: Dict[str, str] = {}
    events: List[Event] = []
    width = 64
    height = 64

    def request(index: int, label: str, command_template: str,
                store: Optional[str] = None,
                expect: Optional[str] = None) -> str:
        command = substitute(command_template, variables)
        if verbose:
            print(f"[{server.name}] collaborative c{index} -> {command}")
        try:
            response = clients[index].request(command)
        except Exception as exc:
            raise type(exc)(
                f"while waiting for {command!r}: {exc}"
            ) from exc
        if verbose:
            print(f"[{server.name}] collaborative c{index} <- {response}")
        if expect is not None and response != expect:
            raise DiffFailure(
                f"{server.name}: c{index}: expected {expect!r} from "
                f"{command!r}, got {response!r}"
            )
        if store is not None:
            parts = response.split()
            if len(parts) != 2 or parts[0] != "0":
                raise DiffFailure(
                    f"{server.name}: c{index}: cannot store {store} from "
                    f"{response!r}"
                )
            variables[store] = parts[1]
        record_response(
            events,
            f"c{index}: {label}",
            command_template,
            response,
            store,
        )
        return response

    def barrier_all(label: str) -> None:
        responses: List[Optional[str]] = [None] * client_count
        errors: List[str] = []
        errors_lock = threading.Lock()
        start = threading.Barrier(client_count)

        def add_error(message: str) -> None:
            with errors_lock:
                errors.append(message)

        def barrier_worker(index: int) -> None:
            command_template = "barrier {shared_canvas}"
            command = substitute(command_template, variables)
            try:
                start.wait(timeout=timeout)
                if verbose:
                    print(
                        f"[{server.name}] collaborative c{index} -> {command}"
                    )
                clients[index].send(command)
                try:
                    responses[index] = clients[index].read_line()
                except Exception as exc:
                    raise type(exc)(
                        f"while waiting for {command!r}: {exc}"
                    ) from exc
                if verbose:
                    print(
                        f"[{server.name}] collaborative c{index} <- "
                        f"{responses[index]}"
                    )
            except Exception as exc:
                add_error(f"c{index}: {describe_runner_error(exc)}")

        threads = [
            threading.Thread(target=barrier_worker, args=(index,))
            for index in range(client_count)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=max(timeout + 1.0, 2.0))

        for index, thread in enumerate(threads):
            if thread.is_alive():
                add_error(f"c{index}: barrier worker timed out")
        if errors:
            raise DiffFailure("; ".join(errors))

        for index, response in enumerate(responses):
            assert response is not None
            record_response(
                events,
                f"c{index}: {label}",
                "barrier {shared_canvas}",
                response,
            )

    try:
        for index in range(client_count):
            request(
                index,
                f"Login user{index}",
                f"Login user{index}",
                expect=str(generated_user_balance(index)),
            )

        request(0, "create shared canvas", "create_canvas 64 64 0",
                store="shared_canvas")
        for index in range(1, client_count):
            request(
                0,
                f"share canvas to user{index}",
                f"share_canvas {{shared_canvas}} user{index}",
                expect="0",
            )

        for index in range(client_count):
            for sprite_slot in range(min_sprites_per_client):
                color = (
                    0x2255AA + index * 0x10203 + sprite_slot * 0x30507
                ) & 0xFFFFFF
                filled = 1
                if (index + sprite_slot) % 2 == 0:
                    sprite_command = (
                        f"create_rectangle {2 + (index + sprite_slot) % 5} "
                        f"{2 + (index * 2 + sprite_slot) % 5} {color} {filled}"
                    )
                else:
                    sprite_command = (
                        f"create_circle {2 + (index + sprite_slot) % 4} "
                        f"{color} {filled}"
                    )
                request(
                    index,
                    f"create sprite {index}.{sprite_slot}",
                    sprite_command,
                    store=f"sprite_{index}_{sprite_slot}",
                )

            for placement_slot in range(min_placements_per_client):
                sprite_slot = placement_slot % min_sprites_per_client
                sprite_name = f"sprite_{index}_{sprite_slot}"
                placement_name = f"placement_{index}_{placement_slot}"
                x = (index * 7 + placement_slot * 3) % (width - 8)
                y = (index * 11 + placement_slot * 5) % (height - 8)
                request(
                    index,
                    f"place sprite {index}.{placement_slot}",
                    f"place_sprite {{shared_canvas}} {{{sprite_name}}} {x} {y}",
                    store=placement_name,
                )

                vx = (index + placement_slot) % 5 - 2
                vy = (index * 2 + placement_slot) % 5 - 2
                if vx == 0 and vy == 0:
                    vx = 1
                ax = 1 if (index + placement_slot) % 7 == 0 else 0
                ay = -1 if (index + placement_slot) % 11 == 0 else 0
                request(
                    index,
                    f"set animation {index}.{placement_slot}",
                    f"set_animation_params {{{placement_name}}} "
                    f"{vx} {vy} {ax} {ay}",
                    expect="0",
                )

        barrier_all("barrier after setup")

        movement_ops = [
            "placement_up",
            "placement_down",
            "placement_top",
            "placement_bottom",
        ]
        barrier_period = max(1, rounds // 3)
        for round_index in range(rounds):
            for index in range(client_count):
                placement_slot = (round_index + index) % min_placements_per_client
                placement_name = f"placement_{index}_{placement_slot}"
                if (round_index + index) % 5 == 4:
                    vx = (round_index + index) % 7 - 3
                    vy = (round_index * 2 + index) % 7 - 3
                    if vx == 0 and vy == 0:
                        vy = 1
                    request(
                        index,
                        f"round {round_index} set animation",
                        f"set_animation_params {{{placement_name}}} "
                        f"{vx} {vy} 0 0",
                        expect="0",
                    )
                else:
                    operation = movement_ops[(round_index + index) % 4]
                    request(
                        index,
                        f"round {round_index} {operation}",
                        f"{operation} {{{placement_name}}}",
                        expect="0",
                    )
            if (round_index + 1) % barrier_period == 0 and (
                round_index + 1
            ) < rounds:
                barrier_all(f"barrier round {round_index}")

        barrier_all("barrier before generate")
        request(
            0,
            "generate collaborative animation",
            f"generate {{shared_canvas}} collaborative_animation 0 "
            f"{frame_count - 1} {frame_rate}",
            expect="0 0 0",
        )

        for index, client in enumerate(clients):
            client.send("Disconnect")
            record_response(events, f"c{index}: Disconnect", "Disconnect", "<sent>")
        return events
    finally:
        for client in clients:
            client.close()


def run_huge_animation_soak_on_server(
    server: ServerRun,
    client_count: int,
    rounds: int,
    timeout: float,
    verbose: bool,
    min_runtime_seconds: float = DEFAULT_HUGE_ANIMATION_MIN_RUNTIME_SECONDS,
    canvas_width: int = DEFAULT_HUGE_ANIMATION_CANVAS_WIDTH,
    canvas_height: int = DEFAULT_HUGE_ANIMATION_CANVAS_HEIGHT,
    frame_count: int = DEFAULT_HUGE_ANIMATION_FRAMES,
    frame_rate: int = DEFAULT_HUGE_ANIMATION_FRAME_RATE,
    generate_count: int = DEFAULT_HUGE_ANIMATION_GENERATE_COUNT,
    min_sprites_per_client: int = DEFAULT_HUGE_MIN_SPRITES_PER_CLIENT,
    min_placements_per_client: int = DEFAULT_HUGE_MIN_PLACEMENTS_PER_CLIENT,
) -> List[Event]:
    if client_count < 2:
        raise ValueError("超大长跑测试至少需要 2 个客户端")
    if rounds < 1:
        raise ValueError("超大长跑测试操作轮数必须 >= 1")
    if min_runtime_seconds < 0:
        raise ValueError("超大长跑测试最短运行秒数必须 >= 0")
    if canvas_width < 32 or canvas_height < 32:
        raise ValueError("超大长跑测试画布宽高都必须 >= 32")
    if frame_count < 2:
        raise ValueError("超大长跑测试帧数必须 >= 2")
    if frame_rate < 1:
        raise ValueError("超大长跑测试帧率必须 >= 1")
    if generate_count < 1 or generate_count > 5:
        raise ValueError("超大长跑测试 generate 次数必须在 1 到 5 之间")
    if min_sprites_per_client < 1:
        raise ValueError("超大长跑测试每客户端 sprite 下限必须 >= 1")
    if min_placements_per_client < 1:
        raise ValueError("超大长跑测试每客户端 placement 下限必须 >= 1")

    clients = [server.connect() for _ in range(client_count)]
    variables: Dict[str, str] = {}
    events: List[Event] = []
    sprites_by_client: List[List[str]] = [[] for _ in range(client_count)]
    placements_by_client: List[List[str]] = [[] for _ in range(client_count)]

    def request(index: int, label: str, command_template: str,
                store: Optional[str] = None,
                expect: Optional[str] = None) -> str:
        command = substitute(command_template, variables)
        if verbose:
            print(f"[{server.name}] huge c{index} -> {command}")
        try:
            response = clients[index].request(command)
        except Exception as exc:
            raise type(exc)(
                f"while waiting for {command!r}: {exc}"
            ) from exc
        if verbose:
            print(f"[{server.name}] huge c{index} <- {response}")
        if expect is not None and response != expect:
            raise DiffFailure(
                f"{server.name}: c{index}: expected {expect!r} from "
                f"{command!r}, got {response!r}"
            )
        if store is not None:
            parts = response.split()
            if len(parts) != 2 or parts[0] != "0":
                raise DiffFailure(
                    f"{server.name}: c{index}: cannot store {store} from "
                    f"{response!r}"
                )
            variables[store] = parts[1]
        record_response(
            events,
            f"c{index}: {label}",
            command_template,
            response,
            store,
        )
        return response

    def barrier_all(label: str) -> None:
        responses: List[Optional[str]] = [None] * client_count
        errors: List[str] = []
        errors_lock = threading.Lock()
        start = threading.Barrier(client_count)

        def add_error(message: str) -> None:
            with errors_lock:
                errors.append(message)

        def barrier_worker(index: int) -> None:
            command_template = "barrier {shared_canvas}"
            command = substitute(command_template, variables)
            try:
                start.wait(timeout=timeout)
                if verbose:
                    print(f"[{server.name}] huge c{index} -> {command}")
                clients[index].send(command)
                try:
                    responses[index] = clients[index].read_line()
                except Exception as exc:
                    raise type(exc)(
                        f"while waiting for {command!r}: {exc}"
                    ) from exc
                if verbose:
                    print(
                        f"[{server.name}] huge c{index} <- "
                        f"{responses[index]}"
                    )
            except Exception as exc:
                add_error(f"c{index}: {describe_runner_error(exc)}")

        threads = [
            threading.Thread(target=barrier_worker, args=(index,))
            for index in range(client_count)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=max(timeout + 1.0, 2.0))

        for index, thread in enumerate(threads):
            if thread.is_alive():
                add_error(f"c{index}: barrier worker timed out")
        if errors:
            raise DiffFailure("; ".join(errors))

        for index, response in enumerate(responses):
            assert response is not None
            record_response(
                events,
                f"c{index}: {label}",
                "barrier {shared_canvas}",
                response,
            )

    def sprite_command(index: int, sprite_slot: int) -> str:
        color = (
            0x114477 + index * 0x020305 + sprite_slot * 0x07111D
        ) & 0xFFFFFF
        if sprite_slot % 4 == 0:
            return f"create_sprite {bmp_filename(index + sprite_slot)}"
        if sprite_slot % 4 == 1:
            width = 6 + (index + sprite_slot * 2) % 18
            height = 5 + (index * 3 + sprite_slot) % 16
            return f"create_rectangle {width} {height} {color} 1"
        if sprite_slot % 4 == 2:
            radius = 3 + (index + sprite_slot) % 10
            return f"create_circle {radius} {color} 1"
        width = 8 + (index * 5 + sprite_slot) % 20
        height = 3 + (index + sprite_slot * 7) % 12
        return f"create_rectangle {width} {height} {color} 0"

    def place_existing_sprite(index: int, sprite_name: str,
                              placement_name: str, salt: int) -> None:
        x_limit = max(1, canvas_width - 24)
        y_limit = max(1, canvas_height - 24)
        x = (index * 37 + salt * 19) % x_limit
        y = (index * 29 + salt * 23) % y_limit
        request(
            index,
            f"place {placement_name}",
            f"place_sprite {{shared_canvas}} {{{sprite_name}}} {x} {y}",
            store=placement_name,
        )
        placements_by_client[index].append(placement_name)

        vx = (index * 3 + salt) % 11 - 5
        vy = (index + salt * 2) % 11 - 5
        if vx == 0 and vy == 0:
            vx = 2
        ax = ((index + salt) % 5) - 2
        ay = ((index * 2 + salt) % 5) - 2
        request(
            index,
            f"set animation {placement_name}",
            f"set_animation_params {{{placement_name}}} {vx} {vy} {ax} {ay}",
            expect="0",
        )

    try:
        for index in range(client_count):
            request(
                index,
                f"Login user{index}",
                f"Login user{index}",
                expect=str(generated_user_balance(index)),
            )

        request(
            0,
            "create huge shared canvas",
            f"create_canvas {canvas_height} {canvas_width} 0",
            store="shared_canvas",
        )
        for index in range(1, client_count):
            request(
                0,
                f"share huge canvas to user{index}",
                f"share_canvas {{shared_canvas}} user{index}",
                expect="0",
            )

        for index in range(client_count):
            for sprite_slot in range(min_sprites_per_client):
                name = f"huge_sprite_{index}_{sprite_slot}"
                request(
                    index,
                    f"create {name}",
                    sprite_command(index, sprite_slot),
                    store=name,
                )
                sprites_by_client[index].append(name)

            for placement_slot in range(min_placements_per_client):
                sprite_name = sprites_by_client[index][
                    placement_slot % len(sprites_by_client[index])
                ]
                placement_name = f"huge_placement_{index}_{placement_slot}"
                place_existing_sprite(index, sprite_name, placement_name,
                                      placement_slot)

        barrier_all("setup barrier")

        movement_ops = [
            "placement_up",
            "placement_down",
            "placement_top",
            "placement_bottom",
        ]
        barrier_period = max(1, rounds // 8)
        dynamic_period = max(1, rounds // 12)
        paced_start = time.monotonic()
        for round_index in range(rounds):
            for index in range(client_count):
                placements = placements_by_client[index]
                base = (round_index * 5 + index * 3) % len(placements)
                for op_offset in range(3):
                    placement_name = placements[
                        (base + op_offset * 7) % len(placements)
                    ]
                    selector = (round_index + index + op_offset) % 6
                    if selector < 4:
                        operation = movement_ops[selector]
                        request(
                            index,
                            f"round {round_index} {operation}",
                            f"{operation} {{{placement_name}}}",
                            expect="0",
                        )
                    else:
                        vx = (round_index + index + op_offset) % 13 - 6
                        vy = (round_index * 2 + index + op_offset) % 13 - 6
                        if vx == 0 and vy == 0:
                            vy = -3
                        ax = ((round_index + index) % 7) - 3
                        ay = ((round_index * 3 + index) % 7) - 3
                        request(
                            index,
                            f"round {round_index} animation",
                            f"set_animation_params {{{placement_name}}} "
                            f"{vx} {vy} {ax} {ay}",
                            expect="0",
                        )

            if (round_index + 1) % dynamic_period == 0:
                creators = max(1, client_count // 6)
                for offset in range(creators):
                    index = (round_index + offset * 5) % client_count
                    sprite_slot = len(sprites_by_client[index])
                    sprite_name = f"huge_sprite_{index}_{sprite_slot}"
                    request(
                        index,
                        f"dynamic create {sprite_name}",
                        sprite_command(index, sprite_slot),
                        store=sprite_name,
                    )
                    sprites_by_client[index].append(sprite_name)
                    placement_slot = len(placements_by_client[index])
                    placement_name = f"huge_placement_{index}_{placement_slot}"
                    place_existing_sprite(
                        index,
                        sprite_name,
                        placement_name,
                        round_index + placement_slot,
                    )

            if (round_index + 1) % barrier_period == 0:
                barrier_all(f"round {round_index} barrier")

            if min_runtime_seconds > 0:
                target = paced_start + (
                    min_runtime_seconds * (round_index + 1) / rounds
                )
                remaining = target - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)

        barrier_all("pre-generate barrier")
        for generate_index in range(generate_count):
            requester = generate_index % client_count
            request(
                requester,
                f"generate huge animation {generate_index}",
                f"generate {{shared_canvas}} huge_animation_{generate_index} "
                f"0 {frame_count - 1} {frame_rate}",
                expect="0 0 0",
            )

        for index, client in enumerate(clients):
            client.send("Disconnect")
            record_response(events, f"c{index}: Disconnect", "Disconnect",
                            "<sent>")
        return events
    finally:
        for client in clients:
            client.close()


def run_pressure_pair(
    name: str,
    pressure_func,
    implementation_dirs: ImplementationDirs,
    threads: int,
    client_count: int,
    timeout: float,
    verbose: bool,
    rounds: Optional[int] = None,
    memory_check: bool = False,
) -> List[str]:
    run_threads = max(1, min(threads, client_count - 1))
    servers: Dict[str, ServerRun] = {}
    events_by_implementation: Dict[str, List[Event]] = {}
    stdout_by_implementation: Dict[str, str] = {}
    stderr_by_implementation: Dict[str, str] = {}
    timing_by_implementation: TimingByImplementation = {}
    passed_implementations: Set[str] = set()
    failed_implementations: Set[str] = set()
    problems: List[str] = []
    clear_runtime_outputs(implementation_dirs)
    try:
        errors: List[str] = []

        for implementation_name, directory in implementation_dirs.items():
            started_at = time.monotonic()
            try:
                servers[implementation_name] = ServerRun(
                    implementation_name,
                    directory,
                    run_threads,
                    timeout,
                    memory_check and implementation_name == "student",
                )
            except Exception as exc:
                timing_by_implementation[implementation_name] = (
                    time.monotonic() - started_at
                )
                failed_implementations.add(implementation_name)
                errors.append(
                    f"{name}: {implementation_name} startup error: "
                    f"{describe_runner_error(exc)}"
                )

        for implementation_name, server in servers.items():
            started_at = time.monotonic()
            try:
                if rounds is None:
                    events_by_implementation[implementation_name] = pressure_func(
                        server, client_count, timeout, verbose
                    )
                else:
                    events_by_implementation[implementation_name] = pressure_func(
                        server, client_count, rounds, timeout, verbose
                    )
                passed_implementations.add(implementation_name)
            except Exception as exc:
                failed_implementations.add(implementation_name)
                errors.append(
                    f"{name}: {implementation_name} runner error: "
                    f"{describe_runner_error(exc)}"
                )
            finally:
                timing_by_implementation[implementation_name] = (
                    time.monotonic() - started_at
                )

        if errors:
            problems.extend(errors)
        else:
            problems.extend(compare_event_sets(name, events_by_implementation))
    except Exception as exc:
        problems.append(f"{name}: runner error: {describe_runner_error(exc)}")
    finally:
        for implementation_name, server in servers.items():
            stdout, stderr = server.stop()
            stdout_by_implementation[implementation_name] = stdout
            stderr_by_implementation[implementation_name] = stderr
            if memory_check and implementation_name == "student":
                problems.extend(memory_report_problems(name, stderr))
        problems.extend(
            compare_python_runtime_outputs(
                name,
                implementation_dirs,
                stdout_by_implementation,
                events_by_implementation.keys(),
            )
        )
        print_timing_report(implementation_dirs, timing_by_implementation)
        save_case_artifacts(
            name,
            implementation_dirs,
            {
                "kind": "pressure",
                "pressure_function": getattr(pressure_func, "__name__", "unknown"),
                "threads": threads,
                "effective_threads": run_threads,
                "client_count": client_count,
                "rounds": rounds,
                "timeout": timeout,
                "memory_check": memory_check,
            },
            events_by_implementation,
            problems,
            stdout_by_implementation,
            stderr_by_implementation,
            timing_by_implementation,
        )
    return add_pass_messages_when_needed(
        name, problems, passed_implementations - failed_implementations
    )


def run_one_scenario(
    scenario: Scenario,
    implementation_dirs: ImplementationDirs,
    threads: int,
    timeout: float,
    verbose: bool,
    memory_check: bool = False,
) -> List[str]:
    servers: Dict[str, ServerRun] = {}
    events_by_implementation: Dict[str, List[Event]] = {}
    stdout_by_implementation: Dict[str, str] = {}
    stderr_by_implementation: Dict[str, str] = {}
    timing_by_implementation: TimingByImplementation = {}
    passed_implementations: Set[str] = set()
    failed_implementations: Set[str] = set()
    problems: List[str] = []
    clear_runtime_outputs(implementation_dirs)
    try:
        for implementation_name, directory in implementation_dirs.items():
            started_at = time.monotonic()
            try:
                servers[implementation_name] = ServerRun(
                    implementation_name,
                    directory,
                    threads,
                    timeout,
                    memory_check and implementation_name == "student",
                )
            except Exception as exc:
                timing_by_implementation[implementation_name] = (
                    time.monotonic() - started_at
                )
                failed_implementations.add(implementation_name)
                problems.append(
                    f"{scenario.name}: {implementation_name} startup error: "
                    f"{describe_runner_error(exc)}"
                )

        for implementation_name, server in servers.items():
            started_at = time.monotonic()
            try:
                events_by_implementation[implementation_name] = (
                    run_scenario_on_server(server, scenario, verbose)
                )
                passed_implementations.add(implementation_name)
            except Exception as exc:
                failed_implementations.add(implementation_name)
                problems.append(
                    f"{scenario.name}: {implementation_name} runner error: "
                    f"{describe_runner_error(exc)}"
                )
            finally:
                timing_by_implementation[implementation_name] = (
                    time.monotonic() - started_at
                )

        if not problems:
            problems.extend(compare_event_sets(scenario.name,
                                               events_by_implementation))
    finally:
        for implementation_name, server in servers.items():
            stdout, stderr = server.stop()
            stdout_by_implementation[implementation_name] = stdout
            stderr_by_implementation[implementation_name] = stderr
            if memory_check and implementation_name == "student":
                problems.extend(memory_report_problems(scenario.name, stderr))
        problems.extend(
            compare_python_runtime_outputs(
                scenario.name,
                implementation_dirs,
                stdout_by_implementation,
                events_by_implementation.keys(),
            )
        )
        print_timing_report(implementation_dirs, timing_by_implementation)
        if verbose:
            for implementation_name, stderr in stderr_by_implementation.items():
                if stderr.strip():
                    print(f"[{implementation_name} stderr]\n{stderr}",
                          file=sys.stderr)
            for implementation_name, stdout in stdout_by_implementation.items():
                if stdout.strip():
                    print(f"[{implementation_name} stdout]\n{stdout}",
                          file=sys.stderr)
        save_case_artifacts(
            scenario.name,
            implementation_dirs,
            {
                "kind": "scenario",
                "scenario": dataclasses.asdict(scenario),
                "threads": threads,
                "timeout": timeout,
                "memory_check": memory_check,
            },
            events_by_implementation,
            problems,
            stdout_by_implementation,
            stderr_by_implementation,
            timing_by_implementation,
        )
    return add_pass_messages_when_needed(
        scenario.name, problems, passed_implementations - failed_implementations
    )


def print_case_header(name: str, description: str = "") -> None:
    print(f"== {name} ==")
    if description:
        print(f"说明: {description}")


def print_group_header(title: str, description: str) -> None:
    print(f"\n## {title} ##")
    print(f"说明: {description}")


def report_case_result(problems: List[str], all_problems: List[str]) -> None:
    if problems:
        print("FAIL")
        for problem in problems:
            print(f"  - {problem}")
        all_problems.extend(problems)
    else:
        print("PASS")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="对拍当前代码、Python 参考实现、test/Hai code 和 test/Dan code。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="运行固定、随机、压力、随机压力全部测试；限制：开关参数。",
    )
    parser.add_argument(
        "--fixed",
        action="store_true",
        help="运行固定手写场景；限制：开关参数，可与其他组组合。",
    )
    parser.add_argument("--threads", type=int, default=DEFAULT_THREADS,
                        help="服务器工作线程数；限制：必须 >= 1。")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help="等待连接或响应的秒数；限制：必须 > 0。")
    parser.add_argument("--build-timeout", type=float,
                        default=DEFAULT_BUILD_TIMEOUT,
                        help="编译命令的等待秒数；限制：必须 > 0。")
    parser.add_argument("--implementations", default=DEFAULT_IMPLEMENTATIONS,
                        help=("参与测试的实现；限制：逗号或空格分隔，可选 "
                              "student/python/hai/dan/all。例如 student 或 "
                              "student,python。"))
    parser.add_argument(
        "--random",
        nargs="?",
        const=DEFAULT_RANDOM_CASES,
        type=int,
        default=0,
        metavar="N",
        help="运行 N 个小规模固定 seed 随机多客户端测试；限制：N 必须 >= 0。",
    )
    parser.add_argument("--random-clients", type=int,
                        default=DEFAULT_RANDOM_CLIENTS,
                        help="小随机测试客户端数；限制：必须 >= 2。")
    parser.add_argument("--commands-per-client", type=int,
                        default=DEFAULT_COMMANDS_PER_CLIENT,
                        help="小随机每客户端约生成的命令数；限制：必须 >= 1。")
    parser.add_argument("--random-create-weight", type=int,
                        default=DEFAULT_RANDOM_CREATE_WEIGHT,
                        help=("create_canvas/create_sprite/create_rectangle/"
                              "create_circle 合并动作权重；限制：必须 >= 0。"))
    parser.add_argument("--random-place-sprite-weight", type=int,
                        default=DEFAULT_RANDOM_PLACE_SPRITE_WEIGHT,
                        help="place_sprite 动作权重；限制：必须 >= 0。")
    parser.add_argument("--random-placement-weight", type=int,
                        default=DEFAULT_RANDOM_PLACEMENT_WEIGHT,
                        help="placement_up/down/top/bottom 合并动作权重；限制：必须 >= 0。")
    parser.add_argument("--random-set-animation-weight", type=int,
                        default=DEFAULT_RANDOM_SET_ANIMATION_WEIGHT,
                        help="set_animation_params 动作权重；限制：必须 >= 0。")
    parser.add_argument("--random-destroy-canvas-weight", type=int,
                        default=DEFAULT_RANDOM_DESTROY_CANVAS_WEIGHT,
                        help="destroy_canvas 动作权重；限制：必须 >= 0。")
    parser.add_argument("--random-destroy-sprite-weight", type=int,
                        default=DEFAULT_RANDOM_DESTROY_SPRITE_WEIGHT,
                        help="destroy_sprite 动作权重；限制：必须 >= 0。")
    parser.add_argument("--random-destroy-placement-weight", type=int,
                        default=DEFAULT_RANDOM_DESTROY_PLACEMENT_WEIGHT,
                        help="destroy_placement 动作权重；限制：必须 >= 0。")
    parser.add_argument("--random-barrier-weight", type=int,
                        default=DEFAULT_RANDOM_BARRIER_WEIGHT,
                        help=("barrier 动作权重；限制：必须 >= 0。0 表示禁用；"
                              "值越大越常生成 barrier；实际概率约为该权重除以"
                              "所有动作权重总和。"))
    parser.add_argument("--random-generate-weight", type=int,
                        default=DEFAULT_RANDOM_GENERATE_WEIGHT,
                        help=("generate 动作权重；限制：必须 >= 0。0 表示禁用；"
                              "值越大越常生成视频导出命令，可能增加运行时间。"))
    parser.add_argument("--random-generate-duration-seconds", type=float,
                        default=DEFAULT_RANDOM_GENERATE_DURATION_SECONDS,
                        help="随机测试有效 generate 视频时长秒数；限制：必须 > 0。")
    parser.add_argument("--random-share-weight", type=int,
                        default=DEFAULT_RANDOM_SHARE_WEIGHT,
                        help=("share_canvas 动作权重；限制：必须 >= 0。0 表示禁用；"
                              "值越大越常生成共享/请求共享，会改变 barrier 参与者。"))
    parser.add_argument("--random-invalid-weight", type=int,
                        default=DEFAULT_RANDOM_INVALID_WEIGHT,
                        help=("非法参数/越权动作权重；限制：必须 >= 0。0 表示禁用；"
                              "值越大越常生成越界数字、坏 handle、越权销毁等失败场景。"))
    parser.add_argument("--random-disconnect-weight", type=int,
                        default=DEFAULT_RANDOM_DISCONNECT_WEIGHT,
                        help=("断连/重连动作权重；限制：必须 >= 0。0 表示禁用；"
                              "值越大越常生成 Disconnect 和同名重新登录场景。"))
    parser.add_argument("--random-min-sprites-per-client", type=int,
                        default=DEFAULT_RANDOM_MIN_SPRITES_PER_CLIENT,
                        help="随机测试预置每客户端 sprite 下限；限制：必须 >= 0。")
    parser.add_argument("--random-min-placements-per-client", type=int,
                        default=DEFAULT_RANDOM_MIN_PLACEMENTS_PER_CLIENT,
                        help="随机测试预置每客户端 placement 下限；限制：必须 >= 0。")
    parser.add_argument("--random-min-canvases-per-client", type=int,
                        default=DEFAULT_RANDOM_MIN_CANVASES_PER_CLIENT,
                        help="随机测试预置每客户端可访问 canvas 下限；限制：必须 >= 0。")
    parser.add_argument("--single-random", type=int, default=0, metavar="N",
                        help="运行 N 个单客户端随机测试；限制：N 必须 >= 0。")
    parser.add_argument("--single-random-ops", type=int, default=20,
                        help="单客户端随机测试操作数；限制：必须 >= 1。")
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED,
                        help="随机种子；限制：整数，相同 seed 生成同样用例。")
    parser.add_argument(
        "--stress",
        action="store_true",
        help="运行独立客户端压力测试；限制：开关参数。",
    )
    parser.add_argument(
        "--pressure",
        action="store_true",
        help="--stress 的别名，运行独立压力组；限制：开关参数。",
    )
    parser.add_argument(
        "--barrier-stress",
        action="store_true",
        help="运行线程数少于客户端数的 barrier 压力测试；限制：开关参数。",
    )
    parser.add_argument(
        "--skip-extreme",
        action="store_true",
        help="跳过极端竞态压力；限制：开关参数。",
    )
    parser.add_argument("--stress-clients", type=int,
                        default=DEFAULT_STRESS_CLIENTS,
                        help="压力测试客户端数；限制：必须 >= 2。")
    parser.add_argument("--stress-rounds", type=int,
                        default=DEFAULT_STRESS_ROUNDS,
                        help="独立压力每客户端轮数；限制：必须 >= 1。")
    parser.add_argument(
        "--random-pressure",
        nargs="?",
        const=DEFAULT_RANDOM_PRESSURE_CASES,
        type=int,
        default=0,
        metavar="N",
        help="运行 N 个大规模固定 seed 随机压力测试；限制：N 必须 >= 0。",
    )
    parser.add_argument("--random-pressure-clients", type=int,
                        default=DEFAULT_RANDOM_PRESSURE_CLIENTS,
                        help="随机压力客户端数；限制：必须 >= 2。")
    parser.add_argument("--random-pressure-commands-per-client", type=int,
                        default=DEFAULT_RANDOM_PRESSURE_COMMANDS_PER_CLIENT,
                        help="随机压力每客户端约生成的命令数；限制：必须 >= 1。")
    parser.add_argument("--keep-temp", action="store_true",
                        help="保留临时编译目录；限制：开关参数。")
    parser.add_argument("--verbose", action="store_true",
                        help="打印详细收发日志；限制：开关参数。")
    parser.add_argument("--no-memcheck", dest="memcheck",
                        action="store_false", default=DEFAULT_MEMCHECK,
                        help=("关闭 sanitizer 内存检查；限制：开关参数，默认开启。"
                              "开启时只对 student 临时副本用 ASan/LSan 编译并扫描"
                              "内存错误/泄漏日志；死锁由每条响应的 timeout 判定。"))
    args = parser.parse_args(argv)
    if args.threads < 1:
        parser.error("--threads 必须 >= 1")
    if args.timeout <= 0:
        parser.error("--timeout 必须 > 0")
    if args.build_timeout <= 0:
        parser.error("--build-timeout 必须 > 0")
    try:
        selected_implementations = parse_implementation_names(args.implementations)
    except ValueError as exc:
        parser.error(str(exc))
    if args.random_clients < 2:
        parser.error("--random-clients 必须 >= 2")
    if args.commands_per_client < 1:
        parser.error("--commands-per-client 必须 >= 1")
    if args.stress_clients < 2:
        parser.error("--stress-clients 必须 >= 2")
    if args.random_pressure_clients < 2:
        parser.error("--random-pressure-clients 必须 >= 2")
    if args.random_pressure_commands_per_client < 1:
        parser.error("--random-pressure-commands-per-client 必须 >= 1")
    if args.random < 0 or args.single_random < 0 or args.random_pressure < 0:
        parser.error("--random、--single-random、--random-pressure 必须 >= 0")
    if args.single_random_ops < 1:
        parser.error("--single-random-ops 必须 >= 1")
    if args.stress_rounds < 1:
        parser.error("--stress-rounds 必须 >= 1")
    if (
        args.random_create_weight < 0
        or args.random_place_sprite_weight < 0
        or args.random_placement_weight < 0
        or args.random_set_animation_weight < 0
        or args.random_destroy_canvas_weight < 0
        or args.random_destroy_sprite_weight < 0
        or args.random_destroy_placement_weight < 0
        or args.random_barrier_weight < 0
        or args.random_generate_weight < 0
        or args.random_share_weight < 0
        or args.random_invalid_weight < 0
        or args.random_disconnect_weight < 0
    ):
        parser.error("所有 random 权重参数都必须 >= 0")
    random_total_weight = (
        args.random_create_weight
        + args.random_place_sprite_weight
        + args.random_placement_weight
        + args.random_set_animation_weight
        + args.random_destroy_canvas_weight
        + args.random_destroy_sprite_weight
        + args.random_destroy_placement_weight
        + args.random_barrier_weight
        + args.random_generate_weight
        + args.random_share_weight
        + args.random_invalid_weight
        + args.random_disconnect_weight
    )
    if random_total_weight <= 0:
        parser.error("所有 random 权重总和必须 > 0")
    if args.random_generate_duration_seconds <= 0:
        parser.error("--random-generate-duration-seconds 必须 > 0")
    if args.random_min_sprites_per_client < 0:
        parser.error("--random-min-sprites-per-client 必须 >= 0")
    if args.random_min_placements_per_client < 0:
        parser.error("--random-min-placements-per-client 必须 >= 0")
    if args.random_min_canvases_per_client < 0:
        parser.error("--random-min-canvases-per-client 必须 >= 0")

    selected_any = (
        args.all
        or args.fixed
        or args.random > 0
        or args.single_random > 0
        or args.stress
        or args.pressure
        or args.barrier_stress
        or args.random_pressure > 0
    )
    run_fixed = args.all or args.fixed or not selected_any
    random_cases = args.random
    random_pressure_cases = args.random_pressure
    if args.all:
        random_cases = random_cases or DEFAULT_RANDOM_CASES
        random_pressure_cases = (
            random_pressure_cases or DEFAULT_RANDOM_PRESSURE_CASES
        )
    run_pressure = args.all or args.stress or args.pressure
    run_barrier_pressure = args.all or args.barrier_stress

    temp_context = tempfile.TemporaryDirectory(prefix="p2_diff_")
    temp_root = Path(temp_context.name)
    if args.keep_temp:
        temp_context.cleanup = lambda: None  # 类型检查器不理解这里替换 cleanup。

    implementation_dirs: ImplementationDirs = {
        name: temp_root / name for name in selected_implementations
    }
    try:
        generated_clients = max(
            args.stress_clients,
            args.random_clients,
            args.random_pressure_clients,
        )
        for implementation_name, directory in implementation_dirs.items():
            copy_implementation_tree(
                implementation_name, directory, generated_clients
            )
        for implementation_name, directory in implementation_dirs.items():
            build_tree(
                implementation_name,
                directory,
                args.build_timeout,
                sanitize=args.memcheck and implementation_name == "student",
            )

        all_problems: List[str] = []
        if run_fixed:
            print_group_header(
                "固定场景",
                "手写的确定性用例，覆盖基础 RPC、失败返回码、共享和 barrier。",
            )
            for scenario in scripted_scenarios():
                print_case_header(scenario.name, scenario.description)
                problems = run_one_scenario(
                    scenario,
                    implementation_dirs,
                    args.threads,
                    args.timeout,
                    args.verbose,
                    args.memcheck,
                )
                report_case_result(problems, all_problems)

        random_scenarios: List[Scenario] = []
        for offset in range(args.single_random):
            random_scenarios.append(
                random_scenario(args.seed + offset, args.single_random_ops)
            )
        for offset in range(random_cases):
            random_scenarios.append(
                random_multiclient_scenario(
                    args.seed + offset,
                    args.random_clients,
                    args.commands_per_client,
                    create_weight=args.random_create_weight,
                    place_sprite_weight=args.random_place_sprite_weight,
                    placement_weight=args.random_placement_weight,
                    set_animation_weight=args.random_set_animation_weight,
                    destroy_canvas_weight=args.random_destroy_canvas_weight,
                    destroy_sprite_weight=args.random_destroy_sprite_weight,
                    destroy_placement_weight=args.random_destroy_placement_weight,
                    barrier_weight=args.random_barrier_weight,
                    generate_weight=args.random_generate_weight,
                    share_weight=args.random_share_weight,
                    invalid_weight=args.random_invalid_weight,
                    disconnect_weight=args.random_disconnect_weight,
                    generate_duration_seconds=args.random_generate_duration_seconds,
                    min_sprites_per_client=args.random_min_sprites_per_client,
                    min_placements_per_client=(
                        args.random_min_placements_per_client
                    ),
                    min_canvases_per_client=args.random_min_canvases_per_client,
                )
            )
        if random_scenarios:
            print_group_header(
                "随机测试",
                "固定 seed 的小规模随机多客户端用例，适合日常快速复现。",
            )
            for scenario in random_scenarios:
                print_case_header(scenario.name, scenario.description)
                problems = run_one_scenario(
                    scenario,
                    implementation_dirs,
                    args.threads,
                    args.timeout,
                    args.verbose,
                    args.memcheck,
                )
                report_case_result(problems, all_problems)

        if run_pressure:
            print_group_header(
                "压力测试",
                "多个客户端并发执行互不共享的资源生命周期，检查线程池和响应顺序。",
            )
            print_case_header(
                "pressure_independent",
                "压力场景：客户端数大于工作线程数时，每个客户端独立创建、放置、移动并销毁资源。",
            )
            problems = run_pressure_pair(
                "pressure_independent",
                run_independent_pressure_on_server,
                implementation_dirs,
                args.threads,
                args.stress_clients,
                args.timeout,
                args.verbose,
                rounds=args.stress_rounds,
                memory_check=args.memcheck,
            )
            report_case_result(problems, all_problems)
            if not args.skip_extreme:
                print_case_header(
                    "pressure_barrier_disconnect",
                    "极端压力：多个 pair 中，一个 barrier 等待者断连，另一个在线参与者必须释放。",
                )
                problems = run_pressure_pair(
                    "pressure_barrier_disconnect",
                    run_barrier_disconnect_pressure_on_server,
                    implementation_dirs,
                    args.threads,
                    args.stress_clients,
                    args.timeout,
                    args.verbose,
                    memory_check=args.memcheck,
                )
                report_case_result(problems, all_problems)
                print_case_header(
                    "pressure_share_disconnect_race",
                    "极端压力：大量 share_canvas 与目标用户 Disconnect 交错，检查资源列表并发访问。",
                )
                problems = run_pressure_pair(
                    "pressure_share_disconnect_race",
                    run_share_disconnect_pressure_on_server,
                    implementation_dirs,
                    args.threads,
                    args.stress_clients,
                    args.timeout,
                    args.verbose,
                    memory_check=args.memcheck,
                )
                report_case_result(problems, all_problems)

        if run_barrier_pressure:
            print_group_header(
                "Barrier 压力测试",
                "客户端数大于工作线程数时，所有共享画布参与者同时等待 barrier。",
            )
            print_case_header(
                "pressure_barrier_underprovisioned",
                "压力场景：专门检查 barrier 不应永久占满线程池导致无法释放。",
            )
            problems = run_pressure_pair(
                "pressure_barrier_underprovisioned",
                run_barrier_pressure_on_server,
                implementation_dirs,
                args.threads,
                args.stress_clients,
                args.timeout,
                args.verbose,
                memory_check=args.memcheck,
            )
            report_case_result(problems, all_problems)

        if random_pressure_cases > 0:
            print_group_header(
                "随机压力测试",
                "固定 seed 的大规模随机多客户端用例，按默认权重混合覆盖各类 RPC。",
            )
            for offset in range(random_pressure_cases):
                pressure_seed = args.seed + 100000 + offset
                scenario = random_multiclient_scenario(
                    pressure_seed,
                    args.random_pressure_clients,
                    args.random_pressure_commands_per_client,
                    create_weight=args.random_create_weight,
                    place_sprite_weight=args.random_place_sprite_weight,
                    placement_weight=args.random_placement_weight,
                    set_animation_weight=args.random_set_animation_weight,
                    destroy_canvas_weight=args.random_destroy_canvas_weight,
                    destroy_sprite_weight=args.random_destroy_sprite_weight,
                    destroy_placement_weight=args.random_destroy_placement_weight,
                    barrier_weight=args.random_barrier_weight,
                    generate_weight=args.random_generate_weight,
                    share_weight=args.random_share_weight,
                    invalid_weight=args.random_invalid_weight,
                    disconnect_weight=args.random_disconnect_weight,
                    generate_duration_seconds=args.random_generate_duration_seconds,
                    min_sprites_per_client=args.random_min_sprites_per_client,
                    min_placements_per_client=(
                        args.random_min_placements_per_client
                    ),
                    min_canvases_per_client=args.random_min_canvases_per_client,
                )
                scenario.name = f"random_pressure_seed_{pressure_seed}"
                scenario.description = (
                    "随机压力场景：大规模多客户端确定性随机 RPC，使用均衡动作配比；"
                    f"seed={pressure_seed}，客户端={args.random_pressure_clients}，"
                    f"预置每客户端 sprite>={args.random_min_sprites_per_client}、"
                    f"placement>={args.random_min_placements_per_client}、"
                    f"canvas>={args.random_min_canvases_per_client}，预置后"
                    f"每客户端约 {args.random_pressure_commands_per_client} "
                    f"条随机命令，随机 generate 时长约 "
                    f"{args.random_generate_duration_seconds:g}s。"
                )
                print_case_header(scenario.name, scenario.description)
                problems = run_one_scenario(
                    scenario,
                    implementation_dirs,
                    args.threads,
                    args.timeout,
                    args.verbose,
                    args.memcheck,
                )
                report_case_result(problems, all_problems)

        if args.keep_temp:
            print(f"已保留临时编译目录: {temp_root}")
        print_artifact_locations()
        return 1 if all_problems else 0
    except BuildFailure as exc:
        print(exc, file=sys.stderr)
        if args.keep_temp:
            print(f"已保留临时编译目录: {temp_root}", file=sys.stderr)
        print_artifact_locations()
        return 2
    finally:
        if not args.keep_temp:
            temp_context.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
