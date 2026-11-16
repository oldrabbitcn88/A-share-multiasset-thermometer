"""万得 Alice Market MCP CLI 的薄封装。

Key 只通过环境变量 WIND_API_KEY 传给 CLI，绝不出现在命令行参数或日志中。
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SKILL_DIR = Path(os.environ.get("WIND_SKILL_DIR", Path.home() / ".agents/skills/wind-mcp-skill"))


class WindError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message

    @property
    def fatal(self) -> bool:
        """额度不足 / 认证失败时，后续调用必然失败，应立即停止。"""
        return self.code == "AUTH_ERROR" or "积分余额不足" in self.message


def call(server: str, tool: str, params: dict, timeout: int = 180) -> dict:
    env = dict(os.environ)
    env.setdefault("NODE_NO_WARNINGS", "1")
    if env.get("HTTPS_PROXY") or env.get("https_proxy"):
        env["NODE_USE_ENV_PROXY"] = "1"  # Node 原生 fetch 默认不读代理变量
    proc = subprocess.run(
        ["node", "scripts/cli.mjs", "call", server, tool, json.dumps(params, ensure_ascii=False)],
        cwd=SKILL_DIR, env=env, capture_output=True, text=True, timeout=timeout,
    )
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise WindError("UNPARSEABLE", (proc.stdout or proc.stderr)[-300:])
    if out.get("ok") is False:
        raise WindError(out.get("code", "UNKNOWN"), out.get("message", ""))
    text = out["content"][0]["text"]
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}
    if isinstance(body, dict) and body.get("error"):
        raise WindError("backend_error", str(body["error"]))
    return body


def table(body: dict) -> tuple[list[str], list[list]]:
    """解析 {data:{columns:[{name}], rows:[[...]]}} 形态的表格返回。"""
    data = body.get("data", body)
    cols = [c["name"] if isinstance(c, dict) else c for c in data.get("columns", [])]
    return cols, data.get("rows", [])
