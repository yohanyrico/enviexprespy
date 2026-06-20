# app/controllers/EnvioController.py
import os
import shutil
import io
import time
import json

from app.config.database import get_db  # ✅ el que ya tenías antes
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse, StreamingResponse, JSONResponse
from sqlalchemy.orm import Session, joinedload, subqueryload
from sqlalchemy import text
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

import pandas as pd
from fpdf import FPDF
from geopy.geocoders import Nominatim

from app.config.database import get_db
from app.models.Envio import Envio
from app.models.Lugar import Lugar
from app.models.Usuario import Usuario
from app.models.Transaccion import Transaccion
from app.models.Tarifa import Tarifa
from app.models.Vehiculo import Vehiculo
from app.models.Ruta import Ruta
from app.models.EnvioItemInventario import EnvioItemInventario
from app.models.inventario import InventarioProducto as Inventario
from app.models.Seguimiento import Seguimiento

from app.security.SecurityConfig import get_current_user, require_admin, require_admin_or_mensajero
import app.repositories.EnvioRepository as envio_repo
import app.repositories.UsuarioRepository as usuario_repo
import app.repositories.VehiculoRepository as vehiculo_repo
import app.repositories.TarifaRepository as tarifa_repo
import app.repositories.RutaRepository as ruta_repo
import app.repositories.LugarRepository as lugar_repo
import app.repositories.SeguimientoRepository as seg_repo
from app.config.templates import templates

router = APIRouter(prefix="/envios", tags=["Envíos"])


# --- CLASE PDF ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 16)
        self.set_text_color(0, 58, 140)
        self.cell(0, 10, 'ENVIEXPRESS S.A.S', 0, 1, 'C')
        self.set_font('Arial', 'B', 12)
        self.set_text_color(100)
        self.cell(0, 10, 'REPORTE OPERATIVO DE LOGÍSTICA', 0, 1, 'C')
        self.set_font('Arial', 'I', 9)
        self.cell(0, 10, f'Generado el: {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}', 0, 1, 'R')
        self.ln(5)
        self.set_draw_color(255, 140, 0)
        self.set_line_width(1)
        self.line(10, self.get_y(), 287, self.get_y())
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(128)
        self.cell(0, 10, f'ENVIEXPRESS S.A.S - Página {self.page_no()}', 0, 0, 'C')


# --- CONSECUTIVO ---
def generar_nuevo_consecutivo(db: Session):
    try:
        res = db.execute(text("SELECT ultimo_consecutivo FROM configuracion WHERE id = 1 FOR UPDATE")).fetchone()
        if not res:
            nuevo_numero = 1
            db.execute(text("INSERT INTO configuracion (id, ultimo_consecutivo) VALUES (1, 1)"))
        else:
            nuevo_numero = res[0] + 1
            db.execute(text("UPDATE configuracion SET ultimo_consecutivo = :num WHERE id = 1"), {"num": nuevo_numero})
        db.commit()
        return f"ENV{nuevo_numero:05d}"
    except Exception as e:
        db.rollback()
        print(f"Error crítico en consecutivo: {e}")
        return f"ENV{datetime.now().strftime('%H%M%S')}"


# --- GEOCODIFICACIÓN ---
def obtener_coordenadas(direccion, ciudad):
    try:
        geolocator = Nominatim(user_agent="enviexpress_manager_v3")
        location = geolocator.geocode(f"{direccion}, {ciudad}, Colombia", timeout=12)
        if location:
            return location.latitude, location.longitude
    except Exception as e:
        print(f"Error en Geocodificación: {e}")
    return None, None


# --- HELPERS ---
def _cargar_datos_formulario(db: Session):
    return {
        "clientes": db.query(Usuario).filter(Usuario.rol == "CLIENTE").all(),
        "tarifas":  db.query(Tarifa).all(),
        "estados":  ["Registrado", "En_Bodega", "En_Ruta", "Entregado", "Cancelado"]
    }


def _build_clientes_tarifas(clientes: list) -> dict:
    return {c.id_usuario: c.tarifa.nombre for c in clientes if c.tarifa and c.tarifa.nombre}


def _extraer_ciudad_depto(lugar) -> tuple:
    if not lugar or not lugar.ciudad:
        return "", ""
    raw = lugar.ciudad
    if " (" in raw:
        partes = raw.split(" (", 1)
        return partes[0].strip(), partes[1].rstrip(")").strip()
    return raw.strip(), raw.strip()


def _extraer_localidad_telefono(lugar) -> tuple:
    if not lugar or not lugar.referencia:
        return "", ""
    localidad = telefono = ""
    for parte in lugar.referencia.split("|"):
        p = parte.strip()
        if p.upper().startswith("LOCALIDAD:"):
            localidad = p.split(":", 1)[1].strip()
        elif p.upper().startswith("TEL:"):
            telefono = p.split(":", 1)[1].strip()
    return localidad, telefono


def _extraer_descripcion_obs(envio) -> tuple:
    if not envio or not envio.instrucciones:
        return "", ""
    descripcion = observaciones = ""
    for parte in envio.instrucciones.split("|"):
        p = parte.strip()
        if p.upper().startswith("CONTENIDO:"):
            descripcion = p.split(":", 1)[1].strip()
        elif p.upper().startswith("OBS:"):
            observaciones = p.split(":", 1)[1].strip()
    return descripcion, observaciones


