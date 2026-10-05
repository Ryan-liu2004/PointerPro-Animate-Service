#!/usr/bin/env python3
"""
拆分后各个对拍入口共用的辅助函数。

说明：
这里不写具体测试场景，只负责准备各份实现、编译、运行场景并打印结果。
固定场景、随机测试、压力测试、随机压力测试分别放在独立入口文件里。
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from diff_against_hai import (
    DEFAULT_BUILD_TIMEOUT,
    DEFAULT_IMPLEMENTATIONS,
    DEFAULT_MEMCHECK,
    DEFAULT_RANDOM_BARRIER_WEIGHT,
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
    DEFAULT_RANDOM_SEED,
    DEFAULT_RANDOM_SET_ANIMATION_WEIGHT,
    DEFAULT_RANDOM_SHARE_WEIGHT,
    DEFAULT_THREADS,
    DEFAULT_TIMEOUT,
    BuildFailure,
    IMPLEMENTATION_NAMES,
    ImplementationDirs,
    Scenario,
    build_tree,
    copy_implementation_tree,
    parse_implementation_names,
    print_artifact_locations,
    print_case_header,
    print_group_header,
    report_case_result,
    run_one_scenario,
    run_pressure_pair,
)


def add_common_args(parser: argparse.ArgumentParser) -> None:
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
    parser.add_argument("--keep-temp", action="store_true",
                        help="保留临时编译目录；限制：开关参数。")
    parser.add_argument("--verbose", action="store_true",
                        help="打印详细收发日志；限制：开关参数。")
    parser.add_argument("--no-memcheck", dest="memcheck",
                        action="store_false", default=DEFAULT_MEMCHECK,
                        help=("关闭 sanitizer 内存检查；限制：开关参数，默认开启。"
                              "开启时只对 student 临时副本用 ASan/LSan 编译并扫描"
                              "内存错误/泄漏日志；死锁由每条响应的 timeout 判定。"))


def add_seed_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED,
                        help="随机种子；限制：整数，相同 seed 生成同样用例。")


def add_random_weight_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--random-create-weight", type=int,
                        default=DEFAULT_RANDOM_CREATE_WEIGHT,
                        help=("create_canvas/create_sprite/create_rectangle/"
                              "create_circle 合并动作权重；限制：必须 >= 0。"
                              "0 表示禁用所有 create 类随机动作。"))
    parser.add_argument("--random-place-sprite-weight", type=int,
                        default=DEFAULT_RANDOM_PLACE_SPRITE_WEIGHT,
                        help=("place_sprite 动作权重；限制：必须 >= 0。0 表示禁用；"
                              "值越大越常把已创建 sprite 放到可访问 canvas 上。"))
    parser.add_argument("--random-placement-weight", type=int,
                        default=DEFAULT_RANDOM_PLACEMENT_WEIGHT,
                        help=("placement_up/down/top/bottom 合并动作权重；限制："
                              "必须 >= 0。0 表示禁用四种层级移动随机动作。"))
    parser.add_argument("--random-set-animation-weight", type=int,
                        default=DEFAULT_RANDOM_SET_ANIMATION_WEIGHT,
                        help=("set_animation_params 动作权重；限制：必须 >= 0。"
                              "0 表示禁用动画参数随机动作。"))
    parser.add_argument("--random-destroy-canvas-weight", type=int,
                        default=DEFAULT_RANDOM_DESTROY_CANVAS_WEIGHT,
                        help=("destroy_canvas 动作权重；限制：必须 >= 0。0 表示禁用。"))
    parser.add_argument("--random-destroy-sprite-weight", type=int,
                        default=DEFAULT_RANDOM_DESTROY_SPRITE_WEIGHT,
                        help=("destroy_sprite 动作权重；限制：必须 >= 0。0 表示禁用。"))
    parser.add_argument("--random-destroy-placement-weight", type=int,
                        default=DEFAULT_RANDOM_DESTROY_PLACEMENT_WEIGHT,
                        help=("destroy_placement 动作权重；限制：必须 >= 0。0 表示禁用。"))
    parser.add_argument("--random-barrier-weight", type=int,
                        default=DEFAULT_RANDOM_BARRIER_WEIGHT,
                        help=("barrier 动作权重；限制：必须 >= 0。0 表示禁用；"
                              "值越大，随机生成器越常选择 barrier。实际概率约为"
                              "该权重除以所有动作权重总和。"))
    parser.add_argument("--random-generate-weight", type=int,
                        default=DEFAULT_RANDOM_GENERATE_WEIGHT,
                        help=("generate 动作权重；限制：必须 >= 0。0 表示禁用；"
                              "值越大越常生成视频导出相关命令，可能明显增加运行时间。"))
    parser.add_argument("--random-share-weight", type=int,
                        default=DEFAULT_RANDOM_SHARE_WEIGHT,
                        help=("share_canvas 动作权重；限制：必须 >= 0。0 表示禁用；"
                              "值越大越常生成共享/请求共享场景，会影响 barrier 参与者数量。"))
    parser.add_argument("--random-invalid-weight", type=int,
                        default=DEFAULT_RANDOM_INVALID_WEIGHT,
                        help=("非法参数/越权动作权重；限制：必须 >= 0。0 表示禁用；"
                              "值越大越常生成越界数字、坏 handle、越权销毁等失败场景。"))
    parser.add_argument("--random-disconnect-weight", type=int,
                        default=DEFAULT_RANDOM_DISCONNECT_WEIGHT,
                        help=("断连/重连动作权重；限制：必须 >= 0。0 表示禁用；"
                              "值越大越常生成 Disconnect 和同名重新登录场景。"))


def add_random_resource_floor_args(
    parser: argparse.ArgumentParser,
    min_sprites_per_client: int = DEFAULT_RANDOM_MIN_SPRITES_PER_CLIENT,
    min_placements_per_client: int = DEFAULT_RANDOM_MIN_PLACEMENTS_PER_CLIENT,
    min_canvases_per_client: int = DEFAULT_RANDOM_MIN_CANVASES_PER_CLIENT,
) -> None:
    parser.add_argument("--random-min-sprites-per-client", type=int,
                        default=min_sprites_per_client,
                        help=("随机多客户端测试预置资源：每个客户端至少拥有的 "
                              "sprite 数；限制：必须 >= 0。"))
    parser.add_argument("--random-min-placements-per-client", type=int,
                        default=min_placements_per_client,
                        help=("随机多客户端测试预置资源：每个客户端至少创建的 "
                              "placement 数；限制：必须 >= 0。"))
    parser.add_argument("--random-min-canvases-per-client", type=int,
                        default=min_canvases_per_client,
                        help=("随机多客户端测试预置资源：每个客户端至少可访问的 "
                              "canvas 数；限制：必须 >= 0。"))


def add_random_generate_duration_arg(
    parser: argparse.ArgumentParser,
    duration_seconds: float = DEFAULT_RANDOM_GENERATE_DURATION_SECONDS,
) -> None:
    parser.add_argument("--random-generate-duration-seconds", type=float,
                        default=duration_seconds,
                        help=("随机测试中有效 generate 命令的视频时长秒数；"
                              "限制：必须 > 0。"))


def validate_common_args(parser: argparse.ArgumentParser,
                         args: argparse.Namespace) -> None:
    if args.threads < 1:
        parser.error("--threads 必须 >= 1")
    if args.timeout <= 0:
        parser.error("--timeout 必须 > 0")
    if args.build_timeout <= 0:
        parser.error("--build-timeout 必须 > 0")
    try:
        args.selected_implementations = parse_implementation_names(
            args.implementations
        )
    except ValueError as exc:
        parser.error(str(exc))


def validate_random_weight_args(parser: argparse.ArgumentParser,
                                args: argparse.Namespace) -> None:
    if args.random_create_weight < 0:
        parser.error("--random-create-weight 必须 >= 0")
    if args.random_place_sprite_weight < 0:
        parser.error("--random-place-sprite-weight 必须 >= 0")
    if args.random_placement_weight < 0:
        parser.error("--random-placement-weight 必须 >= 0")
    if args.random_set_animation_weight < 0:
        parser.error("--random-set-animation-weight 必须 >= 0")
    if args.random_destroy_canvas_weight < 0:
        parser.error("--random-destroy-canvas-weight 必须 >= 0")
    if args.random_destroy_sprite_weight < 0:
        parser.error("--random-destroy-sprite-weight 必须 >= 0")
    if args.random_destroy_placement_weight < 0:
        parser.error("--random-destroy-placement-weight 必须 >= 0")
    if args.random_barrier_weight < 0:
        parser.error("--random-barrier-weight 必须 >= 0")
    if args.random_generate_weight < 0:
        parser.error("--random-generate-weight 必须 >= 0")
    if args.random_share_weight < 0:
        parser.error("--random-share-weight 必须 >= 0")
    if args.random_invalid_weight < 0:
        parser.error("--random-invalid-weight 必须 >= 0")
    if args.random_disconnect_weight < 0:
        parser.error("--random-disconnect-weight 必须 >= 0")
    total_weight = (
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
    if total_weight <= 0:
        parser.error("所有 random 权重总和必须 > 0")


def validate_random_resource_floor_args(parser: argparse.ArgumentParser,
                                        args: argparse.Namespace) -> None:
    if args.random_min_sprites_per_client < 0:
        parser.error("--random-min-sprites-per-client 必须 >= 0")
    if args.random_min_placements_per_client < 0:
        parser.error("--random-min-placements-per-client 必须 >= 0")
    if args.random_min_canvases_per_client < 0:
        parser.error("--random-min-canvases-per-client 必须 >= 0")


def validate_random_generate_duration_arg(parser: argparse.ArgumentParser,
                                          args: argparse.Namespace) -> None:
    if args.random_generate_duration_seconds <= 0:
        parser.error("--random-generate-duration-seconds 必须 > 0")


def run_with_environment(
    generated_clients: int,
    build_timeout: float,
    keep_temp: bool,
    memcheck: bool,
    body: Callable[[ImplementationDirs], int],
    implementations: Optional[Iterable[str]] = None,
) -> int:
    temp_context = tempfile.TemporaryDirectory(prefix="p2_diff_")
    temp_root = Path(temp_context.name)
    if keep_temp:
        temp_context.cleanup = lambda: None  # 类型检查器不理解这里替换 cleanup。

    selected_implementations = tuple(implementations or IMPLEMENTATION_NAMES)
    implementation_dirs: ImplementationDirs = {
        name: temp_root / name for name in selected_implementations
    }
    try:
        for implementation_name, directory in implementation_dirs.items():
            copy_implementation_tree(
                implementation_name, directory, generated_clients
            )
        for implementation_name, directory in implementation_dirs.items():
            build_tree(
                implementation_name,
                directory,
                build_timeout,
                sanitize=memcheck and implementation_name == "student",
            )
        exit_code = body(implementation_dirs)
        if keep_temp:
            print(f"已保留临时编译目录: {temp_root}")
        print_artifact_locations()
        return exit_code
    except BuildFailure as exc:
        print(exc, file=sys.stderr)
        if keep_temp:
            print(f"已保留临时编译目录: {temp_root}", file=sys.stderr)
        print_artifact_locations()
        return 2
    finally:
        if not keep_temp:
            temp_context.cleanup()


def run_scenario_group(
    title: str,
    description: str,
    scenarios: List[Scenario],
    implementation_dirs: ImplementationDirs,
    threads: int,
    timeout: float,
    verbose: bool,
    memory_check: bool,
) -> List[str]:
    all_problems: List[str] = []
    print_group_header(title, description)
    for scenario in scenarios:
        print_case_header(scenario.name, scenario.description)
        problems = run_one_scenario(
            scenario, implementation_dirs, threads, timeout, verbose,
            memory_check
        )
        report_case_result(problems, all_problems)
    return all_problems


def run_one_pressure_case(
    name: str,
    description: str,
    pressure_func,
    implementation_dirs: ImplementationDirs,
    threads: int,
    client_count: int,
    timeout: float,
    verbose: bool,
    rounds: Optional[int] = None,
    memory_check: bool = False,
) -> List[str]:
    all_problems: List[str] = []
    print_case_header(name, description)
    problems = run_pressure_pair(
        name,
        pressure_func,
        implementation_dirs,
        threads,
        client_count,
        timeout,
        verbose,
        rounds=rounds,
        memory_check=memory_check,
    )
    report_case_result(problems, all_problems)
    return all_problems
