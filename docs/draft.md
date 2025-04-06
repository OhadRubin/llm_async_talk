Please implement the client interface in python such that we would be able to do the following. You should use the existing server and only modify the client.py file.

usage:
```

chatroom = AsyncChatRoom()

cool_new_app_description = open("cool_new_app_desc.txt", "r").read()
print(len(cool_new_app_description)) # 100000
print(cool_new_app_description[:100]) # prints "This innovative app revolutionizes task management with AI-powered scheduling, smart notifications, and seamless integrati"
print(chatroom.check()) # prints "ChatGPT: anyone here?"
print(chatroom.append("yeah, i'm here")) #prints nothing
print(chatroom.push()) #prints nothing
print(chatroom.append("what's up?")) #prints nothing
print(chatroom.push()) #prints nothing
print(chatroom.check()) #prints "ChatGPT: oh, hi claude, what are you up to?"
print(chatroom.append("nothing much")) #prints "ChatGPT: did anything interesting recently?"
print(chatroom.undo()) #prints nothing
print(chatroom.append("I started using this cool app.")) 
print(chatroom.append(cool_new_app_description)) #prints "[system] msg truncated: current draft suffix: 'I started using this cool app. This innovative app revolutionizes task management'"
print(chatroom.push()) #prints nothing
```




# Reimagining LLM Conversations with Git-Inspired Action Protocols

## 1. Introduction

We are building a chat app for LLMs with an action-based approach for enabling continuous and asynchronous communication between language models. This approach is particularly useful for complex discussions where LLMs might need to adjust their responses based on new information that arrives during response generation.

The reasoning behind this design is that whenever an LLM performs certain actions, we can additionally check if it received any recent messages. This way, we can allow LLMs to speak in an asynchronous fashion, creating a more natural conversational flow where participants can "want to say something" or "want to wait for the other person to say something."

## 2. The Core Actions

Our protocol implements five key actions that enable this flexible conversation style:

1. **Append action** - (Non-blocking) Appends text to the current draft message (with a length maximum, but not necessarily for the entire message)
2. **Undo action** - (Non-blocking) Reverts the most recent commit/append operation
3. **Push action** - (Blocking) Sends the entire built-up message to the recipient
4. **Reset action** - (Non-blocking) Discards the entire draft message and starts fresh
5. **Check actions** - (Blocking) Waits for new messages

This design creates a two-step communication process (commit then push), which allows the LLM to:
- Prepare a message in segments
- The protocol automatically checks for any incoming messages before actually sending
- Potentially revise the committed message if new information arrives
- Only send when ready with the push action

## 3. Benefits of the Action-Based Architecture

This approach gives fine-grained control over the conversation flow while allowing for asynchronous communication. It's particularly beneficial for LLMs that might need to build up longer responses in chunks while maintaining the ability to check for new incoming messages between commits. The LLM could:

1. Commit part of a response
2. Check if any new messages arrived
3. Either continue with more commits to complete the response, or
4. Reset if the new information makes the current draft obsolete

The key benefits of this system include:

1. More natural conversational flow where models can "interrupt" themselves to respond
2. Ability to check for new information before sending a complete thought
3. More thoughtful responses as models can revise before pushing

## 4. Implementation Considerations

Some important implementation considerations that help refine this approach:

- What happens if an LLM tries to push without committing first? (should be rejected)
- Is there a way for LLMs to see a preview of their committed message before pushing? (yes)
- Can multiple messages be committed before pushing, or does push always send the most recent commit? (push always sends the most recent commit)
- How do you handle the length maximum for commit messages - truncation or rejection? (notify the LLM that it was truncated)

This approach reminds me of Git's commit/push workflow, which makes it intuitive for developers. It's a clever way to give LLMs more control over their communication timing.

## 5. The Interruption Pattern

The interruption pattern allows LLMs to be interrupted between commit and push actions during parallel conversations. This pattern prevents message crossing, enables real-time information integration, and creates natural conversation flow by letting participants adjust their responses dynamically.

## 6. Simulated Conversation Example

Here's how a conversation might flow with this system:

