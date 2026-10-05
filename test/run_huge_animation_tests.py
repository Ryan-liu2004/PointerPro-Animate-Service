#!/usr/bin/env python3
"""
超大共享画布长跑压力入口。

中文场景注释：
所有客户端共同使用一张大画布，每个客户端创建大量 sprite 和 placement，
随后执行长时间、多轮次的层级移动、动画参数更新、barrier 同步和动态增量
资源创建。测试默认会让每个实现至少运行约 10 分钟，最后 generate 少量
不少于 20 秒的长动画，用于观察资源管理、锁顺序、长时间运行和最终视频效果。
"""

from __future__ import annotations

import argparse
from typing import List

from diff_against_hai import (
    DEFAULT_HUGE_ANIMATION_CANVAS_HEIGHT,
    DEFAULT_HUGE_ANIMATION_CANVAS_WIDTH,
    DEFAULT_HUGE_ANIMATION_DURATION_SECONDS,
    DEFAULT_HUGE_ANIMATION_FRAME_RATE,
    DEFAULT_HUGE_ANIMATION_GENERATE_COUNT,
    DEFAULT_HUGE_ANIMATION_CLIENTS,
    DEFAULT_HUGE_ANIMATION_MIN_RUNTIME_SECONDS,
    DEFAULT_HUGE_ANIMATION_ROUNDS,
    DEFAULT_HUGE_BUILD_TIMEOUT,
    DEFAULT_HUGE_MIN_PLACEMENTS_PER_CLIENT,
    DEFAULT_HUGE_MIN_SPRITES_PER_CLIENT,
    DEFAULT_HUGE_TIMEOUT,
    run_huge_animation_soak_on_server,
)
from diff_runner_common import (
    add_common_args,
    print_group_header,
    run_one_pressure_case,
    run_with_environment,
    validate_common_args,
)

# 文件开头可改参数：控制超大长跑测试规模、时长和最终视频。
HUGE_ANIMATION_CLIENTS = DEFAULT_HUGE_ANIMATION_CLIENTS  # 客户端数量；限制：必须 >= 2。
HUGE_ANIMATION_ROUNDS = DEFAULT_HUGE_ANIMATION_ROUNDS  # 操作轮数；限制：必须 >= 1。
HUGE_MIN_RUNTIME_SECONDS = DEFAULT_HUGE_ANIMATION_MIN_RUNTIME_SECONDS  # 单个实现最短运行秒数；限制：必须 >= 0，600 约等于 10 分钟。
HUGE_CANVAS_WIDTH = DEFAULT_HUGE_ANIMATION_CANVAS_WIDTH  # 共享画布宽度；限制：必须 >= 32。
HUGE_CANVAS_HEIGHT = DEFAULT_HUGE_ANIMATION_CANVAS_HEIGHT  # 共享画布高度；限制：必须 >= 32。
HUGE_ANIMATION_DURATION_SECONDS = DEFAULT_HUGE_ANIMATION_DURATION_SECONDS  # 每个 generate 视频时长秒数；限制：必须 >= 20。
HUGE_ANIMATION_FRAME_RATE = DEFAULT_HUGE_ANIMATION_FRAME_RATE  # 每个 generate 视频帧率；限制：必须 >= 1。
HUGE_ANIMATION_FRAMES = None  # 每个 generate 帧数；限制：None 表示按时长*帧率自动计算，填写时必须 >= 2 且视频时长 >= 20 秒。
HUGE_GENERATE_COUNT = DEFAULT_HUGE_ANIMATION_GENERATE_COUNT  # generate 次数；限制：必须在 1 到 5 之间。
HUGE_MIN_SPRITES_PER_CLIENT = DEFAULT_HUGE_MIN_SPRITES_PER_CLIENT  # 每客户端初始 sprite 下限；限制：必须 >= 1。
HUGE_MIN_PLACEMENTS_PER_CLIENT = DEFAULT_HUGE_MIN_PLACEMENTS_PER_CLIENT  # 每客户端初始 placement 下限；限制：必须 >= 1。
HUGE_TIMEOUT = DEFAULT_HUGE_TIMEOUT  # 单次响应等待秒数；限制：必须 > 0，长视频 generate 建议 >= 300。
HUGE_BUILD_TIMEOUT = DEFAULT_HUGE_BUILD_TIMEOUT  # 编译等待秒数；限制：必须 > 0。


