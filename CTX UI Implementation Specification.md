# **CTX UI Implementation Specification**

## **1\. Overview**

This document outlines the complete architectural and visual refactor of the ctx application UI, built on the Textual framework. The interface transitions from a standard scrolling chat to a dual-pane "Conversation Graph" (Right) and "Detail Inspector" (Left). The core philosophy emphasizes high-density information scanning via truncated nodes, coupled with a powerful, dynamic deep-dive panel.

## **2\. Global Layout Architecture**

The top-level ChatApp layout must be refactored into a fixed, rigid grid or docked layout system to ensure the split-view is permanently enabled.

### **2.1 Layout Hierarchy**

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

### **2.2 Global Bars**

* **Top Bar (Header):** A full-width Static or Horizontal container.  
  * *Left:* Active Conversation Title.  
  * *Center:* The CTX logo/text.  
  * *Right:* Total Context Window % used, paired with a visual progress bar (e.g., 60% \[==== \]).  
* **Bottom Bar (Footer):** A full-width Static widget docked to the bottom.  
  * Displays static, nano-style keybinding hints (e.g., ^C Cancel | Tab Switch Pane | / Commands).  
  * Updates dynamically based on the current mode (Insert vs. Edit).

## **3\. Right Pane: Conversation Graph**

This pane houses the MessageList and the user InputBar.

### **3.1 Message Widget (Node) Redesign**

Messages are no longer fully expanded by default. They are compressed nodes meant for scannability.

* **Truncation Rules:**  
  * Messages enforce a strict maximum height via CSS (or Textual's max\_height property).  
  * **Human / Assistant / Context:** Clamped to 2 lines by default.  
  * **App System:** (e.g., "changed model") Clamped to 1 line by default.  
  * *Configurable:* These default heights must be defined in \~/.config/ctx/config.json. Setting a value to "auto" disables truncation for that message type.  
* **Visual Styling:**  
  * **Left Border:** Continues to use a colored border indicating role.  
  * **Context Weight Indicator:** The percentage of context used by the specific node (e.g., 2%, 10%) must be strictly aligned to the **right edge** of the message container.  
  * **App System Messages:** Styled with a light grey color ($text-muted) and *italic* font.  
* **The "Big S" System Message:** The very first node representing the LLM System Prompt. Handled as a standard selectable node, but visually distinct (e.g., marked with "System Prompt").  
* **Selection State:** When focused in Edit Mode, the node gains a thick left border and a lightened background ($surface-lighten-1).

### **3.2 Conversation Passes (Spacing/Margin Logic)**

The MessageList must dynamically calculate vertical margins based on "Conversation Passes" (a Human's turn vs. the Assistant's turn).

* **Same Pass (0 Margin):** A Human query and the Contexts imported specifically for that query belong to the same pass. An Assistant response and Contexts imported by the Assistant belong to the same pass. No vertical space/margin between these nodes.  
* **Different Pass (1 Line Margin):** Transitioning from an Assistant node to a new Human node (or vice versa) constitutes a new pass. A margin-bottom: 1 or empty separator widget must be injected between them.

### **3.3 Input Bar**

* Remains at the bottom of the Right Pane.  
* Typing / triggers the \#command-suggestions overlay to appear *directly above* the input bar, inside the right pane.

## **4\. Left Pane: Detail Inspector**

The Left Pane is a highly reactive Container that swaps or updates its internal widgets based on the active node in the Right Pane.

### **4.1 Standard View (Human / Assistant / System)**

* Displays the **full, untruncated content** of the currently selected message.  
* Uses Textual's Markdown widget for rich text rendering.  
* Fully scrollable.

### **4.2 Context Node View (3-Split Layout)**

When a Context node is selected, the Left Pane divides into three vertically stacked, scrollable areas (VerticalScroll containers).

1. **Top (Prompt):** The prompt used for the import/compression.  
2. **Center (Full Content):** The raw text of the imported document.  
3. **Bottom (Output):** The resulting extracted text/summarization passed to the LLM.  
* **Ratio Rules:** The Center pane (Full Content) must be allocated a significantly larger height ratio than the Top and Bottom panes (e.g., via Textual fr units like height: 1fr for Top/Bottom, and height: 3fr for Center).  
* **Empty State Handling:** If a Context node lacks data for one of these areas (e.g., a direct file import with no prompt), that specific split must be completely hidden (display: none).  
* **Navigation:** Arrow keys *do not* navigate between these splits. Navigation is handled by dedicated strict keybindings (see Section 6).

## **5\. Modes and Real-Time Streaming**

### **5.1 Insert Mode (Typing State)**

* **Focus:** The InputBar is active.  
* **Detail Lock:** The Left Pane explicitly locks its view to the **last node** in the conversation graph.

### **5.2 Real-Time Streaming Behavior**

When the user submits a message, the LLM stream is routed to two places simultaneously:

1. **Right Pane (Preview):** The Assistant node is created and capped at its truncated limit (e.g., 2 lines). It updates, but visual overflow is hidden.  
2. **Left Pane (Full Stream):** Because the view is locked to the last node (the incoming Assistant response), the Left Pane actively renders the complete, unbound streaming text in real-time, auto-scrolling to the bottom as new tokens arrive.

### **5.3 Edit Mode (Navigation State)**

* **Focus:** The MessageList in the Right Pane is active.  
* **Navigation:** Up and Down arrows move the selection through *every* node.  
* **System Node Update:** App System messages are no longer skipped during navigation; they are fully selectable.  
* **Reactivity:** As the user arrows up/down, the Left Pane instantly updates to show the standard or 3-split view of the currently highlighted node.

## **6\. Keybindings Specification**

This matrix updates and expands the existing application keybindings.

| Key | Mode / Context | Action |
| :---- | :---- | :---- |
| Up / Down | Edit Mode | Move node selection up/down in the Right Pane. Updates Left Pane. |
| Esc | Global | Toggle between Insert Mode and Edit Mode. |
| Home (or mapped key) | Global | Jump directly to the "Big S" Root System Prompt node. |
| 1 | Edit Mode (Context Selected) | Maximize/Focus the Top Split (Prompt) in the Left Pane. |
| 2 | Edit Mode (Context Selected) | Maximize/Focus the Center Split (Content) in the Left Pane. |
| 3 | Edit Mode (Context Selected) | Maximize/Focus the Bottom Split (Output) in the Left Pane. |
| / | Insert Mode | Open command suggestion overlay above the input bar. |

## **7\. Configuration Updates**

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