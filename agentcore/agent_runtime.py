# CostOp Intelligence Agent - Runtime
# Created by amitml (https://github.com/amitml)
"""
Amazon Bedrock Agent Core Runtime - FinOps Agent
Uses BedrockAgentCoreApp for proper authentication and Gateway integration
"""
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient
from botocore.credentials import Credentials
from streamable_http_sigv4 import streamablehttp_client_with_sigv4
from tools import (
    get_resource_info, get_monitoring_data, get_cost_data,
    get_recent_changes, check_invocation_logs,
    manage_patterns, detect_issues,
    send_notification, stop_agent_invocations, set_budget_alert,
    request_quota_increase
)
from skill_loader import select_skill
from slack_handler import start_slack_listener, set_agent_fn
import os
import boto3
import logging
from datetime import datetime, timezone

ddb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize the Agent Core app
app = BedrockAgentCoreApp()

# Get configuration from environment
GATEWAY_ARN = os.environ.get('GATEWAY_ARN')
MEMORY_ID = os.environ.get('MEMORY_ID')
MODEL_ID = os.environ.get('MODEL_ID', 'us.anthropic.claude-sonnet-4-5-20250929-v1:0')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')

logger.info(f"Gateway ARN: {GATEWAY_ARN}")
logger.info(f"Model ID: {MODEL_ID}")
logger.info(f"Memory ID: {MEMORY_ID}")
logger.info(f"AWS Region: {AWS_REGION}")

if not GATEWAY_ARN:
    logger.error("Gateway ARN not configured!")
else:
    logger.info("Gateway configured successfully")

if MEMORY_ID:
    logger.info(f"Memory enabled: {MEMORY_ID}")
else:
    logger.warning("Memory ID not configured - memory disabled")

# Initialize Bedrock model
model = BedrockModel(
    model_id=MODEL_ID,
    region_name=AWS_REGION,
    max_tokens=int(os.environ.get('MAX_TOKENS', '12000'))
)

# Get AWS credentials for SigV4 signing
session = boto3.Session()
credentials = session.get_credentials()
frozen_credentials = Credentials(
    access_key=credentials.access_key,
    secret_key=credentials.secret_key,
    token=credentials.token
)

# Extract Gateway ID from ARN and construct endpoint URL
gateway_id = GATEWAY_ARN.split('/')[-1] if GATEWAY_ARN else None
gateway_endpoint = f"https://{gateway_id}.gateway.bedrock-agentcore.{AWS_REGION}.amazonaws.com/mcp" if gateway_id else None

logger.info(f"Gateway Endpoint: {gateway_endpoint}")


def get_current_date_utc() -> str:
    """Get current date and time in UTC for cost query context"""
    try:
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%d (%A) %H:00 UTC")
    except Exception as e:
        logger.warning(f"Failed to get current date: {e}")
        return "2026-01-24 (Friday) 12:00 UTC"


# Local Strands tools (Cost Intelligence extensions)
local_tools = [
    get_resource_info, get_monitoring_data, get_cost_data,
    get_recent_changes, check_invocation_logs,
    manage_patterns, detect_issues,
    send_notification, stop_agent_invocations, set_budget_alert,
    request_quota_increase
]

# Global MCP client to keep connection alive
mcp_client = None
agent = None
mcp_tools = []  # Store tools globally
system_prompt_template = ""  # Store system prompt template