def _campos_edicion_vacios() -> dict:
    return {
        "edit_depto_rec": "", "edit_ciudad_rec": "", "edit_tel_rec": "",
        "edit_loc_rec": "", "edit_dir_rec": "", "edit_depto_ent": "",
        "edit_ciudad_ent": "", "edit_tel_ent": "", "edit_loc_ent": "",
        "edit_descripcion": "", "edit_obs": "", "edit_nombre_dest": "",
    }


def _guardar_items_inventario(db, envio_id, cliente, productos_seleccionados, revertir_previos=False):
    """Guarda los items de inventario vinculados al envío y descuenta stock."""
    if not productos_seleccionados or not getattr(cliente, 'maneja_inventario', False):
        return

    if revertir_previos:
        items_viejos = db.query(EnvioItemInventario).filter(
            EnvioItemInventario.envio_id == envio_id
        ).all()
        for iv in items_viejos:
            prod = db.query(Inventario).filter(Inventario.id == iv.producto_id).first()
            if prod:
                prod.stock_disponible += iv.cantidad
                if hasattr(prod, 'stock_comprometido') and prod.stock_comprometido >= iv.cantidad:
                    prod.stock_comprometido -= iv.cantidad
        db.query(EnvioItemInventario).filter(
            EnvioItemInventario.envio_id == envio_id
        ).delete(synchronize_session=False)

    for item in productos_seleccionados:
        pid = item.get("producto_id") or item.get("id")
        qty = int(item.get("cantidad", 1))
        if not pid or qty < 1:
            continue
        prod = db.query(Inventario).filter(Inventario.id == int(pid)).first()
        if prod:
            if prod.stock_disponible < qty:
                raise Exception(f"Stock insuficiente para '{prod.nombre}'")
            prod.stock_disponible -= qty
            if hasattr(prod, 'stock_comprometido'):
                prod.stock_comprometido += qty
        db.add(EnvioItemInventario(envio_id=envio_id, producto_id=int(pid), cantidad=qty))


# ─────────────────────────────────────────────────────────────────────────────
# LISTADOS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/")
def listar(request: Request, cliente_id: Optional[int] = None, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=302)

    query = db.query(Envio).options(
        joinedload(Envio.cliente), joinedload(Envio.mensajero),
        joinedload(Envio.tarifa), joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega)
    )

    if cliente_id:
        query = query.filter(Envio.usuario_cliente_id == cliente_id)

    envios = query.order_by(Envio.fecha_creacion.desc()).all()

    mensajeros           = db.query(Usuario).filter(Usuario.rol == "MENSAJERO").all()
    clientes_registrados = db.query(Usuario).filter(Usuario.rol.ilike("%CLIENTE%")).all()

    response = templates.TemplateResponse("envios.html", {
        "request": request, "envios": envios,
        "mensajeros": mensajeros, "clientes": clientes_registrados,
        "rol": request.session.get("rol", "ADMIN"),
        "cliente_id_filtro": cliente_id
    })
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@router.get("/mis-guias")
def listar_mis_guias(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login?error=expired")

    usuario = db.query(Usuario).options(joinedload(Usuario.tarifa)).filter(
        Usuario.id_usuario == user_id).first()
    if not usuario:
        return RedirectResponse(url="/login")

    mis_envios = db.query(Envio).filter(
        Envio.usuario_cliente_id == usuario.id_usuario
    ).options(
        joinedload(Envio.lugar_recogida), joinedload(Envio.lugar_entrega), joinedload(Envio.tarifa)
    ).order_by(Envio.fecha_creacion.desc()).all()

    historial_pagos = db.query(Transaccion).filter(
        Transaccion.usuario_id == usuario.id_usuario
    ).order_by(Transaccion.fecha_creacion.desc()).limit(15).all()

    response = templates.TemplateResponse("envios_cliente.html", {
        "request": request, "envios": mis_envios,
        "transacciones": historial_pagos, "username": usuario.user_name,
        "current_user": usuario, "tarifas": db.query(Tarifa).all()
    })
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


# ─────────────────────────────────────────────────────────────────────────────
# DETALLE
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/detalle/{id}")
def ver_detalle_envio(id: int, request: Request, db: Session = Depends(get_db)):
    envio = db.query(Envio).options(
        joinedload(Envio.cliente), joinedload(Envio.mensajero),
        joinedload(Envio.tarifa), joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega), joinedload(Envio.vehiculo)
    ).filter(Envio.envio_id == id).first()

    if not envio:
        raise HTTPException(status_code=404, detail="El envío solicitado no existe o fue eliminado")

    return templates.TemplateResponse("detalle-envio.html", {
        "request": request, "envio": envio,
        "rol": request.session.get("rol", "CLIENTE")
    })


