"""
MCP Server for image_server.py
使用统一入口调用，隐藏内部业务接口
仅提供：Minimax视频生成、Burgeon图片生成、Agnes图片生成
"""

import asyncio
import json
import httpx
import base64
from typing import Any
from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent
import os
from dotenv import load_dotenv

load_dotenv()

app = Server("image-server-mcp")

IMAGE_SERVER_URL = os.getenv("IMAGE_SERVER_URL")
MCP_API_KEY = os.getenv("MCP_API_KEY", "")


async def call_mcp_endpoint(tool_name: str, params: dict) -> dict:
    url = f"{IMAGE_SERVER_URL}/mcp/request"
    
    headers = {}
    if MCP_API_KEY:
        headers["X-MCP-API-Key"] = MCP_API_KEY
    
    body = {
        "tool": tool_name,
        "params": params
    }
    
    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP error: {e.response.status_code}", "details": str(e)}
        except Exception as e:
            return {"error": "Request failed", "details": str(e)}


def image_path_to_base64(image_path: str) -> str | None:
    try:
        if image_path.startswith('file://'):
            image_path = image_path[7:]
        
        image_path = image_path.replace('/', '\\')
        
        if image_path.startswith('\\') and len(image_path) > 2 and image_path[2] == ':':
            image_path = image_path[1:]
        
        if not os.path.isabs(image_path):
            cwd = os.getcwd()
            image_path = os.path.join(cwd, image_path)
        
        image_path = os.path.normpath(image_path)
        
        print(f"尝试读取图片: {image_path}")
        
        if os.path.exists(image_path):
            with open(image_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        else:
            print(f"图片文件不存在: {image_path}")
            
            possible_paths = [
                os.path.join(os.path.expanduser('~'), 'Pictures', os.path.basename(image_path)),
                os.path.join(os.environ.get('TEMP', os.environ.get('TMP', '/tmp')), os.path.basename(image_path)),
                os.path.join(os.environ.get('USERPROFILE', ''), 'AppData', 'Local', 'Temp', os.path.basename(image_path)),
            ]
            
            for alt_path in possible_paths:
                if os.path.exists(alt_path):
                    print(f"在备用路径找到图片: {alt_path}")
                    with open(alt_path, 'rb') as f:
                        return base64.b64encode(f.read()).decode('utf-8')
            
            print(f"尝试搜索文件: {os.path.basename(image_path)}")
            import glob
            search_patterns = [
                f"**/{os.path.basename(image_path)}",
                f"{os.path.basename(image_path)}",
            ]
            for pattern in search_patterns:
                matches = glob.glob(pattern, recursive=True)
                if matches:
                    print(f"搜索到文件: {matches[0]}")
                    with open(matches[0], 'rb') as f:
                        return base64.b64encode(f.read()).decode('utf-8')
            
            return None
    except Exception as e:
        print(f"读取图片文件失败: {e}")
        return None


def is_base64_data(data: str) -> bool:
    if data.startswith('data:image/'):
        return True
    try:
        if len(data) % 4 == 0:
            import re
            if re.match('^[A-Za-z0-9+/]+={0,2}$', data):
                decoded = base64.b64decode(data)
                if len(decoded) > 0:
                    return True
        return False
    except:
        return False


def extract_base64_from_data_uri(data_uri: str) -> tuple[str, str]:
    if data_uri.startswith('data:image/'):
        parts = data_uri.split(',', 1)
        if len(parts) == 2:
            mime_type = parts[0].split(';')[0][5:]
            return parts[1], mime_type
    return data_uri, 'image/png'


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="burgeon_generate_image",
            description="使用Burgeon API生成图片。支持文生图和图生图。图生图时请提供images参数，可以是一张或多张图片的URL，也可以是本地文件路径（如file:///path/to/image.png），系统会自动转换。支持同时上传多张图片进行图生图操作。",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "图片生成提示词"},
                    "mode": {"type": "string", "enum": ["text-to-image", "image-to-image"], "default": "text-to-image", "description": "生成模式，默认text-to-image"},
                    "model": {"type": "string", "enum": ["burgeon-gpt-image-2"], "default": "burgeon-gpt-image-2", "description": "模型名称，默认burgeon-gpt-image-2"},
                    "modelgroup": {"type": "string", "enum": ["burgeon"], "default": "burgeon", "description": "模型组，默认burgeon"},
                    "aspect_ratio": {"type": "string", "enum": ["16:9", "1:1", "3:4"], "default": "1:1", "description": "宽高比，如'16:9', '1:1', '3:4'，默认1:1"},
                    "image_size": {"type": "string", "enum": ["1K", "2K"], "default": "1K", "description": "图片尺寸，默认1K"},
                    "images": {"type": "array", "items": {"type": "string"}, "description": "输入图片的URL或本地文件路径列表（支持多张图片），用于image-to-image模式，例如：['https://example.com/img1.png', 'file:///path/to/img2.png']"},
                },
                "required": ["prompt"],
            },
        ),
        Tool(
            name="agnes_generate_image",
            description="使用Agnes API生成图片。支持文生图和图生图。图生图时请提供images参数，可以是一张或多张图片的URL，也可以是本地文件路径（如file:///path/to/image.png），系统会自动转换。支持同时上传多张图片进行图生图操作。",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "图片生成提示词"},
                    "mode": {"type": "string", "enum": ["text-to-image", "image-to-image"], "default": "text-to-image", "description": "生成模式，默认text-to-image"},
                    "model": {"type": "string", "enum": ["agnes-image-2.1-flash"], "default": "agnes-image-2.1-flash", "description": "模型名称，默认agnes-image-2.1-flash"},
                    "modelgroup": {"type": "string", "enum": ["agnes"], "default": "agnes", "description": "模型组，默认agnes"},
                    "aspect_ratio": {"type": "string", "enum": ["16:9", "1:1", "3:4"], "default": "1:1", "description": "宽高比，如'16:9', '1:1', '3:4'，默认1:1"},
                    "image_size": {"type": "string", "enum": ["1K"], "default": "1K", "description": "图片尺寸，只能是1K"},
                    "n": {"type": "integer", "default": 1, "description": "生成图片数量，默认1"},
                    "images": {"type": "array", "items": {"type": "string"}, "description": "输入图片的URL或本地文件路径列表（支持多张图片），用于image-to-image模式，例如：['https://example.com/img1.png', 'file:///path/to/img2.png']"},
                },
                "required": ["prompt"],
            },
        ),
    ]


