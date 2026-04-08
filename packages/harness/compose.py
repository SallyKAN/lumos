"""
Lumos Harness — 显式组合两个 harness 为一个新的独立 harness

以 base 为基础，将 mixin 的资源追加进来。
组合是一次性操作，产出独立 harness。
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# harness 子目录
RESOURCE_DIRS = ["interceptors", "tools", "skills", "prompts", "config"]


def compose_harness(
    base_dir: Path,
    mixin_dir: Path,
    output_dir: Path,
    output_name: Optional[str] = None,
) -> Path:
    """组合两个 harness

    Args:
        base_dir: 基础 harness 目录
        mixin_dir: 混入 harness 目录
        output_dir: 输出目录（会在其下创建子目录）
        output_name: 输出 harness 名称

    Returns:
        输出 harness 的路径
    """
    base_dir = Path(base_dir)
    mixin_dir = Path(mixin_dir)

    # 加载 manifest
    base_manifest = _load_yaml(base_dir / "HARNESS.yaml")
    mixin_manifest = _load_yaml(mixin_dir / "HARNESS.yaml")

    name = output_name or f"{base_manifest.get('name', 'base')}-{mixin_manifest.get('name', 'mixin')}"
    dest = Path(output_dir) / name

    if dest.exists():
        shutil.rmtree(dest)

    # 复制 base 作为基础
    shutil.copytree(base_dir, dest)

    # 合并 mixin 的资源目录
    for dirname in RESOURCE_DIRS:
        mixin_sub = mixin_dir / dirname
        if not mixin_sub.is_dir():
            continue
        dest_sub = dest / dirname
        dest_sub.mkdir(exist_ok=True)
        for item in mixin_sub.iterdir():
            target = dest_sub / item.name
            if item.is_file():
                # mixin 覆盖 base 的同名文件
                shutil.copy2(item, target)
            elif item.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(item, target)

    # 合并 HARNESS.yaml
    merged = _merge_manifests(base_manifest, mixin_manifest, name)
    with (dest / "HARNESS.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(merged, f, default_flow_style=False, allow_unicode=True)

    logger.info(f"Composed harness: {name} = {base_manifest.get('name')} + {mixin_manifest.get('name')}")
    return dest


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _merge_manifests(base: dict, mixin: dict, name: str) -> dict:
    """合并两个 HARNESS.yaml"""
    merged = dict(base)
    merged["name"] = name
    merged["description"] = f"Composed: {base.get('name', '?')} + {mixin.get('name', '?')}"
    merged["version"] = "0.1.0"

    # 合并 provides
    base_provides = base.get("provides", {})
    mixin_provides = mixin.get("provides", {})
    merged_provides = dict(base_provides)

    for key in ["interceptors", "tools", "skills"]:
        base_list = base_provides.get(key, [])
        mixin_list = mixin_provides.get(key, [])
        if base_list or mixin_list:
            merged_provides[key] = list(base_list) + list(mixin_list)

    # prompts: 合并 system_append 列表
    base_prompts = base_provides.get("prompts", {})
    mixin_prompts = mixin_provides.get("prompts", {})
    if base_prompts or mixin_prompts:
        base_append = base_prompts.get("system_append", []) if isinstance(base_prompts, dict) else []
        mixin_append = mixin_prompts.get("system_append", []) if isinstance(mixin_prompts, dict) else []
        if isinstance(base_append, str):
            base_append = [base_append]
        if isinstance(mixin_append, str):
            mixin_append = [mixin_append]
        merged_provides["prompts"] = {"system_append": base_append + mixin_append}

    # config: mixin 覆盖 base（深度合并）
    base_config = base_provides.get("config", {})
    mixin_config = mixin_provides.get("config", {})
    if base_config or mixin_config:
        merged_provides["config"] = _deep_merge(
            base_config if isinstance(base_config, dict) else {},
            mixin_config if isinstance(mixin_config, dict) else {},
        )

    merged["provides"] = merged_provides
    return merged


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个 dict，override 覆盖 base"""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result
