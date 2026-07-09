"""B 站 AI 学习机器人 —— 大脑适配层 (Brain Adapter)。

设计目标：把插件对「真实 B 站学习逻辑」的依赖收敛到一个接口之后，
插件主体只依赖接口，不依赖具体实现。这样带来两个好处：

1. **可独立运行**：未安装原项目 ``bilibili_learning_bot`` 时，
   :class:`StubBrainAdapter` 提供可演示的占位实现，插件能正常加载、
   所有入口都能返回结构化数据。
2. **可平滑接入**：安装原项目后，:func:`create_brain` 会返回一个
   :class:`RealBrainAdapter`，把调用转发到 ``bilibili_learning_bot`` 的
   ``AgentBrain`` / ``api`` / ``knowledge`` 等模块。

接入真实逻辑时，只需要补全 ``RealBrainAdapter`` 里标注 ``TODO`` 的
几行转发代码即可，无需改动任何 entry / router。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class VideoAnalysis:
    """视频分析结果（结构化，便于 LLM 消费）。"""

    title: str
    summary: str
    tags: List[str] = field(default_factory=list)
    score: float = 0.0
    detailed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "tags": list(self.tags),
            "score": self.score,
            "detailed": self.detailed,
        }


class BrainAdapter:
    """插件与真实业务逻辑之间的契约。

    所有方法都为 ``async``，与 Neko 入口点保持一致；真实实现内部可
    自由使用线程池 / 子进程包装同步的 B 站 SDK 调用。
    """

    async def analyze_video(self, url: str, detailed: bool = False) -> VideoAnalysis:
        raise NotImplementedError

    async def generate_html(self, url: str, style: str = "claude") -> Dict[str, Any]:
        """将视频内容转换为 HTML 网页，返回任务元数据。"""
        raise NotImplementedError

    async def send_comment(self, video_id: str, content: str) -> Dict[str, Any]:
        raise NotImplementedError

    async def reply_private(self, user_id: str, content: str) -> Dict[str, Any]:
        raise NotImplementedError

    async def search_knowledge(self, query: str, limit: int) -> List[Dict[str, Any]]:
        raise NotImplementedError

    async def recommend_feed(self) -> List[Dict[str, Any]]:
        """返回推荐流里待学习的视频列表。"""
        raise NotImplementedError


class StubBrainAdapter(BrainAdapter):
    """占位实现：未接入真实逻辑时使用，保证插件可独立运行与演示。"""

    def __init__(self) -> None:
        self._knowledge: List[Dict[str, Any]] = [
            {"topic": "示例知识：Python 异步编程", "source": "BV1xx411c7mD", "score": 8.6},
            {"topic": "示例知识：Transformer 注意力机制", "source": "BV1xxxxxx", "score": 9.1},
        ]

    async def analyze_video(self, url: str, detailed: bool = False) -> VideoAnalysis:
        return VideoAnalysis(
            title=f"示例视频（来自 {url}）",
            summary=(
                "这是一个由 StubBrainAdapter 生成的示例摘要。"
                "接入真实逻辑后，这里会输出由 LLM 提炼的视频要点。"
            ),
            tags=["技术", "示例", "待接入"],
            score=8.5,
            detailed=detailed,
        )

    async def generate_html(self, url: str, style: str = "claude") -> Dict[str, Any]:
        return {
            "task_id": f"html_{int(time.time())}",
            "style": style,
            "source": url,
            "status": "queued",
            "note": "Stub 实现仅返回任务元数据；真实实现会生成 HTML PPT 文件。",
        }

    async def send_comment(self, video_id: str, content: str) -> Dict[str, Any]:
        return {"video_id": video_id, "content": content, "status": "stub_sent"}

    async def reply_private(self, user_id: str, content: str) -> Dict[str, Any]:
        return {"user_id": user_id, "content": content, "status": "stub_sent"}

    async def search_knowledge(self, query: str, limit: int) -> List[Dict[str, Any]]:
        if not query:
            return self._knowledge[:limit]
        q = query.lower()
        return [k for k in self._knowledge if q in str(k).lower()][:limit]

    async def recommend_feed(self) -> List[Dict[str, Any]]:
        return [
            {"bvid": "BV1xx411c7mD", "title": "Python 异步入门", "reason": "符合兴趣标签"},
            {"bvid": "BV1abcdefg", "title": "深度学习中的注意力机制", "reason": "高评分内容"},
        ]


class RealBrainAdapter(BrainAdapter):
    """真实适配器：把调用转发到 ``bilibili_learning_bot`` 原项目。

    只在创建时按需 import 原项目，因此未安装时不会影响插件加载。
    每个方法里标注了 ``TODO`` 的转发点，按你原项目的实际 API 填即可。
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        self._config = config
        # TODO: 在这里初始化原项目的 AgentBrain / api 客户端
        #   from bilibili_learning_bot.core.brain import AgentBrain
        #   self._brain = AgentBrain(
        #       cookie=config.get("bilibili_cookie"),
        #       api_key=config.get("openai_api_key"),
        #       base_url=config.get("openai_base_url"),
        #       model=config.get("model"),
        #   )
        self._brain = None  # type: ignore[assignment]
        self._stub = StubBrainAdapter()  # 兜底：未初始化成功时退化到占位

    async def analyze_video(self, url: str, detailed: bool = False) -> VideoAnalysis:
        if self._brain is None:
            return await self._stub.analyze_video(url, detailed)
        # TODO: res = await self._brain.analyze(url, detailed=detailed)
        #       return VideoAnalysis(title=res.title, summary=res.summary, ...)
        return await self._stub.analyze_video(url, detailed)

    async def generate_html(self, url: str, style: str = "claude") -> Dict[str, Any]:
        if self._brain is None:
            return await self._stub.generate_html(url, style)
        # TODO: return await self._brain.video_to_html(url, style=style)
        return await self._stub.generate_html(url, style)

    async def send_comment(self, video_id: str, content: str) -> Dict[str, Any]:
        if self._brain is None:
            return await self._stub.send_comment(video_id, content)
        # TODO: return await self._brain.comment(video_id, content)
        return await self._stub.send_comment(video_id, content)

    async def reply_private(self, user_id: str, content: str) -> Dict[str, Any]:
        if self._brain is None:
            return await self._stub.reply_private(user_id, content)
        # TODO: return await self._brain.reply_dm(user_id, content)
        return await self._stub.reply_private(user_id, content)

    async def search_knowledge(self, query: str, limit: int) -> List[Dict[str, Any]]:
        if self._brain is None:
            return await self._stub.search_knowledge(query, limit)
        # TODO: return await self._brain.knowledge.search(query, limit=limit)
        return await self._stub.search_knowledge(query, limit)

    async def recommend_feed(self) -> List[Dict[str, Any]]:
        if self._brain is None:
            return await self._stub.recommend_feed()
        # TODO: return await self._brain.recommend()
        return await self._stub.recommend_feed()


def create_brain(config: Dict[str, Any]) -> BrainAdapter:
    """根据配置创建大脑适配器。

    默认返回 :class:`RealBrainAdapter`（内部会在原项目缺失时自动退化到
    占位实现），因此无论是否安装原项目，插件都能正常运行。
    """
    return RealBrainAdapter(config)
