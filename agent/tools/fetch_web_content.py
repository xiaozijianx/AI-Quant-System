# -*- coding: utf-8 -*-
"""URL 抓取工具 — 对标 Cline createWebFetchTool

抓取 URL 内容并用 prompt 分析。支持批量请求。
使用 urllib.request（标准库，不依赖 requests）抓取内容。

工作流程:
    1. LLM 调用 fetch_web_content(requests=[{url, prompt}, ...])
    2. 工具对每个 request 用 urllib.request 抓取 URL 内容
    3. 根据 Content-Type 区分处理: HTML 转纯文本 / JSON 格式化 / 其他原样
    4. 截断到 50000 字符
    5. 返回 {results: [{url, content, prompt, chars}]}

安全设计:
    - 使用 urllib.request（标准库，避免依赖 requests）
    - 设置 User-Agent 模拟浏览器
    - 30 秒超时
    - 流式读取响应体，超过 5MB 中止（防止大响应撑爆内存）
    - 单次内容截断到 50000 字符

对标 Cline:
    - sdk/packages/core/src/extensions/tools/web-fetch-tool.ts
"""

from __future__ import annotations

import asyncio
import json
import re
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any

from agent.tools.base import BaseTool
from agent.tools.constants import MAX_WEB_CONTENT_CHARS
from agent.types import AgentToolContext, AgentToolResult


