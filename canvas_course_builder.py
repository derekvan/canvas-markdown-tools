#!/usr/bin/env python3
"""
Canvas Course Builder
Creates Canvas LMS course content from a structured Markdown file.

Usage:
    python canvas_course_builder.py course_content.md [--dry-run]

Markdown Format:
    # Module Name
    
    ## [header] Text Header Title
    
    ## [page] Page Title
    Page content here...
    
    ## [link] Link Title
    url: https://example.com
    
    ## [file] Reading: Chapter 1
    filename: chapter1.pdf
    
    ## [assignment] Assignment Title
    points: 10
    due: 2026-01-15 11:59pm
    grade_display: points
    submission_types: online_text_entry, online_upload
    ---
    Assignment description here...
    
    ## [discussion] Discussion Title
    require_initial_post: true
    threaded: false
    graded: true
    points: 5
    due: 2026-01-15 11:59pm
    grade_display: complete_incomplete
    ---
    Discussion prompt here...

Internal Links (resolved to Canvas URLs):
    [[Page:Page Title]]
    [[Assignment:Assignment Title]]
    [[Discussion:Discussion Title]]
    [[File:filename.pdf]]
"""

import re
import sys
import requests
import yaml
import keyring
import html
from html.parser import HTMLParser
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

# =============================================================================
# Configuration - can be set here or provided at runtime
# =============================================================================

# Leave these empty to be prompted, or fill in your defaults
DEFAULT_CANVAS_URL = ""  # e.g., "https://kent.instructure.com"
DEFAULT_COURSE_ID = ""   # e.g., "126998"

# =============================================================================
# Data Models
# =============================================================================

class GradeDisplay(Enum):
    COMPLETE_INCOMPLETE = "complete_incomplete"
    POINTS = "points"
    NOT_GRADED = "not_graded"
    
    def to_canvas(self) -> str:
        """Convert to Canvas API grading_type value."""
        mapping = {
            GradeDisplay.COMPLETE_INCOMPLETE: "pass_fail",
            GradeDisplay.POINTS: "points",
            GradeDisplay.NOT_GRADED: "not_graded",
        }
        return mapping[self]


class SubmissionType(Enum):
    ONLINE_TEXT = "online_text_entry"
    ONLINE_UPLOAD = "online_upload"
    ONLINE_URL = "online_url"
    MEDIA_RECORDING = "media_recording"
    NONE = "none"
    ON_PAPER = "on_paper"


@dataclass
class ChangeDetectionResult:
    """Result of comparing local content against Canvas."""
    has_changes: bool
    changed_fields: list[str]  # e.g., ["content", "title", "points"]
    reason: Optional[str] = None  # Human-readable explanation


@dataclass
class TextHeader:
    title: str
    canvas_module_item_id: Optional[int] = None  # For updating existing items
    

@dataclass
class Page:
    title: str
    content: str
    canvas_id: Optional[int] = None
    canvas_url: Optional[str] = None
    canvas_page_id: Optional[str] = None  # Existing page ID for updates
    canvas_module_item_id: Optional[int] = None


@dataclass
class ExternalLink:
    title: str
    url: str
    canvas_module_item_id: Optional[int] = None


@dataclass
class File:
    title: str  # Display title in module
    filename: str  # Filename to look up in Canvas Files
    canvas_file_id: Optional[int] = None  # Resolved file ID
    canvas_url: Optional[str] = None  # File URL for linking
    canvas_module_item_id: Optional[int] = None


@dataclass 
class Assignment:
    title: str
    description: str
    points: float = 0
    due_at: Optional[datetime] = None
    grade_display: GradeDisplay = GradeDisplay.COMPLETE_INCOMPLETE
    submission_types: list[SubmissionType] = field(default_factory=lambda: [SubmissionType.ONLINE_TEXT])
    canvas_id: Optional[int] = None
    canvas_url: Optional[str] = None
    canvas_assignment_id: Optional[int] = None  # Existing assignment ID for updates
    canvas_module_item_id: Optional[int] = None


@dataclass
class Discussion:
    title: str
    message: str
    require_initial_post: bool = False
    threaded: bool = True
    graded: bool = False
    points: float = 0
    due_at: Optional[datetime] = None
    grade_display: GradeDisplay = GradeDisplay.COMPLETE_INCOMPLETE
    canvas_id: Optional[int] = None
    canvas_url: Optional[str] = None
    canvas_discussion_id: Optional[int] = None  # Existing discussion ID for updates
    canvas_module_item_id: Optional[int] = None


@dataclass
class Module:
    title: str
    items: list = field(default_factory=list)  # List of content items
    canvas_id: Optional[int] = None
    canvas_module_id: Optional[int] = None  # Existing module ID for updates


# =============================================================================
# Markdown Parser
# =============================================================================

