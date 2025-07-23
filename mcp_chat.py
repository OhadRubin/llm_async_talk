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

# Context variable to store the current prefix
current_prefix = contextvars.ContextVar('current_prefix', default='')

# Global lock for stdout access
_stdout_lock = threading.Lock()

class PrefixedOutput:
    """A custom stdout wrapper that prefixes each line with the current context prefix."""
    
    def __init__(self, original_stdout=None):
        self.original_stdout = original_stdout or sys.stdout
        self.buffer = ""
        
    def write(self, text: str) -> int:
        if not text:
            return 0
            
        prefix = current_prefix.get('')
        
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
                    self.original_stdout.write(f"{prefix} | {line}\n")
                elif line:
                    self.original_stdout.write(f"{line}\n")
                else:
                    self.original_stdout.write("\n")
            
            self.original_stdout.flush()
        
        return len(text)
    
    def flush(self):
        prefix = current_prefix.get('')
        with _stdout_lock:
            # Flush any remaining buffer content
            if self.buffer:
                if prefix:
                    self.original_stdout.write(f"{prefix} | {self.buffer}\n")
                else:
                    self.original_stdout.write(f"{self.buffer}\n")
                self.buffer = ""
            self.original_stdout.flush()
        
    def __getattr__(self, name):
        # Delegate other attributes to original stdout
        return getattr(self.original_stdout, name)

# Global prefixed output instance
_prefixed_stdout = PrefixedOutput()

# Replace sys.stdout with our prefixed version
sys.stdout = _prefixed_stdout

async def run_with_prefix(func: Callable, prefix: str, *args, **kwargs):
    """Run an async function with prefixed output using contextvars."""
    # Set the prefix for this async context
    token = current_prefix.set(prefix)
    try:
        return await func(*args, **kwargs)
    finally:
        # Reset the context
        current_prefix.reset(token)


# async def generic_server(server_id: int):
#     print(f"Generic server {server_id} starting...")
#     await asyncio.sleep(0.1 * server_id)
#     print(f"Processing on server {server_id}")
#     await asyncio.sleep(0.2)
#     print(f"Server {server_id} done")


# async def main():
#     # Run multiple async functions concurrently
#     tasks = [
#         server1(),
#         server2(),
#         server3(),
#         run_with_prefix(generic_server, "generic-server-4", 4),
#         run_with_prefix(generic_server, "generic-server-5", 5),
#     ]
    
#     await asyncio.gather(*tasks)


# if __name__ == "__main__":
#     print("Starting async functions with prefixed output...\n")
#     asyncio.run(main())
#     print("\nAll tasks completed!")

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
        asyncio.run(run_with_prefix(session_func, username, chat_config))
    else:
        async def run_all_sessions():
            tasks = [run_with_prefix(session_func, username, chat_config) 
                    for session_func, username in chat_sessions]
            await asyncio.gather(*tasks)
        asyncio.run(run_all_sessions())


if __name__ == "__main__":
    main()
