"""
Skill loader - selects and loads the right SKILL.md based on the user's query.
"""
import os

SKILLS_DIR = os.path.join(os.path.dirname(__file__), 'skills')

SKILLS = {
    'cost-spike-investigation': {
        'keywords': ['investigate', 'spike', 'alarm', 'anomaly', 'why', 'caused', 'root cause', 'firing', 'alert', 'surge', 'jump', 'increased', 'unusual'],
        'path': 'cost-spike-investigation/SKILL.md'
    },
    'agent-economics-review': {
        'keywords': ['agent cost', 'which agent', 'per-agent', 'agent economics', 'expensive agent', 'loop', 'token usage', 'per agent', 'agent breakdown'],
        'path': 'agent-economics-review/SKILL.md'
    },
    'cost-overview': {
        'keywords': ['cost', 'spend', 'budget', 'summary', 'overview', 'total', 'how much', 'top services', 'forecast'],
        'path': 'cost-overview/SKILL.md'
    }
}

def select_skill(query: str) -> str:
    """Select the most relevant skill based on query keywords. Returns skill instructions."""
    query_lower = query.lower()
    
    # Score each skill by keyword matches
    scores = {}
    for name, config in SKILLS.items():
        score = sum(1 for kw in config['keywords'] if kw in query_lower)
        if score > 0:
            scores[name] = score
    
    # Pick highest scoring skill, default to cost-spike-investigation for alerts
    if not scores:
        # Default: if query mentions bedrock/token/rpm, use investigation
        if any(w in query_lower for w in ['bedrock', 'token', 'rpm', 'invocation', 'cloudwatch']):
            selected = 'cost-spike-investigation'
        elif any(w in query_lower for w in ['cost', 'spend', 'budget', 'price', 'bill', 'money', 'dollar', 'forecast', 'usage', 'how much']):
            selected = 'cost-overview'
        else:
            return ""  # No skill - let agent answer naturally
    else:
        selected = max(scores, key=scores.get)
    
    # Load the skill file
    skill_path = os.path.join(SKILLS_DIR, SKILLS[selected]['path'])
    try:
        with open(skill_path, 'r') as f:
            content = f.read()
        # Strip frontmatter
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                return parts[2].strip()
        return content
    except FileNotFoundError:
        return ""
