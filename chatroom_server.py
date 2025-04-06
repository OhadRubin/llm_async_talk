#!/usr/bin/env python3
import argparse
import asyncio
import json
import signal
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, List, Set, AsyncGenerator, Optional

# Core FastAPI/Starlette imports
from fastapi import FastAPI, HTTPException, status, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse

# Pydantic for data validation
from pydantic import BaseModel

# Uvicorn for running the server
import uvicorn

# Global variables for signal handling
shutdown_event = threading.Event()

# --- Signal Handlers ---
def setup_signal_handlers():
    """Set up signal handlers for graceful shutdown."""
    def signal_handler(signum, frame):
        print(f"\nReceived signal {signal.Signals(signum).name}, initiating shutdown...")
        shutdown_event.set()
        # Give a short grace period for cleanup
        time.sleep(0.5)
        # Force exit if still running
        sys.exit(0)
    
    # Register signals
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

# Setup signal handlers immediately on module import
setup_signal_handlers()

# --- ChatServer Class (Largely unchanged, thread-safe) ---
class ChatServer:
    def __init__(self):
        self.clients: Dict[str, List[Dict]] = {}  # username -> list of messages
        self.users: Set[str] = set()  # set of active usernames
        self.lock = threading.Lock()  # Standard threading lock is fine here
        self.running = True
        self.waiting_users: Dict[str, float] = {}  # username -> timestamp when started waiting
        self.last_message_timestamp: Dict[str, float] = {}  # username -> timestamp of last received message
        print("ChatServer initialized")

    def register_user(self, username: str) -> bool:
        """Register a new user to the chat server."""
        with self.lock:
            if not self.running:
                return False  # Prevent registration if shutting down
            
            # Auto-register: Add user to set if not already present
            if username not in self.users:
                self.users.add(username)
                self.clients[username] = []
                print(f"New user registered: {username}")
            else:
                print(f"User already registered: {username}")

            return True  # Always return success

    def unregister_user(self, username: str) -> None:
        """Unregister a user from the chat server."""
        user_existed = False
        with self.lock:
            if username in self.users:
                self.users.remove(username)
                user_existed = True
                # Queue of messages will remain until explicitly cleared or server restarts
                print(f"User unregistered: {username}")
                # Remove from waiting users if they were waiting
                if username in self.waiting_users:
                    del self.waiting_users[username]
                if username in self.last_message_timestamp:
                    del self.last_message_timestamp[username]

        if user_existed:
            # Broadcast leave message outside the lock
            self.broadcast_message("Server", f"{username} has left the chat")

    def add_message_to_queue(self, username: str, message: Dict) -> None:
        """Add a message to a user's queue."""
        with self.lock:
            # Only add if user is still considered active in the clients dict
            if username in self.clients:
                self.clients[username].append(message)

    def get_messages(self, username: str) -> List[Dict]:
        """Get all queued messages for a user and clear the queue."""
        with self.lock:
            if username not in self.clients:
                # If user was unregistered but queue still exists, don't error, return empty
                # If user never existed or queue removed, return empty
                return []

            messages = self.clients[username]
            self.clients[username] = []  # Clear the queue
            return messages

    def get_users(self) -> List[str]:
        """Get a list of all active users."""
        with self.lock:
            return list(self.users)  # Return a copy of the users set as a list

    def broadcast_message(self, sender: str, content: str) -> None:
        """Send a message to all connected users."""
        if not self.running:
            return

        message = {
            "sender": sender,
            "content": content,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
        }

        current_time = time.time()
        
        # Get the list of users *under the lock* to avoid race conditions
        with self.lock:
            current_users = list(self.users)  # Create a copy
            
            # If a user sent a message, update their last message timestamp
            if sender != "Server" and sender in self.users:
                self.last_message_timestamp[sender] = current_time
                
            # If someone other than the server or waiting users sends a message,
            # consider that as a response to waiting users
            if sender != "Server" and self.waiting_users:
                # Clear waiting users since someone responded
                self.waiting_users.clear()

        # Iterate over the copy outside the lock to prevent holding it while potentially
        # doing more work in add_message_to_queue (though it's quick here)
        for username in current_users:
            # add_message_to_queue acquires lock itself
            self.add_message_to_queue(username, message)
        print(f"Broadcast message from {sender} to {len(current_users)} users.")

    def mark_user_waiting(self, username: str) -> None:
        """Mark a user as waiting for a response."""
        with self.lock:
            if username in self.users:
                self.waiting_users[username] = time.time()
                print(f"User {username} is now waiting for a response")

    def get_waiting_users(self) -> Dict[str, float]:
        """Get a copy of the waiting users dictionary."""
        with self.lock:
            return self.waiting_users.copy()

    def stop(self) -> None:
        """Stop the chat server."""
        if not self.running:
            return  # Already stopped
        print("Stopping ChatServer...")
        self.running = False
        # Notify all clients currently connected
        # Get users under lock before broadcasting shutdown
        with self.lock:
            current_users = list(self.users)
            # Clear users set but preserve client message queues
            self.users.clear()
            # Clear waiting users
            self.waiting_users.clear()

        # Send shutdown message to users who were connected at the moment of shutdown
        shutdown_message = {
            "sender": "Server",
            "content": "Server shutting down...",
            "timestamp": datetime.now().strftime("%H:%M:%S"),
        }
        for username in current_users:
            # Add shutdown message to any remaining queues
            if username in self.clients:
                self.clients[username].append(shutdown_message)
        print(f"Server stopping... Notified {len(current_users)} users.")
        # Note: SSE streams will naturally terminate when the server stops accepting connections


