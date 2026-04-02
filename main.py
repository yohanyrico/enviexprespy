import os
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware
from app.config.database import engine, Base, SessionLocal
from app.config.data_initializer import init_database

# Importar los routers
from app.controllers.LandingController import router as landing_router
from app.controllers.HomeController import router as home_router
from app.controllers.UsuarioController import router as usuario_router
from app.controllers.EnvioController import router as envio_router
from app.controllers.VehiculoController import router as vehiculo_router
from app.controllers.TarifaController import router as tarifa_router
from app.controllers.SeguimientoController import router as seguimiento_router
from app.controllers.RutaController import router as ruta_router 
from app.controllers.AppMensajeroController import router as app_mensajero_router # <--- NUEVO

# Importar modelos
from app.models.Usuario import Usuario
from app.models.Envio import Envio
from app.models.Lugar import Lugar
from app.models.Ruta import Ruta
from app.models.Seguimiento import Seguimiento
from app.models.Tarifa import Tarifa
from app.models.Vehiculo import Vehiculo

# Configuración de templates
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

app = FastAPI(
    title="EnvíExpress API",
    description="Sistema de gestión de envíos",
    version="1.0.0"
)

# Middlewares
app.add_middleware(SessionMiddleware, secret_key="tu_clave_secreta_muy_segura")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Permitir que Flutter se conecte
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Crear tablas
Base.metadata.create_all(bind=engine)

# Incluir rutas
app.include_router(landing_router)
app.include_router(home_router)
app.include_router(usuario_router)
app.include_router(envio_router)
app.include_router(vehiculo_router)
app.include_router(tarifa_router)
app.include_router(seguimiento_router)
app.include_router(ruta_router)
app.include_router(app_mensajero_router) # <--- NUEVO: Registro de la ruta para la App

@app.on_event("startup")
def startup_event():
    db = SessionLocal()
    try:
        init_database(db)
    finally:
        db.close()

if __name__ == "__main__":
    import uvicorn
    # Puerto 8080 según tu configuración
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
    
    #uvicorn main:app --reload --port 8080