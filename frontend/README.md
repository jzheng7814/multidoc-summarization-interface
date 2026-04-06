# Frontend Service

The frontend is a run-centric React application for the Multi-Document Summarization Interface. It owns the browser-side workflow, local editing state, document and evidence interaction, and the polling UI for extraction and summary jobs.

This frontend assumes a single-page application with client-side navigation only. It does not use React Router or a client-side data cache. The backend remains the source of truth for run state.

## Quick Start
```bash
npm install
npm run dev
```

By default, the frontend talks to `http://localhost:8000`. Override that with `VITE_BACKEND_URL` if your backend is running elsewhere.

## What The Frontend Owns
- Create a new backend run from the home screen.
- Navigate between `/` and `/run/<run_id>` using the browser history API.
- Let the user upload documents and configure extraction and summary settings for one run.
- Persist updated run configuration to the backend before extraction or summary starts.
- Poll extraction and summary status endpoints and render live waiting pages.
- Render the checklist review stage after extraction completes.
- Render the final workspace with checklist, summary, and document panes.
- Maintain local editing state for checklist edits, summary edits, version history, and highlight interactions.
- Translate user text selection into document evidence spans and checklist updates.

## Frontend Design Principles
- Run-centric UI: every page is driven by a backend `run_id`.
- Backend as source of truth: the frontend hydrates from backend snapshots, then manages only transient editing state locally.
- Minimal routing: top-level navigation is intentionally simple and based on `window.history`.
- Local composition over framework abstraction: shared state is handled with React hooks and context, not a full client state library.
- Stage-driven UX: the UI enforces setup, extraction wait, review, summary wait, and final workspace as separate screens.

## Subsystems
### App Shell And Navigation
Top-level bootstrapping lives in:
- `src/main.jsx`
- `src/App.jsx`

`App.jsx` is the only router. It:
- reads `window.location.pathname`
- parses `/run/<run_id>`
- pushes or replaces history entries
- renders either the home screen or the run flow page

There is no routing library. That keeps the app small, but it also means route parsing and navigation behavior are handwritten.

### Home Screen
The home screen lives in:
- `src/features/home/HomeScreen.jsx`

It does one thing:
- create a new run through the backend

After the backend returns a `run_id`, the app navigates to `/run/<run_id>`.

### Run Flow Orchestrator
The main workflow page lives in:
- `src/features/runFlow/RunFlowPage.jsx`

This file is the frontend's orchestration layer. It is responsible for:
- hydrating the run from the backend
- deriving the correct frontend stage from backend workflow state
- loading documents, checklist data, and summary text when needed
- handling stage transitions such as setup, review, and workspace
- starting extraction and summary generation
- persisting checklist edits before summary generation starts
- letting the user move backward from review to setup or from workspace back to review

If you want to understand how the frontend decides what screen to show, start here.

### Run Setup Page
Run setup lives in:
- `src/features/runFlow/RunSetupPage.jsx`

This page owns the initial configuration workflow:
- enter a run title
- upload `.txt` documents
- import, export, and edit extraction configuration
- import, export, and edit summary configuration
- validate the user-provided configuration locally before sending it to the backend
- load uploaded documents into the existing run
- start extraction only after the run has documents

The extraction configuration editor works directly against the controller-shaped JSON contract:
- `focus_context`
- `checklist_spec.checklist_items[]`
- per-item `key`, `description`, `user_instruction`, `constraints`, `max_steps`, and `reasoning_effort`

The summary configuration editor works directly against:
- `focus_context`
- `reasoning_effort`
- `max_steps`

### Waiting Pages
Long-running cluster-backed stages are rendered by:
- `src/features/runFlow/ExtractionWaitingPage.jsx`
- `src/features/runFlow/SummaryWaitingPage.jsx`

These pages are thin polling clients. They:
- call the relevant backend status endpoint every two seconds
- normalize the progress payload
- show SLURM state, current phase, tool name, and step counters when available
- transition back into the run flow when the backend reports success or failure

They do not maintain durable job state themselves. They only reflect backend state.

### Review And Final Workspace
The post-extraction review and final workspace screens live in:
- `src/features/runFlow/PostExtractionReviewPage.jsx`
- `src/features/runFlow/RunWorkspace.jsx`

The review page:
- shows only checklist and documents
- allows inline checklist editing
- blocks summary editing
- persists checklist changes before summary generation starts

The final workspace:
- shows checklist, summary, and documents together
- keeps the checklist read-only
- allows summary editing and version management
- supports toggling panes and resizing the workspace layout

### Shared Workspace State
The reusable workspace state layer lives in:
- `src/features/workspace/state/WorkspaceProvider.jsx`
- `src/features/workspace/state/useDocumentsStore.js`
- `src/features/workspace/state/useChecklistStore.js`
- `src/features/workspace/state/useSummaryStore.js`
- `src/features/workspace/state/useHighlightStore.jsx`

This layer is only instantiated for the review and workspace screens.

Its responsibilities are split as follows:
- `useDocumentsStore.js`
  - normalize the hydrated document snapshot
  - track the selected document
  - expose the current document text and document container ref
- `useChecklistStore.js`
  - hold checklist categories and flattened values
  - support add, edit, delete, and evidence-span updates
  - compute per-document highlight overlays from stored evidence offsets
- `useSummaryStore.js`
  - hold the current summary text
  - manage edit mode
  - manage saved versions
  - compute word-level patch actions for AI-generated summary diffs