def initialize_agent_with_gateway():
    """Initialize agent with Gateway tools using MCP Client with SigV4 auth"""
    global mcp_client, agent, mcp_tools, system_prompt_template
    
    try:
        # Set system prompt first (needed regardless of Gateway)
        current_date = get_current_date_utc()
        system_prompt_template = f"""You are a Cost Intelligence Agent. You investigate cost anomalies in real-time.

Current date: {current_date}

## TOOLS
When investigating, use these:
1. get_monitoring_data — alarms, metrics, bedrock usage, alarm history
2. get_recent_changes — CloudTrail changes, deployments, config changes
3. check_invocation_logs — caller ARNs, sessions, token details
4. get_cost_data — cost by service, anomalies, forecast, budgets, by tag
5. detect_issues — loop detection, per-agent costs, quota limits
6. manage_patterns — find/save patterns, check topology, save investigations
7. get_resource_info — agent config, Lambda config, stacks, EventBridge, IAM, tags, SNS, ECS

## CONSTRAINTS
- billingMcp tools have 12-hour delay. Use CloudWatch for real-time.
- pricingMcp tools for pricing lookups.
- Destructive actions need user confirmation first.
- Never suggest manual CLI commands — use your tools.
- If a tool returned data, that data exists. Don't claim unavailable later.

## WORKFLOW
0. Identify ownership: get_resource_info('tags') and get_resource_info('iam_role') on primary resource.
1. Check real-time metrics (get_monitoring_data('bedrock_usage'), get_monitoring_data('alarms'))
2. Check what changed (get_recent_changes('bedrock'))
3. Check patterns (manage_patterns('find', 'pattern-type'))
4. Get dollar context (get_cost_data('usage'))
5. Explain root cause + recommend action
6. Save pattern (manage_patterns('save')) if new

## OUTPUT
If your response has data, metrics, or findings — use ```json tiles. Plain text for simple answers. You decide based on content. No emojis in responses.
Before writing blind_spots, verify you tried 2+ relevant tools first."""
        
        # If no Gateway, just use local tools
        if not gateway_endpoint:
            logger.info("No Gateway configured — using local tools only")
            agent = Agent(
                model=model,
                tools=local_tools,
                system_prompt=system_prompt_template
            )
            logger.info(f"✅ Agent created with {len(local_tools)} local tools (no Gateway)")
            return

        # Connect to Gateway for MCP tools
        logger.info("🔧 Initializing MCP Client with SigV4 authentication...")
        mcp_client = MCPClient(lambda: streamablehttp_client_with_sigv4(
            url=gateway_endpoint,
            credentials=frozen_credentials,
            service="bedrock-agentcore",
            region=AWS_REGION
        ))
        mcp_client.__enter__()
        logger.info("📋 Listing tools from Gateway...")
        mcp_tools = mcp_client.list_tools_sync()
        logger.info(f"✅ Retrieved {len(mcp_tools)} tools from Gateway")

        # Create agent with Gateway tools (memory will be added per-request)
        agent = Agent(
            model=model,
            tools=local_tools,
            system_prompt=system_prompt_template
        )
        
        logger.info("✅ Agent created successfully with Gateway tools - connection kept alive")
            
    except Exception as e:
        logger.error(f"❌ Error initializing agent with Gateway: {e}", exc_info=True)
        # Create a fallback agent without tools
        agent = Agent(
            model=model,
            system_prompt="I'm sorry, but I'm having trouble accessing my tools right now. Please try again later."
        )


# Initialize agent with Gateway
logger.info("🚀 Initializing agent with Gateway-backed MCP tools using IAM SigV4 authentication")
initialize_agent_with_gateway()


@app.entrypoint
def invoke(payload):
    """
    Process user input and return FinOps analysis
    """
    global agent

    user_message = payload.get("prompt", "")
    session_id = payload.get("sessionId", "default_session")
    user_id = payload.get("userId", "default_user")

    if not user_message:
        logger.error("No prompt provided in payload")
        return {
            "error": "No prompt provided",
            "message": "Please provide a 'prompt' key in the input"
        }

    logger.info(f"📨 Processing request - Session: {session_id}")

    # Select skill based on query
    skill_instructions = select_skill(user_message)
    request_prompt = system_prompt_template
    if skill_instructions:
        request_prompt = f"""{system_prompt_template}

## ACTIVE SKILL:

{skill_instructions}
"""

    # Create agent with memory session manager if memory is configured
    agent_with_memory = agent  # Default to base agent

    if MEMORY_ID:  # Configure memory and skill-enhanced prompt
        try:
            logger.info(f"💾 Configuring memory - Memory ID: {MEMORY_ID}, Session: {session_id}")

            memory_config = AgentCoreMemoryConfig(
                memory_id=MEMORY_ID,
                session_id=session_id,
                actor_id=user_id
            )

            session_manager = AgentCoreMemorySessionManager(
                agentcore_memory_config=memory_config,
                region_name=AWS_REGION
            )

            # Create agent with session manager (memory handled automatically)
            agent_with_memory = Agent(
                model=model,
                tools=local_tools,  # Use globally stored tools + local tools
                system_prompt=request_prompt,  # Skill-enhanced prompt
                session_manager=session_manager  # This handles memory automatically!
            )

            logger.info("✅ Agent configured with memory session manager")

        except Exception as e:
            logger.warning(f"⚠️ Could not configure memory, using agent without memory: {e}")
            agent_with_memory = Agent(model=model, tools=local_tools, system_prompt=request_prompt)
    else:
        logger.info("ℹ️ Memory not configured, using agent without memory")
        agent_with_memory = Agent(model=model, tools=local_tools, system_prompt=request_prompt)

    # Invoke agent - memory is handled automatically by session_manager
    try:
        logger.info("🤖 Invoking agent...")
        result = agent_with_memory(user_message)

        # Extract the final message from the result
        if hasattr(result, 'message'):
            final_message = result.message
        elif hasattr(result, 'content'):
            final_message = result.content
        elif isinstance(result, str):
            final_message = result
        else:
            final_message = str(result)

        # If final_message is a dict with role/content structure, extract the text
        if isinstance(final_message, dict):
            if 'content' in final_message and isinstance(final_message['content'], list):
                final_message = ''.join([item.get('text', '') for item in final_message['content'] if 'text' in item])
            elif 'text' in final_message:
                final_message = final_message['text']

        logger.info("✅ Request processed successfully")

        # Auto-save investigation if response has structured findings
        try:
            import re as _re, json as _json, uuid as _uuid
            json_match = _re.search(r'```json\s*([\s\S]*?)```', str(final_message))
            if json_match:
                parsed = _json.loads(json_match.group(1).strip())
                if parsed.get('findings') and len(parsed.get('findings', [])) > 0:
                    inv_table = ddb.Table(os.environ.get('INVESTIGATIONS_TABLE', 'cost_investigations'))
                    inv_table.put_item(Item={
                        'investigation_id': str(_uuid.uuid4()),
                        'alarm_name': parsed.get('summary', '')[:50],
                        'severity': parsed.get('severity', 'info'),
                        'summary': parsed.get('summary', ''),
                        'findings': _json.dumps(parsed.get('findings', [])),
                        'timeline': _json.dumps(parsed.get('timeline', [])),
                        'actions': _json.dumps(parsed.get('actions', [])),
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'status': 'completed'
                    })
                    logger.info("💾 Investigation auto-saved to DynamoDB")
        except Exception as save_err:
            logger.warning(f"Could not auto-save investigation: {save_err}")

        response = {
            "result": final_message,
            "sessionId": session_id,
            "userId": user_id
        }

        return response

    except Exception as e:
        logger.error(f"❌ Agent invocation error: {e}", exc_info=True)
        return {
            "error": "Agent processing failed",
            "message": str(e),
            "sessionId": session_id
        }


