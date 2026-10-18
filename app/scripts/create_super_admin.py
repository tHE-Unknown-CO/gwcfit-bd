import argparse
import getpass

from sqlalchemy import select

from app.auth.passwords import hash_password
from app.database.session import SessionLocal
from app.models.enums import RoleName
from app.models.user import User


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the initial PulseFit application owner.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    password = getpass.getpass("Password: ")
    if len(password) < 8:
        raise SystemExit("Password must be at least 8 characters.")

    email = args.email.strip().lower()
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == email)):
            raise SystemExit("A user with this email already exists.")
        user = User(
            gym_id=None,
            email=email,
            hashed_password=hash_password(password),
            full_name=args.name.strip(),
            role=RoleName.SUPER_ADMIN.value,
            is_email_verified=True,
        )
        db.add(user)
        db.commit()
        print(f"Application owner created: {email}")


if __name__ == "__main__":
    main()
