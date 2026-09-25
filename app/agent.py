# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import datetime
import json
import os
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo
from google import genai
from google.cloud import firestore, storage

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.memory import VertexAiMemoryBankService
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.load_memory_tool import LoadMemoryTool
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.genai import types

from .a2ui_utils import a2ui_callback

# Hardcoded Project ID, Bucket Name, and Memory Bank ID strings (required for Agent Platform compatibility)
FIRESTORE_PROJECT_ID = "qwiklabs-gcp-01-8bad3776c23c"
GCS_BUCKET_NAME = "engineering-knowledge-twin-assets-8bad3776"
MEMORY_BANK_ID = "314414146055569408"

# Load Agent Engine resource name / sandbox from deployment_metadata.json if available
deployment_metadata_file = (
    Path(__file__).resolve().parent.parent / "deployment_metadata.json"
)
engine_resource_name = None
sandbox_resource_name = None

if deployment_metadata_file.exists():
    metadata = json.loads(deployment_metadata_file.read_text())
    engine_resource_name = metadata.get("remote_agent_runtime_id")
    sandbox_resource_name = metadata.get("sandbox_resource_name")

code_executor = AgentEngineSandboxCodeExecutor(
    sandbox_resource_name=sandbox_resource_name,
    agent_engine_resource_name=engine_resource_name,
)


def memory_bank_service_builder():
    """Build and return a VertexAiMemoryBankService instance targeting the deployed Memory Bank."""
    return VertexAiMemoryBankService(
        project=FIRESTORE_PROJECT_ID,
        location="us-east1",
        agent_engine_id=MEMORY_BANK_ID,
    )


async def generate_memories_callback(callback_context: CallbackContext):
    """WRITE: After each agent turn, extract and send durable facts to Memory Bank."""
    try:
        await callback_context.add_session_to_memory()
    except (ValueError, Exception) as e:
        pass
    return None



def list_incidents(service: str = "", status: str = "") -> str:
    """List or search engineering incidents stored in the Firestore database.

    Args:
        service: Optional service name to filter by (e.g. 'auth-service', 'billing-service').
        status: Optional status to filter by (e.g. 'OPEN', 'INVESTIGATING', 'RESOLVED').

    Returns:
        A string summarizing the matching incidents.
    """
    db = firestore.Client(project=FIRESTORE_PROJECT_ID)
    query_ref = db.collection("incidents")

    if service:
        query_ref = query_ref.where("service", "==", service)
    if status:
        query_ref = query_ref.where("status", "==", status)

    docs = query_ref.stream()
    incidents = [doc.to_dict() for doc in docs]

    if not incidents:
        return "No incidents found matching the criteria."

    lines = []
    for inc in incidents:
        lines.append(
            f"ID: {inc.get('incident_id')} | Title: {inc.get('title')} | "
            f"Service: {inc.get('service')} | Severity: {inc.get('severity')} | "
            f"Status: {inc.get('status')} | Assigned: {inc.get('assigned_to')}"
        )
    return "\n".join(lines)


def get_incident_details(incident_id: str) -> str:
    """Get complete details for a specific engineering incident from Firestore.

    Args:
        incident_id: The ID of the incident (e.g. 'INC-101').

    Returns:
        A string containing full details of the incident.
    """
    db = firestore.Client(project=FIRESTORE_PROJECT_ID)
    doc_ref = db.collection("incidents").document(incident_id)
    doc = doc_ref.get()

    if not doc.exists:
        return f"Incident {incident_id} not found."

    inc = doc.to_dict()
    return (
        f"Incident ID: {inc.get('incident_id')}\n"
        f"Title: {inc.get('title')}\n"
        f"Service: {inc.get('service')}\n"
        f"Severity: {inc.get('severity')}\n"
        f"Status: {inc.get('status')}\n"
        f"Assigned To: {inc.get('assigned_to')}\n"
        f"Created At: {inc.get('created_at')}\n"
        f"Description: {inc.get('description')}"
    )


