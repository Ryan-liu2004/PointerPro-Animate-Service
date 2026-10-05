#!/usr/bin/env python3
"""
随机压力测试对拍入口。

中文场景注释：
这是大规模固定 seed 随机测试，客户端数和每客户端命令数都更高，
默认使用均衡配比覆盖各类 RPC，不再刻意偏向 barrier/share/generate/断连。
"""

from __future__ import annotations

import argparse
from typing import List

from diff_against_hai import (
    DEFAULT_RANDOM_GENERATE_DURATION_SECONDS,
    DEFAULT_RANDOM_MIN_CANVASES_PER_CLIENT,
    DEFAULT_RANDOM_MIN_PLACEMENTS_PER_CLIENT,
    DEFAULT_RANDOM_MIN_SPRITES_PER_CLIENT,
    DEFAULT_RANDOM_PRESSURE_CASES,
    DEFAULT_RANDOM_PRESSURE_CLIENTS,
    DEFAULT_RANDOM_PRESSURE_COMMANDS_PER_CLIENT,
    Scenario,
    random_multiclient_scenario,
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

# 文件开头可改参数：控制随机压力规模和预置资源下限。
RANDOM_PRESSURE_CASES = DEFAULT_RANDOM_PRESSURE_CASES  # 随机压力用例数量；限制：必须 >= 0。
RANDOM_PRESSURE_CLIENTS = DEFAULT_RANDOM_PRESSURE_CLIENTS  # 随机压力客户端数；限制：必须 >= 2。
RANDOM_PRESSURE_COMMANDS_PER_CLIENT = DEFAULT_RANDOM_PRESSURE_COMMANDS_PER_CLIENT  # 预置后每客户端额外随机命令数；限制：必须 >= 1。
RANDOM_GENERATE_DURATION_SECONDS = DEFAULT_RANDOM_GENERATE_DURATION_SECONDS  # 随机 generate 视频时长秒数；限制：必须 > 0。
RANDOM_MIN_SPRITES_PER_CLIENT = DEFAULT_RANDOM_MIN_SPRITES_PER_CLIENT  # 每客户端至少拥有 sprite 数；限制：必须 >= 0。
RANDOM_MIN_PLACEMENTS_PER_CLIENT = DEFAULT_RANDOM_MIN_PLACEMENTS_PER_CLIENT  # 每客户端至少创建 placement 数；限制：必须 >= 0。
RANDOM_MIN_CANVASES_PER_CLIENT = DEFAULT_RANDOM_MIN_CANVASES_PER_CLIENT  # 每客户端至少可访问 canvas 数；限制：必须 >= 0。


def main() -> int:
    parser = argparse.ArgumentParser(
        description="运行固定 seed 的随机压力对拍测试。",
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
    parser.add_argument("--cases", type=int,
                        default=RANDOM_PRESSURE_CASES,
                        help="随机压力用例数量；限制：必须 >= 0。")
    parser.add_argument("--clients", type=int,
                        default=RANDOM_PRESSURE_CLIENTS,
                        help="随机压力客户端数；限制：必须 >= 2。")
    parser.add_argument("--commands-per-client", type=int,
                        default=RANDOM_PRESSURE_COMMANDS_PER_CLIENT,
                        help="每个客户端约生成的命令数；限制：必须 >= 1。")
    args = parser.parse_args()
    validate_common_args(parser, args)
    validate_random_weight_args(parser, args)
    validate_random_generate_duration_arg(parser, args)
    validate_random_resource_floor_args(parser, args)

    if args.clients < 2:
        parser.error("--clients 必须 >= 2")
    if args.commands_per_client < 1:
        parser.error("--commands-per-client 必须 >= 1")
    if args.cases < 0:
        parser.error("--cases 必须 >= 0")

    scenarios: List[Scenario] = []
    for offset in range(args.cases):
        seed = args.seed + offset
        scenario = random_multiclient_scenario(
            seed,
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
        scenario.name = f"random_pressure_seed_{seed}"
        scenario.description = (
            "随机压力场景：大规模多客户端确定性随机 RPC，使用均衡动作配比；"
            f"seed={seed}，客户端={args.clients}，预置每客户端 "
            f"sprite>={args.random_min_sprites_per_client}、"
            f"placement>={args.random_min_placements_per_client}、"
            f"canvas>={args.random_min_canvases_per_client}，预置后每客户端约 "
            f"{args.commands_per_client} 条随机命令，随机 generate 时长约 "
            f"{args.random_generate_duration_seconds:g}s。"
        )
        scenarios.append(scenario)

    def body(implementation_dirs) -> int:
        problems = run_scenario_group(
            "随机压力测试",
            "大规模固定 seed 随机多客户端用例，按默认权重混合覆盖资源管理和并发。",
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
