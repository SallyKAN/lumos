"""
Lumos Capability — 项目扫描器

自动检测项目语言、框架、构建命令、测试命令。
用于 `lumos init` 生成 LUMOS.md 模板。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ProjectInfo:
    """项目信息"""
    language: str = "unknown"
    framework: str = ""
    build_cmd: str = ""
    test_cmd: str = ""
    lint_cmd: str = ""
    package_manager: str = ""
    detected_files: list[str] = field(default_factory=list)


# 检测规则：(文件名, 语言, 框架, 包管理器, 构建命令, 测试命令)
DETECTION_RULES = [
    ("Cargo.toml", "rust", "", "cargo", "cargo build", "cargo test"),
    ("pyproject.toml", "python", "", "pip", "", "pytest"),
    ("setup.py", "python", "", "pip", "python setup.py build", "pytest"),
    ("package.json", "javascript", "", "npm", "npm run build", "npm test"),
    ("go.mod", "go", "", "go", "go build ./...", "go test ./..."),
    ("pom.xml", "java", "maven", "maven", "mvn package", "mvn test"),
    ("build.gradle", "java", "gradle", "gradle", "gradle build", "gradle test"),
    ("Gemfile", "ruby", "", "bundler", "", "bundle exec rspec"),
    ("mix.exs", "elixir", "", "mix", "mix compile", "mix test"),
]

# 框架检测（在 package.json 的 dependencies 中搜索）
JS_FRAMEWORKS = {
    "next": "nextjs",
    "react": "react",
    "vue": "vue",
    "svelte": "svelte",
    "express": "express",
    "fastify": "fastify",
}

# Python 框架检测（在 pyproject.toml 的 dependencies 中搜索）
PY_FRAMEWORKS = {
    "django": "django",
    "flask": "flask",
    "fastapi": "fastapi",
    "streamlit": "streamlit",
}


class ProjectScanner:
    """项目扫描器"""

    def __init__(self, project_root: Path):
        self._root = project_root

    def scan(self) -> ProjectInfo:
        """扫描项目，返回检测到的信息"""
        info = ProjectInfo()

        for filename, lang, framework, pkg_mgr, build, test in DETECTION_RULES:
            p = self._root / filename
            if p.is_file():
                info.language = lang
                info.framework = framework or info.framework
                info.package_manager = pkg_mgr
                info.build_cmd = build
                info.test_cmd = test
                info.detected_files.append(filename)
                break  # 用第一个匹配的

        # 细化框架检测
        if info.language == "python":
            info.framework = self._detect_python_framework() or info.framework
            # 检查是否有 pytest 配置
            if (self._root / "pytest.ini").is_file() or (self._root / "pyproject.toml").is_file():
                info.test_cmd = "pytest"
        elif info.language == "javascript":
            info.framework = self._detect_js_framework() or info.framework

        return info

    def _detect_python_framework(self) -> Optional[str]:
        """从 pyproject.toml 或 requirements.txt 检测 Python 框架"""
        for fname in ["pyproject.toml", "requirements.txt"]:
            p = self._root / fname
            if p.is_file():
                try:
                    content = p.read_text(encoding="utf-8").lower()
                    for key, framework in PY_FRAMEWORKS.items():
                        if key in content:
                            return framework
                except Exception:
                    pass
        return None

    def _detect_js_framework(self) -> Optional[str]:
        """从 package.json 检测 JS 框架"""
        p = self._root / "package.json"
        if p.is_file():
            try:
                content = p.read_text(encoding="utf-8").lower()
                for key, framework in JS_FRAMEWORKS.items():
                    if f'"{key}"' in content:
                        return framework
            except Exception:
                pass
        return None
