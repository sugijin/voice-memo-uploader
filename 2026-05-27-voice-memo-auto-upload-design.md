# Voice Memo Auto-Upload to Google Drive — Design Spec

**Date:** 2026-05-27
**Status:** Approved

---

## Overview

A Python script (`voice_uploader.py`) runs on the Mac via `launchd` once daily. It scans the iCloud-synced Voice Memos folder, uploads any new `.m4a` recordings to the existing `DailyLogs` Google Drive folder, then deletes each file locally (which syncs the deletion back to the iPhone via iCloud, removing it from Voice Memos there too).

This feeds directly into the existing distillation engine, which already reads from `DailyLogs` on its scheduled runs.

---

## Architecture

```
iPhone Voice Memos
      │  iCloud sync
      ▼
~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/*.m4a
      │  voice_uploader.py (runs daily at 2 AM via launchd)
      ▼
Google Drive: DailyLogs folder (DAILYLOGS_FOLDER_ID)
      │  upload verified ✓
      ▼
Delete local file → iCloud syncs deletion → removed from iPhone
      │
      ▼
~/.jin-pa/voice_upload_state.json  ← log updated
```

---

## Components

### 1. `voice_uploader.py`

**Location:**
```
~/Library/CloudStorage/GoogleDrive-sugijin@gmail.com/My Drive/System/
Jin Personal Assistant System/engine/voice_uploader/voice_uploader.py
```

**Responsibilities:**
- Scan `Recordings/` folder for `.m4a` files
- Load `~/.jin-pa/voice_upload_state.json` to get already-uploaded filenames
- For each new file:
  1. Upload to Google Drive `DailyLogs` folder
  2. Verify upload by confirming file ID is returned
  3. Delete the local `.m4a` file
  4. Add filename to state log
- Save updated state log
- Write structured log output to `~/.jin-pa/voice_uploader.log`

**Error handling:**
- If upload fails: skip file, log the error, do NOT delete
- If deletion fails after successful upload: log a warning, mark as uploaded in state (won't retry upload), user can delete manually
- If `Recordings/` folder is inaccessible: log error and exit cleanly

### 2. Google Drive Auth

- **Scope:** `https://www.googleapis.com/auth/drive.file`
  - Allows creating/uploading files created by the app; does not grant broad Drive access
- **Token file:** `~/.jin-pa/drive_upload_token.json` (separate from existing read-only token)
- **Credentials:** Reuses existing `credentials.json` from the engine — no new OAuth app needed
- First run requires a one-time browser auth; subsequent runs refresh automatically

### 3. State File

**Location:** `~/.jin-pa/voice_upload_state.json`

**Schema:**
```json
{
  "uploaded_filenames": [
    "Recording 2026-05-27 at 09.15.m4a",
    "Recording 2026-05-26 at 22.03.m4a"
  ],
  "last_run": "2026-05-27T02:00:01"
}
```

Deduplication key is **filename** — Voice Memos generates unique timestamped names, so collisions are not a concern.

### 4. launchd Plist

**Location:** `~/Library/LaunchAgents/com.jin.voice-uploader.plist`

**Behaviour:**
- Runs daily at **2:00 AM**
- If Mac is asleep at 2 AM, runs on next wake
- `RunAtLoad: true` — also runs once immediately when first loaded (for initial catchup)
- Stdout/stderr → `~/.jin-pa/voice_uploader.log`

---

## Upload Flow (per file)

```
1. upload(file_path)  →  returns file_id  (abort if None/error)
2. verify file_id is non-empty
3. os.remove(file_path)               (abort log entry if this raises)
4. state["uploaded_filenames"].append(filename)
5. state["last_run"] = now.isoformat()
6. save(state)
```

Safety invariant: **never delete without a confirmed upload**.

---

## Prerequisites & Setup

### iPhone
1. Settings → [Your Name] → iCloud → Show All → **Voice Memos: ON**

### Mac
1. System Settings → [Your Name] → iCloud → Show All → **Voice Memos: ON**
2. System Settings → Privacy & Security → Full Disk Access → add **Terminal.app**
3. One-time: run `voice_uploader.py` manually to complete browser-based Google OAuth
4. Load the launchd agent: `launchctl load ~/Library/LaunchAgents/com.jin.voice-uploader.plist`

---

## File Structure

```
engine/
├── distillation/          ← existing (unchanged)
│   ├── drive.py
│   ├── engine.py
│   └── ...
└── voice_uploader/        ← new
    └── voice_uploader.py
```

`voice_uploader.py` imports `config.py` from `distillation/` for `DAILYLOGS_FOLDER_ID` and `DRIVE_CREDENTIALS_FILE`.

---

## Out of Scope

- Transcription or processing of uploaded files (handled by existing distillation engine)
- Upload from non-Voice Memos apps
- Real-time / push-based upload (daily batch is sufficient)
