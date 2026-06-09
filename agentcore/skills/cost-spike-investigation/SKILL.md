---
name: cost-spike-investigation
description: Investigate cost spikes and anomalies using hypothesis-driven reasoning with evidence ledger.
---

# Cost Spike Investigation

## PROTOCOL

1. ASSESS: Call get_monitoring_data('alarms') + get_monitoring_data('bedrock_usage'). Write evidence.
2. HYPOTHESIZE: Form 2-3 hypotheses based on evidence.
3. TEST: Call 1-2 tools to test top hypothesis. Write evidence.
4. ATTRIBUTE: WHO (caller ARN), WHAT (API + tokens), WHEN (timeline), WHY (trigger), IMPACT ($).
5. CONCLUDE: Only when at least one hypothesis is CONFIRMED.

## EVIDENCE LEDGER

After EACH tool call, write an evidence line before calling the next tool:
- [CONFIRMED] what you now know for certain (with numbers)
- [ELIMINATED] what you ruled out (and why)
- [UNRESOLVED] what remains unclear (and what would resolve it)

Your final response MUST NOT contradict any [CONFIRMED] item.
If a tool returned data, it's [CONFIRMED] that the tool works — never say "need to enable" something you already used.

## TOOLS (use 3-5, not all)

Parallel first pass: get_monitoring_data('alarms'), get_monitoring_data('bedrock_usage'), get_monitoring_data('metric', 'AWS/Bedrock/InputTokenCount')
Then targeted: get_recent_changes('bedrock'), check_invocation_logs(), detect_issues('loops'), manage_patterns('find', 'pattern-type'), get_resource_info('agent_runtime')

## OUTPUT

```json
{
  "type": "investigation",
  "severity": "critical|warning|info",
  "summary": "One sentence: root cause + impact + current state",
  "findings": [
    {"label": "Descriptive title", "value": "Specific numbers, ARNs, timestamps", "status": "danger|warning|ok"}
  ],
  "timeline": [
    {"time": "HH:MM", "event": "Specific event with numbers"}
  ],
  "actions": [
    {"label": "Action name", "prompt": "Exact action", "destructive": false}
  ],
  "blind_spots": "Only genuinely unavailable info. Verify against your evidence ledger before writing."
}
```

## RULES
- 4-8 finding tiles with descriptive labels and specific numbers
- Show multiplier vs baseline (e.g., "9.8x normal")
- If data is partial, USE what you have. Call tool again with different params before concluding "unknown"
- Parallel tool calls allowed when tools are independent
