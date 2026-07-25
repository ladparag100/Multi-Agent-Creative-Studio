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
        secrets = st.secrets
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
        if key in secrets:
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

EXAMPLE_BRIEF = """Create a complete Instagram campaign for:
- Product: EcoFlow Smart Water Bottle (tracks hydration, keeps drinks cold 24h)
- Target Audience: Health-conscious millennials, 25-35 years old
- Platform: Instagram
- Goal: Brand awareness + drive website traffic
- Brand Voice: Motivational, clean, science-backed
- Budget: $3,000
- Timeline: Launch in 2 weeks"""


def run_async(coro):
    return asyncio.run(coro)


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
    st.info(
        "Try a full campaign brief, or a simple request like *'just do market research "
        "for a cold brew coffee brand'*."
    )
    if st.button("Use example campaign brief"):
        st.session_state.prefill = EXAMPLE_BRIEF
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

    st.session_state.messages.append(
        {
            "role": "assistant",
            "activity": activity_lines,
            "content": turn_content,
        }
    )
    st.rerun()
