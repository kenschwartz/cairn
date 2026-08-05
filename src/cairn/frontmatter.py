import yaml


def write_frontmatter(data: dict) -> str:
    dumped = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{dumped}---\n"
