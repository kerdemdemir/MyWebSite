#!/usr/bin/env python3
"""Parse Claude Code JSONL logs and generate usage JSON for the dashboard."""

import json
import os
import glob
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude" / "projects"

# Pricing per million tokens (USD) - Claude models
PRICING = {
    "claude-opus-4-6":   {"input": 15.0, "output": 75.0, "cache_create": 18.75, "cache_read": 1.50},
    "claude-sonnet-4-6": {"input": 3.0,  "output": 15.0, "cache_create": 3.75,  "cache_read": 0.30},
    "claude-haiku-4-5":  {"input": 0.80, "output": 4.0,  "cache_create": 1.0,   "cache_read": 0.08},
}

DEFAULT_PRICING = {"input": 3.0, "output": 15.0, "cache_create": 3.75, "cache_read": 0.30}


def get_pricing(model_id):
    for key, prices in PRICING.items():
        if key in (model_id or ""):
            return prices
    return DEFAULT_PRICING


def parse_all_sessions():
    daily = defaultdict(lambda: {
        "input_tokens": 0, "output_tokens": 0,
        "cache_creation_tokens": 0, "cache_read_tokens": 0,
        "cost": 0.0, "messages": 0
    })

    by_model = defaultdict(lambda: {
        "input_tokens": 0, "output_tokens": 0,
        "cache_creation_tokens": 0, "cache_read_tokens": 0,
        "cost": 0.0
    })

    by_project = defaultdict(lambda: {
        "input_tokens": 0, "output_tokens": 0,
        "cost": 0.0, "messages": 0
    })

    total = {
        "input_tokens": 0, "output_tokens": 0,
        "cache_creation_tokens": 0, "cache_read_tokens": 0,
        "cost": 0.0, "messages": 0, "sessions": 0
    }

    sessions_seen = set()

    for jsonl_file in CLAUDE_DIR.rglob("*.jsonl"):
        project_name = jsonl_file.parent.name
        for line in open(jsonl_file, "r", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("type") != "assistant":
                continue

            msg = entry.get("message", {})
            usage = msg.get("usage", {})
            if not usage:
                continue

            model = msg.get("model", "unknown")
            prices = get_pricing(model)

            inp = usage.get("input_tokens", 0)
            out = usage.get("output_tokens", 0)
            cache_create = usage.get("cache_creation_input_tokens", 0)
            cache_read = usage.get("cache_read_input_tokens", 0)

            cost = (
                (inp / 1_000_000) * prices["input"] +
                (out / 1_000_000) * prices["output"] +
                (cache_create / 1_000_000) * prices["cache_create"] +
                (cache_read / 1_000_000) * prices["cache_read"]
            )

            ts = entry.get("timestamp", "")
            day = ts[:10] if ts else "unknown"

            session_id = entry.get("sessionId", "")
            if session_id and session_id not in sessions_seen:
                sessions_seen.add(session_id)
                total["sessions"] += 1

            daily[day]["input_tokens"] += inp
            daily[day]["output_tokens"] += out
            daily[day]["cache_creation_tokens"] += cache_create
            daily[day]["cache_read_tokens"] += cache_read
            daily[day]["cost"] += cost
            daily[day]["messages"] += 1

            model_key = model.split("-2")[0] if "-2" in model else model
            by_model[model_key]["input_tokens"] += inp
            by_model[model_key]["output_tokens"] += out
            by_model[model_key]["cache_creation_tokens"] += cache_create
            by_model[model_key]["cache_read_tokens"] += cache_read
            by_model[model_key]["cost"] += cost

            by_project[project_name]["input_tokens"] += inp
            by_project[project_name]["output_tokens"] += out
            by_project[project_name]["cost"] += cost
            by_project[project_name]["messages"] += 1

            total["input_tokens"] += inp
            total["output_tokens"] += out
            total["cache_creation_tokens"] += cache_create
            total["cache_read_tokens"] += cache_read
            total["cost"] += cost
            total["messages"] += 1

    # Sort daily by date
    daily_sorted = [
        {"date": k, **v}
        for k, v in sorted(daily.items())
        if k != "unknown"
    ]

    # Top projects by cost
    top_projects = sorted(
        [{"project": k.replace("-home-erdem-", "~/"), **v} for k, v in by_project.items()],
        key=lambda x: x["cost"], reverse=True
    )[:10]

    # Models
    models = [{"model": k, **v} for k, v in sorted(by_model.items(), key=lambda x: x[1]["cost"], reverse=True)]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": total,
        "daily": daily_sorted,
        "models": models,
        "top_projects": top_projects,
    }


if __name__ == "__main__":
    data = parse_all_sessions()
    out_path = Path(__file__).parent / "claude_usage.json"
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Total: {data['total']['messages']} messages, "
          f"{data['total']['input_tokens'] + data['total']['output_tokens']:,} tokens, "
          f"${data['total']['cost']:.2f} estimated cost")
    print(f"Written to {out_path}")
