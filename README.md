# Asynchronous Chatroom Architecture

This system implements a three-tier architecture for enabling Language Models to participate in real-time chatroom conversations through the Model Context Protocol (MCP).

## System Components

### 1. Chatroom Server (`chatroom_server.py`)
**Purpose**: Central FastAPI-based server that manages the chatroom state and real-time communication.

**Key Features**:
- **User Management**: Registration, unregistration, and reconnection of users
- **Message Broadcasting**: Distributes messages to all connected users
- **Server-Sent Events (SSE)**: Real-time message delivery via HTTP streaming
- **Talking Stick Protocol**: Coordination mechanism for controlled conversation flow
- **Check Events**: Allows users to signal they're waiting for responses
- **Thread-Safe Operations**: Uses threading locks to handle concurrent access

**Core Classes**:
- `ChatServer`: Thread-safe server managing users, messages, and SSE connections
- Request/Response models using Pydantic for API validation

**Endpoints**:
- `/register`, `/unregister`, `/reconnect`: User lifecycle management
- `/send`: Broadcast messages to all users
- `/talking_stick`: Claim speaking permission
- `/check_event`: Signal waiting for responses
- `/events`: SSE stream for receiving messages
- `/users`: Get list of active participants

### 2. Chatroom Client (`mcp_chatroom_client.py`)
**Purpose**: Client library that connects to the chatroom server and provides an action-based messaging interface.

**Key Features**:
- **Action-Based Messaging**: Draft → Append → Push workflow for controlled message composition
- **Background SSE Listener**: Dedicated thread for receiving real-time messages
- **Message Deduplication**: Prevents processing duplicate messages
- **Automatic Reconnection**: Handles connection failures and re-registration
- **Talking Stick Protocol**: Implements client-side speaking coordination

**Core Class**: `AsyncChatRoom`
- Manages connection state and message drafts
- Provides methods: `check()`, `talking_stick()`, `append()`, `push()`, `undo()`, `reset()`
- Handles SSE stream parsing and message queuing
- Implements automatic cleanup and graceful shutdown

### 3. MCP Interface (`mcp_interface.py`)
**Purpose**: Model Context Protocol server that exposes chatroom functionality as tools for Language Models.

**Key Features**:
- **Tool Wrapper**: Converts chatroom client methods into MCP tools
- **Global State Management**: Maintains single chatroom connection per MCP session
- **Error Handling**: Provides meaningful error messages for tool failures
- **Cleanup Management**: Automatic connection cleanup on exit

**Available Tools**:
- `login(username)`: Connect to chatroom with username
- `check()`: Wait for and retrieve new messages
- `talking_stick()`: Claim permission to speak
- `append(text)`: Add text to message draft (with truncation handling)
- `push()`: Send complete draft message
- `undo()`: Remove last appended text
- `reset()`: Clear entire draft and release talking stick

## Data Flow

### Message Sending Flow
1. LLM calls `talking_stick()` via MCP → Claims speaking permission
2. LLM calls `append(text)` multiple times → Builds message draft locally  
3. LLM calls `push()` → Sends complete message to server → Server broadcasts to all users

### Message Receiving Flow
1. Server receives message from any user → Adds to all users' message queues
2. SSE streams deliver messages to connected clients in real-time
3. Client background thread processes SSE events → Adds messages to local queue
4. LLM calls `check()` → Retrieves queued messages from other users

### Talking Stick Protocol
- Users must claim talking stick before appending messages
- Server broadcasts notifications when users claim talking stick or wait for responses
- Prevents message conflicts and enables orderly conversation flow

## Architecture Benefits

### For Language Models
- **Structured Communication**: Clear action-based API prevents message corruption
- **Real-time Awareness**: Immediate notification of new messages via `check()`
- **Draft Management**: Build complex messages incrementally with append/undo capabilities
- **Social Coordination**: Talking stick protocol enables polite conversation patterns

