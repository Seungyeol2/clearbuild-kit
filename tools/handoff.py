#!/usr/bin/env python3
"""Bounded, local file handoffs. No AI, networking, background service, or wakeups."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time

INCOMING = {
    "A": ("B_HANDOFF.md", "C_HANDOFF.md"),
    "B": ("PROJECT.md", "DECISIONS.md"),
    "C": ("PROJECT.md", "DECISIONS.md"),
}
MAX_BYTES = 256 * 1024


class HandoffError(Exception):
    pass


def regular_path(root: Path, *parts: str) -> Path:
    """Do not follow handoff/state symlinks outside the selected worklog."""
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise HandoffError(f"심볼릭 링크는 처리하지 않습니다: {path}")
    return path


def snapshot(root: Path, name: str) -> dict:
    path = regular_path(root, name)
    if path.exists() and not path.is_file():
        raise HandoffError(f"일반 파일이 아닙니다: {path}")
    try:
        # One read returns the exact bytes to which its digest applies. Writers
        # must still finish saving before publishing READY; no external lock exists.
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            data = stream.read(MAX_BYTES + 1)
            after = os.fstat(stream.fileno())
        current = path.stat()
    except FileNotFoundError:
        return {"file": name, "sha256": None, "text": None}
    if not path.is_file():
        raise HandoffError(f"일반 파일이 아닙니다: {path}")
    if len(data) > MAX_BYTES:
        raise HandoffError(f"전달 파일 크기는 {MAX_BYTES}바이트 이하여야 합니다: {path}")
    if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size) or (
        after.st_dev, after.st_ino, after.st_mtime_ns, after.st_size
    ) != (current.st_dev, current.st_ino, current.st_mtime_ns, current.st_size):
        raise HandoffError(f"읽는 중 파일이 바뀌었습니다. 저장 완료 후 다시 읽으세요: {path}")
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HandoffError(f"UTF-8 텍스트가 아닙니다: {path}") from exc
    return {"file": name, "sha256": hashlib.sha256(data).hexdigest(), "text": content}


def receipt_path(root: Path, role: str, name: str) -> Path:
    return regular_path(root, ".clearbuild", "receipts", role, name + ".json")


def receipt(root: Path, role: str, name: str) -> str | None:
    path = receipt_path(root, role, name)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))["sha256"]
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("invalid digest")
        return value
    except (ValueError, KeyError, TypeError) as exc:
        raise HandoffError(f"읽음 기록이 손상되었습니다. 확인 후 해당 기록만 복구하세요: {path}") from exc


def status(root: Path, role: str) -> list[dict]:
    rows = []
    for name in INCOMING[role]:
        item = snapshot(root, name)
        previous = receipt(root, role, name)
        item.pop("text")
        item["state"] = (
            "DELETED" if item["sha256"] is None and previous else
            "MISSING" if item["sha256"] is None else
            "READ" if item["sha256"] == previous else "UNREAD"
        )
        rows.append(item)
    return rows


def output_status(root: Path, role: str, rows: list[dict], as_json: bool) -> None:
    if as_json:
        print(json.dumps({"worklog": str(root), "role": role, "files": rows}, ensure_ascii=False))
        return
    print(f"{role} 수신 파일: {root}")
    for item in rows:
        print(f"{item['state']:7} {item['file']}  sha256={item['sha256'] or '-'}")
    print("UNREAD는 변경 감지일 뿐입니다. read로 내용을 검토한 뒤 그 SHA-256으로 ack하세요.")


@contextmanager
def role_lock(root: Path, role: str):
    state = regular_path(root, ".clearbuild")
    state.mkdir(exist_ok=True)
    lock = regular_path(root, ".clearbuild", f"{role}.lock")
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise HandoffError(
            f"{role}의 다른 ack가 진행 중이거나 중단 흔적이 있습니다: {lock}. "
            "실행 중인 ack가 없는지 확인하기 전 삭제하지 마세요."
        ) from exc
    try:
        yield
    finally:
        lock.rmdir()


def acknowledge(root: Path, role: str, name: str, digest: str) -> None:
    with role_lock(root, role):
        item = snapshot(root, name)
        if item["sha256"] is None:
            raise HandoffError(f"없는 파일을 읽음 처리할 수 없습니다: {name}")
        if item["sha256"] != digest:
            raise HandoffError(f"읽은 뒤 파일이 바뀌었거나 해시가 틀렸습니다. {name}을 다시 읽으세요.")
        target = receipt_path(root, role, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".receipt-", dir=target.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({"sha256": digest}, stream)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    print(f"읽음 기록: {role} / {name} / {digest}. 작업 완료나 계약 승인은 아닙니다.")


def initialize(root: Path) -> None:
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise HandoffError(f"비어 있지 않은 경로를 덮어쓰지 않습니다: {root}")
    root.mkdir(parents=True, exist_ok=True)
    templates = Path(__file__).resolve().parent.parent / "templates"
    for name, source in (("PROJECT.md", "PROJECT.md"), ("DECISIONS.md", "DECISIONS.md"),
                         ("B_HANDOFF.md", "HANDOFF.md"), ("C_HANDOFF.md", "HANDOFF.md")):
        # Exclusive creation preserves a file created concurrently. A partial
        # failure is reported; never delete someone else's files to roll back.
        destination = regular_path(root, name)
        content = (templates / source).read_text(encoding="utf-8")
        with destination.open("x", encoding="utf-8") as stream:
            stream.write(content)
    print(f"준비 완료: {root}. 실제 세션 간 공유 여부는 SESSION_HANDOFFS.md의 왕복 확인을 하세요.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worklog", default="worklog", help="세 세션이 실제로 공유하는 전달 폴더")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="비어 있는 폴더에 전달 파일 4개 생성")
    for verb in ("status", "read", "ack", "watch"):
        command = commands.add_parser(verb)
        command.add_argument("--role", required=True, choices=tuple(INCOMING))
        if verb in ("status", "watch"):
            command.add_argument("--json", action="store_true")
        if verb in ("read", "ack"):
            command.add_argument("--file", required=True)
        if verb == "ack":
            command.add_argument("--sha256", required=True)
        if verb == "watch":
            command.add_argument("--timeout", type=float, default=15, help="1~60초, 기본 15초")
            command.add_argument("--interval", type=float, default=2, help="1~10초, 기본 2초")
    args = parser.parse_args(argv)
    root = Path(args.worklog).expanduser().resolve()
    try:
        if args.command == "init":
            initialize(root)
            return 0
        if not root.is_dir():
            raise HandoffError(f"전달 폴더가 없습니다: {root}")
        if args.command in ("read", "ack") and args.file not in INCOMING[args.role]:
            raise HandoffError(f"{args.role}가 읽음 기록을 남길 수 있는 파일: {', '.join(INCOMING[args.role])}")
        if args.command == "read":
            item = snapshot(root, args.file)
            if item["sha256"] is None:
                raise HandoffError(f"파일이 없습니다: {args.file}")
            print(f"FILE: {root / args.file}\nSHA256: {item['sha256']}\n---")
            print(item["text"], end="" if item["text"].endswith("\n") else "\n")
        elif args.command == "ack":
            acknowledge(root, args.role, args.file, args.sha256)
        elif args.command == "status":
            output_status(root, args.role, status(root, args.role), args.json)
        elif args.command == "watch":
            if not (1 <= args.timeout <= 60 and 1 <= args.interval <= 10):
                raise HandoffError("timeout은 1~60초, interval은 1~10초여야 합니다.")
            end = time.monotonic() + args.timeout
            while True:
                rows = status(root, args.role)
                if any(row["state"] in ("UNREAD", "DELETED") for row in rows):
                    output_status(root, args.role, rows, args.json)
                    return 0
                remaining = end - time.monotonic()
                if remaining <= 0:
                    output_status(root, args.role, rows, args.json)
                    print("대기 종료: 새 변경 없음. 세션을 다시 깨우거나 계속 폴링하지 않습니다.", file=sys.stderr)
                    return 3
                time.sleep(min(args.interval, remaining))
        return 0
    except (HandoffError, OSError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("대기를 중단했습니다. 전달 파일은 바뀌지 않았습니다.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
