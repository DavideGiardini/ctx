# **Product Concept Document: Context-Aware Terminal AI Assistant**

## **1\. Executive Summary**

This document outlines the design and architecture of a novel terminal-based AI assistant. Unlike existing CLI tools focused primarily on coding or task automation (like Claude Code or OpenCode), this application serves as a **context-aware conversation IDE**. It is designed for brainstorming, knowledge management, executing large personal projects, and coding, offering the user unprecedented, granular control over the context window.

The core philosophy is **power over protection**: the tool is built for technical users who demand 100% control over what the AI model sees. It informs visually but never blocks or auto-corrects. The interaction paradigm is a stateful Terminal User Interface (TUI) with vim-inspired modal controls, built in Python using the Textual framework.

## **2\. Core Architecture: Knowledge Base, Projects, and Conversations**

The application employs a repository/notebook mental model with three levels:

* **Knowledge Base (The Vault):** The directory you launch ctx from. *Its files are the KB* — the ambient ecosystem of available resources. The KB defines what *can* be imported but never automatically injects anything into active tasks.  
* **Project (The Environment):** A configured workspace attached to that directory, analogous to a Python virtual environment. A project owns its own config, conversations, and KB exclusions. **Multiple projects can share the same directory (and therefore the same KB)** — when a directory hosts more than one, launching ctx prompts you to choose which project to activate.  
* **Conversation (The Notebook/Node):** The active workspace where the user selectively and frictionlessly imports resources from the KB.

### **2.1 Storage Structure**

A project's data lives inside the directory it is launched from. The directory's own files *are* the KB; one or more projects attach to it under a .ctx/ marker, and multiple projects can share that same KB.

\~/.config/ctx/             ← Global config (e.g., MCP credentials, API keys)

\<launch directory\>/       ← The directory you run ctx in; its files ARE the KB    
├── docs/                  ┐    
├── notes/                 ├ Your existing files — the shared Knowledge Base    
├── ...                    ┘    
└── .ctx/                  ← Home for the project(s) attached to this directory    
    ├── alpha/             ← A project (venv-like): its own config & state    
    │   ├── .ignore        ← This project's KB exclusions    
    │   ├── config/        ← Providers, assistants, tools, prompts    
    │   └── conversations/ ← SQLite store for this project's chats    
    └── beta/    
        ├── .ignore        ← Distinct KB exclusions    
        ├── config/    
        └── conversations/

### **2.2 First Run Experience**

Upon initial launch, a one-time, fully terminal-driven setup wizard (similar to Claude Code) configures global settings (API keys, global config location). Subsequently, users run :project init within a directory to create a project rooted there, whose files become the project's KB. Because multiple projects can share one directory, when more than one is present launching ctx asks which project to activate — exactly like selecting a virtual environment.

## **3\. Knowledge Base (KB) and Imports**

The KB consists of everything in the project's launch directory (excluding files specified in .ignore), focusing initially on plain text files (Markdown, txt, code) and indexed conversations.

### **3.1 KB Access and Permission Modes**

The user has granular control over how an Assistant interacts with the KB within a specific conversation.

* **Access Modes:**  
  * **Isolated:** Assistant cannot search or auto-import anything.  
  * **Restricted:** Assistant can only search/import from a specified whitelist (specific files or folder/tag patterns).  
  * **Open:** Assistant has full KB access.  
* **Permission Modes:**  
  * **Automatic:** Assistant searches and imports freely within its Access Mode limits.  
  * **Accept:** The application prompts the user before every search and every chunk import.

**Note:** Regardless of the mode, the user can always manually import anything.

### **3.2 Import Mechanisms (Zero-Effort Pull/Push)**

Importing brings in a specialized compression relevant to the discussion, not the raw file. Every search and import is fully transparent, appearing as explicit nodes in the conversation.

* **Pull (From within current chat):**  
  * **Query (RAG):** User enters a query; system retrieves chunks; user approves/refines.  
  * **Search:** Manual selection of a specific file/chat.  
