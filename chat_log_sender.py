#!/usr/bin/env python3
"""
Chat Log WebSocket Server
Reads chat log file and streams messages to connected clients with original timing

Usage:
  python chat_log_sender.py                                    # Use defaults
  python chat_log_sender.py --slowdown 2.0                    # Half speed
  python chat_log_sender.py --slowdown 0.5                    # Double speed  
  python chat_log_sender.py --log-file path/to/other.log      # Different log file
  python chat_log_sender.py --port 9090 --slowdown 1.5        # Custom port and speed
"""

import asyncio
import websockets
import json
import time
from pathlib import Path
import signal
import sys
import argparse

LOG_FILE = "/Users/ohadr/llm_async_talk/logs/chat_session_20250725_210930.log"
PORT = 8080

def parse_multi_message_content(content, base_user="unknown"):
    """
    Parse content that may contain multiple bracketed messages.
    
    Args:
        content: The raw content string to parse
        base_user: The default user if no bracketed user found
        
    Returns:
        List of parsed message dictionaries
    """
    
    content = content.strip().replace("Logged in successfully as","[Server]: Logged in successfully as").replace("[system] ", "[Server]: ")
    if not content or not content.strip():
        return []
    
    import re
    messages = []
    
    # Use regex to capture all bracketed messages with their content
    pattern = r'\[([^\]]+)\]:\s*(.*?)(?=\[[^\]]+\]:|$)'
    matches = re.findall(pattern, content, re.DOTALL)
    
    for username, message_content in matches:
        username = username.strip()
        message_content = message_content.strip()
        
        if not message_content:
            continue
            
        # Determine message type based on bracketed user
        if username.lower() in ["system", "server"]:
            message = {
                "type": "chat",
                "user": base_user,
                "from": "Server",
                "content": message_content
            }
        else:
            message = {
                "type": "chat", 
                "from": username,
                "content": message_content,
                "user": base_user,
            }
        
        messages.append(message)
    
    # If no bracketed messages found, treat entire content as single message
    if not messages and content.strip():
        messages.append({
            "type": "chat",
            "user": base_user,
            "content": content.strip()
        })
    
    return messages


def detect_message_format(message):
    """Detect if message is V1 or V2 format"""
    if isinstance(message, dict):
        if message.get("format") == "v2":
            return "v2"
        elif "content" in message and isinstance(message["content"], str) and " | " in message["content"]:
            return "v1"
        elif "role" in message and "session_id" in message:
            return "v2"  # V2 without explicit format field
    return "v1"  # Default to V1 for backward compatibility


def parse_message_content_v2(message):
    """Parse V2 format message and categorize content - returns list of messages"""
    if not isinstance(message, dict):
        return []
    
    role = message.get("role")
    session_id = message.get("session_id")
    content = message.get("content", "")
    
    if not session_id:
        return []
    
    results = []
    
    # Handle different roles
    if role == "user":
        pass
        # results.append({
        #     "type": "chat",
        #     "content": f"You: {content}",  # Add "You: " prefix for V1 compatibility
        #     "user": session_id,
        # })
    
    elif role == "assistant":
        tool_calls = message.get("tool_calls", [])
        
        # If there's content, add it as a message first
        if content.strip():

            results.append({
                "type": "thinking",
                "content": content,
                "user": session_id,
            })
            
        # Add tool calls as separate messages
        for tool_call in tool_calls:
            function_name = tool_call.get("function", {}).get("name", "unknown")
            arguments = tool_call.get("function", {}).get("arguments", "{}")
            
            result = {
                "type": "tool_call",
                "function": function_name,
                "user": session_id,
            }
            
            # Special handling for append function
            if function_name == "append":
                try:
                    args_data = json.loads(arguments)
                    result["arguments"] = args_data.get("text", "")
                except json.JSONDecodeError:
                    pass
            
            results.append(result)


    
    elif role == "tool":
        # Tool response - use multi-message parser for complex patterns
        parsed_messages = parse_multi_message_content(content, session_id)
        
        if parsed_messages:
            # Found bracketed messages, add them all
            results.extend(parsed_messages)
        else:
            # No bracketed messages, treat as regular tool response
            if content.strip():
                results.append({
                    "type": "tool_response",
                    "content": content.strip().replace("Logged in successfully as","[Server] Logged in successfully as").replace("[system]", "[Server]"),
                    "user": session_id,
                })
    
    elif role == "system":
        # System messages - usually not displayed in chat
        pass  # Don't add anything to results
    
    elif role == "tool_spec":
        # Tool specifications - not displayed in chat
        pass  # Don't add anything to results
    
    else:
        # Unknown role, treat as chat
        results.append({
            "type": "chat",
            "content": content,
            "user": session_id,
        })
    
    return results


