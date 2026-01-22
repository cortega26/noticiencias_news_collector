
import sys
import os
from pathlib import Path
import yaml

# Add project root to path
sys.path.append(os.getcwd())

from news_collector.config import sources

def text_representer(dumper, data):
    if len(data.splitlines()) > 1:  # check for multiline string
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)

yaml.add_representer(str, text_representer)

def migrate():
    output_path = Path("news_collector/config/sources.yaml")
    
    # Map groups to their dictionaries
    groups = {
        "ELITE_JOURNALS": sources.ELITE_JOURNALS,
        "SCIENCE_MEDIA": sources.SCIENCE_MEDIA,
        "INSTITUTIONAL_SOURCES": sources.INSTITUTIONAL_SOURCES,
        "PREPRINT_SOURCES": sources.PREPRINT_SOURCES,
        "COMMUNITY_FEEDS": sources.COMMUNITY_FEEDS,
        "AI_LABS": sources.AI_LABS
    }
    
    # Check for implicit sources in ALL_SOURCES that might not be in a group (though sources.py defines ALL_SOURCES as a composition)
    
    final_yaml_data = {}
    
    for group_name, group_dict in groups.items():
        for source_id, config in group_dict.items():
            # Add implicit group tag for reconstruction
            config_copy = config.copy()
            config_copy["_group"] = group_name 
            final_yaml_data[source_id] = config_copy
            
    # Dump
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(final_yaml_data, f, sort_keys=False, allow_unicode=True, default_flow_style=False)
        
    print(f"Successfully migrated {len(final_yaml_data)} sources to {output_path}")

if __name__ == "__main__":
    migrate()
