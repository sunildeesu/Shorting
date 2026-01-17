#!/usr/bin/env python3
"""
Check Dropbox connection and token validity
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config

def check_dropbox_connection():
    """Check if Dropbox token is valid and connection works"""
    print("=" * 60)
    print("DROPBOX CONNECTION TEST")
    print("=" * 60)

    # Check if Dropbox upload is enabled
    print(f"\n1. Configuration Check:")
    print(f"   SECTOR_ENABLE_DROPBOX: {config.SECTOR_ENABLE_DROPBOX}")
    print(f"   SECTOR_DROPBOX_FOLDER: {config.SECTOR_DROPBOX_FOLDER}")

    if not config.SECTOR_DROPBOX_TOKEN:
        print(f"   SECTOR_DROPBOX_TOKEN: NOT SET")
        print("\n❌ FAILED: No Dropbox token configured")
        return False
    else:
        token_preview = config.SECTOR_DROPBOX_TOKEN[:20] + "..." + config.SECTOR_DROPBOX_TOKEN[-20:]
        print(f"   SECTOR_DROPBOX_TOKEN: {token_preview}")

    # Try to import dropbox
    print(f"\n2. Library Check:")
    try:
        import dropbox
        from dropbox.files import WriteMode
        print("   ✓ Dropbox library is installed")
    except ImportError as e:
        print(f"   ❌ Dropbox library not installed: {e}")
        print("   Install: pip install dropbox")
        return False

    # Try to authenticate
    print(f"\n3. Authentication Test:")
    try:
        dbx = dropbox.Dropbox(config.SECTOR_DROPBOX_TOKEN)
        print("   ✓ Dropbox client created")
    except Exception as e:
        print(f"   ❌ Failed to create Dropbox client: {e}")
        return False

    # Try to get account info
    print(f"\n4. Account Info Test:")
    try:
        account = dbx.users_get_current_account()
        print(f"   ✓ Connected to Dropbox")
        print(f"   Account name: {account.name.display_name}")
        print(f"   Email: {account.email}")
        print(f"   Account ID: {account.account_id}")
    except dropbox.exceptions.AuthError as e:
        print(f"   ❌ Authentication failed: {e}")
        print("\n   This typically means:")
        print("   - Token is expired")
        print("   - Token is invalid")
        print("   - Token was revoked")
        print("\n   To fix:")
        print("   1. Go to https://www.dropbox.com/developers/apps")
        print("   2. Select your app (or create a new one)")
        print("   3. Generate a new access token")
        print("   4. Update GREEKS_DIFF_DROPBOX_TOKEN in .env file")
        return False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

    # Try to check if folder exists
    print(f"\n5. Folder Access Test:")
    folder_path = config.SECTOR_DROPBOX_FOLDER
    try:
        # List folder contents (or check if it exists)
        try:
            result = dbx.files_list_folder(folder_path)
            print(f"   ✓ Folder '{folder_path}' exists")
            print(f"   Files in folder: {len(result.entries)}")

            # Show some files
            if result.entries:
                print(f"   Recent files:")
                for entry in result.entries[:3]:
                    print(f"     - {entry.name}")
        except dropbox.exceptions.ApiError as e:
            if e.error.is_path() and e.error.get_path().is_not_found():
                print(f"   ℹ Folder '{folder_path}' doesn't exist yet (will be created on first upload)")
            else:
                raise
    except Exception as e:
        print(f"   ⚠ Warning: Could not check folder: {e}")
        print(f"   (This is OK - folder will be created on first upload)")

    # Try to create a test file
    print(f"\n6. Upload Test:")
    try:
        test_content = b"Test file from sector EOD report system"
        test_filename = f"{folder_path}/test_connection.txt"

        dbx.files_upload(
            test_content,
            test_filename,
            mode=WriteMode.overwrite
        )
        print(f"   ✓ Successfully uploaded test file: {test_filename}")

        # Try to create shareable link
        try:
            links = dbx.sharing_list_shared_links(path=test_filename)
            if links.links:
                link_url = links.links[0].url
                print(f"   ✓ Test file link: {link_url}")
            else:
                link = dbx.sharing_create_shared_link_with_settings(test_filename)
                link_url = link.url
                print(f"   ✓ Created shareable link: {link_url}")
        except Exception as e:
            print(f"   ⚠ Warning: Could not create shareable link: {e}")

        # Clean up test file
        try:
            dbx.files_delete_v2(test_filename)
            print(f"   ✓ Cleaned up test file")
        except:
            pass

    except dropbox.exceptions.AuthError as e:
        print(f"   ❌ Upload failed - Authentication error: {e}")
        return False
    except Exception as e:
        print(f"   ❌ Upload failed: {e}")
        return False

    print("\n" + "=" * 60)
    print("✓ DROPBOX CONNECTION TEST PASSED")
    print("=" * 60)
    print("\nYour Dropbox connection is working correctly!")
    print(f"Sector reports will be uploaded to: {folder_path}")
    return True

if __name__ == "__main__":
    success = check_dropbox_connection()
    sys.exit(0 if success else 1)
