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
    require_financiero,
    require_operativo,
    require_ceo,
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


# ─────────────────────────────────────────────
# HELPER: URL de home según rol
# ─────────────────────────────────────────────

def _home_por_rol(rol: str) -> str:
    if rol == "CLIENTE":
        return "/home_cliente"
    return "/home"  # CEO, FACTURACION, ADMINISTRATIVO, MENSAJERO → HomeController decide el template


# ─────────────────────────────────────────────
# LOGIN (WEB Y API)
# ─────────────────────────────────────────────

@router.get("/login")
def login(
    request: Request,
    db: Session = Depends(get_db),
    error: str = None,
    logout: str = None,
    denied: str = None
):
    user_id = request.session.get("user_id")
    if user_id:
        user = db.query(Usuario).filter(Usuario.id_usuario == user_id).first()
        if user and user.activo:
            return RedirectResponse(url=_home_por_rol(user.rol), status_code=302)
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

    if not user.activo:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": True,
            "denied": "inactivo"
        })

    request.session.clear()
    request.session["user_id"] = user.id_usuario
    request.session["username"] = user.user_name
    request.session["rol"] = user.rol

    return RedirectResponse(url=_home_por_rol(user.rol), status_code=303)


# --- ENDPOINT API PARA FLUTTER (JSON) ---

@router.post("/api/login")
async def api_login(data: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, data.username, data.password)
    if not user:
        raise HTTPException(status_code=404, detail="Credenciales incorrectas")
    if not user.activo:
        raise HTTPException(status_code=403, detail="Usuario inactivo")

    token = create_access_token({"sub": user.user_name, "rol": user.rol})
    return JSONResponse({
        "token": token,
        "rol": user.rol,
        "username": user.user_name,
        "id_usuario": user.id_usuario,
        "nombre": user.nombre,
        "apellido": user.apellido
    })


# ─────────────────────────────────────────────
# SESIÓN Y REGISTRO
# ─────────────────────────────────────────────

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


# ─────────────────────────────────────────────
# ADMINISTRACIÓN DE USUARIOS
# Acceso: CEO, FACTURACION, ADMINISTRATIVO
# ─────────────────────────────────────────────

