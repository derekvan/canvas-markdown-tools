#!/usr/bin/env python3
"""
Canvas Course Downloader
Downloads a Canvas LMS course into a structured Markdown file.

Usage:
    python canvas_course_downloader.py [output_file.md] [OPTIONS]

Options:
    --reset-token   Force re-prompt for API token and update Keychain

The output file can be edited and re-uploaded using canvas_course_builder.py
"""

import re
import sys
import requests
import keyring
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional
from html.parser import HTMLParser

# =============================================================================
# Configuration - can be set here or provided at runtime
# =============================================================================

DEFAULT_CANVAS_URL = ""  # e.g., "https://kent.instructure.com"
DEFAULT_COURSE_ID = ""   # e.g., "126998"

# =============================================================================
# HTML to Markdown Converter (simple)
# =============================================================================

class HTMLToMarkdown(HTMLParser):
    """Simple HTML to Markdown converter."""
    
    def __init__(self):
        super().__init__()
        self.result = []
        self.current_href = None
        self.in_list = False
        self.list_type = None
        self.list_index = 0
        self.in_file_link = False
        self.file_link_text = []
        
    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        
        if tag == 'p':
            pass  # Will add newlines on end tag
        elif tag == 'br':
            self.result.append('\n')
        elif tag == 'strong' or tag == 'b':
            self.result.append('**')
        elif tag == 'em' or tag == 'i':
            self.result.append('*')
        elif tag == 'a':
            self.current_href = attrs_dict.get('href', '')
            # Check if this is a Canvas file link
            if self.current_href and '/files/' in self.current_href:
                self.in_file_link = True
                self.file_link_text = []
                self.result.append('[[File:')
            else:
                self.result.append('[')
        elif tag == 'img':
            alt = attrs_dict.get('alt', 'image')
            src = attrs_dict.get('src', '')
            self.result.append(f'![{alt}]({src})')
        elif tag == 'h1':
            self.result.append('\n### ')  # Demote since # is for modules
        elif tag == 'h2':
            self.result.append('\n#### ')
        elif tag == 'h3':
            self.result.append('\n##### ')
        elif tag == 'h4' or tag == 'h5' or tag == 'h6':
            self.result.append('\n###### ')
        elif tag == 'ul':
            self.in_list = True
            self.list_type = 'ul'
            self.result.append('\n')
        elif tag == 'ol':
            self.in_list = True
            self.list_type = 'ol'
            self.list_index = 0
            self.result.append('\n')
        elif tag == 'li':
            if self.list_type == 'ol':
                self.list_index += 1
                self.result.append(f'{self.list_index}. ')
            else:
                self.result.append('- ')
        elif tag == 'blockquote':
            self.result.append('\n> ')
        elif tag == 'code':
            self.result.append('`')
        elif tag == 'pre':
            self.result.append('\n```\n')
    
    def handle_endtag(self, tag):
        if tag == 'p':
            self.result.append('\n\n')
        elif tag == 'strong' or tag == 'b':
            self.result.append('**')
        elif tag == 'em' or tag == 'i':
            self.result.append('*')
        elif tag == 'a':
            if self.in_file_link:
                # Close the [[File:...]] format
                self.result.append(']]')
                self.in_file_link = False
                self.file_link_text = []
            else:
                # Regular link
                self.result.append(f']({self.current_href})')
            self.current_href = None
        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self.result.append('\n')
        elif tag == 'ul' or tag == 'ol':
            self.in_list = False
            self.list_type = None
            self.result.append('\n')
        elif tag == 'li':
            self.result.append('\n')
        elif tag == 'blockquote':
            self.result.append('\n')
        elif tag == 'code':
            self.result.append('`')
        elif tag == 'pre':
            self.result.append('\n```\n')
    
    def handle_data(self, data):
        self.result.append(data)
    
    def get_markdown(self):
        text = ''.join(self.result)
        # Clean up extra whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()


def html_to_markdown(html: str) -> str:
    """Convert HTML to Markdown."""
    if not html:
        return ""
    
    # Quick check if it's already plain text
    if '<' not in html:
        return html.strip()
    
    parser = HTMLToMarkdown()
    try:
        parser.feed(html)
        return parser.get_markdown()
    except:
        # If parsing fails, strip tags crudely
        return re.sub(r'<[^>]+>', '', html).strip()


