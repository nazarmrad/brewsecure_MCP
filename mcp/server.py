#!/usr/bin/env python3
"""BrewSecure MCP Server — FastMCP 3.x, calls BrewSecure REST API over HTTPS."""
import os
import httpx
import uvicorn
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

MCP_SECRET_TOKEN   = os.environ.get("MCP_SECRET_TOKEN", "")
BREWSECURE_API_URL = os.environ.get("BREWSECURE_API_URL", "").rstrip("/")
BREWSECURE_API_KEY = os.environ.get("BREWSECURE_API_KEY", "")
PORT = int(os.environ.get("MCP_PORT", "3002"))

mcp = FastMCP("BrewSecure Inventory")


# ── Auth ──────────────────────────────────────────────────────────────────────

def _authed(request: Request) -> bool:
    if not MCP_SECRET_TOKEN:
        return True
    parts = request.headers.get("Authorization", "").split(" ", 1)
    return len(parts) == 2 and parts[0] == "Bearer" and parts[1] == MCP_SECRET_TOKEN


# ── API client ────────────────────────────────────────────────────────────────

def _api_headers():
    h = {"Accept": "application/json"}
    if BREWSECURE_API_KEY:
        h["Authorization"] = f"Bearer {BREWSECURE_API_KEY}"
    return h


async def _get(path: str, params: dict = None):
    async with httpx.AsyncClient(timeout=10, verify=False) as client:
        r = await client.get(
            f"{BREWSECURE_API_URL}{path}", headers=_api_headers(), params=params
        )
        r.raise_for_status()
        return r.json()


# ── Internal tool implementations ─────────────────────────────────────────────

async def _get_all_products():
    products = await _get("/api/products")
    return sorted(products, key=lambda p: p.get("rating", 0), reverse=True)


async def _get_product_by_id(product_id: int):
    try:
        return await _get(f"/api/products/{product_id}")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"error": f"Product {product_id} not found"}
        raise


async def _search_products(query: str, category: str = None, in_stock_only: bool = True):
    params = {"q": query, "in_stock_only": str(in_stock_only).lower()}
    if category:
        params["category"] = category
    return await _get("/api/products/search", params=params)


async def _check_stock(product_ids: list):
    if not product_ids:
        return []
    return await _get(
        "/api/products/stock",
        params={"ids": ",".join(str(i) for i in product_ids)},
    )


# ── MCP tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_all_products() -> list:
    """Returns the full BrewSecure product catalogue. Use this when the customer
asks what coffees are available, wants to browse the range, asks about categories
(Light, Medium, Dark, Blends), or needs an overview of what's in stock."""
    return await _get_all_products()


@mcp.tool()
async def get_product_by_id(product_id: int) -> dict:
    """Returns full details for a single product by its numeric ID. Use this
when the customer asks about a specific coffee by name and you already know its ID,
or when you need to confirm current stock and price for a specific item."""
    return await _get_product_by_id(product_id)


@mcp.tool()
async def search_products(query: str, category: str = None, in_stock_only: bool = True) -> list:
    """Searches BrewSecure products by keyword, category, origin, or tasting
notes. Use this when the customer describes what they want (e.g. 'fruity light roast',
'Ethiopian coffee', 'something chocolatey', 'low acidity') rather than asking for
a specific product by name."""
    return await _search_products(query, category, in_stock_only)


@mcp.tool()
async def check_stock(product_ids: list) -> list:
    """Returns the current stock level for one or more products by ID. Use
this when the customer asks if something is available, asks about stock levels, or
before recommending a product to confirm it is not sold out."""
    return await _check_stock(product_ids)


# ── Ollama function-calling schema ────────────────────────────────────────────

OLLAMA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_all_products",
            "description": (
                "Returns the full BrewSecure product catalogue. Use this when the customer "
                "asks what coffees are available, wants to browse the range, asks about categories "
                "(Light, Medium, Dark, Blends), or needs an overview of what's in stock."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_by_id",
            "description": (
                "Returns full details for a single product by its numeric ID. Use this "
                "when the customer asks about a specific coffee by name and you already know its ID, "
                "or when you need to confirm current stock and price for a specific item."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "integer", "description": "The numeric product ID"},
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": (
                "Searches BrewSecure products by keyword, category, origin, or tasting notes. "
                "Use this when the customer describes what they want (e.g. 'fruity light roast', "
                "'Ethiopian coffee', 'something chocolatey', 'low acidity') rather than asking "
                "for a specific product by name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Free-text search term"},
                    "category": {
                        "type": "string",
                        "description": "Filter to one of: Light, Medium, Dark, Blends",
                        "enum": ["Light", "Medium", "Dark", "Blends"],
                    },
                    "in_stock_only": {
                        "type": "boolean",
                        "description": "Only return products with stock > 0 (default: true)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_stock",
            "description": (
                "Returns the current stock level for one or more products by ID. Use this "
                "when the customer asks if something is available, asks about stock levels, or "
                "before recommending a product to confirm it is not sold out."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "One or more product IDs to check",
                    },
                },
                "required": ["product_ids"],
            },
        },
    },
]

TOOL_DISPATCH = {
    "get_all_products":  lambda a: _get_all_products(),
    "get_product_by_id": lambda a: _get_product_by_id(a["product_id"]),
    "search_products":   lambda a: _search_products(**a),
    "check_stock":       lambda a: _check_stock(a["product_ids"]),
}


# ── REST routes for the Ollama/Express chat widget ────────────────────────────

@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request):
    return JSONResponse({"status": "ok"})


@mcp.custom_route("/tools", methods=["GET"])
async def list_tools(request: Request):
    if not _authed(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return JSONResponse(OLLAMA_TOOLS)


@mcp.custom_route("/call", methods=["POST"])
async def call_tool_handler(request: Request):
    if not _authed(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        body = await request.json()
        name = body.get("name", "")
        args = body.get("arguments", {})
        fn = TOOL_DISPATCH.get(name)
        if fn is None:
            return JSONResponse({"error": f"Unknown tool: {name}"}, status_code=400)
        result = await fn(args)
        return JSONResponse({"result": result})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(mcp.http_app(), host="0.0.0.0", port=PORT, log_level="info")
