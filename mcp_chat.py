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

@dataclass
class ChatSessionConfig:
    """Configuration for chat session."""

    servers: list["Server"]
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
        try:
            # Initialize servers
            if not await initialize_servers(config.servers):
                return

            # Create tool functions and schemas
            tool_schemas, tool_mapping = await create_tool_functions(config.servers)

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
            await cleanup_servers(config.servers)
    return run_chat_session


def main() -> None:
    """Initialize and run the chat session."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="MCP Client with OpenAI Message Chain")
    parser.add_argument(
        "--model",
        # default="google/gemini-flash-1.5",
        default="gpt-4.1-nano",
        help="Model name to use (default: google/gemini-flash-1.5)",
    )
    parser.add_argument(
        "--base-url",
        # default="https://openrouter.ai/api/v1",
        default=None,
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
    servers = []
    if args.enable_mcp:
        server_config = {
            "mcpServers": {
                "chatroom": {
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

    chat_config = ChatSessionConfig(
        servers=servers,
        api_key=config.llm_api_key,
        model_name=args.model,
        base_url=args.base_url,
        initial_message=args.msg,
        constant_msg=args.constant_msg,
    )
    users = [json.load(open(f"{args.exp_dir}/{user}")) for user in os.listdir(args.exp_dir)]
    users = [create_run_chat_session(user["username"], user["interest"]) for user in users]
    if len(users) == 1:
        asyncio.run(users[0](chat_config))
    else:
        async def run_all_sessions():
            await asyncio.gather(*[user(chat_config) for user in users])
        asyncio.run(run_all_sessions())
    





if __name__ == "__main__":
    main()
    