def _override_default(parser: argparse.ArgumentParser, dest: str,
                      value: object) -> None:
    parser.set_defaults(**{dest: value})
    for action in parser._actions:
        if action.dest == dest:
            action.default = value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="运行至少 10 分钟级别的超大共享画布协作动画长跑测试。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_common_args(parser)
    _override_default(parser, "timeout", HUGE_TIMEOUT)
    _override_default(parser, "build_timeout", HUGE_BUILD_TIMEOUT)
    parser.add_argument("--clients", type=int, default=HUGE_ANIMATION_CLIENTS,
                        help="客户端数量；限制：必须 >= 2。")
    parser.add_argument("--rounds", type=int, default=HUGE_ANIMATION_ROUNDS,
                        help="长跑操作轮数；限制：必须 >= 1。")
    parser.add_argument("--min-runtime-seconds", type=float,
                        default=HUGE_MIN_RUNTIME_SECONDS,
                        help="单个实现至少运行的秒数；限制：必须 >= 0，默认 600 秒约 10 分钟。")
    parser.add_argument("--canvas-width", type=int,
                        default=HUGE_CANVAS_WIDTH,
                        help="共享画布宽度；限制：必须 >= 32。")
    parser.add_argument("--canvas-height", type=int,
                        default=HUGE_CANVAS_HEIGHT,
                        help="共享画布高度；限制：必须 >= 32。")
    parser.add_argument("--duration-seconds", type=float,
                        default=HUGE_ANIMATION_DURATION_SECONDS,
                        help="每个 generate 视频时长秒数；限制：必须 >= 20。")
    parser.add_argument("--frames", type=int,
                        default=HUGE_ANIMATION_FRAMES,
                        help="每个 generate 帧数；限制：不填则按视频时长自动计算，填写时必须 >= 2 且帧数/帧率 >= 20。")
    parser.add_argument("--frame-rate", type=int,
                        default=HUGE_ANIMATION_FRAME_RATE,
                        help="每个 generate 视频帧率；限制：必须 >= 1。")
    parser.add_argument("--generate-count", type=int,
                        default=HUGE_GENERATE_COUNT,
                        help="最终 generate 次数；限制：必须在 1 到 5 之间。")
    parser.add_argument("--min-sprites-per-client", type=int,
                        default=HUGE_MIN_SPRITES_PER_CLIENT,
                        help="每客户端初始创建 sprite 数；限制：必须 >= 1。")
    parser.add_argument("--min-placements-per-client", type=int,
                        default=HUGE_MIN_PLACEMENTS_PER_CLIENT,
                        help="每客户端初始创建 placement 数；限制：必须 >= 1。")
    args = parser.parse_args()
    validate_common_args(parser, args)

    if args.clients < 2:
        parser.error("--clients 必须 >= 2")
    if args.rounds < 1:
        parser.error("--rounds 必须 >= 1")
    if args.min_runtime_seconds < 0:
        parser.error("--min-runtime-seconds 必须 >= 0")
    if args.canvas_width < 32:
        parser.error("--canvas-width 必须 >= 32")
    if args.canvas_height < 32:
        parser.error("--canvas-height 必须 >= 32")
    if args.duration_seconds < 20:
        parser.error("--duration-seconds 必须 >= 20")
    if args.frame_rate < 1:
        parser.error("--frame-rate 必须 >= 1")
    if args.frames is not None and args.frames < 2:
        parser.error("--frames 必须 >= 2")
    if args.frames is None:
        args.frames = max(2, round(args.duration_seconds * args.frame_rate))
    if args.frames / args.frame_rate < 20:
        parser.error("--frames / --frame-rate 必须 >= 20 秒")
    if args.generate_count < 1 or args.generate_count > 5:
        parser.error("--generate-count 必须在 1 到 5 之间")
    if args.min_sprites_per_client < 1:
        parser.error("--min-sprites-per-client 必须 >= 1")
    if args.min_placements_per_client < 1:
        parser.error("--min-placements-per-client 必须 >= 1")

    def huge_func(server, client_count, rounds, timeout, verbose):
        return run_huge_animation_soak_on_server(
            server,
            client_count,
            rounds,
            timeout,
            verbose,
            min_runtime_seconds=args.min_runtime_seconds,
            canvas_width=args.canvas_width,
            canvas_height=args.canvas_height,
            frame_count=args.frames,
            frame_rate=args.frame_rate,
            generate_count=args.generate_count,
            min_sprites_per_client=args.min_sprites_per_client,
            min_placements_per_client=args.min_placements_per_client,
        )

    def body(implementation_dirs) -> int:
        all_problems: List[str] = []
        print_group_header(
            "超大共享画布长跑压力测试",
            "多客户端、多资源、多操作长时间协作；最终 generate 不超过 5 次，"
            "每个视频至少 20 秒。",
        )
        all_problems.extend(
            run_one_pressure_case(
                "huge_collaborative_animation_soak",
                "超大场景：大画布、密集 sprite/placement、长时间层级移动、"
                "动画参数更新、barrier 和少量长视频 generate。",
                huge_func,
                implementation_dirs,
                args.threads,
                args.clients,
                args.timeout,
                args.verbose,
                rounds=args.rounds,
                memory_check=args.memcheck,
            )
        )
        return 1 if all_problems else 0

    return run_with_environment(
        generated_clients=args.clients,
        build_timeout=args.build_timeout,
        keep_temp=args.keep_temp,
        memcheck=args.memcheck,
        body=body,
        implementations=args.selected_implementations,
    )


if __name__ == "__main__":
    raise SystemExit(main())
