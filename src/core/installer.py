import time
import zipfile
import tempfile
import requests
from pathlib import Path
from typing import Optional, Callable
from src.config import MODIO_API_KEY


def download_and_extract(
    url: str,
    filename: str,
    target_dir: Path,
    api_key: str = MODIO_API_KEY,
    on_start: Optional[Callable[[int], None]] = None,
    on_chunk: Optional[Callable[[int, int, float], None]] = None,
    on_extract: Optional[Callable[[], None]] = None,
) -> Optional[str]:
    """
    Потоково скачивает zip-архив с mod.io во временную папку и распаковывает в target_dir.
    Возвращает имя распакованной папки мода (если удалось определить).
    """
    params = {"api_key": api_key} if api_key else {}

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_zip = Path(tmp_dir) / filename
        with requests.get(url, params=params, stream=True, timeout=30) as r:
            r.raise_for_status()
            total_size = int(r.headers.get("content-length", 0))

            if on_start:
                on_start(total_size)

            downloaded = 0
            start_t = time.time()

            with open(tmp_zip, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 128):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)

                    elapsed = time.time() - start_t
                    speed_mb = (downloaded / (1024 * 1024)) / elapsed if elapsed > 0 else 0.0

                    if on_chunk:
                        on_chunk(len(chunk), downloaded, speed_mb)

        if on_extract:
            on_extract()

        target_dir.mkdir(parents=True, exist_ok=True)
        extracted_folder = None
        with zipfile.ZipFile(tmp_zip, "r") as z:
            namelist = z.namelist()
            if namelist:
                top_name = namelist[0].split("/")[0].split("\\")[0]
                if top_name:
                    extracted_folder = top_name
            z.extractall(target_dir)

        return extracted_folder