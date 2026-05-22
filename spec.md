# Spec: Refinery Streamlit App Revamp and Cloud Provider Fix

## Goals
- Resolve the issue where selecting "Cloud" in the Streamlit UI displays a warning that no cloud provider is active, even though `NOTICIENCIAS__NVIDIA__API_KEY` is configured in the `.env` file.
- Perform a complete revamp of the Streamlit App layout, design, and user experience to make it look premium, intuitive, and highly aligned with the project.
- Inject a global custom CSS design system (fonts, shadows, slate backgrounds, clean cards, hover states, metric highlights) for a polished, state-of-the-art UI/UX.

## Implementation Details

### 1. AI Provider Resolution
- In `apps/refinery/admin_panel.py`, unwrap the active provider if it's a `FallbackProvider` instance.
- Check if it has a `providers` attribute and is not empty; if so, assign the first item (`_active_provider.providers[0]`) to the resolved active provider variable.
- This ensures that:
  - `isinstance(actual_provider, NvidiaProvider)` and `isinstance(actual_provider, GeminiProvider)` checks succeed.
  - Model attributes are read directly from the underlying provider, avoiding AttributeError exceptions on `FallbackProvider`.

### 2. UI Restructuring
- Introduce a **persistent sidebar** to act as a dashboard header:
  - Display the project logo: Noticiencias Refinery.
  - Show the resolved Editorial Mode (Strict, Velocity, Standard) with a colored badge or card.
  - Show the resolved Active AI Engine details (provider type, specific model, status dot).
  - Show Database Status: active path, size on disk (in MB), and connection state.
  - Show Repository Status: source/target checkouts, branch info, commit hashes, Pages deploy health metrics.
- Group the main viewport tabs into:
  1. `🏠 Escritorio (Curation Desk)`: Focus area for ingestion, sync, and article refining. Includes manual URL load, ranked candidates list, and a clean curation panel for selected articles.
  2. `🖼️ Cola de Imágenes (Image Queue)`: View and edit briefs for articles lacking images, upload curated images.
  3. `🚀 Contenido Publicado (Live CMS)`: Display published posts, rigor metrics, Pages deploy status, and actions to unpublish/reset.
  4. `📡 Gestión de Fuentes (Source Manager)`: View feed status, latency, error reports, and manage RSS feeds.
  5. `🧠 Prompts (Prompt Lab)`: Edit prompts for translator, editor, and headlines stages.
  6. `⚙️ Configuración (Settings & Logs)`: Adjust scoring weights, keywords, Ollama endpoint, reset actions, and activity logs.

### 3. Styling Enhancements
- Load the Google Font `Outfit` for a modern, sleek typography.
- Inject CSS to color-code alert boxes (success, info, warning, error), tabs, and form buttons.
- Create container classes like `.refinery-card` for visual grouping.
- Replace basic text metrics with styled columns and progress bars illustrating score weights (`source_credibility`, `recency`, `content_quality`, `engagement_potential`) on selected candidates.

## Verification

### Automated Tests
- Run `make lint` to verify coding style and syntax.
- Run `make type` to verify static typing.
- Run `make test` to verify full unit tests.

### Manual Verification
- Launch the Streamlit panel locally using `make refinery`.
- Verify the cloud provider is correctly detected (displays NVIDIA NIM as active when the API key is set in `.env`).
- Verify visual improvements on the tabs, sidebar, and score progress bars.
