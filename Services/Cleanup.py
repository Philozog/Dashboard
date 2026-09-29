"""Legacy entry point: run safe migrations instead of deleting duplicate rows."""

from Services.database import backup_database, initialize_database

if __name__ == "__main__":
    path = initialize_database()
    print(f"Database ready: {path}; backup: {backup_database(path)}")
