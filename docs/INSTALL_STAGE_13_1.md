# Install LARP Audio on macOS arm64

1. Open `LARP-Audio-macOS-arm64.dmg`.
2. Drag **LARP Audio** to the **Applications** shortcut.
3. Open the copied application. This build is ad-hoc signed but not notarized,
   so macOS may require the standard first-open confirmation for an internal
   build.
4. Choose **Prepare speech engine** once. The pinned local timing engine is
   verified and reused; audio and script content are not uploaded.
5. Add audio and the exact original script, then choose **Process**. Results are
   stored under Documents by default.

The application bundles Python, FFmpeg, ffprobe, and runtime libraries. It does
not require Terminal, Homebrew, or a system Python. An internet connection is
required only for the initial online engine preparation; this handoff is not an
offline installer.
