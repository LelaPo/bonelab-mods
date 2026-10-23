import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

MODIO_API_KEY = os.getenv("MODIO_API_KEY", "")
MODIO_GAME_ID = os.getenv("MODIO_GAME_ID", "3809")
MASTER_GIST_ID = os.getenv("MASTER_GIST_ID", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

IS_AUTHOR_MODE = bool(GITHUB_TOKEN)
MODIO_BASE_URL = "https://api.mod.io/v1"

def get_bonelab_mods_path() -> Path:
    user_profile = os.environ.get("USERPROFILE")
    if not user_profile:
        return Path.cwd() / "Mods"
    return Path(user_profile) / "AppData" / "LocalLow" / "Stress Level Zero" / "BONELAB" / "Mods"