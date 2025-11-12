#!/usr/bin/env python3
"""
Live search for Kitty terminal - like iTerm2's Cmd+F
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
import select
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

def jump_to_closest_match(window_id):
    """Jump to closest match, trying up first, then down if up didn't move"""
    # Get current scroll position
    info_before = get_window_info(window_id)
    if not info_before:
        return

    scroll_before = info_before.get('scrolled_by', 0)

    # Try jumping up (prev)
    subprocess.run([
        'kitty', '@', 'kitten',
        f'--match=id:{window_id}',
        str(SCROLLMARK_FILE)
    ], capture_output=True)

    # Check if we moved
    info_after = get_window_info(window_id)
    if not info_after:
        return

    scroll_after = info_after.get('scrolled_by', 0)

    # If we didn't move, try jumping down (next)
    if scroll_before == scroll_after:
        subprocess.run([
            'kitty', '@', 'kitten',
            f'--match=id:{window_id}',
            str(SCROLLMARK_FILE),
            'next'
        ], capture_output=True)

def find_word_boundary_backward(text, pos):
    """Find the start of the word before cursor, handling snake_case and camelCase"""
    if pos == 0:
        return 0

    # Start from position before cursor
    i = pos - 1

    # Skip trailing whitespace
    while i >= 0 and text[i] in ' \t':
        i -= 1

    if i < 0:
        return 0

    # Determine word type at cursor
    start_char = text[i]

    # Move backward through the word with smart boundaries
    while i > 0:
        prev_char = text[i - 1]
        curr_char = text[i]

        # Stop at whitespace
        if prev_char in ' \t':
            break

        # Stop at snake_case boundary (underscore)
        if prev_char == '_' or curr_char == '_':
            if prev_char == '_':
                i -= 1  # Include the underscore in deletion
            break

        # Stop at camelCase boundary (lowercase to uppercase)
        if prev_char.islower() and curr_char.isupper():
            break

        # Stop at number boundary
        if prev_char.isdigit() != curr_char.isdigit():
            break

        i -= 1

    return i

def move_word_left(text, pos):
    """Move cursor left by one word (smart: snake_case and camelCase aware)"""
    if pos == 0:
        return 0

    i = pos - 1

    # Skip trailing whitespace
    while i >= 0 and text[i] in ' \t':
        i -= 1

    if i < 0:
        return 0

    # Move backward through the word with smart boundaries
    while i > 0:
        prev_char = text[i - 1]
        curr_char = text[i]

        # Stop at whitespace
        if prev_char in ' \t':
            break

        # Stop at snake_case boundary (underscore)
        if prev_char == '_' or curr_char == '_':
            break

        # Stop at camelCase boundary (lowercase to uppercase)
        if prev_char.islower() and curr_char.isupper():
            break

        # Stop at number boundary
        if prev_char.isdigit() != curr_char.isdigit():
            break

        i -= 1

    return i

def move_word_right(text, pos):
    """Move cursor right by one word (smart: snake_case and camelCase aware)"""
    if pos >= len(text):
        return len(text)

    i = pos

    # Skip leading whitespace
    while i < len(text) and text[i] in ' \t':
        i += 1

    if i >= len(text):
        return len(text)

    # Move forward through the word with smart boundaries
    while i < len(text) - 1:
        curr_char = text[i]
        next_char = text[i + 1]

        # Stop before whitespace
        if next_char in ' \t':
            i += 1
            break

        # Stop before snake_case boundary (underscore)
        if next_char == '_':
            i += 1
            break

        # Stop at camelCase boundary (lowercase to uppercase)
        if curr_char.islower() and next_char.isupper():
            i += 1
            break

        # Stop at number boundary
        if curr_char.isdigit() != next_char.isdigit():
            i += 1
            break

        i += 1

    # Move to end if we're at the last position
    if i < len(text):
        i += 1

    return i

