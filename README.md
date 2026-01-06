# Canvas Markdown Tools

Create and manage Canvas LMS course content using Markdown files. Write your course content in a simple, readable format and sync it to Canvas via the API.

## Features

- **Markdown to Canvas**: Write course content in Markdown, upload to Canvas
- **Canvas to Markdown**: Download existing courses for editing
- **Round-trip editing**: Download, edit, re-upload without duplicating content
- **Internal links**: Reference pages, assignments, discussions, and files with `[[Type:Name]]` syntax
- **Obsidian integration**: Templater templates for quick content creation

## Supported Content Types

| Type | Description |
|------|-------------|
| Module | Course modules/units |
| Header | Text headers within modules |
| Page | Wiki pages with content |
| Link | External URLs |
| File | Files from Canvas Files (PDFs, etc.) |
| Assignment | Assignments with points, due dates, submission types |
| Discussion | Discussion boards (threaded/focused, graded/ungraded) |

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/canvas-markdown-tools.git
cd canvas-markdown-tools

# Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install requests
```

## Quick Start

### 1. Get Your Canvas API Token

1. Log into Canvas
2. Go to Account → Settings
3. Scroll to "Approved Integrations"
4. Click "+ New Access Token"
5. Save the token securely (it's shown only once)

### 2. Download an Existing Course

```bash
python canvas_course_downloader.py my_course.md
```

You'll be prompted for:
- Canvas URL (e.g., `https://yourschool.instructure.com`)
- Course ID (from the URL: `/courses/12345`)
- API token

### 3. Edit the Markdown

Open `my_course.md` in any text editor or Obsidian. The format is human-readable:

```markdown
# Week 1 - Introduction

## [header] Readings

## [file] Course Syllabus
filename: syllabus.pdf

## [page] Welcome to the Course
Welcome to Ethics 101! Please read [[File:syllabus.pdf]] before our first class.

## [assignment] Introduction Post
points: 10
due: 2026-01-15 11:59pm
submission_types: online_text_entry
---
Introduce yourself to the class. Share your name, major, and why you're 
interested in ethics.
```

### 4. Upload Changes to Canvas

```bash
# Preview changes (no modifications made)
python canvas_course_builder.py my_course.md --dry-run

# Apply changes
python canvas_course_builder.py my_course.md
```

## Markdown Format Reference

### Module

```markdown
# Module Name
```

### Text Header

```markdown
## [header] Section Title
```

### Page

```markdown
## [page] Page Title
Page content goes here. You can use **bold**, *italic*, and other formatting.

You can link to other content:
- [[Page:Another Page]]
- [[Assignment:Homework 1]]
- [[Discussion:Week 1 Discussion]]
- [[File:reading.pdf]]
```

### External Link

```markdown
## [link] Link Title
url: https://example.com
```

### File

```markdown
## [file] Display Title
filename: actual-filename.pdf
```

If the display title matches the filename, you can omit `filename:`:

```markdown
## [file] syllabus.pdf
```

### Assignment

```markdown
## [assignment] Assignment Title
points: 10
due: 2026-01-15 11:59pm
grade_display: points
submission_types: online_text_entry, online_upload
---
Assignment instructions go here.
```

**Options:**
- `points`: Number (default: 0)
- `due`: Date/time in various formats
  - `2026-01-15 11:59pm`
  - `2026-01-15` (defaults to 11:59pm)
  - `Jan 15, 2026`
- `grade_display`: `complete_incomplete` (default), `points`, `not_graded`
- `submission_types`: Comma-separated list
  - `online_text_entry` (default)
  - `online_upload`
  - `online_url`
  - `media_recording`
  - `none`
  - `on_paper`

### Discussion

```markdown
## [discussion] Discussion Title
require_initial_post: true
threaded: false
graded: true
points: 5
due: 2026-01-15 11:59pm
grade_display: complete_incomplete
---
Discussion prompt goes here.
```

**Options:**
- `require_initial_post`: `true` or `false` (default)
- `threaded`: `true` (default) or `false`
- `graded`: `true` or `false` (default)
- If graded: `points`, `due`, `grade_display`

## Internal Links

Link to other content within your course using `[[Type:Name]]` syntax:

```markdown
Before starting [[Assignment:Homework 1]], please read [[File:chapter1.pdf]] 
and review [[Page:Course Policies]].

After completing the assignment, share your thoughts in 
[[Discussion:Week 1 Reflection]].
```

These links are automatically converted to proper Canvas URLs when you build the course.

## Obsidian Templates

The `obsidian-templates/` folder contains Templater templates for quick content creation.

### Setup

1. Install the [Templater](https://github.com/SilentVoid13/Templater) plugin in Obsidian
2. Copy the `obsidian-templates/` folder to your vault
3. Set the template folder location in Templater settings
4. (Optional) Set hotkeys:
   - `Canvas - Add Content`: Main template with dropdown menu
   - `Canvas - Internal Link`: Quick link insertion

### Available Templates

| Template | Description |
|----------|-------------|
| Canvas - Add Content | Main template - dropdown to choose content type |
| Canvas - Module | Create a module |
| Canvas - Header | Create a text header |
| Canvas - Page | Create a page |
| Canvas - Link | Create an external link |
| Canvas - File | Create a file item |
| Canvas - Assignment | Create an assignment with all options |
| Canvas - Discussion | Create a discussion with all options |
| Canvas - Internal Link | Insert a `[[Type:Name]]` link |

### Usage

1. Place cursor where you want to insert content
2. Run "Templater: Insert Template" (or use hotkey)
3. Select the template
4. Follow the prompts

## Round-Trip Workflow

The tools preserve Canvas IDs in HTML comments, enabling non-destructive updates:

```markdown
# Week 1 - Introduction
<!-- canvas_module_id: 123456 -->

## [page] Welcome
<!-- canvas_page_id: welcome-page -->
<!-- canvas_module_item_id: 789012 -->
Content here...
```

When you re-upload:
- **Items with IDs** → Updated in place
- **Items without IDs** → Created as new
- **Removed items** → Left unchanged in Canvas

This means you can safely:
- Edit content and descriptions
- Change due dates and points
- Reorder items within modules
- Add new content

Without creating duplicates.

## Configuration

You can set default values in the scripts to avoid repeated prompts:

```python
# In canvas_course_builder.py and canvas_course_downloader.py
DEFAULT_CANVAS_URL = "https://yourschool.instructure.com"
DEFAULT_COURSE_ID = "12345"
```

## Tips

1. **Start with a download**: Even for a new course, create modules in Canvas first, then download to get the structure.

2. **Use dry-run**: Always preview with `--dry-run` before applying changes.

3. **Upload files first**: Files must exist in Canvas Files before referencing them. Upload PDFs and other files through the Canvas web interface.

4. **Backup your markdown**: The markdown file is your source of truth. Keep it in version control.

5. **One course per file**: Each markdown file represents one Canvas course.

## Limitations

- **Quizzes**: Not fully supported (exported as links)
- **File uploads**: Files must already exist in Canvas Files
- **Rubrics**: Not supported
- **Groups**: Not supported
- **Conditional release**: Not supported

## License

MIT License - See LICENSE file for details.

## Contributing

Contributions welcome! Please open an issue or pull request.
