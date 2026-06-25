"""Dev-only tooling for ctx, kept OUTSIDE the importable ``ctx`` package.

Nothing here ships in the wheel (see docs/decisions/0012). Modules under
``tools`` may import from ``ctx`` (tooling -> product); ``ctx`` must never
import from ``tools``.
"""
