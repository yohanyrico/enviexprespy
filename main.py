import os
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy.orm import Session  # <--- CORREGIDO: Usamos SQLAlchemy, no requests
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles


# Importar configuración de DB
from app.config.database import engine, Base, SessionLocal
from app.config.data_initializer import init_database
from app.config.templates import templates 
from app.security.SecurityConfig import hash_password  # asegúrate que esté importado

# Importar modelos (Asegúrate de importar el modelo Usuario para la consulta)
from app.models.Usuario import Usuario 
from app.models.Usuario import Usuario

# Importar los routers
from app.controllers.LandingController import router as landing_router
from app.controllers.HomeController import router as home_router
from app.controllers.UsuarioController import router as usuario_router
from app.controllers.EnvioController import router as envio_router
from app.controllers.VehiculoController import router as vehiculo_router
from app.controllers.TarifaController import router as tarifa_router
from app.controllers.SeguimientoController import router as seguimiento_router
from app.controllers.RutaController import router as ruta_router
from app.config.database import get_db
from app.controllers.AppMensajeroController import router as app_mensajero_router
from app.controllers.FinanzasController import router as finanzas_router
import app.controllers.UsuarioController as UsuarioController

# Importar servicios
from app.services.email_service import enviar_email_recuperacion
from app.utils.security import crear_token_recuperacion, validar_token_recuperacion

app = FastAPI(
    title="EnvíExpress API",
    description="Sistema de gestión de envíos y logística profesional",
    version="1.0.0"
)

# --- Middlewares ---
app.add_middleware(
    SessionMiddleware,
    secret_key="tu_secret_key",
    max_age=3600,      # 1 hora
    same_site="lax",
    https_only=False
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Base de Datos ---
Base.metadata.create_all(bind=engine)

# --- Montar Archivos Estáticos ---
# Movido fuera del startup para evitar errores de acceso
if not os.path.exists("app/static"):
    os.makedirs("app/static")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

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
app.include_router(finanzas_router)


# --- Eventos de Ciclo de Vida ---
@app.on_event("startup")
def startup_event():
    db = SessionLocal()
    try:
        init_database(db)
    finally:
        db.close()

# --- RUTA DE RECUPERACIÓN ---
@app.post("/recuperar")
async def solicitar_recuperacion(email: str, db: Session = Depends(get_db)):
    # 1. Verificar si el usuario existe
    usuario = db.query(Usuario).filter(Usuario.correo == email).first()
    
    if not usuario:
        # Por seguridad, no confirmamos si el correo existe
        return {"message": "Si el correo es válido, recibirás un enlace"}

    try:
        # 2. Generar un token real usando tu utilidad
        token = crear_token_recuperacion(usuario.correo)
        
        # 3. Enviar el email
        resultado = enviar_email_recuperacion(email, token)
        
        if resultado:
            return {"message": "Enlace enviado correctamente a su bandeja de entrada"}
        else:
            raise HTTPException(status_code=500, detail="Error al conectar con el servidor de correos")
            
    except Exception as e:
        # Esto te dirá el error real en Swagger (ej. si las 16 letras están mal)
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")
    
@app.get("/reset-password")
async def vista_reset_password(request: Request, token: str):
    return templates.TemplateResponse("reset_password.html", {"request": request, "token": token})

@app.post("/reset-password")
async def reset_password(token: str, nueva_clave: str, db: Session = Depends(get_db)):
    email = validar_token_recuperacion(token)
    if not email:
        raise HTTPException(status_code=400, detail="El enlace ha expirado o es inválido")
    
    usuario = db.query(Usuario).filter(Usuario.correo == email).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    usuario.password = hash_password(nueva_clave)  # ← hasheada ✅
    db.commit()
    
    return {"message": "Contraseña actualizada con éxito. Ya puedes iniciar sesión."}

@app.get("/recuperar")
async def vista_recuperar(request: Request):
    return templates.TemplateResponse("recuperar.html", {"request": request})

# --- Ejecución ---
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
    
    #uvicorn main:app --reload --port 8080