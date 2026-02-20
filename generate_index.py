import ast
import glob
import os
from collections import defaultdict
import re

def get_module_name(filepath):
    # e.g. news_collector/system/pipeline.py -> news_collector.system.pipeline
    rel = os.path.relpath(filepath, '.')
    if rel.endswith('.py'):
        rel = rel[:-3]
    return rel.replace('/', '.')

def analyze_repo():
    files = glob.glob('news_collector/**/*.py', recursive=True)
    files = [f for f in files if not f.endswith('__init__.py') and not '/tests/' in f]
    
    modules = {}
    dependencies = defaultdict(list)
    used_by = defaultdict(list)
    
    for f in files:
        mod_name = get_module_name(f)
        try:
            with open(f, 'r', encoding='utf-8') as file:
                content = file.read()
            tree = ast.parse(content)
            
            docstring = ast.get_docstring(tree)
            role = "No summary available."
            if docstring:
                lines = docstring.strip().split('\n')
                for line in lines:
                    if line.strip():
                        role = line.strip()
                        break
            
            # Find imports
            imports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith('news_collector.'):
                            imports.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.startswith('news_collector'):
                        imports.add(node.module)
                    elif node.level > 0:
                        # relative import
                        parts = mod_name.split('.')
                        base = '.'.join(parts[:-node.level])
                        if node.module:
                            imports.add(f"{base}.{node.module}")
                        else:
                            imports.add(base)

            modules[mod_name] = {
                'path': f,
                'role': role[:120] + ('...' if len(role) > 120 else ''),
                'imports': sorted(list(imports))
            }
            
            for imp in imports:
                dependencies[mod_name].append(imp)
                used_by[imp].append(mod_name)
                
        except Exception as e:
            print(f"Error parsing {f}: {e}")

    # Give a score to select top 25 critical modules
    scores = {}
    for m in modules:
        score = 0
        text_lower = m.lower() + " " + modules[m]['role'].lower()
        if 'orchestrator' in text_lower or 'pipeline' in text_lower or 'engine' in text_lower or 'bootstrap' in text_lower:
            score += 10
        if 'contract' in text_lower or 'schema' in text_lower or 'interfaces' in text_lower:
            score += 8
        if 'api' in text_lower or 'client' in text_lower or 'http' in text_lower or 'collector' in text_lower or 'publisher' in text_lower:
            score += 6
        if 'db' in text_lower or 'database' in text_lower or 'storage' in text_lower or 'persistence' in text_lower:
            score += 8
        if 'logic' in text_lower or 'score' in text_lower or 'validat' in text_lower or 'enrich' in text_lower or 'editor' in text_lower:
            score += 5
            
        score += min(len(used_by[m]), 10) * 2
        score += min(len(dependencies[m]), 5)
        
        scores[m] = score

    top_modules = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:30]
    
    # Actually just take top 25 to be safe
    top_modules = top_modules[:25]
    
    out = []
    
    for m in top_modules:
        path = modules[m]['path']
        role = modules[m]['role'].split('.')[0] + '.'
        deps = [d.split('.')[-1] for d in dependencies[m] if d in modules]
        used = [u.split('.')[-1] for u in used_by[m] if u in modules]
        
        # fallback
        if not deps: deps = ['None']
        if not used: used = ['None']
        
        entry = (
            f"Module: {path}\n"
            f"Role: {role}\n"
            f"Dependencies: {', '.join(deps)}\n"
            f"Used by: {', '.join(used)}\n"
        )
        out.append(entry)
        
    md_content = "\n".join(out)
    
    os.makedirs('context', exist_ok=True)
    with open('context/MODULE_INDEX.md', 'w') as f:
        f.write(md_content)

    print("Done generating.")
    with open('context/MODULE_INDEX.md', 'r') as f:
        print(f.read())

if __name__ == '__main__':
    analyze_repo()
