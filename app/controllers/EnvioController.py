# app/controllers/EnvioController.py
from django import db
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, Form
from fastapi.responses import RedirectResponse, HTMLResponse, StreamingResponse, JSONResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text, distinct
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
import io
import time
import pandas as pd
from fpdf import FPDF
from app.models.Ruta import Ruta
from geopy.geocoders import Nominatim

from app.config.database import get_db
from app.models.Envio import Envio
from app.models.Lugar import Lugar
from app.models.Usuario import Usuario
from app.models.Transaccion import Transaccion
from app.models.Tarifa import Tarifa
from app.models.Vehiculo import Vehiculo

from app.security.SecurityConfig import get_current_user, require_admin, require_admin_or_mensajero
import app.repositories.EnvioRepository as envio_repo
import app.repositories.UsuarioRepository as usuario_repo
import app.repositories.VehiculoRepository as vehiculo_repo
import app.repositories.TarifaRepository as tarifa_repo
import app.repositories.RutaRepository as ruta_repo
import app.repositories.LugarRepository as lugar_repo
from app.config.templates import templates

router = APIRouter(prefix="/envios", tags=["Envíos"])

# --- CLASE PDF PROFESIONAL PARA REPORTES ---
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
        self.cell(0, 10, f'ENVIEXPRESS S.A.S - Sistema de Gestión Logística - Página {self.page_no()}', 0, 0, 'C')


# --- FUNCIÓN DE CONSECUTIVO DE GUÍAS CON BLOQUEO ---
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
        return f"ENV-{nuevo_numero:05d}"
    except Exception as e:
        db.rollback()
        print(f"Error crítico en consecutivo: {e}")
        return f"ENV-{datetime.now().strftime('%H%M%S')}"


# --- FUNCIÓN DE GEOLOCALIZACIÓN (fallback con Nominatim) ---
def obtener_coordenadas(direccion, ciudad):
    try:
        geolocator = Nominatim(user_agent="enviexpress_manager_v3")
        query = f"{direccion}, {ciudad}, Colombia"
        location = geolocator.geocode(query, timeout=12)
        if location:
            return location.latitude, location.longitude
    except Exception as e:
        print(f"Error en Geocodificación: {e}")
    return None, None


# --- CARGA DE DATOS PARA FORMULARIOS ---
def _cargar_datos_formulario(db: Session):
    return {
        "clientes": db.query(Usuario).filter(Usuario.rol == "CLIENTE").all(),
        "tarifas": db.query(Tarifa).all(),
        "estados": ["Registrado", "En_Bodega", "En_Ruta", "Entregado", "Cancelado"]
    }


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: construye el mapa {cliente_id: nombre_tarifa} para el cotizador admin
# ─────────────────────────────────────────────────────────────────────────────
def _build_clientes_tarifas(clientes: list) -> dict:
    resultado = {}
    for c in clientes:
        if c.tarifa and c.tarifa.nombre:
            resultado[c.id_usuario] = c.tarifa.nombre
    return resultado


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: extrae ciudad y departamento del campo Lugar.ciudad
# ─────────────────────────────────────────────────────────────────────────────
def _extraer_ciudad_depto(lugar) -> tuple:
    if not lugar or not lugar.ciudad:
        return "", ""
    raw = lugar.ciudad
    if " (" in raw:
        partes = raw.split(" (", 1)
        ciudad = partes[0].strip()
        depto  = partes[1].rstrip(")").strip()
    else:
        ciudad = raw.strip()
        depto  = raw.strip()
    return ciudad, depto


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: extrae localidad y teléfono del campo Lugar.referencia
# ─────────────────────────────────────────────────────────────────────────────
def _extraer_localidad_telefono(lugar) -> tuple:
    if not lugar or not lugar.referencia:
        return "", ""
    localidad = ""
    telefono  = ""
    for parte in lugar.referencia.split("|"):
        p = parte.strip()
        if p.upper().startswith("LOCALIDAD:"):
            localidad = p.split(":", 1)[1].strip()
        elif p.upper().startswith("TEL:"):
            telefono = p.split(":", 1)[1].strip()
    return localidad, telefono


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: extrae descripción e instrucciones del campo Envio.instrucciones
# ─────────────────────────────────────────────────────────────────────────────
def _extraer_descripcion_obs(envio) -> tuple:
    if not envio or not envio.instrucciones:
        return "", ""
    descripcion   = ""
    observaciones = ""
    for parte in envio.instrucciones.split("|"):
        p = parte.strip()
        if p.upper().startswith("CONTENIDO:"):
            descripcion = p.split(":", 1)[1].strip()
        elif p.upper().startswith("OBS:"):
            observaciones = p.split(":", 1)[1].strip()
    return descripcion, observaciones


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: genera el dict de campos de edición vacíos (para nuevo envío)
# ─────────────────────────────────────────────────────────────────────────────
def _campos_edicion_vacios() -> dict:
    return {
        "edit_depto_rec":   "",
        "edit_ciudad_rec":  "",
        "edit_tel_rec":     "",
        "edit_loc_rec":     "",
        "edit_dir_rec":     "",   # ← nueva
        "edit_depto_ent":   "",
        "edit_ciudad_ent":  "",
        "edit_tel_ent":     "",
        "edit_loc_ent":     "",
        "edit_descripcion": "",
        "edit_obs":         "",
    }

