# Image Server MCP

MCP (Model Context Protocol) 服务，用于连接外部 AI 客户端与图片生成后端服务。

## 功能

- **文生图**: 使用 拓全模型 API 和 测试模型 API 生成图片
- **图生图**: 支持上传图片进行风格转换、图片编辑和图片融合
- **结果落盘**: 生成的图片会自动保存到本地，并在返回结果中给出 `local_path`（WorkBuddy 等 Agent 客户端可直接作为产物交付）
- **自检工具**: `server_status` 用于快速排查接入问题

## 配置说明

### 1. 获取项目代码

从 Git 仓库下载项目：

```bash
git clone https://github.com/xiaomile/topboth-gen.git
```

### 2. 检查环境

确保服务器已安装 uv 包管理器：

```bash
uv --version
```

如果未安装，执行以下命令安装。

```bash
irm https://astral.sh/uv/install.ps1 | iex
```

### 3. 安装依赖

项目已提交 `pyproject.toml` 与 `uv.lock`，进入项目目录直接同步依赖即可：

```bash
cd topboth-gen
uv sync
```

> 说明：早期版本仓库里没有 `pyproject.toml`，直接 `uv run mcp_server.py` 会因缺少
> `httpx` / `mcp` 而报 `ModuleNotFoundError`。请确保本目录下存在 `pyproject.toml`。

### 4. 获取 MCP API Key

**请联系管理员或从系统上获取 MCP_API_KEY**，该密钥由服务端统一生成和管理。

## 客户端配置

### Trae 配置

在 Trae 中配置 MCP 服务器：

```json
{
  "mcpServers": {
    "topboth-gen": {
      "command": "uv",
      "args": [
        "run",
        "mcp_server.py"
      ],
      "cwd": "your topboth-gen directory",
      "env": {
        "IMAGE_SERVER_URL": "http://aiphoto.topboth.com",
        "MCP_API_KEY": "your_mcp_api_key"
      }
    }
  }
}
```

### Qoder 配置

由于 Qoder 的 bug，在回写中会忽略 `cwd` 参数，因此需要显式指定 work directory。

在 Qoder 中配置 MCP 服务器：

```json
{
  "mcpServers": {
    "topboth-gen": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "your topboth-gen directory",
        "mcp_server.py"
      ],
      "env": {
        "IMAGE_SERVER_URL": "http://aiphoto.topboth.com",
        "MCP_API_KEY": "your_mcp_api_key"
      }
    }
  }
}
```

### WorkBuddy 配置

WorkBuddy 的 MCP 配置文件为 **`~/.workbuddy/mcp.json`**（Windows 下即
`C:\Users\<用户名>\.workbuddy\mcp.json`），格式同样是 `mcpServers`。

WorkBuddy 不会向 MCP 进程注入工作目录（`cwd` 不生效），因此**必须用绝对路径**，
并推荐用 `--directory` 指定项目目录：

```json
{
  "mcpServers": {
    "topboth-gen": {
      "command": "C:\\Users\\<用户名>\\.local\\bin\\uv.exe",
      "args": [
        "run",
        "--directory",
        "D:\\code\\topboth-gen",
        "mcp_server.py"
      ],
      "env": {
        "IMAGE_SERVER_URL": "http://aiphoto.topboth.com",
        "MCP_API_KEY": "your_mcp_api_key",
        "PYTHONUTF8": "1"
      },
      "timeout": 600000
    }
  }
}
```

配置步骤：

1. 打开 WorkBuddy → 侧边栏 **插件** → 右上角 **MCP 服务器** → **配置 MCP**
   （也可直接编辑 `~/.workbuddy/mcp.json`，把上面的配置合并进 `mcpServers`，不要覆盖其他 server）
2. 保存后回到 **连接器管理**，找到 `topboth-gen`，点击 **信任** 启用
3. 状态显示 🟢 绿色即连接成功；🔴 红色请检查 JSON 格式、`uv` 路径与 `IMAGE_SERVER_URL`
4. 在对话里说一句「调用 server_status 检查一下」即可验证

几个注意点：

