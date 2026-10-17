from typing import Protocol

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

# Tools that change data. The graph pauses for customer confirmation before running these.
WRITE_TOOLS = {"book_appointment", "cancel_booking", "reschedule_booking"}


class ToolProvider(Protocol):
    """Supplies the booking tools for one business. Lets tests swap in local fakes."""

    async def get_tools(self, business_id: str) -> list[BaseTool]: ...


class MCPToolProvider:
    """Loads tools from the VoxDesk MCP server over Streamable HTTP.

    The business is sent as a header on the connection, so the LLM never sees or
    chooses the tenant — tool schemas contain no business_id argument at all.
    """

    def __init__(self, url: str, api_key: str):
        self._url = url
        self._api_key = api_key

    async def get_tools(self, business_id: str) -> list[BaseTool]:
        client = MultiServerMCPClient(
            {
                "voxdesk": {
                    "transport": "streamable_http",
                    "url": self._url,
                    "headers": {
                        "Authorization": f"Bearer {self._api_key}",
                        "X-Business-Id": business_id,
                    },
                }
            }
        )
        # Lists the server's tools; each returned tool opens a short MCP request when called.
        return await client.get_tools()