* **Push:** Navigate to a file/chat and explicitly push it into another target conversation.

### **3.3 Source File Synchronization**

To preserve the historical integrity of the conversation graph, all file imports are treated as static snapshots at the exact time of import. Nodes will never silently update if the underlying file is modified externally. To manage state drift:

* Staleness Indicator: If a source file is modified externally post-import, its corresponding node receives a subtle visual marker (e.g., a tilde \~) indicating the source has drifted.  
* Snapshot vs. Live View:  
  * 'gd' (Deep Dive): Opens the original snapshot (exactly what the LLM saw at the time).  
  * 'gD': Opens the current, live version of the source file to review external edits.  
* Re-importing: If the user wants the updated file in the context, they must explicitly trigger a manual re-import.

## **4\. Context Control and Compression**

This is the primary differentiator of the application. The conversation graph is fundamentally a 2D space: **Vertical \= time/sequence; Horizontal \= compression depth**. The rightmost column of any view is always the ground truth of what flows into the LLM.

### **4.1 The Compression Model**

Users can select a range of messages and compress them into a single node. The model only "sees" the compressed node, preventing context bloat.

* **Generation:** Always AI-drafted (using default project prompts, ad-hoc prompts, or manual entry) but always user-editable before committing.

### **4.2 Spatial Navigation**

Navigation through compression layers mimics standard developer workflows, using "go to definition" and code-folding mental models:

* **Deep Dive (gd / Ctrl+o):**  
  * Placing the cursor on a compressed node and pressing gd acts as "go to definition." It triggers a full view replacement, swapping the screen to show the underlying origin blocks of that node.  
  * A breadcrumb trail (e.g., Chat \> Compressed Node \> Source 2\) tracks depth.  
  * Pressing Ctrl+o (go back) returns you up one level.  
* **Inline Folding (zo / zc / zR / zM):**  
  * Users can "unfold" (zo) a compressed node inline without leaving the conversation view.  
  * Expanded inline blocks are heavily marked visually (e.g., \[expanded · not in context\]).  
  * The parent compressed node remains visible and is anchored to the right of the expanded block.  
  * zR unfolds the entire conversation; zM folds everything back to maximum compression.

### **4.3 Reversibility**

There is no global linear undo history. Instead:

* **Per-Node Reversal:** Every operation is explicitly reversible on the node itself (:expand to completely uncompress and destroy the node, :remove to remove an import).  
* **History Log:** A :history command shows a full log of context operations for selective reversal. Nothing is truly deleted.

## **5\. Branching and Sub-Chats**

* **Branches:** You can branch from any point. Branches appear as inline tabs (Branch1, Branch2) at the fork point.  
* **Sub-chats:** A sub-chat is simply a branch that was later re-imported (and compressed) back into the parent conversation.  
* **Indexing:** An orthogonal property. An "indexed" conversation can be searched/imported by other chats. Moving a chat from indexed to not-indexed effectively "archives" it, making it private.  
* **Titles:** Conversation titles are auto-generated from the first message/exchange by default, but are always manually overridable.

## **6\. Assistants and Tools**

### **6.1 Assistants**

Defined at the project level, an Assistant is a starting configuration that modifies behavior, never content. Switching assistants mid-conversation has no side effects on prior context. An Assistant configuration includes:

* System Prompt  
* Default Model \+ Provider  
* Default auto-invokable tools  
* Default compression prompts

### **6.2 Tools and MCPs**

A two-tier configuration system:

* **Global Registry:** Defined in \~/.config/ctx/ (stores server URLs, credentials).  
* **Project Activation:** The project specifies which global tools are enabled.  
* **Assistant Invocation:** Assistants specify which active tools they can auto-invoke.  
* **Manual Invocation:** Users can manually invoke any active tool using the / command.

## 

## **7\. Interaction Paradigm and UI Layout**

### **7.1. Overview**

