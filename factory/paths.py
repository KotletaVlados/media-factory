"""Where the factory reads and writes (design factory.md §5.2).

Content (stock folders and the rules file) lives under the content folder, which git ignores.
Runner state lives outside every checkout. The poster's own paths (env file, image library,
post record and X ledger) are resolved by the poster's functions, so both tools agree.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from poster import config

STOCK = "stock"
RULES_FILE = "rules.json"
PACKAGES = "packages"


def resolve_content_dir(flag: str | None, environ) -> str:
    if flag:
        return flag
    if environ.get("MF_CONTENT_DIR"):
        return environ["MF_CONTENT_DIR"]
    return os.path.join(config.REPO_ROOT, "content")


def resolve_factory_state_dir(flag: str | None, environ) -> str:
    if flag:
        return flag
    if environ.get("MF_FACTORY_STATE_DIR"):
        return environ["MF_FACTORY_STATE_DIR"]
    base = environ.get("XDG_STATE_HOME") or os.path.join(
        environ.get("HOME") or os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "media-factory", "factory")


@dataclass(frozen=True)
class Paths:
    env_file: str
    content: str
    state: str          # factory state (journal, heartbeat, runner lock)
    poster_state: str   # poster record and X ledger
    library: str

    @property
    def stock(self) -> str:
        return os.path.join(self.content, STOCK)

    @property
    def rules(self) -> str:
        return os.path.join(self.content, RULES_FILE)

    @property
    def packages(self) -> str:
        return os.path.join(self.content, PACKAGES)


def resolve(environ, *, env_file=None, content=None, state=None) -> Paths:
    return Paths(env_file=config.resolve_env_path(env_file, environ),
                 content=resolve_content_dir(content, environ),
                 state=resolve_factory_state_dir(state, environ),
                 poster_state=config.resolve_state_dir(None, environ),
                 library=config.resolve_library(None, environ))
