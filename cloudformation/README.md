# CostOp Intelligence Agent — Deployment Guide

A self-hosted AI agent that monitors Bedrock token usage in real-time, investigates cost spikes autonomously, and provides one-click remediation.

## Quick Start

### Prerequisites
- AWS account with Bedrock access (Claude Sonnet 4.5 or Haiku 4.5)
- AWS CLI configured
- Node.js 18+ (for UI deployment)

### Step 1: Deploy Backend (~5 minutes)

```bash
aws cloudformation deploy \
  --template-file cloudformation/costop-template.yaml \
  --stack-name CostOp \
  --parameter-overrides AdminEmail=your@email.com \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

### Step 2: Deploy Web UI (~1 minute)

```bash
./scripts/deploy-ui.sh CostOp us-east-1
```

### Step 3: Login

Check your email for temporary credentials. Open the Amplify URL printed by the script.

---

## Parameters

| Parameter | Default | Description |
|---|---|---|
| **AdminEmail** | (required) | Login credentials + alert notifications |
| **DefaultModel** | Sonnet4.6 | Sonnet 4.6 (latest), Sonnet 4.5 (proven), or Haiku 4.5 (faster/cheaper). Ignored if CustomModelId is set. |
| **CustomModelId** | (empty) | Override with any Bedrock model ID. Ensure the model is enabled in your account and region. |
| **EnableTokenAlarm** | Yes | Alert on input token spikes |
| **TokenAlarmThreshold** | 200000 | Tokens per 5-min window |
| **EnableRPMAlarm** | Yes | Alert on requests per minute |
| **RPMAlarmThreshold** | 100 | Requests per minute |
| **EnableTPMAlarm** | Yes | Alert on TPM quota usage |
| **TPMAlarmThreshold** | 80 | TPM quota usage percentage |
| **EnableThrottleAlarm** | Yes | Alert on throttled requests |
| **ThrottleAlarmThreshold** | 5 | Throttled requests per minute |
| **EnableErrorAlarm** | Yes | Alert on invocation errors |
| **ErrorAlarmThreshold** | 10 | Client errors per 5 minutes |
| **MonthlyBudgetLimit** | 100 | Monthly budget in USD (0 = no budget) |
| **EnableCostAnomalyDetection** | Yes | AWS Cost Anomaly Detection alerts |
| **EnableInvocationLogging** | Yes | Log all Bedrock invocations |
| **MemoryRetentionDays** | 30 | Days to keep conversation history (7-365) |
| **InvocationLogGroup** | (empty) | Existing log group name (leave empty to create) |
| **SNSTopicArn** | (empty) | Existing SNS topic ARN (leave empty to create) |
| **CloudWatchAlarms** | (empty) | Leave empty to create. Enter EXISTING if you have alarms. |
| **EnableSlack** | No | Slack integration |
| **SlackBotToken** | | Bot token (if Slack enabled) |
| **SlackSigningSecret** | | Signing secret (if Slack enabled) |
| **SlackChannel** | | Channel ID (if Slack enabled) |

---

## What Gets Created

- **AgentCore Runtime** — the investigation agent (from `public.ecr.aws/y3a7j1y9/amitml/costop-agent`)
- **Cognito** — user authentication (admin user auto-created)
- **DynamoDB** — 3 tables (patterns, investigations, topology)
- **CloudWatch Alarms** — based on your selections
- **EventBridge Rules** — alarm + budget + anomaly triggers
- **Bridge Lambda** — proactive investigations → SNS alerts
- **SNS Topic** — email notifications
- **Budget** — monthly Bedrock spend limit (if configured)
- **Invocation Logging** — per-call token tracking (if enabled)

---

## Usage Tips

### Getting Structured Tile Responses

The agent uses structured tile format (findings, timeline, actions) for investigations. To ensure tiles on any query, include "investigate" in your message:

- ✅ `"Investigate my current costs"` → tiles
- ✅ `"Investigate why usage is high"` → tiles
- ✅ `"Investigate all alarms"` → tiles
- ⚡ `"What's my usage?"` → tiles (cost keyword detected)
- 💬 `"Who are you?"` → plain text (no cost context)

### Model Selection

Choose your model at deploy time via the `DefaultModel` parameter:
- **Sonnet 4.6** (default) — latest model, best reasoning and coding performance.
- **Sonnet 4.5** — proven, stable.
- **Haiku 4.5** — faster, cheaper, good for simple queries.
- **Custom** — set `CustomModelId` to use any Bedrock model.

Note: The selected model must be enabled in your AWS account and region. Go to the Bedrock console → Model access to enable models.

### Proactive Alerts

When an alarm fires, the agent automatically:
1. Investigates the root cause
2. Sends findings to your email (SNS)
3. Saves the investigation to history (visible in left panel)

### Left Panel

- **Current Status** — live alarms + budget breaches
- **Cost Anomalies** — AWS-detected anomalies (last 7 days)
- **Investigation History** — all past investigations (click to view)
- **Alarm History** — alarm fire/resolve timeline (click to investigate)

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│ Web UI (Amplify)                                         │
│ • Cognito login → SigV4 direct to AgentCore              │
│ • Structured tiles + dark mode + mobile responsive       │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│ AgentCore Runtime                                        │
│ • Strands Agent + Claude Sonnet/Haiku                    │
│ • 22 tools (CloudWatch, CloudTrail, CE, Budgets, etc.)   │
│ • Evidence ledger (prevents contradictions)              │
│ • Hypothesis-driven investigation                        │
│ • AgentCore Memory (30-day)                              │
│ • Topology verification (prevents false correlations)    │
└─────────────────────────────────────────────────────────┘

Proactive: Alarm/Budget/Anomaly → EventBridge → Lambda → Agent → SNS Email
```

