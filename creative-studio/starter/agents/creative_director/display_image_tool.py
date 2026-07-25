"""Artifact display tool: fetches a GCS image and saves it as an ADK artifact for inline rendering."""
import requests
from google.adk.tools import ToolContext
from google.genai import types


async def display_image(gcs_uri: str, concept_name: str, tool_context: ToolContext) -> dict:
    """
    Fetch a generated image and save it as an artifact so it renders inline.

    Call this for each gcs_uri received from the Designer to show images in the local UI.
    Fetched over plain public HTTPS (the campaign-images bucket is public-read) rather
    than an authenticated GCS client, so this works with no GCP credentials at all -
    e.g. when the Creative Director runs off-GCP (Streamlit Cloud) with only a Gemini
    API key and no service account.

    Args:
        gcs_uri: GCS URI of the image (gs://bucket/path.png)
        concept_name: Short label for this image (e.g. "caption1_concept_a")

    Returns:
        {"status": "success", "concept_name": "..."} or {"status": "error", "error": "..."}
    """
    try:
        without_prefix = gcs_uri[len("gs://"):]
        bucket_name, blob_path = without_prefix.split("/", 1)

        resp = requests.get(f"https://storage.googleapis.com/{bucket_name}/{blob_path}", timeout=10)
        resp.raise_for_status()
        image_bytes = resp.content

        ext = blob_path.rsplit(".", 1)[-1].lower() if "." in blob_path else "png"
        mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}
        mime_type = mime_map.get(ext, "image/png")

        artifact = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        await tool_context.save_artifact(f"{concept_name}.{ext}", artifact)
        return {"status": "success", "concept_name": concept_name}

    except ValueError:
        # No artifact service configured (e.g. Cloud Run) - silently skip
        return {"status": "success", "concept_name": concept_name}
    except Exception as e:
        return {"status": "error", "concept_name": concept_name, "error": str(e)}
