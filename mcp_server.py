# -*- coding: utf-8 -*-
"""
MCP Server for image_server.py

统一入口调用，隐藏内部业务接口。
对外暴露工具：
  - topboth_generate_image / test_generate_image : 文生图 / 图生图
  - server_status                                  : 自检，排查各客户端的接入问题

多客户端兼容说明（Trae / Qoder / WorkBuddy / Claude 等）：
  1. 兼容两代 MCP Python SDK：
       - 1.x：Server + @app.list_tools() / @app.call_tool() 装饰器 API
       - 2.x：Server(on_list_tools=..., on_call_tool=...) 构造器 API
     2.x 已经删除了装饰器 API，直接用老写法会在启动时抛
     AttributeError: 'Server' object has no attribute 'list_tools'，
     导致客户端表现为"连接关闭 / 无法连接"。
  2. 日志全部走 stderr。stdio 传输下 stdout 是 JSON-RPC 通道，任何 print 都可能
     污染协议流（旧版 SDK 不会重定向 fd 1），因此本文件不使用 print。
  3. 不依赖进程工作目录(cwd)。WorkBuddy 不会像 IDE 那样注入 cwd，
     所以 .env、脚本目录、输出目录全部基于脚本所在目录或绝对路径解析。
  4. 输入图片参数做宽容解析：字符串 / 数组 / JSON 字符串 / 各客户端的不同字段名均可。
  5. 生成结果除返回图片内容外，同时落盘并回传本地绝对路径，
     方便 WorkBuddy 这类 Agent 客户端把图片作为产物直接交付给用户。
  6. 强制 UTF-8 控制台输出，避免 Windows 下中文日志乱码或 UnicodeEncodeError。
"""

import asyncio
import base64
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
import mcp.types as mcp_types
from dotenv import load_dotenv
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import ImageContent, TextContent, Tool

SERVER_NAME = "image-server-mcp"
SERVER_VERSION = "2.2.0"

# --------------------------------------------------------------------------- #
# 基础设施
# --------------------------------------------------------------------------- #

BASE_DIR = Path(__file__).resolve().parent