# =============================================================================
# Keychain Token Storage
# =============================================================================

KEYCHAIN_SERVICE = "canvas-course-builder"

def get_keychain_username(canvas_url: str, course_id: str) -> str:
    """Generate unique username for keychain entry."""
    # Normalize URL (remove trailing slash)
    url = canvas_url.rstrip('/')
    return f"{url}:{course_id}"

def get_token_from_keychain(canvas_url: str, course_id: str) -> Optional[str]:
    """
    Retrieve API token from system keychain.

    Returns:
        Token string if found, None otherwise
    """
    username = get_keychain_username(canvas_url, course_id)
    try:
        token = keyring.get_password(KEYCHAIN_SERVICE, username)
        return token
    except Exception as e:
        # Keychain access failed - fall back to prompt
        print(f"  Warning: Could not access Keychain: {e}")
        return None

def save_token_to_keychain(canvas_url: str, course_id: str, token: str) -> bool:
    """
    Save API token to system keychain.

    Returns:
        True if saved successfully, False otherwise
    """
    username = get_keychain_username(canvas_url, course_id)
    try:
        keyring.set_password(KEYCHAIN_SERVICE, username, token)
        return True
    except Exception as e:
        print(f"  Warning: Could not save to Keychain: {e}")
        return False

def delete_token_from_keychain(canvas_url: str, course_id: str) -> bool:
    """Delete API token from system keychain."""
    username = get_keychain_username(canvas_url, course_id)
    try:
        keyring.delete_password(KEYCHAIN_SERVICE, username)
        return True
    except Exception as e:
        print(f"  Warning: Could not delete from Keychain: {e}")
        return False


# =============================================================================
# Canvas API Client
# =============================================================================

class CanvasAPI:
    """Client for Canvas LMS API."""
    
    def __init__(self, base_url: str, course_id: str, api_token: str):
        self.base_url = base_url.rstrip('/')
        self.course_id = course_id
        self.api_token = api_token
        self.headers = {"Authorization": f"Bearer {api_token}"}
    
    def _url(self, path: str) -> str:
        """Build full API URL."""
        return f"{self.base_url}/api/v1/courses/{self.course_id}/{path}"
    
    def _get_paginated(self, path: str, params: dict = None) -> list:
        """Get all results from a paginated endpoint."""
        url = self._url(path)
        results = []
        params = params or {}
        params['per_page'] = 100
        
        while url:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            results.extend(response.json())
            
            # Get next page URL from Link header
            url = response.links.get("next", {}).get("url")
            params = {}  # Clear params for subsequent requests (URL has them)
        
        return results
    
    def _get(self, path: str) -> dict:
        """Get a single resource."""
        url = self._url(path)
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()
    
    # --- Modules ---
    
    def get_modules(self) -> list:
        """Get all modules with their items."""
        modules = self._get_paginated("modules", {"include[]": "items"})
        
        # Sort by position
        modules.sort(key=lambda m: m.get("position", 0))
        
        # For each module, if items weren't included, fetch them
        for module in modules:
            if "items" not in module or module.get("items_count", 0) > len(module.get("items", [])):
                module["items"] = self._get_paginated(f"modules/{module['id']}/items")
        
        return modules
    
    # --- Pages ---
    
    def get_page(self, page_url: str) -> dict:
        """Get a page by its URL slug."""
        return self._get(f"pages/{page_url}")
    
    # --- Assignments ---
    
    def get_assignment(self, assignment_id: int) -> dict:
        """Get an assignment by ID."""
        return self._get(f"assignments/{assignment_id}")
    
    # --- Discussions ---
    
    def get_discussion(self, topic_id: int) -> dict:
        """Get a discussion topic by ID."""
        return self._get(f"discussion_topics/{topic_id}")
    
    # --- Files ---
    
    def get_file(self, file_id: int) -> dict:
        """Get a file by ID."""
        # Files endpoint is at the root, not under courses
        url = f"{self.base_url}/api/v1/files/{file_id}"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()