def create_incident(
    incident_id: str,
    title: str,
    service: str,
    severity: str,
    description: str,
    assigned_to: str,
) -> str:
    """Create and record a new engineering incident in Firestore.

    Args:
        incident_id: Unique incident ID (e.g. 'INC-104').
        title: Short title summarizing the issue.
        service: Microservice or component affected (e.g. 'auth-service').
        severity: Severity level (e.g. 'SEV-1', 'SEV-2', 'SEV-3').
        description: Detailed explanation of the incident symptoms or root cause.
        assigned_to: Email or name of the assigned engineer.

    Returns:
        Confirmation message.
    """
    db = firestore.Client(project=FIRESTORE_PROJECT_ID)
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

    incident_data = {
        "incident_id": incident_id,
        "title": title,
        "service": service,
        "severity": severity,
        "status": "OPEN",
        "description": description,
        "assigned_to": assigned_to,
        "created_at": now_str,
    }

    db.collection("incidents").document(incident_id).set(incident_data)
    return f"Successfully created incident {incident_id} for {service}."


def update_incident_status(incident_id: str, status: str) -> str:
    """Update the status of an existing engineering incident in Firestore.

    Args:
        incident_id: The ID of the incident to update (e.g. 'INC-101').
        status: The new status value (e.g. 'INVESTIGATING', 'RESOLVED', 'CLOSED').

    Returns:
        Confirmation message.
    """
    db = firestore.Client(project=FIRESTORE_PROJECT_ID)
    doc_ref = db.collection("incidents").document(incident_id)

    if not doc_ref.get().exists:
        return f"Incident {incident_id} does not exist."

    doc_ref.update({"status": status})
    return f"Successfully updated incident {incident_id} status to {status}."


def check_service_health(service_name: str) -> str:
    """Check the real-time health, HTTP status, and latency of a microservice.

    Args:
        service_name: The name of the microservice (e.g. 'auth-service', 'billing-service').

    Returns:
        A diagnostic string detailing the service status, latency, and endpoint health.
    """
    service_statuses = {
        "auth-service": {
            "status": "DEGRADED",
            "http_code": 504,
            "latency_ms": 1250,
            "endpoint": "https://auth.novasmart.internal/health",
        },
        "billing-service": {
            "status": "HEALTHY",
            "http_code": 200,
            "latency_ms": 45,
            "endpoint": "https://billing.novasmart.internal/health",
        },
        "analytics-frontend": {
            "status": "HEALTHY",
            "http_code": 200,
            "latency_ms": 12,
            "endpoint": "https://analytics.novasmart.internal/health",
        },
    }

    clean_name = service_name.strip().lower()
    info = service_statuses.get(clean_name)
    if not info:
        return (
            f"Service '{service_name}' not recognized in service registry. "
            f"Active services: {', '.join(service_statuses.keys())}."
        )

    return (
        f"Service: {service_name}\n"
        f"Status: {info['status']}\n"
        f"HTTP Code: {info['http_code']}\n"
        f"Latency: {info['latency_ms']}ms\n"
        f"Endpoint: {info['endpoint']}"
    )


