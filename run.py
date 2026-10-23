import sys
from src.cli.app import run_app

if __name__ == "__main__":
    try:
        run_app()
    except KeyboardInterrupt:
        print("\nПрервано пользователем.")
        sys.exit(0)