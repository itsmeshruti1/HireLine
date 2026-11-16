"""Grant an existing, confirmed Supabase Auth account an application staff role."""
import argparse
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True, help="Supabase Auth user UUID (never a local demo user ID)")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", choices=["admin", "recruiter", "manager"], default="recruiter")
    args = parser.parse_args()
    uuid.UUID(args.id)
    from app.config import get_settings
    from app.db import make_database
    from app.models import User
    from sqlalchemy.orm import Session
    settings = get_settings()
    engine, _ = make_database(settings.database_url)
    with Session(engine) as session:
        existing = session.get(User, args.id)
        if existing:
            existing.email, existing.name, existing.role = args.email.lower(), args.name, args.role
        else:
            session.add(User(id=args.id, email=args.email.lower(), name=args.name, role=args.role))
        session.commit()
    engine.dispose()
    print(f"Granted {args.role} access to {args.email}. No passwords were created or changed.")


if __name__ == "__main__":
    main()
