"""内容交互相关入口：分析视频 / 生成网页 / 评论 / 私信。"""

from __future__ import annotations

from typing import Any

from plugin.sdk.plugin import plugin_entry, Ok, Err, SdkError
from plugin.sdk.shared.core.router import PluginRouter


class ContentRouter(PluginRouter):
    """内容理解与互动。"""

    def __init__(self):
        super().__init__(name="content")

    @plugin_entry(
        id="analyze_video",
        name="分析视频",
        description="分析指定B站视频内容并生成 AI 摘要、标签与评分。",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "B站视频链接或 BV 号"},
                "detailed": {"type": "boolean", "default": False, "description": "是否返回详细分析"},
            },
            "required": ["url"],
        },
        kind="action",
    )
    async def analyze_video(self, url: str, detailed: bool = False, **_) -> Any:
        plugin = self.main_plugin
        analysis = await plugin.brain.analyze_video(url, detailed=detailed)
        return Ok({"success": True, "message": "视频分析完成", "result": analysis.to_dict()})

    @plugin_entry(
        id="video_to_html",
        name="生成视频网页",
        description="将视频内容转换为精美的 HTML PPT 网页。",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "B站视频链接或 BV 号"},
                "style": {"type": "string", "default": "claude", "description": "页面风格"},
            },
            "required": ["url"],
        },
        kind="action",
    )
    async def video_to_html(self, url: str, style: str = "claude", **_) -> Any:
        plugin = self.main_plugin
        res = await plugin.brain.generate_html(url, style=style)
        return Ok({"success": True, "message": "网页生成任务已提交", **res})

    @plugin_entry(
        id="send_comment",
        name="发送评论",
        description="在指定B站视频下发送评论（需启用评论功能）。",
        input_schema={
            "type": "object",
            "properties": {
                "video_id": {"type": "string", "description": "视频 BV 号"},
                "content": {"type": "string", "description": "评论内容"},
            },
            "required": ["video_id", "content"],
        },
        kind="action",
    )
    async def send_comment(self, video_id: str, content: str, **_) -> Any:
        plugin = self.main_plugin
        enabled = await plugin.config.get("bilibili_learning.comment_enabled", True, timeout=5.0)
        if not enabled:
            return Err(SdkError("评论功能已禁用（在配置中开启 comment_enabled）"))
        res = await plugin.brain.send_comment(video_id, content)
        return Ok({"success": True, "message": "评论已发送", **res})

    @plugin_entry(
        id="reply_private",
        name="回复私信",
        description="回复B站用户的私信（需启用私信功能）。",
        input_schema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "用户 UID"},
                "content": {"type": "string", "description": "回复内容"},
            },
            "required": ["user_id", "content"],
        },
        kind="action",
    )
    async def reply_private(self, user_id: str, content: str, **_) -> Any:
        plugin = self.main_plugin
        enabled = await plugin.config.get("bilibili_learning.private_msg_enabled", True, timeout=5.0)
        if not enabled:
            return Err(SdkError("私信功能已禁用（在配置中开启 private_msg_enabled）"))
        res = await plugin.brain.reply_private(user_id, content)
        return Ok({"success": True, "message": "私信已发送", **res})