class _HTMLToTextParser(HTMLParser):
    """简单的 HTML 转纯文本解析器

    去除 HTML 标签，保留文本内容，处理常见标签的换行。
    """

    # 需要在标签前换行的块级元素
    _BLOCK_TAGS = {
        "p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6",
        "li", "tr", "table", "section", "article", "header", "footer",
    }

    # 需要跳过的标签（script/style 内容不显示）
    _SKIP_TAGS = {"script", "style", "noscript", "head"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS and self._parts:
            # 块级元素前加换行
            if not self._parts[-1].endswith("\n"):
                self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in self._BLOCK_TAGS and self._parts:
            # 块级元素后加换行
            if not self._parts[-1].endswith("\n"):
                self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        """获取纯文本结果"""
        text = "".join(self._parts)
        # 压缩多余空白
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


class FetchWebContentTool(BaseTool):
    """URL 抓取工具 — 对标 Cline createWebFetchTool

    参数:
        requests: 数组（必填），每项含:
            - url: 要抓取的 URL（必填）
            - prompt: 分析提示（必填，至少 2 字符）
    """

    # Phase 31.5: 常量统一到 agent.tools.constants — 对标 Cline output-limits.ts
    # 保留类属性作为向后兼容别名，值来自 constants 模块
    _MAX_CONTENT_CHARS = MAX_WEB_CONTENT_CHARS

    # 响应体最大字节数 — 对标 Cline web-fetch.ts maxResponseBytes=5_000_000
    # 流式读取时累计检查，超过则中止，防止大响应撑爆内存
    _MAX_RESPONSE_BYTES = 5_000_000

    # 请求超时秒数
    _REQUEST_TIMEOUT = 30

    # 模拟浏览器的 User-Agent
    _USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    @property
    def name(self) -> str:
        return "fetch_web_content"

    @property
    def description(self) -> str:
        return (
            "抓取 URL 内容并用 prompt 分析。"
            "参数: requests(必填): 数组，每项含 url(必填)/prompt(必填，分析提示)"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "requests": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "要抓取的 URL",
                            },
                            "prompt": {
                                "type": "string",
                                "minLength": 2,
                                "description": "分析提示（告诉工具如何处理抓取的内容）",
                            },
                        },
                        "required": ["url", "prompt"],
                    },
                    "description": "URL 抓取请求数组",
                },
            },
            "required": ["requests"],
        }

    @property
    def read_only(self) -> bool:
        return True

    @property
    def timeout_ms(self) -> int | None:
        """Phase 29.2: URL 抓取 60 秒超时（批量场景）"""
        return 60_000

    @property
    def retryable(self) -> bool:
        """Phase 29.2: 网络请求可重试（瞬时网络故障可恢复）"""
        return True

    @property
    def max_retries(self) -> int:
        """Phase 29.2: 最多重试 2 次"""
        return 2

    async def _execute(
        self,
        input: dict[str, Any],
        context: AgentToolContext,
    ) -> AgentToolResult:
        """执行 URL 抓取 — 对标 Cline createWebFetchTool.execute()"""
        requests = input.get("requests", [])

        if not requests:
            return AgentToolResult(
                output={"error": "requests 不能为空"},
                is_error=True,
            )

        results: list[dict[str, Any]] = []
        for idx, req in enumerate(requests):
            # Phase 28.2: 每个 URL 抓取前检查中止信号
            self._check_aborted(context)
            result_item = await self._fetch_single(req, idx)
            results.append(result_item)

        succeeded = sum(1 for r in results if "error" not in r)
        failed = sum(1 for r in results if "error" in r)

        return AgentToolResult(
            output={"results": results},
            metadata={
                "total_requests": len(requests),
                "succeeded": succeeded,
                "failed": failed,
            },
        )

    async def _fetch_single(self, req: dict[str, Any], index: int) -> dict[str, Any]:
        """抓取单个 URL

        使用 asyncio.to_thread 在线程池中执行同步的 urllib 请求。
        """
        url = req.get("url", "")
        prompt = req.get("prompt", "")

        if not url:
            return {
                "index": index,
                "url": "",
                "error": "url 不能为空",
            }

        if not prompt or len(prompt) < 2:
            return {
                "index": index,
                "url": url,
                "error": "prompt 不能为空且至少 2 字符",
            }

        try:
            # 在线程池中执行同步的 HTTP 请求，返回文本和 Content-Type
            raw_content, content_type = await asyncio.to_thread(self._http_get, url)
            # 根据 Content-Type 区分处理 — 对标 Cline web-fetch.ts L207-222
            if "application/json" in content_type:
                # JSON 响应：解析并格式化输出
                text_content = json.dumps(
                    json.loads(raw_content), indent=2, ensure_ascii=False
                )
            elif "text/html" in content_type or "application/xhtml" in content_type:
                # HTML 响应：转为纯文本
                text_content = self._html_to_text(raw_content)
            else:
                # 其他类型：原样返回
                text_content = raw_content
            # 截断到最大字符数
            truncated = False
            chars = len(text_content)
            if chars > self._MAX_CONTENT_CHARS:
                text_content = text_content[:self._MAX_CONTENT_CHARS]
                truncated = True
                chars = self._MAX_CONTENT_CHARS

            result: dict[str, Any] = {
                "index": index,
                "url": url,
                "content": text_content,
                "prompt": prompt,
                "chars": chars,
            }

            if truncated:
                result["truncated"] = True
                result["note"] = f"内容已截断到 {self._MAX_CONTENT_CHARS} 字符"

            return result

        except urllib.error.HTTPError as e:
            return {
                "index": index,
                "url": url,
                "error": f"HTTP 错误: {e.code} {e.reason}",
            }
        except urllib.error.URLError as e:
            return {
                "index": index,
                "url": url,
                "error": f"URL 错误: {e.reason}",
            }
        except Exception as e:
            return {
                "index": index,
                "url": url,
                "error": f"抓取失败: {e}",
            }

    def _http_get(self, url: str) -> tuple[str, str]:
        """同步 HTTP GET 请求 — 使用 urllib.request

        设置 User-Agent 和超时，返回响应文本和 Content-Type。
        流式读取响应体，超过 _MAX_RESPONSE_BYTES 时中止。
        """
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self._USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        with urllib.request.urlopen(request, timeout=self._REQUEST_TIMEOUT) as response:
            content_type = response.headers.get("Content-Type", "")
            # 流式读取响应体，累计检查总大小 — 对标 Cline web-fetch.ts L177-193
            raw_bytes = bytearray()
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                raw_bytes.extend(chunk)
                if len(raw_bytes) > self._MAX_RESPONSE_BYTES:
                    raise ValueError(
                        f"响应过大: 超过 {self._MAX_RESPONSE_BYTES} 字节"
                    )
            # 尝试从响应头获取编码，默认 UTF-8
            encoding = "utf-8"
            if "charset=" in content_type:
                charset_part = content_type.split("charset=")[-1].split(";")[0].strip()
                if charset_part:
                    encoding = charset_part
            try:
                return raw_bytes.decode(encoding, errors="replace"), content_type
            except (LookupError, UnicodeDecodeError):
                return raw_bytes.decode("utf-8", errors="replace"), content_type

    def _html_to_text(self, html: str) -> str:
        """将 HTML 转为纯文本 — 使用 html.parser

        去除标签，保留文本内容，压缩多余空白。
        """
        parser = _HTMLToTextParser()
        try:
            parser.feed(html)
            parser.close()
            return parser.get_text()
        except Exception:
            # 解析失败时用正则简单去除标签
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text)
            return text.strip()