```
Claude: [commits] The fundamental challenge with quantum computing is maintaining coherence long enough to—
// System automatically checks for new messages, none found

GPT: [commits] I believe the decoherence problem in quantum systems could potentially be addressed by—
GPT: [pushes]
// System automatically delivers GPT's message to Claude

// Claude's system automatically notifies Claude of the new message right after its commit action
Claude: [receives GPT's message immediately after committing]
Claude: [commits] —actually, I just saw your message about decoherence. I agree with your approach but would add that recent advances in error correction suggest—
Claude: [pushes]
```

Server-side events handle automatic message checking and delivery after each action, eliminating the need for explicit checks by LLMs.

## 7. Applications and Use Cases

This dynamic would be particularly interesting in scenarios where:

1. The LLMs are debating complex topics and need to respond to nuanced points
2. They're collaboratively solving problems where new insights change the direction

## 8. Conclusion

The "listening while writing" capability enables fluid, natural LLM conversations by eliminating rigid turn-taking. This creates a reactive environment for immediate responses and dynamic conversation flow, making interactions feel more authentic.




# LLM Conversation Action Protocol API Specification

This document specifies the JSON-RPC API for the git-inspired action protocol that enables asynchronous LLM conversations.

## API Overview

The protocol implements five key actions:

1. **Append** - Non-blocking: Adds text to the current draft message
2. **Undo** - Non-blocking: Reverts the most recent append operation
3. **Push** - Blocking: Sends the complete draft message to recipient
4. **Reset** - Non-blocking: Discards the draft message and starts fresh
5. **Check** - Blocking: Waits for new messages

## Method Specifications

Message object:
{
  "message_id": "msg-345678",
  "sender_id": "llm-456",
  "content": "I believe the decoherence problem in quantum systems could potentially be addressed by—",
  "timestamp": "2023-07-15T14:21:55Z"
}



### append

Appends text to the current draft message.

**Parameters:**
- `text` (string, required): Text to append to the current draft. Has a length limit of 1000 characters.

**Returns:**
- `status` (integer): Operation status (1 if we successfully appended the text, 2 if we partially appended the text, 0 otherwise)
- `suffix` (string): The suffix of the current draft
- `messages` (array): Array of new message objects

**Example Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "append",
  "params": {
    "text": "The fundamental challenge with quantum computing is maintaining coherence long enough."
  },
  "id": 1
}
```

**Example Response:**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "success": 1,
    "suffix": "is maintaining coherence",
    "messages": []
  },
  "id": 1
}
```

### undo

Reverts the most recent append operation.

**Parameters:**
- None required

**Returns:**
- `status` (int): Operation status
- `messages` (array): Array of new message objects

**Example Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "undo",
}
```

**Example Response:**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "status": 1,
    "suffix": "is maintaining coherence",
    "messages": [...]
  },

}
```

### push

Sends the complete draft message to the recipient.

**Parameters:**
- None required

**Returns:**
- `status` (int): Operation status
- `messages` (array): Array of new message objects


**Example Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "push",
  "params": {},
  "id": 3
}
```

**Example Response:**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "status": 1,
    "message_id": "msg-789012",
    "timestamp": "2023-07-15T14:22:07Z"
  },
  "id": 3
}
```

### reset

Discards the entire draft message and starts fresh.

**Parameters:**
- None required

**Returns:**
- `status` (int): Operation status

**Example Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "reset",
  "params": {},
  "id": 4
}
```

**Example Response:**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "status": 1
  },
  "id": 4
}
```


## Error Codes

| Code | Message | Meaning |
|------|---------|---------|
| -32600 | Invalid Request | The JSON sent is not a valid Request object |
| -32601 | Method not found | The method does not exist / is not available |
| -32602 | Invalid params | Invalid method parameter(s) |
| -32603 | Internal error | Internal JSON-RPC error |
| 40001 | No draft exists | Push attempted without any content in draft |
| 40003 | Rate limit exceeded | Too many requests in given time period |
| 40004 | Content policy violation | Content violates usage policies |

## Implementation Notes

1. All actions automatically check for incoming messages between operations.
2. Push is rejected if no content has been appended.
3. The system handles message delivery and notification automatically.
4. Length limits for appended text are handled through truncation with notification.
5. Session management will be implemented separately with the SSE connection. 




  