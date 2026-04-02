from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse, HTMLResponse, StreamingResponse, JSONResponse
from sqlalchemy.orm import Session, joinedload
from datetime import datetime
from decimal import Decimal
from typing import Optional
import random
import io
import pandas as pd

# Librería para el Mapa (Geocoding)
from geopy.geocoders import Nominatim

from app.config.database import get_db
from app.models.Envio import Envio
from app.models.Lugar import Lugar
from app.models.Usuario import Usuario
from app.security.SecurityConfig import get_current_user, require_admin, require_admin_or_mensajero
import app.repositories.EnvioRepository as envio_repo
import app.repositories.UsuarioRepository as usuario_repo
import app.repositories.VehiculoRepository as vehiculo_repo
import app.repositories.TarifaRepository as tarifa_repo
import app.repositories.RutaRepository as ruta_repo
import app.repositories.LugarRepository as lugar_repo
from app.config.templates import templates

router = APIRouter(prefix="/envios", tags=["Envíos"])

# --- FUNCIÓN AUXILIAR GPS ---
def obtener_coordenadas(direccion, ciudad):
    try:
        geolocator = Nominatim(user_agent="enviexpress_bogota_v2")
        query = f"{direccion}, {ciudad}, Colombia"
        location = geolocator.geocode(query, timeout=10)
        if location:
            return location.latitude, location.longitude
    except Exception as e:
        print(f"Log Error GPS: {e}")
    return None, None

# --- LISTADO PRINCIPAL ---
@router.get("/")
def listar(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    query = db.query(Envio).options(
        joinedload(Envio.cliente),
        joinedload(Envio.mensajero),
        joinedload(Envio.tarifa),
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega)
    )

    if current_user.rol == "ADMIN":
        envios = query.all()
    elif current_user.rol == "CLIENTE":
        envios = query.filter(Envio.usuario_cliente_id == current_user.id_usuario).all()
    elif current_user.rol == "MENSAJERO":
        envios = query.filter(Envio.usuario_mensajero_id == current_user.id_usuario).all()
    else:
        envios = []

    mensajeros = db.query(Usuario).filter(Usuario.rol == "MENSAJERO").all()
    
    return templates.TemplateResponse("envios.html", {
        "request": request,
        "envios": envios,
        "mensajeros": mensajeros,
        "rol": current_user.rol
    })

