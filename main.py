import os
import uvicorn
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware

# Importar configuración de DB y Templates
from app.config.database import engine, Base, SessionLocal
from app.config.data_initializer import init_database
# IMPORTANTE: Usamos la configuración centralizada de templates para evitar errores
from app.config.templates import templates 
from fastapi.staticfiles import StaticFiles

# Importar los routers
from app.controllers.LandingController import router as landing_router
from app.controllers.HomeController import router as home_router
from app.controllers.UsuarioController import router as usuario_router
from app.controllers.EnvioController import router as envio_router
from app.controllers.VehiculoController import router as vehiculo_router
from app.controllers.TarifaController import router as tarifa_router
from app.controllers.SeguimientoController import router as seguimiento_router
from app.controllers.RutaController import router as ruta_router 
from app.controllers.AppMensajeroController import router as app_mensajero_router
from app.controllers import UsuarioController

app = FastAPI(
    title="EnvíExpress API",
    description="Sistema de gestión de envíos y logística profesional",
    version="1.0.0"
)

app.include_router(UsuarioController.router, prefix="/envios")
# --- Middlewares ---
# Secret key debe ser consistente para mantener sesiones de usuario
app.add_middleware(SessionMiddleware, secret_key="enviexpress_super_secret_key_2026")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Correcto para desarrollo con Flutter
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Base de Datos ---
# Crea las tablas si no existen
Base.metadata.create_all(bind=engine)

# --- Inclusión de Routers ---
app.include_router(landing_router)
app.include_router(home_router)
app.include_router(usuario_router)
app.include_router(envio_router)
app.include_router(vehiculo_router)
app.include_router(tarifa_router)
app.include_router(seguimiento_router)
app.include_router(ruta_router)
app.include_router(app_mensajero_router)

# --- Eventos de Ciclo de Vida ---
@app.on_event("startup")
def startup_event():
    """Inicializa datos base (roles, estados, etc.) al arrancar"""
    db = SessionLocal()
    try:
        init_database(db)
    finally:
        db.close()
        
        app.mount("/static", StaticFiles(directory="app/static"), name="static")

# --- Ejecución del Servidor ---
if __name__ == "__main__":
    # Puerto 8080 coincide con tu entorno de desarrollo
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
    
    #uvicorn main:app --reload --port 8080