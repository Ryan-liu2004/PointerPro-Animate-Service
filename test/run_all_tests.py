#!/usr/bin/env python3
"""
全部对拍测试入口。

中文场景注释：
这个文件只是顺序调用五个拆分后的入口，方便一次跑完：
固定场景、随机测试、压力测试、共享画布协作动画、随机压力测试。
超大共享画布长跑测试默认不运行，需要显式传 --huge-animation。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from diff_against_hai import (
    ARTIFACT_RUN_ID,
    DEFAULT_BUILD_TIMEOUT,
    DEFAULT_COLLAB_ANIMATION_DURATION_SECONDS,
    DEFAULT_COLLAB_ANIMATION_FRAME_RATE,
    DEFAULT_COLLAB_ANIMATION_ROUNDS,
    DEFAULT_COLLAB_MIN_PLACEMENTS_PER_CLIENT,
    DEFAULT_COLLAB_MIN_SPRITES_PER_CLIENT,
    DEFAULT_COMMANDS_PER_CLIENT,
    DEFAULT_HUGE_ANIMATION_CANVAS_HEIGHT,
    DEFAULT_HUGE_ANIMATION_CANVAS_WIDTH,
    DEFAULT_HUGE_ANIMATION_CLIENTS,
    DEFAULT_HUGE_ANIMATION_DURATION_SECONDS,
    DEFAULT_HUGE_ANIMATION_FRAME_RATE,
    DEFAULT_HUGE_ANIMATION_GENERATE_COUNT,
    DEFAULT_HUGE_ANIMATION_MIN_RUNTIME_SECONDS,
    DEFAULT_HUGE_ANIMATION_ROUNDS,
    DEFAULT_HUGE_BUILD_TIMEOUT,
    DEFAULT_HUGE_MIN_PLACEMENTS_PER_CLIENT,
    DEFAULT_HUGE_MIN_SPRITES_PER_CLIENT,
    DEFAULT_HUGE_TIMEOUT,
    DEFAULT_IMPLEMENTATIONS,
    DEFAULT_MEMCHECK,
    DEFAULT_RANDOM_BARRIER_WEIGHT,
    DEFAULT_RANDOM_CLIENTS,
    DEFAULT_RANDOM_CREATE_WEIGHT,
    DEFAULT_RANDOM_DESTROY_CANVAS_WEIGHT,
    DEFAULT_RANDOM_DESTROY_PLACEMENT_WEIGHT,
    DEFAULT_RANDOM_DESTROY_SPRITE_WEIGHT,
    DEFAULT_RANDOM_DISCONNECT_WEIGHT,
    DEFAULT_RANDOM_GENERATE_DURATION_SECONDS,
    DEFAULT_RANDOM_GENERATE_WEIGHT,
    DEFAULT_RANDOM_INVALID_WEIGHT,
    DEFAULT_RANDOM_MIN_CANVASES_PER_CLIENT,
    DEFAULT_RANDOM_MIN_PLACEMENTS_PER_CLIENT,
    DEFAULT_RANDOM_MIN_SPRITES_PER_CLIENT,
    DEFAULT_RANDOM_PLACE_SPRITE_WEIGHT,
    DEFAULT_RANDOM_PLACEMENT_WEIGHT,
    DEFAULT_RANDOM_PRESSURE_CLIENTS,
    DEFAULT_RANDOM_PRESSURE_COMMANDS_PER_CLIENT,
    DEFAULT_RANDOM_SEED,
    DEFAULT_RANDOM_SET_ANIMATION_WEIGHT,
    DEFAULT_RANDOM_SHARE_WEIGHT,
    DEFAULT_STRESS_CLIENTS,
    DEFAULT_STRESS_ROUNDS,
    DEFAULT_THREADS,
    DEFAULT_TIMEOUT,
    parse_implementation_names,
    print_artifact_locations,
)


TEST_DIR = Path(__file__).resolve().parent

# 文件开头可改参数：控制随机测试预置资源下限。
RANDOM_GENERATE_DURATION_SECONDS = DEFAULT_RANDOM_GENERATE_DURATION_SECONDS  # 随机 generate 视频时长秒数；限制：必须 > 0。
RANDOM_MIN_SPRITES_PER_CLIENT = DEFAULT_RANDOM_MIN_SPRITES_PER_CLIENT  # 每客户端至少拥有 sprite 数；限制：必须 >= 0。
RANDOM_MIN_PLACEMENTS_PER_CLIENT = DEFAULT_RANDOM_MIN_PLACEMENTS_PER_CLIENT  # 每客户端至少创建 placement 数；限制：必须 >= 0。
RANDOM_MIN_CANVASES_PER_CLIENT = DEFAULT_RANDOM_MIN_CANVASES_PER_CLIENT  # 每客户端至少可访问 canvas 数；限制：必须 >= 0。
ANIMATION_DURATION_SECONDS = DEFAULT_COLLAB_ANIMATION_DURATION_SECONDS  # 协作动画最终 generate 视频时长秒数；限制：必须 > 0。
ANIMATION_FRAME_RATE = DEFAULT_COLLAB_ANIMATION_FRAME_RATE  # 协作动画最终 generate 帧率；限制：必须 >= 1。
ANIMATION_FRAMES = None  # 协作动画最终 generate 帧数；限制：None 表示按时长*帧率自动计算，整数值必须 >= 2。
COLLAB_MIN_SPRITES_PER_CLIENT = DEFAULT_COLLAB_MIN_SPRITES_PER_CLIENT  # 协作动画每客户端至少创建 sprite 数；限制：必须 >= 1。
COLLAB_MIN_PLACEMENTS_PER_CLIENT = DEFAULT_COLLAB_MIN_PLACEMENTS_PER_CLIENT  # 协作动画每客户端至少创建 placement 数；限制：必须 >= 1。
HUGE_ANIMATION_CLIENTS = DEFAULT_HUGE_ANIMATION_CLIENTS  # 超大长跑客户端数；限制：必须 >= 2。
HUGE_ANIMATION_ROUNDS = DEFAULT_HUGE_ANIMATION_ROUNDS  # 超大长跑操作轮数；限制：必须 >= 1。
HUGE_MIN_RUNTIME_SECONDS = DEFAULT_HUGE_ANIMATION_MIN_RUNTIME_SECONDS  # 超大长跑单个实现最短运行秒数；限制：必须 >= 0，600 约等于 10 分钟。
HUGE_CANVAS_WIDTH = DEFAULT_HUGE_ANIMATION_CANVAS_WIDTH  # 超大长跑共享画布宽度；限制：必须 >= 32。
HUGE_CANVAS_HEIGHT = DEFAULT_HUGE_ANIMATION_CANVAS_HEIGHT  # 超大长跑共享画布高度；限制：必须 >= 32。
HUGE_ANIMATION_DURATION_SECONDS = DEFAULT_HUGE_ANIMATION_DURATION_SECONDS  # 超大长跑每个 generate 视频时长秒数；限制：必须 >= 20。
HUGE_ANIMATION_FRAME_RATE = DEFAULT_HUGE_ANIMATION_FRAME_RATE  # 超大长跑每个 generate 视频帧率；限制：必须 >= 1。
HUGE_ANIMATION_FRAMES = None  # 超大长跑每个 generate 帧数；限制：None 表示按时长*帧率自动计算，填写时必须 >= 2 且视频时长 >= 20 秒。
HUGE_GENERATE_COUNT = DEFAULT_HUGE_ANIMATION_GENERATE_COUNT  # 超大长跑 generate 次数；限制：必须在 1 到 5 之间。
HUGE_MIN_SPRITES_PER_CLIENT = DEFAULT_HUGE_MIN_SPRITES_PER_CLIENT  # 超大长跑每客户端初始 sprite 下限；限制：必须 >= 1。
HUGE_MIN_PLACEMENTS_PER_CLIENT = DEFAULT_HUGE_MIN_PLACEMENTS_PER_CLIENT  # 超大长跑每客户端初始 placement 下限；限制：必须 >= 1。
HUGE_TIMEOUT = DEFAULT_HUGE_TIMEOUT  # 超大长跑单次响应等待秒数；限制：必须 > 0。
HUGE_BUILD_TIMEOUT = DEFAULT_HUGE_BUILD_TIMEOUT  # 超大长跑编译等待秒数；限制：必须 > 0。


def run_script(script_name: str, args: list[str]) -> int:
    print(f"\n######## {script_name} ########", flush=True)
    env = os.environ.copy()
    env["P2_DIFF_RUN_ID"] = ARTIFACT_RUN_ID
    completed = subprocess.run(
        [sys.executable, str(TEST_DIR / script_name), *args],
        cwd=TEST_DIR.parent,
        env=env,
        check=False,
    )
    return completed.returncode


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="顺序运行所有拆分后的对拍测试。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
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
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED,
                        help="随机种子；限制：整数，相同 seed 生成同样用例。")
    parser.add_argument("--random-clients", type=int,
                        default=DEFAULT_RANDOM_CLIENTS,
                        help="小随机测试客户端数；限制：必须 >= 2。")
    parser.add_argument("--random-commands-per-client", type=int,
                        default=DEFAULT_COMMANDS_PER_CLIENT,
                        help="小随机每客户端约生成的命令数；限制：必须 >= 1。")
    parser.add_argument("--random-create-weight", type=int,
                        default=DEFAULT_RANDOM_CREATE_WEIGHT,
                        help="create 四类动作合并权重；限制：必须 >= 0。")
    parser.add_argument("--random-place-sprite-weight", type=int,
                        default=DEFAULT_RANDOM_PLACE_SPRITE_WEIGHT,
                        help="place_sprite 动作权重；限制：必须 >= 0。")
    parser.add_argument("--random-placement-weight", type=int,
                        default=DEFAULT_RANDOM_PLACEMENT_WEIGHT,
                        help="placement 四类动作合并权重；限制：必须 >= 0。")
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
                        help="barrier 动作权重；限制：必须 >= 0。")
    parser.add_argument("--random-generate-weight", type=int,
                        default=DEFAULT_RANDOM_GENERATE_WEIGHT,
                        help="generate 动作权重；限制：必须 >= 0。")
    parser.add_argument("--random-share-weight", type=int,
                        default=DEFAULT_RANDOM_SHARE_WEIGHT,
                        help="share_canvas 动作权重；限制：必须 >= 0。")
    parser.add_argument("--random-invalid-weight", type=int,
                        default=DEFAULT_RANDOM_INVALID_WEIGHT,
                        help="非法参数/越权动作权重；限制：必须 >= 0。")
    parser.add_argument("--random-disconnect-weight", type=int,
                        default=DEFAULT_RANDOM_DISCONNECT_WEIGHT,
                        help="Disconnect/重连动作权重；限制：必须 >= 0。")
    parser.add_argument("--random-generate-duration-seconds", type=float,
                        default=RANDOM_GENERATE_DURATION_SECONDS,
                        help="随机测试有效 generate 视频时长秒数；限制：必须 > 0。")
    parser.add_argument("--random-min-sprites-per-client", type=int,
                        default=RANDOM_MIN_SPRITES_PER_CLIENT,
                        help="随机测试预置每客户端 sprite 下限；限制：必须 >= 0。")
    parser.add_argument("--random-min-placements-per-client", type=int,
                        default=RANDOM_MIN_PLACEMENTS_PER_CLIENT,
                        help="随机测试预置每客户端 placement 下限；限制：必须 >= 0。")
    parser.add_argument("--random-min-canvases-per-client", type=int,
                        default=RANDOM_MIN_CANVASES_PER_CLIENT,
                        help="随机测试预置每客户端可访问 canvas 下限；限制：必须 >= 0。")
    parser.add_argument("--pressure-clients", type=int,
                        default=DEFAULT_STRESS_CLIENTS,
                        help="压力测试客户端数；限制：必须 >= 2。")
    parser.add_argument("--pressure-rounds", type=int,
                        default=DEFAULT_STRESS_ROUNDS,
                        help="独立压力每客户端轮数；限制：必须 >= 1。")
    parser.add_argument("--animation-rounds", type=int,
                        default=DEFAULT_COLLAB_ANIMATION_ROUNDS,
                        help="协作动画每客户端更新轮数；限制：必须 >= 1。")
    parser.add_argument("--animation-duration-seconds", type=float,
                        default=ANIMATION_DURATION_SECONDS,
                        help=("协作动画最终 generate 视频时长秒数；限制：必须 > 0。"
                              "未指定 --animation-frames 时按它计算帧数。"))
    parser.add_argument("--animation-frames", type=int,
                        default=ANIMATION_FRAMES,
                        help="协作动画最终 generate 帧数；限制：不填则按视频时长自动计算，填写时必须 >= 2。")
    parser.add_argument("--animation-frame-rate", type=int,
                        default=ANIMATION_FRAME_RATE,
                        help="协作动画最终 generate 帧率；限制：必须 >= 1。")
    parser.add_argument("--animation-min-sprites-per-client", type=int,
                        default=COLLAB_MIN_SPRITES_PER_CLIENT,
                        help="协作动画每客户端至少创建 sprite 数；限制：必须 >= 1。")
    parser.add_argument("--animation-min-placements-per-client", type=int,
                        default=COLLAB_MIN_PLACEMENTS_PER_CLIENT,
                        help="协作动画每客户端至少创建 placement 数；限制：必须 >= 1。")
    parser.add_argument("--huge-animation", action="store_true",
                        help="运行超大共享画布长跑测试；限制：开关参数，默认不运行。")
    parser.add_argument("--huge-clients", type=int,
                        default=HUGE_ANIMATION_CLIENTS,
                        help="超大长跑客户端数；限制：必须 >= 2。")
    parser.add_argument("--huge-rounds", type=int,
                        default=HUGE_ANIMATION_ROUNDS,
                        help="超大长跑操作轮数；限制：必须 >= 1。")
    parser.add_argument("--huge-min-runtime-seconds", type=float,
                        default=HUGE_MIN_RUNTIME_SECONDS,
                        help="超大长跑单个实现至少运行秒数；限制：必须 >= 0。")
    parser.add_argument("--huge-canvas-width", type=int,
                        default=HUGE_CANVAS_WIDTH,
                        help="超大长跑共享画布宽度；限制：必须 >= 32。")
    parser.add_argument("--huge-canvas-height", type=int,
                        default=HUGE_CANVAS_HEIGHT,
                        help="超大长跑共享画布高度；限制：必须 >= 32。")
    parser.add_argument("--huge-duration-seconds", type=float,
                        default=HUGE_ANIMATION_DURATION_SECONDS,
                        help="超大长跑每个 generate 视频时长秒数；限制：必须 >= 20。")
    parser.add_argument("--huge-frames", type=int,
                        default=HUGE_ANIMATION_FRAMES,
                        help="超大长跑每个 generate 帧数；限制：不填则按视频时长自动计算，填写时必须 >= 2 且视频时长 >= 20 秒。")
    parser.add_argument("--huge-frame-rate", type=int,
                        default=HUGE_ANIMATION_FRAME_RATE,
                        help="超大长跑每个 generate 视频帧率；限制：必须 >= 1。")
    parser.add_argument("--huge-generate-count", type=int,
                        default=HUGE_GENERATE_COUNT,
                        help="超大长跑最终 generate 次数；限制：必须在 1 到 5 之间。")
    parser.add_argument("--huge-min-sprites-per-client", type=int,
                        default=HUGE_MIN_SPRITES_PER_CLIENT,
                        help="超大长跑每客户端初始 sprite 数；限制：必须 >= 1。")
    parser.add_argument("--huge-min-placements-per-client", type=int,
                        default=HUGE_MIN_PLACEMENTS_PER_CLIENT,
                        help="超大长跑每客户端初始 placement 数；限制：必须 >= 1。")
    parser.add_argument("--huge-timeout", type=float,
                        default=HUGE_TIMEOUT,
                        help="超大长跑单次响应等待秒数；限制：必须 > 0。")
    parser.add_argument("--huge-build-timeout", type=float,
                        default=HUGE_BUILD_TIMEOUT,
                        help="超大长跑编译等待秒数；限制：必须 > 0。")
    parser.add_argument("--random-pressure-clients", type=int,
                        default=DEFAULT_RANDOM_PRESSURE_CLIENTS,
                        help="随机压力客户端数；限制：必须 >= 2。")
    parser.add_argument("--random-pressure-commands-per-client", type=int,
                        default=DEFAULT_RANDOM_PRESSURE_COMMANDS_PER_CLIENT,
                        help="随机压力每客户端约生成的命令数；限制：必须 >= 1。")
    parser.add_argument("--skip-barrier", action="store_true",
                        help="跳过 barrier 压力；限制：开关参数。")
    parser.add_argument("--skip-extreme", action="store_true",
                        help="跳过极端竞态压力；限制：开关参数。")
    parser.add_argument("--skip-animation", action="store_true",
                        help="跳过共享画布协作动画压力；限制：开关参数。")
    parser.add_argument("--keep-temp", action="store_true",
                        help="保留临时编译目录；限制：开关参数。")
    parser.add_argument("--verbose", action="store_true",
                        help="打印详细收发日志；限制：开关参数。")
    parser.add_argument("--no-memcheck", dest="memcheck",
                        action="store_false", default=DEFAULT_MEMCHECK,
                        help=("关闭 sanitizer 内存检查；限制：开关参数，默认开启。"
                              "开启时每个子测试都会用 ASan/LSan 编译 student 临时副本，"
                              "并把响应 timeout 视为可能死锁/阻塞。"))
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
    if args.random_commands_per_client < 1:
        parser.error("--random-commands-per-client 必须 >= 1")
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
    if args.pressure_clients < 2:
        parser.error("--pressure-clients 必须 >= 2")
    if args.pressure_rounds < 1:
        parser.error("--pressure-rounds 必须 >= 1")
    if args.animation_rounds < 1:
        parser.error("--animation-rounds 必须 >= 1")
    if args.animation_duration_seconds <= 0:
        parser.error("--animation-duration-seconds 必须 > 0")
    if args.animation_frames is not None and args.animation_frames < 2:
        parser.error("--animation-frames 必须 >= 2")
    if args.animation_frame_rate < 1:
        parser.error("--animation-frame-rate 必须 >= 1")
    if args.animation_min_sprites_per_client < 1:
        parser.error("--animation-min-sprites-per-client 必须 >= 1")
    if args.animation_min_placements_per_client < 1:
        parser.error("--animation-min-placements-per-client 必须 >= 1")
    if args.animation_frames is None:
        args.animation_frames = max(
            2,
            round(args.animation_duration_seconds * args.animation_frame_rate),
        )
    if args.huge_clients < 2:
        parser.error("--huge-clients 必须 >= 2")
    if args.huge_rounds < 1:
        parser.error("--huge-rounds 必须 >= 1")
    if args.huge_min_runtime_seconds < 0:
        parser.error("--huge-min-runtime-seconds 必须 >= 0")
    if args.huge_canvas_width < 32:
        parser.error("--huge-canvas-width 必须 >= 32")
    if args.huge_canvas_height < 32:
        parser.error("--huge-canvas-height 必须 >= 32")
    if args.huge_duration_seconds < 20:
        parser.error("--huge-duration-seconds 必须 >= 20")
    if args.huge_frames is not None and args.huge_frames < 2:
        parser.error("--huge-frames 必须 >= 2")
    if args.huge_frame_rate < 1:
        parser.error("--huge-frame-rate 必须 >= 1")
    if args.huge_frames is None:
        args.huge_frames = max(
            2,
            round(args.huge_duration_seconds * args.huge_frame_rate),
        )
    if args.huge_frames / args.huge_frame_rate < 20:
        parser.error("--huge-frames / --huge-frame-rate 必须 >= 20 秒")
    if args.huge_generate_count < 1 or args.huge_generate_count > 5:
        parser.error("--huge-generate-count 必须在 1 到 5 之间")
    if args.huge_min_sprites_per_client < 1:
        parser.error("--huge-min-sprites-per-client 必须 >= 1")
    if args.huge_min_placements_per_client < 1:
        parser.error("--huge-min-placements-per-client 必须 >= 1")
    if args.huge_timeout <= 0:
        parser.error("--huge-timeout 必须 > 0")
    if args.huge_build_timeout <= 0:
        parser.error("--huge-build-timeout 必须 > 0")
    if args.random_pressure_clients < 2:
        parser.error("--random-pressure-clients 必须 >= 2")
    if args.random_pressure_commands_per_client < 1:
        parser.error("--random-pressure-commands-per-client 必须 >= 1")

    common = [
        "--threads", str(args.threads),
        "--timeout", str(args.timeout),
        "--build-timeout", str(args.build_timeout),
        "--implementations", ",".join(selected_implementations),
    ]
    if args.keep_temp:
        common.append("--keep-temp")
    if args.verbose:
        common.append("--verbose")
    if not args.memcheck:
        common.append("--no-memcheck")
    random_weights = [
        "--random-create-weight", str(args.random_create_weight),
        "--random-place-sprite-weight", str(args.random_place_sprite_weight),
        "--random-placement-weight", str(args.random_placement_weight),
        "--random-set-animation-weight", str(args.random_set_animation_weight),
        "--random-destroy-canvas-weight", str(args.random_destroy_canvas_weight),
        "--random-destroy-sprite-weight", str(args.random_destroy_sprite_weight),
        "--random-destroy-placement-weight",
        str(args.random_destroy_placement_weight),
        "--random-barrier-weight", str(args.random_barrier_weight),
        "--random-generate-weight", str(args.random_generate_weight),
        "--random-share-weight", str(args.random_share_weight),
        "--random-invalid-weight", str(args.random_invalid_weight),
        "--random-disconnect-weight", str(args.random_disconnect_weight),
    ]
    random_generate_options = [
        "--random-generate-duration-seconds",
        str(args.random_generate_duration_seconds),
    ]
    random_resource_floors = [
        "--random-min-sprites-per-client",
        str(args.random_min_sprites_per_client),
        "--random-min-placements-per-client",
        str(args.random_min_placements_per_client),
        "--random-min-canvases-per-client",
        str(args.random_min_canvases_per_client),
    ]
    huge_common = [
        "--threads", str(args.threads),
        "--timeout", str(max(args.timeout, args.huge_timeout)),
        "--build-timeout", str(max(args.build_timeout, args.huge_build_timeout)),
        "--implementations", ",".join(selected_implementations),
    ]
    if args.keep_temp:
        huge_common.append("--keep-temp")
    if args.verbose:
        huge_common.append("--verbose")
    if not args.memcheck:
        huge_common.append("--no-memcheck")

    results = [
        run_script("run_fixed_tests.py", common),
        run_script(
            "run_random_tests.py",
            [
                *common,
                "--seed", str(args.seed),
                "--clients", str(args.random_clients),
                "--commands-per-client",
                str(args.random_commands_per_client),
                *random_weights,
                *random_generate_options,
                *random_resource_floors,
            ],
        ),
        run_script(
            "run_pressure_tests.py",
            [
                *common,
                "--clients", str(args.pressure_clients),
                "--rounds", str(args.pressure_rounds),
                *(["--skip-barrier"] if args.skip_barrier else []),
                *(["--skip-extreme"] if args.skip_extreme else []),
            ],
        ),
        *(
            []
            if args.skip_animation
            else [
                run_script(
                    "run_collaborative_animation_tests.py",
                    [
                        *common,
                        "--clients", str(args.pressure_clients),
                        "--rounds", str(args.animation_rounds),
                        "--duration-seconds",
                        str(args.animation_duration_seconds),
                        "--frames", str(args.animation_frames),
                        "--frame-rate", str(args.animation_frame_rate),
                        "--min-sprites-per-client",
                        str(args.animation_min_sprites_per_client),
                        "--min-placements-per-client",
                        str(args.animation_min_placements_per_client),
                    ],
                )
            ]
        ),
        *(
            [
                run_script(
                    "run_huge_animation_tests.py",
                    [
                        *huge_common,
                        "--clients", str(args.huge_clients),
                        "--rounds", str(args.huge_rounds),
                        "--min-runtime-seconds",
                        str(args.huge_min_runtime_seconds),
                        "--canvas-width", str(args.huge_canvas_width),
                        "--canvas-height", str(args.huge_canvas_height),
                        "--duration-seconds", str(args.huge_duration_seconds),
                        "--frames", str(args.huge_frames),
                        "--frame-rate", str(args.huge_frame_rate),
                        "--generate-count", str(args.huge_generate_count),
                        "--min-sprites-per-client",
                        str(args.huge_min_sprites_per_client),
                        "--min-placements-per-client",
                        str(args.huge_min_placements_per_client),
                    ],
                )
            ]
            if args.huge_animation
            else []
        ),
        run_script(
            "run_random_pressure_tests.py",
            [
                *common,
                "--seed", str(args.seed),
                "--clients", str(args.random_pressure_clients),
                "--commands-per-client",
                str(args.random_pressure_commands_per_client),
                *random_weights,
                *random_generate_options,
                *random_resource_floors,
            ],
        ),
    ]
    print_artifact_locations()
    return 1 if any(code != 0 for code in results) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
