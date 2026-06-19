"""
Pruebas de Carga — EnViExpress con Locust
Ejecutar con:
  locust -f tests/locustfile.py --host=https://enviexprespy.onrender.com
Luego abrir: http://localhost:8089

NOTA: Las pruebas cubren rutas públicas y el flujo de login.
Las rutas protegidas se validan via pytest (test_enviexprespy.py).
"""

import os
from dotenv import load_dotenv
from locust import HttpUser, task, between

load_dotenv(".env.test")

ADMIN_USER     = os.getenv("LOCUST_ADMIN_USER", "admin")
ADMIN_PASS     = os.getenv("LOCUST_ADMIN_PASS", "123")
CLIENT_USER    = os.getenv("LOCUST_CLIENT_USER", "cliente")
CLIENT_PASS    = os.getenv("LOCUST_CLIENT_PASS", "123")
MENSAJERO_USER = os.getenv("LOCUST_MENSAJERO_USER", "mensajero")
MENSAJERO_PASS = os.getenv("LOCUST_MENSAJERO_PASS", "123")


class UsuarioAnonimo(HttpUser):
    """
    Simula usuarios no autenticados navegando el sistema.
    Peso: 40% del tráfico — usuarios que llegan al sitio.
    """
    wait_time = between(1, 3)
    weight = 2

    @task(5)
    def ver_landing(self):
        self.client.get("/", name="[PUBLIC] Landing page")

    @task(4)
    def ver_login(self):
        self.client.get("/login", name="[PUBLIC] Página de login")

    @task(3)
    def ver_registro(self):
        self.client.get("/registro", name="[PUBLIC] Página de registro")

    @task(2)
    def ver_recuperar(self):
        self.client.get("/recuperar", name="[PUBLIC] Recuperar contraseña")

    @task(2)
    def ver_seguimiento(self):
        self.client.get("/seguimiento", name="[PUBLIC] Seguimiento de envío")


class UsuarioHaciendoLogin(HttpUser):
    """
    Simula usuarios intentando autenticarse.
    Mide el tiempo de respuesta del servidor al procesar logins.
    Peso: 30% del tráfico.
    """
    wait_time = between(2, 5)
    weight = 2

    @task(3)
    def login_admin(self):
        """Simula login del admin — mide respuesta del servidor."""
        with self.client.post(
            "/login",
            data={"username": ADMIN_USER, "password": ADMIN_PASS},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            name="[AUTH] Login Admin",
            allow_redirects=False,
            catch_response=True
        ) as response:
            # 302/303/307 = redirect exitoso, 200 = formulario (error)
            if response.status_code in [302, 303, 307]:
                response.success()
            elif response.status_code == 200:
                # El servidor procesó pero devolvió el form (credenciales inválidas)
                response.success()  # El servidor respondió — eso es lo que medimos
            else:
                response.failure(f"Error inesperado: {response.status_code}")

    @task(2)
    def login_cliente(self):
        """Simula login de cliente."""
        with self.client.post(
            "/login",
            data={"username": CLIENT_USER, "password": CLIENT_PASS},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            name="[AUTH] Login Cliente",
            allow_redirects=False,
            catch_response=True
        ) as response:
            if response.status_code in [200, 302, 303, 307]:
                response.success()
            else:
                response.failure(f"Error: {response.status_code}")

    @task(1)
    def login_mensajero(self):
        """Simula login de mensajero."""
        with self.client.post(
            "/login",
            data={"username": MENSAJERO_USER, "password": MENSAJERO_PASS},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            name="[AUTH] Login Mensajero",
            allow_redirects=False,
            catch_response=True
        ) as response:
            if response.status_code in [200, 302, 303, 307]:
                response.success()
            else:
                response.failure(f"Error: {response.status_code}")


class UsuarioNavegando(HttpUser):
    """
    Simula carga mixta — navega entre páginas públicas simulando
    el comportamiento real de múltiples usuarios simultáneos.
    Peso: 30% del tráfico.
    """
    wait_time = between(1, 4)
    weight = 1

    @task(4)
    def flujo_landing_a_login(self):
        """Simula el flujo más común: landing → login."""
        self.client.get("/", name="[FLUJO] 1. Landing")
        self.client.get("/login", name="[FLUJO] 2. Ir a login")

    @task(3)
    def flujo_landing_a_registro(self):
        """Simula nuevo usuario: landing → registro."""
        self.client.get("/", name="[FLUJO] 1. Landing")
        self.client.get("/registro", name="[FLUJO] 2. Ir a registro")

    @task(2)
    def flujo_seguimiento(self):
        """Simula cliente consultando seguimiento."""
        self.client.get("/", name="[FLUJO] 1. Landing")
        self.client.get("/seguimiento", name="[FLUJO] 2. Seguimiento")

    @task(1)
    def flujo_recuperar_clave(self):
        """Simula usuario recuperando contraseña."""
        self.client.get("/login", name="[FLUJO] 1. Login")
        self.client.get("/recuperar", name="[FLUJO] 2. Recuperar clave")