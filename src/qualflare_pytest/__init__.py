"""Native pytest plugin for Qualflare.

Writes a Collect report that `qualflare-cli` uploads. Makes no network calls.
"""

from .runtime import qualflare

__version__ = "0.1.1"
__all__ = ["qualflare", "__version__"]
