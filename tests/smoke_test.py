# -*- coding: utf-8 -*-
"""
stdio 冒烟测试：不真实调用后端，只验证 MCP 协议层与图片入参解析是否正常。

用途：在任意客户端（Trae / Qoder / WorkBuddy）接入后，先跑一遍确认
服务能启动、能握手、工具能列出、图片路径/别名/JSON 字符串等入参都能解析。

用法：
    uv run --directory <项目目录> tests/smoke_test.py
    # 或
    python tests/smoke_test.py --server D:/path/to/mcp_server.py
"""

import argparse
import asyncio
import base64
import json
import os
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DEFAULT_SERVER = str(Path(__file__).resolve().parents[1] / "mcp_server.py")

# 1x1 透明 PNG
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)


def field(obj, snake, camel):
    return getattr(obj, snake, None) or getattr(obj, camel, None)


async def call(session, tool, arguments):
    result = await session.call_tool(tool, arguments)
    return json.loads(result.content[-1].text)


def is_image_parse_error(body) -> bool:
    return "图片输入无法解析" in str(body.get("error", ""))


async def run(server_path: str) -> int:
    tmp_dir = Path(tempfile.mkdtemp(prefix="topboth-smoke-"))
    png_path = tmp_dir / "probe.png"
    png_path.write_bytes(PNG)

    params = StdioServerParameters(
        command=sys.executable,
        args=[server_path],
        env={
            **os.environ,
            # 指向一个必然连不上的地址，避免真的打到生产后端
            "IMAGE_SERVER_URL": os.environ.get("IMAGE_SERVER_URL", "http://127.0.0.1:9"),
            "MCP_API_KEY": os.environ.get("MCP_API_KEY", "smoke-test-key"),
        },
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            info = field(init, "server_info", "serverInfo")
            print(f"[ok] initialize: {info.name} {info.version}")

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print(f"[ok] tools: {names}")
            assert "burgeon_generate_image" in names and "agnes_generate_image" in names

            result = await session.call_tool("server_status", {})
            print("[ok] server_status:", result.content[0].text.replace("\n", " ")[:160])

            # 1) 不存在的路径 -> 必须返回明确错误，而不是把路径当 base64 蒙混过关
            body = await call(session, "agnes_generate_image", {"prompt": "smoke", "image_path": "C:/definitely/not/exist.png"})
            assert is_image_parse_error(body), f"预期图片解析失败: {body}"
            print("[ok] 不存在的路径:", body["details"][0])

            # 2) JSON 字符串形式的数组，同样要能识别
            body = await call(session, "burgeon_generate_image", {"prompt": "smoke", "images": '["C:/definitely/not/exist.png"]'})
            assert is_image_parse_error(body), f"预期图片解析失败: {body}"
            print("[ok] JSON 字符串数组: 已解析为 1 个路径")

            # 3) 真实存在的本地文件：应通过解析、直接打到（不可达的）后端
            body = await call(session, "agnes_generate_image", {"prompt": "smoke", "image_path": str(png_path)})
            assert not is_image_parse_error(body), f"本地图片应能读取: {body}"
            assert body.get("error"), "后端不可达时应返回错误"
            print("[ok] 本地绝对路径: 图片已读取并发出请求 ->", body["error"])

            # 4) file:/// 形式（WorkBuddy/IDE 常见的引用方式）
            body = await call(
                session,
                "agnes_generate_image",
                {"prompt": "smoke", "images": [f"file:///{png_path.as_posix().lstrip('/')}"]},
            )
            assert not is_image_parse_error(body), f"file:// 形式应能读取: {body}"
            print("[ok] file:/// 形式: 图片已读取并发出请求")

            # 5) base64 data URI
            body = await call(
                session,
                "agnes_generate_image",
                {"prompt": "smoke", "images": ["data:image/png;base64," + base64.b64encode(PNG).decode()]},
            )
            assert not is_image_parse_error(body), f"data URI 应能读取: {body}"
            print("[ok] data URI: 图片已读取并发出请求")

            # 6) 握手之后仍可正常通信 —— 证明 stdout 通道没有被日志污染
            again = await session.list_tools()
            print(f"[ok] 二次 list_tools: {len(again.tools)} tools，通道未污染")

    print("SMOKE TEST PASSED")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default=DEFAULT_SERVER, help="mcp_server.py 的绝对路径")
    args = parser.parse_args()

    try:
        return asyncio.run(run(args.server))
    except AssertionError as e:
        print(f"SMOKE TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"SMOKE TEST FAILED: {e!r}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
