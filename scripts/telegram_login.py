"""One-time interactive login for the Private-chat Telegram bridge.

Telegram authenticates a real account, not a service, so this step cannot be automated:
it sends a code to your phone and you type it in here. What comes out is a session
string — paste it into `LOCUS_TELEGRAM_SESSION` and the backend can message from your
account without ever logging in again.

    python scripts/telegram_login.py

You need an API id and hash first, from https://my.telegram.org → API development tools.
Pass them as arguments or in the environment:

    LOCUS_TELEGRAM_API_ID=... LOCUS_TELEGRAM_API_HASH=... python scripts/telegram_login.py

Treat the printed string like a password: it is full access to the account, and anyone
holding it can read and send your messages. Do not commit it.
"""

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a Telegram session string for Locus")
    parser.add_argument("--api-id", default=os.getenv("LOCUS_TELEGRAM_API_ID", ""))
    parser.add_argument("--api-hash", default=os.getenv("LOCUS_TELEGRAM_API_HASH", ""))
    args = parser.parse_args()

    try:
        from telethon.sync import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        print("telethon is not installed. Run: pip install -r backend/requirements.txt", file=sys.stderr)
        return 1

    api_id = (args.api_id or input("API id: ")).strip()
    api_hash = (args.api_hash or input("API hash: ")).strip()
    if not api_id.isdigit() or not api_hash:
        print("An API id (digits) and API hash are both required.", file=sys.stderr)
        return 1

    with TelegramClient(StringSession(), int(api_id), api_hash) as client:
        me = client.get_me()
        name = " ".join(part for part in [me.first_name or "", me.last_name or ""] if part)
        print()
        print(f"Signed in as {name or me.username or me.id}.")
        print()
        print("Add these to your .env (the session string is a credential — keep it secret):")
        print()
        print(f"LOCUS_TELEGRAM_API_ID={api_id}")
        print(f"LOCUS_TELEGRAM_API_HASH={api_hash}")
        print(f"LOCUS_TELEGRAM_SESSION={client.session.save()}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
