import argparse
import json
import signal
import sys
import threading
import time
import atexit
from datetime import datetime
from collections import deque
from typing import Optional
import requests
import sseclient


class AsyncChatRoom:
    """
    Implements an action-based chat client that uses the existing SSE chat server.
    Draft messages are stored locally.
    When 'push()' is called, the full draft is sent to the server.
    Incoming messages are captured via a background SSE listener thread.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8894,
        username: str = "Claude",
        max_append_length: int = 200,
    ):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.username = username
        self.max_append_length = (
            max_append_length  # Maximum length for a single append operation
        )

        self._draft_segments = []  # list of appended text pieces
        self._queue = deque()  # queue of new messages from other users
        self._running = False
        self._event_thread = None
        self._processed_messages = set()  # Track message IDs we've already processed
        self._has_talking_stick = False  # Flag to track if user has claimed the talking stick

        # Register cleanup function with atexit
        atexit.register(self.close)

    def _connect(self):
        """
        Registers user with the server and starts the background thread
        for receiving SSE events.
        """
        if self._running:
            return
        try:
            print(f"Registering user {self.username} with server...")
            r = requests.post(
                f"{self.base_url}/register", json={"username": self.username}, timeout=5
            )
            r.raise_for_status()
            print(f"User {self.username} registered successfully")

            # Get the list of participants
            try:
                users_response = requests.get(f"{self.base_url}/users", timeout=5)
                if users_response.status_code == 200:
                    users = users_response.json().get("users", [])
                    participants_msg = f"Current participants: {', '.join(users)}"
                    print(participants_msg)
                    self._add_system_message(participants_msg)
                else:
                    print(f"Failed to get participants list: HTTP {users_response.status_code}")
            except Exception as e:
                print(f"Error fetching participants: {e}")

            # Only start the SSE thread after successful registration
            self._running = True
            self._event_thread = threading.Thread(target=self._sse_listener, daemon=True)
            self._event_thread.start()
        except Exception as e:
            print(f"Failed to register with server: {e}")
            self._add_system_message(f"Failed to register with server: {e}")
            return

    def _disconnect(self):
        """Unregisters user from server and stops SSE loop."""
        if self._running:
            self._running = False
            try:
                requests.post(
                    f"{self.base_url}/unregister",
                    json={"username": self.username},
                    timeout=5,
                )
            except:
                pass

    def maybe_connect(self):
        """Decorator that ensures connection before running a method"""
        if not self._running:
            self._connect()

    def _sse_listener(self):
        """
        Background thread function that listens for new messages
        from the server via SSE. Any message from other users
        is saved in the queue for retrieval by check() or append() calls.
        """
        sse_url = f"{self.base_url}/events?username={self.username}"
        headers = {"Accept": "text/event-stream"}

        # Make sure we're registered before attempting to connect to the SSE stream
        try:
            print(f"Ensuring user {self.username} is registered before connecting to SSE...")
            r = requests.post(
                f"{self.base_url}/register", 
                json={"username": self.username}, 
                timeout=5
            )
            if r.status_code != 200:
                print(f"Registration failed with status {r.status_code}")
                # self._add_system_message(f"Initial registration failed: HTTP {r.status_code}")
        except Exception as e:
            print(f"Error during initial registration: {e}")
            # self._add_system_message(f"Initial registration error: {e}")

        while self._running:
            try:
                print(f"SSE listener starting for {self.username}")
                resp = requests.get(sse_url, headers=headers, stream=True)
                print(f"Got response status: {resp.status_code}")

                if resp.status_code == 403:
                    print("Got 403 Forbidden - need to register again")
                    self._add_system_message("Need to register again")

                    # Try to register again
                    try:
                        r = requests.post(
                            f"{self.base_url}/register", 
                            json={"username": self.username}, 
                            timeout=5
                        )
                        r.raise_for_status()
                        print(f"User {self.username} re-registered successfully")

                        # Get updated list of participants
                        try:
                            users_response = requests.get(f"{self.base_url}/users", timeout=5)
                            if users_response.status_code == 200:
                                users = users_response.json().get("users", [])
                                participants_msg = f"Current participants: {', '.join(users)}"
                                print(participants_msg)
                                self._add_system_message(participants_msg)
                        except Exception as e:
                            print(f"Error fetching participants: {e}")

                        time.sleep(1)  # Short delay before reconnecting
                        continue  # Try connecting again
                    except Exception as e:
                        print(f"Failed to re-register: {e}")
                        self._add_system_message(f"Failed to re-register: {e}")
                        time.sleep(3)  # Longer delay on registration failure
                        continue

                if resp.status_code != 200:
                    raise Exception(f"Failed to connect to SSE stream: HTTP {resp.status_code}")

                # Manual SSE parsing instead of using sseclient
                for line in resp.iter_lines():
                    if not self._running:
                        break

                    if not line:
                        continue

                    line = line.decode('utf-8')
                    print(f"SSE line: {line}")

                    if line.startswith('data: '):
                        data = line[6:]  # Skip 'data: ' prefix
                        if not data.strip():
                            continue

                        try:
                            messages = json.loads(data)
                            for msg in messages:
                                sender = msg.get("sender", "")
                                content = msg.get("content", "")

                                # Debug: print all incoming messages
                                print(f"DEBUG: Incoming message - sender: '{sender}', content: '{content}'")

                                # Skip our own messages
                                if sender == self.username:
                                    print(f"DEBUG: Skipping own message")
                                    continue

                                # Create a unique message ID
                                msg_id = f"{sender}:{content}"

                                # Skip if we've already processed this message
                                if msg_id in self._processed_messages and sender != "Server":
                                    continue
                                if sender == "Server" and "waiting" in content and self.username in content:
                                    continue

                                # Mark as processed and add to queue
                                self._processed_messages.add(msg_id)
                                self._queue.append(f"[{sender}]: {content}")

                                # Keep processed messages set from growing too large
                                if len(self._processed_messages) > 1000:
                                    # Just clear it - older messages won't be seen again anyway
                                    self._processed_messages.clear()

                        except json.JSONDecodeError as e:
                            print(f"JSON decode error: {e}, data: {data}")
                            continue
            except Exception as e:
                if not self._running:
                    break
                print(f"SSE listener error: {e}. Reconnecting in 2 seconds...")
                self._add_system_message(f"Connection error: {str(e)}. Reconnecting...")
                time.sleep(2)  # Wait before reconnecting
                continue  # Try to reconnect

        print(f"SSE listener stopped for {self.username}")

    def _add_system_message(self, message: str):
        """Add a system message to the queue"""
        msg_id = f"system:{message}"
        if msg_id not in self._processed_messages:
            self._processed_messages.add(msg_id)
            self._queue.append(f"[system] {message}")

    def _get_current_draft(self) -> str:
        """Get the current draft message as a single string"""
        return "".join(self._draft_segments).strip()

    def _poll_new_message(self, return_list: bool = False) -> Optional[str]:
        """
        Returns all the messages from other users if any is waiting; otherwise returns "".
        Does not block. You can adjust to block briefly if desired.
        """
        if self._queue:
            output = []
            while self._queue:
                content = self._queue.popleft()
                if content in output:
                    continue
                output.append(content)
            if return_list:
                return output
            else:
                return "\n".join(output)
        return ""

    def check(self) -> Optional[str]:
        """
        Sends a 'check' event to notify others that this user is waiting for a response.
        
        Then it is followed by a blocking check for new messages.

        Blocking check for new messages.
        Returns the next messages if available, else blocks briefly.
        If no new message arrives within a short interval, returns "".
        
        This method will:
        1. Ensure connection is established
        2. Poll multiple times with short delays to simulate blocking behavior
        3. Return any received messages or None if no messages
        
        Returns:
            Optional[str]: The received message(s) as a string, or None if no messages
        """
        # Ensure we're connected before checking messages

        self.maybe_connect()

        # Add a limit to avoid infinite loop
        delay = 2
        first_time = True

        while True:
            # Check for any new messages in the queue
            msg = self._poll_new_message()
            if len(msg) > 0:
                print(f"DEBUG: check() found message: {msg}")
                return msg

            # Sleep between polls to avoid busy waiting
            # Slightly longer delay between checks
            # Call the check event endpoint
            if not first_time:
                requests.post(
                    f"{self.base_url}/check_event",
                    json={"username": self.username, "delay": delay},
                    timeout=5,
                )
                

            time.sleep(delay)
            delay = 2 * delay
            first_time = False

    def talking_stick(self) -> Optional[str]:
        """
        Claims the talking stick, which is required before appending messages.
        Notifies all users that this user wants to speak.
        Returns any new messages from other users if found.
        """
        self.maybe_connect()

        try:
            # Reset the draft when claiming talking stick
            self._draft_segments.clear()

            # Call the talking_stick endpoint
            resp = requests.post(
                f"{self.base_url}/talking_stick",
                json={"username": self.username},
                timeout=5
            )
            resp.raise_for_status()

            # Set the flag indicating we have the talking stick
            self._has_talking_stick = True

            # Return any new messages
            return self._poll_new_message()
        except Exception as e:
            print(f"Failed to claim talking stick: {e}")
            self._add_system_message(f"Failed to claim talking stick: {str(e)}")
            return self._poll_new_message()

    def append(self, text: str) -> Optional[str]:
        """
        Appends text to the local draft message. Then checks if there's
        any new messages in the queue. Returns those messages or "" otherwise.

        Requires the talking stick to be claimed first through the talking_stick() method.
        If the text exceeds max_append_length, it's truncated and a system message is added.
        This ensures we check for new messages frequently when building large messages.
        The final message sent via push() has no size limit.
        """
        self.maybe_connect()

        # Check if we have claimed the talking stick
        if not self._has_talking_stick:
            err_msg = "You must claim the talking stick first by calling talking_stick()"
            print(err_msg)
            self._add_system_message(err_msg)
            return self._poll_new_message()

        # Check if the current append operation exceeds the maximum allowed length
        if len(text) > self.max_append_length:
            # Truncate the text to the maximum allowed length for this append operation
            truncated_text = text[: self.max_append_length]
            self._draft_segments.append(truncated_text)

            # Calculate the full draft for the preview message
            current_draft = self._get_current_draft()
            preview = current_draft[-50:] if len(current_draft) > 50 else current_draft

            # Add a system message about truncation
            self._add_system_message(
                f"msg truncated: current draft suffix: '{preview}'"
            )
        else:
            self._draft_segments.append(text)

        return self._poll_new_message()

    def push(self) -> Optional[str]:
        """
        Sends the entire draft to the server as one message.
        Clears the local draft. Returns any immediate messages if present.
        The complete message built from multiple append operations has no size limit.
        Releases the talking stick after sending.
        """
        self.maybe_connect()
        draft = self._get_current_draft()
        if draft:
            try:
                # Add our message to processed set to avoid seeing it again
                msg_id = f"{self.username}:{draft}"
                self._processed_messages.add(msg_id)

                requests.post(
                    f"{self.base_url}/send",
                    json={"username": self.username, "message": draft},
                    timeout=5,
                )
            except Exception as e:
                print(f"Failed to push message: {e}")
                self._add_system_message(f"Failed to send message: {str(e)}")

        # Release talking stick and clear draft
        self._has_talking_stick = False
        self._draft_segments.clear()
        return self._poll_new_message()

    def undo(self) -> Optional[str]:
        """
        Removes the most recent appended text from the draft (if any).
        Returns any new messages from other users if found.
        """
        self.maybe_connect()
        if self._draft_segments:
            self._draft_segments.pop()
        return self._poll_new_message()

    def reset(self) -> Optional[str]:
        """
        Clears the entire draft message.
        Releases the talking stick.
        Returns any new messages from other users if found.
        """
        self.maybe_connect()
        self._draft_segments.clear()
        self._has_talking_stick = False
        return self._poll_new_message()

    def close(self):
        """Call this when done to stop the SSE listener thread."""
        self._disconnect()
        if self._event_thread and self._event_thread.is_alive():
            self._event_thread.join(timeout=2)

    def __del__(self):
        """Destructor to clean up if close() wasn't called."""
        self.close()