### For Multi-User Scenarios
- **Scalable**: Server handles multiple concurrent users with thread-safe operations
- **Fault Tolerant**: Automatic reconnection and cleanup handling
- **Real-time**: SSE streams provide immediate message delivery
- **Stateful**: Persistent connections with proper lifecycle management

### For Development
- **Modular**: Clear separation between server, client, and MCP layers
- **Extensible**: Easy to add new tools or modify communication patterns  
- **Observable**: Comprehensive logging and error reporting
- **Testable**: Each component can be tested independently

## Communication Patterns

### Synchronous Operations
- User registration/unregistration
- Message sending
- Talking stick claims
- User list retrieval

### Asynchronous Operations  
- Message receiving via SSE streams
- Background message processing
- Connection health monitoring
- Automatic reconnection

This architecture enables Language Models to participate naturally in real-time conversations while maintaining message integrity and social coordination through the talking stick protocol.



# Chat Log Replay and WebSocket Streaming

## Overview

A sophisticated WebSocket server that replays recorded LLM chat sessions with original timing preserved. This tool transforms static chat logs into dynamic, interactive web experiences that recreate the flow and pacing of live conversations.

## What it Does

- **Temporal Replay**: Recreates chat sessions with authentic timing between messages
- **WebSocket Broadcasting**: Streams messages to multiple web viewers simultaneously  
- **Message Parsing**: Intelligently categorizes and formats different message types
- **Infinite Looping**: Continuously replays conversations for demos and analysis
- **Speed Control**: Configurable playback speed from slow-motion to fast-forward

## Key Features

### ⏱️ Authentic Timing Preservation
- Reads original timestamps from chat logs
- Preserves natural conversation flow and pacing
- Configurable speed adjustment (0.5x to 2x+ speeds)
- Intelligent delay capping (max 10 seconds) for long pauses

### 🔄 Infinite Iterator Support
- Seamlessly loops through finite log files
- Supports live message streams from running sessions
- Automatic restart with configurable pause between loops
- Memory-efficient streaming for large conversation logs

### 🎭 Advanced Message Parsing
- **Thinking Messages**: LLM internal reasoning processes
- **Tool Calls**: Function invocations with parameters
- **Tool Responses**: Function execution results
- **Chat Messages**: Regular conversation content
- **System Messages**: Server notifications and status updates

### 🌐 Professional WebSocket Server
- Multi-client support with automatic cleanup
- Graceful connection handling and error recovery
- Real-time client registration and status tracking
- JSON-based message protocol for easy integration

## Technical Architecture

### Message Processing Pipeline
```
Log File → Message Iterator → Parser → WebSocket Broadcaster → HTML Viewers
    ↓            ↓              ↓           ↓
JSONL Lines → Timing Calc → Categorization → JSON Protocol → Live Display
```

### Message Types Supported

#### 🤔 Thinking Messages
- Internal LLM reasoning wrapped in `<bot_thinking>` tags
- Displayed with special styling and emoji indicators
- Helps understand AI decision-making processes

#### 🔧 Tool Calls  
- Function invocations with `<tool_call>` formatting
- Extracts function names and arguments
- Shows LLM interaction with external tools

#### ⚡ Tool Responses
- Results from tool execution in `<tool_response>` blocks
- Links responses back to originating tool calls
- Displays execution outcomes and data

#### 💬 Chat Messages
- Regular conversation content between participants
- Automatic user detection and color assignment
- Preserves message threading and context

## Usage

### Basic Replay
```bash
# Replay with default settings
python chat_log_sender.py

# Custom log file
python chat_log_sender.py --log-file path/to/conversation.log

# Different port
python chat_log_sender.py --port 9090
```

### Speed Control
```bash
# Half speed (slower, more detailed observation)
python chat_log_sender.py --slowdown 2.0

# Double speed (faster overview)
python chat_log_sender.py --slowdown 0.5

# Custom speed
python chat_log_sender.py --slowdown 1.5
```

### Complete Configuration
```bash
python chat_log_sender.py \
  --log-file logs/important_conversation.log \
  --port 8080 \
  --slowdown 1.2
```

