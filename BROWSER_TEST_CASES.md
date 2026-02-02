# Browser Sub-Agent Test Cases

Run these test cases to verify the browser sub-agent integration is working correctly.

## ✅ Simple Extraction Tests

### Test 1: Extract Heading
```bash
uv run proxi "Visit example.com and extract the main heading text"
```
**Expected:** Should navigate to example.com, extract "Example Domain" heading, complete in 2 steps.

### Test 2: Extract Page Title
```bash
uv run proxi "Go to example.com and tell me the page title"
```
**Expected:** Should return "Example Domain" as the title.

### Test 3: Describe Page
```bash
uv run proxi "Open example.com and describe what you see - just the main content, don't click anything"
```
**Expected:** Should describe the heading, paragraph text, and "More information" link without clicking.

## 🔍 Search & Navigation Tests

### Test 4: Wikipedia Main Page
```bash
uv run proxi "Go to en.wikipedia.org and tell me the main heading"
```
**Expected:** Should navigate to English Wikipedia and extract the main heading.

### Test 4b: Wikipedia Search (Advanced - may have issues)
```bash
uv run proxi "Go to en.wikipedia.org, search for 'Python programming', and tell me the title of the article"
```
**Expected:** Should search Wikipedia. May have issues due to JavaScript-based search. Consider this an advanced test.

### Test 5: Multi-Step Navigation
```bash
uv run proxi "Visit example.com, click the 'More information' link, and tell me where it takes you"
```
**Expected:** Should click the link and report the final URL (likely iana.org).

## 📊 Data Extraction Tests

### Test 6: Extract Multiple Elements
```bash
uv run proxi "Go to example.com and list all the visible links on the page"
```
**Expected:** Should extract and list the links (probably just "More information" link).

### Test 7: Extract Specific Information
```bash
uv run proxi "Visit example.com and tell me what the first paragraph says"
```
**Expected:** Should extract and return the paragraph text.

## 🧪 Edge Cases

### Test 8: Non-Existent Page
```bash
uv run proxi "Visit example.com/nonexistent and tell me what happens"
```
**Expected:** Should handle 404 page gracefully.

### Test 9: Multiple Pages
```bash
uv run proxi "Visit example.com, then visit wikipedia.org, and tell me both page titles"
```
**Expected:** Should navigate to both and report both titles.

## 🎯 Complex Tasks

### Test 10: Direct Wikipedia Article
```bash
uv run proxi "Go to https://en.wikipedia.org/wiki/Tokyo and extract what you can about Tokyo from the visible content"
```
**Expected:** Should navigate to Tokyo article and extract visible information. Note: Detailed data extraction from Wikipedia infoboxes is challenging.

### Test 10b: Simpler Wikipedia Task  
```bash
uv run proxi "Go to https://en.wikipedia.org/wiki/Earth and tell me the first paragraph"
```
**Expected:** Should extract the introduction paragraph successfully.

### Test 11: Comparison Task
```bash
uv run proxi "Visit example.com and tell me if it has a search box"
```
**Expected:** Should inspect the page and report whether search functionality exists.

## 🚫 What Should NOT Work (Expected Limitations)

### Test 12: Login Required
```bash
uv run proxi "Log into github.com with username 'test' and password 'test'"
```
**Expected:** Will attempt but likely fail (and that's okay - this is a limitation).

### Test 13: JavaScript Heavy Sites
```bash
uv run proxi "Go to a React app and extract data"
```
**Expected:** May have issues with heavily dynamic content that loads after initial render.

## 📝 Running Tests

### Quick Smoke Test
Run this to quickly verify everything works:
```bash
uv run proxi "Visit example.com and extract the main heading"
```

### Headless Mode
To run without showing browser window, edit `proxi/cli/main.py` and set `headless=True`.

### Adjust Max Steps
If tasks are timing out, increase `max_steps` in `proxi/cli/main.py`:
```python
browser_agent = BrowserAgent(
    headless=False,
    max_steps=8,  # Current setting - good for most tasks
    # max_steps=15,  # Increase for very complex multi-step tasks
    ...
)
```

**Guidelines:**
- Simple extraction (1 page): 3-5 steps
- Multi-step navigation: 5-8 steps
- Complex tasks (search, form fill): 8-15 steps

## 🐛 Troubleshooting

**Multiple browsers opening:**
- This means the main agent is calling the browser sub-agent multiple times
- Check that result_data is being populated correctly
- Verify the summary includes extracted data

**Browser not closing:**
- Press Ctrl+C to interrupt
- Browsers should close automatically when task completes

**Task fails immediately:**
- Check OPENAI_API_KEY is set
- Verify playwright chromium is installed: `uv run playwright install chromium`

**Browser hangs/freezes:**
- Reduce max_steps (currently set to 8)
- Some websites have complex JavaScript that may cause issues

**Task keeps scrolling/clicking without progress:**
- The snapshot may not be capturing the data you need (e.g., Wikipedia infoboxes, tables)
- Try a more direct task: instead of "find X", use "extract the first paragraph"
- Or provide a direct URL: "Go to [specific URL] and tell me what you see"

**Wikipedia-specific issues:**
- Infoboxes (population, dates, etc.) are in structured tables not fully captured by snapshots
- Use direct article URLs (https://en.wikipedia.org/wiki/Tokyo) rather than search
- Ask for "visible content" or "first paragraph" rather than specific data points from infoboxes

## 📊 Success Criteria

A successful test should:
1. ✅ Open browser window (if headless=False)
2. ✅ Navigate to the target URL
3. ✅ Complete task in reasonable steps (typically 2-5)
4. ✅ Return extracted data in response
5. ✅ Close browser automatically
6. ✅ NOT open multiple browser windows for single task

## 💡 Tips

- **Be specific:** "Extract the heading" works better than "tell me about the page"
- **Limit scope:** "Just the main heading, don't click" prevents over-exploration
- **Check logs:** Watch for "📸 Page snapshot" to see what the browser sees
- **Step count:** Step 1 = blank page, Step 2 = after navigation, Step 3+ = interactions
