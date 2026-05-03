"""Session migration utilities."""
from pathlib import Path
import shutil
import json


def migrate_flat_sessions_to_project(sessions_dir: Path, project_name: str):
    """
    Move sessions/*.json to sessions/{project_name}/*.json

    Args:
        sessions_dir: Base sessions directory
        project_name: Target project name
    """
    if not sessions_dir.exists():
        print(f"Sessions directory not found: {sessions_dir}")
        return

    # Create project sessions directory
    project_sessions = sessions_dir / project_name
    project_sessions.mkdir(parents=True, exist_ok=True)

    # Find all JSON files in root sessions directory
    migrated = 0
    for session_file in sessions_dir.glob("*.json"):
        target_file = project_sessions / session_file.name

        # Validate JSON before moving
        try:
            with open(session_file) as f:
                json.load(f)
        except Exception as e:
            print(f"Skipping invalid session {session_file.name}: {e}")
            continue

        # Move file
        shutil.move(str(session_file), str(target_file))
        migrated += 1
        print(f"Migrated: {session_file.name}")

    print(f"\nMigration complete: {migrated} sessions moved to {project_sessions}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migrate ADE sessions to project structure")
    parser.add_argument("--project-name", required=True, help="Target project name")
    parser.add_argument("--sessions-dir", default="sessions", help="Sessions directory")

    args = parser.parse_args()

    sessions_dir = Path(args.sessions_dir)
    migrate_flat_sessions_to_project(sessions_dir, args.project_name)
