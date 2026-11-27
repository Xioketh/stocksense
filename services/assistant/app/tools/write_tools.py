"""Write tools: they change stock, so the graph always pauses before running them.

The pause (interrupt_before=["write_tools"]) is the first safety layer. The API
is the second: it re-checks the line is still needs_review (409 if not), and the
UNIQUE(invoice_item_id) constraint on stock_movements is the last.
"""

import json

from langchain_core.tools import BaseTool, tool

from app.tools.api_client import ApiError, StockSenseClient
from app.tools.read_tools import clean_sku


def make_write_tools(client: StockSenseClient) -> list[BaseTool]:
    @tool
    def resolve_review_item(invoice_id: int, line_no: int, sku: str) -> str:
        """Match one needs_review invoice line to an existing product and add its qty to stock.

        Only propose this when the owner has said which product the line is.
        It never creates products. The owner approves it before it runs.
        """
        try:
            data = client.post(
                f"/invoices/{invoice_id}/items/{line_no}/resolve",
                body={"sku": clean_sku(sku)},
            )
        except ApiError as exc:
            return exc.to_json()
        # The API returns more; the LLM only needs what changed (A1 decision).
        return json.dumps({"sku": data["sku"], "added": data["added"], "new_qty": data["new_qty"]})

    return [resolve_review_item]
