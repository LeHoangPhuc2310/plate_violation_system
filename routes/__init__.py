"""
Flask routes for the Plate Violation System.

This package contains all route handlers organized by functionality:
- auth.py: Authentication routes (login, logout)
- main.py: Main application routes (index, home, video feed)
- violations.py: Violation viewing and management routes
- admin.py: Admin routes (vehicle management)
- api.py: API endpoints (health, status, etc.)
"""

from .auth import init_auth_routes
from .main import init_main_routes
from .violations import init_violations_routes
from .admin import init_admin_routes
from .api import init_api_routes

__all__ = [
    'init_auth_routes',
    'init_main_routes',
    'init_violations_routes',
    'init_admin_routes',
    'init_api_routes'
]

