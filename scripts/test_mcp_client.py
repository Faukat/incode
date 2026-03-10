from __future__ import annotations

import asyncio
import json

from fastmcp.client import Client, StdioTransport


async def main() -> None:
    transport = StdioTransport(
        command="uv",
        args=["run", "--directory", r"D:\workspace_2\incode", "repo-indexer-mcp"],
        cwd=r"D:\workspace_2\incode",
        env={
            "REPO_INDEXER_ROOT": r"D:\workspace_2",
            "POSTGRES_HOST": "localhost",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "code_indexer",
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "postgres",
            "EMBEDDING_MODEL": "sentence-transformers/all-MiniLM-L6-v2",
            "QUERY_MIN_SCORE": "0.10",
            "QUERY_FALLBACK_MIN_SCORE": "0.03",
            "QUERY_CANDIDATE_MULTIPLIER": "5",
            "LEXICAL_DB_SCORE_WEIGHT": "0.25",
            "RESULT_PREVIEW_CHARS": "2000",
        },
    )

    async with Client(transport, timeout=60, init_timeout=60) as client:
        tools = await client.list_tools()
        print("TOOLS", sorted(tool.name for tool in tools))

        setup = await client.call_tool("setup_service_tool", {})
        print("SETUP", setup)

        search = await client.call_tool(
            "search_code_tool",
            {
                "project_name": "vanna",
                "query": "how does authentication work",
                "limit": 3,
                "min_score": 0.03,
            },
        )
        print("SEARCH", json.dumps(search.structured_content, default=str))


if __name__ == "__main__":
    asyncio.run(main())
