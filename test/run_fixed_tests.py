#!/usr/bin/env python3
"""
固定场景对拍入口。

中文场景注释：
这些用例是手写、确定性的基础回归测试，主要覆盖登录、RPC 正常返回、
错误返回码、画布共享和 barrier 释放。
"""

from __future__ import annotations

import argparse

from diff_against_hai import scripted_scenarios
from diff_runner_common import (
    add_common_args,
    run_scenario_group,
    run_with_environment,
    validate_common_args,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="运行固定场景对拍测试。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_common_args(parser)
    args = parser.parse_args()
    validate_common_args(parser, args)

    def body(implementation_dirs) -> int:
        problems = run_scenario_group(
            "固定场景",
            "手写确定性用例：基础 RPC、失败返回码、共享和 barrier。",
            scripted_scenarios(),
            implementation_dirs,
            args.threads,
            args.timeout,
            args.verbose,
            args.memcheck,
        )
        return 1 if problems else 0

    return run_with_environment(
        generated_clients=0,
        build_timeout=args.build_timeout,
        keep_temp=args.keep_temp,
        memcheck=args.memcheck,
        body=body,
        implementations=args.selected_implementations,
    )


if __name__ == "__main__":
    raise SystemExit(main())