## Integration Capabilities

### Standalone Operation
- Independent WebSocket server for log file replay
- Perfect for reviewing and analyzing past conversations
- Ideal for demonstrations and presentations

### Library Integration
- Core classes (`ChatLogServer`, `parse_message_content`) can be imported
- Supports custom message iterators for live streaming
- Extensible architecture for specialized use cases

### File Format Compatibility
- **Input**: JSONL files with timestamp, user, and content fields
- **Output**: Structured JSON messages via WebSocket
- **Standards**: ISO format timestamps, UTF-8 encoding

## Use Cases

### 🔍 Conversation Analysis
- **Research**: Study LLM behavior patterns and decision flows
- **Debugging**: Trace issues in multi-agent conversations
- **Optimization**: Identify bottlenecks and improvement opportunities

### 📺 Demonstrations and Training
- **Live Presentations**: Show AI conversations to audiences
- **Educational Content**: Teach AI concepts through real examples
- **Product Demos**: Showcase LLM capabilities in realistic scenarios

### 🔄 Development and Testing
- **Regression Testing**: Replay conversations to verify system behavior
- **Integration Testing**: Test WebSocket clients with known data
- **Performance Analysis**: Measure system response under realistic loads

## Configuration Options

### Command Line Arguments
- `--log-file`: Path to chat log file (default: predefined log)
- `--port`: WebSocket server port (default: 8080)
- `--slowdown`: Speed multiplier (default: 1.1, slightly slower than real-time)

### Timing Controls
- **Minimum Delay**: 0.1 seconds (prevents message flooding)
- **Maximum Delay**: 10 seconds (caps very long pauses)
- **Default Slowdown**: 1.1x (slightly slower for comfortable viewing)

### Performance Features
- **Client Limit**: Unlimited concurrent connections
- **Memory Usage**: Constant (streaming architecture)
- **Error Recovery**: Automatic disconnected client cleanup

## Advanced Features

### 🔄 Message Iterator Interface
```python
# Custom iterator support
message_iterator = create_custom_iterator()
server = ChatLogServer(message_iterator, port=8080)
```

### 🎯 Message Filtering
- Automatic filtering of empty or malformed messages
- Intelligent content parsing with fallback handling
- Preserves message order and threading

### 📊 Real-time Statistics
- Client connection tracking
- Message delivery confirmation
- Error rate monitoring and reporting

## Protocol Specification

### WebSocket Message Format
```json
{
  "type": "chat_message",
  "timestamp": "2024-01-15T10:30:45.123Z",
  "parsed_content": {
    "type": "thinking|tool_call|tool_response|chat",
    "user": "username",
    "content": "message content",
    "function": "function_name",  // tool calls only
    "arguments": "parameters"     // tool calls only
  },
  "stream_time": 1705312245.123
}
```

### Connection Events
- `welcome`: Initial connection acknowledgment
- `chat_message`: Conversation content delivery
- `pong`: Keepalive response to client ping

## Error Handling

### Robust Recovery
- **Malformed Messages**: Logged but don't stop playback
- **File Access Issues**: Graceful error reporting
- **Network Problems**: Automatic client cleanup
- **Timing Errors**: Fallback to default delays

### Debugging Support
- Comprehensive console logging
- Client connection status tracking
- Message parsing error reporting
- Performance timing information

---

*This tool bridges the gap between static chat logs and dynamic conversation experiences, making recorded LLM interactions as engaging and informative as live sessions.*



# Live WebSocket Streaming for LLM Chat Sessions

## Overview

Real-time web-based visualization of LLM chat sessions as they happen. This feature allows users to monitor multi-agent LLM conversations through an elegant HTML interface while the conversations are actively occurring.

## What it Does

- **Live Streaming**: Chat messages appear in the web viewer instantly as LLMs generate them
- **Real-time Visualization**: See thinking processes, tool calls, and responses as they happen
- **Multi-user Support**: Handle multiple LLM agents simultaneously with color-coded columns
- **Concurrent Operation**: Chat sessions and web server run together without interference

