#!/usr/bin/env python3
"""
共享画布协作动画压力入口。

中文场景注释：
所有客户端登录后共同使用同一张画布，每个人都创建自己的 sprite 并放置到
共享画布上，随后执行多轮层级移动/动画参数更新，最后只 generate 一次几秒
的小动画。这个测试复用压力测试的客户端数、线程数、timeout 和轮数概念，
但默认轮数较低，避免视频生成和大量 RPC 让总运行时间超过 5 分钟。
"""

from __future__ import annotations

import argparse
from typing import List

from diff_against_hai import (
    DEFAULT_COLLAB_ANIMATION_DURATION_SECONDS,
    DEFAULT_COLLAB_ANIMATION_FRAME_RATE,
    DEFAULT_COLLAB_ANIMATION_ROUNDS,
    DEFAULT_COLLAB_MIN_PLACEMENTS_PER_CLIENT,
    DEFAULT_COLLAB_MIN_SPRITES_PER_CLIENT,
    DEFAULT_STRESS_CLIENTS,
    run_collaborative_animation_pressure_on_server,
)
from diff_runner_common import (
    add_common_args,
    print_group_header,
    run_one_pressure_case,
    run_with_environment,
    validate_common_args,
)

# 文件开头可改参数：控制协作动画测试规模和最终视频时长。
COLLAB_ANIMATION_CLIENTS = DEFAULT_STRESS_CLIENTS  # 协作客户端数；限制：必须 >= 2。
COLLAB_ANIMATION_ROUNDS = DEFAULT_COLLAB_ANIMATION_ROUNDS  # 每客户端协作更新轮数；限制：必须 >= 1。
COLLAB_ANIMATION_DURATION_SECONDS = DEFAULT_COLLAB_ANIMATION_DURATION_SECONDS  # 最终 generate 视频时长秒数；限制：必须 > 0。
COLLAB_ANIMATION_FRAME_RATE = DEFAULT_COLLAB_ANIMATION_FRAME_RATE  # 最终 generate 帧率；限制：必须 >= 1。
COLLAB_ANIMATION_FRAMES = None  # 最终 generate 帧数；限制：None 表示按时长*帧率自动计算，整数值必须 >= 2。
COLLAB_MIN_SPRITES_PER_CLIENT = DEFAULT_COLLAB_MIN_SPRITES_PER_CLIENT  # 每客户端至少创建 sprite 数；限制：必须 >= 1。
COLLAB_MIN_PLACEMENTS_PER_CLIENT = DEFAULT_COLLAB_MIN_PLACEMENTS_PER_CLIENT  # 每客户端至少创建 placement 数；限制：必须 >= 1。


def main() -> int:
    parser = argparse.ArgumentParser(
        description="运行共享画布协作动画压力对拍测试。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_common_args(parser)
    parser.add_argument("--clients", type=int, default=COLLAB_ANIMATION_CLIENTS,
                        help="协作客户端数；限制：必须 >= 2。")
    parser.add_argument("--rounds", type=int,
                        default=COLLAB_ANIMATION_ROUNDS,
                        help="每个客户端参与的协作更新轮数；限制：必须 >= 1。")
    parser.add_argument("--duration-seconds", type=float,
                        default=COLLAB_ANIMATION_DURATION_SECONDS,
                        help=("最终 generate 的视频时长秒数；限制：必须 > 0。"
                              "未指定 --frames 时用它乘以帧率计算帧数。"))
    parser.add_argument("--frames", type=int,
                        default=COLLAB_ANIMATION_FRAMES,
                        help="最终 generate 的帧数；限制：不填则按视频时长自动计算，填写时必须 >= 2。")
    parser.add_argument("--frame-rate", type=int,
                        default=COLLAB_ANIMATION_FRAME_RATE,
                        help="最终 generate 的帧率；限制：必须 >= 1。")
    parser.add_argument("--min-sprites-per-client", type=int,
                        default=COLLAB_MIN_SPRITES_PER_CLIENT,
                        help="每个客户端至少创建的 sprite 数；限制：必须 >= 1。")
    parser.add_argument("--min-placements-per-client", type=int,
                        default=COLLAB_MIN_PLACEMENTS_PER_CLIENT,
                        help="每个客户端至少创建的 placement 数；限制：必须 >= 1。")
    args = parser.parse_args()
    validate_common_args(parser, args)

    if args.clients < 2:
        parser.error("--clients 必须 >= 2")
    if args.rounds < 1:
        parser.error("--rounds 必须 >= 1")
    if args.duration_seconds <= 0:
        parser.error("--duration-seconds 必须 > 0")
    if args.frames is not None and args.frames < 2:
        parser.error("--frames 必须 >= 2")
    if args.frame_rate < 1:
        parser.error("--frame-rate 必须 >= 1")
    if args.min_sprites_per_client < 1:
        parser.error("--min-sprites-per-client 必须 >= 1")
    if args.min_placements_per_client < 1:
        parser.error("--min-placements-per-client 必须 >= 1")
    if args.frames is None:
        args.frames = max(2, round(args.duration_seconds * args.frame_rate))

    def collaborative_func(server, client_count, rounds, timeout, verbose):
        return run_collaborative_animation_pressure_on_server(
            server,
            client_count,
            rounds,
            timeout,
            verbose,
            frame_count=args.frames,
            frame_rate=args.frame_rate,
            min_sprites_per_client=args.min_sprites_per_client,
            min_placements_per_client=args.min_placements_per_client,
        )

    def body(implementation_dirs) -> int:
        all_problems: List[str] = []
        print_group_header(
            "共享画布协作动画压力测试",
            "多客户端共同创作一张画布，最后生成可播放的短动画。",
        )
        all_problems.extend(
            run_one_pressure_case(
                "pressure_collaborative_animation",
                "协作场景：一张共享画布，所有客户端创建并移动自己的对象，"
                f"每客户端至少 {args.min_sprites_per_client} 个 sprite、"
                f"{args.min_placements_per_client} 个 placement，"
                "最后低频 generate 一次短视频。",
                collaborative_func,
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
