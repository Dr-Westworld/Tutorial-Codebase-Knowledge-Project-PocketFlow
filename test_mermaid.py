#!/usr/bin/env python3
"""
Test script to verify mermaid extraction and injection works correctly.
Run this to debug mermaid diagram processing.

Usage:
    python test_mermaid.py
"""

import re

def test_extract_and_inject():
    """Test the mermaid extraction and injection functions."""

    # Simulate the functions from app.py
    def extract_and_process_mermaid(markdown_content):
        mermaid_blocks = {}
        placeholder_counter = [0]
        mermaid_pattern = r'```mermaid\s*\n(.*?)\n```'

        def extract_block(match):
            code = match.group(1).strip()
            placeholder_counter[0] += 1
            block_id = placeholder_counter[0]
            mermaid_blocks[block_id] = code
            placeholder = f'<!-- MERMAID_BLOCK_{block_id} -->'
            return placeholder

        modified_content = re.sub(mermaid_pattern, extract_block, markdown_content, flags=re.DOTALL)
        return modified_content, mermaid_blocks

    # Test markdown with mermaid diagram
    test_markdown = """# Test Tutorial

This is a test.

```mermaid
graph LR
    A[Town A] -- 10 --> B[Town B]
    A -- 6 --> C[Town C]
    C -- 4 --> D[Town D]
```

More text here.

```mermaid
graph TD
    Start[Start] --> Process[Process]
    Process --> End[End]
```

End of test.
"""

    print("=" * 60)
    print("MERMAID EXTRACTION TEST")
    print("=" * 60)

    # Extract
    print("\n1. EXTRACTING MERMAID BLOCKS...")
    modified, blocks = extract_and_process_mermaid(test_markdown)

    print(f"   Found {len(blocks)} mermaid blocks ✓")
    for block_id, code in blocks.items():
        print(f"\n   Block {block_id}:")
        print(f"   {code[:80]}...")

    # Simulate markdown processing (just show the placeholder)
    print("\n2. MARKDOWN CONVERSION (simulated)...")
    html_content = modified.replace('```', '').replace('markdown', '')
    print(f"   Placeholder format: {list(blocks.keys())}")

    # Check if placeholder is in HTML
    print("\n3. CHECKING PLACEHOLDER SURVIVAL...")
    for block_id, code in blocks.items():
        placeholder = f'<!-- MERMAID_BLOCK_{block_id} -->'
        if placeholder in html_content:
            print(f"   ✓ Block {block_id} placeholder found in HTML")
        else:
            print(f"   ✗ Block {block_id} placeholder NOT found in HTML")

    # Reinject
    print("\n4. REINJECTING MERMAID DIVS...")
    for block_id, code in blocks.items():
        placeholder = f'<!-- MERMAID_BLOCK_{block_id} -->'
        mermaid_div = f'<div class="mermaid">\n{code}\n</div>'
        html_content = html_content.replace(placeholder, mermaid_div)
        print(f"   ✓ Block {block_id} replaced with <div class=\"mermaid\">")

    # Verify
    print("\n5. VERIFICATION...")
    if '<div class="mermaid">' in html_content:
        count = html_content.count('<div class="mermaid">')
        print(f"   ✓ Found {count} mermaid divs in HTML")
    else:
        print(f"   ✗ No mermaid divs found in HTML!")

    if '<!-- MERMAID_BLOCK_' in html_content:
        print(f"   ✗ WARNING: Unprocessed placeholders still in HTML!")
    else:
        print(f"   ✓ All placeholders processed")

    print("\n" + "=" * 60)
    print("RESULT: SUCCESS ✓" if '<div class="mermaid">' in html_content and '<!-- MERMAID_BLOCK_' not in html_content else "RESULT: FAILED ✗")
    print("=" * 60)

    # Show sample output
    print("\nSAMPLE OUTPUT (first 300 chars):")
    print(html_content[:300])
    print("...")

if __name__ == '__main__':
    test_extract_and_inject()