# =============================================================================
# Course Exporter
# =============================================================================

class CourseExporter:
    """Exports a Canvas course to Markdown format."""
    
    def __init__(self, api: CanvasAPI):
        self.api = api
    
    def export(self) -> str:
        """Export the entire course to Markdown."""
        lines = []
        lines.append(f"<!-- Canvas Course Export -->")
        lines.append(f"<!-- URL: {self.api.base_url}/courses/{self.api.course_id} -->")
        lines.append(f"<!-- Exported: {datetime.now().isoformat()} -->")
        lines.append("")
        
        print("Fetching modules...")
        modules = self.api.get_modules()
        print(f"Found {len(modules)} modules.")
        
        for module in modules:
            print(f"\n[Module] {module['name']}")
            lines.append(f"# {module['name']}")
            lines.append(f"<!-- canvas_module_id: {module['id']} -->")
            lines.append("")
            
            items = module.get("items", [])
            items.sort(key=lambda i: i.get("position", 0))
            
            for item in items:
                item_lines = self._export_item(item)
                if item_lines:
                    lines.extend(item_lines)
                    lines.append("")
        
        return "\n".join(lines)
    
    def _export_item(self, item: dict) -> list:
        """Export a single module item to Markdown lines."""
        item_type = item.get("type")
        title = item.get("title", "Untitled")
        
        # Get module item ID for updating
        module_item_id = item.get("id")
        
        if item_type == "SubHeader":
            print(f"  • [header] {title}")
            return [f"## [header] {title}", f"<!-- canvas_module_item_id: {module_item_id} -->"]
        
        elif item_type == "Page":
            print(f"  • [page] {title}")
            return self._export_page(item, module_item_id)
        
        elif item_type == "ExternalUrl":
            url = item.get("external_url", "")
            print(f"  • [link] {title}")
            return [
                f"## [link] {title}",
                f"url: {url}",
                f"<!-- canvas_module_item_id: {module_item_id} -->"
            ]
        
        elif item_type == "Assignment":
            print(f"  • [assignment] {title}")
            return self._export_assignment(item, module_item_id)
        
        elif item_type == "Discussion":
            print(f"  • [discussion] {title}")
            return self._export_discussion(item, module_item_id)
        
        elif item_type == "Quiz":
            print(f"  • [quiz] {title} (exported as link - quizzes not fully supported)")
            # Export quizzes as external links since they're complex
            return [
                f"## [link] {title}",
                f"url: {item.get('html_url', '')}"
            ]
        
        elif item_type == "File":
            print(f"  • [file] {title}")
            return self._export_file(item, module_item_id)
        
        else:
            print(f"  • [{item_type}] {title} (unsupported, skipped)")
            return None
    
    def _export_page(self, item: dict, module_item_id: int) -> list:
        """Export a Page item."""
        page_url = item.get("page_url")
        if not page_url:
            return [f"## [page] {item.get('title', 'Untitled')}", f"<!-- canvas_module_item_id: {module_item_id} -->"]
        
        try:
            page = self.api.get_page(page_url)
            body = html_to_markdown(page.get("body", ""))
            page_id = page.get("page_id") or page.get("url")
            
            lines = [f"## [page] {page.get('title', item.get('title', 'Untitled'))}"]
            lines.append(f"<!-- canvas_page_id: {page_id} -->")
            lines.append(f"<!-- canvas_module_item_id: {module_item_id} -->")
            if body:
                lines.append(body)
            return lines
        except Exception as e:
            print(f"    Warning: Could not fetch page content: {e}")
            return [f"## [page] {item.get('title', 'Untitled')}", f"<!-- canvas_module_item_id: {module_item_id} -->"]
    
    def _export_file(self, item: dict, module_item_id: int) -> list:
        """Export a File item."""
        content_id = item.get("content_id")
        title = item.get("title", "Untitled")
        
        if not content_id:
            return [
                f"## [file] {title}",
                f"<!-- canvas_module_item_id: {module_item_id} -->"
            ]
        
        try:
            file_data = self.api.get_file(content_id)
            filename = file_data.get("display_name", title)
            
            lines = [f"## [file] {title}"]
            lines.append(f"<!-- canvas_file_id: {content_id} -->")
            lines.append(f"<!-- canvas_module_item_id: {module_item_id} -->")
            
            # Only add filename if different from title
            if filename != title:
                lines.append(f"filename: {filename}")
            
            return lines
        except Exception as e:
            print(f"    Warning: Could not fetch file details: {e}")
            return [
                f"## [file] {title}",
                f"<!-- canvas_module_item_id: {module_item_id} -->"
            ]
    
    def _export_assignment(self, item: dict, module_item_id: int) -> list:
        """Export an Assignment item."""
        content_id = item.get("content_id")
        if not content_id:
            return [f"## [assignment] {item.get('title', 'Untitled')}", f"<!-- canvas_module_item_id: {module_item_id} -->", "---"]
        
        try:
            assignment = self.api.get_assignment(content_id)
            
            lines = [f"## [assignment] {assignment.get('name', item.get('title', 'Untitled'))}"]
            lines.append(f"<!-- canvas_assignment_id: {content_id} -->")
            lines.append(f"<!-- canvas_module_item_id: {module_item_id} -->")
            
            # Points
            points = assignment.get("points_possible", 0)
            if points and points > 0:
                lines.append(f"points: {int(points) if points == int(points) else points}")
            
            # Due date
            due_at = assignment.get("due_at")
            if due_at:
                try:
                    # Parse as UTC and convert to local timezone
                    dt = datetime.fromisoformat(due_at.replace('Z', '+00:00'))
                    dt_local = dt.astimezone()  # Convert to local timezone
                    lines.append(f"due: {dt_local.strftime('%Y-%m-%d %I:%M%p').lower()}")
                except:
                    pass
            
            # Grade display
            grading_type = assignment.get("grading_type", "pass_fail")
            grade_map = {
                "pass_fail": "complete_incomplete",
                "points": "points",
                "not_graded": "not_graded",
                "letter_grade": "points",
                "gpa_scale": "points",
                "percent": "points",
            }
            grade_display = grade_map.get(grading_type, "complete_incomplete")
            if grade_display != "complete_incomplete":
                lines.append(f"grade_display: {grade_display}")
            
            # Submission types
            submission_types = assignment.get("submission_types", [])
            if submission_types and submission_types != ["online_text_entry"]:
                # Filter out 'none' if there are other types
                filtered = [t for t in submission_types if t != "none"] or submission_types
                lines.append(f"submission_types: {', '.join(filtered)}")
            
            lines.append("---")
            
            # Description
            description = html_to_markdown(assignment.get("description", ""))
            if description:
                lines.append(description)
            
            return lines
        except Exception as e:
            print(f"    Warning: Could not fetch assignment details: {e}")
            return [f"## [assignment] {item.get('title', 'Untitled')}", f"<!-- canvas_module_item_id: {module_item_id} -->", "---"]
    
    def _export_discussion(self, item: dict, module_item_id: int) -> list:
        """Export a Discussion item."""
        content_id = item.get("content_id")
        if not content_id:
            return [f"## [discussion] {item.get('title', 'Untitled')}", f"<!-- canvas_module_item_id: {module_item_id} -->", "---"]
        
        try:
            discussion = self.api.get_discussion(content_id)
            
            lines = [f"## [discussion] {discussion.get('title', item.get('title', 'Untitled'))}"]
            lines.append(f"<!-- canvas_discussion_id: {content_id} -->")
            lines.append(f"<!-- canvas_module_item_id: {module_item_id} -->")
            
            # Require initial post
            if discussion.get("require_initial_post"):
                lines.append("require_initial_post: true")
            
            # Threaded (side_comment = not threaded)
            disc_type = discussion.get("discussion_type", "threaded")
            if disc_type == "side_comment":
                lines.append("threaded: false")
            
            # Graded discussion
            assignment = discussion.get("assignment")
            if assignment:
                lines.append("graded: true")
                
                points = assignment.get("points_possible", 0)
                if points and points > 0:
                    lines.append(f"points: {int(points) if points == int(points) else points}")
                
                due_at = assignment.get("due_at")
                if due_at:
                    try:
                        # Parse as UTC and convert to local timezone
                        dt = datetime.fromisoformat(due_at.replace('Z', '+00:00'))
                        dt_local = dt.astimezone()  # Convert to local timezone
                        lines.append(f"due: {dt_local.strftime('%Y-%m-%d %I:%M%p').lower()}")
                    except:
                        pass
                
                grading_type = assignment.get("grading_type", "pass_fail")
                grade_map = {
                    "pass_fail": "complete_incomplete",
                    "points": "points",
                    "not_graded": "not_graded",
                }
                grade_display = grade_map.get(grading_type, "complete_incomplete")
                if grade_display != "complete_incomplete":
                    lines.append(f"grade_display: {grade_display}")
            
            lines.append("---")
            
            # Message
            message = html_to_markdown(discussion.get("message", ""))
            if message:
                lines.append(message)
            
            return lines
        except Exception as e:
            print(f"    Warning: Could not fetch discussion details: {e}")
            return [f"## [discussion] {item.get('title', 'Untitled')}", f"<!-- canvas_module_item_id: {module_item_id} -->", "---"]