# ─────────────────────────────────────────────────────────────────────────────
# NUEVO ENVÍO
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/nuevo")
def nuevo(request: Request, db: Session = Depends(get_db)):
    try:
        username_session = request.session.get("username")
        usuario_actual = db.query(Usuario).options(
            joinedload(Usuario.tarifa)
        ).filter(Usuario.user_name == username_session).first()

        if not usuario_actual:
            return RedirectResponse(url="/login")

        datos = _cargar_datos_formulario(db)
        mensajeros_db = db.query(Usuario).filter(Usuario.rol == "MENSAJERO").all()
        clientes_con_tarifa = db.query(Usuario).options(
            joinedload(Usuario.tarifa)
        ).filter(Usuario.rol == "CLIENTE").all()

        datos['clientes'] = clientes_con_tarifa
        clientes_tarifas  = _build_clientes_tarifas(clientes_con_tarifa)
        campos = _campos_edicion_vacios()

        if usuario_actual.rol not in ('CEO', 'FACTURACION', 'ADMINISTRATIVO'):
            datos['clientes'] = [usuario_actual]
            campos["edit_tel_rec"] = getattr(usuario_actual, 'telefono', '') or ""
            campos["edit_loc_rec"] = getattr(usuario_actual, 'localidad', '') or ""
            campos["edit_dir_rec"] = getattr(usuario_actual, 'direccion', '') or ""
            ciudad_usr = getattr(usuario_actual, 'ciudad', '') or ""
            if " (" in ciudad_usr:
                partes = ciudad_usr.split(" (", 1)
                campos["edit_ciudad_rec"] = partes[0].strip()
                campos["edit_depto_rec"]  = partes[1].rstrip(")").strip()
            else:
                campos["edit_ciudad_rec"] = ciudad_usr.strip()
                campos["edit_depto_rec"]  = ciudad_usr.strip()
            clientes_tarifas = {}
            saldo = float(usuario_actual.saldo_plan)
        else:
            saldo = None

        return templates.TemplateResponse("form-envio.html", {
            "request": request,
            "envio": None,
            "rol": usuario_actual.rol,
            "current_user": usuario_actual,
            "clientes_tarifas": clientes_tarifas,
            "saldo_disponible": saldo,
            "mensajeros": mensajeros_db,
            **campos,
            **datos
        })
    except Exception as e:
        print(f"Error renderizando formulario: {e}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")


# ─────────────────────────────────────────────────────────────────────────────
# GUARDAR (CREAR + EDITAR)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/guardar")
async def guardar(request: Request, db: Session = Depends(get_db)):
    rol = request.session.get("rol", "CLIENTE")
    print(f"ROL EN SESIÓN: {rol}")
    destino_ok = "/envios" if rol in ("CEO", "FACTURACION", "ADMINISTRATIVO") else "/envios/mis-guias"

    try:
        form     = await request.form()
        envio_id = form.get("envio_id")
        es_nuevo = not (envio_id and envio_id.strip())

        if rol == "ADMIN":
            cliente_id = form.get("usuario_cliente_id")
            if not cliente_id:
                return RedirectResponse(url=f"{destino_ok}?error=cliente_requerido", status_code=303)
            cliente = db.query(Usuario).options(joinedload(Usuario.tarifa)).filter(
                Usuario.id_usuario == int(cliente_id)).first()
        else:
            cliente = db.query(Usuario).options(joinedload(Usuario.tarifa)).filter(
                Usuario.user_name == request.session.get("username")).first()

        if not cliente:
            return RedirectResponse(url="/login")

        es_cod         = form.get("es_cod") == "on"
        valor_a_cobrar = Decimal(form.get("valor_a_cobrar") or "0") if es_cod else Decimal("0")
        depto_entrega  = form.get("depto_entrega", "").upper()
        ciudad_entrega = form.get("ciudad_entrega", "").upper()
        es_bogota      = "BOGOTÁ" in depto_entrega or "BOGOTÁ" in ciudad_entrega

        contenido   = form.get("descripcion", "").strip()
        obs_cliente = form.get("instrucciones_especiales", "").strip()
        instrucciones_finales = f"CONTENIDO: {contenido} | OBS: {obs_cliente}"

        try:
            productos_seleccionados = json.loads(form.get("productos_inventario", "[]"))
        except Exception:
            productos_seleccionados = []

        if es_nuevo:
            if not es_bogota:
                tarifa_db  = db.query(Tarifa).filter(
                    Tarifa.nombre.ilike("%Nacional%") | Tarifa.nombre.ilike("%Raíces%")
                ).first()
                costo_base = tarifa_db.precio_plan if tarifa_db else Decimal("17990")
                tar_id     = tarifa_db.id if tarifa_db else None
            else:
                tarifa_db  = db.query(Tarifa).filter(Tarifa.id == cliente.tarifa_id).first()
                costo_base = tarifa_db.precio_plan if tarifa_db else cliente.cuota_fija
                tar_id     = tarifa_db.id if tarifa_db else None

            comision_cod = Decimal("0")
            if es_cod and valor_a_cobrar > 0:
                comision_cod = (valor_a_cobrar * Decimal("0.03")).quantize(
                    Decimal("1.00"), rounding=ROUND_HALF_UP)

            costo_total = costo_base + comision_cod

            if cliente.saldo_plan < costo_total and request.session.get("rol") not in ("CEO", "FACTURACION", "ADMINISTRATIVO"):
                return RedirectResponse(url=f"{destino_ok}?error=saldo_insuficiente", status_code=303)

            envio = Envio(
                numero_guia=generar_nuevo_consecutivo(db),
                usuario_cliente_id=cliente.id_usuario,
                fecha_creacion=datetime.now(),
                estado="Registrado",
                costo_envio=costo_total,
                tipo_servicio="EXPRESS" if es_bogota else "NACIONAL",
                instrucciones=instrucciones_finales,
                peso=Decimal(form.get("peso", "1.0")),
                tarifa_id=tar_id,
                es_cod=es_cod,
                valor_a_cobrar=valor_a_cobrar
            )
            if request.session.get("rol") not in ("CEO", "FACTURACION", "ADMINISTRATIVO"):
                cliente.saldo_plan -= costo_total
            db.add(envio)
            db.flush()

            db.add(Transaccion(
                usuario_id=cliente.id_usuario,
                envio_id=envio.envio_id,
                tipo_movimiento='DESCUENTO',
                monto=-costo_total,
                concepto=f"Pago {'Nacional' if not es_bogota else 'Urbano'} Guía {envio.numero_guia}",
                fecha_creacion=datetime.now()
            ))

            db.add(Seguimiento(
                envio_id=envio.envio_id,
                estado="Registrado",
                descripcion="Guía creada en el sistema",
                fecha=datetime.now()
            ))

            _guardar_items_inventario(db, envio.envio_id, cliente, productos_seleccionados, revertir_previos=False)

        else:
            envio = db.query(Envio).filter(Envio.envio_id == int(envio_id)).first()
            if not envio:
                return RedirectResponse(url=f"{destino_ok}?error=no_encontrado")

            envio.instrucciones  = instrucciones_finales
            envio.es_cod         = es_cod
            envio.valor_a_cobrar = valor_a_cobrar
            envio.peso           = Decimal(form.get("peso", "1.0"))

            if productos_seleccionados:
                _guardar_items_inventario(
                    db, envio.envio_id, cliente, productos_seleccionados, revertir_previos=True)

        for tipo in ["recogida", "entrega"]:
            ciudad    = form.get(f"ciudad_{tipo}", "")
            depto     = form.get(f"depto_{tipo}", "")
            direccion = form.get(f"direccion_{tipo}", "").strip()
            telefono  = form.get(f"telefono_{tipo}", "").strip()
            localidad = form.get(f"localidad_{tipo}", "").strip()
            lat_form  = form.get(f"lat_{tipo}", "").strip()
            lon_form  = form.get(f"lon_{tipo}", "").strip()

            if not direccion:
                continue

            if tipo == "entrega":
                nombre_dest = form.get("nombre_destinatario", "").strip()
                referencia_final = (
                    f"Nombre: {nombre_dest} | Localidad: {localidad} | Tel: {telefono}"
                    if localidad else f"Nombre: {nombre_dest} | Tel: {telefono}"
                )
            else:
                referencia_final = (
                    f"Localidad: {localidad} | Tel: {telefono}"
                    if localidad else f"Tel: {telefono}"
                )

            if lat_form and lon_form:
                try:
                    lat, lng = float(lat_form), float(lon_form)
                except ValueError:
                    lat, lng = obtener_coordenadas(direccion, ciudad)
            else:
                lat, lng = obtener_coordenadas(direccion, ciudad)

            lugar = Lugar(
                direccion=direccion,
                ciudad=f"{ciudad} ({depto})",
                referencia=referencia_final,
                latitud=lat, longitud=lng
            )
            db.add(lugar)
            db.flush()

            if tipo == "recogida":
                envio.lugar_recogida_id = lugar.lugar_id
            else:
                envio.lugar_entrega_id = lugar.lugar_id

        db.commit()
        return RedirectResponse(url=destino_ok, status_code=302)

    except Exception as e:
        db.rollback()
        print(f"Error Crítico en Guardar Envío: {e}")
        return RedirectResponse(url=f"{destino_ok}?error=db_error")


