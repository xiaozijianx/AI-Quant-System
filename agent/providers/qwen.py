# -*- coding: utf-8 -*-
"""通义千问 AgentModel 适配器 — 对标 Cline gateway provider

使用 DashScope 的 OpenAI 兼容模式 API，通过 AsyncOpenAI 客户端调用。

关键设计:
    1. 实现 AgentModel 协议的 stream() 方法，返回 AsyncIterator[AgentModelEvent]
    2. 将 AgentModelRequest 转为 OpenAI 兼容格式（messages + tools）
    3. 流式解析 SSE chunk，转为 AgentModelEvent:
       - delta.content → text-delta
       - delta.reasoning_content → reasoning-delta（Qwen 思考模式）
       - delta.tool_calls → tool-call-delta
       - usage → usage
       - finish_reason → finish

对标 Cline:
    - 消息格式转换: sdk/packages/llms/src/providers/format.ts
    - SSE 流解析: sdk/packages/llms/src/providers/stream.ts
    - Provider 接口: sdk/packages/shared/src/llms/gateway.ts

配置项:
    - API key 环境变量: DASHSCOPE_API_KEY
    - Base URL: https://dashscope.aliyuncs.com/compatible-mode/v1
    - 模型: qwen-plus（默认）
    - 工具调用格式: OpenAI function calling
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, AsyncIterator

from agent.types import (
    AgentModelEvent,
    AgentModelFinishReason,
    AgentModelRequest,
)
from agent.providers.base import (
    agent_messages_to_openai,
    map_finish_reason,
    tools_to_openai,
)
from agent.providers.errors import (
    ProviderAuthError,
    classify_openai_error,
)

# DashScope OpenAI 兼容模式端点
_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# 默认流式空闲超时（秒）
_DEFAULT_IDLE_TIMEOUT = 90


class QwenModel:
    """通义千问 AgentModel 实现 — 对标 Cline AgentModel

    使用 DashScope OpenAI 兼容模式 API，支持:
        - 流式文本输出 (text-delta)
        - 推理过程输出 (reasoning-delta, Qwen 思考模式)
        - 工具调用 (tool-call-delta, OpenAI function calling)
        - Token 用量 (usage)
        - 空闲超时检测

    用法:
        model = QwenModel(model="qwen-plus")
        async for event in model.stream(request):
            if event.type == "text-delta":
                print(event.text, end="")
    """

    def __init__(
        self,
        model: str = "qwen-plus",
        api_key: str | None = None,
        base_url: str | None = None,
        max_tokens: int = 8192,
        temperature: float = 0.1,
        idle_timeout: int = _DEFAULT_IDLE_TIMEOUT,
        capabilities: list[str] | None = None,
    ) -> None:
        """初始化 Qwen 模型适配器

        Args:
            model: 模型名称，如 qwen-plus / qwen-max / qwen-turbo
            api_key: DashScope API Key，默认从 DASHSCOPE_API_KEY 环境变量读取
            base_url: API 端点，默认 DashScope 兼容模式
            max_tokens: 最大输出 token 数
            temperature: 温度参数（0-1），越低越确定性
            idle_timeout: 流式空闲超时秒数
            capabilities: provider 能力列表（Stage 7.8 新增），None 时默认
                          ["reasoning", "tools", "streaming"]。供 model-tool-routing
                          等模块查询模型能力
        """
        self.model = model
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY", "")
        self.base_url = base_url or _DASHSCOPE_BASE_URL
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.idle_timeout = idle_timeout
        # Stage 7.8: 暴露 capabilities 实例属性 — 对标 Cline ProviderManifest.capabilities
        self.capabilities = list(capabilities) if capabilities else [
            "reasoning", "tools", "streaming",
        ]

        if not self.api_key:
            raise ProviderAuthError(
                "DashScope API Key 未设置。"
                "请通过 api_key 参数传入或设置 DASHSCOPE_API_KEY 环境变量。",
                provider_id="qwen",
            )

        # 延迟导入 openai，避免未安装时影响其他模块
        self._client = self._create_client()

    def _create_client(self) -> Any:
        """创建 AsyncOpenAI 客户端

        使用 max_retries=0，重试由 AgentRuntime 层处理。
        """
        from openai import AsyncOpenAI

        return AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            max_retries=0,
        )

    async def stream(
        self,
        request: AgentModelRequest,
        abort_signal: Any = None,
    ) -> AsyncIterator[AgentModelEvent]:
        """调用 Qwen API 流式生成 — 对标 Cline AgentModel.stream()

        将 AgentModelRequest 转为 OpenAI 格式，调用 DashScope API，
        流式返回 AgentModelEvent。

        事件序列:
            text-delta*      — 文本增量（零或多个）
            reasoning-delta* — 推理增量（零或多个，Qwen 思考模式）
            tool-call-delta* — 工具调用增量（零或多个）
            usage?           — Token 用量（通常在最后一个 chunk）
            finish           — 结束事件（始终最后一个）

        Args:
            request: Agent 模型请求，包含 system_prompt / messages / tools

        Yields:
            AgentModelEvent: 流式事件
        """
        # 构建请求参数
        # Stage 13.1 (R5): 根据 capabilities 做能力降级（vision/reasoning/tools）
        from agent.providers.base import apply_capability_downgrade
        request = apply_capability_downgrade(request)
        kwargs = self._build_kwargs(request)

        # Cline 的 ai-sdk provider 会为每个 tool call 维护稳定的 toolCallId。
        # Qwen/DashScope 的流式响应中，tool_call_id 通常只在第一个 delta 出现，
        # 后续 delta 的 id 为空字符串。这里按 index 记录首次出现的 id，确保同一
        # 工具调用的所有 delta 使用相同的 tool_call_id。
        tool_call_ids: dict[int | None, str] = {}

        finish_emitted = False
        try:
            stream = await self._client.chat.completions.create(**kwargs)
            stream_iter = stream.__aiter__()

            while True:
                # Phase 28.2: 检查中止信号，在 chunk 间隙立即终止流式接收
                # Phase 2.1: 用户中止走 ABORTED，与真实错误 ERROR 区分 — 对标 Cline
                if abort_signal is not None and abort_signal.is_set():
                    yield AgentModelEvent(
                        type="finish",
                        reason=AgentModelFinishReason.ABORTED,
                        error="aborted by user",
                    )
                    return
                try:
                    chunk = await asyncio.wait_for(
                        stream_iter.__anext__(),
                        timeout=self.idle_timeout,
                    )
                except StopAsyncIteration:
                    break

                # 解析 chunk 并发射事件
                async for event in self._parse_chunk(chunk, tool_call_ids):
                    if event.type == "finish":
                        finish_emitted = True
                    yield event

            # 如果 chunk 中没有 finish_reason，补发一个 stop finish
            if not finish_emitted:
                yield AgentModelEvent(
                    type="finish",
                    reason=AgentModelFinishReason.STOP,
                )

        except asyncio.TimeoutError:
            yield AgentModelEvent(
                type="finish",
                reason=AgentModelFinishReason.ERROR,
                error=f"Qwen API 流式响应超时（{self.idle_timeout}秒无数据）",
            )
        except Exception as e:
            # P2-20: 将 OpenAI SDK 异常映射到 ProviderError 层级
            classified = classify_openai_error(e, provider_id="qwen")
            yield AgentModelEvent(
                type="finish",
                reason=AgentModelFinishReason.ERROR,
                error=str(classified),
            )

    def _build_kwargs(self, request: AgentModelRequest) -> dict[str, Any]:
        """构建 OpenAI API 请求参数
        """
        # 转换消息
        messages: list[dict[str, Any]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.extend(agent_messages_to_openai(request.messages))

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        # 转换工具
        if request.tools:
            kwargs["tools"] = tools_to_openai(request.tools)
            kwargs["tool_choice"] = request.options.get("tool_choice", "auto")

        # 合并额外选项
        extra_options = request.options.get("model_options", {})
        if isinstance(extra_options, dict):
            for key in ("top_p", "presence_penalty", "frequency_penalty", "stop"):
                if key in extra_options:
                    kwargs[key] = extra_options[key]

        return kwargs

    async def _parse_chunk(
        self,
        chunk: Any,
        tool_call_ids: dict[int | None, str] | None = None,
    ) -> AsyncIterator[AgentModelEvent]:
        """解析单个 SSE chunk，发射对应的 AgentModelEvent

        对标 Cline stream.ts 的 chunk 解析逻辑。

        解析规则:
            1. chunk.choices[0].delta.content → text-delta
            2. chunk.choices[0].delta.reasoning_content → reasoning-delta
            3. chunk.choices[0].delta.tool_calls → tool-call-delta
            4. chunk.usage → usage
            5. chunk.choices[0].finish_reason → finish

        Args:
            chunk: OpenAI SDK 返回的 SSE chunk
            tool_call_ids: 按 index 记录 tool_call_id 的状态表，确保同一工具调用
                          在多个 delta 间保持一致的 id
        """
        chunk_dict = _to_dict(chunk)

        # 处理 usage（通常在最后一个 chunk）
        usage = _get_nested(chunk_dict, ("usage",))
        if usage:
            usage_dict = _to_dict(usage)
            # Stage 7.8 (R15): 补全 usage 字段 — 对标 Cline ApiStreamUsageChunk
            # 含 input_tokens / output_tokens / cache_read_tokens / cache_write_tokens
            # / reasoning_token_count / total_cost 共 6 字段
            cache_write_tokens = (
                _get_nested_int(usage_dict, ("prompt_tokens_details", "write_tokens"))
                or _get_nested_int(usage_dict, ("cache_creation_input_tokens",))
            )
            reasoning_token_count = _get_nested_int(
                usage_dict, ("completion_tokens_details", "reasoning_tokens")
            )
            yield AgentModelEvent(
                type="usage",
                usage={
                    "input_tokens": int(usage_dict.get("prompt_tokens", 0)),
                    "output_tokens": int(usage_dict.get("completion_tokens", 0)),
                    "cache_read_tokens": _get_nested_int(
                        usage_dict, ("prompt_tokens_details", "cached_tokens")
                    ),
                    # Stage 7.8 新增字段（API 不返回时为 0，不抛错）
                    "cache_write_tokens": cache_write_tokens,
                    "reasoning_token_count": reasoning_token_count,
                    "total_cost": 0.0,  # 暂无定价表，预留字段
                },
            )

        choices = _get_nested(chunk_dict, ("choices",))
        if not choices:
            return

        choice = _to_dict(choices[0]) if choices else {}
        delta = _to_dict(choice.get("delta", {})) if choice else {}
        finish_reason = choice.get("finish_reason")

        # text-delta: 正文内容
        content = delta.get("content")
        if content and isinstance(content, str):
            yield AgentModelEvent(
                type="text-delta",
                text=content,
            )

        # reasoning-delta: 推理内容（Qwen 思考模式，对标 Cline reasoning chunk）
        reasoning_content = delta.get("reasoning_content")
        if reasoning_content and isinstance(reasoning_content, str):
            yield AgentModelEvent(
                type="reasoning-delta",
                text=reasoning_content,
            )

        # tool-call-delta: 工具调用增量
        tool_calls = delta.get("tool_calls")
        if tool_calls and isinstance(tool_calls, list):
            # Stage 10.1 (C8/C18): 提取 provider metadata — 对标 Cline llm-gateway chunk.metadata
            # 从 chunk 顶层提取 request_id / model_version，标准化字段名
            # finish_reason 仅在 finish chunk 有值，tool-call-delta chunk 通常为 None
            chunk_metadata: dict[str, Any] = {}
            request_id = chunk_dict.get("id")
            if request_id:
                chunk_metadata["request_id"] = request_id
            model_version = chunk_dict.get("model")
            if model_version:
                chunk_metadata["model_version"] = model_version
            if finish_reason:
                chunk_metadata["finish_reason"] = finish_reason
            # 包装为 provider_metadata 子字段，runtime 的 _deep_merge_metadata 会深度合并
            tool_event_metadata = (
                {"provider_metadata": chunk_metadata} if chunk_metadata else None
            )

            for tc in tool_calls:
                tc_dict = _to_dict(tc)
                fn_dict = _to_dict(tc_dict.get("function", {}))
                index = tc_dict.get("index")
                raw_id = tc_dict.get("id") or ""

                # 保持同一 index 的 tool_call_id 稳定：
                # Cline 的 ai-sdk provider 会在同一工具调用的所有 delta 中emit相同
                # 的 toolCallId；Qwen 通常只在第一个 delta 提供 id，后续为空字符串。
                # 这里按 index 记录首次出现的有效 id，并在后续 delta 中复用。
                id_map = tool_call_ids if tool_call_ids is not None else {}
                if raw_id:
                    id_map[index] = raw_id
                tool_call_id = id_map.get(index)
                if not tool_call_id:
                    tool_call_id = raw_id or f"tool_{uuid.uuid4().hex[:8]}"
                    id_map[index] = tool_call_id

                yield AgentModelEvent(
                    type="tool-call-delta",
                    index=index,
                    tool_call_id=tool_call_id,
                    tool_name=fn_dict.get("name"),
                    input_text=fn_dict.get("arguments"),
                    # Stage 10.1 (C8/C18): 携带 provider metadata
                    metadata=tool_event_metadata,
                )

        # finish: 结束原因
        if finish_reason:
            yield AgentModelEvent(
                type="finish",
                reason=map_finish_reason(finish_reason),
            )


# ============================================================================
# 辅助函数 — 处理 SDK 对象和 dict 的统一访问
# ============================================================================

def _to_dict(obj: Any) -> dict[str, Any]:
    """将 SDK Pydantic 对象或 dict 统一转为 dict
    """
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    # SDK Pydantic 对象
    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        result = model_dump()
        if isinstance(result, dict):
            return result
    # 尝试 __dict__
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return {}


def _get_nested(obj: Any, path: tuple[str, ...]) -> Any:
    """按路径获取嵌套值，兼容 dict 和对象属性
    """
    current = obj
    for segment in path:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(segment)
        else:
            current = getattr(current, segment, None)
    return current


def _get_nested_int(obj: Any, path: tuple[str, ...]) -> int:
    """按路径获取嵌套整数值"""
    value = _get_nested(obj, path)
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
