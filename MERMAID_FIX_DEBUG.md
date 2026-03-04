# Mermaid Diagram - Debug & Fix Flow

## Problem Identified

The placeholder `__MERMAID_BLOCK_1__` was appearing in the browser instead of being replaced with mermaid diagrams.

### Root Cause
The markdown library wraps text in `<p>` tags:
```html
<!-- What we got: -->
<p>__MERMAID_BLOCK_1__</p>

<!-- What the replacement was looking for: -->
__MERMAID_BLOCK_1__

<!-- No match = no replacement ❌ -->
```

## Solution Implemented

Changed from text placeholders to **HTML comments** which survive markdown processing:

### Before (❌ Broken)
```python
# Text placeholder gets wrapped in <p> tags by markdown
placeholder_key = f'__MERMAID_BLOCK_1__'  # → becomes <p>__MERMAID_BLOCK_1__</p>
```

### After (✅ Fixed)
```python
# HTML comments pass through markdown unchanged
placeholder = f'<!-- MERMAID_BLOCK_1 -->'  # → stays as <!-- MERMAID_BLOCK_1 -->
```

## Processing Flow (Fixed)

```
1. Markdown File
   ├─ ```mermaid
   │  graph LR
   │    A --> B
   │  ```

2. Extract with Regex
   └─ Replaced with: <!-- MERMAID_BLOCK_1 -->

3. Pass to Markdown Converter
   └─ HTML comments survive conversion

4. Find & Replace
   └─ Find:    <!-- MERMAID_BLOCK_1 -->
   └─ Replace: <div class="mermaid">graph LR A --> B</div>

5. Browser Renders
   └─ Mermaid.js converts <div> to visual diagram 🎉
```

## Code Changes

### File: `app.py`

**Function: `extract_and_process_mermaid()`**
- Changed: `__MERMAID_BLOCK_1__` → `<!-- MERMAID_BLOCK_1 -->`
- Reason: HTML comments survive markdown processing
- Added debug output to diagnose issues

**Function: `reinject_mermaid_divs()`**
- Fixed: Now looks for HTML comment placeholders
- Fixed: Code stored as integers (block_id) instead of string keys
- Fixed: Raw code is placed in `<div class="mermaid">` without HTML escaping
- Added debug: Shows what it finds and replaces

### Function: `view_tutorial()`
- Already correct: Calls both extraction and reinj ection functions

## How to Test

1. **Rebuild Docker:**
   ```bash
   docker-compose down
   docker-compose up --build
   ```

2. **Check Console Output:**
   Open terminal and look for debug output:
   ```
   [DEBUG] Extracted 1 mermaid blocks
   [DEBUG] Block 1: graph LR...
   [DEBUG] Reinjecting 1 mermaid blocks
   [DEBUG] Found placeholder 1, replacing it
   ```

3. **View Tutorial:**
   - Go to: `http://localhost:5000`
   - Generate a tutorial
   - Click on markdown file with mermaid diagrams
   - Should see **rendered flowcharts** not placeholder text ✅

## Expected Behavior Now

### Before (Broken) ❌
```
Tutorial shows:
__MERMAID_BLOCK_1__
__MERMAID_BLOCK_2__
```

### After (Fixed) ✅
```
Tutorial shows:
[Beautiful Flowchart]
[Another Diagram]
```

## Troubleshooting

### If placeholders still show:

1. **Check Docker logs:**
   ```bash
   docker-compose logs web
   ```
   Look for `[DEBUG]` output

2. **If extraction failed:**
   - Look for: `[DEBUG] Extracted 0 mermaid blocks`
   - Issue: Regex pattern not matching your markdown format

3. **If reinject failed:**
   - Look for: `[DEBUG] WARNING: Placeholder not found`
   - Issue: HTML comment syntax didn't survive markdown

### If diagrams still don't render:

1. **Check browser console (F12):**
   - Mermaid.js errors?
   - Script loading errors?

2. **Check Mermaid syntax:**
   - Ensure valid mermaid code
   - Test at: https://mermaid.live

## Files Modified

1. ✅ `app.py` - Fixed extraction and injection functions
2. ✅ `templates/viewer.html` - Already has Mermaid.js library

## Debug Output Example

When working correctly, you should see:
```
[DEBUG] Extracted 3 mermaid blocks
[DEBUG] Block 1: graph LR...
[DEBUG] Block 2: sequenceDiagram...
[DEBUG] Block 3: classDiagram...
[DEBUG] Reinjecting 3 mermaid blocks
[DEBUG] Found placeholder 1, replacing it
[DEBUG] Found placeholder 2, replacing it
[DEBUG] Found placeholder 3, replacing it
```

## Next Steps

After rebuilding with these changes:

1. Load a markdown file with mermaid diagrams
2. Check console output (terminal)
3. Verify flowcharts render in browser
4. If still issues, share the debug output from logs

The key fix: **HTML comments survive markdown, plain text doesn't!** 🎯
