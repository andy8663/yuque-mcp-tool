#!/usr/bin/env python3
"""
Yuque MCP Server (Session Mode)

A MCP server that uses session cookie to access Yuque documents.
Uses Playwright to render JavaScript-heavy pages.

Environment Variables:
  - YUQUE_SESSION: your Yuque session cookie (_yuque_session value)
  - YUQUE_HOST (optional): default is "https://www.yuque.com"
  - YUQUE_BROWSER_CHANNEL (optional): Playwright browser channel, e.g. "chrome"
  - YUQUE_CHROMIUM_EXECUTABLE (optional): absolute path to a Chromium/Chrome executable
  - YUQUE_RENDER_MODE (optional): "auto" (default), "off", or "force"
"""

import asyncio
import html
import json
import os
import re
import sys
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import unquote, urlparse

import aiohttp

from yuque_mcp.markdown import lake_to_markdown

# Constants
DEFAULT_HOST = "https://www.yuque.com"
REQUEST_TIMEOUT = 60
RENDER_MODE_AUTO = "auto"


def _cookie_domain_for(url: str) -> str:
    """Return the parent cookie domain (e.g. '.yuque.com') so the cookie works across subdomains like 'ogtd9v.yuque.com'."""
    host = urlparse(url).hostname or ""
    parts = host.split('.')
    if len(parts) >= 2:
        return '.' + '.'.join(parts[-2:])
    return host


def _origin_for_url(url: str, fallback: str = DEFAULT_HOST) -> str:
    """Return scheme://host for absolute Yuque URLs, falling back to configured host."""
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    return fallback.rstrip("/")


