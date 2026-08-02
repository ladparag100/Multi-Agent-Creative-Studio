"""
Streamlit UI for AI Creative Studio.

Runs the Creative Director in-process (via an ADK Runner) and lets it
orchestrate the 5 specialist agents - brand_strategist, copywriter, designer,
critic, project_manager - reachable via the *_AGENT_URL settings below.

Local dev (specialists as local A2A servers):
    ./run_local_agents.sh

Streamlit Community Cloud (specialists deployed to Cloud Run):
    Set GOOGLE_API_KEY (from aistudio.google.com/apikey), GOOGLE_GENAI_USE_VERTEXAI=0,
    and the 5 *_AGENT_URL values in the app's Secrets - see
    .streamlit/secrets.toml.example. Generated images are read from a
    public-read GCS bucket over plain HTTPS, so no GCP credentials are
    needed on this side at all (only the Cloud Run specialists need GCP
    auth, and Cloud Run already gives them that for free via their
    attached service account).
"""

import asyncio
import os
import re
import sys
import uuid
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()


def _load_secrets_into_env():
    """On Streamlit Community Cloud there's no .env - config comes from
    st.secrets instead. Copy it into the process environment before any
    agent module is imported. No-op locally when no secrets.toml exists
    (.env covers that)."""
    try:
        # st.secrets parses secrets.toml lazily - accessing the object itself
        # never raises, so force the parse here (inside the try) rather than
        # in the loop below, where it would go uncaught.
        secrets = st.secrets
        available = set(secrets.keys())
    except Exception:
        return

    for key in (
        "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI",
        "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION", "GEMINI_MODEL",
        "GEMINI_IMAGE_MODEL", "GCS_IMAGES_BUCKET", "SIGNING_SERVICE_ACCOUNT",
        "STRATEGIST_AGENT_URL", "COPYWRITER_AGENT_URL", "DESIGNER_AGENT_URL",
        "CRITIC_AGENT_URL", "PM_AGENT_URL",
        "NOTION_TOKEN", "NOTION_PROJECT_DATABASE_ID", "NOTION_TASKS_DATABASE_ID",
    ):
        if key in available:
            os.environ[key] = str(secrets[key])


_load_secrets_into_env()

from google.genai import types  # noqa: E402

APP_NAME = "creative_director"
USER_ID = "streamlit-user"

SPECIALISTS = [
    ("brand_strategist", "STRATEGIST_AGENT_URL", "🔎"),
    ("copywriter", "COPYWRITER_AGENT_URL", "✍️"),
    ("designer", "DESIGNER_AGENT_URL", "🎨"),
    ("critic", "CRITIC_AGENT_URL", "🧐"),
    ("project_manager", "PM_AGENT_URL", "🗂️"),
]
AGENT_ICONS = {name: icon for name, _, icon in SPECIALISTS}
AGENT_ICONS["creative_director"] = "🎬"
AGENT_LABELS = {
    "creative_director": "Creative Director",
    "brand_strategist": "Brand Strategist",
    "copywriter": "Copywriter",
    "designer": "Designer",
    "critic": "Critic",
    "project_manager": "Project Manager",
}

# Transient A2A hiccups the Creative Director sometimes narrates even though it
# retries and recovers on its own - strip these out so the visible chat only
# shows things the user actually needs to know about.
_TRANSIENT_RETRY_RE = re.compile(
    r"^\s*[⚠️❕❔]*\s*.*\breturned an empty response\b.*\bretrying\b.*$",
    re.IGNORECASE | re.MULTILINE,
)

ECOFLOW_BRIEF = """Create a complete Instagram campaign for:
- Product: EcoFlow Smart Water Bottle - an insulated stainless steel bottle with a
  built-in hydration sensor that tracks intake via a companion app over Bluetooth,
  keeps drinks cold for 24 hours or hot for 12. Available in 3 colors, retails at $45.
- Target Audience: Health-conscious millennials, 25-35 years old, urban and suburban
  gym-goers and remote workers who like data-driven self-improvement and wellness habits.
- Platform: Instagram (feed posts and Stories)
- Goal: Brand awareness and drive traffic to the website for the pre-order launch
- Key differentiators: Real-time hydration tracking, 24h cold retention, sleek
  minimalist design, app integration with drink reminders
- Brand Voice: Motivational, clean, science-backed, no-nonsense wellness tone
- Budget: $3,000
- Timeline: Launch in 2 weeks; pre-order window is open now
- Offer: 15% off pre-orders, free shipping over $50"""

COLDBREW_BRIEF = """Create a complete Instagram campaign for:
- Product: Roast & Root - a small-batch, single-origin cold brew coffee roastery known
  for slow-steeped (18-hour), low-acid cold brew concentrate sold in reusable glass
  bottles. Holiday gift sets pair a bottle with a reusable glass tumbler and a tasting
  notes card.
- Target Audience: Young professionals, 24-38 years old, coffee enthusiasts and gift
  shoppers looking for thoughtful artisanal presents; urban dwellers who value
  sustainability and small-batch/local craft goods.
- Platform: Instagram (feed posts plus Reels for unboxing and gifting moments)
- Goal: Drive holiday gift-set sales during the November-December gifting season
- Key differentiators: Single-origin beans, 18-hour slow-steeped process, reusable
  and sustainable packaging, small-batch local roaster story
- Brand Voice: Cozy, indulgent, warm, a little playful - coffee as a treat-yourself
  or gift-someone-you-love moment
- Budget: $2,000
- Timeline: 4-week campaign leading up to the holidays; gift sets ship by Dec 20
- Offer: Buy 2 gift sets, get a free tasting-notes card set; limited holiday packaging"""

