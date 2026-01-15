#!/usr/bin/env python3
"""
Quick test script to verify Google Drive setup
"""

import os
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.service_account import Credentials
from openpyxl import Workbook
import config

def test_google_drive_upload():
    """Test Google Drive upload functionality"""

    print("=" * 60)
    print("TESTING GOOGLE DRIVE SETUP")
    print("=" * 60)

    # Step 1: Create a test Excel file
    print("\n1. Creating test Excel file...")
    wb = Workbook()
    ws = wb.active
    ws.title = "Test"
    ws.append(["Test", "Google Drive", "Upload"])
    ws.append(["This is", "a test", "file"])

    test_file = "test_upload.xlsx"
    wb.save(test_file)
    print(f"   ✓ Created: {test_file}")

    # Step 2: Authenticate with Google Drive
    print("\n2. Authenticating with Google Drive...")
    try:
        credentials_path = config.GREEKS_DIFF_GOOGLE_CREDENTIALS_PATH
        print(f"   Using credentials: {credentials_path}")

        if not os.path.exists(credentials_path):
            print(f"   ✗ ERROR: Credentials file not found!")
            return False

        creds = Credentials.from_service_account_file(
            credentials_path,
            scopes=['https://www.googleapis.com/auth/drive.file']
        )
        service = build('drive', 'v3', credentials=creds)
        print(f"   ✓ Authentication successful")
    except Exception as e:
        print(f"   ✗ ERROR: {e}")
        return False

    # Step 3: Upload to Google Drive
    print("\n3. Uploading to Google Drive...")
    try:
        folder_id = config.GREEKS_DIFF_GOOGLE_DRIVE_FOLDER_ID
        print(f"   Target folder ID: {folder_id}")

        file_metadata = {'name': 'test_greeks_tracker.xlsx'}
        if folder_id:
            file_metadata['parents'] = [folder_id]

        media = MediaFileUpload(
            test_file,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True
        ).execute()

        file_id = file['id']
        print(f"   ✓ File uploaded successfully")
        print(f"   File ID: {file_id}")

        # Make it publicly accessible
        service.permissions().create(
            fileId=file_id,
            body={'type': 'anyone', 'role': 'reader'},
            supportsAllDrives=True
        ).execute()
        print(f"   ✓ Set public permissions")

    except Exception as e:
        print(f"   ✗ ERROR: {e}")
        os.remove(test_file)
        return False

    # Step 4: Generate shareable link
    print("\n4. Generating shareable link...")
    shareable_link = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
    print(f"   ✓ Link: {shareable_link}")

    # Step 5: Cleanup
    print("\n5. Cleaning up...")
    os.remove(test_file)
    print(f"   ✓ Deleted local test file")

    # Success!
    print("\n" + "=" * 60)
    print("✅ GOOGLE DRIVE SETUP TEST SUCCESSFUL!")
    print("=" * 60)
    print(f"\nYour test file is now in Google Drive:")
    print(f"{shareable_link}")
    print(f"\n📱 Open this link from your phone/computer to verify access!")
    print("\n" + "=" * 60)

    return True

if __name__ == '__main__':
    success = test_google_drive_upload()

    if success:
        print("\n✅ You're all set! The Greeks Difference Tracker is ready to use.")
        print("\nNext steps:")
        print("  1. Wait for market hours (9:15 AM)")
        print("  2. Run: python greeks_difference_tracker.py --monitor")
        print("  3. You'll get a Telegram message at 9:30 AM with the cloud link")
    else:
        print("\n❌ Setup test failed. Please check the errors above.")
