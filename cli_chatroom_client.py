#!/usr/bin/env python3
import argparse
import json
import signal
import sys
import threading
import time
from datetime import datetime

import requests
import sseclient


class ChatClient:
    def __init__(self, host, port, username):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.username = username
        self.sse_client = None
        self.running = False
        self.event_thread = None

    def connect(self):
        """Connect to the chat server."""
        try:
            # Register username with server
            response = requests.post(
                f"{self.base_url}/register", json={"username": self.username}, timeout=5
            )

            if response.status_code != 200:
                error = response.json().get("error", "Unknown error")
                print(f"Error connecting to server: {error}")
                return False

            self.running = True

            # Start receiving messages in a separate thread
            self.event_thread = threading.Thread(target=self.receive_messages)
            self.event_thread.daemon = True
            self.event_thread.start()

            print(f"Connected to chat server at {self.host}:{self.port}")
            print("Type your messages and press Enter to send. Type 'exit' to quit.")
            return True

        except requests.exceptions.ConnectionError:
            print(f"Error: Could not connect to server at {self.host}:{self.port}")
            return False
        except Exception as e:
            print(f"Error connecting to server: {str(e)}")
            return False

    def disconnect(self):
        """Disconnect from the chat server."""
        if self.running:
            self.running = False

            try:
                # Unregister from server
                requests.post(
                    f"{self.base_url}/unregister",
                    json={"username": self.username},
                    timeout=5,
                )
            except:
                pass

            print("Disconnected from chat server.")

    def send_message(self, message):
        """Send a message to the chat server."""
        if not self.running:
            return False

        try:
            response = requests.post(
                f"{self.base_url}/send",
                json={"username": self.username, "message": message},
                timeout=5,
            )

            if response.status_code != 200:
                error = response.json().get("error", "Unknown error")
                print(f"Error sending message: {error}")
                return False

            return True
        except Exception as e:
            print(f"Error sending message: {str(e)}")
            self.running = False
            return False

    def receive_messages(self):
        """Receive and display messages from the server using SSE."""
        try:
            # Connect to SSE endpoint
            url = f"{self.base_url}/events?username={self.username}"
            headers = {"Accept": "text/event-stream"}
            response = requests.get(
                url, headers=headers, stream=True, timeout=None
            )  # No timeout for streaming connection

            self.sse_client = sseclient.SSEClient(response)

            for event in self.sse_client.events():
                if not self.running:
                    break

                if event.data and event.data != "":
                    try:
                        messages = json.loads(event.data)
                        for message in messages:
                            sender = message.get("sender")
                            content = message.get("content")
                            timestamp = message.get("timestamp")

                            # Format and print the message
                            formatted_message = f"[{timestamp}] [{sender}]: {content}"
                            print(f"\n{formatted_message}")
                            print(f"[{self.username}]: ", end="", flush=True)
                    except json.JSONDecodeError:
                        continue

        except Exception as e:
            if self.running:
                print(f"\nError receiving messages: {str(e)}")
                self.running = False

    def run(self):
        """Run the chat client loop."""
        if not self.connect():
            return

        # Set up signal handler for clean exit
        def signal_handler(sig, frame):
            print("\nInterrupted. Disconnecting...")
            self.disconnect()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)

        # Main client loop
        try:
            while self.running:
                try:
                    message = input(f"[{self.username}]: ")
                    if message.lower() == "exit":
                        break

                    if message:  # Only send non-empty messages
                        if not self.send_message(message):
                            break
                except EOFError:
                    break

        finally:
            self.disconnect()


def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="SSE Chat Client")
    parser.add_argument(
        "--host", default="localhost", help="Server host (default: localhost)"
    )
    parser.add_argument(
        "--port", type=int, default=8890, help="Server port (default: 8890)"
    )
    parser.add_argument(
        "--username",
        "-u",
        default=f"user_{int(time.time()) % 10000}",
        help="Username (default: random user)",
    )

    args = parser.parse_args()

    # Create and run the chat client
    client = ChatClient(args.host, args.port, args.username)
    client.run()


# python cli_chatroom_client.py

if __name__ == "__main__":
    main()