SHELTER_BRIEF = """Create a complete Instagram campaign for:
- Cause: Paws & Home - a local no-kill animal shelter currently housing 40+ dogs and
  cats awaiting adoption, running a "Home for the Holidays" adoption drive.
- Target Audience: Local community members, 22-55 years old, within a 30-mile radius;
  animal lovers and families considering pet adoption, plus existing shelter donors
  and volunteers.
- Platform: Instagram (feed posts featuring adoptable pets, plus Stories/Reels for
  shelter tours and individual pet profiles)
- Goal: Increase adoption applications and one-time or recurring donations during the
  holiday season
- Key details: Adoption fees waived this month for senior pets (5+ years); the shelter
  covers the first vet visit and microchipping; volunteers needed for weekend events
- Brand Voice: Warm, emotional, hopeful, community-focused - heartfelt and uplifting,
  not guilt-driven
- Budget: $800 (small nonprofit budget)
- Timeline: 3-week campaign culminating in a weekend adoption fair
- Offer: Waived adoption fees for pets 5+ years old; a $25 minimum donation covers one
  pet's vaccinations"""

EXAMPLE_CAMPAIGNS = [
    ("💧 EcoFlow Water Bottle", ECOFLOW_BRIEF),
    ("☕ Roast & Root Cold Brew (holiday gift set)", COLDBREW_BRIEF),
    ("🐾 Paws & Home Shelter (adoption drive)", SHELTER_BRIEF),
]


def run_async(coro):
    """Run a coroutine on one event loop kept alive for this browser session.

    get_runner() below is cached per-process, so the same RemoteA2aAgent
    instances (and the async HTTP clients they lazily create) persist across
    every message. asyncio.run() would close its loop after each call,
    orphaning those clients and breaking every A2A request from the second
    message onward ("Event loop is closed"). Reusing one loop per session
    (Streamlit pins a session to one thread for its lifetime) keeps them
    valid for as long as the session lasts.
    """
    if "event_loop" not in st.session_state or st.session_state.event_loop.is_closed():
        st.session_state.event_loop = asyncio.new_event_loop()
    return st.session_state.event_loop.run_until_complete(coro)


@st.cache_resource(show_spinner=False)
def get_runner():
    """Build the Creative Director runner once per Streamlit process."""
    from google.adk.artifacts import InMemoryArtifactService
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    from agents.creative_director.agent import root_app

    return Runner(
        app=root_app,
        session_service=InMemorySessionService(),
        artifact_service=InMemoryArtifactService(),
        auto_create_session=True,
    )


def check_agent(url: str) -> bool:
    try:
        resp = requests.get(f"{url}/.well-known/agent.json", timeout=1.5)
        return resp.status_code == 200
    except requests.RequestException:
        return False


@st.cache_data(ttl=600, show_spinner=False)
def fetch_image_bytes(gcs_uri: str) -> bytes:
    """Fetch a generated image over plain HTTPS - the campaign-images bucket
    is public-read, so no GCP credentials are needed here."""
    without_prefix = gcs_uri[len("gs://"):]
    bucket_name, blob_path = without_prefix.split("/", 1)
    url = f"https://storage.googleapis.com/{bucket_name}/{blob_path}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.content


def new_session():
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.messages = []
    runner = get_runner()
    run_async(
        runner.session_service.create_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=st.session_state.session_id
        )
    )


async def stream_campaign(runner, session_id, message_text, activity, live, activity_lines):
    """Drive the Creative Director for one turn, updating the UI as events arrive."""
    content = types.Content(role="user", parts=[types.Part(text=message_text)])
    turn_content = []

    def log(line: str):
        activity_lines.append(line)
        activity.write(line)

    async for event in runner.run_async(
        user_id=USER_ID, session_id=session_id, new_message=content
    ):
        author = event.author or "creative_director"
        icon = AGENT_ICONS.get(author, "🤖")
        label = AGENT_LABELS.get(author, author)

        for fc in event.get_function_calls():
            log(f"{icon} **{label}** → calling `{fc.name}`")
            # display_image's own response has no gcs_uri (it just saves an ADK
            # artifact, which this UI doesn't render) - the URI lives in the call
            # arguments instead, so pull it from there to actually show the image.
            if fc.name == "display_image" and fc.args and fc.args.get("gcs_uri"):
                gcs_uri = fc.args["gcs_uri"]
                item = {
                    "type": "image",
                    "author": author,
                    "gcs_uri": gcs_uri,
                    "caption": fc.args.get("concept_name", ""),
                }
                turn_content.append(item)
                try:
                    live.image(fetch_image_bytes(gcs_uri), caption=item["caption"])
                except Exception as e:
                    live.warning(f"Could not load image ({gcs_uri}): {e}")

        for fr in event.get_function_responses():
            resp = fr.response or {}
            status = resp.get("status")
            if status == "error":
                log(f"⚠️ **{label}** ← `{fr.name}` error: {resp.get('error')}")
            else:
                log(f"✅ **{label}** ← `{fr.name}` done")

        if event.partial:
            continue

        if event.content and event.content.parts:
            text = "".join(p.text for p in event.content.parts if p.text)
            text = _TRANSIENT_RETRY_RE.sub("", text).strip()
            if text.strip():
                turn_content.append({"type": "text", "author": author, "text": text})
                with live.container():
                    st.markdown(f"**{icon} {label}**")
                    st.markdown(text)

        if event.error_message:
            turn_content.append(
                {"type": "text", "author": author, "text": f"❌ Error: {event.error_message}"}
            )
            live.error(f"{label}: {event.error_message}")

    return turn_content


