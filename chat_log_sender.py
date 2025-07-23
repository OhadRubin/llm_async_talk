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

LOG_FILE = "/Users/ohadr/llm_async_talk/logs/chat_session_20250723_115830.log"
PORT = 8080

class ChatLogServer:
    def __init__(self, log_file_path, port=PORT, slowdown=1.1):
        self.log_file_path = Path(log_file_path)
        self.port = port
        self.slowdown = slowdown
        self.clients = set()
        self.messages = []
        self.current_index = 0
        self.broadcast_task = None

    async def load_messages(self):
        """Load all messages from the log file"""
        if not self.log_file_path.exists():
            print(f"Error: Log file {self.log_file_path} not found")
            return

        with open(self.log_file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                    self.messages.append(message)
                except json.JSONDecodeError as e:
                    print(f"Warning: Could not parse line {line_num}: {e}")

        print(f"Loaded {len(self.messages)} messages from log file")

    async def register_client(self, websocket):
        """Register a new client"""
        self.clients.add(websocket)
        print(f"New client connected. Total clients: {len(self.clients)}")

        # Send welcome message
        welcome_msg = {
            'type': 'welcome',
            'message': 'Connected to Chat Log Server',
            'total_messages': len(self.messages)
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

    def parse_message_content(self, raw_content):
        """Parse and categorize message content"""
        import re

        if not raw_content:
            return None
        try:
            username, content = raw_content.strip().split(" | ", 1)
        except ValueError:
            return None

        # Check for bot thinking
        thinking_match = re.search(r'<bot_thinking>(.*?)</bot_thinking>', content, re.DOTALL)
        if thinking_match:
            return {
                "type": "thinking",
                "content": thinking_match.group(1).strip(),
                "user": username,
            }

        # Check for tool calls
        tool_call_match = re.search(r'<tool_call>(.*?)</tool_call>', content, re.DOTALL)
        if tool_call_match:
            tool_data = json.loads(tool_call_match.group(1))
            try:
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
                return res
            except json.JSONDecodeError:
                return None

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
            return None
        result = {
            "type": "chat",
            "content": content,
            "user": username,
        }
        if from_user:
            result["from"] = from_user
        return result

        # Check for user prefix (like "Micheal | You:")
        # user_prefix_match = re.match(r'^(\w+)\s*\|\s*(.+)', content)
        # if user_prefix_match:
        #     return {
        #         "type": "chat",
        #         "content": user_prefix_match.group(2).strip(),
        #         "user": username,
        #     }

        # # Regular chat message
        # if not content:
        #     return None
        # return {"type": "chat", "content": content, "user": username}

    async def start_broadcasting(self):
        """Start broadcasting messages from the log file with original timing"""
        from datetime import datetime

        self.current_index = 0

        while True:
            if self.current_index >= len(self.messages):
                # Restart from beginning when we reach the end
                self.current_index = 0
                await asyncio.sleep(3)  # Pause before restarting
                continue

            message = self.messages[self.current_index]
            raw_content = message.get('content', '')

            parsed_content = self.parse_message_content(
                raw_content.replace("[system] ", "[Server]: ")
            )
            if not parsed_content or (
                parsed_content["type"] == "tool_response"
                and not parsed_content["content"]
                and not parsed_content.get("arguments", None)
            ):
                self.current_index = self.current_index + 1
                continue

            # Add streaming metadata
            broadcast_data = {
                "type": "chat_message",
                "index": self.current_index,
                "total": len(self.messages),
                "timestamp": message.get("timestamp"),
                # 'user': message.get('user'),
                # 'content': raw_content,
                "parsed_content": parsed_content,
                # 'message_type': message.get('type'),
                # 'metadata': message.get('metadata'),
                "stream_time": time.time(),
            }
            if parsed_content.get("from"):
                broadcast_data["from"] = parsed_content["from"]

            await self.broadcast_message(broadcast_data)
            # if "[system]" in json.dumps(broadcast_data):
            print(broadcast_data)
            # if
            # self.current_index = self.current_index +1

            # continue

            # Calculate delay until next message based on original timestamps
            if self.current_index + 1 < len(self.messages):
                try:
                    current_ts = message.get('timestamp')
                    next_ts = self.messages[self.current_index + 1].get('timestamp')

                    if current_ts and next_ts:
                        # Parse timestamps (ISO format)
                        current_time = datetime.fromisoformat(current_ts.replace('Z', '+00:00'))
                        next_time = datetime.fromisoformat(next_ts.replace('Z', '+00:00'))

                        # Calculate actual time difference
                        time_diff = (next_time - current_time).total_seconds()

                        # Apply slowdown factor and cap the delay at 10 seconds max for very long pauses
                        delay = min(max(time_diff * self.slowdown, 0.1), 10.0)
                    else:
                        delay = 0.5 * self.slowdown  # Default delay if timestamps are missing
                except Exception as e:
                    print(f"Error calculating delay: {e}")
                    delay = 0.5 * self.slowdown  # Default delay on error
            else:
                delay = 0.5 * self.slowdown  # Default delay for last message

            self.current_index += 1
            await asyncio.sleep(delay)

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

        if not self.messages:
            print("No messages found in log file. Exiting.")
            return

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

async def main():
    global server
    args = parse_args()
    
    print(f"Starting Chat Log Server with slowdown factor: {args.slowdown}x")
    server = ChatLogServer(args.log_file, args.port, args.slowdown)
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await server.start()
    except KeyboardInterrupt:
        server.stop()

if __name__ == "__main__":
    asyncio.run(main())
