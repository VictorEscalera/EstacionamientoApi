from flask import Flask, jsonify, request
from flask_cors import CORS
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError
import uuid
from datetime import datetime
import pytz
import os
import bcrypt

app = Flask(__name__)
CORS(app)

# =========================
# CONFIGURACIÓN DE MONGODB
# =========================
MONGO_URI = os.environ.get("MONGO_URI")

cliente = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = cliente["Estacionamiento"]

usuarios = db["usuarios"]
entrada = db["entrada"]

# 🌎 Zona horaria México
zona_mx = pytz.timezone('America/Mexico_City')

try:
    usuarios.create_index("correo", unique=True)
    print("Conexión a MongoDB exitosa ✅")
except Exception as e:
    print(f"Aviso: Error de conexión inicial: {e}")

# =========================
# RUTAS
# =========================

@app.route("/", methods=["GET"])
def inicio():
    return jsonify({"mensaje": "API funcionando 🔥"})

# --- REGISTRO ---
@app.route("/usuarios", methods=["POST"])
def crear_usuario():
    try:
        datos = request.json
        nombre = datos.get("nombre")
        correo = datos.get("correo")
        password = datos.get("password")
        rol = datos.get("rol", "usuario")

        if not nombre or not correo or not password:
            return jsonify({"success": False, "mensaje": "Faltan datos"}), 400

        if usuarios.find_one({"correo": correo}):
            return jsonify({"success": False, "mensaje": "El correo ya existe"}), 409

        nuevo_usuario = {
            "nombre": nombre,
            "correo": correo,
            "password": password,
            "rol": rol,
            "fecha_registro": datetime.now(zona_mx)
        }

        usuarios.insert_one(nuevo_usuario)
        return jsonify({"success": True, "mensaje": "Usuario creado"}), 201

    except Exception as e:
        return jsonify({"success": False, "mensaje": str(e)}), 500

# --- LOGIN ---
@app.route("/login", methods=["POST"])
def login():
    try:
        datos = request.json
        correo = datos.get("correo")
        password = datos.get("password")

        usuario = usuarios.find_one({"correo": correo, "password": password})

        if usuario:
            return jsonify({
                "success": True,
                "usuario": {
                    "_id": str(usuario["_id"]),
                    "nombre": usuario["nombre"],
                    "correo": usuario["correo"],
                    "rol": usuario.get("rol", "usuario")
                }
            })

        return jsonify({"success": False, "mensaje": "Credenciales incorrectas"}), 401

    except Exception:
        return jsonify({"success": False, "mensaje": "Error servidor"}), 500

# --- CREAR QR ---
@app.route("/crear-qr", methods=["POST"])
def crear_qr():
    datos = request.json
    placa = datos.get("placa", "N/A")

    token = str(uuid.uuid4())

    hora_actual = datetime.now(zona_mx)

    nuevo = {
        "qrToken": token,
        "placa": placa,
        "horaEntrada": hora_actual,
        "horaSalida": None,
        "estado": "dentro",
        "tipo": "app"
    }

    entrada.insert_one(nuevo)

    return jsonify({
        "success": True,
        "qrToken": token,
        "horaEntrada": hora_actual.isoformat()
    })

# --- SALIDA ---
@app.route("/salida", methods=["POST"])
def salida():
    datos = request.json
    token = datos.get("qrToken")

    registro = entrada.find_one({"qrToken": token, "estado": "dentro"})

    if not registro:
        return jsonify({"success": False, "mensaje": "No encontrado"}), 404

    hora_salida = datetime.now(zona_mx)

    minutos = (hora_salida - registro["horaEntrada"]).total_seconds() / 60
    precio = round(minutos * 0.5, 2)

    entrada.update_one(
        {"_id": registro["_id"]},
        {"$set": {
            "horaSalida": hora_salida,
            "estado": "salida",
            "precio": precio
        }}
    )

    return jsonify({
        "success": True,
        "tiempo": minutos,
        "precio": precio,
        "horaSalida": hora_salida.isoformat()
    })

# --- VALIDAR QR ---
@app.route("/validar-qr", methods=["POST"])
def validar_qr():
    datos = request.json
    token = datos.get("qrToken")

    registro = entrada.find_one({"qrToken": token})

    if not registro:
        return jsonify({"success": False, "mensaje": "QR no válido"}), 404

    return jsonify({
        "success": True,
        "data": {
            "id": str(registro["_id"]),
            "placa": registro.get("placa"),
            "estado": registro.get("estado"),
            "horaEntrada": registro.get("horaEntrada").isoformat()
        }
    })

# --- STATS ---
@app.route("/stats", methods=["GET"])
def obtener_stats():
    try:
        total = 10
        ocupados = entrada.count_documents({"estado": "dentro"})
        disponibles = total - ocupados

        return jsonify({
            "totalSpaces": total,
            "occupiedSpaces": ocupados,
            "availableSpaces": disponibles,
            "dailyIncome": 0
        })

    except Exception as e:
        return jsonify({"success": False, "mensaje": str(e)}), 500

# --- VEHÍCULOS ---
@app.route("/vehicles", methods=["GET"])
def obtener_vehiculos():
    try:
        lista = list(entrada.find().sort("horaEntrada", -1).limit(20))

        for v in lista:
            v["id"] = str(v["_id"])
            v["plate"] = v.get("placa", "S/N")
            v["entryTime"] = v.get("horaEntrada").isoformat() if v.get("horaEntrada") else None
            v["exitTime"] = v.get("horaSalida").isoformat() if v.get("horaSalida") else None
            v["status"] = "Dentro" if v.get("estado") == "dentro" else "Salida"
            del v["_id"]

        return jsonify(lista)

    except Exception:
        return jsonify([])

# --- ALERTAS ---
@app.route("/alerts", methods=["GET"])
def obtener_alertas():
    return jsonify([])

# --- ENTRADA MANUAL ---
@app.route("/entrada-manual", methods=["POST"])
def entrada_manual():
    datos = request.json
    placa = datos.get("placa")

    if not placa:
        return jsonify({"success": False, "mensaje": "Placa requerida"}), 400

    hora_actual = datetime.now(zona_mx)

    nuevo = {
        "qrToken": None,
        "placa": placa,
        "horaEntrada": hora_actual,
        "horaSalida": None,
        "estado": "dentro",
        "tipo": "manual"
    }

    resultado = entrada.insert_one(nuevo)

    return jsonify({
        "success": True,
        "id": str(resultado.inserted_id),
        "placa": placa,
        "horaEntrada": hora_actual.isoformat()
    })

# =========================
# RUN
# =========================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)