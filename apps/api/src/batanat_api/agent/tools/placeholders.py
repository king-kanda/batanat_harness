"""Two real, trivial tools used to exercise the agent loop in tests.

`echo_fact` and `count_words` do exactly what they say. They are registered but
bound to no trigger in the production capability table — tests patch the table
to reach them, which keeps the shipped policy honest.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from batanat_api.agent.tools.registry import ToolContext, ToolSpec, register

# --- real tools, used to exercise the loop -----------------------------------


class EchoFactArgs(BaseModel):
    fact: str = Field(description="A short statement to record.")


async def _echo_fact(context: ToolContext, args: EchoFactArgs) -> dict[str, Any]:
    return {"recorded": args.fact, "at": datetime.now(UTC).isoformat()}


class CountWordsArgs(BaseModel):
    text: str = Field(description="Text to count the words of.")


async def _count_words(context: ToolContext, args: CountWordsArgs) -> dict[str, Any]:
    return {"words": len(args.text.split())}


register(
    ToolSpec(
        name="echo_fact",
        description="Record a short fact and return it with a timestamp.",
        args_model=EchoFactArgs,
        handler=_echo_fact,
    )
)
register(
    ToolSpec(
        name="count_words",
        description="Count the words in a piece of text.",
        args_model=CountWordsArgs,
        handler=_count_words,
    )
)


# The real handlers for every other tool live in `real_tools.py`. This module
# keeps only the two fake tools, which exist so tests can drive the agent loop
# without stubbing anything.
