# comfy-name-check

Check name availability across Comfy Registry, PyPI, GitHub, npm, and domains.

## Platforms Checked

| Platform | What's Checked |
|----------|----------------|
| Comfy Publisher | Publisher username availability |
| Comfy Node | Node package name (exact match) |
| PyPI | Package name (with PEP 503 normalization) |
| npm | Package name |
| GitHub User | Username availability |
| GitHub Org | Organization name availability |
| Domains | .com, .io, .org, .dev, .ai (via RDAP) |

## Installation

```bash
# From source
git clone https://github.com/akatz-ai/comfy-name-check.git
cd comfy-name-check
uv tool install .

# Or editable for development
uv tool install -e .
```

## Usage

```bash
# Check a single name
name-check my-cool-project

# Check multiple names (comma-separated)
name-check "cool-nodes,awesome-nodes,super-nodes"

# Skip certain platforms
name-check my-project --skip domain,npm

# Custom domain TLDs
name-check my-project --tlds com,io,dev

# Combine options
name-check "name1,name2" --skip github --tlds com,ai
```

## Example Output

```
Checking availability for: my-project

┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┓
┃ Platform        ┃ Status      ┃ Details        ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━┩
│ Comfy Publisher │ ✓ Available │                │
│ Comfy Node      │ ✓ Available │                │
│ PyPI            │ ✗ Taken     │                │
│ npm             │ ✗ Taken     │                │
│ GitHub User     │ ✓ Available │                │
│ GitHub Org      │ ✓ Available │                │
│ my-project.com  │ ✗ Taken     │ exp 2026-01-15 │
│ my-project.io   │ ✓ Available │                │
└─────────────────┴─────────────┴────────────────┘

4 available | 4 taken | 0 unknown
```

## Options

| Option | Description |
|--------|-------------|
| `--tlds` | Comma-separated TLDs to check (default: com,io,org,dev,ai) |
| `--skip` | Skip platforms: `comfy`, `pypi`, `npm`, `github`, `domain` |
| `--version` | Show version |
| `--help` | Show help |

## Rate Limits

- **GitHub**: 60 requests/hour unauthenticated. When checking multiple names, you may hit this limit.
- **Other platforms**: Generally no strict limits for reasonable usage.

## License

MIT