# --- Background Tasks ---
async def check_waiting_users(chat_server: ChatServer):
    """
    Periodically checks for users waiting for responses and sends reminders
    if no one has responded within 3 seconds.
    """
    while chat_server.running:
        waiting_users = chat_server.get_waiting_users()
        current_time = time.time()
        
        for username, wait_start_time in waiting_users.items():
            # If user has been waiting for 3+ seconds, send a reminder
            if current_time - wait_start_time >= 10:
                notification = f"{username} is still waiting for a response"
                chat_server.broadcast_message("Server", notification)
                # Update the waiting timestamp to reset the timer
                with chat_server.lock:
                    if username in chat_server.waiting_users:
                        chat_server.waiting_users[username] = current_time
        
        # Check every second
        await asyncio.sleep(1)


# --- FastAPI Lifespan Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Server starting up...")
    app.state.chat_server = ChatServer()  # Store server instance in app state

    # Setup shutdown monitoring task
    async def monitor_shutdown():
        # Wait for the shutdown event to be set
        while not shutdown_event.is_set():
            await asyncio.sleep(0.1)
        # Once set, stop the chat server
        print("Shutdown event detected, stopping chat server...")
        app.state.chat_server.stop()

    # Start background tasks
    waiting_users_task = asyncio.create_task(check_waiting_users(app.state.chat_server))
    shutdown_monitor_task = asyncio.create_task(monitor_shutdown())
    
    # Run the application
    yield
    
    # Shutdown was triggered either by signal or application exit
    print("Server shutting down...")
    if app.state.chat_server.running:
        app.state.chat_server.stop()
    
    # Cancel background tasks
    waiting_users_task.cancel()
    shutdown_monitor_task.cancel()
    try:
        await waiting_users_task
        await shutdown_monitor_task
    except asyncio.CancelledError:
        pass
    
    print("ChatServer stopped.")


# --- FastAPI App ---
app = FastAPI(lifespan=lifespan)


# --- Pydantic Models for Request Bodies ---
class UserRequest(BaseModel):
    username: str


class SendRequest(BaseModel):
    username: str
    message: str


class TalkingStickRequest(BaseModel):
    username: str


class CheckEventRequest(BaseModel):
    username: str


# --- API Endpoints ---
@app.get("/", response_class=HTMLResponse)
async def home():
    # Simple status page
    return """
    <html>
    <head><title>FastAPI SSE Chat Server</title></head>
    <body>
        <h1>FastAPI SSE Chat Server</h1>
        <p>Server is running. Connect using the client application.</p>
        <p><a href="/docs">API Documentation (Swagger UI)</a></p>
        <p><a href="/redoc">API Documentation (ReDoc)</a></p>
    </body>
    </html>
    """


@app.post("/register", status_code=status.HTTP_200_OK)
async def register(user: UserRequest, request: Request):
    """Registers a new user."""
    chat_server: ChatServer = request.app.state.chat_server
    if not chat_server.running:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server is shutting down",
        )

    # Always register successfully
    chat_server.register_user(user.username)
    return {"success": True}


@app.post("/reconnect", status_code=status.HTTP_200_OK)
async def reconnect(user: UserRequest, request: Request):
    """Reconnects an existing user or registers them if they don't exist."""
    chat_server: ChatServer = request.app.state.chat_server
    if not chat_server.running:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server is shutting down",
        )
    
    with chat_server.lock:
        # If username exists in clients dict but not in users set, add it back
        if user.username in chat_server.clients and user.username not in chat_server.users:
            chat_server.users.add(user.username)
            print(f"User reconnected: {user.username}")
            return {"success": True}
        # If user is brand new, register them
        elif user.username not in chat_server.users:
            success = chat_server.register_user(user.username)
            if success:
                return {"success": True}
        # If user is already connected, it's a success
        elif user.username in chat_server.users:
            print(f"User already connected: {user.username}")
            return {"success": True}
    
    # Should not reach here under normal circumstances
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Could not reconnect user.",
    )


@app.post("/unregister", status_code=status.HTTP_200_OK)
async def unregister(user: UserRequest, request: Request):
    """Unregisters a user."""
    chat_server: ChatServer = request.app.state.chat_server
    # No need to check chat_server.running here, unregister should work even during shutdown prep
    chat_server.unregister_user(user.username)
    # Always return success, even if user wasn't registered (idempotent)
    return {"success": True}


