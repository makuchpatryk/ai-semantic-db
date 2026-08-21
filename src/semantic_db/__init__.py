import logging

__version__ = "0.1.0"

# The library convention: without it, stdlib logging's last-resort handler would print
# warnings to stderr and corrupt the CLI's Rich output. Telemetry attaches the real
# handler to this same logger when it is enabled.
logging.getLogger(__name__).addHandler(logging.NullHandler())
