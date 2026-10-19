"""Write new private owner-login material without replacing existing environment files."""

import getpass
import hashlib
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet


def main():
    password = getpass.getpass("New owner passphrase (at least 16 characters): ")
    confirmation = getpass.getpass("Repeat passphrase: ")
    if password != confirmation or len(password) < 16:
        raise SystemExit("Passphrases must match and contain at least 16 characters")
    salt = secrets.token_hex(16)
    hashed = hashlib.scrypt(
        password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=64
    ).hex()
    target = Path(__file__).resolve().parents[1] / "frontend.private.env"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(
            f"FRONTEND_PASSWORD_HASH={salt}:{hashed}\nFRONTEND_SESSION_SECRET={secrets.token_urlsafe(48)}\nRESUME_ENCRYPTION_KEY={Fernet.generate_key().decode()}\n"
        )
    print(
        "Wrote backend/frontend.private.env with mode 0600. Existing .env files were not changed."
    )
    print(
        "Review and add these entries to backend/.env privately. Keep the resume key stable after the first upload."
    )


if __name__ == "__main__":
    main()
