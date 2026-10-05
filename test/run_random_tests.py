#!/usr/bin/env python3
"""
随机测试对拍入口。

中文场景注释：
这里生成小规模、固定 seed 的多客户端随机测试。随机内容包括正常 RPC、
参数越界、失败返回、越权访问、share_canvas、barrier、generate 和断连重连。
"""

from __future__ import annotations

import argparse
from typing import List

from diff_against_hai import (
    DEFAULT_COMMANDS_PER_CLIENT,
    DEFAULT_RANDOM_CASES,
    DEFAULT_RANDOM_CLIENTS,
    DEFAULT_RANDOM_GENERATE_DURATION_SECONDS,
    DEFAULT_RANDOM_MIN_CANVASES_PER_CLIENT,
    DEFAULT_RANDOM_MIN_PLACEMENTS_PER_CLIENT,
    DEFAULT_RANDOM_MIN_SPRITES_PER_CLIENT,
    Scenario,
    random_multiclient_scenario,
    random_scenario,
)
from diff_runner_common import (
    add_common_args,
    add_random_generate_duration_arg,
    add_random_resource_floor_args,
    add_random_weight_args,
    add_seed_arg,
    run_scenario_group,
    run_with_environment,
    validate_common_args,
    validate_random_generate_duration_arg,
    validate_random_resource_floor_args,
    validate_random_weight_args,
)

# 文件开头可改参数：控制随机测试规模和预置资源下限。
RANDOM_CASES = DEFAULT_RANDOM_CASES  # 多客户端随机用例数量；限制：必须 >= 0。
RANDOM_CLIENTS = DEFAULT_RANDOM_CLIENTS  # 多客户端数量；限制：必须 >= 2。
RANDOM_COMMANDS_PER_CLIENT = DEFAULT_COMMANDS_PER_CLIENT  # 预置后每客户端额外随机命令数；限制：必须 >= 1。
RANDOM_GENERATE_DURATION_SECONDS = DEFAULT_RANDOM_GENERATE_DURATION_SECONDS  # 随机 generate 视频时长秒数；限制：必须 > 0。
RANDOM_MIN_SPRITES_PER_CLIENT = DEFAULT_RANDOM_MIN_SPRITES_PER_CLIENT  # 每客户端至少拥有 sprite 数；限制：必须 >= 0。
RANDOM_MIN_PLACEMENTS_PER_CLIENT = DEFAULT_RANDOM_MIN_PLACEMENTS_PER_CLIENT  # 每客户端至少创建 placement 数；限制：必须 >= 0。
RANDOM_MIN_CANVASES_PER_CLIENT = DEFAULT_RANDOM_MIN_CANVASES_PER_CLIENT  # 每客户端至少可访问 canvas 数；限制：必须 >= 0。


def main() -> int:
    parser = argparse.ArgumentParser(
        description="运行固定 seed 的随机对拍测试。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_common_args(parser)
    add_seed_arg(parser)
    add_random_weight_args(parser)
    add_random_generate_duration_arg(parser, RANDOM_GENERATE_DURATION_SECONDS)
    add_random_resource_floor_args(
        parser,
        RANDOM_MIN_SPRITES_PER_CLIENT,
        RANDOM_MIN_PLACEMENTS_PER_CLIENT,
        RANDOM_MIN_CANVASES_PER_CLIENT,
    )
    parser.add_argument("--cases", type=int, default=RANDOM_CASES,
                        help="多客户端随机用例数量；限制：必须 >= 0。")
    parser.add_argument("--clients", type=int, default=RANDOM_CLIENTS,
                        help="多客户端随机测试的客户端数；限制：必须 >= 2。")
    parser.add_argument("--commands-per-client", type=int,
                        default=RANDOM_COMMANDS_PER_CLIENT,
                        help="每个客户端约生成的命令数；限制：必须 >= 1。")
    parser.add_argument("--single-client-cases", type=int, default=0,
                        help="单客户端随机用例数量；限制：必须 >= 0。")
    parser.add_argument("--single-client-ops", type=int, default=20,
                        help="单客户端随机用例操作数；限制：必须 >= 1。")
    args = parser.parse_args()
    validate_common_args(parser, args)
    validate_random_weight_args(parser, args)
    validate_random_generate_duration_arg(parser, args)
    validate_random_resource_floor_args(parser, args)

    if args.clients < 2:
        parser.error("--clients 必须 >= 2")
    if args.commands_per_client < 1:
        parser.error("--commands-per-client 必须 >= 1")
    if args.cases < 0 or args.single_client_cases < 0:
        parser.error("--cases 和 --single-client-cases 必须 >= 0")
    if args.single_client_ops < 1:
        parser.error("--single-client-ops 必须 >= 1")

    scenarios: List[Scenario] = []
    for offset in range(args.single_client_cases):
        scenarios.append(random_scenario(args.seed + offset,
                                         args.single_client_ops))
    for offset in range(args.cases):
        scenarios.append(
            random_multiclient_scenario(
                args.seed + offset,
                args.clients,
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
                min_placements_per_client=args.random_min_placements_per_client,
                min_canvases_per_client=args.random_min_canvases_per_client,
            )
        )

    def body(implementation_dirs) -> int:
        problems = run_scenario_group(
            "随机测试",
            "小规模固定 seed 随机多客户端用例，适合日常快速复现。",
            scenarios,
            implementation_dirs,
            args.threads,
            args.timeout,
            args.verbose,
            args.memcheck,
        )
        return 1 if problems else 0

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