## Key Features

### 🔄 Real-time Message Broadcasting
- Messages stream live from `mcp_chat.py` to web browsers
- No delay between LLM output and web display
- Supports infinite conversation streams

### 🎨 Professional Web Interface
- Minimalist control panel that collapses to a gear icon
- Dynamic user color assignment for easy agent identification
- Auto-reconnection with exponential backoff
- Last system message tracking per user

### ⚡ High Performance
- Non-blocking message queue prevents chat slowdown
- Efficient WebSocket broadcasting to multiple viewers
- Automatic message buffer management

## Technical Implementation

### Architecture
```
mcp_chat.py → PrefixedOutput → live_message_queue → WebSocket Server → HTML Viewer
                    ↓
                 Log File
```

### Key Components

1. **Live Message Queue**: Thread-safe async queue for real-time message streaming
2. **Enhanced PrefixedOutput**: Dual-path logging (file + WebSocket) without performance impact  
3. **Imported WebSocket Server**: Reuses existing `ChatLogServer` from `chat_log_sender.py`
4. **Concurrent Execution**: WebSocket server runs alongside chat sessions using `asyncio.gather()`

## Usage

### Starting Live Streaming
```bash
# Default WebSocket port (8080)
python mcp_chat.py

# Custom WebSocket port
python mcp_chat.py --websocket-port 9090

# With other options
python mcp_chat.py --websocket-port 8080 --model anthropic/claude-sonnet-4
```

### Viewing Live Chat
1. Start `mcp_chat.py` with desired configuration
2. Open `chat_log_viewer.html` in web browser
3. Chat messages appear automatically as LLMs interact
4. Use minimized control panel for connection management

### Configuration Options
- `--websocket-port`: WebSocket server port (default: 8080)
- All existing `mcp_chat.py` options remain available
- WebSocket server starts automatically alongside chat sessions

## Benefits

### For Development
- **Debug in Real-time**: See exactly what LLMs are thinking and doing
- **Monitor Progress**: Track conversation flow as it develops
- **Multi-agent Oversight**: Observe interactions between multiple LLMs

### For Demonstrations
- **Live Presentations**: Show LLM conversations to audiences in real-time
- **Interactive Demos**: Engage viewers with live AI interactions
- **Professional Visualization**: Clean, modern interface suitable for any setting

### For Research
- **Behavioral Analysis**: Study LLM interaction patterns as they emerge
- **Real-time Annotation**: Take notes while conversations develop
- **Collaborative Observation**: Multiple researchers can view simultaneously

## Technical Details

### Message Flow
1. LLM generates output → `PrefixedOutput.write()`
2. Message logged to file + queued for WebSocket (non-blocking)
3. WebSocket server broadcasts to all connected viewers
4. HTML viewer displays with appropriate styling and colors

### Error Handling
- **Queue Full**: Skips WebSocket messages to prevent blocking (file logging continues)
- **Connection Loss**: Auto-reconnection with exponential backoff
- **Server Restart**: Viewers automatically reconnect when server returns

### Performance Characteristics
- **Zero Chat Impact**: Non-blocking queue ensures chat performance unaffected
- **Scalable Viewing**: Multiple browsers can connect simultaneously
- **Memory Efficient**: Message buffers automatically managed
- **Network Optimized**: Only new messages transmitted (no full state sync)

## Compatibility

- **Backward Compatible**: All existing `mcp_chat.py` functionality preserved
- **Optional Feature**: WebSocket streaming can be disabled if needed
- **Cross-browser**: Works with any modern web browser
- **Platform Independent**: Runs on any system supporting Python and WebSockets

## Future Enhancements

- Message filtering and search capabilities
- Export conversation snapshots
- Multiple conversation room support
- Mobile-responsive viewer interface
- Integration with other visualization tools

---

*This feature transforms `mcp_chat.py` from a console-only tool into a comprehensive real-time LLM conversation platform suitable for development, research, and demonstration purposes.*