# --- LISTADO PRINCIPAL PARA ADMINISTRADORES ---
@router.get("/")
def listar(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=302)

    envios = db.query(Envio).options(
        joinedload(Envio.cliente),
        joinedload(Envio.mensajero),
        joinedload(Envio.tarifa),
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega)
    ).order_by(Envio.fecha_creacion.desc()).all()

    mensajeros = db.query(Usuario).filter(Usuario.rol == "MENSAJERO").all()
    clientes_registrados = db.query(Usuario).filter(Usuario.rol.ilike("%CLIENTE%")).all()

    response = templates.TemplateResponse("envios.html", {
        "request": request,
        "envios": envios,
        "mensajeros": mensajeros,
        "clientes": clientes_registrados,
        "rol": request.session.get("rol", "ADMIN")
    })

    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


# --- LISTADO ESPECÍFICO PARA EL CLIENTE ---
@router.get("/mis-guias")
def listar_mis_guias(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login?error=expired")

    usuario = db.query(Usuario).options(joinedload(Usuario.tarifa)).filter(Usuario.id_usuario == user_id).first()
    if not usuario:
        return RedirectResponse(url="/login")

    todas_las_tarifas = db.query(Tarifa).all()

    mis_envios = db.query(Envio).filter(
        Envio.usuario_cliente_id == usuario.id_usuario
    ).options(
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega),
        joinedload(Envio.tarifa)
    ).order_by(Envio.fecha_creacion.desc()).all()

    historial_pagos = db.query(Transaccion).filter(
        Transaccion.usuario_id == usuario.id_usuario
    ).order_by(Transaccion.fecha_creacion.desc()).limit(15).all()

    response = templates.TemplateResponse("envios_cliente.html", {
        "request": request,
        "envios": mis_envios,
        "transacciones": historial_pagos,
        "username": usuario.user_name,
        "current_user": usuario,
        "tarifas": todas_las_tarifas
    })

    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


# --- DETALLE AMPLIADO DEL ENVÍO ---
@router.get("/detalle/{id}")
def ver_detalle_envio(id: int, request: Request, db: Session = Depends(get_db)):
    envio = db.query(Envio).options(
        joinedload(Envio.cliente),
        joinedload(Envio.mensajero),
        joinedload(Envio.tarifa),
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega),
        joinedload(Envio.vehiculo)
    ).filter(Envio.envio_id == id).first()

    if not envio:
        raise HTTPException(status_code=404, detail="El envío solicitado no existe o fue eliminado")

    rol_session = request.session.get("rol", "CLIENTE")
    return templates.TemplateResponse("detalle-envio.html", {
        "request": request,
        "envio": envio,
        "rol": rol_session
    })