This document outlines the complete architectural and visual refactor of the ctx application UI, built on the Textual framework. The interface transitions from a standard scrolling chat to a dual-pane "Conversation Graph" (Right) and "Detail Inspector" (Left). The core philosophy emphasizes high-density information scanning via truncated nodes, coupled with a powerful, dynamic deep-dive panel.

### 

### **7.2. Global Layout Architecture**

The top-level ChatApp layout must be refactored into a fixed, rigid grid or docked layout system to ensure the split-view is permanently enabled.

#### 

#### **7.2.1 Layout Hierarchy**

┌─────────────────────────────────────────────────────────────┐  
│ Header (Top Bar) \- Docked Top                               │  
├─────────────────────────────┬───────────────────────────────┤  
│ Left Pane (Detail Panel)    │ Right Pane (Conversation)     │  
│                             │                               │  
│ \[Dynamic Content based on   │ \[Scrollable MessageList\]      │  
│  active/selected node\]      │                               │  
│                             │                               │  
│                             │ ┌───────────────────────────┐ │  
│                             │ │ /command overlay (hidden) │ │  
│                             │ │ Input Bar                 │ │  
│                             │ └───────────────────────────┘ │  
├─────────────────────────────┴───────────────────────────────┤  
│ Footer (Bottom Bar) \- Docked Bottom                         │  
└─────────────────────────────────────────────────────────────┘

#### **7.2.2 Global Bars**

* **Top Bar (Header):** A full-width Static or Horizontal container.  
  * *Left:* Active Conversation Title.  
  * *Center:* The CTX logo/text.  
  * *Right:* Total Context Window % used, paired with a visual progress bar (e.g., 60% \[==== \]).  
* **Bottom Bar (Footer):** A full-width Static widget docked to the bottom.  
  * Displays static, nano-style keybinding hints (e.g., ^C Cancel | Tab Switch Pane | / Commands).  
  * Updates dynamically based on the current mode (Insert vs. Edit).

### 

### **7.3. Right Pane: Conversation Graph**

This pane houses the MessageList and the user InputBar.

#### 

#### **7.3.1 Message Widget (Node) Redesign**

Messages are no longer fully expanded by default. They are compressed nodes meant for scannability.

