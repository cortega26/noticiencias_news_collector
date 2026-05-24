# Spec: Malicious Prompt Injection Protection in News Ingestion

## Goals
- Protect the pipeline from executing malicious prompt injections embedded in scraped text during translation, editorial, and critic stages.
- Implement a static heuristic-based validation rule (`PromptInjectionGuardRule`) in the validation phase of the ingestion pipeline.
- Ensure 0% false positives on security-related articles that legitimately discuss prompt injections (e.g., Google Security Blog).

## Implementation Details

### 1. Verification of Inputs
- The rule will check the following fields of an incoming raw article dict: `title`, `content`, and `summary` (if present).

### 2. Detection Patterns (Case-Insensitive Regex)
- **Direct Injection Triggers**:
  - `ignore\s+(?:previous|all|the|prior)\s+instructions` / `ignora\s+(?:las\s+)?(?:instrucciones|órdenes)\s+(?:anteriores|previas)`
  - `forget\s+(?:my\s+)?(?:previous|all|prior)\s+instructions` / `olvida\s+(?:las\s+)?(?:instrucciones|reglas)\s+(?:anteriores|previas)`
  - `system\s+prompt` / `prompt\s+del\s+sistema`
  - `stop\s+translating` / `deja\s+de\s+traducir` / `no\s+traduzcas`
  - `ignore\s+the\s+text\s+(?:above|below)` / `ignora\s+el\s+texto\s+(?:de\s+)?(?:arriba|abajo)`
  - `\[system` / `\[instruction`

### 3. Exemption Patterns (Case-Insensitive Regex)
If a trigger matches, the article is allowed if it contains context indicating it is a legitimate news/security report:
- `"prompt injection"` / `"inyección de prompt"` / `"inyección indirecta"` / `"jailbreak"`
- `"cybersecurity"` / `"ciberseguridad"`
- `"security vulnerability"` / `"vulnerabilidad de seguridad"`
- `"security researcher"` / `"investigador de seguridad"`
- `"threat intelligence"` / `"inteligencia de amenazas"`
- `"google threat intelligence"`
- `"red team"` / `"equipo rojo"`
- `"vulnerabilities"` / `"vulnerabilidades"`
- `"common crawl"`
- `"adversarial"` / `"adversario"`
- `"ciberataque"` / `"cyberattack"`
- `"google security"`
- `"security blog"`

### 4. Integration
- Add `PromptInjectionGuardRule` to `news_collector/validation/rules.py`.
- Add `PromptInjectionGuardRule()` to `ContentValidator._get_default_rules` in `news_collector/validation/validator.py`.

## Verification

### Automated Tests
- Write a unit test `test_prompt_injection_guard_rule` in `tests/validation/test_validator.py` covering:
  - Malicious injection triggers.
  - Legitimate security news containing injection terminology (no false positives).
  - Normal articles without injection terms.
- Run quality checks:
  ```bash
  make lint
  make type
  make test
  ```