# --- RUTA PARA EL FORMULARIO DE NUEVO ENVÍO ---
# --- RUTA PARA EL FORMULARIO DE NUEVO ENVÍO ---
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
        clientes_con_tarifa = db.query(Usuario).options(
            joinedload(Usuario.tarifa)
        ).filter(Usuario.rol == "CLIENTE").all()

        datos['clientes'] = clientes_con_tarifa
        clientes_tarifas  = _build_clientes_tarifas(clientes_con_tarifa)
        campos = _campos_edicion_vacios()

        if usuario_actual.rol != 'ADMIN':
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
            saldo = None  # Admin no tiene restricción de saldo

        return templates.TemplateResponse("form-envio.html", {   # ← UN SOLO return al final
            "request": request,
            "envio": None,
            "rol": usuario_actual.rol,
            "current_user": usuario_actual,
            "clientes_tarifas": clientes_tarifas,
            "saldo_disponible": saldo,
            **campos,
            **datos
        })

    except Exception as e:
        print(f"Error renderizando formulario: {e}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

# --- PROCESO PRINCIPAL DE GUARDADO ---
@router.post("/guardar")
async def guardar(request: Request, db: Session = Depends(get_db)):
    rol = request.session.get("rol", "CLIENTE")
    destino_ok = "/envios" if rol == "ADMIN" else "/envios/mis-guias"

    try:
        form = await request.form()
        envio_id = form.get("envio_id")
        es_nuevo = not (envio_id and envio_id.strip())

        # Si es ADMIN usa el cliente seleccionado en el formulario.
        # Si es CLIENTE usa su propio usuario de sesión.
        if rol == "ADMIN":
            cliente_id = form.get("usuario_cliente_id")
            if not cliente_id:
                return RedirectResponse(url=f"{destino_ok}?error=cliente_requerido", status_code=303)
            cliente = db.query(Usuario).options(
                joinedload(Usuario.tarifa)
            ).filter(Usuario.id_usuario == int(cliente_id)).first()
        else:
            username_session = request.session.get("username")
            cliente = db.query(Usuario).options(
                joinedload(Usuario.tarifa)
            ).filter(Usuario.user_name == username_session).first()

        if not cliente:
            return RedirectResponse(url="/login")

        es_cod = form.get("es_cod") == "on"
        valor_a_cobrar = Decimal(form.get("valor_a_cobrar") or "0") if es_cod else Decimal("0")

        depto_entrega  = form.get("depto_entrega", "").upper()
        ciudad_entrega = form.get("ciudad_entrega", "").upper()
        es_bogota = "BOGOTÁ" in depto_entrega or "BOGOTÁ" in ciudad_entrega

        obs_cliente = form.get("instrucciones_especiales", "").strip()
        contenido   = form.get("descripcion", "").strip()
        instrucciones_finales = f"CONTENIDO: {contenido} | OBS: {obs_cliente}"

        if es_nuevo:
            if not es_bogota:
                tarifa_db  = db.query(Tarifa).filter(
                    Tarifa.nombre.ilike("%Nacional%") | Tarifa.nombre.ilike("%Raíces%")
                ).first()
                # ✅ Corrección
                costo_base = tarifa_db.precio_plan if tarifa_db else Decimal("17990")
                tar_id     = tarifa_db.id if tarifa_db else None
            else:
                tarifa_db  = db.query(Tarifa).filter(Tarifa.id == cliente.tarifa_id).first()
                costo_base = tarifa_db.precio_plan if tarifa_db else cliente.cuota_fija
                tar_id     = tarifa_db.id if tarifa_db else None

            comision_cod = Decimal("0")
            if es_cod and valor_a_cobrar > 0:
                comision_cod = (valor_a_cobrar * Decimal("0.03")).quantize(Decimal("1.00"), rounding=ROUND_HALF_UP)

            costo_total_envio = costo_base + comision_cod

            if cliente.saldo_plan < costo_total_envio:
                return RedirectResponse(url=f"{destino_ok}?error=saldo_insuficiente", status_code=303)

            envio = Envio(
                numero_guia=generar_nuevo_consecutivo(db),
                usuario_cliente_id=cliente.id_usuario,
                fecha_creacion=datetime.now(),
                estado="Registrado",
                costo_envio=costo_total_envio,
                tipo_servicio="EXPRESS" if es_bogota else "NACIONAL",
                instrucciones=instrucciones_finales,
                peso=Decimal(form.get("peso", "1.0")),
                tarifa_id=tar_id,
                es_cod=es_cod,
                valor_a_cobrar=valor_a_cobrar
            )

            cliente.saldo_plan -= costo_total_envio
            db.add(envio)
            db.flush()

            db.add(Transaccion(
                usuario_id=cliente.id_usuario,
                envio_id=envio.envio_id,
                tipo_movimiento='DESCUENTO',
                monto=-costo_total_envio,
                concepto=f"Pago {'Nacional' if not es_bogota else 'Urbano'} Guía {envio.numero_guia} (Base: {costo_base} + COD 3%: {comision_cod})",
                fecha_creacion=datetime.now()
            ))
        else:
            envio = db.query(Envio).filter(Envio.envio_id == int(envio_id)).first()
            if not envio:
                return RedirectResponse(url=f"{destino_ok}?error=no_encontrado")

            envio.instrucciones  = instrucciones_finales
            envio.es_cod         = es_cod
            envio.valor_a_cobrar = valor_a_cobrar
            envio.peso           = Decimal(form.get("peso", "1.0"))

        # ─────────────────────────────────────────────────────────────────────
        # ✅ PROCESAMIENTO DE LUGARES CON COORDENADAS DE GOOGLE MAPS
        #    Prioridad: coordenadas del formulario (Google Maps)
        #    Fallback:  Nominatim si no hay coordenadas en el formulario
        # ─────────────────────────────────────────────────────────────────────
        for tipo in ["recogida", "entrega"]:
            ciudad    = form.get(f"ciudad_{tipo}", "")
            depto     = form.get(f"depto_{tipo}", "")
            direccion = form.get(f"direccion_{tipo}", "").strip()
            telefono  = form.get(f"telefono_{tipo}", "").strip()
            localidad = form.get(f"localidad_{tipo}", "").strip()

            # ✅ Leer coordenadas enviadas por Google Maps desde el formulario
            lat_form = form.get(f"lat_{tipo}", "").strip()
            lon_form = form.get(f"lon_{tipo}", "").strip()

            if direccion:
                if tipo == "entrega":
                    nombre_dest = form.get("nombre_destinatario", "").strip()
                    referencia_final = f"Nombre: {nombre_dest} | Localidad: {localidad} | Tel: {telefono}" if localidad else f"Nombre: {nombre_dest} | Tel: {telefono}"
                else:
                    referencia_final = f"Localidad: {localidad} | Tel: {telefono}" if localidad else f"Tel: {telefono}"

                # ✅ Usar coordenadas de Google Maps si el usuario las seleccionó
                if lat_form and lon_form:
                    try:
                        lat = float(lat_form)
                        lng = float(lon_form)
                        print(f"✅ Coordenadas Google Maps para {tipo}: lat={lat}, lng={lng}")
                    except ValueError:
                        print(f"⚠️ Error parseando coordenadas de formulario para {tipo}, usando Nominatim")
                        lat, lng = obtener_coordenadas(direccion, ciudad)
                else:
                    # Fallback a Nominatim si no hay coordenadas del mapa
                    print(f"⚠️ Sin coordenadas en formulario para {tipo}, usando Nominatim")
                    lat, lng = obtener_coordenadas(direccion, ciudad)

                lugar = Lugar(
                    direccion=direccion,
                    ciudad=f"{ciudad} ({depto})",
                    referencia=referencia_final,
                    latitud=lat,
                    longitud=lng
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


# --- ELIMINAR ENVÍO CON REEMBOLSO ---
@router.get("/eliminar/{id}")
def eliminar(id: int, request: Request, db: Session = Depends(get_db)):
    rol = request.session.get("rol", "CLIENTE")
    destino_ok = "/envios" if rol == "ADMIN" else "/envios/mis-guias"

    try:
        envio = db.query(Envio).filter(Envio.envio_id == id).first()
        if not envio:
            return RedirectResponse(url=destino_ok)

        cliente = db.query(Usuario).filter(Usuario.id_usuario == envio.usuario_cliente_id).first()
        if cliente and envio.costo_envio > 0 and envio.estado == "Registrado":
            cliente.saldo_plan += envio.costo_envio
            db.add(Transaccion(
                usuario_id=cliente.id_usuario,
                tipo_movimiento='REEMBOLSO',
                monto=envio.costo_envio,
                concepto=f"Reembolso por anulación de Guía {envio.numero_guia}",
                fecha_creacion=datetime.now()
            ))

        db.delete(envio)
        db.commit()
        return RedirectResponse(url=destino_ok, status_code=303)
    except Exception as e:
        db.rollback()
        print(f"Error en eliminación: {e}")
        return RedirectResponse(url=f"{destino_ok}?error=delete_fail")


# --- VISTA DE IMPRESIÓN ---
@router.get("/imprimir/{id}")
def imprimir_guia(id: int, request: Request, db: Session = Depends(get_db)):
    envio = db.query(Envio).options(
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega),
        joinedload(Envio.cliente)
    ).filter(Envio.envio_id == id).first()

    if not envio:
        raise HTTPException(status_code=404, detail="La guía no pudo ser localizada")

    return templates.TemplateResponse("imprimir_guia.html", {
        "request": request,
        "envio": envio,
        "fecha_actual": datetime.now().strftime("%d/%m/%Y %H:%M")
    })
    
@router.get("/imprimir-masivo")
def imprimir_masivo(request: Request, ids: str, db: Session = Depends(get_db)):
    lista_ids = [int(i) for i in ids.split(",")]
    envios = db.query(Envio).options(
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega),
        joinedload(Envio.cliente)
    ).filter(Envio.envio_id.in_(lista_ids)).all()
    return templates.TemplateResponse("imprimir_masivo.html", {
        "request": request,
        "envios": envios
    })