def move_word_left_alphanum(text, pos):
    """Move cursor left by one word (non-alphanumeric boundaries)"""
    if pos == 0:
        return 0

    i = pos - 1
    # Skip non-alphanumeric
    while i >= 0 and not text[i].isalnum():
        i -= 1

    # Move to start of alphanumeric sequence
    while i >= 0 and text[i].isalnum():
        i -= 1

    return i + 1

def move_word_right_alphanum(text, pos):
    """Move cursor right by one word (non-alphanumeric boundaries)"""
    if pos >= len(text):
        return len(text)

    i = pos
    # Skip non-alphanumeric
    while i < len(text) and not text[i].isalnum():
        i += 1

    # Move to end of alphanumeric sequence
    while i < len(text) and text[i].isalnum():
        i += 1

    return i

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

def find_matches_with_positions(text, search_text, use_regex=False):
    """Find all matches and their line numbers"""
    if not search_text:
        return []

    try:
        if use_regex:
            pattern = re.compile(search_text, re.IGNORECASE)
        else:
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

def count_matches(text, search_text, use_regex=False):
    """Count how many matches exist in the text (case insensitive)"""
    if not search_text:
        return 0
    try:
        if use_regex:
            pattern = re.compile(search_text, re.IGNORECASE)
        else:
            pattern = re.compile(re.escape(search_text), re.IGNORECASE)
        return len(pattern.findall(text))
    except:
        return 0

def create_marker(window_id, text, use_regex=False):
    """Highlight text in target window with color based on search term"""
    if not text:
        remove_marker(window_id)
        return

    # In regex mode, only use word-based colors if it's a single term (no | or other regex operators)
    if use_regex and '|' in text:
        # Multiple terms in regex, always use yellow
        mark_group = '1'
    else:
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

    # Use regex or itext based on mode
    match_type = 'regex' if use_regex else 'itext'

    subprocess.run([
        'kitty', '@', 'create-marker',
        f'--match=id:{window_id}',
        match_type, mark_group, text
    ], capture_output=True)

def remove_marker(window_id):
    """Remove highlighting from target window"""
    subprocess.run([
        'kitty', '@', 'remove-marker',
        f'--match=id:{window_id}'
    ], capture_output=True)