# ─────────────────────────────────────────────────────────────────────────────
# ELIMINAR ENVÍO  ✅ FIXED: limpia FKs antes de borrar
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/eliminar/{id}")
def eliminar(id: int, request: Request, db: Session = Depends(get_db)):
    rol        = request.session.get("rol", "CLIENTE")
    destino_ok = "/envios" if rol in ("CEO", "FACTURACION", "ADMINISTRATIVO") else "/envios/mis-guias"

    try:
        envio = db.query(Envio).filter(Envio.envio_id == id).first()
        if not envio:
            return RedirectResponse(url=destino_ok)

        # Devolver stock si aplica
        if envio.estado == "Registrado":
            for item in db.query(EnvioItemInventario).filter(
                    EnvioItemInventario.envio_id == envio.envio_id).all():
                prod = db.query(Inventario).filter(Inventario.id == item.producto_id).first()
                if prod:
                    prod.stock_disponible += item.cantidad
                    if hasattr(prod, 'stock_comprometido') and prod.stock_comprometido >= item.cantidad:
                        prod.stock_comprometido -= item.cantidad

        # Reembolso si aplica
        cliente = db.query(Usuario).filter(
            Usuario.id_usuario == envio.usuario_cliente_id).first()
        if cliente and envio.costo_envio > 0 and envio.estado == "Registrado":
            if rol not in ("CEO", "FACTURACION", "ADMINISTRATIVO"):
                cliente.saldo_plan += envio.costo_envio
            db.add(Transaccion(
                usuario_id=cliente.id_usuario,
                tipo_movimiento='REEMBOLSO',
                monto=envio.costo_envio,
                concepto=f"Reembolso por anulación de Guía {envio.numero_guia}",
                fecha_creacion=datetime.now()
            ))

        # ✅ 1. Eliminar seguimientos (FK hacia envio)
        db.query(Seguimiento).filter(
            Seguimiento.envio_id == id
        ).delete(synchronize_session=False)

        # ✅ 2. Eliminar items de inventario (FK hacia envio)
        db.query(EnvioItemInventario).filter(
            EnvioItemInventario.envio_id == id
        ).delete(synchronize_session=False)

        # ✅ 3. Desvincular ruta (FK hacia ruta desde envio)
        envio.ruta_id = None
        db.flush()

        # ✅ 4. Ahora sí eliminar el envío
        db.delete(envio)
        db.commit()
        return RedirectResponse(url=destino_ok, status_code=303)

    except Exception as e:
        db.rollback()
        print(f"Error en eliminación: {e}")
        return RedirectResponse(url=f"{destino_ok}?error=delete_fail")


