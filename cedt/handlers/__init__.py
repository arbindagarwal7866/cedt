"""Context handlers: they read the student's source code to make each
knowledge-base explanation specific (real line, did-you-mean, fixed line)."""
from .base import REGISTRY, Context, Result, handler  # noqa: F401
from . import preproc_lex  # noqa: F401
from . import syntax  # noqa: F401
from . import semantic  # noqa: F401
from . import flow  # noqa: F401
from . import linker  # noqa: F401
