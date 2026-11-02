"""Lock interprocesso compartilhado por Streamlit e importador; sem dependências além de filelock."""
from functools import wraps
from pathlib import Path
from filelock import FileLock


def excel_lock(path):
    p = Path(path).resolve()
    return FileLock(str(p) + '.j2i-sync.lock', timeout=120)


def proteger_gravacao_excel(fn):
    @wraps(fn)
    def wrapper(caminho, *args, **kwargs):
        with excel_lock(caminho):
            return fn(caminho, *args, **kwargs)
    return wrapper
