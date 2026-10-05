#!/usr/bin/env python3
"""
压力测试对拍入口。

中文场景注释：
压力测试分两类：独立资源压力检查普通多客户端并发；barrier 压力检查
客户端数大于线程数时，barrier 等待不会永久占满工作线程。
"""

from __future__ import annotations

import argparse
from typing import List

from diff_against_hai import (
    DEFAULT_STRESS_CLIENTS,
    DEFAULT_STRESS_ROUNDS,
    run_barrier_disconnect_pressure_on_server,
    run_barrier_pressure_on_server,
    run_independent_pressure_on_server,
    run_share_disconnect_pressure_on_server,
)
from diff_runner_common import (
    add_common_args,
    print_group_header,
    run_one_pressure_case,
    run_with_environment,
    validate_common_args,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="运行压力对拍测试。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_common_args(parser)
    parser.add_argument("--clients", type=int, default=DEFAULT_STRESS_CLIENTS,
                        help="压力测试客户端数；限制：必须 >= 2。")
    parser.add_argument("--rounds", type=int, default=DEFAULT_STRESS_ROUNDS,
                        help="独立资源压力每客户端轮数；限制：必须 >= 1。")
    parser.add_argument(
        "--skip-barrier",
        action="store_true",
        help="跳过 barrier 压力，只跑独立资源压力；限制：开关参数。",
    )
    parser.add_argument(
        "--skip-extreme",
        action="store_true",
        help="跳过极端竞态压力；限制：开关参数。",
    )
    args = parser.parse_args()
    validate_common_args(parser, args)

    if args.clients < 2:
        parser.error("--clients 必须 >= 2")
    if args.rounds < 1:
        parser.error("--rounds 必须 >= 1")

    def body(implementation_dirs) -> int:
        all_problems: List[str] = []
        print_group_header(
            "压力测试",
            "多客户端高并发对拍；默认同时包含独立资源压力和 barrier 压力。",
        )
        all_problems.extend(
            run_one_pressure_case(
                "pressure_independent",
                "压力场景：每个客户端独立创建、放置、移动、销毁资源。",
                run_independent_pressure_on_server,
                implementation_dirs,
                args.threads,
                args.clients,
                args.timeout,
                args.verbose,
                rounds=args.rounds,
                memory_check=args.memcheck,
            )
        )
        if not args.skip_barrier:
            all_problems.extend(
                run_one_pressure_case(
                    "pressure_barrier_underprovisioned",
                    "压力场景：客户端数大于工作线程数时，所有参与者同时等待 barrier。",
                    run_barrier_pressure_on_server,
                    implementation_dirs,
                    args.threads,
                    args.clients,
                    args.timeout,
                    args.verbose,
                    memory_check=args.memcheck,
                )
            )
        if not args.skip_extreme:
            all_problems.extend(
                run_one_pressure_case(
                    "pressure_barrier_disconnect",
                    "极端压力：多个 pair 中，一个 barrier 等待者断连，另一个在线参与者必须释放。",
                    run_barrier_disconnect_pressure_on_server,
                    implementation_dirs,
                    args.threads,
                    args.clients,
                    args.timeout,
                    args.verbose,
                    memory_check=args.memcheck,
                )
            )
            all_problems.extend(
                run_one_pressure_case(
                    "pressure_share_disconnect_race",
                    "极端压力：大量 share_canvas 与目标用户 Disconnect 交错，检查资源列表并发访问。",
                    run_share_disconnect_pressure_on_server,
                    implementation_dirs,
                    args.threads,
                    args.clients,
                    args.timeout,
                    args.verbose,
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
