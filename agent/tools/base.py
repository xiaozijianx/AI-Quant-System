# -*- coding: utf-8 -*-
"""工具基类 — 对标 Cline AgentTool 接口

BaseTool 实现 AgentTool 协议（agent/types.py），提供:
    1. 统一的工具属性: name, description, input_schema, lifecycle
    2. 超时/重试配置: timeout_ms, retryable, max_retries
    3. to_definition() 转为 AgentToolDefinition
    4. 参数校验: _validate_required()
    5. 子类只需实现 _execute() 方法

设计要点:
    - execute(input: dict, context: AgentToolContext) 接收结构化输入
    - 返回 AgentToolResult 替代纯文本
    - 有 lifecycle 属性支持 completes_run
    - 有 timeout_ms / retryable / max_retries 属性

对标 Cline:
    - 接口定义: sdk/packages/shared/src/agent.ts L177-186
    - 工具执行: agent-runtime.ts executePreparedTool() L1464-1560
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agent.abort import AbortedError
from agent.types import (
    AgentToolContext,
    AgentToolDefinition,
    AgentToolResult,
    ToolLifecycle,
)


class BaseTool(ABC):
    """工具基类 — 对标 Cline AgentTool

    子类需实现:
        - name: 工具名称
        - description: 工具描述
        - input_schema: JSON Schema 格式的参数定义
        - _execute(): 实际执行逻辑

    可选覆盖:
        - lifecycle: 工具生命周期标记（completes_run 等）
        - timeout_ms: 超时毫秒数
        - retryable: 是否可重试
        - max_retries: 最大重试次数
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称 — 用于 LLM function calling"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述 — LLM 据此决定是否调用"""
        ...

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """输入参数的 JSON Schema"""
        ...

    @property
    def lifecycle(self) -> ToolLifecycle | None:
        """工具生命周期标记 — 默认 None"""
        return None

    @property
    def timeout_ms(self) -> int | None:
        """超时毫秒数 — None 表示由 AgentRuntime 控制"""
        return None

    @property
    def retryable(self) -> bool:
        """是否可重试"""
        return False

    @property
    def max_retries(self) -> int:
        """最大重试次数"""
        return 0

    @property
    def read_only(self) -> bool:
        """是否无副作用（可并行执行）— 对标 Cline concurrencySafe"""
        return False

    @property
    def requires_approval(self) -> bool:
        """是否需要用户审批 — Phase 19 新增，对标 Cline tool-approval

        True 时工具执行前会挂起等待用户批准（除非 auto_approve=True）。
        危险工具（file_write / run_commands / editor / apply_patch）应覆盖为 True。
        只读工具（read_files / search_codebase / list_files）保持默认 False。
        """
        return False

    async def execute(
        self,
        input: dict[str, Any],
        context: AgentToolContext,
    ) -> AgentToolResult:
        """执行工具 — 对标 Cline AgentTool.execute()

        不要覆盖此方法，覆盖 _execute() 代替。
        此方法处理参数校验和异常捕获。
        """
        # Phase 29.1: 运行时 schema 校验（含必填字段、类型、约束）
        # 失败时返回结构化错误，含字段路径便于 LLM 自我纠正
        errors = self._validate_input(input)
        if errors:
            return AgentToolResult(
                output={
                    "error": "参数 schema 校验失败",
                    "tool": self.name,
                    "validation_errors": errors,
                    "received_input": input,
                },
                is_error=True,
            )

        try:
            return await self._execute(input, context)
        except AbortedError:
            # 中止异常向上传播，由 runtime 统一处理状态
            raise
        except Exception as e:
            return AgentToolResult(
                output={"error": str(e)},
                is_error=True,
            )

    def _check_aborted(self, context: AgentToolContext) -> None:
        """检查中止信号 — Phase 28.2 新增，对标 Cline throwIfAborted

        在长 IO 操作（循环批量执行、网络请求等）的关键检查点调用。
        若 abort 被触发，立即抛出 AbortedError，让 runtime 中止运行。

        用法:
            for item in batch:
                self._check_aborted(context)
                await self._process(item)

        Args:
            context: 工具执行上下文，包含 abort_signal 字段

        Raises:
            AbortedError: 当 abort_signal 已被触发时
        """
        signal = getattr(context, "abort_signal", None)
        if signal is not None and signal.is_set():
            raise AbortedError("aborted by user")

    @abstractmethod
    async def _execute(
        self,
        input: dict[str, Any],
        context: AgentToolContext,
    ) -> AgentToolResult:
        """实际执行逻辑 — 子类实现

        Args:
            input: 工具输入参数（已校验必填项）
            context: 工具执行上下文

        Returns:
            AgentToolResult: 执行结果
        """
        ...

    def to_definition(self) -> AgentToolDefinition:
        """转为 AgentToolDefinition — 对标 Cline 工具定义序列化"""
        return AgentToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
            lifecycle=self.lifecycle,
        )

    def _validate_required(self, input: dict[str, Any]) -> list[str]:
        """校验必填参数 — 对标 Cline 参数校验

        Phase 26 增强: 错误信息附带参数说明和当前输入，帮助 LLM 自我修正，
        减少因参数漏传导致的重复失败循环。

        Phase 29.1 起: 推荐使用 _validate_input() 进行完整 schema 校验，
        本方法保留供子类按需调用，但 BaseTool.execute() 已改用 _validate_input。
        """
        errors: list[str] = []
        required = self.input_schema.get("required", [])
        properties = self.input_schema.get("properties", {})
        for field in required:
            if field not in input or input[field] is None:
                prop = properties.get(field, {})
                desc = prop.get("description", "")
                default = prop.get("default")
                hint = f"{field}"
                if desc:
                    hint += f" ({desc})"
                if default is not None:
                    hint += f"，默认: {default}"
                errors.append(f"缺少必填参数: {hint}")
        return errors

    def _validate_input(self, input: dict[str, Any]) -> list[dict[str, Any]]:
        """运行时 schema 校验 — Phase 29.1 新增，对标 Cline validateWithZod

        使用 jsonschema 库按 input_schema 校验输入参数：
            - required: 必填字段缺失
            - type: 类型不匹配（如期望 array 实际 string）
            - minItems/maxItems: 数组长度
            - minLength/maxLength: 字符串长度
            - minimum/maximum: 数值范围
            - 其他 JSON Schema 约束

        错误信息结构化，含字段路径（如 "commands[0]"）便于 LLM 自我纠正。

        Args:
            input: 工具输入参数

        Returns:
            错误信息列表，空列表表示校验通过。每项包含:
                - field: 字段路径（如 "commands[0].path" 或 "(root)"）
                - message: 人类可读的错误描述
                - validator: 失败的校验器名（type/required/minItems 等）
                - expected: 期望值（如有）
                - got: 实际值（如有，截断到 200 字符）
        """
        import jsonschema

        errors: list[dict[str, Any]] = []
        schema = self.input_schema

        # 空 schema 或无 type 的 schema 跳过校验
        if not schema or (not schema.get("type") and not schema.get("required")):
            return errors

        validator = jsonschema.Draft7Validator(schema)

        for error in validator.iter_errors(input):
            # 构建字段路径（如 "commands[0].path"）
            path_parts: list[str] = []
            for part in error.absolute_path:
                if isinstance(part, int):
                    path_parts.append(f"[{part}]")
                else:
                    if path_parts:
                        path_parts.append(f".{part}")
                    else:
                        path_parts.append(str(part))
            field_path = "".join(path_parts) or "(root)"

            error_info: dict[str, Any] = {
                "field": field_path,
                "message": error.message,
                "validator": error.validator,
            }
            if error.validator_value is not None:
                error_info["expected"] = error.validator_value
            if error.instance is not None:
                # 截断过长的实际值，避免撑爆上下文
                instance_str = repr(error.instance)
                if len(instance_str) > 200:
                    instance_str = instance_str[:200] + "..."
                error_info["got"] = instance_str
            errors.append(error_info)

        return errors

    def _get_param(
        self,
        input: dict[str, Any],
        key: str,
        default: Any = None,
    ) -> Any:
        """获取参数值，支持默认值"""
        return input.get(key, default)
