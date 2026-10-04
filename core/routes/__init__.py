"""
Kage API Routes Package.
Deconstructs HTTP REST endpoints from server.py into modular APIRouters.
"""

from core.routes.system import router as system_router
from core.routes.models import router as models_router
from core.routes.memory import router as memory_router
from core.routes.browser_tasks import router as browser_tasks_router

__all__ = ["system_router", "models_router", "memory_router", "browser_tasks_router"]
