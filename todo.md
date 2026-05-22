# Todo: Streamlit UI Revamp and Cloud Provider Fix

- [ ] **Phase 1: Fix AI Provider Unwrapping**
  - [ ] Implement `FallbackProvider` detection in `apps/refinery/admin_panel.py`.
  - [ ] Extract the primary provider (`providers[0]`) for type checks and attribute accesses.
  - [ ] Verify that cloud provider status resolves correctly (NVIDIA NIM / Gemini).

- [ ] **Phase 2: Global Styling and CSS Injection**
  - [ ] Inject custom Google Font (`Outfit`) and override global fonts.
  - [ ] Inject styled CSS overrides for Streamlit tabs, notification blocks, sidebar, buttons, and custom metric containers.
  - [ ] Add `.refinery-card` styles and colored dot status indicators.

- [ ] **Phase 3: Restructure Tabs and Implement Sidebar**
  - [ ] Implement the persistent sidebar displaying:
    - [ ] Logo / header.
    - [ ] Editorial mode card.
    - [ ] Active AI Engine detail.
    - [ ] Database parameters (path, size on disk, connection status).
    - [ ] Repo HEAD details and Pages deploy status.
  - [ ] Consolidate/reorder the tabs:
    - [ ] Tab 1: `🏠 Escritorio (Curation Desk)` (manual URL, sync, candidate list, curation panel with progress bar components).
    - [ ] Tab 2: `🖼️ Cola de Imágenes (Image Queue)`.
    - [ ] Tab 3: `🚀 Contenido Publicado (Live CMS)`.
    - [ ] Tab 4: `📡 Gestión de Fuentes (Source Manager)`.
    - [ ] Tab 5: `🧠 Prompts (Prompt Lab)`.
    - [ ] Tab 6: `⚙️ Configuración (Settings & Logs)` (scoring weights, keywords, Ollama API endpoints, reset system buttons, Activity Monitor timeline).

- [ ] **Phase 4: Verification and Quality Gate**
  - [ ] Run style linting check: `make lint` (or auto-fix if needed with `make lint-fix`).
  - [ ] Run static type checking: `make type`.
  - [ ] Verify unit tests pass: `make test`.
  - [ ] Manually test the Streamlit app layout and functionalities.
