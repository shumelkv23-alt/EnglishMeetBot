# scripts/test_send_dm.py
"""Проверка проактивной отправки: бот сам пишет в тестовый DM (9C.3).

Space берётся из .env -> CHAT_TEST_SPACE (или аргумента командной строки).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.services.chat_sender import send_text  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a proactive DM as the bot")
    parser.add_argument("--space", help="Space name, e.g. spaces/7UqhjKAAAAE")
    parser.add_argument("--text", default="Привет! Это проверка проактивной отправки от EnglishMeetBot. 🎉")
    args = parser.parse_args()

    space = args.space or get_settings().chat_test_space
    if not space:
        raise SystemExit("Space not specified: pass --space or set CHAT_TEST_SPACE in .env")

    result = send_text(space, args.text)
    print(f"Sent to {space}: name={result.get('name')}")


if __name__ == "__main__":
    main()