- `useHighlightStore.jsx`
  - capture text selections in the summary or document viewer
  - compute selection offsets
  - jump to evidence spans in the document viewer
  - render active selection highlights with CSS Highlight API or overlay rectangles

The provider composes those stores and exposes them through React context.

### Workspace Components
The main workspace components live in:
- `src/features/workspace/DocumentsPanel.jsx`
- `src/features/workspace/components/ChecklistPage.jsx`
- `src/features/workspace/components/SummaryPanel.jsx`
- `src/features/workspace/components/SummaryPatchPanel.jsx`
- `src/features/workspace/components/DividerHandle.jsx`
- `src/features/workspace/documentLookup.js`

Their roles are:
- `DocumentsPanel.jsx`
  - render the selected document
  - allow document switching
  - render checklist evidence highlights
  - host the DOM container used for text selection and range offsets
- `ChecklistPage.jsx`
  - render categories and extracted values
  - support manual add, delete, edit, and evidence re-selection
  - navigate back to the referenced evidence span in the document viewer
- `SummaryPanel.jsx`
  - render the summary editor
  - manage summary version save/select interactions
  - render patch preview overlays from `useSummaryStore`
- `SummaryPatchPanel.jsx`
  - show individual word-level summary changes
  - preview, revert, or dismiss generated changes
- `DividerHandle.jsx`
  - provide draggable split-pane resizing in the final workspace

### Snapshot Translation
The run flow builds the initial workspace snapshot through:
- `src/features/runFlow/runSnapshot.js`

This file translates backend checklist categories into the flatter item list expected by the workspace checklist store. It is effectively the bridge between backend run payloads and the local workspace state model.

### API Client
All frontend API calls live in:
- `src/services/apiClient.js`

The API client is intentionally thin:
- one `request()` wrapper around `fetch`
- JSON handling and error normalization
- multipart upload helpers for document ingestion
- one function per backend route used by the UI

It is the only place that should know the backend base URL.

The frontend now assumes the backend wire contract is camelCase. Snake_case response compatibility has been removed from the browser code.

### Selection Utilities
Low-level selection and range math lives in:
- `src/utils/selection.js`

This module is shared by the document and summary highlight system. It handles:
- browser feature detection for CSS Highlight API
- offset extraction from DOM ranges
- DOM range reconstruction from stored offsets
- overlay rectangle computation
- scroll-to-range behavior

### Styling And Build
Frontend styling and build entrypoints live in:
- `src/index.css`
- `index.html`
- `vite.config.js`
- `package.json`

The app uses:
- React
- Vite
- Tailwind CSS 4 through CSS import
- CSS variables for theme tokens
- `lucide-react` for icons

The frontend is light-theme only. Color tokens are centralized in `src/index.css`.

## Run Lifecycle
### 1. Home
`/` renders the home screen and creates a new backend run.

### 2. Setup
`/run/<run_id>` initially renders the setup page. The user:
- enters a title
- uploads documents
- edits extraction config
- edits summary config
- loads the document corpus into the run

### 3. Extraction Wait
After extraction starts, the frontend polls the extraction status endpoint and shows live controller progress.

### 4. Review
After extraction succeeds, the frontend hydrates:
- documents
- checklist categories
- run metadata

The user can edit checklist values and evidence spans here.

### 5. Summary Wait
After the checklist is persisted and summary starts, the frontend polls the summary status endpoint and shows live summary job progress.

### 6. Workspace
After summary succeeds, the frontend hydrates the generated summary text and opens the final workspace. Revisiting `/run/<run_id>` later rehydrates the appropriate stage from backend state.

## Environment Variables
The frontend uses Vite-style environment variables.

| Variable | Purpose |
|----------|---------|
| `VITE_BACKEND_URL` | Base URL for the backend API. Defaults to `http://localhost:8000` when unset. |

## Key Files And Why They Matter
| Path | Responsibility |
|------|----------------|
| `src/App.jsx` | Top-level app shell and minimal client-side routing |
| `src/features/home/HomeScreen.jsx` | Run creation screen |
| `src/features/runFlow/RunFlowPage.jsx` | Main run-stage orchestration |
| `src/features/runFlow/RunSetupPage.jsx` | Document upload and config editing |
| `src/features/runFlow/ExtractionWaitingPage.jsx` | Extraction polling screen |
| `src/features/runFlow/PostExtractionReviewPage.jsx` | Checklist review screen before summary generation |
| `src/features/runFlow/SummaryWaitingPage.jsx` | Summary polling screen |
| `src/features/runFlow/RunWorkspace.jsx` | Final multi-pane workspace |
| `src/features/runFlow/runSnapshot.js` | Backend-to-workspace snapshot translation |
| `src/features/workspace/state/WorkspaceProvider.jsx` | Shared workspace context composition |
| `src/features/workspace/state/useDocumentsStore.js` | Local document-viewer state |
| `src/features/workspace/state/useChecklistStore.js` | Local checklist editing state |
| `src/features/workspace/state/useSummaryStore.js` | Local summary editing and version state |
| `src/features/workspace/state/useHighlightStore.jsx` | Text selection and highlight coordination |
| `src/features/workspace/DocumentsPanel.jsx` | Document viewer |
| `src/features/workspace/components/ChecklistPage.jsx` | Checklist editor/reviewer |
| `src/features/workspace/components/SummaryPanel.jsx` | Summary editor |
| `src/features/workspace/components/SummaryPatchPanel.jsx` | Summary diff and revert UI |
| `src/services/apiClient.js` | Backend HTTP client |
| `src/utils/selection.js` | DOM selection and range utilities |
| `src/index.css` | Global tokens and light theme |
