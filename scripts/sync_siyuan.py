#!/usr/bin/env python3
"""将思源笔记（SiYuan）中的所有文档导出为 Markdown，同步到本仓库。

用法:
    python3 scripts/sync_siyuan.py

配置（按优先级）:
    - API 地址:  环境变量 SIYUAN_API_URL   （默认 http://127.0.0.1:6806）
    - API Token: 环境变量 SIYUAN_API_TOKEN，或仓库根目录下 .siyuan-token 文件（已 gitignore）
    - 数据目录:  环境变量 SIYUAN_DATA_DIR  （默认 ~/Library/Application Support/SiYuan/data）

行为:
    - 每个笔记本对应仓库根目录下的一个文件夹，文档按思源中的层级结构存放为 .md 文件
    - 文档中引用的图片/附件复制到仓库根目录 assets/ 下，链接改写为相对路径
    - 自动生成 README.md 目录索引
    - 通过 .siyuan-sync-manifest.json 记录生成的文件，下次同步前清理旧文件，
      保证仓库内容与思源笔记保持一致（思源中删除/重命名的文档不会残留）
"""

import json
import os
import re
import shutil
import sys
import urllib.request
from pathlib import Path
from urllib.parse import quote, unquote

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / ".siyuan-sync-manifest.json"

API_URL = os.environ.get("SIYUAN_API_URL", "http://127.0.0.1:6806")
DATA_DIR = Path(
    os.environ.get(
        "SIYUAN_DATA_DIR",
        str(Path.home() / "Library/Application Support/SiYuan/data"),
    )
)


def get_token() -> str:
    token = os.environ.get("SIYUAN_API_TOKEN", "").strip()
    if token:
        return token
    token_file = REPO / ".siyuan-token"
    if token_file.exists():
        return token_file.read_text(encoding="utf-8").strip()
    return ""


TOKEN = get_token()


