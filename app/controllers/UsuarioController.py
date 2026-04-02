from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel

from app.config.database import get_db
from app.models.Usuario import Usuario
# Se agrega create_access_token para generar el JWT real
from app.security.SecurityConfig import (
    get_current_user, 
    require_admin, 
    hash_password, 
    authenticate_user, 
    create_access_token 
)
import app.repositories.UsuarioRepository as usuario_repo
from app.config.templates import templates

router = APIRouter(tags=["Usuarios"])

# --- MODELO PARA RECIBIR DATOS DE LA APP FLUTTER ---
class LoginRequest(BaseModel):
    username: str
    password: str

# --- RUTAS DE LOGIN (WEB Y API) ---

@router.get("/login")
def login(request: Request, error: str = None, logout: str = None, denied: str = None):
    """Muestra la vista HTML de login para el navegador"""
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": error,
        "logout": logout,
        "denied": denied
    })

@router.post("/login")
async def do_login(request: Request, db: Session = Depends(get_db)):
    """Procesa el login para la plataforma Web (Formulario HTML)"""
    form = await request.form()
    username = form.get("username")
    password = form.get("password")

    user = authenticate_user(db, username, password)

    if not user:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": True
        })

    request.session["username"] = user.user_name

    # Redirección según rol para la versión Web
    if user.rol in ["ADMIN", "MENSAJERO"]:
        return RedirectResponse(url="/home", status_code=302)
    return RedirectResponse(url="/home_cliente", status_code=302)

@router.post("/api/login")
def api_login(data: LoginRequest, db: Session = Depends(get_db)):
    """
    Ruta para la aplicación Flutter. 
    Genera un JWT real para que el 'get_current_user' funcione en otras rutas.
    """
    user = authenticate_user(db, data.username, data.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Credenciales incorrectas"
        )
    
    # GENERACIÓN DEL TOKEN REAL
    # Esto permite que 'get_current_user' valide al mensajero en la App
    access_token = create_access_token(data={"sub": user.user_name})
    
    return JSONResponse({
        "status": "success",
        "token": access_token, 
        "user": {
            "id": user.id_usuario,
            "nombre": f"{user.nombre} {user.apellido}",
            "username": user.user_name,
            "correo": user.correo,
            "telefono": str(user.telefono) if user.telefono else "",
            "rol": user.rol 
        }
    })

# --- GESTIÓN DE SESIÓN Y REGISTRO ---

@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login?logout=true", status_code=302)

@router.get("/registro")
def registro(request: Request):
    return templates.TemplateResponse("registro.html", {"request": request})

@router.post("/registro/guardar")
async def guardar_registro(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    usuario = Usuario(
        user_name=form.get("user_name"),
        password=hash_password(form.get("password")),
        nombre=form.get("nombre"),
        apellido=form.get("apellido"),
        correo=form.get("correo"),
        telefono=form.get("telefono"),
        rol="CLIENTE",
        activo=True,
        fecha_creacion=datetime.now()
    )
    usuario_repo.save(db, usuario)
    return RedirectResponse(url="/login?registro=exitoso", status_code=302)

# --- ADMINISTRACIÓN DE USUARIOS (WEB) ---

@router.get("/usuarios")
def listar(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_admin(current_user)
    return templates.TemplateResponse("usuarios.html", {
        "request": request,
        "usuarios": usuario_repo.find_all(db)
    })

@router.get("/usuarios/nuevo")
def nuevo(request: Request, current_user=Depends(get_current_user)):
    require_admin(current_user)
    return templates.TemplateResponse("form.html", {
        "request": request,
        "usuario": None,
        "rol": current_user.rol
    })

@router.post("/usuarios/guardar")
async def guardar(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_admin(current_user)
    form = await request.form()
    id_usuario = form.get("id_usuario")

    if id_usuario:
        usuario = usuario_repo.find_by_id(db, int(id_usuario))
        if not usuario:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
    else:
        usuario = Usuario()
        usuario.fecha_creacion = datetime.now()

    usuario.user_name = form.get("user_name")
    if form.get("password"):
        usuario.password = hash_password(form.get("password"))
    usuario.nombre = form.get("nombre", "")
    usuario.apellido = form.get("apellido", "")
    usuario.correo = form.get("correo", "")
    usuario.telefono = form.get("telefono")
    usuario.rol = form.get("rol", "USER")
    usuario.activo = form.get("activo", "true") == "true"

    usuario_repo.save(db, usuario)
    return RedirectResponse(url="/usuarios", status_code=302)

# --- PERFIL Y REPORTES ---

@router.get("/perfil")
def perfil(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    usuario = usuario_repo.find_by_user_name(db, current_user.user_name)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return templates.TemplateResponse("perfil.html", {
        "request": request,
        "usuario": usuario
    })

@router.post("/perfil/guardar")
async def guardar_perfil(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    form = await request.form()
    actual = usuario_repo.find_by_user_name(db, current_user.user_name)
    if not actual:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if form.get("user_name"): actual.user_name = form.get("user_name")
    if form.get("password"): actual.password = hash_password(form.get("password"))
    if form.get("nombre"): actual.nombre = form.get("nombre")
    if form.get("apellido"): actual.apellido = form.get("apellido")
    if form.get("correo"): actual.correo = form.get("correo")

    usuario_repo.save(db, actual)
    return RedirectResponse(url="/home_cliente?actualizado=true", status_code=302)

@router.get("/usuarios/reporte")
def vista_reporte(
    request: Request,
    nombre: Optional[str] = Query(None),
    rol: Optional[str] = Query(None),
    activo: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    require_admin(current_user)
    activo_bool = None
    if activo == "true": activo_bool = True
    elif activo == "false": activo_bool = False

    usuarios = _filtrar_usuarios(db, nombre, rol, activo_bool)
    return templates.TemplateResponse("vista-reporte-usuarios.html", {
        "request": request,
        "usuarios": usuarios,
        "nombre": nombre,
        "rol": rol,
        "activo": activo
    })

def _filtrar_usuarios(db, nombre, rol, activo) -> list:
    usuarios = usuario_repo.find_all(db)
    if nombre:
        nombre_l = nombre.lower()
        usuarios = [u for u in usuarios if 
                    nombre_l in u.nombre.lower() or
                    nombre_l in u.apellido.lower() or
                    nombre_l in u.user_name.lower()]
    if rol:
        usuarios = [u for u in usuarios if u.rol == rol]
    if activo is not None:
        usuarios = [u for u in usuarios if u.activo == activo]
    return usuarios

@router.get("/usuarios/reporte/pdf")
def generar_reporte_pdf(
    nombre: Optional[str] = Query(None),
    rol: Optional[str] = Query(None),
    activo: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    require_admin(current_user)
    from app.utils.pdf_generator import generar_pdf

    activo_bool = None
    if activo == "true": activo_bool = True
    elif activo == "false": activo_bool = False

    usuarios = _filtrar_usuarios(db, nombre, rol, activo_bool)
    return generar_pdf("reporte-usuarios", {
        "usuarios": usuarios,
        "fecha": date.today().strftime("%d/%m/%Y"),
        "total": len(usuarios)
    }, "reporte-usuarios")