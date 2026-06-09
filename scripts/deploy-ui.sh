#!/bin/bash
# Created by amitml (https://github.com/amitml)
# CostOp UI Deployment Script
# Usage: ./deploy-ui.sh <STACK_NAME> [REGION]
#
# Reads CloudFormation stack outputs, configures the web UI, and deploys to Amplify.

set -e

STACK_NAME=${1:-"CostOp"}
REGION=${2:-"us-east-1"}

echo "🚀 CostOp UI Deployment"
echo "   Stack: $STACK_NAME"
echo "   Region: $REGION"
echo ""

# Get stack outputs
echo "📋 Reading stack outputs..."
OUTPUTS=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" --query 'Stacks[0].Outputs' --output json 2>/dev/null)

if [ $? -ne 0 ]; then
    echo "❌ Stack '$STACK_NAME' not found in region '$REGION'. Deploy the backend first."
    exit 1
fi

USER_POOL_ID=$(echo "$OUTPUTS" | python3 -c "import json,sys;o={i['OutputKey']:i['OutputValue'] for i in json.load(sys.stdin)};print(o.get('UserPoolId',''))")
CLIENT_ID=$(echo "$OUTPUTS" | python3 -c "import json,sys;o={i['OutputKey']:i['OutputValue'] for i in json.load(sys.stdin)};print(o.get('UserPoolClientId',''))")
IDENTITY_POOL_ID=$(echo "$OUTPUTS" | python3 -c "import json,sys;o={i['OutputKey']:i['OutputValue'] for i in json.load(sys.stdin)};print(o.get('IdentityPoolId',''))")
AGENT_ARN=$(echo "$OUTPUTS" | python3 -c "import json,sys;o={i['OutputKey']:i['OutputValue'] for i in json.load(sys.stdin)};print(o.get('AgentRuntimeArn',''))")

if [ -z "$USER_POOL_ID" ] || [ -z "$AGENT_ARN" ]; then
    echo "❌ Could not read required outputs from stack. Ensure stack deployed successfully."
    exit 1
fi

echo "   UserPoolId: $USER_POOL_ID"
echo "   ClientId: $CLIENT_ID"
echo "   IdentityPoolId: $IDENTITY_POOL_ID"
echo "   AgentArn: $AGENT_ARN"
echo ""

# Clone or use existing web directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WEB_DIR="$SCRIPT_DIR/../web"

if [ ! -d "$WEB_DIR" ]; then
    echo "📥 Downloading web UI..."
    mkdir -p "$WEB_DIR"
    curl -sL "https://github.com/amitml/cost-intelligence-agent/archive/main.tar.gz" | tar -xz --strip-components=2 -C "$WEB_DIR" "cost-intelligence-agent-main/web"
fi

# Generate config
echo "⚙️  Generating configuration..."
cat > "$WEB_DIR/src/config.js" 2>/dev/null || true

# Update main.js with stack values
cd "$WEB_DIR"
sed -i.bak "s|userPoolId:'[^']*'|userPoolId:'$USER_POOL_ID'|g" main.js 2>/dev/null || \
sed -i '' "s|userPoolId:'[^']*'|userPoolId:'$USER_POOL_ID'|g" main.js
sed -i.bak "s|userPoolClientId:'[^']*'|userPoolClientId:'$CLIENT_ID'|g" main.js 2>/dev/null || \
sed -i '' "s|userPoolClientId:'[^']*'|userPoolClientId:'$CLIENT_ID'|g" main.js
sed -i.bak "s|identityPoolId:'[^']*'|identityPoolId:'$IDENTITY_POOL_ID'|g" main.js 2>/dev/null || \
sed -i '' "s|identityPoolId:'[^']*'|identityPoolId:'$IDENTITY_POOL_ID'|g" main.js
sed -i.bak "s|const AGENT_ARN='[^']*'|const AGENT_ARN='$AGENT_ARN'|g" main.js 2>/dev/null || \
sed -i '' "s|const AGENT_ARN='[^']*'|const AGENT_ARN='$AGENT_ARN'|g" main.js
sed -i.bak "s|const REGION='[^']*'|const REGION='$REGION'|g" main.js 2>/dev/null || \
sed -i '' "s|const REGION='[^']*'|const REGION='$REGION'|g" main.js
# Set investigations table name and alarm prefix
echo "window.INVESTIGATIONS_TABLE='${STACK_NAME}-investigations';" >> main.js
echo "window.ALARM_PREFIX='${STACK_NAME}';" >> main.js
rm -f main.js.bak

# Build
echo "🔨 Building UI..."
npm install --silent 2>/dev/null
npm run build 2>/dev/null

# Deploy to Amplify
echo "📦 Deploying to Amplify..."
APP_ID=$(aws amplify list-apps --region "$REGION" --query "apps[?name=='$STACK_NAME-UI'].appId" --output text 2>/dev/null)

if [ -z "$APP_ID" ] || [ "$APP_ID" = "None" ]; then
    echo "   Creating Amplify app..."
    APP_ID=$(aws amplify create-app --name "$STACK_NAME-UI" --region "$REGION" --query 'app.appId' --output text)
    aws amplify create-branch --app-id "$APP_ID" --branch-name main --region "$REGION" > /dev/null
fi

cd dist
zip -r /tmp/costop-ui-deploy.zip . > /dev/null
DEPLOY=$(aws amplify create-deployment --app-id "$APP_ID" --branch-name main --region "$REGION" --output json)
JOB_ID=$(echo "$DEPLOY" | python3 -c "import json,sys;print(json.load(sys.stdin)['jobId'])")
UPLOAD_URL=$(echo "$DEPLOY" | python3 -c "import json,sys;print(json.load(sys.stdin)['zipUploadUrl'])")
curl -s -T /tmp/costop-ui-deploy.zip "$UPLOAD_URL" > /dev/null
aws amplify start-deployment --app-id "$APP_ID" --branch-name main --job-id "$JOB_ID" --region "$REGION" > /dev/null

# Wait for deployment
sleep 8
STATUS=$(aws amplify get-job --app-id "$APP_ID" --branch-name main --job-id "$JOB_ID" --region "$REGION" --query 'job.summary.status' --output text 2>/dev/null)

DOMAIN=$(aws amplify get-app --app-id "$APP_ID" --region "$REGION" --query 'app.defaultDomain' --output text)

echo ""
echo "✅ Deployment complete!"
echo ""
echo "   🌐 URL: https://main.$DOMAIN"
echo "   👤 Login: Check email for credentials (sent to $AdminEmail)"
echo ""
echo "   To delete everything: aws cloudformation delete-stack --stack-name $STACK_NAME --region $REGION"
