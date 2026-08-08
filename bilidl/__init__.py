from typing import TYPE_CHECKING

__version__ = "0.5.0"

__all__ = ["__version__", "download", "main", "TaskOutcome"]

if TYPE_CHECKING:  # 仅供类型检查与 IDE 补全，运行时不执行
    from .library import download, main
    from .utils.ui import TaskOutcome


def __getattr__(name: str):
    """延迟导入"""
    if name in {"download", "main"}:
        from . import library

        return getattr(library, name)
    if name == "TaskOutcome":
        from .utils.ui import TaskOutcome

        return TaskOutcome
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