# ─────────────────────────────────────────────────────────────────────────────
# ELIMINAR SEGUIMIENTO INDIVIDUAL  ✅ NUEVO
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/seguimiento/{seg_id}/eliminar")
def eliminar_seguimiento(seg_id: int, request: Request, db: Session = Depends(get_db)):
    rol = request.session.get("rol", "")
    if rol not in ("CEO", "FACTURACION", "ADMINISTRATIVO"):
        return JSONResponse(status_code=403, content={"ok": False, "msg": "Sin permiso"})
    try:
        seg = seg_repo.find_by_id(db, seg_id)
        if not seg:
            return JSONResponse(status_code=404, content={"ok": False, "msg": "Seguimiento no encontrado"})
        seg_repo.delete(db, seg)
        return JSONResponse({"ok": True})
    except Exception as e:
        db.rollback()
        print(f"Error eliminando seguimiento {seg_id}: {e}")
        return JSONResponse(status_code=500, content={"ok": False, "msg": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# IMPRIMIR
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/imprimir/{id}")
def imprimir_guia(id: int, request: Request, db: Session = Depends(get_db)):
    envio = db.query(Envio).options(
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega),
        joinedload(Envio.cliente),
        joinedload(Envio.items_inventario)
    ).filter(Envio.envio_id == id).first()

    if not envio:
        raise HTTPException(status_code=404, detail="La guía no pudo ser localizada")

    return templates.TemplateResponse("imprimir_guia.html", {
        "request": request, "envio": envio,
        "fecha_actual": datetime.now().strftime("%d/%m/%Y %H:%M")
    })


@router.get("/imprimir-masivo")
def imprimir_masivo(request: Request, ids: str, db: Session = Depends(get_db)):
    lista_ids = [int(i) for i in ids.split(",")]

    envios = db.query(Envio).options(
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega),
        joinedload(Envio.cliente),
        joinedload(Envio.items_inventario).joinedload(EnvioItemInventario.producto)
    ).filter(Envio.envio_id.in_(lista_ids)).all()

    for envio in envios:
        _ = [(item.producto.nombre, item.producto.sku, item.cantidad)
             for item in envio.items_inventario]

    return templates.TemplateResponse("imprimir_masivo.html", {
        "request": request, "envios": envios
    })


# ─────────────────────────────────────────────────────────────────────────────
# REPORTES
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/reporte")
def generar_reporte(formato: str = Query("csv"), ids: Optional[str] = None, db: Session = Depends(get_db)):
    try:
        query = db.query(Envio).options(joinedload(Envio.cliente), joinedload(Envio.lugar_entrega))
        if ids:
            lista_ids = [int(i) for i in ids.split(",") if i.strip()]
            query = query.filter(Envio.envio_id.in_(lista_ids))

        envios = query.all()
        data = []
        for e in envios:
            ref = (e.lugar_entrega.referencia or "").upper()
            localidad = ref.split('LOCALIDAD:')[1].split('|')[0].strip() if 'LOCALIDAD:' in ref else "ZONA URBANA"
            data.append({
                "Guia":      str(e.numero_guia),
                "Fecha":     e.fecha_creacion.strftime('%d/%m/%Y'),
                "Cliente":   f"{e.cliente.nombre} {e.cliente.apellido}"[:35] if e.cliente else "ANÓNIMO",
                "Localidad": localidad[:20],
                "Direccion": (e.lugar_entrega.direccion or "SIN DIRECCIÓN")[:40],
                "Estado":    str(e.estado).upper(),
                "Valor":     f"{float(e.costo_envio):,.0f}"
            })

        if formato == "csv":
            df = pd.DataFrame(data)
            output = io.StringIO()
            df.to_csv(output, index=False, encoding='utf-8-sig')
            return Response(
                content=output.getvalue(), media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename=reporte_enviexpress_{int(time.time())}.csv"}
            )
        elif formato == "pdf":
            pdf = PDF(orientation='L', unit='mm', format='A4')
            pdf.add_page()
            pdf.set_fill_color(0, 58, 140)
            pdf.set_text_color(255)
            pdf.set_font('Arial', 'B', 10)
            for h, w in [("Guía",30),("Fecha",25),("Cliente",55),("Localidad",35),("Dirección",75),("Estado",30),("Valor",30)]:
                pdf.cell(w, 10, h, 1, 0, 'C', True)
            pdf.ln()
            pdf.set_text_color(0)
            pdf.set_font('Arial', '', 9)
            for row in data:
                pdf.cell(30, 8, row["Guia"], 1)
                pdf.cell(25, 8, row["Fecha"], 1)
                pdf.cell(55, 8, row["Cliente"].encode('latin-1','replace').decode('latin-1'), 1)
                pdf.cell(35, 8, row["Localidad"].encode('latin-1','replace').decode('latin-1'), 1)
                pdf.cell(75, 8, row["Direccion"].encode('latin-1','replace').decode('latin-1'), 1)
                pdf.cell(30, 8, row["Estado"], 1)
                pdf.cell(30, 8, f"$ {row['Valor']}", 1)
                pdf.ln()
            return Response(
                content=bytes(pdf.output(dest='S')), media_type="application/pdf",
                headers={"Content-Disposition": "attachment; filename=reporte_enviexpress.pdf"}
            )
    except Exception as e:
        print(f"Error en Reporte: {e}")
        raise HTTPException(status_code=500, detail="Error al generar el documento")


