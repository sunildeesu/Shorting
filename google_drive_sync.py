"""
Google Drive Sync - copies Excel reports to Google Drive for Desktop synced folder.
Requires Google Drive for Desktop installed (creates a local synced folder).
"""

import os
import shutil
import logging

logger = logging.getLogger(__name__)


def sync_to_drive(local_path: str, subfolder: str) -> str | None:
    """
    Copy a file to Google Drive synced folder.

    Args:
        local_path: Path to the local file to sync
        subfolder: Subfolder name within the Drive sync path (e.g. 'EODReports')

    Returns:
        Destination path on success, None on failure
    """
    from config import ENABLE_GOOGLE_DRIVE_SYNC, GOOGLE_DRIVE_SYNC_PATH

    if not ENABLE_GOOGLE_DRIVE_SYNC or not GOOGLE_DRIVE_SYNC_PATH:
        return None

    try:
        dest_dir = os.path.join(GOOGLE_DRIVE_SYNC_PATH, subfolder)
        os.makedirs(dest_dir, exist_ok=True)

        dest_path = os.path.join(dest_dir, os.path.basename(local_path))
        shutil.copy2(local_path, dest_path)

        logger.info(f"Synced to Google Drive: {dest_path}")
        return dest_path

    except Exception as e:
        logger.warning(f"Google Drive sync failed for {local_path}: {e}")
        return None
