#!/usr/bin/env python3
"""
Chat Log WebSocket Server
Reads chat log file and streams messages to connected clients
Run with: python chat_log_sender.py
"""

import asyncio
import websockets
import json
import time
from pathlib import Path
import signal
import sys

LOG_FILE = "/Users/ohadr/llm_async_talk/logs/chat_session_20250723_115830.log"
PORT = 8080

class ChatLogServer:
    def __init__(self, log_file_path, port=PORT):
        self.log_file_path = Path(log_file_path)
        self.port = port
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
            
            # Add streaming metadata
            broadcast_data = {
                'type': 'chat_message',
                'index': self.current_index,
                'total': len(self.messages),
                'timestamp': message.get('timestamp'),
                'user': message.get('user'),
                'content': message.get('content'),
                'message_type': message.get('type'),
                'metadata': message.get('metadata'),
                'stream_time': time.time()
            }
            
            await self.broadcast_message(broadcast_data)
            
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
                        
                        # Cap the delay at 10 seconds max for very long pauses
                        delay = min(max(time_diff, 0.1), 10.0)
                    else:
                        delay = 0.5  # Default delay if timestamps are missing
                except Exception as e:
                    print(f"Error calculating delay: {e}")
                    delay = 0.5  # Default delay on error
            else:
                delay = 0.5  # Default delay for last message
            
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

async def main():
    global server
    server = ChatLogServer(LOG_FILE, PORT)
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await server.start()
    except KeyboardInterrupt:
        server.stop()

if __name__ == "__main__":
    asyncio.run(main())