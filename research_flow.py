"""
research_flow.py
────────────────
Flow factories for the research paper comparison.

create_tutorial_flow()      → production flow (sync WriteChapters)
create_async_tutorial_flow() → research flow  (AsyncWriteChapters)

Both share the same first four nodes (FetchRepo … OrderChapters) so when
research_app.py runs the two flows sequentially on the same repository it
reuses the cached LLM responses, making the WriteChapters timing the only
real variable between runs.
"""

from pocketflow import Flow
from nodes import (
    FetchRepo,
    IdentifyAbstractions,
    AnalyzeRelationships,
    OrderChapters,
    WriteChapters,
    AsyncWriteChapters,
    CombineTutorial,
)


def create_tutorial_flow():
    """Production flow — sync BatchNode WriteChapters."""
    fetch_repo             = FetchRepo()
    identify_abstractions  = IdentifyAbstractions(max_retries=5, wait=20)
    analyze_relationships  = AnalyzeRelationships(max_retries=5, wait=20)
    order_chapters         = OrderChapters(max_retries=5, wait=20)
    write_chapters         = WriteChapters(max_retries=5, wait=20)
    combine_tutorial       = CombineTutorial()

    fetch_repo            >> identify_abstractions
    identify_abstractions >> analyze_relationships
    analyze_relationships >> order_chapters
    order_chapters        >> write_chapters
    write_chapters        >> combine_tutorial

    return Flow(start=fetch_repo)


def create_async_tutorial_flow():
    """
    Research flow — AsyncWriteChapters (ThreadPoolExecutor).

    Intended to run AFTER create_tutorial_flow() on the *same* repository
    so that the sync chapter time is already recorded in shared and the
    speedup ratio can be computed by AsyncWriteChapters.post().

    Because LLM responses are cached, the async run isolates parallelism
    benefit from API I/O, which is exactly what the paper measures.

    NOTE: This flow re-runs all upstream nodes so that shared["chapters"]
    is correctly set for CombineTutorial.  LLM cache makes the upstream
    nodes nearly instant on the second run.
    """
    fetch_repo             = FetchRepo()
    identify_abstractions  = IdentifyAbstractions(max_retries=5, wait=20)
    analyze_relationships  = AnalyzeRelationships(max_retries=5, wait=20)
    order_chapters         = OrderChapters(max_retries=5, wait=20)
    async_write_chapters   = AsyncWriteChapters(max_retries=5, wait=20)
    combine_tutorial       = CombineTutorial()

    fetch_repo            >> identify_abstractions
    identify_abstractions >> analyze_relationships
    analyze_relationships >> order_chapters
    order_chapters        >> async_write_chapters
    async_write_chapters  >> combine_tutorial

    return Flow(start=fetch_repo)
