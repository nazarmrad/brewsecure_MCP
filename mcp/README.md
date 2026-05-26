# BrewSecure MCP Server

FastMCP server exposing BrewSecure inventory data as four MCP tools over HTTP streamable transport.

## Tools

| Tool | Description |
|------|-------------|
| `get_all_products` | Full product catalogue |
| `get_product_by_id` | Single product by numeric ID |
| `search_products` | Keyword / category / origin / notes search |
| `check_stock` | Stock level for one or more product IDs |

## Requirements

- Python 3.11+
- SQLite3 (stdlib — no extra install needed)

```bash
pip3 install -r mcp/requirements.txt
```

## Running locally

```bash
export MCP_SECRET_TOKEN="your-token-here"
export DB_PATH="backend/brewsecure.db"
python3 mcp/server.py
```

Server starts on port `3002` by default. Override with `MCP_PORT`.

## Running via PM2 (production)

Add the `brewsecure-mcp` entry to `ecosystem.config.js` (see repo root) then:

```bash
pm2 start ecosystem.config.js --only brewsecure-mcp
pm2 save
```

## Nginx

Add the `/mcp/` location block to `/etc/nginx/sites-enabled/org-lnd-01.brewsecure.store`:

```nginx
location /mcp/ {
    proxy_pass http://127.0.0.1:3002;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 300s;
    proxy_buffering off;
    proxy_cache off;
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

## Auth

All requests must include:

```
Authorization: Bearer <MCP_SECRET_TOKEN>
```

Missing or incorrect token → HTTP 401.

Internal calls from the Express app (localhost) still pass the header — just set the same token in both services, or skip the header check by leaving `MCP_SECRET_TOKEN` empty for the local call in `chat.js`.

## Verifying the server

```bash
curl -H "Authorization: Bearer <token>" \
  https://org-lnd-01.brewsecure.store/mcp/tools
```

## ElevenLabs integration

1. Go to `elevenlabs.io/app/agents/integrations`
2. **Add Custom MCP Server**
   - Name: `BrewSecure Inventory`
   - Server URL: `https://org-lnd-01.brewsecure.store/mcp/`
   - Secret Token: value of `MCP_SECRET_TOKEN`
3. Set all four tools to **Auto-approved** (all are read-only).
