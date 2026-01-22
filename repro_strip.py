
from pathlib import Path

def test_stripping():
    content = """
watchdog==6.0.0 \\
    --hash=sha256:07df1fdd701c5d4c8e55ef6cf55b8f0120fe1aef7ef39a1c6fc6bc2e606d517a
    # via
    #   noticiencias-news-collector (pyproject.toml)
    #   streamlit

# The following packages are considered to be unsafe in a requirements file:
pip==25.3 \\
    --hash=sha256:8d0538dbbd7babbd207f261ed969c65de439f6bc9e5dbd3b3b9a77f25d95f343 \\
    --hash=sha256:9655943313a94722b7774661c21049070f6bbb0a1516bf02f7c8d5d9201514cd
    # via pip-api
"""
    lines = content.splitlines()
    filtered_lines = []
    skipping = False

    for line in lines:
        # Keep empty lines, but reset skipping state
        if not line.strip():
            if skipping:
                skipping = False
                continue
            filtered_lines.append(line)
            continue

        # Check for start of a new package block (non-indented) or a warning block
        if line and not line[0].isspace():
            if (
                line.startswith("pip==")
                or line.startswith("# pip==")
                or "The following packages are considered to be unsafe" in line
            ):
                skipping = True
                print(f"Skipping ON: {line}")
            else:
                skipping = False
                print(f"Skipping OFF: {line}")

        if not skipping:
            filtered_lines.append(line)
        else:
            print(f"Skipped: {line}")

    result = "\n".join(filtered_lines)
    print("--- RESULT ---")
    print(result)

    if "pip==25.3" in result:
        print("FAIL: pip==25.3 still present")
    else:
        print("SUCCESS: pip==25.3 removed")

if __name__ == "__main__":
    test_stripping()
