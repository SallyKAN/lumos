"""
Lumos Capability — System Prompt 动态组装器

9 层分层组装，按优先级压缩。替代 LumosAgent.DEFAULT_SYSTEM_PROMPT。

层级（优先级从高到低）：
L1: 核心身份 (IDENTITY.md)              [不可压缩]
L2: 行为规范 (AGENT.md + 内置规则)      [不可压缩]
L3: 用户信息 (USER.md)                 [不可压缩]
L4: 项目指令 (LUMOS.md)                [可轻压缩]
L5: Harness Package prompts            [可压缩]
L6: 活跃 Skill prompt                  [可压缩]
L7: 模式提示 (BUILD/PLAN/REVIEW)       [可压缩]
L8: 活跃记忆 (active_insights.md)      [可压缩]
L9: 运行时上下文                        [动态]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 默认 token 预算：system prompt 不超过此值
DEFAULT_TOKEN_BUDGET = 16000


@dataclass
class PromptSection:
    """System prompt 的一个段落"""
    name: str
    content: str
    priority: int  # 1-9, 1 最高
    compressible: bool = True
    source: str = ""
    token_estimate: int = 0

    def __post_init__(self):
        if self.token_estimate == 0:
            self.token_estimate = len(self.content) // 4

    def to_prompt(self) -> str:
        if not self.content.strip():
            return ""
        return f"=== {self.name.upper()} ===\n\n{self.content.strip()}\n"


class PromptComposer:
    """System prompt 动态组装器

    职责：
    1. 从 WorkspaceLoader 加载 workspace 文件
    2. 加载 Harness Package 的 prompts
    3. 加载活跃 Skill 的 prompt
    4. 加载活跃记忆
    5. 注入运行时上下文
    6. 按优先级分层组装，控制总 token 量
    """

    def __init__(
        self,
        workspace_loader: Optional[Any] = None,
        harness_prompts: Optional[list[str]] = None,
        skill_prompt: Optional[str] = None,
        mode_prompt: Optional[str] = None,
        active_insights: Optional[str] = None,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        fallback_prompt: Optional[str] = None,
    ):
        self._workspace_loader = workspace_loader
        self._harness_prompts = harness_prompts or []
        self._skill_prompt = skill_prompt
        self._mode_prompt = mode_prompt
        self._active_insights = active_insights
        self._token_budget = token_budget
        self._fallback_prompt = fallback_prompt

    def compose(self, runtime_context: Optional[dict] = None) -> str:
        """组装完整的 system prompt"""
        sections = self._collect_sections(runtime_context or {})

        if not any(s.content.strip() for s in sections):
            # 没有任何 workspace 文件 → 退回 fallback
            if self._fallback_prompt:
                return self._fallback_prompt
            return ""

        sections = self._compress_if_needed(sections)
        return self._assemble(sections)

    def _collect_sections(self, runtime_context: dict) -> list[PromptSection]:
        """收集所有 9 层 section"""
        sections: list[PromptSection] = []

        # L1: 核心身份
        identity = self._load_workspace_file("IDENTITY.md")
        sections.append(PromptSection(
            name="Identity", content=identity or "", priority=1,
            compressible=False, source="IDENTITY.md",
        ))

        # L2: 行为规范
        agent_rules = self._load_workspace_file("AGENT.md")
        sections.append(PromptSection(
            name="Agent Rules", content=agent_rules or "", priority=2,
            compressible=False, source="AGENT.md",
        ))

        # L3: 用户信息
        user_info = self._load_workspace_file("USER.md")
        sections.append(PromptSection(
            name="User", content=user_info or "", priority=3,
            compressible=False, source="USER.md",
        ))

        # L4: 项目指令
        project = self._load_workspace_file("LUMOS.md")
        sections.append(PromptSection(
            name="Project Instructions", content=project or "", priority=4,
            compressible=True, source="LUMOS.md",
        ))

        # L5: Harness Package prompts
        harness_content = "\n\n".join(p for p in self._harness_prompts if p.strip())
        sections.append(PromptSection(
            name="Harness", content=harness_content, priority=5,
            compressible=True, source="harness/prompts",
        ))

        # L6: 活跃 Skill prompt
        sections.append(PromptSection(
            name="Skill", content=self._skill_prompt or "", priority=6,
            compressible=True, source="skill",
        ))

        # L7: 模式提示
        sections.append(PromptSection(
            name="Mode", content=self._mode_prompt or "", priority=7,
            compressible=True, source="mode",
        ))

        # L8: 活跃记忆
        sections.append(PromptSection(
            name="Self-Wisdom", content=self._active_insights or "", priority=8,
            compressible=True, source="active_insights.md",
        ))

        # L9: 运行时上下文
        runtime_str = self._format_runtime(runtime_context)
        sections.append(PromptSection(
            name="Runtime", content=runtime_str, priority=9,
            compressible=False, source="runtime",
        ))

        return sections

    def _load_workspace_file(self, filename: str) -> Optional[str]:
        """从 WorkspaceLoader 加载文件"""
        if self._workspace_loader is None:
            return None
        return self._workspace_loader.load_file(filename)

    def _format_runtime(self, context: dict) -> str:
        """格式化运行时上下文"""
        if not context:
            return ""
        lines = []
        for k, v in context.items():
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    def _compress_if_needed(self, sections: list[PromptSection]) -> list[PromptSection]:
        """如果总 token 超预算，从 L8→L5 依次压缩"""
        total = sum(s.token_estimate for s in sections)
        if total <= self._token_budget:
            return sections

        # 按优先级从低到高压缩（L8 → L5）
        compressible = sorted(
            [s for s in sections if s.compressible and s.content.strip()],
            key=lambda s: -s.priority,  # L8 先压缩
        )

        for section in compressible:
            if total <= self._token_budget:
                break
            overflow = total - self._token_budget
            # 按比例截断
            chars_to_cut = overflow * 4  # token → chars 近似
            if chars_to_cut >= len(section.content):
                # 整段删除
                total -= section.token_estimate
                section.content = ""
                section.token_estimate = 0
            else:
                # 截断保留前面部分
                new_len = len(section.content) - chars_to_cut
                section.content = section.content[:int(new_len)] + "\n\n[... truncated ...]"
                section.token_estimate = len(section.content) // 4
                total = sum(s.token_estimate for s in sections)

        return sections

    def _assemble(self, sections: list[PromptSection]) -> str:
        """组装最终 prompt"""
        parts = []
        for s in sorted(sections, key=lambda s: s.priority):
            rendered = s.to_prompt()
            if rendered:
                parts.append(rendered)
        return "\n".join(parts)