def _is_malformed_function_call(turn_content) -> bool:
    """True if the turn ended in Gemini's MALFORMED_FUNCTION_CALL finish reason.

    This is a transient generation quirk - the model occasionally fails to
    serialize a function call with very long/punctuation-heavy string
    arguments (e.g. a full campaign brief passed to a specialist tool). It is
    not a real failure, so it is worth silently retrying the same turn rather
    than surfacing it to the user.
    """
    return any(
        item["type"] == "text" and "Malformed function call" in item["text"]
        for item in turn_content
    )


def render_history_message(msg):
    if msg["role"] == "user":
        with st.chat_message("user"):
            st.markdown(msg["text"])
        return

    with st.chat_message("assistant", avatar="🎬"):
        if msg.get("activity"):
            with st.expander("Agent activity", expanded=False):
                for line in msg["activity"]:
                    st.markdown(line)
        for item in msg.get("content", []):
            icon = AGENT_ICONS.get(item["author"], "🤖")
            label = AGENT_LABELS.get(item["author"], item["author"])
            if item["type"] == "text":
                st.markdown(f"**{icon} {label}**")
                st.markdown(item["text"])
            elif item["type"] == "image":
                try:
                    st.image(fetch_image_bytes(item["gcs_uri"]), caption=item["caption"])
                except Exception as e:
                    st.warning(f"Could not load image ({item['gcs_uri']}): {e}")


st.set_page_config(page_title="AI Creative Studio", page_icon="🎬", layout="wide")

with st.sidebar:
    st.header("🎬 AI Creative Studio")
    st.caption("Creative Director orchestrating 5 specialist agents over A2A")

    st.subheader("Specialist agents")
    for name, env_key, icon in SPECIALISTS:
        url = os.environ.get(env_key, "")
        if not url:
            status = "⚪"
        elif check_agent(url):
            status = "🟢"
        else:
            status = "🔴"
        st.markdown(f"{icon} {AGENT_LABELS[name]} {status}")

    st.divider()
    if st.button("🔄 New conversation", width="stretch"):
        new_session()
        st.rerun()

if "session_id" not in st.session_state:
    with st.spinner("Starting session..."):
        new_session()

st.title("AI Creative Studio")
st.caption(
    "Describe a campaign and the Creative Director will delegate to the Brand Strategist, "
    "Copywriter, Designer, Critic, and Project Manager as needed."
)

for msg in st.session_state.messages:
    render_history_message(msg)

if not st.session_state.messages:
    st.info("Describe your own campaign below, or try one of these example briefs:")
    cols = st.columns(len(EXAMPLE_CAMPAIGNS))
    for col, (label, brief) in zip(cols, EXAMPLE_CAMPAIGNS):
        with col:
            if st.button(label, width="stretch"):
                st.session_state.prefill = brief
                st.rerun()

prompt = st.chat_input("Describe your campaign, or ask for a revision...")
if "prefill" in st.session_state:
    prompt = st.session_state.pop("prefill")

if prompt:
    st.session_state.messages.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant", avatar="🎬"):
        activity_box = st.expander("Agent activity", expanded=True)
        live_area = st.container()
        activity_lines = []
        with st.spinner("Coordinating specialists..."):
            turn_content = run_async(
                stream_campaign(
                    get_runner(),
                    st.session_state.session_id,
                    prompt,
                    activity_box,
                    live_area,
                    activity_lines,
                )
            )

            retries = 0
            max_retries = 2
            while _is_malformed_function_call(turn_content) and retries < max_retries:
                retries += 1
                line = f"⚠️ Model produced a malformed function call, retrying ({retries}/{max_retries})..."
                activity_lines.append(line)
                activity_box.write(line)
                turn_content = run_async(
                    stream_campaign(
                        get_runner(),
                        st.session_state.session_id,
                        prompt,
                        activity_box,
                        live_area,
                        activity_lines,
                    )
                )

    st.session_state.messages.append(
        {
            "role": "assistant",
            "activity": activity_lines,
            "content": turn_content,
        }
    )
    st.rerun()
