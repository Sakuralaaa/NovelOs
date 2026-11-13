#!/usr/bin/env python3
"""NovelOS 命令行：用 API 密钥远程操作自托管的 NovelOS。只依赖 Python 3.9+ 标准库。

配置（参数优先于环境变量）：
  NOVELOS_URL       服务地址，如 https://novel.example.com
  NOVELOS_API_KEY   设置 → API 密钥 里生成的 nvk_...（经由代理注入请求头时可不填）

示例：
  novelos_cli.py health
  novelos_cli.py get /books
  novelos_cli.py post /books/1/chapters/3/generate '{}' --wait     # 返回任务时自动等到结束
  novelos_cli.py job 42 --wait
  novelos_cli.py prompts ls
  novelos_cli.py prompts pull prompts writing_scene > writing_scene.md
  novelos_cli.py prompts push prompts writing_scene writing_scene.md
  novelos_cli.py prompts reset prompts writing_scene
  novelos_cli.py trace ls --task writing_scene -n 5
  novelos_cli.py trace show 17
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any


class Client:
    def __init__(self, url: str, key: str | None, timeout: float = 90) -> None:
        if not url:
            sys.exit("缺少服务地址：设置 NOVELOS_URL 或使用 --url")
        self.base = url.rstrip("/")
        if not self.base.endswith("/api"):
            self.base += "/api"
        self.key = key
        self.timeout = timeout

    def req(self, method: str, path: str, body: Any = None) -> Any:
        path = path if path.startswith("/") else "/" + path
        if path.startswith("/api/"):
            path = path[4:]
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        r = urllib.request.Request(self.base + path, data=data, method=method)
        r.add_header("Accept", "application/json")
        r.add_header("User-Agent", "novelos-cli/0.8")
        if data is not None:
            r.add_header("Content-Type", "application/json")
        if self.key:
            r.add_header("Authorization", f"Bearer {self.key}")
        try:
            with urllib.request.urlopen(r, timeout=self.timeout) as resp:
                text = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            try:
                detail = json.loads(detail).get("detail", detail)
            except (ValueError, AttributeError):
                pass
            hint = "（代理超时，任务可能仍在后台运行）" if e.code in (502, 504, 524) else ""
            sys.exit(f"HTTP {e.code} {method} {path}：{str(detail)[:800]}{hint}")
        except urllib.error.URLError as e:
            sys.exit(f"连接失败：{e.reason}")
        if not text:
            return None
        try:
            return json.loads(text)
        except ValueError:
            return text

    def wait_job(self, jid: int, interval: float = 3, timeout: float = 1800) -> Any:
        t0, last = time.time(), None
        while True:
            j = self.req("GET", f"/jobs/{jid}")
            msg = f"[job {jid}] {j.get('status')} {j.get('progress') or ''} {j.get('message') or ''}".strip()
            if msg != last:
                print(msg, file=sys.stderr)
                last = msg
            if j.get("status") in ("succeeded", "failed", "cancelled"):
                return j
            if time.time() - t0 > timeout:
                sys.exit(f"等待任务 {jid} 超时")
            time.sleep(interval)


def _is_job(x: Any) -> bool:
    return isinstance(x, dict) and "status" in x and "id" in x and ("kind" in x or "progress" in x)


def _body(arg: str | None) -> Any:
    if arg is None:
        return {}
    if arg == "-":
        return json.loads(sys.stdin.read())
    if arg.startswith("@"):
        with open(arg[1:], encoding="utf-8") as f:
            return json.load(f)
    return json.loads(arg)


def out(x: Any) -> None:
    if isinstance(x, str):
        print(x)
    else:
        print(json.dumps(x, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="novelos", description="NovelOS 命令行")
    p.add_argument("--url", default=os.environ.get("NOVELOS_URL", ""))
    p.add_argument("--key", default=os.environ.get("NOVELOS_API_KEY"))
    p.add_argument("--timeout", type=float, default=90)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health")
    for m in ("get", "delete"):
        sp = sub.add_parser(m)
        sp.add_argument("path")
        sp.add_argument("--wait", action="store_true")
    for m in ("post", "put", "patch"):
        sp = sub.add_parser(m)
        sp.add_argument("path")
        sp.add_argument("body", nargs="?", help="JSON 字符串、@文件 或 -（标准输入）")
        sp.add_argument("--wait", action="store_true", help="返回后台任务时等它结束")
    sp = sub.add_parser("job")
    sp.add_argument("id", type=int)
    sp.add_argument("--wait", action="store_true")
    sp = sub.add_parser("prompts")
    sp.add_argument("action", choices=["ls", "pull", "default", "push", "reset"])
    sp.add_argument("kind", nargs="?", choices=["prompts", "rules"])
    sp.add_argument("name", nargs="?")
    sp.add_argument("file", nargs="?")
    sp = sub.add_parser("trace")
    sp.add_argument("action", choices=["ls", "show", "clear"])
    sp.add_argument("id", nargs="?", type=int)
    sp.add_argument("--task")
    sp.add_argument("-n", type=int, default=20)
    a = p.parse_args(argv)
    c = Client(a.url, a.key, a.timeout)

    if a.cmd == "health":
        out(c.req("GET", "/health"))
    elif a.cmd in ("get", "delete", "post", "put", "patch"):
        body = _body(a.body) if a.cmd in ("post", "put", "patch") else None
        r = c.req(a.cmd.upper(), a.path, body)
        if a.wait and _is_job(r):
            r = c.wait_job(r["id"])
        out(r)
    elif a.cmd == "job":
        out(c.wait_job(a.id) if a.wait else c.req("GET", f"/jobs/{a.id}"))
    elif a.cmd == "prompts":
        if a.action == "ls":
            for i in c.req("GET", "/prompts")["items"]:
                flag = "*" if i["overridden"] else " "
                print(f"{flag} {i['kind']:<7} {i['name']:<18} {i['chars']:>6}字  用于 {','.join(i['used_by'])}")
            return
        if not (a.kind and a.name):
            sys.exit("需要 kind 和 name")
        if a.action in ("pull", "default"):
            r = c.req("GET", f"/prompts/{a.kind}/{a.name}")
            sys.stdout.write(r["content"] if a.action == "pull" else r["default"])
        elif a.action == "push":
            if not a.file:
                sys.exit("需要文件路径（- 表示标准输入）")
            text = sys.stdin.read() if a.file == "-" else open(a.file, encoding="utf-8").read()
            out(c.req("PUT", f"/prompts/{a.kind}/{a.name}", {"content": text}))
        else:
            out(c.req("DELETE", f"/prompts/{a.kind}/{a.name}"))
    elif a.cmd == "trace":
        if a.action == "clear":
            out(c.req("DELETE", "/debug/llm-calls"))
        elif a.action == "show":
            if a.id is None:
                sys.exit("需要调用 id")
            e = c.req("GET", f"/debug/llm-calls/{a.id}")
            print(f"# #{e['id']} {e['task']} {e['model']}@{e['channel']} {e['duration_ms']}ms usage={e.get('usage')} err={e.get('error')}")
            for m in e["messages"]:
                print(f"\n===== {m['role']} =====\n{m['content']}")
            o = e["output"]
            print("\n===== output =====\n" + (o if isinstance(o, str) else json.dumps(o, ensure_ascii=False, indent=2)))
        else:
            q = f"?limit={a.n}" + (f"&task={a.task}" if a.task else "")
            for i in c.req("GET", "/debug/llm-calls" + q)["items"]:
                t = time.strftime("%m-%d %H:%M:%S", time.localtime(i["at"]))
                err = f" ERR {i['error']}" if i.get("error") else ""
                print(f"#{i['id']:<5} {t} {i['task']:<16} {i['model']:<22} {i['duration_ms']:>6}ms "
                      f"in{i['prompt_chars']:>6} out{i['output_chars']:>6}{err}  {i['output_head'][:40]!r}")


if __name__ == "__main__":
    main()
