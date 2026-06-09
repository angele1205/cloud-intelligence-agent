---
name: cost-overview
description: Provide a summary of current AWS costs, budget status, and trends.
---

# Cost Overview

Use this skill for general cost questions.

## Steps:
1. `get_cost_and_usage(days=7)` — this week's spend by service
2. `get_budgets()` — budget status
3. `get_alarm_status()` — any active alarms
4. `get_cost_forecast()` — projected month-end

## Output format

Respond with a JSON object wrapped in ```json fences. No text before or after.

```json
{
  "type": "overview",
  "severity": "info|warning|critical",
  "summary": "MTD $X, projected $Y/month, [over/under] budget",
  "findings": [
    {"label": "Month-to-date", "value": "$X", "status": "ok|warning|danger"},
    {"label": "Projected month-end", "value": "$X", "status": "ok|warning|danger"},
    {"label": "Budget status", "value": "X% used", "status": "ok|warning|danger"},
    {"label": "Top service", "value": "ServiceName — $X", "status": "ok|warning"},
    {"label": "vs Last month", "value": "+X% or -X%", "status": "ok|warning|danger"}
  ],
  "timeline": [
    {"time": "May 10", "event": "$X — normal"},
    {"time": "May 11", "event": "$X — spike detected"}
  ],
  "actions": [
    {"label": "Investigate top service", "prompt": "Investigate why [service] costs are high", "destructive": false},
    {"label": "Set budget", "prompt": "Set budget alert at $X/month", "destructive": false}
  ],
  "blind_spots": null
}
```

## Rules:
- timeline: daily spend for last 5-7 days
- findings: always include MTD, projected, budget status, top service, trend
- If spend >80% of budget: severity=warning. If >100%: severity=critical.
- If a service grew >50% MoM: flag it in findings with status=danger.