def _dedupe(values: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        normalized = value.rstrip("/")
        if normalized and normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return result


def _clean_text(value: str) -> str:
    """Convert simple HTML-ish content to readable text without adding a parser dependency."""
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", value)
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    value = re.sub(r"(?i)</(p|div|section|article|h[1-6]|li|tr)>", "\n", value)
    value = re.sub(r"(?s)<[^>]+>", "", value)
    value = html.unescape(value)
    return "\n".join(line.rstrip() for line in value.splitlines() if line.strip()).strip()


def _find_first_string(mapping: Dict, keys: Iterable[str]) -> str:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


class YuqueClient:
    """Client for fetching Yuque documents using a session cookie."""

    def __init__(
        self,
        session_cookie: str,
        host: str = DEFAULT_HOST,
        browser_channel: Optional[str] = None,
        chromium_executable: Optional[str] = None,
        render_mode: str = RENDER_MODE_AUTO,
    ):
        self.host = host.rstrip('/')
        self.session_cookie = session_cookie
        self.browser_channel = browser_channel
        self.chromium_executable = chromium_executable
        self.render_mode = render_mode
        self.session: Optional[aiohttp.ClientSession] = None
        self._browser = None
        self._playwright = None

    async def _ensure_session(self):
        if self.session is None:
            headers = {
                'Cookie': f'_yuque_session={self.session_cookie}; lang=zh-cn',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                headers=headers
            )

    async def close(self):
        """Close all open connections and browser instances."""
        if self.session:
            await self.session.close()
            self.session = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def _fetch_page(self, url: str) -> Optional[str]:
        await self._ensure_session()
        try:
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    return await resp.text()
        except Exception as e:
            print(f"Fetch error: {e}", file=sys.stderr)
        return None

    def _extract_app_data(self, html: str) -> Optional[Dict]:
        match = re.search(r'window\.appData\s*=\s*JSON\.parse\(decodeURIComponent\("([^"]+)"\)\)', html)
        if match:
            try:
                data = json.loads(unquote(match.group(1)))
                return data
            except Exception as e:
                print(f"Parse appData error: {e}", file=sys.stderr)
        return None

    def _extract_content_from_app_data(self, data: Dict) -> str:
        """Prefer embedded appData when it already includes the document body."""
        doc = data.get('doc', {})
        if not isinstance(doc, dict):
            return ""

        raw_content = _find_first_string(doc, (
            'body',
            'body_html',
            'content',
            'content_html',
            'lake_content',
            'data',
        ))
        if not raw_content:
            return ""

        content = _clean_text(raw_content)
        description = doc.get('description') if isinstance(doc.get('description'), str) else ""
        if description and content.strip() == description.strip():
            return ""
        return content

    async def _get_rendered_content(self, url: str) -> str:
        """Use Playwright to get fully rendered page content."""
        if self.render_mode == "off":
            return ""

        try:
            from playwright.async_api import async_playwright

            if self._playwright is None:
                self._playwright = await async_playwright().start()
                launch_options = {'headless': True}
                if self.browser_channel:
                    launch_options['channel'] = self.browser_channel
                if self.chromium_executable:
                    launch_options['executable_path'] = self.chromium_executable
                self._browser = await self._playwright.chromium.launch(**launch_options)

            context = await self._browser.new_context()
            await context.add_cookies([{
                'name': '_yuque_session',
                'value': self.session_cookie,
                'domain': _cookie_domain_for(url),
                'path': '/'
            }])

            page = await context.new_page()

            try:
                await page.goto(url, wait_until='networkidle', timeout=30000)

                # Wait for content to load
                await page.wait_for_selector('.ne-viewer-body, .lake-content, [data-lake-element]', timeout=15000)

                # Extract text content
                content = await page.evaluate('''() => {
                    // Try to find the main content area
                    const selectors = [
                        '.ne-viewer-body',
                        '.lake-content',
                        '[data-lake-element]',
                        'article',
                        '.doc-content'
                    ];

                    for (const selector of selectors) {
                        const el = document.querySelector(selector);
                        if (el) {
                            return el.innerText;
                        }
                    }

                    // Fallback to body
                    return document.body.innerText;
                }''')

                await context.close()
                return content or ""

            except Exception as e:
                await context.close()
                print(f"Playwright render error: {e}", file=sys.stderr)
                return ""

        except ImportError:
            print("Playwright not installed, falling back to simple extraction", file=sys.stderr)
            return ""
        except Exception as e:
            print(f"Browser error: {e}", file=sys.stderr)
            return ""

    async def get_doc_by_url(self, url: str) -> Optional[Dict]:
        """Fetch a Yuque document by URL and return rendered content."""
        html = await self._fetch_page(url)
        if not html:
            return None

        data = self._extract_app_data(html)
        if not data:
            return None

        doc = data.get('doc', {})
        book = data.get('book', {})

        if doc.get('format') == 'lakesheet' or doc.get('origin_format') == 'lakesheet':
            markdown_doc = await self.get_doc_markdown_by_url(url)
            if markdown_doc:
                return markdown_doc

        content = ""
        if self.render_mode != "force":
            content = self._extract_content_from_app_data(data)

        # Try Playwright only when embedded appData was insufficient or rendering was forced.
        if not content:
            content = await self._get_rendered_content(url)

        # Fallback to description if content extraction failed
        if not content:
            content = doc.get('description', '')

        return {
            'id': doc.get('id'),
            'title': doc.get('title'),
            'slug': doc.get('slug'),
            'description': doc.get('description'),
            'content': content,
            'format': doc.get('format'),
            'word_count': doc.get('word_count'),
            'created_at': doc.get('created_at'),
            'updated_at': doc.get('updated_at'),
            'book_name': book.get('name'),
            'book_slug': book.get('slug'),
            'author': data.get('me', {}).get('name'),
        }

    async def get_doc_markdown_by_url(self, url: str) -> Optional[Dict]:
        """Fetch a Yuque document by URL and convert Lake/API source content to Markdown."""
        page_html = await self._fetch_page(url)
        if not page_html:
            return None

        app_data = self._extract_app_data(page_html)
        if not app_data:
            return None

        doc = app_data.get('doc', {})
        book = app_data.get('book', {})
        if not isinstance(doc, dict):
            return None

        slug = doc.get('slug') or url.rstrip('/').split('/')[-1].split('#', 1)[0]
        book_id = doc.get('book_id') or book.get('id')
        if not slug:
            return None

        await self._ensure_session()
        params = {
            "include_contributors": "true",
            "include_like": "true",
            "include_hits": "true",
            "merge_dynamic_data": "false",
        }
        if book_id:
            params["book_id"] = str(book_id)

        origins = _dedupe((
            _origin_for_url(url, self.host),
            self.host,
            DEFAULT_HOST,
        ))

        payload = None
        api_error_notes = []
        for origin in origins:
            api_url = f"{origin}/api/docs/{slug}"
            try:
                async with self.session.get(api_url, params=params) as resp:
                    if resp.status != 200:
                        api_error_notes.append(f"{api_url}: HTTP {resp.status}")
                        continue
                    payload = await resp.json()
                    break
            except Exception as e:
                api_error_notes.append(f"{api_url}: {e}")

        if not payload:
            rendered_content = await self._get_rendered_content(url)
            if not rendered_content:
                rendered_content = doc.get('description', '')
            if not rendered_content:
                print("Yuque API markdown fetch failed: " + "; ".join(api_error_notes), file=sys.stderr)
                return None
            return {
                'id': doc.get('id'),
                'title': doc.get('title'),
                'slug': slug,
                'description': doc.get('description'),
                'content': rendered_content,
                'format': doc.get('format') or 'rendered',
                'word_count': doc.get('word_count'),
                'created_at': doc.get('created_at'),
                'updated_at': doc.get('updated_at'),
                'content_updated_at': doc.get('content_updated_at'),
                'book_name': book.get('name'),
                'book_slug': book.get('slug'),
                'conversion_stats': {
                    'source': 'rendered_fallback',
                    'api_errors': api_error_notes,
                },
            }

        data = payload.get("data", {})
        lake_content = data.get("content") or ""
        markdown, stats = lake_to_markdown(lake_content)

        return {
            'id': data.get('id') or doc.get('id'),
            'title': data.get('title') or doc.get('title'),
            'slug': data.get('slug') or slug,
            'description': data.get('description') or doc.get('description'),
            'content': markdown,
            'format': data.get('format') or doc.get('format'),
            'word_count': data.get('word_count') or doc.get('word_count'),
            'created_at': data.get('created_at') or doc.get('created_at'),
            'updated_at': data.get('updated_at') or doc.get('updated_at'),
            'content_updated_at': data.get('content_updated_at'),
            'book_name': book.get('name'),
            'book_slug': book.get('slug'),
            'conversion_stats': stats,
        }

    async def list_docs(self, repo_slug: str, host: Optional[str] = None) -> List[Dict]:
        """List all documents in a Yuque knowledge base."""
        if re.match(r"^https?://", repo_slug):
            repo_url = repo_slug.rstrip("/")
            parsed = urlparse(repo_url)
            path_parts = [part for part in parsed.path.split("/") if part]
            if len(path_parts) < 2:
                return []
            repo_path = "/".join(path_parts[:2])
            origin = _origin_for_url(repo_url, self.host)
        else:
            parts = repo_slug.split('/')
            if len(parts) != 2:
                return []
            repo_path = repo_slug
            origin = (host or self.host).rstrip("/")
            repo_url = f"{origin}/{repo_path}"

        parts = repo_path.split('/')
        if len(parts) != 2:
            return []

        html = await self._fetch_page(repo_url)
        if not html:
            return []

        data = self._extract_app_data(html)
        if not data:
            return []

        book_data = data.get('book', {})
        toc = book_data.get('toc', [])

        docs = []
        for item in self._iter_doc_toc(toc):
            if item.get('type') == 'DOC':
                slug = item.get('url', '').split('/')[-1] if item.get('url') else ''
                docs.append({
                    'title': item.get('title'),
                    'slug': slug,
                    'url': f"{origin}/{repo_path}/{slug}" if slug else '',
                })

        return docs

    def _iter_doc_toc(self, items: List[Dict]):
        for item in items:
            yield item
            children = item.get('children') or item.get('childrens') or []
            if isinstance(children, list):
                yield from self._iter_doc_toc(children)


class MCPServer:
    """MCP server that exposes Yuque document reading tools over stdio JSON-RPC."""

    def __init__(self):
        self.client: Optional[YuqueClient] = None
        self.config_error: Optional[str] = None

    async def initialize(self):
        """Initialize the Yuque client from environment variables."""
        session_cookie = os.getenv("YUQUE_SESSION")
        host = os.getenv("YUQUE_HOST", DEFAULT_HOST)
        browser_channel = os.getenv("YUQUE_BROWSER_CHANNEL")
        chromium_executable = os.getenv("YUQUE_CHROMIUM_EXECUTABLE")
        render_mode = os.getenv("YUQUE_RENDER_MODE", RENDER_MODE_AUTO).lower()
        if render_mode not in {"auto", "off", "force"}:
            render_mode = RENDER_MODE_AUTO

        if not session_cookie:
            self.config_error = (
                "YUQUE_SESSION is not configured. Set the YUQUE_SESSION environment variable "
                "with your Yuque session cookie in your MCP client configuration, then restart."
            )
            return

        self.client = YuqueClient(
            session_cookie,
            host,
            browser_channel=browser_channel,
            chromium_executable=chromium_executable,
            render_mode=render_mode,
        )
        self.config_error = None

    async def handle_read_tool(self, args: Dict) -> Dict[str, Any]:
        url = args.get("url")
        if not url:
            return {"content": [{"type": "text", "text": "Error: URL is required"}]}

        if not self.client:
            return {"content": [{"type": "text", "text": f"Error: {self.config_error or 'Yuque client not initialized'}"}]}

        doc = await self.client.get_doc_by_url(url)
        if not doc:
            return {"content": [{"type": "text", "text": "Error: Document not found or access denied"}]}

        formatted = f"# {doc.get('title', 'Untitled')}\n\n"
        formatted += f"**URL:** {url}\n"
        formatted += f"**Book:** {doc.get('book_name', 'Unknown')}\n"
        formatted += f"**Format:** {doc.get('format', 'Unknown')}\n"
        formatted += f"**Word Count:** {doc.get('word_count', 0)}\n"
        formatted += f"**Updated:** {doc.get('updated_at', 'Unknown')}\n"
        if doc.get('content_updated_at'):
            formatted += f"**Content Updated:** {doc.get('content_updated_at')}\n"
        if doc.get('conversion_stats'):
            formatted += f"**Markdown Conversion Stats:** `{json.dumps(doc.get('conversion_stats', {}), ensure_ascii=False)}`\n"
        formatted += "\n---\n\n"
        formatted += doc.get('content', 'No content available')

        return {"content": [{"type": "text", "text": formatted}]}

    async def handle_list_docs_tool(self, args: Dict) -> Dict[str, Any]:
        repo_slug = args.get("repo_slug")
        if not repo_slug:
            return {"content": [{"type": "text", "text": "Error: repo_slug is required"}]}

        if not self.client:
            return {"content": [{"type": "text", "text": f"Error: {self.config_error or 'Yuque client not initialized'}"}]}

        docs = await self.client.list_docs(repo_slug, host=args.get("host"))

        formatted = f"# Documents in {repo_slug}\n\n"
        for doc in docs:
            formatted += f"- [{doc.get('title', 'Untitled')}]({doc.get('url', '')})\n"

        return {"content": [{"type": "text", "text": formatted}]}

    async def handle_read_markdown_tool(self, args: Dict) -> Dict[str, Any]:
        url = args.get("url")
        include_stats = bool(args.get("include_stats", False))
        if not url:
            return {"content": [{"type": "text", "text": "Error: URL is required"}]}

        if not self.client:
            return {"content": [{"type": "text", "text": f"Error: {self.config_error or 'Yuque client not initialized'}"}]}

        doc = await self.client.get_doc_markdown_by_url(url)
        if not doc:
            return {"content": [{"type": "text", "text": "Error: Document not found or access denied"}]}

        formatted = f"# {doc.get('title', 'Untitled')}\n\n"
        formatted += f"**URL:** {url}\n"
        formatted += f"**Book:** {doc.get('book_name', 'Unknown')}\n"
        formatted += f"**Format:** {doc.get('format', 'Unknown')}\n"
        formatted += f"**Word Count:** {doc.get('word_count', 0)}\n"
        formatted += f"**Updated:** {doc.get('updated_at', 'Unknown')}\n"
        if doc.get('content_updated_at'):
            formatted += f"**Content Updated:** {doc.get('content_updated_at')}\n"
        if include_stats:
            formatted += f"**Markdown Conversion Stats:** `{json.dumps(doc.get('conversion_stats', {}), ensure_ascii=False)}`\n"
        formatted += "\n---\n\n"
        formatted += doc.get('content', 'No content available')

        return {"content": [{"type": "text", "text": formatted}]}

    async def handle_tool(self, name: str, args: Dict) -> Dict[str, Any]:
        handlers = {
            "yuque_read": self.handle_read_tool,
            "yuque_read_markdown": self.handle_read_markdown_tool,
            "yuque_list_docs": self.handle_list_docs_tool,
        }
        handler = handlers.get(name)
        if handler:
            return await handler(args)
        return {"content": [{"type": "text", "text": f"Error: Unknown tool: {name}"}]}

    async def handle_list_tools(self) -> Dict[str, Any]:
        return {
            "tools": [
                {
                    "name": "yuque_read",
                    "description": "Read a Yuque document by URL. Returns the full rendered content.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "The Yuque document URL to read"}
                        },
                        "required": ["url"]
                    }
                },
                {
                    "name": "yuque_list_docs",
                    "description": "List all documents in a Yuque repository",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "repo_slug": {"type": "string", "description": "The repository slug or full repository URL (e.g., cc9c0g/rebell or https://example.yuque.com/cc9c0g/rebell)"},
                            "host": {"type": "string", "description": "Optional Yuque host to use when repo_slug is not a full URL"}
                        },
                        "required": ["repo_slug"]
                    }
                },
                {
                    "name": "yuque_read_markdown",
                    "description": "Read a Yuque document by URL using Yuque Lake/API source content and convert it to readable Markdown with tables, PlantUML, Mermaid, code blocks, images, links, and board summaries.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "The Yuque document URL to read"},
                            "include_stats": {"type": "boolean", "description": "Whether to include Markdown conversion statistics"}
                        },
                        "required": ["url"]
                    }
                }
            ]
        }

    async def handle_request(self, request: Dict[str, Any]) -> Optional[Dict]:
        method = request.get("method")

        # Notifications have no id and expect no response
        if isinstance(method, str) and method.startswith("notifications/"):
            return None

        if method == "initialize":
            await self.initialize()
            return {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "yuque-mcp-tool", "version": "1.0.0"}
            }
        elif method == "tools/list":
            return await self.handle_list_tools()
        elif method == "tools/call":
            params = request.get("params", {})
            return await self.handle_tool(params.get("name"), params.get("arguments", {}))
        elif method == "shutdown":
            if self.client:
                await self.client.close()
            return {}

        # Unknown method: signal via exception so main() returns a JSON-RPC error
        raise ValueError(f"Method not found: {method}")


async def _serve() -> None:
    """Run the MCP server loop, reading JSON-RPC requests from stdin."""
    server = MCPServer()

    try:
        while True:
            request = None
            try:
                line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
                if not line:
                    break

                request = json.loads(line.strip())
                response = await server.handle_request(request)

                # Only respond if the request had an id (i.e. it's not a notification)
                if request.get("id") is not None and response is not None:
                    result = {"jsonrpc": "2.0", "id": request.get("id"), "result": response}
                    try:
                        print(json.dumps(result), flush=True)
                    except BrokenPipeError:
                        break

            except json.JSONDecodeError:
                continue
            except BrokenPipeError:
                break
            except Exception as e:
                req_id = request.get("id") if isinstance(request, dict) else None
                error_response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32603, "message": str(e)}
                }
                try:
                    print(json.dumps(error_response), flush=True)
                except BrokenPipeError:
                    break
    finally:
        if server.client:
            await server.client.close()


def main() -> None:
    """Entry point for the Yuque MCP server (console script and ``python -m yuque_mcp``)."""
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