---

## Cost

| Component | Monthly Cost |
|---|---|
| Bedrock Sonnet (~20 investigations/day) | ~$150 |
| Bedrock Haiku (~20 investigations/day) | ~$18 |
| AgentCore Runtime | ~$27 |
| CloudWatch Alarms | $0.50 |
| DynamoDB | Free tier |
| Lambda | Free tier |
| SNS | Free tier |
| **Total (Sonnet)** | **~$180/mo** |
| **Total (Haiku)** | **~$45/mo** |

---

## Cleanup

```bash
aws cloudformation delete-stack --stack-name CostOp --region us-east-1
```

This removes all resources. DynamoDB tables and data are deleted.

---

## Slack Setup (Optional)

1. Create a Slack app at https://api.slack.com/apps
2. Add bot scopes: `chat:write`, `app_mentions:read`, `im:write`, `im:read`, `im:history`
3. Enable Event Subscriptions → Request URL will be in stack outputs
4. Install to workspace
5. Redeploy stack with `EnableSlack=Yes` and token parameters
6. Invite bot to your channel: `/invite @CostOp`

---

## Troubleshooting

| Issue | Fix |
|---|---|
| Agent returns error on invoke | Check CloudWatch logs: `/aws/bedrock-agentcore/runtimes/` |
| No email received | Confirm SNS subscription in your inbox |
| Alarms not firing | Check alarm thresholds match your usage patterns |
| UI shows "Unauthorized" | Verify Cognito user exists and password was changed |
| Haiku model error | Ensure Haiku 4.5 is enabled in your Bedrock console |
| "Incorrect username or password" | Cognito sends a temp password via email. If expired, reset with: `aws cognito-idp admin-set-user-password --user-pool-id <POOL_ID> --username admin --password 'YourNewPass1!' --permanent --region us-east-1` |
| "Resolved credential object is not valid" | User is in FORCE_CHANGE_PASSWORD state. Set permanent password with command above |
| Stack delete fails on ECR | Run: `aws ecr delete-repository --repository-name <repo-name> --force --region us-east-1` then retry delete |

### First Login

1. Check email for temporary password from Cognito
2. Login with username `admin` and the temp password
3. If temp password expired, reset it:
   ```bash
   POOL_ID=$(aws cloudformation describe-stacks --stack-name CostOp --region us-east-1 --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' --output text)
   aws cognito-idp admin-set-user-password --user-pool-id $POOL_ID --username admin --password 'CostOp2026!' --permanent --region us-east-1
   ```
