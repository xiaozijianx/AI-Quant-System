# -*- coding: utf-8 -*-
"""Provider 专用错误类型 — P2-20 新增，对标 Cline provider 错误层级

为 LLM provider 适配层定义专用的异常层级，便于上层（runtime / server / hooks）
按错误类型做差异化处理（重试策略、用户提示、降级等），替代此前统一用
RuntimeError / ValueError 表达 provider 错误的做法。

错误层级:
    ProviderError                  — 所有 provider 错误的基类
    ├── ProviderAuthError          — 认证失败（API Key 无效/过期/权限不足）
    ├── ProviderRateLimitError     — 触发限流（429），建议退避重试
    ├── ProviderTimeoutError       — 请求超时（网络/服务端阻塞）
    └── ProviderInvalidRequestError— 请求参数非法（400，如 model 不存在/超长）

用法:
    from agent.providers.errors import ProviderAuthError, ProviderRateLimitError

    try:
        async for event in model.stream(request):
            ...
    except ProviderAuthError as e:
        # 认证失败：提示用户检查 API Key，不重试
        ...
    except ProviderRateLimitError as e:
        # 限流：按 retry_after 退避后重试
        ...
    except ProviderTimeoutError as e:
        # 超时：可重试，记录告警
        ...
    except ProviderInvalidRequestError as e:
        # 参数非法：不重试，提示用户调整请求
        ...
    except ProviderError as e:
        # 其他 provider 错误：兜底处理
        ...

对标 Cline:
    - sdk/packages/core/src/services/llms/ 下的 provider 错误分类
    - Cline 按错误类型决定重试策略（auth 不重试 / rate-limit 退避重试）
"""

from __future__ import annotations


class ProviderError(Exception):
    """Provider 错误基类 — 所有 provider 适配层异常的父类

    Attributes:
        provider_id: 出错的 provider 标识（如 "qwen" / "openai"），便于日志追踪
        request_id: 关联的请求 ID（若 provider 返回），便于关联上游日志
    """

    def __init__(
        self,
        message: str = "",
        *,
        provider_id: str = "",
        request_id: str = "",
    ) -> None:
        self.provider_id = provider_id
        self.request_id = request_id
        super().__init__(message or "provider error")


class ProviderAuthError(ProviderError):
    """认证失败错误 — API Key 无效/过期/权限不足

    对应 HTTP 401/403。不可重试，应提示用户检查 API Key 配置。
    """

    def __init__(self, message: str = "", **kwargs) -> None:
        super().__init__(message or "provider auth failed", **kwargs)


class ProviderRateLimitError(ProviderError):
    """限流错误 — 触发 provider 速率限制

    对应 HTTP 429。可按 retry_after 退避后重试。

    Attributes:
        retry_after: 建议的重试等待秒数（provider 返回，无值时为 None）
    """

    def __init__(
        self,
        message: str = "",
        *,
        retry_after: float | None = None,
        **kwargs,
    ) -> None:
        self.retry_after = retry_after
        super().__init__(message or "provider rate limit exceeded", **kwargs)


class ProviderTimeoutError(ProviderError):
    """请求超时错误 — 网络超时或服务端长时间无响应

    可重试，但应记录告警便于排查偶发性超时。
    """

    def __init__(self, message: str = "", **kwargs) -> None:
        super().__init__(message or "provider request timed out", **kwargs)


class ProviderInvalidRequestError(ProviderError):
    """非法请求错误 — 请求参数被 provider 拒绝

    对应 HTTP 400。如 model 不存在、prompt 超长、tools 格式错误等。
    不可重试，应提示用户调整请求参数。
    """

    def __init__(self, message: str = "", **kwargs) -> None:
        super().__init__(message or "provider invalid request", **kwargs)


def classify_openai_error(e: Exception, *, provider_id: str = "") -> Exception:
    """将 OpenAI SDK 异常映射到 ProviderError 层级 — P2-20 新增

    保留原始异常信息，仅添加类型分类便于上层（runtime/hooks）按错误类型
    做差异化处理（重试策略、用户提示、降级等）。

    未安装 openai 库或异常类型不匹配时，返回原始异常（向后兼容）。

    Args:
        e: 捕获到的异常（通常是 OpenAI SDK 抛出）
        provider_id: provider 标识，附加到 ProviderError 便于日志追踪

    Returns:
        映射后的 ProviderError 子类实例，或原始异常（无法分类时）
    """
    try:
        import openai
    except ImportError:
        return e

    if isinstance(e, openai.AuthenticationError):
        return ProviderAuthError(str(e), provider_id=provider_id)
    if isinstance(e, openai.RateLimitError):
        return ProviderRateLimitError(str(e), provider_id=provider_id)
    if isinstance(e, openai.APITimeoutError):
        return ProviderTimeoutError(str(e), provider_id=provider_id)
    if isinstance(e, openai.BadRequestError):
        return ProviderInvalidRequestError(str(e), provider_id=provider_id)
    if isinstance(e, openai.APIConnectionError):
        return ProviderError(str(e), provider_id=provider_id)
    return e
