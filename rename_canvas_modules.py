#!/usr/bin/env python3
"""
Canvas LMS Module Renamer
Renames modules to include Tuesday/Thursday dates for each week.
"""

import requests
from datetime import datetime, timedelta

# Configuration
CANVAS_URL = "https://kent.instructure.com"
COURSE_ID = "126998"

# Start date: First Tuesday of the semester
# January 13, 2026 is a Tuesday
START_DATE = datetime(2026, 1, 13)

# Spring break: calendar week 9 (Mar 10 & 12) - skip this week
# Week NUMBER 9 is also skipped (goes from Week 8 to Week 10)

def get_week_number(module_position: int) -> int:
    """
    Convert module position (1-15) to week number.
    Skips week 9: positions 1-8 → weeks 1-8, positions 9-15 → weeks 10-16.
    """
    if module_position <= 8:
        return module_position
    else:
        return module_position + 1  # Skip week 9

def get_week_dates(week_number: int) -> tuple[str, str]:
    """
    Calculate Tuesday and Thursday dates for a given week number.
    Week numbers 1-8 map to calendar weeks 1-8.
    Week numbers 10+ map to calendar weeks 10+ (spring break is calendar week 9).
    Returns formatted strings like ("Jan 13", "15")
    """
    # Week number equals calendar week (since we skip both week 9 and spring break)
    calendar_week = week_number
    
    # Calculate the Tuesday of the given calendar week
    tuesday = START_DATE + timedelta(weeks=calendar_week - 1)
    thursday = tuesday + timedelta(days=2)
    
    # Format the dates
    tue_str = tuesday.strftime("%b %d").replace(" 0", " ")  # "Jan 13" not "Jan 01"
    
    # If same month, just show the day number for Thursday
    if tuesday.month == thursday.month:
        thu_str = str(thursday.day)
    else:
        thu_str = thursday.strftime("%b %d").replace(" 0", " ")
    
    return tue_str, thu_str

def generate_module_name(module_position: int) -> str:
    """Generate the new module name for a given module position."""
    week_num = get_week_number(module_position)
    tue_date, thu_date = get_week_dates(week_num)
    return f"Week {week_num} - {tue_date} & {thu_date}"

def get_modules(api_token: str) -> list[dict]:
    """Fetch all modules from the course."""
    headers = {"Authorization": f"Bearer {api_token}"}
    url = f"{CANVAS_URL}/api/v1/courses/{COURSE_ID}/modules"
    
    modules = []
    while url:
        response = requests.get(url, headers=headers, params={"per_page": 100})
        response.raise_for_status()
        modules.extend(response.json())
        
        # Handle pagination
        url = response.links.get("next", {}).get("url")
    
    return modules

def update_module_name(api_token: str, module_id: int, new_name: str) -> dict:
    """Update a module's name."""
    headers = {"Authorization": f"Bearer {api_token}"}
    url = f"{CANVAS_URL}/api/v1/courses/{COURSE_ID}/modules/{module_id}"
    
    response = requests.put(url, headers=headers, data={"module[name]": new_name})
    response.raise_for_status()
    return response.json()

def main():
    print("=" * 60)
    print("Canvas Module Renamer")
    print(f"Course: {CANVAS_URL}/courses/{COURSE_ID}")
    print("=" * 60)
    print()
    
    # Get API token
    api_token = input("Enter your Canvas API token: ").strip()
    if not api_token:
        print("Error: No token provided.")
        return
    
    # Fetch modules
    print("\nFetching modules...")
    try:
        modules = get_modules(api_token)
    except requests.exceptions.HTTPError as e:
        print(f"Error fetching modules: {e}")
        return
    
    print(f"Found {len(modules)} modules.\n")
    
    # Sort modules by position
    modules.sort(key=lambda m: m.get("position", 0))
    
    # We only process 15 modules (weeks 1-8 and 10-16, skipping week 9)
    MAX_MODULES = 15
    if len(modules) > MAX_MODULES:
        print(f"Note: Found {len(modules)} modules, but only processing the first {MAX_MODULES}.")
        print(f"      (Weeks 1-8 and 10-16, skipping week 9 for spring break)\n")
        modules = modules[:MAX_MODULES]
    
    # Generate preview
    print("=" * 60)
    print("PREVIEW OF CHANGES")
    print("=" * 60)
    
    changes = []
    for i, module in enumerate(modules, start=1):
        old_name = module["name"]
        new_name = generate_module_name(i)
        changes.append({
            "id": module["id"],
            "old_name": old_name,
            "new_name": new_name
        })
        
        if old_name != new_name:
            print(f"  [{i:2}] \"{old_name}\"")
            print(f"    → \"{new_name}\"")
            print()
        else:
            print(f"  [{i:2}] \"{old_name}\" (no change)")
            print()
    
    # Confirm
    print("=" * 60)
    confirm = input("Apply these changes? (yes/no): ").strip().lower()
    
    if confirm != "yes":
        print("Aborted. No changes made.")
        return
    
    # Apply changes
    print("\nApplying changes...")
    for change in changes:
        if change["old_name"] != change["new_name"]:
            try:
                update_module_name(api_token, change["id"], change["new_name"])
                print(f"  ✓ Updated: {change['new_name']}")
            except requests.exceptions.HTTPError as e:
                print(f"  ✗ Failed to update {change['old_name']}: {e}")
        else:
            print(f"  - Skipped (no change): {change['old_name']}")
    
    print("\nDone!")

if __name__ == "__main__":
    main()
