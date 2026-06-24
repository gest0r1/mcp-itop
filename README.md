# mcp-itop

MCP (Model Context Protocol) server for **iTop ITSM** — analytics, tickets, comments, knowledge base, CI.

Provides AI assistants (Claude Desktop, opencode, Cursor, etc.) with 19 tools for iTop:
SLA analysis, agent workload, service quality, ticket lifecycle, KB search, CI impact.

## Features

### Analytics
| Tool | Description |
|------|-------------|
| `itop_sla_report` | SLA report per service/period (TTO/TTR passed/breached/N/A, median resolution) |
| `itop_agent_workload` | Agent workload: closed/open tickets, time_spent, backlog |
| `itop_idle_agents` | Find tickets where agent is idle >N hours without action |
| `itop_service_quality` | Detect similar tickets assigned to different services |
| `itop_caller_quality` | Caller service selection accuracy analysis |
| `itop_agent_correction_rate` | Which agents fix/ignore service misclassification |
| `itop_ticket_summary` | Dashboard: created/resolved/open/SLA breaches |

### Comments
| Tool | Description |
|------|-------------|
| `itop_add_comment` | Add public/private comment to a ticket |
| `itop_get_log` | Read ticket log entries (public_log, private_log) |

### Knowledge Base
| Tool | Description |
|------|-------------|
| `itop_search_kb` | Search KB articles (supports KBEntry and FAQ modules) |
| `itop_get_kb_article` | Get full article content |
| `itop_list_kb_categories` | List KB categories |

### CRUD + Lifecycle
| Tool | Description |
|------|-------------|
| `itop_get` | Search objects (OQL / ID / JSON criteria) |
| `itop_create` | Create object (enforces required fields + comment) |
| `itop_update` | Update object fields |
| `itop_delete` | Delete with simulate mode |
| `itop_apply_stimulus` | Lifecycle: ev_assign, ev_resolve, ev_close, ev_reopen, etc. |
| `itop_get_related` | CI impact/dependency analysis |
| `itop_describe_class` | Discover fields by sampling an existing object |

## Quick Start

### 1. Install

```bash
pip install mcp[fastmcp] httpx python-dotenv
```

### 2. Configure (global)

```bash
mkdir -p ~/.config/mcp-itop
cat > ~/.config/mcp-itop/.env << 'CONFIG'
ITOP_URL=https://your-itop.example.com
# Use token OR user+password:
ITOP_TOKEN=your_api_token_here
# ITOP_USER=admin
# ITOP_PASSWORD=secret
ITOP_VERSION=1.3
ITOP_VERIFY_SSL=true
ITOP_TIMEOUT=30
CONFIG
```

### 3. Run

```bash
python server.py
```

Or via opencode (see below).

## Integration

### opencode (global config)

Add to `~/.config/opencode/opencode.json`:

```json
"itop": {
  "type": "local",
  "command": ["python", "/path/to/mcp-itop/server.py"],
  "enabled": true
}
```

### opencode (per-project)

Add to `opencode.json`:

```json
{
  "mcpServers": {
    "itop": {
      "command": "python",
      "args": ["/path/to/mcp-itop/server.py"],
      "env": {
        "ITOP_URL": "https://your-itop.example.com",
        "ITOP_TOKEN": "your_token"
      }
    }
  }
}
```

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "itop": {
      "command": "python",
      "args": ["/path/to/mcp-itop/server.py"]
    }
  }
}
```

## Example Queries

```
Show SLA report for IT support service this month
Which agents are overloaded?
Find tickets idle more than 2 hours
Find similar tickets assigned to different services
Who calls often pick wrong service?
Add comment to RQ-123
Create a new ticket: Printer not working
Assign RQ-456 to Ivanov
Find CIs related to server srv-web-01
Search KB for VPN setup
```

## Compatibility

Tested on:

- **iTop** 3.2.1-1-16749 (PHP 8.1.2, MariaDB 10.6)
- Supports Russian locale (да/нет for SLA) and English (true/false)
- Auto-detects KB module: KBEntry → FAQ

## Requirements

- Python ≥ 3.10
- `mcp[fastmcp]`
- `httpx`
- `python-dotenv`

## Tests

```bash
python -m pytest tests/ -v
```

## Architecture

```
AI Client → MCP (stdio) → server.py → iTop REST API
```

Configuration cascade:
1. `~/.config/mcp-itop/.env` (global, highest priority)
2. `.env` (project-local)
3. Environment variables

## License

MIT
