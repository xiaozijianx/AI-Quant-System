# -*- coding: utf-8 -*-
"""OpenAI 兼容 provider 适配器 — 对标 Cline gateway openai-compatible client

支持所有兼容 OpenAI Chat Completions API 的 provider:
    - OpenAI 官方（api.openai.com）
    - DeepSeek（api.deepseek.com）
    - Moonshot（api.moonshot.cn）
    - Zhipu（open.bigmodel.cn）
    - 任何兼容 OpenAI 协议的自部署模型（vLLM / Ollama / LM Studio 等）

与 QwenModel 的区别:
    1. provider_id 显式暴露为类属性，供 model-tool-routing 使用
    2. base_url 完全可配置，不绑定 DashScope
    3. reasoning_content 字段可选（部分 provider 不返回）
    4. 默认 idle_timeout 提高到 120s（兼容推理较慢的开源模型）

对标 Cline:
    - sdk/packages/llms/src/providers/openai-compatible.ts
    - sdk/packages/core/src/services/llms/handler-factory.ts
    - sdk/packages/core/src/services/llms/provider-defaults.ts
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

# 默认流式空闲超时（秒），兼容推理较慢的开源模型
_DEFAULT_IDLE_TIMEOUT = 120


class OpenAIModel:
    """OpenAI 兼容 AgentModel 实现 — 对标 Cline AgentModel

    使用 openai Python SDK 的 AsyncOpenAI 客户端调用任意 OpenAI 兼容 API。
    支持流式文本 / 推理 / 工具调用 / Token 用量。

    用法:
        # OpenAI 官方
        model = OpenAIModel(model="gpt-4o", api_key="sk-...")
        # DeepSeek
        model = OpenAIModel(
            model="deepseek-chat",
            api_key="sk-...",
            base_url="https://api.deepseek.com/v1",
            provider_id="deepseek",
        )
        # 自部署 vLLM
        model = OpenAIModel(
            model="Qwen2.5-72B-Instruct",
            api_key="EMPTY",
            base_url="http://localhost:8000/v1",
            provider_id="vllm",
        )
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        max_tokens: int = 8192,
        temperature: float = 0.1,
        idle_timeout: int = _DEFAULT_IDLE_TIMEOUT,
        provider_id: str = "openai",
        supports_reasoning: bool = True,
        capabilities: list[str] | None = None,
    ) -> None:
        """初始化 OpenAI 兼容模型适配器

        Args:
            model: 模型名称，如 gpt-4o / deepseek-chat / moonshot-v1-8k
            api_key: API Key，默认从 OPENAI_API_KEY 环境变量读取
            base_url: API 端点，None 时使用 OpenAI 官方端点
            max_tokens: 最大输出 token 数
            temperature: 温度参数（0-1）
            idle_timeout: 流式空闲超时秒数
            provider_id: provider 标识，用于 model-tool-routing 路由
            supports_reasoning: 是否解析 reasoning_content 字段
                               （OpenAI o1/o3、DeepSeek-R1 等推理模型为 True；
                                普通 chat 模型可设 False 跳过解析）
            capabilities: provider 能力列表（Stage 7.8 新增），None 时按
                          supports_reasoning 派生为 ["reasoning", "tools", "streaming"]
                          或 ["tools", "streaming"]。供 model-tool-routing 等模块查询
        """
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url  # None 时 AsyncOpenAI 使用默认 OpenAI 端点
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.idle_timeout = idle_timeout
        self.provider_id = provider_id  # 暴露给 model-tool-routing
        self.supports_reasoning = supports_reasoning
        # Stage 7.8: 暴露 capabilities 实例属性 — 对标 Cline ProviderManifest.capabilities
        if capabilities is not None:
            self.capabilities = list(capabilities)
        else:
            # 派生默认值：supports_reasoning=True 时含 reasoning，否则不含
            self.capabilities = (
                ["reasoning", "tools", "streaming"]
                if supports_reasoning
                else ["tools", "streaming"]
            )

        if not self.api_key:
            raise ProviderAuthError(
                "API Key 未设置。请通过 api_key 参数传入或设置 OPENAI_API_KEY 环境变量。",
                provider_id=self.provider_id,
            )

        # 延迟导入 openai，避免未安装时影响其他模块
        self._client = self._create_client()

    def _create_client(self) -> Any:
        """创建 AsyncOpenAI 客户端

        使用 max_retries=0，重试由 AgentRuntime 层处理。
        """
        from openai import AsyncOpenAI

        kwargs: dict[str, Any] = {
            "api_key": self.api_key,
            "max_retries": 0,
        }
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return AsyncOpenAI(**kwargs)

    async def stream(
        self,
        request: AgentModelRequest,
        abort_signal: Any = None,
    ) -> AsyncIterator[AgentModelEvent]:
        """调用 OpenAI 兼容 API 流式生成 — 对标 Cline AgentModel.stream()

        事件序列:
            text-delta*      — 文本增量
            reasoning-delta* — 推理增量（仅 supports_reasoning=True 时）
            tool-call-delta* — 工具调用增量
            usage?           — Token 用量
            finish           — 结束事件
        """
        # Stage 13.1 (R5): 根据 capabilities 做能力降级（vision/reasoning/tools）
        from agent.providers.base import apply_capability_downgrade
        request = apply_capability_downgrade(request)
        kwargs = self._build_kwargs(request)

        # 按 index 维护稳定的 tool_call_id（OpenAI 兼容 provider 与 Qwen 行为一致）
        tool_call_ids: dict[int | None, str] = {}
        finish_emitted = False

        try:
            stream = await self._client.chat.completions.create(**kwargs)
            stream_iter = stream.__aiter__()

            while True:
                # Phase 28.2: 检查中止信号
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

                async for event in self._parse_chunk(chunk, tool_call_ids):
                    if event.type == "finish":
                        finish_emitted = True
                    yield event

            if not finish_emitted:
                yield AgentModelEvent(
                    type="finish",
                    reason=AgentModelFinishReason.STOP,
                )

        except asyncio.TimeoutError:
            yield AgentModelEvent(
                type="finish",
                reason=AgentModelFinishReason.ERROR,
                error=f"OpenAI API 流式响应超时（{self.idle_timeout}秒无数据）",
            )
        except Exception as e:
            # P2-20: 将 OpenAI SDK 异常映射到 ProviderError 层级
            classified = classify_openai_error(e, provider_id=self.provider_id)
            yield AgentModelEvent(
                type="finish",
                reason=AgentModelFinishReason.ERROR,
                error=str(classified),
            )

    def _build_kwargs(self, request: AgentModelRequest) -> dict[str, Any]:
        """构建 OpenAI API 请求参数"""
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
        """解析单个 SSE chunk — 与 QwenModel._parse_chunk 逻辑一致"""
        chunk_dict = _to_dict(chunk)

        # usage
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

        # text-delta
        content = delta.get("content")
        if content and isinstance(content, str):
            yield AgentModelEvent(type="text-delta", text=content)

        # reasoning-delta（仅当 supports_reasoning=True）
        if self.supports_reasoning:
            reasoning_content = delta.get("reasoning_content")
            if reasoning_content and isinstance(reasoning_content, str):
                yield AgentModelEvent(
                    type="reasoning-delta",
                    text=reasoning_content,
                )

        # tool-call-delta
        tool_calls = delta.get("tool_calls")
        if tool_calls and isinstance(tool_calls, list):
            # Stage 10.1 (C8/C18): 提取 provider metadata — 对标 Cline llm-gateway chunk.metadata
            # 从 chunk 顶层提取 request_id / model_version，标准化字段名
            chunk_metadata: dict[str, Any] = {}
            request_id = chunk_dict.get("id")
            if request_id:
                chunk_metadata["request_id"] = request_id
            model_version = chunk_dict.get("model")
            if model_version:
                chunk_metadata["model_version"] = model_version
            if finish_reason:
                chunk_metadata["finish_reason"] = finish_reason
            tool_event_metadata = (
                {"provider_metadata": chunk_metadata} if chunk_metadata else None
            )

            for tc in tool_calls:
                tc_dict = _to_dict(tc)
                fn_dict = _to_dict(tc_dict.get("function", {}))
                index = tc_dict.get("index")
                raw_id = tc_dict.get("id") or ""

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

        # finish
        if finish_reason:
            yield AgentModelEvent(
                type="finish",
                reason=map_finish_reason(finish_reason),
            )


# ============================================================================
# 辅助函数 — 与 qwen.py 共享（这里复制一份避免循环导入）
# ============================================================================

def _to_dict(obj: Any) -> dict[str, Any]:
    """将 SDK Pydantic 对象或 dict 统一转为 dict"""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        result = model_dump()
        if isinstance(result, dict):
            return result
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return {}


def _get_nested(obj: Any, path: tuple[str, ...]) -> Any:
    """按路径获取嵌套值"""
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
