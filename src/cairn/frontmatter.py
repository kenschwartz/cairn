import yaml
from pathlib import Path


def write_frontmatter(data: dict) -> str:
    dumped = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{dumped}---\n"


def read_frontmatter(path: Path) -> tuple[dict, str]:
    """
    Split a note into (frontmatter_dict, body_str).

    Rules per docs/decisions.md:
    - A note is `---\\n<yaml>\\n---\\n<rest>`. The leading `---` must be the first bytes.
    - frontmatter parsed with `yaml.safe_load`. `None` (empty block) -> `{}`.
    - body is everything after the closing `---\\n`, with no leading newline retained
      beyond what the file has.
    - No frontmatter block (file does not start with `---`) -> raise `ValueError`.

    Round-trips with write_frontmatter for the cairn field set.
    """
    content = path.read_text(encoding="utf-8")

    if not content.startswith("---"):
        raise ValueError(f"Missing frontmatter block: {path}")

    # Split on the closing fence
    parts = content.split("\n---\n", 1)
    if len(parts) != 2:
        raise ValueError(f"Malformed frontmatter block: {path}")

    # parts[0] starts with "---\n", strip that to get the YAML content
    yaml_content = parts[0][4:]  # Remove leading "---\n"
    body = parts[1]

    # Parse YAML, None -> {}
    fm_dict = yaml.safe_load(yaml_content)
    if fm_dict is None:
        fm_dict = {}

    return (fm_dict, body)
