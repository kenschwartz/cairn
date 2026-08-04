import yaml

from cairn.errors import CairnError


def write_frontmatter(data: dict) -> str:
    try:
        dumped = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    except yaml.YAMLError as exc:
        raise CairnError(f"could not serialise frontmatter: {exc}") from exc
    return f"---\n{dumped}---\n"
