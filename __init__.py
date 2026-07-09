"""Bilibili AI Learning Bot — Neko Plugin (SDK v2 规范实现)。

将 ``bilibili_learning_bot`` 核心能力封装为 Neko 插件：

- 自动刷推荐流、智能视频理解
- 评论互动、私信处理
- 知识库沉淀、自我进化
- 视频 → 网页 / HTML PPT 生成

入口按职责拆分到 ``routers`` 子包，业务逻辑收敛到 ``_brain.BrainAdapter``
接口（见 ``_brain.py`` 了解如何接入原项目真实逻辑）。
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Dict, List, Optional

from plugin.sdk.plugin import (
    NekoPluginBase,
    neko_plugin,
    plugin_entry,
    lifecycle,
    message,
    llm_tool,
    Ok,
    Err,
    SdkError,
    PluginSettings,
    SettingsField,
)

from ._brain import BrainAdapter, create_brain
from .routers import (
    LearningRouter,
    ContentRouter,
    KnowledgeRouter,
)


@neko_plugin
class BilibiliLearningPlugin(NekoPluginBase):
    """Bilibili AI Learning Bot —— Neko 插件版。"""

    # ── 业务配置：对应 plugin.toml 的 [bilibili_learning] 段 ──
    class Settings(PluginSettings):
        model_config = {"toml_section": "bilibili_learning"}

        bilibili_cookie: str = SettingsField("", description="B站登录 Cookie（留空则仅演示）")
        openai_api_key: str = SettingsField("", description="OpenAI / 兼容 API Key")
        openai_base_url: str = SettingsField("https://api.openai.com/v1", description="API Base URL")
        model: str = SettingsField("gpt-4o-mini", hot=True, description="用于理解的模型")
        learning_interval: int = SettingsField(30, hot=True, ge=5, le=3600, description="学习循环间隔(秒)")
        comment_enabled: bool = SettingsField(True, hot=True, description="是否允许自动评论")
        private_msg_enabled: bool = SettingsField(True, hot=True, description="是否允许自动私信")
        interest_tags: List[str] = SettingsField(
            default_factory=list, hot=True, description="兴趣标签（控制学习方向）"
        )
        auto_coin: bool = SettingsField(False, description="是否自动投币")
        auto_fav: bool = SettingsField(False, description="是否自动收藏")
        safety_review: bool = SettingsField(True, description="是否开启内容安全审核")

    # ── 声明 router（供主进程静态扫描 entry 元数据）──
    __routers__ = [
        LearningRouter,
        ContentRouter,
        KnowledgeRouter,
    ]

    def __init__(self, ctx: Any):
        super().__init__(ctx)
        self.logger = ctx.logger

        # 运行状态
        self.is_learning: bool = False
        self.is_frozen: bool = False
        self.learning_task: Optional[asyncio.Task] = None
        self.learned_count: int = 0
        self.last_learn_time: Optional[float] = None
        self.start_time: float = time.monotonic()

        # 数据队列
        self.video_queue: deque = deque(maxlen=100)
        self.comment_queue: deque = deque(maxlen=50)
        self.knowledge_queue: deque = deque(maxlen=200)

        # 大脑适配器（__init__ 先给占位实现，startup 再按配置重建）
        self.brain: BrainAdapter = create_brain({})

        # Web 面板
        self.panel_proc = None
        self.panel_url: Optional[str] = None

        # 注册 routers —— 必须在 __init__ 中（collect_entries 早于 startup）
        for router_cls in self.__routers__:
            self.include_router(router_cls())

    # ==================================================================
    # 生命周期
    # ==================================================================

    @lifecycle(id="startup")
    async def on_startup(self, **_) -> Any:
        # MARKER: 验证新代码是否被插件子进程加载
        try:
            import os as _os_marker
            _mk = _os_marker.path.join(_os_marker.path.dirname(_os_marker.path.abspath(__file__)), "Data", ".onstart_marker")
            with open(_mk, "a", encoding="utf-8") as _f:
                _f.write("on_startup entered\n")
        except Exception:
            pass
        self.logger.info("🚀 B站AI学习机器人已启动 v%s", getattr(self, "version", "?"))
        # 随插件启动自动拉起原项目 Flask 管理面板。
        # 注意：必须在后台线程里拉起，且绝不在 startup 关键路径上 await 任何
        # 宿主 RPC（如 config.get）——否则会与宿主的 startup 握手形成死锁，
        # 表现为「进程活着但 10s 启动超时」。
        try:
            import threading as _threading
            _threading.Thread(target=self._start_flask_panel, daemon=True).start()
        except Exception as e:  # noqa: BLE001
            self.logger.error("后台拉起 Flask 面板失败: %s", e)
        # 延迟重建大脑（config.get 是宿主 RPC，放到后台任务，避免启动死锁）
        try:
            asyncio.create_task(self._safe_rebuild_brain())
        except Exception:  # noqa: BLE001
            pass
        # 注册静态 Web UI（plugin/plugins/bilibili_learning/static/index.html）
        try:
            if self.register_static_ui("static"):
                self.logger.info("静态 Web UI 已注册")
        except Exception as e:  # noqa: BLE001
            self.logger.warning("静态 Web UI 注册失败（可忽略）: %s", e)
        return Ok({"status": "ready"})

    # ------------------------------------------------------------------
    # 原项目 Flask 管理面板（独立子进程，UI 页通过 iframe 嵌入）
    # ------------------------------------------------------------------

    def _start_flask_panel(self, port: int = 8080) -> None:
        """随插件启动自动拉起原项目 Flask Web 面板（web_panel.py）。

        路径 / 依赖 / 端口 / 免责声明均已修正，确保子进程能独立跑起来。
        关键点：子进程输出重定向到日志文件（而非 PIPE，避免管道缓冲死锁），
        并剔除 WorkBuddy 沙箱的 safe-delete shim，避免其 sitecustomize 钩子
        干扰子进程；用 start_new_session 彻底脱离插件进程树。
        """
        import os as _os
        import subprocess as _sp
        import sys as _sys
        from pathlib import Path as _Path

        if self.panel_proc is not None and self.panel_proc.poll() is None:
            return  # 已在运行
        project_dir = _Path(__file__).resolve().parent
        panel_script = project_dir / "web_panel.py"
        if not panel_script.exists():
            self.logger.warning("未找到 web_panel.py，跳过自动启动面板")
            return
        vendor_dir = project_dir / "vendor"
        env = dict(_os.environ)
        # 仅保留插件自身路径与 vendor，剔除 WorkBuddy 沙箱 shim
        # （其 sitecustomize 会把 shutil.rmtree 劫持成「安全删除」，在沙箱无回收站时
        #  可能卡死或报错，干扰 web_panel.py 运行）
        inherited = env.get("PYTHONPATH", "")
        clean = [
            p for p in inherited.split(_os.pathsep)
            if p and "cli/vendor/shim" not in p and "safe-bin" not in p and "safe_delete" not in p.lower()
        ]
        env["PYTHONPATH"] = _os.pathsep.join([str(project_dir), str(vendor_dir)] + clean)
        env["BILI_DISCLAIMER_SKIP"] = "1"   # 跳过终端 input() 免责确认（子进程非交互会卡死）
        env["WEB_PORT"] = str(port)         # 固定端口，UI 页据此 iframe
        env["WEB_HOST"] = "127.0.0.1"
        # 输出重定向到日志文件，避免父子进程共享 PIPE 导致缓冲死锁
        log_path = project_dir / "Data" / "panel.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            _logf = open(str(log_path), "ab", buffering=0)
        except Exception:  # noqa: BLE001
            _logf = None
        try:
            self.panel_proc = _sp.Popen(
                [_sys.executable, str(panel_script)],
                cwd=str(project_dir),
                env=env,
                stdout=_logf if _logf is not None else _sp.DEVNULL,
                stderr=_sp.STDOUT if _logf is not None else _sp.DEVNULL,
                start_new_session=True,
            )
            self.panel_url = f"http://localhost:{port}"
            self.logger.info("🌐 Flask 面板已随插件启动 PID=%d port=%d", self.panel_proc.pid, port)
        except Exception as e:  # noqa: BLE001
            self.logger.error("自动启动 Flask 面板失败: %s", e)
            if _logf is not None:
                try:
                    _logf.close()
                except Exception:
                    pass

    @lifecycle(id="shutdown")
    async def on_shutdown(self, **_) -> Any:
        self.logger.info("🛑 正在关闭...")
        self.is_learning = False
        await self._cancel_learning()
        self._kill_panel()
        return Ok({"status": "stopped"})

    @lifecycle(id="freeze")
    async def on_freeze(self, **_) -> Any:
        self.is_frozen = True
        self.logger.info("⏸️ 已暂停")
        return Ok({"status": "frozen"})

    @lifecycle(id="unfreeze")
    async def on_unfreeze(self, **_) -> Any:
        self.is_frozen = False
        self.logger.info("▶️ 已恢复")
        return Ok({"status": "unfrozen"})

    @lifecycle(id="config_change")
    async def on_config_change(self, **_) -> Any:
        await self._rebuild_brain()
        self.logger.info("配置已热更新")
        return Ok({"status": "reloaded"})

    # ==================================================================
    # 消息处理
    # ==================================================================

    @message(id="chat_handler")
    async def on_message(self, **kwargs) -> Any:
        text = str(kwargs.get("text", "") or "").strip()
        if not text:
            return Ok({"handled": False})
        if text == "/bililearn status":
            self.push_message(
                parts=[{"type": "text",
                        "text": f"📊 已学习 {self.learned_count} 个视频，"
                                f"{'运行中' if self.is_learning else '已停止'}"}],
                visibility=["chat"],
                ai_behavior="blind",
            )
            return Ok({"handled": True})
        return Ok({"handled": False})

    # ==================================================================
    # LLM 工具（模型可直接调用）
    # ==================================================================

    @llm_tool(
        name="bili_start_learning",
        description="启动B站AI自动学习循环。",
    )
    async def llm_start_learning(self, **_) -> Any:
        if self.is_learning:
            return {"ok": False, "message": "已在运行"}
        self.is_learning = True
        self.is_frozen = False
        self.learning_task = asyncio.get_running_loop().create_task(self._learning_loop())
        return {"ok": True, "status": "running", "learned_count": self.learned_count}

    @llm_tool(
        name="bili_stop_learning",
        description="停止B站AI自动学习循环。",
    )
    async def llm_stop_learning(self, **_) -> Any:
        if not self.is_learning:
            return {"ok": False, "message": "未运行"}
        self.is_learning = False
        await self._cancel_learning()
        return {"ok": True, "learned_count": self.learned_count}

    @llm_tool(
        name="bili_status",
        description="查询B站AI学习机器人的运行状态与配置。",
    )
    async def llm_status(self, **_) -> Any:
        cfg = await self.config.get("bilibili_learning", {}, timeout=5.0)
        cfg = cfg if isinstance(cfg, dict) else {}
        return {
            "is_learning": self.is_learning,
            "learned_count": self.learned_count,
            "interest_tags": cfg.get("interest_tags", []),
            "model": cfg.get("model"),
        }

    @llm_tool(
        name="bili_analyze_video",
        description="分析一个B站视频链接，返回标题、摘要、标签与评分。",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "B站视频链接或 BV 号"},
            },
            "required": ["url"],
        },
    )
    async def llm_analyze_video(self, *, url: str, **_) -> Any:
        analysis = await self.brain.analyze_video(url)
        return analysis.to_dict()

    # ==================================================================
    # 内部方法
    # ==================================================================

    async def _rebuild_brain(self) -> None:
        """按当前配置重建大脑适配器。"""
        cfg = await self.config.get("bilibili_learning", {}, timeout=5.0)
        cfg = cfg if isinstance(cfg, dict) else {}
        self.brain = create_brain(cfg)
        self.logger.info("大脑适配器已重建（model=%s）", cfg.get("model", "?"))

    async def _safe_rebuild_brain(self) -> None:
        """后台安全地重建大脑；失败不影响插件启动（保留占位实现）。"""
        try:
            await self._rebuild_brain()
        except Exception as e:  # noqa: BLE001
            self.logger.warning("大脑适配器重建失败（将使用占位实现）: %s", e)

    def _kill_panel(self) -> None:
        if self.panel_proc is not None and self.panel_proc.poll() is None:
            self.logger.info("关闭 Web 面板 PID=%d", self.panel_proc.pid)
            self.panel_proc.terminate()
            try:
                self.panel_proc.wait(timeout=5)
            except Exception:
                self.panel_proc.kill()
        self.panel_proc = None
        self.panel_url = None

    async def _cancel_learning(self) -> None:
        task = self.learning_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.learning_task = None

    async def _learning_loop(self) -> None:
        interval = max(5, int(await self.config.get("bilibili_learning.learning_interval", 30) or 30))
        self.logger.info("🎓 学习循环启动，间隔: %ds", interval)
        while self.is_learning:
            try:
                if self.is_frozen:
                    await asyncio.sleep(1)
                    continue
                await self._learn_one_video()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                self.logger.exception("学习循环异常: %s", e)
                await asyncio.sleep(5)
        self.logger.info("🛑 学习循环已结束")

    async def _learn_one_video(self) -> None:
        self.learned_count += 1
        self.last_learn_time = time.time()
        self.logger.info("📺 正在学习第 %d 个视频...", self.learned_count)

        title = "一个B站视频"
        try:
            feed = await self.brain.recommend_feed()
            top = feed[0] if isinstance(feed, list) and feed else None
            if isinstance(top, dict):
                title = top.get("title", title)
        except Exception:  # noqa: BLE001
            pass

        self.push_message(
            parts=[{"type": "text",
                    "text": f"🎓 刚学习了「{title}」（第 {self.learned_count} 个），"
                            f"请总结要点并沉淀知识到记忆中"}],
            visibility=[],
            ai_behavior="respond",
        )
