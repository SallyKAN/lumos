"""
邮件发送工具

支持两种发送方式:
1. Resend API (推荐，走 HTTPS，不受代理影响)
2. SMTP (备选，支持 QQ邮箱、163邮箱等)

功能:
- 发送纯文本邮件
- 发送 HTML 格式邮件
- 添加附件（支持 Excel、PDF 等）
"""

import os
import ssl
import json
import asyncio
import smtplib
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional, List
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


from ..core.tool import Tool, ToolInfo, Parameters, Param

from ..agents.mode_manager import AgentModeManager, AgentMode


# SMTP 服务器配置
SMTP_SERVERS = {
    "qq": {
        "host": "smtp.qq.com",
        "port": 465,
        "ssl": True,
    },
    "163": {
        "host": "smtp.163.com",
        "port": 465,
        "ssl": True,
    },
    "gmail": {
        "host": "smtp.gmail.com",
        "port": 587,
        "ssl": False,
        "starttls": True,
    },
    "outlook": {
        "host": "smtp.office365.com",
        "port": 587,
        "ssl": False,
        "starttls": True,
    },
}


def detect_smtp_provider(email: str) -> Optional[str]:
    """根据邮箱地址检测 SMTP 服务商"""
    email_lower = email.lower()
    if "@qq.com" in email_lower:
        return "qq"
    elif "@163.com" in email_lower or "@126.com" in email_lower:
        return "163"
    elif "@gmail.com" in email_lower:
        return "gmail"
    elif "@outlook.com" in email_lower or "@hotmail.com" in email_lower:
        return "outlook"
    return None


class SendEmailTool(Tool):
    """发送邮件工具

    优先使用 Resend API，如未配置则使用 SMTP。
    """

    def __init__(
        self,
        mode_manager: Optional[AgentModeManager] = None,
        session_id: Optional[str] = None
    ):
        """初始化工具

        Args:
            mode_manager: 模式管理器
            session_id: 会话 ID
        """
        super().__init__()
        self.mode_manager = mode_manager
        self.session_id = session_id or "default"

        self.name = "send_email"
        self.description = """发送邮件。

使用说明:
- 支持发送纯文本或 HTML 格式邮件
- 优先使用 Resend API（推荐），备选 SMTP
- 仅在 BUILD 模式下可用

环境变量配置（二选一）:

方式1 - Resend API（推荐）:
- RESEND_API_KEY: Resend API 密钥

方式2 - SMTP:
- SMTP_EMAIL: 发件人邮箱地址
- SMTP_PASSWORD: SMTP 授权码

参数:
- to: 收件人邮箱地址（必需）
- subject: 邮件主题（必需）
- body: 邮件正文（必需）
- html: 是否为 HTML 格式（可选，默认 False）
- attachments: 附件文件路径列表（可选）
"""
        self.params = [
            Param(
                name="to",
                description="收件人邮箱地址",
                param_type="string",
                required=True
            ),
            Param(
                name="subject",
                description="邮件主题",
                param_type="string",
                required=True
            ),
            Param(
                name="body",
                description="邮件正文",
                param_type="string",
                required=True
            ),
            Param(
                name="html",
                description="是否为 HTML 格式",
                param_type="boolean",
                required=False,
                default_value=False
            ),
            Param(
                name="attachments",
                description="附件文件路径列表",
                param_type="array",
                required=False
            ),
        ]

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步发送邮件"""
        # 模式检查
        if (self.mode_manager and
                self.mode_manager.get_current_mode() != AgentMode.BUILD):
            mode = self.mode_manager.get_current_mode().value
            return (
                f"错误: send_email 在 {mode} 模式下不可用。"
                f"请切换到 BUILD 模式。"
            )

        # 获取参数
        to_addr = inputs.get("to", "")
        subject = inputs.get("subject", "")
        body = inputs.get("body", "")
        is_html = inputs.get("html", False)
        attachments = inputs.get("attachments", [])

        if not to_addr:
            return "错误: 未指定收件人邮箱"
        if not subject:
            return "错误: 未指定邮件主题"
        if not body:
            return "错误: 未指定邮件正文"

        # 优先使用 Resend API
        resend_api_key = os.environ.get("RESEND_API_KEY", "")
        if resend_api_key:
            return await self._send_via_resend(
                resend_api_key, to_addr, subject, body, is_html, attachments
            )

        # 回退到 SMTP
        from_addr = os.environ.get("SMTP_EMAIL", "")
        password = os.environ.get("SMTP_PASSWORD", "")

        if not from_addr or not password:
            return """错误: 未配置邮件发送方式。请设置环境变量:

方式1 - Resend API（推荐）:
  export RESEND_API_KEY="re_xxx"

方式2 - SMTP:
  export SMTP_EMAIL="你的邮箱"
  export SMTP_PASSWORD="授权码"
