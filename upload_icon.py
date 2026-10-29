#!/usr/bin/env python
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from club.models import Team
from django.core.files import File

def upload_icon(team_id, svg_path):
    """Upload SVG icon to team"""
    try:
        team = Team.objects.get(id=team_id)

        with open(svg_path, 'rb') as f:
            # Use Django's File wrapper for proper file handling
            team.currency_icon.save(os.path.basename(svg_path), File(f), save=True)

        print(f"✓ Successfully uploaded icon for team '{team.name}'")
        print(f"  Icon URL: {team.currency_icon.url}")

    except Team.DoesNotExist:
        print(f"✗ Team with ID {team_id} not found")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python upload_icon.py <team_id> <svg_file_path>")
        sys.exit(1)

    team_id = int(sys.argv[1])
    svg_path = sys.argv[2]

    if not os.path.exists(svg_path):
        print(f"✗ File not found: {svg_path}")
        sys.exit(1)

    upload_icon(team_id, svg_path)
