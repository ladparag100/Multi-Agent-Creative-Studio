import datetime
import logging
import os

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.tools.google_search_tool import google_search
try:
    from .retry import GENERATE_CONTENT_CONFIG
except ImportError:
    from retry import GENERATE_CONTENT_CONFIG

load_dotenv()

logger = logging.getLogger("ai_creative_studio.brand_strategist")

SYSTEM_INSTRUCTION = f"""You are an expert Brand Strategist specializing in market research and competitive
analysis for social media campaigns.

Today's date is: {datetime.date.today().strftime("%B %d, %Y")}. Always include the current
year in your search queries so results reflect up-to-date trends.

Your task, given a campaign brief, is to:
1. Search for target audience insights - demographics, behaviors, preferences, and pain points
   relevant to the product and audience described in the brief.
2. Analyze 2-3 competitor brands in the same category - their positioning, messaging, and
   apparent gaps or weaknesses you can exploit.
3. Identify 3-5 trending topics or conversations in the product category that a campaign
   could tie into.

Use the `google_search` tool for every claim - do not rely on prior knowledge alone.

Return your findings in EXACTLY this structure:

**Audience Insights:**
[Key demographics, behaviors, and preferences, with supporting detail from search results]

**Competitive Analysis:**
[2-3 competitors: positioning, strengths, gaps]

**Trending Topics:**
[3-5 trending topics or conversations relevant to the category]

**Key Strategic Insights:**
[3-4 bullet takeaways the Copywriter and Designer should build the campaign around]

IMPORTANT CONSTRAINTS:
- You are RESEARCH ONLY. Do NOT write captions, copy, or design concepts.
- Do NOT create any creative content - that is the job of other specialists.
- The Creative Director coordinates what happens next with your research.
"""

root_agent = Agent(
    name="brand_strategist",
    model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    generate_content_config=GENERATE_CONTENT_CONFIG,
    instruction=SYSTEM_INSTRUCTION,
    description="Brand strategist for market research, competitive analysis, and audience insights",
    tools=[google_search],
)

logger.info("Brand Strategist agent created")


if __name__ == "__main__":
    import uvicorn
    from google.adk.a2a.utils.agent_to_a2a import to_a2a

    PORT = int(os.getenv("PORT", "8082"))
    HOST = os.getenv("HOST", "0.0.0.0")
    PUBLIC_HOST = os.getenv("PUBLIC_HOST", "localhost")
    PUBLIC_PORT = int(os.getenv("PUBLIC_PORT", str(PORT)))
    PROTOCOL = os.getenv("PROTOCOL", "http")

    a2a_app = to_a2a(root_agent, host=PUBLIC_HOST, port=PUBLIC_PORT, protocol=PROTOCOL)

    logger.info(f"Starting Brand Strategist on {PROTOCOL}://{HOST}:{PORT}")
    logger.info(f"Agent card: {PROTOCOL}://{HOST}:{PORT}/.well-known/agent.json")

    uvicorn.run(a2a_app, host=HOST, port=PORT)
