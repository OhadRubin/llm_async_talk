import argparse
import asyncio

import sys
from dataclasses import dataclass
from chains.msg_chains.oai_msg_chain_async import (
    OpenAIAsyncMessageChain as OpenAIMessageChain,
)
from chains.mcp_utils import (
    Configuration,
    Server,
    create_tool_functions,
)
import os
import json

import asyncio
import sys
import io
import threading
from contextlib import redirect_stdout, contextmanager
from typing import Callable, Any
import functools
import contextvars

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
                
                with open(self.log_file_path, 'a', encoding='utf-8') as f:
                    # Split text into lines and create JSON entry for each non-empty line
                    lines = text.split('\n')
                    for line in lines:
                        if line.strip():  # Only log non-empty lines
                            log_entry = {
                                "timestamp": timestamp,
                                "user": prefix,
                                "content": line.strip()
                            }
                            f.write(json.dumps(log_entry) + '\n')
                    f.flush()
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



@dataclass
class ChatSessionConfig:
    """Configuration for chat session."""

    enable_mcp: bool
    api_key: str
    model_name: str = "google/gemini-flash-1.5"
    base_url: str = "https://openrouter.ai/api/v1"
    initial_message: str | None = None
    constant_msg: str | None = None

async def cleanup_servers(servers: list[Server]) -> None:
    """Clean up all servers properly."""
    for server in reversed(servers):
        try:
            await server.cleanup()
        except Exception as e:
            print(f"Warning during final cleanup: {e}")


async def initialize_servers(servers: list[Server]) -> bool:
    for server in servers:
        try:
            await server.initialize()
        except Exception as e:
            print(f"Failed to initialize server: {e}")
            await cleanup_servers(servers)
            return False
    return True


async def handle_interactive_session(
    chain: OpenAIMessageChain, initial_message: str | None = None, constant_msg: str | None = None
) -> OpenAIMessageChain:
    # Send initial message if provided
    if initial_message:
        print(f"You: {initial_message}")
        chain = await chain.user(initial_message).generate_bot()
        print(f"Assistant: {chain.last_response}")

    print("Chat session started. Type 'quit' or 'exit' to end.")

    while True:
        try:
            if constant_msg is not None:
                user_input = constant_msg
            else:
                user_input = input("You: ").strip()
                if user_input.lower() in ["quit", "exit"]:
                    print("\nExiting...")
                    break

            if not user_input:
                continue

            # Use the new async-aware method
            chain = await chain.user(user_input).generate_bot()
            print(f"Assistant: {chain.last_response}")

        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"Error during interaction: {e}")
            continue

    return chain

def create_run_chat_session(username, interest):
    async def run_chat_session(config: ChatSessionConfig) -> None:
        """Main chat session handler using functional paradigm.

        Args:
            config: Chat session configuration
        """
        # Create unique servers for this session to avoid conflicts
        servers = []
        if config.enable_mcp:  # Only if MCP is enabled
            server_config = {
                "mcpServers": {
                    f"chatroom": {
                        "command": "python",
                        "args": [
                            "/Users/ohadr/llm_async_talk/mcp_interface.py",
                        ],
                    },
                }
            }
            servers = [
                Server(name, srv_config)
                for name, srv_config in server_config["mcpServers"].items()
            ]
        
        try:
            # Initialize servers
            if servers and not await initialize_servers(servers):
                return

            # Create tool functions and schemas
            tool_schemas, tool_mapping = await create_tool_functions(servers)

            # Initialize the chain
            chain = (
                OpenAIMessageChain(
                    model_name=config.model_name,
                    base_url=config.base_url,
                    verbose=True,
                )
                .with_tools(tool_schemas, tool_mapping)
                
                .system(
f"""Let's login and start speaking with our friends in the chatroom, your username is {username}.
You are interested in {interest}.
Keep your messages concise. Send a message saying Hi.
Just use the login tool.
One of the people in the chat room is a murderer. Your goal is to find him.
When you are given the instruction "Login" by the user, continue speaking until the user stops you."""
                )
            )

            # Handle interactive session with optional initial message
            chain = await handle_interactive_session(chain, config.initial_message, config.constant_msg)

        finally:
            await cleanup_servers(servers)
    return run_chat_session

import pathlib
import datetime

def main() -> None:
    """Initialize and run the chat session."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="MCP Client with OpenAI Message Chain")
    parser.add_argument(
        "--model",
        # default="moonshotai/kimi-k2",
        default="anthropic/claude-sonnet-4",
        # default="gpt-4.1-nano",
        help="Model name to use (default: google/gemini-flash-1.5)",
    )
    parser.add_argument(
        "--base-url",
        default="https://openrouter.ai/api/v1",
        # default=None,
        help="API base URL (default: https://openrouter.ai/api/v1)",
    )
    parser.add_argument(
        "--msg",
        default="Please login to the chatroom.",
        help="An optional first message to send to the assistant",
    )
    parser.add_argument(
        "--exp-dir",
        default="experiment_configs/exp1",
        help="The directory containing the experiment configuration",
    )
    parser.add_argument(
        "--constant-msg",
        default="Continue talking with the people in the chat, remember that your goal is to find the murderer.",
        help="An optional constant message to send to the assistant",
    )
    parser.add_argument(
        "--disable-mcp",
        action="store_true",
        help="Disable MCP servers",
        
    )

    args = parser.parse_args()
    args.enable_mcp = not args.disable_mcp

    config = Configuration()
    # Create logs directory if it doesn't exist
    logs_dir = "logs"
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
    
    # Create log file with timestamp
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(logs_dir, f"chat_session_{timestamp}.log")
    
    # Create the log file with initial session info as JSONL
    with open(log_file, 'w') as f:
        import json
        session_start = {
            "timestamp": datetime.datetime.now().isoformat(),
            "user": "system",
            "type": "session_start",
            "content": "Chat session started",
            "metadata": {
                "model": args.model,
                "base_url": args.base_url,
                "experiment_directory": args.exp_dir
            }
        }
        f.write(json.dumps(session_start) + '\n')
    
    # Set the log file for PrefixedOutput
    set_log_file(log_file)

    chat_config = ChatSessionConfig(
        enable_mcp=args.enable_mcp,
        api_key=config.llm_api_key,
        model_name=args.model,
        base_url=args.base_url,
        initial_message=args.msg,
        constant_msg=args.constant_msg,
    )
    user_configs = [json.load(open(f"{args.exp_dir}/{user}")) for user in os.listdir(args.exp_dir)]
    chat_sessions = [(create_run_chat_session(user["username"], user["interest"]), user["username"]) for user in user_configs]
    
    if len(chat_sessions) == 1:
        session_func, username = chat_sessions[0]
        asyncio.run(run_with_prefix(session_func, username, get_user_color(username), chat_config))
    else:
        async def run_all_sessions():
            tasks = [run_with_prefix(session_func, username, get_user_color(username), chat_config) 
                    for session_func, username in chat_sessions]
            await asyncio.gather(*tasks)
        asyncio.run(run_all_sessions())


if __name__ == "__main__":
    main()
