"""
Slack Socket Mode handler - runs INSIDE AgentCore.
No Lambda, no API Gateway. Direct WebSocket connection to Slack.
"""
import os
import threading
import logging
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

logger = logging.getLogger(__name__)

SLACK_BOT_TOKEN = os.environ.get('SLACK_BOT_TOKEN', '')
SLACK_APP_TOKEN = os.environ.get('SLACK_APP_TOKEN', '')

app = None
if SLACK_BOT_TOKEN:
    app = App(token=SLACK_BOT_TOKEN)

# Will be set by agent_runtime.py after agent is initialized
agent_invoke_fn = None


def set_agent_fn(fn):
    """Called by agent_runtime.py to provide the agent invocation function."""
    global agent_invoke_fn
    agent_invoke_fn = fn


def _handle_mention(event, say):
    """User @mentioned the bot in a channel."""
    text = event.get('text', '').split('>', 1)[-1].strip()
    thread_ts = event.get('thread_ts', event.get('ts'))
    user = event.get('user', 'unknown')
    
    say(text="🔍 Investigating...", thread_ts=thread_ts)
    
    if agent_invoke_fn:
        response = agent_invoke_fn(text, f"slack-{thread_ts}", user)
        say(text=response, thread_ts=thread_ts)
    else:
        say(text="Agent not ready. Try again in a moment.", thread_ts=thread_ts)


def _handle_dm(event, say):
    """User sent a DM to the bot."""
    if event.get('channel_type') != 'im':
        return
    if event.get('bot_id'):
        return
    
    text = event.get('text', '')
    thread_ts = event.get('thread_ts', event.get('ts'))
    user = event.get('user', 'unknown')
    
    say(text="🔍 Investigating...", thread_ts=thread_ts)
    
    if agent_invoke_fn:
        response = agent_invoke_fn(text, f"slack-dm-{thread_ts}", user)
        say(text=response, thread_ts=thread_ts)
    else:
        say(text="Agent not ready. Try again in a moment.", thread_ts=thread_ts)


if app:
    app.event("app_mention")(_handle_mention)
    app.event("message")(_handle_dm)


def start_socket_mode():
    """Start Socket Mode in a background thread."""
    if not app or not SLACK_APP_TOKEN:
        logger.info("⏭️ Slack not configured (no tokens), skipping")
        return
    try:
        handler = SocketModeHandler(app, SLACK_APP_TOKEN)
        logger.info("🔌 Starting Slack Socket Mode connection...")
        handler.start()
    except Exception as e:
        logger.error(f"❌ Slack Socket Mode failed: {e}")


def start_slack_listener():
    """Start Slack listener in background thread so it doesn't block AgentCore."""
    if not app or not SLACK_APP_TOKEN:
        logger.info("⏭️ Slack not configured, skipping listener")
        return
    thread = threading.Thread(target=start_socket_mode, daemon=True)
    thread.start()
    logger.info("✅ Slack listener started in background")
