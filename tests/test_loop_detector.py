"""T1.8 测试：WriteRmLoopDetector"""

import pytest
from packages.server.core.types import TextContent
from packages.server.interceptor.types import ToolRequest, ToolResult
from packages.server.interceptor.builtins.loop_detector import WriteRmLoopDetector, WARNING_MESSAGE


def _make_result(tool_name: str, arguments: dict | None = None) -> ToolResult:
    req = ToolRequest(
        tool_call_id="tc1",
        tool_name=tool_name,
        arguments=arguments or {},
    )
    return ToolResult(
        tool_call_id="tc1",
        tool_name=tool_name,
        content=[TextContent(text="ok")],
        request=req,
    )


async def _passthrough(r):
    return r


class TestWriteRmLoopDetector:
    @pytest.mark.asyncio
    async def test_no_loop_no_warning(self):
        d = WriteRmLoopDetector()
        result = _make_result("read_file", {"path": "/tmp/a"})
        out = await d.post_tool_use(result, _passthrough)
        assert len(out.content) == 1  # 只有原始 "ok"

    @pytest.mark.asyncio
    async def test_write_rm_loop_detected(self):
        d = WriteRmLoopDetector(threshold=2)

        # 模拟 write → rm → write → rm 循环
        calls = [
            ("write_file", {"file_path": "/tmp/test.py"}),
            ("bash", {"command": "rm /tmp/test.py"}),
            ("write_file", {"file_path": "/tmp/test.py"}),
            ("bash", {"command": "rm /tmp/test.py"}),
        ]

        out = None
        for tool_name, args in calls:
            result = _make_result(tool_name, args)
            out = await d.post_tool_use(result, _passthrough)

        # 最后一次应该包含警告
        texts = [b.text for b in out.content if isinstance(b, TextContent)]
        combined = "".join(texts)
        assert "write_file → rm 循环模式" in combined

    @pytest.mark.asyncio
    async def test_threshold_configurable(self):
        d = WriteRmLoopDetector(threshold=3)

        # 只有 2 次 write-rm，threshold=3 不触发
        calls = [
            ("write_file", {"file_path": "/tmp/a.py"}),
            ("bash", {"command": "rm /tmp/a.py"}),
            ("write_file", {"file_path": "/tmp/a.py"}),
            ("bash", {"command": "rm /tmp/a.py"}),
        ]

        out = None
        for tool_name, args in calls:
            result = _make_result(tool_name, args)
            out = await d.post_tool_use(result, _passthrough)

        assert len(out.content) == 1  # 没有警告

    @pytest.mark.asyncio
    async def test_warning_only_once(self):
        d = WriteRmLoopDetector(threshold=2)

        calls = [
            ("write_file", {"file_path": "/tmp/a.py"}),
            ("bash", {"command": "rm /tmp/a.py"}),
            ("write_file", {"file_path": "/tmp/a.py"}),
            ("bash", {"command": "rm /tmp/a.py"}),
            # 继续循环
            ("write_file", {"file_path": "/tmp/a.py"}),
            ("bash", {"command": "rm /tmp/a.py"}),
        ]

        warning_count = 0
        for tool_name, args in calls:
            result = _make_result(tool_name, args)
            out = await d.post_tool_use(result, _passthrough)
            texts = "".join(b.text for b in out.content if isinstance(b, TextContent))
            if "write_file → rm 循环模式" in texts:
                warning_count += 1

        assert warning_count == 1

    @pytest.mark.asyncio
    async def test_history_sliding_window(self):
        d = WriteRmLoopDetector(threshold=2, history_max=10)

        # 填充 15 条无关记录，把 write-rm 挤出窗口
        for i in range(15):
            result = _make_result("read_file", {"path": f"/tmp/{i}"})
            await d.post_tool_use(result, _passthrough)

        assert len(d._history) <= 30  # 不超过 sliding window

    @pytest.mark.asyncio
    async def test_reset(self):
        d = WriteRmLoopDetector(threshold=2)

        calls = [
            ("write_file", {"file_path": "/tmp/a.py"}),
            ("bash", {"command": "rm /tmp/a.py"}),
            ("write_file", {"file_path": "/tmp/a.py"}),
            ("bash", {"command": "rm /tmp/a.py"}),
        ]
        for tool_name, args in calls:
            result = _make_result(tool_name, args)
            await d.post_tool_use(result, _passthrough)

        assert d._warned is True

        d.reset()
        assert d._warned is False
        assert len(d._history) == 0