# --- REPORTES DINÁMICOS (PDF / CSV) ---
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
            headers = [("Guía", 30), ("Fecha", 25), ("Cliente", 55), ("Localidad", 35), ("Dirección", 75), ("Estado", 30), ("Valor", 30)]
            for h, w in headers:
                pdf.cell(w, 10, h, 1, 0, 'C', True)
            pdf.ln()
            pdf.set_text_color(0)
            pdf.set_font('Arial', '', 9)
            for row in data:
                pdf.cell(30, 8, row["Guia"], 1)
                pdf.cell(25, 8, row["Fecha"], 1)
                pdf.cell(55, 8, row["Cliente"].encode('latin-1', 'replace').decode('latin-1'), 1)
                pdf.cell(35, 8, row["Localidad"].encode('latin-1', 'replace').decode('latin-1'), 1)
                pdf.cell(75, 8, row["Direccion"].encode('latin-1', 'replace').decode('latin-1'), 1)
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


# --- EDITAR ENVÍO ---
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

    usuario_actual = db.query(Usuario).options(
        joinedload(Usuario.tarifa)
    ).filter(Usuario.id_usuario == user_id).first()

    clientes_con_tarifa = db.query(Usuario).options(
        joinedload(Usuario.tarifa)
    ).filter(Usuario.rol == "CLIENTE").all()

    datos['clientes'] = clientes_con_tarifa
    clientes_tarifas  = _build_clientes_tarifas(clientes_con_tarifa)

    if usuario_actual and usuario_actual.rol != 'ADMIN':
        clientes_tarifas = {}

    ciudad_rec, depto_rec = _extraer_ciudad_depto(envio.lugar_recogida)
    loc_rec,    tel_rec   = _extraer_localidad_telefono(envio.lugar_recogida)

    ciudad_ent, depto_ent = _extraer_ciudad_depto(envio.lugar_entrega)
    loc_ent,    tel_ent   = _extraer_localidad_telefono(envio.lugar_entrega)

    descripcion, obs = _extraer_descripcion_obs(envio)

    return templates.TemplateResponse("form-envio.html", {
        "request": request,
        "envio": envio,
        "rol": request.session.get("rol", "CLIENTE"),
        "current_user": usuario_actual,
        "clientes_tarifas": clientes_tarifas,
        "edit_depto_rec":   depto_rec,
        "edit_ciudad_rec":  ciudad_rec,
        "edit_tel_rec":     tel_rec,
        "edit_loc_rec":     loc_rec,
        "edit_depto_ent":   depto_ent,
        "edit_ciudad_ent":  ciudad_ent,
        "edit_tel_ent":     tel_ent,
        "edit_loc_ent":     loc_ent,
        "edit_descripcion": descripcion,
        "edit_obs":         obs,
        **datos
    })


