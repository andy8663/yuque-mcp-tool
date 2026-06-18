# Yuque MCP Tool

一个基于 Session Cookie 的语雀 MCP (Model Context Protocol) 服务器，让你可以在 Claude Desktop、Cursor、WorkBuddy 等 AI 客户端中直接读取语雀文档。

A Model Context Protocol (MCP) server for reading Yuque documents via session cookie, compatible with Claude Desktop, Cursor, WorkBuddy, and other MCP clients.

---

## 中文文档

### 功能特性

提供 3 个 MCP 工具：

| 工具 | 说明 |
|------|------|
| `yuque_read` | 读取语雀文档，返回渲染后的文本内容。 |
| `yuque_read_markdown` | **推荐**。读取语雀 Lake/API 源内容并转换为可读 Markdown，保留表格、PlantUML/Mermaid 图表、代码块、图片、链接和画板摘要。 |
| `yuque_list_docs` | 列出知识库中的所有文档。 |

**技术栈**：aiohttp + Playwright（可选渲染）+ BeautifulSoup4

### 快速开始

#### 1. 安装

```bash
pip install yuque-mcp-tool

# 如果需要 Playwright 渲染功能（推荐）
python -m playwright install chromium
```

或者从源码安装：

```bash
git clone https://github.com/andy8663/yuque-mcp-tool.git
cd yuque-mcp-tool
pip install -e .
```

#### 2. 获取 Session Cookie

1. 登录 [语雀](https://www.yuque.com)
2. 按 `F12` 打开浏览器开发者工具
3. 在 Console 中输入：
   ```javascript
   document.cookie.split('; ').find(c => c.startsWith('_yuque_session=')).split('=')[1]
   ```
4. 复制输出的值

> Session Cookie 有效期约 30 天，过期后需重新获取。

#### 3. 配置 MCP 客户端

根据你使用的客户端，选择对应的配置方式（见下方配置示例）。

### 配置示例

#### Claude Desktop

编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`（macOS）或 `%APPDATA%\Claude\claude_desktop_config.json`（Windows）：

```json
{
  "mcpServers": {
    "yuque": {
      "command": "yuque-mcp",
      "env": {
        "YUQUE_SESSION": "YOUR_YUQUE_SESSION",
        "YUQUE_HOST": "https://www.yuque.com"
      }
    }
  }
}
```

#### Cursor

编辑项目根目录下的 `.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "yuque": {
      "command": "yuque-mcp",
      "env": {
        "YUQUE_SESSION": "YOUR_YUQUE_SESSION",
        "YUQUE_HOST": "https://www.yuque.com"
      }
    }
  }
}
```

#### WorkBuddy

在 WorkBuddy 的 MCP 配置文件中添加：

```json
{
  "mcpServers": {
    "yuque": {
      "command": "yuque-mcp",
      "env": {
        "YUQUE_SESSION": "YOUR_YUQUE_SESSION",
        "YUQUE_HOST": "https://www.yuque.com"
      }
    }
  }
}
```

#### 通用 MCP 客户端

```json
{
  "mcpServers": {
    "yuque": {
      "command": "yuque-mcp",
      "env": {
        "YUQUE_SESSION": "YOUR_YUQUE_SESSION",
        "YUQUE_HOST": "https://www.yuque.com"
      }
    }
  }
}
```

> 如果未通过 `pip install` 安装，也可以使用 `python -m yuque_mcp` 作为 `command`，`args` 留空。

### 环境变量

| 变量名 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| `YUQUE_SESSION` | 是 | — | 语雀 Session Cookie（`_yuque_session` 的值） |
| `YUQUE_HOST` | 否 | `https://www.yuque.com` | 默认语雀主机地址，用于补全短路径 URL |
| `YUQUE_BROWSER_CHANNEL` | 否 | — | Playwright 浏览器通道，如 `chrome` |
| `YUQUE_CHROMIUM_EXECUTABLE` | 否 | — | Chromium/Chrome 可执行文件的绝对路径 |
| `YUQUE_RENDER_MODE` | 否 | `auto` | 渲染模式：`auto`（自动）、`off`（关闭）、`force`（强制使用 Playwright） |

### 常见问题

#### Session 无效 / 读取失败

重新登录语雀网站，获取新的 `_yuque_session` 值并更新配置。

#### Playwright 渲染失败

如果系统已安装 Chrome，可以设置 `YUQUE_BROWSER_CHANNEL=chrome` 以使用系统 Chrome，无需额外安装 Playwright 自带 Chromium。

#### Python 找不到

