from mir.backends.base import Backend, BackendRegistry, emit_to_directory
from mir.backends.structured_text import SAFETY_NOTICE, StructuredTextBackend

registry = BackendRegistry([StructuredTextBackend()])

__all__ = [
    "Backend",
    "BackendRegistry",
    "SAFETY_NOTICE",
    "StructuredTextBackend",
    "emit_to_directory",
    "registry",
]