"""

        # 检测或获取 SMTP 服务器配置
        smtp_host = os.environ.get("SMTP_HOST", "")
        smtp_port = os.environ.get("SMTP_PORT", "")

        if not smtp_host:
            provider = detect_smtp_provider(from_addr)
            if provider and provider in SMTP_SERVERS:
                smtp_config = SMTP_SERVERS[provider]
                smtp_host = smtp_config["host"]
                smtp_port = smtp_config["port"]
            else:
                return (
                    f"错误: 无法检测邮箱 {from_addr} 的 SMTP 服务器，"
                    f"请设置 SMTP_HOST 环境变量"
                )

        smtp_port = int(smtp_port) if smtp_port else 465

        # 在线程池中执行同步的 SMTP 操作
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            self._send_email_smtp,
            from_addr, password, smtp_host, smtp_port,
            to_addr, subject, body, is_html, attachments
        )
        return result

    async def _send_via_resend(
        self,
        api_key: str,
        to_addr: str,
        subject: str,
        body: str,
        is_html: bool,
        attachments: List[str]
    ) -> str:
        """通过 Resend API 发送邮件"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._send_resend_sync,
            api_key, to_addr, subject, body, is_html, attachments
        )

    def _send_resend_sync(
        self,
        api_key: str,
        to_addr: str,
        subject: str,
        body: str,
        is_html: bool,
        attachments: List[str]
    ) -> str:
        """同步发送 Resend 邮件"""
        try:
            # 构建请求数据
            email_data = {
                "from": "Lumos Assistant <onboarding@resend.dev>",
                "to": [to_addr],
                "subject": subject,
            }

            if is_html:
                email_data["html"] = body
            else:
                email_data["text"] = body

            # 处理附件
            if attachments:
                email_attachments = []
                for file_path in attachments:
                    if not os.path.exists(file_path):
                        return f"错误: 附件文件不存在: {file_path}"

                    with open(file_path, "rb") as f:
                        content = base64.b64encode(f.read()).decode("utf-8")
                        filename = os.path.basename(file_path)
                        email_attachments.append({
                            "filename": filename,
                            "content": content
                        })

                email_data["attachments"] = email_attachments

            # 发送请求
            req = Request(
                "https://api.resend.com/emails",
                data=json.dumps(email_data).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "Lumos/1.0 (Python)"
                },
                method="POST"
            )

            with urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))

            attachment_info = ""
            if attachments:
                attachment_info = f"\n附件: {len(attachments)} 个文件"

            return (
                f"✅ 邮件发送成功！(via Resend)\n"
                f"收件人: {to_addr}\n"
                f"主题: {subject}{attachment_info}"
            )

        except HTTPError as e:
            error_body = e.read().decode("utf-8")
            error_data = json.loads(error_body) if error_body else {}
            error_msg = error_data.get("message", error_body)
            
            # 如果是测试模式限制，返回友好提示
            if "testing emails" in error_msg.lower() or "verify a domain" in error_msg.lower():
                registered_email = os.environ.get("RESEND_REGISTERED_EMAIL", "snapekang@gmail.com")
                return (
                    f"⚠️ Resend 测试模式限制：只能发送到注册邮箱 {registered_email}\n"
                    f"当前收件人: {to_addr}\n\n"
                    f"解决方案：\n"
                    f"1. 在 https://resend.com/domains 验证域名后即可发送到任意邮箱\n"
                    f"2. 或配置 SMTP 环境变量使用传统方式发送"
                )
            
            return f"错误: Resend API 请求失败 - {e.code}: {error_msg}"
        except URLError as e:
            return f"错误: 网络请求失败 - {str(e.reason)}"
        except Exception as e:
            return f"错误: 邮件发送失败 - {str(e)}"

    def _send_email_smtp(
        self,
        from_addr: str,
        password: str,
        smtp_host: str,
        smtp_port: int,
        to_addr: str,
        subject: str,
        body: str,
        is_html: bool,
        attachments: List[str]
    ) -> str:
        """通过 SMTP 发送邮件"""
        # 临时清除代理环境变量，避免 SMTP 连接被代理拦截
        proxy_vars = [
            'http_proxy', 'https_proxy', 'all_proxy',
            'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY'
        ]
        saved_proxies = {}
        for var in proxy_vars:
            if var in os.environ:
                saved_proxies[var] = os.environ.pop(var)

        try:
            # 创建邮件
            msg = MIMEMultipart()
            msg.attach(
                MIMEText(body, "html" if is_html else "plain", "utf-8")
            )

            msg["From"] = from_addr
            msg["To"] = to_addr
            msg["Subject"] = subject

            # 添加附件
            for file_path in attachments:
                if not os.path.exists(file_path):
                    return f"错误: 附件文件不存在: {file_path}"

                with open(file_path, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                    encoders.encode_base64(part)

                    filename = os.path.basename(file_path)
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename={filename}"
                    )
                    msg.attach(part)

            # 发送邮件
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

            server = smtplib.SMTP_SSL(
                smtp_host, smtp_port, timeout=30, context=context
            )
            server.set_debuglevel(0)
            server.login(from_addr, password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
            server.quit()

            attachment_info = ""
            if attachments:
                attachment_info = f"\n附件: {len(attachments)} 个文件"

            return (
                f"✅ 邮件发送成功！(via SMTP)\n"
                f"收件人: {to_addr}\n"
                f"主题: {subject}{attachment_info}"
            )

        except smtplib.SMTPAuthenticationError:
            return "错误: SMTP 认证失败，请检查邮箱地址和授权码是否正确"
        except smtplib.SMTPException as e:
            return f"错误: SMTP 发送失败 - {str(e)}"
        except Exception as e:
            return f"错误: 邮件发送失败 - {str(e)}"
        finally:
            # 恢复代理环境变量
            for var, value in saved_proxies.items():
                os.environ[var] = value

    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "to": {
                        "type": "string",
                        "description": "收件人邮箱地址"
                    },
                    "subject": {
                        "type": "string",
                        "description": "邮件主题"
                    },
                    "body": {
                        "type": "string",
                        "description": "邮件正文"
                    },
                    "html": {
                        "type": "boolean",
                        "description": "是否为 HTML 格式"
                    },
                    "attachments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "附件文件路径列表"
                    }
                },
                required=["to", "subject", "body"]
            )
        )


# ==================== 工具工厂 ====================

def create_email_tool(
    mode_manager: Optional[AgentModeManager] = None,
    session_id: Optional[str] = None
) -> SendEmailTool:
    """创建邮件发送工具

    Args:
        mode_manager: 模式管理器
        session_id: 会话 ID

    Returns:
        SendEmailTool 实例
    """
    return SendEmailTool(mode_manager, session_id)
