import json
import logging
import os
from datetime import datetime
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

DAILYLOGS_FOLDER_ID = "1Q8YPDT2_fJ1St22aQBbaTg6fR-J4-TuF"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

BASE_DIR = Path.home() / ".jin-pa"
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
UPLOAD_TOKEN_FILE = BASE_DIR / "drive_upload_token.json"
STATE_FILE = BASE_DIR / "voice_upload_state.json"
LOG_FILE = BASE_DIR / "voice_uploader.log"
VOICE_MEMOS_DIR = (
    Path.home()
    / "Library"
    / "Group Containers"
    / "group.com.apple.VoiceMemos.shared"
    / "Recordings"
)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


def _get_service():
    creds = None

    if UPLOAD_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(UPLOAD_TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(UPLOAD_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def _load_state() -> dict:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        return {"uploaded_filenames": [], "last_run": None}
    with open(STATE_FILE) as f:
        return json.load(f)


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _upload_file(service, file_path: Path):
    media = MediaFileUpload(str(file_path), mimetype="audio/mp4", resumable=False)
    metadata = {"name": file_path.name, "parents": [DAILYLOGS_FOLDER_ID]}
    result = (
        service.files()
        .create(body=metadata, media_body=media, fields="id")
        .execute()
    )
    return result.get("id")


def run():
    log.info("=== voice_uploader starting ===")

    try:
        service = _get_service()
    except Exception as e:
        log.error(f"Google Drive auth failed: {e}")
        return

    if not VOICE_MEMOS_DIR.exists():
        log.info(f"Voice Memos folder not yet synced ({VOICE_MEMOS_DIR}) — nothing to upload.")
        state = _load_state()
        state["last_run"] = datetime.now().isoformat(timespec="seconds")
        _save_state(state)
        return

    state = _load_state()
    uploaded = set(state.get("uploaded_filenames", []))

    m4a_files = sorted(VOICE_MEMOS_DIR.glob("*.m4a"))
    new_files = [f for f in m4a_files if f.name not in uploaded]

    log.info(f"Found {len(m4a_files)} total, {len(new_files)} new to upload.")

    success_count = 0
    for file_path in new_files:
        log.info(f"Uploading: {file_path.name}")
        try:
            file_id = _upload_file(service, file_path)
        except Exception as e:
            log.error(f"Upload failed for {file_path.name}: {e}")
            continue

        if not file_id:
            log.error(f"Upload returned no file ID for {file_path.name} — skipping delete.")
            continue

        log.info(f"Uploaded {file_path.name} → Drive ID {file_id}")

        try:
            os.remove(file_path)
            log.info(f"Deleted local file: {file_path.name}")
        except Exception as e:
            log.warning(f"Delete failed for {file_path.name}: {e} — marking uploaded to avoid retry.")

        uploaded.add(file_path.name)
        state["uploaded_filenames"] = list(uploaded)
        _save_state(state)
        success_count += 1

    state["last_run"] = datetime.now().isoformat(timespec="seconds")
    _save_state(state)
    log.info(f"Done. {success_count}/{len(new_files)} files uploaded and deleted.")


if __name__ == "__main__":
    run()
