module.exports = {
  apps: [
    {
      name: "brewsecure-backend",
      script: "backend/src/app.js",
      cwd: "/home/deploy/BrewSecure",
      instances: 1,
      env: {
        NODE_ENV: "production",
        PORT: 3001,
        // DB_PATH, LANGFUSE_*, etc. — set in the actual file on the server
      },
    },
    {
      name: "brewsecure-mcp",
      script: "mcp/server.py",
      interpreter: "python3",
      cwd: "/home/deploy/BrewSecure",
      env: {
        MCP_SECRET_TOKEN: "REPLACE_WITH_STRONG_RANDOM_TOKEN",
        DB_PATH: "/home/deploy/BrewSecure/backend/brewsecure.db",
        MCP_PORT: "3002",
      },
    },
  ],
};