- `command` 建议写 `uv.exe` 的绝对路径（`where uv` 可查），避免应用进程读不到 PATH
- 首次运行前建议先在项目目录手动执行一次 `uv sync`，让 `.venv` 提前建好
- 若不想依赖 uv，也可以直接把 `command` 换成已装好依赖的 Python 解释器，
  `args` 改为 `["D:\\code\\topboth-gen\\mcp_server.py"]`
- `timeout` 建议不低于 300000（图片生成耗时较长）

### 参数说明

| 参数 | 说明 |
|------|------|
| `command` | 命令，通常为 `uv`（WorkBuddy 建议用绝对路径） |
| `args` | 参数数组，指定运行方式和脚本路径 |
| `IMAGE_SERVER_URL` | 图片生成后端服务器地址（由管理员提供或从系统上获取） |
| `MCP_API_KEY` | 加密的 API Key（由管理员提供或从系统上获取） |
| `IMAGE_OUTPUT_DIR` | 可选，生成图片的默认保存目录 |
| `MCP_HTTP_TIMEOUT` | 可选，后端请求超时秒数，默认 300 |

支持 `cwd` 的客户端可以直接用 `uv run mcp_server.py`；不支持 `cwd` 的客户端
（Qoder、WorkBuddy）用 `uv run --directory <项目目录> mcp_server.py`。

WorkBuddy 上传图片的用法：把图片拖进对话后，直接说「用这张图做图生图，调用
测试模型 生成图片」即可，Agent 会把上传后得到的本地路径传给 `images` 参数；
也可以自己把路径写清楚，例如「调用 测试模型 生成图片，images 传
`C:/Users/me/AppData/Local/Temp/xxx.png`」。详见下方「图生图」小节。

## 使用方法

### 文生图

在 AI 对话框中输入：

```
请生成一张风景油画
```

或者明确指定参数：

```
调用 拓全模型 生成图片，参数：
- 提示词：生成一张赛博朋克风格的城市夜景
- 宽高比：16:9
- 尺寸：1K
```

### 图生图

1. 在对话框中上传图片（拖拽或粘贴）
2. 输入图生图指令：

```
请将这张图片转换为水彩风格
```

也可以显式把图片路径传给工具（推荐，最稳定）：

```
调用 测试模型 生成图片，参数：
- 提示词：将图片转换为梵高风格油画
- 模式：image-to-image
- 图片：['file:///path/to/image.png']
```

**关于"聊天窗口上传的图片能不能传进 MCP"**：可以。客户端会把上传的图片落成本地文件，
Agent 拿到的是本地绝对路径（如 `C:/Users/me/AppData/Local/Temp/xxx.png` 或
`file:///C:/...`），把这个路径传进 `images` 参数即可，服务端会自动读取并转成
base64 提交给后端。三种输入都支持：

| 形式 | 示例 | 说明 |
|------|------|------|
| 本地绝对路径 | `C:/Users/me/upload.png` | 最推荐，聊天窗口上传的图片走这个 |
| `file://` URI | `file:///C:/Users/me/upload.png` | IDE / 客户端给出的引用形式 |
| 图片 URL | `https://example.com/a.png` | 公网可访问 |
| base64 / data URI | `data:image/png;base64,...` | 客户端只能给出内联数据时使用 |

注意：**MCP 服务是独立进程，必须给它一个真实存在的路径**。如果传进来的路径不存在，
服务端会直接返回明确的 `图片输入无法解析 / 本地文件不存在` 错误，并列出具体的图片条目
（不会悄悄退化成文生图）。若只给到文件名，服务端会在当前目录、脚本目录、`Pictures`、
`Downloads`、系统临时目录以及 WorkBuddy 素材目录中按文件名兜底查找。

### 自检

任何客户端接入后，先调用一次自检工具确认配置：

```
调用 server_status 查看服务状态
```

返回内容包含后端地址、API Key 是否已配置、输出目录、当前使用的 MCP SDK 版本等。

## 支持的图片格式

MCP 服务器支持以下图片输入格式（`images` 参数传字符串或数组都可以）：

1. **文件路径**: `file:///path/to/image.jpg`、`C:\path\to\image.png`、`/tmp/a.png`
2. **URL**: 图片 URL，例如 `https://example.com/image.png`
3. **Base64 / data URI**: `data:image/png;base64,...`

路径解析不依赖进程工作目录，且会做兼容处理：`file://` 前缀、`unquote`（`%20` 等）、
Windows 盘符前多余斜杠（`/C:/x`）、`~`、环境变量占位等都能识别。

