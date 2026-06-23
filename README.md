Harmony is a lightweight, high-performance, terminal-based file search utility. It indexes your entire filesystem and provides a fast, TUI-driven interface to find and open files instantly.

---

## Features

- **Fast Indexing**: Uses SQLite FTS5 with trigram tokenization for lightning-fast search results, even across large filesystems.
- **Terminal Interface**: A clean, distraction free interface built with `textual` that stays out of your way.
- **Deep Search**: Indexes your system from the root, ensuring you can find any file, anywhere.
- **Cross-Platform**: Designed to work on Windows, macOS, and Linux.
- **Smart Actions**: 
    - Press `Enter` to open the selected file/application.
    - Press `Ctrl+O` to open the parent folder in your system file explorer.
- **Low Profile**: Operates silently in the background with a minimal footprint.

## Requirements

- Python 3.7+
- `textual` package

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/malinacoin/search.git