@router.get("/usuarios")
def listar(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_operativo(current_user)
    usuarios = db.query(Usuario).options(joinedload(Usuario.tarifa)).all()

    response = templates.TemplateResponse("usuarios.html", {
        "request": request,
        "usuarios": usuarios,
        "puede_ver_finanzas": current_user.rol in {"CEO", "FACTURACION"},
        "es_ceo": current_user.rol == "CEO",
        "rol": current_user.rol
    })
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@router.get("/usuarios/nuevo")
def nuevo(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_operativo(current_user)
    tarifas = db.query(Tarifa).all()
    return templates.TemplateResponse("form.html", {
        "request": request,
        "usuario": None,
        "tarifas": tarifas,
        "rol": current_user.rol,
        "es_ceo": current_user.rol == "CEO",
    })


@router.get("/usuarios/editar/{id}")
def editar(id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_operativo(current_user)
    usuario = usuario_repo.find_by_id(db, id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    tarifas = db.query(Tarifa).all()
    return templates.TemplateResponse("form.html", {
        "request": request,
        "usuario": usuario,
        "tarifas": tarifas,
        "rol": current_user.rol,
        "es_ceo": current_user.rol == "CEO",
    })


@router.post("/usuarios/guardar")
async def guardar(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_operativo(current_user)
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

    usuario.nombre    = form.get("nombre", "")
    usuario.apellido  = form.get("apellido", "")
    usuario.correo    = form.get("correo", "")
    usuario.telefono  = form.get("telefono")
    usuario.activo    = form.get("activo", "true") == "true"
    usuario.direccion = form.get("direccion", "").strip() or None
    usuario.ciudad    = form.get("ciudad_raw", "").strip() or None
    usuario.localidad = form.get("localidad", "").strip() or None

    # ── INVENTARIO: solo aplica a clientes ──────────────────────
    usuario.maneja_inventario = form.get("maneja_inventario") == "true"

    tarifa_id = form.get("tarifa_id")
    usuario.tarifa_id = int(tarifa_id) if tarifa_id and tarifa_id.strip() else None

    # Rol: solo CEO y FACTURACION pueden asignarlo
    rol_form = form.get("rol", "CLIENTE")
    if current_user.rol in {"CEO", "FACTURACION"}:
        usuario.rol = rol_form
    else:
        # ADMINISTRATIVO: conserva el rol existente en edición,
        # asigna CLIENTE si es usuario nuevo
        if not (id_usuario and id_usuario.strip()):
            usuario.rol = "CLIENTE"

    db.add(usuario)
    db.commit()
    return RedirectResponse(url="/usuarios", status_code=302)


@router.get("/usuarios/eliminar/{id}")
def eliminar(id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    # Solo CEO puede eliminar usuarios
    require_ceo(current_user)
    usuario = usuario_repo.find_by_id(db, id)
    if usuario:
        db.delete(usuario)
        db.commit()
    return RedirectResponse(url="/usuarios", status_code=303)


# ─────────────────────────────────────────────
# GESTIÓN DE SALDO — Solo CEO y FACTURACION
# ─────────────────────────────────────────────

@router.get("/usuarios/recargar/{id}")
def vista_recargar_saldo(id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_financiero(current_user)
    usuario = db.query(Usuario).filter(Usuario.id_usuario == id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return templates.TemplateResponse("recargar_saldo.html", {
        "request": request,
        "usuario": usuario
    })


@router.post("/usuarios/procesar-recarga")
async def procesar_recarga(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_financiero(current_user)
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


# ─────────────────────────────────────────────
# PERFIL — Cualquier usuario autenticado
# ─────────────────────────────────────────────

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

    actual.telefono  = form.get("telefono",   "").strip() or None
    actual.direccion = form.get("direccion",  "").strip() or None
    actual.ciudad    = form.get("ciudad_raw", "").strip() or None
    actual.localidad = form.get("localidad",  "").strip() or None

    # Actualizar sesión si cambió el username
    request.session["username"] = actual.user_name

    usuario_repo.save(db, actual)
    return RedirectResponse(url=f"/perfil?actualizado=1", status_code=302)


# ─────────────────────────────────────────────
# REPORTES OPERATIVOS — CEO, FACTURACION, ADMINISTRATIVO
# ─────────────────────────────────────────────

@router.get("/usuarios/reporte")
def vista_reporte(
    request: Request,
    nombre: Optional[str] = Query(None),
    rol: Optional[str] = Query(None),
    activo: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    require_operativo(current_user)
    activo_bool = None
    if activo == "true":   activo_bool = True
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
    require_operativo(current_user)
    from app.utils.pdf_generator import generar_pdf
    activo_bool = None
    if activo == "true":   activo_bool = True
    elif activo == "false": activo_bool = False

    usuarios = _filtrar_usuarios(db, nombre, rol, activo_bool)
    return generar_pdf("reporte-usuarios", {
        "usuarios": usuarios,
        "fecha": date.today().strftime("%d/%m/%Y"),
        "total": len(usuarios)
    }, "reporte-usuarios")


# ─────────────────────────────────────────────
# REPORTE FINANCIERO DEL CLIENTE — Solo su propia cuenta
# ─────────────────────────────────────────────

@router.get("/mi-cuenta/reporte")
def reporte_financiero_cliente(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    # CLIENTE: ve solo sus propias transacciones
    if current_user.rol == "CLIENTE":
        transacciones = db.query(Transaccion).filter(
            Transaccion.usuario_id == current_user.id_usuario
        ).order_by(Transaccion.fecha_creacion.desc()).all()

        return templates.TemplateResponse("reporte_financiero_cliente.html", {
            "request": request,
            "usuario": current_user,
            "transacciones": transacciones
        })

    # CEO y FACTURACION van al módulo financiero completo
    if current_user.rol in {"CEO", "FACTURACION"}:
        return RedirectResponse(url="/finanzas/transacciones")

    # ADMINISTRATIVO y MENSAJERO: acceso denegado
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Acceso denegado."
    )