# --- CLONAR ENVÍO ---
@router.get("/clonar/{id}")
def clonar(id: int, request: Request, db: Session = Depends(get_db)):
    envio = db.query(Envio).options(
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega)
    ).filter(Envio.envio_id == id).first()

    if not envio:
        raise HTTPException(status_code=404, detail="Guía no encontrada para clonar")

    datos = _cargar_datos_formulario(db)
    user_id = request.session.get("user_id")

    usuario_actual = db.query(Usuario).options(
        joinedload(Usuario.tarifa)
    ).filter(Usuario.id_usuario == user_id).first()

    clientes_con_tarifa = db.query(Usuario).options(
        joinedload(Usuario.tarifa)
    ).filter(Usuario.rol == "CLIENTE").all()

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
        "request": request,
        "envio": None,
        "rol": request.session.get("rol", "CLIENTE"),
        "current_user": usuario_actual,
        "clientes_tarifas": clientes_tarifas,
        "edit_depto_rec":   depto_rec,
        "edit_ciudad_rec":  ciudad_rec,
        "edit_tel_rec":     tel_rec,
        "edit_loc_rec":     loc_rec,
        "edit_depto_ent":   depto_ent,
        "edit_ciudad_ent":  ciudad_ent,
        "edit_tel_ent":     tel_ent,
        "edit_loc_ent":     loc_ent,
        "edit_descripcion": descripcion,
        "edit_obs":         obs,
        **datos
    })


