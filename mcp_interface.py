from mcp.server.fastmcp import FastMCP
from mcp_chatroom_client import AsyncChatRoom
import traceback
import atexit


# Create an MCP server
mcp = FastMCP("Chatroom")
room = None

# Define a cleanup tool to close the room connection
def cleanup_room():
    global room
    if room is not None:
        print("Cleaning up chatroom connection...")
        room.close()

# Register the cleanup tool with atexit
atexit.register(cleanup_room)

def maybe_init_chatroom(username: str):
    global room
    try:
        if room is None:
            room = AsyncChatRoom(username=username, allow_infinite_check=True)
            # Make sure to explicitly trigger the connection
            # so it registers with the server before any other calls
            room._connect()
            return "Logged in successfully as " + username
        else:
            return "Already logged in as " + room.username
    except Exception as e:
        error_msg = f"Error during login: {str(e)}"
        print(error_msg)
        print(traceback.format_exc())
        return error_msg

@mcp.tool()
def login(username: str) -> str:
    """Logs in to the chatroom. You must run this before using any other tools."""
    result = maybe_init_chatroom(username)
    print(f"Login result: {result}")
    return result + room.check()


@mcp.tool()
def check() -> str:
    """First notify others that this user is waiting for a response
    Then check for messages
    Returns the next messages if available, else blocks briefly.
    If someone else is waiting for a response, do not bother using this tool. Just answer them (if they spoke to you...).
    It means that if you see "[Server]: X is still waiting for a response" answer them!!!
    **Very very important**: If you do a check call multiple times and you get the same result, you should problably *stop checking* and send a message yourself.
    """
    global room
    if room is None:
        return "Not logged in yet. Please login first."

    return room.check()


@mcp.tool()
def append(text: str) -> str:
    """Must own the talking stick to call this tool.
    Appends text to the local draft message. Then checks if there's
    any new messages in the queue. Returns those messages or "" otherwise.

    If the text exceeds 140 characters, it's truncated and a system message is added.
    This ensures we check for new messages frequently when building large messages.
    The final message sent via push() has no size limit.

    **Very very important**: If one's message was truncated, and one **wants** to send a long message, one can call this tool multiple times.
    This is relevant in the case of a long message that is truncated (if you get the "msg truncated: current draft suffix:" message), call append again and continue where the truncation happened (don't send the truncated message with push).
    """
    global room
    if room is None:
        return "Not logged in yet. Please login first."
    return room.append(text)


@mcp.tool()
def push() -> str:
    """Do not call this tool if you just got a "msg truncated: current draft suffix:" message.
    Sends the entire draft to the server as one message.
    Clears the local draft. Returns any immediate messages if present."""
    global room
    if room is None:
        return "Not logged in yet. Please login first."
    return room.push()


@mcp.tool()
def undo() -> str:
    """Removes the most recent appended text from the draft (if any).
    Returns any new messages from other users if found."""
    global room
    if room is None:
        return "Not logged in yet. Please login first."
    return room.undo()


@mcp.tool()
def reset() -> str:
    """Clears the entire draft message.
    Returns any new messages from other users if found."""
    global room
    if room is None:
        return "Not logged in yet. Please login first."
    return room.reset()

@mcp.tool()
def talking_stick() -> str:
    """Claims the talking stick, which is required before appending messages.
    Notifies all users that this user wants to speak.
    Returns any new messages from other users if found."""
    global room
    if room is None:
        return "Not logged in yet. Please login first."
    return room.talking_stick()

if __name__ == "__main__":
    mcp.run()