def main():
    # Check if another search window already exists in this tab
    result = subprocess.run(['kitty', '@', 'ls'], capture_output=True)
    data = json.loads(result.stdout)

    my_window_id = int(os.environ.get('KITTY_WINDOW_ID', 0))
    search_windows = []

    for os_win in data:
        for tab in os_win['tabs']:
            if tab.get('is_focused'):
                for win in tab['windows']:
                    cmdline = ' '.join(win.get('cmdline', []))
                    if 'live_search.py' in cmdline:
                        search_windows.append(win['id'])

    # If there are multiple search windows (including us), close ourselves and focus the other
    if len(search_windows) > 1:
        for wid in search_windows:
            if wid != my_window_id:
                # Focus the other search window
                subprocess.run(['kitty', '@', 'focus-window', f'--match=id:{wid}'])
                # Close ourselves
                subprocess.run(['kitty', '@', 'close-window', f'--match=id:{my_window_id}'])
                return

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

        # Enable bracketed paste mode
        sys.stdout.write('\x1b[?2004h')
        sys.stdout.flush()

        # Load last search term
        search_text = load_last_search()
        cursor_pos = len(search_text)  # Cursor position in search_text
        use_regex = False
        auto_jump = False  # Toggle for auto-jump to matches
        should_clear_on_exit = False
        last_counter = ""  # Cache the counter to avoid recalculating on cursor movement
        cached_scrollback = None  # Cache scrollback text

        def get_prompt():
            mode_indicators = []
            if use_regex:
                mode_indicators.append("Regex")
            if auto_jump:
                mode_indicators.append("Jump")

            if mode_indicators:
                return f"Search [{'/'.join(mode_indicators)}]: "
            return "Search: "

        def redraw_prompt(update_markers=True, jump_to_match=True):
            nonlocal last_counter, cached_scrollback
            prompt = get_prompt()

            # Build the entire output at once to minimize flicker
            output = []
            output.append('\r\x1b[K')  # Clear line
            output.append(prompt)
            output.append(search_text)

            # Calculate counter if needed
            if search_text and update_markers:
                cached_scrollback = get_scrollback_text(window_id)
                total = count_matches(cached_scrollback, search_text, use_regex)
                last_counter = f" ({total})" if total > 0 else " (0)"
                output.append(last_counter)
            elif search_text and last_counter:
                output.append(last_counter)

            # Position cursor
            cursor_offset = len(prompt) + cursor_pos
            output.append(f'\r\x1b[{cursor_offset + 1}G')

            # Write everything at once
            sys.stdout.write(''.join(output))
            sys.stdout.flush()

            # Update markers after display (so UI is responsive)
            if search_text and update_markers:
                create_marker(window_id, search_text, use_regex)
                if auto_jump and jump_to_match and last_counter and int(last_counter.strip(' ()')) > 0:
                    jump_to_closest_match(window_id)

        # Display prompt with last search term
        redraw_prompt()

        # If there's a previous search, show count and create markers
        if search_text:
            # Create markers immediately
            create_marker(window_id, search_text, use_regex)

            scrollback = get_scrollback_text(window_id)
            total = count_matches(scrollback, search_text, use_regex)

            # Jump to closest match
            if total > 0:
                jump_to_closest_match(window_id)

        while True:
            # Read one character
            char = sys.stdin.read(1)

            # If this is a printable character, collect any buffered input
            if ord(char) >= 32 and ord(char) < 127:
                # Collect all immediately available characters (for paste)
                buffered = char
                while select.select([sys.stdin], [], [], 0)[0]:
                    next_char = sys.stdin.read(1)
                    if ord(next_char) >= 32 and ord(next_char) < 127:
                        buffered += next_char
                    else:
                        # Non-printable char, will be handled next iteration
                        # We can't put it back, so we lose it - but this shouldn't happen with bracketed paste
                        break

                # Insert all characters at once
                search_text = search_text[:cursor_pos] + buffered + search_text[cursor_pos:]
                cursor_pos += len(buffered)

                # Just show text instantly without expensive search
                prompt = get_prompt()
                sys.stdout.write('\r\x1b[K' + prompt + search_text)
                cursor_offset = len(prompt) + cursor_pos
                sys.stdout.write(f'\r\x1b[{cursor_offset + 1}G')
                sys.stdout.flush()
                continue

            # Handle Ctrl+C
            if char == '\x03':
                should_clear_on_exit = True
                break

            # Handle Ctrl+R - trigger search/refresh
            elif char == '\x12':
                if search_text:
                    redraw_prompt()

            # Handle Tab - toggle regex mode
            elif char == '\t':
                use_regex = not use_regex
                redraw_prompt()

            # Handle Ctrl+J - toggle auto-jump
            elif char == '\x0a':
                auto_jump = not auto_jump
                redraw_prompt(update_markers=False, jump_to_match=False)

            # Handle Enter - trigger search (if not done) and close, keeping highlights
            elif char == '\r':
                # Always trigger search before closing to ensure highlights are set
                if search_text:
                    # Do the search and show results
                    cached_scrollback = get_scrollback_text(window_id)
                    total = count_matches(cached_scrollback, search_text, use_regex)
                    create_marker(window_id, search_text, use_regex)

                    # Show the final count
                    prompt = get_prompt()
                    counter = f" ({total})" if total > 0 else " (0)"
                    sys.stdout.write('\r\x1b[K' + prompt + search_text + counter)
                    sys.stdout.flush()

                    # Brief pause so user can see the count
                    import time
                    time.sleep(0.3)

                should_clear_on_exit = False
                break


            # Handle Backspace/Delete
            elif char == '\x7f':
                if cursor_pos > 0:
                    search_text = search_text[:cursor_pos-1] + search_text[cursor_pos:]
                    cursor_pos -= 1

                    if not search_text:
                        should_clear_on_exit = True
                        remove_marker(window_id)
                    redraw_prompt()

            # Handle Escape or arrow keys
            elif char == '\x1b':
                next1 = sys.stdin.read(1)
                if next1 == '\x7f':  # Option/Cmd+Backspace (on macOS: \x1b\x7f)
                    # Smart word delete backwards
                    if cursor_pos > 0:
                        new_pos = find_word_boundary_backward(search_text, cursor_pos)
                        search_text = search_text[:new_pos] + search_text[cursor_pos:]
                        cursor_pos = new_pos

                        if not search_text:
                            should_clear_on_exit = True
                            remove_marker(window_id)
                        redraw_prompt()
                elif next1 == '[':
                    next2 = sys.stdin.read(1)
                    # Check for bracketed paste start
                    if next2 == '2':
                        rest = sys.stdin.read(3)  # Read "00~"
                        if rest == '00~':
                            # Bracketed paste mode - read until end marker
                            pasted = ""
                            while True:
                                c = sys.stdin.read(1)
                                if c == '\x1b':
                                    if sys.stdin.read(5) == '[201~':
                                        break
                                    else:
                                        pasted += c
                                else:
                                    pasted += c
                            # Insert pasted content
                            search_text = search_text[:cursor_pos] + pasted + search_text[cursor_pos:]
                            cursor_pos += len(pasted)
                            # Trigger full search after paste completes
                            redraw_prompt()
                            continue
                    if next2 == 'A':  # Up arrow - scroll to previous mark
                        if search_text:
                            # Trigger search first if needed
                            if last_counter == "":
                                redraw_prompt()
                            subprocess.run([
                                'kitty', '@', 'kitten',
                                f'--match=id:{window_id}',
                                str(SCROLLMARK_FILE)
                            ], capture_output=True)

                    elif next2 == 'B':  # Down arrow - scroll to next mark
                        if search_text:
                            # Trigger search first if needed
                            if last_counter == "":
                                redraw_prompt()
                            subprocess.run([
                                'kitty', '@', 'kitten',
                                f'--match=id:{window_id}',
                                str(SCROLLMARK_FILE),
                                'next'
                            ], capture_output=True)

                    elif next2 == 'C':  # Right arrow - move cursor right
                        if cursor_pos < len(search_text):
                            cursor_pos += 1
                            redraw_prompt(update_markers=False, jump_to_match=False)

                    elif next2 == 'D':  # Left arrow - move cursor left
                        if cursor_pos > 0:
                            cursor_pos -= 1
                            redraw_prompt(update_markers=False, jump_to_match=False)

                    elif next2 == '1':  # Modified arrow keys
                        next3 = sys.stdin.read(1)
                        next4 = sys.stdin.read(1)
                        if next3 == ';':
                            if next4 == '3':  # Alt/Option modifier - smart navigation
                                next5 = sys.stdin.read(1)
                                if next5 == 'C':  # Alt+Right
                                    cursor_pos = move_word_right(search_text, cursor_pos)
                                    redraw_prompt(update_markers=False, jump_to_match=False)
                                elif next5 == 'D':  # Alt+Left
                                    cursor_pos = move_word_left(search_text, cursor_pos)
                                    redraw_prompt(update_markers=False, jump_to_match=False)
                            elif next4 == '9':  # Cmd/Super modifier - smart navigation (same as Option)
                                next5 = sys.stdin.read(1)
                                if next5 == 'C':  # Cmd+Right
                                    cursor_pos = move_word_right(search_text, cursor_pos)
                                    redraw_prompt(update_markers=False, jump_to_match=False)
                                elif next5 == 'D':  # Cmd+Left
                                    cursor_pos = move_word_left(search_text, cursor_pos)
                                    redraw_prompt(update_markers=False, jump_to_match=False)

                else:
                    # Just ESC, clear and exit
                    should_clear_on_exit = True
                    break

        # Only clear highlights if search was cleared or cancelled
        if should_clear_on_exit:
            remove_marker(window_id)
            search_text = ""  # Clear the search text

        # Save search term (empty or not)
        save_last_search(search_text)

        sys.stdout.write('\r\n')

    finally:
        # Disable bracketed paste mode
        sys.stdout.write('\x1b[?2004l')
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

if __name__ == '__main__':
    main()