def _force_utf8_console() -> None:
    """Windows 控制台默认 cp936，强制 UTF-8 避免中文日志报错。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_force_utf8_console()


def log(*args: Any) -> None:
    """统一日志出口：stderr。stdio 传输下 stdout 只能用于 JSON-RPC。"""
    try:
        print(f"[{SERVER_NAME}]", *args, file=sys.stderr, flush=True)
    except Exception:
        pass


# .env 优先取脚本目录（不依赖 cwd），再兜底当前目录
load_dotenv(BASE_DIR / ".env", override=False)
load_dotenv(override=False)

IMAGE_SERVER_URL = (os.getenv("IMAGE_SERVER_URL") or "").strip().rstrip("/")
MCP_API_KEY = os.getenv("MCP_API_KEY", "") or ""
MCP_API_KEY_HEADER = os.getenv("MCP_API_KEY_HEADER", "X-MCP-API-Key") or "X-MCP-API-Key"
IMAGE_OUTPUT_DIR = (os.getenv("IMAGE_OUTPUT_DIR") or "").strip()
DEFAULT_OUTPUT_DIRNAME = "generated_images"

try:
    HTTP_TIMEOUT = float(os.getenv("MCP_HTTP_TIMEOUT", "300"))
except ValueError:
    HTTP_TIMEOUT = 300.0

BUERGEON_MODEL = "拓全智能图片V2"
AGNES_MODEL = "agnes-image-2.5-flash"

# 生成图片落盘时识别扩展名用的魔数
_MAGIC_MIME = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),
    (b"BM", "image/bmp"),
)

_EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}


def sniff_mime(data: bytes) -> str | None:
    """按文件头判断图片类型，避免把非图片数据误当成图片。"""
    if not data:
        return None
    for magic, mime in _MAGIC_MIME:
        if data.startswith(magic):
            return mime
    return None


def guess_mime(name_or_url: str) -> str:
    lowered = (name_or_url or "").lower().split("?")[0]
    if lowered.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lowered.endswith((".webp",)):
        return "image/webp"
    if lowered.endswith((".gif",)):
        return "image/gif"
    if lowered.endswith((".bmp",)):
        return "image/bmp"
    return "image/png"


# --------------------------------------------------------------------------- #
# 后端调用
# --------------------------------------------------------------------------- #

async def call_mcp_endpoint(tool_name: str, params: dict) -> dict:
    if not IMAGE_SERVER_URL:
        return {
            "error": "IMAGE_SERVER_URL 未配置",
            "details": (
                "请在 MCP 客户端的 env 配置或项目根目录 .env 中设置 IMAGE_SERVER_URL，"
                "例如 http://aiphoto.topboth.com"
            ),
        }

    url = f"{IMAGE_SERVER_URL}/mcp/request"

    headers = {"Content-Type": "application/json"}
    if MCP_API_KEY:
        headers[MCP_API_KEY_HEADER] = MCP_API_KEY

    body = {"tool": tool_name, "params": params}

    log(
        f"调用后端 tool={tool_name} url={url} "
        f"images={len(params.get('images') or [])} "
        f"api_key={'已配置' if MCP_API_KEY else '未配置'}"
    )

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        try:
            response = await client.post(url, json=body, headers=headers)
            if response.status_code >= 400:
                return {
                    "error": f"HTTP error: {response.status_code}",
                    "details": response.text[:2000],
                }
            return response.json()
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP error: {e.response.status_code}", "details": str(e)}
        except Exception as e:
            return {"error": "Request failed", "details": str(e)}


# --------------------------------------------------------------------------- #
# 输入图片处理（路径解析 / 下载 / base64）
# --------------------------------------------------------------------------- #

def clean_path_string(raw: Any) -> str:
    """把各客户端给出的路径写法归一化成可用的本地路径字符串。"""
    s = str(raw or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        s = s[1:-1]

    s = unquote(s)

    if s.lower().startswith("file://"):
        s = s[7:]
    # Windows 盘符前多余斜杠：/C:/x -> C:/x
    s = re.sub(r"^/+([A-Za-z]:[/\\])", r"\1", s)

    if os.name == "nt" and s.startswith("\\\\?\\"):
        s = s[4:]

    s = os.path.expandvars(os.path.expanduser(s))
    return s


def workbuddy_search_dirs() -> list[Path]:
    """WorkBuddy 相关目录：用户上传的素材、插件脚本产物常落在这些位置。"""
    dirs: list[Path] = []
    wb_home = Path.home() / ".workbuddy"
    for sub in ("media-index", "artifact-index", "uploads", "attachments"):
        candidate = wb_home / sub
        if candidate.is_dir():
            dirs.append(candidate)
    temp = Path(os.environ.get("TEMP") or os.environ.get("TMP") or "")
    if temp.is_dir():
        try:
            dirs.extend(sorted(p for p in temp.glob("workbuddy*") if p.is_dir()))
        except OSError:
            pass
    return dirs


def locate_image_file(raw: Any) -> Path | None:
    """尽力把一个路径字符串定位到真实存在的文件（不依赖 cwd）。"""
    cleaned = clean_path_string(raw)
    if not cleaned:
        return None

    p = Path(cleaned)
    if p.is_file():
        return p.resolve()

    if not p.is_absolute():
        for base in (Path.cwd(), BASE_DIR, Path.home()):
            candidate = base / cleaned
            try:
                if candidate.is_file():
                    return candidate.resolve()
            except OSError:
                continue

    name = p.name
    if not name or any(ch in name for ch in "*?[]"):
        return None

    search_dirs = [
        Path.cwd(),
        BASE_DIR,
        Path.home() / "Pictures",
        Path.home() / "Downloads",
        Path(os.environ.get("TEMP") or os.environ.get("TMP") or Path.home()),
        Path(os.environ.get("USERPROFILE") or Path.home()) / "AppData" / "Local" / "Temp",
        *workbuddy_search_dirs(),
    ]
    for directory in search_dirs:
        try:
            candidate = directory / name
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue

    # 最后在受限范围内递归查找（只搜 cwd、脚本目录与 WorkBuddy 素材目录，避免扫全盘）
    for directory in (Path.cwd(), BASE_DIR, *workbuddy_search_dirs()):
        try:
            for match in directory.rglob(name):
                if match.is_file():
                    return match.resolve()
        except (OSError, ValueError):
            continue

    return None


def read_image_as_base64(path: Path) -> dict | None:
    try:
        data = path.read_bytes()
    except OSError as e:
        log(f"读取图片失败 {path}: {e}")
        return None
    if not data:
        return None
    return {
        "data": base64.b64encode(data).decode("utf-8"),
        "mimeType": sniff_mime(data) or (guess_mime(path.name) if path.suffix else "image/png"),
    }


def download_image_sync(image_url: str) -> bytes | None:
    """同步下载（统一用 httpx，避免依赖未声明的 requests）。"""
    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            response = client.get(image_url)
            response.raise_for_status()
            return response.content
    except Exception as e:
        log(f"同步下载图片失败: {e}")
        return None


async def download_image_bytes(image_url: str) -> bytes | None:
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(image_url)
            response.raise_for_status()
            return response.content
    except Exception as e:
        log(f"下载图片失败: {e}")
        return None


def is_base64_data(data: str) -> bool:
    """判断是否为 base64 图片数据（data URI 或裸 base64）。"""
    if data.startswith("data:image/"):
        return True
    if len(data) < 512 or len(data) % 4 != 0:
        return False
    if not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", data):
        return False
    try:
        decoded = base64.b64decode(data, validate=True)
    except Exception:
        return False
    # 能识别魔数最好；识别不了（如 heic/avif）时，长度足够且能解码也按图片处理
    return True


_PATH_EXT_RE = re.compile(r"\.(png|jpe?g|webp|gif|bmp|tiff?|heic|heif|avif)$", re.IGNORECASE)


def looks_like_path(s: str) -> bool:
    """判断一段字符串像不像本地文件路径，而不是 URL / base64 / 其它文本。"""
    if not s or s.startswith(("http://", "https://", "data:")):
        return False
    if re.match(r"^[A-Za-z]:[/\\]", s):
        return True
    if s.startswith(("file://", "/", "\\", "~", "./", "../", ".\\", "..\\")):
        return True
    if any(sep in s for sep in ("/", "\\")):
        return True
    # 纯文件名 + 图片后缀 / UNC 路径
    return bool(_PATH_EXT_RE.search(s)) or s.startswith("\\\\")


def extract_base64_from_data_uri(data_uri: str) -> tuple[str, str]:
    if data_uri.startswith("data:image/"):
        parts = data_uri.split(",", 1)
        if len(parts) == 2:
            mime_type = parts[0].split(";")[0][5:]
            return parts[1], mime_type or "image/png"
    return data_uri, "image/png"


# 不同客户端 / 模型可能用不同的字段名传图，这里全部兼容
IMAGE_ARG_KEYS = (
    "images",
    "image",
    "image_paths",
    "image_path",
    "input_images",
    "image_urls",
    "image_url",
    "files",
    "attachments",
)


def _flatten_image_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            out.extend(_flatten_image_value(item))
        return out
    if isinstance(value, dict):
        for key in ("path", "file_path", "filepath", "url", "image_url", "data", "content", "source"):
            if key in value and value[key]:
                return _flatten_image_value(value[key])
        return []
    s = str(value).strip()
    if not s:
        return []
    if s[0] in "[{" and s[-1] in "]}":
        try:
            parsed = json.loads(s)
        except Exception:
            parsed = None
        if parsed is not None and not isinstance(parsed, str):
            return _flatten_image_value(parsed)
    return [s]


def normalize_images_argument(arguments: dict) -> list[str]:
    """从工具参数里收集所有图片输入，兼容字符串/数组/JSON 字符串/字段别名。"""
    collected: list[str] = []
    for key in IMAGE_ARG_KEYS:
        if key in arguments:
            for item in _flatten_image_value(arguments.get(key)):
                if item not in collected:
                    collected.append(item)
    return collected


def process_images_input(images_input: Any) -> tuple[list[dict], list[str]]:
    """把各种形态的图片输入转换成后端需要的 [{data, mimeType}]。

    返回 (成功列表, 错误说明列表)。无法定位/无法识别的输入不会被伪装成 base64
    传给后端，而是以明确错误返回，便于定位"图片没传进来"这类问题。
    """
    raw_items = _flatten_image_value(images_input)
    log(f"收到图片输入: {len(raw_items)} 张")

    images_data: list[dict] = []
    errors: list[str] = []

    for idx, raw in enumerate(raw_items, 1):
        s = str(raw).strip()
        if not s:
            errors.append(f"第 {idx} 张图片为空")
            continue

        if s.startswith("http://") or s.startswith("https://"):
            image_bytes = download_image_sync(s)
            if image_bytes:
                images_data.append(
                    {
                        "data": base64.b64encode(image_bytes).decode("utf-8"),
                        "mimeType": sniff_mime(image_bytes) or guess_mime(s),
                    }
                )
                log(f"第 {idx} 张：URL 下载成功 ({len(image_bytes)} bytes)")
            else:
                errors.append(f"第 {idx} 张：URL 下载失败 {s[:120]}")
                log(f"第 {idx} 张：URL 下载失败 {s[:120]}")
            continue

        if s.startswith("data:image/"):
            data, mime = extract_base64_from_data_uri(s)
            images_data.append({"data": data, "mimeType": mime})
            log(f"第 {idx} 张：data URI 解析成功")
            continue

        if looks_like_path(s):
            local_file = locate_image_file(s)
            if local_file:
                item = read_image_as_base64(local_file)
                if item:
                    images_data.append(item)
                    log(f"第 {idx} 张：读取本地文件成功 {local_file}")
                    continue
                errors.append(f"第 {idx} 张：读取失败 {local_file}")
                continue
            errors.append(f"第 {idx} 张：本地文件不存在或不可读 {s[:160]}")
            log(f"第 {idx} 张：本地文件不存在 {s[:160]}")
            continue

        if is_base64_data(s):
            data, mime = extract_base64_from_data_uri(s)
            images_data.append({"data": data, "mimeType": mime})
            log(f"第 {idx} 张：Base64 解析成功")
            continue

        errors.append(f"第 {idx} 张：无法识别为图片路径 / URL / base64（前 80 字符：{s[:80]}）")
        log(f"第 {idx} 张：无法识别来源（前 80 字符：{s[:80]}）")

    log(f"最终处理完成: {len(images_data)} 张图片，{len(errors)} 个错误")
    return images_data, errors


# --------------------------------------------------------------------------- #
# 输出图片落盘（WorkBuddy 等 Agent 客户端需要本地文件路径）
# --------------------------------------------------------------------------- #

def resolve_output_dir(output_dir: str | None) -> Path:
    raw = (output_dir or "").strip() or IMAGE_OUTPUT_DIR or str(Path.cwd() / DEFAULT_OUTPUT_DIRNAME)
    path = Path(os.path.expandvars(os.path.expanduser(raw)))
    if not path.is_absolute():
        path = Path.cwd() / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_generated_image(
    image_bytes: bytes,
    image_url: str,
    output_dir: str | None,
    filename: str | None,
    name_hint: str,
) -> str | None:
    try:
        target_dir = resolve_output_dir(output_dir)
    except OSError as e:
        log(f"创建输出目录失败: {e}")
        return None

    mime = sniff_mime(image_bytes) or guess_mime(image_url)
    ext = Path(unquote(image_url.split("?")[0])).suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
        ext = _EXT_BY_MIME.get(mime, ".png")

    if filename:
        name = Path(str(filename)).name
        if not Path(name).suffix:
            name += ext
    else:
        name = f"{time.strftime('%Y%m%d_%H%M%S')}_{name_hint}{ext}"

    target = target_dir / name
    counter = 1
    while target.exists():
        target = target_dir / f"{Path(name).stem}_{counter}{Path(name).suffix}"
        counter += 1

    try:
        target.write_bytes(image_bytes)
    except OSError as e:
        log(f"写入图片失败 {target}: {e}")
        return None

    log(f"图片已保存: {target}")
    return str(target.resolve())


def extract_image_urls(result: dict) -> list[str]:
    """兼容后端可能返回 url / urls / images 等不同结构。"""
    data = result.get("data")
    if not isinstance(data, dict):
        return []
    urls: list[str] = []
    for key in ("url", "image_url", "imageUrl"):
        value = data.get(key)
        if isinstance(value, str) and value.startswith("http"):
            urls.append(value)
    for key in ("urls", "images", "image_urls"):
        value = data.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.startswith("http"):
                    urls.append(item)
                elif isinstance(item, dict):
                    inner = item.get("url") or item.get("image_url")
                    if isinstance(inner, str) and inner.startswith("http"):
                        urls.append(inner)
    seen: list[str] = []
    for url in urls:
        if url not in seen:
            seen.append(url)
    return seen


# --------------------------------------------------------------------------- #
# 工具定义
# --------------------------------------------------------------------------- #

IMAGES_SCHEMA = {
    "anyOf": [
        {"type": "array", "items": {"type": "string"}},
        {"type": "string"},
    ],
    "description": (
        "输入图片，用于 image-to-image。可以是单张字符串，也可以是数组；"
        "支持公网 URL、本地文件路径（如 file:///C:/a.png、C:\\a.png、/tmp/a.png）"
        "或 base64 / data URI。系统会自动识别并转换。"
    ),
}

OUTPUT_SCHEMA = {
    "output_dir": {
        "type": "string",
        "description": (
            "生成图片的保存目录（绝对路径优先）。缺省时使用环境变量 IMAGE_OUTPUT_DIR，"
            "再缺省为当前工作目录下的 generated_images。"
        ),
    },
    "filename": {
        "type": "string",
        "description": "保存的文件名，可选，例如 cat.png；缺省按时间戳自动命名。",
    },
}


async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="topboth_generate_image",
            description=(
                "使用 拓全模型 API 生成图片。支持文生图和图生图。"
                "图生图时提供 images 参数（URL、本地路径或 base64 均可）。"
                "生成结果会同时保存到本地，并在返回的 JSON 中给出 local_path。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "图片生成提示词"},
                    "mode": {
                        "type": "string",
                        "enum": ["text-to-image", "image-to-image"],
                        "default": "text-to-image",
                        "description": "生成模式，默认 text-to-image",
                    },
                    "model": {
                        "type": "string",
                        "enum": ["拓全智能图片V2"],
                        "default": BUERGEON_MODEL,
                        "description": "模型名称",
                    },
                    "modelgroup": {
                        "type": "string",
                        "enum": ["burgeon"],
                        "default": "burgeon",
                        "description": "模型组",
                    },
                    "aspect_ratio": {
                        "type": "string",
                        "enum": ["16:9", "1:1", "3:4"],
                        "default": "1:1",
                        "description": "宽高比，默认 1:1",
                    },
                    "image_size": {
                        "type": "string",
                        "enum": ["1K", "2K"],
                        "default": "1K",
                        "description": "图片尺寸，默认 1K",
                    },
                    "n": {
                        "type": "integer",
                        "default": 1,
                        "description": "生成图片数量，默认 1",
                    },
                    "images": IMAGES_SCHEMA,
                    **OUTPUT_SCHEMA,
                },
                "required": ["prompt"],
            },
        ),
        Tool(
            name="test_generate_image",
            description=(
                "使用 测试模型 API 生成图片。支持文生图和图生图。"
                "图生图时提供 images 参数（URL、本地路径或 base64 均可）。"
                "生成结果会同时保存到本地，并在返回的 JSON 中给出 local_path。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "图片生成提示词"},
                    "mode": {
                        "type": "string",
                        "enum": ["text-to-image", "image-to-image"],
                        "default": "text-to-image",
                        "description": "生成模式，默认 text-to-image",
                    },
                    "model": {
                        "type": "string",
                        "enum": ["agnes-image-2.5-flash"],
                        "default": AGNES_MODEL,
                        "description": "模型名称",
                    },
                    "modelgroup": {
                        "type": "string",
                        "enum": ["agnes"],
                        "default": "agnes",
                        "description": "模型组",
                    },
                    "aspect_ratio": {
                        "type": "string",
                        "enum": ["16:9", "1:1", "3:4"],
                        "default": "1:1",
                        "description": "宽高比，默认 1:1",
                    },
                    "image_size": {
                        "type": "string",
                        "enum": ["1K"],
                        "default": "1K",
                        "description": "图片尺寸，只能是 1K",
                    },
                    "n": {
                        "type": "integer",
                        "default": 1,
                        "description": "生成图片数量，默认 1",
                    },
                    "images": IMAGES_SCHEMA,
                    **OUTPUT_SCHEMA,
                },
                "required": ["prompt"],
            },
        ),
        Tool(
            name="server_status",
            description=(
                "检查 topboth-gen MCP 服务的运行与配置状态（后端地址、API Key 是否已配置、"
                "输出目录、运行时信息）。接入任何客户端后都建议先调用一次做自检。"
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


# --------------------------------------------------------------------------- #
# 工具实现
# --------------------------------------------------------------------------- #

async def harvest_images(result: dict, arguments: dict, name_hint: str) -> None:
    """下载生成结果、落盘，并把本地路径回填到返回 JSON。"""
    urls = extract_image_urls(result)
    if not urls:
        return

    output_dir = arguments.get("output_dir") or arguments.get("save_dir") or arguments.get("output_path")
    filename = arguments.get("filename") or arguments.get("file_name")

    local_paths: list[str] = []
    for index, url in enumerate(urls):
        image_bytes = await download_image_bytes(url)
        if not image_bytes:
            continue
        picked_name = filename
        if filename and len(urls) > 1:
            stem = Path(str(filename)).stem
            suffix = Path(str(filename)).suffix
            picked_name = f"{stem}_{index + 1}{suffix}"
        local_path = save_generated_image(image_bytes, url, output_dir, picked_name, name_hint)
        if local_path:
            local_paths.append(local_path)

    data = result.get("data")
    if isinstance(data, dict):
        if local_paths:
            data["local_path"] = local_paths[0]
            data["local_paths"] = local_paths
        else:
            result.setdefault("warnings", []).append("生成成功但图片下载/落盘失败，仅返回远程 URL")


async def execute_tool(name: str, arguments: Any) -> tuple[list, bool]:
    """执行工具，返回 (content 列表, 是否错误)。"""
    try:
        arguments = arguments or {}

        if name == "server_status":
            info = {
                "server": SERVER_NAME,
                "server_version": SERVER_VERSION,
                "mcp_sdk": _sdk_version_info(),
                "image_server_url": IMAGE_SERVER_URL or None,
                "image_server_url_configured": bool(IMAGE_SERVER_URL),
                "api_key_configured": bool(MCP_API_KEY),
                "api_key_preview": (
                    (MCP_API_KEY[:6] + "..." + MCP_API_KEY[-4:]) if len(MCP_API_KEY) > 12 else ("已配置" if MCP_API_KEY else "未配置")
                ),
                "api_key_header": MCP_API_KEY_HEADER,
                "output_dir": str(resolve_output_dir(None)),
                "python": sys.version.split()[0],
                "platform": sys.platform,
                "cwd": str(Path.cwd()),
                "base_dir": str(BASE_DIR),
            }
            return [TextContent(type="text", text=json.dumps(info, ensure_ascii=False, indent=2))], False

        if name in ("topboth_generate_image", "test_generate_image"):
            is_topboth = name == "topboth_generate_image"

            image_config: dict[str, Any] = {
                "aspectRatio": arguments.get("aspect_ratio") or "1:1",
                "imageSize": arguments.get("image_size") or "1K",
            }
            config: dict[str, Any] = {"imageConfig": image_config}

            raw_images = normalize_images_argument(arguments)
            images_data, image_errors = process_images_input(raw_images)

            # 用户明确传了图但一张都没解析出来：直接报错，避免悄悄退化成文生图
            if raw_images and not images_data:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "error": "图片输入无法解析，未调用后端",
                                "details": image_errors,
                                "hint": (
                                    "请传入本地绝对路径（如 C:/Users/me/a.png 或 file:///C:/Users/me/a.png）、"
                                    "可访问的图片 URL，或 base64 数据。"
                                    "若图片来自聊天窗口上传，请让 Agent 把上传后得到的本地路径传给 images 参数。"
                                ),
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                ], True

            data = {
                "mode": arguments.get("mode") or ("image-to-image" if images_data else "text-to-image"),
                "prompt": arguments.get("prompt"),
                "model": arguments.get("model") or (BUERGEON_MODEL if is_topboth else AGNES_MODEL),
                "modelgroup": arguments.get("modelgroup") or ("burgeon" if is_topboth else "agnes"),
                "config": config,
                "images": images_data,
                "n": arguments.get("n", 1) or 1,
            }
            log(f"工具 {name} 参数就绪: mode={data['mode']} model={data['model']} images={len(images_data)}")

            result = await call_mcp_endpoint(name, data)
            if not isinstance(result, dict):
                result = {"error": "后端返回格式异常", "details": str(result)[:2000]}
            if image_errors:
                result.setdefault("image_errors", []).extend(image_errors)
            await harvest_images(result, arguments, "burgeon" if is_topboth else "agnes")
        else:
            result = {"error": f"Unknown tool: {name}"}

        response_content: list = []

        if isinstance(result, dict):
            for index, url in enumerate(extract_image_urls(result)):
                image_bytes = await download_image_bytes(url)
                if not image_bytes:
                    continue
                response_content.append(
                    ImageContent(
                        type="image",
                        data=base64.b64encode(image_bytes).decode("utf-8"),
                        mimeType=sniff_mime(image_bytes) or guess_mime(url),
                    )
                )
                if index >= 3:  # 最多内联 4 张，避免响应过大
                    break

        response_content.append(
            TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))
        )

        is_error = bool(isinstance(result, dict) and result.get("error"))
        return response_content, is_error

    except Exception as e:
        log(f"工具 {name} 执行异常: {e!r}")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": str(e), "tool": name}, ensure_ascii=False, indent=2),
            )
        ], True


# --------------------------------------------------------------------------- #
# MCP SDK 版本兼容注册（1.x 装饰器 API / 2.x 构造器 API）
# --------------------------------------------------------------------------- #

def _is_sdk_v2() -> bool:
    """2.x 用构造器注册 handler，并移除了 list_tools/call_tool 装饰器。"""
    return hasattr(Server, "add_request_handler") and not hasattr(Server, "list_tools")


def _sdk_version_info() -> str:
    try:
        from importlib.metadata import version

        return f"{'2.x-compatible' if _is_sdk_v2() else '1.x-compatible'} (mcp {version('mcp')})"
    except Exception:
        return "2.x-compatible" if _is_sdk_v2() else "1.x-compatible"


def _build_app() -> Server:
    if _is_sdk_v2():

        async def on_list_tools(ctx, params=None):
            return mcp_types.ListToolsResult(tools=await list_tools())

        async def on_call_tool(ctx, params):
            content, is_error = await execute_tool(
                getattr(params, "name", "") or "",
                getattr(params, "arguments", None) or {},
            )
            return mcp_types.CallToolResult(content=content, isError=is_error)

        app = Server(SERVER_NAME, on_list_tools=on_list_tools, on_call_tool=on_call_tool)
        log("已按 mcp SDK 2.x 构造器 API 注册处理器")
        return app

    app = Server(SERVER_NAME)

    @app.list_tools()
    async def _list_tools():
        return await list_tools()

    @app.call_tool()
    async def _call_tool(name: str, arguments: Any):
        content, _ = await execute_tool(name, arguments)
        return content

    log("已按 mcp SDK 1.x 装饰器 API 注册处理器")
    return app


app = _build_app()


async def main():
    if not IMAGE_SERVER_URL:
        log("警告：IMAGE_SERVER_URL 未配置，工具调用会返回配置错误提示。")
    log(f"{SERVER_NAME} v{SERVER_VERSION} 启动中... sdk={_sdk_version_info()} base_dir={BASE_DIR} cwd={Path.cwd()}")

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name=SERVER_NAME,
                server_version=SERVER_VERSION,
                capabilities=app.get_capabilities(
                    notification_options=NotificationOptions(tools_changed=False),
                    experimental_capabilities=None,
                ),
            ),
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