def parse_message_content_v1(raw_content):
    """Parse and categorize V1 format message content - returns list of messages"""
    raw_content = raw_content.replace("[system] ", "[Server]: ")
    import re

    if not raw_content:
        return []
    try:
        username, content = raw_content.strip().split(" | ", 1)
    except ValueError:
        return []

    # Check for bot thinking
    thinking_match = re.search(r'<bot_thinking>(.*?)</bot_thinking>', content, re.DOTALL)
    if thinking_match:
        return [{
            "type": "thinking",
            "content": thinking_match.group(1).strip(),
            "user": username,
        }]

    # Check for tool calls
    tool_call_match = re.search(r'<tool_call>(.*?)</tool_call>', content, re.DOTALL)
    if tool_call_match:
        try:
            tool_data = json.loads(tool_call_match.group(1))
            ftype = tool_data.get("function", {}).get("name", "unknown")
            res = {
                "type": "tool_call",
                "function": ftype,
                # 'content': tool_call_match.group(1).strip(),
                "user": username,
            }
            if ftype == "append":
                res["arguments"] = json.loads(
                    tool_data.get("function", {}).get("arguments", "")
                )["text"]
            return [res]
        except json.JSONDecodeError:
            return []

    # Check for tool responses
    tool_response_match = re.search(r'<tool_response>(.*?)</tool_response>', content, re.DOTALL)
    if not tool_response_match:
        # Also check for tool_response without closing tag (in case it's truncated)
        tool_response_match = re.search(r"<tool_response>(.*)", content, re.DOTALL)

    if not tool_response_match:
        tool_response_match = re.search(r"(.*)</tool_response>", content, re.DOTALL)

    if tool_response_match:
        content = tool_response_match.group(1).strip()
    from_match = re.search(r"\[(.*)\]: (.*)", content)
    if from_match:
        from_user = from_match.group(1).strip()
        content = from_match.group(2).strip()
    else:
        from_user = None
    if not content:
        return []
    result = {
        "type": "chat",
        "content": content,
        "user": username,
    }
    if from_user:
        result["from"] = from_user
    return [result]


def parse_message_content(message):
    """Parse message content - handles both V1 and V2 formats"""
    format_version = detect_message_format(message)
    
    if format_version == "v2":
        return parse_message_content_v2(message)
    else:
        # V1 format - extract content string
        raw_content = message.get('content', '') if isinstance(message, dict) else str(message)
        return parse_message_content_v1(raw_content)

