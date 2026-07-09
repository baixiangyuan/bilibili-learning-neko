"""学习生命周期控制相关入口。"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from plugin.sdk.plugin import plugin_entry, Ok, Err, SdkError
from plugin.sdk.shared.core.router import PluginRouter


class LearningRouter(PluginRouter):
    """学习控制：启动 / 停止 / 状态 / Web 面板 / 兴趣管理。"""

    def __init__(self):
        super().__init__(name="learning")

    # ------------------------------------------------------------------
    # 启动 / 停止
    # ------------------------------------------------------------------

    @plugin_entry(
        id="start_learning",
        name="启动AI学习",
        description="启动B站AI自动学习循环：刷推荐流、理解视频、评论互动、知识沉淀。",
        kind="action",
    )
    async def start_learning(self, **_) -> Any:
        plugin = self.main_plugin
        if plugin.is_learning:
            return Ok({"success": False, "message": "学习循环已在运行中"})

        plugin.is_learning = True
        plugin.is_frozen = False
        plugin.learning_task = asyncio.get_running_loop().create_task(plugin._learning_loop())

        plugin.push_message(
            parts=[{"type": "text",
                    "text": f"🎓 B站AI学习已启动，当前已学习 {plugin.learned_count} 个视频"}],
            visibility=["chat"],
            ai_behavior="blind",
        )
        return Ok({"success": True, "message": "AI学习循环已启动", "status": "running"})

    @plugin_entry(
        id="stop_learning",
        name="停止AI学习",
        description="停止B站AI自动学习循环。",
        kind="action",
    )
    async def stop_learning(self, **_) -> Any:
        plugin = self.main_plugin
        if not plugin.is_learning:
            return Ok({"success": False, "message": "学习循环未运行"})

        plugin.is_learning = False
        await plugin._cancel_learning()

        plugin.push_message(
            parts=[{"type": "text",
                    "text": f"⏹ B站AI学习已停止，本次共学习 {plugin.learned_count} 个视频"}],
            visibility=["chat"],
            ai_behavior="blind",
        )
        return Ok({"success": True, "message": "AI学习循环已停止", "learned_count": plugin.learned_count})

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------

    @plugin_entry(
        id="get_status",
        name="获取状态",
        description="获取插件详细运行状态：学习进度、配置、计数等。",
        kind="action",
    )
    async def get_status(self, **_) -> Any:
        plugin = self.main_plugin
        cfg = await plugin.config.get("bilibili_learning", {}, timeout=5.0)
        cfg = cfg if isinstance(cfg, dict) else {}
        return Ok({
            "success": True,
            "plugin": plugin.plugin_id,
            "is_learning": plugin.is_learning,
            "is_frozen": plugin.is_frozen,
            "uptime": time.monotonic() - plugin.start_time,
            "learned_count": plugin.learned_count,
            "last_learn_time": plugin.last_learn_time,
            "panel_url": plugin.panel_url,
            "config": {
                "learning_interval": cfg.get("learning_interval"),
                "comment_enabled": cfg.get("comment_enabled"),
                "private_msg_enabled": cfg.get("private_msg_enabled"),
                "interest_tags": cfg.get("interest_tags", []),
                "model": cfg.get("model"),
            },
        })

    # ------------------------------------------------------------------
    # 兴趣管理
    # ------------------------------------------------------------------

    @plugin_entry(
        id="manage_interests",
        name="管理兴趣",
        description="添加、删除或列出兴趣标签，控制学习方向。",
        input_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "remove", "list"]},
                "tag": {"type": "string"},
            },
            "required": ["action"],
        },
        kind="action",
    )
    async def manage_interests(self, action: str, tag: str = "", **_) -> Any:
        plugin = self.main_plugin
        interests = await plugin.config.get("bilibili_learning.interest_tags", [], timeout=5.0)
        interests = interests if isinstance(interests, list) else []

        if action == "add" and tag and tag not in interests:
            interests.append(tag)
        elif action == "remove" and tag in interests:
            interests.remove(tag)

        if action in ("add", "remove"):
            await plugin.config.update({"bilibili_learning": {"interest_tags": interests}}, timeout=5.0)

        return Ok({"success": True, "message": "兴趣已更新", "interests": interests})

    # ------------------------------------------------------------------
    # 原项目 Web 面板
    # ------------------------------------------------------------------

    @plugin_entry(
        id="open_web_panel",
        name="打开Web面板",
        description="启动原项目的 Flask Web 管理面板（若存在 web_panel.py）。",
        kind="action",
    )
    async def open_web_panel(self, port: int = 0, **_) -> Any:
        """启动原项目的 Web 面板 (Flask)。"""
        plugin = self.main_plugin
        # 复用插件自带启动逻辑（路径修正 / vendor / 跳过终端免责 / 固定端口）
        plugin._start_flask_panel(port or 8080)
        if plugin.panel_proc is None or plugin.panel_proc.poll() is not None:
            return Err(SdkError("Flask 面板启动失败，请检查插件日志"))
        return Ok({"success": True, "message": "Web面板已启动", "url": plugin.panel_url or ""})
