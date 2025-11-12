#!/usr/bin/env python3
"""
Live search for Kitty terminal
Opens small search bar at bottom, highlights matches in main window
Shows current match position (X/Y) and total count
Keeps highlights after closing (until cleared or new search)
Remembers last search term
"""
import sys
import os
import json
import subprocess
import termios
import tty
import re
from pathlib import Path

# Path to scroll_mark kitten
SCROLLMARK_FILE = Path(os.path.expanduser("~/.config/kitty")) / "scroll_mark.py"
CACHE_FILE = Path(os.path.expanduser("~/.config/kitty")) / ".last_search"
POSITION_CACHE = Path(os.path.expanduser("~/.config/kitty")) / ".search_position"

def get_window_id():
    """Get the window ID to search in"""
    if len(sys.argv) >= 2 and sys.argv[1].isdigit():
        return int(sys.argv[1])

    if os.environ.get('KITTY_WINDOW_ID'):
        return int(os.environ['KITTY_WINDOW_ID'])

    # Fallback: find focused window
    result = subprocess.run(['kitty', '@', 'ls'], capture_output=True)
    data = json.loads(result.stdout)
    for os_win in data:
        for tab in os_win['tabs']:
            for win in tab['windows']:
                if win.get('is_focused'):
                    return win['id']
    return None

def shrink_self():
    """Make this window tiny (1 line)"""
    result = subprocess.run(['kitty', '@', 'ls'], capture_output=True)
    data = json.loads(result.stdout)

    for os_win in data:
        for tab in os_win['tabs']:
            for win in tab['windows']:
                if win.get('is_self'):
                    lines = win.get('lines', 50)
                    shrink = -(lines - 1)
                    subprocess.run([
                        'kitty', '@', 'resize-window',
                        '--self', '--axis=vertical',
                        '--increment', str(shrink)
                    ], capture_output=True)
                    return

def get_window_info(window_id):
    """Get window info including scroll position"""
    result = subprocess.run(['kitty', '@', 'ls'], capture_output=True)
    data = json.loads(result.stdout)

    for os_win in data:
        for tab in os_win['tabs']:
            for win in tab['windows']:
                if win['id'] == window_id:
                    return win
    return None

def load_last_search():
    """Load the last search term from cache"""
    try:
        if CACHE_FILE.exists():
            return CACHE_FILE.read_text().strip()
    except:
        pass
    return ""

def save_last_search(text):
    """Save the last search term to cache"""
    try:
        CACHE_FILE.write_text(text)
        # Reset position when search term changes
        if text:
            save_position(0)
        else:
            POSITION_CACHE.unlink(missing_ok=True)
    except:
        pass

def save_position(pos):
    """Save the current match position"""
    try:
        POSITION_CACHE.write_text(str(pos))
    except:
        pass

def get_scrollback_text(window_id):
    """Get the scrollback text from the target window"""
    result = subprocess.run([
        'kitty', '@', 'get-text',
        f'--match=id:{window_id}',
        '--extent=all'
    ], capture_output=True, text=True)
    return result.stdout

def find_matches_with_positions(text, search_text):
    """Find all matches and their line numbers"""
    if not search_text:
        return []

    try:
        pattern = re.compile(re.escape(search_text), re.IGNORECASE)
        matches = []
        lines = text.split('\n')

        for line_num, line in enumerate(lines, 1):
            for match in pattern.finditer(line):
                matches.append(line_num)

        return matches
    except:
        return []

def find_current_match(matches, window_info):
    """Find which match is currently visible based on scroll position"""
    if not matches or not window_info:
        return 0

    # Get the current scroll position (top line visible)
    # The scrolled_by field tells us how many lines we've scrolled back
    scrolled_by = window_info.get('scrolled_by', 0)
    lines = window_info.get('lines', 0)

    # Calculate the current viewport top line
    # Total lines - visible lines - scrolled_by gives us the top visible line
    # This is approximate since we don't have exact line count

    # For now, find the first match that's likely visible
    # This is a simplified approach - ideally we'd get exact cursor/viewport position
    if scrolled_by == 0:
        # At the bottom, return last match
        return len(matches)

    # Return first match (simplified - proper implementation would need cursor position)
    return 1

def count_matches(text, search_text):
    """Count how many matches exist in the text (case insensitive)"""
    if not search_text:
        return 0
    try:
        pattern = re.compile(re.escape(search_text), re.IGNORECASE)
        return len(pattern.findall(text))
    except:
        return 0

