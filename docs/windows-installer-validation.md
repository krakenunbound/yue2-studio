# Windows installer validation — September 10, 2026

Release: `release/YuE2 Studio_0.3.2_x64-setup.exe` (51,073,470 bytes).

SHA256: `6802E532EA962A04E2E057C35F3C893B34327BF53F729C9145B22E651D29DB0A`.

## Package

- Tauri NSIS x64 installer with generated cyan/violet sidebar and header artwork.
- Per-user installation, selectable writable destination, Start menu shortcut and optional desktop shortcut.
- Clean standalone CPython 3.11 with service dependencies, FFmpeg, and application support files. No Node.js or system Python required by the installed application.
- Creates model, library, logs, downloads, recovery and settings directories. Large model weights and feature runtimes are selected separately in Models. Fresh installations open Models immediately.
- The release remains unsigned. WebView2 is downloaded during setup only if it is missing.

## Verification

Used the actual setup wizard through Windows Computer Use, chose the isolated `F:\YuE2 Installer Test` directory, installed, and launched the installed application through the finish-page option. Inspected welcome/header/finish artwork and the installed Models screen. Opened Keys and verified the Google Gemini key field was empty and cloud writing disabled.

The staged payload and initial installed files passed privacy scans for forbidden user-data paths and the exact local Gemini key. The key was never printed or stored in reports. No user outputs or API-key vault were packaged.

Tested the final package's upgrade and launch. Installed executable matches the final build except for Tauri's expected three-byte NSIS bundle marker. Bundled `tools/ffmpeg.exe -version` passed. Relocated standalone Python created and ran a fresh private virtual environment successfully.

Ran install/uninstall preservation tests using synthetic files (not real keys or songs). Both installer and uninstaller exited 0. Uninstaller removed application files and preserved library, model, runtime and settings test data byte-for-byte. A preliminary invalid library fixture was cleaned up by the application's existing orphan-song cleanup when the app launched; the uninstall preservation test was then repeated with fixtures created immediately before uninstall and passed.

The NSIS build completed successfully. Its first release-copy attempt was blocked by the running test wizard's file lock; after closing the wizard the completed package was copied and its SHA256 verified. No installer/app processes were left running. Automatic approval review blocked deletion of the remaining temporary test folders; those folders were left in place.

This is a separate-directory installation test on the current Windows machine, not a clean Windows virtual-machine test. No full model downloads or GPU generation were repeated as part of installer verification.
