import ast
import os


def parse_module_index():
    with open("context/MODULE_INDEX.md", "r") as f:
        content = f.read()

    modules = []
    current_module = {}
    for line in content.split("\n"):
        if line.startswith("Module: "):
            if current_module:
                modules.append(current_module)
            current_module = {"path": line[8:].strip()}
        elif line.startswith("Role: "):
            current_module["role"] = line[6:].strip()
        elif line.startswith("Dependencies: "):
            current_module["dependencies"] = line[14:].strip()
        elif line.startswith("Used by: "):
            current_module["used_by"] = line[9:].strip()

    if current_module:
        modules.append(current_module)

    return modules


def analyze_ast(filepath):
    if not os.path.exists(filepath):
        return ["None"], ["None"], ["None"], ["None"]

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        inputs = set()
        outputs = set()
        side_effects = set()
        failures = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                for arg in node.args.args:
                    if arg.arg != "self":
                        ann = getattr(arg, "annotation", None)
                        if isinstance(ann, ast.Name):
                            inputs.add(f"{arg.arg}: {ann.id}")
                        elif isinstance(ann, ast.Subscript):
                            try:
                                inputs.add(f"{arg.arg}: {ast.unparse(ann)}")
                            except:  # noqa: E722
                                inputs.add(arg.arg)
                        else:
                            inputs.add(arg.arg)

                if node.returns:
                    if isinstance(node.returns, ast.Name):
                        outputs.add(node.returns.id)
                    elif isinstance(node.returns, ast.Subscript):
                        try:  # noqa: SIM105
                            outputs.add(ast.unparse(node.returns))
                        except:  # noqa: E722, S110
                            pass

            elif isinstance(node, ast.Raise):
                if isinstance(node.exc, ast.Call) and isinstance(
                    node.exc.func, ast.Name
                ):
                    failures.add(node.exc.func.id)
                elif isinstance(node.exc, ast.Name):
                    failures.add(node.exc.id)
                elif isinstance(node.exc, ast.Attribute):
                    failures.add(node.exc.attr)

            elif isinstance(node, ast.ExceptHandler):
                if getattr(node, "type", None) is not None:
                    if isinstance(node.type, ast.Name):
                        failures.add(node.type.id)
                    elif isinstance(node.type, ast.Tuple):
                        for elt in node.type.elts:
                            if isinstance(elt, ast.Name):
                                failures.add(elt.id)

            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):  # noqa: SIM102
                    if isinstance(node.func.value, ast.Name):
                        if node.func.value.id in ["logger", "log"]:
                            side_effects.add("Logging")
                        if node.func.value.id in [
                            "requests",
                            "session",
                            "client",
                            "http_client",
                        ]:
                            side_effects.add("Network I/O")
                        if node.func.value.id in ["db", "session", "cursor", "engine"]:
                            side_effects.add("Database I/O")
                        if node.func.value.id in [
                            "os",
                            "sys",
                            "shutil",
                            "Path",
                            "open",
                        ]:
                            side_effects.add("File I/O")
            elif isinstance(node, ast.ClassDef):
                outputs.add(node.name)
                for body_node in node.body:
                    if isinstance(body_node, ast.AnnAssign) and isinstance(
                        body_node.target, ast.Name
                    ):
                        if isinstance(body_node.annotation, ast.Name):
                            inputs.add(
                                f"{body_node.target.id}: {body_node.annotation.id}"
                            )
                        else:
                            inputs.add(body_node.target.id)

        # Simplify sets
        if not inputs:
            inputs.add("None explicit")
        if not outputs:
            outputs.add("None explicit")
        if not side_effects:
            side_effects.add("None explicit")
        if not failures:
            failures.add("None explicit")

        return (
            sorted(list(inputs))[:8],
            sorted(list(outputs))[:8],
            sorted(list(side_effects))[:5],
            sorted(list(failures))[:5],
        )
    except Exception as e:
        print(f"Error analyzing {filepath}: {e}")
        return (
            ["None explicit"],
            ["None explicit"],
            ["None explicit"],
            ["None explicit"],
        )


def get_invariants(filepath):
    invs = []
    if "contracts" in filepath:
        invs.append("LAW-1: Data Contracts Are Mandatory")
    if "adapters" in filepath:
        invs.append("LAW-2: Adapters Are the Only Conversion Layer")
    if "system" in filepath:
        invs.append("LAW-3: System Layer Is Orchestration Only")

    if (
        "url" in filepath
        or "rss" in filepath
        or "collector" in filepath
        or "pipeline" in filepath
        or "logic" in filepath
    ):
        invs.append("LAW-4: Canonical Identity Is Immutable")

    if "rss" in filepath or "collector" in filepath:
        invs.append("LAW-5: Canonical URLs Are Deterministic & Immutable")

    if not invs:
        invs.append("Standard operational constraints apply")
    return invs


def generate():
    modules = parse_module_index()
    os.makedirs("context/modules", exist_ok=True)

    for m in modules:
        path = m["path"]
        role = m.get("role", "No role defined.")
        used_by = m.get("used_by", "None")

        inputs, outputs, side_effects, failures = analyze_ast(path)
        invariants = get_invariants(path)

        # mod_name matches exactly what users typically consider `<module_name>`. Using full relative path minus root
        # and extension to prevent collision e.g. 'news_collector/system/pipeline.py' -> 'system_pipeline.md'
        # Let's map e.g. news_collector/system/pipeline.py -> system_pipeline
        folder_path = path.replace("news_collector/", "").replace(".py", "")
        mod_name = folder_path.replace("/", "_")

        content = f"Module: {path}\n"
        content += f"Role: {role}\n"
        content += "Inputs:\n" + "\n".join([f"- {i}" for i in inputs]) + "\n"
        content += "Outputs:\n" + "\n".join([f"- {o}" for o in outputs]) + "\n"
        content += (
            "Side effects:\n" + "\n".join([f"- {s}" for s in side_effects]) + "\n"
        )
        content += "Invariants:\n" + "\n".join([f"- {i}" for i in invariants]) + "\n"
        content += "Failure modes:\n" + "\n".join([f"- {f}" for f in failures]) + "\n"

        used_by_list = [u.strip() for u in used_by.split(",")]
        content += "Used by:\n" + "\n".join([f"- {u}" for u in used_by_list]) + "\n"

        with open(f"context/modules/{mod_name}.md", "w") as f:
            f.write(content.strip() + "\n")

    print(f"Generated {len(modules)} context files in context/modules/")


if __name__ == "__main__":
    generate()