## 客户端兼容性

服务端针对不同宿主客户端做了以下适配，改动集中在 `mcp_server.py`：

1. **兼容两代 MCP Python SDK**
   - 1.x：`@app.list_tools()` / `@app.call_tool()` 装饰器 API
   - 2.x：`Server(on_list_tools=..., on_call_tool=...)` 构造器 API
   - 2.x 已删除装饰器 API，老代码在 2.x 下启动即崩溃
     （`AttributeError: 'Server' object has no attribute 'list_tools'`），
     客户端表现为「连接关闭 / 无法连接」。现在按运行时自动选择注册方式。
2. **日志全部走 stderr**：stdio 传输下 stdout 是 JSON-RPC 通道，避免日志污染协议流。
3. **不依赖进程工作目录**：`.env`、脚本目录、输出目录均按脚本所在目录或绝对路径解析。
4. **参数宽容解析**：`images` 支持字符串/数组/JSON 字符串，同时兼容
   `image`、`image_path`、`image_url`、`input_images`、`files` 等字段别名。
5. **图片入参明确报错**：路径不存在或无法识别时直接返回
   `图片输入无法解析` + 具体条目（`details` 数组），不会把路径当 base64 发给后端，
   也不会因为图片解析失败而静默退化成文生图。
6. **结果落盘**：生成图片会保存到本地并回传 `local_path` / `local_paths`。
7. **控制台强制 UTF-8**：避免 Windows 下中文日志乱码或 `UnicodeEncodeError`。

## 自测

不依赖真实后端，验证协议层是否正常：

```bash
uv run --directory <项目目录> tests/smoke_test.py
```

输出 `SMOKE TEST PASSED` 表示：服务能启动、能握手、工具能列出、日志没有污染 stdout 通道，
并且图片入参解析正确 —— 覆盖「不存在的路径要报错」「JSON 字符串数组」「本地绝对路径」
「`file:///` 形式」「base64 data URI」五种情况。

## 项目结构

```
topboth-gen/
├── mcp_server.py              # MCP服务器主程序
├── pyproject.toml             # 项目依赖配置
├── uv.lock                    # 依赖锁定文件
├── .env.example               # 环境变量示例
├── tests/smoke_test.py        # stdio 冒烟测试
└── README.md                  # 项目文档
```

## 常见问题

### Q: 无法读取上传的图片

检查以下几点：
1. 图片路径是否正确
2. MCP服务器是否有权限读取图片文件
3. 图片格式是否支持（PNG, JPEG, WebP）
4. 客户端是否把图片放到了临时目录 —— 服务端会在当前目录、脚本目录、`Pictures`、
   `Downloads`、系统临时目录中按文件名兜底查找

### Q: MCP服务器启动失败

检查：
1. uv 是否已安装（WorkBuddy 中使用绝对路径更稳妥）
2. 依赖是否已安装（运行 `uv sync`）
3. `IMAGE_SERVER_URL` 和 `MCP_API_KEY` 是否配置正确
4. MCP SDK 版本：老代码只支持 1.x，当前版本同时支持 1.x / 2.x

### Q: WorkBuddy 里状态是红色 / 无法连接

1. 确认 `~/.workbuddy/mcp.json` 是合法 JSON（括号、引号、逗号）
2. 确认 `command` 指向真实存在的 `uv.exe` 绝对路径，`args` 里的项目目录是绝对路径
3. 先在命令行验证：`uv run --directory <项目目录> mcp_server.py` 能正常挂起不报错
4. 确认已在连接器页点击「信任」
5. 让 Agent 调用一次 `server_status`，看返回信息定位是配置问题还是网络问题

### Q: 生成的图片无法保存

确保：
1. `IMAGE_SERVER_URL` 配置正确
2. 后端服务器正在运行
3. `MCP_API_KEY` 有效
4. 输出目录（`output_dir` 参数 / `IMAGE_OUTPUT_DIR` / 当前目录）具有写权限

## 注意事项

1. MCP_API_KEY 包含用户信息，请勿泄露
2. 建议定期联系管理员更换 MCP_API_KEY
3. 对于大图片，建议使用较小尺寸以提高生成速度

## License

MIT License