# ─────────────────────────────────────────────────────────────────────────────
# EDITAR
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/editar/{id}")
def editar(id: int, request: Request, db: Session = Depends(get_db)):
    envio = db.query(Envio).options(
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega)
    ).filter(Envio.envio_id == id).first()

    if not envio:
        raise HTTPException(status_code=404, detail="Guía no encontrada para edición")

    datos = _cargar_datos_formulario(db)
    user_id = request.session.get("user_id")

    usuario_actual = db.query(Usuario).options(joinedload(Usuario.tarifa)).filter(
        Usuario.id_usuario == user_id).first()

    clientes_con_tarifa = db.query(Usuario).options(joinedload(Usuario.tarifa)).filter(
        Usuario.rol == "CLIENTE").all()

    datos['clientes'] = clientes_con_tarifa
    clientes_tarifas  = _build_clientes_tarifas(clientes_con_tarifa)

    if usuario_actual and usuario_actual.rol != 'ADMIN':
        clientes_tarifas = {}

    ciudad_rec, depto_rec = _extraer_ciudad_depto(envio.lugar_recogida)
    loc_rec,    tel_rec   = _extraer_localidad_telefono(envio.lugar_recogida)
    ciudad_ent, depto_ent = _extraer_ciudad_depto(envio.lugar_entrega)
    loc_ent,    tel_ent   = _extraer_localidad_telefono(envio.lugar_entrega)
    descripcion, obs      = _extraer_descripcion_obs(envio)

    ref_ent = envio.lugar_entrega.referencia if envio.lugar_entrega and envio.lugar_entrega.referencia else ""
    nombre_dest = ref_ent.split("Nombre:")[1].split("|")[0].strip() if "Nombre:" in ref_ent else ""

    return templates.TemplateResponse("form-envio.html", {
        "request": request, "envio": envio,
        "rol": request.session.get("rol", "CLIENTE"),
        "current_user": usuario_actual,
        "clientes_tarifas": clientes_tarifas,
        "edit_depto_rec":   depto_rec, "edit_ciudad_rec":  ciudad_rec,
        "edit_tel_rec":     tel_rec,   "edit_loc_rec":     loc_rec,
        "edit_depto_ent":   depto_ent, "edit_ciudad_ent":  ciudad_ent,
        "edit_tel_ent":     tel_ent,   "edit_loc_ent":     loc_ent,
        "edit_descripcion": descripcion, "edit_obs": obs,
        "edit_nombre_dest": nombre_dest,
        **datos
    })


# ─────────────────────────────────────────────────────────────────────────────
# CLONAR
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/clonar/{id}")
def clonar(id: int, request: Request, db: Session = Depends(get_db)):
    envio = db.query(Envio).options(
        joinedload(Envio.lugar_recogida), joinedload(Envio.lugar_entrega)
    ).filter(Envio.envio_id == id).first()

    if not envio:
        raise HTTPException(status_code=404, detail="Guía no encontrada para clonar")

    datos = _cargar_datos_formulario(db)
    user_id = request.session.get("user_id")
    usuario_actual = db.query(Usuario).options(joinedload(Usuario.tarifa)).filter(
        Usuario.id_usuario == user_id).first()
    clientes_con_tarifa = db.query(Usuario).options(joinedload(Usuario.tarifa)).filter(
        Usuario.rol == "CLIENTE").all()
    datos['clientes'] = clientes_con_tarifa
    clientes_tarifas  = _build_clientes_tarifas(clientes_con_tarifa)
    if usuario_actual and usuario_actual.rol != 'ADMIN':
        clientes_tarifas = {}

    ciudad_rec, depto_rec = _extraer_ciudad_depto(envio.lugar_recogida)
    loc_rec,    tel_rec   = _extraer_localidad_telefono(envio.lugar_recogida)
    ciudad_ent, depto_ent = _extraer_ciudad_depto(envio.lugar_entrega)
    loc_ent,    tel_ent   = _extraer_localidad_telefono(envio.lugar_entrega)
    descripcion, obs      = _extraer_descripcion_obs(envio)

    return templates.TemplateResponse("form-envio.html", {
        "request": request, "envio": None,
        "rol": request.session.get("rol", "CLIENTE"),
        "current_user": usuario_actual, "clientes_tarifas": clientes_tarifas,
        "edit_depto_rec": depto_rec, "edit_ciudad_rec": ciudad_rec,
        "edit_tel_rec": tel_rec, "edit_loc_rec": loc_rec,
        "edit_depto_ent": depto_ent, "edit_ciudad_ent": ciudad_ent,
        "edit_tel_ent": tel_ent, "edit_loc_ent": loc_ent,
        "edit_descripcion": descripcion, "edit_obs": obs, "edit_nombre_dest": "",
        **datos
    })


# ─────────────────────────────────────────────────────────────────────────────
# MAPA, RUTAS, ASIGNACIÓN
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/puntos-mapa")
def obtener_puntos_mapa(db: Session = Depends(get_db)):
    envios = db.query(Envio).join(Envio.lugar_entrega).filter(
        Envio.ruta_id == None, Envio.estado == "Registrado", Lugar.latitud != None
    ).all()
    return [{
        "id": e.envio_id, "guia": e.numero_guia,
        "lat": float(e.lugar_entrega.latitud), "lng": float(e.lugar_entrega.longitud),
        "direccion": e.lugar_entrega.direccion,
        "cliente": f"{e.cliente.nombre} {e.cliente.apellido}" if e.cliente else "N/A"
    } for e in envios]


