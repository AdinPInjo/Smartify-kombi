"""Run the server: ``python -m smartify`` or the ``smartify`` command.

``python -m smartify reset-login`` deletes the dashboard login (forgotten
password): the dashboard then shows the first-run setup again.
"""

from __future__ import annotations

import logging
import sys

import uvicorn

from smartify.config import get_settings


def reset_login() -> None:
    from smartify.db import migrate, transaction

    settings = get_settings()
    migrate(settings.db_path)
    with transaction(settings.db_path) as conn:
        deleted = conn.execute("DELETE FROM account").rowcount
    if not deleted:
        print("There was no dashboard login to delete.")
    elif settings.password:
        print("Login deleted. SMARTIFY_PASSWORD in .env is used again; remove it to get the setup.")
    else:
        from smartify.services.accounts import AccountService

        code = AccountService(settings, settings.db_path, "unused").setup_code()
        print("Login deleted. Open the dashboard to create a new one.")
        print(f"It asks for this setup code: {code}")


def main() -> None:
    if sys.argv[1:] == ["reset-login"]:
        reset_login()
        return
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    uvicorn.run(
        "smartify.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
