from dataclasses import dataclass

from langchain_core.tools import BaseTool

from app.tools.api_client import StockSenseClient
from app.tools.read_tools import make_read_tools
from app.tools.write_tools import make_write_tools


@dataclass(frozen=True)
class ToolSet:
    """All tools, split by kind. The split IS the allow-list:
    read tools run freely, write tools only after the pause."""

    read: list[BaseTool]
    write: list[BaseTool]

    @property
    def all(self) -> list[BaseTool]:
        return [*self.read, *self.write]

    @property
    def write_names(self) -> set[str]:
        return {t.name for t in self.write}


def make_tools(client: StockSenseClient) -> ToolSet:
    return ToolSet(read=make_read_tools(client), write=make_write_tools(client))