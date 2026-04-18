"""
Tests de autenticación y usuarios.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestAuth:
    """Tests para sistema de autenticación."""
    
    def test_crear_usuario(self, temp_db, clean_user):
        """Test crear usuario básico."""
        from database import create_user
        ok, mensaje = create_user(
            username=clean_user,
            display_name="Test User",
            password="test123456",
            email=f"{clean_user}@test.com"
        )
        assert isinstance(ok, bool)
        assert isinstance(mensaje, str)
    
    def test_autenticar_usuario_existente(self, temp_db, clean_user):
        """Test autenticar usuario que existe."""
        from database import create_user, authenticate_user
        ok, _ = create_user(
            username=clean_user,
            display_name="Auth Test",
            password="password123",
            email=f"{clean_user}@test.com"
        )
        
        if ok:
            user = authenticate_user(clean_user, "password123")
            assert user is not None
            assert "username" in user
            assert "role" in user
    
    def test_autenticar_password_incorrecto(self, temp_db, clean_user):
        """Test autenticar con password incorrecto."""
        from database import create_user, authenticate_user
        create_user(
            username=clean_user,
            display_name="Wrong Pass",
            password="correct_password",
            email=f"{clean_user}@test.com"
        )
        
        user = authenticate_user(clean_user, "wrong_password")
        assert user is None
    
    def test_get_all_users(self, temp_db):
        """Test obtener lista de usuarios."""
        from database import get_all_users
        df = get_all_users()
        assert df is not None


class TestPasswordChange:
    """Tests para cambio de contraseña."""
    
    def test_actualizar_password(self, temp_db, sample_user):
        """Test actualizar contraseña."""
        from database import update_user_password, get_all_users
        if not sample_user["ok"]:
            pytest.skip("No se pudo crear usuario de prueba")
        
        df = get_all_users()
        if df.empty:
            pytest.skip("No hay usuarios para probar")
        
        user_id = df.iloc[0]["id"]
        ok, mensaje = update_user_password(
            user_id=user_id,
            current_password="TestPassword123!",
            new_password="new_password123"
        )
        
        assert isinstance(ok, bool)
        assert isinstance(mensaje, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
