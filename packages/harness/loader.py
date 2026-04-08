"""
Lumos Harness — Harness Package 加载器

从 HARNESS.yaml 加载 interceptors / tools / skills / prompts / config。
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
import sys
from pathlib import Path
from typing import Any, Optional

import yaml

from ..interceptor.base import BaseInterceptor

logger = logging.getLogger(__name__)


class HarnessLoader:
    """从 harness 目录加载资源

    目录结构：
        my-harness/
        ├── HARNESS.yaml
        ├── interceptors/
        ├── tools/
        ├── skills/
        ├── prompts/
        └── config/
    """

    def __init__(self, harness_dir: Path):
        self._root = Path(harness_dir)
        self._manifest = self._load_manifest()

    def _load_manifest(self) -> dict:
        """加载 HARNESS.yaml"""
        p = self._root / "HARNESS.yaml"
        if not p.is_file():
            raise FileNotFoundError(f"HARNESS.yaml not found in {self._root}")
        with p.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    @property
    def name(self) -> str:
        return self._manifest.get("name", self._root.name)

    @property
    def version(self) -> str:
        return self._manifest.get("version", "0.0.0")

    @property
    def description(self) -> str:
        return self._manifest.get("description", "")

    def load_interceptors(self) -> list[BaseInterceptor]:
        """加载所有 interceptor"""
        interceptors = []
        provides = self._manifest.get("provides", {})
        specs = provides.get("interceptors", [])

        for spec in specs:
            if isinstance(spec, str):
                # 简写：文件路径
                path = self._root / "interceptors" / spec
                cls = self._import_class(path, None)
                interceptors.append(cls())
            elif isinstance(spec, dict):
                path = self._root / "interceptors" / spec["file"]
                cls = self._import_class(path, spec.get("class"))
                config = spec.get("config", {})
                interceptors.append(cls(**config))

        return interceptors

    def load_prompts(self) -> str:
        """加载所有 prompt 文件，拼接返回"""
        provides = self._manifest.get("provides", {})
        prompt_spec = provides.get("prompts", {})

        if isinstance(prompt_spec, dict):
            files = prompt_spec.get("system_append", [])
            if isinstance(files, str):
                files = [files]
        elif isinstance(prompt_spec, list):
            files = prompt_spec
        else:
            files = []

        parts = []
        for f in files:
            p = self._root / "prompts" / f
            if p.is_file():
                parts.append(p.read_text(encoding="utf-8"))
        return "\n\n".join(parts)

    def load_config(self) -> dict:
        """加载配置"""
        provides = self._manifest.get("provides", {})
        config_spec = provides.get("config", {})

        if isinstance(config_spec, dict):
            cfg_path = config_spec.get("path")
        elif isinstance(config_spec, str):
            cfg_path = config_spec
        else:
            cfg_path = None

        if cfg_path:
            p = self._root / cfg_path
            if p.is_file():
                with p.open(encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
        return {}

    def load_skill_dirs(self) -> list[Path]:
        """返回 skills 目录路径列表"""
        provides = self._manifest.get("provides", {})
        skills = provides.get("skills", [])
        dirs = []
        for s in skills:
            p = self._root / "skills" / s
            if p.is_dir():
                dirs.append(p)
        return dirs

    def load_tool_paths(self) -> list[Path]:
        """返回 tools 文件路径列表"""
        provides = self._manifest.get("provides", {})
        tools = provides.get("tools", [])
        paths = []
        for t in tools:
            p = self._root / "tools" / t
            if p.is_file():
                paths.append(p)
        return paths

    @property
    def metadata(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "provenance": self._manifest.get("provenance", {}),
        }

    def _import_module(self, path: Path):
        """动态导入 Python 模块"""
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[path.stem] = module
        spec.loader.exec_module(module)
        return module

    def _import_class(self, path: Path, class_name: Optional[str]):
        """动态导入类"""
        module = self._import_module(path)
        if class_name:
            return getattr(module, class_name)
        # 没指定类名：找第一个 BaseInterceptor 子类
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BaseInterceptor) and obj is not BaseInterceptor:
                return obj
        raise ValueError(f"No BaseInterceptor subclass found in {path}")
