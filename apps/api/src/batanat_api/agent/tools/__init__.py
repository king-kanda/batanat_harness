"""Tool registration.

Importing this package registers every tool exactly once. `capabilities`
validates its table against the resulting registry at startup, so a name that
does not exist here fails the boot rather than a run.
"""

from batanat_api.agent.tools import placeholders  # noqa: F401 — fake tools for tests
from batanat_api.agent.tools.real_tools import register_all

register_all()
