# LARP Audio

LARP Audio removes excessive pauses from AI-generated voiceovers, synchronizes subtitles to your exact script and exports a clean WAV file with a ready-to-use SRT.

## Features

- **Hard Comma Boundaries:** Mandatory subtitle splits at every script comma, guaranteeing rhythmic readability.
- **Sub-Millisecond Sync:** Deep acoustic alignment ensures exact subtitle timing down to the sample level.
- **Syntax-Aware Chunking:** Subtitles break naturally along semantic phrases.
- **Lossless Export:** Audio is processed and spliced losslessly without generation degradation.
- **Native Performance:** Hardware-accelerated rendering utilizing native OS toolkits for maximum speed.
- **SRT & Preview Unity:** What you see in the real-time preview is exactly what you get in the SRT file.

## Output Files

LARP Audio generates:
- A clean, spliced `.wav` file with unnecessary AI pauses removed, perfectly matching the original pacing.
- A synchronized `.srt` subtitle file.

## Privacy

**100% Local Processing:** Your scripts and voiceovers never leave your machine. LARP Audio downloads its acoustic models once and performs all alignment, generation, and processing entirely on your local hardware. Complete privacy. Complete control.

## Installation

### macOS (Apple Silicon)
1. Download `LARP-Audio-macOS-arm64.dmg` from the Releases page.
2. Open the `.dmg` file.
3. Drag `LARP Audio.app` to your Applications folder.

### Windows (x64)
1. Download `LARP-Audio-Windows-x64-Setup.exe` from the Releases page.
2. Run the installer and follow the instructions.

## Landing Page & GitHub Pages Setup

The project includes a static landing page located in the `landing/` directory.

To deploy it via GitHub Pages:
1. Go to your repository settings on GitHub.
2. Navigate to **Pages** on the left sidebar.
3. Under **Build and deployment**, select **Deploy from a branch**.
4. Select the `main` branch and the `/landing` folder.
5. Click **Save**.
6. GitHub will automatically deploy the site and provide a URL.
