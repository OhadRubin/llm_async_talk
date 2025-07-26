import sys
import threading
import contextvars
import datetime
import json

# Context variable to store the current prefix and color
current_prefix = contextvars.ContextVar('current_prefix', default='')
current_color = contextvars.ContextVar('current_color', default='')

# ANSI color codes
class Colors:
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    RESET = '\033[0m'

# Global lock for stdout access
_stdout_lock = threading.Lock()

class PrefixedOutput:
    """A custom stdout wrapper that prefixes each line with the current context prefix."""
    
    def __init__(self, original_stdout=None, log_file_path=None):
        self.original_stdout = original_stdout or sys.stdout
        self.buffer = ""
        self.log_file_path = log_file_path
        
    def _write_to_log(self, text: str):
        """Write text to log file as JSONL entries if log file path is set."""
        if self.log_file_path and text.strip():  # Only log non-empty lines
            try:
                import datetime
                import json
                timestamp = datetime.datetime.now().isoformat()
                prefix = current_prefix.get('')
                
                log_entry = {
                    "timestamp": timestamp,
                    "user": prefix,
                    "content": text.rstrip('\n')  # Remove trailing newline but preserve internal ones
                }
                
                # Write to log file
                with open(self.log_file_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(log_entry) + '\n')
                    f.flush()
                
                # Also add to live WebSocket queue (non-blocking)
                live_message_queue.put_nowait(log_entry)
                

                    
            except Exception as e:
                # If logging fails, don't crash the program
                pass
        
    def write(self, text: str) -> int:
        if not text:
            return 0
            
        prefix = current_prefix.get('')
        color = current_color.get('')
        
        with _stdout_lock:  # Thread-safe access to stdout
            # Buffer the text and process line by line
            self.buffer += text
            lines = self.buffer.split('\n')
            
            # Keep the last incomplete line in buffer
            if self.buffer.endswith('\n'):
                self.buffer = ""
            else:
                self.buffer = lines[-1]
                lines = lines[:-1]
            
            # Write complete lines with prefix
            for line in lines:
                if line and prefix:  # Only prefix non-empty lines when prefix is set
                    if color:
                        # Write with color to stdout
                        formatted_line = f"{color}{prefix}{Colors.RESET} | {line}\n"
                        self.original_stdout.write(formatted_line)
                        # Write without color to log file
                        self._write_to_log(f"{prefix} | {line}\n")
                    else:
                        formatted_line = f"{prefix} | {line}\n"
                        self.original_stdout.write(formatted_line)
                        self._write_to_log(formatted_line)
                elif line:
                    formatted_line = f"{line}\n"
                    self.original_stdout.write(formatted_line)
                    self._write_to_log(formatted_line)
                else:
                    self.original_stdout.write("\n")
                    self._write_to_log("\n")
            
            self.original_stdout.flush()
        
        return len(text)
    
    def flush(self):
        prefix = current_prefix.get('')
        color = current_color.get('')
        with _stdout_lock:
            # Flush any remaining buffer content
            if self.buffer:
                if prefix:
                    if color:
                        # Write with color to stdout
                        formatted_line = f"{color}{prefix}{Colors.RESET} | {self.buffer}\n"
                        self.original_stdout.write(formatted_line)
                        # Write without color to log file
                        self._write_to_log(f"{prefix} | {self.buffer}\n")
                    else:
                        formatted_line = f"{prefix} | {self.buffer}\n"
                        self.original_stdout.write(formatted_line)
                        self._write_to_log(formatted_line)
                else:
                    formatted_line = f"{self.buffer}\n"
                    self.original_stdout.write(formatted_line)
                    self._write_to_log(formatted_line)
                self.buffer = ""
            self.original_stdout.flush()
        
    def __getattr__(self, name):
        # Delegate other attributes to original stdout
        return getattr(self.original_stdout, name)

# Global prefixed output instance (will be updated with log file path in main)
_prefixed_stdout = PrefixedOutput()

# Replace sys.stdout with our prefixed version
sys.stdout = _prefixed_stdout

def set_log_file(log_file_path: str):
    """Update the global PrefixedOutput instance with a log file path."""
    global _prefixed_stdout
    _prefixed_stdout.log_file_path = log_file_path

async def run_with_prefix(func: Callable, prefix: str, color: str = '', *args, **kwargs):
    """Run an async function with prefixed output using contextvars."""
    # Set the prefix and color for this async context
    prefix_token = current_prefix.set(prefix)
    color_token = current_color.set(color)
    try:
        return await func(*args, **kwargs)
    finally:
        # Reset the context
        current_prefix.reset(prefix_token)
        current_color.reset(color_token)


def get_user_color(username: str) -> str:
    """Get a consistent color for a username based on hash."""
    color_list = [
        Colors.RED, Colors.GREEN, Colors.YELLOW, Colors.BLUE, 
        Colors.MAGENTA, Colors.CYAN, Colors.BRIGHT_RED, Colors.BRIGHT_GREEN,
        Colors.BRIGHT_YELLOW, Colors.BRIGHT_BLUE, Colors.BRIGHT_MAGENTA, Colors.BRIGHT_CYAN
    ]
    return color_list[hash(username) % len(color_list)]