class ChatLogServer:
    def __init__(self, message_iterator, port=PORT, slowdown=1.1):
        self.message_iterator = message_iterator
        self.port = port
        self.slowdown = slowdown
        self.clients = set()
        self.broadcast_task = None


    async def load_messages(self):
        """Messages are loaded dynamically from the infinite iterator during broadcasting"""
        print("Using infinite iterator - messages will be loaded during broadcasting")


    async def start_broadcasting(self):
        """Start broadcasting messages from the infinite iterator with original timing"""
        from datetime import datetime

        previous_message = None

        async for message in self.message_iterator:
            parsed_contents = parse_message_content(message)
            
            # Handle empty results
            if not parsed_contents:
                previous_message = message
                continue
            
            # Process each parsed message separately
            for parsed_content in parsed_contents:
                if not parsed_content or (
                    parsed_content["type"] == "tool_response"
                    and not parsed_content["content"]
                    and not parsed_content.get("arguments", None)
                ):
                    continue

                # Add streaming metadata
                broadcast_data = {
                    "type": "chat_message",
                    "timestamp": message.get("timestamp"),
                    "parsed_content": parsed_content,
                    "stream_time": time.time(),
                }
                if parsed_content.get("from"):
                    broadcast_data["from"] = parsed_content["from"]

                await self.broadcast_message(broadcast_data)
                print(broadcast_data)

            # Calculate delay until next message based on previous timestamp
            if previous_message:
                try:
                    previous_ts = previous_message.get('timestamp')
                    current_ts = message.get('timestamp')

                    if previous_ts and current_ts:
                        # Parse timestamps (ISO format)
                        previous_time = datetime.fromisoformat(previous_ts.replace('Z', '+00:00'))
                        current_time = datetime.fromisoformat(current_ts.replace('Z', '+00:00'))

                        # Calculate actual time difference
                        time_diff = (current_time - previous_time).total_seconds()

                        # Apply slowdown factor and cap the delay at 10 seconds max for very long pauses
                        delay = min(max(time_diff * self.slowdown, 0.1), 10.0)
                    else:
                        delay = 0.5 * self.slowdown  # Default delay if timestamps are missing
                except Exception as e:
                    print(f"Error calculating delay: {e}")
                    delay = 0.5 * self.slowdown  # Default delay on error
            else:
                delay = 0.5 * self.slowdown  # Default delay for first message

            previous_message = message
            await asyncio.sleep(delay)


    async def register_client(self, websocket):
        """Register a new client"""
        self.clients.add(websocket)
        print(f"New client connected. Total clients: {len(self.clients)}")

        # Send welcome message
        welcome_msg = {
            'type': 'welcome',
            'message': 'Connected to Chat Log Server'
        }
        await websocket.send(json.dumps(welcome_msg))

    async def unregister_client(self, websocket):
        """Unregister a client"""
        self.clients.discard(websocket)
        print(f"Client disconnected. Total clients: {len(self.clients)}")

    async def broadcast_message(self, message):
        """Broadcast a message to all connected clients"""
        if not self.clients:
            return

        # Remove disconnected clients
        disconnected = set()
        for client in self.clients:
            try:
                await client.send(json.dumps(message))
            except websockets.exceptions.ConnectionClosed:
                disconnected.add(client)

        # Clean up disconnected clients
        for client in disconnected:
            self.clients.discard(client)





    async def handle_client(self, websocket):
        """Handle individual client connections"""
        await self.register_client(websocket)
        try:
            # Keep connection alive and handle any incoming messages
            async for message in websocket:
                try:
                    data = json.loads(message)
                    if data.get('type') == 'ping':
                        await websocket.send(json.dumps({'type': 'pong'}))
                except json.JSONDecodeError:
                    pass
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            print(f"Error handling client: {e}")
        finally:
            await self.unregister_client(websocket)

    async def start(self):
        """Start the WebSocket server"""
        # Load messages from log file
        await self.load_messages()

        print(f"Chat Log WebSocket Server starting on ws://localhost:{self.port}")

        # Start the WebSocket server
        server = await websockets.serve(self.handle_client, "localhost", self.port)

        # Start broadcasting task
        self.broadcast_task = asyncio.create_task(self.start_broadcasting())

        # Run both the server and broadcasting concurrently
        await asyncio.gather(
            server.wait_closed(),
            self.broadcast_task
        )

    def stop(self):
        """Stop the server"""
        if self.broadcast_task:
            self.broadcast_task.cancel()
        print("\nShutting down server...")

# Global server instance for signal handling
server = None

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    if server:
        server.stop()
    sys.exit(0)

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Chat Log WebSocket Server - Stream chat log messages to connected clients'
    )
    parser.add_argument(
        '--log-file',
        type=str,
        default=LOG_FILE,
        help=f'Path to the chat log file (default: {LOG_FILE})'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=PORT,
        help=f'WebSocket server port (default: {PORT})'
    )
    parser.add_argument(
        '--slowdown',
        type=float,
        default=1.1,
        help='Slowdown factor for message timing (1.0 = original speed, 2.0 = half speed, 0.5 = double speed) (default: 1.1)'
    )
    return parser.parse_args()

def create_message_iterator(log_file_path):
    """Create an infinite async iterator from the log file"""
    log_file_path = Path(log_file_path)
    
    async def message_generator():
        while True:
            if not log_file_path.exists():
                print(f"Warning: Log file {log_file_path} not found, waiting...")
                await asyncio.sleep(1)
                continue
                
            try:
                with open(log_file_path, 'r', encoding='utf-8') as f:
                    for line_num, line in enumerate(f, 1):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            message = json.loads(line)
                            yield message
                        except json.JSONDecodeError as e:
                            print(f"Warning: Could not parse line {line_num}: {e}")
                            continue
                # When we reach EOF, restart from beginning
                print("Reached end of log file, restarting from beginning...")
                await asyncio.sleep(3)  # Brief pause before restarting
            except Exception as e:
                print(f"Error reading log file: {e}")
                await asyncio.sleep(1)
    
    return message_generator()

async def main():
    global server
    args = parse_args()
    
    print(f"Starting Chat Log Server with slowdown factor: {args.slowdown}x")
    message_iterator = create_message_iterator(args.log_file)
    server = ChatLogServer(message_iterator, args.port, args.slowdown)
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await server.start()
    except KeyboardInterrupt:
        server.stop()

if __name__ == "__main__":
    asyncio.run(main())