@router.get("/ver-ruta/{mensajero_id}", response_class=HTMLResponse)
async def ver_ruta(request: Request, mensajero_id: int, db: Session = Depends(get_db)):
    mensajero = db.query(Usuario).filter(Usuario.id_usuario == mensajero_id).first()
    if not mensajero:
        raise HTTPException(status_code=404, detail="Mensajero no encontrado")

    ruta = db.query(Ruta).filter(
        Ruta.mensajero_id == mensajero_id, Ruta.estado.in_(["Creada", "En curso"])
    ).order_by(Ruta.ruta_id.desc()).first()

    envios_c = db.query(Envio).filter(
        Envio.usuario_mensajero_id == mensajero_id,
        Envio.estado_recogida.in_(["En_Ruta", "Pendiente"]),
        Envio.estado.in_(["Pendiente_Recoger", "En_Ruta"])
    ).options(joinedload(Envio.lugar_recogida), joinedload(Envio.lugar_entrega)).all()

    envios_d = db.query(Envio).filter(
        Envio.usuario_mensajero_entrega_id == mensajero_id,
        Envio.estado_entrega.in_(["En_Ruta", "En_Destino"]),
        Envio.estado.in_(["Pendiente_Verificar", "En_Ruta"])
    ).options(joinedload(Envio.lugar_entrega)).all()

    ids_vistos = set()
    envios = []
    for e in envios_c + envios_d:
        ids_vistos.add(e.envio_id)
        envios.append(e)

    return templates.TemplateResponse("ver_ruta.html", {
        "request": request, "mensajero": mensajero, "ruta": ruta, "envios": envios
    })


@router.post("/asignar-mensajero-masivo")
async def asignar_masivo(request: Request, db: Session = Depends(get_db)):
    try:
        data         = await request.json()
        ids_envios   = data.get("envio_ids")
        id_mensajero = data.get("id_mensajero")
        nombre_ruta  = data.get("nombre_ruta", "").strip()
        tipo         = data.get("tipo", "all")

        if not ids_envios or not id_mensajero:
            raise HTTPException(status_code=400, detail="Parámetros incompletos")

        mensajero = db.query(Usuario).filter(Usuario.id_usuario == int(id_mensajero)).first()
        if not mensajero:
            raise HTTPException(status_code=404, detail="Mensajero no encontrado")

        if not nombre_ruta:
            nombre_ruta = f"Ruta Express - {mensajero.nombre} {datetime.now().strftime('%H:%M')}"

        nueva_ruta = Ruta(nombre_sector=nombre_ruta, ciudad="Bogotá",
                          mensajero_id=int(id_mensajero), estado="Creada")
        db.add(nueva_ruta)
        db.flush()

        for envio_id in ids_envios:
            envio = db.query(Envio).filter(Envio.envio_id == int(envio_id)).first()
            if not envio:
                continue
            if tipo == "c":
                envio.usuario_mensajero_id = int(id_mensajero)
                envio.ruta_id = nueva_ruta.ruta_id
                envio.estado_recogida = "En_Ruta"
                envio.estado = "Pendiente_Recoger"
            elif tipo == "d":
                envio.usuario_mensajero_entrega_id = int(id_mensajero)
                envio.ruta_id = nueva_ruta.ruta_id
                envio.estado_entrega = "En_Ruta"
                envio.estado = "Pendiente_Verificar"
            else:
                envio.usuario_mensajero_id = int(id_mensajero)
                envio.usuario_mensajero_entrega_id = int(id_mensajero)
                envio.ruta_id = nueva_ruta.ruta_id
                envio.estado_recogida = "En_Ruta"
                envio.estado_entrega = "En_Ruta"
                envio.estado = "En_Ruta"

        db.commit()
        return {"status": "success", "ruta_id": nueva_ruta.ruta_id, "total": len(ids_envios)}
    except Exception as e:
        db.rollback()
        import traceback; traceback.print_exc()
        return JSONResponse(status_code=500, content={"detail": str(e)})


@router.get("/quitar-de-ruta/{envio_id}")
async def quitar_de_ruta(envio_id: int, db: Session = Depends(get_db)):
    try:
        envio = db.query(Envio).filter(Envio.envio_id == envio_id).first()
        if not envio:
            return {"status": "error", "message": "Envío no encontrado"}
        envio.usuario_mensajero_id = None
        envio.estado = "Registrado"
        envio.ruta_id = None
        db.commit()
        return RedirectResponse(url="/envios", status_code=303)
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}


