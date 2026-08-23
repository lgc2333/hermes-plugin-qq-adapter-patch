try:
    from .adapter import register
except ImportError:  # pytest may import a hyphenated directory plugin as top-level __init__
    from adapter import register

__all__ = ["register"]
