# Image Server MCP

MCP (Model Context Protocol) 服务，用于连接外部AI客户端与图片生成后端服务。

## 功能

- **文生图**: 使用 Burgeon 和 Agnes API 生成图片
- **图生图**: 支持上传图片进行风格转换,图片编辑和图片融合

## 配置说明

### 1. 获取项目代码

从Git仓库下载项目：

```bash
git clone https://github.com/xiaomile/topboth-gen.git
```

### 2. 检查环境

确保服务器已安装 uv 包管理器：

```bash
uv --version
```

如果未安装，请联系则执行以下命令安装。
```bash
irm https://astral.sh/uv/install.ps1 | iex
```

### 3. 安装依赖

在 mcp_server 目录下运行：

```bash
cd topboth-gen
uv init
uv add mcp httpx python-dotenv cryptography
```

### 4. 获取MCP API Key

**请联系管理员或从系统上获取获取 MCP_API_KEY**，该密钥由服务端统一生成和管理。

## Trae配置

在Trae 中配置MCP服务器：

```json
{
  "mcpServers": {
    "topb-media": {
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

## Qoder配置

由于qoder的bug，在回写中会忽略 `cwd` 参数，因此需要显示指定work directory。 

在Qoder 中配置MCP服务器：

```json
{
  "mcpServers": {
    "topb-media": {
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

### 参数说明

| 参数 | 说明 |
|------|------|
| `command` | 命令，通常为 `uv` |
| `args` | 参数数组，指定运行方式和脚本路径 |
| `IMAGE_SERVER_URL` | 图片生成后端服务器地址（由管理员提供或从系统上获取） |
| `MCP_API_KEY` | 加密的API Key（由管理员提供或从系统上获取） |

## 使用方法

### 文生图

在AI对话框中输入：

```
请生成一张风景油画
```

或者明确指定参数：

```
调用burgeon_generate_image工具，参数：
- 提示词：生成一张赛博朋克风格的城市夜景
- 宽高比：16:9
- 尺寸：1K
```

### 图生图

1. 在对话框中上传图片（拖拽或粘贴）
2. 输入图生图指令：

```
请将这张图片(https://example.com/image.png)转换为水彩风格
```

或者：

```
调用agnes_generate_image工具进行图生图：
- 提示词：将图片转换为梵高风格油画
- 模式：image-to-image
- 图片：['file:///path/to/image.png']
```

## 支持的图片格式

MCP服务器支持以下图片输入格式：

1. **文件路径**: `file:///path/to/image.jpg` 或 `/path/to/image.png`
2. **URL**: 图片URL，例如 `https://example.com/image.png`

## 项目结构

```
topboth-gen/
├── mcp_server.py              # MCP服务器主程序
├── pyproject.toml             # 项目依赖配置
├── README.md                  # 项目文档
└── uv.lock                    # 依赖锁定文件
```

## 常见问题

### Q: 无法读取上传的图片

检查以下几点：
1. 图片路径是否正确
2. MCP服务器是否有权限读取图片文件
3. 图片格式是否支持（PNG, JPEG, WebP）

### Q: MCP服务器启动失败

检查：
1. uv 是否已安装
2. 依赖是否已安装（运行 `uv sync`）
3. `IMAGE_SERVER_URL` 和 `MCP_API_KEY` 是否配置正确

### Q: 生成的图片无法保存

确保：
1. `IMAGE_SERVER_URL` 配置正确
2. 后端服务器正在运行
3. `MCP_API_KEY` 有效

## 注意事项

1. MCP_API_KEY 包含用户信息，请勿泄露
2. 建议定期联系管理员更换MCP_API_KEY
4. 对于大图片，建议使用较小尺寸以提高生成速度

## License

MIT License