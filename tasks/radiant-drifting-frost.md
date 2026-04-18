# JARVIS — MCP Integration Plan

## Context

STT, TTS, LLM layer, voice conversation loop, and quality hardening are all complete.
The remaining work is MCP integration with Claude Desktop, sandbox-first.

---

## Prerequisites (must be confirmed before starting)

```bash
tmutil status | grep Running   # Time Machine must be active with a completed backup
ls ~/jarvis-sandbox/           # sandbox directory must exist
```

---

## Steps

### 1. Audit the MCP filesystem server source

Read source before installing:
`https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem`

Confirm: path allow-list is enforced in TypeScript, symlinks outside root are rejected.

**2. Install and test the server standalone**

```bash
npx -y @modelcontextprotocol/server-filesystem ~/jarvis-sandbox/
```

**3. Configure Claude Desktop**

File to modify: `~/Library/Application Support/Claude/claude_desktop_config.json`
```json
{
  "mcpServers": {
    "jarvis-sandbox-fs": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/Users/benediktschink/jarvis-sandbox"
      ]
    }
  }
}
```

**4. Write `docs/mcp-setup.md`**

Sections: prerequisites (Time Machine, Node.js), why sandbox-first, install, configure, verify,
path traversal check, write access caveat, expanding scope conditions.

**Write access caveat:** The standard `@modelcontextprotocol/server-filesystem` exposes write tools.
These must NOT be used until this phase is validated. A proper read-only fork is required before
expanding scope beyond `~/jarvis-sandbox/`. Do not rely on prompting to prevent writes — this
violates JARVIS security rule #2.

---

## Verify

```bash
# In Claude Desktop: "List files in my sandbox"
# Expected: shows ~/jarvis-sandbox/ contents only

# Path traversal check (in Claude Desktop):
# "Read ../Documents/test.txt"
# Expected: access denied

# Confirm no accidental writes occurred
ls -la ~/jarvis-sandbox/    # only files you explicitly created
```
