"""
Lumos Harness — 单活跃 Harness 管理器

install / use / current / list / uninstall。
同一时刻只有一个 harness 激活。
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

import yaml

from .loader import HarnessLoader

logger = logging.getLogger(__name__)


class HarnessManager:
    """Harness 管理器

    用法:
        mgr = HarnessManager(global_path=Path.home() / ".lumos")
        mgr.install(Path("./my-harness"))
        mgr.use("my-harness")
        print(mgr.current())  # "my-harness"
    """

    def __init__(
        self,
        global_path: Optional[Path] = None,
        project_root: Optional[Path] = None,
    ):
        self._global_path = global_path or Path.home() / ".lumos"
        self._project_root = project_root
        self._packages_dir = self._global_path / "packages"
        self._packages_dir.mkdir(parents=True, exist_ok=True)
        self._config_dir = self._global_path / "config"
        self._config_dir.mkdir(parents=True, exist_ok=True)

    def install(self, source: Path) -> str:
        """安装 harness（复制到 packages 目录）"""
        source = Path(source)
        if not (source / "HARNESS.yaml").is_file():
            raise FileNotFoundError(f"HARNESS.yaml not found in {source}")

        loader = HarnessLoader(source)
        name = loader.name
        dest = self._packages_dir / name

        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source, dest)

        logger.info(f"Installed harness: {name} → {dest}")
        return name

    def uninstall(self, name: str) -> bool:
        """卸载 harness"""
        dest = self._packages_dir / name
        if not dest.exists():
            return False

        # 如果是当前激活的，重置为 default
        if self.current() == name:
            self.use("default")

        shutil.rmtree(dest)
        logger.info(f"Uninstalled harness: {name}")
        return True

    def use(self, name: str) -> None:
        """激活指定 harness"""
        if name != "default":
            dest = self._packages_dir / name
            if not dest.exists():
                raise FileNotFoundError(f"Harness '{name}' not installed")

        config = self._load_global_config()
        config["active_harness"] = name
        self._save_global_config(config)
        logger.info(f"Active harness: {name}")

    def current(self) -> str:
        """返回当前激活的 harness 名称"""
        # 项目级优先
        if self._project_root:
            project_config = self._project_root / ".lumos" / "config.yaml"
            if project_config.is_file():
                try:
                    with project_config.open(encoding="utf-8") as f:
                        cfg = yaml.safe_load(f) or {}
                    if "active_harness" in cfg:
                        return cfg["active_harness"]
                except Exception:
                    pass

        # 全局
        config = self._load_global_config()
        return config.get("active_harness", "default")

    def list_installed(self) -> list[str]:
        """列出已安装的 harness"""
        names = []
        for d in sorted(self._packages_dir.iterdir()):
            if d.is_dir() and (d / "HARNESS.yaml").is_file():
                names.append(d.name)
        return names

    def load_active(self) -> Optional[HarnessLoader]:
        """加载当前激活的 harness，返回 HarnessLoader 或 None"""
        name = self.current()
        if name == "default":
            return None
        dest = self._packages_dir / name
        if not dest.exists():
            logger.warning(f"Active harness '{name}' not found, falling back to default")
            return None
        return HarnessLoader(dest)

    def _load_global_config(self) -> dict:
        p = self._config_dir / "lumos.yaml"
        if p.is_file():
            try:
                with p.open(encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except Exception:
                return {}
        return {}

    def _save_global_config(self, config: dict) -> None:
        p = self._config_dir / "lumos.yaml"
        with p.open("w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, default_flow_style=False)
