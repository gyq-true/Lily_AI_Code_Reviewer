"""命令行入口（PICO 风格）：

    aicr serve [--host H] [--port P]        启动 Web 服务
    aicr review <path>                      审查文件/目录
    aicr diff <repo-path> [--staged]        审查 git 变更
    python -m aicr ...                      等价入口
"""

from __future__ import annotations

import argparse
import asyncio

from . import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aicr",
        description="智能代码审查助手 —— 基于 LLM 的多维度代码审查系统",
    )
    parser.add_argument("--version", action="version", version=f"aicr {__version__}")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="启动 Web 服务")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--reload", action="store_true", help="开发模式：代码变更自动重启")

    review = sub.add_parser("review", help="审查单个文件或整个目录")
    review.add_argument("path", help="文件或目录路径")
    review.add_argument("-e", "--ext", action="append", default=[], help="目录扫描时只看指定扩展名，可重复")
    review.add_argument("--max-files", type=int, default=30)
    review.add_argument("--focus", action="append", default=[], choices=[
        "correctness", "security", "performance", "style", "bestPractice", "testing",
    ])
    review.add_argument("--provider", default=None)
    review.add_argument("--model", default=None)
    review.add_argument("--multi", action="store_true", help="多 Agent 协作审查")
    review.add_argument("--json-out", default=None, help="把报告写入指定 JSON 文件")

    diff = sub.add_parser("diff", help="审查 git 仓库的未提交变更")
    diff.add_argument("repo", nargs="?", default=".", help="仓库路径，默认当前目录")
    diff.add_argument("--staged", action="store_true", help="只看已暂存（--cached）变更")
    diff.add_argument("--provider", default=None)
    diff.add_argument("--model", default=None)
    diff.add_argument("--multi", action="store_true", help="多 Agent 协作审查")
    diff.add_argument("--json-out", default=None)

    chat = sub.add_parser("chat", help="多轮对话（支持思考型模型）")
    chat.add_argument("--provider", default=None)
    chat.add_argument("--model", default=None)
    chat.add_argument("--system", default=None, help="系统提示词（可选）")
    chat.add_argument("--show-thinking", action="store_true", help="打印模型思考内容")

    kb = sub.add_parser("kb", help="知识库管理（RAG 上下文）")
    kb_sub = kb.add_subparsers(dest="kb_action")

    kb_ingest = kb_sub.add_parser("ingest", help="摄入目录/文件到向量库")
    kb_ingest.add_argument("path", help="文档/代码目录或单个文件")
    kb_ingest.add_argument("--chunk-size", type=int, default=None)
    kb_ingest.add_argument("--recreate", action="store_true", help="先清空再摄入")

    kb_search = kb_sub.add_parser("search", help="语义检索知识库")
    kb_search.add_argument("query", help="查询文本")
    kb_search.add_argument("-k", type=int, default=None, help="返回条数")

    kb_sub.add_parser("stats", help="查看知识库统计")
    kb_sub.add_parser("clear", help="清空知识库")

    return parser


def main(argv: list[str] | None = None) -> int:
    import sys

    # Windows GBK 控制台兼容：强制 UTF-8 输出
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = _build_parser().parse_args(argv)

    if args.command == "serve":
        return _cmd_serve(args)
    if args.command == "review":
        return asyncio.run(_cmd_review(args))
    if args.command == "diff":
        return asyncio.run(_cmd_diff(args))
    if args.command == "chat":
        return asyncio.run(_cmd_chat(args))
    if args.command == "kb":
        return _cmd_kb(args)

    _build_parser().print_help()
    return 0


def _cmd_serve(args) -> int:
    import uvicorn

    from .config import load_config

    cfg = load_config()
    port = args.port or int(cfg.providers.get("port") or 3000)
    print("=" * 46)
    print("  智能代码审查助手 (aicr) 已启动")
    print(f"  访问地址: http://{args.host}:{port}")
    section = cfg.for_provider()
    key_state = "已配置" if section.get("api_key") or cfg.provider == "ollama" else "未配置"
    print(f"  Provider : {cfg.provider} ({key_state}) | 模型: {section.get('model')}")
    print("=" * 46)
    uvicorn.run(
        "aicr.web.server:app",
        host=args.host,
        port=port,
        reload=args.reload,
    )
    return 0


