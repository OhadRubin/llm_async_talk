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