@app.post("/send", status_code=status.HTTP_200_OK)
async def send(data: SendRequest, request: Request):
    """Sends a message from a user to all active users."""
    chat_server: ChatServer = request.app.state.chat_server
    if not chat_server.running:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server is shutting down",
        )

    # Check if user is registered (need lock for safe check against users set)
    with chat_server.lock:
        if data.username not in chat_server.users:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not registered"
            )

    # Broadcast the message (method handles its own locking)
    chat_server.broadcast_message(data.username, data.message)
    return {"success": True}


@app.post("/talking_stick", status_code=status.HTTP_200_OK)
async def claim_talking_stick(data: TalkingStickRequest, request: Request):
    """Claims the talking stick for a user, notifying all users of the claim."""
    chat_server: ChatServer = request.app.state.chat_server
    if not chat_server.running:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server is shutting down",
        )

    # Check if user is registered
    with chat_server.lock:
        if data.username not in chat_server.users:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not registered"
            )

    # Broadcast a system message that user has claimed the talking stick
    notification = f"{data.username} has claimed the talking stick and wants to speak"
    chat_server.broadcast_message("Server", notification)
    return {"success": True}


@app.post("/check_event", status_code=status.HTTP_200_OK)
async def check_event(data: CheckEventRequest, request: Request):
    """Notifies all users that a user is waiting for a response."""
    chat_server: ChatServer = request.app.state.chat_server
    if not chat_server.running:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server is shutting down",
        )

    # Check if user is registered
    with chat_server.lock:
        if data.username not in chat_server.users:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not registered"
            )

    # Broadcast a system message that user is waiting for a response
    notification = f"{data.username} is waiting for a response"
    chat_server.broadcast_message("Server", notification)
    
    # Mark the user as waiting for a response
    chat_server.mark_user_waiting(data.username)
    
    return {"success": True}


@app.get("/events")
async def events(username: str, request: Request) -> StreamingResponse:
    """
    SSE endpoint for receiving chat messages.
    Requires 'username' query parameter.
    """
    chat_server: ChatServer = request.app.state.chat_server

    # Auto-register the user if not already registered
    with chat_server.lock:
        if username not in chat_server.users and chat_server.running:
            chat_server.register_user(username)
            print(f"Auto-registered user for SSE stream: {username}")

    async def event_stream() -> AsyncGenerator[str, None]:
        """Yields SSE messages for the specified user."""
        try:
            print(f"SSE stream opened for user: {username}")
            while chat_server.running:
                # Check if user is still registered *within the loop*
                # in case they unregistered via another request.
                # Lock needed for safe check.
                with chat_server.lock:
                    if username not in chat_server.users:
                        print(
                            f"User '{username}' no longer registered. Closing SSE stream."
                        )
                        break  # Exit loop if user unregistered

                messages = chat_server.get_messages(
                    username
                )  # Method handles its own lock

                if not chat_server.running:  # Double-check after getting messages
                    print("Server stopping, breaking SSE loop.")
                    break

                if messages:
                    data = json.dumps(messages)
                    yield f"data: {data}\n\n"
                    # print(f"Sent {len(messages)} messages to {username}") # Debug logging
                else:
                    # Send a keepalive comment periodically to prevent timeouts
                    yield ": keepalive\n\n"

                # Use asyncio.sleep in async functions
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            # This happens if the client disconnects
            print(f"Client disconnected (SSE stream cancelled) for user: {username}")
        except Exception as e:
            print(f"Error in SSE stream for {username}: {e}")
        finally:
            # Clean up when the stream closes (normally or due to error/disconnect)
            print(f"SSE stream closed for user: {username}")
            # Don't unregister users automatically, allow them to reconnect
            # chat_server.unregister_user(username)

    # Return the streaming response
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/users", status_code=status.HTTP_200_OK)
async def get_users(request: Request):
    """Returns a list of all active users."""
    chat_server: ChatServer = request.app.state.chat_server
    if not chat_server.running:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server is shutting down",
        )

    users = chat_server.get_users()
    return {"users": users}


# --- Main Execution ---
def main():
    parser = argparse.ArgumentParser(description="FastAPI SSE Chat Server")
    parser.add_argument(
        "--host", default="0.0.0.0", help="Server host (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=8890, help="Server port (default: 8890)"
    )
    # Uvicorn has its own --reload flag, better than Flask's debug mode
    # parser.add_argument("--reload", action="store_true", help="Enable auto-reload")

    args = parser.parse_args()

    print(f"Starting FastAPI SSE Chat Server on http://{args.host}:{args.port}")
    print("Access API docs at /docs")
    print("Press Ctrl+C to stop the server")

    # Run Uvicorn programmatically with log configuration to see shutdown messages
    config = uvicorn.Config(
        "__main__:app",
        host=args.host,
        port=args.port,
        log_level="info",
        # Force debug off to avoid reload behavior which can interfere with signal handling
        # debug=False,
        # Reduce workers to 1 to simplify signal handling
        workers=1
    )

    server = uvicorn.Server(config)

    try:
        # The server.run() method blocks until the server stops
        server.run()
    except KeyboardInterrupt:
        print("\nKeyboard interrupt received, shutting down gracefully...")
        shutdown_event.set()
    finally:
        print("Server shutdown complete.")

# docker build -t chatroom-server .
# docker run chatroom-server
if __name__ == "__main__":
    main()