async def download_image_bytes(image_url: str) -> bytes | None:
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(image_url)
            response.raise_for_status()
            return response.content
    except Exception as e:
        print(f"下载图片失败: {e}")
        return None


def download_image_sync(image_url: str) -> bytes | None:
    try:
        import requests
        response = requests.get(image_url, timeout=60)
        response.raise_for_status()
        return response.content
    except Exception as e:
        print(f"同步下载图片失败: {e}")
        return None


def process_images_input(images_input: list) -> list:
    images_data = []
    print(f"收到图片输入: {len(images_input)} 张")
    
    for idx, img_input in enumerate(images_input):
        print(f"处理第 {idx+1} 张图片: {type(img_input).__name__}, 长度: {len(str(img_input)) if img_input else 0}")
        
        if not img_input:
            print(f"第 {idx+1} 张图片为空，跳过")
            continue
        
        img_str = str(img_input)
        
        if img_str.startswith('http://') or img_str.startswith('https://'):
            print(f"第 {idx+1} 张图片是HTTP URL")
            image_bytes = download_image_sync(img_str)
            if image_bytes:
                base64_data = base64.b64encode(image_bytes).decode('utf-8')
                mime_type = 'image/jpeg' if img_str.lower().endswith('.jpg') or img_str.lower().endswith('.jpeg') else 'image/png'
                images_data.append({
                    "data": base64_data,
                    "mimeType": mime_type
                })
                print(f"第 {idx+1} 张图片下载成功，大小: {len(base64_data)} 字节")
            else:
                print(f"无法下载图片: {img_str}")
        elif img_str.startswith('file://') or os.path.isfile(img_str) or os.path.isfile(img_str.replace('file://', '')):
            print(f"第 {idx+1} 张图片是文件路径")
            base64_data = image_path_to_base64(img_str)
            if base64_data:
                mime_type = 'image/png'
                if img_str.lower().endswith('.jpg') or img_str.lower().endswith('.jpeg'):
                    mime_type = 'image/jpeg'
                elif img_str.lower().endswith('.webp'):
                    mime_type = 'image/webp'
                images_data.append({
                    "data": base64_data,
                    "mimeType": mime_type
                })
                print(f"第 {idx+1} 张图片读取成功，大小: {len(base64_data)} 字节")
            else:
                print(f"无法读取图片文件: {img_str}")
        elif is_base64_data(img_str):
            print(f"第 {idx+1} 张图片是Base64数据")
            base64_data, mime_type = extract_base64_from_data_uri(img_str)
            images_data.append({
                "data": base64_data,
                "mimeType": mime_type
            })
            print(f"第 {idx+1} 张图片Base64解析成功")
        else:
            print(f"第 {idx+1} 张图片格式未知，直接作为Base64处理")
            images_data.append({
                "data": img_str,
                "mimeType": "image/png"
            })
    
    print(f"最终处理完成: {len(images_data)} 张图片")
    return images_data


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent | ImageContent]:
    try:
        if name == "burgeon_generate_image":
            config = {}
            image_config = {}
            
            if arguments.get("aspect_ratio"):
                image_config["aspectRatio"] = arguments.get("aspect_ratio")
            else:
                image_config["aspectRatio"] = "1:1"
                
            if arguments.get("image_size"):
                image_config["imageSize"] = arguments.get("image_size")
            else:
                image_config["imageSize"] = "1K"
            
            if image_config:
                config["imageConfig"] = image_config

            images_input = arguments.get("images", [])
            images_data = process_images_input(images_input)

            data = {
                "mode": arguments.get("mode", "text-to-image"),
                "prompt": arguments.get("prompt"),
                "model": arguments.get("model"),
                "modelgroup": arguments.get("modelgroup", "burgeon"),
                "config": config,
                "images": images_data,
            }
            result = await call_mcp_endpoint("burgeon_generate_image", data)

        elif name == "agnes_generate_image":
            config = {}
            image_config = {}
            
            if arguments.get("aspect_ratio"):
                image_config["aspectRatio"] = arguments.get("aspect_ratio")
            else:
                image_config["aspectRatio"] = "1:1"

            if arguments.get("image_size"):
                image_config["imageSize"] = arguments.get("image_size")
            else:
                image_config["imageSize"] = "1K"
            
            if image_config:
                config["imageConfig"] = image_config

            images_input = arguments.get("images", [])
            images_data = process_images_input(images_input)

            data = {
                "mode": arguments.get("mode", "text-to-image"),
                "prompt": arguments.get("prompt"),
                "model": arguments.get("model"),
                "modelgroup": arguments.get("modelgroup", "agnes"),
                "config": config,
                "images": images_data,
                "n": arguments.get("n", 1),
            }
            result = await call_mcp_endpoint("agnes_generate_image", data)

        else:
            result = {"error": f"Unknown tool: {name}"}

        response_content: list[TextContent | ImageContent] = []
        
        if result.get("success") and result.get("data"):
            image_url = result["data"].get("url")
            if image_url:
                image_bytes = await download_image_bytes(image_url)
                if image_bytes:
                    mimeType = "image/jpeg" if image_url.lower().endswith(".jpg") or image_url.lower().endswith(".jpeg") else "image/png"
                    image_base64 = base64.b64encode(image_bytes).decode("utf-8")
                    response_content.append(ImageContent(type="image", data=image_base64, mimeType=mimeType))
        
        response_content.append(TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2)))
        
        return response_content

    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}, ensure_ascii=False, indent=2))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="image-server-mcp",
                server_version="2.0.0",
                capabilities=app.get_capabilities(
                    notification_options=NotificationOptions(tools_changed=False),
                    experimental_capabilities=None,
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