* **Truncation Rules:**  
  * Messages enforce a strict maximum height via CSS (or Textual's max\_height property).  
  * **Human / Assistant / Context:** Clamped to 2 lines by default. Can be changed in config. The truncation specification should behave like a maximum: if a message is shorter than it should only occupy a proportional amount of lines, up to two (or more if specified in config).  
  * **App System:** (e.g., "changed model") Clamped to 1 line by default.  
  * *Configurable:* These default heights must be defined in \~/.config/ctx/config.json. Setting a value to "auto" disables truncation for that message type.  
* **Visual Styling:**  
  * **Left Border:** Continues to use a colored border indicating role.  
  * **Context Weight Indicator:** The percentage of context used by the specific node (e.g., 2%, 10%) must be strictly aligned to the **right edge** of the message container.  
  * **App System Messages:** Styled with a light grey color ($text-muted) and *italic* font.  
* **The "Big S" System Message:** The very first node representing the LLM System Prompt. Handled as a standard selectable node, but visually distinct (e.g., marked with "System Prompt").  
* **Selection State:** When focused in Edit Mode, the node gains a thick left border and a lightened background ($surface-lighten-1).

#### 

#### **7.3.2 Conversation Passes (Spacing/Margin Logic)**

The MessageList must dynamically calculate vertical margins based on "Conversation Passes" (a Human's turn vs. the Assistant's turn).

* **Same Pass (0 Margin):** A Human query and the Contexts imported specifically for that query belong to the same pass. An Assistant response and Contexts imported by the Assistant belong to the same pass. No vertical space/margin between these nodes.  
* **Different Pass (1 Line Margin):** Transitioning from an Assistant node to a new Human node (or vice versa) constitutes a new pass. A margin-bottom: 1 or empty separator widget must be injected between them.

#### 

#### **7.3.3 Input Bar**

* Remains at the bottom of the Right Pane.  
* Typing / triggers the \#command-suggestions overlay to appear *directly above* the input bar, inside the right pane.

### 

### **7.4. Left Pane: Detail Inspector**

The Left Pane is a highly reactive Container that swaps or updates its internal widgets based on the active node in the Right Pane.

#### **7.4.1 Standard View (Human / Assistant / System)**

* Displays the **full, untruncated content** of the currently selected message.  
* Uses Textual's Markdown widget for rich text rendering.  
* Fully scrollable.

#### **7.4.2 Context Node View (3-Split Layout)**

When a Context node is selected, the Left Pane divides into three vertically stacked, scrollable areas (VerticalScroll containers).

* **Top (Prompt):** The prompt used for the import/compression.  
* **Center (Full Content):** The raw text of the imported document.  
* **Bottom (Output):** The resulting extracted text/summarization passed to the LLM.  
* **Ratio Rules:** The Center pane (Full Content) must be allocated a significantly larger height ratio than the Top and Bottom panes (e.g., via Textual fr units like height: 1fr for Top/Bottom, and height: 3fr for Center).  
* **Empty State Handling:** If a Context node lacks data for one of these areas (e.g., a direct file import with no prompt), that specific split must be completely hidden (display: none).  
* **Navigation:** Arrow keys *do not* navigate between these splits. Navigation is handled by dedicated strict keybindings (see Section 6).

## 

### **7.5. Modes and Real-Time Streaming**

#### **7.5.1 Insert Mode (Typing State)**

* **Focus:** The InputBar is active.  
* **Detail Lock:** The Left Pane explicitly locks its view to the **last node** in the conversation graph.

#### 

#### **7.5.2 Real-Time Streaming Behavior**

When the user submits a message, the LLM stream is routed to two places simultaneously:

* **Right Pane (Preview):** The Assistant node is created and capped at its truncated limit (e.g., 2 lines). It updates, but visual overflow is hidden.  
* **Left Pane (Full Stream):** Because the view is locked to the last node (the incoming Assistant response), the Left Pane actively renders the complete, unbound streaming text in real-time, auto-scrolling to the bottom as new tokens arrive.

#### 

#### **7.5.3 Edit Mode (Navigation State)**

* **Focus:** The MessageList in the Right Pane is active.  
* **Navigation:** Up and Down arrows move the selection through *every* node.  
* **System Node Update:** App System messages are no longer skipped during navigation; they are fully selectable.  
* **Reactivity:** As the user arrows up/down, the Left Pane instantly updates to show the standard or 3-split view of the currently highlighted node.

### 

### **7.6. Keybindings Specification**

This matrix updates and expands the existing application keybindings.  
| **Key** | **Mode / Context** | **Action** |  
| Up / Down | Edit Mode | Move node selection up/down in the Right Pane. Updates Left Pane. |  
| Esc | Global | Toggle between Insert Mode and Edit Mode. |  
| Home (or mapped key) | Global | Jump directly to the "Big S" Root System Prompt node. |  
| 1 | Edit Mode (Context Selected) | Maximize/Focus the Top Split (Prompt) in the Left Pane. |  
| 2 | Edit Mode (Context Selected) | Maximize/Focus the Center Split (Content) in the Left Pane. |  
| 3 | Edit Mode (Context Selected) | Maximize/Focus the Bottom Split (Output) in the Left Pane. |  
| / | Insert Mode | Open command suggestion overlay above the input bar. |

## 

### **7.7. Configuration Updates**

The \~/.config/ctx/config.json must be updated to support the new layout variables.  
{  
  "ui": {  
    "truncation\_lines": {  
      "human": 2,  
      "assistant": 2,  
      "context": 2,  
      "system": 1  
    }  
  }  
}

*(Setting any of these values to "auto" in the config parsing logic must apply height: auto to the widget, disabling truncation).*