def get_github_repo_info(repo: str) -> str:
    """Fetch real-time metadata and repository statistics from GitHub's Public REST API.

    Args:
        repo: Repository identifier in 'owner/repo' format (e.g. 'google/adk-python', 'fastapi/fastapi').

    Returns:
        A formatted string summarizing repository details, star count, issues, and primary language.
    """
    clean_repo = repo.strip().strip("/")
    url = f"https://api.github.com/repos/{clean_repo}"

    headers = {"User-Agent": "Antigravity-Agent"}
    github_token = os.getenv("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())

        license_name = (
            data.get("license", {}).get("name") if data.get("license") else "None"
        )
        return (
            f"Repository: {data.get('full_name')}\n"
            f"Description: {data.get('description')}\n"
            f"Primary Language: {data.get('language')}\n"
            f"Stars: {data.get('stargazers_count')} | Forks: {data.get('forks_count')} | Open Issues: {data.get('open_issues_count')}\n"
            f"License: {license_name}\n"
            f"URL: {data.get('html_url')}"
        )
    except Exception as e:
        return f"Error fetching GitHub repository data for '{clean_repo}': {str(e)}"


async def generate_architecture_diagram(
    prompt: str, tool_context: ToolContext = None
) -> str:
    """Generate an architecture or component diagram image using gemini-3.1-flash-lite-image in the global region.

    Args:
        prompt: Description of the architecture or component diagram to generate.
        tool_context: Tool context injected by ADK to manage session artifacts.

    Returns:
        The public HTTPS URL of the generated image stored in Cloud Storage.
    """
    client = genai.Client(vertexai=True, location="global")
    res = client.models.generate_content(
        model="gemini-3.1-flash-lite-image",
        contents=f"System architecture diagram showing: {prompt}",
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )

    part = res.candidates[0].content.parts[0]
    image_bytes = part.inline_data.data
    mime_type = part.inline_data.mime_type or "image/png"

    filename = f"diagram_{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}.png"

    # 1. Save artifact so it shows up in Playground's Artifacts panel
    if tool_context:
        artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        await tool_context.save_artifact(filename=filename, artifact=artifact_part)

    # 2. Upload directly to public Cloud Storage bucket without writing local files
    storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
    bucket = storage_client.bucket(GCS_BUCKET_NAME)
    blob_name = f"diagrams/{filename}"
    blob = bucket.blob(blob_name)
    blob.upload_from_string(image_bytes, content_type=mime_type)

    return f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{blob_name}"


async def generate_item_video(
    prompt: str, tool_context: ToolContext = None
) -> str:
    """Generate a short video animation for an engineering item or microservice using gemini-omni-flash-preview in the global region.

    Args:
        prompt: Description of the engineering item or microservice video animation to generate.
        tool_context: Tool context injected by ADK to manage session artifacts.

    Returns:
        The public HTTPS URL of the generated video stored in Cloud Storage.
    """
    client = genai.Client(vertexai=True, location="global")
    interaction = client.interactions.create(
        model="gemini-omni-flash-preview",
        input=f"Short video animation showing: {prompt}",
    )

    if not hasattr(interaction, "output_video") or not interaction.output_video:
        return "Failed to generate video: no video output returned by the model."

    data = interaction.output_video.data
    if isinstance(data, str):
        video_bytes = base64.b64decode(data)
    else:
        video_bytes = data

    mime_type = getattr(interaction.output_video, "mime_type", None) or "video/mp4"
    filename = f"video_{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}.mp4"

    # 1. Save artifact so it shows up in Playground's Artifacts panel
    if tool_context:
        artifact_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
        await tool_context.save_artifact(filename=filename, artifact=artifact_part)

    # 2. Upload directly to public Cloud Storage bucket without writing local files
    storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
    bucket = storage_client.bucket(GCS_BUCKET_NAME)
    blob_name = f"videos/{filename}"
    blob = bucket.blob(blob_name)
    blob.upload_from_string(video_bytes, content_type=mime_type)

    return f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{blob_name}"


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are the Engineering Knowledge Twin Agent for NovaSmart. "
        "You help engineers troubleshoot system outages, track active incidents in Firestore, "
        "check live microservice health, query public GitHub repositories, generate architecture diagrams, "
        "generate item videos using Omni Flash, "
        "execute python code in a secure sandbox, and manage engineering knowledge. "
        "You remember the user's stated preferences and facts from previous conversations and use them to personalize responses."
    ),
    workflow_description="Analyze the request and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        "{\"Image\": {\"url\": {\"literalString\": \"https://...\"}}}. Never point an "
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)


async def load_memory(query: str, tool_context: ToolContext = None) -> str:
    """Retrieve memories from long-term Memory Bank.

    Args:
        query: Search query for retrieving stored facts.
    """
    if tool_context:
        try:
            memories = await tool_context.search_memory(query)
            return str(memories) if memories else "No relevant memories found."
        except Exception:
            return "Memory service is currently not available."
    return "No memory service attached."


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-2.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=instruction,
    code_executor=code_executor,
    tools=[
        PreloadMemoryTool(),
        load_memory,
        list_incidents,
        get_incident_details,
        create_incident,
        update_incident_status,
        check_service_health,
        get_github_repo_info,
        generate_architecture_diagram,
        generate_item_video,
    ],
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
)


app = App(
    root_agent=root_agent,
    name="app",
)