if __name__ == "__main__":
    logger.info("🚀 Starting FinOps Agent Runtime with BedrockAgentCoreApp")
    logger.info(f"📊 Model: {MODEL_ID}")
    logger.info(f"🌐 Gateway: {gateway_endpoint}")
    logger.info(f"💾 Memory: {MEMORY_ID if MEMORY_ID else 'Disabled'}")
    
    # Start Slack Socket Mode (direct connection, no Lambda needed)
    def slack_agent_invoke(prompt, session_id, user_id):
        """Called by Slack handler to invoke the agent."""
        try:
            skill_instructions = select_skill(prompt)
            request_prompt = f"{system_prompt_template}\n\n## ACTIVE SKILL:\n{skill_instructions}"
            agent_instance = Agent(model=model, tools=mcp_tools + local_tools, system_prompt=request_prompt)
            result = agent_instance(prompt)
            if hasattr(result, 'message'):
                msg = result.message
                if isinstance(msg, dict) and 'content' in msg:
                    return ''.join([item.get('text', '') for item in msg['content'] if 'text' in item])
                return str(msg)
            return str(result)
        except Exception as e:
            return f"Error: {str(e)}"
    
    set_agent_fn(slack_agent_invoke)
    start_slack_listener()
    logger.info("🔌 Slack Socket Mode started")
    
    app.run()


@app.websocket
async def websocket_handler(websocket, context):
    """WebSocket handler for real-time streaming to web UI."""
    import json as _json
    await websocket.accept()
    
    try:
        data = await websocket.receive_json()
        user_message = data.get('prompt', '')
        session_id = data.get('sessionId', 'ws-default')
        model_choice = data.get('model', 'sonnet')
        
        if not user_message:
            await websocket.send_json({"type": "error", "message": "No prompt provided"})
            await websocket.close()
            return
        
        # Select skill and build prompt
        skill_instructions = select_skill(user_message)
        request_prompt = f"""{system_prompt_template}

## ACTIVE SKILL:
{skill_instructions}

REMINDER: If your response contains findings, metrics, or comparisons — respond with structured JSON. Always use tiles for data.
"""
        selected_model = haiku_model if model_choice == "haiku" else model
        
        # Send status
        await websocket.send_json({"type": "status", "message": "Starting investigation..."})
        
        # Create agent with tool use callback
        from strands import Agent
        from strands.agent.callback_handler import CallbackHandler
        
        class StreamingCallback(CallbackHandler):
            def __init__(self, ws):
                self._ws = ws
                self._loop = None
                import asyncio
                self._loop = asyncio.get_event_loop()
                
            def on_tool_start(self, tool_name, tool_input):
                import asyncio
                asyncio.ensure_future(
                    self._ws.send_json({"type": "tool_start", "tool": tool_name}),
                    loop=self._loop
                )
            
            def on_tool_end(self, tool_name, tool_output):
                import asyncio
                # Send abbreviated result
                output_str = str(tool_output)[:200]
                asyncio.ensure_future(
                    self._ws.send_json({"type": "tool_end", "tool": tool_name, "result": output_str}),
                    loop=self._loop
                )
        
        try:
            callback = StreamingCallback(websocket)
            agent_instance = Agent(
                model=selected_model,
                tools=local_tools,
                system_prompt=request_prompt,
                callback_handler=callback
            )
            result = agent_instance(user_message)
            
            # Extract final message
            if hasattr(result, 'message'):
                final = result.message
            elif isinstance(result, str):
                final = result
            else:
                final = str(result)
            
            if isinstance(final, dict):
                if 'content' in final and isinstance(final['content'], list):
                    final = ''.join([item.get('text', '') for item in final['content'] if 'text' in item])
            
            await websocket.send_json({"type": "response", "message": str(final)})
        except Exception as e:
            await websocket.send_json({"type": "error", "message": str(e)})
        
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await websocket.close()
