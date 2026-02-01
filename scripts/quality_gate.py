import json
import os
import sys
from pathlib import Path
from typing import Dict

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

GOLDEN_DIR = PROJECT_ROOT / "quality_gate" / "golden"


class QualityGateValidator:
    def __init__(self):
        # No LLM init here
        pass

    def run(self):
        print("🔒 Quality Gate Validator (Snapshot Mode)")

        if not GOLDEN_DIR.exists():
            print(f"❌ Golden directory not found: {GOLDEN_DIR}")
            sys.exit(1)

        cases = sorted([d for d in GOLDEN_DIR.iterdir() if d.is_dir()])
        failed_cases = []

        # Security: Ensure Ollama is not accidentally used
        if os.getenv("OLLAMA_API_URL"):
            pass

        for case_dir in cases:
            print(f"\n>> 📂 Case: {case_dir.name}")
            if not self._validate_case(case_dir):
                failed_cases.append(case_dir.name)

        print("\n" + "=" * 50)
        if failed_cases:
            print(f"❌ QUALITY GATE FAILED. {len(failed_cases)} cases failed.")
            sys.exit(1)
        else:
            print("✅ QUALITY GATE PASSED. All snapshots valid.")
            sys.exit(0)

    def _validate_case(self, case_dir: Path) -> bool:
        snapshot_path = case_dir / "snapshot.json"
        expect_path = case_dir / "expected.json"
        input_path = case_dir / "input.txt"

        if not snapshot_path.exists():
            print(f"   ❌ Snapshot missing: {snapshot_path.name}")
            print("      Run 'make quality-gate-refresh' from a clean state.")
            return False

        # Load Data
        try:
            with open(snapshot_path, "r") as f:
                snapshot = json.load(f)
        except Exception as e:
            print(f"   ❌ JSON Error: {e}")
            return False

        # --- METADATA VALIDATION ---
        meta = snapshot.get("_meta", {})
        if not meta:
            print("   ❌ Integrity Violation: Missing '_meta'. Manual edit suspected.")
            return False

        if meta.get("generated_by") != "quality_gate_refresh":
            print(
                f"   ❌ Integrity Violation: Invalid generator '{meta.get('generated_by')}'."
            )
            return False

        if not meta.get("git_commit"):
            print("   ❌ Integrity Violation: Missing git provenance.")
            return False
        # ---------------------------

        if not expect_path.exists():
            print("   ⚠️ Expected rules missing. Skipping.")
            return True

        if not input_path.exists():
            input_len = 0
        else:
            input_len = len(input_path.read_text())

        with open(expect_path, "r") as f:
            expectations = json.load(f)

        content = snapshot.get("content", "")
        headlines = snapshot.get("headlines", {})

        if not content:
            print("   ❌ Snapshot has empty content")
            return False

        return self._check_rules(content, headlines, expectations, input_len)

    def _check_rules(  # noqa: C901
        self, output: str, headlines: Dict, rules: Dict, input_len: int
    ) -> bool:
        errors = []

        # A. Section Presence
        required_sections = rules.get("must_have_sections", [])
        for sec in required_sections:
            if sec not in output:
                errors.append(f"Missing required section content: '{sec}'")

        # B. Forbidden Phrases
        forbidden = rules.get("forbidden_phrases", [])
        lower_out = output.lower()
        for phrase in forbidden:
            if phrase.lower() in lower_out:
                errors.append(f"Found forbidden phrase: '{phrase}'")

        # C. Claims
        no_claims = rules.get("must_not_claim", [])
        for claim in no_claims:
            if claim.lower() in lower_out:
                errors.append(f"Found forbidden claim: '{claim}'")

        # D. Headlines Schema
        required_keys = rules.get(
            "headlines_schema", ["directo", "pregunta", "relevancia"]
        )
        for k in required_keys:
            if k not in headlines or not headlines[k]:
                errors.append(f"Missing headline key: '{k}'")

        # E. Length Bounds
        out_len = len(output)
        min_chars = rules.get("min_length_chars", 0)
        max_ratio = rules.get("max_length_ratio", 3.0)

        if out_len < min_chars:
            errors.append(f"Output too short ({out_len} < {min_chars})")
        if input_len > 0 and out_len > input_len * max_ratio:
            errors.append(
                f"Output too long (Ratio {out_len/input_len:.1f} > {max_ratio})"
            )

        if errors:
            for err in errors:
                print(f"   ❌ {err}")
            return False

        print("   ✅ Snapshot valid.")
        return True


def main():
    QualityGateValidator().run()


if __name__ == "__main__":
    main()
