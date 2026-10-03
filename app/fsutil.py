"""Small filesystem helpers shared by the JSON writers."""
import os
import threading
import time
from pathlib import Path


def replace_with_retry(tmp, dst, tries: int = 5, delay: float = 0.1) -> None:
    """os.replace, retrying briefly on PermissionError (Windows readers/antivirus/indexers).
    The tmp file is removed if the replace finally fails; the error propagates."""
    for attempt in range(tries):
        try:
            os.replace(tmp, dst)
            return
        except PermissionError:
            if attempt == tries - 1:
                Path(tmp).unlink(missing_ok=True)
                raise
            time.sleep(delay)


def atomic_write_text(path, text: str, encoding: str = "utf-8") -> None:
    """Write text to a unique tmp file (pid + thread id) next to path, then replace atomically."""
    path = Path(path)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        replace_with_retry(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
