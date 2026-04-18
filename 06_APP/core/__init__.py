"""
Core - Nucleo de la aplicación JrAI11
Este paquete contiene la lógica de negocio sin dependencias de UI.
"""

def get_session_module():
    """Lazy import del módulo de sesión."""
    from . import auth
    return auth.session


def get_components_module():
    """Lazy import del módulo de componentes UI."""
    from . import ui
    return ui.components


__all__ = [
    "get_session_module",
    "get_components_module",
]