# --- PUNTOS GPS PARA EL MAPA OPERATIVO ---
@router.get("/puntos-mapa")
def obtener_puntos_mapa(db: Session = Depends(get_db)):
    envios = db.query(Envio).join(Envio.lugar_entrega).filter(
        Envio.ruta_id == None,
        Envio.estado == "Registrado",
        Lugar.latitud != None
    ).all()

    return [{
        "id":        e.envio_id,
        "guia":      e.numero_guia,
        "lat":       float(e.lugar_entrega.latitud),
        "lng":       float(e.lugar_entrega.longitud),
        "direccion": e.lugar_entrega.direccion,
        "cliente":   f"{e.cliente.nombre} {e.cliente.apellido}" if e.cliente else "N/A"
    } for e in envios]


# --- VER RUTA EN TIEMPO REAL DE UN MENSAJERO ---
@router.get("/ver-ruta/{id_mensajero}")
def ver_ruta_mensajero(id_mensajero: int, request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login")

    mensajero = db.query(Usuario).filter(
        Usuario.id_usuario == id_mensajero,
        Usuario.rol == "MENSAJERO"
    ).first()
    if not mensajero:
        raise HTTPException(status_code=404, detail="El mensajero no existe o no tiene una ruta asignada")

    envios = db.query(Envio).options(
        joinedload(Envio.lugar_entrega),
        joinedload(Envio.cliente)
    ).filter(
        Envio.usuario_mensajero_id == id_mensajero,
        Envio.estado == "En_Ruta"
    ).all()

    return templates.TemplateResponse("ver_ruta.html", {
        "request": request,
        "mensajero": mensajero,
        "envios": envios,
        "rol": request.session.get("rol", "ADMIN")
    })


# --- ASIGNACIÓN MASIVA DE ENVÍOS A MENSAJERO ---
@router.post("/asignar-mensajero-masivo")
async def asignar_masivo(request: Request, db: Session = Depends(get_db)):
    try:
        data         = await request.json()
        ids_envios   = data.get("envio_ids")
        id_mensajero = data.get("id_mensajero")

        if not ids_envios or not id_mensajero:
            raise HTTPException(status_code=400, detail="Parámetros de asignación incompletos")

        mensajero = db.query(Usuario).filter(Usuario.id_usuario == int(id_mensajero)).first()

        nueva_ruta = Ruta(
            nombre_sector=f"Ruta Express - {mensajero.nombre} {datetime.now().strftime('%H:%M')}",
            ciudad="Bogotá",
            mensajero_id=int(id_mensajero)
        )
        db.add(nueva_ruta)
        db.flush()

        for envio_id in ids_envios:
            envio = db.query(Envio).filter(Envio.envio_id == int(envio_id)).first()
            if envio:
                envio.usuario_mensajero_id = int(id_mensajero)
                envio.ruta_id              = nueva_ruta.ruta_id
                envio.estado               = "En_Ruta"

        db.commit()
        return {"status": "success", "ruta_id": nueva_ruta.ruta_id, "total": len(ids_envios)}
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"detail": f"Error en asignación: {str(e)}"})


