# Editorial Modes

Noticiencias implements three distinct "Editorial Modes" that govern the rigor and speed of the publication pipeline. These modes control the thresholds for the AI Critic (pre-generation) and the Editorial Auditor (post-generation).

## Configuration

Set the mode in `config/config.toml`:

```toml
[app]
editorial_mode = "standard"  # options: velocity, standard, strict
```

## Modes Overview

| Mode         | Critic Threshold | Auditor Threshold  | Caveats Required | Use Case                                              |
| :----------- | :--------------- | :----------------- | :--------------- | :---------------------------------------------------- |
| **Velocity** | **70.0**         | **0.0** (Advisory) | No               | Rapid breaking news, development, low-stakes content. |
| **Standard** | **80.0**         | **8.0**            | Yes              | **Default**. Balanced high-quality reporting.         |
| **Strict**   | **85.0**         | **8.5**            | **Yes**          | Medical/Scientific deep dives, high-risk topics.      |

### 1. Velocity Mode

- **Philosophy**: "Better fast than perfect."
- **Behavior**:
  - Critic accepts articles with a score of **7/10** or higher.
  - Auditor runs in the background but **never blocks** publication, regardless of the score.
  - Useful for high-volume ingestion or initial testing.

### 2. Standard Mode (Default)

- **Philosophy**: "Trust but verify."
- **Behavior**:
  - Critic threshold raised to **8/10** (previously 7).
  - **Auditor Check**: If an audit score exists (e.g., from a previous run or retry), it must be $\ge$ **8.0**.
  - **Fail-Open (Auditor)**: If no audit score is available efficiently (cache miss), the pipeline _proceeds_ to publish. The Auditor runs asynchronously to flag issues post-publication.

### 3. Strict Mode

- **Philosophy**: "Do no harm."
- **Behavior**:
  - Critic threshold raised to **8.5/10**.
  - **Auditor Check**: If an audit score exists, it must be $\ge$ **8.5**.
  - **Mandatory Caveats**: Articles making claims (especially medical) must include proper caveats/limitations.
  - **Hallucination Check**: Enables stricter fact-checking guardrails (if configured).

## Policy Logic

The logic is encapsulated in `news_collector.editorial.policy.EditorialPolicy`.

```python
# news_collector/editorial/policy.py
@dataclass
class EditorialPolicy:
    mode: str
    critic_threshold: float
    auditor_threshold: float
    require_caveats: bool
```

### Integration Points

1.  **Refinery Engine**:
    - Loads policy at startup.
    - Injects `critic_threshold` into the `EditorAgent`.
    - Checks `auditor.get_cached_score(id)` before creating a Pull Request.
2.  **Admin Panel**:
    - Displays the active mode and thresholds in the header.

## Changing Modes

To change the mode, edit `config.toml` and restart the `refinery` and `collector` services.

```bash
# Example: Switch to Velocity
sed -i 's/editorial_mode = "standard"/editorial_mode = "velocity"/' config/config.toml
```