class MarkdownParser:
    """Parses the structured markdown format into content objects."""
    
    # Regex patterns
    MODULE_PATTERN = re.compile(r'^# (.+)$')
    ITEM_PATTERN = re.compile(r'^## \[(\w+)\] (.+)$')
    METADATA_PATTERN = re.compile(r'^(\w+):\s*(.+)$')
    CANVAS_ID_PATTERN = re.compile(r'^<!-- canvas_(\w+): (\S+) -->$')
    CONTENT_SEPARATOR = '---'
    
    def __init__(self, content: str):
        self.lines = content.split('\n')
        self.pos = 0
        self.modules: list[Module] = []
        
    def parse(self) -> list[Module]:
        """Parse the entire markdown file."""
        while self.pos < len(self.lines):
            line = self.lines[self.pos].rstrip()
            
            # Check for module header
            module_match = self.MODULE_PATTERN.match(line)
            if module_match:
                module = Module(title=module_match.group(1))
                self.pos += 1
                
                # Check for canvas_module_id on next line
                if self.pos < len(self.lines):
                    id_match = self.CANVAS_ID_PATTERN.match(self.lines[self.pos].rstrip())
                    if id_match and id_match.group(1) == 'module_id':
                        try:
                            module.canvas_module_id = int(id_match.group(2))
                        except ValueError:
                            pass
                        self.pos += 1
                
                self.modules.append(module)
                continue
            
            # Check for content item
            item_match = self.ITEM_PATTERN.match(line)
            if item_match and self.modules:
                item_type = item_match.group(1).lower()
                title = item_match.group(2)
                self.pos += 1
                item = self._parse_item(item_type, title)
                if item:
                    self.modules[-1].items.append(item)
                continue
            
            self.pos += 1
        
        return self.modules
    
    def _parse_item(self, item_type: str, title: str):
        """Parse a content item based on its type."""
        metadata = {}
        canvas_ids = {}
        content_lines = []
        in_content = False
        
        # Parse metadata and content
        while self.pos < len(self.lines):
            line = self.lines[self.pos].rstrip()
            
            # Stop at next module or item
            if self.MODULE_PATTERN.match(line) or self.ITEM_PATTERN.match(line):
                break
            
            # Check for content separator
            if line == self.CONTENT_SEPARATOR:
                in_content = True
                self.pos += 1
                continue
            
            # Check for canvas ID comments
            id_match = self.CANVAS_ID_PATTERN.match(line)
            if id_match:
                id_type = id_match.group(1)
                try:
                    canvas_ids[id_type] = int(id_match.group(2))
                except ValueError:
                    canvas_ids[id_type] = id_match.group(2)  # Keep as string if not int
                self.pos += 1
                continue
            
            if in_content:
                content_lines.append(line)
            else:
                # Parse metadata
                meta_match = self.METADATA_PATTERN.match(line)
                if meta_match:
                    key = meta_match.group(1).lower()
                    value = meta_match.group(2).strip()
                    metadata[key] = value
                elif line and not line.startswith('<!--'):
                    # If it's not metadata and not a comment, it's content
                    # (for items without --- separator, like pages)
                    content_lines.append(line)
            
            self.pos += 1
        
        content = '\n'.join(content_lines).strip()
        
        # Create appropriate object based on type
        if item_type == 'header':
            return TextHeader(
                title=title,
                canvas_module_item_id=canvas_ids.get('module_item_id'),
            )
        
        elif item_type == 'page':
            return Page(
                title=title,
                content=content,
                canvas_page_id=canvas_ids.get('page_id'),
                canvas_module_item_id=canvas_ids.get('module_item_id'),
            )
        
        elif item_type == 'link':
            url = metadata.get('url', '')
            if not url:
                print(f"  Warning: Link '{title}' has no URL, skipping")
                return None
            return ExternalLink(
                title=title,
                url=url,
                canvas_module_item_id=canvas_ids.get('module_item_id'),
            )
        
        elif item_type == 'file':
            filename = metadata.get('filename', '')
            if not filename:
                # If no filename specified, use title as filename
                filename = title
            return File(
                title=title,
                filename=filename,
                canvas_file_id=canvas_ids.get('file_id'),
                canvas_module_item_id=canvas_ids.get('module_item_id'),
            )
        
        elif item_type == 'assignment':
            return Assignment(
                title=title,
                description=content,
                points=float(metadata.get('points', 0)),
                due_at=self._parse_date(metadata.get('due')),
                grade_display=self._parse_grade_display(metadata.get('grade_display')),
                submission_types=self._parse_submission_types(metadata.get('submission_types')),
                canvas_assignment_id=canvas_ids.get('assignment_id'),
                canvas_module_item_id=canvas_ids.get('module_item_id'),
            )
        
        elif item_type == 'discussion':
            return Discussion(
                title=title,
                message=content,
                require_initial_post=self._parse_bool(metadata.get('require_initial_post', 'false')),
                threaded=self._parse_bool(metadata.get('threaded', 'true')),
                graded=self._parse_bool(metadata.get('graded', 'false')),
                points=float(metadata.get('points', 0)),
                due_at=self._parse_date(metadata.get('due')),
                grade_display=self._parse_grade_display(metadata.get('grade_display')),
                canvas_discussion_id=canvas_ids.get('discussion_id'),
                canvas_module_item_id=canvas_ids.get('module_item_id'),
            )
        
        else:
            print(f"  Warning: Unknown item type '{item_type}', skipping")
            return None
    
    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse various date formats into datetime."""
        if not date_str:
            return None
        
        date_str = date_str.strip()
        
        # Try various formats
        formats = [
            '%Y-%m-%d %I:%M%p',      # 2026-01-15 11:59pm
            '%Y-%m-%d %I:%M %p',     # 2026-01-15 11:59 pm
            '%Y-%m-%d %H:%M',        # 2026-01-15 23:59
            '%Y-%m-%d',              # 2026-01-15 (defaults to 11:59pm)
            '%b %d, %Y %I:%M%p',     # Jan 15, 2026 11:59pm
            '%b %d, %Y %I:%M %p',    # Jan 15, 2026 11:59 pm
            '%b %d, %Y',             # Jan 15, 2026
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                # If no time specified, default to 11:59 PM
                if dt.hour == 0 and dt.minute == 0 and '%H' not in fmt and '%I' not in fmt:
                    dt = dt.replace(hour=23, minute=59)
                return dt
            except ValueError:
                continue
        
        print(f"  Warning: Could not parse date '{date_str}'")
        return None
    
    def _parse_grade_display(self, value: Optional[str]) -> GradeDisplay:
        """Parse grade display option."""
        if not value:
            return GradeDisplay.COMPLETE_INCOMPLETE
        
        value = value.lower().strip()
        mapping = {
            'complete_incomplete': GradeDisplay.COMPLETE_INCOMPLETE,
            'pass_fail': GradeDisplay.COMPLETE_INCOMPLETE,
            'points': GradeDisplay.POINTS,
            'not_graded': GradeDisplay.NOT_GRADED,
        }
        return mapping.get(value, GradeDisplay.COMPLETE_INCOMPLETE)
    
    def _parse_submission_types(self, value: Optional[str]) -> list[SubmissionType]:
        """Parse submission types."""
        if not value:
            return [SubmissionType.ONLINE_TEXT]
        
        types = []
        mapping = {
            'online_text_entry': SubmissionType.ONLINE_TEXT,
            'online_text': SubmissionType.ONLINE_TEXT,
            'text': SubmissionType.ONLINE_TEXT,
            'online_upload': SubmissionType.ONLINE_UPLOAD,
            'upload': SubmissionType.ONLINE_UPLOAD,
            'file': SubmissionType.ONLINE_UPLOAD,
            'online_url': SubmissionType.ONLINE_URL,
            'url': SubmissionType.ONLINE_URL,
            'media_recording': SubmissionType.MEDIA_RECORDING,
            'media': SubmissionType.MEDIA_RECORDING,
            'none': SubmissionType.NONE,
            'on_paper': SubmissionType.ON_PAPER,
            'paper': SubmissionType.ON_PAPER,
        }
        
        for part in value.split(','):
            part = part.strip().lower()
            if part in mapping:
                types.append(mapping[part])
        
        return types if types else [SubmissionType.ONLINE_TEXT]
    
    def _parse_bool(self, value: str) -> bool:
        """Parse boolean value."""
        return value.lower().strip() in ('true', 'yes', '1', 'on')


# =============================================================================
# YAML Frontmatter Parser
# =============================================================================

def extract_frontmatter(content: str) -> tuple[dict, str]:
    """
    Extract YAML frontmatter from markdown content.

    Returns:
        (metadata_dict, content_without_frontmatter)

    Example:
        content = '''---
        canvas_url: https://example.com
        course_id: 12345
        ---
        # Module 1'''

        metadata, clean_content = extract_frontmatter(content)
        # metadata = {'canvas_url': 'https://example.com', 'course_id': 12345}
        # clean_content = '# Module 1'
    """
    lines = content.split('\n')

    # Check if file starts with frontmatter delimiter
    if not lines or lines[0].strip() != '---':
        return {}, content

    # Find closing delimiter
    closing_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == '---':
            closing_idx = i
            break

    if closing_idx is None:
        # No closing delimiter found - treat as regular content
        return {}, content

    # Extract and parse YAML frontmatter
    frontmatter_text = '\n'.join(lines[1:closing_idx])

    try:
        metadata = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as e:
        print(f"  Warning: Failed to parse YAML frontmatter: {e}")
        print(f"  Continuing without frontmatter metadata...")
        metadata = {}

    # Remove frontmatter from content (keep everything after closing ---)
    remaining_content = '\n'.join(lines[closing_idx + 1:])

    return metadata, remaining_content


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
    
    def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make an API request."""
        url = self._url(path)
        response = requests.request(method, url, headers=self.headers, **kwargs)

        # Better error handling to show Canvas error messages
        if not response.ok:
            print(f"\n[ERROR] Canvas API returned {response.status_code}")
            try:
                error_data = response.json()
                print(f"  Error details: {error_data}")
            except:
                print(f"  Error text: {response.text[:500]}")

        response.raise_for_status()
        return response.json() if response.text else {}
    
    # --- Modules ---
    
    def create_module(self, name: str, position: Optional[int] = None) -> dict:
        """Create a new module."""
        data = {"module[name]": name}
        if position:
            data["module[position]"] = position
        return self._request("POST", "modules", data=data)
    
    def update_module(self, module_id: int, name: str, position: Optional[int] = None) -> dict:
        """Update an existing module."""
        data = {"module[name]": name}
        if position:
            data["module[position]"] = position
        return self._request("PUT", f"modules/{module_id}", data=data)

    def get_module(self, module_id: int) -> dict:
        """Get a single module by ID."""
        return self._request("GET", f"modules/{module_id}")

    def get_module_item(self, module_id: int, item_id: int) -> dict:
        """Get a single module item by ID."""
        return self._request("GET", f"modules/{module_id}/items/{item_id}")

    def create_module_item(self, module_id: int, item_type: str, **kwargs) -> dict:
        """Create a module item."""
        data = {"module_item[type]": item_type}
        for key, value in kwargs.items():
            if value is not None:
                data[f"module_item[{key}]"] = value
        return self._request("POST", f"modules/{module_id}/items", data=data)
    
    def update_module_item(self, module_id: int, item_id: int, **kwargs) -> dict:
        """Update an existing module item."""
        data = {}
        for key, value in kwargs.items():
            if value is not None:
                data[f"module_item[{key}]"] = value
        return self._request("PUT", f"modules/{module_id}/items/{item_id}", data=data)
    
    # --- Files ---
    
    def get_files(self) -> list:
        """Get all files in the course (paginated)."""
        url = self._url("files")
        all_files = []
        params = {"per_page": 100}
        
        while url:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            all_files.extend(response.json())
            
            # Get next page from Link header
            links = response.links
            url = links.get("next", {}).get("url")
            params = {}  # Clear params for subsequent requests
        
        return all_files
    
    def get_file_by_name(self, filename: str, files_cache: list = None) -> Optional[dict]:
        """Find a file by its display name."""
        if files_cache is None:
            files_cache = self.get_files()
        
        # Try exact match first
        for f in files_cache:
            if f.get("display_name") == filename:
                return f
        
        # Try case-insensitive match
        filename_lower = filename.lower()
        for f in files_cache:
            if f.get("display_name", "").lower() == filename_lower:
                return f
        
        return None
    
    # --- Pages ---
    
    def create_page(self, title: str, body: str, published: bool = True) -> dict:
        """Create a wiki page."""
        data = {
            "wiki_page[title]": title,
            "wiki_page[body]": body,
            "wiki_page[published]": str(published).lower(),
        }
        return self._request("POST", "pages", data=data)
    
    def update_page(self, page_url: str, body: str, title: str = None) -> dict:
        """Update a wiki page's content."""
        data = {"wiki_page[body]": body}
        if title:
            data["wiki_page[title]"] = title
        return self._request("PUT", f"pages/{page_url}", data=data)

    def get_page(self, page_url: str) -> dict:
        """Get a page by its URL slug."""
        return self._request("GET", f"pages/{page_url}")

    # --- Assignments ---
    
    def create_assignment(
        self,
        name: str,
        description: str = "",
        points_possible: float = 0,
        due_at: Optional[datetime] = None,
        grading_type: str = "pass_fail",
        submission_types: list[str] = None,
        published: bool = True,
    ) -> dict:
        """Create an assignment."""
        data = {
            "assignment[name]": name,
            "assignment[description]": description,
            "assignment[points_possible]": points_possible,
            "assignment[grading_type]": grading_type,
            "assignment[published]": str(published).lower(),
        }
        
        if due_at:
            # Ensure timezone info is included for Canvas API
            if due_at.tzinfo is None:
                # Treat naive datetime as local time and add timezone info
                import datetime as dt
                local_tz = dt.datetime.now(dt.timezone.utc).astimezone().tzinfo
                due_at_with_tz = due_at.replace(tzinfo=local_tz)
                data["assignment[due_at]"] = due_at_with_tz.isoformat()
            else:
                data["assignment[due_at]"] = due_at.isoformat()

        if submission_types:
            # Handle "none" specially - don't send it in array format
            if submission_types == ["none"]:
                data["assignment[submission_types][]"] = "none"
            else:
                for i, st in enumerate(submission_types):
                    data[f"assignment[submission_types][{i}]"] = st
        else:
            data["assignment[submission_types][]"] = "online_text_entry"

        # Debug: Print what we're creating
        print(f"\n[DEBUG] Creating assignment: {name}")
        print(f"  Data being sent:")
        for key, value in sorted(data.items()):
            if len(str(value)) > 100:
                print(f"    {key}: {str(value)[:100]}...")
            else:
                print(f"    {key}: {value}")

        return self._request("POST", "assignments", data=data)
    
    def update_assignment_full(
        self,
        assignment_id: int,
        name: str,
        description: str = "",
        points_possible: float = 0,
        due_at: Optional[datetime] = None,
        grading_type: str = "pass_fail",
        submission_types: list[str] = None,
    ) -> dict:
        """Update an assignment with all fields."""
        data = {
            "assignment[name]": name,
            "assignment[description]": description,
            "assignment[points_possible]": points_possible,
            "assignment[grading_type]": grading_type,
        }

        if due_at:
            # Ensure timezone info is included for Canvas API
            if due_at.tzinfo is None:
                # Treat naive datetime as local time and add timezone info
                import datetime as dt
                local_tz = dt.datetime.now(dt.timezone.utc).astimezone().tzinfo
                due_at_with_tz = due_at.replace(tzinfo=local_tz)
                data["assignment[due_at]"] = due_at_with_tz.isoformat()
            else:
                data["assignment[due_at]"] = due_at.isoformat()
        # Note: Don't send due_at field if None - let Canvas keep existing value
        # Sending empty string causes 400 error

        # NOTE: Canvas API does NOT allow changing submission_types on existing assignments
        # submission_types can only be set when creating a new assignment
        # Attempting to update them results in "Invalid submission types" error

        # Debug: Print what we're sending to Canvas
        print(f"\n[DEBUG] Updating assignment {assignment_id}: {name}")
        print(f"  Data being sent:")
        for key, value in sorted(data.items()):
            if len(str(value)) > 100:
                print(f"    {key}: {str(value)[:100]}...")
            else:
                print(f"    {key}: {value}")

        return self._request("PUT", f"assignments/{assignment_id}", data=data)
    
    def update_assignment(self, assignment_id: int, description: str) -> dict:
        """Update an assignment's description."""
        data = {"assignment[description]": description}
        return self._request("PUT", f"assignments/{assignment_id}", data=data)

    def get_assignment(self, assignment_id: int) -> dict:
        """Get an assignment by ID."""
        return self._request("GET", f"assignments/{assignment_id}")

    # --- Discussions ---
    
    def create_discussion(
        self,
        title: str,
        message: str = "",
        require_initial_post: bool = False,
        discussion_type: str = "threaded",
        published: bool = True,
        # For graded discussions:
        graded: bool = False,
        points_possible: float = 0,
        due_at: Optional[datetime] = None,
        grading_type: str = "pass_fail",
    ) -> dict:
        """Create a discussion topic."""
        data = {
            "title": title,
            "message": message,
            "require_initial_post": str(require_initial_post).lower(),
            "discussion_type": discussion_type,
            "published": str(published).lower(),
        }
        
        if graded:
            data["assignment[points_possible]"] = points_possible
            data["assignment[grading_type]"] = grading_type
            if due_at:
                data["assignment[due_at]"] = due_at.isoformat()
        
        return self._request("POST", "discussion_topics", data=data)
    
    def update_discussion_full(
        self,
        topic_id: int,
        title: str,
        message: str = "",
        require_initial_post: bool = False,
        discussion_type: str = "threaded",
        # For graded discussions:
        graded: bool = False,
        points_possible: float = 0,
        due_at: Optional[datetime] = None,
        grading_type: str = "pass_fail",
    ) -> dict:
        """Update a discussion topic with all fields."""
        data = {
            "title": title,
            "message": message,
            "require_initial_post": str(require_initial_post).lower(),
            "discussion_type": discussion_type,
        }

        if graded:
            data["assignment[points_possible]"] = points_possible
            data["assignment[grading_type]"] = grading_type
            if due_at:
                data["assignment[due_at]"] = due_at.isoformat()

        return self._request("PUT", f"discussion_topics/{topic_id}", data=data)
    
    def update_discussion(self, topic_id: int, message: str) -> dict:
        """Update a discussion's message."""
        data = {"message": message}
        return self._request("PUT", f"discussion_topics/{topic_id}", data=data)

    def get_discussion(self, topic_id: int) -> dict:
        """Get a discussion topic by ID."""
        return self._request("GET", f"discussion_topics/{topic_id}")


