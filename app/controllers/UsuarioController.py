from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel

from app.config.database import get_db
from app.models.Usuario import Usuario
from app.models.Transaccion import Transaccion
from app.models.Tarifa import Tarifa 
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
def login(request: Request, db: Session = Depends(get_db), error: str = None, logout: str = None, denied: str = None):
    user_id = request.session.get("user_id")
    if user_id:
        # ✅ Verificar que el usuario realmente existe en BD y está activo
        user = db.query(Usuario).filter(Usuario.id_usuario == user_id).first()
        if user and user.activo:
            if user.rol == "ADMIN":
                return RedirectResponse(url="/envios/", status_code=302)
            return RedirectResponse(url="/home_cliente", status_code=302)
        # ✅ Si no existe o está inactivo, limpiar sesión basura
        request.session.clear()

    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": error,
        "logout": logout,
        "denied": denied
    })

@router.post("/login")
async def do_login(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    username = form.get("username", "").strip()
    password = form.get("password", "").strip()

    # ✅ Validar campos vacíos ANTES de tocar la BD
    if not username or not password:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": True
        })

    user = authenticate_user(db, username, password)

    if not user:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": True
        })

    request.session.clear()
    request.session["user_id"] = user.id_usuario
    request.session["username"] = user.user_name
    request.session["rol"] = user.rol

    if user.rol == "ADMIN":
        return RedirectResponse(url="/home/", status_code=303)

    return RedirectResponse(url="/home_cliente", status_code=303)

# --- GESTIÓN DE SESIÓN Y REGISTRO ---

# ✅ GET y POST: destruye sesión, elimina cookie, redirige a /login
@router.get("/logout")
@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    response = RedirectResponse(url="/login?logout=true", status_code=303)
    response.delete_cookie("session")
    return response

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
        direccion=form.get("direccion", "").strip() or None,
        ciudad=form.get("ciudad_raw", "").strip() or None,
        localidad=form.get("localidad", "").strip() or None,
        rol="CLIENTE",
        activo=True,
        fecha_creacion=datetime.now()
    )
    usuario_repo.save(db, usuario)
    return RedirectResponse(url="/login?registro=exitoso", status_code=302)

# --- ADMINISTRACIÓN DE USUARIOS ---

@router.get("/usuarios")
def listar(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_admin(current_user)
    usuarios = db.query(Usuario).options(joinedload(Usuario.tarifa)).all()
    
    response = templates.TemplateResponse("usuarios.html", {
        "request": request,
        "usuarios": usuarios
    })
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@router.get("/usuarios/nuevo")
def nuevo(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_admin(current_user)
    tarifas = db.query(Tarifa).all()
    return templates.TemplateResponse("form.html", {
        "request": request,
        "usuario": None,
        "tarifas": tarifas,
        "rol": current_user.rol
    })

@router.get("/usuarios/editar/{id}")
def editar(id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_admin(current_user)
    usuario = usuario_repo.find_by_id(db, id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    tarifas = db.query(Tarifa).all()
    return templates.TemplateResponse("form.html", {
        "request": request, 
        "usuario": usuario, 
        "tarifas": tarifas,
        "rol": current_user.rol
    })

@router.post("/usuarios/guardar")
async def guardar(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_admin(current_user)
    form = await request.form()
    id_usuario = form.get("id_usuario")

    if id_usuario and id_usuario.strip():
        usuario = usuario_repo.find_by_id(db, int(id_usuario))
        if not usuario:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
    else:
        usuario = Usuario()
        usuario.fecha_creacion = datetime.now()

    usuario.user_name = form.get("user_name")
    if form.get("password") and form.get("password").strip():
        usuario.password = hash_password(form.get("password"))
    
    usuario.nombre   = form.get("nombre", "")
    usuario.apellido = form.get("apellido", "")
    usuario.correo   = form.get("correo", "")
    usuario.telefono = form.get("telefono")
    usuario.rol      = form.get("rol", "CLIENTE")
    usuario.activo   = form.get("activo", "true") == "true"

    usuario.direccion = form.get("direccion", "").strip() or None
    usuario.ciudad    = form.get("ciudad_raw", "").strip() or None
    usuario.localidad = form.get("localidad", "").strip() or None

    tarifa_id = form.get("tarifa_id")
    if tarifa_id and tarifa_id.strip():
        usuario.tarifa_id = int(tarifa_id)
    else:
        usuario.tarifa_id = None

    db.add(usuario)
    db.commit() 
    return RedirectResponse(url="/usuarios", status_code=302)

@router.get("/usuarios/eliminar/{id}")
def eliminar(id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_admin(current_user)
    usuario = usuario_repo.find_by_id(db, id)
    if usuario:
        db.delete(usuario)
        db.commit()
    return RedirectResponse(url="/usuarios", status_code=303)

# --- GESTIÓN DE SALDO ---

@router.get("/usuarios/recargar/{id}")
def vista_recargar_saldo(id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_admin(current_user)
    usuario = db.query(Usuario).filter(Usuario.id_usuario == id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    return templates.TemplateResponse("recargar_saldo.html", {
        "request": request,
        "usuario": usuario
    })

@router.post("/usuarios/procesar-recarga")
async def procesar_recarga(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_admin(current_user)
    form = await request.form()
    usuario_id    = int(form.get("usuario_id"))
    monto_recarga = Decimal(form.get("monto"))
    concepto      = form.get("concepto", "Recarga manual por Administrador")

    usuario = db.query(Usuario).filter(Usuario.id_usuario == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    usuario.saldo_plan += monto_recarga
    tipo = 'DESCUENTO' if monto_recarga < 0 else 'CARGA'

    nueva_trans = Transaccion(
        usuario_id=usuario.id_usuario,
        tipo_movimiento=tipo,
        monto=monto_recarga,
        concepto=concepto,
        fecha_creacion=datetime.now()
    )
    db.add(nueva_trans)
    db.commit()
    return RedirectResponse(url="/usuarios", status_code=303)

# --- PERFIL ---

@router.get("/perfil")
def perfil(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    usuario = usuario_repo.find_by_user_name(db, current_user.user_name)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    response = templates.TemplateResponse("perfil.html", {
        "request": request,
        "usuario": usuario
    })
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@router.post("/perfil/guardar")
async def guardar_perfil(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    form = await request.form()
    actual = usuario_repo.find_by_user_name(db, current_user.user_name)
    if not actual:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if form.get("user_name"): actual.user_name = form.get("user_name")
    if form.get("password"):  actual.password  = hash_password(form.get("password"))
    if form.get("nombre"):    actual.nombre    = form.get("nombre")
    if form.get("apellido"):  actual.apellido  = form.get("apellido")
    if form.get("correo"):    actual.correo    = form.get("correo")

    usuario_repo.save(db, actual)
    return RedirectResponse(url="/home_cliente?actualizado=true", status_code=302)

# --- REPORTES ---

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
    if activo == "true":  activo_bool = True
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
    usuarios = db.query(Usuario).options(joinedload(Usuario.tarifa)).all()
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
    if activo == "true":  activo_bool = True
    elif activo == "false": activo_bool = False

    usuarios = _filtrar_usuarios(db, nombre, rol, activo_bool)
    return generar_pdf("reporte-usuarios", {
        "usuarios": usuarios,
        "fecha": date.today().strftime("%d/%m/%Y"),
        "total": len(usuarios)
    }, "reporte-usuarios")