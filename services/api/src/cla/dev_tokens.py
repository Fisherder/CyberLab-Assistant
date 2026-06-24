from __future__ import annotations

from cla.security import create_dev_token
from cla.settings import load_settings


def main() -> None:
    settings = load_settings()
    print("teacher:")
    print(create_dev_token(settings, subject="teacher@example.edu", roles=["teacher"]))
    print("student:")
    print(create_dev_token(settings, subject="student@example.edu", roles=["student"]))


if __name__ == "__main__":
    main()

