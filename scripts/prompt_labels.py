"""Quản lý prompt `day13-chat` trong project Langfuse cá nhân.

    python scripts/prompt_labels.py setup          # tạo v1 (baseline, production) và v2 (candidate)
    python scripts/prompt_labels.py status         # in version và labels hiện tại
    python scripts/prompt_labels.py promote 2      # chuyển label production sang version 2
    python scripts/prompt_labels.py promote 1      # rollback production về version 1
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from app.prompt_management import DEFAULT_PROMPT_TEMPLATE

PROMPT_V1 = DEFAULT_PROMPT_TEMPLATE
# v2 chỉ đổi format câu trả lời; vẫn giữ nguyên ba biến của prompt contract.
PROMPT_V2 = (
    "Answer in at most 3 short bullet points, using only the docs below.\n"
    + DEFAULT_PROMPT_TEMPLATE
)


def prompt_name() -> str:
    return os.getenv("LANGFUSE_PROMPT_NAME", "day13-chat")


def list_versions(client) -> list:
    versions = []
    version = 1
    while True:
        try:
            versions.append(
                client.get_prompt(prompt_name(), version=version, cache_ttl_seconds=0, max_retries=0)
            )
        except Exception:
            return versions
        version += 1


def status(client) -> None:
    versions = list_versions(client)
    if not versions:
        print(f"Chưa có prompt '{prompt_name()}'. Chạy: python scripts/prompt_labels.py setup")
        return
    for prompt in versions:
        print(f"{prompt_name()} v{prompt.version}: labels={prompt.labels}")


def setup(client) -> None:
    if list_versions(client):
        print("Prompt đã tồn tại, không tạo thêm version.")
    else:
        client.create_prompt(
            name=prompt_name(),
            prompt=PROMPT_V1,
            labels=["baseline", "production"],
            commit_message="v1 baseline: template gốc của lab",
        )
        client.create_prompt(
            name=prompt_name(),
            prompt=PROMPT_V2,
            labels=["candidate"],
            commit_message="v2 candidate: giới hạn câu trả lời tối đa 3 bullet",
        )
    status(client)


def promote(client, version: int) -> None:
    # Langfuse chỉ cho một version giữ mỗi label, nên gán cho version mới sẽ tự gỡ khỏi version cũ.
    client.update_prompt(name=prompt_name(), version=version, new_labels=["production"])
    print(f"Đã chuyển label production sang v{version}.")
    status(client)


def main() -> None:
    configure_utf8_stdio()
    load_dotenv(REPO_ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup")
    sub.add_parser("status")
    promote_parser = sub.add_parser("promote")
    promote_parser.add_argument("version", type=int)
    args = parser.parse_args()

    from langfuse import get_client

    client = get_client()
    if args.command == "setup":
        setup(client)
    elif args.command == "status":
        status(client)
    else:
        promote(client, args.version)
    client.flush()


if __name__ == "__main__":
    main()
