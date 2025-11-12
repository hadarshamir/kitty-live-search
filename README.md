# Kitty Live Search

Live incremental search for Kitty terminal.

## Features

- Opens small search bar at bottom of terminal
- Highlights all matches in the main window as you type
- Shows match count
- Smart color coding:
  - Red for error-related terms (error, fail, fatal, critical)
  - Orange for warnings (warn, warning, caution)
  - Yellow for everything else
- Navigate between matches with up/down arrows
- Remembers last search term
- Keeps highlights after closing (until cleared or new search)

## Installation

1. Copy `live_search.py` and `scroll_mark.py` to `~/.config/kitty/`

2. Make them executable:
   ```bash
   chmod +x ~/.config/kitty/live_search.py ~/.config/kitty/scroll_mark.py
   ```

3. Add to your `kitty.conf`:
   ```
   # Live incremental search
   map super+f launch --location=hsplit --allow-remote-control python3 ~/.config/kitty/live_search.py @active-kitty-window-id

   # Marker colors
   # Mark 1: Search results (yellow)
   mark1_foreground black
   mark1_background #f9e2af

   # Mark 2: Warnings (orange)
   mark2_foreground black
   mark2_background #fab387

   # Mark 3: Errors (red)
   mark3_foreground black
   mark3_background #f38ba8
   ```

4. Reload Kitty config or restart Kitty

## Usage

- **Cmd+F** (or your configured key) - Open search
- **Type** - Search incrementally
- **Up/Down arrows** - Navigate between matches
- **Backspace** - Delete single character
- **Option+Backspace** - Delete word backwards
- **Enter** - Close search, keep highlights
- **Esc or Ctrl+C** - Close search, clear highlights

## Requirements

- Kitty terminal with remote control enabled
- Python 3

## License

MIT