# =============================================================================
# Main
# =============================================================================

def main():
    print("=" * 60)
    print("Canvas Course Downloader")
    print("=" * 60)

    # Parse command line arguments
    output_file = "course_content.md"
    reset_token = False

    for arg in sys.argv[1:]:
        if arg == "--reset-token":
            reset_token = True
        elif not arg.startswith("--"):
            output_file = arg

    # Get Canvas URL
    canvas_url = DEFAULT_CANVAS_URL
    if not canvas_url:
        canvas_url = input("\nEnter your Canvas URL (e.g., https://kent.instructure.com): ").strip()
        if not canvas_url:
            print("Error: Canvas URL is required.")
            sys.exit(1)
    
    if not canvas_url.startswith("http"):
        canvas_url = "https://" + canvas_url
    
    # Get Course ID
    course_id = DEFAULT_COURSE_ID
    if not course_id:
        course_id = input("Enter your Course ID (e.g., 126998): ").strip()
        if not course_id:
            print("Error: Course ID is required.")
            sys.exit(1)
    
    # Get API token (with keychain support)
    api_token = None

    # Try to retrieve from Keychain (unless --reset-token flag is set)
    if not reset_token:
        api_token = get_token_from_keychain(canvas_url, course_id)
        if api_token:
            print(f"\n✓ Using API token from Keychain")
            print(f"  Course: {canvas_url}/courses/{course_id}")

    # Prompt for token if not found in Keychain OR reset requested
    if not api_token or reset_token:
        if reset_token:
            print("\n• Resetting API token (--reset-token flag)")
            # Delete old token from Keychain if exists
            delete_token_from_keychain(canvas_url, course_id)
        else:
            print(f"\nNo saved token found in Keychain for this course.")

        # Prompt for token
        api_token = input("Enter your Canvas API token: ").strip()
        if not api_token:
            print("Error: No token provided.")
            sys.exit(1)

        # Save to Keychain for future use
        print("\nSaving token to Keychain...", end=" ")
        if save_token_to_keychain(canvas_url, course_id, api_token):
            print("✓ Saved")
            print(f"  (Next time, token will be retrieved automatically)")
        else:
            print("✗ Failed")
            print(f"  (You will be prompted again next time)")

    print(f"\nCourse: {canvas_url}/courses/{course_id}")
    print(f"Output: {output_file}")
    print("=" * 60)
    
    # Export
    api = CanvasAPI(canvas_url, course_id, api_token)
    exporter = CourseExporter(api)
    
    try:
        markdown = exporter.export()
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(markdown)
        
        print("\n" + "=" * 60)
        print(f"SUCCESS! Course exported to: {output_file}")
        print("=" * 60)
        print("\nYou can now:")
        print(f"  1. Edit {output_file} in Obsidian or any text editor")
        print(f"  2. Re-upload with: python canvas_course_builder.py {output_file}")
        
    except requests.exceptions.HTTPError as e:
        print(f"\nError: API request failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