async def _cmd_review(args) -> int:
    from .collector import CollectorError, collect_from_path
    from .engine import run_review
    from .providers import ProviderError

    try:
        items = collect_from_path(args.path, extensions=args.ext or None, max_files=args.max_files)
    except CollectorError as err:
        print(f"[错误] {err}")
        return 2

    failed = 0
    reports = []
    for item in items:
        print(f"→ 审查 {item.path} ...")
        try:
            result = await run_review(
                code=item.code,
                filename=item.path,
                language=item.language,
                focus=args.focus,
                provider_name=args.provider,
                model=args.model,
                mode="multi" if args.multi else None,
            )
        except ProviderError as err:
            print(f"  ✗ 失败：{err.message if hasattr(err, 'message') else err}")
            failed += 1
            continue
        reports.append({"file": item.path, **result})
        _print_brief(item.path, result)

    if args.json_out and reports:
        import json
        from pathlib import Path

        Path(args.json_out).write_text(
            json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n报告已写入 {args.json_out}")

    print(f"\n完成：{len(reports)} 成功 / {failed} 失败")
    return 1 if failed and not reports else 0


async def _cmd_diff(args) -> int:
    from .collector import CollectorError, collect_git_diff
    from .engine import run_review
    from .providers import ProviderError

    try:
        items = collect_git_diff(args.repo, staged=args.staged)
    except CollectorError as err:
        print(f"[错误] {err}")
        return 2

    print(f"检测到 {len(items)} 个变更文件")
    for item in items:
        print(f"→ 审查 {item.path} (diff) ...")
        try:
            result = await run_review(
                code=item.code,
                filename=item.path,
                language=item.language,
                provider_name=args.provider,
                model=args.model,
                is_diff=True,
                mode="multi" if args.multi else None,
            )
        except ProviderError as err:
            print(f"  ✗ 失败：{getattr(err, 'message', err)}")
            continue
        _print_brief(item.path, result)
    return 0


async def _cmd_chat(args) -> int:
    from .conversation import Conversation
    from .providers import ProviderError

    conv = Conversation.create(args.provider, model=args.model, system=args.system)
    print(f"多轮对话已就绪（provider={conv.provider.name}，model={conv.model}）")
    print("输入 exit / quit 或空行退出。")
    while True:
        try:
            line = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if line.lower() in ("exit", "quit", ""):
            break
        try:
            result = await conv.ask(line)
        except ProviderError as err:
            print(f"[错误] {getattr(err, 'message', err)}")
            continue
        if args.show_thinking and result.reasoning:
            print(f"[思考] {result.reasoning}")
        print(f"助手> {result.text}")
        if result.finish_reason == "length" or result.finish_reason == "max_tokens":
            print("（提示：本轮已触发 max_tokens 续写，若内容仍被截断请调大 max_tokens）")
    return 0


def _cmd_kb(args) -> int:
    from .config import load_config
    from .knowledge import build_embedder, build_store, ingest_path

    cfg = load_config()
    if args.kb_action == "ingest":
        try:
            store = build_store(cfg)
            embedder = build_embedder(cfg)
            stats = ingest_path(
                args.path,
                store=store,
                embedder=embedder,
                chunk_size=args.chunk_size or cfg.kb_chunk_size,
                overlap=cfg.kb_chunk_overlap,
                recreate=args.recreate,
            )
        except Exception as err:  # noqa: BLE001
            print(f"[错误] 摄入失败：{err}")
            return 2
        print(
            f"摄入完成：{stats['files']} 个文件 → {stats['chunks']} 个块 → "
            f"{stats['points']} 个向量（collection={cfg.kb_collection}）"
        )
        return 0

    if args.kb_action == "search":
        from .rag import retrieve_context

        store = build_store(cfg)
        embedder = build_embedder(cfg)
        chunks = retrieve_context(store, embedder, args.query, args.k or cfg.kb_top_k)
        for i, ch in enumerate(chunks, 1):
            src = (ch["payload"] or {}).get("source", "?")
            text = (ch["payload"] or {}).get("text", "").replace("\n", " ")[:120]
            print(f"[{i}] {src}  (score={ch['score']:.3f})\n    {text}\n")
        print(f"共 {len(chunks)} 条结果")
        return 0

    if args.kb_action == "stats":
        store = build_store(cfg)
        print(f"collection : {cfg.kb_collection}")
        print(f"点数        : {store.count()}")
        print(f"embedding  : {cfg.kb_embedding_model}")
        print(f"向量库      : {'远程 ' + cfg.kb_qdrant_url if cfg.kb_qdrant_url else '本地内嵌'}")
        return 0

    if args.kb_action == "clear":
        store = build_store(cfg)
        store.clear()
        print("知识库已清空")
        return 0

    print("用法：aicr kb {ingest|search|stats|clear} ...")
    return 0


def _print_brief(path: str, result: dict) -> None:
    stars = {"critical": "!!!", "major": "!! ", "minor": "!  ", "suggestion": "   "}
    print(f"  ✓ 评分 {result['score']} | 问题 {result['issueCount']} 个 | 摘要: {result['summary'][:60]}")
    for issue in result["issues"][:10]:
        line = f"@{issue['line']}" if issue.get("line") else ""
        print(f"    [{stars.get(issue['severity'], '   ')}]{line} {issue['title']}")


if __name__ == "__main__":
    raise SystemExit(main())