def create_marker(window_id, text):
    """Highlight text in target window with color based on search term"""
    if not text:
        remove_marker(window_id)
        return

    # Determine marker group based on search term
    text_lower = text.lower()

    # Check if it's an error-related term (use mark3 - red)
    if any(word in text_lower for word in ['error', 'fail', 'failed', 'fatal', 'critical']):
        mark_group = '3'
    # Check if it's a warning-related term (use mark2 - orange)
    elif any(word in text_lower for word in ['warn', 'warning', 'caution']):
        mark_group = '2'
    # Default to mark1 (yellow)
    else:
        mark_group = '1'

    subprocess.run([
        'kitty', '@', 'create-marker',
        f'--match=id:{window_id}',
        'itext', mark_group, text
    ], capture_output=True)

def remove_marker(window_id):
    """Remove highlighting from target window"""
    subprocess.run([
        'kitty', '@', 'remove-marker',
        f'--match=id:{window_id}'
    ], capture_output=True)

def main():
    window_id = get_window_id()
    if not window_id:
        print("Error: Could not find window ID", file=sys.stderr)
        return

    # Make ourselves small
    shrink_self()

    # Setup raw terminal mode
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    try:
        tty.setraw(fd)

        # Load last search term
        search_text = load_last_search()
        prompt = "Search: "
        should_clear_on_exit = False

        # Display prompt with last search term
        sys.stdout.write(prompt + search_text)
        sys.stdout.flush()

        # If there's a previous search, show count and create markers
        if search_text:
            # Create markers immediately
            create_marker(window_id, search_text)

            scrollback = get_scrollback_text(window_id)
            total = count_matches(scrollback, search_text)
            counter = f" ({total})" if total > 0 else " (0)"

            sys.stdout.write(counter)
            sys.stdout.flush()

        while True:
            # Read one character
            char = sys.stdin.read(1)

            # Handle Ctrl+C
            if char == '\x03':
                should_clear_on_exit = True
                break

            # Handle Enter - close search but KEEP highlights
            elif char == '\r' or char == '\n':
                should_clear_on_exit = False
                break

            # Handle Backspace/Delete
            elif char in ('\x7f', '\x08'):
                if search_text:
                    search_text = search_text[:-1]

                    # Get fresh scrollback and count
                    if search_text:
                        scrollback = get_scrollback_text(window_id)
                        total = count_matches(scrollback, search_text)
                        counter = f" ({total})" if total > 0 else " (0)"
                    else:
                        counter = ""

                    # Redraw line
                    sys.stdout.write('\r\x1b[K' + prompt + search_text + counter)
                    sys.stdout.flush()
                    create_marker(window_id, search_text)

                    # If search is cleared, mark for clearing on exit
                    if not search_text:
                        should_clear_on_exit = True

            # Handle Escape or arrow keys
            elif char == '\x1b':
                next1 = sys.stdin.read(1)
                if next1 == '[':
                    next2 = sys.stdin.read(1)
                    if next2 == 'A':  # Up arrow - scroll to previous mark
                        if search_text:
                            subprocess.run([
                                'kitty', '@', 'kitten',
                                f'--match=id:{window_id}',
                                str(SCROLLMARK_FILE)
                            ], capture_output=True)

                    elif next2 == 'B':  # Down arrow - scroll to next mark
                        if search_text:
                            subprocess.run([
                                'kitty', '@', 'kitten',
                                f'--match=id:{window_id}',
                                str(SCROLLMARK_FILE),
                                'next'
                            ], capture_output=True)


                elif next1 == '\x7f':  # Option+Backspace (on macOS: \x1b\x7f)
                    # Delete word backwards
                    if search_text:
                        # Find last space and delete from there
                        last_space = search_text.rfind(' ')
                        if last_space != -1:
                            search_text = search_text[:last_space]
                        else:
                            search_text = ""

                        # Get fresh scrollback and count
                        if search_text:
                            scrollback = get_scrollback_text(window_id)
                            total = count_matches(scrollback, search_text)
                            counter = f" ({total})" if total > 0 else " (0)"
                        else:
                            counter = ""
                            should_clear_on_exit = True

                        # Redraw line
                        sys.stdout.write('\r\x1b[K' + prompt + search_text + counter)
                        sys.stdout.flush()
                        create_marker(window_id, search_text)
                else:
                    # Just ESC, clear and exit
                    should_clear_on_exit = True
                    break

            # Regular printable character
            elif ord(char) >= 32 and ord(char) < 127:
                search_text += char

                # Get scrollback and count matches
                scrollback = get_scrollback_text(window_id)
                total = count_matches(scrollback, search_text)
                counter = f" ({total})" if total > 0 else " (0)"

                # Redraw with counter
                sys.stdout.write('\r\x1b[K' + prompt + search_text + counter)
                sys.stdout.flush()
                create_marker(window_id, search_text)

        # Save search term (empty or not)
        save_last_search(search_text)

        # Only clear highlights if search was cleared or cancelled
        if should_clear_on_exit:
            remove_marker(window_id)

        sys.stdout.write('\r\n')

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

if __name__ == '__main__':
    main()
