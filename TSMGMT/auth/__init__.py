# TSMGMT/auth/__init__.py

# Expose the Blueprint so it can be imported directly from the package
from .routes import auth_bp

__all__ = ['auth_bp']
