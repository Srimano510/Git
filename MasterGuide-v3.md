# Executive Summary

We will build a **toggleable context-construction system** for an AI chat agent: one mode uses the classic linear history window, the other uses a **Context Graph** of the conversation. The goal is to **incrementally implement and demonstrate** how representing the chat history as a graph (with branching, merging, summaries, etc.) can enable more selective and explainable context retrieval. Throughout, we maintain a **baseline** (linear) engine so that every change can be compared. The final product is a demonstrable agent with:

- A **Graph-based context engine** alongside the linear mode.
- UI controls: a **toggle** between context modes, a **branch** button under each message (to fork the conversation), and a **copy** button.
- A **Context Observatory** panel showing which nodes were used, token counts, metrics (retrieval time, relevant vs irrelevant nodes, etc.), and the differences between modes.
- Instrumentation to log performance metrics and save intermediate states (for resumption).

The project unfolds in **phases (Layer 1..6)**, each with clear objectives, tasks, and deliverables. At each phase we introduce one concept or feature (e.g. graph data model, context traversal, vector search) and verify it before moving on. This ensures the agent always has a working context path (the “control” path) and we evolve only the experimental path. 

Key references guiding our design are the **Context Graph** paradigm (graph is a knowledge structure optimized for LLMs) and the **ThoughtDAG** idea (explicit graph edges determine exactly what the model sees). We also adapt ideas from [HKUDS/nanobot](https://github.com/HKUDS/nanobot) (branching, context compaction) and hybrid retrieval research.

The following sections detail **Project Goal**, **Requirements**, and **Proposed Phased Path**, then break down each phase with objectives, deliverables, step-by-step instructions, data schemas, tests, expected outputs, failure modes, instrumentation, and a **[DO THIS]** prompt guiding the agent’s work.

---

## Project Goal

- **Goal:** Demonstrate a conversation context system in which the agent can switch between linear-history retrieval and a rich **graph-based context graph** (or eventually a full Context-Aware Workflow DAG). Show how the graph enables branching conversation threads, multi-parent context merging, semantic search, and summarization for scalable retrieval. 

- **Research Question:** Can representing chat as a graph (rather than a flat transcript) yield better or more controllable context assembly for LLM prompts?

- **Approach:** Build an experimental “A/B” style agent. One path (the control) uses the existing linear context window. The other path (the experiment) uses an evolving graph context engine. Provide tools (UI toggle, dashboards, metrics) to compare them live.

- **Demonstration:** Show the same user query answered under *Linear* vs *Graph* context. For example, a branching conversation about API design (REST vs GraphQL) should retrieve only relevant branches in graph-mode. Display side-by-side context differences, token usage, and answer quality. 

---

## Requirements

We gather requirements from the project description and existing docs. Each is unambiguous:

- **Conversation Graph**: A data model to store each prompt/response as a **node**, with **typed edges** (e.g. REPLY, BRANCH, SUMMARY, CONTEXT, REFERENCE). Nodes have attributes: `id`, `role` (user/assistant/system), `content`, `timestamp`, optional `embedding` or summary. Edges have `source`, `target`, `type`.

- **Branching**: At any message node, the user can click a **“Branch”** button. This creates a new “branch” of the conversation by copying the context up to that node. Implementation: clone the node (or mark it as a branching point) and continue from there. (In graph terms, simply add new edges without altering old ones.)

- **Copy Button**: A button to copy the message text to clipboard (already in many UIs, but included for completeness).

- **Toggle Context Mode**: A UI toggle (e.g. switch or radio button) to select between *Linear* or *Graph* context. This controls which **ContextEngine** is used. Both engines share the same chat interface and bot logic, but differ in how they build the prompt.

- **Linear Context Engine (baseline)**: The classic mode that takes the *N* most recent messages (user + assistant) and discards earlier history.

- **Graph Context Engine (experimental)**: Builds context by traversing the conversation graph, following edges up (and optionally sideways via semantic links), applying token limits, etc.

- **Typed Edges & Semantic Links**: Support edges that indicate different relationships. For example: 
  - `REPLY`: answer to a question.
  - `BRANCH`: start of a new branch.
  - `CONTEXT`: implied context link (maybe same branch continuation).
  - `SUMMARY`: from a node to its summary node.
  - `REFERENCE`: pointing to related but non-sequential nodes.

- **Summarization Nodes**: Ability to insert nodes that contain summaries of subgraphs. The context resolver may include a summary node instead of many detailed nodes to save tokens.

- **Vector/Semantic Retrieval**: Given a query or current node, support retrieving additional relevant nodes by **vector embedding search** in a local index. This is an extension; not required at the very start, but to be added later. 

- **Token Budgeting**: The context engine must respect LLM token limits. It should rank and prune nodes until within budget. Metrics should report how many tokens were used from history vs budget.

- **Context Observatory (Floating Inspector)**: An overlay/panel in the UI that shows:
  - Which nodes were retrieved for context (IDs and content).
  - **Why** each node was included or excluded (edge type, recency, semantic score, branch filter).
  - Token counts breakdown (recent vs graph vs summary).
  - Performance metrics: retrieval time, ranking time, etc.
  - A *comparison view* highlighting differences when toggling modes.

- **Performance Metrics Logging**: Instrumentation to measure and log:
  - Context retrieval latency.
  - Number of nodes/tokens retrieved.
  - Recall of relevant nodes vs total (ideally manually labeled in tests).
  - (Later) answer quality metrics if needed.
  These should be logged (e.g. to console or file) at runtime for each query.

- **Persistence**: The conversation graph should be saved to disk (serialized as JSON) periodically and reloaded. Each session has its own graph file. This enables crash recovery and long-term memory.

- **Integration with HKUDS/nanobot**: The system should slot into the nanobot framework (or similar agent). In practice, we’ll modify the context-building step of the agent: the WebUI/terminal is unchanged except for adding the toggle/buttons. We’ll reuse nanobot’s session and workspace handling, plus any existing context compaction hooks if helpful.

- **Modular Implementation**: The design should separate the *data model* (nodes/edges/graph) from the *context engine* (retrieval logic). That way we can plug the graph engine into any agent, and easily compare against the baseline.

Additional (optional) ideas (for on-demand extension):
- **Multiple Context Strategies**: More modes beyond Linear/Graph (e.g. Graph+Vector). 
- **Chat-Pair Strategy**: Another axis to toggle not just history vs graph, but different filtering rules.
- **Presentation Slides**: Prepare a final slide deck outline summarizing problem, solution, and demo results.

> **Performance note:** Early phases should not introduce heavy dependencies like Neo4j, Kafka, Kubernetes, or machine learning. Use plain Python structures, local embeddings (or small Faiss index), and simple web frameworks (the existing nanobot WebUI is fine). Later, these could be replaced by production components if needed.

### Repository-Specific Integration Contract — `Srimano510/Git`

> **Target repository:** `https://github.com/Srimano510/Git`, branch `master`, as inspected on 2026-09-18.
>
> This section specializes the guide for the current repository. **The original guide remains the conceptual specification.** When an earlier pseudocode example suggests creating a parallel chat/session implementation, prefer the repository-native integration points below. Do not replace working nanobot session, WebUI, routing, security, or persistence behavior merely to match a simplified example in this document.

#### Current repository shape that this guide must preserve

The repository is already a nanobot application, not a blank project. The relevant existing areas are:

```text
Srimano510/Git
├── nanobot/                  # Python runtime/package
│   ├── agent/
│   │   ├── context.py        # ContextBuilder / TranscriptInput
│   │   └── loop.py           # turn lifecycle and transcript input
│   ├── session/
│   │   └── manager.py        # Session / SessionManager / JSONL persistence
│   ├── runtime_context.py    # per-turn runtime context metadata
│   └── ...
├── webui/                    # React/TypeScript browser UI
│   └── src/
│       ├── App.tsx
│       ├── components/thread/
│       │   ├── ThreadShell.tsx
│       │   ├── ThreadViewport.tsx
│       │   └── ...
│       └── lib/api.ts
├── tui/
├── tests/
├── docs/
└── pyproject.toml
```

`pyproject.toml` defines the package as `nanobot-ai`, requires Python 3.11+, exposes the `nanobot` CLI, and includes the WebUI build in the Python distribution.

#### Existing context path — extend this path instead of building a second agent pipeline

The current repository already separates persisted conversation history from final prompt assembly:

```text
Inbound message
    ↓
nanobot/agent/loop.py
    ↓
Session.add_message(...) + SessionManager.save(...)
    ↓
Session.get_history(...)
    ↓
TurnContext.history
    ↓
AgentLoop._build_transcript_input(...)
    ↓
TranscriptInput(history=..., current_message=...)
    ↓
nanobot/agent/context.py
ContextBuilder.build_transcript(...)
    ↓
system prompt + selected history + fresh current message
    ↓
AgentRunner / provider
```

Therefore, the graph experiment should hook into the **history-selection boundary before `ContextBuilder.build_transcript()`**, while leaving `ContextBuilder` responsible for constructing the model transcript. Do not duplicate system-prompt construction, skill injection, runtime-context handling, attachment handling, or provider invocation inside a new context engine.

#### Existing session model — preserve it

`nanobot/session/manager.py` already provides:

- `Session.messages` as the canonical in-memory message history.
- `Session.add_message(...)` to append persisted messages.
- `Session.get_history(...)` to return a legal replay slice while respecting compaction/checkpoint boundaries, tool-call boundaries, runtime-context visibility, and token/message limits.
- JSONL-backed session persistence outside the agent workspace.
- Existing session metadata and recovery behavior.

**Repository rule:** `LinearContextEngine` must use repository-native replay semantics rather than reimplementing `list(graph.nodes.values())[-N:]`. In this repository, the true baseline is the current `Session.get_history(...)` behavior.

This matters because the simplified `last N nodes` pseudocode elsewhere in this document does not know about tool-call/result pairing, archived checkpoints, hidden continuation markers, runtime context, media breadcrumbs, or other nanobot-specific replay rules.

#### Existing branch behavior — reuse it

The current WebUI already has a fork/branch path:

```text
App.tsx
  onForkChat
      ↓
ThreadShell.tsx
      ↓
ThreadViewport.tsx
  onForkFromMessage(beforeUserIndex)
      ↓
existing WebUI/session fork operation
      ↓
new independent nanobot session seeded from the chosen history boundary
```

`ThreadViewport` already carries `forkBoundaryMessageCount` and `onForkFromMessage`, and `App.tsx` passes `onForkChat` into `ThreadShell`.

**Repository rule:** do not add a second, competing branch implementation that merely sets an in-memory `active_node_id`. Adapt the graph layer to the existing fork semantics:

- A forked chat remains a distinct nanobot session.
- Graph lineage may span more than one session.
- Record the relationship between the source session/boundary and the child session as a graph `BRANCH` edge.
- The first new message in the child session continues from that inherited boundary.
- Preserve existing WebUI fork UX and session recovery behavior.

A useful graph-level representation is:

```json
{
  "graph_id": "g_...",
  "nodes": [
    {
      "id": "node_...",
      "session_key": "websocket:source-chat",
      "message_index": 14,
      "role": "assistant",
      "content": "..."
    },
    {
      "id": "node_...",
      "session_key": "websocket:forked-chat",
      "message_index": 15,
      "role": "user",
      "content": "Try the other approach."
    }
  ],
  "edges": [
    {
      "source": "node_source_boundary",
      "target": "node_first_child_message",
      "type": "BRANCH"
    }
  ]
}
```

#### WebUI display state is not the same thing as model context

The WebUI has a disk-backed display-thread API (`fetchWebuiThread(...)` in `webui/src/lib/api.ts`) that is intentionally separate from the agent session transcript.

**Repository rule:** the Context Graph must derive model-history facts from the agent/session layer, not from rendered browser bubbles. The WebUI may visualize graph data, but it must not become the source of truth for context assembly.

#### Recommended module placement

Add the experiment as a cohesive Python package instead of scattering graph logic across `loop.py`, `context.py`, and UI handlers:

```text
nanobot/context_graph/
├── __init__.py
├── model.py          # ChatNode, ChatEdge, ConversationGraph, enums
├── store.py          # graph persistence + lineage/session mapping
├── engines.py        # LinearContextEngine, GraphContextEngine
├── traversal.py      # ancestor / merge traversal
├── ranking.py        # token budget + scoring
├── vector.py         # optional semantic index, Phase 4
├── summaries.py      # summary-node policy, Phase 4
└── observability.py  # ContextResult + metrics/reasons, Phase 6
```

Suggested tests:

```text
tests/context_graph/
├── test_model.py
├── test_store.py
├── test_linear_engine.py
├── test_graph_engine.py
├── test_branch_lineage.py
├── test_budgeting.py
├── test_vector_index.py
└── test_observability.py
```

The filenames are recommendations; adapt them if the repository already has a more appropriate local naming convention by the time implementation begins.

#### Strategy state and compatibility contract

Use an explicit strategy value, for example:

```python
ContextStrategy = Literal["linear", "graph", "graph_vector"]
```

Persist the selected strategy as session/chat metadata or another repository-native per-chat setting so it survives WebUI refreshes. Default to `"linear"` for existing sessions and for any unknown/corrupt value.

The strategy switch must change **history selection only**. All later behavior remains shared:

```text
                         ┌─ LinearContextEngine ─┐
Session + current turn ──┤                       ├─ selected history
                         └─ GraphContextEngine ──┘
                                      ↓
                         ContextBuilder.build_transcript()
                                      ↓
                              AgentRunner/provider
```

#### Node identity and synchronization

Do not use list position alone as the permanent node ID. Session history can be compacted, migrated, forked, or restored.

For the experiment, assign graph node IDs when messages are synchronized into the graph, and retain provenance such as:

```python
ChatNode(
    id="node_<uuid>",
    role="user",
    content="...",
    timestamp="...",
    session_key="websocket:...",
    session_message_index=42,
    turn_id="...",          # when available
    message_id="...",       # when available
    metadata={...},
)
```

Maintain an idempotent mapping so reloading an existing session does not create duplicate graph nodes.

#### Persistence boundary

Do **not** store graph files in the selected project workspace merely because the graph belongs to a chat. Nanobot deliberately keeps canonical session storage outside the agent-accessible workspace.

Prefer a runtime/config-owned sidecar location, conceptually:

```text
<config-runtime>/context-graphs/<workspace-id>/<graph-id>.json
<config-runtime>/context-graphs/<workspace-id>/<graph-id>.vectors
```

The exact path helper should reuse `nanobot.config.paths` conventions. Graph persistence failures must not prevent the ordinary linear chat path from continuing.

#### Context result contract

From Phase 1 onward, use a structured result even if the UI does not display it yet:

```python
@dataclass
class ContextResult:
    strategy: str
    messages: list[dict[str, Any]]
    node_ids: list[str]
    reasons: dict[str, str]
    token_count: int
    retrieval_ms: float
    diagnostics: dict[str, Any]
```

The agent loop should consume `ContextResult.messages` as history. Phase 6 can expose the remaining fields to the observatory without redesigning the engine API.

#### Security and behavior-preservation rule

This repository has explicit workspace, channel, runtime-context, attachment, and recovery boundaries. The context-graph feature must not weaken them.

In particular:

- Do not move canonical sessions into the project workspace.
- Do not expose private session files directly to the browser.
- Do not serialize model-only runtime context into a public graph-inspector response without applying the repository's existing public-history/scrubbing rules.
- Do not bypass legal tool-call boundaries produced by `Session.get_history(...)`.
- Do not make Graph mode the default until the experiment is proven safe.
- If Graph mode fails, fall back to the existing linear path and log the failure.


---

## Proposed Solution Architecture

We adopt a **two-layer architecture** (as identified in prior analysis):

1. **Conversation Graph (Data Layer)** – manages the state of the chat as a graph.
   - *Nodes:* each message or summary.
   - *Edges:* typed relationships (REPLY, BRANCH, etc.).
   - *Storage:* in-memory with JSON serialization for persistence.
   - **Key objects:** `ChatNode`, `ChatEdge`, `ConversationGraph`.

2. **Context Engine (Logic Layer)** – given the conversation graph and current node, it decides what to include as prompt context.
   - Implements *Graph traversal*, *vector search*, *ranking*, *token limiting*.
   - Exposes a common interface so that a **toggle** can switch between implementations.
   - **Strategies:** `LinearContextEngine`, `GraphContextEngine`, etc.

The high-level flow (see **Figure 1** below) is:

```mermaid
graph TD
    A[User Input] --> B[Agent Runtime]
    B --> C[Context Engine] 
    C --> D{Context Strategy}
    D --> E[LinearContextEngine]
    D --> F[GraphContextEngine]
    F --> G[ConversationGraph]
    F --> H[VectorIndex (optional)]
    F --> I[SummaryStore (optional)]
    E --> J[TokenBuffer]
    F --> J
    J --> K[Construct Prompt]
    K --> L[LLM]
    L --> M[Agent Response]
```

- **Context Engine**: Takes the current message (node) and chosen strategy. 
- **LinearContextEngine**: simply grabs last-N messages (from graph or log).
- **GraphContextEngine**: traverses `ConversationGraph`, follows relevant edges, ranks by recency/relevance, includes summaries and vector hits.
- **ConversationGraph**: Underlying data (nodes/edges). 
- **VectorIndex**: Local embedding store for all messages (optional, added later).
- **SummaryStore**: Contains summary nodes created on demand.
- **Prompt Construction**: The collected context nodes are merged with the system prompt to call the LLM.

In the UI, there is a toggle (`Context Strategy: [ Linear ○ | Graph ○ ]`). When the user switches modes, the agent’s code picks the respective engine. A **branch** button appears next to each past assistant or user message: clicking it clones the graph up to that point. A **copy** icon allows copying text. There is also a floating **Context Observatory** panel (hidden by default) that can be popped out to inspect the selected context (see **Figure 2** under UI behavior below).

### Data Model Sketch (JSON example)

An example of the serialized conversation graph (very simplified) might look like:

```json
{
  "nodes": [
    {"id": "n1", "role": "user", "content": "Let's design an API.", "timestamp": "..."},
    {"id": "n2", "role": "assistant", "content": "We can use REST...", "timestamp": "..."},
    {"id": "n3", "role": "user", "content": "What about GraphQL?", "timestamp": "..."},
    {"id": "n4", "role": "assistant", "content": "GraphQL offers...", "timestamp": "..."},
    {"id": "n5", "role": "assistant", "content": "Summary: We discussed REST vs GraphQL...", "timestamp": "...", "type": "summary"}
  ],
  "edges": [
    {"source": "n1", "target": "n2", "type": "REPLY"},
    {"source": "n1", "target": "n3", "type": "BRANCH"},
    {"source": "n3", "target": "n4", "type": "REPLY"},
    {"source": "n1", "target": "n5", "type": "SUMMARY"},
    {"source": "n3", "target": "n5", "type": "SUMMARY"}
  ]
}
```

This graph represents a conversation where the user asks about APIs, the assistant suggests REST (`n2`), then the user branches and asks about GraphQL (`n3`), and the assistant answers (`n4`). A summary node `n5` connects back to both branches. The context engine will traverse such edges to collect context.

---

# Project Phases

We break the implementation into **Layer 1..6 (Phase 1..6)**. Each phase adds one capability. After every phase, the system should be in a demonstrable state. Below is an outline of each phase, with all necessary details.

| Phase | Objective                                | Deliverable                                                  |
|-------|------------------------------------------|--------------------------------------------------------------|
| 1     | Baseline toggle & data model foundation  | Toggle UI, Node/Edge classes, LinearContextEngine baseline   |
| 2     | Graph data model with branching          | In-memory ConversationGraph, `BRANCH` functionality, copy UI |
| 3     | Graph-based context resolution           | GraphContextEngine with traversal, multi-parent merging      |
| 4     | Semantic retrieval and summaries         | Hybrid graph + vector retrieval, summary nodes, ranking      |
| 5     | Context-Aware Workflow DAG (optional)    | Extend graph to include “operation” nodes (intent, tools)    |
| 6     | Observability & demonstration            | Context Inspector UI, metrics logging, side-by-side compare   |

Each phase description below includes:
- **Objective:** what we aim to achieve.
- **Deliverables:** the components and features added.
- **Steps:** procedural instructions (to code or configure).
- **Data Structures / Schema:** key classes or JSON with examples.
- **API / Interfaces:** what functions or modules are provided.
- **Tests & Expected Results:** how to verify.
- **Failure Modes & Recovery:** common issues and mitigation.
- **Instrumentation / Metrics:** what metrics to collect and how.
- **[DO THIS] Prompt:** a directive the agent should execute for that phase.

We also note: after each coding step, instruct the agent to **save state/snapshot** using the (future) save-state procedure, so work is not lost.

---

## Phase 1: Baseline Setup & Toggle

**Objective:** Establish the basic project skeleton. Implement the **Linear context engine** as a baseline, and a UI toggle to switch modes (though initially Graph mode will behave identically). Create the foundational data model classes (`Node`, `Edge`, `ConversationGraph`). Ensure a working chat pipeline exists with no regressions.

**Deliverables:** 
- `ContextEngine` interface or base class.
- `LinearContextEngine` class: returns last N messages.
- Graph data classes: `ChatNode`, `ChatEdge`, `ConversationGraph` (in-memory, JSON-serializable).
- A **toggle control** in the UI to switch between “Linear” and “Graph” mode.
- The **branch button** and inspector can be stubbed or hidden for now.
- Ensure the existing agent (nanobot or similar) can run with no changes to chat flow.

**Steps:**

1. **Define Data Classes**. Create basic classes in Python:

   ```python
   class ChatNode:
       def __init__(self, id, role, content, timestamp=None, **meta):
           self.id = id
           self.role = role          # 'user', 'assistant', 'system', etc.
           self.content = content
           self.timestamp = timestamp or time.time()
           self.metadata = meta      # e.g., topic tags
           self.embedding = None     # to be filled later

   class ChatEdge:
       def __init__(self, source, target, edge_type):
           self.source = source      # node id
           self.target = target      # node id
           self.type = edge_type     # 'REPLY', 'BRANCH', etc.
   ```

   These are the minimal properties. We will add fields (e.g. embedding, token count) later as needed.

2. **Implement `ConversationGraph`**. This holds nodes and edges. Basic interface:
   ```python
   class ConversationGraph:
       def __init__(self):
           self.nodes = {}  # id -> ChatNode
           self.edges = []  # list of ChatEdge

       def add_node(self, node: ChatNode):
           self.nodes[node.id] = node

       def add_edge(self, edge: ChatEdge):
           self.edges.append(edge)

       def get_node(self, node_id):
           return self.nodes.get(node_id)
       # (optionally) methods to serialize to/from JSON, find ancestors, etc.
   ```
   - **Schema example** (JSON):  
     ```json
     {
       "nodes": [
         {"id": "n1", "role": "user", "content": "Hello"},
         {"id": "n2", "role": "assistant", "content": "Hi there"}
       ],
       "edges": [
         {"source": "n1", "target": "n2", "type": "REPLY"}
       ]
     }
     ```

3. **Set up Serialization**. Write `to_json()` / `from_json()` methods for the graph so it can be saved:
   ```python
   import json
   def save_graph(graph: ConversationGraph, filename):
       data = {
         "nodes": [{...} for each node],
         "edges": [{...} for each edge]
       }
       with open(filename, 'w') as f: json.dump(data, f)

   def load_graph(filename) -> ConversationGraph:
       data = json.load(open(filename))
       # create graph, populate nodes/edges, return it
   ```

4. **Integrate with Agent**. In the agent’s code (nanobot or your chat app), identify where the context is built. Replace that temporarily with a placeholder that chooses one of two engines:
   ```python
   class ContextEngineBase:
       def build_context(self, graph: ConversationGraph, current_node_id):
           raise NotImplementedError

   class LinearContextEngine(ContextEngineBase):
       def __init__(self, window_size=5):
           self.window_size = window_size

       def build_context(self, graph, current_node_id):
           # find the list of the last N nodes chronologically
           # For now, assume graph.nodes is insertion-ordered or store list
           last_nodes = list(graph.nodes.values())[-self.window_size:]
           return last_nodes
   ```

5. **UI Toggle**. Add a setting or button in the chat UI (web or terminal) labeled “Context Strategy” with options **Linear** (default) and **Graph**. When changed, it should set a flag in the agent (e.g., `context_engine = LinearContextEngine()` vs `GraphContextEngine()`).  
   - In web UI: add a radio button or dropdown in settings.  
   - In TUI: add a command like `/set context=graph`.  
   Initially, selecting *Graph* can still just use the same `LinearContextEngine` logic (we’ll override it later).

6. **Baseline Behavior Check**. At this point, the *Graph mode* should behave identically to *Linear mode*. Test by conversing and verifying the agent still works, retrieving last N messages as context. No user-noticeable change should occur.

7. **Basic Logging**. Log which context engine is used for each query (Linear or Graph) for verification.

8. **Save State**. After building this, save the conversation graph to disk at session end or periodically (e.g. after each user message) using the `save_graph()` function.

**Data Structures / Schema (Phase 1):**
```json
{
  "nodes": [
    {"id": "n1", "role": "user",      "content": "Hi",        "timestamp": 123.0},
    {"id": "n2", "role": "assistant", "content": "Hello there!", "timestamp": 124.0}
  ],
  "edges": [
    {"source": "n1", "target": "n2", "type": "REPLY"}
  ]
}
```

**API / Interfaces (Phase 1):**
- `ConversationGraph.add_node(node)`, `add_edge(edge)`, `save_graph(file)`, `load_graph(file)`.
- `LinearContextEngine.build_context(graph, current_node_id)` returns list of nodes.

**Tests & Expected Results:**

- *Test 1:* Add 3 messages to graph and a couple of edges. Call `LinearContextEngine.build_context` with `window_size=2`. It should return the last 2 messages.  
- *Test 2:* Run the chat agent in Linear mode with known conversation (e.g. 5 back-and-forth messages). The prompt sent to LLM contains exactly the last N messages (N=window_size).  
- *Toggle Test:* Switch the UI toggle to *Graph* mode. Ask a question. The system should log “Using GraphContextEngine (fallback to linear)”. The behavior should not change (it still uses last-N).

**Failure Modes & Recovery:**

- If the `ConversationGraph` has no nodes or edges, the context engines should handle it gracefully (return empty list or just current message).  
- If an unknown mode is selected, fallback to linear.  
- If saving the graph fails (disk full/permissions), log an error and continue without persistence.

**Instrumentation / Metrics (Phase 1):**

- Log the time taken by `LinearContextEngine.build_context`.  
- Count of nodes retrieved vs total graph nodes.  
- (Later) These logs will be used by the inspector.

**[DO THIS] Prompt:**  
```plaintext
**[DO THIS]**: Implement the core classes `ChatNode`, `ChatEdge`, and `ConversationGraph` with JSON serialization. Integrate `LinearContextEngine` (using last-N messages). Add a UI toggle labeled “Context Strategy” that switches between Linear and Graph mode (Graph mode initially uses the linear logic). Test by running a chat and verifying the correct context is built. Save the conversation graph to a file after each user message.
```

### Repository-specific implementation notes for Phase 1

For `Srimano510/Git`, interpret Phase 1 as an **adapter around the existing session/history path**, not as replacement session infrastructure.

1. Create `nanobot/context_graph/` with the model, store, engine interface, and `ContextResult`.
2. Implement the baseline engine by delegating to the existing session replay API:

   ```python
   class LinearContextEngine:
       def build_context(
           self,
           session: Session,
           *,
           max_messages: int = 0,
           max_tokens: int = 0,
       ) -> ContextResult:
           started = time.perf_counter()
           history = session.get_history(
               max_messages=max_messages,
               max_tokens=max_tokens,
               extend_to_user=True,
           )
           return ContextResult(
               strategy="linear",
               messages=history,
               node_ids=[],
               reasons={},
               token_count=estimate_history_tokens(history),
               retrieval_ms=(time.perf_counter() - started) * 1000,
               diagnostics={},
           )
   ```

   The exact token helper may use existing utilities. The important requirement is that the returned messages preserve nanobot's legal replay semantics.

3. In `nanobot/agent/loop.py`, select a context strategy at the point where `ctx.history` is prepared, or immediately before `_build_transcript_input(ctx)`. Keep `_build_transcript_input()` and `ContextBuilder.build_transcript()` as the shared downstream path.
4. Do **not** alter `_persist_user_message_early()` merely to support the toggle. Persistence remains canonical and strategy-independent.
5. Add the WebUI control to the existing thread settings/header/composer surface rather than building a second chat page. Persist the choice per chat/session.
6. For the first commit, `graph` may deliberately call the same native linear adapter so the toggle plumbing can be tested without changing answers.
7. Add regression tests proving that enabling the feature with strategy `linear` produces the same replay history as the repository did before the feature.

**Phase-1 completion test for this repository:** existing CLI/WebUI chats, attachments, tool-call histories, session compaction/replay, and recovery tests still pass with the feature installed but set to Linear.


---

## Phase 2: Graph Representation & Branching

**Objective:** Introduce the graph structure and branching functionality. Enable actual divergence in the conversation graph (so it’s no longer linear). Add a **“Branch”** button in the UI that lets the user fork the context at any message. The agent should continue the conversation from the branched node as a new branch.

**Deliverables:** 
- `ConversationGraph` now supports branching. (No longer treating it as a linear list.)
- Ability to create a new branch: copying or referencing the parent node’s context.
- Update UI: a branch icon/button under each message (user or assistant) that duplicates the context up to that point. 
- **Copy button**: For convenience, next to each message, include a copy-to-clipboard icon (this is mostly UI, not critical for logic, but we include it per requirements).
- Ensure `GraphContextEngine` (still a stub) handles multi-branch graph (for now it can simply follow one path).
- Continue supporting linear mode as before.

**Steps:**

1. **Allow Graph with Branches**. Modify `ConversationGraph` to handle branching. Actually, the existing structure already does; just ensure we can add edges that aren’t strictly chronological. We will rely on edge types to define branches. 
   
   - Define a new edge type `BRANCH`. A branch operation will add an edge from the branch point to the new message with type `BRANCH`. E.g., if the user branches at node `n2`, the next message has `BRANCH` from `n2`.
   
2. **Implement Branch Button (UI)**. In the UI conversation view, under each message, add a small **“🗂 Branch”** button next to “Copy”. When clicked:
   - Capture the `message_id` (node id) of that message.
   - In the backend, handle it by creating a new empty child node with a new ID (you may create a placeholder like “(new branch)”) or by simply setting the next input to continue from there.
   - For simplicity, the action can be: store a pointer `active_node_id` = branch_message_id. The next user input will be attached to that node. In effect, the next message will get a `BRANCH` edge from `active_node_id`.
   
   For example, user clicks Branch on message `n2`. The system sets `active_node = n2`. Then the next user input (or assistant reply) is added with an edge type `BRANCH` from `n2` to the new node.
   
3. **Graph.add_edge with BRANCH**. When processing the next message after a branch:
   ```python
   if context_engine.mode == 'GRAPH' and branch_clicked:
       graph.add_edge(ChatEdge(source=active_node, target=new_node_id, edge_type='BRANCH'))
   else:
       graph.add_edge(ChatEdge(source=last_node, target=new_node_id, edge_type='REPLY'))
   ```
   This allows multiple children of a node (branching). The graph can become a tree or DAG.

4. **Copy Button (UI)**. Implement a copy-to-clipboard icon (or context menu) for each message. The frontend can simply copy the message text. (No backend logic needed; it's purely UI/UX.)

5. **GraphContextEngine (stub)**. Now that the conversation is branching, modify the stub `GraphContextEngine` to at least not crash. For now, it can simply follow the same logic as linear (last-N chronological) or, better, traverse the current branch. E.g.:
   ```python
   class GraphContextEngine(ContextEngineBase):
       def build_context(self, graph, current_node_id):
           # Basic fallback: same as linear for now
           return LinearContextEngine(window_size=5).build_context(graph, current_node_id)
   ```
   We’ll improve it next phase.

6. **Scenario Testing**. Create a test scenario:
   ```
   User: [n1] "Start project X"
   Assistant: [n2] "I suggest approach A."          (edge n1->n2: REPLY)
   User: [branch at n2] "Actually, consider approach B."  (branching)
   Assistant: [n3] "Approach B is viable because..." (edge n2->n3: BRANCH)
   ```
   The graph now has two paths:
   - Path1: n1 → n2 (rest branch)
   - Path2: n2 → n3 (GraphQL branch)
   (In a more complex scenario, n1 could have multiple children.)
   Ensure the graph reflects this.

7. **Save Graph After Branch**. After each branch action, serialize the graph so the branch is persisted.

**Data Structures / Schema (Phase 2):**
```json
{
  "nodes": [
    {"id": "n1", "role": "user", "content": "Project X"},
    {"id": "n2", "role": "assistant", "content": "Use approach A."},
    {"id": "n3", "role": "assistant", "content": "Alternatively, try approach B."}
  ],
  "edges": [
    {"source": "n1", "target": "n2", "type": "REPLY"},
    {"source": "n2", "target": "n3", "type": "BRANCH"}
  ]
}
```
(Here `n3` branched off `n2`.)

**API / Interfaces (Phase 2):**
- `ConversationGraph.add_edge(source, target, type='BRANCH')` to mark a branch.
- UI handler `on_branch_click(node_id)`: sets `active_node = node_id`.
- Context Engine: `GraphContextEngine` (fallback to linear for now).

**Tests & Expected Results:**

- *Test 1:* In Linear mode, after branching, the context should still include only recent messages (ignoring branch logic) – i.e., baseline unchanged.
- *Test 2:* In Graph mode, after a branch, verify `ConversationGraph` has the new `BRANCH` edge. For example, if user branches at `n2`, then speak, the graph should record an edge `{"source":"n2","target":"n3","type":"BRANCH"}`.
- *Branch Button UI Test:* Click branch on a past message, then send a new message. The new message should appear in the thread (and logs) with an arrow from the branched message.

**Failure Modes & Recovery:**

- If two branches use the same target ID accidentally, ensure unique IDs (UUIDs).
- If `active_node` is set to a branch point but the user deletes it or moves away, reset `active_node` to the last message to avoid orphaned branches.
- If user tries to branch at an already branched node while in linear mode, switch to graph mode automatically or ignore.

**Instrumentation / Metrics (Phase 2):**

- Track number of branches created.
- Log when a branch edge is added (for the inspector).
- Measure if branch handling adds noticeable delay.

**[DO THIS] Prompt:**  
```plaintext
**[DO THIS]**: Extend `ConversationGraph` to allow multiple children per node. Add a “Branch” button in the UI under each message. Implement the logic so that clicking it makes the next message follow a `BRANCH` edge from that node. Update the graph and save it. Verify by branching a conversation path and inspecting the graph JSON. Also add a “Copy” icon for each message text.
```

### Repository-specific implementation notes for Phase 2

The repository already forks chats. Therefore **Phase 2 should instrument the existing fork path, not replace it.**

- Reuse `App.tsx -> ThreadShell -> ThreadViewport.onForkFromMessage(...)`.
- When the backend creates the child session, record lineage metadata sufficient for the graph store to identify:
  - source session key,
  - child session key,
  - fork boundary,
  - shared `graph_id`.
- Synchronize the inherited prefix into the graph idempotently.
- When the first new child message is persisted, add a `BRANCH` edge from the graph node at the source boundary to the child message node.
- Continue to let nanobot own the actual child-session copy/seed behavior.
- Preserve `forkBoundaryMessageCount` behavior in the WebUI.

For this repository, a branch is therefore **both**:

```text
nanobot level:  source session  ──fork──> child session
graph level:    boundary node   ─BRANCH─> first divergent child node
```

This is preferable to cloning graph nodes on every branch. Shared inherited messages may remain one logical graph ancestry while provenance records which sessions contain/replay them.

Before adding a new Copy button, inspect the current message-action UI. If copy already exists, reuse it and add no duplicate control.

Add a test that forks from a historical user message, sends a new child message, reloads both sessions, reloads the graph store, and confirms the `BRANCH` edge still points to the correct logical boundary.


---

## Phase 3: Graph-Based Context Resolution

**Objective:** Replace the fallback with a real graph traversal context engine. The engine should follow incoming edges (e.g. follow parent links through REPLY or CONTEXT edges) to collect all relevant ancestor nodes, handling multi-parent merges. It should **deduplicate** nodes, sort chronologically or by relevance, and apply token budgeting. The graph mode should now differ from linear mode. 

**Deliverables:** 
- `GraphContextEngine.build_context(graph, current_node_id)` with actual logic:
  - Traverse upward through REPLY/BRANCH edges to collect ancestors.
  - Optionally follow `CONTEXT` or `REFERENCE` edges (if present).
  - Merge context from multiple parents (multi-parent merge).
  - Output a list of nodes as the context.
- Ensure that in a graph with merges, context includes all parents.
- UI: A small indicator of the current branch (optional).
- The toggle now truly selects different behaviors.

**Steps:**

1. **Define Relevant Edge Types**. Decide which edge types the context resolver will follow. For now, use:
   - **REPLY**: always follow (it’s the natural thread).
   - **BRANCH**: treat like reply (since branch creates a new child).
   - **CONTEXT**: high-priority context edges (if introduced).
   - **REFERENCE**: optional edges we may use later.
   - (Ignore SUMMARY edges here).
   
   In code, define e.g. `TRAVERSE_EDGE_TYPES = {'REPLY', 'BRANCH', 'CONTEXT'}`.

2. **Traverse Parents**. Implement a graph-walking function:
   ```python
   def get_ancestor_context(graph, current_id):
       stack = [current_id]
       visited = set()
       result = []
       while stack:
           nid = stack.pop()
           if nid in visited: continue
           visited.add(nid)
           node = graph.get_node(nid)
           if node:
               result.append(node)
               # Find incoming edges to nid
               parents = [edge.source for edge in graph.edges if edge.target == nid and edge.type in TRAVERSE_EDGE_TYPES]
               stack.extend(parents)
       return result  # list of ChatNode
   ```
   This collects the current node and all reachable parents. 

   Alternatively, we may want chronological order: sort `result` by timestamp after collecting.

3. **GraphContextEngine**. Replace the stub with this logic:
   ```python
   class GraphContextEngine(ContextEngineBase):
       def __init__(self, window_tokens=2000):
           self.token_budget = window_tokens

       def build_context(self, graph, current_node_id):
           nodes = get_ancestor_context(graph, current_node_id)
           # Remove duplicates and sort by timestamp:
           unique = {n.id: n for n in nodes}.values()
           sorted_nodes = sorted(unique, key=lambda n: n.timestamp)
           # Apply token budget: include nodes from newest backwards until limit
           context = []
           tokens = 0
           for node in reversed(sorted_nodes):
               tok_len = count_tokens(node.content)
               if tokens + tok_len > self.token_budget:
                   break
               context.insert(0, node)
               tokens += tok_len
           return context
   ```
   Here, `count_tokens` can be a simple heuristic (e.g. word count or a tokenizer).

4. **Test Multi-Parent**. Create a graph scenario:
   ```
       n1
      /      n2    n3
      \  /
       n4
   ```
   Edges: n1->n2, n1->n3 (two branches), n2->n4, n3->n4 (merge). If current_node_id = n4, `build_context` should return [n1, n2, n3, n4] (in chronological order). Verify by unit test.

5. **Merge Summaries (placeholder)**. If summary nodes exist, the resolver should treat them specially: e.g., if a SUMMARY edge leads to a summary node, it could include that instead of raw nodes. (We'll implement summary logic in next phase, but design to skip details now.)

6. **Switch on Toggle**. Now the UI toggle should switch between using `LinearContextEngine` and `GraphContextEngine`. In *Graph* mode, confirm that context is collected via the graph traversal. 

7. **User Experience**. After this change, in graph mode when a branch exists, older messages from the other branch should not be included (unless linked by context edges). For example, if conversation branched at n2 (rest vs graphql), then in graph mode on branch B, we should not include branch A’s messages by default. Linear mode would have mixed them if within window. This should become evident in testing.

**Data Structures / Schema (Phase 3):**
The JSON schema is unchanged, but we now interpret edges. Example multi-parent:
```json
{
  "nodes": [
    {"id": "n1", ...},
    {"id": "n2", "role":"assistant", ...},
    {"id": "n3", "role":"assistant", ...},
    {"id": "n4", "role":"assistant", ...}
  ],
  "edges": [
    {"source": "n1", "target": "n2", "type": "REPLY"},
    {"source": "n1", "target": "n3", "type": "REPLY"},
    {"source": "n2", "target": "n4", "type": "REPLY"},
    {"source": "n3", "target": "n4", "type": "REPLY"}
  ]
}
```
(This is a diamond: n1->n2, n1->n3, n2->n4, n3->n4.)

**API / Interfaces (Phase 3):**
- `GraphContextEngine.build_context(graph, current_node_id)` returns a list of ChatNode in context, honoring token budget.
- Possibly `get_ancestor_context(graph, current_node_id)` as a helper.
- Configuration for token budget.

**Tests & Expected Results:**

- *Test 1:* With the diamond graph above and current=n4, context should include n1, n2, n3, n4. Check using a unit test.
- *Test 2:* In a scenario with two separate branches (A and B) that never merge, context for branch A messages should not include branch B nodes. E.g. if current node is in branch B, nodes from branch A should not be in context (since not reachable via edges).
- *Test 3:* Verify token budgeting: given small budget, context may cut off some ancestors (we can simulate by adjusting token counts).
- *Feature Test:* In UI Graph mode, the displayed context (if inspectable via console or logs) matches the graph traversal output.

**Failure Modes & Recovery:**

- If a node has no parents (root), context is just [that node].
- If cycle is introduced (shouldn’t happen normally), `visited` set prevents infinite loop.
- If token budget is too small to include even the current node, ensure at least current node is returned (otherwise LLM has no prompt).

**Instrumentation / Metrics (Phase 3):**

- Measure time taken by `get_ancestor_context` and total context building. 
- Log number of nodes visited vs returned.
- For each included node, record the reason (we’ll surface this in the inspector in Phase 6).
- Count how many ancestors were pruned by budget.

**[DO THIS] Prompt:**  
```plaintext
**[DO THIS]**: Implement `GraphContextEngine.build_context()` to traverse the ConversationGraph from the current node backward. Follow REPLY and BRANCH edges to collect ancestors, deduplicate, and sort chronologically. Then apply a token budget to trim the oldest messages if needed. Test with multi-parent scenarios (e.g. a diamond-shaped graph) to ensure all parents are included.
```

### Repository-specific implementation notes for Phase 3

Graph traversal now becomes an alternative **history selector**.

Recommended flow inside the agent turn:

```text
Session / current message
      ↓
resolve selected strategy
      ↓
Linear: Session.get_history(...)
Graph:  GraphContextEngine.resolve(...)
      ↓
ContextResult.messages
      ↓
TurnContext.history
      ↓
AgentLoop._build_transcript_input(ctx)
      ↓
ContextBuilder.build_transcript(...)
```

For Graph mode:

- Traverse `REPLY`, `BRANCH`, and `CONTEXT` ancestry.
- Support ancestry that crosses nanobot session keys after a fork.
- Convert selected `ChatNode`s back into the message dictionaries expected by `TranscriptInput.history`.
- Keep tool-call/result sequences legal. If graph pruning would split a tool interaction or otherwise produce an invalid replay boundary, expand to the smallest legal group or omit that group.
- Never include the fresh current user input twice: it remains `TranscriptInput.current_message`, not part of `history`.
- Preserve current runtime-context handling by leaving it to the existing context builder / runtime-context path.
- If graph resolution throws, logs invalid structure, or cannot produce a legal replay, fall back to the native linear result for that turn and report the fallback in diagnostics.

The diamond-merge unit test in the generic guide should remain, but add a repository-level integration test where two forked sessions contribute to a merged graph context and the resulting history can still pass through `ContextBuilder.build_transcript()` without changing its API.


---

## Phase 4: Hybrid Retrieval & Summaries

**Objective:** Enhance the graph-based context with semantic search and summarization. The context engine should now optionally retrieve additional relevant nodes via vector similarity, handle **SUMMARY** nodes to condense long histories, and maintain full persistence/re-indexing of vector embeddings across application restarts. This shows how a hybrid (graph + vector) approach works reliably in persistent sessions.

**Deliverables:** 
- A vector search component (e.g. using OpenAI embeddings or a local FAISS/Pinecone mock) that given the current message or context, finds semantically related past nodes. Integrate this into `GraphContextEngine` to add extra nodes.
- **Vector Index Persistence & Re-indexing:** Persistence mechanism for the vector index (`save`/`load`) saved alongside the graph JSON, with automatic re-indexing from `ConversationGraph` on session reload if missing or out-of-sync.
- A mechanism to create and use summary nodes: if a branch is very long, one can insert a **Summary** node linked from the branch root, and the context engine can use it instead of all underlying messages.
- Ranking: After combining graph-traversed nodes and vector hits, sort/filter them by relevance (for example, recency or similarity).
- Token-budget integration: now context may include both sources; trim by highest relevance.
- The UI can flag nodes that were included via vector search or were summary placeholders.

**Steps:**

1. **Embedding Index & Persistence**. Choose or mock an embedding function. For example, use OpenAI embeddings (if API keys available) or a dummy vectorizer. Create an in-memory index of embeddings for every `ChatNode.content` as nodes are added. Implement `save()` and `load()` methods to persist vectors to disk (e.g., `vector_index.json` or binary file) whenever the conversation graph is saved. Also implement a `reindex(graph)` fallback method that rebuilds embeddings for all nodes in `ConversationGraph` if the vector file is missing or corrupted on application load. Provide API:
   ```python
   class VectorIndex:
       def __init__(self):
           self.id_to_vector = {}
       def add(self, node_id, content):
           vec = embed(content)  # e.g. call an embedding model
           self.id_to_vector[node_id] = vec
       def query(self, text, top_k=5):
           qvec = embed(text)
           # compute cosine with all stored vectors, return top_k node_ids
           return top_k_results
       def save(self, filename):
           # serialize self.id_to_vector to JSON / disk
           with open(filename, 'w') as f:
               json.dump(self.id_to_vector, f)
       def load(self, filename):
           # load serialized vectors from disk
           with open(filename, 'r') as f:
               self.id_to_vector = json.load(f)
       def reindex(self, graph: ConversationGraph):
           # iterate through graph.nodes and compute embeddings for missing items
           for node_id, node in graph.nodes.items():
               if node_id not in self.id_to_vector:
                   self.add(node_id, node.content)
   ```

2. **Integrate into GraphContextEngine**. Modify `build_context`:
   - After collecting ancestor context nodes (from phase 3), **perform semantic search** if enabled:
     ```python
     semantic_hits = vector_index.query(current_node_content, top_k=3)
     for hit in semantic_hits:
         if hit not in [node.id for node in context_nodes]:
             context_nodes.append(graph.get_node(hit))
             reasons[hit] = f"Semantic similarity to current node"
     ```
   - Combine these with existing nodes.

3. **Summary Nodes**. Implement a simple summary feature:
   - For any branch that exceeds, say, 10 messages, allow creating a summary node. This can be done manually or automatically (for demo, we can hardcode some summary content for tests).
   - A summary node is a `ChatNode` with `type="summary"`. It should connect to the branch with a `SUMMARY` edge:
     ```python
     summary_node = ChatNode(id="n10", role="assistant", content="Summary: ...", timestamp=...)
     graph.add_node(summary_node)
     graph.add_edge(ChatEdge(source=branch_root_id, target=summary_node.id, type="SUMMARY"))
     ```
   - The context engine, when it sees a SUMMARY edge, should include the summary node and skip underlying raw nodes if necessary:
     ```python
     if any(edge.type=="SUMMARY" for edge in graph.edges if edge.source == parent_id):
         context_nodes = [node for node in context_nodes if node.id != parent_id]
         context_nodes.append(summary_node)
         reasons[summary_node.id] = "Used summary instead of raw nodes"
     ```
   - This is a simple approach: either include summary or details.

4. **Ranking & Token Limit**. After gathering ancestors + semantic hits, rank by a heuristic (e.g. recency * weight + semantic score). Then trim to budget:
   - We already sorted by time, but we may incorporate semantic rank (for now, assume semantic hits go at the top).
   - If necessary, drop lowest-scored nodes first.

5. **Update Toggle Options**. UI can now allow selecting "Graph + Vector" mode. For simplicity, this could be a third option or a checkbox “Enable semantic retrieval”.

6. **Test Semantic Retrieval**. Create a conversation where a relevant piece of info is out of branch. For example:
   ```
   n1: "What did we decide about the database?"
   [Many unrelated messages...]
   nX: (Graph mode): should retrieve the earlier mention if semantically similar.
   ```
   Use a manual test or a scripted one with embeddings that match.

7. **Test Summaries**. Simulate a long thread (e.g. 20 messages). Create a summary node for the first 15. Verify that in context, if budget is low, the engine picks the summary node instead of all 15 messages.

**Data Structures / Schema (Phase 4):**
```json
{
  "nodes": [
    // ... existing messages
    {"id": "n10", "role": "assistant", "content": "Summary: We discussed options A and B...","type":"summary", "timestamp": 125}
  ],
  "edges": [
    // ... previous edges
    {"source": "n2", "target": "n10", "type": "SUMMARY"}
  ]
}
```
`n10` is a summary for branch starting at n2.

**API / Interfaces (Phase 4):**
- `VectorIndex.add_node(node_id, content)`, `VectorIndex.query(text, k)`, `VectorIndex.save(file)`, `VectorIndex.load(file)`, and `VectorIndex.reindex(graph)`.
- `GraphContextEngine.enable_semantic = True/False`.
- Possibly `SummaryStore.create_summary(node_ids)` to auto-generate, but manual is fine for demo.

**Tests & Expected Results:**

- *Test 1:* Add some nodes and run `VectorIndex.query("some query")` to ensure it returns the top K matching node IDs. For a known small dataset, check if expected node is returned.
- *Test 2:* In Graph mode with semantic enabled, verify that context includes at least one semantically relevant past node (simulate by using identical or similar text).
- *Test 3:* For summarization: given a graph where node n2 has a SUMMARY child n10, if current is beyond n10, ensure n10 appears in context in place of detailed nodes.
- *Test 4:* Ensure total tokens in context do not exceed budget; count accordingly.
- *Test 5 (Persistence & Re-indexing):* Save the `VectorIndex` and `ConversationGraph` to disk, reload them in a fresh session instance, and verify semantic search works without re-embedding existing nodes. Delete the vector file, reload, and verify `reindex(graph)` reconstructs the index cleanly.

**Failure Modes & Recovery:**

- If embedding service fails (no internet/keys), fallback to ignoring semantic search.
- If vector index file is missing, stale, or corrupted upon session load, trigger `reindex(graph)` to restore semantic search capabilities.
- If summary content is not good, it might degrade context quality. For now assume summary nodes are valid.
- If combining semantic hits and ancestors exceeds budget grossly, ensure at least something (similar to phase 3 logic).
- If same node appears via graph and vector, deduplicate it.

**Instrumentation / Metrics (Phase 4):**

- Log number of semantic hits found and how many were included.
- Time taken for embedding queries.
- Report how often summary nodes are used vs raw nodes.
- Track recall improvement: (if we had labeled relevant nodes, measure if semantic search found extra relevant context).

**[DO THIS] Prompt:**  
```plaintext
**[DO THIS]**: Integrate semantic retrieval, persistence, and summarization into `GraphContextEngine`. Build or mock a `VectorIndex` that embeds messages and supports `save()`, `load()`, and `reindex(graph)` for persistence across session reloads. In `build_context`, after graph traversal, query the index with the current message to get extra node IDs. Add those nodes to context. Also implement summary logic: if a branch is long, create a summary node and use it in context instead of all children. Apply ranking and trimming to stay within the token budget. Test with examples to ensure semantic hits, vector persistence/re-indexing, and summary nodes appear/work in context as expected.
```

### Repository-specific implementation notes for Phase 4

Keep semantic retrieval and summaries **inside `nanobot/context_graph/`** and outside the existing long-term `MemoryStore`/Dream system. They solve different problems:

- Dream / `MemoryStore`: durable agent memory and consolidation.
- Session summary/checkpoints: nanobot's existing replay compaction/recovery mechanism.
- Context Graph summary nodes: experimental graph-level substitutes used by Graph mode.

Do not silently replace nanobot's existing session summaries with graph summary nodes.

For vector persistence:

- Key embeddings by stable graph node ID.
- Store the embedding model/version and content hash with each vector.
- On load, re-embed only nodes whose vector is missing, corrupt, model-incompatible, or whose content hash changed.
- Exclude nodes that should not enter user/model context, including internal workflow-only nodes.
- Treat semantic hits as candidates, then pass them through the same visibility/security filters and token-budget rules as graph ancestry.
- A semantic hit from another fork is allowed only when the configured graph strategy permits cross-branch retrieval; the reason must be visible in `ContextResult.reasons`.

Prefer local/simple dependencies for the experiment. Do not add a production database or distributed vector service merely for Phase 4 unless the repository later adopts one independently.


---

## Phase 5: Workflow DAG (Advanced / Optional)

**Objective:** (Optional) Extend the conversation graph concept into a **Context-Aware Workflow DAG**, where nodes can represent not only messages but also operations (intents, search calls, merges). This aligns with the initial specification of modeling agent execution. It’s an advanced extension and may not be needed for the basic demo, but we outline it for completeness.

**Deliverables:** 
- Ability to insert **operation** nodes into the graph (e.g. “IntentAnalysis”, “MemorySearch”, “PromptBuild”, “LLMCall”).
- Typed edges to represent dependencies and data flow.
- The context engine should traverse or honor execution edges as well.
- The UI/graph inspector could show these workflow nodes in a different color.

**Steps:**

1. **Define Operation Node Types.** In `ChatNode` or a new class `WorkflowNode`, allow `type` field such as `"intent"`, `"tool"`, `"merge"`, `"output"`. These can store metadata (e.g., the query sent to a search).
   
2. **Build a Sample Flow.** For example:
   ```
   [User Input] -> IntentNode -> (MemorySearch + WebSearch) -> ContextMerge -> PromptBuild -> LLMCall -> [Assistant Output]
   ```
   Represent this as nodes with edges. For instance, `IntentNode` connects to `MemorySearchNode` and `WebSearchNode` with edges, then they both go to `ContextMerge`, etc.

3. **Execution Traces (optional)**. If the agent actually performs searches or calls, log those as nodes with edges. For now, we can simulate.

4. **GraphContextEngine Adaptation.** The context engine might skip these nodes when assembling user context (since they are internal operations), or use them to inform what context to gather. For simplicity, treat them as non-user message nodes and do not include them in final prompt.

5. **UI Visualization.** In the context inspector or graph view, highlight these nodes (e.g. `[MemorySearch]` steps). This is mainly for demonstration.

**Data Structures / Schema (Phase 5):**
```json
{
  "nodes": [
    {"id": "intent1", "role":"system", "content":"Determine user intent", "type":"intent"},
    {"id": "memsearch1", "role":"system", "content":"Search memory", "type":"tool"},
    {"id": "websearch1", "role":"system", "content":"Search web", "type":"tool"},
    {"id": "merge1", "role":"system", "content":"Merge context", "type":"merge"},
    {"id": "prompt1", "role":"system", "content":"Build prompt", "type":"prompt"},
    {"id": "llmcall1", "role":"system", "content":"LLM call", "type":"execution"},
    // plus original messages
  ],
  "edges": [
    {"source":"user1","target":"intent1","type":"INTENT"},
    {"source":"intent1","target":"memsearch1","type":"TRIGGERS"},
    {"source":"intent1","target":"websearch1","type":"TRIGGERS"},
    {"source":"memsearch1","target":"merge1","type":"FEEDS"},
    {"source":"websearch1","target":"merge1","type":"FEEDS"},
    {"source":"merge1","target":"prompt1","type":"FEEDS"},
    {"source":"prompt1","target":"llmcall1","type":"FEEDS"},
    {"source":"llmcall1","target":"assistant1","type":"FEEDS"}
  ]
}
```
(This is illustrative; edges like `FEEDS`, `TRIGGERS` show dependencies.)

**API / Interfaces (Phase 5):**
- Ability to create workflow nodes and edges via code or UI actions.
- Possibly reuse the same `ConversationGraph` to store them.

**Tests & Expected Results:**

- *Test:* Visualize or inspect the extended graph. Ensure the context engine ignores or properly handles workflow nodes when assembling prompt.
- *Test:* If we simulate execution, verify that edges represent correct sequence (like memory search and web search running in parallel).

**Failure Modes & Recovery:**

- The context engine might accidentally include these nodes in prompt; explicitly filter them out by role or type.
- Circular dependencies should not occur in well-designed workflow, but check for loops.

**Instrumentation / Metrics:**

- Log the execution order and time of simulated tasks.
- Possibly measure if splitting into workflow slows down response (should be minimal in this demo).

**[DO THIS] Prompt:**  
```plaintext
**[DO THIS]**: (Optional) Extend the graph to include workflow/execution nodes. Define node types for intent analysis, searches, merging, prompt construction, LLM invocation, etc. Link them with dependency edges. Ensure that the context-building logic skips these non-conversation nodes when assembling user prompt. Prepare one example workflow in the graph to illustrate the flow (no actual search needed).
```

### Repository-specific implementation notes for Phase 5

Workflow DAG nodes are optional and should not be inserted into `Session.messages`.

Store them only in the experimental graph sidecar and link them to conversation nodes by `turn_id`, `message_id`, or graph node ID where available.

Examples that map naturally to this repository include:

```text
InboundMessage
  -> RuntimeContextResolution
  -> ContextStrategySelection
  -> GraphTraversal
  -> SemanticSearch
  -> ContextRanking
  -> ContextBuilder
  -> AgentRunner
  -> ProviderCall
  -> AssistantMessage
```

These nodes are observability/execution records. They must be filtered from `ContextResult.messages` unless a later explicit design says otherwise.


---

## Phase 6: Context Observatory & Metrics (Demo Preparation)

**Objective:** Build the final demonstration tools: UI inspector panel, comparison view, and metrics overlays. The goal is to **visualize and compare** the two context strategies on-the-fly. Also prepare the final scenario and slides outline.

**Deliverables:** 
- **Context Inspector Panel:** A floating or slide-out UI component that shows, for the last query:
  - List of nodes included in context, grouped by source (graph traversal vs vector vs summary).
  - For each node: ID, content excerpt, and *reason tags* (e.g. "Parent", "Semantic match 0.85", "Summary used", "Recency").
  - A “diff” view comparing Linear vs Graph contexts (highlighting nodes unique to each).
  - Token counts and time taken for each strategy.
- **Performance/Timing View:** Display of retrieval times (bars or text) for graph traversal, vector search, ranking, total.
- Buttons or toggles to show/hide inspector.
- **Metrics Logging:** Ensure every query logs:
  ```
  Strategy: Linear
  Nodes: X, Tokens: Y, Time: Z ms
  Strategy: Graph
  Nodes: A, Tokens: B, Time: C ms
  Relevant recall: ...
  ```
- **Demo Scenario**: Prepare a controlled conversation illustrating branching and merging. For example:
  ```
  User: I'm building an AI agent.
  Assistant: ...
      /branch "What about graphs vs vectors?"
  Assistant: ...
      \merge at 'graph and vectors synergy'
  ```
  The idea is to create branches (e.g. separate lines of inquiry) and then an intersection question.
- **Final Presentation Outline:** Include slides on Problem, Linear vs Graph representation, Context Engine design, Demo (act1,2,3), Comparison charts, Conclusions.

**Steps:**

1. **Context Inspector UI**. Implement a new UI component (e.g., a panel or modal):
   - Fetch the last `ContextResult` from both engines after each query.
   - Display in a table or list:
     ```
     [ID] [Role] [Content excerpt] [Source] [Reason] [Tokens]
     ```
     For example:
     `n12 | user | "discuss memory..." | Graph | Parent`
     `n05 | assistant | "Summary:..." | Graph | Summary`
   - Use color or icons to indicate Shared vs Only-Linear vs Only-Graph context. (E.g. ✓ for both, L for linear-only, G for graph-only).
   - Provide a “side by side diff” list:
     ```
     Linear-only nodes: [n8, n9, ...]
     Graph-only nodes: [n5(summary), n7, ...]
     Shared: [n1, n4, ...]
     ```
   - You can implement this as a toggleable HTML/CSS panel (if web UI) or as log output (if terminal).

2. **Performance Metrics**. After each context assembly:
   - Record `time_linear`, `time_graph`, `nodes_linear`, `nodes_graph`, `tokens_linear`, `tokens_graph`, `relevant_count`, `irrelevant_count`.
   - Display or log these. For UI, show a small overlay:
     ```
     Linear: 10 nodes, 1200 tokens, 15ms
     Graph: 8 nodes, 900 tokens, 42ms (breakdown: traverse=30ms, vector=8ms, rank=4ms)
     Recall: 8/8 relevant, 0 irrelevant | Graph saved 300 tokens
     ```
   - In context inspector, visualize bars or a table for quick comparison.

3. **Final Demo Scenario**. Script or manually run a conversation that:
   - Has at least one branch and one merge.
   - Involves questions where semantic retrieval might bring in nodes from other branches.
   - Include usage of summary to show effect.
   Run this scenario in both modes and capture outputs.

4. **Slide Outline**. Draft slides (no need to produce them, but include headings):
   - *Slide 1: Problem Illustration.* Show linear vs actual conversation graph.
   - *Slide 2: Limitations of Linear History.* (irrelevant vs missing context).
   - *Slide 3: Graph Representation.* Describe nodes/edges.
   - *Slide 4: Context Engine Architecture.* (Use earlier architecture diagram).
   - *Slide 5: Phase Progression.* List our phased approach (maybe a timeline).
   - *Slide 6: Demo Comparison.* Screenshots or text of Linear vs Graph contexts for same query.
   - *Slide 7: Performance Metrics.* Sample numbers and graphs.
   - *Slide 8: Conclusion.* State that graph-based context is **selective, structured, and explainable**. Mention future work.

**Data Structures / Schema (Phase 6):**
Not much new; we may augment `ContextResult`:
```json
{
  "strategy": "graph",
  "nodes_in_context": ["n1", "n3", "n5", "n10"],
  "reasons": {"n3":"Parent", "n5":"Semantic 0.92", "n10":"Summary"}
  // metrics logged separately
}
```

**API / Interfaces (Phase 6):**
- `ContextEngine.build_context()` should now return not only nodes but a structure with reasons and token counts.
- UI hooks: a way to retrieve these `ContextResult`s after each turn.

**Tests & Expected Results:**

- *UI Test:* Toggle strategies and ask a branching question. The context inspector should clearly list different nodes for each mode.
- *Metric Test:* In the logs or panel, metrics should update for each query.
- *Demo Test:* Walk through the prepared conversation. The Linear context should include irrelevant or stale info; Graph context should be tight and relevant (verify by inspection).

**Failure Modes & Recovery:**

- Performance UI might slow UI; make it optional.
- If no context (empty nodes), the diff UI should handle gracefully (just show none).
- Ensure clearing/hiding inspector between queries if needed.

**Instrumentation / Metrics:**

- Already covered: retrieval times, context sizes, recall/noise.
- Plot or chart can be created after logs.

**[DO THIS] Prompt:**  
```plaintext
**[DO THIS]**: Build the Context Observatory UI and logging. After each query, collect the context nodes and metrics from both Linear and Graph engines. Display them in a panel showing lists of nodes, reasons for inclusion, and token counts. Highlight differences (Linear-only vs Graph-only). Log performance metrics and token usage for comparison. Prepare one multi-branch test conversation and run it to demonstrate the outputs of both strategies side-by-side.
```

### Repository-specific implementation notes for Phase 6

Build the Context Observatory into the existing React/TypeScript WebUI.

Recommended placement:

```text
webui/src/components/thread/
├── ContextObservatory.tsx
├── ContextNodeList.tsx
└── ContextDiffView.tsx
```

Names are suggestions; follow current component conventions.

Wire it through `ThreadShell` so it is scoped to the active chat/pane. The repository already supports multiple chats/panes, so observatory state must be keyed by session/chat rather than held as one global "last query" object.

Backend exposure should return a **sanitized observability DTO**, not raw session files. A response can resemble:

```json
{
  "strategy": "graph",
  "nodes": [
    {
      "id": "node_123",
      "role": "user",
      "excerpt": "Discuss the database choice...",
      "source": "ancestor",
      "reason": "REPLY ancestor",
      "tokens": 12
    }
  ],
  "metrics": {
    "retrieval_ms": 3.8,
    "ranking_ms": 0.7,
    "token_count": 842,
    "candidate_nodes": 19,
    "returned_nodes": 8
  },
  "fallback": null
}
```

Do not expose private runtime-context metadata, filesystem paths, credentials, provider state, or hidden recovery records.

For the A/B comparison, resolve both strategies against the same persisted pre-turn session snapshot when practical. Only the user-selected strategy should feed the actual provider call; the other result is diagnostic so the comparison itself cannot alter the answer.

Add tests for:

- observatory payload sanitization,
- per-session/pane isolation,
- Graph vs Linear diff calculation,
- fallback visibility,
- metrics after page refresh,
- no regression in existing WebUI fork behavior.


---

## Optional: Future Strategies & Presentation

*(Implement on demand)*

- **Additional Toggles / Modes**: Beyond Linear/Graph, we could allow:
  - *Hybrid Mode:* always combine Linear + Graph context (not very distinct, but conceptually possible).
  - *Graph-only Recency:* Graph traversal but ignoring semantic (vector off).
  - *Vector-only:* ignore history edges, only rely on semantic search of all past messages.
  - These can be added as extra UI options.
- **Alternate Retrieval**: E.g. toggle *with summaries vs without summaries*, *with/without memory* etc.

- **Final Slide Structure**: Prepare a slide list (for reference):
  1. **Title Slide:** Project name and authors.
  2. **Motivation:** Why linear context is insufficient (diagram).
  3. **Context Graph Concept:** Show graph vs transcript (with citations).
  4. **Architecture:** The two-layer design (mermaid diagram).
  5. **Data Model:** Node/Edge schema (JSON example).
  6. **Phase Path:** Overview of layers 1-6 (flowchart diagram).
  7. **Demo 1:** Linear context example (screenshots/text).
  8. **Demo 2:** Graph context example (same query).
  9. **Inspector View:** Side-by-side context diff.
  10. **Performance:** Table or chart of metrics (tokens, latency).
  11. **Summary:** Key findings and next steps.

---

# Appendix: High-Level Flowchart of Phases

```mermaid
flowchart LR
    P1[Phase 1: Baseline & Toggle] --> P2[Phase 2: Graph & Branching]
    P2 --> P3[Phase 3: Graph Traversal Engine]
    P3 --> P4[Phase 4: Hybrid Retrieval & Summaries]
    P4 --> P5[Phase 5: Workflow DAG (optional)]
    P5 --> P6[Phase 6: Inspector & Metrics]
    P6 --> END[Final Demo & Evaluation]
```

# Appendix: References

- Context Graph concept: “Context graphs are knowledge graphs specifically optimized for AI model consumption, providing structured, semantically rich context”. This motivates our graph design.
- Knowledge graphs vs vectors: “Graphs store not just facts, but also how those facts connect… making answers more grounded and easier to explain than using only vectors”.
- Dynamic conversation graphs: In ThoughtDAG, *“Wires are the context. What the model sees is exactly what wires into the node”*, reflecting our use of edges to control context.
- Branching and context commands in [nanobot README](https://github.com/HKUDS/nanobot) (for reference on UI patterns).

---

# Appendix: Repository Implementation Map (`Srimano510/Git`)

Use this map when an implementation agent needs to translate the generic pseudocode in this guide into the actual repository.

| Concern | Existing repository owner | Context-Graph change |
|---|---|---|
| Canonical conversation persistence | `nanobot/session/manager.py` | Observe/synchronize; do not replace |
| Native baseline replay | `Session.get_history(...)` | Wrap as `LinearContextEngine` |
| Fresh user turn persistence | `nanobot/agent/loop.py` (`_persist_user_message_early`) | Keep strategy-independent |
| Turn/history handoff | `nanobot/agent/loop.py` (`_build_transcript_input`) | Supply selected history before this handoff |
| Final transcript construction | `nanobot/agent/context.py` (`ContextBuilder`, `TranscriptInput`) | Reuse unchanged where possible |
| Runtime context | `nanobot/runtime_context.py` + existing resolver path | Preserve; never rebuild in graph engine |
| Branch/fork UI | `webui/src/App.tsx`, `webui/src/components/thread/ThreadShell.tsx`, `webui/src/components/thread/ThreadViewport.tsx` | Instrument existing fork |
| Browser API client | `webui/src/lib/api.ts` | Add strategy/observatory calls if needed |
| Browser display thread | existing WebUI thread persistence/API | Visualization only; not model-context truth |
| Graph model/store | new `nanobot/context_graph/` package | Implement |
| Graph/vector tests | `tests/context_graph/` | Implement |
| Observatory UI | existing `webui/src/components/thread/` | Add panel/diff UI |

## Definition of done for the repository adaptation

The guide is being followed correctly if all of the following remain true:

1. Linear mode still uses nanobot's native replay semantics and is the default.
2. Graph mode changes history selection without duplicating the rest of the agent pipeline.
3. Existing WebUI session forking remains the user-visible branching mechanism.
4. A graph branch can span source and child nanobot sessions.
5. Context Graph persistence is separate from project files and recoverable on restart.
6. Graph failure cannot brick ordinary chat; it falls back to Linear.
7. The observatory explains what was selected without exposing private session/runtime data.
8. Existing tests continue to pass, and new tests cover graph behavior.
9. No generic code snippet in this guide should be copied literally when it conflicts with a repository-native API described in the Repository-Specific Integration Contract.

