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
from typing import Dict, List, Set, AsyncGenerator, Optional, Any

# Core FastAPI/Starlette imports
from fastapi import FastAPI, HTTPException, status, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse

# Pydantic for data validation
from pydantic import BaseModel



# --- ChatServer Class (Largely unchanged, thread-safe) ---
class ChatServer:
    def __init__(self):
        self.clients: Dict[str, List[Dict]] = {}  # username -> list of messages
        self.users: Set[str] = set()  # set of active usernames
        self.lock = threading.Lock()  # Standard threading lock is fine here
        self.running = True
        self.sse_tasks: Dict[str, asyncio.Task[Any]] = {} # Track active SSE tasks

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
        with self.lock:
            # Remove from active users set
            if username in self.users:
                self.users.remove(username)
                print(f"User unregistered: {username}")
                
            # Cancel and remove any associated SSE task if user unregisters explicitly
            task = self.sse_tasks.pop(username, None)
            if task and not task.done():
                task.cancel()
                print(f"Cancelled SSE task for explicitly unregistered user: {username}")

            # Clean up message queue (don't remove as they might reconnect)
            if username in self.clients:
                # Don't delete the queue completely, just clear it
                # This allows users to reconnect without losing their identity
                self.clients[username] = []
                


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
        
        # Get the list of users *under the lock* to avoid race conditions
        with self.lock:
            current_users = list(self.users)  # Create a copy
            
        # Iterate over the copy outside the lock to prevent holding it while potentially
        # doing more work in add_message_to_queue (though it's quick here)
        for username in current_users:
            # add_message_to_queue acquires lock itself
            self.add_message_to_queue(username, message)
        print(f"Broadcast message from {sender} to {len(current_users)} users.")


    async def stop(self) -> None:
        """Stop the chat server and clean up resources."""
        if not self.running:
            return  # Already stopped
        print("Stopping ChatServer...")
        self.running = False

        # --- Graceful SSE Task Cancellation ---
        tasks_to_cancel: List[asyncio.Task[Any]] = []
        with self.lock:
            # Create a list of tasks to cancel while holding the lock
            tasks_to_cancel = list(self.sse_tasks.values())
            # Clear the task dictionary immediately
            self.sse_tasks.clear()
            # Get users before clearing the main users set
            current_users = list(self.users)
            self.users.clear() # Clear the main users set

        print(f"Attempting to cancel {len(tasks_to_cancel)} active SSE tasks...")
        for task in tasks_to_cancel:
            task.cancel()

        # Wait for all cancellation tasks to complete
        if tasks_to_cancel:
            # return_exceptions=True prevents gather from stopping if one task raises error
            results = await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            print(f"SSE task cancellation results: {results}") # Log results/errors
        print("All active SSE tasks cancelled.")
        # --- End SSE Task Cancellation ---


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
        
        # Give clients a moment to process the shutdown message
        time.sleep(1)
        
        # Final cleanup of all resources
        with self.lock:
            # Clear all client message queues to free memory
            self.clients.clear()
            
            # Log cleanup completion
            print("All server resources cleaned up.")


# --- FastAPI Lifespan Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Server starting up...")
    app.state.chat_server = ChatServer()  # Store server instance in app state

    try: # Added try/finally for robust shutdown
        # Run the application
        yield
    finally:
        # Shutdown
        print("Server shutting down...")
        chat_server: ChatServer = app.state.chat_server
        if chat_server:
            await chat_server.stop() # Await the async stop method
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
    delay: int = 1

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

    # Log when a user sends a message
    print(f"[SERVER] {data.username} sent message: {data.message}")
    
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
    notification = f"{data.username} has been waiting for a response for {data.delay} seconds..."
    chat_server.broadcast_message("Server", notification)
    
    
    
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
        last_activity_time = time.time()
        connection_timeout = 60  # Timeout after 60 seconds of inactivity
        current_task = asyncio.current_task() # Get the current task

        # Register the task with the server
        with chat_server.lock:
            # Only register if server is running and user is considered active
            if chat_server.running and username in chat_server.users:
                chat_server.sse_tasks[username] = current_task
                print(f"SSE Task registered for user: {username}")
            else:
                # If server stopped or user unregistered before task could be added, cancel immediately
                print(f"Server stopped or user {username} not active during SSE task registration. Cancelling stream.")
                if current_task:
                    current_task.cancel() # Cancel self


        try:
            print(f"SSE stream opened for user: {username}")
            connection_count = 0
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
                
                # Check for connection timeout
                current_time = time.time()
                if current_time - last_activity_time > connection_timeout:
                    print(f"Connection timeout for {username}. Closing SSE stream.")
                    break
                
                messages = chat_server.get_messages(
                    username
                )  # Method handles its own lock

                if not chat_server.running:  # Double-check after getting messages
                    print("Server stopping, breaking SSE loop.")
                    break

                if messages:
                    data = json.dumps(messages)
                    yield f"data: {data}\n\n"
                    # Update activity time when data is sent
                    last_activity_time = time.time()
                    # print(f"Sent {len(messages)} messages to {username}") # Debug logging
                else:
                    # Send a keepalive comment periodically to prevent timeouts
                    # Increment connection count for timeout tracking
                    connection_count += 1
                    # Standard SSE keepalive comment - clients ignore this
                    yield ": keepalive\n\n"
                    
                    # Reset connection_count if it gets too large
                    if connection_count > 10000:
                        connection_count = 0

                # Use asyncio.sleep in async functions
                await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            # This happens if the client disconnects
            print(f"Client disconnected (SSE stream cancelled) for user: {username}")
        except Exception as e:
            print(f"Error in SSE stream for {username}: {e}")
        finally:
            # Clean up when the stream closes (normally or due to error/disconnect)
            print(f"SSE stream closing for user: {username}")
            # Remove task from tracking dict and unregister user
            with chat_server.lock:
                removed_task = chat_server.sse_tasks.pop(username, None)
                if removed_task:
                    print(f"SSE Task unregistered for user: {username}")
                # Unregister user if they are still in the users set
                # This handles cases like timeout or client disconnect cleanly
                if username in chat_server.users:
                     chat_server.users.remove(username)
                     print(f"User {username} unregistered due to SSE stream closure.")
                 # Optionally clear their message queue if desired upon disconnect
                 # if username in chat_server.clients:
                 #     chat_server.clients[username] = []

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