def api(path: str, payload: dict | None = None) -> dict:
    req = urllib.request.Request(
        API_URL + path,
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"token {TOKEN}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if result.get("code") != 0:
        raise RuntimeError(f"API {path} 失败: {result.get('msg')}")
    return result.get("data")


def sanitize_segment(seg: str) -> str:
    """将 hpath 中的一段转换为跨平台安全的文件/目录名。"""
    seg = re.sub(r'[\\:*?"<>|]', "-", seg).strip().rstrip(".")
    return seg or "untitled"


def sql_all_docs() -> list[dict]:
    docs, offset, page = [], 0, 512
    while True:
        rows = api(
            "/api/query/sql",
            {
                "stmt": f"SELECT id, box, hpath FROM blocks WHERE type='d' "
                f"ORDER BY hpath LIMIT {page} OFFSET {offset}"
            },
        )
        docs.extend(rows or [])
        if not rows or len(rows) < page:
            return docs
        offset += page


# 匹配 [xx](assets/...) 与 ![xx](assets/... "title") 中的资源路径
ASSET_LINK_RE = re.compile(r'\]\((assets/[^)"]+?)(\s+"[^"]*")?\)')
# 思源残留语法检查：块引用 ((id "text")) 与嵌入块 {{SQL}}
LEFTOVER_REF_RE = re.compile(r"\(\(\d{14}-[0-9a-z]{7}")


def rewrite_asset_links(content: str, depth: int, used_assets: set) -> str:
    """将 assets/ 链接改写为相对于文档位置的路径，并登记需要复制的资源。"""

    def repl(m: re.Match) -> str:
        raw = m.group(1).strip()
        title = m.group(2) or ""
        name = unquote(raw[len("assets/") :])
        src = DATA_DIR / "assets" / name
        if not src.exists():
            # 链接可能本身未编码
            name = raw[len("assets/") :]
            src = DATA_DIR / "assets" / name
        if src.exists():
            used_assets.add(name)
        rel = "../" * depth + "assets/" + quote(name)
        return f"]({rel}{title})"

    return ASSET_LINK_RE.sub(repl, content)


def clean_previous(manifest_path: Path) -> None:
    """删除上一次同步生成的文件，并清理空目录。"""
    if not manifest_path.exists():
        return
    try:
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    dirs = set()
    for rel in old.get("files", []):
        p = REPO / rel
        if p.is_file():
            p.unlink()
        for parent in p.parents:
            if parent == REPO:
                break
            dirs.add(parent)
    for d in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()


def build_readme(notebooks: list[dict], tree: dict) -> str:
    lines = [
        "# 📚 NoteBook",
        "",
        "个人学习笔记，使用 [思源笔记](https://github.com/siyuan-note/siyuan) 记录，"
        "通过 [scripts/sync_siyuan.py](scripts/sync_siyuan.py) 自动导出为 Markdown。",
        "",
    ]
    total = sum(len(docs) for docs in tree.values())
    lines.append(f"共 **{len(tree)}** 个笔记本、**{total}** 篇笔记。")
    lines.append("")
    lines.append("## 目录")
    lines.append("")
    for nb in notebooks:
        docs = tree.get(nb["id"])
        if not docs:
            continue
        nb_dir = sanitize_segment(nb["name"])
        lines.append(f"### {nb['name']}")
        lines.append("")
        for hpath, _doc_id in sorted(docs, key=lambda x: x[0]):
            segs = [s for s in hpath.split("/") if s]
            depth = len(segs) - 1
            rel = nb_dir + "/" + "/".join(sanitize_segment(s) for s in segs) + ".md"
            link = quote(rel)
            lines.append(f"{'  ' * depth}- [{segs[-1]}]({link})")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "> 本 README 由同步脚本自动生成，请勿手动编辑。"
        "运行 `python3 scripts/sync_siyuan.py` 重新同步。"
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    if not TOKEN:
        print(
            "[错误] 未找到 API token：请设置环境变量 SIYUAN_API_TOKEN，"
            "或在仓库根目录创建 .siyuan-token 文件",
            file=sys.stderr,
        )
        return 1

    notebooks = [nb for nb in api("/api/notebook/lsNotebooks")["notebooks"] if not nb["closed"]]
    nb_names = {nb["id"]: nb["name"] for nb in notebooks}
    docs = sql_all_docs()
    print(f"发现 {len(notebooks)} 个笔记本，{len(docs)} 篇文档")

    clean_previous(MANIFEST)

    written: list[str] = []
    used_assets: set = set()
    warnings: list[str] = []
    tree: dict[str, list] = {}

    for doc in docs:
        nb_name = nb_names.get(doc["box"])
        if nb_name is None:
            continue  # 已关闭/未知笔记本
        data = api("/api/export/exportMdContent", {"id": doc["id"]})
        hpath = data.get("hPath") or doc["hpath"]
        segs = [sanitize_segment(s) for s in hpath.split("/") if s]
        rel_path = Path(sanitize_segment(nb_name), *segs[:-1], segs[-1] + ".md")
        depth = len(rel_path.parts) - 1

        content = rewrite_asset_links(data["content"], depth, used_assets)
        if LEFTOVER_REF_RE.search(content):
            warnings.append(f"{rel_path}: 存在未转换的块引用语法")
        if "{{" in content:
            warnings.append(f"{rel_path}: 可能存在嵌入块语法（{{{{...}}}}）")

        out = REPO / rel_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
        written.append(str(rel_path))
        tree.setdefault(doc["box"], []).append((hpath, doc["id"]))
        print(f"  导出 {rel_path}")

    assets_dir = REPO / "assets"
    for name in sorted(used_assets):
        src = DATA_DIR / "assets" / name
        dst = assets_dir / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        written.append(str(Path("assets", name)))
    print(f"复制 {len(used_assets)} 个资源文件到 assets/")

    readme = build_readme(notebooks, tree)
    (REPO / "README.md").write_text(readme, encoding="utf-8")
    written.append("README.md")

    MANIFEST.write_text(
        json.dumps({"files": sorted(written)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if warnings:
        print("\n[警告]")
        for w in warnings:
            print(f"  - {w}")
    print(f"\n完成：共写入 {len(written)} 个文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