# --- RECARGA ACUMULATIVA DE BILLETERA ---
@router.post("/recargar-saldo")
async def recargar_saldo(request: Request, db: Session = Depends(get_db)):
    try:
        form      = await request.form()
        u_id      = request.session.get("user_id")
        monto_str = form.get("monto_plan")

        if not u_id or not monto_str:
            return RedirectResponse(url="/login?error=auth")

        monto = int(monto_str)

        db.execute(text("""
            UPDATE usuario 
            SET saldo_plan = saldo_plan + :m, 
                rol = 'CLIENTE' 
            WHERE id_usuario = :u
        """), {"m": monto, "u": u_id})

        db.execute(text("""
            INSERT INTO transaccion (usuario_id, tipo_movimiento, monto, concepto, fecha_creacion) 
            VALUES (:u, 'RECARGA', :m, 'Compra de Plan / Recarga de Billetera', NOW())
        """), {"u": u_id, "m": monto})

        db.commit()
        return RedirectResponse(url=f"/home_cliente?v={int(time.time())}", status_code=303)

    except Exception as e:
        db.rollback()
        print(f"Error crítico en sistema de recargas: {e}")
        return RedirectResponse(url="/home_cliente?error=true")


# --- GESTIÓN TIPO ERP ---
@router.get("/gestion/{id}")
def gestionar_envio_erp(id: int, request: Request, db: Session = Depends(get_db)):
    envio = db.query(Envio).options(
        joinedload(Envio.cliente),
        joinedload(Envio.mensajero),
        joinedload(Envio.tarifa),
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega)
    ).filter(Envio.envio_id == id).first()

    if not envio:
        raise HTTPException(status_code=404, detail="Envío no encontrado")

    ciudad_rec, depto_rec = _extraer_ciudad_depto(envio.lugar_recogida)
    ciudad_ent, depto_ent = _extraer_ciudad_depto(envio.lugar_entrega)
    descripcion, obs = _extraer_descripcion_obs(envio)

    return templates.TemplateResponse("gestionar_detalle.html", {
        "request": request,
        "envio": envio,
        "ciudad_rec": ciudad_rec,
        "depto_rec": depto_rec,
        "ciudad_ent": ciudad_ent,
        "depto_ent": depto_ent,
        "descripcion": descripcion,
        "observaciones": obs,
        "rol": request.session.get("rol", "ADMIN")
    })


# --- PROCESAR ACTUALIZACIÓN DESDE LA VISTA DE GESTIÓN ERP ---
@router.post("/actualizar-gestion/{id}")
async def actualizar_gestion_envio(id: int, request: Request, db: Session = Depends(get_db)):
    try:
        form = await request.form()
        envio = db.query(Envio).filter(Envio.envio_id == id).first()

        if not envio:
            return JSONResponse(status_code=404, content={"message": "Envío no encontrado"})

        dir_rec = form.get("dir_rec")
        dir_ent = form.get("dir_ent")
        if envio.lugar_recogida and dir_rec:
            envio.lugar_recogida.direccion = dir_rec
        if envio.lugar_entrega and dir_ent:
            envio.lugar_entrega.direccion = dir_ent

        nuevo_estado = form.get("nuevo_estado", "").strip()
        comentario   = form.get("comentario", "")

        if nuevo_estado:
            if nuevo_estado == "Entregado":
                confirmacion_pago = form.get("cobro_ok")
                if envio.es_cod and not confirmacion_pago:
                    print(f"Alerta: Intento de entrega sin confirmar cobro en Guía {envio.numero_guia}")
            envio.estado = nuevo_estado
            print(f"Novedad en Guía {envio.numero_guia}: {nuevo_estado} - {comentario}")

        db.commit()
        return RedirectResponse(url=f"/envios/gestion/{id}?success=true", status_code=303)

    except Exception as e:
        db.rollback()
        print(f"Error al actualizar gestión: {e}")
        return RedirectResponse(url=f"/envios/gestion/{id}?error=true", status_code=303)

# --- FIN DEL CONTROLADOR DE ENVÍOS ---