在配置中使用 Python 的完整路径作为 `command`，例如：
- macOS: `/usr/bin/python3`
- Windows: `C:/Users/你的用户名/AppData/Local/Programs/Python/Python312/python.exe`

#### 团队/空间子域名

如果文档位于团队子域名下（如 `ogtd9v.yuque.com`），可以将 `YUQUE_HOST` 设为常用子域名；也可以直接传完整文档 URL，工具会从 URL 推导实际 host。

### License

MIT License — 详见 [LICENSE](LICENSE)。

---

## English Documentation

### Features

Provides 3 MCP tools:

| Tool | Description |
|------|-------------|
| `yuque_read` | Read a Yuque document and return the rendered text content. |
| `yuque_read_markdown` | **Recommended.** Read the Yuque Lake/API source content and convert it to readable Markdown, preserving tables, PlantUML/Mermaid diagrams, code blocks, images, links, and board summaries. |
| `yuque_list_docs` | List all documents in a Yuque knowledge base. |

**Tech stack**: aiohttp + Playwright (optional rendering) + BeautifulSoup4

### Quick Start

#### 1. Installation

```bash
pip install yuque-mcp-tool

# If you need Playwright rendering (recommended)
python -m playwright install chromium
```

Or install from source:

```bash
git clone https://github.com/andy8663/yuque-mcp-tool.git
cd yuque-mcp-tool
pip install -e .
```

#### 2. Get Your Session Cookie

1. Log in to [Yuque](https://www.yuque.com)
2. Press `F12` to open browser DevTools
3. In the Console, run:
   ```javascript
   document.cookie.split('; ').find(c => c.startsWith('_yuque_session=')).split('=')[1]
   ```
4. Copy the output value

> The session cookie is valid for approximately 30 days.

#### 3. Configure Your MCP Client

Choose the configuration for your client below.

### Configuration Examples

#### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "yuque": {
      "command": "yuque-mcp",
      "env": {
        "YUQUE_SESSION": "YOUR_YUQUE_SESSION",
        "YUQUE_HOST": "https://www.yuque.com"
      }
    }
  }
}
```

#### Cursor

Edit `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "yuque": {
      "command": "yuque-mcp",
      "env": {
        "YUQUE_SESSION": "YOUR_YUQUE_SESSION",
        "YUQUE_HOST": "https://www.yuque.com"
      }
    }
  }
}
```

#### WorkBuddy

Add to your WorkBuddy MCP configuration:

```json
{
  "mcpServers": {
    "yuque": {
      "command": "yuque-mcp",
      "env": {
        "YUQUE_SESSION": "YOUR_YUQUE_SESSION",
        "YUQUE_HOST": "https://www.yuque.com"
      }
    }
  }
}
```

#### Generic MCP Client

```json
{
  "mcpServers": {
    "yuque": {
      "command": "yuque-mcp",
      "env": {
        "YUQUE_SESSION": "YOUR_YUQUE_SESSION",
        "YUQUE_HOST": "https://www.yuque.com"
      }
    }
  }
}
```

> If you haven't installed via `pip install`, you can use `python -m yuque_mcp` as the `command` instead.

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `YUQUE_SESSION` | Yes | — | Yuque session cookie (`_yuque_session` value) |
| `YUQUE_HOST` | No | `https://www.yuque.com` | Default Yuque host for short-path URL completion |
| `YUQUE_BROWSER_CHANNEL` | No | — | Playwright browser channel, e.g. `chrome` |
| `YUQUE_CHROMIUM_EXECUTABLE` | No | — | Absolute path to a Chromium/Chrome executable |
| `YUQUE_RENDER_MODE` | No | `auto` | Rendering mode: `auto`, `off`, or `force` |

### FAQ

#### Invalid Session / Read Failure

Re-log in to Yuque, obtain a new `_yuque_session` value, and update your configuration.

#### Playwright Rendering Failure

If Chrome is installed on your system, set `YUQUE_BROWSER_CHANNEL=chrome` to use the system Chrome without installing Playwright's bundled Chromium.

#### Python Not Found

Use the full path to your Python executable as the `command` in your configuration:
- macOS: `/usr/bin/python3`
- Windows: `C:/Users/your-username/AppData/Local/Programs/Python/Python312/python.exe`

#### Team / Workspace Subdomains

If your documents are on a team subdomain (e.g. `ogtd9v.yuque.com`), set `YUQUE_HOST` to your common subdomain. You can also pass full document URLs directly — the tool derives the actual host from the URL.

### License

MIT License — see [LICENSE](LICENSE).