@router.post("/quitar-de-ruta-masivo")
async def quitar_de_ruta_masivo(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
        envio_ids = data.get("envio_ids", [])
        if not envio_ids:
            return {"status": "error", "message": "No hay envíos seleccionados"}
        db.query(Envio).filter(Envio.envio_id.in_(envio_ids)).update(
            {"usuario_mensajero_id": None, "estado": "Registrado", "ruta_id": None},
            synchronize_session=False
        )
        db.commit()
        return {"status": "success"}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# SALDO Y GESTIÓN ERP
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/recargar-saldo")
async def recargar_saldo(request: Request, db: Session = Depends(get_db)):
    try:
        form      = await request.form()
        u_id      = request.session.get("user_id")
        monto_str = form.get("monto_plan")
        if not u_id or not monto_str:
            return RedirectResponse(url="/login?error=auth")
        monto = int(monto_str)
        db.execute(text("UPDATE usuario SET saldo_plan = saldo_plan + :m, rol = 'CLIENTE' WHERE id_usuario = :u"),
                   {"m": monto, "u": u_id})
        db.execute(text("INSERT INTO transaccion (usuario_id, tipo_movimiento, monto, concepto, fecha_creacion) VALUES (:u, 'RECARGA', :m, 'Compra de Plan / Recarga de Billetera', NOW())"),
                   {"u": u_id, "m": monto})
        db.commit()
        return RedirectResponse(url=f"/home_cliente?v={int(time.time())}", status_code=303)
    except Exception as e:
        db.rollback()
        print(f"Error en recargas: {e}")
        return RedirectResponse(url="/home_cliente?error=true")


@router.get("/gestion/{id}")
def gestionar_envio_erp(id: int, request: Request, db: Session = Depends(get_db)):
    envio = db.query(Envio).options(
        joinedload(Envio.cliente), joinedload(Envio.mensajero), joinedload(Envio.tarifa),
        joinedload(Envio.lugar_recogida), joinedload(Envio.lugar_entrega),
        joinedload(Envio.seguimientos),
        joinedload(Envio.mensajero_entrega)
    ).filter(Envio.envio_id == id).first()

    if not envio:
        raise HTTPException(status_code=404, detail="Envío no encontrado")

    ciudad_rec, depto_rec = _extraer_ciudad_depto(envio.lugar_recogida)
    ciudad_ent, depto_ent = _extraer_ciudad_depto(envio.lugar_entrega)
    descripcion, obs      = _extraer_descripcion_obs(envio)

    mensajeros = db.query(Usuario).filter(Usuario.rol == "MENSAJERO").all()

    return templates.TemplateResponse("gestionar_detalle.html", {
        "request": request, "envio": envio,
        "ciudad_rec": ciudad_rec, "depto_rec": depto_rec,
        "ciudad_ent": ciudad_ent, "depto_ent": depto_ent,
        "tel_rec": _extraer_localidad_telefono(envio.lugar_recogida)[1],
        "tel_ent": _extraer_localidad_telefono(envio.lugar_entrega)[1],
        "descripcion": descripcion, "observaciones": obs,
        "rol": request.session.get("rol", "ADMIN"),
        "mensajeros": mensajeros,
    })


@router.post("/actualizar-gestion/{id}")
async def actualizar_gestion_envio(id: int, request: Request, db: Session = Depends(get_db)):
    try:
        form  = await request.form()
        envio = db.query(Envio).filter(Envio.envio_id == id).first()
        if not envio:
            return JSONResponse(status_code=404, content={"message": "Envío no encontrado"})

        if envio.lugar_recogida and form.get("dir_rec"):
            envio.lugar_recogida.direccion = form.get("dir_rec")
        if envio.lugar_entrega and form.get("dir_ent"):
            envio.lugar_entrega.direccion = form.get("dir_ent")

        nuevo_estado      = form.get("nuevo_estado", "").strip()
        comentario_novedad = form.get("comentario_novedad", "").strip()

        if nuevo_estado and nuevo_estado != envio.estado:
            envio.estado = nuevo_estado
            descripcion = comentario_novedad or f"Estado actualizado a: {nuevo_estado}"
            db.add(Seguimiento(
                envio_id=id,
                estado=nuevo_estado,
                descripcion=descripcion,
                fecha=datetime.now()
            ))
        elif comentario_novedad:
            # Solo comentario sin cambio de estado
            db.add(Seguimiento(
                envio_id=id,
                estado=envio.estado,
                descripcion=comentario_novedad,
                fecha=datetime.now()
            ))

        db.commit()
        return RedirectResponse(url=f"/envios/gestion/{id}?success=true", status_code=303)
    except Exception as e:
        db.rollback()
        return RedirectResponse(url=f"/envios/gestion/{id}?error=true", status_code=303)


# ─────────────────────────────────────────────────────────────────────────────
# FOTO DE ENTREGA
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{envio_id}/foto-entrega")
async def subir_foto_entrega(
    envio_id: int, file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    if current_user.rol != "MENSAJERO":
        raise HTTPException(status_code=403, detail="Solo mensajeros pueden subir fotos")
    envio = db.query(Envio).filter(Envio.envio_id == envio_id).first()
    if not envio:
        raise HTTPException(status_code=404, detail="Envío no encontrado")
    if envio.usuario_mensajero_id != current_user.id_usuario:
        raise HTTPException(status_code=403, detail="No tienes permiso sobre este envío")

    carpeta = "app/static/fotos_entrega"
    os.makedirs(carpeta, exist_ok=True)
    extension = file.filename.rsplit(".", 1)[-1].lower() if file.filename else "jpg"
    if extension not in ["jpg", "jpeg", "png", "webp"]:
        extension = "jpg"
    nombre_archivo = f"{envio.numero_guia}.{extension}"
    with open(f"{carpeta}/{nombre_archivo}", "wb") as f:
        shutil.copyfileobj(file.file, f)

    envio.foto_entrega = nombre_archivo
    db.commit()
    return JSONResponse({"ok": True, "foto": nombre_archivo})


# ─────────────────────────────────────────────────────────────────────────────
# API PÚBLICA: RASTREO DE GUÍAS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/rastreo/{numero_guia}")
def rastrear_guia_publica(numero_guia: str, db: Session = Depends(get_db)):
    envio = envio_repo.find_by_numero_guia(db, numero_guia)

    if not envio:
        raise HTTPException(status_code=404, detail="Número de guía no encontrado")

    return {
        "envio_id": envio.envio_id,
        "numero_guia": envio.numero_guia,
        "estado": envio.estado,
        "tipo_servicio": envio.tipo_servicio,
        "fecha_creacion": envio.fecha_creacion.isoformat() if envio.fecha_creacion else None,
        "seguimientos": [
            {
                "seguimiento_id": s.seguimiento_id,
                "estado": s.estado,
                "descripcion": s.descripcion if s.descripcion else "Sin observaciones.",
                "fecha": s.fecha.isoformat() if s.fecha else None
            }
            for s in envio.seguimientos
        ] if envio.seguimientos else []
    }

# --- FIN DEL CONTROLADOR ---