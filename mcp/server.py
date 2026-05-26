import os
import sqlite3
from typing import Optional
from fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

DB_PATH = os.environ.get("DB_PATH", "/home/deploy/BrewSecure/backend/brewsecure.db")
MCP_SECRET_TOKEN = os.environ.get("MCP_SECRET_TOKEN", "")
PORT = int(os.environ.get("MCP_PORT", "3002"))

mcp = FastMCP("BrewSecure Inventory MCP")


def get_db():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row):
    return dict(row)


# ── Auth middleware ────────────────────────────────────────────────────────────

class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Health / introspection paths that don't need auth
        auth = request.headers.get("Authorization", "")
        if MCP_SECRET_TOKEN and auth != f"Bearer {MCP_SECRET_TOKEN}":
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Returns the full BrewSecure product catalogue. Use this when the customer "
        "asks what coffees are available, wants to browse the range, asks about categories "
        "(Light, Medium, Dark, Blends), or needs an overview of what's in stock."
    )
)
def get_all_products() -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT id, name, description, price, stock, category, badge, rating,
                   roastLevel, process, altitude, origin, region, notes
            FROM products
            ORDER BY rating DESC
            """
        ).fetchall()
        return [row_to_dict(r) for r in rows]
    finally:
        conn.close()


@mcp.tool(
    description=(
        "Returns full details for a single product by its numeric ID. Use this "
        "when the customer asks about a specific coffee by name and you already know its ID, "
        "or when you need to confirm current stock and price for a specific item."
    )
)
def get_product_by_id(product_id: int) -> dict:
    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT id, name, description, price, stock, category, badge, rating,
                   roastLevel, process, altitude, origin, region, notes
            FROM products
            WHERE id = ?
            """,
            (product_id,),
        ).fetchone()
        if row is None:
            return {"error": f"Product with id {product_id} not found"}
        return row_to_dict(row)
    finally:
        conn.close()


@mcp.tool(
    description=(
        "Searches BrewSecure products by keyword, category, origin, or tasting "
        "notes. Use this when the customer describes what they want (e.g. 'fruity light roast', "
        "'Ethiopian coffee', 'something chocolatey', 'low acidity') rather than asking for "
        "a specific product by name."
    )
)
def search_products(
    query: str,
    category: Optional[str] = None,
    in_stock_only: bool = True,
) -> list[dict]:
    conn = get_db()
    try:
        like = f"%{query}%"
        conditions = [
            "(name LIKE ? OR description LIKE ? OR origin LIKE ? OR region LIKE ? OR notes LIKE ?)"
        ]
        params: list = [like, like, like, like, like]

        if category:
            conditions.append("category = ?")
            params.append(category)

        if in_stock_only:
            conditions.append("stock > 0")

        where = " AND ".join(conditions)
        rows = conn.execute(
            f"""
            SELECT id, name, description, price, stock, category, badge, rating,
                   roastLevel, process, altitude, origin, region, notes
            FROM products
            WHERE {where}
            ORDER BY rating DESC
            LIMIT 6
            """,
            params,
        ).fetchall()
        return [row_to_dict(r) for r in rows]
    finally:
        conn.close()


@mcp.tool(
    description=(
        "Returns the current stock level for one or more products by ID. Use "
        "this when the customer asks if something is available, asks about stock levels, or "
        "before recommending a product to confirm it's not sold out."
    )
)
def check_stock(product_ids: list[int]) -> list[dict]:
    conn = get_db()
    try:
        placeholders = ",".join("?" * len(product_ids))
        rows = conn.execute(
            f"SELECT id, name, stock FROM products WHERE id IN ({placeholders})",
            product_ids,
        ).fetchall()
        return [
            {"id": r["id"], "name": r["name"], "stock": r["stock"], "in_stock": r["stock"] > 0}
            for r in rows
        ]
    finally:
        conn.close()


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = mcp.http_app()
    app.add_middleware(BearerAuthMiddleware)

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
