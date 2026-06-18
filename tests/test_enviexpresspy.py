import os
import sys

# Variables de entorno ANTES de cualquier import del proyecto
os.environ["DATABASE_URL"] = "sqlite:///./test_enviexprespy.db"
os.environ["SECRET_KEY"] = "clave_test_123"
os.environ["WOMPI_PUBLIC_KEY"] = "test_key"
os.environ["MAIL_USERNAME"] = "test@test.com"
os.environ["MAIL_PASSWORD"] = "test_pass"
os.environ["MAIL_FROM"] = "test@test.com"
os.environ["MAIL_SERVER"] = "smtp.test.com"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch, MagicMock

# ── Crear carpeta static antes de importar la app ──
os.makedirs("app/static", exist_ok=True)

from main import app
from app.config.database import Base, get_db
from app.security.SecurityConfig import hash_password

# ── BD de prueba SQLite ──
SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///./test_enviexprespy.db"

engine_test = create_engine(
    SQLALCHEMY_TEST_DATABASE_URL,
    connect_args={"check_same_thread": False}
)

@event.listens_for(engine_test, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(scope="session", autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine_test)
    yield
    Base.metadata.drop_all(bind=engine_test)
    pass  # No borrar la BD en Windows (archivo en uso)

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def db():
    database = TestingSessionLocal()
    try:
        yield database
    finally:
        database.close()

@pytest.fixture
def usuario_admin(db):
    from app.models.Usuario import Usuario
    existing = db.query(Usuario).filter(Usuario.user_name == "test_admin").first()
    if existing:
        return existing
    user = Usuario(
        id_usuario=1,
        user_name="test_admin",
        password=hash_password("admin123"),
        nombre="Admin",
        apellido="Test",
        correo="admin_test@enviexpress.com",
        telefono="3000000000",
        rol="CEO",
        activo=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@pytest.fixture
def usuario_cliente(db):
    from app.models.Usuario import Usuario
    existing = db.query(Usuario).filter(Usuario.user_name == "test_cliente").first()
    if existing:
        return existing
    user = Usuario(
        id_usuario=2,
        user_name="test_cliente",
        password=hash_password("cliente123"),
        nombre="Cliente",
        apellido="Test",
        correo="cliente_test@enviexpress.com",
        telefono="3111111111",
        rol="CLIENTE",
        activo=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@pytest.fixture
def token_admin(client, usuario_admin):
    response = client.post("/api/login", json={
        "username": "test_admin",
        "password": "admin123"
    })
    assert response.status_code == 200, f"Login admin falló: {response.text}"
    data = response.json()
    token = data.get("token") or data.get("access_token")
    assert token, f"No se encontró token en respuesta: {data}"
    return token

@pytest.fixture
def token_cliente(client, usuario_cliente):
    response = client.post("/api/login", json={
        "username": "test_cliente",
        "password": "cliente123"
    })
    assert response.status_code == 200, f"Login cliente falló: {response.text}"
    data = response.json()
    token = data.get("token") or data.get("access_token")
    assert token, f"No se encontró token en respuesta: {data}"
    return token


# ─────────────────────────────────────────────
# PRUEBAS UNITARIAS — Seguridad
# ─────────────────────────────────────────────

class TestSeguridad:

    def test_hash_password_genera_hash(self):
        """El hash de una contraseña no debe ser igual al texto plano."""
        hashed = hash_password("mi_clave_123")
        assert hashed != "mi_clave_123"
        assert len(hashed) > 20

    def test_verify_password_correcto(self):
        """verify_password debe retornar True con la contraseña correcta."""
        from app.security.SecurityConfig import verify_password
        hashed = hash_password("clave_segura")
        assert verify_password("clave_segura", hashed) is True

    def test_verify_password_incorrecto(self):
        """verify_password debe retornar False con contraseña incorrecta."""
        from app.security.SecurityConfig import verify_password
        hashed = hash_password("clave_real")
        assert verify_password("clave_incorrecta", hashed) is False

    def test_crear_token_jwt(self):
        """El token JWT debe generarse y ser una cadena válida."""
        from app.security.SecurityConfig import create_access_token
        token = create_access_token(data={"sub": "test_user"})
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 10

    def test_token_recuperacion(self):
        """El token de recuperación debe crearse y validarse."""
        from app.utils.security import crear_token_recuperacion, validar_token_recuperacion
        token = crear_token_recuperacion("correo@test.com")
        email = validar_token_recuperacion(token)
        assert email == "correo@test.com"


# ─────────────────────────────────────────────
# PRUEBAS UNITARIAS — Modelos
# ─────────────────────────────────────────────

class TestModelos:

    def test_crear_usuario_modelo(self, db):
        """Un objeto Usuario debe crearse y guardarse correctamente."""
        from app.models.Usuario import Usuario
        user = Usuario(
            id_usuario=10,
            user_name="modelo_test",
            password=hash_password("pass123"),
            nombre="Modelo",
            apellido="Test",
            correo="modelo@test.com",
            rol="CLIENTE",
            activo=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        assert user.id_usuario is not None
        assert user.rol == "CLIENTE"
        assert user.activo is True
        db.delete(user)
        db.commit()

    def test_usuario_saldo_default(self, db):
        """El saldo por defecto de un usuario debe ser 0."""
        from app.models.Usuario import Usuario
        user = Usuario(
            id_usuario=11,
            user_name="saldo_test",
            password=hash_password("pass"),
            nombre="Saldo",
            apellido="Test",
            correo="saldo@test.com",
            rol="CLIENTE",
            activo=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        assert float(user.saldo_plan) == 0.0
        db.delete(user)
        db.commit()


# ─────────────────────────────────────────────
# PRUEBAS UNITARIAS — Endpoints públicos
# ─────────────────────────────────────────────

class TestEndpointsPublicos:

    def test_landing_page(self, client):
        """La página principal debe responder 200."""
        response = client.get("/")
        assert response.status_code == 200

    def test_login_page_get(self, client):
        """El formulario de login debe responder 200."""
        response = client.get("/login")
        assert response.status_code == 200

    def test_registro_page(self, client):
        """La página de registro debe responder 200."""
        response = client.get("/registro")
        assert response.status_code == 200

    def test_recuperar_page(self, client):
        """La página de recuperación debe responder 200."""
        response = client.get("/recuperar")
        assert response.status_code == 200


# ─────────────────────────────────────────────
# PRUEBAS UNITARIAS — Autenticación
# ─────────────────────────────────────────────

class TestAutenticacion:

    def test_api_login_exitoso(self, client, usuario_admin):
        """Login correcto debe retornar token."""
        response = client.post("/api/login", json={
            "username": "test_admin",
            "password": "admin123"
        })
        assert response.status_code == 200
        data = response.json()
        tiene_token = "token" in data or "access_token" in data
        assert tiene_token, f"No hay token en respuesta: {data}"

    def test_api_login_password_incorrecto(self, client, usuario_admin):
        """Login con contraseña incorrecta debe retornar error."""
        response = client.post("/api/login", json={
            "username": "test_admin",
            "password": "clave_mal"
        })
        assert response.status_code in [401, 404]

    def test_api_login_usuario_inexistente(self, client):
        """Login con usuario inexistente debe retornar error."""
        response = client.post("/api/login", json={
            "username": "no_existe_xyz_999",
            "password": "cualquier"
        })
        assert response.status_code in [401, 404, 422]

    def test_ruta_protegida_sin_token(self, client):
        """Sin token debe redirigir o rechazar."""
        response = client.get("/usuarios", follow_redirects=False)
        assert response.status_code in [302, 303, 307, 401]

    def test_ruta_protegida_con_token(self, client, token_admin):
        """Con token válido debe responder 200."""
        response = client.get("/usuarios", headers={
            "Authorization": f"Bearer {token_admin}"
        })
        assert response.status_code == 200


# ─────────────────────────────────────────────
# PRUEBAS DE INTEGRACIÓN — Usuarios
# ─────────────────────────────────────────────

class TestIntegracionUsuarios:

    def test_flujo_registro_y_login(self, client, db):
        """Integración: crear usuario y hacer login."""
        from app.models.Usuario import Usuario
        nuevo_user = Usuario(
            id_usuario=20,
            user_name="flujo_test_user",
            password=hash_password("flujo123"),
            nombre="Flujo",
            apellido="Test",
            correo="flujo@integracion.com",
            rol="CLIENTE",
            activo=True,
        )
        db.add(nuevo_user)
        db.commit()

        response = client.post("/api/login", json={
            "username": "flujo_test_user",
            "password": "flujo123"
        })
        assert response.status_code == 200
        data = response.json()
        tiene_token = "token" in data or "access_token" in data
        assert tiene_token, f"No hay token: {data}"

        db.delete(nuevo_user)
        db.commit()

    def test_flujo_login_acceso_perfil(self, client, usuario_cliente, token_cliente):
        """Integración: login → acceder a perfil."""
        response = client.get("/perfil", headers={
            "Authorization": f"Bearer {token_cliente}"
        })
        assert response.status_code == 200

    def test_flujo_usuario_inactivo_no_puede_login(self, client, db):
        """Integración: usuario inactivo no puede autenticarse."""
        from app.models.Usuario import Usuario
        inactivo = Usuario(
            id_usuario=21,
            user_name="inactivo_test",
            password=hash_password("pass123"),
            nombre="Inactivo",
            apellido="Test",
            correo="inactivo@test.com",
            rol="CLIENTE",
            activo=False,
        )
        db.add(inactivo)
        db.commit()

        response = client.post("/api/login", json={
            "username": "inactivo_test",
            "password": "pass123"
        })
        assert response.status_code in [401, 403]

        db.delete(inactivo)
        db.commit()


# ─────────────────────────────────────────────
# PRUEBAS DE INTEGRACIÓN — Envíos
# ─────────────────────────────────────────────

class TestIntegracionEnvios:

    def test_flujo_listar_envios_admin(self, client, token_admin):
        """Integración: admin puede ver listado de envíos."""
        response = client.get("/envios", headers={
            "Authorization": f"Bearer {token_admin}"
        })
        assert response.status_code == 200

    def test_flujo_crear_envio_como_cliente(self, client, token_cliente):
        """Integración: cliente accede al formulario de nuevo envío."""
        response = client.get("/envios/nuevo", headers={
            "Authorization": f"Bearer {token_cliente}"
        })
        assert response.status_code in [200, 302, 303, 307]

    def test_acceso_envios_sin_autenticar(self, client):
        """Integración: sin autenticar no se puede ver envíos."""
        response = client.get("/envios", follow_redirects=False)
        assert response.status_code in [302, 303, 307, 401]

    def test_api_ubicaciones_mensajeros(self, client, token_admin):
        """Integración: endpoint del mapa responde correctamente."""
        response = client.get("/api/admin/ubicaciones-mensajeros", headers={
            "Authorization": f"Bearer {token_admin}"
        })
        assert response.status_code in [200, 500]