# =============================================================================
# HTML Normalization and Change Detection
# =============================================================================

class HTMLTextExtractor(HTMLParser):
    """Extract plain text from HTML, preserving semantic structure."""
    def __init__(self):
        super().__init__()
        self.text_parts = []

    def handle_data(self, data):
        text = data.strip()
        if text:
            self.text_parts.append(text)

    def get_text(self):
        return ' '.join(self.text_parts)


def markdown_to_html_basic(text: str) -> str:
    """Convert common markdown patterns to HTML equivalents."""
    # Headers: #### text → <h4>text</h4>
    text = re.sub(r'^####\s+(.+)$', r'<h4>\1</h4>', text, flags=re.MULTILINE)
    text = re.sub(r'^###\s+(.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
    text = re.sub(r'^##\s+(.+)$', r'<h2>\1</h2>', text, flags=re.MULTILINE)
    text = re.sub(r'^#\s+(.+)$', r'<h1>\1</h1>', text, flags=re.MULTILINE)

    # Lists: - item → <li>item</li>
    text = re.sub(r'^-\s+(.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)
    text = re.sub(r'^\*\s+(.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)

    # Links: [text](url) → <a href="url">text</a>
    text = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2">\1</a>', text)

    # Bold: **text** → <strong>text</strong>
    text = re.sub(r'\*\*([^\*]+)\*\*', r'<strong>\1</strong>', text)

    # Italic: *text* or _text_ → <em>text</em>
    text = re.sub(r'\*([^\*]+)\*', r'<em>\1</em>', text)
    text = re.sub(r'(?<!\*)_([^_]+)_(?!\*)', r'<em>\1</em>', text)

    return text


def normalize_html(content: str) -> str:
    """
    Normalize HTML/markdown for semantic comparison.

    Process:
    1. Decode HTML entities (&nbsp;, &#39;, etc.)
    2. Convert markdown to HTML (for local content)
    3. Extract text content (strip all tags)
    4. Normalize whitespace
    5. Return lowercase text for case-insensitive comparison
    """
    if not content:
        return ""

    # Step 1: Decode HTML entities (&#39; → ', &nbsp; → space, etc.)
    normalized = html.unescape(content.strip())

    # Step 2: Convert common markdown to HTML (so both sources match)
    normalized = markdown_to_html_basic(normalized)

    # Step 3: Extract plain text from HTML
    extractor = HTMLTextExtractor()
    try:
        extractor.feed(normalized)
        text = extractor.get_text()
    except Exception:
        # Fallback: simple tag stripping
        text = re.sub(r'<[^>]+>', ' ', normalized)

    # Step 4: Normalize whitespace (multiple spaces → single space)
    text = re.sub(r'\s+', ' ', text)

    # Step 5: Final cleanup
    return text.strip().lower()


class ContentComparator:
    """Compares local content against Canvas data to detect changes."""

    @staticmethod
    def compare_module(local: Module, canvas_data: dict) -> ChangeDetectionResult:
        """Compare module metadata."""
        changed = []

        # Check title
        canvas_name = canvas_data.get("name", "")
        if local.title != canvas_name:
            changed.append("title")

        return ChangeDetectionResult(
            has_changes=bool(changed),
            changed_fields=changed,
            reason=f"Changed: {', '.join(changed)}" if changed else None
        )

    @staticmethod
    def compare_text_header(local: TextHeader, canvas_data: dict) -> ChangeDetectionResult:
        """Compare text header (module item)."""
        changed = []

        # Check title
        canvas_title = canvas_data.get("title", "")
        if local.title != canvas_title:
            changed.append("title")

        return ChangeDetectionResult(
            has_changes=bool(changed),
            changed_fields=changed,
            reason=f"Changed: {', '.join(changed)}" if changed else None
        )

    @staticmethod
    def compare_external_link(local: ExternalLink, canvas_data: dict) -> ChangeDetectionResult:
        """Compare external link (module item)."""
        changed = []

        # Check title
        canvas_title = canvas_data.get("title", "")
        if local.title != canvas_title:
            changed.append("title")

        # Check URL
        canvas_url = canvas_data.get("external_url", "")
        if local.url != canvas_url:
            changed.append("url")

        return ChangeDetectionResult(
            has_changes=bool(changed),
            changed_fields=changed,
            reason=f"Changed: {', '.join(changed)}" if changed else None
        )

    @staticmethod
    def compare_page(local: Page, canvas_data: dict) -> ChangeDetectionResult:
        """Compare page content and metadata."""
        changed = []

        # Check title
        canvas_title = canvas_data.get("title", "")
        if local.title != canvas_title:
            changed.append("title")

        # Check body/content (normalize HTML first)
        canvas_body = canvas_data.get("body", "")
        local_normalized = normalize_html(local.content)
        canvas_normalized = normalize_html(canvas_body)
        if local_normalized != canvas_normalized:
            changed.append("content")
            # Debug output
            if False:  # Set to True to enable debug output
                print(f"\n[DEBUG] Page '{local.title}' content mismatch:")
                print(f"  Local:  {repr(local_normalized[:200])}")
                print(f"  Canvas: {repr(canvas_normalized[:200])}")

        return ChangeDetectionResult(
            has_changes=bool(changed),
            changed_fields=changed,
            reason=f"Changed: {', '.join(changed)}" if changed else None
        )

    @staticmethod
    def compare_assignment(local: Assignment, canvas_data: dict) -> ChangeDetectionResult:
        """Compare assignment metadata and description."""
        changed = []

        # Check title
        if local.title != canvas_data.get("name", ""):
            changed.append("title")

        # Check description
        canvas_desc = canvas_data.get("description", "")
        local_normalized = normalize_html(local.description)
        canvas_normalized = normalize_html(canvas_desc)
        if local_normalized != canvas_normalized:
            changed.append("description")
            # Debug output
            if False:  # Set to True to enable debug output
                print(f"\n[DEBUG] Assignment '{local.title}' description mismatch:")
                print(f"  Local:  {repr(local_normalized[:200])}")
                print(f"  Canvas: {repr(canvas_normalized[:200])}")

        # Check points
        canvas_points = canvas_data.get("points_possible", 0)
        if local.points != canvas_points:
            changed.append("points")

        # Check due date
        canvas_due = canvas_data.get("due_at")
        local_due_iso = local.due_at.isoformat() if local.due_at else None
        canvas_due_iso = canvas_due if canvas_due else None
        if local_due_iso != canvas_due_iso:
            changed.append("due_date")

        # Check grading type
        canvas_grading = canvas_data.get("grading_type", "pass_fail")
        if local.grade_display.to_canvas() != canvas_grading:
            changed.append("grading_type")

        # Check submission types
        canvas_sub_types = set(canvas_data.get("submission_types", []))
        local_sub_types = set(st.value for st in local.submission_types)
        if local_sub_types != canvas_sub_types:
            changed.append("submission_types")

        return ChangeDetectionResult(
            has_changes=bool(changed),
            changed_fields=changed,
            reason=f"Changed: {', '.join(changed)}" if changed else None
        )

    @staticmethod
    def compare_discussion(local: Discussion, canvas_data: dict) -> ChangeDetectionResult:
        """Compare discussion metadata and message."""
        changed = []

        # Check title
        if local.title != canvas_data.get("title", ""):
            changed.append("title")

        # Check message
        canvas_msg = canvas_data.get("message", "")
        local_normalized = normalize_html(local.message)
        canvas_normalized = normalize_html(canvas_msg)
        if local_normalized != canvas_normalized:
            changed.append("message")
            # Debug output
            if False:  # Set to True to enable debug output
                print(f"\n[DEBUG] Discussion '{local.title}' message mismatch:")
                print(f"  Local:  {repr(local_normalized[:200])}")
                print(f"  Canvas: {repr(canvas_normalized[:200])}")

        # Check require_initial_post
        canvas_req_post = canvas_data.get("require_initial_post", False)
        if local.require_initial_post != canvas_req_post:
            changed.append("require_initial_post")

        # Check threaded/discussion_type
        canvas_type = canvas_data.get("discussion_type", "threaded")
        local_type = "threaded" if local.threaded else "side_comment"
        if local_type != canvas_type:
            changed.append("discussion_type")

        # Check graded status and assignment settings
        canvas_assignment = canvas_data.get("assignment")
        if local.graded:
            if not canvas_assignment:
                changed.append("graded_status")
            else:
                # Check graded discussion metadata
                if local.points != canvas_assignment.get("points_possible", 0):
                    changed.append("points")

                canvas_due = canvas_assignment.get("due_at")
                local_due_iso = local.due_at.isoformat() if local.due_at else None
                canvas_due_iso = canvas_due if canvas_due else None
                if local_due_iso != canvas_due_iso:
                    changed.append("due_date")

                canvas_grading = canvas_assignment.get("grading_type", "pass_fail")
                if local.grade_display.to_canvas() != canvas_grading:
                    changed.append("grading_type")
        elif canvas_assignment:
            # Was graded, now not graded
            changed.append("graded_status")

        return ChangeDetectionResult(
            has_changes=bool(changed),
            changed_fields=changed,
            reason=f"Changed: {', '.join(changed)}" if changed else None
        )


# =============================================================================
# Internal Link Resolver
# =============================================================================

class LinkResolver:
    """Resolves internal [[Type:Title]] links to Canvas URLs."""
    
    LINK_PATTERN = re.compile(r'\[\[(Page|Assignment|Discussion|File):([^\]]+)\]\]')
    
    def __init__(self, base_url: str, course_id: str):
        self.base_url = base_url
        self.course_id = course_id
        self.pages: dict[str, Page] = {}
        self.assignments: dict[str, Assignment] = {}
        self.discussions: dict[str, Discussion] = {}
        self.files: dict[str, dict] = {}  # filename -> {id, url, display_name}
    
    def register_page(self, page: Page):
        """Register a page for link resolution."""
        self.pages[page.title.lower()] = page
    
    def register_assignment(self, assignment: Assignment):
        """Register an assignment for link resolution."""
        self.assignments[assignment.title.lower()] = assignment
    
    def register_discussion(self, discussion: Discussion):
        """Register a discussion for link resolution."""
        self.discussions[discussion.title.lower()] = discussion
    
    def register_file(self, filename: str, file_data: dict):
        """Register a file for link resolution."""
        self.files[filename.lower()] = file_data
    
    def resolve(self, content: str) -> str:
        """Replace all internal links with Canvas URLs."""
        def replace_link(match):
            link_type = match.group(1)
            title = match.group(2).strip()
            title_lower = title.lower()
            
            if link_type == 'Page':
                page = self.pages.get(title_lower)
                if page and page.canvas_url:
                    return f'<a href="{page.canvas_url}">{title}</a>'
            
            elif link_type == 'Assignment':
                assignment = self.assignments.get(title_lower)
                if assignment and assignment.canvas_url:
                    return f'<a href="{assignment.canvas_url}">{title}</a>'
            
            elif link_type == 'Discussion':
                discussion = self.discussions.get(title_lower)
                if discussion and discussion.canvas_url:
                    return f'<a href="{discussion.canvas_url}">{title}</a>'
            
            elif link_type == 'File':
                file_data = self.files.get(title_lower)
                if file_data and file_data.get('url'):
                    display_name = file_data.get('display_name', title)
                    # Use Canvas file preview URL
                    file_id = file_data.get('id')
                    preview_url = f"{self.base_url}/courses/{self.course_id}/files/{file_id}"
                    return f'<a href="{preview_url}" class="instructure_file_link">{display_name}</a>'
            
            # Link not found - return original text
            print(f"  Warning: Could not resolve link [[{link_type}:{title}]]")
            return title
        
        return self.LINK_PATTERN.sub(replace_link, content)
    
    def has_internal_links(self, content: str) -> bool:
        """Check if content has internal links."""
        return bool(self.LINK_PATTERN.search(content))


# =============================================================================
# Course Builder
# =============================================================================

class CourseBuilder:
    """Builds Canvas course content from parsed markdown."""
    
    def __init__(self, api: Optional[CanvasAPI] = None):
        self.api = api
        if api:
            self.resolver = LinkResolver(api.base_url, api.course_id)
        else:
            self.resolver = None
        self.items_needing_link_resolution: list = []
        self.files_cache: list = []  # Cache of all course files
        self.canvas_data_cache: dict = {
            'modules': {},    # module_id -> canvas_data
            'pages': {},      # page_id -> canvas_data
            'assignments': {}, # assignment_id -> canvas_data
            'discussions': {}, # discussion_id -> canvas_data
            'module_items': {}, # module_item_id -> canvas_data (for headers/links)
        }
        self.comparator = ContentComparator()
    
    def build(self, modules: list[Module], dry_run: bool = False):
        """Build all course content."""
        # Check if we need to fetch files
        has_files = any(
            isinstance(item, File)
            for m in modules
            for item in m.items
        )
        
        # Check if we have file links in content
        has_file_links = any(
            '[[File:' in getattr(item, 'content', '') or 
            '[[File:' in getattr(item, 'description', '') or
            '[[File:' in getattr(item, 'message', '')
            for m in modules
            for item in m.items
        )
        
        if has_files or has_file_links:
            print("\n" + "=" * 60)
            print("PHASE 0: Fetching course files")
            print("=" * 60)
            self.files_cache = self.api.get_files()
            print(f"  Found {len(self.files_cache)} files in course")
            
            # Register all files with the resolver
            for f in self.files_cache:
                self.resolver.register_file(f.get('display_name', ''), f)
        
        # Check if we have any existing content (update mode)
        # Debug: count items with IDs
        id_counts = {
            'modules': sum(1 for m in modules if m.canvas_module_id),
            'pages': sum(1 for m in modules for item in m.items if getattr(item, 'canvas_page_id', None)),
            'assignments': sum(1 for m in modules for item in m.items if getattr(item, 'canvas_assignment_id', None)),
            'discussions': sum(1 for m in modules for item in m.items if getattr(item, 'canvas_discussion_id', None)),
            'module_items': sum(1 for m in modules for item in m.items if getattr(item, 'canvas_module_item_id', None)),
        }

        print(f"\nDetected IDs in markdown:")
        for id_type, count in id_counts.items():
            if count > 0:
                print(f"  {id_type}: {count}")

        has_existing = any(
            m.canvas_module_id or any(
                getattr(item, 'canvas_module_item_id', None) or
                getattr(item, 'canvas_page_id', None) or
                getattr(item, 'canvas_assignment_id', None) or
                getattr(item, 'canvas_discussion_id', None)
                for item in m.items
            )
            for m in modules
        )

        print(f"has_existing = {has_existing}\n")

        # Fetch existing data for comparison if in update mode
        if has_existing:
            self._fetch_existing_data(modules)

        # If dry-run, show preview with comparison results and exit
        if dry_run:
            self._preview(modules)
            return

        mode = "UPDATING" if has_existing else "CREATING"

        print("\n" + "=" * 60)
        print(f"PHASE 1: {mode} content")
        print("=" * 60)

        # First pass: Create or update all content and collect IDs
        for i, module in enumerate(modules, start=1):
            print(f"\n[Module {i}] {module.title}")
            
            # Create or update module
            if module.canvas_module_id:
                # Check if module has changes before updating
                canvas_data = self.canvas_data_cache['modules'].get(module.canvas_module_id)
                if canvas_data:
                    comparison = self.comparator.compare_module(module, canvas_data)
                    if comparison.has_changes:
                        result = self.api.update_module(module.canvas_module_id, module.title, position=i)
                        module.canvas_id = module.canvas_module_id
                        print(f"  ✓ Updated module (ID: {module.canvas_id}, changed: {', '.join(comparison.changed_fields)})")
                    else:
                        module.canvas_id = module.canvas_module_id
                        print(f"  • Module (ID: {module.canvas_id}, no changes, skipped)")
                else:
                    # No comparison data, perform update anyway
                    result = self.api.update_module(module.canvas_module_id, module.title, position=i)
                    module.canvas_id = module.canvas_module_id
                    print(f"  ✓ Updated module (ID: {module.canvas_id}, no comparison data)")
            else:
                result = self.api.create_module(module.title, position=i)
                module.canvas_id = result["id"]
                print(f"  ✓ Created module (ID: {module.canvas_id})")
            
            # Create or update content items
            for item in module.items:
                self._create_or_update_item(module, item)
        
        print("\n" + "=" * 60)
        print("PHASE 2: Resolving internal links")
        print("=" * 60)
        
        # Second pass: Resolve internal links and update content
        self._resolve_links()
        
        print("\n" + "=" * 60)
        print("PHASE 3: Adding items to modules")
        print("=" * 60)
        
        # Third pass: Add items to modules
        for module in modules:
            print(f"\n[Module] {module.title}")
            for position, item in enumerate(module.items, start=1):
                self._add_to_module(module, item, position)
        
        print("\n" + "=" * 60)
        print("COMPLETE!")
        print("=" * 60)

    def _fetch_existing_data(self, modules: list[Module]):
        """Fetch existing Canvas data for all items with IDs."""
        print("\n" + "=" * 60)
        print("PHASE 0.5: Fetching existing Canvas data for comparison")
        print("=" * 60)

        stats = {
            'modules': {'success': 0, 'failed': []},
            'pages': {'success': 0, 'failed': []},
            'assignments': {'success': 0, 'failed': []},
            'discussions': {'success': 0, 'failed': []},
            'module_items': {'success': 0, 'failed': []},
        }

        for module in modules:
            # Fetch module data
            if module.canvas_module_id:
                try:
                    module_data = self.api.get_module(module.canvas_module_id)
                    self.canvas_data_cache['modules'][module.canvas_module_id] = module_data
                    stats['modules']['success'] += 1
                except Exception as e:
                    stats['modules']['failed'].append({
                        'title': module.title,
                        'id': module.canvas_module_id,
                        'error': str(e)
                    })

            # Fetch item data
            for item in module.items:
                if isinstance(item, Page) and item.canvas_page_id:
                    try:
                        page_data = self.api.get_page(item.canvas_page_id)
                        self.canvas_data_cache['pages'][item.canvas_page_id] = page_data
                        stats['pages']['success'] += 1
                    except Exception as e:
                        stats['pages']['failed'].append({
                            'title': item.title,
                            'id': item.canvas_page_id,
                            'error': str(e)
                        })

                elif isinstance(item, Assignment) and item.canvas_assignment_id:
                    try:
                        assgn_data = self.api.get_assignment(item.canvas_assignment_id)
                        self.canvas_data_cache['assignments'][item.canvas_assignment_id] = assgn_data
                        stats['assignments']['success'] += 1
                    except Exception as e:
                        stats['assignments']['failed'].append({
                            'title': item.title,
                            'id': item.canvas_assignment_id,
                            'error': str(e)
                        })

                elif isinstance(item, Discussion) and item.canvas_discussion_id:
                    try:
                        disc_data = self.api.get_discussion(item.canvas_discussion_id)
                        self.canvas_data_cache['discussions'][item.canvas_discussion_id] = disc_data
                        stats['discussions']['success'] += 1
                    except Exception as e:
                        stats['discussions']['failed'].append({
                            'title': item.title,
                            'id': item.canvas_discussion_id,
                            'error': str(e)
                        })

                elif (isinstance(item, (TextHeader, ExternalLink)) and
                      getattr(item, 'canvas_module_item_id', None) and
                      module.canvas_module_id):
                    try:
                        item_data = self.api.get_module_item(module.canvas_module_id, item.canvas_module_item_id)
                        self.canvas_data_cache['module_items'][item.canvas_module_item_id] = item_data
                        stats['module_items']['success'] += 1
                    except Exception as e:
                        stats['module_items']['failed'].append({
                            'title': item.title,
                            'id': item.canvas_module_item_id,
                            'error': str(e)
                        })

        # Print summary
        total_success = sum(s['success'] for s in stats.values())
        total_failed = sum(len(s['failed']) for s in stats.values())

        print(f"\n  Successfully fetched: {total_success} items")
        if total_failed > 0:
            print(f"  Failed to fetch: {total_failed} items")
            print("\n  FETCH FAILURES:")
            for item_type, data in stats.items():
                if data['failed']:
                    print(f"\n  {item_type.upper()}:")
                    for failure in data['failed']:
                        print(f"    - \"{failure['title']}\" (ID: {failure['id']})")
                        print(f"      Error: {failure['error']}")
        print()

    def _create_or_update_item(self, module: Module, item):
        """Create or update a content item in Canvas."""
        if isinstance(item, TextHeader):
            # Text headers are created directly as module items (no separate content)
            # They will be updated in phase 3 if they have an existing ID
            print(f"  • [header] {item.title}")
        
        elif isinstance(item, Page):
            content = item.content
            if self.resolver and self.resolver.has_internal_links(content):
                self.items_needing_link_resolution.append(item)
            
            if item.canvas_page_id:
                # Check if page has changes before updating
                canvas_data = self.canvas_data_cache['pages'].get(item.canvas_page_id)
                if canvas_data:
                    comparison = self.comparator.compare_page(item, canvas_data)
                    if comparison.has_changes:
                        # Update existing page
                        result = self.api.update_page(item.canvas_page_id, content, title=item.title)
                        item.canvas_id = item.canvas_page_id
                        item.canvas_url = result.get("html_url", f"{self.api.base_url}/courses/{self.api.course_id}/pages/{item.canvas_page_id}")
                        print(f"  ✓ [page] {item.title} (updated: {', '.join(comparison.changed_fields)})")
                    else:
                        # No changes, skip update
                        item.canvas_id = item.canvas_page_id
                        item.canvas_url = canvas_data.get("html_url", f"{self.api.base_url}/courses/{self.api.course_id}/pages/{item.canvas_page_id}")
                        print(f"  • [page] {item.title} (no changes, skipped)")
                else:
                    # No comparison data, perform update anyway
                    result = self.api.update_page(item.canvas_page_id, content, title=item.title)
                    item.canvas_id = item.canvas_page_id
                    item.canvas_url = result.get("html_url", f"{self.api.base_url}/courses/{self.api.course_id}/pages/{item.canvas_page_id}")
                    print(f"  ✓ [page] {item.title} (updated - no comparison data)")
            else:
                # Create new page
                result = self.api.create_page(item.title, content)
                item.canvas_id = result["page_id"]
                item.canvas_url = result["html_url"]
                print(f"  ✓ [page] {item.title} (created)")
            
            if self.resolver:
                self.resolver.register_page(item)
        
        elif isinstance(item, ExternalLink):
            # External links are created/updated directly as module items
            print(f"  • [link] {item.title} → {item.url}")
        
        elif isinstance(item, File):
            # Look up the file in the course files
            file_data = self.api.get_file_by_name(item.filename, self.files_cache)
            if file_data:
                item.canvas_file_id = file_data.get('id')
                item.canvas_url = file_data.get('url')
                print(f"  ✓ [file] {item.title} → {item.filename} (ID: {item.canvas_file_id})")
            else:
                print(f"  ✗ [file] {item.title} → {item.filename} (NOT FOUND in course files)")
        
        elif isinstance(item, Assignment):
            content = item.description
            if self.resolver and self.resolver.has_internal_links(content):
                self.items_needing_link_resolution.append(item)
            
            submission_types = [st.value for st in item.submission_types]

            if item.canvas_assignment_id:
                # Check if assignment has changes before updating
                canvas_data = self.canvas_data_cache['assignments'].get(item.canvas_assignment_id)
                if canvas_data:
                    comparison = self.comparator.compare_assignment(item, canvas_data)
                    if comparison.has_changes:
                        # Update existing assignment
                        result = self.api.update_assignment_full(
                            assignment_id=item.canvas_assignment_id,
                            name=item.title,
                            description=content,
                            points_possible=item.points,
                            due_at=item.due_at,
                            grading_type=item.grade_display.to_canvas(),
                            submission_types=submission_types,
                        )
                        item.canvas_id = item.canvas_assignment_id
                        item.canvas_url = result.get("html_url", f"{self.api.base_url}/courses/{self.api.course_id}/assignments/{item.canvas_assignment_id}")
                        action = f"updated: {', '.join(comparison.changed_fields)}"
                    else:
                        # No changes, skip update
                        item.canvas_id = item.canvas_assignment_id
                        item.canvas_url = canvas_data.get("html_url", f"{self.api.base_url}/courses/{self.api.course_id}/assignments/{item.canvas_assignment_id}")
                        action = "no changes, skipped"
                else:
                    # No comparison data, perform update anyway
                    result = self.api.update_assignment_full(
                        assignment_id=item.canvas_assignment_id,
                        name=item.title,
                        description=content,
                        points_possible=item.points,
                        due_at=item.due_at,
                        grading_type=item.grade_display.to_canvas(),
                        submission_types=submission_types,
                    )
                    item.canvas_id = item.canvas_assignment_id
                    item.canvas_url = result.get("html_url", f"{self.api.base_url}/courses/{self.api.course_id}/assignments/{item.canvas_assignment_id}")
                    action = "updated - no comparison data"
            else:
                # Create new assignment
                result = self.api.create_assignment(
                    name=item.title,
                    description=content,
                    points_possible=item.points,
                    due_at=item.due_at,
                    grading_type=item.grade_display.to_canvas(),
                    submission_types=submission_types,
                )
                item.canvas_id = result["id"]
                item.canvas_url = result["html_url"]
                action = "created"

            if self.resolver:
                self.resolver.register_assignment(item)

            due_str = f" (due: {item.due_at.strftime('%b %d')})" if item.due_at else ""
            print(f"  ✓ [assignment] {item.title}{due_str} ({action})")
        
        elif isinstance(item, Discussion):
            content = item.message
            if self.resolver and self.resolver.has_internal_links(content):
                self.items_needing_link_resolution.append(item)
            
            discussion_type = "threaded" if item.threaded else "side_comment"

            if item.canvas_discussion_id:
                # Check if discussion has changes before updating
                canvas_data = self.canvas_data_cache['discussions'].get(item.canvas_discussion_id)
                if canvas_data:
                    comparison = self.comparator.compare_discussion(item, canvas_data)
                    if comparison.has_changes:
                        # Update existing discussion
                        result = self.api.update_discussion_full(
                            topic_id=item.canvas_discussion_id,
                            title=item.title,
                            message=content,
                            require_initial_post=item.require_initial_post,
                            discussion_type=discussion_type,
                            graded=item.graded,
                            points_possible=item.points if item.graded else 0,
                            due_at=item.due_at if item.graded else None,
                            grading_type=item.grade_display.to_canvas() if item.graded else "pass_fail",
                        )
                        item.canvas_id = item.canvas_discussion_id
                        item.canvas_url = result.get("html_url", f"{self.api.base_url}/courses/{self.api.course_id}/discussion_topics/{item.canvas_discussion_id}")
                        action = f"updated: {', '.join(comparison.changed_fields)}"
                    else:
                        # No changes, skip update
                        item.canvas_id = item.canvas_discussion_id
                        item.canvas_url = canvas_data.get("html_url", f"{self.api.base_url}/courses/{self.api.course_id}/discussion_topics/{item.canvas_discussion_id}")
                        action = "no changes, skipped"
                else:
                    # No comparison data, perform update anyway
                    result = self.api.update_discussion_full(
                        topic_id=item.canvas_discussion_id,
                        title=item.title,
                        message=content,
                        require_initial_post=item.require_initial_post,
                        discussion_type=discussion_type,
                        graded=item.graded,
                        points_possible=item.points if item.graded else 0,
                        due_at=item.due_at if item.graded else None,
                        grading_type=item.grade_display.to_canvas() if item.graded else "pass_fail",
                    )
                    item.canvas_id = item.canvas_discussion_id
                    item.canvas_url = result.get("html_url", f"{self.api.base_url}/courses/{self.api.course_id}/discussion_topics/{item.canvas_discussion_id}")
                    action = "updated - no comparison data"
            else:
                # Create new discussion
                result = self.api.create_discussion(
                    title=item.title,
                    message=content,
                    require_initial_post=item.require_initial_post,
                    discussion_type=discussion_type,
                    graded=item.graded,
                    points_possible=item.points if item.graded else 0,
                    due_at=item.due_at if item.graded else None,
                    grading_type=item.grade_display.to_canvas() if item.graded else "pass_fail",
                )
                item.canvas_id = result["id"]
                item.canvas_url = result["html_url"]
                action = "created"

            if self.resolver:
                self.resolver.register_discussion(item)

            graded_str = " (graded)" if item.graded else ""
            print(f"  ✓ [discussion] {item.title}{graded_str} ({action})")
    
    def _resolve_links(self):
        """Resolve internal links in content that needs it."""
        if not self.items_needing_link_resolution:
            print("\n  No internal links to resolve.")
            return
        
        for item in self.items_needing_link_resolution:
            if isinstance(item, Page):
                new_content = self.resolver.resolve(item.content)
                self.api.update_page(item.canvas_url.split('/')[-1], new_content)
                print(f"  ✓ Updated links in page: {item.title}")
            
            elif isinstance(item, Assignment):
                new_content = self.resolver.resolve(item.description)
                self.api.update_assignment(item.canvas_id, new_content)
                print(f"  ✓ Updated links in assignment: {item.title}")
            
            elif isinstance(item, Discussion):
                new_content = self.resolver.resolve(item.message)
                self.api.update_discussion(item.canvas_id, new_content)
                print(f"  ✓ Updated links in discussion: {item.title}")
    
    def _add_to_module(self, module: Module, item, position: int):
        """Add or update an item in a module."""
        # Check if this item already exists in the module
        existing_item_id = getattr(item, 'canvas_module_item_id', None)
        
        if isinstance(item, TextHeader):
            if existing_item_id:
                self.api.update_module_item(
                    module.canvas_id,
                    existing_item_id,
                    title=item.title,
                    position=position,
                )
                print(f"  ✓ Updated header: {item.title}")
            else:
                self.api.create_module_item(
                    module.canvas_id,
                    "SubHeader",
                    title=item.title,
                    position=position,
                )
                print(f"  ✓ Added header: {item.title}")
        
        elif isinstance(item, Page):
            if existing_item_id:
                self.api.update_module_item(
                    module.canvas_id,
                    existing_item_id,
                    position=position,
                )
                print(f"  ✓ Updated page position: {item.title}")
            else:
                self.api.create_module_item(
                    module.canvas_id,
                    "Page",
                    content_id=item.canvas_id,
                    page_url=item.canvas_url.split('/')[-1] if item.canvas_url else item.canvas_id,
                    position=position,
                )
                print(f"  ✓ Added page: {item.title}")
        
        elif isinstance(item, ExternalLink):
            if existing_item_id:
                self.api.update_module_item(
                    module.canvas_id,
                    existing_item_id,
                    title=item.title,
                    external_url=item.url,
                    position=position,
                )
                print(f"  ✓ Updated link: {item.title}")
            else:
                self.api.create_module_item(
                    module.canvas_id,
                    "ExternalUrl",
                    title=item.title,
                    external_url=item.url,
                    new_tab=True,
                    position=position,
                )
                print(f"  ✓ Added link: {item.title}")
        
        elif isinstance(item, File):
            if not item.canvas_file_id:
                print(f"  ✗ Skipped file (not found): {item.title}")
                return
            
            if existing_item_id:
                self.api.update_module_item(
                    module.canvas_id,
                    existing_item_id,
                    title=item.title,
                    position=position,
                )
                print(f"  ✓ Updated file position: {item.title}")
            else:
                self.api.create_module_item(
                    module.canvas_id,
                    "File",
                    content_id=item.canvas_file_id,
                    title=item.title,
                    position=position,
                )
                print(f"  ✓ Added file: {item.title}")
        
        elif isinstance(item, Assignment):
            if existing_item_id:
                self.api.update_module_item(
                    module.canvas_id,
                    existing_item_id,
                    position=position,
                )
                print(f"  ✓ Updated assignment position: {item.title}")
            else:
                self.api.create_module_item(
                    module.canvas_id,
                    "Assignment",
                    content_id=item.canvas_id,
                    position=position,
                )
                print(f"  ✓ Added assignment: {item.title}")
        
        elif isinstance(item, Discussion):
            if existing_item_id:
                self.api.update_module_item(
                    module.canvas_id,
                    existing_item_id,
                    position=position,
                )
                print(f"  ✓ Updated discussion position: {item.title}")
            else:
                self.api.create_module_item(
                    module.canvas_id,
                    "Discussion",
                    content_id=item.canvas_id,
                    position=position,
                )
                print(f"  ✓ Added discussion: {item.title}")
    
    def _preview(self, modules: list[Module]):
        """Preview what would be created or updated with actual change detection."""
        print("\n" + "=" * 60)
        print("PREVIEW (dry run - no changes will be made)")
        print("=" * 60)

        for i, module in enumerate(modules, start=1):
            # Check module for changes
            if module.canvas_module_id:
                canvas_data = self.canvas_data_cache['modules'].get(module.canvas_module_id)
                if canvas_data:
                    comparison = self.comparator.compare_module(module, canvas_data)
                    if comparison.has_changes:
                        mode = f"UPDATE (changed: {', '.join(comparison.changed_fields)})"
                    else:
                        mode = "SKIP (no changes)"
                else:
                    mode = "UPDATE (no comparison data)"
            else:
                mode = "CREATE"

            print(f"\n[Module {i}] {module.title} ({mode})")

            for item in module.items:
                if isinstance(item, TextHeader):
                    if getattr(item, 'canvas_module_item_id', None):
                        canvas_data = self.canvas_data_cache['module_items'].get(item.canvas_module_item_id)
                        if canvas_data:
                            comparison = self.comparator.compare_text_header(item, canvas_data)
                            if comparison.has_changes:
                                item_mode = f"update: {', '.join(comparison.changed_fields)}"
                            else:
                                item_mode = "skip (no changes)"
                        else:
                            item_mode = "update - no comparison data"
                    else:
                        item_mode = "create"
                    print(f"  • [header] {item.title} ({item_mode})")

                elif isinstance(item, Page):
                    if item.canvas_page_id:
                        canvas_data = self.canvas_data_cache['pages'].get(item.canvas_page_id)
                        if canvas_data:
                            comparison = self.comparator.compare_page(item, canvas_data)
                            if comparison.has_changes:
                                page_mode = f"update: {', '.join(comparison.changed_fields)}"
                            else:
                                page_mode = "skip (no changes)"
                        else:
                            page_mode = "update - no comparison data"
                    else:
                        page_mode = "create"
                    print(f"  • [page] {item.title} ({page_mode})")

                elif isinstance(item, ExternalLink):
                    if getattr(item, 'canvas_module_item_id', None):
                        canvas_data = self.canvas_data_cache['module_items'].get(item.canvas_module_item_id)
                        if canvas_data:
                            comparison = self.comparator.compare_external_link(item, canvas_data)
                            if comparison.has_changes:
                                item_mode = f"update: {', '.join(comparison.changed_fields)}"
                            else:
                                item_mode = "skip (no changes)"
                        else:
                            item_mode = "update - no comparison data"
                    else:
                        item_mode = "create"
                    print(f"  • [link] {item.title} ({item_mode})")
                    print(f"      URL: {item.url}")

                elif isinstance(item, File):
                    # Files are looked up, not compared for changes
                    file_data = self.api.get_file_by_name(item.filename, self.files_cache) if self.files_cache else None
                    if file_data:
                        print(f"  • [file] {item.title} (found: {item.filename})")
                    else:
                        print(f"  • [file] {item.title} (NOT FOUND: {item.filename})")

                elif isinstance(item, Assignment):
                    if item.canvas_assignment_id:
                        canvas_data = self.canvas_data_cache['assignments'].get(item.canvas_assignment_id)
                        if canvas_data:
                            comparison = self.comparator.compare_assignment(item, canvas_data)
                            if comparison.has_changes:
                                assgn_mode = f"update: {', '.join(comparison.changed_fields)}"
                            else:
                                assgn_mode = "skip (no changes)"
                        else:
                            assgn_mode = "update - no comparison data"
                    else:
                        assgn_mode = "create"
                    print(f"  • [assignment] {item.title} ({assgn_mode})")
                    print(f"      Points: {item.points}, Grade: {item.grade_display.value}")
                    print(f"      Submission: {', '.join(st.value for st in item.submission_types)}")
                    if item.due_at:
                        print(f"      Due: {item.due_at.strftime('%Y-%m-%d %I:%M %p')}")

                elif isinstance(item, Discussion):
                    if item.canvas_discussion_id:
                        canvas_data = self.canvas_data_cache['discussions'].get(item.canvas_discussion_id)
                        if canvas_data:
                            comparison = self.comparator.compare_discussion(item, canvas_data)
                            if comparison.has_changes:
                                disc_mode = f"update: {', '.join(comparison.changed_fields)}"
                            else:
                                disc_mode = "skip (no changes)"
                        else:
                            disc_mode = "update - no comparison data"
                    else:
                        disc_mode = "create"
                    graded_str = f", graded ({item.points} pts)" if item.graded else ""
                    threaded_str = "threaded" if item.threaded else "focused"
                    initial_str = ", require initial post" if item.require_initial_post else ""
                    print(f"  • [discussion] {item.title} ({disc_mode})")
                    print(f"      Type: {threaded_str}{initial_str}{graded_str}")
                    if item.graded and item.due_at:
                        print(f"      Due: {item.due_at.strftime('%Y-%m-%d %I:%M %p')}")

        print("\n" + "=" * 60)
        print("This was a dry run. No changes were made.")
        print("Remove --dry-run to apply these changes to Canvas.")
        print("=" * 60)


# =============================================================================
# Main
# =============================================================================

def main():
    # Check command line arguments
    if len(sys.argv) < 2:
        print("Canvas Course Builder")
        print("=" * 60)
        print("\nUsage: python canvas_course_builder.py <markdown_file> [OPTIONS]")
        print("\nOptions:")
        print("  --dry-run       Preview changes without applying them")
        print("  --reset-token   Force re-prompt for API token and update Keychain")
        print("\nExample: python canvas_course_builder.py course_content.md --dry-run")
        sys.exit(1)
    
    markdown_file = sys.argv[1]
    dry_run = "--dry-run" in sys.argv
    reset_token = "--reset-token" in sys.argv

    # Read markdown file first (to extract frontmatter)
    try:
        with open(markdown_file, 'r', encoding='utf-8') as f:
            file_content = f.read()
    except FileNotFoundError:
        print(f"\nError: File '{markdown_file}' not found.")
        sys.exit(1)

    # Extract frontmatter (if present)
    metadata, content = extract_frontmatter(file_content)

    # Get Canvas URL (priority: frontmatter > DEFAULT > prompt)
    canvas_url = metadata.get('canvas_url') or DEFAULT_CANVAS_URL
    if not canvas_url:
        canvas_url = input("Enter your Canvas URL (e.g., https://kent.instructure.com): ").strip()
        if not canvas_url:
            print("Error: Canvas URL is required.")
            sys.exit(1)
    elif 'canvas_url' in metadata:
        print(f"  Using Canvas URL from frontmatter: {canvas_url}")

    # Ensure URL has https:// prefix
    if not canvas_url.startswith("http"):
        canvas_url = "https://" + canvas_url

    # Get Course ID (priority: frontmatter > DEFAULT > prompt)
    course_id = metadata.get('course_id')
    if course_id:
        course_id = str(course_id)  # Convert to string if needed
        print(f"  Using Course ID from frontmatter: {course_id}")
    else:
        course_id = DEFAULT_COURSE_ID
        if not course_id:
            course_id = input("Enter your Course ID (e.g., 126998): ").strip()
            if not course_id:
                print("Error: Course ID is required.")
                sys.exit(1)

    print("\n" + "=" * 60)
    print("Canvas Course Builder")
    print(f"Course: {canvas_url}/courses/{course_id}")
    print("=" * 60)

    # Parse markdown (use content without frontmatter)
    print(f"\nParsing {markdown_file}...")
    parser = MarkdownParser(content)  # Not file_content!
    modules = parser.parse()
    
    print(f"Found {len(modules)} modules with {sum(len(m.items) for m in modules)} items.")

    # Get API token (needed even for dry-run to fetch existing data)
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

    # Create API client
    api = CanvasAPI(canvas_url, course_id, api_token)
    builder = CourseBuilder(api)

    if dry_run:
        # Dry-run mode: fetch existing data and show preview
        builder.build(modules, dry_run=True)
    else:
        # Confirm before making changes
        print(f"\nThis will create/update {len(modules)} modules with {sum(len(m.items) for m in modules)} items.")
        confirm = input("Proceed? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("Aborted.")
            sys.exit(0)

        # Build course
        builder.build(modules)


if __name__ == "__main__":
    main()
