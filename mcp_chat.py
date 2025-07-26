import argparse
import asyncio
import websockets
import time
from pathlib import Path

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

# Import WebSocket server functionality from chat_log_sender
from chat_log_sender import ChatLogServer, parse_message_content

# Global message queue for live WebSocket broadcasting
live_message_queue = asyncio.Queue()
msg_queue = asyncio.Queue()

def create_live_message_iterator():
    """Create an async iterator that yields messages from the live queue."""
    async def message_generator():
        while True:
            try:
                message = await live_message_queue.get()
                yield message
            except Exception as e:
                print(f"Error in live message iterator: {e}")
                await asyncio.sleep(0.1)
    
    return message_generator()





@dataclass
class ChatSessionConfig:
    """Configuration for chat session."""

    enable_mcp: bool
    api_key: str
    model_name: str = "google/gemini-flash-1.5"
    base_url: str = "https://openrouter.ai/api/v1"
    initial_message: str | None = None
    constant_msg: str | None = None
    mock_mode: bool = False

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
    chain: OpenAIMessageChain,  config: ChatSessionConfig
    # initial_message: str | None = None, constant_msg: str | None = None
) -> OpenAIMessageChain:
    # Send initial message if provided
    initial_message = config.initial_message
    constant_msg = config.constant_msg
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
                    verbose=False,
                    session_id=username,
                    # verbose=True,
                    stream_queue=msg_queue
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
            if not config.mock_mode:
                chain = await handle_interactive_session(chain, config)
            else:
                # Add random delay to prevent all sessions from hitting the server simultaneously
                import random
                while True:
                    print("Mock mode, skipping interactive session")
                    delay = random.uniform(1, 5)  # Random delay between 0.1-0.5 seconds
                    await asyncio.sleep(delay)

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
    parser.add_argument(
        "--websocket-port",
        type=int,
        default=8080,
        help="WebSocket server port for live chat viewing (default: 8080)",
    )
    parser.add_argument(
        "--mock-mode",
        action="store_true",
        help="Mock mode, skip interactive session",
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
    

    chat_config = ChatSessionConfig(
        enable_mcp=args.enable_mcp,
        api_key=config.llm_api_key,
        model_name=args.model,
        base_url=args.base_url,
        initial_message=args.msg,
        constant_msg=args.constant_msg,
        mock_mode=args.mock_mode,
    )
    user_configs = [json.load(open(f"{args.exp_dir}/{user}")) for user in os.listdir(args.exp_dir)]
    chat_sessions = [(create_run_chat_session(user["username"], user["interest"]), user["username"]) for user in user_configs]
    
    # Create and start WebSocket server
    message_iterator = create_live_message_iterator()
    websocket_server = ChatLogServer(message_iterator, args.websocket_port)
    
    async def start_websocket_server():
        """Start the WebSocket server for live chat viewing."""
        try:
            print(f"Starting WebSocket server on port {args.websocket_port}")
            await websocket_server.start()
        except Exception as e:
            print(f"Failed to start WebSocket server: {e}")
    
    async def start_msg_queue():
        """Start the message queue for live chat viewing."""
        while True:
            timestamp = datetime.datetime.now().isoformat()
            message = await msg_queue.get()
            message["timestamp"] = timestamp
            
            print(f"Message: {message}")
            message["format"] = "v2"
            with open(log_file, 'a', encoding='utf-8') as f:
                
                f.write(json.dumps(message) + '\n')
                f.flush()
            live_message_queue.put_nowait(message)
    
    assert len(chat_sessions) > 1

    async def run_all_sessions():
        chat_tasks = [session_func(chat_config) for session_func, username in chat_sessions]
        # Start WebSocket server alongside all chat sessions
        await asyncio.gather(
            start_websocket_server(),
            start_msg_queue(),
            *chat_tasks
        )
    asyncio.run(run_all_sessions())


if __name__ == "__main__":
    main()