# --- REPORTES (EXCEL Y PDF REAL DESCARGABLE) ---
@router.get("/reporte")
async def generar_reporte_envios(
    request: Request,
    formato: str, 
    ids: Optional[str] = Query(None), 
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    require_admin(current_user)
    
    # 1. Filtro de IDs
    lista_ids = [int(i) for i in ids.split(",")] if ids else None
    
    # 2. Consulta con relaciones cargadas
    query = db.query(Envio).options(
        joinedload(Envio.cliente),
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega)
    )
    if lista_ids:
        query = query.filter(Envio.envio_id.in_(lista_ids))
    
    registros = query.all()
    fecha_hoy = datetime.now()

    # --- EXPORTAR A EXCEL ---
    if formato == "excel":
        data = []
        for e in registros:
            data.append({
                "Guía": e.numero_guia,
                "Cliente": f"{e.cliente.nombre} {e.cliente.apellido}" if e.cliente else "N/A",
                "Origen": e.lugar_recogida.direccion if e.lugar_recogida else "N/A",
                "Destino": e.lugar_entrega.direccion if e.lugar_entrega else "N/A",
                "Peso (kg)": float(e.peso),
                "Costo ($)": float(e.costo_envio),
                "Estado": e.estado.replace('_', ' '),
                "Fecha": e.fecha_creacion.strftime("%d/%m/%Y")
            })
        
        df = pd.DataFrame(data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Reporte Envíos')
        
        output.seek(0)
        filename = f"Reporte_Envios_{fecha_hoy.strftime('%Y%m%d_%H%M')}.xlsx"
        return StreamingResponse(
            output, 
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    # --- EXPORTAR A PDF (BINARIO REAL) ---
    elif formato == "pdf":
        from xhtml2pdf import pisa
        
        total_costos = sum(e.costo_envio for e in registros) if registros else 0
        
        # Renderizamos el HTML como string
        html_content = templates.get_template("reporte-envios.html").render({
            "request": request,
            "envios": registros,
            "total": len(registros),
            "total_costos": total_costos,
            "fecha": fecha_hoy.strftime("%d/%m/%Y %H:%M")
        })

        # Creamos el buffer para el PDF binario
        pdf_buffer = io.BytesIO()
        pisa_status = pisa.CreatePDF(io.StringIO(html_content), dest=pdf_buffer)

        if pisa_status.err:
            return JSONResponse(content={"error": "No se pudo generar el PDF"}, status_code=500)

        pdf_buffer.seek(0)
        filename = f"Reporte_Envios_{fecha_hoy.strftime('%Y%m%d_%H%M')}.pdf"

        return StreamingResponse(
            pdf_buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    raise HTTPException(status_code=400, detail="Formato no soportado")

@router.get("/reporte-usuarios")
async def generar_reporte_usuarios(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    require_admin(current_user)
    usuarios = db.query(Usuario).all()
    
    return templates.TemplateResponse("reporte-usuarios.html", {
        "request": request,
        "usuarios": usuarios,
        "total": len(usuarios),
        "fecha": datetime.now().strftime("%d/%m/%Y %H:%M")
    })

# --- VISTA MAPA OPERATIVO ---
@router.get("/mapa-operativo")
def mapa_completo(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_admin_or_mensajero(current_user)
    envios = db.query(Envio).options(
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega)
    ).all()
    mensajeros = db.query(Usuario).filter(Usuario.rol == "MENSAJERO").all()
    
    return templates.TemplateResponse("mapa-operaciones.html", {
        "request": request, "envios": envios, "mensajeros": mensajeros
    })

# --- FORMULARIO NUEVO ---
@router.get("/nuevo")
def nuevo(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    datos = _cargar_datos_formulario(db)
    return templates.TemplateResponse("form-envio.html", {
        "request": request, "envio": None, "rol": current_user.rol, **datos
    })

# --- GUARDAR / ACTUALIZAR ---
@router.post("/guardar")
async def guardar(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    form = await request.form()
    es_admin = current_user.rol == "ADMIN"
    envio_id = form.get("envio_id")

    if envio_id and envio_id.strip():
        envio = envio_repo.find_by_id(db, int(envio_id))
        if not envio: raise HTTPException(status_code=404, detail="No encontrado")
    else:
        envio = Envio()
        envio.fecha_creacion = datetime.now()
        envio.estado = "Registrado"
        envio.numero_guia = f"ENV{random.randint(0, 999999):06d}"
        if not es_admin: envio.usuario_cliente_id = current_user.id_usuario

    if es_admin and form.get("cliente_id"):
        envio.usuario_cliente_id = int(form.get("cliente_id"))
    
    if form.get("mensajero_id"):
        envio.usuario_mensajero_id = int(form.get("mensajero_id"))

    for tipo in ["recogida", "entrega"]:
        ciudad = form.get(f"ciudad_{tipo}", "")
        depto = form.get(f"depto_{tipo}", "")
        direccion = form.get(f"direccion_{tipo}", "").strip()
        
        if direccion:
            lat, lon = obtener_coordenadas(direccion, ciudad)
            lugar = Lugar(
                direccion=direccion,
                ciudad=f"{ciudad} ({depto})",
                referencia=f"Localidad: {form.get(f'localidad_{tipo}','')} | Tel: {form.get(f'telefono_{tipo}','')}",
                latitud=lat, longitud=lon
            )
            lugar_repo.save(db, lugar)
            if tipo == "recogida": envio.lugar_recogida_id = lugar.lugar_id
            else: envio.lugar_entrega_id = lugar.lugar_id

    envio.peso = Decimal(form.get("peso", "1.0"))
    envio.tipo_servicio = form.get("tipo_servicio", "BASICA")
    envio.instrucciones = f"CONTENIDO: {form.get('descripcion')} | NOTAS: {form.get('instrucciones')}"

    if form.get("tarifa_id"):
        tarifa = tarifa_repo.find_by_id(db, int(form.get("tarifa_id")))
        if tarifa:
            envio.tarifa_id = tarifa.id
            envio.costo_envio = tarifa.precio_kg * envio.peso
            if envio.tipo_servicio == "EXPRESS": envio.costo_envio *= Decimal("1.5")

    if es_admin:
        if form.get("vehiculo_id"): envio.vehiculo_id = int(form.get("vehiculo_id"))
        if form.get("estado"): envio.estado = form.get("estado")

    envio_repo.save(db, envio)
    return RedirectResponse(url="/envios", status_code=302)

# --- ACCIONES: EDITAR, DETALLE, IMPRIMIR ---
@router.get("/editar/{id}")
def editar(id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    envio = envio_repo.find_by_id(db, id)
    if not envio: raise HTTPException(status_code=404, detail="No encontrado")
    datos = _cargar_datos_formulario(db)
    return templates.TemplateResponse("form-envio.html", {
        "request": request, "envio": envio, "rol": current_user.rol, **datos
    })

@router.get("/imprimir/{id}")
def imprimir_guia(id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    envio = envio_repo.find_by_id(db, id)
    if not envio: raise HTTPException(status_code=404, detail="No encontrado")
    return templates.TemplateResponse("formato-guia.html", {"request": request, "envio": envio})

@router.get("/detalle/{id}")
def detalle(id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    envio = envio_repo.find_by_id(db, id)
    if not envio: raise HTTPException(status_code=404, detail="No encontrado")
    return templates.TemplateResponse("detalle-envio.html", {"request": request, "envio": envio})

# --- ELIMINACIÓN SEGURA ---
@router.get("/eliminar/{id}")
def eliminar(id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_admin(current_user)
    try:
        envio = envio_repo.find_by_id(db, id)
        if not envio: return RedirectResponse(url="/envios?error=no_encontrado", status_code=303)
        from app.models.Seguimiento import Seguimiento 
        db.query(Seguimiento).filter(Seguimiento.envio_id == id).delete()
        db.delete(envio)
        db.commit() 
        return RedirectResponse(url="/envios", status_code=303)
    except Exception as e:
        db.rollback() 
        return RedirectResponse(url="/envios?error=restriccion_db", status_code=303)

# --- FUNCIONES DE APOYO ---
def _cargar_datos_formulario(db):
    return {
        "clientes": usuario_repo.find_by_rol(db, "CLIENTE"),
        "mensajeros": usuario_repo.find_by_rol(db, "MENSAJERO"),
        "vehiculos": vehiculo_repo.find_all(db),
        "tarifas": tarifa_repo.find_all(db),
        "rutas": ruta_repo.find_all(db),
        "estados": ["Registrado", "En_Bodega", "En_Ruta", "En_Destino", "Entregado", "Fallido"]
    }

@router.post("/planificar-ruta", response_class=HTMLResponse)
@router.get("/planificar-ruta", response_class=HTMLResponse)
async def planificar_ruta(request: Request, db: Session = Depends(get_db)):
    envios = db.query(Envio).options(
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega)
    ).filter(Envio.usuario_mensajero_id == None).all()
    mensajeros = db.query(Usuario).filter(Usuario.rol == "MENSAJERO").all()
    rutas_activas = db.query(Usuario).join(Envio, Envio.usuario_mensajero_id == Usuario.id_usuario)\
        .filter(Envio.estado == 'En_Ruta').distinct().all()
    return templates.TemplateResponse("mapa-operaciones.html", {
        "request": request, "envios": envios, "mensajeros": mensajeros, "rutas_activas": rutas_activas
    })

@router.get("/ver-ruta/{id_mensajero}", response_class=HTMLResponse)
async def ver_ruta_detalle(id_mensajero: int, request: Request, db: Session = Depends(get_db)):
    mensajero = db.query(Usuario).filter(Usuario.id_usuario == id_mensajero).first()
    envios = db.query(Envio).options(
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega),
        joinedload(Envio.cliente)
    ).filter(Envio.usuario_mensajero_id == id_mensajero, Envio.estado == 'En_Ruta').all()
    return templates.TemplateResponse("detalle-ruta-mapa.html", {
        "request": request, "envios": envios, "mensajero": mensajero
    })