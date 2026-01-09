#!/usr/bin/env python3
"""
Quick test script to verify Dropbox setup
"""

import os
import dropbox
from dropbox.files import WriteMode
from openpyxl import Workbook
import config

def test_dropbox_upload():
    """Test Dropbox upload functionality"""

    print("=" * 60)
    print("TESTING DROPBOX SETUP")
    print("=" * 60)

    # Step 1: Create a test Excel file
    print("\n1. Creating test Excel file...")
    wb = Workbook()
    ws = wb.active
    ws.title = "Test"
    ws.append(["Test", "Dropbox", "Upload"])
    ws.append(["This is", "a test", "file"])

    test_file = "test_dropbox_upload.xlsx"
    wb.save(test_file)
    print(f"   ✓ Created: {test_file}")

    # Step 2: Authenticate with Dropbox
    print("\n2. Authenticating with Dropbox...")
    try:
        token = config.GREEKS_DIFF_DROPBOX_TOKEN
        if not token:
            print(f"   ✗ ERROR: Dropbox token not configured!")
            return False

        dbx = dropbox.Dropbox(token)

        # Test authentication by getting account info
        account = dbx.users_get_current_account()
        print(f"   ✓ Authenticated as: {account.name.display_name}")
        print(f"   Email: {account.email}")

    except Exception as e:
        print(f"   ✗ ERROR: {e}")
        return False

    # Step 3: Upload to Dropbox
    print("\n3. Uploading to Dropbox...")
    try:
        file_path = "/greeks_tracker_test.xlsx"

        with open(test_file, 'rb') as f:
            dbx.files_upload(
                f.read(),
                file_path,
                mode=WriteMode.overwrite
            )

        print(f"   ✓ File uploaded to: {file_path}")

    except Exception as e:
        print(f"   ✗ ERROR: {e}")
        os.remove(test_file)
        return False

    # Step 4: Create shareable link
    print("\n4. Creating shareable link...")
    try:
        # Try to get existing link
        try:
            links = dbx.sharing_list_shared_links(path=file_path)
            if links.links:
                link_url = links.links[0].url
                print(f"   ✓ Using existing link")
            else:
                # Create new link
                link = dbx.sharing_create_shared_link_with_settings(file_path)
                link_url = link.url
                print(f"   ✓ Created new link")
        except dropbox.exceptions.ApiError as e:
            if 'shared_link_already_exists' in str(e):
                # Get the existing link
                links = dbx.sharing_list_shared_links(path=file_path)
                link_url = links.links[0].url
                print(f"   ✓ Retrieved existing link")
            else:
                raise

        # Convert to direct download link
        shareable_link = link_url.replace('?dl=0', '?dl=1')
        print(f"   Link: {shareable_link}")

    except Exception as e:
        print(f"   ✗ ERROR creating link: {e}")
        # Link creation failed, but upload succeeded
        shareable_link = f"https://www.dropbox.com/home{file_path}"

    # Step 5: Cleanup local file
    print("\n5. Cleaning up...")
    os.remove(test_file)
    print(f"   ✓ Deleted local test file")

    # Success!
    print("\n" + "=" * 60)
    print("✅ DROPBOX SETUP TEST SUCCESSFUL!")
    print("=" * 60)
    print(f"\nYour test file is now in Dropbox at:")
    print(f"{file_path}")
    print(f"\nShareable link:")
    print(f"{shareable_link}")
    print(f"\n📱 Open this link from your phone/computer to verify access!")
    print("\n" + "=" * 60)

    return True

if __name__ == '__main__':
    success = test_dropbox_upload()

    if success:
        print("\n✅ You're all set! The Greeks Difference Tracker is ready to use.")
        print("\nNext steps:")
        print("  1. Wait for market hours (9:15 AM)")
        print("  2. Run: python greeks_difference_tracker.py --monitor")
        print("  3. You'll get a Telegram message at 9:30 AM with the Dropbox link")
    else:
        print("\n❌ Setup test failed. Please check the errors above.")
