# CostOp Intelligence Agent

A real-time cost monitoring, investigation, and usage tracking platform for AWS Bedrock workloads. Combines an autonomous investigation agent with a live usage dashboard — so you know what's happening now, not 24 hours from now.

Built on Amazon Bedrock AgentCore + Strands SDK + Claude Sonnet 4.5.

---

## What It Does

### Agent Tab — Autonomous Investigation

```
CloudWatch Alarm fires → Agent investigates automatically →
Sends you an email with: WHO caused it, WHY, HOW MUCH, and HOW TO FIX
```

- **Real-time detection** — 5 CloudWatch alarms monitor Bedrock metrics
- **Autonomous investigation** — hypothesis-driven with evidence ledger
- **Structured reports** — findings tiles, timeline, action buttons
- **Pattern memory** — learns from past incidents, recognizes repeats
- **Proactive alerts** — email + Slack with full investigation (not just "alarm fired")

### Usage Tab — Live Token & Cost Dashboard

Inspired by [bedrock-lens](https://github.com/OmarCodes022/bedrock-lens), the Usage tab provides real-time visibility into Bedrock model usage directly in the browser:

- **Per-model breakdown** — invocations, input/output tokens, estimated cost
- **Time range selection** — last 30m, 1h, 6h, today, yesterday, this week
- **Auto-refresh** — polls every 30 seconds for live monitoring
- **Summary cards** — total cost, invocations, token counts, active models
- **No CLI required** — runs in the browser using Cognito credentials + SigV4

The Usage tab queries CloudWatch Logs Insights against `/aws/bedrock/modelinvocations` — the same data source as bedrock-lens — and renders per-model token/cost breakdowns without the 24-48 hour Cost Explorer lag.

### Both Tabs Share

- **Cognito authentication** — single sign-on across agent and dashboard
- **Dark/light mode** — full theme support
- **Mobile responsive** — works on any device

---

## Architecture

```
Web UI (Amplify)
├── Agent Tab → Cognito Auth → AgentCore Runtime (12 tools)
│                                     ↓
│                 CloudWatch + CloudTrail + Cost Explorer + Invocation Logs
│                                     ↓
│                 Structured investigation → Email + Slack + DynamoDB
│
└── Usage Tab → Cognito Auth → CloudWatch Logs Insights (direct query)
                                     ↓
                 Per-model token counts + cost calculation → Table render

Proactive: Alarm → EventBridge → Lambda → Agent → Email/Slack
```

---

## First Time Setup (5 minutes)

### Prerequisites
- AWS account with Bedrock access (Claude Sonnet 4.5 enabled in your region)
- AWS CLI configured (`aws configure`)

### Step 1: Download the template

```bash
curl -O https://raw.githubusercontent.com/angele1205/cloud-intelligence-agent/main/cloudformation/costop-template.yaml
```

### Step 2: Deploy

```bash
aws cloudformation create-stack \
  --stack-name CostOp \
  --template-body file://costop-template.yaml \
  --parameters ParameterKey=AdminEmail,ParameterValue=YOUR_EMAIL@company.com \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

### Step 3: Wait ~5 minutes

```bash
aws cloudformation wait stack-create-complete --stack-name CostOp --region us-east-1
```

### Step 4: Enable Bedrock Invocation Logging (required for Usage tab)

```bash
# Get the logging role ARN from the stack
ROLE_ARN=$(aws cloudformation describe-stack-resources --stack-name CostOp \
  --query "StackResources[?LogicalResourceId=='LoggingRole'].PhysicalResourceId" --output text)
ROLE_ARN=$(aws iam get-role --role-name $ROLE_ARN --query 'Role.Arn' --output text)

# Create the log group
aws logs create-log-group --log-group-name /aws/bedrock/modelinvocations --region us-east-1

# Enable invocation logging
aws bedrock put-model-invocation-logging-configuration --region us-east-1 \
  --logging-config "{\"cloudWatchConfig\":{\"logGroupName\":\"/aws/bedrock/modelinvocations\",\"roleArn\":\"$ROLE_ARN\"},\"textDataDeliveryEnabled\":true,\"imageDataDeliveryEnabled\":false,\"embeddingDataDeliveryEnabled\":false}"
```

### Step 5: Get your URL and login

```bash
aws cloudformation describe-stacks --stack-name CostOp --region us-east-1 \
  --query 'Stacks[0].Outputs[?OutputKey==`WebAppURL`].OutputValue' --output text
```

- Check your email for temporary password from Cognito
- Login with username `admin` and the temp password
- Set a new password when prompted

---

## Configuration Options

Deploy with custom parameters:

```bash
aws cloudformation create-stack \
  --stack-name CostOp \
  --template-body file://costop-template.yaml \
  --parameters \
    ParameterKey=AdminEmail,ParameterValue=you@company.com \
    ParameterKey=DefaultModel,ParameterValue=Haiku4.5 \
    ParameterKey=MonthlyBudgetLimit,ParameterValue=200 \
    ParameterKey=EnableSlack,ParameterValue=Yes \
    ParameterKey=SlackBotToken,ParameterValue=xoxb-... \
    ParameterKey=MemoryRetentionDays,ParameterValue=90 \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

### Custom Model

Use any Bedrock model by setting `CustomModelId`:

```bash
ParameterKey=CustomModelId,ParameterValue=us.anthropic.claude-sonnet-4-5-20250929-v1:0
```

See [cloudformation/README.md](cloudformation/README.md) for all parameters.

---

## Cost to Run

| Model | Per Investigation |
|---|---|
| Sonnet 4.5 | ~$0.25 |
| Haiku 4.5 | ~$0.03 |

The Usage dashboard itself costs nothing extra — it reads CloudWatch Logs directly from the browser.

Monthly cost depends on alarm frequency and investigation count. Infrastructure (alarms, DynamoDB, Lambda) is free tier or negligible.

---

## Usage Tab Details

The Usage tab replicates the core functionality of [bedrock-lens](https://github.com/OmarCodes022/bedrock-lens) as a web interface:

| Feature | bedrock-lens (CLI) | CostOp Usage Tab |
|---------|-------------------|------------------|
| Per-model token breakdown | ✓ | ✓ |
| Cost calculation | ✓ | ✓ |
| Time range selection | ✓ (`--since`) | ✓ (dropdown) |
| Auto-refresh | ✓ (`--live`) | ✓ (30s checkbox) |
| Auth | AWS CLI credentials | Cognito (browser) |
| Setup required | `pip install` | None (deployed with stack) |

Supported models include Claude (Sonnet 4.5/4.6, Haiku 4.5, 3.5 Sonnet), Amazon Nova (Micro, Lite, Pro), and any other model — unknown models display token counts with "N/A" for pricing.

---

## Delete Everything

```bash
aws ecr delete-repository --repository-name $(aws ecr describe-repositories --query 'repositories[?contains(repositoryName, `costop`)].repositoryName' --output text) --force --region us-east-1
aws cloudformation delete-stack --stack-name CostOp --region us-east-1
```

---

## Troubleshooting

| Issue | Fix |
|---|---|
| "Incorrect username or password" | Reset: `aws cognito-idp admin-set-user-password --user-pool-id <ID> --username admin --password 'NewPass1!' --permanent` |
| Agent returns error | Check logs: CloudWatch → `/aws/bedrock-agentcore/runtimes/` |
| Usage tab shows "No invocations" | Enable invocation logging (see Step 4 above) |
| Usage tab shows "Failed to start query" | Ensure the authenticated role has `logs:StartQuery` + `logs:GetQueryResults` permissions |
| Stack delete fails | Delete ECR repo first (see Delete section above) |

---

## Credits

- Agent framework based on [AWS FinOps Agent sample](https://github.com/aws-samples/sample-finops-agent-amazon-bedrock-agentcore)
- Usage dashboard inspired by [bedrock-lens](https://github.com/OmarCodes022/bedrock-lens)
- Originally created by [amitml](https://github.com/amitml)
